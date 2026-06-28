from pathlib import Path

from config import ANALYSIS_CRITERIA, ANALYSIS_RULES, ANALYSIS_WEIGHTS, DESIGN_PIPELINE, WEIGHT_LABELS
from analyzer.explain_analyzer import ExplainReason
from analyzer.score_calculator import SCORE_ITEM_NAMES
from analyzer.schemas import AnalysisResult


DETAIL_COLUMNS = [
    ("past_run_analysis"),
    ("opponent_level"),
    ("running_style"),
    ("distance_fitness"),
    ("track_fitness"),
    ("pedigree"),
    ("body_weight"),
    ("pace_forecast"),
]


def build_report_text(results: list[AnalysisResult], feature_file_path: str = "") -> str:
    """分析結果を、画面表示と保存に使える文章へ変換します。"""

    lines: list[str] = []

    lines.append("中央競馬分析AI レポート")
    lines.append("")
    lines.append("設計思想: " + " → ".join(DESIGN_PIPELINE))
    lines.append("")
    lines.append("基本ルール: " + " → ".join(numbered_rules()))
    lines.append("")
    lines.append("=== 評価基準 ===")
    lines.extend(build_criteria_table())

    lines.append("")
    lines.append("=== 今回の分析重み ===")
    lines.extend(build_weight_table())

    if feature_file_path:
        lines.append("")
        lines.append("=== 特徴量保存 ===")
        lines.append(f"特徴量を保存しました: {feature_file_path}")

    lines.append("")
    lines.append("=== 展開予想エンジン ===")
    lines.extend(build_pace_analysis_section(results))

    lines.append("")
    lines.append("=== ラップ分析エンジン ===")
    lines.extend(build_lap_analysis_section(results))

    lines.append("")
    lines.append("=== 馬場バイアス評価エンジン ===")
    lines.extend(build_track_bias_section(results))

    lines.append("")
    lines.append("=== 相手関係評価エンジン ===")
    lines.extend(build_opponent_analysis_section(results))

    lines.append("")
    lines.append("=== 血統辞書分析 ===")
    lines.extend(build_bloodline_section(results))

    lines.append("")
    lines.append("=== 統合評価 ===")
    lines.extend(build_integrated_evaluation_section(results))

    lines.append("")
    lines.append(f"=== {numbered_rule(8)} ===")
    lines.extend(build_summary_table(results))

    lines.append("")
    lines.append("=== 項目別スコア表 ===")
    lines.extend(build_item_score_table(results))

    lines.append("")
    lines.append("=== Explain Engine ===")
    lines.extend(build_explain_section(results))

    lines.append("")
    lines.append("=== ①〜⑧ 分析詳細表 ===")
    for rank, result in enumerate(results, start=1):
        lines.append("")
        lines.append(f"{rank}位: {result.horse_name}")
        lines.extend(build_detail_table(result))

    lines.append("")
    lines.append(f"=== {numbered_rule(9)} ===")
    lines.extend(build_in_the_money_table(results))

    return "\n".join(lines)


def build_summary_table(results: list[AnalysisResult]) -> list[str]:
    """全頭を横並びで比較するための表を作ります。"""

    rows = [["順位", "馬番", "枠", "馬名", "評価印", "統合評価点", "3着内率仮スコア"]]

    for rank, result in enumerate(results, start=1):
        integrated = result.integrated_evaluation
        rows.append(
            [
                f"{rank}位",
                str(result.horse_number),
                str(result.frame_number),
                result.horse_name,
                integrated.label,
                f"{result.score:.1f}点",
                f"{result.in_the_money_score:.1f}点",
            ]
        )

    return format_table(rows)


def build_criteria_table() -> list[str]:
    """config.py の評価基準を、レポート用の表にします。"""

    rows = [["分析項目", "AIが見るポイント"]]

    # ANALYSIS_RULESに追加・削除があっても、ANALYSIS_CRITERIAに基準がある項目だけを表示します。
    for index, rule_name in enumerate(ANALYSIS_RULES):
        criteria = ANALYSIS_CRITERIA.get(rule_name)
        if criteria is None:
            continue
        rows.append([numbered_rule(index), " / ".join(criteria)])

    return format_table(rows)


def build_weight_table() -> list[str]:
    """config.py の ANALYSIS_WEIGHTS をレポートに表示します。"""

    rows = [["重みキー", "分析項目", "重み"]]

    for key, weight in ANALYSIS_WEIGHTS.items():
        rows.append([key, WEIGHT_LABELS.get(key, key), str(weight)])

    return format_table(rows)


