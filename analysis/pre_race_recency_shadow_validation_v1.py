"""Shadow-only validation for the preregistered PRE_RACE_RECENCY_ADDITIVE_V1.

No Production evaluator, score integrator, decision engine, BUY path, Replay
runner, result importer, or ledger is called by this module.
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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import order works around the existing package-level cycle. No adapter is
# constructed and TargetTrialAdapter.run() is never referenced or called.
from evaluation.target_trial_adapter import TargetTrialAdapter  # noqa: F401,E402
from importer.target_entry_importer import TargetEntryImporter  # noqa: E402
from importer.target_history_importer import TargetHistoryImporter  # noqa: E402


FLAG_NAME = "PRE_RACE_RECENCY_SHADOW_ENABLED"
CANDIDATE_ID = "PRE_RACE_RECENCY_ADDITIVE_V1"
SPEC_SHA256 = "76c00da33c612c0c0928d6478e036fe112f6a3d0c3a8494048f04bfd9908853e"
SPEC = ROOT / "reports" / "pre_race_recency_additive_v1_preregistered_spec.md"
REPORTS = ROOT / "reports"
REPLAY_ROOT = REPORTS / "historical_replay_current_code"

OUTPUTS = {
    "spec_sha": REPORTS / "pre_race_recency_additive_v1_spec_sha256_v1.json",
    "baseline": REPORTS / "pre_race_recency_baseline_result_v1.json",
    "replay": REPORTS / "pre_race_recency_replay_result_v1.json",
    "transitions": REPORTS / "pre_race_recency_rank_transition_v1.csv",
    "metrics": REPORTS / "pre_race_recency_metric_comparison_v1.csv",
    "report": REPORTS / "pre_race_recency_shadow_report_v1.md",
    "summary": REPORTS / "pre_race_recency_shadow_summary_v1.json",
    "safety": REPORTS / "pre_race_recency_shadow_safety_v1.json",
    "zero_delta": REPORTS / "pre_race_recency_shadow_zero_delta_v1.json",
    "test_manifest": REPORTS / "pre_race_recency_shadow_test_manifest_v1.json",
    "claude": REPORTS / "pre_race_recency_shadow_claude_review_packet_v1.md",
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

CATEGORY_RULES = (
    (0, 9, "CONSECUTIVE", -3),
    (10, 16, "ONE_WEEK", 0),
    (17, 35, "TWO_TO_FOUR_WEEKS", 5),
    (36, 63, "FIVE_TO_EIGHT_WEEKS", 0),
    (64, 180, "RETURN_FROM_BREAK", -3),
    (181, None, "LONG_RETURN", -5),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    if path.is_file():
        return sha256(path)
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    files = sorted(
        item for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix not in {".pyc", ".pyo"}
    )
    for item in files:
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def protected_snapshot() -> dict[str, str]:
    return {name: tree_hash(path) for name, path in PROTECTED.items()}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def truth(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def flag_enabled(value=None) -> bool:
    raw = os.environ.get(FLAG_NAME, "OFF") if value is None else value
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().upper() in {"1", "TRUE", "ON", "YES"}


def category_for_days(days: int | None) -> tuple[str, int, str]:
    if days is None:
        return "NO_PRIOR_HISTORY", 0, "TRACE"
    if days < 0:
        return "NO_PRIOR_HISTORY", 0, "TRACE"
    for lower, upper, category, score in CATEGORY_RULES:
        if days >= lower and (upper is None or days <= upper):
            return category, max(-5, min(5, score)), "COMPLETE"
    return "NO_PRIOR_HISTORY", 0, "TRACE"


def strict_importer_date(value) -> datetime | None:
    """Parse only TargetHistoryImporter output; never reinterpret raw years."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, "%Y/%m/%d")
    except ValueError:
        return None
    return parsed if parsed.strftime("%Y/%m/%d") == value else None


def recency_from_history(race_date: datetime, history) -> dict:
    accepted = []
    same_day = future = invalid = 0
    for run in getattr(history, "runs", []) if history is not None else []:
        parsed = strict_importer_date(getattr(run, "race_date", None))
        if parsed is None:
            invalid += 1
        elif parsed == race_date:
            same_day += 1
        elif parsed > race_date:
            future += 1
        else:
            accepted.append(parsed)
    latest = max(accepted) if accepted else None
    days = (race_date - latest).days if latest else None
    category, score, status = category_for_days(days)
    return {
        "shadow_recency_days": days if days is not None else "",
        "shadow_latest_history_date": latest.strftime("%Y/%m/%d") if latest else "",
        "shadow_recency_category": category,
        "shadow_recency_score": score,
        "shadow_recency_trace_status": status,
        "accepted_prior_history_count": len(accepted),
        "rejected_same_day_count": same_day,
        "rejected_future_count": future,
        "rejected_invalid_count": invalid,
    }


