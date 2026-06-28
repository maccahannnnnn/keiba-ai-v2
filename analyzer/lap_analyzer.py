import re
from dataclasses import dataclass

from analyzer.schemas import ScoreDetail, TodayEntry


@dataclass
class LapHorseEvaluation:
    """1頭ごとのラップ適性です。"""

    horse_number: int
    horse_name: str
    running_style: str
    score: float
    reason: str


@dataclass
class LapAnalysis:
    """レース全体のラップ分析です。"""

    front_3f: float | None
    late_3f: float | None
    half_difference: float | None
    pace: str
    race_type: str
    favorable_styles: list[str]
    reason: str
    horse_evaluations: dict[str, LapHorseEvaluation]

    def to_features(self) -> dict[str, float]:
        """将来、機械学習へ渡しやすい数値へ変換します。"""

        return {
            "lap_front_3f": self.front_3f or 0.0,
            "lap_late_3f": self.late_3f or 0.0,
            "lap_half_difference": self.half_difference or 0.0,
            "lap_pace": {"スロー": 0.0, "平均": 1.0, "ハイ": 2.0}.get(self.pace, 1.0),
            "lap_race_type": {"瞬発戦": 0.0, "持続戦": 1.0, "消耗戦": 2.0}.get(self.race_type, 1.0),
        }


def analyze_lap(entries: list[TodayEntry]) -> LapAnalysis:
    """今回想定されるラップを分析します。

    今は `expected_lap_note` のメモや簡単な数値から判定します。
    将来、実際のラップタイムCSVを読む場合も、この関数の入口へ流し込めます。
    """

    expected_note = first_non_empty(entry.expected_lap_note for entry in entries)
    front_3f, late_3f = parse_lap_note(expected_note)
    pace = judge_pace(front_3f, late_3f, expected_note)
    race_type = judge_race_type(front_3f, late_3f, expected_note)
    half_difference = calculate_half_difference(front_3f, late_3f)
    favorable_styles = decide_favorable_styles(race_type, pace)
    reason = build_lap_reason(front_3f, late_3f, half_difference, pace, race_type, expected_note)

    horse_evaluations = {
        entry.horse_name: evaluate_horse_lap(entry, race_type, pace, favorable_styles)
        for entry in entries
    }

    return LapAnalysis(
        front_3f=front_3f,
        late_3f=late_3f,
        half_difference=half_difference,
        pace=pace,
        race_type=race_type,
        favorable_styles=favorable_styles,
        reason=reason,
        horse_evaluations=horse_evaluations,
    )


def parse_lap_note(note: str) -> tuple[float | None, float | None]:
    """ラップメモから前半3Fと後半3Fを取り出します。

    例:
    - `前半34.5 後半36.0`
    - `前半3F:35.8 後半3F:34.2`
    """

    front = find_lap_value(note, ["前半3F", "前半"])
    late = find_lap_value(note, ["後半3F", "後半", "上がり"])
    return front, late


def find_lap_value(note: str, labels: list[str]) -> float | None:
    """指定したラベルの近くにある小数を探します。"""

    for label in labels:
        pattern = rf"{label}\s*[:：]?\s*(\d{{2}}\.\d)"
        match = re.search(pattern, note)
        if match:
            return float(match.group(1))
    return None


def calculate_half_difference(front_3f: float | None, late_3f: float | None) -> float | None:
    """前半3F - 後半3F を計算します。プラスなら後半が速い形です。"""

    if front_3f is None or late_3f is None:
        return None
    return round(front_3f - late_3f, 1)


def judge_pace(front_3f: float | None, late_3f: float | None, note: str) -> str:
    """前半3Fとメモからペースを判定します。"""

    if "ハイ" in note or "前半速" in note or "前半が速" in note:
        return "ハイ"
    if "スロー" in note or "前半遅" in note or "前半が遅" in note:
        return "スロー"

    if front_3f is None:
        return "平均"
    if front_3f <= 34.5:
        return "ハイ"
    if front_3f >= 36.0:
        return "スロー"
    return "平均"


def judge_race_type(front_3f: float | None, late_3f: float | None, note: str) -> str:
    """前後半差やメモからレース質を判定します。"""

    if "瞬発" in note or "上がり勝負" in note:
        return "瞬発戦"
    if "消耗" in note or "後半掛" in note or "後半が掛" in note:
        return "消耗戦"
    if "持続" in note or "ロングスパート" in note:
        return "持続戦"

    if front_3f is None or late_3f is None:
        return "持続戦"

    difference = front_3f - late_3f
    if difference >= 1.0:
        return "瞬発戦"
    if difference <= -1.0:
        return "消耗戦"
    return "持続戦"


def decide_favorable_styles(race_type: str, pace: str) -> list[str]:
    """レース質から有利になりやすい脚質を決めます。"""

    if race_type == "瞬発戦":
        return ["先行", "差し"]
    if race_type == "消耗戦":
        return ["差し", "追込"]
    if pace == "スロー":
        return ["逃げ", "先行"]
    return ["先行", "差し"]


def evaluate_horse_lap(
    entry: TodayEntry,
    race_type: str,
    pace: str,
    favorable_styles: list[str],
) -> LapHorseEvaluation:
    """各馬の脚質と過去ラップメモから、ラップ適性を評価します。"""

    score = 55.0
    reasons: list[str] = []

    if entry.running_style in favorable_styles:
        score += 20
        reasons.append(f"{race_type}で{entry.running_style}が有利脚質")
    else:
        score -= 5
        reasons.append(f"{race_type}では{entry.running_style}が中心ではない")

    note = entry.past_lap_note
    if race_type in note:
        score += 15
        reasons.append(f"過去ラップメモに{race_type}への適性")
    if pace in note:
        score += 8
        reasons.append(f"過去ラップメモに{pace}ペース経験")
    if any(word in note for word in ["苦手", "不安", "割引"]):
        score -= 12
        reasons.append("過去ラップメモに不安材料")
    if not note:
        reasons.append("過去ラップメモなし")

    return LapHorseEvaluation(
        horse_number=entry.horse_number,
        horse_name=entry.horse_name,
        running_style=entry.running_style,
        score=clamp(score),
        reason="、".join(reasons),
    )


def lap_score_detail(entry: TodayEntry, lap_analysis: LapAnalysis) -> ScoreDetail:
    """score_calculator.py で使いやすい形に変換します。"""

    evaluation = lap_analysis.horse_evaluations[entry.horse_name]
    return ScoreDetail(evaluation.score, evaluation.reason)


def build_lap_reason(
    front_3f: float | None,
    late_3f: float | None,
    half_difference: float | None,
    pace: str,
    race_type: str,
    note: str,
) -> str:
    """レポート用の説明文を作ります。"""

    if front_3f is None or late_3f is None:
        return f"数値ラップ未入力のためメモから判定。想定ペース{pace}、レース質{race_type}。メモ: {note or 'なし'}"
    return (
        f"前半3F{front_3f:.1f}秒、後半3F{late_3f:.1f}秒、"
        f"前後半差{half_difference:+.1f}秒から、想定ペース{pace}、レース質{race_type}と判定"
    )


def first_non_empty(values) -> str:
    """最初に見つかった空でない文字列を返します。"""

    for value in values:
        if value:
            return value
    return ""


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    """点数を0〜100点に収めます。"""

    return round(max(minimum, min(maximum, value)), 1)
