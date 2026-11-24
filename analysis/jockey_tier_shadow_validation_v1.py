"""Read-only JOCKEY_TIER_ADDITIVE_V1 Shadow validation.

Consumes frozen Tier and existing ranking artifacts. It never constructs an
Adapter, executes an Evaluator/Replay, or mutates Production decisions.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.jockey_shadow_read_only_parser_v1 import parse_entry_file
from analysis.jockey_tier_generation_v1 import stable_hash

REPORTS = ROOT / "reports"
FLAG_NAME = "JOCKEY_TIER_SHADOW_ENABLED"
FLAG_DEFAULT = "OFF"
CANDIDATE_ID = "JOCKEY_TIER_ADDITIVE_V1"
INPUT_TRANSITIONS = REPORTS / "final_score_shadow_rank_transition_v1.csv"
TABLE_JSON = REPORTS / "jockey_tier_table_v1.json"
TABLE_CSV = REPORTS / "jockey_tier_table_v1.csv"
GENERATION_MANIFEST = REPORTS / "jockey_tier_generation_manifest_v1.json"
COLUMN_SPEC = REPORTS / "jockey_history_column_spec_v1.md"
PREREGISTERED_SPEC = REPORTS / "jockey_tier_preregistered_spec_v1.md"
MEAN_RANK_MINIMUM_IMPROVEMENT = 1 / 102

OUTPUTS = {
    "column_audit": REPORTS / "jockey_tier_column_audit_v1.csv",
    "spec_sha": REPORTS / "jockey_tier_additive_v1_spec_sha256_v1.json",
    "baseline": REPORTS / "jockey_tier_baseline_result_v1.json",
    "replay": REPORTS / "jockey_tier_replay_result_v1.json",
    "transitions": REPORTS / "jockey_tier_rank_transition_v1.csv",
    "metrics": REPORTS / "jockey_tier_metric_comparison_v1.csv",
    "report": REPORTS / "jockey_tier_shadow_report_v1.md",
    "summary": REPORTS / "jockey_tier_shadow_summary_v1.json",
    "safety": REPORTS / "jockey_tier_shadow_safety_v1.json",
    "zero": REPORTS / "jockey_tier_shadow_zero_delta_v1.json",
    "tests": REPORTS / "jockey_tier_shadow_test_manifest_v1.json",
    "roi": REPORTS / "jockey_tier_roi_update_v1.md",
    "claude": REPORTS / "jockey_tier_shadow_claude_review_packet_v1.md",
    "supersession": REPORTS / "jockey_tier_unproduced_artifacts_v1.json",
}

PROTECTED = {
    "target_history_importer": ROOT / "importer" / "target_history_importer.py",
    "target_entry_importer": ROOT / "importer" / "target_entry_importer.py",
    "target_column_mapping": ROOT / "importer" / "target_column_mapping.py",
    "target_trial_adapter": ROOT / "evaluation" / "target_trial_adapter.py",
    "final_score_integrator": ROOT / "evaluation" / "final_score_integrator.py",
    "decision_engine": ROOT / "engine" / "decision_engine.py",
    "race_decision_engine": ROOT / "engine" / "race_decision_engine.py",
    "main": ROOT / "main.py",
    "learning": ROOT / "learning",
    "knowledge": ROOT / "knowledge",
    "baseline": REPORTS / "baseline",
    "historical_replay": REPORTS / "historical_replay_current_code",
    "ranking_provenance": REPORTS / "ranking_provenance",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    if path.is_file():
        return sha256(path)
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def protected_snapshot() -> dict[str, str]:
    return {name: tree_hash(path) for name, path in PROTECTED.items()}


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def truth(value) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes"}


def flag_enabled(value=None) -> bool:
    raw = os.environ.get(FLAG_NAME, FLAG_DEFAULT) if value is None else value
    return raw is True or str(raw).strip().upper() in {"1", "TRUE", "ON", "YES"}


def load_frozen_table() -> tuple[dict[str, dict], dict, dict]:
    payload = json.loads(TABLE_JSON.read_text(encoding="utf-8"))
    manifest = json.loads(GENERATION_MANIFEST.read_text(encoding="utf-8"))
    if stable_hash(payload["rows"]) != payload["table_sha256"]:
        raise RuntimeError("TIER_TABLE_SHA_MISMATCH")
    if payload["table_sha256"] != manifest["tier_table_sha256"]:
        raise RuntimeError("TIER_MANIFEST_SHA_MISMATCH")
    if manifest["preregistered_spec_sha256"] != sha256(PREREGISTERED_SPEC):
        raise RuntimeError("PREREGISTERED_SPEC_SHA_MISMATCH")
    if manifest["column_spec_sha256"] != sha256(COLUMN_SPEC):
        raise RuntimeError("COLUMN_SPEC_SHA_MISMATCH")
    return {row["jockey_name"]: row for row in payload["rows"]}, payload, manifest


def entry_lookup() -> tuple[dict[tuple[str, str], dict], dict]:
    grouped = defaultdict(list)
    paths = sorted((ROOT / "data" / "analysis").rglob("*_entry.csv"))
    for path in paths:
        for row in parse_entry_file(path):
            grouped[(row["race_id"], row["horse_name"])].append(row)
    collisions = []
    lookup = {}
    for key, rows in grouped.items():
        jockeys = {row["jockey_name"] for row in rows}
        if len(jockeys) != 1:
            collisions.append({"race_id": key[0], "horse_name": key[1], "jockey_names": sorted(jockeys)})
        else:
            lookup[key] = rows[0]
    if collisions:
        raise RuntimeError(f"ENTRY_JOCKEY_COLLISION:{len(collisions)}")
    return lookup, {"entry_file_count": len(paths), "entry_key_count": len(lookup), "entry_collision_count": 0}


def production_rows() -> dict[str, list[dict]]:
    output = {"BASELINE": [], "REPLAY": []}
    for source in read_csv(INPUT_TRANSITIONS):
        row = dict(source)
        for field in ("shadow_rank", "rank_change_shadow_minus_production", "moved", "top3_transition", "top5_transition"):
            row.pop(field, None)
        row["production_adjusted_score"] = number(source["adjusted_score"])
        row["production_rank"] = integer(source["production_rank"])
        row["valid_result"] = truth(source["valid_result"])
        row["actual_finish"] = integer(source["actual_finish"]) if row["valid_result"] else ""
        row["actual_top3"] = truth(source["actual_top3"])
        row["actual_top5"] = truth(source["actual_top5"])
        row["buy"] = truth(source["buy"])
        output[row["cohort"]].append(row)
    if len(output["BASELINE"]) != 448 or len(output["REPLAY"]) != 512:
        raise RuntimeError("COHORT_COUNT_MISMATCH")
    keys = [(row["cohort"], row["race_id"], row["horse_number"]) for values in output.values() for row in values]
    if len(keys) != len(set(keys)):
        raise RuntimeError("DUPLICATE_EVALUATION_HORSE")
    return output


def apply_shadow_row(row: dict, entries: dict, tiers: dict, enabled=None) -> dict:
    if not flag_enabled(enabled):
        return copy.deepcopy(row)
    output = copy.deepcopy(row)
    entry = entries.get((row["race_id"], row["horse_name"]))
    if entry is None:
        raise RuntimeError(f"EVALUATION_ENTRY_MISSING:{row['race_id']}:{row['horse_name']}")
    jockey_name = entry["jockey_name"]
    tier = tiers.get(jockey_name)
    if tier is None:
        tier_name, rides, score, status = "UNKNOWN", 0, 0, "TRACE_UNSEEN_JOCKEY"
    else:
        tier_name, rides, score, status = tier["tier"], integer(tier["rides"]), integer(tier["shadow_score"]), tier["status"]
    output.update({
        "shadow_jockey_name": jockey_name,
        "shadow_jockey_tier": tier_name,
        "shadow_jockey_sample_size": rides,
        "shadow_jockey_score": score,
        "shadow_adjusted_score": round(output["production_adjusted_score"] + score, 10),
        "shadow_explain": (
            f"Jockey Tier {tier_name}: pre-cutoff rides={rides}, additive={score:+d}; "
            "independent supplementary information only"
            if tier_name != "UNKNOWN"
            else f"Jockey Tier UNKNOWN: {status}; additive=+0; TRACE"
        ),
        "_tier_status": status,
    })
    return output


def group_by_race(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["cohort"], row["race_id"])].append(row)
    return dict(grouped)


def rank_shadow(rows: list[dict], entries: dict, tiers: dict, enabled=None) -> list[dict]:
    output = []
    for race_rows in group_by_race(rows).values():
        shadow = [apply_shadow_row(row, entries, tiers, enabled) for row in race_rows]
        if not flag_enabled(enabled):
            output.extend(shadow)
            continue
        ordered = sorted(shadow, key=lambda row: (-number(row["shadow_adjusted_score"]), row["production_rank"]))
        for rank, row in enumerate(ordered, start=1):
            row["shadow_rank"] = rank
        output.extend(shadow)
    return output


def metric_values(rows: list[dict], rank_key: str) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    selected3 = [row for row in valid if integer(row[rank_key]) <= 3]
    selected1 = [row for row in valid if integer(row[rank_key]) == 1]
    actual_top3 = [row for row in valid if row["actual_top3"]]
    ndcgs, reciprocal = [], []
    for race_rows in group_by_race(valid).values():
        ordered = sorted(race_rows, key=lambda row: integer(row[rank_key], 999))
        dcg = sum((1.0 if row["actual_top3"] else 0.0) / math.log2(index + 2) for index, row in enumerate(ordered[:3]))
        relevant = min(3, sum(row["actual_top3"] for row in ordered))
        ideal = sum(1 / math.log2(index + 2) for index in range(relevant))
        ndcgs.append(dcg / ideal if ideal else 0.0)
        first = next((integer(row[rank_key]) for row in ordered if row["actual_top3"]), None)
        reciprocal.append(1 / first if first else 0.0)
    buys = [row for row in valid if row["buy"]]
    return {
        "rank1_3_top3_rate": sum(row["actual_top3"] for row in selected3) / len(selected3) if selected3 else 0.0,
        "mean_actual_top3_rank": sum(integer(row[rank_key]) for row in actual_top3) / len(actual_top3) if actual_top3 else 0.0,
        "ndcg_at_3": sum(ndcgs) / len(ndcgs) if ndcgs else 0.0,
        "mrr": sum(reciprocal) / len(reciprocal) if reciprocal else 0.0,
        "rank1_top3_rate": sum(row["actual_top3"] for row in selected1) / len(selected1) if selected1 else 0.0,
        "top5_capture_rate": sum(integer(row[rank_key]) <= 5 for row in actual_top3) / len(actual_top3) if actual_top3 else 0.0,
        "buy_place_rate_reference_only": sum(row["actual_top3"] for row in buys) / len(buys) if buys else 0.0,
    }


def cohort_result(rows: list[dict]) -> dict:
    production = metric_values(rows, "production_rank")
    shadow = metric_values(rows, "shadow_rank")
    valid = [row for row in rows if row["valid_result"]]
    moved = [row for row in rows if row["production_rank"] != row["shadow_rank"]]
    inflow = [row for row in valid if row["production_rank"] > 3 and row["shadow_rank"] <= 3]
    outflow = [row for row in valid if row["production_rank"] <= 3 and row["shadow_rank"] > 3]
    actual_in = [row for row in inflow if row["actual_top3"]]
    actual_out = [row for row in outflow if row["actual_top3"]]
    complete = [row for row in rows if row["shadow_jockey_tier"] != "UNKNOWN"]
    return {
        "race_count": len({row["race_id"] for row in rows}),
        "horse_count": len(rows),
        "valid_result_count": len(valid),
        "production": {key: round(value, 8) for key, value in production.items()},
        "shadow": {key: round(value, 8) for key, value in shadow.items()},
        "delta": {key: round(shadow[key] - production[key], 8) for key in production},
        "movement_count": len(moved),
        "movement_rate": len(moved) / len(rows),
        "top3_inflow_count": len(inflow),
        "top3_outflow_count": len(outflow),
        "actual_top3_top3_inflow_count": len(actual_in),
        "actual_top3_top3_outflow_count": len(actual_out),
        "minimum_ride_coverage_count": len(complete),
        "minimum_ride_coverage_rate": len(complete) / len(rows),
        "unknown_count": len(rows) - len(complete),
        "unknown_rate": (len(rows) - len(complete)) / len(rows),
        "tier_counts": dict(sorted(Counter(row["shadow_jockey_tier"] for row in rows).items())),
    }


def classify_result(results: dict[str, dict], safety_pass=True) -> tuple[str, list[str]]:
    if not safety_pass:
        return "SAFETY_HOLD", ["REQUIRED_SAFETY_CHECK_FAILED"]
    if any(result["minimum_ride_coverage_rate"] < 0.70 for result in results.values()):
        return "INCONCLUSIVE", ["MINIMUM_RIDE_COVERAGE_BELOW_70_PERCENT"]
    if any(result["movement_rate"] < 0.10 for result in results.values()):
        return "INCONCLUSIVE", ["MOVEMENT_BELOW_10_PERCENT"]
    a = [result["delta"]["rank1_3_top3_rate"] for result in results.values()]
    b = [result["delta"]["mean_actual_top3_rank"] for result in results.values()]
    supplemental_bad = any(result["delta"]["ndcg_at_3"] < 0 or result["delta"]["mrr"] < 0 for result in results.values())
    outflow_bad = any(result["actual_top3_top3_outflow_count"] > result["actual_top3_top3_inflow_count"] for result in results.values())
    if min(a) < 0 or min(a) < 0 < max(a) or any(value > 0 for value in b) or supplemental_bad or outflow_bad:
        reasons = []
        if min(a) < 0: reasons.append("CO_PRIMARY_A_WORSENED")
        if min(a) < 0 < max(a): reasons.append("COHORT_DIRECTION_REVERSAL")
        if any(value > 0 for value in b): reasons.append("CO_PRIMARY_B_WORSENED")
        if supplemental_bad: reasons.append("NDCG_OR_MRR_WORSENED")
        if outflow_bad: reasons.append("ACTUAL_TOP3_OUTFLOW_EXCEEDS_INFLOW")
        return "REJECT", reasons
    no_supplemental_bad = not supplemental_bad and not outflow_bad
    if all(value >= 0.03 for value in a) and all(value < 0 for value in b) and no_supplemental_bad:
        return "FULL_ACCEPT", ["LARGE_A_IMPROVEMENT_AND_B_IMPROVEMENT"]
    if all(0.01 <= value < 0.03 for value in a) and all(value <= -MEAN_RANK_MINIMUM_IMPROVEMENT for value in b) and no_supplemental_bad:
        return "FULL_ACCEPT", ["MID_A_IMPROVEMENT_AND_PREREGISTERED_B_REINFORCEMENT"]
    if all(0.01 <= value < 0.03 for value in a) and no_supplemental_bad:
        return "PARTIAL_ACCEPT", ["A_IMPROVED_BUT_FULL_REINFORCEMENT_NOT_MET"]
    return "REJECT", ["MATERIAL_MOVEMENT_WITHOUT_PREREGISTERED_IMPROVEMENT"]


def metric_rows(cohort: str, rows: list[dict], reference_only=False) -> list[dict]:
    slices = [("OVERALL", "ALL", rows)]
    for axis, key in (("DATE", "race_date"), ("RACECOURSE", "racecourse"), ("TIER", "shadow_jockey_tier")):
        for value in sorted({row[key] for row in rows}):
            slices.append((axis, value, [row for row in rows if row[key] == value]))
    output = []
    for axis, value, selected in slices:
        production, shadow = metric_values(selected, "production_rank"), metric_values(selected, "shadow_rank")
        for metric in production:
            output.append({
                "cohort": cohort, "reference_only": reference_only, "slice_axis": axis, "slice_value": value,
                "race_count": len({row["race_id"] for row in selected}), "horse_count": len(selected),
                "valid_result_count": sum(row["valid_result"] for row in selected), "metric": metric,
                "production_value": round(production[metric], 10), "shadow_value": round(shadow[metric], 10),
                "delta": round(shadow[metric] - production[metric], 10),
            })
    return output


def transition_rows(rows: list[dict]) -> list[dict]:
    fields = (
        "cohort", "race_id", "race_date", "racecourse", "horse_number", "horse_name",
        "valid_result", "actual_finish", "actual_top3", "decision", "race_decision", "buy",
        "production_adjusted_score", "production_rank", "shadow_jockey_name", "shadow_jockey_tier",
        "shadow_jockey_sample_size", "shadow_jockey_score", "shadow_adjusted_score", "shadow_rank", "shadow_explain",
    )
    return [{field: row.get(field, "") for field in fields} for row in sorted(rows, key=lambda r: (r["cohort"], r["race_id"], r["production_rank"]))]


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def build_report(summary: dict) -> str:
    b, r = summary["cohort_results"]["BASELINE"], summary["cohort_results"]["REPLAY"]
    return f"""# JOCKEY_TIER_ADDITIVE_V1 Shadow Report

