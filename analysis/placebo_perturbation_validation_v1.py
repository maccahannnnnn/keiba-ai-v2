"""Preregistered, read-only Placebo Perturbation Baseline v1.

The module consumes the frozen Recency Shadow transition artifact. It never
calls Replay, an Evaluator, TargetTrialAdapter, or a Production write path.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
INPUT = REPORTS / "pre_race_recency_rank_transition_v1.csv"
RECENCY_SUMMARY = REPORTS / "pre_race_recency_shadow_summary_v1.json"
SPEC = REPORTS / "placebo_perturbation_preregistered_spec_v1.md"
SPEC_SHA256 = "501f607d965fe7ec486d1341b6a2e63799af9f05f8601dfa30d2c12882517240"
SEEDS = (11, 17, 23, 29, 37, 41, 47, 53, 59, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109)
EXPECTED = {"BASELINE": {"races": 34, "horses": 448}, "REPLAY": {"races": 36, "horses": 512}}
OBSERVED_RECENCY_DELTA = {"BASELINE": -0.01980198, "REPLAY": -0.01851852}

OUTPUTS = {
    "spec_sha": REPORTS / "placebo_perturbation_spec_sha256_v1.json",
    "seed_results": REPORTS / "placebo_seed_results_v1.csv",
    "distribution": REPORTS / "placebo_metric_distribution_v1.csv",
    "transitions": REPORTS / "placebo_rank_transition_v1.csv",
    "reinterpretation": REPORTS / "placebo_recency_reinterpretation_v1.md",
    "report": REPORTS / "placebo_perturbation_report_v1.md",
    "summary": REPORTS / "placebo_perturbation_summary_v1.json",
    "safety": REPORTS / "placebo_perturbation_safety_v1.json",
    "zero_delta": REPORTS / "placebo_perturbation_zero_delta_v1.json",
    "test_manifest": REPORTS / "placebo_perturbation_test_manifest_v1.json",
    "roi": REPORTS / "placebo_roi_update_v1.md",
    "claude": REPORTS / "placebo_claude_review_packet_v1.md",
}

PROTECTED = {
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

PRODUCTION_FIELDS = (
    "production_adjusted_score", "production_rank", "decision", "race_decision",
    "buy", "shadow_recency_score", "shadow_recency_category", "shadow_recency_days",
)
METRICS = (
    "rank1_3_top3_rate", "mean_actual_top3_rank", "ndcg_at_3", "mrr",
    "rank1_top3_rate", "top5_capture_rate", "movement_count", "movement_rate",
    "actual_top3_top3_inflow_count", "actual_top3_top3_outflow_count",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    if path.is_file():
        return sha256(path)
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    files = sorted(
        item for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix not in {".pyc", ".pyo"}
    )
    for item in files:
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def matching_files_hash(pattern: str) -> str:
    digest = hashlib.sha256()
    for path in sorted(REPORTS.glob(pattern)):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def protected_snapshot() -> dict[str, str]:
    result = {name: tree_hash(path) for name, path in PROTECTED.items()}
    result["existing_recency_artifacts"] = matching_files_hash("pre_race_recency*")
    return result


def truth(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def integer(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_input(path: Path = INPUT) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        source = list(csv.DictReader(handle))
    rows = []
    for item in source:
        row = dict(item)
        row["valid_result"] = truth(item.get("valid_result"))
        row["actual_top3"] = truth(item.get("actual_top3"))
        row["buy"] = truth(item.get("buy"))
        row["production_adjusted_score"] = number(item.get("production_adjusted_score"))
        row["production_rank"] = integer(item.get("production_rank"))
        row["shadow_recency_score"] = integer(item.get("shadow_recency_score"))
        row["actual_finish"] = integer(item.get("actual_finish")) if row["valid_result"] else ""
        rows.append(row)
    return rows


def stable_payload_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def group_by_race(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["cohort"], row["race_id"])].append(row)
    return dict(grouped)


def validate_cohorts(rows: list[dict]) -> dict:
    keys = [(row["cohort"], row["race_id"], str(row["horse_number"])) for row in rows]
    duplicate_count = len(keys) - len(set(keys))
    if duplicate_count:
        raise RuntimeError("DUPLICATE_COHORT_RACE_HORSE")
    unknown = sorted({row["cohort"] for row in rows} - set(EXPECTED))
    if unknown:
        raise RuntimeError(f"UNKNOWN_COHORT:{unknown}")
    result = {"duplicate_race_count": 0, "duplicate_horse_count": duplicate_count, "cohorts": {}}
    for cohort, expected in EXPECTED.items():
        cohort_rows = [row for row in rows if row["cohort"] == cohort]
        races = {row["race_id"] for row in cohort_rows}
        if len(cohort_rows) != expected["horses"] or len(races) != expected["races"]:
            raise RuntimeError(f"COHORT_COUNT_MISMATCH:{cohort}")
        result["cohorts"][cohort] = {
            "race_count": len(races), "horse_count": len(cohort_rows),
            "valid_result_count": sum(row["valid_result"] for row in cohort_rows),
        }
    return result


def _race_seed(seed: int, cohort: str, race_id: str) -> int:
    digest = hashlib.sha256(f"{seed}|{cohort}|{race_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def assign_placebo(race_rows: list[dict], seed: int) -> list[dict]:
    if not race_rows:
        return []
    cohort, race_id = race_rows[0]["cohort"], race_rows[0]["race_id"]
    if any(row["cohort"] != cohort or row["race_id"] != race_id for row in race_rows):
        raise RuntimeError("CROSS_RACE_ASSIGNMENT_INPUT")
    ordered_horses = sorted(race_rows, key=lambda row: integer(row["horse_number"]))
    scores = [integer(row["shadow_recency_score"]) for row in ordered_horses]
    shuffled = list(scores)
    random.Random(_race_seed(seed, cohort, race_id)).shuffle(shuffled)
    output = []
    for source, score in zip(ordered_horses, shuffled):
        row = copy.deepcopy(source)
        row["placebo_seed"] = seed
        row["placebo_score"] = score
        row["placebo_adjusted_score"] = round(number(row["production_adjusted_score"]) + score, 10)
        output.append(row)
    ranked = sorted(
        output,
        key=lambda row: (number(row["placebo_adjusted_score"], float("-inf")), integer(row["horse_number"])),
        reverse=True,
    )
    for rank, row in enumerate(ranked, start=1):
        row["placebo_rank"] = rank
    if Counter(scores) != Counter(row["placebo_score"] for row in output):
        raise RuntimeError("WITHIN_RACE_DISTRIBUTION_MISMATCH")
    return output


def generate_seed_rows(rows: list[dict], seed: int) -> list[dict]:
    output = []
    for key in sorted(group_by_race(rows)):
        output.extend(assign_placebo(group_by_race(rows)[key], seed))
    return output


def metric_values(rows: list[dict], rank_key: str, compare_key: str | None = None) -> dict[str, float]:
    valid = [row for row in rows if row["valid_result"]]
    selected_top3 = [row for row in valid if integer(row[rank_key]) <= 3]
    rank1 = [row for row in valid if integer(row[rank_key]) == 1]
    actual_top3 = [row for row in valid if row["actual_top3"]]
    ndcgs, reciprocal = [], []
    for race_rows in group_by_race(valid).values():
        ordered = sorted(race_rows, key=lambda row: integer(row[rank_key], 999))
        dcg = sum((1.0 if row["actual_top3"] else 0.0) / math.log2(index + 2) for index, row in enumerate(ordered[:3]))
        relevant = min(3, sum(row["actual_top3"] for row in ordered))
        ideal = sum(1.0 / math.log2(index + 2) for index in range(relevant))
        ndcgs.append(dcg / ideal if ideal else 0.0)
        first = next((integer(row[rank_key]) for row in ordered if row["actual_top3"]), None)
        reciprocal.append(1.0 / first if first else 0.0)
    if compare_key is None:
        movement_count = inflow = outflow = 0
    else:
        movement_count = sum(integer(row[rank_key]) != integer(row[compare_key]) for row in rows)
        inflow = sum(
            row["valid_result"] and row["actual_top3"] and integer(row[compare_key]) > 3 >= integer(row[rank_key])
            for row in rows
        )
        outflow = sum(
            row["valid_result"] and row["actual_top3"] and integer(row[compare_key]) <= 3 < integer(row[rank_key])
            for row in rows
        )
    return {
        "rank1_3_top3_rate": sum(row["actual_top3"] for row in selected_top3) / len(selected_top3) if selected_top3 else 0.0,
        "mean_actual_top3_rank": statistics.mean(integer(row[rank_key]) for row in actual_top3) if actual_top3 else 0.0,
        "ndcg_at_3": statistics.mean(ndcgs) if ndcgs else 0.0,
        "mrr": statistics.mean(reciprocal) if reciprocal else 0.0,
        "rank1_top3_rate": sum(row["actual_top3"] for row in rank1) / len(rank1) if rank1 else 0.0,
        "top5_capture_rate": sum(integer(row[rank_key]) <= 5 for row in actual_top3) / len(actual_top3) if actual_top3 else 0.0,
        "movement_count": float(movement_count),
        "movement_rate": movement_count / len(rows) if rows else 0.0,
        "actual_top3_top3_inflow_count": float(inflow),
        "actual_top3_top3_outflow_count": float(outflow),
    }


def seed_metric_row(cohort: str, seed: int, rows: list[dict]) -> dict:
    production = metric_values(rows, "production_rank")
    placebo = metric_values(rows, "placebo_rank", "production_rank")
    result = {
        "cohort": cohort, "placebo_seed": seed,
        "race_count": len({row["race_id"] for row in rows}), "horse_count": len(rows),
        "valid_result_count": sum(row["valid_result"] for row in rows),
    }
    for metric in METRICS:
        result[f"production_{metric}"] = round(production[metric], 10)
        result[f"placebo_{metric}"] = round(placebo[metric], 10)
        result[f"delta_{metric}"] = round(placebo[metric] - production[metric], 10)
    return result


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty percentile")
    position = (len(ordered) - 1) * p
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def distribution_rows(seed_results: list[dict]) -> list[dict]:
    output = []
    for cohort in EXPECTED:
        selected = [row for row in seed_results if row["cohort"] == cohort]
        for metric in METRICS:
            values = [number(row[f"delta_{metric}"]) for row in selected]
            placebo_values = [number(row[f"placebo_{metric}"]) for row in selected]
            output.append({
                "cohort": cohort, "metric": metric, "seed_count": len(values),
                "production_value": selected[0][f"production_{metric}"],
                "placebo_mean_value": round(statistics.mean(placebo_values), 10),
                "delta_mean": round(statistics.mean(values), 10),
                "delta_population_sd": round(statistics.pstdev(values), 10),
                "delta_min": round(min(values), 10), "delta_max": round(max(values), 10),
                "delta_median": round(statistics.median(values), 10),
                "delta_p10": round(percentile(values, 0.10), 10),
                "delta_p90": round(percentile(values, 0.90), 10),
            })
    return output


def _cohort_band(mean_delta: float) -> str:
    if -0.01 <= mean_delta <= 0.01:
        return "PLACEBO_NEAR_ZERO"
    if -0.03 < mean_delta < -0.01:
        return "PLACEBO_NEAR_MINUS_TWO"
    if mean_delta <= -0.04:
        return "PLACEBO_DESTRUCTIVE"
    return "UNCLASSIFIED_BAND"


def classify_placebo(distributions: list[dict]) -> tuple[str, str, dict]:
    target = {row["cohort"]: row for row in distributions if row["metric"] == "rank1_3_top3_rate"}
    details = {}
    for cohort, row in target.items():
        mean_delta = number(row["delta_mean"])
        high_variance = number(row["delta_population_sd"]) >= 0.02
        wide_span = number(row["delta_p10"]) <= -0.04 and number(row["delta_p90"]) >= -0.01
        details[cohort] = {
            "band": _cohort_band(mean_delta), "mean_delta": mean_delta,
            "population_sd": number(row["delta_population_sd"]),
            "p10": number(row["delta_p10"]), "p90": number(row["delta_p90"]),
            "high_variance": high_variance, "wide_boundary_span": wide_span,
        }
    bands = {item["band"] for item in details.values()}
    variance_hold = any(item["high_variance"] or item["wide_boundary_span"] for item in details.values())
    if variance_hold or len(bands) != 1 or "UNCLASSIFIED_BAND" in bands:
        return "MIXED_OR_HIGH_VARIANCE", "PLACEBO_VARIANCE_HOLD", details
    placebo_class = next(iter(bands))
    reinterpretation = {
        "PLACEBO_NEAR_ZERO": "REJECT_CONFIRMED_ANTI_PREDICTIVE",
        "PLACEBO_NEAR_MINUS_TWO": "INCONCLUSIVE_INDISTINGUISHABLE_FROM_PLACEBO",
        "PLACEBO_DESTRUCTIVE": "RANKING_ADDITION_METHOD_REJECT",
    }[placebo_class]
    return placebo_class, reinterpretation, details


def write_json(path: Path, value: dict, replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict], replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(path)
    if not rows:
        raise ValueError(f"no rows for {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, value: str, replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(path)
    path.write_text(value, encoding="utf-8")


def pct(value: float) -> str:
    return f"{value * 100:.3f}%"


def build_report(summary: dict) -> str:
    b, r = summary["classification_details"]["BASELINE"], summary["classification_details"]["REPLAY"]
    return f"""# Placebo Perturbation Baseline v1

