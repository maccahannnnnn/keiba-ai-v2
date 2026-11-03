"""Pure, post-Result decision/diagnostic helpers for the frozen PL+J addendum.

This module opens no files and has no PRE, model, or Production execution path.
Callers must supply frozen PRE identities and a verified, later Result join.
"""

from __future__ import annotations

from collections import Counter
from math import erfc, sqrt
import random


def require_paired_identity(days: list[dict]) -> None:
    for day in days:
        if not (day["same_race"] and day["same_k"] and day["same_volume"]):
            raise ValueError("STOP_PLJ_CURRENT_PAIRED_IDENTITY")
        if day["plj_slots"] != day["current_slots"] or day["plj_slots"] < 0:
            raise ValueError("STOP_PLJ_CURRENT_PAIRED_VOLUME")


def ordinary_rate(rows: list[dict]) -> dict:
    valid = [r for r in rows if r["valid_result"]]
    hits = sum(bool(r["actual_top3"]) for r in valid)
    return {"selected": len(rows), "invalid": len(rows) - len(valid),
            "valid": len(valid), "hits": hits,
            "buy_top3_rate": hits / len(valid) if valid else None}


def rule_a_hits(rows: list[dict]) -> int:
    # Existing all-selected-slots Rule A: invalid is a non-hit, not an excluded slot.
    return sum(bool(r["valid_result"] and r["actual_top3"]) for r in rows)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    position = (len(sorted_values) - 1) * fraction
    lower = int(position)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[min(lower + 1, len(sorted_values) - 1)] * weight


def date_bootstrap(days: list[dict], *, seed: int = 20261103, draws: int = 10000) -> tuple[float, float] | None:
    if not days or draws < 2 or sum(d["plj_slots"] for d in days) == 0:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(draws):
        sample = rng.choices(days, k=len(days))
        slots = sum(d["plj_slots"] for d in sample)
        if slots == 0:
            return None
        values.append(100 * sum(d["delta_hits"] for d in sample) / slots)
    values.sort()
    return _percentile(values, .025), _percentile(values, .975)


