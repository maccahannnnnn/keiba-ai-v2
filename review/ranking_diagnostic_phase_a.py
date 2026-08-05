"""Static saved-artifact availability audit for Ranking Diagnostic Phase A."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SOURCES = {
    "20260725": ("reports/review_20260725/race_review.csv", "reports/review_20260725/horse_review.csv", "legacy", "legacy_minimal"),
    "20260726": ("reports/review_20260726/race_review.csv", "reports/review_20260726/horse_review.csv", "legacy", "legacy_detailed"),
    "20260801": ("reports/review_20260801/race_summary_20260801_v2.csv", "reports/review_20260801/horse_review_20260801_v2.csv", "v2", "v2_review_basic"),
    "20260802": ("reports/review_20260802/race_summary_20260802_v1.csv", "reports/review_20260802/horse_review_20260802_v1.csv", "v1", "v1_pre_race_detailed"),
}
HORSE_FIELDS = (
    "race_id", "horse_name", "horse_number", "ai_rank", "decision", "final_score", "adjusted_score", "decision_score",
    "past_performance_score", "distance_score", "course_shape_score", "lap_score", "lap_suitability_score",
    "race_shape_score", "pace_style_score", "bloodline_score", "ability_score", "track_condition_score",
    "positive_evaluators", "negative_evaluators", "missing_evaluators", "blocking_missing_evaluators",
    "consistency_score", "consistency_level", "strong_matches", "weak_matches", "conflict_factors",
    "score_weights", "weighted_score", "weighted_score_breakdown", "adjusted_score_provenance",
)


def load(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def present(value) -> bool:
    return value not in (None, "")


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def data_type(values: list[str]) -> str:
    nonempty = [value for value in values if present(value)]
    if not nonempty:
        return "UNKNOWN"
    if all(number(value) is not None for value in nonempty):
        return "NUMERIC"
    if all(str(value).lower() in {"true", "false"} for value in nonempty):
        return "BOOLEAN"
    return "TEXT"


def inventory() -> tuple[list[dict], list[dict], dict[str, list[dict]], dict[str, list[dict]]]:
    rows, compatibility, horse_by_date, race_by_date = [], [], {}, {}
    for date, (race_rel, horse_rel, version, family) in SOURCES.items():
        race_path, horse_path = ROOT / race_rel, ROOT / horse_rel
        races, horses = load(race_path), load(horse_path)
        race_by_date[date], horse_by_date[date] = races, horses
        headers = set(horses[0]) if horses else set()
        for field in HORSE_FIELDS:
            values = [row.get(field, "") for row in horses]
            count = sum(present(value) for value in values)
            rows.append({
                "race_date": date, "schema_family": family, "source_version": version, "field": field,
                "column_exists": field in headers, "row_count": len(horses), "nonempty_count": count,
                "missing_count": len(horses) - count, "coverage_pct": round(100 * count / len(horses), 2) if horses else 0,
                "data_type": data_type(values), "source_file": horse_rel, "source_sha256": sha(horse_path),
                "value_kind": "STORED" if field in headers else "NOT_STORED",
                "current_schema_compatibility": "DIRECT" if field in headers else "UNAVAILABLE",
            })
        evaluator_fields = [field for field in HORSE_FIELDS[8:18] if field in headers]
        compatibility.append({
            "race_date": date, "schema_family": family, "declared_source_version": version,
            "race_count": len(races), "horse_count": len(horses), "same_schema_as_previous_date": (
                "N/A" if not compatibility else str(set(horses[0]) == set(horse_by_date[list(horse_by_date)[-2]][0]))
            ),
            "calculation_version_saved": False, "rc1_specification_saved": False,
            "evaluator_columns": ";".join(evaluator_fields), "evaluator_column_count": len(evaluator_fields),
            "adjusted_score_provenance_saved": False,
            "pooling_judgment": "CORE_SCORE_AND_OUTCOME_ONLY" if date != "20260802" else "CURRENT_EVALUATOR_SUBSET_ONLY",
            "source_race_file": race_rel, "source_horse_file": horse_rel,
            "source_race_sha256": sha(race_path), "source_horse_sha256": sha(horse_path),
        })
    return rows, compatibility, horse_by_date, race_by_date


def rank_shift(horse_by_date: dict[str, list[dict]]) -> dict:
    total = changed = ai_matches_adjusted = valid = 0
    for rows in horse_by_date.values():
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["race_id"]].append(row)
        for group in grouped.values():
            usable = [row for row in group if number(row.get("final_score")) is not None and number(row.get("adjusted_score")) is not None]
            final_order = sorted(usable, key=lambda row: (-number(row["final_score"]), int(row.get("horse_number") or 999)))
            adjusted_order = sorted(usable, key=lambda row: (-number(row["adjusted_score"]), int(row.get("horse_number") or 999)))
            final_rank = {id(row): index for index, row in enumerate(final_order, 1)}
            adjusted_rank = {id(row): index for index, row in enumerate(adjusted_order, 1)}
            for row in usable:
                total += 1
                changed += final_rank[id(row)] != adjusted_rank[id(row)]
                saved_rank = int(row.get("ai_rank") or row.get("rank") or 0)
                if saved_rank:
                    valid += 1
                    ai_matches_adjusted += saved_rank == adjusted_rank[id(row)]
    return {"comparable_horses": total, "rank_changed": changed, "saved_ai_rank_available": valid, "saved_ai_rank_matches_adjusted_rank": ai_matches_adjusted}


def component_trace() -> list[dict]:
    return [
        {"component":"Evaluator layer","input":"saved pre-race inputs","calculation":"component-specific scoring","output":"evaluator scores","next_component":"ConsistencyEngine / ScoreWeightEvaluator / FinalScoreIntegrator","production_impact":"CURRENT_CODE_DESCRIPTION_ONLY; saved coverage varies"},
        {"component":"ConsistencyEngine","input":"evaluator scores + race structure","calculation":"strong/weak/conflict matching; no direct score mutation","output":"consistency result","next_component":"ScoreWeightEvaluator and DecisionEngine","production_impact":"CURRENT_CODE_DESCRIPTION_ONLY; output not saved in baseline"},
        {"component":"ScoreWeightEvaluator","input":"evaluator scores + structure hints + consistency","calculation":"raw_score * dynamic weight","output":"weighted_score/integrated_score + breakdown","next_component":"ImpactEvaluator","production_impact":"CURRENT_CODE_DESCRIPTION_ONLY; weights/contributions not saved"},
        {"component":"FinalScoreIntegrator","input":"nine raw evaluator score fields","calculation":"sum(raw evaluator scores)","output":"final_score + score_breakdown","next_component":"ImpactEvaluator (integrated_score preferred when present)","production_impact":"final_score stored; provenance/breakdown not stored"},
        {"component":"ImpactEvaluator","input":"integrated_score fallback final_score + RaceShape","calculation":"base + impact_score","output":"adjusted_score","next_component":"AI rank and DecisionEngine","production_impact":"adjusted_score stored; impact/provenance not stored"},
        {"component":"AI rank generation","input":"adjusted_score + horse_number tie-break","calculation":"descending sort","output":"ai_rank","next_component":"Decision/RaceDecision/BUY","production_impact":"rank stored; static current-code trace only"},
        {"component":"DecisionEngine","input":"adjusted/integrated/weighted/final priority + consistency + risks","calculation":"decision score and guards","output":"decision + decision_score + reasons","next_component":"RaceDecision and BUY layers","production_impact":"decision stored; detailed input/guard trace not stored"},
    ]


def data_gaps() -> list[dict]:
    return [
        {"item":"ability_score","availability":"20260726 only: 112/448","acquisition_class":"A_EXISTING_SEPARATE_SAVED_RESULT_PARTIAL","retrospective_action":"Use only as LEGACY_ONLY stratum; do not impute other dates"},
        {"item":"track_condition_score","availability":"0/448","acquisition_class":"F_UNAVAILABLE","retrospective_action":"No diagnostic; future explicit export required"},
        {"item":"ScoreWeightEvaluator weights","availability":"0/448","acquisition_class":"C_EXPORTER_ADDITION_FUTURE_ONLY","retrospective_action":"Cannot reconstruct version-faithfully without replay"},
        {"item":"weighted contribution","availability":"0/448","acquisition_class":"C_EXPORTER_ADDITION_FUTURE_ONLY","retrospective_action":"Cannot infer from adjusted_score"},
        {"item":"ConsistencyEngine output","availability":"0/448","acquisition_class":"C_EXPORTER_ADDITION_FUTURE_ONLY","retrospective_action":"Reason text is not a numeric substitute"},
        {"item":"DecisionEngine input/guard provenance","availability":"0/448 detailed trace","acquisition_class":"C_EXPORTER_ADDITION_FUTURE_ONLY","retrospective_action":"Decision and partial decision_score only"},
        {"item":"adjusted_score provenance","availability":"0/448","acquisition_class":"C_EXPORTER_ADDITION_FUTURE_ONLY","retrospective_action":"Analyze observed delta/rank shift only; do not attribute component"},
    ]


def evidence_counts(baseline: list[dict], inventory_rows: list[dict], compatibility: list[dict]) -> dict:
    valid = [row for row in baseline if str(row["valid_result"]).lower() == "true"]
    buy = [row for row in valid if str(row["buy_flag"]).lower() == "true"]
    successful = [row for row in buy if str(row["actual_top3"]).lower() == "true"]
    fp = [row for row in buy if int(row["actual_finish"]) >= 4]
    fn = [row for row in valid if str(row["actual_top3"]).lower() == "true" and str(row["buy_flag"]).lower() != "true"]
    current = [row for row in baseline if row["race_date"] == "20260802"]
    current_valid = [row for row in current if str(row["valid_result"]).lower() == "true"]
    return {
        "baseline": {"races": 34, "horses": len(baseline), "valid_horses": len(valid), "dates": 4, "racecourses": len({row["race_id"].split("_")[2] for row in baseline}), "successful_buy": len(successful), "fp_buy": len(fp), "non_buy_top3": len(fn)},
        "current_evaluator_subset": {"races": len({row["race_id"] for row in current}), "horses": len(current), "valid_horses": len(current_valid), "dates": 1, "racecourses": len({row["race_id"].split("_")[2] for row in current}), "successful_buy": sum(str(row["buy_flag"]).lower()=="true" and str(row["actual_top3"]).lower()=="true" for row in current_valid), "fp_buy": sum(str(row["buy_flag"]).lower()=="true" and int(row["actual_finish"])>=4 for row in current_valid), "non_buy_top3": sum(str(row["buy_flag"]).lower()!="true" and str(row["actual_top3"]).lower()=="true" for row in current_valid)},
        "shadow_minimum": {"valid_horses":100,"fp":15,"fn":15,"dates":10,"racecourses":3},
    }


def run() -> tuple[list[dict], list[dict], list[dict], list[dict], dict]:
    inv, compat, horse_by_date, _ = inventory()
    baseline = load(REPORTS / "baseline" / "keibaai_baseline_4days_v1_horse.csv")
    shifts = rank_shift(horse_by_date)
    evidence = evidence_counts(baseline, inv, compat)
    trace = component_trace(); gaps = data_gaps()
    readiness = {
        "status":"RANKING_DIAGNOSTIC_PHASE_A_COMPLETE",
        "judgment":"PARTIAL_DIAGNOSTIC_READY",
        "first_diagnostic":"FINAL_TO_ADJUSTED_RANK_SHIFT",
        "usable_dates":["20260725","20260726","20260801","20260802"],
        "usable_races":34,"usable_horses":448,
        "ranking_score_layer":"PARTIALLY_DIAGNOSTIC",
        "score_weight_evaluator":"NOT_DIAGNOSTIC",
        "consistency_engine":"NOT_DIAGNOSTIC",
        "decision_engine":"PARTIALLY_DIAGNOSTIC",
        "past_performance":"CURRENT_ONLY; 102 horses / 8 races / 1 date; not cross-date diagnostic",
        "date_compatibility":"Core score/outcome fields only; evaluator schemas must remain separate",
        "rank_shift":shifts,"evidence":evidence,
        "shadow_progression":"HOLD: only 4 dates; current evaluator subset has 1 date, 3 FP BUY, and no cross-date compatibility",
        "production_candidate":"NONE","production_delta":"ZERO",
    }
    return inv, trace, compat, gaps, readiness


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def main() -> None:
    inv, trace, compat, gaps, ready = run()
    write_csv(REPORTS / "ranking_diagnostic_column_inventory_v1.csv", inv)
    write_csv(REPORTS / "ranking_diagnostic_component_trace_v1.csv", trace)
    write_csv(REPORTS / "ranking_diagnostic_compatibility_v1.csv", compat)
    write_csv(REPORTS / "ranking_diagnostic_data_gap_v1.csv", gaps)
    (REPORTS / "ranking_diagnostic_readiness_v1.json").write_text(json.dumps(ready, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    base, current = ready["evidence"]["baseline"], ready["evidence"]["current_evaluator_subset"]
    lines = [
        "# Ranking & Evaluator Diagnostic Phase A", "", "## Judgment", "", "**PARTIAL_DIAGNOSTIC_READY**", "",
        "The first diagnostic is the observed final_score -> adjusted_score rank shift. It uses stored values only and does not attribute the delta to ScoreWeightEvaluator because weights, contributions, impact provenance, and calculation versions were not saved.", "",
        "## Availability", "", f"- Core ranking layer: 4 dates / 34 races / 448 horses", f"- Valid results: {base['valid_horses']}", f"- Successful BUY: {base['successful_buy']}", f"- FP BUY: {base['fp_buy']}", f"- non-BUY Top3: {base['non_buy_top3']}",
        f"- Stored-rank comparison: {ready['rank_shift']['comparable_horses']} horses; final-vs-adjusted rank changes {ready['rank_shift']['rank_changed']}", "",
        "## Component readiness", "", "- Ranking score layer: PARTIALLY_DIAGNOSTIC", "- ScoreWeightEvaluator: NOT_DIAGNOSTIC", "- ConsistencyEngine: NOT_DIAGNOSTIC", "- DecisionEngine: PARTIALLY_DIAGNOSTIC", "- PastPerformance: CURRENT_ONLY (2026-08-02, 102 horses)", "",
        "## Compatibility", "", "The declared source labels do not imply a common schema. 2026-07-25 is legacy-minimal; 2026-07-26 is legacy-detailed; 2026-08-01 is v2-basic; 2026-08-02 is v1 pre-race detailed. Only core score/rank/decision/outcome fields may be pooled. Evaluator columns remain version/date strata.", "",
        "## Evidence minimum", "", f"Current evaluator subset: {current['valid_horses']} valid horses / {current['fp_buy']} FP / {current['non_buy_top3']} non-BUY Top3 / {current['dates']} date / {current['racecourses']} courses.", "Shadow progression is HOLD: the 10-date minimum is not met, and the evaluator subset is not cross-date compatible. No improvement candidate is created.", "",
        "## Required future collection", "", "Export score_weights, weighted_score_breakdown, consistency result, DecisionEngine input/guard trace, adjusted_score provenance, calculation version, and explicit missing flags before result join. No retrospective imputation is allowed.", "",
        "Production Candidate: NONE. Production delta: ZERO.",
    ]
    (REPORTS / "ranking_diagnostic_phase_a_v1.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(ready, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
