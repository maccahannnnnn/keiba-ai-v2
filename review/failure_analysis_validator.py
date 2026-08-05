"""Validator for Failure Analysis Engine v1.0."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "failure_analysis" / "SP_COUNT_EQ_2"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _history_count() -> int:
    path = ROOT / "reports" / "shadow_validation" / "shadow_project_history.jsonl"
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def _main_py_check() -> dict[str, Any]:
    py = ROOT.parent / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)
    proc = subprocess.run(
        [str(py), "main.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return {"returncode": proc.returncode, "success": proc.returncode == 0, "stdout_lines": len(proc.stdout.splitlines()), "stderr": proc.stderr[-500:]}


def run_validation() -> dict[str, Any]:
    summary = read_json(OUT_DIR / "failure_analysis_summary.json")
    matrix = read_csv(OUT_DIR / "failure_feature_matrix.csv")
    removed_success = read_csv(OUT_DIR / "removed_successful_buy_cases.csv")
    removed_fp = read_csv(OUT_DIR / "removed_false_positive_cases.csv")
    possible = read_csv(OUT_DIR / "possible_separators.csv")
    causes = read_csv(OUT_DIR / "failure_cause_candidates.csv")
    errors = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(len([r for r in matrix if r.get("analysis_group", "").startswith("REMOVED_")]) == 7, "removed_buy_7_not_recognized")
    require(len(removed_success) == 2, "removed_successful_buy_2_not_recognized")
    require(len(removed_fp) == 5, "removed_fp_5_not_recognized")
    require(all(row.get("filter_rule_id") == "SP_COUNT_EQ_2" for row in matrix if row.get("analysis_group", "").startswith("REMOVED_")), "non_sp_count_rule_mixed")
    require(len({(row.get("race_id"), row.get("horse_name")) for row in matrix if row.get("analysis_group", "").startswith("REMOVED_")}) == 7, "removed_duplicate_count")
    require(summary.get("candidate_registration_count") == 0, "candidate_was_registered")
    require(summary.get("production_buy_diff") == 0, "production_buy_diff_not_zero")
    require(summary.get("score_diff") == 0, "score_diff_not_zero")
    require(summary.get("decision_diff") == 0, "decision_diff_not_zero")
    require(summary.get("race_state_diff") == 0, "race_state_diff_not_zero")
    require(bool(possible), "possible_separator_not_found")
    require(bool(causes), "cause_candidates_not_found")
    require(all("閾値" not in json.dumps(row, ensure_ascii=False) for row in possible), "threshold_auto_decision_detected")

    before = _history_count()
    after = _history_count()
    main_check = _main_py_check()
    require(main_check["success"], "main_py_failed")
    result = {
        "validator_status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "removed_buy_count": 7,
        "removed_successful_buy_count": len(removed_success),
        "removed_fp_count": len(removed_fp),
        "possible_separator_count": len(possible),
        "cause_candidate_count": len(causes),
        "history_before": before,
        "history_after": after,
        "history_diff": after - before,
        "production_buy_diff": summary.get("production_buy_diff"),
        "score_diff": summary.get("score_diff"),
        "decision_diff": summary.get("decision_diff"),
        "race_state_diff": summary.get("race_state_diff"),
        "main_py": main_check,
    }
    (OUT_DIR / "validator_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_validation(), ensure_ascii=False, indent=2, sort_keys=True))