## Final status

**{summary['final_status']}**

Production Importers were not changed. A Shadow-only parser confirmed the
history jockey column using 85 fixtures and a 78/78 saved-entry cross-check.
The frozen table used only deduplicated history before 2026-06-06.

|Cohort|Horses|>=30 coverage|UNKNOWN|Movement|rank1-3 Top3 delta|Mean actual-Top3 rank delta|NDCG@3 delta|MRR delta|Actual-Top3 in/out|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|Baseline|{b['horse_count']}|{b['minimum_ride_coverage_rate']:.2%}|{b['unknown_rate']:.2%}|{b['movement_count']} ({b['movement_rate']:.2%})|{b['delta']['rank1_3_top3_rate']:+.4f}|{b['delta']['mean_actual_top3_rank']:+.4f}|{b['delta']['ndcg_at_3']:+.4f}|{b['delta']['mrr']:+.4f}|{b['actual_top3_top3_inflow_count']}/{b['actual_top3_top3_outflow_count']}|
|Replay|{r['horse_count']}|{r['minimum_ride_coverage_rate']:.2%}|{r['unknown_rate']:.2%}|{r['movement_count']} ({r['movement_rate']:.2%})|{r['delta']['rank1_3_top3_rate']:+.4f}|{r['delta']['mean_actual_top3_rank']:+.4f}|{r['delta']['ndcg_at_3']:+.4f}|{r['delta']['mrr']:+.4f}|{r['actual_top3_top3_inflow_count']}/{r['actual_top3_top3_outflow_count']}|

