"""Validate PastPerformance Quality Guard as an OFF-by-default candidate."""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.past_performance_quality_guard import PastPerformanceQualityGuard
from review.ability_override_shadow_validator import OUT_DIR, baseline_metrics, load_population, to_float, to_int, write_csv


FP5 = {
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
    "actual_finish",
    "ai_rank",
    "official_decision",
    "guard_decision",
    "decision_changed",
    "decision_score",
    "adjusted_decision_score",
    "race_shape_score",
    "past_performance_score",
    "distance_score",
    "quality_guard_candidate",
    "quality_guard_applied",
    "quality_guard_skipped_reason",
    "guard_reason",
    "decision_cap",
    "case_effect",
]


def apply_guard(rows, enabled):
    guard = PastPerformanceQualityGuard(enabled=enabled)
    contexts = race_contexts(rows)
    details = []
    output_rows = []
    for row in rows:
        item = dict(row)
        item["shape_score"] = row.get("race_shape_score")
        item["risk_factors"] = split_text(row.get("risk_reasons"))
        context = contexts.get(row.get("race_id"), {})
        result = guard.apply(
            item,
            context,
            row.get("official_decision"),
            row.get("decision_score"),
        )
        guarded = result.get("guarded_decision") or row.get("official_decision")
        output = dict(row)
        output["guard_decision"] = guarded
        output["quality_guard_result"] = result
        output_rows.append(output)
        details.append(detail_row(row, result, guarded))
    return output_rows, details


def race_contexts(rows):
    by_race = defaultdict(list)
    for row in rows:
        by_race[row.get("race_id")].append(row)
    contexts = {}
    for race_id, race_rows in by_race.items():
        scores = [to_float(row.get("adjusted_score"), None) for row in race_rows]
        scores = [score for score in scores if score is not None]
        contexts[race_id] = {
            "top_score": max(scores) if scores else None,
            "bottom_score": min(scores) if scores else None,
        }
    return contexts


def split_text(value):
    text = str(value or "")
    return [part.strip() for part in text.split(";") if part.strip()]


def detail_row(row, result, guarded):
    official = str(row.get("official_decision") or "")
    finish = to_int(row.get("actual_finish"))
    changed = official != guarded
    effect = "unchanged"
    if changed and official == "PASS" and guarded == "CAUTION" and finish in {1, 2, 3}:
        effect = "rescued_pass_to_caution"
    elif changed and guarded == "BUY" and finish and finish >= 4:
        effect = "new_fp"
    elif changed:
        effect = "other_decision_change"
    return {
        "race_id": row.get("race_id"),
        "horse_name": row.get("horse_name"),
        "dataset_group": row.get("dataset_group"),
        "actual_finish": finish,
        "ai_rank": row.get("ai_rank"),
        "official_decision": official,
        "guard_decision": guarded,
        "decision_changed": changed,
        "decision_score": row.get("decision_score"),
        "adjusted_decision_score": result.get("adjusted_decision_score"),
        "race_shape_score": row.get("race_shape_score"),
        "past_performance_score": row.get("past_performance_score"),
        "distance_score": row.get("distance_score"),
        "quality_guard_candidate": result.get("quality_guard_candidate"),
        "quality_guard_applied": result.get("quality_guard_applied"),
        "quality_guard_skipped_reason": result.get("quality_guard_skipped_reason"),
        "guard_reason": result.get("guard_reason"),
        "decision_cap": result.get("decision_cap"),
        "case_effect": effect,
    }


