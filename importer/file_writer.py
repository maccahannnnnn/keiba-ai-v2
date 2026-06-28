import csv
from pathlib import Path

from importer.normalized_entry import TARGET_COLUMNS, NormalizedEntry


def write_today_entries(output_path: Path, entries: list[NormalizedEntry]) -> None:
    """変換済みの出走表データをCSVに保存します。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=TARGET_COLUMNS)
        writer.writeheader()

        for entry in entries:
            writer.writerow(entry.to_row())
