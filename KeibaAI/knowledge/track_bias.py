from dataclasses import dataclass


@dataclass
class TrackBiasProfile:
    """馬場バイアスの知識データです。

    ここには分析ロジックを書かず、競馬場・条件ごとの傾向だけを登録します。
    今後データを増やす場合は TRACK_BIAS_PROFILES に追加します。
    """

    racecourse: str
    surface: str
    distance: int
    inner_favorable: bool
    outer_favorable: bool
    front_favorable: bool
    closing_favorable: bool
    fast_clock: bool
    slow_clock: bool
    rain_impact: str
    deterioration_trend: str
    notes: list[str]

    def favorable_frames(self) -> list[str]:
        """有利になりやすい枠を文字で返します。"""

        frames: list[str] = []
        if self.inner_favorable:
            frames.append("内枠")
        if self.outer_favorable:
            frames.append("外枠")
        return frames or ["大きな偏りなし"]

    def favorable_styles(self) -> list[str]:
        """有利になりやすい脚質を文字で返します。"""

        styles: list[str] = []
        if self.front_favorable:
            styles.extend(["逃げ", "先行"])
        if self.closing_favorable:
            styles.extend(["差し", "追込"])
        return styles or ["大きな偏りなし"]

    def clock_tendency(self) -> str:
        """時計傾向を返します。"""

        if self.fast_clock:
            return "時計が速い"
        if self.slow_clock:
            return "時計が掛かる"
        return "標準"


DEFAULT_TRACK_BIAS = TrackBiasProfile(
    racecourse="不明",
    surface="不明",
    distance=0,
    inner_favorable=False,
    outer_favorable=False,
    front_favorable=False,
    closing_favorable=False,
    fast_clock=False,
    slow_clock=False,
    rain_impact="登録データなし",
    deterioration_trend="登録データなし",
    notes=["該当条件をknowledge/track_bias.pyに追加してください"],
)


TRACK_BIAS_PROFILES = {
    ("東京", "芝", 1600): TrackBiasProfile(
        racecourse="東京",
        surface="芝",
        distance=1600,
        inner_favorable=False,
        outer_favorable=True,
        front_favorable=False,
        closing_favorable=True,
        fast_clock=True,
        slow_clock=False,
        rain_impact="雨で時計が掛かると差しの持続力を評価",
        deterioration_trend="馬場悪化時は外差しが届きやすい",
        notes=["直線が長く、外からの末脚が生きやすい"],
    ),
    ("東京", "芝", 1800): TrackBiasProfile(
        racecourse="東京",
        surface="芝",
        distance=1800,
        inner_favorable=False,
        outer_favorable=True,
        front_favorable=False,
        closing_favorable=True,
        fast_clock=True,
        slow_clock=False,
        rain_impact="雨で瞬発力より持続力が問われやすい",
        deterioration_trend="内が荒れると外差しを強めに評価",
        notes=["直線が長く、差し・先行のバランスを見たい条件"],
    ),
    ("阪神", "芝", 2200): TrackBiasProfile(
        racecourse="阪神",
        surface="芝",
        distance=2200,
        inner_favorable=True,
        outer_favorable=False,
        front_favorable=True,
        closing_favorable=False,
        fast_clock=False,
        slow_clock=True,
        rain_impact="雨でスタミナと持続力が重要になりやすい",
        deterioration_trend="馬場悪化時は早めに動ける先行馬を評価",
        notes=["内回りでロングスパートと立ち回りが重要"],
    ),
    ("中山", "芝", 2000): TrackBiasProfile(
        racecourse="中山",
        surface="芝",
        distance=2000,
        inner_favorable=True,
        outer_favorable=False,
        front_favorable=True,
        closing_favorable=False,
        fast_clock=False,
        slow_clock=True,
        rain_impact="雨でパワー型と内で我慢できる馬を評価",
        deterioration_trend="馬場悪化時は外を回す差し馬にロスが出やすい",
        notes=["コーナーが多く、器用さと先行力が生きやすい"],
    ),
    ("京都", "ダート", 1800): TrackBiasProfile(
        racecourse="京都",
        surface="ダート",
        distance=1800,
        inner_favorable=True,
        outer_favorable=False,
        front_favorable=True,
        closing_favorable=False,
        fast_clock=True,
        slow_clock=False,
        rain_impact="脚抜きが良いと前が止まりにくい",
        deterioration_trend="湿ったダートでは先行力とスピードを評価",
        notes=["先行してロスなく運べる馬を評価"],
    ),
}


def get_track_bias_profile(racecourse: str, surface: str, distance: int) -> TrackBiasProfile:
    """競馬場・芝/ダート・距離から馬場バイアスを取得します。"""

    key = (racecourse, surface, distance)
    return TRACK_BIAS_PROFILES.get(key, DEFAULT_TRACK_BIAS)
