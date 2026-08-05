"""Validate BUY v1.0 RC1 production promotion.

This validator is diagnostic only. It runs the normal TargetTrialAdapter path
with RC1 ON and with explicit RC1 OFF, verifies that scores/evaluator outputs
are unchanged, and confirms that production BUY is capped by RC1 behavior.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.buy_v1_rc1_engine import BUYV1RC1Engine
from evaluation.target_trial_adapter import TargetTrialAdapter


OUT_DIR = ROOT / "reports" / "buy_v1_rc1_production_promotion_validation"
ANALYSIS_DIR = ROOT / "data" / "analysis"

RACE_IDS = [
    "race_20260801_sapporo_10R",
    "race_20260801_sapporo_11R",
    "race_20260801_niigata_6R",
    "race_20260801_niigata_7R",
    "race_20260801_niigata_8R",
    "race_20260801_chuukyou_6R",
    "race_20260801_chuukyou_7R",
    "race_20260801_chuukyou_8R",
]

SCORE_FIELDS = [
    "final_score",
    "adjusted_score",
    "decision_score",
    "distance_score",
    "course_shape_score",
    "race_shape_score",
    "shape_score",
    "track_bias_score",
    "pace_style_score",
    "running_style_score",
    "lap_suitability_score",
    "lap_score",
    "blood_score",
    "bloodline_score",
    "weight_score",
    "condition_score",
    "track_condition_score",
    "past_performance_score",
]

HORSE_FIELDS = [
    "race_id",
    "horse_number",
    "horse_name",
    "ai_rank",
    "legacy_decision",
    "production_decision",
    "rc1_decision",
    "production_buy",
    "legacy_buy",
    "rc1_status",
    "rc1_race_state",
    "final_score",
    "adjusted_score",
    "decision_score",
    "score_diff",
    "legacy_to_production_changed",
    "change_reason",
]

RACE_FIELDS = [
    "race_id",
    "race_decision",
    "race_confidence",
    "legacy_buy_count",
    "production_buy_count",
    "rc1_race_state",
    "rc1_candidate_count",
    "rc1_unconverged_candidate_count",
    "max3_ok",
    "legacy_removed_horses",
    "production_buy_horses",
]


def _noop_adapter(enabled: bool) -> TargetTrialAdapter:
    adapter = TargetTrialAdapter(buy_v1_rc1_enabled=enabled)
    adapter.trial_report_exporter.export = lambda *a, **k: {
        "trial_report": None,
        "trial_report_summary": {},
        "trial_report_horses": [],
    }
    adapter.review_recorder.record = lambda *a, **k: {
        "prediction_snapshot": {},
        "prediction_time": "",
        "prediction_id": "",
        "review_record": {},
        "review_status": "validator_no_write",
        "review_ready": False,
    }
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
    }
    adapter.learning_phase2_writer.write_analysis = lambda *a, **k: {
        "enabled": False,
        "saved": False,
        "record_count": 0,
        "storage_path": "",
    }
    return adapter


def _race_paths(race_id: str) -> tuple[Path, Path]:
    return (
        ANALYSIS_DIR / f"{race_id}_entry.csv",
        ANALYSIS_DIR / f"{race_id}_horses.csv",
    )


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_number(left: Any, right: Any) -> bool:
    lnum = _safe_float(left)
    rnum = _safe_float(right)
    if lnum is None and rnum is None:
        return True
    if lnum is None or rnum is None:
        return False
    return abs(lnum - rnum) < 0.000001


def _ranked(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in result.get("ranked_results", []) or []
        if isinstance(row, dict)
    ]


def _by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("horse_name")): row
        for row in rows
        if row.get("horse_name")
    }


def _rc1_records_from_off_rows(race_id: str, legacy_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    engine = BUYV1RC1Engine(enabled=True)
    shadow_rows = []
    for rank, row in enumerate(legacy_rows, start=1):
        clone = dict(row)
        clone["ai_rank"] = rank
        clone["race_id"] = race_id
        shadow_rows.append(clone)
    result = engine.evaluate(race_output={"race_id": race_id}, horses=shadow_rows)
    return {
        row.get("horse_name"): row
        for row in result.get("horse_records", [])
        if row.get("horse_name")
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def validate() -> dict[str, Any]:
    adapter_on = _noop_adapter(True)
    adapter_off = _noop_adapter(False)
    race_rows: list[dict[str, Any]] = []
    horse_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    score_diff_count = 0
    legacy_diff_count = 0
    max3_violations = []
    rc1_mismatch_count = 0

    for race_id in RACE_IDS:
        entry, horses = _race_paths(race_id)
        if not entry.exists() or not horses.exists():
            errors.append({"race_id": race_id, "error": "missing entry/horses csv"})
            continue

        try:
            off = adapter_off.run(str(entry), horse_data_csv_path=str(horses))
            on = adapter_on.run(str(entry), horse_data_csv_path=str(horses))
        except Exception as exc:  # pragma: no cover - runtime diagnostic path
            errors.append({"race_id": race_id, "error": str(exc)})
            continue

        off_rows = _ranked(off)
        on_rows = _ranked(on)
        off_map = _by_name(off_rows)
        rc1_reference = _rc1_records_from_off_rows(race_id, off_rows)
        production_buy = []
        legacy_buy = []
        removed = []

        for rank, on_row in enumerate(on_rows, start=1):
            name = str(on_row.get("horse_name") or "")
            off_row = off_map.get(name, {})
            rc1_record = rc1_reference.get(name, {})
            score_diff = any(
                not _same_number(on_row.get(field), off_row.get(field))
                for field in SCORE_FIELDS
                if field in on_row or field in off_row
            )
            if score_diff:
                score_diff_count += 1
            legacy_decision = on_row.get("legacy_decision")
            if legacy_decision != off_row.get("decision"):
                legacy_diff_count += 1
            if rc1_record and on_row.get("decision") != rc1_record.get("rc1_decision"):
                rc1_mismatch_count += 1

            legacy_is_buy = off_row.get("decision") == "BUY"
            production_is_buy = on_row.get("decision") == "BUY"
            if legacy_is_buy:
                legacy_buy.append(name)
            if production_is_buy:
                production_buy.append(name)
            if legacy_is_buy and not production_is_buy:
                removed.append(name)

            horse_rows.append(
                {
                    "race_id": race_id,
                    "horse_number": on_row.get("horse_number"),
                    "horse_name": name,
                    "ai_rank": rank,
                    "legacy_decision": legacy_decision,
                    "production_decision": on_row.get("decision"),
                    "rc1_decision": on_row.get("buy_v1_rc1_decision"),
                    "production_buy": production_is_buy,
                    "legacy_buy": legacy_is_buy,
                    "rc1_status": on_row.get("buy_v1_rc1_status"),
                    "rc1_race_state": on_row.get("buy_v1_rc1_race_state"),
                    "final_score": on_row.get("final_score"),
                    "adjusted_score": on_row.get("adjusted_score"),
                    "decision_score": on_row.get("decision_score"),
                    "score_diff": score_diff,
                    "legacy_to_production_changed": off_row.get("decision") != on_row.get("decision"),
                    "change_reason": on_row.get("buy_v1_rc1_reason"),
                }
            )

        buy_v1_summary = on.get("buy_v1_rc1_summary", {})
        race_state = on.get("buy_v1_rc1_race_state", "")
        max3_ok = len(production_buy) <= 3
        if not max3_ok:
            max3_violations.append(race_id)
        race_rows.append(
            {
                "race_id": race_id,
                "race_decision": on.get("race_decision"),
                "race_confidence": on.get("race_confidence"),
                "legacy_buy_count": len(legacy_buy),
                "production_buy_count": len(production_buy),
                "rc1_race_state": race_state,
                "rc1_candidate_count": buy_v1_summary.get("candidate_count"),
                "rc1_unconverged_candidate_count": buy_v1_summary.get("unconverged_candidate_count"),
                "max3_ok": max3_ok,
                "legacy_removed_horses": "; ".join(removed),
                "production_buy_horses": "; ".join(production_buy),
            }
        )

    race_state_counts = Counter(row.get("rc1_race_state") for row in race_rows)
    summary = {
        "status": "PASS"
        if not errors and not max3_violations and score_diff_count == 0 and legacy_diff_count == 0 and rc1_mismatch_count == 0
        else "FAIL",
        "race_count": len(race_rows),
        "horse_count": len(horse_rows),
        "errors": errors,
        "max3_violations": max3_violations,
        "production_buy": sum(1 for row in horse_rows if row.get("production_buy")),
        "legacy_buy": sum(1 for row in horse_rows if row.get("legacy_buy")),
        "legacy_removed": sum(
            1 for row in horse_rows if row.get("legacy_buy") and not row.get("production_buy")
        ),
        "score_diff_count": score_diff_count,
        "legacy_decision_diff_count": legacy_diff_count,
        "rc1_mismatch_count": rc1_mismatch_count,
        "race_state_counts": dict(race_state_counts),
        "buy_by_race": {
            row["race_id"]: row["production_buy_count"]
            for row in race_rows
        },
    }
    return {
        "summary": summary,
        "race_rows": race_rows,
        "horse_rows": horse_rows,
    }


def write_report(result: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = result["summary"]
    write_csv(OUT_DIR / "race_comparison.csv", result["race_rows"], RACE_FIELDS)
    write_csv(OUT_DIR / "horse_comparison.csv", result["horse_rows"], HORSE_FIELDS)
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# BUY V1 RC1 Production Promotion Validation",
        "",
        f"- Status: {summary['status']}",
        f"- Race count: {summary['race_count']}",
        f"- Horse count: {summary['horse_count']}",
        f"- Legacy BUY: {summary['legacy_buy']}",
        f"- Production BUY: {summary['production_buy']}",
        f"- Legacy removed by RC1: {summary['legacy_removed']}",
        f"- Score diff count: {summary['score_diff_count']}",
        f"- Legacy decision preservation diff count: {summary['legacy_decision_diff_count']}",
        f"- RC1 mismatch count: {summary['rc1_mismatch_count']}",
        f"- Max3 violations: {len(summary['max3_violations'])}",
        f"- Race states: {summary['race_state_counts']}",
        "",
        "## BUY By Race",
    ]
    for race_id, count in summary["buy_by_race"].items():
        lines.append(f"- {race_id}: {count}")
    if summary["errors"]:
        lines.extend(["", "## Errors"])
        for error in summary["errors"]:
            lines.append(f"- {error}")
    (OUT_DIR / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    result = validate()
    write_report(result)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
