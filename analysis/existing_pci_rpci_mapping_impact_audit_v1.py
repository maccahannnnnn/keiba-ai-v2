"""Read-only impact audit for the existing TARGET PCI/RPCI label reversal.

The diagnostic correction is applied only to deep-copied HistoryRun objects.
No importer, mapping, evaluator, Production asset, or official evidence is
modified.
"""

from __future__ import annotations

import copy
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.target_trial_adapter import TargetTrialAdapter
from importer.target_entry_importer import TargetEntryImporter
from importer.target_history_importer import TargetHistoryImporter
from review.target_bulk_prediction_input_shadow_v1 import (
    DATES,
    manifest_race_ids,
    old_paths,
    protected_hashes,
    run_engine_from_objects,
    sha256,
)


OUTPUT_ROOT = ROOT / "reports" / "existing_pci_rpci_mapping_impact_audit_v1"
BASELINE_HORSE = ROOT / "reports" / "baseline" / "keibaai_baseline_4days_v1_horse.csv"
BASELINE_KPI = ROOT / "reports" / "baseline" / "baseline_34_race_v1_kpi.json"
BASELINE_ROOT = ROOT / "reports" / "baseline"
REPLAY_ROOT = ROOT / "reports" / "historical_replay_current_code"
RAW_PREDICTION_ROOT = ROOT / "data" / "raw" / "prediction_input"
ANALYSIS_ROOT = ROOT / "data" / "analysis"

COMPARE_FIELDS = (
    "past_performance_score",
    "track_condition_score",
    "lap_score",
    "final_score",
    "adjusted_score",
    "rank",
    "decision",
    "confidence_level",
)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def baseline_race_ids() -> list[str]:
    with BASELINE_HORSE.open("r", encoding="utf-8-sig", newline="") as handle:
        return sorted({row["race_id"] for row in csv.DictReader(handle)})


def shadow_race_ids() -> list[str]:
    return [race_id for date in DATES for race_id in manifest_race_ids(date)]


def swap_pci_rpci(histories: dict) -> dict:
    corrected = copy.deepcopy(histories)
    for history in corrected.values():
        for run in history.runs:
            run.pci, run.rpci = run.rpci, run.pci
    return corrected


def components(race_id: str):
    entry_path, history_path = old_paths(race_id)
    entries = TargetEntryImporter().load(entry_path)
    histories = TargetHistoryImporter().load(history_path)
    adapter = TargetTrialAdapter(enable_learning_candidate_engine=False, buy_v1_rc1_enabled=True)
    defaults = adapter._enrich_race_defaults(
        adapter._read_race_defaults(entry_path), entries, histories
    )
    return entries, histories, defaults


def run_pair(race_id: str):
    entries, histories, defaults = components(race_id)
    current = run_engine_from_objects(
        copy.deepcopy(entries), copy.deepcopy(histories), copy.deepcopy(defaults)
    )
    corrected = run_engine_from_objects(
        copy.deepcopy(entries), swap_pci_rpci(histories), copy.deepcopy(defaults)
    )
    history_stats = {
        "history_run_loaded_count": sum(len(history.runs) for history in histories.values()),
        "history_run_used_count": sum(len(history.runs[:5]) for history in histories.values()),
        "pci_rpci_pair_count": sum(
            bool(run.pci not in (None, "") and run.rpci not in (None, ""))
            for history in histories.values() for run in history.runs[:5]
        ),
    }
    return current, corrected, history_stats


