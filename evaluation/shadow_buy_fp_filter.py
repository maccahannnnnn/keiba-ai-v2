"""Shadow-only BUY false positive filter for BUY v1.0 RC1.

This module never changes production BUY, scores, decisions, thresholds, or
evaluator output.  It only annotates a copied shadow result for validation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ID = "SHADOW_BUY_FALSE_POSITIVE_RC1_V1"
VERSION = "shadow_buy_fp_filter_v1_0"
FEATURE_FLAG_NAME = "SHADOW_BUY_FP_FILTER_V1_ENABLED"

RESULT_DERIVED_FIELDS = {
    "finish_position",
    "actual_finish",
    "actual_top3",
    "actual_top5",
    "official_time",
    "result_margin",
    "last_3f_result",
    "result_passing_order",
    "top3_label",
    "success_label",
    "fp_label",
}


@dataclass(frozen=True)
class ShadowBuyFPFilterResult:
    production_buy: bool
    shadow_buy_fp_filter_v1: bool
    shadow_buy_rc1_v1: bool
    shadow_fp_filter_applied: bool
    shadow_fp_filter_rule_id: str = ""
    shadow_fp_filter_reason: str = ""
    shadow_fp_filter_evidence: dict[str, Any] = field(default_factory=dict)
    shadow_fp_filter_version: str = VERSION
    shadow_project_id: str = PROJECT_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_buy": self.production_buy,
            "shadow_buy_fp_filter_v1": self.shadow_buy_fp_filter_v1,
            "shadow_buy_rc1_v1": self.shadow_buy_rc1_v1,
            "shadow_fp_filter_applied": self.shadow_fp_filter_applied,
            "shadow_fp_filter_rule_id": self.shadow_fp_filter_rule_id,
            "shadow_fp_filter_reason": self.shadow_fp_filter_reason,
            "shadow_fp_filter_evidence": json.dumps(
                self.shadow_fp_filter_evidence, ensure_ascii=False, sort_keys=True
            ),
            "shadow_fp_filter_version": self.shadow_fp_filter_version,
            "shadow_project_id": self.shadow_project_id,
        }


class ShadowBuyFalsePositiveFilter:
    """Apply one selected shadow-only exclusion rule to RC1 BUY horses."""

    def __init__(self, enabled: bool | None = None, selected_rule: dict[str, Any] | None = None):
        self.enabled = self._env_enabled() if enabled is None else bool(enabled)
        self.selected_rule = selected_rule if selected_rule is not None else self._load_selected_rule()

    @staticmethod
    def _env_enabled() -> bool:
        return str(os.getenv(FEATURE_FLAG_NAME, "")).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _load_selected_rule() -> dict[str, Any]:
        root = Path(__file__).resolve().parents[1]
        path = root / "reports" / "shadow_buy_fp_filter" / "selected_rule.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def evaluate(self, row: dict[str, Any]) -> ShadowBuyFPFilterResult:
        production_buy = self._is_production_buy(row)
        if not self.enabled or not production_buy:
            return ShadowBuyFPFilterResult(
                production_buy=production_buy,
                shadow_buy_fp_filter_v1=False,
                shadow_buy_rc1_v1=production_buy,
                shadow_fp_filter_applied=False,
            )

        if not self._rule_is_active(self.selected_rule):
            return ShadowBuyFPFilterResult(
                production_buy=production_buy,
                shadow_buy_fp_filter_v1=False,
                shadow_buy_rc1_v1=production_buy,
                shadow_fp_filter_applied=False,
            )

        conditions = self.selected_rule.get("conditions", [])
        if len(conditions) > 2 or self._uses_result_fields(conditions):
            return ShadowBuyFPFilterResult(
                production_buy=production_buy,
                shadow_buy_fp_filter_v1=False,
                shadow_buy_rc1_v1=production_buy,
                shadow_fp_filter_applied=False,
            )

        matched = all(self._matches_condition(row, condition) for condition in conditions)
        evidence = {
            condition.get("field", ""): row.get(condition.get("field", ""), "")
            for condition in conditions
        }
        reason = self.selected_rule.get("reason", "")
        rule_id = self.selected_rule.get("rule_id", "") if matched else ""
        return ShadowBuyFPFilterResult(
            production_buy=production_buy,
            shadow_buy_fp_filter_v1=matched,
            shadow_buy_rc1_v1=production_buy and not matched,
            shadow_fp_filter_applied=matched,
            shadow_fp_filter_rule_id=rule_id,
            shadow_fp_filter_reason=reason if matched else "",
            shadow_fp_filter_evidence=evidence if matched else {},
        )

    def annotate(self, row: dict[str, Any]) -> dict[str, Any]:
        annotated = dict(row)
        annotated.update(self.evaluate(row).to_dict())
        return annotated

    @staticmethod
    def _rule_is_active(rule: dict[str, Any]) -> bool:
        return rule.get("status") in {"SELECTED_SHADOW_ONLY", "ACTIVE_SHADOW_ONLY"}

    @staticmethod
    def _uses_result_fields(conditions: list[dict[str, Any]]) -> bool:
        return any(condition.get("field") in RESULT_DERIVED_FIELDS for condition in conditions)

    @staticmethod
    def _is_production_buy(row: dict[str, Any]) -> bool:
        if str(row.get("rc1_status", "")).upper() == "RC1_BUY":
            return True
        if str(row.get("rc1_decision", "")).upper() == "BUY":
            return True
        return str(row.get("production_buy", "")).strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def _matches_condition(row: dict[str, Any], condition: dict[str, Any]) -> bool:
        field = condition.get("field", "")
        op = condition.get("op", "==")
        expected = condition.get("value")
        actual = row.get(field, "")
        actual_value = ShadowBuyFalsePositiveFilter._coerce(actual)
        expected_value = ShadowBuyFalsePositiveFilter._coerce(expected)
        if op == "==":
            return actual_value == expected_value
        if op == "!=":
            return actual_value != expected_value
        if op == ">=":
            return actual_value >= expected_value
        if op == ">":
            return actual_value > expected_value
        if op == "<=":
            return actual_value <= expected_value
        if op == "<":
            return actual_value < expected_value
        return False

    @staticmethod
    def _coerce(value: Any) -> Any:
        if isinstance(value, bool) or value is None:
            return value
        text = str(value).strip()
        if text.lower() == "true":
            return True
        if text.lower() == "false":
            return False
        try:
            if "." in text:
                return float(text)
            return int(text)
        except ValueError:
            return text
