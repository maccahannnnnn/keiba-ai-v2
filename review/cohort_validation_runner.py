"""Focused cohort validation for a fixed race-id list.

Diagnostic only.  This module runs existing production analysis for requested
complete race sets and writes isolated cohort reports.  It does not change
evaluators, BUY logic, scores, decisions, race state, knowledge, CSV schemas,
importers, existing validation reports, shadow projects, or main.py.
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

from engine.buy_v1_rc1_engine import BUYV1RC1Engine
from evaluation.race_file_locator import RaceFileLocator
from evaluation.shadow_buy_fp_filter import PROJECT_ID, ShadowBuyFalsePositiveFilter
from evaluation.target_result_adapter import TargetResultAdapter
from evaluation.target_trial_adapter import TargetTrialAdapter
from review.unseen_shadow_fp_validator import (
    _distance_band,
    _general_unseen_summary,
    _load_selected_rule,
    _lookup,
    _metrics,
    _official_map,
    _result_type,
    _to_engine_horse,
    _to_float,
    _to_int,
)


DEFAULT_COHORT_ID = "JUNE_20260613_20260614_12R"
DEFAULT_RACE_LIST = ROOT / "config" / "cohort_20260613_20260614_12races.txt"
OUT_ROOT = ROOT / "reports" / "cohort_validation"
REFERENCE_12R_COHORT_ID = "JUNE_20260613_20260614_12R"

HORSE_FIELDS = [
    "race_id",
    "race_date",
    "racecourse",
    "race_number",
    "race_name",
    "class_name",
    "surface",
    "distance",
    "track_condition",
    "horse_number",
    "horse_name",
    "ai_rank",
    "production_buy",
    "decision",
    "final_score",
    "adjusted_score",
    "decision_score",
    "confidence",
    "race_state",
    "buy_reason",
    "danger_reason",
    "strong_positive_count",
    "strong_negative_count",
    "positive_evaluator_count",
    "negative_evaluator_count",
    "finish_position",
    "is_top3",
    "is_top5",
    "result_status",
    "production_result_type",
]

RACE_FIELDS = [
    "race_id",
    "race_date",
    "racecourse",
    "race_number",
    "race_name",
    "class_name",
    "surface",
    "distance",
    "track_condition",
    "horse_count",
    "race_decision",
    "race_confidence",
    "race_state",
    "buy_count",
    "successful_buy_count",
    "false_positive_count",
    "non_buy_top3_count",
    "actual_top3",
    "buy_horses",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)


def load_race_list(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    values: list[str] = []
    warnings: list[dict[str, Any]] = []
    seen = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text in seen:
            warnings.append({"race_id": text, "warning": "duplicate_race_id_in_list", "line": line_no})
            continue
        values.append(text)
        seen.add(text)
    return values, warnings


def race_part(race_id: str, index: int) -> str:
    parts = str(race_id or "").split("_")
    return parts[index] if len(parts) > index else ""


def bool_text(value: bool) -> str:
    return "True" if value else "False"


def find_sets(race_ids: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    locator = RaceFileLocator()
    found = locator.find_complete_race_sets(ROOT / "data" / "analysis", ROOT / "data" / "results")
    analysis = {row.get("race_id"): row for row in locator.find_analysis_pairs(ROOT / "data" / "analysis").get("pairs", [])}
    results = {row.get("race_id"): row for row in locator.find_result_pairs(ROOT / "data" / "results").get("pairs", [])}
    complete = {row.get("race_id"): row for row in found.get("complete_sets", [])}
    rows: list[dict[str, Any]] = []
    sets: list[dict[str, Any]] = []
    fallback_warnings: list[str] = []
    for race_id in race_ids:
        a = analysis.get(race_id, {})
        r = results.get(race_id, {})
        c = complete.get(race_id, {})
        if a and not r:
            fallback_result = fallback_result_pair(race_id)
            if fallback_result:
                r = fallback_result
                c = {"race_id": race_id, **a, **r}
                fallback_warnings.append(f"fallback_result_pair_used:{race_id}")
        is_complete = bool(c)
        if is_complete:
            sets.append(c)
        rows.append(
            {
                "race_id": race_id,
                "race_date": race_part(race_id, 1),
                "racecourse": race_part(race_id, 2),
                "race_number": race_part(race_id, 3),
                "analysis_entry_exists": bool_text(bool(a.get("entry_path") or c.get("entry_path"))),
                "analysis_horses_exists": bool_text(bool(a.get("horses_path") or c.get("horses_path"))),
                "race_result_exists": bool_text(bool(r.get("race_result_path") or c.get("race_result_path"))),
                "horse_result_exists": bool_text(bool(r.get("horse_result_path") or c.get("horse_result_path"))),
                "is_complete": bool_text(is_complete),
                "classification": "COMPLETE" if is_complete else "INCOMPLETE",
                "entry_path": a.get("entry_path") or c.get("entry_path", ""),
                "horses_path": a.get("horses_path") or c.get("horses_path", ""),
                "race_result_path": r.get("race_result_path") or c.get("race_result_path", ""),
                "horse_result_path": r.get("horse_result_path") or c.get("horse_result_path", ""),
            }
        )
    diagnostics = {
        "requested_race_count": len(race_ids),
        "complete_race_set_count": len(sets),
        "missing_count": sum(1 for row in rows if row["is_complete"] != "True"),
        "duplicate_count": len(found.get("duplicates", [])),
        "unexpected_race_count": 0,
        "locator_warnings": list(found.get("warnings", [])) + fallback_warnings,
    }
    return rows, sets, diagnostics


def fallback_result_pair(race_id: str) -> dict[str, Any]:
    """Find a result pair for a requested cohort race when one filename has a typo.

    This is cohort-local discovery only. It does not rename files or change the
    global RaceFileLocator behavior.
    """

    parts = str(race_id or "").split("_")
    if len(parts) < 4:
        return {}
    date, course, race_number = parts[1], parts[2], parts[3]
    race_path = ROOT / "data" / "results" / f"race_{date}_{course}_{race_number}_result.csv"
    if not race_path.exists():
        return {}
    race_digits = "".join(ch for ch in race_number if ch.isdigit())
    candidates = sorted((ROOT / "data" / "results").glob(f"horse_{date}_{course}_*R_result.csv"))
    exact = ROOT / "data" / "results" / f"horse_{date}_{course}_{race_number}_result.csv"
    if exact.exists():
        return {"race_id": race_id, "race_result_path": str(race_path), "horse_result_path": str(exact)}
    for path in candidates:
        name = path.name
        token = name.replace(f"horse_{date}_{course}_", "").replace("_result.csv", "")
        digits = "".join(ch for ch in token if ch.isdigit())
        if digits.lstrip("0") == race_digits.lstrip("0"):
            return {"race_id": race_id, "race_result_path": str(race_path), "horse_result_path": str(path)}
        if digits.endswith(race_digits) and len(digits) <= len(race_digits) + 1:
            return {"race_id": race_id, "race_result_path": str(race_path), "horse_result_path": str(path)}
    return {}


def collect_horses(sets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    adapter = TargetTrialAdapter()
    result_adapter = TargetResultAdapter()
    rc1_engine = BUYV1RC1Engine(enabled=True)
    rows: list[dict[str, Any]] = []
    race_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for race_set in sorted(sets, key=lambda row: row.get("race_id", "")):
        race_id = race_set.get("race_id", "")
        try:
            analysis = adapter.run(race_set.get("entry_path"), horse_data_csv_path=race_set.get("horses_path"))
            official = result_adapter.load(race_set.get("race_result_path"), race_set.get("horse_result_path"))
            official_rows = [row for row in official.get("horse_results", []) if isinstance(row, dict)]
            official_by_name = _official_map(official_rows)
            ranked = sorted(
                [row for row in analysis.get("ranked_results", []) if isinstance(row, dict)],
                key=lambda row: (_to_float(row.get("adjusted_score"), 0.0) or 0.0, _to_int(row.get("horse_number"), 0) or 0),
                reverse=True,
            )
            engine_horses = [_to_engine_horse(horse, rank, race_id) for rank, horse in enumerate(ranked, start=1)]
            rc1 = rc1_engine.evaluate(
                race_output={
                    "race_id": race_id,
                    "race_decision": analysis.get("race_decision"),
                    "race_confidence": analysis.get("race_confidence"),
                },
                horses=engine_horses,
            )
            rc1_records = {row.get("horse_name"): row for row in rc1.get("horse_records", [])}
            race_result = official.get("race_result") or {}
            race_horse_rows = []
            for rank, horse in enumerate(ranked, start=1):
                result = _lookup(official_by_name, horse.get("horse_name"))
                rc1_record = rc1_records.get(horse.get("horse_name"), {})
                profile = rc1_record.get("consensus_profile", {}) if isinstance(rc1_record.get("consensus_profile"), dict) else {}
                finish = _to_int(result.get("finish_position"), 99) or 99
                production_buy = (rc1_record.get("rc1_decision") or horse.get("decision")) == "BUY"
                is_top3 = finish <= 3
                is_top5 = finish <= 5
                row = {
                    "race_id": race_id,
                    "race_date": race_part(race_id, 1),
                    "racecourse": race_result.get("racecourse") or race_part(race_id, 2),
                    "race_number": race_result.get("race_number") or race_part(race_id, 3),
                    "race_name": race_result.get("race_name") or "NOT_AVAILABLE",
                    "class_name": race_result.get("race_class") or analysis.get("race_class") or "NOT_AVAILABLE",
                    "surface": race_result.get("surface") or analysis.get("surface") or "NOT_AVAILABLE",
                    "distance": race_result.get("distance") or analysis.get("distance") or "",
                    "track_condition": race_result.get("track_condition") or analysis.get("track_condition") or "NOT_AVAILABLE",
                    "horse_number": horse.get("horse_number") or result.get("horse_number"),
                    "horse_name": horse.get("horse_name"),
                    "ai_rank": rank,
                    "production_buy": production_buy,
                    "decision": rc1_record.get("rc1_decision") or horse.get("decision"),
                    "final_score": horse.get("final_score"),
                    "adjusted_score": horse.get("adjusted_score"),
                    "decision_score": horse.get("decision_score"),
                    "confidence": horse.get("confidence_level") or horse.get("confidence"),
                    "race_state": rc1.get("race_state", ""),
                    "buy_reason": rc1_record.get("rc1_reason") or horse.get("decision_reason") or "",
                    "danger_reason": "; ".join(str(x) for x in horse.get("final_risks") or horse.get("risk_factors") or []),
                    "strong_positive_count": profile.get("strong_positive_count", ""),
                    "strong_negative_count": profile.get("strong_negative_count", ""),
                    "positive_evaluator_count": profile.get("positive_evaluator_count", ""),
                    "negative_evaluator_count": profile.get("negative_evaluator_count", ""),
                    "finish_position": finish,
                    "is_top3": is_top3,
                    "is_top5": is_top5,
                    "result_status": "LOADED" if result else "RESULT_NOT_MATCHED",
                    "production_result_type": _result_type(production_buy, is_top3),
                }
                rows.append(row)
                race_horse_rows.append(row)
            buy_rows = [row for row in race_horse_rows if row.get("production_buy")]
            top3_names = [row.get("horse_name", "") for row in sorted(race_horse_rows, key=lambda x: _to_int(x.get("finish_position"), 99) or 99) if row.get("is_top3")]
            race_rows.append(
                {
                    "race_id": race_id,
                    "race_date": race_part(race_id, 1),
                    "racecourse": race_result.get("racecourse") or race_part(race_id, 2),
                    "race_number": race_result.get("race_number") or race_part(race_id, 3),
                    "race_name": race_result.get("race_name") or "NOT_AVAILABLE",
                    "class_name": race_result.get("race_class") or "NOT_AVAILABLE",
                    "surface": race_result.get("surface") or "NOT_AVAILABLE",
                    "distance": race_result.get("distance") or "",
                    "track_condition": race_result.get("track_condition") or "NOT_AVAILABLE",
                    "horse_count": len(race_horse_rows),
                    "race_decision": analysis.get("race_decision"),
                    "race_confidence": analysis.get("race_confidence"),
                    "race_state": rc1.get("race_state", ""),
                    "buy_count": len(buy_rows),
                    "successful_buy_count": sum(1 for row in buy_rows if row.get("is_top3")),
                    "false_positive_count": sum(1 for row in buy_rows if not row.get("is_top3")),
                    "non_buy_top3_count": sum(1 for row in race_horse_rows if row.get("is_top3") and not row.get("production_buy")),
                    "actual_top3": "; ".join(top3_names),
                    "buy_horses": "; ".join(row.get("horse_name", "") for row in buy_rows),
                }
            )
        except Exception as exc:
            errors.append({"race_id": race_id, "error": str(exc)})
    return rows, race_rows, errors


def build_buy_monitoring(race_rows: list[dict[str, Any]], horse_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "race_id": row.get("race_id"),
            "race_state": row.get("race_state"),
            "buy_count": row.get("buy_count"),
            "buy_horses": row.get("buy_horses"),
            "successful_buy_count": row.get("successful_buy_count"),
            "false_positive_count": row.get("false_positive_count"),
            "buy_place_rate": round((_to_int(row.get("successful_buy_count"), 0) or 0) / (_to_int(row.get("buy_count"), 0) or 1) * 100, 1)
            if (_to_int(row.get("buy_count"), 0) or 0)
            else 0.0,
            "classification": "BUY_SUCCESS"
            if (_to_int(row.get("successful_buy_count"), 0) or 0)
            else "BUY_FAILURE"
            if (_to_int(row.get("buy_count"), 0) or 0)
            else "BUY_NONE",
        }
        for row in race_rows
    ]


def summarize_conditions(horse_rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in horse_rows:
        grouped[str(row.get(field) or "NOT_AVAILABLE")].append(row)
    output = []
    for key, rows in sorted(grouped.items()):
        buy = [row for row in rows if row.get("production_buy")]
        output.append(
            {
                field: key,
                "horse_count": len(rows),
                "buy_count": len(buy),
                "successful_buy_count": sum(1 for row in buy if row.get("is_top3")),
                "false_positive_count": sum(1 for row in buy if not row.get("is_top3")),
                "non_buy_top3_count": sum(1 for row in rows if row.get("is_top3") and not row.get("production_buy")),
                "note": "SMALL_SAMPLE" if len(rows) < 20 else "OBSERVED_RESULT",
            }
        )
    return output


def build_shadow_diagnostic(horse_rows: list[dict[str, Any]], out_dir: Path, run_dir: Path) -> dict[str, Any]:
    selected_rule = _load_selected_rule()
    shadow_filter = ShadowBuyFalsePositiveFilter(enabled=True, selected_rule=selected_rule)
    shadow_rows = []
    for row in horse_rows:
        base = {
            **row,
            "production_buy": row.get("production_buy"),
            "strong_positive_count": row.get("strong_positive_count"),
        }
        annotated = shadow_filter.annotate(base)
        shadow_buy = bool(annotated.get("shadow_buy_rc1_v1"))
        production_buy = bool(row.get("production_buy"))
        shadow_rows.append(
            {
                **annotated,
                "shadow_buy": shadow_buy,
                "removed_by_shadow": production_buy and not shadow_buy,
                "removed_result_type": "REMOVED_SUCCESSFUL_BUY"
                if production_buy and not shadow_buy and row.get("is_top3")
                else "REMOVED_FALSE_POSITIVE"
                if production_buy and not shadow_buy
                else "",
                "newly_added_by_shadow": (not production_buy) and shadow_buy,
            }
        )
    production = _metrics(shadow_rows, "production_buy")
    shadow = _metrics(shadow_rows, "shadow_buy")
    removed = [row for row in shadow_rows if row.get("removed_by_shadow")]
    kept = [row for row in shadow_rows if row.get("production_buy") and row.get("shadow_buy")]
    removed_fp = sum(1 for row in removed if not row.get("is_top3"))
    removed_success = sum(1 for row in removed if row.get("is_top3"))
    if not removed or len(removed) < 3:
        diagnostic = "INSUFFICIENT_SAMPLE"
    elif removed_success and removed_fp:
        diagnostic = "MIXED_RESULT"
    elif removed_success:
        diagnostic = "SUPPORTS_REVERT"
    elif removed_fp:
        diagnostic = "ADDITIONAL_SUPPORT_ONLY"
    else:
        diagnostic = "INSUFFICIENT_SAMPLE"
    summary = {
        "project_id": PROJECT_ID,
        "rule_id": selected_rule.get("rule_id", "SP_COUNT_EQ_2"),
        "rule_matched_count": sum(
            1
            for row in shadow_rows
            if row.get("shadow_buy_fp_filter_v1") or row.get("shadow_fp_filter_applied")
        ),
        "removed_buy": len(removed),
        "removed_successful_buy": removed_success,
        "removed_fp": removed_fp,
        "kept_successful_buy": sum(1 for row in kept if row.get("is_top3")),
        "new_buy": sum(1 for row in shadow_rows if row.get("newly_added_by_shadow")),
        "production_metrics": production,
        "shadow_metrics": shadow,
        "place_rate_delta": shadow.get("buy_top3_rate", 0) - production.get("buy_top3_rate", 0),
        "additional_diagnostic": diagnostic,
        "project_status_changed": False,
        "new_shadow_rule_created": False,
    }
    shadow_dir = out_dir / "shadow_diagnostic"
    shadow_dir.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(list(HORSE_FIELDS) + ["shadow_buy", "removed_by_shadow", "removed_result_type", "newly_added_by_shadow", "shadow_buy_fp_filter_v1", "shadow_fp_filter_applied", "shadow_fp_filter_rule_id"]))
    write_csv(shadow_dir / "shadow_comparison.csv", shadow_rows, fields)
    write_csv(shadow_dir / "shadow_removed_buy.csv", removed, fields)
    write_csv(shadow_dir / "shadow_kept_buy.csv", kept, fields)
    write_json(shadow_dir / "shadow_summary.json", summary)
    (shadow_dir / "shadow_summary.md").write_text(shadow_summary_md(summary, removed, kept), encoding="utf-8")
    run_shadow_dir = run_dir / "shadow_diagnostic"
    run_shadow_dir.mkdir(parents=True, exist_ok=True)
    for name in ["shadow_comparison.csv", "shadow_removed_buy.csv", "shadow_kept_buy.csv", "shadow_summary.json", "shadow_summary.md"]:
        source = shadow_dir / name
        target = run_shadow_dir / name
        if source.suffix == ".json":
            write_json(target, json.loads(source.read_text(encoding="utf-8")))
        else:
            target.write_text(source.read_text(encoding="utf-8-sig" if source.suffix == ".csv" else "utf-8"), encoding="utf-8")
    return summary


def shadow_summary_md(summary: dict[str, Any], removed: list[dict[str, Any]], kept: list[dict[str, Any]]) -> str:
    lines = [
        "# SP_COUNT_EQ_2 Additional Diagnostic",
        "",
        f"- Project: {summary.get('project_id')}",
        f"- Rule: {summary.get('rule_id')}",
        f"- Rule matched: {summary.get('rule_matched_count')}",
        f"- Removed BUY: {summary.get('removed_buy')}",
        f"- Removed Successful BUY: {summary.get('removed_successful_buy')}",
        f"- Removed FP: {summary.get('removed_fp')}",
        f"- Kept Successful BUY: {summary.get('kept_successful_buy')}",
        f"- Additional Diagnostic: {summary.get('additional_diagnostic')}",
        "",
        "## Removed BUY",
    ]
    lines.extend(
        f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')} type={row.get('removed_result_type')}"
        for row in removed
    )
    if not removed:
        lines.append("- none")
    lines.append("")
    lines.append("## Kept BUY")
    lines.extend(
        f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')}"
        for row in kept
    )
    if not kept:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_race_reports(out_dir: Path, race_rows: list[dict[str, Any]], horse_rows: list[dict[str, Any]]) -> None:
    race_dir = out_dir / "races"
    race_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in horse_rows:
        grouped[row.get("race_id", "")].append(row)
    race_map = {row.get("race_id"): row for row in race_rows}
    for race_id, rows in sorted(grouped.items()):
        race = race_map.get(race_id, {})
        buy_rows = [row for row in rows if row.get("production_buy")]
        non_buy_top3 = [row for row in rows if row.get("is_top3") and not row.get("production_buy")]
        lines = [
            f"# {race_id}",
            "",
            "## 1. Race Information",
            f"- Race Name: {race.get('race_name')}",
            f"- Class: {race.get('class_name')}",
            f"- Course: {race.get('racecourse')} {race.get('surface')} {race.get('distance')}m {race.get('track_condition')}",
            "",
            "## 2. Input Validation",
            "- Complete Race Set: True",
            "",
            "## 3. Race Decision",
            f"- RaceDecision: {race.get('race_decision')}",
            f"- Confidence: {race.get('race_confidence')}",
            f"- RaceState: {race.get('race_state')}",
            "",
            "## 4. Production BUY",
        ]
        lines.extend(f"- {row.get('horse_name')} finish={row.get('finish_position')} rank={row.get('ai_rank')}" for row in buy_rows)
        if not buy_rows:
            lines.append("- BUYなし")
        lines.extend(["", "## 5. Actual Top3"])
        lines.extend(f"- {row.get('horse_name')} decision={row.get('decision')} rank={row.get('ai_rank')}" for row in sorted(rows, key=lambda r: _to_int(r.get("finish_position"), 99) or 99) if row.get("is_top3"))
        lines.extend(["", "## 6. BUY Result"])
        lines.append(f"- Successful BUY: {race.get('successful_buy_count')}")
        lines.append(f"- False Positive: {race.get('false_positive_count')}")
        lines.extend(["", "## 7. NON_BUY_TOP3"])
        lines.extend(f"- {row.get('horse_name')} finish={row.get('finish_position')} decision={row.get('decision')}" for row in non_buy_top3)
        if not non_buy_top3:
            lines.append("- none")
        lines.extend(["", "## 8. Explain Review"])
        for row in sorted(rows, key=lambda r: _to_int(r.get("ai_rank"), 99) or 99)[:5]:
            lines.append(f"- {row.get('ai_rank')}. {row.get('horse_name')}: {row.get('decision')} / {row.get('buy_reason')}")
        lines.extend(["", "## 9. Observed Error Type"])
        if race.get("false_positive_count"):
            lines.append("- FALSE_POSITIVE observed")
        if race.get("non_buy_top3_count"):
            lines.append("- NON_BUY_TOP3 observed")
        if not race.get("false_positive_count") and not race.get("non_buy_top3_count"):
            lines.append("- NO_MAJOR_BUY_REVIEW_ISSUE")
        lines.extend(["", "## 10. Improvement Candidate Material", "- REVIEW_REQUIRED where FN/FP exists.", "", "## 11. Human Review Notes", "- Add human notes after cohort review."])
        (race_dir / f"{race_id}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_summary(
    cohort_id: str,
    race_ids: list[str],
    inventory_diag: dict[str, Any],
    horse_rows: list[dict[str, Any]],
    race_rows: list[dict[str, Any]],
    shadow_summary: dict[str, Any],
    cohort_comparison: dict[str, Any],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    fingerprint: str,
) -> dict[str, Any]:
    production = _metrics([{**row, "production_buy": row.get("production_buy")} for row in horse_rows], "production_buy")
    race_state_counts = Counter(str(row.get("race_state") or "NOT_AVAILABLE") for row in race_rows)
    play_count = sum(count for state, count in race_state_counts.items() if state.startswith("PLAY"))
    skip_count = race_state_counts.get("SKIP", 0)
    buy_zero = sum(1 for row in race_rows if (_to_int(row.get("buy_count"), 0) or 0) == 0)
    summary = {
        "cohort_id": cohort_id,
        "cohort_fingerprint": fingerprint,
        "requested_race_ids": race_ids,
        "requested_race_count": len(race_ids),
        "validated_race_count": len(race_rows),
        "complete_race_set_count": inventory_diag.get("complete_race_set_count", 0),
        "missing_count": inventory_diag.get("missing_count", 0),
        "duplicate_count": inventory_diag.get("duplicate_count", 0),
        "unexpected_race_count": inventory_diag.get("unexpected_race_count", 0),
        "horse_count": len(horse_rows),
        "result_join_success_count": sum(1 for row in horse_rows if row.get("result_status") == "LOADED"),
        "play_count": play_count,
        "skip_count": skip_count,
        "buy_race_count": len([row for row in race_rows if (_to_int(row.get("buy_count"), 0) or 0) > 0]),
        "buy_none_race_count": buy_zero,
        "production_buy": production.get("buy", 0),
        "successful_buy": production.get("successful_buy", production.get("buy_top3", 0)),
        "false_positive": production.get("fp", 0),
        "buy_win_count": sum(1 for row in horse_rows if row.get("production_buy") and (_to_int(row.get("finish_position"), 99) or 99) == 1),
        "buy_place_rate": production.get("buy_top3_rate", 0),
        "non_buy_top3": production.get("fn", 0),
        "race_state_counts": dict(race_state_counts),
        "shadow_diagnostic": shadow_summary,
        "cohort_comparison": cohort_comparison,
        "failure_analysis_status": failure_separator_status(shadow_summary).get("failure_analysis_status"),
        "separator_analysis_status": failure_separator_status(shadow_summary).get("separator_analysis_status"),
        "production_buy_diff": 0,
        "score_diff": 0,
        "decision_diff": 0,
        "race_state_diff": 0,
        "candidate_registration_count": 0,
        "shadow_project_created_count": 0,
        "history_diff": 0,
        "warning_count": len(warnings),
        "error_count": len(errors),
        "recommended_next_action": "ACCEPT_COHORT_AND_MERGE_LATER" if not errors and not inventory_diag.get("missing_count") else "REVIEW_COHORT_ERRORS",
        "status": "COHORT_VALIDATION_COMPLETED" if not errors and not inventory_diag.get("missing_count") else "COHORT_VALIDATION_REVIEW_REQUIRED",
    }
    return summary


def failure_separator_status(shadow_summary: dict[str, Any]) -> dict[str, str]:
    removed_success = int(shadow_summary.get("removed_successful_buy") or 0)
    removed_fp = int(shadow_summary.get("removed_fp") or 0)
    enough = removed_success >= 2 and removed_fp >= 5
    status = "READY_FOR_COHORT_ANALYSIS" if enough else "INSUFFICIENT_SAMPLE"
    return {"failure_analysis_status": status, "separator_analysis_status": status}


def comparison_metric(summary: dict[str, Any]) -> dict[str, Any]:
    races = int(summary.get("validated_race_count") or summary.get("requested_race_count") or 0)
    buy_none = int(summary.get("buy_none_race_count") or 0)
    return {
        "target_race_count": races,
        "horse_count": int(summary.get("horse_count") or 0),
        "play_count": int(summary.get("play_count") or 0),
        "skip_count": int(summary.get("skip_count") or 0),
        "buy_count": int(summary.get("production_buy") or 0),
        "successful_buy": int(summary.get("successful_buy") or 0),
        "false_positive": int(summary.get("false_positive") or 0),
        "buy_place_rate": float(summary.get("buy_place_rate") or 0),
        "buy_none_race_rate": round(buy_none / races * 100.0, 1) if races else 0.0,
        "non_buy_top3": int(summary.get("non_buy_top3") or 0),
    }


def build_cohort_comparison(current_summary_base: dict[str, Any]) -> dict[str, Any]:
    reference_path = OUT_ROOT / REFERENCE_12R_COHORT_ID / "cohort_summary.json"
    reference = {}
    if reference_path.exists():
        try:
            reference = json.loads(reference_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            reference = {}
    current = comparison_metric(current_summary_base)
    ref = comparison_metric(reference) if reference else {}
    diff = {
        key: round(float(current.get(key, 0)) - float(ref.get(key, 0)), 3)
        for key in current
        if key in ref
    }
    return {
        "reference_cohort_id": REFERENCE_12R_COHORT_ID,
        "reference_available": bool(reference),
        "reference": ref,
        "current": current,
        "diff_current_minus_reference": diff,
    }


def fingerprint_payload(cohort_id: str, race_ids: list[str], horse_rows: list[dict[str, Any]], race_rows: list[dict[str, Any]]) -> str:
    payload = {
        "cohort_id": cohort_id,
        "race_ids": sorted(race_ids),
        "horse_rows": sorted(
            [
                {
                    "race_id": row.get("race_id"),
                    "horse_name": row.get("horse_name"),
                    "decision": row.get("decision"),
                    "final_score": row.get("final_score"),
                    "adjusted_score": row.get("adjusted_score"),
                    "finish_position": row.get("finish_position"),
                }
                for row in horse_rows
            ],
            key=lambda row: (row.get("race_id") or "", row.get("horse_name") or ""),
        ),
        "race_rows": sorted(race_rows, key=lambda row: row.get("race_id") or ""),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def summary_md(summary: dict[str, Any], race_rows: list[dict[str, Any]], horse_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# June Cohort Validation v1.0",
        "",
        "## 1. Executive Summary",
        f"- Status: {summary.get('status')}",
        f"- Recommended Next Action: {summary.get('recommended_next_action')}",
        f"- Cohort ID: {summary.get('cohort_id')}",
        f"- Fingerprint: {summary.get('cohort_fingerprint')}",
        "",
        "## 2. Cohort Definition",
    ]
    lines.extend(f"- {race_id}" for race_id in summary.get("requested_race_ids", []))
    lines.extend(
        [
            "",
            "## 3. File Validation",
            f"- Requested: {summary.get('requested_race_count')}",
            f"- Complete Race Sets: {summary.get('complete_race_set_count')}",
            f"- Missing: {summary.get('missing_count')}",
            f"- Duplicate: {summary.get('duplicate_count')}",
            f"- Unexpected Race: {summary.get('unexpected_race_count')}",
            "",
            "## 4. Complete Race Sets",
        ]
    )
    lines.extend(f"- {row.get('race_id')}" for row in race_rows)
    lines.extend(
        [
            "",
            "## 5. Race Inventory",
            f"- Validated Races: {summary.get('validated_race_count')}",
            f"- Horses: {summary.get('horse_count')}",
            "",
            "## 6. Production Race Decisions",
            f"- PLAY: {summary.get('play_count')}",
            f"- SKIP: {summary.get('skip_count')}",
            f"- RaceState: {summary.get('race_state_counts')}",
            "",
            "## 7. Production BUY Results",
            f"- BUY: {summary.get('production_buy')}",
            f"- Successful BUY: {summary.get('successful_buy')}",
            f"- False Positive: {summary.get('false_positive')}",
            f"- BUY Place Rate: {summary.get('buy_place_rate')}%",
            "",
            "## 8. Successful BUY",
        ]
    )
    for row in horse_rows:
        if row.get("production_buy") and row.get("is_top3"):
            lines.append(f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')}")
    lines.extend(["", "## 9. False Positive"])
    for row in horse_rows:
        if row.get("production_buy") and not row.get("is_top3"):
            lines.append(f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')}")
    lines.extend(
        [
            "",
            "## 10. BUY-None Races",
        ]
    )
    for row in race_rows:
        if (_to_int(row.get("buy_count"), 0) or 0) == 0:
            lines.append(f"- {row.get('race_id')}")
    lines.extend(["", "## 11. NON-BUY Top3"])
    for row in horse_rows:
        if row.get("is_top3") and not row.get("production_buy"):
            lines.append(f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')} decision={row.get('decision')}")
    lines.extend(
        [
            "",
            "## 12. Course / Surface / Distance / Class Summary",
            "- See condition CSV outputs.",
            "",
            "## 13. Takara-zuka Kinen Review",
        ]
    )
    takara = [row for row in race_rows if row.get("race_id") == "race_20260614_hanshin_11R"]
    if takara:
        row = takara[0]
        lines.extend(
            [
                f"- Race Name: {row.get('race_name')}",
                f"- Class: {row.get('class_name')}",
                f"- RaceDecision: {row.get('race_decision')}",
                f"- BUY: {row.get('buy_count')}",
                f"- Actual Top3: {row.get('actual_top3')}",
            ]
        )
    else:
        lines.append("- NOT_AVAILABLE")
    shadow = summary.get("shadow_diagnostic", {})
    lines.extend(
        [
            "",
            "## 14. SP_COUNT_EQ_2 Additional Diagnostic",
            f"- Rule matched: {shadow.get('rule_matched_count')}",
            f"- Removed BUY: {shadow.get('removed_buy')}",
            f"- Removed Successful BUY: {shadow.get('removed_successful_buy')}",
            f"- Removed FP: {shadow.get('removed_fp')}",
            f"- Diagnostic: {shadow.get('additional_diagnostic')}",
            "",
            "## 14.5 12R vs Current Cohort Comparison",
        ]
    )
    comparison = summary.get("cohort_comparison", {})
    if comparison.get("reference_available"):
        ref = comparison.get("reference", {})
        cur = comparison.get("current", {})
        diff = comparison.get("diff_current_minus_reference", {})
        for key in ["target_race_count", "horse_count", "play_count", "skip_count", "buy_count", "successful_buy", "false_positive", "buy_place_rate", "buy_none_race_rate", "non_buy_top3"]:
            lines.append(f"- {key}: 12R={ref.get(key)} current={cur.get(key)} diff={diff.get(key)}")
    else:
        lines.append("- Reference 12R cohort not available.")
    lines.extend(
        [
            "",
            "## 15. Observed Issues",
            f"- Warnings: {summary.get('warning_count')}",
            f"- Errors: {summary.get('error_count')}",
            "",
            "## 16. Improvement Candidate Material",
            "- Diagnostic material only. No candidate was registered automatically.",
            "",
            "## 17. Data Limitations",
            f"- SMALL_SAMPLE: {summary.get('requested_race_count')} race focused cohort only.",
            "- Existing General / Focused / Failure / Separator reports were not overwritten.",
            "",
            "## 18. Recommended Next Action",
            f"- {summary.get('recommended_next_action')}",
        ]
    )
    return "\n".join(lines) + "\n"


def run_cohort_validation(
    race_list_file: str | Path = DEFAULT_RACE_LIST,
    cohort_id: str = DEFAULT_COHORT_ID,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    run_validators: bool = False,
) -> dict[str, Any]:
    out_dir = Path(output_dir) if output_dir else OUT_ROOT / cohort_id
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    run_id = f"COHORT_VALIDATION_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = out_dir / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    race_ids, list_warnings = load_race_list(Path(race_list_file))
    inventory_rows, complete_sets, inventory_diag = find_sets(race_ids)
    warnings = list(list_warnings)
    warnings.extend({"race_id": "GLOBAL", "warning": text} for text in inventory_diag.get("locator_warnings", []))
    errors: list[dict[str, Any]] = []
    if inventory_diag.get("missing_count"):
        errors.append({"race_id": "GLOBAL", "error": "cohort_has_incomplete_race_sets"})
    horse_rows: list[dict[str, Any]] = []
    race_rows: list[dict[str, Any]] = []
    shadow_summary: dict[str, Any] = {}
    if not dry_run and not errors:
        horse_rows, race_rows, run_errors = collect_horses(complete_sets)
        errors.extend(run_errors)
        write_race_reports(out_dir, race_rows, horse_rows)
        shadow_summary = build_shadow_diagnostic(horse_rows, out_dir, run_dir)
    fp = fingerprint_payload(cohort_id, race_ids, horse_rows, race_rows)
    summary_base = build_summary(cohort_id, race_ids, inventory_diag, horse_rows, race_rows, shadow_summary, {}, warnings, errors, fp)
    cohort_comparison = build_cohort_comparison(summary_base)
    summary = build_summary(cohort_id, race_ids, inventory_diag, horse_rows, race_rows, shadow_summary, cohort_comparison, warnings, errors, fp)
    if dry_run:
        summary["status"] = "DRY_RUN_COMPLETE" if not errors else "DRY_RUN_REVIEW_REQUIRED"
        summary["recommended_next_action"] = "RUN_COHORT_VALIDATION" if not errors else "REVIEW_COHORT_ERRORS"
    write_csv(out_dir / "cohort_inventory.csv", inventory_rows)
    write_csv(out_dir / "complete_race_sets.csv", [row for row in inventory_rows if row.get("is_complete") == "True"])
    write_csv(out_dir / "missing_files.csv", [row for row in inventory_rows if row.get("is_complete") != "True"])
    write_csv(out_dir / "duplicate_files.csv", [])
    write_csv(out_dir / "horse_analysis_results.csv", horse_rows, HORSE_FIELDS)
    write_csv(out_dir / "race_analysis_results.csv", race_rows, RACE_FIELDS)
    write_csv(out_dir / "buy_monitoring.csv", build_buy_monitoring(race_rows, horse_rows))
    write_csv(out_dir / "non_buy_top3.csv", [row for row in horse_rows if row.get("is_top3") and not row.get("production_buy")], HORSE_FIELDS)
    write_csv(out_dir / "race_condition_summary.csv", summarize_conditions(horse_rows, "surface") + summarize_conditions(horse_rows, "track_condition"))
    write_csv(out_dir / "course_summary.csv", summarize_conditions(horse_rows, "racecourse"))
    write_csv(out_dir / "class_summary.csv", summarize_conditions(horse_rows, "class_name"))
    write_csv(out_dir / "validation_errors.csv", errors)
    write_csv(out_dir / "validation_warnings.csv", warnings)
    comparison = summary.get("cohort_comparison", {})
    comparison_rows = []
    if comparison:
        for label, values in [("reference_12R", comparison.get("reference", {})), ("current", comparison.get("current", {})), ("diff_current_minus_reference", comparison.get("diff_current_minus_reference", {}))]:
            row = {"comparison_row": label}
            row.update(values)
            comparison_rows.append(row)
    write_csv(out_dir / "cohort_comparison_12r_vs_current.csv", comparison_rows)
    write_json(out_dir / "cohort_summary.json", summary)
    (out_dir / "cohort_summary.md").write_text(summary_md(summary, race_rows, horse_rows), encoding="utf-8")
    # Keep a run snapshot for repeatability checks.
    for path in [
        "cohort_inventory.csv",
        "complete_race_sets.csv",
        "missing_files.csv",
        "horse_analysis_results.csv",
        "race_analysis_results.csv",
        "buy_monitoring.csv",
        "non_buy_top3.csv",
        "race_condition_summary.csv",
        "course_summary.csv",
        "class_summary.csv",
        "validation_errors.csv",
        "validation_warnings.csv",
        "cohort_summary.json",
        "cohort_summary.md",
    ]:
        source = out_dir / path
        target = run_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    validator_result = {}
    if run_validators and not dry_run:
        from review.cohort_validation_validator import run_validation

        validator_result = run_validation(cohort_id=cohort_id, output_dir=out_dir)
        summary["validator_result"] = validator_result
        write_json(out_dir / "cohort_summary.json", summary)
        write_json(run_dir / "cohort_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KeibaAI focused cohort validation")
    parser.add_argument("--race-list-file", default=str(DEFAULT_RACE_LIST))
    parser.add_argument("--cohort-id", default=DEFAULT_COHORT_ID)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--isolated-report", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-validators", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    return run_cohort_validation(
        race_list_file=args.race_list_file,
        cohort_id=args.cohort_id,
        output_dir=args.output_dir or None,
        dry_run=args.dry_run,
        run_validators=args.run_validators,
    )


if __name__ == "__main__":
    main()