def metrics(label, rows, details):
    decisions = Counter(row.get("guard_decision", row.get("official_decision")) for row in rows)
    buy_rows = [row for row in rows if row.get("guard_decision", row.get("official_decision")) == "BUY"]
    pass_rows = [row for row in rows if row.get("guard_decision", row.get("official_decision")) == "PASS"]
    race_ids = sorted({row.get("race_id") for row in rows})
    return {
        "scenario": label,
        "race_count": len(race_ids),
        "horse_count": len(rows),
        "guard_candidate_count": sum(1 for row in details if row.get("quality_guard_candidate")),
        "guard_applied_count": sum(1 for row in details if row.get("quality_guard_applied")),
        "decision_changed_count": sum(1 for row in details if row.get("decision_changed")),
        "PASS_to_CAUTION": sum(1 for row in details if row.get("official_decision") == "PASS" and row.get("guard_decision") == "CAUTION"),
        "CAUTION_to_BUY": sum(1 for row in details if row.get("official_decision") == "CAUTION" and row.get("guard_decision") == "BUY"),
        "PASS_to_BUY": sum(1 for row in details if row.get("official_decision") == "PASS" and row.get("guard_decision") == "BUY"),
        "BUY_changed": sum(1 for row in details if row.get("official_decision") == "BUY" and row.get("guard_decision") != "BUY"),
        "BUY": decisions.get("BUY", 0),
        "CAUTION": decisions.get("CAUTION", 0),
        "PASS": decisions.get("PASS", 0),
        "BUY_top3": sum(1 for row in buy_rows if row.get("actual_top3")),
        "BUY_top3_rate": round(sum(1 for row in buy_rows if row.get("actual_top3")) / len(buy_rows), 3) if buy_rows else 0,
        "FN": sum(1 for row in rows if row.get("actual_top3") and row.get("guard_decision", row.get("official_decision")) != "BUY"),
        "FP": sum(1 for row in rows if row.get("guard_decision", row.get("official_decision")) == "BUY" and not row.get("actual_top3")),
        "PASS_success": sum(1 for row in pass_rows if row.get("actual_top3")),
        "new_fp": sum(1 for row in details if row.get("case_effect") == "new_fp"),
        "rescued": sum(1 for row in details if row.get("case_effect") == "rescued_pass_to_caution"),
        "net_rescue": sum(1 for row in details if row.get("case_effect") == "rescued_pass_to_caution") - sum(1 for row in details if row.get("case_effect") == "new_fp"),
    }


def off_diff(rows, off_details):
    diffs = []
    for row, detail in zip(rows, off_details):
        if row.get("official_decision") != detail.get("guard_decision"):
            diffs.append(detail)
    return diffs


def fp5_check(on_details):
    by_key = {(row.get("race_id"), row.get("horse_name")): row for row in on_details}
    output = []
    for race_id, horse_name in sorted(FP5):
        row = by_key.get((race_id, horse_name), {})
        output.append(
            {
                "race_id": race_id,
                "horse_name": horse_name,
                "official_decision": row.get("official_decision"),
                "guard_candidate": row.get("quality_guard_candidate"),
                "past_performance_score": row.get("past_performance_score"),
                "distance_score": row.get("distance_score"),
                "race_shape_score": row.get("race_shape_score"),
                "guard_applied": row.get("quality_guard_applied"),
                "decision_changed": row.get("decision_changed"),
                "guard_decision": row.get("guard_decision"),
                "became_buy": row.get("guard_decision") == "BUY",
                "skipped_reason": row.get("quality_guard_skipped_reason"),
            }
        )
    return output


