"""Post-prediction, frozen-category H5 July H2 temporal validation only."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_daily_result_list_schema_v2_validator import validate_source_pair


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "h5_temporal_july_h2_v1"
INPUT = ROOT / "data" / "raw" / "prediction_input"
RESULTS = ROOT / "data" / "raw" / "target" / "daily_result_list"
DATES = ("20260718", "20260719", "20260725", "20260726")
VENUES = {"sapporo": "札幌", "niigata": "新潟", "chuukyou": "中京", "hakodate": "函館", "fukushima": "福島", "kokura": "小倉"}
ABNORMAL = {"中止", "除外", "取消", "失格"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, data: object) -> None:
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def metric(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    top3 = [row for row in valid if row["actual_top3"]]
    return {
        "race_count": len({row["race_id"] for row in rows}),
        "BUY_count": len(rows), "valid_BUY_count": len(valid),
        "Top3_count": len(top3), "failure_count": len(valid) - len(top3),
        "Top3_rate": len(top3) / len(valid) if valid else None,
    }


def result_rows(date: str) -> tuple[dict[tuple[str, int], list[str]], dict]:
    primary = RESULTS / f"馬番順着順_{date}.csv"
    auxiliary = RESULTS / f"着順馬番_{date}.csv"
    validation = validate_source_pair(primary, auxiliary, date)
    if validation["status"] != "PASS":
        raise RuntimeError(f"RESULT_SCHEMA_FAIL:{date}")
    with primary.open(encoding="cp932", newline="") as source:
        raw_rows = list(csv.reader(source))
    index = {(row[1], int(row[2])): row for row in raw_rows}
    if len(index) != len(raw_rows):
        raise RuntimeError(f"DUPLICATE_RESULT_RACE:{date}")
    return index, validation


def main() -> None:
    if not OUT.exists() or (OUT / "summary.json").exists():
        raise RuntimeError("OUTPUT_STATE_INVALID")
    input_summary, result_summary, coverage, all_buy_rows = {}, {}, [], []
    for date in DATES:
        paths = {kind: INPUT / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
        bundle = TargetBulkPredictionInputAdapterV1().load(paths["DG"], paths["DE"], paths["DS"])
        if bundle.date != date:
            raise RuntimeError(f"TARGET_DATE_MISMATCH:{date}:{bundle.date}")
        result_index, result_validation = result_rows(date)
        artifacts = sorted((OUT / f"prediction_{date}").glob("race_*_prediction.json"))
        artifact_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in artifacts]
        race_ids = [payload["race_id"] for payload in artifact_payloads]
        if len(race_ids) != len(set(race_ids)):
            raise RuntimeError(f"DUPLICATE_PREDICTION_RACE:{date}")
        if set(race_ids) != set(bundle.races):
            raise RuntimeError(f"PREDICTION_POPULATION_MISMATCH:{date}")
        date_buy_rows = []
        for payload in artifact_payloads:
            race_id = payload["race_id"]
            parts = race_id.split("_")
            canonical_key = (VENUES[parts[-2]], int(parts[-1][:-1]))
            result = result_index.get(canonical_key)
            if result is None:
                raise RuntimeError(f"MISSING_RESULT_RACE:{race_id}")
            for horse in payload["ranked_results"]:
                horse_number = int(horse["horse_number"])
                value_index = 11 + horse_number
                if value_index >= len(result):
                    raise RuntimeError(f"MISSING_RESULT_HORSE:{race_id}:{horse_number}")
                if horse.get("decision") != "BUY":
                    continue
                raw_finish = result[value_index]
                valid = raw_finish.isdigit() and int(raw_finish) > 0
                if not valid and raw_finish not in ABNORMAL:
                    raise RuntimeError(f"UNKNOWN_FINISH_STATUS:{race_id}:{horse_number}:{raw_finish}")
                date_buy_rows.append({"date": date, "race_id": race_id, "horse_number": horse_number,
                                      "race_buy_count": payload["buy_count"], "valid_result": valid,
                                      "actual_top3": bool(valid and int(raw_finish) <= 3), "raw_result": raw_finish})
        eligible_horses = sum(len(payload["ranked_results"]) for payload in artifact_payloads)
        input_summary[date] = {"adapter_status": "PASS", "target_date": bundle.date,
                               "raw_race_count": len(bundle.races), "eligible_race_count": len(artifact_payloads),
                               "eligible_horse_count": eligible_horses,
                               "raw_sha256": {kind: sha256(path) for kind, path in paths.items()}}
        result_summary[date] = {"status": "PASS", "race_set_count": result_validation["race_set_count"],
                                "primary_width": result_validation["source_d_primary"]["raw_column_count"],
                                "auxiliary_width": result_validation["source_c_auxiliary"]["raw_column_count"]}
        coverage.append({"date": date, "prediction_races": len(artifact_payloads), "mapped_races": len(artifact_payloads),
                         "prediction_horses": eligible_horses, "mapped_horses": eligible_horses,
                         "missing": 0, "duplicate": 0, "collision": 0, "ambiguous": 0,
                         "abnormal_BUY_exclusions": sum(not row["valid_result"] for row in date_buy_rows)})
        all_buy_rows.extend(date_buy_rows)

    per_date = {date: {str(count): metric([row for row in all_buy_rows if row["date"] == date and row["race_buy_count"] == count]) for count in (1, 2, 3)} for date in DATES}
    pooled = {str(count): metric([row for row in all_buy_rows if row["race_buy_count"] == count]) for count in (1, 2, 3)}
    total = {key: sum(item[key] for item in coverage) for key in ("prediction_races", "mapped_races", "prediction_horses", "mapped_horses", "missing", "duplicate", "collision", "ambiguous")}
    development = {"block": "AUG_DEVELOPMENT", "categories": {"1": "12/27 = 44.44%", "2": "10/26 = 38.46%", "3": "2/18 = 11.11%"}, "target_category_races": 6, "target_category_BUY": 18}
    july_h1 = {"block": "JULY_H1", "categories": {"1": "7/16 = 43.75%", "2": "4/14 = 28.57%", "3": "8/21 = 38.10%"}, "target_category_races": 7, "target_category_BUY": 21}
    h2_races, h2_buys = pooled["3"]["race_count"], pooled["3"]["BUY_count"]
    cumulative_races, cumulative_buys = 13 + h2_races, 39 + h2_buys
    band = "TOO_SMALL" if cumulative_races <= 9 else "OBSERVATION_ONLY" if cumulative_races <= 19 else "DIRECTIONAL_WATCH" if cumulative_races <= 29 else "MEANINGFUL_VALIDATION" if cumulative_races <= 49 else "STRONG_RETROSPECTIVE_EVIDENCE" if cumulative_races <= 99 else "HIGH_CONFIDENCE_OPERATIONAL"

    # The state is deliberately derived only from the predeclared relative 1/2/3 category comparison.
    h2_three, h2_one, h2_two = pooled["3"]["Top3_rate"], pooled["1"]["Top3_rate"], pooled["2"]["Top3_rate"]
    if h2_races == 0 or h2_three is None:
        h5_state = "H5_UNCHANGED_MIXED"
    elif h2_three < h2_one and h2_three < h2_two:
        h5_state = "H5_STRENGTHENED"
    elif h2_three >= h2_one and h2_three >= h2_two:
        h5_state = "H5_WEAKENED"
    else:
        h5_state = "H5_UNCHANGED_MIXED"
    if pooled["1"]["race_count"] == 0 or h2_one is None:
        one_buy_state = "ONE_BUY_MIXED_OBSERVATION"
    elif h2_one >= h2_two and h2_one >= h2_three:
        one_buy_state = "ONE_BUY_SUPPORTIVE_OBSERVATION"
    elif h2_one < h2_two and h2_one < h2_three:
        one_buy_state = "ONE_BUY_CONTRADICTORY_OBSERVATION"
    else:
        one_buy_state = "ONE_BUY_MIXED_OBSERVATION"
    continuation = "JUNE_BLOCK_JUSTIFIED" if cumulative_races < 20 or h5_state == "H5_UNCHANGED_MIXED" else "JUNE_BLOCK_NOT_JUSTIFIED"

    with (OUT / "h5_buy_rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "race_id", "horse_number", "race_buy_count", "valid_result", "actual_top3", "raw_result"])
        writer.writeheader(); writer.writerows(all_buy_rows)
    write("input_validation_summary.json", input_summary)
    write("result_validation_summary.json", result_summary)
    write("prediction_coverage_summary.json", {"total_prediction_races": total["prediction_races"], "by_date": coverage})
    write("result_mapping_summary.json", {"by_date": coverage, "total": total})
    write("h5_per_date.json", per_date)
    write("h5_july_h2_pooled.json", pooled)
    write("h5_temporal_comparison.json", {"aug_development": development, "july_h1": july_h1, "july_h2": pooled,
                                             "h5_temporal_direction": h5_state,
                                             "comparison_rule": "pre-registered natural race_buy_count categories only; no Trace field used"})
    write("h5_cumulative_evidence.json", {"CUMULATIVE_TARGET_CATEGORY_RACE_COUNT": cumulative_races,
                                             "CUMULATIVE_TARGET_CATEGORY_BUY_COUNT": cumulative_buys,
                                             "CURRENT_H5_EVIDENCE_BAND": band,
                                             "blocks_reported_separately": True})
    write("one_buy_secondary_observation.json", {"label": "PRE_REGISTERED_SECONDARY_OBSERVATION_FROM_JULY_H2_ONWARD",
                                                   "confirmation_block_number": 1, "state": one_buy_state,
                                                   "july_h2_one_buy": pooled["1"], "discovery_context_only": {"aug": "12/27 = 44.44%", "july_h1": "7/16 = 43.75%"}})
    write("continuation_gate.json", {"JUNE_CONTINUATION_GATE": continuation,
                                       "reason": "One later mechanically selected block could add independent 3-BUY races; it was not selected or run in this task.",
                                       "historical_ceiling": "maximum 5 temporal blocks or 50 independent target-category races"})
    write("summary.json", {"evidence_classification": "RETROSPECTIVE_TEMPORAL_VALIDATION_BLOCK", "block": "JULY_H2",
                             "final_decision": h5_state, "CURRENT_H5_EVIDENCE_BAND": band,
                             "ONE_BUY_SECONDARY_STATE": one_buy_state, "JUNE_CONTINUATION_GATE": continuation,
                             "prediction_coverage": total["prediction_races"], "mapping_coverage": total["mapped_races"],
                             "h5_july_h2_pooled": pooled, "production_changes": 0, "no_new_candidate_mining": True})
    (OUT / "report.md").write_text(
        "# H5 Temporal Stability — July H2 Validation Block\n\n"
        f"Primary state: `{h5_state}`. Cumulative H5 evidence is `{band}` with {cumulative_races} independent 3-BUY races and {cumulative_buys} BUY horses across Aug, July H1, and July H2.\n\n"
        f"July H2: 1-BUY {pooled['1']['Top3_count']}/{pooled['1']['valid_BUY_count']}, 2-BUY {pooled['2']['Top3_count']}/{pooled['2']['valid_BUY_count']}, 3-BUY {pooled['3']['Top3_count']}/{pooled['3']['valid_BUY_count']}.\n\n"
        f"One-BUY secondary state: `{one_buy_state}`. June continuation gate: `{continuation}`. No Trace field was used as H5 decision logic; no Candidate or Production rule changed.\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
