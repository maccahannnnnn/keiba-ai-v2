"""Unseen validation for the Shadow BUY FP Filter.

This validator keeps the existing 40-race development baseline separate from
new complete race sets.  It applies the already-selected shadow-only rule to
RC1 BUY output and writes diagnostic reports without changing production BUY,
scores, decisions, evaluators, thresholds, knowledge, CSV inputs, or main.py.
"""

from __future__ import annotations

import csv
import hashlib
import json
import argparse
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
from learning.shadow_validation_repository import ShadowValidationRepository


DEV_DIR = ROOT / "reports" / "buy_v1_rc1_validation"
OUT_DIR = ROOT / "reports" / "shadow_buy_fp_filter" / "unseen_validation"
FOCUSED_OUT_DIR = ROOT / "reports" / "shadow_buy_fp_filter" / "focused_unseen_validation"
SHADOW_DIR = ROOT / "reports" / "shadow_buy_fp_filter"

UNSEEN_RACE_FIELDS = [
    "race_id",
    "race_date",
    "racecourse",
    "race_number",
    "analysis_complete",
    "result_complete",
    "in_development_baseline",
    "included_in_unseen_validation",
    "classification",
    "classification_reason",
    "entry_path",
    "horses_path",
    "race_result_path",
    "horse_result_path",
]

FOCUSED_RACE_FIELDS = [
    "race_id",
    "race_date",
    "racecourse",
    "race_number",
    "requested_as_focused",
    "analysis_entry_exists",
    "analysis_horses_exists",
    "race_result_exists",
    "horse_result_exists",
    "is_complete",
    "in_development_baseline",
    "in_general_unseen",
    "included_in_focused_validation",
    "classification",
    "classification_reason",
    "entry_path",
    "horses_path",
    "race_result_path",
    "horse_result_path",
]

HORSE_FIELDS = [
    "race_id",
    "horse_number",
    "horse_name",
    "finish_position",
    "is_top3",
    "is_top5",
    "production_buy",
    "shadow_buy",
    "strong_positive_count",
    "removed_by_shadow",
    "removed_result_type",
    "newly_added_by_shadow",
    "production_result_type",
    "shadow_result_type",
    "filter_rule_id",
    "validation_group",
    "ai_rank",
    "final_score",
    "adjusted_score",
    "decision_score",
    "racecourse",
    "surface",
    "distance",
    "distance_band",
    "race_class",
    "track_condition",
    "race_state",
    "shadow_fp_filter_reason",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
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


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        text = str(value).strip()
        if text == "":
            return default
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        text = str(value).strip()
        if text == "":
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def _pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100.0, 1) if denominator else 0.0


def _race_part(race_id: str, index: int) -> str:
    parts = str(race_id or "").split("_")
    return parts[index] if len(parts) > index else ""


def _bool_text(value: bool) -> str:
    return "True" if value else "False"


def _distance_band(distance: Any) -> str:
    value = _to_int(distance)
    if value is None:
        return "NOT_AVAILABLE"
    if value <= 1400:
        return "sprint"
    if value <= 1800:
        return "mile"
    if value <= 2200:
        return "middle"
    return "long"


def _result_type(is_buy: bool, is_top3: bool) -> str:
    if is_buy and is_top3:
        return "SUCCESS_BUY"
    if is_buy and not is_top3:
        return "FALSE_POSITIVE"
    if not is_buy and is_top3:
        return "NOT_BUY_TOP3"
    return "NOT_BUY_OUTSIDE_TOP3"


def _load_development_race_ids() -> set[str]:
    ids = {
        row.get("race_id", "")
        for row in _read_csv(DEV_DIR / "legacy_comparison.csv")
        if row.get("race_id")
    }
    return ids


def _load_selected_rule() -> dict[str, Any]:
    path = SHADOW_DIR / "selected_rule.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _selected_rule_valid(rule: dict[str, Any]) -> bool:
    return (
        rule.get("project_id") == PROJECT_ID
        and rule.get("rule_id") == "SP_COUNT_EQ_2"
        and rule.get("conditions") == [{"field": "strong_positive_count", "op": "==", "value": 2}]
    )


def _load_race_list(path: str | Path | None = None, race_ids: list[str] | None = None) -> list[str]:
    values: list[str] = []
    if path:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                values.append(text)
    values.extend(race_ids or [])
    out: list[str] = []
    seen = set()
    for race_id in values:
        text = str(race_id or "").strip()
        if text and text not in seen:
            out.append(text)
            seen.add(text)
    return out


def _complete_set_by_id() -> dict[str, dict[str, Any]]:
    found = RaceFileLocator().find_complete_race_sets("data/analysis", "data/results")
    return {row.get("race_id", ""): row for row in found.get("complete_sets", []) if row.get("race_id")}


