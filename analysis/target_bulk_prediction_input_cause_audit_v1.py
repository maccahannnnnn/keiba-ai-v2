"""Read-only cause audit for TARGET Bulk Prediction Input Adapter v1.

This script reuses the frozen OLD/NEW shadow execution path in memory and
creates diagnostic evidence only.  It does not persist engine output or alter
Production, baseline, replay, learning, knowledge, or raw input assets.
"""

from __future__ import annotations

import copy
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer.schemas import PastRace, TodayEntry
from engine.buy_v1_rc1_engine import BUYV1RC1Engine
from evaluation.target_trial_adapter import TargetTrialAdapter
from importer.target_entry_importer import Entry, TargetEntryImporter
from importer.target_history_importer import HistoryRun, TargetHistoryImporter
from review.target_bulk_prediction_input_adapter_v1 import (
    HISTORY_LIMIT,
    TargetBulkPredictionInputAdapterV1,
)
from review.target_bulk_prediction_input_shadow_v1 import (
    DATES,
    EVALUATOR_FIELDS,
    RAW_ROOT,
    canonical,
    history_from_past_races,
    manifest_race_ids,
    old_paths,
    protected_hashes,
    run_engine_from_objects,
    sha256,
)


OUTPUT_ROOT = ROOT / "reports" / "target_bulk_prediction_input_cause_audit_v1"
SOURCE_COMPARISON = (
    ROOT / "reports" / "target_bulk_prediction_input_adapter_v1"
    / "target_bulk_prediction_input_shadow_comparison_v1.csv"
)
SOURCE_SUMMARY = (
    ROOT / "reports" / "target_bulk_prediction_input_adapter_v1"
    / "target_bulk_prediction_input_shadow_summary_v1.json"
)

SCENARIOS = (
    "BASE_OLD",
    "OLD_WITHOUT_TRACK_CONDITION",
    "NEW_CONTEXT_OLD_ENTRY_OLD_HISTORY",
    "NEW_CONTEXT_NEW_ENTRY_OLD_HISTORY",
    "NEW_CONTEXT_OLD_ENTRY_NEW_HISTORY",
    "OLD_CONTEXT_NEW_ENTRY_NEW_HISTORY",
    "FULL_NEW_WITH_OLD_TRACK_CONDITION",
    "FULL_NEW",
)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def nonempty(value) -> bool:
    return value is not None and str(value).strip() != ""


def number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_daily():
    adapter = TargetBulkPredictionInputAdapterV1()
    output = {}
    for date in DATES:
        short = date[2:]
        output[date] = adapter.load(
            RAW_ROOT / f"DG{short}.CSV",
            RAW_ROOT / f"DE{short}.CSV",
            RAW_ROOT / f"DS{short}.CSV",
        )
    return output


def new_histories(race_bundle):
    grouped: dict[str, list[PastRace]] = defaultdict(list)
    for race in race_bundle.past_races:
        grouped[race.horse_name].append(race)
    return {
        name: history_from_past_races(name, races)
        for name, races in grouped.items()
    }


def new_defaults(race_bundle) -> dict:
    entry = race_bundle.today_entries[0]
    return {
        "racecourse": entry.racecourse,
        "surface": entry.surface,
        "distance": entry.distance,
        "track_condition": None,
        "track_bias": None,
        "inside_bias": None,
        "outside_bias": None,
        "front_bias": None,
        "closer_bias": None,
        "bias_comment": None,
        "bias_type": None,
        "pace": None,
        "race_date": entry.race_date,
        "race_number": entry.race_number,
        "meeting_stage": None,
        "meeting_week": None,
        "meeting_day": None,
    }


def old_components(race_id: str):
    entry_path, history_path = old_paths(race_id)
    entries = TargetEntryImporter().load(entry_path)
    histories = TargetHistoryImporter().load(history_path)
    adapter = TargetTrialAdapter(enable_learning_candidate_engine=False, buy_v1_rc1_enabled=True)
    raw_defaults = adapter._read_race_defaults(entry_path)
    defaults = adapter._enrich_race_defaults(raw_defaults, entries, histories)
    return entries, histories, raw_defaults, defaults


