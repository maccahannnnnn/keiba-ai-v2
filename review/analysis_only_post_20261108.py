"""Read-only selection join for the 2026-11-08 ANALYSIS_ONLY six-lane packet."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome, parse_race_id
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "reports/20261108_analysis_only_v1"
OUT = ROOT / "reports/20261108_analysis_only_post_v1"
DATE = "20261108"
LANES = ("Current", "EXP-024", "Current Rank1", "Independent V5", "PL+Jockey", "E1")
RANK1_REPORTED = (("fukushima", 11, 5), ("kyoto", 10, 2), ("tokyo", 10, 3), ("tokyo", 7, 7))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def key(race_id: str, number: int):
    return race_id, int(number)


def metrics(keys: set, joined: dict):
    rows = [joined[k] for k in keys]
    valid = [r for r in rows if r["valid_result"]]
    by_finish = Counter(r["finish"] for r in valid)
    hits = sum(r["actual_top3"] for r in valid)
    return {"selected_n": len(rows), "valid_n": len(valid), "invalid_n": len(rows) - len(valid),
            "first": by_finish[1], "second": by_finish[2], "third": by_finish[3],
            "top3_hits": hits, "top3_rate": hits / len(valid) if valid else None,
            "win_rate": by_finish[1] / len(valid) if valid else None}


def main():
    if OUT.exists():
        raise RuntimeError("STOP_OUTPUT_EXISTS")
    primary = ROOT / f"data/raw/target/daily_result_list/馬番順着順_{DATE}.csv"
    auxiliary = ROOT / f"data/raw/target/daily_result_list/着順馬番_{DATE}.csv"
    validation = validate_source_pair(primary, auxiliary, DATE)
    p = {(r[1], int(r[2])): r for r in csv.reader(primary.open(encoding="cp932", newline=""))}
    a = {(r[1], int(r[2])): r for r in csv.reader(auxiliary.open(encoding="cp932", newline=""))}
    if set(p) != set(a) or len(p) != 36 or sum(int(r[9]) for r in p.values()) != 497:
        raise RuntimeError("STOP_RESULT_POPULATION")
    ties = []
    for race, row in p.items():
        other = a[race]
        n = int(row[9])
        if row[:12] != other[:12]:
            raise RuntimeError("STOP_RESULT_RACE_METADATA")
        order = [int(v) for v in other[12:12+n]]
        if set(order) != set(range(1, n+1)):
            raise RuntimeError("STOP_RESULT_HORSE_SET")
        seen_valid = []
        for place, number in enumerate(order, 1):
            valid, finish, _ = outcome(row, number)
            if valid:
                seen_valid.append(finish)
                if finish != place:
                    ties.append({"venue": race[0], "race_number": race[1], "horse_number": number,
                                 "display_position": place, "actual_finish": finish})
        if seen_valid != sorted(seen_valid):
            raise RuntimeError("STOP_RESULT_ORDER_RECONCILIATION")

    current_root = PRE / "current"
    cm = load(current_root / "prediction_manifest.json")
    for item in cm["files"]:
        if sha(current_root / item["relative_path"]) != item["sha256"]:
            raise RuntimeError("STOP_CURRENT_PRE_SHA")
    if load(current_root / "provenance.json").get("result_data_access_count") != 0:
        raise RuntimeError("STOP_PRE_RESULT_ACCESS")
    index = load(current_root / "race_index.json")["race_index"]
    payloads = [load(current_root / item["artifact"]) for item in index]
    if len(payloads) != 21 or sum(len(x["ranked_results"]) for x in payloads) != 300:
        raise RuntimeError("STOP_PRE_POPULATION")
    names = {key(r["race_id"], h["horse_number"]): h["horse_name"] for r in payloads for h in r["ranked_results"]}
    if len(names) != 300:
        raise RuntimeError("STOP_PRE_DUPLICATE_HORSE")
    current = {key(r["race_id"], h["horse_number"]) for r in payloads for h in r["buys"]}
    ind_art = PRE / "independent_v5_retry1/selection_manifest.json"
    ind = load(ind_art)
    if ind.get("date") != DATE or ind.get("result_data_access_count") != 0:
        raise RuntimeError("STOP_INDEPENDENT_PRE")
    independent = {key(r["race_id"], h["horse_number"]) for r in ind["races"] for h in r["selected_horses"]}
    plj_art = PRE / "pl_jockey_analysis_only.json"
    plj = load(plj_art)
    if plj.get("date") != DATE or plj.get("role") != "ANALYSIS_ONLY" or plj.get("result_access_count") != 0:
        raise RuntimeError("STOP_PLJ_PRE")
    jockey = {key(r["race_id"], n) for r in plj["races"] for n in r["candidate_selected_horses"]}
    e1_art = PRE / "e1_analysis_only.json"
    e1 = load(e1_art)
    if e1.get("date") != DATE or e1.get("role") != "ANALYSIS_ONLY" or e1.get("result_access_count") != 0:
        raise RuntimeError("STOP_E1_PRE")
    e1_keys = {key(h["race_id"], h["horse_number"]) for h in e1["selected"]}
    exp024 = {key(h["race_id"], h["horse_number"]) for h in e1["comparator"]}
    rank1 = {key(f"race_{DATE}_{venue}_{number}R", horse) for venue, number, horse in RANK1_REPORTED}
    selections = dict(zip(LANES, (current, exp024, rank1, independent, jockey, e1_keys)))
    expected_counts = (20, 20, 4, 14, 20, 20)
    if tuple(map(len, selections.values())) != expected_counts or any(not s <= names.keys() for s in selections.values()):
        raise RuntimeError("STOP_PRE_SELECTION_SET")
    if len(e1["comparator"]) != 20 or len(e1["selected"]) != 20:
        raise RuntimeError("STOP_E1_COMPARATOR_COUNT")
    # Rank1 has no independent saved PRE selection file; check the four prior-chat identities
    # against Current's frozen race state and stored rank, without selecting anything anew.
    for race_id, number in rank1:
        race = next(r for r in payloads if r["race_id"] == race_id)
        horse = next(h for h in race["ranked_results"] if int(h["horse_number"]) == number)
        if int(race["buy_count"]) != 0 or int(horse["rank"]) != 1:
            raise RuntimeError("STOP_RANK1_REPORTED_IDENTITY")

    joined = {}
    for race_id, number in names:
        d, venue, race_number = parse_race_id(race_id)
        if d != DATE or (JAPANESE_VENUE[venue], race_number) not in p:
            raise RuntimeError("STOP_RESULT_RACE_MISSING")
        row = p[JAPANESE_VENUE[venue], race_number]
        race = next(r for r in index if r["race_id"] == race_id)
        if int(row[9]) != int(race["horse_count"]):
            raise RuntimeError("STOP_RESULT_HEADCOUNT")
        valid, finish, top3 = outcome(row, number)
        joined[race_id, number] = {"race_id": race_id, "venue": JAPANESE_VENUE[venue],
                                   "race_number": race_number, "horse_number": number,
                                   "horse_name": names[race_id, number], "finish": finish,
                                   "finish_raw": row[11+number].strip(), "valid_result": valid,
                                   "actual_top3": bool(top3) if valid else None}

    union = set().union(*selections.values())
    selected = [{**joined[k], "selecting_lanes": [lane for lane in LANES if k in selections[lane]],
                 "support_count": sum(k in s for s in selections.values())} for k in sorted(union)]
    groups = {str(n): {k for k in union if sum(k in s for s in selections.values()) == n} for n in range(1, 7)}
    pairs = (("Current", "Independent V5"), ("Current Rank1", "Independent V5"),
             ("EXP-024", "PL+Jockey"), ("EXP-024", "E1"), ("E1", "PL+Jockey"), ("Current", "E1"))
    pair_stats = [{"lanes": list(pair), **metrics(selections[pair[0]] & selections[pair[1]], joined)} for pair in pairs]
    buy_races = {rid for rid, _ in current}
    e1_nonbuy = {k for k in e1_keys if k[0] not in buy_races}
    e1_buy = e1_keys - e1_nonbuy
    other_current_misses = [r for r in selected if (r["race_id"], r["horse_number"]) not in current and r["actual_top3"]]
    data = {"date": DATE, "role": "POST_RESULT_ANALYSIS_ONLY_DIAGNOSTIC", "formal_evidence": False,
            "result_source": {"primary": str(primary.relative_to(ROOT)), "primary_sha256": sha(primary),
                              "auxiliary": str(auxiliary.relative_to(ROOT)), "auxiliary_sha256": sha(auxiliary),
                              "total_races": len(p), "total_horses": 497, "pre_scope_races": 21,
                              "pre_scope_horses": len(joined), "source_pair_validation": validation["status"],
                              "ordered_result_tie_offsets": ties},
            "pre_source_sha256": {"current_prediction_manifest": sha(current_root / "prediction_manifest.json"),
                                   "independent_selection_manifest": sha(ind_art),
                                   "pl_jockey_analysis": sha(plj_art), "e1_analysis": sha(e1_art)},
            "selection_authority": {"Current": "SAVED_CURRENT_PRE", "EXP-024": "SAVED_E1_ANALYSIS_COMPARATOR",
                                    "Current Rank1": "PRIOR_CHAT_REPORT_ONLY_CROSSCHECKED_CURRENT_RANK1",
                                    "Independent V5": "SAVED_INDEPENDENT_PRE", "PL+Jockey": "SAVED_ANALYSIS_PRE",
                                    "E1": "SAVED_ANALYSIS_PRE"},
            "lane_metrics": {lane: metrics(keys, joined) for lane, keys in selections.items()},
            "support_metrics": {n: metrics(keys, joined) for n, keys in groups.items()},
            "selected_horses": selected, "pair_metrics": pair_stats,
            "e1_jockey": {"both": metrics(e1_keys & jockey, joined),
                           "e1_without_jockey": metrics(e1_keys - jockey, joined),
                           "jockey_without_e1": metrics(jockey - e1_keys, joined)},
            "e1_by_current_race": {"current_buy_race": metrics(e1_buy, joined),
                                   "current_nonbuy_race": metrics(e1_nonbuy, joined),
                                   "current_nonbuy_races": sorted({rid for rid, _ in e1_nonbuy}),
                                   "current_nonbuy_horses": [joined[k] for k in sorted(e1_nonbuy)]},
            "other_ai_top3_outside_current": other_current_misses,
            "pre_analysis_execution_time_jst": plj.get("analysis_execution_time_jst"),
            "post_execution_time_jst": datetime.now(timezone(timedelta(hours=9))).isoformat(),
            "new_buy_rule_created": False, "training_executed": False, "git_operation": False}
    OUT.mkdir(parents=True)
    (OUT / "diagnostic.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (OUT / "selected_horses.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ("venue", "race_number", "horse_number", "horse_name", "selecting_lanes", "support_count", "finish_raw", "valid_result", "actual_top3")
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            writer.writerow({name: ",".join(row[name]) if name == "selecting_lanes" else row[name] for name in fields})
    hashes = {p.name: sha(p) for p in (OUT / "diagnostic.json", OUT / "selected_horses.csv")}
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": data["result_source"], "lane_metrics": data["lane_metrics"],
                      "support_metrics": data["support_metrics"], "e1_jockey": data["e1_jockey"],
                      "e1_by_current_race": {k:v for k,v in data["e1_by_current_race"].items() if k != "current_nonbuy_horses"},
                      "union_n": len(selected), "other_current_miss_top3": len(other_current_misses),
                      "hashes": hashes}, ensure_ascii=True))


if __name__ == "__main__":
    main()