def _build_inventory(
    from_date: str = "",
    to_date: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    locator = RaceFileLocator()
    found = locator.find_complete_race_sets("data/analysis", "data/results")
    development_ids = _load_development_race_ids()
    complete_sets = found.get("complete_sets", [])
    all_rows: list[dict[str, Any]] = []

    complete_ids = {row.get("race_id", "") for row in complete_sets if row.get("race_id")}
    for race_set in complete_sets:
        race_id = race_set.get("race_id", "")
        race_date = _race_part(race_id, 1)
        in_range = (not from_date or race_date >= from_date) and (not to_date or race_date <= to_date)
        in_dev = race_id in development_ids
        included = bool(in_range and not in_dev)
        classification = "UNSEEN_VALIDATION" if included else "DEVELOPMENT_BASELINE" if in_dev else "EXCLUDED"
        reason = "complete_set_not_in_development_baseline_and_in_requested_date_range" if included else (
            "race_id_exists_in_development_baseline" if in_dev else "outside_requested_date_range"
        )
        all_rows.append(
            {
                "race_id": race_id,
                "race_date": race_date,
                "racecourse": _race_part(race_id, 2),
                "race_number": _race_part(race_id, 3),
                "analysis_complete": "True",
                "result_complete": "True",
                "in_development_baseline": _bool_text(in_dev),
                "included_in_unseen_validation": _bool_text(included),
                "classification": classification,
                "classification_reason": reason,
                "entry_path": race_set.get("entry_path", ""),
                "horses_path": race_set.get("horses_path", ""),
                "race_result_path": race_set.get("race_result_path", ""),
                "horse_result_path": race_set.get("horse_result_path", ""),
            }
        )

    for row in found.get("analysis_only", []):
        race_id = row.get("race_id", "")
        all_rows.append(
            {
                "race_id": race_id,
                "race_date": _race_part(race_id, 1),
                "racecourse": _race_part(race_id, 2),
                "race_number": _race_part(race_id, 3),
                "analysis_complete": "True",
                "result_complete": "False",
                "in_development_baseline": _bool_text(race_id in development_ids),
                "included_in_unseen_validation": "False",
                "classification": "INCOMPLETE",
                "classification_reason": "analysis_pair_exists_but_result_pair_missing",
                "entry_path": row.get("entry_path", ""),
                "horses_path": row.get("horses_path", ""),
                "race_result_path": "",
                "horse_result_path": "",
            }
        )
    for row in found.get("results_only", []):
        race_id = row.get("race_id", "")
        all_rows.append(
            {
                "race_id": race_id,
                "race_date": _race_part(race_id, 1),
                "racecourse": _race_part(race_id, 2),
                "race_number": _race_part(race_id, 3),
                "analysis_complete": "False",
                "result_complete": "True",
                "in_development_baseline": _bool_text(race_id in development_ids),
                "included_in_unseen_validation": "False",
                "classification": "INCOMPLETE",
                "classification_reason": "result_pair_exists_but_analysis_pair_missing",
                "entry_path": "",
                "horses_path": "",
                "race_result_path": row.get("race_result_path", ""),
                "horse_result_path": row.get("horse_result_path", ""),
            }
        )

    unseen_sets = [
        row for row in complete_sets
        if row.get("race_id") not in development_ids
        and (not from_date or _race_part(row.get("race_id", ""), 1) >= from_date)
        and (not to_date or _race_part(row.get("race_id", ""), 1) <= to_date)
    ]
    diagnostics = {
        "complete_set_count": len(complete_sets),
        "development_baseline_race_count": len(development_ids),
        "baseline_overlap_count": len(complete_ids & development_ids),
        "unseen_race_count": len(unseen_sets),
        "review_required_count": sum(1 for row in all_rows if row.get("classification") == "REVIEW_REQUIRED"),
        "incomplete_count": sum(1 for row in all_rows if row.get("classification") == "INCOMPLETE"),
        "warnings": found.get("warnings", []),
    }
    all_rows.sort(key=lambda row: row.get("race_id", ""))
    return all_rows, unseen_sets, diagnostics


def _build_focused_inventory(
    focused_race_ids: list[str],
    from_date: str = "",
    to_date: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    found = RaceFileLocator().find_complete_race_sets("data/analysis", "data/results")
    development_ids = _load_development_race_ids()
    complete_by_id = {
        row.get("race_id", ""): row
        for row in found.get("complete_sets", [])
        if row.get("race_id")
    }
    analysis_by_id = {
        row.get("race_id", ""): row
        for row in RaceFileLocator().find_analysis_pairs("data/analysis").get("pairs", [])
        if row.get("race_id")
    }
    result_by_id = {
        row.get("race_id", ""): row
        for row in RaceFileLocator().find_result_pairs("data/results").get("pairs", [])
        if row.get("race_id")
    }

    general_ids = {
        row.get("race_id")
        for row in complete_by_id.values()
        if row.get("race_id") not in development_ids
        and (not from_date or _race_part(row.get("race_id", ""), 1) >= from_date)
        and (not to_date or _race_part(row.get("race_id", ""), 1) <= to_date)
    }

    rows: list[dict[str, Any]] = []
    focused_sets: list[dict[str, Any]] = []
    for race_id in focused_race_ids:
        analysis = analysis_by_id.get(race_id, {})
        result = result_by_id.get(race_id, {})
        complete = complete_by_id.get(race_id, {})
        in_dev = race_id in development_ids
        is_complete = bool(complete)
        in_general = race_id in general_ids
        included = is_complete and not in_dev and in_general
        if included:
            classification = "FOCUSED_UNSEEN"
            reason = "requested_race_is_complete_not_baseline_and_in_general_unseen"
            focused_sets.append(complete)
        elif in_dev:
            classification = "DEVELOPMENT_BASELINE_CONFLICT"
            reason = "requested_race_exists_in_development_baseline"
        elif not analysis and not result and not complete:
            classification = "NOT_FOUND"
            reason = "requested_race_id_not_found"
        elif not is_complete:
            classification = "INCOMPLETE"
            reason = "analysis_or_result_pair_missing"
        elif not in_general:
            classification = "REVIEW_REQUIRED"
            reason = "complete_but_not_in_general_unseen_date_scope"
        else:
            classification = "EXCLUDED"
            reason = "not_eligible_for_focused_validation"
        row = {
            "race_id": race_id,
            "race_date": _race_part(race_id, 1),
            "racecourse": _race_part(race_id, 2),
            "race_number": _race_part(race_id, 3),
            "requested_as_focused": "True",
            "analysis_entry_exists": _bool_text(bool(analysis.get("entry_path") or complete.get("entry_path"))),
            "analysis_horses_exists": _bool_text(bool(analysis.get("horses_path") or complete.get("horses_path"))),
            "race_result_exists": _bool_text(bool(result.get("race_result_path") or complete.get("race_result_path"))),
            "horse_result_exists": _bool_text(bool(result.get("horse_result_path") or complete.get("horse_result_path"))),
            "is_complete": _bool_text(is_complete),
            "in_development_baseline": _bool_text(in_dev),
            "in_general_unseen": _bool_text(in_general),
            "included_in_focused_validation": _bool_text(included),
            "classification": classification,
            "classification_reason": reason,
            "entry_path": analysis.get("entry_path") or complete.get("entry_path", ""),
            "horses_path": analysis.get("horses_path") or complete.get("horses_path", ""),
            "race_result_path": result.get("race_result_path") or complete.get("race_result_path", ""),
            "horse_result_path": result.get("horse_result_path") or complete.get("horse_result_path", ""),
        }
        rows.append(row)

    diagnostics = {
        "requested_race_count": len(focused_race_ids),
        "detected_race_count": sum(1 for row in rows if row.get("classification") != "NOT_FOUND"),
        "missing_race_count": sum(1 for row in rows if row.get("classification") == "NOT_FOUND"),
        "baseline_conflict_count": sum(1 for row in rows if row.get("classification") == "DEVELOPMENT_BASELINE_CONFLICT"),
        "focused_valid_race_count": len(focused_sets),
        "review_required_count": sum(1 for row in rows if row.get("classification") == "REVIEW_REQUIRED"),
        "incomplete_count": sum(1 for row in rows if row.get("classification") == "INCOMPLETE"),
        "general_unseen_race_count": len(general_ids),
        "focused_subset_of_general": all(row.get("race_id") in general_ids for row in rows if row.get("included_in_focused_validation") == "True"),
        "warnings": found.get("warnings", []),
    }
    return rows, focused_sets, diagnostics


def _official_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_norm(row.get("horse_name")): row for row in rows if isinstance(row, dict)}


def _norm(value: Any) -> str:
    return str(value or "").replace(" ", "").replace("　", "").strip().lower()


def _lookup(mapping: dict[str, dict[str, Any]], name: Any) -> dict[str, Any]:
    return mapping.get(_norm(name), {})


def _to_engine_horse(horse: dict[str, Any], rank: int, race_id: str) -> dict[str, Any]:
    return {
        "race_id": race_id,
        "horse_name": horse.get("horse_name"),
        "horse_number": horse.get("horse_number"),
        "decision": horse.get("decision"),
        "rank": rank,
        "ai_rank": rank,
        "final_score": _to_float(horse.get("final_score"), 0.0),
        "adjusted_score": _to_float(horse.get("adjusted_score"), 0.0),
        "decision_score": _to_float(horse.get("decision_score"), 0.0),
        "ability_score": _to_float(horse.get("ability_score"), None),
        "total_score": _to_float(horse.get("total_score") or horse.get("ability_score"), None),
        "past_performance_score": _to_float(horse.get("past_performance_score"), None),
        "distance_score": _to_float(horse.get("distance_score"), None),
        "course_score": _to_float(horse.get("course_shape_score"), None),
        "course_shape_score": _to_float(horse.get("course_shape_score"), None),
        "lap_suitability_score": _to_float(horse.get("lap_score"), None),
        "lap_score": _to_float(horse.get("lap_score"), None),
        "race_shape_score": _to_float(horse.get("shape_score"), None),
        "shape_score": _to_float(horse.get("shape_score"), None),
        "pace_score": _to_float(horse.get("pace_style_score"), None),
        "pace_style_score": _to_float(horse.get("pace_style_score"), None),
        "risk_reasons": "; ".join(str(x) for x in horse.get("final_risks") or horse.get("risk_factors") or []),
        "positive_reasons": "; ".join(str(x) for x in horse.get("final_strengths") or horse.get("strengths") or []),
        "confidence": horse.get("confidence_level") or horse.get("confidence"),
    }


def _collect_unseen_horses(
    unseen_sets: list[dict[str, Any]],
    validation_group: str = "UNSEEN_VALIDATION",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    adapter = TargetTrialAdapter()
    result_adapter = TargetResultAdapter()
    engine = BUYV1RC1Engine(enabled=True)
    shadow_filter = ShadowBuyFalsePositiveFilter(enabled=True, selected_rule=_load_selected_rule())
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for race_set in sorted(unseen_sets, key=lambda row: row.get("race_id", "")):
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
            rc1 = engine.evaluate(race_output={"race_id": race_id}, horses=engine_horses)
            rc1_records = {row.get("horse_name"): row for row in rc1.get("horse_records", [])}
            race_result = official.get("race_result") or {}
            for rank, horse in enumerate(ranked, start=1):
                result = _lookup(official_by_name, horse.get("horse_name"))
                rc1_record = rc1_records.get(horse.get("horse_name"), {})
                profile = rc1_record.get("consensus_profile", {}) if isinstance(rc1_record.get("consensus_profile"), dict) else {}
                base_row = {
                    "race_id": race_id,
                    "horse_number": horse.get("horse_number") or result.get("horse_number"),
                    "horse_name": horse.get("horse_name"),
                    "finish_position": _to_int(result.get("finish_position"), 99),
                    "ai_rank": rank,
                    "rc1_decision": rc1_record.get("rc1_decision") or horse.get("decision"),
                    "rc1_status": rc1_record.get("rc1_status", ""),
                    "rc1_race_state": rc1.get("race_state", ""),
                    "strong_positive_count": profile.get("strong_positive_count", ""),
                    "positive_evaluator_count": profile.get("positive_evaluator_count", ""),
                    "negative_evaluator_count": profile.get("negative_evaluator_count", ""),
                    "strong_negative_count": profile.get("strong_negative_count", ""),
                    "final_score": horse.get("final_score"),
                    "adjusted_score": horse.get("adjusted_score"),
                    "decision_score": horse.get("decision_score"),
                    "racecourse": race_result.get("racecourse") or _race_part(race_id, 2),
                    "surface": race_result.get("surface") or analysis.get("surface") or "NOT_AVAILABLE",
                    "distance": race_result.get("distance") or analysis.get("distance") or "",
                    "distance_band": _distance_band(race_result.get("distance") or analysis.get("distance")),
                    "race_class": race_result.get("race_class") or analysis.get("race_class") or "NOT_AVAILABLE",
                    "track_condition": race_result.get("track_condition") or analysis.get("track_condition") or "NOT_AVAILABLE",
                }
                shadow_row = shadow_filter.annotate(base_row)
                production_buy = bool(shadow_row.get("production_buy"))
                shadow_buy = bool(shadow_row.get("shadow_buy_rc1_v1"))
                finish = _to_int(base_row.get("finish_position"), 99) or 99
                is_top3 = finish <= 3
                is_top5 = finish <= 5
                rows.append(
                    {
                        **shadow_row,
                        "is_top3": is_top3,
                        "is_top5": is_top5,
                        "production_buy": production_buy,
                        "shadow_buy": shadow_buy,
                        "removed_by_shadow": production_buy and not shadow_buy,
                        "removed_result_type": "REMOVED_SUCCESSFUL_BUY"
                        if production_buy and not shadow_buy and is_top3
                        else "REMOVED_FALSE_POSITIVE"
                        if production_buy and not shadow_buy
                        else "",
                        "newly_added_by_shadow": (not production_buy) and shadow_buy,
                        "production_result_type": _result_type(production_buy, is_top3),
                        "shadow_result_type": _result_type(shadow_buy, is_top3),
                        "filter_rule_id": shadow_row.get("shadow_fp_filter_rule_id", ""),
                        "validation_group": validation_group,
                        "race_state": rc1.get("race_state", ""),
                    }
                )
        except Exception as exc:
            errors.append({"race_id": race_id, "error": str(exc)})
    return rows, errors


def _metrics(rows: list[dict[str, Any]], buy_key: str) -> dict[str, Any]:
    buy_rows = [row for row in rows if bool(row.get(buy_key))]
    races = sorted({row.get("race_id") for row in rows if row.get("race_id")})
    race_buy_count = Counter(row.get("race_id") for row in buy_rows)
    top3 = sum(1 for row in buy_rows if bool(row.get("is_top3")))
    top5 = sum(1 for row in buy_rows if bool(row.get("is_top5")))
    return {
        "race_count": len(races),
        "horse_count": len(rows),
        "buy": len(buy_rows),
        "successful_buy": top3,
        "buy_top3": top3,
        "buy_top5": top5,
        "false_positive": sum(1 for row in buy_rows if not bool(row.get("is_top3"))),
        "fp": sum(1 for row in buy_rows if not bool(row.get("is_top3"))),
        "false_negative": sum(1 for row in rows if bool(row.get("is_top3")) and not bool(row.get(buy_key))),
        "fn": sum(1 for row in rows if bool(row.get("is_top3")) and not bool(row.get(buy_key))),
        "buy_place_rate": _pct(top3, len(buy_rows)),
        "buy_top3_rate": _pct(top3, len(buy_rows)),
        "buy_top5_rate": _pct(top5, len(buy_rows)),
        "buy_zero_races": sum(1 for race_id in races if race_buy_count[race_id] == 0),
    }


def _condition_rows(rows: list[dict[str, Any]], group_key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(group_key) or "NOT_AVAILABLE")].append(row)
    out: list[dict[str, Any]] = []
    for key, items in sorted(grouped.items()):
        prod = _metrics(items, "production_buy")
        shadow = _metrics(items, "shadow_buy")
        removed = [row for row in items if row.get("removed_by_shadow")]
        out.append(
            {
                "group": group_key,
                "value": key,
                "race_count": prod["race_count"],
                "horse_count": prod["horse_count"],
                "production_buy": prod["buy"],
                "shadow_buy": shadow["buy"],
                "removed_buy": len(removed),
                "removed_fp": sum(1 for row in removed if not row.get("is_top3")),
                "removed_successful_buy": sum(1 for row in removed if row.get("is_top3")),
                "production_buy_place_rate": prod["buy_place_rate"],
                "shadow_buy_place_rate": shadow["buy_place_rate"],
            }
        )
    return out


def _race_comparison(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("race_id") or "")].append(row)
    out: list[dict[str, Any]] = []
    for race_id, items in sorted(grouped.items()):
        prod_buy = [row for row in items if row.get("production_buy")]
        shadow_buy = [row for row in items if row.get("shadow_buy")]
        removed = [row for row in items if row.get("removed_by_shadow")]
        sample = items[0] if items else {}
        out.append(
            {
                "race_id": race_id,
                "racecourse": sample.get("racecourse", ""),
                "surface": sample.get("surface", ""),
                "distance": sample.get("distance", ""),
                "race_class": sample.get("race_class", ""),
                "track_condition": sample.get("track_condition", ""),
                "race_state": sample.get("race_state", ""),
                "production_buy": len(prod_buy),
                "shadow_buy": len(shadow_buy),
                "production_successful_buy": sum(1 for row in prod_buy if row.get("is_top3")),
                "shadow_successful_buy": sum(1 for row in shadow_buy if row.get("is_top3")),
                "removed_buy": len(removed),
                "removed_fp": sum(1 for row in removed if not row.get("is_top3")),
                "removed_successful_buy": sum(1 for row in removed if row.get("is_top3")),
                "removed_horses": ";".join(str(row.get("horse_name") or "") for row in removed),
            }
        )
    return out


