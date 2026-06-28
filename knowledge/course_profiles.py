from dataclasses import dataclass, field


@dataclass
class CourseProfile:
    """競馬場・距離・芝/ダートごとのコース特徴です。

    Analyzer が現在使っている主な項目は features / favorable_styles /
    frame_bias / required_abilities / cautions です。
    それ以外の項目は、将来レポートや機械学習用特徴量へ広げるための知識として
    ここに蓄積しておきます。
    """

    racecourse: str
    surface: str
    distance: int
    features: list[str]
    favorable_styles: list[str]
    frame_bias: str
    required_abilities: list[str]
    cautions: list[str]
    course_shape: str = "不明"
    pace_tendency: str = "不明"
    closing_tendency: str = "不明"
    suitable_types: list[str] = field(default_factory=list)
    unsuitable_types: list[str] = field(default_factory=list)
    bloodline_tendency: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """レポートに表示しやすい短い説明を作ります。"""

        return " / ".join(self.features)


DEFAULT_COURSE_PROFILE = CourseProfile(
    racecourse="不明",
    surface="不明",
    distance=0,
    features=["コース辞書に未登録"],
    favorable_styles=["先行", "差し"],
    frame_bias="枠順傾向は未設定",
    required_abilities=["総合力"],
    cautions=["該当コースをcourse_profiles.pyに追加してください"],
)
"""未登録コース用の仮プロフィールです。"""


COURSE_PROFILES = {
    ("東京", "芝", 1600): CourseProfile(
        racecourse="東京",
        surface="芝",
        distance=1600,
        features=["直線が長い", "瞬発力が重要", "差しも届きやすい"],
        favorable_styles=["差し", "先行"],
        frame_bias="極端な枠有利は少なめだが、スムーズに運べる枠を評価",
        required_abilities=["瞬発力", "トップスピード", "直線での加速力"],
        cautions=["スローだと前残りに注意"],
        course_shape="ワンターンの芝マイル。直線が長く、坂を含む末脚勝負になりやすい",
        pace_tendency="平均からスロー寄りになりやすいが、メンバー次第で差し決着も多い",
        closing_tendency="速い上がりを使える馬を評価",
        suitable_types=["長く脚を使える差し馬", "折り合える先行馬"],
        unsuitable_types=["直線の瞬発力に欠ける馬", "一本調子の逃げ馬"],
        bloodline_tendency=["ディープインパクト系", "キングマンボ系", "欧州型の持続力血統"],
    ),
    ("東京", "芝", 1800): CourseProfile(
        racecourse="東京",
        surface="芝",
        distance=1800,
        features=["直線が長い", "切れ味が問われやすい", "コーナーまでの入りも重要"],
        favorable_styles=["差し", "先行"],
        frame_bias="内で包まれない立ち回りを評価",
        required_abilities=["瞬発力", "持続力", "折り合い"],
        cautions=["スローの上がり勝負では前も残りやすい"],
        course_shape="ワンターンに近い芝1800m。直線の長さを活かした末脚勝負になりやすい",
        pace_tendency="スローから平均になりやすい",
        closing_tendency="上がり性能が結果に直結しやすい",
        suitable_types=["瞬発力型", "中団で折り合える馬"],
        unsuitable_types=["小回り専用型", "急加速に対応しづらい馬"],
        bloodline_tendency=["ディープインパクト系", "ハーツクライ系", "ロードカナロア系"],
    ),
    ("阪神", "芝", 2200): CourseProfile(
        racecourse="阪神",
        surface="芝",
        distance=2200,
        features=["内回り", "持続力とロングスパートが重要", "早めに動ける馬を評価"],
        favorable_styles=["先行", "差し"],
        frame_bias="内で立ち回れる馬をやや評価",
        required_abilities=["持続力", "ロングスパート", "コーナーでの加速力"],
        cautions=["瞬発力だけの馬は取りこぼしに注意"],
        course_shape="内回りの中距離。コーナーで動ける機動力が必要",
        pace_tendency="平均からやや持続戦になりやすい",
        closing_tendency="上がり最速だけでなく長く脚を使えるかを見る",
        suitable_types=["持続力型", "早めに進出できる先行・差し馬"],
        unsuitable_types=["直線だけに賭ける追込馬", "器用さに欠ける大型馬"],
        bloodline_tendency=["ハーツクライ系", "ステイゴールド系", "ロベルト系"],
    ),
}
"""コース辞書本体です。

データを増やすときは、同じ形式で
("競馬場", "芝またはダート", 距離): CourseProfile(...)
を追加します。
"""


