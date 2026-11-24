"""Read-only TARGET parsers used only by JOCKEY_TIER_ADDITIVE_V1 Shadow.

This module is deliberately disconnected from Production importers and never
accepts result, POST, review, ledger, learning, or knowledge paths.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path


HISTORY_COLUMN_COUNT = 53
HISTORY_COLUMNS = {
    "year": 0,
    "month": 1,
    "day": 2,
    "racecourse": 4,
    "race_number": 6,
    "horse_name": 16,
    "jockey_name": 19,
    "carried_weight": 20,
    "finish_position": 23,
}

ENTRY_COLUMN_COUNTS = {22, 25}
ENTRY_COLUMNS = {"horse_number": 2, "horse_name": 7, "jockey_name": 12}


class ShadowSourceError(RuntimeError):
    pass


def _read_headerless(path: Path, allowed_counts: set[int]) -> list[list[str]]:
    if not path.is_file():
        raise ShadowSourceError(f"SOURCE_MISSING:{path}")
    rows = None
    for encoding in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                rows = list(csv.reader(handle))
            break
        except UnicodeDecodeError:
            continue
    if rows is None:
        raise ShadowSourceError(f"SOURCE_DECODE_FAILED:{path}")
    if not rows:
        raise ShadowSourceError(f"SOURCE_EMPTY:{path}")
    widths = {len(row) for row in rows}
    if not widths <= allowed_counts:
        raise ShadowSourceError(f"SOURCE_COLUMN_COUNT:{path}:{sorted(widths)}")
    return rows


def _date(row: list[str]) -> str:
    try:
        year = int(row[HISTORY_COLUMNS["year"]])
        year = year + 2000 if year < 100 else year
        month = int(row[HISTORY_COLUMNS["month"]])
        day = int(row[HISTORY_COLUMNS["day"]])
    except (ValueError, IndexError) as exc:
        raise ShadowSourceError("INVALID_HISTORY_DATE") from exc
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_history_file(path: Path) -> list[dict]:
    rows = _read_headerless(path, {HISTORY_COLUMN_COUNT})
    output = []
    for row_number, row in enumerate(rows, start=1):
        values = {name: row[index].strip() for name, index in HISTORY_COLUMNS.items()}
        output.append({
            "history_date": _date(row),
            **values,
            "source_path": path.as_posix(),
            "source_row_number": row_number,
            "semantic_row": tuple(cell.strip() for cell in row),
        })
    return output


def parse_history_files(paths: list[Path]) -> list[dict]:
    output = []
    for path in sorted(paths):
        output.extend(parse_history_file(path))
    return output


def parse_entry_file(path: Path) -> list[dict]:
    match = re.fullmatch(r"race_(\d{8})_([^_]+)_([0-9]+R)_entry", path.stem, re.IGNORECASE)
    if not match:
        raise ShadowSourceError(f"ENTRY_FILENAME_INVALID:{path}")
    race_date, racecourse, race_number = match.groups()
    rows = _read_headerless(path, ENTRY_COLUMN_COUNTS)
    return [
        {
            "race_id": f"race_{race_date}_{racecourse}_{race_number.upper()}",
            "race_date": race_date,
            "racecourse": racecourse,
            "race_number": race_number.upper(),
            "horse_number": row[ENTRY_COLUMNS["horse_number"]].strip(),
            "horse_name": row[ENTRY_COLUMNS["horse_name"]].strip(),
            "jockey_name": row[ENTRY_COLUMNS["jockey_name"]].strip(),
            "source_path": path.as_posix(),
        }
        for row in rows
    ]
