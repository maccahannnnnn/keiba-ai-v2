from collections import Counter
from dataclasses import dataclass

from analyzer.schemas import ScoreDetail, TodayEntry
from knowledge.course_profiles import CourseProfile, get_course_profile


RUNNING_STYLES = ["逃げ", "先行", "差し", "追込"]
"""このAIで扱う基本脚質です。"""


@dataclass
class HorsePaceEvaluation:
    """1頭分の展開評価です。"""

    horse_number: int
    horse_name: str
    running_style: str
    score: float
    reason: str


@dataclass
class PaceAnalysisResult:
    """レース全体の展開予想結果です。"""

    course_profile: CourseProfile
    style_counts: dict[str, int]
    pace: str
    favorable_styles: list[str]
    pace_favorable_styles: list[str]
    reason: str
    course_impact: str
    horse_evaluations: dict[str, HorsePaceEvaluation]


def analyze_pace(entries: list[TodayEntry]) -> PaceAnalysisResult:
    """出走馬全体から展開を予想します。

    今は機械学習を使わず、脚質の頭数からルールベースで判断します。
    将来はここにラップ分析、コース形態、枠順、騎手傾向などを追加できます。
    """

    style_counts = count_running_styles(entries)
    course_profile = get_course_profile(
        entries[0].racecourse,
        entries[0].surface,
        entries[0].distance,
    )
    pace, pace_reason = estimate_pace(style_counts)
    pace_favorable_styles = decide_favorable_styles(pace, style_counts)
    favorable_styles = merge_favorable_styles(pace_favorable_styles, course_profile.favorable_styles)
    course_impact = describe_course_impact(course_profile, pace, favorable_styles)

    horse_evaluations: dict[str, HorsePaceEvaluation] = {}
    for entry in entries:
        evaluation = evaluate_horse_pace(
            entry,
            pace,
            favorable_styles,
            pace_favorable_styles,
            course_profile,
            style_counts,
        )
        horse_evaluations[entry.horse_name] = evaluation

    return PaceAnalysisResult(
        course_profile=course_profile,
        style_counts=style_counts,
        pace=pace,
        favorable_styles=favorable_styles,
        pace_favorable_styles=pace_favorable_styles,
        reason=pace_reason,
        course_impact=course_impact,
        horse_evaluations=horse_evaluations,
    )


def count_running_styles(entries: list[TodayEntry]) -> dict[str, int]:
    """逃げ・先行・差し・追込の頭数を数えます。"""

    counter = Counter(classify_running_style(entry.running_style) for entry in entries)
    return {style: counter.get(style, 0) for style in RUNNING_STYLES}


def classify_running_style(style: str) -> str:
    """入力された脚質を、基本4分類にそろえます。"""

    cleaned = style.strip()
    if cleaned in RUNNING_STYLES:
        return cleaned

    # 手入力で少し表記が揺れても、なるべく分類できるようにします。
    if "逃" in cleaned:
        return "逃げ"
    if "先" in cleaned:
        return "先行"
    if "差" in cleaned:
        return "差し"
    if "追" in cleaned:
        return "追込"

    return "差し"


def estimate_pace(style_counts: dict[str, int]) -> tuple[str, str]:
    """逃げ馬と先行馬の数から、スロー・平均・ハイを推定します。"""

    escape_count = style_counts["逃げ"]
    front_count = style_counts["逃げ"] + style_counts["先行"]

    if escape_count >= 2 or front_count >= 5:
        return "ハイ", f"逃げ{escape_count}頭、逃げ先行{front_count}頭で前が速くなりやすい"
    if escape_count == 0 and front_count <= 2:
        return "スロー", f"逃げ{escape_count}頭、逃げ先行{front_count}頭で前が落ち着きやすい"
    if escape_count == 1 and front_count <= 3:
        return "平均", f"逃げ{escape_count}頭、逃げ先行{front_count}頭で極端な流れにはなりにくい"

    return "平均", f"逃げ{escape_count}頭、逃げ先行{front_count}頭で標準的な流れを想定"


def decide_favorable_styles(pace: str, style_counts: dict[str, int]) -> list[str]:
    """推定ペースから、有利になりやすい脚質を決めます。"""

    if pace == "ハイ":
        return ["差し", "追込"]
    if pace == "スロー":
        return ["逃げ", "先行"]

    # 平均ペースでは、前に行ける馬と中団から差せる馬を標準的に評価します。
    if style_counts["逃げ"] + style_counts["先行"] >= 4:
        return ["差し"]
    return ["先行", "差し"]


def merge_favorable_styles(pace_styles: list[str], course_styles: list[str]) -> list[str]:
    """展開からの有利脚質と、コースからの有利脚質を合わせます。"""

    merged: list[str] = []
    for style in pace_styles + course_styles:
        if style not in merged:
            merged.append(style)
    return merged


def describe_course_impact(
    course_profile: CourseProfile,
    pace: str,
    favorable_styles: list[str],
) -> str:
    """コース特徴が展開予想にどう影響するかを説明します。"""

    styles = "・".join(favorable_styles)
    abilities = "・".join(course_profile.required_abilities)
    cautions = " / ".join(course_profile.cautions)
    return f"{course_profile.racecourse}{course_profile.surface}{course_profile.distance}mは{course_profile.summary()}。想定{pace}では{styles}を評価。必要能力は{abilities}。注意点: {cautions}"


def evaluate_horse_pace(
    entry: TodayEntry,
    pace: str,
    favorable_styles: list[str],
    pace_favorable_styles: list[str],
    course_profile: CourseProfile,
    style_counts: dict[str, int],
) -> HorsePaceEvaluation:
    """1頭ごとに展開適性を0〜100点で評価します。"""

    style = classify_running_style(entry.running_style)
    escape_count = style_counts["逃げ"]
    front_count = style_counts["逃げ"] + style_counts["先行"]

    if style in pace_favorable_styles:
        score = 82
        reason = f"想定{pace}で{style}が展開上有利"
    else:
        score = 58
        reason = f"想定{pace}では{style}に大きな展開利は少ない"

    if style in course_profile.favorable_styles:
        score += 8
        reason += "、コース辞書でも有利脚質"

    # 逃げ馬が1頭だけなら、逃げ馬は少し加点します。
    if style == "逃げ" and escape_count == 1:
        score += 8
        reason += "、単騎逃げの可能性"

    # 先行馬が多いと、前の馬には少し厳しく見ます。
    if style in {"逃げ", "先行"} and front_count >= 5:
        score -= 10
        reason += "、先行争いが厳しい可能性"

    # ハイペースの追込は届かないリスクもあるため、差しより少し控えめにします。
    if pace == "ハイ" and style == "追込":
        score -= 4
        reason += "、追込は届かないリスクも考慮"

    score = clamp(score)
    return HorsePaceEvaluation(
        horse_number=entry.horse_number,
        horse_name=entry.horse_name,
        running_style=style,
        score=score,
        reason=reason,
    )


def pace_score_detail(entry: TodayEntry, pace_analysis: PaceAnalysisResult) -> ScoreDetail:
    """score_calculator.py で使いやすい形に変換します。"""

    evaluation = pace_analysis.horse_evaluations[entry.horse_name]
    return ScoreDetail(evaluation.score, evaluation.reason)


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    """点数が0〜100点の範囲に収まるようにします。"""

    return round(max(minimum, min(maximum, value)), 1)
