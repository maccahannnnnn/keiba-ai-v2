"""Create final BUY / CAUTION / PASS labels without changing scores.

DecisionEngine is a final interpretation layer. It reads existing scores,
consistency, explanation, risk, and warning data, then returns a decision label
for review. It never changes final_score, weighted_score, integrated_score,
adjusted_score, score_weights, or any evaluator result.
"""


class DecisionEngine:
    """Judge BUY / CAUTION / PASS from existing evaluation output."""

    MAJOR_RISK_KEYWORDS = [
        "構造一致度が低い",
        "脚質不明",
        "ラップ情報不足",
        "馬場適性情報不足",
        "距離適性の不安",
        "展開面の不安",
        "ズレ",
        "不向き",
        "不足",
    ]

    def decide(self, horse=None, rank_context=None):
        """Return decision_result for one horse."""

        item = horse if isinstance(horse, dict) else {}
        context = rank_context if isinstance(rank_context, dict) else {}

        score = self._base_score(item, context)
        factors = []
        risks = []

        score = self._apply_consistency(item, score, factors, risks)
        score = self._apply_strengths_and_risks(item, score, factors, risks)
        score = self._apply_impact(item, score, factors, risks)
        score = self._apply_warnings(item, score, risks)
        score = self._apply_summary_flags(item, score, factors, risks)
        score = max(0, min(1, round(score, 2)))

        decision = self._decision(score, item, risks)
        level = self._decision_level(score, decision)
        reason = self._decision_reason(decision, factors, risks)

        return {
            "decision": decision,
            "decision_score": score,
            "decision_level": level,
            "decision_reason": reason,
            "decision_factors": self._unique(factors),
            "decision_risks": self._unique(risks),
        }

    def decide_many(self, horses=None):
        """Return decision results in input order without mutating scores."""

        rows = horses if isinstance(horses, list) else []
        context = self._rank_context(rows)
        return [self.decide(row, context) for row in rows]

    def _base_score(self, item, context):
        value = self._best_score(item)
        top = context.get("top_score")
        bottom = context.get("bottom_score")
        if value is None:
            return 0.5
        if top is None or bottom is None or top == bottom:
            return 0.6 if value > 0 else 0.45
        return 0.35 + ((value - bottom) / (top - bottom)) * 0.45

    def _rank_context(self, rows):
        scores = [self._best_score(row) for row in rows if isinstance(row, dict)]
        scores = [score for score in scores if score is not None]
        if not scores:
            return {"top_score": None, "bottom_score": None}
        return {"top_score": max(scores), "bottom_score": min(scores)}

    def _best_score(self, item):
        for key in ["adjusted_score", "integrated_score", "weighted_score", "final_score"]:
            value = self._number_or_none(item.get(key))
            if value is not None:
                return value
        return None

    def _apply_consistency(self, item, score, factors, risks):
        level = str(item.get("consistency_level") or "").lower()
        consistency = self._number_or_none(item.get("consistency_score"))
        strong_matches = self._list(item.get("strong_matches"))
        conflict_factors = self._list(item.get("conflict_factors"))

        if level == "high" or (consistency is not None and consistency >= 0.85):
            score += 0.12
            factors.append("構造一致度が高い")
        elif level == "medium" or (consistency is not None and consistency >= 0.7):
            score += 0.04
            factors.append("構造一致度は標準以上")
        elif level in {"low", "conflict"} or (consistency is not None and consistency < 0.5):
            score -= 0.18
            risks.append("構造一致度が低い")

        if len(strong_matches) >= 4:
            score += 0.06
            factors.append("複数Evaluatorが同方向")
        if len(conflict_factors) >= 2:
            score -= 0.1
            risks.append("構造との矛盾あり")
        return score

    def _apply_strengths_and_risks(self, item, score, factors, risks):
        strengths = self._list(item.get("final_strengths")) or self._list(item.get("strengths"))
        weaknesses = self._list(item.get("final_weaknesses")) or self._list(item.get("weaknesses"))
        risk_factors = self._list(item.get("final_risks")) or self._list(item.get("risk_factors"))

        if len(strengths) >= 6:
            score += 0.08
            factors.append("強みが多い")
        elif len(strengths) >= 3:
            score += 0.04
            factors.append("評価材料あり")

        if weaknesses:
            score -= min(0.12, 0.03 * len(weaknesses))
            risks.extend(str(weakness) for weakness in weaknesses[:4])

        if risk_factors:
            score -= min(0.18, 0.04 * len(risk_factors))
            risks.extend(str(risk) for risk in risk_factors[:5])

        major_count = sum(1 for risk in risks if self._is_major_risk(risk))
        if major_count >= 2:
            score -= 0.12
            risks.append("重大リスクが複数")
        return score

    def _apply_impact(self, item, score, factors, risks):
        impact = self._number(item.get("impact_score"))
        if impact > 0:
            score += min(0.08, impact / 100)
            factors.append("展開利あり")
        elif impact < 0:
            score -= min(0.08, abs(impact) / 100)
            risks.append("展開不向き")
        return score

    def _apply_warnings(self, item, score, risks):
        warnings = self._list(item.get("warnings"))
        if warnings:
            score -= min(0.12, 0.03 * len(warnings))
            risks.append("warningsあり")
        return score

    def _apply_summary_flags(self, item, score, factors, risks):
        text = " ".join(
            str(item.get(key) or "")
            for key in ["final_summary", "explain_summary", "confidence_reason"]
        )
        if any(word in text for word in ["過信", "ズレ", "不安", "注意", "不足"]):
            score -= 0.05
            risks.append("説明内に注意要素あり")
        if any(word in text for word in ["一致率が高", "複数Evaluator", "展開利", "整合性が高"]):
            score += 0.04
            factors.append("説明上の整合性が高い")
        return score

    def _decision(self, score, item, risks):
        major_count = sum(1 for risk in risks if self._is_major_risk(risk))
        conflicts = len(self._list(item.get("conflict_factors")))

        if score >= 0.8 and major_count == 0 and conflicts <= 1:
            return "BUY"
        if score < 0.5 or major_count >= 2 or conflicts >= 3:
            return "PASS"
        return "CAUTION"

    def _decision_level(self, score, decision=None):
        if decision == "PASS":
            return "pass" if score < 0.5 else "weak_caution"
        if decision == "CAUTION":
            return "caution" if score >= 0.5 else "weak_caution"
        if score >= 0.9:
            return "strong_buy"
        if score >= 0.8:
            return "buy"
        if score >= 0.5:
            return "caution"
        if score >= 0.35:
            return "weak_caution"
        return "pass"

    def _decision_reason(self, decision, factors, risks):
        factor_text = "、".join(self._unique(factors)) or "評価材料は限定的"
        risk_text = "、".join(self._unique(risks)) or "大きなリスクは限定的"

        if decision == "BUY":
            return f"構造一致度と評価材料のバランスが良く、{factor_text}を確認。リスクは{risk_text}。"
        if decision == "CAUTION":
            return f"{factor_text}は評価できますが、{risk_text}も残るため慎重評価。"
        return f"一部評価材料はありますが、{risk_text}が大きく、今回は見送り寄りの判断。"

    def _is_major_risk(self, text):
        value = str(text)
        return any(keyword in value for keyword in self.MAJOR_RISK_KEYWORDS)

    def _number(self, value):
        number = self._number_or_none(value)
        return number if number is not None else 0

    def _number_or_none(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _unique(self, values):
        unique = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique


if __name__ == "__main__":
    engine = DecisionEngine()
    sample = {
        "horse_name": "sample",
        "adjusted_score": 120,
        "consistency_score": 0.91,
        "consistency_level": "high",
        "strong_matches": ["course_shape", "distance", "lap", "bloodline"],
        "strengths": ["距離適性", "ラップ適性", "血統適性"],
        "risk_factors": ["当日バイアス情報が限定的"],
        "impact_score": 10,
    }
    print(engine.decide(sample, {"top_score": 120, "bottom_score": 0}))
