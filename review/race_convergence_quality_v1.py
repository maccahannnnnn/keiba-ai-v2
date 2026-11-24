"""Descriptive Race Convergence Quality analysis from saved Prediction artifacts."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "race_convergence_quality_v1"

BLOCKS = {
    "JUNE_BLOCK_1": ("20260620", "20260621", "20260627", "20260628"),
    "JULY_H1": ("20260704", "20260705", "20260711", "20260712"),
    "JULY_H2": ("20260718", "20260719", "20260725", "20260726"),
    "AUGUST_DEVELOPMENT": ("20260801", "20260802", "20260808", "20260809", "20260815", "20260816"),
}
PREDICTION_ROOTS = {
    **{date: ROOT / "reports" / "h5_temporal_june_block1_v1" / f"prediction_{date}" for date in BLOCKS["JUNE_BLOCK_1"]},
    **{date: ROOT / "reports" / "cand_h5_001_july_4day_validation_v1" / f"prediction_{date}" for date in BLOCKS["JULY_H1"]},
    **{date: ROOT / "reports" / "h5_temporal_july_h2_v1" / f"prediction_{date}" for date in BLOCKS["JULY_H2"]},
    **{date: ROOT / "reports" / "buy_improvement_historical_6day_v1" / f"prediction_{date}" for date in ("20260801", "20260802", "20260808", "20260809")},
    "20260815": ROOT / "reports" / "prospective_analysis_20260815_v1",
    "20260816": ROOT / "reports" / "prospective_analysis_20260816_v1",
}
RESULT_CSVS = {
    "JUNE_BLOCK_1": ROOT / "reports" / "h5_temporal_june_block1_v1" / "h5_buy_rows.csv",
    "JULY_H1": ROOT / "reports" / "cand_h5_001_july_4day_validation_v1" / "h5_buy_rows.csv",
    "JULY_H2": ROOT / "reports" / "h5_temporal_july_h2_v1" / "h5_buy_rows.csv",
    "AUGUST_DEVELOPMENT": ROOT / "reports" / "buy_improvement_historical_6day_v1" / "buy_success_failure_analysis.csv",
}


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def boolean(value: object) -> bool:
    return value is True or str(value).lower() == "true"


def quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    low, high = math.floor(index), math.ceil(index)
    return ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def describe(rows: list[dict], race_key: str = "race_id") -> dict:
    values = [row["gap"] for row in rows]
    if not values:
        return {"count": 0, "independent_race_count": 0, "mean": None, "median": None, "minimum": None, "maximum": None, "quartiles": None}
    return {"count": len(values), "independent_race_count": len({row[race_key] for row in rows}),
            "mean": sum(values) / len(values), "median": quantile(values, .5), "minimum": min(values), "maximum": max(values),
            "quartiles": {"q1": quantile(values, .25), "q2": quantile(values, .5), "q3": quantile(values, .75)}}


def direction(success: list[dict], failure: list[dict]) -> str:
    if not success or not failure:
        return "NO_CLEAR_DIRECTION"
    s, f = describe(success)["median"], describe(failure)["median"]
    return "POSITIVE_DIRECTION" if s > f else "NEGATIVE_DIRECTION" if s < f else "NO_CLEAR_DIRECTION"


def quartiles(rows: list[dict], success_key: str) -> dict:
    values = [row["gap"] for row in rows]
    if not values:
        return {"boundaries": None, "bins": {}, "monotonicity": "NOT_AVAILABLE"}
    boundaries = [quantile(values, .25), quantile(values, .5), quantile(values, .75)]
    labels = ("Q1", "Q2", "Q3", "Q4")
    buckets = {label: [] for label in labels}
    for row in rows:
        gap = row["gap"]
        label = labels[0] if gap <= boundaries[0] else labels[1] if gap <= boundaries[1] else labels[2] if gap <= boundaries[2] else labels[3]
        buckets[label].append(row)
    output = {}
    rates = []
    for label in labels:
        bucket = buckets[label]
        successes = sum(boolean(row[success_key]) for row in bucket)
        rate = successes / len(bucket) if bucket else None
        rates.append(rate)
        output[label] = {"count": len(bucket), "independent_race_count": len({row["race_id"] for row in bucket}), "success_count": successes, "top3_rate": rate}
    usable = [rate for rate in rates if rate is not None]
    monotonicity = "BROADLY_INCREASING" if usable == sorted(usable) else "BROADLY_DECREASING" if usable == sorted(usable, reverse=True) else "NOT_MONOTONIC"
    return {"boundaries": {"q1": boundaries[0], "q2": boundaries[1], "q3": boundaries[2]}, "bins": output, "monotonicity": monotonicity,
            "rule": "Predictor-only linear quartiles; ties remain at the same boundary side. Descriptive only; no rule or cutoff is inferred."}


def load_outcomes(block: str) -> dict[tuple[str, int], dict]:
    outcomes = {}
    with RESULT_CSVS[block].open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            key = (row["race_id"], int(row["horse_number"]))
            if key in outcomes:
                raise RuntimeError(f"DUPLICATE_SAVED_RESULT:{block}:{key}")
            outcomes[key] = {"valid_result": boolean(row["valid_result"]), "actual_top3": boolean(row["actual_top3"])}
    return outcomes


def main() -> None:
    if OUT.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    all_block_races, source_validation, metric_validation = {}, {}, {}
    total_ties = {"adjacent_exact_score_ties": 0, "race_top_gap_exact_ties": 0, "buy_next_gap_exact_ties": 0}
    for block, dates in BLOCKS.items():
        outcomes = load_outcomes(block)
        records, found, missing, adjusted_count, ranks_checked = [], [], [], 0, 0
        for date in dates:
            root = PREDICTION_ROOTS[date]
            paths = sorted(root.glob("race_*_prediction.json"))
            if not paths:
                missing.append(str(root.relative_to(ROOT)))
                continue
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                race_id = payload.get("race_id")
                rows = payload.get("ranked_results")
                if not race_id or not isinstance(rows, list) or len(rows) < 2:
                    raise RuntimeError(f"ARTIFACT_STRUCTURE_INVALID:{path}")
                ordered = sorted(rows, key=lambda row: row.get("rank"))
                ranks = [row.get("rank") for row in ordered]
                if ranks != list(range(1, len(ordered) + 1)):
                    raise RuntimeError(f"RANKING_AMBIGUOUS:{race_id}")
                scores = []
                for row in ordered:
                    if row.get("adjusted_score") is None:
                        raise RuntimeError(f"ADJUSTED_SCORE_MISSING:{race_id}:{row.get('horse_number')}")
                    scores.append(float(row["adjusted_score"])); adjusted_count += 1
                ranks_checked += len(ordered)
                total_ties["adjacent_exact_score_ties"] += sum(scores[i] == scores[i + 1] for i in range(len(scores) - 1))
                top_gap = scores[0] - scores[1]
                if top_gap != float(ordered[0]["adjusted_score"]) - float(ordered[1]["adjusted_score"]):
                    raise RuntimeError(f"RACE_TOP_GAP_ARITHMETIC_FAIL:{race_id}")
                total_ties["race_top_gap_exact_ties"] += int(top_gap == 0)
                buys = []
                for position, row in enumerate(ordered):
                    is_buy = row.get("decision") == "BUY" or boolean(row.get("buy"))
                    if not is_buy:
                        continue
                    key = (race_id, int(row["horse_number"]))
                    if key not in outcomes:
                        raise RuntimeError(f"MISSING_SAVED_RESULT:{block}:{key}")
                    outcome = outcomes[key]
                    next_gap = None if position == len(ordered) - 1 else scores[position] - scores[position + 1]
                    if next_gap is not None and next_gap != float(row["adjusted_score"]) - float(ordered[position + 1]["adjusted_score"]):
                        raise RuntimeError(f"BUY_NEXT_GAP_ARITHMETIC_FAIL:{race_id}:{row['horse_number']}")
                    if next_gap == 0:
                        total_ties["buy_next_gap_exact_ties"] += 1
                    buys.append({"race_id": race_id, "horse_number": int(row["horse_number"]), "valid_result": outcome["valid_result"],
                                 "actual_top3": outcome["actual_top3"], "gap": next_gap})
                records.append({"race_id": race_id, "top_gap": top_gap, "buys": buys})
                found.append(str(path.relative_to(ROOT)))
        if missing:
            raise RuntimeError(f"REQUIRED_ARTIFACT_MISSING:{block}:{missing}")
        expected_outcome_keys = {key for record in records for key in [(record["race_id"], buy["horse_number"]) for buy in record["buys"]]}
        if expected_outcome_keys != set(outcomes):
            raise RuntimeError(f"SAVED_RESULT_POPULATION_MISMATCH:{block}:{len(expected_outcome_keys)}:{len(outcomes)}")
        all_block_races[block] = records
        source_validation[block] = {"dates": list(dates), "prediction_artifact_count": len(records), "prediction_artifacts_found": len(found),
                                    "saved_buy_result_count": len(outcomes), "missing_artifacts": missing,
                                    "result_source": str(RESULT_CSVS[block].relative_to(ROOT)), "result_source_used": "SAVED_ARTIFACT_ONLY"}
        metric_validation[block] = {"adjusted_score_coverage": f"{adjusted_count}/{adjusted_count}", "rank_field_checked": ranks_checked,
                                    "ranking_unambiguous": True, "direct_race_top_gap_arithmetic": "PASS", "direct_buy_next_gap_arithmetic": "PASS",
                                    "result_fields_used_in_gap_formula": False, "threshold_optimization": False}

    race_output, buy_output, race_quartiles, buy_quartiles, temporal = {}, {}, {}, {}, {}
    total_eligible, total_valid_buys = 0, 0
    for block, records in all_block_races.items():
        total_eligible += len(records)
        success, failure, unclassified = [], [], []
        buy_success, buy_failure, not_available = [], [], []
        for record in records:
            valid_buys = [buy for buy in record["buys"] if buy["valid_result"]]
            if not valid_buys:
                unclassified.append({"race_id": record["race_id"], "gap": record["top_gap"]})
            elif any(buy["actual_top3"] for buy in valid_buys):
                success.append({"race_id": record["race_id"], "gap": record["top_gap"], "actual_top3": True})
            else:
                failure.append({"race_id": record["race_id"], "gap": record["top_gap"], "actual_top3": False})
            for buy in valid_buys:
                total_valid_buys += 1
                if buy["gap"] is None:
                    not_available.append(buy); continue
                target = buy_success if buy["actual_top3"] else buy_failure
                target.append({"race_id": buy["race_id"], "gap": buy["gap"], "actual_top3": buy["actual_top3"]})
        race_output[block] = {"TOTAL_ELIGIBLE_RACES": len(records), "BUY_SUCCESS_RACES": describe(success), "BUY_FAILURE_ONLY_RACES": describe(failure),
                              "BUY_ABSENT_OR_INVALID_ONLY_RACES": describe(unclassified), "direction": direction(success, failure)}
        buy_output[block] = {"BUY_TOP3": describe(buy_success), "BUY_VALID_NON_TOP3": describe(buy_failure), "NOT_AVAILABLE_FINAL_RANKED_BUY": len(not_available),
                             "direction": direction(buy_success, buy_failure), "independence_note": "BUY observations may cluster within a race; independent race counts are reported but horse counts are not evidence-strength units."}
        classified_races = success + failure
        race_quartiles[block] = quartiles(classified_races, "actual_top3")
        buy_quartiles[block] = quartiles(buy_success + buy_failure, "actual_top3")
        temporal[block] = {"RACE_TOP_GAP_DIRECTION": race_output[block]["direction"], "BUY_NEXT_GAP_DIRECTION": buy_output[block]["direction"],
                           "BUY_SUCCESS_RACE_COUNT": len(success), "BUY_FAILURE_ONLY_RACE_COUNT": len(failure)}

    directions = [item["RACE_TOP_GAP_DIRECTION"] for item in temporal.values()]
    positive, negative = directions.count("POSITIVE_DIRECTION"), directions.count("NEGATIVE_DIRECTION")
    if positive >= 2 and negative == 0:
        final = "CONVERGENCE_QUALITY_SUPPORTED"
    elif positive + negative <= 1:
        final = "CONVERGENCE_QUALITY_OBSERVATION_ONLY"
    else:
        final = "CONVERGENCE_QUALITY_NOT_SUPPORTED"
    evidence_band = "TOO_SMALL" if total_eligible <= 9 else "OBSERVATION_ONLY" if total_eligible <= 19 else "DIRECTIONAL_WATCH" if total_eligible <= 29 else "MEANINGFUL_VALIDATION" if total_eligible <= 49 else "STRONG_RETROSPECTIVE_EVIDENCE" if total_eligible <= 99 else "HIGH_CONFIDENCE_OPERATIONAL"
    gate = {"analysis_gate": "CANDIDATE_DISCUSSION_MAY_BE_JUSTIFIED_LATER" if final == "CONVERGENCE_QUALITY_SUPPORTED" else "CLOSE_CONVERGENCE_PATH; SAME_BUY_COUNT_SUCCESS_FAILURE_COMPARISON_NEXT",
            "candidate_rule_created": False, "production_change": 0}
    write("source_artifact_validation.json", source_validation)
    write("derived_metric_validation.json", {"per_block": metric_validation, "exact_score_ties": total_ties,
                                               "metric_formula": {"RACE_TOP_GAP": "rank1.adjusted_score - rank2.adjusted_score", "BUY_NEXT_GAP": "BUY adjusted_score - next lower-ranked adjusted_score"},
                                               "no_result_field_enters_metric_calculation": True, "no_threshold_optimization": True})
    write("race_top_gap_per_block.json", race_output); write("buy_next_gap_per_block.json", buy_output)
    write("race_top_gap_quartiles.json", race_quartiles); write("buy_next_gap_quartiles.json", buy_quartiles)
    write("temporal_direction_summary.json", {"by_block": temporal, "positive_direction_block_count": positive, "negative_direction_block_count": negative,
                                                "consistency": "CONSISTENT_POSITIVE" if positive >= 2 and negative == 0 else "INCONSISTENT_OR_NO_CLEAR"})
    write("analysis_gate.json", gate)
    write("summary.json", {"final_decision": final, "TOTAL_ELIGIBLE_RACES": total_eligible, "total_valid_BUY_count": total_valid_buys,
                             "CURRENT_EVIDENCE_BAND": evidence_band, "exact_score_ties": total_ties, "analysis_gate": gate["analysis_gate"],
                             "no_threshold_mining": True, "production_changes": 0})
    (OUT / "report.md").write_text(
        "# Race Convergence Quality Analysis\n\n"
        f"Final descriptive decision: `{final}`. Eligible races: {total_eligible}; valid BUY horses: {total_valid_buys}; evidence band: `{evidence_band}`.\n\n"
        "Only saved `ranked_results[].adjusted_score`, saved rank, and saved BUY result semantics were used. No gap threshold, Candidate rule, or Production behavior was created or changed.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
