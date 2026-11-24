"""Deterministic race-local adjusted-score gap feature."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Mapping


class RelativeGapFeatureError(ValueError):
    """Input is not safe for deterministic feature construction."""


def _finite_score(value: object, row_identity: str) -> float:
    if isinstance(value, bool):
        raise RelativeGapFeatureError(f"ADJUSTED_SCORE_INVALID:{row_identity}")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise RelativeGapFeatureError(f"ADJUSTED_SCORE_INVALID:{row_identity}") from exc
    if not math.isfinite(numeric):
        raise RelativeGapFeatureError(f"ADJUSTED_SCORE_INVALID:{row_identity}")
    return numeric


def adjusted_score_gap_to_top(rows: Iterable[Mapping[str, object]]) -> dict[str, float]:
    """Return each row's score minus the maximum score in its race group."""
    grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
    seen: set[str] = set()
    for row in rows:
        race_id = row.get("race_id")
        row_id = row.get("row_id")
        if not isinstance(race_id, str) or not race_id or not isinstance(row_id, str) or not row_id:
            raise RelativeGapFeatureError("RACE_OR_ROW_ID_INVALID")
        if row_id in seen:
            raise RelativeGapFeatureError(f"ROW_ID_DUPLICATE:{row_id}")
        seen.add(row_id)
        grouped[race_id].append((row_id, _finite_score(row.get("adjusted_score"), row_id)))
    if not grouped:
        raise RelativeGapFeatureError("EMPTY_FEATURE_INPUT")
    values: dict[str, float] = {}
    for race_rows in grouped.values():
        top = max(score for _, score in race_rows)
        for row_id, score in race_rows:
            values[row_id] = score - top
    return values
