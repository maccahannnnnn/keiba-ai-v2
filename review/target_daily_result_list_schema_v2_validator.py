"""Read-only structural validator for TARGET Daily Result List Schema v2.

Schema v2 inherits all result semantics from the frozen v1 schema.  This
module deliberately validates only source structure and Source C/D identity;
it never derives finishes, joins results, or calculates a KPI.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


COMMON_COLUMN_COUNT = 12
MIN_HEAD_COUNT = 1
MAX_HEAD_COUNT = 18
PRIMARY_VARIANT = "HORSE_NUMBER_ORDER_FINISH_STATUS"
AUXILIARY_VARIANT = "FINISH_ORDER_HORSE_NUMBER"


class DailyResultListSchemaV2ValidationError(ValueError):
    """Fail-closed validation exception carrying a stable reason code."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class ValidatedSource:
    path: str
    sha256: str
    variant: str
    date: str
    row_count: int
    raw_column_count: int
    normalized_column_count: int
    max_head_count: int
    race_index: dict[str, dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "variant": self.variant,
            "date": self.date,
            "row_count": self.row_count,
            "raw_column_count": self.raw_column_count,
            "normalized_column_count": self.normalized_column_count,
            "max_head_count": self.max_head_count,
            "race_index": self.race_index,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_cp932_csv(path: Path) -> list[list[str]]:
    try:
        with path.open("r", encoding="cp932", newline="") as source:
            rows = list(csv.reader(source))
    except UnicodeDecodeError as error:
        raise DailyResultListSchemaV2ValidationError(
            "CP932_DECODE_FAILURE", f"{path}: {error}"
        ) from error
    if not rows:
        raise DailyResultListSchemaV2ValidationError("EMPTY_SOURCE", str(path))
    return rows


def _integer(value: str, code: str, detail: str) -> int:
    if not value.isdigit():
        raise DailyResultListSchemaV2ValidationError(code, detail)
    return int(value)


def _validate_common_row(row: list[str], date: str, row_number: int) -> tuple[str, int]:
    if len(row) < COMMON_COLUMN_COUNT:
        raise DailyResultListSchemaV2ValidationError(
            "INTERMEDIATE_COLUMN_SHIFT_SUSPECTED",
            f"row {row_number} has fewer than {COMMON_COLUMN_COUNT} common columns",
        )
    race_key = row[0]
    if not re.fullmatch(r"[0-9]{16}", race_key) or race_key[:8] != date:
        raise DailyResultListSchemaV2ValidationError(
            "INTERMEDIATE_COLUMN_SHIFT_SUSPECTED",
            f"row {row_number} target_race_key is invalid for {date}: {race_key!r}",
        )
    if not row[1] or not row[3]:
        raise DailyResultListSchemaV2ValidationError(
            "INTERMEDIATE_COLUMN_SHIFT_SUSPECTED",
            f"row {row_number} has an empty required venue or race_name",
        )
    race_number = _integer(row[2], "INTERMEDIATE_COLUMN_SHIFT_SUSPECTED", f"row {row_number} race_number")
    if not 1 <= race_number <= 12:
        raise DailyResultListSchemaV2ValidationError(
            "INTERMEDIATE_COLUMN_SHIFT_SUSPECTED", f"row {row_number} race_number={race_number}"
        )
    head_count = _integer(row[9], "INVALID_HEAD_COUNT", f"row {row_number} head_count={row[9]!r}")
    if not MIN_HEAD_COUNT <= head_count <= MAX_HEAD_COUNT:
        raise DailyResultListSchemaV2ValidationError(
            "INVALID_HEAD_COUNT", f"row {row_number} head_count={head_count}"
        )
    return race_key, head_count


def _validate_variant_slots(
    row: list[str], variant: str, head_count: int, max_head_count: int, row_number: int
) -> None:
    required_last_index = COMMON_COLUMN_COUNT - 1 + head_count
    if required_last_index >= len(row):
        raise DailyResultListSchemaV2ValidationError(
            "REQUIRED_SLOT_MISSING", f"row {row_number} requires slot {head_count}"
        )

    required = row[COMMON_COLUMN_COUNT : COMMON_COLUMN_COUNT + head_count]
    if any(value == "" for value in required):
        raise DailyResultListSchemaV2ValidationError(
            "REQUIRED_SLOT_MISSING", f"row {row_number} has an empty required slot"
        )
    unused = row[COMMON_COLUMN_COUNT + head_count : COMMON_COLUMN_COUNT + max_head_count]
    if any(value != "" for value in unused):
        raise DailyResultListSchemaV2ValidationError(
            "UNUSED_SLOT_NOT_EMPTY", f"row {row_number} has content above head_count"
        )

    if variant == AUXILIARY_VARIANT:
        horse_numbers = []
        for value in required:
            horse_number = _integer(value, "REQUIRED_SLOT_MISSING", f"row {row_number} display slot={value!r}")
            if not 1 <= horse_number <= head_count:
                raise DailyResultListSchemaV2ValidationError(
                    "REQUIRED_SLOT_MISSING", f"row {row_number} display horse={horse_number}"
                )
            horse_numbers.append(horse_number)
        if set(horse_numbers) != set(range(1, head_count + 1)):
            raise DailyResultListSchemaV2ValidationError(
                "REQUIRED_SLOT_MISSING", f"row {row_number} display horse set is incomplete or duplicated"
            )


def validate_source(path: str | Path, date: str, variant: str) -> ValidatedSource:
    """Validate a single Source C or D file without normalizing its rows."""
    source_path = Path(path)
    if variant not in {PRIMARY_VARIANT, AUXILIARY_VARIANT}:
        raise ValueError(f"unsupported variant: {variant}")
    if not source_path.is_file():
        raise DailyResultListSchemaV2ValidationError("SOURCE_MISSING", str(source_path))
    rows = _read_cp932_csv(source_path)
    widths = {len(row) for row in rows}
    if len(widths) != 1:
        raise DailyResultListSchemaV2ValidationError(
            "INCONSISTENT_ROW_COLUMN_COUNT", f"{source_path}: widths={sorted(widths)}"
        )

    identities: list[tuple[str, int]] = []
    for row_number, row in enumerate(rows, start=1):
        identities.append(_validate_common_row(row, date, row_number))
    max_head_count = max(head_count for _, head_count in identities)
    raw_column_count = widths.pop()
    expected_width = COMMON_COLUMN_COUNT + max_head_count
    if raw_column_count != expected_width:
        raise DailyResultListSchemaV2ValidationError(
            "FILE_WIDTH_HEAD_COUNT_MISMATCH",
            f"{source_path}: width={raw_column_count}, expected={expected_width}, M={max_head_count}",
        )

    race_index: dict[str, dict[str, Any]] = {}
    for row_number, (row, (race_key, head_count)) in enumerate(zip(rows, identities), start=1):
        if race_key in race_index:
            raise DailyResultListSchemaV2ValidationError("DUPLICATE_TARGET_RACE_KEY", race_key)
        _validate_variant_slots(row, variant, head_count, max_head_count, row_number)
        race_index[race_key] = {
            "venue_name": row[1],
            "race_number": int(row[2]),
            "race_name": row[3],
            "head_count": head_count,
        }
    return ValidatedSource(
        path=str(source_path),
        sha256=sha256_file(source_path),
        variant=variant,
        date=date,
        row_count=len(rows),
        raw_column_count=raw_column_count,
        normalized_column_count=raw_column_count,
        max_head_count=max_head_count,
        race_index=race_index,
    )


def validate_source_pair(primary_path: str | Path, auxiliary_path: str | Path, date: str) -> dict[str, Any]:
    """Validate v2 structure and Source C/D identity reconciliation only."""
    primary = validate_source(primary_path, date, PRIMARY_VARIANT)
    auxiliary = validate_source(auxiliary_path, date, AUXILIARY_VARIANT)
    if primary.raw_column_count != auxiliary.raw_column_count:
        raise DailyResultListSchemaV2ValidationError(
            "SOURCE_VARIANT_WIDTH_MISMATCH",
            f"primary={primary.raw_column_count}, auxiliary={auxiliary.raw_column_count}",
        )
    if set(primary.race_index) != set(auxiliary.race_index):
        raise DailyResultListSchemaV2ValidationError("SOURCE_VARIANT_RACE_SET_MISMATCH", date)
    for race_key, primary_race in primary.race_index.items():
        auxiliary_race = auxiliary.race_index[race_key]
        if primary_race["head_count"] != auxiliary_race["head_count"]:
            raise DailyResultListSchemaV2ValidationError(
                "SOURCE_HEAD_COUNT_MISMATCH", f"{race_key}: {primary_race['head_count']} != {auxiliary_race['head_count']}"
            )
        if (primary_race["venue_name"], primary_race["race_number"]) != (
            auxiliary_race["venue_name"],
            auxiliary_race["race_number"],
        ):
            raise DailyResultListSchemaV2ValidationError("SOURCE_VARIANT_RACE_IDENTITY_MISMATCH", race_key)
    return {
        "date": date,
        "status": "PASS",
        "source_c_auxiliary": auxiliary.as_dict(),
        "source_d_primary": primary.as_dict(),
        "race_set_count": len(primary.race_index),
        "result_semantics_evaluated": False,
        "normalized_padding_applied": False,
    }


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate TARGET Daily Result List Schema v2 structure")
    parser.add_argument("--date", required=True)
    parser.add_argument("--primary", required=True)
    parser.add_argument("--auxiliary", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(validate_source_pair(args.primary, args.auxiliary, args.date), ensure_ascii=False, indent=2))
    except DailyResultListSchemaV2ValidationError as error:
        print(json.dumps({"status": "FAIL", "reason_code": error.code, "detail": error.detail}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
