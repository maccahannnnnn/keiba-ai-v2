"""Read-only validator for Candidate Registry Schema v1 audit metadata."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "reports" / "candidate_registry_v1.json"

AUDIT_FIELDS = (
    "hold_subject_type",
    "hold_reason",
    "reopen_condition",
    "reopen_condition_reachable_with_current_evidence",
    "hold_exit_classification",
    "resolved_by",
    "resolution_evidence",
    "classification_date",
    "classified_by",
)
HOLD_SUBJECT_TYPES = {"METHOD", "THEME_HYPOTHESIS", "UNDETERMINED"}
HOLD_REASONS = {
    "EVIDENCE_QUANTITY",
    "MEASUREMENT_METHOD",
    "EVIDENCE_INTEGRITY",
    "DIRECTION_CONFLICT",
    "OTHER",
}
REACHABILITY = {"YES", "NO", "UNDETERMINED"}
EXIT_CLASSIFICATIONS = {
    "REOPEN_CONDITION_DEFINED",
    "METHOD_LINE_ENDED",
    "AWAITING_NEW_EVIDENCE",
    "RESOLVED_BY_SUCCESSOR",
    "UNDETERMINED",
}
RECORDED_EXIT_CLASSIFICATIONS = EXIT_CLASSIFICATIONS - {"UNDETERMINED"}
PRESERVED_TARGET_STATE = {
    "REG-001": ("HOLD", "PLACEBO_VARIANCE_HOLD"),
    "REG-004": ("HOLD", "INCONCLUSIVE"),
    "REG-006": ("CLOSED", "PLACEBO_VARIANCE_HOLD"),
    "REG-010": ("SUPERSEDED_BY_REG-011", "HOLD"),
    "REG-013": ("HOLD", "CLASSIFICATION_SEPARATION_HOLD"),
    "REG-009": ("SHADOW_IMPLEMENTED_OOS_VALIDATION_PENDING", "UNCONVERGED_HOLD"),
    "REG-012": ("PAUSE", "HOLD"),
}
EXPECTED_PRIORITY4_LINE_STATES = {
    "CONSENSUS": "CLOSED",
    "ABSOLUTE": "CLOSED",
    "RISK_PRIMARY": "CLOSED",
    "UNCONVERGED": "HOLD",
}
EXPECTED_LINE_RULES = {
    "new_real_race_count_min": 5,
    "latest_only": True,
    "past_mixing_prohibited": True,
    "fn_improvement_gt_fp_increase": True,
    "roi_min": 0,
}
EXPECTED_GUARD_RULES = {
    "fn_improvement_min": 1,
    "roi_min": 0,
    "fp_increase_max": 1,
    "explainability_min": "HIGH",
    "rollback_ease_required": "HIGH",
    "feature_flag_fit_required": "HIGH",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_unconverged_alignment(entries_by_id: dict, root: Path, errors: list[str]) -> None:
    for registry_id in ("REG-009", "REG-012"):
        entry = entries_by_id.get(registry_id)
        if entry is None:
            errors.append(f"{registry_id}:MISSING_FOR_UNCONVERGED_ALIGNMENT")
            continue
        if "STEP 1" not in (entry.get("reopen_condition") or "") or "STEP 2" not in entry["reopen_condition"]:
            errors.append(f"{registry_id}:TWO_STAGE_REOPEN_CONDITION_MISSING")
        audit = entry.get("latest_recheck", {}).get("criteria_alignment_v1")
        if not isinstance(audit, dict):
            errors.append(f"{registry_id}:CRITERIA_ALIGNMENT_MISSING")
            continue
        if audit.get("relationship") != "SAME_UNCONVERGED_LINE_DIFFERENT_GRANULARITY":
            errors.append(f"{registry_id}:INVALID_UNCONVERGED_RELATIONSHIP")
        if audit.get("priority4_line_states") != EXPECTED_PRIORITY4_LINE_STATES:
            errors.append(f"{registry_id}:PRIORITY4_LINE_STATE_MISMATCH")
        if audit.get("reg_009_guard") != "ADJUSTED_GAP_GUARD" or audit.get("reg_012_guard") != "TOP_CLUSTER_DUAL_SEPARATION":
            errors.append(f"{registry_id}:GUARD_IDENTITY_MISMATCH")
        if audit.get("reg_009_guard") == audit.get("reg_012_guard") or audit.get("guard_identity_distinct") is not True:
            errors.append(f"{registry_id}:GUARDS_NOT_DISTINCT")
        level_1 = audit.get("level_1", {})
        level_2 = audit.get("level_2", {})
        if level_1.get("rules") != EXPECTED_LINE_RULES:
            errors.append(f"{registry_id}:LINE_RULES_CHANGED")
        if level_1.get("result") != "REOPEN_CONDITION_MET":
            errors.append(f"{registry_id}:LINE_REOPEN_RESULT_MISMATCH")
        if level_2.get("rules") != EXPECTED_GUARD_RULES:
            errors.append(f"{registry_id}:GUARD_GO_RULES_CHANGED")
        if level_2.get("guard") != "ADJUSTED_GAP_GUARD":
            errors.append(f"{registry_id}:LEVEL_2_GUARD_MISMATCH")
        if level_2.get("observed", {}).get("fp_increase") != 2:
            errors.append(f"{registry_id}:OBSERVED_FP_INCREASE_MISMATCH")
        if level_2.get("condition_results", {}).get("fp_increase_max") != "FAIL":
            errors.append(f"{registry_id}:FP_LIMIT_FAILURE_NOT_RECORDED")
        if level_2.get("result") != "SHADOW_GO_CONDITION_NOT_MET":
            errors.append(f"{registry_id}:GUARD_GO_RESULT_MISMATCH")
        blockers = audit.get("blocker_audit", {})
        if blockers != {"ROI_BELOW_ZERO": "RESOLVED", "FP_INCREASE_ABOVE_1": "REMAINS"}:
            errors.append(f"{registry_id}:BLOCKER_AUDIT_MISMATCH")
        if audit.get("level_1_does_not_imply_level_2") is not True:
            errors.append(f"{registry_id}:LEVEL_SEPARATION_MISSING")
        if audit.get("standalone_reg_009_shadow_progression_authorized") is not False:
            errors.append(f"{registry_id}:STANDALONE_REG_009_PROGRESSION_NOT_BLOCKED")
        if not audit.get("next_latest_cohort_rule"):
            errors.append(f"{registry_id}:NEXT_COHORT_TWO_STAGE_RULE_MISSING")
        for level_name, level in (("LEVEL_1", level_1), ("LEVEL_2", level_2)):
            source_file = level.get("source_file")
            source_sha = level.get("source_sha256")
            path = (root / source_file).resolve() if source_file else None
            if path is None or not path.is_file():
                errors.append(f"{registry_id}:{level_name}_SOURCE_MISSING")
            elif _sha256(path) != source_sha:
                errors.append(f"{registry_id}:{level_name}_SOURCE_SHA_MISMATCH")
    reg_009 = entries_by_id.get("REG-009", {})
    reg_012 = entries_by_id.get("REG-012", {})
    if "REG-012" not in reg_009.get("lineage", []) and "REG-012" not in reg_009.get("overlap", []):
        errors.append("REG-009:REG-012_RELATION_MISSING")
    if "REG-009" not in reg_012.get("lineage", []) and "REG-009" not in reg_012.get("overlap", []):
        errors.append("REG-012:REG-009_RELATION_MISSING")
    preserved = reg_012.get("latest_recheck", {}).get("criteria_alignment_v1", {}).get("entry_guard_recheck_preserved", {})
    if preserved.get("guard") != "TOP_CLUSTER_DUAL_SEPARATION" or preserved.get("result") != "REOPEN_CONDITION_NOT_MET":
        errors.append("REG-012:ENTRY_GUARD_RECHECK_NOT_PRESERVED")


def validate_registry(data: dict, root: Path | str = ROOT) -> dict:
    root = Path(root).resolve()
    errors: list[str] = []
    entries = data.get("entries")
    if not isinstance(entries, list):
        return {"status": "FAIL", "errors": ["ENTRIES_NOT_LIST"]}
    ids = {entry.get("registry_id") for entry in entries}
    entries_by_id = {entry.get("registry_id"): entry for entry in entries}
    if None in ids or len(ids) != len(entries):
        errors.append("REGISTRY_ID_MISSING_OR_DUPLICATE")
    if data.get("entry_count") != len(entries):
        errors.append("ENTRY_COUNT_MISMATCH")
    if "EVIDENCE_COMPLETENESS" in json.dumps(data, ensure_ascii=False):
        errors.append("FORBIDDEN_HOLD_REASON:EVIDENCE_COMPLETENESS")

    for entry in entries:
        registry_id = entry.get("registry_id", "UNKNOWN")
        for field in AUDIT_FIELDS:
            if field not in entry:
                errors.append(f"{registry_id}:MISSING_AUDIT_FIELD:{field}")
        subject = entry.get("hold_subject_type")
        reason = entry.get("hold_reason")
        reachable = entry.get("reopen_condition_reachable_with_current_evidence")
        exit_class = entry.get("hold_exit_classification")
        if subject is not None and subject not in HOLD_SUBJECT_TYPES:
            errors.append(f"{registry_id}:INVALID_HOLD_SUBJECT_TYPE:{subject}")
        if reason is not None and reason not in HOLD_REASONS:
            errors.append(f"{registry_id}:INVALID_HOLD_REASON:{reason}")
        if reachable is not None and reachable not in REACHABILITY:
            errors.append(f"{registry_id}:INVALID_REACHABILITY:{reachable}")
        if exit_class is not None and exit_class not in EXIT_CLASSIFICATIONS:
            errors.append(f"{registry_id}:INVALID_EXIT_CLASSIFICATION:{exit_class}")
        if exit_class in RECORDED_EXIT_CLASSIFICATIONS and entry.get("hold_without_exit") is not False:
            errors.append(f"{registry_id}:RECORDED_EXIT_REQUIRES_FALSE_FLAG")
        if exit_class == "UNDETERMINED" and entry.get("hold_without_exit") is not True:
            errors.append(f"{registry_id}:UNDETERMINED_REQUIRES_TRUE_FLAG")
        if entry.get("hold_without_exit") is True and exit_class != "UNDETERMINED":
            errors.append(f"{registry_id}:TRUE_FLAG_REQUIRES_UNDETERMINED_EXIT")
        if exit_class == "RESOLVED_BY_SUCCESSOR":
            resolved_by = entry.get("resolved_by")
            if not resolved_by:
                errors.append(f"{registry_id}:RESOLVED_BY_SUCCESSOR_REQUIRES_ID")
            elif resolved_by not in ids:
                errors.append(f"{registry_id}:RESOLVED_BY_UNKNOWN_ID:{resolved_by}")
        elif entry.get("resolved_by") is not None:
            errors.append(f"{registry_id}:RESOLVED_BY_REQUIRES_SUCCESSOR_CLASSIFICATION")
        if exit_class == "AWAITING_NEW_EVIDENCE" and not entry.get("reopen_condition"):
            errors.append(f"{registry_id}:AWAITING_NEW_EVIDENCE_REQUIRES_CONDITION")

        evidence = entry.get("resolution_evidence")
        if evidence is not None:
            if not isinstance(evidence, dict) or not evidence.get("source_file") or not evidence.get("source_sha256"):
                errors.append(f"{registry_id}:INVALID_RESOLUTION_EVIDENCE")
            else:
                path = (root / evidence["source_file"]).resolve()
                try:
                    path.relative_to(root)
                except ValueError:
                    errors.append(f"{registry_id}:EVIDENCE_OUTSIDE_ROOT")
                else:
                    if not path.is_file():
                        errors.append(f"{registry_id}:EVIDENCE_MISSING:{evidence['source_file']}")
                    elif _sha256(path) != evidence["source_sha256"]:
                        errors.append(f"{registry_id}:EVIDENCE_SHA_MISMATCH:{evidence['source_file']}")

        if registry_id in PRESERVED_TARGET_STATE:
            expected_status, expected_decision = PRESERVED_TARGET_STATE[registry_id]
            if (entry.get("status"), entry.get("decision")) != (expected_status, expected_decision):
                errors.append(f"{registry_id}:HISTORICAL_STATE_CHANGED")

    _validate_unconverged_alignment(entries_by_id, root, errors)

    actual_hold_without_exit = sum(entry.get("hold_without_exit") is True for entry in entries)
    if data.get("hold_without_exit_count") != actual_hold_without_exit:
        errors.append("HOLD_WITHOUT_EXIT_COUNT_MISMATCH")
    return {
        "status": "PASS" if not errors else "FAIL",
        "entry_count": len(entries),
        "hold_without_exit_count": actual_hold_without_exit,
        "validated_audit_field_count": len(entries) * len(AUDIT_FIELDS),
        "unconverged_criteria_alignment": "PASS" if not any("REG-009" in error or "REG-012" in error or "LEVEL_" in error or "GUARD_" in error or "PRIORITY4" in error or "BLOCKER_" in error for error in errors) else "FAIL",
        "errors": errors,
    }


def main(path: str | None = None) -> int:
    registry_path = Path(path).resolve() if path else DEFAULT_REGISTRY
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    result = validate_registry(data, root=ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
