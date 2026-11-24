"""Deprecated compatibility facade; it is not a Formal state writer.

Stage 1 replaces this retry-era registry with ``prospective_state_v1``.  The
write methods deliberately fail closed so an old import cannot start or alter
a Formal date attempt.
"""
from __future__ import annotations

from pathlib import Path

from review.current_corrected_shadow_v2_prospective_protocol_v1 import ROOT, Stop
from review.current_corrected_shadow_v2_prospective_state_v1 import StateReader


BASE = ROOT / "reports" / "current_corrected_shadow_v2_prospective_state_v1"


def state(date: str, *, registry_root: Path | None = None) -> str:
    return StateReader(registry_root or BASE).get_date_state(date)


def claim(*_args, **_kwargs):
    raise Stop("STOP_LEGACY_DATE_REGISTRY_DISABLED")


def complete(*_args, **_kwargs):
    raise Stop("STOP_LEGACY_DATE_REGISTRY_DISABLED")


def emergency(*_args, **_kwargs):
    raise Stop("STOP_LEGACY_DATE_REGISTRY_DISABLED")
