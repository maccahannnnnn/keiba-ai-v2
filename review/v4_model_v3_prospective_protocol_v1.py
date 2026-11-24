"""Formal prospective V4-v3 protocol artifact creator; no prospective execution."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from review.v4_model_v3_prospective_validator_v1 import MIN_DATES, MIN_RACES, ROLE, validate_ledger


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "v4_model_v3_prospective_protocol_v1"
MODEL = ROOT / "reports" / "ml_v4_buy_selection_model_v3"


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path: Path, payload: object) -> None: path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def protocol() -> dict:
    return {"protocol_version": "V4_MODEL_V3_FORMAL_PROSPECTIVE_SHADOW_PROTOCOL_V1", "status": "HUMAN_APPROVED_AND_FROZEN", "evidence_role": ROLE, "model_version": "V4 Model v3", "formal_eligibility": "PLAY_CONVERGED AND Current BUY >= 1", "comparator": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "same_volume": "per-race Current BUY count", "selection_order": ["predicted P(actual_top3) DESC", "safe shadow_ai_rank ASC", "horse_number ASC"], "minimum_evidence": {"independent_eligible_races": MIN_RACES, "independent_eligible_dates": MIN_DATES}, "lift_threshold_percentage_points": 0.0, "invalid_result_semantics": "finish>0 and abnormal code empty/0; invalid rows excluded from valid denominator", "phase_a_b_gate": {"phase_a": ["source integrity", "population", "model SHA", "comparator", "same-volume", "prediction schema", "Result access 0", "evidence role", "date exclusivity", "artifact freeze"], "phase_b": "Claude-authored pre_independent_review_manifest.json, BLOCKING=0, then Human confirmation"}, "multi_shadow_governance": ["EACH_CANDIDATE_EVALUATED_ONLY_AGAINST_ITS_OWN_FROZEN_GATE", "NO_POST_HOC_WINNER_SELECTION_ACROSS_PARALLEL_SHADOW_CANDIDATES"], "quiet_stopping": "RUNNING candidate must reach minimum evidence or have SUSPENDED state with reason, timestamp, and Human decision.", "freeze_boundary": "Any post-disclosure semantic change requires a new model/protocol version and Formal Prospective evidence restarts at zero.", "sole_phase_a_exception": "Only human-approved technical correction before any aggregate performance calculation/disclosure, preserving prediction/selection semantics, with SHA and independent review.", "historical_boundaries": {"march": "CONSUMED_TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V3; not Formal Prospective", "may": "Model v2 OOS / later training reuse lineage; not Formal Prospective", "v4_20260829": "REFERENCE_SHADOW_ONLY_PENDING_HISTORICAL_GATE; not Formal Prospective", "cf": "separate candidate; never pooled"}, "formal_start": "next unseen JRA date after Protocol implementation, Independent Review, and Human approval"}


def ledger(protocol_sha: str) -> dict:
    value = {"ledger_version": "V4_MODEL_V3_FORMAL_PROSPECTIVE_EVIDENCE_LEDGER_V1", "model_version": "V4 Model v3", "evidence_role": ROLE, "protocol_sha256": protocol_sha, "start_date": None, "eligible_dates": [], "eligible_races": 0, "current_selected": 0, "v4_selected": 0, "current_valid": 0, "v4_valid": 0, "current_hits": 0, "v4_hits": 0, "pooled_lift_percentage_points": None, "decision_state": "SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE", "state": "NOT_STARTED", "flags": {"temporal_fragility": None, "temporal_concentration": None}, "suspended": False, "suspension_reason": None, "suspension_timestamp": None, "human_decision": None, "artifact_references": [], "excluded_nonformal_evidence": ["March Historical Holdout", "May OOS", "April External Holdout", "2026-08-29 V4 Reference Shadow", "CF Formal Prospective"]}
    validate_ledger(value)
    return value


def main() -> int:
    if OUT.exists(): raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    model_hashes = {name: sha(MODEL / name) for name in ("model.joblib", "scaler.joblib", "model_metadata.json", "training_manifest.json", "feature_transform_schema.json")}
    OUT.mkdir(parents=True)
    p = protocol(); write(OUT / "protocol.json", p); psha = sha(OUT / "protocol.json")
    write(OUT / "evidence_ledger.json", ledger(psha))
    (OUT / "protocol.md").write_text("# V4 Model v3 Formal Prospective Shadow Protocol v1\n\nFrozen formal protocol. It contains no prospective evidence and authorizes no execution.\n", encoding="utf-8")
    write(OUT / "model_authority.json", {"model_root": str(MODEL.relative_to(ROOT)), "sha256": model_hashes, "model_mutation": 0})
    write(OUT / "safety.json", {"status": "PASS", "prospective_pre_execution_count": 0, "result_access_count": 0, "post_execution_count": 0, "production_change_count": 0, "model_change_count": 0, "cf_change_count": 0, "march_artifact_mutation_count": 0, "may_artifact_mutation_count": 0})
    hashes = {x.name: sha(x) for x in OUT.iterdir() if x.is_file() and x.name != "artifact_hashes.json"}; write(OUT / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": hashes})
    print("V4_MODEL_V3_FORMAL_PROSPECTIVE_IMPLEMENTATION=COMPLETE_PENDING_INDEPENDENT_REVIEW")
    return 0


if __name__ == "__main__": raise SystemExit(main())
