"""Governance-only reconciliation audit for April Candidate reuse.

It reads fixed April evidence metadata and the two authoritative ledger files.
It never opens April raw feature/result inputs or creates a training dataset.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "april_2026_candidate_reuse_ledger_reconciliation_v1"
LEDGER = ROOT / "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md"
INDEX = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"
DRAFT = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX_DRAFT_V3.json"
APRIL = ROOT / "reports" / "april_2026_retrospective_external_holdout_v2"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(name: str, value) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def find_gate(doc: dict) -> dict | None:
    for key in ("entries", "authoritative_additive_entries"):
        for entry in doc.get(key, []):
            if entry.get("stable_id") == "GATE-001":
                return entry
    return None


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    before_ledger, before_index = sha(LEDGER), sha(INDEX)
    index = read(INDEX); draft = read(DRAFT)
    gate_authoritative, gate_draft = find_gate(index), find_gate(draft)
    v3 = read(APRIL / "one_shot_post_evaluation_v4" / "v3_post_evaluation.json")
    post = read(APRIL / "one_shot_post_evaluation_v4" / "post_evaluation_manifest.json")
    recovery = read(APRIL / "phase_a_recovery_finalization_v3" / "phase_a_final_gate.json")
    evaluation = v3["evaluation"]
    expected = {
        "valid_count": 105, "top3_count": 41, "top3_rate": 0.3904761904761905,
        "selection_lift_percentage_points": 2.4016563146997907,
        "april_classification": "INCONCLUSIVE",
    }
    if any(evaluation.get(key) != value for key, value in expected.items()):
        raise RuntimeError("APRIL_HISTORICAL_FACT_MISMATCH")
    if v3.get("result_access_before_freeze") is not False or v3.get("post_outcome_tuning_allowed") is not False:
        raise RuntimeError("APRIL_FREEZE_BOUNDARY_MISMATCH")
    if post.get("result_join", {}).get("matched_horse_count") != 2035 or post.get("formal_variant_crosscheck") != "152/152 PASS":
        raise RuntimeError("APRIL_RESULT_JOIN_FACT_MISMATCH")
    if recovery.get("status") != "PHASE_A_RECOVERY_COMPLETE" or recovery.get("formal_variant_crosscheck") != "152/152 PASS" or recovery.get("pre_hashes_unchanged") != "PASS":
        raise RuntimeError("APRIL_RECOVERY_FINAL_STATE_MISMATCH")
    # GATE-001 remains only in the non-authoritative Draft V3.  The
    # authoritative index explicitly says its base entries are adopted from
    # that draft, but does not contain them as addressable records.  No
    # existing authoritative update field has an unambiguous GATE-001 schema.
    if gate_authoritative is not None or gate_draft is None or gate_draft.get("evidence_gate_status") != "PENDING":
        raise RuntimeError("GATE001_EXPECTED_SCHEMA_STATE_MISMATCH")
    status_vocabulary = sorted(index.get("evidence_gate_status_counts", {}).keys())
    OUT.mkdir(parents=True)
    authority = {
        "ledger": {"path": str(LEDGER.relative_to(ROOT)), "sha256": before_ledger},
        "fingerprint_index": {"path": str(INDEX.relative_to(ROOT)), "sha256": before_index},
        "draft_gate_source": {"path": str(DRAFT.relative_to(ROOT)), "sha256": sha(DRAFT), "authoritative": False},
        "april_authority_paths": [
            "reports/april_2026_retrospective_external_holdout_v2/one_shot_post_evaluation_v4/v3_post_evaluation.json",
            "reports/april_2026_retrospective_external_holdout_v2/one_shot_post_evaluation_v4/post_evaluation_manifest.json",
            "reports/april_2026_retrospective_external_holdout_v2/phase_a_recovery_finalization_v3/phase_a_final_gate.json",
        ],
    }
    historical = {
        "APRIL_HISTORICAL_HOLDOUT_COMPLETED": "YES",
        "APRIL_RESULT_ALREADY_DISCLOSED": "YES",
        "APRIL_ALREADY_CONSUMED_AS_EVIDENCE": "YES",
        "APRIL_HISTORICAL_CLASSIFICATION": evaluation["april_classification"],
        "valid_selected": evaluation["valid_count"], "top3": evaluation["top3_count"],
        "top3_rate": evaluation["top3_rate"], "selection_lift_percentage_points": evaluation["selection_lift_percentage_points"],
        "result_access_before_freeze": v3["result_access_before_freeze"],
        "post_outcome_tuning_allowed": v3["post_outcome_tuning_allowed"],
        "matched_horse_count": post["result_join"]["matched_horse_count"], "missing": 0, "ambiguous": 0,
        "formal_variant_crosscheck": post["formal_variant_crosscheck"],
        "phase_a_recovery": recovery["status"], "pre_hashes_unchanged": recovery["pre_hashes_unchanged"],
        "APRIL_DATA_INTEGRITY_BLOCKER": "NO",
    }
    review = {
        "APRIL_POST_INDEPENDENT_REVIEW_COMPLETED": "UNCLEAR",
        "reason": "No April-specific independent POST review completion artifact was found in the primary repository authority reviewed by this task.",
        "no_claim_of_verified_completion": True,
    }
    schema = {
        "existing_evidence_gate_status_vocabulary": status_vocabulary,
        "authoritative_gate001_record_present": False,
        "draft_gate001_record_present": True,
        "draft_gate001_before": gate_draft,
        "authoritative_index_base_entry_storage": "The authoritative index describes 39 immutable base entries as adopted from Draft V3, but does not embed those records.",
        "unambiguous_authoritative_update_path_for_gate001": False,
        "result": "LEDGER_SCHEMA_DECISION_REQUIRED",
        "reason": "Updating non-authoritative Draft V3 would not update the ledger authority; adding an authoritative override/record would create an unapproved structure or field semantics.",
        "new_enum_created": False,
    }
    scope = {"canonical_task": "APRIL_2026_CANDIDATE_REUSE_LEDGER_RECONCILIATION_V1", "mode": "GOVERNANCE_RECONCILIATION_ONLY", "april_raw_feature_access": 0, "april_result_rejoin": 0, "april_performance_recalculation": 0}
    assertions = {
        "GATE_001_STABLE_ID_UNCHANGED": "YES", "APRIL_HISTORICAL_RESULT_UNCHANGED": "YES",
        "APRIL_HISTORICAL_CLASSIFICATION_UNCHANGED": "YES", "APRIL_POST_INDEPENDENT_REVIEW_PROVENANCE": "UNCLEAR",
        "APRIL_DATA_INTEGRITY_BLOCKER": "NO", "LEDGER_SCHEMA_DECISION_REQUIRED": "YES",
        "authoritative_ledger_change": 0, "authoritative_fingerprint_change": 0,
    }
    safety = {"MODEL_TRAINING":0,"SCALER_FIT":0,"PREDICTION":0,"CANDIDATE_EXACT5":0,"STAGE_A_RERUN":0,"STAGE_B_EXECUTION":0,"ENGINE_CHANGE":0,"RACE_DECISION_ENGINE_CHANGE":0,"APRIL_FULL_FIELD_DATASET_BUILD":0,"APRIL_RESULT_REJOIN":0,"APRIL_PERFORMANCE_RECALCULATION":0,"JUNE_ACCESS":0,"JULY_ACCESS":0,"AUGUST_ADDITIONAL_ACCESS":0,"UNTOUCHED_HOLDOUT_ACCESS":0,"FUTURE_RESULT_ACCESS":0,"PRODUCTION_CHANGE":0,"WORK_RECORD_CHANGE":0,"GIT_COMMIT":0,"GIT_PUSH":0,"ARTIFACT_HASH_VALIDATION":"PENDING"}
    unchanged = {"ledger_before_sha256":before_ledger,"ledger_after_sha256":sha(LEDGER),"fingerprint_before_sha256":before_index,"fingerprint_after_sha256":sha(INDEX),"modified_authoritative_files":[]}
    for name, value in {"scope.json":scope,"authority_audit.json":authority,"april_historical_state.json":historical,"independent_review_provenance_audit.json":review,"ledger_schema_audit.json":schema,"gate001_before.json":{"source":"DRAFT_V3_NON_AUTHORITATIVE","entry":gate_draft},"gate001_after.json":{"status":"NOT_UPDATED","reason":"LEDGER_SCHEMA_DECISION_REQUIRED"},"fingerprint_before.json":{"sha256":before_index,"gate001_authoritative_record":None},"fingerprint_after.json":{"sha256":sha(INDEX),"gate001_authoritative_record":None},"change_manifest.json":unchanged,"reconciliation_assertions.json":assertions,"safety.json":safety}.items(): write(name,value)
    (OUT / "report.md").write_text("# April 2026 Candidate Development Reuse Ledger Reconciliation\n\n`APRIL_2026_CANDIDATE_REUSE_LEDGER_RECONCILIATION_V1 = STOP`\n\nApril historical evidence facts and Phase A recovery finalization are consistent. However, authoritative Ledger/Fingerprint storage has no addressable GATE-001 base record: GATE-001 exists only in non-authoritative Draft V3. No existing authoritative metadata/update schema unambiguously records the approved reuse role and future-OOS restriction. The two authorities were therefore left unchanged.\n\n`NEXT = CLAUDE_CHATGPT_HUMAN_LEDGER_SCHEMA_REVIEW`\n",encoding="utf-8")
    hashes={p.name:{"sha256":sha(p),"size":p.stat().st_size} for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hash_index.json"}
    write("artifact_hash_index.json",{"indexed_artifacts":hashes,"self_hash_excluded":True})
    print("APRIL_2026_CANDIDATE_REUSE_LEDGER_RECONCILIATION_V1=STOP")

if __name__ == "__main__": main()
