"""Family C Stage-1: consumed February Current BUY margin diagnostic only."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

from scipy.stats import mannwhitneyu, spearmanr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.buy_specification import ShadowBUYSpecV1Config


OUT = ROOT / "reports" / "v4_family_c_stage1_marginality_v1"
PRE = ROOT / "reports" / "v4_model_v4_february_historical_holdout" / "formal_pre"
POST = ROOT / "reports" / "v4_model_v4_february_historical_holdout" / "formal_post"
V4_MODEL = ROOT / "reports" / "ml_v4_buy_selection_model_v4"
V3_PROTOCOL = ROOT / "reports" / "v4_model_v3_prospective_protocol_v1"
V4_PROTOCOL = ROOT / "reports" / "v4_model_v4_formal_prospective"
CF = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"
COMPONENTS = ("decision_score_margin", "final_score_margin", "adjusted_score_margin", "positive_evaluator_margin", "negative_evaluator_margin", "risk_count_margin", "conflict_count_margin")


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stop(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def dump(name: str, payload: Any) -> None:
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_index(root: Path) -> int:
    payload = load(root / "artifact_hashes.json")
    entries = payload.get("indexed_artifacts", payload.get("hashes"))
    if not isinstance(entries, dict):
        raise Stop(f"HASH_INDEX_INVALID:{root}")
    for name, digest in entries.items():
        if not isinstance(digest, str) or not (root / name).is_file() or sha(root / name) != digest:
            raise Stop(f"HASH_INDEX_MISMATCH:{root}:{name}")
    return len(entries)


def q(values: list[float], at: float) -> float | None:
    if not values:
        return None
    return float(__import__("numpy").percentile(values, at))


def describe(values: list[float]) -> dict[str, Any]:
    return {"n": len(values), "median": q(values, 50), "mean_descriptive_only": statistics.mean(values) if values else None, "iqr": [q(values, 25), q(values, 75)]}


def comparison(left: list[float], right: list[float], expected: str, labels: tuple[str, str]) -> dict[str, Any]:
    if not left or not right:
        return {"status": "NOT_EVALUABLE", labels[0]: describe(left), labels[1]: describe(right)}
    u = float(mannwhitneyu(left, right, alternative="two-sided").statistic)
    p = float(mannwhitneyu(left, right, alternative="two-sided").pvalue)
    rbc = 2 * u / (len(left) * len(right)) - 1  # positive means left tends larger than right
    left_median, right_median = q(left, 50), q(right, 50)
    if expected == "LEFT_GREATER":
        state = "DIRECTIONALLY_SUPPORTS_H1" if left_median > right_median and rbc > 0 else "OPPOSITE_TO_H1" if left_median < right_median and rbc < 0 else "NO_CLEAR_SEPARATION"
    else:  # LEFT_SMALLER
        state = "DIRECTIONALLY_SUPPORTS_H1" if left_median < right_median and rbc < 0 else "OPPOSITE_TO_H1" if left_median > right_median and rbc > 0 else "NO_CLEAR_SEPARATION"
    return {"status": state, labels[0]: describe(left), labels[1]: describe(right), "mann_whitney_u": u, "two_sided_p": p, "rank_biserial_left_minus_right": rbc, "expected_direction": expected}


def duplicate_preflight() -> dict[str, Any]:
    records = [
        {"analysis_name": "BUY Gate block-frequency / trace diagnostics", "question_asked": "Which categorical gate/trace block occurs and how often?", "population": "prior BUY trace cohorts", "variables": ["pass/block states", "trace reasons"], "outcome": "categorical block-frequency evidence", "state": "closed / separate", "artifact_path": "reports/buy_gate_diagnostic_v1/; reports/buy_gate_trace_implementation_v1/", "overlap_with_current_stage1": "PARTIAL", "exclusion": "No continuous boundary-distance measure or February formal Current BUY success/failure comparison."},
        {"analysis_name": "NET_CONSENSUS_SCORE", "question_asked": "Does saved net consensus score separate BUY success/failure within BUY-count layers?", "population": "18-date historical BUY trace", "variables": ["net_consensus_score"], "outcome": "same-BUY-count descriptive analysis", "state": "closed descriptive", "artifact_path": "reports/net_consensus_same_buy_count_v1/", "overlap_with_current_stage1": "PARTIAL", "exclusion": "Net consensus is not any of the seven fixed continuous existing-gate margins."},
        {"analysis_name": "ONE_BUY_STABILITY / race_buy_count", "question_asked": "Does race BUY count relate to BUY behavior?", "population": "historical BUY cohorts", "variables": ["race buy count"], "outcome": "race-level stability/count context", "state": "closed / separate", "artifact_path": "reports/buy_precision_v1/; reports/buy_gate_count_correct_rejected_v1/", "overlap_with_current_stage1": "PARTIAL", "exclusion": "No horse-level continuous decision-boundary margin."},
        {"analysis_name": "RACE_CONVERGENCE_QUALITY", "question_asked": "How does race convergence state relate to selection quality?", "population": "convergence cohort", "variables": ["race state", "candidate count"], "outcome": "race-level convergence observation", "state": "closed / separate", "artifact_path": "reports/race_convergence_quality_v1/", "overlap_with_current_stage1": "NONE", "exclusion": "No Current BUY gate distance analysis."},
        {"analysis_name": "Relative Gap experiments", "question_asked": "Does adjusted-score gap to top add TRAIN-only model signal?", "population": "V4 TRAIN ablation", "variables": ["adjusted_score_gap_to_top"], "outcome": "relative-gap development assessment", "state": "closed / deferred", "artifact_path": "reports/v4_model_v4_train_ablation_v1/; review/v4_feature_expansion_relative_gap_position_v1.py", "overlap_with_current_stage1": "PARTIAL", "exclusion": "Relative advantage is expressly deferred; no Engine rerun or top-score reconstruction."},
        {"analysis_name": "Exact prior continuous Current BUY gate-margin diagnostic", "question_asked": "Same seven per-component distances from frozen BUY boundaries on February Current BUY success/failure, focal vs control, and replacement benefit", "population": "February formal Current BUY", "variables": list(COMPONENTS), "outcome": "not found in inspected governance/reports/review records", "state": "NOT_FOUND", "artifact_path": None, "overlap_with_current_stage1": "NONE", "exclusion": None},
    ]
    return {"status": "PASS_NO_EXACT_DUPLICATE", "inspected_sources": ["reports/candidate_registry_v1.json", "reports/ directories relevant to BUY Gate/precision", "docs/keibaai_development_rules_v0_4.md", "analysis/", "review/"], "governance_sources_not_found": ["ANALYSIS_HISTORY", "DECISION_LOG", "DATA_CATALOG", "work persistent governance record"], "records": records, "exact_duplicate_count": 0, "continue_scope": "seven fixed per-component margins only"}


def authority() -> dict[str, Any]:
    source = ROOT / "engine" / "buy_specification.py"
    values = {
        "MIN_DECISION_SCORE": ShadowBUYSpecV1Config.MIN_DECISION_SCORE,
        "MIN_FINAL_SCORE": ShadowBUYSpecV1Config.MIN_FINAL_SCORE,
        "MIN_ADJUSTED_SCORE": ShadowBUYSpecV1Config.MIN_ADJUSTED_SCORE,
        "MIN_POSITIVE_EVALUATORS": ShadowBUYSpecV1Config.MIN_POSITIVE_EVALUATORS,
        "MAX_NEGATIVE_EVALUATORS": ShadowBUYSpecV1Config.MAX_NEGATIVE_EVALUATORS,
        "MAX_RISK_COUNT": ShadowBUYSpecV1Config.MAX_RISK_COUNT,
        "MAX_CONFLICT_COUNT": ShadowBUYSpecV1Config.MAX_CONFLICT_COUNT,
    }
    expected = {"MIN_DECISION_SCORE": .8, "MIN_FINAL_SCORE": 130.0, "MIN_ADJUSTED_SCORE": 145.0, "MIN_POSITIVE_EVALUATORS": 5, "MAX_NEGATIVE_EVALUATORS": 1, "MAX_RISK_COUNT": 5, "MAX_CONFLICT_COUNT": 1}
    if values != expected:
        raise Stop("AUTHORITATIVE_THRESHOLD_VALUES_UNEXPECTED")
    return {"status": "PASS", "source_path": str(source.relative_to(ROOT)), "source_sha256": sha(source), "source_locations": {"absolute_quality": ["engine/buy_specification.py:92-94", "engine/shadow_buy_decision_engine.py:160-164"], "effective_reliability": ["engine/buy_specification.py:101-102", "engine/shadow_buy_decision_engine.py:175-185"], "risk_guard": ["engine/buy_specification.py:109-110", "engine/shadow_buy_decision_engine.py:189-190"]}, "constants": values, "deferred": {"RELATIVE_ADVANTAGE_MARGIN": "DEFERRED_PENDING_READ_ONLY_RERUN_DESIGN_REVIEW", "RISK_KEYWORD_MARGIN_COMPONENT": "DEFERRED_RECONSTRUCTABLE"}}


def traces_and_outcomes() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    eligible = load(PRE / "formal_eligible_population.json")["eligible_races"]
    joined = load(POST / "selection_result_join.json")
    current_outcomes = {(row["race_id"], int(row["horse_number"])): row for row in joined["current_selected"]}
    v4_outcomes = {(row["race_id"], int(row["horse_number"])): row for row in joined["v4_selected"]}
    rows: list[dict[str, Any]] = []
    rescue_fields_present = 0
    for item in eligible:
        path = PRE / "current_ai" / item["date"] / f"{item['race_id']}_prediction.json"
        payload = load(path)
        trace = {int(row["horse_number"]): row for row in payload.get("buy_gate_trace", {}).get("horses", [])}
        if len(trace) != len(payload.get("ranked_results", [])):
            raise Stop(f"FROZEN_BUY_TRACE_COVERAGE_MISMATCH:{item['race_id']}")
        current_numbers = [int(row["horse_number"]) for row in item["current_selected_horses"]]
        for number in current_numbers:
            gate = trace.get(number); outcome = current_outcomes.get((item["race_id"], number))
            if gate is None or outcome is None:
                raise Stop(f"FROZEN_CURRENT_BUY_TRACE_OR_RESULT_MISSING:{item['race_id']}:{number}")
            if "risk_summary" not in gate or "conflict_factors" not in gate:
                raise Stop(
                    "BUY_GATE_TRACE_RISK_OR_CONFLICT_FIELD_MISSING:"
                    f"{item['race_id']}:{number}"
                )
            risks, conflicts = gate["risk_summary"], gate["conflict_factors"]
            if not isinstance(risks, list) or not isinstance(conflicts, list):
                raise Stop(f"PERSISTED_RISK_SEMANTICS_INVALID:{item['race_id']}:{number}")
            rescue_available = "consensus_rescue_applied" in gate
            rescue_fields_present += int(rescue_available)
            record = {
                "date": item["date"], "race_id": item["race_id"], "venue": item["venue"], "race_number": item["race_number"],
                "horse_number": number, "horse_name": outcome["horse_name"], "buy_volume": item["current_buy_count"], "replacement_depth": item["replacement_depth"],
                "valid_result": outcome["valid_result"], "actual_top3": outcome["actual_top3"], "actual_finish": outcome["actual_finish"],
                "decision_score": gate["decision_score"], "final_score": gate["final_score"], "adjusted_score": gate["adjusted_score"],
                "positive_count": gate["positive_count"], "negative_count": gate["negative_count"], "risk_count": len(risks), "conflict_count": len(conflicts),
                "absolute_quality_pass": gate["absolute_quality_pass"], "effective_reliability_pass": gate["effective_reliability_pass"], "reliability_pass": gate["reliability_pass"], "risk_guard_pass": gate["risk_guard_pass"],
                "consensus_rescue_status": gate.get("consensus_rescue_applied") if rescue_available else "NOT_PERSISTED_IN_FROZEN_TRACE",
                "decision_score_margin": float(gate["decision_score"]) - ShadowBUYSpecV1Config.MIN_DECISION_SCORE,
                "final_score_margin": float(gate["final_score"]) - ShadowBUYSpecV1Config.MIN_FINAL_SCORE,
                "adjusted_score_margin": float(gate["adjusted_score"]) - ShadowBUYSpecV1Config.MIN_ADJUSTED_SCORE,
                "positive_evaluator_margin": int(gate["positive_count"]) - ShadowBUYSpecV1Config.MIN_POSITIVE_EVALUATORS,
                "negative_evaluator_margin": ShadowBUYSpecV1Config.MAX_NEGATIVE_EVALUATORS - int(gate["negative_count"]),
                "risk_count_margin": ShadowBUYSpecV1Config.MAX_RISK_COUNT - len(risks),
                "conflict_count_margin": ShadowBUYSpecV1Config.MAX_CONFLICT_COUNT - len(conflicts),
            }
            if item["current_buy_count"] == 1 and item["replacement_depth"] == 1:
                v4 = item["v4_selected_horses"]
                if len(v4) != 1:
                    raise Stop(f"FROZEN_FOCAL_V4_PAIR_INVALID:{item['race_id']}")
                v4_result = v4_outcomes.get((item["race_id"], int(v4[0]["horse_number"])))
                if v4_result is None:
                    raise Stop(f"FROZEN_FOCAL_V4_OUTCOME_MISSING:{item['race_id']}")
                record["replacement_pair_outcome"] = int(v4_result["actual_top3"]) - int(outcome["actual_top3"])
            else:
                record["replacement_pair_outcome"] = None
            rows.append(record)
    if len(rows) != 133 or sum(bool(row["actual_top3"]) for row in rows) != 35 or any(not row["valid_result"] for row in rows):
        raise Stop("FROZEN_CURRENT_BUY_POPULATION_REPRODUCTION_MISMATCH")
    meta = {"rescue_status_available_count": rescue_fields_present, "rescue_status_not_persisted_count": len(rows) - rescue_fields_present, "effective_reliability_pass_count": sum(bool(row["effective_reliability_pass"]) for row in rows), "raw_reliability_pass_count": sum(bool(row["reliability_pass"]) for row in rows)}
    return rows, meta


def diagnostics(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    success, failure = [row for row in rows if row["actual_top3"]], [row for row in rows if not row["actual_top3"]]
    focal = [row for row in rows if row["buy_volume"] == 1 and row["replacement_depth"] == 1]
    control = [row for row in rows if row["buy_volume"] == 1 and row["replacement_depth"] == 0]
    benefit, nonbenefit = [row for row in focal if row["replacement_pair_outcome"] == 1], [row for row in focal if row["replacement_pair_outcome"] in (0, -1)]
    if (len(focal), len(control), len(benefit), len(nonbenefit)) != (30, 11, 11, 19):
        raise Stop(f"FROZEN_STAGE1_POPULATION_MISMATCH:{len(focal)}:{len(control)}:{len(benefit)}:{len(nonbenefit)}")
    all_tests = {component: comparison([float(row[component]) for row in success], [float(row[component]) for row in failure], "LEFT_GREATER", ("top3_success", "non_top3_failure")) for component in COMPONENTS}
    focal_tests = {component: comparison([float(row[component]) for row in focal], [float(row[component]) for row in control], "LEFT_SMALLER", ("focal_replacement_active", "one_buy_no_replacement_control")) for component in COMPONENTS}
    benefit_tests = {component: comparison([float(row[component]) for row in benefit], [float(row[component]) for row in nonbenefit], "LEFT_SMALLER", ("positive_replacement_benefit", "nonpositive_replacement_benefit")) for component in COMPONENTS}
    grouped = {"absolute_quality": {key: all_tests[key] for key in COMPONENTS[:3]}, "effective_reliability": {key: all_tests[key] for key in COMPONENTS[3:5]}, "risk_guard_count": {key: all_tests[key] for key in COMPONENTS[5:]}}
    return all_tests, focal_tests, benefit_tests, grouped


def redundancy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source = {"decision_score_margin": "decision_score", "final_score_margin": "final_score", "adjusted_score_margin": "adjusted_score", "positive_evaluator_margin": "positive_count", "negative_evaluator_margin": "negative_count", "risk_count_margin": "risk_count", "conflict_count_margin": "conflict_count"}
    signs = {"decision_score_margin": 1, "final_score_margin": 1, "adjusted_score_margin": 1, "positive_evaluator_margin": 1, "negative_evaluator_margin": -1, "risk_count_margin": -1, "conflict_count_margin": -1}
    entries = {}
    for margin, base in source.items():
        rho = float(spearmanr([float(row[margin]) for row in rows], [float(row[base]) for row in rows]).statistic)
        entries[margin] = {"existing_v4_semantic_feature": {"decision_score": "decision_score", "final_score": "final_score", "adjusted_score": "adjusted_score", "positive_count": "consensus_positive_count", "negative_count": "consensus_negative_count", "risk_count": "risk_count", "conflict_count": "conflict_count"}[base], "spearman_rho": rho, "high_redundancy": abs(rho) > .90, "relationship": f"EXACT_AFFINE_TRANSFORM_SIGN_{'POSITIVE' if signs[margin] > 0 else 'NEGATIVE'}", "interpretation": "mostly a re-expression of an existing V4 semantic feature; no multivariate selection performed."}
    return {"status": "PASS", "components": entries, "automatic_rejection": "PROHIBITED"}


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    before = {"pre": sha(PRE / "artifact_hashes.json"), "post": sha(POST / "artifact_hashes.json"), "v3": sha(V3_PROTOCOL / "artifact_hashes.json"), "v4_protocol": sha(V4_PROTOCOL / "artifact_hashes.json"), "cf": sha(CF / "protocol.json")}
    check = {"february_pre_verified": verify_index(PRE), "february_post_verified": verify_index(POST), "v3_protocol_verified": verify_index(V3_PROTOCOL), "v4_protocol_verified": verify_index(V4_PROTOCOL)}
    preflight = duplicate_preflight()
    if preflight["exact_duplicate_count"]:
        raise Stop("EXACT_DUPLICATE_ANALYSIS_EXISTS")
    thresholds = authority()
    rows, rescue = traces_and_outcomes()
    all_tests, focal_tests, benefit_tests, grouped = diagnostics(rows)
    redundancy_result = redundancy(rows)
    after = {"pre": sha(PRE / "artifact_hashes.json"), "post": sha(POST / "artifact_hashes.json"), "v3": sha(V3_PROTOCOL / "artifact_hashes.json"), "v4_protocol": sha(V4_PROTOCOL / "artifact_hashes.json"), "cf": sha(CF / "protocol.json")}
    if before != after:
        raise Stop("FROZEN_AUTHORITY_MUTATION")
    OUT.mkdir(parents=True)
    dump("duplicate_analysis_preflight.json", preflight)
    dump("scope.json", {"status": "CONSUMED_DATA_DIAGNOSTIC_ONLY", "immediate_scope": ["absolute_quality margin components", "effective_reliability margin components", "risk_guard COUNT margin components"], "deferred": ["relative_advantage margin", "severe-risk keyword reconstruction", "data-limitation keyword reconstruction", "trace extension", "Engine rerun"], "component_count": 7, "forbidden": ["composite marginality", "threshold optimization", "feature implementation", "new holdout"]})
    dump("threshold_authority.json", thresholds)
    dump("population_manifest.json", {"population_a_focal": {"definition": "buy_volume=1 AND replacement_depth=1", "races": 30, "current": "4/30", "v4": "13/30"}, "population_b_all_formal_current_buy": {"selected": len(rows), "top3_success": sum(row["actual_top3"] for row in rows), "non_top3_failure": sum(not row["actual_top3"] for row in rows)}, "population_c_replacement_active": {"races": 62, "depth1_races": 51, "depth2_races": 11, "usage": "descriptive/context only"}, "population_c_prime": {"definition": "buy_volume=1 AND replacement_depth=0", "races": 11}, "rescue_handling": rescue})
    fields = list(rows[0])
    with (OUT / "margin_dataset.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    dump("absolute_quality_diagnostic.json", {"test": "All Current BUY Top3 success vs non-Top3 failure", "components": grouped["absolute_quality"]})
    dump("reliability_diagnostic.json", {"test": "All Current BUY Top3 success vs non-Top3 failure", "components": grouped["effective_reliability"], "rescue_handling": rescue, "note": "No rescue-adjusted continuous score was created."})
    dump("risk_count_diagnostic.json", {"test": "All Current BUY Top3 success vs non-Top3 failure", "components": grouped["risk_guard_count"], "risk_keyword_margin_component": "DEFERRED_RECONSTRUCTABLE"})
    dump("focal_vs_control.json", {"test": "Focal buy_volume=1/replacement_depth=1 vs One-BUY no-replacement control", "components": focal_tests})
    dump("replacement_benefit_margin.json", {"test": "Focal positive replacement outcome (+1) vs non-positive (0/-1)", "components": benefit_tests})
    dump("feature_redundancy.json", redundancy_result)
    dump("prior_analysis_overlap.json", {"current_question": "Among Current BUY selections, does continuous distance from an existing frozen decision boundary identify fragility?", "distinct_from": ["Gate block frequency", "NET_CONSENSUS_SCORE", "ONE_BUY_STABILITY/race BUY count", "RACE_CONVERGENCE_QUALITY", "Relative Gap experiments"], "preflight_reference": "duplicate_analysis_preflight.json"})
    dump("evidence_boundary.json", {"frozen_february_formal_evidence": "Current 35/133=26.32%; V4 49/133=36.84%; lift +10.53pt; unchanged", "relative_advantage_margin": "DEFERRED_PENDING_READ_ONLY_RERUN_DESIGN_REVIEW", "no_feature_candidate_created": True, "formal_tracks": {"V4_MODEL_V4_FORMAL_PROSPECTIVE_STATUS": "READY_FOR_FIRST_FORMAL_PRE", "V4_MODEL_V3_FORMAL_PROSPECTIVE_SHADOW": "CONTINUE", "CF_EVIDENCE_TRACK": "SEPARATE_AND_CONTINUING"}})
    dump("safety.json", {"status": "PASS", "production_change_count": 0, "current_ai_change_count": 0, "buy_gate_change_count": 0, "decision_engine_change_count": 0, "shadow_buy_semantics_change_count": 0, "model_v4_change_count": 0, "scaler_change_count": 0, "dataset_v4_change_count": 0, "v3_prospective_protocol_change_count": 0, "v4_prospective_protocol_change_count": 0, "cf_protocol_change_count": 0, "prediction_execution_count": 0, "new_result_acquisition_count": 0, "untouched_holdout_access_count": 0, "frozen_february_artifact_mutation_count": 0, "authority_hashes_before_after": after, **check})
    all_states = {component: all_tests[component]["status"] for component in COMPONENTS}
    report = ["# Family C Stage 1 — Current BUY Boundary / Marginality", "", "- Final: `STAGE1_FAMILY_C_DIAGNOSTIC = COMPLETE_PENDING_INDEPENDENT_REVIEW`", "- Duplicate preflight: `PASS_NO_EXACT_DUPLICATE`", "- Formal February evidence unchanged: `Current 35/133=26.32%; V4 49/133=36.84%; lift +10.53pt`", "- All seven margins are exact affine transforms of existing V4 semantic features; no composite or new feature was created.", "", "## Component classification (success vs failure)", ""]
    report.extend(f"- `{component}`: `{state}`" for component, state in all_states.items())
    report.extend(["", "- Relative advantage: `DEFERRED_PENDING_READ_ONLY_RERUN_DESIGN_REVIEW`", "- V4 Formal Prospective: `READY_FOR_FIRST_FORMAL_PRE`", "- V3: `CONTINUE`; CF: `SEPARATE_AND_CONTINUING`", ""])
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    hashes = {path.name: sha(path) for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}
    dump("artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": hashes})
    if any(sha(OUT / name) != digest for name, digest in hashes.items()):
        raise Stop("STAGE1_ARTIFACT_HASH_MISMATCH")
    print("STAGE1_FAMILY_C_DIAGNOSTIC=COMPLETE_PENDING_INDEPENDENT_REVIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
