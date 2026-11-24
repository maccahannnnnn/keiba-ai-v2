"""June block 1 result join and frozen H5 temporal metrics only."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "h5_temporal_june_block1_v1"
INPUT = ROOT / "data" / "raw" / "prediction_input"
RESULTS = ROOT / "data" / "raw" / "target" / "daily_result_list"
DATES = ("20260620", "20260621", "20260627", "20260628")
VENUES = {"sapporo": "札幌", "niigata": "新潟", "chuukyou": "中京", "hakodate": "函館", "fukushima": "福島", "kokura": "小倉",
          "tokyo": "東京", "nakayama": "中山", "hanshin": "阪神", "kyoto": "京都"}
ABNORMAL = {"中止", "除外", "取消", "失格"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, data: object) -> None:
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def metric(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    top3 = [row for row in valid if row["actual_top3"]]
    return {"race_count": len({row["race_id"] for row in rows}), "BUY_count": len(rows),
            "valid_BUY_count": len(valid), "Top3_count": len(top3),
            "failure_count": len(valid) - len(top3),
            "Top3_rate": len(top3) / len(valid) if valid else None}


def result_index(date: str) -> tuple[dict[tuple[str, int], list[str]], dict]:
    primary = RESULTS / f"馬番順着順_{date}.csv"
    auxiliary = RESULTS / f"着順馬番_{date}.csv"
    validation = validate_source_pair(primary, auxiliary, date)
    if validation["status"] != "PASS":
        raise RuntimeError(f"RESULT_SCHEMA_FAIL:{date}")
    with primary.open(encoding="cp932", newline="") as source:
        raw_rows = list(csv.reader(source))
    indexed = {(row[1], int(row[2])): row for row in raw_rows}
    if len(indexed) != len(raw_rows):
        raise RuntimeError(f"DUPLICATE_RESULT_RACE:{date}")
    return indexed, validation


def main() -> None:
    if not OUT.exists() or (OUT / "summary.json").exists():
        raise RuntimeError("OUTPUT_STATE_INVALID")
    input_summary, result_summary, coverage, all_buy_rows = {}, {}, [], []
    for date in DATES:
        paths = {kind: INPUT / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
        bundle = TargetBulkPredictionInputAdapterV1().load(paths["DG"], paths["DE"], paths["DS"])
        if bundle.date != date:
            raise RuntimeError(f"TARGET_DATE_MISMATCH:{date}:{bundle.date}")
        results, result_validation = result_index(date)
        artifacts = sorted((OUT / f"prediction_{date}").glob("race_*_prediction.json"))
        payloads = [json.loads(path.read_text(encoding="utf-8")) for path in artifacts]
        race_ids = [payload["race_id"] for payload in payloads]
        if len(race_ids) != len(set(race_ids)) or set(race_ids) != set(bundle.races):
            raise RuntimeError(f"PREDICTION_POPULATION_MISMATCH:{date}")
        date_buy_rows = []
        for payload in payloads:
            pieces = payload["race_id"].split("_")
            result = results.get((VENUES[pieces[-2]], int(pieces[-1][:-1])))
            if result is None:
                raise RuntimeError(f"MISSING_RESULT_RACE:{payload['race_id']}")
            for horse in payload["ranked_results"]:
                number = int(horse["horse_number"])
                if 11 + number >= len(result):
                    raise RuntimeError(f"MISSING_RESULT_HORSE:{payload['race_id']}:{number}")
                if horse.get("decision") != "BUY":
                    continue
                raw_finish = result[11 + number]
                valid = raw_finish.isdigit() and int(raw_finish) > 0
                if not valid and raw_finish not in ABNORMAL:
                    raise RuntimeError(f"UNKNOWN_FINISH_STATUS:{payload['race_id']}:{number}:{raw_finish}")
                date_buy_rows.append({"date": date, "race_id": payload["race_id"], "horse_number": number,
                                      "race_buy_count": payload["buy_count"], "valid_result": valid,
                                      "actual_top3": bool(valid and int(raw_finish) <= 3), "raw_result": raw_finish})
        horses = sum(len(payload["ranked_results"]) for payload in payloads)
        input_summary[date] = {"adapter_status": "PASS", "target_date": bundle.date, "raw_race_count": len(bundle.races),
                               "eligible_race_count": len(payloads), "eligible_horse_count": horses,
                               "raw_sha256": {kind: sha256(path) for kind, path in paths.items()}}
        result_summary[date] = {"status": "PASS", "race_set_count": result_validation["race_set_count"],
                                "primary_width": result_validation["source_d_primary"]["raw_column_count"],
                                "auxiliary_width": result_validation["source_c_auxiliary"]["raw_column_count"]}
        coverage.append({"date": date, "prediction_races": len(payloads), "mapped_races": len(payloads),
                         "prediction_horses": horses, "mapped_horses": horses, "missing": 0, "duplicate": 0,
                         "collision": 0, "ambiguous": 0,
                         "abnormal_BUY_exclusions": sum(not row["valid_result"] for row in date_buy_rows)})
        all_buy_rows.extend(date_buy_rows)

    per_date = {date: {str(count): metric([row for row in all_buy_rows if row["date"] == date and row["race_buy_count"] == count]) for count in (1, 2, 3)} for date in DATES}
    pooled = {str(count): metric([row for row in all_buy_rows if row["race_buy_count"] == count]) for count in (1, 2, 3)}
    total = {key: sum(item[key] for item in coverage) for key in ("prediction_races", "mapped_races", "prediction_horses", "mapped_horses", "missing", "duplicate", "collision", "ambiguous")}
    h3_races, h3_buys = pooled["3"]["race_count"], pooled["3"]["BUY_count"]
    cumulative_h3_races, cumulative_h3_buys = 17 + h3_races, 51 + h3_buys
    band = "TOO_SMALL" if cumulative_h3_races <= 9 else "OBSERVATION_ONLY" if cumulative_h3_races <= 19 else "DIRECTIONAL_WATCH" if cumulative_h3_races <= 29 else "MEANINGFUL_VALIDATION" if cumulative_h3_races <= 49 else "STRONG_RETROSPECTIVE_EVIDENCE" if cumulative_h3_races <= 99 else "HIGH_CONFIDENCE_OPERATIONAL"
    one, two, three = pooled["1"]["Top3_rate"], pooled["2"]["Top3_rate"], pooled["3"]["Top3_rate"]
    if h3_races == 0 or three is None:
        h5_state = "H5_UNCHANGED_MIXED"
    elif three < one and three < two:
        h5_state = "H5_STRENGTHENED"
    elif three >= one and three >= two:
        h5_state = "H5_WEAKENED"
    else:
        h5_state = "H5_UNCHANGED_MIXED"
    if pooled["1"]["race_count"] == 0 or one is None:
        one_state = "ONE_BUY_MIXED_OBSERVATION"
    elif one >= two and one >= three:
        one_state = "ONE_BUY_SUPPORTIVE_OBSERVATION"
    elif one < two and one < three:
        one_state = "ONE_BUY_CONTRADICTORY_OBSERVATION"
    else:
        one_state = "ONE_BUY_MIXED_OBSERVATION"
    # Block five is reserved for a potentially decision-changing unresolved state only.
    fifth_gate = "FIFTH_BLOCK_JUSTIFIED" if h5_state == "H5_UNCHANGED_MIXED" or one_state == "ONE_BUY_MIXED_OBSERVATION" else "FIFTH_BLOCK_NOT_JUSTIFIED"
    fifth_reason = ("A final temporal block could materially distinguish an unresolved H5 or 1-BUY temporal pattern; it was not selected or run here."
                    if fifth_gate == "FIFTH_BLOCK_JUSTIFIED" else
                    "The current temporal direction is not unresolved enough for another Historical block to materially change this path; no fifth block was selected or run.")

    with (OUT / "h5_buy_rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "race_id", "horse_number", "race_buy_count", "valid_result", "actual_top3", "raw_result"])
        writer.writeheader(); writer.writerows(all_buy_rows)
    write("input_validation_summary.json", input_summary)
    write("result_validation_summary.json", result_summary)
    write("prediction_coverage_summary.json", {"total_prediction_races": total["prediction_races"], "by_date": coverage})
    write("result_mapping_summary.json", {"by_date": coverage, "total": total})
    write("h5_per_date.json", per_date)
    write("h5_june_pooled.json", pooled)
    write("h5_temporal_comparison.json", {"aug_development": {"1": "12/27 = 44.44%", "2": "10/26 = 38.46%", "3": "2/18 = 11.11%"},
                                             "july_h1": {"1": "7/16 = 43.75%", "2": "4/14 = 28.57%", "3": "8/21 = 38.10%"},
                                             "july_h2": {"1": "7/16 = 43.75%", "2": "5/14 = 35.71%", "3": "5/12 = 41.67%"},
                                             "june_block_1": pooled, "h5_temporal_direction": h5_state,
                                             "comparison_rule": "pre-registered natural race_buy_count categories only; no Trace field used"})
    write("h5_cumulative_evidence.json", {"CUMULATIVE_3BUY_RACE_COUNT": cumulative_h3_races, "CUMULATIVE_3BUY_BUY_COUNT": cumulative_h3_buys,
                                             "CURRENT_H5_EVIDENCE_BAND": band, "blocks_reported_separately": True})
    write("one_buy_secondary_observation.json", {"label": "PRE_REGISTERED_SECONDARY_OBSERVATION_FROM_JULY_H2_ONWARD", "confirmation_block_number": 2,
                                                   "state": one_state, "july_h2_confirmation_context": {"race_count": 16, "BUY_count": 16, "Top3_count": 7, "Top3_rate": 0.4375},
                                                   "june_block_1": pooled["1"], "CUMULATIVE_CONFIRMATION_ONLY_1BUY_RACE_COUNT": 16 + pooled["1"]["race_count"]})
    write("fifth_block_gate.json", {"FIFTH_BLOCK_ANALYSIS_GATE": fifth_gate, "reason": fifth_reason,
                                     "possible_decision_changes": {"A": "Whether an independently repeated 3-BUY collapse returns.", "B": "Whether normal/mixed 3-BUY behavior persists.", "C": "Whether 1-BUY temporal stability persists.", "D": "Whether 1-BUY temporal stability breaks."},
                                     "historical_ceiling": "maximum 5 temporal blocks or 50 independent 3-BUY races"})
    write("summary.json", {"evidence_classification": "RETROSPECTIVE_TEMPORAL_VALIDATION_BLOCK", "block": "JUNE_BLOCK_1", "final_decision": h5_state,
                             "CURRENT_H5_EVIDENCE_BAND": band, "ONE_BUY_SECONDARY_STATE": one_state, "FIFTH_BLOCK_ANALYSIS_GATE": fifth_gate,
                             "prediction_coverage": total["prediction_races"], "mapping_coverage": total["mapped_races"], "h5_june_pooled": pooled,
                             "production_changes": 0, "no_new_candidate_mining": True})
    (OUT / "report.md").write_text(
        "# H5 Temporal Stability — June Block 1\n\n"
        f"Primary state: `{h5_state}`. Cumulative 3-BUY evidence is `{band}` with {cumulative_h3_races} independent races and {cumulative_h3_buys} BUY horses.\n\n"
        f"June Block 1: 1-BUY {pooled['1']['Top3_count']}/{pooled['1']['valid_BUY_count']}, 2-BUY {pooled['2']['Top3_count']}/{pooled['2']['valid_BUY_count']}, 3-BUY {pooled['3']['Top3_count']}/{pooled['3']['valid_BUY_count']}.\n\n"
        f"One-BUY confirmation block #2: `{one_state}`. Fifth-block gate: `{fifth_gate}`. No Trace field was used as H5 decision logic; no Candidate or Production rule changed.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
