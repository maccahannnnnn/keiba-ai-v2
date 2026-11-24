"""Fail-closed validators for the V2 prospective protocol."""
from __future__ import annotations

from typing import Any

from review.current_corrected_shadow_v2_prospective_protocol_v1 import Stop, validate_cumulative, validate_pre_rows, validate_protocol, verify_freeze_pins

def validate_pre_start(protocol: dict[str, Any]) -> dict[str, str]:
    validate_protocol(protocol); verify_freeze_pins(protocol)
    return {"protocol": "PASS", "freeze_pins": "PASS", "formal_execution_authorized": "FALSE_RECORDED"}

def validate_pre(current_rows: list[dict[str, Any]], corrected_rows: list[dict[str, Any]], target_k: int, gates: dict[str, str], result_access_count: int) -> None:
    if result_access_count != 0 or set(gates) != {"G1", "G2", "G3", "G4"} or any(value != "PASS" for value in gates.values()):
        raise Stop("DATE_LEVEL_STOP:PRE_GATES")
    if target_k < 1: raise Stop("DATE_LEVEL_STOP:TARGET_K")
    validate_pre_rows(current_rows, corrected_rows, target_k)

def validate_post(pre_hash_ok: bool, rows: list[dict[str, Any]]) -> None:
    if not pre_hash_ok: raise Stop("STOP_POST_PRE_HASH")
    seen = set()
    for row in rows:
        key = (row.get("race_id"), row.get("horse_number"))
        if key in seen: raise Stop("STOP_POST_DUPLICATE_HORSE")
        seen.add(key)
        if not isinstance(row.get("valid_result"), bool) or not isinstance(row.get("actual_top3"), bool): raise Stop("STOP_POST_RESULT_SEMANTICS")
        if row["valid_result"] is False and row["actual_top3"] is True: raise Stop("STOP_POST_INVALID_TOP3")

def validate_ledger(ledger: dict[str, Any]) -> None:
    validate_cumulative(ledger)
    if ledger.get("minimum_unit") != ["races", "dates"]: raise Stop("STOP_CUMULATIVE_MINIMUM_UNIT")
    if ledger.get("block_is_gate") is True: raise Stop("STOP_CUMULATIVE_BLOCK_GATE")
    if ledger.get("state") == "SUSPENDED" and not (ledger.get("suspension_reason") and ledger.get("suspended_at") and ledger.get("human_decision")):
        raise Stop("STOP_CUMULATIVE_SUSPENSION_METADATA")
