import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from importer.csv_normalizer import normalize_target_row, write_standard_csv


DEFAULT_TARGET_INPUT = "data/raw/target_sample_entries.csv"
DEFAULT_TARGET_OUTPUT = "data/today_entries.csv"


def import_target_csv(
    input_path: str = DEFAULT_TARGET_INPUT,
    output_path: str = DEFAULT_TARGET_OUTPUT,
) -> str:
    """TARGET/JRA-VAN由来CSVをKeibaAI v1.0標準CSVへ変換します。

    TARGETの出力設定によって列名が少し変わることがあります。
    そのため、実際の変換は `csv_normalizer.py` の列マッピングに任せます。
    """

    source_path = Path(input_path)
    if not source_path.exists():
        raise FileNotFoundError(
            f"{source_path} が見つかりません。data/raw/ にTARGET CSVを置いてください。"
        )

    with source_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        source_rows = list(csv.DictReader(csv_file))

    standard_rows = [normalize_target_row(row) for row in source_rows]
    return write_standard_csv(standard_rows, output_path)


def import_first_target_csv(
    raw_dir: str = "data/raw",
    output_path: str = DEFAULT_TARGET_OUTPUT,
) -> str:
    """data/raw/ 内のCSVを1つ見つけて標準CSVへ変換します。

    実運用ではTARGETから出力したCSVを `data/raw/` に置き、この関数を入口にできます。
    """

    raw_path = Path(raw_dir)
    candidates = sorted(
        path for path in raw_path.glob("*.csv")
        if path.name != Path(output_path).name
    )
    if not candidates:
        raise FileNotFoundError(f"{raw_path} にCSVファイルが見つかりません。")

    return import_target_csv(str(candidates[0]), output_path)


def save_target_rows_as_standard(
    rows: list[dict[str, object]],
    output_path: str = DEFAULT_TARGET_OUTPUT,
) -> str:
    """Python上で作ったTARGET風データを、標準CSVとして保存する補助関数です。"""

    standard_rows = [normalize_target_row(row) for row in rows]
    return write_standard_csv(standard_rows, output_path)


if __name__ == "__main__":
    output = import_target_csv()
    print(f"TARGET CSVをKeibaAI標準CSVへ変換しました: {output}")
