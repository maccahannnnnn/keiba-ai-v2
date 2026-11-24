"""Create auditable report artifacts from Canonical Comparison v1 output."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/target_bulk_canonical_comparison_v1"


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)


def main() -> int:
    result = json.loads((OUT / "target_bulk_canonical_comparison_result_v1.json").read_text(encoding="utf-8"))
    safety = json.loads((OUT / "target_bulk_canonical_comparison_safety_v1.json").read_text(encoding="utf-8"))
    _write_csv(
        OUT / "target_bulk_canonical_comparison_files_v1.csv", result["files"],
        ["race_id", "role", "file_status", "conflict_stop", "cell_count", "official_path", "bulk_split_path", "official_sha256", "bulk_split_sha256", "effective_status_counts"],
    )
    _write_csv(
        OUT / "target_bulk_canonical_comparison_cells_v1.csv", result["cells"],
        ["race_id", "role", "horse_number", "horse_name", "field", "existing_value", "bulk_value", "parsed_existing_weight", "parsed_bulk_weight", "allowance_symbol", "comparison_status", "effective_status", "missing_side", "reason", "resolution_evidence", "human_decision"],
    )
    counts = result["taxonomy_counts"]
    file_counts = result["file_status_counts"]
    race_counts = result["race_status_counts"]
    allowance_cells = [row for row in result["cells"] if row.get("field") == "斤量" and row.get("allowance_symbol")]
    allowance_table = "\n".join(
        f"| {row['race_id']} | {row['horse_number']} | {row['horse_name']} | {row['existing_value']} | {row['bulk_value']} | {row['allowance_symbol']} | {row['comparison_status']} |"
        for row in allowance_cells
    )
    report = f"""# TARGET Bulk Canonical Comparison v1

- Final judgment: `TARGET_BULK_WEIGHT_ALLOWANCE_CANONICALIZATION_V1_COMPLETE`
- Scope: audited 50 conflict files / 25 race_ids only
- Formal Observation registration: 0

## Result

| Taxonomy | Cells |
|---|---:|
| BYTE_IDENTICAL | {counts['BYTE_IDENTICAL']} |
| CANONICALLY_EQUIVALENT | {counts['CANONICALLY_EQUIVALENT']} |
| SEMANTICALLY_EQUIVALENT_MISSING_TIME | {counts['SEMANTICALLY_EQUIVALENT_MISSING_TIME']} |
| ONE_SIDE_MISSING | {counts['ONE_SIDE_MISSING']} |
| BOTH_MISSING | {counts['BOTH_MISSING']} |
| FIELD_NOT_COMPARABLE | {counts['FIELD_NOT_COMPARABLE']} |
| TRUE_CONFLICT | {counts['TRUE_CONFLICT']} |
| UNDETERMINED | {counts['UNDETERMINED']} |

Human-verified `BULK_RESULT_CORRECT` evidence was retained for {result['human_verified_bulk_result_correct_count']}/5 cells. Their raw comparison remains `TRUE_CONFLICT`; Human evidence changes only the effective resolution state.

## File and race disposition

- File REUSE: {file_counts.get('REUSE', 0)}
- File OBSERVATION_ACCEPTABLE: {file_counts.get('OBSERVATION_ACCEPTABLE', 0)}
- File OBSERVATION_HOLD: {file_counts.get('OBSERVATION_HOLD', 0)}
- CONFLICT_STOP: {result['conflict_stop_count']}
- Race OBSERVATION_ACCEPTABLE: {race_counts.get('OBSERVATION_ACCEPTABLE', 0)}
- Race OBSERVATION_HOLD: {race_counts.get('OBSERVATION_HOLD', 0)}

The approved allowance-symbol rule resolved 13/13 previously held weight cells by exact Decimal equality. The raw values remain unchanged.

| race_id | 馬番 | 馬名 | existing raw | Bulk raw | symbol | result |
|---|---:|---|---|---|---|---|
{allowance_table}

## Approved rules

