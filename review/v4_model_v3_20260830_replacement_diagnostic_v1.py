"""Read-only post-hoc structural diagnostic for frozen 2026-08-30 selections."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from review.prospective_three_system_pre_freeze_v1 import TRANSFORMED, vector


ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "reports" / "prospective_prediction_20260830_v1"
V4_PRE = ROOT / "reports" / "v4_model_v3_formal_prospective" / "20260830_pre"
V4_POST = ROOT / "reports" / "v4_model_v3_formal_prospective" / "20260830_post"
MODEL_ROOT = ROOT / "reports" / "ml_v4_buy_selection_model_v3"
OUT = ROOT / "reports" / "v4_model_v3_20260830_replacement_diagnostic_v1"
TARGETS = {
    "race_20260830_niigata_8R": {"out": 2, "in": 8},
    "race_20260830_niigata_12R": {"out": 5, "in": 6},
}
MODEL_SHA = "7f06d9e3ba2f330b6f42d699ee25ea64d83a5287c3b7f72fb0233e14c755312d"
SCALER_SHA = "800a0d54307e0caafef7b8efd131f5ab60f1d75d1e021dae7627d690187d103c"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_index(root: Path, key: str) -> None:
    index = json.loads((root / "artifact_hashes.json").read_text(encoding="utf-8"))[key]
    for name, expected in index.items():
        if sha(root / name) != expected:
            raise RuntimeError(f"FROZEN_ARTIFACT_HASH_MISMATCH:{root.name}:{name}")


def prediction_payload(race_id: str) -> dict[str, Any]:
    venue, number = race_id.split("_")[-2], race_id.split("_")[-1]
    path = PRE / f"race_20260830_{venue}_{number}_prediction.json"
    return json.loads(path.read_text(encoding="utf-8"))


def record(v4_records: dict[str, dict[str, Any]], race_id: str) -> dict[str, Any]:
    value = v4_records.get(race_id)
    if value is None or value.get("scope_status") != "ELIGIBLE":
        raise RuntimeError(f"V4_ELIGIBLE_RACE_MISSING:{race_id}")
    return value


def horse_feature(horse: dict[str, Any], trace: dict[str, Any], state: str) -> dict[str, Any]:
    snapshot = trace["evaluator_score_snapshot"]
    return {
        "shadow_ai_rank": trace["shadow_ai_rank"], "decision_score": horse["decision_score"],
        "final_score": horse["final_score"], "adjusted_score": horse["adjusted_score"],
        "absolute_quality_pass": trace["absolute_quality_pass"], "relative_advantage_pass": trace["relative_advantage_pass"],
        "effective_reliability_pass": trace["effective_reliability_pass"], "risk_guard_pass": trace["risk_guard_pass"],
        "consensus_positive_count": horse["consensus_positive_count"], "consensus_negative_count": horse["consensus_negative_count"],
        "risk_count": horse["risk_count"], "conflict_count": horse["conflict_count"], "race_state": state,
        "evaluators": {key: snapshot.get(key) for key in ("Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle")},
        "current_buy_decision": horse["decision"], "current_buy": horse["buy"], "current_buy_reason": horse["buy_v1_rc1_reason"],
        "risks": horse.get("risks", []), "conflicts": trace.get("conflict_factors", []),
    }


def main() -> None:
    if OUT.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    verify_index(V4_PRE, "indexed_artifacts")
    verify_index(V4_POST, "hashes")
    manifest = json.loads((PRE / "prediction_manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if sha(PRE / item["relative_path"]) != item["sha256"]:
            raise RuntimeError(f"CURRENT_PRE_HASH_MISMATCH:{item['relative_path']}")
    transform = json.loads((MODEL_ROOT / "feature_transform_schema.json").read_text(encoding="utf-8"))
    if transform["transformed_model_input_columns"] != TRANSFORMED:
        raise RuntimeError("MODEL_V3_TRANSFORM_SCHEMA_MISMATCH")
    if sha(MODEL_ROOT / "model.joblib") != MODEL_SHA or sha(MODEL_ROOT / "scaler.joblib") != SCALER_SHA:
        raise RuntimeError("MODEL_V3_FROZEN_AUTHORITY_HASH_MISMATCH")
    model = joblib.load(MODEL_ROOT / "model.joblib")
    scaler = joblib.load(MODEL_ROOT / "scaler.joblib")
    if list(getattr(model, "feature_names_in_", [])) and list(model.feature_names_in_) != TRANSFORMED:
        raise RuntimeError("MODEL_V3_FEATURE_ORDER_MISMATCH")

    v4_pre = json.loads((V4_PRE / "v4_prediction.json").read_text(encoding="utf-8"))
    v4_records = {row["race_id"]: row for row in v4_pre["races"]}
    post_comparisons = {row["race_id"]: row for row in json.loads((V4_POST / "race_level_comparison.json").read_text(encoding="utf-8"))["comparisons"]}
    pairs, race_outputs = [], {}
    for race_id, selectors in TARGETS.items():
        payload = prediction_payload(race_id)
        state = payload["buy_gate_trace"]["race"]["shadow_race_state"]
        if state != "PLAY_CONVERGED":
            raise RuntimeError(f"RACE_STATE_MISMATCH:{race_id}")
        ranked = {int(x["horse_number"]): x for x in payload["ranked_results"]}
        trace = {int(x["horse_number"]): x for x in payload["buy_gate_trace"]["horses"]}
        v4 = record(v4_records, race_id)
        probability = {int(x["horse_number"]): x["predicted_actual_top3_probability"] for x in v4["top5_probabilities"]}
        current = [int(x["horse_number"]) for x in payload["buys"]]
        selected = [int(x["horse_number"]) for x in v4["selected_horses"]]
        overlap, current_only, v4_only = sorted(set(current) & set(selected)), sorted(set(current) - set(selected)), sorted(set(selected) - set(current))
        if current_only != [selectors["out"]] or v4_only != [selectors["in"]] or len(current) != len(selected):
            raise RuntimeError(f"REPLACEMENT_STRUCTURE_MISMATCH:{race_id}")
        out_no, in_no = selectors["out"], selectors["in"]
        out_horse, in_horse = ranked[out_no], ranked[in_no]
        out_trace, in_trace = trace[out_no], trace[in_no]
        out_vec = np.asarray(vector(out_horse, out_trace, state, f"{race_id}:{out_no}"), dtype=float)
        in_vec = np.asarray(vector(in_horse, in_trace, state, f"{race_id}:{in_no}"), dtype=float)
        out_probability = float(model.predict_proba(scaler.transform(out_vec.reshape(1, -1)))[0, 1])
        in_probability = float(model.predict_proba(scaler.transform(in_vec.reshape(1, -1)))[0, 1])
        if abs(out_probability - probability[out_no]) > 1e-12 or abs(in_probability - probability[in_no]) > 1e-12:
            raise RuntimeError(f"FROZEN_MODEL_PROBABILITY_MISMATCH:{race_id}")
        contributions_out = ((out_vec - scaler.mean_) / scaler.scale_) * model.coef_[0]
        contributions_in = ((in_vec - scaler.mean_) / scaler.scale_) * model.coef_[0]
        contribution_delta = contributions_in - contributions_out
        detail = [{"feature": name, "out_scaled_x_coef": float(a), "in_scaled_x_coef": float(b), "in_minus_out_logit_contribution": float(d)} for name, a, b, d in zip(TRANSFORMED, contributions_out, contributions_in, contribution_delta, strict=True)]
        ordered_pos = sorted(detail, key=lambda x: (-x["in_minus_out_logit_contribution"], x["feature"]))[:5]
        ordered_neg = sorted(detail, key=lambda x: (x["in_minus_out_logit_contribution"], x["feature"]))[:5]
        comparison = post_comparisons[race_id]
        pair = {"race_id": race_id, "venue": comparison["venue"], "race_number": comparison["race_number"],
                "race_state": state, "buy_volume": len(current), "overlap_horses": overlap, "current_only_horses": current_only,
                "v4_only_horses": v4_only, "replacement_depth": len(current_only), "overlap_ratio": len(overlap) / len(current),
                "current_only": {"horse_number": out_no, "horse_name": out_horse["horse_name"], "pre": horse_feature(out_horse, out_trace, state), "model_probability": out_probability},
                "v4_only": {"horse_number": in_no, "horse_name": in_horse["horse_name"], "pre": horse_feature(in_horse, in_trace, state), "model_probability": in_probability},
                "probability_difference_in_minus_out": in_probability - out_probability,
                "rank_difference_in_minus_out": float(in_trace["shadow_ai_rank"]) - float(out_trace["shadow_ai_rank"]),
                "adjusted_score_difference_in_minus_out": in_horse["adjusted_score"] - out_horse["adjusted_score"],
                "decision_score_difference_in_minus_out": in_horse["decision_score"] - out_horse["decision_score"],
                "logit": {"in_minus_out": float(contribution_delta.sum()), "top_positive_contributors": ordered_pos, "top_negative_contributors": ordered_neg, "all_feature_contributions": detail},
                "result": {"out_finish": next(x["actual_finish"] for x in comparison["current_horses"] if x["horse_number"] == out_no), "in_finish": next(x["actual_finish"] for x in comparison["v4_horses"] if x["horse_number"] == in_no), "interpretation": "THIS_REPLACEMENT_WAS_SUCCESSFUL_ON_20260830"},
                "frozen_ordering": "V4 orders by predicted probability DESC, then shadow_ai_rank ASC, then horse_number ASC."}
        pairs.append(pair); race_outputs[race_id] = pair

    all_summary = []
    for race in json.loads((V4_POST / "race_level_comparison.json").read_text(encoding="utf-8"))["comparisons"]:
        current = {x["horse_number"] for x in race["current_horses"]}; v4 = {x["horse_number"] for x in race["v4_horses"]}
        all_summary.append({"race_id": race["race_id"], "venue": race["venue"], "race_number": race["race_number"], "replacement_depth": len(current-v4), "buy_volume": len(current), "overlap_ratio": len(current & v4) / len(current), "current_hits": race["current_hits"], "v4_hits": race["v4_hits"], "contribution": race["raw_hit_difference"]})
    scope = {"status": "POST_HOC_STRUCTURAL_DIAGNOSTIC_ONLY", "date": "20260830", "target_races": list(TARGETS), "new_result_access": 0, "new_formal_evidence": 0, "production_change": 0, "model_change": 0, "gate_change": 0, "protocol_change": 0, "dataset_change": 0}
    boundary = {"not_proven": ["depth=1 Gate", "V4 universal superiority", "causal feature claim", "Production readiness"], "prohibited": ["counterfactual optimization", "threshold change", "subgroup Gate", "new formal evidence"], "result_usage": "Only existing 20260830 Formal POST records; Result is displayed last and does not enter feature or contribution calculations."}
    hypothesis = {"replacement_depth_context": all_summary, "statement": "QUALITATIVELY_CONSISTENT_ONLY", "interpretation": "Both positive-contribution races have replacement_depth=1. This is not a preregistered V4-v3 subgroup diagnostic and does not confirm the May/March post-hoc hypothesis."}
    safety = {"status": "PASS", "frozen_pre_rehashed": True, "frozen_post_rehashed": True, "result_raw_access": 0, "prediction_execution": 0, "production_change": 0, "current_ai_change": 0, "v4_model_v3_change": 0, "model_v4_change": 0, "cf_change": 0, "formal_protocol_change": 0, "evidence_ledger_change": 0, "buy_gate_change": 0, "dataset_change": 0}

    OUT.mkdir(parents=True)
    dump("scope.json", scope)
    dump("race_niigata_8r_comparison.json", race_outputs["race_20260830_niigata_8R"])
    dump("race_niigata_12r_comparison.json", race_outputs["race_20260830_niigata_12R"])
    dump("replacement_pair_features.json", {"pairs": pairs})
    dump("logit_contribution_analysis.json", {"model": "V4 Model v3 frozen LogisticRegression", "method": "scaled_feature_value × frozen coefficient; IN minus OUT", "pairs": [{"race_id": p["race_id"], "logit": p["logit"]} for p in pairs]})
    dump("all_eligible_race_replacement_summary.json", {"eligible_races": all_summary, "distribution": {"replacement_depth_1": sum(x["replacement_depth"] == 1 for x in all_summary), "other": sum(x["replacement_depth"] != 1 for x in all_summary)}})
    dump("hypothesis_context.json", hypothesis)
    dump("evidence_boundary.json", boundary)
    dump("safety.json", safety)
    lines = ["# V4 vs Current Difference Diagnostic — 2026-08-30", "", "- Status: `COMPLETE_POST_HOC_STRUCTURAL_DIAGNOSTIC_ONLY`", "- `QUALITATIVELY_CONSISTENT_ONLY`: 両positive raceのreplacement depthは1。確認・採用判断ではない。", ""]
    for pair in pairs:
        lines += [f"## {pair['venue']} {pair['race_number']}R", "", f"- OUT: #{pair['current_only']['horse_number']} {pair['current_only']['horse_name']} → {pair['result']['out_finish']}着", f"- IN: #{pair['v4_only']['horse_number']} {pair['v4_only']['horse_name']} → {pair['result']['in_finish']}着", f"- V4 probability difference (IN−OUT): {pair['probability_difference_in_minus_out']:+.6f}", f"- Current BUYとV4の同容量選択を比較した固定済み診断。結果は特徴量寄与へ使っていない。", ""]
    lines += ["## What is not proven", "", "- depth=1 Gate、V4の普遍的優位、因果的feature効果、Production readinessはいずれも証明しない。"]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    dump("artifact_hashes.json", {"hashes": {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "artifact_hashes.json"}, "self_hash_excluded": True})


if __name__ == "__main__":
    main()
