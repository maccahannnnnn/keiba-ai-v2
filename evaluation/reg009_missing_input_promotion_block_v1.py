"""Shadow-only REG-009 promotion block based on existing missing-input signals.

The feature flag defaults to OFF.  This module is not connected to Production
and never changes scores, ranks, decisions, confidence, or existing BUY.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


FEATURE_FLAG_NAME = "REG009_MISSING_INPUT_PROMOTION_BLOCK_V1_ENABLED"
VERSION = "missing_input_promotion_block_v1"
RULE_ID = "MISSING_INPUT_PROMOTION_BLOCK_V1"

# Exact values already exported by existing KeibaAI provenance/guards.
# Deliberately no substring, score, rank, risk-count, or result-based matching.
EXISTING_MISSING_INPUT_SIGNALS = frozenset(
    {
        "profile not found",
        "Bloodline profile not found",
        "入力データに一部不足あり",
        "evaluator_score_missing",
        "large_data_limitation_present",
    }
)
SOURCE_FIELDS = (
    "missing_input_categories",
    "consensus_block_reasons",
    "warnings",
    "risk_reasons",
)


@dataclass(frozen=True)
class MissingInputPromotionBlockResult:
    feature_flag_enabled: bool
    production_buy: bool
    reg009_promoted: bool
    shadow_buy_before: bool
    shadow_buy_after: bool
    promotion_blocked: bool
    missing_input_signal_present: bool
    matched_missing_input_signals: tuple[str, ...]
    condition_count: int = 1
    rule_id: str = RULE_ID
    version: str = VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "missing_input_promotion_block_v1_enabled": self.feature_flag_enabled,
            "production_buy": self.production_buy,
            "reg009_promoted": self.reg009_promoted,
            "reg009_shadow_buy_before_missing_input_block": self.shadow_buy_before,
            "reg009_shadow_buy_after_missing_input_block": self.shadow_buy_after,
            "missing_input_promotion_block_applied": self.promotion_blocked,
            "missing_input_signal_present": self.missing_input_signal_present,
            "matched_missing_input_signals": list(self.matched_missing_input_signals),
            "missing_input_promotion_block_condition_count": self.condition_count,
            "missing_input_promotion_block_rule_id": self.rule_id,
            "missing_input_promotion_block_version": self.version,
        }


class MissingInputPromotionBlockV1:
    """Block only a REG-009-added Shadow BUY carrying an existing missing signal."""

    def __init__(self, enabled: bool | None = None):
        self.enabled = self._env_enabled() if enabled is None else bool(enabled)

    @staticmethod
    def _env_enabled() -> bool:
        return str(os.getenv(FEATURE_FLAG_NAME, "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def evaluate(self, row: dict[str, Any]) -> MissingInputPromotionBlockResult:
        production_buy = self._bool(row.get("production_buy", False))
        promoted = self._bool(row.get("reg009_promoted", False))
        shadow_before = self._bool(row.get("reg009_shadow_buy", promoted or production_buy))
        matched = tuple(sorted(self._existing_missing_signals(row)))
        missing_present = bool(matched)
        block = bool(
            self.enabled
            and promoted
            and shadow_before
            and not production_buy
            and missing_present
        )
        return MissingInputPromotionBlockResult(
            feature_flag_enabled=self.enabled,
            production_buy=production_buy,
            reg009_promoted=promoted,
            shadow_buy_before=shadow_before,
            shadow_buy_after=shadow_before and not block,
            promotion_blocked=block,
            missing_input_signal_present=missing_present,
            matched_missing_input_signals=matched,
        )

    def annotate(self, row: dict[str, Any]) -> dict[str, Any]:
        annotated = dict(row)
        annotated.update(self.evaluate(row).to_dict())
        return annotated

    @classmethod
    def _existing_missing_signals(cls, row: dict[str, Any]) -> set[str]:
        tokens: set[str] = set()
        for field in SOURCE_FIELDS:
            tokens.update(cls._tokens(row.get(field)))
        return tokens.intersection(EXISTING_MISSING_INPUT_SIGNALS)

    @staticmethod
    def _tokens(value: Any) -> set[str]:
        if value is None or value == "":
            return set()
        if isinstance(value, (list, tuple, set)):
            return {str(item).strip() for item in value if str(item).strip()}
        if isinstance(value, dict):
            return {str(key).strip() for key, present in value.items() if present}
        text = str(value).strip()
        if not text:
            return set()
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, list):
                return {str(item).strip() for item in decoded if str(item).strip()}
        return {part.strip() for part in text.split(";") if part.strip()}

    @staticmethod
    def _bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
