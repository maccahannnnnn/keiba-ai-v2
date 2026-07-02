"""Trial Phase 用のJSON Loaderです。

正式Importerではありません。
JRAレース1レース分を表すJSONを読み込み、TrialRaceLoaderが受け取れる
race_data(dict) へ安全に変換します。
"""

import json
from pathlib import Path


class TrialJsonLoader:
    """JSONファイルから試運転用race_dataを作るクラスです。"""

    RACE_KEYS = [
        "racecourse",
        "surface",
        "distance",
        "track_condition",
        "bias_type",
        "pace",
    ]

    HORSE_KEYS = [
        "name",
        "sire",
        "broodmare_sire",
    ]

    def load(self, path):
        """JSONを読み込み、TrialRaceLoaderへ渡せるdictへ変換します。

        horses が複数ある場合、TrialRaceLoaderがすぐ使えるように
        先頭馬の sire / broodmare_sire をトップレベルへ展開します。
        全馬情報は horses と race_data_list に保持します。
        """

        data = self._read_json(path)
        if not isinstance(data, dict):
            return self._empty_race_data(error="JSON root is not an object")
        if "_error" in data:
            return self._empty_race_data(error=data.get("_error"))

        horses = self._normalize_horses(data.get("horses"))
        first_horse = horses[0] if horses else {}

        race_data = {
            "racecourse": data.get("racecourse"),
            "surface": data.get("surface"),
            "distance": data.get("distance"),
            "track_condition": data.get("track_condition"),
            "bias_type": data.get("bias_type"),
            "pace": data.get("pace"),
            "sire": first_horse.get("sire"),
            "broodmare_sire": first_horse.get("broodmare_sire"),
            "horse_name": first_horse.get("name"),
            "horses": horses,
            "race_data_list": self._build_race_data_list(data, horses),
        }

        return race_data

    def _read_json(self, path):
        """JSONファイルを安全に読み込みます。失敗時はエラー情報dictを返します。"""

        if path is None:
            return {"_error": "JSON path is None"}

        try:
            json_path = Path(path)
            with json_path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            return {"_error": str(error)}

    def _normalize_horses(self, horses):
        """horsesをlist[dict]へ整えます。空や形式違いでも落としません。"""

        if not isinstance(horses, list):
            return []

        normalized = []
        for horse in horses:
            if not isinstance(horse, dict):
                continue

            normalized.append(
                {
                    "name": horse.get("name"),
                    "sire": horse.get("sire"),
                    "broodmare_sire": horse.get("broodmare_sire"),
                }
            )

        return normalized

    def _build_race_data_list(self, race_data, horses):
        """全馬分のTrialRaceLoader向けrace_dataを作ります。"""

        if not horses:
            return []

        race_values = {key: race_data.get(key) for key in self.RACE_KEYS}
        rows = []

        for horse in horses:
            row = dict(race_values)
            row["sire"] = horse.get("sire")
            row["broodmare_sire"] = horse.get("broodmare_sire")
            row["horse_name"] = horse.get("name")
            rows.append(row)

        return rows

    def _empty_race_data(self, error=None):
        """読み込み失敗時もTrialRaceLoaderに渡せる空dictを返します。"""

        race_data = {key: None for key in self.RACE_KEYS}
        race_data.update(
            {
                "sire": None,
                "broodmare_sire": None,
                "horse_name": None,
                "horses": [],
                "race_data_list": [],
            }
        )
        if error:
            race_data["error"] = error
        return race_data


if __name__ == "__main__":
    loader = TrialJsonLoader()
    print(loader.load(None))
