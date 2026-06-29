"""レースレベル知識の互換入口です。"""

from knowledge.race_level.profiles import (
    DEFAULT_RACE_LEVEL,
    RACE_LEVEL_ALIASES,
    RACE_LEVEL_PROFILES,
    RaceLevelProfile,
    get_race_level_profile,
    get_race_level_score,
    normalize_race_level_name,
)

__all__ = [
    "DEFAULT_RACE_LEVEL",
    "RACE_LEVEL_ALIASES",
    "RACE_LEVEL_PROFILES",
    "RaceLevelProfile",
    "get_race_level_profile",
    "get_race_level_score",
    "normalize_race_level_name",
]
