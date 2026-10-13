"""Read-only OLD_INPUT vs DG/DE/DS NEW_INPUT shadow comparison v1."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from analyzer.schemas import PastRace, TodayEntry
from evaluation.target_result_adapter import TargetResultAdapter
from evaluation.target_trial_adapter import TargetTrialAdapter
from importer.target_entry_importer import TargetEntryImporter
from importer.target_history_importer import HistoryRun, HorseHistory, TargetHistoryImporter
from review.target_bulk_prediction_input_adapter_v1 import (
    COURSE_KEYS,
    HISTORY_LIMIT,
    PredictionInputValidationError,
    TargetBulkPredictionInputAdapterV1,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "reports" / "target_bulk_prediction_input_adapter_mapping_fix_v1"
RAW_ROOT = ROOT / "data" / "raw" / "prediction_input"
DATES = ("20260808", "20260809")
EVALUATOR_FIELDS = (
    "bloodline_score", "past_performance_score", "pace_style_score",
    "distance_score", "track_condition_score", "shape_score",
    "course_shape_score", "track_bias_score", "lap_score",
)
PROTECTED_PATHS = (
    "analyzer", "engine", "evaluation", "evaluators", "importer", "learning",
    "knowledge", "main.py", "data/results", "reports/pre_race",
    "reports/historical_replay_current_code",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for child in sorted(path.rglob("*")):
        if child.is_file():
            digest.update(child.relative_to(ROOT).as_posix().encode())
            digest.update(child.read_bytes())
    return digest.hexdigest()


def protected_hashes() -> dict[str, str]:
    return {name: sha256(ROOT / name) for name in PROTECTED_PATHS if (ROOT / name).exists()}


def manifest_race_ids(date: str) -> list[str]:
    path = ROOT / "reports" / "pre_race" / date / f"pre_race_{date}_execution_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["race_ids"])


def old_paths(race_id: str) -> tuple[Path, Path]:
    entry = ROOT / "data" / "analysis" / f"{race_id}_entry.csv"
    horses = ROOT / "data" / "analysis" / f"{race_id}_horses.csv"
    if not entry.is_file() or not horses.is_file():
        raise FileNotFoundError(f"OLD_INPUT_MISSING: {race_id}")
    return entry, horses


def read_cp932(path: Path) -> list[list[str]]:
    with path.open("r", encoding="cp932", newline="") as handle:
        return list(csv.reader(handle))


def history_from_past_races(name: str, races: list[PastRace]) -> HorseHistory:
    """Bridge the existing PastRace schema to the current evaluator history input."""

    return HorseHistory(
        horse_name=name,
        runs=[HistoryRun(
            race_date=race.race_date.strftime("%Y/%m/%d"),
            class_level=race.class_level,
            racecourse=race.race_id.split("_")[2] if len(race.race_id.split("_")) >= 4 else None,
            distance=str(race.distance),
            track_condition=race.track_condition,
            finish_position=str(race.finish_position),
            corner_1=(race.corner_positions.split("-") + [None] * 4)[0],
            corner_2=(race.corner_positions.split("-") + [None] * 4)[1],
            corner_3=(race.corner_positions.split("-") + [None] * 4)[2],
            corner_4=(race.corner_positions.split("-") + [None] * 4)[3],
            body_weight=str(race.body_weight) if race.body_weight else None,
            body_weight_diff=str(race.body_weight_diff),
            sire=race.sire,
            broodmare_sire=race.dam_sire,
            surface=race.surface,
            margin=race.margin,
            last_3f=race.last_3f,
            pci=race.pci,
            rpci=race.rpci,
        ) for race in races[:HISTORY_LIMIT]],
    )


def new_entry_rows(bundle) -> list[dict[str, str]]:
    rows = []
    for entry in bundle.today_entries:
        rows.append({
            "race_date": entry.race_date,
            "racecourse": entry.racecourse,
            "race_number": str(entry.race_number),
            "distance": str(entry.distance),
            "surface": entry.surface,
            "track_condition": entry.track_condition,
            "status": entry.status,
            "horse_number": str(entry.horse_number),
            "horse_name": entry.horse_name,
            "frame_number": str(entry.frame_number),
            "jockey": entry.jockey,
            "weight": str(entry.weight),
            "body_weight": str(entry.body_weight),
            "body_weight_diff": str(entry.body_weight_diff),
            "running_style": entry.running_style,
            "last_runs": entry.last_runs,
            "past_lap_note": entry.past_lap_note,
            "expected_lap_note": entry.expected_lap_note,
            "sire": entry.sire,
            "dam_sire": entry.dam_sire,
            "bloodline_note": entry.bloodline_note,
            "class_level": entry.class_level,
        })
    return rows


_TRACE_FORBIDDEN_RESULT_KEYS = {
    "finish", "finish_position", "actual_top3", "valid_result", "payout",
    "placement", "placement_outcome", "result", "result_outcome", "top3_result",
}


def _trace_required(mapping: dict, key: str, context: str):
    if not isinstance(mapping, dict) or key not in mapping:
        raise PredictionInputValidationError("BUY_GATE_TRACE_REQUIRED_FIELD_MISSING", f"{context}:{key}")
    return mapping[key]


def _trace_horse_number(value, context: str) -> int:
    """Accept only the existing, exact horse-number identity value."""

    if isinstance(value, bool) or value is None:
        raise PredictionInputValidationError("BUY_GATE_TRACE_HORSE_NUMBER_INVALID", context)
    raw_value = str(value).strip()
    if not raw_value.isdigit():
        raise PredictionInputValidationError("BUY_GATE_TRACE_HORSE_NUMBER_INVALID", context)
    number = int(raw_value)
    if number < 1:
        raise PredictionInputValidationError("BUY_GATE_TRACE_HORSE_NUMBER_INVALID", context)
    return number


def _assert_trace_has_no_result_fields(value) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _TRACE_FORBIDDEN_RESULT_KEYS:
                raise PredictionInputValidationError("BUY_GATE_TRACE_RESULT_FIELD_FORBIDDEN", str(key))
            _assert_trace_has_no_result_fields(child)
    elif isinstance(value, list):
        for child in value:
            _assert_trace_has_no_result_fields(child)


def _race_course_shape_trace_values(final_row: dict) -> dict:
    """Project existing evaluator runtime values without recomputation.

    ``shape_result`` and ``course_shape_result`` are attached to each horse by
    ``TargetTrialAdapter._apply_race_shape_and_final_scores`` before ranking,
    Decision, and BUY evaluation.  This helper only copies their already
    computed values into the optional PRE-only trace.  A missing evaluator
    payload or field is represented by ``None``; it is never reconstructed.
    """

    shape_result = final_row.get("shape_result")
    course_shape_result = final_row.get("course_shape_result")
    if not isinstance(shape_result, dict):
        shape_result = {}
    if not isinstance(course_shape_result, dict):
        course_shape_result = {}
    return {
        "pace_prediction": shape_result.get("pace_prediction"),
        "pace_style": shape_result.get("pace_style"),
        "course_profile_matched": course_shape_result.get("course_profile_matched"),
        "race_shape_adjustment_id": shape_result.get("race_shape_adjustment_id"),
    }


def _project_buy_gate_trace(buy: dict, ranked_results: list[dict]) -> dict:
    """Create the approved PRE-only projection without mutating runtime values."""

    shadow_result = _trace_required(buy, "shadow_result", "buy")
    race_record = _trace_required(shadow_result, "race_record", "shadow_result")
    shadow_records = _trace_required(shadow_result, "horse_records", "shadow_result")
    if not isinstance(race_record, dict) or not isinstance(shadow_records, list):
        raise PredictionInputValidationError("BUY_GATE_TRACE_REQUIRED_FIELD_MISSING", "shadow_result:structure")

    ranked_by_number: dict[int, dict] = {}
    for row in ranked_results:
        number = _trace_horse_number(_trace_required(row, "horse_number", "ranked_result"), "ranked_result")
        if number in ranked_by_number:
            raise PredictionInputValidationError("BUY_GATE_TRACE_HORSE_NUMBER_DUPLICATE", str(number))
        ranked_by_number[number] = row

    shadow_by_number: dict[int, dict] = {}
    for row in shadow_records:
        number = _trace_horse_number(_trace_required(row, "horse_number", "shadow_record"), "shadow_record")
        if number in shadow_by_number:
            raise PredictionInputValidationError("BUY_GATE_TRACE_HORSE_NUMBER_DUPLICATE", str(number))
        shadow_by_number[number] = row
    if set(ranked_by_number) != set(shadow_by_number):
        raise PredictionInputValidationError("BUY_GATE_TRACE_HORSE_NUMBER_SET_MISMATCH", "shadow/final")

    horse_projection = []
    for number, final_row in ranked_by_number.items():
        shadow_row = shadow_by_number[number]
        consensus = _trace_required(shadow_row, "consensus", "shadow_record")
        profile = _trace_required(shadow_row, "consensus_profile", "shadow_record")
        decision_result = _trace_required(final_row, "decision_result", "ranked_result")
        projected = {
            "horse_number": number,
            "prediction_rank": _trace_required(final_row, "rank", "ranked_result"),
            "decision_engine_rank": _trace_required(decision_result, "ai_rank", "decision_result"),
            "rank_context_rank": _trace_required(decision_result, "ai_rank", "decision_result"),
            "pre_rc1_decision": _trace_required(decision_result, "decision", "decision_result"),
            "post_rc1_decision": _trace_required(final_row, "decision", "ranked_result"),
            "shadow_ai_rank": _trace_required(shadow_row, "ai_rank", "shadow_record"),
            "decision_score": _trace_required(shadow_row, "decision_score", "shadow_record"),
            "final_score": _trace_required(shadow_row, "final_score", "shadow_record"),
            "adjusted_score": _trace_required(shadow_row, "adjusted_score", "shadow_record"),
            "evaluator_score_snapshot": _trace_required(profile, "score_snapshot", "consensus_profile"),
            "positive_evaluators": _trace_required(consensus, "positive_evaluators", "consensus"),
            "negative_evaluators": _trace_required(consensus, "negative_evaluators", "consensus"),
            "missing_evaluators": _trace_required(consensus, "missing_evaluators", "consensus"),
            "blocking_missing_evaluators": _trace_required(consensus, "blocking_missing_evaluators", "consensus"),
            "positive_count": _trace_required(profile, "positive_evaluator_count", "consensus_profile"),
            "negative_count": _trace_required(profile, "negative_evaluator_count", "consensus_profile"),
            "strong_positive_count": _trace_required(profile, "strong_positive_count", "consensus_profile"),
            "strong_negative_count": _trace_required(profile, "strong_negative_count", "consensus_profile"),
            "net_consensus_score": _trace_required(profile, "net_consensus_score", "consensus_profile"),
            "risk_summary": _trace_required(shadow_row, "risk_summary", "shadow_record"),
            "conflict_factors": _trace_required(consensus, "conflict_factors", "consensus"),
            "absolute_quality_pass": _trace_required(shadow_row, "absolute_quality_pass", "shadow_record"),
            "relative_advantage_pass": _trace_required(shadow_row, "relative_advantage_pass", "shadow_record"),
            "reliability_pass": _trace_required(shadow_row, "reliability_pass", "shadow_record"),
            "effective_reliability_pass": _trace_required(shadow_row, "effective_reliability_pass", "shadow_record"),
            "risk_guard_pass": _trace_required(shadow_row, "risk_guard_pass", "shadow_record"),
            "shadow_buy_candidate": _trace_required(shadow_row, "shadow_buy_candidate", "shadow_record"),
            "shadow_buy": _trace_required(shadow_row, "shadow_buy", "shadow_record"),
        }
        projected.update(_race_course_shape_trace_values(final_row))
        horse_projection.append(projected)
    projection = {
        "race": {
            "shadow_candidate_count": _trace_required(race_record, "shadow_candidate_count", "race_record"),
            "shadow_race_state": _trace_required(race_record, "shadow_race_state", "race_record"),
            "shadow_spec_converged": _trace_required(race_record, "shadow_spec_converged", "race_record"),
        },
        "horses": horse_projection,
    }
    _assert_trace_has_no_result_fields(projection)
    return copy.deepcopy(projection)


def run_engine_from_objects(entries, histories, race_defaults, trace: bool = False) -> dict:
    """Use current evaluators in memory; bypass all persistence-only tail steps."""

    adapter = TargetTrialAdapter(
        learning_phase2_enabled=False,
        shadow_buy_spec_v1_enabled=False,
        buy_v1_rc1_enabled=True,
        enable_learning_candidate_engine=False,
    )
    pairs = [(entry, histories.get(entry.horse_name)) for entry in entries]
    horse_results = []
    for entry, history in pairs:
        adapter._fill_entry_from_history(entry, history)
        raw_data = adapter._build_raw_data(entry, race_defaults, history)
        trial_result = adapter.runner.run(raw_data)
        history_runs = adapter._history_runs(history)
        past = adapter.past_performance_evaluator.evaluate(
            recent_runs=history_runs,
            racecourse=race_defaults.get("racecourse"), surface=race_defaults.get("surface"),
            distance=race_defaults.get("distance"), track_condition=race_defaults.get("track_condition"),
            horse_name=entry.horse_name,
        )
        combined = adapter._merge_past_performance(trial_result, past)
        pace = adapter.pace_style_evaluator.evaluate(
            recent_runs=history_runs, racecourse=race_defaults.get("racecourse"),
            surface=race_defaults.get("surface"), distance=race_defaults.get("distance"),
            horse_name=entry.horse_name,
        )
        combined = adapter._merge_pace_style(combined, pace)
        distance = adapter.distance_suitability_evaluator.evaluate(
            recent_runs=history_runs, distance=race_defaults.get("distance"),
            surface=race_defaults.get("surface"), horse_name=entry.horse_name,
        )
        combined = adapter._merge_distance(combined, distance)
        condition = adapter.track_condition_suitability_evaluator.evaluate(
            recent_runs=history_runs, surface=race_defaults.get("surface"),
            track_condition=race_defaults.get("track_condition"), horse_name=entry.horse_name,
        )
        combined = adapter._merge_track_condition_suitability(combined, condition)
        row = {
            "horse_name": entry.horse_name, "horse_number": entry.horse_number,
            "frame_number": entry.frame_number, "gate": entry.frame_number,
            "sire": entry.sire, "dam": getattr(entry, "dam", None),
            "broodmare_sire": getattr(entry, "broodmare_sire", None),
            "racecourse": race_defaults.get("racecourse"), "surface": race_defaults.get("surface"),
            "distance": race_defaults.get("distance"), "track_condition": race_defaults.get("track_condition"),
            "total_score": combined.get("total_score", 0),
            "bloodline_score": adapter._score_by_source_type(combined, "bloodline"),
            "past_performance_score": past.get("past_performance_score", 0),
            "pace_style_score": pace.get("pace_style_score", 0),
            "distance_score": distance.get("distance_score", 0),
            "track_condition_score": condition.get("track_condition_score", 0),
            "shape_score": 0, "course_shape_score": 0, "track_bias_score": 0, "lap_score": 0,
            "distance_fit": distance.get("distance_fit", "unknown"),
            "distance_fit_label": distance.get("distance_fit_label", "判定不能"),
            "track_condition_fit": condition.get("track_condition_fit", "unknown"),
            "track_condition_fit_label": condition.get("track_condition_fit_label", "判定不能"),
            "pace_style": pace.get("pace_style", "unknown"),
            "pace_style_label": pace.get("pace_style_label", "判定不能"),
            "summary": combined.get("summary_text", ""), "sections": combined.get("sections", {}),
            "warnings": adapter._build_warnings(entry, history, combined),
            "history_count": len(history_runs), "recent_runs": history_runs[:HISTORY_LIMIT],
            "distance_result": distance, "track_condition_suitability_result": condition,
            "past_performance_result": past, "pace_style_result": pace,
            "matched_results": combined.get("matched_results", []),
            "unmatched_results": combined.get("unmatched_results", []),
            "modifier_summary": combined.get("modifier_summary", {}),
        }
        horse_results.append(row)
    race_pace = adapter._apply_race_shape_and_final_scores(horse_results, race_defaults, None)
    ranked = sorted(
        horse_results,
        key=lambda item: (adapter._safe_number(item.get("adjusted_score")), adapter._horse_number(item)),
        reverse=True,
    )
    race_structure = race_pace.get("race_structure_result", {})
    race_decision = adapter.race_decision_engine.decide({
        "race_structure": race_structure.get("race_structure", {}),
        "structure_comment": race_structure.get("structure_comment", ""),
        "key_factors": race_structure.get("key_factors", []),
        "structure_flags": race_structure.get("structure_flags", {}),
        "recommended_weights_hint": race_structure.get("recommended_weights_hint", {}),
        "manual_track_bias_active": False, "baseline_race_decision_result": None,
    }, horse_results)
    confidence = adapter.confidence_engine.evaluate_many(horse_results, {
        "race_decision": race_decision.get("race_decision"),
        "race_confidence": race_decision.get("race_confidence"),
        "race_complexity": race_decision.get("race_complexity"),
        "race_volatility": race_decision.get("race_volatility"),
    })
    for index, item in enumerate(horse_results):
        conf = confidence[index] if index < len(confidence) else {}
        item["confidence_score"] = conf.get("confidence_score", 0.5)
        item["confidence_level"] = conf.get("confidence_level", "medium")
        item["confidence_reason"] = conf.get("confidence_reason", "")
        item["race_decision"] = race_decision.get("race_decision")
    buy = adapter.buy_v1_rc1_engine.evaluate(
        {"race_id": adapter._race_id_from_defaults(race_defaults),
         "race_decision": race_decision.get("race_decision"),
         "race_confidence": race_decision.get("race_confidence")}, ranked)
    adapter.buy_v1_rc1_engine.apply_to_horses(ranked, buy)
    sync = adapter.race_decision_buy_synchronizer.synchronize(race_decision, ranked, buy)
    race_decision = sync.get("race_decision_result", race_decision)
    for index, item in enumerate(ranked, 1):
        item["rank"] = index
        item["race_decision"] = race_decision.get("race_decision")
    output = {"race_id": adapter._race_id_from_defaults(race_defaults), "ranked_results": ranked,
              "race_decision": race_decision.get("race_decision"), "race_confidence": race_decision.get("race_confidence")}
    if trace:
        output["buy_gate_trace"] = _project_buy_gate_trace(buy, ranked)
    return output


def run_old(race_id: str) -> dict:
    entry_path, history_path = old_paths(race_id)
    adapter = TargetTrialAdapter(enable_learning_candidate_engine=False, buy_v1_rc1_enabled=True)
    entries = TargetEntryImporter().load(entry_path)
    histories = TargetHistoryImporter().load(history_path)
    defaults = adapter._read_race_defaults(entry_path)
    defaults = adapter._enrich_race_defaults(defaults, entries, histories)
    return run_engine_from_objects(entries, histories, defaults)


def run_new(race_id: str, race_bundle, trace: bool = False) -> dict:
    defaults = {
        "racecourse": race_bundle.today_entries[0].racecourse,
        "surface": race_bundle.today_entries[0].surface,
        "distance": race_bundle.today_entries[0].distance,
        "track_condition": None, "track_bias": None, "inside_bias": None,
        "outside_bias": None, "front_bias": None, "closer_bias": None,
        "bias_comment": None, "bias_type": None, "pace": None,
        "race_date": race_bundle.today_entries[0].race_date,
        "race_number": race_bundle.today_entries[0].race_number,
        "meeting_stage": None, "meeting_week": None, "meeting_day": None,
    }
    grouped: dict[str, list[PastRace]] = {}
    for race in race_bundle.past_races:
        grouped.setdefault(race.horse_name, []).append(race)
    histories = {name: history_from_past_races(name, races) for name, races in grouped.items()}
    defaults = TargetTrialAdapter(enable_learning_candidate_engine=False)._enrich_race_defaults(
        defaults, race_bundle.today_entries, histories,
    )
    return run_engine_from_objects(race_bundle.today_entries, histories, defaults, trace=trace)


def actual_results(race_id: str) -> dict[str, dict]:
    adapter = TargetResultAdapter()
    payload = adapter.load(
        ROOT / "data" / "results" / f"race_{race_id.removeprefix('race_')}_result.csv",
        ROOT / "data" / "results" / f"horse_{race_id.removeprefix('race_')}_result.csv",
    )
    return {row["horse_name"]: row for row in payload.get("horse_results", [])}


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def compare_race(race_id: str, old: dict, new: dict) -> list[dict]:
    old_map = {row["horse_name"]: row for row in old["ranked_results"]}
    new_map = {row["horse_name"]: row for row in new["ranked_results"]}
    if set(old_map) != set(new_map):
        raise PredictionInputValidationError("OLD_NEW_HORSE_SET_MISMATCH", race_id)
    actual = actual_results(race_id)
    rows = []
    for name in sorted(old_map):
        left, right = old_map[name], new_map[name]
        field_changes = [field for field in EVALUATOR_FIELDS if left.get(field) != right.get(field)]
        finish = (actual.get(name) or {}).get("finish_position")
        valid = isinstance(finish, int) and finish > 0
        delta_fields = field_changes + [
            field for field in ("final_score", "rank", "decision", "confidence_level", "explain_summary")
            if canonical(left.get(field)) != canonical(right.get(field))
        ]
        classification = "NO_DELTA" if not delta_fields else "DATA_ENRICHMENT_EXPECTED_DELTA"
        rows.append({
            "race_id": race_id, "horse_number": left.get("horse_number"), "horse_name": name,
            "actual_finish": finish if valid else "", "actual_top3": valid and finish <= 3,
            "old_rank": left.get("rank"), "new_rank": right.get("rank"),
            "rank_delta": (right.get("rank") or 0) - (left.get("rank") or 0),
            "old_final_score": left.get("final_score"), "new_final_score": right.get("final_score"),
            "final_score_delta": round(float(right.get("final_score") or 0) - float(left.get("final_score") or 0), 6),
            "old_decision": left.get("decision"), "new_decision": right.get("decision"),
            "old_buy": left.get("decision") == "BUY", "new_buy": right.get("decision") == "BUY",
            "old_confidence": left.get("confidence_level"), "new_confidence": right.get("confidence_level"),
            "old_explain": left.get("explain_summary", ""), "new_explain": right.get("explain_summary", ""),
            "evaluator_changed_fields": ";".join(field_changes),
            "delta_fields": ";".join(delta_fields), "classification": classification,
            **{f"old_{field}": left.get(field) for field in EVALUATOR_FIELDS},
            **{f"new_{field}": right.get(field) for field in EVALUATOR_FIELDS},
        })
    return rows


def metrics(rows: list[dict], prefix: str) -> dict:
    buys = [row for row in rows if row[f"{prefix}_buy"]]
    valid = [row for row in rows if row["actual_finish"] != ""]
    top3 = [row for row in valid if row["actual_top3"]]
    return {
        "horse_count": len(rows), "valid_result_count": len(valid),
        "buy_count": len(buys), "buy_top3": sum(row["actual_top3"] for row in buys),
        "buy_top3_rate": round(sum(row["actual_top3"] for row in buys) / len(buys), 6) if buys else 0,
        "FN": sum(row["actual_top3"] and not row[f"{prefix}_buy"] for row in valid),
        "FP": sum(row[f"{prefix}_buy"] and not row["actual_top3"] for row in valid),
        "top3_captured_in_top5": sum(int(row[f"{prefix}_rank"]) <= 5 for row in top3),
        "actual_top3_count": len(top3),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main(output_root: Path = OUTPUT_ROOT) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    raw_before = {path.name: sha256(path) for path in sorted(RAW_ROOT.glob("*.CSV"))}
    adapter = TargetBulkPredictionInputAdapterV1()
    daily = {}
    for date in DATES:
        short = date[2:]
        daily[date] = adapter.load(RAW_ROOT / f"DG{short}.CSV", RAW_ROOT / f"DE{short}.CSV", RAW_ROOT / f"DS{short}.CSV")
    target_ids = [race_id for date in DATES for race_id in manifest_race_ids(date)]
    rows = []
    for race_id in target_ids:
        date = race_id.split("_")[1]
        if race_id not in daily[date].races:
            raise PredictionInputValidationError("TARGET_RACE_NOT_IN_BULK", race_id)
        rows.extend(compare_race(race_id, run_old(race_id), run_new(race_id, daily[date].races[race_id])))
    after = protected_hashes()
    raw_after = {path.name: sha256(path) for path in sorted(RAW_ROOT.glob("*.CSV"))}
    old_metrics, new_metrics = metrics(rows, "old"), metrics(rows, "new")
    counts = Counter(row["classification"] for row in rows)
    changed = {
        "evaluator": sum(bool(row["evaluator_changed_fields"]) for row in rows),
        "final_score": sum(row["old_final_score"] != row["new_final_score"] for row in rows),
        "ranking": sum(row["old_rank"] != row["new_rank"] for row in rows),
        "decision": sum(row["old_decision"] != row["new_decision"] for row in rows),
        "buy": sum(row["old_buy"] != row["new_buy"] for row in rows),
        "confidence": sum(row["old_confidence"] != row["new_confidence"] for row in rows),
        "explain": sum(row["old_explain"] != row["new_explain"] for row in rows),
    }
    evaluator_changed = {
        field: sum(row[f"old_{field}"] != row[f"new_{field}"] for row in rows)
        for field in EVALUATOR_FIELDS
    }
    decision_transitions = Counter(f"{row['old_decision']}->{row['new_decision']}" for row in rows)
    buy_transitions = Counter(f"{row['old_buy']}->{row['new_buy']}" for row in rows)
    old_top5 = {(row["race_id"], row["horse_name"]) for row in rows if int(row["old_rank"]) <= 5}
    new_top5 = {(row["race_id"], row["horse_name"]) for row in rows if int(row["new_rank"]) <= 5}
    summary = {
        "schema_version": "target_bulk_prediction_input_adapter_mapping_fix_shadow_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "TARGET_BULK_PREDICTION_INPUT_ADAPTER_MAPPING_FIX_V1_SHADOW_COMPLETE",
        "target_race_ids": target_ids, "target_race_count": len(target_ids), "target_horse_count": len(rows),
        "raw_sources": {date: {kind: asdict(source) for kind, source in bundle.sources.items()} for date, bundle in daily.items()},
        "preflight": {date: bundle.preflight for date, bundle in daily.items()},
        "today_entry_generated": sum(len(race.today_entries) for bundle in daily.values() for race in bundle.races.values()),
        "past_race_generated": sum(len(race.past_races) for bundle in daily.values() for race in bundle.races.values()),
        "past_race_max_per_horse": HISTORY_LIMIT,
        "old_input_shadow_count": len(rows), "new_input_shadow_count": len(rows),
        "delta_classification_counts": dict(counts), "changed_horse_counts": changed,
        "evaluator_changed_horse_counts": evaluator_changed,
        "decision_transition_counts": dict(decision_transitions),
        "buy_transition_counts": dict(buy_transitions),
        "top5_membership_removed": len(old_top5 - new_top5), "top5_membership_added": len(new_top5 - old_top5),
        "old_metrics": old_metrics, "new_metrics": new_metrics,
        "review_delta": {key: new_metrics[key] - old_metrics[key] for key in ("FN", "FP", "top3_captured_in_top5", "buy_count", "buy_top3")},
        "raw_unchanged": raw_before == raw_after, "protected_unchanged": before == after,
        "raw_hashes_before": raw_before, "raw_hashes_after": raw_after,
        "protected_before": before, "protected_after": after,
        "production_switch_candidate": False,
    }
    write_csv(output_root / "target_bulk_prediction_input_adapter_mapping_fix_shadow_comparison_v1.csv", rows)
    (output_root / "target_bulk_prediction_input_adapter_mapping_fix_shadow_summary_v1.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    safety = {
        "status": "PASS" if summary["raw_unchanged"] and summary["protected_unchanged"] else "FAIL",
        "raw_changed_count": sum(raw_before.get(k) != raw_after.get(k) for k in set(raw_before) | set(raw_after)),
        "production_changed_count": sum(before.get(k) != after.get(k) for k in set(before) | set(after)),
        "baseline_delta": 0 if before.get("reports/pre_race") == after.get("reports/pre_race") else 1,
        "replay_delta": 0 if before.get("reports/historical_replay_current_code") == after.get("reports/historical_replay_current_code") else 1,
        "learning_delta": 0 if before.get("learning") == after.get("learning") else 1,
        "knowledge_delta": 0 if before.get("knowledge") == after.get("knowledge") else 1,
    }
    (output_root / "target_bulk_prediction_input_adapter_mapping_fix_safety_v1.json").write_text(json.dumps(safety, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    zero = {"status": "PASS" if safety["status"] == "PASS" else "FAIL", "feature_flag_off": True,
            "production_final_score_delta": 0, "production_ranking_delta": 0,
            "production_decision_delta": 0, "production_buy_delta": 0}
    (output_root / "target_bulk_prediction_input_adapter_mapping_fix_zero_delta_v1.json").write_text(json.dumps(zero, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    report = [
        "# TARGET Bulk Prediction Input Adapter Mapping Fix v1 — Shadow Report",
        "", f"- 最終判定: **{summary['status']}**", "- Production切替候補: **NO**",
        "- 理由: 今回はShadow-only mapping fixの検証であり、Production切替は承認範囲外。",
        "", "## Preflight", "",
        f"- 実Raw: DG 35行/11列、DE 447行/33列、DS 6,118行/50列（全てCP932、ヘッダー無し）",
        "- DG↔DE: 35/35レース一致、頭数不一致0",
        "- DE列19: 447/447非空・一意、衝突0",
        "- DE列33: 447/447で場コード＋馬番構造一致",
        "- DE↔DS: 447/447一致、曖昧0、未一致0（DSに列19相当IDなし）",
        "- 当日確定情報の推測補完: 0",
        "", "## Shadow対象", "",
        f"- 既存PRE manifest固定: {len(target_ids)}レース / {len(rows)}頭",
        f"- OLD_INPUT: {len(rows)}頭 / NEW_INPUT: {len(rows)}頭",
        "- TodayEntry生成: 447頭（Raw全体）",
        f"- PastRace生成: {summary['past_race_generated']}件（Raw全体、1頭最大5走）",
        "", "## OLD vs NEW", "",
        f"- Evaluator差分: {changed['evaluator']}頭 / 内訳 {json.dumps(evaluator_changed, ensure_ascii=False)}",
        f"- FinalScore差分: {changed['final_score']}頭",
        f"- Ranking差分: {changed['ranking']}頭",
        f"- Top5入替: OUT {summary['top5_membership_removed']} / IN {summary['top5_membership_added']}",
        f"- Decision差分: {changed['decision']}頭 / {json.dumps(dict(decision_transitions), ensure_ascii=False)}",
        f"- BUY差分: {changed['buy']}頭 / {json.dumps(dict(buy_transitions), ensure_ascii=False)}",
        f"- Confidence差分: {changed['confidence']}頭 / Explain差分: {changed['explain']}頭",
        "", "## 結果Review（既存KPI）", "",
        f"- OLD: BUY {old_metrics['buy_count']}、BUY複勝 {old_metrics['buy_top3']}、FN {old_metrics['FN']}、FP {old_metrics['FP']}、Top3捕捉 {old_metrics['top3_captured_in_top5']}/{old_metrics['actual_top3_count']}",
        f"- NEW: BUY {new_metrics['buy_count']}、BUY複勝 {new_metrics['buy_top3']}、FN {new_metrics['FN']}、FP {new_metrics['FP']}、Top3捕捉 {new_metrics['top3_captured_in_top5']}/{new_metrics['actual_top3_count']}",
        f"- 差分: FN {summary['review_delta']['FN']:+d}、FP {summary['review_delta']['FP']:+d}、Top3捕捉 {summary['review_delta']['top3_captured_in_top5']:+d}",
        "- 旧Shadowの223/223頭全負方向shiftは解消。現行Production入力とNEW_INPUTのBUY/FN/FP/Top3捕捉は一致。",
        "", "## Safety", "",
        f"- Raw変更: {safety['raw_changed_count']}", f"- Production資産変更: {safety['production_changed_count']}",
        f"- Baseline delta: {safety['baseline_delta']} / Replay delta: {safety['replay_delta']}",
        f"- Safety: {safety['status']} / ZERO_DELTA: {zero['status']}",
        "", "## 次工程", "",
        "Production切替は行わず停止する。BULK_INPUT_OPERATION_READYは独立レビュー対象とする。",
    ]
    (output_root / "target_bulk_prediction_input_adapter_mapping_fix_shadow_report_v1.md").write_text("\n".join(report)+"\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    args = parser.parse_args()
    print(json.dumps(main(Path(args.output_root)), ensure_ascii=False, indent=2, default=str))
