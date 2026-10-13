from __future__ import annotations

import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from review.target_daily_result_list_schema_v2_validator import (
    AUXILIARY_VARIANT,
    PRIMARY_VARIANT,
    DailyResultListSchemaV2ValidationError,
    validate_source,
    validate_source_pair,
)


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "data" / "raw" / "target" / "daily_result_list"


def make_row(date: str, race: int, head: int, width_max: int, variant: str) -> list[str]:
    row = [""] * (12 + width_max)
    row[0] = f"{date}0101{race:02d}01"
    row[1] = "札幌"
    row[2] = str(race)
    row[3] = f"テスト{race}R"
    row[9] = str(head)
    for horse in range(1, head + 1):
        row[11 + horse] = str(horse if variant == AUXILIARY_VARIANT else 1)
    return row


class TargetDailyResultListSchemaV2ValidatorTests(unittest.TestCase):
    def write_source(self, directory: Path, date: str, variant: str, rows: list[list[str]]) -> Path:
        filename = ("primary" if variant == PRIMARY_VARIANT else "auxiliary") + f"_{date}.csv"
        path = directory / filename
        with path.open("w", encoding="cp932", newline="") as target:
            csv.writer(target).writerows(rows)
        return path

    def assert_code(self, code: str, callable_obj, *args) -> None:
        with self.assertRaises(DailyResultListSchemaV2ValidationError) as caught:
            callable_obj(*args)
        self.assertEqual(code, caught.exception.code)

    def test_30_column_m18_source_passes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = self.write_source(Path(tmp), "20260628", PRIMARY_VARIANT, [make_row("20260628", 1, 18, 18, PRIMARY_VARIANT)])
            self.assertEqual(30, validate_source(path, "20260628", PRIMARY_VARIANT).raw_column_count)

    def test_29_column_m17_source_passes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = self.write_source(Path(tmp), "20260627", PRIMARY_VARIANT, [make_row("20260627", 1, 17, 17, PRIMARY_VARIANT)])
            self.assertEqual(29, validate_source(path, "20260627", PRIMARY_VARIANT).raw_column_count)

    def test_29_column_m18_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = self.write_source(Path(tmp), "20260627", PRIMARY_VARIANT, [make_row("20260627", 1, 18, 18, PRIMARY_VARIANT)[:-1]])
            self.assert_code("FILE_WIDTH_HEAD_COUNT_MISMATCH", validate_source, path, "20260627", PRIMARY_VARIANT)

    def test_28_column_m17_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            row = make_row("20260627", 1, 17, 17, PRIMARY_VARIANT)[:-1]
            path = self.write_source(Path(tmp), "20260627", PRIMARY_VARIANT, [row])
            self.assert_code("FILE_WIDTH_HEAD_COUNT_MISMATCH", validate_source, path, "20260627", PRIMARY_VARIANT)

    def test_mixed_row_width_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            rows = [make_row("20260627", 1, 17, 17, PRIMARY_VARIANT), make_row("20260627", 2, 17, 17, PRIMARY_VARIANT)[:-1]]
            path = self.write_source(Path(tmp), "20260627", PRIMARY_VARIANT, rows)
            self.assert_code("INCONSISTENT_ROW_COLUMN_COUNT", validate_source, path, "20260627", PRIMARY_VARIANT)

    def test_middle_column_deletion_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            row = make_row("20260628", 1, 18, 18, PRIMARY_VARIANT)
            del row[5]
            path = self.write_source(Path(tmp), "20260628", PRIMARY_VARIANT, [row])
            self.assert_code("INVALID_HEAD_COUNT", validate_source, path, "20260628", PRIMARY_VARIANT)

    def test_non_integer_head_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            row = make_row("20260627", 1, 17, 17, PRIMARY_VARIANT); row[9] = "A"
            path = self.write_source(Path(tmp), "20260627", PRIMARY_VARIANT, [row])
            self.assert_code("INVALID_HEAD_COUNT", validate_source, path, "20260627", PRIMARY_VARIANT)

    def test_zero_head_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            row = make_row("20260627", 1, 17, 17, PRIMARY_VARIANT); row[9] = "0"
            path = self.write_source(Path(tmp), "20260627", PRIMARY_VARIANT, [row])
            self.assert_code("INVALID_HEAD_COUNT", validate_source, path, "20260627", PRIMARY_VARIANT)

    def test_nineteen_head_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            row = make_row("20260627", 1, 17, 17, PRIMARY_VARIANT); row[9] = "19"
            path = self.write_source(Path(tmp), "20260627", PRIMARY_VARIANT, [row])
            self.assert_code("INVALID_HEAD_COUNT", validate_source, path, "20260627", PRIMARY_VARIANT)

    def test_required_primary_slot_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            row = make_row("20260627", 1, 17, 17, PRIMARY_VARIANT); row[28] = ""
            path = self.write_source(Path(tmp), "20260627", PRIMARY_VARIANT, [row])
            self.assert_code("REQUIRED_SLOT_MISSING", validate_source, path, "20260627", PRIMARY_VARIANT)

    def test_unused_slot_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            rows = [make_row("20260628", 1, 18, 18, PRIMARY_VARIANT), make_row("20260628", 2, 17, 18, PRIMARY_VARIANT)]
            rows[1][29] = "x"
            path = self.write_source(Path(tmp), "20260628", PRIMARY_VARIANT, rows)
            self.assert_code("UNUSED_SLOT_NOT_EMPTY", validate_source, path, "20260628", PRIMARY_VARIANT)

    def test_auxiliary_duplicate_horse_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            row = make_row("20260627", 1, 17, 17, AUXILIARY_VARIANT); row[28] = "1"
            path = self.write_source(Path(tmp), "20260627", AUXILIARY_VARIANT, [row])
            self.assert_code("REQUIRED_SLOT_MISSING", validate_source, path, "20260627", AUXILIARY_VARIANT)

    def test_invalid_identity_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            row = make_row("20260627", 1, 17, 17, PRIMARY_VARIANT); row[0] = "bad"
            path = self.write_source(Path(tmp), "20260627", PRIMARY_VARIANT, [row])
            self.assert_code("INTERMEDIATE_COLUMN_SHIFT_SUSPECTED", validate_source, path, "20260627", PRIMARY_VARIANT)

    def test_pair_29_column_m17_passes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            directory = Path(tmp)
            primary = self.write_source(directory, "20260627", PRIMARY_VARIANT, [make_row("20260627", 1, 17, 17, PRIMARY_VARIANT)])
            auxiliary = self.write_source(directory, "20260627", AUXILIARY_VARIANT, [make_row("20260627", 1, 17, 17, AUXILIARY_VARIANT)])
            self.assertEqual("PASS", validate_source_pair(primary, auxiliary, "20260627")["status"])

    def test_pair_30_column_m18_passes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            directory = Path(tmp)
            primary = self.write_source(directory, "20260628", PRIMARY_VARIANT, [make_row("20260628", 1, 18, 18, PRIMARY_VARIANT)])
            auxiliary = self.write_source(directory, "20260628", AUXILIARY_VARIANT, [make_row("20260628", 1, 18, 18, AUXILIARY_VARIANT)])
            self.assertEqual("PASS", validate_source_pair(primary, auxiliary, "20260628")["status"])

    def test_pair_width_mismatch_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            directory = Path(tmp)
            primary = self.write_source(directory, "20260628", PRIMARY_VARIANT, [make_row("20260628", 1, 18, 18, PRIMARY_VARIANT)])
            auxiliary = self.write_source(directory, "20260628", AUXILIARY_VARIANT, [make_row("20260628", 1, 17, 17, AUXILIARY_VARIANT)])
            self.assert_code("SOURCE_VARIANT_WIDTH_MISMATCH", validate_source_pair, primary, auxiliary, "20260628")

    def test_pair_head_mismatch_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            directory = Path(tmp)
            primary = self.write_source(directory, "20260628", PRIMARY_VARIANT, [
                make_row("20260628", 1, 17, 18, PRIMARY_VARIANT),
                make_row("20260628", 2, 18, 18, PRIMARY_VARIANT),
            ])
            auxiliary = self.write_source(directory, "20260628", AUXILIARY_VARIANT, [
                make_row("20260628", 1, 18, 18, AUXILIARY_VARIANT),
                make_row("20260628", 2, 18, 18, AUXILIARY_VARIANT),
            ])
            self.assert_code("SOURCE_HEAD_COUNT_MISMATCH", validate_source_pair, primary, auxiliary, "20260628")

    def test_pair_race_set_mismatch_rejects(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            directory = Path(tmp)
            primary = self.write_source(directory, "20260627", PRIMARY_VARIANT, [make_row("20260627", 1, 17, 17, PRIMARY_VARIANT)])
            auxiliary = self.write_source(directory, "20260627", AUXILIARY_VARIANT, [make_row("20260627", 2, 17, 17, AUXILIARY_VARIANT)])
            self.assert_code("SOURCE_VARIANT_RACE_SET_MISMATCH", validate_source_pair, primary, auxiliary, "20260627")

    def test_actual_four_date_pairs_pass_without_normalization(self):
        for date in ("20260627", "20260628", "20260815", "20260816"):
            result = validate_source_pair(
                RAW_ROOT / f"馬番順着順_{date}.csv",
                RAW_ROOT / f"着順馬番_{date}.csv",
                date,
            )
            self.assertEqual("PASS", result["status"])
            self.assertFalse(result["normalized_padding_applied"])

    def test_actual_raw_sha_is_unchanged_by_validation(self):
        path = RAW_ROOT / "馬番順着順_20260627.csv"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        validate_source(path, "20260627", PRIMARY_VARIANT)
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
