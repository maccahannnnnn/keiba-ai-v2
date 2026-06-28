import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


@dataclass
class ReviewInput:
    """1頭分の予想・特徴量・実際の結果をまとめたデータです。"""

    race_date: str
    racecourse: str
    race_number: int
    horse_number: int
    horse_name: str
    predicted_rank: int
    actual_finish: int
    estimated_top3_rate: float
    history_score: float
    opponent_score: float
    bloodline_score: float
    track_bias_score: float
    course_score: float


@dataclass
class ReviewResult:
    """自己採点で出した1頭分の評価結果です。"""

    horse_number: int
    horse_name: str
    predicted_rank: int
    actual_finish: int
    rank_error: int
    top3_judgement: str
    history_judgement: str
    opponent_judgement: str
    bloodline_judgement: str
    track_bias_judgement: str
    course_judgement: str
    good_reason: str
    missed_reason: str
    improvement_candidate: str


def run_self_review(
    analysis_result_csv: str = "data/analysis_result.csv",
    race_result_csv: str = "data/race_result.csv",
    feature_csv: str = "data/features.csv",
    report_path: str = "reports/review_report.txt",
) -> str:
    """予想CSVと結果CSVを比較して、自己採点レポートを保存します。"""

    report = build_self_review_report(analysis_result_csv, race_result_csv, feature_csv)
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return str(path)


def build_self_review_report(
    analysis_result_csv: str,
    race_result_csv: str,
    feature_csv: str,
) -> str:
    """Self Review Engineのレポート本文を作ります。"""

    analysis_path = Path(analysis_result_csv)
    result_path = Path(race_result_csv)
    feature_path = Path(feature_csv)

    lines = [
        "Self Review Engine レポート",
        "",
        "=== 入力ファイル ===",
        f"予想: {analysis_result_csv}",
        f"結果: {race_result_csv}",
        f"特徴量: {feature_csv}",
        "",
    ]

    if not analysis_path.exists():
        lines.append("analysis_result.csv が見つからないため、自己採点できません。")
        return "\n".join(lines)

    if not result_path.exists():
        lines.extend(
            [
                "race_result.csv が見つからないため、今回は採点を保留しました。",
                "data/race_result_template.csv を参考に data/race_result.csv を作成してください。",
                "レース結果を入力すると、予想順位・着順・各スコアの過大評価/過小評価を比較できます。",
            ]
        )
        return "\n".join(lines)

    predictions = read_csv_rows(analysis_path)
    results = read_csv_rows(result_path)
    features = read_csv_rows(feature_path) if feature_path.exists() else []
    review_inputs = build_review_inputs(predictions, results, features)

    if not review_inputs:
        lines.extend(
            [
                "予想CSVと結果CSVで一致する馬がありませんでした。",
                "analysis_result.csv と race_result.csv の horse_number が同じか確認してください。",
            ]
        )
        return "\n".join(lines)

    review_results = [review_horse(row) for row in review_inputs]
    lines.append("=== 自己採点一覧 ===")
    lines.extend(build_review_table(review_results))
    lines.append("")
    lines.append("=== AI自身の自己評価 ===")
    lines.extend(build_overall_review(review_results))
    return "\n".join(lines)


def build_review_inputs(
    predictions: list[dict[str, str]],
    actual_results: list[dict[str, str]],
    features: list[dict[str, str]],
) -> list[ReviewInput]:
    """予想・結果・特徴量を馬ごとに結合します。"""

    actual_by_key = {horse_key(row): row for row in actual_results}
    feature_by_key = {horse_key(row): row for row in features}
    rows: list[ReviewInput] = []

    for prediction in predictions:
        key = horse_key(prediction)
        actual = actual_by_key.get(key)
        if actual is None:
            continue

        feature = feature_by_key.get(key, {})
        rows.append(
            ReviewInput(
                race_date=prediction.get("race_date", ""),
                racecourse=prediction.get("racecourse", ""),
                race_number=to_int(prediction.get("race_number")),
                horse_number=to_int(prediction.get("horse_number")),
                horse_name=prediction.get("horse_name", ""),
                predicted_rank=to_int(prediction.get("predicted_rank")),
                actual_finish=to_int(actual.get("finish_position")),
                estimated_top3_rate=to_float(prediction.get("estimated_top3_rate")),
                history_score=pick_score(feature, "history_score", "past_run_score"),
                opponent_score=pick_score(feature, "opponent_score"),
                bloodline_score=pick_score(feature, "bloodline_score"),
                track_bias_score=pick_score(feature, "track_bias_score"),
                course_score=pick_score(feature, "course_score"),
            )
        )

    return rows


