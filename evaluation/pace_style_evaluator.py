"""Trial evaluator for running style from corner positions.

This module reads recent corner positions from TARGET history runs and judges
each horse's pace/running style tendency.  It is only connected to the trial
Evaluation Engine and does not touch the production Analyzer or main.py.
"""

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from evaluation.score_modifier_engine import ScoreModifierEngine


class PaceStyleEvaluator:
    """Judge running style from corner_1 to corner_4 in recent runs."""

    SOURCE_TYPE = "pace_style"
    HISTORY_LIMIT = 5

    STYLE_LABELS = {
        "escape": "逃げ",
        "front": "先行",
        "stalk": "好位",
        "closer": "差し",
        "deep_closer": "追込",
        "unknown": "判定不能",
    }

    def evaluate(self, recent_runs=None, horse_name=None, racecourse=None, surface=None, distance=None):
        """Return a ScoreModifierEngine-compatible pace style evaluation."""

        runs = self._normalize_runs(recent_runs)[: self.HISTORY_LIMIT]
        source_name = f"pace_style_{horse_name or 'unknown'}"
        valid_corner_runs = self._extract_valid_corner_runs(runs)

        if not valid_corner_runs:
            warning = f"pace style unknown: {horse_name or 'unknown'}"
            return self._empty_result(source_name, horse_name, warning)

        styles = [self._classify_run(run) for run in valid_corner_runs]
        dominant_style = self._dominant_style(styles)

        modifiers = {}
        reasons = {}
        explain_parts = []

        self._score_style_stability(styles, modifiers, reasons, explain_parts)
        self._score_kokura_dirt_1700_fit(
            dominant_style,
            racecourse,
            surface,
            distance,
            modifiers,
            reasons,
            explain_parts,
        )
        self._score_positioning(valid_corner_runs, modifiers, reasons, explain_parts)
        self._score_move_up(valid_corner_runs, modifiers, reasons, explain_parts)
        self._score_escape_risk(styles, modifiers, reasons, explain_parts)

        engine = ScoreModifierEngine()
        engine.add_modifiers(
            source_name=source_name,
            score_modifiers=modifiers,
            modifier_reasons=reasons,
            explain=" / ".join(explain_parts),
            source_type=self.SOURCE_TYPE,
        )
        summary = engine.get_summary()

        return {
            "horse_name": horse_name,
            "racecourse": racecourse,
            "surface": surface,
            "distance": distance,
            "matched": True,
            "matched_sources": [source_name],
            "summary": summary,
            "pace_style_score": summary.get("total_score", 0),
            "pace_style": dominant_style,
            "pace_style_label": self.STYLE_LABELS.get(dominant_style, "判定不能"),
            "style_counts": self._count_styles(styles),
            "history_count": len(runs),
            "corner_history_count": len(valid_corner_runs),
            "warnings": [],
        }

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
            "pace_style_score": 0,
            "pace_style": "unknown",
            "pace_style_label": self.STYLE_LABELS["unknown"],
            "style_counts": {},
            "history_count": 0,
            "corner_history_count": 0,
            "warnings": [warning] if warning else [],
        }
        if warning:
            result["warning"] = warning
        return result

    def _normalize_runs(self, recent_runs):
        if not isinstance(recent_runs, list):
            return []
        return [run for run in recent_runs if isinstance(run, dict)]

    def _extract_valid_corner_runs(self, runs):
        valid_runs = []
        for run in runs:
            corners = self._corners(run)
            if not corners:
                continue
            if all(value == 0 for value in corners.values()):
                continue
            if corners.get("corner_4", 0) <= 0:
                continue
            valid_runs.append(corners)
        return valid_runs

    def _corners(self, run):
        corners = {
            "corner_1": self._to_int(run.get("corner_1")),
            "corner_2": self._to_int(run.get("corner_2")),
            "corner_3": self._to_int(run.get("corner_3")),
            "corner_4": self._to_int(run.get("corner_4")),
        }
        if all(value is None for value in corners.values()):
            return None
        return {key: value if value is not None else 0 for key, value in corners.items()}

    def _classify_run(self, corners):
        corner_4 = corners.get("corner_4", 0)
        corner_1 = corners.get("corner_1", 0)

        if corner_4 <= 0:
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

    def _dominant_style(self, styles):
        counts = self._count_styles(styles)
        if not counts:
            return "unknown"
        priority = ["escape", "front", "stalk", "closer", "deep_closer", "unknown"]
        return max(priority, key=lambda style: (counts.get(style, 0), -priority.index(style)))

    def _count_styles(self, styles):
        counts = {}
        for style in styles:
            counts[style] = counts.get(style, 0) + 1
        return counts

    def _score_style_stability(self, styles, modifiers, reasons, explain_parts):
        counts = self._count_styles(styles)
        dominant_style = self._dominant_style(styles)
        dominant_count = counts.get(dominant_style, 0)
        total = len(styles)

        score = 0
        if dominant_count == total and total >= 2:
            score += 8
        elif dominant_count / total >= 0.6:
            score += 5
        elif dominant_count >= 2:
            score += 3

        self._add_modifier(
            modifiers,
            reasons,
            "style_stability",
            score,
            f"{self.STYLE_LABELS.get(dominant_style)}型が{dominant_count}/{total}走で、脚質の再現性を評価",
        )
        explain_parts.append(
            f"脚質傾向は{self.STYLE_LABELS.get(dominant_style)}型中心({dominant_count}/{total}走)"
        )

    def _score_kokura_dirt_1700_fit(
        self,
        dominant_style,
        racecourse,
        surface,
        distance,
        modifiers,
        reasons,
        explain_parts,
    ):
        if not self._is_kokura_dirt_1700(racecourse, surface, distance):
            return

        score_by_style = {
            "escape": 4,
            "front": 8,
            "stalk": 7,
            "closer": 1,
            "deep_closer": -4,
            "unknown": 0,
        }
        score = score_by_style.get(dominant_style, 0)

        self._add_modifier(
            modifiers,
            reasons,
            "kokura_dirt_1700_style_fit",
            score,
            "小倉ダ1700m想定では先行・好位型を評価し、極端な追込は軽く割引",
        )
        explain_parts.append(
            f"小倉ダ1700m適性は{self.STYLE_LABELS.get(dominant_style)}型として評価"
        )

    def _is_kokura_dirt_1700(self, racecourse, surface, distance):
        racecourse_text = str(racecourse or "").strip().lower()
        surface_text = str(surface or "").strip().lower()
        distance_value = self._to_int(distance)
        return (
            racecourse_text in {"kokura", "小倉"}
            and surface_text in {"dirt", "ダート", "ダ"}
            and distance_value == 1700
        )

    def _score_positioning(self, corner_runs, modifiers, reasons, explain_parts):
        corner_4_values = [run.get("corner_4", 0) for run in corner_runs if run.get("corner_4", 0) > 0]
        if not corner_4_values:
            return

        front_count = sum(1 for value in corner_4_values if value <= 4)
        stalk_count = sum(1 for value in corner_4_values if value <= 6)
        deep_count = sum(1 for value in corner_4_values if value >= 11)
        average = sum(corner_4_values) / len(corner_4_values)

        score = 0
        if front_count >= 3:
            score += 9
        elif front_count >= 2:
            score += 6
        elif stalk_count >= 3:
            score += 4

        if average <= 4:
            score += 5
        elif average <= 7:
            score += 2
        elif average >= 10:
            score -= 3

        if deep_count >= 2:
            score -= 3

        self._add_modifier(
            modifiers,
            reasons,
            "front_positioning",
            score,
            f"4角平均{average:.1f}番手、4角4番手以内{front_count}回を評価",
        )
        explain_parts.append(f"位置取りは4角平均{average:.1f}番手、前目{front_count}回")

    def _score_move_up(self, corner_runs, modifiers, reasons, explain_parts):
        move_up_count = 0
        valid_count = 0
        total_gain = 0
        for run in corner_runs:
            corner_1 = run.get("corner_1", 0)
            corner_4 = run.get("corner_4", 0)
            if corner_1 <= 0 or corner_4 <= 0:
                continue
            valid_count += 1
            gain = corner_1 - corner_4
            total_gain += gain
            if gain >= 2:
                move_up_count += 1

        if valid_count == 0:
            return

        score = 0
        if move_up_count >= 3:
            score += 7
        elif move_up_count >= 2:
            score += 5
        elif move_up_count == 1:
            score += 2

        average_gain = total_gain / valid_count
        if average_gain >= 2:
            score += 3
        elif average_gain <= -3:
            score -= 2

        self._add_modifier(
            modifiers,
            reasons,
            "move_up_ability",
            score,
            f"1角から4角で押し上げたレース{move_up_count}回、平均押し上げ{average_gain:.1f}を評価",
        )
        explain_parts.append(f"押し上げ傾向は{move_up_count}回、平均{average_gain:.1f}")

    def _score_escape_risk(self, styles, modifiers, reasons, explain_parts):
        if not styles:
            return

        escape_count = sum(1 for style in styles if style == "escape")
        non_escape_count = len(styles) - escape_count
        score = 0
        if escape_count >= 3 and non_escape_count == 0:
            score -= 4
        elif escape_count >= 3 and non_escape_count <= 1:
            score -= 2

        self._add_modifier(
            modifiers,
            reasons,
            "escape_only_risk",
            score,
            "逃げ一辺倒の可能性がある場合は軽く割引",
        )
        if score < 0:
            explain_parts.append("逃げ以外の形が少ない点は軽く割引")

    def _add_modifier(self, modifiers, reasons, key, score, reason):
        if score == 0:
            return
        modifiers[key] = modifiers.get(key, 0) + score
        reasons[key] = reason

    def _to_int(self, value):
        if value is None:
            return None
        try:
            text = str(value).strip()
            if not text or text in {"取消", "除外", "中止"}:
                return None
            return int(float(text))
        except (TypeError, ValueError):
            return None


if __name__ == "__main__":
    evaluator = PaceStyleEvaluator()
    sample_runs = [
        {"corner_1": "3", "corner_2": "3", "corner_3": "2", "corner_4": "2"},
        {"corner_1": "6", "corner_2": "5", "corner_3": "4", "corner_4": "3"},
        {"corner_1": "8", "corner_2": "8", "corner_3": "6", "corner_4": "5"},
    ]
    print(evaluator.evaluate(sample_runs, horse_name="sample", racecourse="kokura", surface="dirt", distance=1700))
    print(evaluator.evaluate([], horse_name="unknown"))
