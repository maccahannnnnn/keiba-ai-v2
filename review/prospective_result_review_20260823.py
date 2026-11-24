"""POST-only review of the frozen 2026-08-23 Human-exclusion PRE run."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

from review.target_daily_result_list_schema_v2_validator import validate_source_pair


ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "reports" / "prospective_prediction_20260823_v1"
OUT = ROOT / "reports" / "prospective_result_20260823_v1"
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
EXCLUDED_RACE_ID = "race_20260823_niigata_7R"
VENUES = {"sapporo": "札幌", "niigata": "新潟", "chuukyou": "中京"}
ABNORMAL = {"中止", "除外", "取消", "失格"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def parts(race_id: str) -> tuple[str, int]:
    values = race_id.split("_")
    return VENUES[values[-2]], int(re.sub(r"R$", "", values[-1]))


def result_outcome(row: list[str], horse_number: int) -> dict:
    raw = row[11 + horse_number]
    valid = raw.isdigit() and int(raw) > 0
    if not valid and raw not in ABNORMAL:
        raise RuntimeError(f"UNKNOWN_RESULT_SEMANTICS:{raw}")
    return {"actual_finish": raw, "valid_result": valid, "actual_top3": bool(valid and int(raw) <= 3), "winner": bool(valid and int(raw) == 1)}


def metric(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(row["actual_top3"] for row in valid)
    return {"numerator": hits, "denominator": len(valid), "rate": rate(hits, len(valid))}


def main() -> None:
    if OUT.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    manifest = json.loads((PRE / "prediction_manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        path = PRE / item["relative_path"]
        if not path.exists() or sha(path) != item["sha256"]:
            raise RuntimeError(f"FROZEN_PRE_MANIFEST_MISMATCH:{item['relative_path']}")
    frozen_summary = json.loads((PRE / "summary.json").read_text(encoding="utf-8"))
    frozen_exclusion = json.loads((PRE / "exclusion_record.json").read_text(encoding="utf-8"))
    if (frozen_summary["total_source_races"], frozen_summary["evaluated_races"], frozen_summary["evaluated_horses"], frozen_summary["buy_count"]) != (18, 17, 238, 14):
        raise RuntimeError("FROZEN_POPULATION_MISMATCH")
    if frozen_exclusion["excluded_races"] != frozen_summary["not_evaluated"] or frozen_exclusion["excluded_races"][0]["race_id"] != EXCLUDED_RACE_ID:
        raise RuntimeError("FROZEN_EXCLUSION_RECORD_MISMATCH")

    primary = RAW / "馬番順着順_20260823.csv"
    auxiliary = RAW / "着順馬番_20260823.csv"
    validation = validate_source_pair(primary, auxiliary, "20260823")
    if validation["status"] != "PASS":
        raise RuntimeError("RESULT_SCHEMA_FAIL")
    with primary.open(encoding="cp932", newline="") as handle:
        raw_rows = list(csv.reader(handle))
    results = {(row[1], int(row[2])): row for row in raw_rows}
    if len(results) != len(raw_rows):
        raise RuntimeError("DUPLICATE_RESULT_RACE")

    index = json.loads((PRE / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    if len(index) != 17 or EXCLUDED_RACE_ID in {item["race_id"] for item in index}:
        raise RuntimeError("FROZEN_EVALUATED_RACE_SET_MISMATCH")
    all_rows, race_rows, buys, unconverged, skips, missing = [], [], [], [], [], []
    for item in sorted(index, key=lambda value: value["race_id"]):
        payload = json.loads((PRE / item["artifact"]).read_text(encoding="utf-8"))
        race_id = payload["race_id"]
        venue, race_number = parts(race_id)
        result_row = results.get((venue, race_number))
        if result_row is None:
            missing.append(race_id)
            continue
        trace = payload["buy_gate_trace"]
        ranked, by_number = [], {}
        for horse in payload["ranked_results"]:
            number = int(horse["horse_number"])
            mapped = {"race_id": race_id, "venue": venue, "race_number": race_number, "horse_number": number, "horse_name": horse.get("horse_name"), "rank": horse.get("rank"), "frozen_buy": horse.get("buy", horse.get("decision") == "BUY"), **result_outcome(result_row, number)}
            ranked.append(mapped)
            by_number[number] = mapped
            all_rows.append(mapped)
            if mapped["frozen_buy"]:
                buys.append(mapped)
        top5 = ranked[:5]
        top5_top3 = sum(row["valid_result"] and row["actual_top3"] for row in top5)
        winner_in_top5 = any(row["winner"] for row in top5)
        valid_winner_confirmed = any(row["winner"] for row in ranked)
        race_rows.append({"race_id": race_id, "venue": venue, "race_number": race_number, "field_size": len(ranked), "frozen_buy_count": sum(row["frozen_buy"] for row in ranked), "frozen_buy_top3_count": sum(row["frozen_buy"] and row["valid_result"] and row["actual_top3"] for row in ranked), "at_least_one_successful_buy": any(row["frozen_buy"] and row["valid_result"] and row["actual_top3"] for row in ranked), "top5_actual_top3_count": top5_top3, "winner_in_top5": winner_in_top5, "valid_winner_confirmed": valid_winner_confirmed, "shadow_race_state": trace["race"]["shadow_race_state"], "shadow_candidate_count": trace["race"]["shadow_candidate_count"]})
        state = trace["race"]["shadow_race_state"]
        if state == "PLAY_UNCONVERGED_4PLUS":
            # Selection is built from frozen PRE rank before result fields are
            # attached; outcome is descriptive context only, never a rule.
            candidates_pre = []
            for horse in trace["horses"]:
                if horse["shadow_buy_candidate"] is True:
                    candidates_pre.append({"horse_number": int(horse["horse_number"]), "shadow_ai_rank": horse["shadow_ai_rank"]})
            candidates_pre.sort(key=lambda row: row["shadow_ai_rank"])
            if len(candidates_pre) != trace["race"]["shadow_candidate_count"]:
                raise RuntimeError(f"CANDIDATE_COUNT_MISMATCH:{race_id}")
            candidates = [{**candidate, **result_outcome(result_row, candidate["horse_number"]), "horse_name": by_number[candidate["horse_number"]]["horse_name"], "CF_TOP3_RANK_ANCHORED_selected": index < 3} for index, candidate in enumerate(candidates_pre)]
            selected = [candidate for candidate in candidates if candidate["CF_TOP3_RANK_ANCHORED_selected"]]
            context = {
                "selection_basis": "frozen shadow_ai_rank ascending",
                "selected_horse_count": len(selected),
                "selected_valid_horse_count": sum(row["valid_result"] for row in selected),
                "selected_actual_top3_count": sum(row["valid_result"] and row["actual_top3"] for row in selected),
                "selected_top3_rate": rate(
                    sum(row["valid_result"] and row["actual_top3"] for row in selected),
                    sum(row["valid_result"] for row in selected),
                ),
            }
            unconverged.append({
                "race_id": race_id, "venue": venue, "race_number": race_number,
                "classification": "PRE_PROTOCOL_PROSPECTIVE_CONTEXT_ONLY",
                "frozen_shadow_candidate_count": len(candidates), "candidates": candidates,
                "actual_top3_candidate_count": sum(row["valid_result"] and row["actual_top3"] for row in candidates),
                "CF_TOP3_RANK_ANCHORED_context": context,
            })
        if state == "SKIP":
            skips.append({"race_id": race_id, "venue": venue, "race_number": race_number, "top5": top5, "actual_top3_capture_count": top5_top3, "winner_capture": winner_in_top5})
    if missing:
        raise RuntimeError(f"ELIGIBLE_RESULT_MAPPING_MISSING:{missing}")
    if len(all_rows) != 238 or len(buys) != 14:
        raise RuntimeError(f"FROZEN_HORSE_BUY_MISMATCH:{len(all_rows)}:{len(buys)}")
    if len({(row["race_id"], row["horse_number"]) for row in all_rows}) != 238:
        raise RuntimeError("DUPLICATE_HORSE_MAPPING")

    buy_metric = metric(buys)
    top5 = [row for row in all_rows if row["rank"] <= 5]
    nonbuy_metric = metric([row for row in top5 if not row["frozen_buy"]])
    top5_metric = metric(top5)
    total_top3 = sum(row["valid_result"] and row["actual_top3"] for row in all_rows)
    top5_hits = sum(row["valid_result"] and row["actual_top3"] for row in top5)
    winner_races = [row for row in race_rows if row["valid_winner_confirmed"]]
    winner_hits = sum(row["winner_in_top5"] for row in winner_races)
    abnormal = [row for row in all_rows if not row["valid_result"]]
    for item in manifest["files"]:
        if sha(PRE / item["relative_path"]) != item["sha256"]:
            raise RuntimeError(f"FROZEN_PRE_MUTATED:{item['relative_path']}")

    OUT.mkdir(parents=True)
    lift = None if buy_metric["rate"] is None or nonbuy_metric["rate"] is None else buy_metric["rate"] - nonbuy_metric["rate"]
    dump("result_validation.json", {"status": "PASS", "date": "20260823", "schema_validation": validation, "source_races": 18, "eligible_frozen_races": 17, "mapped_eligible_races": 17, "missing_eligible_races": 0, "mapped_prediction_horses": 238, "duplicate_race_mapping": 0, "duplicate_horse_mapping": 0, "abnormal_result_exclusions": len(abnormal), "frozen_pre_manifest_unchanged": True})
    dump("horse_result_mapping.json", {"mapping_count": len(all_rows), "rows": all_rows})
    dump("buy_results.json", {"frozen_buy_count": len(buys), "valid_buy_count": buy_metric["denominator"], "buy_top3_count": buy_metric["numerator"], "buy_top3_rate": buy_metric["rate"], "horses": buys, "by_race": [{"race_id": row["race_id"], "venue": row["venue"], "race_number": row["race_number"], "buy_count": row["frozen_buy_count"], "buy_top3_count": row["frozen_buy_top3_count"], "at_least_one_successful_buy": row["at_least_one_successful_buy"]} for row in race_rows if row["frozen_buy_count"]]})
    dump("buy_precision.json", {"BUY_TOP3_RATE": buy_metric, "NON_BUY_TOP5_TOP3_RATE": nonbuy_metric, "BUY_SELECTION_LIFT": lift, "boundary": "One-day prospective observation only; no revision to established cumulative state."})
    dump("top5_precision.json", {"TOP5_HORSE_TOP3_RATE": top5_metric, "TOP5_CAPTURE_RATE": {"numerator": top5_hits, "denominator": total_top3, "rate": rate(top5_hits, total_top3)}, "WINNER_TOP5_CAPTURE_RATE": {"numerator": winner_hits, "denominator": len(winner_races), "rate": rate(winner_hits, len(winner_races))}, "denominator_method": "All frozen evaluated horses only; NOT_EVALUATED 新潟7R excluded."})
    dump("unconverged_results.json", {"classification": "PRE_PROTOCOL_PROSPECTIVE_CONTEXT_ONLY", "race_count": len(unconverged), "races": unconverged, "not_formal_shadow_evidence": True})
    dump("skip_results.json", {"race_count": len(skips), "races": skips})
    dump("exclusion_audit.json", {"not_evaluated": frozen_exclusion["excluded_races"], "excluded_from_buy_top5_unconverged_skip_kpi": True, "result_joined_for_metrics": False, "no_past_performance_classification_applied": False})
    summary = {"final_status": "PROSPECTIVE_POST_REVIEW_COMPLETE", "source_races": 18, "evaluated_races": 17, "not_evaluated_races": 1, "prediction_horse_count": len(all_rows), "frozen_buy_count": len(buys), "valid_buy_count": buy_metric["denominator"], "buy_top3_count": buy_metric["numerator"], "BUY_TOP3_RATE": buy_metric["rate"], "BUY_RACE_SUCCESS_COUNT": sum(row["at_least_one_successful_buy"] for row in race_rows), "NON_BUY_TOP5_TOP3_RATE": nonbuy_metric["rate"], "TOP5_HORSE_TOP3_RATE": top5_metric["rate"], "TOP5_CAPTURE_RATE": rate(top5_hits, total_top3), "WINNER_TOP5_CAPTURE_RATE": rate(winner_hits, len(winner_races)), "BUY_SELECTION_LIFT": lift, "unconverged_race_count": len(unconverged), "skip_race_count": len(skips), "abnormal_result_exclusions": len(abnormal), "mapping_discrepancies": 0, "frozen_pre_manifest_unchanged": True, "prediction_rerun": False, "rule_changes": 0, "shadow_implementation": False, "production_changes": 0}
    dump("summary.json", summary)
    fmt = lambda value: "n/a" if value is None else f"{value:.2%}"
    lines = ["# 2026-08-23 Prospective POST Review", "", f"- Evaluated frozen races: 17/18; NOT_EVALUATED: 新潟7R", f"- BUY Top3: {buy_metric['numerator']}/{buy_metric['denominator']} ({fmt(buy_metric['rate'])})", f"- Non-BUY Top5 Top3: {nonbuy_metric['numerator']}/{nonbuy_metric['denominator']} ({fmt(nonbuy_metric['rate'])})", f"- Top5 capture: {top5_hits}/{total_top3} ({fmt(rate(top5_hits, total_top3))})", f"- Winner Top5 capture: {winner_hits}/{len(winner_races)} ({fmt(rate(winner_hits, len(winner_races)))})", f"- BUY selection lift: {fmt(lift)}", "", "## BUY outcomes", "", "| Venue | Race | Horse | Finish | Valid | Top3 |", "|---|---:|---|---:|---|---|"]
    for row in buys:
        lines.append(f"| {row['venue']} | {row['race_number']}R | {row['horse_number']} {row['horse_name']} | {row['actual_finish']} | {row['valid_result']} | {row['actual_top3']} |")
    lines += ["", "## PRE-protocol UNCONVERGED context only", ""]
    for row in unconverged:
        context = row["CF_TOP3_RANK_ANCHORED_context"]
        lines.append(f"- {row['venue']} {row['race_number']}R: pool Top3={row['actual_top3_candidate_count']}; CF selected Top3={context['selected_actual_top3_count']}/{context['selected_valid_horse_count']} ({fmt(context['selected_top3_rate'])}) — not formal Shadow evidence.")
    lines += ["", "## SKIP observation", ""]
    for row in skips:
        lines.append(f"- {row['venue']} {row['race_number']}R: Top5 actual Top3={row['actual_top3_capture_count']}, winner captured={row['winner_capture']}")
    lines += ["", "新潟7R remained NOT_EVALUATED and was excluded from every metric. Frozen PRE manifest remained unchanged. No Prediction rerun, rule change, Shadow implementation, or Production change occurred."]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
