import csv
from pathlib import Path

from importer.normalized_entry import TARGET_COLUMNS, NormalizedEntry
from importer.value_cleaner import normalize_row


HEADER_MAP = {
    "日付": "race_date",
    "開催日": "race_date",
    "競馬場": "racecourse",
    "場名": "racecourse",
    "レース": "race_number",
    "R": "race_number",
    "距離": "distance",
    "コース": "surface",
    "馬場": "track_condition",
    "馬場状態": "track_condition",
    "馬番": "horse_number",
    "馬名": "horse_name",
    "枠": "frame_number",
    "枠番": "frame_number",
    "騎手": "jockey",
    "斤量": "weight",
    "馬体重": "body_weight",
    "増減": "body_weight_diff",
    "馬体重増減": "body_weight_diff",
    "脚質": "running_style",
    "過去走": "last_runs",
    "過去走分析": "last_runs",
    "過去ラップ": "past_lap_note",
    "過去ラップメモ": "past_lap_note",
    "想定ラップ": "expected_lap_note",
    "想定ラップメモ": "expected_lap_note",
    "父": "sire",
    "種牡馬": "sire",
    "母父": "dam_sire",
    "母父馬": "dam_sire",
    "血統": "bloodline_note",
    "血統メモ": "bloodline_note",
}


def parse_source_csv_entries(file_path: Path) -> list[NormalizedEntry]:
    """元CSVを読み込み、AI用の列名にそろえます。"""

    entries: list[NormalizedEntry] = []

    with file_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            normalized_row: dict[str, str] = {}

            for source_name, value in row.items():
                target_name = HEADER_MAP.get(source_name, source_name)
                if target_name in TARGET_COLUMNS:
                    normalized_row[target_name] = value

            normalized_row = normalize_row(normalized_row)
            entries.append(NormalizedEntry(**normalized_row))

    return entries