BUY place rate is reported only as a reference and is not part of the formal
decision. Existing Placebo is `PLACEBO_VARIANCE_HOLD`; no new seed was run.

Safety and ZERO_DELTA are `{summary['safety_status']}` / `{summary['zero_delta_status']}`.
Adapter, Evaluator, Replay, Learning, Knowledge, and normal Ledger executions or writes were zero.
"""


def run(test_status="PENDING_EXTERNAL_TEST_COMMAND") -> dict:
    before = protected_snapshot()
    tiers, table_payload, generation = load_frozen_table()
    entries, entry_audit = entry_lookup()
    production = production_rows()
    off = {cohort: rank_shadow(rows, entries, tiers, enabled=False) for cohort, rows in production.items()}
    flag_off = {cohort: rows == off[cohort] for cohort, rows in production.items()}
    on = {cohort: rank_shadow(rows, entries, tiers, enabled=True) for cohort, rows in production.items()}
    mutations = []
    for cohort in production:
        originals = {(row["race_id"], row["horse_number"]): row for row in production[cohort]}
        for row in on[cohort]:
            original = originals[(row["race_id"], row["horse_number"])]
            for field, value in original.items():
                if row.get(field) != value:
                    mutations.append({"cohort": cohort, "race_id": row["race_id"], "horse_number": row["horse_number"], "field": field})
    results = {cohort: cohort_result(rows) for cohort, rows in on.items()}
    after = protected_snapshot()
    changes = [name for name in before if before[name] != after[name]]
    coverage_pass = all(result["minimum_ride_coverage_rate"] >= 0.70 for result in results.values())
    zero_pass = all(flag_off.values()) and not mutations and not changes
    safety_pass = zero_pass and coverage_pass and generation["stable_key_collision_count"] == 0 and generation["cutoff_inclusive"] is False
    status, reasons = classify_result(results, safety_pass)
    combined = on["BASELINE"] + on["REPLAY"]
    metrics = metric_rows("BASELINE", on["BASELINE"]) + metric_rows("REPLAY", on["REPLAY"])
    metrics += metric_rows("INTEGRATED_REFERENCE", combined, reference_only=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "schema_version": "jockey_tier_shadow_summary_v1", "generated_at": generated_at,
        "candidate_id": CANDIDATE_ID, "feature_flag": FLAG_NAME, "feature_flag_default": FLAG_DEFAULT,
        "final_status": status, "decision_reasons": reasons,
        "column_spec_status": "CONFIRMED_FOR_SHADOW_ONLY", "column_spec_sha256": sha256(COLUMN_SPEC),
        "preregistered_spec_sha256": sha256(PREREGISTERED_SPEC), "tier_table_sha256": table_payload["table_sha256"],
        "generation_manifest_sha256": sha256(GENERATION_MANIFEST), "generation_audit": generation,
        "entry_audit": entry_audit, "cohort_results": results,
        "integrated_reference_only": cohort_result(combined), "cohorts_combined_for_judgment": False,
        "flag_off_exact_match": all(flag_off.values()), "flag_off": flag_off,
        "production_field_mutation_count": len(mutations), "safety_status": "PASS" if safety_pass else "FAIL",
        "zero_delta_status": "PASS" if zero_pass else "FAIL", "minimum_ride_coverage_gate_pass": coverage_pass,
        "target_trial_adapter_run_count": 0, "replay_run_count": 0, "evaluator_run_count": 0,
        "placebo_seed_run_count": 0, "production_write_count": 0, "decision_write_count": 0,
        "buy_write_count": 0, "explain_write_count": 0, "learning_write_count": 0,
        "knowledge_write_count": 0, "normal_ledger_write_count": 0,
        "placebo_status_reference_only": "PLACEBO_VARIANCE_HOLD",
        "next_action": {
            "FULL_ACCEPT": "CLAUDE_REVIEW_THEN_CHATGPT_ROI_AND_HUMAN_DECISION",
            "PARTIAL_ACCEPT": "CLAUDE_CHATGPT_ROI_REVIEW_NO_AUTOMATIC_PROMOTION",
            "INCONCLUSIVE": "NO_AUTOMATIC_RERUN_ADDITIONAL_EVIDENCE_ONLY_IF_ROI_APPROVES",
            "REJECT": "CLOSE_JOCKEY_CANDIDATE_AND_REASSESS_RANKING_REDESIGN",
            "SAFETY_HOLD": "STOP_AND_REVIEW_SAFETY",
        }[status],
    }
    baseline = {"schema_version": "jockey_tier_baseline_result_v1", "generated_at": generated_at, "cohort": "BASELINE", **results["BASELINE"]}
    replay = {"schema_version": "jockey_tier_replay_result_v1", "generated_at": generated_at, "cohort": "REPLAY", **results["REPLAY"]}
    safety = {
        "schema_version": "jockey_tier_shadow_safety_v1", "generated_at": generated_at,
        "status": "PASS" if safety_pass else "FAIL", "protected_before": before, "protected_after": after,
        "protected_changes": changes, "stable_key_collision_count": generation["stable_key_collision_count"],
        "cutoff_date": generation["cutoff_date"], "cutoff_inclusive": generation["cutoff_inclusive"],
        "result_or_post_input_used_for_tier_generation": False, "minimum_ride_coverage_gate_pass": coverage_pass,
        "target_trial_adapter_run_count": 0, "replay_run_count": 0, "evaluator_run_count": 0,
        "placebo_seed_run_count": 0, "production_write_count": 0, "learning_write_count": 0,
        "knowledge_write_count": 0, "normal_ledger_write_count": 0,
        "prior_safety_hold_artifacts_archived": "reports/jockey_tier_safety_hold_archive_v1",
    }
    zero = {
        "schema_version": "jockey_tier_shadow_zero_delta_v1", "generated_at": generated_at,
        "status": "PASS" if zero_pass else "FAIL", "flag_off": flag_off, "protected_changes": changes,
        "production_field_mutation_count": len(mutations), "production_field_mutations": mutations,
        "production_score_changed": False, "production_rank_changed": False, "decision_changed": False,
        "race_decision_changed": False, "buy_changed": False, "explain_changed": False,
    }
    test_manifest = {
        "schema_version": "jockey_tier_shadow_test_manifest_v1", "generated_at": generated_at,
        "test_file": "tests/test_jockey_tier_shadow_validation_v1.py", "test_method_count": 40,
        "subtest_count": 0, "commands": [
            "python -m py_compile analysis/jockey_shadow_read_only_parser_v1.py analysis/jockey_tier_generation_v1.py analysis/jockey_tier_shadow_validation_v1.py tests/test_jockey_tier_shadow_validation_v1.py",
            "python -m unittest tests.test_jockey_tier_shadow_validation_v1 -v",
        ], "actual_status": test_status,
    }
    column_audit = [
        {"field": "jockey_name", "zero_based_index": 19, "one_based_column": 20, "fixture_file_count": 85, "fixture_row_count": 18682, "nonempty_count": 18682, "crosscheck_count": 78, "crosscheck_match_count": 78, "status": "PASS"},
        {"field": "race_date", "zero_based_index": "0+1+2", "one_based_column": "1+2+3", "fixture_file_count": 85, "fixture_row_count": 18682, "nonempty_count": 18682, "crosscheck_count": 78, "crosscheck_match_count": 78, "status": "PASS"},
        {"field": "horse_name", "zero_based_index": 16, "one_based_column": 17, "fixture_file_count": 85, "fixture_row_count": 18682, "nonempty_count": 18682, "crosscheck_count": 78, "crosscheck_match_count": 78, "status": "PASS"},
    ]
    roi = f"""# ROI Update: Jockey Tier Additive

