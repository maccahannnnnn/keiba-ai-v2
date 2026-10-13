"""Tier 1a/1b regression and bounded parity harness for BUY Gate Trace."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import unittest
from pathlib import Path

from engine.buy_v1_rc1_engine import BUYV1RC1Engine
from engine.shadow_buy_decision_engine import ShadowBUYDecisionEngine
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "prediction_input"
DATES = ("260627", "260628", "260815", "260816")
FORBIDDEN_RESULT_KEYS = {
    "finish", "finish_position", "actual_top3", "valid_result", "payout",
    "placement", "placement_outcome", "result", "result_outcome", "top3_result",
}
TRACE_HORSE_KEYS = {
    "horse_number", "prediction_rank", "shadow_ai_rank", "decision_score", "final_score",
    "decision_engine_rank", "rank_context_rank", "pre_rc1_decision", "post_rc1_decision",
    "adjusted_score", "evaluator_score_snapshot", "positive_evaluators",
    "negative_evaluators", "missing_evaluators", "blocking_missing_evaluators",
    "positive_count", "negative_count", "strong_positive_count", "strong_negative_count",
    "net_consensus_score", "risk_summary", "conflict_factors", "absolute_quality_pass",
    "relative_advantage_pass", "reliability_pass", "effective_reliability_pass",
    "risk_guard_pass", "shadow_buy_candidate", "shadow_buy",
    "pace_prediction", "pace_style", "course_profile_matched", "race_shape_adjustment_id",
}


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def strip_approved_nondeterministic_paths(output: dict) -> dict:
    """Remove only the five approved logical DecisionEngine id(row) fields.

    ``deepcopy`` intentionally preserves existing aliases.  The production
    payload exposes parts of ``decision_diagnostics`` through several mirrored
    references; removing an approved field from its source object therefore
    removes the same object from those mirrors without selecting another path.
    """

    normalized = copy.deepcopy(output)
    for row in normalized.get("ranked_results", []):
        diagnostics = row.get("decision_diagnostics")
        if isinstance(diagnostics, dict):
            diagnostics.pop("ai_rank", None)  # path 1
            trace = diagnostics.get("decision_trace")
            if isinstance(trace, list):
                if len(trace) > 2 and isinstance(trace[2], dict):
                    trace[2].pop("value", None)  # path 2
                if len(trace) > 10 and isinstance(trace[10], dict):
                    trace[10].pop("ai_rank", None)  # path 3
        decision_result = row.get("decision_result")
        if isinstance(decision_result, dict):
            decision_result.pop("ai_rank", None)  # path 4
            nested = decision_result.get("decision_diagnostics")
            if isinstance(nested, dict):
                nested.pop("ai_rank", None)  # path 5
    return normalized


def parity_v2(left: dict, right: dict) -> bool:
    return strip_approved_nondeterministic_paths(left) == strip_approved_nondeterministic_paths(right)


def assert_result_free(test: unittest.TestCase, value) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            test.assertNotIn(str(key).lower(), FORBIDDEN_RESULT_KEYS)
            assert_result_free(test, child)
    elif isinstance(value, list):
        for child in value:
            assert_result_free(test, child)


class BuyGateTraceTier1V2Tests(unittest.TestCase):
    def _bundle(self, date: str):
        return TargetBulkPredictionInputAdapterV1().load(
            RAW / f"DG{date}.CSV", RAW / f"DE{date}.CSV", RAW / f"DS{date}.CSV"
        )

    def _outputs(self, date: str, trace: bool | None) -> dict:
        bundle = self._bundle(date)
        if trace is None:
            return {race_id: run_new(race_id, race) for race_id, race in sorted(bundle.races.items())}
        return {
            race_id: run_new(race_id, race, trace=trace)
            for race_id, race in sorted(bundle.races.items())
        }

    def test_01_engine_only_adds_existing_horse_number(self):
        engine = ShadowBUYDecisionEngine()
        horse = {"horse_number": 7, "horse_name": "identity", "final_score": 80.0,
                 "adjusted_score": 80.0, "decision_score": 80.0}
        record = engine._horse_record(horse, [horse])
        self.assertEqual(record["horse_number"], horse["horse_number"])
        source = inspect.getsource(ShadowBUYDecisionEngine._horse_record)
        self.assertIn('"horse_number": horse.get("horse_number"),', source)

    def test_02_two_argument_and_explicit_false_share_the_same_false_path(self):
        for date in DATES:
            omitted = self._outputs(date, None)
            false = self._outputs(date, False)
            with self.subTest(date=date):
                self.assertTrue(all(parity_v2(omitted[race_id], false[race_id]) for race_id in omitted))
                self.assertTrue(all("buy_gate_trace" not in row for row in false.values()))
                self.assertTrue(all("buy_gate_trace" not in row for row in omitted.values()))

    def test_03_trace_on_is_additive_under_bounded_parity_for_all_races(self):
        for date in DATES:
            false = self._outputs(date, False)
            true = self._outputs(date, True)
            for race_id in sorted(false):
                with self.subTest(date=date, race_id=race_id):
                    traced = true[race_id]
                    self.assertIn("buy_gate_trace", traced)
                    existing = {key: value for key, value in traced.items() if key != "buy_gate_trace"}
                    self.assertTrue(parity_v2(false[race_id], existing))

    def test_04_trace_identity_and_structure_use_horse_number_only(self):
        for date in DATES:
            for race_id, traced in self._outputs(date, True).items():
                with self.subTest(date=date, race_id=race_id):
                    payload = traced["buy_gate_trace"]
                    self.assertEqual(set(payload), {"race", "horses"})
                    self.assertEqual(set(payload["race"]), {
                        "shadow_candidate_count", "shadow_race_state", "shadow_spec_converged",
                    })
                    final = {int(row["horse_number"]): row for row in traced["ranked_results"]}
                    trace = {row["horse_number"]: row for row in payload["horses"]}
                    self.assertEqual(set(final), set(trace))
                    self.assertEqual(len(trace), len(payload["horses"]))
                    for number, row in trace.items():
                        self.assertEqual(set(row), TRACE_HORSE_KEYS)
                        self.assertEqual(row["prediction_rank"], final[number]["rank"])
                    assert_result_free(self, payload)

    def test_05_trace_sources_match_captured_runtime_values(self):
        captured = {}
        original = BUYV1RC1Engine.evaluate

        def wrapped(engine, *args, **kwargs):
            result = original(engine, *args, **kwargs)
            captured.update({
                int(row["horse_number"]): copy.deepcopy(row)
                for row in result["shadow_result"]["horse_records"]
            })
            captured["race"] = copy.deepcopy(result["shadow_result"]["race_record"])
            return result

        BUYV1RC1Engine.evaluate = wrapped
        try:
            bundle = self._bundle("260815")
            race_id, race = next(iter(sorted(bundle.races.items())))
            output = run_new(race_id, race, trace=True)
        finally:
            BUYV1RC1Engine.evaluate = original
        for row in output["buy_gate_trace"]["horses"]:
            source = captured[row["horse_number"]]
            self.assertEqual(row["shadow_ai_rank"], source["ai_rank"])
            self.assertEqual(row["decision_score"], source["decision_score"])
            self.assertEqual(row["final_score"], source["final_score"])
            self.assertEqual(row["adjusted_score"], source["adjusted_score"])
            self.assertEqual(row["evaluator_score_snapshot"], source["consensus_profile"]["score_snapshot"])
            self.assertEqual(row["shadow_buy"], source["shadow_buy"])
            final = next(item for item in output["ranked_results"] if item["horse_number"] == row["horse_number"])
            self.assertEqual(row["decision_engine_rank"], final["decision_result"]["ai_rank"])
            self.assertEqual(row["rank_context_rank"], final["decision_result"]["ai_rank"])
            self.assertEqual(row["pre_rc1_decision"], final["decision_result"]["decision"])
            self.assertEqual(row["post_rc1_decision"], final["decision"])
            self.assertEqual(row["pace_prediction"], final["shape_result"].get("pace_prediction"))
            self.assertEqual(row["pace_style"], final["shape_result"].get("pace_style"))
            self.assertEqual(row["course_profile_matched"], final["course_shape_result"].get("course_profile_matched"))
            self.assertEqual(row["race_shape_adjustment_id"], final["shape_result"].get("race_shape_adjustment_id"))
        self.assertEqual(output["buy_gate_trace"]["race"]["shadow_race_state"], captured["race"]["shadow_race_state"])

    def test_06_trace_determinism_and_no_name_or_position_join(self):
        first = self._outputs("260816", True)
        second = self._outputs("260816", True)
        first_trace = {key: value["buy_gate_trace"] for key, value in first.items()}
        second_trace = {key: value["buy_gate_trace"] for key, value in second.items()}
        self.assertEqual(canonical(first_trace), canonical(second_trace))
        source = inspect.getsource(__import__("review.target_bulk_prediction_input_shadow_v1", fromlist=["_"])._project_buy_gate_trace)
        self.assertNotIn("horse_name", source)
        self.assertNotIn("enumerate(", source)

    def test_07_parity_harness_allows_only_approved_paths(self):
        sample = {
            "ranked_results": [{
                "rank": 1, "final_score": 100.0,
                "decision_diagnostics": {"ai_rank": 1, "decision_trace": [{}, {}, {"value": 1}, {}, {}, {}, {}, {}, {}, {}, {"ai_rank": 1}]},
                "decision_result": {"ai_rank": 1, "decision_diagnostics": {"ai_rank": 1}},
            }]
        }
        approved = copy.deepcopy(sample)
        approved["ranked_results"][0]["decision_diagnostics"]["ai_rank"] = 2
        approved["ranked_results"][0]["decision_diagnostics"]["decision_trace"][2]["value"] = 2
        approved["ranked_results"][0]["decision_diagnostics"]["decision_trace"][10]["ai_rank"] = 2
        approved["ranked_results"][0]["decision_result"]["ai_rank"] = 2
        approved["ranked_results"][0]["decision_result"]["decision_diagnostics"]["ai_rank"] = 2
        self.assertTrue(parity_v2(sample, approved))
        unexpected = copy.deepcopy(sample)
        unexpected["ranked_results"][0]["final_score"] = 101.0
        self.assertFalse(parity_v2(sample, unexpected))

    def test_08_deterministic_fixture_covers_exactly_five_approved_paths(self):
        baseline = {
            "race_decision": "PLAY",
            "ranked_results": [{
                "final_score": 80.0,
                "buy": False,
                "decision_diagnostics": {
                    "ai_rank": 4,
                    "decision_trace": [{}, {}, {"value": 4}, {}, {}, {}, {}, {}, {}, {}, {"ai_rank": 4}],
                },
                "decision_result": {
                    "ai_rank": 4,
                    "decision_diagnostics": {"ai_rank": 4},
                },
            }],
        }
        approved_only = copy.deepcopy(baseline)
        row = approved_only["ranked_results"][0]
        row["decision_diagnostics"]["ai_rank"] = 5
        row["decision_diagnostics"]["decision_trace"][2]["value"] = 5
        row["decision_diagnostics"]["decision_trace"][10]["ai_rank"] = 5
        row["decision_result"]["ai_rank"] = 5
        row["decision_result"]["decision_diagnostics"]["ai_rank"] = 5
        self.assertTrue(parity_v2(baseline, approved_only))
        for field, value in (("final_score", 81.0), ("buy", True)):
            with self.subTest(field=field):
                unexpected = copy.deepcopy(approved_only)
                unexpected["ranked_results"][0][field] = value
                self.assertFalse(parity_v2(baseline, unexpected))
        unexpected_race = copy.deepcopy(approved_only)
        unexpected_race["race_decision"] = "PASS"
        self.assertFalse(parity_v2(baseline, unexpected_race))

    def test_09_missing_race_course_shape_values_are_explicit_null(self):
        from review.target_bulk_prediction_input_shadow_v1 import _race_course_shape_trace_values

        self.assertEqual(_race_course_shape_trace_values({}), {
            "pace_prediction": None,
            "pace_style": None,
            "course_profile_matched": None,
            "race_shape_adjustment_id": None,
        })
        self.assertEqual(_race_course_shape_trace_values({
            "shape_result": {"pace_prediction": "fast", "pace_style": "front"},
            "course_shape_result": {"course_profile_matched": False},
        }), {
            "pace_prediction": "fast",
            "pace_style": "front",
            "course_profile_matched": False,
            "race_shape_adjustment_id": None,
        })

    def test_10_trace_schema_versions_are_additive(self):
        schema_v1 = json.loads((ROOT / "docs" / "buy_gate_trace_schema_v1.json").read_text(encoding="utf-8"))
        schema_v1_1 = json.loads((ROOT / "docs" / "buy_gate_trace_schema_v1_1.json").read_text(encoding="utf-8"))
        schema_v1_2 = json.loads((ROOT / "docs" / "buy_gate_trace_schema_v1_2.json").read_text(encoding="utf-8"))
        self.assertEqual(schema_v1_1["schema_version"], "BUY_GATE_TRACE_SCHEMA_V1_1")
        self.assertEqual(schema_v1_1["compatibility"]["extends"], schema_v1["schema_version"])
        self.assertTrue(set(schema_v1["race_fields"]).issubset(schema_v1_1["race_fields"]))
        self.assertTrue(set(schema_v1["horse_fields"]).issubset(schema_v1_1["horse_fields"]))
        self.assertTrue({"pace_prediction", "pace_style", "course_profile_matched", "race_shape_adjustment_id"}.issubset(schema_v1_1["horse_fields"]))
        self.assertEqual(schema_v1_2["schema_version"], "BUY_GATE_TRACE_SCHEMA_V1_2")
        self.assertEqual(schema_v1_2["compatibility"]["extends"], schema_v1_1["schema_version"])
        self.assertTrue({"decision_engine_rank", "rank_context_rank", "pre_rc1_decision", "post_rc1_decision"}.issubset(schema_v1_2["horse_fields_added"]))

    def test_11_existing_frozen_prediction_manifests_remain_valid_without_writes(self):
        roots = (
            ROOT / "reports" / "prospective_prediction_20260822_v1",
            ROOT / "reports" / "prospective_prediction_20260823_v1",
        )
        before = {}
        for root in roots:
            manifest = json.loads((root / "prediction_manifest.json").read_text(encoding="utf-8"))
            before[root] = {
                row["relative_path"]: hashlib.sha256((root / row["relative_path"]).read_bytes()).hexdigest()
                for row in manifest["files"]
            }
            self.assertEqual(before[root], {row["relative_path"]: row["sha256"] for row in manifest["files"]})
        self._outputs("260815", True)
        for root, expected in before.items():
            self.assertEqual(expected, {
                relative_path: hashlib.sha256((root / relative_path).read_bytes()).hexdigest()
                for relative_path in expected
            })


if __name__ == "__main__":
    unittest.main()
