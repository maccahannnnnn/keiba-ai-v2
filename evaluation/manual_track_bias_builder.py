"""Build manual same-day track-bias input for trial evaluation.

This module only normalizes an optional manual input value into the dictionary
shape already consumed by TrackBiasEvaluator. It does not score, infer, or
modify existing evaluator logic.
"""


class ManualTrackBiasBuilder:
    """Convert a manual track-bias label into race-bias fields."""

    ALLOWED_VALUES = [
        "neutral",
        "front",
        "closer",
        "inside",
        "outside",
        "front_inside",
        "front_outside",
        "closer_inside",
        "closer_outside",
    ]

    BIAS_MAP = {
        "neutral": {
            "track_bias": "neutral",
            "front_bias": False,
            "closer_bias": False,
            "inside_bias": False,
            "outside_bias": False,
            "bias_comment": "手動指定: 中立",
        },
        "front": {
            "track_bias": "front",
            "front_bias": True,
            "closer_bias": False,
            "inside_bias": False,
            "outside_bias": False,
            "bias_comment": "手動指定: 前残り傾向",
        },
        "closer": {
            "track_bias": "closer",
            "front_bias": False,
            "closer_bias": True,
            "inside_bias": False,
            "outside_bias": False,
            "bias_comment": "手動指定: 差し有利傾向",
        },
        "inside": {
            "track_bias": "inside",
            "front_bias": False,
            "closer_bias": False,
            "inside_bias": True,
            "outside_bias": False,
            "bias_comment": "手動指定: 内有利傾向",
        },
        "outside": {
            "track_bias": "outside",
            "front_bias": False,
            "closer_bias": False,
            "inside_bias": False,
            "outside_bias": True,
            "bias_comment": "手動指定: 外有利傾向",
        },
        "front_inside": {
            "track_bias": "front_inside",
            "front_bias": True,
            "closer_bias": False,
            "inside_bias": True,
            "outside_bias": False,
            "bias_comment": "手動指定: 前残り・内有利傾向",
        },
        "front_outside": {
            "track_bias": "front_outside",
            "front_bias": True,
            "closer_bias": False,
            "inside_bias": False,
            "outside_bias": True,
            "bias_comment": "手動指定: 前残り・外有利傾向",
        },
        "closer_inside": {
            "track_bias": "closer_inside",
            "front_bias": False,
            "closer_bias": True,
            "inside_bias": True,
            "outside_bias": False,
            "bias_comment": "手動指定: 差し有利・内有利傾向",
        },
        "closer_outside": {
            "track_bias": "closer_outside",
            "front_bias": False,
            "closer_bias": True,
            "inside_bias": False,
            "outside_bias": True,
            "bias_comment": "手動指定: 差し有利・外有利傾向",
        },
    }

    def build(self, manual_track_bias=None):
        """Return normalized bias fields, or None when no manual input exists."""

        normalized = self.normalize(manual_track_bias)
        if normalized is None:
            return None
        return dict(self.BIAS_MAP[normalized])

    def normalize(self, manual_track_bias=None):
        """Normalize case and surrounding spaces for a manual bias label."""

        if manual_track_bias is None:
            return None

        text = str(manual_track_bias).strip().lower()
        if not text:
            return None

        if text not in self.BIAS_MAP:
            allowed = ", ".join(self.ALLOWED_VALUES)
            raise ValueError(
                f"Unsupported manual_track_bias: {manual_track_bias}. "
                f"Allowed values: {allowed}"
            )
        return text


def build_manual_track_bias(manual_track_bias=None):
    """Convenience wrapper for callers that do not need a builder instance."""

    return ManualTrackBiasBuilder().build(manual_track_bias)


if __name__ == "__main__":
    builder = ManualTrackBiasBuilder()
    for value in [None, "", " FRONT_INSIDE ", "closer_outside"]:
        print(value, "=>", builder.build(value))
