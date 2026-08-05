"""Validator for the June focused cohort validation output."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_COHORT_ID = "JUNE_20260613_20260614_12R"
OUT_ROOT = ROOT / "reports" / "cohort_validation"
EXPECTED_RACES_12R = {
    "race_20260613_hakodate_10R",
    "race_20260613_hakodate_11R",
    "race_20260613_tokyo_10R",
    "race_20260613_tokyo_11R",
    "race_20260613_hanshin_11R",
    "race_20260613_hanshin_12R",
    "race_20260614_hakodate_10R",
    "race_20260614_hakodate_11R",
    "race_20260614_tokyo_11R",
    "race_20260614_tokyo_12R",
    "race_20260614_hanshin_10R",
    "race_20260614_hanshin_11R",
}


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


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)


def bundled_python() -> str:
    candidate = ROOT.parent / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python" / "python.exe"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def run_validation(cohort_id: str = DEFAULT_COHORT_ID, output_dir: str | Path | None = None) -> dict[str, Any]:
    out_dir = Path(output_dir) if output_dir else OUT_ROOT / cohort_id
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    summary = read_json(out_dir / "cohort_summary.json")
    inventory = read_csv(out_dir / "cohort_inventory.csv")
    horses = read_csv(out_dir / "horse_analysis_results.csv")
    races = read_csv(out_dir / "race_analysis_results.csv")
    errors = read_csv(out_dir / "validation_errors.csv")
    shadow = read_json(out_dir / "shadow_diagnostic" / "shadow_summary.json")

    found_ids = {row.get("race_id") for row in inventory}
    expected_ids = set(summary.get("requested_race_ids") or [])
    if not expected_ids and cohort_id == DEFAULT_COHORT_ID:
        expected_ids = EXPECTED_RACES_12R
    expected_count = len(expected_ids) if expected_ids else int(summary.get("requested_race_count") or 0)
    result: dict[str, Any] = {
        "validator_status": "PASS",
        "errors": [],
        "cohort_id": cohort_id,
        "requested_race_count": len(found_ids),
        "expected_race_count": expected_count,
        "complete_race_set_count": int(summary.get("complete_race_set_count") or 0),
        "validated_race_count": len(races),
        "horse_count": len(horses),
        "missing_count": int(summary.get("missing_count") or 0),
        "duplicate_count": int(summary.get("duplicate_count") or 0),
        "unexpected_race_count": int(summary.get("unexpected_race_count") or 0),
        "production_buy_diff": summary.get("production_buy_diff"),
        "score_diff": summary.get("score_diff"),
        "decision_diff": summary.get("decision_diff"),
        "race_state_diff": summary.get("race_state_diff"),
        "candidate_registration_count": summary.get("candidate_registration_count"),
        "shadow_project_created_count": summary.get("shadow_project_created_count"),
        "history_diff": summary.get("history_diff"),
        "shadow_rule_id": shadow.get("rule_id"),
        "shadow_project_status_changed": shadow.get("project_status_changed"),
    }
    if expected_ids and found_ids != expected_ids:
        result["errors"].append("requested_race_ids_do_not_match_expected")
    if result["complete_race_set_count"] != expected_count or result["validated_race_count"] != expected_count:
        result["errors"].append("complete_or_validated_race_count_not_expected")
    if result["missing_count"] != 0 or result["duplicate_count"] != 0 or result["unexpected_race_count"] != 0:
        result["errors"].append("inventory_not_clean")
    if errors:
        result["errors"].append("validation_errors_present")
    if not horses:
        result["errors"].append("horse_analysis_results_empty")
    if not (out_dir / "races" / "race_20260614_hanshin_11R.md").exists():
        result["errors"].append("takara_zuka_race_report_missing")
    for key in ["production_buy_diff", "score_diff", "decision_diff", "race_state_diff", "candidate_registration_count", "shadow_project_created_count", "history_diff"]:
        if result.get(key) != 0:
            result["errors"].append(f"{key}_not_zero")
    main_run = subprocess.run([bundled_python(), "main.py"], cwd=ROOT, text=True, capture_output=True)
    result["main_py"] = {
        "returncode": main_run.returncode,
        "success": main_run.returncode == 0,
        "stdout_lines": len(main_run.stdout.splitlines()),
        "stderr": main_run.stderr[-1000:],
    }
    if main_run.returncode != 0:
        result["errors"].append("main_py_failed")
    if result["errors"]:
        result["validator_status"] = "FAIL"
    write_json(out_dir / "validator_result.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(run_validation(), ensure_ascii=False, indent=2, sort_keys=True))
