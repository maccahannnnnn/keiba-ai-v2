"""複数Evaluatorの評価結果を統合するためのAggregatorです。

このモジュールは Analyzer や main.py には接続しません。
CourseEvaluator / BloodlineEvaluator / TrackConditionEvaluator / PaceEvaluator
などが返す辞書を受け取り、総合スコアや理由一覧を1つにまとめます。
"""


class EvaluationAggregator:
    """Evaluatorごとのsummaryを安全に合算するクラスです。"""

    def aggregate(self, evaluation_results):
        """複数の評価結果を1つの辞書に統合します。

        Args:
            evaluation_results (list | None): 各Evaluatorが返した評価結果の一覧。

        Returns:
            dict: total_score / modifiers / reasons / explains などを統合した結果。
        """

        results = evaluation_results if isinstance(evaluation_results, list) else []

        aggregated = {
            "total_score": 0,
            "modifiers": {},
            "source_type_summary": {},
            "reasons": [],
            "explains": [],
            "matched_results": [],
            "unmatched_results": [],
            "warnings": [],
        }

        for result in results:
            if not isinstance(result, dict):
                continue

            summary = result.get("summary")
            if not isinstance(summary, dict):
                summary = {}

            aggregated["total_score"] += self._safe_number(summary.get("total_score"))
            self._merge_modifiers(aggregated["modifiers"], summary.get("modifiers"))
            self._merge_list(aggregated["reasons"], summary.get("reasons"))
            self._merge_list(aggregated["explains"], summary.get("explains"))
            self._merge_source_type_summary(
                aggregated["source_type_summary"],
                summary.get("source_type_summary"),
            )

            if result.get("matched", False):
                aggregated["matched_results"].append(result)
            else:
                aggregated["unmatched_results"].append(result)

            warning = result.get("warning")
            if warning:
                aggregated["warnings"].append(warning)

        return aggregated

    def _merge_modifiers(self, destination, source):
        """modifier別スコアを合算します。数値以外はスキップします。"""

        if not isinstance(source, dict):
            return

        for modifier, score in source.items():
            safe_score = self._safe_number_or_none(score)
            if safe_score is None:
                continue

            modifier_name = str(modifier)
            destination[modifier_name] = destination.get(modifier_name, 0) + safe_score

    def _merge_list(self, destination, source):
        """reasons / explains などのlistを安全に連結します。"""

        if not isinstance(source, list):
            return

        destination.extend(source)

    def _merge_source_type_summary(self, destination, source):
        """source_type_summary を source_type ごとに統合します。"""

        if not isinstance(source, dict):
            return

        for source_type, summary in source.items():
            if not isinstance(summary, dict):
                continue

            source_type_name = str(source_type)
            if source_type_name not in destination:
                destination[source_type_name] = {
                    "total_score": 0,
                    "modifiers": {},
                    "sources": [],
                }

            target = destination[source_type_name]
            target["total_score"] += self._safe_number(summary.get("total_score"))
            self._merge_modifiers(target["modifiers"], summary.get("modifiers"))
            self._merge_sources(target["sources"], summary.get("sources"))

    def _merge_sources(self, destination, source):
        """source一覧を重複なしで統合します。"""

        if not isinstance(source, list):
            return

        for item in source:
            source_name = str(item)
            if source_name not in destination:
                destination.append(source_name)

    def _safe_number(self, value):
        """数値でなければ0として扱います。"""

        safe_value = self._safe_number_or_none(value)
        return safe_value if safe_value is not None else 0

    def _safe_number_or_none(self, value):
        """int / float だけを有効なスコアとして扱います。"""

        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return value
        return None


if __name__ == "__main__":
    aggregator = EvaluationAggregator()

    course_result = {
        "matched": True,
        "summary": {
            "total_score": 5,
            "modifiers": {"sustained_speed": 3, "left_turn": 2},
            "reasons": [{"source_type": "course", "reason": "コース適性を評価"}],
            "explains": [{"source_type": "course", "explain": "長い直線を評価"}],
            "source_type_summary": {
                "course": {
                    "total_score": 5,
                    "modifiers": {"sustained_speed": 3, "left_turn": 2},
                    "sources": ["tokyo_turf_1600"],
                }
            },
        },
    }

    bloodline_result = {
        "matched": True,
        "summary": {
            "total_score": 7,
            "modifiers": {"late_speed": 4, "sustained_speed": 3},
            "reasons": [{"source_type": "bloodline", "reason": "血統適性を評価"}],
            "explains": [{"source_type": "bloodline", "explain": "末脚血統を評価"}],
            "source_type_summary": {
                "bloodline": {
                    "total_score": 7,
                    "modifiers": {"late_speed": 4, "sustained_speed": 3},
                    "sources": ["sire_キズナ"],
                }
            },
        },
    }

    track_condition_result = {
        "matched": True,
        "summary": {
            "total_score": 4,
            "modifiers": {"fast_track": 4},
            "reasons": [{"source_type": "track_condition", "reason": "高速馬場を評価"}],
            "explains": [{"source_type": "track_condition", "explain": "高速決着向き"}],
            "source_type_summary": {
                "track_condition": {
                    "total_score": 4,
                    "modifiers": {"fast_track": 4},
                    "sources": ["track_condition_turf_good_fast_track"],
                }
            },
        },
    }

    pace_result = {
        "matched": True,
        "summary": {
            "total_score": 3,
            "modifiers": {"sustained_speed": 2, "positioning": 1},
            "reasons": [{"source_type": "pace", "reason": "平均ペースを評価"}],
            "explains": [{"source_type": "pace", "explain": "総合力勝負"}],
            "source_type_summary": {
                "pace": {
                    "total_score": 3,
                    "modifiers": {"sustained_speed": 2, "positioning": 1},
                    "sources": ["tokyo_turf_1600_average"],
                }
            },
        },
    }

    unmatched_result = {
        "matched": False,
        "warning": "Course profile not found",
        "summary": {
            "total_score": 0,
            "modifiers": {},
            "reasons": [],
            "explains": [],
            "source_type_summary": {},
        },
    }

    print(
        aggregator.aggregate(
            [
                course_result,
                bloodline_result,
                track_condition_result,
                pace_result,
                unmatched_result,
            ]
        )
    )
    print(aggregator.aggregate(None))
    print(aggregator.aggregate([]))
