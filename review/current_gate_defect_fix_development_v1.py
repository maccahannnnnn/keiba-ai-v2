"""Result-free historical A1/A2 selection freeze; no formal PRE authority.

Reuses the frozen Current raw-replay payload and the approved A1/A2 shadow.
All validation is completed before creating the new output directory.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import re

from engine.decision_engine import DecisionEngine
from review.current_gate_defect_fix_shadow_v1 import GateFixConfig, run_race
from review.current_corrected_shadow_v2_replay import _filtered_date_sources
from review.target_bulk_prediction_input_adapter_v1 import (
    HUMAN_APPROVED_20260906_EXACT_EXCEPTION,
    TargetBulkPredictionInputAdapterV1,
)

ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "data" / "raw" / "prediction_input"
BASE = ROOT / "reports" / "current_corrected_shadow_v1_raw_replay_v7"
OUT = ROOT / "reports" / "current_gate_defect_fix_development_v1"
START, END = "20260201", "20260913"
CONFIGS = {
    "CURRENT": GateFixConfig(),
    "A1_ONLY": GateFixConfig(True, False),
    "A2_ONLY": GateFixConfig(False, True),
    "A1_A2": GateFixConfig(True, True),
}
JST = timezone(timedelta(hours=9))
COMPARISON_RULE = "TIE_ORDER_DIAGNOSTIC_ONLY_V1_20261113"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def race_id_from_manifest(row):
    return Path(row["payload_path"]).name.removesuffix("_current_replay.json")


def horse_key(row):
    return int(row["horse_number"]), str(row["horse_name"])


def trace_by_number(payload):
    return {int(row["horse_number"]): row for row in payload["buy_gate_trace"]["horses"]}


def leaf_diffs(current, saved, path=""):
    """Compare all stored fields, including nested diagnostics; omit nothing."""
    if type(current) is not type(saved):
        return [(path, current, saved)]
    if isinstance(current, dict):
        result = []
        for key in sorted(set(current) | set(saved)):
            child = f"{path}.{key}"
            if key not in current or key not in saved:
                result.append((child, current.get(key), saved.get(key)))
            else:
                result.extend(leaf_diffs(current[key], saved[key], child))
        return result
    if isinstance(current, list):
        if len(current) != len(saved):
            return [(f"{path}.length", len(current), len(saved))]
        result = []
        for index, (left, right) in enumerate(zip(current, saved)):
            result.extend(leaf_diffs(left, right, f"{path}[{index}]"))
        return result
    return [] if current == saved else [(path, current, saved)]


def _is_rank_derived(path, current_value, saved_value, current_row, saved_row):
    current_rank = current_row["decision_result"]["ai_rank"]
    saved_rank = saved_row["decision_result"]["ai_rank"]
    if isinstance(current_value, list) and isinstance(saved_value, list):
        return (len(current_value) == len(saved_value)
                and any(left != right for left, right in zip(current_value, saved_value))
                and all(left == right or _is_rank_derived(path, left, right, current_row, saved_row)
                        for left, right in zip(current_value, saved_value)))
    if path.endswith(".ai_rank"):
        return current_value == current_rank and saved_value == saved_rank
    if re.search(r"\.decision_trace\[2\]\.value$", path):
        return (current_row["decision_trace"][2]["stage"] == "rank"
                and saved_row["decision_trace"][2]["stage"] == "rank"
                and current_value == current_rank and saved_value == saved_rank)
    if (path.endswith(".top_score_pass_rescue_skipped_reason")
            or re.search(r"\.decision_trace\[7\]\.reason$", path)):
        if (current_row["decision_trace"][7]["stage"] != "top_score_pass_rescue"
                or saved_row["decision_trace"][7]["stage"] != "top_score_pass_rescue"):
            return False
        engine = DecisionEngine()
        for rank, value in ((current_rank, current_value), (saved_rank, saved_value)):
            predicted = engine._top_score_pass_rescue(
                current_row, {"rank": rank}, current_row["decision_score"], "PASS"
            )["top_score_pass_rescue_skipped_reason"]
            if value != predicted:
                return False
        return True
    if isinstance(current_value, str) and isinstance(saved_value, str):
        before = f"Low Rank BUY Guard: AI順位{saved_rank:g}位のためBUYからCAUTIONへ調整"
        after = f"Low Rank BUY Guard: AI順位{current_rank:g}位のためBUYからCAUTIONへ調整"
        return before in saved_value and saved_value.replace(before, after) == current_value
    return False


def compare_off(race_id, output, saved):
    """Return every discrepancy classified by the Human-approved narrow rule."""
    differences = []
    for field in ("race_id", "race_decision", "race_confidence"):
        if output.get(field) != saved.get(field):
            differences.append({"race_id": race_id, "horse_number": None, "path": field,
                                "classification": "DECISION_RELEVANT", "cause": "race_header"})
    left_rows = output.get("ranked_results", [])
    right_rows = saved.get("ranked_results", [])
    left = {horse_key(row): row for row in left_rows}
    right = {horse_key(row): row for row in right_rows}
    if len(left) != len(left_rows) or len(right) != len(right_rows) or set(left) != set(right):
        differences.append({"race_id": race_id, "horse_number": None, "path": "horse_set",
                            "classification": "DECISION_RELEVANT", "cause": "identity"})
        return differences
    engine = DecisionEngine()
    scores = {key: engine._best_score(row) for key, row in left.items()}
    groups = defaultdict(list)
    for key, score in scores.items():
        groups[score].append(key)
    tie_allowed_horses = set()
    for key in sorted(left):
        current_row, saved_row = left[key], right[key]
        row_diffs = leaf_diffs(current_row, saved_row)
        if not row_diffs:
            continue
        current_rank = current_row.get("decision_result", {}).get("ai_rank")
        saved_rank = saved_row.get("decision_result", {}).get("ai_rank")
        tied = groups[scores[key]]
        tie_ranks = {left[member].get("rank") for member in tied}
        tie_valid = (
            scores[key] is not None and len(tied) >= 2 and current_rank != saved_rank
            and current_rank == current_row.get("rank") == saved_row.get("rank")
            and saved_rank in tie_ranks
            and {left[member].get("decision_result", {}).get("ai_rank") for member in tied} == tie_ranks
            and {right[member].get("decision_result", {}).get("ai_rank") for member in tied} == tie_ranks
        )
        if tie_valid and all(_is_rank_derived(path, current_value, saved_value, current_row, saved_row)
                             for path, current_value, saved_value in row_diffs):
            tie_allowed_horses.add(key[0])
        for path, current_value, saved_value in row_diffs:
            decision_field = any(path == "." + name or path.startswith("." + name + ".") for name in (
                "decision", "decision_score", "buy_v1_rc1_buy", "buy_v1_rc1_candidate",
                "buy_v1_rc1_race_state", "final_score", "adjusted_score", "rank",
            ))
            allowed = tie_valid and _is_rank_derived(
                path, current_value, saved_value, current_row, saved_row
            )
            differences.append({"race_id": race_id, "horse_number": key[0],
                                "horse_name": key[1], "path": path,
                                "current": current_value, "saved": saved_value,
                                "current_ai_rank": current_rank, "saved_ai_rank": saved_rank,
                                "top_rank": current_row.get("rank"), "exact_best_score": scores[key],
                                "tied_horse_numbers": sorted(member[0] for member in tied),
                                "classification": ("TIE_ORDER_DIAGNOSTIC_ONLY" if allowed else
                                                   "DECISION_RELEVANT" if decision_field else "OTHER"),
                                "cause": "20261013_score_rank_map_tie_order" if allowed else "unapproved_difference"})
    actual, expected = output.get("buy_gate_trace", {}), saved.get("buy_gate_trace", {})
    if actual.get("race") != expected.get("race"):
        differences.append({"race_id": race_id, "horse_number": None, "path": "buy_gate_trace.race",
                            "classification": "DECISION_RELEVANT", "cause": "race_gate"})
    a, b = trace_by_number(output), trace_by_number(saved)
    if set(a) != set(b):
        differences.append({"race_id": race_id, "horse_number": None, "path": "buy_gate_trace.horse_set",
                            "classification": "DECISION_RELEVANT", "cause": "horse_gate_set"})
    else:
        for number, stored in b.items():
            for field, value in stored.items():
                if a[number].get(field) != value:
                    rank_only_risk_summary = (
                        field == "risk_summary" and number in tie_allowed_horses
                        and _is_rank_derived(
                            "risk_summary", a[number].get(field), value,
                            next(row for key, row in left.items() if key[0] == number),
                            next(row for key, row in right.items() if key[0] == number),
                        )
                    )
                    differences.append({"race_id": race_id, "horse_number": number,
                                        "path": "buy_gate_trace." + field,
                                        "current": a[number].get(field), "saved": value,
                                        "classification": ("TIE_ORDER_DIAGNOSTIC_ONLY" if rank_only_risk_summary
                                                           else "DECISION_RELEVANT"),
                                        "cause": ("20261013_score_rank_map_tie_order" if rank_only_risk_summary
                                                  else "horse_gate")})
    return differences


def write_csv_new(path, rows, fields):
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def group_counts(rows, group_field):
    grouped = defaultdict(lambda: Counter())
    for row in rows:
        group = grouped[row[group_field]]
        group["horses"] += 1
        for name in CONFIGS:
            group[name + "_buy"] += row[name + "_buy"]
            group[name + "_candidate"] += row[name + "_candidate"]
            group[name + "_risk_guard_pass"] += row[name + "_risk_guard_pass"]
            if row[name + "_buy"]:
                group[name + "_buy_races_set"] = 0  # calculated from race identity below
        for name in CONFIGS:
            if row[name + "_buy"]:
                group[name + "_buy_race_keys_" + row["race_id"]] = 1
        for name in CONFIGS:
            category = row[name + "_change_group"]
            if category:
                group[name + "_" + category] += 1
            reason = row[name + "_G3_reason"]
            if reason:
                group[name + "_G3_" + reason] += 1
    result = []
    for key, counter in sorted(grouped.items()):
        item = {group_field: key, "horses": counter["horses"]}
        for name in CONFIGS:
            item[name + "_buy"] = counter[name + "_buy"]
            item[name + "_candidate"] = counter[name + "_candidate"]
            item[name + "_risk_guard_pass"] = counter[name + "_risk_guard_pass"]
            item[name + "_buy_races"] = sum(1 for k in counter if k.startswith(name + "_buy_race_keys_"))
            for category in ("G1", "G2", "G3", "G3_UNCONVERGED", "G3_OTHER"):
                item[name + "_" + category] = counter[name + "_" + category]
        result.append(item)
    return result


def source_paths_for_date(date, baselines):
    source_sets = {tuple(sorted(row["raw_source_paths"].items())) for row in baselines}
    if len(source_sets) != 1:
        raise RuntimeError(f"STOP_MULTIPLE_INPUT_AUTHORITIES:{date}")
    recorded = dict(next(iter(source_sets)))
    paths = {}
    for kind in ("DG", "DE", "DS"):
        relative = Path(recorded[kind].replace("\\", "/"))
        path = (ROOT / relative).resolve()
        if path.parent != INPUT_ROOT.resolve() or not path.name.startswith(f"{kind}{date[2:]}"):
            raise RuntimeError(f"STOP_SOURCE_PATH_OUTSIDE_APPROVED_INPUT:{date}:{kind}")
        if not path.is_file():
            raise RuntimeError(f"STOP_INPUT_MISSING:{date}:{kind}")
        paths[kind] = path
    return paths


def load_date(date, paths, temporary):
    load_paths = _filtered_date_sources(
        date, (paths["DG"], paths["DE"], paths["DS"]), Path(temporary) / date
    )
    compatibility = HUMAN_APPROVED_20260906_EXACT_EXCEPTION if date == "20260906" else None
    return TargetBulkPredictionInputAdapterV1().load(
        *load_paths, compatibility_exception=compatibility
    )


def audit_all_off(by_date):
    """Complete every Result-free baseline comparison before any variant run."""
    all_differences = []
    input_sha = {}
    checked = 0
    with TemporaryDirectory(prefix="keiba_a1a2_all_off_") as temporary:
        for date, baselines in sorted(by_date.items()):
            paths = source_paths_for_date(date, baselines)
            digest = {kind: sha(path) for kind, path in paths.items()}
            input_sha[date] = {kind: {"path": str(path.relative_to(ROOT)), "sha256": digest[kind]}
                               for kind, path in paths.items()}
            daily = load_date(date, paths, temporary)
            expected_races = {race_id_from_manifest(row) for row in baselines}
            if set(daily.races) != expected_races:
                raise RuntimeError(f"STOP_DAILY_RACE_SET_MISMATCH:{date}")
            for item in sorted(baselines, key=race_id_from_manifest):
                race_id = race_id_from_manifest(item)
                source_path = BASE / "complete_payloads" / f"{race_id}_current_replay.json"
                if sha(source_path) != item["payload_sha256"]:
                    raise RuntimeError(f"STOP_BASELINE_SHA_MISMATCH:{race_id}")
                saved = json.loads(source_path.read_text(encoding="utf-8"))
                if (saved["race_id"] != race_id or saved["date"] != date
                        or saved["result_data_access_count"] != 0
                        or saved["source"]["sha256"] != digest):
                    raise RuntimeError(f"STOP_BASELINE_METADATA_OR_INPUT_MISMATCH:{race_id}")
                live = run_race(race_id, daily.races[race_id], CONFIGS["CURRENT"])
                all_differences.extend(compare_off(race_id, live, saved["current_replay"]))
                checked += 1
            print(f"ALL_OFF_DATE_DONE {date} {checked}", flush=True)
    counts = Counter(row["classification"] for row in all_differences)
    status = "PASS" if checked == 1111 and not counts["DECISION_RELEVANT"] and not counts["OTHER"] else "FAIL"
    return {"status": status, "checked_races": checked, "input_sha256_by_date": input_sha,
            "classification_field_counts": dict(counts),
            "tie_races": len({row["race_id"] for row in all_differences
                              if row["classification"] == "TIE_ORDER_DIAGNOSTIC_ONLY"}),
            "tie_horses": len({(row["race_id"], row["horse_number"]) for row in all_differences
                               if row["classification"] == "TIE_ORDER_DIAGNOSTIC_ONLY"}),
            "tie_dates": len({row["race_id"].split("_")[1] for row in all_differences
                              if row["classification"] == "TIE_ORDER_DIAGNOSTIC_ONLY"}),
            "differences": all_differences}


def main():
    if OUT.exists():
        raise RuntimeError("STOP_EXISTING_OUTPUT")
    manifest_path = BASE / "current_canonical_complete_replay_payload_manifest_v1.json"
    protected = [manifest_path, BASE / "artifact_hashes.json",
                 ROOT / "reports" / "formal_pre_daily" / "20261114" / "summary.json",
                 ROOT / "review" / "current_gate_defect_fix_shadow_v1.py",
                 ROOT / "review" / "current_gate_defect_fix_technical_v1.py"]
    protected_before = {str(path.relative_to(ROOT)): sha(path) for path in protected}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = [row for row in manifest["races"] if START <= str(row["date"]) <= END]
    if len(selected) != 1111:
        raise RuntimeError(f"STOP_POPULATION_NOT_1111:{len(selected)}")
    if len({race_id_from_manifest(row) for row in selected}) != len(selected):
        raise RuntimeError("STOP_DUPLICATE_BASELINE_RACE")
    by_date = defaultdict(list)
    for row in selected:
        by_date[str(row["date"])].append(row)
    audit = audit_all_off(by_date)
    if audit["status"] != "PASS":
        raise RuntimeError(f"STOP_ALL_OFF_AUDIT_FAIL:{audit['classification_field_counts']}")
    input_sha = audit["input_sha256_by_date"]
    selection_rows = []
    a1b_rows = []
    source_kind = Counter()
    for date, baselines in sorted(by_date.items()):
        paths = source_paths_for_date(date, baselines)
        digest = {kind: sha(path) for kind, path in paths.items()}
        with TemporaryDirectory(prefix="keiba_a1a2_source_") as temporary:
            daily = load_date(date, paths, temporary)
        if set(daily.races) != {race_id_from_manifest(row) for row in baselines}:
            raise RuntimeError(f"STOP_DAILY_RACE_SET_MISMATCH:{date}")
        for item in sorted(baselines, key=race_id_from_manifest):
            race_id = race_id_from_manifest(item)
            source_path = BASE / "complete_payloads" / f"{race_id}_current_replay.json"
            if sha(source_path) != item["payload_sha256"]:
                raise RuntimeError(f"STOP_BASELINE_SHA_MISMATCH:{race_id}")
            frozen = json.loads(source_path.read_text(encoding="utf-8"))
            if frozen["race_id"] != race_id or frozen["date"] != date or frozen["result_data_access_count"] != 0:
                raise RuntimeError(f"STOP_BASELINE_METADATA_MISMATCH:{race_id}")
            if frozen["source"]["sha256"] != digest:
                raise RuntimeError(f"STOP_BASELINE_INPUT_SHA_MISMATCH:{race_id}")
            source_kind[item.get("observable_match_status", "UNKNOWN")] += 1
            bundle = daily.races[race_id]
            outputs = {name: run_race(race_id, bundle, config) for name, config in CONFIGS.items()}
            second_check = compare_off(race_id, outputs["CURRENT"], frozen["current_replay"])
            if any(row["classification"] != "TIE_ORDER_DIAGNOSTIC_ONLY" for row in second_check):
                raise RuntimeError(f"STOP_SECOND_PASS_CURRENT_MISMATCH:{race_id}")
            baseline_rows = {horse_key(row): row for row in outputs["CURRENT"]["ranked_results"]}
            current_buy = {key for key, row in baseline_rows.items() if row.get("decision") == "BUY"}
            for name, output in outputs.items():
                if {horse_key(row) for row in output["ranked_results"]} != set(baseline_rows):
                    raise RuntimeError(f"STOP_VARIANT_HORSE_SET:{date}:{race_id}:{name}")
                if any(row.get("final_score") != baseline_rows[horse_key(row)].get("final_score")
                       or row.get("adjusted_score") != baseline_rows[horse_key(row)].get("adjusted_score")
                       or row.get("rank") != baseline_rows[horse_key(row)].get("rank")
                       for row in output["ranked_results"]):
                    raise RuntimeError(f"STOP_UNEXPECTED_SCORE_OR_RANK_CHANGE:{date}:{race_id}:{name}")
            variant_rows = {name: {horse_key(row): row for row in output["ranked_results"]}
                            for name, output in outputs.items()}
            gates = {name: trace_by_number(output) for name, output in outputs.items()}
            for key in sorted(baseline_rows):
                number, horse_name = key
                record = {"date": date, "month": date[:6], "race_id": race_id,
                          "horse_id": f"{race_id}#{number}", "horse_number": number,
                          "horse_name": horse_name, "baseline_payload_sha256": item["payload_sha256"]}
                for name in CONFIGS:
                    row = variant_rows[name][key]
                    gate = gates[name][number]
                    record[name + "_buy"] = int(row.get("decision") == "BUY")
                    record[name + "_candidate"] = int(bool(row.get("buy_v1_rc1_candidate")))
                    record[name + "_risk_guard_pass"] = int(bool(gate.get("risk_guard_pass")))
                    record[name + "_race_state"] = str(row.get("buy_v1_rc1_race_state") or "")
                    record[name + "_decision_status"] = str(row.get("decision") or "")
                    record[name + "_decision_score"] = row.get("decision_score")
                    record[name + "_decision_risks"] = json.dumps(row.get("decision_risks") or [], ensure_ascii=False)
                    record[name + "_change_group"] = ""
                    record[name + "_G3_reason"] = ""
                    if name != "CURRENT":
                        now_buy = bool(record[name + "_buy"])
                        was_buy = key in current_buy
                        if now_buy and not was_buy:
                            record[name + "_change_group"] = "G1" if current_buy else "G2"
                        elif was_buy and not now_buy:
                            record[name + "_change_group"] = "G3"
                            record[name + "_G3_reason"] = (
                                "UNCONVERGED" if "UNCONVERGED" in record[name + "_race_state"] else "OTHER"
                            )
                selection_rows.append(record)
                risks = baseline_rows[key].get("decision_risks") or []
                if "展開不向き" in risks and "展開面の不安" in risks:
                    a1b_rows.append({"date": date, "race_id": race_id, "horse_id": record["horse_id"],
                                     "horse_name": horse_name,
                                     "pace_style": baseline_rows[key].get("pace_style"),
                                     "impact_score": baseline_rows[key].get("impact_score"),
                                     "shape_score": baseline_rows[key].get("shape_score"),
                                     "causal_attribution": "UNKNOWN"})
    daily = group_counts(selection_rows, "date")
    monthly = group_counts(selection_rows, "month")
    protected_after = {str(path.relative_to(ROOT)): sha(path) for path in protected}
    if protected_before != protected_after:
        raise RuntimeError("STOP_PROTECTED_SHA_CHANGED")
    summary = {"schema_version": "CURRENT_GATE_DEFECT_FIX_DEVELOPMENT_V1",
               "execution_time_jst": datetime.now(JST).isoformat(),
               "execution_command": "python -m review.current_gate_defect_fix_development_v1",
               "execution_environment": {"python": sys.version, "platform": platform.platform()},
               "target_period": {"start": START, "end": END},
               "role": "DEVELOPMENT_ONLY_NON_EVIDENTIAL", "evidence_credit": 0,
               "result_access_count": 0, "post_access_count": 0,
               "formal_pre_executed": False, "performance_evaluation_count": 0,
               "race_count": len(selected), "date_count": len(by_date), "horse_count": len(selection_rows),
               "current_complete_row_match_count": len(selection_rows),
               "current_saved_gate_fields_match": True,
               "comparison_rule": COMPARISON_RULE,
               "all_off_audit": {key: audit[key] for key in (
                   "status", "checked_races", "classification_field_counts",
                   "tie_races", "tie_horses", "tie_dates")},
               "protected_sha256_before_after": protected_before,
               "baseline_manifest": {"path": str(manifest_path.relative_to(ROOT)), "sha256": sha(manifest_path)},
               "baseline_observable_match_status_counts": dict(source_kind),
               "input_sha256_by_date": input_sha,
               "code_sha256": {str(path.relative_to(ROOT)): sha(path) for path in (
                   ROOT / "review" / "current_gate_defect_fix_shadow_v1.py",
                   ROOT / "review" / "current_gate_defect_fix_technical_v1.py",
                   Path(__file__),
               )},
               "a1b_pair_horses": len(a1b_rows), "a1b_causal_attribution": "UNKNOWN",
               "metrics": monthly and {name: {
                   "buy_horses": sum(row[name + "_buy"] for row in selection_rows),
                   "buy_races": len({row["race_id"] for row in selection_rows if row[name + "_buy"]}),
                   "risk_guard_pass_horses": sum(row[name + "_risk_guard_pass"] for row in selection_rows),
                   "candidate_horses": sum(row[name + "_candidate"] for row in selection_rows),
                   "race_states": dict(Counter(next(row[name + "_race_state"] for row in selection_rows
                                                    if row["race_id"] == race_id)
                                               for race_id in {row["race_id"] for row in selection_rows})),
                   "G1": sum(row[name + "_change_group"] == "G1" for row in selection_rows),
                   "G2": sum(row[name + "_change_group"] == "G2" for row in selection_rows),
                   "G3": sum(row[name + "_change_group"] == "G3" for row in selection_rows),
                   "G3_UNCONVERGED": sum(row[name + "_G3_reason"] == "UNCONVERGED" for row in selection_rows),
                   "G3_OTHER": sum(row[name + "_G3_reason"] == "OTHER" for row in selection_rows),
               } for name in CONFIGS},
               "limitations": ["Horse ID is the unambiguous race ID plus horse number; registration ID is not exposed by the approved replay schema.",
                               "Historical raw replay contains reconstructed PRE rows; this is non-evidential development validation."]}
    OUT.mkdir(parents=True, exist_ok=False)
    write_csv_new(OUT / "selection_rows.csv", selection_rows, list(selection_rows[0]))
    write_csv_new(OUT / "daily_metrics.csv", daily, list(daily[0]))
    write_csv_new(OUT / "monthly_metrics.csv", monthly, list(monthly[0]))
    write_csv_new(OUT / "a1b_observation.csv", a1b_rows,
                  ["date", "race_id", "horse_id", "horse_name", "pace_style", "impact_score", "shape_score", "causal_attribution"])
    with (OUT / "all_off_differences.json").open("x", encoding="utf-8") as handle:
        json.dump(audit["differences"], handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with (OUT / "summary.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    output_hashes = {p.name: sha(p) for p in OUT.iterdir() if p.is_file()}
    with (OUT / "artifact_sha256.json").open("x", encoding="utf-8") as handle:
        json.dump(output_hashes, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return summary


if __name__ == "__main__":
    report = main()
    print(json.dumps({key: report[key] for key in ("race_count", "date_count", "horse_count", "metrics", "a1b_pair_horses")}, ensure_ascii=False))
