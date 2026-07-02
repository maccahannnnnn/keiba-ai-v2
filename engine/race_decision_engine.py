"""Judge whether the whole race is playable without changing horse scores.

RaceDecisionEngine is a race-level interpretation layer. It reads the already
computed horse decisions, scores, consistency data, risks, warnings, and race
structure, then returns PLAY / CAUTION / PASS for the race as a whole.
"""


class RaceDecisionEngine:
    """Create a race-level PLAY / CAUTION / PASS decision."""

    SCORE_KEYS = ["adjusted_score", "integrated_score", "weighted_score", "final_score"]

    def decide(self, race_context=None, horses=None):
        """Return race_decision_result without mutating horses or scores."""

        context = race_context if isinstance(race_context, dict) else {}
        rows = [horse for horse in horses if isinstance(horse, dict)] if isinstance(horses, list) else []

        stats = self._stats(rows)
        structure = context.get("race_structure")
        structure_flags = context.get("structure_flags")

        confidence = self._confidence(stats, structure, structure_flags)
        complexity = self._complexity(stats, structure, structure_flags)
        volatility = self._volatility(stats)
        score, factors, risks = self._score(stats, confidence, complexity, volatility, structure)

        decision = self._decision(score, stats, confidence, complexity, volatility)
        level = self._level(score, decision)
        reason = self._reason(decision, confidence, complexity, volatility, factors, risks)

        return {
            "race_decision": decision,
            "race_decision_score": score,
            "race_decision_level": level,
            "race_decision_reason": reason,
            "race_decision_factors": self._unique(factors),
            "race_decision_risks": self._unique(risks),
            "race_confidence": confidence,
            "race_complexity": complexity,
            "race_volatility": volatility,
            "race_stats": stats,
        }

    def _stats(self, rows):
        decisions = {"BUY": 0, "CAUTION": 0, "PASS": 0}
        buy_scores = []
        buy_consistency = []
        all_scores = []
        warning_count = 0
        risk_count = 0
        conflict_count = 0

        for row in rows:
            decision = str(row.get("decision") or "CAUTION").upper()
            if decision not in decisions:
                decision = "CAUTION"
            decisions[decision] += 1

            score = self._best_score(row)
            if score is not None:
                all_scores.append(score)
            if decision == "BUY":
                decision_score = self._number_or_none(row.get("decision_score"))
                if decision_score is not None:
                    buy_scores.append(decision_score)
                consistency_score = self._number_or_none(row.get("consistency_score"))
                if consistency_score is not None:
                    buy_consistency.append(consistency_score)

            warning_count += len(self._list(row.get("warnings")))
            risk_count += len(self._list(row.get("final_risks")) or self._list(row.get("risk_factors")))
            conflict_count += len(self._list(row.get("conflict_factors")))

        sorted_scores = sorted(all_scores, reverse=True)
        top_gap = 0
        if len(sorted_scores) >= 2:
            top_gap = sorted_scores[0] - sorted_scores[1]
        top3_gap = 0
        if len(sorted_scores) >= 4:
            top3_gap = sorted_scores[0] - sorted_scores[3]

        return {
            "horse_count": len(rows),
            "buy_count": decisions["BUY"],
            "caution_count": decisions["CAUTION"],
            "pass_count": decisions["PASS"],
            "average_buy_decision_score": self._average(buy_scores),
            "average_buy_consistency_score": self._average(buy_consistency),
            "top_score_gap": round(top_gap, 3),
            "top4_score_gap": round(top3_gap, 3),
            "warning_count": warning_count,
            "risk_count": risk_count,
            "conflict_count": conflict_count,
        }

    def _confidence(self, stats, structure, structure_flags):
        if stats["horse_count"] == 0:
            return "unknown"

        score = 0
        if stats["buy_count"] >= 2:
            score += 2
        elif stats["buy_count"] == 1:
            score += 1
        else:
            score -= 2

        if stats["average_buy_decision_score"] >= 0.8:
            score += 2
        elif stats["average_buy_decision_score"] >= 0.65:
            score += 1

        if stats["average_buy_consistency_score"] >= 0.8:
            score += 2
        elif stats["average_buy_consistency_score"] >= 0.65:
            score += 1

        if stats["top_score_gap"] >= 12:
            score += 1
        if stats["warning_count"] <= max(2, stats["horse_count"] // 4):
            score += 1
        if self._structure_is_clear(structure, structure_flags):
            score += 1

        if score >= 6:
            return "high"
        if score >= 3:
            return "medium"
        return "low"

    def _complexity(self, stats, structure, structure_flags):
        if stats["horse_count"] == 0:
            return "unknown"

        score = 0
        if stats["caution_count"] >= max(4, stats["horse_count"] // 3):
            score += 2
        if stats["top4_score_gap"] <= 18 and stats["horse_count"] >= 6:
            score += 2
        elif stats["top_score_gap"] <= 6 and stats["horse_count"] >= 3:
            score += 1
        if stats["conflict_count"] >= 4:
            score += 2
        elif stats["conflict_count"] >= 2:
            score += 1
        if stats["risk_count"] >= stats["horse_count"]:
            score += 1
        if stats["warning_count"] >= stats["horse_count"]:
            score += 1
        if not self._structure_is_clear(structure, structure_flags):
            score += 1

        if score >= 5:
            return "high"
        if score >= 2:
            return "medium"
        return "low"

    def _volatility(self, stats):
        if stats["horse_count"] == 0:
            return "unknown"

        score = 0
        if stats["buy_count"] == 0:
            score += 3
        elif stats["buy_count"] == 1:
            score += 1
        if stats["caution_count"] >= max(4, stats["horse_count"] // 3):
            score += 2
        if stats["top_score_gap"] <= 6 and stats["horse_count"] >= 3:
            score += 2
        if stats["warning_count"] >= stats["horse_count"]:
            score += 1
        if stats["risk_count"] >= stats["horse_count"]:
            score += 1
        if stats["conflict_count"] >= 3:
            score += 1

        if score >= 5:
            return "high"
        if score >= 2:
            return "medium"
        return "low"

    def _score(self, stats, confidence, complexity, volatility, structure):
        score = 0.5
        factors = []
        risks = []

        if stats["horse_count"] == 0:
            return 0.5, factors, ["評価対象馬が不足"]

        if stats["buy_count"] >= 2:
            score += 0.18
            factors.append("BUY馬が複数いる")
        elif stats["buy_count"] == 1:
            score += 0.08
            factors.append("BUY馬がいる")
        else:
            score -= 0.25
            risks.append("BUY馬がいない")

        if stats["average_buy_decision_score"] >= 0.8:
            score += 0.12
            factors.append("BUY馬のdecision_scoreが高い")
        elif stats["average_buy_decision_score"] < 0.65 and stats["buy_count"]:
            score -= 0.08
            risks.append("BUY馬のdecision_scoreが物足りない")

        if stats["average_buy_consistency_score"] >= 0.8:
            score += 0.1
            factors.append("BUY馬の構造一致度が高い")

        if stats["top_score_gap"] >= 12:
            score += 0.08
            factors.append("上位評価が明確")
        elif stats["top_score_gap"] <= 6 and stats["horse_count"] >= 3:
            score -= 0.08
            risks.append("上位評価が接近")

        if self._structure_is_clear(structure, None):
            score += 0.06
            factors.append("レース構造が比較的明確")
        else:
            score -= 0.06
            risks.append("レース構造の情報が不足")

        if confidence == "high":
            score += 0.08
            factors.append("race_confidenceがhigh")
        elif confidence == "low":
            score -= 0.12
            risks.append("race_confidenceがlow")

        if complexity == "high":
            score -= 0.12
            risks.append("race_complexityがhigh")
        elif complexity == "low":
            score += 0.05
            factors.append("race_complexityがlow")

        if volatility == "high":
            score -= 0.16
            risks.append("race_volatilityがhigh")
        elif volatility == "low":
            score += 0.06
            factors.append("race_volatilityがlow")

        if stats["warning_count"] >= stats["horse_count"]:
            score -= 0.08
            risks.append("warningsが多い")
        if stats["conflict_count"] >= 4:
            score -= 0.08
            risks.append("conflict_factorsが多い")

        return max(0, min(1, round(score, 2))), factors, risks

    def _decision(self, score, stats, confidence, complexity, volatility):
        if stats["horse_count"] == 0:
            return "CAUTION"
        if score >= 0.8 and stats["buy_count"] >= 1 and confidence in {"high", "medium"}:
            if complexity != "high" and volatility != "high":
                return "PLAY"
        if score < 0.5 or stats["buy_count"] == 0 or volatility == "high":
            return "PASS"
        return "CAUTION"

    def _level(self, score, decision):
        if decision == "PASS":
            return "pass" if score < 0.35 else "weak_caution"
        if score >= 0.9:
            return "strong_play"
        if score >= 0.8:
            return "play"
        if score >= 0.5:
            return "caution"
        if score >= 0.35:
            return "weak_caution"
        return "pass"

    def _reason(self, decision, confidence, complexity, volatility, factors, risks):
        factor_text = "、".join(self._unique(factors)) or "明確なプラス材料は限定的"
        risk_text = "、".join(self._unique(risks)) or "大きな不安は限定的"

        if decision == "PLAY":
            return (
                f"レース構造とBUY候補の評価が噛み合い、{factor_text}。"
                f"信頼度は{confidence}、複雑度は{complexity}、荒れやすさは{volatility}で、"
                f"リスクは{risk_text}。"
            )
        if decision == "CAUTION":
            return (
                f"{factor_text}はありますが、{risk_text}も残ります。"
                f"信頼度{confidence}、複雑度{complexity}、荒れやすさ{volatility}のため慎重評価。"
            )
        return (
            f"{risk_text}が大きく、レース全体としては見送り寄り。"
            f"信頼度{confidence}、複雑度{complexity}、荒れやすさ{volatility}。"
        )

    def _structure_is_clear(self, structure, structure_flags):
        text = str(structure or "") + " " + str(structure_flags or "")
        if not text.strip() or text.strip() in {"{}", "[]"}:
            return False
        lowered = text.lower()
        return "unknown" not in lowered and "neutral" not in lowered

    def _best_score(self, row):
        for key in self.SCORE_KEYS:
            value = self._number_or_none(row.get(key))
            if value is not None:
                return value
        return None

    def _average(self, values):
        clean = [value for value in values if isinstance(value, (int, float))]
        if not clean:
            return 0
        return round(sum(clean) / len(clean), 3)

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _number_or_none(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _unique(self, values):
        unique = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique


if __name__ == "__main__":
    engine = RaceDecisionEngine()
    sample_horses = [
        {"decision": "BUY", "decision_score": 0.91, "adjusted_score": 120, "consistency_score": 0.88},
        {"decision": "CAUTION", "decision_score": 0.65, "adjusted_score": 101},
        {"decision": "PASS", "decision_score": 0.42, "adjusted_score": 80},
    ]
    print(engine.decide({"race_structure": {"pace": "average"}}, sample_horses))
