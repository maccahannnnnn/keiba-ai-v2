from dataclasses import dataclass

from config import ANALYSIS_WEIGHTS, PAST_RUN_LIMIT, SCORE_ITEM_WEIGHT_KEYS
from analyzer.lap_analyzer import LapAnalysis, lap_score_detail
from analyzer.opponent_analyzer import OpponentEvaluation
from analyzer.pace_analyzer import PaceAnalysisResult, pace_score_detail
from analyzer.schemas import PastRace, ScoreDetail, TodayEntry
from analyzer.track_bias_analyzer import TrackBiasAnalysis
from knowledge.bloodline_profiles import analyze_bloodline
from knowledge.course_profiles import get_course_profile


SCORE_ITEM_NAMES = [
    "過去走分析",
    "相手関係",
    "通過順・脚質",
    "距離適性",
    "馬場",
    "血統",
    "馬体重",
    "展開予想",
    "ラップ適性",
]
"""0〜100点で評価する分析項目です。"""


@dataclass
class ScoreResult:
    """1頭分のスコア計算結果です。"""

    item_scores: dict[str, ScoreDetail]
    total_score: float
    in_the_money_score: float


def calculate_scores(
    entry: TodayEntry,
    past_races: list[PastRace],
    all_entries: list[TodayEntry],
    expected_pace: str,
    pace_analysis: PaceAnalysisResult,
    opponent_analysis: OpponentEvaluation,
    track_bias_analysis: TrackBiasAnalysis,
    lap_analysis: LapAnalysis,
) -> ScoreResult:
    """1頭分の項目別スコア、総合評価点、3着内率の仮スコアを計算します。"""

    positions = recent_positions(entry, past_races)

    item_scores = {
        "過去走分析": score_past_runs(positions),
        "相手関係": score_opponent_level(opponent_analysis),
        "通過順・脚質": score_running_style(entry, past_races),
        "距離適性": score_distance(entry, past_races),
        "馬場": score_track(entry, past_races, track_bias_analysis),
        "血統": score_bloodline(entry),
        "馬体重": score_body_weight(entry, past_races),
        "展開予想": pace_score_detail(entry, pace_analysis),
        "ラップ適性": lap_score_detail(entry, lap_analysis),
    }
    item_scores = clear_report_reasons(item_scores)

    total_score = weighted_average(item_scores)
    in_the_money_score = calculate_in_the_money_score(positions)

    return ScoreResult(
        item_scores=item_scores,
        total_score=total_score,
        in_the_money_score=in_the_money_score,
    )


def clear_report_reasons(item_scores: dict[str, ScoreDetail]) -> dict[str, ScoreDetail]:
    """理由文は Explain Engine が管理するため、点数計算側からは返しません。"""

    for detail in item_scores.values():
        detail.reason = ""
    return item_scores


def score_past_runs(positions: list[int]) -> ScoreDetail:
    """過去走の着順が安定しているほど高く評価します。"""

    if not positions:
        return ScoreDetail(40, "過去走データがないため低めの仮評価")

    average_position = sum(positions) / len(positions)
    top3_count = sum(1 for position in positions if position <= 3)
    bad_count = sum(1 for position in positions if position >= 8)

    score = 100 - (average_position - 1) * 9 + top3_count * 4 - bad_count * 5
    reason = f"平均{average_position:.1f}着、3着内{top3_count}回、大敗{bad_count}回"
    return ScoreDetail(clamp(score), reason)


def score_opponent_level(opponent_analysis: OpponentEvaluation) -> ScoreDetail:
    """相手関係評価エンジンの結果をスコアへ反映します。"""

    reason = (
        f"相手レベル{opponent_analysis.score:.1f}点 / "
        f"平均{opponent_analysis.average_level:.1f}点 / "
        f"最高{opponent_analysis.highest_level}点 / "
        f"直近{opponent_analysis.latest_level}点 / "
        f"推移{opponent_analysis.trend}"
    )
    return ScoreDetail(clamp(opponent_analysis.score), reason)


