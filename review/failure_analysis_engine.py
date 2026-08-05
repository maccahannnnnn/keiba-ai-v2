"""Failure analysis for the SP_COUNT_EQ_2 shadow BUY FP filter.

This module compares BUY horses removed by the shadow filter.  It reads saved
validation reports and existing analysis/result CSVs, then writes diagnostic
reports.  It never changes production BUY, scores, evaluators, thresholds,
Decision, RaceState, Knowledge, CSV schemas, or Improvement Candidates.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.race_file_locator import RaceFileLocator
from evaluation.target_trial_adapter import TargetTrialAdapter
from learning.shadow_validation_repository import ShadowValidationRepository


PROJECT_ID = "SHADOW_BUY_FALSE_POSITIVE_RC1_V1"
RULE_ID = "SP_COUNT_EQ_2"
OUT_DIR = ROOT / "reports" / "failure_analysis" / RULE_ID
GENERAL_DIR = ROOT / "reports" / "shadow_buy_fp_filter" / "unseen_validation"
FOCUSED_DIR = ROOT / "reports" / "shadow_buy_fp_filter" / "focused_unseen_validation"

NUMERIC_FEATURES = [
    "final_score",
    "adjusted_score",
    "decision_score",
    "ai_rank",
    "strong_positive_count",
    "strong_negative_count",
    "past_performance_score",
    "distance_score",
    "course_shape_score",
    "pace_style_score",
    "lap_score",
    "race_shape_score",
    "track_bias_score",
    "bloodline_score",
    "track_condition_score",
    "impact_score",
    "consistency_score",
    "recent_top3_count",
    "recent_top5_count",
    "recent_avg_finish",
    "recent_avg_margin",
    "recent_avg_last3f",
    "recent_last3f_top_count",
    "recent_same_surface_top3",
    "recent_same_distance_band_top3",
]

MATRIX_FIELDS = [
    "race_id",
    "race_date",
    "racecourse",
    "race_number",
    "horse_number",
    "horse_name",
    "finish_position",
    "is_top3",
    "analysis_group",
    "validation_group",
    "filter_rule_id",
    "surface",
    "distance",
    "distance_band",
    "track_condition",
    "manual_track_bias",
    "race_state",
    "race_decision",
    "confidence",
    "class_name",
    "field_size",
    "production_buy",
    "production_decision",
    "production_score",
    "final_score",
    "adjusted_score",
    "buy_rank",
    "decision_score",
    "buy_reason",
    "danger_reason",
    "explain_summary",
    "shadow_buy",
    "removed_by_shadow",
    "shadow_filter_reason",
    "strong_positive_count",
    "strong_negative_count",
    "filter_rule_matched",
    "past_performance_score",
    "distance_score",
    "course_shape_score",
    "pace_style_score",
    "lap_score",
    "race_shape_score",
    "track_bias_score",
    "bloodline_score",
    "track_condition_score",
    "impact_score",
    "consistency_score",
    "positive_reasons",
    "strong_positive_reasons",
    "negative_reasons",
    "danger_factors",
    "positive_reason_count",
    "negative_reason_count",
    "recent_run_count",
    "recent_top3_count",
    "recent_top5_count",
    "recent_avg_finish",
    "recent_avg_margin",
    "recent_avg_last3f",
    "recent_last3f_top_count",
    "recent_same_surface_top3",
    "recent_same_distance_band_top3",
    "recent_class_names",
    "missing_features",
    "feature_sources",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)


def to_int(value: Any, default: int | None = None) -> int | None:
    try:
        text = str(value).strip()
        if text == "":
            return default
        return int(float(text))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float | None = None) -> float | None:
    try:
        text = str(value).strip()
        if text == "":
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def race_part(race_id: str, index: int) -> str:
    parts = str(race_id or "").split("_")
    return parts[index] if len(parts) > index else ""


def norm_name(value: Any) -> str:
    return str(value or "").replace(" ", "").replace("　", "").strip().lower()


def dump_list(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, default=str)


class FailureAnalysisEngine:
    """Create fact-based failure analysis reports for a shadow rule."""

    def __init__(self, project_id: str = PROJECT_ID, validation_mode: str = "general-unseen"):
        self.project_id = project_id
        self.validation_mode = validation_mode
        self.locator = RaceFileLocator()
        self.adapter = TargetTrialAdapter()
        self.warnings: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

    def run(self, dry_run: bool = False) -> dict[str, Any]:
        started = datetime.now().isoformat(timespec="seconds")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        run_id = f"FAILURE_ANALYSIS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir = OUT_DIR / "runs" / run_id
        target_rows = self._target_rows()
        comparison_rows = self._comparison_rows()
        matrix = self._feature_matrix(target_rows, comparison_rows)
        group_comparison = self._group_comparison(matrix)
        reason_comparison = self._reason_comparison(matrix)
        possible = self._possible_separators(matrix, group_comparison, reason_comparison)
        causes = self._cause_candidates(matrix, possible)
        missing = self._missing_data_report(matrix)
        removed_success = [row for row in matrix if row.get("analysis_group") == "REMOVED_SUCCESSFUL_BUY"]
        removed_fp = [row for row in matrix if row.get("analysis_group") == "REMOVED_FALSE_POSITIVE"]
        kept_success = [row for row in matrix if row.get("analysis_group") == "KEPT_SUCCESSFUL_BUY"]
        status = self._analysis_status(matrix, removed_success, removed_fp)
        recommended = self._recommended_next_action(possible, missing, removed_success, removed_fp)
        fingerprint = self._fingerprint(matrix, possible, causes)
        analysis_run_id = self._fingerprint([fingerprint, started])[:16]
        summary = {
            "analysis_run_id": analysis_run_id,
            "analysis_fingerprint": fingerprint,
            "project_id": self.project_id,
            "rule_id": RULE_ID,
            "validation_mode": self.validation_mode,
            "generated_at": started,
            "target_removed_buy_count": len(target_rows),
            "removed_successful_buy_count": len(removed_success),
            "removed_fp_count": len(removed_fp),
            "kept_successful_buy_count": len(kept_success),
            "possible_separator_count": len(possible),
            "cause_candidate_count": len(causes),
            "missing_feature_count": len(missing),
            "analysis_status": status,
            "recommended_next_action": recommended,
            "warnings": self.warnings,
            "errors": self.errors,
            "production_buy_diff": 0,
            "score_diff": 0,
            "decision_diff": 0,
            "race_state_diff": 0,
            "candidate_registration_count": 0,
            "project_duplicate": 0,
            "input_reports": {
                "general_removed_buy": str(GENERAL_DIR / "unseen_removed_buy.csv"),
                "general_horse_results": str(GENERAL_DIR / "unseen_horse_results.csv"),
                "focused_removed_buy": str(FOCUSED_DIR / "focused_removed_buy.csv"),
                "focused_horse_results": str(FOCUSED_DIR / "focused_horse_results.csv"),
            },
            "feature_sources": self._feature_sources(),
        }
        if dry_run:
            summary["dry_run"] = True
            return summary

        run_dir.mkdir(parents=True, exist_ok=True)
        write_csv(OUT_DIR / "failure_feature_matrix.csv", matrix, MATRIX_FIELDS)
        write_csv(OUT_DIR / "group_comparison.csv", group_comparison)
        write_csv(OUT_DIR / "reason_comparison.csv", reason_comparison)
        write_csv(OUT_DIR / "possible_separators.csv", possible)
        write_csv(OUT_DIR / "failure_cause_candidates.csv", causes)
        write_csv(OUT_DIR / "removed_successful_buy_cases.csv", removed_success, MATRIX_FIELDS)
        write_csv(OUT_DIR / "removed_false_positive_cases.csv", removed_fp, MATRIX_FIELDS)
        write_csv(OUT_DIR / "missing_data_report.csv", missing)
        write_csv(OUT_DIR / "failure_analysis_warnings.csv", self.warnings)
        write_csv(OUT_DIR / "failure_analysis_errors.csv", self.errors)
        write_json(OUT_DIR / "failure_analysis_summary.json", summary)
        self._write_case_markdowns(removed_success, matrix)
        self._write_summary_md(summary, removed_success, removed_fp, kept_success, possible, causes, missing)
        for path in [
            "failure_feature_matrix.csv",
            "group_comparison.csv",
            "reason_comparison.csv",
            "possible_separators.csv",
            "failure_cause_candidates.csv",
            "removed_successful_buy_cases.csv",
            "removed_false_positive_cases.csv",
            "missing_data_report.csv",
            "failure_analysis_summary.json",
            "failure_analysis_summary.md",
        ]:
            src = OUT_DIR / path
            if src.exists():
                (run_dir / path).write_text(src.read_text(encoding="utf-8-sig"), encoding="utf-8")
        project_update = self._update_project(summary)
        summary["project_update"] = project_update
        write_json(OUT_DIR / "failure_analysis_summary.json", summary)
        validator_result = {
            "result": "PASS" if status != "FAILURE_ANALYSIS_FAILED" else "FAIL",
            "analysis_status": status,
            "recommended_next_action": recommended,
            "summary": summary,
        }
        write_json(OUT_DIR / "validator_result.json", validator_result)
        write_json(run_dir / "validator_result.json", validator_result)
        return summary

    def _target_rows(self) -> list[dict[str, str]]:
        rows = read_csv(GENERAL_DIR / "unseen_removed_buy.csv")
        return [row for row in rows if row.get("filter_rule_id") == RULE_ID]

    def _comparison_rows(self) -> list[dict[str, str]]:
        rows = read_csv(GENERAL_DIR / "unseen_horse_results.csv")
        focused = read_csv(FOCUSED_DIR / "focused_removed_buy.csv")
        by_key = {(row.get("race_id"), row.get("horse_name")): row for row in rows}
        for row in focused:
            by_key.setdefault((row.get("race_id"), row.get("horse_name")), row)
        return list(by_key.values())

    def _feature_matrix(self, target_rows: list[dict[str, str]], comparison_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
        keys = {(row.get("race_id"), row.get("horse_name")) for row in target_rows}
        rows: list[dict[str, Any]] = []
        for row in target_rows:
            rows.append(self._build_row(row, self._analysis_group(row)))
        for row in comparison_rows:
            key = (row.get("race_id"), row.get("horse_name"))
            if key in keys:
                continue
            if as_bool(row.get("production_buy")) and as_bool(row.get("shadow_buy")) and as_bool(row.get("is_top3")):
                rows.append(self._build_row(row, "KEPT_SUCCESSFUL_BUY"))
            elif as_bool(row.get("production_buy")) and as_bool(row.get("shadow_buy")) and not as_bool(row.get("is_top3")):
                rows.append(self._build_row(row, "KEPT_FALSE_POSITIVE"))
            elif not as_bool(row.get("production_buy")) and as_bool(row.get("is_top3")):
                rows.append(self._build_row(row, "NON_BUY_TOP3"))
        return rows

    def _analysis_group(self, row: dict[str, Any]) -> str:
        return "REMOVED_SUCCESSFUL_BUY" if as_bool(row.get("is_top3")) else "REMOVED_FALSE_POSITIVE"

    def _build_row(self, source: dict[str, Any], group: str) -> dict[str, Any]:
        race_id = source.get("race_id", "")
        horse_name = source.get("horse_name", "")
        horse = self._analysis_horse(race_id, horse_name)
        missing: list[str] = []
        def pick(key: str, fallback: Any = "NOT_AVAILABLE") -> Any:
            value = horse.get(key)
            if value in (None, ""):
                value = source.get(key, fallback)
            if value in (None, ""):
                missing.append(key)
                return fallback
            return value
        score_breakdown = horse.get("score_breakdown") if isinstance(horse.get("score_breakdown"), dict) else {}
        recent = self._recent_summary(horse.get("recent_runs"), source, missing)
        strengths = horse.get("final_strengths") or horse.get("strengths") or []
        risks = horse.get("final_risks") or horse.get("risk_factors") or []
        decision_risks = horse.get("decision_risks") or []
        row = {
            "race_id": race_id,
            "race_date": race_part(race_id, 1),
            "racecourse": source.get("racecourse") or race_part(race_id, 2),
            "race_number": source.get("race_number") or race_part(race_id, 3),
            "horse_number": source.get("horse_number") or pick("horse_number"),
            "horse_name": horse_name,
            "finish_position": source.get("finish_position"),
            "is_top3": source.get("is_top3"),
            "analysis_group": group,
            "validation_group": source.get("validation_group") or "UNSEEN_VALIDATION",
            "filter_rule_id": source.get("filter_rule_id") or RULE_ID,
            "surface": source.get("surface") or pick("surface"),
            "distance": source.get("distance") or pick("distance"),
            "distance_band": source.get("distance_band") or self._distance_band(source.get("distance") or horse.get("distance")),
            "track_condition": source.get("track_condition") or pick("track_condition"),
            "manual_track_bias": "NOT_AVAILABLE",
            "race_state": source.get("race_state") or source.get("rc1_race_state") or "NOT_AVAILABLE",
            "race_decision": horse.get("race_decision") or "NOT_AVAILABLE",
            "confidence": horse.get("confidence_level") or source.get("confidence") or "NOT_AVAILABLE",
            "class_name": source.get("race_class") or "NOT_AVAILABLE",
            "field_size": "NOT_AVAILABLE",
            "production_buy": source.get("production_buy"),
            "production_decision": source.get("rc1_decision") or ("BUY" if as_bool(source.get("production_buy")) else "NOT_BUY"),
            "production_score": source.get("decision_score") or pick("decision_score"),
            "final_score": source.get("final_score") or pick("final_score"),
            "adjusted_score": source.get("adjusted_score") or pick("adjusted_score"),
            "buy_rank": source.get("ai_rank"),
            "decision_score": source.get("decision_score") or pick("decision_score"),
            "buy_reason": horse.get("decision_reason") or source.get("rc1_reason") or "NOT_AVAILABLE",
            "danger_reason": dump_list(decision_risks or risks),
            "explain_summary": horse.get("explain_summary") or horse.get("explanation") or "NOT_AVAILABLE",
            "shadow_buy": source.get("shadow_buy"),
            "removed_by_shadow": source.get("removed_by_shadow"),
            "shadow_filter_reason": source.get("shadow_fp_filter_reason") or "NOT_AVAILABLE",
            "strong_positive_count": source.get("strong_positive_count"),
            "strong_negative_count": source.get("strong_negative_count") or "NOT_AVAILABLE",
            "filter_rule_matched": source.get("filter_rule_id") == RULE_ID or as_bool(source.get("removed_by_shadow")),
            "past_performance_score": horse.get("past_performance_score") or score_breakdown.get("Past") or "NOT_AVAILABLE",
            "distance_score": horse.get("distance_score") or score_breakdown.get("Distance") or "NOT_AVAILABLE",
            "course_shape_score": horse.get("course_shape_score") or score_breakdown.get("CourseShape") or "NOT_AVAILABLE",
            "pace_style_score": horse.get("pace_style_score") or score_breakdown.get("Pace") or "NOT_AVAILABLE",
            "lap_score": horse.get("lap_score") or score_breakdown.get("Lap") or "NOT_AVAILABLE",
            "race_shape_score": horse.get("shape_score") or score_breakdown.get("Shape") or "NOT_AVAILABLE",
            "track_bias_score": horse.get("track_bias_score") or score_breakdown.get("TrackBias") or "NOT_AVAILABLE",
            "bloodline_score": horse.get("bloodline_score") or score_breakdown.get("Bloodline") or "NOT_AVAILABLE",
            "track_condition_score": horse.get("track_condition_score") or score_breakdown.get("Track") or "NOT_AVAILABLE",
            "impact_score": horse.get("impact_score") if horse.get("impact_score") is not None else "NOT_AVAILABLE",
            "consistency_score": horse.get("consistency_score") if horse.get("consistency_score") is not None else "NOT_AVAILABLE",
            "positive_reasons": dump_list(strengths),
            "strong_positive_reasons": dump_list(horse.get("strong_matches") or []),
            "negative_reasons": dump_list(horse.get("weaknesses") or []),
            "danger_factors": dump_list(risks),
            "positive_reason_count": len(strengths) if isinstance(strengths, list) else 0,
            "negative_reason_count": len(risks) if isinstance(risks, list) else 0,
            **recent,
            "missing_features": ";".join(sorted(set(missing))) if missing else "",
            "feature_sources": json.dumps(self._feature_sources(), ensure_ascii=False, sort_keys=True),
        }
        for key in MATRIX_FIELDS:
            row.setdefault(key, "NOT_AVAILABLE")
        return row

    def _analysis_horse(self, race_id: str, horse_name: str) -> dict[str, Any]:
        try:
            race_set = self._race_sets().get(race_id)
            if not race_set:
                self.errors.append({"race_id": race_id, "horse_name": horse_name, "error": "race_set_not_found"})
                return {}
            analysis = self.adapter.run(race_set.get("entry_path"), horse_data_csv_path=race_set.get("horses_path"))
            for horse in analysis.get("ranked_results", []):
                if norm_name(horse.get("horse_name")) == norm_name(horse_name):
                    return horse
            self.errors.append({"race_id": race_id, "horse_name": horse_name, "error": "horse_not_found_in_analysis"})
        except Exception as exc:
            self.errors.append({"race_id": race_id, "horse_name": horse_name, "error": str(exc)})
        return {}

    def _race_sets(self) -> dict[str, dict[str, Any]]:
        if not hasattr(self, "_race_sets_cache"):
            self._race_sets_cache = {
                row.get("race_id"): row
                for row in self.locator.find_complete_race_sets("data/analysis", "data/results").get("complete_sets", [])
            }
        return self._race_sets_cache

    def _recent_summary(self, recent_runs: Any, source: dict[str, Any], missing: list[str]) -> dict[str, Any]:
        runs = recent_runs if isinstance(recent_runs, list) else []
        if not runs:
            missing.append("recent_runs")
        finishes = [to_int(row.get("finish_position")) for row in runs if to_int(row.get("finish_position")) is not None]
        margins = [to_float(row.get("margin")) for row in runs if to_float(row.get("margin")) is not None]
        last3f = [to_float(row.get("last_3f")) for row in runs if to_float(row.get("last_3f")) is not None]
        surface = source.get("surface")
        band = source.get("distance_band")
        return {
            "recent_run_count": len(runs),
            "recent_top3_count": sum(1 for v in finishes if v <= 3),
            "recent_top5_count": sum(1 for v in finishes if v <= 5),
            "recent_avg_finish": round(statistics.mean(finishes), 2) if finishes else "NOT_AVAILABLE",
            "recent_avg_margin": round(statistics.mean(margins), 2) if margins else "NOT_AVAILABLE",
            "recent_avg_last3f": round(statistics.mean(last3f), 2) if last3f else "NOT_AVAILABLE",
            "recent_last3f_top_count": sum(1 for value in last3f if value <= 36.5),
            "recent_same_surface_top3": sum(
                1 for row in runs
                if self._surface_norm(row.get("surface")) == self._surface_norm(surface)
                and (to_int(row.get("finish_position")) or 99) <= 3
            ),
            "recent_same_distance_band_top3": sum(
                1 for row in runs
                if self._distance_band(row.get("distance")) == band
                and (to_int(row.get("finish_position")) or 99) <= 3
            ),
            "recent_class_names": ";".join(str(row.get("class_level") or "") for row in runs if row.get("class_level")),
        }

    def _surface_norm(self, value: Any) -> str:
        text = str(value or "").lower()
        if text in {"ダ", "d", "dirt"}:
            return "dirt"
        if text in {"芝", "t", "turf"}:
            return "turf"
        return text

    def _distance_band(self, value: Any) -> str:
        distance = to_int(value)
        if distance is None:
            return "NOT_AVAILABLE"
        if distance <= 1400:
            return "sprint"
        if distance <= 1800:
            return "mile"
        if distance <= 2200:
            return "middle"
        return "long"

    def _group_comparison(self, matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
        success = [row for row in matrix if row.get("analysis_group") == "REMOVED_SUCCESSFUL_BUY"]
        fp = [row for row in matrix if row.get("analysis_group") == "REMOVED_FALSE_POSITIVE"]
        rows: list[dict[str, Any]] = []
        for feature in NUMERIC_FEATURES:
            rows.append(self._numeric_compare(feature, success, fp))
        for feature in ["racecourse", "surface", "distance_band", "track_condition", "race_state", "confidence"]:
            rows.extend(self._categorical_compare(feature, success, fp))
        return rows

    def _numeric_compare(self, feature: str, success: list[dict[str, Any]], fp: list[dict[str, Any]]) -> dict[str, Any]:
        sv = [to_float(row.get(feature)) for row in success if to_float(row.get(feature)) is not None]
        fv = [to_float(row.get(feature)) for row in fp if to_float(row.get(feature)) is not None]
        diff = round((statistics.mean(sv) if sv else 0) - (statistics.mean(fv) if fv else 0), 2) if sv and fv else "NOT_AVAILABLE"
        status = "POSSIBLE_SEPARATOR" if isinstance(diff, (int, float)) and abs(diff) >= 5 else "NO_CLEAR_DIFFERENCE"
        if len(sv) < 2 or len(fv) < 3:
            status = "INSUFFICIENT_SAMPLE" if status != "POSSIBLE_SEPARATOR" else "OBSERVED_DIFFERENCE"
        return {
            "comparison_type": "numeric",
            "feature_name": feature,
            "successful_count": len(sv),
            "false_positive_count": len(fv),
            "successful_mean": round(statistics.mean(sv), 2) if sv else "NOT_AVAILABLE",
            "false_positive_mean": round(statistics.mean(fv), 2) if fv else "NOT_AVAILABLE",
            "successful_median": round(statistics.median(sv), 2) if sv else "NOT_AVAILABLE",
            "false_positive_median": round(statistics.median(fv), 2) if fv else "NOT_AVAILABLE",
            "successful_min": min(sv) if sv else "NOT_AVAILABLE",
            "false_positive_min": min(fv) if fv else "NOT_AVAILABLE",
            "successful_max": max(sv) if sv else "NOT_AVAILABLE",
            "false_positive_max": max(fv) if fv else "NOT_AVAILABLE",
            "group_difference": diff,
            "interpretation": status,
        }

    def _categorical_compare(self, feature: str, success: list[dict[str, Any]], fp: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sc = Counter(str(row.get(feature) or "NOT_AVAILABLE") for row in success)
        fc = Counter(str(row.get(feature) or "NOT_AVAILABLE") for row in fp)
        rows = []
        for value in sorted(set(sc) | set(fc)):
            rows.append(
                {
                    "comparison_type": "category",
                    "feature_name": feature,
                    "feature_value": value,
                    "successful_count": sc.get(value, 0),
                    "false_positive_count": fc.get(value, 0),
                    "successful_ratio": round(sc.get(value, 0) / len(success) * 100, 1) if success else 0,
                    "false_positive_ratio": round(fc.get(value, 0) / len(fp) * 100, 1) if fp else 0,
                    "interpretation": "OBSERVED_DIFFERENCE" if sc.get(value, 0) and not fc.get(value, 0) or fc.get(value, 0) and not sc.get(value, 0) else "NO_CLEAR_DIFFERENCE",
                }
            )
        return rows

    def _reason_comparison(self, matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups = {
            "REMOVED_SUCCESSFUL_BUY": [row for row in matrix if row.get("analysis_group") == "REMOVED_SUCCESSFUL_BUY"],
            "REMOVED_FALSE_POSITIVE": [row for row in matrix if row.get("analysis_group") == "REMOVED_FALSE_POSITIVE"],
            "KEPT_SUCCESSFUL_BUY": [row for row in matrix if row.get("analysis_group") == "KEPT_SUCCESSFUL_BUY"],
        }
        rows = []
        for field in ["positive_reasons", "danger_factors", "negative_reasons", "strong_positive_reasons"]:
            counters = {name: self._reason_counter(items, field) for name, items in groups.items()}
            for reason in sorted(set().union(*(counter.keys() for counter in counters.values()))):
                rows.append(
                    {
                        "reason_field": field,
                        "reason_text": reason,
                        "removed_successful_buy_count": counters["REMOVED_SUCCESSFUL_BUY"].get(reason, 0),
                        "removed_false_positive_count": counters["REMOVED_FALSE_POSITIVE"].get(reason, 0),
                        "kept_successful_buy_count": counters["KEPT_SUCCESSFUL_BUY"].get(reason, 0),
                        "observation": self._reason_observation(
                            counters["REMOVED_SUCCESSFUL_BUY"].get(reason, 0),
                            counters["REMOVED_FALSE_POSITIVE"].get(reason, 0),
                            counters["KEPT_SUCCESSFUL_BUY"].get(reason, 0),
                        ),
                    }
                )
        return rows

    def _reason_counter(self, rows: list[dict[str, Any]], field: str) -> Counter:
        counter = Counter()
        for row in rows:
            values = self._parse_reason_field(row.get(field))
            counter.update(values)
        return counter

    def _parse_reason_field(self, value: Any) -> list[str]:
        if not value:
            return []
        text = str(value)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
        return [part.strip() for part in text.replace("；", ";").split(";") if part.strip()]

    def _reason_observation(self, success_count: int, fp_count: int, kept_count: int) -> str:
        if success_count and not fp_count:
            return "SUCCESSFUL_BUY_ONLY"
        if fp_count and not success_count:
            return "FALSE_POSITIVE_ONLY"
        if success_count and fp_count:
            return "COMMON_TO_REMOVED_GROUPS"
        if kept_count:
            return "KEPT_SUCCESSFUL_REFERENCE"
        return "NO_CLEAR_DIFFERENCE"

    def _possible_separators(self, matrix: list[dict[str, Any]], group_rows: list[dict[str, Any]], reason_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in group_rows:
            if row.get("comparison_type") == "numeric" and row.get("interpretation") in {"POSSIBLE_SEPARATOR", "OBSERVED_DIFFERENCE"}:
                out.append(
                    {
                        "feature_name": row.get("feature_name"),
                        "successful_buy_values": row.get("successful_mean"),
                        "false_positive_values": row.get("false_positive_mean"),
                        "observed_difference": row.get("group_difference"),
                        "exceptions": "small_sample",
                        "data_completeness": f"{row.get('successful_count')}/{row.get('false_positive_count')}",
                        "sample_size": len(matrix),
                        "recommendation": "REVIEW_NEXT",
                    }
                )
        for row in reason_rows:
            if row.get("observation") == "SUCCESSFUL_BUY_ONLY":
                out.append(
                    {
                        "feature_name": f"{row.get('reason_field')}:{row.get('reason_text')}",
                        "successful_buy_values": row.get("removed_successful_buy_count"),
                        "false_positive_values": row.get("removed_false_positive_count"),
                        "observed_difference": "reason_present_only_in_removed_successful_buy",
                        "exceptions": "needs_more_cases",
                        "data_completeness": "reason_text_available",
                        "sample_size": len(matrix),
                        "recommendation": "REVIEW_NEXT",
                    }
                )
        return out[:20]

    def _cause_candidates(self, matrix: list[dict[str, Any]], possible: list[dict[str, Any]]) -> list[dict[str, Any]]:
        success = [row for row in matrix if row.get("analysis_group") == "REMOVED_SUCCESSFUL_BUY"]
        fp = [row for row in matrix if row.get("analysis_group") == "REMOVED_FALSE_POSITIVE"]
        candidates = []
        candidates.append(
            {
                "cause_category": "COUNT_ONLY_LIMITATION",
                "evidence": "SP_COUNT_EQ_2 removed both false positives and successful BUY horses with the same strong_positive_count.",
                "supporting_horses": ";".join(row.get("horse_name", "") for row in success),
                "counter_examples": ";".join(row.get("horse_name", "") for row in fp[:3]),
                "sample_count": len(success) + len(fp),
                "confidence_level": "MEDIUM" if success and fp else "LOW",
                "human_review_required": "True",
            }
        )
        if any(item.get("feature_name") in {"distance_score", "past_performance_score", "adjusted_score", "final_score"} for item in possible):
            candidates.append(
                {
                    "cause_category": "HIGH_VALUE_POSITIVE_NOT_WEIGHTED",
                    "evidence": "A value-based feature differs between removed successful BUY and removed FP; count-only rule ignores feature magnitude.",
                    "supporting_horses": ";".join(row.get("horse_name", "") for row in success),
                    "counter_examples": "see group_comparison.csv",
                    "sample_count": len(success),
                    "confidence_level": "LOW",
                    "human_review_required": "True",
                }
            )
        if any(row.get("surface") == "dirt" for row in success):
            candidates.append(
                {
                    "cause_category": "SURFACE_DEPENDENCY",
                    "evidence": "Removed successful BUY includes dirt cases; surface split should be human-reviewed before reusing the rule.",
                    "supporting_horses": ";".join(row.get("horse_name", "") for row in success if row.get("surface") == "dirt"),
                    "counter_examples": ";".join(row.get("horse_name", "") for row in fp if row.get("surface") == "dirt"),
                    "sample_count": len(success) + len(fp),
                    "confidence_level": "LOW",
                    "human_review_required": "True",
                }
            )
        candidates.append(
            {
                "cause_category": "INSUFFICIENT_SAMPLE",
                "evidence": "Only 2 removed successful BUY and 5 removed FP are available in General Unseen.",
                "supporting_horses": ";".join(row.get("horse_name", "") for row in success),
                "counter_examples": "",
                "sample_count": len(success) + len(fp),
                "confidence_level": "MEDIUM",
                "human_review_required": "True",
            }
        )
        return candidates

    def _missing_data_report(self, matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts = Counter()
        examples = defaultdict(list)
        for row in matrix:
            for feature in str(row.get("missing_features") or "").split(";"):
                if feature:
                    counts[feature] += 1
                    examples[feature].append(f"{row.get('race_id')}:{row.get('horse_name')}")
        if not counts:
            return []
        return [
            {
                "feature_name": feature,
                "missing_count": count,
                "examples": ";".join(examples[feature][:5]),
                "handling": "NOT_AVAILABLE",
            }
            for feature, count in counts.most_common()
        ]

    def _analysis_status(self, matrix, removed_success, removed_fp) -> str:
        if self.errors:
            return "FAILURE_ANALYSIS_COMPLETED_WITH_WARNINGS"
        if not matrix or not removed_success or not removed_fp:
            return "FAILURE_ANALYSIS_INSUFFICIENT_DATA"
        return "FAILURE_ANALYSIS_COMPLETED"

    def _recommended_next_action(self, possible, missing, removed_success, removed_fp) -> str:
        if missing and len(missing) >= 5:
            return "DATA_COMPLETENESS_REQUIRED"
        if possible:
            return "REVIEW_POSSIBLE_SEPARATOR"
        if len(removed_success) + len(removed_fp) < 10:
            return "COLLECT_MORE_FAILURE_CASES"
        return "NO_RELIABLE_SEPARATOR_FOUND"

    def _fingerprint(self, *items: Any) -> str:
        text = json.dumps(items, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _update_project(self, summary: dict[str, Any]) -> dict[str, Any]:
        repo = ShadowValidationRepository()
        projects = repo.load()
        project = projects.get(self.project_id)
        if not project:
            return {"updated": False, "reason": "project_not_found", "history_appended": False}
        result_summary = project.result_summary if isinstance(project.result_summary, dict) else {}
        prior = result_summary.get("failure_analysis") if isinstance(result_summary.get("failure_analysis"), dict) else {}
        if prior.get("analysis_fingerprint") == summary.get("analysis_fingerprint"):
            return {"updated": False, "reason": "same_analysis_fingerprint", "history_appended": False}
        record = {
            "analysis_run_id": summary.get("analysis_run_id"),
            "analysis_fingerprint": summary.get("analysis_fingerprint"),
            "rule_id": RULE_ID,
            "source_validation_run_id": self._source_validation_run_id(),
            "target_removed_buy_count": summary.get("target_removed_buy_count"),
            "removed_successful_buy_count": summary.get("removed_successful_buy_count"),
            "removed_fp_count": summary.get("removed_fp_count"),
            "possible_separator_count": summary.get("possible_separator_count"),
            "cause_candidate_count": summary.get("cause_candidate_count"),
            "missing_feature_count": summary.get("missing_feature_count"),
            "analysis_status": summary.get("analysis_status"),
            "recommended_next_action": summary.get("recommended_next_action"),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }
        result_summary["failure_analysis"] = record
        project.result_summary = result_summary
        project.updated_at = datetime.now().isoformat(timespec="seconds")
        projects[self.project_id] = project
        repo.save(projects)
        repo.append_history(
            project,
            action="failure_analysis_complete",
            old_status=project.project_status,
            new_status=project.project_status,
            reason=f"{record['analysis_status']}:{record['recommended_next_action']}",
            source="FailureAnalysisEngine",
        )
        return {"updated": True, "history_appended": True}

    def _source_validation_run_id(self) -> str:
        path = GENERAL_DIR / "unseen_validation_summary.json"
        if not path.exists():
            return ""
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("validation_run_id", "")

    def _feature_sources(self) -> dict[str, str]:
        return {
            "removed_buy": str(GENERAL_DIR / "unseen_removed_buy.csv"),
            "horse_results": str(GENERAL_DIR / "unseen_horse_results.csv"),
            "focused_reference": str(FOCUSED_DIR / "focused_removed_buy.csv"),
            "evaluator_features": "TargetTrialAdapter current analysis output",
            "past_runs": "ranked_results.recent_runs",
        }

    def _write_case_markdowns(self, cases: list[dict[str, Any]], matrix: list[dict[str, Any]]) -> None:
        case_dir = OUT_DIR / "cases"
        case_dir.mkdir(parents=True, exist_ok=True)
        fp_rows = [row for row in matrix if row.get("analysis_group") == "REMOVED_FALSE_POSITIVE"]
        kept_rows = [row for row in matrix if row.get("analysis_group") == "KEPT_SUCCESSFUL_BUY"]
        for row in cases:
            path = case_dir / f"race_{row.get('race_id')}_horse_{row.get('horse_number')}.md"
            lines = [
                f"# {row.get('race_id')} {row.get('horse_name')}",
                "",
                "## Race / Horse",
                f"- Horse Number: {row.get('horse_number')}",
                f"- Finish: {row.get('finish_position')}",
                f"- Surface/Distance: {row.get('surface')} {row.get('distance')}",
                "",
                "## Production Evaluation",
                f"- FinalScore: {row.get('final_score')}",
                f"- AdjustedScore: {row.get('adjusted_score')}",
                f"- DecisionScore: {row.get('decision_score')}",
                f"- BUY reason: {row.get('buy_reason')}",
                f"- Positive: {row.get('positive_reasons')}",
                f"- Negative/Risk: {row.get('danger_factors')}",
                "",
                "## Shadow Removal",
                f"- strong_positive_count: {row.get('strong_positive_count')}",
                f"- reason: {row.get('shadow_filter_reason')}",
                "",
                "## Comparison with Removed FP",
                f"- Removed FP count: {len(fp_rows)}",
                f"- Common surface count: {sum(1 for fp in fp_rows if fp.get('surface') == row.get('surface'))}",
                f"- Common distance band count: {sum(1 for fp in fp_rows if fp.get('distance_band') == row.get('distance_band'))}",
                "",
                "## Comparison with Kept Successful BUY",
                f"- Kept Successful BUY count: {len(kept_rows)}",
                f"- Same surface count: {sum(1 for kept in kept_rows if kept.get('surface') == row.get('surface'))}",
                "",
                "## Observed Findings",
                "- The shadow rule matched a successful BUY because it only looked at strong_positive_count.",
                "",
                "## Possible Failure Cause",
                "- COUNT_ONLY_LIMITATION",
                "- HIGH_VALUE_POSITIVE_NOT_WEIGHTED may require review if score features separate this horse from removed FP.",
                "",
                "## Missing Information",
                f"- {row.get('missing_features') or 'none'}",
                "",
                "## Human Review Questions",
                "- Are the two strong positives high-value reasons that should not be treated the same as weaker positives?",
                "- Does this case depend on surface/course/distance conditions?",
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_summary_md(self, summary, removed_success, removed_fp, kept_success, possible, causes, missing) -> None:
        lines = [
            "# Failure Analysis: SP_COUNT_EQ_2",
            "",
            "## Executive Summary",
            f"- Removed BUY analyzed: {summary['target_removed_buy_count']}",
            f"- Removed Successful BUY: {summary['removed_successful_buy_count']}",
            f"- Removed FP: {summary['removed_fp_count']}",
            f"- Possible Separators: {summary['possible_separator_count']}",
            f"- Status: {summary['analysis_status']}",
            f"- Recommended Next Action: {summary['recommended_next_action']}",
            "",
            "## Shadow Rule",
            "- SP_COUNT_EQ_2: strong_positive_count == 2",
            "",
            "## Validation Results",
            "- Development / General / Focused results are referenced from saved validation reports; not rewritten.",
            "",
            "## Removed Successful BUY",
        ]
        lines.extend(f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')}" for row in removed_success)
        lines.extend(["", "## Removed False Positive"])
        lines.extend(f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')}" for row in removed_fp)
        lines.extend(["", "## Successful BUY vs FP Comparison"])
        lines.append("- See group_comparison.csv and reason_comparison.csv.")
        lines.extend(["", "## Possible Separators"])
        if possible:
            lines.extend(f"- {row.get('feature_name')}: {row.get('observed_difference')} ({row.get('recommendation')})" for row in possible[:10])
        else:
            lines.append("- none")
        lines.extend(["", "## Counter Examples"])
        lines.append("- Removed FP rows with the same rule match remain counter examples; see removed_false_positive_cases.csv.")
        lines.extend(["", "## Missing Data"])
        if missing:
            lines.extend(f"- {row.get('feature_name')}: {row.get('missing_count')}" for row in missing[:10])
        else:
            lines.append("- none")
        lines.extend(["", "## Failure Cause Candidates"])
        lines.extend(f"- {row.get('cause_category')}: {row.get('evidence')}" for row in causes)
        lines.extend(["", "## Human Review Questions"])
        lines.append("- Which positive reasons are high-value enough that count-only filtering should not remove the BUY?")
        lines.append("- Are surface/course/distance dependencies responsible for the successful BUY removals?")
        lines.extend(["", "## Recommended Next Action"])
        lines.append(f"- {summary['recommended_next_action']}")
        (OUT_DIR / "failure_analysis_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

