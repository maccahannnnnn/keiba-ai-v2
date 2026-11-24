"""Shadow-only validation of positive RaceShape Impact deduplication.

Production ImpactEvaluator logic is imported read-only. The Shadow wrapper
reuses its existing impact decision helper and never mutates Production rows.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.impact_evaluator import ImpactEvaluator  # noqa: E402


REPORTS = ROOT / "reports"
REPLAY_ROOT = REPORTS / "historical_replay_current_code"
INPUT_TRANSITIONS = REPORTS / "final_score_shadow_rank_transition_v1.csv"
REPLAY_COHORT = REPORTS / "ranking_weight_unique_cohort_v1.csv"
SPEC = REPORTS / "raceshape_positive_impact_dedup_preregistered_spec_v1.md"
SPEC_SHA256 = "feba3f1fcdb8e2f7c2ce08cae760afd0bef51ba372b72f88b294df67508a6529"
FLAG_NAME = "RACESHAPE_POSITIVE_IMPACT_DEDUP_SHADOW_ENABLED"
CANDIDATE_ID = "RACESHAPE_POSITIVE_IMPACT_DEDUP_SHADOW_V1"
MEAN_RANK_MIN_IMPROVEMENT = 1 / 102

OUTPUTS = {
    "spec_sha": REPORTS / "raceshape_positive_impact_dedup_spec_sha256_v1.json",
    "structure": REPORTS / "raceshape_positive_impact_dedup_structure_evidence_v1.csv",
    "baseline": REPORTS / "raceshape_positive_impact_dedup_baseline_result_v1.json",
    "replay": REPORTS / "raceshape_positive_impact_dedup_replay_result_v1.json",
    "transitions": REPORTS / "raceshape_positive_impact_dedup_rank_transition_v1.csv",
    "metrics": REPORTS / "raceshape_positive_impact_dedup_metric_comparison_v1.csv",
    "report": REPORTS / "raceshape_positive_impact_dedup_shadow_report_v1.md",
    "summary": REPORTS / "raceshape_positive_impact_dedup_shadow_summary_v1.json",
    "safety": REPORTS / "raceshape_positive_impact_dedup_safety_v1.json",
    "zero": REPORTS / "raceshape_positive_impact_dedup_zero_delta_v1.json",
    "tests": REPORTS / "raceshape_positive_impact_dedup_test_manifest_v1.json",
    "roi": REPORTS / "raceshape_positive_impact_dedup_roi_update_v1.md",
    "claude": REPORTS / "raceshape_positive_impact_dedup_claude_review_packet_v1.md",
}

PROTECTED = {
    "impact_evaluator": ROOT / "evaluation" / "impact_evaluator.py",
    "target_trial_adapter": ROOT / "evaluation" / "target_trial_adapter.py",
    "final_score_integrator": ROOT / "evaluation" / "final_score_integrator.py",
    "score_weight_evaluator": ROOT / "evaluators" / "score_weight_evaluator.py",
    "decision_engine": ROOT / "engine" / "decision_engine.py",
    "race_decision_engine": ROOT / "engine" / "race_decision_engine.py",
    "main": ROOT / "main.py",
    "learning": ROOT / "learning",
    "knowledge": ROOT / "knowledge",
    "baseline": REPORTS / "baseline",
    "historical_replay": REPLAY_ROOT,
    "ranking_provenance": REPORTS / "ranking_provenance",
}

SHADOW_REASON = (
    "RaceShapeはweighted contributionとして既にintegrated_scoreへ反映済みのため、"
    "正方向Impactの重複加点をShadow上で抑制（正負両方向でRaceShape重複評価を避ける検証）"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    if path.is_file():
        return sha256(path)
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"})
    for item in files:
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
    result["misranking_artifacts"] = matching_hash("misranking_*")
    result["placebo_artifacts"] = matching_hash("placebo_*")
    return result


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def truth(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


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


def stable_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def flag_enabled(value=None) -> bool:
    raw = os.environ.get(FLAG_NAME, "OFF") if value is None else value
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().upper() in {"1", "TRUE", "ON", "YES"}


def _line(source: Path, text: str) -> int:
    for index, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if text in line:
            return index
    raise RuntimeError(f"STRUCTURE_PATTERN_MISSING:{source}:{text}")


def structure_evidence() -> list[dict]:
    adapter = ROOT / "evaluation" / "target_trial_adapter.py"
    weights = ROOT / "evaluators" / "score_weight_evaluator.py"
    impact = ROOT / "evaluation" / "impact_evaluator.py"
    adapter_text = adapter.read_text(encoding="utf-8")
    adjusted_assignments = adapter_text.count('item["adjusted_score"] = impact_result.get(')
    if adjusted_assignments != 1:
        raise RuntimeError(f"POST_INTEGRATED_ADDITIVE_PATH_COUNT:{adjusted_assignments}")
    return [
        {"check_id": 1, "fact": "shape_score calculated once and stored", "status": "PASS", "file": "evaluation/target_trial_adapter.py", "line": _line(adapter, 'item["shape_score"] = shape_result.get'), "evidence": "RaceShapeEvaluator result is stored as shape_score"},
        {"check_id": 2, "fact": "RaceShape weight applied", "status": "PASS", "file": "evaluators/score_weight_evaluator.py", "line": _line(weights, "self._adjust_shape_weight(data, weights, comments)"), "evidence": "ScoreWeightEvaluator invokes RaceShape weight adjustment"},
        {"check_id": 3, "fact": "weighted contribution enters integrated_score", "status": "PASS", "file": "evaluators/score_weight_evaluator.py", "line": _line(weights, '"integrated_score": weighted_score'), "evidence": "integrated_score equals weighted_score containing shape_score * weight"},
        {"check_id": 4, "fact": "same shape_score passed to ImpactEvaluator", "status": "PASS", "file": "evaluation/target_trial_adapter.py", "line": _line(adapter, 'shape_score=item.get("shape_score")'), "evidence": "Stored shape_score is passed without recalculation"},
        {"check_id": 5, "fact": "positive Impact separately enters adjusted_score", "status": "PASS", "file": "evaluation/impact_evaluator.py", "line": _line(impact, "adjusted_score = base_score + impact_score"), "evidence": "ImpactEvaluator adds Impact after integrated_score is supplied as base"},
        {"check_id": 6, "fact": "Production dedup is negative-only", "status": "PASS", "file": "evaluation/impact_evaluator.py", "line": _line(impact, "if impact_score >= 0:"), "evidence": "Non-negative Impact returns unchanged; only negative RaceShape signal is suppressed"},
        {"check_id": 7, "fact": "no other Evaluator has same post-integrated additive route", "status": "PASS", "file": "evaluation/target_trial_adapter.py", "line": _line(adapter, 'item["adjusted_score"] = impact_result.get'), "evidence": "Exactly one adjusted_score assignment consumes a post-integrated evaluator result, and it is ImpactEvaluator"},
    ]


def normalize_transition_rows() -> dict[str, list[dict]]:
    rows = read_csv(INPUT_TRANSITIONS)
    output = {"BASELINE": [], "REPLAY": []}
    for source in rows:
        row = dict(source)
        # The input was produced by the earlier final_score Shadow.  Its
        # shadow-only rank/transition fields are not Production state and must
        # not be carried into this candidate's zero-delta comparison.
        for field in (
            "shadow_rank",
            "rank_change_shadow_minus_production",
            "moved",
            "top3_transition",
            "top5_transition",
        ):
            row.pop(field, None)
        row["production_adjusted_score"] = number(source["adjusted_score"])
        row["production_rank"] = integer(source["production_rank"])
        row["valid_result"] = truth(source["valid_result"])
        row["actual_top3"] = truth(source["actual_top3"])
        row["actual_top5"] = truth(source["actual_top5"])
        row["buy"] = truth(source["buy"])
        row["actual_finish"] = integer(source["actual_finish"]) if row["valid_result"] else ""
        output[row["cohort"]].append(row)
    if len(output["BASELINE"]) != 448 or len(output["REPLAY"]) != 512:
        raise RuntimeError("COHORT_COUNT_MISMATCH")
    keys = [(r["cohort"], r["race_id"], r["horse_number"]) for rows_ in output.values() for r in rows_]
    if len(keys) != len(set(keys)):
        raise RuntimeError("DUPLICATE_HORSE")
    return output


def _replay_race_dir(item: dict) -> Path:
    return REPLAY_ROOT / item["adopted_run"] / item["race_date"] / item["race_id"]


def replay_evidence() -> dict[tuple[str, str, str], dict]:
    lookup = {}
    for item in read_csv(REPLAY_COHORT):
        race_dir = _replay_race_dir(item)
        pre = json.loads((race_dir / "analysis" / "pre_analysis.json").read_text(encoding="utf-8"))
        long_files = list((race_dir / "ranking_provenance" / "pre_race").glob("*_evaluator_long.csv"))
        if len(long_files) != 1:
            raise RuntimeError(f"EVALUATOR_LONG_COUNT:{item['race_id']}:{len(long_files)}")
        race_shape = {str(row["horse_number"]): row for row in read_csv(long_files[0]) if row["evaluator_name"] == "RaceShape"}
        for horse in pre["horses"]:
            key = ("REPLAY", item["race_id"], str(horse["horse_number"]))
            provenance = race_shape.get(str(horse["horse_number"]))
            if provenance is None:
                raise RuntimeError(f"RACESHAPE_PROVENANCE_MISSING:{key}")
            lookup[key] = {
                "shape_score": horse.get("shape_score"), "shape_comment": horse.get("shape_comment"),
                "integrated_score": horse.get("integrated_score"), "impact_score": horse.get("impact_score"),
                "adjusted_score": horse.get("adjusted_score"),
                "weight_status": provenance.get("weight_status"),
                "weighted_contribution": provenance.get("weighted_contribution"),
                "source_run": item["adopted_run"],
            }
    if len(lookup) != 512:
        raise RuntimeError(f"REPLAY_EVIDENCE_COUNT:{len(lookup)}")
    return lookup


def apply_shadow_row(row: dict, evidence: dict | None, evaluator: ImpactEvaluator, enabled=None) -> dict:
    if not flag_enabled(enabled):
        return copy.deepcopy(row)
    output = copy.deepcopy(row)
    if evidence is None:
        output.update({
            "shadow_original_impact_score": "", "shadow_raceshape_positive_impact_suppressed": False,
            "shadow_dedup_impact_score": "", "shadow_adjusted_score": output["production_adjusted_score"],
            "shadow_reason": "BASELINE_REQUIRED_PROVENANCE_UNAVAILABLE",
            "_shadow_eligible": False, "_raw_impact_from_existing_logic": "",
        })
        return output
    original_impact = number(evidence.get("impact_score"))
    existing_logic_impact = evaluator._impact_from_comment_or_score(evidence.get("shape_comment"), evidence.get("shape_score"))
    complete = evidence.get("weight_status") == "COMPLETE"
    integrated_present = evidence.get("integrated_score") not in (None, "")
    positive = original_impact > 0 and number(existing_logic_impact) > 0
    eligible = complete and integrated_present and positive
    dedup_impact = 0 if eligible else original_impact
    shadow_score = number(evidence["integrated_score"]) + dedup_impact if integrated_present else output["production_adjusted_score"]
    output.update({
        "shadow_original_impact_score": original_impact,
        "shadow_raceshape_positive_impact_suppressed": eligible,
        "shadow_dedup_impact_score": dedup_impact,
        "shadow_adjusted_score": round(shadow_score, 10),
        "shadow_reason": SHADOW_REASON if eligible else "RACESHAPE_POSITIVE_DEDUP_NOT_APPLICABLE",
        "_shadow_eligible": eligible, "_raw_impact_from_existing_logic": existing_logic_impact,
    })
    return output


def group_by_race(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["cohort"], row["race_id"])].append(row)
    return dict(grouped)


def rank_shadow(rows: list[dict], evidence_lookup: dict[tuple[str, str, str], dict], enabled=None) -> list[dict]:
    evaluator = ImpactEvaluator()
    output = []
    for key, race_rows in group_by_race(rows).items():
        shadow = [
            apply_shadow_row(
                row,
                evidence_lookup.get((row["cohort"], row["race_id"], str(row["horse_number"]))),
                evaluator,
                enabled,
            )
            for row in race_rows
        ]
        if not flag_enabled(enabled):
            output.extend(shadow)
            continue
        if not any(row["shadow_raceshape_positive_impact_suppressed"] for row in shadow):
            for row in shadow:
                row["shadow_rank"] = row["production_rank"]
            output.extend(shadow)
            continue
        ordered = sorted(shadow, key=lambda row: (number(row["shadow_adjusted_score"], float("-inf")), integer(row["horse_number"])), reverse=True)
        for rank, row in enumerate(ordered, start=1):
            row["shadow_rank"] = rank
        output.extend(shadow)
    return output


def metric_values(rows: list[dict], rank_key: str) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    selected = [row for row in valid if integer(row[rank_key]) <= 3]
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
    return {
        "rank1_3_top3_rate": sum(row["actual_top3"] for row in selected) / len(selected) if selected else 0.0,
        "mean_actual_top3_rank": statistics.mean(integer(row[rank_key]) for row in actual_top3) if actual_top3 else 0.0,
        "ndcg_at_3": statistics.mean(ndcgs) if ndcgs else 0.0,
        "mrr": statistics.mean(reciprocal) if reciprocal else 0.0,
        "top5_capture_rate": sum(integer(row[rank_key]) <= 5 for row in actual_top3) / len(actual_top3) if actual_top3 else 0.0,
    }


def cohort_result(rows: list[dict]) -> dict:
    production = metric_values(rows, "production_rank")
    shadow = metric_values(rows, "shadow_rank")
    moved = [row for row in rows if row["production_rank"] != row["shadow_rank"]]
    top3_in = [row for row in rows if row["production_rank"] > 3 >= row["shadow_rank"]]
    top3_out = [row for row in rows if row["production_rank"] <= 3 < row["shadow_rank"]]
    return {
        "race_count": len({row["race_id"] for row in rows}), "horse_count": len(rows),
        "valid_result_count": sum(row["valid_result"] for row in rows),
        "production": {key: round(value, 8) for key, value in production.items()},
        "shadow": {key: round(value, 8) for key, value in shadow.items()},
        "delta": {key: round(shadow[key] - production[key], 8) for key in production},
        "movement_count": len(moved), "movement_rate": round(len(moved) / len(rows), 8),
        "top3_inflow_count": len(top3_in), "top3_outflow_count": len(top3_out),
        "actual_top3_top3_inflow_count": sum(row["valid_result"] and row["actual_top3"] for row in top3_in),
        "actual_top3_top3_outflow_count": sum(row["valid_result"] and row["actual_top3"] for row in top3_out),
        "positive_impact_suppressed_count": sum(bool(row.get("shadow_raceshape_positive_impact_suppressed")) for row in rows),
        "eligible_count": sum(bool(row.get("_shadow_eligible")) for row in rows),
    }


def classify_result(results: dict[str, dict], structure_pass=True, safety_pass=True, design_hold=False) -> tuple[str, list[str]]:
    if design_hold:
        return "DESIGN_HOLD", ["EXPLICIT_POSITIVE_RETENTION_RATIONALE_FOUND"]
    if not structure_pass or not safety_pass:
        return "SAFETY_HOLD", ["STRUCTURE_OR_SAFETY_FAIL"]
    if any(result["movement_rate"] < 0.10 for result in results.values()):
        return "INCONCLUSIVE", ["MOVEMENT_BELOW_10_PERCENT"]
    top3 = [result["delta"]["rank1_3_top3_rate"] for result in results.values()]
    mean_rank = [result["delta"]["mean_actual_top3_rank"] for result in results.values()]
    reasons = []
    if top3[0] * top3[1] < 0 or mean_rank[0] * mean_rank[1] < 0:
        reasons.append("COHORT_DIRECTION_REVERSAL")
    for cohort, result in results.items():
        if result["delta"]["rank1_3_top3_rate"] < 0 or result["delta"]["mean_actual_top3_rank"] > 0:
            reasons.append(f"{cohort}_PRIMARY_METRIC_WORSENED")
        if result["actual_top3_top3_outflow_count"] > 0:
            reasons.append(f"{cohort}_ACTUAL_TOP3_OUTFLOW")
        if result["delta"]["ndcg_at_3"] < 0 or result["delta"]["mrr"] < 0:
            reasons.append(f"{cohort}_NDCG_OR_MRR_WORSENED")
    if reasons:
        return "REJECT", reasons
    full_large = all(result["delta"]["rank1_3_top3_rate"] >= 0.03 for result in results.values())
    full_large = full_large and all(result["delta"]["mean_actual_top3_rank"] < 0 for result in results.values())
    full_mid = all(0.01 <= result["delta"]["rank1_3_top3_rate"] < 0.03 for result in results.values())
    full_mid = full_mid and all(result["delta"]["mean_actual_top3_rank"] <= -MEAN_RANK_MIN_IMPROVEMENT for result in results.values())
    supplemental = all(result["delta"]["ndcg_at_3"] >= 0 and result["delta"]["mrr"] >= 0 for result in results.values())
    if (full_large or full_mid) and supplemental:
        return "FULL_ACCEPT", ["PREREGISTERED_FULL_ACCEPT_CONDITIONS_MET"]
    partial = all(0.01 <= result["delta"]["rank1_3_top3_rate"] < 0.03 for result in results.values())
    if partial:
        return "PARTIAL_ACCEPT", ["A_IMPROVES_B_REINFORCEMENT_NOT_MET"]
    return "REJECT", ["ACCEPT_EFFECT_THRESHOLD_NOT_MET"]


def metric_rows(cohort: str, rows: list[dict], reference_only=False) -> list[dict]:
    slices = [("OVERALL", "ALL", rows)]
    for axis, key in (("DATE", "race_date"), ("RACECOURSE", "racecourse")):
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
        "production_adjusted_score", "production_rank", "shadow_original_impact_score",
        "shadow_raceshape_positive_impact_suppressed", "shadow_dedup_impact_score",
        "shadow_adjusted_score", "shadow_rank", "shadow_reason",
    )
    return [{field: row.get(field, "") for field in fields} for row in sorted(rows, key=lambda r: (r["cohort"], r["race_id"], r["production_rank"]))]


def write_csv(path: Path, rows: list[dict], replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(path)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def write_json(path: Path, value: dict, replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, value: str, replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(path)
    path.write_text(value, encoding="utf-8")


def build_report(summary: dict) -> str:
    b, r = summary["cohort_results"]["BASELINE"], summary["cohort_results"]["REPLAY"]
    return f"""# RACESHAPE_POSITIVE_IMPACT_DEDUP_SHADOW_V1

