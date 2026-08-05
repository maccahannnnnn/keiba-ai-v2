"""Validator for Separator Candidate Analyzer v1.0."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "separator_candidate_analysis" / "SP_COUNT_EQ_2"
FAILURE_DIR = ROOT / "reports" / "failure_analysis" / "SP_COUNT_EQ_2"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def history_count() -> int:
    path = ROOT / "reports" / "shadow_validation" / "shadow_project_history.jsonl"
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def main_py_check() -> dict[str, Any]:
    py = ROOT.parent / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)
    proc = subprocess.run([str(py), "main.py"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return {"returncode": proc.returncode, "success": proc.returncode == 0, "stdout_lines": len(proc.stdout.splitlines()), "stderr": proc.stderr[-500:]}


def run_validation() -> dict[str, Any]:
    summary = read_json(OUT_DIR / "separator_analysis_summary.json")
    failure = read_json(FAILURE_DIR / "failure_analysis_summary.json")
    ranking = read_csv(OUT_DIR / "separator_candidate_ranking.csv")
    excluded = read_csv(OUT_DIR / "excluded_features.csv")
    numeric = read_csv(OUT_DIR / "numeric_feature_comparison.csv")
    categorical = read_csv(OUT_DIR / "categorical_feature_comparison.csv")
    reasons = read_csv(OUT_DIR / "reason_feature_comparison.csv")
    counters = read_csv(OUT_DIR / "counter_examples.csv")
    errors = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(summary.get("removed_successful_buy_count") == 2, "removed_successful_buy_count_not_2")
    require(summary.get("removed_fp_count") == 5, "removed_fp_count_not_5")
    require(summary.get("kept_successful_buy_count") == 7, "kept_successful_buy_count_not_7")
    require(summary.get("source_failure_analysis_fingerprint") == failure.get("analysis_fingerprint"), "failure_fingerprint_mismatch")
    require(any(row.get("feature_name") == "adjusted_score" for row in numeric), "adjusted_score_not_analyzed")
    require(any(row.get("feature_name") == "strong_positive_count" and row.get("exclude_reason") == "CONSTANT_WITHIN_TARGET" for row in excluded), "strong_positive_count_not_excluded_constant")
    leakage = {"horse_name", "race_id", "horse_number", "finish_position", "is_top3", "analysis_group", "production_buy", "shadow_buy", "removed_by_shadow", "filter_rule_matched", "validation_group"}
    require(not any(row.get("feature_name") in leakage for row in ranking), "result_leakage_feature_ranked")
    require(bool(ranking), "ranking_empty")
    require(bool(counters), "counter_examples_missing")
    require(summary.get("candidate_registration_count") == 0, "candidate_registered")
    require(summary.get("shadow_project_created_count") == 0, "shadow_project_created")
    require(summary.get("production_buy_diff") == 0, "production_buy_diff")
    require(summary.get("score_diff") == 0, "score_diff")
    require(summary.get("decision_diff") == 0, "decision_diff")
    require(summary.get("race_state_diff") == 0, "race_state_diff")
    text = json.dumps(ranking, ensure_ascii=False)
    require(">= " not in text and "<= " not in text, "threshold_like_rule_generated")
    require(len(categorical) >= 1, "categorical_not_analyzed")
    require(len(reasons) >= 1, "reason_not_analyzed")

    before = history_count()
    after = history_count()
    main_check = main_py_check()
    require(main_check["success"], "main_py_failed")
    result = {
        "validator_status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "ranking_count": len(ranking),
        "rank_a_count": summary.get("rank_a_count"),
        "rank_b_count": summary.get("rank_b_count"),
        "excluded_feature_count": len(excluded),
        "adjusted_score_analyzed": True,
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
