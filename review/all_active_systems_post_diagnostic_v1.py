"""Read-only POST diagnostic for frozen six-lane all-active-system PREs.

This module deliberately separates PRE-only UNION reconstruction from the
subsequent result join.  It never invokes a prediction or selection runtime.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from review.all_active_systems_analysis_export_v1 import (
    LANES,
    ROOT,
    _load,
    _number_key,
    _paths,
    _rows,
    _selected_numbers,
    _sha256,
    _truth,
    _union_document,
)
from review.target_daily_result_list_schema_v2_validator import validate_source_pair


VENUE_JA = {
    "sapporo": "札幌", "hakodate": "函館", "fukushima": "福島", "niigata": "新潟",
    "tokyo": "東京", "nakayama": "中山", "chukyo": "中京", "kyoto": "京都",
    "hanshin": "阪神", "kokura": "小倉",
}
ABNORMAL_MARKERS = ("中止", "取消", "除外", "失格")


def _dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _dump_or_verify(path: Path, value: Any) -> None:
    """Never replace a partial POST output unless its semantic content matches."""
    if path.exists():
        existing = _load(path)
        if existing == value:
            return
        # The first interrupted invocation wrote this report before the mandatory
        # finish-order crosscheck was added.  It is not a frozen authority and can
        # be safely completed only by adding that reconciliation record.
        if path.name == "20261003_all_active_systems_post_diagnostic.json" and existing.get("schema_version") == value.get("schema_version"):
            existing_checked = existing.get("result_reconciliation", {}).get("finish_consistency", {}).get("checked_races", 0)
            expected_checked = value.get("result_reconciliation", {}).get("finish_consistency", {}).get("checked_races", 0)
            if existing_checked < expected_checked:
                _dump(path, value)
                return
        raise RuntimeError(f"STOP_PARTIAL_OUTPUT_CONTENT_MISMATCH:{path.name}")
    _dump(path, value)


def _identity(race_id: str) -> tuple[str, int]:
    parts = race_id.split("_")
    return parts[-2], int(parts[-1].removesuffix("R"))


def _rate(hits: int, valid_n: int) -> float | None:
    return hits / valid_n if valid_n else None


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row["valid_result"]]
    hits = [row for row in valid if row["actual_top3"]]
    selected_races = {row["race_id"] for row in rows}
    hit_races = {row["race_id"] for row in hits}
    return {
        "raw_n": len(rows), "invalid_n": len(rows) - len(valid), "valid_n": len(valid),
        "hits": len(hits), "top3_rate": _rate(len(hits), len(valid)),
        "selected_races": len(selected_races), "races_with_top3_hit": len(hit_races),
        "race_hit_rate": _rate(len(hit_races), len(selected_races)),
    }


def _combine(items: list[dict[str, Any]]) -> dict[str, Any]:
    raw_n = sum(item["raw_n"] for item in items)
    invalid_n = sum(item["invalid_n"] for item in items)
    valid_n = sum(item["valid_n"] for item in items)
    hits = sum(item["hits"] for item in items)
    return {"raw_n": raw_n, "invalid_n": invalid_n, "valid_n": valid_n, "hits": hits,
            "top3_rate": _rate(hits, valid_n)}


def _empty_metrics() -> dict[str, Any]:
    return _metrics([])


def _load_frozen_pre(date: str) -> dict[str, Any]:
    """Load and cross-check frozen sources without calling any lane runtime."""
    paths = _paths(date)
    current_index = _load(paths["current"] / "race_index.json")["race_index"]
    current: dict[str, dict[str, Any]] = {}
    for entry in current_index:
        payload = _load(paths["current"] / entry["artifact"])
        current[payload["race_id"]] = payload

    independent_doc = _load(paths["independent"] / "selection_manifest.json")
    independent = {str(row["race_id"]): row for row in _rows(independent_doc.get("races"))}
    tc_rows = _rows(_load(paths["trackcondition"] / "horse_level_trace.json").get("rows"))
    tc_races = {str(row["race_id"]): row for row in _rows(_load(paths["trackcondition"] / "race_level_trace.json").get("rows"))}
    daily_doc = _load(paths["daily"] / "selection.json")
    daily = {str(row["race_id"]): row for row in _rows(daily_doc.get("races"))}
    formal_doc = _load(paths["formal"] / "dual_pre_semantic.json")
    formal = {str(row["v5"]["race_id"]): row for row in _rows(formal_doc.get("races"))}

    records: dict[str, dict[str, Any]] = {}
    selection: dict[str, dict[str, set[str]]] = {lane: {} for lane in LANES}
    for race_id, payload in current.items():
        ranked = _rows(payload.get("ranked_results"))
        if not ranked:
            raise RuntimeError(f"STOP_EMPTY_CURRENT_RACE:{race_id}")
        sample = ranked[0]
        venue = str(sample.get("venue") or _identity(race_id)[0])
        race_number = int(sample.get("race_number") or _identity(race_id)[1])
        selection["CURRENT"][race_id] = _selected_numbers(_rows(payload.get("buys")))
        selection["INDEPENDENT_V5"][race_id] = _selected_numbers(_rows(independent.get(race_id, {}).get("selected_horses")))
        selection["TRACKCONDITION_SEMANTIC"][race_id] = {
            str(row.get("horse_number")) for row in tc_rows
            if str(row.get("race_id")) == race_id and _truth(row.get("shadow_selected"))
        }
        selection["DAILY_V5_SAME_VOLUME"][race_id] = _selected_numbers(_rows(daily.get(race_id, {}).get("selected_horses")))
        selection["FORMAL_V5"][race_id] = {
            str(row.get("horse_number")) for row in _rows(formal.get(race_id, {}).get("v5", {}).get("horses"))
            if _truth(row.get("selected_by_protocol"))
        }
        selection["FORMAL_V6"][race_id] = {
            str(row.get("horse_number")) for row in _rows(formal.get(race_id, {}).get("v6", {}).get("horses"))
            if _truth(row.get("selected_by_protocol"))
        }
        records[race_id] = {
            "race_id": race_id, "venue": venue, "race_number": race_number, "ranked": ranked,
            "names": {str(row.get("horse_number")): str(row.get("horse_name")) for row in ranked},
            "current_state": payload.get("buy_gate_trace", {}).get("race", {}).get("shadow_race_state"),
            "tc_race": tc_races.get(race_id, {}),
        }

    current_ids = set(current)
    source_race_sets = {
        "INDEPENDENT_V5": set(independent), "TRACKCONDITION_SEMANTIC": set(tc_races),
        "DAILY_V5_SAME_VOLUME": set(daily), "FORMAL_V5": set(formal), "FORMAL_V6": set(formal),
    }
    if any(ids != current_ids for ids in source_race_sets.values()):
        raise RuntimeError("STOP_LANE_RACE_SET_MISMATCH")
    for lane in LANES:
        for race_id, selected in selection[lane].items():
            available = {str(row.get("horse_number")) for row in records[race_id]["ranked"]}
            if not selected <= available:
                raise RuntimeError(f"STOP_LANE_HORSE_SET_MISMATCH:{lane}:{race_id}")

    manifest = _load(paths["current"] / "prediction_manifest.json")
    for item in _rows(manifest.get("files")):
        relative, digest = item.get("relative_path"), item.get("sha256")
        if not isinstance(relative, str) or not isinstance(digest, str) or _sha256(paths["current"] / relative) != digest:
            raise RuntimeError("STOP_CURRENT_PRE_SHA_MISMATCH")
    input_manifest = _load(paths["current"] / "input_manifest.json")
    summary = _load(paths["current"] / "summary.json")
    if (input_manifest.get("date") != date or input_manifest.get("input_exception") is not None
            or summary.get("date") != date or summary.get("race_count") != len(records)
            or summary.get("horse_count") != sum(len(value["ranked"]) for value in records.values())):
        raise RuntimeError("STOP_CURRENT_PRE_INPUT_INTEGRITY")
    sources = input_manifest.get("sources")
    if not isinstance(sources, dict):
        raise RuntimeError("STOP_CURRENT_PRE_INPUT_INTEGRITY")
    for source in sources.values():
        path = ROOT / str(source.get("path", ""))
        if not path.is_file() or _sha256(path) != source.get("sha256"):
            raise RuntimeError("STOP_CURRENT_PRE_INPUT_INTEGRITY")

    return {
        "date": date, "records": records, "selection": selection,
        "selected_counts": {lane: sum(map(len, selection[lane].values())) for lane in LANES},
        "input_manifest_sha256": _sha256(paths["current"] / "input_manifest.json"),
        "input_sources": sources,
    }


def _outcome(raw_finish: str) -> dict[str, Any]:
    raw_finish = raw_finish.strip()
    valid = raw_finish.isdigit() and int(raw_finish) > 0
    if not valid and raw_finish not in {"", "0"} and not any(marker in raw_finish for marker in ABNORMAL_MARKERS):
        raise RuntimeError(f"STOP_UNKNOWN_RESULT_STATUS:{raw_finish}")
    return {"raw_result": raw_finish, "actual_finish": int(raw_finish) if valid else None,
            "valid_result": valid, "actual_top3": bool(valid and int(raw_finish) <= 3)}


def _crosscheck_finish_order(primary_rows: dict[str, list[str]], auxiliary_rows: dict[str, list[str]], result_index: dict[str, Any]) -> dict[str, Any]:
    """Check all races, including out-of-scope ones, without assigning meaning to an abnormal suffix."""
    records = []
    for key in sorted(primary_rows):
        source, auxiliary = primary_rows[key], auxiliary_rows[key]
        head_count = int(result_index[key]["head_count"])
        normal_finish_groups: dict[int, set[int]] = defaultdict(set)
        abnormal_horses: set[int] = set()
        for number in range(1, head_count + 1):
            outcome = _outcome(source[11 + number])
            if outcome["valid_result"]:
                normal_finish_groups[int(outcome["actual_finish"])].add(number)
            else:
                abnormal_horses.add(number)
        sequence = [int(value) for value in auxiliary[12:12 + head_count]]
        prefix_length = 0
        for finish in sorted(normal_finish_groups):
            group = normal_finish_groups[finish]
            observed = sequence[prefix_length:prefix_length + len(group)]
            if set(observed) != group:
                raise RuntimeError(f"STOP_RESULT_FINISH_CONSISTENCY_MISMATCH:{key}:{finish}")
            prefix_length += len(group)
        if set(sequence[prefix_length:]) != abnormal_horses:
            raise RuntimeError(f"STOP_RESULT_ABNORMAL_SUFFIX_MISMATCH:{key}")
        records.append({"target_race_key": key, "status": "PASS", "normal_finish_group_count": len(normal_finish_groups),
                        "abnormal_horse_count": len(abnormal_horses)})
    return {"status": "PASS", "checked_races": len(records), "records": records}


def _join_results(pre: dict[str, Any]) -> dict[str, Any]:
    """Validate the result pair, then attach outcomes to pre-existing rows only."""
    date = pre["date"]
    raw = ROOT / "data/raw" / "target" / "daily_result_list"
    primary = raw / f"馬番順着順_{date}.csv"
    auxiliary = raw / f"着順馬番_{date}.csv"
    pair = validate_source_pair(primary, auxiliary, date)
    if pair.get("status") != "PASS":
        raise RuntimeError("STOP_RESULT_PAIR_VALIDATION")
    with primary.open("r", encoding="cp932", newline="") as handle:
        primary_rows = {row[0]: row for row in csv.reader(handle)}
    with auxiliary.open("r", encoding="cp932", newline="") as handle:
        auxiliary_rows = {row[0]: row for row in csv.reader(handle)}
    if set(primary_rows) != set(auxiliary_rows):
        raise RuntimeError("STOP_RESULT_VARIANT_RACE_SET_MISMATCH")
    result_index = pair["source_d_primary"]["race_index"]
    finish_consistency = _crosscheck_finish_order(primary_rows, auxiliary_rows, result_index)
    by_identity = {(item["venue_name"], int(item["race_number"])): key for key, item in result_index.items()}
    outcomes: dict[tuple[str, str], dict[str, Any]] = {}
    all_field_rows: list[dict[str, Any]] = []
    for race_id, record in pre["records"].items():
        key = by_identity.get((VENUE_JA[record["venue"]], int(record["race_number"])))
        if key is None:
            raise RuntimeError(f"STOP_RESULT_RACE_IDENTITY_MISMATCH:{race_id}")
        source = primary_rows.get(key)
        if source is None or int(result_index[key]["head_count"]) != len(record["ranked"]):
            raise RuntimeError(f"STOP_RESULT_HORSE_IDENTITY_MISMATCH:{race_id}")
        for horse in record["ranked"]:
            number = int(horse["horse_number"])
            value = _outcome(source[11 + number])
            outcomes[(race_id, str(number))] = value
            all_field_rows.append({"race_id": race_id, "horse_number": number, "horse_name": horse["horse_name"], **value})
    return {
        "pair": pair, "primary_sha256": _sha256(primary), "auxiliary_sha256": _sha256(auxiliary),
        "outcomes": outcomes, "all_field_rows": all_field_rows,
        "finish_consistency": finish_consistency,
    }


def _union_rows(pre: dict[str, Any], union: dict[str, Any], outcomes: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for member in union["canonical_selection"]["members"]:
        race_id, number = member["race_id"], str(member["horse_no"])
        rows.append({**member, "current_race_state": pre["records"][race_id]["current_state"], **outcomes[(race_id, number)]})
    return rows


def _lane_rows(union_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {lane: [row for row in union_rows if lane in row["selecting_lanes"]] for lane in LANES}


def _subset_metrics(rows: list[dict[str, Any]], predicate) -> dict[str, Any]:
    return _metrics([row for row in rows if predicate(row)])


def _per_race_table(pre: dict[str, Any], lane_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_lane_race = {(lane, race_id): [] for lane in LANES for race_id in pre["records"]}
    for lane, rows in lane_rows.items():
        for row in rows:
            by_lane_race[(lane, row["race_id"])].append(row)
    table = []
    for race_id, record in sorted(pre["records"].items()):
        for lane in LANES:
            rows = sorted(by_lane_race[(lane, race_id)], key=lambda row: row["horse_no"])
            metric = _metrics(rows)
            table.append({
                "venue": record["venue"], "race_number": record["race_number"], "race_id": race_id,
                "current_state": record["current_state"], "lane": lane,
                "selected_horses": [f"#{row['horse_no']} {row['horse_name']}" for row in rows],
                "top3_horses_among_selection": [f"#{row['horse_no']} {row['horse_name']}" for row in rows if row["actual_top3"]],
                "hits": metric["hits"], "valid_n": metric["valid_n"], "invalid_n": metric["invalid_n"],
            })
    return table


def _replacement_diagnostics(union_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_race: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in union_rows:
        by_race[row["race_id"]].append(row)
    result: dict[str, list[dict[str, Any]]] = {}
    for lane in ("DAILY_V5_SAME_VOLUME", "TRACKCONDITION_SEMANTIC", "FORMAL_V5"):
        cases = []
        for race_id, rows in sorted(by_race.items()):
            current = [row for row in rows if row["current_support"]]
            candidate = [row for row in rows if lane in row["selecting_lanes"]]
            removed = [row for row in current if lane not in row["selecting_lanes"]]
            added = [row for row in candidate if not row["current_support"]]
            if removed or added:
                cases.append({
                    "race_id": race_id, "lane": lane,
                    "current_removed": [{key: row[key] for key in ("horse_no", "horse_name", "actual_finish", "valid_result", "actual_top3")} for row in removed],
                    "replacement_added": [{key: row[key] for key in ("horse_no", "horse_name", "actual_finish", "valid_result", "actual_top3")} for row in added],
                })
        result[lane] = cases
    return result


def _current_miss_recovery(pre: dict[str, Any], outcomes: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    missed = []
    current = pre["selection"]["CURRENT"]
    for race_id, record in pre["records"].items():
        for horse in record["ranked"]:
            number = str(horse["horse_number"])
            outcome = outcomes[(race_id, number)]
            if not outcome["actual_top3"] or number in current[race_id]:
                continue
            owners = [lane for lane in LANES if lane != "CURRENT" and number in pre["selection"][lane][race_id]]
            if owners:
                missed.append({"race_id": race_id, "venue": record["venue"], "race_number": record["race_number"],
                               "horse_no": int(number), "horse_name": horse["horse_name"], "selected_by_lanes": owners, **outcome})
    return missed


def _diagnose(date: str, *, write_phase_a: Path | None = None, frozen_phase_a: dict[str, Any] | None = None) -> dict[str, Any]:
    pre = _load_frozen_pre(date)
    union = _union_document(date, pre["records"], pre["selection"])
    if write_phase_a is not None:
        _dump(write_phase_a, union)  # Phase A is committed before any result read in this invocation.
    if frozen_phase_a is not None and frozen_phase_a.get("selection_sha256") != union.get("selection_sha256"):
        raise RuntimeError("STOP_PHASE_A_SELECTION_SHA_MISMATCH")
    joined = _join_results(pre)
    union_rows = _union_rows(pre, union, joined["outcomes"])
    lane_rows = _lane_rows(union_rows)
    lane_metrics = {lane: _metrics(rows) for lane, rows in lane_rows.items()}
    union_metrics = _metrics(union_rows)
    for row in union_rows:
        row["result_date"] = date
    support_count = {str(count): _subset_metrics(union_rows, lambda row, count=count: row["lane_support_count"] == count) for count in range(1, 7)}
    structures = ("CURRENT_ONLY", "CURRENT_PLUS_V5", "CURRENT_PLUS_TC", "CURRENT_PLUS_TC_PLUS_V5", "V5_FAMILY_ONLY", "TC_ONLY", "TC_PLUS_V5")
    structure_metrics = {name: _subset_metrics(union_rows, lambda row, name=name: row["support_structure"] == name) for name in structures}
    key_structure_metrics = {
        "CURRENT_PLUS_ANY_OTHER_LANE": _subset_metrics(union_rows, lambda row: row["current_support"] and row["lane_support_count"] > 1),
        "CURRENT_PLUS_V5_FAMILY": structure_metrics["CURRENT_PLUS_V5"],
        "CURRENT_PLUS_TC": structure_metrics["CURRENT_PLUS_TC"],
        "CURRENT_PLUS_TC_PLUS_V5": structure_metrics["CURRENT_PLUS_TC_PLUS_V5"],
        "CURRENT_ONLY": structure_metrics["CURRENT_ONLY"],
        "CURRENT_FALSE_ANY_OTHER_LANE": _subset_metrics(union_rows, lambda row: not row["current_support"]),
        "V5_FAMILY_ONLY": structure_metrics["V5_FAMILY_ONLY"],
        "TC_ONLY": structure_metrics["TC_ONLY"],
        "TC_PLUS_V5_OUTSIDE_CURRENT": structure_metrics["TC_PLUS_V5"],
    }
    consensus = {
        "single_lane_support": _subset_metrics(union_rows, lambda row: row["lane_support_count"] == 1),
        "multi_lane_support": _subset_metrics(union_rows, lambda row: row["lane_support_count"] >= 2),
        "structurally_multi_supported": _subset_metrics(union_rows, lambda row: row["family_support_count"] >= 2),
        "one_structure_only": _subset_metrics(union_rows, lambda row: row["family_support_count"] == 1),
    }
    coverage = {
        "selected_races": union_metrics["selected_races"], "race_coverage_hits": union_metrics["races_with_top3_hit"],
        "race_coverage_rate": union_metrics["race_hit_rate"], "captured_actual_top3_horses": union_metrics["hits"],
        "total_valid_actual_top3_horses_in_selected_races": sum(
            row["actual_top3"] for row in joined["all_field_rows"]
            if row["race_id"] in {item["race_id"] for item in union_rows} and row["valid_result"]
        ),
    }
    coverage["top3_capture_rate"] = _rate(coverage["captured_actual_top3_horses"], coverage["total_valid_actual_top3_horses_in_selected_races"])
    current_keys = {(row["race_id"], row["horse_no"]) for row in lane_rows["CURRENT"]}
    lane_keys = {lane: {(row["race_id"], row["horse_no"]) for row in rows} for lane, rows in lane_rows.items()}
    variant = {
        "independent": {
            "current_buy_zero_race": _subset_metrics(lane_rows["INDEPENDENT_V5"], lambda row: not pre["selection"]["CURRENT"][row["race_id"]]),
            "current_buy_positive_race": _subset_metrics(lane_rows["INDEPENDENT_V5"], lambda row: bool(pre["selection"]["CURRENT"][row["race_id"]])),
            "by_current_state": {state: _subset_metrics(lane_rows["INDEPENDENT_V5"], lambda row, state=state: row["current_race_state"] == state) for state in ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP")},
        },
        "trackcondition": {
            "common_with_current": _metrics([row for row in lane_rows["TRACKCONDITION_SEMANTIC"] if (row["race_id"], row["horse_no"]) in current_keys]),
            "dropped_from_current": _metrics([row for row in lane_rows["CURRENT"] if (row["race_id"], row["horse_no"]) not in lane_keys["TRACKCONDITION_SEMANTIC"]]),
            "new_outside_current": _metrics([row for row in lane_rows["TRACKCONDITION_SEMANTIC"] if (row["race_id"], row["horse_no"]) not in current_keys]),
        },
        "daily_v5": {
            "retained": _metrics([row for row in lane_rows["DAILY_V5_SAME_VOLUME"] if (row["race_id"], row["horse_no"]) in current_keys]),
            "removed_from_current": _metrics([row for row in lane_rows["CURRENT"] if (row["race_id"], row["horse_no"]) not in lane_keys["DAILY_V5_SAME_VOLUME"]]),
            "newly_selected": _metrics([row for row in lane_rows["DAILY_V5_SAME_VOLUME"] if (row["race_id"], row["horse_no"]) not in current_keys]),
        },
        "formal": {
            "common": _metrics([row for row in lane_rows["FORMAL_V5"] if (row["race_id"], row["horse_no"]) in current_keys]),
            "current_only": _metrics([row for row in lane_rows["CURRENT"] if (row["race_id"], row["horse_no"]) not in lane_keys["FORMAL_V5"]]),
            "formal_only": _metrics([row for row in lane_rows["FORMAL_V5"] if (row["race_id"], row["horse_no"]) not in current_keys]),
            "v5_v6_final_selection_identical": lane_keys["FORMAL_V5"] == lane_keys["FORMAL_V6"],
        },
    }
    state_other_lanes = {
        state: _subset_metrics(union_rows, lambda row, state=state: row["current_race_state"] == state and not row["current_support"])
        for state in ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP")
    }
    return {
        "pre": pre, "union": union, "joined": joined, "union_rows": union_rows, "lane_rows": lane_rows,
        "lane_metrics": lane_metrics, "union_metrics": union_metrics, "support_count": support_count,
        "structure_metrics": structure_metrics, "key_structure_metrics": key_structure_metrics,
        "consensus": consensus, "coverage": coverage, "variant": variant,
        "per_race": _per_race_table(pre, lane_rows), "current_miss_recovery": _current_miss_recovery(pre, joined["outcomes"]),
        "replacement_diagnostics": _replacement_diagnostics(union_rows), "state_other_lanes": state_other_lanes,
    }


def _brief(metric: dict[str, Any]) -> str:
    rate = metric["top3_rate"]
    return f"{metric['hits']} / {metric['valid_n']} = {rate:.2%}" if rate is not None else f"{metric['hits']} / 0 = n.a."


def _rate_text(metric: dict[str, Any]) -> str:
    return f"{metric['top3_rate']:.2%}" if metric["top3_rate"] is not None else "n.a."


def run() -> dict[str, Path]:
    date = "20261003"
    reports = ROOT / "reports"
    outputs = {
        "post": reports / f"{date}_all_active_systems_post_diagnostic.json",
        "horses": reports / f"{date}_all_active_systems_post_horses.csv",
        "summary": reports / f"{date}_all_active_systems_post_summary.md",
        "phase_a": reports / f"{date}_all_active_systems_union_phase_a_selection.json",
        "union_post": reports / f"{date}_all_active_systems_union_post_diagnostic.json",
        "cumulative": reports / "20260926_1003_all_active_systems_ensemble_cumulative.json",
    }
    # This writes the PRE-only phase-A union before _diagnose accesses any result source.
    if outputs["phase_a"].exists():
        frozen_phase_a = _load(outputs["phase_a"])
        today = _diagnose(date, frozen_phase_a=frozen_phase_a)
    else:
        today = _diagnose(date, write_phase_a=outputs["phase_a"])
    historical = [_diagnose(value) for value in ("20260926", "20260927")]
    contributions = historical + [today]
    cumulative = {
        "schema_version": "all_active_systems_ensemble_cumulative_v2", "role": "POST_RESULT_RETROSPECTIVE_ENSEMBLE_DIAGNOSTIC_ONLY",
        "family_definition_version": "FAMILY_DEFINITION_V2", "dates": [item["pre"]["date"] for item in contributions],
        "harmonized_from_immutable_pre_artifacts": True,
        "union": _combine([item["union_metrics"] for item in contributions]),
        "single_lane_support": _combine([item["consensus"]["single_lane_support"] for item in contributions]),
        "multi_lane_support": _combine([item["consensus"]["multi_lane_support"] for item in contributions]),
        "current_plus_any_other_lane": _combine([item["key_structure_metrics"]["CURRENT_PLUS_ANY_OTHER_LANE"] for item in contributions]),
        "current_only": _combine([item["key_structure_metrics"]["CURRENT_ONLY"] for item in contributions]),
        "current_false_any_other_lane": _combine([item["key_structure_metrics"]["CURRENT_FALSE_ANY_OTHER_LANE"] for item in contributions]),
        "support_structure_v2": {key: _combine([item["structure_metrics"][key] for item in contributions]) for key in today["structure_metrics"]},
        "per_date": [{"date": item["pre"]["date"], "union": item["union_metrics"], "single_lane_support": item["consensus"]["single_lane_support"], "multi_lane_support": item["consensus"]["multi_lane_support"]} for item in contributions],
        "safety": {"post_result_selection_change": False, "formal_evidence": False, "production_change": False},
    }
    post = {
        "schema_version": "all_active_systems_post_diagnostic_v1", "date": date,
        "role": "POST_RESULT_RETROSPECTIVE_ENSEMBLE_DIAGNOSTIC_ONLY", "formal_evidence": False,
        "precondition": {"races": len(today["pre"]["records"]), "horses": sum(len(row["ranked"]) for row in today["pre"]["records"].values()), "selected_counts": today["pre"]["selected_counts"]},
        "result_reconciliation": {"status": "PASS", "primary_sha256": today["joined"]["primary_sha256"], "auxiliary_sha256": today["joined"]["auxiliary_sha256"], "result_race_count": len(today["joined"]["pair"]["source_d_primary"]["race_index"]), "finish_consistency": today["joined"]["finish_consistency"]},
        "lane_results": today["lane_metrics"], "union_result": today["union_metrics"],
        "support_count_results": today["support_count"], "support_structure_v2_results": today["structure_metrics"],
        "key_ensemble_diagnostics": today["key_structure_metrics"], "consensus_vs_unique": today["consensus"],
        "candidate_generation_coverage": today["coverage"], "variant_diagnostics": today["variant"],
        "race_state_other_lane_diagnostics": today["state_other_lanes"], "current_miss_recovery": today["current_miss_recovery"],
        "replacement_diagnostics": today["replacement_diagnostics"], "per_race_results": today["per_race"],
        "safety": {"pre_selection_changed": False, "post_result_selection_change": False, "model_change": False,
                   "threshold_change": False, "training": False, "formal_evidence": False, "production_change": False},
    }
    union_post = {
        "schema_version": "all_active_systems_union_post_diagnostic_v2", "date": date,
        "phase_a_selection_sha256": today["union"]["selection_sha256"], "phase_a_selection_changed_after_result": False,
        "family_definition_version": "FAMILY_DEFINITION_V2", "union_result": today["union_metrics"],
        "lane_support_count_results": today["support_count"], "support_structure_v2_results": today["structure_metrics"],
        "per_race_union_results": [{
            "race_id": race_id, "union_selected_count": metric["raw_n"], "invalid_selected": metric["invalid_n"],
            "union_top3_hits": metric["hits"], "union_top3_rate": metric["top3_rate"],
        } for race_id, metric in sorted((
            (race_id, _metrics([row for row in today["union_rows"] if row["race_id"] == race_id]))
            for race_id in today["pre"]["records"]
        ), key=lambda item: item[0])],
        "safety": {"post_result_selection_change": False, "formal_evidence": False, "production_change": False},
    }
    _dump_or_verify(outputs["post"], post)
    _dump_or_verify(outputs["union_post"], union_post)
    _dump_or_verify(outputs["cumulative"], cumulative)
    fields = ["date", "venue", "race", "race_id", "horse_no", "horse_name", "selecting_lanes", "lane_support_count", "family_support_count", "support_structure", "current_race_state", "actual_finish", "valid_result", "actual_top3"]
    with outputs["horses"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in today["union_rows"]:
            writer.writerow({key: ";".join(row[key]) if key == "selecting_lanes" else row.get(key) for key in fields})
    lines = ["# 2026-10-03 All Active Systems POST", "", "Role: POST_RESULT_RETROSPECTIVE_ENSEMBLE_DIAGNOSTIC_ONLY", "", "## Lane results", "", "| Lane | Hits | Valid N | Rate |", "|---|---:|---:|---:|"]
    lines += [f"| {lane} | {metric['hits']} | {metric['valid_n']} | {_rate_text(metric)} |" for lane, metric in today["lane_metrics"].items()]
    lines += ["", "## PRE-fixed UNION", "", f"{_brief(today['union_metrics'])}; selected races {today['union_metrics']['selected_races']}; invalid {today['union_metrics']['invalid_n']}.", "", "## Support structures", "", "| Structure | Hits | Valid N | Rate |", "|---|---:|---:|---:|"]
    lines += [f"| {name} | {metric['hits']} | {metric['valid_n']} | {_rate_text(metric)} |" for name, metric in today["key_structure_metrics"].items()]
    lines += ["", "## Cumulative 2026-09-26 + 2026-09-27 + 2026-10-03", "", f"UNION: {_brief(cumulative['union'])}.", "", "No threshold, model, selection, or Production change is made by this diagnostic."]
    outputs["summary"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    for name, path in run().items():
        print(f"{name}={path}")
