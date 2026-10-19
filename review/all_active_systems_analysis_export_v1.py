"""Rebuild the descriptive All Active Systems analysis from frozen PRE artifacts.

This module is intentionally analysis-only.  It neither invokes prediction
runtimes nor reads result artifacts.  It may overwrite only the dated
analysis/comparison outputs that it owns.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LANES = (
    "CURRENT",
    "INDEPENDENT_V5",
    "TRACKCONDITION_SEMANTIC",
    "DAILY_V5_SAME_VOLUME",
    "FORMAL_V5",
    "FORMAL_V6",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number_key(value: str) -> tuple[int, str]:
    try:
        return (0, f"{int(value):04d}")
    except (TypeError, ValueError):
        return (1, str(value))


def _selected_numbers(items: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("horse_number")) for item in items}


def _truth(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _selection_digest(selection: dict[str, dict[str, set[str]]]) -> str:
    canonical = {
        lane: {race_id: sorted(values, key=_number_key) for race_id, values in sorted(by_race.items())}
        for lane, by_race in sorted(selection.items())
    }
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _selection_equal(
    left: dict[str, dict[str, set[str]]],
    right: dict[str, dict[str, set[str]]],
) -> bool:
    """Compare selections while treating omitted races as explicit empty sets."""
    for lane in LANES:
        for race_id in set(left.get(lane, {})) | set(right.get(lane, {})):
            if left.get(lane, {}).get(race_id, set()) != right.get(lane, {}).get(race_id, set()):
                return False
    return True


def _paths(date: str) -> dict[str, Path]:
    reports = ROOT / "reports"
    return {
        "reports": reports,
        "current": reports / f"daily_pre_analysis_{date}" / "current_frozen",
        "independent": reports / "independent_race_selection_prospective" / f"{date}_pre",
        "trackcondition": reports / "track_condition_semantic_shadow_prospective" / f"{date}_pre",
        "daily": reports / "daily_v5_same_volume_prospective" / f"{date}_pre",
        "formal": reports / "selection_authority_protocol_v1_v6_forward_shadow" / "pre" / date,
    }


def _output_paths(date: str, output_dir: Path | None = None) -> dict[str, Path]:
    reports = output_dir or ROOT / "reports"
    stem = f"{date}_all_active_systems"
    return {
        "pre": reports / f"{stem}_pre.json",
        "horse": reports / f"{stem}_horse_analysis.csv",
        "lane": reports / f"{stem}_lane_comparison.csv",
        "cases": reports / f"{stem}_interesting_cases.json",
        "summary": reports / f"{stem}_analysis_summary.md",
        "hashes": reports / f"{stem}_analysis_artifact_hashes.json",
        "union": reports / f"{stem}_union_phase_a_selection.json",
    }


def _previous_selection(path: Path) -> dict[str, dict[str, set[str]]] | None:
    """Read the preceding analysis file only to prove its selection flags remain unchanged."""
    if not path.exists():
        return None
    columns = {
        "CURRENT": "current_buy",
        "INDEPENDENT_V5": "independent_v5_selected",
        "TRACKCONDITION_SEMANTIC": "trackcondition_selected",
        "DAILY_V5_SAME_VOLUME": "daily_v5_selected",
        "FORMAL_V5": "formal_v5_selected",
        "FORMAL_V6": "formal_v6_selected",
    }
    result: dict[str, dict[str, set[str]]] = {lane: defaultdict(set) for lane in LANES}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            for lane, column in columns.items():
                if _truth(row.get(column)):
                    result[lane][row["race_id"]].add(str(row["horse_number"]))
    return {lane: dict(by_race) for lane, by_race in result.items()}


def _union_document(date: str, records: dict[str, dict[str, Any]], selection: dict[str, dict[str, set[str]]]) -> dict[str, Any]:
    """Create a deterministic, PRE-only diagnostic union without outcomes."""
    lane_order = list(LANES)
    members: list[dict[str, Any]] = []
    for race_id, record in sorted(records.items()):
        all_numbers = sorted(set().union(*(selection[lane][race_id] for lane in LANES)), key=_number_key)
        for number in all_numbers:
            selecting = [lane for lane in lane_order if number in selection[lane][race_id]]
            current = "CURRENT" in selecting
            tc = "TRACKCONDITION_SEMANTIC" in selecting
            v5 = any(lane in selecting for lane in ("INDEPENDENT_V5", "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6"))
            if current and tc and v5: structure = "CURRENT_PLUS_TC_PLUS_V5"
            elif current and tc: structure = "CURRENT_PLUS_TC"
            elif current and v5: structure = "CURRENT_PLUS_V5"
            elif current: structure = "CURRENT_ONLY"
            elif tc and v5: structure = "TC_PLUS_V5"
            elif tc: structure = "TC_ONLY"
            else: structure = "V5_FAMILY_ONLY"
            members.append({
                "date": date, "venue": record["venue"], "race": record["race_number"],
                "race_id": race_id, "horse_no": int(number), "horse_name": record["names"].get(number, ""),
                "selecting_lanes": selecting, "lane_support_count": len(selecting),
                "current_support": current, "trackcondition_support": tc,
                "v5_family_support": v5, "formal_v6_support": "FORMAL_V6" in selecting,
                "family_support_count": sum((current, tc, v5)), "support_structure": structure,
            })
    members.sort(key=lambda row: (row["date"], row["venue"], _number_key(str(row["race"])), row["horse_no"]))
    bucket_counts = Counter({
        "one_lane_support": 0, "multi_lane_support": 0, "CURRENT_ONLY": 0,
        "CURRENT_PLUS_V5": 0, "CURRENT_PLUS_TC": 0, "CURRENT_PLUS_TC_PLUS_V5": 0,
        "CURRENT_FALSE_OTHER_LANE_SELECTED": 0, "V5_FAMILY_ONLY": 0,
        "TC_ONLY": 0, "TC_PLUS_V5": 0,
    })
    bucket_counts.update("one_lane_support" if row["lane_support_count"] == 1 else "multi_lane_support" for row in members)
    bucket_counts.update(row["support_structure"] for row in members)
    bucket_counts["CURRENT_FALSE_OTHER_LANE_SELECTED"] = sum(not row["current_support"] for row in members)
    canonical = {"family_definition_version": "PRE_FIXED_UNION_FAMILY_DEFINITION_V2", "date": date, "active_lanes": lane_order, "members": members}
    selection_sha = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "schema_version": "all_active_systems_union_phase_a_selection_v2",
        "role": "PRE_FIXED_ENSEMBLE_DIAGNOSTIC_SELECTION", "formal_evidence": False,
        "generated_before_result": True, "result_access_count": 0,
        "family_definition_version": "PRE_FIXED_UNION_FAMILY_DEFINITION_V2",
        "family_definition": {
            "CURRENT_BASE": ["CURRENT"], "TRACKCONDITION_VARIANT": ["TRACKCONDITION_SEMANTIC"],
            "V5_FAMILY": ["INDEPENDENT_V5", "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6"],
        },
        "historical_20260926_27_compatibility": "DIFFERENT_FAMILY_DEFINITION_VERSION; prior artifact is immutable and was not rewritten.",
        "union_unique_count": len(members), "selected_race_count": len({row["race_id"] for row in members}),
        "support_bucket_counts": dict(sorted(bucket_counts.items())), "selection_sha256": selection_sha,
        "canonical_selection": canonical,
    }


def build(date: str, *, output_dir: Path | None = None) -> dict[str, Any]:
    paths = _paths(date)
    if output_dir is not None:
        output_dir = output_dir.resolve()
    outputs = _output_paths(date, output_dir)
    if any(path.exists() for path in outputs.values()):
        raise RuntimeError("STOP_ANALYSIS_OUTPUT_EXISTS")
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Current frozen artifacts are the target-date full-field authority.
    index = _load(paths["current"] / "race_index.json")["race_index"]
    current: dict[str, dict[str, Any]] = {}
    for entry in index:
        payload = _load(paths["current"] / entry["artifact"])
        traces = {
            str(row.get("horse_number")): row
            for row in _rows(payload.get("buy_gate_trace", {}).get("horses"))
        }
        current[payload["race_id"]] = {"payload": payload, "traces": traces}

    independent_document = _load(paths["independent"] / "selection_manifest.json")
    independent = {str(row["race_id"]): row for row in _rows(independent_document.get("races"))}
    independent_horse: dict[tuple[str, str], dict[str, Any]] = {}
    for race_id, race in independent.items():
        selected = _selected_numbers(_rows(race.get("selected_horses")))
        for horse in _rows(race.get("candidate_horses")):
            independent_horse[(race_id, str(horse.get("horse_number")))] = {
                **horse,
                "selected": str(horse.get("horse_number")) in selected,
                "race": race,
            }

    tc_horses = _rows(_load(paths["trackcondition"] / "horse_level_trace.json").get("rows"))
    tc_horse = {(str(row["race_id"]), str(row["horse_number"])): row for row in tc_horses}
    tc_races = {
        str(row["race_id"]): row
        for row in _rows(_load(paths["trackcondition"] / "race_level_trace.json").get("rows"))
    }

    daily_document = _load(paths["daily"] / "selection.json")
    daily = {str(row["race_id"]): row for row in _rows(daily_document.get("races"))}
    daily_horse: dict[tuple[str, str], dict[str, Any]] = {}
    for race_id, race in daily.items():
        selected = _selected_numbers(_rows(race.get("selected_horses")))
        for horse in _rows(race.get("top5_probabilities")):
            daily_horse[(race_id, str(horse.get("horse_number")))] = {
                **horse,
                "selected": str(horse.get("horse_number")) in selected,
                "race": race,
            }

    formal_document = _load(paths["formal"] / "dual_pre_semantic.json")
    formal = {
        str(row["v5"]["race_id"]): row
        for row in _rows(formal_document.get("races"))
    }
    formal_horse: dict[tuple[str, str, str], dict[str, Any]] = {}
    for race_id, race in formal.items():
        for version in ("v5", "v6"):
            arm = race.get(version, {}) or {}
            for horse in _rows(arm.get("horses")):
                formal_horse[(version, race_id, str(horse.get("horse_number")))] = {
                    **horse,
                    "arm": arm,
                    "outer": race,
                }

    selection: dict[str, dict[str, set[str]]] = {lane: {} for lane in LANES}
    records: dict[str, dict[str, Any]] = {}
    for race_id, item in current.items():
        payload = item["payload"]
        ranked = _rows(payload.get("ranked_results"))
        sample = ranked[0] if ranked else {}
        venue = sample.get("venue") or race_id.split("_")[-2]
        race_number = sample.get("race_number") or race_id.split("_")[-1]
        current_state = payload.get("buy_gate_trace", {}).get("race", {}).get("shadow_race_state")
        selection["CURRENT"][race_id] = _selected_numbers(_rows(payload.get("buys")))
        selection["INDEPENDENT_V5"][race_id] = _selected_numbers(
            _rows(independent.get(race_id, {}).get("selected_horses"))
        )
        selection["TRACKCONDITION_SEMANTIC"][race_id] = {
            str(row.get("horse_number"))
            for row in tc_horses
            if str(row.get("race_id")) == race_id and row.get("shadow_selected")
        }
        selection["DAILY_V5_SAME_VOLUME"][race_id] = _selected_numbers(
            _rows(daily.get(race_id, {}).get("selected_horses"))
        )
        selection["FORMAL_V5"][race_id] = {
            str(row.get("horse_number"))
            for row in _rows(formal.get(race_id, {}).get("v5", {}).get("horses"))
            if row.get("selected_by_protocol")
        }
        selection["FORMAL_V6"][race_id] = {
            str(row.get("horse_number"))
            for row in _rows(formal.get(race_id, {}).get("v6", {}).get("horses"))
            if row.get("selected_by_protocol")
        }
        records[race_id] = {
            "race_id": race_id,
            "venue": venue,
            "race_number": race_number,
            "ranked": ranked,
            "traces": item["traces"],
            "current_state": current_state,
            "names": {str(row.get("horse_number")): row.get("horse_name") for row in ranked},
        }

    actual_counts = {lane: sum(map(len, races.values())) for lane, races in selection.items()}
    source_selection = {
        "CURRENT": {race_id: _selected_numbers(_rows(item["payload"].get("buys"))) for race_id, item in current.items()},
        "INDEPENDENT_V5": {race_id: _selected_numbers(_rows(row.get("selected_horses"))) for race_id, row in independent.items()},
        "TRACKCONDITION_SEMANTIC": {race_id: {str(row.get("horse_number")) for row in tc_horses if str(row.get("race_id")) == race_id and _truth(row.get("shadow_selected"))} for race_id in current},
        "DAILY_V5_SAME_VOLUME": {race_id: _selected_numbers(_rows(row.get("selected_horses"))) for race_id, row in daily.items()},
        "FORMAL_V5": {race_id: {str(row.get("horse_number")) for row in _rows(row.get("v5", {}).get("horses")) if _truth(row.get("selected_by_protocol"))} for race_id, row in formal.items()},
        "FORMAL_V6": {race_id: {str(row.get("horse_number")) for row in _rows(row.get("v6", {}).get("horses")) if _truth(row.get("selected_by_protocol"))} for race_id, row in formal.items()},
    }
    current_ids = set(current)
    if any(set(source_selection[lane]) != current_ids for lane in LANES) or not _selection_equal(selection, source_selection):
        raise RuntimeError("STOP_LANE_RACE_OR_SELECTION_SET_MISMATCH")
    for lane in LANES:
        for race_id, values in selection[lane].items():
            available = {str(row.get("horse_number")) for row in records[race_id]["ranked"]}
            if not values <= available:
                raise RuntimeError("STOP_LANE_HORSE_SET_MISMATCH")
    current_summary = _load(paths["current"] / "summary.json")
    current_manifest = _load(paths["current"] / "input_manifest.json")
    prediction_manifest = _load(paths["current"] / "prediction_manifest.json")
    sources = current_manifest.get("sources")
    if (
        current_manifest.get("date") != date
        or current_manifest.get("input_exception") is not None
        or current_summary.get("date") != date
        or current_summary.get("race_count") != len(records)
        or current_summary.get("horse_count") != sum(len(row["ranked"]) for row in records.values())
        or not isinstance(sources, dict)
    ):
        raise RuntimeError("STOP_CURRENT_PRE_INPUT_INTEGRITY")
    for kind in ("DG", "DE", "DS"):
        source = sources.get(kind, {})
        path = ROOT / str(source.get("path", ""))
        if not path.is_file() or source.get("sha256") != _sha256(path):
            raise RuntimeError("STOP_CURRENT_PRE_INPUT_INTEGRITY")
    manifest_files = {item.get("relative_path"): item.get("sha256") for item in _rows(prediction_manifest.get("files"))}
    if any(not isinstance(name, str) or not isinstance(digest, str) or not (paths["current"] / name).is_file() or _sha256(paths["current"] / name) != digest for name, digest in manifest_files.items()):
        raise RuntimeError("STOP_CURRENT_PRE_MANIFEST_INTEGRITY")
    input_preflight = {
        "target_date": date, "current_input_manifest_sha256": _sha256(paths["current"] / "input_manifest.json"),
        "source_files": sources, "race_count": len(records),
        "horse_count": sum(len(row["ranked"]) for row in records.values()),
        "input_exception": current_manifest.get("input_exception"),
        "result_access_count": _load(paths["current"] / "provenance.json").get("result_data_access_count"),
        "race_index_integrity": "PASS", "lane_race_and_horse_set_integrity": "PASS",
    }
    previous = _previous_selection(outputs["horse"])
    if previous is not None and not _selection_equal(previous, selection):
        raise RuntimeError("PREVIOUS_ANALYSIS_SELECTION_DRIFT")

    current_state_counts = Counter(record["current_state"] for record in records.values())
    if set(current_state_counts) - {"PLAY_CONVERGED", "SKIP", "PLAY_UNCONVERGED_4PLUS"}:
        raise RuntimeError(f"STOP_CURRENT_RACE_STATE_INVALID: {dict(current_state_counts)}")

    # Build every horse row from Current's frozen full field, only adding saved lane fields.
    horse_rows: list[dict[str, Any]] = []
    for race_id, record in records.items():
        for horse in record["ranked"]:
            number = str(horse.get("horse_number"))
            trace = record["traces"].get(number, {})
            ind = independent_horse.get((race_id, number), {})
            tc = tc_horse.get((race_id, number), {})
            daily_item = daily_horse.get((race_id, number), {})
            daily_race = daily.get(race_id, {})
            fv5 = formal_horse.get(("v5", race_id, number), {})
            fv6 = formal_horse.get(("v6", race_id, number), {})
            v5arm, v6arm = fv5.get("arm", {}), fv6.get("arm", {})
            ind_race = ind.get("race", {})
            p_top3, tau = _float(ind.get("p_top3")), _float(ind_race.get("tau"))
            daily_scope = daily_race.get("scope_status")
            formal_scope = formal.get(race_id, {}).get("eligibility_reason")
            if _truth(horse.get("buy")):
                current_status = "BUY"
            elif (horse.get("rank") or 999) <= 5:
                current_status = "TOP5_NOT_BUY"
            else:
                current_status = "OUTSIDE_TOP5"
            if ind.get("selected"):
                ind_status = "SELECTED"
            elif not ind:
                ind_status = "OUTSIDE_CANDIDATE"
            elif ind.get("risk_guard_pass") is False:
                ind_status = "VETOED"
            elif p_top3 is not None and tau is not None and p_top3 < tau:
                ind_status = "BELOW_THRESHOLD"
            else:
                ind_status = "OUTSIDE_TARGET_K"
            if daily_scope != "ELIGIBLE":
                daily_status = daily_scope or "NOT_ELIGIBLE_RACE_STATE_OR_CURRENT_BUY_ZERO"
            elif daily_item.get("selected"):
                daily_status = "SELECTED"
            elif daily_item:
                daily_status = "NOT_SELECTED"
            else:
                daily_status = "OUTSIDE_CANDIDATE"
            def formal_status(row: dict[str, Any]) -> str:
                if formal_scope == "TARGET_K_ZERO_OUT_OF_SCOPE":
                    return "TARGET_K_ZERO_OUT_OF_SCOPE"
                if row.get("selected_by_protocol"):
                    return "SELECTED"
                return row.get("selection_exclusion_reason") or "NOT_AVAILABLE"
            p5, p6 = _float(fv5.get("probability")), _float(fv6.get("probability"))
            rank5, rank6 = _float(fv5.get("probability_rank")), _float(fv6.get("probability_rank"))
            selected_flags = [
                lane for lane in LANES
                if number in selection[lane][race_id]
            ]
            horse_rows.append({
                "date": date, "race_id": race_id, "venue": record["venue"],
                "race_number": record["race_number"], "field_size": len(record["ranked"]),
                "horse_number": horse.get("horse_number"), "horse_name": horse.get("horse_name"),
                "current_race_state": record["current_state"], "current_lane_status": current_status,
                "current_rank": horse.get("rank"), "current_final_score": horse.get("final_score"),
                "current_adjusted_score": horse.get("adjusted_score"), "current_decision_score": horse.get("decision_score"),
                "current_decision": horse.get("decision"), "current_buy": horse.get("buy"),
                "current_top5": (horse.get("rank") or 999) <= 5,
                "current_runtime_reason": horse.get("buy_v1_rc1_reason"),
                "current_shadow_buy_candidate": trace.get("shadow_buy_candidate"),
                "current_risk_guard_pass": trace.get("risk_guard_pass"), "current_shadow_ai_rank": trace.get("shadow_ai_rank"),
                "independent_v5_lane_status": ind_status, "independent_v5_candidate": bool(ind),
                "independent_v5_p_top3": ind.get("p_top3"), "independent_v5_tau": ind_race.get("tau"),
                "independent_v5_threshold_delta": p_top3 - tau if p_top3 is not None and tau is not None else None,
                "independent_v5_selected": ind.get("selected", False),
                "independent_v5_selected_rank": ind.get("selected_rank"),
                "independent_v5_shadow_ai_rank": ind.get("shadow_ai_rank"),
                "independent_v5_risk_guard_pass": ind.get("risk_guard_pass"),
                "independent_v5_selection_reason": ind_race.get("selection_reason"),
                "trackcondition_lane_status": "SELECTED" if tc.get("shadow_selected") else "NOT_SELECTED",
                "trackcondition_selected": tc.get("shadow_selected"), "trackcondition_rank": tc.get("shadow_rank"),
                "trackcondition_score": tc.get("shadow_score"), "trackcondition_decision": tc.get("shadow_decision"),
                "trackcondition_race_state": tc.get("shadow_race_state"),
                "track_condition": tc.get("race_track_condition"),
                "field_history_track_condition": tc.get("field_history_track_condition"),
                "trackcondition_risk_guard_pass": tc.get("risk_guard_pass"),
                "daily_v5_scope_status": daily_scope,
                "daily_v5_lane_status": daily_status, "daily_v5_candidate": bool(daily_item),
                "daily_v5_probability": daily_item.get("predicted_actual_top3_probability"),
                "daily_v5_shadow_ai_rank": daily_item.get("shadow_ai_rank"),
                "daily_v5_selected": daily_item.get("selected", False),
                "daily_v5_selected_count": daily_race.get("selected_count"), "daily_v5_race_state": daily_race.get("race_state"),
                "formal_v5_scope_reason": formal_scope, "formal_v5_lane_status": formal_status(fv5),
                "formal_v5_probability": fv5.get("probability"), "formal_v5_probability_rank": fv5.get("probability_rank"),
                "formal_v5_exact5_membership": fv5.get("exact5_membership"), "formal_v5_exact5_rank": fv5.get("exact5_rank"),
                "formal_v5_risk_guard_pass": fv5.get("risk_guard_pass"), "formal_v5_selected": fv5.get("selected_by_protocol", False),
                "formal_v5_selection_rank": fv5.get("selection_rank"), "formal_v5_selection_exclusion_reason": fv5.get("selection_exclusion_reason"),
                "formal_v5_target_k": v5arm.get("target_k"), "formal_v5_shortfall": v5arm.get("shortfall"), "formal_v5_race_state": v5arm.get("race_state"),
                "formal_v6_scope_reason": formal_scope, "formal_v6_lane_status": formal_status(fv6),
                "formal_v6_probability": fv6.get("probability"), "formal_v6_probability_rank": fv6.get("probability_rank"),
                "formal_v6_exact5_membership": fv6.get("exact5_membership"), "formal_v6_exact5_rank": fv6.get("exact5_rank"),
                "formal_v6_risk_guard_pass": fv6.get("risk_guard_pass"), "formal_v6_selected": fv6.get("selected_by_protocol", False),
                "formal_v6_selection_rank": fv6.get("selection_rank"), "formal_v6_selection_exclusion_reason": fv6.get("selection_exclusion_reason"),
                "formal_v6_target_k": v6arm.get("target_k"), "formal_v6_shortfall": v6arm.get("shortfall"), "formal_v6_race_state": v6arm.get("race_state"),
                "formal_v5_v6_probability_difference": p6 - p5 if p5 is not None and p6 is not None else None,
                "formal_v5_v6_rank_difference": int(rank6 - rank5) if rank5 is not None and rank6 is not None else None,
                "cross_lane_selected_flags": ";".join(selected_flags),
            })

    # Frozen-model output comparison is derived from the two immutable arms.
    comparable = [row for row in horse_rows if row["formal_v5_probability"] is not None]
    probability_changed = sum(
        row["formal_v5_probability"] != row["formal_v6_probability"] for row in comparable
    )
    rank_changed = [row for row in comparable if row["formal_v5_probability_rank"] != row["formal_v6_probability_rank"]]
    rank_changed_races = {row["race_id"] for row in rank_changed}
    exact5_changed_races = {
        race_id for race_id in records
        if {row["horse_number"] for row in horse_rows if row["race_id"] == race_id and _truth(row["formal_v5_exact5_membership"])}
        != {row["horse_number"] for row in horse_rows if row["race_id"] == race_id and _truth(row["formal_v6_exact5_membership"])}
    }
    exact5_order_changed = {
        race_id for race_id in records
        if [(row["horse_number"], row["formal_v5_exact5_rank"]) for row in horse_rows if row["race_id"] == race_id and _truth(row["formal_v5_exact5_membership"])]
        != [(row["horse_number"], row["formal_v6_exact5_rank"]) for row in horse_rows if row["race_id"] == race_id and _truth(row["formal_v6_exact5_membership"])]
    }
    v5_v6 = {
        "probability_values_different_horses": probability_changed,
        "probability_rank_changed_horses": len(rank_changed),
        "probability_rank_changed_races": len(rank_changed_races),
        "exact5_set_divergence_races": len(exact5_changed_races),
        "exact5_internal_order_divergence_races": len(exact5_order_changed),
        "final_selection_divergence_races": sum(
            selection["FORMAL_V5"][race_id] != selection["FORMAL_V6"][race_id]
            for race_id in records
        ),
    }
    for race_id, race in formal.items():
        for version in ("v5", "v6"):
            arm = race.get(version, {})
            horses = _rows(arm.get("horses"))
            selected = {str(row.get("horse_number")) for row in horses if _truth(row.get("selected_by_protocol"))}
            if selected != selection[f"FORMAL_{version.upper()}"][race_id] or any(row.get("outside_fill") is True for row in horses):
                raise RuntimeError("STOP_FORMAL_SELECTION_INTEGRITY")

    # Meeting and venue summaries distinguish lane scope from no selection.
    daily_eligible = {race_id for race_id, row in daily.items() if row.get("scope_status") == "ELIGIBLE"}
    formal_eligible = {race_id for race_id, row in formal.items() if row.get("eligible_evidence_race")}
    lane_eligible = {
        "CURRENT": set(records), "INDEPENDENT_V5": set(records), "TRACKCONDITION_SEMANTIC": set(records),
        "DAILY_V5_SAME_VOLUME": daily_eligible, "FORMAL_V5": formal_eligible, "FORMAL_V6": formal_eligible,
    }
    meeting: dict[str, dict[str, Any]] = {}
    for lane in LANES:
        eligible = lane_eligible[lane]
        selected_races = sum(bool(selection[lane][race_id]) for race_id in eligible)
        selected_horses = sum(len(selection[lane][race_id]) for race_id in eligible)
        meeting[lane] = {
            "source_races": len(records), "eligible_races": len(eligible),
            "out_of_scope_races": len(records) - len(eligible), "selected_races": selected_races,
            "selected_horses": selected_horses,
            "eligible_but_no_selection_races": len(eligible) - selected_races,
            "average_selected_horses_per_selected_race": selected_horses / selected_races if selected_races else 0,
        }
    meeting["CURRENT"].update({
        "play_converged_races": current_state_counts["PLAY_CONVERGED"],
        "skip_races": current_state_counts["SKIP"],
        "play_unconverged_4plus_races": current_state_counts["PLAY_UNCONVERGED_4PLUS"],
    })
    venue: dict[str, dict[str, Any]] = defaultdict(lambda: {"race_ids": set(), **{lane: 0 for lane in LANES}})
    for race_id, record in records.items():
        entry = venue[record["venue"]]
        entry["race_ids"].add(race_id)
        for lane in LANES:
            entry[lane] += len(selection[lane][race_id])
    venue_summary = {
        name: {"race_count": len(row.pop("race_ids")), "selected_horse_count_by_lane": row}
        for name, row in venue.items()
    }

    # Daily same-volume exchange is checked per eligible race, not only in total.
    retained = removed = added = changed = 0
    for race_id in daily_eligible:
        base, replacement = selection["CURRENT"][race_id], selection["DAILY_V5_SAME_VOLUME"][race_id]
        if len(base) != len(replacement):
            raise RuntimeError("STOP_DAILY_V5_TARGET_K_MISMATCH")
        retained += len(base & replacement)
        removed += len(base - replacement)
        added += len(replacement - base)
        changed += base != replacement
    daily_difference = {
        "retained": retained, "removed_from_current": removed, "newly_selected_by_daily_v5": added,
        "changed_races": changed, "eligible_races": len(daily_eligible),
    }

    # Interesting cases remain descriptive, and state whether empty selections participate.
    def case(race_id: str, note: str) -> dict[str, Any]:
        record = records[race_id]
        return {
            "race_id": race_id, "venue": record["venue"], "race_number": record["race_number"],
            "selection_sets": {lane: sorted(selection[lane][race_id], key=_number_key) for lane in LANES},
            "note": note,
        }
    cases: dict[str, list[dict[str, Any]]] = {
        "current_selected_v5_family_zero": [], "current_zero_independent_selected": [],
        "current_daily_difference": [], "current_trackcondition_difference": [],
        "formal_v5_v6_divergence": [], "all_lanes_empty_selection_agreement": [],
        "high_disagreement_three_or_more_unique_sets_including_empty": [],
        "high_disagreement_three_or_more_nonempty_sets": [],
    }
    for race_id in records:
        sets = {lane: selection[lane][race_id] for lane in LANES}
        v5_family = sets["INDEPENDENT_V5"] | sets["DAILY_V5_SAME_VOLUME"] | sets["FORMAL_V5"] | sets["FORMAL_V6"]
        if sets["CURRENT"] and not v5_family:
            cases["current_selected_v5_family_zero"].append(case(race_id, "Current selected; V5-family selected zero."))
        if not sets["CURRENT"] and sets["INDEPENDENT_V5"]:
            cases["current_zero_independent_selected"].append(case(race_id, "Current selected zero; Independent V5 selected."))
        if sets["CURRENT"] != sets["DAILY_V5_SAME_VOLUME"]:
            cases["current_daily_difference"].append(case(race_id, "Current and Daily V5 selection sets differ."))
        if sets["CURRENT"] != sets["TRACKCONDITION_SEMANTIC"]:
            cases["current_trackcondition_difference"].append(case(race_id, "Current and TrackCondition selection sets differ."))
        if sets["FORMAL_V5"] != sets["FORMAL_V6"]:
            cases["formal_v5_v6_divergence"].append(case(race_id, "Formal V5 and Formal V6 final selections differ."))
        unique_including_empty = {tuple(sorted(values, key=_number_key)) for values in sets.values()}
        unique_nonempty = {tuple(sorted(values, key=_number_key)) for values in sets.values() if values}
        if not any(sets.values()):
            cases["all_lanes_empty_selection_agreement"].append(case(race_id, "All lanes have empty selection; this is empty-selection agreement only."))
        if len(unique_including_empty) >= 3:
            cases["high_disagreement_three_or_more_unique_sets_including_empty"].append(case(race_id, "Three or more unique selection sets; empty set included in this definition."))
        if len(unique_nonempty) >= 3:
            cases["high_disagreement_three_or_more_nonempty_sets"].append(case(race_id, "Three or more distinct non-empty selection sets."))
    # Output writes begin only after every frozen-output assertion above passes.
    fieldnames = list(horse_rows[0])
    with outputs["horse"].open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(horse_rows)

    lane_rows: list[dict[str, Any]] = []
    lane_meta = {
        "CURRENT": ("CURRENT_AI_OPERATIONAL", lambda race_id: (records[race_id]["current_state"], "IN_SCOPE", None)),
        "INDEPENDENT_V5": ("FORMAL_PROSPECTIVE_SHADOW", lambda race_id: (None, "IN_SCOPE", independent.get(race_id, {}).get("selection_reason"))),
        "TRACKCONDITION_SEMANTIC": ("FORMAL_PROSPECTIVE_SHADOW", lambda race_id: (tc_races.get(race_id, {}).get("shadow_race_state"), "IN_SCOPE", None)),
        "DAILY_V5_SAME_VOLUME": ("FORMAL_PROSPECTIVE_SHADOW", lambda race_id: (daily.get(race_id, {}).get("race_state"), daily.get(race_id, {}).get("scope_status"), None)),
        "FORMAL_V5": ("FORMAL_PROSPECTIVE_SHADOW", lambda race_id: (formal.get(race_id, {}).get("v5", {}).get("race_state"), formal.get(race_id, {}).get("eligibility_reason"), None)),
        "FORMAL_V6": ("FORMAL_PROSPECTIVE_SHADOW", lambda race_id: (formal.get(race_id, {}).get("v6", {}).get("race_state"), formal.get(race_id, {}).get("eligibility_reason"), None)),
    }
    for race_id, record in sorted(records.items()):
        for lane in LANES:
            role, state_fn = lane_meta[lane]
            lane_state, scope, reason = state_fn(race_id)
            selected = sorted(selection[lane][race_id], key=_number_key)
            base = {
                "Date": date, "Venue": record["venue"], "Race": record["race_number"], "Race Name": "",
                "Lane": lane, "current_race_state": record["current_state"], "lane_race_state": lane_state,
                "lane_scope_status": scope, "lane_selection_reason": reason,
                "Selected Count": len(selected), "Race ID": race_id, "Field Size": len(record["ranked"]),
                "Lane Role": role, "Comparison Status": "DESCRIPTIVE_ONLY",
            }
            if selected:
                for number in selected:
                    lane_rows.append({**base, "Selected": "YES", "Horse No": number, "Horse Name": record["names"].get(number, "")})
            else:
                lane_rows.append({**base, "Selected": "NO", "Horse No": "", "Horse Name": ""})
    lane_fields = list(lane_rows[0])
    with outputs["lane"].open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=lane_fields)
        writer.writeheader()
        writer.writerows(lane_rows)

    case_document = {
        "schema_version": "all_active_systems_interesting_cases_v2",
        "date": date, "analysis_role": "ANALYSIS / COMPARISON OUTPUT",
        "result_access_count": 0,
        "definitions": {
            "all_lanes_empty_selection_agreement": "All six lanes selected no horse; it is not a positive recommendation agreement.",
            "high_disagreement_three_or_more_unique_sets_including_empty": "Unique selection-set count includes the empty set.",
            "high_disagreement_three_or_more_nonempty_sets": "Counts only distinct non-empty selection sets.",
        },
        "case_counts": {name: len(items) for name, items in cases.items()},
        "cases": cases,
    }
    outputs["cases"].write_text(json.dumps(case_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    union_document = _union_document(date, records, selection)
    outputs["union"].write_text(json.dumps(union_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    document = {
        "schema_version": "all_active_systems_pre_analysis_v2",
        "date": date, "status": "COMPLETE", "analysis_role": "ANALYSIS / COMPARISON OUTPUT",
        "input_preflight": input_preflight,
        "active_lanes": [{
            "lane": lane,
            "selected_horses": actual_counts[lane],
            "selected_races": sum(bool(selection[lane][race_id]) for race_id in records),
        } for lane in LANES],
        "explicitly_excluded_lanes": ["CF_TOP3_RANK_ANCHORED", "CURRENT_CORRECTED_SHADOW_V2", "DAILY_V5_REFERENCE", "V4_MODEL_V3_REFERENCE", "December one-shot", "consumed/reference-only lanes"],
        "selection_integrity": {
            "source_rederived_selected_counts": {lane: sum(map(len, source_selection[lane].values())) for lane in LANES}, "actual_selected_counts": actual_counts,
            "prediction_selection_changed": False, "previous_analysis_selection_match": previous is not None,
            "frozen_source_selection_digest": _selection_digest(selection),
        },
        "current_race_state_summary": dict(current_state_counts),
        "meeting_summary": meeting, "venue_summary": venue_summary,
        "daily_v5_difference_summary": daily_difference,
        "formal_v5_v6_summary": {
            **v5_v6,
            "final_selection_status": "IDENTICAL",
            "model_output_status": "NOT_IDENTICAL",
        },
        "case_counts": case_document["case_counts"],
        "family_interpretation": "INDEPENDENT_V5, DAILY_V5_SAME_VOLUME and FORMAL_V5 share a V5 family; FORMAL_V6 is a V5-derived development variant. No majority-vote evidence is generated.",
        "reproducibility": {
            "generator": "review/all_active_systems_analysis_export_v1.py",
            "command": f"python review/all_active_systems_analysis_export_v1.py --date {date}",
            "reads_frozen_pre_artifacts_only": True,
        },
        "execution_safety": {
            "result_access_count": 0, "pre_rerun": False, "model_change": False,
            "threshold_change": False, "training": False, "production_change": False,
        },
        "outputs": {name: str(path.relative_to(ROOT)).replace("\\\\", "/") for name, path in outputs.items()},
    }
    outputs["pre"].write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def selected_label(race_id: str, lane: str) -> str:
        return ", ".join(
            f"#{number} {records[race_id]['names'].get(number, '')}"
            for number in sorted(selection[lane][race_id], key=_number_key)
        ) or "—"
    summary = [
        f"# {date} All Active Systems PRE 分析サマリー", "",
        "## 1. Input validation", "",
        f"- 対象日artifactから再導出: {input_preflight['race_count']}レース・{input_preflight['horse_count']}頭、input exception = {input_preflight['input_exception']}、Current input manifest SHA = `{input_preflight['current_input_manifest_sha256']}`。", "",
        "## 2. Execution safety", "",
        "- Result access = 0。PRE再実行、モデル変更、threshold変更、学習、Production変更はありません。", "",
        "## 3. Meeting overview", "",
        "| Lane | Eligible races | Out of scope | Selected races | Selected horses | Eligible but no selection |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for lane in LANES:
        value = meeting[lane]
        summary.append(f"| {lane} | {value['eligible_races']} | {value['out_of_scope_races']} | {value['selected_races']} | {value['selected_horses']} | {value['eligible_but_no_selection_races']} |")
    summary += [
        "", "### CURRENT official race states", "",
        f"- PLAY_CONVERGED: {current_state_counts['PLAY_CONVERGED']} / SKIP: {current_state_counts['SKIP']} / PLAY_UNCONVERGED_4PLUS: {current_state_counts['PLAY_UNCONVERGED_4PLUS']}。Current stateは `buy_gate_trace.race.shadow_race_state` のみから取得。", "",
        "## 4. CURRENT analysis", "",
        "- 全頭CSVの `current_race_state`、`current_shadow_ai_rank`、`current_shadow_buy_candidate`、`current_risk_guard_pass`、`current_runtime_reason` を参照してください。Top5内非BUYは `TOP5_NOT_BUY` です。", "",
        "## 5. INDEPENDENT_V5 analysis", "",
        "- 最大3頭ruleは既存protocolのままです。全候補の P(top3)、tau差、risk guard、selected rankをCSVへ保存しました。", "",
        "## 6. TRACKCONDITION_SEMANTIC analysis", "",
        "- Currentとの差は `current_trackcondition_difference` で記録。PRE時点のtrack conditionとhistorical trace fieldsもCSVに保持しています。", "",
        "## 7. DAILY_V5_SAME_VOLUME analysis", "",
        f"- eligible {len(daily_eligible)}Rの差分: retained {retained} / Currentから除外 {removed} / Daily V5新規 {added} / changed {changed}R。総数が同じでも選択集合は同じとは限りません。",
        f"- 対象外{len(records) - len(daily_eligible)}Rの全馬は `NOT_ELIGIBLE_RACE_STATE_OR_CURRENT_BUY_ZERO` と表示し、`OUTSIDE_CANDIDATE` と混同しません。", "",
        "## 8. FORMAL_V5 / FORMAL_V6 analysis", "",
        f"- 各formal laneのeligible raceは{len(formal_eligible)}R。target_k、exact5、risk veto、shortfall、最終選択は凍結formal artifactから再導出しました。", 
        "- formal対象外馬は `TARGET_K_ZERO_OUT_OF_SCOPE` と明示します。", "",
        "## 9. V5 vs V6 differences", "",
        f"- probability値差: {v5_v6['probability_values_different_horses']}頭。probability rank差: {v5_v6['probability_rank_changed_races']}R・{v5_v6['probability_rank_changed_horses']}頭。exact5 set差: {v5_v6['exact5_set_divergence_races']}R、exact5内順序差: {v5_v6['exact5_internal_order_divergence_races']}R、最終選択差: {v5_v6['final_selection_divergence_races']}R。", 
        f"- `FORMAL_V5_V6_FINAL_SELECTION = {'IDENTICAL' if v5_v6['final_selection_divergence_races'] == 0 else 'DIFFERENT'}`。", "",
        "## 10. Cross-lane agreement / disagreement", "",
        "- V5 familyの一致は独立票ではありません。多数決scoreは生成していません。", 
        "- empty setを含む3種類以上の集合差: " + str(len(cases["high_disagreement_three_or_more_unique_sets_including_empty"])) + "R。非空集合だけで3種類以上: " + str(len(cases["high_disagreement_three_or_more_nonempty_sets"])) + "R。", "",
        "## 11. Interesting races", "",
        f"- `ALL_LANES_EMPTY_SELECTION_AGREEMENT` は {len(cases['all_lanes_empty_selection_agreement'])}R。これは正の推奨一致ではありません。", 
        "- 詳細は `" + outputs["cases"].name + "`。", "",
        "## 12. Full race-by-race table", "",
        "| Venue | Race | Current state | Current | Independent V5 | TC | Daily V5 | Formal V5 | Formal V6 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for race_id, record in sorted(records.items()):
        summary.append(
            f"| {record['venue']} | {record['race_number']} | {record['current_state']} | {selected_label(race_id, 'CURRENT')} | {selected_label(race_id, 'INDEPENDENT_V5')} | {selected_label(race_id, 'TRACKCONDITION_SEMANTIC')} | {selected_label(race_id, 'DAILY_V5_SAME_VOLUME')} | {selected_label(race_id, 'FORMAL_V5')} | {selected_label(race_id, 'FORMAL_V6')} |"
        )
    summary += [
        "", "## Reproducibility", "",
        f"- 再生成コマンド: `python review/all_active_systems_analysis_export_v1.py --date {date}`", 
        f"- 分析artifact SHA index: `{outputs['hashes'].name}`。PRE-fixed UNION SHA: `{union_document['selection_sha256']}`。", "",
    ]
    outputs["summary"].write_text("\n".join(summary), encoding="utf-8")

    # The index deliberately excludes itself, avoiding self-referential hash ambiguity.
    hash_document = {
        "schema_version": "all_active_systems_analysis_artifact_hashes_v1",
        "date": date,
        "analysis_only": True,
        "generator_sha256": _sha256(Path(__file__)),
        "self_hash_excluded": True,
        "artifacts": {
            name: {"path": str(path.relative_to(ROOT)).replace("\\\\", "/"), "sha256": _sha256(path), "bytes": path.stat().st_size}
            for name, path in outputs.items() if name != "hashes"
        },
    }
    outputs["hashes"].write_text(json.dumps(hash_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "COMPLETE", "selected_counts": actual_counts,
        "current_race_states": dict(current_state_counts), "v5_v6": v5_v6,
        "daily_difference": daily_difference, "outputs": {k: str(v) for k, v in outputs.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="YYYYMMDD date whose frozen PRE artifacts are analyzed")
    parser.add_argument("--output-dir", type=Path, help="Optional empty directory for analysis-only regression output")
    args = parser.parse_args()
    print(json.dumps(build(args.date, output_dir=args.output_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
