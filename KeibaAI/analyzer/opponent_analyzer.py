from dataclasses import dataclass

from analyzer.schemas import PastRace, TodayEntry
from knowledge.opponent_profiles import get_opponent_level, normalize_class_name


@dataclass
class OpponentEvaluation:
    """1頭分の相手関係評価です。

    平均・最高・直近・推移を分けて持つことで、将来の機械学習にも使いやすくします。
    """

    horse_name: str
    average_level: float
    highest_level: int
    latest_level: int
    trend: str
    score: float
    reason: str
    member_comparison: str

    def to_features(self) -> dict[str, float]:
        """機械学習に渡しやすい数値へ変換します。"""

        trend_value = {"上昇": 1.0, "維持": 0.0, "下降": -1.0}.get(self.trend, 0.0)
        return {
            "opponent_average_level": self.average_level,
            "opponent_highest_level": float(self.highest_level),
            "opponent_latest_level": float(self.latest_level),
            "opponent_trend": trend_value,
            "opponent_score": self.score,
        }


def analyze_opponents(
    entries: list[TodayEntry],
    past_by_horse: dict[str, list[PastRace]],
) -> dict[str, OpponentEvaluation]:
    """全頭の相手関係を分析し、今回メンバー平均との差も計算します。"""

    evaluations: dict[str, OpponentEvaluation] = {}

    for entry in entries:
        evaluations[entry.horse_name] = analyze_single_opponent(
            entry,
            past_by_horse.get(entry.horse_name, []),
        )

    averages = [
        evaluation.average_level
        for evaluation in evaluations.values()
        if evaluation.average_level > 0
    ]
    member_average = sum(averages) / len(averages) if averages else 0.0

    for evaluation in evaluations.values():
        evaluation.member_comparison = compare_with_member_level(
            evaluation.average_level,
            member_average,
        )
        evaluation.reason += f" / 今回メンバー平均{member_average:.1f}点との比較: {evaluation.member_comparison}"

    return evaluations


def analyze_single_opponent(entry: TodayEntry, past_races: list[PastRace]) -> OpponentEvaluation:
    """1頭の過去レースから相手レベルを評価します。"""

    if not past_races:
        if entry.class_level != "不明":
            level = get_opponent_level(entry.class_level)
            class_name = normalize_class_name(entry.class_level)
            return OpponentEvaluation(
                horse_name=entry.horse_name,
                average_level=float(level),
                highest_level=level,
                latest_level=level,
                trend="維持",
                score=clamp(level),
                reason=f"today_entries.csv の class_level={class_name} を相手レベルとして仮評価",
                member_comparison="未計算",
            )

        return OpponentEvaluation(
            horse_name=entry.horse_name,
            average_level=0.0,
            highest_level=0,
            latest_level=0,
            trend="不明",
            score=40.0,
            reason="過去レースのクラス情報がないため仮評価",
            member_comparison="比較不可",
        )

    levels = [get_opponent_level(race.class_level) for race in past_races]
    class_names = [normalize_class_name(race.class_level) for race in past_races]

    average_level = sum(levels) / len(levels)
    highest_level = max(levels)
    latest_level = levels[0]
    trend = judge_trend(levels)
    trend_bonus = {"上昇": 6, "維持": 2, "下降": -6}.get(trend, 0)

    # 平均相手レベルを中心に、最高レベル・直近レベル・推移を加味します。
    score = average_level * 0.5 + highest_level * 0.2 + latest_level * 0.2 + trend_bonus
    reason = (
        f"過去クラス: {' → '.join(reversed(class_names))} / "
        f"平均{average_level:.1f}点 / 最高{highest_level}点 / "
        f"直近{latest_level}点 / 推移{trend}"
    )

    return OpponentEvaluation(
        horse_name=entry.horse_name,
        average_level=round(average_level, 1),
        highest_level=highest_level,
        latest_level=latest_level,
        trend=trend,
        score=clamp(score),
        reason=reason,
        member_comparison="未計算",
    )


def judge_trend(levels: list[int]) -> str:
    """相手レベルの推移を判定します。

    `levels[0]` が直近、`levels[-1]` が最も古いレースです。
    古いレースから見て直近が上がっていれば「上昇」とします。
    """

    if len(levels) < 2:
        return "維持"

    latest_level = levels[0]
    oldest_level = levels[-1]

    if latest_level >= oldest_level + 8:
        return "上昇"
    if latest_level <= oldest_level - 8:
        return "下降"
    return "維持"


def compare_with_member_level(average_level: float, member_average: float) -> str:
    """今回メンバー全体の平均相手レベルと比較します。"""

    if average_level <= 0 or member_average <= 0:
        return "比較不可"

    difference = average_level - member_average
    if difference >= 5:
        return f"今回メンバー平均より高い(+{difference:.1f}点)"
    if difference <= -5:
        return f"今回メンバー平均より低い({difference:.1f}点)"
    return f"今回メンバー平均とほぼ同等({difference:+.1f}点)"


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    """点数を0〜100点に収めます。"""

    return round(max(minimum, min(maximum, value)), 1)
