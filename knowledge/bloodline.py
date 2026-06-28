from dataclasses import dataclass, field


@dataclass
class BloodlineProfile:
    """種牡馬・母父などの血統特徴です。

    既存Analyzerが使う基本項目は best_distances / preferred_tracks /
    surface_aptitude / instant_speed / stamina / heavy_track_aptitude /
    growth / cautions です。

    それ以外の適性項目は、将来の特徴量化やレポート強化に使えるように
    辞書側へ蓄積しておきます。
    """

    name: str
    best_distances: tuple[int, int]
    preferred_tracks: list[str]
    surface_aptitude: list[str]
    instant_speed: int
    stamina: int
    heavy_track_aptitude: int
    growth: str
    cautions: list[str]
    turf_aptitude: int = 50
    dirt_aptitude: int = 50
    sprint_aptitude: int = 50
    mile_aptitude: int = 50
    middle_aptitude: int = 50
    long_aptitude: int = 50
    fukushima_aptitude: int = 50
    hakodate_aptitude: int = 50
    kokura_aptitude: int = 50
    front_runner: int = 50
    stalker: int = 50
    closer: int = 50
    fast_clock: int = 50
    power_type: int = 50
    stamina_type: int = 50
    notes: list[str] = field(default_factory=list)


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


def profile(
    name: str,
    best_distances: tuple[int, int],
    preferred_tracks: list[str],
    surface_aptitude: list[str],
    instant_speed: int,
    stamina: int,
    heavy_track_aptitude: int,
    growth: str,
    cautions: list[str],
    *,
    turf: int,
    dirt: int,
    sprint: int,
    mile: int,
    middle: int,
    long: int,
    fukushima: int,
    hakodate: int,
    kokura: int,
    front: int,
    stalker: int,
    closer: int,
    fast_clock: int,
    power: int,
    stamina_type: int,
    notes: list[str],
) -> BloodlineProfile:
    """種牡馬データを読みやすく登録するための補助関数です。"""

    return BloodlineProfile(
        name=name,
        best_distances=best_distances,
        preferred_tracks=preferred_tracks,
        surface_aptitude=surface_aptitude,
        instant_speed=instant_speed,
        stamina=stamina,
        heavy_track_aptitude=heavy_track_aptitude,
        growth=growth,
        cautions=cautions,
        turf_aptitude=turf,
        dirt_aptitude=dirt,
        sprint_aptitude=sprint,
        mile_aptitude=mile,
        middle_aptitude=middle,
        long_aptitude=long,
        fukushima_aptitude=fukushima,
        hakodate_aptitude=hakodate,
        kokura_aptitude=kokura,
        front_runner=front,
        stalker=stalker,
        closer=closer,
        fast_clock=fast_clock,
        power_type=power,
        stamina_type=stamina_type,
        notes=notes,
    )


