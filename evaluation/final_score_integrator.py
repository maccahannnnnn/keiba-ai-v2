"""Integrate trial evaluation scores into one final score.

This module is intentionally independent from the production Analyzer.  It
only receives scores calculated by trial evaluators and adds them together.
Later, a WeightOptimizer can replace the simple addition without changing the
callers that read final_score and score_breakdown.
"""


class FinalScoreIntegrator:
    """Combine each trial evaluator score into final_score."""

    SCORE_FIELDS = {
        "bloodline": "bloodline_score",
        "past": "past_performance_score",
        "pace": "pace_style_score",
        "distance": "distance_score",
        "track": "track_condition_score",
        "shape": "shape_score",
        "course_shape": "course_shape_score",
        "track_bias": "track_bias_score",
        "lap": "lap_score",
    }

    DISPLAY_LABELS = {
        "bloodline": "Bloodline",
        "past": "Past",
        "pace": "Pace",
        "distance": "Distance",
        "track": "Track",
        "shape": "Shape",
        "course_shape": "CourseShape",
        "track_bias": "TrackBias",
        "lap": "Lap",
        "final": "Final",
    }

    def integrate(
        self,
        score_data=None,
        *,
        horse_name=None,
        bloodline_score=None,
        past_performance_score=None,
        pace_style_score=None,
        distance_score=None,
        track_condition_score=None,
        shape_score=None,
        course_shape_score=None,
        track_bias_score=None,
        lap_score=None,
    ):
        """Return final_score and score_breakdown for one horse.

        score_data can be a dict from a trial result.  Keyword scores are also
        accepted so the class can be used in small standalone checks.
        """

        data = score_data if isinstance(score_data, dict) else {}
        name = horse_name or data.get("horse_name") or data.get("name")

        raw_scores = {
            "bloodline": self._first_number(
                bloodline_score,
                data.get("bloodline_score"),
                self._modifier_score(data, "bloodline"),
            ),
            "past": self._first_number(
                past_performance_score,
                data.get("past_performance_score"),
            ),
            "pace": self._first_number(
                pace_style_score,
                data.get("pace_style_score"),
            ),
            "distance": self._first_number(
                distance_score,
                data.get("distance_score"),
            ),
            "track": self._first_number(
                track_condition_score,
                data.get("track_condition_score"),
            ),
            "shape": self._first_number(
                shape_score,
                data.get("shape_score"),
            ),
            "course_shape": self._first_number(
                course_shape_score,
                data.get("course_shape_score"),
            ),
            "track_bias": self._first_number(
                track_bias_score,
                data.get("track_bias_score"),
            ),
            "lap": self._first_number(
                lap_score,
                data.get("lap_score"),
            ),
        }

        final_score = sum(raw_scores.values())
        score_breakdown = {
            self.DISPLAY_LABELS[key]: value for key, value in raw_scores.items()
        }
        score_breakdown[self.DISPLAY_LABELS["final"]] = final_score

        return {
            "horse_name": name,
            "final_score": final_score,
            "score_breakdown": score_breakdown,
        }

    def integrate_many(self, score_rows):
        """Integrate many horses while preserving input order."""

        rows = score_rows if isinstance(score_rows, list) else []
        return [self.integrate(row) for row in rows]

    def format_report(self, integrated_results):
        """Create a readable final-score table."""

        rows = integrated_results if isinstance(integrated_results, list) else []
        lines = [
            "==================",
            "Final Score",
            "==================",
            "馬名 | Final | Bloodline | Past | Pace | Distance | Track | Shape | CourseShape | TrackBias | Lap",
        ]
        for row in rows:
            breakdown = row.get("score_breakdown") if isinstance(row, dict) else {}
            if not isinstance(breakdown, dict):
                breakdown = {}
            lines.append(
                f"{row.get('horse_name') or '-'} | "
                f"{breakdown.get('Final', 0)} | "
                f"{breakdown.get('Bloodline', 0)} | "
                f"{breakdown.get('Past', 0)} | "
                f"{breakdown.get('Pace', 0)} | "
                f"{breakdown.get('Distance', 0)} | "
                f"{breakdown.get('Track', 0)} | "
                f"{breakdown.get('Shape', 0)} | "
                f"{breakdown.get('CourseShape', 0)} | "
                f"{breakdown.get('TrackBias', 0)} | "
                f"{breakdown.get('Lap', 0)}"
            )
        return "\n".join(lines)

    def _first_number(self, *values):
        """Return the first numeric-looking value, otherwise 0."""

        for value in values:
            number = self._safe_number(value)
            if number is not None:
                return number
        return 0

    def _safe_number(self, value):
        """Convert numeric strings safely; ignore unavailable values."""

        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number.is_integer():
            return int(number)
        return number

    def _modifier_score(self, data, source_type):
        """Fallback: read source_type total_score from source_type_summary."""

        aggregate_result = data.get("aggregate_result")
        if not isinstance(aggregate_result, dict):
            aggregate_result = data

        source_summary = aggregate_result.get("source_type_summary")
        if not isinstance(source_summary, dict):
            return None

        source_data = source_summary.get(source_type)
        if not isinstance(source_data, dict):
            return None
        return source_data.get("total_score")


if __name__ == "__main__":
    integrator = FinalScoreIntegrator()
    sample_results = [
        {
            "horse_name": "sample_a",
            "bloodline_score": 20,
            "past_performance_score": 57,
            "pace_style_score": 18,
            "distance_score": 14,
            "track_condition_score": 28,
            "shape_score": 15,
            "course_shape_score": 6,
            "track_bias_score": 3,
            "lap_score": 8,
        },
        {
            "horse_name": "sample_b",
            "bloodline_score": 12,
            "past_performance_score": 30,
            "pace_style_score": -5,
            "distance_score": 8,
            "track_condition_score": 10,
            "shape_score": -10,
            "course_shape_score": -4,
            "track_bias_score": 0,
            "lap_score": -4,
        },
    ]
    integrated = integrator.integrate_many(sample_results)
    print(integrator.format_report(integrated))
