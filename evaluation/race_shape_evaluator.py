"""Evaluate each horse's advantage from race pace and running style.

This is a standalone trial Evaluation Engine utility.  It combines the race
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
            "escape": -10,
            "front": -5,
            "stalk": 5,
            "closer": 15,
            "deep_closer": 10,
        },
        "very_fast": {
            "escape": -20,
            "front": -15,
            "stalk": 5,
            "closer": 20,
            "deep_closer": 15,
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

    def evaluate(self, pace_prediction, pace_style, horse_name=None):
        """Evaluate one horse's race-shape fit."""

        pace = self._normalize_pace(pace_prediction)
        style = self._normalize_style(pace_style)
        shape_score = self.SHAPE_TABLE.get(pace, {}).get(style, 0)

        return {
            "horse_name": horse_name,
            "pace_prediction": pace,
            "pace_style": style,
            "pace_style_label": self.STYLE_LABELS.get(style, "判定不能"),
            "shape_score": shape_score,
            "shape_comment": self._shape_comment(shape_score),
        }

    def evaluate_many(self, pace_prediction, horses):
        """Evaluate many horses while preserving input order."""

        rows = horses if isinstance(horses, list) else []
        results = []
        for horse in rows:
            if isinstance(horse, dict):
                horse_name = horse.get("horse_name") or horse.get("name")
                style = horse.get("pace_style")
            else:
                horse_name = None
                style = None
            results.append(self.evaluate(pace_prediction, style, horse_name))
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
