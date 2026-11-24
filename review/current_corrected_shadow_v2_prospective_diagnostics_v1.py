"""Result-row diagnostics reused from the frozen V4-v3 prospective precedent.

The functions accept already joined, frozen selections only.  They never load
raw input, a Result file, or a model.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from review.v4_model_v3_prospective_validator_v1 import concentration, lodo, selected_metric, uncertainty


def _arms(date_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"date": entry["date"], "current": entry["current_rows"], "v4": entry["corrected_rows"]}
        for entry in date_entries
    ]


def block_tables(date_entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Build diagnostic-only block and leave-one-block-out tables."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in date_entries:
        groups[entry["block_id"]].append(entry)
    table = []
    for block in sorted(groups):
        current = [r for entry in groups[block] for r in entry["current_rows"]]
        corrected = [r for entry in groups[block] for r in entry["corrected_rows"]]
        cm, vm = selected_metric(current), selected_metric(corrected)
        table.append({"block_id": block, "races": sum(entry["counted_races"] for entry in groups[block]), "current": cm, "corrected": vm, "lift": vm["buy_top3_rate"] - cm["buy_top3_rate"]})
    lobo = []
    for row in table:
        current = [r for entry in date_entries if entry["block_id"] != row["block_id"] for r in entry["current_rows"]]
        corrected = [r for entry in date_entries if entry["block_id"] != row["block_id"] for r in entry["corrected_rows"]]
        if not current or not corrected:
            lobo.append({"removed_block_id": row["block_id"], "status": "NOT_EVALUATED_INSUFFICIENT_REMAINING_EVIDENCE"})
            continue
        cm, vm = selected_metric(current), selected_metric(corrected)
        lobo.append({"removed_block_id": row["block_id"], "current": cm, "corrected": vm, "lift": vm["buy_top3_rate"] - cm["buy_top3_rate"]})
    return {"independent_block_table": table, "leave_one_block_out_table": lobo}


def diagnostics(date_entries: list[dict[str, Any]]) -> dict[str, Any]:
    arms = _arms(date_entries)
    all_current = [row for arm in arms for row in arm["current"]]
    all_corrected = [row for arm in arms for row in arm["v4"]]
    cm, vm = selected_metric(all_current), selected_metric(all_corrected)
    if len({entry["date"] for entry in date_entries}) < 2:
        return {
            "pooled": {"status": "NOT_EVALUATED_INSUFFICIENT_DATES", "current": cm, "corrected": vm},
            "leave_one_date_out": [], "temporal_fragility_flag": False,
            "temporal_concentration_flag": False, **block_tables(date_entries),
        }
    folds, fragility = lodo(arms)
    stress = concentration(arms)
    return {
        "pooled": uncertainty(cm, vm, folds, stress),
        "leave_one_date_out": folds,
        "temporal_fragility_flag": fragility,
        "temporal_concentration_flag": stress["temporal_concentration_flag"],
        **block_tables(date_entries),
    }