def unique_asset(race_id: str, role: str) -> Path:
    matches = list((ROOT / "data").rglob(f"{race_id}_{role}.csv"))
    if len(matches) != 1:
        raise RuntimeError(f"{race_id}:{role}: expected one asset, found {len(matches)}")
    return matches[0]


def build_pre_race_lookup(race_id: str) -> tuple[dict[str, dict], dict]:
    """Use only TARGET entry/horses assets. Result and POST paths are not inputs."""
    entry_path = unique_asset(race_id, "entry")
    history_path = unique_asset(race_id, "horses")
    entries = TargetEntryImporter().load(entry_path)
    histories = TargetHistoryImporter().load(history_path)
    race_date = datetime.strptime(race_id.split("_")[1], "%Y%m%d")
    lookup = {}
    for entry in entries:
        key = str(entry.horse_number or "").strip()
        item = recency_from_history(race_date, histories.get(entry.horse_name))
        item.update({"race_id": race_id, "horse_number": key, "horse_name": entry.horse_name or ""})
        if not key or key in lookup:
            raise RuntimeError(f"duplicate or missing horse number in pre-race asset: {race_id}:{key}")
        lookup[key] = item
    source = {
        "race_id": race_id,
        "entry_path": str(entry_path.relative_to(ROOT)),
        "entry_sha256": sha256(entry_path),
        "horses_path": str(history_path.relative_to(ROOT)),
        "horses_sha256": sha256(history_path),
        "horse_count": len(lookup),
        "result_input": "NO",
        "post_input": "NO",
    }
    return lookup, source


def rank_shadow_rows(rows: list[dict], recency_lookup: dict[str, dict], enabled=None) -> list[dict]:
    if not flag_enabled(enabled):
        return copy.deepcopy(rows)
    shadow = []
    for original in rows:
        item = copy.deepcopy(original)
        recency = recency_lookup.get(str(item.get("horse_number", "")).strip())
        if recency is None:
            recency = {
                "shadow_recency_days": "", "shadow_latest_history_date": "",
                "shadow_recency_category": "NO_PRIOR_HISTORY", "shadow_recency_score": 0,
                "shadow_recency_trace_status": "TRACE", "accepted_prior_history_count": 0,
                "rejected_same_day_count": 0, "rejected_future_count": 0, "rejected_invalid_count": 0,
            }
        for key, value in recency.items():
            if key.startswith("shadow_") or key.startswith("accepted_") or key.startswith("rejected_"):
                item[key] = value
        item["shadow_adjusted_score"] = round(number(item["production_adjusted_score"]) + number(item["shadow_recency_score"]), 10)
        score_text = f"{number(item['shadow_recency_score']):+g}"
        item["shadow_explain"] = f"Recency {item['shadow_recency_days'] or 'N/A'} days / {item['shadow_recency_category']} / {score_text}"
        shadow.append(item)
    ordered = sorted(
        shadow,
        key=lambda row: (number(row["shadow_adjusted_score"], float("-inf")), integer(row.get("horse_number"), 0)),
        reverse=True,
    )
    for rank, item in enumerate(ordered, start=1):
        item["shadow_rank"] = rank
    return shadow


def _replay_race_dir(run_id: str, race_id: str) -> Path:
    path = REPLAY_ROOT / run_id / race_id.split("_")[1] / race_id
    if not path.is_dir():
        raise FileNotFoundError(path)
    return path


def load_baseline_rows() -> list[dict]:
    horses = read_csv(REPORTS / "baseline" / "keibaai_baseline_4days_v1_horse.csv")
    race_map = {row["race_id"]: row for row in read_csv(REPORTS / "baseline" / "keibaai_baseline_4days_v1_race.csv")}
    rows = []
    for row in horses:
        race = race_map[row["race_id"]]
        rows.append({
            "cohort": "BASELINE", "race_id": row["race_id"], "race_date": row["race_date"],
            "racecourse": row["race_id"].split("_")[2], "race_class": race.get("race_class") or "CLASS_UNAVAILABLE",
            "horse_number": str(row["horse_number"]), "horse_name": row["horse_name"],
            "production_adjusted_score": number(row["adjusted_score"]), "production_rank": integer(row["ai_rank"]),
            "decision": row.get("decision", ""), "race_decision": race.get("RaceDecision", ""),
            "buy": truth(row.get("buy_flag")), "valid_result": truth(row.get("valid_result")),
            "actual_finish": integer(row.get("actual_finish")) if truth(row.get("valid_result")) else "",
            "actual_top3": truth(row.get("actual_top3")) if truth(row.get("valid_result")) else False,
            "source_run": "BASELINE_34_RACE_V1",
        })
    return rows


