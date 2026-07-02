"""Evaluate confidence for each horse without changing existing scores.

ConfidenceEngine is separate from DecisionEngine.  It answers "how reliable is
this horse's evaluation?" by reading existing decision, consistency, impact,
risk, warning, and race-level decision data.
"""


class ConfidenceEngine:
    """Create confidence_score / confidence_level for one horse or many horses."""

    SCORE_KEYS = ["adjusted_score", "integrated_score", "weighted_score", "final_score"]

    def evaluate(self, horse=None, race_context=None):
        """Return confidence_result for one horse without mutating input."""

        item = horse if isinstance(horse, dict) else {}
        context = race_context if isinstance(race_context, dict) else {}

        if not item:
            return self._default_result()

        score = 0.5
        factors = []
        risks = []

        score = self._apply_decision(item, score, factors, risks)
        score = self._apply_consistency(item, score, factors, risks)
        score = self._apply_impact_and_scores(item, score, factors, risks)
        score = self._apply_race_context(context, score, factors, risks)
        score = self._apply_risks(item, score, factors, risks)
        score = max(0, min(1, round(score, 2)))

        level = self._level(score)
        reason = self._reason(level, factors, risks)

        return {
            "confidence_score": score,
            "confidence_level": level,
            "confidence_reason": reason,
            "confidence_factors": self._unique(factors),
            "confidence_risks": self._unique(risks),
        }

    def evaluate_many(self, horses=None, race_context=None):
        """Return confidence results in input order."""

        rows = horses if isinstance(horses, list) else []
        context = race_context if isinstance(race_context, dict) else {}
        return [self.evaluate(row, context) for row in rows]

    def _apply_decision(self, item, score, factors, risks):
        decision = str(item.get("decision") or "").upper()
        decision_score = self._number_or_none(item.get("decision_score"))

        if decision_score is not None:
            if decision_score >= 0.85:
                score += 0.16
                factors.append("DecisionScore高")
            elif decision_score >= 0.65:
                score += 0.08
                factors.append("DecisionScore標準以上")
            elif decision_score < 0.45:
                score -= 0.14
                risks.append("DecisionScore低")
        else:
            risks.append("DecisionScore不足")

        if decision == "BUY":
            score += 0.08
            factors.append("Decision BUY")
        elif decision == "PASS":
            score -= 0.12
            risks.append("Decision PASS")
        elif decision == "CAUTION":
            risks.append("Decision CAUTION")
        else:
            risks.append("Decision不明")
        return score

    def _apply_consistency(self, item, score, factors, risks):
        consistency = self._number_or_none(item.get("consistency_score"))
        level = str(item.get("consistency_level") or "").lower()
        strong_matches = self._list(item.get("strong_matches"))
        weak_matches = self._list(item.get("weak_matches"))
        conflicts = self._list(item.get("conflict_factors"))

        if level == "high" or (consistency is not None and consistency >= 0.85):
            score += 0.16
            factors.append("Consistency高")
        elif level == "medium" or (consistency is not None and consistency >= 0.65):
            score += 0.06
            factors.append("Consistency標準")
        elif level in {"low", "conflict"} or (consistency is not None and consistency < 0.5):
            score -= 0.18
            risks.append("Consistency低")
        else:
            risks.append("Consistency不足")

        if len(strong_matches) >= 4:
            score += 0.08
            factors.append("StrongMatches多")
        elif len(strong_matches) >= 2:
            score += 0.04
            factors.append("StrongMatchesあり")

        if weak_matches:
            score -= min(0.08, len(weak_matches) * 0.02)
            risks.append("WeakMatchesあり")
        if conflicts:
            score -= min(0.16, len(conflicts) * 0.04)
            risks.append("Conflictあり")
        return score

    def _apply_impact_and_scores(self, item, score, factors, risks):
        impact = self._number(item.get("impact_score"))
        if impact > 0:
            score += min(0.08, impact / 100)
            factors.append("Impact加点")
        elif impact < 0:
            score -= min(0.08, abs(impact) / 100)
            risks.append("Impact減点")

        best_score = self._best_score(item)
        if best_score is not None and best_score > 0:
            score += 0.04
            factors.append("総合スコアあり")
        else:
            risks.append("総合スコア不足")
        return score

    def _apply_race_context(self, context, score, factors, risks):
        race_decision = str(context.get("race_decision") or "").upper()
        race_confidence = str(context.get("race_confidence") or "").lower()

        if race_decision == "PLAY":
            score += 0.08
            factors.append("RaceDecision PLAY")
        elif race_decision == "PASS":
            score -= 0.1
            risks.append("RaceDecision PASS")
        elif race_decision == "CAUTION":
            risks.append("RaceDecision CAUTION")

        if race_confidence == "high":
            score += 0.08
            factors.append("RaceConfidence High")
        elif race_confidence == "medium":
            score += 0.03
            factors.append("RaceConfidence Medium")
        elif race_confidence == "low":
            score -= 0.1
            risks.append("RaceConfidence Low")
        else:
            risks.append("RaceConfidence不明")
        return score

    def _apply_risks(self, item, score, factors, risks):
        warning_count = len(self._list(item.get("warnings")))
        risk_count = len(self._list(item.get("final_risks")) or self._list(item.get("risk_factors")))
        conflict_count = len(self._list(item.get("conflict_factors")))

        if warning_count == 0:
            score += 0.05
            factors.append("Warnings少")
        else:
            score -= min(0.15, warning_count * 0.04)
            risks.append("Warnings多")

        if risk_count == 0:
            score += 0.04
            factors.append("Risk少")
        else:
            score -= min(0.15, risk_count * 0.03)
            risks.append("Risk多")

        if conflict_count == 0:
            score += 0.04
            factors.append("Conflict少")
        else:
            score -= min(0.12, conflict_count * 0.04)
            risks.append("Conflict多")
        return score

    def _level(self, score):
        if score >= 0.9:
            return "very_high"
        if score >= 0.75:
            return "high"
        if score >= 0.55:
            return "medium"
        if score >= 0.35:
            return "low"
        return "very_low"

    def _reason(self, level, factors, risks):
        factor_text = "、".join(self._unique(factors)) or "評価材料は限定的"
        risk_text = "、".join(self._unique(risks)) or "大きな不安は限定的"

        if level in {"very_high", "high"}:
            return f"{factor_text}が確認でき、リスクは{risk_text}のため信頼度は高め。"
        if level == "medium":
            return f"{factor_text}はある一方で、{risk_text}も残るため信頼度は中程度。"
        return f"{risk_text}が目立つため、評価の信頼度は低め。"

    def _default_result(self):
        return {
            "confidence_score": 0.5,
            "confidence_level": "medium",
            "confidence_reason": "評価情報が不足しているため中立評価。",
            "confidence_factors": [],
            "confidence_risks": ["評価情報不足"],
        }

    def _best_score(self, item):
        for key in self.SCORE_KEYS:
            value = self._number_or_none(item.get(key))
            if value is not None:
                return value
        return None

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
    engine = ConfidenceEngine()
    sample = {
        "decision": "BUY",
        "decision_score": 0.91,
        "consistency_score": 0.88,
        "consistency_level": "high",
        "strong_matches": ["distance", "bloodline", "lap", "shape"],
        "impact_score": 10,
        "adjusted_score": 120,
    }
    print(engine.evaluate(sample, {"race_decision": "PLAY", "race_confidence": "high"}))
