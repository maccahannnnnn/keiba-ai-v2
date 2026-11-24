import unittest

from analysis.weakness_analysis_106race_day2_v2 import (
    SPEC_SHA256,
    average_rank_percentiles,
    classify_percentiles,
    cohort_role,
)


class WeaknessAnalysis106RaceDay2V2Tests(unittest.TestCase):
    def test_frozen_sha(self):
        self.assertEqual(SPEC_SHA256, "3f010795f76ef85f410e1fcfe7b224fa18ac37a4be68a386ee94fc537c593800")

    def test_average_rank_percentile_tie(self):
        self.assertEqual(average_rank_percentiles([1, 2, 2, 4]), [25.0, 62.5, 62.5, 100.0])

    def test_classification_a(self):
        self.assertEqual(classify_percentiles([10, 20, 30, 35, 39, 40, 50, 60])[0], "a")

    def test_classification_b(self):
        self.assertEqual(classify_percentiles([5, 55, 60, 65, 70, 75, 80, 85])[0], "b")

    def test_classification_c(self):
        self.assertEqual(classify_percentiles([45, 45, 45, 45, 45, 45, 45, 45])[0], "c")

    def test_target_role(self):
        row = {"valid_result": True, "decision": "CAUTION", "actual_top3": True, "final_rank": 6}
        self.assertEqual(cohort_role(row), "TARGET")

    def test_rank5_top3_is_not_target(self):
        row = {"valid_result": True, "decision": "PASS", "actual_top3": True, "final_rank": 5}
        self.assertEqual(cohort_role(row), "OTHER")

    def test_control_has_no_rank_filter(self):
        row = {"valid_result": True, "decision": "PASS", "actual_top3": False, "final_rank": 1}
        self.assertEqual(cohort_role(row), "CONTROL")

    def test_invalid_excluded(self):
        row = {"valid_result": False, "decision": "PASS", "actual_top3": False, "final_rank": 8}
        self.assertEqual(cohort_role(row), "INVALID_RESULT_EXCLUDED")


if __name__ == "__main__":
    unittest.main()
