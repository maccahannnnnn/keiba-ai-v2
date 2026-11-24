import copy
import json
import unittest
from pathlib import Path

from review.candidate_registry_validator import ROOT, validate_registry


class CandidateRegistryValidatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads((ROOT / "reports" / "candidate_registry_v1.json").read_text(encoding="utf-8"))

    def mutated(self):
        return copy.deepcopy(self.registry)

    def test_current_registry_passes(self):
        self.assertEqual(validate_registry(self.registry)["status"], "PASS")

    def test_invalid_enum_fails(self):
        data = self.mutated(); data["entries"][0]["hold_reason"] = "NOT_FORMAL"
        self.assertEqual(validate_registry(data)["status"], "FAIL")

    def test_evidence_completeness_is_forbidden(self):
        data = self.mutated(); data["entries"][0]["hold_reason"] = "EVIDENCE_COMPLETENESS"
        self.assertTrue(any("FORBIDDEN_HOLD_REASON" in error for error in validate_registry(data)["errors"]))

    def test_resolved_successor_requires_existing_id(self):
        data = self.mutated(); entry = next(e for e in data["entries"] if e["registry_id"] == "REG-010"); entry["resolved_by"] = "REG-999"
        self.assertTrue(any("RESOLVED_BY_UNKNOWN_ID" in error for error in validate_registry(data)["errors"]))

    def test_resolution_evidence_sha_is_checked(self):
        data = self.mutated(); data["entries"][0]["resolution_evidence"]["source_sha256"] = "0" * 64
        self.assertTrue(any("EVIDENCE_SHA_MISMATCH" in error for error in validate_registry(data)["errors"]))

    def test_hold_without_exit_mapping_is_checked(self):
        data = self.mutated(); data["entries"][0]["hold_without_exit"] = True; data["hold_without_exit_count"] = 1
        self.assertTrue(any("RECORDED_EXIT_REQUIRES_FALSE_FLAG" in error for error in validate_registry(data)["errors"]))

    def test_awaiting_new_evidence_requires_condition(self):
        data = self.mutated(); data["entries"][0]["reopen_condition"] = ""
        self.assertTrue(any("AWAITING_NEW_EVIDENCE_REQUIRES_CONDITION" in error for error in validate_registry(data)["errors"]))

    def test_target_decision_and_status_are_preserved(self):
        data = self.mutated(); data["entries"][0]["decision"] = "REJECT"
        self.assertTrue(any("HISTORICAL_STATE_CHANGED" in error for error in validate_registry(data)["errors"]))

    def test_non_target_null_audit_fields_are_valid(self):
        entry = next(e for e in self.registry["entries"] if e["registry_id"] == "REG-002")
        self.assertIsNone(entry["hold_subject_type"])
        self.assertEqual(validate_registry(self.registry)["status"], "PASS")

    def test_line_reopen_does_not_substitute_for_guard_go(self):
        data = self.mutated(); entry = next(e for e in data["entries"] if e["registry_id"] == "REG-009")
        entry["latest_recheck"]["criteria_alignment_v1"]["level_2"]["result"] = "PASS"
        self.assertTrue(any("GUARD_GO_RESULT_MISMATCH" in error for error in validate_registry(data)["errors"]))

    def test_frozen_fp_limit_cannot_change(self):
        data = self.mutated(); entry = next(e for e in data["entries"] if e["registry_id"] == "REG-009")
        entry["latest_recheck"]["criteria_alignment_v1"]["level_2"]["rules"]["fp_increase_max"] = 2
        self.assertTrue(any("GUARD_GO_RULES_CHANGED" in error for error in validate_registry(data)["errors"]))

    def test_adjusted_gap_and_top_cluster_are_distinct(self):
        data = self.mutated(); entry = next(e for e in data["entries"] if e["registry_id"] == "REG-012")
        entry["latest_recheck"]["criteria_alignment_v1"]["reg_012_guard"] = "ADJUSTED_GAP_GUARD"
        self.assertTrue(any("GUARD" in error for error in validate_registry(data)["errors"]))

    def test_alignment_source_sha_is_checked(self):
        data = self.mutated(); entry = next(e for e in data["entries"] if e["registry_id"] == "REG-009")
        entry["latest_recheck"]["criteria_alignment_v1"]["level_2"]["source_sha256"] = "0" * 64
        self.assertTrue(any("LEVEL_2_SOURCE_SHA_MISMATCH" in error for error in validate_registry(data)["errors"]))

    def test_reg_009_and_reg_012_states_are_preserved(self):
        data = self.mutated(); entry = next(e for e in data["entries"] if e["registry_id"] == "REG-012"); entry["status"] = "GO"
        self.assertTrue(any("HISTORICAL_STATE_CHANGED" in error for error in validate_registry(data)["errors"]))

    def test_reg_009_oos_pending_status_is_formal(self):
        entry = next(e for e in self.registry["entries"] if e["registry_id"] == "REG-009")
        self.assertEqual(entry["status"], "SHADOW_IMPLEMENTED_OOS_VALIDATION_PENDING")
        self.assertEqual(entry["lifecycle_state"]["oos_validation"], "PENDING")
        self.assertEqual(entry["lifecycle_state"]["production"], "HOLD")

    def test_reg_009_not_evaluated_is_not_pass(self):
        entry = next(e for e in self.registry["entries"] if e["registry_id"] == "REG-009")
        policy = entry["oos_validation_policy"]["not_evaluated"]
        self.assertFalse(policy["not_evaluated_is_pass"])
        self.assertEqual(policy["guard_activation_race_count_zero"], "OOS_VALIDATION_NOT_EVALUATED")

    def test_reg_009_history_sequence_four_is_append_only_status_record(self):
        entry = next(e for e in self.registry["entries"] if e["registry_id"] == "REG-009")
        self.assertEqual([item["sequence"] for item in entry["recheck_history"]], [1, 2, 3, 4])
        self.assertEqual(entry["recheck_history"][-1]["prior_status"], "HOLD")
        self.assertEqual(entry["recheck_history"][-1]["production"], "HOLD")


if __name__ == "__main__":
    unittest.main()
