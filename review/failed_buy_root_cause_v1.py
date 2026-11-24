"""Structural failed-BUY diagnosis from saved Predictions and existing result lists."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "failed_buy_root_cause_v1"
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
EXPECTED_FAILURE_RACES = {"JUNE_BLOCK_1": 20, "JULY_H1": 14, "JULY_H2": 12, "AUGUST_DEVELOPMENT": 23}


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def result_index(date: str) -> tuple[dict[tuple[str, int], list[str]], dict]:
    primary, auxiliary = RAW / f"馬番順着順_{date}.csv", RAW / f"着順馬番_{date}.csv"
    validation = validate_source_pair(primary, auxiliary, date)
    if validation["status"] != "PASS":
        raise RuntimeError(f"RESULT_SCHEMA_FAIL:{date}")
    with primary.open(encoding="cp932", newline="") as source:
        rows = list(csv.reader(source))
    indexed = {(row[1], int(row[2])): row for row in rows}
    if len(indexed) != len(rows):
        raise RuntimeError(f"DUPLICATE_RESULT_RACE:{date}")
    return indexed, validation


def outcome(row: list[str], horse_number: int) -> dict:
    index = 11 + horse_number
    if index >= len(row):
        raise RuntimeError(f"RESULT_HORSE_INDEX_MISSING:{horse_number}")
    raw = row[index]
    valid = raw.isdigit() and int(raw) > 0
    if not valid and raw not in ABNORMAL:
        raise RuntimeError(f"UNKNOWN_RESULT_SEMANTICS:{horse_number}:{raw}")
    return {"raw_result": raw, "valid_result": valid, "actual_top3": bool(valid and int(raw) <= 3)}


def main() -> None:
    if OUT.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    source_validation, block_summary, classifications, top5_export, capture_distribution = {}, {}, [], [], {1: 0, 2: 0, 3: 0}
    total_prediction_races = total_prediction_horses = total_mapped_horses = total_abnormal = fewer_than_five = 0
    for block, dates in BLOCKS.items():
        block_races, mapped_horses, prediction_horses, result_status = [], 0, 0, {}
        for date in dates:
            result_rows, validation = result_index(date); result_status[date] = {"status": validation["status"], "primary_width": validation["source_d_primary"]["raw_column_count"], "auxiliary_width": validation["source_c_auxiliary"]["raw_column_count"]}
            artifacts = sorted(PREDICTION_ROOTS[date].glob("race_*_prediction.json"))
            if not artifacts:
                raise RuntimeError(f"PREDICTION_ARTIFACT_MISSING:{date}")
            seen_races = set()
            for path in artifacts:
                payload = json.loads(path.read_text(encoding="utf-8")); race_id = payload.get("race_id"); ranked = payload.get("ranked_results")
                if not race_id or not isinstance(ranked, list) or race_id in seen_races:
                    raise RuntimeError(f"PREDICTION_STRUCTURE_INVALID:{path}")
                seen_races.add(race_id)
                ordered = sorted(ranked, key=lambda horse: horse.get("rank")); ranks = [horse.get("rank") for horse in ordered]
                if ranks != list(range(1, len(ordered) + 1)):
                    raise RuntimeError(f"RANKING_UNAVAILABLE:{race_id}")
                pieces = race_id.split("_"); key = (VENUES[pieces[-2]], int(pieces[-1][:-1])); result = result_rows.get(key)
                if result is None:
                    raise RuntimeError(f"RESULT_RACE_MAPPING_MISSING:{race_id}")
                horses = []
                for horse in ordered:
                    number = int(horse["horse_number"]); mapped = outcome(result, number)
                    horses.append({"rank": int(horse["rank"]), "horse_number": number, "is_buy": horse.get("decision") == "BUY" or horse.get("buy") is True, **mapped})
                prediction_horses += len(horses); mapped_horses += len(horses)
                total_abnormal += sum(not horse["valid_result"] for horse in horses if horse["is_buy"])
                top5 = horses[: min(5, len(horses))]
                if len(top5) < 5:
                    fewer_than_five += 1
                for horse in top5:
                    top5_export.append({"block": block, "date": date, "race_id": race_id, "rank": horse["rank"], "horse_number": horse["horse_number"], "is_buy": horse["is_buy"], "valid_result": horse["valid_result"], "actual_top3": horse["actual_top3"], "raw_result": horse["raw_result"]})
                block_races.append({"date": date, "race_id": race_id, "horses": horses, "top5": top5})
        failure_races = []
        for race in block_races:
            valid_buys = [horse for horse in race["horses"] if horse["is_buy"] and horse["valid_result"]]
            if valid_buys and not any(horse["actual_top3"] for horse in valid_buys):
                failure_races.append(race)
        if len(failure_races) != EXPECTED_FAILURE_RACES[block]:
            raise RuntimeError(f"BUY_FAILURE_ONLY_COUNT_MISMATCH:{block}:{len(failure_races)}:{EXPECTED_FAILURE_RACES[block]}")
        selection = generation = 0
        for race in failure_races:
            captured = [horse for horse in race["top5"] if not horse["is_buy"] and horse["valid_result"] and horse["actual_top3"]]
            category = "BUY_SELECTION_FAILURE" if captured else "TOP5_GENERATION_FAILURE"
            if category == "BUY_SELECTION_FAILURE":
                selection += 1; capture_distribution[len(captured)] += 1
            else:
                generation += 1
            classifications.append({"block": block, "date": race["date"], "race_id": race["race_id"], "category": category, "non_buy_top5_top3_capture_count": len(captured), "top5_horse_count": len(race["top5"])})
        if selection + generation != len(failure_races):
            raise RuntimeError(f"CLASSIFICATION_INVARIANT_FAIL:{block}")
        block_summary[block] = {"BUY_FAILURE_ONLY_RACES": len(failure_races), "BUY_SELECTION_FAILURE_RACES": selection, "TOP5_GENERATION_FAILURE_RACES": generation,
                                "BUY_SELECTION_FAILURE_RATE": selection / len(failure_races) if failure_races else None, "TOP5_GENERATION_FAILURE_RATE": generation / len(failure_races) if failure_races else None,
                                "TOTAL_ELIGIBLE_RACES": len(block_races), "prediction_horses": prediction_horses, "mapped_horses": mapped_horses}
        source_validation[block] = {"date_count": len(dates), "dates": list(dates), "prediction_races": len(block_races), "prediction_horses": prediction_horses, "mapped_horses": mapped_horses,
                                    "mapping_complete": prediction_horses == mapped_horses, "result_schema": result_status, "ranking_available": True}
        total_prediction_races += len(block_races); total_prediction_horses += prediction_horses; total_mapped_horses += mapped_horses
    selection_total = sum(row["BUY_SELECTION_FAILURE_RACES"] for row in block_summary.values()); generation_total = sum(row["TOP5_GENERATION_FAILURE_RACES"] for row in block_summary.values())
    total_failure = selection_total + generation_total
    dominant = [(name, "BUY_SELECTION") if row["BUY_SELECTION_FAILURE_RACES"] > row["TOP5_GENERATION_FAILURE_RACES"] else (name, "TOP5_GENERATION") if row["TOP5_GENERATION_FAILURE_RACES"] > row["BUY_SELECTION_FAILURE_RACES"] else (name, "TIE") for name, row in block_summary.items()]
    values = [value for _, value in dominant]
    decision = "PRIMARY_BOTTLENECK_BUY_SELECTION" if values.count("BUY_SELECTION") >= 3 and values.count("TOP5_GENERATION") == 0 else "PRIMARY_BOTTLENECK_TOP5_GENERATION" if values.count("TOP5_GENERATION") >= 3 and values.count("BUY_SELECTION") == 0 else "MIXED_FAILURE_STRUCTURE"
    with (OUT / "top5_result_export.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(top5_export[0])); writer.writeheader(); writer.writerows(top5_export)
    with (OUT / "failed_buy_classification.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(classifications[0])); writer.writeheader(); writer.writerows(classifications)
    write_json("source_validation.json", {"total_source_dates": 18, "prediction_races": total_prediction_races, "prediction_horses": total_prediction_horses, "mapped_horses": total_mapped_horses, "by_block": source_validation})
    write_json("population_validation.json", {"expected_buy_failure_only_by_block": EXPECTED_FAILURE_RACES, "actual_buy_failure_only_by_block": {block: row["BUY_FAILURE_ONLY_RACES"] for block, row in block_summary.items()}, "total_buy_failure_only": total_failure, "mapping_complete": total_prediction_horses == total_mapped_horses, "abnormal_BUY_exclusions": total_abnormal, "classification_exclusive_and_exhaustive": True})
    write_json("block_summary.json", block_summary)
    write_json("capture_count_summary.json", {"BUY_SELECTION_FAILURE_CAPTURE_DISTRIBUTION": {str(key): value for key, value in capture_distribution.items()}, "definition": "count of actual Top3 non-BUY horses inside AI Top5; recorded only for BUY_SELECTION_FAILURE"})
    write_json("temporal_consistency.json", {"dominance_by_block": [{"block": block, "dominance": value} for block, value in dominant], "stable_dominance": len(set(values)) == 1, "interpretation": "Block-level dominance is required; pooled majority alone is not treated as dominance."})
    gate = {"final_decision": decision, "primary_bottleneck": "BUY_SELECTION" if decision == "PRIMARY_BOTTLENECK_BUY_SELECTION" else "TOP5_GENERATION" if decision == "PRIMARY_BOTTLENECK_TOP5_GENERATION" else "BOTH_OR_TEMPORALLY_MIXED", "next_investigation_focus": "BUY_SELECTION" if decision == "PRIMARY_BOTTLENECK_BUY_SELECTION" else "TOP5_GENERATION" if decision == "PRIMARY_BOTTLENECK_TOP5_GENERATION" else "BOTH", "candidate_created": False, "production_changes": 0}
    write_json("analysis_gate.json", gate)
    write_json("summary.json", {"final_decision": decision, "total_source_dates": 18, "prediction_races": total_prediction_races, "prediction_horses": total_prediction_horses, "mapped_horses": total_mapped_horses, "BUY_FAILURE_ONLY_RACES": total_failure, "BUY_SELECTION_FAILURE_RACES": selection_total, "TOP5_GENERATION_FAILURE_RACES": generation_total, "BUY_SELECTION_FAILURE_RATE": selection_total / total_failure, "TOP5_GENERATION_FAILURE_RATE": generation_total / total_failure, "abnormal_BUY_exclusions": total_abnormal, "fewer_than_five_ranked_cases": fewer_than_five, "no_feature_mining": True, "production_changes": 0})
    (OUT / "report.md").write_text(f"# Failed BUY Root Cause Analysis\n\nFinal structural decision: `{decision}`. The 69 pre-established BUY_FAILURE_ONLY races were revalidated using saved Prediction ranking and existing Daily Result List mapping. No feature, threshold, Candidate, or Production change was made.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
