"""Read-only validator for the Learning Candidate production pipeline.

The validator checks that candidate generation, ranking, human review, and
shadow validation artifacts are connected. It does not rerun engines that append
history or mutate candidate repositories.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "learning_candidate_pipeline_validation"


def run_validation() -> dict[str, object]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    learning_db = _read_json(ROOT / "learning" / "improvement_candidates.json")
    report_candidates = _read_json(
        ROOT / "reports" / "improvement_candidates" / "improvement_candidates.json"
    )
    priority_summary = _read_json(ROOT / "reports" / "improvement_priority" / "priority_summary.json")
    human_review = _read_json(ROOT / "learning" / "candidate_review_status.json")
    shadow_summary = _read_json(ROOT / "reports" / "shadow_validation" / "summary.json")
    pipeline_source = (ROOT / "operations" / "review_pipeline.py").read_text(
        encoding="utf-8",
        errors="replace",
    )

    learning_records = _list(learning_db.get("records"))
    learning_aggregates = _list(learning_db.get("aggregates"))
    report_rows = _list(report_candidates.get("candidates"))
    review_rows = _list(human_review.get("records"))

    report_ids = [row.get("candidate_id") for row in report_rows if row.get("candidate_id")]
    learning_ids = [row.get("candidate_id") for row in learning_records if row.get("candidate_id")]
    evidence_counts = [
        int(row.get("evidence_count", 0) or 0)
        for row in report_rows
        if isinstance(row, dict)
    ]
    priority_counts = priority_summary.get("priority_counts", {})
    status_counts = Counter(row.get("status", "") for row in review_rows)

    summary = {
        "status": "PASS" if _all_required_present(
            learning_records,
            report_rows,
            priority_summary,
            review_rows,
            shadow_summary,
            pipeline_source,
        ) else "REVIEW_REQUIRED",
        "learning_db_records": len(learning_records),
        "learning_db_aggregates": len(learning_aggregates),
        "report_candidate_count": len(report_rows),
        "report_duplicate_candidate_ids": _duplicates(report_ids),
        "learning_duplicate_candidate_ids": _duplicates(learning_ids),
        "evidence_count_positive_rows": sum(1 for value in evidence_counts if value > 0),
        "priority_counts": priority_counts,
        "shadow_queue_count": priority_summary.get("shadow_queue_count", 0),
        "human_review_records": len(review_rows),
        "human_review_status_counts": dict(status_counts),
        "shadow_project_count": shadow_summary.get("project_count", 0),
        "shadow_status_counts": shadow_summary.get("status_counts", {}),
        "pipeline_connections": {
            "improvement_candidates_stage": "ImprovementCandidateEngine().generate" in pipeline_source,
            "priority_stage": "ImprovementPriorityManager().run" in pipeline_source,
            "shadow_stage": "ShadowValidationManager" in pipeline_source,
            "buy_monitor_stage": "review.buy_monitor" in pipeline_source,
        },
        "writes_existing_history": False,
        "auto_production_change": False,
    }
    _write_json(OUT_DIR / "summary.json", summary)
    _write_md(OUT_DIR / "summary.md", summary)
    return summary


def _all_required_present(
    learning_records,
    report_rows,
    priority_summary,
    review_rows,
    shadow_summary,
    pipeline_source,
) -> bool:
    return all(
        [
            len(learning_records) > 0,
            len(report_rows) > 0,
            bool(priority_summary.get("priority_counts")),
            len(review_rows) > 0,
            int(shadow_summary.get("project_count", 0) or 0) > 0,
            "ImprovementCandidateEngine().generate" in pipeline_source,
            "ImprovementPriorityManager().run" in pipeline_source,
            "ShadowValidationManager" in pipeline_source,
        ]
    )


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _list(value) -> list[dict[str, object]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _duplicates(values: list[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def _write_json(path: Path, data: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _write_md(path: Path, summary: dict[str, object]) -> None:
    lines = [
        "# Learning Candidate Pipeline Validation",
        "",
        f"- Status: {summary.get('status')}",
        f"- Learning DB Records: {summary.get('learning_db_records')}",
        f"- Learning DB Aggregates: {summary.get('learning_db_aggregates')}",
        f"- Report Candidate Count: {summary.get('report_candidate_count')}",
        f"- Evidence Rows > 0: {summary.get('evidence_count_positive_rows')}",
        f"- Priority Counts: {summary.get('priority_counts')}",
        f"- Shadow Queue Count: {summary.get('shadow_queue_count')}",
        f"- Human Review Records: {summary.get('human_review_records')}",
        f"- Human Review Status Counts: {summary.get('human_review_status_counts')}",
        f"- Shadow Project Count: {summary.get('shadow_project_count')}",
        f"- Pipeline Connections: {summary.get('pipeline_connections')}",
        f"- Existing History Writes: {summary.get('writes_existing_history')}",
        f"- Auto Production Change: {summary.get('auto_production_change')}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    print(json.dumps(run_validation(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
