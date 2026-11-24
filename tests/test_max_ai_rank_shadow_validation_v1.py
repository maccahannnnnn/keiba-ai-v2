import json
import unittest
from pathlib import Path

from analysis import max_ai_rank_shadow_validation_v1 as validation


class MaxAiRankShadowValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = validation.baseline_rows()
        cls.replay = validation.replay_rows()
        cls.summary = json.loads(validation.OUTPUT_JSON.read_text(encoding="utf-8"))

    def test_flag_off_baseline_exact(self): self.assertTrue(all(x["shadow_buy"] == x["production_buy"] for x in validation.apply_shadow(self.baseline)))
    def test_flag_off_replay_exact(self): self.assertTrue(all(x["shadow_buy"] == x["production_buy"] for x in validation.apply_shadow(self.replay)))
    def test_flag_on_rank_max3_baseline(self): self.assertTrue(all(not x["shadow_buy"] or x["ai_rank"] <= 3 for x in validation.apply_shadow(self.baseline, 3)))
    def test_flag_on_rank_max3_replay(self): self.assertTrue(all(not x["shadow_buy"] or x["ai_rank"] <= 3 for x in validation.apply_shadow(self.replay, 3)))
    def test_baseline_current_buy39(self): self.assertEqual(self.summary["results"][0]["current_buy_count"], 39)
    def test_baseline_shadow_buy30(self): self.assertEqual(self.summary["results"][0]["shadow_buy_count"], 30)
    def test_baseline_success_preserved10(self): self.assertEqual(self.summary["results"][0]["shadow_buy_top3"], 10)
    def test_baseline_fp_reduced9(self): self.assertEqual(self.summary["results"][0]["fp_buy_reduction"], 9)
    def test_replay_current_buy36(self): self.assertEqual(self.summary["results"][1]["current_buy_count"], 36)
    def test_replay_shadow_buy31(self): self.assertEqual(self.summary["results"][1]["shadow_buy_count"], 31)
    def test_replay_success_lost2(self): self.assertEqual(self.summary["results"][1]["successful_buy_reduction"], 2)
    def test_replay_fp_reduced3(self): self.assertEqual(self.summary["results"][1]["fp_buy_reduction"], 3)
    def test_replay_rate_declines(self): self.assertLess(self.summary["results"][1]["shadow_buy_place_rate"], self.summary["results"][1]["current_buy_place_rate"])
    def test_decision_distribution_unchanged(self): self.assertTrue(all(x["full_population_decision_unchanged"] for x in self.summary["results"]))
    def test_race_decision_distribution_unchanged(self): self.assertTrue(all(x["full_population_race_decision_unchanged"] for x in self.summary["results"]))
    def test_production_reject(self): self.assertEqual(self.summary["production_adoption"], "REJECT")
    def test_no_target_adapter_reference(self): self.assertNotIn("TargetTrialAdapter", Path(validation.__file__).read_text(encoding="utf-8"))
    def test_no_replay_runner_reference(self): self.assertNotIn("historical_replay_runner", Path(validation.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__": unittest.main()