def review_horse(row: ReviewInput) -> ReviewResult:
    """1頭分について、一致・過大評価・過小評価を判定します。"""

    rank_error = abs(row.predicted_rank - row.actual_finish)
    good_reasons: list[str] = []
    missed_reasons: list[str] = []
    improvements: list[str] = []

    if rank_error <= 1:
        good_reasons.append("予想順位と結果順位が近い")
    elif row.predicted_rank < row.actual_finish:
        missed_reasons.append("実際の着順より高く評価した")
    else:
        missed_reasons.append("実際の着順より低く評価した")

    top3_judgement = judge_top3(row.estimated_top3_rate, row.actual_finish)
    score_judgements = {
        "history": judge_score(row.history_score, row.actual_finish),
        "opponent": judge_score(row.opponent_score, row.actual_finish),
        "bloodline": judge_score(row.bloodline_score, row.actual_finish),
        "track_bias": judge_score(row.track_bias_score, row.actual_finish),
        "course": judge_score(row.course_score, row.actual_finish),
    }

    for label, judgement in score_judgements.items():
        if judgement == "一致":
            good_reasons.append(f"{label}評価は結果と合った")
        elif judgement == "過大評価":
            missed_reasons.append(f"{label}評価を高く見すぎた")
            improvements.append(f"{label}評価の減点条件を確認")
        elif judgement == "過小評価":
            missed_reasons.append(f"{label}評価を低く見すぎた")
            improvements.append(f"{label}評価の加点条件を確認")

    if top3_judgement != "一致":
        improvements.append("3着内率の見積もりを確認")

    return ReviewResult(
        horse_number=row.horse_number,
        horse_name=row.horse_name,
        predicted_rank=row.predicted_rank,
        actual_finish=row.actual_finish,
        rank_error=rank_error,
        top3_judgement=top3_judgement,
        history_judgement=score_judgements["history"],
        opponent_judgement=score_judgements["opponent"],
        bloodline_judgement=score_judgements["bloodline"],
        track_bias_judgement=score_judgements["track_bias"],
        course_judgement=score_judgements["course"],
        good_reason=join_or_default(good_reasons, "大きな一致理由なし"),
        missed_reason=join_or_default(missed_reasons, "大きな外れ理由なし"),
        improvement_candidate=join_or_default(improvements, "現時点では大きな修正候補なし"),
    )


def judge_top3(estimated_top3_rate: float, actual_finish: int) -> str:
    """3着内率の見立てが結果と合ったか判定します。"""

    expected_top3 = estimated_top3_rate >= 50
    actual_top3 = 1 <= actual_finish <= 3
    if expected_top3 == actual_top3:
        return "一致"
    if expected_top3 and not actual_top3:
        return "過大評価"
    return "過小評価"


def judge_score(score: float, actual_finish: int) -> str:
    """各分析スコアが、実際の着順に対して高すぎたか低すぎたかを見ます。"""

    if actual_finish <= 3:
        if score >= 65:
            return "一致"
        return "過小評価"

    if actual_finish >= 8:
        if score >= 70:
            return "過大評価"
        return "一致"

    if 45 <= score <= 75:
        return "一致"
    if score > 75:
        return "過大評価"
    return "過小評価"


