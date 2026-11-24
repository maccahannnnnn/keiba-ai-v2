"""Read-only BUY selection precision analysis using frozen prediction artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "buy_precision_v1"
TOP5 = ROOT / "reports" / "failed_buy_root_cause_v1" / "top5_result_export.csv"
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
BLOCKS = {
    "JUNE_BLOCK_1": ("20260620", "20260621", "20260627", "20260628"),
    "JULY_H1": ("20260704", "20260705", "20260711", "20260712"),
    "JULY_H2": ("20260718", "20260719", "20260725", "20260726"),
    "AUGUST_DEVELOPMENT": ("20260801", "20260802", "20260808", "20260809", "20260815", "20260816"),
}
PREDICTION_ROOTS = {
    **{d: ROOT / "reports" / "h5_temporal_june_block1_v1" / f"prediction_{d}" for d in BLOCKS["JUNE_BLOCK_1"]},
    **{d: ROOT / "reports" / "cand_h5_001_july_4day_validation_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H1"]},
    **{d: ROOT / "reports" / "h5_temporal_july_h2_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H2"]},
    **{d: ROOT / "reports" / "buy_improvement_trace_6day_v1" / f"prediction_{d}" for d in BLOCKS["AUGUST_DEVELOPMENT"]},
}
VENUES = {"sapporo": "札幌", "niigata": "新潟", "chuukyou": "中京", "hakodate": "函館", "fukushima": "福島", "kokura": "小倉", "tokyo": "東京", "nakayama": "中山", "hanshin": "阪神", "kyoto": "京都"}
ABNORMAL = {"中止", "除外", "取消", "失格"}


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rate(hit: int, total: int) -> float | None:
    return hit / total if total else None


def outcome(row: list[str], number: int) -> dict:
    raw = row[11 + number]
    valid = raw.isdigit() and int(raw) > 0
    if not valid and raw not in ABNORMAL:
        raise RuntimeError(f"UNKNOWN_RESULT_SEMANTICS:{raw}")
    return {"raw_result": raw, "valid_result": valid, "actual_top3": valid and int(raw) <= 3, "winner": valid and int(raw) == 1}


def result_rows(date: str) -> tuple[dict[tuple[str, int], list[str]], dict]:
    primary = RAW / f"馬番順着順_{date}.csv"
    auxiliary = RAW / f"着順馬番_{date}.csv"
    validation = validate_source_pair(primary, auxiliary, date)
    if validation["status"] != "PASS":
        raise RuntimeError(f"RESULT_SCHEMA_FAIL:{date}")
    with primary.open("r", encoding="cp932", newline="") as f:
        rows = list(csv.reader(f))
    indexed = {(r[1], int(r[2])): r for r in rows}
    if len(indexed) != len(rows):
        raise RuntimeError(f"DUPLICATE_RESULT_RACE:{date}")
    return indexed, validation


def parse_bool(value: str, field: str) -> bool:
    if value not in {"True", "False"}:
        raise RuntimeError(f"INVALID_BOOLEAN:{field}:{value}")
    return value == "True"


def evidence_band(races: int) -> str:
    if races <= 9: return "TOO_SMALL"
    if races <= 19: return "OBSERVATION_ONLY"
    if races <= 29: return "DIRECTIONAL_WATCH"
    if races <= 49: return "MEANINGFUL_VALIDATION"
    if races <= 99: return "STRONG_RETROSPECTIVE_EVIDENCE"
    return "HIGH_CONFIDENCE_OPERATIONAL"


def metric(races: list[dict]) -> dict:
    top5 = [h for r in races for h in r["top5"]]
    all_horses = [h for r in races for h in r["horses"]]
    def group(predicate):
        values = [h for h in top5 if predicate(h) and h["valid_result"]]
        return {"numerator": sum(h["actual_top3"] for h in values), "denominator": len(values), "rate": rate(sum(h["actual_top3"] for h in values), len(values))}
    buy = group(lambda h: h["is_buy"])
    nonbuy = group(lambda h: not h["is_buy"])
    alltop = group(lambda h: True)
    top3_denom = sum(h["valid_result"] and h["actual_top3"] for h in all_horses)
    top3_num = sum(h["valid_result"] and h["actual_top3"] for h in top5)
    winner_races = [r for r in races if any(h["winner"] for h in r["horses"])]
    winner_num = sum(any(h["winner"] for h in r["top5"]) for r in winner_races)
    return {
        "eligible_race_count": len(races), "evidence_band": evidence_band(len(races)),
        "races_contributing_buy_observations": sum(any(h["is_buy"] and h["valid_result"] for h in r["top5"]) for r in races),
        "races_contributing_non_buy_top5_observations": sum(any(not h["is_buy"] and h["valid_result"] for h in r["top5"]) for r in races),
        "BUY_TOP3_RATE": buy, "NON_BUY_TOP5_TOP3_RATE": nonbuy, "TOP5_HORSE_TOP3_RATE": alltop,
        "BUY_SELECTION_LIFT": None if buy["rate"] is None or nonbuy["rate"] is None else buy["rate"] - nonbuy["rate"],
        "TOP5_CAPTURE_RATE": {"numerator": top3_num, "denominator": top3_denom, "rate": rate(top3_num, top3_denom)},
        "WINNER_TOP5_CAPTURE_RATE": {"numerator": winner_num, "denominator": len(winner_races), "rate": rate(winner_num, len(winner_races))},
        "valid_actual_top3_positions_all_ranked_horses": top3_denom,
        "races_with_valid_confirmed_winner": len(winner_races),
    }


def main() -> None:
    if OUT.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    required_dates = {d for dates in BLOCKS.values() for d in dates}
    with TOP5.open(encoding="utf-8", newline="") as f:
        primary = list(csv.DictReader(f))
    if len(primary) != 1535:
        raise RuntimeError(f"TOP5_ROW_COUNT:{len(primary)}")
    top5_by_race: dict[str, list[dict]] = defaultdict(list)
    for row in primary:
        row["rank"] = int(row["rank"]); row["horse_number"] = int(row["horse_number"])
        for field in ("is_buy", "valid_result", "actual_top3"): row[field] = parse_bool(row[field], field)
        top5_by_race[row["race_id"]].append(row)
    if len(top5_by_race) != 307:
        raise RuntimeError(f"TOP5_RACE_COUNT:{len(top5_by_race)}")
    for race_id, rows in top5_by_race.items():
        if [r["rank"] for r in sorted(rows, key=lambda x:x["rank"])] != [1,2,3,4,5]:
            raise RuntimeError(f"TOP5_RANK_INTEGRITY:{race_id}")
    races_by_block: dict[str, list[dict]] = {b: [] for b in BLOCKS}
    source_dates = set(); total_horses = 0; validation = {}; denominator_provenance = {}
    for block, dates in BLOCKS.items():
        for date in dates:
            result, schema = result_rows(date)
            artifacts = sorted(PREDICTION_ROOTS[date].glob("race_*_prediction.json"))
            if not artifacts: raise RuntimeError(f"PREDICTION_ARTIFACT_MISSING:{date}")
            validation[date] = {"prediction_root": str(PREDICTION_ROOTS[date].relative_to(ROOT)), "prediction_race_count": len(artifacts), "result_schema_status": schema["status"], "top5_rows": 0}
            denominator_provenance[date] = {"primary_result_path": str((RAW / f"馬番順着順_{date}.csv").relative_to(ROOT)), "primary_result_sha256": sha(RAW / f"馬番順着順_{date}.csv"), "schema_validation": "PASS"}
            for path in artifacts:
                payload = json.loads(path.read_text(encoding="utf-8")); race_id = payload["race_id"]
                if race_id not in top5_by_race: raise RuntimeError(f"PRIMARY_TOP5_RACE_MISSING:{race_id}")
                parts = race_id.split("_"); key = (VENUES[parts[-2]], int(parts[-1][:-1]))
                if key not in result: raise RuntimeError(f"RESULT_MAPPING_MISSING:{race_id}")
                ordered = sorted(payload["ranked_results"], key=lambda h:h["rank"])
                if [h["rank"] for h in ordered] != list(range(1, len(ordered)+1)): raise RuntimeError(f"RANKING_INVALID:{race_id}")
                horses=[]
                for h in ordered:
                    o=outcome(result[key], int(h["horse_number"]))
                    horses.append({"rank":int(h["rank"]), "horse_number":int(h["horse_number"]), "is_buy": bool(h.get("buy")), **o})
                export = sorted(top5_by_race[race_id], key=lambda x:x["rank"])
                actual = horses[:5]
                for expected, observed in zip(export, actual):
                    keys=("rank","horse_number","is_buy","valid_result","actual_top3","raw_result")
                    if any(expected[k] != observed[k] for k in keys): raise RuntimeError(f"PRIMARY_EXPORT_MISMATCH:{race_id}:{expected['rank']}")
                races_by_block[block].append({"date":date,"race_id":race_id,"horses":horses,"top5":actual})
                validation[date]["top5_rows"] += 5; source_dates.add(date); total_horses += len(horses)
    if source_dates != required_dates or sum(len(v) for v in races_by_block.values()) != 307 or total_horses != 3925:
        raise RuntimeError("SOURCE_POPULATION_MISMATCH")
    blocks = {block: metric(races) for block, races in races_by_block.items()}
    pooled = metric([r for races in races_by_block.values() for r in races])
    lifts = {b:v["BUY_SELECTION_LIFT"] for b,v in blocks.items()}
    signs = {b: "POSITIVE" if x > 0 else "NEGATIVE" if x < 0 else "ZERO" for b,x in lifts.items()}
    if "POSITIVE" in signs.values() and "NEGATIVE" in signs.values(): decision = "BUY_SELECTION_TEMPORALLY_UNSTABLE"
    elif list(signs.values()).count("POSITIVE") >= 2: decision = "BUY_SELECTION_ADDS_PRECISION"
    else: decision = "BUY_SELECTION_FAILS_TO_ADD_PRECISION"
    june_subset = [r for r in races_by_block["JUNE_BLOCK_1"] if r["date"] in {"20260627","20260628"}]
    cross = metric(june_subset)
    aug_subset = [r for r in races_by_block["AUGUST_DEVELOPMENT"] if r["date"] in {"20260815","20260816"}]
    aug_winner = metric(aug_subset)["WINNER_TOP5_CAPTURE_RATE"]
    dump("source_validation.json", {"status":"PASS","primary_source":str(TOP5.relative_to(ROOT)),"primary_sha256":sha(TOP5),"expected_top5_rows":1535,"actual_top5_rows":len(primary),"expected_races":307,"actual_races":len(top5_by_race),"expected_dates":18,"actual_dates":len(source_dates),"expected_prediction_horses":3925,"actual_prediction_horses":total_horses,"by_date":validation,"primary_export_matches_saved_prediction_and_result_mapping":True})
    dump("denominator_validation.json", {"status":"PASS","method":"All saved ranked Prediction horses were joined read-only to schema-validated existing Daily Result List primary sources. No fixed-three-per-race assumption was used.","by_date":denominator_provenance,"all_ranked_horse_count":total_horses,"all_valid_actual_top3_positions":pooled["valid_actual_top3_positions_all_ranked_horses"],"races_with_valid_confirmed_winner":pooled["races_with_valid_confirmed_winner"]})
    dump("block_precision.json", blocks); dump("pooled_precision.json", pooled)
    dump("buy_selection_lift.json", {"by_block":lifts,"sign_by_block":signs,"pooled":pooled["BUY_SELECTION_LIFT"],"descriptive_only":True})
    dump("top5_capture.json", {"by_block":{b:v["TOP5_CAPTURE_RATE"] for b,v in blocks.items()},"pooled":pooled["TOP5_CAPTURE_RATE"]})
    dump("winner_capture.json", {"by_block":{b:v["WINNER_TOP5_CAPTURE_RATE"] for b,v in blocks.items()},"pooled":pooled["WINNER_TOP5_CAPTURE_RATE"],"legacy_20260815_20260816_context":{"legacy":"19/34","current":aug_winner,"explanation":"The current frozen Prediction population contains 16 eligible races on 2026-08-15 and 17 on 2026-08-16 (33 total); all 33 have a valid confirmed winner. The legacy denominator 34 therefore included one race outside the current frozen Prediction population."}})
    dump("temporal_consistency.json", {"lift_sign_by_block":signs,"positive_block_count":list(signs.values()).count("POSITIVE"),"negative_block_count":list(signs.values()).count("NEGATIVE"),"zero_block_count":list(signs.values()).count("ZERO"),"consistent_direction":len(set(signs.values()))==1,"independent_evidence_unit":"RACE","interpretation":"Block-level lift sign is primary; pooled horse-level rate is secondary."})
    dump("analysis_gate.json", {"final_decision":decision,"rule":"positive and negative signs across blocks => temporally unstable; otherwise two or more positive blocks => adds precision; otherwise fails to add precision.","feature_mining":False,"candidate_created":False,"production_changes":0,"buy_changes":0,"decision_changes":0})
    summary = {"final_decision":decision,"source_dates":len(source_dates),"source_races":307,"source_top5_rows":len(primary),"valid_BUY_count":pooled["BUY_TOP3_RATE"]["denominator"],"valid_NON_BUY_TOP5_count":pooled["NON_BUY_TOP5_TOP3_RATE"]["denominator"],"pooled":pooled,"cross_check_20260627_20260628":{"current": {"BUY":cross["BUY_TOP3_RATE"],"NON_BUY_TOP5":cross["NON_BUY_TOP5_TOP3_RATE"]},"legacy_context":{"BUY":"6/23","NON_BUY_TOP5":"46/146"}},"no_feature_mining":True,"no_candidate_created":True,"production_buy_decision_changes":0}
    dump("summary.json", summary)
    lines=["# BUY Precision Analysis v1","",f"Final decision: `{decision}`.","", "This read-only analysis used the frozen 1,535-row Top5 export as its primary source. Existing saved full rankings and schema-validated Daily Result Lists were used only to establish capture denominators.","", "## Block metrics", "", "| Block | BUY Top3 | Non-BUY Top5 Top3 | Lift | Top5 Capture | Winner Capture | Eligible races |", "|---|---:|---:|---:|---:|---:|---:|"]
    for b,v in blocks.items():
        fmt=lambda x: "n/a" if x is None else f"{x:.2%}"
        lines.append(f"| {b} | {fmt(v['BUY_TOP3_RATE']['rate'])} ({v['BUY_TOP3_RATE']['numerator']}/{v['BUY_TOP3_RATE']['denominator']}) | {fmt(v['NON_BUY_TOP5_TOP3_RATE']['rate'])} ({v['NON_BUY_TOP5_TOP3_RATE']['numerator']}/{v['NON_BUY_TOP5_TOP3_RATE']['denominator']}) | {fmt(v['BUY_SELECTION_LIFT'])} | {fmt(v['TOP5_CAPTURE_RATE']['rate'])} ({v['TOP5_CAPTURE_RATE']['numerator']}/{v['TOP5_CAPTURE_RATE']['denominator']}) | {fmt(v['WINNER_TOP5_CAPTURE_RATE']['rate'])} ({v['WINNER_TOP5_CAPTURE_RATE']['numerator']}/{v['WINNER_TOP5_CAPTURE_RATE']['denominator']}) | {v['eligible_race_count']} |")
    lines += ["", "No feature mining, Candidate creation, Prediction rerun, or Production/BUY/Decision modification was performed."]
    (OUT / "report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")

if __name__ == "__main__": main()
