"""Formal result-free Prospective PRE lane for frozen TrackCondition semantics."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.track_condition_semantic_shadow_v1 import run_race_pair

PROTOCOL = ROOT / "docs" / "track_condition_semantic_shadow_prospective_protocol_v1.json"
FROZEN_PROTOCOL_SHA256 = "db8bff65e856613003647d1e53b883df3e54b17e7ed0c2673723c95a3185c08f"
RESULT_KEYS = {"actual_finish", "actual_top3", "valid_result", "finish", "result", "payout", "daily_result_list"}
JST = timezone(timedelta(hours=9))


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise Stop("STOP_INDEPENDENT_ARTIFACT_MISSING")
    return {str(path.relative_to(root)).replace("\\", "/"): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def canonical(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def ensure_output_isolated(output_root: Path, independent_root: Path, current_root: Path) -> None:
    output = canonical(output_root)
    for protected in (canonical(independent_root), canonical(current_root)):
        if output == protected or output.is_relative_to(protected):
            raise Stop("STOP_TRACKCONDITION_OUTPUT_ROOT_ISOLATION")


def verify_tree_unchanged(before: dict[str, str], root: Path, code: str) -> None:
    if before != tree_hashes(root):
        raise Stop(code)


def validate_execution_date(target_date: str, execution: datetime) -> str:
    try:
        datetime.strptime(target_date, "%Y%m%d")
    except (TypeError, ValueError) as exc:
        raise Stop("STOP_TRACKCONDITION_EXECUTION_DATE_UNPARSABLE") from exc
    execution_date_jst = execution.astimezone(JST).strftime("%Y%m%d")
    if target_date < execution_date_jst:
        raise Stop("STOP_TRACKCONDITION_POST_EVENT_EXECUTION")
    return execution_date_jst


def central_jra_meeting_week_id(target_date: str) -> str:
    """Return the JST Saturday anchoring the target date's central meeting week.

    This deliberately depends only on the PRE target date.  It is not derived
    from a result, POST artifact, or an observed actual-race date.
    """
    try:
        target_jst = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    except (TypeError, ValueError) as exc:
        raise Stop("STOP_TRACKCONDITION_TARGET_DATE_UNPARSABLE") from exc
    anchor = target_jst - timedelta(days=(target_jst.weekday() - 5) % 7)
    return anchor.strftime("%Y%m%d")


def normalize_actual_race_date(value: object) -> str:
    """Normalize only direct ISO/compact date representations; never infer a date."""
    raw = str(value).strip()
    if len(raw) == 8 and raw.isdigit():
        return raw
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-" and raw.replace("-", "").isdigit():
        return raw.replace("-", "")
    raise Stop("HOLD_MIXED_ACTUAL_RACE_DATES")


def assert_result_free(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in RESULT_KEYS:
                raise Stop("STOP_RESULT_LEAKAGE")
            assert_result_free(child)
    elif isinstance(value, list):
        for child in value:
            assert_result_free(child)


def load_protocol() -> dict[str, Any]:
    if sha(PROTOCOL) != FROZEN_PROTOCOL_SHA256:
        raise Stop("STOP_PROTOCOL_SHA_MISMATCH")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    required = {"role", "human_approval_freeze_date", "minimum_evidence", "prospective_boundaries", "result_free_pre", "independent_isolation", "independent_block_definition", "selected_race_definition", "invalid_result_semantics", "execution_date_guard", "actual_race_date_scope"}
    if set(required) - set(protocol) or protocol.get("role") != "FORMAL_PROSPECTIVE_TRACK_CONDITION_SEMANTIC_SHADOW":
        raise Stop("STOP_PROTOCOL_INVALID")
    minimum = protocol["minimum_evidence"]
    if (minimum.get("independent_blocks"), minimum.get("race_dates"), minimum.get("selected_races")) != (2, 4, 60):
        raise Stop("STOP_MINIMUM_EVIDENCE_INVALID")
    rules = protocol["decision_rules"]
    if set(("before_minimum", "accept_candidate", "reject", "extend")) - set(rules):
        raise Stop("STOP_DECISION_RULE_INVALID")
    return protocol


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _current_rows(current_pre_root: Path, target_date: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    summary = json.loads((current_pre_root / "summary.json").read_text(encoding="utf-8"))
    provenance = json.loads((current_pre_root / "provenance.json").read_text(encoding="utf-8"))
    index = json.loads((current_pre_root / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    manifest = json.loads((current_pre_root / "prediction_manifest.json").read_text(encoding="utf-8"))
    if summary.get("date") != target_date or provenance.get("target_date") != target_date:
        raise Stop("STOP_TRACKCONDITION_CONTROL_REPRODUCTION_FAILURE:CURRENT_SCOPE")
    if any(sha(current_pre_root / entry["relative_path"]) != entry["sha256"] for entry in manifest["files"]):
        raise Stop("STOP_CURRENT_PRE_HASH_MISMATCH")
    values = {}
    for item in index:
        payload = json.loads((current_pre_root / item["artifact"]).read_text(encoding="utf-8"))
        assert_result_free(payload)
        values[payload["race_id"]] = payload
    return values, summary, provenance


def validate_gates(target_date: str, protocol: dict[str, Any], current_summary: dict[str, Any], current_provenance: dict[str, Any], execution: datetime) -> dict[str, str]:
    if target_date <= protocol["human_approval_freeze_date"]:
        raise Stop("STOP_TRACKCONDITION_G1")
    if current_summary.get("date") != target_date:
        raise Stop("STOP_TRACKCONDITION_G2")
    try:
        generated = datetime.fromisoformat(str(current_provenance["generated_at"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise Stop("STOP_TRACKCONDITION_G3") from exc
    if generated > execution.astimezone(timezone.utc) or current_provenance.get("result_data_access_count") != 0:
        raise Stop("STOP_TRACKCONDITION_G3")
    if current_provenance.get("target_date") != target_date:
        raise Stop("STOP_TRACKCONDITION_G4")
    return {"G1": "PASS", "G2": "PASS", "G3": "PASS", "G4": "PASS"}


def _buy_set(rows: list[dict[str, Any]], *, current: bool) -> set[int]:
    return {int(row["horse_number"]) for row in rows if bool(row.get("buy") if current else row.get("buy_v1_rc1_buy"))}


def compare_control_to_current(control: dict[str, Any], current: dict[str, Any]) -> None:
    control_rows = {int(row["horse_number"]): row for row in control["ranked_results"]}
    current_rows = {int(row["horse_number"]): row for row in current["ranked_results"]}
    if set(control_rows) != set(current_rows):
        raise Stop("STOP_TRACKCONDITION_CONTROL_REPRODUCTION_FAILURE:HORSE_SET")
    if _buy_set(list(control_rows.values()), current=False) != _buy_set(list(current_rows.values()), current=True):
        raise Stop("STOP_TRACKCONDITION_CONTROL_REPRODUCTION_FAILURE:BUY_SET")
    if control["race_decision"] != current.get("race_decision"):
        raise Stop("STOP_TRACKCONDITION_CONTROL_REPRODUCTION_FAILURE:RACE_DECISION")
    states = {row.get("buy_v1_rc1_race_state") for row in control_rows.values()}
    current_state = current.get("buy_gate_trace", {}).get("race", {}).get("shadow_race_state")
    if len(states) != 1 or next(iter(states)) != current_state:
        raise Stop("STOP_TRACKCONDITION_CONTROL_REPRODUCTION_FAILURE:RACE_STATE")
    for number, control_row in control_rows.items():
        frozen = current_rows[number]
        for key in ("rank", "adjusted_score"):
            if control_row.get(key) != frozen.get(key):
                raise Stop(f"STOP_TRACKCONDITION_CONTROL_REPRODUCTION_FAILURE:{key}:{number}")


def _race_state(result: dict[str, Any]) -> str | None:
    values = {row.get("buy_v1_rc1_race_state") for row in result["ranked_results"]}
    return next(iter(values)) if len(values) == 1 else None


def run(target_date: str, dg: Path, de: Path, ds: Path, current_pre_root: Path, independent_pre_root: Path, output_root: Path, *, clock_utc: datetime | None = None) -> Path:
    protocol = load_protocol()
    if output_root.exists():
        raise Stop("STOP_OUTPUT_EXISTS")
    execution = datetime.now(timezone.utc) if clock_utc is None else clock_utc.astimezone(timezone.utc)
    execution_date_jst = validate_execution_date(target_date, execution)
    meeting_week_id = central_jra_meeting_week_id(target_date)
    ensure_output_isolated(output_root, independent_pre_root, current_pre_root)
    independent_before = tree_hashes(independent_pre_root)
    current_before = tree_hashes(current_pre_root)
    current, summary, provenance = _current_rows(current_pre_root, target_date)
    gates = validate_gates(target_date, protocol, summary, provenance, execution)
    bundle = TargetBulkPredictionInputAdapterV1().load(dg, de, ds)
    if bundle.date != target_date:
        raise Stop("STOP_TRACKCONDITION_G2:INPUT_DATE")
    raw_actual_dates = {str(race.today_entries[0].race_date) for race in bundle.races.values()}
    actual_dates = {normalize_actual_race_date(value) for value in raw_actual_dates}
    if len(actual_dates) != 1 or actual_dates != {target_date}:
        raise Stop("HOLD_MIXED_ACTUAL_RACE_DATES")
    horse_rows, race_rows = [], []
    for race_id, race_bundle in bundle.races.items():
        if race_id not in current:
            raise Stop("STOP_TRACKCONDITION_CONTROL_REPRODUCTION_FAILURE:CURRENT_RACE_MISSING")
        control, shadow, field_history = run_race_pair(race_bundle)
        compare_control_to_current(control, current[race_id])
        crows = {int(row["horse_number"]): row for row in control["ranked_results"]}
        srows = {int(row["horse_number"]): row for row in shadow["ranked_results"]}
        entry = race_bundle.today_entries[0]
        trace_by_number = {int(row["horse_number"]): row for row in current[race_id].get("buy_gate_trace", {}).get("horses", [])}
        control_state, shadow_state = _race_state(control), _race_state(shadow)
        race_rows.append({"date": target_date, "actual_race_date": entry.race_date, "race_id": race_id, "venue": entry.racecourse, "race_number": entry.race_number,
                          "control_race_decision": control["race_decision"], "shadow_race_decision": shadow["race_decision"],
                          "control_race_state": control_state, "shadow_race_state": shadow_state,
                          "control_buy_count": len(_buy_set(list(crows.values()), current=False)), "shadow_buy_count": len(_buy_set(list(srows.values()), current=False)),
                          "transition": f"{control_state}_TO_{shadow_state}", "field_history_track_condition": field_history, "control_reproduction": "PASS"})
        for number, control_row in crows.items():
            shadow_row = srows[number]
            horse_rows.append({"date": target_date, "actual_race_date": entry.race_date, "venue": entry.racecourse, "race_number": entry.race_number, "race_id": race_id,
                               "horse_number": number, "horse_name": control_row.get("horse_name"), "control_selected": bool(control_row.get("buy_v1_rc1_buy")), "control_rank": control_row.get("rank"),
                               "control_score": control_row.get("adjusted_score"), "control_decision": control_row.get("decision"), "control_race_state": control_state,
                               "shadow_selected": bool(shadow_row.get("buy_v1_rc1_buy")), "shadow_rank": shadow_row.get("rank"), "shadow_score": shadow_row.get("adjusted_score"),
                               "shadow_decision": shadow_row.get("decision"), "shadow_race_state": shadow_state, "control_track_condition_score": control_row.get("track_condition_score"),
                               "shadow_track_condition_score": shadow_row.get("track_condition_score"), "control_past_performance_score": control_row.get("past_performance_score"),
                               "shadow_past_performance_score": shadow_row.get("past_performance_score"), "race_track_condition": "UNKNOWN", "field_history_track_condition": field_history,
                               "historical_track_condition_preserved": True, "risk_guard_pass": trace_by_number.get(number, {}).get("risk_guard_pass"),
                               "shadow_ai_rank": trace_by_number.get(number, {}).get("shadow_ai_rank")})
    output_root.mkdir(parents=True)
    _write(output_root / "horse_level_trace.json", {"date": target_date, "rows": horse_rows, "result_data_access_count": 0})
    _write(output_root / "race_level_trace.json", {"date": target_date, "rows": race_rows, "result_data_access_count": 0})
    _write(output_root / "summary.json", {"date": target_date, "actual_date": target_date, "central_jra_meeting_week_id": meeting_week_id, "eligible_races": len(race_rows), "horse_count": len(horse_rows),
                                              "control_selected_horses": sum(x["control_selected"] for x in horse_rows), "shadow_selected_horses": sum(x["shadow_selected"] for x in horse_rows),
                                              "control_selected_races": sum(x["control_buy_count"] > 0 for x in race_rows), "shadow_selected_races": sum(x["shadow_buy_count"] > 0 for x in race_rows),
                                              "control_reproduction": "PASS", "result_data_access_count": 0, "production_authorization": False})
    _write(output_root / "provenance.json", {"target_date": target_date, "central_jra_meeting_week_id": meeting_week_id, "actual_race_date": next(iter(raw_actual_dates)), "actual_race_date_normalized": next(iter(actual_dates)), "execution_date_jst": execution_date_jst, "generated_at": execution.isoformat(), "runner": str(Path(__file__).relative_to(ROOT)), "runner_sha256": sha(Path(__file__)),
                                                 "protocol_sha256": sha(PROTOCOL), "start_boundary": gates, "independent_tree_sha256_before": independent_before,
                                                 "final_independent_mutation_check": "AFTER_ALL_OUTPUT_WRITES", "final_current_frozen_mutation_check": "AFTER_ALL_OUTPUT_WRITES",
                                                 "result_data_access_count": 0, "production_change": 0})
    files = [path for path in output_root.iterdir() if path.is_file()]
    _write(output_root / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": {path.name: sha(path) for path in files}})
    verify_tree_unchanged(independent_before, independent_pre_root, "STOP_INDEPENDENT_PRE_MUTATED")
    verify_tree_unchanged(current_before, current_pre_root, "STOP_CURRENT_FROZEN_MUTATED")
    return output_root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--date", required=True); parser.add_argument("--dg", type=Path, required=True); parser.add_argument("--de", type=Path, required=True); parser.add_argument("--ds", type=Path, required=True); parser.add_argument("--current-pre", type=Path, required=True); parser.add_argument("--independent-pre", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); print(run(args.date, args.dg, args.de, args.ds, args.current_pre, args.independent_pre, args.output))
