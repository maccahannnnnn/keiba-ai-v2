"""Result-free A1/A2 development shadow; never changes a production class.

The existing prediction runner is called in a separate development process.
Only its adapter factory is temporarily rebound, and the binding is restored
even when prediction raises.  This module does not grant PRE or BUY authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MethodType

from evaluation.target_trial_adapter import TargetTrialAdapter
from review import target_bulk_prediction_input_shadow_v1 as raw_runner


SYNTHESIZED_MAJOR_TEXT = "重大リスクが複数"


@dataclass(frozen=True)
class GateFixConfig:
    a1_exact_major_dedup: bool = False
    a2_skip_synthesized_major_text: bool = False


def _a1_major_risks(self, risks):
    # Keep the production major-risk predicate, vocabulary and ordering.
    return self._unique(
        str(risk) for risk in self._list(risks) if self._is_major_risk(risk)
    )


def _a2_risks(self, horse):
    values = []
    for key in (
        "decision_risks", "final_risks", "risk_factors", "risk_reasons",
        "risk_summary", "warnings",
    ):
        for value in self._list(horse.get(key)):
            if not value:
                continue
            # DecisionEngine alone synthesizes this exact explanatory text.
            # Other risk fields and near-matching text retain their authority.
            if key == "decision_risks" and str(value) == SYNTHESIZED_MAJOR_TEXT:
                continue
            values.append(str(value))
    return self._unique(values)


def configure_adapter(adapter: TargetTrialAdapter, config: GateFixConfig) -> None:
    """Patch only this adapter's two decision objects, never module classes."""
    if config.a1_exact_major_dedup:
        adapter.decision_engine._major_risks = MethodType(
            _a1_major_risks, adapter.decision_engine
        )
    if config.a2_skip_synthesized_major_text:
        # RC1 uses its own shadow engine, not adapter.shadow_buy_decision_engine.
        shadow = adapter.buy_v1_rc1_engine.shadow_engine
        shadow._risks = MethodType(_a2_risks, shadow)


def run_race(race_id: str, race_bundle, config: GateFixConfig, *, trace=True):
    """Run one race with the existing Current computation and isolated fixes."""
    if not isinstance(config, GateFixConfig):
        raise TypeError("config must be GateFixConfig")
    if not (config.a1_exact_major_dedup or config.a2_skip_synthesized_major_text):
        return raw_runner.run_new(race_id, race_bundle, trace=trace)

    original = raw_runner.TargetTrialAdapter

    class BoundAdapter(TargetTrialAdapter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            configure_adapter(self, config)

    raw_runner.TargetTrialAdapter = BoundAdapter
    try:
        return raw_runner.run_new(race_id, race_bundle, trace=trace)
    finally:
        raw_runner.TargetTrialAdapter = original
