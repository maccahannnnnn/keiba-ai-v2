from dataclasses import dataclass


@dataclass
class CourseProfile:
    """競馬場・距離・芝/ダートごとのコース特徴です。"""

    racecourse: str
    surface: str
    distance: int
    features: list[str]
    favorable_styles: list[str]
    frame_bias: str
    required_abilities: list[str]
    cautions: list[str]

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
        frame_bias="極端な枠有利は小さめだが、スムーズに運べる枠を評価",
        required_abilities=["瞬発力", "トップスピード", "直線での加速力"],
        cautions=["スローだと前残りに注意"],
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
    ),
}
"""コース辞書本体です。

データを増やすときは、同じ形式で
("競馬場", "芝またはダート", 距離): CourseProfile(...)
を追加します。
"""


def get_course_profile(racecourse: str, surface: str, distance: int) -> CourseProfile:
    """競馬場・芝/ダート・距離からコース特徴を取得します。"""

    key = (racecourse, surface, distance)
    return COURSE_PROFILES.get(key, DEFAULT_COURSE_PROFILE)
