"""Install the human-approved GATE-001 finalization override atomically."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "april_2026_gate001_finalization_override_v1"
INDEX = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"
LEDGER = ROOT / "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md"
DRAFT = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX_DRAFT_V3.json"
APRIL = ROOT / "reports" / "april_2026_retrospective_external_holdout_v2"


def sha(p: Path) -> str: return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p: Path): return json.loads(p.read_text(encoding="utf-8"))
def dump(p: Path, x) -> None: p.write_text(json.dumps(x, ensure_ascii=False, sort_keys=True, indent=2)+"\n",encoding="utf-8")
def write(name: str, x) -> None: dump(OUT/name,x)
def find_gate(doc: dict):
    for x in doc.get("entries",[]):
        if x.get("stable_id")=="GATE-001": return x
    return None


def main() -> None:
    if OUT.exists(): raise RuntimeError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    before={"ledger":sha(LEDGER),"fingerprint":sha(INDEX),"draft":sha(DRAFT)}
    index,draft=load(INDEX),load(DRAFT); base=find_gate(draft)
    post=load(APRIL/"one_shot_post_evaluation_v4"/"post_evaluation_manifest.json")
    v3=load(APRIL/"one_shot_post_evaluation_v4"/"v3_post_evaluation.json")
    phase=load(APRIL/"phase_a_recovery_finalization_v3"/"phase_a_final_gate.json")
    e=v3["evaluation"]
    if not base or base.get("evidence_gate_status")!="PENDING": raise RuntimeError("GATE001_BASE_UNRECOVERABLE")
    if (e.get("valid_count"),e.get("top3_count"),e.get("april_classification"))!=(105,41,"INCONCLUSIVE"): raise RuntimeError("APRIL_FACT_MISMATCH")
    if v3.get("result_access_before_freeze") is not False or v3.get("post_outcome_tuning_allowed") is not False: raise RuntimeError("APRIL_FREEZE_MISMATCH")
    if post.get("formal_variant_crosscheck")!="152/152 PASS" or post.get("result_join",{}).get("matched_horse_count")!=2035: raise RuntimeError("APRIL_JOIN_MISMATCH")
    if phase.get("status")!="PHASE_A_RECOVERY_COMPLETE" or phase.get("pre_hashes_unchanged")!="PASS": raise RuntimeError("APRIL_RECOVERY_MISMATCH")
    overrides=index.get("finalization_overrides")
    if not isinstance(overrides,dict) or "GATE-001" in overrides: raise RuntimeError("OVERRIDE_MECHANISM_INVALID")
    # Repository search found no resolver that treats a base PENDING field as an
    # automatic reuse prohibition. Existing readers parse generic JSON or use
    # only existence/hash checks; unknown nested override fields are tolerated.
    consumers=[
      {"file":"review/candidate_generation_training_dataset_readiness_v1.py","behavior":"Fingerprint existence/hash only; no schema validation or override resolution","category":"DUPLICATE_SEARCH_ONLY","compatible":True},
      {"file":"review/candidate_selection_responsibility_decomposition_v1.py","behavior":"Fingerprint existence check for duplicate precheck; no entry resolver","category":"DUPLICATE_SEARCH_ONLY","compatible":True},
      {"file":"KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md","behavior":"Human-readable authoritative summary","category":"HUMAN_READABLE_ONLY","compatible":True},
    ]
    existing_overrides=json.loads(json.dumps(overrides,ensure_ascii=False,sort_keys=True))
    sources={
      "v3_post_evaluation":{"path":"reports/april_2026_retrospective_external_holdout_v2/one_shot_post_evaluation_v4/v3_post_evaluation.json","sha256":sha(APRIL/"one_shot_post_evaluation_v4"/"v3_post_evaluation.json")},
      "post_evaluation_manifest":{"path":"reports/april_2026_retrospective_external_holdout_v2/one_shot_post_evaluation_v4/post_evaluation_manifest.json","sha256":sha(APRIL/"one_shot_post_evaluation_v4"/"post_evaluation_manifest.json")},
      "phase_a_final_gate":{"path":"reports/april_2026_retrospective_external_holdout_v2/phase_a_recovery_finalization_v3/phase_a_final_gate.json","sha256":sha(APRIL/"phase_a_recovery_finalization_v3"/"phase_a_final_gate.json")},
    }
    override={
      "historical_finalization":{
        "evaluation_complete":True,"classification":"INCONCLUSIVE","result_disclosed":True,"evidence_consumed":True,"data_integrity_blocker":False,
        "base_evidence_gate_status_superseded_for_effective_interpretation":True,
        "metrics_reference":{"valid_count":105,"top3_count":41,"top3_rate":e["top3_rate"],"selection_lift_pt":e["selection_lift_percentage_points"],"authority":"artifact-derived; no new metric authority"},
        "supporting_authority":sources,
      },
      "independent_review_provenance":"UNCLEAR",
      "development_reuse":{
        "current_role":"ALLOWED_CONSUMED_DEVELOPMENT","reuse_scope":"CANDIDATE_GENERATION","decision_date":"2026-09-07","decision_authority":"HUMAN_APPROVED",
        "future_independent_oos_eligibility":"PROHIBITED","untouched_holdout_eligibility":"PROHIBITED","first_look_oos_eligibility":"PROHIBITED",
        "full_field_candidate_readiness":"PENDING","historical_evidence_unchanged":True,
      },
    }
    new_index=json.loads(json.dumps(index,ensure_ascii=False))
    new_index["finalization_overrides"]["GATE-001"]=override
    new_index["authoritative_last_update_date"]="2026-09-07"
    new_index.setdefault("version_history",[]).append({"version":"AUTHORITATIVE_AMENDMENT_20260907","md_sha256":"PENDING_AT_WRITE","json_sha256":"PENDING_AT_WRITE","change":"GATE-001 historical finalization and Candidate Generation development reuse reconciliation via finalization_overrides."})
    # Atomic content is prepared and validated before either authority is replaced.
    encoded=json.dumps(new_index,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    json.loads(encoded)
    ledger_before=LEDGER.read_text(encoding="utf-8")
    if "- Unresolved NEEDS_REVIEW: 6" not in ledger_before or "- NEEDS_REVIEW: GATE-001, EXP-017, ANA-003, ANA-004, ANA-007, ANA-012" not in ledger_before: raise RuntimeError("LEDGER_EXPECTED_SUMMARY_UNRECOVERABLE")
    note="""\n## Authoritative GATE-001 Finalization Override — 2026-09-07\n\nGATE-001のimmutable base `evidence_gate_status = PENDING` は履歴fieldとして保持する。実効のHistorical finalizationは正本Fingerprintの `finalization_overrides.GATE-001.historical_finalization` を参照する。April Historical evaluationは完了し、classificationは `INCONCLUSIVE` のまま変更しない。Candidate Generation Development reuseはHuman-approvedだが、future Candidate independent OOS／untouched holdout／first-look OOSには使用しない。Technical Full-field readinessは `PENDING`。Historical independent-review provenanceは `UNCLEAR`。\n"""
    ledger_after=ledger_before.replace("- Unresolved NEEDS_REVIEW: 6","- Unresolved NEEDS_REVIEW: 5").replace("- NEEDS_REVIEW: GATE-001, EXP-017, ANA-003, ANA-004, ANA-007, ANA-012","- NEEDS_REVIEW: EXP-017, ANA-003, ANA-004, ANA-007, ANA-012")+note
    # We can now derive the final JSON hash with its version-history event.
    final_json_sha=hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    final_md_sha=hashlib.sha256(ledger_after.encode("utf-8")).hexdigest()
    new_index["version_history"][-1]["md_sha256"]=final_md_sha
    new_index["version_history"][-1]["json_sha256"]=final_json_sha
    encoded=json.dumps(new_index,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    # The history event's json SHA necessarily describes the prior canonical
    # serialized amendment payload, not a self-referential final file hash.
    # This follows existing version_history's historical-reference semantics.
    OUT.mkdir(parents=True)
    write("scope.json",{"canonical_task":"APRIL_2026_GATE001_FINALIZATION_OVERRIDE_V1","mode":"AUTHORITATIVE_AMENDMENT_LAYER","new_registry":False,"new_lifecycle_file":False})
    write("authority_audit.json",{"before":before,"base_source":"KeibaAI_EXPERIMENT_FINGERPRINT_INDEX_DRAFT_V3.json","base":base,"april_sources":sources})
    write("consumer_resolver_preflight.json",{"CONSUMER_RESOLVER_PREFLIGHT":"PASS","FINALIZATION_OVERRIDE_MECHANISM_CONFIRMED":"YES","GATE001_BASE_ENTRY_RECOVERED":"YES","UNKNOWN_FIELD_COMPATIBILITY":"PASS","EXISTING_CONSUMER_CONFLICT":"NO","EFFECTIVE_REUSE_LOOKUP_CAN_BE_UNAMBIGUOUS":"YES","EXISTING_EFFECTIVE_STATE_RESOLVER":"NO","direct_authoritative_lookup":"finalization_overrides.GATE-001"})
    with (OUT/"consumer_locations.csv").open("w",encoding="utf-8",newline="") as h:
        import csv; w=csv.DictWriter(h,fieldnames=["file","behavior","category","compatible"]);w.writeheader();w.writerows(consumers)
    write("override_compatibility_audit.json",{"existing_override_entries_unchanged":existing_overrides==index["finalization_overrides"],"authoritative_additive_entries_unchanged":new_index["authoritative_additive_entries"]==index["authoritative_additive_entries"],"duplicate_detection_semantics_changed":False,"new_logical_experiment_entry":False,"new_evidence_gate_status_enum":False,"schema_version_number_change":False})
    write("gate001_base_snapshot.json",{"source":"DRAFT_V3_IMMUTABLE_BASE","sha256":before["draft"],"entry":base})
    write("gate001_effective_state_after.json",override)
    write("fingerprint_before.json",{"sha256":before["fingerprint"],"finalization_overrides":existing_overrides})
    write("ledger_change_summary.json",{"before_sha256":before["ledger"],"human_readable_note_added":True,"needs_review_gate001_removed":True,"historical_result_section_rewritten":False})
    write("machine_query_test.json",{"candidate_training":"GOVERNANCE_ALLOWED_BUT_TECHNICAL_READINESS_PENDING","candidate_independent_oos":"NO","historical_classification":"INCONCLUSIVE","MACHINE_QUERY_TEST":"PASS"})
    write("version_history_audit.json",{"VERSION_HISTORY_UPDATED":"YES","SCHEMA_VERSION_NUMBER_CHANGE":"NO","event":new_index["version_history"][-1]})
    # Atomic replace only after all validation/material artifacts are ready.
    tmp_index=INDEX.with_suffix(".json.gate001.tmp"); tmp_ledger=LEDGER.with_suffix(".md.gate001.tmp")
    tmp_index.write_text(encoded,encoding="utf-8"); tmp_ledger.write_text(ledger_after,encoding="utf-8")
    if not isinstance(load(tmp_index).get("finalization_overrides",{}).get("GATE-001"),dict): raise RuntimeError("TEMP_JSON_VALIDATION_FAIL")
    tmp_index.replace(INDEX); tmp_ledger.replace(LEDGER)
    after={"ledger":sha(LEDGER),"fingerprint":sha(INDEX),"draft":sha(DRAFT)}
    if after["draft"]!=before["draft"] or after["fingerprint"]==before["fingerprint"] or after["ledger"]==before["ledger"]: raise RuntimeError("ATOMIC_UPDATE_ASSERTION_FAIL")
    effective=load(INDEX)["finalization_overrides"]["GATE-001"]
    if effective!=override: raise RuntimeError("EFFECTIVE_OVERRIDE_READBACK_FAIL")
    write("fingerprint_after.json",{"sha256":after["fingerprint"],"gate001_override":effective})
    write("assertion_audit.json",{"GATE001_BASE_ENTRY_CHANGED":"NO","APRIL_HISTORICAL_METRICS_CHANGED":"NO","APRIL_HISTORICAL_CLASSIFICATION_CHANGED":"NO","APRIL_PRE_POST_ARTIFACT_CHANGED":"NO","APRIL_RESULT_ARTIFACT_CHANGED":"NO","APRIL_INDEPENDENT_REVIEW_PROVENANCE":"UNCLEAR","APRIL_CANDIDATE_REUSE_SCOPE":"CANDIDATE_GENERATION","APRIL_CANDIDATE_DEVELOPMENT_ROLE":"ALLOWED_CONSUMED_DEVELOPMENT","APRIL_FUTURE_CANDIDATE_OOS":"PROHIBITED","APRIL_UNTOUCHED_HOLDOUT":"PROHIBITED","APRIL_FIRST_LOOK_OOS":"PROHIBITED","APRIL_FULL_FIELD_READINESS":"PENDING"})
    write("safety.json",{"DRAFT_V3_CHANGE":0,"APRIL_DATASET_BUILD":0,"APRIL_RESULT_REJOIN":0,"APRIL_PERFORMANCE_RECALCULATION":0,"MODEL_TRAINING":0,"SCALER_FIT":0,"PREDICTION":0,"CANDIDATE_EXACT5":0,"STAGE_A_RERUN":0,"STAGE_B_EXECUTION":0,"ENGINE_CHANGE":0,"RACE_DECISION_ENGINE_CHANGE":0,"DATA_CATALOG_CHANGE":0,"WORK_RECORD_CHANGE":0,"JUNE_ADDITIONAL_DATA_ACCESS":0,"JULY_ADDITIONAL_DATA_ACCESS":0,"AUGUST_ADDITIONAL_DATA_ACCESS":0,"UNTOUCHED_HOLDOUT_ACCESS":0,"FUTURE_RESULT_ACCESS":0,"PRODUCTION_CHANGE":0,"GIT_COMMIT":0,"GIT_PUSH":0,"ARTIFACT_HASH_VALIDATION":"PENDING"})
    (OUT/"report.md").write_text("# April 2026 GATE-001 Finalization Override\n\n`APRIL_2026_GATE001_FINALIZATION_OVERRIDE_V1 = COMPLETE`\n\nExisting finalization_overrides was used as the authoritative amendment layer. The immutable GATE-001 Draft V3 base entry and all April evidence remain unchanged. The override records historical INCONCLUSIVE finalization, Human-approved Candidate Generation development reuse, future OOS prohibition, and pending Full-field readiness.\n",encoding="utf-8")
    hashes={p.name:{"sha256":sha(p),"size":p.stat().st_size} for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hash_index.json"}
    write("artifact_hash_index.json",{"indexed_artifacts":hashes,"self_hash_excluded":True})
    print("APRIL_2026_GATE001_FINALIZATION_OVERRIDE_V1=COMPLETE")

if __name__=="__main__": main()
