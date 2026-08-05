"""Read-only TrackCondition metadata root cause audit.

This diagnostic writes only reports/track_condition_metadata_* files.
It does not mutate learning JSON, analysis CSV, result CSV, or production code.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.target_result_adapter import TargetResultAdapter

TARGET_HR_ID = "hr_381e8e38d41f"
REPORT_MD = ROOT / "reports" / "track_condition_metadata_root_cause_v1.md"
TRACE_CSV = ROOT / "reports" / "track_condition_metadata_trace_v1.csv"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        if not path.exists() or not path.is_file():
            continue
        digest.update(str(path.relative_to(ROOT)).replace("\\", "/").encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def tracked_hashes() -> dict[str, str]:
    return {
        "production_json": stable_hash([ROOT / "learning" / "improvement_candidates.json"]),
        "human_review_db": stable_hash([ROOT / "learning" / "candidate_review_status.json"]),
        "analysis_csv": stable_hash(list((ROOT / "data" / "analysis").rglob("*.csv"))),
        "results_csv": stable_hash(list((ROOT / "data" / "results").rglob("*.csv"))),
    }


def status(value: Any) -> str:
    if value == "unknown":
        return "UNKNOWN"
    if value is None:
        return "MISSING"
    if value == "":
        return "EMPTY"
    return "PRESENT"


def find_analysis_paths(race_id: str) -> tuple[Path | None, Path | None]:
    entry = next((ROOT / "data" / "analysis").rglob(f"{race_id}_entry.csv"), None)
    horses = next((ROOT / "data" / "analysis").rglob(f"{race_id}_horses.csv"), None)
    return entry, horses


def result_paths(race_id: str) -> tuple[Path, Path]:
    suffix = race_id.replace("race_", "")
    return (
        ROOT / "data" / "results" / f"{race_id}_result.csv",
        ROOT / "data" / "results" / f"horse_{suffix}_result.csv",
    )


def representative_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = [
        row
        for row in records
        if row.get("case_type") in {"FN", "FP"} or row.get("fn") or row.get("fp")
    ]
    with_meta = [
        row
        for row in cases
        if all(row.get(key) not in (None, "", "unknown") for key in ["distance", "surface", "track_condition"])
    ]
    fn = [row for row in with_meta if row.get("fn")][:5]
    fp = [row for row in with_meta if row.get("fp")][:5]
    return fn + fp


def learning_record_meta(row: dict[str, Any]) -> dict[str, Any]:
    """Use already-saved learning records only; do not rerun production adapters."""
    return {
        "learning_racecourse": row.get("racecourse"),
        "learning_surface": row.get("surface"),
        "learning_distance": row.get("distance"),
        "learning_track_condition": row.get("track_condition"),
        "track_condition_score": row.get("track_condition_score"),
        "track_condition_fit": row.get("track_condition_fit"),
        "track_condition_fit_label": row.get("track_condition_fit_label"),
    }


def target_result_meta(race_id: str) -> dict[str, Any]:
    race_path, horse_path = result_paths(race_id)
    if not race_path.exists() or not horse_path.exists():
        return {"result_status": "MISSING_RESULT"}
    try:
        output = TargetResultAdapter().load(race_path, horse_path)
    except Exception as exc:  # diagnostic only
        return {"result_status": f"ERROR:{type(exc).__name__}:{exc}"}
    return {
        "result_status": "OK",
        "result_racecourse": output.get("racecourse"),
        "result_surface": output.get("surface"),
        "result_distance": output.get("distance"),
        "result_track_condition": output.get("track_condition"),
        "result_horse_count": len(output.get("horse_results") or []),
    }


def counter_state(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(Counter(status(row.get(field)) for row in rows))


def main() -> dict[str, Any]:
    before_hashes = tracked_hashes()

    learning = read_json(ROOT / "learning" / "improvement_candidates.json")
    human = read_json(ROOT / "learning" / "candidate_review_status.json")
    records = learning.get("records", [])
    hr_records = human.get("records", [])
    target_hr = next((row for row in hr_records if row.get("candidate_id") == TARGET_HR_ID), {})
    snapshot = target_hr.get("ranking_snapshot") or {}

    cases = [
        row
        for row in records
        if row.get("case_type") in {"FN", "FP"} or row.get("fn") or row.get("fp")
    ]
    with_meta = [
        row
        for row in cases
        if all(row.get(key) not in (None, "", "unknown") for key in ["distance", "surface", "track_condition"])
    ]
    missing_meta = [row for row in cases if row not in with_meta]
    track_condition_mentions = [
        row for row in cases if "TrackConditionSuitabilityEvaluator" in json.dumps(row, ensure_ascii=False)
    ]
    reps = representative_records(records)

    trace_rows: list[dict[str, Any]] = []
    for row in reps:
        race_id = row.get("race_id") or ""
        horse = row.get("horse") or ""
        entry, horses = find_analysis_paths(race_id)
        race_result, horse_result = result_paths(race_id)
        learning_meta = learning_record_meta(row)
        result = target_result_meta(race_id)
        trace_rows.append(
            {
                "race_id": race_id,
                "horse": horse,
                "case_type": row.get("case_type"),
                "decision": row.get("decision"),
                "actual_finish": row.get("actual_finish"),
                "analysis_entry": "PRESENT" if entry else "MISSING",
                "analysis_horses": "PRESENT" if horses else "MISSING",
                "result_race": "PRESENT" if race_result.exists() else "MISSING",
                "result_horse": "PRESENT" if horse_result.exists() else "MISSING",
                "learning_racecourse": row.get("racecourse"),
                "learning_distance": row.get("distance"),
                "learning_surface": row.get("surface"),
                "learning_track_condition": row.get("track_condition"),
                "learning_race_class": row.get("race_class"),
                **learning_meta,
                **result,
            }
        )

    TRACE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_CSV.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(trace_rows[0].keys()) if trace_rows else [])
        if trace_rows:
            writer.writeheader()
            writer.writerows(trace_rows)

    current_equivalent = {
        "case_records": len(cases),
        "with_distance_surface_track_condition": len(with_meta),
        "missing_distance_surface_track_condition": len(missing_meta),
        "with_meta_fn": sum(1 for row in with_meta if row.get("fn")),
        "with_meta_fp": sum(1 for row in with_meta if row.get("fp")),
        "with_meta_races": len({row.get("race_id") for row in with_meta}),
        "track_condition_mentions_current": len(track_condition_mentions),
        "distance_state": counter_state(cases, "distance"),
        "surface_state": counter_state(cases, "surface"),
        "track_condition_state": counter_state(cases, "track_condition"),
        "race_class_state": counter_state(cases, "race_class"),
        "missing_versions": dict(Counter(row.get("candidate_generation_version") for row in missing_meta)),
        "with_meta_versions": dict(Counter(row.get("candidate_generation_version") for row in with_meta)),
    }

    lines = [
        "# TrackCondition Metadata Root Cause Analysis v1.0",
        "",
        "## Executive Summary",
        "",
        f"- Target Human Review candidate: `{TARGET_HR_ID}` / `{target_hr.get('candidate_name')}`",
        f"- occurrences=90 meaning: single archived Human Review candidate snapshot occurrences, not multiple candidates.",
        f"- Archived snapshot active: `{target_hr.get('ranking_active')}`",
        f"- Archived reason: `{target_hr.get('archive_reason')}`",
        f"- Archived FN / FP: {snapshot.get('fn_count')} / {snapshot.get('fp_count')}",
        f"- Archived race_count: {snapshot.get('race_count')}",
        "- Root cause classification: `LEGACY_SCHEMA_ONLY` with `REVIEW_SCHEMA_OMISSION` in the old Learning Candidate input.",
        "- Production Evaluator impact: none. Current learning records contain distance/surface/track_condition for the equivalent 90 FN/FP cases.",
        "",
        "## Target Candidate",
        "",
        "| field | value |",
        "|---|---|",
        f"| candidate_id | {target_hr.get('candidate_id')} |",
        f"| candidate_name | {target_hr.get('candidate_name')} |",
        f"| candidate_type | {target_hr.get('candidate_type')} |",
        f"| priority | {target_hr.get('priority')} |",
        f"| ranking_score | {target_hr.get('ranking_score')} |",
        f"| status | {target_hr.get('status')} |",
        f"| status_source | {target_hr.get('status_source', 'LEGACY_UNKNOWN')} |",
        f"| occurrences | {snapshot.get('occurrences')} |",
        f"| FN | {snapshot.get('fn_count')} |",
        f"| FP | {snapshot.get('fp_count')} |",
        f"| race_count | {snapshot.get('race_count')} |",
        f"| distances | {snapshot.get('distances')} |",
        f"| surfaces | {snapshot.get('surfaces')} |",
        f"| track_conditions | {snapshot.get('track_conditions')} |",
        f"| related_evaluators | {snapshot.get('related_evaluators')} |",
        f"| created_at | {target_hr.get('created_at')} |",
        f"| updated_at | {target_hr.get('updated_at')} |",
        "",
        "## Current Data Comparison",
        "",
        f"- Current FN/FP case records: {current_equivalent['case_records']}",
        f"- Current records with distance/surface/track_condition: {current_equivalent['with_distance_surface_track_condition']}",
        f"- Current records missing any of those fields: {current_equivalent['missing_distance_surface_track_condition']}",
        f"- Current with-meta FN/FP/races: {current_equivalent['with_meta_fn']} / {current_equivalent['with_meta_fp']} / {current_equivalent['with_meta_races']}",
        f"- Current TrackConditionSuitabilityEvaluator mentions: {current_equivalent['track_condition_mentions_current']}",
        f"- Distance state: {current_equivalent['distance_state']}",
        f"- Surface state: {current_equivalent['surface_state']}",
        f"- Track condition state: {current_equivalent['track_condition_state']}",
        f"- Race class state: {current_equivalent['race_class_state']}",
        f"- With-meta versions: {current_equivalent['with_meta_versions']}",
        f"- Missing-meta versions: {current_equivalent['missing_versions']}",
        "",
        "## Unknown First Occurrence",
        "",
        "- HumanReviewEngine only copies ranking item fields into `ranking_snapshot`.",
        "- LearningCandidateRankingEngine reads `record['distance']`, `record['surface']`, `record['track_condition']` via `_race_meta()`.",
        "- `_race_meta()` converts `None` or empty values to `unknown`.",
        "- Therefore the first active fallback location is `engine/learning_candidate_ranking_engine.py::_race_meta`, lines around 398-412.",
        "- For this archived candidate, the upstream old Learning Candidate records that produced the snapshot were missing race-level metadata; the exact old 90 row set is not retained in the Human Review snapshot.",
        "",
        "## Representative Trace",
        "",
        f"See `{TRACE_CSV.relative_to(ROOT)}`.",
        "",
        "| race_id | horse | case | learning meta | learning TrackCondition output | result race meta |",
        "|---|---|---|---|---|---|",
    ]
    for row in trace_rows:
        lines.append(
            "| {race_id} | {horse} | {case_type} | {learning_surface}/{learning_distance}/{learning_track_condition} "
            "| score={track_condition_score} fit={track_condition_fit}/{track_condition_fit_label} "
            "| {result_surface}/{result_distance}/{result_track_condition} |".format(**row)
        )

    lines.extend(
        [
            "",
            "## Field Mapping",
            "",
            "| Concept | Current source field | Legacy problem | Correct target |",
            "|---|---|---|---|",
            "| racecourse | `record.racecourse`; fallback from `race_id` | available even in archived snapshot | `ranking_snapshot.racecourses` |",
            "| distance | `record.distance` | old records did not carry it | `ranking_snapshot.distances` |",
            "| surface | `record.surface` | old records did not carry it | `ranking_snapshot.surfaces` |",
            "| track_condition | `record.track_condition` | old records did not carry it | `ranking_snapshot.track_conditions` |",
            "| race_class | `record.race_class` | still not supplied in current records | `ranking_snapshot.race_classes` |",
            "",
            "## Data Path",
            "",
            "1. analysis CSV / horse history: available to TargetTrialAdapter.",
            "2. TargetTrialAdapter: horse-level ranking rows contain racecourse/surface/distance/track_condition and TrackConditionSuitabilityEvaluator score.",
            "3. Result CSV / TargetResultAdapter: older result files provide horse results, but race-level surface/distance/track_condition may be missing after adapter conversion.",
            "4. Review / Learning Candidate input: old pre-phase_e_step4 records omitted race metadata.",
            "5. LearningCandidateRankingEngine: `_race_meta()` converted missing metadata to `unknown`.",
            "6. HumanReviewEngine: copied already-unknown values into `ranking_snapshot`.",
            "",
            "## Impact",
            "",
            "- Production scoring: no impact.",
            "- TrackConditionSuitabilityEvaluator: no evidence of evaluation-input failure in current saved learning records.",
            "- Review/Learning explainability: affected for archived Human Review candidate only.",
            "- Ranking/Priority: archived TrackConditionSuitabilityEvaluator candidate used unconditioned metadata, but it is no longer active.",
            "- Shadow target selection: historical archived candidate is unsafe to use directly because condition segmentation is lost.",
            "",
            "## Minimal Fix Proposal (not implemented)",
            "",
            "1. Additive metadata propagation check in Learning Candidate generation/input layer: ensure each FN/FP record stores `racecourse`, `distance`, `surface`, `track_condition`, and optionally `race_class` when available from horse-level adapter output or review row.",
            "2. Add Ranking validator warning when an active Evaluator candidate has occurrences > 0 and all `distances/surfaces/track_conditions` are unknown.",
            "3. Do not migrate archived `hr_381e8e38d41f` automatically; create a new candidate from regenerated current records if TrackCondition becomes active again.",
            "",
            "## Shadow Validation Plan",
            "",
            "- Compare unknown rate before/after metadata propagation.",
            "- Compare distance/surface/track_condition acquisition rates.",
            "- Rebuild candidates from the same review set in a temporary output directory.",
            "- Confirm BUY / Score / Decision / Evaluator outputs are unchanged.",
            "- Confirm Human Review display improves without rewriting existing legacy records.",
            "",
            "## Implementation Gate",
            "",
            "Proceed only if the next implementation stays in Review/Learning metadata propagation, preserves schema compatibility, writes no inferred legacy values, and validates before/after unknown rate in a temporary repository.",
            "",
            "## Hash Verification",
            "",
            f"- Before hashes: {before_hashes}",
        ]
    )

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    after_hashes = tracked_hashes()
    with REPORT_MD.open("a", encoding="utf-8") as fh:
        fh.write(f"- After hashes: {after_hashes}\n")
        fh.write(f"- Hash changed: {before_hashes != after_hashes}\n")

    return {
        "report": str(REPORT_MD),
        "trace": str(TRACE_CSV),
        "target_candidate": target_hr.get("candidate_name"),
        "occurrences": snapshot.get("occurrences"),
        "fn": snapshot.get("fn_count"),
        "fp": snapshot.get("fp_count"),
        "current_with_meta": len(with_meta),
        "current_missing_meta": len(missing_meta),
        "hash_changed": before_hashes != after_hashes,
    }


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