def score_running_style(entry: TodayEntry, past_races: list[PastRace]) -> ScoreDetail:
    """脚質と過去の走り方の一致度を見ます。"""

    if not past_races:
        base_scores = {"逃げ": 65, "先行": 70, "差し": 62, "追込": 55}
        score = base_scores.get(entry.running_style, 55)
        return ScoreDetail(score, f"過去通過順がないため、入力脚質{entry.running_style}で仮評価")

    from collections import Counter

    style_counts = Counter(race.running_style for race in past_races)
    main_style = style_counts.most_common(1)[0][0]
    score = 78 if main_style == entry.running_style else 58
    reason = f"過去の主脚質は{main_style}、今回入力は{entry.running_style}"
    return ScoreDetail(score, reason)


def score_distance(entry: TodayEntry, past_races: list[PastRace]) -> ScoreDetail:
    """今回の距離と近い距離で好走しているかを見ます。"""

    course_profile = get_course_profile(entry.racecourse, entry.surface, entry.distance)
    bloodline_analysis = analyze_bloodline(
        entry.sire,
        entry.dam_sire,
        entry.surface,
        entry.distance,
        entry.track_condition,
    )

    if not past_races:
        note_bonus = 12 if contains_positive_word(entry.bloodline_note) else 0
        course_bonus = 5 if entry.running_style in course_profile.favorable_styles else 0
        score = 50 + note_bonus + course_bonus + bloodline_analysis.score_bonus
        return ScoreDetail(clamp(score), "過去距離データがないため血統辞書・血統メモ・コース辞書で簡易評価")

    same_distance = [race for race in past_races if race.distance == entry.distance]
    near_distance = [race for race in past_races if abs(race.distance - entry.distance) <= 200]
    good_near = sum(1 for race in near_distance if race.finish_position <= 3)

    score = 45 + len(same_distance) * 8 + good_near * 10
    if entry.running_style in course_profile.favorable_styles:
        score += 5
        reason = f"同距離{len(same_distance)}走、近い距離で3着内{good_near}回、コース有利脚質"
    else:
        reason = f"同距離{len(same_distance)}走、近い距離で3着内{good_near}回"
    if bloodline_analysis.score_bonus:
        score += bloodline_analysis.score_bonus
        reason += "、血統辞書で条件適性を加点"
    return ScoreDetail(clamp(score), reason)


def score_track(
    entry: TodayEntry,
    past_races: list[PastRace],
    track_bias_analysis: TrackBiasAnalysis,
) -> ScoreDetail:
    """当日の馬場状態と血統メモから馬場適性を見ます。"""

    course_profile = get_course_profile(entry.racecourse, entry.surface, entry.distance)
    bloodline_analysis = analyze_bloodline(
        entry.sire,
        entry.dam_sire,
        entry.surface,
        entry.distance,
        entry.track_condition,
    )
    same_track = [race for race in past_races if race.track_condition == entry.track_condition]
    good_same_track = sum(1 for race in same_track if race.finish_position <= 3)

    score = 50 + good_same_track * 10
    reason_parts = [f"{entry.track_condition}馬場で3着内{good_same_track}回"]

    if entry.track_condition in entry.bloodline_note or contains_positive_word(entry.bloodline_note):
        score += 12
        reason_parts.append("血統メモにプラス材料")
    if contains_negative_word(entry.bloodline_note):
        score -= 10
        reason_parts.append("血統メモに不安材料")
    if entry.running_style in course_profile.favorable_styles:
        score += 5
        reason_parts.append("コース有利脚質")
    if bloodline_analysis.score_bonus:
        score += min(10, bloodline_analysis.score_bonus)
        reason_parts.append("血統辞書で馬場・条件適性を加点")

    bias_evaluation = track_bias_analysis.horse_evaluations.get(entry.horse_name)
    if bias_evaluation:
        if bias_evaluation.score >= 80:
            score += 12
            reason_parts.append("馬場バイアスに強く合う")
        elif bias_evaluation.score >= 70:
            score += 7
            reason_parts.append("馬場バイアスに合う")
        elif bias_evaluation.score < 50:
            score -= 6
            reason_parts.append("馬場バイアスとは合いにくい")
        reason_parts.append(f"バイアス理由: {bias_evaluation.reason}")

    return ScoreDetail(clamp(score), "、".join(reason_parts))


