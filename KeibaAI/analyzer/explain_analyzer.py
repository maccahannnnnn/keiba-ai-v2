from dataclasses import dataclass, field

from analyzer.schemas import AnalysisResult


PLUS = "加点"
MINUS = "減点"


@dataclass
class ExplainReason:
    """1つの加点・減点理由を、あとで機械学習にも使いやすい形で持ちます。"""

    reason_id: str
    reason_type: str
    category: str
    summary: str
    score: float


@dataclass
class ExplainAnalysis:
    """Explain Engine が1頭分の理由を集約した結果です。"""

    horse_name: str
    plus_reasons: list[ExplainReason] = field(default_factory=list)
    minus_reasons: list[ExplainReason] = field(default_factory=list)
    overall_reasons: list[str] = field(default_factory=list)

    def reason_ids(self) -> list[str]:
        """features.csv 用に、文章ではなく安定したIDだけを返します。"""

        return [reason.reason_id for reason in self.plus_reasons + self.minus_reasons]

    def reason_types(self) -> list[str]:
        """features.csv 用に、加点・減点の種別だけを返します。"""

        return [reason.reason_type for reason in self.plus_reasons + self.minus_reasons]

    def to_features(self) -> dict[str, object]:
        """将来の機械学習で使いやすい、文章を含まない特徴量に変換します。"""

        return {
            "reason_ids": "|".join(self.reason_ids()),
            "reason_types": "|".join(self.reason_types()),
            "reason_plus_count": len(self.plus_reasons),
            "reason_minus_count": len(self.minus_reasons),
        }


def build_explain_analysis(result: AnalysisResult) -> ExplainAnalysis:
    """各分析エンジンの結果を見て、加点理由・減点理由を集約します。"""

    explain = ExplainAnalysis(horse_name=result.horse_name)

    add_score_reasons(result, explain)
    add_pace_lap_reasons(result, explain)
    add_course_reasons(result, explain)
    add_track_bias_reasons(result, explain)
    add_integrated_reasons(result, explain)
    explain.overall_reasons = build_overall_reasons(result, explain)

    return explain


def add_score_reasons(result: AnalysisResult, explain: ExplainAnalysis) -> None:
    """項目別スコアから、強み・弱みを理由IDとして作ります。"""

    score_rules = [
        ("past_run", "過去走分析", "past_run_high_score", "past_run_low_score", "過去走が安定している", "過去走の安定感に不安がある"),
        ("opponent", "相手関係", "opponent_high_level", "opponent_low_level", "強い相手と戦ってきた", "相手関係の裏付けが弱い"),
        ("distance", "距離適性", "distance_fit", "distance_risk", "今回距離への適性が高い", "今回距離への適性に不安がある"),
        ("bloodline", "血統", "bloodline_fit", "bloodline_risk", "血統面が今回条件に合う", "血統面の後押しが弱い"),
        ("body_weight", "馬体重", "body_weight_stable", "body_weight_risk", "馬体重の変動が許容範囲", "馬体重の変動が大きい"),
    ]

    for category, item_name, plus_id, minus_id, plus_text, minus_text in score_rules:
        score = get_item_score(result, item_name)
        if score >= 75:
            add_reason(explain, plus_id, PLUS, category, plus_text, score)
        elif score < 55:
            add_reason(explain, minus_id, MINUS, category, minus_text, score)


def add_pace_lap_reasons(result: AnalysisResult, explain: ExplainAnalysis) -> None:
    """展開評価とラップ評価の一致・矛盾を見ます。"""

    pace_score = get_item_score(result, "展開予想")
    lap_score = get_item_score(result, "ラップ適性")

    if pace_score >= 75 and lap_score >= 75:
        add_reason(explain, "pace_lap_match", PLUS, "pace_lap", "展開評価とラップ評価がそろって高い", min(pace_score, lap_score))
    elif pace_score >= 75 and lap_score < 55:
        add_reason(explain, "pace_lap_conflict", MINUS, "pace_lap", "展開評価は高いがラップ適性が低い", lap_score)
    elif pace_score < 55 and lap_score >= 75:
        add_reason(explain, "lap_fit_pace_risk", MINUS, "pace_lap", "ラップ適性は高いが展開面に不安がある", pace_score)


