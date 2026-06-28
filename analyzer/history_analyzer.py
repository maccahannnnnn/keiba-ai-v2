from dataclasses import dataclass
from statistics import mean

from config import PAST_RUN_LIMIT
from analyzer.schemas import PastRace, TodayEntry
from knowledge.history_profiles import HISTORY_COMMENT_RULES, get_history_grade


@dataclass
class HistoryRun:
    """過去走1走分を、過去走評価エンジンが見やすい形にそろえたデータです。"""

    finish_position: int | None
    margin: float | None
    popularity: int | None
    closing_rank: int | None
    corner_positions: str
    distance: int | None
    racecourse: str
    class_level: str


@dataclass
class HistoryAnalysis:
    """1頭分の過去走評価結果です。将来ML用の特徴量にも変換しやすい形にしています。"""

    horse_name: str
    history_score: float
    history_comment: str
    grade: str
    average_finish: float | None
    stability: str
    trend: str
    rise_degree: float
    decline_degree: float
    finish_transition: str
    margin_transition: str
    popularity_transition: str
    closing_rank_transition: str
    corner_transition: str
    distance_transition: str
    course_transition: str
    class_transition: str

    def to_features(self) -> dict[str, float]:
        """features.csvへ将来保存しやすいよう、数値だけを返します。"""

        return {
            "history_score": self.history_score,
            "history_rise_degree": self.rise_degree,
            "history_decline_degree": self.decline_degree,
        }


def analyze_history(entry: TodayEntry, past_races: list[PastRace]) -> HistoryAnalysis:
    """直近の過去走から、成績の安定度・上昇度・下降度を評価します。

    今は `today_entries.csv` の `last_runs` を中心に使います。
    将来TARGET/JRA-VANなどから詳細な過去走データが入ったら、同じ関数へ
    着差・人気・上がり・通過順・距離・コース・クラスを渡すだけで拡張できます。
    """

    runs = build_history_runs(entry, past_races)
    finishes = [run.finish_position for run in runs if run.finish_position is not None]

    if not finishes:
        return HistoryAnalysis(
            horse_name=entry.horse_name,
            history_score=0.0,
            history_comment="過去走データなし",
            grade="D",
            average_finish=None,
            stability="不明",
            trend="不明",
            rise_degree=0.0,
            decline_degree=0.0,
            finish_transition="-",
            margin_transition="-",
            popularity_transition="-",
            closing_rank_transition="-",
            corner_transition="-",
            distance_transition="-",
            course_transition="-",
            class_transition="-",
        )

    average_finish = mean(finishes)
    stability = judge_stability(finishes)
    trend, rise_degree, decline_degree = judge_trend(finishes)
    score = calculate_history_score(finishes, stability, rise_degree, decline_degree)
    grade_profile = get_history_grade(score)
    comments = build_history_comments(entry, runs, finishes, stability, trend, grade_profile.comment)

    return HistoryAnalysis(
        horse_name=entry.horse_name,
        history_score=score,
        history_comment=" / ".join(comments),
        grade=grade_profile.grade,
        average_finish=average_finish,
        stability=stability,
        trend=trend,
        rise_degree=rise_degree,
        decline_degree=decline_degree,
        finish_transition=format_transition(finishes),
        margin_transition=format_transition([run.margin for run in runs]),
        popularity_transition=format_transition([run.popularity for run in runs]),
        closing_rank_transition=format_transition([run.closing_rank for run in runs]),
        corner_transition=format_transition([run.corner_positions for run in runs]),
        distance_transition=format_transition([run.distance for run in runs]),
        course_transition=format_transition([run.racecourse for run in runs]),
        class_transition=format_transition([run.class_level for run in runs]),
    )


def build_history_runs(entry: TodayEntry, past_races: list[PastRace]) -> list[HistoryRun]:
    """CSVの簡易データと、将来の詳細データを同じ形に変換します。"""

    positions = limit_positions(parse_last_runs(entry.last_runs)) if entry.last_runs.strip() else []

    if positions:
        return [
            HistoryRun(
                finish_position=position,
                margin=None,
                popularity=None,
                closing_rank=None,
                corner_positions="不明",
                distance=entry.distance,
                racecourse=entry.racecourse,
                class_level=entry.class_level,
            )
            for position in positions
        ]

    limited_races = limit_history_races(past_races)
    runs: list[HistoryRun] = []
    for race in limited_races:
        # PastRaceにまだ存在しない項目は getattr で安全に取り出します。
        # 将来フィールドを増やしても、この関数を少し直すだけで対応できます。
        runs.append(
            HistoryRun(
                finish_position=race.finish_position,
                margin=getattr(race, "margin", None),
                popularity=race.popularity,
                closing_rank=getattr(race, "closing_rank", None),
                corner_positions=race.corner_positions,
                distance=race.distance,
                racecourse=getattr(race, "racecourse", "不明"),
                class_level=race.class_level,
            )
        )
    return runs


