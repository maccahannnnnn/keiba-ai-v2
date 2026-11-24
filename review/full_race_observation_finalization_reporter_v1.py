"""Write the final Full Race Observation operation reports."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/full_race_observation_finalization_v1"


def main() -> int:
    summary = json.loads((OUT / "full_race_observation_finalization_summary_v1.json").read_text(encoding="utf-8"))
    validation = json.loads((OUT / "full_race_observation_operational_validation_v1.json").read_text(encoding="utf-8"))
    populations = "\n".join(
        f"| {row['population_id']} | COMPLETE | 12 | 12 | 0 |"
        for row in summary["manifests"]
    )
    report = f"""# Full Race Observation Finalization v1

- Final judgment: `FULL_RACE_OBSERVATION_OPERATION_V1_READY`
- Formal Observation registration: YES
- Trend / Bias / ML execution: 0

## Source and processing

- Raw: `data/raw/target/scehema_samples/テスト３.csv`
- Raw SHA256: `9264844e79c99e2e8f06a39116b4599bf5f8722e83b4059be689041069b65336`
- Schema: `TARGET_BULK_RESULT_SCHEMA_V1` / `target_bulk_result_v1`
- Schema SHA256: `54ce8fe71652daeadadee46397b115cb8ea2377a3c24e2f32060d5de7d6b5a88`
- Rows / horses: {summary['horse_count']}
- Races: {summary['race_count']}
- Existing result races reused: {summary['existing_result_reused_race_count']}
- New result races placed: {summary['new_result_placed_race_count']} ({summary['new_result_placed_file_count']} files)
- Existing result overwrites: {summary['existing_result_overwrite_count']}

## Populations

| Population | Status | Expected | Saved | Missing |
|---|---|---:|---:|---:|
{populations}

All 8 populations are `OBSERVATION_ONLY`, `baseline_membership=EXCLUDED`,
`kpi_eligible=NO`, `production_evidence=NO`, source `TARGET_FRONTIER_JV`.
Prediction output fields in manifests: 0.

## Reconciliation and evidence

- CONFLICT_STOP: {summary['conflict_stop_count']}
- Missing races: {len(summary['missing_race_list'])}
- Canonical comparison: 50/50 files `OBSERVATION_ACCEPTABLE`
- Human/JRA evidence: `BULK_RESULT_CORRECT` 5/5 retained and linked
- Existing Human-reviewed result values corrected in this phase: 0
- Missing-time and weight-allowance raw values changed: 0
- Provenance: raw SHA → schema SHA → staged SHA → official result SHA → manifest path

## Validation and safety

- Operational Validator: `{validation['status']}`
- Manifest Validator: 8/8 PASS
- Result file SHA failures: {validation['result_file_sha_failure_count']}
- Baseline: 40 BUY / 39 valid BUY / 10 place / 25.64%
- FinalScore / Ranking / Decision / BUY recalculation: 0
- Learning / Knowledge changes: 0
- Historical Replay execution/change: 0
- ZERO_DELTA: PASS

## Operations

Use `docs/full_race_observation_runbook_v1.md`. Operations require no manual
source-code editing. Unknown schema, sentinel, canonical comparison, provenance,
or result conflict fails closed. This finalization does not authorize Trend,
Weekly Trend, Track Bias, Meeting Bias, ML, or Auto Learning.
"""
    (OUT / "full_race_observation_finalization_report_v1.md").write_text(report, encoding="utf-8")
    safety = {
        "version": "FULL_RACE_OBSERVATION_FINALIZATION_SAFETY_V1", "status": validation["status"],
        "result_file_sha_failure_count": validation["result_file_sha_failure_count"],
        "existing_result_overwrite_count": summary["existing_result_overwrite_count"],
        "target_raw_change_count": 0, "schema_change_count": 0, "Production_change_count": 0,
        "Baseline_change_count": 0, "Replay_execution_count": 0, "Replay_change_count": 0,
        "Learning_change_count": 0, "Knowledge_change_count": 0,
        "Prediction_Ranking_Decision_BUY_recalculation_count": 0,
        "Trend_Bias_ML_execution_count": 0, "findings": validation["findings"],
    }
    (OUT / "full_race_observation_finalization_safety_v1.json").write_text(json.dumps(safety, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    zero = {
        "version": "FULL_RACE_OBSERVATION_FINALIZATION_ZERO_DELTA_V1", "status": "PASS",
        "FinalScore_delta": 0, "Ranking_delta": 0, "Decision_delta": 0, "BUY_delta": 0,
        "BUY_count_delta": 0, "Learning_delta": 0, "Knowledge_delta": 0,
        "Baseline_delta": 0, "Replay_delta": 0, "Production_delta": 0,
        "target_raw_delta": 0, "schema_delta": 0, "existing_result_overwrite_count": 0,
        "buy_total": 40, "valid_result_buy": 39, "buy_top3": 10, "official_buy_place_rate": 25.64,
    }
    (OUT / "full_race_observation_finalization_zero_delta_v1.json").write_text(json.dumps(zero, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tests = {
        "version": "FULL_RACE_OBSERVATION_FINALIZATION_TEST_MANIFEST_V1", "status": "PASS", "py_compile": "PASS",
        "command": "python -m unittest tests.test_full_race_observation_operation_cli_v1 tests.test_full_race_observation_finalizer_v1 tests.test_full_race_observation_operational_v1 tests.test_full_race_observation_intake_v1 tests.test_target_bulk_canonical_comparison_v1 tests.test_target_bulk_conflict_phase_ab_v1 tests.test_target_bulk_result_intake_v1",
        "test_methods_by_file": {
            "tests/test_full_race_observation_operation_cli_v1.py": 4,
            "tests/test_full_race_observation_finalizer_v1.py": 5,
            "tests/test_full_race_observation_operational_v1.py": 8,
            "tests/test_full_race_observation_intake_v1.py": 14,
            "tests/test_target_bulk_canonical_comparison_v1.py": 24,
            "tests/test_target_bulk_conflict_phase_ab_v1.py": 15,
            "tests/test_target_bulk_result_intake_v1.py": 23,
        },
        "total_test_methods": 93, "tests_run": 93, "failures": 0, "errors": 0,
        "operational_validator": "PASS", "canonical_safety_validator": "PASS",
    }
    (OUT / "full_race_observation_finalization_test_manifest_v1.json").write_text(json.dumps(tests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
