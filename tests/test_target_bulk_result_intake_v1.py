from __future__ import annotations

import csv
import hashlib
import json
import shutil
import unittest
import uuid
from pathlib import Path

from review.target_bulk_result_intake import (
    FORMAL_SCHEMA_PATH,
    FORMAL_SCHEMA_SHA_PATH,
    TargetBulkIntakeError,
    TargetBulkResultSplitter,
    TargetBulkResultValidator,
)


def write_rows(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="cp932", newline="") as handle:
        csv.writer(handle).writerows(rows)


class TargetBulkResultIntakeV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(FORMAL_SCHEMA_PATH.read_text(encoding="utf-8"))

    def setUp(self) -> None:
        self.root = Path.cwd() / "reports" / "target_bulk_result_tmp_tests" / f"case_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.raw = self.root / "raw.csv"
        self.validator = TargetBulkResultValidator()
        self.splitter = TargetBulkResultSplitter(self.validator)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def row(self, *, race=1, horse=1, field=2, finish=1, abnormal="0") -> list[str]:
        values = {
            "年": "26", "月": "08", "日": "15", "回次": "1", "場所": "札幌", "日次": "1",
            "レース番号": str(race), "レース名": "Sample", "クラス名": "未勝利", "略レース名": "未勝利",
            "クラスコード": "7", "天候": "晴", "芝・ダ": "芝", "トラックコード": "1", "距離": "1200",
            "馬場状態": "良", "馬名": f"Horse{horse}", "性別": "牡", "年齢": "3", "騎手": "騎手A",
            "斤量": "55.0", "頭数": str(field), "馬番": str(horse), "確定着順": str(finish), "入線着順": str(finish),
            "異常コード": abnormal, "着差タイム": "0.0", "人気": "1", "走破タイム(秒)": "70.0",
            "タイムS": "1.10.0", "補正タイム": "", "通過順1角": "", "通過順2角": "", "通過順3角": "1",
            "通過順4角": "1", "上がり3Fタイム": "34.0", "Ave-3F": "35.00", "馬体重": "480", "増減": "+2",
            "調教師": "調教師A", "所属": "栗", "賞金": "100", "騎手コード": "01001", "調教師コード": "01101",
            "父馬名": "Sire", "母馬名": "Dam", "母の父馬名": "DamSire", "毛色": "鹿", "RPCI": "50.0", "PCI": "51.0",
        }
        return [values[column] for column in self.schema["ordered_columns"]]

    def valid_rows(self) -> list[list[str]]:
        return [self.row(horse=1, finish=1), self.row(horse=2, finish=2)]

    def assert_reason(self, expected: str, callback) -> None:
        with self.assertRaises(TargetBulkIntakeError) as caught:
            callback()
        self.assertEqual(caught.exception.reason_code, expected)

    def test_valid_50_column_csv_passes(self):
        write_rows(self.raw, self.valid_rows())
        result = self.validator.validate(self.raw)
        self.assertEqual((result["row_count"], result["race_count"], result["column_count"]), (2, 1, 50))

    def test_49_columns_fail_closed_without_output(self):
        write_rows(self.raw, [self.row()[:-1]])
        out = self.root / "split"
        self.assert_reason("COLUMN_COUNT_MISMATCH", lambda: self.splitter.stage(self.raw, out))
        self.assertFalse(out.exists())

    def test_51_columns_fail_closed_without_output(self):
        write_rows(self.raw, [self.row() + ["extra"]])
        out = self.root / "split"
        self.assert_reason("COLUMN_COUNT_MISMATCH", lambda: self.splitter.stage(self.raw, out))
        self.assertFalse(out.exists())

    def test_wrong_target_format_fails_sentinel(self):
        row = self.row()
        row[29] = "35.00"
        row[36] = "1.10.0"
        write_rows(self.raw, [row])
        self.assert_reason("SENTINEL_VALIDATION_FAILED", lambda: self.validator.validate(self.raw))

    def test_schema_sha_mismatch_fails(self):
        schema = self.root / "schema.json"
        sha = self.root / "schema.sha256"
        schema.write_bytes(FORMAL_SCHEMA_PATH.read_bytes())
        sha.write_text("0" * 64 + "  schema.json\n", encoding="ascii")
        write_rows(self.raw, self.valid_rows())
        validator = TargetBulkResultValidator(schema, sha)
        self.assert_reason("SCHEMA_SHA256_MISMATCH", lambda: validator.validate(self.raw))

    def test_schema_version_mismatch_fails(self):
        write_rows(self.raw, self.valid_rows())
        self.assert_reason("SCHEMA_VERSION_MISMATCH", lambda: self.validator.validate(self.raw, expected_schema_version="wrong"))

    def test_invalid_racecourse_fails(self):
        row = self.row()
        row[4] = "Unknown"
        write_rows(self.raw, [row])
        self.assert_reason("SENTINEL_VALIDATION_FAILED", lambda: self.validator.validate(self.raw))

    def test_race_number_out_of_range_fails(self):
        write_rows(self.raw, [self.row(race=13)])
        self.assert_reason("SENTINEL_VALIDATION_FAILED", lambda: self.validator.validate(self.raw))

    def test_duplicate_horse_number_fails(self):
        write_rows(self.raw, [self.row(horse=1), self.row(horse=1)])
        self.assert_reason("DUPLICATE_HORSE_NUMBER", lambda: self.validator.validate(self.raw))

    def test_race_grouping_inconsistent_fails(self):
        rows = self.valid_rows()
        rows[1][12] = "ダ"
        write_rows(self.raw, rows)
        self.assert_reason("RACE_GROUPING_INCONSISTENT", lambda: self.validator.validate(self.raw))

    def test_race_key_reappearance_fails(self):
        write_rows(self.raw, [self.row(race=1, horse=1, field=2), self.row(race=2, horse=1, field=1), self.row(race=1, horse=2, field=2)])
        self.assert_reason("RACE_KEY_REAPPEARED", lambda: self.validator.validate(self.raw))

    def test_existing_identical_result_is_reused(self):
        write_rows(self.raw, self.valid_rows())
        staged = self.splitter.stage(self.raw, self.root / "split")
        official = self.root / "official"
        official.mkdir()
        for item in staged["split_files"]:
            shutil.copy2(item["path"], official / Path(item["path"]).name)
        result = self.splitter.reconcile(staged, official)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(all(row["reconciliation_status"] == "REUSE" for row in result["files"]))

    def test_existing_different_result_stops(self):
        write_rows(self.raw, self.valid_rows())
        staged = self.splitter.stage(self.raw, self.root / "split")
        official = self.root / "official"
        official.mkdir()
        target = official / Path(staged["split_files"][0]["path"]).name
        target.write_text("different\n", encoding="utf-8")
        result = self.splitter.reconcile(staged, official)
        self.assertEqual((result["status"], result["conflict_count"]), ("STOP", 1))

    def test_abnormal_raw_result_is_preserved(self):
        write_rows(self.raw, [self.row(horse=1, field=1, finish=0, abnormal="3")])
        staged = self.splitter.stage(self.raw, self.root / "split")
        horse = next(Path(item["path"]) for item in staged["split_files"] if item["role"] == "HORSE_RESULT")
        with horse.open(encoding="cp932", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual((row["確定着順"], row["異常コード"]), ("0", "3"))

    def test_observation_kpi_and_baseline_excluded(self):
        write_rows(self.raw, self.valid_rows())
        staged = self.splitter.stage(self.raw, self.root / "split")
        manifest = self.splitter.build_observation_manifests(staged)[0]
        self.assertEqual((manifest["kpi_eligible"], manifest["baseline_membership"], manifest["production_evidence"]), ("NO", "EXCLUDED", "NO"))

    def test_prediction_artifact_is_zero_delta(self):
        write_rows(self.raw, self.valid_rows())
        prediction = self.root / "prediction.json"
        prediction.write_text(json.dumps({"decision": "BUY", "count": 1}), encoding="utf-8")
        before = hashlib.sha256(prediction.read_bytes()).hexdigest()
        self.splitter.stage(self.raw, self.root / "split")
        self.assertEqual(before, hashlib.sha256(prediction.read_bytes()).hexdigest())

    def test_buy_artifact_is_zero_delta(self):
        self._assert_unrelated_artifact_unchanged("buy.json", {"buy_count": 1})

    def test_learning_artifact_is_zero_delta(self):
        self._assert_unrelated_artifact_unchanged("learning.json", {"candidates": []})

    def test_knowledge_artifact_is_zero_delta(self):
        self._assert_unrelated_artifact_unchanged("knowledge.json", {"courses": []})

    def test_target_result_adapter_is_used_for_every_split_race(self):
        write_rows(self.raw, self.valid_rows())
        staged = self.splitter.stage(self.raw, self.root / "split")
        self.assertEqual(staged["target_result_adapter_complete_count"], staged["race_count"])

    def test_raw_to_split_provenance(self):
        write_rows(self.raw, self.valid_rows())
        raw_before = self.raw.read_bytes()
        staged = self.splitter.stage(self.raw, self.root / "split")
        provenance = self.splitter.build_provenance(staged, imported_at="2026-08-12T00:00:00+09:00")
        self.assertEqual(provenance["source_file_sha256"], hashlib.sha256(raw_before).hexdigest())
        self.assertEqual(len(provenance["split_files"]), 2)
        self.assertEqual(raw_before, self.raw.read_bytes())

    def test_missing_race_is_incomplete(self):
        write_rows(self.raw, self.valid_rows())
        staged = self.splitter.stage(self.raw, self.root / "split")
        from review.observation_intake import ObservationManifestBuilder
        manifest = ObservationManifestBuilder(staged["staging_root"]).build(date="20260815", racecourse="sapporo", expected_race_numbers=(1, 2))
        self.assertEqual((manifest["completeness_status"], len(manifest["missing_race_list"])), ("INCOMPLETE", 1))

    def test_complete_race_set_is_complete(self):
        write_rows(self.raw, self.valid_rows())
        staged = self.splitter.stage(self.raw, self.root / "split")
        manifest = self.splitter.build_observation_manifests(staged)[0]
        self.assertEqual((manifest["completeness_status"], manifest["saved_race_count"]), ("COMPLETE", 1))

    def _assert_unrelated_artifact_unchanged(self, name: str, payload: dict) -> None:
        write_rows(self.raw, self.valid_rows())
        artifact = self.root / name
        artifact.write_text(json.dumps(payload), encoding="utf-8")
        before = hashlib.sha256(artifact.read_bytes()).hexdigest()
        self.splitter.stage(self.raw, self.root / "split")
        self.assertEqual(before, hashlib.sha256(artifact.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