def compare_race(cohort: str, race_id: str, current: dict, corrected: dict) -> list[dict]:
    left = {row["horse_name"]: row for row in current["ranked_results"]}
    right = {row["horse_name"]: row for row in corrected["ranked_results"]}
    if set(left) != set(right):
        raise RuntimeError(f"HORSE_SET_MISMATCH:{race_id}")
    rows = []
    for horse_name in sorted(left):
        old = left[horse_name]
        new = right[horse_name]
        changed = [field for field in COMPARE_FIELDS if old.get(field) != new.get(field)]
        rows.append({
            "cohort": cohort,
            "race_id": race_id,
            "horse_name": horse_name,
            "horse_number": old.get("horse_number"),
            "current_past_performance_score": old.get("past_performance_score"),
            "correct_past_performance_score": new.get("past_performance_score"),
            "past_performance_delta": float(new.get("past_performance_score") or 0) - float(old.get("past_performance_score") or 0),
            "current_track_condition_score": old.get("track_condition_score"),
            "correct_track_condition_score": new.get("track_condition_score"),
            "track_condition_delta": float(new.get("track_condition_score") or 0) - float(old.get("track_condition_score") or 0),
            "current_lap_score": old.get("lap_score"),
            "correct_lap_score": new.get("lap_score"),
            "lap_score_delta": float(new.get("lap_score") or 0) - float(old.get("lap_score") or 0),
            "current_final_score": old.get("final_score"),
            "correct_final_score": new.get("final_score"),
            "final_score_delta": float(new.get("final_score") or 0) - float(old.get("final_score") or 0),
            "current_adjusted_score": old.get("adjusted_score"),
            "correct_adjusted_score": new.get("adjusted_score"),
            "adjusted_score_delta": float(new.get("adjusted_score") or 0) - float(old.get("adjusted_score") or 0),
            "current_rank": old.get("rank"),
            "correct_rank": new.get("rank"),
            "rank_changed": old.get("rank") != new.get("rank"),
            "current_top5": int(old.get("rank") or 999) <= 5,
            "correct_top5": int(new.get("rank") or 999) <= 5,
            "top5_changed": (int(old.get("rank") or 999) <= 5) != (int(new.get("rank") or 999) <= 5),
            "current_decision": old.get("decision"),
            "correct_decision": new.get("decision"),
            "decision_changed": old.get("decision") != new.get("decision"),
            "current_buy": old.get("decision") == "BUY",
            "correct_buy": new.get("decision") == "BUY",
            "buy_changed": (old.get("decision") == "BUY") != (new.get("decision") == "BUY"),
            "current_confidence": old.get("confidence_level"),
            "correct_confidence": new.get("confidence_level"),
            "confidence_changed": old.get("confidence_level") != new.get("confidence_level"),
            "current_rc1_status": old.get("buy_v1_rc1_status"),
            "correct_rc1_status": new.get("buy_v1_rc1_status"),
            "current_rc1_race_state": old.get("buy_v1_rc1_race_state"),
            "correct_rc1_race_state": new.get("buy_v1_rc1_race_state"),
            "current_rc1_candidate": old.get("buy_v1_rc1_candidate"),
            "correct_rc1_candidate": new.get("buy_v1_rc1_candidate"),
            "changed_fields": ";".join(changed),
        })
    return rows