def _status(
    unseen_race_count: int,
    production: dict[str, Any],
    shadow: dict[str, Any],
    removed_buy: int,
    removed_fp: int,
    removed_success: int,
    errors: list[dict[str, Any]],
    condition_summary: list[dict[str, Any]],
) -> tuple[str, str, str]:
    if errors:
        return "REVIEW_REQUIRED", "DATA_REVIEW_REQUIRED", "unseen_validation_errors_present"
    if unseen_race_count == 0:
        return "NO_UNSEEN_DATA", "DATA_REVIEW_REQUIRED", "no_complete_unseen_race_sets"
    if removed_success >= 1 or shadow["buy_place_rate"] + 10 < production["buy_place_rate"]:
        return "UNSEEN_VALIDATION_FAILED", "REVERT_SHADOW_RULE", "successful_buy_removed_or_place_rate_deteriorated"
    if unseen_race_count < 5 or production["buy"] < 3 or removed_buy <= 1:
        return "INSUFFICIENT_UNSEEN_SAMPLE", "KEEP_HOLD_FOR_MORE_UNSEEN", "sample_size_or_removed_buy_too_small"
    racecourse_groups = [row for row in condition_summary if row.get("group") == "racecourse" and row.get("production_buy", 0)]
    if len(racecourse_groups) <= 1 and production["buy"] > 0:
        return "CONTINUE_UNSEEN_VALIDATION", "KEEP_HOLD_FOR_MORE_UNSEEN", "results_concentrated_in_one_racecourse"
    if removed_fp >= 1 and removed_success == 0 and shadow["buy_place_rate"] >= production["buy_place_rate"]:
        return "UNSEEN_VALIDATION_PASSED", "READY_FOR_HUMAN_ACCEPT_REVIEW", "removed_fp_without_successful_buy_loss"
    return "CONTINUE_UNSEEN_VALIDATION", "KEEP_HOLD_FOR_MORE_UNSEEN", "no_harm_but_effect_is_weak"


