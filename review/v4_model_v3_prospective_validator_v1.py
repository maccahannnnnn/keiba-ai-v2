"""Pure validation and disclosure helpers for the V4-v3 prospective protocol.

No function in this module reads raw sources, Results, Model artifacts, or
existing evidence.  The future runner supplies already-frozen records.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


MIN_RACES, MIN_DATES = 60, 12
ROLE = "FORMAL_PROSPECTIVE_SHADOW_V4_MODEL_V3"
NON_FORMAL_DATES = {"20260301", "20260307", "20260308", "20260314", "20260315", "20260321", "20260322", "20260328", "20260329", "20260822", "20260823", "20260829"}


class ProspectiveProtocolError(ValueError):
    pass


def selected_metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply frozen valid-result semantics without inventing any outcome."""
    for row in rows:
        if not isinstance(row.get("valid_result"), bool) or not isinstance(row.get("actual_top3"), bool):
            raise ProspectiveProtocolError("INVALID_RESULT_SEMANTICS_REQUIRED")
        if not row["valid_result"] and row["actual_top3"]:
            raise ProspectiveProtocolError("INVALID_RESULT_CANNOT_BE_TOP3")
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(row["actual_top3"] for row in valid)
    return {"selected_count": len(rows), "valid_selected_count": len(valid), "invalid_selected_count": len(rows) - len(valid), "top3_hits": hits, "buy_top3_rate": hits / len(valid) if valid else None}


def same_volume(current_by_race: dict[str, list[dict]], v4_by_race: dict[str, list[dict]]) -> None:
    if set(current_by_race) != set(v4_by_race):
        raise ProspectiveProtocolError("FORMAL_RACE_SET_MISMATCH")
    for race_id, current in current_by_race.items():
        if len(current) == 0 and len(v4_by_race[race_id]) != 0:
            raise ProspectiveProtocolError(f"CURRENT_BUY_ZERO_FORMAL_V4_SELECTION:{race_id}")
        if len(current) != len(v4_by_race[race_id]):
            raise ProspectiveProtocolError(f"SAME_VOLUME_MISMATCH:{race_id}")


def lift(current: dict[str, Any], v4: dict[str, Any]) -> dict[str, float | int]:
    if current["buy_top3_rate"] is None or v4["buy_top3_rate"] is None:
        raise ProspectiveProtocolError("VALID_DENOMINATOR_REQUIRED")
    value = v4["buy_top3_rate"] - current["buy_top3_rate"]
    return {"raw_hit_difference": v4["top3_hits"] - current["top3_hits"], "lift": value, "lift_percentage_points": value * 100}


def lodo(date_records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    dates = sorted({row["date"] for row in date_records})
    folds = []
    for excluded in dates:
        current = [horse for row in date_records if row["date"] != excluded for horse in row["current"]]
        v4 = [horse for row in date_records if row["date"] != excluded for horse in row["v4"]]
        item = {"excluded_date": excluded, "remaining_dates": len(dates)-1, "remaining_races": sum(row["date"] != excluded for row in date_records), "current": selected_metric(current), "v4": selected_metric(v4)}
        item.update(lift(item["current"], item["v4"]))
        folds.append(item)
    return folds, any(row["lift"] < 0 for row in folds)


def concentration(date_records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"current": [], "v4": []})
    for row in date_records:
        grouped[row["date"]]["current"].extend(row["current"])
        grouped[row["date"]]["v4"].extend(row["v4"])
    contributions = []
    for date, values in grouped.items():
        contributions.append({"date": date, "hit_contribution": selected_metric(values["v4"])["top3_hits"] - selected_metric(values["current"])["top3_hits"]})
    contributions.sort(key=lambda x: (-x["hit_contribution"], x["date"]))
    excluded = [row["date"] for row in contributions[:math.ceil(len(grouped)/3)]]
    current = [horse for date, values in grouped.items() if date not in excluded for horse in values["current"]]
    v4 = [horse for date, values in grouped.items() if date not in excluded for horse in values["v4"]]
    cm, vm = selected_metric(current), selected_metric(v4)
    return {"date_contributions": contributions, "excluded_dates": excluded, "remaining_current": cm, "remaining_v4": vm, **lift(cm, vm), "temporal_concentration_flag": lift(cm, vm)["lift"] < 0}


