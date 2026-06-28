from pathlib import Path

from importer.file_writer import write_today_entries
from importer.html_entry_parser import parse_html_entries
from importer.source_csv_parser import parse_source_csv_entries


def convert_to_today_entries(input_path: str, output_path: str) -> None:
    """HTMLまたはCSVを読み込み、AI用の today_entries.csv を作ります。"""

    source_path = Path(input_path)
    suffix = source_path.suffix.lower()

    if suffix in {".html", ".htm"}:
        entries = parse_html_entries(source_path)
    elif suffix == ".csv":
        entries = parse_source_csv_entries(source_path)
    else:
        raise ValueError("読み込める形式は .html, .htm, .csv です")

    write_today_entries(Path(output_path), entries)