def run_unit_cases():
    guard_off = PastPerformanceQualityGuard(enabled=False)
    guard_on = PastPerformanceQualityGuard(enabled=True)
    base = {
        "shape_score": -3,
        "past_performance_score": 70,
        "distance_score": 35,
    }
    context = {"top_score": 170, "bottom_score": 70}
    cases = [
        ("disabled_returns_input", guard_off, base, "PASS", 0.49, "PASS", False),
        ("non_target_not_adjusted", guard_on, {"shape_score": 0, "past_performance_score": 80, "distance_score": 40}, "PASS", 0.49, "PASS", False),
        ("past_69_not_adjusted", guard_on, {"shape_score": -3, "past_performance_score": 69, "distance_score": 40}, "PASS", 0.49, "PASS", False),
        ("past_70_candidate", guard_on, base, "PASS", 0.499, "CAUTION", True),
        ("distance_34_not_adjusted", guard_on, {"shape_score": -3, "past_performance_score": 70, "distance_score": 34}, "PASS", 0.499, "PASS", False),
        ("distance_35_candidate", guard_on, base, "PASS", 0.499, "CAUTION", True),
        ("pass_capped_to_caution", guard_on, {"shape_score": -10, "past_performance_score": 90, "distance_score": 40}, "PASS", 0.799, "CAUTION", True),
        ("caution_does_not_buy", guard_on, {"shape_score": -10, "past_performance_score": 90, "distance_score": 40}, "CAUTION", 0.799, "CAUTION", False),
        ("buy_unchanged", guard_on, base, "BUY", 0.85, "BUY", False),
        ("missing_inputs_safe", guard_on, {}, "PASS", 0.49, "PASS", False),
        ("unknown_risk_text_not_applied", guard_on, {"risk_factors": ["unknown"], "past_performance_score": 80, "distance_score": 40}, "PASS", 0.499, "PASS", False),
        (
            "target_risk_text_candidate",
            guard_on,
            {"risk_factors": [guard_on.TARGET_RISK_TEXTS[2]], "past_performance_score": 80, "distance_score": 40},
            "PASS",
            0.499,
            "CAUTION",
            True,
        ),
        (
            "same_system_duplicate_risk_limited",
            guard_on,
            {"risk_factors": [guard_on.TARGET_RISK_TEXTS[2], guard_on.TARGET_RISK_TEXTS[3]], "past_performance_score": 80, "distance_score": 40},
            "PASS",
            0.499,
            "CAUTION",
            True,
        ),
        ("trace_contains_guard_fields", guard_on, base, "PASS", 0.499, "CAUTION", True),
        ("high_score_caution_stays_caution", guard_on, {"shape_score": -10, "past_performance_score": 90, "distance_score": 40}, "CAUTION", 0.95, "CAUTION", False),
    ]
    rows = []
    for name, guard, item, decision, score, expected_decision, expected_applied in cases:
        result = guard.apply(item, context, decision, score)
        trace_ok = True
        if name == "trace_contains_guard_fields":
            trace_ok = all(
                key in result
                for key in (
                    "quality_guard_applied",
                    "quality_guard_name",
                    "original_race_shape_penalty",
                    "adjusted_race_shape_penalty",
                    "guard_multiplier",
                    "past_performance_score",
                    "distance_score",
                    "original_decision",
                    "guarded_decision",
                    "decision_cap",
                    "guard_reason",
                )
            )
        passed = (
            result.get("guarded_decision") == expected_decision
            and bool(result.get("quality_guard_applied")) == expected_applied
            and trace_ok
        )
        rows.append(
            {
                "case": name,
                "expected_decision": expected_decision,
                "actual_decision": result.get("guarded_decision"),
                "expected_applied": expected_applied,
                "actual_applied": result.get("quality_guard_applied"),
                "passed": passed,
                "reason": result.get("guard_reason") or result.get("quality_guard_skipped_reason"),
            }
        )
    return rows


