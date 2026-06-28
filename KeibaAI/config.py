ANALYSIS_RULES = [
    "過去走分析",
    "相手関係",
    "通過順・脚質",
    "距離適性",
    "馬場",
    "血統",
    "馬体重",
    "展開予想",
    "全頭評価",
    "3着内率",
]
"""中央競馬分析AIが使う分析ルールです。

分析の順番を変えたいときは、まずこのリストを編集します。
各プログラムはここを読み込むので、ルールを一か所で管理できます。
"""


DESIGN_PIPELINE = [
    "JRA出走表",
    "データ取得",
    "過去走取得",
    "展開分析",
    "馬場分析",
    "血統分析",
    "相手関係分析",
    "総合評価",
    "将来的に機械学習",
]
"""この競馬AIの設計思想です。

開発を進めるときは、この流れを崩さないようにします。
今は自動取得や機械学習はまだ行わず、HTML/CSV入力から分析できる土台を作っています。
"""


PAST_RUN_LIMIT = 5
"""過去走を何走分見るかを決める設定です。

今は5走を見ます。
将来は `10` にすれば過去10走、`"all"` にすれば取得できた全過去走を使う設計です。
"""


ANALYSIS_WEIGHTS = {
    "past_run": 20,
    "opponent": 20,
    "pace": 20,
    "lap": 15,
    "track_bias": 10,
    "course": 5,
    "distance": 10,
    "bloodline": 5,
    "body_weight": 5,
}
"""分析項目ごとの重みです。

数値そのものよりも「ここで一元管理する」ことが重要です。
将来、コース別・競馬場別・レース別・馬場別に変えたい場合は、
この設定をもとに専用プロファイルを増やしていきます。
"""


WEIGHT_PROFILES = {
    "default": ANALYSIS_WEIGHTS,
}
"""重みプロファイルです。

今は default だけですが、将来は以下のように増やせます。
例:
`tokyo_turf_1600`: 東京芝1600m用
`heavy_track`: 道悪用
`sprint`: 短距離用
"""


SCORE_ITEM_WEIGHT_KEYS = {
    "過去走分析": "past_run",
    "相手関係": "opponent",
    "通過順・脚質": "pace",
    "距離適性": "distance",
    "馬場": "track_bias",
    "血統": "bloodline",
    "馬体重": "body_weight",
    "展開予想": "pace",
    "ラップ適性": "lap",
}
"""日本語の分析項目と、重みキーをつなぐ設定です。"""


WEIGHT_LABELS = {
    "past_run": "過去走",
    "opponent": "相手関係",
    "pace": "展開",
    "lap": "ラップ",
    "track_bias": "馬場バイアス",
    "course": "コース",
    "distance": "距離",
    "bloodline": "血統",
    "body_weight": "馬体重",
}
"""レポート表示用の重み名です。"""


INTEGRATED_RULE_WEIGHTS = {
    "pace_course": ("pace", "course"),
    "pace_course_bloodline": ("pace", "course", "bloodline"),
    "distance_bloodline": ("distance", "bloodline"),
    "track_bloodline": ("track_bias", "bloodline"),
    "lap_pace": ("lap", "pace"),
    "lap_course_track": ("lap", "course", "track_bias"),
    "past_opponent": ("past_run", "opponent"),
    "pace_bad_track": ("pace", "track_bias"),
    "course_bad_distance": ("course", "distance"),
    "bloodline_bad_body": ("bloodline", "body_weight"),
    "track_bad_bloodline": ("track_bias", "bloodline"),
    "pace_bad_lap": ("pace", "lap"),
    "bad_lap_style": ("lap",),
    "past_bad_opponent": ("past_run", "opponent"),
}
"""統合評価で使う補正ルールと、参照する重みキーです。"""


ANALYSIS_CRITERIA = {
    "過去走分析": [
        "着順の安定感",
        "3着以内に入った回数",
        "大きく負けたレースがあるか",
        "近走で調子が上がっているか",
    ],
    "相手関係": [
        "これまで戦ってきた相手の強さ",
        "同じクラスや上のクラスで通用しているか",
        "近走の着順が相手の強さを考えて評価できるか",
    ],
    "通過順・脚質": [
        "逃げ、先行、差し、追込のどのタイプか",
        "前走や近走の通過順",
        "今回のメンバー構成に脚質が合うか",
        "自分の形で競馬ができそうか",
    ],
    "距離適性": [
        "今回と同じ距離での成績",
        "近い距離での好走歴",
        "距離短縮や距離延長がプラスかマイナスか",
    ],
    "馬場": [
        "良、稍重、重、不良などの馬場状態への適性",
        "芝またはダートへの適性",
        "当日の馬場傾向に合う脚質か",
    ],
    "血統": [
        "父や母父から見た距離適性",
        "芝、ダート、道悪などへの適性",
        "成長力や底力がありそうか",
        "血統メモに不安材料があるか",
    ],
    "馬体重": [
        "今回の馬体重",
        "前走からの増減",
        "過去の平均馬体重との比較",
        "大きな増減が不安材料にならないか",
    ],
    "展開予想": [
        "逃げ、先行馬の頭数",
        "想定ペースがスロー、ミドル、ハイのどれになりそうか",
        "その展開が各馬の脚質に合うか",
        "展開利または展開不利がありそうか",
    ],
}
"""分析項目ごとの評価基準です。

AIが「何を見て評価するのか」をここにまとめます。
将来、分析項目を追加した場合は、`ANALYSIS_RULES` に項目名を追加し、
必要であればこの辞書にも同じ項目名で評価基準を追加します。
"""
