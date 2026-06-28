from html.parser import HTMLParser
from pathlib import Path

from importer.normalized_entry import TARGET_COLUMNS, NormalizedEntry
from importer.source_csv_parser import HEADER_MAP
from importer.value_cleaner import normalize_row


class TableHTMLParser(HTMLParser):
    """HTML内の表を、行と列のリストとして取り出す簡単なパーサーです。"""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"th", "td"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._current_cell is not None and self._current_row is not None:
            text = " ".join(part for part in self._current_cell if part)
            self._current_row.append(text)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None and self._current_table is not None:
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None


def parse_html_entries(file_path: Path) -> list[NormalizedEntry]:
    """保存済みHTMLから出走表らしい表を探し、AI用データに変換します。"""

    html = file_path.read_text(encoding="utf-8")
    parser = TableHTMLParser()
    parser.feed(html)

    table = find_entry_table(parser.tables)
    if not table:
        raise ValueError("HTML内に出走表らしいテーブルが見つかりませんでした")

    header = table[0]
    entries: list[NormalizedEntry] = []

    for cells in table[1:]:
        source_row = dict(zip(header, cells))
        normalized_row: dict[str, str] = {}

        for source_name, value in source_row.items():
            target_name = HEADER_MAP.get(source_name, source_name)
            if target_name in TARGET_COLUMNS:
                normalized_row[target_name] = value

        normalized_row = normalize_row(normalized_row)
        entries.append(NormalizedEntry(**normalized_row))

    return entries


def find_entry_table(tables: list[list[list[str]]]) -> list[list[str]]:
    """複数の表から、馬名や馬番を含む出走表を探します。"""

    for table in tables:
        if not table:
            continue

        header_text = " ".join(table[0])
        has_horse_name = "馬名" in header_text or "horse_name" in header_text
        has_horse_number = "馬番" in header_text or "horse_number" in header_text

        if has_horse_name and has_horse_number:
            return table

    return []