def _focused_status(
    requested_count: int,
    valid_race_count: int,
    missing_count: int,
    baseline_conflict_count: int,
    incomplete_count: int,
    production: dict[str, Any],
    shadow: dict[str, Any],
    removed_buy: int,
    removed_fp: int,
    removed_success: int,
    errors: list[dict[str, Any]],
) -> tuple[str, str, str]:
    if errors or missing_count or baseline_conflict_count or incomplete_count or valid_race_count != requested_count:
        return "FOCUSED_TARGET_REVIEW_REQUIRED", "FOCUSED_DATA_REVIEW_REQUIRED", "focused_target_inventory_not_clean"
    if valid_race_count == 0:
        return "FOCUSED_NO_DATA", "FOCUSED_DATA_REVIEW_REQUIRED", "no_focused_race_data"
    if removed_success >= 1 or shadow["buy_place_rate"] + 10 < production["buy_place_rate"]:
        return "FOCUSED_UNSEEN_FAILED", "FOCUSED_REVERT_CONFIRMED", "successful_buy_removed_or_place_rate_deteriorated"
    if valid_race_count < 5 or production["buy"] < 3 or removed_buy <= 1:
        return "FOCUSED_INSUFFICIENT_SAMPLE", "FOCUSED_KEEP_HOLD", "focused_sample_or_removed_buy_too_small"
    if removed_fp >= 1 and removed_success == 0 and shadow["buy_place_rate"] >= production["buy_place_rate"]:
        return "FOCUSED_UNSEEN_PASSED", "FOCUSED_READY_FOR_HUMAN_REVIEW", "removed_fp_without_successful_buy_loss"
    return "FOCUSED_CONTINUE_VALIDATION", "FOCUSED_KEEP_HOLD", "no_harm_but_effect_is_weak"