def write_markdown(base, off_summary, on_summary, applied, fp5, tests):
    passed = all(row.get("passed") for row in tests)
    accept = (
        not off_summary["decision_changed_count"]
        and on_summary["new_fp"] == 0
        and on_summary["BUY"] == base["BUY"]
        and on_summary["BUY_top3_rate"] == base["BUY_top3_rate"]
        and on_summary["rescued"] == 1
        and passed
    )
    lines = [
        "# PastPerformance Quality Guard Candidate",
        "",
        "## Feature Flag",
        "",
        "- `ENABLE_PAST_PERFORMANCE_QUALITY_GUARD = False`",
        "- Normal operation remains OFF.",
        "",
        "## OFF Validation",
        "",
        f"- Baseline BUY / CAUTION / PASS: {base['BUY']} / {base['CAUTION']} / {base['PASS']}",
        f"- OFF BUY / CAUTION / PASS: {off_summary['BUY']} / {off_summary['CAUTION']} / {off_summary['PASS']}",
        f"- OFF decision changes: {off_summary['decision_changed_count']}",
        "",
        "## ON Validation",
        "",
        f"- Guard candidates: {on_summary['guard_candidate_count']}",
        f"- Guard applied: {on_summary['guard_applied_count']}",
        f"- Decision changes: {on_summary['decision_changed_count']}",
        f"- PASS -> CAUTION: {on_summary['PASS_to_CAUTION']}",
        f"- CAUTION -> BUY: {on_summary['CAUTION_to_BUY']}",
        f"- PASS -> BUY: {on_summary['PASS_to_BUY']}",
        f"- BUY / CAUTION / PASS: {on_summary['BUY']} / {on_summary['CAUTION']} / {on_summary['PASS']}",
        f"- BUY Top3 rate: {on_summary['BUY_top3_rate']}",
        f"- FN / FP / PASS success: {on_summary['FN']} / {on_summary['FP']} / {on_summary['PASS_success']}",
        f"- New FP / rescued / net: {on_summary['new_fp']} / {on_summary['rescued']} / {on_summary['net_rescue']}",
        "",
        "## Applied Horses",
        "",
        "| race_id | horse | finish | decision | score | past | distance |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for row in applied:
        lines.append(
            f"| {row['race_id']} | {row['horse_name']} | {row['actual_finish']} | "
            f"{row['official_decision']}->{row['guard_decision']} | {row['decision_score']}->{row['adjusted_decision_score']} | "
            f"{row['past_performance_score']} | {row['distance_score']} |"
        )
    lines.extend(
        [
            "",
            "## Previous FP5 Check",
            "",
            "| horse | official | candidate | applied | guard decision | became BUY | skipped reason |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in fp5:
        lines.append(
            f"| {row['horse_name']} | {row['official_decision']} | {row['guard_candidate']} | "
            f"{row['guard_applied']} | {row['guard_decision']} | {row['became_buy']} | {row['skipped_reason']} |"
        )
    lines.extend(
        [
            "",
            "## Test Result",
            "",
            f"- Unit-style guard cases passed: {sum(1 for row in tests if row['passed'])}/{len(tests)}",
            "",
            "## Judgment",
            "",
            f"- {'ACCEPT' if accept else 'REJECT'}",
            "- Production candidate can be kept, but normal operation should remain OFF.",
        ]
    )
    (OUT_DIR / "past_performance_quality_guard_candidate.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "ACCEPT" if accept else "REJECT"


def main():
    rows, warnings = load_population()
    base = baseline_metrics(rows)
    off_rows, off_details = apply_guard(rows, enabled=False)
    on_rows, on_details = apply_guard(rows, enabled=True)
    off_summary = metrics("guard_off", off_rows, off_details)
    on_summary = metrics("guard_on", on_rows, on_details)
    diffs = off_diff(rows, off_details)
    applied = [row for row in on_details if row.get("quality_guard_applied")]
    fp5 = fp5_check(on_details)
    tests = run_unit_cases()
    judgment = write_markdown(base, off_summary, on_summary, applied, fp5, tests)

    write_csv(OUT_DIR / "past_performance_quality_guard_off_diff.csv", diffs, DETAIL_FIELDS)
    write_csv(OUT_DIR / "past_performance_quality_guard_on_summary.csv", [off_summary, on_summary], list(on_summary.keys()))
    write_csv(OUT_DIR / "past_performance_quality_guard_on_details.csv", on_details, DETAIL_FIELDS)
    write_csv(OUT_DIR / "past_performance_quality_guard_applied.csv", applied, DETAIL_FIELDS)
    write_csv(OUT_DIR / "past_performance_quality_guard_fp5_check.csv", fp5, list(fp5[0].keys()))
    write_csv(OUT_DIR / "past_performance_quality_guard_tests.csv", tests, list(tests[0].keys()))

    print("PastPerformance Quality Guard Candidate Validation")
    print(f"baseline BUY/CAUTION/PASS={base['BUY']}/{base['CAUTION']}/{base['PASS']}")
    print(f"off changes={off_summary['decision_changed_count']}")
    print(
        "on BUY/CAUTION/PASS="
        f"{on_summary['BUY']}/{on_summary['CAUTION']}/{on_summary['PASS']}"
    )
    print(
        "candidate/applied/rescued/new_fp/net="
        f"{on_summary['guard_candidate_count']}/{on_summary['guard_applied_count']}/"
        f"{on_summary['rescued']}/{on_summary['new_fp']}/{on_summary['net_rescue']}"
    )
    print(f"tests_passed={sum(1 for row in tests if row['passed'])}/{len(tests)}")
    print(f"judgment={judgment}")
    if warnings:
        print(f"warnings={len(warnings)}")


if __name__ == "__main__":
    main()
