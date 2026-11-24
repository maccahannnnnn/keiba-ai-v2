"""Iteration 2 Recovery Option A: static, non-executing aggregation plan.

This module deliberately contains no training, inference, result aggregation,
metric, bootstrap, Gate, or model-selection execution path.  It prepares the
immutable input contract that a separately authorized corrected aggregation may
use later.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_A = ROOT / ".tmp" / "iter2_model_runs" / "run_a.json"
RUN_B = ROOT / ".tmp" / "iter2_model_runs" / "run_b.json"
V5_TOP5_REFERENCE = (
    ROOT
    / "reports"
    / "full_field_redesign_iteration1_completion_v1"
    / "primary_global_selected_horses.csv"
)
RATIFICATION = ROOT / "docs" / "KeibaAI_WS2_FullField_Iteration2_Human_Ratification_v1.md"

CORRECTED_COMPARATORS = (
    "CURRENT_GLOBAL",
    "PP_ONLY_DETERMINISTIC",
    "V5_TOP5_TRAINED",
    "V5_FULL_FIELD_TRAINED",
    "CORRECTED_PLACKETT_LUCE",
    "CORRECTED_HIST_GRADIENT_BOOSTING",
)

# Human-ratified semantic correction; these are field mappings, not refits.
MODEL_SCORE_FIELD = {
    "CORRECTED_PLACKETT_LUCE": "p_hgb",
    "CORRECTED_HIST_GRADIENT_BOOSTING": "p_pl",
}
RANK1_GUARD = {
    "reference": "V5_FULL_FIELD_TRAINED",
    "comparison_population": "COMMON_VALID_RACE_SET",
    "minimum_delta_percentage_points": -1.0,
}
RESEARCH_CLOCK = {
    "legacy_ws2_research_start_date": "UNKNOWN_LEGACY_NOT_BACKFILLED",
    "ws2_full_field_research_start_date": "2026-10-14",
    "four_week_deadline": "2026-11-11",
    "applies_to": ("ITERATION_2", "ITERATION_3"),
    "iteration_3_clock_reset": False,
}


class CorrectionPreparationStop(RuntimeError):
    """Raised when frozen-source or non-performance contract checks fail."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_prediction_source_manifest() -> dict[str, Any]:
    """Return byte-level lineage for the two permitted new-model sources only."""
    if not RUN_A.is_file() or not RUN_B.is_file():
        raise CorrectionPreparationStop("STOP_FROZEN_RUN_SOURCE_MISSING")
    a_bytes, b_bytes = RUN_A.read_bytes(), RUN_B.read_bytes()
    return {
        "run_a": {"path": str(RUN_A.relative_to(ROOT)), "bytes": len(a_bytes), "sha256": hashlib.sha256(a_bytes).hexdigest()},
        "run_b": {"path": str(RUN_B.relative_to(ROOT)), "bytes": len(b_bytes), "sha256": hashlib.sha256(b_bytes).hexdigest()},
        "byte_identical": a_bytes == b_bytes,
    }


def load_prediction_scores_only(path: Path) -> list[dict[str, Any]]:
    """Read only fields needed for later corrected selection construction.

    Result labels are intentionally not returned or inspected by this function.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "date", "race_id", "horse_number", "p_v5", "p_pl", "p_hgb",
        "past_performance", "adjusted_score",
    }
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise CorrectionPreparationStop("STOP_FROZEN_RUN_ROWS_MISSING")
    if any(not required.issubset(row) for row in rows):
        raise CorrectionPreparationStop("STOP_FROZEN_RUN_SCHEMA")
    return [{key: row[key] for key in required} for row in rows]


def corrected_score(row: dict[str, Any], comparator: str) -> float:
    """Return a frozen score after only the ratified model-label correction."""
    if comparator not in MODEL_SCORE_FIELD:
        raise CorrectionPreparationStop("STOP_UNKNOWN_CORRECTED_COMPARATOR")
    return float(row[MODEL_SCORE_FIELD[comparator]])


def corrected_tie_break_key(row: dict[str, Any], comparator: str) -> tuple[Any, ...]:
    """Human-ratified order for equal PL/HGB scores; no rank-derived key."""
    return (
        -corrected_score(row, comparator),
        str(row["date"]),
        str(row["race_id"]),
        int(row["horse_number"]),
    )


def assert_corrected_pl_probability_mass(rows: list[dict[str, Any]], tolerance: float = 1e-8) -> None:
    """Later corrected aggregation must prove per-race PL P(top3) mass ~= 3."""
    by_race: dict[tuple[str, str], float] = defaultdict(float)
    for row in rows:
        by_race[(str(row["date"]), str(row["race_id"]))] += corrected_score(row, "CORRECTED_PLACKETT_LUCE")
    bad = {key: total for key, total in by_race.items() if abs(total - 3.0) > tolerance}
    if bad:
        raise CorrectionPreparationStop(f"STOP_CORRECTED_PL_PROBABILITY_MASS:{len(bad)}")


def correction_execution_plan() -> dict[str, Any]:
    """Static plan only; no performance values or Result-label computations."""
    return {
        "role": "DEVELOPMENT_ONLY_NON_EVIDENTIAL",
        "recovery_option": "A_AGGREGATION_ONLY_CORRECTION",
        "permitted_new_model_prediction_sources": (str(RUN_A.relative_to(ROOT)), str(RUN_B.relative_to(ROOT))),
        "v5_top5_reference_only_source": str(V5_TOP5_REFERENCE.relative_to(ROOT)),
        "comparators": CORRECTED_COMPARATORS,
        "model_score_field": MODEL_SCORE_FIELD,
        "corrected_tie_break": ["date", "existing PRE canonical race_id string order", "horse_number"],
        "rank1_guard": RANK1_GUARD,
        "research_clock": RESEARCH_CLOCK,
        "training_permitted": False,
        "prediction_rerun_permitted": False,
        "aggregation_authorized": False,
        "performance_output_authorized": False,
        "ratification_path": str(RATIFICATION.relative_to(ROOT)),
    }


def main() -> None:
    raise SystemExit(
        "Correction aggregation is not authorized. This module is static preparation only."
    )


if __name__ == "__main__":
    main()
