"""Decompose DecisionEngine gates into upstream root-cause signals."""

from collections import Counter


class DecisionRootCauseEngine:
    """Explain which upstream scores contributed before the Decision gate."""

    ROOT_VERSION = "phase_e_step2_v1"

    SCORE_SIGNALS = [
        ("DistanceEvaluator", ("distance_score",), 35, "distance fit did not strongly support BUY"),
        ("RaceShapeEvaluator", ("shape_score",), 8, "race shape did not strongly support BUY"),
        ("BloodlineEvaluator", ("bloodline_score", "blood_score"), 20, "bloodline signal was weak or missing"),
        ("PaceStyleEvaluator", ("pace_style_score", "running_style_score"), 20, "pace/style fit was not strong"),
        ("LapSuitabilityEvaluator", ("lap_score",), 8, "lap suitability did not strongly support BUY"),
        ("TrackBiasEvaluator", ("track_bias_score",), 4, "track bias did not add enough support"),
        ("PastPerformanceEvaluator", ("past_performance_score", "past_score"), 70, "past performance support was limited"),
        ("CourseEvaluator", ("course_shape_score", "course_score"), 8, "course fit did not strongly support BUY"),
        ("ConditionEvaluator", ("track_condition_score", "track_score", "condition_score"), 18, "condition fit was limited"),
        ("WeightEvaluator", ("weight_score",), 70, "weight signal was not strong"),
        ("ConsistencyEngine", ("consistency_score",), 0.85, "consistency did not strongly support BUY"),
    ]

    DECISION_GATE_EFFECTS = {
        "low_rank_buy_guard_applied": "BUY Guard",
        "buy_suppressed": "BUY Guard",
        "top_score_pass_rescued": "Decision Rule",
    }

    def analyze(self, horse=None, decision_attribution=None):
        """Return root causes without changing horse, score, or decision."""

        item = horse if isinstance(horse, dict) else {}
        attribution = decision_attribution if isinstance(decision_attribution, dict) else {}
        decision = str(item.get("decision") or attribution.get("decision") or "").upper()
        primary_blocker = attribution.get("primary_blocker")
        if not isinstance(primary_blocker, dict):
            primary_blocker = {}
        decision_primary = primary_blocker.get("target") == "DecisionEngine"
        decision_gate = self._decision_gate(item, attribution)
        root_causes = []
        if decision != "BUY" and decision_primary:
            root_causes = self._upstream_root_causes(item, attribution)
        elif decision != "BUY":
            existing = primary_blocker if primary_blocker.get("target") else {}
            if existing and existing.get("target") != "UNKNOWN":
                root_causes = [self._from_existing_detail(existing)]
        elif decision == "BUY":
            root_causes = self._buy_supporter_roots(item, attribution)

        if not root_causes and decision != "BUY":
            root_causes = [self._decision_specific_cause(decision_gate, item, attribution)]

        root_causes = self._rank_causes(root_causes)
        primary = root_causes[0] if root_causes else self._unknown_cause("no root cause")
        secondary = root_causes[1:4]
        return {
            "root_version": self.ROOT_VERSION,
            "decision_primary_was_gate": decision_primary,
            "decision_gate": decision_gate,
            "root_causes": root_causes,
            "root_primary_candidate": primary.get("target", "UNKNOWN"),
            "root_secondary_candidates": [item.get("target") for item in secondary],
            "root_importance": primary.get("importance", 0),
            "root_confidence": primary.get("confidence", "LOW"),
            "root_cause_type": self._root_cause_type(root_causes, decision_gate),
            "unknown": primary.get("target") == "UNKNOWN",
        }

    def analyze_many(self, horse_results=None):
        rows = horse_results if isinstance(horse_results, list) else []
        results = []
        for row in rows:
            if not isinstance(row, dict):
                result = {
                    "root_version": self.ROOT_VERSION,
                    "decision_gate": "UNKNOWN",
                    "root_causes": [self._unknown_cause("non dict row")],
                    "root_primary_candidate": "UNKNOWN",
                    "root_secondary_candidates": [],
                    "root_importance": 0,
                    "root_confidence": "LOW",
                    "root_cause_type": "UNKNOWN",
                    "unknown": True,
                }
            else:
                result = self.analyze(row, row.get("decision_attribution"))
                row["decision_root_cause"] = result
            results.append(result)
        return {
            "root_version": self.ROOT_VERSION,
            "horse_root_causes": results,
            "summary": self.summary(results),
            "warnings": [],
        }

    def summary(self, root_results):
        rows = [row for row in root_results if isinstance(row, dict)]
        primary = Counter(row.get("root_primary_candidate") or "UNKNOWN" for row in rows)
        gates = Counter(row.get("decision_gate") or "UNKNOWN" for row in rows)
        unknown = sum(1 for row in rows if row.get("unknown"))
        decision_gate_count = sum(
            1 for row in rows if str(row.get("decision_gate") or "") not in {"", "none"}
        )
        root_count = sum(len(row.get("root_causes") or []) for row in rows)
        return {
            "root_result_count": len(rows),
            "root_cause_count": root_count,
            "primary_root_causes": dict(primary.most_common()),
            "decision_gates": dict(gates.most_common()),
            "decision_gate_count": decision_gate_count,
            "unknown_count": unknown,
        }

    def _upstream_root_causes(self, item, attribution):
        causes = []
        distance_to_buy = self._to_float(attribution.get("distance_to_buy")) or 0.0
        for target, keys, threshold, reason in self.SCORE_SIGNALS:
            value, key = self._first_number(item, keys)
            if value is None:
                continue
            deficit = max(0.0, threshold - value)
            effect = -self._scaled_effect(deficit, threshold)
            if effect >= -0.02:
                continue
            importance = min(1.0, abs(effect) + min(0.28, distance_to_buy / 2.0))
            confidence = "HIGH" if importance >= 0.45 else "MEDIUM" if importance >= 0.22 else "LOW"
            causes.append(
                {
                    "target": target,
                    "effect": round(effect, 3),
                    "importance": round(importance, 3),
                    "rank": None,
                    "reason": reason,
                    "evidence": [f"{key}={value:g}", f"target_threshold={threshold:g}"],
                    "confidence": confidence,
                }
            )
        causes.extend(self._risk_penalty_causes(item))
        if not causes:
            causes.append(self._decision_specific_cause(self._decision_gate(item, attribution), item, attribution))
        return causes

    def _buy_supporter_roots(self, item, attribution):
        supporters = []
        supporter = attribution.get("primary_supporter")
        if isinstance(supporter, dict) and supporter.get("target"):
            supporters.append(self._from_existing_detail(supporter, positive=True))
        return supporters

    def _risk_penalty_causes(self, item):
        causes = []
        risk_count = self._to_int(item.get("risk_count")) or 0
        conflict_count = self._to_int(item.get("conflict_count")) or 0
        if risk_count >= 3:
            causes.append(
                {
                    "target": "RiskPenalty",
                    "effect": round(-min(0.5, risk_count * 0.10), 3),
                    "importance": round(min(1.0, 0.35 + risk_count * 0.08), 3),
                    "rank": None,
                    "reason": "multiple Decision risk items reduced BUY reach",
                    "evidence": [f"risk_count={risk_count}"],
                    "confidence": "MEDIUM",
                }
            )
        if conflict_count >= 3:
            causes.append(
                {
                    "target": "RiskPenalty",
                    "effect": round(-min(0.45, conflict_count * 0.09), 3),
                    "importance": round(min(1.0, 0.32 + conflict_count * 0.08), 3),
                    "rank": None,
                    "reason": "conflict items reduced BUY reach",
                    "evidence": [f"conflict_count={conflict_count}"],
                    "confidence": "MEDIUM",
                }
            )
        return causes

    def _decision_gate(self, item, attribution):
        for key, label in self.DECISION_GATE_EFFECTS.items():
            if item.get(key) or attribution.get(key):
                return label
        rank = self._to_int(attribution.get("overall_rank") or item.get("rank") or item.get("final_rank"))
        if rank is not None and rank > 5 and item.get("decision") == "CAUTION":
            return "RankBlocker"
        if self._to_int(item.get("risk_count")) and self._to_int(item.get("risk_count")) >= 3:
            return "RiskPenalty"
        diagnostics = item.get("decision_diagnostics") if isinstance(item.get("decision_diagnostics"), dict) else {}
        if self._to_int(diagnostics.get("major_risk_count")):
            return "MajorPenalty"
        if str(item.get("confidence_level") or "").lower() in {"low", "very_low"}:
            return "Confidence Gate"
        if (self._to_float(attribution.get("distance_to_buy")) or 0) > 0:
            return "Decision Score Gate"
        return "none"

    def _decision_specific_cause(self, gate, item, attribution):
        target = "DecisionEngine"
        if gate == "RiskPenalty":
            target = "RiskPenalty"
        elif gate == "RankBlocker":
            target = "RankBlocker"
        elif gate == "Confidence Gate":
            target = "Confidence Gate"
        elif gate == "MajorPenalty":
            target = "MajorPenalty"
        return {
            "target": target,
            "effect": round(-(self._to_float(attribution.get("distance_to_buy")) or 0), 3),
            "importance": 0.35,
            "rank": None,
            "reason": f"{gate} could not be decomposed into a supported evaluator cause",
            "evidence": [f"decision_score={item.get('decision_score')}"],
            "confidence": "LOW",
        }

    def _from_existing_detail(self, detail, positive=False):
        importance = self._to_float(detail.get("importance")) or 0.25
        effect = importance if positive else -importance
        return {
            "target": detail.get("target") or "UNKNOWN",
            "effect": round(effect, 3),
            "importance": round(importance, 3),
            "rank": None,
            "reason": detail.get("reason") or "existing decision attribution detail",
            "evidence": list(detail.get("evidence") or []),
            "confidence": detail.get("confidence") or "LOW",
        }

    def _unknown_cause(self, reason):
        return {
            "target": "UNKNOWN",
            "effect": 0,
            "importance": 0,
            "rank": 1,
            "reason": reason,
            "evidence": [],
            "confidence": "LOW",
        }

    def _rank_causes(self, causes):
        rows = [row for row in causes if isinstance(row, dict)]
        rows.sort(key=lambda row: (-float(row.get("importance") or 0), str(row.get("target") or "")))
        total = sum(float(row.get("importance") or 0) for row in rows) or 1.0
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
            row["importance_share"] = round(float(row.get("importance") or 0) / total, 3)
        return rows

    def _root_cause_type(self, causes, gate):
        if not causes:
            return "UNKNOWN"
        if causes[0].get("target") == "UNKNOWN":
            return "UNKNOWN"
        if len([row for row in causes if row.get("target") != "UNKNOWN"]) >= 2:
            return "複合要因"
        if gate in {"BUY Guard", "RankBlocker", "RiskPenalty", "MajorPenalty", "Confidence Gate", "Decision Rule"}:
            return "Decision固有"
        return "Evaluator"

    def _first_number(self, item, keys):
        for key in keys:
            value = self._to_float(item.get(key))
            if value is not None:
                return value, key
        return None, None

    def _scaled_effect(self, deficit, threshold):
        scale = max(1.0, abs(float(threshold)))
        if threshold <= 1:
            scale = 0.35
        return min(1.0, deficit / scale)

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
