"""Trial JSON 内の馬を1頭ずつ試運転評価するAnalyzerです。

正式Analyzerではありません。
JSON由来のrace_dataを入力順に処理し、TrialRunnerで馬ごとの説明を返します。
順位付けやCSV連携は行いません。
"""

from evaluation.trial_runner import TrialRunner


class TrialHorseAnalyzer:
    """race_json内のhorsesを入力順に評価する試運転用クラスです。"""

    RACE_KEYS = [
        "racecourse",
        "surface",
        "distance",
        "track_condition",
        "bias_type",
        "pace",
    ]

    def __init__(self):
        self.runner = TrialRunner()

    def analyze_race(self, race_json):
        """race_json['horses']を1頭ずつTrialRunnerで評価します。"""

        data = race_json if isinstance(race_json, dict) else {}
        race_data_list = data.get("race_data_list")

        if isinstance(race_data_list, list) and race_data_list:
            rows = [row for row in race_data_list if isinstance(row, dict)]
        else:
            rows = self._build_rows_from_horses(data)

        results = []
        for row in rows:
            trial_result = self.runner.run(row)
            results.append(
                {
                    "name": row.get("horse_name") or row.get("name"),
                    "total_score": trial_result.get("total_score", 0),
                    "summary": trial_result.get("summary_text", ""),
                    "sections": trial_result.get("sections", {}),
                    "warnings": trial_result.get("warnings", []),
                }
            )

        return results

    def _build_rows_from_horses(self, race_json):
        """race_json['horses']からTrialRunner向けraw_data一覧を作ります。"""

        horses = race_json.get("horses")
        if not isinstance(horses, list):
            return []

        race_values = {key: race_json.get(key) for key in self.RACE_KEYS}
        rows = []

        for horse in horses:
            if not isinstance(horse, dict):
                continue

            row = dict(race_values)
            row["horse_name"] = horse.get("name")
            row["name"] = horse.get("name")
            row["sire"] = horse.get("sire")
            row["broodmare_sire"] = horse.get("broodmare_sire")
            rows.append(row)

        return rows


if __name__ == "__main__":
    analyzer = TrialHorseAnalyzer()
    sample = {
        "racecourse": "東京",
        "surface": "芝",
        "distance": 1600,
        "track_condition": "良",
        "bias_type": "fast_track",
        "pace": "average",
        "horses": [
            {
                "name": "サンプルホース1",
                "sire": "キズナ",
                "broodmare_sire": "キングカメハメハ",
            }
        ],
    }
    print(analyzer.analyze_race(sample))
