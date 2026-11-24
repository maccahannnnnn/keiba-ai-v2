from __future__ import annotations

import csv
import unittest
from pathlib import Path

from review.target_bulk_canonical_comparison import (
    BOTH_MISSING,
    BYTE_IDENTICAL,
    CANONICALLY_EQUIVALENT,
    FIELD_NOT_COMPARABLE,
    ONE_SIDE_MISSING,
    SEMANTICALLY_EQUIVALENT_MISSING_TIME,
    TRUE_CONFLICT,
    UNDETERMINED,
    compare_field,
)


ROOT = Path(__file__).resolve().parents[1]
HUMAN_CSV = ROOT / "reports/target_bulk_human_review_v1/target_bulk_human_review_cells_v1.csv"


class TargetBulkCanonicalComparisonV1Tests(unittest.TestCase):
    def test_weather_outer_whitespace_is_equivalent(self):
        self.assertEqual(compare_field("天候", " 晴 ", "晴")["comparison_status"], CANONICALLY_EQUIVALENT)

    def test_different_weather_is_conflict(self):
        self.assertEqual(compare_field("天候", "晴", "曇")["comparison_status"], TRUE_CONFLICT)

    def test_existing_surface_map_is_equivalent(self):
        self.assertEqual(compare_field("芝・ダート", "ダート", "ダ")["comparison_status"], CANONICALLY_EQUIVALENT)

    def test_unknown_surface_fails_closed(self):
        self.assertEqual(compare_field("芝・ダート", "unknown", "ダ")["comparison_status"], UNDETERMINED)

    def test_weight_integer_decimal_is_equivalent(self):
        self.assertEqual(compare_field("斤量", "53", "53.0")["comparison_status"], CANONICALLY_EQUIVALENT)

    def test_different_weight_is_conflict(self):
        self.assertEqual(compare_field("斤量", "53", "54.0")["comparison_status"], TRUE_CONFLICT)

    def test_unparseable_weight_fails_closed(self):
        self.assertEqual(compare_field("斤量", "53kg", "53.0")["comparison_status"], UNDETERMINED)

    def test_approved_allowance_triangle_is_equivalent(self):
        result = compare_field("斤量", "55▲", "55.0")
        self.assertEqual(result["comparison_status"], CANONICALLY_EQUIVALENT)
        self.assertEqual((result["parsed_existing_weight"], result["parsed_bulk_weight"], result["allowance_symbol"]), ("55", "55.0", "▲"))

    def test_approved_allowance_star_outline_is_equivalent(self):
        self.assertEqual(compare_field("斤量", "57☆", "57.0")["comparison_status"], CANONICALLY_EQUIVALENT)

    def test_approved_allowance_diamond_is_equivalent(self):
        self.assertEqual(compare_field("斤量", "54◇", "54.0")["comparison_status"], CANONICALLY_EQUIVALENT)

    def test_approved_allowance_star_filled_is_equivalent(self):
        self.assertEqual(compare_field("斤量", "52★", "52.0")["comparison_status"], CANONICALLY_EQUIVALENT)

    def test_allowance_numeric_mismatch_is_not_equivalent(self):
        self.assertEqual(compare_field("斤量", "55▲", "54.0")["comparison_status"], TRUE_CONFLICT)

    def test_unknown_allowance_symbol_is_undetermined(self):
        result = compare_field("斤量", "55?", "55.0")
        self.assertEqual((result["comparison_status"], result["allowance_symbol"]), (UNDETERMINED, "?"))

    def test_non_numeric_allowance_value_is_undetermined(self):
        self.assertEqual(compare_field("斤量", "--▲", "55.0")["comparison_status"], UNDETERMINED)

    def test_numeric_weight_still_uses_decimal_fallback(self):
        self.assertEqual(compare_field("斤量", "55", "55.0")["comparison_status"], CANONICALLY_EQUIVALENT)

    def test_one_side_missing_preserves_direction(self):
        result = compare_field("PCI", "", "50.0")
        self.assertEqual((result["comparison_status"], result["missing_side"]), (ONE_SIDE_MISSING, "EXISTING"))

    def test_both_missing_is_not_value_match(self):
        self.assertEqual(compare_field("PCI", "", "")["comparison_status"], BOTH_MISSING)

    def test_margin_is_not_comparable(self):
        self.assertEqual(compare_field("着差", "クビ", "0.1")["comparison_status"], FIELD_NOT_COMPARABLE)

    def test_win_odds_is_not_comparable(self):
        self.assertEqual(compare_field("単勝オッズ", "2.0", "")["comparison_status"], FIELD_NOT_COMPARABLE)

    def test_normal_time_difference_is_conflict(self):
        self.assertEqual(compare_field("タイム", "1.10.0", "1.10.1", finish=1, abnormal_code=0)["comparison_status"], TRUE_CONFLICT)

    def test_approved_phase_ab_sentinel_pair_is_equivalent(self):
        self.assertEqual(
            compare_field("タイム", "------", "0.00.0", finish=0, abnormal_code=3)["comparison_status"],
            SEMANTICALLY_EQUIVALENT_MISSING_TIME,
        )

    def test_sentinel_vs_real_time_is_conflict(self):
        self.assertEqual(compare_field("タイム", "------", "1.10.0", finish=0, abnormal_code=3)["comparison_status"], TRUE_CONFLICT)

    def test_literal_match_is_byte_identical(self):
        self.assertEqual(compare_field("馬名", "Horse", "Horse")["comparison_status"], BYTE_IDENTICAL)

    def test_human_confirmed_five_cells_remain_bulk_correct(self):
        with HUMAN_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["human_review_status"] == "VERIFIED" for row in rows))
        self.assertTrue(all(row["human_decision"] == "BULK_RESULT_CORRECT" for row in rows))
        self.assertTrue(all(row["confirmed_value"] == row["bulk_value"] != row["existing_value"] for row in rows))


if __name__ == "__main__":
    unittest.main()
