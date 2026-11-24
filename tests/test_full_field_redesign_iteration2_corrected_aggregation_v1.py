from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from review import full_field_redesign_iteration2_corrected_aggregation_v1 as agg

TEST_SANDBOX = Path(__file__).resolve().parents[1] / ".tmp"


def row(*, date="20260301", race="race_20260301_tokyo_10R", horse=1, p_hgb=0.5, p_pl=0.2, p_v5=0.3, adjusted=10.0, pp=8.0, shadow=1):
    return {
        "date": date, "month": date[:6], "race_id": race, "venue": "東京", "race_number": 10,
        "horse_number": horse, "current_buy": True, "shadow_ai_rank": shadow,
        "adjusted_score": adjusted, "past_performance": pp, "p_v5": p_v5,
        "p_pl": p_pl, "p_hgb": p_hgb,
    }


class CorrectedAggregationTest(unittest.TestCase):
    def test_mapping_and_probability_mass(self):
        rows = [row(horse=1, p_hgb=1.0, p_pl=0.1), row(horse=2, p_hgb=1.0, p_pl=0.2), row(horse=3, p_hgb=1.0, p_pl=0.3)]
        self.assertEqual(agg.score(rows[0], "CORRECTED_PLACKETT_LUCE"), 1.0)
        self.assertEqual(agg.score(rows[0], "CORRECTED_HIST_GRADIENT_BOOSTING"), 0.1)
        agg.assert_pl_probability_sanity(rows)

    def test_corrected_tie_break_is_lexical_race_then_horse(self):
        rows = [row(race="race_20260301_tokyo_2R", horse=2), row(race="race_20260301_tokyo_10R", horse=8), row(race="race_20260301_tokyo_10R", horse=3)]
        selected = agg.select_daily_global(rows, "CORRECTED_PLACKETT_LUCE", {"20260301": 3})["20260301"]
        self.assertEqual([item["horse_number"] for item in selected], [3, 8, 2])

    def test_daily_global_top_n(self):
        rows = [row(horse=1, p_hgb=0.1), row(horse=2, p_hgb=0.9), row(horse=3, p_hgb=0.8)]
        selected = agg.select_daily_global(rows, "CORRECTED_PLACKETT_LUCE", {"20260301": 2})["20260301"]
        self.assertEqual([item["horse_number"] for item in selected], [2, 3])

    def test_common_rank1_set(self):
        r1, r2 = row(horse=1, p_hgb=0.8, p_pl=0.7, p_v5=0.6), row(horse=2, p_hgb=0.4, p_pl=0.3, p_v5=0.2)
        selections = {model: {"20260301": [r1, r2]} for model in ("V5_FULL_FIELD_TRAINED", *agg.NEW_MODELS)}
        result = {agg.identity(r1): {"valid_result": True}, agg.identity(r2): {"valid_result": True}}
        output = agg.common_rank1_set(selections, result)
        self.assertEqual(output["V5_FULL_FIELD_TRAINED"]["common_races"], [("20260301", "race_20260301_tokyo_10R")])

    def test_rank1_and_calibration_guards(self):
        self.assertTrue(agg.rank1_guard(0.50, 0.49))
        self.assertFalse(agg.rank1_guard(0.50, 0.4899))
        self.assertTrue(agg.calibration_guard(0.2, 0.2, 2, 7))
        self.assertFalse(agg.calibration_guard(0.2, 0.21, 0, 7))
        self.assertTrue(agg.monthly_current_condition(5, 7))
        self.assertFalse(agg.monthly_current_condition(4, 7))

    def test_candidate_gate_and_model_selection(self):
        passed = agg.candidate_gate(lift_vs_current=.06, current_beaten_months=5, bootstrap_vs_current_lower=.001, rank_guard_pass=True, calibration_guard_pass=True, bootstrap_vs_pp_lower=.001, comparator="CORRECTED_PLACKETT_LUCE")
        hgb = agg.candidate_gate(lift_vs_current=.06, current_beaten_months=5, bootstrap_vs_current_lower=.001, rank_guard_pass=True, calibration_guard_pass=True, bootstrap_vs_pp_lower=.001, comparator="CORRECTED_HIST_GRADIENT_BOOSTING")
        self.assertEqual(passed["status"], "PASS")
        self.assertEqual(agg.select_model(passed, hgb, .001, True), "HIST_GRADIENT_BOOSTING")
        self.assertEqual(agg.select_model(passed, hgb, 0.0, True), "PLACKETT_LUCE")
        with self.assertRaisesRegex(agg.Stop, "STOP_V5_TOP5_GATE_FORBIDDEN"):
            agg.candidate_gate(lift_vs_current=1, current_beaten_months=7, bootstrap_vs_current_lower=1, rank_guard_pass=True, calibration_guard_pass=True, bootstrap_vs_pp_lower=1, comparator="V5_TOP5_TRAINED")

    def test_hgb_minus_pl_bootstrap_direction(self):
        left = {"20260301": {"hits": 1, "valid_n": 10}, "20260302": {"hits": 1, "valid_n": 10}}
        right = {"20260301": {"hits": 2, "valid_n": 10}, "20260302": {"hits": 2, "valid_n": 10}}
        outcome = agg.paired_date_bootstrap(left, right, rounds=10000)
        self.assertGreater(outcome["observed_difference"], 0)

    def test_existing_output_root_stops(self):
        TEST_SANDBOX.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_SANDBOX) as temp:
            path = Path(temp) / "existing"; path.mkdir()
            with self.assertRaisesRegex(agg.Stop, "STOP_OUTPUT_ROOT_ALREADY_EXISTS"):
                agg.assert_fresh_output_root(path)

    def test_sha_mismatch_stops_before_recovery_copy(self):
        TEST_SANDBOX.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_SANDBOX) as temp:
            root = Path(temp); a, b = root / "a.json", root / "b.json"
            a.write_text("not-a-frozen-run", encoding="utf-8"); b.write_text("not-a-frozen-run", encoding="utf-8")
            with self.assertRaisesRegex(agg.Stop, "STOP_FROZEN_SOURCE_SHA_MISMATCH"):
                agg.copy_recovery_inputs(a, b, root / "inputs")


if __name__ == "__main__":
    unittest.main()
