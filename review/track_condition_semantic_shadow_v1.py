"""TrackCondition Semantic Shadow v1.

This module is deliberately shadow-only.  It reuses the approved TARGET bulk
adapter and the existing in-memory Trial engine path, changing only the
target-day track-condition value passed to the evaluators: ``None`` means
unknown.  It never writes to production assets or reads result CSV files.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.target_trial_adapter import TargetTrialAdapter
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import history_from_past_races, run_engine_from_objects


OUT = ROOT / "reports" / "track_condition_semantic_shadow_v1"
MAY_DATES = ("20260502", "20260503", "20260509", "20260510", "20260516", "20260517", "20260523", "20260524", "20260530", "20260531")
EXPECTED = {
    "dates": 10, "races": 192, "horses": 2645, "control_buys": 181,
    "shadow_buys": 133, "common_buys": 66, "control_only_buys": 115,
    "shadow_only_buys": 67, "track_condition_score_changed": 2635,
    "past_performance_score_changed": 2161, "final_score_changed": 2635,
    "ranking_changed": 600, "race_decision_changed": 125,
    "buy_changed_races": 109,
}
PROTECTED = (
    "evaluation/target_trial_adapter.py",
    "review/target_bulk_prediction_input_adapter_v1.py",
    "review/target_bulk_prediction_input_shadow_v1.py",
    "docs/independent_race_selection_prospective_protocol_v1.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _base_defaults(entry: Any) -> dict[str, Any]:
    return {
        "racecourse": entry.racecourse, "surface": entry.surface, "distance": entry.distance,
        "track_condition": None, "track_bias": None, "inside_bias": None, "outside_bias": None,
        "race_date": entry.race_date, "race_number": entry.race_number,
        "meeting_stage": None, "meeting_week": None, "meeting_day": None,
    }


def _histories(race_bundle: Any) -> dict[str, Any]:
    grouped: dict[str, list[Any]] = {}
    for run in race_bundle.past_races:
        grouped.setdefault(run.horse_name, []).append(run)
    return {name: history_from_past_races(name, runs) for name, runs in grouped.items()}


def shadow_defaults(control_defaults: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic variant: target-day condition is unknown only."""
    result = copy.deepcopy(control_defaults)
    result["track_condition"] = None
    return result


def run_race_pair(race_bundle: Any) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    """Run control and semantic shadow through the identical existing engine."""
    histories = _histories(race_bundle)
    trial = TargetTrialAdapter(enable_learning_candidate_engine=False)
    control_defaults = trial._enrich_race_defaults(
        _base_defaults(race_bundle.today_entries[0]), copy.deepcopy(race_bundle.today_entries), histories
    )
    field_history_track_condition = control_defaults.get("track_condition")
    if not field_history_track_condition:
        raise RuntimeError(f"FIELD_HISTORY_TRACK_CONDITION_MISSING:{race_bundle.race_id}")
    control = run_engine_from_objects(
        copy.deepcopy(race_bundle.today_entries), copy.deepcopy(histories), copy.deepcopy(control_defaults)
    )
    shadow = run_engine_from_objects(
        copy.deepcopy(race_bundle.today_entries), copy.deepcopy(histories), shadow_defaults(control_defaults)
    )
    return control, shadow, field_history_track_condition


def is_buy(row: dict[str, Any]) -> bool:
    return bool(row.get("buy_v1_rc1_buy"))


def _float_changed(left: Any, right: Any) -> bool:
    return left != right


