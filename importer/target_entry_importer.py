"""Importer for TARGET frontier JV entry CSV files.

This module reads TARGET C-style entry CSV files and converts each row into
an Entry object.  It is intentionally standalone and is not connected to the
Analyzer, Evaluation Engine, CSV normalizer, or main.py.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from evaluation.course_name_normalizer import normalize_course_name
from importer.target_column_mapping import (
    TARGET_ENTRY_COLUMN_MAP,
    get_mapped_value,
    normalize_column_name,
)
from importer.target_entry_schema import get_entry_25_value


TARGET_ENTRY_22_COLUMN_SCHEMA = {
    "frame_number": 0,
    "horse_number": 2,
    "horse_name": 7,
    "sex": 9,
    "age": 10,
    "jockey": 12,
    "weight_carried": 13,
    "affiliation": 15,
    "trainer": 16,
    "owner": 18,
    "breeder": 19,
}


@dataclass
class Entry:
    horse_name: str | None = None
    frame_number: str | None = None
    horse_number: str | None = None
    sex_age: str | None = None
    weight_carried: str | None = None
    jockey: str | None = None
    sire: str | None = None
    dam: str | None = None
    broodmare_sire: str | None = None
    trainer: str | None = None
    affiliation: str | None = None
    owner: str | None = None
    breeder: str | None = None
    body_weight: str | None = None
    body_weight_diff: str | None = None
    race_date: str | None = None
    racecourse: str | None = None
    race_number: str | None = None


class TargetEntryImporter:
    """Read TARGET entry CSV rows into Entry objects."""

    ENCODINGS = ["utf-8-sig", "cp932", "shift_jis"]
    HEADERLESS_25_COLUMN_COUNT = 25
    HEADERLESS_22_COLUMN_COUNT = 22

    def load(self, csv_path):
        rows = self._read_rows(csv_path)
        context = self._context_from_path(csv_path)
        return [self._row_to_entry(row, context) for row in rows]

    def _read_rows(self, csv_path):
        if csv_path is None:
            return []

        path = Path(csv_path)
        for encoding in self.ENCODINGS:
            try:
                with path.open("r", encoding=encoding, newline="") as file:
                    raw_rows = list(csv.reader(file))
                return self._convert_raw_rows(raw_rows)
            except (OSError, csv.Error, UnicodeDecodeError):
                continue
        return []

    def _convert_raw_rows(self, raw_rows):
        if not raw_rows:
            return []
        if self._looks_like_header(raw_rows[0]):
            header = raw_rows[0]
            return [
                {header[index]: value for index, value in enumerate(row)}
                for row in raw_rows[1:]
            ]
        return raw_rows

    def _looks_like_header(self, row):
        normalized_aliases = {
            normalize_column_name(alias)
            for aliases in TARGET_ENTRY_COLUMN_MAP.values()
            for alias in aliases
        }
        normalized_cells = {normalize_column_name(cell) for cell in row}
        return bool(normalized_aliases & normalized_cells)

    def _context_from_path(self, csv_path):
        if csv_path is None:
            return {}
        name = Path(csv_path).stem
        match = re.search(r"race_(\d{8})_([^_]+)_([0-9]+R)", name, re.IGNORECASE)
        if not match:
            return {}

        race_date, racecourse, race_number = match.groups()
        return {
            "race_date": f"{race_date[:4]}-{race_date[4:6]}-{race_date[6:]}",
            "racecourse": normalize_course_name(racecourse),
            "race_number": race_number.upper(),
        }

    def _row_to_entry(self, row, context=None):
        context = context or {}
        return Entry(
            horse_name=self._value(row, "horse_name"),
            frame_number=self._value(row, "frame_number"),
            horse_number=self._value(row, "horse_number"),
            sex_age=self._value(row, "sex_age"),
            weight_carried=self._value(row, "weight_carried"),
            jockey=self._value(row, "jockey"),
            sire=self._value(row, "sire"),
            dam=self._value(row, "dam"),
            broodmare_sire=self._value(row, "broodmare_sire"),
            trainer=self._value(row, "trainer"),
            affiliation=self._value(row, "affiliation"),
            owner=self._value(row, "owner"),
            breeder=self._value(row, "breeder"),
            body_weight=self._value(row, "body_weight"),
            body_weight_diff=self._value(row, "body_weight_diff"),
            race_date=self._value(row, "race_date") or context.get("race_date"),
            racecourse=normalize_course_name(self._value(row, "racecourse") or context.get("racecourse")),
            race_number=self._value(row, "race_number") or context.get("race_number"),
        )

    def _value(self, row, field_name):
        if isinstance(row, list):
            return self._fixed_value(row, field_name)
        return get_mapped_value(row, TARGET_ENTRY_COLUMN_MAP, field_name)

    def _fixed_value(self, row, field_name):
        if len(row) == self.HEADERLESS_25_COLUMN_COUNT:
            getter = get_entry_25_value
        elif len(row) == self.HEADERLESS_22_COLUMN_COUNT:
            getter = self._get_entry_22_value
        else:
            return None
        if field_name == "sex_age":
            sex = getter(row, "sex")
            age = getter(row, "age")
            return f"{sex}{age}" if sex or age else None
        return getter(row, field_name)

    def _get_entry_22_value(self, row, field_name, default=None):
        index = TARGET_ENTRY_22_COLUMN_SCHEMA.get(field_name)
        if index is None or not isinstance(row, list) or index >= len(row):
            return default
        value = row[index]
        if value is None:
            return default
        text = str(value).strip()
        return text if text else default


def load_target_entries(csv_path):
    """Convenience function for scripts and quick checks."""

    return TargetEntryImporter().load(csv_path)


if __name__ == "__main__":
    print(TargetEntryImporter().load(None))