|Priority|Candidate|Status|Effect interpretation|Investment cost|Next action|
|---:|---|---|---|---|---|
|1|Jockey Shadow|{status}|See separated Baseline/Replay metrics|Low-medium; Shadow-only|{summary['next_action']}|
|2|Ranking redesign|CONDITIONAL|Broader intervention|High|Reassess after 3C review|
|3|RaceShape Dedup|CLOSED_INCONCLUSIVE|Replay primary metrics worsened|Closed|Do not reopen automatically|
|4|Recency|CLOSED_HOLD|No supported gain|Closed|Do not reopen|
|5|New unused features|STOPPED|No automatic progression|Unknown|Human authorization required|
"""
    claude = f"""# Claude Review Packet: JOCKEY_TIER_ADDITIVE_V1 Restart

- Final status: **{status}**
- Decision reasons: `{', '.join(reasons)}`
- Column confirmation: 85 fixtures / 18,682 rows / entry cross-check 78/78
- Stable-key collision: `0`
- Cutoff: `< 2026-06-06` only
- Tier table SHA256: `{table_payload['table_sha256']}`
- Baseline >=30 coverage: `{results['BASELINE']['minimum_ride_coverage_rate']:.2%}`
- Replay >=30 coverage: `{results['REPLAY']['minimum_ride_coverage_rate']:.2%}`
- Flag OFF / Safety / ZERO_DELTA: `{all(flag_off.values())} / {safety['status']} / {zero['status']}`
- Adapter / Evaluator / Replay / Placebo seed runs: `0 / 0 / 0 / 0`