def score_bloodline(entry: TodayEntry) -> ScoreDetail:
    """血統辞書と血統メモを使って点数化します。"""

    analysis = analyze_bloodline(
        entry.sire,
        entry.dam_sire,
        entry.surface,
        entry.distance,
        entry.track_condition,
    )

    score = 55 + analysis.score_bonus
    if contains_positive_word(entry.bloodline_note):
        score += 18
    if contains_negative_word(entry.bloodline_note):
        score -= 18

    note = entry.bloodline_note if entry.bloodline_note else "血統メモなし"
    reason = f"{analysis.reason} / {note}"
    return ScoreDetail(clamp(score), reason)


def score_body_weight(entry: TodayEntry, past_races: list[PastRace]) -> ScoreDetail:
    """馬体重と増減を見ます。大きすぎる増減は少し下げます。"""

    score = 70
    reason_parts = [f"今回{entry.body_weight}kg、増減{entry.body_weight_diff:+}kg"]

    if abs(entry.body_weight_diff) <= 6:
        score += 8
        reason_parts.append("増減が安定")
    elif abs(entry.body_weight_diff) <= 12:
        reason_parts.append("増減は許容範囲")
    else:
        score -= 18
        reason_parts.append("増減が大きい")

    if past_races:
        average_weight = sum(race.body_weight for race in past_races) / len(past_races)
        difference = entry.body_weight - average_weight
        reason_parts.append(f"過去平均比{difference:+.1f}kg")
        if abs(difference) > 12:
            score -= 8

    return ScoreDetail(clamp(score), "、".join(reason_parts))


def calculate_in_the_money_score(positions: list[int]) -> float:
    """3着内率を0〜100点の仮スコアにします。"""

    if not positions:
        return 0.0

    top3_count = sum(1 for position in positions if position <= 3)
    return round(top3_count / len(positions) * 100, 1)


def weighted_average(item_scores: dict[str, ScoreDetail]) -> float:
    """項目別スコアから総合評価点を作ります。

    重みは config.py の ANALYSIS_WEIGHTS を参照します。
    """

    total_weight = 0.0
    weighted_sum = 0.0

    for item_name, detail in item_scores.items():
        weight_key = SCORE_ITEM_WEIGHT_KEYS.get(item_name)
        weight = ANALYSIS_WEIGHTS.get(weight_key, 0)
        total_weight += weight
        weighted_sum += detail.score * weight

    if total_weight == 0:
        return 0.0

    return round(weighted_sum / total_weight, 1)


def recent_positions(entry: TodayEntry, past_races: list[PastRace]) -> list[int]:
    """CSVのlast_runsを優先して、評価に使う過去走着順を取り出します。"""

    if entry.last_runs.strip():
        return limit_positions(parse_last_runs(entry.last_runs))

    return [race.finish_position for race in limit_past_races(past_races)]


def parse_last_runs(value: str) -> list[int]:
    """`1-3-4-2-1` のような文字を数値リストにします。"""

    normalized = value.replace(",", "-").replace("/", "-").replace("　", "-").replace(" ", "-")
    return [int(part) for part in normalized.split("-") if part.strip().isdigit()]


def limit_positions(positions: list[int]) -> list[int]:
    """PAST_RUN_LIMITに合わせて、使う着順数を制限します。"""

    if PAST_RUN_LIMIT == "all":
        return positions
    return positions[: int(PAST_RUN_LIMIT)]


def limit_past_races(past_races: list[PastRace]) -> list[PastRace]:
    """PAST_RUN_LIMITに合わせて、使う過去レース数を制限します。"""

    if PAST_RUN_LIMIT == "all":
        return past_races
    return past_races[: int(PAST_RUN_LIMIT)]


def contains_positive_word(text: str) -> bool:
    """メモ内にプラス評価の言葉があるか調べます。"""

    return any(word in text for word in ["向き", "得意", "良い", "強い", "プラス", "歓迎", "末脚"])


def contains_negative_word(text: str) -> bool:
    """メモ内にマイナス評価の言葉があるか調べます。"""

    return any(word in text for word in ["不安", "割引", "苦手", "マイナス", "待ち"])


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    """点数が0〜100点の範囲に収まるようにします。"""

    return round(max(minimum, min(maximum, value)), 1)