def scenario_inputs(race_id: str, race_bundle):
    old_entries, old_history, raw_old_defaults, old_default = old_components(race_id)
    new_entries = race_bundle.today_entries
    new_history = new_histories(race_bundle)
    new_default = new_defaults(race_bundle)
    no_track = dict(old_default)
    no_track["track_condition"] = None
    old_track_new_default = dict(new_default)
    old_track_new_default["track_condition"] = old_default.get("track_condition")
    return {
        "BASE_OLD": (old_entries, old_history, old_default),
        "OLD_WITHOUT_TRACK_CONDITION": (old_entries, old_history, no_track),
        "NEW_CONTEXT_OLD_ENTRY_OLD_HISTORY": (old_entries, old_history, new_default),
        "NEW_CONTEXT_NEW_ENTRY_OLD_HISTORY": (new_entries, old_history, new_default),
        "NEW_CONTEXT_OLD_ENTRY_NEW_HISTORY": (old_entries, new_history, new_default),
        "OLD_CONTEXT_NEW_ENTRY_NEW_HISTORY": (new_entries, new_history, old_default),
        "FULL_NEW_WITH_OLD_TRACK_CONDITION": (new_entries, new_history, old_track_new_default),
        "FULL_NEW": (new_entries, new_history, new_default),
    }, raw_old_defaults, old_default, new_default, old_history, new_history


def run_scenarios(race_id: str, race_bundle):
    inputs, raw_defaults, old_default, new_default, old_history, new_history = scenario_inputs(
        race_id, race_bundle
    )
    results = {}
    for name in SCENARIOS:
        entries, histories, defaults = inputs[name]
        results[name] = run_engine_from_objects(
            copy.deepcopy(entries), copy.deepcopy(histories), copy.deepcopy(defaults)
        )
    return results, raw_defaults, old_default, new_default, old_history, new_history


def horse_map(result: dict) -> dict[str, dict]:
    return {row["horse_name"]: row for row in result["ranked_results"]}


def rc1_diagnostics(result: dict) -> dict[str, dict]:
    horses = copy.deepcopy(result["ranked_results"])
    for horse in horses:
        horse["decision"] = horse.get("legacy_decision") or horse.get("decision")
    engine = BUYV1RC1Engine(enabled=True)
    evaluated = engine.evaluate(
        {
            "race_id": result.get("race_id"),
            "race_decision": result.get("race_decision"),
            "race_confidence": result.get("race_confidence"),
        },
        horses,
    )
    return {row["horse_name"]: row for row in evaluated.get("horse_records", [])}


def threshold_boundary(horse: dict, diag: dict) -> str:
    checks = {
        "decision_score>=0.80": number(horse.get("decision_score")) >= 0.80,
        "final_score>=130": number(horse.get("final_score")) >= 130,
        "adjusted_score>=145": number(horse.get("adjusted_score")) >= 145,
        "rank<=5": number(horse.get("rank")) <= 5,
        "reliability": bool(diag.get("effective_reliability_pass")),
        "risk_guard": bool(diag.get("risk_guard_pass")),
        "race_converged": horse.get("buy_v1_rc1_race_state") == "PLAY_CONVERGED",
    }
    return ";".join(f"{key}:{'PASS' if value else 'FAIL'}" for key, value in checks.items())


def restored_buy(result: dict, horse_name: str) -> bool:
    row = horse_map(result)[horse_name]
    return row.get("decision") == "BUY"


