"""Evaluation Engine の試運転用ドライバーです。

このモジュールは正式Analyzerではありません。
CSVを読まず、main.pyにも接続せず、入力されたrace_contextだけを使って
Course / Bloodline / TrackCondition / Pace の評価を一気通貫で確認します。
"""

from evaluation.bloodline_evaluator import BloodlineEvaluator
from evaluation.course_evaluator import CourseEvaluator
from evaluation.evaluation_aggregator import EvaluationAggregator
from evaluation.explain_engine import ExplainEngine
from evaluation.pace_evaluator import PaceEvaluator
from evaluation.track_condition_evaluator import TrackConditionEvaluator


class TrialAnalyzer:
    """評価エンジン群を試運転するための簡易Analyzerです。"""

    def __init__(self):
        self.course_evaluator = CourseEvaluator()
        self.bloodline_evaluator = BloodlineEvaluator()
        self.track_condition_evaluator = TrackConditionEvaluator()
        self.pace_evaluator = PaceEvaluator()
        self.aggregator = EvaluationAggregator()
        self.explain_engine = ExplainEngine()

    def analyze(self, race_context):
        """race_contextを受け取り、評価から説明生成までをまとめて実行します。

        Args:
            race_context (dict | None): レース条件と血統1セットを持つ簡易入力。

        Returns:
            dict: 各Evaluatorの中間結果と統合結果、説明結果をまとめた辞書。
        """

        context = race_context if isinstance(race_context, dict) else {}

        racecourse = context.get("racecourse")
        surface = context.get("surface")
        distance = context.get("distance")
        pace = context.get("pace")

        bloodline = context.get("bloodline")
        if not isinstance(bloodline, dict):
            bloodline = {}

        track_condition = context.get("track_condition")
        if not isinstance(track_condition, dict):
            track_condition = {}

        course_result = self.course_evaluator.evaluate(
            racecourse=racecourse,
            surface=surface,
            distance=distance,
        )
        bloodline_result = self.bloodline_evaluator.evaluate(
            sire_name=bloodline.get("sire_name"),
            broodmare_sire_name=bloodline.get("broodmare_sire_name"),
        )
        track_condition_result = self.track_condition_evaluator.evaluate(
            surface=track_condition.get("surface", surface),
            condition=track_condition.get("condition"),
            bias_type=track_condition.get("bias_type"),
        )
        pace_result = self.pace_evaluator.evaluate(
            racecourse=racecourse,
            surface=surface,
            distance=distance,
            pace=pace,
        )

        aggregate_result = self.aggregator.aggregate(
            [
                course_result,
                bloodline_result,
                track_condition_result,
                pace_result,
            ]
        )
        explain_result = self.explain_engine.build(aggregate_result)

        return {
            "input": context,
            "course_result": course_result,
            "bloodline_result": bloodline_result,
            "track_condition_result": track_condition_result,
            "pace_result": pace_result,
            "aggregate_result": aggregate_result,
            "explain_result": explain_result,
        }


if __name__ == "__main__":
    analyzer = TrialAnalyzer()
    trial_contexts = [
        {
            "racecourse": "tokyo",
            "surface": "turf",
            "distance": 1600,
            "pace": "average",
            "track_condition": {
                "surface": "turf",
                "condition": "good",
                "bias_type": "fast_track",
            },
            "bloodline": {
                "sire_name": "キズナ",
                "broodmare_sire_name": "キングカメハメハ",
            },
        },
        {
            "racecourse": "nakayama",
            "surface": "dirt",
            "distance": 1800,
            "pace": "average",
            "track_condition": {
                "surface": "dirt",
                "condition": "heavy",
                "bias_type": "power_track",
            },
            "bloodline": {
                "sire_name": "ドレフォン",
                "broodmare_sire_name": "キングカメハメハ",
            },
        },
        {
            "racecourse": "unknown",
            "surface": "turf",
            "distance": 9999,
            "bloodline": {
                "sire_name": "不明",
            },
        },
    ]

    for context in trial_contexts:
        result = analyzer.analyze(context)
        print(
            {
                "input": context,
                "course_matched": result["course_result"]["matched"],
                "bloodline_matched": result["bloodline_result"]["matched"],
                "track_condition_matched": result["track_condition_result"]["matched"],
                "pace_matched": result["pace_result"]["matched"],
                "total_score": result["aggregate_result"]["total_score"],
                "warnings": result["aggregate_result"]["warnings"],
                "summary_text": result["explain_result"]["summary_text"],
            }
        )
