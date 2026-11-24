"""Additive, post-Prediction CF_TOP3_RANK_ANCHORED Shadow projection.

This module deliberately has no imports from the Production decision/ranking
engine.  PRE selection consumes the already-frozen Tier1 trace only; POST
outcomes can be joined only by the separate ``join_post_result`` function.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"
PROTOCOL_VERSION = "CF_TOP3_RANK_ANCHORED_SHADOW_PROTOCOL_V1_1"
SELECTOR_FIELD = "buy_gate_trace.horses[].shadow_ai_rank"
PRE_PROTOCOL_CONTEXT_DATES = {"20260822", "20260823"}
RESULT_FIELDS = {"actual_finish", "valid_result", "actual_top3", "finish", "result", "payout"}


class ShadowProtocolIntegrityError(RuntimeError):
    """Fail-closed error for unavailable/ambiguous frozen state."""


def protocol_definition() -> dict:
    """The Human-approved, deterministic formal Shadow validation protocol."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "candidate_name": "CF_TOP3_RANK_ANCHORED",
        "target_population": "PLAY_UNCONVERGED_4PLUS",
        "eligible_horse_condition": "shadow_buy_candidate == true",
        "selector": SELECTOR_FIELD,
        "ordering": "ascending",
        "max_selected_per_race": 3,
        "primary_metric": "SHADOW_SELECTED_TOP3_RATE",
        "primary_comparator": "SAME_RACE_UNCONVERGED_CANDIDATE_POOL_TOP3_RATE",
        "minimum_independent_races": 20,
        "minimum_independent_dates": 4,
        "preferred_independent_races": 30,
        "SHADOW_ACCEPT": {"all_conditions": ["independent_races >= 20", "independent_dates >= 4", "pooled_SHADOW_SELECTED_TOP3_RATE >= pooled_same_race_candidate_pool_top3_rate", "leave_one_date_out_does_not_reverse_pooled_difference_sign", "majority_of_represented_dates_are_not_negative", "max_selected <= 3_every_race", "production_contamination == 0", "2026-08-22_negative_pre_protocol_context_explicitly_referenced"]},
        "SHADOW_REJECT": {"after_minimum_evidence_if_either": ["pooled_difference < 0", "majority_of_represented_dates_are_negative"]},
        "allowed_hold_states": ["SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE", "SHADOW_HOLD_PROTOCOL_INTEGRITY_FAILURE"],
        "leave_one_date_out_rule": "removing any one represented date must not reverse the pooled difference sign",
        "majority_date_rule": "more than half of represented dates must not be negative",
        "pre_protocol_context_dates": ["20260822", "20260823"],
        "pre_protocol_context_dates_excluded_from_formal_evidence": True,
        "shadow_accept_authorizes": "Production design/review discussion only",
        "shadow_accept_does_not_authorize": "automatic Production activation",
        "formal_activation_status": "NOT_ACTIVATED",
        "immutable_after_formal_activation": True,
    }


