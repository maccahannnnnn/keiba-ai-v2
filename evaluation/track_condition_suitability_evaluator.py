"""Trial evaluator for track-condition suitability from recent runs.

This evaluator uses TARGET history runs to judge whether today's track
condition fits a horse.  It is for the trial Evaluation Engine only and is not
connected to the production Analyzer or main.py.
"""

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from evaluation.score_modifier_engine import ScoreModifierEngine


class TrackConditionSuitabilityEvaluator:
    """Evaluate suitability for today's track condition without odds/popularity."""

    SOURCE_TYPE = "track_condition_suitability"
    HISTORY_LIMIT = 5
    WET_CONDITIONS = {"yielding", "soft", "heavy"}

    def evaluate(self, recent_runs=None, surface=None, track_condition=None, horse_name=None):
        """Return a ScoreModifierEngine-compatible track-condition evaluation."""

        runs = self._normalize_runs(recent_runs)[: self.HISTORY_LIMIT]
        target_condition = self._normalize_condition(track_condition)
        target_surface = self._normalize_surface(surface)
        source_name = f"track_condition_suitability_{horse_name or 'unknown'}"

        if not runs or target_condition is None:
            warning = f"track condition unknown: {horse_name or 'unknown'}"
            return self._empty_result(source_name, horse_name, warning)

        condition_runs = [
            run
            for run in runs
            if self._normalize_condition(run.get("track_condition")) is not None
        ]
        if not condition_runs:
            warning = f"track condition unknown: {horse_name or 'unknown'}"
            return self._empty_result(source_name, horse_name, warning)

        modifiers = {}
        reasons = {}
        explain_parts = []
        warnings = []

        self._score_same_condition(target_condition, condition_runs, modifiers, reasons, explain_parts)
        self._score_wet_condition(target_condition, condition_runs, modifiers, reasons, explain_parts)
        self._score_firm_only_risk(target_condition, condition_runs, modifiers, reasons, explain_parts)
        self._score_condition_style(target_condition, target_surface, condition_runs, modifiers, reasons, explain_parts)
        self._score_condition_last_3f(target_condition, condition_runs, modifiers, reasons, explain_parts)
        self._score_condition_pci_rpci(target_condition, condition_runs, modifiers, reasons, explain_parts)
        self._collect_missing_warnings(condition_runs, warnings)

        engine = ScoreModifierEngine()
        engine.add_modifiers(
            source_name=source_name,
            score_modifiers=modifiers,
            modifier_reasons=reasons,
            explain=" / ".join(explain_parts),
            source_type=self.SOURCE_TYPE,
        )
        summary = engine.get_summary()
        condition_score = summary.get("total_score", 0)

        result = {
            "horse_name": horse_name,
            "surface": target_surface,
            "track_condition": target_condition,
            "matched": True,
            "matched_sources": [source_name],
            "summary": summary,
            "track_condition_score": condition_score,
            "track_condition_fit": self._condition_fit(condition_score),
            "track_condition_fit_label": self._condition_fit_label(condition_score),
            "history_count": len(runs),
            "condition_history_count": len(condition_runs),
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
            "track_condition_score": 0,
            "track_condition_fit": "unknown",
            "track_condition_fit_label": "判定不能",
            "history_count": 0,
            "condition_history_count": 0,
            "warnings": [warning] if warning else [],
        }
        if warning:
            result["warning"] = warning
        return result

    def _score_same_condition(self, target_condition, runs, modifiers, reasons, explain_parts):
        same_runs = [
            run for run in runs if self._normalize_condition(run.get("track_condition")) == target_condition
        ]
        good_runs = [run for run in same_runs if self._is_good_run(run)]
        if not same_runs:
            return

        score = 3
        if good_runs:
            score += min(7, len(good_runs) * 4)

        self._add_modifier(
            modifiers,
            reasons,
            "same_condition_record",
            score,
            f"今回と同じ馬場で{len(same_runs)}走、好内容{len(good_runs)}走を評価",
        )
        explain_parts.append(f"同馬場は{len(same_runs)}走、好内容{len(good_runs)}走")

    def _score_wet_condition(self, target_condition, runs, modifiers, reasons, explain_parts):
        if target_condition not in self.WET_CONDITIONS:
            return

        wet_runs = [
            run for run in runs if self._normalize_condition(run.get("track_condition")) in self.WET_CONDITIONS
        ]
        good_wet_runs = [run for run in wet_runs if self._is_good_run(run)]
        close_wet_runs = [
            run for run in wet_runs if (self._to_float(run.get("margin")) is not None and self._to_float(run.get("margin")) <= 1.0)
        ]
        bad_wet_runs = [run for run in wet_runs if self._is_bad_run(run)]
        if not wet_runs:
            return

        score = 0
        if good_wet_runs:
            score += min(8, len(good_wet_runs) * 4)
        if close_wet_runs:
            score += min(6, len(close_wet_runs) * 3)
        if len(bad_wet_runs) >= 2:
            score -= 6
        elif len(bad_wet_runs) == 1:
            score -= 3

        self._add_modifier(
            modifiers,
            reasons,
            "wet_condition_record",
            score,
            f"道悪{len(wet_runs)}走、好内容{len(good_wet_runs)}走、着差小{len(close_wet_runs)}走を評価",
        )
        explain_parts.append(
            f"道悪実績は{len(wet_runs)}走、好内容{len(good_wet_runs)}走、着差小{len(close_wet_runs)}走"
        )

    def _score_firm_only_risk(self, target_condition, runs, modifiers, reasons, explain_parts):
        if target_condition not in self.WET_CONDITIONS:
            return

        good_condition_runs = [
            run for run in runs if self._normalize_condition(run.get("track_condition")) == "good"
        ]
        wet_runs = [
            run for run in runs if self._normalize_condition(run.get("track_condition")) in self.WET_CONDITIONS
        ]
        good_condition_success = sum(1 for run in good_condition_runs if self._is_good_run(run))
        wet_bad = sum(1 for run in wet_runs if self._is_bad_run(run))

        score = 0
        if good_condition_success >= 2 and wet_bad >= 1:
            score -= 5
        elif good_condition_success >= 1 and wet_bad >= 2:
            score -= 6

        self._add_modifier(
            modifiers,
            reasons,
            "firm_only_risk",
            score,
            "良馬場での好走が中心で、道悪凡走がある場合は軽く割引",
        )
        if score < 0:
            explain_parts.append("良馬場寄りで道悪凡走がある点は割引")

    def _score_condition_style(self, target_condition, target_surface, runs, modifiers, reasons, explain_parts):
        if target_condition not in self.WET_CONDITIONS:
            return

        wet_runs = [
            run for run in runs if self._normalize_condition(run.get("track_condition")) in self.WET_CONDITIONS
        ]
        target_like_runs = wet_runs if target_condition in self.WET_CONDITIONS else runs
        if not target_like_runs:
            return

        front_count = 0
        deep_count = 0
        valid_count = 0
        for run in target_like_runs:
            corner_4 = self._to_int(run.get("corner_4"))
            if corner_4 is None or corner_4 <= 0:
                continue
            valid_count += 1
            if corner_4 <= 4:
                front_count += 1
            if corner_4 >= 11:
                deep_count += 1

        if valid_count == 0:
            return

        score = 0
        if target_surface == "dirt" and target_condition in self.WET_CONDITIONS:
            if front_count >= 2:
                score += 5
            elif front_count == 1:
                score += 3
            if deep_count >= 2:
                score -= 4
            elif deep_count == 1:
                score -= 2

        self._add_modifier(
            modifiers,
            reasons,
            "condition_style_fit",
            score,
            f"道悪・稍重系で4角前目{front_count}回、後方{deep_count}回を評価",
        )
        explain_parts.append(f"馬場と脚質は前目{front_count}回、後方{deep_count}回")

    def _score_condition_last_3f(self, target_condition, runs, modifiers, reasons, explain_parts):
        if target_condition not in self.WET_CONDITIONS:
            return

        wet_runs = [
            run for run in runs if self._normalize_condition(run.get("track_condition")) in self.WET_CONDITIONS
        ]
        values = [self._to_float(run.get("last_3f")) for run in wet_runs]
        values = [value for value in values if value is not None and value > 0]
        if not values:
            return

        average = sum(values) / len(values)
        spread = max(values) - min(values) if len(values) >= 2 else 0
        score = 0
        if average <= 38.5:
            score += 2
        if spread <= 1.5:
            score += 2
        elif spread <= 2.5:
            score += 1

        self._add_modifier(
            modifiers,
            reasons,
            "condition_last_3f",
            score,
            f"道悪で上がり平均{average:.1f}秒、ブレ幅{spread:.1f}秒を評価",
        )
        explain_parts.append(f"道悪上がりは平均{average:.1f}秒")

    def _score_condition_pci_rpci(self, target_condition, runs, modifiers, reasons, explain_parts):
        if target_condition not in self.WET_CONDITIONS:
            return

        wet_runs = [
            run for run in runs if self._normalize_condition(run.get("track_condition")) in self.WET_CONDITIONS
        ]
        stable_count = 0
        valid_count = 0
        for run in wet_runs:
            pci = self._to_float(run.get("pci"))
            rpci = self._to_float(run.get("rpci"))
            if pci is None or rpci is None:
                continue
            valid_count += 1
            if abs(pci - rpci) <= 5:
                stable_count += 1

        if valid_count == 0:
            return

        score = 0
        if stable_count >= 2:
            score += 3
        elif stable_count == 1:
            score += 2

        self._add_modifier(
            modifiers,
            reasons,
            "condition_pci_rpci",
            score,
            f"道悪でPCI/RPCI差が小さいレース{stable_count}/{valid_count}走を評価",
        )
        explain_parts.append(f"道悪PCI/RPCI安定は{stable_count}/{valid_count}走")

    def _collect_missing_warnings(self, runs, warnings):
        fields = {
            "track_condition": "track condition missing",
            "finish_position": "finish position missing",
            "margin": "margin missing",
            "last_3f": "last 3f missing",
            "pci": "PCI missing",
            "rpci": "RPCI missing",
            "corner_4": "corner position missing",
        }
        for field_name, message in fields.items():
            if all(not run.get(field_name) for run in runs):
                warnings.append(message)

    def _condition_fit(self, score):
        if score >= 22:
            return "strong_fit"
        if score >= 10:
            return "fit"
        if score > 0:
            return "some_fit"
        if score < 0:
            return "concern"
        return "unknown"

    def _condition_fit_label(self, score):
        labels = {
            "strong_fit": "高い",
            "fit": "合う",
            "some_fit": "やや合う",
            "concern": "不安",
            "unknown": "判定不能",
        }
        return labels[self._condition_fit(score)]

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
    evaluator = TrackConditionSuitabilityEvaluator()
    sample_runs = [
        {
            "track_condition": "稍",
            "finish_position": "2",
            "margin": "0.1",
            "last_3f": "38.3",
            "pci": "48.7",
            "rpci": "49.6",
            "corner_4": "3",
        },
        {
            "track_condition": "重",
            "finish_position": "4",
            "margin": "0.8",
            "last_3f": "38.7",
            "pci": "50.5",
            "rpci": "50.4",
            "corner_4": "5",
        },
    ]
    print(evaluator.evaluate(sample_runs, surface="dirt", track_condition="稍重", horse_name="sample"))
    print(evaluator.evaluate([], surface="dirt", track_condition="稍重", horse_name="unknown"))
