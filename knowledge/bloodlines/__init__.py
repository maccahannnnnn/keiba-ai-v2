"""血統知識ライブラリの入口です。

既存Analyzer向けの血統辞書と、将来拡張用の血統教科書をまとめて読み込めます。
"""

from knowledge.bloodlines.profiles import (
    BLOODLINE_PROFILES,
    BloodlineProfile,
    BloodlineAnalysis,
    analyze_bloodline,
    get_bloodline_profile,
)
from knowledge.bloodlines.foundation import BLOODLINE_FOUNDATION
from knowledge.bloodlines.sire_profiles import SIRE_PROFILES
from knowledge.bloodlines.broodmare import BROODMARE_SIRE_PROFILES
from knowledge.bloodlines.nicks import NICKS, CROSSES
from knowledge.bloodlines.turf import TURF_BLOODLINES
from knowledge.bloodlines.dirt import DIRT_BLOODLINES
from knowledge.bloodlines.stamina import STAMINA_BLOODLINES
from knowledge.bloodlines.speed import SPEED_BLOODLINES
from knowledge.bloodlines.course_affinity import COURSE_BLOODLINE_AFFINITY

__all__ = [
    "BLOODLINE_PROFILES",
    "BloodlineProfile",
    "BloodlineAnalysis",
    "analyze_bloodline",
    "get_bloodline_profile",
    "BLOODLINE_FOUNDATION",
    "SIRE_PROFILES",
    "BROODMARE_SIRE_PROFILES",
    "NICKS",
    "CROSSES",
    "TURF_BLOODLINES",
    "DIRT_BLOODLINES",
    "STAMINA_BLOODLINES",
    "SPEED_BLOODLINES",
    "COURSE_BLOODLINE_AFFINITY",
]
