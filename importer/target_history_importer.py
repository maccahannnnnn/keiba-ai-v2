"""Importer for TARGET frontier JV all-horse history CSV files.

This module reads TARGET S-style result/history CSV files and groups past
runs by horse name.  It is standalone and is not connected to the Analyzer,
Evaluation Engine, CSV normalizer, or main.py.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from importer.target_column_mapping import (
    TARGET_HISTORY_FIXED_COLUMN_MAP,
    TARGET_HISTORY_COLUMN_MAP,
    get_fixed_value,
    get_mapped_value,
    normalize_column_name,
)


@dataclass
class HistoryRun:
    race_date: str | None = None
    race_name: str | None = None
    class_level: str | None = None
    racecourse: str | None = None
    surface: str | None = None
    distance: str | None = None
    track_condition: str | None = None
    finish_position: str | None = None
    margin: str | None = None
    time: str | None = None
    adjusted_time: str | None = None
    corner_1: str | None = None
    corner_2: str | None = None
    corner_3: str | None = None
    corner_4: str | None = None
    last_3f: str | None = None
    body_weight: str | None = None
    body_weight_diff: str | None = None
    sire: str | None = None
    dam: str | None = None
    broodmare_sire: str | None = None
    pci: str | None = None
    rpci: str | None = None


@dataclass
class HorseHistory:
    horse_name: str
    runs: list[HistoryRun] = field(default_factory=list)


class TargetHistoryImporter:
    """Read TARGET history CSV rows into HorseHistory objects by horse name."""

    ENCODINGS = ["utf-8-sig", "cp932", "shift_jis"]

    def load(self, csv_path):
        rows = self._read_rows(csv_path)
        histories = {}

        for row in rows:
            horse_name = self._value(row, "horse_name")
            if not horse_name:
                continue

            if horse_name not in histories:
                histories[horse_name] = HorseHistory(horse_name=horse_name)
            histories[horse_name].runs.append(self._row_to_run(row))

        return histories

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
            for aliases in TARGET_HISTORY_COLUMN_MAP.values()
            for alias in aliases
        }
        normalized_cells = {normalize_column_name(cell) for cell in row}
        return bool(normalized_aliases & normalized_cells)

    def _row_to_run(self, row):
        return HistoryRun(
            race_date=self._value(row, "race_date"),
            race_name=self._value(row, "race_name"),
            class_level=self._value(row, "class_level"),
            racecourse=self._value(row, "racecourse"),
            surface=self._value(row, "surface"),
            distance=self._value(row, "distance"),
            track_condition=self._value(row, "track_condition"),
            finish_position=self._value(row, "finish_position"),
            margin=self._value(row, "margin"),
            time=self._value(row, "time"),
            adjusted_time=self._value(row, "adjusted_time"),
            corner_1=self._value(row, "corner_1"),
            corner_2=self._value(row, "corner_2"),
            corner_3=self._value(row, "corner_3"),
            corner_4=self._value(row, "corner_4"),
            last_3f=self._value(row, "last_3f"),
            body_weight=self._value(row, "body_weight"),
            body_weight_diff=self._value(row, "body_weight_diff"),
            sire=self._value(row, "sire"),
            dam=self._value(row, "dam"),
            broodmare_sire=self._value(row, "broodmare_sire"),
            pci=self._value(row, "pci"),
            rpci=self._value(row, "rpci"),
        )

    def _value(self, row, field_name):
        if isinstance(row, list):
            return self._fixed_value(row, field_name)
        return get_mapped_value(row, TARGET_HISTORY_COLUMN_MAP, field_name)

    def _fixed_value(self, row, field_name):
        if field_name == "race_date":
            return self._fixed_race_date(row)
        return get_fixed_value(row, TARGET_HISTORY_FIXED_COLUMN_MAP, field_name)

    def _fixed_race_date(self, row):
        year = get_fixed_value(row, TARGET_HISTORY_FIXED_COLUMN_MAP, "year")
        month = get_fixed_value(row, TARGET_HISTORY_FIXED_COLUMN_MAP, "month")
        day = get_fixed_value(row, TARGET_HISTORY_FIXED_COLUMN_MAP, "day")
        if not year or not month or not day:
            return None

        try:
            year_number = int(year)
            if year_number < 100:
                year_number += 2000
            return f"{year_number:04d}/{int(month):02d}/{int(day):02d}"
        except ValueError:
            return f"{year}/{month}/{day}"


def load_target_histories(csv_path):
    """Convenience function for scripts and quick checks."""

    return TargetHistoryImporter().load(csv_path)


def attach_histories_to_entries(entries, histories):
    """Return pairs of Entry and HorseHistory matched by horse name."""

    pairs = []
    for entry in entries or []:
        horse_name = getattr(entry, "horse_name", None)
        pairs.append((entry, histories.get(horse_name) if isinstance(histories, dict) else None))
    return pairs


if __name__ == "__main__":
    print(TargetHistoryImporter().load(None))
