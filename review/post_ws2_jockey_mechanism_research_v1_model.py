"""Implementation-only JOCKEY_CONTEXT rolling-OOS candidate.

Importing this module does not read Result data, fit a model, or write files.
The development entry point is fail-closed until separately authorized.
"""
from __future__ import annotations

import hashlib
import csv
import json
import math
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

from review import exp025_offset_pl_raw_history_v1 as exp025
from review import full_field_redesign_iter0_retry7 as iter0
from review import full_field_redesign_iteration2_v1 as iter2
from review import jockey_context_cross_snapshot_pit_audit_v1 as jockey_pit
from review import post_ws2_jockey_mechanism_research_v1_preonly as preonly
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


ROOT = Path(__file__).resolve().parents[1]
AUTHORITIES = {
    "base_prereg": (
        ROOT / "docs/KeibaAI_POST_WS2_JOCKEY_MECHANISM_RESEARCH_V1_Preregistration.md",
        "6b2c829d488d9dcc5030cfebba5655b094701d1880d6a5c40f76947d62671596",
    ),
    "amendment_1": (
        ROOT / "docs/KeibaAI_POST_WS2_JOCKEY_MECHANISM_RESEARCH_V1_Amendment1.md",
        "507f6c116863cdd17e687f966d65ad662b9bae4970c757d410dc90a603204175",
    ),
    "exp025_evaluation": (
        ROOT / "review/exp025_offset_pl_raw_history_v1.py",
        "2d37ace37a6581128f870bf633edf34e1b9e1bc928174ade9249a74fd652400c",
    ),
    "base_pl_reproduction": (
        ROOT / "reports/full_field_redesign_iteration2_recovery_inputs_v1/run_a_frozen.json",
        "48401e556f28f5625d85dfa315153a6dbba84e3114e3a9752e17b25e50f71c22",
    ),
}
SEED = 20261023
KAPPA = 10.0
EVAL_MONTHS = exp025.EVAL_MONTHS
CONSUMED_SECONDARY_START = "20260919"
CONSUMED_SECONDARY_END = "20261012"
FEATURE = "JOCKEY_TOP3_LIFT"
CANONICAL_OUTPUT = ROOT / "reports/post_ws2_jockey_mechanism_research_v1_development"
_RUN_TOKEN = object()


class Stop(RuntimeError):
    """Fail-closed implementation or authority error."""


