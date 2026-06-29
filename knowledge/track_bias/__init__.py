"""馬場バイアス知識の互換入口です。

既存コードは `knowledge.track_bias` を import するため、この入口で
`profiles.py` の内容を再公開します。
"""

from knowledge.track_bias.profiles import (
    DEFAULT_TRACK_BIAS,
    TRACK_BIAS_PROFILES,
    TrackBiasProfile,
    TrackConditionBias,
    condition_bias,
    condition_set,
    get_track_bias_profile,
)

__all__ = [
    "DEFAULT_TRACK_BIAS",
    "TRACK_BIAS_PROFILES",
    "TrackBiasProfile",
    "TrackConditionBias",
    "condition_bias",
    "condition_set",
    "get_track_bias_profile",
]