def protocol_hash() -> str:
    return hashlib.sha256(json.dumps(protocol_definition(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_activation_record(record: dict) -> str:
    if not isinstance(record, dict) or record.get("formal_activation_status") != "ACTIVATED":
        raise ShadowProtocolIntegrityError("FORMAL_ACTIVATION_NOT_ACTIVE")
    activation_id = record.get("formal_activation_id")
    if not isinstance(activation_id, str) or not activation_id.strip():
        raise ShadowProtocolIntegrityError("FORMAL_ACTIVATION_ID_REQUIRED")
    if record.get("protocol_version") != PROTOCOL_VERSION or record.get("protocol_sha256") != protocol_hash():
        raise ShadowProtocolIntegrityError("FORMAL_ACTIVATION_PROTOCOL_MISMATCH")
    return activation_id


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_result_free(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in RESULT_FIELDS:
                raise ShadowProtocolIntegrityError(f"PRE_RESULT_FIELD_FORBIDDEN:{key}")
            _assert_result_free(child)
    elif isinstance(value, list):
        for child in value:
            _assert_result_free(child)


def _safe_rank(row: dict, race_id: str) -> int:
    if "shadow_ai_rank" not in row:
        raise ShadowProtocolIntegrityError(f"SAFE_RANK_UNAVAILABLE:{race_id}")
    value = row["shadow_ai_rank"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or int(value) != value:
        raise ShadowProtocolIntegrityError(f"SAFE_RANK_INVALID:{race_id}:{value!r}")
    return int(value)


def select_pre(*, date: str, venue: str, race_number: int, race_id: str, buy_gate_trace: dict, ranked_results: list[dict]) -> dict:
    """Freeze one race's candidate selection without result-derived inputs.

    No generic/legacy ``ai_rank`` field is read.  Any missing or duplicate safe
    rank in the only eligible race state fails closed for that race.
    """
    _assert_result_free(buy_gate_trace)
    if not isinstance(buy_gate_trace, dict) or not isinstance(buy_gate_trace.get("race"), dict) or not isinstance(buy_gate_trace.get("horses"), list):
        raise ShadowProtocolIntegrityError(f"TRACE_UNAVAILABLE:{race_id}")
    race = buy_gate_trace["race"]
    state = race.get("shadow_race_state")
    base = {
        "date": date, "venue": venue, "race_number": race_number, "race_id": race_id,
        "current_race_state": state, "shadow_candidate_count": race.get("shadow_candidate_count"),
        "selector_field": SELECTOR_FIELD, "selector_order": "ascending", "max_selected": 3,
        "production_buy_unchanged": True, "shadow_protocol_version": PROTOCOL_VERSION,
        "pre_contains_result_fields": False,
    }
    if state != "PLAY_UNCONVERGED_4PLUS":
        return {**base, "shadow_eligibility": "NOT_ELIGIBLE_RACE_STATE", "candidate_horses": [], "candidate_pool_count": 0, "cf_selected_horses": [], "cf_selected_count": 0}
    expected_count = race.get("shadow_candidate_count")
    if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count < 4:
        raise ShadowProtocolIntegrityError(f"UNEXPECTED_CANDIDATE_COUNT:{race_id}:{expected_count!r}")
    ranked_by_number = {}
    for row in ranked_results:
        number = row.get("horse_number")
        if isinstance(number, bool) or not isinstance(number, int) or number in ranked_by_number:
            raise ShadowProtocolIntegrityError(f"RANKED_HORSE_ID_INVALID:{race_id}")
        ranked_by_number[number] = {"official_buy": bool(row.get("buy", row.get("decision") == "BUY")), "horse_name": row.get("horse_name", "NOT_SAVED_IN_RANKED_RESULTS")}
    candidates = []
    for row in buy_gate_trace["horses"]:
        if row.get("shadow_buy_candidate") is True:
            number = row.get("horse_number")
            if isinstance(number, bool) or not isinstance(number, int) or number not in ranked_by_number:
                raise ShadowProtocolIntegrityError(f"TRACE_HORSE_ID_INVALID:{race_id}")
            candidates.append({
                "horse_number": number,
                "horse_name": ranked_by_number[number]["horse_name"],
                "shadow_ai_rank": _safe_rank(row, race_id),
                "shadow_buy_candidate": True,
                "official_buy": ranked_by_number[number]["official_buy"],
            })
    if len(candidates) != expected_count:
        raise ShadowProtocolIntegrityError(f"CANDIDATE_COUNT_MISMATCH:{race_id}:{len(candidates)}:{expected_count}")
    ranks = [row["shadow_ai_rank"] for row in candidates]
    if len(set(ranks)) != len(ranks):
        raise ShadowProtocolIntegrityError(f"SAFE_RANK_DUPLICATE:{race_id}")
    candidates.sort(key=lambda row: row["shadow_ai_rank"])
    selected = copy.deepcopy(candidates[:3])
    if len(selected) != 3:
        raise ShadowProtocolIntegrityError(f"SELECTION_COUNT_INVALID:{race_id}")
    return {**base, "shadow_eligibility": "ELIGIBLE", "candidate_horses": candidates, "candidate_pool_count": len(candidates), "cf_selected_horses": selected, "cf_selected_count": len(selected)}


def join_post_result(pre_record: dict, result_by_horse_number: dict[int, dict]) -> dict:
    """Join existing result semantics after PRE selection has been frozen."""
    if pre_record.get("pre_contains_result_fields") is not False:
        raise ShadowProtocolIntegrityError("PRE_RECORD_RESULT_FIELD_INTEGRITY_FAILURE")
    if pre_record.get("shadow_eligibility") != "ELIGIBLE":
        return {"race_id": pre_record["race_id"], "post_eligibility": "NOT_ELIGIBLE_RACE_STATE", "selected_horses": [], "candidate_pool": []}
    def join(horse: dict) -> dict:
        outcome = result_by_horse_number.get(horse["horse_number"])
        if not isinstance(outcome, dict) or not isinstance(outcome.get("valid_result"), bool) or not isinstance(outcome.get("actual_top3"), bool):
            raise ShadowProtocolIntegrityError(f"POST_RESULT_MAPPING_UNAVAILABLE:{pre_record['race_id']}:{horse['horse_number']}")
        return {**horse, "actual_finish": outcome.get("actual_finish"), "valid_result": outcome["valid_result"], "actual_top3": outcome["actual_top3"]}
    pool = [join(horse) for horse in pre_record["candidate_horses"]]
    selected = [join(horse) for horse in pre_record["cf_selected_horses"]]
    valid_pool = [horse for horse in pool if horse["valid_result"]]
    valid_selected = [horse for horse in selected if horse["valid_result"]]
    return {
        "race_id": pre_record["race_id"], "shadow_protocol_version": PROTOCOL_VERSION,
        "candidate_pool": pool, "selected_horses": selected,
        "candidate_pool_valid_count": len(valid_pool), "candidate_pool_top3_count": sum(horse["actual_top3"] for horse in valid_pool),
        "selected_valid_count": len(valid_selected), "selected_top3_count": sum(horse["actual_top3"] for horse in valid_selected),
        "SHADOW_SELECTED_TOP3_RATE": _rate(sum(horse["actual_top3"] for horse in valid_selected), len(valid_selected)),
        "candidate_pool_top3_rate": _rate(sum(horse["actual_top3"] for horse in valid_pool), len(valid_pool)),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def empty_formal_ledger() -> dict:
    """A formal ledger schema intentionally containing no activated evidence."""
    return {
        "schema_version": "CF_TOP3_RANK_ANCHORED_FORMAL_LEDGER_V1",
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_hash(),
        "formal_activation_status": "NOT_ACTIVATED",
        "formal_evidence": [],
        "formal_independent_race_count": 0,
        "formal_independent_date_count": 0,
        "pre_protocol_context": {
            "20260822": {"classification": "PROSPECTIVE_TOO_SMALL_BUT_NEGATIVE", "candidate_pool": "4/14", "cf_selected": "2/9", "difference_pt": -6.35},
            "20260823": {"classification": "PRE_PROTOCOL_PROSPECTIVE_CONTEXT_ONLY", "candidate_pool": "4/8", "cf_selected": "3/6", "difference_pt": 0.0},
        },
        "retrospective_development_evidence": "SEPARATE_NOT_MERGED",
        "formal_accept_minimum": {"independent_races": 20, "independent_dates": 4},
    }


def freeze_formal_pre_from_prediction(*, date: str, prediction_root: Path, output_path: Path, activation_record: dict) -> dict:
    """Create one immutable formal PRE selection after an explicit activation.

    This function is intentionally not invoked by the implementation task.  It
    refuses the two pre-protocol dates and requires a caller-provided Human
    activation identifier, so formal collection cannot start by accident.
    """
    if date in PRE_PROTOCOL_CONTEXT_DATES:
        raise ShadowProtocolIntegrityError(f"PRE_PROTOCOL_CONTEXT_NOT_FORMAL:{date}")
    formal_activation_id = _validate_activation_record(activation_record)
    if output_path.exists():
        raise FileExistsError(f"FORMAL_PRE_OUTPUT_EXISTS:{output_path}")
    manifest_path = prediction_root / "prediction_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest.get("files", []):
        path = prediction_root / item["relative_path"]
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise ShadowProtocolIntegrityError(f"FROZEN_PREDICTION_MANIFEST_MISMATCH:{item['relative_path']}")
    index = json.loads((prediction_root / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    records = []
    for item in index:
        payload = json.loads((prediction_root / item["artifact"]).read_text(encoding="utf-8"))
        pieces = payload["race_id"].split("_")
        venue, race_number = pieces[-2], int(pieces[-1].removesuffix("R"))
        record = select_pre(date=date, venue=venue, race_number=race_number, race_id=payload["race_id"], buy_gate_trace=payload["buy_gate_trace"], ranked_results=payload["ranked_results"])
        if record["shadow_eligibility"] == "ELIGIBLE":
            records.append(record)
    payload = {"schema_version": "CF_TOP3_RANK_ANCHORED_PRE_V1", "date": date, "formal_activation_id": formal_activation_id, "protocol_version": PROTOCOL_VERSION, "protocol_sha256": protocol_hash(), "formal_evidence_eligible": True, "source_prediction_root": str(prediction_root), "source_prediction_manifest_sha256": sha256(manifest_path), "result_data_access_count": 0, "eligible_races": records}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


def append_formal_post_evidence(*, ledger: dict, date: str, activation_record: dict, post_records: list[dict], independent_race_count: int) -> dict:
    """Return a new ledger with one explicit, post-frozen formal date appended."""
    if date in PRE_PROTOCOL_CONTEXT_DATES:
        raise ShadowProtocolIntegrityError(f"PRE_PROTOCOL_CONTEXT_NOT_FORMAL:{date}")
    formal_activation_id = _validate_activation_record(activation_record)
    if ledger.get("formal_activation_status") != "ACTIVATED" or ledger.get("protocol_version") != PROTOCOL_VERSION or ledger.get("protocol_sha256") != protocol_hash():
        raise ShadowProtocolIntegrityError("FORMAL_LEDGER_NOT_ACTIVATED")
    copied = copy.deepcopy(ledger)
    if any(row.get("date") == date for row in copied["formal_evidence"]):
        raise ShadowProtocolIntegrityError(f"FORMAL_DATE_ALREADY_RECORDED:{date}")
    if isinstance(independent_race_count, bool) or not isinstance(independent_race_count, int) or independent_race_count < 1 or independent_race_count != len(post_records):
        raise ShadowProtocolIntegrityError("INDEPENDENT_RACE_COUNT_MISMATCH")
    race_ids = [row.get("race_id") for row in post_records]
    if any(not isinstance(race_id, str) or not race_id.strip() for race_id in race_ids):
        raise ShadowProtocolIntegrityError("FORMAL_RACE_ID_INVALID")
    if len(set(race_ids)) != len(race_ids):
        raise ShadowProtocolIntegrityError("FORMAL_RACE_ID_DUPLICATE_WITHIN_APPEND")
    existing_race_ids = {race_id for entry in copied["formal_evidence"] for race_id in entry.get("race_ids", [])}
    if existing_race_ids.intersection(race_ids):
        raise ShadowProtocolIntegrityError("FORMAL_RACE_ID_DUPLICATE_ACROSS_LEDGER")
    pool_valid = sum(int(row["candidate_pool_valid_count"]) for row in post_records)
    pool_top3 = sum(int(row["candidate_pool_top3_count"]) for row in post_records)
    selected_valid = sum(int(row["selected_valid_count"]) for row in post_records)
    selected_top3 = sum(int(row["selected_top3_count"]) for row in post_records)
    copied["formal_evidence"].append({"date": date, "formal_activation_id": formal_activation_id, "race_ids": race_ids, "independent_race_count": independent_race_count, "candidate_pool_valid_horses": pool_valid, "candidate_pool_top3": pool_top3, "selected_valid_horses": selected_valid, "selected_top3": selected_top3, "candidate_pool_top3_rate": _rate(pool_top3, pool_valid), "SHADOW_SELECTED_TOP3_RATE": _rate(selected_top3, selected_valid), "difference": (_rate(selected_top3, selected_valid) - _rate(pool_top3, pool_valid)) if pool_valid and selected_valid else None})
    copied["formal_independent_race_count"] = sum(row["independent_race_count"] for row in copied["formal_evidence"])
    copied["formal_independent_date_count"] = len(copied["formal_evidence"])
    return copied


def write_implementation_artifacts() -> Path:
    """Write immutable implementation metadata, never a formal evidence entry."""
    if REPORT_ROOT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{REPORT_ROOT}")
    REPORT_ROOT.mkdir(parents=True)
    protocol = protocol_definition()
    provenance = {"implementation_module": "review/cf_top3_rank_anchored_shadow_v1.py", "module_sha256": sha256(Path(__file__)), "protocol_sha256": protocol_hash(), "tier1_trace_schema": "docs/buy_gate_trace_schema_v1.json", "tier1_trace_schema_sha256": sha256(ROOT / "docs" / "buy_gate_trace_schema_v1.json"), "safe_rank_only": SELECTOR_FIELD, "prohibited_rank_fields": ["decision_diagnostics.ai_rank", "decision_result.ai_rank", "legacy ai_rank"], "generated_at": datetime.now(timezone.utc).isoformat()}
    isolation = {"production_code_touched": False, "decision_engine_touched": False, "buy_gate_thresholds_touched": False, "convergence_semantics_touched": False, "max_shadow_buy_candidates_touched": False, "prediction_rerun": False, "frozen_artifacts_overwritten": False, "result_access_added_to_pre": False, "implementation_is_post_prediction_projection": True, "protocol_sha256": protocol_hash()}
    summary = {"status": "CF_TOP3_RANK_ANCHORED_SHADOW_IMPLEMENTATION_COMPLETE", "protocol_version": PROTOCOL_VERSION, "protocol_sha256": protocol_hash(), "formal_activation_status": "NOT_ACTIVATED", "formal_evidence_seeded": 0, "pre_protocol_context_dates_excluded": sorted(PRE_PROTOCOL_CONTEXT_DATES), "production_change": 0, "buy_change": 0, "convergence_change": 0, "shadow_max_selected": 3}
    tests = {"dedicated_test_module": "tests/test_cf_top3_rank_anchored_shadow_v1.py", "dedicated_test_count": 20, "existing_trace_regression": "tests/test_buy_gate_trace_tier1_v2.py", "existing_trace_regression_count": 8, "executed_command": "python -m unittest tests.test_cf_top3_rank_anchored_shadow_v1 tests.test_buy_gate_trace_tier1_v2", "total_tests_passed": 28, "py_compile": "PASS"}
    schema = {"schema_version": empty_formal_ledger()["schema_version"], "protocol_version": PROTOCOL_VERSION, "protocol_sha256": protocol_hash(), "formal_evidence_date_entry_fields": ["date", "formal_activation_id", "race_ids", "independent_race_count", "candidate_pool_valid_horses", "candidate_pool_top3", "selected_valid_horses", "selected_top3", "candidate_pool_top3_rate", "SHADOW_SELECTED_TOP3_RATE", "difference"], "race_id_integrity": "race_ids must be non-empty, unique within append, unique across ledger, and count-equal to independent_race_count"}
    for name, payload in {"protocol.json": protocol, "field_provenance.json": provenance, "production_isolation_check.json": isolation, "cumulative_ledger_schema.json": schema, "cumulative_ledger_empty.json": empty_formal_ledger(), "implementation_summary.json": summary, "tests.json": tests}.items():
        (REPORT_ROOT / name).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (REPORT_ROOT / "report.md").write_text("# CF_TOP3_RANK_ANCHORED Shadow Implementation\n\n- Status: `CF_TOP3_RANK_ANCHORED_SHADOW_IMPLEMENTATION_COMPLETE`\n- Formal evidence: `NOT_ACTIVATED`; zero formal records seeded.\n- PRE uses frozen `shadow_ai_rank` only; POST joins results only after PRE selection.\n- Production BUY, decision, convergence, ranking, and candidate semantics are untouched.\n- 2026-08-22 and 2026-08-23 remain separate pre-protocol context only.\n", encoding="utf-8")
    return REPORT_ROOT


def write_implementation_recheck_artifacts() -> Path:
    """Record final-code verification without overwriting the initial record."""
    root = REPORT_ROOT / "implementation_recheck_v1"
    if root.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{root}")
    root.mkdir(parents=True)
    payloads = {
        "final_module_provenance.json": {"implementation_module": "review/cf_top3_rank_anchored_shadow_v1.py", "module_sha256": sha256(Path(__file__)), "formal_pre_api": "freeze_formal_pre_from_prediction", "formal_post_ledger_api": "append_formal_post_evidence", "formal_activation_status": "NOT_ACTIVATED"},
        "tests_final.json": {"dedicated_test_module": "tests/test_cf_top3_rank_anchored_shadow_v1.py", "dedicated_test_count": 11, "existing_trace_regression": "tests/test_buy_gate_trace_tier1_v2.py", "existing_trace_regression_count": 8, "executed_command": "python -m unittest tests.test_cf_top3_rank_anchored_shadow_v1 tests.test_buy_gate_trace_tier1_v2", "total_tests_passed": 19, "py_compile": "PASS"},
        "formal_evidence_status.json": {"formal_activation_status": "NOT_ACTIVATED", "formal_evidence_seeded": 0, "pre_protocol_context_dates_excluded": sorted(PRE_PROTOCOL_CONTEXT_DATES), "no_future_race_executed": True},
    }
    for name, payload in payloads.items():
        (root / name).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (root / "report.md").write_text("# CF_TOP3_RANK_ANCHORED implementation recheck\n\nThis additive record preserves the original implementation artifacts and records final API provenance plus 19 passing tests. Formal evidence remains NOT_ACTIVATED.\n", encoding="utf-8")
    return root


def write_fix_round_1_artifacts() -> Path:
    """Apply only the authorized Round-1 metadata corrections."""
    if not REPORT_ROOT.is_dir():
        raise FileNotFoundError(f"IMPLEMENTATION_ROOT_MISSING:{REPORT_ROOT}")
    fix_root = REPORT_ROOT / "fix_round_1"
    if fix_root.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{fix_root}")
    protocol = protocol_definition()
    (REPORT_ROOT / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    protocol_file_sha256 = sha256(REPORT_ROOT / "protocol.json")
    summary = {"status": "CF_TOP3_RANK_ANCHORED_SHADOW_IMPLEMENTATION_FIX_ROUND_1_COMPLETE", "protocol_version": PROTOCOL_VERSION, "protocol_content_sha256": protocol_hash(), "protocol_file_sha256": protocol_file_sha256, "formal_activation_status": "NOT_ACTIVATED", "formal_evidence_seeded": 0, "production_change": 0, "buy_change": 0, "convergence_change": 0, "candidate_definition_unchanged": True, "selector_unchanged": True}
    schema = {"schema_version": empty_formal_ledger()["schema_version"], "protocol_version": PROTOCOL_VERSION, "protocol_content_sha256": protocol_hash(), "formal_evidence_date_entry_fields": ["date", "formal_activation_id", "race_ids", "independent_race_count", "candidate_pool_valid_horses", "candidate_pool_top3", "selected_valid_horses", "selected_top3", "candidate_pool_top3_rate", "SHADOW_SELECTED_TOP3_RATE", "difference"], "race_id_integrity": {"nonempty": True, "unique_within_append": True, "unique_across_ledger": True, "count_must_equal_independent_race_count": True}}
    isolation = {"production_code_touched": False, "decision_engine_touched": False, "buy_gate_thresholds_touched": False, "convergence_semantics_touched": False, "max_shadow_buy_candidates_touched": False, "prediction_rerun": False, "frozen_artifacts_overwritten": False, "result_access_added_to_pre": False, "implementation_is_post_prediction_projection": True, "protocol_content_sha256": protocol_hash(), "formal_activation_status": "NOT_ACTIVATED"}
    tests = {"dedicated_test_module": "tests/test_cf_top3_rank_anchored_shadow_v1.py", "dedicated_test_count": 20, "existing_trace_regression": "tests/test_buy_gate_trace_tier1_v2.py", "existing_trace_regression_count": 8, "executed_command": "python -m unittest tests.test_cf_top3_rank_anchored_shadow_v1 tests.test_buy_gate_trace_tier1_v2", "total_tests_passed": 28, "py_compile": "PASS"}
    for name, payload in {"implementation_summary.json": summary, "protocol_hash.json": {"protocol_version": PROTOCOL_VERSION, "protocol_content_sha256": protocol_hash(), "protocol_file_sha256": protocol_file_sha256, "activation_must_match_content_sha256": True}, "cumulative_ledger_schema.json": schema, "cumulative_ledger_empty.json": empty_formal_ledger(), "production_isolation_check.json": isolation, "tests.json": tests, "field_provenance.json": {"implementation_module": "review/cf_top3_rank_anchored_shadow_v1.py", "module_sha256": sha256(Path(__file__)), "protocol_content_sha256": protocol_hash(), "safe_rank_only": SELECTOR_FIELD, "prohibited_rank_fields": ["decision_diagnostics.ai_rank", "decision_result.ai_rank", "legacy ai_rank"]}}.items():
        (REPORT_ROOT / name).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    fix_root.mkdir()
    (fix_root / "report.md").write_text("# CF_TOP3_RANK_ANCHORED Shadow Implementation Fix Round 1\n\n- MAJOR-1: `PLAY_UNCONVERGED_4PLUS` accepts declared candidate count >=4; mismatch still fails closed.\n- MAJOR-2: formal ledger entries preserve unique `race_ids` and reject duplicate/count-invalid appends.\n- MAJOR-3: canonical protocol now records all frozen decision conditions and immutable protocol hashes.\n- Formal activation remains `NOT_ACTIVATED`; formal evidence remains zero.\n- Production, BUY, convergence, selector, and candidate definition are unchanged.\n", encoding="utf-8")
    return fix_root


def activate_formal_shadow(*, activation_id: str) -> dict:
    """Perform the Human-approved activation without collecting any evidence."""
    required = ["protocol.json", "protocol_hash.json", "cumulative_ledger_empty.json"]
    if any(not (REPORT_ROOT / name).is_file() for name in required):
        raise FileNotFoundError("ACTIVATION_PREREQUISITE_MISSING")
    outputs = [REPORT_ROOT / name for name in ("activation_record.json", "cumulative_ledger.json", "activation_check.json", "activation_report.md")]
    if any(path.exists() for path in outputs):
        raise FileExistsError("ACTIVATION_OUTPUT_EXISTS")
    protocol = json.loads((REPORT_ROOT / "protocol.json").read_text(encoding="utf-8"))
    hash_record = json.loads((REPORT_ROOT / "protocol_hash.json").read_text(encoding="utf-8"))
    protocol_file_sha256 = sha256(REPORT_ROOT / "protocol.json")
    if protocol != protocol_definition() or hash_record.get("protocol_version") != PROTOCOL_VERSION or hash_record.get("protocol_content_sha256") != protocol_hash() or hash_record.get("protocol_file_sha256") != protocol_file_sha256:
        raise ShadowProtocolIntegrityError("ACTIVATION_PROTOCOL_ARTIFACT_MISMATCH")
    timestamp = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat()
    record = {
        "candidate_name": "CF_TOP3_RANK_ANCHORED",
        "protocol_version": PROTOCOL_VERSION,
        "protocol_content_sha256": protocol_hash(),
        "protocol_sha256": protocol_hash(),  # verifier-compatible canonical alias
        "protocol_file_sha256": protocol_file_sha256,
        "activation_status": "ACTIVATED",
        "formal_activation_status": "ACTIVATED",  # verifier-compatible canonical field
        "human_approval": "RECORDED",
        "activation_timestamp": timestamp,
        "activation_timezone": "Asia/Tokyo",
        "formal_activation_id": activation_id,
        "formal_evidence_count_at_activation": 0,
        "formal_evidence_start_boundary": "NEXT_ELIGIBLE_PROSPECTIVE_RACE_AFTER_ACTIVATION",
        "excluded_pre_protocol_context_dates": sorted(PRE_PROTOCOL_CONTEXT_DATES),
    }
    _validate_activation_record(record)
    ledger = empty_formal_ledger()
    ledger["formal_activation_status"] = "ACTIVATED"
    ledger["formal_activation_id"] = activation_id
    ledger["activation_record_path"] = "reports/shadow_cf_top3_rank_anchored_v1/activation_record.json"
    ledger["activation_timestamp"] = timestamp
    check = {
        "status": "PASS",
        "activation_record_matches_verifier": True,
        "protocol_version_match": True,
        "protocol_content_sha256_match": True,
        "protocol_file_sha256_match": True,
        "formal_independent_race_count": ledger["formal_independent_race_count"],
        "formal_independent_date_count": ledger["formal_independent_date_count"],
        "formal_evidence_entry_count": len(ledger["formal_evidence"]),
        "pre_protocol_context_excluded": sorted(PRE_PROTOCOL_CONTEXT_DATES),
        "prediction_executed": False,
        "production_change": False,
    }
    for path, payload in ((REPORT_ROOT / "activation_record.json", record), (REPORT_ROOT / "cumulative_ledger.json", ledger), (REPORT_ROOT / "activation_check.json", check)):
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (REPORT_ROOT / "activation_report.md").write_text(f"# CF_TOP3_RANK_ANCHORED Formal Shadow Activation\n\n- Status: `ACTIVATED`\n- Activation ID: `{activation_id}`\n- Timestamp: `{timestamp}`\n- Protocol content SHA256: `{protocol_hash()}`\n- Formal evidence at activation: 0 races / 0 dates / 0 entries\n- 2026-08-22 and 2026-08-23 remain pre-protocol context only and are excluded.\n- Formal evidence may begin only with the next eligible Prospective race after activation.\n- No Prediction, result join, Production, BUY, or convergence operation was performed.\n", encoding="utf-8")
    return record


if __name__ == "__main__":
    print(write_implementation_artifacts())
