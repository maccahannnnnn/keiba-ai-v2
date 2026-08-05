"""Build a race-level structure context without scoring individual horses.

RaceStructureEngine is not an Evaluator.  It is a small command-center style
module that reads race-level facts, summarizes the likely race structure, and
returns context that later engines can reference safely.
"""

class RaceStructureEngine:
    """Analyze the whole race structure and return neutral context data."""

    STYLE_KEYS = [
        "escape",
        "front",
        "stalk",
        "closer",
        "deep_closer",
        "unknown",
    ]

    def analyze(self, race_data):
        """Return race_structure, comments, flags, and weight hints.

        Args:
            race_data (dict): Race-level data.  Missing fields are allowed and
                are handled as unknown / neutral.
        """

        data = race_data if isinstance(race_data, dict) else {}
        horses = data.get("horses") if isinstance(data.get("horses"), list) else []

        racecourse = self._text(data.get("racecourse") or data.get("course"))
        surface = self._normalize_surface(data.get("surface"))
        distance = self._safe_int(data.get("distance"))
        track_condition = self._text(data.get("track_condition"))
        pace = self._normalize_pace(data.get("pace_prediction") or data.get("pace"))

        style_counts = self._style_counts(data, horses)
        pace_pressure = self._pace_pressure(style_counts)
        dominant_styles = self._dominant_styles(style_counts)
        course_shape = self._course_shape(racecourse, surface, distance)
        draw_impact = self._draw_impact(data, course_shape, surface, distance)
        track_bias = self._track_bias(data)
        lap_profile = self._lap_profile(data, horses)
        structure_flags = self._structure_flags(
            surface=surface,
            distance=distance,
            pace=pace,
            course_shape=course_shape,
            track_bias=track_bias,
            lap_profile=lap_profile,
            data=data,
        )
        key_factors = self._key_factors(
            surface=surface,
            distance=distance,
            pace=pace,
            pace_pressure=pace_pressure,
            course_shape=course_shape,
            draw_impact=draw_impact,
            track_bias=track_bias,
            lap_profile=lap_profile,
            flags=structure_flags,
        )
        recommended_weights_hint = self._recommended_weights_hint(
            key_factors=key_factors,
            pace_pressure=pace_pressure,
            track_bias=track_bias,
            flags=structure_flags,
        )

        race_structure = {
            "racecourse": racecourse or "unknown",
            "course": self._course_label(racecourse, surface, distance),
            "surface": surface,
            "distance": distance,
            "track_condition": track_condition or "unknown",
            "pace": pace,
            "pace_pressure": pace_pressure,
            "dominant_styles": dominant_styles,
            "course_shape": course_shape,
            "draw_impact": draw_impact,
            "track_bias": track_bias,
            "lap_profile": lap_profile,
            "key_factors": key_factors,
        }
        comment_parts = self._comment_parts(race_structure, structure_flags, data)
        structure_comment = self._structure_comment(comment_parts, structure_flags)

        return {
            "race_structure": race_structure,
            "structure_comment": structure_comment,
            "structure_comment_parts": comment_parts,
            "key_factors": key_factors,
            "structure_flags": structure_flags,
            "recommended_weights_hint": recommended_weights_hint,
        }

    def _style_counts(self, data, horses):
        counts = {style: self._safe_int(data.get(f"{style}_count")) or 0 for style in self.STYLE_KEYS}
        if any(counts.values()):
            return counts

        for horse in horses:
            style = "unknown"
            if isinstance(horse, dict):
                style = self._normalize_style(horse.get("pace_style"))
            counts[style] = counts.get(style, 0) + 1
        return counts

    def _pace_pressure(self, counts):
        if not isinstance(counts, dict) or not any(counts.values()):
            return "unknown"

        escape = self._safe_int(counts.get("escape")) or 0
        front = self._safe_int(counts.get("front")) or 0
        stalk = self._safe_int(counts.get("stalk")) or 0
        closer = self._safe_int(counts.get("closer")) or 0
        deep = self._safe_int(counts.get("deep_closer")) or 0
        pressure = escape * 2 + front + stalk * 0.5

        if escape >= 3 or pressure >= 7:
            return "very_high"
        if escape >= 2 or pressure >= 5:
            return "high"
        if pressure >= 2:
            return "medium"
        if closer + deep > front + escape:
            return "low"
        return "medium"

    def _dominant_styles(self, counts):
        if not isinstance(counts, dict) or not any(counts.values()):
            return ["unknown"]

        max_count = max(counts.values())
        if max_count <= 0:
            return ["unknown"]
        return [style for style in self.STYLE_KEYS if counts.get(style, 0) == max_count]

    def _course_shape(self, racecourse, surface, distance):
        course = self._normalize_racecourse(racecourse)
        dist = distance or 0

        if surface == "dirt" and dist <= 1400:
            return "dirt_sprint"
        if dist and dist <= 1400:
            return "sprint"

        if course == "niigata" and surface == "turf" and dist in {1000, 1600, 1800, 2000}:
            return "long_straight_one_turn"
        if course == "tokyo" and (
            surface == "turf" or (surface == "dirt" and dist in {1300, 1400, 1600})
        ):
            return "long_straight_one_turn"

        if course in {"fukushima", "hakodate", "kokura", "sapporo"}:
            return "small_turn"
        if dist >= 1700:
            return "two_turn"
        return "unknown"

    def _draw_impact(self, data, course_shape, surface, distance):
        draw_bias = data.get("draw_bias")
        if draw_bias:
            return "high"
        if course_shape in {"small_turn", "dirt_sprint"}:
            return "high"
        if course_shape == "long_straight_one_turn":
            return "low" if surface == "turf" else "moderate"
        if distance and distance >= 2000:
            return "moderate"
        return "unknown"

    def _track_bias(self, data):
        explicit = self._text(data.get("track_bias"))
        if explicit:
            return explicit

        active = []
        for key, label in [
            ("inside_bias", "inside"),
            ("outside_bias", "outside"),
            ("front_bias", "front"),
            ("closer_bias", "closer"),
        ]:
            if self._is_truthy_bias(data.get(key)):
                active.append(label)
        return "_".join(active) if active else "neutral"

    def _lap_profile(self, data, horses):
        explicit = self._normalize_lap(data.get("lap_style") or data.get("lap_profile"))
        if explicit != "unknown":
            return explicit

        counts = {style: 0 for style in ["instant", "sustained", "attrition", "balanced", "unknown"]}
        for horse in horses:
            style = "unknown"
            if isinstance(horse, dict):
                style = self._normalize_lap(horse.get("lap_style"))
            counts[style] += 1

        if not any(counts.values()):
            return "unknown"
        best = max(counts, key=counts.get)
        return best if counts.get(best, 0) > 0 else "unknown"

    def _structure_flags(self, surface, distance, pace, course_shape, track_bias, lap_profile, data):
        dist = distance or 0
        limited = not data or not distance or surface == "unknown"
        return {
            "is_sprint": bool(dist and dist <= 1400),
            "is_mile": bool(1500 <= dist <= 1800),
            "is_middle_distance": bool(1801 <= dist <= 2200),
            "is_long_distance": bool(dist >= 2201),
            "is_turf": surface == "turf",
            "is_dirt": surface == "dirt",
            "is_one_turn": course_shape in {"long_straight_one_turn", "sprint", "dirt_sprint"},
            "is_two_turn": course_shape in {"two_turn", "small_turn"},
            "is_long_straight": course_shape == "long_straight_one_turn",
            "is_small_turn": course_shape == "small_turn",
            "is_high_pace": pace in {"fast", "very_fast"},
            "is_slow_pace": pace == "slow",
            "is_bias_available": track_bias not in {"", "unknown", "neutral"},
            "is_lap_profile_clear": lap_profile not in {"", "unknown"},
            "is_information_limited": limited,
        }

    def _key_factors(self, surface, distance, pace, pace_pressure, course_shape, draw_impact, track_bias, lap_profile, flags):
        factors = []

        if course_shape != "unknown":
            factors.append("course_shape")
        if pace != "unknown" or pace_pressure != "unknown":
            factors.append("pace")
            factors.append("positioning")
        if draw_impact in {"high", "moderate"}:
            factors.append("draw")
        if track_bias != "neutral":
            factors.append("track_bias")
        if lap_profile != "unknown":
            factors.append("lap_suitability")
        if distance:
            factors.append("distance_fit")
        if surface in {"turf", "dirt"}:
            factors.append("track_condition")
            factors.append("bloodline_fit")
        if flags.get("is_long_distance"):
            factors.append("stamina")
        if flags.get("is_sprint") or pace_pressure in {"high", "very_high"}:
            factors.append("early_speed")
        if flags.get("is_long_straight"):
            factors.append("late_speed")
        if course_shape in {"small_turn", "two_turn"}:
            factors.append("sustained_speed")

        unique = []
        for factor in factors:
            if factor not in unique:
                unique.append(factor)
        if len(unique) < 3:
            unique.append("general_ability")
        return unique

    def _recommended_weights_hint(self, key_factors, pace_pressure, track_bias, flags):
        weights = {
            "course_shape_score": 1.0,
            "shape_score": 1.0,
            "track_bias_score": 1.0,
            "lap_score": 1.0,
            "distance_score": 1.0,
            "bloodline_score": 1.0,
            "past_score": 1.0,
        }

        if "lap_suitability" in key_factors:
            weights["lap_score"] = 1.3
        if "course_shape" in key_factors:
            weights["course_shape_score"] = 1.3
        if pace_pressure in {"high", "very_high"}:
            weights["shape_score"] = 1.25
        if track_bias not in {"", "unknown", "neutral"}:
            weights["track_bias_score"] = 1.3
        if flags.get("is_long_distance"):
            weights["distance_score"] = 1.2
        if flags.get("is_information_limited"):
            weights["past_score"] = 1.1
        if "bloodline_fit" in key_factors and (flags.get("is_dirt") or flags.get("is_long_distance")):
            weights["bloodline_score"] = 1.1
        return weights

    def _comment_parts(self, race_structure, flags, data):
        parts = [
            race_structure.get("course") or "course unknown",
            f"pace={race_structure.get('pace')}",
            f"pressure={race_structure.get('pace_pressure')}",
            f"course_shape={race_structure.get('course_shape')}",
        ]

        if flags.get("is_long_straight"):
            parts.append("直線の長さを評価")
        if flags.get("is_small_turn"):
            parts.append("小回りで位置取りと持続力を評価")
        if race_structure.get("draw_impact") in {"high", "moderate"}:
            parts.append("枠順影響を確認")
        if race_structure.get("track_bias") != "neutral":
            parts.append("当日バイアスを確認")
        if flags.get("is_lap_profile_clear"):
            parts.append(f"ラップ質={race_structure.get('lap_profile')}")
        if flags.get("is_information_limited"):
            parts.append("一部の構造情報が不足")
        if data.get("bias_comment"):
            parts.append(str(data.get("bias_comment")))
        return parts

    def _structure_comment(self, parts, flags):
        base = " / ".join(str(part) for part in parts if part)
        if not base:
            base = "レース構造情報が不足しているため、中立的に整理します。"
        if flags.get("is_information_limited"):
            return f"{base}。一部の構造情報が不足しているため、中立的に評価します。"
        return f"{base}。今回のレース構造として重要な評価要素を整理しました。"

    def _course_label(self, racecourse, surface, distance):
        course = racecourse or "unknown"
        surf = {"turf": "芝", "dirt": "ダート"}.get(surface, surface or "unknown")
        dist = f"{distance}m" if distance else "距離不明"
        return f"{course} {surf} {dist}"

    def _normalize_racecourse(self, value):
        text = self._text(value).lower()
        mapping = {
            "東京": "tokyo",
            "中山": "nakayama",
            "中京": "chukyo",
            "京都": "kyoto",
            "阪神": "hanshin",
            "福島": "fukushima",
            "函館": "hakodate",
            "小倉": "kokura",
            "札幌": "sapporo",
            "新潟": "niigata",
        }
        from evaluation.course_name_normalizer import normalize_course_name

        return normalize_course_name(mapping.get(text, text))

    def _normalize_surface(self, value):
        text = self._text(value).lower()
        if text in {"芝", "turf"}:
            return "turf"
        if text in {"ダート", "ダ", "dirt"}:
            return "dirt"
        return "unknown"

    def _normalize_pace(self, value):
        text = self._text(value).lower()
        mapping = {"スロー": "slow", "平均": "average", "ミドル": "average", "ハイ": "fast"}
        text = mapping.get(text, text)
        return text if text in {"slow", "average", "fast", "very_fast"} else "unknown"

    def _normalize_style(self, value):
        text = self._text(value).lower()
        return text if text in self.STYLE_KEYS else "unknown"

    def _normalize_lap(self, value):
        text = self._text(value).lower()
        mapping = {
            "瞬発戦": "instant",
            "持続戦": "sustained",
            "消耗戦": "attrition",
            "バランス": "balanced",
        }
        text = mapping.get(text, text)
        return text if text in {"instant", "sustained", "attrition", "balanced"} else "unknown"

    def _is_truthy_bias(self, value):
        text = self._text(value).lower()
        return text in {"1", "true", "yes", "y", "有", "あり", "強い", "front", "inside", "outside", "closer"}

    def _safe_int(self, value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        try:
            return int(float(str(value).replace("m", "").strip()))
        except (TypeError, ValueError):
            return None

    def _text(self, value):
        if value is None:
            return ""
        return str(value).strip()


if __name__ == "__main__":
    engine = RaceStructureEngine()
    sample = {
        "racecourse": "東京",
        "surface": "芝",
        "distance": 1600,
        "track_condition": "良",
        "pace_prediction": "average",
        "escape_count": 1,
        "front_count": 3,
        "stalk_count": 4,
        "closer_count": 5,
        "deep_closer_count": 2,
        "horses": [
            {"horse_name": "sample_a", "pace_style": "front", "lap_style": "instant"},
            {"horse_name": "sample_b", "pace_style": "closer", "lap_style": "instant"},
        ],
    }
    print(engine.analyze(sample))
