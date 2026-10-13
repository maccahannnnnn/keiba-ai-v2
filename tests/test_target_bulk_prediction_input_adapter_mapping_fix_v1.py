import csv
import unittest
from pathlib import Path

from analyzer.schemas import PastRace
from evaluation.target_trial_adapter import TargetTrialAdapter  # noqa: F401 - stabilize package imports
from importer.target_history_importer import TargetHistoryImporter
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import history_from_past_races


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "prediction_input"


class TargetBulkPredictionInputAdapterMappingFixV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = TargetBulkPredictionInputAdapterV1()
        with (RAW / "DS260808.CSV").open(encoding="cp932", newline="") as handle:
            cls.rows = list(csv.reader(handle))

    def test_past_race_keyword_backward_compatibility(self):
        race = PastRace(
            race_date=self.adapter._ds_datetime(self.rows[0]), race_id="race_test",
            horse_name="test", jockey="test", distance=1200, track_condition="良",
            field_size=16, class_level="test", popularity=1, finish_position=1,
            corner_positions="1-1-1-1", running_style="", pace="", body_weight=480,
            body_weight_diff=0, sire="test", dam_sire="test",
        )
        self.assertIsNone(race.surface)
        self.assertIsNone(race.margin)
        self.assertIsNone(race.last_3f)
        self.assertIsNone(race.pci)
        self.assertIsNone(race.rpci)

    def test_ds_mapping_and_history_bridge(self):
        row = next(row for row in self.rows if row[48] and row[49] and row[26] not in {"", "----"})
        race = self.adapter._past_races([row])[0]
        self.assertEqual(race.surface, row[12])
        self.assertEqual(race.margin, float(row[26]))
        self.assertEqual(race.last_3f, float(row[35]))
        self.assertEqual(race.rpci, float(row[48]))
        self.assertEqual(race.pci, float(row[49]))
        run = history_from_past_races(race.horse_name, [race]).runs[0]
        self.assertEqual(run.surface, race.surface)
        self.assertEqual(run.margin, race.margin)
        self.assertEqual(run.last_3f, race.last_3f)
        self.assertEqual(run.rpci, race.rpci)
        self.assertEqual(run.pci, race.pci)

    def test_missing_numeric_values_remain_none(self):
        self.assertIsNone(self.adapter._optional_float(""))
        self.assertIsNone(self.adapter._optional_float("----"))

    def test_twenty_real_rows_match_existing_history_semantics(self):
        race_ids = []
        for date in ("20260808", "20260809"):
            manifest = ROOT / "reports" / "pre_race" / date / f"pre_race_{date}_execution_manifest.json"
            import json
            race_ids.extend(json.loads(manifest.read_text(encoding="utf-8"))["race_ids"])
        existing = {}
        importer = TargetHistoryImporter()
        for race_id in race_ids:
            histories = importer.load(ROOT / "data" / "analysis" / f"{race_id}_horses.csv")
            for name, history in histories.items():
                for run in history.runs:
                    key = (name.replace(" ", "").replace("　", ""), run.race_date, run.racecourse)
                    existing.setdefault(key, run)
        checked = 0
        seen_horses = set()
        for row in self.rows:
            name = self.adapter._clean_name(row[16])
            key = (name, self.adapter._ds_datetime(row).strftime("%Y/%m/%d"), row[4])
            run = existing.get(key)
            if (run is None or name in seen_horses or not self.adapter._text(row[12])
                    or not self.adapter._text(row[26]) or not self.adapter._text(row[35])):
                continue
            self.assertEqual(self.adapter._text(row[12]), run.surface)
            self.assertEqual(self.adapter._text(row[26]), run.margin)
            self.assertEqual(self.adapter._text(row[35]), run.last_3f)
            seen_horses.add(name)
            checked += 1
            if checked == 20:
                break
        self.assertEqual(checked, 20)


if __name__ == "__main__":
    unittest.main()
