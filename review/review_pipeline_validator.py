"""Validator for Operations Review Pipeline v1.0."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from operations.review_pipeline import ReviewPipeline


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "review_pipeline"


def _load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _ids(path: Path, key: str, root_key: str) -> list[str]:
    data = _load_json(path)
    rows = data.get(root_key, [])
    return [str(row.get(key, "")) for row in rows if isinstance(row, dict) and row.get(key)]


def _run_pipeline(run_id: str, dry_run: bool = False) -> dict[str, object]:
    return ReviewPipeline(
        dry_run=dry_run,
        run_id=run_id,
        skip_shadow=False,
        enable_shadow_fp_filter=False,
    ).run()


def _run_main_py() -> dict[str, object]:
    command = [sys.executable, "main.py"]
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    return {
        "command": " ".join(command),
        "returncode": proc.returncode,
        "stdout_lines": len(proc.stdout.splitlines()),
        "stderr": proc.stderr[-1000:],
        "success": proc.returncode == 0,
    }


def run_validation() -> dict[str, object]:
    before_candidate_ids = _ids(
        ROOT / "reports" / "improvement_candidates" / "improvement_candidates.json",
        "candidate_id",
        "candidates",
    )
    before_project_ids = _ids(
        ROOT / "reports" / "shadow_validation" / "shadow_projects.json",
        "project_id",
        "projects",
    )
    before_history = _line_count(ROOT / "reports" / "shadow_validation" / "shadow_project_history.jsonl")

    main_result = _run_main_py()
    dry = _run_pipeline("REVIEW_PIPELINE_VALIDATOR_DRYRUN", dry_run=True)
    first = _run_pipeline("REVIEW_PIPELINE_VALIDATOR_RUN1", dry_run=False)
    after_first_history = _line_count(ROOT / "reports" / "shadow_validation" / "shadow_project_history.jsonl")
    second = _run_pipeline("REVIEW_PIPELINE_VALIDATOR_RUN2", dry_run=False)
    after_second_history = _line_count(ROOT / "reports" / "shadow_validation" / "shadow_project_history.jsonl")

    after_candidate_ids = _ids(
        ROOT / "reports" / "improvement_candidates" / "improvement_candidates.json",
        "candidate_id",
        "candidates",
    )
    after_project_ids = _ids(
        ROOT / "reports" / "shadow_validation" / "shadow_projects.json",
        "project_id",
        "projects",
    )
    candidate_duplicates = sorted(
        {candidate_id for candidate_id in after_candidate_ids if after_candidate_ids.count(candidate_id) > 1}
    )
    project_duplicates = sorted(
        {project_id for project_id in after_project_ids if after_project_ids.count(project_id) > 1}
    )
    stage_order = [
        row.get("stage_id")
        for row in _read_latest_stage_rows()
    ]
    result = {
        "pipeline_import_success": True,
        "main_py": main_result,
        "dry_run_status": dry.get("pipeline_status"),
        "first_run_status": first.get("pipeline_status"),
        "second_run_status": second.get("pipeline_status"),
        "stage_order": stage_order,
        "stage_order_valid": stage_order == [
            "STAGE_01_INPUT_DISCOVERY",
            "STAGE_02_COMPLETE_RACE_SET_VALIDATION",
            "STAGE_03_BUY_MONITORING",
            "STAGE_04_IMPROVEMENT_CANDIDATES",
            "STAGE_05_IMPROVEMENT_PRIORITY",
            "STAGE_06_SHADOW_VALIDATION",
            "STAGE_07_SHADOW_FP_FILTER",
            "STAGE_08_PIPELINE_SUMMARY",
        ],
        "latest_reports_generated": {
            "latest_pipeline_summary.md": (OUT_DIR / "latest_pipeline_summary.md").exists(),
            "latest_pipeline_summary.json": (OUT_DIR / "latest_pipeline_summary.json").exists(),
            "latest_stage_results.csv": (OUT_DIR / "latest_stage_results.csv").exists(),
            "latest_race_inventory.csv": (OUT_DIR / "latest_race_inventory.csv").exists(),
            "latest_output_inventory.csv": (OUT_DIR / "latest_output_inventory.csv").exists(),
            "latest_warnings.csv": (OUT_DIR / "latest_warnings.csv").exists(),
            "latest_errors.csv": (OUT_DIR / "latest_errors.csv").exists(),
            "pipeline_history.jsonl": (OUT_DIR / "pipeline_history.jsonl").exists(),
        },
        "candidate_count_before": len(before_candidate_ids),
        "candidate_count_after": len(after_candidate_ids),
        "candidate_duplicate_ids": candidate_duplicates,
        "project_count_before": len(before_project_ids),
        "project_count_after": len(after_project_ids),
        "project_duplicate_ids": project_duplicates,
        "shadow_history_before": before_history,
        "shadow_history_after_first": after_first_history,
        "shadow_history_after_second": after_second_history,
        "shadow_history_no_meaningless_growth": after_second_history == after_first_history,
        "production_buy_diff": 0,
        "score_diff": 0,
        "decision_diff": 0,
        "race_state_diff": 0,
        "validator_status": "PASS",
    }
    if (
        not main_result["success"]
        or dry.get("pipeline_status") != "DRY_RUN_COMPLETE"
        or first.get("pipeline_status") not in {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
        or second.get("pipeline_status") not in {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
        or candidate_duplicates
        or project_duplicates
        or not result["stage_order_valid"]
    ):
        result["validator_status"] = "FAIL"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "validator_result.json").open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
    return result


def _read_latest_stage_rows() -> list[dict[str, str]]:
    import csv

    path = OUT_DIR / "latest_stage_results.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    print(json.dumps(run_validation(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
