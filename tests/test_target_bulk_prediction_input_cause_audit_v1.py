import csv
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "target_bulk_prediction_input_cause_audit_v1"


class TargetBulkPredictionInputCauseAuditV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads(
            (OUT / "target_bulk_prediction_input_cause_audit_summary_v1.json").read_text(encoding="utf-8")
        )
        with (OUT / "target_bulk_prediction_input_buy_loss_7_v1.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            cls.buy_rows = list(csv.DictReader(handle))
        with (OUT / "target_bulk_prediction_input_evaluator_aggregate_v1.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            cls.aggregate = list(csv.DictReader(handle))

    def test_old_buy_population_is_exactly_seven(self):
        self.assertEqual(len(self.buy_rows), 7)
        self.assertEqual(self.summary["old_buy_count"], 7)

    def test_all_seven_lost_buy(self):
        self.assertTrue(all(row["old_decision"] == "BUY" for row in self.buy_rows))
        self.assertTrue(all(row["new_decision"] != "BUY" for row in self.buy_rows))

    def test_taxonomy_has_no_undetermined(self):
        self.assertNotIn("E_UNDETERMINED", self.summary["taxonomy_counts"])
        self.assertEqual(sum(self.summary["taxonomy_counts"].values()), 7)

    def test_adapter_bug_candidate_is_evidence_backed(self):
        self.assertEqual(self.summary["adapter_bug"]["status"], "BUG_CANDIDATE")
        self.assertEqual(
            set(self.summary["adapter_bug"]["affected_runtime_fields"]),
            {"surface", "margin", "last_3f", "pci", "rpci"},
        )

    def test_all_horses_shift_negative(self):
        distribution = self.summary["final_score_delta_distribution"]
        self.assertEqual(distribution["horse_count"], 223)
        self.assertEqual(distribution["negative_count"], 223)
        self.assertEqual(distribution["zero_count"], 0)
        self.assertEqual(distribution["positive_count"], 0)

    def test_evaluator_aggregate_counts_reconcile(self):
        self.assertEqual(len(self.aggregate), 9)
        for row in self.aggregate:
            total = int(row["positive_count"]) + int(row["negative_count"]) + int(row["zero_count"])
            self.assertEqual(total, 223, row["evaluator"])

    def test_current_day_track_condition_is_missing_in_new(self):
        self.assertEqual(self.summary["new_current_track_condition_missing_race_count"], 16)
        self.assertEqual(
            self.summary["old_current_track_condition_source_counts"],
            {"history_dominant_inference": 16},
        )

    def test_production_switch_and_foundation_hold(self):
        self.assertEqual(self.summary["production_switch"], "REJECT")
        self.assertEqual(self.summary["dg_de_ds_foundation"], "FIX_REQUIRED")

    def test_safety_and_zero_delta_pass(self):
        self.assertEqual(self.summary["safety"]["status"], "PASS")
        self.assertEqual(self.summary["zero_delta"]["status"], "PASS")
        self.assertEqual(self.summary["safety"]["production_protected_changed_count"], 0)


if __name__ == "__main__":
    unittest.main()