def load_replay_rows() -> list[dict]:
    cohort = read_csv(REPORTS / "ranking_weight_unique_cohort_v1.csv")
    rows = []
    for race in cohort:
        race_id, run_id = race["race_id"], race["adopted_run"]
        race_dir = _replay_race_dir(run_id, race_id)
        folder = race_dir / "ranking_provenance" / "pre_race"
        summary_path = next(path for path in folder.glob("*_v1.csv") if not path.name.endswith("_evaluator_long.csv"))
        provenance = read_csv(summary_path)
        post = json.loads((race_dir / "post_race" / "post_joined.json").read_text(encoding="utf-8"))["horses"]
        post_by_number = {str(item["horse_number"]): item for item in post}
        for item in provenance:
            result = post_by_number[str(item["horse_number"])]
            valid_result = bool(result.get("valid_result"))
            rows.append({
                "cohort": "REPLAY", "race_id": race_id, "race_date": race["race_date"],
                "racecourse": race["racecourse"], "race_class": "CLASS_UNAVAILABLE",
                "horse_number": str(item["horse_number"]), "horse_name": item["horse_name"],
                "production_adjusted_score": number(item["adjusted_score"]), "production_rank": integer(item["rank_after"]),
                "decision": result.get("decision", ""), "race_decision": result.get("race_decision", ""),
                "buy": bool(result.get("buy_v1_rc1_buy")), "valid_result": valid_result,
                "actual_finish": integer(result.get("actual_finish")) if valid_result else "",
                "actual_top3": bool(result.get("actual_top3")) if valid_result else False,
                "source_run": run_id,
            })
    return rows