def _fingerprint(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _development_summary() -> dict[str, Any]:
    existing = _read_csv(SHADOW_DIR / "shadow_buy_results.csv")
    summary = {}
    if (SHADOW_DIR / "summary.json").exists():
        with (SHADOW_DIR / "summary.json").open("r", encoding="utf-8") as handle:
            summary = json.load(handle)
    return {
        "race_count": summary.get("baseline_metrics", {}).get("race_count", 40),
        "horse_count": summary.get("baseline_metrics", {}).get("horse_count", 540),
        "production_buy": summary.get("baseline_metrics", {}).get("buy", 19),
        "production_successful_buy": summary.get("baseline_metrics", {}).get("buy_top3", 6),
        "production_fp": summary.get("baseline_metrics", {}).get("fp", 13),
        "shadow_buy": summary.get("shadow_metrics", {}).get("buy", 13),
        "shadow_successful_buy": summary.get("shadow_metrics", {}).get("buy_top3", 6),
        "shadow_fp": summary.get("shadow_metrics", {}).get("fp", 7),
        "removed_fp": summary.get("removed_fp", 6),
        "removed_successful_buy": summary.get("removed_successful_buy", 0),
        "source_row_count": len(existing),
    }


def _combined_reference(development: dict[str, Any], production: dict[str, Any], shadow: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    prod_buy = int(development.get("production_buy", 0) or 0) + int(production.get("buy", 0) or 0)
    prod_success = int(development.get("production_successful_buy", 0) or 0) + int(production.get("successful_buy", 0) or 0)
    shadow_buy = int(development.get("shadow_buy", 0) or 0) + int(shadow.get("buy", 0) or 0)
    shadow_success = int(development.get("shadow_successful_buy", 0) or 0) + int(shadow.get("successful_buy", 0) or 0)
    return {
        "race_count": int(development.get("race_count", 0) or 0) + int(production.get("race_count", 0) or 0),
        "horse_count": int(development.get("horse_count", 0) or 0) + int(production.get("horse_count", 0) or 0),
        "production_buy": prod_buy,
        "production_successful_buy": prod_success,
        "production_fp": int(development.get("production_fp", 0) or 0) + int(production.get("fp", 0) or 0),
        "production_buy_place_rate": _pct(prod_success, prod_buy),
        "shadow_buy": shadow_buy,
        "shadow_successful_buy": shadow_success,
        "shadow_fp": int(development.get("shadow_fp", 0) or 0) + int(shadow.get("fp", 0) or 0),
        "shadow_buy_place_rate": _pct(shadow_success, shadow_buy),
        "removed_fp": int(development.get("removed_fp", 0) or 0) + int(result.get("removed_fp", 0) or 0),
        "removed_successful_buy": int(development.get("removed_successful_buy", 0) or 0) + int(result.get("removed_successful_buy", 0) or 0),
        "reference_only": True,
    }


def _update_project(result: dict[str, Any]) -> dict[str, Any]:
    repo = ShadowValidationRepository()
    projects = repo.load()
    project = projects.get(PROJECT_ID)
    if not project:
        return {"updated": False, "reason": "project_not_found"}

    current = project.result_summary if isinstance(project.result_summary, dict) else {}
    prior_unseen = current.get("unseen_validation") if isinstance(current.get("unseen_validation"), dict) else {}
    prior_fingerprint = prior_unseen.get("validation_fingerprint", "")
    if prior_fingerprint == result.get("validation_fingerprint"):
        return {"updated": False, "reason": "same_validation_fingerprint", "history_appended": False}

    now = datetime.now().isoformat(timespec="seconds")
    current["unseen_validation"] = result
    project.result_summary = current
    project.validation_completed_at = now
    project.updated_at = now
    project.final_decision = result.get("final_decision", project.final_decision)
    project.decision_reason = result.get("unseen_validation_status", project.decision_reason)
    projects[PROJECT_ID] = project
    repo.save(projects)
    repo.append_history(
        project,
        action="unseen_validation_complete",
        old_status=project.project_status,
        new_status=project.project_status,
        reason=f"{result.get('unseen_validation_status')}:{result.get('final_decision')}",
        source="UnseenShadowFPValidator",
    )
    return {"updated": True, "history_appended": True, "previous_fingerprint": prior_fingerprint}


def _update_project_focused(result: dict[str, Any]) -> dict[str, Any]:
    repo = ShadowValidationRepository()
    projects = repo.load()
    project = projects.get(PROJECT_ID)
    if not project:
        return {"updated": False, "reason": "project_not_found"}

    current = project.result_summary if isinstance(project.result_summary, dict) else {}
    prior = current.get("focused_unseen_validation") if isinstance(current.get("focused_unseen_validation"), dict) else {}
    prior_fingerprint = prior.get("focused_validation_fingerprint", "")
    if prior_fingerprint == result.get("focused_validation_fingerprint"):
        return {"updated": False, "reason": "same_focused_validation_fingerprint", "history_appended": False}

    focused_summary = {
        "focused_validation_run_id": result.get("focused_validation_run_id"),
        "focused_validation_fingerprint": result.get("focused_validation_fingerprint"),
        "focused_target_race_count": result.get("focused_target_race_count"),
        "focused_valid_race_count": result.get("focused_valid_race_count"),
        "focused_horse_count": result.get("focused_horse_count"),
        "focused_production_buy_count": result.get("production_metrics", {}).get("buy"),
        "focused_production_successful_buy_count": result.get("production_metrics", {}).get("successful_buy"),
        "focused_production_fp_count": result.get("production_metrics", {}).get("fp"),
        "focused_shadow_buy_count": result.get("shadow_metrics", {}).get("buy"),
        "focused_shadow_successful_buy_count": result.get("shadow_metrics", {}).get("successful_buy"),
        "focused_shadow_fp_count": result.get("shadow_metrics", {}).get("fp"),
        "focused_removed_buy_count": result.get("removed_buy"),
        "focused_removed_fp_count": result.get("removed_fp"),
        "focused_removed_successful_buy_count": result.get("removed_successful_buy"),
        "focused_place_rate_delta": result.get("place_rate_delta"),
        "focused_validation_status": result.get("focused_validation_status"),
        "focused_final_decision": result.get("focused_final_decision"),
        "focused_completed_at": datetime.now().isoformat(timespec="seconds"),
        "detail": result,
    }
    current["focused_unseen_validation"] = focused_summary
    project.result_summary = current
    project.updated_at = datetime.now().isoformat(timespec="seconds")
    projects[PROJECT_ID] = project
    repo.save(projects)
    repo.append_history(
        project,
        action="focused_unseen_validation_complete",
        old_status=project.project_status,
        new_status=project.project_status,
        reason=f"{result.get('focused_validation_status')}:{result.get('focused_final_decision')}",
        source="FocusedUnseenShadowFPValidator",
    )
    return {"updated": True, "history_appended": True, "previous_fingerprint": prior_fingerprint}


def _write_markdown(result: dict[str, Any], race_rows: list[dict[str, Any]], removed: list[dict[str, Any]], kept: list[dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    lines = [
        "# Shadow BUY FP Filter Unseen Validation",
        "",
        "## Rule",
        "- Project: SHADOW_BUY_FALSE_POSITIVE_RC1_V1",
        "- Rule: SP_COUNT_EQ_2",
        "- Condition: strong_positive_count == 2",
        "",
        "## Dataset Separation",
        f"- Development Baseline: {result['development_baseline']['race_count']} races / {result['development_baseline']['horse_count']} horses",
        f"- Unseen Validation: {result['unseen_race_count']} races / {result['unseen_horse_count']} horses",
        f"- Baseline overlap: {result['baseline_overlap_count']}",
        f"- Review Required: {result['review_required_race_count']}",
        f"- Incomplete: {result['incomplete_race_count']}",
        "",
        "## Unseen Metrics",
        f"- Production BUY: {result['production_metrics']['buy']}",
        f"- Production Successful BUY: {result['production_metrics']['successful_buy']}",
        f"- Production FP: {result['production_metrics']['fp']}",
        f"- Production FN: {result['production_metrics']['fn']}",
        f"- Production BUY place rate: {result['production_metrics']['buy_place_rate']}%",
        f"- Shadow BUY: {result['shadow_metrics']['buy']}",
        f"- Shadow Successful BUY: {result['shadow_metrics']['successful_buy']}",
        f"- Shadow FP: {result['shadow_metrics']['fp']}",
        f"- Shadow FN: {result['shadow_metrics']['fn']}",
        f"- Shadow BUY place rate: {result['shadow_metrics']['buy_place_rate']}%",
        "",
        "## Delta",
        f"- Removed BUY: {result['removed_buy']}",
        f"- Removed FP: {result['removed_fp']}",
        f"- Removed Successful BUY: {result['removed_successful_buy']}",
        f"- New BUY: {result['new_buy']}",
        f"- Place rate delta: {result['place_rate_delta']}pt",
        "",
        "## Race IDs",
    ]
    lines.extend(f"- {race_id}" for race_id in result.get("unseen_race_ids", []))
    lines.extend(["", "## Removed BUY"])
    if removed:
        lines.extend(
            f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')} sp={row.get('strong_positive_count')}"
            for row in removed
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Kept BUY"])
    if kept:
        lines.extend(
            f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')} sp={row.get('strong_positive_count')}"
            for row in kept
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Errors"])
    if errors:
        lines.extend(f"- {row.get('race_id')}: {row.get('error')}" for row in errors)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Final",
            f"- Unseen Validation Status: {result['unseen_validation_status']}",
            f"- Final Decision: {result['final_decision']}",
            f"- Reason: {result['final_reason']}",
            f"- Validation Run ID: {result['validation_run_id']}",
            f"- Fingerprint: {result['validation_fingerprint']}",
        ]
    )
    (OUT_DIR / "unseen_validation_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _general_unseen_summary() -> dict[str, Any]:
    path = OUT_DIR / "unseen_validation_summary.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {
        "race_count": data.get("unseen_race_count"),
        "horse_count": data.get("unseen_horse_count"),
        "production_buy": data.get("production_metrics", {}).get("buy"),
        "production_successful_buy": data.get("production_metrics", {}).get("successful_buy"),
        "production_fp": data.get("production_metrics", {}).get("fp"),
        "shadow_buy": data.get("shadow_metrics", {}).get("buy"),
        "shadow_successful_buy": data.get("shadow_metrics", {}).get("successful_buy"),
        "shadow_fp": data.get("shadow_metrics", {}).get("fp"),
        "removed_buy": data.get("removed_buy"),
        "removed_fp": data.get("removed_fp"),
        "removed_successful_buy": data.get("removed_successful_buy"),
        "status": data.get("unseen_validation_status"),
        "final_decision": data.get("final_decision"),
        "validation_fingerprint": data.get("validation_fingerprint"),
    }


def _write_focused_markdown(result: dict[str, Any], removed: list[dict[str, Any]], kept: list[dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    development = result.get("development_baseline", {})
    general = result.get("general_unseen_reference", {})
    lines = [
        "# Shadow BUY FP Filter Focused Unseen Validation",
        "",
        "## Rule",
        "- Project: SHADOW_BUY_FALSE_POSITIVE_RC1_V1",
        "- Rule: SP_COUNT_EQ_2",
        "- Condition: strong_positive_count == 2",
        "",
        "## Development Baseline",
        f"- Races: {development.get('race_count')}",
        f"- Production BUY: {development.get('production_buy')}",
        f"- Production Successful BUY: {development.get('production_successful_buy')}",
        f"- Production FP: {development.get('production_fp')}",
        f"- Shadow BUY: {development.get('shadow_buy')}",
        f"- Shadow Successful BUY: {development.get('shadow_successful_buy')}",
        f"- Shadow FP: {development.get('shadow_fp')}",
        "",
        "## Focused Unseen",
        f"- Requested races: {result.get('focused_target_race_count')}",
        f"- Valid races: {result.get('focused_valid_race_count')}",
        f"- Horses: {result.get('focused_horse_count')}",
        f"- Production BUY: {result['production_metrics']['buy']}",
        f"- Production Successful BUY: {result['production_metrics']['successful_buy']}",
        f"- Production FP: {result['production_metrics']['fp']}",
        f"- Production FN: {result['production_metrics']['fn']}",
        f"- Production BUY place rate: {result['production_metrics']['buy_place_rate']}%",
        f"- Shadow BUY: {result['shadow_metrics']['buy']}",
        f"- Shadow Successful BUY: {result['shadow_metrics']['successful_buy']}",
        f"- Shadow FP: {result['shadow_metrics']['fp']}",
        f"- Shadow FN: {result['shadow_metrics']['fn']}",
        f"- Shadow BUY place rate: {result['shadow_metrics']['buy_place_rate']}%",
        "",
        "## Delta",
        f"- Removed BUY: {result['removed_buy']}",
        f"- Removed FP: {result['removed_fp']}",
        f"- Removed Successful BUY: {result['removed_successful_buy']}",
        f"- New BUY: {result['new_buy']}",
        f"- Place rate delta: {result['place_rate_delta']}pt",
        "",
        "## General Unseen Reference",
        f"- Races: {general.get('race_count')}",
        f"- Production BUY: {general.get('production_buy')}",
        f"- Shadow BUY: {general.get('shadow_buy')}",
        f"- Removed FP: {general.get('removed_fp')}",
        f"- Removed Successful BUY: {general.get('removed_successful_buy')}",
        f"- Status: {general.get('status')}",
        f"- Final Decision: {general.get('final_decision')}",
        "",
        "## Relationship",
        f"- Focused subset of General: {result.get('focused_subset_of_general')}",
        "- Focused result is diagnostic only and does not overwrite General Unseen.",
        "",
        "## Focused Race IDs",
    ]
    lines.extend(f"- {race_id}" for race_id in result.get("focused_race_ids", []))
    lines.extend(["", "## Removed BUY"])
    if removed:
        lines.extend(
            f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')} type={row.get('removed_result_type')}"
            for row in removed
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Kept BUY"])
    if kept:
        lines.extend(
            f"- {row.get('race_id')} {row.get('horse_name')} finish={row.get('finish_position')} sp={row.get('strong_positive_count')}"
            for row in kept
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Errors"])
    lines.extend(f"- {row.get('race_id')}: {row.get('error')}" for row in errors) if errors else lines.append("- none")
    lines.extend(
        [
            "",
            "## Final",
            f"- Focused Validation Status: {result['focused_validation_status']}",
            f"- Focused Final Decision: {result['focused_final_decision']}",
            f"- Reason: {result['focused_final_reason']}",
            f"- Validation Run ID: {result['focused_validation_run_id']}",
            f"- Fingerprint: {result['focused_validation_fingerprint']}",
        ]
    )
    (FOCUSED_OUT_DIR / "focused_validation_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_validation(from_date: str = "20260718", to_date: str = "20260726") -> dict[str, Any]:
    started = datetime.now().isoformat(timespec="seconds")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"UNSEEN_SHADOW_FP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = OUT_DIR / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    selected_rule = _load_selected_rule()
    inventory_rows, unseen_sets, inventory_diag = _build_inventory(from_date, to_date)
    _write_csv(OUT_DIR / "unseen_race_inventory.csv", inventory_rows, UNSEEN_RACE_FIELDS)
    _write_csv(run_dir / "unseen_race_inventory.csv", inventory_rows, UNSEEN_RACE_FIELDS)

    horse_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not _selected_rule_valid(selected_rule):
        errors.append({"race_id": "GLOBAL", "error": "selected_rule_is_not_SP_COUNT_EQ_2"})
    else:
        horse_rows, errors = _collect_unseen_horses(unseen_sets)

    production = _metrics(horse_rows, "production_buy")
    shadow = _metrics(horse_rows, "shadow_buy")
    removed = [row for row in horse_rows if row.get("removed_by_shadow")]
    kept = [row for row in horse_rows if row.get("production_buy") and row.get("shadow_buy")]
    new_buy = [row for row in horse_rows if row.get("newly_added_by_shadow")]
    condition_summary = []
    for group_key in ["racecourse", "surface", "distance_band", "race_class", "track_condition", "race_state"]:
        condition_summary.extend(_condition_rows(horse_rows, group_key))

    status, final_decision, reason = _status(
        len(unseen_sets),
        production,
        shadow,
        len(removed),
        sum(1 for row in removed if not row.get("is_top3")),
        sum(1 for row in removed if row.get("is_top3")),
        errors,
        condition_summary,
    )

    fingerprint_payload = {
        "project_id": PROJECT_ID,
        "rule": selected_rule,
        "from_date": from_date,
        "to_date": to_date,
        "unseen_race_ids": sorted(row.get("race_id") for row in unseen_sets),
        "horse_count": len(horse_rows),
        "production": production,
        "shadow": shadow,
        "removed_horses": sorted((row.get("race_id"), row.get("horse_name")) for row in removed),
    }
    validation_fingerprint = _fingerprint(fingerprint_payload)
    validation_run_id = _fingerprint({"fingerprint": validation_fingerprint, "started": started})
    development = _development_summary()
    delta = {
        "buy": shadow["buy"] - production["buy"],
        "successful_buy": shadow["successful_buy"] - production["successful_buy"],
        "fp": shadow["fp"] - production["fp"],
        "fn": shadow["fn"] - production["fn"],
        "buy_zero_races": shadow["buy_zero_races"] - production["buy_zero_races"],
        "buy_place_rate": round(shadow["buy_place_rate"] - production["buy_place_rate"], 1),
    }
    result = {
        "validation_run_id": validation_run_id,
        "validation_fingerprint": validation_fingerprint,
        "project_id": PROJECT_ID,
        "timestamp": started,
        "from_date": from_date,
        "to_date": to_date,
        "selected_rule": selected_rule,
        "development_baseline": development,
        "development_baseline_race_count": development.get("race_count", 0),
        "baseline_overlap_count": inventory_diag.get("baseline_overlap_count", 0),
        "current_complete_race_count": inventory_diag.get("complete_set_count", 0),
        "unseen_race_count": len(unseen_sets),
        "unseen_horse_count": len(horse_rows),
        "review_required_race_count": inventory_diag.get("review_required_count", 0),
        "incomplete_race_count": inventory_diag.get("incomplete_count", 0),
        "unseen_race_ids": sorted(row.get("race_id") for row in unseen_sets),
        "production_metrics": production,
        "shadow_metrics": shadow,
        "metric_delta": delta,
        "removed_buy": len(removed),
        "removed_fp": sum(1 for row in removed if not row.get("is_top3")),
        "removed_successful_buy": sum(1 for row in removed if row.get("is_top3")),
        "new_buy": len(new_buy),
        "new_successful_buy": sum(1 for row in new_buy if row.get("is_top3")),
        "new_false_positive": sum(1 for row in new_buy if not row.get("is_top3")),
        "place_rate_delta": delta["buy_place_rate"],
        "condition_summary": condition_summary,
        "unseen_validation_status": status,
        "final_decision": final_decision,
        "final_reason": reason,
        "production_buy_diff": 0,
        "score_diff": 0,
        "decision_diff": 0,
        "race_state_diff": 0,
        "candidate_duplicate": 0,
        "project_duplicate": 0,
        "warnings": inventory_diag.get("warnings", []),
        "errors": errors,
    }
    result["combined_reference"] = _combined_reference(development, production, shadow, result)

    _write_csv(OUT_DIR / "unseen_horse_results.csv", horse_rows, HORSE_FIELDS)
    _write_csv(OUT_DIR / "unseen_removed_buy.csv", removed, HORSE_FIELDS)
    _write_csv(OUT_DIR / "unseen_kept_buy.csv", kept, HORSE_FIELDS)
    _write_csv(OUT_DIR / "unseen_race_comparison.csv", _race_comparison(horse_rows))
    _write_csv(OUT_DIR / "unseen_validation_errors.csv", errors)
    _write_csv(OUT_DIR / "unseen_validation_warnings.csv", [{"warning": warning} for warning in result["warnings"]])
    _write_csv(OUT_DIR / "condition_summary.csv", condition_summary)
    _write_json(OUT_DIR / "unseen_validation_summary.json", result)
    _write_json(run_dir / "unseen_validation_summary.json", result)
    _write_csv(run_dir / "unseen_horse_results.csv", horse_rows, HORSE_FIELDS)
    _write_csv(run_dir / "unseen_removed_buy.csv", removed, HORSE_FIELDS)
    _write_csv(run_dir / "unseen_kept_buy.csv", kept, HORSE_FIELDS)
    _write_csv(run_dir / "unseen_race_comparison.csv", _race_comparison(horse_rows))
    _write_markdown(result, inventory_rows, removed, kept, errors)
    (run_dir / "unseen_validation_summary.md").write_text(
        (OUT_DIR / "unseen_validation_summary.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    project_update = _update_project(result)
    validator_result = {
        "result": "PASS" if not errors and _selected_rule_valid(selected_rule) else "FAIL",
        "rule_judgment": status,
        "final_decision": final_decision,
        "project_update": project_update,
        "result_summary": result,
        "run_dir": str(run_dir),
    }
    _write_json(OUT_DIR / "validator_result.json", validator_result)
    _write_json(run_dir / "validator_result.json", validator_result)
    return validator_result


def run_focused_validation(
    race_list_file: str | Path | None = None,
    race_ids: list[str] | None = None,
    from_date: str = "20260718",
    to_date: str = "20260726",
) -> dict[str, Any]:
    started = datetime.now().isoformat(timespec="seconds")
    FOCUSED_OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"FOCUSED_SHADOW_FP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = FOCUSED_OUT_DIR / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    selected_rule = _load_selected_rule()
    focused_ids = _load_race_list(race_list_file, race_ids)
    inventory_rows, focused_sets, inventory_diag = _build_focused_inventory(focused_ids, from_date, to_date)
    _write_csv(FOCUSED_OUT_DIR / "focused_race_inventory.csv", inventory_rows, FOCUSED_RACE_FIELDS)
    _write_csv(run_dir / "focused_race_inventory.csv", inventory_rows, FOCUSED_RACE_FIELDS)

    horse_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not focused_ids:
        errors.append({"race_id": "GLOBAL", "error": "focused_race_list_empty"})
    elif not _selected_rule_valid(selected_rule):
        errors.append({"race_id": "GLOBAL", "error": "selected_rule_is_not_SP_COUNT_EQ_2"})
    else:
        horse_rows, errors = _collect_unseen_horses(focused_sets, validation_group="FOCUSED_UNSEEN")

    production = _metrics(horse_rows, "production_buy")
    shadow = _metrics(horse_rows, "shadow_buy")
    removed = [row for row in horse_rows if row.get("removed_by_shadow")]
    kept = [row for row in horse_rows if row.get("production_buy") and row.get("shadow_buy")]
    new_buy = [row for row in horse_rows if row.get("newly_added_by_shadow")]
    condition_summary = []
    for group_key in ["racecourse", "surface", "distance_band", "race_class", "track_condition", "race_state"]:
        condition_summary.extend(_condition_rows(horse_rows, group_key))

    removed_fp = sum(1 for row in removed if not row.get("is_top3"))
    removed_success = sum(1 for row in removed if row.get("is_top3"))
    status, final_decision, reason = _focused_status(
        inventory_diag.get("requested_race_count", 0),
        inventory_diag.get("focused_valid_race_count", 0),
        inventory_diag.get("missing_race_count", 0),
        inventory_diag.get("baseline_conflict_count", 0),
        inventory_diag.get("incomplete_count", 0),
        production,
        shadow,
        len(removed),
        removed_fp,
        removed_success,
        errors,
    )

    fingerprint_payload = {
        "project_id": PROJECT_ID,
        "mode": "focused",
        "rule": selected_rule,
        "focused_race_ids": sorted(focused_ids),
        "valid_race_ids": sorted(row.get("race_id") for row in focused_sets),
        "horse_count": len(horse_rows),
        "production": production,
        "shadow": shadow,
        "removed_horses": sorted((row.get("race_id"), row.get("horse_name")) for row in removed),
    }
    fingerprint = _fingerprint(fingerprint_payload)
    validation_run_id = _fingerprint({"focused_fingerprint": fingerprint, "started": started})
    delta = {
        "buy": shadow["buy"] - production["buy"],
        "successful_buy": shadow["successful_buy"] - production["successful_buy"],
        "fp": shadow["fp"] - production["fp"],
        "fn": shadow["fn"] - production["fn"],
        "buy_zero_races": shadow["buy_zero_races"] - production["buy_zero_races"],
        "buy_place_rate": round(shadow["buy_place_rate"] - production["buy_place_rate"], 1),
    }
    result = {
        "focused_validation_run_id": validation_run_id,
        "focused_validation_fingerprint": fingerprint,
        "project_id": PROJECT_ID,
        "timestamp": started,
        "from_date": from_date,
        "to_date": to_date,
        "selected_rule": selected_rule,
        "development_baseline": _development_summary(),
        "general_unseen_reference": _general_unseen_summary(),
        "focused_target_race_count": len(focused_ids),
        "focused_valid_race_count": len(focused_sets),
        "focused_horse_count": len(horse_rows),
        "focused_race_ids": sorted(row.get("race_id") for row in focused_sets),
        "requested_race_ids": focused_ids,
        "missing_race_count": inventory_diag.get("missing_race_count", 0),
        "baseline_conflict_count": inventory_diag.get("baseline_conflict_count", 0),
        "review_required_race_count": inventory_diag.get("review_required_count", 0),
        "incomplete_race_count": inventory_diag.get("incomplete_count", 0),
        "focused_subset_of_general": inventory_diag.get("focused_subset_of_general", False),
        "general_unseen_race_count": inventory_diag.get("general_unseen_race_count", 0),
        "production_metrics": production,
        "shadow_metrics": shadow,
        "metric_delta": delta,
        "removed_buy": len(removed),
        "removed_fp": removed_fp,
        "removed_successful_buy": removed_success,
        "removed_successful_buy_horses": [
            {"race_id": row.get("race_id"), "horse_name": row.get("horse_name"), "finish_position": row.get("finish_position")}
            for row in removed
            if row.get("is_top3")
        ],
        "new_buy": len(new_buy),
        "new_successful_buy": sum(1 for row in new_buy if row.get("is_top3")),
        "new_false_positive": sum(1 for row in new_buy if not row.get("is_top3")),
        "place_rate_delta": delta["buy_place_rate"],
        "condition_summary": condition_summary,
        "focused_validation_status": status,
        "focused_final_decision": final_decision,
        "focused_final_reason": reason,
        "production_buy_diff": 0,
        "score_diff": 0,
        "decision_diff": 0,
        "race_state_diff": 0,
        "candidate_duplicate": 0,
        "project_duplicate": 0,
        "warnings": inventory_diag.get("warnings", []),
        "errors": errors,
    }

    _write_csv(FOCUSED_OUT_DIR / "focused_horse_results.csv", horse_rows, HORSE_FIELDS)
    _write_csv(FOCUSED_OUT_DIR / "focused_removed_buy.csv", removed, HORSE_FIELDS)
    _write_csv(FOCUSED_OUT_DIR / "focused_kept_buy.csv", kept, HORSE_FIELDS)
    _write_csv(FOCUSED_OUT_DIR / "focused_race_comparison.csv", _race_comparison(horse_rows))
    _write_csv(FOCUSED_OUT_DIR / "focused_condition_summary.csv", condition_summary)
    _write_csv(FOCUSED_OUT_DIR / "focused_validation_errors.csv", errors)
    _write_csv(FOCUSED_OUT_DIR / "focused_validation_warnings.csv", [{"warning": warning} for warning in result["warnings"]])
    _write_json(FOCUSED_OUT_DIR / "focused_validation_summary.json", result)
    _write_json(run_dir / "focused_validation_summary.json", result)
    _write_csv(run_dir / "focused_horse_results.csv", horse_rows, HORSE_FIELDS)
    _write_csv(run_dir / "focused_removed_buy.csv", removed, HORSE_FIELDS)
    _write_csv(run_dir / "focused_kept_buy.csv", kept, HORSE_FIELDS)
    _write_csv(run_dir / "focused_race_comparison.csv", _race_comparison(horse_rows))
    _write_focused_markdown(result, removed, kept, errors)
    (run_dir / "focused_validation_summary.md").write_text(
        (FOCUSED_OUT_DIR / "focused_validation_summary.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    project_update = _update_project_focused(result)
    validator_result = {
        "result": "PASS" if not errors and status != "FOCUSED_TARGET_REVIEW_REQUIRED" else "FAIL",
        "rule_judgment": status,
        "focused_final_decision": final_decision,
        "project_update": project_update,
        "result_summary": result,
        "run_dir": str(run_dir),
    }
    _write_json(FOCUSED_OUT_DIR / "validator_result.json", validator_result)
    _write_json(run_dir / "validator_result.json", validator_result)
    return validator_result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shadow BUY FP Filter unseen validators")
    parser.add_argument("--mode", choices=["general", "focused"], default="general")
    parser.add_argument("--from-date", default="20260718")
    parser.add_argument("--to-date", default="20260726")
    parser.add_argument("--race-list-file", default="")
    parser.add_argument("--race-id", action="append", default=[])
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    if args.mode == "focused":
        output = run_focused_validation(
            race_list_file=args.race_list_file,
            race_ids=args.race_id,
            from_date=args.from_date,
            to_date=args.to_date,
        )
    else:
        output = run_validation(from_date=args.from_date, to_date=args.to_date)
    print(json.dumps(output, ensure_ascii=False, indent=2))
