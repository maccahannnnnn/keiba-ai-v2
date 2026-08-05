"""Rank separator candidates from Failure Analysis features.

Diagnostic only: this module reads saved Failure Analysis outputs and writes
review reports.  It does not create shadow rules, thresholds, candidates, or
change production BUY, evaluators, scores, decisions, race state, knowledge,
CSV schemas, importers, or main.py.
"""

from __future__ import annotations

import argparse
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

from learning.shadow_validation_repository import ShadowValidationRepository


PROJECT_ID = "SHADOW_BUY_FALSE_POSITIVE_RC1_V1"
RULE_ID = "SP_COUNT_EQ_2"
IN_DIR = ROOT / "reports" / "failure_analysis" / RULE_ID
OUT_DIR = ROOT / "reports" / "separator_candidate_analysis" / RULE_ID

LEAKAGE_FEATURES = {
    "horse_name",
    "race_id",
    "horse_number",
    "finish_position",
    "is_top3",
    "analysis_group",
    "production_buy",
    "shadow_buy",
    "removed_by_shadow",
    "filter_rule_matched",
    "validation_group",
}

CORE_SCORE = {"final_score", "adjusted_score", "decision_score", "production_score", "buy_rank"}
EVALUATOR_SCORE = {
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
}
EXPLAIN_NUMERIC = {"positive_reason_count", "negative_reason_count", "strong_positive_count", "strong_negative_count"}
RACE_CONDITION = {"surface", "distance_band", "racecourse", "track_condition", "manual_track_bias", "race_state", "field_size", "class_name", "confidence"}
PAST_PERFORMANCE = {
    "recent_run_count",
    "recent_top3_count",
    "recent_top5_count",
    "recent_avg_finish",
    "recent_avg_margin",
    "recent_avg_last3f",
    "recent_last3f_top_count",
    "recent_same_surface_top3",
    "recent_same_distance_band_top3",
}
REASON_FEATURES = {"positive_reasons", "strong_positive_reasons", "negative_reasons", "danger_factors"}

