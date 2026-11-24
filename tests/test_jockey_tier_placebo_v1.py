import json, unittest
from collections import Counter
from pathlib import Path
from analysis import jockey_tier_placebo_v1 as p

ROOT=Path(__file__).resolve().parents[1]; REPORTS=ROOT/"reports"
class JockeyTierPlaceboV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=p.read_rows(); cls.seed_rows=p.v1.read_csv(REPORTS/"jockey_tier_placebo_seed_results_v1.csv")
        cls.summary=json.loads((REPORTS/"jockey_tier_placebo_summary_v1.json").read_text(encoding="utf-8")); cls.safety=json.loads((REPORTS/"jockey_tier_placebo_safety_v1.json").read_text(encoding="utf-8")); cls.zero=json.loads((REPORTS/"jockey_tier_placebo_zero_delta_v1.json").read_text(encoding="utf-8"))
    def test_01_frozen_seeds(self): self.assertEqual(p.SEEDS,(11,17,23,29,37,41,47,53,59,67,71,73,79,83,89,97,101,103,107,109))
    def test_02_seed_count(self): self.assertEqual(len(p.SEEDS),20)
    def test_03_tier_sha_fixed(self): self.assertEqual(self.summary["tier_table_sha256"],"3cdb6e18fe4594b0e2250de7e5d2ce086acbe8b3737cab2bd973e855f217f938")
    def test_04_within_race_distribution_exact(self):
        assigned=p.assign(self.rows,11)
        for key,rr in p.groups(assigned).items(): self.assertEqual(Counter((r["shadow_jockey_tier"],r["shadow_jockey_score"]) for r in p.groups(self.rows)[key]),Counter((r["placebo_tier"],r["placebo_score"]) for r in rr))
    def test_05_deterministic(self): self.assertEqual(p.assign(self.rows,11),p.assign(self.rows,11))
    def test_06_no_cross_race_assignment(self): self.assertTrue(self.summary["within_race_distribution_exact"])
    def test_07_input_identity_preserved(self): self.assertTrue(self.zero["feature_flag_off_input_identity"])
    def test_08_production_fields_unchanged(self): self.assertEqual(self.zero["production_field_mutation_count"],0)
    def test_09_each_cohort_has_20_results(self):
        self.assertEqual(sum(r["cohort"]=="BASELINE" for r in self.seed_rows),20); self.assertEqual(sum(r["cohort"]=="REPLAY" for r in self.seed_rows),20)
    def test_10_percentile_linear(self): self.assertEqual(p.percentile([0,10],.5),5)
    def test_11_baseline_observed_percentile(self): self.assertEqual(next(r for r in self.summary["observed_percentiles"] if r["cohort"]=="BASELINE" and r["metric"]=="rank1_3_top3_rate")["observed_percentile"],100)
    def test_12_replay_observed_percentile(self): self.assertEqual(next(r for r in self.summary["observed_percentiles"] if r["cohort"]=="REPLAY" and r["metric"]=="rank1_3_top3_rate")["observed_percentile"],72.5)
    def test_13_interpretation(self): self.assertEqual(self.summary["final_interpretation"],"PLACEBO_VARIANCE_HOLD")
    def test_14_safety_pass(self): self.assertEqual(self.safety["status"],"PASS")
    def test_15_zero_delta_pass(self): self.assertEqual(self.zero["status"],"PASS")
    def test_16_no_adapter_replay_evaluator(self): self.assertEqual((self.summary["target_trial_adapter_run_count"],self.summary["replay_run_count"],self.summary["evaluator_run_count"]),(0,0,0))
    def test_17_no_v2_or_new_candidate(self): self.assertFalse(self.summary["jockey_v2_executed"]); self.assertFalse(self.summary["new_shadow_candidate_created"])
    def test_18_jockey_v1_closed(self): self.assertTrue(self.summary["jockey_v1_closed"])
if __name__=="__main__": unittest.main()