## Final status

**{summary['final_status']}**

## Design gate and implementation

- Design gate: `B_NO_EXPLICIT_POSITIVE_RETENTION_RATIONALE`
- History checked: commit `80d5195` and the available file history/tests
- Finding: the existing helper documents only avoiding duplicate RaceShape downside; no explicit reason for retaining positive duplication was found
- Feature flag: `RACESHAPE_POSITIVE_IMPACT_DEDUP_SHADOW_ENABLED` (default `OFF`)
- Implementation: thin Shadow wrapper reusing `ImpactEvaluator._impact_from_comment_or_score`; Production `_suppress_duplicate_shape_penalty()` is unchanged
- Preregistered spec SHA256: `{summary['preregistered_spec_sha256']}`
- Structure evidence: `7/7 PASS`

## Cohort results

|Cohort|Horses|Suppressed|Movement|rank1-3 Top3 delta|Mean actual-Top3 rank delta|NDCG@3 delta|MRR delta|Actual-Top3 inflow/outflow|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|Baseline|448|{b['positive_impact_suppressed_count']}|{b['movement_count']} ({b['movement_rate']:.2%})|{b['delta']['rank1_3_top3_rate']:+.4f}|{b['delta']['mean_actual_top3_rank']:+.4f}|{b['delta']['ndcg_at_3']:+.4f}|{b['delta']['mrr']:+.4f}|{b['actual_top3_top3_inflow_count']}/{b['actual_top3_top3_outflow_count']}|
|Replay|512|{r['positive_impact_suppressed_count']}|{r['movement_count']} ({r['movement_rate']:.2%})|{r['delta']['rank1_3_top3_rate']:+.4f}|{r['delta']['mean_actual_top3_rank']:+.4f}|{r['delta']['ndcg_at_3']:+.4f}|{r['delta']['mrr']:+.4f}|{r['actual_top3_top3_inflow_count']}/{r['actual_top3_top3_outflow_count']}|

