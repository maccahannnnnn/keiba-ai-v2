from dataclasses import dataclass


@dataclass
class BloodlineProfile:
    """種牡馬・母父などの血統特徴です。"""

    name: str
    best_distances: tuple[int, int]
    preferred_tracks: list[str]
    surface_aptitude: list[str]
    instant_speed: int
    stamina: int
    heavy_track_aptitude: int
    growth: str
    cautions: list[str]


@dataclass
class BloodlineAnalysis:
    """今回条件と血統の相性をまとめた結果です。"""

    sire_name: str
    dam_sire_name: str
    features: str
    compatibility: str
    reason: str
    score_bonus: float


UNKNOWN_BLOODLINE = BloodlineProfile(
    name="未登録",
    best_distances=(1200, 2400),
    preferred_tracks=["良", "稍重", "重", "不良"],
    surface_aptitude=["芝", "ダート"],
    instant_speed=50,
    stamina=50,
    heavy_track_aptitude=50,
    growth="標準",
    cautions=["血統辞書に未登録"],
)


BLOODLINE_PROFILES = {
    "エピファネイア": BloodlineProfile(
        name="エピファネイア",
        best_distances=(1800, 2400),
        preferred_tracks=["良", "稍重"],
        surface_aptitude=["芝"],
        instant_speed=72,
        stamina=82,
        heavy_track_aptitude=58,
        growth="成長力あり",
        cautions=["気性面で折り合いに注意"],
    ),
    "キズナ": BloodlineProfile(
        name="キズナ",
        best_distances=(1600, 2400),
        preferred_tracks=["良", "稍重", "重"],
        surface_aptitude=["芝", "ダート"],
        instant_speed=68,
        stamina=78,
        heavy_track_aptitude=72,
        growth="古馬での成長力あり",
        cautions=["切れ味勝負だけになると相手次第"],
    ),
    "ロードカナロア": BloodlineProfile(
        name="ロードカナロア",
        best_distances=(1200, 1800),
        preferred_tracks=["良", "稍重"],
        surface_aptitude=["芝"],
        instant_speed=82,
        stamina=58,
        heavy_track_aptitude=55,
        growth="完成度が高い",
        cautions=["距離延長では折り合いと持続力に注意"],
    ),
    "ドゥラメンテ": BloodlineProfile(
        name="ドゥラメンテ",
        best_distances=(1800, 2400),
        preferred_tracks=["良", "稍重"],
        surface_aptitude=["芝"],
        instant_speed=78,
        stamina=80,
        heavy_track_aptitude=62,
        growth="成長力あり",
        cautions=["気性や体質面に注意"],
    ),
    "ハーツクライ": BloodlineProfile(
        name="ハーツクライ",
        best_distances=(1800, 2500),
        preferred_tracks=["良", "稍重"],
        surface_aptitude=["芝"],
        instant_speed=70,
        stamina=86,
        heavy_track_aptitude=60,
        growth="晩成傾向",
        cautions=["短距離の速い流れでは忙しい場合がある"],
    ),
    "ディープインパクト": BloodlineProfile(
        name="ディープインパクト",
        best_distances=(1600, 2400),
        preferred_tracks=["良", "稍重"],
        surface_aptitude=["芝"],
        instant_speed=90,
        stamina=76,
        heavy_track_aptitude=54,
        growth="完成度と成長力の両方",
        cautions=["重い馬場では切れ味を削がれることがある"],
    ),
    "キタサンブラック": BloodlineProfile(
        name="キタサンブラック",
        best_distances=(1800, 3000),
        preferred_tracks=["良", "稍重", "重"],
        surface_aptitude=["芝"],
        instant_speed=70,
        stamina=88,
        heavy_track_aptitude=72,
        growth="成長力あり",
        cautions=["瞬発力だけの勝負では相手の切れに注意"],
    ),
}
"""血統辞書本体です。

血統を増やす場合は、同じ形式で `BLOODLINE_PROFILES` に追加します。
"""


def get_bloodline_profile(name: str) -> BloodlineProfile:
    """血統名からプロフィールを取得します。"""

    return BLOODLINE_PROFILES.get(name, UNKNOWN_BLOODLINE)


def analyze_bloodline(
    sire_name: str,
    dam_sire_name: str,
    surface: str,
    distance: int,
    track_condition: str,
) -> BloodlineAnalysis:
    """今回条件と血統の相性を分析します。"""

    sire = get_bloodline_profile(sire_name)
    dam_sire = get_bloodline_profile(dam_sire_name)
    reasons: list[str] = []
    bonus = 0.0

    if is_distance_match(sire, distance):
        bonus += 8
        reasons.append("父の得意距離に近い")
    if is_distance_match(dam_sire, distance):
        bonus += 4
        reasons.append("母父の得意距離に近い")

    if surface in sire.surface_aptitude:
        bonus += 6
        reasons.append(f"父が{surface}向き")
    if track_condition in sire.preferred_tracks:
        bonus += 5
        reasons.append(f"父が{track_condition}馬場に対応")
    if track_condition in {"重", "不良"} and sire.heavy_track_aptitude >= 70:
        bonus += 6
        reasons.append("重馬場適性が高い")

    if not reasons:
        reasons.append("血統辞書上は標準評価")

    features = (
        f"父{sire.name}: 得意距離{sire.best_distances[0]}-{sire.best_distances[1]}m、"
        f"瞬発力{sire.instant_speed}、持続力{sire.stamina}、成長力:{sire.growth}"
    )
    compatibility = f"{surface}{distance}m・{track_condition}馬場への相性を評価"
    reason = " / ".join(reasons + sire.cautions[:1])

    return BloodlineAnalysis(
        sire_name=sire_name,
        dam_sire_name=dam_sire_name,
        features=features,
        compatibility=compatibility,
        reason=reason,
        score_bonus=bonus,
    )


def is_distance_match(profile: BloodlineProfile, distance: int) -> bool:
    """今回距離が血統の得意距離内かを判定します。"""

    return profile.best_distances[0] <= distance <= profile.best_distances[1]
