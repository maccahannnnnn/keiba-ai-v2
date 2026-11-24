"""Independent, read-only re-computation package for the three all-active POST dates."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from review.all_active_systems_analysis_export_v1 import LANES, ROOT, _paths, _sha256
from review.all_active_systems_post_diagnostic_v1 import _combine, _diagnose, _metrics


DATES = ("20260926", "20260927", "20261003")
FAMILY_VERSION = "FAMILY_DEFINITION_V2"


def _dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _rate_text(metric: dict[str, Any]) -> str:
    return f"{metric['hits']} / {metric['valid_n']} / {metric['top3_rate']:.2%}" if metric["top3_rate"] is not None else f"{metric['hits']} / 0 / n.a."


def _pre_sources(date: str) -> list[dict[str, str]]:
    paths = _paths(date)
    items = {
        "CURRENT_prediction_manifest": paths["current"] / "prediction_manifest.json",
        "CURRENT_race_index": paths["current"] / "race_index.json",
        "CURRENT_input_manifest": paths["current"] / "input_manifest.json",
        "INDEPENDENT_V5_selection_manifest": paths["independent"] / "selection_manifest.json",
        "TRACKCONDITION_horse_trace": paths["trackcondition"] / "horse_level_trace.json",
        "TRACKCONDITION_race_trace": paths["trackcondition"] / "race_level_trace.json",
        "DAILY_V5_selection": paths["daily"] / "selection.json",
        "FORMAL_V5_V6_dual_semantic": paths["formal"] / "dual_pre_semantic.json",
    }
    return [{"role": role, "path": str(path.relative_to(ROOT)), "sha256": _sha256(path)} for role, path in items.items()]


def _result_sources(result: dict[str, Any]) -> dict[str, Any]:
    pair = result["joined"]["pair"]
    return {
        "primary": {"path": pair["source_d_primary"]["path"], "sha256": result["joined"]["primary_sha256"]},
        "auxiliary": {"path": pair["source_c_auxiliary"]["path"], "sha256": result["joined"]["auxiliary_sha256"]},
        "pair_schema_status": pair["status"],
        "finish_consistency": result["joined"]["finish_consistency"],
    }


def _legacy_lane_metrics(date: str) -> dict[str, dict[str, Any]]:
    if date == "20261003":
        source = json.loads((ROOT / "reports" / "20261003_all_active_systems_post_diagnostic.json").read_text(encoding="utf-8"))["lane_results"]
        return source
    source = json.loads((ROOT / "reports" / f"{date}_all_active_systems_post" / "all_system_performance.json").read_text(encoding="utf-8"))
    return {lane: {"raw_n": value["selected_n"], "invalid_n": value["invalid_n"], "valid_n": value["valid_n"],
                   "hits": value["hits"], "top3_rate": value["rate"]} for lane, value in source.items()}


def _legacy_union_metrics(date: str) -> dict[str, Any]:
    if date == "20261003":
        return json.loads((ROOT / "reports" / "20261003_all_active_systems_post_diagnostic.json").read_text(encoding="utf-8"))["union_result"]
    document = json.loads((ROOT / "reports" / "20260926_27_all_active_systems_union_diagnostic.json").read_text(encoding="utf-8"))
    value = document["union_metrics_by_date"][date]
    return {"raw_n": value["selected_raw"], "invalid_n": value["invalid_selected"], "valid_n": value["valid_selected"],
            "hits": value["top3_hits"], "top3_rate": value["buy_top3_rate"]}


def _same_metrics(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left[key] == right[key] for key in ("raw_n", "invalid_n", "valid_n", "hits", "top3_rate"))


def _all_top3_diagnostics(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pre, outcomes = result["pre"], result["joined"]["outcomes"]
    recovered, unrecovered = [], []
    for race_id, record in pre["records"].items():
        for horse in record["ranked"]:
            number = str(horse["horse_number"])
            outcome = outcomes[(race_id, number)]
            if not outcome["actual_top3"] or number in pre["selection"]["CURRENT"][race_id]:
                continue
            others = [lane for lane in LANES if lane != "CURRENT" and number in pre["selection"][lane][race_id]]
            common = {
                "date": pre["date"], "venue": record["venue"], "race": record["race_number"], "race_id": race_id,
                "horse_no": int(number), "horse_name": horse["horse_name"], "finish": outcome["actual_finish"],
                "valid_result": outcome["valid_result"], "actual_top3": outcome["actual_top3"], "current_race_state": record["current_state"],
                "current_rank": horse.get("rank"),
            }
            if others:
                current = next(row for row in result["union_rows"] if row["race_id"] == race_id and row["horse_no"] == int(number))
                recovered.append({**common, "selecting_other_lanes": others, "support_structure": current["support_structure"],
                                  "lane_support_count": current["lane_support_count"]})
            else:
                unrecovered.append({**common, "selecting_other_lanes": [], "support_structure": "UNSELECTED_BY_ALL_LANES"})
    return recovered, unrecovered


def _replacement_rows(results: list[dict[str, Any]], lane: str) -> list[dict[str, Any]]:
    values = []
    for result in results:
        for item in result["replacement_diagnostics"][lane]:
            values.append({"date": result["pre"]["date"], **item})
    return values


def run() -> dict[str, Path]:
    reports = ROOT / "reports"
    outputs = {
        "package": reports / "20260926_1003_ensemble_independent_audit_package.json",
        "recovery": reports / "20260926_1003_current_miss_recovery.csv",
        "family": reports / "20260926_1003_harmonized_family_v2.json",
        "summary": reports / "20260926_1003_harmonized_family_v2_summary.md",
        "hashes": reports / "20260926_1003_ensemble_audit_hashes.json",
    }
    if any(path.exists() for path in outputs.values()):
        raise RuntimeError("STOP_AUDIT_OUTPUT_EXISTS")

    results = [_diagnose(date) for date in DATES]
    by_date = {result["pre"]["date"]: result for result in results}
    reconciliations = {}
    for date, result in by_date.items():
        independent_lane = result["lane_metrics"]
        legacy_lane = _legacy_lane_metrics(date)
        lane_match = {lane: _same_metrics(independent_lane[lane], legacy_lane[lane]) for lane in LANES}
        union_match = _same_metrics(result["union_metrics"], _legacy_union_metrics(date))
        if not all(lane_match.values()) or not union_match:
            raise RuntimeError(f"STOP_EXISTING_POST_RECONCILIATION_MISMATCH:{date}")
        reconciliations[date] = {"lane_match": lane_match, "union_match": union_match, "status": "PASS"}

    recovered_by_date, unrecovered_by_date = {}, {}
    for date, result in by_date.items():
        recovered_by_date[date], unrecovered_by_date[date] = _all_top3_diagnostics(result)
    recovered = [row for date in DATES for row in recovered_by_date[date]]
    unrecovered = [row for date in DATES for row in unrecovered_by_date[date]]
    recovery_by_lane = {lane: sum(lane in row["selecting_other_lanes"] for row in recovered) for lane in LANES if lane != "CURRENT"}

    structures = ("CURRENT_ONLY", "CURRENT_PLUS_V5", "CURRENT_PLUS_TC", "CURRENT_PLUS_TC_PLUS_V5", "V5_FAMILY_ONLY", "TC_ONLY", "TC_PLUS_V5")
    cumulative_structures = {name: _combine([result["structure_metrics"][name] for result in results]) for name in structures}
    summary_rows = {
        "UNION": {date: by_date[date]["union_metrics"] for date in DATES},
        "CURRENT": {date: by_date[date]["lane_metrics"]["CURRENT"] for date in DATES},
        "DAILY_V5_SAME_VOLUME": {date: by_date[date]["lane_metrics"]["DAILY_V5_SAME_VOLUME"] for date in DATES},
        "CURRENT_PLUS_ANY_OTHER_LANE": {date: by_date[date]["key_structure_metrics"]["CURRENT_PLUS_ANY_OTHER_LANE"] for date in DATES},
        "CURRENT_ONLY": {date: by_date[date]["key_structure_metrics"]["CURRENT_ONLY"] for date in DATES},
        "CURRENT_PLUS_V5": {date: by_date[date]["structure_metrics"]["CURRENT_PLUS_V5"] for date in DATES},
        "CURRENT_PLUS_TC_PLUS_V5": {date: by_date[date]["structure_metrics"]["CURRENT_PLUS_TC_PLUS_V5"] for date in DATES},
        "V5_FAMILY_ONLY": {date: by_date[date]["structure_metrics"]["V5_FAMILY_ONLY"] for date in DATES},
        "TC_ONLY": {date: by_date[date]["structure_metrics"]["TC_ONLY"] for date in DATES},
        "TC_PLUS_V5": {date: by_date[date]["structure_metrics"]["TC_PLUS_V5"] for date in DATES},
        "CURRENT_MISS_RECOVERY": {date: _metrics(recovered_by_date[date]) for date in DATES},
    }
    for name, values in summary_rows.items():
        values["combined"] = _combine([values[date] for date in DATES])

    package = {
        "schema_version": "ensemble_independent_audit_package_v1", "role": "POST_RESULT_RETROSPECTIVE_ENSEMBLE_DIAGNOSTIC_ONLY",
        "formal_evidence": False, "family_definition_version": FAMILY_VERSION, "dates": list(DATES),
        "aggregation_formulas": {
            "valid_n": "raw_n - invalid_n", "hits": "count(valid_result=true and actual_top3=true)",
            "top3_rate": "hits / valid_n", "union": "deduplicate PRE selections by date + venue + race + horse_no before result join",
        },
        "family_definition": {"CURRENT_BASE": ["CURRENT"], "TRACKCONDITION_VARIANT": ["TRACKCONDITION_SEMANTIC"],
                              "V5_FAMILY": ["INDEPENDENT_V5", "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6"]},
        "source_artifacts": {date: {"pre": _pre_sources(date), "result": _result_sources(by_date[date])} for date in DATES},
        "pre_selected_horse_set_and_result_join": {date: by_date[date]["union_rows"] for date in DATES},
        "lane_results_recomputed": {date: by_date[date]["lane_metrics"] for date in DATES},
        "union_results_recomputed": {date: by_date[date]["union_metrics"] for date in DATES},
        "existing_post_reconciliation": reconciliations,
        "daily_v5_reselection": {date: by_date[date]["variant"]["daily_v5"] for date in DATES},
        "formal_reselection": {date: by_date[date]["variant"]["formal"] for date in DATES},
        "trackcondition_reselection": {date: by_date[date]["variant"]["trackcondition"] for date in DATES},
        "replacement_tables": {"DAILY_V5_SAME_VOLUME": _replacement_rows(results, "DAILY_V5_SAME_VOLUME"),
                               "FORMAL_V5": _replacement_rows(results, "FORMAL_V5"),
                               "TRACKCONDITION_SEMANTIC": _replacement_rows(results, "TRACKCONDITION_SEMANTIC")},
        "current_miss_recovery": {"union_unique_recovery_count": len(recovered), "by_lane": recovery_by_lane, "horses": recovered},
        "current_misses_not_recovered": {"count": len(unrecovered), "horses": unrecovered},
        "safety": {"pre_selection_changed": False, "post_result_selection_change": False, "model_change": False,
                   "threshold_change": False, "training": False, "formal_evidence": False, "production_change": False},
    }
    family = {
        "schema_version": "harmonized_family_v2_diagnostic_v1", "role": "POST_RESULT_RETROSPECTIVE_ENSEMBLE_DIAGNOSTIC_ONLY",
        "family_definition_version": FAMILY_VERSION, "dates": list(DATES),
        "per_date_support_structures": {date: by_date[date]["structure_metrics"] for date in DATES},
        "combined_support_structures": cumulative_structures,
        "per_date_additional_structures": {date: by_date[date]["consensus"] | by_date[date]["key_structure_metrics"] for date in DATES},
        "combined_additional_structures": {
            "one_lane_support": _combine([result["consensus"]["single_lane_support"] for result in results]),
            "multi_lane_support": _combine([result["consensus"]["multi_lane_support"] for result in results]),
            "one_structure_support": _combine([result["consensus"]["one_structure_only"] for result in results]),
            "multi_structure_support": _combine([result["consensus"]["structurally_multi_supported"] for result in results]),
            "current_plus_any_other_lane": _combine([result["key_structure_metrics"]["CURRENT_PLUS_ANY_OTHER_LANE"] for result in results]),
            "current_false_any_other_lane": _combine([result["key_structure_metrics"]["CURRENT_FALSE_ANY_OTHER_LANE"] for result in results]),
        },
        "three_date_summary": summary_rows,
        "note": "FORMAL_V6 is included within V5_FAMILY. TrackCondition is a Current semantic variant, not an asserted independent vote.",
    }
    _dump(outputs["package"], package)
    _dump(outputs["family"], family)
    recovery_fields = ["date", "venue", "race", "race_id", "horse_no", "horse_name", "finish", "valid_result", "actual_top3", "current_race_state", "current_rank", "selecting_other_lanes", "support_structure", "lane_support_count"]
    with outputs["recovery"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=recovery_fields)
        writer.writeheader()
        for row in recovered:
            writer.writerow({key: ";".join(row[key]) if key == "selecting_other_lanes" else row.get(key) for key in recovery_fields})
    lines = ["# Harmonized Family Definition V2: 2026-09-26 / 09-27 / 10-03", "", "Role: POST_RESULT_RETROSPECTIVE_ENSEMBLE_DIAGNOSTIC_ONLY", "", "| Structure | 9/26 | 9/27 | 10/03 | Combined |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {name} | {_rate_text(values[DATES[0]])} | {_rate_text(values[DATES[1]])} | {_rate_text(values[DATES[2]])} | {_rate_text(values['combined'])} |" for name, values in summary_rows.items()]
    lines += ["", "Support counts are not independent votes. This package is diagnostic only; it does not create a selection, BUY, or threshold rule."]
    outputs["summary"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    hash_index = {name: {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path), "bytes": path.stat().st_size}
                  for name, path in outputs.items() if name != "hashes"}
    _dump(outputs["hashes"], {"schema_version": "ensemble_independent_audit_hashes_v1", "self_hash_excluded": True, "artifacts": hash_index})
    return outputs


if __name__ == "__main__":
    for key, value in run().items():
        print(f"{key}={value}")
