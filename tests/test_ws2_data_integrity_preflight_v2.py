from __future__ import annotations

import copy
import json
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from review.ws2_data_integrity_preflight_v2 import (
    DataIntegrityStop, audit_monthly_incomplete, build_rolling_origin_folds,
    evaluate_preflight, sha256, validate_rolling_origin_folds, write_preflight,
)


ROOT = Path(__file__).resolve().parents[1]


class WS2DataIntegrityPreflightV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = ROOT / ".tmp" / f"ws2_preflight_{uuid4().hex}"
        self.sandbox.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.sandbox, True)
        (self.sandbox / "source.txt").write_text("result-free source identity", encoding="utf-8")
        (self.sandbox / "pipeline.py").write_text("def build_feature(values):\n    return values\n", encoding="utf-8")

    def bundle(self) -> dict:
        races = []
        labels = []
        history = []
        for index, month in enumerate(("202601", "202602", "202603", "202604"), 1):
            race_id = f"r{index}"
            races.append({"race_id": race_id, "target_date": f"{month}15", "de_horse_numbers": [1, 2], "ranked_horse_numbers": [1, 2]})
            labels.extend([
                {"race_id": race_id, "horse_number": 1, "actual_top3": True, "valid_result": True},
                {"race_id": race_id, "horse_number": 2, "actual_top3": False, "valid_result": True},
            ])
            history.append({"race_id": race_id, "horse_number": 1, "target_date": f"{month}15", "past_race_date": f"{month}01"})
        columns = ["row_id", "race_id", "horse_number", "date", "current_score", "actual_top3", "valid_result"]
        policy = [
            {"feature": "row_id", "feature_group": "identity", "source": "dataset", "role": "METADATA", "pre_time_available": True, "pit_class": "PIT_FROZEN_PROSPECTIVE"},
            {"feature": "race_id", "feature_group": "identity", "source": "dataset", "role": "METADATA", "pre_time_available": True, "pit_class": "PIT_FROZEN_PROSPECTIVE"},
            {"feature": "horse_number", "feature_group": "identity", "source": "dataset", "role": "METADATA", "pre_time_available": True, "pit_class": "PIT_FROZEN_PROSPECTIVE"},
            {"feature": "date", "feature_group": "identity", "source": "dataset", "role": "METADATA", "pre_time_available": True, "pit_class": "PIT_FROZEN_PROSPECTIVE"},
            {"feature": "current_score", "feature_group": "current", "source": "pre_payload", "role": "FEATURE", "pre_time_available": True, "pit_class": "PIT_FROZEN_PROSPECTIVE", "required_by_iteration_0": True, "learning_db_dependency": "NONE"},
            {"feature": "actual_top3", "feature_group": "label", "source": "result", "role": "TARGET", "pre_time_available": False, "pit_class": "PIT_FROZEN_PROSPECTIVE", "result_derived": True},
            {"feature": "valid_result", "feature_group": "label_validity", "source": "result", "role": "FORBIDDEN_RESULT", "pre_time_available": False, "pit_class": "PIT_FROZEN_PROSPECTIVE", "result_derived": True},
        ]
        return {
            "generated_at_jst": "2099-01-01T00:00:00+09:00",
            "source_files": [{"path": str((self.sandbox / "source.txt").relative_to(ROOT)), "sha256": sha256(self.sandbox / "source.txt")}],
            "dataset": {"columns": columns, "training_race_ids": ["r1", "r2", "r3"], "rows": [{"race_id": race["race_id"], "horse_number": horse, "date": race["target_date"], "venue": "東京", "current_top5": True} for race in races for horse in (1, 2)]},
            "feature_policy": policy,
            "source_races": races,
            "source_race_exclusions": [{"race_id": "r4", "reason_code": "DECLARED_HOLDOUT"}],
            "past_race_rows": history,
            "label_rows": labels,
            "period_roles": [{"period": month, "roles_history": ["TRAINING"]} for month in ("202601", "202602", "202603", "202604")],
            "rolling_months": ["202601", "202602", "202603", "202604"],
            "used_feature_code_paths": [str((self.sandbox / "pipeline.py").relative_to(ROOT))],
            "v5_runtime": {"model_sha256": "a" * 64, "scaler_sha256": "b" * 64, "feature_spec_sha256": "c" * 64, "training_end_date": "20260913", "dataset_identity": "ML_V4_TRAIN_DATASET_V5", "recipe_identity": "FROZEN_V5", "runtime_identity": "test", "deterministic_reproduction": "PASS"},
            "caller_preflight_pass": True,
        }

    def assert_stop(self, bundle: dict, code: str) -> None:
        with self.assertRaisesRegex(DataIntegrityStop, code):
            evaluate_preflight(bundle, ROOT)

    def test_01_safe_bundle_passes_without_performance_metrics(self):
        result = evaluate_preflight(self.bundle(), ROOT)
        self.assertEqual(result["overall_status"], "PASS")
        self.assertFalse(result["summary"]["caller_status_overrides_used"])
        self.assertFalse(result["summary"]["performance_metrics_emitted"])

    def test_02_result_derived_feature_stops(self):
        value = self.bundle(); value["feature_policy"][4]["result_derived"] = True
        self.assert_stop(value, "RESULT_FEATURE_LEAKAGE")

    def test_02b_result_lineage_feature_stops(self):
        value = self.bundle(); value["feature_policy"][4]["source_lineage"] = ["DE finalized finish_position"]
        self.assert_stop(value, "RESULT_FEATURE_LEAKAGE")

    def test_03_unknown_column_stops(self):
        value = self.bundle(); value["dataset"]["columns"].append("unregistered")
        self.assert_stop(value, "UNREGISTERED_DATASET_COLUMN")

    def test_04_market_feature_stops(self):
        value = self.bundle(); value["dataset"]["columns"][4] = "odds_score"; value["feature_policy"][4]["feature"] = "odds_score"
        self.assert_stop(value, "MARKET_FEATURE_LEAKAGE")

    def test_04b_market_derived_feature_stops_even_without_market_name(self):
        value = self.bundle(); value["feature_policy"][4]["market_derived"] = True
        self.assert_stop(value, "MARKET_FEATURE_LEAKAGE")

    def test_05_future_past_race_stops(self):
        value = self.bundle(); value["past_race_rows"][0]["past_race_date"] = value["past_race_rows"][0]["target_date"]
        self.assert_stop(value, "FUTURE_OR_SAME_DAY_PAST_RACE")

    def test_06_unexplained_source_race_exclusion_stops(self):
        value = self.bundle(); value["source_race_exclusions"] = []
        self.assert_stop(value, "UNEXPLAINED_SOURCE_RACE_EXCLUSION")

    def test_07_period_role_contradiction_stops(self):
        value = self.bundle(); value["period_roles"][0]["roles_history"] = ["TRAINING", "UNTOUCHED_CANDIDATE"]
        self.assert_stop(value, "PERIOD_ROLE_CONTRADICTION")

    def test_08_future_training_month_stops(self):
        with self.assertRaisesRegex(DataIntegrityStop, "ROLLING_ORIGIN_FUTURE_LEAKAGE"):
            validate_rolling_origin_folds([{"training_months": ["202601", "202602", "202604"], "validation_month": "202603"}])

    def test_09_horse_set_mismatch_stops(self):
        value = self.bundle(); value["source_races"][0]["ranked_horse_numbers"] = [1, 2, 3]
        self.assert_stop(value, "HORSE_SET_MISMATCH")

    def test_10_source_sha_mismatch_stops(self):
        value = self.bundle(); value["source_files"][0]["sha256"] = "0" * 64
        self.assert_stop(value, "SOURCE_HASH_MISMATCH")

    def test_11_required_pit_unproven_stops(self):
        value = self.bundle(); value["feature_policy"][4]["pit_class"] = "PIT_UNPROVEN"
        self.assert_stop(value, "ITERATION_0_REQUIRED_FEATURE_PIT_UNPROVEN")

    def test_12_confirmed_learning_dependency_stops(self):
        (self.sandbox / "pipeline.py").write_text("Path('learning/state.json').read_text()\n", encoding="utf-8")
        value = self.bundle()
        self.assert_stop(value, "CONFIRMED_LEARNING_DB_DEPENDENCY")

    def test_13_duplicate_or_inconsistent_label_stops(self):
        value = self.bundle(); value["label_rows"].append(dict(value["label_rows"][0]))
        self.assert_stop(value, "LABEL_IDENTITY_OR_DUPLICATION")
        value = self.bundle(); value["label_rows"][0]["valid_result"] = False
        self.assert_stop(value, "LABEL_INCONSISTENCY")

    def test_14_no_untouched_holdout_is_info_not_stop(self):
        result = evaluate_preflight(self.bundle(), ROOT)
        self.assertEqual(result["holdout"]["status"], "NO_UNTOUCHED_HISTORICAL_HOLDOUT_AVAILABLE")

    def test_15_monthly_incomplete_exactly_five_percent_is_usable_warn(self):
        complete = [{"month": "202601"} for _ in range(19)]; incomplete = [{"month": "202601"}]
        monthly, warnings = audit_monthly_incomplete(complete, incomplete)
        self.assertEqual(monthly[0]["rolling_origin_role"], "USABLE_FOR_ROLLING_ORIGIN")
        self.assertEqual(len(warnings), 1)

    def test_16_monthly_incomplete_over_five_percent_is_excluded(self):
        complete = [{"month": "202601"} for _ in range(18)]; incomplete = [{"month": "202601"}, {"month": "202601"}]
        monthly, warnings = audit_monthly_incomplete(complete, incomplete)
        self.assertEqual(monthly[0]["rolling_origin_role"], "EXCLUDED_FROM_ROLLING_ORIGIN")
        self.assertEqual(warnings, [])

    def test_17_three_prior_months_are_accepted(self):
        folds = build_rolling_origin_folds(["202601", "202602", "202603", "202604"], {month: ["TRAINING"] for month in ("202601", "202602", "202603", "202604")})
        self.assertEqual(folds, [{"training_months": ["202601", "202602", "202603"], "validation_month": "202604", "primary": "ROLLING_ORIGIN_MONTHLY_CROSS_FIT", "lomo": "SENSITIVITY_ONLY"}])

    def test_18_fewer_than_three_months_stops(self):
        with self.assertRaisesRegex(DataIntegrityStop, "ROLLING_ORIGIN_EMPTY"):
            build_rolling_origin_folds(["202601", "202602", "202603"], {month: ["TRAINING"] for month in ("202601", "202602", "202603")})

    def test_19_semantic_output_is_deterministic_and_writer_is_exclusive(self):
        value = self.bundle(); first = evaluate_preflight(value, ROOT); second = evaluate_preflight(copy.deepcopy(value), ROOT)
        self.assertEqual(first, second)
        bundle_path = self.sandbox / "bundle.json"; bundle_path.write_text(json.dumps(value), encoding="utf-8")
        output = self.sandbox / "output"; target = write_preflight(bundle_path, output, ROOT)
        self.assertTrue(target.is_file())
        with self.assertRaisesRegex(DataIntegrityStop, "OUTPUT_ALREADY_EXISTS"):
            write_preflight(bundle_path, output, ROOT)

    def test_20_stop_output_is_machine_readable_and_non_training(self):
        value = self.bundle(); value["feature_policy"][4]["result_derived"] = True
        bundle_path = self.sandbox / "bad_bundle.json"; bundle_path.write_text(json.dumps(value), encoding="utf-8")
        target = write_preflight(bundle_path, self.sandbox / "stop_output", ROOT)
        output = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(output["overall_status"], "STOP")
        self.assertFalse(output["summary"]["training_started"])


if __name__ == "__main__":
    unittest.main()
