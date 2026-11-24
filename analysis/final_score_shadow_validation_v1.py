"""Shadow-only comparison of Production adjusted_score rank vs final_score rank.

Only saved Baseline and CURRENT_CODE_REPLAY evidence is read. No evaluator,
adapter, replay runner, score integrator, decision path, BUY path, Learning,
Knowledge, or Production component is called or mutated.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
REPLAY_ROOT = REPORTS / "historical_replay_current_code"
CANDIDATE_ID = "FINAL_SCORE_SHADOW_V1"
FLAG_NAME = "FINAL_SCORE_SHADOW_ENABLED"
FLAG_DEFAULT = "OFF"

OUTPUTS = {
    "report": REPORTS / "final_score_shadow_report_v1.md",
    "summary": REPORTS / "final_score_shadow_summary_v1.json",
    "metrics": REPORTS / "final_score_shadow_metric_comparison_v1.csv",
    "transitions": REPORTS / "final_score_shadow_rank_transition_v1.csv",
    "safety": REPORTS / "final_score_shadow_safety_v1.json",
    "zero_delta": REPORTS / "final_score_shadow_zero_delta_v1.json",
    "test_manifest": REPORTS / "final_score_shadow_test_manifest_v1.json",
    "claude": REPORTS / "final_score_shadow_claude_review_packet_v1.md",
    "roi": REPORTS / "final_score_shadow_roi_v1.md",
}

PROTECTED = {
    "target_trial_adapter": ROOT / "evaluation" / "target_trial_adapter.py",
    "final_score_integrator": ROOT / "evaluation" / "final_score_integrator.py",
    "decision_engine": ROOT / "engine" / "decision_engine.py",
    "race_decision_engine": ROOT / "engine" / "race_decision_engine.py",
    "main": ROOT / "main.py",
    "learning": ROOT / "learning",
    "knowledge": ROOT / "knowledge",
    "baseline": REPORTS / "baseline",
    "historical_replay": REPLAY_ROOT,
    "ranking_provenance": REPORTS / "ranking_provenance",
}

PROTECTED_ROW_FIELDS = (
    "final_score", "adjusted_score", "production_rank", "decision",
    "race_decision", "buy", "explain_sha256",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    if path.is_file():
        return sha256(path)
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    for item in sorted(
        p for p in path.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}
    ):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def protected_snapshot() -> dict[str, str]:
    return {name: tree_hash(path) for name, path in PROTECTED.items()}


def stable_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value, default=None):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def truth(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def flag_enabled(value=None) -> bool:
    raw = os.environ.get(FLAG_NAME, FLAG_DEFAULT) if value is None else value
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().upper() in {"1", "TRUE", "ON", "YES"}


def _explain_hash(value) -> str:
    if value in (None, ""):
        return "NOT_AVAILABLE"
    return stable_hash(value)


def load_baseline_rows() -> tuple[list[dict], list[dict]]:
    horse_path = REPORTS / "baseline" / "keibaai_baseline_4days_v1_horse.csv"
    race_path = REPORTS / "baseline" / "keibaai_baseline_4days_v1_race.csv"
    horses = read_csv(horse_path)
    races = {row["race_id"]: row for row in read_csv(race_path)}
    rows = []
    for source in horses:
        race = races[source["race_id"]]
        valid = truth(source.get("valid_result"))
        rows.append({
            "cohort": "BASELINE", "race_id": source["race_id"], "race_date": source["race_date"],
            "racecourse": source["race_id"].split("_")[2], "horse_number": str(source["horse_number"]),
            "horse_name": source["horse_name"], "final_score": number(source["final_score"]),
            "adjusted_score": number(source["adjusted_score"]), "production_rank": integer(source["ai_rank"]),
            "decision": source.get("decision", ""), "race_decision": race.get("RaceDecision", ""),
            "buy": truth(source.get("buy_flag")), "explain_sha256": "NOT_AVAILABLE",
            "valid_result": valid,
            "actual_finish": integer(source.get("actual_finish")) if valid else "",
            "actual_top3": truth(source.get("actual_top3")) if valid else False,
            "actual_top5": truth(source.get("actual_top5")) if valid else False,
            "source_run": "BASELINE_34_RACE_V1",
        })
    sources = [
        {"cohort": "BASELINE", "role": "horse", "path": horse_path.relative_to(ROOT).as_posix(), "sha256": sha256(horse_path)},
        {"cohort": "BASELINE", "role": "race", "path": race_path.relative_to(ROOT).as_posix(), "sha256": sha256(race_path)},
    ]
    return rows, sources


def _replay_race_dir(run_id: str, race_id: str) -> Path:
    path = REPLAY_ROOT / run_id / race_id.split("_")[1] / race_id
    if not path.is_dir():
        raise FileNotFoundError(path)
    return path


def load_replay_rows() -> tuple[list[dict], list[dict]]:
    cohort_path = REPORTS / "ranking_weight_unique_cohort_v1.csv"
    cohort = read_csv(cohort_path)
    if len(cohort) != len({row["race_id"] for row in cohort}):
        raise RuntimeError("REPLAY_COHORT_DUPLICATE")
    rows, sources = [], [{"cohort": "REPLAY", "role": "cohort", "path": cohort_path.relative_to(ROOT).as_posix(), "sha256": sha256(cohort_path)}]
    for race in cohort:
        race_id, run_id = race["race_id"], race["adopted_run"]
        race_dir = _replay_race_dir(run_id, race_id)
        folder = race_dir / "ranking_provenance" / "pre_race"
        candidates = [path for path in folder.glob("*_v1.csv") if not path.name.endswith("_evaluator_long.csv")]
        if len(candidates) != 1:
            raise RuntimeError(f"PROVENANCE_ASSET_COUNT:{race_id}:{len(candidates)}")
        provenance_path = candidates[0]
        post_path = race_dir / "post_race" / "post_joined.json"
        provenance = read_csv(provenance_path)
        post = json.loads(post_path.read_text(encoding="utf-8"))["horses"]
        post_by_number = {str(item["horse_number"]): item for item in post}
        if len(post_by_number) != len(post):
            raise RuntimeError(f"POST_HORSE_DUPLICATE:{race_id}")
        for item in provenance:
            result = post_by_number.get(str(item["horse_number"]))
            if result is None:
                raise RuntimeError(f"POST_JOIN_MISSING:{race_id}:{item['horse_number']}")
            valid = bool(result.get("valid_result"))
            rows.append({
                "cohort": "REPLAY", "race_id": race_id, "race_date": race["race_date"],
                "racecourse": race["racecourse"], "horse_number": str(item["horse_number"]),
                "horse_name": item["horse_name"], "final_score": number(item["final_score"]),
                "adjusted_score": number(item["adjusted_score"]), "production_rank": integer(item["rank_after"]),
                "decision": result.get("decision", ""), "race_decision": result.get("race_decision", ""),
                "buy": bool(result.get("buy_v1_rc1_buy")), "explain_sha256": _explain_hash(result.get("explanation")),
                "valid_result": valid,
                "actual_finish": integer(result.get("actual_finish")) if valid else "",
                "actual_top3": bool(result.get("actual_top3")) if valid else False,
                "actual_top5": bool(result.get("actual_top5")) if valid else False,
                "source_run": run_id,
            })
        sources.extend([
            {"cohort": "REPLAY", "race_id": race_id, "role": "pre_race_provenance", "path": provenance_path.relative_to(ROOT).as_posix(), "sha256": sha256(provenance_path)},
            {"cohort": "REPLAY", "race_id": race_id, "role": "post_evaluation_only", "path": post_path.relative_to(ROOT).as_posix(), "sha256": sha256(post_path)},
        ])
    return rows, sources


def group_by_race(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["cohort"], row["race_id"])].append(row)
    return dict(grouped)


def rank_map(rows: list[dict], score_field: str) -> dict[tuple[str, str], int]:
    if any(number(row.get(score_field)) is None for row in rows):
        raise RuntimeError(f"MISSING_SCORE:{score_field}")
    ordered = sorted(
        rows,
        key=lambda row: (-number(row[score_field]), -integer(row["horse_number"], 0), row["horse_name"]),
    )
    return {(row["race_id"], row["horse_number"]): rank for rank, row in enumerate(ordered, 1)}


def rank_shadow_rows(rows: list[dict], enabled=None) -> list[dict]:
    if not flag_enabled(enabled):
        return copy.deepcopy(rows)
    output = copy.deepcopy(rows)
    for race_rows in group_by_race(output).values():
        ranks = rank_map(race_rows, "final_score")
        for row in race_rows:
            row["shadow_rank"] = ranks[(row["race_id"], row["horse_number"])]
    return output


def validate_rows(rows: list[dict]) -> dict:
    keys = [(row["cohort"], row["race_id"], row["horse_number"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise RuntimeError("COHORT_RACE_HORSE_DUPLICATE")
    mismatches = []
    for race_rows in group_by_race(rows).values():
        ranks = rank_map(race_rows, "adjusted_score")
        score_counts = defaultdict(int)
        for row in race_rows:
            score_counts[row["adjusted_score"]] += 1
        for row in race_rows:
            recalculated = ranks[(row["race_id"], row["horse_number"])]
            if recalculated != row["production_rank"]:
                mismatches.append({
                    "cohort": row["cohort"], "race_id": row["race_id"], "horse_number": row["horse_number"],
                    "adjusted_score": row["adjusted_score"], "saved": row["production_rank"], "recalculated": recalculated,
                    "exact_score_tie": score_counts[row["adjusted_score"]] > 1,
                    "reason": "LEGACY_SAVED_TIE_ORDER_DIFFERS_FROM_CURRENT_RULE" if row["cohort"] == "BASELINE" and score_counts[row["adjusted_score"]] > 1 else "UNEXPLAINED",
                })
    non_tie = [row for row in mismatches if not row["exact_score_tie"]]
    replay_mismatch = [row for row in mismatches if row["cohort"] == "REPLAY"]
    status = "PASS" if not mismatches else "PASS_WITH_LEGACY_TIE_DIFFERENCE" if not non_tie and not replay_mismatch else "FAIL"
    return {
        "unique": True, "status": status, "adjusted_rank_mismatch_count": len(mismatches),
        "non_tie_mismatch_count": len(non_tie), "replay_mismatch_count": len(replay_mismatch),
        "adjusted_rank_mismatches": mismatches,
    }


def metric_values(rows: list[dict], rank_field: str) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    actual_top3 = [row for row in valid if row["actual_top3"]]
    selected_top3 = [row for row in valid if integer(row[rank_field], 999) <= 3]
    selected_top5 = [row for row in valid if integer(row[rank_field], 999) <= 5]
    ndcgs, reciprocal = [], []
    for race_rows in group_by_race(valid).values():
        ordered = sorted(race_rows, key=lambda row: integer(row[rank_field], 999))
        dcg = sum((1.0 if row["actual_top3"] else 0.0) / math.log2(index + 2) for index, row in enumerate(ordered[:3]))
        relevant = min(3, sum(row["actual_top3"] for row in ordered))
        ideal = sum(1.0 / math.log2(index + 2) for index in range(relevant))
        ndcgs.append(dcg / ideal if ideal else 0.0)
        first = next((integer(row[rank_field]) for row in ordered if row["actual_top3"]), None)
        reciprocal.append(1.0 / first if first else 0.0)
    return {
        "rank1_3_top3_rate": sum(row["actual_top3"] for row in selected_top3) / len(selected_top3) if selected_top3 else None,
        "mean_actual_top3_rank": statistics.mean(integer(row[rank_field]) for row in actual_top3) if actual_top3 else None,
        "ndcg_at_3": statistics.mean(ndcgs) if ndcgs else None,
        "mrr": statistics.mean(reciprocal) if reciprocal else None,
        "top5_capture_rate": sum(row["actual_top3"] for row in selected_top5) / len(actual_top3) if actual_top3 else None,
        "top5_actual_top3_count": sum(row["actual_top3"] for row in selected_top5),
    }


def cohort_result(rows: list[dict]) -> dict:
    production = metric_values(rows, "production_rank")
    shadow = metric_values(rows, "shadow_rank")
    moved = [row for row in rows if row["production_rank"] != row["shadow_rank"]]
    top3_in = [row for row in rows if row["production_rank"] > 3 >= row["shadow_rank"]]
    top3_out = [row for row in rows if row["production_rank"] <= 3 < row["shadow_rank"]]
    top5_in = [row for row in rows if row["production_rank"] > 5 >= row["shadow_rank"]]
    top5_out = [row for row in rows if row["production_rank"] <= 5 < row["shadow_rank"]]
    delta = {}
    for key in production:
        left, right = production[key], shadow[key]
        delta[key] = round(right - left, 8) if isinstance(left, (int, float)) and isinstance(right, (int, float)) else None
    return {
        "race_count": len({row["race_id"] for row in rows}), "horse_count": len(rows),
        "valid_result_count": sum(row["valid_result"] for row in rows),
        "production": {key: round(value, 8) if isinstance(value, float) else value for key, value in production.items()},
        "shadow": {key: round(value, 8) if isinstance(value, float) else value for key, value in shadow.items()},
        "delta": delta,
        "movement_count": len(moved), "movement_rate": round(len(moved) / len(rows), 8) if rows else 0,
        "top3_inflow_count": len(top3_in), "top3_outflow_count": len(top3_out),
        "actual_top3_top3_inflow_count": sum(row["valid_result"] and row["actual_top3"] for row in top3_in),
        "actual_top3_top3_outflow_count": sum(row["valid_result"] and row["actual_top3"] for row in top3_out),
        "top5_inflow_count": len(top5_in), "top5_outflow_count": len(top5_out),
        "actual_top3_top5_inflow_count": sum(row["valid_result"] and row["actual_top3"] for row in top5_in),
        "actual_top3_top5_outflow_count": sum(row["valid_result"] and row["actual_top3"] for row in top5_out),
    }


def classify_result(results: dict[str, dict]) -> tuple[str, list[str]]:
    reasons = []
    if any(result["movement_rate"] < 0.10 for result in results.values()):
        return "INCONCLUSIVE", ["MOVEMENT_BELOW_10_PERCENT"]
    top3_deltas = [result["delta"]["rank1_3_top3_rate"] for result in results.values()]
    mean_rank_deltas = [result["delta"]["mean_actual_top3_rank"] for result in results.values()]
    if top3_deltas[0] * top3_deltas[1] < 0 or mean_rank_deltas[0] * mean_rank_deltas[1] < 0:
        reasons.append("COHORT_DIRECTION_REVERSAL")
    for cohort, result in results.items():
        if result["delta"]["rank1_3_top3_rate"] < 0:
            reasons.append(f"{cohort}_RANK1_3_TOP3_RATE_WORSENED")
        if result["delta"]["mean_actual_top3_rank"] > 0:
            reasons.append(f"{cohort}_MEAN_ACTUAL_TOP3_RANK_WORSENED")
    if reasons:
        return "REJECT", reasons
    full = all(result["delta"]["rank1_3_top3_rate"] >= 0.03 for result in results.values())
    full = full and all(result["delta"]["mean_actual_top3_rank"] < 0 for result in results.values())
    full = full and all(result["delta"]["ndcg_at_3"] >= 0 and result["delta"]["mrr"] >= 0 for result in results.values())
    if full:
        return "FULL_ACCEPT", ["ALL_FULL_ACCEPT_CONDITIONS_MET"]
    partial = all(result["delta"]["rank1_3_top3_rate"] >= 0.01 for result in results.values())
    if partial:
        return "PARTIAL_ACCEPT", ["BOTH_COHORTS_IMPROVE_BY_AT_LEAST_1_POINT_BUT_FULL_CONDITIONS_NOT_MET"]
    return "REJECT", ["ACCEPT_EFFECT_THRESHOLD_NOT_MET"]


def metric_rows(cohort: str, rows: list[dict], reference_only=False) -> list[dict]:
    slices = [("OVERALL", "ALL", rows)]
    for axis, key in (("DATE", "race_date"), ("RACECOURSE", "racecourse")):
        for value in sorted({row[key] for row in rows}):
            slices.append((axis, value, [row for row in rows if row[key] == value]))
    output = []
    for axis, value, selected in slices:
        production = metric_values(selected, "production_rank")
        shadow = metric_values(selected, "shadow_rank")
        for metric in production:
            left, right = production[metric], shadow[metric]
            delta = right - left if isinstance(left, (int, float)) and isinstance(right, (int, float)) else None
            if delta is None:
                direction = "UNAVAILABLE"
            elif abs(delta) < 1e-12:
                direction = "NEUTRAL"
            elif (metric == "mean_actual_top3_rank" and delta < 0) or (metric != "mean_actual_top3_rank" and delta > 0):
                direction = "IMPROVED"
            else:
                direction = "WORSENED"
            output.append({
                "cohort": cohort, "reference_only": reference_only, "slice_axis": axis, "slice_value": value,
                "race_count": len({row["race_id"] for row in selected}), "horse_count": len(selected),
                "valid_result_count": sum(row["valid_result"] for row in selected), "metric": metric,
                "production_value": "" if left is None else round(left, 8),
                "shadow_value": "" if right is None else round(right, 8),
                "delta": "" if delta is None else round(delta, 8), "direction": direction,
            })
    return output


def transition_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in sorted(rows, key=lambda item: (item["cohort"], item["race_id"], item["production_rank"])):
        production_rank, shadow_rank = row["production_rank"], row["shadow_rank"]
        output.append({
            "cohort": row["cohort"], "race_id": row["race_id"], "race_date": row["race_date"],
            "racecourse": row["racecourse"], "horse_number": row["horse_number"], "horse_name": row["horse_name"],
            "final_score": row["final_score"], "adjusted_score": row["adjusted_score"],
            "production_rank": production_rank, "shadow_rank": shadow_rank,
            "rank_change_shadow_minus_production": shadow_rank - production_rank,
            "moved": shadow_rank != production_rank,
            "top3_transition": "IN" if production_rank > 3 >= shadow_rank else "OUT" if production_rank <= 3 < shadow_rank else "STAY",
            "top5_transition": "IN" if production_rank > 5 >= shadow_rank else "OUT" if production_rank <= 5 < shadow_rank else "STAY",
            "valid_result": row["valid_result"], "actual_finish": row["actual_finish"],
            "actual_top3": row["actual_top3"], "actual_top5": row["actual_top5"],
            "decision": row["decision"], "race_decision": row["race_decision"], "buy": row["buy"],
            "source_run": row["source_run"],
        })
    return output


def roi_rows(status: str) -> list[dict]:
    if status == "FULL_ACCEPT":
        next_action = "Claude review後、Production昇格条件を別途設計"
        redesign = "final_score切替を先に評価し、全面再設計は保留"
    elif status == "PARTIAL_ACCEPT":
        next_action = "SWP_V1診断を3日時間箱で実施"
        redesign = "SWP_V1で候補が出ない場合のみ再評価"
    else:
        next_action = "切替候補を棄却し、誤順位分析の実装点を限定"
        redesign = "原因分離後にのみ着手"
    if status in {"REJECT", "INCONCLUSIVE"}:
        ranks = {"誤順位分析": 1, "Placebo": 2, "ランキング再設計": 3, "騎手Shadow": 4, "final_score Shadow": 5}
    else:
        ranks = {"final_score Shadow": 1, "誤順位分析": 2, "Placebo": 3, "騎手Shadow": 4, "ランキング再設計": 5}
    rows = [
        {"candidate": "final_score Shadow", "judgment": status, "roi_rank": ranks["final_score Shadow"], "next_action": next_action},
        {"candidate": "誤順位分析", "judgment": "GO", "roi_rank": ranks["誤順位分析"], "next_action": "ReplayでTop3流出を起こしたrace/horseを原因層別する"},
        {"candidate": "Placebo", "judgment": "NOT_RUN", "roi_rank": ranks["Placebo"], "next_action": "誤順位分析から単一介入候補が出た場合のみ実施"},
        {"candidate": "騎手Shadow", "judgment": "SAFETY_HOLD", "roi_rank": ranks["騎手Shadow"], "next_action": "履歴Importerの騎手列正式マッピング後のみ再開"},
        {"candidate": "ランキング再設計", "judgment": "CONDITIONAL", "roi_rank": ranks["ランキング再設計"], "next_action": redesign},
    ]
    return sorted(rows, key=lambda row: row["roi_rank"])


def build_roi(status: str, rows: list[dict]) -> str:
    lines = ["# final_score Shadow ROI v1", "", "|候補|判定|ROI順位|次アクション|", "|---|---|---:|---|"]
    lines.extend(f"|{row['candidate']}|{row['judgment']}|{row['roi_rank']}|{row['next_action']}|" for row in rows)
    lines.extend(["", f"現在の最優先候補は `{rows[0]['candidate']}`。判定は `{status}`。", ""])
    return "\n".join(lines)


def build_report(summary: dict) -> str:
    b, r = summary["cohort_results"]["BASELINE"], summary["cohort_results"]["REPLAY"]
    def pct(value): return f"{value:.2%}"
    lines = [
        "# final_score Shadow Validation v1", "", "## Final judgment", "", f"**{summary['final_status']}**", "",
        "Production保存順位は変更せず、Shadow順位だけを `final_score DESC -> horse_number DESC` で生成した。", "",
        "|Cohort|Races|Horses|Valid|Movement|rank1-3 Top3 Production|Shadow|Delta|Mean actual-Top3 rank Production|Shadow|Delta|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"|Baseline|{b['race_count']}|{b['horse_count']}|{b['valid_result_count']}|{b['movement_count']} ({pct(b['movement_rate'])})|{pct(b['production']['rank1_3_top3_rate'])}|{pct(b['shadow']['rank1_3_top3_rate'])}|{b['delta']['rank1_3_top3_rate']:+.4f}|{b['production']['mean_actual_top3_rank']:.4f}|{b['shadow']['mean_actual_top3_rank']:.4f}|{b['delta']['mean_actual_top3_rank']:+.4f}|",
        f"|Replay|{r['race_count']}|{r['horse_count']}|{r['valid_result_count']}|{r['movement_count']} ({pct(r['movement_rate'])})|{pct(r['production']['rank1_3_top3_rate'])}|{pct(r['shadow']['rank1_3_top3_rate'])}|{r['delta']['rank1_3_top3_rate']:+.4f}|{r['production']['mean_actual_top3_rank']:.4f}|{r['shadow']['mean_actual_top3_rank']:.4f}|{r['delta']['mean_actual_top3_rank']:+.4f}|",
        "", "## Supplemental metrics", "",
        f"- Baseline NDCG@3: {b['production']['ndcg_at_3']:.4f} -> {b['shadow']['ndcg_at_3']:.4f}; MRR: {b['production']['mrr']:.4f} -> {b['shadow']['mrr']:.4f}; Top5 capture: {pct(b['production']['top5_capture_rate'])} -> {pct(b['shadow']['top5_capture_rate'])}",
        f"- Replay NDCG@3: {r['production']['ndcg_at_3']:.4f} -> {r['shadow']['ndcg_at_3']:.4f}; MRR: {r['production']['mrr']:.4f} -> {r['shadow']['mrr']:.4f}; Top5 capture: {pct(r['production']['top5_capture_rate'])} -> {pct(r['shadow']['top5_capture_rate'])}",
        "", "## Decision reasons", "",
        *[f"- {reason}" for reason in summary["decision_reasons"]],
        "", "## Safety", "",
        f"- Feature Flag OFF exact identity: {summary['flag_off_exact_match']}",
        f"- Production row-field mutations: {summary['production_field_mutation_count']}",
        f"- Adjusted-rank reconstruction: {summary['adjusted_rank_validation']['status']} ({summary['adjusted_rank_validation']['adjusted_rank_mismatch_count']} legacy exact-tie rows; Replay 0, non-tie 0)",
        f"- Safety / ZERO_DELTA: {summary['safety_status']} / {summary['zero_delta_status']}",
        "- Adapter / Evaluator / Replay execution: 0 / 0 / 0", "",
        "## Next action", "", summary["next_action"], "",
    ]
    return "\n".join(lines)


def write_json_new(path: Path, value, overwrite=False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv_new(path: Path, rows: list[dict], overwrite=False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    with path.open("w" if overwrite else "x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def run(overwrite_generated=False) -> dict:
    existing = [str(path) for path in OUTPUTS.values() if path.exists()]
    if existing and not overwrite_generated:
        raise FileExistsError(f"refusing to overwrite: {existing}")
    before = protected_snapshot()
    baseline, baseline_sources = load_baseline_rows()
    replay, replay_sources = load_replay_rows()
    if (len(baseline), sum(row["valid_result"] for row in baseline), len(replay)) != (448, 443, 512):
        raise RuntimeError("FORMAL_COHORT_COUNT_MISMATCH")
    validation = validate_rows(baseline + replay)
    if validation["status"] == "FAIL":
        raise RuntimeError("PRODUCTION_ADJUSTED_RANK_RECONSTRUCTION_UNEXPLAINED_MISMATCH")

    production = {"BASELINE": baseline, "REPLAY": replay}
    off_hashes, shadow, mutations = {}, {}, []
    for cohort, rows in production.items():
        off = rank_shadow_rows(rows, enabled=False)
        on = rank_shadow_rows(rows, enabled=True)
        off_hashes[cohort] = {"production_sha256": stable_hash(rows), "flag_off_sha256": stable_hash(off), "exact_match": rows == off}
        base = {(row["race_id"], row["horse_number"]): row for row in rows}
        for row in on:
            original = base[(row["race_id"], row["horse_number"])]
            extra = set(row) - set(original)
            if extra != {"shadow_rank"}:
                mutations.append({"cohort": cohort, "race_id": row["race_id"], "horse_number": row["horse_number"], "field": "UNEXPECTED_SHADOW_FIELDS", "fields": sorted(extra)})
            for field in PROTECTED_ROW_FIELDS:
                if row[field] != original[field]:
                    mutations.append({"cohort": cohort, "race_id": row["race_id"], "horse_number": row["horse_number"], "field": field})
        shadow[cohort] = on

    results = {cohort: cohort_result(rows) for cohort, rows in shadow.items()}
    status, reasons = classify_result(results)
    integrated_rows = shadow["BASELINE"] + shadow["REPLAY"]
    integrated = cohort_result(integrated_rows)
    metrics = metric_rows("BASELINE", shadow["BASELINE"]) + metric_rows("REPLAY", shadow["REPLAY"])
    metrics += metric_rows("INTEGRATED_REFERENCE", integrated_rows, reference_only=True)
    transitions = transition_rows(integrated_rows)
    roi = roi_rows(status)

    after = protected_snapshot()
    protected_changes = [name for name in before if before[name] != after[name]]
    flag_off_pass = all(item["exact_match"] for item in off_hashes.values())
    zero_pass = flag_off_pass and not mutations and not protected_changes
    safety_pass = zero_pass and validation["status"] in {"PASS", "PASS_WITH_LEGACY_TIE_DIFFERENCE"}
    if not safety_pass:
        status = "SAFETY_HOLD"
        reasons.append("SAFETY_OR_ZERO_DELTA_FAIL")
    next_action = {
        "FULL_ACCEPT": "Claude独立レビュー後、final_score切替のProduction昇格条件を別指示で設計する。",
        "PARTIAL_ACCEPT": "SWP_V1診断を3日時間箱で実施し、具体的修正候補が出なければ騎手Shadowへフォールバックする。",
        "INCONCLUSIVE": "追加閾値探索をせず、順位変動不足の原因を確認する。",
        "REJECT": "final_score単純切替を棄却し、誤順位分析の介入点を限定する。",
        "SAFETY_HOLD": "安全差分を修復するまで停止する。",
    }[status]
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "schema_version": "final_score_shadow_summary_v1", "generated_at": generated_at,
        "candidate_id": CANDIDATE_ID, "feature_flag": FLAG_NAME, "feature_flag_default": FLAG_DEFAULT,
        "production_ranking_source": "adjusted_score", "shadow_ranking_source": "final_score",
        "tie_break_rule": "score DESC -> horse_number DESC", "score_values_changed": False,
        "final_status": status, "decision_reasons": reasons, "cohort_results": results,
        "integrated_reference_only": integrated, "cohorts_combined_for_judgment": False,
        "adjusted_rank_validation": validation, "flag_off": off_hashes, "flag_off_exact_match": flag_off_pass,
        "production_field_mutation_count": len(mutations), "production_field_mutations": mutations,
        "source_assets": baseline_sources + replay_sources,
        "ranking_input_fields": ["race_id", "horse_number", "horse_name", "final_score"],
        "outcome_fields_used_for_ranking": [], "outcome_fields_used_for_metrics_only": ["valid_result", "actual_finish", "actual_top3", "actual_top5"],
        "safety_status": "PASS" if safety_pass else "FAIL", "zero_delta_status": "PASS" if zero_pass else "FAIL",
        "target_trial_adapter_run_count": 0, "replay_run_count": 0, "evaluator_run_count": 0,
        "learning_write_count": 0, "knowledge_write_count": 0, "production_write_count": 0,
        "roi_ranking": roi, "next_action": next_action,
    }
    safety = {
        "schema_version": "final_score_shadow_safety_v1", "generated_at": generated_at,
        "status": "PASS" if safety_pass else "FAIL", "protected_changes": protected_changes,
        "protected_before": before, "protected_after": after, "flag_off_exact_match": flag_off_pass,
        "production_field_mutation_count": len(mutations), "adjusted_rank_mismatch_count": validation["adjusted_rank_mismatch_count"],
        "target_trial_adapter_run_count": 0, "replay_run_count": 0, "evaluator_run_count": 0,
        "decision_write_count": 0, "race_decision_write_count": 0, "buy_write_count": 0, "explain_write_count": 0,
        "learning_write_count": 0, "knowledge_write_count": 0, "production_write_count": 0,
    }
    zero = {
        "schema_version": "final_score_shadow_zero_delta_v1", "generated_at": generated_at,
        "status": "PASS" if zero_pass else "FAIL", "protected_changes": protected_changes,
        "flag_off": off_hashes, "production_field_mutations": mutations,
        "score_changed": False, "production_rank_changed": False, "decision_changed": False,
        "race_decision_changed": False, "buy_changed": False, "explain_changed": False,
        "protected_before": before, "protected_after": after,
    }
    test_manifest = {
        "schema_version": "final_score_shadow_test_manifest_v1", "generated_at": generated_at,
        "test_file": "tests/test_final_score_shadow_validation_v1.py", "test_method_count": 24, "subtest_count": 0,
        "commands": [
            "python -m py_compile analysis/final_score_shadow_validation_v1.py tests/test_final_score_shadow_validation_v1.py",
            "python -m unittest tests.test_final_score_shadow_validation_v1 -v",
        ],
        "actual_status": "PENDING_TEST_EXECUTION",
    }
    write_csv_new(OUTPUTS["metrics"], metrics, overwrite_generated)
    write_csv_new(OUTPUTS["transitions"], transitions, overwrite_generated)
    write_json_new(OUTPUTS["summary"], summary, overwrite_generated)
    write_json_new(OUTPUTS["safety"], safety, overwrite_generated)
    write_json_new(OUTPUTS["zero_delta"], zero, overwrite_generated)
    write_json_new(OUTPUTS["test_manifest"], test_manifest, overwrite_generated)
    OUTPUTS["report"].write_text(build_report(summary), encoding="utf-8")
    OUTPUTS["roi"].write_text(build_roi(status, roi), encoding="utf-8")
    OUTPUTS["claude"].write_text(
        "# Claude Review Packet: final_score Shadow Validation v1\n\n"
        f"- Final judgment: **{status}**\n"
        f"- Baseline: `{json.dumps(results['BASELINE'], ensure_ascii=False)}`\n"
        f"- Replay: `{json.dumps(results['REPLAY'], ensure_ascii=False)}`\n"
        f"- Primary judgment reasons: `{';'.join(reasons)}`\n"
        f"- Safety / ZERO_DELTA: `{'PASS' if safety_pass else 'FAIL'} / {'PASS' if zero_pass else 'FAIL'}`\n"
        f"- Next action: `{next_action}`\n\n"
        "Please independently review:\n\n"
        "1. Baseline and Replay are judged separately; integrated values are reference-only.\n"
        "2. Shadow ranking uses saved final_score only and the Production tie-break rule.\n"
        "3. Replay Production adjusted ranks exactly reconstruct; Baseline has four documented legacy exact-tie ordering rows and no non-tie mismatch.\n"
        "4. Co-primary metrics and FULL/PARTIAL/INCONCLUSIVE/REJECT classification match the instruction.\n"
        "5. Whether expected ROI justifies SWP_V1 diagnosis or Production promotion design.\n"
        "6. Whether ranking redesign should proceed or remain conditional.\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": status, "baseline": results["BASELINE"], "replay": results["REPLAY"], "safety": safety["status"]}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    run(overwrite_generated="--replace-generated" in sys.argv)
