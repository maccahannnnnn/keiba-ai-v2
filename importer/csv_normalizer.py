import csv
from pathlib import Path


KEIBAAI_V1_COLUMNS = [
    "race_date",
    "racecourse",
    "race_number",
    "distance",
    "surface",
    "track_condition",
    "status",
    "horse_number",
    "horse_name",
    "frame_number",
    "jockey",
    "weight",
    "body_weight",
    "body_weight_diff",
    "running_style",
    "last_runs",
    "past_lap_note",
    "expected_lap_note",
    "sire",
    "dam_sire",
    "bloodline_note",
    "class_level",
]
"""KeibaAI v1.0 の正式な標準CSV列です。"""


STANDARD_CSV_PATH = "data/today_entries.csv"

INPUT_ALIASES = {
    "carried_weight": "weight",
}
"""入力元でよく使われる別名を、KeibaAI v1.0 標準列へ対応させます。"""

TARGET_COLUMN_ALIASES = {
    "年月日": "race_date",
    "日付": "race_date",
    "開催日": "race_date",
    "場名": "racecourse",
    "競馬場": "racecourse",
    "場所": "racecourse",
    "R": "race_number",
    "レース番号": "race_number",
    "レース": "race_number",
    "距離": "distance",
    "芝ダ": "surface",
    "芝・ダ": "surface",
    "トラック種別": "surface",
    "馬場状態": "track_condition",
    "馬場": "track_condition",
    "状態": "status",
    "出走状態": "status",
    "馬番": "horse_number",
    "番": "horse_number",
    "馬名": "horse_name",
    "枠番": "frame_number",
    "枠": "frame_number",
    "騎手": "jockey",
    "斤量": "weight",
    "負担重量": "weight",
    "馬体重": "body_weight",
    "増減": "body_weight_diff",
    "馬体重増減": "body_weight_diff",
    "脚質": "running_style",
    "近走": "last_runs",
    "過去走": "last_runs",
    "前走着順": "last_runs",
    "ラップメモ": "past_lap_note",
    "過去ラップ": "past_lap_note",
    "想定ラップ": "expected_lap_note",
    "父": "sire",
    "種牡馬": "sire",
    "母父": "dam_sire",
    "母父馬": "dam_sire",
    "血統メモ": "bloodline_note",
    "血統": "bloodline_note",
    "クラス": "class_level",
    "レースクラス": "class_level",
    "class": "class_level",
    "race_date": "race_date",
    "racecourse": "racecourse",
    "race_number": "race_number",
    "distance": "distance",
    "surface": "surface",
    "track_condition": "track_condition",
    "status": "status",
    "horse_number": "horse_number",
    "horse_name": "horse_name",
    "frame_number": "frame_number",
    "jockey": "jockey",
    "weight": "weight",
    "body_weight": "body_weight",
    "body_weight_diff": "body_weight_diff",
    "running_style": "running_style",
    "last_runs": "last_runs",
    "past_lap_note": "past_lap_note",
    "expected_lap_note": "expected_lap_note",
    "sire": "sire",
    "dam_sire": "dam_sire",
    "bloodline_note": "bloodline_note",
    "class_level": "class_level",
}
"""TARGET/JRA-VAN CSVの列名をKeibaAI標準列へ寄せるためのマッピングです。"""


def normalize_to_standard_row(source_row: dict[str, object]) -> dict[str, str]:
    """どの入力元のデータでも、KeibaAI v1.0 標準CSVの1行へそろえます。"""

    aliased_row = apply_aliases(source_row)
    normalized_row = {
        column: normalize_cell(aliased_row.get(column, ""))
        for column in KEIBAAI_V1_COLUMNS
    }

    # status がない古いCSVや手入力CSVは、通常出走として扱います。
    if normalized_row["status"] in {"", "不明"}:
        normalized_row["status"] = "出走"

    return normalized_row


def normalize_to_standard_rows(source_rows: list[dict[str, object]]) -> list[dict[str, str]]:
    """複数行のデータを、KeibaAI v1.0 標準CSV形式へそろえます。"""

    return [normalize_to_standard_row(row) for row in source_rows]


def normalize_target_row(source_row: dict[str, object]) -> dict[str, str]:
    """TARGET/JRA-VAN由来CSVの1行をKeibaAI標準CSVの1行へ変換します。"""

    mapped_row: dict[str, object] = {}
    for source_name, value in source_row.items():
        standard_name = find_standard_column(source_name)
        if standard_name:
            mapped_row[standard_name] = value

    return normalize_to_standard_row(mapped_row)


def normalize_target_rows(source_rows: list[dict[str, object]]) -> list[dict[str, str]]:
    """TARGET/JRA-VAN由来CSVの複数行をKeibaAI標準CSV形式へ変換します。"""

    return [normalize_target_row(row) for row in source_rows]


def write_standard_csv(rows: list[dict[str, object]], output_path: str = STANDARD_CSV_PATH) -> str:
    """標準形式へそろえたデータを data/today_entries.csv として保存します。"""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_rows = normalize_to_standard_rows(rows)

    with path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=KEIBAAI_V1_COLUMNS)
        writer.writeheader()
        writer.writerows(normalized_rows)

    return str(path)


def normalize_standard_csv_file(input_path: str, output_path: str = STANDARD_CSV_PATH) -> str:
    """既存CSVを読み込み、KeibaAI v1.0 標準形式だけのCSVへ変換します。"""

    with Path(input_path).open("r", newline="", encoding="utf-8-sig") as csv_file:
        rows = list(csv.DictReader(csv_file))

    return write_standard_csv(rows, output_path)


def read_standard_csv(file_path: str = STANDARD_CSV_PATH) -> list[dict[str, str]]:
    """KeibaAI v1.0 標準CSVを辞書のリストとして読み込みます。"""

    with Path(file_path).open("r", newline="", encoding="utf-8-sig") as csv_file:
        return list(csv.DictReader(csv_file))


def normalize_cell(value: object) -> str:
    """CSVに保存しやすい文字列へ変換します。空欄は「不明」にします。"""

    if value is None:
        return "不明"

    text = str(value).strip()
    return text if text else "不明"


def apply_aliases(source_row: dict[str, object]) -> dict[str, object]:
    """入力列の別名を標準列へ寄せます。標準列がある場合はそちらを優先します。"""

    aliased_row = dict(source_row)
    for source_name, standard_name in INPUT_ALIASES.items():
        standard_value = normalize_cell(aliased_row.get(standard_name, ""))
        if standard_value == "不明":
            aliased_row[standard_name] = source_row.get(source_name, "")
    return aliased_row


def find_standard_column(source_name: str) -> str:
    """入力CSVの列名から、対応するKeibaAI標準列名を探します。"""

    cleaned_name = normalize_column_name(source_name)
    for alias, standard_name in TARGET_COLUMN_ALIASES.items():
        if normalize_column_name(alias) == cleaned_name:
            return standard_name
    return ""


def normalize_column_name(name: object) -> str:
    """列名比較用に、空白や記号の違いを少し吸収します。"""

    text = str(name).strip().lower()
    for char in [" ", "　", "_", "-", "・", "/", "\\", "(", ")", "（", "）"]:
        text = text.replace(char, "")
    return text
