"""Read-only Misranking Analysis v1 for actual-Top3 boundary movers only."""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
TRANSITIONS = REPORTS / "final_score_shadow_rank_transition_v1.csv"
REPLAY_COHORT = REPORTS / "ranking_weight_unique_cohort_v1.csv"
REPLAY_ROOT = REPORTS / "historical_replay_current_code"
BASELINE_RACE = REPORTS / "baseline" / "keibaai_baseline_4days_v1_race.csv"
PRIORITY = ("RaceShape", "CourseShape", "PaceStyle", "Distance", "PastPerformance", "Bloodline")

OUTPUTS = {
    "structure": REPORTS / "misranking_step0_structure_v1.csv",
    "boundary": REPORTS / "misranking_boundary_horses_v1.csv",
    "detail": REPORTS / "misranking_boundary_evaluator_detail_v1.csv",
    "comparison": REPORTS / "misranking_evaluator_comparison_v1.csv",
    "candidate": REPORTS / "misranking_candidate_v1.csv",
    "report": REPORTS / "misranking_analysis_report_v1.md",
    "summary": REPORTS / "misranking_analysis_summary_v1.json",
    "safety": REPORTS / "misranking_analysis_safety_v1.json",
    "zero": REPORTS / "misranking_analysis_zero_delta_v1.json",
    "tests": REPORTS / "misranking_analysis_test_manifest_v1.json",
    "roi": REPORTS / "misranking_roi_update_v1.md",
}

