from dataclasses import dataclass


@dataclass(frozen=True)
class RaceLevelProfile:
    """中央競馬のレースレベル定義です。

    ここでは「どのクラスの相手と走ってきたか」を0〜100点で管理します。
    Analyzer側はこの辞書を参照するだけにして、知識と評価ロジックを分離します。
    """

    name: str
    race_level_score: int
    description: str


RACE_LEVEL_PROFILES = {
    "G1": RaceLevelProfile("G1", 100, "中央競馬の最高レベル。相手関係は最上位"),
    "G2": RaceLevelProfile("G2", 95, "G1に近い高レベル戦"),
    "G3": RaceLevelProfile("G3", 90, "重賞レベル。オープンより明確に相手が強い"),
    "L": RaceLevelProfile("L", 85, "リステッド競走。オープン上位の相手関係"),
    "リステッド": RaceLevelProfile("リステッド", 85, "オープン上位の相手関係"),
    "OP": RaceLevelProfile("OP", 80, "オープンクラス"),
    "オープン": RaceLevelProfile("オープン", 80, "オープンクラス"),
    "3勝クラス": RaceLevelProfile("3勝クラス", 70, "条件戦の上位クラス"),
    "3勝": RaceLevelProfile("3勝クラス", 70, "条件戦の上位クラス"),
    "2勝クラス": RaceLevelProfile("2勝クラス", 60, "条件戦の中位クラス"),
    "2勝": RaceLevelProfile("2勝クラス", 60, "条件戦の中位クラス"),
    "1勝クラス": RaceLevelProfile("1勝クラス", 50, "条件戦の下位クラス"),
    "1勝": RaceLevelProfile("1勝クラス", 50, "条件戦の下位クラス"),
    "未勝利": RaceLevelProfile("未勝利", 30, "未勝利戦"),
    "新馬": RaceLevelProfile("新馬", 20, "新馬戦"),
}


DEFAULT_RACE_LEVEL = RaceLevelProfile("不明", 40, "レースレベル不明の仮評価")


RACE_LEVEL_ALIASES = {
    "Listed": "L",
    "オープン特別": "オープン",
    "3勝": "3勝クラス",
    "2勝": "2勝クラス",
    "1勝": "1勝クラス",
}


def normalize_race_level_name(class_level: str) -> str:
    """入力されたクラス名を、辞書で扱いやすい名前へそろえます。"""

    value = (class_level or "").strip()
    if not value or value == "不明":
        return "不明"
    return RACE_LEVEL_ALIASES.get(value, value)


def get_race_level_profile(class_level: str) -> RaceLevelProfile:
    """クラス名からレースレベルプロフィールを取得します。"""

    normalized = normalize_race_level_name(class_level)
    return RACE_LEVEL_PROFILES.get(normalized, DEFAULT_RACE_LEVEL)


def get_race_level_score(class_level: str) -> int:
    """クラス名から race_level_score だけを取得します。"""

    return get_race_level_profile(class_level).race_level_score
