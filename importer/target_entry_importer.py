"""Importer for TARGET frontier JV entry CSV files.

This module reads TARGET C-style entry CSV files and converts each row into
an Entry object.  It is intentionally standalone and is not connected to the
Analyzer, Evaluation Engine, CSV normalizer, or main.py.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from importer.target_column_mapping import (
    TARGET_ENTRY_COLUMN_MAP,
    get_mapped_value,
)


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


class TargetEntryImporter:
    """Read TARGET entry CSV rows into Entry objects."""

    def load(self, csv_path):
        rows = self._read_rows(csv_path)
        return [self._row_to_entry(row) for row in rows]

    def _read_rows(self, csv_path):
        if csv_path is None:
            return []

        try:
            path = Path(csv_path)
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                if reader.fieldnames is None:
                    return []
                return [dict(row) for row in reader]
        except (OSError, csv.Error, UnicodeDecodeError):
            return []

    def _row_to_entry(self, row):
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
        )

    def _value(self, row, field_name):
        return get_mapped_value(row, TARGET_ENTRY_COLUMN_MAP, field_name)


def load_target_entries(csv_path):
    """Convenience function for scripts and quick checks."""

    return TargetEntryImporter().load(csv_path)


if __name__ == "__main__":
    print(TargetEntryImporter().load(None))
