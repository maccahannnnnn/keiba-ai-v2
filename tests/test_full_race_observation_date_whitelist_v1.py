from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from review import full_race_observation_operation_v1 as operation
from review.target_bulk_result_intake import (
    FORMAL_SCHEMA_PATH,
    TargetBulkIntakeError,
    TargetBulkResultSplitter,
    TargetBulkResultValidator,
    normalize_allowed_dates,
)


class FullRaceObservationDateWhitelistV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(FORMAL_SCHEMA_PATH.read_text(encoding="utf-8"))

    def setUp(self) -> None:
        self.root = Path.cwd() / "reports" / "full_race_observation_date_whitelist_tmp_tests" / f"case_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.raw = self.root / "raw.csv"
        self.official = self.root / "official"
        self.official.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        try:
            self.root.parent.rmdir()
        except OSError:
            pass

    def row(
        self,
        *,
        date_text: str = "2026-07-18",
        course: str = "札幌",
        race: int = 1,
        horse: int = 1,
        field: int = 1,
        class_name: str = "未勝利",
    ) -> list[str]:
        year, month, day = date_text.split("-")
        values = {
            "年": year[2:], "月": month, "日": day, "回次": "1", "場所": course, "日次": "1",
            "レース番号": str(race), "レース名": "Sample", "クラス名": class_name, "略レース名": class_name,
            "クラスコード": "7", "天候": "晴", "芝・ダ": "芝", "トラックコード": "1", "距離": "1200",
            "馬場状態": "良", "馬名": f"Horse{horse}", "性別": "牡", "年齢": "3", "騎手": "騎手A",
            "斤量": "55.0", "頭数": str(field), "馬番": str(horse), "確定着順": "1", "入線着順": "1",
            "異常コード": "0", "着差タイム": "0.0", "人気": "1", "走破タイム(秒)": "70.0",
            "タイムS": "1.10.0", "補正タイム": "", "通過順1角": "", "通過順2角": "", "通過順3角": "1",
            "通過順4角": "1", "上がり3Fタイム": "34.0", "Ave-3F": "35.00", "馬体重": "480", "増減": "+2",
            "調教師": "調教師A", "所属": "栗", "賞金": "100", "騎手コード": "01001", "調教師コード": "01101",
            "父馬名": "Sire", "母馬名": "Dam", "母の父馬名": "DamSire", "毛色": "鹿", "RPCI": "50.0", "PCI": "51.0",
        }
        return [values[column] for column in self.schema["ordered_columns"]]

    @staticmethod
    def write_rows(path: Path, rows: list[list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="cp932", newline="") as handle:
            csv.writer(handle).writerows(rows)

    def stage_for_official(self, rows: list[list[str]]) -> dict:
        source = self.root / "official_source.csv"
        self.write_rows(source, rows)
        staged = TargetBulkResultSplitter().stage(source, self.root / "official_stage")
        for item in staged["split_files"]:
            shutil.copy2(item["path"], self.official / Path(item["path"]).name)
        return staged

    def test_default_unspecified_path_preserves_legacy_shape(self):
        self.write_rows(self.raw, [self.row(), self.row(date_text="2026-07-19", race=2)])
        staged = TargetBulkResultSplitter().stage(self.raw, self.root / "stage")
        self.assertEqual(staged["race_count"], 2)
        self.assertNotIn("date_filter_audit", staged)
        self.assertNotIn("raw_row_count", staged)
        provenance = TargetBulkResultSplitter().build_provenance(staged, imported_at="fixed")
        self.assertEqual(
            set(provenance),
            {
                "provenance_version", "source_type", "raw_source_path", "source_file_sha256",
                "imported_at", "schema_name", "schema_version", "schema_sha256",
                "selected_column_count", "row_count", "split_count", "split_files",
                "formal_observation_registered",
            },
        )

    def test_unfiltered_execute_summary_keeps_legacy_keys(self):
        self.write_rows(self.raw, [self.row()])
        result = operation.run(self.raw, self.root / "out", self.official)
        self.assertEqual(
            set(result),
            {
                "status", "row_count", "race_count", "new_result_placed_file_count",
                "reuse_file_count", "conflict_count", "population_count",
                "complete_population_count", "incomplete_population_count",
                "populations", "formal_observation_registered",
            },
        )
        self.assertNotIn("date_filter_applied", result)

    def test_single_and_multiple_allowed_dates(self):
        rows = [self.row(), self.row(date_text="2026-07-19", race=2), self.row(date_text="2026-07-20", race=3)]
        self.write_rows(self.raw, rows)
        splitter = TargetBulkResultSplitter()
        single = splitter.stage(self.raw, self.root / "single", allowed_dates=["2026-07-18"])
        multiple = splitter.stage(self.raw, self.root / "multiple", allowed_dates=["2026-07-18", "2026-07-19"])
        self.assertEqual(single["race_ids"], ["race_20260718_sapporo_1R"])
        self.assertEqual(multiple["race_ids"], ["race_20260718_sapporo_1R", "race_20260719_sapporo_2R"])
        self.assertEqual(multiple["date_filter_audit"]["excluded_dates"], ["2026-07-20"])

    def test_repeatable_cli_argument(self):
        argv = [
            "operation", "--raw", "one.csv", "--raw", "two.csv", "--output-root", "out",
            "--allowed-date", "2026-07-18", "--allowed-date", "2026-07-19",
        ]
        with patch.object(sys, "argv", argv), patch.object(operation, "run", return_value={"status": "PASS"}) as called:
            self.assertEqual(operation.main(), 0)
        self.assertEqual(called.call_args.args[0], ["one.csv", "two.csv"])
        self.assertEqual(called.call_args.kwargs["allowed_dates"], ["2026-07-18", "2026-07-19"])
        self.assertFalse(called.call_args.kwargs["execute"])

    def test_strict_iso_dates_and_invalid_forms(self):
        self.assertEqual(normalize_allowed_dates(["2026-07-18"])["allowed_dates"], ["2026-07-18"])
        for invalid in ("20260718", "2026/07/18", "7/18", "2026-02-30", ""):
            with self.subTest(invalid=invalid), self.assertRaises(TargetBulkIntakeError) as caught:
                normalize_allowed_dates([invalid])
            self.assertEqual(caught.exception.reason_code, "INVALID_ALLOWED_DATE_FORMAT")
        argv = ["operation", "--raw", "one.csv", "--output-root", "out", "--allowed-date", "20260718"]
        with patch.object(sys, "argv", argv), patch.object(operation, "run") as called:
            with self.assertRaises(SystemExit) as caught:
                operation.main()
        self.assertEqual(caught.exception.code, 2)
        called.assert_not_called()

    def test_duplicate_dates_are_normalized_and_audited(self):
        self.write_rows(self.raw, [self.row()])
        staged = TargetBulkResultSplitter().stage(
            self.raw, self.root / "stage", allowed_dates=["2026-07-18", "2026-07-18"]
        )
        audit = staged["date_filter_audit"]
        self.assertEqual(audit["allowed_dates"], ["2026-07-18"])
        self.assertEqual(audit["allowed_dates_original_arguments"], ["2026-07-18", "2026-07-18"])
        self.assertTrue(audit["duplicate_allowed_dates_detected"])

    def test_missing_and_partially_missing_allowed_dates_stop_without_stage(self):
        self.write_rows(self.raw, [self.row()])
        for allowed in (["2026-07-19"], ["2026-07-18", "2026-07-19"]):
            stage = self.root / ("stage_" + str(len(allowed)))
            with self.subTest(allowed=allowed), self.assertRaises(TargetBulkIntakeError) as caught:
                TargetBulkResultSplitter().stage(self.raw, stage, allowed_dates=allowed)
            self.assertEqual(caught.exception.reason_code, "ALLOWED_DATE_NOT_FOUND")
            self.assertFalse(stage.exists())
            self.assertEqual(caught.exception.details["detected_input_dates"], ["2026-07-18"])

    def test_excluded_dates_never_reach_stage_reconcile_write_or_population(self):
        self.write_rows(self.raw, [self.row(), self.row(date_text="2026-07-19", race=2)])
        before = hashlib.sha256(json.dumps(sorted(p.name for p in self.official.iterdir())).encode()).hexdigest()
        out = self.root / "out"
        result = operation.run(self.raw, out, self.official, allowed_dates=["2026-07-18"], execute=False)
        after = hashlib.sha256(json.dumps(sorted(p.name for p in self.official.iterdir())).encode()).hexdigest()
        reconciliation = json.loads((out / "reconciliation_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(result["new_result_placed_file_count"], 0)
        self.assertEqual(result["population_count"], 0)
        self.assertFalse(result["formal_observation_registered"])
        self.assertEqual(before, after)
        self.assertTrue(all("20260718" in row["race_id"] for row in reconciliation["files"]))
        self.assertEqual(result["excluded_race_ids"], ["race_20260719_sapporo_2R"])
        self.assertFalse((out / "stage").exists())

    def test_allowed_reuse_new_and_conflict_behave_as_before(self):
        allowed_row = self.row()
        self.stage_for_official([allowed_row])
        self.write_rows(self.raw, [allowed_row, self.row(race=2)])
        reuse_new = operation.run(
            self.raw, self.root / "reuse_new", self.official,
            allowed_dates=["2026-07-18"], execute=False,
        )
        self.assertEqual((reuse_new["reuse_file_count"], reuse_new["planned_new_file_count"]), (2, 2))

        conflict_file = self.official / "race_20260718_sapporo_1R_result.csv"
        original = conflict_file.read_bytes()
        conflict_file.write_bytes(b"different\n")
        conflict = operation.run(
            self.raw, self.root / "conflict", self.official,
            allowed_dates=["2026-07-18"], execute=True,
        )
        self.assertEqual(conflict["status"], "CONFLICT_STOP")
        self.assertEqual(conflict["new_result_placed_file_count"], 0)
        self.assertEqual(conflict_file.read_bytes(), b"different\n")
        self.assertFalse((self.official / "race_20260718_sapporo_2R_result.csv").exists())
        self.assertNotEqual(original, conflict_file.read_bytes())

    def test_execute_places_only_allowed_new_files_exclusively(self):
        self.write_rows(self.raw, [self.row(), self.row(date_text="2026-07-19", race=2)])
        result = operation.run(
            self.raw, self.root / "out", self.official,
            allowed_dates=["2026-07-18"], execute=True,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["new_result_placed_file_count"], 2)
        self.assertTrue((self.official / "race_20260718_sapporo_1R_result.csv").exists())
        self.assertTrue((self.official / "horse_20260718_sapporo_1R_result.csv").exists())
        self.assertFalse(any("20260719" in path.name for path in self.official.iterdir()))
        manifests = list((self.root / "out" / "manifests").glob("*.json"))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        self.assertTrue(manifest["date_filter_applied"])
        self.assertNotIn("2026-07-19", manifest["included_dates"])

    def test_newcomer_and_jump_are_not_filtered_inside_allowed_date(self):
        self.write_rows(
            self.raw,
            [self.row(class_name="新馬"), self.row(race=2, class_name="障害未勝利")],
        )
        staged = TargetBulkResultSplitter().stage(
            self.raw, self.root / "stage", allowed_dates=["2026-07-18"]
        )
        self.assertEqual(staged["race_count"], 2)
        self.assertEqual(staged["date_filter_audit"]["excluded_race_count"], 0)

    def test_dry_run_is_idempotent_and_write_free(self):
        self.write_rows(self.raw, [self.row()])
        first = operation.run(self.raw, self.root / "out1", self.official, allowed_dates=["2026-07-18"], execute=False)
        second = operation.run(self.raw, self.root / "out2", self.official, allowed_dates=["2026-07-18"], execute=False)
        self.assertEqual(first, second)
        self.assertEqual(list(self.official.iterdir()), [])

    def test_multiple_sources_and_duplicate_source_race_handling(self):
        raw2 = self.root / "raw2.csv"
        self.write_rows(self.raw, [self.row()])
        self.write_rows(raw2, [self.row(date_text="2026-07-19", race=2)])
        result = operation.run(
            [self.raw, raw2], self.root / "out", self.official,
            allowed_dates=["2026-07-18", "2026-07-19"], execute=False,
        )
        self.assertEqual(result["race_count"], 2)
        self.assertEqual(len(result["raw_source_paths"]), 2)

        same = self.root / "same.csv"
        self.write_rows(same, [self.row()])
        staged = TargetBulkResultSplitter().stage_many([self.raw, same], self.root / "same_stage")
        self.assertEqual(staged["race_count"], 1)
        self.assertEqual(staged["duplicate_source_race_ids"], ["race_20260718_sapporo_1R"])

        different = self.root / "different.csv"
        self.write_rows(different, [self.row(class_name="1勝クラス")])
        with self.assertRaises(TargetBulkIntakeError) as caught:
            TargetBulkResultSplitter().stage_many([self.raw, different], self.root / "different_stage")
        self.assertEqual(caught.exception.reason_code, "DUPLICATE_RACE_ID_ACROSS_SOURCES_CONFLICT")

    def test_venue_completeness_is_not_inferred(self):
        self.write_rows(self.raw, [self.row(course="札幌", race=7)])
        staged = TargetBulkResultSplitter().stage(
            self.raw, self.root / "stage", allowed_dates=["2026-07-18"]
        )
        self.assertEqual(staged["date_filter_audit"]["included_by_date"], [
            {
                "date": "2026-07-18", "venue": "sapporo", "race_count": 1,
                "race_ids": ["race_20260718_sapporo_7R"],
            }
        ])

    def test_downstream_scope_invariant_rejects_excluded_race_id(self):
        staged = {
            "race_ids": ["race_20260719_sapporo_1R"],
            "split_files": [],
            "date_filter_audit": {"allowed_dates": ["2026-07-18"]},
        }
        with self.assertRaises(TargetBulkIntakeError) as caught:
            operation._assert_processing_scope(staged)
        self.assertEqual(caught.exception.reason_code, "DATE_FILTER_SCOPE_INVARIANT_VIOLATION")

    def test_invalid_excluded_date_structure_still_fails_full_validation(self):
        good = self.row()
        bad = self.row(date_text="2026-07-19", race=2)[:-1]
        self.write_rows(self.raw, [good, bad])
        stage = self.root / "stage"
        with self.assertRaises(TargetBulkIntakeError) as caught:
            TargetBulkResultSplitter().stage(self.raw, stage, allowed_dates=["2026-07-18"])
        self.assertEqual(caught.exception.reason_code, "COLUMN_COUNT_MISMATCH")
        self.assertFalse(stage.exists())

    def test_invalid_excluded_date_sentinel_still_fails_full_validation(self):
        bad = self.row(date_text="2026-07-19", race=2)
        bad[4] = "Unknown"
        self.write_rows(self.raw, [self.row(), bad])
        stage = self.root / "stage"
        with self.assertRaises(TargetBulkIntakeError) as caught:
            TargetBulkResultSplitter().stage(self.raw, stage, allowed_dates=["2026-07-18"])
        self.assertEqual(caught.exception.reason_code, "SENTINEL_VALIDATION_FAILED")
        self.assertFalse(stage.exists())


if __name__ == "__main__":
    unittest.main()
