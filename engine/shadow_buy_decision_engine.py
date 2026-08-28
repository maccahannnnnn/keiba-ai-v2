"""Shadow BUY Specification v1.0 decision engine.

This engine runs beside production DecisionEngine. It never mutates production
BUY / CAUTION / PASS labels, evaluator scores, final scores, or rankings.
"""

from engine.buy_specification import (
    SHADOW_BUY_SPEC_V1_ENABLED,
    SHADOW_BUY_SPEC_V1_1_ENABLED,
    ShadowConsensusTargetedRescueConfig,
    ShadowBUYSpecV1Config,
)


class ShadowBUYDecisionEngine:
    """Create shadow PLAY/SKIP and shadow BUY labels from existing outputs."""

    SCORE_KEYS = ("adjusted_score", "final_score", "integrated_score", "weighted_score")
    POSITIVE_THRESHOLDS = {
        "Ability": 120.0,
        "PastPerformance": 55.0,
        "Distance": 30.0,
        "CourseShape": 5.0,
        "LapSuitability": 0.0,
        "RaceShape": 0.0,
        "PaceStyle": 10.0,
    }
    STRONG_POSITIVE_MULTIPLIER = 1.25
    STRONG_NEGATIVE_THRESHOLD = -5.0
    SCORE_FIELD_MAP = {
        "Ability": ("total_score", "ability_score"),
        "PastPerformance": ("past_performance_score",),
        "Distance": ("distance_score",),
        "CourseShape": ("course_shape_score", "course_score"),
        "LapSuitability": ("lap_score", "lap_suitability_score"),
        "RaceShape": ("shape_score", "race_shape_score"),
        "PaceStyle": ("pace_style_score", "pace_score", "running_style_score"),
    }
    OPTIONAL_MISSING_EVALUATORS = {"Ability"}
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

    def __init__(
        self,
        enabled=SHADOW_BUY_SPEC_V1_ENABLED,
        config=None,
        use_v1_1=None,
        consensus_rescue_config=None,
    ):
        self.enabled = bool(enabled)
        self.config = config or ShadowBUYSpecV1Config()
        self.use_v1_1 = SHADOW_BUY_SPEC_V1_1_ENABLED if use_v1_1 is None else bool(use_v1_1)
        self.consensus_rescue_config = (
            consensus_rescue_config or ShadowConsensusTargetedRescueConfig.disabled()
        )

    def evaluate(self, race_output=None, horses=None):
        """Return shadow race and horse decisions without mutating inputs."""

        race = race_output if isinstance(race_output, dict) else {}
        rows = [horse for horse in horses if isinstance(horse, dict)] if isinstance(horses, list) else []
        if not self.enabled:
            return {
                "enabled": False,
                "version": self.config.VERSION,
                "shadow_race_decision": "",
                "shadow_play_skip_reason": ["shadow_disabled"],
                "shadow_spec_converged": True,
                "race_record": {},
                "horse_records": [],
                "summary": {"shadow_buy_count": 0},
            }

        ranked = self._with_ranks(rows)
        horse_records = [self._horse_record(row, ranked) for row in ranked]
        candidate_records = [row for row in horse_records if row.get("shadow_buy_candidate")]
        converged = len(candidate_records) <= self.config.MAX_SHADOW_BUY_CANDIDATES
        race_eval = self._race_record(race, ranked, horse_records, candidate_records, converged)

        race_state = race_eval.get("shadow_race_state", race_eval.get("shadow_race_decision", ""))

        shadow_buy_names = set()
        unconverged_candidate_names = set()
        if race_state == "PLAY_CONVERGED" and converged:
            shadow_buy_names = {row["horse_name"] for row in candidate_records}
        elif race_state == "PLAY_UNCONVERGED_4PLUS":
            unconverged_candidate_names = {row["horse_name"] for row in candidate_records}

        for row in horse_records:
            row["shadow_buy"] = row["horse_name"] in shadow_buy_names
            row["shadow_candidate_unconverged"] = row["horse_name"] in unconverged_candidate_names
            row["shadow_status"] = self._horse_shadow_status(row, race_state)
            row["shadow_decision"] = "BUY" if row["shadow_buy"] else row["current_decision"]
            if row["shadow_buy"]:
                row["shadow_buy_reason"] = self._join_reason(
                    row.get("shadow_buy_reason"),
                    "race_play_and_candidate_converged",
                )
            elif row["shadow_candidate_unconverged"]:
                row["shadow_not_buy_reason"] = self._join_reason(
                    row.get("shadow_not_buy_reason"),
                    "candidate_retained_unconverged_4plus",
                )
            elif not row.get("shadow_not_buy_reason"):
                row["shadow_not_buy_reason"] = "race_skip_or_not_candidate"

        race_eval["shadow_buy_count"] = len(shadow_buy_names)
        race_eval["shadow_unconverged_candidate_count"] = len(unconverged_candidate_names)
        race_eval["shadow_buy_horses"] = [
            row["horse_name"] for row in horse_records if row.get("shadow_buy")
        ]
        race_eval["shadow_unconverged_candidate_horses"] = [
            row["horse_name"] for row in horse_records if row.get("shadow_candidate_unconverged")
        ]
        for row in horse_records:
            row["race_id"] = race_eval.get("race_id", "")
        return {
            "enabled": True,
            "version": self.config.VERSION,
            "shadow_race_decision": race_eval.get("shadow_race_decision"),
            "shadow_race_state": race_eval.get("shadow_race_state"),
            "shadow_play_skip_reason": race_eval.get("shadow_play_skip_reason", []),
            "shadow_spec_converged": converged,
            "race_record": race_eval,
            "horse_records": horse_records,
            "summary": self._summary(race_eval, horse_records),
        }

    def _horse_record(self, horse, ranked):
        current_decision = str(horse.get("decision") or "")
        rank = self._rank(horse)
        final_score = self._number_or_none(horse.get("final_score"))
        adjusted_score = self._number_or_none(horse.get("adjusted_score"))
        decision_score = self._number_or_none(horse.get("decision_score"))
        score_value = self._score_value(horse)
        top_score = self._score_value(ranked[0]) if ranked else None
        next_score = self._next_score(rank, ranked)
        evaluator_view = self._evaluator_view(horse)
        risk_items = self._risks(horse)
        conflict_items = self._list(horse.get("conflict_factors"))

        absolute = (
            current_decision == "BUY"
            or (
                decision_score is not None
                and decision_score >= self.config.MIN_DECISION_SCORE
                and final_score is not None
                and final_score >= self.config.MIN_FINAL_SCORE
                and adjusted_score is not None
                and adjusted_score >= self.config.MIN_ADJUSTED_SCORE
            )
        )
        relative = (
            rank is not None
            and rank <= self.config.MAX_AI_RANK
            and score_value is not None
            and top_score is not None
            and (top_score - score_value) <= max(35.0, top_score * 0.22)
        )
        reliability = (
            len(evaluator_view["positive"]) >= self.config.MIN_POSITIVE_EVALUATORS
            and len(evaluator_view["negative"]) <= self.config.MAX_NEGATIVE_EVALUATORS
            and not evaluator_view["blocking_missing"]
        )
        consensus_rescue = self._consensus_targeted_rescue(
            reliability,
            absolute,
            relative,
            evaluator_view["profile"],
        )
        effective_reliability = reliability or consensus_rescue["rescued_consensus_pass"]
        risk_guard = (
            not self._has_keyword(" ".join(risk_items), self.SEVERE_RISK_KEYWORDS)
            and not self._has_keyword(" ".join(risk_items), self.DATA_LIMITATION_KEYWORDS)
            and len(risk_items) <= self.config.MAX_RISK_COUNT
            and len(conflict_items) <= self.config.MAX_CONFLICT_COUNT
        )
        if consensus_rescue["rescued_consensus_pass"] and not risk_guard:
            consensus_rescue["rescued_consensus_pass"] = False
            consensus_rescue["consensus_rescue_applied"] = False
            consensus_rescue["consensus_rescue_reason"] = self._join_reason(
                consensus_rescue.get("consensus_rescue_reason"),
                "risk_guard_failed_after_consensus_rescue",
            )
            effective_reliability = reliability

        block_reasons = []
        if not absolute:
            block_reasons.append("absolute_quality_failed")
        if not relative:
            block_reasons.append("relative_advantage_failed")
        if not effective_reliability:
            block_reasons.append("reliability_failed")
        if not risk_guard:
            block_reasons.append("risk_guard_failed")

        candidate = bool(absolute and relative and effective_reliability and risk_guard)
        return {
            "race_id": "",
            "horse_number": horse.get("horse_number"),
            "horse_name": horse.get("horse_name") or horse.get("name") or "",
            "current_decision": current_decision,
            "shadow_decision": current_decision,
            "current_buy": current_decision == "BUY",
            "shadow_buy": False,
            "final_score": final_score,
            "adjusted_score": adjusted_score,
            "decision_score": decision_score,
            "ai_rank": rank,
            "confidence": horse.get("confidence_level")
            or horse.get("confidence")
            or horse.get("confidence_reason"),
            "consensus": {
                "positive_evaluators": evaluator_view["positive"],
                "negative_evaluators": evaluator_view["negative"],
                "neutral_evaluators": evaluator_view["neutral"],
                "missing_evaluators": evaluator_view["missing"],
                "blocking_missing_evaluators": evaluator_view["blocking_missing"],
                "strong_positive_evaluators": evaluator_view["strong_positive"],
                "strong_negative_evaluators": evaluator_view["strong_negative"],
                "strong_matches": self._list(horse.get("strong_matches")),
                "weak_matches": self._list(horse.get("weak_matches")),
                "conflict_factors": conflict_items,
            },
            "consensus_profile": evaluator_view["profile"],
            "consensus_rescue": consensus_rescue,
            "risk_summary": risk_items,
            "absolute_quality_pass": absolute,
            "relative_advantage_pass": relative,
            "reliability_pass": reliability,
            "effective_reliability_pass": effective_reliability,
            "risk_guard_pass": risk_guard,
            "shadow_buy_candidate": candidate,
            "shadow_candidate_unconverged": False,
            "shadow_status": "SHADOW_NOT_BUY" if not candidate else "SHADOW_BUY_CANDIDATE",
            "shadow_buy_reason": self._candidate_reason(
                absolute,
                relative,
                effective_reliability,
                risk_guard,
                evaluator_view,
                top_score,
                score_value,
                next_score,
            )
            if candidate
            else "",
            "shadow_not_buy_reason": ";".join(block_reasons),
            "finish_position": None,
            "top3_result": None,
        }

    def _consensus_targeted_rescue(self, original_consensus_pass, absolute, relative, profile):
        config = self.consensus_rescue_config
        failure_reasons = []
        if original_consensus_pass:
            failure_reasons.append("original_consensus_pass")
        if profile.get("positive_evaluator_count") != config.MIN_POSITIVE_COUNT:
            failure_reasons.append("positive_count_not_target")
        if profile.get("negative_evaluator_count", 0) > config.MAX_NEGATIVE_COUNT:
            failure_reasons.append("negative_count_above_target")
        if profile.get("strong_negative_count", 0) > config.MAX_STRONG_NEGATIVE_COUNT:
            failure_reasons.append("strong_negative_present")
        if not absolute:
            failure_reasons.append("absolute_quality_failed")
        if not relative:
            failure_reasons.append("relative_advantage_failed")

        base_target = (
            bool(getattr(config, "ENABLED", False))
            and not original_consensus_pass
            and profile.get("positive_evaluator_count") == config.MIN_POSITIVE_COUNT
            and profile.get("negative_evaluator_count", 0) <= config.MAX_NEGATIVE_COUNT
            and profile.get("strong_negative_count", 0) <= config.MAX_STRONG_NEGATIVE_COUNT
            and absolute
            and relative
        )
        method_pass = False
        method = getattr(config, "METHOD", "disabled")
        if base_target and method == "strong_positive":
            method_pass = (
                profile.get("strong_positive_count", 0)
                >= config.MIN_STRONG_POSITIVE_COUNT
            )
            if not method_pass:
                failure_reasons.append("strong_positive_below_rescue_min")
        elif base_target and method == "net_consensus":
            method_pass = (
                profile.get("net_consensus_score", 0.0)
                >= config.MIN_NET_CONSENSUS_SCORE
            )
            if not method_pass:
                failure_reasons.append("net_consensus_below_rescue_min")
        elif base_target and method == "strong_positive_and_net":
            strong_pass = (
                profile.get("strong_positive_count", 0)
                >= config.MIN_STRONG_POSITIVE_COUNT
            )
            net_pass = (
                profile.get("net_consensus_score", 0.0)
                >= config.MIN_NET_CONSENSUS_SCORE
            )
            method_pass = strong_pass and net_pass
            if not strong_pass:
                failure_reasons.append("strong_positive_below_rescue_min")
            if not net_pass:
                failure_reasons.append("net_consensus_below_rescue_min")
        elif base_target:
            failure_reasons.append("rescue_method_disabled")

        applied = bool(base_target and method_pass)
        return {
            "consensus_rescue_applied": applied,
            "consensus_rescue_method": method if applied else "",
            "consensus_rescue_reason": (
                "targeted_consensus_boundary_rescue"
                if applied
                else ";".join(failure_reasons)
            ),
            "original_consensus_pass": original_consensus_pass,
            "original_consensus_failure_reasons": ";".join(failure_reasons),
            "rescued_consensus_pass": applied,
            "rescue_config_name": getattr(config, "CONFIG_NAME", "disabled"),
        }

    def _race_record(self, race, ranked, horse_records, candidates, converged):
        current_buy_count = sum(1 for row in ranked if row.get("decision") == "BUY")
        scores = [self._score_value(row) for row in ranked]
        scores = [score for score in scores if score is not None]
        top_group_separation = 0.0
        if len(scores) >= 4:
            top_group_separation = round(scores[0] - scores[3], 3)
        field_competitiveness = "unknown"
        if len(scores) >= 5:
            spread = max(scores) - min(scores)
            field_competitiveness = "high" if spread < 60 else "medium" if spread < 110 else "low"

        skip_reasons = []
        if len(candidates) < self.config.MIN_RACE_CANDIDATES_FOR_PLAY:
            skip_reasons.append("skip_no_shadow_buy_candidate")
        if not scores:
            skip_reasons.append("skip_insufficient_score_distribution")
        if field_competitiveness == "high" and top_group_separation < 12:
            skip_reasons.append("skip_field_too_competitive")

        if not converged and len(candidates) >= 4:
            state = "PLAY_UNCONVERGED_4PLUS"
            decision = "PLAY"
            reasons = ["play_unconverged_4plus"]
        elif skip_reasons:
            state = "SKIP"
            decision = "SKIP"
            reasons = skip_reasons
        else:
            state = "PLAY_CONVERGED"
            decision = "PLAY"
            reasons = ["sufficient_quality_and_converged_candidates"]

        return {
            "race_id": race.get("race_id", ""),
            "race_decision_current": race.get("race_decision", ""),
            "shadow_race_decision": decision,
            "shadow_race_state": state,
            "shadow_play_skip_reason": reasons,
            "current_buy_count": current_buy_count,
            "shadow_candidate_count": len(candidates),
            "shadow_buy_count": 0,
            "shadow_unconverged_candidate_count": 0,
            "shadow_spec_converged": converged,
            "field_competitiveness": field_competitiveness,
            "top_group_separation": top_group_separation,
            "race_confidence_summary": race.get("race_confidence_summary")
            or race.get("race_confidence")
            or "",
            "race_risk_summary": race.get("race_risk_summary") or race.get("race_decision_risks") or [],
            "unconverged_reason": "" if converged else "more_than_3_shadow_buy_candidates",
        }

    def _summary(self, race_record, horse_records):
        return {
            "shadow_race_decision": race_record.get("shadow_race_decision"),
            "shadow_race_state": race_record.get("shadow_race_state"),
            "shadow_buy_count": race_record.get("shadow_buy_count", 0),
            "shadow_unconverged_candidate_count": race_record.get(
                "shadow_unconverged_candidate_count", 0
            ),
            "shadow_spec_converged": race_record.get("shadow_spec_converged", True),
            "candidate_count": race_record.get(
                "shadow_candidate_count",
                sum(1 for row in horse_records if row.get("shadow_buy_candidate")),
            ),
            "current_buy_count": race_record.get("current_buy_count", 0),
        }

    def _horse_shadow_status(self, row, race_state):
        if row.get("shadow_buy"):
            return "SHADOW_BUY"
        if row.get("shadow_candidate_unconverged"):
            return "SHADOW_BUY_CANDIDATE_UNCONVERGED"
        if row.get("shadow_buy_candidate"):
            return "SHADOW_NOT_BUY"
        return "SHADOW_REJECTED"

    def _with_ranks(self, rows):
        ranked = sorted(
            rows,
            key=lambda row: (
                self._score_value(row) if self._score_value(row) is not None else -999999,
                -self._number(row.get("rank"), 999),
            ),
            reverse=True,
        )
        output = []
        for index, row in enumerate(ranked, start=1):
            copy = dict(row)
            copy.setdefault("rank", index)
            output.append(copy)
        return output

    def _evaluator_view(self, horse):
        positive = []
        negative = []
        neutral = []
        missing = []
        strong_positive = []
        strong_negative = []
        scores = {}
        for evaluator, keys in self.SCORE_FIELD_MAP.items():
            value = self._score(horse, keys)
            scores[evaluator] = value
            if value is None:
                missing.append(evaluator)
            elif value < 0:
                negative.append(evaluator)
                if value <= self.STRONG_NEGATIVE_THRESHOLD:
                    strong_negative.append(evaluator)
            elif value >= self.POSITIVE_THRESHOLDS[evaluator]:
                positive.append(evaluator)
                if value >= self._strong_positive_threshold(evaluator):
                    strong_positive.append(evaluator)
            else:
                neutral.append(evaluator)
        profile = self._consensus_profile(
            positive,
            negative,
            neutral,
            missing,
            strong_positive,
            strong_negative,
            scores,
        )
        return {
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "missing": missing,
            "strong_positive": strong_positive,
            "strong_negative": strong_negative,
            "blocking_missing": [
                item for item in missing if item not in self.OPTIONAL_MISSING_EVALUATORS
            ],
            "scores": scores,
            "profile": profile,
        }

    def _strong_positive_threshold(self, evaluator):
        threshold = self.POSITIVE_THRESHOLDS[evaluator]
        if threshold <= 0:
            return threshold + 5.0
        return threshold * self.STRONG_POSITIVE_MULTIPLIER

    def _consensus_profile(
        self,
        positive,
        negative,
        neutral,
        missing,
        strong_positive,
        strong_negative,
        scores,
    ):
        evaluated_count = len(positive) + len(negative) + len(neutral)
        total_count = evaluated_count + len(missing)
        positive_ratio = len(positive) / evaluated_count if evaluated_count else 0.0
        negative_ratio = len(negative) / evaluated_count if evaluated_count else 0.0
        net_consensus_score = (
            len(positive)
            - len(negative)
            + (0.5 * len(strong_positive))
            - (0.5 * len(strong_negative))
        )
        return {
            "positive_evaluator_count": len(positive),
            "negative_evaluator_count": len(negative),
            "neutral_evaluator_count": len(neutral),
            "missing_evaluator_count": len(missing),
            "evaluated_evaluator_count": evaluated_count,
            "total_evaluator_count": total_count,
            "strong_positive_count": len(strong_positive),
            "strong_negative_count": len(strong_negative),
            "positive_ratio": round(positive_ratio, 3),
            "negative_ratio": round(negative_ratio, 3),
            "net_consensus_score": round(net_consensus_score, 3),
            "positive_evaluators": list(positive),
            "negative_evaluators": list(negative),
            "neutral_evaluators": list(neutral),
            "missing_evaluators": list(missing),
            "strong_positive_evaluators": list(strong_positive),
            "strong_negative_evaluators": list(strong_negative),
            "score_snapshot": dict(scores),
        }

    def _candidate_reason(
        self,
        absolute,
        relative,
        reliability,
        risk_guard,
        evaluator_view,
        top_score,
        score_value,
        next_score,
    ):
        reasons = []
        if absolute:
            reasons.append("absolute_quality")
        if relative:
            top_gap = None if top_score is None or score_value is None else round(top_score - score_value, 3)
            next_gap = None if next_score is None or score_value is None else round(score_value - next_score, 3)
            reasons.append(f"relative_advantage(top_gap={top_gap},next_gap={next_gap})")
        if reliability:
            reasons.append("evaluator_consensus:" + ",".join(evaluator_view["positive"]))
        if risk_guard:
            reasons.append("risk_guard_clear")
        return ";".join(reasons)

    def _score_value(self, horse):
        for key in self.SCORE_KEYS:
            value = self._number_or_none(horse.get(key))
            if value is not None:
                return value
        return None

    def _next_score(self, rank, ranked):
        if rank is None:
            return None
        index = int(rank)
        if index < 1 or index >= len(ranked):
            return None
        return self._score_value(ranked[index])

    def _rank(self, horse):
        return self._number_or_none(horse.get("rank") or horse.get("final_rank") or horse.get("score_rank"))

    def _score(self, horse, keys):
        for key in keys:
            value = self._number_or_none(horse.get(key))
            if value is not None:
                return value
        return None

    def _risks(self, horse):
        values = []
        for key in (
            "decision_risks",
            "final_risks",
            "risk_factors",
            "risk_reasons",
            "risk_summary",
            "warnings",
        ):
            values.extend(str(value) for value in self._list(horse.get(key)) if value)
        return self._unique(values)

    def _has_keyword(self, text, keywords):
        return any(keyword in str(text) for keyword in keywords)

    def _join_reason(self, existing, reason):
        if not existing:
            return reason
        return f"{existing};{reason}"

    def _number_or_none(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _number(self, value, default=0.0):
        number = self._number_or_none(value)
        return default if number is None else number

    def _list(self, value):
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        return [value]

    def _unique(self, values):
        seen = set()
        output = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            output.append(value)
        return output
