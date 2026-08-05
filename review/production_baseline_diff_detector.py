"""Read-only comparison of saved production snapshots against a frozen baseline."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

CLASSES = ("NO_CHANGE", "BUY_SET_CHANGED", "DECISION_CHANGED", "SCORE_CHANGED_ONLY",
           "SOURCE_CHANGED", "RACE_SET_CHANGED", "HORSE_SET_CHANGED",
           "TRACE_INCOMPATIBLE", "UNDETERMINED")
SCORE_FIELDS = ("final_score", "adjusted_score", "decision_score")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def stable_hash(rows: Iterable[dict[str, Any]], fields: tuple[str, ...]) -> str:
    values = [[str(row.get(field, "")).strip() for field in fields] for row in rows]
    payload = json.dumps(sorted(values), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _horse_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("race_id", "")), str(row.get("horse_number", ""))

def _value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return ""


def compare(baseline_races: list[dict[str, Any]], baseline_horses: list[dict[str, Any]],
            current_races: list[dict[str, Any]], current_horses: list[dict[str, Any]],
            *, source_compatible: bool = True, trace_compatible: bool = True) -> dict[str, Any]:
    differences: list[str] = []
    br, cr = {str(x.get("race_id")) for x in baseline_races}, {str(x.get("race_id")) for x in current_races}
    bh, ch = {_horse_key(x) for x in baseline_horses}, {_horse_key(x) for x in current_horses}
    if br != cr: differences.append("RACE_SET_CHANGED")
    if bh != ch: differences.append("HORSE_SET_CHANGED")
    if not trace_compatible: differences.append("TRACE_INCOMPATIBLE")
    if not source_compatible: differences.append("SOURCE_CHANGED")

    common_r = br & cr
    rb = {str(x.get("race_id")): x for x in baseline_races}; rc = {str(x.get("race_id")): x for x in current_races}
    if any((_value(rb[k],"race_decision","RaceDecision"), _value(rb[k],"race_state","RaceState"), _value(rb[k],"confidence","Confidence")) !=
           (_value(rc[k],"race_decision","RaceDecision"), _value(rc[k],"race_state","RaceState"), _value(rc[k],"confidence","Confidence")) for k in common_r):
        differences.append("DECISION_CHANGED")
    hb = {_horse_key(x): x for x in baseline_horses}; hc = {_horse_key(x): x for x in current_horses}
    common_h = bh & ch
    buy_b = {k for k in bh if str(hb[k].get("buy_flag", hb[k].get("decision", ""))).upper() in ("1", "TRUE", "BUY")}
    buy_c = {k for k in ch if str(hc[k].get("buy_flag", hc[k].get("decision", ""))).upper() in ("1", "TRUE", "BUY")}
    if buy_b != buy_c: differences.append("BUY_SET_CHANGED")
    if any(any(str(hb[k].get(f, "")) != str(hc[k].get(f, "")) for f in SCORE_FIELDS) for k in common_h):
        differences.append("SCORE_CHANGED_ONLY")

    precedence = ("TRACE_INCOMPATIBLE", "RACE_SET_CHANGED", "HORSE_SET_CHANGED", "SOURCE_CHANGED",
                  "BUY_SET_CHANGED", "DECISION_CHANGED", "SCORE_CHANGED_ONLY")
    ordered = [x for x in precedence if x in differences]
    primary = ordered[0] if ordered else "NO_CHANGE"
    trigger = "BASELINE_INCOMPATIBLE" if primary in ("TRACE_INCOMPATIBLE", "RACE_SET_CHANGED", "HORSE_SET_CHANGED") else (
        "REMEASUREMENT_GO" if primary in ("BUY_SET_CHANGED", "DECISION_CHANGED") else "REMEASUREMENT_WAIT")
    return {"primary_difference": primary, "secondary_differences": ordered[1:],
            "all_differences": ordered or ["NO_CHANGE"], "remeasurement_judgment": trigger}


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--baseline-race", type=Path, required=True)
    p.add_argument("--baseline-horse", type=Path, required=True); p.add_argument("--current-race", type=Path, required=True)
    p.add_argument("--current-horse", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = compare(read_csv(args.baseline_race), read_csv(args.baseline_horse),
                     read_csv(args.current_race), read_csv(args.current_horse))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__": raise SystemExit(main())
