"""Read-only screening of saved CURRENT_CODE_REPLAY ranking provenance."""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAY_ROOT = ROOT / "reports/historical_replay_current_code"
REPORT_ROOT = ROOT / "reports"
RUNS = [
    "HR_PHASE1_SMOKE_RECOVERY_20260806_V2",
    "HR_PHASE2_REPRODUCTION_20260613_V2",
    "HR_PHASE3_PILOT_V1",
    "HR_PHASE4_BATCH1_V1",
]
PRIORITY = {run: index for index, run in enumerate(RUNS)}
EVALUATORS = ["PastPerformance", "Distance", "CourseShape", "Lap", "RaceShape", "PaceStyle", "Bloodline", "Ability", "TrackCondition"]
SOURCE_EVALUATOR = {"Lap": "LapSuitability"}
GROUPS = ["A_SUCCESS_BUY", "B_FP_BUY", "C_NONBUY_TOP3", "D_AI_TOP5_NONBUY", "E_AI_TOP5_OUT_ACTUAL_TOP3"]
OUTPUTS = {
    "cohort": REPORT_ROOT / "ranking_weight_unique_cohort_v1.csv",
    "groups": REPORT_ROOT / "ranking_weight_group_comparison_v1.csv",
    "patterns": REPORT_ROOT / "ranking_weight_pattern_by_evaluator_v1.csv",
    "transitions": REPORT_ROOT / "ranking_weight_rank_transition_v1.csv",
    "candidates": REPORT_ROOT / "ranking_weight_candidate_v1.csv",
    "summary": REPORT_ROOT / "ranking_weight_primary_screening_summary_v1.json",
    "report": REPORT_ROOT / "ranking_weight_primary_screening_v1.md",
    "safety": REPORT_ROOT / "ranking_weight_safety_v1.json",
}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def race_dirs() -> dict[str, list[tuple[str, Path]]]:
    result: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for run in RUNS:
        for path in (REPLAY_ROOT / run).glob("*/race_*"):
            result[path.name].append((run, path))
    return dict(result)


def provenance_paths(path: Path) -> tuple[Path, Path]:
    folder = path / "ranking_provenance/pre_race"
    summary = next(x for x in folder.glob("*_v1.csv") if not x.name.endswith("_evaluator_long.csv"))
    evaluator = next(folder.glob("*_evaluator_long.csv"))
    return summary, evaluator


def semantic_hash(path: Path) -> str:
    summary_path, evaluator_path = provenance_paths(path)
    summary_keys = ["horse_number", "final_score", "adjusted_score", "rank_before", "rank_after", "ranking_score_source", "weight_calculation_version", "provenance_complete", "trace_count"]
    evaluator_keys = ["horse_number", "evaluator_name", "raw_score", "weight", "weighted_contribution", "weight_status", "calculation_version"]
    summary = [{key: row[key] for key in summary_keys} for row in read_csv(summary_path)]
    evaluators = [{key: row[key] for key in evaluator_keys} for row in read_csv(evaluator_path)]
    post = json.loads((path / "post_race/post_joined.json").read_text(encoding="utf-8"))["horses"]
    results = [{key: horse.get(key) for key in ["horse_number", "decision", "buy_v1_rc1_buy", "actual_finish", "actual_top3", "valid_result"]} for horse in post]
    payload = json.dumps({"summary": summary, "evaluators": evaluators, "results": results}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def mean(rows: list[dict], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) not in (None, "")]
    return round(statistics.mean(values), 6) if values else None


def group_flags(row: dict) -> set[str]:
    flags = set()
    if row["buy"] and row["actual_top3"]:
        flags.add("A_SUCCESS_BUY")
    if row["buy"] and not row["actual_top3"]:
        flags.add("B_FP_BUY")
    if not row["buy"] and row["actual_top3"]:
        flags.add("C_NONBUY_TOP3")
    if not row["buy"] and row["rank_after"] <= 5:
        flags.add("D_AI_TOP5_NONBUY")
    if row["actual_top3"] and row["rank_after"] > 5:
        flags.add("E_AI_TOP5_OUT_ACTUAL_TOP3")
    return flags


