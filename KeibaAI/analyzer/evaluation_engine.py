import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


@dataclass
class PredictionRecord:
    """AIが出した予想結果を1頭分だけ持つデータです。"""

    race_date: str
    racecourse: str
    race_number: int
    horse_number: int
    horse_name: str
    predicted_rank: int
    predicted_score: float
    estimated_top3_rate: float

    @property
    def race_key(self) -> tuple[str, str, int]:
        """同じレースかどうかを比較するためのキーです。"""

        return (self.race_date, self.racecourse, self.race_number)


@dataclass
class ActualResultRecord:
    """実際のレース結果を1頭分だけ持つデータです。"""

    race_date: str
    racecourse: str
    race_number: int
    horse_number: int
    horse_name: str
    actual_finish: int
    popularity: int
    win_odds: float
    time: str
    final_3f: float
    corner_positions: str

    @property
    def race_key(self) -> tuple[str, str, int]:
        """同じレースかどうかを比較するためのキーです。"""

        return (self.race_date, self.racecourse, self.race_number)


@dataclass
class HorseEvaluationRow:
    """予想と実結果を横並びで比較した1頭分の結果です。"""

    race_date: str
    racecourse: str
    race_number: int
    horse_number: int
    horse_name: str
    predicted_rank: int
    actual_finish: int
    rank_error: int
    predicted_score: float
    score_gap_from_average: float
    estimated_top3_rate: float
    popularity: int
    win_odds: float
    time: str
    final_3f: float
    corner_positions: str


@dataclass
class EvaluationSummary:
    """レース全体の検証指標をまとめた結果です。"""

    total_horses: int
    rank_match_rate: float
    top3_hit_rate: float
    average_rank_error: float
    average_score_gap: float
    rows: list[HorseEvaluationRow]


def evaluate_from_csv(prediction_csv: str, result_csv: str) -> EvaluationSummary:
    """予想CSVと実結果CSVを読み込み、検証結果を返します。"""

    predictions = load_prediction_records(prediction_csv)
    actual_results = load_actual_result_records(result_csv)
    return evaluate_predictions(predictions, actual_results)


def load_prediction_records(file_path: str) -> list[PredictionRecord]:
    """analysis_result.csv からAIの予想結果を読み込みます。"""

    records: list[PredictionRecord] = []
    for row in read_csv_rows(file_path):
        records.append(
            PredictionRecord(
                race_date=row.get("race_date", ""),
                racecourse=row.get("racecourse", ""),
                race_number=to_int(row.get("race_number")),
                horse_number=to_int(row.get("horse_number")),
                horse_name=row.get("horse_name", ""),
                predicted_rank=to_int(row.get("predicted_rank")),
                predicted_score=to_float(row.get("predicted_score")),
                estimated_top3_rate=to_float(row.get("estimated_top3_rate")),
            )
        )
    return records


def load_actual_result_records(file_path: str) -> list[ActualResultRecord]:
    """result.csv から実際の着順・人気・タイムなどを読み込みます。"""

    records: list[ActualResultRecord] = []
    for row in read_csv_rows(file_path):
        records.append(
            ActualResultRecord(
                race_date=row.get("race_date", ""),
                racecourse=row.get("racecourse", ""),
                race_number=to_int(row.get("race_number")),
                horse_number=to_int(row.get("horse_number")),
                horse_name=row.get("horse_name", ""),
                actual_finish=to_int(row.get("actual_finish")),
                popularity=to_int(row.get("popularity")),
                win_odds=to_float(row.get("win_odds")),
                time=row.get("time", ""),
                final_3f=to_float(row.get("final_3f")),
                corner_positions=row.get("corner_positions", ""),
            )
        )
    return records


def evaluate_predictions(
    predictions: list[PredictionRecord],
    actual_results: list[ActualResultRecord],
) -> EvaluationSummary:
    """予想順位と実際の着順を比較し、検証指標を計算します。"""

    actual_by_key = {
        build_horse_key(result.race_key, result.horse_number, result.horse_name): result
        for result in actual_results
    }
    average_score = mean([prediction.predicted_score for prediction in predictions]) if predictions else 0.0

    rows: list[HorseEvaluationRow] = []
    for prediction in predictions:
        actual = actual_by_key.get(
            build_horse_key(prediction.race_key, prediction.horse_number, prediction.horse_name)
        )
        if actual is None:
            continue

        rank_error = abs(prediction.predicted_rank - actual.actual_finish)
        rows.append(
            HorseEvaluationRow(
                race_date=prediction.race_date,
                racecourse=prediction.racecourse,
                race_number=prediction.race_number,
                horse_number=prediction.horse_number,
                horse_name=prediction.horse_name,
                predicted_rank=prediction.predicted_rank,
                actual_finish=actual.actual_finish,
                rank_error=rank_error,
                predicted_score=prediction.predicted_score,
                score_gap_from_average=round(prediction.predicted_score - average_score, 1),
                estimated_top3_rate=prediction.estimated_top3_rate,
                popularity=actual.popularity,
                win_odds=actual.win_odds,
                time=actual.time,
                final_3f=actual.final_3f,
                corner_positions=actual.corner_positions,
            )
        )

    return build_summary(rows)


