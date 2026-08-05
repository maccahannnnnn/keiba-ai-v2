"""PastPerformance Quality Guard production candidate.

The guard is disabled by default and only narrows excessive RaceShape-derived
Decision impact to CAUTION. It never creates BUY, never changes evaluator
scores, and never changes FinalScore or adjusted_score.
"""


ENABLE_PAST_PERFORMANCE_QUALITY_GUARD = False


class PastPerformanceQualityGuard:
    """Limit RaceShape-derived underestimation when past/distance support exists."""

    BUY_THRESHOLD = 0.80
    CAUTION_THRESHOLD = 0.50
    PAST_PERFORMANCE_THRESHOLD = 70.0
    DISTANCE_THRESHOLD = 35.0
    GUARD_MULTIPLIER = 0.75
    DECISION_CAP = "CAUTION"

    TARGET_RISK_TEXTS = (
        "螻暮幕荳榊髄縺・",
        "螻暮幕髱｢縺ｮ荳榊ｮ・",
        "展開不向き",
        "展開面の不安",
    )

    def __init__(self, enabled=ENABLE_PAST_PERFORMANCE_QUALITY_GUARD):
        self.enabled = bool(enabled)

    def apply(self, item=None, context=None, decision=None, decision_score=None):
        """Return guarded decision and trace without mutating input values."""

        item = item if isinstance(item, dict) else {}
        context = context if isinstance(context, dict) else {}
        original_decision = str(decision or "")
        original_score = self._number_or_none(decision_score)
        result = self._base_result(original_decision, original_score)

        if not self.enabled:
            result["quality_guard_skipped_reason"] = "guard_disabled"
            return result
        if original_decision not in {"PASS", "CAUTION"}:
            result["quality_guard_skipped_reason"] = "decision_not_pass_or_caution"
            return result

        past_score = self._score(item, "past_performance_score", "ability_score")
        distance_score = self._score(item, "distance_score")
        if past_score is None or past_score < self.PAST_PERFORMANCE_THRESHOLD:
            result["quality_guard_skipped_reason"] = "past_performance_score_below_threshold"
            return result
        if distance_score is None or distance_score < self.DISTANCE_THRESHOLD:
            result["quality_guard_skipped_reason"] = "distance_score_below_threshold"
            return result

        penalty, penalty_source = self._race_shape_penalty(item)
        if penalty >= 0:
            result["quality_guard_skipped_reason"] = "race_shape_negative_penalty_unavailable"
            return result

        adjusted_score = self._adjusted_decision_score(original_score, penalty, context)
        if adjusted_score is None:
            result["quality_guard_skipped_reason"] = "decision_score_unavailable"
            return result

        result.update(
            {
                "quality_guard_candidate": True,
                "quality_guard_name": "PastPerformanceQualityGuard",
                "original_race_shape_penalty": penalty,
                "adjusted_race_shape_penalty": round(penalty * self.GUARD_MULTIPLIER, 4),
                "guard_multiplier": self.GUARD_MULTIPLIER,
                "past_performance_score": past_score,
                "distance_score": distance_score,
                "adjusted_decision_score": adjusted_score,
                "decision_cap": self.DECISION_CAP,
                "penalty_source": penalty_source,
            }
        )

        if adjusted_score < self.CAUTION_THRESHOLD:
            result["quality_guard_skipped_reason"] = "adjusted_score_below_caution_threshold"
            return result

        guarded_decision = "CAUTION"
        if self._level(guarded_decision) <= self._level(original_decision):
            result["quality_guard_skipped_reason"] = "decision_already_at_or_above_cap"
            return result

        result.update(
            {
                "quality_guard_applied": True,
                "quality_guard_skipped_reason": "",
                "guarded_decision": guarded_decision,
                "guard_reason": (
                    "PastPerformanceQualityGuard: past_performance_score and "
                    "distance_score support limited RaceShape-risk mitigation; "
                    "decision capped at CAUTION."
                ),
            }
        )
        return result

    def _base_result(self, decision, decision_score):
        return {
            "quality_guard_applied": False,
            "quality_guard_candidate": False,
            "quality_guard_name": "PastPerformanceQualityGuard",
            "original_decision": decision,
            "guarded_decision": decision,
            "original_decision_score": decision_score,
            "adjusted_decision_score": decision_score,
            "original_race_shape_penalty": "",
            "adjusted_race_shape_penalty": "",
            "guard_multiplier": self.GUARD_MULTIPLIER,
            "past_performance_score": "",
            "distance_score": "",
            "decision_cap": self.DECISION_CAP,
            "guard_reason": "",
            "quality_guard_skipped_reason": "",
            "penalty_source": "",
        }

    def _race_shape_penalty(self, item):
        for key in ("race_shape_score", "shape_score"):
            score = self._number_or_none(item.get(key))
            if score is not None and score < 0:
                return score, key

        for key in ("decision_risks", "risk_factors", "final_risks", "risks"):
            for text in self._list(item.get(key)):
                if any(target in str(text) for target in self.TARGET_RISK_TEXTS):
                    return -3.0, key
        return 0.0, ""

    def _adjusted_decision_score(self, decision_score, penalty, context):
        if decision_score is None:
            return None
        spread = self._score_spread(context)
        recovery = abs(penalty) * (1.0 - self.GUARD_MULTIPLIER)
        score_delta = (recovery / spread) * 0.45
        return max(0.0, min(1.0, round(decision_score + score_delta, 3)))

    def _score_spread(self, context):
        top = self._number_or_none(context.get("top_score"))
        bottom = self._number_or_none(context.get("bottom_score"))
        if top is None or bottom is None or top == bottom:
            return 1.0
        return max(1.0, top - bottom)

    def _score(self, item, *keys):
        for key in keys:
            value = self._number_or_none(item.get(key))
            if value is not None:
                return value
        return None

    def _level(self, decision):
        return {"PASS": 0, "CAUTION": 1, "BUY": 2}.get(str(decision or ""), 0)

    def _number_or_none(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _list(self, value):
        return value if isinstance(value, list) else []
