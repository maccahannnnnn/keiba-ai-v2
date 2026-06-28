"""相手関係評価用の互換入口です。

KeibaAI v1.0 のレースレベル定義は knowledge/race_level.py で管理します。
既存コードが import している関数名を残しながら、新しい辞書へ一本化します。
"""

from knowledge.race_level import (
    DEFAULT_RACE_LEVEL,
    RACE_LEVEL_PROFILES,
    RaceLevelProfile,
    get_race_level_score,
    normalize_race_level_name,
)


OPPONENT_LEVELS = {
    name: profile.race_level_score
    for name, profile in RACE_LEVEL_PROFILES.items()
}
DEFAULT_OPPONENT_LEVEL = DEFAULT_RACE_LEVEL.race_level_score


def get_opponent_level(class_level: str) -> int:
    """クラス名から相手レベル点を取得します。"""

    return get_race_level_score(class_level)


def normalize_class_name(class_level: str) -> str:
    """旧関数名との互換用。レースレベル名を正規化します。"""

    return normalize_race_level_name(class_level)


__all__ = [
    "DEFAULT_OPPONENT_LEVEL",
    "OPPONENT_LEVELS",
    "RaceLevelProfile",
    "get_opponent_level",
    "normalize_class_name",
]
