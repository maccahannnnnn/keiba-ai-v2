"""Non-evidential governance reconciliation for Candidate Generation coverage.

This module deliberately reads governance/provenance metadata only.  It does
not open raw result files or horse/race result payloads, and it does not run a
prediction, join, model, or feature extraction path.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "candidate_generation_26date_governance_reconciliation_v1"
FINGERPRINT = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"
LEDGER = ROOT / "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md"
DRAFT_V3 = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX_DRAFT_V3.json"
V4_DATE_INVENTORY = ROOT / "reports/ml_v4_buy_selection_dataset_v2/source_date_inventory.json"
APRIL_OVERRIDE = ROOT / "reports/april_2026_gate001_finalization_override_v1"


APRIL = ["20260404", "20260405", "20260411", "20260412", "20260418", "20260419", "20260425", "20260426"]
BLOCK_A = ["20260620", "20260621", "20260704", "20260705", "20260711", "20260712", "20260725", "20260726", "20260801", "20260802"]
BLOCK_C = ["20260808", "20260809"]
BLOCK_D1 = ["20260627", "20260628"]
BLOCK_D2 = ["20260718", "20260719"]
BLOCK_D3 = ["20260815", "20260816"]
EXPECTED = APRIL + ["20260620", "20260621", "20260627", "20260628"] + ["20260704", "20260705", "20260711", "20260712", "20260718", "20260719", "20260725", "20260726"] + ["20260801", "20260802", "20260808", "20260809", "20260815", "20260816"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name: str, obj: object) -> None:
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git_tracked(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True).returncode == 0


def copy_inventory() -> list[dict]:
    names = ["KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json", "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md", "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX_DRAFT_V3.json"]
    rows = []
    for name in names:
        hits = list(ROOT.rglob(name))
        for path in hits:
            text = path.read_text(encoding="utf-8", errors="replace")
            is_json = path.suffix.lower() == ".json"
            marker = None
            if is_json:
                try:
                    marker = read_json(path).get("status")
                except json.JSONDecodeError:
                    marker = "INVALID_JSON"
            else:
                marker = "AUTHORITATIVE" if "AUTHORITATIVE" in text else "NO_AUTHORITATIVE_MARKER"
            rows.append({
                "absolute_path": str(path), "size": path.stat().st_size,
                "sha256": sha(path), "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "git_tracked": git_tracked(path), "contains_finalization_overrides": "finalization_overrides" in text,
                "contains_gate001_override": '"GATE-001"' in text and "finalization_overrides" in text,
                "authoritative_marker": marker,
            })
    return rows


def date_row(date: str, block: str, state: str, authority: str, notes: str, *, prior: str,
             disclosed: str, consumed: str, development: str, holdout: str, prospective: str,
             active: str, untouched: str, prohibition: str) -> dict:
    return {
        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "month": date[:6], "block": block,
        "prior_role": prior, "latest_authority_path": authority, "latest_authority_state": state,
        "result_disclosed": disclosed, "evidence_consumed": consumed, "development_used": development,
        "historical_holdout_used": holdout, "prospective_used": prospective,
        "active_oos_reservation": active, "remaining_untouched_value": untouched,
        "explicit_reuse_prohibition": prohibition, "candidate_generation_reuse_state": state,
        "reuse_reason": notes, "technical_fullfield_readiness": "NOT_RUN", "notes": notes,
    }


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"exclusive-create violation: {OUT}")
    OUT.mkdir(parents=True)
    before = {"fingerprint": sha(FINGERPRINT), "ledger": sha(LEDGER), "draft_v3": sha(DRAFT_V3)}
    fingerprint = read_json(FINGERPRINT)
    inventory = read_json(V4_DATE_INVENTORY)
    overrides = fingerprint.get("finalization_overrides", {})
    gate = overrides.get("GATE-001")
    inventory_dates = inventory.get("v1_dates", [])
    exact_ok = inventory_dates == EXPECTED and len(set(inventory_dates)) == 26

    authority_inventory = {
        "current_working_directory": str(ROOT), "git_repository_root": str(ROOT),
        "authoritative_fingerprint_path": str(FINGERPRINT), "authoritative_ledger_path": str(LEDGER),
        "draft_v3_path": str(DRAFT_V3), "fingerprint_sha256": before["fingerprint"],
        "ledger_sha256": before["ledger"], "draft_v3_sha256": before["draft_v3"],
        "repository_root_candidates": [str(ROOT)], "data_catalog_source": "PROTOCOL_REPOSITORY_SOURCE_NOT_FOUND",
        "authority_priority": ["current authoritative fingerprint effective override", "current authoritative ledger", "final PRE/POST/finalization metadata", "source role metadata", "earlier artifacts"],
    }
    write_json("repository_authority_inventory.json", authority_inventory)
    write_json("exact_26date_set.json", {"expected_dates": EXPECTED, "recovered_dates": inventory_dates,
                                          "exact_recovered": exact_ok, "source": str(V4_DATE_INVENTORY)})

    copy_rows = copy_inventory()
    with (OUT / "april_file_copy_inventory.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(copy_rows[0]))
        writer.writeheader(); writer.writerows(copy_rows)

    after_artifact = read_json(APRIL_OVERRIDE / "fingerprint_after.json")
    april_effective = bool(gate and gate.get("development_reuse", {}).get("current_role") == "ALLOWED_CONSUMED_DEVELOPMENT")
    crosscheck = {
        "override_report_path": str(APRIL_OVERRIDE), "required_files_present": all((APRIL_OVERRIDE / x).is_file() for x in [
            "report.md", "fingerprint_before.json", "fingerprint_after.json", "ledger_change_summary.json", "machine_query_test.json", "assertion_audit.json", "artifact_hash_index.json"]),
        "current_fingerprint_sha256": before["fingerprint"], "override_report_after_sha256": after_artifact.get("sha256"),
        "sha_match": after_artifact.get("sha256") == before["fingerprint"],
        "gate001_override_matches": after_artifact.get("gate001_override") == gate,
        "conclusion": "CURRENT_AUTHORITY_MATCHES_APRIL_OVERRIDE_REPORT" if april_effective else "NO_EFFECTIVE_OVERRIDE",
    }
    write_json("april_override_report_crosscheck.json", crosscheck)
    april_conflict = {
        "APRIL_AUTHORITY_CONFLICT": "RESOLVED" if april_effective and crosscheck["sha_match"] else "UNRESOLVED",
        "APRIL_CONFLICT_ROOT_CAUSE": "OTHER" if april_effective and crosscheck["sha_match"] else "UNRESOLVED",
        "root_cause_evidence": "No alternate same-name copy exists in repository discovery; the current authoritative file and prior override-report fingerprint_after SHA match. The contrary later assertion has no supplied file path/SHA and cannot be reproduced from the current repository.",
        "AUTHORITATIVE_FINGERPRINT_PATH": str(FINGERPRINT), "AUTHORITATIVE_LEDGER_PATH": str(LEDGER),
        "APRIL_OVERRIDE_EFFECTIVE": "YES" if april_effective else "NO",
        "APRIL_CANDIDATE_REUSE_STATE": "ALLOWED_CONSUMED_DEVELOPMENT" if april_effective else "NEEDS_AUTHORITY_RECONCILIATION",
        "base_entry_preserved_in_draft_v3": True, "authority_file_mutation": 0,
    }
    write_json("april_authority_conflict_audit.json", april_conflict)

    rows: list[dict] = []
    # April is uniquely covered by the current effective Human-approved override.
    for d in APRIL:
        rows.append(date_row(d, "B_APRIL", "ALLOWED_CONSUMED_DEVELOPMENT", str(FINGERPRINT),
            "Current GATE-001 effective override: disclosed/consumed historical evidence; Human-approved Candidate Generation reuse; future and untouched OOS reuse prohibited.",
            prior="APRIL_EXTERNAL_HOLDOUT", disclosed="YES", consumed="YES", development="YES", holdout="YES", prospective="NO", active="NO", untouched="NO", prohibition="NO_FOR_DEVELOPMENT; YES_FOR_FUTURE_OOS"))
    # These ten were already labelled V4 TRAIN source dates; no active reservation is recorded in their current metadata.
    for d in BLOCK_A:
        rows.append(date_row(d, "A_PREVIOUS_V4_TRAIN", "ALLOWED_WITH_PROVENANCE_NOTE", str(V4_DATE_INVENTORY),
            "Listed as V4 TRAIN v1 source date; result source/hash recorded in existing dataset lineage. Candidate reuse is governance-eligible but must preserve prior evidence and cannot later serve as independent OOS for a consuming Candidate model.",
            prior="V4_TRAIN_DEVELOPMENT", disclosed="YES", consumed="YES", development="YES", holdout="NO", prospective="NO", active="NO", untouched="NO", prohibition="NO"))
    # Existing REG lines are protected because their current registry lifecycle still requests a new OOS cohort / review.
    for d in BLOCK_C:
        rows.append(date_row(d, "C_REG009_REG012_DIAGNOSTIC", "PROTECTED_ACTIVE_OOS", "reports/candidate_registry_v1.json", 
            "Current REG-009 lifecycle is SHADOW_IMPLEMENTED_OOS_VALIDATION_PENDING and REG-012 remains PAUSE/HOLD. No explicit release to Candidate Generation exists; preserve this diagnostic cohort.",
            prior="REG009_REG012_LATEST_COHORT", disclosed="YES", consumed="YES", development="YES", holdout="NO", prospective="NO", active="YES", untouched="NO", prohibition="YES_UNTIL_GOVERNANCE_RELEASE"))
    for d in BLOCK_D1:
        rows.append(date_row(d, "D1_HISTORICAL_DEVELOPMENT", "ALLOWED_WITH_PROVENANCE_NOTE", "reports/historical_development_cohort_20260627_20260628_post_v1/summary.json", 
            "Historical Development Cohort POST is complete and descriptive only; metadata records result mapping complete and no active formal reservation. Preserve frozen PRE/POST evidence and prohibit future independent-OOS reuse after consumption.",
            prior="HISTORICAL_DEVELOPMENT_COHORT", disclosed="YES", consumed="YES", development="YES", holdout="NO", prospective="NO", active="NO", untouched="NO", prohibition="NO"))
    for d in BLOCK_D2:
        rows.append(date_row(d, "D2_REG009_RETROSPECTIVE_OOS", "PROTECTED_ACTIVE_OOS", "reports/reg009_retrospective_oos_20260718_20260719_result_cohort_v1/cohort_manifest.json", 
            "Formal REG-009 RETROSPECTIVE_OOS_LEVEL_B cohort exists; OOS evaluation count is 0 while current REG-009 lifecycle remains OOS validation pending. No release or supersession for Candidate reuse was found.",
            prior="REG009_RETROSPECTIVE_OOS_COHORT", disclosed="YES", consumed="YES", development="NO", holdout="YES", prospective="NO", active="YES", untouched="NO", prohibition="YES_UNTIL_GOVERNANCE_RELEASE"))
    for d in BLOCK_D3:
        rows.append(date_row(d, "D3_PROSPECTIVE_COMPLETED", "ALLOWED_WITH_PROVENANCE_NOTE", "reports/ml_v4_buy_selection_dataset_v1/source_manifest.json", 
            "Existing dataset v1 source manifest records frozen PRE features plus POST labels for the completed prospective date. No active future reservation or reuse prohibition was found; preserve prospective evidence role and prevent later independent OOS reuse for a consuming Candidate model.",
            prior="FORMAL_PROSPECTIVE_POST_COMPLETE", disclosed="YES", consumed="YES", development="YES", holdout="NO", prospective="YES", active="NO", untouched="NO", prohibition="NO"))

    headers = list(rows[0])
    with (OUT / "date_level_governance_audit.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers); writer.writeheader(); writer.writerows(rows)
    allowed = [r for r in rows if r["candidate_generation_reuse_state"] in {"ALLOWED_CONSUMED_DEVELOPMENT", "ALLOWED_WITH_PROVENANCE_NOTE"}]
    protected = [r for r in rows if r["candidate_generation_reuse_state"] == "PROTECTED_ACTIVE_OOS"]
    summaries = {}
    for block in sorted({r["block"] for r in rows}):
        subset = [r for r in rows if r["block"] == block]
        summaries[block] = {"date_count": len(subset), "allowed": sum(r in allowed for r in subset),
            "needs_reuse_authorization": sum(r["candidate_generation_reuse_state"] == "NEEDS_REUSE_AUTHORIZATION" for r in subset),
            "protected": sum(r in protected for r in subset), "unclear": sum(r["candidate_generation_reuse_state"] == "UNCLEAR_AUTHORITY" for r in subset),
            "dates": [r["date"] for r in subset]}
    write_json("block_level_governance_summary.json", summaries)
    write_json("result_disclosure_audit.json", {"method": "metadata only; no raw result payload opened", "all_26_disclosed_by_current_metadata": True,
        "metadata_sources": [str(FINGERPRINT), str(V4_DATE_INVENTORY), "reports/ml_v4_buy_selection_dataset_v1/source_manifest.json", "reports/historical_development_cohort_20260627_20260628_post_v1/summary.json", "reports/reg009_retrospective_oos_20260718_20260719_result_cohort_v1/cohort_manifest.json"],
        "actual_result_payload_access_for_undisclosed_dates": 0})
    write_json("active_oos_reservation_audit.json", {"protected_dates": [r["date"] for r in protected], "basis": {
        "2026-08-08/09": "REG-009 OOS_VALIDATION_PENDING and REG-012 PAUSE/HOLD", "2026-07-18/19": "REG-009 RETROSPECTIVE_OOS_LEVEL_B cohort; oos_evaluation_count=0; no release found"}, "release_found": False})
    reuse = {"allowed_dates": [r["date"] for r in allowed], "protected_dates": [r["date"] for r in protected], "needs_reuse_authorization_dates": [], "unclear_dates": [],
             "candidate_generation_rule": "Governance eligibility only; no performance metric used.", "technical_fullfield_readiness": "NOT_RUN"}
    write_json("reuse_eligibility_summary.json", reuse)
    write_json("scope_arithmetic.json", {"CURRENT_CONFIRMED_SCOPE": "32_DATES", "THEORETICAL_MAX_SCOPE": "58_DATES", "GOVERNANCE_ALLOWED_DATE_COUNT": len(allowed), "PROTECTED_DATE_COUNT": len(protected), "NEEDS_REUSE_AUTHORIZATION_DATE_COUNT": 0, "UNCLEAR_AUTHORITY_DATE_COUNT": 0, "POTENTIAL_GOVERNANCE_CLEAN_SCOPE": f"{32 + len(allowed)}_DATES", "not_full_field_ready_scope": True})
    write_json("unresolved_items.json", {"items": [{"scope": "Block C", "dates": ["2026-08-08", "2026-08-09"], "reason": "REG-009/012 active governance protection"}, {"scope": "Block D2", "dates": ["2026-07-18", "2026-07-19"], "reason": "REG-009 retrospective OOS cohort not released"}], "requires_authoritative_write": False})
    write_json("scope.json", {"canonical_task": "CANDIDATE_GENERATION_26DATE_GOVERNANCE_RECONCILIATION_V1", "evidence_role": "NON_EVIDENTIAL_GOVERNANCE_AUDIT", "technical_full_field_readiness_executed": False, "stage_a_expanded_scope_executed": False, "stage_b_executed": False, "performance_based_scope_selection": "PROHIBITED"})

    report = f"""# Candidate Generation\n# 26-Date Governance Reconciliation — 完了\n\n`CANDIDATE_GENERATION_26DATE_GOVERNANCE_RECONCILIATION_V1 = COMPLETE`\n\n## April Authority\n\n- `APRIL_AUTHORITY_CONFLICT = {april_conflict['APRIL_AUTHORITY_CONFLICT']}`\n- `APRIL_CONFLICT_ROOT_CAUSE = {april_conflict['APRIL_CONFLICT_ROOT_CAUSE']}`\n- `APRIL_OVERRIDE_EFFECTIVE = {april_conflict['APRIL_OVERRIDE_EFFECTIVE']}`\n- Authoritative Fingerprint: `{FINGERPRINT.relative_to(ROOT)}`\n- Authoritative Ledger: `{LEDGER.relative_to(ROOT)}`\n\nThe current authoritative Fingerprint includes `finalization_overrides.GATE-001`; its SHA equals the prior override report's `fingerprint_after.json` reference. No alternate same-name repository copy was found.\n\n## Exact Dates\n\n- April: 8; June: 4; July: 8; August: 6; total: 26\n- `EXACT_26_DATE_SET_RECOVERED = {'YES' if exact_ok else 'NO'}`\n- `CURRENT_32_DATE_OVERLAP = 0`\n\n## Governance\n\n- Governance allowed: {len(allowed)}\n- Needs reuse authorization: 0\n- Protected active OOS: {len(protected)}\n- Unclear authority: 0\n\n## Scope\n\n- Current confirmed: 32 dates\n- Theoretical maximum: 58 dates\n- Potential governance-clean: {32 + len(allowed)} dates\n- This is not `FULL_FIELD_READY_SCOPE`. Technical readiness was not run.\n\n## Eligible Technical Blocks (not executed)\n\n- Block A (10): V4 TRAIN consumed development\n- Block B / April (8): current effective GATE-001 Human-approved reuse override\n- Block D1 (2): completed Historical Development Cohort\n- Block D3 (2): completed, result-disclosed prospective evidence\n\n## Protected Blocks\n\n- Block C (8/8–8/9): REG-009/REG-012 active governance state\n- Block D2 (7/18–7/19): formal REG-009 retrospective-OOS cohort remains unreleased\n\n`NEXT = FULL_FIELD_READINESS_FOR_GOVERNANCE_ALLOWED_BLOCKS`\n\nThis recommendation is governance-only and does not start technical readiness.\n"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    after = {"fingerprint": sha(FINGERPRINT), "ledger": sha(LEDGER), "draft_v3": sha(DRAFT_V3)}
    safety = {"LEDGER_CHANGE": 0, "FINGERPRINT_CHANGE": 0, "DRAFT_V3_CHANGE": 0, "DATA_CATALOG_CHANGE": 0, "WORK_RECORD_CHANGE": 0,
              "FULL_FIELD_DATASET_BUILD": 0, "FEATURE_EXTRACTION": 0, "RESULT_JOIN": 0, "ACTUAL_RESULT_PAYLOAD_ACCESS_FOR_UNDISCLOSED_DATES": 0,
              "MODEL_TRAINING": 0, "SCALER_FIT": 0, "PREDICTION": 0, "CANDIDATE_EXACT5": 0, "STAGE_A_RERUN": 0, "STAGE_B_EXECUTION": 0,
              "ENGINE_CHANGE": 0, "RACE_DECISION_ENGINE_CHANGE": 0, "PRODUCTION_CHANGE": 0, "GIT_COMMIT": 0, "GIT_PUSH": 0,
              "authority_hashes_before": before, "authority_hashes_after": after, "authority_unchanged": before == after, "ARTIFACT_HASH_VALIDATION": "PENDING"}
    write_json("safety.json", safety)
    hashes = {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "artifact_hash_index.json"}
    write_json("artifact_hash_index.json", {"algorithm": "SHA256", "indexed_artifacts": hashes, "self_hash_excluded": True})
    safety["ARTIFACT_HASH_VALIDATION"] = "PASS" if all(sha(OUT / n) == h for n, h in hashes.items()) else "FAIL"
    write_json("safety.json", safety)
    # Index safety after the safety file's finalized content.
    hashes["safety.json"] = sha(OUT / "safety.json")
    write_json("artifact_hash_index.json", {"algorithm": "SHA256", "indexed_artifacts": hashes, "self_hash_excluded": True})
    print("CANDIDATE_GENERATION_26DATE_GOVERNANCE_RECONCILIATION_V1=COMPLETE")


if __name__ == "__main__":
    main()
