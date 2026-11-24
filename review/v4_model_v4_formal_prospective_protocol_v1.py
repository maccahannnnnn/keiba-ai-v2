"""Freeze V4 Model v4's separate Formal Prospective Shadow protocol only."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "v4_model_v4_formal_prospective"
MODEL = ROOT / "reports" / "ml_v4_buy_selection_model_v4"
V3 = ROOT / "reports" / "v4_model_v3_prospective_protocol_v1"
CF = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"
MODEL_SHA = "58d3977d0f44eab325a2b384f0c17b66ddc276fff6370f6e05b7a1680642d74f"
SCALER_SHA = "3d18757f4991c21a4a645f92ca26361d88c030a4097696d2cc4a6c86d3767b90"
DATASET_SHA = "b02bb4b59b5f297e60964f96050890dbf32a7ac3b5a9ef93424b9d612e3ae80a"
ROLE = "FORMAL_PROSPECTIVE_SHADOW_V4_MODEL_V4"


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, payload: Any) -> None:
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stop(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def verify_index(root: Path) -> int:
    indexed = read(root / "artifact_hashes.json").get("indexed_artifacts", read(root / "artifact_hashes.json").get("hashes"))
    if not isinstance(indexed, dict):
        raise Stop(f"HASH_INDEX_INVALID:{root}")
    for name, digest in indexed.items():
        if not isinstance(digest, str) or not (root / name).is_file() or sha(root / name) != digest:
            raise Stop(f"HASH_INDEX_MISMATCH:{root}:{name}")
    return len(indexed)


def protocol() -> dict[str, Any]:
    return {
        "protocol_version": "V4_MODEL_V4_FORMAL_PROSPECTIVE_SHADOW_PROTOCOL_V1",
        "status": "FROZEN_PENDING_INDEPENDENT_REVIEW",
        "evidence_role": ROLE,
        "candidate": "V4 Model v4",
        "eligibility": "PLAY_CONVERGED AND Current BUY >= 1",
        "comparator": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK",
        "same_volume_rule": "V4 selected count equals Current BUY count for each eligible race; permitted Current volume is 1/2/3 only.",
        "selection_order": ["P(actual_top3) DESC", "safe shadow_ai_rank ASC", "horse_number ASC"],
        "formal_minimum_evidence": {"eligible_races_ge": 60, "independent_dates_ge": 12, "early_accept": "PROHIBITED"},
        "formal_gate": {"metric": "pooled_same_volume_lift_percentage_points", "threshold_ge": 0.0, "population": "ALL eligible races including replacement_depth=0"},
        "invalid_result_semantics": "finish>0 and abnormal code empty/0; invalid selected rows excluded from valid denominator and reported separately.",
        "pre_result_access_prohibited": True,
        "relative_gap": "AVAILABLE_BUT_NOT_SELECTED_FOR_MODEL_V4",
        "cross_candidate_comparison": "NOT_A_CONTROLLED_AB_TEST",
        "formal_start": "A date may run only after independent protocol review and Human activation approval.",
    }


def empty_ledger(protocol_sha: str) -> dict[str, Any]:
    return {
        "ledger_version": "V4_MODEL_V4_FORMAL_PROSPECTIVE_EVIDENCE_LEDGER_V1",
        "model_version": "V4 Model v4", "evidence_role": ROLE, "protocol_sha256": protocol_sha,
        "completed_formal_dates": 0, "eligible_dates": [], "eligible_races": 0,
        "current_selected": 0, "v4_selected": 0,
        "current_valid": 0, "v4_valid": 0, "current_hits": 0, "v4_hits": 0,
        "pooled_same_volume_lift_percentage_points": None,
        "formal_gate": "NOT_EVALUATED_INSUFFICIENT_MINIMUM_EVIDENCE",
        "state": "NOT_STARTED", "artifact_references": [],
        "excluded_nonformal_evidence": ["February 2026 Historical Holdout", "March Historical", "April", "May", "V4 Model v3 Formal Prospective", "2026-08-29 V4 Reference", "CF evidence", "development CV", "Family C diagnostics"],
    }


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    before = {
        "model": sha(MODEL / "model.joblib"), "scaler": sha(MODEL / "scaler.joblib"),
        "dataset": sha(ROOT / "reports" / "ml_v4_buy_selection_dataset_v4" / "dataset.csv"),
        "v3_protocol": sha(V3 / "protocol.json"), "cf_protocol": sha(CF / "protocol.json"),
    }
    if (before["model"], before["scaler"], before["dataset"]) != (MODEL_SHA, SCALER_SHA, DATASET_SHA):
        raise Stop("MODEL_AUTHORITY_SHA_MISMATCH")
    v3_verified, cf_verified = verify_index(V3), None
    selected = read(MODEL / "selected_feature_columns.json")
    if selected.get("relative_gap_status") != "AVAILABLE_BUT_NOT_SELECTED_FOR_MODEL_V4" or len(selected.get("semantic_selected_columns", [])) != 20 or len(selected.get("transformed_selected_columns", [])) != 21:
        raise Stop("MODEL_V4_FEATURE_AUTHORITY_MISMATCH")
    OUT.mkdir(parents=True)
    frozen = protocol()
    write("protocol.json", frozen)
    psha = sha(OUT / "protocol.json")
    write("activation_record.json", {"candidate": "V4 Model v4", "protocol_sha256": psha, "activation": "HOLD_PENDING_INDEPENDENT_REVIEW", "actual_racing_date": None, "pre_execution_count": 0, "result_access_count": 0, "human_approval": "PROTOCOL_IMPLEMENTATION_ONLY"})
    write("model_authority.json", {"model_root": str(MODEL.relative_to(ROOT)), "model_sha256": before["model"], "scaler_sha256": before["scaler"], "dataset_sha256": before["dataset"], "semantic_input_count": 20, "transformed_input_count": 21, "relative_gap": "AVAILABLE_BUT_NOT_SELECTED_FOR_MODEL_V4", "model_mutation_count": 0})
    write("eligibility_rule.json", {"status": "FROZEN", "rule": "PLAY_CONVERGED AND Current BUY >= 1", "semantic_change_prohibited": True})
    write("same_volume_rule.json", {"status": "FROZEN", "rule": "V4 selected count equals Current BUY count for every eligible race", "current_buy_volume_values": [1, 2, 3], "arbitrary_volume_adjustment": "PROHIBITED"})
    write("selection_rule.json", {"status": "FROZEN", "ordering": frozen["selection_order"], "result_information_in_pre": "PROHIBITED", "tie_break": "safe shadow_ai_rank then horse_number"})
    write("formal_gate.json", {"status": "FROZEN", "minimum_evidence": frozen["formal_minimum_evidence"], "gate": frozen["formal_gate"], "primary_metrics": ["selected", "valid", "invalid", "Top3 hits", "Top3 rate", "raw hit difference", "pooled same-volume lift"]})
    write("replacement_depth_preregistration.json", {"status": "PREREGISTERED_DIAGNOSTIC_NON_GATE", "definition": "current_only_count = v4_only_count; replacement_depth = current_only_count", "bins": [0, 1, 2, 3], "per_pre_eligible_race_fields": ["overlap_count", "current_only_count", "v4_only_count", "replacement_depth"], "same_count_required": True})
    write("buy_volume_preregistration.json", {"status": "PREREGISTERED_DIAGNOSTIC_NON_GATE", "definition": "Current BUY count per eligible race", "bins": [1, 2, 3], "later_bin_modification": "PROHIBITED"})
    write("replacement_active_subset_diagnostic.json", {"status": "PREREGISTERED_DIAGNOSTIC_NON_GATE", "definition": "replacement_active = replacement_depth >= 1", "metric": "REPLACEMENT_ACTIVE_SUBSET_LIFT", "report_fields": ["races", "Current valid N/hits/rate", "V4 valid N/hits/rate", "raw hit difference", "lift"], "formal_gate_population": "NOT_THIS_SUBSET"})
    write("depth_buyvolume_cross_diagnostic.json", {"status": "PREREGISTERED_DIAGNOSTIC_NON_GATE", "definition": "mechanically report observed cells implied by replacement_depth <= buy_volume", "report_fields": ["races", "Current N/hits/rate", "V4 N/hits/rate", "raw hit difference", "lift"], "optimization": "PROHIBITED", "gate_use": "PROHIBITED"})
    write("temporal_diagnostics.json", {"status": "PREREGISTERED_DIAGNOSTIC_NON_GATE", "lodo": "For each completed independent date remove the date and recalculate pooled metrics.", "concentration": {"date_contribution": "V4 hits - Current hits", "sort": ["contribution DESC", "date ASC"], "remove_date_count": "ceil(completed_dates / 3)", "report": ["Current N/hits/rate", "V4 N/hits/rate", "raw hit difference", "lift"]}})
    write("statistical_uncertainty_spec.json", {"status": "PREREGISTERED_DIAGNOSTIC_NON_GATE", "labels": ["APPROXIMATE_DIAGNOSTIC_ONLY", "RACE_WITHIN_SELECTION_DEPENDENCE_NOT_MODELED"], "standard_error_formula": "sqrt(p_current*(1-p_current)/n_current + p_v4*(1-p_v4)/n_v4)", "report_fields": ["Current valid N/hits/rate", "V4 valid N/hits/rate", "raw hit difference", "pooled lift", "approximate z", "approximate two-sided p-value"]})
    write("invalid_result_semantics.json", {"status": "FROZEN", "valid_result": "finish>0 AND abnormal code is empty or 0", "invalid_handling": "excluded from valid denominator; neither success nor failure", "required_post_field": "invalid_selected_count per candidate"})
    write("cross_candidate_display_rule.json", {"cross_candidate_comparison_status": "NOT_A_CONTROLLED_AB_TEST", "shared_current_baseline_race_set": True, "prohibited_statistic": "v4_lift - v3_lift as standalone independent-comparison statistic", "reason": "V3/V4 share Current baseline and race outcomes; candidate lifts are statistically correlated."})
    write("evidence_ledger.json", empty_ledger(psha))
    write("evidence_boundary.json", {"role": ROLE, "formal_prospective_totals_start": "ZERO", "excluded_from_totals": empty_ledger(psha)["excluded_nonformal_evidence"], "historical_may_be_lineage_only": True, "new_feature_model_rule": "A feature-modified model is a new candidate with a new SHA and Formal Prospective evidence starts at zero."})
    write("safety.json", {"status": "PASS", "production_change_count": 0, "buy_gate_change_count": 0, "current_ai_change_count": 0, "decision_engine_change_count": 0, "model_v4_change_count": 0, "scaler_change_count": 0, "dataset_v4_change_count": 0, "model_v3_protocol_change_count": 0, "cf_protocol_change_count": 0, "prediction_execution_count": 0, "result_access_count": 0, "formal_post_execution_count": 0, "v3_artifacts_verified": v3_verified, "cf_protocol_sha_before_after": before["cf_protocol"], "v3_protocol_sha_before_after": before["v3_protocol"]})
    report = ["# V4 Model v4 Formal Prospective Shadow Protocol", "", f"- Protocol: `{frozen['status']}`", "- Activation: `HOLD_PENDING_INDEPENDENT_REVIEW`", f"- Evidence role: `{ROLE}`", "- Initial Formal Prospective evidence: `0 dates / 0 races / 0 selections`", "- V3: `CONTINUE`", "- CF: `SEPARATE_AND_CONTINUING`", "- Family C: `INDEPENDENT_OF_V4_PROSPECTIVE_START`", "- Prediction / Result access: `0`", ""]
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    after = {"model": sha(MODEL / "model.joblib"), "scaler": sha(MODEL / "scaler.joblib"), "dataset": sha(ROOT / "reports" / "ml_v4_buy_selection_dataset_v4" / "dataset.csv"), "v3_protocol": sha(V3 / "protocol.json"), "cf_protocol": sha(CF / "protocol.json")}
    if before != after:
        raise Stop("FROZEN_AUTHORITY_MUTATION")
    hashes = {path.name: sha(path) for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}
    write("artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": hashes})
    if any(sha(OUT / name) != digest for name, digest in hashes.items()):
        raise Stop("PROTOCOL_ARTIFACT_FREEZE_MISMATCH")
    print("V4_MODEL_V4_FORMAL_PROSPECTIVE_PROTOCOL=FROZEN_PENDING_INDEPENDENT_REVIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
