"""Scaffold for a future formal V4-v3 prospective run.

It refuses execution unless a caller supplies a newly approved, unseen date and
an explicit Phase-A authority.  This implementation task never invokes it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from review.v4_model_v3_prospective_validator_v1 import ROLE, ProspectiveProtocolError, same_volume


def select_same_volume(current_by_race: dict[str, list[dict]], v4_top5_by_race: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Freeze only the already-scored V4 Top5 in the protocol's fixed order.

    Model inference is deliberately outside this helper.  Its input must be the
    frozen probability records produced by the eventual Phase-A runner.
    """
    if set(current_by_race) != set(v4_top5_by_race):
        raise ProspectiveProtocolError("FORMAL_RACE_SET_MISMATCH")
    selected = {}
    for race_id, current in current_by_race.items():
        count = len(current)
        candidates = v4_top5_by_race[race_id]
        if count == 0:
            selected[race_id] = []
            continue
        if len(candidates) < count:
            raise ProspectiveProtocolError(f"V4_CANDIDATE_SHORTAGE:{race_id}")
        try:
            ordered = sorted(candidates, key=lambda row: (-float(row["predicted_actual_top3_probability"]), int(row["shadow_ai_rank"]), int(row["horse_number"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProspectiveProtocolError(f"V4_ORDERING_KEY_INVALID:{race_id}") from exc
        selected[race_id] = ordered[:count]
    same_volume(current_by_race, selected)
    return selected


def phase_a_freeze(*, date: str, phase_a_authorized: bool, result_access_count: int, current_by_race: dict[str, list[dict]], v4_by_race: dict[str, list[dict]], output_root: Path) -> dict[str, Any]:
    """Validate a future PRE selection; this function never runs Current AI or V4 inference."""
    if not phase_a_authorized:
        raise ProspectiveProtocolError("FORMAL_PROSPECTIVE_EXECUTION_NOT_AUTHORIZED")
    if result_access_count != 0:
        raise ProspectiveProtocolError("PHASE_A_RESULT_ACCESS_FORBIDDEN")
    if output_root.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{output_root}")
    same_volume(current_by_race, v4_by_race)
    return {"date": date, "evidence_role": ROLE, "phase": "A_PRE_FREEZE_VALIDATED", "result_data_access_count": 0, "formal_eligible_races": len(current_by_race), "current_selected": sum(map(len, current_by_race.values())), "v4_selected": sum(map(len, v4_by_race.values()))}