def add_course_reasons(result: AnalysisResult, explain: ExplainAnalysis) -> None:
    """コース辞書と脚質の相性を見ます。"""

    running_style = get_running_style(result)
    course_profile = result.pace_analysis.course_profile

    if running_style in course_profile.favorable_styles:
        add_reason(
            explain,
            "course_style_fit",
            PLUS,
            "course",
            f"{course_profile.racecourse}{course_profile.surface}{course_profile.distance}mで脚質が合う",
            80.0,
        )
    else:
        add_reason(explain, "course_style_mismatch", MINUS, "course", "コース辞書上の有利脚質とは少しずれる", 55.0)


def add_track_bias_reasons(result: AnalysisResult, explain: ExplainAnalysis) -> None:
    """馬場バイアス評価エンジンの結果を理由に変換します。"""

    evaluation = result.track_bias_analysis.horse_evaluations.get(result.horse_name)
    if evaluation is None:
        return

    if evaluation.score >= 70:
        add_reason(explain, "track_bias_fit", PLUS, "track_bias", "当日の馬場バイアスに合う", evaluation.score)
    elif evaluation.score < 50:
        add_reason(explain, "track_bias_mismatch", MINUS, "track_bias", "当日の馬場バイアスとは合いにくい", evaluation.score)


def add_integrated_reasons(result: AnalysisResult, explain: ExplainAnalysis) -> None:
    """統合評価エンジンの補正理由を、ID付き理由に変換します。"""

    integrated = result.integrated_evaluation

    for index, reason in enumerate(integrated.add_reasons, start=1):
        add_reason(explain, f"integrated_plus_{index:02d}", PLUS, "integrated", reason, integrated.final_score)

    for index, reason in enumerate(integrated.deduct_reasons, start=1):
        if "なし" in reason:
            continue
        add_reason(explain, f"integrated_minus_{index:02d}", MINUS, "integrated", reason, integrated.final_score)


def build_overall_reasons(result: AnalysisResult, explain: ExplainAnalysis) -> list[str]:
    """加点・減点のバランスから、総合評価理由を作ります。"""

    reasons: list[str] = []

    if result.integrated_evaluation.adjustment > 0:
        reasons.append("複数条件の組み合わせで総合評価を押し上げた")
    elif result.integrated_evaluation.adjustment < 0:
        reasons.append("一部条件の矛盾により総合評価を補正した")
    else:
        reasons.append("大きな補正はなく、項目別スコアを中心に評価した")

    plus_count = len(explain.plus_reasons)
    minus_count = len(explain.minus_reasons)
    if plus_count > minus_count:
        reasons.append("加点材料が減点材料を上回る")
    elif minus_count > plus_count:
        reasons.append("減点材料が加点材料を上回るため注意が必要")
    else:
        reasons.append("加点材料と減点材料が拮抗している")

    return reasons


def add_reason(
    explain: ExplainAnalysis,
    reason_id: str,
    reason_type: str,
    category: str,
    summary: str,
    score: float,
) -> None:
    """同じ理由IDを重複登録しないように追加します。"""

    reasons = explain.plus_reasons if reason_type == PLUS else explain.minus_reasons
    if any(reason.reason_id == reason_id for reason in reasons):
        return

    reasons.append(
        ExplainReason(
            reason_id=reason_id,
            reason_type=reason_type,
            category=category,
            summary=summary,
            score=round(score, 1),
        )
    )


def get_item_score(result: AnalysisResult, item_name: str) -> float:
    """項目別スコアを安全に取り出します。"""

    detail = result.item_scores.get(item_name)
    if detail is None:
        return 0.0
    return detail.score


def get_running_style(result: AnalysisResult) -> str:
    """展開分析で使った脚質を取り出します。"""

    evaluation = result.pace_analysis.horse_evaluations.get(result.horse_name)
    if evaluation is None:
        return result.running_style
    return evaluation.running_style
