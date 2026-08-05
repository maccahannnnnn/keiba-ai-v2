"""Shadow validation for Ability Override against RaceShape penalties.

This is diagnostic-only.  It builds the 40-race review population from the
existing 22-race baseline reconstruction plus the official 20260725/20260726
review CSVs, applies shadow-only RaceShape penalty mitigation for horses with
multiple ability signals, and writes comparison reports under analysis/reports.
It does not modify production evaluators, DecisionEngine, scores, Knowledge,
CSV specs, or main.py.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.overall_22race_health_check import Overall22RaceHealthCheck


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "analysis" / "reports"
SCENARIOS = [0.75, 0.5, 0.25]
BUY_THRESHOLD = 0.8
CAUTION_THRESHOLD = 0.5


DETAIL_FIELDS = [
    "scenario",
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
    "penalty_source",
    "ability_signal_count",
    "ability_signals",
    "ability_override_applied",
    "score_delta",
    "decision_changed",
    "case_effect",
    "reason",
]


SUMMARY_FIELDS = [
    "scenario",
    "race_count",
    "horse_count",
    "target_count",
    "BUY",
    "CAUTION",
    "PASS",
    "BUY_top3",
    "BUY_top5",
    "BUY_top3_rate",
    "BUY_top5_rate",
    "PASS_top3",
    "FN",
    "FP",
    "top5_hit",
    "buy_zero_races",
    "rescued_pass_success",
    "rescued_fn_to_buy",
    "rescued_fn_to_caution",
    "new_fp",
    "existing_buy_success_changed",
    "net_rescue",
    "judgment",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def to_float(value, default=None):
    if isinstance(value, bool) or value is None or value == "":
        return default
    try:
        return float(str(value).strip())
    except ValueError:
        return default


def to_int(value, default=None):
    number = to_float(value, None)
    return int(number) if number is not None else default


def race_date(race_id: str) -> str:
    parts = str(race_id or "").split("_")
    return parts[1] if len(parts) > 1 else ""


def load_population() -> tuple[list[dict[str, object]], list[str]]:
    warnings: list[str] = []
    rows: list[dict[str, object]] = []

    health = Overall22RaceHealthCheck()
    races22, rows22, errors22 = health._collect("data/analysis", "data/results")
    warnings.extend(f"baseline22: {error}" for error in errors22)
    for row in rows22:
        rows.append(normalize_22_row(row))

    for folder in [ROOT / "reports" / "review_20260725", ROOT / "reports" / "review_20260726"]:
        for row in read_csv(folder / "horse_review.csv"):
            rows.append(normalize_review_row(row, folder.name))

    return rows, warnings


def normalize_22_row(row: dict[str, object]) -> dict[str, object]:
    scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
    decision = str(row.get("decision") or "").upper()
    finish = to_int(row.get("finish_position"))
    return {
        "dataset_group": "baseline_22",
        "race_id": row.get("race_id"),
        "race_date": row.get("race_date") or race_date(str(row.get("race_id") or "")),
        "racecourse": row.get("racecourse"),
        "race_number": row.get("race_number"),
        "horse_name": row.get("horse_name"),
        "official_decision": decision,
        "actual_finish": finish,
        "actual_top3": finish in {1, 2, 3},
        "actual_top5": bool(finish and finish <= 5),
        "ai_rank": to_int(row.get("ai_rank")),
        "final_score": to_float(row.get("final_score"), 0.0),
        "adjusted_score": to_float(row.get("adjusted_score"), 0.0),
        "decision_score": to_float(row.get("decision_score"), 0.0),
        "race_shape_score": to_float(scores.get("shape_score"), 0.0),
        "past_performance_score": to_float(scores.get("past_performance_score"), None),
        "distance_score": to_float(scores.get("distance_score"), None),
        "lap_score": to_float(scores.get("lap_score"), None),
        "course_score": to_float(scores.get("course_shape_score"), None),
        "pace_score": to_float(scores.get("pace_style_score"), None),
        "positive_reasons": "; ".join(row.get("major_plus") or []) if isinstance(row.get("major_plus"), list) else "",
        "risk_reasons": "; ".join(row.get("major_minus") or []) if isinstance(row.get("major_minus"), list) else "",
        "trace_quality": "reconstructed_22_full",
    }


def normalize_review_row(row: dict[str, str], dataset_group: str) -> dict[str, object]:
    decision = str(row.get("official_decision") or row.get("decision") or "").upper()
    finish = to_int(row.get("actual_finish"))
    race_shape_score = to_float(row.get("race_shape_score"), None)
    if race_shape_score is None:
        race_shape_score = to_float(row.get("shape_score"), None)
    return {
        "dataset_group": dataset_group,
        "race_id": row.get("race_id"),
        "race_date": race_date(row.get("race_id", "")),
        "racecourse": row.get("racecourse"),
        "race_number": row.get("race_number"),
        "horse_name": row.get("horse_name"),
        "official_decision": decision,
        "actual_finish": finish,
        "actual_top3": finish in {1, 2, 3},
        "actual_top5": bool(finish and finish <= 5),
        "ai_rank": to_int(row.get("ai_rank")),
        "final_score": to_float(row.get("final_score"), 0.0),
        "adjusted_score": to_float(row.get("adjusted_score"), 0.0),
        "decision_score": to_float(row.get("decision_score"), 0.0),
        "race_shape_score": race_shape_score,
        "past_performance_score": to_float(row.get("ability_score"), None),
        "distance_score": to_float(row.get("distance_score"), None),
        "lap_score": to_float(row.get("lap_suitability_score"), None),
        "course_score": to_float(row.get("course_score"), None),
        "pace_score": to_float(row.get("pace_score"), None),
        "positive_reasons": row.get("positive_reasons", ""),
        "risk_reasons": row.get("risk_reasons", ""),
        "trace_quality": "official_review_csv",
    }


def ability_signals(row: dict[str, object]) -> list[str]:
    signals = []
    past = to_float(row.get("past_performance_score"), None)
    distance = to_float(row.get("distance_score"), None)
    lap = to_float(row.get("lap_score"), None)
    course = to_float(row.get("course_score"), None)
    final_score = to_float(row.get("final_score"), 0.0)
    adjusted = to_float(row.get("adjusted_score"), 0.0)
    positives = str(row.get("positive_reasons") or "")

    if past is not None and past >= 70:
        signals.append(f"past_performance_score={past:g}")
    elif "近走内容" in positives or "過去走" in positives:
        signals.append("past_performance_positive_text")
    if distance is not None and distance >= 35:
        signals.append(f"distance_score={distance:g}")
    elif "距離適性" in positives:
        signals.append("distance_positive_text")
    if lap is not None and lap >= 8:
        signals.append(f"lap_score={lap:g}")
    if course is not None and course >= 8:
        signals.append(f"course_score={course:g}")
    if final_score >= 140:
        signals.append(f"final_score={final_score:g}")
    if adjusted >= 150:
        signals.append(f"adjusted_score={adjusted:g}")
    return signals


def race_shape_penalty(row: dict[str, object]) -> tuple[float, str]:
    score = to_float(row.get("race_shape_score"), None)
    if score is not None and score < 0:
        return score, "race_shape_score"
    risks = str(row.get("risk_reasons") or "")
    if "展開不向き" in risks:
        return -10.0, "risk_text_estimated_展開不向き"
    if "展開面の不安" in risks:
        return -6.0, "risk_text_estimated_展開面の不安"
    return 0.0, "none"


def applicable(row: dict[str, object]) -> tuple[bool, list[str], float, str]:
    penalty, source = race_shape_penalty(row)
    signals = ability_signals(row)
    return penalty < 0 and len(signals) >= 2, signals, penalty, source


def apply_shadow(rows: list[dict[str, object]], multiplier: float) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    shadow = [deepcopy(row) for row in rows]
    details: list[dict[str, object]] = []
    by_race = defaultdict(list)
    for row in shadow:
        by_race[row["race_id"]].append(row)

    for race_id, race_rows in by_race.items():
        top = max(to_float(row.get("adjusted_score"), 0.0) for row in race_rows)
        bottom = min(to_float(row.get("adjusted_score"), 0.0) for row in race_rows)
        spread = max(1.0, top - bottom)
        for row in race_rows:
            ok, signals, penalty, source = applicable(row)
            old_adjusted = to_float(row.get("adjusted_score"), 0.0)
            old_decision_score = to_float(row.get("decision_score"), 0.0)
            recovery = abs(penalty) * (1.0 - multiplier) if ok else 0.0
            shadow_adjusted = old_adjusted + recovery
            score_delta = (recovery / spread) * 0.45
            shadow_score = max(0.0, min(1.0, round(old_decision_score + score_delta, 3)))
            row["shadow_adjusted_score"] = round(shadow_adjusted, 3)
            row["shadow_decision_score"] = shadow_score
            row["ability_override_applied"] = ok
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

    for row in shadow:
        details.append(detail_row(row, multiplier))
    return shadow, details


def shadow_decision(row: dict[str, object], rank: int) -> str:
    official = str(row.get("official_decision") or "").upper()
    if not row.get("ability_override_applied"):
        return official
    if official == "BUY":
        return "BUY"
    score = to_float(row.get("shadow_decision_score"), 0.0)
    official_level = {"PASS": 0, "CAUTION": 1, "BUY": 2}.get(official, 0)
    if score >= BUY_THRESHOLD:
        decision = "BUY" if rank <= 5 else "CAUTION"
    elif score >= CAUTION_THRESHOLD:
        decision = "CAUTION"
    else:
        decision = "PASS"
    shadow_level = {"PASS": 0, "CAUTION": 1, "BUY": 2}.get(decision, 0)
    if shadow_level < official_level:
        return official
    return decision


def detail_row(row: dict[str, object], multiplier: float) -> dict[str, object]:
    official = row.get("official_decision")
    shadow = row.get("shadow_decision")
    finish = to_int(row.get("actual_finish"))
    changed = official != shadow
    effect = "unchanged"
    if changed and official != "BUY" and shadow == "BUY" and finish in {1, 2, 3}:
        effect = "rescued_fn_to_buy"
    elif changed and official == "PASS" and shadow == "CAUTION" and finish in {1, 2, 3}:
        effect = "rescued_pass_to_caution"
    elif changed and shadow == "BUY" and finish and finish >= 4:
        effect = "new_fp"
    elif changed:
        effect = "other_decision_change"
    signals = row.get("ability_signals") or []
    return {
        "scenario": multiplier,
        "race_id": row.get("race_id"),
        "horse_name": row.get("horse_name"),
        "dataset_group": row.get("dataset_group"),
        "official_decision": official,
        "shadow_decision": shadow,
        "actual_finish": finish,
        "ai_rank": row.get("ai_rank"),
        "shadow_rank": row.get("shadow_rank"),
        "final_score": row.get("final_score"),
        "adjusted_score": row.get("adjusted_score"),
        "shadow_adjusted_score": row.get("shadow_adjusted_score"),
        "decision_score": row.get("decision_score"),
        "shadow_decision_score": row.get("shadow_decision_score"),
        "race_shape_score": row.get("race_shape_score"),
        "race_shape_penalty_used": row.get("race_shape_penalty_used"),
        "penalty_source": row.get("penalty_source"),
        "ability_signal_count": len(signals),
        "ability_signals": "; ".join(signals),
        "ability_override_applied": row.get("ability_override_applied"),
        "score_delta": row.get("score_delta"),
        "decision_changed": changed,
        "case_effect": effect,
        "reason": shadow_reason(row),
    }


def shadow_reason(row: dict[str, object]) -> str:
    if not row.get("ability_override_applied"):
        return "not_target"
    return (
        "RaceShape negative with multiple ability signals; "
        f"penalty={row.get('race_shape_penalty_used')} source={row.get('penalty_source')}"
    )


def metrics(rows: list[dict[str, object]], scenario: float, details: list[dict[str, object]]) -> dict[str, object]:
    decisions = Counter(row.get("shadow_decision") for row in rows)
    race_ids = sorted({row.get("race_id") for row in rows})
    buy_rows = [row for row in rows if row.get("shadow_decision") == "BUY"]
    pass_rows = [row for row in rows if row.get("shadow_decision") == "PASS"]
    target_count = sum(1 for row in rows if row.get("ability_override_applied"))
    buy_top3 = sum(1 for row in buy_rows if row.get("actual_top3"))
    buy_top5 = sum(1 for row in buy_rows if row.get("actual_top5"))
    fn = sum(1 for row in rows if row.get("actual_top3") and row.get("shadow_decision") != "BUY")
    fp = sum(1 for row in rows if row.get("shadow_decision") == "BUY" and not row.get("actual_top3"))
    top5_hit = sum(1 for row in rows if to_int(row.get("shadow_rank"), 999) <= 5 and row.get("actual_top3"))
    buy_by_race = Counter(row.get("race_id") for row in buy_rows)
    rescued_pass_success = sum(1 for row in details if row["case_effect"] in {"rescued_fn_to_buy", "rescued_pass_to_caution"})
    rescued_fn_to_buy = sum(1 for row in details if row["case_effect"] == "rescued_fn_to_buy")
    rescued_fn_to_caution = sum(1 for row in details if row["case_effect"] == "rescued_pass_to_caution")
    new_fp = sum(1 for row in details if row["case_effect"] == "new_fp")
    existing_buy_success_changed = sum(
        1
        for row in rows
        if row.get("official_decision") == "BUY"
        and row.get("actual_top3")
        and row.get("shadow_decision") != "BUY"
    )
    judgment = "REJECT"
    if rescued_fn_to_buy > new_fp and existing_buy_success_changed == 0:
        judgment = "ACCEPT"
    elif rescued_pass_success > 0 and new_fp <= rescued_pass_success:
        judgment = "ACCEPT_WITH_NOTE"
    return {
        "scenario": scenario,
        "race_count": len(race_ids),
        "horse_count": len(rows),
        "target_count": target_count,
        "BUY": decisions.get("BUY", 0),
        "CAUTION": decisions.get("CAUTION", 0),
        "PASS": decisions.get("PASS", 0),
        "BUY_top3": buy_top3,
        "BUY_top5": buy_top5,
        "BUY_top3_rate": round(buy_top3 / len(buy_rows), 3) if buy_rows else 0,
        "BUY_top5_rate": round(buy_top5 / len(buy_rows), 3) if buy_rows else 0,
        "PASS_top3": sum(1 for row in pass_rows if row.get("actual_top3")),
        "FN": fn,
        "FP": fp,
        "top5_hit": top5_hit,
        "buy_zero_races": sum(1 for race_id in race_ids if buy_by_race.get(race_id, 0) == 0),
        "rescued_pass_success": rescued_pass_success,
        "rescued_fn_to_buy": rescued_fn_to_buy,
        "rescued_fn_to_caution": rescued_fn_to_caution,
        "new_fp": new_fp,
        "existing_buy_success_changed": existing_buy_success_changed,
        "net_rescue": rescued_fn_to_buy - new_fp,
        "judgment": judgment,
    }


def baseline_metrics(rows: list[dict[str, object]]) -> dict[str, object]:
    race_ids = sorted({row.get("race_id") for row in rows})
    decisions = Counter(row.get("official_decision") for row in rows)
    buy_rows = [row for row in rows if row.get("official_decision") == "BUY"]
    return {
        "race_count": len(race_ids),
        "horse_count": len(rows),
        "BUY": decisions.get("BUY", 0),
        "CAUTION": decisions.get("CAUTION", 0),
        "PASS": decisions.get("PASS", 0),
        "BUY_top3": sum(1 for row in buy_rows if row.get("actual_top3")),
        "BUY_top5": sum(1 for row in buy_rows if row.get("actual_top5")),
        "BUY_top3_rate": round(sum(1 for row in buy_rows if row.get("actual_top3")) / len(buy_rows), 3) if buy_rows else 0,
        "BUY_top5_rate": round(sum(1 for row in buy_rows if row.get("actual_top5")) / len(buy_rows), 3) if buy_rows else 0,
        "PASS_top3": sum(1 for row in rows if row.get("official_decision") == "PASS" and row.get("actual_top3")),
        "FN": sum(1 for row in rows if row.get("actual_top3") and row.get("official_decision") != "BUY"),
        "FP": sum(1 for row in rows if row.get("official_decision") == "BUY" and not row.get("actual_top3")),
        "top5_hit": sum(1 for row in rows if to_int(row.get("ai_rank"), 999) <= 5 and row.get("actual_top3")),
        "buy_zero_races": sum(1 for race_id in race_ids if not any(row.get("race_id") == race_id and row.get("official_decision") == "BUY" for row in rows)),
    }


def write_markdown(baseline: dict[str, object], summaries: list[dict[str, object]], warnings: list[str]) -> None:
    best = choose_best(summaries)
    lines = [
        "# Ability Override Shadow Validation",
        "",
        "## Baseline",
        "",
        f"- Races: {baseline['race_count']}",
        f"- Horses: {baseline['horse_count']}",
        f"- BUY / CAUTION / PASS: {baseline['BUY']} / {baseline['CAUTION']} / {baseline['PASS']}",
        f"- FN / FP: {baseline['FN']} / {baseline['FP']}",
        f"- BUY Top3 rate: {baseline['BUY_top3_rate']}",
        f"- Top5 hit: {baseline['top5_hit']}",
        "",
        "## Shadow Comparison",
        "",
        "| multiplier | target | BUY | CAUTION | PASS | BUY Top3 rate | FN | FP | rescued to BUY | rescued to CAUTION | new FP | net rescue | judgment |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summaries:
        lines.append(
            f"| {row['scenario']} | {row['target_count']} | {row['BUY']} | {row['CAUTION']} | {row['PASS']} | "
            f"{row['BUY_top3_rate']} | {row['FN']} | {row['FP']} | {row['rescued_fn_to_buy']} | "
            f"{row['rescued_fn_to_caution']} | {row['new_fp']} | {row['net_rescue']} | {row['judgment']} |"
        )
    lines.extend(
        [
            "",
            "## Best Multiplier",
            "",
            f"- Best: {best.get('scenario') if best else 'none'}",
            f"- Judgment: {best.get('judgment') if best else 'REJECT'}",
            "",
            "## Final Decision",
            "",
            final_decision(best),
            "",
            "## Notes",
            "",
            "- Shadow only. Production Decision, Evaluators, FinalScore, thresholds, Knowledge, CSV specs, and main.py were not changed.",
            "- 20260725 rows have less evaluator-score detail than 20260726 and baseline22; some RaceShape penalties are estimated from risk text.",
        ]
    )
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    (OUT_DIR / "ability_override_shadow.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def choose_best(summaries: list[dict[str, object]]) -> dict[str, object]:
    if not summaries:
        return {}
    return sorted(
        summaries,
        key=lambda row: (
            row.get("net_rescue", -999),
            row.get("rescued_fn_to_buy", 0),
            -row.get("new_fp", 0),
            row.get("BUY_top3_rate", 0),
        ),
        reverse=True,
    )[0]


def final_decision(best: dict[str, object]) -> str:
    if not best:
        return "REJECT: no scenario could be evaluated."
    if best.get("judgment") == "ACCEPT":
        return "ACCEPT for further Shadow review only. Production implementation is not recommended yet."
    if best.get("judgment") == "ACCEPT_WITH_NOTE":
        return "ACCEPT_WITH_NOTE for another Shadow pass. Production implementation is not recommended yet."
    return "REJECT: Ability Override did not satisfy rescue and FP balance."


def main() -> None:
    rows, warnings = load_population()
    baseline = baseline_metrics(rows)
    all_details: list[dict[str, object]] = []
    rescued_rows: list[dict[str, object]] = []
    fp_rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []

    for multiplier in SCENARIOS:
        shadow_rows, details = apply_shadow(rows, multiplier)
        summary = metrics(shadow_rows, multiplier, details)
        summaries.append(summary)
        all_details.extend(details)
        rescued_rows.extend(row for row in details if row["case_effect"] in {"rescued_fn_to_buy", "rescued_pass_to_caution"})
        fp_rows.extend(row for row in details if row["case_effect"] == "new_fp")

    write_csv(OUT_DIR / "ability_override_shadow.csv", summaries, SUMMARY_FIELDS)
    write_csv(OUT_DIR / "ability_override_detail.csv", all_details, DETAIL_FIELDS)
    write_csv(OUT_DIR / "ability_override_rescued.csv", rescued_rows, DETAIL_FIELDS)
    write_csv(OUT_DIR / "ability_override_false_positive.csv", fp_rows, DETAIL_FIELDS)
    write_markdown(baseline, summaries, warnings)

    result = {
        "baseline": baseline,
        "summaries": summaries,
        "best": choose_best(summaries),
        "outputs": [
            str(OUT_DIR / "ability_override_shadow.md"),
            str(OUT_DIR / "ability_override_shadow.csv"),
            str(OUT_DIR / "ability_override_detail.csv"),
            str(OUT_DIR / "ability_override_false_positive.csv"),
            str(OUT_DIR / "ability_override_rescued.csv"),
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