BLOODLINE_PROFILES = {
    "キズナ": profile("キズナ", (1600, 2400), ["良", "稍重", "重"], ["芝", "ダート"], 68, 78, 72, "古馬での成長力あり", ["切れ味勝負だけになると相手次第"], turf=82, dirt=62, sprint=50, mile=78, middle=86, long=72, fukushima=78, hakodate=76, kokura=76, front=64, stalker=76, closer=70, fast_clock=70, power=76, stamina_type=80, notes=["芝中距離", "道悪対応", "持続力型"]),
    "エピファネイア": profile("エピファネイア", (1800, 2400), ["良", "稍重"], ["芝"], 72, 82, 58, "成長力あり", ["気性面で折り合いに注意"], turf=88, dirt=35, sprint=38, mile=72, middle=90, long=82, fukushima=70, hakodate=68, kokura=68, front=58, stalker=72, closer=74, fast_clock=74, power=66, stamina_type=82, notes=["芝中長距離", "持続力", "大物感"]),
    "キタサンブラック": profile("キタサンブラック", (1800, 3000), ["良", "稍重", "重"], ["芝"], 70, 88, 72, "成長力あり", ["瞬発力だけの勝負では相手の切れに注意"], turf=88, dirt=40, sprint=35, mile=62, middle=88, long=90, fukushima=78, hakodate=78, kokura=74, front=76, stalker=78, closer=62, fast_clock=68, power=78, stamina_type=90, notes=["スタミナ", "先行持続", "道悪対応"]),
    "ドゥラメンテ": profile("ドゥラメンテ", (1800, 2400), ["良", "稍重"], ["芝"], 78, 80, 62, "成長力あり", ["気性や体質面に注意"], turf=90, dirt=40, sprint=38, mile=70, middle=90, long=78, fukushima=72, hakodate=70, kokura=72, front=62, stalker=74, closer=76, fast_clock=80, power=72, stamina_type=78, notes=["芝中距離", "総合力", "末脚"]),
    "ロードカナロア": profile("ロードカナロア", (1200, 1800), ["良", "稍重"], ["芝"], 82, 58, 55, "完成度が高い", ["距離延長では折り合いと持続力に注意"], turf=90, dirt=48, sprint=92, mile=84, middle=58, long=30, fukushima=78, hakodate=76, kokura=82, front=78, stalker=76, closer=62, fast_clock=88, power=62, stamina_type=50, notes=["短距離", "マイル", "高速馬場"]),
    "ハービンジャー": profile("ハービンジャー", (1800, 2600), ["稍重", "重", "不良"], ["芝"], 62, 86, 82, "晩成寄り", ["高速上がり勝負では切れ負けに注意"], turf=82, dirt=30, sprint=28, mile=55, middle=86, long=86, fukushima=80, hakodate=88, kokura=78, front=58, stalker=70, closer=72, fast_clock=48, power=88, stamina_type=88, notes=["洋芝", "重馬場", "スタミナ"]),
    "ルーラーシップ": profile("ルーラーシップ", (1800, 2600), ["良", "稍重", "重"], ["芝", "ダート"], 66, 84, 72, "古馬で良化しやすい", ["スタートや器用さに課題が出ることがある"], turf=82, dirt=58, sprint=35, mile=62, middle=86, long=82, fukushima=78, hakodate=78, kokura=76, front=58, stalker=72, closer=70, fast_clock=62, power=80, stamina_type=86, notes=["持続力", "パワー", "中距離"]),
    "ゴールドシップ": profile("ゴールドシップ", (1800, 3000), ["稍重", "重", "不良"], ["芝"], 54, 92, 88, "使いながら良化", ["瞬発力勝負や高速馬場では注意"], turf=78, dirt=28, sprint=25, mile=45, middle=78, long=92, fukushima=82, hakodate=86, kokura=78, front=58, stalker=70, closer=72, fast_clock=42, power=90, stamina_type=94, notes=["スタミナ", "道悪", "持続戦"]),
    "モーリス": profile("モーリス", (1400, 2200), ["良", "稍重"], ["芝"], 74, 76, 64, "成長力あり", ["距離や気性でムラが出ることがある"], turf=84, dirt=42, sprint=68, mile=84, middle=78, long=55, fukushima=72, hakodate=72, kokura=74, front=70, stalker=76, closer=66, fast_clock=76, power=72, stamina_type=72, notes=["マイル", "中距離", "パワー"]),
    "リアルスティール": profile("リアルスティール", (1600, 2200), ["良", "稍重"], ["芝"], 78, 72, 58, "標準から成長力あり", ["重馬場や消耗戦では注意"], turf=84, dirt=45, sprint=50, mile=82, middle=82, long=62, fukushima=68, hakodate=66, kokura=70, front=62, stalker=74, closer=74, fast_clock=82, power=60, stamina_type=70, notes=["芝マイル中距離", "瞬発力", "高速馬場"]),
    "スワーヴリチャード": profile("スワーヴリチャード", (1600, 2400), ["良", "稍重"], ["芝"], 76, 78, 64, "成長力あり", ["小回りでは器用さを確認"], turf=84, dirt=40, sprint=45, mile=76, middle=86, long=72, fukushima=70, hakodate=70, kokura=70, front=62, stalker=74, closer=72, fast_clock=76, power=70, stamina_type=78, notes=["中距離", "持続力", "成長力"]),
    "リオンディーズ": profile("リオンディーズ", (1600, 2200), ["良", "稍重"], ["芝", "ダート"], 72, 72, 64, "標準", ["気性面と折り合いに注意"], turf=76, dirt=58, sprint=55, mile=76, middle=76, long=58, fukushima=72, hakodate=72, kokura=72, front=68, stalker=72, closer=62, fast_clock=72, power=70, stamina_type=70, notes=["マイル中距離", "先行", "パワー"]),
    "サトノダイヤモンド": profile("サトノダイヤモンド", (1800, 2600), ["良", "稍重"], ["芝"], 70, 82, 60, "成長力あり", ["道悪や高速短距離は割引"], turf=82, dirt=30, sprint=25, mile=58, middle=84, long=82, fukushima=70, hakodate=70, kokura=68, front=58, stalker=72, closer=70, fast_clock=68, power=66, stamina_type=84, notes=["芝中長距離", "スタミナ", "良馬場"]),
    "ドレフォン": profile("ドレフォン", (1200, 1800), ["良", "稍重", "重"], ["ダート", "芝"], 70, 68, 74, "早めから動ける", ["芝の瞬発力勝負では注意"], turf=58, dirt=86, sprint=78, mile=78, middle=62, long=35, fukushima=76, hakodate=76, kokura=78, front=78, stalker=72, closer=55, fast_clock=74, power=78, stamina_type=66, notes=["ダート", "短距離マイル", "先行力"]),
    "シニスターミニスター": profile("シニスターミニスター", (1200, 1800), ["良", "稍重", "重", "不良"], ["ダート"], 66, 76, 82, "ダートで安定", ["芝替わりは基本割引"], turf=20, dirt=92, sprint=72, mile=82, middle=66, long=38, fukushima=82, hakodate=82, kokura=84, front=86, stalker=72, closer=45, fast_clock=78, power=82, stamina_type=76, notes=["ダート先行", "小回り", "道悪"]),
    "ヘニーヒューズ": profile("ヘニーヒューズ", (1200, 1800), ["良", "稍重", "重"], ["ダート"], 74, 68, 76, "完成度高め", ["距離延長ではスタミナ確認"], turf=22, dirt=90, sprint=84, mile=80, middle=58, long=30, fukushima=78, hakodate=80, kokura=82, front=82, stalker=74, closer=48, fast_clock=82, power=76, stamina_type=64, notes=["ダート短距離", "スピード", "先行"]),
    "パイロ": profile("パイロ", (1200, 1800), ["稍重", "重", "不良"], ["ダート"], 64, 74, 84, "堅実", ["芝の切れ味勝負は不向き"], turf=20, dirt=86, sprint=72, mile=76, middle=66, long=38, fukushima=80, hakodate=80, kokura=80, front=78, stalker=72, closer=50, fast_clock=72, power=86, stamina_type=74, notes=["ダート", "道悪", "パワー"]),
    "ホッコータルマエ": profile("ホッコータルマエ", (1600, 2000), ["良", "稍重", "重"], ["ダート"], 58, 82, 78, "古馬で堅実", ["短距離の速力勝負は忙しい"], turf=15, dirt=90, sprint=45, mile=76, middle=84, long=62, fukushima=82, hakodate=82, kokura=82, front=80, stalker=76, closer=48, fast_clock=68, power=88, stamina_type=82, notes=["ダート中距離", "先行持続", "パワー"]),
    "アジアエクスプレス": profile("アジアエクスプレス", (1200, 1800), ["良", "稍重", "重"], ["ダート"], 70, 70, 76, "早めから動ける", ["芝では決め手不足に注意"], turf=25, dirt=86, sprint=80, mile=78, middle=62, long=35, fukushima=78, hakodate=78, kokura=80, front=82, stalker=72, closer=45, fast_clock=76, power=78, stamina_type=68, notes=["ダート短距離マイル", "先行", "パワー"]),
    "ディープインパクト": profile("ディープインパクト", (1600, 2400), ["良", "稍重"], ["芝"], 90, 76, 54, "完成度と成長力の両方", ["重い馬場では切れ味を削がれることがある"], turf=95, dirt=25, sprint=55, mile=88, middle=90, long=78, fukushima=68, hakodate=66, kokura=70, front=56, stalker=76, closer=86, fast_clock=92, power=54, stamina_type=76, notes=["瞬発力", "芝", "高速馬場"]),
    "ハーツクライ": profile("ハーツクライ", (1800, 2500), ["良", "稍重"], ["芝"], 70, 86, 60, "晩成傾向", ["短距離の速い流れでは忙しい場合がある"], turf=88, dirt=35, sprint=30, mile=62, middle=88, long=86, fukushima=72, hakodate=74, kokura=70, front=54, stalker=72, closer=76, fast_clock=72, power=68, stamina_type=88, notes=["中長距離", "成長力", "持続力"]),
}


