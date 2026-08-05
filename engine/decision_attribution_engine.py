"""Explain why a horse did or did not reach BUY without changing decisions."""

from collections import Counter

from engine.decision_root_cause_engine import DecisionRootCauseEngine


class DecisionAttributionEngine:
    """Create post-decision attribution diagnostics for each horse."""

    ATTRIBUTION_VERSION = "phase_e_step1_v1"
    BUY_THRESHOLD = 0.80
    CAUTION_THRESHOLD = 0.50

    EVALUATOR_SCORES = [
        ("PastPerformanceEvaluator", "past_performance_score", 30, 70),
        ("DistanceEvaluator", "distance_score", 20, 35),
        ("TrackConditionSuitabilityEvaluator", "track_condition_score", -1, 18),
        ("CourseShapeEvaluator", "course_shape_score", -4, 8),
        ("RaceShapeEvaluator", "shape_score", -4, 8),
        ("PaceStyleEvaluator", "pace_style_score", 10, 20),
        ("LapSuitabilityEvaluator", "lap_score", -4, 8),
        ("BloodlineEvaluator", "bloodline_score", 0, 20),
        ("TrackBiasEvaluator", "track_bias_score", -1, 4),
        ("ImpactEvaluator", "impact_score", -1, 8),
        ("ConsistencyEngine", "consistency_score", 0.5, 0.85),
    ]

    DECISION_FIXED_TARGET = "DecisionEngine"

    def __init__(self):
        self.decision_root_cause_engine = DecisionRootCauseEngine()

    def evaluate_many(self, horse_results=None, race_context=None):
        """Attach attribution dictionaries in input order."""

        rows = horse_results if isinstance(horse_results, list) else []
        context = race_context if isinstance(race_context, dict) else {}
        ranked = sorted(
            [row for row in rows if isinstance(row, dict)],
            key=lambda row: (
                self._to_float(
                    row.get("adjusted_score")
                    or row.get("integrated_score")
                    or row.get("weighted_score")
                    or row.get("final_score")
                )
                or 0.0,
                self._to_int(row.get("horse_number")) or 0,
            ),
            reverse=True,
        )
        rank_map = {id(row): index for index, row in enumerate(ranked, start=1)}
        attributions = []
        warnings = []
        for row in rows:
            if not isinstance(row, dict):
                attributions.append(self._empty_attribution("non_dict_row"))
                warnings.append("non_dict_row")
                continue
            attribution = self.evaluate(row, context, rank_map.get(id(row)))
            root_cause = self.decision_root_cause_engine.analyze(row, attribution)
            attribution["decision_root_cause"] = root_cause
            row["decision_root_cause"] = root_cause
            row["decision_attribution"] = attribution
            attributions.append(attribution)
        return {
            "attribution_version": self.ATTRIBUTION_VERSION,
            "horse_attributions": attributions,
            "summary": self.summary(attributions),
            "warnings": warnings,
        }

    def evaluate(self, horse, race_context=None, rank=None):
        """Return one attribution dictionary without mutating input values."""

        item = horse if isinstance(horse, dict) else {}
        context = race_context if isinstance(race_context, dict) else {}
        decision = str(item.get("decision") or "").upper()
        decision_score = self._to_float(item.get("decision_score")) or 0.0
        overall_rank = self._rank(item, rank)
        blockers = self._blockers(item, decision_score, overall_rank)
        supporters = self._supporters(item, decision_score, overall_rank)
        fixed_blockers = self._fixed_decision_blockers(item, decision, decision_score, overall_rank)
        if decision != "BUY":
            blockers = fixed_blockers + blockers
        primary_blocker, secondary_blockers = self._primary_and_secondary(blockers)
        primary_supporter, secondary_supporters = self._primary_and_secondary(supporters)
        if decision != "BUY" and not primary_blocker:
            primary_blocker = self._unknown_detail(
                "No specific blocker had enough evidence",
                target_type="Unknown",
            )
        if decision == "BUY" and not primary_supporter:
            primary_supporter = self._unknown_detail(
                "No specific supporter had enough evidence",
                target_type="Unknown",
            )

        distance_to_buy = max(0.0, round(self.BUY_THRESHOLD - decision_score, 3))
        distance_to_caution = max(0.0, round(self.CAUTION_THRESHOLD - decision_score, 3))
        decision_margin = round(decision_score - self.BUY_THRESHOLD, 3)
        cause_count = self._cause_count(primary_blocker, secondary_blockers, decision)
        counterfactuals = self._counterfactuals(
            decision=decision,
            distance_to_buy=distance_to_buy,
            primary_blocker=primary_blocker,
            blockers=blockers,
        )
        unknown_blockers = []
        if decision != "BUY" and primary_blocker.get("target") == "UNKNOWN":
            unknown_blockers.append(primary_blocker)
        attribution_confidence = self._attribution_confidence(
            primary_blocker if decision != "BUY" else primary_supporter,
            secondary_blockers if decision != "BUY" else secondary_supporters,
            unknown_blockers,
        )

        result = {
            "decision": decision,
            "race_decision": context.get("race_decision") or item.get("race_decision"),
            "final_score": self._to_float(item.get("final_score")),
            "adjusted_score": self._to_float(item.get("adjusted_score")),
            "decision_score": decision_score,
            "overall_rank": overall_rank,
            "buy_threshold": self.BUY_THRESHOLD,
            "caution_threshold": self.CAUTION_THRESHOLD,
            "distance_to_buy": distance_to_buy,
            "distance_to_caution": distance_to_caution,
            "decision_margin": decision_margin,
            "primary_blocker": primary_blocker if decision != "BUY" else {},
            "secondary_blockers": secondary_blockers if decision != "BUY" else [],
            "primary_supporter": primary_supporter if decision == "BUY" else {},
            "secondary_supporters": secondary_supporters if decision == "BUY" else [],
            "decision_rules_triggered": self._rules_triggered(
                item,
                decision,
                decision_score,
                overall_rank,
            ),
            "decision_rules_not_met": self._rules_not_met(
                item,
                decision,
                decision_score,
                overall_rank,
            ),
            "rank_blocker": self._rank_blocker(item, overall_rank),
            "risk_blocker": self._risk_blocker(item),
            "major_penalty_blocker": self._major_penalty_blocker(item),
            "confidence_blocker": self._confidence_blocker(item),
            "score_blocker": self._score_blocker(decision_score),
            "relative_evaluation_blocker": self._relative_evaluation_blocker(item, overall_rank),
            "unknown_blockers": unknown_blockers,
            "attribution_confidence": attribution_confidence,
            "counterfactuals": counterfactuals,
            "counterfactual_feasible": any(
                item.get("feasibility") in {"HIGH", "MEDIUM"} for item in counterfactuals
            ),
            "cause_count_type": "multiple" if cause_count > 1 else "single",
            "fixed_decision_blocker": any(
                detail.get("target_type") == "Decision" for detail in fixed_blockers
            ),
            "attribution_version": self.ATTRIBUTION_VERSION,
        }
        return result

    def summary(self, attributions):
        rows = [row for row in attributions if isinstance(row, dict)]
        decisions = Counter(row.get("decision") for row in rows)
        blocker_counter = Counter()
        supporter_counter = Counter()
        confidence_counter = Counter()
        unknown_count = 0
        counterfactual_count = 0
        root_counter = Counter()
        gate_counter = Counter()
        distance_values = []
        fixed_blockers = 0
        single_count = 0
        multiple_count = 0
        missing_fields = 0
        for row in rows:
            confidence_counter[row.get("attribution_confidence") or "UNKNOWN"] += 1
            if row.get("decision") != "BUY":
                blocker = row.get("primary_blocker") if isinstance(row.get("primary_blocker"), dict) else {}
                blocker_counter[blocker.get("target") or "UNKNOWN"] += 1
                distance = self._to_float(row.get("distance_to_buy"))
                if distance is not None:
                    distance_values.append(distance)
            else:
                supporter = row.get("primary_supporter") if isinstance(row.get("primary_supporter"), dict) else {}
                supporter_counter[supporter.get("target") or "UNKNOWN"] += 1
            if row.get("unknown_blockers"):
                unknown_count += 1
            root = row.get("decision_root_cause") if isinstance(row.get("decision_root_cause"), dict) else {}
            root_counter[root.get("root_primary_candidate") or "UNKNOWN"] += 1
            gate_counter[root.get("decision_gate") or "UNKNOWN"] += 1
            counterfactual_count += len(row.get("counterfactuals") or [])
            if row.get("fixed_decision_blocker"):
                fixed_blockers += 1
            if row.get("cause_count_type") == "multiple":
                multiple_count += 1
            else:
                single_count += 1
            missing_fields += self._missing_required_field_count(row)
        return {
            "attribution_count": len(rows),
            "decision_counts": dict(decisions),
            "primary_blockers": dict(blocker_counter.most_common()),
            "primary_supporters": dict(supporter_counter.most_common()),
            "primary_root_causes": dict(root_counter.most_common()),
            "decision_gates": dict(gate_counter.most_common()),
            "attribution_confidence": dict(confidence_counter),
            "unknown_count": unknown_count,
            "counterfactual_count": counterfactual_count,
            "fixed_decision_blocker_count": fixed_blockers,
            "single_cause_count": single_count,
            "multiple_cause_count": multiple_count,
            "average_distance_to_buy": self._average(distance_values),
            "missing_required_field_count": missing_fields,
        }

    def _blockers(self, item, decision_score, rank):
        blockers = []
        for target, key, low_threshold, high_threshold in self.EVALUATOR_SCORES:
            value = self._to_float(item.get(key))
            if value is None:
                continue
            if self._is_low_value(value, low_threshold, key):
                severity = self._low_severity(value, low_threshold, key)
                blockers.append(
                    self._detail(
                        target=target,
                        target_type=self._target_type(target),
                        effect="blocked_buy",
                        importance=min(1.0, 0.35 + severity),
                        reason=f"{key}={value:g} is below the review threshold {low_threshold:g}",
                        evidence=[f"{key}={value:g}", f"decision_score={decision_score:g}"],
                        counter_evidence=self._counter_evidence_for_score(value, high_threshold, key),
                        confidence="MEDIUM" if severity >= 0.25 else "LOW",
                    )
                )
        if rank is not None and rank > 5:
            blockers.append(self._rank_blocker_detail(rank))
        if item.get("buy_suppressed") or item.get("low_rank_buy_guard_applied"):
            blockers.append(self._decision_guard_detail(item, rank))
        return blockers

    def _supporters(self, item, decision_score, rank):
        supporters = []
        for target, key, _low_threshold, high_threshold in self.EVALUATOR_SCORES:
            value = self._to_float(item.get(key))
            if value is None:
                continue
            if self._is_high_value(value, high_threshold, key):
                severity = self._high_severity(value, high_threshold, key)
                supporters.append(
                    self._detail(
                        target=target,
                        target_type=self._target_type(target),
                        effect="supported_buy",
                        importance=min(1.0, 0.35 + severity),
                        reason=f"{key}={value:g} supported the BUY decision",
                        evidence=[f"{key}={value:g}", f"decision_score={decision_score:g}"],
                        counter_evidence=[],
                        confidence="MEDIUM" if severity >= 0.20 else "LOW",
                    )
                )
        if decision_score >= self.BUY_THRESHOLD:
            supporters.append(
                self._detail(
                    target="DecisionEngine",
                    target_type="Decision",
                    effect="supported_buy",
                    importance=min(1.0, 0.45 + (decision_score - self.BUY_THRESHOLD)),
                    reason="decision_score reached the BUY threshold",
                    evidence=[f"decision_score={decision_score:g}", f"rank={rank}"],
                    counter_evidence=[],
                    confidence="MEDIUM",
                )
            )
        return supporters

    def _fixed_decision_blockers(self, item, decision, decision_score, rank):
        blockers = []
        if decision_score < self.BUY_THRESHOLD:
            blockers.append(
                self._detail(
                    target="DecisionEngine",
                    target_type="Decision",
                    effect="fixed_threshold_blocker",
                    importance=min(1.0, 0.45 + (self.BUY_THRESHOLD - decision_score)),
                    reason="decision_score did not reach the BUY threshold",
                    evidence=[f"decision_score={decision_score:g}", "buy_threshold=0.8"],
                    counter_evidence=[],
                    confidence="HIGH" if decision_score < 0.72 else "MEDIUM",
                )
            )
        risk_count = self._to_int(item.get("risk_count")) or 0
        conflict_count = self._to_int(item.get("conflict_count")) or 0
        if risk_count >= 3:
            blockers.append(self._risk_blocker_detail(item, risk_count))
        if conflict_count >= 3:
            blockers.append(self._conflict_blocker_detail(item, conflict_count))
        if rank is not None and rank > 5 and decision == "CAUTION":
            blockers.append(self._rank_blocker_detail(rank))
        return blockers

    def _primary_and_secondary(self, items):
        details = [item for item in items if isinstance(item, dict)]
        details.sort(
            key=lambda item: (
                -float(item.get("importance") or 0),
                str(item.get("target") or ""),
            )
        )
        for index, item in enumerate(details, start=1):
            item["rank"] = index
        if not details:
            return {}, []
        return details[0], details[1:4]

    def _counterfactuals(self, decision, distance_to_buy, primary_blocker, blockers):
        if decision == "BUY" or not primary_blocker or primary_blocker.get("target") == "UNKNOWN":
            return []
        feasibility = "HIGH" if distance_to_buy <= 0.05 else "MEDIUM" if distance_to_buy <= 0.12 else "LOW"
        result = [
            {
                "target": primary_blocker.get("target"),
                "target_type": primary_blocker.get("target_type"),
                "needed_change": round(distance_to_buy, 3),
                "condition": "decision_score would need to reach 0.80",
                "feasibility": feasibility,
                "note": "diagnostic only; no score or threshold change is proposed",
            }
        ]
        if len(blockers) > 1:
            result.append(
                {
                    "target": "MultiEvaluator",
                    "target_type": "Composite",
                    "needed_change": round(distance_to_buy, 3),
                    "condition": "multiple blockers would need to improve together",
                    "feasibility": "LOW" if distance_to_buy > 0.08 else "MEDIUM",
                    "note": "diagnostic only; no implementation change is proposed",
                }
            )
        return result

    def _rules_triggered(self, item, decision, decision_score, rank):
        rules = []
        if decision == "BUY":
            rules.append("buy_decision")
        if decision_score >= self.BUY_THRESHOLD:
            rules.append("decision_score_buy_threshold_met")
        if decision_score >= self.CAUTION_THRESHOLD:
            rules.append("decision_score_caution_threshold_met")
        if item.get("low_rank_buy_guard_applied"):
            rules.append("low_rank_buy_guard")
        if item.get("buy_suppressed"):
            rules.append("track_bias_buy_guard")
        if item.get("top_score_pass_rescued"):
            rules.append("top_score_pass_rescue")
        if rank is not None and rank <= 5:
            rules.append("top5_rank")
        return rules

    def _rules_not_met(self, item, decision, decision_score, rank):
        rules = []
        if decision != "BUY":
            if decision_score < self.BUY_THRESHOLD:
                rules.append("decision_score_below_buy_threshold")
            if rank is not None and rank > 5:
                rules.append("outside_top5_rank")
            if self._to_int(item.get("risk_count")) and self._to_int(item.get("risk_count")) >= 3:
                rules.append("risk_count_buy_condition_not_met")
            if self._to_int(item.get("conflict_count")) and self._to_int(item.get("conflict_count")) >= 2:
                rules.append("conflict_buy_condition_not_met")
        return rules

    def _rank_blocker(self, item, rank):
        if rank is None or rank <= 5:
            return {}
        return self._rank_blocker_detail(rank)

    def _rank_blocker_detail(self, rank):
        return self._detail(
            target="DecisionEngine",
            target_type="Decision",
            effect="rank_blocker",
            importance=0.72 if rank > 8 else 0.58,
            reason="AI rank was outside the Top5 safety range",
            evidence=[f"rank={rank}"],
            counter_evidence=[],
            confidence="MEDIUM",
        )

    def _risk_blocker(self, item):
        count = self._to_int(item.get("risk_count")) or 0
        if count <= 0:
            return {}
        return self._risk_blocker_detail(item, count)

    def _risk_blocker_detail(self, item, count):
        return self._detail(
            target="DecisionEngine",
            target_type="Decision",
            effect="risk_blocker",
            importance=min(1.0, 0.35 + count * 0.08),
            reason="Decision risk items reduced BUY confidence",
            evidence=[f"risk_count={count}"] + self._list_text(item.get("risk_items"))[:3],
            counter_evidence=[],
            confidence="MEDIUM",
        )

    def _conflict_blocker_detail(self, item, count):
        return self._detail(
            target="DecisionEngine",
            target_type="Decision",
            effect="conflict_blocker",
            importance=min(1.0, 0.42 + count * 0.09),
            reason="Decision conflict items reduced BUY confidence",
            evidence=[f"conflict_count={count}"] + self._list_text(item.get("conflict_items"))[:3],
            counter_evidence=[],
            confidence="MEDIUM",
        )

    def _major_penalty_blocker(self, item):
        diagnostics = item.get("decision_diagnostics") if isinstance(item.get("decision_diagnostics"), dict) else {}
        major_count = self._to_int(diagnostics.get("major_risk_count"))
        if major_count is None:
            major_count = self._to_int(item.get("major_risk_count"))
        if not major_count:
            return {}
        return self._detail(
            target="DecisionEngine",
            target_type="Decision",
            effect="major_penalty_blocker",
            importance=min(1.0, 0.50 + major_count * 0.12),
            reason="major risks were present in Decision diagnostics",
            evidence=[f"major_risk_count={major_count}"],
            counter_evidence=[],
            confidence="HIGH" if major_count >= 2 else "MEDIUM",
        )

    def _confidence_blocker(self, item):
        level = str(item.get("confidence_level") or "").lower()
        if level not in {"low", "very_low"}:
            return {}
        return self._detail(
            target="ConfidenceEngine",
            target_type="Decision",
            effect="confidence_blocker",
            importance=0.55 if level == "low" else 0.72,
            reason="confidence level was low",
            evidence=[f"confidence_level={level}"],
            counter_evidence=[],
            confidence="MEDIUM",
        )

    def _score_blocker(self, decision_score):
        if decision_score >= self.BUY_THRESHOLD:
            return {}
        return self._detail(
            target="DecisionEngine",
            target_type="Decision",
            effect="score_blocker",
            importance=min(1.0, 0.45 + (self.BUY_THRESHOLD - decision_score)),
            reason="decision_score remained below BUY threshold",
            evidence=[f"decision_score={decision_score:g}", "buy_threshold=0.8"],
            counter_evidence=[],
            confidence="HIGH" if decision_score < 0.70 else "MEDIUM",
        )

    def _relative_evaluation_blocker(self, item, rank):
        if rank is None or rank <= 5:
            return {}
        return self._detail(
            target="DecisionEngine",
            target_type="Decision",
            effect="relative_evaluation_blocker",
            importance=0.52,
            reason="relative rank was weaker than top candidates",
            evidence=[f"rank={rank}", f"adjusted_score={item.get('adjusted_score')}"],
            counter_evidence=[],
            confidence="MEDIUM",
        )

    def _decision_guard_detail(self, item, rank):
        reason = (
            item.get("low_rank_buy_guard_reason")
            or item.get("buy_suppression_reason")
            or "Decision guard changed BUY to CAUTION"
        )
        return self._detail(
            target="DecisionEngine",
            target_type="Decision",
            effect="guard_blocker",
            importance=0.82,
            reason=reason,
            evidence=[f"rank={rank}", f"decision_score={item.get('decision_score')}"],
            counter_evidence=[],
            confidence="HIGH",
        )

    def _detail(
        self,
        target,
        target_type,
        effect,
        importance,
        reason,
        evidence=None,
        counter_evidence=None,
        confidence="LOW",
    ):
        return {
            "target": target,
            "target_type": target_type,
            "effect": effect,
            "importance": round(max(0.0, min(1.0, float(importance or 0))), 3),
            "rank": None,
            "reason": reason,
            "evidence": self._list_text(evidence),
            "counter_evidence": self._list_text(counter_evidence),
            "confidence": confidence,
        }

    def _unknown_detail(self, reason, target_type="Unknown"):
        return self._detail(
            target="UNKNOWN",
            target_type=target_type,
            effect="unknown",
            importance=0.0,
            reason=reason,
            evidence=[],
            counter_evidence=[],
            confidence="LOW",
        )

    def _empty_attribution(self, reason):
        item = self._unknown_detail(reason)
        return {
            "decision": "",
            "race_decision": "",
            "final_score": None,
            "adjusted_score": None,
            "decision_score": 0.0,
            "overall_rank": None,
            "buy_threshold": self.BUY_THRESHOLD,
            "caution_threshold": self.CAUTION_THRESHOLD,
            "distance_to_buy": self.BUY_THRESHOLD,
            "distance_to_caution": self.CAUTION_THRESHOLD,
            "decision_margin": -self.BUY_THRESHOLD,
            "primary_blocker": item,
            "secondary_blockers": [],
            "primary_supporter": {},
            "secondary_supporters": [],
            "decision_rules_triggered": [],
            "decision_rules_not_met": [],
            "rank_blocker": {},
            "risk_blocker": {},
            "major_penalty_blocker": {},
            "confidence_blocker": {},
            "score_blocker": {},
            "relative_evaluation_blocker": {},
            "unknown_blockers": [item],
            "attribution_confidence": "LOW",
            "counterfactuals": [],
            "counterfactual_feasible": False,
            "cause_count_type": "single",
            "fixed_decision_blocker": False,
            "attribution_version": self.ATTRIBUTION_VERSION,
        }

    def _rank(self, item, rank):
        for value in [rank, item.get("rank"), item.get("final_rank"), item.get("score_rank")]:
            number = self._to_int(value)
            if number is not None:
                return number
        return None

    def _is_low_value(self, value, threshold, key):
        if key == "consistency_score":
            return value < threshold
        return value <= threshold

    def _is_high_value(self, value, threshold, key):
        if key == "consistency_score":
            return value >= threshold
        return value >= threshold

    def _low_severity(self, value, threshold, key):
        scale = 0.25 if key == "consistency_score" else 20.0
        return min(0.45, abs(value - threshold) / scale)

    def _high_severity(self, value, threshold, key):
        scale = 0.25 if key == "consistency_score" else 30.0
        return min(0.45, abs(value - threshold) / scale)

    def _target_type(self, target):
        if target in {"DecisionEngine", "ConfidenceEngine", "ConsistencyEngine"}:
            return "Decision"
        return "Evaluator"

    def _counter_evidence_for_score(self, value, high_threshold, key):
        if self._is_high_value(value, high_threshold, key):
            return [f"{key}={value:g} is also a strong positive signal"]
        return []

    def _cause_count(self, primary, secondary, decision):
        if decision == "BUY":
            return 1
        if not primary or primary.get("target") == "UNKNOWN":
            return 1
        return 1 + len([item for item in secondary if item.get("target") != "UNKNOWN"])

    def _attribution_confidence(self, primary, secondary, unknowns):
        if unknowns or not primary or primary.get("target") == "UNKNOWN":
            return "LOW"
        confidence = primary.get("confidence")
        importance = float(primary.get("importance") or 0)
        if confidence == "HIGH" and importance >= 0.70:
            return "HIGH"
        if confidence in {"HIGH", "MEDIUM"} or secondary:
            return "MEDIUM"
        return "LOW"

    def _missing_required_field_count(self, item):
        required = [
            "decision",
            "race_decision",
            "final_score",
            "adjusted_score",
            "decision_score",
            "overall_rank",
            "buy_threshold",
            "caution_threshold",
            "distance_to_buy",
            "distance_to_caution",
            "decision_margin",
            "primary_blocker",
            "secondary_blockers",
            "primary_supporter",
            "secondary_supporters",
            "decision_rules_triggered",
            "decision_rules_not_met",
            "rank_blocker",
            "risk_blocker",
            "major_penalty_blocker",
            "confidence_blocker",
            "score_blocker",
            "relative_evaluation_blocker",
            "unknown_blockers",
            "attribution_confidence",
            "attribution_version",
        ]
        return sum(1 for key in required if key not in item)

    def _average(self, values):
        numbers = [value for value in values if isinstance(value, (int, float))]
        if not numbers:
            return 0.0
        return round(sum(numbers) / len(numbers), 3)

    def _to_float(self, value):
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _to_int(self, value):
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _list_text(self, value):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item not in (None, "")]
        return [str(value)]
