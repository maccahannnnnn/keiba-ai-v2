"""血統辞書の新しい管理場所です。

現時点では互換性維持のため、既存の `knowledge.bloodline` を再公開します。
将来はこのファイルへ血統カテゴリ別の分割を進めます。
"""

from knowledge.bloodline import (
    BLOODLINE_PROFILES,
    BloodlineAnalysis,
    BloodlineProfile,
    analyze_bloodline,
    get_bloodline_profile,
)

__all__ = [
    "BLOODLINE_PROFILES",
    "BloodlineAnalysis",
    "BloodlineProfile",
    "analyze_bloodline",
    "get_bloodline_profile",
]
