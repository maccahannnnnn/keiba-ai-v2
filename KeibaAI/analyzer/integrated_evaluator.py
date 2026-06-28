from dataclasses import dataclass

from config import ANALYSIS_WEIGHTS, INTEGRATED_RULE_WEIGHTS
from analyzer.schemas import ScoreDetail, TodayEntry


@dataclass
class IntegratedEvaluation:
    """複数の分析条件を組み合わせた最終評価です。

    ここで作る数値は、将来の機械学習に渡す特徴量としても使えるように
    「補正前の点数」「補正量」「補正後の点数」を分けて持たせています。
    """

    base_score: float
    adjustment: float
    final_score: float
    label: str
    add_reasons: list[str]
    deduct_reasons: list[str]

    def to_features(self) -> dict[str, float]:
        """将来、機械学習へ渡しやすい数値データに変換します。"""

        return {
            "integrated_base_score": self.base_score,
            "integrated_adjustment": self.adjustment,
            "integrated_final_score": self.final_score,
            "integrated_add_reason_count": float(len(self.add_reasons)),
            "integrated_deduct_reason_count": float(len(self.deduct_reasons)),
        }


def evaluate_integrated_score(
    entry: TodayEntry,
    item_scores: dict[str, ScoreDetail],
    base_score: float,
    pace_analysis,
    bloodline_analysis,
    lap_analysis,
) -> IntegratedEvaluation:
    """展開・コース・血統・距離・馬場・相手関係を組み合わせて補正します。

    項目を単独で見るだけではなく、
    「展開とコースが同時に合う」「血統は良いが馬場が不安」などの
    条件の組み合わせを評価するためのエンジンです。
    """

    add_points = 0.0
    deduct_points = 0.0
    add_reasons: list[str] = []
    deduct_reasons: list[str] = []

    past_score = get_score(item_scores, "過去走分析")
    opponent_score = get_score(item_scores, "相手関係")
    distance_score = get_score(item_scores, "距離適性")
    track_score = get_score(item_scores, "馬場")
    bloodline_score = get_score(item_scores, "血統")
    body_score = get_score(item_scores, "馬体重")
    pace_score = get_score(item_scores, "展開予想")
    lap_score = get_score(item_scores, "ラップ適性")

    course_profile = pace_analysis.course_profile
    course_fits_style = entry.running_style in course_profile.favorable_styles
    lap_fits_style = entry.running_style in lap_analysis.favorable_styles

    # 展開とコースの両方が合う馬は、実戦で力を出しやすいと見ます。
    if pace_score >= 80 and course_fits_style:
        add_points += integrated_adjustment("pace_course")
        add_reasons.append("展開評価が高く、コース辞書でも有利な脚質")

    # 展開・コース・血統がそろう形は、今回条件への総合的な後押しとします。
    if pace_score >= 80 and course_fits_style and bloodline_score >= 75:
        add_points += integrated_adjustment("pace_course_bloodline")
        add_reasons.append("展開・コース・血統がそろって高評価")

    # 距離と血統が同時に合う場合は、適性面の信頼度を少し上げます。
    if distance_score >= 75 and bloodline_score >= 70:
        add_points += integrated_adjustment("distance_bloodline")
        add_reasons.append("距離適性と血統評価がともに良好")

    # 馬場と血統が同時に合う場合は、当日条件への適性を加点します。
    if track_score >= 75 and bloodline_score >= 70:
        add_points += integrated_adjustment("track_bloodline")
        add_reasons.append("馬場評価と血統評価がかみ合う")

    # ラップ適性と展開評価が同時に高い場合は、レース質に合うと見ます。
    if lap_score >= 75 and pace_score >= 75:
        add_points += integrated_adjustment("lap_pace")
        add_reasons.append("ラップ適性と展開評価がともに良好")

    # ラップ・コース・馬場がそろう場合は、今回条件への総合適性を加点します。
    if lap_score >= 75 and course_fits_style and track_score >= 70:
        add_points += integrated_adjustment("lap_course_track")
        add_reasons.append("ラップ・コース・馬場の条件がかみ合う")

    # 過去走と相手関係が両方安定している馬は、基礎能力の裏付けと見ます。
    if past_score >= 70 and opponent_score >= 70:
        add_points += integrated_adjustment("past_opponent")
        add_reasons.append("過去走と相手関係の安定感がある")

    # 展開は良くても馬場が合わない場合は、評価を少し抑えます。
    if pace_score >= 80 and track_score < 55:
        deduct_points += integrated_adjustment("pace_bad_track")
        deduct_reasons.append("展開は向くが、馬場評価が低い")

    # コース向きの脚質でも、距離適性が低い場合は過信しません。
    if course_fits_style and distance_score < 55:
        deduct_points += integrated_adjustment("course_bad_distance")
        deduct_reasons.append("コース脚質は合うが、距離適性に不安")

    # 血統面が良くても馬体重の変動が大きい場合は、状態面を割り引きます。
    if bloodline_score >= 75 and body_score < 55:
        deduct_points += integrated_adjustment("bloodline_bad_body")
        deduct_reasons.append("血統評価は高いが、馬体重面に不安")

    # 馬場と血統の両方が低い場合は、今回条件への不安が大きいと見ます。
    if track_score < 50 and bloodline_score < 55:
        deduct_points += integrated_adjustment("track_bad_bloodline")
        deduct_reasons.append("馬場と血統の両面で今回条件に不安")

    # 展開が向いても、想定ラップの質が合わない場合は少し割り引きます。
    if pace_score >= 75 and lap_score < 55:
        deduct_points += integrated_adjustment("pace_bad_lap")
        deduct_reasons.append("展開は向くが、想定ラップへの適性が低い")

    if not lap_fits_style and lap_score < 55:
        deduct_points += integrated_adjustment("bad_lap_style")
        deduct_reasons.append("脚質が想定ラップの有利脚質から外れる")

    # 近走と相手関係の両方が弱い場合は、基礎評価を下げます。
    if past_score < 50 and opponent_score < 50:
        deduct_points += integrated_adjustment("past_bad_opponent")
        deduct_reasons.append("過去走と相手関係の裏付けが弱い")

    adjustment = clamp(add_points - deduct_points, -15, 15)
    final_score = clamp(base_score + adjustment)

    if not add_reasons:
        add_reasons.append("大きな加点条件はなし")
    if not deduct_reasons:
        deduct_reasons.append("大きな減点条件はなし")

    return IntegratedEvaluation(
        base_score=base_score,
        adjustment=adjustment,
        final_score=final_score,
        label=score_label(final_score),
        add_reasons=add_reasons,
        deduct_reasons=deduct_reasons,
    )


def get_score(item_scores: dict[str, ScoreDetail], item_name: str) -> float:
    """項目別スコアを安全に取り出します。"""

    detail = item_scores.get(item_name)
    if detail is None:
        return 0.0
    return detail.score


def integrated_adjustment(rule_name: str) -> float:
    """統合評価の補正量を config.py の重みから計算します。

    ルール名と参照する重みキーの対応は config.py の
    INTEGRATED_RULE_WEIGHTS で管理します。
    """

    weight_keys = INTEGRATED_RULE_WEIGHTS.get(rule_name, ())
    if not weight_keys:
        return 0.0

    total_weight = sum(ANALYSIS_WEIGHTS.get(key, 0) for key in weight_keys)
    average_weight = total_weight / len(weight_keys)
    return round(average_weight / 4, 1)


def score_label(score: float) -> str:
    """点数を人間が見やすい評価印に変換します。"""

    if score >= 85:
        return "◎"
    if score >= 75:
        return "○"
    if score >= 60:
        return "▲"
    if score >= 45:
        return "△"
    return "×"


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    """点数や補正量を決めた範囲内に収めます。"""

    return round(max(minimum, min(maximum, value)), 1)
