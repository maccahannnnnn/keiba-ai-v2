"""Optional post-decision guard based on evaluator consensus.

The guard is disabled by default. When enabled, it may promote only
PASS->CAUTION or CAUTION->BUY without changing evaluator scores, final scores,
ranking scores, or thresholds.
"""


ENABLE_MULTI_EVALUATOR_CONSENSUS_GUARD = False


class MultiEvaluatorConsensusGuard:
    """Promote narrow cases where evaluator support strongly agrees."""

    BUY_THRESHOLD = 0.80
    CAUTION_THRESHOLD = 0.50

    POSITIVE_THRESHOLDS = {
        "Ability": 120.0,
        "PastPerformance": 55.0,
        "Distance": 30.0,
        "Course": 5.0,
        "LapSuitability": 0.0,
        "RaceShape": 0.0,
        "PaceStyle": 10.0,
    }

    SCORE_KEYS = {
        "Ability": ("total_score", "ability_score"),
        "PastPerformance": ("past_performance_score",),
        "Distance": ("distance_score",),
        "Course": ("course_shape_score", "course_score"),
        "LapSuitability": ("lap_score", "lap_suitability_score"),
        "RaceShape": ("shape_score", "race_shape_score"),
        "PaceStyle": ("pace_style_score", "pace_score", "running_style_score"),
    }

    SEVERE_RISK_KEYWORDS = (
        "severe",
        "danger",
        "major",
        "重大",
        "出走不能",
        "取消",
        "除外",
        "能力不足",
        "距離不適",
    )

    DATA_LIMITATION_KEYWORDS = (
        "データ不足が大きい",
        "評価値が欠損",
        "構造評価に必要な情報が不足",
    )

    def __init__(self, enabled=ENABLE_MULTI_EVALUATOR_CONSENSUS_GUARD):
        self.enabled = bool(enabled)

    def apply(self, item=None, context=None, decision=None, decision_score=None):
        """Return guarded decision and trace without mutating input values."""

        item = item if isinstance(item, dict) else {}
        context = context if isinstance(context, dict) else {}
        original_decision = str(decision or "")
        original_score = self._number_or_none(decision_score)
        rank = self._rank(item, context)
        evaluation = self._evaluate_consensus(item)
        risks = self._risk_text(item)
        result = self._base_result(original_decision, original_score, rank, evaluation)

        if not self.enabled:
            result["consensus_block_reasons"].append("guard_disabled")
            return result
        if original_decision not in {"PASS", "CAUTION"}:
            result["consensus_block_reasons"].append("decision_not_pass_or_caution")
            return result
        if rank is None or rank > 5:
            result["consensus_block_reasons"].append("rank_not_top5")
            return result
        if evaluation["missing"]:
            result["consensus_block_reasons"].append("evaluator_score_missing")
            return result
        if len(evaluation["positive"]) < 3:
            result["consensus_block_reasons"].append("positive_evaluators_below_3")
            return result
        if len(evaluation["negative"]) >= 2:
            result["consensus_block_reasons"].append("negative_evaluators_2_or_more")
            return result
        if self._has_keyword(risks, self.SEVERE_RISK_KEYWORDS):
            result["consensus_block_reasons"].append("severe_risk_present")
            return result
        if self._has_keyword(risks, self.DATA_LIMITATION_KEYWORDS):
            result["consensus_block_reasons"].append("large_data_limitation_present")
            return result
        if self._is_newcomer_or_jump(item, context):
            result["consensus_block_reasons"].append("newcomer_or_jump")
            return result

        result["consensus_guard_candidate"] = True

        if original_decision == "PASS":
            return self._pass_to_caution(result, original_score, evaluation)
        if original_decision == "CAUTION":
            return self._caution_to_buy(result, original_score, rank, evaluation)
        return result

    def _pass_to_caution(self, result, score, evaluation):
        if score is None or score < self.CAUTION_THRESHOLD:
            result["consensus_block_reasons"].append("decision_score_below_caution_threshold")
            return result
        if len(evaluation["positive"]) < 5:
            result["consensus_block_reasons"].append("pass_positive_evaluators_below_5")
            return result
        result.update(
            {
                "consensus_guard_applied": True,
                "consensus_guard_final_decision": "CAUTION",
                "guarded_decision": "CAUTION",
                "consensus_guard_reason": (
                    "MultiEvaluatorConsensusGuard: multiple evaluators support the horse; "
                    "single negative factor is capped at CAUTION."
                ),
            }
        )
        return result

    def _caution_to_buy(self, result, score, rank, evaluation):
        if rank is None or rank > 3:
            result["consensus_block_reasons"].append("buy_promotion_rank_not_top3")
            return result
        if score is None or score < 0.85:
            result["consensus_block_reasons"].append("decision_score_not_near_buy")
            return result
        if len(evaluation["positive"]) < 6:
            result["consensus_block_reasons"].append("buy_positive_evaluators_below_6")
            return result
        result.update(
            {
                "consensus_guard_applied": True,
                "consensus_guard_final_decision": "BUY",
                "guarded_decision": "BUY",
                "consensus_guard_reason": (
                    "MultiEvaluatorConsensusGuard: AI Top3 with six or more evaluator "
                    "supports and at most one negative evaluator; promoted to BUY."
                ),
            }
        )
        return result

    def _base_result(self, decision, score, rank, evaluation):
        return {
            "consensus_guard_enabled": self.enabled,
            "consensus_guard_candidate": False,
            "consensus_guard_applied": False,
            "consensus_guard_original_decision": decision,
            "consensus_guard_final_decision": decision,
            "original_decision": decision,
            "guarded_decision": decision,
            "original_decision_score": score,
            "ai_rank": rank,
            "consensus_positive_count": len(evaluation["positive"]),
            "consensus_negative_count": len(evaluation["negative"]),
            "consensus_positive_evaluators": evaluation["positive"],
            "consensus_negative_evaluators": evaluation["negative"],
            "consensus_neutral_evaluators": evaluation["neutral"],
            "consensus_missing_evaluators": evaluation["missing"],
            "consensus_evaluator_scores": evaluation["scores"],
            "consensus_block_reasons": [],
            "consensus_guard_reason": "",
        }

    def _evaluate_consensus(self, item):
        positive = []
        negative = []
        neutral = []
        missing = []
        scores = {}
        for evaluator, keys in self.SCORE_KEYS.items():
            value = self._score(item, keys)
            scores[evaluator] = value
            if value is None:
                missing.append(evaluator)
            elif value < 0:
                negative.append(evaluator)
            elif value >= self.POSITIVE_THRESHOLDS[evaluator]:
                positive.append(evaluator)
            else:
                neutral.append(evaluator)
        return {
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "missing": missing,
            "scores": scores,
        }

    def _rank(self, item, context):
        value = context.get("rank")
        if value is None:
            value = item.get("rank") or item.get("final_rank") or item.get("score_rank")
        return self._number_or_none(value)

    def _score(self, item, keys):
        for key in keys:
            value = self._number_or_none(item.get(key))
            if value is not None:
                return value
        return None

    def _risk_text(self, item):
        parts = []
        for key in (
            "decision_risks",
            "risk_factors",
            "final_risks",
            "risks",
            "weaknesses",
            "final_weaknesses",
            "warnings",
            "confidence_reason",
        ):
            value = item.get(key)
            if isinstance(value, list):
                parts.extend(str(part) for part in value if part)
            elif value:
                parts.append(str(value))
        return " ".join(parts)

    def _has_keyword(self, text, keywords):
        return any(keyword in text for keyword in keywords)

    def _is_newcomer_or_jump(self, item, context):
        text = " ".join(
            str(value or "")
            for value in (
                item.get("race_class"),
                item.get("class_name"),
                item.get("race_name"),
                item.get("surface"),
                context.get("race_class"),
                context.get("race_name"),
                context.get("surface"),
            )
        )
        return any(keyword in text for keyword in ("新馬", "障害", "jump"))

    def _number_or_none(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