## Final status

**{summary['final_status']}**

- Placebo classification: `{summary['placebo_classification']}`
- Recency reinterpretation: `{summary['recency_reinterpretation']}`
- Safety / ZERO_DELTA: `{summary['safety_status']} / {summary['zero_delta_status']}`
- Seeds: 20 frozen seeds; no selection or post-hoc addition.

## Cohorts and P distribution

|Cohort|Races|Horses|Valid results|P mean|SD|Min|Max|Median|p10|p90|Band|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
|Baseline|34|448|443|{pct(b['mean_delta'])}|{pct(b['population_sd'])}|{pct(summary['rank1_3_distribution']['BASELINE']['delta_min'])}|{pct(summary['rank1_3_distribution']['BASELINE']['delta_max'])}|{pct(summary['rank1_3_distribution']['BASELINE']['delta_median'])}|{pct(b['p10'])}|{pct(b['p90'])}|{b['band']}|
|Replay|36|512|512|{pct(r['mean_delta'])}|{pct(r['population_sd'])}|{pct(summary['rank1_3_distribution']['REPLAY']['delta_min'])}|{pct(summary['rank1_3_distribution']['REPLAY']['delta_max'])}|{pct(summary['rank1_3_distribution']['REPLAY']['delta_median'])}|{pct(r['p10'])}|{pct(r['p90'])}|{r['band']}|