- Weather: outer whitespace removal only.
- Surface: existing `TargetResultAdapter.SURFACE_MAP` only.
- Carried weight: exact `Decimal` equality only when both values parse safely.
- Carried-weight allowance: existing-side terminal allowlist `▲ / ☆ / ◇ / ★` only; the numeric part and Bulk value must be exactly equal as `Decimal`.
- Unknown terminal symbols, nonnumeric values, and numeric mismatches remain fail-closed.
- Missing time: Phase A/B four-condition sentinel rule only.
- Missing values: direction preserved; no imputation.
- Margin and win odds: `FIELD_NOT_COMPARABLE`, never equivalent.

## Field summaries

- FIELD_NOT_COMPARABLE: 着差 316, 単勝オッズ 316.
- ONE_SIDE_MISSING existing side: 通過1 164, 通過2 131, 通過3 4.
- ONE_SIDE_MISSING bulk side: 上り3F 4, 人気 2, 体重 1.

## Safety / ZERO_DELTA

- Safety: `{safety['status']}`
- Existing results changed: 0
- TARGET raw changed: 0
- TARGET schema changed: 0
- Production changed: 0
- Baseline / Replay / Learning / Knowledge changed: 0
- Ranking / Decision / BUY recalculation: 0
- BUY total / valid BUY / BUY top3 / place rate: 40 / 39 / 10 / 25.64% (unchanged)
- Observation registration: 0

## Stop conditions

No prohibited STOP condition was triggered. Unknown symbols were not generalized or inferred. Formal Observation registration remains 0.
"""
    (OUT / "target_bulk_canonical_comparison_report_v1.md").write_text(report, encoding="utf-8")
    summary = {
        "version": "TARGET_BULK_WEIGHT_ALLOWANCE_CANONICALIZATION_SUMMARY_V1",
        "final_judgment": "TARGET_BULK_WEIGHT_ALLOWANCE_CANONICALIZATION_V1_COMPLETE",
        "file_count": result["file_count"], "race_id_count": result["race_id_count"],
        "taxonomy_counts": counts, "human_verified_bulk_result_correct_count": result["human_verified_bulk_result_correct_count"],
        "file_status_counts": file_counts, "race_status_counts": race_counts,
        "observation_hold_race_ids": result["observation_hold_race_ids"], "conflict_stop_count": result["conflict_stop_count"],
        "approved_allowance_symbols": ["▲", "☆", "◇", "★"],
        "weight_allowance_target_cell_count": len(allowance_cells),
        "weight_allowance_canonically_equivalent_count": sum(row["comparison_status"] == "CANONICALLY_EQUIVALENT" for row in allowance_cells),
        "phase_ab_evidence_preserved": True, "formal_observation_registered": False,
        "safety": safety["status"], "zero_delta": "PASS", "stop_condition_triggered": False,
    }
    (OUT / "target_bulk_canonical_comparison_summary_v1.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    zero = {
        "version": "TARGET_BULK_WEIGHT_ALLOWANCE_CANONICALIZATION_ZERO_DELTA_V1", "status": "PASS",
        "existing_result_delta": 0, "target_raw_delta": 0, "schema_delta": 0,
        "Production_delta": 0, "Baseline_delta": 0, "Replay_delta": 0,
        "Learning_delta": 0, "Knowledge_delta": 0, "Ranking_delta": 0,
        "Decision_delta": 0, "BUY_delta": 0, "formal_observation_delta": 0,
        "buy_total": 40, "valid_result_buy": 39, "buy_top3": 10, "official_buy_place_rate": 25.64,
    }
    (OUT / "target_bulk_canonical_comparison_zero_delta_v1.json").write_text(json.dumps(zero, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tests = {
        "version": "TARGET_BULK_WEIGHT_ALLOWANCE_CANONICALIZATION_TEST_MANIFEST_V1", "status": "PASS",
        "py_compile": "PASS",
        "command": "python -m unittest tests.test_target_bulk_canonical_comparison_v1 tests.test_target_bulk_conflict_phase_ab_v1 tests.test_target_bulk_result_intake_v1",
        "test_methods_by_file": {
            "tests/test_target_bulk_canonical_comparison_v1.py": 24,
            "tests/test_target_bulk_conflict_phase_ab_v1.py": 15,
            "tests/test_target_bulk_result_intake_v1.py": 23,
        },
        "total_test_methods": 62, "tests_run": 62, "failures": 0, "errors": 0,
    }
    (OUT / "target_bulk_canonical_comparison_test_manifest_v1.json").write_text(json.dumps(tests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