def decision(days: list[dict], *, parent_suspended: bool = False,
             bootstrap_ci: tuple[float, float] | None = None) -> dict:
    require_paired_identity(days)
    ordered = sorted(days, key=lambda d: d["date"])
    if len({d["date"] for d in ordered}) != len(ordered):
        raise ValueError("STOP_DUPLICATE_ELIGIBLE_DATE")
    slots = sum(d["plj_slots"] for d in ordered)
    races = sum(d["eligible_races"] for d in ordered)
    delta = sum(d["delta_hits"] for d in ordered)
    point = 100 * delta / slots if slots else None
    ci = bootstrap_ci if bootstrap_ci is not None else date_bootstrap(ordered)
    valid_n = sum(d["plj_valid_n"] for d in ordered)
    valid_hits = sum(d["plj_valid_hits"] for d in ordered)
    ordinary = valid_hits / valid_n if valid_n else None
    second = sum(d["delta_hits"] for d in ordered[len(ordered) // 2:])
    strongest = sorted(ordered, key=lambda d: (-d["delta_hits"], d["date"]))[:2]
    after_top2 = delta - sum(d["delta_hits"] for d in strongest)
    z = delta / (.5 * sqrt(slots)) if slots else None
    p_two_sided = erfc(abs(z) / sqrt(2)) if z is not None else None
    first = len(ordered) >= 12 and races >= 60
    final = len(ordered) >= 24 and races >= 120
    accept = (first and point is not None and point >= 5 and ci is not None
              and ci[0] > 0 and ordinary is not None and ordinary >= .4
              and second >= 0 and after_top2 > 0)
    if parent_suspended:
        status = "PARENT_SUSPEND_HUMAN_REVIEW"
    elif final and (delta <= 0 or (ci is not None and ci[1] < 0)):
        status = "REJECT"
    elif accept:
        status = "ACCEPT"
    elif final:
        status = "INCONCLUSIVE_CLOSE"
    elif first:
        status = "CONTINUE_OBSERVATION"
    else:
        status = "BELOW_FIRST_MINIMUM"
    return {"status": status, "eligible_dates": len(ordered), "eligible_races": races,
            "paired_selection_slots": slots, "delta_hits": delta, "delta_pt": point,
            "bootstrap_ci95_pt": ci, "plj_ordinary_valid_rate": ordinary,
            "second_half_delta_hits": second, "top_two_removed_delta_hits": after_top2,
            "approx_z": z, "approx_p_two_sided": p_two_sided,
            "harm_warning": bool(first and z is not None and z <= -1.645),
            "first_checkpoint_reached": first, "final_checkpoint_reached": final}


def field_size_diagnostic(rows: list[dict]) -> dict:
    if any(int(r["field_size"]) <= 0 for r in rows):
        raise ValueError("STOP_INVALID_PRE_FIELD_SIZE")
    valid = [r for r in rows if r["valid_result"]]
    n = len(valid)
    hits = sum(bool(r["actual_top3"]) for r in valid)
    expected = sum(min(3, int(r["field_size"])) / int(r["field_size"]) for r in valid)
    p = hits / n if n else None
    b = expected / n if n else None
    odds_ratio = (p / (1-p)) / (b / (1-b)) if p is not None and b is not None and 0 < p < 1 and 0 < b < 1 else None
    return {"selected": len(rows), "invalid": len(rows)-n, "valid": n, "hits": hits,
            "rate": p, "expected_hits": expected, "excess_hits": hits-expected,
            "mean_field_size_base_rate": b, "base_rate_ratio": p/b if b else None,
            "statistical_odds_ratio": odds_ratio,
            "field_size_distribution": dict(sorted(Counter(int(r["field_size"]) for r in rows).items())),
            "mean_field_size": sum(int(r["field_size"]) for r in rows)/len(rows) if rows else None}


def smallest_field_first(pre_rows: list[dict], daily_n: int) -> list[dict]:
    if daily_n < 0:
        raise ValueError("STOP_NEGATIVE_DAILY_N")
    chosen = []
    counts = Counter()
    for row in sorted(pre_rows, key=lambda r: (int(r["field_size"]), str(r["race_id"]), int(r["horse_number"]))):
        race = str(row["race_id"])
        if counts[race] < 3 and len(chosen) < daily_n:
            chosen.append(row)
            counts[race] += 1
    if len(chosen) != daily_n:
        raise ValueError("NOT_EVALUABLE_INSUFFICIENT_PRE_CAPACITY")
    return chosen


def overlap_class(plj_keys: set[tuple], e1_keys: set[tuple]) -> dict[str, set[tuple]]:
    return {"PL_JOCKEY_E1_OVERLAP": plj_keys & e1_keys,
            "PL_JOCKEY_NON_OVERLAP": plj_keys - e1_keys,
            "E1_NON_OVERLAP": e1_keys - plj_keys}


def global_allocation(pre_rows: list[dict], daily_n: int) -> list[dict]:
    if any(r.get("plj_p_top3") is None for r in pre_rows):
        raise ValueError("NOT_EVALUABLE_MISSING_FULL_FIELD_SCORE")
    ranked = sorted(pre_rows, key=lambda r: (-float(r["plj_p_top3"]), str(r["race_id"]), int(r["horse_number"])))
    chosen, counts = [], Counter()
    for row in ranked:
        race = str(row["race_id"])
        if counts[race] < 3 and len(chosen) < daily_n:
            chosen.append(row)
            counts[race] += 1
    if len(chosen) != daily_n:
        raise ValueError("NOT_EVALUABLE_INSUFFICIENT_PRE_CAPACITY")
    return chosen


def require_post_source(*, result_exists: bool, result_read_after_freeze: bool) -> None:
    if not result_exists or not result_read_after_freeze:
        raise ValueError("STOP_RESULT_NOT_AVAILABLE_AFTER_PRE_FREEZE")
