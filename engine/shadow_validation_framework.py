"""Common helpers for corrected shadow validation.

The framework separates three states:

* official: saved evaluation output
* zero_delta: shadow re-decision with no score change
* shadow: shadow re-decision after a local diagnostic delta

Corrected shadow effects are measured as shadow - zero_delta, never as
shadow - official.  This keeps re-decision drift out of Knowledge validation
metrics.  The framework is diagnostic only and never mutates official rows.
"""

from collections import Counter
from copy import deepcopy

from engine.decision_engine import DecisionEngine


class ShadowValidationFramework:
    """Build official / zero-delta / shadow layers for copied race rows."""

    MODE = "corrected_baseline"

    def __init__(self, decision_runner=None):
        self.decision_runner = decision_runner or DecisionEngine()

    def validate(
        self,
        race_results=None,
        shadow_applier=None,
        scope_filter=None,
        candidate_id="shadow_candidate",
    ):
        """Return corrected shadow comparison data.

        race_results is a list of dictionaries containing race_set, analysis,
        and official result payloads.  shadow_applier receives a copied horse row
        and may mutate that copy only.  scope_filter returns True for rows that
        should receive the shadow delta.
        """

        scope_filter = scope_filter or (lambda _row: False)
        shadow_applier = shadow_applier or (lambda _row: None)
        races = race_results if isinstance(race_results, list) else []
        official_rows = []
        zero_rows = []
        shadow_rows = []

        for race in races:
            race_id = (race.get("race_set") or {}).get("race_id")
            ranked = [
                row for row in self._list((race.get("analysis") or {}).get("ranked_results"))
                if isinstance(row, dict)
            ]
            official_rows.extend(self._official_layer(race_id, ranked, scope_filter))
            zero_rows.extend(
                self._redecision_layer(
                    race_id,
                    ranked,
                    scope_filter,
                    shadow_applier=None,
                    layer_name="zero_delta",
                )
            )
            shadow_rows.extend(
                self._redecision_layer(
                    race_id,
                    ranked,
                    scope_filter,
                    shadow_applier=shadow_applier,
                    layer_name="shadow",
                )
            )

        official_map = self._row_map(official_rows)
        zero_map = self._row_map(zero_rows)
        shadow_map = self._row_map(shadow_rows)
        comparisons = []
        for key in sorted(official_map):
            official = official_map.get(key, {})
            zero = zero_map.get(key, {})
            shadow = shadow_map.get(key, {})
            comparisons.append(
                self._comparison_row(
                    candidate_id=candidate_id,
                    official=official,
                    zero=zero,
                    shadow=shadow,
                )
            )

        return {
            "mode": self.MODE,
            "candidate_id": candidate_id,
            "official_results": official_rows,
            "zero_delta_results": zero_rows,
            "shadow_results": shadow_rows,
            "comparisons": comparisons,
            "metrics": self._metrics(comparisons),
        }

    def _official_layer(self, race_id, ranked, scope_filter):
        rows = []
        for rank, row in enumerate(ranked, start=1):
            rows.append(self._snapshot_row(race_id, row, rank, scope_filter, "official"))
        return rows

    def _redecision_layer(self, race_id, ranked, scope_filter, shadow_applier, layer_name):
        copied = [deepcopy(row) for row in ranked]
        for row in copied:
            if shadow_applier is not None and scope_filter(row):
                shadow_applier(row)
        sorted_rows = sorted(
            copied,
            key=lambda item: (
                self._to_float(item.get("adjusted_score")) or 0,
                self._to_int(item.get("horse_number")) or 0,
            ),
            reverse=True,
        )
        decisions = self.decision_runner.decide_many(sorted_rows)
        rows = []
        for rank, row in enumerate(sorted_rows, start=1):
            decision = decisions[rank - 1] if rank - 1 < len(decisions) else {}
            row["decision"] = decision.get("decision", row.get("decision"))
            row["decision_score"] = decision.get("decision_score", row.get("decision_score"))
            row["decision_result"] = decision
            rows.append(self._snapshot_row(race_id, row, rank, scope_filter, layer_name))
        return rows

    def _snapshot_row(self, race_id, row, rank, scope_filter, layer):
        decision_result = row.get("decision_result") if isinstance(row.get("decision_result"), dict) else {}
        return {
            "layer": layer,
            "race_id": race_id,
            "horse_name": row.get("horse_name"),
            "horse_number": row.get("horse_number"),
            "racecourse": row.get("racecourse"),
            "surface": row.get("surface"),
            "distance": self._to_int(row.get("distance")),
            "track_condition": row.get("track_condition"),
            "broodmare_sire": row.get("broodmare_sire"),
            "shadow_applicable": bool(scope_filter(row)),
            "bloodline_score": self._to_float(row.get("bloodline_score")) or 0,
            "final_score": self._to_float(row.get("final_score")) or 0,
            "adjusted_score": self._to_float(row.get("adjusted_score")) or 0,
            "decision_score": self._to_float(row.get("decision_score")),
            "rank": rank,
            "decision": row.get("decision"),
            "risk_count": decision_result.get("risk_count"),
            "risk_score": decision_result.get("risk_score"),
            "risk_items": self._list(decision_result.get("risk_items")),
            "rank_blocker": {
                "low_rank_buy_guard_applied": decision_result.get("low_rank_buy_guard_applied"),
                "low_rank_buy_guard_skipped_reason": decision_result.get("low_rank_buy_guard_skipped_reason"),
                "ai_rank": decision_result.get("ai_rank"),
                "top_score_pass_rescued": decision_result.get("top_score_pass_rescued"),
                "top_score_pass_rescue_skipped_reason": decision_result.get("top_score_pass_rescue_skipped_reason"),
            },
        }

    def _comparison_row(self, candidate_id, official, zero, shadow):
        official_to_zero = official.get("decision") != zero.get("decision")
        official_to_shadow = official.get("decision") != shadow.get("decision")
        zero_to_shadow = zero.get("decision") != shadow.get("decision")
        applicable = bool(official.get("shadow_applicable"))
        same_race_effect = bool(
            not applicable
            and shadow.get("shadow_applicable") is False
            and zero_to_shadow
        )
        return {
            "candidate_id": candidate_id,
            "race_id": official.get("race_id"),
            "horse_name": official.get("horse_name"),
            "shadow_applicable": applicable,
            "official": official,
            "zero_delta_baseline": zero,
            "shadow": shadow,
            "official_final_score": official.get("final_score"),
            "zero_delta_final_score": zero.get("final_score"),
            "shadow_final_score": shadow.get("final_score"),
            "redecision_final_score_drift": self._delta(zero.get("final_score"), official.get("final_score")),
            "corrected_shadow_final_score_delta": self._delta(shadow.get("final_score"), zero.get("final_score")),
            "official_adjusted_score": official.get("adjusted_score"),
            "zero_delta_adjusted_score": zero.get("adjusted_score"),
            "shadow_adjusted_score": shadow.get("adjusted_score"),
            "redecision_adjusted_score_drift": self._delta(zero.get("adjusted_score"), official.get("adjusted_score")),
            "corrected_shadow_adjusted_score_delta": self._delta(shadow.get("adjusted_score"), zero.get("adjusted_score")),
            "official_decision_score": official.get("decision_score"),
            "zero_delta_decision_score": zero.get("decision_score"),
            "shadow_decision_score": shadow.get("decision_score"),
            "redecision_decision_score_drift": self._delta(zero.get("decision_score"), official.get("decision_score")),
            "corrected_shadow_decision_score_delta": self._delta(shadow.get("decision_score"), zero.get("decision_score")),
            "official_rank": official.get("rank"),
            "zero_delta_rank": zero.get("rank"),
            "shadow_rank": shadow.get("rank"),
            "official_decision": official.get("decision"),
            "zero_delta_decision": zero.get("decision"),
            "shadow_decision": shadow.get("decision"),
            "official_to_zero_delta_changed": official_to_zero,
            "official_to_shadow_changed": official_to_shadow,
            "zero_delta_to_shadow_changed": zero_to_shadow,
            "redecision_drift": official_to_zero,
            "raw_shadow_difference": official_to_shadow,
            "corrected_shadow_difference": zero_to_shadow,
            "direct_shadow_effect": applicable and zero_to_shadow,
            "same_race_relative_effect": same_race_effect,
            "redecision_drift_only": official_to_zero and not zero_to_shadow,
            "propagation_class": self._propagation_class(applicable, official_to_zero, zero_to_shadow),
            "risk_penalty_changed": self._risk_changed(zero, shadow),
            "rank_blocker_changed": self._rank_blocker_changed(zero, shadow),
            "decision_score_improved": self._delta(shadow.get("decision_score"), zero.get("decision_score")) > 0,
            "rank_improved": (shadow.get("rank") or 999) < (zero.get("rank") or 999),
        }

    def _metrics(self, comparisons):
        corrected = [row for row in comparisons if row.get("zero_delta_to_shadow_changed")]
        raw = [row for row in comparisons if row.get("official_to_shadow_changed")]
        drift = [row for row in comparisons if row.get("official_to_zero_delta_changed")]
        applicable = [row for row in comparisons if row.get("shadow_applicable")]
        non_applicable = [row for row in comparisons if not row.get("shadow_applicable")]
        return {
            "horse_count": len(comparisons),
            "target_count": len(applicable),
            "official_to_zero_delta_changes": len(drift),
            "official_to_shadow_changes": len(raw),
            "zero_delta_to_shadow_changes": len(corrected),
            "redecision_drift_excluded": len(drift),
            "target_corrected_changes": sum(1 for row in applicable if row.get("zero_delta_to_shadow_changed")),
            "non_target_corrected_changes": sum(1 for row in non_applicable if row.get("zero_delta_to_shadow_changed")),
            "same_race_corrected_changes": sum(1 for row in corrected if row.get("same_race_relative_effect")),
            "cross_race_corrected_changes": 0,
            "fn_improved_count": 0,
            "new_fp_count": 0,
            "pass_to_caution_count": self._transition_count(corrected, "PASS", "CAUTION"),
            "pass_to_buy_count": self._transition_count(corrected, "PASS", "BUY"),
            "caution_to_buy_count": self._transition_count(corrected, "CAUTION", "BUY"),
            "buy_to_caution_count": self._transition_count(corrected, "BUY", "CAUTION"),
            "rank_improvement_count": sum(1 for row in comparisons if row.get("rank_improved")),
            "decision_score_improvement_count": sum(
                1 for row in comparisons if row.get("decision_score_improved")
            ),
            "propagation_classes": dict(Counter(row.get("propagation_class") for row in comparisons)),
        }

    def _propagation_class(self, applicable, official_to_zero, zero_to_shadow):
        if applicable and zero_to_shadow:
            return "DIRECT_SHADOW_EFFECT"
        if zero_to_shadow:
            return "SAME_RACE_RELATIVE_EFFECT"
        if official_to_zero:
            return "REDECISION_DRIFT_ONLY"
        return "NO_CHANGE"

    def _transition_count(self, rows, before, after):
        return sum(
            1 for row in rows
            if row.get("zero_delta_decision") == before and row.get("shadow_decision") == after
        )

    def _risk_changed(self, zero, shadow):
        return (
            zero.get("risk_count") != shadow.get("risk_count")
            or zero.get("risk_score") != shadow.get("risk_score")
            or zero.get("risk_items") != shadow.get("risk_items")
        )

    def _rank_blocker_changed(self, zero, shadow):
        return zero.get("rank_blocker") != shadow.get("rank_blocker")

    def _row_map(self, rows):
        return {
            (row.get("race_id"), str(row.get("horse_name") or "")): row
            for row in rows
        }

    def _delta(self, after, before):
        after = self._to_float(after)
        before = self._to_float(before)
        if after is None or before is None:
            return 0
        return round(after - before, 6)

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _to_int(self, value):
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _to_float(self, value):
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None