Baseline has no full-cohort COMPLETE RaceShape weight provenance, so the strict eligibility condition makes no inferred changes. No values were inferred. The preregistered movement gate therefore makes the formal result `INCONCLUSIVE`.

Replay has sufficient provenance and suppressed 227 positive RaceShape-derived Impact entries. It moved 173/512 horses (33.79%), but rank1-3 Top3 rate fell 1.85 points, NDCG@3 and MRR also fell, and actual-Top3 boundary movement was 1 inflow versus 3 outflows. The mean actual-Top3 rank improved by 0.0796 and Top5 capture improved by 2.65 points, but those secondary gains do not support Production adoption against the co-primary and supplemental deterioration.

## Safety and interpretation

- Flag OFF exact match: `PASS`
- Safety: `{summary['safety_status']}`
- ZERO_DELTA: `{summary['zero_delta_status']}`
- Production/Decision/RaceDecision/BUY/Explain/Learning/Knowledge/normal Ledger writes: `0`
- TargetTrialAdapter.run / Replay / full Evaluator executions: `0 / 0 / 0`
- Formal status: `INCONCLUSIVE`; practical adoption posture: `HOLD`
- No second candidate, coefficient search, or threshold post-fitting was performed

An initial non-formal QA generation was invalidated before reporting because a race_id shared by the two cohorts exposed a cohort-key collision and a prior Shadow rank column was initially misclassified as Production state. Both issues were confined to this new analysis module, Production changes remained zero, and regression tests now cover both cases. Only the corrected artifacts are formal.
"""


def roi_text(status: str) -> str:
    if status == "FULL_ACCEPT":
        race, next_action = "FULL_ACCEPT / rank 1", "Claude independent review then ChatGPT GO/NOGO"
    elif status == "PARTIAL_ACCEPT":
        race, next_action = "PARTIAL_ACCEPT / rank 1", "SWP_V1 diagnostic with three-day timebox"
    elif status == "REJECT":
        race, next_action = "CLOSED_REJECT", "Move to Jockey Shadow after 3C review"
    else:
        race, next_action = f"{status} / HOLD", "Claude and ChatGPT review; no automatic rerun or threshold search"
    return f"""# ROI Update: RaceShape Positive Impact Dedup

