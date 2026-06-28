from dataclasses import dataclass

from config import PAST_RUN_LIMIT
from analyzer.schemas import PastRace, TodayEntry
from knowledge.race_level import get_race_level_profile, get_race_level_score, normalize_race_level_name


@dataclass
class PastOpponentRun:
    """直近走ごとの相手関係評価です。

    現在の PastRace には着差・上がり順位の列がありません。
    将来JRA-VANやTARGET CSVから列が入ったときに使えるよう、
    margin / closing_rank は None を許可して土台だけ作っています。
    """

    class_level: str
    race_level_score: int
    finish_position: int | None
    margin: float | None
    popularity: int | None
    closing_rank: int | None


@dataclass
class OpponentEvaluation:
    """1頭ごとの相手関係評価です。"""

    horse_name: str
    average_level: float
    highest_level: int
    latest_level: int
    trend: str
    score: float
    reason: str
    member_comparison: str
    recent_runs: list[PastOpponentRun]

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
        evaluation.reason += (
            f" / 今回メンバー平均{member_average:.1f}点との比較: "
            f"{evaluation.member_comparison}"
        )

    return evaluations


def analyze_single_opponent(entry: TodayEntry, past_races: list[PastRace]) -> OpponentEvaluation:
    """1頭の直近5走から相手関係を評価します。"""

    recent_races = past_races[:PAST_RUN_LIMIT]
    recent_runs = [build_past_opponent_run(race) for race in recent_races]

    if not recent_runs:
        class_name = normalize_race_level_name(entry.class_level)
        level = get_race_level_score(entry.class_level)
        profile = get_race_level_profile(entry.class_level)
        reason = (
            f"過去走のレースレベル詳細がないため、"
            f"today_entries.csv の class_level={class_name} を仮評価。"
            f"{profile.description}"
        )
        return OpponentEvaluation(
            horse_name=entry.horse_name,
            average_level=float(level),
            highest_level=level,
            latest_level=level,
            trend="維持",
            score=clamp(level),
            reason=reason,
            member_comparison="未計算",
            recent_runs=[],
        )

    levels = [run.race_level_score for run in recent_runs]
    average_level = sum(levels) / len(levels)
    highest_level = max(levels)
    latest_level = levels[0]
    trend = judge_trend(levels)

    class_part = " → ".join(run.class_level for run in reversed(recent_runs))
    score = calculate_opponent_score(recent_runs, trend)
    reason = build_reason_text(recent_runs, average_level, highest_level, latest_level, trend, class_part)

    return OpponentEvaluation(
        horse_name=entry.horse_name,
        average_level=round(average_level, 1),
        highest_level=highest_level,
        latest_level=latest_level,
        trend=trend,
        score=score,
        reason=reason,
        member_comparison="未計算",
        recent_runs=recent_runs,
    )


def build_past_opponent_run(race: PastRace) -> PastOpponentRun:
    """PastRaceから、相手関係評価で使う情報だけを取り出します。"""

    class_name = normalize_race_level_name(race.class_level)
    return PastOpponentRun(
        class_level=class_name,
        race_level_score=get_race_level_score(race.class_level),
        finish_position=safe_int(getattr(race, "finish_position", None)),
        margin=safe_float(getattr(race, "margin", None)),
        popularity=safe_int(getattr(race, "popularity", None)),
        closing_rank=safe_int(getattr(race, "closing_rank", None)),
    )


def calculate_opponent_score(recent_runs: list[PastOpponentRun], trend: str) -> float:
    """直近5走の相手レベル・着順・人気・上がり順位から簡易スコアを出します。"""

    levels = [run.race_level_score for run in recent_runs]
    average_level = sum(levels) / len(levels)
    highest_level = max(levels)
    latest_level = levels[0]

    score = average_level * 0.55 + highest_level * 0.15 + latest_level * 0.15

    finish_bonus = average_finish_bonus(recent_runs)
    popularity_bonus = popularity_bonus_score(recent_runs)
    margin_bonus = margin_bonus_score(recent_runs)
    closing_bonus = closing_rank_bonus_score(recent_runs)
    trend_bonus = {"上昇": 5, "維持": 2, "下降": -5}.get(trend, 0)

    return clamp(score + finish_bonus + popularity_bonus + margin_bonus + closing_bonus + trend_bonus)


