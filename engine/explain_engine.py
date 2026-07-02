"""Generate readable explanations without changing any score.

This engine reads RaceStructureEngine output and each evaluator's comments.
It does not calculate, adjust, or overwrite final_score / weighted_score /
integrated_score / adjusted_score.
"""


class ExplainEngine:
    """Build explanation text, strengths, weaknesses, risks, and confidence."""

    POSITIVE_KEYS = {
        "bloodline_score": "血統一致",
        "past_performance_score": "近走内容",
        "pace_style_score": "脚質安定",
        "distance_score": "距離適性",
        "track_condition_score": "馬場適性",
        "shape_score": "展開適性",
        "course_shape_score": "コース形状適性",
        "track_bias_score": "馬場バイアス適性",
        "lap_score": "ラップ適性",
    }

    NEGATIVE_KEYS = {
        "bloodline_score": "血統面の根拠が弱い",
        "past_performance_score": "近走内容に課題",
        "pace_style_score": "脚質判定に課題",
        "distance_score": "距離適性に課題",
        "track_condition_score": "馬場適性に課題",
        "shape_score": "展開不向き",
        "course_shape_score": "コース形状と噛み合わない",
        "track_bias_score": "馬場バイアス不向き",
        "lap_score": "想定ラップと噛み合わない",
    }

    def build(self, horse):
        """Return explanation data for one horse.

        Args:
            horse (dict): One horse result from TargetTrialAdapter.
        """

        item = horse if isinstance(horse, dict) else {}
        strengths = self._strengths(item)
        weaknesses = self._weaknesses(item)
        risk_factors = self._risk_factors(item)
        consistency_summary = self._consistency_summary(item)
        consistency_explanation = self._consistency_explanation(item)
        self._apply_consistency_to_lists(item, strengths, weaknesses, risk_factors)
        strengths = self._unique(strengths)
        weaknesses = self._unique(weaknesses)
        risk_factors = self._unique(risk_factors)
        confidence_reason = self._confidence_reason(item, strengths, weaknesses, risk_factors)
        confidence_reason = self._append_confidence_consistency(item, confidence_reason)
        summary = self._summary(item, strengths, weaknesses)
        summary = self._append_summary_consistency(item, summary)
        explanation = self._explanation(item, summary, strengths, weaknesses, risk_factors)
        if consistency_explanation:
            explanation = f"{explanation}\n{consistency_explanation}" if explanation else consistency_explanation

        return {
            "explanation": explanation,
            "summary": summary,
            "consistency_explanation": consistency_explanation,
            "consistency_summary": consistency_summary,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "risk_factors": risk_factors,
            "confidence_reason": confidence_reason,
        }

    def _strengths(self, item):
        strengths = []
        for key, label in self.POSITIVE_KEYS.items():
            if self._number(item.get(key)) >= self._positive_threshold(key):
                strengths.append(label)

        for factor in self._list(item.get("key_factors")):
            if factor == "course_shape" and item.get("course_shape_score", 0) > 0:
                strengths.append("レース構造との一致")
            elif factor == "positioning" and item.get("shape_score", 0) > 0:
                strengths.append("位置取り")
            elif factor == "sustained_speed" and item.get("lap_score", 0) > 0:
                strengths.append("持続力")
            elif factor == "early_speed" and item.get("pace_style") in {"escape", "front", "stalk"}:
                strengths.append("先行力")

        return self._unique(strengths) or ["明確な強調材料は限定的"]

    def _weaknesses(self, item):
        weaknesses = []
        for key, label in self.NEGATIVE_KEYS.items():
            if self._number(item.get(key)) <= self._negative_threshold(key):
                weaknesses.append(label)

        flags = item.get("structure_flags") if isinstance(item.get("structure_flags"), dict) else {}
        if flags.get("is_small_turn") and item.get("pace_style") in {"closer", "deep_closer"}:
            weaknesses.append("小回りで後方脚質")
        if flags.get("is_long_straight") and item.get("pace_style") == "escape":
            weaknesses.append("長い直線で逃げ粘りが課題")

        return self._unique(weaknesses)

    def _risk_factors(self, item):
        risks = []
        pace = self._race_structure(item).get("pace") or item.get("race_pace_prediction")
        pace_style = item.get("pace_style")

        if pace in {"fast", "very_fast"} and pace_style in {"escape", "front"}:
            risks.append("ハイペースになると前半負荷が高い")
        if pace == "slow" and pace_style in {"closer", "deep_closer"}:
            risks.append("スローでは後方から届きにくい")
        if self._number(item.get("track_bias_score")) == 0:
            risks.append("当日バイアス情報が限定的")
        if self._number(item.get("lap_score")) <= 0:
            risks.append("想定ラップへの上積みが限定的")
        if item.get("warnings"):
            risks.append("入力データに一部不足あり")

        return self._unique(risks)

    def _confidence_reason(self, item, strengths, weaknesses, risk_factors):
        positive_count = sum(
            1
            for key in [
                "bloodline_score",
                "past_performance_score",
                "distance_score",
                "track_condition_score",
                "shape_score",
                "course_shape_score",
                "lap_score",
            ]
            if self._number(item.get(key)) > 0
        )
        negative_count = sum(
            1
            for key in [
                "distance_score",
                "track_condition_score",
                "shape_score",
                "course_shape_score",
                "lap_score",
            ]
            if self._number(item.get(key)) < 0
        )

        if positive_count >= 5 and not weaknesses:
            return "複数Evaluatorが同方向を示している"
        if self._number(item.get("shape_score")) > 0 and self._number(item.get("course_shape_score")) > 0:
            return "構造と脚質が一致"
        if positive_count >= 4 and negative_count <= 1:
            return "評価要素の整合性が高い"
        if risk_factors:
            return "評価材料はあるがリスク要素も残る"
        return "評価材料が限定的なため慎重に扱う"

    def _summary(self, item, strengths, weaknesses):
        if strengths and strengths != ["明確な強調材料は限定的"] and not weaknesses:
            return "構造との一致率が高く、展開利が見込める。"
        if strengths and weaknesses:
            return "評価できる材料はあるが、構造上の課題も残る。"
        if weaknesses:
            return "現時点では不安材料が目立ち、慎重な評価が必要。"
        return "大きな強調材料は限定的で、中立寄りの評価。"

    def _explanation(self, item, summary, strengths, weaknesses, risk_factors):
        parts = []
        structure_comment = item.get("structure_comment")
        if structure_comment:
            parts.append(str(structure_comment))

        for key in [
            "shape_comment",
            "course_shape_comment",
            "track_bias_comment",
            "lap_comment",
            "weight_comment",
        ]:
            value = item.get(key)
            if value:
                parts.append(str(value))

        parts.append(f"要約: {summary}")
        if strengths:
            parts.append("強み: " + "、".join(strengths))
        if weaknesses:
            parts.append("弱み: " + "、".join(weaknesses))
        if risk_factors:
            parts.append("リスク: " + "、".join(risk_factors))
        return "\n".join(parts)

    def _race_structure(self, item):
        value = item.get("race_structure")
        return value if isinstance(value, dict) else {}

    def _consistency_result(self, item):
        value = item.get("consistency_result")
        return value if isinstance(value, dict) else {}

    def _consistency_summary(self, item):
        result = self._consistency_result(item)
        level = str(result.get("consistency_level") or "").lower()
        if level == "high":
            return "構造一致度が高い"
        if level == "medium":
            return "構造一致度は標準"
        if level in {"low", "conflict"}:
            return "構造との矛盾あり"
        return ""

    def _consistency_explanation(self, item):
        result = self._consistency_result(item)
        if not result:
            return ""

        level = str(result.get("consistency_level") or "").lower()
        strong = self._list(result.get("strong_matches"))
        conflict = self._list(result.get("conflict_factors"))

        if level == "high":
            return (
                "レース構造と評価項目の一致度が高く、"
                f"{self._labels(strong)}が同じ方向を示しています。"
            )
        if level == "medium":
            return "レース構造との一致度は標準的で、大きな矛盾は少ない評価です。"
        if level in {"low", "conflict"}:
            detail = self._labels(conflict) if conflict else "一部評価項目"
            return f"{detail}がレース構造と噛み合っておらず、評価には注意が必要です。"
        return str(result.get("consistency_comment") or "")

    def _apply_consistency_to_lists(self, item, strengths, weaknesses, risk_factors):
        result = self._consistency_result(item)
        if not result:
            return

        for factor in self._list(result.get("strong_matches")):
            label = self._match_label(factor)
            if label and label not in strengths:
                strengths.append(label)

        conflict_labels = []
        for factor in self._list(result.get("conflict_factors")):
            label = self._conflict_label(factor)
            if label:
                conflict_labels.append(label)
                if label not in weaknesses:
                    weaknesses.append(label)

        level = str(result.get("consistency_level") or "").lower()
        if level in {"low", "conflict"} and "構造一致度が低い" not in risk_factors:
            risk_factors.append("構造一致度が低い")
        for label in conflict_labels:
            if label not in risk_factors:
                risk_factors.append(label)

    def _append_confidence_consistency(self, item, confidence_reason):
        summary = self._consistency_summary(item)
        if not summary:
            return confidence_reason

        level = str(self._consistency_result(item).get("consistency_level") or "").lower()
        if level == "high":
            addition = "構造一致度が高く、複数Evaluatorが同方向を示している"
        elif level == "medium":
            addition = "構造一致度は標準的"
        elif level in {"low", "conflict"}:
            addition = "構造との矛盾があり、評価には注意が必要"
        else:
            addition = summary

        if not confidence_reason:
            return addition
        if addition in confidence_reason:
            return confidence_reason
        return f"{confidence_reason} / {addition}"

    def _append_summary_consistency(self, item, summary):
        consistency_summary = self._consistency_summary(item)
        if not consistency_summary or consistency_summary in summary:
            return summary
        if consistency_summary == "構造一致度が高い":
            return f"{summary} 構造との一致率が高い。"
        if consistency_summary == "構造との矛盾あり":
            return f"{summary} 構造とのズレがある。"
        return f"{summary} {consistency_summary}。"

    def _labels(self, factors):
        labels = [self._match_label(factor) for factor in factors]
        labels = self._unique([label for label in labels if label])
        return "、".join(labels) if labels else "複数の評価項目"

    def _match_label(self, factor):
        mapping = {
            "course_shape": "コース形状との一致",
            "shape": "展開・位置取りとの一致",
            "pace": "展開・位置取りとの一致",
            "positioning": "展開・位置取りとの一致",
            "distance": "距離適性との一致",
            "bloodline": "血統適性との一致",
            "lap": "ラップ適性との一致",
            "track_bias": "馬場バイアスとの一致",
            "past": "近走内容との一致",
        }
        return mapping.get(str(factor))

    def _conflict_label(self, factor):
        mapping = {
            "course_shape": "コース形状とのズレ",
            "shape": "展開面の不安",
            "pace": "展開面の不安",
            "positioning": "展開面の不安",
            "distance": "距離適性の不安",
            "bloodline": "血統面のズレ",
            "lap": "ラップ適性の不安",
            "track_bias": "馬場バイアスとのズレ",
            "past": "近走内容との不安",
        }
        return mapping.get(str(factor))

    def _positive_threshold(self, key):
        if key in {"shape_score", "course_shape_score", "track_bias_score", "lap_score"}:
            return 4
        return 8

    def _negative_threshold(self, key):
        if key in {"shape_score", "course_shape_score", "track_bias_score", "lap_score"}:
            return -4
        return -5

    def _number(self, value):
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _unique(self, values):
        unique = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique


if __name__ == "__main__":
    engine = ExplainEngine()
    sample = {
        "horse_name": "sample",
        "structure_comment": "小回り1700mで位置取りと持続力を評価。",
        "pace_style": "front",
        "shape_score": 10,
        "course_shape_score": 6,
        "distance_score": 12,
        "lap_score": 5,
        "key_factors": ["course_shape", "positioning", "sustained_speed"],
        "structure_flags": {"is_small_turn": True},
    }
    print(engine.build(sample))