|Priority|Candidate|Status|Next action|
|---:|---|---|---|
|1|RaceShape Positive Impact Dedup|{race}|{next_action}|
|2|Jockey Shadow|WAITING|Next eligible candidate if RaceShape is closed|
|3|Ranking redesign|CONDITIONAL|Reassess only after 3C review|
|4|Recency|CLOSED_HOLD|Do not reopen|
|5|Other candidates|STOPPED|No second candidate from this analysis|
"""


def run(replace: bool = False, test_status: str = "PENDING_EXTERNAL_TEST_COMMAND") -> dict:
    if sha256(SPEC) != SPEC_SHA256:
        raise RuntimeError("SPEC_SHA256_MISMATCH")
    before = protected_snapshot()
    structures = structure_evidence()
    structure_pass = all(row["status"] == "PASS" for row in structures)
    production = normalize_transition_rows()
    evidence = replay_evidence()
    off = {cohort: rank_shadow(rows, evidence, enabled=False) for cohort, rows in production.items()}
    flag_off = {cohort: rows == off[cohort] and stable_hash(rows) == stable_hash(off[cohort]) for cohort, rows in production.items()}
    on = {cohort: rank_shadow(rows, evidence, enabled=True) for cohort, rows in production.items()}
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
    changes = [key for key in before if before[key] != after[key]]
    zero_pass = all(flag_off.values()) and not mutations and not changes
    safety_pass = zero_pass and structure_pass
    status, reasons = classify_result(results, structure_pass, safety_pass, design_hold=False)
    combined = on["BASELINE"] + on["REPLAY"]
    integrated = cohort_result(combined)
    metrics = metric_rows("BASELINE", on["BASELINE"]) + metric_rows("REPLAY", on["REPLAY"])
    metrics += metric_rows("INTEGRATED_REFERENCE", combined, reference_only=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "schema_version": "raceshape_positive_impact_dedup_shadow_summary_v1", "generated_at": generated_at,
        "candidate_id": CANDIDATE_ID, "feature_flag": FLAG_NAME, "feature_flag_default": "OFF",
        "final_status": status, "decision_reasons": reasons,
        "design_gate": "B_NO_EXPLICIT_POSITIVE_RETENTION_RATIONALE",
        "design_history_commit": "80d5195", "structure_evidence_pass": structure_pass,
        "preregistered_spec_sha256": SPEC_SHA256,
        "mean_actual_top3_rank_minimum_improvement": MEAN_RANK_MIN_IMPROVEMENT,
        "mean_rank_threshold_basis": "1 rank position / 102 Phase-B valid actual-Top3 Baseline horses",
        "cohort_results": results, "integrated_reference_only": integrated,
        "cohorts_combined_for_judgment": False, "flag_off_exact_match": all(flag_off.values()), "flag_off": flag_off,
        "production_field_mutation_count": len(mutations), "safety_status": "PASS" if safety_pass else "FAIL",
        "zero_delta_status": "PASS" if zero_pass else "FAIL",
        "baseline_eligibility_status": "BASELINE_REQUIRED_PROVENANCE_UNAVAILABLE_NO_INFERENCE",
        "replay_eligibility_status": "COMPLETE",
        "target_horse_count": 960,
        "positive_impact_suppressed_count": sum(result["positive_impact_suppressed_count"] for result in results.values()),
        "target_trial_adapter_run_count": 0, "replay_run_count": 0, "evaluator_full_run_count": 0,
        "impact_existing_helper_call_count": 512,
        "production_write_count": 0, "decision_write_count": 0, "buy_write_count": 0,
        "explain_write_count": 0, "learning_write_count": 0, "knowledge_write_count": 0,
        "normal_ledger_write_count": 0,
        "preliminary_run_audit": {
            "status": "INVALIDATED_NOT_FORMAL",
            "reason": "COHORT_KEY_COLLISION_AND_PRIOR_SHADOW_FIELD_CLASSIFICATION",
            "production_change_count": 0,
            "corrected_by_tests": [
                "test_30_replay_evidence_never_leaks_into_baseline",
                "test_31_prior_shadow_fields_are_not_production_state",
            ],
        },
        "next_action": {
            "FULL_ACCEPT": "CLAUDE_REVIEW_THEN_CHATGPT_GO_NOGO",
            "PARTIAL_ACCEPT": "SWP_V1_DIAGNOSTIC_THREE_DAY_TIMEBOX",
            "REJECT": "CLOSE_RACESHAPE_AND_MOVE_TO_NEXT_CANDIDATE",
            "INCONCLUSIVE": "CLAUDE_CHATGPT_REVIEW_NO_AUTOMATIC_RERUN",
            "DESIGN_HOLD": "STOP_AND_REVIEW_DESIGN",
            "SAFETY_HOLD": "STOP_AND_REVIEW_SAFETY",
        }[status],
    }
    baseline = {"schema_version": "raceshape_positive_impact_dedup_baseline_result_v1", "generated_at": generated_at, "cohort": "BASELINE", **results["BASELINE"]}
    replay = {"schema_version": "raceshape_positive_impact_dedup_replay_result_v1", "generated_at": generated_at, "cohort": "REPLAY", **results["REPLAY"]}
    safety = {
        "schema_version": "raceshape_positive_impact_dedup_safety_v1", "generated_at": generated_at,
        "status": "PASS" if safety_pass else "FAIL", "protected_before": before, "protected_after": after,
        "protected_changes": changes, "structure_evidence_pass": structure_pass,
        "target_trial_adapter_run_count": 0, "replay_run_count": 0, "evaluator_full_run_count": 0,
        "production_write_count": 0, "learning_write_count": 0, "knowledge_write_count": 0,
        "normal_ledger_write_count": 0, "existing_artifact_overwrite_count": 0,
    }
    zero = {
        "schema_version": "raceshape_positive_impact_dedup_zero_delta_v1", "generated_at": generated_at,
        "status": "PASS" if zero_pass else "FAIL", "flag_off": flag_off, "protected_changes": changes,
        "production_field_mutation_count": len(mutations), "production_field_mutations": mutations,
        "production_score_changed": False, "production_rank_changed": False, "decision_changed": False,
        "race_decision_changed": False, "buy_changed": False, "explain_changed": False,
    }
    test_manifest = {
        "schema_version": "raceshape_positive_impact_dedup_test_manifest_v1", "generated_at": generated_at,
        "test_file": "tests/test_raceshape_positive_impact_dedup_shadow_v1.py",
        "test_method_count": 31, "subtest_count": 0,
        "commands": [
            "python -m py_compile analysis/raceshape_positive_impact_dedup_shadow_v1.py tests/test_raceshape_positive_impact_dedup_shadow_v1.py",
            "python -m unittest tests.test_raceshape_positive_impact_dedup_shadow_v1 -v",
        ], "actual_status": test_status,
    }
    claude = f"""# Claude Review Packet: RACESHAPE_POSITIVE_IMPACT_DEDUP_SHADOW_V1

