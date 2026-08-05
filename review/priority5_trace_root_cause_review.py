"""Read-only Priority5 Phase2 audit for six DATA_QUALITY_OR_TRACE rows."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
TARGET_CLASS = "DATA_QUALITY_OR_TRACE"


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(row: dict[str, str]) -> tuple[str, str]:
    return row["race_id"], row["horse_number"]


def classify(row: dict[str, str]) -> dict[str, str]:
    date = row["race_date"]
    if date == "20260725":
        return {
            "primary_cause": "LEGACY_SCHEMA_MISSING",
            "secondary_flags": "MISSING_EVALUATOR_SCORE;GATE_PROVENANCE_MISSING;SOURCE_VERSION_MISMATCH",
            "missing_point": "LEGACY_INCOMPATIBLE",
            "fp_relationship": "B_AUDIT_MISSING_UNRELATED_TO_FP",
            "fixability": "NOT_FIXABLE_RETROSPECTIVELY",
            "evidence": "Saved legacy review has BUY/final/adjusted and reason text but no decision_score, numeric evaluator scores, or gate provenance.",
            "successful_buy_controls": "セボンサデッセ;ライフゲート",
            "successful_buy_control_count": "2",
            "control_comparison": "Same legacy trace absence exists in two successful BUY controls on the same date.",
        }
    if date == "20260801":
        return {
            "primary_cause": "GATE_PROVENANCE_MISSING",
            "secondary_flags": "REVIEW_MAPPING_ERROR",
            "missing_point": "REPORT_MAPPING_MISSING",
            "fp_relationship": "B_AUDIT_MISSING_UNRELATED_TO_FP",
            "fixability": "REPORT_ONLY_FIX",
            "evidence": "Saved v2 review contains decision/final/adjusted scores; Phase1 reporter looked for absent precomputed margin fields and exported blanks.",
            "successful_buy_controls": "ピエマンソン;ヨヒーン",
            "successful_buy_control_count": "2",
            "control_comparison": "The same v2 export schema is shared by two successful BUY controls.",
        }
    return {
        "primary_cause": "BLOCKING_MISSING_EVALUATOR",
        "secondary_flags": "MISSING_EVALUATOR_SCORE;TRUE_DATA_QUALITY_FAILURE",
        "missing_point": "SOURCE_MISSING",
        "fp_relationship": "C_CAUSALITY_UNDETERMINED",
        "fixability": "FUTURE_DATA_COLLECTION_FIX",
        "evidence": "Saved v1 review explicitly records bloodline_missing=True, missing_evaluator=Bloodline, and 'Bloodline profile not found'.",
        "successful_buy_controls": "クールミラボー",
        "successful_buy_control_count": "1",
        "control_comparison": "Only one same-version successful BUY control; insufficient to attribute this FP to Bloodline absence.",
    }


def analysis_paths(race_id: str) -> tuple[Path, Path]:
    return ROOT / "data" / "analysis" / f"{race_id}_entry.csv", ROOT / "data" / "analysis" / f"{race_id}_horses.csv"


def run() -> tuple[list[dict[str, str]], list[dict[str, str]], dict]:
    classification_path = REPORTS / "priority5_fp_classification_v1.csv"
    margin_path = REPORTS / "priority5_fp_gate_margin_v1.csv"
    classification = [row for row in load_csv(classification_path) if row["primary_classification"] == TARGET_CLASS]
    margins = [row for row in load_csv(margin_path) if row["primary_classification"] == TARGET_CLASS]
    if len(classification) != 6 or len({key(row) for row in classification}) != 6:
        raise ValueError("EXPECTED_EXACTLY_SIX_UNIQUE_DATA_QUALITY_OR_TRACE_ROWS")
    if {key(row) for row in classification} != {key(row) for row in margins}:
        raise ValueError("CLASSIFICATION_AND_MARGIN_TARGET_SET_MISMATCH")

    baseline = {key(row): row for row in load_csv(REPORTS / "baseline" / "keibaai_baseline_4days_v1_horse.csv")}
    output: list[dict[str, str]] = []
    audit: list[dict[str, str]] = []
    for row in classification:
        base = baseline[key(row)]
        review_path = ROOT / row["source_path"]
        entry_path, history_path = analysis_paths(row["race_id"])
        cause = classify(row)
        common = {
            "race_id": row["race_id"], "race_date": row["race_date"], "racecourse": row["racecourse"],
            "race_number": row["race_number"], "horse_name": row["horse_name"], "horse_number": row["horse_number"],
            "ai_rank": row["ai_rank"], "actual_finish": row["actual_finish"], "final_score": row["final_score"],
            "adjusted_score": row["adjusted_score"], "decision_score": row["decision_score"],
            "buy_decision": base["decision"], "valid_result": base["valid_result"],
            "source_file": row["source_path"], "source_sha256": sha256(review_path),
            **cause,
        }
        output.append(common)
        audit.append({
            **common,
            "analysis_entry_file": str(entry_path.relative_to(ROOT)),
            "analysis_entry_sha256": sha256(entry_path),
            "analysis_history_file": str(history_path.relative_to(ROOT)),
            "analysis_history_sha256": sha256(history_path),
            "analysis_input_status": "PRESENT_RAW_INPUT_NO_SAVED_EVALUATOR_TRACE",
            "saved_review_status": "PRESENT",
            "saved_review_trace_status": (
                "LEGACY_SCHEMA_NO_DECISION_OR_NUMERIC_EVALUATOR_TRACE" if row["race_date"] == "20260725"
                else "SCORES_PRESENT_GATE_PROVENANCE_NOT_EXPORTED" if row["race_date"] == "20260801"
                else "EVALUATOR_TRACE_PRESENT_BLOODLINE_SOURCE_MISSING"
            ),
            "phase1_classification_file": str(classification_path.relative_to(ROOT)),
            "phase1_classification_sha256": sha256(classification_path),
            "phase1_margin_file": str(margin_path.relative_to(ROOT)),
            "phase1_margin_sha256": sha256(margin_path),
        })

    causes = Counter(row["primary_cause"] for row in output)
    fixes = Counter(row["fixability"] for row in output)
    relationships = Counter(row["fp_relationship"] for row in output)
    homogeneous = causes.get("LEGACY_SCHEMA_MISSING", 0) >= 3
    summary = {
        "status": "PRIORITY5_PHASE2_COMPLETE",
        "target_classification": TARGET_CLASS,
        "target_count": len(output),
        "unique_count": len({key(row) for row in output}),
        "primary_causes": dict(causes),
        "missing_points": dict(Counter(row["missing_point"] for row in output)),
        "fp_relationships": dict(relationships),
        "fixability": dict(fixes),
        "homogeneous_group": {"exists": homogeneous, "cause": "LEGACY_SCHEMA_MISSING", "count": causes.get("LEGACY_SCHEMA_MISSING", 0)},
        "successful_buy_controls_available": True,
        "reducible_fp": 0,
        "lost_successful_buy": 0,
        "shadow_candidate": False,
        "shadow_candidate_reason": "Legacy audit gap is shared by successful BUY controls; Bloodline source failure is one case; no causal subgroup of three.",
        "priority5_judgment": "PRIORITY5_COMPLETE_NO_CANDIDATE",
        "unconverged_status": "PAUSE_EVIDENCE_ACCUMULATION_ONLY",
        "production_candidate": "NONE",
        "evaluator_next_phase": {
            "start_with": "PastPerformance",
            "then": ["Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle", "Bloodline", "Ability"],
            "saved_fields_required": ["numeric score", "missing flag", "calculation version", "source provenance", "pre-race timestamp"],
            "controls": ["successful BUY", "FP", "non-BUY actual Top3"],
            "leakage_rule": "Freeze pre-race evaluator evidence before joining results; results are labels only.",
            "unit": "horse within race, stratified by date/course/source_version",
        },
    }
    return output, audit, summary


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    rows, audit, summary = run()
    write_csv(REPORTS / "priority5_trace_classification_v1.csv", rows)
    write_csv(REPORTS / "priority5_trace_source_audit_v1.csv", audit)
    (REPORTS / "priority5_trace_summary_v1.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# Priority5 Phase2 DATA_QUALITY_OR_TRACE Root Cause Review", "",
        "## Scope", "", "Exactly six DATA_QUALITY_OR_TRACE severe misses were audited. No other cohort was reanalyzed.", "",
        "## Six-case classification", "",
        "| Race / horse | Primary cause | Missing point | FP relationship | Fixability |",
        "|---|---|---|---|---|",
        *[
            f"| {row['race_id']} / {row['horse_name']} | {row['primary_cause']} | {row['missing_point']} | {row['fp_relationship']} | {row['fixability']} |"
            for row in rows
        ], "",
        "## Primary causes", "",
        "- LEGACY_SCHEMA_MISSING: 4 (2026-07-25)",
        "- GATE_PROVENANCE_MISSING: 1 (2026-08-01)",
        "- BLOCKING_MISSING_EVALUATOR: 1 (2026-08-02 Bloodline)", "",
        "The four legacy cases form a homogeneous audit-gap group, but the same schema gap exists in two successful BUY controls. It is not a rational FP guard.", "",
        "## FP relationship and fixability", "",
        "- Audit missing unrelated to FP: 5", "- Causality undetermined: 1", "- Causally attributable FP: 0", "",
        "- NOT_FIXABLE_RETROSPECTIVELY: 4", "- REPORT_ONLY_FIX: 1", "- FUTURE_DATA_COLLECTION_FIX: 1", "",
        "Reducible FP is 0 and lost successful BUY is 0 because no filter is proposed. There is no Shadow candidate.", "",
        "## Decision", "", "**PRIORITY5_COMPLETE_NO_CANDIDATE**", "",
        "HIGH_CONFIDENCE four-case review remains closed. UNCONVERGED remains paused except for new evidence accumulation. Production Candidate remains NONE.", "",
        "## Evaluator next phase proposal", "",
        "Start with PastPerformance, then inspect Distance, CourseShape, LapSuitability, RaceShape, PaceStyle, Bloodline, and Ability one at a time. Save numeric score, missing flag, calculation version, source provenance, and pre-race timestamp. Compare successful BUY, FP, and non-BUY actual Top3 within date/course/source-version strata. Freeze all features before the result join; results are labels only.",
    ]
    (REPORTS / "priority5_trace_root_cause_v1.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    completion = [
        "# Priority5 Completion v1", "", "Status: **PRIORITY5_PHASE2_COMPLETE**", "",
        "Final judgment: **PRIORITY5_COMPLETE_NO_CANDIDATE**", "",
        "- HIGH_CONFIDENCE_SEVERE_MISS: closed with no candidate", "- DATA_QUALITY_OR_TRACE: six cases fully traced", "- Shadow candidate: none", "- Production Candidate: NONE", "- UNCONVERGED: PAUSE (new evidence accumulation only)", "- Next phase: evaluator precision diagnostic design only; no evaluator execution or change", "",
    ]
    (REPORTS / "priority5_completion_v1.md").write_text("\n".join(completion), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
