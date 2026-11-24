from __future__ import annotations

import csv
import json
import shutil
import unittest
import uuid
from pathlib import Path

from engine.result_importer import ResultImporter
from review.observation_intake import ObservationManifestBuilder
from review.observation_manifest_validator import ObservationManifestValidator


RACE_HEADER = [
    "年",
    "月",
    "日",
    "場所",
    "R",
    "略レース名",
    "芝・ダート",
    "距離",
    "天候",
    "馬場状態",
    "頭数",
]
HORSE_HEADER = [
    "確定着順",
    "異常コード",
    "枠番",
    "馬番",
    "馬名",
    "タイム",
    "通過1",
    "通過2",
    "通過3",
    "通過4",
    "Ave-3F",
    "上り3F",
    "体重",
    "増減",
]


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="cp932", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


class FullRaceObservationIntakeV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "reports" / "full_race_observation_tmp_tests" / f"case_{uuid.uuid4().hex}"
        self.results = self.root / "data" / "results"
        self.results.mkdir(parents=True)
        self.builder = ObservationManifestBuilder(result_root=self.results)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def add_race(self, race_number: int, horse_rows: list[list[object]] | None = None) -> tuple[Path, Path]:
        suffix = f"20990101_tokyo_{race_number}R"
        race = self.results / f"race_{suffix}_result.csv"
        horse = self.results / f"horse_{suffix}_result.csv"
        write_csv(race, RACE_HEADER, [[2099, "01", "01", "東京", race_number, "sample", "芝", 1600, "晴", "良", 2]])
        write_csv(
            horse,
            HORSE_HEADER,
            horse_rows
            or [
                [1, 0, 1, 1, "HorseA", "1.34.0", 1, 1, 1, 1, "36.0", "34.0", 480, 0],
                [2, 0, 2, 2, "HorseB", "1.34.1", 2, 2, 2, 2, "36.1", "34.1", 470, 2],
            ],
        )
        return race, horse

    def build(self, expected=(1,), prediction_linked=()):
        return self.builder.build(
            date="20990101",
            racecourse="tokyo",
            expected_race_numbers=expected,
            prediction_linked_race_ids=prediction_linked,
            generated_at="2099-01-01T12:00:00+00:00",
        )

    def test_result_importer_loads_without_prediction_id(self):
        _, horse = self.add_race(1)
        result = ResultImporter().import_result(horse, prediction_id=None)
        self.assertTrue(result["result_loaded"])
        self.assertIsNone(result["prediction_id"])
        self.assertEqual(len(result["horse_results"]), 2)

    def test_complete_manifest_references_existing_csv_without_copying(self):
        race, horse = self.add_race(1)
        before = {race: race.read_bytes(), horse: horse.read_bytes()}
        manifest = self.build()
        self.assertEqual(manifest["completeness_status"], "COMPLETE")
        self.assertEqual(manifest["saved_race_count"], 1)
        self.assertEqual(manifest["saved_horse_count"], 2)
        self.assertEqual(len(manifest["files"]), 2)
        self.assertEqual(before, {race: race.read_bytes(), horse: horse.read_bytes()})

    def test_prediction_and_observation_counts_are_separated(self):
        self.add_race(1)
        self.add_race(2)
        linked = "race_20990101_tokyo_1R"
        manifest = self.build(expected=(1, 2), prediction_linked=(linked,))
        self.assertEqual(manifest["prediction_linked_race_count"], 1)
        self.assertEqual(manifest["observation_only_race_count"], 1)
        rows = {row["race_id"]: row for row in manifest["races"]}
        self.assertTrue(rows[linked]["prediction_linked"])
        self.assertFalse(rows[linked]["observation_only"])
        self.assertFalse(rows["race_20990101_tokyo_2R"]["prediction_linked"])
        self.assertTrue(rows["race_20990101_tokyo_2R"]["observation_only"])

    def test_observation_metadata_is_excluded_from_kpi_and_baseline(self):
        self.add_race(1)
        manifest = self.build()
        self.assertEqual(manifest["population_type"], "OBSERVATION_ONLY")
        self.assertFalse(manifest["prediction_linked"])
        self.assertEqual(manifest["baseline_membership"], "EXCLUDED")
        self.assertEqual(manifest["production_evidence"], "NO")
        self.assertEqual(manifest["kpi_eligible"], "NO")

    def test_target_frontier_source_is_allowed_without_schema_change(self):
        self.add_race(1)
        manifest = self.builder.build(
            date="20990101", racecourse="tokyo", expected_race_numbers=(1,),
            generated_at="2099-01-01T12:00:00+00:00", source="TARGET_FRONTIER_JV",
        )
        self.assertEqual(manifest["source"], "TARGET_FRONTIER_JV")
        self.assertEqual(ObservationManifestValidator().validate(manifest)["status"], "PASS")

    def test_unknown_observation_source_is_rejected(self):
        self.add_race(1)
        manifest = self.build()
        manifest["source"] = "UNKNOWN"
        result = ObservationManifestValidator().validate(manifest)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("INVALID_OBSERVATION_SOURCE", result["reason_codes"])

    def test_observation_manifest_contains_no_prediction_outputs(self):
        self.add_race(1)
        manifest = self.build()
        serialized = json.dumps(manifest).lower()
        for forbidden in ('"decision"', '"buy"', '"ranking"', '"pre_race"', '"review"'):
            self.assertNotIn(forbidden, serialized)

    def test_prediction_cohort_artifact_is_unchanged(self):
        self.add_race(1)
        prediction = self.root / "reports" / "prediction_cohort.json"
        prediction.parent.mkdir(parents=True, exist_ok=True)
        prediction_payload = {"decision": "BUY", "sentinel": "unchanged"}
        prediction.write_text(json.dumps(prediction_payload), encoding="utf-8")
        before = prediction.read_bytes()
        self.build()
        self.assertEqual(before, prediction.read_bytes())

    def test_missing_race_pair_is_not_complete(self):
        self.add_race(1)
        manifest = self.build(expected=(1, 2))
        self.assertEqual(manifest["completeness_status"], "INCOMPLETE")
        self.assertEqual(manifest["saved_race_count"], 1)
        self.assertEqual(manifest["missing_race_list"][0]["race_id"], "race_20990101_tokyo_2R")
        self.assertEqual(set(manifest["missing_race_list"][0]["missing_files"]), {"RACE_RESULT", "HORSE_RESULT"})

    def test_abnormal_finish_semantics_are_counted_without_rewriting(self):
        rows = [
            [0, 0, 1, 1, "HorseA", "", "", "", "", "", "", "", 480, 0],
            [2, "中止", 2, 2, "HorseB", "", "", "", "", "", "", "", 470, 0],
            [3, 0, 3, 3, "HorseC", "1.34.2", 3, 3, 3, 3, "36.2", "34.2", 460, 0],
        ]
        _, horse = self.add_race(1, rows)
        before = horse.read_bytes()
        manifest = self.build()
        self.assertEqual(manifest["abnormal_result_count"], 2)
        self.assertEqual(before, horse.read_bytes())

    def test_validator_accepts_complete_manifest_and_file_hashes(self):
        self.add_race(1)
        result = ObservationManifestValidator().validate(self.build())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["errors"], [])

    def test_validator_rejects_complete_with_missing_race(self):
        self.add_race(1)
        manifest = self.build(expected=(1, 2))
        manifest["completeness_status"] = "COMPLETE"
        result = ObservationManifestValidator().validate(manifest)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("COMPLETE_WITH_MISSING_RACE", result["reason_codes"])

    def test_validator_detects_result_file_hash_change(self):
        _, horse = self.add_race(1)
        manifest = self.build()
        horse.write_text("changed\n", encoding="utf-8")
        result = ObservationManifestValidator().validate(manifest)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("FILE_SHA256_MISMATCH", result["reason_codes"])

    def test_save_writes_only_manifest_path(self):
        race, horse = self.add_race(1)
        source_before = {race: race.read_bytes(), horse: horse.read_bytes()}
        manifest_path = self.root / "reports" / "observation_manifest.json"
        self.builder.save(self.build(), manifest_path)
        self.assertTrue(manifest_path.is_file())
        self.assertEqual(source_before, {race: race.read_bytes(), horse: horse.read_bytes()})
        self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["schema_version"], "OBSERVATION_MANIFEST_V1")


if __name__ == "__main__":
    unittest.main()