def calculate_history_score(
    finishes: list[int],
    stability: str,
    rise_degree: float,
    decline_degree: float,
) -> float:
    """過去走内容を0〜100点にします。今回は簡易ルールです。"""

    average_finish = mean(finishes)
    score = 100 - (average_finish - 1) * 9
    top3_count = sum(1 for position in finishes if position <= 3)
    board_count = sum(1 for position in finishes if position <= 5)

    score += top3_count * 3
    score += board_count * 1.5

    if stability == "高":
        score += 8
    elif stability == "低":
        score -= 8

    score += rise_degree * 0.8
    score -= decline_degree * 0.8

    return round(max(0.0, min(100.0, score)), 1)


def judge_stability(finishes: list[int]) -> str:
    """着順のブレ幅から安定度を判定します。"""

    if len(finishes) <= 1:
        return "不明"

    finish_range = max(finishes) - min(finishes)
    if finish_range <= 2:
        return "高"
    if finish_range <= 5:
        return "中"
    return "低"


def judge_trend(finishes: list[int]) -> tuple[str, float, float]:
    """近2走とそれ以前を比べて、上昇・維持・下降を判定します。"""

    if len(finishes) < 3:
        return "不明", 0.0, 0.0

    recent_average = mean(finishes[:2])
    older_average = mean(finishes[2:])
    difference = older_average - recent_average

    if difference >= 1.0:
        return "上昇", round(difference * 10, 1), 0.0
    if difference <= -1.0:
        return "下降", 0.0, round(abs(difference) * 10, 1)
    return "維持", 0.0, 0.0


def build_history_comments(
    entry: TodayEntry,
    runs: list[HistoryRun],
    finishes: list[int],
    stability: str,
    trend: str,
    grade_comment: str,
) -> list[str]:
    """レポートに表示する短いコメントを作ります。"""

    comments: list[str] = [grade_comment]

    if all(position <= 5 for position in finishes):
        comments.append(HISTORY_COMMENT_RULES["all_board"])
    if stability == "高":
        comments.append(HISTORY_COMMENT_RULES["stable"])
    if trend == "上昇":
        comments.append(HISTORY_COMMENT_RULES["rising"])
    elif trend == "下降":
        comments.append(HISTORY_COMMENT_RULES["declining"])

    distances = [run.distance for run in runs if run.distance is not None]
    if distances and any(abs(distance - entry.distance) <= 200 for distance in distances):
        comments.append(HISTORY_COMMENT_RULES["distance_match"])

    if all(run.margin is None for run in runs):
        comments.append(HISTORY_COMMENT_RULES["missing_margin"])
    if all(run.closing_rank is None for run in runs):
        comments.append(HISTORY_COMMENT_RULES["missing_closing"])

    return unique_texts(comments)


def format_transition(values: list[object]) -> str:
    """推移を `1 -> 3 -> 2` のように表示します。空欄は不明にします。"""

    cleaned = ["不明" if value in (None, "") else str(value) for value in values]
    return " -> ".join(cleaned) if cleaned else "-"


def limit_history_races(races: list[PastRace]) -> list[PastRace]:
    """config.py の PAST_RUN_LIMIT に合わせて対象走数を制限します。"""

    if PAST_RUN_LIMIT == "all":
        return races
    return races[: int(PAST_RUN_LIMIT)]


def parse_last_runs(value: str) -> list[int]:
    """`1-3-4-2-1` のような文字列を着順リストに変換します。"""

    positions: list[int] = []
    normalized = value.replace(",", "-").replace("/", "-").replace("　", "-").replace(" ", "-")
    for part in normalized.split("-"):
        if part.strip().isdigit():
            positions.append(int(part))
    return positions


def limit_positions(positions: list[int]) -> list[int]:
    """config.py の PAST_RUN_LIMIT に合わせて、使う着順数を制限します。"""

    if PAST_RUN_LIMIT == "all":
        return positions
    return positions[: int(PAST_RUN_LIMIT)]


def unique_texts(values: list[str]) -> list[str]:
    """同じコメントを重複表示しないための小さな補助関数です。"""

    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique
