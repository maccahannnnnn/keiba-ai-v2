"""Frozen, PRE-only V3 selector over an existing Prediction/Trace artifact.

This is a semantically inert wrapper: it reads the frozen V2 pipeline, uses
only existing ``shadow_buy_candidate`` eligibility, and creates no Production
decision.  It never implements Gate booleans, refits, or accesses Results.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import joblib
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "reports" / "low_capacity_top3_selector_v2_train_v1_retry2" / "low_capacity_top3_selector_v2_pipeline.joblib"
MODEL_SHA256 = "486a2af2c1d3e6426a5031c0bff7e926ccd2154a4d46176b7bd6b6a712820a8c"
FEATURES = ("Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle")
V3_SCOPE = "PLAY_UNCONVERGED_4PLUS"


class V3PreSelectionError(ValueError):
    """Fail-closed V3 PRE selection error with a stable reason code."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen_v3_model(path: Path = MODEL_PATH):
    """Load the designated frozen model and reject a substituted artifact."""
    actual = sha256(path)
    if actual != MODEL_SHA256:
        raise V3PreSelectionError(f"APRIL_PRE_PHASE0_MODEL_SHA_MISMATCH:{actual}")
    pipeline = joblib.load(path)
    steps = [name for name, _ in getattr(pipeline, "steps", [])]
    if steps != ["scaler", "logistic_regression"]:
        raise V3PreSelectionError("APRIL_PRE_PHASE0_MODEL_PIPELINE_MISMATCH")
    scaler = pipeline.named_steps["scaler"]
    logistic = pipeline.named_steps["logistic_regression"]
    if getattr(scaler, "n_features_in_", None) != len(FEATURES) or getattr(logistic, "n_features_in_", None) != len(FEATURES):
        raise V3PreSelectionError("APRIL_PRE_PHASE0_FEATURE_ORDER_MISMATCH")
    return pipeline


def _rank_key(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value).is_integer() or int(value) < 1:
        raise V3PreSelectionError(f"APRIL_PRE_PHASE0_SAFE_RANK_INVALID:{context}")
    return int(value)


def _horse_number(value: object, context: str) -> int:
    if isinstance(value, bool) or value is None:
        raise V3PreSelectionError(f"APRIL_PRE_PHASE0_RANKED_HORSE_NUMBER_INVALID:{context}")
    text = str(value).strip()
    if not text.isdigit() or int(text) < 1:
        raise V3PreSelectionError(f"APRIL_PRE_PHASE0_RANKED_HORSE_NUMBER_INVALID:{context}")
    return int(text)


def _feature_vector(snapshot: object, context: str) -> list[float]:
    if not isinstance(snapshot, dict):
        raise V3PreSelectionError(f"APRIL_PRE_PHASE0_FEATURE_SNAPSHOT_MISSING:{context}")
    vector: list[float] = []
    for feature in FEATURES:
        value = snapshot.get(feature)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise V3PreSelectionError(f"APRIL_PRE_PHASE0_FEATURE_ORDER_MISMATCH:{context}:{feature}")
        vector.append(float(value))
    return vector


