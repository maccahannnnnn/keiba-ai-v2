"""Evaluate each horse's advantage from race pace and running style.

This is a standalone trial Evaluation Engine utility. It combines the race
pace predicted by RacePacePredictor with each horse's pace_style and returns a
simple shape score/comment without changing existing evaluators or main.py.
"""


class RaceShapeEvaluator:
    """Judge whether the expected race shape helps each running style."""

    SHAPE_TABLE = {
        "slow": {
            "escape": 20,
            "front": 15,
            "stalk": 10,
            "closer": 0,
            "deep_closer": -15,
        },
        "average": {
            "escape": 5,
            "front": 10,
            "stalk": 10,
            "closer": 10,
            "deep_closer": 0,
        },
        "fast": {
            "escape": -8,
            "front": -3,
            "stalk": 5,
            "closer": 15,
            "deep_closer": 10,
        },
        "very_fast": {
            "escape": -10,
            "front": -6,
            "stalk": 4,
            "closer": 12,
            "deep_closer": 8,
        },
        "sprint_turf_very_fast": {
            "escape": -12,
            "front": -8,
            "stalk": 4,
            "closer": 14,
            "deep_closer": 10,
        },
        "dirt_small_turn_1700_very_fast": {
            "escape": -10,
            "front": -6,
            "stalk": 4,
            "closer": 10,
            "deep_closer": 8,
        },
        "default_very_fast": {
            "escape": -10,
            "front": -6,
            "stalk": 4,
            "closer": 12,
            "deep_closer": 8,
        },
    }

    STYLE_LABELS = {
        "escape": "逃げ",
        "front": "先行",
        "stalk": "好位",
        "closer": "差し",
        "deep_closer": "追込",
        "unknown": "判定不能",
    }

    def evaluate(
        self,
        pace_prediction,
        pace_style,
        horse_name=None,
        surface=None,
        distance=None,
        course_shape=None,
    ):
        """Evaluate one horse's race-shape fit."""

        pace = self._normalize_pace(pace_prediction)
        style = self._normalize_style(pace_style)
        table_key = self._shape_table_key(pace, surface, distance, course_shape)
        shape_score = self.SHAPE_TABLE.get(table_key, {}).get(style, 0)
        adjustment = self._limited_adjustment(
            table_key,
            style,
            shape_score,
            surface=surface,
            distance=distance,
        )
        if adjustment.get("applied"):
            shape_score = adjustment["score_after"]

        return {
            "horse_name": horse_name,
            "pace_prediction": pace,
            "shape_table_key": table_key,
            "pace_style": style,
            "pace_style_label": self.STYLE_LABELS.get(style, "判定不能"),
            "shape_score": shape_score,
            "shape_comment": self._shape_comment(shape_score),
            "race_shape_adjustment_applied": adjustment.get("applied", False),
            "race_shape_adjustment_id": adjustment.get("id", ""),
            "race_shape_adjustment_reason": adjustment.get("reason", ""),
            "race_shape_adjustment_scope": adjustment.get("scope", ""),
            "race_shape_score_before": adjustment.get("score_before", shape_score),
            "race_shape_score_after": adjustment.get("score_after", shape_score),
        }

    def evaluate_many(
        self,
        pace_prediction,
        horses,
        race_context=None,
        structure_result=None,
    ):
        """Evaluate many horses while preserving input order."""

        rows = horses if isinstance(horses, list) else []
        context = race_context if isinstance(race_context, dict) else {}
        structure = structure_result if isinstance(structure_result, dict) else {}
        race_structure = structure.get("race_structure") if isinstance(structure.get("race_structure"), dict) else {}
        default_surface = race_structure.get("surface") or context.get("surface")
        default_distance = race_structure.get("distance") or context.get("distance")
        default_course_shape = race_structure.get("course_shape") or context.get("course_shape")
        results = []
        for horse in rows:
            if isinstance(horse, dict):
                horse_name = horse.get("horse_name") or horse.get("name")
                style = horse.get("pace_style")
                surface = horse.get("surface") or default_surface
                distance = horse.get("distance") or default_distance
                course_shape = horse.get("course_shape") or default_course_shape
            else:
                horse_name = None
                style = None
                surface = default_surface
                distance = default_distance
                course_shape = default_course_shape
            results.append(
                self.evaluate(
                    pace_prediction,
                    style,
                    horse_name,
                    surface=surface,
                    distance=distance,
                    course_shape=course_shape,
                )
            )
        return results

    def format_report(self, shape_results):
        """Create a readable list report."""

        rows = shape_results if isinstance(shape_results, list) else []
        lines = [
            "==================",
            "Race Shape",
            "==================",
            "馬名 | 脚質 | ペース | shape_score | コメント",
        ]
        for row in rows:
            lines.append(
                f"{row.get('horse_name') or '-'} | "
                f"{row.get('pace_style_label') or '-'} | "
                f"{row.get('pace_prediction') or '-'} | "
                f"{row.get('shape_score', 0)} | "
                f"{row.get('shape_comment') or '-'}"
            )
        return "\n".join(lines)

    def _normalize_pace(self, value):
        text = str(value).strip().lower() if value is not None else "average"
        if text in {"slow", "average", "fast", "very_fast"}:
            return text
        return "average"

    def _normalize_style(self, value):
        text = str(value).strip().lower() if value is not None else "unknown"
        if text in self.STYLE_LABELS:
            return text
        return "unknown"

    def _shape_table_key(self, pace, surface=None, distance=None, course_shape=None):
        if pace != "very_fast":
            return pace

        normalized_surface = self._normalize_surface(surface)
        normalized_course_shape = (
            str(course_shape).strip().lower() if course_shape is not None else ""
        )
        normalized_distance = self._safe_int(distance)

        if normalized_surface == "turf" and normalized_distance is not None and normalized_distance <= 1400:
            return "sprint_turf_very_fast"

        if (
            normalized_surface == "dirt"
            and normalized_distance is not None
            and 1600 <= normalized_distance <= 1800
            and normalized_course_shape == "small_turn"
        ):
            return "dirt_small_turn_1700_very_fast"

        return "default_very_fast"

    def _limited_adjustment(self, table_key, style, shape_score, surface=None, distance=None):
        normalized_surface = self._normalize_surface(surface)
        normalized_distance = self._safe_int(distance)
        if (
            table_key == "fast"
            and normalized_surface == "turf"
            and normalized_distance is not None
            and normalized_distance <= 1400
            and style == "closer"
            and shape_score == 15
        ):
            return {
                "applied": True,
                "id": "phase_d_step5_fast_turf_sprint_closer_guard",
                "scope": "fast_turf_sprint_closer_overvaluation_guard",
                "reason": "芝短距離のfast想定で差し馬へのRaceShape加点を限定",
                "score_before": shape_score,
                "score_after": 10,
            }
        if (
            table_key == "sprint_turf_very_fast"
            and style == "escape"
            and shape_score == -12
        ):
            return {
                "applied": True,
                "id": "phase_d_step6_sprint_turf_very_fast_escape_mitigation",
                "scope": "sprint_turf_very_fast_escape_mitigation",
                "reason": "芝短距離のvery_fast想定で逃げ馬へのRaceShape減点を限定緩和",
                "score_before": shape_score,
                "score_after": -8,
            }
        return {
            "applied": False,
            "id": "",
            "scope": "",
            "reason": "",
            "score_before": shape_score,
            "score_after": shape_score,
        }

    def _normalize_surface(self, value):
        text = str(value).strip().lower() if value is not None else ""
        if text in {"turf", "芝", "t"}:
            return "turf"
        if text in {"dirt", "ダート", "ダ", "d"}:
            return "dirt"
        return text

    def _safe_int(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _shape_comment(self, score):
        if score >= 10:
            return "展開向く"
        if score <= -10:
            return "展開不向き"
        return "展開普通"


if __name__ == "__main__":
    evaluator = RaceShapeEvaluator()
    sample_horses = [
        {"horse_name": "escape_sample", "pace_style": "escape"},
        {"horse_name": "front_sample", "pace_style": "front"},
        {"horse_name": "closer_sample", "pace_style": "closer"},
        {"horse_name": "deep_sample", "pace_style": "deep_closer"},
    ]
    results = evaluator.evaluate_many("fast", sample_horses)
    print(evaluator.format_report(results))
