"""CURRENT_CORRECTED_SHADOW_V1.

This module is deliberately a *shadow* projection.  It does not import or
mutate the production adapter, ranking, DecisionEngine, or BUY engine.  The
all-disabled configuration is an identity projection for a frozen Current
payload; the corrected configuration is a separately auditable calculation.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any, Iterable


AUTHORITY_EVALUATORS = (
    "bloodline", "past_performance", "pace_style", "distance", "track_condition",
)
ACTIVE_SCORE_COMPONENTS = (
    "bloodline", "past_performance", "pace_style", "distance", "track_condition",
    "lap", "track_bias",
)
TRACE_ONLY_REASON_IDS = {"race_shape", "pace", "consistency", "course_shape", "impact"}
DERIVED_REASON_IDS = {"derived_multiple_major_risks"}


@dataclass(frozen=True)
class CorrectionConfig:
    """Explicit, production-safe correction switches.

    ``production_defaults`` is intentionally all false.  No caller can obtain
    corrected behaviour accidentally by importing this module.
    """
    semantic_risk_dedupe: bool = False
    impact_trace_only: bool = False
    shape_trace_only: bool = False
    pace_trace_only: bool = False
    consistency_trace_only: bool = False
    course_shape_trace_only: bool = False
    corrected_score_weights: bool = False
    low_history_race_median: bool = False
    reliability_4_of_5: bool = False
    gate_correction: bool = False
    relative_gap_trace_only: bool = False
    competitive_skip_trace_only: bool = False
    consensus_targeted_rescue_disabled: bool = False

    @classmethod
    def production_defaults(cls) -> "CorrectionConfig":
        return cls()

    @classmethod
    def corrected_shadow(cls) -> "CorrectionConfig":
        return cls(**{key: True for key in asdict(cls()).keys()})

    def enabled(self) -> bool:
        return any(asdict(self).values())


def _text(value: Any) -> str:
    return str(value or "").strip()


def semantic_reason_id(item: Any) -> str:
    """Return a stable reason id without changing the display wording.

    Legacy records have no semantic id, so their exact text is the only safe
    deduplication key.  Importantly, a bare Japanese "不足" is not classified
    as data shortage; only an explicit id (or an explicit data-limitation
    marker) receives that authority.
    """
    if isinstance(item, dict):
        explicit = _text(item.get("semantic_reason_id") or item.get("reason_id"))
        if explicit:
            return explicit
        if bool(item.get("data_limitation")):
            return "data_shortage"
        return "legacy:" + _text(item.get("text") or item.get("display") or item.get("reason"))
    return "legacy:" + _text(item)


def risk_display(item: Any) -> str:
    if isinstance(item, dict):
        return _text(item.get("text") or item.get("display") or item.get("reason"))
    return _text(item)


def dedupe_authority_risks(items: Iterable[Any]) -> list[dict[str, Any]]:
    """Deduplicate by semantic id and remove non-authority/derived causes."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        reason_id = semantic_reason_id(item)
        root = reason_id.split(":", 1)[0]
        if reason_id in seen or root in TRACE_ONLY_REASON_IDS or reason_id in DERIVED_REASON_IDS:
            continue
        seen.add(reason_id)
        result.append({
            "semantic_reason_id": reason_id,
            "text": risk_display(item),
            "data_limitation": reason_id == "data_shortage",
        })
    return result


def reliability_4_of_5(evaluators: dict[str, Any]) -> dict[str, Any]:
    positive = [name for name in AUTHORITY_EVALUATORS if float(evaluators.get(name, 0) or 0) > 0]
    negative = [name for name in AUTHORITY_EVALUATORS if float(evaluators.get(name, 0) or 0) < 0]
    return {
        "authority_evaluators": list(AUTHORITY_EVALUATORS),
        "positive": positive,
        "negative": negative,
        "positive_count": len(positive),
        "negative_count": len(negative),
        "pass": len(positive) >= 4 and len(negative) <= 1,
    }


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _history_count(row: dict[str, Any]) -> int:
    return int(_number(row.get("valid_history_count", row.get("past_race_count", 0))))


