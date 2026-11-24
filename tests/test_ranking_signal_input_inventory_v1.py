import csv
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


class RankingSignalInputInventoryV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (REPORTS / "ranking_signal_input_inventory_v1.csv").open(encoding="utf-8-sig", newline="") as handle:
            cls.inventory = list(csv.DictReader(handle))
        with (REPORTS / "ranking_signal_candidate_priority_v1.csv").open(encoding="utf-8-sig", newline="") as handle:
            cls.candidates = list(csv.DictReader(handle))
        cls.summary = json.loads((REPORTS / "ranking_signal_summary_v1.json").read_text(encoding="utf-8"))
        cls.safety = json.loads((REPORTS / "ranking_signal_safety_v1.json").read_text(encoding="utf-8"))

    def test_inventory_has_priority_and_other_raw_fields(self):
        ids = {row["field_id"] for row in self.inventory}
        self.assertTrue({"jockey", "trainer", "weight_carried", "body_weight", "body_weight_diff", "frame_number", "horse_number", "sex_age", "layoff_interval", "affiliation", "owner", "breeder"}.issubset(ids))

    def test_cohorts_are_separate_and_expected_size(self):
        self.assertEqual(self.summary["cohorts"]["baseline"]["race_count"], 34)
        self.assertEqual(self.summary["cohorts"]["baseline"]["horse_count"], 448)
        self.assertEqual(self.summary["cohorts"]["replay"]["race_count"], 36)
        self.assertEqual(self.summary["cohorts"]["replay"]["horse_count"], 512)
        self.assertFalse(self.summary["cohorts"]["baseline"]["combined_with_replay"])

    def test_selected_candidate_is_complete_and_pre_race(self):
        selected = [row for row in self.candidates if row["selected"] == "YES"]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["input_field"], "layoff_interval")
        self.assertLessEqual(float(selected[0]["baseline_missing_rate"]), 0.10)
        self.assertLessEqual(float(selected[0]["replay_missing_rate"]), 0.10)
        self.assertIn("PRE_DATE_FILTER", selected[0]["leak_risk"])

    def test_candidate_limit_and_prohibited_number(self):
        self.assertLessEqual(len(self.candidates), 3)
        self.assertNotIn("horse_number", {row["input_field"] for row in self.candidates})

    def test_body_weight_rejected_for_missingness(self):
        row = next(row for row in self.inventory if row["field_id"] == "body_weight")
        self.assertEqual(float(row["baseline_missing_rate"]), 1.0)
        self.assertGreater(float(row["replay_missing_rate"]), 0.10)
        self.assertEqual(row["candidate_eligible"], "NO")

    def test_frame_and_horse_number_not_claimed_unused(self):
        rows = {row["field_id"]: row for row in self.inventory}
        self.assertEqual(rows["frame_number"]["usage_class"], "USED")
        self.assertEqual(rows["horse_number"]["usage_class"], "USED_CONTROL_ONLY")

    def test_safety_and_forbidden_execution_counts(self):
        self.assertEqual(self.safety["status"], "PASS")
        self.assertEqual(self.safety["target_trial_adapter_run_count"], 0)
        self.assertEqual(self.safety["replay_run_count"], 0)
        self.assertEqual(self.safety["evaluator_run_count"], 0)
        self.assertEqual(self.safety["weight_recalculation_count"], 0)
        self.assertFalse(self.safety["result_used_for_pre_recalculation"])
        self.assertEqual(self.safety["protected_changes"], [])


if __name__ == "__main__":
    unittest.main()