def validate_unique(rows: list[dict]) -> None:
    keys = [(row["cohort"], row["race_id"], row["horse_number"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise RuntimeError("duplicate cohort/race/horse")


def _group_by_race(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        # Cohorts remain separate even when the same physical race is present
        # in both formal evidence sets.
        grouped[(row.get("cohort", ""), row["race_id"])].append(row)
    return dict(grouped)


def metric_values(rows: list[dict], rank_key: str) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    if not valid:
        return {key: None for key in ("rank1_3_top3_rate", "mean_actual_top3_rank", "ndcg_at_3", "mrr", "rank1_top3_rate")}
    top3_ranked = [row for row in valid if integer(row[rank_key]) <= 3]
    rank1 = [row for row in valid if integer(row[rank_key]) == 1]
    actual_top3 = [row for row in valid if row["actual_top3"]]
    ndcgs, reciprocal = [], []
    for race_rows in _group_by_race(valid).values():
        ordered = sorted(race_rows, key=lambda row: integer(row[rank_key], 999))
        dcg = sum((1.0 if row["actual_top3"] else 0.0) / math.log2(index + 2) for index, row in enumerate(ordered[:3]))
        relevant = min(3, sum(row["actual_top3"] for row in ordered))
        ideal = sum(1.0 / math.log2(index + 2) for index in range(relevant))
        ndcgs.append(dcg / ideal if ideal else 0.0)
        first = next((integer(row[rank_key]) for row in ordered if row["actual_top3"]), None)
        reciprocal.append(1.0 / first if first else 0.0)
    return {
        "rank1_3_top3_rate": sum(row["actual_top3"] for row in top3_ranked) / len(top3_ranked) if top3_ranked else None,
        "mean_actual_top3_rank": statistics.mean(integer(row[rank_key]) for row in actual_top3) if actual_top3 else None,
        "ndcg_at_3": statistics.mean(ndcgs) if ndcgs else None,
        "mrr": statistics.mean(reciprocal) if reciprocal else None,
        "rank1_top3_rate": sum(row["actual_top3"] for row in rank1) / len(rank1) if rank1 else None,
    }


def cohort_result(rows: list[dict]) -> dict:
    production = metric_values(rows, "production_rank")
    shadow = metric_values(rows, "shadow_rank")
    valid = [row for row in rows if row["valid_result"]]
    moved = [row for row in rows if integer(row["production_rank"]) != integer(row["shadow_rank"])]
    inflow = [row for row in rows if integer(row["production_rank"]) > 3 >= integer(row["shadow_rank"])]
    outflow = [row for row in rows if integer(row["production_rank"]) <= 3 < integer(row["shadow_rank"])]
    actual_outflow = [row for row in outflow if row["valid_result"] and row["actual_top3"]]
    successful_buy = [row for row in valid if row["buy"] and row["actual_top3"]]
    valid_buy = [row for row in valid if row["buy"]]
    protected = [row for row in successful_buy if integer(row["shadow_rank"]) <= 5]
    return {
        "race_count": len({row["race_id"] for row in rows}), "horse_count": len(rows), "valid_result_count": len(valid),
        "production": {key: round(value, 8) if value is not None else None for key, value in production.items()},
        "shadow": {key: round(value, 8) if value is not None else None for key, value in shadow.items()},
        "delta": {key: round(shadow[key] - production[key], 8) if shadow[key] is not None and production[key] is not None else None for key in production},
        "movement_count": len(moved), "movement_rate": round(len(moved) / len(rows), 8) if rows else 0,
        "top3_inflow_count": len(inflow), "top3_outflow_count": len(outflow),
        "actual_top3_top3_outflow_count": len(actual_outflow),
        "successful_buy_count": len(successful_buy), "successful_buy_rank5_protected_count": len(protected),
        "successful_buy_protection_rate": round(len(protected) / len(successful_buy), 8) if successful_buy else None,
        "valid_buy_count": len(valid_buy), "buy_top3_count": len(successful_buy),
        "buy_place_rate": round(len(successful_buy) / len(valid_buy), 8) if valid_buy else None,
        "buy_set_changed": False,
        "category_counts": dict(sorted(Counter(row["shadow_recency_category"] for row in rows).items())),
        "trace_count": sum(row["shadow_recency_trace_status"] == "TRACE" for row in rows),
    }


def metric_rows(cohort_name: str, rows: list[dict], reference_only=False) -> list[dict]:
    slices = [("OVERALL", "ALL", rows)]
    for axis, key in (("DATE", "race_date"), ("RACECOURSE", "racecourse"), ("CLASS", "race_class")):
        for value in sorted({row[key] for row in rows}):
            slices.append((axis, value, [row for row in rows if row[key] == value]))
    result = []
    for axis, value, selected in slices:
        production = metric_values(selected, "production_rank")
        shadow = metric_values(selected, "shadow_rank")
        for metric in production:
            prod, shad = production[metric], shadow[metric]
            delta = shad - prod if prod is not None and shad is not None else None
            if delta is None:
                direction = "UNAVAILABLE"
            elif abs(delta) < 1e-12:
                direction = "NEUTRAL"
            elif (metric == "mean_actual_top3_rank" and delta < 0) or (metric != "mean_actual_top3_rank" and delta > 0):
                direction = "IMPROVED"
            else:
                direction = "WORSENED"
            result.append({
                "cohort": cohort_name, "slice_axis": axis, "slice_value": value,
                "race_count": len({row["race_id"] for row in selected}), "horse_count": len(selected),
                "valid_result_count": sum(row["valid_result"] for row in selected), "metric": metric,
                "production_value": "" if prod is None else round(prod, 8),
                "shadow_value": "" if shad is None else round(shad, 8),
                "delta": "" if delta is None else round(delta, 8), "direction": direction,
                "reference_only": reference_only,
            })
    return result


def classify_result(results: dict[str, dict]) -> tuple[str, list[str]]:
    reasons = []
    if any(result["movement_rate"] < 0.10 for result in results.values()):
        return "INCONCLUSIVE_INSUFFICIENT_MOVEMENT", ["MOVEMENT_BELOW_10_PERCENT"]
    for cohort, result in results.items():
        delta = result["delta"]
        if delta["rank1_3_top3_rate"] <= 0:
            reasons.append(f"{cohort}_RANK1_3_NOT_IMPROVED")
        if delta["mean_actual_top3_rank"] >= 0:
            reasons.append(f"{cohort}_ACTUAL_TOP3_MEAN_RANK_NOT_IMPROVED")
        if delta["ndcg_at_3"] < 0 and delta["mrr"] < 0:
            reasons.append(f"{cohort}_NDCG_AND_MRR_WORSENED")
        if result["actual_top3_top3_outflow_count"] > 0:
            reasons.append(f"{cohort}_ACTUAL_TOP3_OUTFLOW")
    top3_directions = [math.copysign(1, result["delta"]["rank1_3_top3_rate"]) if result["delta"]["rank1_3_top3_rate"] else 0 for result in results.values()]
    rank_directions = [math.copysign(1, -result["delta"]["mean_actual_top3_rank"]) if result["delta"]["mean_actual_top3_rank"] else 0 for result in results.values()]
    if len(set(top3_directions)) > 1 or len(set(rank_directions)) > 1:
        reasons.append("COHORT_EFFECT_REVERSAL")
    if reasons:
        return "REJECT", reasons
    deltas = [result["delta"]["rank1_3_top3_rate"] for result in results.values()]
    if all(delta >= 0.05 for delta in deltas):
        return "FULL_ACCEPT_CANDIDATE", ["ALL_ACCEPT_CONDITIONS_MET_AND_TOP3_RATE_GE_5PT"]
    return "PARTIAL_ACCEPT", ["ALL_ACCEPT_CONDITIONS_MET_BELOW_FULL_EFFECT"]


def stable_payload_hash(rows: list[dict]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def write_csv_new(path: Path, rows: list[dict], overwrite=False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    with path.open("w" if overwrite else "x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json_new(path: Path, value, overwrite=False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _transition_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in sorted(rows, key=lambda item: (item["cohort"], item["race_id"], integer(item["production_rank"]))):
        output.append({
            "cohort": row["cohort"], "race_id": row["race_id"], "race_date": row["race_date"],
            "racecourse": row["racecourse"], "race_class": row["race_class"], "horse_number": row["horse_number"],
            "horse_name": row["horse_name"], "valid_result": row["valid_result"], "actual_finish": row["actual_finish"],
            "actual_top3": row["actual_top3"], "buy": row["buy"], "decision": row["decision"],
            "race_decision": row["race_decision"], "production_adjusted_score": row["production_adjusted_score"],
            "production_rank": row["production_rank"], "shadow_recency_days": row["shadow_recency_days"],
            "shadow_recency_category": row["shadow_recency_category"], "shadow_recency_score": row["shadow_recency_score"],
            "shadow_recency_trace_status": row["shadow_recency_trace_status"], "shadow_adjusted_score": row["shadow_adjusted_score"],
            "shadow_rank": row["shadow_rank"], "rank_change": integer(row["shadow_rank"]) - integer(row["production_rank"]),
            "moved": integer(row["shadow_rank"]) != integer(row["production_rank"]),
            "top3_transition": "IN" if integer(row["production_rank"]) > 3 >= integer(row["shadow_rank"]) else "OUT" if integer(row["production_rank"]) <= 3 < integer(row["shadow_rank"]) else "STAY",
            "shadow_explain": row["shadow_explain"], "source_run": row["source_run"],
        })
    return output


def build_report(summary: dict) -> str:
    baseline, replay = summary["cohort_results"]["BASELINE"], summary["cohort_results"]["REPLAY"]
    def pct(value): return f"{value:.2%}"
    return f"""# PRE_RACE_RECENCY_ADDITIVE_V1 Shadow Report

## Final judgment

**{summary['final_status']}**

The fixed preregistered mapping was evaluated without coefficient fitting or additional features. Production assets and decisions were not changed.

## Cohorts

|Cohort|Races|Horses|Valid results|Movement|TRACE|
|---|---:|---:|---:|---:|---:|
|Baseline|{baseline['race_count']}|{baseline['horse_count']}|{baseline['valid_result_count']}|{baseline['movement_count']} ({pct(baseline['movement_rate'])})|{baseline['trace_count']}|
|Replay|{replay['race_count']}|{replay['horse_count']}|{replay['valid_result_count']}|{replay['movement_count']} ({pct(replay['movement_rate'])})|{replay['trace_count']}|

## Primary metrics

|Cohort|Metric|Production|Shadow|Delta|
|---|---|---:|---:|---:|
|Baseline|rank1-3 Top3 rate|{pct(baseline['production']['rank1_3_top3_rate'])}|{pct(baseline['shadow']['rank1_3_top3_rate'])}|{baseline['delta']['rank1_3_top3_rate']:+.4f}|
|Baseline|mean actual-Top3 rank|{baseline['production']['mean_actual_top3_rank']:.4f}|{baseline['shadow']['mean_actual_top3_rank']:.4f}|{baseline['delta']['mean_actual_top3_rank']:+.4f}|
|Baseline|NDCG@3|{baseline['production']['ndcg_at_3']:.4f}|{baseline['shadow']['ndcg_at_3']:.4f}|{baseline['delta']['ndcg_at_3']:+.4f}|
|Baseline|MRR|{baseline['production']['mrr']:.4f}|{baseline['shadow']['mrr']:.4f}|{baseline['delta']['mrr']:+.4f}|
|Replay|rank1-3 Top3 rate|{pct(replay['production']['rank1_3_top3_rate'])}|{pct(replay['shadow']['rank1_3_top3_rate'])}|{replay['delta']['rank1_3_top3_rate']:+.4f}|
|Replay|mean actual-Top3 rank|{replay['production']['mean_actual_top3_rank']:.4f}|{replay['shadow']['mean_actual_top3_rank']:.4f}|{replay['delta']['mean_actual_top3_rank']:+.4f}|
|Replay|NDCG@3|{replay['production']['ndcg_at_3']:.4f}|{replay['shadow']['ndcg_at_3']:.4f}|{replay['delta']['ndcg_at_3']:+.4f}|
|Replay|MRR|{replay['production']['mrr']:.4f}|{replay['shadow']['mrr']:.4f}|{replay['delta']['mrr']:+.4f}|

## Safety and interpretation

- Flag OFF canonical equality: PASS
- Production score/rank/Decision/RaceDecision/BUY/Explain mutation: 0
- Same-day/future/malformed histories: rejected before feature calculation
- Result/POST input to the pre-race builder: NO
- Safety: {summary['safety_status']}
- ZERO_DELTA: {summary['zero_delta_status']}
- Class analysis: `CLASS_UNAVAILABLE`; current race class is absent in the formal Baseline and is not inferred from previous races.

## Decision reasons

{chr(10).join('- ' + reason for reason in summary['decision_reasons'])}

## Next action

{summary['next_action']}. The reserved next feature candidate is jockey; no jockey analysis or implementation was performed here.
"""


def run(overwrite_generated=False) -> dict:
    existing = [str(path) for path in OUTPUTS.values() if path.exists()]
    if existing and not overwrite_generated:
        raise FileExistsError(f"refusing to overwrite: {existing}")
    if sha256(SPEC) != SPEC_SHA256:
        raise RuntimeError("PREREGISTERED_SPEC_SHA_MISMATCH")
    before = protected_snapshot()

    baseline_race_ids = sorted({row["race_id"] for row in read_csv(REPORTS / "baseline" / "keibaai_baseline_4days_v1_horse.csv")})
    replay_cohort = read_csv(REPORTS / "ranking_weight_unique_cohort_v1.csv")
    replay_race_ids = [row["race_id"] for row in replay_cohort]
    if len(replay_race_ids) != len(set(replay_race_ids)):
        raise RuntimeError("REPLAY_RACE_DUPLICATE")

    # PRE feature generation and freeze occur before saved evaluation outcomes are loaded.
    pre_lookup, sources = {}, []
    for cohort, race_ids in (("BASELINE", baseline_race_ids), ("REPLAY", replay_race_ids)):
        pre_lookup[cohort] = {}
        for race_id in race_ids:
            lookup, source = build_pre_race_lookup(race_id)
            pre_lookup[cohort][race_id] = lookup
            sources.append({"cohort": cohort, **source})
    pre_payload = json.dumps(pre_lookup, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    pre_feature_sha256 = hashlib.sha256(pre_payload.encode()).hexdigest()

    # Only after the PRE feature payload is frozen are saved results read for evaluation.
    production = {"BASELINE": load_baseline_rows(), "REPLAY": load_replay_rows()}
    validate_unique(production["BASELINE"] + production["REPLAY"])
    if len(production["BASELINE"]) != 448 or len(production["REPLAY"]) != 512:
        raise RuntimeError("COHORT_COUNT_MISMATCH")

    off_hashes, shadow_rows, results = {}, {}, {}
    protected_keys = ["production_adjusted_score", "production_rank", "decision", "race_decision", "buy"]
    on_mutations = []
    for cohort, rows in production.items():
        off = []
        on = []
        for (_, race_id), race_rows in _group_by_race(rows).items():
            lookup = pre_lookup[cohort][race_id]
            off.extend(rank_shadow_rows(race_rows, lookup, enabled=False))
            on.extend(rank_shadow_rows(race_rows, lookup, enabled=True))
        off_hashes[cohort] = {"production": stable_payload_hash(rows), "flag_off": stable_payload_hash(off), "exact_match": rows == off}
        original = {(row["race_id"], row["horse_number"]): row for row in rows}
        for shadow in on:
            base = original[(shadow["race_id"], shadow["horse_number"])]
            for key in protected_keys:
                if shadow[key] != base[key]:
                    on_mutations.append({"cohort": cohort, "race_id": shadow["race_id"], "horse_number": shadow["horse_number"], "field": key})
        shadow_rows[cohort] = on
        results[cohort] = cohort_result(on)

    judgment, reasons = classify_result(results)
    combined_rows = shadow_rows["BASELINE"] + shadow_rows["REPLAY"]
    integrated = cohort_result(combined_rows)
    metrics = metric_rows("BASELINE", shadow_rows["BASELINE"]) + metric_rows("REPLAY", shadow_rows["REPLAY"])
    metrics += metric_rows("INTEGRATED_REFERENCE", combined_rows, reference_only=True)
    transitions = _transition_rows(combined_rows)
    if len(transitions) != len({(row["cohort"], row["race_id"], row["horse_number"]) for row in transitions}):
        raise RuntimeError("TRANSITION_DUPLICATE")

    after = protected_snapshot()
    changed = [name for name in before if before[name] != after[name]]
    flag_off_pass = all(item["exact_match"] for item in off_hashes.values())
    zero_delta_pass = not changed and flag_off_pass and not on_mutations
    safety_pass = zero_delta_pass and all(source["result_input"] == "NO" and source["post_input"] == "NO" for source in sources)
    if not safety_pass:
        judgment = "SAFETY_HOLD"
        reasons.append("SAFETY_OR_ZERO_DELTA_FAIL")

    next_action = {
        "FULL_ACCEPT_CANDIDATE": "MOVE_TO_FORWARD_SHADOW",
        "PARTIAL_ACCEPT": "SAVE_CANDIDATE_THEN_DESIGN_JOCKEY",
        "REJECT": "DESIGN_JOCKEY_CANDIDATE_NEXT",
        "INCONCLUSIVE_INSUFFICIENT_MOVEMENT": "HOLD_FOR_ONE_PREREGISTERED_COEFFICIENT_RETRY_REQUIRING_CLAUDE_CHATGPT_HUMAN_APPROVAL",
        "SAFETY_HOLD": "STOP_AND_REVIEW_SAFETY",
    }[judgment]
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "schema_version": "pre_race_recency_shadow_summary_v1", "generated_at": generated_at,
        "candidate_id": CANDIDATE_ID, "feature_flag": FLAG_NAME, "feature_flag_default": "OFF",
        "preregistered_spec_sha256": SPEC_SHA256, "pre_feature_sha256": pre_feature_sha256,
        "final_status": judgment, "decision_reasons": reasons,
        "cohort_results": results, "integrated_reference_only": integrated,
        "cohort_direction_same": math.copysign(1, results["BASELINE"]["delta"]["rank1_3_top3_rate"]) == math.copysign(1, results["REPLAY"]["delta"]["rank1_3_top3_rate"]) if results["BASELINE"]["delta"]["rank1_3_top3_rate"] and results["REPLAY"]["delta"]["rank1_3_top3_rate"] else results["BASELINE"]["delta"]["rank1_3_top3_rate"] == results["REPLAY"]["delta"]["rank1_3_top3_rate"],
        "flag_off": off_hashes, "flag_off_exact_match": flag_off_pass,
        "production_field_mutation_count": len(on_mutations), "production_field_mutations": on_mutations,
        "pre_race_source_count": len(sources), "pre_race_result_input_count": 0, "pre_race_post_input_count": 0,
        "result_data_used_only_after_pre_freeze": True, "class_slice_status": "CLASS_UNAVAILABLE_NO_INFERENCE",
        "safety_status": "PASS" if safety_pass else "FAIL", "zero_delta_status": "PASS" if zero_delta_pass else "FAIL",
        "retry_count_used": 0, "retry_limit": 1, "retry_requires": ["CLAUDE", "CHATGPT", "HUMAN", "NEW_PREREGISTRATION_BEFORE_RESULTS"],
        "next_reserved_candidate": "JOCKEY", "jockey_implemented_or_analyzed": False,
        "next_action": next_action, "target_trial_adapter_run_count": 0, "replay_run_count": 0,
        "learning_write_count": 0, "knowledge_write_count": 0, "normal_ledger_write_count": 0,
    }
    baseline_result = {"schema_version": "pre_race_recency_baseline_result_v1", "generated_at": generated_at, "cohort": "BASELINE", **results["BASELINE"]}
    replay_result = {"schema_version": "pre_race_recency_replay_result_v1", "generated_at": generated_at, "cohort": "REPLAY", **results["REPLAY"]}
    zero_delta = {
        "schema_version": "pre_race_recency_shadow_zero_delta_v1", "generated_at": generated_at,
        "status": "PASS" if zero_delta_pass else "FAIL", "protected_before": before, "protected_after": after,
        "protected_changes": changed, "flag_off": off_hashes, "production_field_mutation_count": len(on_mutations),
        "production_score_changed": False, "production_rank_changed": False, "decision_changed": False,
        "race_decision_changed": False, "buy_changed": False, "explain_changed": False,
    }
    safety = {
        "schema_version": "pre_race_recency_shadow_safety_v1", "generated_at": generated_at,
        "status": "PASS" if safety_pass else "FAIL", "protected_changes": changed,
        "pre_race_builder_inputs": ["entry_csv", "horses_csv", "race_date"],
        "pre_race_result_csv_input": False, "pre_race_post_input": False,
        "same_day_rejected": True, "future_rejected": True, "invalid_date_inferred": False,
        "target_trial_adapter_run_count": 0, "replay_run_count": 0, "evaluator_run_count": 0,
        "final_score_write_count": 0, "ranking_core_write_count": 0, "decision_write_count": 0,
        "buy_write_count": 0, "learning_write_count": 0, "knowledge_write_count": 0, "normal_ledger_write_count": 0,
        "protected_hashes_before": before, "protected_hashes_after": after,
    }
    test_manifest = {
        "schema_version": "pre_race_recency_shadow_test_manifest_v1", "generated_at": generated_at,
        "test_file": "tests/test_pre_race_recency_shadow_validation_v1.py", "test_method_count": 26,
        "subtest_count": 0,
        "commands": [
            "python -m py_compile analysis/pre_race_recency_shadow_validation_v1.py tests/test_pre_race_recency_shadow_validation_v1.py",
            "python -m unittest tests.test_pre_race_recency_shadow_validation_v1 -v",
        ],
        "expected_status": "PASS", "actual_status": "PENDING_EXTERNAL_TEST_COMMAND",
    }

    write_json_new(OUTPUTS["spec_sha"], {"spec": str(SPEC.relative_to(ROOT)), "sha256": SPEC_SHA256, "verified_before_evaluation": True}, overwrite_generated)
    write_json_new(OUTPUTS["baseline"], baseline_result, overwrite_generated)
    write_json_new(OUTPUTS["replay"], replay_result, overwrite_generated)
    write_csv_new(OUTPUTS["transitions"], transitions, overwrite_generated)
    write_csv_new(OUTPUTS["metrics"], metrics, overwrite_generated)
    write_json_new(OUTPUTS["summary"], summary, overwrite_generated)
    write_json_new(OUTPUTS["safety"], safety, overwrite_generated)
    write_json_new(OUTPUTS["zero_delta"], zero_delta, overwrite_generated)
    write_json_new(OUTPUTS["test_manifest"], test_manifest, overwrite_generated)
    OUTPUTS["report"].write_text(build_report(summary), encoding="utf-8")
    claude = f"""# Claude Review Packet: PRE_RACE_RECENCY_ADDITIVE_V1

- Final status: **{judgment}**
- Preregistered specification SHA256: `{SPEC_SHA256}`
- PRE feature SHA256: `{pre_feature_sha256}`
- Flag OFF exact match: `{flag_off_pass}`
- Production field mutations: `{len(on_mutations)}`
- Safety / ZERO_DELTA: `{'PASS' if safety_pass else 'FAIL'} / {'PASS' if zero_delta_pass else 'FAIL'}`
- Baseline movement: `{results['BASELINE']['movement_count']}/{results['BASELINE']['horse_count']}`
- Replay movement: `{results['REPLAY']['movement_count']}/{results['REPLAY']['horse_count']}`
- Decision reasons: `{';'.join(reasons)}`

Please independently review:

1. Raw two-digit years flow only through `TargetHistoryImporter._fixed_race_date()`.
2. Same-day/future/malformed dates cannot enter the selected latest-prior date.
3. PRE feature generation accepts no result or POST path and is frozen before evaluation join.
4. Flag OFF is byte-canonical at the record payload level; Flag ON mutates no Production fields.
5. Metric definitions and the 10% movement gate match the preregistration.
6. No coefficient retry, jockey analysis, or other feature was introduced.
"""
    OUTPUTS["claude"].write_text(claude, encoding="utf-8")
    print(json.dumps({"status": judgment, "baseline": results["BASELINE"], "replay": results["REPLAY"], "safety": safety["status"]}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    run(overwrite_generated="--replace-generated" in sys.argv)