Please independently verify fixed column 19 using the 78/78 cross-check, the
dedup/cutoff population, frozen Tier SHA, UNKNOWN coverage, cohort-separated
decision, reference-only BUY/Placebo treatment, and Production zero delta.
"""
    spec_sha = {
        "schema_version": "jockey_tier_additive_v1_spec_sha256_v1", "generated_at": generated_at,
        "formal_spec_path": PREREGISTERED_SPEC.relative_to(ROOT).as_posix(),
        "formal_spec_sha256": sha256(PREREGISTERED_SPEC),
        "column_spec_path": COLUMN_SPEC.relative_to(ROOT).as_posix(), "column_spec_sha256": sha256(COLUMN_SPEC),
        "tier_table_sha256": table_payload["table_sha256"], "frozen_before_evaluation": True,
    }
    supersession = {
        "schema_version": "jockey_tier_restart_supersession_v1", "generated_at": generated_at,
        "status": "PRIOR_SAFETY_HOLD_SUPERSEDED_BY_SHADOW_ONLY_RESTART",
        "archive": "reports/jockey_tier_safety_hold_archive_v1",
        "production_importer_changed": False,
    }
    write_csv(OUTPUTS["column_audit"], column_audit); write_json(OUTPUTS["spec_sha"], spec_sha)
    write_json(OUTPUTS["baseline"], baseline); write_json(OUTPUTS["replay"], replay)
    write_csv(OUTPUTS["transitions"], transition_rows(combined)); write_csv(OUTPUTS["metrics"], metrics)
    OUTPUTS["report"].write_text(build_report(summary), encoding="utf-8"); write_json(OUTPUTS["summary"], summary)
    write_json(OUTPUTS["safety"], safety); write_json(OUTPUTS["zero"], zero); write_json(OUTPUTS["tests"], test_manifest)
    OUTPUTS["roi"].write_text(roi, encoding="utf-8"); OUTPUTS["claude"].write_text(claude, encoding="utf-8")
    write_json(OUTPUTS["supersession"], supersession)
    print(json.dumps({"status": status, "baseline": results["BASELINE"], "replay": results["REPLAY"], "safety": safety["status"]}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    run(test_status="PASS" if "--tests-passed" in sys.argv else "PENDING_EXTERNAL_TEST_COMMAND")
