import ast
import csv
import inspect
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from analysis import final_score_shadow_validation_v1 as module


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def sample_rows():
    return [
        {"cohort": "X", "race_id": "race_1", "horse_number": "1", "horse_name": "A", "final_score": 10.0, "adjusted_score": 20.0, "production_rank": 1, "decision": "BUY", "race_decision": "PLAY", "buy": True, "explain_sha256": "x", "valid_result": True, "actual_finish": 1, "actual_top3": True, "actual_top5": True, "source_run": "fixture", "race_date": "20260101", "racecourse": "tokyo"},
        {"cohort": "X", "race_id": "race_1", "horse_number": "2", "horse_name": "B", "final_score": 10.0, "adjusted_score": 19.0, "production_rank": 2, "decision": "PASS", "race_decision": "PLAY", "buy": False, "explain_sha256": "y", "valid_result": True, "actual_finish": 4, "actual_top3": False, "actual_top5": True, "source_run": "fixture", "race_date": "20260101", "racecourse": "tokyo"},
    ]


class FinalScoreShadowValidationV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads((REPORTS / "final_score_shadow_summary_v1.json").read_text(encoding="utf-8"))
        cls.safety = json.loads((REPORTS / "final_score_shadow_safety_v1.json").read_text(encoding="utf-8"))
        cls.zero = json.loads((REPORTS / "final_score_shadow_zero_delta_v1.json").read_text(encoding="utf-8"))
        cls.baseline, _ = module.load_baseline_rows()
        cls.replay, _ = module.load_replay_rows()

    def test_01_flag_default_is_off(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(module.flag_enabled())
        self.assertEqual(module.FLAG_DEFAULT, "OFF")

    def test_02_flag_off_is_exact_identity(self):
        rows = sample_rows(); off = module.rank_shadow_rows(rows, enabled=False)
        self.assertEqual(rows, off); self.assertIsNot(rows, off)

    def test_03_flag_on_adds_only_shadow_rank(self):
        rows = sample_rows(); on = module.rank_shadow_rows(rows, enabled=True)
        for original, shadow in zip(rows, on):
            self.assertEqual(set(shadow) - set(original), {"shadow_rank"})

    def test_04_final_score_tie_break_uses_horse_number_desc(self):
        on = module.rank_shadow_rows(sample_rows(), enabled=True)
        ranks = {row["horse_number"]: row["shadow_rank"] for row in on}
        self.assertEqual(ranks, {"2": 1, "1": 2})

    def test_05_score_values_are_not_changed(self):
        rows = sample_rows(); on = module.rank_shadow_rows(rows, enabled=True)
        self.assertEqual([(r["final_score"], r["adjusted_score"]) for r in rows], [(r["final_score"], r["adjusted_score"]) for r in on])

    def test_06_decision_race_decision_buy_explain_are_not_changed(self):
        rows = sample_rows(); on = module.rank_shadow_rows(rows, enabled=True)
        for field in ("decision", "race_decision", "buy", "explain_sha256"):
            self.assertEqual([r[field] for r in rows], [r[field] for r in on])

    def test_07_formal_cohort_counts(self):
        self.assertEqual((len(self.baseline), sum(r["valid_result"] for r in self.baseline)), (448, 443))
        self.assertEqual((len(self.replay), sum(r["valid_result"] for r in self.replay)), (512, 512))

    def test_08_cohort_race_counts(self):
        results = self.summary["cohort_results"]
        self.assertEqual(results["BASELINE"]["race_count"], 34)
        self.assertEqual(results["REPLAY"]["race_count"], 36)

    def test_09_race_horse_keys_are_unique(self):
        result = module.validate_rows(self.baseline + self.replay)
        self.assertTrue(result["unique"])

    def test_10_saved_adjusted_rank_differences_are_legacy_ties_only(self):
        audit = self.summary["adjusted_rank_validation"]
        self.assertEqual(audit["status"], "PASS_WITH_LEGACY_TIE_DIFFERENCE")
        self.assertEqual(audit["adjusted_rank_mismatch_count"], 4)
        self.assertEqual(audit["non_tie_mismatch_count"], 0)
        self.assertEqual(audit["replay_mismatch_count"], 0)

    def test_11_movement_rate_reconciles(self):
        for result in self.summary["cohort_results"].values():
            self.assertAlmostEqual(result["movement_rate"], result["movement_count"] / result["horse_count"], places=7)

    def test_12_metric_csv_has_separate_overall_cohorts(self):
        with (REPORTS / "final_score_shadow_metric_comparison_v1.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        overall = {(r["cohort"], r["metric"]) for r in rows if r["slice_axis"] == "OVERALL"}
        for cohort in ("BASELINE", "REPLAY"):
            self.assertIn((cohort, "rank1_3_top3_rate"), overall)
            self.assertIn((cohort, "mean_actual_top3_rank"), overall)

    def test_13_integrated_metrics_are_reference_only(self):
        self.assertFalse(self.summary["cohorts_combined_for_judgment"])
        with (REPORTS / "final_score_shadow_metric_comparison_v1.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        integrated = [r for r in rows if r["cohort"] == "INTEGRATED_REFERENCE"]
        self.assertTrue(integrated); self.assertEqual({r["reference_only"] for r in integrated}, {"True"})

    def test_14_below_ten_percent_movement_is_inconclusive(self):
        base = {"movement_rate": .09, "delta": {"rank1_3_top3_rate": .05, "mean_actual_top3_rank": -.1, "ndcg_at_3": 0, "mrr": 0}}
        self.assertEqual(module.classify_result({"BASELINE": base, "REPLAY": base})[0], "INCONCLUSIVE")

    def test_15_full_accept_rule(self):
        full = {"movement_rate": .2, "delta": {"rank1_3_top3_rate": .03, "mean_actual_top3_rank": -.1, "ndcg_at_3": 0, "mrr": 0}}
        self.assertEqual(module.classify_result({"BASELINE": full, "REPLAY": full})[0], "FULL_ACCEPT")

    def test_16_partial_accept_rule(self):
        partial = {"movement_rate": .2, "delta": {"rank1_3_top3_rate": .02, "mean_actual_top3_rank": -.1, "ndcg_at_3": -.01, "mrr": 0}}
        self.assertEqual(module.classify_result({"BASELINE": partial, "REPLAY": partial})[0], "PARTIAL_ACCEPT")

    def test_17_primary_worsening_is_reject(self):
        bad = {"movement_rate": .2, "delta": {"rank1_3_top3_rate": -.01, "mean_actual_top3_rank": .1, "ndcg_at_3": 0, "mrr": 0}}
        self.assertEqual(module.classify_result({"BASELINE": bad, "REPLAY": bad})[0], "REJECT")

    def test_18_cohort_reversal_is_reject(self):
        good = {"movement_rate": .2, "delta": {"rank1_3_top3_rate": .02, "mean_actual_top3_rank": -.1, "ndcg_at_3": 0, "mrr": 0}}
        bad = {"movement_rate": .2, "delta": {"rank1_3_top3_rate": -.02, "mean_actual_top3_rank": .1, "ndcg_at_3": 0, "mrr": 0}}
        status, reasons = module.classify_result({"BASELINE": good, "REPLAY": bad})
        self.assertEqual(status, "REJECT"); self.assertIn("COHORT_DIRECTION_REVERSAL", reasons)

    def test_19_rank_transition_count_and_uniqueness(self):
        with (REPORTS / "final_score_shadow_rank_transition_v1.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 960)
        self.assertEqual(len(rows), len({(r["cohort"], r["race_id"], r["horse_number"]) for r in rows}))

    def test_20_top5_capture_is_bounded(self):
        for result in self.summary["cohort_results"].values():
            for ranking in ("production", "shadow"):
                self.assertGreaterEqual(result[ranking]["top5_capture_rate"], 0)
                self.assertLessEqual(result[ranking]["top5_capture_rate"], 1)

    def test_21_safety_pass(self):
        self.assertEqual(self.safety["status"], "PASS")
        self.assertEqual(self.safety["target_trial_adapter_run_count"], 0)
        self.assertEqual(self.safety["replay_run_count"], 0)

    def test_22_zero_delta_pass(self):
        self.assertEqual(self.zero["status"], "PASS")
        self.assertEqual(self.zero["protected_changes"], [])
        self.assertEqual(self.zero["production_field_mutations"], [])

    def test_23_source_has_no_adapter_evaluator_or_replay_execution(self):
        source = inspect.getsource(module); tree = ast.parse(source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        forbidden = {"TargetTrialAdapter", "TargetEntryImporter", "TargetHistoryImporter", "HistoricalReplayRunner"}
        self.assertFalse(any(isinstance(node.func, ast.Name) and node.func.id in forbidden for node in calls))

    def test_24_roi_contains_required_candidates(self):
        names = {row["candidate"] for row in self.summary["roi_ranking"]}
        self.assertEqual(names, {"final_score Shadow", "Placebo", "誤順位分析", "騎手Shadow", "ランキング再設計"})


if __name__ == "__main__":
    unittest.main()
