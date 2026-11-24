import json
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from analysis.pre_race_recency_shadow_validation_v1 import (
    FLAG_NAME,
    SPEC_SHA256,
    TargetHistoryImporter,
    category_for_days,
    classify_result,
    flag_enabled,
    rank_shadow_rows,
    recency_from_history,
    sha256,
)
from importer.target_history_importer import HorseHistory


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
FIXTURE = ROOT / "tests" / "fixtures" / "pre_race_recency_shadow_v1_fixture.json"


def raw_row(horse_name, year, month, day):
    row = [""] * 53
    row[0], row[1], row[2], row[16] = year, month, day, horse_name
    return row


def history_from_fixture(case):
    importer = TargetHistoryImporter()
    runs = [importer._row_to_run(raw_row(case["horse_name"], *parts)) for parts in case["raw_history_dates"]]
    return HorseHistory(case["horse_name"], runs)


def sample_rows():
    return [
        {"race_id": "race_20260710_tokyo_1R", "horse_number": "1", "production_adjusted_score": 100.0, "production_rank": 1, "decision": "BUY", "race_decision": "PLAY", "buy": True, "explain": {"text": "original"}},
        {"race_id": "race_20260710_tokyo_1R", "horse_number": "2", "production_adjusted_score": 99.0, "production_rank": 2, "decision": "PASS", "race_decision": "PLAY", "buy": False, "explain": {"text": "original2"}},
    ]


