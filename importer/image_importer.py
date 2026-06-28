from pathlib import Path

from importer.csv_normalizer import write_standard_csv


def import_entry_image(input_path: str, output_path: str = "data/today_entries.csv") -> str:
    """JRA出馬表画像をOCRして標準CSVへ変換する将来用の予備入口です。"""

    raise NotImplementedError(
        f"{Path(input_path)} の画像OCR変換は予備機能として今後実装します。"
        f"出力先は {output_path} を想定しています。"
    )


def save_ocr_rows_as_standard(rows: list[dict[str, object]], output_path: str = "data/today_entries.csv") -> str:
    """OCR済みの行データを、標準CSVとして保存します。"""

    return write_standard_csv(rows, output_path)
