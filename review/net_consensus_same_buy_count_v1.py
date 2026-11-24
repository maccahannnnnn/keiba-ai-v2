"""Descriptive, saved-field-only net_consensus_score analysis."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "net_consensus_same_buy_count_v1"
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


def q(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values); index = (len(values) - 1) * p; low, high = math.floor(index), math.ceil(index)
    return values[low] if low == high else values[low] + (values[high] - values[low]) * (index - low)


def describe(rows: list[dict]) -> dict:
    values = [row["net_consensus_score"] for row in rows]
    if not values:
        return {"observation_count": 0, "independent_race_count": 0, "mean": None, "median": None, "minimum": None, "maximum": None, "quartiles": None}
    return {"observation_count": len(values), "independent_race_count": len({row["race_id"] for row in rows}),
            "mean": sum(values) / len(values), "median": q(values, .5), "minimum": min(values), "maximum": max(values),
            "quartiles": {"q1": q(values, .25), "q2": q(values, .5), "q3": q(values, .75)}}


def saved_outcomes(block: str) -> dict[tuple[str, int], dict]:
    result = {}
    with RESULT_CSVS[block].open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            key = (row["race_id"], int(row["horse_number"]))
            if key in result:
                raise RuntimeError(f"DUPLICATE_SAVED_RESULT:{block}:{key}")
            result[key] = {"valid_result": boolean(row["valid_result"]), "actual_top3": boolean(row["actual_top3"])}
    return result


def direction(success: list[dict], failure: list[dict]) -> str:
    contributing_races = len({r["race_id"] for r in success + failure})
    if contributing_races < 10:
        return "TOO_SMALL"
    if not success or not failure:
        return "NO_CLEAR_DIRECTION"
    a, b = describe(success)["median"], describe(failure)["median"]
    return "POSITIVE_DIRECTION" if a > b else "NEGATIVE_DIRECTION" if a < b else "NO_CLEAR_DIRECTION"


def evidence_band(race_count: int) -> str:
    return "TOO_SMALL" if race_count <= 9 else "OBSERVATION_ONLY" if race_count <= 19 else "DIRECTIONAL_WATCH" if race_count <= 29 else "MEANINGFUL_VALIDATION" if race_count <= 49 else "STRONG_RETROSPECTIVE_EVIDENCE" if race_count <= 99 else "HIGH_CONFIDENCE_OPERATIONAL"


def main() -> None:
    if OUT.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    source_validation, field_validation, observations = {}, {}, {count: {block: [] for block in BLOCKS} for count in (1, 2, 3)}
    total_races = total_valid_buys = total_abnormal = total_trace_horses = 0
    for block, dates in BLOCKS.items():
        outcomes = saved_outcomes(block); found_paths = []; mapped = set(); trace_statuses = set(); field_rows = 0
        for date in dates:
            root = PREDICTION_ROOTS[date]; paths = sorted(root.glob("race_*_prediction.json"))
            if not paths:
                raise RuntimeError(f"REQUIRED_ARTIFACT_MISSING:{date}:{root}")
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8")); race_id = payload.get("race_id")
                trace = payload.get("buy_gate_trace")
                if not race_id or not isinstance(trace, dict) or not isinstance(trace.get("horses"), list):
                    raise RuntimeError(f"TRACE_MISSING:{path}")
                trace_statuses.add(payload.get("trace_status", "NOT_FORMALLY_FROZEN_TRACE"))
                trace_by_number = {}
                for trace_horse in trace["horses"]:
                    number = trace_horse.get("horse_number"); score = trace_horse.get("net_consensus_score")
                    if number is None or score is None or not isinstance(score, (int, float)):
                        raise RuntimeError(f"NET_CONSENSUS_SCORE_MISSING_OR_NON_NUMERIC:{race_id}:{number}")
                    if int(number) in trace_by_number:
                        raise RuntimeError(f"DUPLICATE_TRACE_HORSE:{race_id}:{number}")
                    trace_by_number[int(number)] = round(float(score), 3); field_rows += 1
                ranked = payload.get("ranked_results")
                if not isinstance(ranked, list):
                    raise RuntimeError(f"RANKED_RESULTS_MISSING:{path}")
                for horse in ranked:
                    is_buy = horse.get("decision") == "BUY" or boolean(horse.get("buy"))
                    if not is_buy:
                        continue
                    number = int(horse["horse_number"]); key = (race_id, number)
                    if key not in outcomes:
                        raise RuntimeError(f"RESULT_MAPPING_MISSING:{block}:{key}")
                    if number not in trace_by_number:
                        raise RuntimeError(f"BUY_TRACE_MAPPING_MISSING:{race_id}:{number}")
                    if key in mapped:
                        raise RuntimeError(f"DUPLICATE_BUY_MAPPING:{block}:{key}")
                    mapped.add(key); outcome = outcomes[key]
                    if not outcome["valid_result"]:
                        total_abnormal += 1; continue
                    buy_count = int(payload.get("buy_count", 0))
                    if buy_count not in (1, 2, 3):
                        raise RuntimeError(f"UNEXPECTED_BUY_COUNT:{race_id}:{buy_count}")
                    observations[buy_count][block].append({"race_id": race_id, "net_consensus_score": trace_by_number[number], "actual_top3": outcome["actual_top3"]})
                    total_valid_buys += 1
                total_races += 1; total_trace_horses += len(trace_by_number); found_paths.append(str(path.relative_to(ROOT)))
        if mapped != set(outcomes):
            raise RuntimeError(f"RESULT_POPULATION_MISMATCH:{block}:{len(mapped)}:{len(outcomes)}")
        source_validation[block] = {"date_count": len(dates), "dates": list(dates), "prediction_artifact_count": len(found_paths),
                                    "saved_result_BUY_count": len(outcomes), "trace_statuses": sorted(str(x) for x in trace_statuses),
                                    "result_source": str(RESULT_CSVS[block].relative_to(ROOT)), "missing_artifacts": []}
        field_validation[block] = {"net_consensus_score_coverage": f"{field_rows}/{field_rows}", "net_consensus_score_numeric": True,
                                   "saved_value_used_without_recomputation": True, "result_field_used_to_derive_score": False,
                                   "threshold_optimization": False}

    outputs, layer_summary = {}, {}
    for layer, filename in ((1, "one_buy_per_block.json"), (2, "two_buy_per_block.json"), (3, "three_buy_per_block.json")):
        per_block = {}; directions = []
        for block, rows in observations[layer].items():
            success = [row for row in rows if row["actual_top3"]]
            failure = [row for row in rows if not row["actual_top3"]]
            item = {"SUCCESS_BUY": describe(success), "FAILURE_BUY": describe(failure), "direction": direction(success, failure),
                    "independence_note": "Horse observations may cluster within a race; independent race counts are descriptive evidence units."}
            per_block[block] = item; directions.append(item["direction"])
        meaningful = [x for x in directions if x != "TOO_SMALL"]
        positive, negative = meaningful.count("POSITIVE_DIRECTION"), meaningful.count("NEGATIVE_DIRECTION")
        total_layer_races = len({row["race_id"] for block_rows in observations[layer].values() for row in block_rows})
        if not meaningful:
            gate = "NET_CONSENSUS_TOO_SMALL_FOR_LAYER"
        elif positive >= 2 and negative == 0:
            gate = "NET_CONSENSUS_SUPPORTED_FOR_LAYER"
        else:
            gate = "NET_CONSENSUS_NOT_SUPPORTED_FOR_LAYER"
        outputs[layer] = per_block
        layer_summary[str(layer)] = {"directions_by_block": {block: per_block[block]["direction"] for block in BLOCKS},
                                     "meaningful_block_count": len(meaningful), "positive_direction_block_count": positive,
                                     "negative_direction_block_count": negative, "independent_race_count": total_layer_races,
                                     "evidence_band": evidence_band(total_layer_races), "analysis_gate": gate}
        write(filename, per_block)
    supported = [x for x in layer_summary.values() if x["analysis_gate"] == "NET_CONSENSUS_SUPPORTED_FOR_LAYER"]
    meaningful_layers = [x for x in layer_summary.values() if x["analysis_gate"] != "NET_CONSENSUS_TOO_SMALL_FOR_LAYER"]
    final = "NET_CONSENSUS_SUPPORTED" if len(supported) > 1 else "NET_CONSENSUS_PARTIALLY_SUPPORTED" if len(supported) == 1 else "NET_CONSENSUS_NOT_SUPPORTED" if meaningful_layers else "NET_CONSENSUS_TOO_SMALL"
    analysis_gate = {"layer_gates": {layer: value["analysis_gate"] for layer, value in layer_summary.items()},
                     "candidate_discussion": "REQUIRES_CLAUDE_CHATGPT_HUMAN_REVIEW" if final in ("NET_CONSENSUS_SUPPORTED", "NET_CONSENSUS_PARTIALLY_SUPPORTED") else "NOT_JUSTIFIED",
                     "next_improvement_axis": "REQUIRES_NEW_DESIGN_DECISION" if final == "NET_CONSENSUS_NOT_SUPPORTED" else "NOT_SELECTED_IN_THIS_TASK",
                     "candidate_created": False, "production_changes": 0}
    write("source_validation.json", {"total_source_date_count": 18, "TOTAL_ELIGIBLE_RACES": total_races, "by_block": source_validation})
    write("field_validation.json", {"total_trace_horse_records": total_trace_horses, "by_block": field_validation,
                                     "authoritative_field": "buy_gate_trace.horses[].net_consensus_score", "formula_recomputed": False,
                                     "only_variable_analyzed": "net_consensus_score", "abnormal_result_exclusions": total_abnormal})
    write("layer_direction_summary.json", layer_summary)
    write("evidence_summary.json", {"valid_BUY_horse_count": total_valid_buys, "independent_race_counts_by_layer": {layer: value["independent_race_count"] for layer, value in layer_summary.items()},
                                      "evidence_bands_by_layer": {layer: value["evidence_band"] for layer, value in layer_summary.items()}})
    write("analysis_gate.json", analysis_gate)
    write("summary.json", {"final_decision": final, "source_date_count": 18, "source_race_count": total_races, "valid_BUY_horse_count": total_valid_buys,
                             "abnormal_result_exclusions": total_abnormal, "layer_gates": analysis_gate["layer_gates"], "candidate_discussion": analysis_gate["candidate_discussion"],
                             "no_threshold_mining": True, "only_variable_analyzed": "net_consensus_score", "production_changes": 0})
    (OUT / "report.md").write_text(
        "# Same-BUY-Count Success/Failure — Net Consensus Score\n\n"
        f"Final descriptive decision: `{final}`. Saved net_consensus_score values were used without recomputation across 18 dates and {total_races} races.\n\n"
        "BUY-count is a control layer only. No threshold, Candidate, trace rerun, or Production behavior change was made.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