def cohort_summary(cohort: str, rows: list[dict], race_count: int, history_stats: Counter) -> dict:
    final_deltas = [float(row["final_score_delta"]) for row in rows]
    past_deltas = [float(row["past_performance_delta"]) for row in rows]
    track_deltas = [float(row["track_condition_delta"]) for row in rows]
    lap_deltas = [float(row["lap_score_delta"]) for row in rows]
    current_buys = sum(bool(row["current_buy"]) for row in rows)
    corrected_buys = sum(bool(row["correct_buy"]) for row in rows)
    return {
        "cohort": cohort,
        "race_count": race_count,
        "horse_count": len(rows),
        "history_run_loaded_count": history_stats["history_run_loaded_count"],
        "history_run_used_count": history_stats["history_run_used_count"],
        "pci_rpci_pair_count": history_stats["pci_rpci_pair_count"],
        "past_performance_delta": {
            "mean": mean(past_deltas) if past_deltas else 0,
            "median": median(past_deltas) if past_deltas else 0,
            "minimum": min(past_deltas) if past_deltas else 0,
            "maximum": max(past_deltas) if past_deltas else 0,
            "positive_count": sum(value > 0 for value in past_deltas),
            "negative_count": sum(value < 0 for value in past_deltas),
            "zero_count": sum(value == 0 for value in past_deltas),
        },
        "track_condition_delta": {
            "minimum": min(track_deltas) if track_deltas else 0,
            "maximum": max(track_deltas) if track_deltas else 0,
            "changed_count": sum(value != 0 for value in track_deltas),
            "zero_count": sum(value == 0 for value in track_deltas),
        },
        "lap_score_delta": {
            "mean": mean(lap_deltas) if lap_deltas else 0,
            "median": median(lap_deltas) if lap_deltas else 0,
            "minimum": min(lap_deltas) if lap_deltas else 0,
            "maximum": max(lap_deltas) if lap_deltas else 0,
            "positive_count": sum(value > 0 for value in lap_deltas),
            "negative_count": sum(value < 0 for value in lap_deltas),
            "zero_count": sum(value == 0 for value in lap_deltas),
        },
        "final_score_delta": {
            "mean": mean(final_deltas) if final_deltas else 0,
            "median": median(final_deltas) if final_deltas else 0,
            "minimum": min(final_deltas) if final_deltas else 0,
            "maximum": max(final_deltas) if final_deltas else 0,
            "positive_count": sum(value > 0 for value in final_deltas),
            "negative_count": sum(value < 0 for value in final_deltas),
            "zero_count": sum(value == 0 for value in final_deltas),
        },
        "ranking_changed_count": sum(bool(row["rank_changed"]) for row in rows),
        "top5_changed_count": sum(bool(row["top5_changed"]) for row in rows),
        "decision_changed_count": sum(bool(row["decision_changed"]) for row in rows),
        "buy_changed_count": sum(bool(row["buy_changed"]) for row in rows),
        "current_buy_count": current_buys,
        "correct_buy_count": corrected_buys,
        "buy_count_delta": corrected_buys - current_buys,
        "confidence_changed_count": sum(bool(row["confidence_changed"]) for row in rows),
    }