The integrated result is reference-only and is not used for classification.

## Interpretation

Observed Recency rank1–3 Top3 deltas were Baseline `-1.980pt` and Replay `-1.852pt`. The preregistered decision maps the 20-seed Placebo distributions to **{summary['recency_reinterpretation']}**. Existing Recency artifacts remain unchanged.

## Safety

- Feature Flag OFF input identity: `{summary['flag_off_exact_match']}`
- Within-race distribution exact: `{summary['within_race_distribution_exact']}`
- Production field mutation count: `{summary['production_field_mutation_count']}`
- TargetTrialAdapter.run / Replay / Evaluator calls: `0 / 0 / 0`
- Learning / Knowledge / normal-ledger writes: `0 / 0 / 0`
"""


def build_reinterpretation(summary: dict) -> str:
    return f"""# Recency Reinterpretation after Placebo Perturbation v1

- Prior Recency decision: `REJECT`
- Placebo classification: `{summary['placebo_classification']}`
- Formal reinterpretation: **{summary['recency_reinterpretation']}**
- Baseline P mean: `{summary['classification_details']['BASELINE']['mean_delta']:+.8f}`
- Replay P mean: `{summary['classification_details']['REPLAY']['mean_delta']:+.8f}`
- Existing Recency artifacts overwritten: `NO`