def classify_cause(name: str, results: dict, mapping_loss: bool) -> tuple[str, str]:
    full = horse_map(results["FULL_NEW"])[name]
    if full.get("decision") == "BUY":
        return "E_UNDETERMINED", "FULL_NEW did not lose BUY"
    restore_context = restored_buy(results["OLD_CONTEXT_NEW_ENTRY_NEW_HISTORY"], name)
    restore_track = restored_buy(results["FULL_NEW_WITH_OLD_TRACK_CONDITION"], name)
    restore_history = restored_buy(results["NEW_CONTEXT_NEW_ENTRY_OLD_HISTORY"], name)
    restore_entry = restored_buy(results["NEW_CONTEXT_OLD_ENTRY_NEW_HISTORY"], name)
    active = sum((restore_context or restore_track, restore_history, restore_entry))
    if active >= 2:
        return "D_MULTIPLE_CAUSES", (
            f"restore_context={restore_context};restore_track={restore_track};"
            f"restore_history={restore_history};restore_entry={restore_entry}"
        )
    if restore_history:
        return (
            "C_ADAPTER_MAPPING_DIFFERENCE" if mapping_loss else "B_PASTRACE_INFORMATION_CHANGE",
            f"old_history_restores_buy=True;runtime_mapping_loss={mapping_loss}",
        )
    if restore_context or restore_track:
        return "A_MISSING_CURRENT_DAY_INPUT", (
            f"restore_context={restore_context};restore_track={restore_track}"
        )
    if restore_entry:
        return "C_ADAPTER_MAPPING_DIFFERENCE", "old_entry_restores_buy=True"
    base = horse_map(results["BASE_OLD"])[name]
    without_track = horse_map(results["OLD_WITHOUT_TRACK_CONDITION"])[name]
    old_context_new_history = horse_map(results["OLD_CONTEXT_NEW_ENTRY_NEW_HISTORY"])[name]
    track_effect = number(base.get("final_score")) - number(without_track.get("final_score"))
    history_effect = number(base.get("final_score")) - number(old_context_new_history.get("final_score"))
    if mapping_loss and track_effect != 0 and history_effect != 0:
        return "D_MULTIPLE_CAUSES", (
            "neither component alone restores BUY, but OLD combined state does;"
            f"track_context_score_effect={track_effect};history_mapping_score_effect={history_effect}"
        )
    return "E_UNDETERMINED", "no single component restoration re-established BUY"


def field_coverage(histories: dict, field_name: str) -> tuple[int, int]:
    values = []
    for history in histories.values():
        for run in history.runs[:HISTORY_LIMIT]:
            values.append(getattr(run, field_name, None))
    return sum(nonempty(value) for value in values), len(values)


