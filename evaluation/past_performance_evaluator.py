"""Trial evaluator for recent past performances.

This evaluator reads recent HistoryRun data produced by TargetHistoryImporter
and converts it into score_modifiers for the trial Evaluation Engine.  It is
not connected to the production Analyzer or main.py.
"""

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from evaluation.score_modifier_engine import ScoreModifierEngine


class PastPerformanceEvaluator:
    """Evaluate the latest four to five runs without using odds or popularity."""

    SOURCE_TYPE = "past_performance"
    HISTORY_LIMIT = 5

    def evaluate(
        self,
        recent_runs=None,
        racecourse=None,
        surface=None,
        distance=None,
        track_condition=None,
        horse_name=None,
    ):
        """Return a trial evaluation result for recent past performances."""

        runs = self._normalize_runs(recent_runs)[: self.HISTORY_LIMIT]
        source_name = f"past_performance_{horse_name or 'unknown'}"

        if not runs:
            warning = f"history not found: {horse_name or 'unknown'}"
            return self._empty_result(
                source_name=source_name,
                horse_name=horse_name,
                warning=warning,
            )

        modifiers = {}
        reasons = {}
        explain_parts = []
        warnings = []

        self._score_finish_positions(runs, modifiers, reasons, explain_parts)
        self._score_margins(runs, modifiers, reasons, explain_parts)
        self._score_corners(runs, modifiers, reasons, explain_parts)
        self._score_distance_surface(
            runs,
            surface,
            distance,
            modifiers,
            reasons,
            explain_parts,
        )
        self._score_track_condition(
            runs,
            track_condition,
            modifiers,
            reasons,
            explain_parts,
        )
        self._score_last_3f(runs, modifiers, reasons, explain_parts)
        self._score_pci_rpci(runs, modifiers, reasons, explain_parts)
        self._score_recent_trend(runs, modifiers, reasons, explain_parts)

        self._collect_missing_warnings(runs, warnings)

        engine = ScoreModifierEngine()
        engine.add_modifiers(
            source_name=source_name,
            score_modifiers=modifiers,
            modifier_reasons=reasons,
            explain=" / ".join(explain_parts),
            source_type=self.SOURCE_TYPE,
        )
        summary = engine.get_summary()

        result = {
            "horse_name": horse_name,
            "racecourse": racecourse,
            "surface": surface,
            "distance": distance,
            "track_condition": track_condition,
            "matched": True,
            "matched_sources": [source_name],
            "summary": summary,
            "past_performance_score": summary.get("total_score", 0),
            "history_count": len(runs),
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
            "past_performance_score": 0,
            "history_count": 0,
            "warnings": [warning] if warning else [],
        }
        if warning:
            result["warning"] = warning
        return result

    def _normalize_runs(self, recent_runs):
        if not isinstance(recent_runs, list):
            return []
        return [run for run in recent_runs if isinstance(run, dict)]

    def _score_finish_positions(self, runs, modifiers, reasons, explain_parts):
        positions = [self._to_int(run.get("finish_position")) for run in runs]
        positions = [position for position in positions if position is not None and position > 0]
        if not positions:
            return

        top5_count = sum(1 for position in positions if position <= 5)
        bad_count = sum(1 for position in positions if position >= 10)
        average = sum(positions) / len(positions)

        score = 0
        if top5_count >= 4:
            score += 10
        elif top5_count >= 3:
            score += 7
        elif top5_count >= 2:
            score += 4

        if average <= 4:
            score += 5
        elif average <= 7:
            score += 2

        if bad_count >= 2:
            score -= 4
        elif bad_count == 1:
            score -= 2

        self._add_modifier(
            modifiers,
            reasons,
            "finish_stability",
            score,
            f"近走{len(positions)}走の平均着順{average:.1f}着、掲示板内{top5_count}回を評価",
        )
        explain_parts.append(f"着順安定度は平均{average:.1f}着、掲示板内{top5_count}回")

    def _score_margins(self, runs, modifiers, reasons, explain_parts):
        margins = [self._to_float(run.get("margin")) for run in runs]
        margins = [margin for margin in margins if margin is not None and margin >= 0]
        if not margins:
            return

        close_count = sum(1 for margin in margins if margin <= 1.0)
        large_loss_count = sum(1 for margin in margins if margin >= 3.0)
        average = sum(margins) / len(margins)

        score = 0
        if close_count >= 4:
            score += 8
        elif close_count >= 3:
            score += 6
        elif close_count >= 2:
            score += 3

        if average <= 0.8:
            score += 5
        elif average <= 1.5:
            score += 3
        elif average >= 3.0:
            score -= 4

        if large_loss_count:
            score -= min(large_loss_count * 2, 5)

        self._add_modifier(
            modifiers,
            reasons,
            "margin_quality",
            score,
            f"近走の平均着差{average:.1f}秒、1.0秒以内{close_count}回を評価",
        )
        explain_parts.append(f"着差は平均{average:.1f}秒で大敗の少なさを確認")

    def _score_corners(self, runs, modifiers, reasons, explain_parts):
        corner_4_values = [self._to_int(run.get("corner_4")) for run in runs]
        corner_4_values = [value for value in corner_4_values if value is not None and value > 0]
        if not corner_4_values:
            return

        front_count = sum(1 for value in corner_4_values if value <= 4)
        middle_count = sum(1 for value in corner_4_values if 5 <= value <= 8)
        average = sum(corner_4_values) / len(corner_4_values)

        score = 0
        if front_count >= 3:
            score += 8
        elif front_count >= 2:
            score += 5
        elif middle_count >= 3:
            score += 3
        if average >= 10:
            score -= 3

        self._add_modifier(
            modifiers,
            reasons,
            "corner_positioning",
            score,
            f"4角平均{average:.1f}番手。先行して粘れる内容を評価",
        )
        explain_parts.append(f"通過順は4角平均{average:.1f}番手")

    def _score_distance_surface(self, runs, surface, distance, modifiers, reasons, explain_parts):
        target_distance = self._to_int(distance)
        target_surface = self._normalize_surface(surface)
        if target_distance is None and target_surface is None:
            return

        close_distance_count = 0
        surface_count = 0
        same_condition_good_runs = 0

        for run in runs:
            run_distance = self._to_int(run.get("distance"))
            run_surface = self._normalize_surface(run.get("surface"))
            finish = self._to_int(run.get("finish_position"))

            if target_distance is not None and run_distance is not None:
                if abs(run_distance - target_distance) <= 200:
                    close_distance_count += 1

            if target_surface is not None and run_surface == target_surface:
                surface_count += 1
                if finish is not None and finish <= 5:
                    same_condition_good_runs += 1

        score = 0
        if close_distance_count >= 3:
            score += 7
        elif close_distance_count >= 2:
            score += 5
        elif close_distance_count == 1:
            score += 2

        if surface_count >= 4:
            score += 7
        elif surface_count >= 2:
            score += 5
        elif surface_count == 1:
            score += 2

        if same_condition_good_runs >= 2:
            score += 4
        elif same_condition_good_runs == 1:
            score += 2

        self._add_modifier(
            modifiers,
            reasons,
            "distance_surface_fit",
            score,
            f"今回距離に近い経験{close_distance_count}走、同馬場種別経験{surface_count}走を評価",
        )
        explain_parts.append(
            f"距離・馬場は近い距離{close_distance_count}走、同馬場{surface_count}走"
        )

    def _score_track_condition(self, runs, track_condition, modifiers, reasons, explain_parts):
        target_condition = self._normalize_condition(track_condition)
        wet_conditions = {"yielding", "soft", "heavy"}

        wet_good_count = 0
        target_good_count = 0
        for run in runs:
            condition = self._normalize_condition(run.get("track_condition"))
            finish = self._to_int(run.get("finish_position"))
            if finish is None:
                continue

            if condition in wet_conditions and finish <= 5:
                wet_good_count += 1
            if target_condition is not None and condition == target_condition and finish <= 5:
                target_good_count += 1

        score = 0
        if wet_good_count >= 2:
            score += 5
        elif wet_good_count == 1:
            score += 3

        if target_good_count >= 2:
            score += 5
        elif target_good_count == 1:
            score += 3

        self._add_modifier(
            modifiers,
            reasons,
            "track_condition_fit",
            score,
            f"道悪で崩れていない実績{wet_good_count}回、今回馬場に近い好走{target_good_count}回を評価",
        )
        explain_parts.append(f"馬場適性は道悪好走{wet_good_count}回を確認")

    def _score_last_3f(self, runs, modifiers, reasons, explain_parts):
        values = [self._to_float(run.get("last_3f")) for run in runs]
        values = [value for value in values if value is not None and value > 0]
        if not values:
            return

        average = sum(values) / len(values)
        spread = max(values) - min(values) if len(values) >= 2 else 0

        score = 0
        if average <= 37.5:
            score += 6
        elif average <= 38.5:
            score += 4
        elif average <= 39.5:
            score += 2

        if spread <= 1.0:
            score += 4
        elif spread <= 2.0:
            score += 2

        self._add_modifier(
            modifiers,
            reasons,
            "last_3f_stability",
            score,
            f"上がり3F平均{average:.1f}秒、ブレ幅{spread:.1f}秒を評価",
        )
        explain_parts.append(f"上がり3Fは平均{average:.1f}秒")

    def _score_pci_rpci(self, runs, modifiers, reasons, explain_parts):
        pci_values = [self._to_float(run.get("pci")) for run in runs]
        rpci_values = [self._to_float(run.get("rpci")) for run in runs]
        pci_values = [value for value in pci_values if value is not None]
        rpci_values = [value for value in rpci_values if value is not None]
        if not pci_values and not rpci_values:
            return

        stable_count = 0
        for index in range(min(len(pci_values), len(rpci_values))):
            if abs(pci_values[index] - rpci_values[index]) <= 5:
                stable_count += 1

        score = 0
        if stable_count >= 3:
            score += 6
        elif stable_count >= 2:
            score += 4
        elif stable_count == 1:
            score += 2

        self._add_modifier(
            modifiers,
            reasons,
            "pci_rpci_balance",
            score,
            f"PCI/RPCI差が小さいレース{stable_count}走を評価",
        )
        explain_parts.append(f"PCI/RPCIは展開依存の小さい走りを{stable_count}走確認")

    def _score_recent_trend(self, runs, modifiers, reasons, explain_parts):
        positions = [self._to_int(run.get("finish_position")) for run in runs]
        positions = [position for position in positions if position is not None and position > 0]
        if len(positions) < 3:
            return

        recent_average = sum(positions[:2]) / 2
        older_average = sum(positions[2:]) / len(positions[2:])

        score = 0
        if recent_average + 1 <= older_average:
            score += 6
            trend_text = "上昇傾向"
        elif recent_average > older_average + 2:
            score -= 4
            trend_text = "下降傾向"
        else:
            score += 2
            trend_text = "横ばい"

        self._add_modifier(
            modifiers,
            reasons,
            "recent_trend",
            score,
            f"近2走平均{recent_average:.1f}着、以前平均{older_average:.1f}着で{trend_text}",
        )
        explain_parts.append(f"近走トレンドは{trend_text}")

    def _collect_missing_warnings(self, runs, warnings):
        fields = {
            "finish_position": "finish position missing",
            "margin": "margin missing",
            "corner_4": "corner position missing",
            "last_3f": "last 3f missing",
            "pci": "PCI missing",
            "rpci": "RPCI missing",
        }
        for field_name, message in fields.items():
            if all(not run.get(field_name) for run in runs):
                warnings.append(message)

    def _add_modifier(self, modifiers, reasons, key, score, reason):
        if score == 0:
            return
        modifiers[key] = modifiers.get(key, 0) + score
        reasons[key] = reason

    def _normalize_surface(self, value):
        if value is None:
            return None
        text = str(value).strip().lower()
        if text in {"d", "ダ", "ダート", "dirt"}:
            return "dirt"
        if text in {"t", "芝", "turf"}:
            return "turf"
        return text or None

    def _normalize_condition(self, value):
        if value is None:
            return None
        text = str(value).strip().lower()
        aliases = {
            "良": "good",
            "good": "good",
            "稍": "yielding",
            "稍重": "yielding",
            "yielding": "yielding",
            "重": "soft",
            "soft": "soft",
            "不": "heavy",
            "不良": "heavy",
            "heavy": "heavy",
        }
        return aliases.get(text, text or None)

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
    evaluator = PastPerformanceEvaluator()
    sample_runs = [
        {
            "finish_position": "2",
            "margin": "0.1",
            "surface": "ダ",
            "distance": "1800",
            "track_condition": "良",
            "corner_4": "3",
            "last_3f": "38.3",
            "pci": "48.7",
            "rpci": "49.6",
        },
        {
            "finish_position": "3",
            "margin": "0.8",
            "surface": "ダ",
            "distance": "1800",
            "track_condition": "稍",
            "corner_4": "5",
            "last_3f": "38.3",
            "pci": "50.5",
            "rpci": "50.4",
        },
    ]
    print(
        evaluator.evaluate(
            recent_runs=sample_runs,
            surface="dirt",
            distance=1700,
            track_condition="yielding",
            horse_name="sample",
        )
    )
    print(evaluator.evaluate(recent_runs=None, horse_name="no_history"))