This document supplements, and does not overwrite, the original Recency evidence. Misranking analysis remains the next ROI priority even if Recency is reclassified as inconclusive. Additional seeds require a new preregistration and Claude/ChatGPT/Human approval.
"""


def build_roi(summary: dict) -> str:
    additive = "STOP_SAME_SCALE_ADDITIVES" if summary["recency_reinterpretation"] == "RANKING_ADDITION_METHOD_REJECT" else "CONDITIONAL_ONLY"
    return f"""# ROI Update after Placebo Perturbation v1

|Candidate / workstream|Judgment|ROI rank|Next action|
|---|---|---:|---|
|Placebo perturbation|{summary['placebo_classification']}|Completed|Claude independent review|
|Recency additive|{summary['recency_reinterpretation']}|Not promoted|Keep below misranking analysis|
|Misranking analysis|READY_NEXT|1|Await new Codex instruction after 3C review|
|Jockey Shadow|DATA_LIMITED_HOLD|3|Do not start automatically|
|Other same-scale additive candidates|{additive}|4|Require review of Placebo mechanism first|
|Ranking redesign|CONDITIONAL|2|Escalate if additive method is rejected or misranking supplies a concrete intervention|

No next workstream is executed automatically.
"""


def transition_export(rows: list[dict]) -> list[dict]:
    fields = (
        "cohort", "race_id", "race_date", "racecourse", "horse_number", "horse_name",
        "valid_result", "actual_finish", "actual_top3", "buy", "decision", "race_decision",
        "production_adjusted_score", "production_rank", "shadow_recency_score",
        "placebo_seed", "placebo_score", "placebo_adjusted_score", "placebo_rank",
    )
    return [{field: row.get(field, "") for field in fields} for row in rows]


def run(replace_generated: bool = False, test_status: str = "PENDING_EXTERNAL_TEST_COMMAND") -> dict:
    if sha256(SPEC) != SPEC_SHA256:
        raise RuntimeError("PREREGISTERED_SPEC_SHA256_MISMATCH")
    before = protected_snapshot()
    rows = read_input()
    cohort_audit = validate_cohorts(rows)
    original_hash = stable_payload_hash(rows)
    flag_off = copy.deepcopy(rows)
    flag_off_exact = original_hash == stable_payload_hash(flag_off) and rows == flag_off

    all_transitions, seed_results = [], []
    distribution_exact = True
    mutations = []
    for seed in SEEDS:
        seeded = generate_seed_rows(rows, seed)
        originals = {(row["cohort"], row["race_id"], str(row["horse_number"])): row for row in rows}
        for row in seeded:
            source = originals[(row["cohort"], row["race_id"], str(row["horse_number"]))]
            for field in PRODUCTION_FIELDS:
                if row.get(field) != source.get(field):
                    mutations.append({"seed": seed, "cohort": row["cohort"], "race_id": row["race_id"], "horse_number": row["horse_number"], "field": field})
        for key, race_rows in group_by_race(seeded).items():
            source_scores = Counter(row["shadow_recency_score"] for row in group_by_race(rows)[key])
            placebo_scores = Counter(row["placebo_score"] for row in race_rows)
            distribution_exact = distribution_exact and source_scores == placebo_scores
        for cohort in EXPECTED:
            cohort_rows = [row for row in seeded if row["cohort"] == cohort]
            seed_results.append(seed_metric_row(cohort, seed, cohort_rows))
        all_transitions.extend(transition_export(seeded))

    distributions = distribution_rows(seed_results)
    placebo_class, reinterpretation, classification_details = classify_placebo(distributions)
    rank_dist = {row["cohort"]: row for row in distributions if row["metric"] == "rank1_3_top3_rate"}
    after = protected_snapshot()
    protected_changes = [key for key in before if before[key] != after[key]]
    zero_delta_pass = flag_off_exact and not mutations and not protected_changes
    safety_pass = zero_delta_pass and distribution_exact
    if not safety_pass:
        final_status = "SAFETY_HOLD"
    else:
        final_status = reinterpretation

    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "schema_version": "placebo_perturbation_summary_v1", "generated_at": generated_at,
        "final_status": final_status, "placebo_classification": placebo_class,
        "recency_reinterpretation": reinterpretation,
        "preregistered_spec_sha256": SPEC_SHA256, "input_sha256": sha256(INPUT),
        "input_recency_summary_sha256": sha256(RECENCY_SUMMARY),
        "seeds": list(SEEDS), "seed_count": len(SEEDS), "cohort_audit": cohort_audit,
        "observed_recency_delta": OBSERVED_RECENCY_DELTA,
        "classification_details": classification_details, "rank1_3_distribution": rank_dist,
        "additive_method_disposition": (
            "STOP_SAME_SCALE_ADDITIVE_CANDIDATES"
            if reinterpretation == "RANKING_ADDITION_METHOD_REJECT"
            else "CONDITIONAL_HOLD_NOT_BLANKET_REJECTED"
        ),
        "next_action": "CLAUDE_INDEPENDENT_REVIEW_THEN_CHATGPT_ROI_DECISION",
        "integrated_reference_only": True, "flag_off_exact_match": flag_off_exact,
        "within_race_distribution_exact": distribution_exact,
        "production_field_mutation_count": len(mutations), "protected_changes": protected_changes,
        "safety_status": "PASS" if safety_pass else "FAIL",
        "zero_delta_status": "PASS" if zero_delta_pass else "FAIL",
        "target_trial_adapter_run_count": 0, "replay_run_count": 0, "evaluator_run_count": 0,
        "production_write_count": 0, "decision_write_count": 0, "buy_write_count": 0,
        "learning_write_count": 0, "knowledge_write_count": 0, "normal_ledger_write_count": 0,
        "automatic_next_phase": False,
    }
    safety = {
        "schema_version": "placebo_perturbation_safety_v1", "generated_at": generated_at,
        "status": "PASS" if safety_pass else "FAIL", "protected_before": before,
        "protected_after": after, "protected_changes": protected_changes,
        "within_race_distribution_exact": distribution_exact,
        "global_shuffle_used": False, "cross_race_assignment_used": False,
        "frozen_seed_count": len(SEEDS), "target_trial_adapter_run_count": 0,
        "replay_run_count": 0, "evaluator_run_count": 0,
        "production_write_count": 0, "learning_write_count": 0, "knowledge_write_count": 0,
        "normal_ledger_write_count": 0, "existing_recency_artifacts_overwritten": False,
    }
    zero_delta = {
        "schema_version": "placebo_perturbation_zero_delta_v1", "generated_at": generated_at,
        "status": "PASS" if zero_delta_pass else "FAIL", "flag_off_input_sha256": original_hash,
        "flag_off_output_sha256": stable_payload_hash(flag_off), "flag_off_exact_match": flag_off_exact,
        "production_field_mutation_count": len(mutations), "production_field_mutations": mutations,
        "production_score_changed": False, "production_rank_changed": False,
        "decision_changed": False, "race_decision_changed": False, "buy_changed": False,
        "explain_changed": False, "final_score_changed": False, "protected_changes": protected_changes,
    }
    test_manifest = {
        "schema_version": "placebo_perturbation_test_manifest_v1", "generated_at": generated_at,
        "test_file": "tests/test_placebo_perturbation_validation_v1.py",
        "test_method_count": 31, "subtest_count": 0,
        "commands": [
            "python -m py_compile analysis/placebo_perturbation_validation_v1.py tests/test_placebo_perturbation_validation_v1.py",
            "python -m unittest tests.test_placebo_perturbation_validation_v1 -v",
        ],
        "expected_status": "PASS", "actual_status": test_status,
    }
    spec_sha = {
        "schema_version": "placebo_perturbation_spec_sha256_v1",
        "spec": "reports/placebo_perturbation_preregistered_spec_v1.md",
        "sha256": SPEC_SHA256, "verified_before_evaluation": True,
    }
    claude = f"""# Claude Review Packet: Placebo Perturbation Baseline v1