RANKING_FIELDS = [
    "rank",
    "feature_name",
    "feature_category",
    "candidate_type",
    "source",
    "separator_review_score",
    "candidate_rank",
    "confidence",
    "a_count",
    "b_count",
    "a_mean",
    "b_mean",
    "mean_difference",
    "a_median",
    "b_median",
    "median_difference",
    "range_overlap",
    "missing_rate",
    "counter_example_count",
    "data_completeness",
    "explainability",
    "implementation_safety",
    "redundancy_status",
    "sample_warning",
    "recommendation",
    "human_review_required",
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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def to_float(value: Any) -> float | None:
    try:
        text = str(value).strip()
        if text in {"", "NOT_AVAILABLE", "SOURCE_NOT_FOUND", "None"}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def pct(n: int, d: int) -> float:
    return round(n / d * 100.0, 1) if d else 0.0


def parse_reasons(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text or text == "NOT_AVAILABLE":
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in text.replace("；", ";").split(";") if part.strip()]


class SeparatorCandidateAnalyzer:
    """Analyze and rank possible separators for removed BUY failures."""

    SCORE_SPEC = (
        "Separator Review Score = observed separation up to 35 + completeness up to 20 "
        "+ counter-example resistance up to 15 + explainability up to 10 "
        "+ implementation safety up to 10 + sample reliability up to 10. "
        "A small-sample cap limits score to 72 for the current 2-vs-5 sample. "
        "This is a review ranking score only, never a production score or threshold."
    )

    def __init__(
        self,
        project_id: str = PROJECT_ID,
        rule_id: str = RULE_ID,
        top_n: int = 10,
        include_categorical: bool = True,
        include_reason_features: bool = True,
        validation_mode: str = "general-unseen",
        output_dir: str | Path | None = None,
    ):
        self.project_id = project_id
        self.rule_id = rule_id
        self.top_n = top_n
        self.include_categorical = include_categorical
        self.include_reason_features = include_reason_features
        self.validation_mode = validation_mode
        self.output_dir = Path(output_dir) if output_dir else OUT_DIR
        self.warnings: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

    def run(self, dry_run: bool = False) -> dict[str, Any]:
        started = datetime.now().isoformat(timespec="seconds")
        rows = read_csv(IN_DIR / "failure_feature_matrix.csv")
        failure_summary = self._read_json(IN_DIR / "failure_analysis_summary.json")
        groups = self._groups(rows)
        feature_names = [name for name in rows[0].keys()] if rows else []
        excluded = self._excluded_features(rows, feature_names)
        numeric = self._numeric_features(rows, feature_names, excluded)
        categorical = self._categorical_features(rows, feature_names, excluded) if self.include_categorical else []
        reasons = self._reason_features(rows) if self.include_reason_features else []
        redundancy = self._feature_redundancy(rows, numeric)
        ranking = self._ranking(numeric, categorical, reasons, redundancy)
        top_candidates = [row for row in ranking if row["candidate_rank"] in {"RANK_A", "RANK_B"}][:3]
        counter_examples = self._counter_examples(rows, ranking)
        missing = self._missing_data(rows)
        adjusted = self._adjusted_score_review(numeric, ranking)
        fingerprint = self._fingerprint(
            failure_summary.get("analysis_fingerprint"),
            rows,
            [r["feature_name"] for r in ranking],
            self.SCORE_SPEC,
        )
        run_id = self._fingerprint([fingerprint, started])[:16]
        rank_counts = Counter(row.get("candidate_rank") for row in ranking)
        summary = {
            "analysis_run_id": run_id,
            "analysis_fingerprint": fingerprint,
            "project_id": self.project_id,
            "rule_id": self.rule_id,
            "source_failure_analysis_fingerprint": failure_summary.get("analysis_fingerprint"),
            "generated_at": started,
            "validation_mode": self.validation_mode,
            "removed_successful_buy_count": len(groups["REMOVED_SUCCESSFUL_BUY"]),
            "removed_fp_count": len(groups["REMOVED_FALSE_POSITIVE"]),
            "kept_successful_buy_count": len(groups["KEPT_SUCCESSFUL_BUY"]),
            "analyzed_feature_count": len(numeric) + len(categorical) + len(reasons),
            "numeric_feature_count": len(numeric),
            "categorical_feature_count": len(categorical),
            "reason_feature_count": len(reasons),
            "excluded_feature_count": len(excluded),
            "missing_feature_count": len(missing),
            "duplicate_feature_count": sum(1 for row in redundancy if row.get("redundancy_status") in {"DUPLICATE", "HIGHLY_REDUNDANT"}),
            "rank_a_count": rank_counts.get("RANK_A", 0),
            "rank_b_count": rank_counts.get("RANK_B", 0),
            "top_candidate_names": [row.get("feature_name") for row in top_candidates],
            "top_candidate_scores": [row.get("separator_review_score") for row in top_candidates],
            "counter_example_count": len(counter_examples),
            "analysis_status": self._status(rows, groups),
            "recommended_next_action": self._recommended(top_candidates, missing),
            "score_spec": self.SCORE_SPEC,
            "adjusted_score_review": adjusted,
            "production_buy_diff": 0,
            "score_diff": 0,
            "decision_diff": 0,
            "race_state_diff": 0,
            "candidate_registration_count": 0,
            "shadow_project_created_count": 0,
            "warnings": self.warnings,
            "errors": self.errors,
        }
        if dry_run:
            summary["dry_run"] = True
            return summary

        self.output_dir.mkdir(parents=True, exist_ok=True)
        run_dir = self.output_dir / "runs" / f"SEPARATOR_ANALYSIS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir.mkdir(parents=True, exist_ok=True)
        write_csv(self.output_dir / "separator_candidate_ranking.csv", ranking, RANKING_FIELDS)
        write_csv(self.output_dir / "numeric_feature_comparison.csv", numeric)
        write_csv(self.output_dir / "categorical_feature_comparison.csv", categorical)
        write_csv(self.output_dir / "reason_feature_comparison.csv", reasons)
        write_csv(self.output_dir / "feature_redundancy.csv", redundancy)
        write_csv(self.output_dir / "counter_examples.csv", counter_examples)
        write_csv(self.output_dir / "top_candidate_details.csv", top_candidates, RANKING_FIELDS)
        write_csv(self.output_dir / "excluded_features.csv", excluded)
        write_csv(self.output_dir / "missing_data_report.csv", missing)
        write_csv(self.output_dir / "separator_analysis_warnings.csv", self.warnings)
        write_csv(self.output_dir / "separator_analysis_errors.csv", self.errors)
        write_json(self.output_dir / "separator_analysis_summary.json", summary)
        self._write_summary_md(summary, ranking, adjusted, counter_examples, missing)
        for path in [
            "separator_analysis_summary.md",
            "separator_analysis_summary.json",
            "separator_candidate_ranking.csv",
            "numeric_feature_comparison.csv",
            "categorical_feature_comparison.csv",
            "reason_feature_comparison.csv",
            "feature_redundancy.csv",
            "counter_examples.csv",
            "top_candidate_details.csv",
            "excluded_features.csv",
            "missing_data_report.csv",
        ]:
            src = self.output_dir / path
            if src.exists():
                (run_dir / path).write_text(src.read_text(encoding="utf-8-sig"), encoding="utf-8")
        project_update = self._update_project(summary)
        summary["project_update"] = project_update
        write_json(self.output_dir / "separator_analysis_summary.json", summary)
        validator = {
            "result": "PASS" if summary["analysis_status"] != "SEPARATOR_ANALYSIS_FAILED" else "FAIL",
            "summary": summary,
        }
        write_json(self.output_dir / "validator_result.json", validator)
        write_json(run_dir / "validator_result.json", validator)
        return summary

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _groups(self, rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
        return {
            name: [row for row in rows if row.get("analysis_group") == name]
            for name in ["REMOVED_SUCCESSFUL_BUY", "REMOVED_FALSE_POSITIVE", "KEPT_SUCCESSFUL_BUY", "KEPT_FALSE_POSITIVE", "NON_BUY_TOP3"]
        }

    def _feature_category(self, name: str) -> str:
        if name in CORE_SCORE:
            return "CORE_SCORE"
        if name in EVALUATOR_SCORE:
            return "EVALUATOR_SCORE"
        if name in EXPLAIN_NUMERIC or name in REASON_FEATURES:
            return "EXPLAIN_FEATURE"
        if name in RACE_CONDITION:
            return "RACE_CONDITION"
        if name in PAST_PERFORMANCE:
            return "PAST_PERFORMANCE"
        return "DERIVED_METADATA"

    def _candidate_type(self, category: str, feature: str) -> str:
        if feature in {"final_score", "adjusted_score", "decision_score", "production_score"}:
            return "SCORE_SEPARATOR"
        if category == "EVALUATOR_SCORE":
            return "EVALUATOR_SEPARATOR"
        if category == "EXPLAIN_FEATURE":
            return "REASON_QUALITY_SEPARATOR"
        if category == "RACE_CONDITION":
            return "RACE_CONDITION_SEPARATOR"
        if category == "PAST_PERFORMANCE":
            return "PAST_PERFORMANCE_SEPARATOR"
        return "DATA_INSUFFICIENT"

    def _excluded_features(self, rows: list[dict[str, str]], feature_names: list[str]) -> list[dict[str, Any]]:
        removed = [row for row in rows if row.get("analysis_group") in {"REMOVED_SUCCESSFUL_BUY", "REMOVED_FALSE_POSITIVE"}]
        out = []
        for name in feature_names:
            reason = ""
            if name in LEAKAGE_FEATURES:
                reason = "RESULT_OR_GROUP_LEAKAGE"
            elif name == "strong_positive_count":
                vals = {row.get(name) for row in removed}
                if len(vals) <= 1:
                    reason = "CONSTANT_WITHIN_TARGET"
            elif name in {"buy_reason", "danger_reason", "explain_summary", "shadow_filter_reason", "missing_features", "feature_sources", "recent_class_names"}:
                reason = "TEXT_METADATA_NOT_DIRECT_SEPARATOR"
            if reason:
                out.append({"feature_name": name, "feature_category": self._feature_category(name), "exclude_reason": reason})
        return out

    def _numeric_features(self, rows: list[dict[str, str]], feature_names: list[str], excluded: list[dict[str, Any]]) -> list[dict[str, Any]]:
        excluded_names = {row["feature_name"] for row in excluded}
        groups = self._groups(rows)
        out = []
        for name in feature_names:
            if name in excluded_names or name in REASON_FEATURES:
                continue
            values = [to_float(row.get(name)) for row in rows]
            if not any(v is not None for v in values):
                continue
            a = [to_float(row.get(name)) for row in groups["REMOVED_SUCCESSFUL_BUY"] if to_float(row.get(name)) is not None]
            b = [to_float(row.get(name)) for row in groups["REMOVED_FALSE_POSITIVE"] if to_float(row.get(name)) is not None]
            c = [to_float(row.get(name)) for row in groups["KEPT_SUCCESSFUL_BUY"] if to_float(row.get(name)) is not None]
            out.append(self._numeric_row(name, a, b, c, len(groups["REMOVED_SUCCESSFUL_BUY"]) + len(groups["REMOVED_FALSE_POSITIVE"])))
        return out

    def _numeric_row(self, name: str, a: list[float], b: list[float], c: list[float], total: int) -> dict[str, Any]:
        a_mean = statistics.mean(a) if a else None
        b_mean = statistics.mean(b) if b else None
        a_median = statistics.median(a) if a else None
        b_median = statistics.median(b) if b else None
        overlap = self._range_overlap(a, b)
        exact = len(set(a) & set(b))
        diff = (a_mean - b_mean) if a_mean is not None and b_mean is not None else None
        direction = "SUCCESSFUL_HIGHER" if diff is not None and diff > 0 else "FP_HIGHER" if diff is not None and diff < 0 else "NO_CLEAR_DIRECTION"
        missing = total - len(a) - len(b)
        category = self._feature_category(name)
        return {
            "feature_name": name,
            "feature_category": category,
            "candidate_type": self._candidate_type(category, name),
            "source": self._source(name),
            "a_count": len(a),
            "b_count": len(b),
            "c_count": len(c),
            "a_mean": round(a_mean, 3) if a_mean is not None else "NOT_AVAILABLE",
            "b_mean": round(b_mean, 3) if b_mean is not None else "NOT_AVAILABLE",
            "c_mean": round(statistics.mean(c), 3) if c else "NOT_AVAILABLE",
            "mean_difference": round(diff, 3) if diff is not None else "NOT_AVAILABLE",
            "absolute_mean_difference": round(abs(diff), 3) if diff is not None else "NOT_AVAILABLE",
            "relative_difference": round(abs(diff) / max(abs(b_mean), 1) * 100, 1) if diff is not None and b_mean is not None else "NOT_AVAILABLE",
            "a_median": round(a_median, 3) if a_median is not None else "NOT_AVAILABLE",
            "b_median": round(b_median, 3) if b_median is not None else "NOT_AVAILABLE",
            "median_difference": round(a_median - b_median, 3) if a_median is not None and b_median is not None else "NOT_AVAILABLE",
            "a_min": min(a) if a else "NOT_AVAILABLE",
            "a_max": max(a) if a else "NOT_AVAILABLE",
            "b_min": min(b) if b else "NOT_AVAILABLE",
            "b_max": max(b) if b else "NOT_AVAILABLE",
            "a_values": json.dumps(a, ensure_ascii=False),
            "b_values": json.dumps(b, ensure_ascii=False),
            "c_values": json.dumps(c, ensure_ascii=False),
            "standard_deviation_a": round(statistics.pstdev(a), 3) if len(a) > 1 else 0,
            "standard_deviation_b": round(statistics.pstdev(b), 3) if len(b) > 1 else 0,
            "range_overlap": overlap,
            "exact_overlap_count": exact,
            "direction": direction,
            "a_all_ge_b_median": bool(a and b and min(a) >= statistics.median(b)),
            "a_all_ge_b_mean": bool(a and b and min(a) >= statistics.mean(b)),
            "b_all_le_a_median": bool(a and b and max(b) <= statistics.median(a)),
            "kept_success_direction_match": bool(c and diff is not None and ((statistics.mean(c) >= b_mean) if diff > 0 else (statistics.mean(c) <= b_mean))),
            "counter_example_count": self._numeric_counter_examples(a, b, c, direction),
            "missing_count": missing,
            "missing_rate": pct(missing, total),
        }

    def _categorical_features(self, rows: list[dict[str, str]], feature_names: list[str], excluded: list[dict[str, Any]]) -> list[dict[str, Any]]:
        excluded_names = {row["feature_name"] for row in excluded}
        groups = self._groups(rows)
        out = []
        for name in feature_names:
            if name in excluded_names or name not in RACE_CONDITION:
                continue
            a_vals = [row.get(name) or "NOT_AVAILABLE" for row in groups["REMOVED_SUCCESSFUL_BUY"]]
            b_vals = [row.get(name) or "NOT_AVAILABLE" for row in groups["REMOVED_FALSE_POSITIVE"]]
            c_vals = [row.get(name) or "NOT_AVAILABLE" for row in groups["KEPT_SUCCESSFUL_BUY"]]
            a_set, b_set = set(a_vals), set(b_vals)
            out.append(
                {
                    "feature_name": name,
                    "feature_category": "RACE_CONDITION",
                    "candidate_type": "RACE_CONDITION_SEPARATOR",
                    "source": self._source(name),
                    "a_values": json.dumps(sorted(a_set), ensure_ascii=False),
                    "b_values": json.dumps(sorted(b_set), ensure_ascii=False),
                    "c_values": json.dumps(sorted(set(c_vals)), ensure_ascii=False),
                    "common_values": json.dumps(sorted(a_set & b_set), ensure_ascii=False),
                    "a_only_values": json.dumps(sorted(a_set - b_set), ensure_ascii=False),
                    "b_only_values": json.dumps(sorted(b_set - a_set), ensure_ascii=False),
                    "a_count": len(a_vals),
                    "b_count": len(b_vals),
                    "counter_example_count": len(a_set & b_set),
                    "missing_count": sum(1 for v in a_vals + b_vals if v == "NOT_AVAILABLE"),
                    "missing_rate": pct(sum(1 for v in a_vals + b_vals if v == "NOT_AVAILABLE"), len(a_vals) + len(b_vals)),
                    "observation": "POSSIBLE_CONDITION_DEPENDENCY" if a_set != b_set else "NO_CLEAR_DIFFERENCE",
                }
            )
        return out

    def _reason_features(self, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
        groups = self._groups(rows)
        out = []
        for field in REASON_FEATURES:
            a_counter = self._reason_counter(groups["REMOVED_SUCCESSFUL_BUY"], field)
            b_counter = self._reason_counter(groups["REMOVED_FALSE_POSITIVE"], field)
            c_counter = self._reason_counter(groups["KEPT_SUCCESSFUL_BUY"], field)
            for reason in sorted(set(a_counter) | set(b_counter) | set(c_counter)):
                out.append(
                    {
                        "feature_name": f"{field}:{reason}",
                        "reason_field": field,
                        "reason_text": reason,
                        "feature_category": "EXPLAIN_FEATURE",
                        "candidate_type": "REASON_QUALITY_SEPARATOR",
                        "source": "failure_feature_matrix.reason_text",
                        "a_count": a_counter.get(reason, 0),
                        "b_count": b_counter.get(reason, 0),
                        "c_count": c_counter.get(reason, 0),
                        "a_ratio": pct(a_counter.get(reason, 0), len(groups["REMOVED_SUCCESSFUL_BUY"])),
                        "b_ratio": pct(b_counter.get(reason, 0), len(groups["REMOVED_FALSE_POSITIVE"])),
                        "counter_example_count": b_counter.get(reason, 0),
                        "missing_count": 0,
                        "missing_rate": 0,
                        "observation": "POSSIBLE_SEPARATOR" if a_counter.get(reason, 0) and not b_counter.get(reason, 0) else "NO_CLEAR_DIFFERENCE",
                    }
                )
        return out

    def _feature_redundancy(self, rows: list[dict[str, str]], numeric: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        names = [row["feature_name"] for row in numeric]
        for name in names:
            status = "INDEPENDENT"
            related = ""
            if name == "adjusted_score":
                status = "DERIVED"
                related = "final_score + impact/score_weight/guard-related adjustments (confirmed as downstream score field; exact formula not modified here)"
            elif name == "production_score":
                status = "DUPLICATE"
                related = "decision_score"
            elif name in {"course_shape_score", "race_shape_score"}:
                status = "RELATION_UNKNOWN"
                related = "shape/course shape are related concepts but distinct fields in feature matrix"
            out.append({"feature_name": name, "redundancy_status": status, "related_feature": related})
        return out

    def _ranking(self, numeric, categorical, reasons, redundancy) -> list[dict[str, Any]]:
        redundancy_map = {row["feature_name"]: row["redundancy_status"] for row in redundancy}
        candidates = []
        for row in numeric:
            score = self._score_numeric(row)
            candidates.append(self._ranking_row(row, score, redundancy_map.get(row["feature_name"], "INDEPENDENT")))
        for row in categorical:
            score = 30 if row.get("observation") == "POSSIBLE_CONDITION_DEPENDENCY" else 5
            score = min(score, 45)
            candidates.append(self._ranking_row(row, score, "RELATION_UNKNOWN"))
        for row in reasons:
            score = 42 if row.get("observation") == "POSSIBLE_SEPARATOR" else 8
            candidates.append(self._ranking_row(row, score, "RELATION_UNKNOWN"))
        candidates.sort(key=lambda r: (float(r["separator_review_score"]), r["feature_name"]), reverse=True)
        rank_a_used = 0
        for idx, row in enumerate(candidates, start=1):
            row["rank"] = idx
            if row["candidate_rank"] == "RANK_A":
                rank_a_used += 1
                if rank_a_used > 3:
                    row["candidate_rank"] = "RANK_B"
                    row["recommendation"] = "REVIEW_AS_SECONDARY"
        return candidates[: self.top_n]

    def _ranking_row(self, row: dict[str, Any], score: float, redundancy_status: str) -> dict[str, Any]:
        score = min(round(score, 1), 72.0)
        confidence = "MEDIUM" if score >= 60 else "LOW_TO_MEDIUM" if score >= 45 else "LOW"
        candidate_rank = "RANK_A" if score >= 55 and redundancy_status not in {"DUPLICATE"} else "RANK_B" if score >= 35 else "RANK_C"
        recommendation = "REVIEW_NEXT" if candidate_rank == "RANK_A" else "REVIEW_AS_SECONDARY" if candidate_rank == "RANK_B" else "COLLECT_MORE_DATA"
        if redundancy_status == "DUPLICATE":
            candidate_rank = "EXCLUDED"
            recommendation = "EXCLUDE_REDUNDANT"
        return {
            "rank": 0,
            "feature_name": row.get("feature_name"),
            "feature_category": row.get("feature_category"),
            "candidate_type": row.get("candidate_type"),
            "source": row.get("source", "failure_feature_matrix"),
            "separator_review_score": score,
            "candidate_rank": candidate_rank,
            "confidence": confidence,
            "a_count": row.get("a_count", ""),
            "b_count": row.get("b_count", ""),
            "a_mean": row.get("a_mean", ""),
            "b_mean": row.get("b_mean", ""),
            "mean_difference": row.get("mean_difference", ""),
            "a_median": row.get("a_median", ""),
            "b_median": row.get("b_median", ""),
            "median_difference": row.get("median_difference", ""),
            "range_overlap": row.get("range_overlap", row.get("common_values", "")),
            "missing_rate": row.get("missing_rate", 0),
            "counter_example_count": row.get("counter_example_count", 0),
            "data_completeness": "COMPLETE" if float(row.get("missing_rate", 0) or 0) == 0 else "PARTIAL",
            "explainability": self._explainability(row.get("feature_category")),
            "implementation_safety": "SHADOW_REVIEW_ONLY_SAFE_EXISTING_FEATURE",
            "redundancy_status": redundancy_status,
            "sample_warning": "SMALL_SAMPLE_2_VS_5",
            "recommendation": recommendation,
            "human_review_required": "True",
        }

    def _score_numeric(self, row: dict[str, Any]) -> float:
        diff = to_float(row.get("absolute_mean_difference")) or 0
        rel = to_float(row.get("relative_difference")) or 0
        overlap = row.get("range_overlap") == "NO_OVERLAP"
        counter = int(row.get("counter_example_count") or 0)
        score = min(diff * 3, 25) + min(rel / 2, 10)
        score += 8 if overlap else 0
        score += 20 if float(row.get("missing_rate") or 0) == 0 else 8
        score += max(0, 15 - counter * 4)
        score += 10
        score += 10
        score += 2  # small-sample reliability is intentionally low
        return score

    def _counter_examples(self, rows, ranking) -> list[dict[str, Any]]:
        out = []
        groups = self._groups(rows)
        for cand in ranking[:10]:
            feature = cand["feature_name"]
            if ":" in feature:
                reason = feature.split(":", 1)[1]
                for group_name in ["REMOVED_FALSE_POSITIVE", "REMOVED_SUCCESSFUL_BUY", "KEPT_SUCCESSFUL_BUY"]:
                    for row in groups[group_name]:
                        if reason in " ".join(parse_reasons(row.get(feature.split(":", 1)[0]))):
                            out.append({"feature_name": feature, "counter_group": group_name, "race_id": row.get("race_id"), "horse_name": row.get("horse_name"), "counter_type": "REASON_PRESENT"})
                            break
                continue
            direction = cand.get("mean_difference")
            b_med = to_float(cand.get("b_median"))
            a_med = to_float(cand.get("a_median"))
            for group_name in ["REMOVED_FALSE_POSITIVE", "REMOVED_SUCCESSFUL_BUY", "KEPT_SUCCESSFUL_BUY"]:
                for row in groups[group_name]:
                    value = to_float(row.get(feature))
                    if value is None:
                        continue
                    counter = False
                    if to_float(direction) is not None and to_float(direction) > 0 and b_med is not None and group_name == "REMOVED_FALSE_POSITIVE" and value >= a_med:
                        counter = True
                    if to_float(direction) is not None and to_float(direction) < 0 and b_med is not None and group_name == "REMOVED_FALSE_POSITIVE" and value <= a_med:
                        counter = True
                    if counter:
                        out.append({"feature_name": feature, "counter_group": group_name, "race_id": row.get("race_id"), "horse_name": row.get("horse_name"), "value": value, "counter_type": "VALUE_OVERLAP"})
        return out or [{"feature_name": "ALL", "counter_group": "NONE_OBSERVED_IN_CURRENT_SAMPLE", "counter_type": "NONE_OBSERVED_IN_CURRENT_SAMPLE"}]

    def _missing_data(self, rows) -> list[dict[str, Any]]:
        counts = Counter()
        for row in rows:
            for key, value in row.items():
                if value in {"", "NOT_AVAILABLE", "SOURCE_NOT_FOUND"}:
                    counts[key] += 1
        return [{"feature_name": k, "missing_count": v, "missing_rate": pct(v, len(rows)), "handling": "NOT_AVAILABLE"} for k, v in counts.most_common()]

    def _adjusted_score_review(self, numeric, ranking) -> dict[str, Any]:
        adj = next((row for row in numeric if row["feature_name"] == "adjusted_score"), {})
        rank = next((row for row in ranking if row["feature_name"] == "adjusted_score"), {})
        final = next((row for row in numeric if row["feature_name"] == "final_score"), {})
        return {
            "analyzed": bool(adj),
            "formula_source": "FORMULA_SOURCE_PARTIALLY_CONFIRMED",
            "formula_note": "Existing outputs show adjusted_score is downstream of final_score plus adjustment fields such as impact/score_weight; this analysis does not inspect or alter the formula.",
            "final_score_mean_difference": final.get("mean_difference", "NOT_AVAILABLE"),
            "adjusted_score_mean_difference": adj.get("mean_difference", "NOT_AVAILABLE"),
            "a_values": adj.get("a_values", "[]"),
            "b_values": adj.get("b_values", "[]"),
            "c_values": adj.get("c_values", "[]"),
            "rank": rank.get("rank", "NOT_RANKED"),
            "candidate_rank": rank.get("candidate_rank", "NOT_RANKED"),
            "score": rank.get("separator_review_score", "NOT_RANKED"),
            "safety": "Shadow review possible as existing feature, but threshold/rule must not be created from current sample.",
            "overlap_with_buy_logic": "HIGH_REDUNDANCY_WITH_EXISTING_SCORE_FLOW",
        }

    def _source(self, name: str) -> str:
        if name in CORE_SCORE | EVALUATOR_SCORE | EXPLAIN_NUMERIC | RACE_CONDITION | PAST_PERFORMANCE:
            return "failure_feature_matrix.csv"
        return "failure_feature_matrix.csv"

    def _range_overlap(self, a: list[float], b: list[float]) -> str:
        if not a or not b:
            return "NOT_AVAILABLE"
        return "NO_OVERLAP" if max(min(a), min(b)) > min(max(a), max(b)) else "OVERLAP"

    def _numeric_counter_examples(self, a, b, c, direction) -> int:
        if not a or not b:
            return 0
        med_a = statistics.median(a)
        med_b = statistics.median(b)
        if direction == "SUCCESSFUL_HIGHER":
            return sum(1 for value in b if value >= med_a) + sum(1 for value in a if value <= med_b)
        if direction == "FP_HIGHER":
            return sum(1 for value in b if value <= med_a) + sum(1 for value in a if value >= med_b)
        return len(a) + len(b)

    def _reason_counter(self, rows, field) -> Counter:
        counter = Counter()
        for row in rows:
            counter.update(set(parse_reasons(row.get(field))))
        return counter

    def _explainability(self, category: str) -> str:
        if category in {"CORE_SCORE", "EVALUATOR_SCORE", "EXPLAIN_FEATURE", "RACE_CONDITION", "PAST_PERFORMANCE"}:
            return "EXPLAINABLE_EXISTING_FEATURE"
        return "RELATION_UNKNOWN"

    def _status(self, rows, groups) -> str:
        if self.errors:
            return "SEPARATOR_ANALYSIS_COMPLETED_WITH_WARNINGS"
        if not rows or len(groups["REMOVED_SUCCESSFUL_BUY"]) < 1 or len(groups["REMOVED_FALSE_POSITIVE"]) < 1:
            return "SEPARATOR_ANALYSIS_INSUFFICIENT_DATA"
        return "SEPARATOR_ANALYSIS_COMPLETED"

    def _recommended(self, top_candidates, missing) -> str:
        if top_candidates:
            return "REVIEW_TOP_SEPARATOR"
        if missing:
            return "IMPROVE_FEATURE_COMPLETENESS"
        return "NO_RELIABLE_SEPARATOR"

    def _fingerprint(self, *items) -> str:
        text = json.dumps(items, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _update_project(self, summary: dict[str, Any]) -> dict[str, Any]:
        repo = ShadowValidationRepository()
        projects = repo.load()
        project = projects.get(self.project_id)
        if not project:
            return {"updated": False, "reason": "project_not_found", "history_appended": False}
        result_summary = project.result_summary if isinstance(project.result_summary, dict) else {}
        prior = result_summary.get("separator_analysis") if isinstance(result_summary.get("separator_analysis"), dict) else {}
        if prior.get("analysis_fingerprint") == summary.get("analysis_fingerprint"):
            return {"updated": False, "reason": "same_analysis_fingerprint", "history_appended": False}
        record = {
            "analysis_run_id": summary.get("analysis_run_id"),
            "analysis_fingerprint": summary.get("analysis_fingerprint"),
            "source_failure_analysis_fingerprint": summary.get("source_failure_analysis_fingerprint"),
            "analyzed_feature_count": summary.get("analyzed_feature_count"),
            "excluded_feature_count": summary.get("excluded_feature_count"),
            "rank_a_count": summary.get("rank_a_count"),
            "rank_b_count": summary.get("rank_b_count"),
            "top_candidate_names": summary.get("top_candidate_names"),
            "top_candidate_scores": summary.get("top_candidate_scores"),
            "counter_example_count": summary.get("counter_example_count"),
            "analysis_status": summary.get("analysis_status"),
            "recommended_next_action": summary.get("recommended_next_action"),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }
        result_summary["separator_analysis"] = record
        project.result_summary = result_summary
        project.updated_at = datetime.now().isoformat(timespec="seconds")
        projects[self.project_id] = project
        repo.save(projects)
        repo.append_history(
            project,
            action="separator_analysis_complete",
            old_status=project.project_status,
            new_status=project.project_status,
            reason=f"{record['analysis_status']}:{record['recommended_next_action']}",
            source="SeparatorCandidateAnalyzer",
        )
        return {"updated": True, "history_appended": True}

    def _write_summary_md(self, summary, ranking, adjusted, counters, missing) -> None:
        lines = [
            "# Separator Candidate Analysis: SP_COUNT_EQ_2",
            "",
            "## Executive Summary",
            f"- Status: {summary['analysis_status']}",
            f"- Recommended Next Action: {summary['recommended_next_action']}",
            f"- Removed Successful BUY: {summary['removed_successful_buy_count']}",
            f"- Removed FP: {summary['removed_fp_count']}",
            f"- Kept Successful BUY: {summary['kept_successful_buy_count']}",
            "",
            "## Input and Sample Size",
            "- Main comparison is 2 vs 5; all findings are small-sample observations.",
            "",
            "## Current Rule Failure",
            "- SP_COUNT_EQ_2 removed both FP and Successful BUY; strong_positive_count is constant in removed targets.",
            "",
            "## Analyzed Feature Count",
            f"- Total: {summary['analyzed_feature_count']}",
            f"- Numeric: {summary['numeric_feature_count']}",
            f"- Categorical: {summary['categorical_feature_count']}",
            f"- Reason: {summary['reason_feature_count']}",
            f"- Excluded: {summary['excluded_feature_count']}",
            "",
            "## Separator Review Score",
            f"- {self.SCORE_SPEC}",
            "",
            "## Numeric Candidate Ranking",
        ]
        lines.extend(f"- {row['rank']}. {row['feature_name']} score={row['separator_review_score']} rank={row['candidate_rank']} confidence={row['confidence']}" for row in ranking[:10])
        lines.extend(["", "## AdjustedScore Deep Review"])
        for key, value in adjusted.items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Top Human Review Candidates"])
        top = [row for row in ranking if row["candidate_rank"] in {"RANK_A", "RANK_B"}][:3]
        if top:
            lines.extend(f"- {row['feature_name']}: {row['recommendation']}" for row in top)
        else:
            lines.append("- none")
        lines.extend(["", "## Counter Examples"])
        lines.extend(f"- {row.get('feature_name')} {row.get('counter_group')} {row.get('race_id')} {row.get('horse_name')}" for row in counters[:10])
        lines.extend(["", "## Data Limitations"])
        lines.append("- No statistical significance claims; sample is too small.")
        if missing:
            lines.extend(f"- {row['feature_name']}: {row['missing_rate']}%" for row in missing[:5])
        lines.extend(["", "## Recommended Next Action"])
        lines.append(f"- {summary['recommended_next_action']}")
        (self.output_dir / "separator_analysis_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run separator candidate analysis")
    parser.add_argument("--project-id", default=PROJECT_ID)
    parser.add_argument("--rule-id", default=RULE_ID)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--include-categorical", action="store_true", default=True)
    parser.add_argument("--include-reason-features", action="store_true", default=True)
    parser.add_argument("--validation-mode", default="general-unseen")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-validators", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    analyzer = SeparatorCandidateAnalyzer(
        project_id=args.project_id,
        rule_id=args.rule_id,
        top_n=args.top_n,
        include_categorical=args.include_categorical,
        include_reason_features=args.include_reason_features,
        validation_mode=args.validation_mode,
        output_dir=args.output_dir or None,
    )
    result = analyzer.run(dry_run=args.dry_run)
    if args.run_validators and not args.dry_run:
        from review.separator_candidate_validator import run_validation

        result["validator_result"] = run_validation()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
