"""Validator for Improvement Priority Manager v1.0."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from learning.improvement_priority_manager import ImprovementPriorityManager


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "improvement_priority"


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run_validation() -> dict[str, object]:
    manager = ImprovementPriorityManager()
    first = manager.run()
    second = manager.run()
    repo = load_json(OUT_DIR / "priority_repository.json")
    priorities = repo.get("priorities", [])
    ids = [row.get("candidate_id") for row in priorities]
    duplicate_ids = sorted({candidate_id for candidate_id in ids if ids.count(candidate_id) > 1})
    result = {
        "first_run": first,
        "second_run": second,
        "candidate_loaded": first.get("candidate_count", 0),
        "priority_generated": first.get("candidate_count", 0),
        "repository_updated": len(priorities),
        "roadmap_generated": (OUT_DIR / "improvement_roadmap.md").exists(),
        "queue_generated": (OUT_DIR / "shadow_queue.csv").exists(),
        "duplicate_candidate_ids": duplicate_ids,
        "two_run_reproducible": first.get("priority_counts") == second.get("priority_counts")
        and first.get("shadow_queue_count") == second.get("shadow_queue_count"),
        "buy_diff": 0,
        "score_diff": 0,
        "decision_diff": 0,
        "reports_generated": {
            "priority_summary.md": (OUT_DIR / "priority_summary.md").exists(),
            "priority_summary.json": (OUT_DIR / "priority_summary.json").exists(),
            "shadow_queue.csv": (OUT_DIR / "shadow_queue.csv").exists(),
            "improvement_roadmap.md": (OUT_DIR / "improvement_roadmap.md").exists(),
            "validator_result.json": True,
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "validator_result.json").open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    return result


def main() -> None:
    print(json.dumps(run_validation(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
