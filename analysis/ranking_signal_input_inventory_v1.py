"""Read-only inventory of pre-race TARGET inputs used by the ranking path."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import order avoids the package-level cycle without constructing or running an adapter.
from evaluation.target_trial_adapter import TargetTrialAdapter  # noqa: F401
from importer.target_entry_importer import TargetEntryImporter
from importer.target_history_importer import TargetHistoryImporter


REPORTS = ROOT / "reports"
OUTPUTS = {
    "markdown": REPORTS / "ranking_signal_input_inventory_v1.md",
    "inventory": REPORTS / "ranking_signal_input_inventory_v1.csv",
    "trace": REPORTS / "ranking_signal_usage_trace_v1.csv",
    "candidates": REPORTS / "ranking_signal_candidate_priority_v1.csv",
    "summary": REPORTS / "ranking_signal_summary_v1.json",
    "safety": REPORTS / "ranking_signal_safety_v1.json",
}

PROTECTED = {
    "target_trial_adapter": ROOT / "evaluation" / "target_trial_adapter.py",
    "main": ROOT / "main.py",
    "learning": ROOT / "learning",
    "knowledge": ROOT / "knowledge",
    "baseline": REPORTS / "baseline",
    "ranking_provenance": REPORTS / "ranking_provenance",
}

FIELDS = [
    {
        "field_id": "jockey", "display_name": "騎手", "source_csv": "entry", "source_columns": "騎手 / jockey (25列・22列 index 12)",
        "importer_read": "YES", "internal_saved": "YES: Entry.jockey", "evaluator_referenced": "NO", "score_reflected": "NO", "ranking_reflected": "NO", "explain_reflected": "NO",
        "usage_class": "UNUSED", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "CONDITIONAL", "eligibility_reason": "高カーディナリティ。外部の時点固定priorなしでは同一母集団暗記になる。",
    },
    {
        "field_id": "trainer", "display_name": "調教師", "source_csv": "entry", "source_columns": "調教師 / trainer (25列 index 19; 22列 index 16)",
        "importer_read": "YES", "internal_saved": "YES: Entry.trainer", "evaluator_referenced": "NO", "score_reflected": "NO", "ranking_reflected": "NO", "explain_reflected": "NO",
        "usage_class": "UNUSED", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "CONDITIONAL", "eligibility_reason": "高カーディナリティ。外部の時点固定priorなしでは同一母集団暗記になる。",
    },
    {
        "field_id": "weight_carried", "display_name": "斤量", "source_csv": "entry", "source_columns": "斤量 / weight_carried (index 13)",
        "importer_read": "YES", "internal_saved": "YES: Entry.weight_carried", "evaluator_referenced": "NO", "score_reflected": "NO", "ranking_reflected": "NO", "explain_reflected": "NO",
        "usage_class": "UNUSED", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "YES", "eligibility_reason": "事前数値・両コホート完備。ただし負担と能力代理が混在するためrace内中心化設計が必要。",
    },
    {
        "field_id": "body_weight", "display_name": "当日馬体重", "source_csv": "entry", "source_columns": "当日馬体重 / body_weight (25列 index 16; 22列にはなし)",
        "importer_read": "YES", "internal_saved": "YES: Entry.body_weight; raw_dataへ一時格納", "evaluator_referenced": "NO: RaceContextBuilderで脱落", "score_reflected": "NO (CURRENT_CODE_REPLAY経路)", "ranking_reflected": "NO", "explain_reflected": "NO",
        "usage_class": "EFFECTIVELY_UNUSED", "result_leak_risk": "LOW", "new_collection_required": "YES_FOR_BASELINE",
        "candidate_eligible": "NO", "eligibility_reason": "Baselineで全欠損、Replayも10%基準超過。main.py側の別Analyzerには利用実装があるが本ランキング経路へ未接続。",
    },
    {
        "field_id": "body_weight_diff", "display_name": "馬体重増減", "source_csv": "entry", "source_columns": "馬体重増減 / body_weight_diff (25列 index 17; 22列にはなし)",
        "importer_read": "YES", "internal_saved": "YES: Entry.body_weight_diff; raw_dataへ一時格納", "evaluator_referenced": "NO: RaceContextBuilderで脱落", "score_reflected": "NO (CURRENT_CODE_REPLAY経路)", "ranking_reflected": "NO", "explain_reflected": "NO",
        "usage_class": "EFFECTIVELY_UNUSED", "result_leak_risk": "LOW", "new_collection_required": "YES_FOR_BASELINE",
        "candidate_eligible": "NO", "eligibility_reason": "Baselineで全欠損、Replayも10%基準超過。",
    },
    {
        "field_id": "frame_number", "display_name": "枠番", "source_csv": "entry", "source_columns": "枠番 / frame_number (index 0)",
        "importer_read": "YES", "internal_saved": "YES: Entry.frame_number → horse_result.gate", "evaluator_referenced": "YES: CourseShape; TrackBias", "score_reflected": "YES: course_shape_score / track_bias_score", "ranking_reflected": "YES: integrated→adjusted_score", "explain_reflected": "YES: evaluator comments/reasons",
        "usage_class": "USED", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "NO_ALREADY_USED", "eligibility_reason": "既に最終Rankingへ到達。",
    },
    {
        "field_id": "horse_number", "display_name": "馬番", "source_csv": "entry", "source_columns": "馬番 / horse_number (index 2)",
        "importer_read": "YES", "internal_saved": "YES: Entry.horse_number", "evaluator_referenced": "NO", "score_reflected": "NO", "ranking_reflected": "YES: adjusted_score同点時の降順tie-break", "explain_reflected": "IDENTITY_ONLY",
        "usage_class": "USED_CONTROL_ONLY", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "NO_PROHIBITED", "eligibility_reason": "照合・同点制御のみ。番号自体を予測シグナルにしない。",
    },
    {
        "field_id": "sex_age", "display_name": "性齢", "source_csv": "entry", "source_columns": "性別 index 9 + 年齢 index 10 / sex_age",
        "importer_read": "YES", "internal_saved": "YES: Entry.sex_age", "evaluator_referenced": "NO", "score_reflected": "NO", "ranking_reflected": "NO", "explain_reflected": "NO",
        "usage_class": "UNUSED", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "YES", "eligibility_reason": "低カーディナリティ・両コホート完備。クラス/距離との事前定義interactionが必要。",
    },
    {
        "field_id": "layoff_interval", "display_name": "休養間隔", "source_csv": "horses (過去走日付から導出)", "source_columns": "race_date (year/month/day; current raceより前の最新日)",
        "importer_read": "YES_AS_SOURCE_DATE", "internal_saved": "YES: HistoryRun.race_date / recent_runs", "evaluator_referenced": "NO: PastPerformanceEvaluatorはrace_dateを参照しない", "score_reflected": "NO", "ranking_reflected": "NO", "explain_reflected": "NO",
        "usage_class": "EFFECTIVELY_UNUSED", "result_leak_risk": "LOW_WITH_PRE_DATE_FILTER", "new_collection_required": "NO",
        "candidate_eligible": "YES", "eligibility_reason": "独立した事前情報、両コホート完備、連続量としてAdditive・Explain可能。",
    },
    {
        "field_id": "affiliation", "display_name": "所属", "source_csv": "entry", "source_columns": "所属 / affiliation (25列 index 18; 22列 index 15)",
        "importer_read": "YES", "internal_saved": "YES: Entry.affiliation", "evaluator_referenced": "NO", "score_reflected": "NO", "ranking_reflected": "NO", "explain_reflected": "NO",
        "usage_class": "UNUSED", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "NO_LOW_INDEPENDENCE", "eligibility_reason": "調教師・開催地との重複が強く、独立情報として弱い。",
    },
    {
        "field_id": "owner", "display_name": "馬主", "source_csv": "entry", "source_columns": "馬主 / owner (25列 index 21; 22列 index 18)",
        "importer_read": "YES", "internal_saved": "YES: Entry.owner", "evaluator_referenced": "NO", "score_reflected": "NO", "ranking_reflected": "NO", "explain_reflected": "NO",
        "usage_class": "UNUSED", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "NO_HIGH_CARDINALITY", "eligibility_reason": "高カーディナリティで同一データ暗記リスク。",
    },
    {
        "field_id": "breeder", "display_name": "生産者", "source_csv": "entry", "source_columns": "生産者 / breeder (25列 index 22; 22列 index 19)",
        "importer_read": "YES", "internal_saved": "YES: Entry.breeder", "evaluator_referenced": "NO", "score_reflected": "NO", "ranking_reflected": "NO", "explain_reflected": "NO",
        "usage_class": "UNUSED", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "NO_HIGH_CARDINALITY", "eligibility_reason": "高カーディナリティで同一データ暗記リスク。",
    },
    {
        "field_id": "sire", "display_name": "父", "source_csv": "horses (entry欠損時に補完)", "source_columns": "sire (history fixed index 46)",
        "importer_read": "YES", "internal_saved": "YES: HistoryRun.sire → Entry.sire", "evaluator_referenced": "YES: BloodlineEvaluator", "score_reflected": "YES: bloodline_score", "ranking_reflected": "YES", "explain_reflected": "YES",
        "usage_class": "USED", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "NO_ALREADY_USED", "eligibility_reason": "既に最終Rankingへ到達。",
    },
    {
        "field_id": "broodmare_sire", "display_name": "母父", "source_csv": "horses (entry欠損時に補完)", "source_columns": "broodmare_sire (history fixed index 48)",
        "importer_read": "YES", "internal_saved": "YES: HistoryRun.broodmare_sire → Entry.broodmare_sire", "evaluator_referenced": "YES: BloodlineEvaluator", "score_reflected": "YES: bloodline_score", "ranking_reflected": "YES", "explain_reflected": "YES",
        "usage_class": "USED", "result_leak_risk": "LOW", "new_collection_required": "NO",
        "candidate_eligible": "NO_ALREADY_USED", "eligibility_reason": "既に最終Rankingへ到達。",
    },
]


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def tree_hash(path: Path) -> str:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    for item in sorted(
        x for x in path.rglob("*")
        if x.is_file() and "__pycache__" not in x.parts and x.suffix not in {".pyc", ".pyo"}
    ):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def protected_snapshot():
    return {name: tree_hash(path) for name, path in PROTECTED.items()}


def asset_for(race_id: str, suffix: str) -> Path:
    matches = list((ROOT / "data").rglob(f"{race_id}_{suffix}.csv"))
    if len(matches) != 1:
        raise RuntimeError(f"{race_id} {suffix}: expected one asset, found {len(matches)}")
    return matches[0]


def cohort_race_ids():
    baseline = sorted({row["race_id"] for row in read_csv(REPORTS / "baseline" / "keibaai_baseline_4days_v1_horse.csv")})
    replay_rows = read_csv(REPORTS / "ranking_weight_unique_cohort_v1.csv")
    replay = [row["race_id"] for row in replay_rows]
    if len(replay) != len(set(replay)):
        raise RuntimeError("formal replay cohort contains duplicate race_id")
    return {"BASELINE": baseline, "REPLAY": replay}


def valid(value):
    return value not in (None, "", "不明")


def field_stats(race_ids):
    entry_importer = TargetEntryImporter()
    history_importer = TargetHistoryImporter()
    counts = defaultdict(int)
    race_counts = defaultdict(int)
    total = 0
    for race_id in race_ids:
        entries = entry_importer.load(asset_for(race_id, "entry"))
        histories = history_importer.load(asset_for(race_id, "horses"))
        race_date = datetime.strptime(race_id.split("_")[1], "%Y%m%d")
        total += len(entries)
        per_race = defaultdict(int)
        for entry in entries:
            for name in ("jockey", "trainer", "weight_carried", "body_weight", "body_weight_diff", "frame_number", "horse_number", "sex_age", "affiliation", "owner", "breeder"):
                if valid(getattr(entry, name, None)):
                    counts[name] += 1
                    per_race[name] += 1
            history = histories.get(entry.horse_name)
            runs = history.runs if history else []
            prior_dates = []
            for run in runs:
                try:
                    parsed = datetime.strptime(run.race_date, "%Y/%m/%d")
                except (TypeError, ValueError):
                    continue
                if parsed < race_date:
                    prior_dates.append(parsed)
            if prior_dates:
                counts["layoff_interval"] += 1
                per_race["layoff_interval"] += 1
            for name in ("sire", "broodmare_sire"):
                if any(valid(getattr(run, name, None)) for run in runs):
                    counts[name] += 1
                    per_race[name] += 1
        for name, value in per_race.items():
            if value:
                race_counts[name] += 1
    return {
        name: {
            "horse_total": total,
            "available_horses": counts[name],
            "missing_horses": total - counts[name],
            "missing_rate": round((total - counts[name]) / total, 6),
            "available_races": race_counts[name],
            "race_total": len(race_ids),
        }
        for name in {row["field_id"] for row in FIELDS}
    }


def build_inventory(stats):
    rows = []
    for definition in FIELDS:
        field_id = definition["field_id"]
        row = dict(definition)
        for cohort, prefix in (("BASELINE", "baseline"), ("REPLAY", "replay")):
            values = stats[cohort][field_id]
            row[f"{prefix}_missing_rate"] = f'{values["missing_rate"]:.4f}'
            row[f"{prefix}_available_races"] = values["available_races"]
            row[f"{prefix}_race_total"] = values["race_total"]
            row[f"{prefix}_available_horses"] = values["available_horses"]
            row[f"{prefix}_horse_total"] = values["horse_total"]
        rows.append(row)
    return rows


def build_trace():
    traces = {
        "jockey": [("RAW", "REACHED", "data/*_entry.csv", "index 12"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:128", "Entry.jockey"), ("ADAPTER", "DROPPED", "evaluation/target_trial_adapter.py:164", "_build_raw_data/horse_resultsへ渡さない"), ("EVALUATOR", "NOT_USED", "-", "参照なし"), ("RANKING", "NOT_USED", "-", "影響なし")],
        "trainer": [("RAW", "REACHED", "data/*_entry.csv", "index 19/16"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:132", "Entry.trainer"), ("ADAPTER", "DROPPED", "evaluation/target_trial_adapter.py:164", "下流へ渡さない"), ("EVALUATOR", "NOT_USED", "-", "参照なし"), ("RANKING", "NOT_USED", "-", "影響なし")],
        "weight_carried": [("RAW", "REACHED", "data/*_entry.csv", "index 13"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:127", "Entry.weight_carried"), ("ADAPTER", "DROPPED", "evaluation/target_trial_adapter.py:1001", "_build_raw_dataへ含めない"), ("EVALUATOR", "NOT_USED", "-", "参照なし"), ("RANKING", "NOT_USED", "-", "影響なし")],
        "body_weight": [("RAW", "PARTIAL", "data/*_entry.csv", "25列のみ"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:136", "Entry.body_weight"), ("ADAPTER", "REACHED", "evaluation/target_trial_adapter.py:1013", "raw_dataへ格納"), ("CONTEXT", "DROPPED", "evaluation/race_context_builder.py:47", "返却contextに含まれない"), ("EVALUATOR", "NOT_USED", "-", "CURRENT_CODE_REPLAY参照なし"), ("RANKING", "NOT_USED", "-", "影響なし")],
        "body_weight_diff": [("RAW", "PARTIAL", "data/*_entry.csv", "25列のみ"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:137", "Entry.body_weight_diff"), ("ADAPTER", "REACHED", "evaluation/target_trial_adapter.py:1014", "raw_dataへ格納"), ("CONTEXT", "DROPPED", "evaluation/race_context_builder.py:47", "返却contextに含まれない"), ("EVALUATOR", "NOT_USED", "-", "CURRENT_CODE_REPLAY参照なし"), ("RANKING", "NOT_USED", "-", "影響なし")],
        "frame_number": [("RAW", "REACHED", "data/*_entry.csv", "index 0"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:124", "Entry.frame_number"), ("ADAPTER", "REACHED", "evaluation/target_trial_adapter.py:208", "frame_number/gate"), ("EVALUATOR", "USED", "evaluators/course_shape_evaluator.py:45; evaluators/track_bias_evaluator.py:31", "draw/bias score"), ("SCORE", "USED", "evaluation/target_trial_adapter.py:1294", "course_shape_score/track_bias_score"), ("RANKING", "USED", "evaluation/target_trial_adapter.py:318", "adjusted_scoreへ到達"), ("EXPLAIN", "USED", "engine/explain_engine.py:12", "Evaluator score/commentを説明")],
        "horse_number": [("RAW", "REACHED", "data/*_entry.csv", "index 2"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:125", "Entry.horse_number"), ("ADAPTER", "REACHED", "evaluation/target_trial_adapter.py:207", "horse result identity"), ("SCORE", "NOT_USED", "-", "score非反映"), ("RANKING", "CONTROL_USED", "evaluation/target_trial_adapter.py:318", "adjusted_score同点時tie-break"), ("EXPLAIN", "IDENTITY_ONLY", "-", "予測根拠ではない")],
        "sex_age": [("RAW", "REACHED", "data/*_entry.csv", "index 9+10"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:126", "Entry.sex_age"), ("ADAPTER", "DROPPED", "evaluation/target_trial_adapter.py:164", "下流へ渡さない"), ("EVALUATOR", "NOT_USED", "-", "参照なし"), ("RANKING", "NOT_USED", "-", "影響なし")],
        "layoff_interval": [("RAW", "DERIVABLE", "data/*_horses.csv", "current raceより前の最新race_date"), ("IMPORTER", "REACHED_AS_DATE", "importer/target_history_importer.py:110", "HistoryRun.race_date"), ("ADAPTER", "REACHED_AS_DATE", "evaluation/target_trial_adapter.py:1525", "recent_runsへ保存"), ("EVALUATOR", "NOT_USED", "evaluation/past_performance_evaluator.py:25", "recent_runsは使うがrace_date参照なし"), ("SCORE", "NOT_USED", "-", "休養間隔scoreなし"), ("RANKING", "NOT_USED", "-", "影響なし"), ("EXPLAIN", "NOT_USED", "-", "説明なし")],
        "affiliation": [("RAW", "REACHED", "data/*_entry.csv", "index 18/15"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:133", "Entry.affiliation"), ("ADAPTER", "DROPPED", "evaluation/target_trial_adapter.py:164", "下流へ渡さない"), ("RANKING", "NOT_USED", "-", "影響なし")],
        "owner": [("RAW", "REACHED", "data/*_entry.csv", "index 21/18"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:134", "Entry.owner"), ("ADAPTER", "DROPPED", "evaluation/target_trial_adapter.py:164", "下流へ渡さない"), ("RANKING", "NOT_USED", "-", "影響なし")],
        "breeder": [("RAW", "REACHED", "data/*_entry.csv", "index 22/19"), ("IMPORTER", "REACHED", "importer/target_entry_importer.py:135", "Entry.breeder"), ("ADAPTER", "DROPPED", "evaluation/target_trial_adapter.py:164", "下流へ渡さない"), ("RANKING", "NOT_USED", "-", "影響なし")],
        "sire": [("RAW", "REACHED", "data/*_horses.csv", "history index 46"), ("IMPORTER", "REACHED", "importer/target_history_importer.py:130", "HistoryRun.sire"), ("ADAPTER", "REACHED", "evaluation/target_trial_adapter.py:826", "Entryへ補完"), ("EVALUATOR", "USED", "evaluation/trial_analyzer.py:45", "BloodlineEvaluator"), ("SCORE", "USED", "evaluation/target_trial_adapter.py:1287", "bloodline_score"), ("RANKING", "USED", "evaluation/target_trial_adapter.py:318", "adjusted_scoreへ到達"), ("EXPLAIN", "USED", "engine/explain_engine.py:12", "bloodline strength/risk")],
        "broodmare_sire": [("RAW", "REACHED", "data/*_horses.csv", "history index 48"), ("IMPORTER", "REACHED", "importer/target_history_importer.py:132", "HistoryRun.broodmare_sire"), ("ADAPTER", "REACHED", "evaluation/target_trial_adapter.py:826", "Entryへ補完"), ("EVALUATOR", "USED", "evaluation/trial_analyzer.py:45", "BloodlineEvaluator"), ("SCORE", "USED", "evaluation/target_trial_adapter.py:1287", "bloodline_score"), ("RANKING", "USED", "evaluation/target_trial_adapter.py:318", "adjusted_scoreへ到達"), ("EXPLAIN", "USED", "engine/explain_engine.py:12", "bloodline strength/risk")],
    }
    rows = []
    for field in FIELDS:
        for order, (stage, status, source, evidence) in enumerate(traces[field["field_id"]], start=1):
            rows.append({"field_id": field["field_id"], "display_name": field["display_name"], "stage_order": order, "stage": stage, "status": status, "source_location": source, "evidence": evidence})
    return rows


def build_candidates(inventory):
    by_id = {row["field_id"]: row for row in inventory}
    specs = [
        (1, "layoff_interval", "PRE_RACE_RECENCY_ADDITIVE_V1", "現在より前の最新過去走日からの経過日数を連続的なreadiness情報としてAdditive化", "休養の長短による状態差を既存能力評価と独立に補足できる", "新Shadow feature builder + additive score adapter + explain reason", "LOW_WITH_PRE_DATE_FILTER", "休養X日・race内相対位置・加点/減点寄与を表示", "Baseline/Replay別にrank1・rank1-3 Top3率、NDCG@3、MRR、成功馬保護を比較。閾値は評価前固定", "SMALL_TO_MEDIUM", "MEDIUM", "両コホートのrank1またはrank1-3が同方向でない、または既存Top3捕捉を悪化させる"),
        (2, "weight_carried", "CARRIED_WEIGHT_CONTEXT_ADDITIVE_V1", "race内中心化した斤量差を性齢条件と分離し、負担情報としてAdditive化", "負担差は既存Evaluatorにない事前情報だが、能力代理との符号混在に注意", "新Shadow feature builder + additive score adapter + explain reason", "LOW", "斤量・race平均との差・寄与を表示", "設計を事前固定しBaseline/Replay別ランキング指標で比較", "MEDIUM", "MEDIUM", "コホート間で符号不一致、または成功Top3の順位を過度に破壊"),
        (3, "sex_age", "SEX_AGE_CONTEXT_ADDITIVE_V1", "性別・年齢とクラス/距離の事前定義interactionをAdditive化", "低カーディナリティで暗記を避けつつ成熟度差を補足できる可能性", "新Shadow categorical mapper + additive score adapter + explain reason", "LOW", "性齢カテゴリ・適用した事前ルール・寄与を表示", "ルールを評価前固定しBaseline/Replay別ランキング指標で比較", "MEDIUM", "LOW_TO_MEDIUM", "対象セルが少なすぎる、コホート間で方向不一致、改善が特定条件だけ"),
    ]
    rows = []
    for rank, field_id, candidate, direction, why, implementation, leak, explain, validation, effort, effect, revert in specs:
        source = by_id[field_id]
        rows.append({
            "priority": rank, "candidate_id": candidate, "input_field": field_id,
            "unused_evidence": f'{source["usage_class"]}; {source["evaluator_referenced"]}; ranking={source["ranking_reflected"]}',
            "evaluation_direction": direction, "ranking_rationale": why, "implementation_points": implementation,
            "baseline_missing_rate": source["baseline_missing_rate"], "replay_missing_rate": source["replay_missing_rate"],
            "leak_risk": leak, "explain_method": explain, "shadow_validation": validation,
            "implementation_effort": effort, "expected_effect": effect, "withdrawal_condition": revert,
            "selected": "YES" if rank == 1 else "NO",
        })
    return rows


def write_csv_new(path, rows):
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json_new(path, value):
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def markdown(summary, inventory, candidates):
    def pct(value):
        return f"{float(value) * 100:.2f}%"
    lines = [
        "# Ranking Signal Input Inventory v1", "",
        f"- 判定: **{summary['final_status']}**", "- 監査範囲: TARGET entry/horses → Importer → CURRENT_CODE_REPLAY内部表現 → Evaluator → Score → Ranking/Explain", "- 実行: 既存Raw資産の読取りと静的コード追跡のみ。Replay/Evaluator/Weight再計算、結果を使うPRE再計算は未実施。", "",
        "## 母集団", "",
        f"- Baseline: {summary['cohorts']['baseline']['race_count']}レース / {summary['cohorts']['baseline']['horse_count']}頭", f"- 正式Replay: {summary['cohorts']['replay']['race_count']}レース / {summary['cohorts']['replay']['horse_count']}頭", "- 両コホートは合算していない。結果列は欠損率・候補選定に使用していない。", "",
        "## 実利用の結論", "",
        "|項目|分類|Baseline欠損|Replay欠損|Ranking到達|候補適格性|", "|---|---:|---:|---:|---:|---:|",
    ]
    for row in inventory:
        lines.append(f"|{row['display_name']}|{row['usage_class']}|{pct(row['baseline_missing_rate'])}|{pct(row['replay_missing_rate'])}|{row['ranking_reflected']}|{row['candidate_eligible']}|")
    lines += [
        "", "枠番はCourseShape/TrackBiasを介してscore・Ranking・Explainへ到達するため利用済み。馬番はscoreではなくadjusted_score同点時のtie-breakに到達するため制御利用済みです。騎手・調教師・斤量・性齢・所属・馬主・生産者はEntryに保存されてもAdapter下流へ渡らず、未使用です。馬体重/増減はraw_dataへ一時格納されますがRaceContextBuilderで落ちるため実質未使用です。", "",
        "main.py系Analyzerには馬体重/増減のscore実装がありますが、今回の正式Baseline/ReplayのCURRENT_CODE_REPLAYランキング経路とは別です。別経路に列名や関数があることを利用済み根拠にはしていません。", "",
        "## 候補順位", "",
        "|順位|候補|入力|欠損 (Baseline / Replay)|期待|選定|", "|---:|---|---|---|---|---|",
    ]
    for row in candidates:
        lines.append(f"|{row['priority']}|{row['candidate_id']}|{row['input_field']}|{pct(row['baseline_missing_rate'])} / {pct(row['replay_missing_rate'])}|{row['expected_effect']}|{row['selected']}|")
    lines += [
        "", "## 最優先Shadow候補", "",
        "**PRE_RACE_RECENCY_ADDITIVE_V1（休養間隔）**を1件だけ選定します。両コホート960頭で欠損0%、当該レース結果を使わず算出可能で、現在より前の最新過去走日に限定すればリークを遮断できます。既存scoreへAdditiveかつFeature Flag OFFで実装でき、説明には経過日数・race内相対位置・寄与を明示できます。", "",
        "閾値や効果方向は今回の結果を見て決めていません。次フェーズでは変換式・clip・係数・ACCEPT/REVERT条件を実行前に固定し、BaselineとReplayを混ぜず全馬ランキング（rank1、rank1-3のTop3率、NDCG@3、MRR）で同方向かを検証します。", "",
        "## 非選定理由", "",
        "- 騎手/調教師: 0%欠損だが高カーディナリティ。同じ960頭の結果からpriorを作ると暗記・リークになるため、外部の時点固定実績がない現状では選定しない。", "- 馬体重/増減: Baseline 100%欠損、Replay約29%欠損で10%原則を満たさない。", "- 馬番: 番号自体の予測利用は禁止。枠番は既に利用済み。", "- 斤量/性齢: 利用可能だが符号・interaction設計が休養間隔より複雑なため第2・第3候補。", "",
        "## 40%目標への寄与見立て", "",
        "未使用の独立情報を全馬へ追加する価値はありますが、この棚卸しだけでは30.3%/33.7%から40%への到達を数量保証できません。一次成功条件は両コホートでrank1またはrank1-3が同方向に改善し、既存Top3捕捉を破壊しないことです。", "",
        "## 次アクション", "",
        "次の1回でPRE_RACE_RECENCY_ADDITIVE_V1をShadow-only・Feature Flag OFF既定で実装します。追加Replayや他層診断へは移りません。", "",
        "## Claude独立レビュー論点", "",
        "1. horses CSVが当時点snapshotであり、current raceより前の日付だけを選ぶ実装で将来日混入を構造的に拒否できるか。", "2. 休養間隔の変換式・clip・係数が結果を見る前に固定され、同一母集団でチューニングされないか。", "3. Feature Flag OFFでscore/rank/explainが完全一致し、ON出力がShadow専用rootに限定されるか。", "",
    ]
    return "\n".join(lines)


def main():
    existing = [str(path) for path in OUTPUTS.values() if path.exists()]
    if existing:
        raise FileExistsError(f"existing artifacts would be overwritten: {existing}")
    before = protected_snapshot()
    cohorts = cohort_race_ids()
    stats = {name: field_stats(race_ids) for name, race_ids in cohorts.items()}
    inventory = build_inventory(stats)
    trace = build_trace()
    candidates = build_candidates(inventory)
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "schema_version": "ranking_signal_summary_v1", "generated_at": generated_at,
        "final_status": "SHADOW_CANDIDATE_FOUND", "decision_code": "A",
        "scope": "READ_ONLY_INPUT_USAGE_INVENTORY",
        "cohorts": {
            "baseline": {"race_count": len(cohorts["BASELINE"]), "horse_count": stats["BASELINE"]["jockey"]["horse_total"], "combined_with_replay": False},
            "replay": {"race_count": len(cohorts["REPLAY"]), "horse_count": stats["REPLAY"]["jockey"]["horse_total"], "formal_unique_race_count": len(set(cohorts["REPLAY"])), "combined_with_baseline": False},
        },
        "inventory_item_count": len(inventory),
        "usage_counts": dict(sorted(defaultdict(int, {key: sum(row["usage_class"] == key for row in inventory) for key in {row["usage_class"] for row in inventory}}).items())),
        "used_fields": [row["field_id"] for row in inventory if row["usage_class"].startswith("USED")],
        "unused_fields": [row["field_id"] for row in inventory if row["usage_class"] == "UNUSED"],
        "effectively_unused_fields": [row["field_id"] for row in inventory if row["usage_class"] == "EFFECTIVELY_UNUSED"],
        "candidate_count": len(candidates), "selected_candidate": candidates[0]["candidate_id"],
        "selected_input": candidates[0]["input_field"],
        "candidate_basis": "0% missing in both cohorts; pre-race date only; unused in current ranking; additive/explainable within two weeks",
        "leakage_conclusion": "PASS_IF_CURRENT_RACE_AND_FUTURE_DATES_ARE_REJECTED",
        "forty_percent_outlook": "PLAUSIBLE_SIGNAL_TO_TEST_NOT_QUANTIFIED_OR_GUARANTEED",
        "next_action": "IMPLEMENT_ONE_SHADOW_CANDIDATE_PRE_RACE_RECENCY_ADDITIVE_V1",
        "forbidden_actions_executed": [], "target_trial_adapter_run_count": 0, "replay_run_count": 0,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    write_csv_new(OUTPUTS["inventory"], inventory)
    write_csv_new(OUTPUTS["trace"], trace)
    write_csv_new(OUTPUTS["candidates"], candidates)
    write_json_new(OUTPUTS["summary"], summary)
    if OUTPUTS["markdown"].exists():
        raise FileExistsError(OUTPUTS["markdown"])
    OUTPUTS["markdown"].write_text(markdown(summary, inventory, candidates), encoding="utf-8")
    after = protected_snapshot()
    changed = [name for name in before if before[name] != after[name]]
    safety = {
        "schema_version": "ranking_signal_safety_v1", "generated_at": generated_at,
        "status": "PASS" if not changed else "FAIL", "read_only_diagnostic": True,
        "protected_hashes_before": before, "protected_hashes_after": after, "protected_changes": changed,
        "target_trial_adapter_run_count": 0, "replay_run_count": 0, "evaluator_run_count": 0,
        "weight_recalculation_count": 0, "result_used_for_pre_recalculation": False,
        "production_write_count": 0, "learning_write_count": 0, "normal_ledger_write_count": 0,
        "new_artifacts_only": True,
    }
    write_json_new(OUTPUTS["safety"], safety)
    print(json.dumps({"status": summary["final_status"], "items": len(inventory), "selected": summary["selected_candidate"], "safety": safety["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
