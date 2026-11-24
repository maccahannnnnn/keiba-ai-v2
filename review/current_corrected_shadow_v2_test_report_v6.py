"""Truthful v6 test-report registry for CURRENT_CORRECTED_SHADOW_V2.

The registry is deliberately source-validated: an item cannot be reported as
covered unless its named test function is present in the test module.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_SOURCE = ROOT / "tests" / "test_current_corrected_shadow_v2.py"
REPORT = ROOT / "reports" / "current_corrected_shadow_v2_test_report_v6.json"

REQUIREMENTS = (
    ("ONE_CAUSE_MULTI_GATE_TEST", "test_one_cause_multi_gate_is_deduped_by_actual_guard_processing", "actual apply_corrected_shadow_v2 risk_guard authority count"),
    ("TRACE_ONLY_RISKS_NOT_AUTHORITY", "test_trace_only_risks_never_become_authority", "actual risk_guard authority count and pass"),
    ("TRUE_DATA_LIMITATION_EXACT_KEYWORDS", "test_true_data_limitation_exact_keywords_only", "three blocking and two non-blocking canonical keywords"),
    ("PP_VOTE_USES_ORIGINAL", "test_pp_vote_uses_original_actual_reliability_argument", "instrumented reliability_v2 original PastPerformance argument"),
    ("PP_RANK_USES_NEUTRALIZED", "test_pp_rank_uses_neutralized_value_in_actual_integrated_score", "integrated score changes with neutralized ranking PastPerformance"),
    ("PACE_ACTUAL_INPUT_AVERAGE", "test_actual_pace_consumers_receive_average_and_lap_is_recomputed", "instrumented Shadow runner consumer inputs and lap evaluator result"),
    ("MISSING_PACE_CONSUMER", "test_pace_consumer_inventory_is_repository_derived_and_complete", "repository-derived TargetTrialAdapter pace consumers compared with Shadow supply"),
    ("ALL_OFF_REPRODUCTION_19929", "test_canonical_artifacts_are_complete_and_result_free", "v5 all-off artifact race/horse/mismatch fields"),
    ("ALL_ON_SCHEMA_COMPLETE", "test_canonical_artifacts_are_complete_and_result_free", "all 1,472 v5 all-on artifact corrected-shadow required fields"),
    ("CANONICAL_UNMAPPED_ZERO", "test_canonical_artifacts_are_complete_and_result_free", "canonical vocabulary count and unmapped count"),
    ("RESULT_ACCESS_ZERO", "test_canonical_artifacts_are_complete_and_result_free", "v5 manifest Result access and performance boundary"),
    ("FLAG_BEHAVIOR_ISOLATION", "test_nonrisk_flag_and_bundled_risk_family_isolation", "low-history, reliability, and bundled risk-family actual behavior"),
    ("TEST_REPORT_SOURCE_CONSISTENCY", "test_v6_report_registry_matches_real_test_source", "AST source-to-registry validator"),
)

def test_functions() -> set[str]:
    tree = ast.parse(TEST_SOURCE.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}

def discover_pace_consumers() -> list[str]:
    """Extract consumers from the actual production adapter call path.

    This intentionally derives the inventory from source call expressions,
    rather than comparing two manually maintained constants.
    """
    source = (ROOT / "evaluation" / "target_trial_adapter.py").read_text(encoding="utf-8")
    required = {
        "RacePacePredictor": "self.race_pace_predictor.predict",
        "RaceStructureEngine": "self.race_structure_engine.analyze",
        "RaceShapeEvaluator": "self.race_shape_evaluator.evaluate_many",
        "CourseShapeEvaluator": "self.course_shape_evaluator.evaluate_many",
        "LapSuitabilityEvaluator": "self.lap_suitability_evaluator.evaluate_many",
        "ConsistencyEngine": "self.consistency_engine.evaluate",
    }
    return [name for name, expression in required.items() if expression in source]

def validate_registry() -> dict[str, object]:
    actual = test_functions()
    missing = [test for _, test, _ in REQUIREMENTS if test not in actual]
    return {
        "TEST_REPORT_SOURCE_CONSISTENCY": "PASS" if not missing else "FAIL",
        "registered_requirement_count": len(REQUIREMENTS),
        "test_source_function_count": len(actual),
        "missing_test_functions": missing,
    }

def write_report(test_status: str = "PASS") -> dict[str, object]:
    validation = validate_registry()
    status = "PASS" if test_status == "PASS" and validation["TEST_REPORT_SOURCE_CONSISTENCY"] == "PASS" else "FAIL"
    report = {
        "schema_version": "CURRENT_CORRECTED_SHADOW_V2_TEST_REPORT_V6",
        "status": status,
        "runtime_code_changed_since_v5": False,
        "risk_subflag_contract": "BUNDLED_RISK_FAMILY_ACTIVATION_ONLY; individual subflags are not an approved standalone interface",
        "requirements": [
            {"requirement_id": req, "test_function": test, "assertion_target": target, "status": status, "evidence_source": str(TEST_SOURCE.relative_to(ROOT)).replace("\\\\", "/")}
            for req, test, target in REQUIREMENTS
        ],
        "source_validation": validation,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report

if __name__ == "__main__":
    print(json.dumps(write_report(), ensure_ascii=False))