def _safe(value: Any) -> Any:
    return value if value is not None else ""


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def execute() -> dict[str, Any]:
    if OUT.exists():
        raise FileExistsError(f"exclusive-create output already exists: {OUT}")
    before = {relative: sha256(ROOT / relative) for relative in PROTECTED}
    raw_root = ROOT / "data" / "raw" / "prediction_input"
    manifest_sources: list[dict[str, Any]] = []
    horse_rows: list[dict[str, Any]] = []
    race_rows: list[dict[str, Any]] = []
    all_control_buys: set[tuple[str, int]] = set()
    all_shadow_buys: set[tuple[str, int]] = set()
    field_conditions: Counter[str] = Counter()
    score_changes = Counter()
    race_decision_changed = 0
    buy_changed_races = 0
    races = 0

    adapter = TargetBulkPredictionInputAdapterV1()
    for date in MAY_DATES:
        paths = {kind: raw_root / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
        for kind, path in paths.items():
            if not path.is_file():
                raise FileNotFoundError(path)
            manifest_sources.append({"date": date, "kind": kind, "path": str(path.relative_to(ROOT)), "sha256": sha256(path), "bytes": path.stat().st_size})
        bundle = adapter.load(paths["DG"], paths["DE"], paths["DS"])
        for race_id, race_bundle in bundle.races.items():
            control, shadow, field_condition = run_race_pair(race_bundle)
            field_conditions[str(field_condition)] += 1
            control_map = {int(row["horse_number"]): row for row in control["ranked_results"]}
            shadow_map = {int(row["horse_number"]): row for row in shadow["ranked_results"]}
            if set(control_map) != set(shadow_map):
                raise RuntimeError(f"CONTROL_SHADOW_HORSE_SET_MISMATCH:{race_id}")
            control_buys = {number for number, row in control_map.items() if is_buy(row)}
            shadow_buys = {number for number, row in shadow_map.items() if is_buy(row)}
            if control_buys != shadow_buys:
                buy_changed_races += 1
            if control["race_decision"] != shadow["race_decision"]:
                race_decision_changed += 1
            entry = race_bundle.today_entries[0]
            race_rows.append({
                "date": date, "race_id": race_id, "venue": entry.racecourse, "race_number": entry.race_number,
                "field_history_track_condition": field_condition, "race_track_condition_shadow": "UNKNOWN",
                "control_race_decision": control["race_decision"], "shadow_race_decision": shadow["race_decision"],
                "race_decision_changed": control["race_decision"] != shadow["race_decision"],
                "control_buy_count": len(control_buys), "shadow_buy_count": len(shadow_buys),
                "buy_set_changed": control_buys != shadow_buys,
                "manual_track_bias_used": False,
            })
            for number in sorted(control_map):
                left, right = control_map[number], shadow_map[number]
                tc_changed = _float_changed(left.get("track_condition_score"), right.get("track_condition_score"))
                pp_changed = _float_changed(left.get("past_performance_score"), right.get("past_performance_score"))
                final_changed = _float_changed(left.get("adjusted_score"), right.get("adjusted_score"))
                rank_changed = left.get("rank") != right.get("rank")
                score_changes["track_condition_score_changed"] += int(tc_changed)
                score_changes["past_performance_score_changed"] += int(pp_changed)
                score_changes["final_score_changed"] += int(final_changed)
                score_changes["ranking_changed"] += int(rank_changed)
                if tc_changed and pp_changed:
                    mechanism = "TRACK_CONDITION_AND_PAST_PERFORMANCE"
                elif tc_changed:
                    mechanism = "TRACK_CONDITION_ONLY"
                elif pp_changed:
                    mechanism = "PAST_PERFORMANCE_ONLY"
                else:
                    mechanism = "UNCHANGED"
                row = {
                    "date": date, "race_id": race_id, "venue": entry.racecourse, "race_number": entry.race_number,
                    "horse_number": number, "horse_name": left.get("horse_name"),
                    "race_track_condition": "UNKNOWN", "field_history_track_condition": field_condition,
                    "historical_track_condition_preserved": True,
                    "control_track_condition_score": left.get("track_condition_score"), "shadow_track_condition_score": right.get("track_condition_score"),
                    "control_past_performance_score": left.get("past_performance_score"), "shadow_past_performance_score": right.get("past_performance_score"),
                    "control_final_score": left.get("adjusted_score"), "shadow_final_score": right.get("adjusted_score"),
                    "control_rank": left.get("rank"), "shadow_rank": right.get("rank"),
                    "control_decision": left.get("decision"), "shadow_decision": right.get("decision"),
                    "control_buy": is_buy(left), "shadow_buy": is_buy(right),
                    "mechanism_classification": mechanism,
                    "manual_track_bias_used": False,
                }
                horse_rows.append(row)
                if row["control_buy"]:
                    all_control_buys.add((race_id, number))
                if row["shadow_buy"]:
                    all_shadow_buys.add((race_id, number))
            races += 1

    common = all_control_buys & all_shadow_buys
    actual = {
        "dates": len(MAY_DATES), "races": races, "horses": len(horse_rows),
        "control_buys": len(all_control_buys), "shadow_buys": len(all_shadow_buys), "common_buys": len(common),
        "control_only_buys": len(all_control_buys - all_shadow_buys), "shadow_only_buys": len(all_shadow_buys - all_control_buys),
        **dict(score_changes), "race_decision_changed": race_decision_changed, "buy_changed_races": buy_changed_races,
    }
    mismatches = {key: {"expected": value, "actual": actual.get(key)} for key, value in EXPECTED.items() if actual.get(key) != value}
    if field_conditions != Counter({"good": 192}):
        mismatches["field_history_track_condition"] = {"expected": {"good": 192}, "actual": dict(field_conditions)}
    if any(row["shadow_track_condition_score"] != 0 for row in horse_rows):
        mismatches["shadow_track_condition_neutral"] = "nonzero shadow score"
    if any(row["manual_track_bias_used"] for row in horse_rows):
        mismatches["manual_track_bias"] = "used"
    if mismatches:
        raise RuntimeError("FROZEN_MAY_REPRODUCTION_MISMATCH:" + json.dumps(mismatches, ensure_ascii=False, sort_keys=True))

    OUT.mkdir(parents=True)
    source_manifest = {
        "sources": manifest_sources, "runner": "review/track_condition_semantic_shadow_v1.py",
        "runner_sha256": sha256(Path(__file__)),
        "test": "tests/test_track_condition_semantic_shadow_v1.py",
        "test_sha256": sha256(ROOT / "tests" / "test_track_condition_semantic_shadow_v1.py"),
        "result_data_access_count": 0,
        "production_input_switch": "HOLD", "manual_track_bias_weather_used": False,
    }
    summary = {
        "final_status": "TRACK_CONDITION_SEMANTIC_SHADOW_V1_COMPLETE",
        "created_at": datetime.now(timezone.utc).isoformat(), "expected": EXPECTED, "actual": actual,
        "frozen_may_reproduction": "PASS", "field_history_track_conditions": dict(field_conditions),
        "target_day_track_condition_shadow": "UNKNOWN", "outcome_diagnostic": "NOT_CALCULATED",
        "outcome_diagnostic_reason": "No complete horse-level outcome mapping was consumed; raw Result CSV access is prohibited.",
        "result_data_access_count": 0, "prediction_execution_count": 0,
        "production_modification_count": 0, "manual_track_bias_weather_used": False,
        "pre_post_protected_sha256": {"before": before, "after": {relative: sha256(ROOT / relative) for relative in PROTECTED}},
    }
    _write_csv(OUT / "horse_level.csv", horse_rows, list(horse_rows[0]))
    _write_csv(OUT / "race_level.csv", race_rows, list(race_rows[0]))
    json_dump(OUT / "source_manifest.json", source_manifest)
    json_dump(OUT / "summary.json", summary)
    report = "\n".join([
        "# TrackCondition Semantic Shadow v1", "", "- Status: `TRACK_CONDITION_SEMANTIC_SHADOW_V1_COMPLETE`",
        "- Variant: target-day `race_track_condition = UNKNOWN`; historical DS conditions are preserved.",
        "- Control remains the existing field-history plurality condition; it is trace-only in Shadow.",
        f"- May reproduction: {actual['dates']} dates / {actual['races']} races / {actual['horses']} horses — PASS.",
        f"- BUY: control {actual['control_buys']}, shadow {actual['shadow_buys']}, common {actual['common_buys']}, control-only {actual['control_only_buys']}, shadow-only {actual['shadow_only_buys']}.",
        f"- Deltas: TrackCondition {actual['track_condition_score_changed']}, PastPerformance {actual['past_performance_score_changed']}, FinalScore {actual['final_score_changed']}, rank {actual['ranking_changed']}, race decision {actual['race_decision_changed']}, BUY changed races {actual['buy_changed_races']}.",
        "- No Result CSV was read. No manual TrackBias/Weather adjustment was used. Production remains unchanged.", "",
    ])
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hashes = {path.name: sha256(path) for path in sorted(OUT.iterdir()) if path.name != "artifact_hashes.json"}
    json_dump(OUT / "artifact_hashes.json", {"algorithm": "SHA256", "artifacts": hashes, "self_hash_excluded": True})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run the one-shot May semantic shadow")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required")
    print(json.dumps(execute(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
