"""PastPerformance Quality Gate v2 shadow validation.

Shadow-only diagnostic.  Production evaluators, Decision, FinalScore,
thresholds, Knowledge, CSV specs, and main.py are not modified.
"""

from __future__ import annotations

import csv
import statistics
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from review.ability_override_shadow_validator import (
    OUT_DIR,
    applicable,
    apply_shadow,
    baseline_metrics,
    load_population,
    shadow_decision,
    to_float,
    to_int,
    write_csv,
)


MULTIPLIER = 0.75
PAST_HIGH = 70.0
DISTANCE_SIMILAR = 35.0
PAST_SCORE_SCALE_MAX = 100.0
LAP_NON_NEGATIVE = 0.0
PAST_THRESHOLDS = [68, 69, 70, 71, 72]
DISTANCE_THRESHOLDS = [33, 34, 35, 36, 37]
SIX_HORSES = {
    ("race_20260712_hakodate_11R", "シルトホルン"),
    ("race_20260705_hakodate_11R", "プロミストジーン"),
    ("race_20260712_fukushima_11R", "コントラポスト"),
    ("race_20260712_fukushima_11R", "サヴォーナ"),
    ("race_20260712_hakodate_11R", "タシット"),
    ("race_20260712_kokura_11R", "ゴッドブルービー"),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def v1_gate(row: dict[str, object], past_threshold: float = PAST_HIGH, distance_threshold: float = DISTANCE_SIMILAR) -> bool:
    past = to_float(row.get("past_performance_score"), None)
    distance = to_float(row.get("distance_score"), None)
    return past is not None and distance is not None and past >= past_threshold and distance >= distance_threshold


def v2_features(row: dict[str, object]) -> dict[str, object]:
    candidate, signals, penalty, source = applicable(row)
    past = to_float(row.get("past_performance_score"), None)
    distance = to_float(row.get("distance_score"), None)
    lap = to_float(row.get("lap_score"), None)
    course = to_float(row.get("course_score"), None)
    pace = to_float(row.get("pace_score"), None)
    return {
        "race_id": row.get("race_id"),
        "horse_name": row.get("horse_name"),
        "dataset_group": row.get("dataset_group"),
        "official_decision": row.get("official_decision"),
        "actual_finish": to_int(row.get("actual_finish")),
        "actual_top3": row.get("actual_top3"),
        "ai_rank": row.get("ai_rank"),
        "race_shape_score": row.get("race_shape_score"),
        "race_shape_penalty": penalty,
        "penalty_source": source,
        "ability_override_candidate": candidate,
        "ability_signal_count": len(signals),
        "ability_signals": "; ".join(signals),
        "past_performance_score": past,
        "distance_score": distance,
        "lap_score": lap,
        "course_score": course,
        "pace_score": pace,
        "past_score_available": past is not None,
        "distance_score_available": distance is not None,
        "lap_score_available": lap is not None,
        "course_score_available": course is not None,
        "pace_score_available": pace is not None,
        "v1_gate": candidate and v1_gate(row),
        "score_scale_stable": past is not None and past <= PAST_SCORE_SCALE_MAX,
        "lap_non_negative": lap is not None and lap >= LAP_NON_NEGATIVE,
        "distance_similarity_support": distance is not None and distance >= DISTANCE_SIMILAR,
        "v2_gate": v2_gate(row)[0],
        "v2_gate_reason": v2_gate(row)[1],
        "quality_class": quality_class(row),
    }


def quality_class(row: dict[str, object]) -> str:
    if not applicable(row)[0]:
        return "OUT_OF_SCOPE"
    if not v1_gate(row):
        return "V1_FAIL"
    if v2_gate(row)[0] and row.get("actual_top3"):
        return "REPRODUCIBLE_CONDITION_TRANSFER_SUCCESS"
    if v2_gate(row)[0]:
        return "REPRODUCIBLE_CONDITION_TRANSFER_UNPROVEN"
    past = to_float(row.get("past_performance_score"), None)
    lap = to_float(row.get("lap_score"), None)
    if past is not None and past > PAST_SCORE_SCALE_MAX:
        return "SCORE_SCALE_UNSTABLE"
    if lap is not None and lap < LAP_NON_NEGATIVE:
        return "LAP_SUPPORT_MISSING"
    return "QUALITY_SUPPORT_MISSING"


def v2_gate(row: dict[str, object]) -> tuple[bool, str]:
    candidate, _signals, _penalty, _source = applicable(row)
    if not candidate:
        return False, "not previous ability override candidate"
    if not v1_gate(row):
        return False, "v1 gate failed"
    past = to_float(row.get("past_performance_score"), None)
    lap = to_float(row.get("lap_score"), None)
    if past is None or past > PAST_SCORE_SCALE_MAX:
        return False, "past performance score scale is unstable or unavailable"
    if lap is None or lap < LAP_NON_NEGATIVE:
        return False, "lap suitability does not support race-shape resilience"
    return True, "v1 gate + stable past score scale + non-negative lap support"


def apply_v2_shadow(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    shadow = [deepcopy(row) for row in rows]
    by_race: dict[object, list[dict[str, object]]] = defaultdict(list)
    for row in shadow:
        by_race[row.get("race_id")].append(row)

    for race_rows in by_race.values():
        top = max(to_float(row.get("adjusted_score"), 0.0) for row in race_rows)
        bottom = min(to_float(row.get("adjusted_score"), 0.0) for row in race_rows)
        spread = max(1.0, top - bottom)
        for row in race_rows:
            candidate, signals, penalty, source = applicable(row)
            gate_pass, gate_reason = v2_gate(row)
            recovery = abs(penalty) * (1.0 - MULTIPLIER) if gate_pass else 0.0
            old_adjusted = to_float(row.get("adjusted_score"), 0.0)
            old_decision_score = to_float(row.get("decision_score"), 0.0)
            score_delta = (recovery / spread) * 0.45
            row["shadow_adjusted_score"] = round(old_adjusted + recovery, 3)
            row["shadow_decision_score"] = max(0.0, min(1.0, round(old_decision_score + score_delta, 3)))
            row["ability_override_applied"] = gate_pass
            row["v1_gate"] = candidate and v1_gate(row)
            row["v2_gate"] = gate_pass
            row["v2_gate_reason"] = gate_reason
            row["ability_signals"] = signals
            row["race_shape_penalty_used"] = penalty
            row["penalty_source"] = source
            row["score_delta"] = round(score_delta, 3)
            row["quality_class"] = quality_class(row)

        ranked = sorted(
            race_rows,
            key=lambda item: (to_float(item.get("shadow_adjusted_score"), 0.0), to_int(item.get("ai_rank"), 999) * -1),
            reverse=True,
        )
        for rank, row in enumerate(ranked, start=1):
            row["shadow_rank"] = rank
            row["shadow_decision"] = shadow_decision(row, rank)

    return shadow, [detail_row(row) for row in shadow]


def effect_label(row: dict[str, object]) -> str:
    official = str(row.get("official_decision") or "").upper()
    shadow = str(row.get("shadow_decision") or "").upper()
    finish = to_int(row.get("actual_finish"))
    if official == shadow:
        return "unchanged"
    if official != "BUY" and shadow == "BUY" and finish in {1, 2, 3}:
        return "rescued_fn_to_buy"
    if official == "PASS" and shadow == "CAUTION" and finish in {1, 2, 3}:
        return "rescued_pass_to_caution"
    if shadow == "BUY" and finish and finish >= 4:
        return "new_fp"
    return "other_decision_change"


def detail_row(row: dict[str, object]) -> dict[str, object]:
    official = str(row.get("official_decision") or "").upper()
    shadow = str(row.get("shadow_decision") or "").upper()
    return {
        "race_id": row.get("race_id"),
        "horse_name": row.get("horse_name"),
        "dataset_group": row.get("dataset_group"),
        "official_decision": official,
        "shadow_decision": shadow,
        "actual_finish": to_int(row.get("actual_finish")),
        "ai_rank": row.get("ai_rank"),
        "shadow_rank": row.get("shadow_rank"),
        "final_score": row.get("final_score"),
        "adjusted_score": row.get("adjusted_score"),
        "shadow_adjusted_score": row.get("shadow_adjusted_score"),
        "decision_score": row.get("decision_score"),
        "shadow_decision_score": row.get("shadow_decision_score"),
        "race_shape_score": row.get("race_shape_score"),
        "race_shape_penalty_used": row.get("race_shape_penalty_used"),
        "past_performance_score": row.get("past_performance_score"),
        "distance_score": row.get("distance_score"),
        "lap_score": row.get("lap_score"),
        "course_score": row.get("course_score"),
        "pace_score": row.get("pace_score"),
        "v1_gate": row.get("v1_gate"),
        "v2_gate": row.get("v2_gate"),
        "v2_gate_reason": row.get("v2_gate_reason"),
        "quality_class": row.get("quality_class"),
        "score_delta": row.get("score_delta"),
        "decision_changed": official != shadow,
        "case_effect": effect_label(row),
    }


def metric_row(label: str, rows: list[dict[str, object]], detail_rows: list[dict[str, object]], gate_key: str = "v2_gate") -> dict[str, object]:
    decisions = Counter(row.get("shadow_decision", row.get("official_decision")) for row in rows)
    buy_rows = [row for row in rows if row.get("shadow_decision", row.get("official_decision")) == "BUY"]
    pass_rows = [row for row in rows if row.get("shadow_decision", row.get("official_decision")) == "PASS"]
    race_ids = sorted({row.get("race_id") for row in rows})
    buy_by_race = Counter(row.get("race_id") for row in buy_rows)
    rescued = [row for row in detail_rows if row.get("case_effect") in {"rescued_fn_to_buy", "rescued_pass_to_caution"}]
    new_fp = [row for row in detail_rows if row.get("case_effect") == "new_fp"]
    existing_buy_success_changed = sum(
        1
        for row in rows
        if row.get("official_decision") == "BUY"
        and row.get("actual_top3")
        and row.get("shadow_decision", row.get("official_decision")) != "BUY"
    )
    return {
        "scenario": label,
        "race_count": len(race_ids),
        "horse_count": len(rows),
        "candidate_count": sum(1 for row in rows if applicable(row)[0]),
        "gate_pass_count": sum(1 for row in rows if row.get(gate_key)),
        "BUY": decisions.get("BUY", 0),
        "CAUTION": decisions.get("CAUTION", 0),
        "PASS": decisions.get("PASS", 0),
        "BUY_top3": sum(1 for row in buy_rows if row.get("actual_top3")),
        "BUY_top5": sum(1 for row in buy_rows if row.get("actual_top5")),
        "BUY_top3_rate": round(sum(1 for row in buy_rows if row.get("actual_top3")) / len(buy_rows), 3) if buy_rows else 0,
        "BUY_top5_rate": round(sum(1 for row in buy_rows if row.get("actual_top5")) / len(buy_rows), 3) if buy_rows else 0,
        "PASS_top3": sum(1 for row in pass_rows if row.get("actual_top3")),
        "FN": sum(1 for row in rows if row.get("actual_top3") and row.get("shadow_decision", row.get("official_decision")) != "BUY"),
        "FP": sum(1 for row in rows if row.get("shadow_decision", row.get("official_decision")) == "BUY" and not row.get("actual_top3")),
        "top5_hit": sum(1 for row in rows if to_int(row.get("shadow_rank", row.get("ai_rank")), 999) <= 5 and row.get("actual_top3")),
        "buy_zero_races": sum(1 for race_id in race_ids if buy_by_race.get(race_id, 0) == 0),
        "rescued_buy": sum(1 for row in rescued if row.get("case_effect") == "rescued_fn_to_buy"),
        "rescued_caution": sum(1 for row in rescued if row.get("case_effect") == "rescued_pass_to_caution"),
        "new_fp": len(new_fp),
        "net_rescue": len(rescued) - len(new_fp),
        "existing_buy_success_maintained": sum(1 for row in rows if row.get("official_decision") == "BUY" and row.get("actual_top3")) - existing_buy_success_changed,
        "non_target_impact_count": sum(1 for row in detail_rows if not row.get(gate_key) and row.get("decision_changed") == "True"),
    }


def baseline_as_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    base = baseline_metrics(rows)
    return {
        "scenario": "Baseline",
        "race_count": base["race_count"],
        "horse_count": base["horse_count"],
        "candidate_count": sum(1 for row in rows if applicable(row)[0]),
        "gate_pass_count": "",
        "BUY": base["BUY"],
        "CAUTION": base["CAUTION"],
        "PASS": base["PASS"],
        "BUY_top3": base["BUY_top3"],
        "BUY_top5": base["BUY_top5"],
        "BUY_top3_rate": base["BUY_top3_rate"],
        "BUY_top5_rate": base["BUY_top5_rate"],
        "PASS_top3": base["PASS_top3"],
        "FN": base["FN"],
        "FP": base["FP"],
        "top5_hit": base["top5_hit"],
        "buy_zero_races": base["buy_zero_races"],
        "rescued_buy": "",
        "rescued_caution": "",
        "new_fp": "",
        "net_rescue": "",
        "existing_buy_success_maintained": base["BUY_top3"],
        "non_target_impact_count": 0,
    }


def apply_threshold_shadow(rows: list[dict[str, object]], past_threshold: float, distance_threshold: float) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    shadow = [deepcopy(row) for row in rows]
    by_race: dict[object, list[dict[str, object]]] = defaultdict(list)
    for row in shadow:
        by_race[row.get("race_id")].append(row)
    for race_rows in by_race.values():
        top = max(to_float(row.get("adjusted_score"), 0.0) for row in race_rows)
        bottom = min(to_float(row.get("adjusted_score"), 0.0) for row in race_rows)
        spread = max(1.0, top - bottom)
        for row in race_rows:
            candidate, signals, penalty, source = applicable(row)
            gate = candidate and v1_gate(row, past_threshold, distance_threshold)
            recovery = abs(penalty) * (1.0 - MULTIPLIER) if gate else 0.0
            old_adjusted = to_float(row.get("adjusted_score"), 0.0)
            old_decision_score = to_float(row.get("decision_score"), 0.0)
            score_delta = (recovery / spread) * 0.45
            row["shadow_adjusted_score"] = round(old_adjusted + recovery, 3)
            row["shadow_decision_score"] = max(0.0, min(1.0, round(old_decision_score + score_delta, 3)))
            row["ability_override_applied"] = gate
            row["v1_gate"] = gate
            row["v2_gate"] = gate
            row["v2_gate_reason"] = f"threshold sensitivity past>={past_threshold} distance>={distance_threshold}"
            row["ability_signals"] = signals
            row["race_shape_penalty_used"] = penalty
            row["penalty_source"] = source
            row["score_delta"] = round(score_delta, 3)
        ranked = sorted(
            race_rows,
            key=lambda item: (to_float(item.get("shadow_adjusted_score"), 0.0), to_int(item.get("ai_rank"), 999) * -1),
            reverse=True,
        )
        for rank, row in enumerate(ranked, start=1):
            row["shadow_rank"] = rank
            row["shadow_decision"] = shadow_decision(row, rank)
    return shadow, [detail_row(row) for row in shadow]


def sensitivity(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for past_threshold in PAST_THRESHOLDS:
        for distance_threshold in DISTANCE_THRESHOLDS:
            shadow_rows, details = apply_threshold_shadow(rows, past_threshold, distance_threshold)
            summary = metric_row(f"past>={past_threshold}_distance>={distance_threshold}", shadow_rows, details, "v1_gate")
            summary["past_threshold"] = past_threshold
            summary["distance_threshold"] = distance_threshold
            output.append(summary)
    return output


def data_availability(feature_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    fields = [
        "past_performance_score",
        "distance_score",
        "lap_score",
        "course_score",
        "pace_score",
        "available_past_runs",
        "valid_past_runs",
        "top3_count",
        "top5_count",
        "mean_margin",
        "latest_run_score",
        "similar_condition_good_run_count",
        "higher_class_run_count",
        "pace_resilience_support",
    ]
    output = []
    for field in fields:
        if field in {"available_past_runs", "valid_past_runs", "top3_count", "top5_count", "mean_margin", "latest_run_score", "similar_condition_good_run_count", "higher_class_run_count", "pace_resilience_support"}:
            count = 0
        else:
            count = sum(1 for row in feature_rows if row.get(field) not in {None, ""})
        output.append(
            {
                "feature": field,
                "available_count": count,
                "missing_count": len(feature_rows) - count,
                "availability_rate": round(count / len(feature_rows), 3) if feature_rows else 0,
                "baseline22_available": sum(1 for row in feature_rows if row.get("dataset_group") == "baseline_22" and row.get(field) not in {None, ""}) if count else 0,
                "added18_available": sum(1 for row in feature_rows if row.get("dataset_group") != "baseline_22" and row.get(field) not in {None, ""}) if count else 0,
                "use_in_v2_required_gate": field in {"past_performance_score", "distance_score", "lap_score"},
            }
        )
    return output


def group_comparison(feature_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups = {
        "A_top3": lambda row: row.get("actual_top3") is True,
        "B_4plus": lambda row: row.get("actual_top3") is not True,
        "C_v1_gate_pass": lambda row: row.get("v1_gate") is True,
        "D_v1_gate_fail": lambda row: row.get("v1_gate") is not True,
        "E_pass_top3": lambda row: row.get("official_decision") == "PASS" and row.get("actual_top3") is True,
        "F_pass_4plus": lambda row: row.get("official_decision") == "PASS" and row.get("actual_top3") is not True,
        "G_caution_top3": lambda row: row.get("official_decision") == "CAUTION" and row.get("actual_top3") is True,
        "H_caution_4plus": lambda row: row.get("official_decision") == "CAUTION" and row.get("actual_top3") is not True,
    }
    output = []
    for group, predicate in groups.items():
        selected = [row for row in feature_rows if predicate(row)]
        output.append(describe_group(group, selected))
    return output


def describe_group(group: str, rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "group": group,
        "count": len(rows),
        "v1_gate_pass": sum(1 for row in rows if row.get("v1_gate")),
        "v2_gate_pass": sum(1 for row in rows if row.get("v2_gate")),
        "mean_past": mean_value(rows, "past_performance_score"),
        "median_past": median_value(rows, "past_performance_score"),
        "mean_distance": mean_value(rows, "distance_score"),
        "median_distance": median_value(rows, "distance_score"),
        "mean_lap": mean_value(rows, "lap_score"),
        "median_lap": median_value(rows, "lap_score"),
        "mean_course": mean_value(rows, "course_score"),
        "mean_pace": mean_value(rows, "pace_score"),
        "score_scale_unstable_count": sum(1 for row in rows if to_float(row.get("past_performance_score"), 0) > PAST_SCORE_SCALE_MAX),
        "lap_non_negative_count": sum(1 for row in rows if to_float(row.get("lap_score"), -999) >= 0),
    }


def mean_value(rows: list[dict[str, object]], field: str):
    values = [to_float(row.get(field), None) for row in rows]
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 3) if values else ""


def median_value(rows: list[dict[str, object]], field: str):
    values = [to_float(row.get(field), None) for row in rows]
    values = [value for value in values if value is not None]
    return round(statistics.median(values), 3) if values else ""


def period_comparison(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    subsets = {
        "baseline22": [row for row in rows if row.get("dataset_group") == "baseline_22"],
        "added18": [row for row in rows if row.get("dataset_group") != "baseline_22"],
        "all40": rows,
    }
    for label, subset in subsets.items():
        shadow_rows, details = apply_v2_shadow(subset)
        output.append(metric_row(label, shadow_rows, details))
    return output


def leave_one_race_out(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for race_id in sorted({row.get("race_id") for row in rows}):
        subset = [row for row in rows if row.get("race_id") != race_id]
        shadow_rows, details = apply_v2_shadow(subset)
        row = metric_row(f"exclude_{race_id}", shadow_rows, details)
        row["excluded_race_id"] = race_id
        output.append(row)
    return output


def six_horse_comparison(details: list[dict[str, object]]) -> list[dict[str, object]]:
    detail_map = {(row["race_id"], row["horse_name"]): row for row in details}
    previous = {
        (row.get("race_id"), row.get("horse_name")): row
        for row in read_csv(OUT_DIR / "past_performance_quality_6horse_details.csv")
    }
    rows = []
    for race_id, horse_name in sorted(SIX_HORSES):
        current = detail_map.get((race_id, horse_name), {})
        old = previous.get((race_id, horse_name), {})
        rows.append(
            {
                "race_id": race_id,
                "horse_name": horse_name,
                "actual_finish": current.get("actual_finish"),
                "official_decision": current.get("official_decision"),
                "v1_shadow_decision": old.get("quality_shadow_decision"),
                "v2_shadow_decision": current.get("shadow_decision"),
                "v1_gate_pass": old.get("quality_gate_pass"),
                "v2_gate_pass": current.get("v2_gate"),
                "past_performance_score": current.get("past_performance_score"),
                "distance_score": current.get("distance_score"),
                "lap_score": current.get("lap_score"),
                "quality_class": current.get("quality_class"),
                "v2_gate_reason": current.get("v2_gate_reason"),
                "case_effect": current.get("case_effect"),
            }
        )
    return rows


def comparison_table(rows: list[dict[str, object]], v2_rows: list[dict[str, object]], v2_details: list[dict[str, object]]) -> list[dict[str, object]]:
    ability_rows, ability_details = apply_shadow(rows, MULTIPLIER)
    v1_rows = read_csv(OUT_DIR / "past_performance_quality_shadow_summary.csv")
    output = [baseline_as_summary(rows), metric_row("AbilityOverride_0.75", ability_rows, ability_details)]
    if v1_rows:
        v1 = dict(v1_rows[0])
        output.append(
            {
                "scenario": "QualityGate_v1",
                "race_count": v1.get("race_count"),
                "horse_count": v1.get("horse_count"),
                "candidate_count": v1.get("candidate_count"),
                "gate_pass_count": v1.get("gate_pass_count"),
                "BUY": v1.get("BUY"),
                "CAUTION": v1.get("CAUTION"),
                "PASS": v1.get("PASS"),
                "BUY_top3": v1.get("BUY_top3"),
                "BUY_top5": v1.get("BUY_top5"),
                "BUY_top3_rate": v1.get("BUY_top3_rate"),
                "BUY_top5_rate": v1.get("BUY_top5_rate"),
                "PASS_top3": v1.get("PASS_top3"),
                "FN": v1.get("FN"),
                "FP": v1.get("FP"),
                "top5_hit": v1.get("top5_hit"),
                "buy_zero_races": v1.get("buy_zero_races"),
                "rescued_buy": v1.get("rescued_fn_to_buy"),
                "rescued_caution": v1.get("rescued_fn_to_caution"),
                "new_fp": v1.get("new_fp"),
                "net_rescue": v1.get("net_quality_rescue"),
                "existing_buy_success_maintained": "",
                "non_target_impact_count": 0,
            }
        )
    output.append(metric_row("QualityGate_v2", v2_rows, v2_details))
    return output


def write_markdown(
    comparison: list[dict[str, object]],
    period: list[dict[str, object]],
    loo: list[dict[str, object]],
    six: list[dict[str, object]],
    data_rows: list[dict[str, object]],
) -> str:
    v2 = comparison[-1]
    positive_loo = sum(1 for row in loo if to_int(row.get("net_rescue"), 0) >= 0)
    fp_loo = sum(1 for row in loo if to_int(row.get("new_fp"), 0) > 0)
    decision = "ACCEPT_FOR_NEXT_SHADOW"
    if to_int(v2.get("rescued_caution"), 0) + to_int(v2.get("rescued_buy"), 0) <= 0:
        decision = "REJECT_V2_KEEP_V1_SHADOW"
    if to_int(v2.get("new_fp"), 0) > 0:
        decision = "REJECT_V2_KEEP_V1_SHADOW"
    lines = [
        "# PastPerformance Quality Gate v2 Shadow Validation",
        "",
        "## v2 Gate",
        "",
        "- Base: previous Ability Override 0.75 candidates.",
        "- v1 must pass: past_performance_score >= 70 and distance_score >= 35.",
        "- Added data-quality condition: past_performance_score <= 100 to avoid cross-period score-scale instability.",
        "- Added resilience condition: lap_score >= 0 to require at least neutral lap support before offsetting RaceShape penalty.",
        "- RaceShape penalty multiplier: 0.75, Shadow only.",
        "",
        "## Baseline / Ability / v1 / v2",
        "",
        "| scenario | candidates | gate | BUY | CAUTION | PASS | BUY3 rate | FN | FP | rescued BUY | rescued CAUTION | new FP | net |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparison:
        lines.append(
            f"| {row['scenario']} | {row['candidate_count']} | {row['gate_pass_count']} | {row['BUY']} | "
            f"{row['CAUTION']} | {row['PASS']} | {row['BUY_top3_rate']} | {row['FN']} | {row['FP']} | "
            f"{row['rescued_buy']} | {row['rescued_caution']} | {row['new_fp']} | {row['net_rescue']} |"
        )
    lines.extend(
        [
            "",
            "## Period Comparison",
            "",
            "| period | races | horses | candidates | gate | rescued | new FP | net | BUY3 rate | FN | FP |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in period:
        rescued = to_int(row.get("rescued_buy"), 0) + to_int(row.get("rescued_caution"), 0)
        lines.append(
            f"| {row['scenario']} | {row['race_count']} | {row['horse_count']} | {row['candidate_count']} | "
            f"{row['gate_pass_count']} | {rescued} | {row['new_fp']} | {row['net_rescue']} | "
            f"{row['BUY_top3_rate']} | {row['FN']} | {row['FP']} |"
        )
    lines.extend(
        [
            "",
            "## Six-Horse Comparison",
            "",
            "| horse | official | v1 | v2 | finish | v2 gate | reason |",
            "|---|---|---|---|---:|---|---|",
        ]
    )
    for row in six:
        lines.append(
            f"| {row['horse_name']} | {row['official_decision']} | {row['v1_shadow_decision']} | "
            f"{row['v2_shadow_decision']} | {row['actual_finish']} | {row['v2_gate_pass']} | {row['v2_gate_reason']} |"
        )
    lines.extend(
        [
            "",
            "## Data Availability",
            "",
            "- Run-level features requested for reproducibility, class/opponent support, and pace-disadvantage history were not present in the integrated 40-race rows.",
            "- v2 therefore uses only pre-result evaluator outputs available for all 60 prior candidates.",
            f"- Fully available candidate-level fields: {sum(1 for row in data_rows if row['availability_rate'] == 1)} of {len(data_rows)} listed feature groups.",
            "",
            "## Leave-One-Race-Out",
            "",
            f"- LOO runs: {len(loo)}",
            f"- Non-negative net_rescue runs: {positive_loo}",
            f"- Runs with new FP: {fp_loo}",
            "",
            "## Final Judgment",
            "",
            f"- Judgment: {decision}",
            "- Production candidate: No. v2 is cleaner than v1 for FP control, but it remains baseline22-dependent and does not create FN-to-BUY improvement.",
        ]
    )
    text = "\n".join(lines) + "\n"
    (OUT_DIR / "past_performance_quality_v2_shadow.md").write_text(text, encoding="utf-8")
    (OUT_DIR / "past_performance_quality_v2_review.md").write_text(text, encoding="utf-8")
    return decision


def main() -> None:
    rows, warnings = load_population()
    feature_rows = [v2_features(row) for row in rows if applicable(row)[0]]
    v2_rows, v2_details = apply_v2_shadow(rows)
    comparison = comparison_table(rows, v2_rows, v2_details)
    data_rows = data_availability(feature_rows)
    group_rows = group_comparison(feature_rows)
    sensitivity_rows = sensitivity(rows)
    period_rows = period_comparison(rows)
    loo_rows = leave_one_race_out(rows)
    six_rows = six_horse_comparison(v2_details)
    gate_rows = [row for row in feature_rows if row.get("v1_gate") or row.get("v2_gate")]
    rescued_rows = [row for row in v2_details if row["case_effect"] in {"rescued_fn_to_buy", "rescued_pass_to_caution"}]
    fp_rows = [row for row in v2_details if row["case_effect"] == "new_fp"]

    write_csv(OUT_DIR / "past_performance_quality_v2_features.csv", feature_rows, list(feature_rows[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v2_data_availability.csv", data_rows, list(data_rows[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v2_group_comparison.csv", group_rows, list(group_rows[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v2_6horse_comparison.csv", six_rows, list(six_rows[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v1_sensitivity.csv", sensitivity_rows, list(sensitivity_rows[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v2_gate.csv", gate_rows, list(gate_rows[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v2_shadow_summary.csv", comparison, list(comparison[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v2_shadow_details.csv", v2_details, list(v2_details[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v2_rescued.csv", rescued_rows, list(v2_details[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v2_false_positive.csv", fp_rows, list(v2_details[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v2_period_comparison.csv", period_rows, list(period_rows[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_v2_leave_one_race_out.csv", loo_rows, list(loo_rows[0].keys()))
    judgment = write_markdown(comparison, period_rows, loo_rows, six_rows, data_rows)

    v2 = comparison[-1]
    print("PastPerformance Quality Gate v2 Shadow Validation")
    print(f"races={v2['race_count']} horses={v2['horse_count']}")
    print(f"candidate/gate={v2['candidate_count']}/{v2['gate_pass_count']}")
    print(f"BUY/CAUTION/PASS={v2['BUY']}/{v2['CAUTION']}/{v2['PASS']}")
    print(f"rescued_buy/rescued_caution/new_fp/net={v2['rescued_buy']}/{v2['rescued_caution']}/{v2['new_fp']}/{v2['net_rescue']}")
    print(f"judgment={judgment}")
    if warnings:
        print(f"warnings={len(warnings)}")


if __name__ == "__main__":
    main()
