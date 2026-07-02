"""Predict race pace from the whole field's running-style composition.

This is a trial Evaluation Engine utility.  It receives running-style labels
such as escape/front/stalk/closer/deep_closer and predicts the likely race
pace without changing the production Analyzer, importer, or main.py.
"""


class RacePacePredictor:
    """Predict slow / average / fast / very_fast from all horses' pace styles."""

    STYLE_KEYS = [
        "escape",
        "front",
        "stalk",
        "closer",
        "deep_closer",
        "unknown",
    ]

    def predict(self, pace_styles):
        """Return pace prediction and style counts.

        Args:
            pace_styles (list): A list of style strings or dicts containing a
                pace_style key.  Unknown or missing values are counted as
                unknown instead of raising an error.
        """

        styles = self._normalize_styles(pace_styles)
        counts = self._count_styles(styles)
        prediction = self._predict_from_counts(counts)
        reason = self._build_reason(counts, prediction)

        return {
            "pace_prediction": prediction,
            "escape_count": counts["escape"],
            "front_count": counts["front"],
            "stalk_count": counts["stalk"],
            "closer_count": counts["closer"],
            "deep_closer_count": counts["deep_closer"],
            "unknown_count": counts["unknown"],
            "total_count": len(styles),
            "reason": reason,
        }

    def format_report(self, prediction_result):
        """Create a readable text report for trial checks."""

        result = prediction_result if isinstance(prediction_result, dict) else {}
        return "\n".join(
            [
                "==================",
                "Race Pace",
                "==================",
                f"Escape : {result.get('escape_count', 0)}",
                f"Front : {result.get('front_count', 0)}",
                f"Stalk : {result.get('stalk_count', 0)}",
                f"Closer : {result.get('closer_count', 0)}",
                f"DeepCloser : {result.get('deep_closer_count', 0)}",
                f"Unknown : {result.get('unknown_count', 0)}",
                "",
                f"Prediction : {result.get('pace_prediction', 'slow')}",
                f"Reason : {result.get('reason', '')}",
            ]
        )

    def _normalize_styles(self, pace_styles):
        if not isinstance(pace_styles, list):
            return []

        normalized = []
        for item in pace_styles:
            if isinstance(item, dict):
                style = item.get("pace_style") or item.get("style")
            else:
                style = item

            style_text = str(style).strip().lower() if style is not None else "unknown"
            normalized.append(style_text if style_text in self.STYLE_KEYS else "unknown")
        return normalized

    def _count_styles(self, styles):
        counts = {style: 0 for style in self.STYLE_KEYS}
        for style in styles:
            counts[style if style in counts else "unknown"] += 1
        return counts

    def _predict_from_counts(self, counts):
        escape = counts["escape"]
        front = counts["front"]
        stalk = counts["stalk"]
        forward_pressure = escape * 2 + front + (stalk * 0.5)

        if escape >= 3:
            return "very_fast"
        if escape >= 2 and front >= 4:
            return "fast"
        if escape >= 2 and forward_pressure >= 5:
            return "fast"
        if escape == 1 and front >= 3:
            return "average"
        if escape == 1 and front <= 2:
            return "slow"
        if escape == 0 and front >= 4:
            return "average"
        if escape == 0:
            return "slow"
        return "average"

    def _build_reason(self, counts, prediction):
        return (
            f"逃げ{counts['escape']}頭、先行{counts['front']}頭、"
            f"好位{counts['stalk']}頭の構成から {prediction} と判定"
        )


if __name__ == "__main__":
    predictor = RacePacePredictor()
    samples = [
        ["front", "front", "stalk", "closer"],
        ["escape", "front", "front", "closer"],
        ["escape", "escape", "front", "front", "front", "front"],
        ["escape", "escape", "escape", "front"],
    ]

    for sample in samples:
        print(predictor.format_report(predictor.predict(sample)))
        print()
