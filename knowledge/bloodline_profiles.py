"""血統辞書の互換入口です。

KeibaAI v1.0 の血統データ本体は knowledge/bloodline.py で管理します。
既存Analyzerはこのファイルを import しているため、Analyzerを変更せずに
新しい血統辞書を使えるよう、ここから再公開します。
"""

from knowledge.bloodline import (
    BLOODLINE_PROFILES,
    UNKNOWN_BLOODLINE,
    BloodlineAnalysis,
    BloodlineProfile,
    analyze_bloodline,
    get_bloodline_profile,
    is_distance_match,
)


__all__ = [
    "BLOODLINE_PROFILES",
    "UNKNOWN_BLOODLINE",
    "BloodlineAnalysis",
    "BloodlineProfile",
    "analyze_bloodline",
    "get_bloodline_profile",
    "is_distance_match",
]
