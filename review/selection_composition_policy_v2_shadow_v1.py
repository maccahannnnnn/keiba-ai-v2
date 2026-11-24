"""Additive, Result-free Selection Composition Policy v2 shadow seam.

Candidate membership is owned by an immutable Exact5 packet.  Frozen V4 owns
only probability/rank.  Stage B owns the natural BUY decision.  Current K is
accepted as metadata only and never participates in an operational branch.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Callable

import numpy as np

from review.candidate_generation_stage_b_shadow_v1 import CandidateGenerationStageBShadow


class PolicyV2Stop(RuntimeError):
    """Fail-closed Policy v2 execution error."""


class SelectionCompositionPolicyV2Shadow:
    """Compose Exact5 → frozen V4 rank → all-five Stage B override."""

    def __init__(self, stage_b: CandidateGenerationStageBShadow | None = None):
        self.stage_b = stage_b or CandidateGenerationStageBShadow()

    @staticmethod
    def _validate_identity(exact5: list[dict], full_race_context: list[dict]) -> dict[int, dict]:
        if not isinstance(exact5, list) or len(exact5) != 5:
            raise PolicyV2Stop("STOP_POLICY_V2_CANDIDATE_COUNT")
        if not isinstance(full_race_context, list) or not full_race_context:
            raise PolicyV2Stop("STOP_POLICY_V2_FULL_CONTEXT")
        full_numbers = [row.get("horse_number") for row in full_race_context if isinstance(row, dict)]
        if len(full_numbers) != len(full_race_context) or any(isinstance(number, bool) or not isinstance(number, int) for number in full_numbers):
            raise PolicyV2Stop("STOP_POLICY_V2_IDENTITY_INVALID")
        if len(set(full_numbers)) != len(full_numbers):
            raise PolicyV2Stop("STOP_POLICY_V2_IDENTITY_DUPLICATE")
        candidate_numbers = [row.get("horse_number") for row in exact5 if isinstance(row, dict)]
        if len(candidate_numbers) != 5 or any(isinstance(number, bool) or not isinstance(number, int) for number in candidate_numbers):
            raise PolicyV2Stop("STOP_POLICY_V2_IDENTITY_INVALID")
        if len(set(candidate_numbers)) != 5:
            raise PolicyV2Stop("STOP_POLICY_V2_IDENTITY_AMBIGUOUS")
        if not set(candidate_numbers).issubset(set(full_numbers)):
            raise PolicyV2Stop("STOP_POLICY_V2_IDENTITY_UNMATCHED")
        if sorted(row.get("candidate_rank") for row in exact5) != [1, 2, 3, 4, 5]:
            raise PolicyV2Stop("STOP_POLICY_V2_CANDIDATE_RANK")
        return {int(row["horse_number"]): row for row in full_race_context}

    @staticmethod
    def _v4_rank(exact5: list[dict], probabilities: np.ndarray) -> dict[int, int]:
        if probabilities.shape != (5,) or not np.isfinite(probabilities).all():
            raise PolicyV2Stop("STOP_POLICY_V2_V4_OUTPUT")
        ordered = sorted(
            zip(exact5, probabilities),
            key=lambda pair: (
                -float(pair[1]),
                float(pair[0]["shadow_ai_rank"]),
                int(pair[0]["horse_number"]),
            ),
        )
        ranks = {int(row["horse_number"]): index + 1 for index, (row, _) in enumerate(ordered)}
        if set(ranks.values()) != {1, 2, 3, 4, 5}:
            raise PolicyV2Stop("STOP_POLICY_V2_V4_RANK")
        return ranks

    def run(
        self,
        candidate_packet: dict,
        full_race_context: list[dict],
        race_context: dict,
        *,
        model,
        scaler,
        feature_vector: Callable[[dict, str], list[float]],
        race_state: str,
        current_k_metadata: int | None = None,
    ) -> dict:
        """Execute Policy v2 without an operational K quantity.

        ``current_k_metadata`` is copied to output metadata after execution. It
        is deliberately absent from membership, inference, ranking, override,
        and Stage-B call construction.
        """
        original_packet = deepcopy(candidate_packet)
        original_context = deepcopy(full_race_context)
        try:
            exact5 = candidate_packet.get("exact5") if isinstance(candidate_packet, dict) else None
            by_number = self._validate_identity(exact5, full_race_context)
            matrix = np.asarray(
                [feature_vector(by_number[int(row["horse_number"])], race_state) for row in exact5],
                dtype=float,
            )
            if matrix.shape != (5, 21) or not np.isfinite(matrix).all():
                raise PolicyV2Stop("STOP_POLICY_V2_FEATURE_COMPLETENESS")
            probabilities = np.asarray(model.predict_proba(scaler.transform(matrix)))[:, 1]
            v4_rank = self._v4_rank(exact5, probabilities)
            override = dict(v4_rank)
            if set(override) != {int(row["horse_number"]) for row in exact5} or set(override.values()) != {1, 2, 3, 4, 5}:
                raise PolicyV2Stop("STOP_POLICY_V2_OVERRIDE")
            stage_result = self.stage_b.run(
                candidate_packet,
                full_race_context,
                race_context,
                decision_rank_override=override,
            )
            if stage_result.get("status") != "COMMITTED":
                raise PolicyV2Stop(f"STOP_POLICY_V2_STAGE_B:{stage_result.get('failure_state')}")
            if original_packet != candidate_packet or original_context != full_race_context:
                raise PolicyV2Stop("STOP_POLICY_V2_INPUT_MUTATION")
            output = {int(row["horse_number"]): row for row in stage_result["horses"]}
            if any(output[number].get("decision_rank") != rank for number, rank in v4_rank.items()):
                raise PolicyV2Stop("STOP_POLICY_V2_DECISION_RANK_MISMATCH")
            return {
                "status": "COMMITTED",
                "stage_b_result": stage_result,
                "v4_rank": v4_rank,
                "decision_rank_override": override,
                "probabilities": {int(row["horse_number"]): float(probability) for row, probability in zip(exact5, probabilities)},
                "policy_metadata": {
                    "current_k_metadata": current_k_metadata,
                    "operational_k": None,
                    "operational_k_dependency_count": 0,
                },
            }
        except PolicyV2Stop as error:
            if original_packet != candidate_packet or original_context != full_race_context:
                raise AssertionError("POLICY_V2_INPUT_MUTATED")
            return {"status": "STOP", "failure_state": str(error), "valid_policy_v2_buy_artifact": False}