def average_finish_bonus(recent_runs: list[PastOpponentRun]) -> float:
    """強い相手に好走しているほど加点します。"""

    positions = [run.finish_position for run in recent_runs if run.finish_position]
    if not positions:
        return 0.0

    average_position = sum(positions) / len(positions)
    if average_position <= 3:
        return 8.0
    if average_position <= 5:
        return 4.0
    if average_position >= 10:
        return -6.0
    return 0.0


def popularity_bonus_score(recent_runs: list[PastOpponentRun]) -> float:
    """人気より走れているかを見るための簡易加点です。"""

    comparisons = [
        run.popularity - run.finish_position
        for run in recent_runs
        if run.popularity and run.finish_position
    ]
    if not comparisons:
        return 0.0

    average = sum(comparisons) / len(comparisons)
    if average >= 2:
        return 4.0
    if average <= -3:
        return -3.0
    return 0.0


def margin_bonus_score(recent_runs: list[PastOpponentRun]) -> float:
    """着差が小さい好走を評価します。現状は列がない場合は0点です。"""

    margins = [run.margin for run in recent_runs if run.margin is not None]
    if not margins:
        return 0.0

    average_margin = sum(margins) / len(margins)
    if average_margin <= 0.3:
        return 5.0
    if average_margin >= 1.5:
        return -5.0
    return 0.0


def closing_rank_bonus_score(recent_runs: list[PastOpponentRun]) -> float:
    """上がり順位が良い馬を評価します。現状は列がない場合は0点です。"""

    ranks = [run.closing_rank for run in recent_runs if run.closing_rank]
    if not ranks:
        return 0.0

    average_rank = sum(ranks) / len(ranks)
    if average_rank <= 3:
        return 4.0
    if average_rank >= 10:
        return -3.0
    return 0.0


def build_reason_text(
    recent_runs: list[PastOpponentRun],
    average_level: float,
    highest_level: int,
    latest_level: int,
    trend: str,
    class_part: str,
) -> str:
    """レポートに表示する相手関係評価の説明文を作ります。"""

    high_classes = [run.class_level for run in recent_runs if run.race_level_score >= 80]
    high_class_text = "、".join(dict.fromkeys(high_classes))
    if high_class_text:
        level_summary = f"過去{len(recent_runs)}走で{high_class_text}を経験しており、相手レベルは高い"
    else:
        level_summary = f"過去{len(recent_runs)}走は{class_part}が中心"

    finish_positions = [run.finish_position for run in recent_runs if run.finish_position]
    finish_summary = ""
    if finish_positions:
        average_position = sum(finish_positions) / len(finish_positions)
        finish_summary = f" / 平均着順{average_position:.1f}着"

    missing_parts = []
    if not any(run.margin is not None for run in recent_runs):
        missing_parts.append("着差データなし")
    if not any(run.closing_rank is not None for run in recent_runs):
        missing_parts.append("上がり順位データなし")
    missing_text = f" / {'・'.join(missing_parts)}" if missing_parts else ""

    return (
        f"相手関係評価: {level_summary}。"
        f"レースレベル推移: {class_part} / "
        f"平均{average_level:.1f}点 / 最高{highest_level}点 / 直近{latest_level}点 / 推移{trend}"
        f"{finish_summary}{missing_text}"
    )


def judge_trend(levels: list[int]) -> str:
    """相手レベルの推移を判定します。levels[0] が直近走です。"""

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


def safe_int(value: object) -> int | None:
    """数値にできない場合はNoneにします。"""

    if value in {None, "", "不明"}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_float(value: object) -> float | None:
    """小数にできない場合はNoneにします。"""

    if value in {None, "", "不明"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    """点数を0〜100点に収めます。"""

    return round(max(minimum, min(maximum, value)), 1)