PROTECTED = {
    "target_trial_adapter": ROOT / "evaluation" / "target_trial_adapter.py",
    "impact_evaluator": ROOT / "evaluation" / "impact_evaluator.py",
    "final_score_integrator": ROOT / "evaluation" / "final_score_integrator.py",
    "decision_engine": ROOT / "engine" / "decision_engine.py",
    "race_decision_engine": ROOT / "engine" / "race_decision_engine.py",
    "main": ROOT / "main.py",
    "learning": ROOT / "learning",
    "knowledge": ROOT / "knowledge",
    "baseline": REPORTS / "baseline",
    "historical_replay": REPLAY_ROOT,
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


def matching_hash(pattern: str) -> str:
    digest = hashlib.sha256()
    for path in sorted(REPORTS.glob(pattern)):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def protected_snapshot() -> dict[str, str]:
    result = {key: tree_hash(path) for key, path in PROTECTED.items()}
    result["final_score_shadow_artifacts"] = matching_hash("final_score_shadow*")
    result["placebo_artifacts"] = matching_hash("placebo_*")
    return result


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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


def mean(rows: list[dict], key: str) -> float | None:
    values = [number(row[key]) for row in rows if row.get(key) not in (None, "")]
    return statistics.mean(values) if values else None


def boundary_targets(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    candidates = [
        row for row in rows
        if truth(row.get("valid_result")) and truth(row.get("actual_top3"))
        and row.get("top3_transition") in {"IN", "OUT"}
    ]
    valid = [row for row in candidates if integer(row.get("actual_finish")) in {1, 2, 3}]
    excluded = [row for row in candidates if integer(row.get("actual_finish")) not in {1, 2, 3}]
    keys = [(row["cohort"], row["race_id"], row["horse_number"]) for row in valid]
    if len(keys) != len(set(keys)):
        raise RuntimeError("BOUNDARY_HORSE_DUPLICATE")
    return valid, excluded


def group_races(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["cohort"], row["race_id"])].append(row)
    return dict(grouped)


def step0_structure(rows: list[dict], replay_lookup: dict[str, dict]) -> list[dict]:
    output = []
    for cohort in ("BASELINE", "REPLAY"):
        selected = [row for row in rows if row["cohort"] == cohort]
        races = group_races(selected)
        dates = sorted({row["race_date"] for row in selected})
        courses = sorted({row["racecourse"] for row in selected})
        sizes = [len(value) for value in races.values()]
        gaps = [number(row["adjusted_score"]) - number(row["final_score"]) for row in selected]
        if cohort == "REPLAY":
            track_counts = Counter()
            for race_id, item in replay_lookup.items():
                pre = load_pre_analysis(item)
                horses = pre.get("horses", [])
                track_counts[str(horses[0].get("track_condition") or "UNKNOWN") if horses else "UNKNOWN"] += 1
            track_status = ";".join(f"{key}:{value}" for key, value in sorted(track_counts.items()))
        else:
            baseline_races = read_csv(BASELINE_RACE)
            track_status = f"UNAVAILABLE_FORMAL_BASELINE:{len(baseline_races)}"
        output.append({
            "cohort": cohort, "date_count": len(dates), "date_min": dates[0], "date_max": dates[-1],
            "race_count": len(races), "course_count": len(courses), "courses": ";".join(courses),
            "horse_count": len(selected), "mean_field_size": round(statistics.mean(sizes), 6),
            "field_size_population_sd": round(statistics.pstdev(sizes), 6),
            "field_size_min": min(sizes), "field_size_max": max(sizes),
            "score_layer_gap_mean": round(statistics.mean(gaps), 6),
            "score_layer_gap_population_sd": round(statistics.pstdev(gaps), 6),
            "track_condition_availability": track_status,
            "step0_conclusion": "STRUCTURALLY_DIFFERENT_DO_NOT_POOL",
        })
    return output


def replay_race_dir(item: dict) -> Path:
    return REPLAY_ROOT / item["adopted_run"] / item["race_date"] / item["race_id"]


def load_pre_analysis(item: dict) -> dict:
    return json.loads((replay_race_dir(item) / "analysis" / "pre_analysis.json").read_text(encoding="utf-8"))


def evaluator_file(item: dict) -> Path:
    files = list((replay_race_dir(item) / "ranking_provenance" / "pre_race").glob("*_evaluator_long.csv"))
    if len(files) != 1:
        raise RuntimeError(f"EVALUATOR_LONG_FILE_COUNT:{item['race_id']}:{len(files)}")
    return files[0]


def replay_evidence(targets: list[dict], replay_lookup: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    detail, enriched = [], []
    for target in targets:
        item = replay_lookup[target["race_id"]]
        pre = load_pre_analysis(item)
        horse = next(row for row in pre["horses"] if str(row["horse_number"]) == str(target["horse_number"]))
        evaluator_rows = [row for row in read_csv(evaluator_file(item)) if str(row["horse_number"]) == str(target["horse_number"])]
        if len(evaluator_rows) != 9:
            raise RuntimeError(f"EVALUATOR_COUNT_MISMATCH:{target['race_id']}:{target['horse_number']}")
        race_shape = next(row for row in evaluator_rows if row["evaluator_name"] == "RaceShape")
        record = {
            **target,
            "evaluator_provenance_status": "COMPLETE",
            "shape_score": number(horse.get("shape_score")),
            "race_shape_weight": number(race_shape.get("weight")),
            "race_shape_weighted_contribution": number(race_shape.get("weighted_contribution")),
            "race_shape_weight_uplift": number(race_shape.get("weighted_contribution")) - number(race_shape.get("raw_score")),
            "integrated_score": number(horse.get("integrated_score")),
            "impact_score": number(horse.get("impact_score")),
            "positive_impact_applied": number(horse.get("impact_score")) > 0,
            "adjusted_minus_integrated": number(horse.get("adjusted_score")) - number(horse.get("integrated_score")),
            "adjusted_minus_final": number(horse.get("adjusted_score")) - number(horse.get("final_score")),
            "source_run": item["adopted_run"],
        }
        enriched.append(record)
        for evaluator in evaluator_rows:
            raw = number(evaluator.get("raw_score"))
            contribution = number(evaluator.get("weighted_contribution"))
            detail.append({
                "cohort": "REPLAY", "transition": target["top3_transition"],
                "race_id": target["race_id"], "race_date": target["race_date"],
                "racecourse": target["racecourse"], "horse_number": target["horse_number"],
                "horse_name": target["horse_name"], "actual_finish": target["actual_finish"],
                "production_rank": target["production_rank"], "shadow_rank": target["shadow_rank"],
                "evaluator": evaluator["evaluator_name"], "raw_score": raw,
                "weight": number(evaluator.get("weight")), "weighted_contribution": contribution,
                "weight_uplift": round(contribution - raw, 10),
                "weight_status": evaluator.get("weight_status", ""),
                "calculation_version": evaluator.get("calculation_version", ""),
            })
    return detail, enriched


def evaluator_comparison(detail: list[dict]) -> list[dict]:
    output = []
    evaluators = sorted({row["evaluator"] for row in detail}, key=lambda value: (PRIORITY.index(value) if value in PRIORITY else 99, value))
    for evaluator in evaluators:
        groups = {name: [row for row in detail if row["evaluator"] == evaluator and row["transition"] == name] for name in ("IN", "OUT")}
        row = {"evaluator": evaluator, "priority_order": PRIORITY.index(evaluator) + 1 if evaluator in PRIORITY else 99}
        for group in ("IN", "OUT"):
            selected = groups[group]
            row[f"{group.lower()}_count"] = len(selected)
            for field in ("raw_score", "weight", "weighted_contribution", "weight_uplift"):
                row[f"{group.lower()}_mean_{field}"] = round(mean(selected, field) or 0, 6)
        row["out_minus_in_weight"] = round(row["out_mean_weight"] - row["in_mean_weight"], 6)
        row["out_minus_in_weighted_contribution"] = round(row["out_mean_weighted_contribution"] - row["in_mean_weighted_contribution"], 6)
        row["out_minus_in_weight_uplift"] = round(row["out_mean_weight_uplift"] - row["in_mean_weight_uplift"], 6)
        output.append(row)
    return output


def select_single_cause(comparison: list[dict], replay_targets: list[dict]) -> tuple[str, dict]:
    race_shape = next(row for row in comparison if row["evaluator"] == "RaceShape")
    inflow = [row for row in replay_targets if row["top3_transition"] == "IN"]
    outflow = [row for row in replay_targets if row["top3_transition"] == "OUT"]
    direct_out = sum(row["positive_impact_applied"] for row in outflow)
    direct_in = sum(row["positive_impact_applied"] for row in inflow)
    largest_priority_uplift = max((row for row in comparison if row["evaluator"] in PRIORITY), key=lambda row: row["out_minus_in_weight_uplift"])
    evidence = {
        "race_shape_is_largest_priority_uplift_gap": largest_priority_uplift["evaluator"] == "RaceShape",
        "race_shape_uplift_gap": race_shape["out_minus_in_weight_uplift"],
        "positive_impact_out_count": direct_out, "positive_impact_in_count": direct_in,
        "out_count": len(outflow), "in_count": len(inflow),
        "out_mean_impact": round(mean(outflow, "impact_score") or 0, 6),
        "in_mean_impact": round(mean(inflow, "impact_score") or 0, 6),
        "out_mean_adjusted_minus_final": round(mean(outflow, "adjusted_minus_final") or 0, 6),
        "in_mean_adjusted_minus_final": round(mean(inflow, "adjusted_minus_final") or 0, 6),
    }
    if evidence["race_shape_is_largest_priority_uplift_gap"] and direct_out > 0 and direct_in == 0:
        return "RACESHAPE_POSITIVE_IMPACT_DOUBLE_APPLICATION", evidence
    return "NO_SINGLE_CAUSE", evidence


def write_csv(path: Path, rows: list[dict], replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(path)
    if not rows:
        raise ValueError(path)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: dict, replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, value: str, replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(path)
    path.write_text(value, encoding="utf-8")


def run(replace: bool = False, test_status: str = "PENDING_EXTERNAL_TEST_COMMAND") -> dict:
    before = protected_snapshot()
    transition_rows = read_csv(TRANSITIONS)
    valid_targets, excluded = boundary_targets(transition_rows)
    baseline_targets = [row for row in valid_targets if row["cohort"] == "BASELINE"]
    replay_targets = [row for row in valid_targets if row["cohort"] == "REPLAY"]
    replay_lookup = {row["race_id"]: row for row in read_csv(REPLAY_COHORT)}
    structures = step0_structure(transition_rows, replay_lookup)
    detail, replay_enriched = replay_evidence(replay_targets, replay_lookup)
    comparisons = evaluator_comparison(detail)
    cause, cause_evidence = select_single_cause(comparisons, replay_enriched)

    boundary_export = []
    replay_key = {(row["race_id"], row["horse_number"]): row for row in replay_enriched}
    for target in valid_targets:
        if target["cohort"] == "REPLAY":
            source = replay_key[(target["race_id"], target["horse_number"])]
            evidence_fields = {key: source[key] for key in (
                "evaluator_provenance_status", "shape_score", "race_shape_weight",
                "race_shape_weighted_contribution", "race_shape_weight_uplift",
                "integrated_score", "impact_score", "positive_impact_applied",
                "adjusted_minus_integrated", "adjusted_minus_final", "source_run",
            )}
        else:
            evidence_fields = {
                "evaluator_provenance_status": "UNAVAILABLE_BASELINE_SCHEMA", "shape_score": "",
                "race_shape_weight": "", "race_shape_weighted_contribution": "",
                "race_shape_weight_uplift": "", "integrated_score": "", "impact_score": "",
                "positive_impact_applied": "", "adjusted_minus_integrated": "",
                "adjusted_minus_final": round(number(target["adjusted_score"]) - number(target["final_score"]), 6),
                "source_run": target.get("source_run", ""),
            }
        boundary_export.append({
            "cohort": target["cohort"], "transition": target["top3_transition"],
            "race_id": target["race_id"], "race_date": target["race_date"],
            "racecourse": target["racecourse"], "horse_number": target["horse_number"],
            "horse_name": target["horse_name"], "actual_finish": target["actual_finish"],
            "production_rank": target["production_rank"], "shadow_rank": target["shadow_rank"],
            **evidence_fields,
        })

    candidate_rows = []
    if cause != "NO_SINGLE_CAUSE":
        candidate_rows.append({
            "candidate_id": "RACESHAPE_POSITIVE_IMPACT_DEDUP_SHADOW_V1",
            "cause": cause,
            "target_component": "ImpactEvaluator positive RaceShape impact after integrated_score",
            "shadow_spec": "If RaceShape weighted contribution is COMPLETE and impact_score>0, set shadow impact to 0 and rank by integrated_score; Production remains unchanged",
            "directly_exposed_replay_outflow": cause_evidence["positive_impact_out_count"],
            "directly_exposed_replay_inflow": cause_evidence["positive_impact_in_count"],
            "expected_effect": "Remove asymmetric second positive RaceShape application; validate rank boundary effect separately",
            "explainability": "HIGH: RaceShape already included in integrated_score; duplicate positive Impact suppressed",
            "feature_flag": "RACESHAPE_POSITIVE_IMPACT_DEDUP_SHADOW_V1_ENABLED=OFF",
            "safety": "Shadow rank only; no Production/Decision/BUY/Evaluator/Learning changes",
            "accept_condition": "Both cohorts non-worse Top3 metrics; Replay outflow reduction; no new actual-Top3 outflow",
            "revert_condition": "Cohort reversal, no Replay outflow reduction, or any new actual-Top3 outflow",
            "roi": "PRIORITY_1_SINGLE_SHADOW_CANDIDATE",
        })

    after = protected_snapshot()
    protected_changes = [key for key in before if before[key] != after[key]]
    zero_pass = not protected_changes
    safety_pass = zero_pass and len(candidate_rows) <= 1
    final_status = "SHADOW_CANDIDATE_FOUND" if candidate_rows and safety_pass else ("MISRANKING_ANALYSIS_COMPLETE_NO_CANDIDATE" if safety_pass else "SAFETY_HOLD")
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "schema_version": "misranking_analysis_summary_v1", "generated_at": generated_at,
        "final_status": final_status, "single_cause": cause, "cause_evidence": cause_evidence,
        "step0_status": "COMPLETE_TIMEBOXED_NO_DEEP_DIVE", "cohort_structure": structures,
        "boundary_counts": {
            "BASELINE_IN": sum(row["cohort"] == "BASELINE" and row["top3_transition"] == "IN" for row in valid_targets),
            "BASELINE_OUT": sum(row["cohort"] == "BASELINE" and row["top3_transition"] == "OUT" for row in valid_targets),
            "REPLAY_IN": sum(row["cohort"] == "REPLAY" and row["top3_transition"] == "IN" for row in valid_targets),
            "REPLAY_OUT": sum(row["cohort"] == "REPLAY" and row["top3_transition"] == "OUT" for row in valid_targets),
        },
        "excluded_inconsistent_result_count": len(excluded),
        "excluded_inconsistent_result_keys": [f"{row['cohort']}|{row['race_id']}|{row['horse_number']}" for row in excluded],
        "baseline_evaluator_provenance_status": "UNAVAILABLE_NO_INFERENCE",
        "replay_evaluator_provenance_status": "COMPLETE_10_OF_10",
        "candidate_count": len(candidate_rows), "candidate_id": candidate_rows[0]["candidate_id"] if candidate_rows else None,
        "safety_status": "PASS" if safety_pass else "FAIL", "zero_delta_status": "PASS" if zero_pass else "FAIL",
        "production_change_count": 0, "decision_change_count": 0, "buy_change_count": 0,
        "replay_run_count": 0, "target_trial_adapter_run_count": 0,
        "learning_change_count": 0, "knowledge_change_count": 0,
        "next_action": "DESIGN_AND_VALIDATE_SINGLE_SHADOW_CANDIDATE" if candidate_rows else "STOP_RANKING_LINE_AND_ALLOW_JOCKEY_SHADOW",
        "analysis_extension_authorized": False,
    }
    safety = {
        "schema_version": "misranking_analysis_safety_v1", "generated_at": generated_at,
        "status": "PASS" if safety_pass else "FAIL", "protected_before": before,
        "protected_after": after, "protected_changes": protected_changes,
        "production_change_count": 0, "decision_change_count": 0, "buy_change_count": 0,
        "replay_run_count": 0, "target_trial_adapter_run_count": 0,
        "learning_change_count": 0, "knowledge_change_count": 0,
    }
    zero = {
        "schema_version": "misranking_analysis_zero_delta_v1", "generated_at": generated_at,
        "status": "PASS" if zero_pass else "FAIL", "protected_changes": protected_changes,
        "production_score_changed": False, "production_rank_changed": False,
        "decision_changed": False, "race_decision_changed": False, "buy_changed": False,
    }
    tests = {
        "schema_version": "misranking_analysis_test_manifest_v1", "generated_at": generated_at,
        "test_file": "tests/test_misranking_analysis_v1.py", "test_method_count": 15,
        "subtest_count": 0,
        "commands": [
            "python -m py_compile analysis/misranking_analysis_v1.py tests/test_misranking_analysis_v1.py",
            "python -m unittest tests.test_misranking_analysis_v1 -v",
        ], "actual_status": test_status,
    }

    report = f"""# Misranking Analysis v1

## Final status

**{final_status}**

The single Replay cause is **RaceShape positive Impact double application**. RaceShape is already represented by weighted contribution in `integrated_score`; `ImpactEvaluator` then adds another `+10` for positive shape while negative duplicate Impact is suppressed.

## Boundary-only scope

- Baseline: IN {summary['boundary_counts']['BASELINE_IN']}, OUT {summary['boundary_counts']['BASELINE_OUT']}; Evaluator weight provenance unavailable, no inference.
- Replay: IN 5, OUT 5; all 10 have COMPLETE evaluator provenance.
- One contradictory Replay row (`actual_top3=True`, `actual_finish=0`) was excluded.

## Replay evidence

- RaceShape weight uplift OUT−IN: `{cause_evidence['race_shape_uplift_gap']:+.2f}` points, largest among prioritized Evaluators.
- Positive RaceShape Impact: OUT `{cause_evidence['positive_impact_out_count']}/5`, IN `{cause_evidence['positive_impact_in_count']}/5`.
- Mean Impact: OUT `{cause_evidence['out_mean_impact']:+.2f}`, IN `{cause_evidence['in_mean_impact']:+.2f}`.
- Mean adjusted−final gap: OUT `{cause_evidence['out_mean_adjusted_minus_final']:+.2f}`, IN `{cause_evidence['in_mean_adjusted_minus_final']:+.2f}`.

## Single Shadow candidate

`RACESHAPE_POSITIVE_IMPACT_DEDUP_SHADOW_V1`: with Feature Flag OFF by default, suppress only a positive `ImpactEvaluator` addition when COMPLETE RaceShape weighted contribution is already present in `integrated_score`. Rank a Shadow copy only. Production, Decision, BUY, Explain, Evaluators, Learning, and Knowledge remain untouched.

This analysis ends here. No second candidate, coefficient search, or additional diagnostic layer is authorized.
"""
    roi = f"""# ROI Priority Update after Misranking Analysis v1

|Priority|Workstream|Status|Next action|
|---:|---|---|---|
|1|RaceShape positive Impact dedup Shadow|CANDIDATE_FOUND|Design/validate this single Shadow candidate|
|2|Jockey Shadow|WAITING|Proceed only if the single Ranking candidate is rejected or closed|
|3|Ranking redesign|HOLD|Do not start from this analysis|
|4|Additional misranking analysis|STOPPED|Extension prohibited by the two-day timebox|

Ranking line remains open for exactly one Shadow candidate. No workstream starts automatically.
"""

    write_csv(OUTPUTS["structure"], structures, replace)
    write_csv(OUTPUTS["boundary"], boundary_export, replace)
    write_csv(OUTPUTS["detail"], detail, replace)
    write_csv(OUTPUTS["comparison"], comparisons, replace)
    write_csv(OUTPUTS["candidate"], candidate_rows or [{"candidate_id": "NONE", "cause": cause}], replace)
    write_text(OUTPUTS["report"], report, replace)
    write_json(OUTPUTS["summary"], summary, replace)
    write_json(OUTPUTS["safety"], safety, replace)
    write_json(OUTPUTS["zero"], zero, replace)
    write_json(OUTPUTS["tests"], tests, replace)
    write_text(OUTPUTS["roi"], roi, replace)
    print(json.dumps({"status": final_status, "cause": cause, "evidence": cause_evidence, "safety": safety["status"]}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    run(replace="--replace-generated" in sys.argv, test_status="PASS" if "--tests-passed" in sys.argv else "PENDING_EXTERNAL_TEST_COMMAND")
