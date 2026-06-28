"""相手レベルの知識を管理するファイルです。

分析ロジック側には点数を直接書かず、このファイルを参照させます。
将来JRA、JRA-VAN、netkeibaなどから取得したクラス表記に合わせたい場合は、
基本的にこの辞書へ名前を追加して対応します。
"""


OPPONENT_LEVELS = {
    "G1": 100,
    "G2": 95,
    "G3": 90,
    "リステッド": 85,
    "L": 85,
    "オープン": 80,
    "OP": 80,
    "3勝クラス": 70,
    "3勝": 70,
    "2勝クラス": 60,
    "2勝": 60,
    "1勝クラス": 50,
    "1勝": 50,
    "未勝利": 30,
    "新馬": 20,
}
"""レースクラスごとの相手レベルです。0〜100点で管理します。"""


DEFAULT_OPPONENT_LEVEL = 40
"""クラスが読めない場合の仮レベルです。"""


def get_opponent_level(class_level: str) -> int:
    """クラス名から相手レベルを取得します。"""

    normalized = normalize_class_name(class_level)
    return OPPONENT_LEVELS.get(normalized, DEFAULT_OPPONENT_LEVEL)


def normalize_class_name(class_level: str) -> str:
    """表記ゆれを少し吸収します。

    例:
    - 「3勝」も「3勝クラス」も同じ意味として扱います。
    - 空欄の場合は未知のクラスとして扱います。
    """

    value = class_level.strip()
    if not value:
        return "不明"

    aliases = {
        "L": "リステッド",
        "Listed": "リステッド",
        "オープン特別": "オープン",
        "3勝": "3勝クラス",
        "2勝": "2勝クラス",
        "1勝": "1勝クラス",
    }
    return aliases.get(value, value)
