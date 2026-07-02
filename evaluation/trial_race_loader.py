"""試運転用のレース情報Loaderです。

正式Importerではありません。
JRAレース情報に近いdictを、RaceContextBuilderへ渡しやすいraw_dataへ整形します。
評価やKnowledge Base参照は一切行いません。
"""


class TrialRaceLoader:
    """レース情報dictをTrialRunner向けraw_dataへ変換するクラスです。"""

    OUTPUT_KEYS = [
        "racecourse",
        "surface",
        "distance",
        "track_condition",
        "bias_type",
        "pace",
        "sire_name",
        "broodmare_sire_name",
    ]

    KEY_ALIASES = {
        "racecourse": ["racecourse", "競馬場", "場名"],
        "surface": ["surface", "馬場種別", "芝ダート", "コース種別"],
        "distance": ["distance", "距離", "距離m"],
        "track_condition": [
            "track_condition",
            "condition",
            "馬場状態",
            "当日馬場状態",
        ],
        "bias_type": ["bias_type", "track_bias", "馬場傾向", "バイアス"],
        "pace": ["pace", "想定ペース", "ペース"],
        "sire_name": ["sire_name", "sire", "father", "父", "父名", "種牡馬"],
        "broodmare_sire_name": [
            "broodmare_sire_name",
            "broodmare_sire",
            "dam_sire",
            "母父",
            "母父名",
        ],
    }

    def load(self, race_data):
        """race_dataをRaceContextBuilderへ渡せるraw_dataへ変換します。"""

        data = race_data if isinstance(race_data, dict) else {}
        raw_data = {}

        for output_key in self.OUTPUT_KEYS:
            raw_data[output_key] = self._first_value(
                data,
                self.KEY_ALIASES.get(output_key, [output_key]),
            )

        return raw_data

    def _first_value(self, data, keys):
        """候補キーから最初に見つかった値を返します。不足時はNoneです。"""

        for key in keys:
            if key in data:
                return data.get(key)
        return None


if __name__ == "__main__":
    loader = TrialRaceLoader()
    samples = [
        {
            "racecourse": "tokyo",
            "surface": "turf",
            "distance": 1600,
            "condition": "good",
            "pace": "average",
            "sire": "キズナ",
            "broodmare_sire": "キングカメハメハ",
        },
        {
            "racecourse": "hanshin",
            "surface": "turf",
            "distance": 2200,
            "condition": "good",
            "pace": "slow",
            "sire": "キズナ",
            "broodmare_sire": "キングカメハメハ",
        },
        {
            "racecourse": "nakayama",
            "surface": "dirt",
            "distance": 1800,
            "condition": "heavy",
            "pace": "average",
            "sire": "ドレフォン",
            "broodmare_sire": "キングカメハメハ",
        },
        {
            "racecourse": "tokyo",
            "distance": 1600,
        },
        {},
        {
            "競馬場": "東京",
            "馬場種別": "芝",
            "距離": "1600m",
            "馬場状態": "良",
            "ペース": "平均",
            "父": "キズナ",
            "母父": "キングカメハメハ",
        },
    ]

    for sample in samples:
        print(loader.load(sample))
