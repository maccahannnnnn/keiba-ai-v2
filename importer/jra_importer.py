from pathlib import Path

from importer.csv_normalizer import write_standard_csv


def import_jra_entries(input_path: str, output_path: str = "data/today_entries.csv") -> str:
    """JRA公式HTML/出馬表を KeibaAI v1.0 標準CSVへ変換する将来用入口です。"""

    raise NotImplementedError(
        f"{Path(input_path)} のJRA公式HTML/出馬表変換は今後実装します。"
        f"出力先は {output_path} を想定しています。"
    )


def save_jra_rows_as_standard(rows: list[dict[str, object]], output_path: str = "data/today_entries.csv") -> str:
    """JRA由来の行データを、標準CSVとして保存します。"""

    return write_standard_csv(rows, output_path)