class PreRaceRecencyShadowValidationV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def fixture_case(self, name):
        return next(item for item in self.fixture["cases"] if item["horse_name"] == name)

    def test_01_flag_off_complete_identity(self):
        rows = sample_rows(); off = rank_shadow_rows(rows, {}, enabled=False)
        self.assertEqual(rows, off); self.assertIsNot(rows, off)
        with patch.dict(os.environ, {}, clear=True): self.assertFalse(flag_enabled())
        self.assertEqual(sha256(REPORTS / "pre_race_recency_additive_v1_preregistered_spec.md"), SPEC_SHA256)

    def test_02_future_history_rejected(self):
        result = recency_from_history(datetime(2026, 7, 10), history_from_fixture(self.fixture_case("PRIOR_SAME_FUTURE_INVALID")))
        self.assertEqual(result["rejected_future_count"], 2)

    def test_03_same_day_history_rejected(self):
        result = recency_from_history(datetime(2026, 7, 10), history_from_fixture(self.fixture_case("PRIOR_SAME_FUTURE_INVALID")))
        self.assertEqual(result["rejected_same_day_count"], 1)

    def test_04_only_before_race_is_accepted(self):
        result = recency_from_history(datetime(2026, 7, 10), history_from_fixture(self.fixture_case("PRIOR_SAME_FUTURE_INVALID")))
        self.assertEqual(result["accepted_prior_history_count"], 2)

    def test_05_latest_prior_history_selected(self):
        result = recency_from_history(datetime(2026, 7, 10), history_from_fixture(self.fixture_case("PRIOR_SAME_FUTURE_INVALID")))
        self.assertEqual(result["shadow_latest_history_date"], "2026/07/09")

    def test_06_invalid_date_not_inferred(self):
        result = recency_from_history(datetime(2026, 7, 10), history_from_fixture(self.fixture_case("INVALID_ONLY")))
        self.assertEqual(result["rejected_invalid_count"], 1); self.assertEqual(result["shadow_recency_days"], "")

    def test_07_two_digit_year_uses_existing_importer(self):
        history = history_from_fixture(self.fixture_case("TWO_DIGIT_YEAR"))
        self.assertEqual(history.runs[0].race_date, "2025/12/31")

    def test_08_no_history_zero_and_trace(self):
        result = recency_from_history(datetime(2026, 7, 10), history_from_fixture(self.fixture_case("NO_HISTORY")))
        self.assertEqual((result["shadow_recency_score"], result["shadow_recency_trace_status"]), (0, "TRACE"))

    def test_09_boundary_9_10(self):
        self.assertEqual(category_for_days(9)[1], -3); self.assertEqual(category_for_days(10)[1], 0)

    def test_10_boundary_16_17(self):
        self.assertEqual(category_for_days(16)[1], 0); self.assertEqual(category_for_days(17)[1], 5)

    def test_11_boundary_35_36(self):
        self.assertEqual(category_for_days(35)[1], 5); self.assertEqual(category_for_days(36)[1], 0)

    def test_12_boundary_63_64(self):
        self.assertEqual(category_for_days(63)[1], 0); self.assertEqual(category_for_days(64)[1], -3)

    def test_13_boundary_180_181(self):
        self.assertEqual(category_for_days(180)[1], -3); self.assertEqual(category_for_days(181)[1], -5)

    def test_14_score_cap_plus_minus_5(self):
        self.assertTrue(all(abs(category_for_days(day)[1]) <= 5 for day in [0, 9, 10, 16, 17, 35, 36, 63, 64, 180, 181, 9999]))

    def test_15_production_score_unchanged(self):
        rows = sample_rows(); lookup = {"1": {"shadow_recency_days": 20, "shadow_recency_category": "TWO_TO_FOUR_WEEKS", "shadow_recency_score": 5, "shadow_recency_trace_status": "COMPLETE"}, "2": {"shadow_recency_days": 200, "shadow_recency_category": "LONG_RETURN", "shadow_recency_score": -5, "shadow_recency_trace_status": "COMPLETE"}}
        on = rank_shadow_rows(rows, lookup, enabled=True); self.assertEqual([x["production_adjusted_score"] for x in on], [100.0, 99.0])

    def test_16_production_rank_unchanged(self):
        rows = sample_rows(); on = rank_shadow_rows(rows, {}, enabled=True)
        self.assertEqual(sorted(x["production_rank"] for x in on), [1, 2])

    def test_17_decision_unchanged(self):
        rows = sample_rows(); on = rank_shadow_rows(rows, {}, enabled=True)
        self.assertEqual(sorted(x["decision"] for x in on), ["BUY", "PASS"])

    def test_18_buy_unchanged(self):
        rows = sample_rows(); on = rank_shadow_rows(rows, {}, enabled=True)
        self.assertEqual(sorted(x["buy"] for x in on), [False, True])

    def test_19_shadow_fields_only_generated_when_on(self):
        rows = sample_rows(); off = rank_shadow_rows(rows, {}, enabled=False); on = rank_shadow_rows(rows, {}, enabled=True)
        self.assertNotIn("shadow_rank", off[0]); self.assertIn("shadow_rank", on[0]); self.assertIn("shadow_explain", on[0])

    def test_20_baseline_replay_are_separate(self):
        baseline = json.loads((REPORTS / "pre_race_recency_baseline_result_v1.json").read_text(encoding="utf-8"))
        replay = json.loads((REPORTS / "pre_race_recency_replay_result_v1.json").read_text(encoding="utf-8"))
        self.assertEqual((baseline["cohort"], baseline["race_count"]), ("BASELINE", 34)); self.assertEqual((replay["cohort"], replay["race_count"]), ("REPLAY", 36))

    def test_21_movement_rate_calculation(self):
        summary = json.loads((REPORTS / "pre_race_recency_shadow_summary_v1.json").read_text(encoding="utf-8"))
        for result in summary["cohort_results"].values(): self.assertAlmostEqual(result["movement_rate"], result["movement_count"] / result["horse_count"], places=7)

    def test_22_below_10_percent_is_inconclusive(self):
        result = {"movement_rate": .09, "delta": {"rank1_3_top3_rate": .1, "mean_actual_top3_rank": -1, "ndcg_at_3": 0, "mrr": 0}, "actual_top3_top3_outflow_count": 0}
        self.assertEqual(classify_result({"BASELINE": result, "REPLAY": result})[0], "INCONCLUSIVE_INSUFFICIENT_MOVEMENT")

    def test_23_retry_limit_is_one(self):
        summary = json.loads((REPORTS / "pre_race_recency_shadow_summary_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["retry_limit"], 1); self.assertEqual(summary["retry_count_used"], 0)

    def test_24_cohort_reversal_is_reject(self):
        base = {"movement_rate": .2, "delta": {"rank1_3_top3_rate": .03, "mean_actual_top3_rank": -.2, "ndcg_at_3": 0, "mrr": 0}, "actual_top3_top3_outflow_count": 0}
        replay = {"movement_rate": .2, "delta": {"rank1_3_top3_rate": -.03, "mean_actual_top3_rank": .2, "ndcg_at_3": 0, "mrr": 0}, "actual_top3_top3_outflow_count": 0}
        status, reasons = classify_result({"BASELINE": base, "REPLAY": replay}); self.assertEqual(status, "REJECT"); self.assertIn("COHORT_EFFECT_REVERSAL", reasons)

    def test_25_safety_pass(self):
        safety = json.loads((REPORTS / "pre_race_recency_shadow_safety_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(safety["status"], "PASS"); self.assertEqual(safety["target_trial_adapter_run_count"], 0)

    def test_26_zero_delta_pass(self):
        zero = json.loads((REPORTS / "pre_race_recency_shadow_zero_delta_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(zero["status"], "PASS"); self.assertEqual(zero["protected_changes"], [])

if __name__ == "__main__":
    unittest.main()