def build_pace_analysis_section(results: list[AnalysisResult]) -> list[str]:
    """展開予想エンジンの結果をレポートに表示します。"""

    if not results:
        return ["出走馬データがありません。"]

    pace_analysis = results[0].pace_analysis
    lines: list[str] = []

    lines.append("脚質一覧")
    lines.extend(build_running_style_table(results))
    lines.append("")

    style_counts_text = " / ".join(
        f"{style}{count}頭" for style, count in pace_analysis.style_counts.items()
    )
    favorable_styles = "・".join(pace_analysis.favorable_styles)

    lines.append("ペース予想")
    lines.extend(
        format_table(
            [
                ["項目", "内容"],
                ["脚質頭数", style_counts_text],
                ["推定ペース", pace_analysis.pace],
                ["有利な脚質", favorable_styles],
                ["理由", pace_analysis.reason],
            ]
        )
    )
    lines.append("")

    lines.append("コース特徴")
    lines.extend(build_course_profile_table(pace_analysis))
    lines.append("")

    lines.append("各馬の展開評価")
    lines.extend(build_pace_score_table(results))
    return lines


def build_running_style_table(results: list[AnalysisResult]) -> list[str]:
    """各馬の脚質を一覧にします。"""

    rows = [["馬番", "馬名", "脚質"]]
    pace_analysis = results[0].pace_analysis

    for result in sorted(results, key=lambda item: item.horse_number):
        evaluation = pace_analysis.horse_evaluations[result.horse_name]
        rows.append([str(result.horse_number), result.horse_name, evaluation.running_style])

    return format_table(rows)


def build_course_profile_table(pace_analysis) -> list[str]:
    """コース辞書から取得した特徴を表示します。"""

    profile = pace_analysis.course_profile
    return format_table(
        [
            ["項目", "内容"],
            ["コース", f"{profile.racecourse} {profile.surface} {profile.distance}m"],
            ["コース特徴", " / ".join(profile.features)],
            ["コースから見た有利な脚質", "・".join(profile.favorable_styles)],
            ["枠順傾向", profile.frame_bias],
            ["求められる能力", "・".join(profile.required_abilities)],
            ["注意点", " / ".join(profile.cautions)],
            ["展開予想への影響", pace_analysis.course_impact],
        ]
    )


def build_pace_score_table(results: list[AnalysisResult]) -> list[str]:
    """各馬の展開評価点と理由を表示します。"""

    rows = [["馬番", "馬名", "脚質", "展開評価", "評価理由"]]
    pace_analysis = results[0].pace_analysis

    for result in sorted(results, key=lambda item: item.horse_number):
        evaluation = pace_analysis.horse_evaluations[result.horse_name]
        rows.append(
            [
                str(evaluation.horse_number),
                evaluation.horse_name,
                evaluation.running_style,
                f"{evaluation.score:.1f}点",
                evaluation.reason,
            ]
        )

    return format_table(rows)


def build_bloodline_section(results: list[AnalysisResult]) -> list[str]:
    """血統辞書をもとにした分析結果を表示します。"""

    rows = [["馬番", "馬名", "血統特徴", "今回の条件との相性", "評価理由"]]

    for result in sorted(results, key=lambda item: item.horse_number):
        analysis = result.bloodline_analysis
        rows.append(
            [
                str(result.horse_number),
                result.horse_name,
                analysis.features,
                analysis.compatibility,
                analysis.reason,
            ]
        )

    return format_table(rows)


def build_lap_analysis_section(results: list[AnalysisResult]) -> list[str]:
    """ラップ分析エンジンの結果を表示します。"""

    if not results:
        return ["出走馬データがありません。"]

    analysis = results[0].lap_analysis
    lines: list[str] = []
    front_3f = "-" if analysis.front_3f is None else f"{analysis.front_3f:.1f}秒"
    late_3f = "-" if analysis.late_3f is None else f"{analysis.late_3f:.1f}秒"
    difference = "-" if analysis.half_difference is None else f"{analysis.half_difference:+.1f}秒"

    lines.append("ラップ分析")
    lines.extend(
        format_table(
            [
                ["項目", "内容"],
                ["前半3F", front_3f],
                ["後半3F", late_3f],
                ["前後半差", difference],
                ["ペース判定", analysis.pace],
                ["レース質", analysis.race_type],
                ["有利な脚質", "・".join(analysis.favorable_styles)],
                ["評価理由", analysis.reason],
            ]
        )
    )

    lines.append("")
    lines.append("各馬のラップ適性")
    rows = [["馬番", "馬名", "脚質", "ラップ適性", "評価理由"]]

    for evaluation in sorted(analysis.horse_evaluations.values(), key=lambda item: item.horse_number):
        rows.append(
            [
                str(evaluation.horse_number),
                evaluation.horse_name,
                evaluation.running_style,
                f"{evaluation.score:.1f}点",
                evaluation.reason,
            ]
        )

    lines.extend(format_table(rows))
    return lines


