from pathlib import Path


def load_saved_jra_html(file_path: str) -> str:
    """保存済みのJRA出走表HTMLを読み込みます。

    今は自動取得を行いません。
    将来、JRA公式サイトから取得する処理を追加する場合は、
    このファイルに `fetch_jra_html()` のような関数を増やします。
    """

    return Path(file_path).read_text(encoding="utf-8")
