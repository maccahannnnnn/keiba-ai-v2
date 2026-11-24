"""Family C Stage 1.5: frozen-February relative-advantage diagnosis only.

Phase A deliberately reads only formal PRE artifacts and locked code constants.
It freezes the reconstructed PRE-only table before Phase B consumes the already
joined February labels.
"""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from scipy.stats import mannwhitneyu, spearmanr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.buy_specification import ShadowBUYSpecV1Config
from engine.shadow_buy_decision_engine import ShadowBUYDecisionEngine

OUT = ROOT / "reports" / "v4_family_c_stage1_5_relative_advantage_v1"
PRE = ROOT / "reports" / "v4_model_v4_february_historical_holdout" / "formal_pre"
POST = ROOT / "reports" / "v4_model_v4_february_historical_holdout" / "formal_post"
STAGE1 = ROOT / "reports" / "v4_family_c_stage1_marginality_v1"
V3 = ROOT / "reports" / "v4_model_v3_prospective_protocol_v1"
V4 = ROOT / "reports" / "v4_model_v4_formal_prospective"
CF = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stop(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def dump(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_index(root: Path) -> int:
    index = load(root / "artifact_hashes.json").get("indexed_artifacts")
    if not isinstance(index, dict):
        raise Stop(f"HASH_INDEX_INVALID:{root}")
    for name, digest in index.items():
        if not isinstance(digest, str) or not (root / name).is_file() or sha(root / name) != digest:
            raise Stop(f"HASH_INDEX_MISMATCH:{root}:{name}")
    return len(index)


def percentile(values: list[float], point: float) -> float | None:
    if not values:
        return None
    return float(__import__("numpy").percentile(values, point))


def summary(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "median": percentile(values, 50),
        "mean_descriptive_only": statistics.mean(values) if values else None,
        "iqr": [percentile(values, 25), percentile(values, 75)],
        "raw_distribution": sorted(values),
    }


def compare(left: list[float], right: list[float], expected: str, labels: tuple[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {labels[0]: summary(left), labels[1]: summary(right), "expected_direction": expected}
    if not left or not right:
        payload["status"] = "NOT_EVALUABLE"
        return payload
    test = mannwhitneyu(left, right, alternative="two-sided")
    u = float(test.statistic)
    rbc = 2 * u / (len(left) * len(right)) - 1
    payload.update({"mann_whitney_u": u, "two_sided_p": float(test.pvalue), "rank_biserial_left_minus_right": rbc})
    lm, rm = percentile(left, 50), percentile(right, 50)
    supports = (expected == "LEFT_GREATER" and lm > rm and rbc > 0) or (expected == "LEFT_SMALLER" and lm < rm and rbc < 0)
    opposite = (expected == "LEFT_GREATER" and lm < rm and rbc < 0) or (expected == "LEFT_SMALLER" and lm > rm and rbc > 0)
    payload["status"] = "DIRECTIONALLY_SUPPORTS_H1" if supports else "OPPOSITE_TO_H1" if opposite else "NO_CLEAR_SEPARATION"
    return payload


def duplicate_preflight() -> dict[str, Any]:
    records = [
        {"analysis_name": "Family C Stage 1", "question": "Seven horse-local existing-gate margins", "population": "February Current BUY", "variables": ["absolute/reliability/risk count margins"], "outcome": "generic margin feature rejected as redundant", "state": "independently accepted/closed", "path": "reports/v4_family_c_stage1_marginality_v1/", "overlap": "PARTIAL", "reason": "It explicitly deferred relative advantage; it did not reconstruct top_score or evaluate a race-relative pass boundary."},
        {"analysis_name": "Relative Gap research", "question": "TRAIN-only adjusted-score gap to top", "population": "V4 TRAIN ablation", "variables": ["adjusted_score_gap_to_top"], "outcome": "separate/deferred development research", "state": "closed/deferred", "path": "reports/v4_model_v4_train_ablation_v1/; review/v4_feature_expansion_relative_gap_position_v1.py", "overlap": "PARTIAL", "reason": "Not a frozen February Current BUY exact reproduction of _score_value and relative_advantage_pass."},
        {"analysis_name": "BUY Gate Trace diagnostics", "question": "Categorical gate trace and block frequency", "population": "BUY trace cohorts", "variables": ["categorical pass/block"], "outcome": "separate", "state": "closed", "path": "reports/buy_gate_diagnostic_v1/; reports/buy_gate_trace_implementation_v1/", "overlap": "PARTIAL", "reason": "No continuous relative-advantage margin or top_score reconstruction."},
        {"analysis_name": "Race convergence diagnostics", "question": "Race-level convergence/candidate count", "population": "convergence cohorts", "variables": ["race state", "candidate count"], "outcome": "separate", "state": "closed", "path": "reports/race_convergence_quality_v1/", "overlap": "PARTIAL", "reason": "May provide context only; not an exact Stage 1.5 test."},
        {"analysis_name": "Exact Stage 1.5 equivalent", "question": "Frozen February exact relative_advantage_pass reconstruction plus positive-count by buy-volume context", "population": "February Formal Current BUY", "variables": ["top_score", "relative_gap_margin", "positive_count × buy_volume"], "outcome": "not found", "state": "NOT_FOUND", "path": None, "overlap": "NONE", "reason": None},
    ]
    return {"status": "PASS_NO_EXACT_DUPLICATE", "exact_duplicate_count": 0, "inspected_sources": ["reports/candidate_registry_v1.json", "reports/Family C", "BUY Gate Trace", "Relative Gap research", "race convergence diagnostics", "analysis/", "review/", "docs/keibaai_development_rules_v0_4.md"], "governance_sources_not_found": ["ANALYSIS_HISTORY", "DECISION_LOG", "DATA_CATALOG", "work persistent governance record"], "records": records}


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score_value(horse: dict[str, Any]) -> float | None:
    # Exact read-only mirror of ShadowBUYDecisionEngine._score_value.
    for key in ShadowBUYDecisionEngine.SCORE_KEYS:
        value = number(horse.get(key))
        if value is not None:
            return value
    return None


def rank_value(horse: dict[str, Any]) -> float | None:
    # Exact read-only mirror of ShadowBUYDecisionEngine._rank.
    return number(horse.get("rank") or horse.get("final_rank") or horse.get("score_rank"))


def authority() -> dict[str, Any]:
    config = ShadowBUYSpecV1Config
    expected = {"MAX_AI_RANK": 5, "absolute_gap_floor": 35.0, "proportional_gap_factor": 0.22}
    if config.MAX_AI_RANK != expected["MAX_AI_RANK"]:
        raise Stop("AUTHORITATIVE_MAX_AI_RANK_DIFFERS_FROM_REVIEWED_SEMANTICS")
    return {
        "status": "PASS", "authoritative_sources": {"engine": "engine/shadow_buy_decision_engine.py", "engine_sha256": sha(ROOT / "engine" / "shadow_buy_decision_engine.py"), "spec": "engine/buy_specification.py", "spec_sha256": sha(ROOT / "engine" / "buy_specification.py")},
        "score_value_logic": {"keys_in_order": list(ShadowBUYDecisionEngine.SCORE_KEYS), "missing_value_behavior": "First non-empty numeric value; otherwise None."},
        "rank_logic": {"keys_in_order": ["rank", "final_rank", "score_rank"], "safe_rank_behavior": "Missing/non-numeric rank is None and fails rank eligibility."},
        "top_score_logic": "_score_value(ranked[0]) when ranked is non-empty; no separate tie breaker. Tied top values yield top_gap=0.",
        "relative_advantage": {"max_ai_rank": config.MAX_AI_RANK, "absolute_gap_floor": 35.0, "proportional_gap_factor": 0.22, "pass_expression": "rank is not None AND rank <= MAX_AI_RANK AND score_value/top_score are not None AND (top_score-score_value) <= max(35.0, top_score*0.22)", "rank_margin_semantics": "Ordinal/discrete boundary variable retained separately; no weighted combination with gap margin."},
        "reviewed_semantics_match": True,
    }


def phase_a_reconstruct() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    eligible = load(PRE / "formal_eligible_population.json").get("eligible_races")
    if not isinstance(eligible, list):
        raise Stop("FROZEN_ELIGIBLE_POPULATION_INVALID")
    rows: list[dict[str, Any]] = []
    validation_rows = 0
    mismatches: list[dict[str, Any]] = []
    for item in eligible:
        if not isinstance(item, dict):
            raise Stop("FROZEN_ELIGIBLE_ITEM_INVALID")
        path = PRE / "current_ai" / item["date"] / f"{item['race_id']}_prediction.json"
        payload = load(path)
        ranked = payload.get("ranked_results")
        traces = payload.get("buy_gate_trace", {}).get("horses")
        if not isinstance(ranked, list) or not ranked or not isinstance(traces, list):
            raise Stop(f"FROZEN_PRE_RANKED_OR_TRACE_MISSING:{item['race_id']}")
        ranked_by_number = {int(row["horse_number"]): row for row in ranked}
        trace_by_number = {int(row["horse_number"]): row for row in traces}
        if len(ranked_by_number) != len(ranked) or len(trace_by_number) != len(ranked):
            raise Stop(f"FROZEN_PRE_HORSE_IDENTITY_OR_TRACE_COVERAGE_INVALID:{item['race_id']}")
        top = score_value(ranked[0])
        if top is None:
            raise Stop(f"RELATIVE_ADVANTAGE_TOP_SCORE_MISSING:{item['race_id']}")
        selected = item.get("current_selected_horses")
        if not isinstance(selected, list):
            raise Stop(f"FROZEN_CURRENT_SELECTION_MISSING:{item['race_id']}")
        for selected_horse in selected:
            horse_number = int(selected_horse["horse_number"])
            horse, trace = ranked_by_number.get(horse_number), trace_by_number.get(horse_number)
            if horse is None or trace is None:
                raise Stop(f"FROZEN_CURRENT_SELECTED_HORSE_MISSING:{item['race_id']}:{horse_number}")
            rank, value = rank_value(horse), score_value(horse)
            if rank is None or value is None:
                raise Stop(f"RELATIVE_ADVANTAGE_SELECTED_RANK_OR_SCORE_MISSING:{item['race_id']}:{horse_number}")
            allowed = max(35.0, top * 0.22)
            gap = top - value
            rank_eligible = rank <= ShadowBUYSpecV1Config.MAX_AI_RANK
            gap_eligible = gap <= allowed
            reproduced = bool(rank_eligible and gap_eligible)
            stored = trace.get("relative_advantage_pass")
            validation_rows += 1
            if not isinstance(stored, bool) or stored != reproduced:
                mismatches.append({"race_id": item["race_id"], "horse_number": horse_number, "stored": stored, "reconstructed": reproduced, "rank": rank, "top_gap": gap, "allowed_relative_gap": allowed})
            snapshot = trace.get("evaluator_score_snapshot")
            if not isinstance(snapshot, dict):
                raise Stop(f"FROZEN_EVALUATOR_SNAPSHOT_MISSING:{item['race_id']}:{horse_number}")
            rows.append({
                "date": item["date"], "race_id": item["race_id"], "venue": item["venue"], "race_number": item["race_number"], "race_state": item["race_state"],
                "horse_number": horse_number, "horse_name": horse.get("horse_name", ""), "frozen_current_buy": True, "buy_volume": item["current_buy_count"], "replacement_depth": item["replacement_depth"],
                "shadow_ai_rank": rank, "score_value": value, "race_top_score": top, "top_gap": gap, "allowed_relative_gap": allowed,
                "rank_eligibility": rank_eligible, "gap_eligibility": gap_eligible, "relative_advantage_pass": reproduced, "relative_gap_margin": allowed-gap,
                "rank_boundary_variable": rank, "rank_margin": ShadowBUYSpecV1Config.MAX_AI_RANK-rank,
                "decision_score": number(trace.get("decision_score")), "final_score": number(trace.get("final_score")), "adjusted_score": number(trace.get("adjusted_score")),
                "positive_count": number(trace.get("positive_count")), "negative_count": number(trace.get("negative_count")), "risk_count": len(trace.get("risk_summary", [])), "conflict_count": len(trace.get("conflict_factors", [])),
                **{f"evaluator_{key}": number(snapshot.get(key)) for key in ("Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle")},
            })
    if len(rows) != 133:
        raise Stop(f"FROZEN_CURRENT_BUY_COUNT_MISMATCH:{len(rows)}")
    validation = {"status": "PASS" if not mismatches else "FAIL", "total_rows": validation_rows, "matches": validation_rows-len(mismatches), "mismatches": len(mismatches), "mismatch_rate": len(mismatches)/validation_rows if validation_rows else None, "mismatch_examples": mismatches[:20], "required_state": "RELATIVE_ADVANTAGE_RECONSTRUCTION_VALIDATION = PASS" if not mismatches else "RELATIVE_ADVANTAGE_EXACT_RECONSTRUCTION_NOT_PROVEN"}
    if mismatches:
        raise Stop("RELATIVE_ADVANTAGE_EXACT_RECONSTRUCTION_NOT_PROVEN")
    return rows, validation


def write_phase_a(rows: list[dict[str, Any]], validation: dict[str, Any], authority_record: dict[str, Any]) -> dict[str, str]:
    dump("relative_advantage_code_authority.json", authority_record)
    dump("phase_a_evidence_boundary.json", {"phase": "A_PRE_ONLY_RECONSTRUCTION", "allowed": ["Frozen February PRE", "locked code/spec", "pre-existing PRE model outputs"], "forbidden": ["actual_top3", "finish", "Result CSV", "POST outcome columns", "outcome-based filtering", "result-derived flags"], "state": "RELATIVE_ADVANTAGE_PRE_RECONSTRUCTION = FROZEN_BEFORE_RESULT_JOIN"})
    fields = list(rows[0])
    with (OUT / "relative_advantage_pre_reconstruction.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    dump("reconstruction_validation.json", validation)
    hashes = {name: sha(OUT / name) for name in ("relative_advantage_code_authority.json", "phase_a_evidence_boundary.json", "relative_advantage_pre_reconstruction.csv", "reconstruction_validation.json")}
    dump("phase_a_artifact_hashes.json", {"state": "RELATIVE_ADVANTAGE_PRE_RECONSTRUCTION = FROZEN_BEFORE_RESULT_JOIN", "indexed_artifacts": hashes, "self_hash_excluded": True})
    return {**hashes, "phase_a_artifact_hashes.json": sha(OUT / "phase_a_artifact_hashes.json")}


def phase_b_join(rows: list[dict[str, Any]], phase_a_hash: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if sha(OUT / "relative_advantage_pre_reconstruction.csv") != phase_a_hash:
        raise Stop("PHASE_A_ARTIFACT_SHA_CHANGED_BEFORE_RESULT_JOIN")
    joined = load(POST / "selection_result_join.json")
    outcomes = {(row["race_id"], int(row["horse_number"])): row for row in joined.get("current_selected", [])}
    v4 = {(row["race_id"], int(row["horse_number"])): row for row in joined.get("v4_selected", [])}
    eligible = {item["race_id"]: item for item in load(PRE / "formal_eligible_population.json")["eligible_races"]}
    output: list[dict[str, Any]] = []
    for row in rows:
        key = (row["race_id"], row["horse_number"])
        outcome = outcomes.get(key)
        if outcome is None or not outcome.get("valid_result"):
            raise Stop(f"CONSUMED_RESULT_JOIN_MISSING_OR_INVALID:{key}")
        copied = dict(row)
        copied["actual_top3"] = bool(outcome["actual_top3"])
        if copied["buy_volume"] == 1 and copied["replacement_depth"] == 1:
            selected_v4 = eligible[copied["race_id"]]["v4_selected_horses"]
            if len(selected_v4) != 1:
                raise Stop(f"FROZEN_FOCAL_PAIR_INVALID:{copied['race_id']}")
            paired = v4.get((copied["race_id"], int(selected_v4[0]["horse_number"])))
            if paired is None or not paired.get("valid_result"):
                raise Stop(f"CONSUMED_V4_PAIR_RESULT_MISSING:{copied['race_id']}")
            copied["replacement_pair_outcome"] = int(bool(paired["actual_top3"]))-int(copied["actual_top3"])
        else:
            copied["replacement_pair_outcome"] = None
        output.append(copied)
    if sum(row["actual_top3"] for row in output) != 35:
        raise Stop("FORMAL_CURRENT_BUY_OUTCOME_TOTAL_MISMATCH")
    after = sha(OUT / "relative_advantage_pre_reconstruction.csv")
    if after != phase_a_hash:
        raise Stop("PHASE_A_ARTIFACT_SHA_CHANGED_AFTER_RESULT_JOIN")
    return output, {"phase_a_artifact": "relative_advantage_pre_reconstruction.csv", "phase_a_sha_before_result_join": phase_a_hash, "phase_a_sha_after_result_join": after, "mismatch_count": 0, "consumed_result_source": str((POST / "selection_result_join.json").relative_to(ROOT)), "result_joined_rows": len(output), "formal_current_top3": "35/133", "mutation_of_phase_a_values": 0}


def outcome_tests(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    success = [row for row in rows if row["actual_top3"]]
    failure = [row for row in rows if not row["actual_top3"]]
    focal = [row for row in rows if row["buy_volume"] == 1 and row["replacement_depth"] == 1]
    control = [row for row in rows if row["buy_volume"] == 1 and row["replacement_depth"] == 0]
    benefit = [row for row in focal if row["replacement_pair_outcome"] == 1]
    nonbenefit = [row for row in focal if row["replacement_pair_outcome"] in (0, -1)]
    if (len(success), len(failure), len(focal), len(control), len(benefit), len(nonbenefit)) != (35, 98, 30, 11, 11, 19):
        raise Stop("FROZEN_STAGE1_5_POPULATION_MISMATCH")
    def selected(group: list[dict[str, Any]], key: str) -> list[float]: return [float(row[key]) for row in group]
    test1 = {key: compare(selected(success, key), selected(failure, key), "LEFT_GREATER", ("top3_success", "non_top3_failure")) for key in ("relative_gap_margin", "top_gap", "rank_boundary_variable")}
    test2 = {key: compare(selected(focal, key), selected(control, key), "LEFT_SMALLER", ("focal_depth1", "one_buy_depth0_control")) for key in ("relative_gap_margin", "top_gap", "rank_boundary_variable")}
    test3 = {key: compare(selected(benefit, key), selected(nonbenefit, key), "LEFT_SMALLER", ("positive_replacement_benefit", "nonpositive_replacement_benefit")) for key in ("relative_gap_margin", "top_gap", "rank_boundary_variable")}
    return ({"population": "All February Formal Current BUY", "test": "Current BUY Top3 success vs non-Top3 failure", "components": test1}, {"population": "buy_volume=1 AND replacement_depth=1 vs buy_volume=1 AND replacement_depth=0", "test": "PRE-only focal vs no-replacement control", "components": test2}, {"population": "Focal depth=1", "test": "Positive V4 replacement benefit (+1) vs non-positive (0/-1)", "components": test3})


def redundancy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bases = ["decision_score", "final_score", "adjusted_score", "shadow_ai_rank", "evaluator_Ability", "evaluator_PastPerformance", "evaluator_Distance", "evaluator_CourseShape", "evaluator_LapSuitability", "evaluator_RaceShape", "evaluator_PaceStyle", "positive_count", "negative_count", "risk_count", "conflict_count"]
    result: dict[str, Any] = {}
    target = [float(row["relative_gap_margin"]) for row in rows]
    for base in bases:
        pairs = [(float(row[base]), float(row["relative_gap_margin"])) for row in rows if row.get(base) is not None]
        if len(pairs) < 3:
            result[base] = {"status": "NOT_EVALUABLE", "n": len(pairs)}
            continue
        x, y = zip(*pairs)
        rho = float(spearmanr(x, y).statistic)
        exact = all(abs(a-b) < 1e-12 for a, b in pairs)
        result[base] = {"n": len(pairs), "spearman_rho": rho, "high_correlation": abs(rho) > .90, "exact_duplicate": exact, "deterministic_transform_status": "NOT_EXACT_DUPLICATE" if not exact else "EXACT_DUPLICATE"}
    race_top_by_race = {row["race_id"]: row["race_top_score"] for row in rows}
    return {"status": "PASS", "relative_variable": "relative_gap_margin", "horse_local_feature_comparisons": result, "race_state": {"type": "categorical", "correlation": "NOT_APPLICABLE", "exact_duplicate": False}, "race_level_top_score": {"available": True, "distinct_race_top_score_count": len(set(race_top_by_race.values())), "interpretation": "top_score is a PRE-available race-level quantity. It is not stored as a horse-local V4 semantic feature in this diagnostic; its presence is what can make relative_gap_margin non-identical to a horse-local score."}, "classification": "NON_REDUNDANT" if not any(item.get("exact_duplicate") for item in result.values()) else "EXACT_REEXPRESSION", "automatic_feature_selection": "PROHIBITED"}


def context_check() -> dict[str, Any]:
    path = STAGE1 / "margin_dataset.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    output: dict[str, Any] = {}
    directions: list[str] = []
    for volume in (1, 2, 3):
        active = [float(row["positive_evaluator_margin"]) for row in rows if int(row["buy_volume"]) == volume and int(row["replacement_depth"]) >= 1]
        control = [float(row["positive_evaluator_margin"]) for row in rows if int(row["buy_volume"]) == volume and int(row["replacement_depth"]) == 0]
        item = compare(active, control, "LEFT_SMALLER", ("replacement_active", "no_replacement"))
        direction = "yes" if item["status"] == "DIRECTIONALLY_SUPPORTS_H1" else "no" if item["status"] == "OPPOSITE_TO_H1" else "not_evaluable"
        item.update({"buy_volume": volume, "direction_consistent_with_buyvolume1_pattern": direction, "p_interpretation": "descriptive_only"})
        directions.append(direction); output[str(volume)] = item
    status = "CONTEXT_PATTERN_DIRECTIONALLY_REPEATED" if directions[1:] == ["yes", "yes"] else "CONTEXT_PATTERN_BUYVOLUME1_SPECIFIC" if directions[1:] == ["no", "no"] else "CONTEXT_PATTERN_NOT_EVALUABLE" if all(x == "not_evaluable" for x in directions[1:]) else "CONTEXT_PATTERN_MIXED"
    return {"source": str(path.relative_to(ROOT)), "source_sha256": sha(path), "question": "replacement occurrence context only; not an outcome analysis", "by_buy_volume": output, "status": status}


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    authority_hashes_before = {"pre": sha(PRE / "artifact_hashes.json"), "post": sha(POST / "artifact_hashes.json"), "stage1": sha(STAGE1 / "artifact_hashes.json"), "v3": sha(V3 / "artifact_hashes.json"), "v4": sha(V4 / "artifact_hashes.json"), "cf": sha(CF / "protocol.json")}
    checks = {"frozen_pre_verified": verify_index(PRE), "frozen_post_verified": verify_index(POST), "stage1_verified": verify_index(STAGE1), "v3_verified": verify_index(V3), "v4_verified": verify_index(V4)}
    preflight = duplicate_preflight()
    if preflight["exact_duplicate_count"]:
        raise Stop("EXACT_STAGE1_5_DUPLICATE_EXISTS")
    OUT.mkdir(parents=True)
    dump("duplicate_analysis_preflight.json", preflight)
    dump("scope.json", {"status": "POST_HOC_CONSUMED_DATA_DIAGNOSTIC_ONLY", "question_a": "relative_advantage exact boundary information", "question_b": "positive evaluator context by buy_volume", "forbidden": ["feature implementation", "model training", "gate change", "prediction rerun", "new holdout", "new Result acquisition"]})
    auth = authority()
    phase_a_rows, validation = phase_a_reconstruct()
    phase_a_hashes = write_phase_a(phase_a_rows, validation, auth)
    phase_a_csv_hash = phase_a_hashes["relative_advantage_pre_reconstruction.csv"]
    phase_b_rows, join_manifest = phase_b_join(phase_a_rows, phase_a_csv_hash)
    test1, test2, test3 = outcome_tests(phase_b_rows)
    redundancy_result = redundancy(phase_a_rows)
    context = context_check()
    technical = "RELATIVE_ADVANTAGE_SIGNAL_PRESENT" if test1["components"]["relative_gap_margin"]["status"] == "DIRECTIONALLY_SUPPORTS_H1" and redundancy_result["classification"] == "NON_REDUNDANT" else "RELATIVE_ADVANTAGE_NO_CLEAR_SIGNAL"
    assessment = {"FAMILY_C_STAGE1_5": "COMPLETE_PENDING_INDEPENDENT_REVIEW", "RELATIVE_ADVANTAGE_TECHNICAL_OBSERVATION": technical.replace("RELATIVE_ADVANTAGE_", ""), "POSITIVE_EVALUATOR_CONTEXT_CHECK": context["status"].replace("CONTEXT_PATTERN_", ""), "FAMILY_C_STATUS": "OPEN_PENDING_INDEPENDENT_REVIEW", "h1_authority": "GATE_MARGIN_HYPOTHESIS_H1 = WEAKENED (unchanged)", "measurement_only": True}
    dump("phase_b_result_join_manifest.json", join_manifest)
    dump("current_buy_outcome_diagnostic.json", test1)
    dump("focal_vs_control_diagnostic.json", test2)
    dump("replacement_benefit_diagnostic.json", test3)
    dump("relative_advantage_redundancy.json", redundancy_result)
    dump("positive_evaluator_context_generalization.json", context)
    dump("family_c_stage1_5_assessment.json", assessment)
    dump("evidence_boundary.json", {"formal_evidence_unchanged": "Current 35/133=26.32%; V4 49/133=36.84%; lift +10.53pt; Historical Gate PASS", "stage1_5": "POST_HOC_CONSUMED_DATA_DIAGNOSTIC_ONLY", "prospective_tracks": {"V4_MODEL_V4_FORMAL_PROSPECTIVE_STATUS": "READY_FOR_FIRST_FORMAL_PRE", "V4_MODEL_V3_FORMAL_PROSPECTIVE_SHADOW": "CONTINUE", "CF_EVIDENCE_TRACK": "SEPARATE_AND_CONTINUING"}, "no_evidence_mixing": True})
    authority_hashes_after = {"pre": sha(PRE / "artifact_hashes.json"), "post": sha(POST / "artifact_hashes.json"), "stage1": sha(STAGE1 / "artifact_hashes.json"), "v3": sha(V3 / "artifact_hashes.json"), "v4": sha(V4 / "artifact_hashes.json"), "cf": sha(CF / "protocol.json")}
    if authority_hashes_before != authority_hashes_after:
        raise Stop("FROZEN_AUTHORITY_MUTATION")
    dump("safety.json", {"status": "PASS", "production_change_count": 0, "current_ai_change_count": 0, "buy_gate_change_count": 0, "decision_engine_change_count": 0, "shadow_buy_semantics_change_count": 0, "model_v4_change_count": 0, "scaler_change_count": 0, "dataset_change_count": 0, "v3_protocol_change_count": 0, "v4_protocol_change_count": 0, "cf_protocol_change_count": 0, "prediction_execution_count": 0, "new_result_acquisition_count": 0, "untouched_holdout_access_count": 0, "february_pre_mutation_count": 0, "february_post_mutation_count": 0, "trace_schema_mutation_count": 0, "authority_hashes_before_after": authority_hashes_after, **checks})
    report = ["# Family C Stage 1.5 — Relative Advantage + Context", "", "- `FAMILY_C_STAGE1_5 = COMPLETE_PENDING_INDEPENDENT_REVIEW`", "- Phase A PRE-only reconstruction was frozen and hash-checked before the consumed Result join.", "- No feature, model, gate, prediction, or Production change was made.", f"- Relative technical observation: `{assessment['RELATIVE_ADVANTAGE_TECHNICAL_OBSERVATION']}`", f"- Positive evaluator context: `{assessment['POSITIVE_EVALUATOR_CONTEXT_CHECK']}`", "- `FAMILY_C_STATUS = OPEN_PENDING_INDEPENDENT_REVIEW`", ""]
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    hashes = {path.name: sha(path) for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}
    dump("artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": hashes})
    if any(sha(OUT / name) != digest for name, digest in hashes.items()):
        raise Stop("ARTIFACT_HASH_MISMATCH")
    print("FAMILY_C_STAGE1_5=COMPLETE_PENDING_INDEPENDENT_REVIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
