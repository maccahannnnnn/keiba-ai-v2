from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path

from review.target_bulk_result_intake import (
    MISSING_TIME_COMPARISON_STATUS,
    compare_known_missing_time_sentinels,
)


ROOT = Path(__file__).resolve().parents[1]
HUMAN_CSV = ROOT / "reports/target_bulk_human_review_v1/target_bulk_human_review_cells_v1.csv"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TargetBulkConflictPhaseABV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with HUMAN_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
            cls.rows = list(csv.DictReader(handle))

    def test_human_review_is_five_of_five_bulk_correct(self):
        self.assertEqual(len(self.rows), 5)
        self.assertEqual({row["human_review_status"] for row in self.rows}, {"VERIFIED"})
        self.assertEqual({row["human_decision"] for row in self.rows}, {"BULK_RESULT_CORRECT"})

    def test_jra_official_provenance_is_five_of_five(self):
        self.assertTrue(all(row["verified_by"] == "HUMAN" for row in self.rows))
        self.assertTrue(all(row["source_type"] == "JRA_OFFICIAL" for row in self.rows))
        self.assertTrue(all(row["source_reference"] for row in self.rows))
        self.assertTrue(all(row["verified_at"] for row in self.rows))

    def test_confirmed_values_match_bulk_not_existing(self):
        self.assertTrue(all(row["confirmed_value"] == row["bulk_value"] for row in self.rows))
        self.assertTrue(all(row["confirmed_value"] != row["existing_value"] for row in self.rows))

    def test_existing_results_remain_at_preapproved_sha(self):
        expected = {
            "horse_20260726_sapporo_11R_result.csv": "0c6f454371249f1b3f8bf2ac1c51f74289d6cc8ff0eb1db6efe8bdc5a0ec03f0",
            "horse_20260726_sapporo_12R_result.csv": "27e482a6f01c080c4da0afde095d1918dd4d2c4e480cd21f60872e23b2a2b5a3",
            "horse_20260725_chuukyou_6R_result.csv": "85d6b10b847ad30df8d71a09e3658512672c883e2aa1c7b0b8da21fc4db19cba",
        }
        self.assertEqual({name: sha(ROOT / "data/results" / name) for name in expected}, expected)

    def test_target_raw_remains_at_frozen_sha(self):
        self.assertEqual(
            sha(ROOT / "data/raw/target/scehema_samples/テスト３.csv"),
            "9264844e79c99e2e8f06a39116b4599bf5f8722e83b4059be689041069b65336",
        )

    def test_exact_sentinel_pair_abnormal_result_is_equivalent(self):
        self.assertEqual(
            compare_known_missing_time_sentinels("タイム", "------", "0.00.0", 0, 3),
            MISSING_TIME_COMPARISON_STATUS,
        )

    def test_exact_sentinel_pair_is_symmetric(self):
        self.assertEqual(
            compare_known_missing_time_sentinels("タイム", "0.00.0", "------", "0", "4"),
            MISSING_TIME_COMPARISON_STATUS,
        )

    def test_normal_finish_does_not_equate_sentinels(self):
        self.assertEqual(compare_known_missing_time_sentinels("タイム", "------", "0.00.0", 1, 3), "CONFLICT")

    def test_normal_abnormal_code_does_not_equate_sentinels(self):
        self.assertEqual(compare_known_missing_time_sentinels("タイム", "------", "0.00.0", 0, 0), "CONFLICT")

    def test_other_abnormal_real_times_remain_conflict(self):
        self.assertEqual(compare_known_missing_time_sentinels("タイム", "60.3", "61.0", 0, 3), "CONFLICT")

    def test_missing_sentinel_vs_real_time_remains_conflict(self):
        self.assertEqual(compare_known_missing_time_sentinels("タイム", "0.00.0", "61.0", 0, 3), "CONFLICT")

    def test_other_field_remains_conflict(self):
        self.assertEqual(compare_known_missing_time_sentinels("着差", "------", "0.00.0", 0, 3), "CONFLICT")

    def test_whitespace_variant_remains_conflict(self):
        self.assertEqual(compare_known_missing_time_sentinels("タイム", " ------", "0.00.0", 0, 3), "CONFLICT")

    def test_baseline_frozen_assets_remain_at_manifest_sha(self):
        manifest = json.loads((ROOT / "reports/baseline/baseline_34_race_v1_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sha(ROOT / "reports/baseline/keibaai_baseline_4days_v1_race.csv"), manifest["hashes"]["race_baseline_sha256"])
        self.assertEqual(sha(ROOT / "reports/baseline/keibaai_baseline_4days_v1_horse.csv"), manifest["hashes"]["horse_baseline_sha256"])

    def test_baseline_kpi_buy_count_and_rate_unchanged(self):
        kpi = json.loads((ROOT / "reports/baseline/baseline_34_race_v1_kpi.json").read_text(encoding="utf-8"))
        self.assertEqual((kpi["buy_total"], kpi["valid_result_buy"], kpi["buy_top3"], kpi["official_buy_place_rate"]), (40, 39, 10, 25.64))


if __name__ == "__main__":
    unittest.main()
