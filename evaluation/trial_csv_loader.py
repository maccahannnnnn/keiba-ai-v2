"""Trial Phase 用のCSV Loaderです。

正式Importerではありません。
試運転用CSVを読み込み、TrialHorseAnalyzerが受け取れるrace_jsonへ変換します。
"""

import csv
from pathlib import Path


class TrialCSVLoader:
    """CSVから試運転用race_jsonを作るクラスです。"""

    RACE_KEYS = [
        "racecourse",
        "surface",
        "distance",
        "track_condition",
        "bias_type",
        "pace",
    ]

    HORSE_KEYS = [
        "horse_name",
        "sire",
        "broodmare_sire",
    ]

    def load(self, csv_path):
        """CSVを読み込み、TrialHorseAnalyzer用race_jsonへ変換します。"""

        rows, error = self._read_rows(csv_path)
        race_json = self._empty_race_json()

        if error:
            race_json["error"] = error
            return race_json

        if not rows:
            return race_json

        first_row = rows[0]
        for key in self.RACE_KEYS:
            race_json[key] = first_row.get(key)

        race_json["horses"] = [self._build_horse(row) for row in rows]
        return race_json

    def _read_rows(self, csv_path):
        """CSVを安全に読み込みます。失敗時は(error)を返します。"""

        if csv_path is None:
            return [], "CSV path is None"

        try:
            path = Path(csv_path)
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                if reader.fieldnames is None:
                    return [], None
                rows = [dict(row) for row in reader]
                return rows, None
        except (OSError, csv.Error, UnicodeDecodeError) as error:
            return [], str(error)

    def _build_horse(self, row):
        """CSV 1行からhorse dictを作ります。列不足はNoneで補います。"""

        return {
            "name": row.get("horse_name"),
            "sire": row.get("sire"),
            "broodmare_sire": row.get("broodmare_sire"),
        }

    def _empty_race_json(self):
        """空CSVや読み込み失敗時にも安全なrace_jsonを返します。"""

        race_json = {key: None for key in self.RACE_KEYS}
        race_json["horses"] = []
        return race_json


if __name__ == "__main__":
    loader = TrialCSVLoader()
    print(loader.load(None))