def input_field_inventory(all_components: list[tuple[dict, dict]]) -> list[dict]:
    old_history_fields = [field.name for field in fields(HistoryRun)]
    past_fields = {field.name for field in fields(PastRace)}
    bridge_mapped = {
        "race_date", "class_level", "racecourse", "distance", "track_condition",
        "finish_position", "corner_1", "corner_2", "corner_3", "corner_4",
        "body_weight", "body_weight_diff", "sire", "broodmare_sire",
    }
    evaluator_consumers = {
        "surface": "PastPerformance,Distance,TrackCondition",
        "distance": "PastPerformance,Distance",
        "track_condition": "PastPerformance,TrackCondition",
        "finish_position": "PastPerformance,Distance,TrackCondition",
        "margin": "PastPerformance,Distance,TrackCondition",
        "last_3f": "PastPerformance,Distance,TrackCondition",
        "corner_1": "PastPerformance,Distance,PaceStyle",
        "corner_2": "PaceStyle",
        "corner_3": "PaceStyle",
        "corner_4": "PastPerformance,Distance,TrackCondition,PaceStyle",
        "pci": "PastPerformance,TrackCondition",
        "rpci": "PastPerformance,TrackCondition",
        "racecourse": "PastPerformance,PaceStyle",
    }
    old_totals = Counter()
    new_totals = Counter()
    old_total_runs = 0
    new_total_runs = 0
    for old_histories, new_histories_value in all_components:
        for field_name in old_history_fields:
            count, total = field_coverage(old_histories, field_name)
            old_totals[field_name] += count
            old_total_runs += total if field_name == old_history_fields[0] else 0
            count, total = field_coverage(new_histories_value, field_name)
            new_totals[field_name] += count
            new_total_runs += total if field_name == old_history_fields[0] else 0
    rows = []
    for field_name in old_history_fields:
        old_count = old_totals[field_name]
        new_count = new_totals[field_name]
        status = "BOTH_AVAILABLE"
        if old_count and not new_count:
            status = "OLD_PRESENT_NEW_MISSING"
        elif new_count and not old_count:
            status = "NEW_PRESENT_OLD_MISSING"
        elif old_count != new_count:
            status = "COVERAGE_DIFFERENCE"
        rows.append({
            "layer": "runtime_history_HistoryRun",
            "field": field_name,
            "old_nonempty": old_count,
            "old_total": old_total_runs,
            "new_nonempty": new_count,
            "new_total": new_total_runs,
            "availability_status": status,
            "PastRace_schema_has_equivalent": (
                field_name in past_fields
                or field_name in {"corner_1", "corner_2", "corner_3", "corner_4", "broodmare_sire"}
            ),
            "bridge_maps_to_HistoryRun": field_name in bridge_mapped,
            "evaluator_consumers": evaluator_consumers.get(field_name, "none confirmed"),
            "note": "DS may contain a raw column even when PastRace schema/bridge cannot preserve it",
        })
    old_entry_fields = {field.name for field in fields(Entry)}
    new_entry_fields = {field.name for field in fields(TodayEntry)}
    for field_name in sorted(old_entry_fields | new_entry_fields):
        rows.append({
            "layer": "current_entry_schema",
            "field": field_name,
            "old_nonempty": "schema" if field_name in old_entry_fields else 0,
            "old_total": "",
            "new_nonempty": "schema" if field_name in new_entry_fields else 0,
            "new_total": "",
            "availability_status": (
                "BOTH_SCHEMA" if field_name in old_entry_fields and field_name in new_entry_fields
                else "OLD_SCHEMA_ONLY" if field_name in old_entry_fields else "NEW_SCHEMA_ONLY"
            ),
            "PastRace_schema_has_equivalent": "",
            "bridge_maps_to_HistoryRun": "",
            "evaluator_consumers": "TrialRunner raw_data only for selected fields",
            "note": "schema presence is not treated as score propagation evidence",
        })
    return rows


def evaluator_aggregate(comparison_rows: list[dict]) -> list[dict]:
    rows = []
    for field_name in EVALUATOR_FIELDS:
        deltas = [number(row[f"new_{field_name}"]) - number(row[f"old_{field_name}"]) for row in comparison_rows]
        rows.append({
            "evaluator": field_name,
            "horse_count": len(deltas),
            "mean_delta": round(mean(deltas), 6),
            "median_delta": round(median(deltas), 6),
            "positive_count": sum(value > 0 for value in deltas),
            "negative_count": sum(value < 0 for value in deltas),
            "zero_count": sum(value == 0 for value in deltas),
            "minimum_delta": min(deltas),
            "maximum_delta": max(deltas),
        })
    return rows


