import hashlib
import json
import csv
import unittest
from pathlib import Path

from analyzer.schemas import PastRace, TodayEntry
from review.target_bulk_prediction_input_adapter_v1 import (
    COURSE_CODES,
    PredictionInputValidationError,
    TargetBulkPredictionInputAdapterV1,
)


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "prediction_input"


class TargetBulkPredictionInputAdapterV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = TargetBulkPredictionInputAdapterV1()
        cls.paths = [RAW / f"{kind}{date}.CSV" for date in ("260808", "260809") for kind in ("DG", "DE", "DS")]
        cls.before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in cls.paths}
        cls.bundles = {
            date: cls.adapter.load(RAW / f"DG{date}.CSV", RAW / f"DE{date}.CSV", RAW / f"DS{date}.CSV")
            for date in ("260808", "260809")
        }

    def test_01_dg_read_and_schema(self):
        self.assertEqual(self.bundles["260808"].sources["DG"].width, 11)
        self.assertEqual(self.bundles["260809"].sources["DG"].row_count, 18)

    def test_02_de_read_and_schema(self):
        self.assertEqual(self.bundles["260808"].sources["DE"].width, 33)
        self.assertEqual(sum(x.preflight["horse_count"] for x in self.bundles.values()), 447)

    def test_03_ds_read_and_schema(self):
        self.assertEqual(self.bundles["260809"].sources["DS"].width, 50)
        self.assertEqual(sum(x.preflight["ds_row_count"] for x in self.bundles.values()), 6118)

    def test_04_race_id_generation(self):
        self.assertIn("race_20260808_chuukyou_6R", self.bundles["260808"].races)

    def test_05_dg_de_race_match(self):
        self.assertTrue(all(x.preflight["dg_de_race_mismatch_count"] == 0 for x in self.bundles.values()))

    def test_06_dg_de_headcount_match(self):
        self.assertTrue(all(x.preflight["dg_de_headcount_mismatch_count"] == 0 for x in self.bundles.values()))

    def test_07_de_column_19_unique(self):
        self.assertTrue(all(x.preflight["de_column_19_collision_count"] == 0 for x in self.bundles.values()))

    def test_08_de_column_19_collision_fail_closed(self):
        with (RAW / "DE260808.CSV").open(encoding="cp932", newline="") as handle:
            rows = list(csv.reader(handle))
        rows[1][18] = rows[0][18]
        with self.assertRaisesRegex(PredictionInputValidationError, "DE_IDENTIFIER_COLLISION"):
            self.adapter._validate_de(rows, "20260808")

    def test_09_de_column_33_structure(self):
        self.assertEqual(sum(x.preflight["de_column_33_structural_mismatch_count"] for x in self.bundles.values()), 0)

    def test_10_de_ds_match(self):
        self.assertEqual(sum(x.preflight["de_ds_unmatched_count"] for x in self.bundles.values()), 0)

    def test_11_ambiguous_name_fail_closed(self):
        with (RAW / "DE260808.CSV").open(encoding="cp932", newline="") as handle:
            rows = list(csv.reader(handle))
        rows[1][7] = rows[0][7]
        with self.assertRaisesRegex(PredictionInputValidationError, "DE_DS_AMBIGUOUS_HORSE"):
            self.adapter._validate_de_ds(rows, {})

    def test_12_today_entry_generated(self):
        entry = next(iter(self.bundles["260808"].races.values())).today_entries[0]
        self.assertIsInstance(entry, TodayEntry)

    def test_13_past_race_generated(self):
        race = self.bundles["260808"].races["race_20260808_chuukyou_6R"]
        self.assertIsInstance(race.past_races[0], PastRace)

    def test_14_max_five_runs(self):
        for bundle in self.bundles.values():
            for race in bundle.races.values():
                counts = {}
                for run in race.past_races:
                    counts[run.horse_name] = counts.get(run.horse_name, 0) + 1
                self.assertLessEqual(max(counts.values(), default=0), 5)

    def test_15_missing_fields_not_inferred(self):
        entry = self.bundles["260808"].races["race_20260808_chuukyou_6R"].today_entries[0]
        self.assertEqual((entry.status, entry.track_condition, entry.body_weight, entry.running_style), ("", "", 0, ""))

    def test_16_raw_sha_unchanged(self):
        after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.paths}
        self.assertEqual(self.before, after)

    def test_17_production_modules_do_not_import_shadow_adapter(self):
        shadow_name = "target_bulk_prediction_input_adapter_v1"
        for rel in ("main.py", "evaluation/target_trial_adapter.py", "analyzer/keiba_analyzer.py"):
            self.assertNotIn(shadow_name, (ROOT / rel).read_text(encoding="utf-8"))

    def test_18_old_new_shadow_output_complete(self):
        path = ROOT / "reports" / "target_bulk_prediction_input_adapter_v1" / "target_bulk_prediction_input_shadow_summary_v1.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["old_input_shadow_count"], 223)
        self.assertEqual(payload["new_input_shadow_count"], 223)
        self.assertTrue(payload["raw_unchanged"])
        self.assertTrue(payload["protected_unchanged"])

    def test_19_fixed_width_rejected(self):
        with (RAW / "DG260808.CSV").open(encoding="cp932", newline="") as handle:
            rows = list(csv.reader(handle))
        rows[0].pop()
        with self.assertRaisesRegex(PredictionInputValidationError, "RAW_COLUMN_COUNT_INVALID"):
            self.adapter._read_fixed_rows_for_test(rows, "DG")

    def test_20_unexpected_header_rejected(self):
        with self.assertRaisesRegex(PredictionInputValidationError, "RAW_HEADER_UNEXPECTED"):
            self.adapter._read_fixed_rows_for_test([["年"] + [""] * 10], "DG")

    def test_21_same_day_history_rejected(self):
        with (RAW / "DS260808.CSV").open(encoding="cp932", newline="") as handle:
            rows = list(csv.reader(handle))
        rows[0][0:3] = ["26", "08", "08"]
        with self.assertRaisesRegex(PredictionInputValidationError, "DS_FUTURE_OR_SAME_DAY_RUN"):
            self.adapter._validate_ds(rows, "20260808")

    def test_22_column_33_invalid_rejected(self):
        with (RAW / "DE260808.CSV").open(encoding="cp932", newline="") as handle:
            rows = list(csv.reader(handle))
        rows[0][32] = "9999999999"
        with self.assertRaisesRegex(PredictionInputValidationError, "DE_STABLE_KEY_STRUCTURE_INVALID"):
            self.adapter._validate_de(rows, "20260808")

    @staticmethod
    def _stable_key_row(venue: str, code: str, horse_number: int = 7):
        with (RAW / "DE260808.CSV").open(encoding="cp932", newline="") as handle:
            row = next(csv.reader(handle))
        row[1] = venue
        row[2] = "1"
        row[3] = str(horse_number)
        row[7] = f"{venue}検証馬"
        row[18] = "12345678"
        row[32] = f"{code}260101{horse_number:02d}"
        return row

    def test_23_all_jra_venue_prefixes_are_accepted(self):
        expected = {
            "札幌": "01", "函館": "02", "福島": "03", "新潟": "04", "東京": "05",
            "中山": "06", "中京": "07", "京都": "08", "阪神": "09", "小倉": "10",
        }
        self.assertEqual(COURSE_CODES, expected)
        for venue, code in expected.items():
            with self.subTest(venue=venue):
                self.adapter._validate_de([self._stable_key_row(venue, code)], "20260808")

    def test_24_wrong_venue_prefix_is_rejected(self):
        row = self._stable_key_row("東京", "99")
        with self.assertRaisesRegex(PredictionInputValidationError, "DE_STABLE_KEY_STRUCTURE_INVALID"):
            self.adapter._validate_de([row], "20260808")

    def test_25_wrong_horse_number_suffix_is_rejected(self):
        row = self._stable_key_row("東京", "05")
        row[32] = "0526010108"
        with self.assertRaisesRegex(PredictionInputValidationError, "DE_STABLE_KEY_STRUCTURE_INVALID"):
            self.adapter._validate_de([row], "20260808")

    def test_26_unknown_venue_remains_fail_closed(self):
        row = self._stable_key_row("未知", "99")
        with self.assertRaisesRegex(PredictionInputValidationError, "DE_STABLE_KEY_STRUCTURE_INVALID"):
            self.adapter._validate_de([row], "20260808")

    def test_27_real_hakodate_fukushima_kokura_de_patterns_are_accepted(self):
        for date in ("260627", "260628"):
            with self.subTest(date=date):
                bundle = self.adapter.load(
                    RAW / f"DG{date}.CSV",
                    RAW / f"DE{date}.CSV",
                    RAW / f"DS{date}.CSV",
                )
                self.assertEqual(bundle.date, f"20{date}")
                self.assertEqual(bundle.preflight["de_column_33_structural_mismatch_count"], 0)


if __name__ == "__main__":
    unittest.main()
