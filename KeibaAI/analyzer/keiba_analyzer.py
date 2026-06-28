from collections import Counter, defaultdict

from config import ANALYSIS_CRITERIA, ANALYSIS_RULES, PAST_RUN_LIMIT
from analyzer.explain_analyzer import build_explain_analysis
from analyzer.integrated_evaluator import evaluate_integrated_score
from analyzer.lap_analyzer import analyze_lap
from analyzer.opponent_analyzer import analyze_opponents
from analyzer.pace_analyzer import analyze_pace
from analyzer.score_calculator import calculate_scores
from analyzer.schemas import AnalysisResult, PastRace, TodayEntry
from analyzer.track_bias_analyzer import analyze_track_bias
from knowledge.bloodline_profiles import analyze_bloodline


class KeibaAnalyzer:
    """中央競馬の分析を補助するAIです。

    今は機械学習を使わず、人間が競馬新聞を見て考える流れに近い形で分析します。
    """

    def __init__(self, past_races: list[PastRace]) -> None:
        # 分析ルールは config.py から読み込みます。
        # ルールを変えたいときに、複数ファイルを直さなくて済みます。
        self.analysis_rules = ANALYSIS_RULES
        self.analysis_criteria = ANALYSIS_CRITERIA

        # 馬名ごとに過去レースをまとめます。
        self.past_by_horse: dict[str, list[PastRace]] = defaultdict(list)

        for race in past_races:
            self.past_by_horse[race.horse_name].append(race)

        # 新しいレース順に並べると、指定した数の過去走を取り出しやすくなります。
        for horse_name in self.past_by_horse:
            self.past_by_horse[horse_name].sort(key=lambda race: race.race_date, reverse=True)

    def analyze(self, entries: list[TodayEntry], expected_pace: str) -> list[AnalysisResult]:
        """基本ルールの順番に沿って全頭を分析します。"""

        results: list[AnalysisResult] = []
        pace_analysis = analyze_pace(entries)
        lap_analysis = analyze_lap(entries)
        track_bias_analysis = analyze_track_bias(entries, pace_analysis)
        opponent_analyses = analyze_opponents(entries, self.past_by_horse)

        for entry in entries:
            past_races = limit_past_races(self.past_by_horse.get(entry.horse_name, []))
            opponent_analysis = opponent_analyses[entry.horse_name]

            past_run_analysis, past_score = self.analyze_past_runs(entry, past_races)
            opponent, opponent_score = self.analyze_opponent_level(opponent_analysis)
            style, style_score = self.analyze_running_style(past_races, entry)
            distance, distance_score = self.analyze_distance_fitness(past_races, entry)
            track, track_score = self.analyze_track_fitness(past_races, entry)
            pedigree, pedigree_score = self.analyze_pedigree(entry)
            body, body_score = self.analyze_body_weight(entry, past_races)
            pace, pace_score = self.analyze_pace_forecast(entry, pace_analysis.pace, entries)
            in_the_money_rate = self.calculate_in_the_money_rate(entry, past_races)
            score_result = calculate_scores(
                entry,
                past_races,
                entries,
                pace_analysis.pace,
                pace_analysis,
                opponent_analysis,
                track_bias_analysis,
                lap_analysis,
            )
            bloodline_analysis = analyze_bloodline(
                entry.sire,
                entry.dam_sire,
                entry.surface,
                entry.distance,
                entry.track_condition,
            )
            integrated_evaluation = evaluate_integrated_score(
                entry,
                score_result.item_scores,
                score_result.total_score,
                pace_analysis,
                bloodline_analysis,
                lap_analysis,
            )

            result = AnalysisResult(
                horse_name=entry.horse_name,
                horse_number=entry.horse_number,
                frame_number=entry.frame_number,
                race_info=f"{entry.race_date} {entry.racecourse}{entry.race_number}R {entry.surface}{entry.distance}m {entry.track_condition}",
                past_run_analysis=past_run_analysis,
                opponent_level=opponent,
                running_style=style,
                distance_fitness=distance,
                track_fitness=track,
                pedigree=pedigree,
                body_weight=body,
                pace_forecast=pace,
                score=integrated_evaluation.final_score,
                in_the_money_rate=in_the_money_rate,
                in_the_money_score=score_result.in_the_money_score,
                item_scores=score_result.item_scores,
                pace_analysis=pace_analysis,
                bloodline_analysis=bloodline_analysis,
                integrated_evaluation=integrated_evaluation,
                opponent_analysis=opponent_analysis,
                track_bias_analysis=track_bias_analysis,
                lap_analysis=lap_analysis,
            )
            result.explain_analysis = build_explain_analysis(result)
            results.append(result)

        return sorted(results, key=lambda result: result.score, reverse=True)

    def analyze_past_runs(self, entry: TodayEntry, races: list[PastRace]) -> tuple[str, float]:
        """1. 過去走を分析します。"""

        positions = recent_positions(entry, races)
        if not positions:
            return "過去データなし", 0.4

        average_position = sum(positions) / len(positions)
        top3_count = sum(1 for position in positions if position <= 3)
        score = normalize_lower_is_better(average_position, best=1, worst=10)

        return f"{past_run_label()} {positions} / 平均{average_position:.1f}着 / 3着内{top3_count}回", score

    def analyze_opponent_level(self, opponent_analysis) -> tuple[str, float]:
        """2. 相手関係を分析します。"""

        text = (
            f"平均相手レベル{opponent_analysis.average_level:.1f}点 / "
            f"最高{opponent_analysis.highest_level}点 / "
            f"直近{opponent_analysis.latest_level}点 / "
            f"推移{opponent_analysis.trend} / "
            f"{opponent_analysis.member_comparison}"
        )
        return text, opponent_analysis.score / 100

    def analyze_running_style(self, races: list[PastRace], entry: TodayEntry) -> tuple[str, float]:
        """3. 通過順・脚質を分析します。"""

        if not races:
            return f"脚質{entry.running_style} / 通過順データなし", 0.55

        style_counts = Counter(race.running_style for race in races)
        main_style = style_counts.most_common(1)[0][0]
        latest_corner = races[0].corner_positions
        score = 0.75 if main_style == entry.running_style else 0.55

        return f"主脚質{main_style} / 今回入力{entry.running_style} / 前走通過{latest_corner}", score

    def analyze_distance_fitness(self, races: list[PastRace], entry: TodayEntry) -> tuple[str, float]:
        """4. 距離適性を分析します。"""

        if not races:
            return "距離データなし", 0.4

        same_distance = [race for race in races if race.distance == entry.distance]
        near_distance = [race for race in races if abs(race.distance - entry.distance) <= 200]
        good_near = sum(1 for race in near_distance if race.finish_position <= 3)
        score = min(1.0, 0.35 + good_near * 0.18 + len(same_distance) * 0.08)

        return f"同距離{len(same_distance)}走 / 近い距離で3着内{good_near}回", score

    def analyze_track_fitness(self, races: list[PastRace], entry: TodayEntry) -> tuple[str, float]:
        """5. 当日馬場を分析します。"""

        if not races:
            return f"{entry.track_condition}馬場 / データなし", 0.4

        same_track = [race for race in races if race.track_condition == entry.track_condition]
        good_same_track = sum(1 for race in same_track if race.finish_position <= 3)
        score = min(1.0, 0.45 + good_same_track * 0.2) if same_track else 0.45

        return f"{entry.track_condition}馬場{len(same_track)}走 / 3着内{good_same_track}回", score

    def analyze_pedigree(self, entry: TodayEntry) -> tuple[str, float]:
        """6. 血統を分析します。"""

        if not entry.bloodline_note:
            return "血統メモなし", 0.5

        positive_words = ["向き", "得意", "良い", "強い", "プラス", "歓迎"]
        negative_words = ["不安", "割引", "苦手", "マイナス"]

        score = 0.55
        if any(word in entry.bloodline_note for word in positive_words):
            score += 0.2
        if any(word in entry.bloodline_note for word in negative_words):
            score -= 0.2

        return entry.bloodline_note, max(0.2, min(score, 1.0))

    def analyze_body_weight(self, entry: TodayEntry, races: list[PastRace]) -> tuple[str, float]:
        """7. 馬体重を分析します。"""

        if not races:
            return f"斤量{entry.weight:.1f}kg / 馬体重{entry.body_weight}kg({entry.body_weight_diff:+}kg) / 比較なし", 0.5

        average_weight = sum(race.body_weight for race in races) / len(races)
        difference = entry.body_weight - average_weight

        if abs(entry.body_weight_diff) <= 6 and abs(difference) <= 10:
            condition = "安定"
            score = 0.8
        elif abs(entry.body_weight_diff) <= 12:
            condition = "許容範囲"
            score = 0.6
        else:
            condition = "大きな変動"
            score = 0.35

        return f"斤量{entry.weight:.1f}kg / 馬体重{entry.body_weight}kg({entry.body_weight_diff:+}kg) / 平均比{difference:+.1f}kg / {condition}", score

    def analyze_pace_forecast(
        self,
        entry: TodayEntry,
        expected_pace: str,
        entries: list[TodayEntry],
    ) -> tuple[str, float]:
        """8. 展開予想を分析します。"""

        style_counts = Counter(today_entry.running_style for today_entry in entries)
        front_count = style_counts["逃げ"] + style_counts["先行"]

        score = 0.55
        reason = "標準"

        if expected_pace == "ハイ" and entry.running_style in {"差し", "追込"}:
            score = 0.8
            reason = "前が速くなれば差し有利"
        elif expected_pace == "スロー" and entry.running_style in {"逃げ", "先行"}:
            score = 0.8
            reason = "楽に先行できれば有利"
        elif front_count >= 3 and entry.running_style in {"差し", "追込"}:
            score = 0.72
            reason = "先行馬が多く差し向き"
        elif front_count <= 1 and entry.running_style in {"逃げ", "先行"}:
            score = 0.72
            reason = "前が少なく展開利"

        return f"想定{expected_pace} / 逃げ先行{front_count}頭 / {reason}", score

    def calculate_in_the_money_rate(self, entry: TodayEntry, races: list[PastRace]) -> float:
        """10. 3着内率を計算します。"""

        positions = recent_positions(entry, races)
        if not positions:
            return 0.0

        top3_count = sum(1 for position in positions if position <= 3)
        return top3_count / len(positions)


