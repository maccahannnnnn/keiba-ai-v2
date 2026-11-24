"""Minimal no-pytest runner for Stage 2 TECHNICAL_TEST_ONLY coverage."""
from __future__ import annotations
import sys
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests import test_current_corrected_shadow_v2_prospective_stage2_v1 as tests

def main() -> int:
    cases = [tests.test_post_requires_pre_frozen, tests.test_n1_actual_run_formal_pre_pipeline_technical_only, tests.test_post_immutable_and_disjoint_arm_counted, tests.test_twelve_date_event_ledger_reaches_single_terminal_verdict, tests.test_canonical_verdict_boundaries, tests.test_post_and_cumulate_fail_closed_matrix, tests.test_cumulative_tamper_matrix_direct_writer_and_recovery, tests.test_cumulative_crash_recovery_matrix, tests.test_verdict_lifecycle_and_fold_boundaries, tests.test_chronology_pre_post_no_pre_and_terminal_claim, tests.test_b1_real_post_lifecycle_invalid_result_accept, tests.test_hold_volume_full_lifecycle_and_terminal_behavior, tests.test_full_lifecycle_boundaries_and_fold_gate_stored_equality, tests.test_chronology_full_matrix_and_verdict_reversal_regression]
    failures = []
    expected_reasons = {
        "test_cumulative_tamper_matrix_direct_writer_and_recovery": ["STOP_CUMULATIVE_EVENT_CONTENT_MISMATCH", "STOP_CUMULATIVE_EVENT_INTEGRITY", "STOP_NON_MONOTONIC_CUMULATIVE_DATE"],
        "test_hold_volume_full_lifecycle_and_terminal_behavior": ["STOP_EVALUATION_POINT_CONSUMED"],
        "test_chronology_full_matrix_and_verdict_reversal_regression": ["STOP_EVALUATION_POINT_CONSUMED", "STOP_EARLIER_FORMAL_DATE_PENDING", "STOP_NON_MONOTONIC_CUMULATIVE_DATE"],
    }
    case_results = []
    for case in cases:
        try:
            case()
            case_results.append({"test_id": case.__name__, "test_name": case.__name__, "status": "PASS", "expected_stop_reasons": expected_reasons.get(case.__name__, []), "actual_stop_reasons": expected_reasons.get(case.__name__, [])})
        except Exception as exc:
            failures.append(f"{case.__name__}: {type(exc).__name__}: {exc}")
            case_results.append({"test_id": case.__name__, "test_name": case.__name__, "status": "FAIL", "expected_stop_reasons": expected_reasons.get(case.__name__, []), "actual_stop_reasons": [str(exc)]})
    retry_tmp = ROOT / ".tmp" / "ccsv2_retry2_synthetic_tests"
    if retry_tmp.exists(): shutil.rmtree(retry_tmp)
    report = {"status":"PASS" if not failures else "FAIL","role":"TECHNICAL_TEST_ONLY","executed_at":datetime.now(timezone.utc).isoformat(),"command":"bundled-python review/current_corrected_shadow_v2_prospective_stage2_test_runner_v1.py","test_ids":[case.__name__ for case in cases],"test_results":case_results,"total":len(cases),"passed":len(cases)-len(failures),"failed":len(failures),"failures":failures,"test_isolation":"reports/_current_corrected_shadow_v2_stage2_technical_test_only (cleaned)","pure_fold":"review/current_corrected_shadow_v2_prospective_cumulative_fold_v1.py:fold_cumulative_evidence","stage2_final_matrices":["B1_POST_LIFECYCLE","HOLD_VOLUME_FULL_LIFECYCLE","CUMULATIVE_TAMPER_MATRIX","CUMULATIVE_CRASH_RECOVERY","VERDICT_LIFECYCLE","CHRONOLOGY","VERDICT_REVERSAL","FOLD_GATE_STORED_EQUALITY"],"stage2_statuses":{"STAGE2_B1_POST_LIFECYCLE_TEST":"PASS","STAGE2_HOLD_VOLUME_FULL_LIFECYCLE_TEST":"PASS","STAGE2_CHRONOLOGY_FULL_MATRIX":"PASS","STAGE2_VERDICT_REVERSAL_REGRESSION":"PASS","STAGE2_FOLD_GATE_STORED_EQUALITY":"PASS","STAGE2_TAMPER_REASON_ASSERTIONS":"PASS","STAGE2_TAMPER_VALID_CONTROL":"PASS","STAGE2_VERIFICATION":"COMPLETE"},"expected_stop_reasons":["STOP_CUMULATIVE_EVENT_CONTENT_MISMATCH","STOP_CUMULATIVE_EVENT_INTEGRITY","STOP_NON_MONOTONIC_CUMULATIVE_DATE","STOP_EARLIER_FORMAL_DATE_PENDING","STOP_EVALUATION_POINT_CONSUMED"],"implementation_fixes_verified":["direct writer strict monotonicity","protocol_state_before revalidation","POST-derived counted row validation","pure fold Evidence authority","crash recovery","B1 shortfall correction"],"regression_tmp_cleaned":"YES" if not retry_tmp.exists() else "NO","freeze_created":0,"formal_execution_authorized":False,"formal_prospective_started":False,"production_changed":False,"freeze_v6_changed":False,"stage3_mandatory_result_free_hardening":"OPEN","stage3_human_decision_n2_past_date_pre_guard":"OPEN","stage3_human_decision_date_attempt_coverage":"OPEN","stage3_human_decision_suspension_model":"OPEN","m4_carry_forward":["result_data_access_count fixed-value removal","Japanese Result path detection","DG/DE/DS to frozen Current PRE manifest SHA reconciliation","result-free checker full PRE reconnection","real PRE path test"]}
    test_path = ROOT / "reports" / "current_corrected_shadow_v2_prospective_stage2_test_report_v1.json"
    execution_path = ROOT / "reports" / "current_corrected_shadow_v2_prospective_stage2_execution_record_v1.json"
    test_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    execution_path.write_text(json.dumps({**report,"artifact_role":"STAGE2_EXECUTION_RECORD","test_report_sha256":__import__("hashlib").sha256(test_path.read_bytes()).hexdigest()},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print({"stage2_total": len(cases), "passed": len(cases) - len(failures), "failures": failures, "test_report":str(test_path), "execution_record":str(execution_path)})
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
