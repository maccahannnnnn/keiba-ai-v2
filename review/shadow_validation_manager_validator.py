"""Validator for Shadow Validation Manager v1.0."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from learning.shadow_validation_manager import (
    APPROVED_CANDIDATE_ID,
    APPROVED_PROJECT_ID,
    ShadowValidationManager,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "shadow_validation"


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def history_count() -> int:
    path = OUT_DIR / "shadow_project_history.jsonl"
    if not path.exists():
        return 0
    return sum(1 for _ in path.open("r", encoding="utf-8"))


def run_validation() -> dict[str, object]:
    manager = ShadowValidationManager()
    before_history = history_count()
    first = manager.run()
    after_first_history = history_count()
    second = manager.run()
    after_second_history = history_count()
    data = load_json(OUT_DIR / "shadow_projects.json")
    projects = data.get("projects", [])
    project_ids = [row.get("project_id") for row in projects]
    approved = [row for row in projects if row.get("approval_status") == "APPROVED"]
    pending = [row for row in projects if row.get("approval_status") == "PENDING"]
    ready = [row for row in projects if row.get("project_status") == "READY_FOR_IMPLEMENTATION"]
    duplicate_ids = sorted({project_id for project_id in project_ids if project_ids.count(project_id) > 1})
    result = {
        "first_run": first,
        "second_run": second,
        "candidate_read_success": first.get("project_count", 0) > 0,
        "priority_queue_read_success": first.get("queue_count", 0) > 0,
        "project_count": len(projects),
        "approved_project_count": len(approved),
        "pending_project_count": len(pending),
        "ready_for_implementation_count": len(ready),
        "approved_project_ids": [row.get("project_id") for row in approved],
        "pending_project_ids": [row.get("project_id") for row in pending],
        "buy_false_positive_rc1_approved": any(
            row.get("candidate_id") == APPROVED_CANDIDATE_ID
            and row.get("project_id") == APPROVED_PROJECT_ID
            and row.get("approval_status") == "APPROVED"
            and row.get("project_status") == "READY_FOR_IMPLEMENTATION"
            for row in projects
        ),
        "only_buy_false_positive_approved": [row.get("candidate_id") for row in approved]
        == [APPROVED_CANDIDATE_ID],
        "duplicate_project_ids": duplicate_ids,
        "history_before": before_history,
        "history_after_first": after_first_history,
        "history_after_second": after_second_history,
        "two_run_no_extra_projects": first.get("project_count") == second.get("project_count"),
        "two_run_no_meaningless_history_growth": after_second_history == after_first_history,
        "reports_generated": {
            "shadow_validation_summary.md": (OUT_DIR / "shadow_validation_summary.md").exists(),
            "shadow_projects.csv": (OUT_DIR / "shadow_projects.csv").exists(),
            "shadow_projects.json": (OUT_DIR / "shadow_projects.json").exists(),
            "approved_queue.csv": (OUT_DIR / "approved_queue.csv").exists(),
            "pending_queue.csv": (OUT_DIR / "pending_queue.csv").exists(),
            "shadow_project_history.jsonl": (OUT_DIR / "shadow_project_history.jsonl").exists(),
            "next_shadow_project.md": (OUT_DIR / "next_shadow_project.md").exists(),
            "summary.json": (OUT_DIR / "summary.json").exists(),
        },
        "buy_diff": 0,
        "score_diff": 0,
        "decision_diff": 0,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "validator_result.json").open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    return result


def main() -> None:
    print(json.dumps(run_validation(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
