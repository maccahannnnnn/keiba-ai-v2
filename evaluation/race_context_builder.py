"""TrialAnalyzer 用の race_context を組み立てるBuilderです。

このモジュールはデータ整形専用です。
Knowledge Baseは読まず、評価もスコア計算も行いません。
CSV / Importer / Analyzer / main.py には接続しない独立モジュールです。
"""


from evaluation.course_name_normalizer import normalize_course_name


class RaceContextBuilder:
    """さまざまな入力dictを TrialAnalyzer が使える共通形式へ整えます。"""

    RACECOURSE_ALIASES = {
        "chukyo": "chuukyou",
        "chuukyou": "chuukyou",
        "札幌": "sapporo",
        "函館": "hakodate",
        "福島": "fukushima",
        "新潟": "niigata",
        "東京": "tokyo",
        "中山": "nakayama",
        "中京": "chukyo",
        "京都": "kyoto",
        "阪神": "hanshin",
        "小倉": "kokura",
    }

    SURFACE_ALIASES = {
        "芝": "turf",
        "turf": "turf",
        "ダート": "dirt",
        "dirt": "dirt",
    }

    CONDITION_ALIASES = {
        "良": "good",
        "good": "good",
        "firm": "firm",
        "稍重": "yielding",
        "稍": "yielding",
        "yielding": "yielding",
        "重": "soft",
        "soft": "soft",
        "heavy": "heavy",
        "不良": "heavy",
    }

    PACE_ALIASES = {
        "スロー": "slow",
        "slow": "slow",
        "平均": "average",
        "ミドル": "average",
        "average": "average",
        "middle": "average",
        "medium": "average",
        "ハイ": "fast",
        "high": "fast",
        "fast": "fast",
    }

    def build(self, raw_data):
        """raw_dataを TrialAnalyzer 用 race_context に変換します。"""

        data = raw_data if isinstance(raw_data, dict) else {}

        racecourse = self.normalize_racecourse(
            self._first_value(data, ["racecourse", "競馬場", "場名"])
        )
        surface = self.normalize_surface(
            self._first_value(data, ["surface", "馬場種別", "芝ダート", "コース種別"])
        )
        distance = self.normalize_distance(
            self._first_value(data, ["distance", "距離", "距離m"])
        )
        pace = self.normalize_pace(
            self._first_value(data, ["pace", "想定ペース", "ペース"])
        )
        condition = self.normalize_condition(
            self._first_value(
                data,
                ["track_condition", "condition", "馬場状態", "当日馬場状態"],
            )
        )
        bias_type = self._first_value(
            data,
            ["bias_type", "track_bias", "馬場傾向", "バイアス"],
        )

        sire_name = self._first_value(
            data,
            ["sire_name", "sire", "father", "父", "父名", "種牡馬"],
        )
        broodmare_sire_name = self._first_value(
            data,
            ["broodmare_sire_name", "broodmare_sire", "dam_sire", "母父", "母父名"],
        )

        return {
            "racecourse": racecourse,
            "surface": surface,
            "distance": distance,
            "pace": pace,
            "track_condition": {
                "surface": surface,
                "condition": condition,
                "bias_type": bias_type,
            },
            "bloodline": {
                "sire_name": sire_name,
                "broodmare_sire_name": broodmare_sire_name,
            },
        }

    def normalize_surface(self, value):
        """芝/ダート表記を TrialAnalyzer 用の英語キーへ寄せます。"""

        text = self._normalize_text(value)
        if text is None:
            return None
        return self.SURFACE_ALIASES.get(text, text)

    def normalize_condition(self, value):
        """馬場状態を英語キーへ寄せます。"""

        text = self._normalize_text(value)
        if text is None:
            return None
        return self.CONDITION_ALIASES.get(text, text)

    def normalize_distance(self, value):
        """距離をintへ変換します。変換できない場合はNoneを返します。"""

        if value is None:
            return None

        text = str(value).strip().lower().replace("m", "").replace("ｍ", "")
        try:
            return int(float(text))
        except ValueError:
            return None

    def normalize_racecourse(self, value):
        """競馬場名を英語キーへ寄せます。"""

        text = self._normalize_text(value)
        if text is None:
            return None
        return normalize_course_name(self.RACECOURSE_ALIASES.get(text, text))

    def normalize_pace(self, value):
        """ペース表記を slow / average / fast へ寄せます。"""

        text = self._normalize_text(value)
        if text is None:
            return None
        return self.PACE_ALIASES.get(text, text)

    def _first_value(self, data, keys):
        """複数候補キーのうち、最初に見つかった値を返します。"""

        for key in keys:
            if key in data:
                return data.get(key)
        return None

    def _normalize_text(self, value):
        """文字列の空白と英字小文字化だけを行います。"""

        if value is None:
            return None

        text = str(value).strip()
        if text == "":
            return None
        return text.lower() if self._is_ascii(text) else text

    def _is_ascii(self, value):
        try:
            value.encode("ascii")
        except UnicodeEncodeError:
            return False
        return True


if __name__ == "__main__":
    builder = RaceContextBuilder()
    samples = [
        {
            "racecourse": "tokyo",
            "surface": "turf",
            "distance": 1600,
            "track_condition": "good",
            "bias_type": "fast_track",
            "pace": "average",
            "sire_name": "キズナ",
            "broodmare_sire_name": "キングカメハメハ",
        },
        {
            "racecourse": "nakayama",
            "surface": "dirt",
            "distance": "1800",
            "track_condition": "heavy",
            "bias_type": "power_track",
            "pace": "average",
            "sire_name": "ドレフォン",
            "broodmare_sire_name": "キングカメハメハ",
        },
        {
            "競馬場": "東京",
            "馬場種別": "芝",
            "距離": "1600m",
            "馬場状態": "良",
            "バイアス": "fast_track",
            "ペース": "平均",
            "父": "キズナ",
            "母父": "キングカメハメハ",
        },
        {},
        None,
    ]

    for sample in samples:
        print(builder.build(sample))
