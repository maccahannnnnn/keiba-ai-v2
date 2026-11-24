"""Roadmap v3 result-free PRE diagnostic infrastructure.

This additive module consumes frozen Current PRE artifacts, a frozen Next-PRE
full-field V5 diagnostic, and Formal-V5 tie-break identity.  It never invokes
a prediction engine, re-infers a probability, changes a lane, reads Result
content, or creates a BUY/Production decision.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
RESULT_KEYS = {"actual_top3", "actual_finish", "finish", "valid_result", "result", "payout"}
TIE_BREAK = ("p_top3 DESC", "shadow_ai_rank ASC", "race_id ASC", "horse_number ASC")


class RoadmapStop(RuntimeError):
    """Fail-closed stop for the Roadmap v3 PRE layer."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _truth(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _int(value: Any, label: str) -> int:
    """Normalize only exact integer semantics at the CSV adapter boundary."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise RoadmapStop(f"STOP_ROADMAP_V3_INVALID_{label}")
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise RoadmapStop(f"STOP_ROADMAP_V3_INVALID_{label}") from error
    if number != number or number in (float("inf"), float("-inf")) or not number.is_integer():
        raise RoadmapStop(f"STOP_ROADMAP_V3_INVALID_{label}")
    return int(number)


def _float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise RoadmapStop(f"STOP_ROADMAP_V3_INVALID_{label}") from error
    if number != number or number in (float("inf"), float("-inf")):
        raise RoadmapStop(f"STOP_ROADMAP_V3_INVALID_{label}")
    return number


def assert_result_free(value: Any, context: str = "pre") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in RESULT_KEYS:
                raise RoadmapStop(f"STOP_ROADMAP_V3_RESULT_FIELD_IN_PRE:{context}:{key}")
            assert_result_free(child, context)
    elif isinstance(value, list):
        for child in value:
            assert_result_free(child, context)


def _result_source_exists(target_date: str, repository_root: Path) -> bool:
    root = repository_root / "data" / "raw" / "target" / "daily_result_list"
    names = (f"着順馬番_{target_date}.csv", f"馬番順着順_{target_date}.csv")
    return any((root / name).exists() for name in names)


def assert_evidence_start(
    *, target_date: str, execution_spec_approval_date: str, implementation_verified: bool,
    artifact_sha_frozen: bool,
) -> dict[str, Any]:
    if not (target_date.isdigit() and execution_spec_approval_date.isdigit() and len(target_date) == len(execution_spec_approval_date) == 8):
        raise RoadmapStop("STOP_ROADMAP_V3_EVIDENCE_START_DATE_FORMAT")
    if not implementation_verified or not artifact_sha_frozen:
        raise RoadmapStop("STOP_ROADMAP_V3_EVIDENCE_START_PREREQUISITE")
    if target_date <= execution_spec_approval_date:
        raise RoadmapStop("STOP_ROADMAP_V3_EVIDENCE_START_NOT_STRICTLY_AFTER_APPROVAL")
    return {"target_date": target_date, "evidence_start_eligible": True, "retroactive_counting": False}


def execution_date_jst(now_utc: datetime | None = None) -> str:
    """Reuse the fixed UTC+09:00 semantics of the closed Next-PRE guard."""
    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d")


def validate_pre_timing(*, target_date: str, execution_date: str | None = None, repository_root: Path = ROOT) -> dict[str, Any]:
    execution = execution_date or execution_date_jst()
    if not (target_date.isdigit() and execution.isdigit() and len(target_date) == len(execution) == 8):
        raise RoadmapStop("STOP_ROADMAP_V3_PRE_DATE_FORMAT")
    if target_date < execution:
        raise RoadmapStop("STOP_PAST_DATE_ROADMAP_V3_PRE")
    if _result_source_exists(target_date, repository_root):
        raise RoadmapStop("STOP_ROADMAP_V3_RESULT_SOURCE_EXISTS_BEFORE_PRE_FREEZE")
    return {"target_date": target_date, "execution_date_jst": execution, "result_source_existence_check": "PASS"}


def validate_verification_manifest(path: Path, expected: dict[str, str]) -> tuple[dict[str, Any], str]:
    """Validate independent-review acceptance and pin every required source SHA."""
    if not path.is_file():
        raise RoadmapStop("STOP_ROADMAP_V3_INFRASTRUCTURE_NOT_VERIFIED")
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = ("execution_spec_sha", "amendment_sha", "active_contract_sha", "implementation_file_sha", "relevant_test_file_sha", "test_status", "independent_review_status", "human_authorization_status", "verification_timestamp_jst", "verification_record_sha")
    if any(key not in payload for key in required):
        raise RoadmapStop("STOP_ROADMAP_V3_INFRASTRUCTURE_NOT_VERIFIED")
    record = dict(payload); stated = str(record.pop("verification_record_sha"))
    if canonical_sha(record) != stated:
        raise RoadmapStop("STOP_ROADMAP_V3_INFRASTRUCTURE_NOT_VERIFIED")
    if payload.get("test_status") != "PASS" or payload.get("independent_review_status") != "ACCEPT" or payload.get("human_authorization_status") is not True:
        raise RoadmapStop("STOP_ROADMAP_V3_INFRASTRUCTURE_NOT_VERIFIED")
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RoadmapStop("STOP_ROADMAP_V3_INFRASTRUCTURE_NOT_VERIFIED")
    return payload, sha256(path)


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RoadmapStop("STOP_ROADMAP_V3_EMPTY_ANALYSIS")
    assert_result_free(rows, "all_active_systems_horse_analysis")
    return rows


def _current_authority(current_pre_root: Path, target_date: str) -> tuple[set[str], dict[str, dict[str, Any]], dict[str, str]]:
    provenance_path = current_pre_root / "provenance.json"
    index_path = current_pre_root / "race_index.json"
    manifest_path = current_pre_root / "prediction_manifest.json"
    if not provenance_path.is_file() or not index_path.is_file() or not manifest_path.is_file():
        raise RoadmapStop("STOP_ROADMAP_V3_CURRENT_PRE_INTEGRITY")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance.get("target_date") != target_date or provenance.get("result_data_access_count") != 0:
        raise RoadmapStop("STOP_ROADMAP_V3_CURRENT_PRE_INTEGRITY")
    index = json.loads(index_path.read_text(encoding="utf-8")).get("race_index")
    if not isinstance(index, list) or not index:
        raise RoadmapStop("STOP_ROADMAP_V3_CURRENT_RACE_INDEX_INVALID")
    races: dict[str, dict[str, Any]] = {}
    for entry in index:
        artifact = current_pre_root / str(entry.get("artifact", ""))
        if not artifact.is_file():
            raise RoadmapStop("STOP_ROADMAP_V3_CURRENT_ARTIFACT_MISSING")
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert_result_free(payload, f"current:{artifact.name}")
        race_id = str(payload.get("race_id", ""))
        ranked = payload.get("ranked_results")
        if not race_id or not isinstance(ranked, list) or not ranked:
            raise RoadmapStop("STOP_ROADMAP_V3_CURRENT_ARTIFACT_INVALID")
        races[race_id] = payload
    if len(races) != len(index):
        raise RoadmapStop("STOP_ROADMAP_V3_CURRENT_RACE_ID_DUPLICATE")
    return set(races), races, {
        "current_provenance_sha256": sha256(provenance_path),
        "current_race_index_sha256": sha256(index_path),
        "current_prediction_manifest_sha256": sha256(manifest_path),
    }


def _formal_identity(path: Path) -> dict[str, Any]:
    """Normalize a frozen Formal-V5 identity without invoking its runtime.

    The normal Formal dual PRE stores V5 identity in ``v5_identity`` and the
    runtime label in its sibling ``run_metadata.json``.  A dedicated identity
    document is also accepted for tests or a future explicit export.
    """
    source = json.loads(path.read_text(encoding="utf-8"))
    identity = dict(source.get("v5_identity") or source)
    runtime = identity.get("runtime_identity") or source.get("runtime_identity")
    metadata = path.parent / "run_metadata.json"
    if not runtime and metadata.is_file():
        runtime = json.loads(metadata.read_text(encoding="utf-8")).get("runtime")
    if runtime:
        identity["runtime_identity"] = runtime
    if not identity.get("model_sha256") or not identity.get("runtime_identity"):
        raise RoadmapStop("STOP_ROADMAP_V3_V5_RUNTIME_IDENTITY_UNPROVEN")
    return identity


def comparison_a_records(
    *, target_date: str, current_races: dict[str, dict[str, Any]], rows: list[dict[str, str]],
    formal_identity: dict[str, Any],
) -> dict[str, Any]:
    """Build the pre-result same-volume set from stored Formal-V5 probabilities."""
    assert_result_free(rows, "comparison_a_rows")
    by_race: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_race[str(row.get("race_id", ""))].append(row)
    current_ids = set(current_races)
    if set(by_race) != current_ids:
        raise RoadmapStop("STOP_ROADMAP_V3_COMPARISON_A_RACE_SET_MISMATCH")

    budget = sum(sum(_truth(horse.get("buy")) for horse in payload["ranked_results"]) for payload in current_races.values())
    race_rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    unavailable_horses = 0
    for race_id in sorted(current_ids):
        payload = current_races[race_id]
        current_horses = {str(horse.get("horse_number")): horse for horse in payload["ranked_results"]}
        source_rows = by_race[race_id]
        if {str(row.get("horse_number")) for row in source_rows} != set(current_horses):
            raise RoadmapStop("STOP_ROADMAP_V3_COMPARISON_A_HORSE_SET_MISMATCH")
        missing_probability = any(str(row.get("formal_v5_probability", "")).strip() == "" for row in source_rows)
        if missing_probability:
            unavailable_horses += len(source_rows)
            race_rows.append({"race_id": race_id, "race_status": "DIAGNOSTIC_INFERENCE_UNAVAILABLE", "candidate_count": 0, "horses": []})
            continue
        state = payload.get("buy_gate_trace", {}).get("race", {}).get("shadow_race_state")
        current_top5 = {str(horse.get("horse_number")) for horse in payload.get("top5", [])}
        local: list[dict[str, Any]] = []
        for row in source_rows:
            number = str(row["horse_number"])
            horse = current_horses[number]
            trace_rows = payload.get("buy_gate_trace", {}).get("horses", [])
            trace = next((item for item in trace_rows if str(item.get("horse_number")) == number), None)
            rank = row.get("current_shadow_ai_rank") or (trace or {}).get("shadow_ai_rank")
            local.append({
                "target_date": target_date, "race_id": race_id, "venue": row.get("venue") or payload.get("venue"),
                "race_number": row.get("race_number") or payload.get("race_number"), "horse_number": _int(number, "HORSE_NUMBER"),
                "horse_name": horse.get("horse_name"), "p_top3": _float(row["formal_v5_probability"], "FORMAL_V5_PROBABILITY"),
                "shadow_ai_rank": _int(rank, "SHADOW_AI_RANK"), "current_top5_membership": number in current_top5,
                "current_race_state": state, "selected": False, "unavailable": False,
            })
        candidates.extend(local)
        race_rows.append({"race_id": race_id, "race_status": "AVAILABLE", "candidate_count": len(local), "horses": local})

    if budget == 0:
        selected: set[tuple[str, int]] = set()
        zero_budget = True
    else:
        zero_budget = False
        ordered = sorted(candidates, key=lambda item: (-item["p_top3"], item["shadow_ai_rank"], item["race_id"], item["horse_number"]))
        selected = {(item["race_id"], item["horse_number"]) for item in ordered[:budget]}
    for item in candidates:
        item["selected"] = (item["race_id"], item["horse_number"]) in selected
    for record in race_rows:
        for item in record["horses"]:
            item["selected"] = (item["race_id"], item["horse_number"]) in selected

    selected_rows = [item for item in candidates if item["selected"]]
    for rank, item in enumerate(sorted(candidates, key=lambda value: (-value["p_top3"], value["shadow_ai_rank"], value["race_id"], value["horse_number"])), 1):
        item["deterministic_rank"] = rank
    return {
        "schema_version": "roadmap_v3_comparison_a_pre_v1",
        "role": "ROADMAP_V3_PRIMARY_COMPARISON_A",
        "target_date": target_date, "result_access_count": 0, "formal_evidence": False,
        "production_change": False, "new_buy_rule_created": False,
        "model_identity": formal_identity, "tie_break_rule": list(TIE_BREAK),
        "budget_n": budget, "zero_budget_status": "ZERO_BUDGET_NOT_COUNTED" if zero_budget else "NONZERO_BUDGET",
        "unavailable_race_count": sum(record["race_status"] != "AVAILABLE" for record in race_rows),
        "unavailable_horse_count": unavailable_horses, "candidate_pool_size": len(candidates),
        "selected_n": len(selected_rows), "shortfall": max(0, budget - len(selected_rows)),
        "selected_current_top5_count": sum(item["current_top5_membership"] for item in selected_rows),
        "selected_outside_current_top5_count": sum(not item["current_top5_membership"] for item in selected_rows),
        "race_records": race_rows,
        "selected_horses": sorted(selected_rows, key=lambda item: item["deterministic_rank"]),
    }


def comparison_b_pre(rows: list[dict[str, str]]) -> dict[str, Any]:
    assert_result_free(rows, "comparison_b_rows")
    groups = {"BOTH_SELECTED": [], "CURRENT_ONLY": [], "FORMAL_ONLY": []}
    independent_races: set[str] = set()
    for row in rows:
        current, formal = _truth(row.get("current_buy")), _truth(row.get("formal_v5_selected"))
        if current or formal:
            independent_races.add(str(row["race_id"]))
            groups["BOTH_SELECTED" if current and formal else "CURRENT_ONLY" if current else "FORMAL_ONLY"].append({
                "race_id": row["race_id"], "horse_number": _int(row["horse_number"], "HORSE_NUMBER"), "horse_name": row.get("horse_name"),
            })
    return {
        "schema_version": "roadmap_v3_comparison_b_pre_v1", "role": "ROADMAP_V3_PRIMARY_COMPARISON_B",
        "same_volume": False, "result_access_count": 0, "formal_evidence": False,
        "independent_race_count": len(independent_races), "overlap_decomposition": groups,
        "current_selected_n": len(groups["BOTH_SELECTED"]) + len(groups["CURRENT_ONLY"]),
        "formal_selected_n": len(groups["BOTH_SELECTED"]) + len(groups["FORMAL_ONLY"]),
    }


def comparison_a_from_full_field_diagnostic(
    *, target_date: str, current_races: dict[str, dict[str, Any]], analysis_rows: list[dict[str, str]],
    full_field_diagnostic_path: Path, formal_tie_break_identity: dict[str, Any],
) -> dict[str, Any]:
    """Use one frozen full-field diagnostic artifact as the sole probability authority.

    Formal V5 is deliberately used only for its already-approved tie-break
    semantics.  Its target-k scope must never decide whether a race has an
    available probability in Comparison A.
    """
    if not full_field_diagnostic_path.is_file():
        raise RoadmapStop("STOP_ROADMAP_V3_FULL_FIELD_DIAGNOSTIC_MISSING")
    diagnostic = json.loads(full_field_diagnostic_path.read_text(encoding="utf-8"))
    if (
        diagnostic.get("schema_version") != "v5_full_field_diagnostic_inference_v1"
        or diagnostic.get("role") != "V5_FULL_FIELD_DIAGNOSTIC_ONLY"
        or diagnostic.get("target_date") != target_date
        or diagnostic.get("result_access_count") != 0
    ):
        raise RoadmapStop("STOP_ROADMAP_V3_FULL_FIELD_DIAGNOSTIC_INTEGRITY")
    records = diagnostic.get("records")
    if not isinstance(records, list):
        raise RoadmapStop("STOP_ROADMAP_V3_FULL_FIELD_DIAGNOSTIC_INTEGRITY")
    probabilities: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = (str(record.get("race_id", "")), str(record.get("horse_number", "")))
        if not all(key) or key in probabilities:
            raise RoadmapStop("STOP_ROADMAP_V3_FULL_FIELD_DIAGNOSTIC_HORSE_IDENTITY")
        probabilities[key] = record
    expected = {(race_id, str(horse.get("horse_number"))) for race_id, payload in current_races.items() for horse in payload["ranked_results"]}
    if set(probabilities) != expected:
        raise RoadmapStop("STOP_ROADMAP_V3_FULL_FIELD_DIAGNOSTIC_RACE_OR_HORSE_SET_MISMATCH")
    model_identity = diagnostic.get("records", [{}])[0].get("model_identity") if records else None
    runtime_identity = (model_identity or {}).get("python_executable") or (model_identity or {}).get("environment_identifier")
    if not isinstance(model_identity, dict) or not model_identity.get("model_sha256") or not runtime_identity:
        raise RoadmapStop("STOP_ROADMAP_V3_V5_RUNTIME_IDENTITY_UNPROVEN")
    if model_identity["model_sha256"] != formal_tie_break_identity.get("model_sha256"):
        raise RoadmapStop("STOP_ROADMAP_V3_V5_MODEL_SHA_MISMATCH")
    if any(
        not isinstance(record.get("model_identity"), dict)
        or record["model_identity"].get("model_sha256") != model_identity["model_sha256"]
        for record in records
    ):
        raise RoadmapStop("STOP_ROADMAP_V3_V5_MODEL_SHA_MISMATCH")
    translated: list[dict[str, str]] = []
    for row in analysis_rows:
        key = (str(row["race_id"]), str(row["horse_number"]))
        source = probabilities[key]
        copied = dict(row)
        # The source is exclusive: no Formal-V5 probability can enter this row.
        copied["formal_v5_probability"] = str(source["p_top3"]) if source.get("diagnostic_status") == "AVAILABLE" else ""
        translated.append(copied)
    comparison = comparison_a_records(
        target_date=target_date, current_races=current_races, rows=translated,
        formal_identity={"model_sha256": model_identity["model_sha256"], "runtime_identity": runtime_identity},
    )
    comparison["probability_authority"] = "FROZEN_NEXT_PRE_DIAGNOSTIC_FULL_FIELD_V5_P_TOP3"
    comparison["probability_source_artifact_sha256"] = sha256(full_field_diagnostic_path)
    comparison["tie_break_authority"] = {
        "source": "FORMAL_V5_DETERMINISTIC_ORDERING_ONLY",
        "model_sha256": formal_tie_break_identity.get("model_sha256"),
        "rules": list(TIE_BREAK),
    }
    return comparison


def rank1_diagnostics(comparison_a: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    by_race = {record["race_id"]: record for record in comparison_a["race_records"]}
    current_buy_races = {str(row["race_id"]) for row in rows if _truth(row.get("current_buy"))}
    r1, r2, r3 = [], [], []
    for race_id, record in by_race.items():
        if record["race_status"] != "AVAILABLE":
            continue
        ordered = sorted(record["horses"], key=lambda item: item["deterministic_rank"])
        item = {"race_id": race_id, "current_rank1": [row["horse_number"] for row in ordered if row["shadow_ai_rank"] == 1], "v5_rank1": ordered[0]["horse_number"]}
        r3.append(item)
        (r1 if race_id in current_buy_races else r2).append(item)
    if {row["race_id"] for row in r1} | {row["race_id"] for row in r2} != {row["race_id"] for row in r3}:
        raise RoadmapStop("STOP_ROADMAP_V3_RANK1_PARTITION")
    return {"role": "DIAGNOSTIC_ONLY", "result_access_count": 0, "R1": r1, "R2": r2, "R3": r3, "partition_pass": True}


def meeting_block(target_date: str) -> str:
    day = datetime.strptime(target_date, "%Y%m%d").date()
    saturday = day - timedelta(days=(day.weekday() - 5) % 7)
    return saturday.strftime("%Y%m%d")


def meeting_summary(target_dates: Iterable[str], independent_race_count: int) -> dict[str, Any]:
    dates = sorted(set(target_dates))
    blocks = sorted({meeting_block(value) for value in dates})
    return {"defined_meeting_count": len(blocks), "target_date_count": len(dates), "defined_meeting_blocks": blocks, "independent_race_count": independent_race_count}


def validate_rolling_origin(folds: list[dict[str, Any]]) -> dict[str, Any]:
    for fold in folds:
        prediction_month = str(fold.get("prediction_month", ""))
        training = [str(value) for value in fold.get("training_months", [])]
        if not prediction_month or not training or any(value >= prediction_month for value in training):
            raise RoadmapStop("STOP_WS2_ROLLING_ORIGIN_ORDER")
    return {"status": "PASS", "cross_fit": "ROLLING_ORIGIN_MONTHLY_CROSS_FIT", "fold_count": len(folds)}


def ws2_preflight(manifest: dict[str, Any]) -> dict[str, Any]:
    required_true = ("v5_top5_only_confirmed", "historical_full_field_rows_available", "current_scores_point_in_time_safe", "learning_db_clean", "pre_time_features_only", "track_condition_semantics_known", "model_identity_proven", "runtime_available")
    result_columns = {str(value).lower() for value in manifest.get("feature_columns", [])}
    forbidden = {"actual_top3", "finish", "actual_finish", "result", "de_col29", "de_col30", "de_col31"}
    if any(not manifest.get(key) for key in required_true) or result_columns & forbidden:
        raise RoadmapStop("STOP_WS2_DATA_INTEGRITY")
    return {"status": "PASS", "training_started": False, "model_change": False, "checks": list(required_true), "result_columns_detected": sorted(result_columns & forbidden)}


def holdout_inventory(consumed_periods: list[dict[str, Any]]) -> dict[str, Any]:
    dates = sorted({str(item["period"]) for item in consumed_periods if item.get("period")})
    return {"status": "INVENTORIED_NOT_ALLOCATED", "consumed_periods": dates, "untouched_holdout_declared": False, "if_none": "NO_UNTOUCHED_HISTORICAL_HOLDOUT_AVAILABLE"}


def market_inventory(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("feature_table_path") or source.get("model_input_path"):
        raise RoadmapStop("STOP_ROADMAP_V3_MARKET_ISOLATION")
    return {"status": "INVENTORY_ONLY", "market_as_ai_input": "PROHIBITED", "source_availability": source.get("source_availability", "NOT_COLLECTED"), "storage_isolation": "REQUIRED"}


def freeze_comparison_a(
    *, target_date: str, current_pre_root: Path, analysis_horse_csv: Path, formal_identity_path: Path,
    full_field_diagnostic_path: Path, verification_manifest_path: Path, output_root: Path,
    execution_date: str | None = None, repository_root: Path = ROOT,
) -> Path:
    if output_root.exists():
        raise RoadmapStop("STOP_ROADMAP_V3_OUTPUT_EXISTS")
    timing = validate_pre_timing(target_date=target_date, execution_date=execution_date, repository_root=repository_root)
    execution_spec = ROOT / "docs" / "KeibaAI_Performance_Roadmap_v3_Execution_Spec_v1.md"
    amendment = ROOT / "docs" / "KeibaAI_Performance_Roadmap_v3_Execution_Amendment_1.md"
    contract = ROOT / "docs" / "roadmap_v3_pre_infrastructure_contract_v2.json"
    implementation = Path(__file__).resolve()
    test_file = ROOT / "tests" / "test_roadmap_v3_pre_infrastructure_v1.py"
    verification, verification_sha = validate_verification_manifest(verification_manifest_path, {
        "execution_spec_sha": sha256(execution_spec), "amendment_sha": sha256(amendment),
        "active_contract_sha": sha256(contract), "implementation_file_sha": sha256(implementation),
        "relevant_test_file_sha": sha256(test_file),
    })
    race_ids, current_races, current_source_hashes = _current_authority(current_pre_root, target_date)
    rows = _load_csv_rows(analysis_horse_csv)
    formal_identity = _formal_identity(formal_identity_path)
    comparison = comparison_a_from_full_field_diagnostic(
        target_date=target_date, current_races=current_races, analysis_rows=rows,
        full_field_diagnostic_path=full_field_diagnostic_path, formal_tie_break_identity=formal_identity,
    )
    rank1 = rank1_diagnostics(comparison, rows)
    comp_b = comparison_b_pre(rows)
    document = {
        "comparison_a": comparison, "comparison_b_pre": comp_b, "rank1_diagnostics": rank1,
        "source_artifacts": {**current_source_hashes, "six_lane_analysis_sha256": sha256(analysis_horse_csv), "formal_identity_sha256": sha256(formal_identity_path), "probability_source_artifact_sha256": sha256(full_field_diagnostic_path)},
        "infrastructure_provenance": {
            "execution_spec_sha": sha256(execution_spec), "amendment_sha": sha256(amendment),
            "contract_sha": sha256(contract), "implementation_sha": sha256(implementation),
            "verification_manifest_sha": verification_sha, "verification_record_sha": verification["verification_record_sha"],
            "v5_model_sha": comparison["model_identity"]["model_sha256"],
        },
        "forward_timing_guard": timing,
        "race_population_count": len(race_ids), "generated_at_jst": datetime.now(timezone(timedelta(hours=9))).replace(microsecond=0).isoformat(),
        "result_access_count": 0, "roadmap_v3_forward_evidence_started": False,
    }
    output_root.mkdir(parents=True)
    target = output_root / "roadmap_v3_pre_freeze.json"
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n")
    with (output_root / "artifact_hashes.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump({"roadmap_v3_pre_freeze.json": sha256(target)}, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n")
    return output_root
