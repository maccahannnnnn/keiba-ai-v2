"""Check consistency between race structure and evaluator results.

ConsistencyEngine does not add prediction logic and does not modify any score.
It only reports whether existing evaluator outputs point in the same direction
as the race structure produced by RaceStructureEngine.
"""


class ConsistencyEngine:
    """Evaluate structure/evaluator agreement without changing scores."""

    def evaluate(self, horse=None, race_structure=None):
        """Return consistency_result for one horse."""

        item = horse if isinstance(horse, dict) else {}
        structure = race_structure if isinstance(race_structure, dict) else item.get("race_structure")
        if not isinstance(structure, dict):
            structure = {}

        strong_matches = []
        weak_matches = []
        conflict_factors = []

        self._check_course_shape(item, structure, strong_matches, weak_matches, conflict_factors)
        self._check_pace_shape(item, structure, strong_matches, weak_matches, conflict_factors)
        self._check_distance(item, structure, strong_matches, weak_matches, conflict_factors)
        self._check_bloodline(item, structure, strong_matches, weak_matches, conflict_factors)
        self._check_track_bias(item, structure, strong_matches, weak_matches, conflict_factors)
        self._check_lap(item, structure, strong_matches, weak_matches, conflict_factors)

        strong_matches = self._unique(strong_matches)
        weak_matches = self._unique(weak_matches)
        conflict_factors = self._unique(conflict_factors)
        consistency_score = self._score(strong_matches, weak_matches, conflict_factors)
        consistency_level = self._level(consistency_score)

        return {
            "consistency_score": consistency_score,
            "consistency_level": consistency_level,
            "strong_matches": strong_matches,
            "weak_matches": weak_matches,
            "conflict_factors": conflict_factors,
            "consistency_comment": self._comment(consistency_level, strong_matches, conflict_factors),
            "bonus_hint": self._bonus_hint(consistency_level),
            "penalty_hint": self._penalty_hint(consistency_level, conflict_factors),
        }

    def evaluate_many(self, horses=None, race_structure=None):
        """Evaluate many horses while preserving input order."""

        rows = horses if isinstance(horses, list) else []
        return [self.evaluate(row, race_structure) for row in rows]

    def _check_course_shape(self, item, structure, strong, weak, conflict):
        course_shape = structure.get("course_shape")
        pace_style = item.get("pace_style")
        score = self._number(item.get("course_shape_score"))

        if score >= 4:
            strong.append("course_shape")
        elif score > 0:
            weak.append("course_shape")
        elif score < 0:
            conflict.append("course_shape")

        if course_shape == "small_turn" and pace_style in {"closer", "deep_closer"}:
            conflict.append("positioning")
        if course_shape == "small_turn" and pace_style in {"escape", "front", "stalk"}:
            strong.append("positioning")
        if course_shape == "long_straight_one_turn" and pace_style in {"closer", "deep_closer"}:
            strong.append("late_speed")

    def _check_pace_shape(self, item, structure, strong, weak, conflict):
        pace = structure.get("pace")
        pace_style = item.get("pace_style")
        shape_score = self._number(item.get("shape_score"))

        if shape_score >= 8:
            strong.append("shape")
        elif shape_score > 0:
            weak.append("shape")
        elif shape_score < 0:
            conflict.append("pace")

        if pace in {"fast", "very_fast"} and pace_style in {"closer", "deep_closer"}:
            strong.append("pace")
        if pace in {"fast", "very_fast"} and pace_style in {"escape", "front"}:
            conflict.append("pace")
        if pace == "slow" and pace_style in {"escape", "front"}:
            strong.append("pace")
        if pace == "slow" and pace_style == "deep_closer":
            conflict.append("pace")

    def _check_distance(self, item, structure, strong, weak, conflict):
        if "distance_fit" not in self._list(structure.get("key_factors")):
            return
        score = self._number(item.get("distance_score"))
        if score >= 8:
            strong.append("distance")
        elif score > 0:
            weak.append("distance")
        elif score < 0:
            conflict.append("distance")

    def _check_bloodline(self, item, structure, strong, weak, conflict):
        if "bloodline_fit" not in self._list(structure.get("key_factors")):
            return
        score = self._number(item.get("bloodline_score"))
        if score >= 8:
            strong.append("bloodline")
        elif score > 0:
            weak.append("bloodline")
        elif score < 0:
            conflict.append("bloodline")

    def _check_track_bias(self, item, structure, strong, weak, conflict):
        track_bias = structure.get("track_bias")
        score = self._number(item.get("track_bias_score"))
        if track_bias in {"", None, "unknown", "neutral"}:
            if score == 0:
                weak.append("track_bias")
            return
        if score >= 4:
            strong.append("track_bias")
        elif score > 0:
            weak.append("track_bias")
        elif score < 0:
            conflict.append("track_bias")

    def _check_lap(self, item, structure, strong, weak, conflict):
        lap_profile = structure.get("lap_profile")
        lap_style = item.get("lap_style")
        score = self._number(item.get("lap_score"))

        if lap_profile not in {"", None, "unknown", "balanced"} and lap_profile == lap_style:
            strong.append("lap")
        elif lap_profile not in {"", None, "unknown", "balanced"} and lap_style not in {"", None, "unknown"}:
            conflict.append("lap")
        elif score >= 4:
            strong.append("lap")
        elif score > 0:
            weak.append("lap")
        elif score < 0:
            conflict.append("lap")

    def _score(self, strong, weak, conflict):
        total = len(strong) + len(weak) + len(conflict)
        if total <= 0:
            return 0.5
        raw = 0.5 + (len(strong) * 0.09) + (len(weak) * 0.03) - (len(conflict) * 0.12)
        return max(0, min(1, round(raw, 2)))

    def _level(self, score):
        if score >= 0.8:
            return "high"
        if score >= 0.6:
            return "medium"
        if score >= 0.4:
            return "low"
        return "conflict"

    def _comment(self, level, strong, conflict):
        if level == "high":
            return "RaceStructureEngineと複数Evaluatorの方向性がよく一致しています。"
        if level == "medium":
            return "レース構造とEvaluator結果はおおむね一致しています。"
        if level == "low":
            return "一部の評価要素は一致しますが、強い整合性までは確認できません。"
        return "レース構造と一部Evaluator結果に矛盾があります。"

    def _bonus_hint(self, level):
        if level == "high":
            return "structure_bonus"
        if level == "medium":
            return "minor_structure_bonus"
        return "none"

    def _penalty_hint(self, level, conflict):
        if level == "conflict":
            return "structure_conflict_penalty"
        if conflict:
            return "minor_conflict_check"
        return "none"

    def _number(self, value):
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _unique(self, values):
        unique = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique


if __name__ == "__main__":
    engine = ConsistencyEngine()
    sample_horse = {
        "pace_style": "front",
        "shape_score": 10,
        "course_shape_score": 6,
        "distance_score": 12,
        "bloodline_score": 9,
        "track_bias_score": 0,
        "lap_score": 4,
        "lap_style": "sustained",
    }
    sample_structure = {
        "pace": "average",
        "course_shape": "small_turn",
        "track_bias": "neutral",
        "lap_profile": "unknown",
        "key_factors": ["course_shape", "pace", "positioning", "distance_fit", "bloodline_fit"],
    }
    print(engine.evaluate(sample_horse, sample_structure))
