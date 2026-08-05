"""Validator for MeetingBias production wiring.

This validator is diagnostic only. It runs TargetTrialAdapter with persistence
layers disabled, then verifies that MeetingBias is present as explain/review
metadata and remains non-scoring.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from evaluation.race_file_locator import RaceFileLocator
from evaluation.target_trial_adapter import TargetTrialAdapter


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "meeting_bias_validation"


def _noop_adapter() -> TargetTrialAdapter:
    adapter = TargetTrialAdapter()
    adapter.result_importer.import_result = lambda *a, **k: {
        "race_result": {},
        "horse_results": [],
        "result_loaded": False,
        "result_status": "validator_no_result",
    }
    adapter.review_engine.review = lambda *a, **k: {
        "review_summary": {},
        "review_score": 0,
        "review_level": "",
        "review_hits": [],
        "review_misses": [],
        "review_comment": "",
    }
    adapter.improvement_advisor.advise = lambda *a, **k: {
        "improvement_summary": {},
        "improvement_suggestions": [],
        "improvement_targets": [],
        "improvement_priority": "",
        "improvement_comment": "",
    }
    adapter.learning_database.save = lambda *a, **k: {
        "learning_record": {},
        "learning_history": [],
        "learning_id": "",
        "learning_time": "",
        "learning_status": "validator_no_write",
    }
    adapter.learning_engine.analyze = lambda *a, **k: {
        "learning_analysis_result": {},
        "learning_summary": {},
        "learning_trends": {},
        "success_patterns": [],
        "failure_patterns": [],
        "frequent_improvement_targets": [],
        "decision_trends": {},
        "confidence_trends": {},
        "learning_comment": "",
    }
    adapter.learning_candidate_engine.generate = lambda *a, **k: {
        "candidates": [],
        "summary": {},
        "warnings": [],
    }
    adapter.learning_phase2_writer.write_analysis = lambda *a, **k: {
        "enabled": False,
        "saved": False,
        "record_count": 0,
        "storage_path": "",
    }
    return adapter


def _target_pairs(limit: int = 8) -> list[dict[str, str]]:
    pairs = RaceFileLocator().find_analysis_pairs(ROOT / "data" / "analysis").get("pairs", [])
    preferred = [row for row in pairs if "20260801" in str(row.get("race_id", ""))]
    selected = preferred or pairs
    return sorted(selected, key=lambda row: row.get("race_id", ""))[:limit]


def run_validation() -> dict[str, object]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    adapter = _noop_adapter()
    rows = []
    errors = []
    stage_counts = {"opening": 0, "middle": 0, "closing": 0}
    score_impact_violations = []
    trial_report_missing = []
    review_trace_missing = []

    for pair in _target_pairs():
        race_id = pair.get("race_id", "")
        try:
            output = adapter.run(pair.get("entry_path"), horse_data_csv_path=pair.get("horses_path"))
        except Exception as exc:  # validator should report, not hide, wiring failures
            errors.append({"race_id": race_id, "error": str(exc)})
            continue

        meeting = output.get("meeting_bias_result") if isinstance(output, dict) else {}
        if not isinstance(meeting, dict):
            meeting = {}
        stage = meeting.get("selected_meeting_stage", "")
        if stage in stage_counts:
            stage_counts[stage] += 1
        if meeting.get("score_impact") != "none":
            score_impact_violations.append(race_id)
        trial_report = output.get("trial_report") or ""
        if "MeetingBias" not in trial_report:
            trial_report_missing.append(race_id)

        review_record = output.get("review_record") if isinstance(output.get("review_record"), dict) else {}
        horses = review_record.get("horses") if isinstance(review_record.get("horses"), list) else []
        if horses:
            first = horses[0]
            trace = first.get("review_trace") if isinstance(first.get("review_trace"), dict) else {}
            if "meeting_bias_comment" not in trace:
                review_trace_missing.append(race_id)
        else:
            review_trace_missing.append(race_id)

        rows.append(
            {
                "race_id": race_id,
                "meeting_bias_ready": meeting.get("meeting_bias_ready", False),
                "selected_stage": stage,
                "selected_surface": meeting.get("selected_surface", ""),
                "selected_distance_category": meeting.get("selected_distance_category", ""),
                "score_impact": meeting.get("score_impact", ""),
                "comment_present": bool(meeting.get("meeting_bias_comment")),
                "trial_report_present": "MeetingBias" in trial_report,
                "review_trace_present": race_id not in review_trace_missing,
            }
        )

    summary = {
        "status": "PASS"
        if rows and not errors and not score_impact_violations and not trial_report_missing and not review_trace_missing
        else "REVIEW_REQUIRED",
        "race_count": len(rows),
        "stage_counts": stage_counts,
        "errors": errors,
        "score_impact_violations": score_impact_violations,
        "trial_report_missing": trial_report_missing,
        "review_trace_missing": review_trace_missing,
        "production_score_impact": "none",
        "writes_existing_history": False,
    }
    _write_csv(OUT_DIR / "race_validation.csv", rows)
    _write_json(OUT_DIR / "summary.json", summary)
    _write_md(OUT_DIR / "summary.md", summary)
    return summary


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "race_id",
        "meeting_bias_ready",
        "selected_stage",
        "selected_surface",
        "selected_distance_category",
        "score_impact",
        "comment_present",
        "trial_report_present",
        "review_trace_present",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _write_md(path: Path, summary: dict[str, object]) -> None:
    lines = [
        "# MeetingBias Validation",
        "",
        f"- Status: {summary.get('status')}",
        f"- Race Count: {summary.get('race_count')}",
        f"- Stage Counts: {summary.get('stage_counts')}",
        f"- Score Impact: {summary.get('production_score_impact')}",
        f"- Existing History Writes: {summary.get('writes_existing_history')}",
        f"- Errors: {len(summary.get('errors', []))}",
        f"- Score Impact Violations: {len(summary.get('score_impact_violations', []))}",
        f"- Trial Report Missing: {len(summary.get('trial_report_missing', []))}",
        f"- Review Trace Missing: {len(summary.get('review_trace_missing', []))}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    print(json.dumps(run_validation(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
