"""Additive PL+J Step 1 operations. No model, prediction, or Result reader."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from review.pl_jockey_decision_addendum_v1 import (
    decision, global_allocation, overlap_class, smallest_field_first,
)


FREEZE_DATE = "2026-11-03"
BLOCKED_DATES = {"2026-10-31", "2026-11-01"}
JST = timezone(timedelta(hours=9))
TERMINAL = {"ACCEPT", "REJECT", "INCONCLUSIVE_CLOSE", "PARENT_SUSPEND_HUMAN_REVIEW"}


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_date(date: str) -> str:
    text = str(date)
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return datetime.strptime(text, "%Y-%m-%d").date().isoformat()


def eligible_races_from_pre(races: list[dict], current_buy_counts: dict[str, int]) -> tuple[int, int]:
    seen = set()
    positive = 0
    slots = 0
    if {str(r["race_id"]) for r in races} != set(current_buy_counts):
        raise ValueError("STOP_PLJ_CURRENT_RACE_SET_MISMATCH")
    for row in races:
        race = str(row["race_id"])
        if race in seen:
            raise ValueError("STOP_DUPLICATE_PLJ_RACE")
        seen.add(race)
        k = int(row["current_k"])
        if k < 0 or int(row["candidate_k"]) != k or int(current_buy_counts[race]) != k:
            raise ValueError("STOP_PLJ_CURRENT_K_MISMATCH")
        if len(row["candidate_selected_horses"]) != k or len(row["current_selected_horses"]) != k:
            raise ValueError("STOP_PLJ_CURRENT_SLOT_MISMATCH")
        if k > 0:
            positive += 1
            slots += k
    return positive, slots


def credit_class(date: str, role: str, *, freeze_date: str = FREEZE_DATE,
                 pre_frozen_before_result: bool = False) -> str:
    date = normalize_date(date)
    freeze_date = normalize_date(freeze_date)
    if date in BLOCKED_DATES:
        return "PRE_ADDENDUM_OBSERVATION"
    if (date <= freeze_date or role != "PROSPECTIVE_ELIGIBLE" or
            not pre_frozen_before_result):
        return "REFERENCE_ONLY"
    return "FORMAL_NEW_GATE_ELIGIBLE"


def advance_state(state: dict, day: dict, *, freeze_date: str = FREEZE_DATE,
                  bootstrap_ci: tuple[float, float] | None = None) -> dict:
    """Return a new state. Caller supplies POST counts after a verified frozen PRE join."""
    result = json.loads(json.dumps(state))
    day = dict(day)
    day["date"] = normalize_date(day["date"])
    classification = credit_class(day["date"], day["role"], freeze_date=freeze_date,
                                  pre_frozen_before_result=day["pre_frozen_before_result"])
    result["last_input_classification"] = classification
    if classification != "FORMAL_NEW_GATE_ELIGIBLE" or result.get("terminal_status") in TERMINAL:
        return result
    if day.get("parent_suspended"):
        result["terminal_status"] = "PARENT_SUSPEND_HUMAN_REVIEW"
        result["WORKSTREAM_STATE"] = "PARENT_SUSPEND_HUMAN_REVIEW"
        return result
    if day.get("result_join_verified") is not True:
        raise ValueError("STOP_RESULT_JOIN_NOT_VERIFIED")
    days = result.setdefault("formal_days", [])
    if any(existing["date"] == day["date"] for existing in days):
        raise ValueError("STOP_DUPLICATE_FORMAL_GATE_DATE")
    races, slots = eligible_races_from_pre(day["pre_races"], day["current_buy_counts"])
    if slots != int(day["plj_slots"]) or slots != int(day["current_slots"]):
        raise ValueError("STOP_GATE_SLOT_TOTAL_MISMATCH")
    if day["plj_valid_hits"] > day["plj_valid_n"] or day["plj_valid_n"] > slots:
        raise ValueError("STOP_GATE_VALID_COUNT_MISMATCH")
    compact = {key: day[key] for key in ("date", "plj_slots", "current_slots", "delta_hits",
                                         "plj_valid_n", "plj_valid_hits")}
    compact.update(eligible_races=races, same_race=True, same_k=True, same_volume=True)
    days.append(compact)
    days.sort(key=lambda d: d["date"])
    dates = len(days)
    total_races = sum(d["eligible_races"] for d in days)
    result["formal_evidence_dates"] = dates
    result["formal_evidence_races"] = total_races
    if not result.get("first_checkpoint_decided", False) and dates >= 12 and total_races >= 60:
        outcome = decision(days, bootstrap_ci=bootstrap_ci)
        result["first_checkpoint_decided"] = True
        result["FIRST_CHECKPOINT_DECIDED"] = "YES"
        result["first_checkpoint_date"] = day["date"]
        result["first_checkpoint_outcome"] = outcome["status"]
        if outcome["status"] == "ACCEPT":
            result["terminal_status"] = "ACCEPT"
            result["WORKSTREAM_STATE"] = "ACCEPT"
    if (not result.get("final_checkpoint_decided", False) and not result.get("terminal_status")
            and dates >= 24 and total_races >= 120):
        outcome = decision(days, bootstrap_ci=bootstrap_ci)
        result["final_checkpoint_decided"] = True
        result["FINAL_CHECKPOINT_DECIDED"] = "YES"
        result["final_checkpoint_date"] = day["date"]
        result["terminal_status"] = outcome["status"]
        result["WORKSTREAM_STATE"] = outcome["status"]
    return result


def same_scorer_smallest_field(pre_rows: list[dict], daily_n: int, *, scorer: str) -> list[dict]:
    if scorer not in {"pl_probability", "plj_p_top3"}:
        raise ValueError("STOP_UNAPPROVED_SCORER")
    if any(row.get(scorer) is None or int(row["field_size"]) <= 0 for row in pre_rows):
        raise ValueError("NOT_EVALUABLE_MISSING_PRE_SCORE_OR_FIELD")
    ranked = sorted(pre_rows, key=lambda r: (int(r["field_size"]), str(r["race_id"]),
                                              -float(r[scorer]), int(r["horse_number"])))
    result, counts = [], {}
    for row in ranked:
        race = str(row["race_id"])
        if counts.get(race, 0) < 3 and len(result) < daily_n:
            result.append(row)
            counts[race] = counts.get(race, 0) + 1
    if len(result) != daily_n:
        raise ValueError("NOT_EVALUABLE_INSUFFICIENT_PRE_CAPACITY")
    return result


def _keys(rows: list[dict]) -> list[dict]:
    return [{"race_id": r["race_id"], "horse_number": int(r["horse_number"]),
             "horse_name": r.get("horse_name"), "field_size": int(r["field_size"])} for r in rows]


def derive_pre(plj: dict, e1: dict, *, current_buy_counts: dict[str, int]) -> dict:
    """Build five PRE-only membership sets from *existing* frozen outputs."""
    if plj["date"] != e1["date"] or plj.get("result_access_count") != 0 or e1.get("result_access_count_at_pre_freeze") != 0:
        raise ValueError("STOP_PRE_AUTHORITY_OR_RESULT_ACCESS")
    if (plj.get("role") != "PROVISIONAL_PRIMARY_OPERATIONAL_CANDIDATE_PRE_ONLY" or
            plj.get("semantic_validation_result") != "PASS" or
            e1.get("role") != "PROSPECTIVE_SHADOW_PRE_ONLY" or
            e1.get("cap3_status") != "PASS" or
            e1.get("three_way_n_identity", {}).get("status") != "PASS"):
        raise ValueError("STOP_FROZEN_PRE_SEMANTIC_AUTHORITY")
    races, slots = eligible_races_from_pre(plj["races"], current_buy_counts)
    if slots != int(e1["daily_n"]):
        raise ValueError("STOP_CURRENT_DAILY_N_MISMATCH")
    e1_full = e1["frozen_probabilities_consumed"]
    plj_full = []
    selected_plj = set()
    for race in plj["races"]:
        field = len(race["horses"])
        for horse in race["horses"]:
            plj_full.append({"race_id": race["race_id"], "horse_number": int(horse["horse_number"]),
                             "horse_name": horse["horse_name"], "field_size": field,
                             "plj_p_top3": horse["candidate_p_top3"]})
        selected_plj.update((race["race_id"], int(h)) for h in race["candidate_selected_horses"])
    e1_rows = [{"race_id": r["race_id"], "horse_number": int(r["horse_number"]),
                "horse_name": r["horse_name"], "field_size": int(r["field_size"]),
                "pl_probability": r["pl_probability"]} for r in e1_full]
    if {(r["race_id"], r["horse_number"]) for r in e1_rows} != {(r["race_id"], r["horse_number"]) for r in plj_full}:
        raise ValueError("STOP_PRE_FULL_FIELD_UNIVERSE_MISMATCH")
    e1_selected = {(r["race_id"], int(r["horse_number"])) for r in e1["selected_horses"]}
    if len(e1_selected) != slots or len(selected_plj) != slots:
        raise ValueError("STOP_FROZEN_PRE_SELECTION_VOLUME")
    partitions = overlap_class(selected_plj, e1_selected)
    return {"date": plj["date"], "daily_n": slots, "eligible_race_count": races,
            "formal_evidence_credit": 0,
            "field_size_pre_inventory": {
                "PL_JOCKEY": _keys([r for r in plj_full if (r["race_id"], r["horse_number"]) in selected_plj]),
                "E1": _keys([r for r in e1_rows if (r["race_id"], r["horse_number"]) in e1_selected]),
                "CURRENT": _keys([r for race in plj["races"] for r in plj_full
                                  if r["race_id"] == race["race_id"] and
                                  r["horse_number"] in {int(h) for h in race["current_selected_horses"]}]),
            },
            "simple_smallest_field_first": _keys(smallest_field_first(e1_rows, slots)),
            "smallest_field_first_same_scorer_e1": _keys(same_scorer_smallest_field(e1_rows, slots, scorer="pl_probability")),
            "smallest_field_first_same_scorer_plj": _keys(same_scorer_smallest_field(plj_full, slots, scorer="plj_p_top3")),
            "pl_jockey_e1_overlap": {k: [{"race_id": race, "horse_number": horse} for race, horse in sorted(v)]
                                      for k, v in partitions.items()},
            "pl_jockey_global_rank_diagnostic": _keys(global_allocation(plj_full, slots))}


def freeze_pre(*, plj_path: Path, e1_path: Path, current_manifest_path: Path,
               current_buy_counts: dict[str, int], first_start_at: str, output_path: Path,
               now: datetime | None = None) -> dict:
    """Freeze a future PRE diagnostic. No Result lookup, even an existence check."""
    now = now or datetime.now(JST)
    first = datetime.fromisoformat(first_start_at)
    if first.tzinfo is None or now >= first or now.date().isoformat() > first.date().isoformat():
        raise ValueError("NOT_EVALUABLE_PRE_NOT_FROZEN")
    if plj_path.name != "selection.json" or e1_path.name != "selection.json" or current_manifest_path.name != "prediction_manifest.json":
        raise ValueError("STOP_UNEXPECTED_PRE_AUTHORITY_PATH")
    plj = json.loads(plj_path.read_text(encoding="utf-8"))
    e1 = json.loads(e1_path.read_text(encoding="utf-8"))
    if sha(current_manifest_path) != plj["current_pre_sha256"] or sha(current_manifest_path) != e1["current_formal_pre_sha256"]:
        raise ValueError("STOP_CURRENT_AUTHORITY_SHA_MISMATCH")
    derived = derive_pre(plj, e1, current_buy_counts=current_buy_counts)
    if normalize_date(derived["date"]) <= FREEZE_DATE:
        raise ValueError("NOT_EVALUABLE_PRE_NOT_FROZEN")
    selection_sha = hashlib.sha256(canonical(derived)).hexdigest()
    payload = {"status": "FROZEN_PRE_DERIVATION", "target_date": derived["date"],
               "created_at_jst": now.astimezone(JST).isoformat(), "first_start_at": first_start_at,
               "input_pre_sha256": {"current": sha(current_manifest_path), "pl_jockey": sha(plj_path), "e1": sha(e1_path)},
               "daily_n": derived["daily_n"], "eligible_race_count": derived["eligible_race_count"],
               "selection_membership_sha256": selection_sha, "result_access": 0,
               "formal_evidence_credit": 0, "derived": derived}
    if output_path.exists():
        raise ValueError("STOP_PRE_DERIVATION_ALREADY_EXISTS")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical(payload) + b"\n")
    return payload


def write_next_gate_state(*, previous_state_path: Path | None, verified_day_path: Path,
                          output_path: Path) -> dict:
    """Append one verified POST day to an immutable next-state artifact."""
    if output_path.exists():
        raise ValueError("STOP_GATE_STATE_ALREADY_EXISTS")
    previous = json.loads(previous_state_path.read_text(encoding="utf-8")) if previous_state_path else {}
    day = json.loads(verified_day_path.read_text(encoding="utf-8"))
    next_state = advance_state(previous, day)
    next_state["previous_state_sha256"] = sha(previous_state_path) if previous_state_path else None
    next_state["verified_day_sha256"] = sha(verified_day_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical(next_state) + b"\n")
    return next_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze future PL+J derived PRE diagnostic only")
    parser.add_argument("--mode", choices=("freeze-pre", "advance-state"), required=True)
    parser.add_argument("--plj-pre", type=Path)
    parser.add_argument("--e1-pre", type=Path)
    parser.add_argument("--current-manifest", type=Path)
    parser.add_argument("--current-race-index", type=Path)
    parser.add_argument("--first-start-at")
    parser.add_argument("--previous-state", type=Path)
    parser.add_argument("--verified-day", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "advance-state":
        if args.verified_day is None:
            raise ValueError("STOP_VERIFIED_DAY_REQUIRED")
        next_state = write_next_gate_state(previous_state_path=args.previous_state,
                                          verified_day_path=args.verified_day,
                                          output_path=args.output)
        print(json.dumps({k: next_state.get(k) for k in ("formal_evidence_dates", "formal_evidence_races",
                                                         "first_checkpoint_decided", "final_checkpoint_decided", "terminal_status")}, ensure_ascii=False))
        return
    if not all((args.plj_pre, args.e1_pre, args.current_manifest, args.current_race_index, args.first_start_at)):
        raise ValueError("STOP_PRE_DERIVATION_ARGUMENT_MISSING")
    index = json.loads(args.current_race_index.read_text(encoding="utf-8"))
    manifest = json.loads(args.current_manifest.read_text(encoding="utf-8"))
    listed = {r["relative_path"]: r["sha256"] for r in manifest.get("files", [])}
    if (args.current_race_index.parent.resolve() != args.current_manifest.parent.resolve() or
            listed.get(args.current_race_index.name) != sha(args.current_race_index)):
        raise ValueError("STOP_CURRENT_RACE_INDEX_SHA_MISMATCH")
    index = index.get("race_index") if isinstance(index, dict) else index
    if not isinstance(index, list):
        raise ValueError("STOP_CURRENT_RACE_INDEX_SCHEMA")
    counts = {str(row["race_id"]): int(row["buy_count"]) for row in index}
    if len(counts) != len(index):
        raise ValueError("STOP_DUPLICATE_CURRENT_RACE_INDEX")
    result = freeze_pre(plj_path=args.plj_pre, e1_path=args.e1_pre,
                        current_manifest_path=args.current_manifest,
                        current_buy_counts=counts, first_start_at=args.first_start_at,
                        output_path=args.output)
    print(json.dumps({k: result[k] for k in ("status", "target_date", "daily_n", "eligible_race_count", "selection_membership_sha256", "result_access")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
