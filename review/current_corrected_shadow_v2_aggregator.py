"""Permanent field-separated aggregation for CURRENT_CORRECTED_SHADOW_V2."""
from __future__ import annotations
from typing import Any
def selections(rows:list[dict[str,Any]], side:str)->list[dict[str,Any]]:
    if side=="current": return [r for r in rows if r.get("buy_v1_rc1_buy") is True]
    if side=="corrected": return [r for r in rows if isinstance(r.get("corrected_shadow"),dict) and r["corrected_shadow"].get("buy") is True]
    raise ValueError("side must be current or corrected")
def ranks(rows:list[dict[str,Any]], side:str)->list[int]:
    if side=="current": return [int(r["rank"]) for r in rows]
    return [int(r["corrected_shadow"]["rank"]) for r in rows]