def verify_authorities() -> dict[str, str]:
    actual = {}
    for name, (path, expected) in AUTHORITIES.items():
        if not path.is_file():
            raise Stop(f"STOP_AUTHORITY_MISSING:{name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise Stop(f"STOP_AUTHORITY_SHA_MISMATCH:{name}")
        actual[name] = digest
    return actual


def _strict_field_size(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer() or numeric < 2:
        return None
    return int(numeric)


def _strict_finish(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer() or numeric <= 0:
        return None
    return int(numeric)


def jockey_top3_lift(target: dict[str, Any], records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Raw log-ratio as of this target row's own date; no scaling or centering."""
    date = str(target["date"])
    jockey = str(target["current_jockey_normalized"])
    own_identity = tuple(target["horse_identity"])
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for record in records:
        if not jockey or str(record["historical_jockey_normalized"]) != jockey:
            continue
        if str(record["snapshot_date"]) > date or str(record["historical_race_date"]) >= date:
            continue
        identity = tuple(record["horse_identity"])
        if identity == own_identity:
            continue
        key = (*identity, str(record["historical_race_id"]))
        value = {
            "historical_race_date": str(record["historical_race_date"]),
            "historical_jockey_normalized": jockey,
            "field_size": record["field_size"],
            "finish": record["finish"],
            "completed_valid": bool(record["completed_valid"]),
        }
        if key in unique and unique[key] != value:
            raise Stop(f"STOP_CROSS_SNAPSHOT_RIDE_CONFLICT:{key}")
        unique[key] = value
    hits, expected, rides = 0, 0.0, 0
    for ride in unique.values():
        field_size = _strict_field_size(ride["field_size"])
        finish = _strict_finish(ride["finish"])
        if not ride["completed_valid"] or field_size is None or finish is None:
            continue
        rides += 1
        hits += int(finish <= 3)
        expected += min(3, field_size) / field_size
    return {
        FEATURE: math.log((hits + KAPPA) / (expected + KAPPA)),
        "prior_ride_count": rides,
        "H": hits,
        "E": expected,
        "cold_start": rides == 0,
    }


def development_source_dates() -> tuple[str, ...]:
    """The approved 62-date pool, never the consumed secondary snapshots."""
    dates = tuple(date for date in jockey_pit.EXPECTED_DATES if date <= preonly.EVALUATION_CUTOFF)
    if len(dates) != 62 or dates[-1] != "20260913":
        raise Stop("STOP_FROZEN_DEVELOPMENT_DATE_SCOPE")
    return dates


def load_development_pit_pool() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Reapply the approved PRE-only identity/history boundary to 62 dates only.

    This intentionally does not call preonly.target_and_snapshot_records(),
    which also loads the later consumed secondary dates for its coverage audit.
    """
    adapter = TargetBulkPredictionInputAdapterV1()
    early_authority = jockey_pit.early_authority()
    targets: list[dict[str, Any]] = []
    snapshots: dict[str, list[dict[str, Any]]] = {}
    for date in development_source_dates():
        de_path = exp025.source_path("DE", date)
        ds_path = exp025.source_path("DS", date)
        de = exp025.read_source(de_path, 33)
        ds = exp025.read_source(ds_path, 50)
        if not jockey_pit.source_authority(date, ds_path, early_authority)["match"]:
            raise Stop(f"STOP_DS_SOURCE_AUTHORITY_MISMATCH:{date}")
        by_lookup: dict[tuple[str, str, str], list[list[str]]] = defaultdict(list)
        for row in ds:
            by_lookup[(exp025.clean(row[16]), exp025.clean(row[44]), exp025.clean(row[46]))].append(row)
        snapshot: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for de_row in de:
            venue = exp025.clean(de_row[1])
            race_number = exp025.integer(de_row[2])
            horse_number = exp025.integer(de_row[3])
            if race_number is None or horse_number is None:
                raise Stop(f"STOP_TARGET_RACE_OR_HORSE_NUMBER:{date}")
            race_id = exp025.race_id(date, venue, race_number)
            if race_id in jockey_pit.EXCLUDED_RACES:
                continue
            name, sire, maternal = (
                exp025.clean(de_row[7]), exp025.clean(de_row[16]), exp025.clean(de_row[20])
            )
            identity = (name, sire, maternal)
            registration = exp025.clean(de_row[18])
            lookup_name = name
            if (
                date == exp025.KNOWN_20260906["date"]
                and race_id == exp025.KNOWN_20260906["race_id"]
                and horse_number == exp025.KNOWN_20260906["horse_number"]
            ):
                if name != exp025.KNOWN_20260906["de_name"] or registration != exp025.KNOWN_20260906["registration_id"]:
                    raise Stop("STOP_20260906_EXCEPTION_SCOPE")
                lookup_name = exp025.KNOWN_20260906["ds_name"]
            history_rows = by_lookup.get((lookup_name, sire, maternal))
            if not history_rows:
                raise Stop(f"STOP_HISTORY_IDENTITY_UNMATCHED:{date}:{race_id}:{horse_number}")
            targets.append({
                "date": date, "month": date[:6], "race_id": race_id,
                "horse_number": horse_number, "horse_name": name,
                "registration_id": registration,
                "current_jockey_normalized": jockey_pit.normalize_jockey(de_row[10]),
                "horse_identity": identity,
            })
            for history in adapter.valid_history_rows(history_rows):
                history_date = exp025.ds_date(history)
                if history_date >= date:
                    raise Stop(f"STOP_HISTORY_DATE_NOT_STRICTLY_BEFORE_SNAPSHOT:{date}:{history_date}")
                historical_race_id = adapter._race_id(
                    history_date, exp025.clean(history[4]), exp025.integer(history[6])
                )
                key = (*identity, historical_race_id)
                record = {
                    "snapshot_date": date, "horse_identity": identity,
                    "historical_race_id": historical_race_id,
                    "historical_race_date": history_date,
                    "historical_jockey_normalized": jockey_pit.normalize_jockey(history[19]),
                    "field_size": history[21],  # DS column 22, 1-based
                    "finish": history[23],  # DS column 24, 1-based
                    "completed_valid": True,  # adapter.valid_history_rows
                }
                if key in snapshot and snapshot[key] != record:
                    raise Stop(f"STOP_DUPLICATE_RIDE_WITHIN_SNAPSHOT:{date}:{key}")
                snapshot[key] = record
        snapshots[date] = list(snapshot.values())
    if len(targets) != 14870:
        raise Stop(f"STOP_FROZEN_DEVELOPMENT_TARGET_COUNT:{len(targets)}")
    return targets, snapshots


def feature_map_asof(
    targets: list[dict[str, Any]], snapshots: dict[str, list[dict[str, Any]]]
) -> dict[tuple[str, str, int], dict[str, Any]]:
    """Advance snapshots chronologically, including the same-day snapshot."""
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        by_date[str(target["date"])].append(target)
    known: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    by_jockey: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
    output: dict[tuple[str, str, int], dict[str, Any]] = {}
    for date in sorted(snapshots):
        for record in snapshots[date]:
            key = (*tuple(record["horse_identity"]), str(record["historical_race_id"]))
            if key in known:
                old = known[key]
                for field in ("historical_race_date", "historical_jockey_normalized", "field_size", "finish", "completed_valid"):
                    if old[field] != record[field]:
                        raise Stop(f"STOP_CROSS_SNAPSHOT_RIDE_CONFLICT:{key}")
                continue
            known[key] = record
            jockey = str(record["historical_jockey_normalized"])
            if jockey:
                by_jockey[jockey].add(key)
        for target in by_date[date]:
            key = (date, str(target["race_id"]), int(target["horse_number"]))
            if key in output:
                raise Stop(f"STOP_TARGET_IDENTITY_DUPLICATE:{key}")
            jockey = str(target["current_jockey_normalized"])
            output[key] = jockey_top3_lift(target, (known[k] for k in by_jockey.get(jockey, set())))
    if len(output) != len(targets):
        raise Stop("STOP_TARGET_FEATURE_COVERAGE")
    return output


def _partial_objective_one(
    groups: list[tuple[list[dict[str, Any]], list[int]]], beta: np.ndarray
) -> tuple[float, np.ndarray]:
    """EXP-025 ordered Top3 partial-PL loss/gradient, one raw feature."""
    if beta.shape != (1,) or not groups:
        raise Stop("STOP_OFFSET_OBJECTIVE_INPUT")
    loss, gradient = 0.0, np.zeros(1)
    for rows, winners in groups:
        feature = np.asarray([float(row[FEATURE]) for row in rows])
        utility = np.asarray([float(row["base_utility"]) for row in rows]) + feature * beta[0]
        remaining = list(range(len(rows)))
        for winner in winners:
            position = remaining.index(winner)
            values = utility[remaining]
            weights = np.exp(values - logsumexp(values))
            loss += -utility[winner] + logsumexp(values)
            gradient[0] += -feature[winner] + weights @ feature[remaining]
            remaining.pop(position)
    return loss / len(groups), gradient / len(groups)


def fit_jockey_offset(
    train: list[dict[str, Any]], base_scaler: Any, base_coef: np.ndarray
) -> tuple[float, dict[str, Any]]:
    groups = []
    for values, winner_indices in iter2.valid_pl_races(train)[0]:
        for row in values:
            row["base_utility"] = float(
                base_scaler.transform(np.asarray([row["features"]], dtype=float))[0, :19] @ base_coef
            )
            if not math.isfinite(float(row[FEATURE])):
                raise Stop("STOP_JOCKEY_FEATURE_NONFINITE")
        groups.append((values, winner_indices))
    if not groups:
        raise Stop("STOP_OFFSET_PL_NO_TRAINING_RACES")
    fit = minimize(
        lambda x: _partial_objective_one(groups, x)[0],
        np.zeros(1),
        jac=lambda x: _partial_objective_one(groups, x)[1],
        method="L-BFGS-B",
        options={"maxiter": 1000, "gtol": 1e-6},
    )
    if not fit.success or not np.all(np.isfinite(fit.x)) or not math.isfinite(float(fit.fun)):
        raise Stop(f"STOP_JOCKEY_OFFSET_NUMERICAL:{fit.message}")
    return float(fit.x[0]), {
        "optimizer": "L-BFGS-B", "initial_beta": 0.0, "maxiter": 1000,
        "gtol": 1e-6, "l2": 0.0, "training_races": len(groups),
        "iterations": int(fit.nit), "objective": float(fit.fun),
    }


def assert_exact_base_reproduction(
    train: list[dict[str, Any]], test: list[dict[str, Any]], frozen: dict[tuple[str, str, int], dict[str, Any]]
) -> tuple[Any, np.ndarray, dict[str, Any]]:
    keys = {(str(row["date"]), str(row["race_id"]), int(row["horse_number"])) for row in test}
    months = {str(row["date"])[:6] for row in test}
    frozen_fold_keys = {key for key in frozen if key[0][:6] in months}
    if len(months) != 1 or keys != frozen_fold_keys or len(keys) != len(test):
        raise Stop("STOP_BASE_PL_REPRODUCTION_IDENTITY")
    try:
        return exp025.reproduction(train, test, frozen)
    except exp025.Stop as error:
        raise Stop(str(error)) from error


def predict_fold(
    rows: list[dict[str, Any]], base_scaler: Any, base_coef: np.ndarray, beta_jockey: float
) -> None:
    for values in exp025._race_groups(rows).values():
        matrix = np.vstack([np.asarray(row["features"], dtype=float) for row in values])
        utility = base_scaler.transform(matrix)[:, :19] @ base_coef
        base, base_total = iter2.pl_top3(base_scaler.transform(matrix), base_coef)
        candidate, candidate_total = exp025._top3_from_utility(
            utility + np.asarray([float(row[FEATURE]) for row in values]) * beta_jockey
        )
        if abs(base_total - 3.0) > 1e-8 or abs(candidate_total - 3.0) > 1e-8:
            raise Stop("STOP_JOCKEY_TOP3_PROBABILITY_MASS")
        for row, base_p, candidate_p in zip(values, base, candidate):
            row["base_p_top3"] = float(base_p)
            row["jockey_p_top3"] = float(candidate_p)


def reject_consumed_secondary(rows: Iterable[dict[str, Any]]) -> None:
    for row in rows:
        date = str(row["date"])
        if CONSUMED_SECONDARY_START <= date <= CONSUMED_SECONDARY_END:
            raise Stop(f"STOP_CONSUMED_SECONDARY_DATE:{date}")
        if date > preonly.EVALUATION_CUTOFF:
            raise Stop(f"STOP_OUTSIDE_FROZEN_DEVELOPMENT_POPULATION:{date}")


def evaluate_frozen_gates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Future-only evaluation hook; never called at import or by implementation tests."""
    reject_consumed_secondary(rows)
    if {str(row["month"]) for row in rows} != set(EVAL_MONTHS):
        raise Stop("STOP_EVALUATION_MONTH_SCOPE")
    current = exp025.current_selection(rows)
    base, base_rank1 = exp025.selection(rows, "base_p_top3")
    candidate, candidate_rank1 = exp025.selection(rows, "jockey_p_top3")
    by_race_base, by_race_candidate = exp025._race_groups(base), exp025._race_groups(candidate)
    race_delta = []
    for key in sorted(set(by_race_base) & set(by_race_candidate)):
        base_metric = exp025.metric(by_race_base[key])
        candidate_metric = exp025.metric(by_race_candidate[key])
        race_delta.append({
            "date": key[0], "race_id": key[1],
            "race_top3_delta": candidate_metric["top3_hits"] - base_metric["top3_hits"],
        })
    base_daily, base_month = exp025._full_metric_by_month(rows, lambda subset: exp025.selection(subset, "base_p_top3")[0])
    candidate_daily, candidate_month = exp025._full_metric_by_month(rows, lambda subset: exp025.selection(subset, "jockey_p_top3")[0])
    paired_rank = [(left, right) for left, right in zip(base_rank1, candidate_rank1) if left["valid_result"] and right["valid_result"]]
    rank_base = exp025.metric([pair[0] for pair in paired_rank])
    rank_candidate = exp025.metric([pair[1] for pair in paired_rank])
    base_brier = exp025.brier(rows, "base_p_top3")
    candidate_brier = exp025.brier(rows, "jockey_p_top3")
    worse_brier = sum(
        exp025.brier([row for row in rows if row["month"] == month], "jockey_p_top3")
        > exp025.brier([row for row in rows if row["month"] == month], "base_p_top3")
        for month in EVAL_MONTHS
    )
    current_global = exp025.global_selection(rows, "adjusted_score")
    candidate_global = exp025.global_selection(rows, "jockey_p_top3")
    current_global_daily = {date: exp025.metric(value) for date, value in current_global.items()}
    candidate_global_daily = {date: exp025.metric(value) for date, value in candidate_global.items()}
    global_current = exp025.metric([row for values in current_global.values() for row in values])
    global_candidate = exp025.metric([row for values in candidate_global.values() for row in values])
    global_month_current = {month: exp025.metric([row for date, values in current_global.items() if date.startswith(month) for row in values]) for month in EVAL_MONTHS}
    global_month_candidate = {month: exp025.metric([row for date, values in candidate_global.items() if date.startswith(month) for row in values]) for month in EVAL_MONTHS}
    global_rank_current = [sorted(values, key=lambda row: (-float(row["adjusted_score"]), int(row["horse_number"])))[0] for values in exp025._race_groups(rows).values()]
    global_rank_candidate = [sorted(values, key=lambda row: (-float(row["jockey_p_top3"]), int(row["horse_number"])))[0] for values in exp025._race_groups(rows).values()]
    global_paired = [(left, right) for left, right in zip(global_rank_current, global_rank_candidate) if left["valid_result"] and right["valid_result"]]
    global_rank_current_metric = exp025.metric([pair[0] for pair in global_paired])
    global_rank_candidate_metric = exp025.metric([pair[1] for pair in global_paired])
    race_bootstrap = exp025.bootstrap_race_delta(race_delta, seed=SEED)
    global_bootstrap = exp025.bootstrap_rate(current_global_daily, candidate_global_daily, seed=SEED)
    calibration_guard = candidate_brier <= base_brier and worse_brier <= 2
    gates = {
        "GATE_1": race_bootstrap["ci_lower_95"] > 0.0,
        "GATE_2": sum(candidate_month[month]["top3_rate"] >= base_month[month]["top3_rate"] for month in EVAL_MONTHS) >= 5,
        "GATE_3": rank_candidate["top3_rate"] >= rank_base["top3_rate"] - 0.01,
        "GATE_4": calibration_guard,
        "GATE_5": all((
            global_candidate["top3_rate"] - global_current["top3_rate"] >= 0.06,
            sum(global_month_candidate[month]["top3_rate"] > global_month_current[month]["top3_rate"] for month in EVAL_MONTHS) >= 5,
            global_bootstrap["ci_lower_95"] > 0.0,
            global_rank_candidate_metric["top3_rate"] >= global_rank_current_metric["top3_rate"] - 0.01,
            calibration_guard,
        )),
    }
    return {
        "gates": gates, "development_gate": all(gates.values()),
        "current": exp025.metric(current), "base": exp025.metric(base),
        "candidate": exp025.metric(candidate), "rank1_base": rank_base,
        "rank1_candidate": rank_candidate, "brier_base": base_brier,
        "brier_candidate": candidate_brier, "brier_months_worse": worse_brier,
        "global_current": global_current, "global_candidate": global_candidate,
        "race_bootstrap": race_bootstrap, "global_bootstrap": global_bootstrap,
        "base_daily": base_daily, "candidate_daily": candidate_daily,
        "selected_base": base, "selected_candidate": candidate,
    }


def predeclared_diagnostics(
    rows: list[dict[str, Any]], evaluation: dict[str, Any], fold_audit: list[dict[str, Any]]
) -> dict[str, Any]:
    """Only the three preregistered, non-gating diagnostic descriptions."""
    counts = sorted(int(row["prior_ride_count"]) for row in rows)
    if not counts:
        raise Stop("STOP_DIAGNOSTIC_POPULATION_EMPTY")
    lower = counts[(len(counts) - 1) // 3]
    upper = counts[(2 * (len(counts) - 1)) // 3]

    def tercile(row: dict[str, Any]) -> str:
        count = int(row["prior_ride_count"])
        if count <= lower:
            return "LOW"
        if count <= upper:
            return "MIDDLE"
        return "HIGH"

    by_tercile = {}
    for label in ("LOW", "MIDDLE", "HIGH"):
        base = exp025.metric([row for row in evaluation["selected_base"] if tercile(row) == label])
        candidate = exp025.metric([row for row in evaluation["selected_candidate"] if tercile(row) == label])
        by_tercile[label] = {
            "base": base, "candidate": candidate,
            "candidate_minus_base_rate": (
                candidate["top3_rate"] - base["top3_rate"]
                if candidate["top3_rate"] is not None and base["top3_rate"] is not None else None
            ),
        }
    return {
        "cold_start_rows": sum(int(row["prior_ride_count"]) == 0 for row in rows),
        "cold_start_row_rate": sum(int(row["prior_ride_count"]) == 0 for row in rows) / len(rows),
        "prior_ride_count_tercile_cutoffs": {"lower": lower, "upper": upper},
        "incremental_result_by_prior_ride_count_tercile": by_tercile,
        "beta_jockey_sign_by_fold": [
            {"fold_id": audit["fold"]["fold_id"], "sign": audit["beta_sign"]}
            for audit in fold_audit
        ],
        "gating_role": False,
    }


def prepare_development_inputs() -> dict[str, Any]:
    """Authority and PRE/PIT identity checks, without a Result JOIN."""
    authority = verify_authorities()
    targets, snapshots = load_development_pit_pool()
    features = feature_map_asof(targets, snapshots)
    pre_rows = iter0.load_pre_rows()
    pre_keys = {
        (str(row["date"]), str(row["race_id"]), int(row["horse_number"]))
        for row in pre_rows
    }
    if len(pre_rows) != 14870 or pre_keys != set(features):
        raise Stop("STOP_FROZEN_PRE_FEATURE_IDENTITY_MISMATCH")
    frozen_keys = set(exp025.frozen_rows())
    if {key for key in pre_keys if key[0][:6] in EVAL_MONTHS} != frozen_keys:
        raise Stop("STOP_BASE_PL_FROZEN_POPULATION_MISMATCH")
    return {"authority": authority, "targets": targets, "features": features}


def run_development(
    *, human_execution_approved: bool = False, prepared_inputs: dict[str, Any] | None = None,
    _wrapper_token: object | None = None,
) -> dict[str, Any]:
    """Future execution entry point. Not called in this implementation stage."""
    if human_execution_approved is not True:
        raise Stop("STOP_HUMAN_EXECUTION_APPROVAL_REQUIRED")
    if _wrapper_token is not _RUN_TOKEN:
        raise Stop("STOP_USE_ATOMIC_EXECUTION_WRAPPER")
    verify_authorities()
    prepared = prepared_inputs if prepared_inputs is not None else prepare_development_inputs()
    targets, features = prepared["targets"], prepared["features"]
    rows = iter2.load_rows()  # Result JOIN: forbidden until separate Human execution approval.
    reject_consumed_secondary(rows)
    if len(rows) != 14870 or {str(row["date"]) for row in rows} != {str(row["date"]) for row in targets if row["date"] <= preonly.EVALUATION_CUTOFF}:
        raise Stop("STOP_FROZEN_DEVELOPMENT_POPULATION")
    for row in rows:
        key = (str(row["date"]), str(row["race_id"]), int(row["horse_number"]))
        if key not in features:
            raise Stop(f"STOP_JOCKEY_FEATURE_MISSING:{key}")
        row.update(features[key])
    frozen = exp025.frozen_rows()
    expected_test = {(str(row["date"]), str(row["race_id"]), int(row["horse_number"])) for row in rows if row["month"] in EVAL_MONTHS}
    if expected_test != set(frozen):
        raise Stop("STOP_BASE_PL_FROZEN_POPULATION_MISMATCH")
    fold_audit, all_eval = [], []
    for fold in iter0.folds(rows):
        try:
            month = fold["evaluation_months"][0]
            train = [row for row in rows if row["month"] in fold["train_months"] and row["valid_result"]]
            test = [dict(row) for row in rows if row["month"] == month]
            base_scaler, base_coef, reproduction = assert_exact_base_reproduction(train, test, frozen)
            beta, fit_audit = fit_jockey_offset(train, base_scaler, base_coef)
            predict_fold(test, base_scaler, base_coef, beta)
            all_eval.extend(test)
            fold_audit.append({"fold": fold, "base_reproduction": reproduction, "beta_jockey": beta, "beta_sign": int(np.sign(beta)), "fit": fit_audit})
        except Exception as error:
            raise Stop(f"STOP_DEVELOPMENT_FOLD:{fold['fold_id']}:{error}") from error
    evaluation = evaluate_frozen_gates(all_eval)
    # No full-data refit, final-model serialization, prospective path, or write.
    return {
        "fold_audit": fold_audit,
        "evaluation": evaluation,
        "evaluation_rows": all_eval,
        "predeclared_diagnostics": predeclared_diagnostics(all_eval, evaluation, fold_audit),
    }


def _json_write(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _fold_report(
    fold_audit: list[dict[str, Any]], rows: list[dict[str, Any]], targets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    target_dates = sorted({str(row["date"]) for row in targets})
    report = []
    for item in fold_audit:
        fold = item["fold"]
        train_months = set(fold["train_months"])
        test_months = set(fold["evaluation_months"])
        train_dates = [date for date in target_dates if date[:6] in train_months]
        test_rows = [row for row in rows if str(row["month"]) in test_months]
        if not train_dates or not test_rows:
            raise Stop(f"STOP_FOLD_REPORT_SCOPE:{fold['fold_id']}")
        test_dates = sorted({str(row["date"]) for row in test_rows})
        report.append({
            "fold_id": fold["fold_id"],
            "train_months": fold["train_months"], "test_months": fold["evaluation_months"],
            "train_date_first": train_dates[0], "train_date_last": train_dates[-1],
            "test_date_first": test_dates[0], "test_date_last": test_dates[-1],
            "train_race_count": item["fit"]["training_races"],
            "train_valid_row_count": fold["train_rows"],
            "test_race_count": len({(row["date"], row["race_id"]) for row in test_rows}),
            "test_valid_row_count": sum(bool(row["valid_result"]) for row in test_rows),
            "base_pl_reproduction_max_abs_difference": item["base_reproduction"]["max_abs_probability_difference"],
            "beta_jockey": item["beta_jockey"],
            "beta_jockey_sign": item["beta_sign"],
            "optimizer_success": True,
            "optimizer": item["fit"],
        })
    if len(report) != len(EVAL_MONTHS):
        raise Stop("STOP_FOLD_REPORT_COUNT")
    return report


def _gate_report(rows: list[dict[str, Any]], evaluation: dict[str, Any]) -> dict[str, Any]:
    """Persist components of the already-computed frozen gates, not new gates."""
    base_daily, base_month = exp025._full_metric_by_month(
        rows, lambda subset: exp025.selection(subset, "base_p_top3")[0]
    )
    candidate_daily, candidate_month = exp025._full_metric_by_month(
        rows, lambda subset: exp025.selection(subset, "jockey_p_top3")[0]
    )
    monthly = [
        {
            "month": month, "base": base_month[month], "candidate": candidate_month[month],
            "candidate_ge_base": candidate_month[month]["top3_rate"] >= base_month[month]["top3_rate"],
        }
        for month in EVAL_MONTHS
    ]
    brier_monthly = [
        {
            "month": month,
            "base": exp025.brier([row for row in rows if row["month"] == month], "base_p_top3"),
            "candidate": exp025.brier([row for row in rows if row["month"] == month], "jockey_p_top3"),
        }
        for month in EVAL_MONTHS
    ]
    current_global = exp025.global_selection(rows, "adjusted_score")
    candidate_global = exp025.global_selection(rows, "jockey_p_top3")
    current_global_metric = exp025.metric([row for values in current_global.values() for row in values])
    candidate_global_metric = exp025.metric([row for values in candidate_global.values() for row in values])
    current_month = {
        month: exp025.metric([row for date, values in current_global.items() if date.startswith(month) for row in values])
        for month in EVAL_MONTHS
    }
    candidate_month_global = {
        month: exp025.metric([row for date, values in candidate_global.items() if date.startswith(month) for row in values])
        for month in EVAL_MONTHS
    }
    current_rank1 = [
        sorted(values, key=lambda row: (-float(row["adjusted_score"]), int(row["horse_number"])))[0]
        for values in exp025._race_groups(rows).values()
    ]
    candidate_rank1 = [
        sorted(values, key=lambda row: (-float(row["jockey_p_top3"]), int(row["horse_number"])))[0]
        for values in exp025._race_groups(rows).values()
    ]
    paired_global = [
        (left, right) for left, right in zip(current_rank1, candidate_rank1)
        if left["valid_result"] and right["valid_result"]
    ]
    current_rank_metric = exp025.metric([pair[0] for pair in paired_global])
    candidate_rank_metric = exp025.metric([pair[1] for pair in paired_global])
    components = {
        "rate_at_least_current_plus_6pp": candidate_global_metric["top3_rate"] - current_global_metric["top3_rate"] >= 0.06,
        "above_current_in_at_least_5_months": sum(
            candidate_month_global[month]["top3_rate"] > current_month[month]["top3_rate"]
            for month in EVAL_MONTHS
        ) >= 5,
        "global_bootstrap_lower_above_zero": evaluation["global_bootstrap"]["ci_lower_95"] > 0.0,
        "paired_rank1_guard": candidate_rank_metric["top3_rate"] >= current_rank_metric["top3_rate"] - 0.01,
        "calibration_guard": evaluation["brier_candidate"] <= evaluation["brier_base"] and evaluation["brier_months_worse"] <= 2,
    }
    if (sum(item["candidate_ge_base"] for item in monthly) >= 5) != evaluation["gates"]["GATE_2"]:
        raise Stop("STOP_GATE_REPORT_G2_MISMATCH")
    if all(components.values()) != evaluation["gates"]["GATE_5"]:
        raise Stop("STOP_GATE_REPORT_G5_MISMATCH")
    if len(base_daily) != len(candidate_daily):
        raise Stop("STOP_GATE_REPORT_DATE_SCOPE")
    return {
        "experiment": "POST_WS2_JOCKEY_MECHANISM_RESEARCH_V1",
        "primary_same_volume": {"base": evaluation["base"], "candidate": evaluation["candidate"]},
        "G1": {"pass": evaluation["gates"]["GATE_1"], "bootstrap": evaluation["race_bootstrap"]},
        "G2": {"pass": evaluation["gates"]["GATE_2"], "monthly": monthly},
        "G3": {"pass": evaluation["gates"]["GATE_3"], "base_rank1": evaluation["rank1_base"], "candidate_rank1": evaluation["rank1_candidate"]},
        "G4": {"pass": evaluation["gates"]["GATE_4"], "base_brier": evaluation["brier_base"], "candidate_brier": evaluation["brier_candidate"], "monthly": brier_monthly, "months_worse": evaluation["brier_months_worse"]},
        "G5": {"pass": evaluation["gates"]["GATE_5"], "components": components, "current_global": current_global_metric, "candidate_global": candidate_global_metric, "monthly_current": current_month, "monthly_candidate": candidate_month_global, "global_bootstrap": evaluation["global_bootstrap"], "paired_rank1_current": current_rank_metric, "paired_rank1_candidate": candidate_rank_metric},
        "development_gate": "PASS" if evaluation["development_gate"] else "FAIL",
    }


def _write_execution_artifacts(
    staging: Path, prepared: dict[str, Any], result: dict[str, Any]
) -> dict[str, str]:
    rows = sorted(
        result["evaluation_rows"],
        key=lambda row: (str(row["date"]), str(row["race_id"]), int(row["horse_number"])),
    )
    authority = {
        name: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": prepared["authority"][name]}
        for name, (path, _expected) in AUTHORITIES.items()
    }
    _json_write(staging / "authority_verification.json", {
        "experiment": "POST_WS2_JOCKEY_MECHANISM_RESEARCH_V1",
        "execution_count": 1, "human_execution_approved": True,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "authorities": authority,
        "implementation": {
            "path": str(Path(__file__).relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "bootstrap_seed": SEED,
        "final_model_trained": False,
        "prospective_model_created": False,
    })
    _json_write(
        staging / "fold_audit.json",
        _fold_report(result["fold_audit"], rows, prepared["targets"]),
    )
    fields = [
        "date", "race_id", "horse_number", "horse_name", "month", "current_buy",
        "valid_result", "actual_top3", "base_p_top3", "jockey_p_top3",
        FEATURE, "prior_ride_count",
    ]
    with (staging / "evaluation_rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    _json_write(staging / "gate_evaluation.json", _gate_report(rows, result["evaluation"]))
    _json_write(staging / "predeclared_diagnostics.json", result["predeclared_diagnostics"])
    artifacts = (
        "authority_verification.json", "fold_audit.json", "evaluation_rows.csv",
        "gate_evaluation.json", "predeclared_diagnostics.json",
    )
    hashes = {name: hashlib.sha256((staging / name).read_bytes()).hexdigest() for name in artifacts}
    _json_write(staging / "artifact_hashes.json", {
        "self_hash_excluded": True,
        "artifacts": {
            name: {"sha256": hashes[name], "size": (staging / name).stat().st_size}
            for name in artifacts
        },
    })
    return hashes


def run(
    output: Path | None = None, *, human_execution_approved: bool = False
) -> dict[str, Any]:
    """Single authorized Development execution with adjacent atomic output.

    This function is NOT invoked during implementation or tests on real data.
    """
    if human_execution_approved is not True:
        raise Stop("STOP_HUMAN_EXECUTION_NOT_APPROVED")
    canonical = CANONICAL_OUTPUT
    destination = Path(output) if output is not None else canonical
    if destination.resolve() != canonical.resolve():
        raise Stop("STOP_NONCANONICAL_OUTPUT")
    if destination.exists():
        raise Stop("STOP_OUTPUT_EXISTS")
    prepared = prepare_development_inputs()
    if destination.exists():
        raise Stop("STOP_OUTPUT_EXISTS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging_", dir=destination.parent))
    try:
        result = run_development(
            human_execution_approved=True, prepared_inputs=prepared, _wrapper_token=_RUN_TOKEN
        )
        hashes = _write_execution_artifacts(staging, prepared, result)
        if destination.exists():
            raise Stop("STOP_OUTPUT_EXISTS")
        staging.rename(destination)
        return {
            "STATUS": "COMPLETE", "EXPERIMENT": "POST_WS2_JOCKEY_MECHANISM_RESEARCH_V1",
            "EXECUTION_COUNT": 1, "output": str(destination),
            "artifact_hashes": hashes, "FINAL_MODEL_TRAINED": False,
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)
