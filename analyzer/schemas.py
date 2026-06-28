from dataclasses import dataclass
from datetime import datetime


@dataclass
class ScoreDetail:
    """分析項目1つ分の点数と理由です。"""

    score: float
    reason: str


@dataclass
class PastRace:
    """過去レース1走分のデータです。"""

    race_date: datetime
    race_id: str
    horse_name: str
    jockey: str
    distance: int
    track_condition: str
    field_size: int
    class_level: str
    popularity: int
    finish_position: int
    corner_positions: str
    running_style: str
    pace: str
    body_weight: int
    body_weight_diff: int
    sire: str
    dam_sire: str


@dataclass
class TodayEntry:
    """今回出走する馬のデータです。

    JRAの出走表を見ながら、手入力またはCSV入力しやすい項目にしています。
    """

    race_date: str
    racecourse: str
    race_number: int
    surface: str
    horse_name: str
    horse_number: int
    frame_number: int
    jockey: str
    distance: int
    track_condition: str
    weight: float
    body_weight: int
    body_weight_diff: int
    running_style: str
    last_runs: str
    past_lap_note: str
    expected_lap_note: str
    sire: str
    dam_sire: str
    bloodline_note: str
    class_level: str = "不明"


@dataclass
class AnalysisResult:
    """1頭分の分析結果です。将来はこのデータを機械学習にも使えます。"""

    horse_name: str
    horse_number: int
    frame_number: int
    race_info: str
    past_run_analysis: str
    opponent_level: str
    running_style: str
    distance_fitness: str
    track_fitness: str
    pedigree: str
    body_weight: str
    pace_forecast: str
    score: float
    in_the_money_rate: float
    in_the_money_score: float
    item_scores: dict[str, ScoreDetail]
    pace_analysis: object
    bloodline_analysis: object
    integrated_evaluation: object
    opponent_analysis: object
    track_bias_analysis: object
    lap_analysis: object
    explain_analysis: object = None

    def to_features(self) -> dict[str, float]:
        """将来、機械学習に渡す数値データを作るための入口です。"""

        features = {
            "score": self.score,
            "in_the_money_rate": self.in_the_money_rate,
            "in_the_money_score": self.in_the_money_score,
        }

        # 項目別スコアも特徴量として使えるようにします。
        for name, detail in self.item_scores.items():
            features[f"{name}_score"] = detail.score

        # 統合評価エンジンの補正結果も特徴量として使えるようにします。
        if self.integrated_evaluation:
            features.update(self.integrated_evaluation.to_features())

        # 相手関係評価も、後で機械学習に渡せる数値として追加します。
        if self.opponent_analysis:
            features.update(self.opponent_analysis.to_features())

        # 馬場バイアスもレース条件の特徴量として追加します。
        if self.track_bias_analysis:
            features.update(self.track_bias_analysis.to_features())

        # ラップ分析もレース質の特徴量として追加します。
        if self.lap_analysis:
            features.update(self.lap_analysis.to_features())

        # Explain Engine は、文章ではなく reason_id などの構造化データだけを保存します。
        if self.explain_analysis:
            features.update(self.explain_analysis.to_features())

        return features