BLOODLINE_PROFILES.update(
    {
        "ミッキーアイル": profile("ミッキーアイル", (1200, 1600), ["良", "稍重"], ["芝"], 82, 58, 55, "早めから完成", ["距離延長では折り合いと持続力に注意"], turf=84, dirt=42, sprint=88, mile=78, middle=45, long=20, fukushima=78, hakodate=76, kokura=82, front=82, stalker=72, closer=48, fast_clock=86, power=60, stamina_type=48, notes=["短距離", "スピード", "先行"]),
        "ダノンバラード": profile("ダノンバラード", (1600, 2200), ["稍重", "重"], ["芝"], 62, 76, 76, "標準", ["高速瞬発戦では切れ負けに注意"], turf=74, dirt=35, sprint=35, mile=68, middle=78, long=62, fukushima=82, hakodate=78, kokura=78, front=62, stalker=72, closer=66, fast_clock=56, power=80, stamina_type=76, notes=["小回り", "道悪", "持続力"]),
        "デクラレーションオブウォー": profile("デクラレーションオブウォー", (1200, 2000), ["良", "稍重", "重"], ["芝", "ダート"], 68, 72, 74, "標準", ["極端な瞬発戦では注意"], turf=66, dirt=70, sprint=70, mile=74, middle=68, long=42, fukushima=76, hakodate=76, kokura=76, front=74, stalker=70, closer=54, fast_clock=66, power=78, stamina_type=70, notes=["パワー", "芝ダート", "先行"]),
        "ラブリーデイ": profile("ラブリーデイ", (1600, 2200), ["良", "稍重"], ["芝"], 68, 74, 62, "標準", ["一線級の切れ味勝負では注意"], turf=76, dirt=42, sprint=45, mile=70, middle=78, long=58, fukushima=74, hakodate=72, kokura=74, front=64, stalker=72, closer=62, fast_clock=70, power=66, stamina_type=72, notes=["中距離", "立ち回り", "持続力"]),
        "ニューイヤーズデイ": profile("ニューイヤーズデイ", (1400, 2000), ["良", "稍重", "重"], ["ダート", "芝"], 66, 74, 76, "標準", ["芝の速い上がり勝負では注意"], turf=55, dirt=78, sprint=62, mile=74, middle=72, long=48, fukushima=76, hakodate=76, kokura=76, front=76, stalker=72, closer=48, fast_clock=66, power=80, stamina_type=74, notes=["パワー", "ダート", "先行"]),
        "フィエールマン": profile("フィエールマン", (1800, 3000), ["良", "稍重"], ["芝"], 74, 90, 62, "成長力あり", ["短距離や小回りの忙しい流れは注意"], turf=86, dirt=25, sprint=20, mile=55, middle=82, long=92, fukushima=68, hakodate=70, kokura=66, front=50, stalker=70, closer=78, fast_clock=76, power=62, stamina_type=92, notes=["長距離", "スタミナ", "末脚"]),
        "サートゥルナーリア": profile("サートゥルナーリア", (1600, 2400), ["良", "稍重"], ["芝"], 82, 78, 60, "成長力あり", ["気性面で力を出し切れない場合に注意"], turf=88, dirt=35, sprint=45, mile=78, middle=88, long=72, fukushima=72, hakodate=70, kokura=72, front=66, stalker=78, closer=72, fast_clock=84, power=68, stamina_type=76, notes=["芝中距離", "瞬発力", "総合力"]),
        "ハービンジャー": BLOODLINE_PROFILES["ハービンジャー"],
        "ニューイヤーズデイ": profile("ニューイヤーズデイ", (1400, 2000), ["良", "稍重", "重"], ["ダート", "芝"], 66, 74, 76, "標準", ["芝の速い上がり勝負では注意"], turf=55, dirt=78, sprint=62, mile=74, middle=72, long=48, fukushima=76, hakodate=76, kokura=76, front=76, stalker=72, closer=48, fast_clock=66, power=80, stamina_type=74, notes=["パワー", "ダート", "先行"]),
        "ブリックスアンドモルタル": profile("ブリックスアンドモルタル", (1400, 2200), ["良", "稍重"], ["芝"], 72, 74, 62, "標準から成長力あり", ["日本の高速決着では適性確認"], turf=78, dirt=42, sprint=60, mile=76, middle=76, long=55, fukushima=72, hakodate=72, kokura=72, front=66, stalker=74, closer=66, fast_clock=70, power=72, stamina_type=72, notes=["芝マイル中距離", "パワー", "持続力"]),
        "ナダル": profile("ナダル", (1200, 1800), ["良", "稍重", "重"], ["ダート", "芝"], 70, 72, 78, "早めから動ける", ["芝の切れ味勝負は未知数"], turf=45, dirt=84, sprint=76, mile=78, middle=62, long=35, fukushima=78, hakodate=78, kokura=80, front=82, stalker=72, closer=45, fast_clock=74, power=82, stamina_type=70, notes=["ダート", "先行", "パワー"]),
        "マインドユアビスケッツ": profile("マインドユアビスケッツ", (1200, 1800), ["良", "稍重", "重"], ["ダート"], 72, 68, 76, "早めから動ける", ["芝では決め手に注意"], turf=35, dirt=84, sprint=80, mile=76, middle=58, long=32, fukushima=78, hakodate=78, kokura=80, front=80, stalker=70, closer=46, fast_clock=78, power=78, stamina_type=66, notes=["ダート短距離", "先行", "スピード"]),
        "イスラボニータ": profile("イスラボニータ", (1200, 1800), ["良", "稍重"], ["芝"], 78, 66, 58, "標準", ["長距離や消耗戦では注意"], turf=82, dirt=38, sprint=72, mile=82, middle=62, long=28, fukushima=74, hakodate=72, kokura=76, front=68, stalker=76, closer=66, fast_clock=82, power=60, stamina_type=62, notes=["マイル", "瞬発力", "立ち回り"]),
        "サトノクラウン": profile("サトノクラウン", (1800, 2400), ["稍重", "重", "不良"], ["芝"], 62, 82, 86, "成長力あり", ["軽い高速馬場では切れ負け注意"], turf=78, dirt=35, sprint=28, mile=55, middle=82, long=78, fukushima=78, hakodate=84, kokura=76, front=58, stalker=70, closer=70, fast_clock=48, power=88, stamina_type=84, notes=["道悪", "パワー", "中距離"]),
        "オルフェーヴル": profile("オルフェーヴル", (1600, 2600), ["稍重", "重", "不良"], ["芝", "ダート"], 68, 86, 88, "成長力あり", ["気性面とムラに注意"], turf=82, dirt=62, sprint=35, mile=65, middle=84, long=82, fukushima=80, hakodate=84, kokura=78, front=58, stalker=72, closer=72, fast_clock=56, power=90, stamina_type=88, notes=["道悪", "スタミナ", "パワー"]),
        "マジェスティックウォリアー": profile("マジェスティックウォリアー", (1400, 1900), ["良", "稍重", "重"], ["ダート"], 62, 76, 78, "標準", ["芝替わりは割引"], turf=18, dirt=88, sprint=65, mile=80, middle=74, long=45, fukushima=82, hakodate=82, kokura=82, front=80, stalker=74, closer=44, fast_clock=72, power=84, stamina_type=76, notes=["ダート中距離", "先行", "パワー"]),
        "ダイワメジャー": profile("ダイワメジャー", (1200, 1800), ["良", "稍重"], ["芝"], 78, 66, 60, "完成度高い", ["距離延長や消耗戦は注意"], turf=84, dirt=42, sprint=82, mile=84, middle=58, long=25, fukushima=78, hakodate=78, kokura=82, front=82, stalker=72, closer=46, fast_clock=82, power=70, stamina_type=60, notes=["短距離マイル", "先行", "パワー"]),
        "Kingman": profile("Kingman", (1200, 1800), ["良", "稍重"], ["芝"], 86, 62, 55, "完成度高い", ["距離延長と重馬場は確認"], turf=88, dirt=25, sprint=78, mile=90, middle=58, long=20, fukushima=68, hakodate=66, kokura=72, front=62, stalker=76, closer=76, fast_clock=90, power=58, stamina_type=56, notes=["マイル", "瞬発力", "高速馬場"]),
        "Frankel": profile("Frankel", (1400, 2200), ["良", "稍重"], ["芝"], 86, 76, 60, "高い成長力", ["日本の小回りでは器用さ確認"], turf=92, dirt=20, sprint=65, mile=90, middle=82, long=62, fukushima=66, hakodate=68, kokura=66, front=64, stalker=78, closer=78, fast_clock=88, power=66, stamina_type=76, notes=["芝", "瞬発力", "底力"]),
        "American Pharoah": profile("American Pharoah", (1200, 2000), ["良", "稍重", "重"], ["ダート", "芝"], 74, 76, 76, "標準", ["芝の瞬発戦では相手次第"], turf=55, dirt=84, sprint=72, mile=80, middle=72, long=45, fukushima=78, hakodate=78, kokura=80, front=82, stalker=72, closer=46, fast_clock=78, power=82, stamina_type=74, notes=["ダート", "先行", "スピード"]),
    }
)


BLOODLINE_PROFILES["ジャスタウェイ"] = profile(
    "ジャスタウェイ",
    (1600, 2400),
    ["良", "稍重"],
    ["芝"],
    76,
    80,
    60,
    "古馬で良化しやすい",
    ["短距離の速い流れでは忙しい場合がある"],
    turf=84,
    dirt=38,
    sprint=35,
    mile=76,
    middle=86,
    long=74,
    fukushima=72,
    hakodate=72,
    kokura=70,
    front=56,
    stalker=72,
    closer=76,
    fast_clock=76,
    power=66,
    stamina_type=82,
    notes=["芝中距離", "持続力", "差し"],
)


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
