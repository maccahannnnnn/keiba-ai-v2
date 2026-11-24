import csv
import json
import unittest
from pathlib import Path

from analysis import ranking_weight_primary_screening_v1 as screening


class RankingWeightPrimaryScreeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads(screening.OUTPUTS["summary"].read_text(encoding="utf-8"))
        with screening.OUTPUTS["cohort"].open(encoding="utf-8-sig", newline="") as handle:
            cls.cohort = list(csv.DictReader(handle))
        with screening.OUTPUTS["transitions"].open(encoding="utf-8-sig", newline="") as handle:
            cls.horses = list(csv.DictReader(handle))

    def test_formal_unique_races_36(self): self.assertEqual(len(self.cohort), 36)
    def test_dates_8(self): self.assertEqual(len({x["race_date"] for x in self.cohort}), 8)
    def test_racecourses_6(self): self.assertEqual(len({x["racecourse"] for x in self.cohort}), 6)
    def test_race_duplicates_zero(self): self.assertEqual(len({x["race_id"] for x in self.cohort}), 36)
    def test_horse_duplicates_zero(self): self.assertEqual(len({(x["race_id"], x["horse_number"]) for x in self.horses}), len(self.horses))
    def test_trace_zero(self): self.assertEqual(sum(int(x["trace_count"]) for x in self.horses), 0)
    def test_all_results_valid(self): self.assertEqual(len(self.horses), self.summary["cohort"]["horse_count"])
    def test_success_buy_10(self): self.assertEqual(self.summary["groups"]["successful_buy"], 10)
    def test_fp_buy_26(self): self.assertEqual(self.summary["groups"]["fp_buy"], 26)
    def test_nonbuy_top3_103(self): self.assertEqual(self.summary["groups"]["non_buy_top3"], 103)
    def test_phase_b_reproduced(self): self.assertTrue(self.summary["phase_b_reproduction"]["reproduced"])
    def test_ability_missing_is_explicit(self): self.assertEqual(self.summary["ability_provenance"], "MISSING")
    def test_candidate_zero_without_go(self): self.assertEqual(self.summary["candidate_count"], 0)
    def test_baseline_not_combined(self): self.assertFalse(self.summary["baseline_reference_only"]["combined_with_current_code_replay"])
    def test_no_adapter_dependency(self): self.assertNotIn("TargetTrialAdapter", Path(screening.__file__).read_text(encoding="utf-8"))
    def test_declared_scope_reconciliation_is_explicit(self): self.assertEqual(self.summary["declared_scope_reconciliation"]["phase2_phase3_batch1_only_unique_races"], 34)
    def test_duplicate_semantics_all_match(self): self.assertTrue(self.summary["cohort"]["all_duplicate_semantics_match"])


if __name__ == "__main__": unittest.main()
