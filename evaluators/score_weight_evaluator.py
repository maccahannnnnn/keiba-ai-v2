"""Adjust score weights from race structure before final integration.

This evaluator does not change the production Analyzer, Knowledge Base,
Importer, CSV format, Self Review Engine, or main.py.  It reads already
calculated trial scores and decides which score items should matter more for
the current race structure.
"""


class ScoreWeightEvaluator:
    """Create score weights, weighted_score, and weighted_score_breakdown."""

    SCORE_KEYS = [
        "bloodline_score",
        "past_performance_score",
        "pace_style_score",
        "distance_score",
        "track_condition_score",
        "shape_score",
        "course_shape_score",
        "track_bias_score",
        "lap_score",
    ]

    def evaluate(self, horse=None):
        """Return weights and weighted score for one horse."""

        data = horse if isinstance(horse, dict) else {}
        weights = {key: 1.0 for key in self.SCORE_KEYS}
        comments = []
        hinted_keys = self._apply_recommended_weights_hint(data, weights)

        self._adjust_course_shape_weight(data, weights, comments)
        self._adjust_lap_weight(data, weights, comments)
        self._adjust_track_bias_weight(data, weights, comments)
        self._adjust_shape_weight(data, weights, comments)
        self._adjust_distance_weight(data, weights, comments)
        self._adjust_bloodline_weight(data, weights, comments)
        self._adjust_past_weight(data, weights, comments)
        if hinted_keys:
            self._apply_recommended_weights_hint(data, weights)
            comments.insert(0, "RaceStructureEngineの構造を採用")

        consistency_adjustments = self._apply_consistency_result(data, weights, comments)

        breakdown = {}
        weighted_score = 0
        for key in self.SCORE_KEYS:
            raw_score = self._score(data, key)
            weight = weights.get(key, 1.0)
            weighted_value = raw_score * weight
            weighted_score += weighted_value
            breakdown[key] = {
                "raw_score": raw_score,
                "weight": weight,
                "weighted_value": weighted_value,
            }

        if not comments:
            comments.append("全体の情報量から標準重みで評価")

        weighted_score = self._clean_number(weighted_score)
        return {
            "horse_name": data.get("horse_name") or data.get("name"),
            "score_weights": weights,
            "weight_source": self._weight_source(hinted_keys, bool(consistency_adjustments)),
            "weight_comment": " / ".join(comments),
            "weighted_score": weighted_score,
            "integrated_score": weighted_score,
            "weighted_score_breakdown": breakdown,
            "consistency_weight_adjustments": consistency_adjustments,
        }

    def evaluate_many(self, horses=None):
        """Evaluate many horses while preserving input order."""

        rows = horses if isinstance(horses, list) else []
        return [self.evaluate(row) for row in rows]

    def format_report(self, weight_results):
        """Create a readable weighted-score table."""

        rows = weight_results if isinstance(weight_results, list) else []
        lines = [
            "==================",
            "Score Weight",
            "==================",
            "馬名 | Weighted | Comment",
        ]
        for row in rows:
            if not isinstance(row, dict):
                row = {}
            lines.append(
                f"{row.get('horse_name') or '-'} | "
                f"{row.get('weighted_score', 0)} | "
                f"{row.get('weight_comment') or '-'}"
            )
        return "\n".join(lines)

    def _adjust_course_shape_weight(self, data, weights, comments):
        score = abs(self._score(data, "course_shape_score"))
        comment = str(data.get("course_shape_comment") or "")
        keywords = ["コース形状", "枠", "直線", "小回り", "ワンターン", "コーナー", "位置取り"]
        if score >= 8:
            weights["course_shape_score"] = 1.4
            comments.append("コース形状と位置取りの影響が大きいため course_shape_score を重視")
        elif score >= 4 or any(word in comment for word in keywords):
            weights["course_shape_score"] = 1.2
            comments.append("コース形状の影響を加味して course_shape_score をやや重視")

    def _adjust_lap_weight(self, data, weights, comments):
        lap_style = str(data.get("lap_style") or "")
        score = abs(self._score(data, "lap_score"))
        if lap_style in {"instant", "sustained", "attrition"} and score >= 8:
            weights["lap_score"] = 1.4
            comments.append("今回のレースはラップ適性の影響が大きいため lap_score を重視")
        elif lap_style in {"instant", "sustained", "attrition"} and score >= 4:
            weights["lap_score"] = 1.2
            comments.append("ラップ適性の差を反映して lap_score をやや重視")

    def _adjust_track_bias_weight(self, data, weights, comments):
        score = abs(self._score(data, "track_bias_score"))
        if score >= 8:
            weights["track_bias_score"] = 1.4
            comments.append("当日バイアスの影響が大きいため track_bias_score を重視")
        elif score >= 4:
            weights["track_bias_score"] = 1.2
            comments.append("当日バイアスを加味して track_bias_score をやや重視")
        elif score == 0:
            comments.append("当日バイアス情報が不足しているため track_bias_score は標準重み")

    def _adjust_shape_weight(self, data, weights, comments):
        pace = str(data.get("race_pace_prediction") or data.get("pace_prediction") or "")
        score = abs(self._score(data, "shape_score"))
        if pace in {"fast", "very_fast", "slow"}:
            weights["shape_score"] = 1.3 if score >= 8 else 1.2
            comments.append("ペースが極端になりやすいため shape_score を重視")
        elif pace == "average" and score >= 8:
            weights["shape_score"] = 1.1
            comments.append("平均ペースだが展開適性差があるため shape_score を少し重視")

    def _adjust_distance_weight(self, data, weights, comments):
        score = abs(self._score(data, "distance_score"))
        distance = self._to_int(data.get("distance"))
        if distance is not None and distance >= 2200 and score >= 4:
            weights["distance_score"] = 1.3
            comments.append("長距離条件のため distance_score を重視")
        elif score >= 8:
            weights["distance_score"] = 1.2
            comments.append("距離適性差が大きいため distance_score を重視")
        elif score >= 4:
            weights["distance_score"] = 1.1
            comments.append("距離適性をやや重視")

    def _adjust_bloodline_weight(self, data, weights, comments):
        surface = str(data.get("surface") or "")
        distance = self._to_int(data.get("distance"))
        track_condition_comment = str(data.get("track_condition_fit_label") or "")
        course_comment = str(data.get("course_shape_comment") or "")
        if (
            "重" in track_condition_comment
            or "道悪" in course_comment
            or (distance is not None and distance >= 2200)
            or surface in {"dirt", "ダート"}
        ):
            weights["bloodline_score"] = 1.1
            comments.append("条件適性が問われるため bloodline_score をやや重視")

    def _adjust_past_weight(self, data, weights, comments):
        warnings = data.get("warnings")
        missing_count = 0
        if isinstance(warnings, list):
            missing_count = sum(1 for warning in warnings if "missing" in str(warning) or "unknown" in str(warning))
        if missing_count >= 3:
            weights["past_performance_score"] = 1.1
            comments.append("他項目に情報不足が多いため past_performance_score をやや重視")

    def _apply_recommended_weights_hint(self, data, weights):
        hints = data.get("recommended_weights_hint")
        if not isinstance(hints, dict):
            return set()

        aliases = {
            "past_score": "past_performance_score",
            "pace_score": "pace_style_score",
            "pace_style": "pace_style_score",
            "track_condition": "track_condition_score",
            "track_condition_fit": "track_condition_score",
            "course_shape": "course_shape_score",
            "track_bias": "track_bias_score",
            "lap": "lap_score",
            "lap_style": "lap_score",
            "distance": "distance_score",
            "distance_type": "distance_score",
            "bloodline": "bloodline_score",
        }

        applied = set()
        for raw_key, raw_value in hints.items():
            key = aliases.get(str(raw_key), str(raw_key))
            if key not in weights:
                continue
            value = self._to_float(raw_value)
            if value is None:
                continue
            weights[key] = value
            applied.add(key)
        return applied

    def _weight_source(self, hinted_keys, consistency_applied=False):
        if not hinted_keys:
            base = "default"
        elif len(hinted_keys) >= len(self.SCORE_KEYS):
            base = "race_structure"
        else:
            base = "mixed"
        return f"{base}_consistency" if consistency_applied else base

    def _apply_consistency_result(self, data, weights, comments):
        result = data.get("consistency_result")
        if not isinstance(result, dict):
            return {}

        level = str(result.get("consistency_level") or "").lower()
        score = self._to_float(result.get("consistency_score"))
        strong_matches = self._as_list(result.get("strong_matches"))
        conflict_factors = self._as_list(result.get("conflict_factors"))
        adjustments = {}

        if level == "high" or (score is not None and score >= 0.85):
            for factor in strong_matches:
                self._adjust_weight_for_factor(weights, adjustments, factor, self._positive_delta(score))
            if strong_matches:
                comments.append("構造一致度が高いため strong_matches の評価項目をやや重視")
        elif level == "medium" or (score is not None and 0.7 <= score < 0.85):
            if len(strong_matches) >= 3:
                for factor in strong_matches:
                    self._adjust_weight_for_factor(weights, adjustments, factor, 0.1)
                comments.append("構造一致度が中程度のため、強く一致した項目のみ最小補正")
        elif level in {"low", "conflict"} or (score is not None and score < 0.5):
            delta = -0.2 if level == "conflict" or (score is not None and score < 0.3) else -0.1
            for factor in conflict_factors:
                self._adjust_weight_for_factor(weights, adjustments, factor, delta)
            if conflict_factors:
                comments.append("構造との矛盾があるため conflict_factors の評価項目を軽く抑制")

        if adjustments:
            comments.append("ConsistencyEngine の結果を補助的に反映")
        return adjustments

    def _positive_delta(self, score):
        if score is not None and score >= 0.9:
            return 0.2
        return 0.1

    def _adjust_weight_for_factor(self, weights, adjustments, factor, delta):
        for key in self._factor_to_score_keys(factor):
            if key not in weights:
                continue
            before = weights.get(key, 1.0)
            after = self._clamp_weight(before + delta)
            if after == before:
                continue
            weights[key] = after
            current = self._parse_delta(adjustments.get(key))
            adjustments[key] = self._format_delta(current + (after - before))

    def _factor_to_score_keys(self, factor):
        text = str(factor)
        mapping = {
            "course_shape": ["course_shape_score"],
            "shape": ["shape_score"],
            "pace": ["shape_score"],
            "positioning": ["shape_score"],
            "distance": ["distance_score"],
            "bloodline": ["bloodline_score"],
            "lap": ["lap_score"],
            "track_bias": ["track_bias_score"],
            "past": ["past_performance_score"],
        }
        return mapping.get(text, [])

    def _clamp_weight(self, value):
        return max(0.7, min(1.5, round(value, 2)))

    def _format_delta(self, value):
        text = f"{value:+.2f}"
        return text.rstrip("0").rstrip(".")

    def _parse_delta(self, value):
        if value is None:
            return 0
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return 0

    def _as_list(self, value):
        return value if isinstance(value, list) else []

    def _score(self, data, key):
        aliases = {
            "past_performance_score": ["past_score"],
            "pace_style_score": ["pace_score"],
        }
        for candidate in [key] + aliases.get(key, []):
            value = data.get(candidate)
            number = self._to_float(value)
            if number is not None:
                return number
        return 0

    def _to_float(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _clean_number(self, value):
        rounded = round(value, 2)
        return int(rounded) if float(rounded).is_integer() else rounded


if __name__ == "__main__":
    evaluator = ScoreWeightEvaluator()
    sample = {
        "horse_name": "sample",
        "bloodline_score": 12,
        "past_performance_score": 40,
        "pace_style_score": 8,
        "distance_score": 10,
        "track_condition_score": 5,
        "shape_score": 10,
        "course_shape_score": 8,
        "track_bias_score": 0,
        "lap_score": 9,
        "lap_style": "attrition",
        "race_pace_prediction": "average",
        "surface": "dirt",
        "distance": 1700,
    }
    print(evaluator.format_report([evaluator.evaluate(sample)]))