def normalize_lower_is_better(value: float, best: float, worst: float) -> float:
    """小さいほど良い数値を、0.0から1.0の評価に変換します。"""

    if value <= best:
        return 1.0
    if value >= worst:
        return 0.0
    return 1.0 - ((value - best) / (worst - best))


def recent_positions(entry: TodayEntry, races: list[PastRace]) -> list[int]:
    """過去走の着順を取り出します。

    今は `today_entries.csv` の `last_runs` を優先します。
    空欄の場合だけ、過去レースCSVから補います。
    将来はJRA公式、JRA-VAN、netkeibaなどから取得した成績データもここへ流し込めます。
    """

    if entry.last_runs.strip():
        return limit_positions(parse_last_runs(entry.last_runs))

    return [race.finish_position for race in limit_past_races(races)]


def parse_last_runs(value: str) -> list[int]:
    """`1-3-4-2-1` のような文字を、[1, 3, 4, 2, 1] に変換します。"""

    positions: list[int] = []

    # カンマ、スラッシュ、全角スペースなどで入力しても読めるようにします。
    normalized = value.replace(",", "-").replace("/", "-").replace("　", "-").replace(" ", "-")
    for part in normalized.split("-"):
        if part.strip().isdigit():
            positions.append(int(part))

    return positions


def limit_positions(positions: list[int]) -> list[int]:
    """config.py の PAST_RUN_LIMIT に合わせて、使う着順数を切り替えます。"""

    if PAST_RUN_LIMIT == "all":
        return positions
    return positions[: int(PAST_RUN_LIMIT)]


def limit_past_races(races: list[PastRace]) -> list[PastRace]:
    """config.py の PAST_RUN_LIMIT に合わせて、使う過去レース数を切り替えます。"""

    if PAST_RUN_LIMIT == "all":
        return races
    return races[: int(PAST_RUN_LIMIT)]


def past_run_label() -> str:
    """レポート用に、何走分を見ているか分かる文字を作ります。"""

    if PAST_RUN_LIMIT == "all":
        return "全過去走"
    return f"対象過去走({PAST_RUN_LIMIT}走)"


def class_rank(class_level: str) -> int:
    """クラス文字列を比較しやすい数字に変換します。"""

    ranks = {
        "新馬": 1,
        "未勝利": 2,
        "1勝": 3,
        "2勝": 4,
        "3勝": 5,
        "OP": 6,
        "G3": 7,
        "G2": 8,
        "G1": 9,
    }
    return ranks.get(class_level, 0)