def build_track_bias_section(results: list[AnalysisResult]) -> list[str]:
    """馬場バイアス評価エンジンの結果を表示します。"""

    if not results:
        return ["出走馬データがありません。"]

    analysis = results[0].track_bias_analysis
    profile = analysis.profile
    lines: list[str] = []

    lines.append("馬場バイアス")
    lines.extend(
        format_table(
            [
                ["項目", "内容"],
                ["コース", f"{profile.racecourse} {profile.surface} {profile.distance}m"],
                ["有利な脚質", "・".join(analysis.favorable_styles)],
                ["有利な枠", "・".join(analysis.favorable_frames)],
                ["時計傾向", analysis.clock_tendency],
                ["今回の展開との相性", analysis.pace_compatibility],
                ["雨の影響", profile.rain_impact],
                ["馬場悪化時の傾向", profile.deterioration_trend],
                ["評価理由", analysis.reason],
            ]
        )
    )

    lines.append("")
    lines.append("今回有利になる馬")
    rows = [["馬番", "馬名", "脚質", "枠", "バイアス評価", "評価理由"]]

    evaluations = sorted(
        analysis.horse_evaluations.values(),
        key=lambda item: item.score,
        reverse=True,
    )
    for evaluation in evaluations:
        rows.append(
            [
                str(evaluation.horse_number),
                evaluation.horse_name,
                evaluation.running_style,
                str(evaluation.frame_number),
                f"{evaluation.score:.1f}点",
                evaluation.reason,
            ]
        )

    lines.extend(format_table(rows))
    return lines


def build_opponent_analysis_section(results: list[AnalysisResult]) -> list[str]:
    """相手関係評価エンジンの結果を表示します。"""

    rows = [
        [
            "馬番",
            "馬名",
            "相手レベル",
            "平均",
            "最高",
            "直近",
            "推移",
            "今回メンバーとの比較",
            "評価理由",
        ]
    ]

    for result in sorted(results, key=lambda item: item.horse_number):
        analysis = result.opponent_analysis
        rows.append(
            [
                str(result.horse_number),
                result.horse_name,
                f"{analysis.score:.1f}点",
                f"{analysis.average_level:.1f}点",
                f"{analysis.highest_level}点",
                f"{analysis.latest_level}点",
                analysis.trend,
                analysis.member_comparison,
                analysis.reason,
            ]
        )

    return format_table(rows)


def build_integrated_evaluation_section(results: list[AnalysisResult]) -> list[str]:
    """複数条件を組み合わせた最終補正を表示します。"""

    rows = [["馬番", "馬名", "補正前", "補正", "統合評価", "評価印", "加点理由", "減点理由"]]

    for result in results:
        integrated = result.integrated_evaluation
        rows.append(
            [
                str(result.horse_number),
                result.horse_name,
                f"{integrated.base_score:.1f}点",
                f"{integrated.adjustment:+.1f}点",
                f"{integrated.final_score:.1f}点",
                integrated.label,
                " / ".join(integrated.add_reasons),
                " / ".join(integrated.deduct_reasons),
            ]
        )

    return format_table(rows)


def build_detail_table(result: AnalysisResult) -> list[str]:
    """1頭ごとの分析を、項目と内容が見やすい表にします。"""

    rows = [["分析項目", "内容"]]

    rows.append(["レース情報", result.race_info])
    rows.append(["馬番・枠番", f"{result.horse_number}番 / {result.frame_number}枠"])

    for index, attribute_name in enumerate(DETAIL_COLUMNS):
        title = numbered_rule(index)
        rows.append([title, str(getattr(result, attribute_name))])

    rows.append([numbered_rule(9), f"{result.in_the_money_rate * 100:.1f}%"])
    return format_table(rows)


def build_item_score_table(results: list[AnalysisResult]) -> list[str]:
    """各馬の項目別スコアを横並びで比較できる表にします。"""

    rows = [["馬番", "馬名"] + SCORE_ITEM_NAMES + ["補正前総合", "統合評価点", "3着内率仮スコア"]]

    for result in results:
        row = [str(result.horse_number), result.horse_name]
        for item_name in SCORE_ITEM_NAMES:
            detail = result.item_scores.get(item_name)
            row.append(f"{detail.score:.1f}" if detail else "-")
        row.append(f"{result.integrated_evaluation.base_score:.1f}")
        row.append(f"{result.score:.1f}")
        row.append(f"{result.in_the_money_score:.1f}")
        rows.append(row)

    return format_table(rows)