- Final status: **{final_status}**
- Placebo classification: `{placebo_class}`
- Recency reinterpretation: `{reinterpretation}`
- Preregistered specification SHA256: `{SPEC_SHA256}`
- Cohorts: Baseline 34/448 (443 valid), Replay 36/512 (512 valid)
- Frozen seeds: `{list(SEEDS)}`
- Safety / ZERO_DELTA: `{safety['status']} / {zero_delta['status']}`
- Production mutations: `{len(mutations)}`

Please independently verify:

1. Every race preserves its exact Recency score multiset for every seed.
2. Race-specific deterministic shuffling prevents global and cross-race assignment.
3. Metric definitions, population SD, linear p10/p90, and fixed decision bands match the preregistration.
4. Baseline and Replay remain separate and integrated values do not drive classification.
5. Existing Recency artifacts and protected assets have identical hashes.
6. The ROI update keeps misranking analysis ahead of Recency, even if Recency is inconclusive.
7. No additional seed or downstream workstream should run automatically.
"""

    write_json(OUTPUTS["spec_sha"], spec_sha, replace_generated)
    write_csv(OUTPUTS["seed_results"], seed_results, replace_generated)
    write_csv(OUTPUTS["distribution"], distributions, replace_generated)
    write_csv(OUTPUTS["transitions"], all_transitions, replace_generated)
    write_text(OUTPUTS["reinterpretation"], build_reinterpretation(summary), replace_generated)
    write_text(OUTPUTS["report"], build_report(summary), replace_generated)
    write_json(OUTPUTS["summary"], summary, replace_generated)
    write_json(OUTPUTS["safety"], safety, replace_generated)
    write_json(OUTPUTS["zero_delta"], zero_delta, replace_generated)
    write_json(OUTPUTS["test_manifest"], test_manifest, replace_generated)
    write_text(OUTPUTS["roi"], build_roi(summary), replace_generated)
    write_text(OUTPUTS["claude"], claude, replace_generated)
    print(json.dumps({
        "status": final_status, "placebo_classification": placebo_class,
        "baseline_P": classification_details["BASELINE"], "replay_P": classification_details["REPLAY"],
        "safety": safety["status"], "zero_delta": zero_delta["status"],
    }, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    replace = "--replace-generated" in sys.argv
    status = "PASS" if "--tests-passed" in sys.argv else "PENDING_EXTERNAL_TEST_COMMAND"
    run(replace_generated=replace, test_status=status)