def uncertainty(current: dict[str, Any], v4: dict[str, Any], lodo_folds: list[dict[str, Any]], stress: dict[str, Any]) -> dict[str, Any]:
    p1, p2 = current["buy_top3_rate"], v4["buy_top3_rate"]
    n1, n2 = current["valid_selected_count"], v4["valid_selected_count"]
    pooled = (current["top3_hits"] + v4["top3_hits"]) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1/n1 + 1/n2)) if pooled not in {0, 1} else 0.0
    z = None if se == 0 else (p2-p1)/se
    p_approx = None if z is None else math.erfc(abs(z) / math.sqrt(2))
    return {"label": "APPROXIMATE_DIAGNOSTIC_ONLY", "dependence_note": "RACE_WITHIN_SELECTION_DEPENDENCE_NOT_MODELED", "current_valid_n": n1, "v4_valid_n": n2, "raw_hit_difference": v4["top3_hits"]-current["top3_hits"], "pooled_lift_percentage_points": (p2-p1)*100, "approximate_two_proportion_z": z, "approximate_p_value_equivalent": p_approx, "lodo_lift_range_percentage_points": [min(x["lift_percentage_points"] for x in lodo_folds), max(x["lift_percentage_points"] for x in lodo_folds)] if lodo_folds else None, "concentration": stress}


def decision_state(eligible_races: int, eligible_dates: int, pooled_lift_pt: float, fragility: bool, concentration_flag: bool) -> dict[str, str]:
    if eligible_races < MIN_RACES or eligible_dates < MIN_DATES:
        return {"state": "SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE", "candidate_state": "RUNNING", "gate": "NOT_EVALUATED"}
    if pooled_lift_pt < 0:
        return {"state": "V4_MODEL_V3_PROSPECTIVE_GATE_FAIL", "candidate_state": "V4_MODEL_V3_PROSPECTIVE_REJECT", "gate": "FAIL"}
    suffix = ""
    if fragility and concentration_flag: suffix = "_WITH_TEMPORAL_FRAGILITY_AND_CONCENTRATION_FLAG"
    elif fragility: suffix = "_WITH_TEMPORAL_FRAGILITY_FLAG"
    elif concentration_flag: suffix = "_WITH_TEMPORAL_CONCENTRATION_FLAG"
    return {"state": "V4_MODEL_V3_PROSPECTIVE_ACCEPT" + suffix, "candidate_state": "PRODUCTION_DESIGN_REVIEW_ELIGIBLE", "gate": "PASS"}


def validate_ledger(ledger: dict[str, Any]) -> None:
    if ledger.get("evidence_role") != ROLE:
        raise ProspectiveProtocolError("EVIDENCE_ROLE_INVALID")
    if any(date in NON_FORMAL_DATES for date in ledger.get("eligible_dates", [])):
        raise ProspectiveProtocolError("NON_FORMAL_EVIDENCE_DATE_FORBIDDEN")
    if ledger.get("state") == "SUSPENDED" and not all(ledger.get(key) for key in ("suspension_reason", "suspension_timestamp", "human_decision")):
        raise ProspectiveProtocolError("SUSPENDED_METADATA_REQUIRED")
    if ledger.get("state") not in {"NOT_STARTED", "RUNNING", "SUSPENDED", "V4_MODEL_V3_PROSPECTIVE_REJECT", "PRODUCTION_DESIGN_REVIEW_ELIGIBLE"}:
        raise ProspectiveProtocolError("LEDGER_STATE_INVALID")


def phase_a_technical_correction_allowed(*, aggregate_performance_disclosed: bool, human_approved_scope: bool, prediction_selection_semantics_unchanged: bool) -> bool:
    """The sole, pre-disclosure exception to the protocol freeze boundary."""
    if aggregate_performance_disclosed:
        raise ProspectiveProtocolError("POST_DISCLOSURE_PROTOCOL_MUTATION_REJECTED")
    if not human_approved_scope or not prediction_selection_semantics_unchanged:
        raise ProspectiveProtocolError("PHASE_A_CORRECTION_REQUIREMENTS_UNMET")
    return True
