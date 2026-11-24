"""Regression tests for the persistent, prediction-only prospective runner."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from review import prospective_prediction_runner_v1 as runner
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new


ROOT = Path(__file__).resolve().parents[1]
HORSE_FIELDS = [
    "horse_number", "horse_name", "rank", "final_score", "decision", "buy",
    "confidence", "past_race_count", "decision_score", "adjusted_score",
    "consensus_positive_count", "consensus_negative_count", "explain_summary", "warnings", "risks",
    "risk_count", "conflict_count", "buy_v1_rc1_status", "buy_v1_rc1_candidate",
    "buy_v1_rc1_race_state", "buy_v1_rc1_reason",
]
FORBIDDEN = {"decision_diagnostics", "decision_result", "decision_trace"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ProspectivePredictionRunnerV1Tests(unittest.TestCase):
    def _run(self, date: str, root: Path, trace: bool = False) -> Path:
        return runner.run(date, trace=trace, output_root=root)

    def test_01_schema_is_explicit_and_forbids_diagnostic_dump_fields(self):
        schema = _load(ROOT / "docs" / "prospective_prediction_schema_v1.json")
        self.assertEqual(schema["schema_version"], runner.SCHEMA_VERSION)
        self.assertEqual(schema["horse_fields"], HORSE_FIELDS)
        self.assertEqual(set(schema["forbidden_fields"]), FORBIDDEN)

    def test_02_default_output_is_trace_off_and_schema_c_only(self):
        bundle = TargetBulkPredictionInputAdapterV1().load(
            ROOT / "data/raw/prediction_input/DG260627.CSV", ROOT / "data/raw/prediction_input/DE260627.CSV",
            ROOT / "data/raw/prediction_input/DS260627.CSV",
        )
        race_id, race = next(iter(sorted(bundle.races.items())))
        artifact = runner._project_race(race_id, run_new(race_id, race))
        self.assertNotIn("buy_gate_trace", artifact)
        self.assertNotIn("trace_status", artifact)
        self.assertEqual(list(artifact["ranked_results"][0]), HORSE_FIELDS)
        self._assert_no_forbidden(artifact)

    def test_03_trace_is_opt_in_and_not_claimed_as_formally_frozen(self):
        with patch("sys.argv", ["runner", "--date", "20260627", "--trace"]), patch.object(runner, "run", return_value=Path("x")) as call:
            self.assertEqual(runner.main(), 0)
        self.assertEqual(call.call_args.args, ("20260627",))
        self.assertEqual(call.call_args.kwargs, {"trace": True})

    def test_04_exclusive_create_refuses_existing_root(self):
        source = (ROOT / "review" / "prospective_prediction_runner_v1.py").read_text(encoding="utf-8")
        self.assertIn("if root.exists():", source)
        self.assertIn("OUTPUT_ROOT_EXISTS", source)

    def test_05_population_guard_fails_closed_for_excluded_classes(self):
        bundle = SimpleNamespace(races={"r": SimpleNamespace(today_entries=[SimpleNamespace(class_level="未勝利", surface="芝", race_name="")])})
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_PREDICTION_POPULATION_RACE"):
            runner._assert_population(bundle)

    def test_06_manifest_is_complete_and_excludes_itself(self):
        source = (ROOT / "review" / "prospective_prediction_runner_v1.py").read_text(encoding="utf-8")
        self.assertIn('"report.md"', source)
        self.assertIn('"excludes": ["prediction_manifest.json"]', source)

    def test_07_common_contract_matches_frozen_historical_pre_for_627(self):
        frozen = ROOT / "reports" / "historical_development_cohort_20260627_20260628_pre_v2_final"
        projections = [runner.common_semantic_projection(_load(p)) for p in frozen.glob("race_20260627_*_prediction.json")]
        self.assertEqual(len(projections), 17)
        self.assertTrue(all(set(row["ranked_results"][0]) == set(runner.COMMON_SEMANTIC_HORSE_FIELDS) for row in projections))

    def test_08_result_data_isolation_is_structural(self):
        source = (ROOT / "review" / "prospective_prediction_runner_v1.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("target_result", source)
        self.assertNotIn("data/results", source)

    def test_09_date_parameter_is_fail_closed_before_input_access(self):
        with self.assertRaisesRegex(ValueError, "YYYYMMDD"):
            runner.run("2026-06-27")

    def test_10_schema_identifier_is_attached_to_each_projected_race(self):
        artifact = runner._project_race("race_example", {"ranked_results": []})
        self.assertEqual(artifact["schema_version"], "prospective_prediction_schema_v1")

    def test_11_prediction_semantics_remain_delegated_to_run_new(self):
        source = (ROOT / "review" / "prospective_prediction_runner_v1.py").read_text(encoding="utf-8")
        self.assertIn("output = run_new(race_id, race, trace=trace)", source)
        self.assertNotIn("EvaluationEngine", source)
        self.assertNotIn("TargetTrialAdapter", source)

    def test_12_projected_artifact_is_deterministic_when_run_new_is_repeated(self):
        bundle = TargetBulkPredictionInputAdapterV1().load(
            ROOT / "data/raw/prediction_input/DG260627.CSV", ROOT / "data/raw/prediction_input/DE260627.CSV",
            ROOT / "data/raw/prediction_input/DS260627.CSV",
        )
        race_id, race = next(iter(sorted(bundle.races.items())))
        self.assertEqual(runner._project_race(race_id, run_new(race_id, race)),
                         runner._project_race(race_id, run_new(race_id, race)))

    def test_13_legacy_projection_contract_is_explicit_before_comparison(self):
        contract = _load(ROOT / "docs" / "prospective_prediction_semantic_projection_contract_v1.json")
        self.assertEqual(contract["horse_fields"], list(runner.COMMON_SEMANTIC_HORSE_FIELDS))
        self.assertEqual(contract["failure_behavior"], "STOPPED_NEEDS_REVIEW if any declared common field differs.")

    def test_14_legacy_815_projection_uses_only_the_declared_common_contract(self):
        legacy = _load(next((ROOT / "reports/prospective_analysis_20260815_v1").glob("race_*_prediction.json")))
        projected = runner.common_semantic_projection(legacy)
        self.assertEqual(set(projected), {"race_id", "race_decision", "race_confidence", "buy_count", "ranked_results"})
        self.assertEqual(set(projected["ranked_results"][0]), set(runner.COMMON_SEMANTIC_HORSE_FIELDS))

    def test_15_four_observability_fields_are_direct_runtime_copies(self):
        bundle = TargetBulkPredictionInputAdapterV1().load(
            ROOT / "data/raw/prediction_input/DG260627.CSV", ROOT / "data/raw/prediction_input/DE260627.CSV",
            ROOT / "data/raw/prediction_input/DS260627.CSV",
        )
        race_id, race = next(iter(sorted(bundle.races.items())))
        raw = run_new(race_id, race)
        projected = runner._project_race(race_id, raw)
        raw_by_number = {row["horse_number"]: row for row in raw["ranked_results"]}
        for row in projected["ranked_results"]:
            runtime = raw_by_number[row["horse_number"]]
            for key in ("decision_score", "adjusted_score", "consensus_positive_count", "consensus_negative_count"):
                self.assertIn(key, row)
                self.assertEqual(row[key], runtime[key])

    def test_16_added_observability_fields_are_deterministic(self):
        bundle = TargetBulkPredictionInputAdapterV1().load(
            ROOT / "data/raw/prediction_input/DG260627.CSV", ROOT / "data/raw/prediction_input/DE260627.CSV",
            ROOT / "data/raw/prediction_input/DS260627.CSV",
        )
        race_id = "race_20260627_hakodate_7R"
        left = runner._project_race(race_id, run_new(race_id, bundle.races[race_id]))
        right = runner._project_race(race_id, run_new(race_id, bundle.races[race_id]))
        keys = ("decision_score", "adjusted_score", "consensus_positive_count", "consensus_negative_count")
        self.assertEqual([{key: row[key] for key in keys} for row in left["ranked_results"]],
                         [{key: row[key] for key in keys} for row in right["ranked_results"]])

    def _assert_no_forbidden(self, value):
        if isinstance(value, dict):
            self.assertFalse(FORBIDDEN.intersection(value))
            for child in value.values():
                self._assert_no_forbidden(child)
        elif isinstance(value, list):
            for child in value:
                self._assert_no_forbidden(child)
