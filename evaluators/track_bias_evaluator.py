"""Evaluate same-day track bias fit for each horse.

This trial evaluator combines track-bias inputs such as inside/outside and
front/closer bias with a horse's running style and draw.  It is deliberately
safe: when same-day bias data is missing, it returns a neutral score instead of
guessing.
"""


class TrackBiasEvaluator:
    """Score how well each horse matches the day's track bias."""

    NEUTRAL_COMMENT = "馬場バイアス情報が不足しているため中立"

    STYLE_LABELS = {
        "escape": "逃げ",
        "front": "先行",
        "stalk": "好位",
        "closer": "差し",
        "deep_closer": "追込",
        "unknown": "判定不能",
    }

    def evaluate(self, horse=None, race_bias=None):
        """Evaluate one horse against same-day track bias information."""

        horse_data = horse if isinstance(horse, dict) else {}
        bias_data = self._collect_bias_data(horse_data, race_bias)

        pace_style = self._normalize_style(horse_data.get("pace_style"))
        gate = self._safe_int(
            horse_data.get("gate")
            or horse_data.get("frame_number")
            or horse_data.get("枠番")
        )
        track_condition = (
            horse_data.get("track_condition")
            or bias_data.get("track_condition")
            or horse_data.get("condition")
        )

        if not self._has_bias_information(bias_data):
            return self._neutral_result(horse_data, pace_style, gate, track_condition)

        score = 0
        reasons = []

        score += self._front_back_score(pace_style, bias_data, reasons)
        score += self._inside_outside_score(gate, pace_style, bias_data, reasons)
        score += self._condition_score(track_condition, pace_style, bias_data, reasons)

        score = self._clamp(score, -10, 10)
        comment = self._build_comment(score, reasons, bias_data)

        return {
            "horse_name": horse_data.get("horse_name") or horse_data.get("name"),
            "pace_style": pace_style,
            "pace_style_label": self.STYLE_LABELS.get(pace_style, "判定不能"),
            "gate": gate,
            "track_condition": track_condition,
            "track_bias_score": score,
            "track_bias_comment": comment,
            "track_bias_reasons": reasons,
            "track_bias_matched": True,
        }

    def evaluate_many(self, horses=None, race_bias=None):
        """Evaluate many horses while preserving input order."""

        rows = horses if isinstance(horses, list) else []
        return [self.evaluate(horse=row, race_bias=race_bias) for row in rows]

    def format_report(self, track_bias_results):
        """Create a readable table for trial checks."""

        rows = track_bias_results if isinstance(track_bias_results, list) else []
        lines = [
            "==================",
            "Track Bias",
            "==================",
            "馬名 | Style | Gate | Score | Comment",
        ]
        for row in rows:
            if not isinstance(row, dict):
                row = {}
            lines.append(
                f"{row.get('horse_name') or '-'} | "
                f"{row.get('pace_style_label') or '-'} | "
                f"{row.get('gate') or '-'} | "
                f"{row.get('track_bias_score', 0)} | "
                f"{row.get('track_bias_comment') or '-'}"
            )
        return "\n".join(lines)

    def _collect_bias_data(self, horse_data, race_bias):
        data = {}
        if isinstance(race_bias, dict):
            data.update(race_bias)
        for key in [
            "track_bias",
            "inside_bias",
            "outside_bias",
            "front_bias",
            "closer_bias",
            "bias_comment",
            "track_condition",
            "surface",
            "course",
            "racecourse",
            "distance",
        ]:
            if key in horse_data and horse_data.get(key) not in (None, ""):
                data[key] = horse_data.get(key)
        return data

    def _has_bias_information(self, bias_data):
        if not isinstance(bias_data, dict):
            return False
        for key in ["track_bias", "inside_bias", "outside_bias", "front_bias", "closer_bias"]:
            value = bias_data.get(key)
            if value not in (None, "", False, "false", "False", "なし", "不明"):
                return True
        return False

    def _front_back_score(self, style, bias_data, reasons):
        score = 0
        if self._truthy(bias_data.get("front_bias")) or self._contains_bias(
            bias_data.get("track_bias"),
            ["前", "前残り", "front"],
        ):
            if style == "escape":
                score += 4
                reasons.append("当日の前残り傾向と逃げ脚質が噛み合う")
            elif style == "front":
                score += 4
                reasons.append("当日の前残り傾向と先行脚質が噛み合う")
            elif style == "stalk":
                score += 2
                reasons.append("前有利馬場で好位から運べる")
            elif style == "closer":
                score -= 2
                reasons.append("前有利馬場で差し脚質は少し割引")
            elif style == "deep_closer":
                score -= 4
                reasons.append("前有利馬場で追込脚質は割引")

        if self._truthy(bias_data.get("closer_bias")) or self._contains_bias(
            bias_data.get("track_bias"),
            ["差し", "外差し", "closer"],
        ):
            if style == "closer":
                score += 4
                reasons.append("差し有利の馬場で末脚を活かせる")
            elif style == "deep_closer":
                score += 4
                reasons.append("差し有利の馬場で追込も届きやすい")
            elif style == "stalk":
                score += 2
                reasons.append("差し有利でも好位なら対応しやすい")
            elif style == "escape":
                score -= 4
                reasons.append("差し有利馬場で逃げは割引")
            elif style == "front":
                score -= 2
                reasons.append("差し有利馬場で先行は少し割引")
        return score

    def _inside_outside_score(self, gate, style, bias_data, reasons):
        if gate is None:
            return 0

        score = 0
        is_inner = gate <= 3
        is_middle = 4 <= gate <= 6
        is_outer = gate >= 7

        if self._truthy(bias_data.get("inside_bias")) or self._contains_bias(
            bias_data.get("track_bias"),
            ["内", "inside"],
        ):
            if is_inner:
                score += 3
                reasons.append("内有利馬場で内枠を評価")
                if style in {"escape", "front"}:
                    score += 2
                    reasons.append("内枠先行で位置取りが噛み合う")
            elif is_outer:
                score -= 3
                reasons.append("内有利馬場で外枠は距離ロスに注意")

        if self._truthy(bias_data.get("outside_bias")) or self._contains_bias(
            bias_data.get("track_bias"),
            ["外", "外差し", "outside"],
        ):
            if is_outer:
                score += 3
                reasons.append("外有利馬場で外枠を評価")
                if style in {"closer", "deep_closer"}:
                    score += 2
                    reasons.append("外差し馬場で末脚を活かせる")
            elif is_inner and style in {"closer", "deep_closer"}:
                score -= 2
                reasons.append("外有利馬場だが内枠差しで進路に課題")
            elif is_middle:
                score += 1
                reasons.append("外有利馬場でも中枠なら対応可能")
        return score

    def _condition_score(self, condition, style, bias_data, reasons):
        text = str(condition or "").strip()
        if not text:
            return 0

        score = 0
        if text in {"稍重", "yielding"} and style in {"escape", "front", "stalk"}:
            score += 1
            reasons.append("稍重で先行力を少し評価")
        elif text in {"重", "heavy"} and (
            self._truthy(bias_data.get("front_bias")) or style in {"escape", "front"}
        ):
            score += 2
            reasons.append("重馬場で前に行ける点を評価")
        elif text in {"不良", "soft"} and style in {"escape", "front"}:
            score += 1
            reasons.append("不良馬場でスピードを活かせる可能性")
        return score

    def _neutral_result(self, horse_data, pace_style, gate, track_condition):
        return {
            "horse_name": horse_data.get("horse_name") or horse_data.get("name"),
            "pace_style": pace_style,
            "pace_style_label": self.STYLE_LABELS.get(pace_style, "判定不能"),
            "gate": gate,
            "track_condition": track_condition,
            "track_bias_score": 0,
            "track_bias_comment": self.NEUTRAL_COMMENT,
            "track_bias_reasons": [self.NEUTRAL_COMMENT],
            "track_bias_matched": False,
        }

    def _build_comment(self, score, reasons, bias_data):
        if bias_data.get("bias_comment"):
            reasons.append(str(bias_data.get("bias_comment")))

        if score >= 8:
            base = "当日のトラックバイアスがかなり向く"
        elif score >= 4:
            base = "当日のトラックバイアスがやや向く"
        elif score <= -8:
            base = "当日のトラックバイアスがかなり不向き"
        elif score <= -4:
            base = "当日のトラックバイアスに課題"
        else:
            base = "トラックバイアスは普通"

        if reasons:
            return f"{base}。{reasons[0]}"
        return base

    def _truthy(self, value):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower() if value is not None else ""
        return text in {"1", "true", "yes", "on", "有", "あり", "有利"}

    def _contains_bias(self, value, keywords):
        text = str(value or "").lower()
        return any(str(keyword).lower() in text for keyword in keywords)

    def _normalize_style(self, value):
        text = str(value).strip().lower() if value is not None else "unknown"
        return text if text in self.STYLE_LABELS else "unknown"

    def _safe_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _clamp(self, value, minimum, maximum):
        return max(minimum, min(maximum, value))


if __name__ == "__main__":
    evaluator = TrackBiasEvaluator()
    horses = [
        {"horse_name": "inner_front", "pace_style": "front", "gate": 2},
        {"horse_name": "outer_closer", "pace_style": "closer", "gate": 8},
        {"horse_name": "unknown_bias", "pace_style": "escape", "gate": 1},
    ]
    bias = {"inside_bias": True, "front_bias": True, "track_condition": "稍重"}
    print(evaluator.format_report(evaluator.evaluate_many(horses[:2], bias)))
    print()
    print(evaluator.format_report(evaluator.evaluate_many(horses[2:], {})))
