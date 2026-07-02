"""Evaluate the structural fit between course shape, pace, style, and draw.

This evaluator is part of the trial Evaluation Engine layer.  It reads course
knowledge when available, but it never modifies Knowledge Base data and never
touches the production Analyzer, importer, CSV format, Self Review Engine, or
main.py.
"""

from evaluation.course_evaluator import CourseEvaluator


class CourseShapeEvaluator:
    """Score how well a horse fits the expected race structure."""

    NEUTRAL_COMMENT = "構造評価に必要な情報が不足しているため中立"

    STYLE_LABELS = {
        "escape": "逃げ",
        "front": "先行",
        "stalk": "好位",
        "closer": "差し",
        "deep_closer": "追込",
        "unknown": "判定不能",
    }

    FORWARD_STYLES = {"escape", "front", "stalk"}
    CLOSING_STYLES = {"closer", "deep_closer"}

    def __init__(self):
        self.course_evaluator = CourseEvaluator()

    def evaluate(self, horse=None, pace_result=None, race_context=None):
        """Evaluate one horse and return course_shape_score/comment."""

        horse_data = horse if isinstance(horse, dict) else {}
        pace_data = pace_result if isinstance(pace_result, dict) else {}
        context = race_context if isinstance(race_context, dict) else {}

        pace_prediction = self._normalize_pace(
            horse_data.get("pace_prediction")
            or pace_data.get("pace_prediction")
            or context.get("pace_prediction")
        )
        pace_style = self._normalize_style(horse_data.get("pace_style"))
        gate = self._safe_int(
            horse_data.get("gate")
            or horse_data.get("frame_number")
            or horse_data.get("枠番")
        )
        racecourse = (
            horse_data.get("course")
            or horse_data.get("racecourse")
            or context.get("racecourse")
            or context.get("course")
        )
        surface = horse_data.get("surface") or context.get("surface")
        distance = self._safe_int(horse_data.get("distance") or context.get("distance"))

        profile = self._find_course_profile(racecourse, surface, distance)
        if profile is None or pace_style == "unknown":
            return self._neutral_result(
                horse_data,
                pace_prediction,
                pace_style,
                gate,
                racecourse,
                surface,
                distance,
            )

        course_info = self._course_info(profile)
        score = 0
        reasons = []

        score += self._pace_style_score(pace_prediction, pace_style, course_info, reasons)
        score += self._course_style_score(pace_style, course_info, reasons)
        score += self._draw_score(gate, pace_style, course_info, surface, distance, reasons)

        score = self._clamp(score, -10, 10)
        comment = self._build_comment(score, reasons)

        return {
            "horse_name": horse_data.get("horse_name") or horse_data.get("name"),
            "pace_prediction": pace_prediction,
            "pace_style": pace_style,
            "pace_style_label": self.STYLE_LABELS.get(pace_style, "判定不能"),
            "gate": gate,
            "course": racecourse,
            "surface": surface,
            "distance": distance,
            "course_shape_score": score,
            "course_shape_comment": comment,
            "course_shape_reasons": reasons,
            "course_profile_matched": True,
        }

    def evaluate_many(self, horses=None, pace_result=None, race_context=None):
        """Evaluate many horses while preserving input order."""

        rows = horses if isinstance(horses, list) else []
        return [
            self.evaluate(horse=row, pace_result=pace_result, race_context=race_context)
            for row in rows
        ]

    def format_report(self, course_shape_results):
        """Create a readable table for trial checks."""

        rows = course_shape_results if isinstance(course_shape_results, list) else []
        lines = [
            "==================",
            "Course Shape",
            "==================",
            "馬名 | Pace | Style | Gate | Score | Comment",
        ]
        for row in rows:
            if not isinstance(row, dict):
                row = {}
            lines.append(
                f"{row.get('horse_name') or '-'} | "
                f"{row.get('pace_prediction') or '-'} | "
                f"{row.get('pace_style_label') or '-'} | "
                f"{row.get('gate') or '-'} | "
                f"{row.get('course_shape_score', 0)} | "
                f"{row.get('course_shape_comment') or '-'}"
            )
        return "\n".join(lines)

    def _find_course_profile(self, racecourse, surface, distance):
        if not racecourse or not surface or distance is None:
            return None
        try:
            course_info = self.course_evaluator._normalize_racecourse(racecourse)
            surface_info = self.course_evaluator._normalize_surface(surface)
            return self.course_evaluator._find_profile(course_info, surface_info, distance)
        except Exception:
            return None

    def _course_info(self, profile):
        text_parts = []
        for name in [
            "features",
            "course_shape",
            "pace_tendency",
            "closing_tendency",
            "frame_bias",
            "favorable_styles",
            "required_abilities",
            "cautions",
        ]:
            value = self._get_value(profile, name)
            text_parts.append(self._stringify(value))

        text = " ".join(part for part in text_parts if part)
        favorable_styles = self._get_value(profile, "favorable_styles")
        score_modifiers = self._get_value(profile, "score_modifiers")

        return {
            "text": text,
            "favorable_styles": favorable_styles if isinstance(favorable_styles, list) else [],
            "score_modifiers": score_modifiers if isinstance(score_modifiers, dict) else {},
            "small_turn": self._contains(text, ["小回り", "コーナー4回", "直線が短い", "ローカル"]),
            "long_straight": self._contains(text, ["直線が長い", "長い直線", "外回り", "大箱"]),
            "one_turn": self._contains(text, ["ワンターン", "芝スタート"]),
            "four_corners": self._contains(text, ["コーナー4回", "4回", "小回り"]),
            "inner_bias": self._contains(text, ["内枠", "内で", "内から中枠"]),
            "outer_bias": self._contains(text, ["外枠有利", "外差し", "外伸び", "芝スタート"]),
            "front_bias": self._contains(text, ["逃げ・先行有利", "前にいる馬", "前残り", "先行有利"]),
            "closing_bias": self._contains(text, ["差し", "追込", "末脚", "長い直線"]),
        }

    def _pace_style_score(self, pace, style, course_info, reasons):
        score = 0
        if pace in {"fast", "very_fast"}:
            if style in {"escape", "front"}:
                penalty = -3 if course_info["front_bias"] or course_info["small_turn"] else -5
                score += penalty
                reasons.append("速い流れで前に行く馬は負荷がかかる")
            elif style in self.CLOSING_STYLES:
                bonus = 5 if not course_info["small_turn"] else 3
                score += bonus
                reasons.append("速い流れで差し脚を活かしやすい")
        elif pace == "slow":
            if style in self.FORWARD_STYLES:
                score += 5
                reasons.append("スローで前の位置を取れる")
            elif style == "deep_closer":
                penalty = -2 if course_info["long_straight"] else -5
                score += penalty
                reasons.append("スローでは後方脚質が届きにくい")
        else:
            if style in {"front", "stalk", "closer"}:
                score += 3
                reasons.append("平均ペースで脚質が極端すぎない")
            elif style in {"escape", "deep_closer"}:
                score -= 1
                reasons.append("平均ペースでは極端な脚質を少し慎重評価")
        return score

    def _course_style_score(self, style, course_info, reasons):
        score = 0
        if course_info["small_turn"] or course_info["four_corners"]:
            if style in self.FORWARD_STYLES:
                score += 4
                reasons.append("小回り・コーナー型で位置取りが噛み合う")
            elif style == "deep_closer":
                score -= 4
                reasons.append("小回りで後方脚質は届きにくい")
            elif style == "closer":
                score -= 1
                reasons.append("小回りでは差しは早め進出が必要")

        if course_info["long_straight"]:
            if style in self.CLOSING_STYLES:
                score += 4
                reasons.append("直線の長さで差し脚を活かせる")
            elif style == "escape":
                score -= 2
                reasons.append("長い直線では逃げ切りに持続力が必要")

        if course_info["front_bias"] and style in self.FORWARD_STYLES:
            score += 2
            reasons.append("コース知識上、前に行く脚質を評価")

        if course_info["closing_bias"] and style in self.CLOSING_STYLES:
            score += 2
            reasons.append("コース知識上、差し脚質も評価")

        return score

    def _draw_score(self, gate, style, course_info, surface, distance, reasons):
        if gate is None:
            reasons.append("枠順情報が不足")
            return 0

        score = 0
        is_inner = gate <= 3
        is_middle = 4 <= gate <= 6
        is_outer = gate >= 7

        if course_info["inner_bias"]:
            if is_inner and style in self.FORWARD_STYLES:
                score += 3
                reasons.append("内枠と前目の位置取りが噛み合う")
            elif is_outer and style in self.CLOSING_STYLES:
                score -= 2
                reasons.append("外枠で外々を回されるリスク")

        if course_info["outer_bias"]:
            if is_outer and style in {"front", "stalk", "closer"}:
                score += 3
                reasons.append("外枠を活かしやすい構造")
            elif is_inner and style == "deep_closer":
                score -= 1
                reasons.append("内枠の追込は進路取りに注意")

        if not course_info["inner_bias"] and not course_info["outer_bias"]:
            if is_middle:
                score += 1
                reasons.append("枠順は大きな不利なく中立")

        if self._normalize_surface(surface) == "dirt" and distance in {1300, 1400, 1600}:
            if is_outer and style in {"front", "stalk"}:
                score += 2
                reasons.append("芝スタート寄りのダートで外枠先行を評価")

        return score

    def _neutral_result(self, horse_data, pace_prediction, pace_style, gate, racecourse, surface, distance):
        return {
            "horse_name": horse_data.get("horse_name") or horse_data.get("name"),
            "pace_prediction": pace_prediction,
            "pace_style": pace_style,
            "pace_style_label": self.STYLE_LABELS.get(pace_style, "判定不能"),
            "gate": gate,
            "course": racecourse,
            "surface": surface,
            "distance": distance,
            "course_shape_score": 0,
            "course_shape_comment": self.NEUTRAL_COMMENT,
            "course_shape_reasons": [self.NEUTRAL_COMMENT],
            "course_profile_matched": False,
        }

    def _build_comment(self, score, reasons):
        if score >= 8:
            base = "展開とコース形状がかなり向く"
        elif score >= 4:
            base = "展開とコース形状がやや向く"
        elif score <= -8:
            base = "展開とコース形状がかなり不向き"
        elif score <= -4:
            base = "展開またはコース形状に課題"
        else:
            base = "構造的には中立"

        if reasons:
            return f"{base}。{reasons[0]}"
        return base

    def _get_value(self, profile, name):
        if isinstance(profile, dict):
            return profile.get(name)
        return getattr(profile, name, None)

    def _stringify(self, value):
        if value is None:
            return ""
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        if isinstance(value, dict):
            return " ".join(f"{key}:{item}" for key, item in value.items())
        return str(value)

    def _contains(self, text, needles):
        return any(needle in text for needle in needles)

    def _normalize_pace(self, value):
        text = str(value).strip().lower() if value is not None else "average"
        return text if text in {"slow", "average", "fast", "very_fast"} else "average"

    def _normalize_style(self, value):
        text = str(value).strip().lower() if value is not None else "unknown"
        return text if text in self.STYLE_LABELS else "unknown"

    def _normalize_surface(self, value):
        text = str(value).strip().lower() if value is not None else ""
        if text in {"dirt", "ダート"}:
            return "dirt"
        if text in {"turf", "芝"}:
            return "turf"
        return text

    def _safe_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _clamp(self, value, minimum, maximum):
        return max(minimum, min(maximum, value))


if __name__ == "__main__":
    evaluator = CourseShapeEvaluator()
    horses = [
        {"horse_name": "front_sample", "pace_style": "front", "gate": 2},
        {"horse_name": "closer_sample", "pace_style": "closer", "gate": 8},
        {"horse_name": "unknown_sample", "pace_style": "unknown"},
    ]
    pace = {"pace_prediction": "average"}
    context = {"racecourse": "kokura", "surface": "dirt", "distance": 1700}
    print(evaluator.format_report(evaluator.evaluate_many(horses, pace, context)))
