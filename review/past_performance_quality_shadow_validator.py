"""Shadow validation for PastPerformance quality-gated Ability Override.

Diagnostic-only.  This script reuses the existing Ability Override shadow
population, applies a narrow PastPerformance quality gate, and writes reports
under analysis/reports.  It does not change production evaluators, Decision,
FinalScore, thresholds, Knowledge, CSV specs, or main.py.
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
    baseline_metrics,
    load_population,
    race_shape_penalty,
    shadow_decision,
    to_float,
    to_int,
    write_csv,
)


MULTIPLIER = 0.75
PAST_HIGH_THRESHOLD = 70.0
DISTANCE_TRANSFER_THRESHOLD = 35.0
SIX_HORSES = {
    ("race_20260712_hakodate_11R", "シルトホルン"),
    ("race_20260705_hakodate_11R", "プロミストジーン"),
    ("race_20260712_fukushima_11R", "コントラポスト"),
    ("race_20260712_fukushima_11R", "サヴォーナ"),
    ("race_20260712_hakodate_11R", "タシット"),
    ("race_20260712_kokura_11R", "ゴッドブルービー"),
}


DETAIL_FIELDS = [
    "race_id",
    "horse_name",
    "dataset_group",
    "official_decision",
    "shadow_decision",
    "actual_finish",
    "ai_rank",
    "shadow_rank",
    "final_score",
    "adjusted_score",
    "shadow_adjusted_score",
    "decision_score",
    "shadow_decision_score",
    "race_shape_score",
    "race_shape_penalty_used",
    "past_performance_score",
    "distance_score",
    "quality_candidate",
    "quality_gate_pass",
    "quality_gate_reason",
    "ppq_primary",
    "ppq_secondary",
    "score_delta",
    "decision_changed",
    "case_effect",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def is_past_high(row: dict[str, object]) -> bool:
    past = to_float(row.get("past_performance_score"), None)
    return past is not None and past >= PAST_HIGH_THRESHOLD


def has_distance_transfer(row: dict[str, object]) -> bool:
    distance = to_float(row.get("distance_score"), None)
    return distance is not None and distance >= DISTANCE_TRANSFER_THRESHOLD


def quality_gate(row: dict[str, object]) -> tuple[bool, str]:
    if not is_past_high(row):
        return False, "past_performance_score below 70"
    if not has_distance_transfer(row):
        return False, "distance_score below 35; current-condition transfer not confirmed"
    return True, "past_performance_score>=70 and distance_score>=35"


def ppq_classification(row: dict[str, object], candidate: bool, gate_pass: bool) -> tuple[str, str]:
    past = is_past_high(row)
    distance = has_distance_transfer(row)
    finish = to_int(row.get("actual_finish"))
    actual_top3 = finish in {1, 2, 3}
    actual_top5 = bool(finish and finish <= 5)

    if not candidate:
        return "OUT_OF_SCOPE", ""
    if gate_pass and actual_top3:
        return "PPQ-1", "PPQ-4"
    if gate_pass and not actual_top3:
        return "PPQ-9", "PPQ-10"
    if past and not distance and not actual_top5:
        return "PPQ-5", "PPQ-10"
    if past and not distance:
        return "PPQ-7", "PPQ-10"
    if distance and not past:
        return "PPQ-10", "PPQ-6"
    return "PPQ-11", ""


def apply_quality_shadow(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    shadow = [deepcopy(row) for row in rows]
    details: list[dict[str, object]] = []
    gate_rows: list[dict[str, object]] = []
    by_race: dict[object, list[dict[str, object]]] = defaultdict(list)
    for row in shadow:
        by_race[row.get("race_id")].append(row)

    for race_rows in by_race.values():
        top = max(to_float(row.get("adjusted_score"), 0.0) for row in race_rows)
        bottom = min(to_float(row.get("adjusted_score"), 0.0) for row in race_rows)
        spread = max(1.0, top - bottom)

        for row in race_rows:
            candidate, ability_signals, penalty, source = applicable(row)
            gate_pass, gate_reason = quality_gate(row) if candidate else (False, "not previous ability override candidate")
            recovery = abs(penalty) * (1.0 - MULTIPLIER) if gate_pass else 0.0
            old_adjusted = to_float(row.get("adjusted_score"), 0.0)
            old_decision_score = to_float(row.get("decision_score"), 0.0)
            score_delta = (recovery / spread) * 0.45
            shadow_score = max(0.0, min(1.0, round(old_decision_score + score_delta, 3)))
            ppq_primary, ppq_secondary = ppq_classification(row, candidate, gate_pass)

            row["shadow_adjusted_score"] = round(old_adjusted + recovery, 3)
            row["shadow_decision_score"] = shadow_score
            row["ability_override_applied"] = gate_pass
            row["quality_candidate"] = candidate
            row["quality_gate_pass"] = gate_pass
            row["quality_gate_reason"] = gate_reason
            row["ppq_primary"] = ppq_primary
            row["ppq_secondary"] = ppq_secondary
            row["ability_signals"] = ability_signals
            row["race_shape_penalty_used"] = penalty
            row["penalty_source"] = source
            row["score_delta"] = round(score_delta, 3)

            if candidate:
                gate_rows.append(gate_row(row))

        ranked = sorted(
            race_rows,
            key=lambda item: (to_float(item.get("shadow_adjusted_score"), 0.0), to_int(item.get("ai_rank"), 999) * -1),
            reverse=True,
        )
        for rank, row in enumerate(ranked, start=1):
            row["shadow_rank"] = rank
            row["shadow_decision"] = shadow_decision(row, rank)

    for row in shadow:
        details.append(detail_row(row))
    return shadow, details, gate_rows


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
        "quality_candidate": row.get("quality_candidate"),
        "quality_gate_pass": row.get("quality_gate_pass"),
        "quality_gate_reason": row.get("quality_gate_reason"),
        "ppq_primary": row.get("ppq_primary"),
        "ppq_secondary": row.get("ppq_secondary"),
        "score_delta": row.get("score_delta"),
        "decision_changed": official != shadow,
        "case_effect": effect_label(row),
    }


def gate_row(row: dict[str, object]) -> dict[str, object]:
    return {
        "race_id": row.get("race_id"),
        "horse_name": row.get("horse_name"),
        "official_decision": row.get("official_decision"),
        "actual_finish": to_int(row.get("actual_finish")),
        "ai_rank": row.get("ai_rank"),
        "race_shape_score": row.get("race_shape_score"),
        "past_performance_score": row.get("past_performance_score"),
        "distance_score": row.get("distance_score"),
        "ability_signals": "; ".join(row.get("ability_signals") or []),
        "quality_gate_pass": row.get("quality_gate_pass"),
        "quality_gate_reason": row.get("quality_gate_reason"),
        "ppq_primary": row.get("ppq_primary"),
        "ppq_secondary": row.get("ppq_secondary"),
    }


def metrics(rows: list[dict[str, object]], details: list[dict[str, object]]) -> dict[str, object]:
    decisions = Counter(row.get("shadow_decision") for row in rows)
    race_ids = sorted({row.get("race_id") for row in rows})
    buy_rows = [row for row in rows if row.get("shadow_decision") == "BUY"]
    pass_rows = [row for row in rows if row.get("shadow_decision") == "PASS"]
    buy_by_race = Counter(row.get("race_id") for row in buy_rows)
    rescued = [row for row in details if row["case_effect"] in {"rescued_fn_to_buy", "rescued_pass_to_caution"}]
    new_fp = [row for row in details if row["case_effect"] == "new_fp"]
    return {
        "scenario": "past_performance_quality_gate_0.75",
        "race_count": len(race_ids),
        "horse_count": len(rows),
        "candidate_count": sum(1 for row in rows if row.get("quality_candidate")),
        "gate_pass_count": sum(1 for row in rows if row.get("quality_gate_pass")),
        "BUY": decisions.get("BUY", 0),
        "CAUTION": decisions.get("CAUTION", 0),
        "PASS": decisions.get("PASS", 0),
        "BUY_top3": sum(1 for row in buy_rows if row.get("actual_top3")),
        "BUY_top5": sum(1 for row in buy_rows if row.get("actual_top5")),
        "BUY_top3_rate": round(sum(1 for row in buy_rows if row.get("actual_top3")) / len(buy_rows), 3) if buy_rows else 0,
        "BUY_top5_rate": round(sum(1 for row in buy_rows if row.get("actual_top5")) / len(buy_rows), 3) if buy_rows else 0,
        "PASS_top3": sum(1 for row in pass_rows if row.get("actual_top3")),
        "FN": sum(1 for row in rows if row.get("actual_top3") and row.get("shadow_decision") != "BUY"),
        "FP": sum(1 for row in rows if row.get("shadow_decision") == "BUY" and not row.get("actual_top3")),
        "top5_hit": sum(1 for row in rows if to_int(row.get("shadow_rank"), 999) <= 5 and row.get("actual_top3")),
        "buy_zero_races": sum(1 for race_id in race_ids if buy_by_race.get(race_id, 0) == 0),
        "rescued_pass_success": len(rescued),
        "rescued_fn_to_buy": sum(1 for row in rescued if row["case_effect"] == "rescued_fn_to_buy"),
        "rescued_fn_to_caution": sum(1 for row in rescued if row["case_effect"] == "rescued_pass_to_caution"),
        "new_fp": len(new_fp),
        "net_quality_rescue": len(rescued) - len(new_fp),
        "existing_buy_success_changed": sum(
            1
            for row in rows
            if row.get("official_decision") == "BUY"
            and row.get("actual_top3")
            and row.get("shadow_decision") != "BUY"
        ),
    }


def group_comparison(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups = {
        "A_past_high_top3": lambda row: is_past_high(row) and row.get("actual_top3"),
        "B_past_high_4plus": lambda row: is_past_high(row) and not row.get("actual_top3"),
        "C_past_high_PASS": lambda row: is_past_high(row) and row.get("official_decision") == "PASS",
        "D_past_high_BUY": lambda row: is_past_high(row) and row.get("official_decision") == "BUY",
        "E_shape_negative_past_high_top3": lambda row: is_past_high(row) and race_shape_penalty(row)[0] < 0 and row.get("actual_top3"),
        "F_shape_negative_past_high_4plus": lambda row: is_past_high(row) and race_shape_penalty(row)[0] < 0 and not row.get("actual_top3"),
    }
    output = []
    for name, predicate in groups.items():
        selected = [row for row in rows if predicate(row)]
        finishes = [to_int(row.get("actual_finish")) for row in selected if to_int(row.get("actual_finish"))]
        output.append(
            {
                "group": name,
                "count": len(selected),
                "BUY": sum(1 for row in selected if row.get("official_decision") == "BUY"),
                "CAUTION": sum(1 for row in selected if row.get("official_decision") == "CAUTION"),
                "PASS": sum(1 for row in selected if row.get("official_decision") == "PASS"),
                "top3": sum(1 for row in selected if row.get("actual_top3")),
                "top5": sum(1 for row in selected if row.get("actual_top5")),
                "avg_finish": round(sum(finishes) / len(finishes), 2) if finishes else "",
                "median_finish": statistics.median(finishes) if finishes else "",
                "distance_transfer_count": sum(1 for row in selected if has_distance_transfer(row)),
                "race_shape_negative_count": sum(1 for row in selected if race_shape_penalty(row)[0] < 0),
            }
        )
    return output


def six_horse_details(rows: list[dict[str, object]], details: list[dict[str, object]]) -> list[dict[str, object]]:
    detail_map = {(row["race_id"], row["horse_name"]): row for row in details}
    previous_detail = {
        (row.get("race_id"), row.get("horse_name")): row
        for row in read_csv(OUT_DIR / "ability_override_detail.csv")
        if row.get("scenario") == "0.75"
    }
    output = []
    for key in sorted(SIX_HORSES):
        row = detail_map.get(key, {})
        prev = previous_detail.get(key, {})
        output.append(
            {
                "race_id": key[0],
                "horse_name": key[1],
                "previous_exists": bool(prev),
                "previous_official_decision": prev.get("official_decision"),
                "previous_shadow_decision": prev.get("shadow_decision"),
                "previous_finish": prev.get("actual_finish"),
                "current_official_decision": row.get("official_decision"),
                "quality_shadow_decision": row.get("shadow_decision"),
                "actual_finish": row.get("actual_finish"),
                "past_performance_score": row.get("past_performance_score"),
                "distance_score": row.get("distance_score"),
                "race_shape_score": row.get("race_shape_score"),
                "quality_gate_pass": row.get("quality_gate_pass"),
                "quality_gate_reason": row.get("quality_gate_reason"),
                "ppq_primary": row.get("ppq_primary"),
                "ppq_secondary": row.get("ppq_secondary"),
                "case_effect": row.get("case_effect"),
            }
        )
    return output


def write_markdown(
    baseline: dict[str, object],
    summary: dict[str, object],
    group_rows: list[dict[str, object]],
    six_rows: list[dict[str, object]],
    warnings: list[str],
) -> None:
    decision = "ACCEPT" if summary["rescued_pass_success"] >= 1 and summary["new_fp"] == 0 else "REJECT"
    lines = [
        "# PastPerformance Quality Shadow Validation",
        "",
        "## Baseline",
        "",
        f"- Races / horses: {baseline['race_count']} / {baseline['horse_count']}",
        f"- BUY / CAUTION / PASS: {baseline['BUY']} / {baseline['CAUTION']} / {baseline['PASS']}",
        f"- FN / FP: {baseline['FN']} / {baseline['FP']}",
        f"- BUY Top3 rate: {baseline['BUY_top3_rate']}",
        "",
        "## Quality Gate",
        "",
        "- Base population: previous Ability Override candidates only.",
        f"- Gate: past_performance_score >= {PAST_HIGH_THRESHOLD:g} and distance_score >= {DISTANCE_TRANSFER_THRESHOLD:g}.",
        "- Interpretation: high past performance is accepted only when current distance suitability supports transferability.",
        "- Shadow multiplier: RaceShape penalty x 0.75, gate-pass horses only.",
        "",
        "## Shadow Result",
        "",
        "| candidate | gate pass | BUY | CAUTION | PASS | BUY Top3 rate | FN | FP | rescued to BUY | rescued to CAUTION | new FP | net quality rescue |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {summary['candidate_count']} | {summary['gate_pass_count']} | {summary['BUY']} | "
            f"{summary['CAUTION']} | {summary['PASS']} | {summary['BUY_top3_rate']} | "
            f"{summary['FN']} | {summary['FP']} | {summary['rescued_fn_to_buy']} | "
            f"{summary['rescued_fn_to_caution']} | {summary['new_fp']} | {summary['net_quality_rescue']} |"
        ),
        "",
        "## Six-Horse Audit",
        "",
        "| horse | previous | quality shadow | finish | gate | PPQ |",
        "|---|---|---|---:|---|---|",
    ]
    for row in six_rows:
        lines.append(
            f"| {row['horse_name']} | {row['previous_official_decision']}->{row['previous_shadow_decision']} | "
            f"{row['current_official_decision']}->{row['quality_shadow_decision']} | {row['actual_finish']} | "
            f"{row['quality_gate_pass']} | {row['ppq_primary']} {row['ppq_secondary']} |"
        )
    lines.extend(
        [
            "",
            "## Group Comparison",
            "",
            "| group | count | BUY | CAUTION | PASS | top3 | top5 | distance transfer |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in group_rows:
        lines.append(
            f"| {row['group']} | {row['count']} | {row['BUY']} | {row['CAUTION']} | {row['PASS']} | "
            f"{row['top3']} | {row['top5']} | {row['distance_transfer_count']} |"
        )
    lines.extend(
        [
            "",
            "## Judgment",
            "",
            f"- Final shadow judgment: {decision}",
            "- Production implementation: not recommended yet; this is a cleaner shadow hypothesis, but FN-to-BUY improvement remains zero.",
            "- Next review focus: PastPerformance quality should be separated from raw high score before any production mitigation.",
        ]
    )
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    (OUT_DIR / "past_performance_quality_shadow.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_DIR / "past_performance_quality_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rows, warnings = load_population()
    baseline = baseline_metrics(rows)
    shadow_rows, details, gate_rows = apply_quality_shadow(rows)
    summary = metrics(shadow_rows, details)
    group_rows = group_comparison(rows)
    six_rows = six_horse_details(rows, details)

    write_csv(OUT_DIR / "past_performance_quality_shadow_details.csv", details, DETAIL_FIELDS)
    write_csv(OUT_DIR / "past_performance_quality_gate.csv", gate_rows, list(gate_rows[0].keys()) if gate_rows else [])
    write_csv(OUT_DIR / "past_performance_quality_group_comparison.csv", group_rows, list(group_rows[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_6horse_details.csv", six_rows, list(six_rows[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_shadow_summary.csv", [summary], list(summary.keys()))
    write_csv(
        OUT_DIR / "past_performance_quality_rescued.csv",
        [row for row in details if row["case_effect"] in {"rescued_fn_to_buy", "rescued_pass_to_caution"}],
        DETAIL_FIELDS,
    )
    write_csv(
        OUT_DIR / "past_performance_quality_false_positive.csv",
        [row for row in details if row["case_effect"] == "new_fp"],
        DETAIL_FIELDS,
    )
    write_markdown(baseline, summary, group_rows, six_rows, warnings)

    print("PastPerformance Quality Shadow Validation")
    print(f"races={baseline['race_count']} horses={baseline['horse_count']}")
    print(
        "baseline BUY/CAUTION/PASS="
        f"{baseline['BUY']}/{baseline['CAUTION']}/{baseline['PASS']}"
    )
    print(
        "shadow BUY/CAUTION/PASS="
        f"{summary['BUY']}/{summary['CAUTION']}/{summary['PASS']}"
    )
    print(
        "candidate/gate/rescued/new_fp="
        f"{summary['candidate_count']}/{summary['gate_pass_count']}/"
        f"{summary['rescued_pass_success']}/{summary['new_fp']}"
    )


if __name__ == "__main__":
    main()