COURSE_PROFILES.update(
    {
        ("福島", "芝", 1200): CourseProfile(
            racecourse="福島",
            surface="芝",
            distance=1200,
            features=["小回り", "直線が短い", "スタート後の位置取りが重要"],
            favorable_styles=["逃げ", "先行"],
            frame_bias="内枠でロスなく先行できる馬を評価。開催が進むと外差しにも注意",
            required_abilities=["先行力", "スピード持続力", "コーナー加速"],
            cautions=["後方一気は届きにくい。馬場悪化時は外目の差しに注意"],
            course_shape="2コーナー奥からスタートする小回り芝短距離",
            pace_tendency="前半から流れやすく、先行争いが激しいと差しも届く",
            closing_tendency="極端な瞬発力よりもスピードを持続する上がりが重要",
            suitable_types=["先行力のある短距離馬", "小回りで加速できる馬"],
            unsuitable_types=["スタートが遅い追込馬", "大箱向きの末脚型"],
            bloodline_tendency=["ロードカナロア系", "サクラバクシンオー系", "ミスタープロスペクター系"],
        ),
        ("福島", "芝", 1800): CourseProfile(
            racecourse="福島",
            surface="芝",
            distance=1800,
            features=["小回り", "コーナー4回", "立ち回りと持続力が重要"],
            favorable_styles=["先行", "差し"],
            frame_bias="内で脚をためられる枠を評価。外枠は早めに動ける機動力が必要",
            required_abilities=["持続力", "器用さ", "コーナーでの加速力"],
            cautions=["直線だけの瞬発力勝負にはなりにくい"],
            course_shape="スタンド前から始まる小回り芝中距離",
            pace_tendency="平均ペースになりやすく、早めに動く競馬が増えやすい",
            closing_tendency="長く脚を使う上がりが必要",
            suitable_types=["器用な先行馬", "早めに進出できる差し馬"],
            unsuitable_types=["大外を回すだけの追込馬", "加速に時間がかかる馬"],
            bloodline_tendency=["ステイゴールド系", "ロベルト系", "キングマンボ系"],
        ),
        ("福島", "芝", 2000): CourseProfile(
            racecourse="福島",
            surface="芝",
            distance=2000,
            features=["小回り", "コーナー4回", "早めに動ける持続力が重要"],
            favorable_styles=["先行", "差し"],
            frame_bias="内で立ち回れる馬を評価しつつ、外から早めに動ける馬も注意",
            required_abilities=["持続力", "機動力", "コーナー加速"],
            cautions=["直線だけの瞬発力勝負にはなりにくい"],
            course_shape="小回りの芝2000m。コーナーを4回通る持続力コース",
            pace_tendency="平均からややハイになりやすく、早めの仕掛けが入りやすい",
            closing_tendency="速い上がりよりもバテずに伸びる脚を評価",
            suitable_types=["持続力型", "小回り巧者", "早めに動ける先行・差し馬"],
            unsuitable_types=["直線一気型", "コーナー加速が苦手な馬"],
            bloodline_tendency=["ステイゴールド系", "ハービンジャー系", "ロベルト系"],
        ),
        ("福島", "ダート", 1700): CourseProfile(
            racecourse="福島",
            surface="ダート",
            distance=1700,
            features=["小回りダート", "コーナー4回", "前で運べる馬が有利になりやすい"],
            favorable_styles=["逃げ", "先行"],
            frame_bias="内で砂をかぶらず立ち回れる先行馬を評価。外枠はスムーズに先行できれば可",
            required_abilities=["先行力", "持続力", "砂をかぶる耐性"],
            cautions=["後方から大外を回す競馬はロスが大きい"],
            course_shape="小回りのダート1700m。1コーナーまでの位置取りが重要",
            pace_tendency="前半から位置を取りに行くため平均以上になりやすい",
            closing_tendency="上がりの速さよりも最後まで止まらない持続力を評価",
            suitable_types=["逃げ・先行馬", "器用に立ち回れる馬"],
            unsuitable_types=["揉まれ弱い差し馬", "加速に時間がかかる追込馬"],
            bloodline_tendency=["シニスターミニスター系", "ヘニーヒューズ系", "キングカメハメハ系"],
        ),
        ("函館", "芝", 1200): CourseProfile(
            racecourse="函館",
            surface="芝",
            distance=1200,
            features=["洋芝", "直線が短い", "パワーと先行力が重要"],
            favorable_styles=["逃げ", "先行"],
            frame_bias="内枠でロスなく運べる馬を評価。馬場が荒れると外差しも注意",
            required_abilities=["先行力", "洋芝適性", "パワー"],
            cautions=["軽い芝専用の瞬発型は割引が必要"],
            course_shape="洋芝の小回り短距離。直線が短く前の位置が重要",
            pace_tendency="短距離らしく流れやすいが、前が止まりにくい",
            closing_tendency="切れ味よりも洋芝で踏ん張る上がりが必要",
            suitable_types=["パワー型の先行馬", "洋芝実績のある短距離馬"],
            unsuitable_types=["軽い高速芝向きの差し馬", "スタートが遅い馬"],
            bloodline_tendency=["ロードカナロア系", "ダイワメジャー系", "ノーザンダンサー系"],
        ),
        ("函館", "芝", 1800): CourseProfile(
            racecourse="函館",
            surface="芝",
            distance=1800,
            features=["洋芝", "小回り", "持続力と立ち回りが重要"],
            favorable_styles=["先行", "差し"],
            frame_bias="内で脚をためられる馬を評価。外枠は早めに位置を取れるかが鍵",
            required_abilities=["洋芝適性", "持続力", "器用さ"],
            cautions=["瞬発力だけで差す競馬は決まりにくい"],
            course_shape="コーナー4回の洋芝中距離",
            pace_tendency="平均ペースになりやすく、早めに動く持続戦が多い",
            closing_tendency="上がりの速さよりも長く脚を使う力を評価",
            suitable_types=["洋芝巧者", "先行してしぶとい馬", "持続力型の差し馬"],
            unsuitable_types=["高速上がり専用型", "小回りで置かれる馬"],
            bloodline_tendency=["ハービンジャー系", "ステイゴールド系", "ロベルト系"],
        ),
        ("函館", "芝", 2000): CourseProfile(
            racecourse="函館",
            surface="芝",
            distance=2000,
            features=["洋芝", "コーナー4回", "スタミナと持続力が問われる"],
            favorable_styles=["先行", "差し"],
            frame_bias="内でロスなく運べる馬を評価。外枠は早めに動けるかが重要",
            required_abilities=["スタミナ", "洋芝適性", "持続力"],
            cautions=["軽い瞬発力だけのタイプは過信しない"],
            course_shape="洋芝の小回り芝2000m。コーナーで動く力が必要",
            pace_tendency="平均から持続戦になりやすい",
            closing_tendency="ラストまで脚を使い続ける上がりが重要",
            suitable_types=["持続力型", "パワー型", "早めに動ける馬"],
            unsuitable_types=["直線だけの追込馬", "洋芝で止まりやすい軽量型"],
            bloodline_tendency=["ハービンジャー系", "ハーツクライ系", "ロベルト系"],
        ),
        ("函館", "ダート", 1700): CourseProfile(
            racecourse="函館",
            surface="ダート",
            distance=1700,
            features=["小回りダート", "直線が短い", "先行力と持続力が重要"],
            favorable_styles=["逃げ", "先行"],
            frame_bias="内枠で前に行ける馬を評価。外枠でもスムーズに先行できれば可",
            required_abilities=["先行力", "持続力", "パワー"],
            cautions=["後方待機は展開待ちになりやすい"],
            course_shape="小回りのダート1700m。1コーナーまでの入りが重要",
            pace_tendency="先行争いで流れることもあるが、基本は前有利",
            closing_tendency="速い上がりよりも粘り込み性能を評価",
            suitable_types=["逃げ・先行馬", "砂をかぶっても問題ない馬"],
            unsuitable_types=["追込一辺倒", "揉まれ弱い馬"],
            bloodline_tendency=["ヘニーヒューズ系", "シニスターミニスター系", "ロベルト系"],
        ),
        ("小倉", "芝", 1200): CourseProfile(
            racecourse="小倉",
            surface="芝",
            distance=1200,
            features=["高速決着が出やすい", "下りから流れる", "スピード持続力が重要"],
            favorable_styles=["逃げ", "先行"],
            frame_bias="開幕週は内・先行を評価。馬場が荒れると外差しに注意",
            required_abilities=["テンの速さ", "スピード持続力", "立ち回り"],
            cautions=["前半が速すぎると差しが浮上する"],
            course_shape="芝短距離。スタート後からスピードに乗りやすい",
            pace_tendency="ハイペースになりやすい",
            closing_tendency="速い時計に対応し、最後までスピードを落とさない力が必要",
            suitable_types=["スピード型の逃げ・先行馬", "高速馬場適性のある馬"],
            unsuitable_types=["テンに置かれる馬", "重い芝向きのパワー型"],
            bloodline_tendency=["ロードカナロア系", "サクラバクシンオー系", "ダイワメジャー系"],
        ),
        ("小倉", "芝", 1800): CourseProfile(
            racecourse="小倉",
            surface="芝",
            distance=1800,
            features=["小回り", "コーナー4回", "器用さと持続力が重要"],
            favorable_styles=["先行", "差し"],
            frame_bias="内で立ち回れる馬を評価。外枠は早めに動ける機動力が必要",
            required_abilities=["器用さ", "持続力", "コーナー加速"],
            cautions=["外を回し続けるとロスが大きい"],
            course_shape="小回り芝1800m。コーナリングと位置取りが重要",
            pace_tendency="平均からやや速めになりやすい",
            closing_tendency="瞬発力よりもコーナーから長く脚を使う力を評価",
            suitable_types=["小回り巧者", "先行・中団から動ける馬"],
            unsuitable_types=["大箱向きの追込馬", "不器用な馬"],
            bloodline_tendency=["ステイゴールド系", "キングマンボ系", "ロベルト系"],
        ),
        ("小倉", "芝", 2000): CourseProfile(
            racecourse="小倉",
            surface="芝",
            distance=2000,
            features=["小回り", "コーナー4回", "早めに動く持続戦になりやすい"],
            favorable_styles=["先行", "差し"],
            frame_bias="内でロスなく運べる馬を評価。外枠はまくれる持続力が必要",
            required_abilities=["持続力", "機動力", "スタミナ"],
            cautions=["直線だけで差し切る形は難しい"],
            course_shape="小回り芝2000m。道中から脚を使わされやすい",
            pace_tendency="平均から持続戦になりやすい",
            closing_tendency="上がり最速よりも早めに動いて粘る脚を評価",
            suitable_types=["持続力型", "器用な先行馬", "まくれる差し馬"],
            unsuitable_types=["瞬発力専用型", "後方一気型"],
            bloodline_tendency=["ハーツクライ系", "ステイゴールド系", "ハービンジャー系"],
        ),
        ("小倉", "ダート", 1700): CourseProfile(
            racecourse="小倉",
            surface="ダート",
            distance=1700,
            features=["小回りダート", "先行有利", "早めにポジションを取る力が重要"],
            favorable_styles=["逃げ", "先行"],
            frame_bias="内で砂をかぶらず先行できる馬を評価。外枠はスムーズに被されない利点もある",
            required_abilities=["先行力", "持続力", "コーナーでの器用さ"],
            cautions=["差し馬はペースや馬群の捌きに左右されやすい"],
            course_shape="小回りダート1700m。コーナー4回で立ち回り差が出やすい",
            pace_tendency="先行争いで流れることもあるが、基本は前の組を評価",
            closing_tendency="上がり性能よりも長く脚を使って粘る力が重要",
            suitable_types=["逃げ・先行馬", "小回りダート巧者"],
            unsuitable_types=["後方一気型", "砂をかぶると嫌がる馬"],
            bloodline_tendency=["ヘニーヒューズ系", "シニスターミニスター系", "キングカメハメハ系"],
        ),
    }
)


def get_course_profile(racecourse: str, surface: str, distance: int) -> CourseProfile:
    """競馬場・芝/ダート・距離からコース特徴を取得します。"""

    key = (racecourse, surface, distance)
    return COURSE_PROFILES.get(key, DEFAULT_COURSE_PROFILE)