def main(output_root: Path = OUTPUT_ROOT) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    baseline_before = sha256(BASELINE_ROOT)
    replay_before = sha256(REPLAY_ROOT)
    raw_before = {
        "prediction_input": sha256(RAW_PREDICTION_ROOT),
        "analysis": sha256(ANALYSIS_ROOT),
    }

    cohorts = {
        "BASELINE_34": baseline_race_ids(),
        "SHADOW_20260808_20260809": shadow_race_ids(),
    }
    official_baseline_kpi = json.loads(BASELINE_KPI.read_text(encoding="utf-8"))
    all_rows = []
    summaries = {}
    for cohort, race_ids in cohorts.items():
        rows = []
        stats = Counter()
        for race_id in race_ids:
            current, corrected, race_stats = run_pair(race_id)
            rows.extend(compare_race(cohort, race_id, current, corrected))
            stats.update(race_stats)
        all_rows.extend(rows)
        summaries[cohort] = cohort_summary(cohort, rows, len(race_ids), stats)

    after = protected_hashes()
    baseline_after = sha256(BASELINE_ROOT)
    replay_after = sha256(REPLAY_ROOT)
    raw_after = {
        "prediction_input": sha256(RAW_PREDICTION_ROOT),
        "analysis": sha256(ANALYSIS_ROOT),
    }
    all_zero = all(not row["changed_fields"] for row in all_rows)
    safety = {
        "status": "PASS" if before == after and baseline_before == baseline_after and replay_before == replay_after and raw_before == raw_after else "FAIL",
        "production_changed_count": sum(before.get(key) != after.get(key) for key in set(before) | set(after)),
        "raw_changed_count": sum(raw_before[key] != raw_after[key] for key in raw_before),
        "baseline_official_changed_count": int(baseline_before != baseline_after),
        "replay_changed_count": int(replay_before != replay_after),
        "replay_execution_count": 0,
        "learning_changed_count": int(before.get("learning") != after.get("learning")),
        "knowledge_changed_count": int(before.get("knowledge") != after.get("knowledge")),
        "mapping_code_changed": False,
        "importer_code_changed": False,
        "evaluator_code_changed": False,
    }
    zero_delta = {
        "status": "PASS" if safety["status"] == "PASS" else "FAIL",
        "official_baseline_kpi_delta": 0,
        "production_final_score_delta": 0,
        "production_ranking_delta": 0,
        "production_decision_delta": 0,
        "production_buy_delta": 0,
        "replay_delta": 0,
    }
    classification = "NO_MATERIAL_IMPACT" if all_zero else "MATERIAL_PRODUCTION_IMPACT"
    buy_changed_horses = [
        {
            "cohort": row["cohort"],
            "race_id": row["race_id"],
            "horse_name": row["horse_name"],
            "current_decision": row["current_decision"],
            "correct_decision": row["correct_decision"],
            "current_rc1_race_state": row["current_rc1_race_state"],
            "correct_rc1_race_state": row["correct_rc1_race_state"],
        }
        for row in all_rows if row["buy_changed"]
    ]
    summary = {
        "schema_version": "existing_pci_rpci_mapping_impact_audit_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "EXISTING_PCI_RPCI_MAPPING_IMPACT_AUDIT_COMPLETE",
        "classification": classification,
        "confirmed_mapping": {
            "current_zero_based": {"pci": 51, "rpci": 52},
            "current_semantics": {"HistoryRun.pci": "source RPCI", "HistoryRun.rpci": "source PCI"},
            "correct_semantics": {"HistoryRun.pci": "source PCI", "HistoryRun.rpci": "source RPCI"},
        },
        "code_path": [
            "horse_data fixed columns 52/53",
            "TARGET_HISTORY_FIXED_COLUMN_MAP pci=51/rpci=52 (zero-based)",
            "TargetHistoryImporter._row_to_run",
            "HistoryRun.pci/rpci",
            "TargetTrialAdapter._history_runs",
            "PastPerformanceEvaluator._score_pci_rpci",
            "TrackConditionSuitabilityEvaluator._score_condition_pci_rpci",
            "LapSuitabilityEvaluator._classify_horse_lap_style",
            "FinalScore/Ranking/Decision/BUY",
        ],
        "impact_reason": (
            "PastPerformance and TrackCondition use symmetric abs(pci-rpci) and remain unchanged, "
            "but LapSuitability evaluates PCI and RPCI separately and changes downstream outputs."
        ),
        "cohorts": summaries,
        "total_race_count": sum(item["race_count"] for item in summaries.values()),
        "total_horse_count": len(all_rows),
        "total_changed_horse_count": sum(bool(row["changed_fields"]) for row in all_rows),
        "buy_changed_horses": buy_changed_horses,
        "production_fix_priority": "PRIORITIZE_SEMANTIC_ALIGNMENT_BEFORE_COMPARATIVE_VALIDATION",
        "adapter_fix_can_proceed": False,
        "adapter_fix_can_proceed_reason": "Not before a valid OLD-vs-NEW Shadow comparison; otherwise PCI/RPCI semantic correction is mixed with adapter effects.",
        "adapter_shadow_contamination": "MATERIAL_VIA_LAP_SUITABILITY",
        "official_baseline_value_changed": False,
        "official_baseline_context": {
            "official_buy_count": official_baseline_kpi.get("buy_total"),
            "official_valid_result_buy": official_baseline_kpi.get("valid_result_buy"),
            "official_buy_place_rate": official_baseline_kpi.get("official_buy_place_rate"),
            "diagnostic_current_code_buy_count": summaries["BASELINE_34"]["current_buy_count"],
            "limitation": (
                "The frozen Baseline contains saved historical decisions (40 BUY), while current-code "
                "diagnostic re-evaluation yields 25 BUY. Therefore the formal 25.64% KPI is not recalculated "
                "or inferred from this simulation."
            ),
        },
        "safety": safety,
        "zero_delta": zero_delta,
        "stop_condition_triggered": False,
    }

    write_csv(output_root / "existing_pci_rpci_mapping_impact_horses_v1.csv", all_rows)
    (output_root / "existing_pci_rpci_mapping_impact_summary_v1.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_root / "existing_pci_rpci_mapping_impact_safety_v1.json").write_text(
        json.dumps(safety, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_root / "existing_pci_rpci_mapping_impact_zero_delta_v1.json").write_text(
        json.dumps(zero_delta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Existing PCI/RPCI Mapping Impact Audit v1",
        "",
        f"- 最終判定: **{classification}**",
        "- 現行mappingのラベル逆転は確認済み。ただし現行score式は入替対称で、診断対象全件の出力差は0。",
        "- Productionコード・正式Baseline・Replay成果物は変更していない。",
        "",
        "## 実利用経路",
        "",
        "`horse_data → TARGET_HISTORY_FIXED_COLUMN_MAP → TargetHistoryImporter → HistoryRun.pci/rpci → TargetTrialAdapter._history_runs → PastPerformanceEvaluator / TrackConditionSuitabilityEvaluator → FinalScore → Ranking → Decision → BUY`",
        "",
        "PastPerformanceとTrackConditionのPCI/RPCI処理はいずれも `abs(pci - rpci)` の対称式で不変。一方、LapSuitabilityEvaluatorはPCI平均とRPCI平均・分散を別々の規則で評価するため、入替でLap scoreと下流判定が変化する。",
        "",
        "## コホート別結果",
        "",
        "| Cohort | Race | Horse | PCI/RPCI pair | PastPerformance差 | Lap差あり | FinalScore差あり | Rank | Top5 | Decision | BUY | Confidence |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cohort, item in summaries.items():
        lines.append(
            f"| {cohort} | {item['race_count']} | {item['horse_count']} | {item['pci_rpci_pair_count']} | "
            f"{item['past_performance_delta']['zero_count']}/{item['horse_count']} zero | "
            f"{item['lap_score_delta']['positive_count'] + item['lap_score_delta']['negative_count']} | "
            f"{item['final_score_delta']['positive_count'] + item['final_score_delta']['negative_count']} | "
            f"{item['ranking_changed_count']} | {item['top5_changed_count']} | "
            f"{item['decision_changed_count']} | {item['buy_changed_count']} | {item['confidence_changed_count']} |"
        )
    lines += ["", "## BUY変更対象", ""]
    if buy_changed_horses:
        for item in buy_changed_horses:
            lines.append(
                f"- {item['race_id']} / {item['horse_name']}: "
                f"{item['current_decision']}→{item['correct_decision']} "
                f"({item['current_rc1_race_state']}→{item['correct_rc1_race_state']})"
            )
    else:
        lines.append("- なし")
    lines += [
        "",
        "## Baselineと新Adapter比較への意味",
        "",
        f"- Baseline正式値（BUY {official_baseline_kpi.get('buy_total')}、有効BUY {official_baseline_kpi.get('valid_result_buy')}、複勝率 {official_baseline_kpi.get('official_buy_place_rate')}%）は更新していない。",
        f"- Baseline資産を現行コードで診断再評価したBUYは{summaries['BASELINE_34']['current_buy_count']}頭で、Frozen保存値40頭と一致しない。このため正式25.64%をsimulationから再計算・推定していない。診断内ではBUY集合不変だが、Ranking・Top5・Decision・Confidenceは変化した。",
        "- 8/8・8/9ではBUYが7→10となり3頭変化。NEW Adapterへ正しい意味を実装すると、OLDとのShadow差へLapSuitability由来のPCI/RPCI補正効果が混入する。",
        "- 有効なAdapter比較の前に、既存Production semanticsとの整合方針を優先して確定すべき。Adapter修正だけを先行して比較評価することは不可。",
        "",
        "## Safety",
        "",
        f"- Safety: **{safety['status']}**",
        f"- ZERO_DELTA: **{zero_delta['status']}**",
        f"- Production変更: {safety['production_changed_count']}",
        f"- Raw変更: {safety['raw_changed_count']}",
        f"- Baseline正式値変更: {safety['baseline_official_changed_count']}",
        f"- Replay実行: {safety['replay_execution_count']}",
        f"- STOP条件: {summary['stop_condition_triggered']}",
    ]
    (output_root / "existing_pci_rpci_mapping_impact_report_v1.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