def build_score_reason_table(result: AnalysisResult) -> list[str]:
    """なぜその点数になったかを、項目ごとに表示します。"""

    rows = [["項目", "点数", "理由"]]

    for item_name in SCORE_ITEM_NAMES:
        detail = result.item_scores.get(item_name)
        if detail is None:
            continue
        rows.append([item_name, f"{detail.score:.1f}点", detail.reason])

    integrated = result.integrated_evaluation
    rows.append(["補正前総合", f"{integrated.base_score:.1f}点", "項目別スコアを重み付き平均で計算"])
    rows.append(
        [
            "統合評価",
            f"{integrated.final_score:.1f}点",
            f"補正{integrated.adjustment:+.1f}点 / 加点: {' / '.join(integrated.add_reasons)} / 減点: {' / '.join(integrated.deduct_reasons)}",
        ]
    )
    rows.append(["3着内率仮スコア", f"{result.in_the_money_score:.1f}点", "過去走の3着以内回数から仮計算"])
    return format_table(rows)


def build_explain_section(results: list[AnalysisResult]) -> list[str]:
    """Explain Engine が集約した加点・減点理由を表示します。"""

    lines: list[str] = []

    for rank, result in enumerate(results, start=1):
        explain = result.explain_analysis
        lines.append("")
        lines.append(f"{rank}位: {result.horse_name}")

        if explain is None:
            lines.append("Explain Engine の結果がありません。")
            continue

        lines.append("【加点理由】")
        lines.extend(build_explain_reason_table(explain.plus_reasons))
        lines.append("")
        lines.append("【減点理由】")
        lines.extend(build_explain_reason_table(explain.minus_reasons))
        lines.append("")
        lines.append("【総合評価理由】")
        lines.extend(build_overall_reason_table(explain.overall_reasons))

    return lines


def build_explain_reason_table(reasons: list[ExplainReason]) -> list[str]:
    """理由を、カテゴリ・ID・内容の表にします。"""

    rows = [["項目", "reason_id", "理由", "参考スコア"]]

    if not reasons:
        rows.append(["-", "-", "大きな理由なし", "-"])
        return format_table(rows)

    for reason in reasons:
        rows.append(
            [
                reason.category,
                reason.reason_id,
                reason.summary,
                f"{reason.score:.1f}",
            ]
        )

    return format_table(rows)


def build_overall_reason_table(reasons: list[str]) -> list[str]:
    """総合評価理由を表として表示します。"""

    rows = [["内容"]]
    if not reasons:
        rows.append(["総合評価理由なし"])
        return format_table(rows)

    for reason in reasons:
        rows.append([reason])

    return format_table(rows)


def build_in_the_money_table(results: list[AnalysisResult]) -> list[str]:
    """3着内率だけを比較する表を作ります。"""

    rows = [["順位", "馬番", "馬名", "3着内率仮スコア", "総合評価点"]]

    sorted_results = sorted(results, key=lambda result: result.in_the_money_score, reverse=True)
    for rank, result in enumerate(sorted_results, start=1):
        rows.append(
            [
                f"{rank}位",
                str(result.horse_number),
                result.horse_name,
                f"{result.in_the_money_score:.1f}点",
                f"{result.score:.1f}点",
            ]
        )

    return format_table(rows)


def format_table(rows: list[list[str]]) -> list[str]:
    """文字幅をそろえたシンプルな表を作ります。"""

    column_count = len(rows[0])
    widths = [0] * column_count

    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], display_width(cell))

    lines = []
    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    lines.append(separator)

    for row_index, row in enumerate(rows):
        padded_cells = [
            cell + " " * (widths[index] - display_width(cell))
            for index, cell in enumerate(row)
        ]
        lines.append("| " + " | ".join(padded_cells) + " |")

        # 見出し行の下に区切り線を入れると表が読みやすくなります。
        if row_index == 0:
            lines.append(separator)

    lines.append(separator)
    return lines


def display_width(text: str) -> int:
    """日本語を含む文字列の見た目の幅をざっくり計算します。"""

    width = 0
    for char in text:
        # 日本語は英数字より横幅が広いので、2文字分として数えます。
        width += 2 if ord(char) > 127 else 1
    return width


def numbered_rules() -> list[str]:
    """config.py の分析ルールに、①②③のような番号を付けます。"""

    return [numbered_rule(index) for index in range(len(ANALYSIS_RULES))]


def numbered_rule(index: int) -> str:
    """1つの分析ルールに見やすい番号を付けます。"""

    circled_numbers = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]
    prefix = circled_numbers[index] if index < len(circled_numbers) else f"{index + 1}."
    return f"{prefix}{ANALYSIS_RULES[index]}"


def save_report(file_path: str, text: str) -> None:
    """分析結果をreportsフォルダに保存します。"""

    path = Path(file_path)

    # reportsフォルダがまだ無い場合でも、自動で作成します。
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