def build_overall_review(results: list[ReviewResult]) -> list[str]:
    """レース全体としてAIが何を良く見て、何を外したかを文章化します。"""

    lines: list[str] = []
    average_error = mean([row.rank_error for row in results])
    top3_matches = count_judgement(results, "top3_judgement", "一致")
    history_over = count_judgement(results, "history_judgement", "過大評価")
    opponent_over = count_judgement(results, "opponent_judgement", "過大評価")
    bloodline_matches = count_judgement(results, "bloodline_judgement", "一致")
    track_matches = count_judgement(results, "track_bias_judgement", "一致")

    lines.append(f"平均順位誤差は {average_error:.2f} でした。")

    if top3_matches >= len(results) / 2:
        lines.append("3着内率の見立ては一定程度合っていました。")
    else:
        lines.append("3着内率の見立ては改善余地があります。")

    if track_matches >= len(results) / 2:
        lines.append("馬場バイアス評価は比較的適切でした。")
    else:
        lines.append("馬場バイアス評価は結果とのズレが目立ちました。")

    if bloodline_matches >= len(results) / 2:
        lines.append("血統評価は結果と合う馬が多くありました。")
    else:
        lines.append("血統評価は今回の結果に対して再確認が必要です。")

    if opponent_over >= len(results) / 3:
        lines.append("相手関係を高く見すぎた馬が目立ちました。")
    if history_over >= len(results) / 3:
        lines.append("過去走評価を高く見すぎた馬が目立ちました。")

    lines.append("今回は自己採点のみで、重み変更・学習・自動補正は行っていません。")
    return lines


def build_review_table(results: list[ReviewResult]) -> list[str]:
    """自己採点結果を読みやすい表にします。"""

    rows = [
        [
            "馬番",
            "馬名",
            "予想順位",
            "結果順位",
            "誤差",
            "3着内率",
            "history",
            "opponent",
            "bloodline",
            "track_bias",
            "course",
            "外した理由",
            "良かった理由",
            "改善候補",
        ]
    ]
    for row in sorted(results, key=lambda item: item.predicted_rank):
        rows.append(
            [
                str(row.horse_number),
                row.horse_name,
                str(row.predicted_rank),
                str(row.actual_finish),
                str(row.rank_error),
                row.top3_judgement,
                row.history_judgement,
                row.opponent_judgement,
                row.bloodline_judgement,
                row.track_bias_judgement,
                row.course_judgement,
                row.missed_reason,
                row.good_reason,
                row.improvement_candidate,
            ]
        )
    return format_table(rows)


def horse_key(row: dict[str, str]) -> int:
    """Self Reviewでは、同一レース内の horse_number を照合キーにします。"""

    return to_int(row.get("horse_number"))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """CSVを辞書のリストとして読み込みます。"""

    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def pick_score(row: dict[str, str], primary_key: str, fallback_key: str = "") -> float:
    """特徴量スコアを取り出します。列がない場合は代替列を使います。"""

    if primary_key in row and row.get(primary_key, "") != "":
        return to_float(row.get(primary_key))
    if fallback_key:
        return to_float(row.get(fallback_key))
    return 0.0


def to_int(value: object) -> int:
    """空欄でも止まらないように整数へ変換します。"""

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def to_float(value: object) -> float:
    """空欄でも止まらないように小数へ変換します。"""

    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def count_judgement(results: list[ReviewResult], attribute: str, expected: str) -> int:
    """指定した判定が何件あるか数えます。"""

    return sum(1 for row in results if getattr(row, attribute) == expected)


def join_or_default(values: list[str], default: str) -> str:
    """理由が空の場合に、読みやすい初期文言を返します。"""

    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return " / ".join(unique) if unique else default


def format_table(rows: list[list[str]]) -> list[str]:
    """外部ライブラリなしで、テキスト表を作ります。"""

    widths = [0] * len(rows[0])
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], display_width(cell))

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    lines = [separator]
    for row_index, row in enumerate(rows):
        padded = [
            cell + " " * (widths[index] - display_width(cell))
            for index, cell in enumerate(row)
        ]
        lines.append("| " + " | ".join(padded) + " |")
        if row_index == 0:
            lines.append(separator)
    lines.append(separator)
    return lines


def display_width(text: str) -> int:
    """日本語を含む表が崩れにくいよう、表示幅をざっくり計算します。"""

    return sum(2 if ord(char) > 127 else 1 for char in text)


if __name__ == "__main__":
    output_path = run_self_review()
    print(Path(output_path).read_text(encoding="utf-8"))
    print("")
    print(f"自己採点レポートを保存しました: {output_path}")
