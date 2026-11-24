"""Cumulative, shadow-only decision gate for Daily V5 same-volume evidence."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/daily_v5_same_volume_prospective_protocol_v1.json"


def evaluate(post_summaries: list[dict]) -> dict:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    start = protocol["evidence_start"].replace("-", "")
    if any(item["date"].replace("-", "") < start for item in post_summaries):
        raise RuntimeError("STOP_EVIDENCE_START_BOUNDARY")
    minimum = protocol["minimum_evidence"]
    current = {"valid": 0, "hits": 0}
    daily = {"valid": 0, "hits": 0}
    blocks: dict[str, list[dict]] = {}
    for item in post_summaries:
        blocks.setdefault(item.get("block", item["date"].replace("-", "")[:6]), []).append(item)
        for name, target in (("current", current), ("daily_v5", daily)):
            metrics = item["combined"][name]
            target["valid"] += metrics["valid_selected_count"]
            target["hits"] += metrics["top3_count"]
    races = sum(item.get("eligible_selected_races", 0) for item in post_summaries)
    current_rate = current["hits"] / current["valid"] if current["valid"] else None
    daily_rate = daily["hits"] / daily["valid"] if daily["valid"] else None
    ready = len(post_summaries) >= minimum["dates"] and len(blocks) >= minimum["independent_blocks"] and races >= minimum["selected_races"]
    if not ready:
        decision = "HOLD"
    elif daily_rate >= current_rate and daily["hits"] >= current["hits"]:
        nonnegative_blocks = 0
        for entries in blocks.values():
            c_valid = sum(x["combined"]["current"]["valid_selected_count"] for x in entries)
            d_valid = sum(x["combined"]["daily_v5"]["valid_selected_count"] for x in entries)
            if c_valid and d_valid:
                c_rate = sum(x["combined"]["current"]["top3_count"] for x in entries) / c_valid
                d_rate = sum(x["combined"]["daily_v5"]["top3_count"] for x in entries) / d_valid
                nonnegative_blocks += d_rate >= c_rate
        decision = "ACCEPT_CANDIDATE" if nonnegative_blocks >= 2 else "HOLD_EXTEND"
    elif daily_rate < current_rate and daily["hits"] <= current["hits"]:
        decision = "REJECT"
    else:
        decision = "HOLD_EXTEND"
    return {"status": "SUCCESS", "decision": decision, "production_authorization": False, "evidence_start": start,
            "dates": len(post_summaries), "blocks": len(blocks), "selected_races": races,
            "current": {**current, "rate": current_rate}, "daily_v5": {**daily, "rate": daily_rate}}
