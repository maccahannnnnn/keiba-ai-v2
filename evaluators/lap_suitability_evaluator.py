"""Evaluate lap suitability from recent runs and expected race structure.

This evaluator is a trial-layer component.  It uses recent TARGET history data
such as PCI, RPCI, last 3F, corner positions, and the predicted race pace to
explain whether a horse fits an instant, sustained, or attrition race.
"""


class LapSuitabilityEvaluator:
    """Judge lap style and score fit to the expected race type."""

    NEUTRAL_COMMENT = "ラップ情報不足のため中立"

    STYLE_LABELS = {
        "instant": "瞬発戦",
        "sustained": "持続戦",
        "attrition": "消耗戦",
        "balanced": "バランス型",
        "unknown": "判定不能",
    }

    SCORE_MATRIX = {
        "instant": {
            "instant": 9,
            "sustained": 2,
            "attrition": -5,
            "balanced": 2,
            "unknown": 0,
        },
        "sustained": {
            "instant": 1,
            "sustained": 8,
            "attrition": 3,
            "balanced": 3,
            "unknown": 0,
        },
        "attrition": {
            "instant": -5,
            "sustained": 3,
            "attrition": 9,
            "balanced": 2,
            "unknown": 0,
        },
        "balanced": {
            "instant": 2,
            "sustained": 3,
            "attrition": 2,
            "balanced": 1,
            "unknown": 0,
        },
    }

    INSTANT_COURSES = {"tokyo", "niigata", "kyoto"}
    SUSTAINED_COURSES = {"hanshin", "nakayama", "chukyo"}
    ATTRITION_COURSES = {"fukushima", "hakodate", "sapporo", "kokura"}

    def evaluate(self, horse=None, pace_result=None, race_context=None):
        """Evaluate one horse's lap suitability."""

        horse_data = horse if isinstance(horse, dict) else {}
        pace_data = pace_result if isinstance(pace_result, dict) else {}
        context = race_context if isinstance(race_context, dict) else {}

        runs = self._runs(horse_data)
        metrics = self._collect_metrics(runs)
        if not metrics["has_data"]:
            return self._empty_result(horse_data)

        horse_lap_style, horse_reasons = self._classify_horse_lap_style(
            metrics,
            horse_data,
        )
        expected_lap_style = self._expected_lap_style(horse_data, pace_data, context)
        lap_score = self.SCORE_MATRIX.get(expected_lap_style, {}).get(horse_lap_style, 0)

        lap_score += self._small_adjustments(horse_lap_style, horse_data, metrics)
        lap_score = self._clamp(lap_score, -10, 10)
        lap_comment = self._build_comment(
            lap_score,
            horse_lap_style,
            expected_lap_style,
            horse_reasons,
        )

        return {
            "horse_name": horse_data.get("horse_name") or horse_data.get("name"),
            "lap_style": horse_lap_style,
            "expected_lap_style": expected_lap_style,
            "lap_score": lap_score,
            "lap_comment": lap_comment,
            "lap_reasons": horse_reasons,
            "lap_matched": True,
        }

    def evaluate_many(self, horses=None, pace_result=None, race_context=None):
        """Evaluate many horses while preserving input order."""

        rows = horses if isinstance(horses, list) else []
        return [
            self.evaluate(horse=row, pace_result=pace_result, race_context=race_context)
            for row in rows
        ]

    def format_report(self, lap_results):
        """Create a readable table for trial checks."""

        rows = lap_results if isinstance(lap_results, list) else []
        lines = [
            "==================",
            "Lap Suitability",
            "==================",
            "馬名 | LapStyle | Expected | Score | Comment",
        ]
        for row in rows:
            if not isinstance(row, dict):
                row = {}
            lines.append(
                f"{row.get('horse_name') or '-'} | "
                f"{row.get('lap_style') or 'unknown'} | "
                f"{row.get('expected_lap_style') or 'unknown'} | "
                f"{row.get('lap_score', 0)} | "
                f"{row.get('lap_comment') or '-'}"
            )
        return "\n".join(lines)

    def _runs(self, horse_data):
        for key in ["past_performances", "recent_runs", "history_runs"]:
            value = horse_data.get(key)
            if isinstance(value, list):
                return [run for run in value[:5] if isinstance(run, dict)]
        return []

    def _collect_metrics(self, runs):
        pci_values = [self._to_float(run.get("pci")) for run in runs]
        rpci_values = [self._to_float(run.get("rpci")) for run in runs]
        last_3f_values = [self._to_float(run.get("last_3f")) for run in runs]
        corner_1_values = [self._to_int(run.get("corner_1")) for run in runs]
        corner_4_values = [self._to_int(run.get("corner_4")) for run in runs]
        finishes = [self._to_int(run.get("finish_position")) for run in runs]

        pci_values = [value for value in pci_values if value is not None]
        rpci_values = [value for value in rpci_values if value is not None]
        last_3f_values = [value for value in last_3f_values if value is not None and value > 0]
        corner_pairs = [
            (corner_1, corner_4)
            for corner_1, corner_4 in zip(corner_1_values, corner_4_values)
            if corner_1 is not None and corner_4 is not None and corner_4 > 0
        ]
        finishes = [value for value in finishes if value is not None and value > 0]

        return {
            "has_data": bool(pci_values or rpci_values or last_3f_values or corner_pairs),
            "pci_values": pci_values,
            "rpci_values": rpci_values,
            "last_3f_values": last_3f_values,
            "corner_pairs": corner_pairs,
            "finishes": finishes,
        }

    def _classify_horse_lap_style(self, metrics, horse_data):
        scores = {"instant": 0, "sustained": 0, "attrition": 0}
        reasons = []

        pci_avg = self._average(metrics["pci_values"])
        rpci_values = metrics["rpci_values"]
        last_3f_avg = self._average(metrics["last_3f_values"])
        last_3f_spread = self._spread(metrics["last_3f_values"])

        if pci_avg is not None:
            if pci_avg >= 52:
                scores["instant"] += 3
                reasons.append("PCIが高く瞬発力を示す")
            elif pci_avg <= 45:
                scores["attrition"] += 3
                reasons.append("PCIが低めで消耗戦耐性を示す")
            else:
                scores["sustained"] += 1
                reasons.append("PCIは中庸で持続型寄り")

        if rpci_values:
            if self._spread(rpci_values) <= 5:
                scores["sustained"] += 3
                reasons.append("RPCIが安定しており持続戦向き")
            if self._average(rpci_values) is not None and self._average(rpci_values) <= 45:
                scores["attrition"] += 2
                reasons.append("RPCIが厳しい流れへの対応を示す")

        if last_3f_avg is not None:
            if last_3f_avg <= 37.0:
                scores["instant"] += 3
                reasons.append("上がり3Fが速く瞬発力を評価")
            elif last_3f_spread is not None and last_3f_spread <= 1.0:
                scores["sustained"] += 2
                reasons.append("上がりが安定して長く脚を使える")
            elif last_3f_avg >= 39.0:
                scores["attrition"] += 1
                reasons.append("上がりの掛かる競馬を経験")

        front_count = 0
        move_up_count = 0
        for corner_1, corner_4 in metrics["corner_pairs"]:
            if corner_4 <= 4:
                front_count += 1
            if corner_1 - corner_4 >= 2:
                move_up_count += 1
        if front_count:
            scores["sustained"] += min(3, front_count)
            reasons.append("先行しながら粘る形を確認")
        if move_up_count:
            scores["attrition"] += min(3, move_up_count)
            reasons.append("早め進出できる消耗戦向き要素を確認")

        pace_style = self._normalize_style(horse_data.get("pace_style"))
        if pace_style in {"front", "stalk"}:
            scores["sustained"] += 1
        elif pace_style in {"closer", "deep_closer"}:
            scores["instant"] += 1
        elif pace_style == "escape":
            scores["attrition"] += 1

        best_style = max(scores, key=scores.get)
        best_score = scores[best_style]
        sorted_scores = sorted(scores.values(), reverse=True)
        if best_score <= 2 or (len(sorted_scores) >= 2 and best_score - sorted_scores[1] <= 1):
            return "balanced", reasons or ["明確なラップ特徴は薄い"]
        return best_style, reasons or ["ラップ適性を判定"]

    def _expected_lap_style(self, horse_data, pace_data, context):
        pace = self._normalize_pace(
            horse_data.get("pace_prediction")
            or pace_data.get("pace_prediction")
            or context.get("pace_prediction")
            or context.get("pace")
        )
        racecourse = str(
            horse_data.get("racecourse")
            or horse_data.get("course")
            or context.get("racecourse")
            or context.get("course")
            or ""
        ).lower()
        surface = str(horse_data.get("surface") or context.get("surface") or "").lower()
        distance = self._to_int(horse_data.get("distance") or context.get("distance"))
        course_shape_score = self._to_float(horse_data.get("course_shape_score"))

        if pace in {"fast", "very_fast"}:
            return "attrition"
        if pace == "slow" and racecourse in self.INSTANT_COURSES and surface in {"turf", "芝"}:
            return "instant"
        if racecourse in self.ATTRITION_COURSES:
            return "attrition"
        if racecourse in self.SUSTAINED_COURSES:
            return "sustained"
        if surface in {"dirt", "ダート"} and distance is not None and distance >= 1700:
            return "attrition"
        if surface in {"dirt", "ダート"}:
            return "sustained"
        if course_shape_score is not None and course_shape_score >= 6:
            return "sustained"
        return "balanced"

    def _small_adjustments(self, lap_style, horse_data, metrics):
        adjustment = 0
        course_shape_score = self._to_float(horse_data.get("course_shape_score"))
        if course_shape_score is not None:
            if course_shape_score >= 8 and lap_style in {"sustained", "attrition"}:
                adjustment += 1
            elif course_shape_score <= -4 and lap_style == "instant":
                adjustment -= 1

        finishes = metrics.get("finishes") or []
        if finishes and sum(1 for finish in finishes if finish <= 5) >= 2:
            adjustment += 1
        return adjustment

    def _empty_result(self, horse_data):
        return {
            "horse_name": horse_data.get("horse_name") or horse_data.get("name"),
            "lap_style": "unknown",
            "expected_lap_style": "unknown",
            "lap_score": 0,
            "lap_comment": self.NEUTRAL_COMMENT,
            "lap_reasons": [self.NEUTRAL_COMMENT],
            "lap_matched": False,
        }

    def _build_comment(self, score, lap_style, expected_lap_style, reasons):
        style_label = self.STYLE_LABELS.get(lap_style, "判定不能")
        expected_label = self.STYLE_LABELS.get(expected_lap_style, "判定不能")

        if score >= 8:
            base = f"今回想定ラップと一致する。{style_label}適性が高い"
        elif score >= 4:
            base = f"{style_label}で能力を発揮しやすい"
        elif score <= -8:
            base = f"今回想定ラップとは大きく噛み合わない"
        elif score <= -4:
            base = f"今回想定ラップとは噛み合いにくい"
        else:
            base = f"{expected_label}想定に対してラップ適性は普通"

        if reasons:
            return f"{base}。{reasons[0]}"
        return base

    def _normalize_pace(self, value):
        text = str(value).strip().lower() if value is not None else "average"
        return text if text in {"slow", "average", "fast", "very_fast"} else "average"

    def _normalize_style(self, value):
        text = str(value).strip().lower() if value is not None else "unknown"
        if text in {"escape", "front", "stalk", "closer", "deep_closer"}:
            return text
        return "unknown"

    def _to_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _average(self, values):
        return sum(values) / len(values) if values else None

    def _spread(self, values):
        return max(values) - min(values) if len(values) >= 2 else 0 if values else None

    def _clamp(self, value, minimum, maximum):
        return max(minimum, min(maximum, value))


if __name__ == "__main__":
    evaluator = LapSuitabilityEvaluator()
    sample = {
        "horse_name": "sample",
        "pace_style": "front",
        "racecourse": "kokura",
        "surface": "dirt",
        "distance": 1700,
        "course_shape_score": 8,
        "recent_runs": [
            {"pci": "48.2", "rpci": "47.5", "last_3f": "38.4", "corner_1": "3", "corner_4": "3", "finish_position": "2"},
            {"pci": "45.0", "rpci": "46.1", "last_3f": "39.0", "corner_1": "6", "corner_4": "3", "finish_position": "4"},
        ],
    }
    print(evaluator.format_report([evaluator.evaluate(sample, {"pace_prediction": "average"}, sample)]))
