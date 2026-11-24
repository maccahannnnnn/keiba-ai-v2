"""2026-10-04 pre-registered forward ensemble diagnostic.

The runner verifies the pre-registration and frozen PRE sources before it
opens the Result pair.  It joins outcomes only to the already fixed six-lane
selection and pre-defined H1--H5 populations.  It does not invoke prediction,
selection, model, threshold, or Production code.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from review.all_active_systems_analysis_export_v1 import LANES, ROOT, _load, _sha256
from review.all_active_systems_post_diagnostic_v1 import (
    _combine,
    _join_results,
    _load_frozen_pre,
    _metrics,
    _rate,
    _union_rows,
)


DATE = "20261004"
REPORTS = ROOT / "reports"
PREREG_SHA = "7573af49fb83b9c8e7b63783fbae29ff7c992cef8a4b88af34e332584eba3960"
UNION_SHA = "9e3b3f78c500d6ea55a6c87ea1fc144e20aedfd0c8adf1e49729c17f38804b64"
STRUCTURES = (
    "CURRENT_ONLY",
    "CURRENT_PLUS_V5",
    "CURRENT_PLUS_TC",
    "CURRENT_PLUS_TC_PLUS_V5",
    "V5_FAMILY_ONLY",
    "TC_ONLY",
    "TC_PLUS_V5",
)


def _dump_exclusive(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _csv_exclusive(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ";".join(row[key]) if isinstance(row.get(key), list) else row.get(key) for key in fields})


def _truth(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def _by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["race_id"], str(row["horse_no"])): row for row in rows}


def _brief(metric: dict[str, Any]) -> str:
    rate = metric.get("top3_rate")
    return f"{metric['hits']} / {metric['valid_n']} = {rate:.2%}" if rate is not None else f"{metric['hits']} / 0 = n.a."


def _rate_text(metric: dict[str, Any]) -> str:
    return f"{metric['top3_rate']:.2%}" if metric.get("top3_rate") is not None else "n.a."


def _metric_rows(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    return _metrics([row for row in rows if predicate(row)])


def _direction(hypothesis: str, *, left: dict[str, Any] | None = None, right: dict[str, Any] | None = None) -> str:
    """Return only the directional labels pre-authorized by the protocol."""
    if hypothesis in {"H1", "H2"}:
        metric = left or _metrics([])
        if metric["valid_n"] == 0:
            return "INCONCLUSIVE"
        if hypothesis == "H1":
            return "NOT_SUPPORTED_THIS_DATE" if metric["hits"] else "SUPPORTED_THIS_DATE"
        return "SUPPORTED_THIS_DATE" if metric["hits"] else "NOT_SUPPORTED_THIS_DATE"
    if hypothesis in {"H3", "H4"}:
        if left is None or right is None or left["valid_n"] == 0 or right["valid_n"] == 0:
            return "INCONCLUSIVE"
        if left["top3_rate"] > right["top3_rate"]:
            return "SUPPORTED_THIS_DATE"
        if left["top3_rate"] < right["top3_rate"]:
            return "NOT_SUPPORTED_THIS_DATE"
        return "INCONCLUSIVE"
    # H5 pre-registered no numerical boundary for "large share".  A one-day
    # rate therefore cannot support or refute it without inventing a threshold.
    return "INCONCLUSIVE"


def _verify_preregistration() -> tuple[dict[str, Any], dict[str, Any]]:
    prereg_path = REPORTS / "20261004_ensemble_hypothesis_preregistration_v1.json"
    union_path = REPORTS / "20261004_all_active_systems_union_phase_a_selection.json"
    prereg = _load(prereg_path)
    union = _load(union_path)
    if _sha256(prereg_path) != PREREG_SHA:
        raise RuntimeError("STOP_PREREGISTRATION_SHA_MISMATCH")
    if prereg.get("source_union", {}).get("selection_sha256") != UNION_SHA or union.get("selection_sha256") != UNION_SHA:
        raise RuntimeError("STOP_UNION_SELECTION_SHA_MISMATCH")
    if prereg.get("result_free_preconditions", {}).get("result_access_count") != 0:
        raise RuntimeError("STOP_PREREGISTRATION_NOT_RESULT_FREE")
    for source in prereg.get("source_pre_artifacts", []):
        path = ROOT / str(source.get("relative_path", ""))
        if not path.is_file() or _sha256(path) != source.get("sha256"):
            raise RuntimeError("STOP_FROZEN_PRE_SOURCE_SHA_MISMATCH")
    return prereg, union


def _verify_union_exactly_matches_pre(pre: dict[str, Any], union: dict[str, Any]) -> None:
    actual = {lane: set() for lane in LANES}
    for member in union.get("canonical_selection", {}).get("members", []):
        key = (member["race_id"], str(member["horse_no"]))
        for lane in member.get("selecting_lanes", []):
            if lane not in actual:
                raise RuntimeError("STOP_UNKNOWN_UNION_LANE")
            actual[lane].add(key)
    expected = {
        lane: {(race_id, number) for race_id, selected in pre["selection"][lane].items() for number in selected}
        for lane in LANES
    }
    if actual != expected or len(union.get("canonical_selection", {}).get("members", [])) != 28:
        raise RuntimeError("STOP_PRE_FIXED_UNION_MEMBERSHIP_MISMATCH")


def _all_field_rows(pre: dict[str, Any], joined: dict[str, Any], union_lookup: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for race_id, record in pre["records"].items():
        for horse in record["ranked"]:
            number = str(horse["horse_number"])
            selecting = [lane for lane in LANES if number in pre["selection"][lane][race_id]]
            union_row = union_lookup.get((race_id, number))
            rows.append({
                "date": DATE,
                "race_id": race_id,
                "venue": record["venue"],
                "race_number": record["race_number"],
                "horse_no": int(number),
                "horse_name": horse["horse_name"],
                "current_race_state": record["current_state"],
                "current_rank": horse.get("rank") or horse.get("final_rank") or horse.get("score_rank"),
                "selecting_lanes": selecting,
                "lane_support_count": len(selecting),
                "support_structure": union_row["support_structure"] if union_row else "UNSELECTED_BY_ALL_LANES",
                **joined["outcomes"][(race_id, number)],
            })
    return rows


def _locate(rows: list[dict[str, Any]], member: dict[str, Any]) -> dict[str, Any]:
    key = (member["race_id"], str(member.get("horse_no", member.get("horse_number"))))
    found = _by_key(rows).get(key)
    if found is None:
        raise RuntimeError(f"STOP_PREREGISTERED_MEMBER_MISSING:{key}")
    return found


def _replacement_sets(union_rows: list[dict[str, Any]], lane: str) -> dict[str, Any]:
    current = {(row["race_id"], str(row["horse_no"])) for row in union_rows if row["current_support"]}
    selected = {(row["race_id"], str(row["horse_no"])) for row in union_rows if lane in row["selecting_lanes"]}
    lookup = _by_key(union_rows)
    def members(keys: set[tuple[str, str]]) -> list[dict[str, Any]]:
        return [lookup[key] for key in sorted(keys)]
    return {
        "common": _metrics(members(current & selected)),
        "current_removed": _metrics(members(current - selected)),
        "lane_added": _metrics(members(selected - current)),
        "current_removed_members": members(current - selected),
        "lane_added_members": members(selected - current),
    }


def _coverage(rows: list[dict[str, Any]], *, lane: str | None, state: str) -> dict[str, Any]:
    subset = [
        row for row in rows
        if row["current_race_state"] == state
        and not row["selecting_lanes"].count("CURRENT")
        and (lane is None or lane in row["selecting_lanes"])
        and (lane is not None or bool(row["selecting_lanes"]))
    ]
    metric = _metrics(subset)
    metric["race_count"] = len({row["race_id"] for row in subset})
    metric["race_hit_coverage"] = _rate(metric["races_with_top3_hit"], metric["race_count"])
    return metric


def _metrics_from_historical(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _metrics(rows)


def _mixed_role_descriptive(today: dict[str, Any]) -> dict[str, Any]:
    audit_path = REPORTS / "20260926_1003_ensemble_independent_audit_package.json"
    family_path = REPORTS / "20260926_1003_harmonized_family_v2.json"
    audit, family = _load(audit_path), _load(family_path)
    dates = ["20260926", "20260927", "20261003", DATE]
    per_date: dict[str, dict[str, dict[str, Any]]] = {date: {} for date in dates}
    names = {
        "CURRENT": "CURRENT",
        "INDEPENDENT_V5": "INDEPENDENT_V5",
        "TRACKCONDITION_SEMANTIC": "TRACKCONDITION_SEMANTIC",
        "DAILY_V5_SAME_VOLUME": "DAILY_V5_SAME_VOLUME",
        "FORMAL_V5": "FORMAL_V5",
        "FORMAL_V6": "FORMAL_V6",
        "UNION": "UNION",
    }
    for date in dates[:3]:
        for label, lane in names.items():
            per_date[date][label] = audit["union_results_recomputed"][date] if label == "UNION" else audit["lane_results_recomputed"][date][lane]
        extra = family["per_date_additional_structures"][date]
        structures = family["per_date_support_structures"][date]
        per_date[date].update({
            "CURRENT_PLUS_ANY_OTHER_LANE": extra["CURRENT_PLUS_ANY_OTHER_LANE"],
            "CURRENT_ONLY": structures["CURRENT_ONLY"],
            "CURRENT_PLUS_V5": structures["CURRENT_PLUS_V5"],
            "CURRENT_PLUS_TC_PLUS_V5": structures["CURRENT_PLUS_TC_PLUS_V5"],
            "V5_FAMILY_ONLY": structures["V5_FAMILY_ONLY"],
            "TC_ONLY": structures["TC_ONLY"],
            "TC_PLUS_V5": structures["TC_PLUS_V5"],
        })
    today_metrics = today["lane_metrics"]
    for label, lane in names.items():
        per_date[DATE][label] = today["union_metrics"] if label == "UNION" else today_metrics[lane]
    per_date[DATE].update({
        "CURRENT_PLUS_ANY_OTHER_LANE": today["key_structure_metrics"]["CURRENT_PLUS_ANY_OTHER_LANE"],
        "CURRENT_ONLY": today["structure_metrics"]["CURRENT_ONLY"],
        "CURRENT_PLUS_V5": today["structure_metrics"]["CURRENT_PLUS_V5"],
        "CURRENT_PLUS_TC_PLUS_V5": today["structure_metrics"]["CURRENT_PLUS_TC_PLUS_V5"],
        "V5_FAMILY_ONLY": today["structure_metrics"]["V5_FAMILY_ONLY"],
        "TC_ONLY": today["structure_metrics"]["TC_ONLY"],
        "TC_PLUS_V5": today["structure_metrics"]["TC_PLUS_V5"],
    })
    labels = list(per_date[DATE])
    combined = {label: _combine([per_date[date][label] for date in dates]) for label in labels}

    historical_recovery = audit["current_miss_recovery"]["horses"]
    historical_unrecovered = audit["current_misses_not_recovered"]["horses"]
    today_h5 = today["h5"]
    recovery = {}
    unrecovered = {}
    for date in dates[:3]:
        recovered = [row for row in historical_recovery if row["date"] == date]
        missing = [row for row in historical_unrecovered if row["date"] == date]
        total = audit["lane_results_recomputed"][date]["CURRENT"]["hits"] + len(recovered) + len(missing)
        recovery[date] = {"hits": len(recovered), "valid_n": total, "raw_n": total, "invalid_n": 0, "top3_rate": _rate(len(recovered), total)}
        unrecovered[date] = {"hits": len(missing), "valid_n": total, "raw_n": total, "invalid_n": 0, "top3_rate": _rate(len(missing), total)}
    recovery[DATE] = {"hits": today_h5["B_CURRENT_FALSE_OTHER_LANE_SELECTED"]["count"], "valid_n": today_h5["total_valid_actual_top3_horses"], "raw_n": today_h5["total_valid_actual_top3_horses"], "invalid_n": 0, "top3_rate": today_h5["other_lane_recovery_share"]}
    unrecovered[DATE] = {"hits": today_h5["C_ALL_LANES_UNSELECTED"]["count"], "valid_n": today_h5["total_valid_actual_top3_horses"], "raw_n": today_h5["total_valid_actual_top3_horses"], "invalid_n": 0, "top3_rate": today_h5["all_lanes_unrecovered_share"]}
    combined["CURRENT_MISS_RECOVERY"] = _combine([recovery[date] for date in dates])
    combined["ALL_LANE_UNRECOVERED"] = _combine([unrecovered[date] for date in dates])
    for date in dates:
        per_date[date]["CURRENT_MISS_RECOVERY"] = recovery[date]
        per_date[date]["ALL_LANE_UNRECOVERED"] = unrecovered[date]
    return {
        "schema_version": "ensemble_mixed_role_descriptive_v1",
        "role": "MIXED_EVIDENCE_ROLE_DESCRIPTIVE_ONLY",
        "formal_evidence": False,
        "dates": dates,
        "evidence_role_by_date": {
            "20260926": "RETROSPECTIVE_DIAGNOSTIC; lane PRE selections frozen, UNION/Family V2 aggregation post-result",
            "20260927": "RETROSPECTIVE_DIAGNOSTIC; lane PRE selections frozen, UNION/Family V2 aggregation post-result",
            "20261003": "RETROSPECTIVE_DIAGNOSTIC; lane PRE selections frozen, UNION/Family V2 aggregation post-result",
            DATE: "FORWARD_PREREGISTERED; lane PRE, UNION, Family V2, and H1-H5 fixed before Result access",
        },
        "source_artifacts": {
            "historical_audit": {"relative_path": str(audit_path.relative_to(ROOT)).replace("\\", "/"), "sha256": _sha256(audit_path)},
            "historical_family": {"relative_path": str(family_path.relative_to(ROOT)).replace("\\", "/"), "sha256": _sha256(family_path)},
        },
        "per_date": per_date,
        "combined": combined,
    }


def run() -> dict[str, Path]:
    outputs = {
        "post": REPORTS / "20261004_all_active_systems_post_diagnostic.json",
        "horses": REPORTS / "20261004_all_active_systems_post_horses.csv",
        "observation": REPORTS / "20261004_ensemble_preregistered_observation_post.json",
        "summary": REPORTS / "20261004_ensemble_preregistered_observation_summary.md",
        "mixed": REPORTS / "20260926_1004_ensemble_mixed_role_descriptive.json",
        "hashes": REPORTS / "20261004_post_artifact_hashes.json",
    }
    if any(path.exists() for path in outputs.values()):
        raise RuntimeError("STOP_POST_OUTPUT_ALREADY_EXISTS")

    # Phase A: frozen pre-registration and PRE source validation only.
    prereg, union = _verify_preregistration()
    pre = _load_frozen_pre(DATE)
    expected_counts = {
        "CURRENT": 7, "INDEPENDENT_V5": 13, "TRACKCONDITION_SEMANTIC": 8,
        "DAILY_V5_SAME_VOLUME": 7, "FORMAL_V5": 7, "FORMAL_V6": 7,
    }
    if pre["selected_counts"] != expected_counts:
        raise RuntimeError("STOP_FROZEN_LANE_COUNT_MISMATCH")
    state_counts: dict[str, int] = defaultdict(int)
    for record in pre["records"].values():
        state_counts[str(record["current_state"])] += 1
    if dict(state_counts) != {"PLAY_CONVERGED": 5, "PLAY_UNCONVERGED_4PLUS": 6, "SKIP": 2}:
        raise RuntimeError("STOP_FROZEN_CURRENT_RACE_STATE_MISMATCH")
    _verify_union_exactly_matches_pre(pre, union)

    # Phase B: Result pair validation and join to the fixed population.
    joined = _join_results(pre)
    union_rows = _union_rows(pre, union, joined["outcomes"])
    if len(union_rows) != 28 or len({row["race_id"] for row in union_rows}) != 11:
        raise RuntimeError("STOP_PRE_FIXED_UNION_COUNT_MISMATCH")
    lane_rows = {lane: [row for row in union_rows if lane in row["selecting_lanes"]] for lane in LANES}
    lane_metrics = {lane: _metrics(rows) for lane, rows in lane_rows.items()}
    union_metrics = _metrics(union_rows)
    structure_metrics = {name: _metric_rows(union_rows, lambda row, name=name: row["support_structure"] == name) for name in STRUCTURES}
    preregistered_structure_counts = prereg["additional_pre_fixed_structures"]["counts"]
    if {name: structure_metrics[name]["raw_n"] for name in preregistered_structure_counts} != preregistered_structure_counts:
        raise RuntimeError("STOP_PREREGISTERED_SUPPORT_STRUCTURE_COUNT_MISMATCH")
    key_structure_metrics = {
        "CURRENT_TOTAL": lane_metrics["CURRENT"],
        "CURRENT_ONLY": structure_metrics["CURRENT_ONLY"],
        "CURRENT_PLUS_ANY_OTHER_LANE": _metric_rows(union_rows, lambda row: row["current_support"] and row["lane_support_count"] > 1),
        "CURRENT_PLUS_V5": structure_metrics["CURRENT_PLUS_V5"],
        "CURRENT_PLUS_TC": structure_metrics["CURRENT_PLUS_TC"],
        "CURRENT_PLUS_TC_PLUS_V5": structure_metrics["CURRENT_PLUS_TC_PLUS_V5"],
    }
    union_lookup = _by_key(union_rows)
    all_rows = _all_field_rows(pre, joined, union_lookup)

    hypotheses = prereg["hypotheses"]
    h1_rows = [_locate(all_rows, member) for member in hypotheses["H1_CURRENT_ONLY"]["pre_fixed_population"]]
    h2_rows = [_locate(all_rows, member) for member in hypotheses["H2_INDEPENDENT_IN_CURRENT_UNCONVERGED"]["pre_fixed_members"]]
    h3_a = [_locate(all_rows, member) for member in hypotheses["H3_TC_AGREEMENT_WITHIN_CURRENT"]["group_a_current_and_tc"]["members"]]
    h3_b = [_locate(all_rows, member) for member in hypotheses["H3_TC_AGREEMENT_WITHIN_CURRENT"]["group_b_current_not_tc"]["members"]]
    if len(h1_rows) != 1 or len(h2_rows) != 12 or len(h3_a) != 2 or len(h3_b) != 5:
        raise RuntimeError("STOP_PREREGISTERED_HYPOTHESIS_POPULATION_MISMATCH")
    h1_metric, h2_metric, h3_a_metric, h3_b_metric = _metrics(h1_rows), _metrics(h2_rows), _metrics(h3_a), _metrics(h3_b)

    h4_pairs = []
    removed_rows, added_rows = [], []
    for pair in hypotheses["H4_DAILY_V5_SAME_VOLUME_RESELECTION"]["pre_fixed_replacement_pairs"]:
        current = _locate(all_rows, {"race_id": pair["race_id"], "horse_number": pair["current_removed"]["horse_number"]})
        daily = _locate(all_rows, {"race_id": pair["race_id"], "horse_number": pair["daily_added"]["horse_number"]})
        if "CURRENT" not in current["selecting_lanes"] or "DAILY_V5_SAME_VOLUME" in current["selecting_lanes"]:
            raise RuntimeError("STOP_H4_CURRENT_REMOVED_MEMBERSHIP_MISMATCH")
        if "CURRENT" in daily["selecting_lanes"] or "DAILY_V5_SAME_VOLUME" not in daily["selecting_lanes"]:
            raise RuntimeError("STOP_H4_DAILY_ADDED_MEMBERSHIP_MISMATCH")
        removed_rows.append(current)
        added_rows.append(daily)
        h4_pairs.append({
            "race_id": pair["race_id"], "venue": pair["venue"], "race_number": pair["race_number"],
            "current_removed": current, "daily_added": daily,
            "hit_difference_daily_minus_current": int(daily["actual_top3"]) - int(current["actual_top3"]),
        })
    h4_removed, h4_added = _metrics(removed_rows), _metrics(added_rows)
    retained = [row for row in lane_rows["CURRENT"] if "DAILY_V5_SAME_VOLUME" in row["selecting_lanes"]]

    actual_top3 = [row for row in all_rows if row["valid_result"] and row["actual_top3"]]
    h5_a = [row for row in actual_top3 if "CURRENT" in row["selecting_lanes"]]
    h5_b = [row for row in actual_top3 if "CURRENT" not in row["selecting_lanes"] and bool(row["selecting_lanes"])]
    h5_c = [row for row in actual_top3 if not row["selecting_lanes"]]
    if len(h5_a) + len(h5_b) + len(h5_c) != len(actual_top3):
        raise RuntimeError("STOP_H5_PARTITION_MISMATCH")
    h5 = {
        "total_valid_actual_top3_horses": len(actual_top3),
        "A_CURRENT_SELECTED": {"count": len(h5_a), "horses": h5_a},
        "B_CURRENT_FALSE_OTHER_LANE_SELECTED": {"count": len(h5_b), "horses": h5_b},
        "C_ALL_LANES_UNSELECTED": {"count": len(h5_c), "horses": h5_c},
        "current_capture_share": _rate(len(h5_a), len(actual_top3)),
        "other_lane_recovery_share": _rate(len(h5_b), len(actual_top3)),
        "all_lanes_unrecovered_share": _rate(len(h5_c), len(actual_top3)),
    }

    daily_replacement = _replacement_sets(union_rows, "DAILY_V5_SAME_VOLUME")
    formal_replacement = _replacement_sets(union_rows, "FORMAL_V5")
    tc_replacement = _replacement_sets(union_rows, "TRACKCONDITION_SEMANTIC")
    current_abstention_coverage = {
        "A_UNCONVERGED_INDEPENDENT_SELECTED": _coverage(union_rows, lane="INDEPENDENT_V5", state="PLAY_UNCONVERGED_4PLUS"),
        "B_UNCONVERGED_TC_SELECTED": _coverage(union_rows, lane="TRACKCONDITION_SEMANTIC", state="PLAY_UNCONVERGED_4PLUS"),
        "C_SKIP_ANY_OTHER_LANE_SELECTED": _coverage(union_rows, lane=None, state="SKIP"),
    }
    current_miss_recovery = h5_b
    current_miss_unrecovered = h5_c

    h1_direction = _direction("H1", left=h1_metric)
    h2_direction = _direction("H2", left=h2_metric)
    h3_direction = _direction("H3", left=h3_a_metric, right=h3_b_metric)
    h4_direction = _direction("H4", left=h4_added, right=h4_removed)
    h5_direction = _direction("H5")
    observation = {
        "schema_version": "ensemble_preregistered_observation_post_v1",
        "date": DATE,
        "role": "POST_RESULT_RETROSPECTIVE_ENSEMBLE_DIAGNOSTIC_ONLY",
        "formal_evidence": False,
        "pre_registration": {"relative_path": "reports/20261004_ensemble_hypothesis_preregistration_v1.json", "sha256": PREREG_SHA, "verified": True},
        "pre_fixed_union": {"selection_sha256": UNION_SHA, "verified": True, "raw_unique_n": 28, "selected_races": 11},
        "H1_CURRENT_ONLY": {"pre_fixed_n": 1, "members": h1_rows, "metrics": h1_metric, "direction": h1_direction},
        "H2_INDEPENDENT_IN_CURRENT_UNCONVERGED": {"pre_fixed_n": 12, "members": h2_rows, "metrics": h2_metric, "direction": h2_direction},
        "H3_TC_AGREEMENT_INSIDE_CURRENT": {
            "group_a_current_and_tc": {"pre_fixed_n": 2, "members": h3_a, "metrics": h3_a_metric},
            "group_b_current_not_tc": {"pre_fixed_n": 5, "members": h3_b, "metrics": h3_b_metric},
            "direction": h3_direction,
        },
        "H4_DAILY_V5_SAME_VOLUME": {
            "pre_fixed_pair_count": 4, "pairs": h4_pairs,
            "current_removed": h4_removed, "daily_added": h4_added,
            "net_hit_difference_daily_minus_current": h4_added["hits"] - h4_removed["hits"],
            "retained": {"members": retained, "metrics": _metrics(retained)}, "direction": h4_direction,
        },
        "H5_COVERAGE": {**h5, "direction": h5_direction},
        "support_structures_v2": structure_metrics,
        "current_refinement_diagnostic": key_structure_metrics,
        "current_abstention_candidate_generation": current_abstention_coverage,
        "current_miss_recovery": current_miss_recovery,
        "current_misses_not_recovered": current_miss_unrecovered,
        "lane_replacement_diagnostics": {"daily": daily_replacement, "formal": formal_replacement, "trackcondition": tc_replacement},
        "safety": {
            "pre_selection_changed": False, "union_selection_changed": False, "family_definition_changed": False,
            "hypothesis_definition_changed": False, "post_result_selection_change": False, "new_buy_rule_created": False,
            "model_change": False, "threshold_change": False, "training": False, "formal_evidence": False,
            "production_change": False,
        },
    }
    today = {"lane_metrics": lane_metrics, "union_metrics": union_metrics, "key_structure_metrics": key_structure_metrics, "structure_metrics": structure_metrics, "h5": h5}
    mixed = _mixed_role_descriptive(today)
    post = {
        "schema_version": "all_active_systems_post_diagnostic_v2",
        "date": DATE,
        "role": "POST_RESULT_RETROSPECTIVE_ENSEMBLE_DIAGNOSTIC_ONLY",
        "formal_evidence": False,
        "frozen_pre_integrity": {"status": "PASS", "selected_counts": pre["selected_counts"], "current_race_state_counts": dict(state_counts)},
        "result_reconciliation": {
            "status": "PASS", "primary_sha256": joined["primary_sha256"], "auxiliary_sha256": joined["auxiliary_sha256"],
            "result_race_count": len(joined["pair"]["source_d_primary"]["race_index"]), "finish_consistency": joined["finish_consistency"],
        },
        "lane_results": lane_metrics,
        "union_result": union_metrics,
        "support_structure_v2_results": structure_metrics,
        "current_refinement_diagnostic": key_structure_metrics,
        "candidate_generation_coverage": current_abstention_coverage,
        "safety": observation["safety"],
    }
    horse_fields = ["date", "venue", "race_number", "race_id", "horse_no", "horse_name", "selecting_lanes", "lane_support_count", "family_support_count", "support_structure", "current_race_state", "actual_finish", "valid_result", "actual_top3"]
    summary_lines = [
        "# 2026-10-04 Pre-registered Forward Ensemble Diagnostic", "",
        "Role: POST_RESULT_RETROSPECTIVE_ENSEMBLE_DIAGNOSTIC_ONLY", "",
        "## Six-lane results", "", "| Lane | Hits | Valid N | Rate |", "|---|---:|---:|---:|",
    ]
    summary_lines += [f"| {lane} | {metric['hits']} | {metric['valid_n']} | {_rate_text(metric)} |" for lane, metric in lane_metrics.items()]
    summary_lines += [
        "", "## PRE-fixed UNION", "", f"{_brief(union_metrics)}. Raw unique N {union_metrics['raw_n']}; invalid {union_metrics['invalid_n']}; selected races {union_metrics['selected_races']}.",
        "", "## H1-H5", "", "| Hypothesis | Pre-fixed N | Result | Direction |", "|---|---:|---|---|",
        f"| H1 Current only | 1 | {_brief(h1_metric)} | {h1_direction} |",
        f"| H2 Independent in Current UNCONVERGED | 12 | {_brief(h2_metric)} | {h2_direction} |",
        f"| H3 TC agreement inside Current | A {_brief(h3_a_metric)} / B {_brief(h3_b_metric)} | rate comparison | {h3_direction} |",
        f"| H4 Daily same-volume pairs | 4 | Daily {_brief(h4_added)} / Current {_brief(h4_removed)} | {h4_direction} |",
        f"| H5 all-lane unrecovered | {h5['total_valid_actual_top3_horses']} actual Top3 | unrecovered {h5['C_ALL_LANES_UNSELECTED']['count']} ({h5['all_lanes_unrecovered_share']:.2%}) | {h5_direction} |",
        "", "## Current refinement", "", "| Structure | Hits | Valid N | Rate |", "|---|---:|---:|---:|",
    ]
    summary_lines += [f"| {name} | {metric['hits']} | {metric['valid_n']} | {_rate_text(metric)} |" for name, metric in key_structure_metrics.items()]
    summary_lines += ["", "## Four-date descriptive summary", "", "Evidence role: MIXED_EVIDENCE_ROLE_DESCRIPTIVE_ONLY. The 9/26--10/03 UNION/Family V2 aggregation is retrospective; 10/04 is forward pre-registered.", "", "| Structure | 9/26 | 9/27 | 10/03 | 10/04 | Combined |", "|---|---|---|---|---|---|"]
    for name, metric in mixed["combined"].items():
        summary_lines.append("| " + name + " | " + " | ".join(_brief(mixed["per_date"][date][name]) for date in mixed["dates"]) + f" | {_brief(metric)} |")
    summary_lines += ["", "No selection, threshold, model, training, BUY rule, Formal Evidence, or Production change is made by this diagnostic."]

    _dump_exclusive(outputs["post"], post)
    _csv_exclusive(outputs["horses"], union_rows, horse_fields)
    _dump_exclusive(outputs["observation"], observation)
    with outputs["summary"].open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(summary_lines) + "\n")
    _dump_exclusive(outputs["mixed"], mixed)
    hashes = {
        "schema_version": "post_artifact_hashes_v1",
        "self_hash_excluded": True,
        "indexed_artifacts": {
            name: {"relative_path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": _sha256(path)}
            for name, path in outputs.items() if name != "hashes"
        },
    }
    _dump_exclusive(outputs["hashes"], hashes)
    return outputs


if __name__ == "__main__":
    for name, path in run().items():
        print(f"{name}={path}")
