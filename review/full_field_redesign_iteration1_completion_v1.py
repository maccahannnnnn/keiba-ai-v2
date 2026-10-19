"""Iteration 1 development-only completion: fixed-scope daily global Top-N.

This is deliberately separate from the frozen Iter0 runner.  It consumes the
same PRE-only 62-day materialisation and freezes ranking semantics before any
result source is read.  It is not a BUY rule or Formal Evidence runner.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review import full_field_redesign_iter0_retry7 as iter0


OUT = ROOT / "reports" / "full_field_redesign_iteration1_completion_v1"
ITER0 = ROOT / "reports" / "full_field_redesign_iter0_v1_retry8"
PRE_ROOT = ROOT / "reports" / "full_field_redesign_iter0_v1_retry6" / "pre_only_regeneration" / "shards"
MONTHS = ("202602", "202603", "202604", "202605", "202606", "202607", "202608", "202609")
EVALUATION_MONTHS = MONTHS[1:]
FEATURES = tuple(iter0.FEATURES)
COMPARATORS = ("CURRENT", "PP_ONLY_DETERMINISTIC", "V5_TOP5_TRAINED", "V5_FULL_FIELD_TRAINED")


class Stop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def write_json(name: str, value: Any) -> Path:
    path = OUT / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def write_csv(name: str, rows: list[dict[str, Any]], fields: list[str]) -> Path:
    path = OUT / name
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def pct(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def finite_number(value: Any, label: str) -> float:
    try:
        answer = float(value)
    except (TypeError, ValueError) as exc:
        raise Stop(f"STOP_MISSING_OR_NON_NUMERIC_{label}:{value!r}") from exc
    if not math.isfinite(answer):
        raise Stop(f"STOP_NONFINITE_{label}:{value!r}")
    return answer


def parse_race(row: dict[str, Any]) -> tuple[str, int]:
    _, venue, race_number = iter0.parse_race_id(str(row["race_id"]))
    return venue, int(race_number)


def vector(row: dict[str, Any]) -> list[float]:
    values = row["features"]
    if isinstance(values, list):
        return [float(value) for value in values]
    return iter0.vector(values)


def model_recipe() -> dict[str, Any]:
    return {
        "scaler": "StandardScaler",
        "model": "LogisticRegression",
        "solver": "lbfgs",
        "penalty": "l2",
        "C": 1.0,
        "class_weight": None,
        "max_iter": 100,
        "tol": 0.0001,
        "semantic_feature_order": list(FEATURES),
        "transformed_input_count": 21,
    }


def fit_predict(train: list[dict[str, Any]], evaluate: list[dict[str, Any]], score_key: str) -> None:
    if not train or not evaluate:
        raise Stop("STOP_EMPTY_ROLLING_ORIGIN_FOLD")
    labels = np.asarray([int(row["actual_top3"]) for row in train], dtype=int)
    if len(set(labels.tolist())) != 2:
        raise Stop("STOP_SINGLE_CLASS_TRAINING_FOLD")
    scaler = StandardScaler()
    transformed_train = scaler.fit_transform(np.asarray([vector(row) for row in train], dtype=float))
    model = LogisticRegression(solver="lbfgs", penalty="l2", C=1.0, class_weight=None, max_iter=100, tol=0.0001)
    model.fit(transformed_train, labels)
    probabilities = model.predict_proba(scaler.transform(np.asarray([vector(row) for row in evaluate], dtype=float)))[:, 1]
    for row, probability in zip(evaluate, probabilities):
        row[score_key] = float(probability)


def rank_key(row: dict[str, Any], comparator: str, venue_order: dict[str, int]) -> tuple[Any, ...]:
    # Human-approved deterministic fallback: the existing materialised PRE
    # order, not an inferred venue or performance ordering.
    common = (str(row["date"]), str(row["race_id"]), int(row["horse_number"]))
    if comparator == "CURRENT":
        # TargetTrialAdapter ranks adjusted_score DESC, horse_number DESC.
        return (-finite_number(row["adjusted_score"], "ADJUSTED_SCORE"), -int(row["horse_number"]), *common)
    if comparator == "PP_ONLY_DETERMINISTIC":
        # No Current/shadow rank may enter this score or tie-break.
        return (-finite_number(row["past_performance"], "PAST_PERFORMANCE"), *common)
    score = "p_top5_trained" if comparator == "V5_TOP5_TRAINED" else "p_full_field_trained"
    # Formal V5 frozen order for probability ties, followed by stable cross-race order.
    return (-finite_number(row[score], score.upper()), finite_number(row["shadow_ai_rank"], "SHADOW_AI_RANK"), int(row["horse_number"]), *common)


def select_global(rows: list[dict[str, Any]], comparator: str, budget: int, venue_order: dict[str, int]) -> list[dict[str, Any]]:
    if budget < 0 or budget > len(rows):
        raise Stop(f"STOP_INVALID_DAILY_BUDGET:{budget}/{len(rows)}")
    return sorted(rows, key=lambda row: rank_key(row, comparator, venue_order))[:budget]


def select_per_race(rows: list[dict[str, Any]], comparator: str, budget: int, venue_order: dict[str, int]) -> list[dict[str, Any]]:
    if comparator == "CURRENT":
        return [row for row in rows if row["current_buy"]]
    return select_global(rows, comparator, budget, venue_order)


def metric(rows: Iterable[dict[str, Any]], selected: Iterable[dict[str, Any]]) -> dict[str, Any]:
    selected = list(selected)
    valid = [row for row in selected if row["valid_result"]]
    hits = sum(int(row["actual_top3"]) for row in valid)
    by_race = Counter((row["date"], row["race_id"]) for row in selected)
    return {
        "selected_n": len(selected),
        "invalid_n": len(selected) - len(valid),
        "valid_n": len(valid),
        "top3_hits": hits,
        "top3_rate": pct(hits, len(valid)),
        "races_represented": len(by_race),
        "selection_per_race_distribution": json.dumps(dict(sorted(Counter(by_race.values()).items())), ensure_ascii=False, sort_keys=True),
    }


def auc_score(rows: list[dict[str, Any]], score_key: str) -> float | None:
    valid = [row for row in rows if row["valid_result"]]
    positives = sum(int(row["actual_top3"]) for row in valid)
    negatives = len(valid) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(valid, key=lambda row: finite_number(row[score_key], score_key))
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        score = finite_number(ordered[index][score_key], score_key)
        end = index + 1
        while end < len(ordered) and finite_number(ordered[end][score_key], score_key) == score:
            end += 1
        average_rank = (index + 1 + end) / 2
        rank_sum += average_rank * sum(int(row["actual_top3"]) for row in ordered[index:end])
        index = end
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def calibration(rows: list[dict[str, Any]], score_key: str) -> dict[str, Any]:
    valid = [row for row in rows if row["valid_result"]]
    if not valid:
        return {"auc": None, "brier": None, "ece": None, "calibration_bins": []}
    probs = [finite_number(row[score_key], score_key) for row in valid]
    labels = [int(row["actual_top3"]) for row in valid]
    brier = sum((probability - label) ** 2 for probability, label in zip(probs, labels)) / len(valid)
    bins: list[dict[str, Any]] = []
    ece = 0.0
    for index in range(10):
        low, high = index / 10, (index + 1) / 10
        bucket = [(probability, label) for probability, label in zip(probs, labels) if low <= probability < high or (index == 9 and probability == 1.0)]
        if not bucket:
            bins.append({"lower": low, "upper": high, "n": 0, "mean_probability": None, "observed_rate": None})
            continue
        mean_probability = sum(item[0] for item in bucket) / len(bucket)
        observed = sum(item[1] for item in bucket) / len(bucket)
        ece += len(bucket) / len(valid) * abs(mean_probability - observed)
        bins.append({"lower": low, "upper": high, "n": len(bucket), "mean_probability": mean_probability, "observed_rate": observed})
    return {"auc": auc_score(valid, score_key), "brier": brier, "ece": ece, "calibration_bins": bins}


def bootstrap_difference(left_by_date: dict[str, dict[str, Any]], right_by_date: dict[str, dict[str, Any]], *, seed: int = 20261014, rounds: int = 10000) -> dict[str, Any]:
    dates = sorted(set(left_by_date) & set(right_by_date))
    if not dates:
        raise Stop("STOP_BOOTSTRAP_NO_COMMON_DATES")
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(rounds):
        sampled = [rng.choice(dates) for _ in dates]
        left_hits = sum(left_by_date[date]["top3_hits"] for date in sampled)
        left_valid = sum(left_by_date[date]["valid_n"] for date in sampled)
        right_hits = sum(right_by_date[date]["top3_hits"] for date in sampled)
        right_valid = sum(right_by_date[date]["valid_n"] for date in sampled)
        if left_valid and right_valid:
            values.append(right_hits / right_valid - left_hits / left_valid)
    values.sort()
    observed_left_hits = sum(left_by_date[date]["top3_hits"] for date in dates)
    observed_left_valid = sum(left_by_date[date]["valid_n"] for date in dates)
    observed_right_hits = sum(right_by_date[date]["top3_hits"] for date in dates)
    observed_right_valid = sum(right_by_date[date]["valid_n"] for date in dates)
    return {
        "left": "", "right": "", "unit": "date", "seed": seed, "rounds": rounds,
        "observed_difference": observed_right_hits / observed_right_valid - observed_left_hits / observed_left_valid,
        "ci_95_lower": values[int(0.025 * (len(values) - 1))],
        "ci_95_upper": values[int(0.975 * (len(values) - 1))],
        "date_count": len(dates),
    }


def assert_iter0_compatibility(folds: list[dict[str, Any]]) -> dict[str, Any]:
    path = ITER0 / "cross_fit_training_audit.json"
    split_path = ITER0 / "split_manifest.json"
    if not path.exists() or not split_path.exists():
        raise Stop("STOP_ITER0_COMPATIBILITY_ARTIFACT_MISSING")
    existing = json.loads(path.read_text(encoding="utf-8"))
    existing_split = json.loads(split_path.read_text(encoding="utf-8"))
    existing_folds = existing_split.get("folds")
    comparable = [{key: value for key, value in fold.items() if key in {"fold_id", "train_months", "evaluation_months", "train_rows", "evaluation_rows", "evaluation_races"}} for fold in folds]
    old_comparable = [{key: fold.get(key) for key in {"fold_id", "train_months", "evaluation_months", "train_rows", "evaluation_rows", "evaluation_races"}} for fold in existing_folds or []]
    expected_recipe = "StandardScaler + LogisticRegression(l2,C=1.0,solver=lbfgs,class_weight=None,max_iter=100,tol=0.0001)"
    recipe_ok = existing.get("v5_recipe") == "frozen V5 StandardScaler + LogisticRegression" and all(model.get("recipe") == expected_recipe for model in existing.get("models", []))
    folds_ok = old_comparable == comparable
    # Iter0 imported the same frozen FEATURE tuple from this runner module; its
    # report predates a dedicated feature-order artifact, so assert the concrete
    # executable authority and record its SHA rather than inventing a schema.
    feature_ok = tuple(iter0.FEATURES) == FEATURES
    if not (recipe_ok and folds_ok and feature_ok):
        raise Stop("STOP_ITER0_FULL_FIELD_COMPARATOR_MATERIAL_DIFFERENCE")
    return {"status": "PASS", "iter0_cross_fit_training_audit": str(path.relative_to(ROOT)), "iter0_sha256": sha256(path), "iter0_split_manifest": str(split_path.relative_to(ROOT)), "iter0_split_sha256": sha256(split_path), "iter0_runner": str((ROOT / "review" / "full_field_redesign_iter0_retry7.py").relative_to(ROOT)), "iter0_runner_sha256": sha256(ROOT / "review" / "full_field_redesign_iter0_retry7.py"), "recipe_match": recipe_ok, "split_match": folds_ok, "feature_order_match": feature_ok}


def assert_current_ranking(rows: list[dict[str, Any]], venue_order: dict[str, int]) -> None:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["date"], row["race_id"])].append(row)
        finite_number(row["adjusted_score"], "ADJUSTED_SCORE")
    for key, group in groups.items():
        actual = [int(row["horse_number"]) for row in sorted(group, key=lambda item: rank_key(item, "CURRENT", venue_order))]
        expected = [int(row["current_rank"] and row["horse_number"]) for row in sorted(group, key=lambda item: int(item["current_rank"]))]
        if actual != expected:
            raise Stop(f"STOP_CURRENT_GLOBAL_SCORE_UNRESOLVED:{key}")


def main() -> None:
    if OUT.exists():
        # A pre-result implementation stop is retained as audit evidence, but
        # it contains no freeze artifact and may be safely followed by retry 1.
        existing = {path.name for path in OUT.iterdir()}
        if existing != {"execution_stop.json"}:
            raise Stop(f"STOP_OUTPUT_EXISTS:{OUT}")
    else:
        OUT.mkdir(parents=True)
    try:
        pre_rows = iter0.load_pre_rows()
        raw_dates = sorted({str(row["date"]) for row in pre_rows})
        if len(raw_dates) != 62 or any(date.startswith("202512") for date in raw_dates) or any(date >= "20260926" for date in raw_dates):
            raise Stop("STOP_SCOPE_DATE_VIOLATION")
        venue_order: dict[str, int] = {}
        # Existing deterministic PRE materialisation sorts (date, race_id,
        # horse_number).  The Human-approved PP fallback is this exact order.
        existing_ids = [(row["date"], row["race_id"], int(row["horse_number"])) for row in sorted(pre_rows, key=lambda row: (str(row["date"]), str(row["race_id"]), int(row["horse_number"]))) ]
        if not existing_ids:
            raise Stop("STOP_PRE_CANONICAL_ORDER_EMPTY")
        # PRE-only material is now the only source used until these freeze artifacts are written.
        for row in pre_rows:
            values = row["values"]
            row["adjusted_score"] = finite_number(values.get("adjusted_score"), "ADJUSTED_SCORE")
            row["past_performance"] = finite_number(values.get("PastPerformance"), "PAST_PERFORMANCE")
            row["shadow_ai_rank"] = finite_number(values.get("shadow_ai_rank"), "SHADOW_AI_RANK")
            row["current_rank"] = int(row["rank"])
            row["current_top5"] = bool(row["top5"])
            row["current_buy"] = values.get("post_rc1_decision") == "BUY"
            row["features"] = {name: values.get(name) for name in FEATURES}
        assert_current_ranking(pre_rows, venue_order)
        iter0_split_path = ITER0 / "split_manifest.json"
        if not iter0_split_path.exists():
            raise Stop("STOP_ITER0_SPLIT_MANIFEST_MISSING")
        frozen_iter0_split = json.loads(iter0_split_path.read_text(encoding="utf-8"))
        folds = frozen_iter0_split.get("folds")
        if not isinstance(folds, list) or len(folds) != len(EVALUATION_MONTHS):
            raise Stop("STOP_ITER0_SPLIT_MANIFEST_INVALID")
        budgets = []
        by_pre_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in pre_rows:
            by_pre_date[row["date"]].append(row)
        for date, rows in sorted(by_pre_date.items()):
            budgets.append({"date": date, "month": date[:6], "current_pre_buy_count": sum(row["current_buy"] for row in rows), "eligible_horse_count": len(rows), "eligible_race_count": len({row["race_id"] for row in rows})})
        governance = {
            "execution_role": "DEVELOPMENT_ONLY_NON_EVIDENTIAL", "iteration": 1,
            "additional_iteration_consumed": False, "fixed_scope": {"date_count": len(raw_dates), "dates": raw_dates, "december_2025_usage": 0, "prospective_results_20260926_plus_usage": 0},
            "prohibitions": ["feature change", "model family change", "hyperparameter change", "threshold/tau tuning", "Current-derived feature ablation", "BUY rule change", "Production change", "Formal advancement"],
            "current_feature_ablation": "DEFER", "market_benchmark": "NOT_AVAILABLE", "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        split_manifest = {"rolling_origin_monthly_cross_fit": folds, "months": list(MONTHS), "evaluation_months": list(EVALUATION_MONTHS), "feature_order": list(FEATURES), "model_recipe": model_recipe(), "iter0_split_manifest": str(iter0_split_path.relative_to(ROOT)), "iter0_split_manifest_sha256": sha256(iter0_split_path), "post_result_row_count_reassertion_required": True}
        ranking_spec = {
            "GLOBAL_RANKING_SPEC_FROZEN_BEFORE_RESULT": True,
            "pre_result_freeze_sequence": ["PRE-only rows", "scope/split validation", "Current score validation", "global ranking specification", "daily Current BUY budgets", "only then Result join"],
            "canonical_pre_race_order_authority": {"source": "review/ws2_deterministic_pre_only_regeneration_v1.py:418 and :600", "existing_order": "date ASC, race_id string ASC, horse_number ASC", "human_approval": "ITERATION_1_RESUME_PP_DETERMINISTIC_TIEBREAK", "validation": "PASS"},
            "daily_selection_budget": "N = frozen Current PRE post_rc1_decision == BUY count for the date; N is not changed for invalid POST results",
            "invalid_horse_handling": "selected invalid results remain in frozen raw N and are excluded from valid denominator; no replacement",
            "comparators": {
                "CURRENT": {"score_field": "adjusted_score", "direction": "DESC", "rank_authority": "evaluation/target_trial_adapter.py:316-320", "tie_break": ["horse_number DESC (same-race canonical Current ranking)", "existing PRE date/race_id string/horse_number order for complete cross-race ties"], "missing_score": "STOP"},
                "PP_ONLY_DETERMINISTIC": {"score_field": "PastPerformance", "direction": "DESC", "tie_break": ["date ASC", "existing PRE canonical race_id string ASC", "horse_number ASC"], "CURRENT_RANK_used": False, "RESULT_dependent": False, "ODDS_POPULARITY_dependent": False, "forbidden_tie_breaks": ["Current rank", "shadow_ai_rank"], "missing_score": "STOP"},
                "V5_TOP5_TRAINED": {"score_field": "cross-fit p(actual_top3)", "direction": "DESC", "train_population": "Current Top5 only", "inference_population": "full field", "tie_break": ["Formal V5 frozen: shadow_ai_rank ASC", "horse_number ASC", "existing PRE date/race_id string/horse_number order"], "missing_score": "STOP"},
                "V5_FULL_FIELD_TRAINED": {"score_field": "cross-fit p(actual_top3)", "direction": "DESC", "train_population": "all eligible full-field rows", "inference_population": "full field", "tie_break": ["Formal V5 frozen: shadow_ai_rank ASC", "horse_number ASC", "existing PRE date/race_id string/horse_number order"], "missing_score": "STOP"},
            },
        }
        write_json("governance_scope.json", governance)
        write_json("iteration_status.json", {"ITERATION_1_STATUS": "RUNNING_COMPLETION", "previous_status": "PARTIALLY_EXECUTED", "additional_iteration_consumed": False, "iter0_reuse_compatibility": "PENDING_POST_RESULT_ROW_COUNT_REASSERTION"})
        write_json("split_manifest.json", split_manifest)
        ranking_path = write_json("global_ranking_spec.json", ranking_spec)
        write_csv("daily_current_buy_budget.csv", budgets, list(budgets[0]))
        write_json("pre_result_freeze_manifest.json", {"status": "FROZEN", "global_ranking_spec_sha256": sha256(ranking_path), "pre_root": str(PRE_ROOT.relative_to(ROOT)), "pre_shard_count": len(list(PRE_ROOT.glob("run_c_*/runtime_pre_only_output.json"))), "pre_row_count": len(pre_rows), "result_access_before_freeze": 0, "source_order_validation": "PASS", "current_score_validation": "PASS"})

        # Result access starts only after all ranking semantics and budgets are written.
        rows = iter0.result_join(pre_rows)
        pre_by_id = {(row["date"], row["race_id"], int(row["horse_number"])): row for row in pre_rows}
        for row in rows:
            source = pre_by_id[(row["date"], row["race_id"], int(row["horse_number"]))]
            row["adjusted_score"] = source["adjusted_score"]
        for row in rows:
            row["p_top5_trained"] = None
            row["p_full_field_trained"] = None
        actual_folds = iter0.folds(rows)
        compatibility = assert_iter0_compatibility(actual_folds)
        if actual_folds != folds:
            raise Stop("STOP_ROLLING_SPLIT_ROW_COUNT_MISMATCH")
        fold_audit: list[dict[str, Any]] = []
        for fold in actual_folds:
            train = [row for row in rows if row["month"] in fold["train_months"] and row["valid_result"]]
            evaluate = [row for row in rows if row["month"] in fold["evaluation_months"]]
            top5_train = [row for row in train if row["current_top5"]]
            if len(top5_train) == 0:
                raise Stop("STOP_TOP5_TRAINING_POPULATION_EMPTY")
            fit_predict(top5_train, evaluate, "p_top5_trained")
            fit_predict(train, evaluate, "p_full_field_trained")
            fold_audit.append({**fold, "top5_train_rows": len(top5_train), "top5_train_positives": sum(int(row["actual_top3"]) for row in top5_train), "full_train_rows": len(train), "full_train_positives": sum(int(row["actual_top3"]) for row in train)})
        evaluation_rows = [row for row in rows if row["month"] in EVALUATION_MONTHS]
        if any(row["p_top5_trained"] is None or row["p_full_field_trained"] is None for row in evaluation_rows):
            raise Stop("STOP_CROSS_FIT_SCORE_MISSING")
        # Selection is generated only from frozen scores/budgets; labels never affect membership.
        budgets_by_date = {row["date"]: int(row["current_pre_buy_count"]) for row in budgets if row["month"] in EVALUATION_MONTHS}
        by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in evaluation_rows:
            by_date[row["date"]].append(row)
        selections: dict[str, dict[str, list[dict[str, Any]]]] = {name: {} for name in COMPARATORS}
        primary_date_rows: list[dict[str, Any]] = []
        selected_freeze: list[dict[str, Any]] = []
        for date, group in sorted(by_date.items()):
            budget = budgets_by_date[date]
            for comparator in COMPARATORS:
                chosen = select_global(group, comparator, budget, venue_order)
                selections[comparator][date] = chosen
                values = metric(group, chosen)
                primary_date_rows.append({"comparator": comparator, "date": date, "month": date[:6], "daily_budget_n": budget, "eligible_pool_n": len(group), **values})
                for rank, row in enumerate(chosen, start=1):
                    selected_freeze.append({"comparator": comparator, "date": date, "race_id": row["race_id"], "venue": row["venue"], "race_number": row["race_number"], "horse_number": row["horse_number"], "horse_name": row["horse_name"], "global_rank": rank, "score": row["adjusted_score"] if comparator == "CURRENT" else row["past_performance"] if comparator == "PP_ONLY_DETERMINISTIC" else row["p_top5_trained"] if comparator == "V5_TOP5_TRAINED" else row["p_full_field_trained"], "current_top5": row["current_top5"], "selected_pre_result_membership_fixed": True})
        write_csv("primary_global_selected_horses.csv", selected_freeze, list(selected_freeze[0]))
        write_json("primary_selection_freeze_manifest.json", {"status": "FROZEN_POST_SCORE_PRE_METRIC", "selection_membership_sha256": sha256(OUT / "primary_global_selected_horses.csv"), "result_access_before_global_ranking_spec": 0, "selection_generated_from": "fixed score/tie-break/budget definitions"})
        write_json("cross_fit_training_audit.json", {"status": "PASS", "folds": fold_audit, "top5_train_inference": "full field", "full_field_train_inference": "full field", "recipe": model_recipe(), "training_population_only_difference": True})

        # Primary totals and months.
        primary_total: list[dict[str, Any]] = []
        primary_month: list[dict[str, Any]] = []
        date_metrics: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in primary_date_rows:
            date_metrics[row["comparator"]][row["date"]] = row
        for comparator in COMPARATORS:
            all_chosen = [row for date in sorted(selections[comparator]) for row in selections[comparator][date]]
            primary_total.append({"comparator": comparator, "metric": "DAILY_GLOBAL_TOP_N_TOP3_RATE", **metric(evaluation_rows, all_chosen), "date_count": len(selections[comparator]), "evaluation_race_count": len({(row["date"], row["race_id"]) for row in evaluation_rows})})
            for month in EVALUATION_MONTHS:
                chosen = [row for date, items in selections[comparator].items() if date.startswith(month) for row in items]
                primary_month.append({"comparator": comparator, "month": month, **metric(evaluation_rows, chosen), "date_count": len({row["date"] for row in chosen})})
        write_csv("primary_daily_global_topn_metrics.csv", primary_total, list(primary_total[0]))
        write_csv("primary_daily_global_topn_by_date.csv", primary_date_rows, list(primary_date_rows[0]))
        write_csv("primary_daily_global_topn_by_month.csv", primary_month, list(primary_month[0]))

        # Secondary race-conditioned same volume.
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in evaluation_rows:
            groups[(row["date"], row["race_id"])].append(row)
        secondary_selected: dict[str, list[dict[str, Any]]] = {name: [] for name in COMPARATORS}
        for _, group in groups.items():
            k = sum(row["current_buy"] for row in group)
            if not k:
                continue
            for comparator in COMPARATORS:
                secondary_selected[comparator].extend(select_per_race(group, comparator, k, venue_order))
        secondary = [{"comparator": comparator, "metric": "RACE_CONDITIONED_SAME_VOLUME_SECONDARY", **metric(evaluation_rows, secondary_selected[comparator])} for comparator in COMPARATORS]
        write_csv("secondary_race_conditioned_metrics.csv", secondary, list(secondary[0]))

        # One common rank-1 denominator for every comparator.
        rank1: dict[str, dict[tuple[str, str], dict[str, Any]]] = {name: {} for name in COMPARATORS}
        exclusions: list[dict[str, Any]] = []
        for identity, group in sorted(groups.items()):
            choices = {name: select_global(group, name, 1, venue_order)[0] for name in COMPARATORS}
            invalid_for = [name for name, row in choices.items() if not row["valid_result"]]
            if invalid_for:
                exclusions.append({"date": identity[0], "race_id": identity[1], "reason": "RANK1_INVALID_RESULT", "invalid_comparators": ";".join(invalid_for)})
                continue
            for name, row in choices.items():
                rank1[name][identity] = row
        common_races = sorted(set.intersection(*(set(items) for items in rank1.values())))
        rank1_metrics = []
        for name in COMPARATORS:
            chosen = [rank1[name][identity] for identity in common_races]
            rank1_metrics.append({"comparator": name, "metric": "COMMON_VALID_RACE_SET_RANK1_TOP3_RATE", "common_valid_races": len(common_races), **metric(evaluation_rows, chosen)})
        write_csv("rank1_common_denominator_metrics.csv", rank1_metrics, list(rank1_metrics[0]))
        write_csv("rank1_common_denominator_exclusions.csv", exclusions, ["date", "race_id", "reason", "invalid_comparators"])

        # Calibration is descriptive; bins were fixed in the pre-result ranking spec.
        calibration_rows: list[dict[str, Any]] = []
        for comparator, score_key in (("V5_TOP5_TRAINED", "p_top5_trained"), ("V5_FULL_FIELD_TRAINED", "p_full_field_trained")):
            for scope, subset in [("POOLED", evaluation_rows), *[(month, [row for row in evaluation_rows if row["month"] == month]) for month in EVALUATION_MONTHS]]:
                value = calibration(subset, score_key)
                calibration_rows.append({"comparator": comparator, "scope": scope, "valid_n": sum(row["valid_result"] for row in subset), "auc": value["auc"], "brier": value["brier"], "ece_fixed_10_bin": value["ece"], "calibration_bins_json": json.dumps(value["calibration_bins"], ensure_ascii=False)})
        write_csv("auc_brier_calibration.csv", calibration_rows, list(calibration_rows[0]))

        # Paired bootstrap uses fixed daily selections and labels only.
        bootstrap: dict[str, Any] = {"method": "paired date resampling; difference = right rate - left rate", "comparisons": {}}
        for left, right, label in (("CURRENT", "V5_FULL_FIELD_TRAINED", "CURRENT_VS_FULL_FIELD"), ("PP_ONLY_DETERMINISTIC", "V5_FULL_FIELD_TRAINED", "PP_VS_FULL_FIELD"), ("V5_TOP5_TRAINED", "V5_FULL_FIELD_TRAINED", "TOP5_VS_FULL_FIELD")):
            item = bootstrap_difference(date_metrics[left], date_metrics[right])
            item["left"], item["right"] = left, right
            bootstrap["comparisons"][label] = item
        write_json("paired_bootstrap.json", bootstrap)

        # Monthly W/L/T and leave-one-month-out.
        monthly_lookup = {(row["comparator"], row["month"]): row for row in primary_month}
        wlt_rows: list[dict[str, Any]] = []
        for left, right, label in (("V5_TOP5_TRAINED", "V5_FULL_FIELD_TRAINED", "TOP5_VS_FULL_FIELD"), ("PP_ONLY_DETERMINISTIC", "V5_FULL_FIELD_TRAINED", "PP_VS_FULL_FIELD")):
            wins = losses = ties = 0
            for month in EVALUATION_MONTHS:
                l_rate = monthly_lookup[(left, month)]["top3_rate"]
                r_rate = monthly_lookup[(right, month)]["top3_rate"]
                state = "WIN" if r_rate > l_rate else "LOSS" if r_rate < l_rate else "TIE"
                wins += state == "WIN"; losses += state == "LOSS"; ties += state == "TIE"
                wlt_rows.append({"comparison": label, "month": month, "left_rate": l_rate, "right_rate": r_rate, "right_minus_left": r_rate - l_rate, "outcome_for_right": state, "wins": "", "losses": "", "ties": ""})
            wlt_rows.append({"comparison": label, "month": "SUMMARY", "left_rate": "", "right_rate": "", "right_minus_left": "", "outcome_for_right": "", "wins": wins, "losses": losses, "ties": ties})
        write_csv("monthly_win_loss_tie.csv", wlt_rows, list(wlt_rows[0]))
        loo_rows: list[dict[str, Any]] = []
        for omitted in EVALUATION_MONTHS:
            for comparator in COMPARATORS:
                chosen = [row for date, selected in selections[comparator].items() if not date.startswith(omitted) for row in selected]
                loo_rows.append({"omitted_month": omitted, "comparator": comparator, **metric(evaluation_rows, chosen)})
        write_csv("leave_one_month_out.csv", loo_rows, list(loo_rows[0]))

        # Training-population selection decomposition and external-to-Current-Top5 evidence.
        effect_rows: list[dict[str, Any]] = []
        external_rows: list[dict[str, Any]] = []
        for date in sorted(by_date):
            top5_ids = {(row["date"], row["race_id"], row["horse_number"]) for row in selections["V5_TOP5_TRAINED"][date]}
            full_ids = {(row["date"], row["race_id"], row["horse_number"]) for row in selections["V5_FULL_FIELD_TRAINED"][date]}
            for bucket, ids in (("BOTH_SELECTED", top5_ids & full_ids), ("TOP5_TRAINED_ONLY", top5_ids - full_ids), ("FULL_FIELD_TRAINED_ONLY", full_ids - top5_ids)):
                subset = [row for row in by_date[date] if (row["date"], row["race_id"], row["horse_number"]) in ids]
                effect_rows.append({"date": date, "month": date[:6], "bucket": bucket, **metric(evaluation_rows, subset)})
            for inside, label in ((True, "CURRENT_TOP5_INSIDE"), (False, "CURRENT_TOP5_OUTSIDE")):
                subset = [row for row in selections["V5_FULL_FIELD_TRAINED"][date] if row["current_top5"] is inside]
                external_rows.append({"date": date, "month": date[:6], "bucket": label, **metric(evaluation_rows, subset)})
        for collection in (effect_rows, external_rows):
            summary: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in collection:
                summary[row["bucket"]].append(row)
            for bucket, items in summary.items():
                selected_n = sum(int(item["selected_n"]) for item in items); valid_n = sum(int(item["valid_n"]) for item in items); hits = sum(int(item["top3_hits"]) for item in items)
                collection.append({"date": "POOLED", "month": "POOLED", "bucket": bucket, "selected_n": selected_n, "invalid_n": selected_n - valid_n, "valid_n": valid_n, "top3_hits": hits, "top3_rate": pct(hits, valid_n), "races_represented": "", "selection_per_race_distribution": ""})
        write_csv("training_population_effect.csv", effect_rows, list(effect_rows[0]))
        write_csv("top5_external_selection_analysis.csv", external_rows, list(external_rows[0]))

        total_by_comp = {row["comparator"]: row for row in primary_total}
        current_rate = total_by_comp["CURRENT"]["top3_rate"]
        full_rate = total_by_comp["V5_FULL_FIELD_TRAINED"]["top3_rate"]
        top5_rate = total_by_comp["V5_TOP5_TRAINED"]["top3_rate"]
        pp_rate = total_by_comp["PP_ONLY_DETERMINISTIC"]["top3_rate"]
        brier = {(row["comparator"], row["scope"]): row["brier"] for row in calibration_rows}
        months_brier_deteriorated = sum(brier[("V5_FULL_FIELD_TRAINED", month)] > brier[("V5_TOP5_TRAINED", month)] for month in EVALUATION_MONTHS)
        calibration_guard = brier[("V5_FULL_FIELD_TRAINED", "POOLED")] <= brier[("V5_TOP5_TRAINED", "POOLED")] and months_brier_deteriorated <= len(EVALUATION_MONTHS) / 3
        full_current = bootstrap["comparisons"]["CURRENT_VS_FULL_FIELD"]
        full_pp = bootstrap["comparisons"]["PP_VS_FULL_FIELD"]
        positive_month_gain = {month: max(0, (monthly_lookup[("V5_FULL_FIELD_TRAINED", month)]["top3_hits"] - monthly_lookup[("V5_TOP5_TRAINED", month)]["top3_hits"])) for month in EVALUATION_MONTHS}
        total_positive_gain = sum(positive_month_gain.values())
        concentration = bool(total_positive_gain and max(positive_month_gain.values()) / total_positive_gain > 0.5)
        monthly_full_wins_current = sum(monthly_lookup[("V5_FULL_FIELD_TRAINED", month)]["top3_rate"] > monthly_lookup[("CURRENT", month)]["top3_rate"] for month in EVALUATION_MONTHS)
        rank1_lookup = {row["comparator"]: row for row in rank1_metrics}
        rank1_guard = rank1_lookup["V5_FULL_FIELD_TRAINED"]["top3_rate"] >= rank1_lookup["CURRENT"]["top3_rate"]
        candidate_conditions = {
            "primary_lift_vs_current_at_least_6pt": full_rate - current_rate >= 0.06,
            "monthly_current_wins_at_least_2_3": monthly_full_wins_current >= math.ceil(2 * len(EVALUATION_MONTHS) / 3),
            "paired_date_bootstrap_current_lower_gt_0": full_current["ci_95_lower"] > 0,
            "rank1_guard_not_materially_worse": rank1_guard,
            "calibration_guard": calibration_guard,
        }
        candidate_gate = {"candidate": "V5_FULL_FIELD_TRAINED", "conditions": candidate_conditions, "rank1_guard_operationalization": "common-denominator Full-field rank1 rate must be >= Current rank1 rate (pre-result fixed, zero-tolerance interpretation of 'not materially worse')", "status": "PASS" if all(candidate_conditions.values()) else "FAIL", "not_formal_accept": True}
        simplify = {"development_simplify_signal": full_pp["ci_95_lower"] <= 0, "complexity_not_justified": full_pp["ci_95_lower"] <= 0, "primary_simplicity_baseline": "PP_ONLY_DETERMINISTIC", "pp_vs_full_field": full_pp, "formal_simplify_decision": False}
        write_json("candidate_gate.json", candidate_gate)
        write_json("simplify_signal.json", simplify)

        # Final completion artifacts, then self-excluding index.
        conclusion = "TRAINING_POPULATION_EXPANSION_SUPPORTED" if candidate_gate["status"] == "PASS" else "NO_CLEAR_BENEFIT" if full_rate >= top5_rate else "NEGATIVE"
        summary = f"""# Full-field Redesign — Iteration 1 Completion\n\n`EXECUTION_ROLE = DEVELOPMENT_ONLY_NON_EVIDENTIAL`\n\n- Iteration: 1 (additional iteration consumed: `FALSE`)\n- Primary metric: `DAILY_GLOBAL_TOP_N_TOP3_RATE`\n- Secondary metric: `RACE_CONDITIONED_SAME_VOLUME`\n- Current global score: `adjusted_score` descending\n- PP tie-break: existing PRE `date → race_id → horse_number` order, expressed as date → canonical venue token order → race number → horse number\n- Common Rank1 races: {len(common_races)}\n\n| Comparator | Hits / valid N | Rate | Lift vs Current |\n|---|---:|---:|---:|\n""" + "\n".join(f"| {name} | {total_by_comp[name]['top3_hits']} / {total_by_comp[name]['valid_n']} | {total_by_comp[name]['top3_rate']:.4%} | {(total_by_comp[name]['top3_rate'] - current_rate):+.4%} |" for name in COMPARATORS) + f"""\n\n- Full-field minus Top5-trained: {full_rate - top5_rate:+.4%}\n- Full-field minus PP-only deterministic: {full_rate - pp_rate:+.4%}\n- Calibration guard: `{'PASS' if calibration_guard else 'FAIL'}`\n- Concentration flag: `{concentration}`\n- Development simplify signal: `{simplify['development_simplify_signal']}`\n- Candidate gate: `{candidate_gate['status']}`\n- Conclusion: `{conclusion}`\n\nNo Production or Formal advancement was performed.\n"""
        # The global-ranking authority above is the canonical wording.  Keep
        # this human-readable line aligned if this development runner is reused.
        summary = summary.replace("existing PRE `date → race_id → horse_number` order, expressed as date → canonical venue token order → race number → horse number", "existing PRE `date → race_id string → horse_number` order")
        (OUT / "summary.md").write_text(summary, encoding="utf-8")
        write_json("iteration_status.json", {"ITERATION_1_STATUS": "COMPLETE", "previous_status": "PARTIALLY_EXECUTED", "additional_iteration_consumed": False, "training_population_effect_only": True, "formal_evidence": False, "production_changed": False, "git_commit": "NONE", "git_push": "NONE"})
        hashes = {path.relative_to(OUT).as_posix(): {"sha256": sha256(path), "size": path.stat().st_size} for path in sorted(OUT.rglob("*")) if path.is_file() and path.name != "artifact_hashes.json"}
        write_json("artifact_hashes.json", {"self_hash_excluded": True, "artifacts": hashes})
        print(canonical({"ITERATION_1_STATUS": "COMPLETE", "output": str(OUT), "candidate_gate": candidate_gate["status"], "common_rank1_races": len(common_races)}))
    except Exception:
        if OUT.exists() and not (OUT / "artifact_hashes.json").exists():
            write_json("execution_stop.json", {"ITERATION_1_STATUS": "STOPPED", "error": str(sys.exc_info()[1]), "result_freeze_status": "see_pre_result_freeze_manifest_if_present"})
        raise


if __name__ == "__main__":
    main()