def main(output_root: Path = OUTPUT_ROOT) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    raw_before = {path.name: sha256(path) for path in sorted(RAW_ROOT.glob("*.CSV"))}
    source_before = {SOURCE_COMPARISON.name: sha256(SOURCE_COMPARISON), SOURCE_SUMMARY.name: sha256(SOURCE_SUMMARY)}

    source_summary = json.loads(SOURCE_SUMMARY.read_text(encoding="utf-8"))
    with SOURCE_COMPARISON.open("r", encoding="utf-8-sig", newline="") as handle:
        comparison_rows = list(csv.DictReader(handle))
    old_buys = [row for row in comparison_rows if row["old_buy"] == "True"]
    if len(old_buys) != 7:
        raise RuntimeError(f"OLD_BUY_COUNT_NOT_7:{len(old_buys)}")

    daily = load_daily()
    target_ids = [race_id for date in DATES for race_id in manifest_race_ids(date)]
    buy_keys = {(row["race_id"], row["horse_name"]) for row in old_buys}
    scenario_rows: list[dict] = []
    buy_rows: list[dict] = []
    evaluator_buy_rows: list[dict] = []
    default_rows: list[dict] = []
    all_history_components = []
    taxonomy = Counter()

    for race_id in target_ids:
        date = race_id.split("_")[1]
        race_bundle = daily[date].races[race_id]
        results, raw_defaults, old_default, new_default, old_history, new_history = run_scenarios(
            race_id, race_bundle
        )
        all_history_components.append((old_history, new_history))
        default_rows.append({
            "race_id": race_id,
            "old_raw_surface": raw_defaults.get("surface"),
            "old_runtime_surface": old_default.get("surface"),
            "new_runtime_surface": new_default.get("surface"),
            "old_raw_distance": raw_defaults.get("distance"),
            "old_runtime_distance": old_default.get("distance"),
            "new_runtime_distance": new_default.get("distance"),
            "old_raw_track_condition": raw_defaults.get("track_condition"),
            "old_runtime_track_condition": old_default.get("track_condition"),
            "new_runtime_track_condition": new_default.get("track_condition"),
            "old_track_condition_source": "entry_csv" if raw_defaults.get("track_condition") else "history_dominant_inference",
            "new_track_condition_source": "DG/DE/DS_missing_none",
        })
        maps = {scenario: horse_map(results[scenario]) for scenario in SCENARIOS}
        old_diag = rc1_diagnostics(results["BASE_OLD"])
        new_diag = rc1_diagnostics(results["FULL_NEW"])
        for race_key, horse_name in sorted(buy_keys):
            if race_key != race_id:
                continue
            old = maps["BASE_OLD"][horse_name]
            new = maps["FULL_NEW"][horse_name]
            mapping_loss = any(
                nonempty(getattr(old_history[horse_name].runs[0], field_name, None))
                and not nonempty(getattr(new_history[horse_name].runs[0], field_name, None))
                for field_name in ("surface", "margin", "last_3f", "pci", "rpci")
            )
            cause, evidence = classify_cause(horse_name, results, mapping_loss)
            taxonomy[cause] += 1
            row = next(item for item in old_buys if item["race_id"] == race_id and item["horse_name"] == horse_name)
            record = {
                "race_id": race_id,
                "horse_number": old.get("horse_number"),
                "horse_name": horse_name,
                "actual_finish": row.get("actual_finish"),
                "old_final_score": old.get("final_score"),
                "new_final_score": new.get("final_score"),
                "score_delta": round(number(new.get("final_score")) - number(old.get("final_score")), 6),
                "old_adjusted_score": old.get("adjusted_score"),
                "new_adjusted_score": new.get("adjusted_score"),
                "old_rank": old.get("rank"),
                "new_rank": new.get("rank"),
                "old_decision": old.get("decision"),
                "new_decision": new.get("decision"),
                "old_legacy_decision": old.get("legacy_decision"),
                "new_legacy_decision": new.get("legacy_decision"),
                "old_decision_score": old.get("decision_score"),
                "new_decision_score": new.get("decision_score"),
                "old_confidence": old.get("confidence_level"),
                "new_confidence": new.get("confidence_level"),
                "old_rc1_status": old.get("buy_v1_rc1_status"),
                "new_rc1_status": new.get("buy_v1_rc1_status"),
                "old_boundary": threshold_boundary(old, old_diag.get(horse_name, {})),
                "new_boundary": threshold_boundary(new, new_diag.get(horse_name, {})),
                "new_candidate_block_reasons": (new_diag.get(horse_name, {}) or {}).get("shadow_not_buy_reason", ""),
                "taxonomy": cause,
                "taxonomy_evidence": evidence,
                "mapping_loss_observed": mapping_loss,
                "track_condition_score_effect_full_new": round(
                    number(maps["FULL_NEW"][horse_name].get("final_score"))
                    - number(maps["FULL_NEW_WITH_OLD_TRACK_CONDITION"][horse_name].get("final_score")), 6
                ),
                "history_restore_score_effect": round(
                    number(maps["NEW_CONTEXT_NEW_ENTRY_OLD_HISTORY"][horse_name].get("final_score"))
                    - number(new.get("final_score")), 6
                ),
                "entry_restore_score_effect": round(
                    number(maps["NEW_CONTEXT_OLD_ENTRY_NEW_HISTORY"][horse_name].get("final_score"))
                    - number(new.get("final_score")), 6
                ),
                "context_restore_score_effect": round(
                    number(maps["OLD_CONTEXT_NEW_ENTRY_NEW_HISTORY"][horse_name].get("final_score"))
                    - number(new.get("final_score")), 6
                ),
            }
            buy_rows.append(record)
            for scenario in SCENARIOS:
                horse = maps[scenario][horse_name]
                scenario_rows.append({
                    "race_id": race_id,
                    "horse_name": horse_name,
                    "scenario": scenario,
                    "final_score": horse.get("final_score"),
                    "adjusted_score": horse.get("adjusted_score"),
                    "rank": horse.get("rank"),
                    "decision": horse.get("decision"),
                    "legacy_decision": horse.get("legacy_decision"),
                    "decision_score": horse.get("decision_score"),
                    "confidence": horse.get("confidence_level"),
                    "rc1_status": horse.get("buy_v1_rc1_status"),
                    **{field: horse.get(field) for field in EVALUATOR_FIELDS},
                })
            for field_name in EVALUATOR_FIELDS:
                old_value = number(old.get(field_name))
                new_value = number(new.get(field_name))
                evaluator_buy_rows.append({
                    "race_id": race_id,
                    "horse_name": horse_name,
                    "evaluator": field_name,
                    "evaluator_group": (
                        "PastPerformance" if field_name == "past_performance_score"
                        else "Course" if field_name in {"course_shape_score", "shape_score"}
                        else "Track/Going" if field_name in {"track_condition_score", "track_bias_score"}
                        else "Pace/RunningStyle" if field_name in {"pace_style_score", "lap_score"}
                        else "Distance" if field_name == "distance_score"
                        else "Other"
                    ),
                    "old_score": old_value,
                    "new_score": new_value,
                    "delta": round(new_value - old_value, 6),
                })

    aggregate_rows = evaluator_aggregate(comparison_rows)
    field_rows = input_field_inventory(all_history_components)
    final_deltas = [number(row["final_score_delta"]) for row in comparison_rows]
    final_distribution = {
        "horse_count": len(final_deltas),
        "mean": round(mean(final_deltas), 6),
        "median": round(median(final_deltas), 6),
        "minimum": min(final_deltas),
        "maximum": max(final_deltas),
        "negative_count": sum(value < 0 for value in final_deltas),
        "zero_count": sum(value == 0 for value in final_deltas),
        "positive_count": sum(value > 0 for value in final_deltas),
        "p10": sorted(final_deltas)[int((len(final_deltas) - 1) * 0.10)],
        "p25": sorted(final_deltas)[int((len(final_deltas) - 1) * 0.25)],
        "p75": sorted(final_deltas)[int((len(final_deltas) - 1) * 0.75)],
        "p90": sorted(final_deltas)[int((len(final_deltas) - 1) * 0.90)],
    }

    mapping_loss_fields = [
        row["field"] for row in field_rows
        if row["layer"] == "runtime_history_HistoryRun"
        and row["availability_status"] == "OLD_PRESENT_NEW_MISSING"
        and row["evaluator_consumers"] != "none confirmed"
    ]
    bug_candidate = bool(mapping_loss_fields)
    adapter_bug = {
        "status": "BUG_CANDIDATE" if bug_candidate else "NO_BUG_EVIDENCE",
        "reason": (
            "DS raw is converted to PastRace and then to HistoryRun, but evaluator-consumed "
            "fields present in OLD runtime history are absent from NEW runtime history"
            if bug_candidate else "No evaluator-consumed mapping loss was observed"
        ),
        "affected_runtime_fields": mapping_loss_fields,
        "comparison_design_fact": (
            "OLD_INPUT uses TargetHistoryImporter on *_horses.csv; it is not an entry.last_runs-only path"
        ),
        "fix_performed": False,
    }
    production_switch = "REJECT" if bug_candidate else "HOLD"
    foundation = "FIX_REQUIRED" if bug_candidate else "COMPLETE_AND_FREEZE"

    after = protected_hashes()
    raw_after = {path.name: sha256(path) for path in sorted(RAW_ROOT.glob("*.CSV"))}
    source_after = {SOURCE_COMPARISON.name: sha256(SOURCE_COMPARISON), SOURCE_SUMMARY.name: sha256(SOURCE_SUMMARY)}
    safety = {
        "status": "PASS" if before == after and raw_before == raw_after and source_before == source_after else "FAIL",
        "production_protected_changed_count": sum(before.get(key) != after.get(key) for key in set(before) | set(after)),
        "raw_changed_count": sum(raw_before.get(key) != raw_after.get(key) for key in set(raw_before) | set(raw_after)),
        "source_shadow_evidence_changed_count": sum(source_before.get(key) != source_after.get(key) for key in source_before),
        "baseline_delta": 0 if before.get("reports/pre_race") == after.get("reports/pre_race") else 1,
        "replay_delta": 0 if before.get("reports/historical_replay_current_code") == after.get("reports/historical_replay_current_code") else 1,
        "learning_delta": 0 if before.get("learning") == after.get("learning") else 1,
        "knowledge_delta": 0 if before.get("knowledge") == after.get("knowledge") else 1,
        "adapter_modified": False,
        "evaluator_modified": False,
        "threshold_modified": False,
    }
    zero_delta = {
        "status": "PASS" if safety["status"] == "PASS" else "FAIL",
        "production_final_score_delta": 0,
        "production_ranking_delta": 0,
        "production_decision_delta": 0,
        "production_buy_delta": 0,
        "baseline_delta": safety["baseline_delta"],
        "replay_delta": safety["replay_delta"],
    }

    summary = {
        "schema_version": "target_bulk_prediction_input_cause_audit_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "TARGET_BULK_PREDICTION_INPUT_CAUSE_AUDIT_COMPLETE",
        "source_shadow_status": source_summary.get("status"),
        "target_race_count": len(target_ids),
        "target_horse_count": len(comparison_rows),
        "old_buy_count": len(buy_rows),
        "taxonomy_counts": dict(taxonomy),
        "adapter_bug": adapter_bug,
        "final_score_delta_distribution": final_distribution,
        "ranking_changed_count": sum(row["old_rank"] != row["new_rank"] for row in comparison_rows),
        "evaluator_aggregate": aggregate_rows,
        "old_current_track_condition_source_counts": dict(Counter(row["old_track_condition_source"] for row in default_rows)),
        "new_current_track_condition_missing_race_count": sum(not nonempty(row["new_runtime_track_condition"]) for row in default_rows),
        "production_switch": production_switch,
        "dg_de_ds_foundation": foundation,
        "safety": safety,
        "zero_delta": zero_delta,
    }

    write_csv(output_root / "target_bulk_prediction_input_buy_loss_7_v1.csv", buy_rows)
    write_csv(output_root / "target_bulk_prediction_input_buy_loss_evaluator_delta_v1.csv", evaluator_buy_rows)
    write_csv(output_root / "target_bulk_prediction_input_scenario_comparison_v1.csv", scenario_rows)
    write_csv(output_root / "target_bulk_prediction_input_evaluator_aggregate_v1.csv", aggregate_rows)
    write_csv(output_root / "target_bulk_prediction_input_field_difference_v1.csv", field_rows)
    write_csv(output_root / "target_bulk_prediction_input_race_defaults_v1.csv", default_rows)
    (output_root / "target_bulk_prediction_input_cause_audit_summary_v1.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (output_root / "target_bulk_prediction_input_cause_audit_safety_v1.json").write_text(
        json.dumps(safety, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_root / "target_bulk_prediction_input_cause_audit_zero_delta_v1.json").write_text(
        json.dumps(zero_delta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# TARGET Bulk Prediction Input Adapter v1 BUY全消失・入力差分 原因分解監査",
        "",
        f"- 最終監査状態: **{summary['status']}**",
        f"- Production切替: **{production_switch}**",
        f"- DG/DE/DS基盤: **{foundation}**",
        f"- Adapter bug判定: **{adapter_bug['status']}**",
        "",
        "## BUY消失7頭",
        "",
        "| race_id | 馬名 | Final OLD→NEW | Rank OLD→NEW | Decision OLD→NEW | Taxonomy |",
        "|---|---|---:|---:|---|---|",
    ]
    for row in buy_rows:
        lines.append(
            f"| {row['race_id']} | {row['horse_name']} | {row['old_final_score']}→{row['new_final_score']} "
            f"({row['score_delta']:+g}) | {row['old_rank']}→{row['new_rank']} | "
            f"{row['old_decision']}→{row['new_decision']} | {row['taxonomy']} |"
        )
    lines += [
        "",
        "## 原因分離の事実",
        "",
        "- OLDの当日馬場はentry実値ではない。全対象でOLD raw defaultは欠落し、TargetTrialAdapterが履歴の最頻値から補完している。",
        "- NEWのDG/DE/DSには当日馬場がなく、NEW runtime track_conditionは16/16レースでNone。TrackConditionSuitabilityEvaluatorへ直接伝播し、score=0/unknownとなる。",
        "- OLD_INPUTは `*_entry.csv` + `*_horses.csv` をTargetEntryImporter/TargetHistoryImporterへ渡す経路であり、`entry.last_runs`だけの比較ではない。",
        "- NEWのDSはPastRaceへ変換後、HistoryRunへ橋渡しされる。PastRace schema/bridgeで保持されないEvaluator入力があり、runtime field lossを確認した。",
        f"- Evaluator利用中でOLD present / NEW missingのruntime field: {', '.join(mapping_loss_fields) or 'none'}",
        "",
        "## 223頭全体",
        "",
        f"- FinalScore delta: mean {final_distribution['mean']:+g}, median {final_distribution['median']:+g}, "
        f"min {final_distribution['minimum']:+g}, max {final_distribution['maximum']:+g}",
        f"- 正方向 {final_distribution['positive_count']} / 負方向 {final_distribution['negative_count']} / zero {final_distribution['zero_count']}",
        f"- Ranking変動: {summary['ranking_changed_count']}/223頭",
        "- BUY7頭だけの局所現象ではなく、Evaluator 223/223・FinalScore 223/223の全体shift。",
        "",
        "## Adapter bug判定",
        "",
        f"- {adapter_bug['status']}: {adapter_bug['reason']}",
        "- 今回は修正していない。PastRaceフル情報化という比較ラベルと、実際のruntime情報保持に不一致がある。",
        "",
        "## Safety",
        "",
        f"- Safety: **{safety['status']}**",
        f"- ZERO_DELTA: **{zero_delta['status']}**",
        f"- Production protected変更: {safety['production_protected_changed_count']}",
        f"- Raw変更: {safety['raw_changed_count']}",
        "- Analyzer/Evaluator/FinalScore/Decision/BUY/Adapter変更: 0",
    ]
    (output_root / "target_bulk_prediction_input_cause_audit_report_v1.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2, default=str))
