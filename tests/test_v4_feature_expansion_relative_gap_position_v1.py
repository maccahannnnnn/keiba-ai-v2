import unittest

from review.v4_feature_expansion_relative_gap_position_feature_v1 import (
    RelativeGapFeatureError,
    adjusted_score_gap_to_top,
)


class RelativeGapFeatureTests(unittest.TestCase):
    def test_top_and_non_top(self):
        rows = [{"row_id": "a", "race_id": "r", "adjusted_score": 82}, {"row_id": "b", "race_id": "r", "adjusted_score": 79}]
        self.assertEqual(adjusted_score_gap_to_top(rows), {"a": 0.0, "b": -3.0})

    def test_tied_top_is_zero_for_each_horse(self):
        rows = [{"row_id": "a", "race_id": "r", "adjusted_score": 82}, {"row_id": "b", "race_id": "r", "adjusted_score": 82}]
        self.assertEqual(adjusted_score_gap_to_top(rows), {"a": 0.0, "b": 0.0})

    def test_races_are_independent_and_input_order_is_irrelevant(self):
        rows = [{"row_id": "b", "race_id": "r2", "adjusted_score": 4}, {"row_id": "a", "race_id": "r1", "adjusted_score": 10}, {"row_id": "c", "race_id": "r2", "adjusted_score": 7}, {"row_id": "d", "race_id": "r1", "adjusted_score": 8}]
        expected = {"a": 0.0, "d": -2.0, "b": -3.0, "c": 0.0}
        self.assertEqual(adjusted_score_gap_to_top(rows), expected)
        self.assertEqual(adjusted_score_gap_to_top(list(reversed(rows))), expected)

    def test_missing_score_fails_closed(self):
        with self.assertRaises(RelativeGapFeatureError):
            adjusted_score_gap_to_top([{"row_id": "a", "race_id": "r", "adjusted_score": ""}])

    def test_duplicate_row_id_fails_closed(self):
        with self.assertRaises(RelativeGapFeatureError):
            adjusted_score_gap_to_top([{"row_id": "a", "race_id": "r", "adjusted_score": 1}, {"row_id": "a", "race_id": "r", "adjusted_score": 2}])


if __name__ == "__main__":
    unittest.main()
