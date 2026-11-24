from __future__ import annotations

import unittest

from review.ml_v4_buy_selection_dataset_build_v5_1 import (
    Stop,
    assert_only_gap_changes,
    pre_result_current_top5_gaps,
)


def payload(outside_score: float = 99.0, outcome: str = "invalid") -> dict:
    return {
        "ranked_results": [
            {"horse_number": 1, "rank": 1, "adjusted_score": 10.0},
            {"horse_number": 2, "rank": 2, "adjusted_score": 8.0},
            {"horse_number": 3, "rank": 3, "adjusted_score": 7.0},
            {"horse_number": 4, "rank": 4, "adjusted_score": 6.0},
            {"horse_number": 5, "rank": 5, "adjusted_score": 5.0},
            {"horse_number": 6, "rank": 6, "adjusted_score": outside_score, "post_result_outcome": outcome},
        ]
    }


class PreResultCurrentTop5GapTests(unittest.TestCase):
    def test_top5_highest_score_is_reference_even_when_its_result_is_invalid(self) -> None:
        source = payload()
        source["ranked_results"][0]["post_result_outcome"] = "DNF"
        self.assertEqual(pre_result_current_top5_gaps(source), {"1": 0.0, "2": -2.0, "3": -3.0, "4": -4.0, "5": -5.0})

    def test_dnf_or_cancelled_outcome_cannot_change_gap(self) -> None:
        self.assertEqual(pre_result_current_top5_gaps(payload(outcome="DNF")), pre_result_current_top5_gaps(payload(outcome="取消")))

    def test_full_field_horse_outside_current_top5_cannot_change_gap(self) -> None:
        self.assertEqual(pre_result_current_top5_gaps(payload(outside_score=99.0)), pre_result_current_top5_gaps(payload(outside_score=1000.0)))

    def test_no_result_input_is_required_for_feature_computation(self) -> None:
        self.assertEqual(pre_result_current_top5_gaps(payload())["2"], -2.0)

    def test_invalid_current_top5_adjusted_score_fails_closed(self) -> None:
        source = payload(); source["ranked_results"][1]["adjusted_score"] = None
        with self.assertRaisesRegex(Stop, "CURRENT_TOP5_ADJUSTED_SCORE_INVALID"):
            pre_result_current_top5_gaps(source)

    def test_known_sapporo10_and_sapporo9_corrections_reproduce(self) -> None:
        sapporo10 = {"ranked_results": [
            {"horse_number": 1, "rank": 1, "adjusted_score": 0.0},
            {"horse_number": 3, "rank": 2, "adjusted_score": 19.0},
            {"horse_number": 7, "rank": 3, "adjusted_score": 7.0},
            {"horse_number": 11, "rank": 4, "adjusted_score": 6.3},
            {"horse_number": 9, "rank": 5, "adjusted_score": 24.3},
        ]}
        sapporo9 = {"ranked_results": [
            {"horse_number": 1, "rank": 1, "adjusted_score": 25.3},
            {"horse_number": 2, "rank": 2, "adjusted_score": 29.1},
            {"horse_number": 4, "rank": 3, "adjusted_score": 0.0},
            {"horse_number": 8, "rank": 4, "adjusted_score": 37.9},
            {"horse_number": 9, "rank": 5, "adjusted_score": 42.4},
        ]}
        for horse, expected in {"1": -24.3, "3": -5.3, "7": -17.3, "11": -18.0}.items():
            self.assertAlmostEqual(pre_result_current_top5_gaps(sapporo10)[horse], expected)
        for horse, expected in {"1": -17.1, "2": -13.3, "4": -42.4, "8": -4.5}.items():
            self.assertAlmostEqual(pre_result_current_top5_gaps(sapporo9)[horse], expected)

    def test_non_gap_dataset_change_fails_closed(self) -> None:
        before = [{"row_id": "r1", "adjusted_score_gap_to_top": "-2.0", "actual_top3": "0"}]
        gap_only = [{"row_id": "r1", "adjusted_score_gap_to_top": "-3.0", "actual_top3": "0"}]
        assert_only_gap_changes(before, gap_only, list(before[0]))
        outcome_changed = [{"row_id": "r1", "adjusted_score_gap_to_top": "-3.0", "actual_top3": "1"}]
        with self.assertRaisesRegex(Stop, "NON_GAP_DATASET_VALUE_CHANGED"):
            assert_only_gap_changes(before, outcome_changed, list(before[0]))


if __name__ == "__main__":
    unittest.main()
