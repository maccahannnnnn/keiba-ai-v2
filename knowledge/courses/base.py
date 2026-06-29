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
    score_modifiers: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        """レポートに表示しやすい短い説明を作ります。"""

        return " / ".join(self.features)