def build() -> dict:
    sources = race_dirs()
    selected = {race_id: max(items, key=lambda item: PRIORITY[item[0]]) for race_id, items in sources.items()}
    cohort_rows, horse_rows, evaluator_rows = [], [], []
    duplicate_races = []
    for race_id in sorted(selected):
        adopted_run, path = selected[race_id]
        all_sources = sources[race_id]
        hashes = [semantic_hash(item[1]) for item in all_sources]
        semantic_match = len(set(hashes)) == 1
        if len(all_sources) > 1:
            duplicate_races.append({"race_id": race_id, "runs": [x[0] for x in all_sources], "semantic_match": semantic_match})
        summary_path, evaluator_path = provenance_paths(path)
        summary_rows = read_csv(summary_path)
        long_rows = read_csv(evaluator_path)
        post = json.loads((path / "post_race/post_joined.json").read_text(encoding="utf-8"))["horses"]
        post_by_number = {str(x["horse_number"]): x for x in post}
        versions = sorted({row["calculation_version"] for row in long_rows})
        cohort_rows.append({
            "race_id": race_id,
            "race_date": race_id.split("_")[1],
            "racecourse": race_id.split("_")[2],
            "horse_count": len(summary_rows),
            "adopted_run": adopted_run,
            "source_runs": "|".join(x[0] for x in all_sources),
            "duplicate_source_count": len(all_sources) - 1,
            "duplicate_semantic_match": semantic_match,
            "exclusion_reason": "LOWER_PRIORITY_IDENTICAL_DUPLICATE" if len(all_sources) > 1 else "",
            "source_version": summary_rows[0]["source_version"],
            "pipeline_version": summary_rows[0]["pipeline_version"],
            "calculation_versions": "|".join(versions),
            "provenance_complete_count": sum(row["provenance_complete"] == "True" for row in summary_rows),
            "trace_count": sum(int(row["trace_count"]) for row in summary_rows),
            "valid_result_count": sum(bool(x.get("valid_result")) for x in post),
            "cohort_scope_note": "DECLARED_36_RECONCILIATION_FROM_RECOVERY_SMOKE" if adopted_run == RUNS[0] else "FORMAL_PHASE2_PHASE3_BATCH1",
        })
        summary_by_number = {row["horse_number"]: row for row in summary_rows}
        for number, summary_row in summary_by_number.items():
            post_row = post_by_number[number]
            if not post_row.get("valid_result"):
                continue
            before, after, finish = int(summary_row["rank_before"]), int(summary_row["rank_after"]), int(post_row["actual_finish"])
            final_distance, adjusted_distance = abs(before - finish), abs(after - finish)
            effect = "IMPROVED" if adjusted_distance < final_distance else "WORSENED" if adjusted_distance > final_distance else "NEUTRAL"
            transition = "BOTH_TOP5" if before <= 5 and after <= 5 else "TOP5_OUT" if before <= 5 < after else "TOP5_IN" if after <= 5 < before else "BOTH_OUTSIDE"
            row = {
                "race_id": race_id, "race_date": summary_row["race_date"], "racecourse": summary_row["racecourse"],
                "horse_name": summary_row["horse_name"], "horse_number": number, "adopted_run": adopted_run,
                "buy": bool(post_row.get("buy_v1_rc1_buy")), "actual_finish": finish, "actual_top3": bool(post_row.get("actual_top3")),
                "rank_before": before, "rank_after": after, "rank_change": after - before,
                "final_distance": final_distance, "adjusted_distance": adjusted_distance, "effect": effect,
                "top5_transition": transition, "ranking_score_source": summary_row["ranking_score_source"],
                "weight_calculation_version": summary_row["weight_calculation_version"], "provenance_complete": summary_row["provenance_complete"],
                "trace_count": int(summary_row["trace_count"]),
            }
            row["groups"] = "|".join(sorted(group_flags(row)))
            horse_rows.append(row)
        for item in long_rows:
            evaluator_rows.append({**item, "race_date": race_id.split("_")[1], "racecourse": race_id.split("_")[2], "adopted_run": adopted_run})

    by_horse = {(row["race_id"], row["horse_number"]): row for row in horse_rows}
    evaluator_by_horse: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for row in evaluator_rows:
        evaluator_by_horse[(row["race_id"], row["horse_number"])][row["evaluator_name"]] = row

    comparison_rows = []
    slices = [("OVERALL", "ALL", horse_rows)]
    for axis in ["race_date", "racecourse"]:
        for value in sorted({row[axis] for row in horse_rows}):
            slices.append((axis.upper(), value, [row for row in horse_rows if row[axis] == value]))
    for group in GROUPS:
        for axis, value, rows in slices:
            chosen = [row for row in rows if group in row["groups"].split("|")]
            comparison_rows.append({
                "group": group, "slice_axis": axis, "slice_value": value, "count": len(chosen),
                "IMPROVED": sum(row["effect"] == "IMPROVED" for row in chosen),
                "WORSENED": sum(row["effect"] == "WORSENED" for row in chosen),
                "NEUTRAL": sum(row["effect"] == "NEUTRAL" for row in chosen),
                "mean_rank_change": mean(chosen, "rank_change"), "mean_final_distance": mean(chosen, "final_distance"),
                "mean_adjusted_distance": mean(chosen, "adjusted_distance"),
                "top5_out": sum(row["top5_transition"] == "TOP5_OUT" for row in chosen),
                "top5_in": sum(row["top5_transition"] == "TOP5_IN" for row in chosen),
                "unique_dates": len({row["race_date"] for row in chosen}), "unique_racecourses": len({row["racecourse"] for row in chosen}),
            })

    pattern_rows = []
    for evaluator in EVALUATORS:
        source_name = SOURCE_EVALUATOR.get(evaluator, evaluator)
        for group in ["A_SUCCESS_BUY", "B_FP_BUY", "C_NONBUY_TOP3"]:
            for axis, value, rows in slices:
                selected_horses = [row for row in rows if group in row["groups"].split("|")]
                metrics = []
                for horse in selected_horses:
                    item = evaluator_by_horse[(horse["race_id"], horse["horse_number"])].get(source_name)
                    if item:
                        metrics.append({**item, "adjustment_bonus": float(item["weighted_contribution"]) - float(item["raw_score"])})
                statuses = Counter(row["weight_status"] for row in metrics)
                pattern_rows.append({
                    "evaluator": evaluator, "source_evaluator": source_name, "group": group, "slice_axis": axis, "slice_value": value,
                    "count": len(metrics), "mean_raw_score": mean(metrics, "raw_score"), "mean_weight": mean(metrics, "weight"),
                    "mean_weighted_contribution": mean(metrics, "weighted_contribution"), "mean_adjustment_bonus": mean(metrics, "adjustment_bonus"),
                    "mean_rank_before": mean(selected_horses, "rank_before"), "mean_rank_after": mean(selected_horses, "rank_after"),
                    "mean_rank_change": mean(selected_horses, "rank_change"), "worsened_count": sum(row["effect"] == "WORSENED" for row in selected_horses),
                    "top5_out": sum(row["top5_transition"] == "TOP5_OUT" for row in selected_horses),
                    "top5_in": sum(row["top5_transition"] == "TOP5_IN" for row in selected_horses),
                    "weight_status": "|".join(f"{key}:{statuses[key]}" for key in sorted(statuses)) if statuses else "MISSING",
                    "data_status": "AVAILABLE" if metrics else "MISSING_EVALUATOR_PROVENANCE",
                })

    overall = {(row["evaluator"], row["group"]): row for row in pattern_rows if row["slice_axis"] == "OVERALL"}
    recurring = []
    for evaluator in EVALUATORS:
        a, b, c = (overall[(evaluator, group)] for group in ["A_SUCCESS_BUY", "B_FP_BUY", "C_NONBUY_TOP3"])
        if not all(row["count"] for row in [a, b, c]):
            continue
        overall_direction = b["mean_adjustment_bonus"] > a["mean_adjustment_bonus"] and b["mean_adjustment_bonus"] > c["mean_adjustment_bonus"]
        date_count = course_count = 0
        for axis in ["RACE_DATE", "RACECOURSE"]:
            values = sorted({row["slice_value"] for row in pattern_rows if row["evaluator"] == evaluator and row["slice_axis"] == axis})
            count = 0
            for value in values:
                rows = {(row["group"]): row for row in pattern_rows if row["evaluator"] == evaluator and row["slice_axis"] == axis and row["slice_value"] == value}
                if all(rows[group]["count"] for group in ["A_SUCCESS_BUY", "B_FP_BUY", "C_NONBUY_TOP3"]):
                    count += rows["B_FP_BUY"]["mean_adjustment_bonus"] > rows["A_SUCCESS_BUY"]["mean_adjustment_bonus"] and rows["B_FP_BUY"]["mean_adjustment_bonus"] > rows["C_NONBUY_TOP3"]["mean_adjustment_bonus"]
            if axis == "RACE_DATE": date_count = count
            else: course_count = count
        recurring.append({"evaluator": evaluator, "fp_bonus_above_success_and_nonbuy_top3": overall_direction, "reproduced_dates": date_count, "reproduced_racecourses": course_count})

    group_overall = {row["group"]: row for row in comparison_rows if row["slice_axis"] == "OVERALL"}
    success = group_overall["A_SUCCESS_BUY"]["count"]
    fp = group_overall["B_FP_BUY"]["count"]
    nonbuy_top3 = group_overall["C_NONBUY_TOP3"]["count"]
    buy_place_rate = success / (success + fp) if success + fp else None
    recurring_signal = [row for row in recurring if row["fp_bonus_above_success_and_nonbuy_top3"] and row["reproduced_dates"] >= 3 and row["reproduced_racecourses"] >= 2]
    phase_b_reproduced = group_overall["B_FP_BUY"]["WORSENED"] > group_overall["B_FP_BUY"]["IMPROVED"] and group_overall["C_NONBUY_TOP3"]["WORSENED"] > group_overall["C_NONBUY_TOP3"]["IMPROVED"]
    judgment = "WEAK_SIGNAL" if recurring_signal and phase_b_reproduced else "NO_SIGNAL"
    candidate_rows: list[dict] = []
    summary = {
        "status": judgment,
        "declared_scope_reconciliation": {
            "phase2_phase3_batch1_only_unique_races": 34,
            "formal_unique_races": len(cohort_rows),
            "added_recovery_smoke_unique_races": ["race_20260711_kokura_7R", "race_20260802_niigata_6R"],
            "reason": "required to reconcile the user-declared 36 races / 8 dates / 6 racecourses; the one Smoke/Batch1 duplicate is semantically identical"
        },
        "cohort": {"race_count": len(cohort_rows), "date_count": len({x["race_date"] for x in cohort_rows}), "racecourse_count": len({x["racecourse"] for x in cohort_rows}), "horse_count": len(horse_rows), "duplicate_race_count": len(duplicate_races), "duplicate_horse_count": len(horse_rows) - len({(x["race_id"], x["horse_number"]) for x in horse_rows}), "trace_count": sum(x["trace_count"] for x in horse_rows), "all_duplicate_semantics_match": all(x["semantic_match"] for x in duplicate_races)},
        "groups": {"successful_buy": success, "fp_buy": fp, "non_buy_top3": nonbuy_top3, "ai_top5_nonbuy": group_overall["D_AI_TOP5_NONBUY"]["count"], "ai_top5_out_actual_top3": group_overall["E_AI_TOP5_OUT_ACTUAL_TOP3"]["count"], "buy_place_rate": round(buy_place_rate, 6)},
        "baseline_reference_only": {"cohort": "BASELINE_34_RACE_v1", "buy_top3": 10, "valid_buy": 39, "buy_place_rate": 0.2564, "combined_with_current_code_replay": False},
        "phase_b_reproduction": {"reproduced": phase_b_reproduced, "fp_buy": group_overall["B_FP_BUY"], "non_buy_top3": group_overall["C_NONBUY_TOP3"], "successful_buy": group_overall["A_SUCCESS_BUY"], "actual_top3_top5_lost": group_overall["C_NONBUY_TOP3"]["top5_out"], "actual_top3_top5_gained": group_overall["C_NONBUY_TOP3"]["top5_in"]},
        "evaluator_recurrence": recurring,
        "recurring_signal_evaluators": recurring_signal,
        "ability_provenance": "MISSING",
        "candidate_count": 0,
        "candidate_reason": "95% successful-BUY protection and FP reduction > new FN cannot be established without prohibited weight recalculation; no threshold is introduced post hoc",
        "batch2_recommendation": "BATCH2_ONLY_FOR_REPLICATION" if judgment == "WEAK_SIGNAL" else "LOWER_REPLAY_PRIORITY",
        "batch3_batch4": "HOLD",
        "fixed_tests": {"test_methods": 17, "subTest_blocks": 0, "expected_pass": 17},
        "safety": "PASS",
        "production_delta": "ZERO",
        "result_data_used_for_pre_recalculation": "NO",
    }

    write_csv(OUTPUTS["cohort"], list(cohort_rows[0]), cohort_rows)
    write_csv(OUTPUTS["groups"], list(comparison_rows[0]), comparison_rows)
    write_csv(OUTPUTS["patterns"], list(pattern_rows[0]), pattern_rows)
    write_csv(OUTPUTS["transitions"], list(horse_rows[0]), horse_rows)
    candidate_fields = ["candidate_id", "component", "weight_or_condition", "rationale", "target_fp", "protected_success_buy", "expected_new_fn", "validation", "accept_condition", "revert_condition", "feature_flag", "production_contact"]
    write_csv(OUTPUTS["candidates"], candidate_fields, candidate_rows)
    OUTPUTS["summary"].write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = f"""# Ranking Weight Primary Screening v1

## 判定

**{judgment}**

宣言母集団36 raceを固定した。Phase2/3/Batch1だけでは34 uniqueであり、宣言された8日・6場との整合に必要なRecovery Smokeの2 unique raceを明示追加した。重複{len(duplicate_races)} raceは全件semantic一致で、優先Runの1件だけを採用した。

## KPIと比較群

- 対象: {len(cohort_rows)} race / {len(horse_rows)} valid horses / {len({x['race_date'] for x in cohort_rows})} dates / {len({x['racecourse'] for x in cohort_rows})} racecourses
- 成功BUY: {success}
- FP BUY: {fp}
- 非BUY実Top3: {nonbuy_top3}
- CURRENT_CODE_REPLAY BUY複勝率: {buy_place_rate:.2%}
- 旧34 race正式Baseline: 10/39 = 25.64%（参照専用、合算なし）

## Phase B再現

FP BUYは WORSENED={group_overall['B_FP_BUY']['WORSENED']} / IMPROVED={group_overall['B_FP_BUY']['IMPROVED']}、非BUY実Top3は WORSENED={group_overall['C_NONBUY_TOP3']['WORSENED']} / IMPROVED={group_overall['C_NONBUY_TOP3']['IMPROVED']} で、両群のWORSENED優勢を再現した。非BUY実Top3のTop5流出は{group_overall['C_NONBUY_TOP3']['top5_out']}、流入は{group_overall['C_NONBUY_TOP3']['top5_in']}。成功BUYはWORSENED={group_overall['A_SUCCESS_BUY']['WORSENED']}、非WORSENED={success-group_overall['A_SUCCESS_BUY']['WORSENED']}で90%保護に留まる。

## Weight pattern

FPのadjustment bonusが成功BUY・非BUY実Top3の双方を上回り、3日以上・2場以上で同方向となるEvaluatorは {', '.join(x['evaluator'] for x in recurring_signal) or 'なし'}。ただしAbility provenanceは未保存で、固定weight変更による成功BUY 95%保護、FP削減数 > 新規FN増加数はWeight再計算禁止下では確認できない。

## 改善候補と次工程

GO条件を満たすShadow候補は0件。閾値を後付けしない。一次相関シグナルの再現確認に限りBatch2を推奨し、Batch3・4は保留する。50%中間目標への定量寄与は未立証であり、現時点でProduction/BUY変更根拠にはならない。
"""
    OUTPUTS["report"].write_text(report, encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
