"""Trial evaluator for distance suitability from recent TARGET history runs.

This module is part of the trial Evaluation Engine only.  It reads recent
history rows and judges whether today's distance fits the horse, without using
odds or popularity.
"""

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from evaluation.score_modifier_engine import ScoreModifierEngine


class DistanceSuitabilityEvaluator:
    """Evaluate distance fit from recent distances, results, margins, and corners."""

    SOURCE_TYPE = "distance"
    HISTORY_LIMIT = 5

    def evaluate(
        self,
        recent_runs=None,
        distance=None,
        surface=None,
        horse_name=None,
    ):
        """Return a ScoreModifierEngine-compatible distance evaluation."""

        runs = self._normalize_runs(recent_runs)[: self.HISTORY_LIMIT]
        target_distance = self._to_int(distance)
        source_name = f"distance_{horse_name or 'unknown'}"

        if not runs or target_distance is None:
            warning = f"distance unknown: {horse_name or 'unknown'}"
            return self._empty_result(source_name, horse_name, warning)

        distance_runs = [run for run in runs if self._to_int(run.get("distance")) is not None]
        if not distance_runs:
            warning = f"distance unknown: {horse_name or 'unknown'}"
            return self._empty_result(source_name, horse_name, warning)

        modifiers = {}
        reasons = {}
        explain_parts = []
        warnings = []

        self._score_same_distance(target_distance, distance_runs, modifiers, reasons, explain_parts)
        self._score_near_distance(target_distance, distance_runs, modifiers, reasons, explain_parts)
        self._score_distance_range(target_distance, distance_runs, modifiers, reasons, explain_parts)
        self._score_distance_change(target_distance, distance_runs, modifiers, reasons, explain_parts)
        self._score_distance_margin(target_distance, distance_runs, modifiers, reasons, explain_parts)
        self._score_distance_last_3f(target_distance, distance_runs, modifiers, reasons, explain_parts)
        self._score_distance_style(target_distance, distance_runs, modifiers, reasons, explain_parts)
        self._collect_missing_warnings(distance_runs, warnings)

        engine = ScoreModifierEngine()
        engine.add_modifiers(
            source_name=source_name,
            score_modifiers=modifiers,
            modifier_reasons=reasons,
            explain=" / ".join(explain_parts),
            source_type=self.SOURCE_TYPE,
        )
        summary = engine.get_summary()
        distance_score = summary.get("total_score", 0)

        result = {
            "horse_name": horse_name,
            "surface": surface,
            "distance": target_distance,
            "matched": True,
            "matched_sources": [source_name],
            "summary": summary,
            "distance_score": distance_score,
            "distance_fit": self._distance_fit(distance_score),
            "distance_fit_label": self._distance_fit_label(distance_score),
            "history_count": len(runs),
            "distance_history_count": len(distance_runs),
            "warnings": warnings,
        }
        if warnings:
            result["warning"] = "; ".join(warnings)
        return result

    def _empty_result(self, source_name, horse_name=None, warning=None):
        summary = {
            "total_score": 0,
            "modifiers": {},
            "reasons": [],
            "explains": [],
            "source_type_summary": {},
        }
        result = {
            "horse_name": horse_name,
            "matched": False,
            "matched_sources": [],
            "summary": summary,
            "distance_score": 0,
            "distance_fit": "unknown",
            "distance_fit_label": "判定不能",
            "history_count": 0,
            "distance_history_count": 0,
            "warnings": [warning] if warning else [],
        }
        if warning:
            result["warning"] = warning
        return result

    def _score_same_distance(self, target_distance, runs, modifiers, reasons, explain_parts):
        same_runs = [run for run in runs if self._to_int(run.get("distance")) == target_distance]
        good_runs = [run for run in same_runs if self._is_good_run(run)]
        if not same_runs:
            return

        score = 4
        if good_runs:
            score += 6

        self._add_modifier(
            modifiers,
            reasons,
            "same_distance_record",
            score,
            f"同距離{target_distance}mを{len(same_runs)}走、好内容{len(good_runs)}走として評価",
        )
        explain_parts.append(f"同距離{target_distance}mは{len(same_runs)}走、好内容{len(good_runs)}走")

    def _score_near_distance(self, target_distance, runs, modifiers, reasons, explain_parts):
        near_runs = [
            run
            for run in runs
            if self._distance_diff(target_distance, run) is not None
            and 0 < self._distance_diff(target_distance, run) <= 200
        ]
        good_runs = [run for run in near_runs if self._is_good_run(run)]
        bad_runs = [run for run in near_runs if self._is_bad_run(run)]
        if not near_runs:
            return

        score = 0
        if good_runs:
            score += min(7, 3 + len(good_runs) * 2)
        if len(bad_runs) >= 2:
            score -= 5
        elif len(bad_runs) == 1:
            score -= 2

        self._add_modifier(
            modifiers,
            reasons,
            "near_distance_record",
            score,
            f"近似距離±200mを{len(near_runs)}走、好内容{len(good_runs)}走、大敗{len(bad_runs)}走として評価",
        )
        explain_parts.append(f"近似距離は{len(near_runs)}走、好内容{len(good_runs)}走")

    def _score_distance_range(self, target_distance, runs, modifiers, reasons, explain_parts):
        distances = [self._to_int(run.get("distance")) for run in runs]
        distances = [value for value in distances if value is not None]
        if not distances:
            return

        minimum = min(distances)
        maximum = max(distances)
        score = 0

        if minimum <= target_distance <= maximum:
            score += 7
            reason = "今回距離が近走の距離レンジ内"
        elif target_distance < minimum:
            score -= 3
            reason = "今回距離が近走レンジより短い"
        else:
            score -= 5
            reason = "今回距離が近走レンジより長い"

        self._add_modifier(
            modifiers,
            reasons,
            "distance_range_fit",
            score,
            f"{reason}。近走レンジ{minimum}-{maximum}m",
        )
        explain_parts.append(f"距離レンジは{minimum}-{maximum}mで今回{target_distance}m")

    def _score_distance_change(self, target_distance, runs, modifiers, reasons, explain_parts):
        latest_distance = self._to_int(runs[0].get("distance"))
        if latest_distance is None:
            return

        difference = target_distance - latest_distance
        score = 0
        if abs(difference) <= 100:
            score += 3
            change_text = "ほぼ同距離"
        elif difference > 0:
            longer_experience = any(
                (self._to_int(run.get("distance")) or 0) >= target_distance - 200
                and not self._is_bad_run(run)
                for run in runs[1:]
            )
            score += 3 if longer_experience else -4
            change_text = "距離延長"
        else:
            shorter_experience = any(
                (self._to_int(run.get("distance")) or 99999) <= target_distance + 200
                and not self._is_bad_run(run)
                for run in runs[1:]
            )
            score += 3 if shorter_experience else -3
            change_text = "距離短縮"

        self._add_modifier(
            modifiers,
            reasons,
            "distance_change_fit",
            score,
            f"前走{latest_distance}mから今回{target_distance}mへの{change_text}を評価",
        )
        explain_parts.append(f"前走{latest_distance}mから今回は{change_text}")

    def _score_distance_margin(self, target_distance, runs, modifiers, reasons, explain_parts):
        target_runs = [
            run
            for run in runs
            if self._distance_diff(target_distance, run) is not None
            and self._distance_diff(target_distance, run) <= 200
        ]
        margins = [self._to_float(run.get("margin")) for run in target_runs]
        margins = [value for value in margins if value is not None and value >= 0]
        if not margins:
            return

        close_count = sum(1 for value in margins if value <= 1.0)
        score = 0
        if close_count >= 3:
            score += 5
        elif close_count >= 2:
            score += 4
        elif close_count == 1:
            score += 2

        self._add_modifier(
            modifiers,
            reasons,
            "distance_margin_quality",
            score,
            f"同距離・近似距離で1.0秒以内の競馬{close_count}回を評価",
        )
        explain_parts.append(f"距離と着差は1.0秒以内{close_count}回")

    def _score_distance_last_3f(self, target_distance, runs, modifiers, reasons, explain_parts):
        target_runs = [
            run
            for run in runs
            if self._distance_diff(target_distance, run) is not None
            and self._distance_diff(target_distance, run) <= 200
        ]
        last_3f_values = [self._to_float(run.get("last_3f")) for run in target_runs]
        last_3f_values = [value for value in last_3f_values if value is not None and value > 0]
        if not last_3f_values:
            return

        average = sum(last_3f_values) / len(last_3f_values)
        spread = max(last_3f_values) - min(last_3f_values) if len(last_3f_values) >= 2 else 0

        score = 0
        if average <= 38.5:
            score += 2
        if spread <= 1.5:
            score += 2

        self._add_modifier(
            modifiers,
            reasons,
            "distance_last_3f",
            score,
            f"近い距離で上がり平均{average:.1f}秒、ブレ幅{spread:.1f}秒を評価",
        )
        explain_parts.append(f"近い距離での上がりは平均{average:.1f}秒")

    def _score_distance_style(self, target_distance, runs, modifiers, reasons, explain_parts):
        style = self._dominant_style(runs)
        score = 0

        if target_distance >= 1600 and style in {"front", "stalk"}:
            score += 4
        elif target_distance >= 1600 and style == "deep_closer":
            score -= 3

        sprint_only = all((self._to_int(run.get("distance")) or 0) <= 1400 for run in runs)
        if target_distance >= 1700 and sprint_only and style in {"closer", "deep_closer"}:
            score -= 6

        self._add_modifier(
            modifiers,
            reasons,
            "distance_style_fit",
            score,
            f"今回距離{target_distance}mと脚質{self._style_label(style)}の噛み合わせを評価",
        )
        explain_parts.append(f"距離と脚質は{self._style_label(style)}型として評価")

    def _dominant_style(self, runs):
        styles = [self._classify_style(run) for run in runs]
        styles = [style for style in styles if style != "unknown"]
        if not styles:
            return "unknown"

        counts = {}
        for style in styles:
            counts[style] = counts.get(style, 0) + 1

        priority = ["escape", "front", "stalk", "closer", "deep_closer"]
        return max(priority, key=lambda style: (counts.get(style, 0), -priority.index(style)))

    def _classify_style(self, run):
        corner_4 = self._to_int(run.get("corner_4"))
        corner_1 = self._to_int(run.get("corner_1"))
        if corner_4 is None or corner_4 <= 0:
            return "unknown"
        if corner_4 <= 1 or (corner_1 in {1, 2} and corner_4 <= 2):
            return "escape"
        if corner_4 <= 4:
            return "front"
        if corner_4 <= 6:
            return "stalk"
        if corner_4 <= 10:
            return "closer"
        return "deep_closer"

    def _collect_missing_warnings(self, runs, warnings):
        fields = {
            "finish_position": "finish position missing",
            "margin": "margin missing",
            "last_3f": "last 3f missing",
            "corner_4": "corner position missing",
        }
        for field_name, message in fields.items():
            if all(not run.get(field_name) for run in runs):
                warnings.append(message)

    def _distance_fit(self, score):
        if score >= 25:
            return "strong_fit"
        if score >= 12:
            return "fit"
        if score > 0:
            return "some_fit"
        if score < 0:
            return "concern"
        return "unknown"

    def _distance_fit_label(self, score):
        labels = {
            "strong_fit": "高い",
            "fit": "合う",
            "some_fit": "やや合う",
            "concern": "不安",
            "unknown": "判定不能",
        }
        return labels[self._distance_fit(score)]

    def _style_label(self, style):
        return {
            "escape": "逃げ",
            "front": "先行",
            "stalk": "好位",
            "closer": "差し",
            "deep_closer": "追込",
            "unknown": "判定不能",
        }.get(style, "判定不能")

    def _distance_diff(self, target_distance, run):
        run_distance = self._to_int(run.get("distance"))
        if run_distance is None:
            return None
        return abs(run_distance - target_distance)

    def _is_good_run(self, run):
        finish = self._to_int(run.get("finish_position"))
        margin = self._to_float(run.get("margin"))
        return (finish is not None and finish <= 5) or (margin is not None and margin <= 1.0)

    def _is_bad_run(self, run):
        finish = self._to_int(run.get("finish_position"))
        margin = self._to_float(run.get("margin"))
        return (finish is not None and finish >= 10) or (margin is not None and margin >= 3.0)

    def _add_modifier(self, modifiers, reasons, key, score, reason):
        if score == 0:
            return
        modifiers[key] = modifiers.get(key, 0) + score
        reasons[key] = reason

    def _normalize_runs(self, recent_runs):
        if not isinstance(recent_runs, list):
            return []
        return [run for run in recent_runs if isinstance(run, dict)]

    def _to_int(self, value):
        if value is None:
            return None
        try:
            text = str(value).strip().lower().replace("m", "")
            if not text or text in {"取消", "除外", "中止"}:
                return None
            return int(float(text))
        except (TypeError, ValueError):
            return None

    def _to_float(self, value):
        if value is None:
            return None
        try:
            text = str(value).strip()
            if not text or text in {"取消", "除外", "中止"}:
                return None
            return float(text)
        except (TypeError, ValueError):
            return None


if __name__ == "__main__":
    evaluator = DistanceSuitabilityEvaluator()
    sample_runs = [
        {
            "distance": "1800",
            "finish_position": "2",
            "margin": "0.1",
            "last_3f": "38.3",
            "corner_1": "4",
            "corner_4": "3",
        },
        {
            "distance": "1700",
            "finish_position": "4",
            "margin": "0.8",
            "last_3f": "38.7",
            "corner_1": "3",
            "corner_4": "3",
        },
    ]
    print(evaluator.evaluate(sample_runs, distance=1700, surface="dirt", horse_name="sample"))
    print(evaluator.evaluate([], distance=1700, horse_name="unknown"))