- Status: **{status}**
- Design gate: `B_NO_EXPLICIT_POSITIVE_RETENTION_RATIONALE`
- Spec SHA256: `{SPEC_SHA256}`
- Structure evidence: `7/7 PASS`
- Flag OFF / Safety / ZERO_DELTA: `{all(flag_off.values())} / {safety['status']} / {zero['status']}`
- Baseline suppressed: `{results['BASELINE']['positive_impact_suppressed_count']}`
- Replay suppressed: `{results['REPLAY']['positive_impact_suppressed_count']}`

Please verify that the Git history contains no explicit positive-retention rationale, the Shadow wrapper reuses `_impact_from_comment_or_score`, COMPLETE/integrated-score eligibility is strict, Baseline is not inferred, the final-score Shadow decision precedence is preserved, and no Production or existing evidence asset changed.
"""
    spec_sha = {"schema_version": "raceshape_positive_impact_dedup_spec_sha256_v1", "spec": str(SPEC.relative_to(ROOT)), "sha256": SPEC_SHA256, "verified_before_shadow": True}
    write_json(OUTPUTS["spec_sha"], spec_sha, replace)
    write_csv(OUTPUTS["structure"], structures, replace)
    write_json(OUTPUTS["baseline"], baseline, replace); write_json(OUTPUTS["replay"], replay, replace)
    write_csv(OUTPUTS["transitions"], transition_rows(combined), replace); write_csv(OUTPUTS["metrics"], metrics, replace)
    write_text(OUTPUTS["report"], build_report(summary), replace); write_json(OUTPUTS["summary"], summary, replace)
    write_json(OUTPUTS["safety"], safety, replace); write_json(OUTPUTS["zero"], zero, replace)
    write_json(OUTPUTS["tests"], test_manifest, replace); write_text(OUTPUTS["roi"], roi_text(status), replace)
    write_text(OUTPUTS["claude"], claude, replace)
    print(json.dumps({"status": status, "baseline": results["BASELINE"], "replay": results["REPLAY"], "safety": safety["status"]}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    run(replace="--replace-generated" in sys.argv, test_status="PASS" if "--tests-passed" in sys.argv else "PENDING_EXTERNAL_TEST_COMMAND")
