"""Apply race-shape impact adjustments to final scores.

This is a standalone trial Evaluation Engine utility.  It does not change the
production Analyzer, existing evaluators, importer, CSV format, or main.py.
The class receives the current final_score and RaceShapeEvaluator output, then
returns an adjusted_score for trial comparison.
"""


class ImpactEvaluator:
    """Convert race-shape fit into an impact_score and adjusted_score."""

    COMMENT_IMPACTS = {
        "展開向く": 10,
        "やや向く": 5,
        "展開普通": 0,
        "やや不向き": -5,
        "展開不向き": -10,
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
        horse_name=None,
        pace_style=None,
        shape_score=None,
        shape_comment=None,
        final_score=None,
    ):
        """Evaluate one horse's race-shape impact.

        Args:
            horse_name (str | None): Horse name for display.
            pace_style (str | None): escape/front/stalk/closer/deep_closer.
            shape_score (int | float | None): Score from RaceShapeEvaluator.
            shape_comment (str | None): Comment from RaceShapeEvaluator.
            final_score (int | float | None): Current final score.
        """

        base_score = self._safe_number(final_score)
        raw_impact_score = self._impact_from_comment_or_score(shape_comment, shape_score)
        impact_score, suppression_reason = self._suppress_duplicate_shape_penalty(
            raw_impact_score,
            shape_comment,
            shape_score,
        )
        adjusted_score = base_score + impact_score

        return {
            "horse_name": horse_name,
            "pace_style": self._normalize_style(pace_style),
            "pace_style_label": self.STYLE_LABELS.get(
                self._normalize_style(pace_style),
                "判定不能",
            ),
            "shape_score": self._safe_number(shape_score),
            "shape_comment": shape_comment or self._comment_from_impact(impact_score),
            "final_score": base_score,
            "raw_impact_score": raw_impact_score,
            "impact_score": impact_score,
            "adjusted_score": adjusted_score,
            "comment": self._build_comment(pace_style, impact_score),
            "impact_reasons": self._impact_reasons(
                raw_impact_score,
                impact_score,
                suppression_reason,
            ),
            "duplicate_shape_impact_suppressed": bool(suppression_reason),
            "impact_suppression_reason": suppression_reason,
        }

    def evaluate_many(self, horses):
        """Evaluate many horse result dicts while preserving input order."""

        rows = horses if isinstance(horses, list) else []
        results = []
        for row in rows:
            if not isinstance(row, dict):
                row = {}
            results.append(
                self.evaluate(
                    horse_name=row.get("horse_name") or row.get("name"),
                    pace_style=row.get("pace_style"),
                    shape_score=row.get("shape_score"),
                    shape_comment=row.get("shape_comment"),
                    final_score=row.get("final_score"),
                )
            )
        return results

    def format_report(self, impact_results):
        """Create a readable impact-adjustment table."""

        rows = impact_results if isinstance(impact_results, list) else []
        lines = [
            "==================",
            "Impact Evaluation",
            "==================",
            "馬名 | Final | Impact | Adjusted | Comment",
        ]
        for row in rows:
            if not isinstance(row, dict):
                row = {}
            lines.append(
                f"{row.get('horse_name') or '-'} | "
                f"{row.get('final_score', 0)} | "
                f"{self._format_signed(row.get('impact_score', 0))} | "
                f"{row.get('adjusted_score', 0)} | "
                f"{row.get('comment') or '-'}"
            )
        return "\n".join(lines)

    def _impact_from_comment_or_score(self, shape_comment, shape_score):
        """Prefer explicit comments, then fall back to numeric shape_score."""

        comment = str(shape_comment).strip() if shape_comment is not None else ""
        if comment in self.COMMENT_IMPACTS:
            return self.COMMENT_IMPACTS[comment]

        score = self._safe_number(shape_score)
        if score >= 10:
            return 10
        if score >= 5:
            return 5
        if score <= -10:
            return -10
        if score <= -5:
            return -5
        return 0

    def _suppress_duplicate_shape_penalty(self, impact_score, shape_comment, shape_score):
        """Avoid counting RaceShape downside twice in final and adjusted scores."""

        if impact_score >= 0:
            return impact_score, ""

        if self._is_race_shape_negative_signal(shape_comment, shape_score):
            return 0, "RaceShapeで評価済みのため重複Impactは付与しない"

        return impact_score, ""

    def _is_race_shape_negative_signal(self, shape_comment, shape_score):
        comment = str(shape_comment).strip() if shape_comment is not None else ""
        if comment in {"展開不向き", "やや不向き"}:
            return True

        score = self._safe_number(shape_score)
        return score <= -5

    def _impact_reasons(self, raw_impact_score, impact_score, suppression_reason):
        if suppression_reason:
            return [suppression_reason]
        if impact_score > 0:
            return ["RaceShape由来の正のImpact"]
        if impact_score < 0:
            return ["RaceShape由来の負のImpact"]
        if raw_impact_score < 0:
            return ["RaceShape由来の負のImpactを抑制"]
        return []

    def _comment_from_impact(self, impact_score):
        if impact_score >= 10:
            return "展開向く"
        if impact_score >= 5:
            return "やや向く"
        if impact_score <= -10:
            return "展開不向き"
        if impact_score <= -5:
            return "やや不向き"
        return "展開普通"

    def _build_comment(self, pace_style, impact_score):
        style = self.STYLE_LABELS.get(self._normalize_style(pace_style), "判定不能")
        if impact_score > 0:
            return f"{style}に向く展開で加点"
        if impact_score < 0:
            return f"{style}に厳しい展開で減点"
        return f"{style}への展開補正なし"

    def _normalize_style(self, value):
        text = str(value).strip().lower() if value is not None else "unknown"
        return text if text in self.STYLE_LABELS else "unknown"

    def _safe_number(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return 0
        if isinstance(value, (int, float)):
            return value
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0
        if number.is_integer():
            return int(number)
        return number

    def _format_signed(self, value):
        number = self._safe_number(value)
        return f"+{number}" if number > 0 else str(number)


if __name__ == "__main__":
    evaluator = ImpactEvaluator()
    samples = [
        {
            "horse_name": "グリーンゴー",
            "pace_style": "closer",
            "shape_score": 15,
            "shape_comment": "展開向く",
            "final_score": 183,
        },
        {
            "horse_name": "逃げサンプル",
            "pace_style": "escape",
            "shape_score": -10,
            "shape_comment": "展開不向き",
            "final_score": 90,
        },
        {
            "horse_name": "普通サンプル",
            "pace_style": "stalk",
            "shape_score": 0,
            "shape_comment": "展開普通",
            "final_score": 70,
        },
    ]
    print(evaluator.format_report(evaluator.evaluate_many(samples)))
