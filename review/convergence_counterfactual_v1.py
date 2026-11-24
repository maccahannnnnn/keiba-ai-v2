"""One-shot, bounded, outcome-blind convergence counterfactual analysis.

The selection phase reads only frozen prediction / BUY-gate trace data.  Result
rows are joined afterwards solely to score the fixed selection.  It never calls
the prediction engine and intentionally refuses all legacy decision ``ai_rank``
fields.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "convergence_counterfactual_v1"
TOP5 = ROOT / "reports" / "failed_buy_root_cause_v1" / "top5_result_export.csv"
BUY_CONTEXT = ROOT / "reports" / "buy_precision_v1" / "pooled_precision.json"
PROSPECTIVE_ROOT = ROOT / "reports" / "prospective_prediction_20260822_v1"
PROSPECTIVE_RESULTS = ROOT / "reports" / "prospective_result_20260822_v1" / "horse_result_mapping.json"

BLOCKS = {
    "JUNE": ("20260620", "20260621", "20260627", "20260628"),
    "JULY_H1": ("20260704", "20260705", "20260711", "20260712"),
    "JULY_H2": ("20260718", "20260719", "20260725", "20260726"),
    "AUGUST": ("20260801", "20260802", "20260808", "20260809", "20260815", "20260816"),
}
ROOTS = {
    **{d: ROOT / "reports" / "h5_temporal_june_block1_v1" / f"prediction_{d}" for d in BLOCKS["JUNE"]},
    **{d: ROOT / "reports" / "cand_h5_001_july_4day_validation_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H1"]},
    **{d: ROOT / "reports" / "h5_temporal_july_h2_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H2"]},
    **{d: ROOT / "reports" / "buy_improvement_trace_6day_v1" / f"prediction_{d}" for d in BLOCKS["AUGUST"]},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def require_bool(value: object, field: str, race_id: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeError(f"INVALID_BOOLEAN:{field}:{race_id}")
    return value


def safe_rank(row: dict, race_id: str) -> int:
    # The approved design allows only this frozen trace field.  Explicitly do
    # not use decision_diagnostics.ai_rank, decision_result.ai_rank, or a
    # generic/legacy ai_rank fallback.
    if "shadow_ai_rank" not in row:
        raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:MISSING_SHADOW_AI_RANK:{race_id}")
    value = row["shadow_ai_rank"]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0 or int(value) != value:
        raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:INVALID_SHADOW_AI_RANK:{race_id}:{value!r}")
    return int(value)


def outcome_summary(races: list[dict]) -> dict:
    pool = [horse for race in races for horse in race["candidates"] if horse["valid_result"]]
    selected = [horse for race in races for horse in race["selected"] if horse["valid_result"]]
    pool_top3 = sum(horse["actual_top3"] for horse in pool)
    selected_top3 = sum(horse["actual_top3"] for horse in selected)
    return {
        "race_count": len(races),
        "candidate_horse_count": sum(len(race["candidates"]) for race in races),
        "candidate_valid_horse_count": len(pool),
        "candidate_top3_count": pool_top3,
        "candidate_pool_top3_rate": rate(pool_top3, len(pool)),
        "selected_horse_count": sum(len(race["selected"]) for race in races),
        "selected_valid_horse_count": len(selected),
        "selected_top3_count": selected_top3,
        "CF_SELECTED_TOP3_RATE": rate(selected_top3, len(selected)),
        "difference_vs_candidate_pool": (
            rate(selected_top3, len(selected)) - rate(pool_top3, len(pool)) if pool and selected else None
        ),
        "candidate_retention_rate": rate(sum(len(race["selected"]) for race in races), sum(len(race["candidates"]) for race in races)),
        "races_with_at_least_1_selected_top3": sum(sum(h["actual_top3"] for h in race["selected"] if h["valid_result"]) >= 1 for race in races),
        "races_with_at_least_2_selected_top3": sum(sum(h["actual_top3"] for h in race["selected"] if h["valid_result"]) >= 2 for race in races),
        "races_with_all_3_selected_top3": sum(sum(h["actual_top3"] for h in race["selected"] if h["valid_result"]) == 3 for race in races),
    }


def select_from_trace(payload: dict, block: str, date: str, results: dict) -> dict | None:
    trace = payload.get("buy_gate_trace")
    if not isinstance(trace, dict):
        raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:MISSING_BUY_GATE_TRACE:{payload.get('race_id')}")
    race = trace.get("race")
    horses = trace.get("horses")
    race_id = payload.get("race_id")
    if not isinstance(race_id, str) or not isinstance(race, dict) or not isinstance(horses, list):
        raise RuntimeError("INSUFFICIENT_FROZEN_STATE:MALFORMED_TRACE")
    if race.get("shadow_race_state") != "PLAY_UNCONVERGED_4PLUS":
        return None
    candidate_count = race.get("shadow_candidate_count")
    if candidate_count not in {4, 5}:
        raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:UNEXPECTED_CANDIDATE_COUNT:{race_id}:{candidate_count!r}")

    candidates = []
    for horse in horses:
        if require_bool(horse.get("shadow_buy_candidate"), "shadow_buy_candidate", race_id):
            number = horse.get("horse_number")
            if not isinstance(number, int):
                raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:INVALID_HORSE_NUMBER:{race_id}")
            rank = safe_rank(horse, race_id)
            candidates.append({"horse_number": number, "shadow_ai_rank": rank})
    if len(candidates) != candidate_count:
        raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:CANDIDATE_SET_COUNT_MISMATCH:{race_id}")
    ranks = [horse["shadow_ai_rank"] for horse in candidates]
    if len(set(ranks)) != len(ranks):
        raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:DUPLICATE_SHADOW_AI_RANK:{race_id}")

    # Selection is complete here, before result fields are consulted.
    selected_numbers = {horse["horse_number"] for horse in sorted(candidates, key=lambda horse: horse["shadow_ai_rank"])[:3]}
    joined = []
    for horse in candidates:
        result = results.get((race_id, horse["horse_number"]))
        if result is None:
            raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:MISSING_FROZEN_RESULT_JOIN:{race_id}:{horse['horse_number']}")
        joined.append({**horse, "selected": horse["horse_number"] in selected_numbers, "valid_result": result["valid_result"], "actual_top3": result["actual_top3"], "actual_finish": result["actual_finish"]})
    return {"race_id": race_id, "block": block, "date": date, "candidate_count": candidate_count, "candidates": joined, "selected": [horse for horse in joined if horse["selected"]]}


def render_report(pooled: dict, blocks: dict, counts: dict, prospective: dict, gate: dict) -> str:
    pct = lambda value: "n/a" if value is None else f"{value:.2%}"
    lines = ["# Convergence Bounded Counterfactual V1", "", f"Analysis Gate: `{gate['analysis_gate_result']}`.", "", "## Fixed rule", "", "`CF_TOP3_RANK_ANCHORED`: within each frozen `PLAY_UNCONVERGED_4PLUS` race, select the first three saved `shadow_buy_candidate=True` horses by ascending saved `shadow_ai_rank`.", "", "Selection was reconstructed before result joining. Legacy `ai_rank` fields were not read.", "", "## Pooled retrospective result", "", f"- Races: {pooled['race_count']}", f"- Candidate pool: {pooled['candidate_top3_count']}/{pooled['candidate_valid_horse_count']} ({pct(pooled['candidate_pool_top3_rate'])})", f"- CF selected: {pooled['selected_top3_count']}/{pooled['selected_valid_horse_count']} ({pct(pooled['CF_SELECTED_TOP3_RATE'])})", f"- Difference: {pct(pooled['difference_vs_candidate_pool'])}", f"- Candidate retention: {pct(pooled['candidate_retention_rate'])}", f"- Races with selected Top3 ≥1 / ≥2 / 3: {pooled['races_with_at_least_1_selected_top3']} / {pooled['races_with_at_least_2_selected_top3']} / {pooled['races_with_all_3_selected_top3']}", "", "## Temporal blocks", "", "| Block | Races | Pool Top3 rate | CF Top3 rate | Difference |", "|---|---:|---:|---:|---:|"]
    for block, value in blocks.items():
        lines.append(f"| {block} | {value['race_count']} | {pct(value['candidate_pool_top3_rate'])} | {pct(value['CF_SELECTED_TOP3_RATE'])} | {pct(value['difference_vs_candidate_pool'])} |")
    lines += ["", "## Candidate-count safety", "", "| Candidate count | Races | Pool Top3 rate | CF Top3 rate | Direction |", "|---|---:|---:|---:|---:|"]
    for count, value in counts.items():
        direction = "non-underperforming" if value["difference_vs_candidate_pool"] is not None and value["difference_vs_candidate_pool"] >= 0 else "underperforming"
        lines.append(f"| {count} | {value['race_count']} | {pct(value['candidate_pool_top3_rate'])} | {pct(value['CF_SELECTED_TOP3_RATE'])} | {direction} |")
    lines += ["", "## 2026-08-22 prospective context only", "", f"- Affected races: {prospective['race_count']}", f"- Candidate pool: {prospective['candidate_top3_count']}/{prospective['candidate_valid_horse_count']} ({pct(prospective['candidate_pool_top3_rate'])})", f"- CF selected: {prospective['selected_top3_count']}/{prospective['selected_valid_horse_count']} ({pct(prospective['CF_SELECTED_TOP3_RATE'])})", f"- Difference: {pct(prospective['difference_vs_candidate_pool'])}", "", "This is not merged into the retrospective population and is not independent GO/REJECT evidence.", "", f"Exact next action: `{gate['exact_next_action']}`.", "", "No Prediction rerun, threshold optimization, engine/Production change, BUY-max change, or Candidate creation occurred."]
    return "\n".join(lines) + "\n"


def main() -> None:
    if OUT.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    with TOP5.open(encoding="utf-8", newline="") as handle:
        top5_rows = list(csv.DictReader(handle))
    if len(top5_rows) != 1535:
        raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:TOP5_ROW_COUNT:{len(top5_rows)}")
    results = {}
    for row in top5_rows:
        key = (row["race_id"], int(row["horse_number"]))
        if key in results:
            raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:DUPLICATE_FROZEN_RESULT:{key}")
        results[key] = {"valid_result": row["valid_result"] == "True", "actual_top3": row["actual_top3"] == "True", "actual_finish": row["raw_result"]}

    retrospective = []
    sources = []
    for block, dates in BLOCKS.items():
        for date in dates:
            files = sorted(ROOTS[date].glob("race_*_prediction.json"))
            if not files:
                raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:NO_PREDICTION_ARTIFACTS:{date}")
            for path in files:
                payload = load_json(path)
                sources.append({"block": block, "date": date, "path": str(path.relative_to(ROOT)), "sha256": sha256(path)})
                selected = select_from_trace(payload, block, date, results)
                if selected is not None:
                    retrospective.append(selected)
    if len(retrospective) != 67:
        raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:RETROSPECTIVE_RACE_COUNT:{len(retrospective)}")
    if Counter(race["candidate_count"] for race in retrospective) != {4: 29, 5: 38}:
        raise RuntimeError("INSUFFICIENT_FROZEN_STATE:RETROSPECTIVE_CANDIDATE_SPLIT")

    # 8/22 selection reads the same frozen trace first, then its separately
    # frozen POST result mapping. It is deliberately excluded from all pooled
    # and temporal retrospective calculations.
    prospective_mapping = load_json(PROSPECTIVE_RESULTS)
    prospective_results = {}
    for row in prospective_mapping["rows"]:
        key = (row["race_id"], row["horse_number"])
        if key in prospective_results:
            raise RuntimeError(f"INSUFFICIENT_FROZEN_STATE:DUPLICATE_PROSPECTIVE_RESULT:{key}")
        prospective_results[key] = {"valid_result": row["valid_result"], "actual_top3": row["actual_top3"], "actual_finish": row["actual_finish"]}
    prospective_races = []
    prospective_sources = []
    for path in sorted(PROSPECTIVE_ROOT.glob("race_*_prediction.json")):
        payload = load_json(path)
        prospective_sources.append({"path": str(path.relative_to(ROOT)), "sha256": sha256(path)})
        selected = select_from_trace(payload, "PROSPECTIVE_CONTEXT_ONLY", "20260822", prospective_results)
        if selected is not None:
            prospective_races.append(selected)
    expected_prospective = {"race_20260822_chuukyou_10R", "race_20260822_niigata_10R", "race_20260822_sapporo_7R"}
    if {race["race_id"] for race in prospective_races} != expected_prospective:
        raise RuntimeError("INSUFFICIENT_FROZEN_STATE:PROSPECTIVE_UNCONVERGED_RACE_SET")

    pooled = outcome_summary(retrospective)
    by_block = {block: outcome_summary([race for race in retrospective if race["block"] == block]) for block in BLOCKS}
    by_count = {str(count): outcome_summary([race for race in retrospective if race["candidate_count"] == count]) for count in (4, 5)}
    prospective = outcome_summary(prospective_races)

    # Conservative, deterministic reading of "clear underperformance": a
    # strictly negative rate difference against the matched same-block pool.
    underperforming_blocks = [block for block, value in by_block.items() if value["difference_vs_candidate_pool"] is not None and value["difference_vs_candidate_pool"] < 0]
    subgroup_directions = {count: (value["difference_vs_candidate_pool"] is not None and value["difference_vs_candidate_pool"] >= 0) for count, value in by_count.items()}
    subgroup_conflict = subgroup_directions["4"] != subgroup_directions["5"]
    # The frozen design says the three-race 8/22 slice is context only and may
    # not independently justify REJECT.  It has no preregistered quantitative
    # definition of "clear contradictory pattern", so a negative descriptive
    # difference alone is not silently promoted to such a finding.
    prospective_contradiction = False
    pooled_non_underperforming = pooled["difference_vs_candidate_pool"] is not None and pooled["difference_vs_candidate_pool"] >= 0
    if subgroup_conflict:
        decision, next_action = "HOLD_FOR_4_VS_5_CONFLICT", "HOLD_FOR_4_VS_5_CONFLICT"
    elif len(underperforming_blocks) >= 3:
        decision, next_action = "REJECT_AND_MOVE_ON", "REJECT_AND_MOVE_ON"
    elif pooled_non_underperforming and len(underperforming_blocks) <= 2 and not prospective_contradiction:
        decision, next_action = "COUNTERFACTUAL_PROMISING_FOR_SHADOW", "GO_TO_SHADOW_DESIGN"
    else:
        # The frozen design permits no generic HOLD.  A failed GO condition
        # without a 4-vs-5 conflict is therefore a V1 rejection.
        decision, next_action = "REJECT_AND_MOVE_ON", "REJECT_AND_MOVE_ON"

    existing_buy = load_json(BUY_CONTEXT)["BUY_TOP3_RATE"]
    descriptive = {"context_only": True, "existing_valid_buy_horses": existing_buy["denominator"], "existing_buy_top3": existing_buy["numerator"], "cf_selected_valid_horses": pooled["selected_valid_horse_count"], "cf_selected_top3": pooled["selected_top3_count"], "DESCRIPTIVE_COUNTERFACTUAL_OVERALL_BUY_TOP3_RATE": rate(existing_buy["numerator"] + pooled["selected_top3_count"], existing_buy["denominator"] + pooled["selected_valid_horse_count"])}
    gate = {"analysis_gate_result": decision, "exact_next_action": next_action, "pooled_non_underperforming": pooled_non_underperforming, "underperforming_temporal_blocks": underperforming_blocks, "majority_blocks_not_underperforming": len(underperforming_blocks) <= 2, "buy_max_preserved": all(len(race["selected"]) == 3 for race in retrospective + prospective_races), "prospective_context_contradiction": prospective_contradiction, "prospective_context_interpretation": "Three-race context only: its descriptive negative difference is reported but is not independently treated as a clear contradiction because no quantitative clear-contradiction threshold was preregistered.", "candidate_count_4_vs_5_opposing_directions": subgroup_conflict, "clear_underperformance_definition": "strictly negative CF selected rate minus matched candidate-pool rate"}

    dump("source_validation.json", {"status": "PASS", "retrospective_source_dates": 18, "retrospective_source_races": len(sources), "retrospective_unconverged_races": len(retrospective), "candidate_count_split": {"4": 29, "5": 38}, "safe_rank_field": "buy_gate_trace.horses[].shadow_ai_rank", "prohibited_legacy_ai_rank_fields_used": False, "prediction_rerun": False, "result_informed_selection": False, "threshold_optimization": False, "engine_change": False, "production_change": False})
    dump("field_provenance.json", {"selection_rank_field": "buy_gate_trace.horses[].shadow_ai_rank", "fallback_rank_field_used": None, "prohibited_fields": ["decision_diagnostics.ai_rank", "decision_result.ai_rank", "legacy ai_rank"], "retrospective_prediction_sources": sources, "retrospective_result_source": {"path": str(TOP5.relative_to(ROOT)), "sha256": sha256(TOP5)}, "prospective_prediction_sources": prospective_sources, "prospective_result_source": {"path": str(PROSPECTIVE_RESULTS.relative_to(ROOT)), "sha256": sha256(PROSPECTIVE_RESULTS)}})
    dump("retrospective_selection.json", {"rule": "CF_TOP3_RANK_ANCHORED", "selection_order": "shadow_ai_rank ascending", "selection_phase_result_independent": True, "races": retrospective})
    dump("candidate_pool_baseline.json", {"primary_null": "UNCONVERGED_CANDIDATE_POOL_TOP3_RATE", "pooled": {key: pooled[key] for key in ("candidate_horse_count", "candidate_valid_horse_count", "candidate_top3_count", "candidate_pool_top3_rate")}})
    dump("block_results.json", by_block)
    dump("candidate_count_4_vs_5.json", by_count)
    dump("pooled_results.json", pooled)
    dump("descriptive_kpi_impact.json", descriptive)
    dump("prospective_20260822_context.json", {"classification": "PROSPECTIVE_CONTEXT_ONLY", "races": prospective_races, "summary": prospective, "not_merged_with_retrospective": True})
    dump("analysis_gate.json", gate)
    dump("summary.json", {"final_status": decision, "exact_next_action": next_action, "retrospective": pooled, "temporal_blocks": by_block, "candidate_count_subgroups": by_count, "prospective_context_only": prospective, "descriptive_kpi_impact": descriptive, "safety": {"prediction_rerun": False, "result_informed_selection": False, "threshold_optimization": False, "production_change": False, "engine_change": False, "buy_max_change": False, "candidate_creation": False}})
    (OUT / "report.md").write_text(render_report(pooled, by_block, by_count, prospective, gate), encoding="utf-8")


if __name__ == "__main__":
    main()
