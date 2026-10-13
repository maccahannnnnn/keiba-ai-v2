"""Approved Iter0 baseline evaluation from the frozen deterministic PRE rows.

This is a one-shot, development-only runner.  It loads result labels only
after authenticating the already-frozen C/D PRE-only regeneration evidence.
It never reruns prediction, tunes a threshold, or changes Production.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.candidate_generation_training_dataset_readiness_v1 import (
    FEATURES, JAPANESE_VENUE, Stop, outcome, parse_race_id, result_rows,
)


PRE_ROOT = ROOT / "reports" / "full_field_redesign_iter0_v1_retry6" / "pre_only_regeneration" / "shards"
DETERMINISM = ROOT / "reports" / "decision_engine_determinism_fix_v1" / "run_c_d_determinism_comparison.json"
OUT = ROOT / "reports" / "full_field_redesign_iter0_v1_retry8"
MONTHS = ("202602", "202603", "202604", "202605", "202606", "202607", "202608", "202609")
GATES = {"absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass"}


class Iter0Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def csv_write(name: str, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_pre_rows() -> list[dict[str, Any]]:
    rows: dict[tuple[str, str, int], dict[str, Any]] = {}
    expected_shards = 31
    files = sorted(PRE_ROOT.glob("run_c_*/runtime_pre_only_output.json"))
    if len(files) != expected_shards:
        raise Iter0Stop(f"STOP_PRE_FREEZE_SHARD_COUNT:{len(files)}")
    for path in files:
        for row in json.loads(path.read_text(encoding="utf-8"))["generated_rows"]:
            key = (str(row["date"]), str(row["race_id"]), int(row["horse_number"]))
            if key in rows:
                raise Iter0Stop(f"STOP_PRE_IDENTITY_DUPLICATE:{key}")
            rows[key] = row
    ordered = [rows[key] for key in sorted(rows)]
    if len(ordered) != 14870:
        raise Iter0Stop(f"STOP_PRE_POPULATION_COUNT:{len(ordered)}")
    return ordered


def number(value: Any, name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise Iter0Stop(f"STOP_FEATURE_VALUE_INVALID:{name}:{value!r}")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise Iter0Stop(f"STOP_FEATURE_VALUE_INVALID:{name}:{value!r}") from error
    if not math.isfinite(result):
        raise Iter0Stop(f"STOP_FEATURE_VALUE_NONFINITE:{name}")
    return result


def vector(row: dict[str, Any]) -> list[float]:
    values = row["values"]
    vector_values: list[float] = []
    for feature in FEATURES[:-1]:
        value = values.get(feature)
        vector_values.append(float(bool(value)) if feature in GATES else number(value, feature))
    state = str(values.get("race_state"))
    vector_values.extend([float(state == "PLAY_UNCONVERGED_4PLUS"), float(state == "SKIP")])
    if len(vector_values) != 21:
        raise Iter0Stop("STOP_V5_TRANSFORM_DIMENSION")
    return vector_values


def result_join(pre_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pre_rows:
        by_date[str(row["date"])].append(row)
    joined: list[dict[str, Any]] = []
    for date, rows in sorted(by_date.items()):
        result = result_rows(date)
        for source in rows:
            race_date, venue_key, race_number = parse_race_id(str(source["race_id"]))
            if race_date != date or venue_key not in JAPANESE_VENUE:
                raise Iter0Stop(f"STOP_PRE_RACE_IDENTITY:{source['race_id']}")
            result_row = result.get((JAPANESE_VENUE[venue_key], race_number))
            if result_row is None:
                raise Iter0Stop(f"STOP_RESULT_RACE_UNMATCHED:{source['race_id']}")
            valid, finish, top3 = outcome(result_row, int(source["horse_number"]))
            values = source["values"]
            joined.append({
                "date": date, "month": date[:6], "race_id": source["race_id"],
                "venue": JAPANESE_VENUE[venue_key], "race_number": race_number,
                "horse_number": int(source["horse_number"]), "horse_name": source.get("horse_name"),
                "current_rank": int(source["rank"]), "current_top5": bool(source["top5"]),
                "current_buy": values.get("post_rc1_decision") == "BUY",
                "shadow_ai_rank": number(values.get("shadow_ai_rank"), "shadow_ai_rank"),
                "past_performance": number(values.get("PastPerformance"), "PastPerformance"),
                "valid_result": bool(valid), "actual_finish": finish,
                "actual_top3": bool(top3) if valid else None,
                "features": vector(source),
            })
    if len(joined) != len(pre_rows) or len({(r["date"], r["race_id"], r["horse_number"]) for r in joined}) != len(joined):
        raise Iter0Stop("STOP_RESULT_JOIN_IDENTITY")
    return joined


def folds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    present = tuple(sorted({row["month"] for row in rows}))
    if present != MONTHS:
        raise Iter0Stop(f"STOP_MONTH_SCOPE:{present}")
    records = []
    for position, month in enumerate(MONTHS[1:], start=1):
        train_months, eval_months = MONTHS[:position], (month,)
        train = [row for row in rows if row["month"] in train_months and row["valid_result"]]
        evaluation = [row for row in rows if row["month"] == month]
        if not train or not evaluation or not {row["actual_top3"] for row in train} == {False, True}:
            raise Iter0Stop(f"STOP_ROLLING_FOLD_LABELS:{month}")
        records.append({"fold_id": f"ROLLING_ORIGIN_{month}", "train_months": list(train_months), "evaluation_months": list(eval_months), "train_rows": len(train), "evaluation_rows": len(evaluation), "evaluation_races": len({(r['date'], r['race_id']) for r in evaluation})})
    return records


def probability_model(train: list[dict[str, Any]], evaluation: list[dict[str, Any]]) -> tuple[np.ndarray, dict[str, Any]]:
    x = np.asarray([row["features"] for row in train], dtype=float)
    y = np.asarray([int(bool(row["actual_top3"])) for row in train], dtype=int)
    scaler = StandardScaler()
    model = LogisticRegression(solver="lbfgs", penalty="l2", C=1.0, class_weight=None, max_iter=100, tol=0.0001)
    fitted = model.fit(scaler.fit_transform(x), y)
    p = fitted.predict_proba(scaler.transform(np.asarray([row["features"] for row in evaluation], dtype=float)))[:, 1]
    return p, {"training_rows": len(train), "positive_rows": int(y.sum()), "negative_rows": int(len(y) - y.sum()), "recipe": "StandardScaler + LogisticRegression(l2,C=1.0,solver=lbfgs,class_weight=None,max_iter=100,tol=0.0001)"}


def rank_groups(rows: list[dict[str, Any]], score_name: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["date"], row["race_id"])].append(row)
    for key, group in grouped.items():
        group.sort(key=lambda item: (-float(item[score_name]), float(item["shadow_ai_rank"]), int(item["horse_number"])))
        for index, item in enumerate(group, start=1):
            item[f"{score_name}_rank"] = index
    return grouped


def metrics(name: str, rows: list[dict[str, Any]], score_name: str, *, same_volume: bool, probabilistic: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    groups = rank_groups(rows, score_name)
    selected: list[dict[str, Any]] = []
    rank1: list[dict[str, Any]] = []
    for _, group in groups.items():
        k = sum(bool(row["current_buy"]) for row in group) if same_volume else 1
        for index, row in enumerate(group, start=1):
            if index == 1:
                rank1.append(row)
            if index <= k:
                selected.append(row)
    valid_selected = [row for row in selected if row["valid_result"]]
    valid_rank1 = [row for row in rank1 if row["valid_result"]]
    valid_all = [row for row in rows if row["valid_result"]]
    y = np.asarray([int(bool(row["actual_top3"])) for row in valid_all], dtype=int)
    p = np.asarray([float(row[score_name]) for row in valid_all], dtype=float)
    result = {
        "comparator": name, "raw_selected_n": len(selected), "valid_selected_n": len(valid_selected),
        "same_volume_top3_hits": sum(bool(row["actual_top3"]) for row in valid_selected),
        "same_volume_buy_top3_rate": (sum(bool(row["actual_top3"]) for row in valid_selected) / len(valid_selected)) if valid_selected else None,
        "rank1_valid_n": len(valid_rank1), "rank1_top3_hits": sum(bool(row["actual_top3"]) for row in valid_rank1),
        "rank1_top3_rate": (sum(bool(row["actual_top3"]) for row in valid_rank1) / len(valid_rank1)) if valid_rank1 else None,
        "full_field_valid_n": len(valid_all), "full_field_top3_coverage": 1.0,
        "auc": float(roc_auc_score(y, p)) if len(set(y)) == 2 else None,
        "brier": float(brier_score_loss(y, p)) if probabilistic else None,
        "selected_race_count": len({(row['date'], row['race_id']) for row in selected}),
        "evaluation_race_count": len(groups),
    }
    return result, selected


def calibration(rows: list[dict[str, Any]], score_name: str, comparator: str) -> list[dict[str, Any]]:
    bins = [{"count": 0, "sum_probability": 0.0, "sum_actual": 0} for _ in range(10)]
    for row in rows:
        if not row["valid_result"]:
            continue
        probability = min(1.0, max(0.0, float(row[score_name])))
        index = min(9, int(probability * 10))
        bins[index]["count"] += 1; bins[index]["sum_probability"] += probability; bins[index]["sum_actual"] += int(bool(row["actual_top3"]))
    return [{"comparator": comparator, "bin": index, "valid_n": item["count"], "mean_prediction": item["sum_probability"] / item["count"] if item["count"] else None, "observed_top3_rate": item["sum_actual"] / item["count"] if item["count"] else None} for index, item in enumerate(bins)]


def run() -> None:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    determinism = json.loads(DETERMINISM.read_text(encoding="utf-8"))
    if determinism.get("status") != "PASS" or determinism.get("RUN_C_D_DIFFERENCE_COUNT") != 0:
        raise Iter0Stop("STOP_DETERMINISM_GATE")
    pre = load_pre_rows()  # The pre-freeze is complete before any result read below.
    pre_sha = sha(DETERMINISM)
    OUT.mkdir(parents=True)
    dump("governance_scope.json", {"execution_role": "DEVELOPMENT_ONLY_NON_EVIDENTIAL", "human_approval": "CONFIRMED", "scope_dates": 62, "pre_rows": len(pre), "production_change": False, "formal_advancement": False, "threshold_optimization": False, "feature_search": False, "parameter_search": False})
    dump("december_holdout_status.json", {"status": "CONSUMED", "canonical_record": "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md:511-516", "iter0_holdout_usage": 0, "december_2025_used": False})
    dump("pre_only_regeneration_manifest.json", {"frozen_run": "run_c", "source": str(PRE_ROOT.relative_to(ROOT)).replace("\\", "/"), "row_count": len(pre), "determinism_comparison": str(DETERMINISM.relative_to(ROOT)).replace("\\", "/"), "determinism_sha256": pre_sha, "result_joined_before_freeze": False})

    joined = result_join(pre)
    valid = [row for row in joined if row["valid_result"]]
    if not valid or any(row["month"] == "202512" for row in joined):
        raise Iter0Stop("STOP_LABEL_JOIN_OR_DECEMBER_BOUNDARY")
    dump("full_field_dataset_manifest.json", {"population": "ALL_ELIGIBLE_PRE_REGENERATED_HORSES", "top5_population_filter": False, "row_count": len(joined), "valid_label_rows": len(valid), "invalid_label_rows": len(joined) - len(valid), "positive_rows": sum(bool(row["actual_top3"]) for row in valid), "result_label_join_after_pre_freeze": True, "source_pre_sha256": pre_sha})
    csv_write("full_field_result_labels.csv", [{k: v for k, v in row.items() if k != "features"} for row in joined], ["date", "month", "race_id", "venue", "race_number", "horse_number", "horse_name", "current_rank", "current_top5", "current_buy", "shadow_ai_rank", "past_performance", "valid_result", "actual_finish", "actual_top3"])

    split = folds(joined)
    dump("split_manifest.json", {"cross_fit": "ROLLING_ORIGIN_MONTHLY_CROSS_FIT", "february_training_only": True, "folds": split, "result_leakage": "PROHIBITED"})
    all_rows: dict[str, list[dict[str, Any]]] = {"CURRENT_RANK_SAME_VOLUME": [], "PP_ONLY_RANKING": [], "V5_PROCEDURE_ON_V5_1": []}
    model_audit: list[dict[str, Any]] = []
    for fold in split:
        train_months, eval_month = set(fold["train_months"]), fold["evaluation_months"][0]
        train = [row for row in joined if row["month"] in train_months and row["valid_result"]]
        evaluation = [dict(row) for row in joined if row["month"] == eval_month]
        probability, audit = probability_model(train, evaluation)
        model_audit.append({"fold_id": fold["fold_id"], **audit})
        for row, value in zip(evaluation, probability):
            row["v5_probability"] = float(value)
            row["pp_probability"] = float(row["past_performance"])
            row["current_probability"] = -float(row["current_rank"])
        all_rows["CURRENT_RANK_SAME_VOLUME"].extend(evaluation)
        all_rows["PP_ONLY_RANKING"].extend([dict(row) for row in evaluation])
        all_rows["V5_PROCEDURE_ON_V5_1"].extend([dict(row) for row in evaluation])
    dump("cross_fit_training_audit.json", {"models": model_audit, "all_data_final_fit": 0, "v5_recipe": "frozen V5 StandardScaler + LogisticRegression", "legacy_tau_used": False})

    specs = {"CURRENT_RANK_SAME_VOLUME": "current_probability", "PP_ONLY_RANKING": "pp_probability", "V5_PROCEDURE_ON_V5_1": "v5_probability"}
    pooled: list[dict[str, Any]] = []; monthly: list[dict[str, Any]] = []; venue: list[dict[str, Any]] = []; calibration_rows: list[dict[str, Any]] = []; selections: list[dict[str, Any]] = []
    for name, score in specs.items():
        probabilistic = name == "V5_PROCEDURE_ON_V5_1"
        result, selected = metrics(name, all_rows[name], score, same_volume=True, probabilistic=probabilistic)
        pooled.append(result)
        if probabilistic:
            calibration_rows.extend(calibration(all_rows[name], score, name))
        for row in selected:
            selections.append({"comparator": name, "selected": True, **{k: v for k, v in row.items() if k not in {"features"}}})
        for month in MONTHS[1:]:
            metric, _ = metrics(name, [row for row in all_rows[name] if row["month"] == month], score, same_volume=True, probabilistic=probabilistic)
            monthly.append(metric | {"month": month})
        for venue_name in sorted({row["venue"] for row in all_rows[name]}):
            metric, _ = metrics(name, [row for row in all_rows[name] if row["venue"] == venue_name], score, same_volume=True, probabilistic=probabilistic)
            venue.append(metric | {"venue": venue_name})
    csv_write("comparator_metrics_pooled.csv", pooled, list(pooled[0]))
    csv_write("comparator_metrics_monthly.csv", monthly, list(monthly[0]))
    csv_write("comparator_metrics_venue.csv", venue, list(venue[0]))
    csv_write("rank1_metrics.csv", pooled, ["comparator", "rank1_valid_n", "rank1_top3_hits", "rank1_top3_rate", "auc", "brier"])
    csv_write("same_volume_metrics.csv", pooled, ["comparator", "raw_selected_n", "valid_selected_n", "same_volume_top3_hits", "same_volume_buy_top3_rate", "selected_race_count"])
    csv_write("full_field_top3_coverage.csv", pooled, ["comparator", "full_field_valid_n", "full_field_top3_coverage"])
    csv_write("calibration_metrics.csv", calibration_rows, list(calibration_rows[0]))
    csv_write("cross_fit_selected_horses.csv", selections, ["comparator", "selected", "date", "month", "race_id", "venue", "race_number", "horse_number", "horse_name", "current_rank", "current_top5", "current_buy", "shadow_ai_rank", "past_performance", "valid_result", "actual_finish", "actual_top3", "current_probability", "pp_probability", "v5_probability"])

    by_name = {row["comparator"]: row for row in pooled}
    pp, v5 = by_name["PP_ONLY_RANKING"], by_name["V5_PROCEDURE_ON_V5_1"]
    simplify = bool(pp["same_volume_buy_top3_rate"] >= v5["same_volume_buy_top3_rate"] and pp["rank1_top3_rate"] >= v5["rank1_top3_rate"])
    dump("simplify_check.json", {"criterion": "PP_ONLY same-volume and rank1 rates >= V5 procedure, no optimisation", "pp_only_exceeds_or_equals_v5": simplify, "SIMPLIFY_SIGNAL": simplify})
    dump("market_benchmark.json", {"status": "NOT_AVAILABLE", "reason": "No frozen PRE-time market provenance was registered for this Iter0 authority; no market source was opened."})
    dump("v51_semantic_equivalence.json", {"status": "NOT_PROVEN", "authority": "reports/decision_engine_determinism_fix_v1/v51_semantic_equivalence_after_fix.json", "development_continuation": "ALLOWED_WITH_PIT_UNPROVEN", "formal_evidence": False})
    dump("result_access_audit.json", {"result_label_join": "AFTER_PRE_FREEZE_ONLY", "result_access_during_regeneration": 0, "post_artifact_access_during_regeneration": 0, "learning_access_during_regeneration": 0, "network_access_during_regeneration": 0, "december_2025_usage": 0})
    report = ["# Full-field Redesign Iter0 — Retry 8", "", "`DEVELOPMENT_ONLY_NON_EVIDENTIAL`", "", f"- PRE freeze: 62 dates / {len(pre)} horses", f"- Valid labelled rows: {len(valid)}", "- Evaluation: rolling-origin, March–September; February is train-only.", "- Market benchmark: NOT_AVAILABLE (no valid PRE-time provenance opened).", "- V5.1 semantic equivalence: NOT_PROVEN; Iter0 remains development-only.", "- Brier/calibration are reported only for the V5 probability model; rank-only comparators do not claim calibrated probabilities.", "", "## Pooled comparators", "", "| Comparator | Same-volume hits / valid N | Rate | Rank1 rate | AUC | Brier |", "|---|---:|---:|---:|---:|---:|"]
    for row in pooled:
        brier = "N/A (rank only)" if row["brier"] is None else f"{row['brier']:.4f}"
        report.append(f"| {row['comparator']} | {row['same_volume_top3_hits']} / {row['valid_selected_n']} | {row['same_volume_buy_top3_rate']:.4f} | {row['rank1_top3_rate']:.4f} | {row['auc']:.4f} | {brier} |")
    report.extend(["", f"SIMPLIFY_SIGNAL = {simplify}", "", "No Production or Formal advancement is authorized by this report."])
    (OUT / "summary.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    hashes = {str(path.relative_to(OUT)).replace("\\", "/"): {"sha256": sha(path), "size": path.stat().st_size} for path in sorted(OUT.rglob("*")) if path.is_file() and path.name != "artifact_hashes.json"}
    dump("artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": hashes})
    print("FULL_FIELD_REDESIGN_ITER0_RETRY8=COMPLETE")


if __name__ == "__main__":
    run()
