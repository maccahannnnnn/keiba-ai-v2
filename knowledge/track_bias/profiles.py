from dataclasses import dataclass, field


@dataclass
class TrackConditionBias:
    """馬場状態ごとの細かいバイアス知識です。

    今のAnalyzerは TrackBiasProfile の基本項目を使います。
    この状態別データは、将来「良なら内前」「重なら外差し」などを
    より細かく評価するための知識として蓄積します。
    """

    condition: str
    inner_favorable: bool
    outer_favorable: bool
    front_favorable: bool
    closing_favorable: bool
    deep_closing_favorable: bool
    fast_clock: bool
    slow_clock: bool
    stamina_required: bool
    instant_acceleration_required: bool
    notes: list[str]


@dataclass
class TrackBiasProfile:
    """馬場バイアスの知識データです。

    ここには分析ロジックを書かず、競馬場・コースごとの傾向だけを登録します。
    データを増やす場合は TRACK_BIAS_PROFILES に追加します。
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
    condition_biases: dict[str, TrackConditionBias] = field(default_factory=dict)

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


def condition_bias(
    condition: str,
    *,
    inner: bool,
    outer: bool,
    front: bool,
    closing: bool,
    deep_closing: bool,
    fast: bool,
    slow: bool,
    stamina: bool,
    instant: bool,
    notes: list[str],
) -> TrackConditionBias:
    """状態別バイアスを読みやすく登録するための補助関数です。"""

    return TrackConditionBias(
        condition=condition,
        inner_favorable=inner,
        outer_favorable=outer,
        front_favorable=front,
        closing_favorable=closing,
        deep_closing_favorable=deep_closing,
        fast_clock=fast,
        slow_clock=slow,
        stamina_required=stamina,
        instant_acceleration_required=instant,
        notes=notes,
    )


def condition_set(
    *,
    good: TrackConditionBias,
    yielding: TrackConditionBias,
    soft: TrackConditionBias,
    heavy: TrackConditionBias,
) -> dict[str, TrackConditionBias]:
    """良・稍重・重・不良の4状態をまとめます。"""

    return {
        "良": good,
        "稍重": yielding,
        "重": soft,
        "不良": heavy,
    }


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
        notes=["直線が長く、差しと先行のバランスを見る条件"],
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


TRACK_BIAS_PROFILES.update(
    {
        ("福島", "芝", 1200): TrackBiasProfile(
            racecourse="福島",
            surface="芝",
            distance=1200,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=False,
            fast_clock=True,
            slow_clock=False,
            rain_impact="雨量が増えると内の傷みが出やすく、外差しも浮上",
            deterioration_trend="開催後半は外差しやパワー型を警戒",
            notes=["小回り短距離で位置取りが重要", "良馬場は内前とスピードを評価"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["内前有利", "速い時計に対応できる短距離スピードを評価"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["前有利は残るが差しも届き始める", "パワーと持続力を評価"]),
                soft=condition_bias("重", inner=False, outer=True, front=False, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["内の傷みを避ける外差しに注意", "時計が掛かる"]),
                heavy=condition_bias("不良", inner=False, outer=True, front=False, closing=True, deep_closing=True, fast=False, slow=True, stamina=True, instant=False, notes=["外目を通る持続型を評価", "追込は展開待ちだが浮上余地あり"]),
            ),
        ),
        ("福島", "芝", 1800): TrackBiasProfile(
            racecourse="福島",
            surface="芝",
            distance=1800,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=True,
            fast_clock=False,
            slow_clock=True,
            rain_impact="雨で持続力とコーナーで動く力が重要",
            deterioration_trend="内が荒れると外から早めに動ける差しを評価",
            notes=["小回りで立ち回りと持続力が重要", "直線一気は難しい"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["内で立ち回る先行馬を評価", "差しは早めに動けることが条件"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["持続力のある先行・差しを評価", "瞬発力だけでは届きにくい"]),
                soft=condition_bias("重", inner=False, outer=True, front=False, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["外から長く脚を使う差しを評価", "スタミナ要求が上がる"]),
                heavy=condition_bias("不良", inner=False, outer=True, front=False, closing=True, deep_closing=True, fast=False, slow=True, stamina=True, instant=False, notes=["外差しと消耗戦適性を評価", "追込は展開が速ければ浮上"]),
            ),
        ),
        ("福島", "芝", 2000): TrackBiasProfile(
            racecourse="福島",
            surface="芝",
            distance=2000,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=True,
            fast_clock=False,
            slow_clock=True,
            rain_impact="雨でスタミナと持続力の比重が上がる",
            deterioration_trend="馬場が荒れると外から早めに進出できる馬を評価",
            notes=["小回り2000mで機動力と持続力が重要", "良馬場でも直線だけの差しは過信しない"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=False, stamina=True, instant=False, notes=["内で立ち回れる先行馬を評価", "差しは早めに動けるタイプ"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["持続力とパワーを評価", "内前も残るが差しも届く"]),
                soft=condition_bias("重", inner=False, outer=True, front=False, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["外差しとまくりに注意", "スタミナ要求が高い"]),
                heavy=condition_bias("不良", inner=False, outer=True, front=False, closing=True, deep_closing=True, fast=False, slow=True, stamina=True, instant=False, notes=["消耗戦適性を重視", "追込は展開が崩れた時に浮上"]),
            ),
        ),
        ("福島", "ダート", 1700): TrackBiasProfile(
            racecourse="福島",
            surface="ダート",
            distance=1700,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=False,
            fast_clock=True,
            slow_clock=False,
            rain_impact="脚抜きが良くなると前のスピードが止まりにくい",
            deterioration_trend="乾いて時計が掛かるとパワーと持続力を評価",
            notes=["小回りダートで先行力が重要", "1コーナーまでの位置取りを評価"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["前で運べる馬を評価", "時計はやや掛かりやすい"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["脚抜きが良く前有利", "スピード要求が上がる"]),
                soft=condition_bias("重", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["高速ダートで前が止まりにくい", "先行力を重視"]),
                heavy=condition_bias("不良", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["かなり時計が速くなりやすい", "差しは展開が速い時のみ"]),
            ),
        ),
        ("函館", "芝", 1200): TrackBiasProfile(
            racecourse="函館",
            surface="芝",
            distance=1200,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=False,
            fast_clock=False,
            slow_clock=True,
            rain_impact="洋芝で雨が降るとパワーとスタミナ要求が強まる",
            deterioration_trend="開催後半は外差しと洋芝巧者に注意",
            notes=["洋芝短距離で先行力とパワーを評価", "軽い瞬発力だけでは不安"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=False, slow=True, stamina=False, instant=True, notes=["内前と洋芝適性を評価", "短距離スピードが必要"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["パワー型先行馬を評価", "差しも持続力があれば届く"]),
                soft=condition_bias("重", inner=False, outer=True, front=False, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["洋芝の重馬場で外差し注意", "スタミナ要求が上がる"]),
                heavy=condition_bias("不良", inner=False, outer=True, front=False, closing=True, deep_closing=True, fast=False, slow=True, stamina=True, instant=False, notes=["時計が掛かる消耗戦", "外の持続型を評価"]),
            ),
        ),
        ("函館", "芝", 1800): TrackBiasProfile(
            racecourse="函館",
            surface="芝",
            distance=1800,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=True,
            fast_clock=False,
            slow_clock=True,
            rain_impact="雨で洋芝適性とスタミナがさらに重要",
            deterioration_trend="馬場悪化時は外を通る持続型の差しも評価",
            notes=["洋芝小回りで立ち回りと持続力が重要"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["内で運ぶ先行馬を評価", "差しは早めに動けるタイプ"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["パワーと持続力を評価", "瞬発力要求は低め"]),
                soft=condition_bias("重", inner=False, outer=True, front=False, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["外差しとスタミナ型を評価", "時計が掛かる"]),
                heavy=condition_bias("不良", inner=False, outer=True, front=False, closing=True, deep_closing=True, fast=False, slow=True, stamina=True, instant=False, notes=["消耗戦で追込も展開次第", "洋芝重馬場適性を重視"]),
            ),
        ),
        ("函館", "芝", 2000): TrackBiasProfile(
            racecourse="函館",
            surface="芝",
            distance=2000,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=True,
            fast_clock=False,
            slow_clock=True,
            rain_impact="雨でスタミナとパワーの比重が大きく上がる",
            deterioration_trend="外差しも届くが、早めに動ける機動力が必要",
            notes=["洋芝2000mで持続力とスタミナを評価", "直線だけでは届きにくい"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["内前と持続力を評価", "差しは早め進出が必要"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["パワーと洋芝適性を評価", "スタミナ要求が高い"]),
                soft=condition_bias("重", inner=False, outer=True, front=False, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["外差しと持続型を評価", "時計が掛かる"]),
                heavy=condition_bias("不良", inner=False, outer=True, front=False, closing=True, deep_closing=True, fast=False, slow=True, stamina=True, instant=False, notes=["消耗戦色が強い", "追込は展開が崩れれば浮上"]),
            ),
        ),
        ("函館", "ダート", 1700): TrackBiasProfile(
            racecourse="函館",
            surface="ダート",
            distance=1700,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=False,
            fast_clock=True,
            slow_clock=False,
            rain_impact="湿ると前が止まりにくく時計も速くなりやすい",
            deterioration_trend="乾いた力のいる馬場ではパワー型先行馬を評価",
            notes=["小回りダート1700mで先行力と立ち回りが重要"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["先行力とパワーを評価", "時計は掛かりやすい"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["脚抜きが良く前有利", "スピード要求"]),
                soft=condition_bias("重", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["高速ダートで前が残りやすい", "先行力を重視"]),
                heavy=condition_bias("不良", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["時計が速い", "差しは前崩れ時に限定"]),
            ),
        ),
        ("小倉", "芝", 1200): TrackBiasProfile(
            racecourse="小倉",
            surface="芝",
            distance=1200,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=False,
            fast_clock=True,
            slow_clock=False,
            rain_impact="雨で時計が掛かると外差しとパワー型に注意",
            deterioration_trend="開催後半は内の傷みで外差しが台頭しやすい",
            notes=["高速短距離でテンの速さが重要", "開幕週は内前を評価"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["内前と高速適性を評価", "瞬発力よりスピード持続"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["前有利は残るが差しも注意", "パワー要求"]),
                soft=condition_bias("重", inner=False, outer=True, front=False, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["外差しと持続力を評価", "時計が掛かる"]),
                heavy=condition_bias("不良", inner=False, outer=True, front=False, closing=True, deep_closing=True, fast=False, slow=True, stamina=True, instant=False, notes=["外の消耗戦型を評価", "追込も展開次第"]),
            ),
        ),
        ("小倉", "芝", 1800): TrackBiasProfile(
            racecourse="小倉",
            surface="芝",
            distance=1800,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=True,
            fast_clock=True,
            slow_clock=False,
            rain_impact="雨で時計が掛かると持続力とパワーを評価",
            deterioration_trend="馬場が荒れると外から動ける差しが届く",
            notes=["小回りで位置取りとコーナー加速が重要"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["内で立ち回る先行馬を評価", "差しは機動力が必要"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["持続力とパワーを評価", "外差しも警戒"]),
                soft=condition_bias("重", inner=False, outer=True, front=False, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["外差しとまくりを評価", "スタミナ要求"]),
                heavy=condition_bias("不良", inner=False, outer=True, front=False, closing=True, deep_closing=True, fast=False, slow=True, stamina=True, instant=False, notes=["消耗戦適性を重視", "追込は展開次第"]),
            ),
        ),
        ("小倉", "芝", 2000): TrackBiasProfile(
            racecourse="小倉",
            surface="芝",
            distance=2000,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=True,
            fast_clock=False,
            slow_clock=True,
            rain_impact="雨でスタミナと持続力要求が上がる",
            deterioration_trend="外をまくれる差し馬に注意",
            notes=["小回り2000mで早めに動ける持続力が重要"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=False, stamina=True, instant=False, notes=["内前と機動力を評価", "差しは早め進出が条件"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["持続力とパワーを評価", "時計は掛かりやすい"]),
                soft=condition_bias("重", inner=False, outer=True, front=False, closing=True, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["外差しとまくりを評価", "スタミナ要求が高い"]),
                heavy=condition_bias("不良", inner=False, outer=True, front=False, closing=True, deep_closing=True, fast=False, slow=True, stamina=True, instant=False, notes=["消耗戦になりやすい", "追込は展開が向けば浮上"]),
            ),
        ),
        ("小倉", "ダート", 1700): TrackBiasProfile(
            racecourse="小倉",
            surface="ダート",
            distance=1700,
            inner_favorable=True,
            outer_favorable=False,
            front_favorable=True,
            closing_favorable=False,
            fast_clock=True,
            slow_clock=False,
            rain_impact="脚抜きが良いとスピード型先行馬が止まりにくい",
            deterioration_trend="乾いた力のいる馬場ではパワーと持続力を評価",
            notes=["小回りダートで前に行ける馬を評価", "差しは展開依存"],
            condition_biases=condition_set(
                good=condition_bias("良", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=False, slow=True, stamina=True, instant=False, notes=["先行力とパワーを評価", "時計はやや掛かる"]),
                yielding=condition_bias("稍重", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["脚抜きが良く高速化", "前有利"]),
                soft=condition_bias("重", inner=True, outer=False, front=True, closing=False, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["先行スピードを重視", "時計が速い"]),
                heavy=condition_bias("不良", inner=True, outer=False, front=True, closing=True, deep_closing=False, fast=True, slow=False, stamina=False, instant=True, notes=["高速ダート", "差しは前崩れ時に注意"]),
            ),
        ),
    }
)


def get_track_bias_profile(racecourse: str, surface: str, distance: int) -> TrackBiasProfile:
    """競馬場・芝/ダート・距離から馬場バイアスを取得します。"""

    key = (racecourse, surface, distance)
    return TRACK_BIAS_PROFILES.get(key, DEFAULT_TRACK_BIAS)