def apply_corrected_shadow(rows: list[dict[str, Any]], config: CorrectionConfig) -> list[dict[str, Any]]:
    """Produce a separately auditable shadow result for one race.

    The score is intentionally additive with unit component weights.  Inputs
    are evaluator outputs, not outcome data.  This helper neither reads result
    files nor writes to the production records passed to it.
    """
    if not config.enabled():
        return deepcopy(rows)

    reference_pp = [
        _number(row.get("past_performance_score")) for row in rows if _history_count(row) >= 2
    ]
    race_median_pp = median(reference_pp) if reference_pp else None
    projected: list[dict[str, Any]] = []
    for original in rows:
        row = deepcopy(original)
        pp_original = _number(row.get("past_performance_score"))
        low_history = _history_count(row) <= 1
        pp_ranking = pp_original
        unavailable = False
        if config.low_history_race_median and low_history:
            if race_median_pp is None:
                unavailable = True
            else:
                pp_ranking = float(race_median_pp)

        components = {
            "bloodline": _number(row.get("bloodline_score")),
            "past_performance": pp_ranking,
            "pace_style": _number(row.get("pace_style_score")),
            "distance": _number(row.get("distance_score")),
            "track_condition": _number(row.get("track_condition_score")),
            "lap": _number(row.get("lap_score")),
            "track_bias": _number(row.get("track_bias_score")),
        }
        integrated = sum(components.values())
        trace = {
            "impact": row.get("impact_score"),
            "shape_score": row.get("shape_score"),
            "shape_table_key": row.get("shape_table_key"),
            "race_pace_prediction": row.get("race_pace_prediction"),
            "pace_downstream_value": "average",
            "consistency_score": row.get("consistency_score"),
            "strong_matches": deepcopy(row.get("strong_matches", [])),
            "conflict_factors": deepcopy(row.get("conflict_factors", [])),
            "course_shape_score": row.get("course_shape_score"),
            "track_bias_inert": _number(row.get("track_bias_score")) == 0,
        }
        style_candidates = row.get("tied_style_candidates", [])
        trace["style_ambiguous"] = bool(style_candidates) or bool(row.get("style_ambiguous"))
        trace["tied_style_candidates"] = deepcopy(style_candidates)
        risks = dedupe_authority_risks(
            list(row.get("weaknesses", [])) + list(row.get("risk_factors", []))
            + list(row.get("decision_risks", [])) + list(row.get("final_weaknesses", []))
            + list(row.get("final_risks", []))
        ) if config.semantic_risk_dedupe else []
        evaluator_scores = row.get("evaluator_scores")
        if not isinstance(evaluator_scores, dict):
            evaluator_scores = {
                "bloodline": row.get("bloodline_score"),
                "past_performance": row.get("past_performance_score"),
                "pace_style": row.get("pace_style_score"),
                "distance": row.get("distance_score"),
                "track_condition": row.get("track_condition_score"),
            }
        reliability = reliability_4_of_5(evaluator_scores) if config.reliability_4_of_5 else {}
        rank = int(_number(row.get("rank", row.get("final_rank", 999))))
        risk_guard = len(risks) < 6 and not any(x["data_limitation"] for x in risks)
        relative = rank <= 5
        candidate = bool(relative and reliability.get("pass", False) and risk_guard)
        row["corrected_shadow"] = {
            "version": "CURRENT_CORRECTED_SHADOW_V1",
            "score_components": components,
            "score_weights": {key: 1.0 for key in ACTIVE_SCORE_COMPONENTS},
            "integrated_score": integrated,
            "adjusted_score": integrated,  # impact is trace-only
            "past_performance_vote_score": pp_original,
            "low_history": low_history,
            "imputation_unavailable": unavailable,
            "trace": trace,
            "authority_risks": risks,
            "risk_guard_pass": risk_guard,
            "relative_rank_pass": relative,
            "relative_score_gap_trace_only": row.get("relative_score_gap"),
            "competitive_skip_trace_only": row.get("competitive_skip"),
            "decision_score_trace_only": row.get("decision_score"),
            "consensus_targeted_rescue": "DISABLED",
            "reliability": reliability,
            "candidate": candidate,
        }
        projected.append(row)
    # Corrected ranking is a shadow-only ordering.  Stable sorting keeps input
    # order for an exact score tie; no new tie-break threshold is introduced.
    ordered = sorted(enumerate(projected), key=lambda pair: (-pair[1]["corrected_shadow"]["adjusted_score"], pair[0]))
    for corrected_rank, (_, row) in enumerate(ordered, start=1):
        shadow = row["corrected_shadow"]
        shadow["rank"] = corrected_rank
        shadow["relative_rank_pass"] = corrected_rank <= 5
        shadow["candidate"] = bool(
            shadow["relative_rank_pass"]
            and shadow["reliability"].get("pass", False)
            and shadow["risk_guard_pass"]
        )
    candidates = [row for row in projected if row["corrected_shadow"]["candidate"]]
    candidate_count = len(candidates)
    race_state = (
        "SKIP" if candidate_count == 0 else
        "PLAY_CONVERGED" if candidate_count <= 3 else
        "PLAY_UNCONVERGED_4PLUS"
    )
    for row in projected:
        shadow = row["corrected_shadow"]
        shadow["race_state"] = race_state
        shadow["buy"] = bool(shadow["candidate"] and race_state == "PLAY_CONVERGED")
    return projected


def assert_production_reproduction(frozen_current: list[dict[str, Any]], projected: list[dict[str, Any]]) -> int:
    """Assert exact OFF-mode equality and return matched horse count."""
    if frozen_current != projected:
        raise AssertionError("PRODUCTION_REPRODUCTION_MISMATCH")
    return len(frozen_current)