def select_v3_pre(payload: dict, pipeline=None) -> dict:
    """Return a V3 Shadow-only selection for one frozen PRE artifact.

    ``ranked_results[].horse_number`` is the sole authoritative horse-number
    source.  Trace horse-number echo fields are intentionally not read.
    Trace-to-ranked mapping is by the already-frozen safe rank, and fails
    closed unless ranks are unique and complete.
    """
    if not isinstance(payload, dict):
        raise V3PreSelectionError("APRIL_PRE_PHASE0_ARTIFACT_INVALID")
    race_id = payload.get("race_id")
    trace = payload.get("buy_gate_trace")
    ranked = payload.get("ranked_results")
    if not isinstance(race_id, str) or not isinstance(trace, dict) or not isinstance(ranked, list):
        raise V3PreSelectionError("APRIL_PRE_PHASE0_TRACE_STRUCTURE_MISMATCH")
    race = trace.get("race")
    trace_horses = trace.get("horses")
    if not isinstance(race, dict) or not isinstance(trace_horses, list):
        raise V3PreSelectionError("APRIL_PRE_PHASE0_TRACE_STRUCTURE_MISMATCH")
    state = race.get("shadow_race_state")
    if state != V3_SCOPE:
        return {"race_id": race_id, "race_state": state, "eligible": False, "gate_eligible_count": 0, "selected": [], "all_candidates": []}

    ranked_by_safe_rank: dict[int, dict] = {}
    for row in ranked:
        if not isinstance(row, dict):
            raise V3PreSelectionError(f"APRIL_PRE_PHASE0_RANKED_RESULT_INVALID:{race_id}")
        rank = _rank_key(row.get("rank"), race_id)
        if rank in ranked_by_safe_rank:
            raise V3PreSelectionError(f"APRIL_PRE_PHASE0_RANKED_SAFE_RANK_DUPLICATE:{race_id}:{rank}")
        ranked_by_safe_rank[rank] = row

    candidates: list[dict] = []
    seen_safe_ranks: set[int] = set()
    for index, trace_row in enumerate(trace_horses):
        if not isinstance(trace_row, dict):
            raise V3PreSelectionError(f"APRIL_PRE_PHASE0_TRACE_HORSE_INVALID:{race_id}:{index}")
        eligible = trace_row.get("shadow_buy_candidate")
        if not isinstance(eligible, bool):
            raise V3PreSelectionError(f"APRIL_PRE_PHASE0_ELIGIBILITY_INVALID:{race_id}:{index}")
        if not eligible:
            continue
        safe_rank = _rank_key(trace_row.get("shadow_ai_rank"), f"{race_id}:{index}")
        if safe_rank in seen_safe_ranks or safe_rank not in ranked_by_safe_rank:
            raise V3PreSelectionError(f"APRIL_PRE_PHASE0_TRACE_RANK_MAPPING_FAILURE:{race_id}:{safe_rank}")
        seen_safe_ranks.add(safe_rank)
        ranked_row = ranked_by_safe_rank[safe_rank]
        horse_number = _horse_number(ranked_row.get("horse_number"), f"{race_id}:{safe_rank}")
        candidates.append({
            "horse_number": horse_number,
            "horse_name": ranked_row.get("horse_name"),
            "shadow_ai_rank": safe_rank,
            "feature_vector": _feature_vector(trace_row.get("evaluator_score_snapshot"), f"{race_id}:{safe_rank}"),
            "source_trace_row_identifier": f"buy_gate_trace.horses[{index}]",
            "source_ranked_row_identifier": f"ranked_results[rank={safe_rank}]",
        })
    declared_count = race.get("shadow_candidate_count")
    if isinstance(declared_count, bool) or not isinstance(declared_count, int) or declared_count != len(candidates):
        raise V3PreSelectionError(f"APRIL_PRE_PHASE0_CANDIDATE_COUNT_MISMATCH:{race_id}")
    if len(candidates) < 4:
        raise V3PreSelectionError(f"APRIL_PRE_PHASE0_UNCONVERGED_SCOPE_MISMATCH:{race_id}:{len(candidates)}")

    active_pipeline = pipeline if pipeline is not None else load_frozen_v3_model()
    matrix = np.asarray([row.pop("feature_vector") for row in candidates], dtype=float)
    probabilities = active_pipeline.predict_proba(matrix)
    if probabilities.shape != (len(candidates), 2):
        raise V3PreSelectionError(f"APRIL_PRE_PHASE0_PROBABILITY_SHAPE_MISMATCH:{race_id}:{probabilities.shape}")
    for row, probability in zip(candidates, probabilities[:, 1], strict=True):
        row["predicted_top3_probability"] = float(probability)
    ordered = sorted(candidates, key=lambda row: (-row["predicted_top3_probability"], row["shadow_ai_rank"], row["horse_number"]))
    selected = [{**row, "selection_rank": position} for position, row in enumerate(ordered[:3], start=1)]
    if len(selected) != 3:
        raise V3PreSelectionError(f"APRIL_PRE_PHASE0_MAX3_MISMATCH:{race_id}")
    return {"race_id": race_id, "race_state": state, "eligible": True, "gate_eligible_count": len(candidates), "selected": selected, "all_candidates": ordered}