def build_summary(rows: list[HorseEvaluationRow]) -> EvaluationSummary:
    """1頭ごとの比較結果から、全体指標を計算します。"""

    if not rows:
        return EvaluationSummary(
            total_horses=0,
            rank_match_rate=0.0,
            top3_hit_rate=0.0,
            average_rank_error=0.0,
            average_score_gap=0.0,
            rows=[],
        )

    rank_match_count = sum(1 for row in rows if row.predicted_rank == row.actual_finish)
    top3_hit_count = sum(1 for row in rows if row.predicted_rank <= 3 and row.actual_finish <= 3)
    rank_errors = [row.rank_error for row in rows]
    score_gaps = [abs(row.score_gap_from_average) for row in rows]

    return EvaluationSummary(
        total_horses=len(rows),
        rank_match_rate=round(rank_match_count / len(rows) * 100, 1),
        top3_hit_rate=round(top3_hit_count / len(rows) * 100, 1),
        average_rank_error=round(mean(rank_errors), 2),
        average_score_gap=round(mean(score_gaps), 2),
        rows=rows,
    )


def save_evaluation_report(summary: EvaluationSummary, file_path: str) -> str:
    """検証結果をテキストレポートとして保存します。"""

    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_evaluation_report_text(summary), encoding="utf-8")
    return str(path)


def build_evaluation_report_text(summary: EvaluationSummary) -> str:
    """検証結果を読みやすいテキストに変換します。"""

    lines = [
        "Evaluation Engine レポート",
        "",
        "=== 検証指標 ===",
        f"比較頭数: {summary.total_horses}",
        f"順位一致率: {summary.rank_match_rate:.1f}%",
        f"3着内率: {summary.top3_hit_rate:.1f}%",
        f"平均誤差: {summary.average_rank_error:.2f}",
        f"スコア平均との差: {summary.average_score_gap:.2f}",
        "",
        "=== 予想と実結果の比較 ===",
    ]

    header = [
        "馬番",
        "馬名",
        "予想順位",
        "実着順",
        "誤差",
        "人気",
        "単勝オッズ",
        "タイム",
        "上がり",
        "通過順",
        "予想スコア",
        "平均との差",
    ]
    lines.extend(format_table([header] + [row_to_table(row) for row in summary.rows]))
    return "\n".join(lines)


def row_to_table(row: HorseEvaluationRow) -> list[str]:
    """比較結果1行を、表に表示しやすい文字列へ変換します。"""

    return [
        str(row.horse_number),
        row.horse_name,
        str(row.predicted_rank),
        str(row.actual_finish),
        str(row.rank_error),
        str(row.popularity),
        f"{row.win_odds:.1f}",
        row.time,
        f"{row.final_3f:.1f}",
        row.corner_positions,
        f"{row.predicted_score:.1f}",
        f"{row.score_gap_from_average:+.1f}",
    ]


def build_horse_key(race_key: tuple[str, str, int], horse_number: int, horse_name: str) -> tuple[str, str, int, int, str]:
    """レースと馬を特定するためのキーを作ります。"""

    race_date, racecourse, race_number = race_key
    return (race_date, racecourse, race_number, horse_number, horse_name)


def read_csv_rows(file_path: str) -> list[dict[str, str]]:
    """CSVを辞書のリストとして読み込みます。"""

    with Path(file_path).open("r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def to_int(value: object) -> int:
    """空欄や不正な値でも止まらないように整数へ変換します。"""

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def to_float(value: object) -> float:
    """空欄や不正な値でも止まらないように小数へ変換します。"""

    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def format_table(rows: list[list[str]]) -> list[str]:
    """外部ライブラリを使わず、簡単なテキスト表を作ります。"""

    if not rows:
        return []

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
    """日本語を含む表でも幅が崩れにくいよう、表示幅をざっくり計算します。"""

    return sum(2 if ord(char) > 127 else 1 for char in text)


if __name__ == "__main__":
    summary = evaluate_from_csv("data/analysis_result.csv", "data/result.csv")
    output_path = save_evaluation_report(summary, "reports/evaluation_report.txt")
    print(build_evaluation_report_text(summary))
    print("")
    print(f"検証レポートを保存しました: {output_path}")
