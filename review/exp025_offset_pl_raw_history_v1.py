"""EXP-025: frozen Offset PL V2 Raw History development runner.

This is deliberately development-only.  It is a closed implementation of the
EXP-025 preregistration: seven raw-history covariates are learned as an offset
to fold-local Iteration-2 Plackett--Luce utilities.  It has no production
imports or write paths outside its own report root.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review import full_field_redesign_iteration2_v1 as iter2
from review import full_field_redesign_iter0_retry7 as iter0
from review.target_bulk_prediction_input_adapter_v1 import COURSE_KEYS


EXPERIMENT_ID = "EXP-025"
PREREG = ROOT / "docs" / "KeibaAI_Iteration3_Offset_PL_Raw_History_V1_Preregistration.md"
PREREG_SHA = "88e8a9dca64a0c520f79880e3eb73d5e4bc318fc0052e28b4a543de4cac79a29"
BASELINE_HEAD = "7117bb28231436ecef786345bf48cf98cd6ff588"
PL_FORWARD_MODEL = ROOT / "models" / "pl_forward_shadow_v1" / "pl_forward_shadow_v1_model.json"
PL_FORWARD_SHA = "418fc9b4cefe1757f79dfc22a7d49b7c1592b91084cca97f88f55bb1389b0585"
ITER2_FROZEN = ROOT / "reports" / "full_field_redesign_iteration2_recovery_inputs_v1" / "run_a_frozen.json"
OUT = ROOT / "reports" / "exp025_offset_pl_raw_history_v1"
EVAL_MONTHS = ("202603", "202604", "202605", "202606", "202607", "202608", "202609")
CONTINUOUS = (0, 1, 2, 3, 5)
FEATURES = (
    "RECENT_FINISH_PCT", "RECENT_MARGIN", "RECENT_CORNER4_PCT",
    "DISTANCE_GAP", "SURFACE_SWITCH", "LOG_REST", "HISTORY_DEPTH",
)
KNOWN_20260906 = {
    "date": "20260906", "race_id": "race_20260906_hanshin_11R",
    "horse_number": 8, "de_name": "ファストネットワーク", "ds_name": "ファストネットワー",
    "registration_id": "20190007",
}
EXCLUDED_20260823_RACE = "race_20260823_niigata_7R"


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def dump(root: Path, name: str, value: Any) -> Path:
    path = root / name
    path.write_text(canonical(value), encoding="utf-8")
    return path


def csvout(root: Path, name: str, rows: list[dict[str, Any]], fields: list[str]) -> Path:
    path = root / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def clean(value: Any) -> str:
    return str(value or "").strip().replace(" ", "").replace("　", "")


def number(value: Any) -> float | None:
    text = str(value or "").strip().replace("+", "")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def integer(value: Any) -> int | None:
    parsed = number(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def ds_date(row: list[str]) -> str:
    try:
        return f"{2000 + int(row[0].strip()):04d}{int(row[1].strip()):02d}{int(row[2].strip()):02d}"
    except (IndexError, ValueError) as error:
        raise Stop("STOP_RAW_HISTORY_DS_DATE_INVALID") from error


def source_path(kind: str, date: str) -> Path:
    suffix = date[2:]
    return ROOT / "data" / "raw" / "prediction_input" / f"{kind}{suffix}{'v2' if date == '20260418' else ''}.CSV"


def read_source(path: Path, width: int) -> list[list[str]]:
    if not path.is_file():
        raise Stop(f"STOP_RAW_HISTORY_SOURCE_MISSING:{path}")
    with path.open(encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows or any(len(row) != width for row in rows):
        raise Stop(f"STOP_RAW_HISTORY_SOURCE_SCHEMA:{path.name}")
    return rows


def race_id(date: str, venue: str, race_number: int) -> str:
    if venue not in COURSE_KEYS:
        raise Stop(f"STOP_RAW_HISTORY_VENUE:{venue}")
    return f"race_{date}_{COURSE_KEYS[venue]}_{race_number}R"


def valid_history(row: list[str], target_date: str) -> bool:
    finish, field = integer(row[23]), integer(row[21])
    return ds_date(row) < target_date and row[25].strip() in {"", "0"} and finish is not None and finish >= 1 and field is not None and field >= 2


def final_corner(row: list[str]) -> int | None:
    values = [integer(row[index]) for index in range(31, 35)]
    usable = [value for value in values if value is not None and value >= 1]
    return usable[-1] if usable else None


def raw_feature_values(history: list[list[str]], *, target_date: str, target_distance: int, target_surface: str) -> tuple[list[float | None], dict[str, Any]]:
    """Compute exactly the seven preregistered V1 features without labels."""
    ordered = sorted(history, key=ds_date, reverse=True)
    if any(ds_date(row) >= target_date for row in ordered):
        raise Stop("STOP_RAW_HISTORY_ASOF_VIOLATION")
    valid = [row for row in ordered if valid_history(row, target_date)][:3]
    finish_pct = []
    margins = []
    corners = []
    distances = []
    for row in valid:
        finish, field = integer(row[23]), integer(row[21])
        assert finish is not None and field is not None
        finish_pct.append((finish - 1) / (field - 1))
        margin = number(row[26])
        if margin is not None:
            margins.append(min(3.0, max(0.0, margin)))
        corner = final_corner(row)
        if corner is not None:
            corners.append((corner - 1) / (field - 1))
        distance = integer(row[14])
        if distance is not None:
            distances.append(abs(target_distance - distance) / 1000.0)
    recent = valid[0] if valid else None
    if recent is None:
        surface_switch: float | None = None
    else:
        surface_switch = float(clean(recent[12]) != clean(target_surface))
    if ordered:
        target = datetime.strptime(target_date, "%Y%m%d").date()
        prior = datetime.strptime(ds_date(ordered[0]), "%Y%m%d").date()
        rest = math.log1p(min(365, max(0, (target - prior).days)))
    else:
        rest = None
    values: list[float | None] = [
        float(np.mean(finish_pct)) if finish_pct else None,
        float(np.mean(margins)) if margins else None,
        float(np.mean(corners)) if corners else None,
        float(min(distances)) if distances else None,
        surface_switch,
        rest,
        len(valid) / 3.0,
    ]
    return values, {
        "valid_history_count": len(valid), "all_history_count": len(ordered),
        "latest_history_date": ds_date(ordered[0]) if ordered else None,
        "feature_missing": [FEATURES[index] for index, value in enumerate(values) if value is None],
    }


def authority_check() -> dict[str, Any]:
    if sha(PREREG) != PREREG_SHA:
        raise Stop("STOP_PREREGISTRATION_SHA_MISMATCH")
    if sha(PL_FORWARD_MODEL) != PL_FORWARD_SHA:
        raise Stop("STOP_PL_FORWARD_MODEL_SHA_MISMATCH")
    import subprocess
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", BASELINE_HEAD, "HEAD"], cwd=ROOT).returncode == 0
    if not ancestor:
        raise Stop("STOP_APPROVED_BASELINE_NOT_ANCESTOR")
    return {"preregistration_sha256": PREREG_SHA, "baseline_head": BASELINE_HEAD, "current_head": head, "baseline_is_ancestor": True, "pl_forward_model_sha256": PL_FORWARD_SHA}


def frozen_rows() -> dict[tuple[str, str, int], dict[str, Any]]:
    value = json.loads(ITER2_FROZEN.read_text(encoding="utf-8"))
    rows = value.get("rows")
    if not isinstance(rows, list) or not rows:
        raise Stop("STOP_ITER2_FROZEN_ROWS_MISSING")
    result = {(str(row["date"]), str(row["race_id"]), int(row["horse_number"])): row for row in rows}
    if len(result) != len(rows):
        raise Stop("STOP_ITER2_FROZEN_IDENTITY_DUPLICATE")
    return result


def history_by_target(rows: list[dict[str, Any]]) -> tuple[dict[tuple[str, str, int], tuple[list[list[str]], list[float | None], dict[str, Any]]], dict[str, Any]]:
    """Source-only identity/PIT materialization for already frozen PRE rows."""
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[str(row["date"])].append(row)
    result: dict[tuple[str, str, int], tuple[list[list[str]], list[float | None], dict[str, Any]]] = {}
    inventory = []
    identity_audit = {"one_to_one_races": 0, "dam_corroborated_rows": 0, "dam_missing_permitted_rows": 0, "exception_20260906_rows": 0, "excluded_20260823_rows": 0}
    for date, target_rows in sorted(by_date.items()):
        de_path, dg_path, ds_path = source_path("DE", date), source_path("DG", date), source_path("DS", date)
        de, dg, ds = read_source(de_path, 33), read_source(dg_path, 11), read_source(ds_path, 50)
        inventory.extend({"date": date, "kind": kind, "path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "rows": len(raw), "width": width, "encoding": "cp932"} for kind, path, raw, width in (("DE", de_path, de, 33), ("DG", dg_path, dg, 11), ("DS", ds_path, ds, 50)))
        dg_map = {(clean(row[3]), integer(row[4])): row for row in dg}
        de_map = {}
        for row in de:
            venue, no, horse = clean(row[1]), integer(row[2]), integer(row[3])
            if no is None or horse is None:
                raise Stop("STOP_RAW_HISTORY_DE_RACE_OR_HORSE_INVALID")
            de_map[(race_id(date, venue, no), horse)] = row
        ds_by_identity: dict[tuple[str, str, str], list[list[str]]] = defaultdict(list)
        for row in ds:
            ds_by_identity[(clean(row[16]), clean(row[44]), clean(row[46]))].append(row)
        race_keys: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        for target in target_rows:
            key = (date, str(target["race_id"]), int(target["horse_number"]))
            if key[1] == EXCLUDED_20260823_RACE:
                identity_audit["excluded_20260823_rows"] += 1
                continue
            de_row = de_map.get((key[1], key[2]))
            if de_row is None or clean(de_row[7]) != clean(target.get("horse_name")):
                raise Stop(f"STOP_RAW_HISTORY_DE_PRE_IDENTITY:{key}")
            name, sire, dam, maternal = clean(de_row[7]), clean(de_row[16]), clean(de_row[17]), clean(de_row[20])
            lookup_name = name
            if date == KNOWN_20260906["date"] and key[1] == KNOWN_20260906["race_id"] and key[2] == KNOWN_20260906["horse_number"] and name == KNOWN_20260906["de_name"]:
                if clean(de_row[18]) != KNOWN_20260906["registration_id"]:
                    raise Stop("STOP_RAW_HISTORY_20260906_EXCEPTION_SCOPE")
                lookup_name = KNOWN_20260906["ds_name"]
                identity_audit["exception_20260906_rows"] += 1
            ident = (lookup_name, sire, maternal)
            race_keys[key[1]].add((name, sire, maternal))
            history = ds_by_identity.get(ident)
            if not history:
                raise Stop(f"STOP_RAW_HISTORY_IDENTITY_UNMATCHED:{key}")
            if any(ds_date(row) >= date for row in history):
                raise Stop(f"STOP_RAW_HISTORY_ASOF_VIOLATION:{key}")
            for past in history:
                past_dam = clean(past[45])
                if dam and past_dam:
                    if dam != past_dam:
                        raise Stop(f"STOP_RAW_HISTORY_DAM_CORROBORATION:{key}")
                    identity_audit["dam_corroborated_rows"] += 1
                else:
                    identity_audit["dam_missing_permitted_rows"] += 1
            venue, no = clean(de_row[1]), integer(de_row[2])
            dg_row = dg_map.get((venue, no))
            if dg_row is None:
                raise Stop(f"STOP_RAW_HISTORY_DG_DE_RACE:{key}")
            distance = integer(dg_row[8])
            if distance is None or clean(dg_row[7]) not in {"芝", "ダ", "ダート"}:
                raise Stop(f"STOP_RAW_HISTORY_RACE_CONTEXT:{key}")
            raw, audit = raw_feature_values(history, target_date=date, target_distance=distance, target_surface=clean(dg_row[7]))
            result[key] = (history, raw, {**audit, "identity": {"name": name, "sire": sire, "maternal_grandsire": maternal, "dam": dam}})
        for rid, keys in race_keys.items():
            count = sum(1 for target in target_rows if target["race_id"] == rid and target["race_id"] != EXCLUDED_20260823_RACE)
            if len(keys) != count:
                raise Stop(f"STOP_RAW_HISTORY_IDENTITY_NOT_ONE_TO_ONE:{date}:{rid}")
            identity_audit["one_to_one_races"] += 1
    if len(result) != len(rows):
        raise Stop(f"STOP_RAW_HISTORY_TARGET_COVERAGE:{len(result)}/{len(rows)}")
    return result, {"inventory": inventory, "identity_audit": identity_audit}


def scale_fit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    means, scales = [], []
    for index in CONTINUOUS:
        values = [float(row["raw_features"][index]) for row in rows if row["raw_features"][index] is not None]
        if not values:
            raise Stop(f"STOP_RAW_HISTORY_SCALER_EMPTY:{FEATURES[index]}")
        mean, scale = float(np.mean(values)), float(np.std(values))
        if not math.isfinite(mean) or not math.isfinite(scale) or scale == 0.0:
            raise Stop(f"STOP_RAW_HISTORY_SCALER_INVALID:{FEATURES[index]}")
        means.append(mean); scales.append(scale)
    return {"continuous_indices": list(CONTINUOUS), "mean": means, "scale": scales, "fit_rows": len(rows)}


def scale_transform(raw: list[float | None], scaler: dict[str, Any]) -> np.ndarray:
    value = np.zeros(7, dtype=float)
    by_index = {index: (float(mean), float(scale)) for index, mean, scale in zip(scaler["continuous_indices"], scaler["mean"], scaler["scale"])}
    for index in CONTINUOUS:
        observed = raw[index]
        value[index] = 0.0 if observed is None else (float(observed) - by_index[index][0]) / by_index[index][1]
    if raw[4] is None:
        raise Stop("STOP_SURFACE_SWITCH_MISSING_POLICY_UNSPECIFIED")
    value[4] = float(raw[4])
    value[6] = float(raw[6])
    if not np.all(np.isfinite(value)):
        raise Stop("STOP_RAW_HISTORY_TRANSFORM_NONFINITE")
    return value


def _race_groups(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["date"]), str(row["race_id"]))].append(row)
    return groups


def _partial_objective(groups: list[tuple[list[dict[str, Any]], list[int]]], gamma: np.ndarray) -> tuple[float, np.ndarray]:
    loss, gradient = 0.0, np.zeros(7)
    for rows, winners in groups:
        utility = np.asarray([row["base_utility"] for row in rows]) + np.vstack([row["raw_z"] for row in rows]) @ gamma
        remaining = list(range(len(rows)))
        for winner in winners:
            pos = remaining.index(winner)
            matrix = np.vstack([rows[index]["raw_z"] for index in remaining])
            current = utility[remaining]
            weights = np.exp(current - logsumexp(current))
            loss += -utility[winner] + logsumexp(current)
            gradient += -rows[winner]["raw_z"] + weights @ matrix
            remaining.pop(pos)
    return loss / len(groups), gradient / len(groups)


def fit_offset(rows: list[dict[str, Any]], base_scaler: Any, base_coef: np.ndarray) -> tuple[dict[str, Any], np.ndarray, dict[str, Any]]:
    scaler = scale_fit(rows)
    groups = []
    for values, winner_indices in iter2.valid_pl_races(rows)[0]:
        for row in values:
            row["raw_z"] = scale_transform(row["raw_features"], scaler)
            row["base_utility"] = float(base_scaler.transform(np.asarray([row["features"]], dtype=float))[0, :19] @ base_coef)
        groups.append((values, winner_indices))
    if not groups:
        raise Stop("STOP_OFFSET_PL_NO_TRAINING_RACES")
    fit = minimize(lambda x: _partial_objective(groups, x)[0], np.zeros(7), jac=lambda x: _partial_objective(groups, x)[1], method="L-BFGS-B", options={"maxiter": 1000, "gtol": 1e-6})
    if not fit.success or not np.all(np.isfinite(fit.x)):
        raise Stop(f"STOP_OFFSET_PL_NUMERICAL:{fit.message}")
    return scaler, np.asarray(fit.x, dtype=float), {"optimizer_success": True, "optimizer_message": str(fit.message), "iterations": int(fit.nit), "objective": float(fit.fun), "l2_regularization": 0.0, "training_races": len(groups)}


def predict_fold(rows: list[dict[str, Any]], base_scaler: Any, base_coef: np.ndarray, raw_scaler: dict[str, Any], gamma: np.ndarray) -> None:
    for values in _race_groups(rows).values():
        matrix = np.vstack([np.asarray(row["features"], dtype=float) for row in values])
        utility = base_scaler.transform(matrix)[:, :19] @ base_coef
        for row, item in zip(values, utility):
            row["base_utility"] = float(item)
            row["raw_z"] = scale_transform(row["raw_features"], raw_scaler)
        base, total = iter2.pl_top3(base_scaler.transform(matrix), base_coef)
        offset, offset_total = _top3_from_utility(utility + np.vstack([row["raw_z"] for row in values]) @ gamma)
        if abs(total - 3.0) > 1e-8 or abs(offset_total - 3.0) > 1e-8:
            raise Stop("STOP_OFFSET_PL_PROBABILITY_MASS")
        for row, base_p, v2_p in zip(values, base, offset):
            row["base_p_top3"] = float(base_p)
            row["v2_p_top3"] = float(v2_p)


def _top3_from_utility(utility: np.ndarray) -> tuple[np.ndarray, float]:
    if utility.ndim != 1 or len(utility) < 3 or not np.all(np.isfinite(utility)):
        raise Stop("STOP_OFFSET_PL_UTILITY_INVALID")
    worth = np.exp(utility - float(np.max(utility)))
    total = float(worth.sum())
    output = np.zeros(len(worth))
    for a in range(len(worth)):
        pa = worth[a] / total
        for b in range(len(worth)):
            if a == b:
                continue
            pab = pa * worth[b] / (total - worth[a])
            for c in range(len(worth)):
                if c in (a, b):
                    continue
                probability = pab * worth[c] / (total - worth[a] - worth[b])
                output[a] += probability; output[b] += probability; output[c] += probability
    if not np.all(np.isfinite(output)) or abs(float(output.sum()) - 3.0) > 1e-8:
        raise Stop("STOP_OFFSET_PL_PROBABILITY_MASS")
    return output, float(output.sum())


def selection(rows: list[dict[str, Any]], score: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected, rank1 = [], []
    for _, values in sorted(_race_groups(rows).items()):
        k = sum(bool(row["current_buy"]) for row in values)
        if not k:
            continue
        ordered = sorted(values, key=lambda row: (-float(row[score]), int(row["horse_number"])))
        if k < len(ordered) and float(ordered[k - 1][score]) == float(ordered[k][score]):
            raise Stop("STOP_OFFSET_PL_SELECTION_TIE_UNRESOLVED")
        selected.extend(ordered[:k]); rank1.append(ordered[0])
    return selected, rank1


def current_selection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["current_buy"]]


def metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(bool(row["actual_top3"]) for row in valid)
    return {"selected_n": len(rows), "valid_n": len(valid), "invalid_n": len(rows) - len(valid), "top3_hits": hits, "top3_rate": hits / len(valid) if valid else None}


def brier(rows: list[dict[str, Any]], field: str) -> float:
    valid = [row for row in rows if row["valid_result"]]
    return float(np.mean([(float(row[field]) - int(bool(row["actual_top3"]))) ** 2 for row in valid]))


def global_selection(rows: list[dict[str, Any]], score: str) -> dict[str, list[dict[str, Any]]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[str(row["date"])].append(row)
    output = {}
    for date, values in sorted(by_date.items()):
        n = sum(bool(row["current_buy"]) for row in values)
        output[date] = sorted(values, key=lambda row: (-float(row[score]), str(row["race_id"]), int(row["horse_number"])))[:n]
    return output


def bootstrap_race_delta(rows: list[dict[str, Any]], seed: int = 20261020) -> dict[str, Any]:
    by_date: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_date[str(row["date"])].append(float(row["race_top3_delta"]))
    dates = sorted(by_date)
    if not dates:
        raise Stop("STOP_OFFSET_PL_BOOTSTRAP_EMPTY")
    rng, values = random.Random(seed), []
    for _ in range(10000):
        sample = [rng.choice(dates) for _ in dates]
        flattened = [value for date in sample for value in by_date[date]]
        values.append(float(np.mean(flattened)))
    values.sort()
    observed = float(np.mean([value for date in dates for value in by_date[date]]))
    return {"unit": "DATE", "seed": seed, "iterations": 10000, "mean_race_delta": observed, "ci_lower_95": values[249], "ci_upper_95": values[9749]}


def bootstrap_rate(left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]], seed: int = 20261020) -> dict[str, Any]:
    dates = sorted(set(left) & set(right))
    rng, values = random.Random(seed), []
    for _ in range(10000):
        sample = [rng.choice(dates) for _ in dates]
        def rate(source: dict[str, dict[str, Any]]) -> float:
            return sum(source[date]["top3_hits"] for date in sample) / sum(source[date]["valid_n"] for date in sample)
        values.append(rate(right) - rate(left))
    values.sort()
    point = sum(right[d]["top3_hits"] for d in dates) / sum(right[d]["valid_n"] for d in dates) - sum(left[d]["top3_hits"] for d in dates) / sum(left[d]["valid_n"] for d in dates)
    return {"unit": "DATE", "seed": seed, "iterations": 10000, "point_difference": point, "ci_lower_95": values[249], "ci_upper_95": values[9749]}


def reproduction(train: list[dict[str, Any]], test: list[dict[str, Any]], frozen: dict[tuple[str, str, int], dict[str, Any]]) -> tuple[Any, np.ndarray, dict[str, Any]]:
    scaler, coef, audit = iter2.pl_fit(train)
    predicted = {}
    for values in _race_groups(test).values():
        p, total = iter2.pl_top3(scaler.transform(np.vstack([np.asarray(row["features"], dtype=float) for row in values])), coef)
        if abs(total - 3.0) > 1e-8:
            raise Stop("STOP_BASE_PL_PROBABILITY_MASS")
        for row, probability in zip(values, p):
            predicted[(row["date"], row["race_id"], row["horse_number"])] = float(probability)
    deltas = []
    for key, value in predicted.items():
        if key not in frozen:
            raise Stop("STOP_BASE_PL_REPRODUCTION_IDENTITY")
        deltas.append(abs(value - float(frozen[key]["p_hgb"])))
    max_delta = max(deltas, default=0.0)
    if max_delta != 0.0:
        raise Stop(f"STOP_BASE_PL_REPRODUCTION_FAILURE:{max_delta!r}")
    return scaler, coef, {"status": "PASS", "rows": len(predicted), "max_abs_probability_difference": max_delta, "pl_audit": audit}


def _full_metric_by_month(rows: list[dict[str, Any]], selection_fn) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    daily, monthly = {}, {}
    for date in sorted({row["date"] for row in rows}):
        daily[date] = metric(selection_fn([row for row in rows if row["date"] == date]))
    for month in EVAL_MONTHS:
        monthly[month] = metric([row for date in daily if date.startswith(month) for row in selection_fn([item for item in rows if item["date"] == date])])
    return daily, monthly


def _rank_positions(rows: list[dict[str, Any]], score: str) -> dict[tuple[str, str, int], int]:
    result = {}
    for (_, _), values in _race_groups(rows).items():
        ordered = sorted(values, key=lambda row: (-float(row[score]), int(row["horse_number"])))
        for position, row in enumerate(ordered, start=1):
            result[(row["date"], row["race_id"], row["horse_number"])] = position
    return result


def phase5_diagnostics(rows: list[dict[str, Any]], current: list[dict[str, Any]], base: list[dict[str, Any]], v2: list[dict[str, Any]], fold_outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Pre-registered, descriptive-only diagnostics; no selection rule is formed."""
    race_k = {key: sum(bool(row["current_buy"]) for row in values) for key, values in _race_groups(rows).items()}
    same_k = lambda row, k: race_k[(row["date"], row["race_id"])] == k
    by_k = {}
    for k in (1, 2, 3):
        by_k[str(k)] = {
            "CURRENT": metric([row for row in current if same_k(row, k)]),
            "BASE_PL": metric([row for row in base if same_k(row, k)]),
            "OFFSET_PL_V2": metric([row for row in v2 if same_k(row, k)]),
        }
    base_ranks, v2_ranks = _rank_positions(rows, "base_p_top3"), _rank_positions(rows, "v2_p_top3")
    rank_metrics = {}
    for rank in (1, 2, 3):
        rank_metrics[str(rank)] = {
            "BASE_PL": metric([row for row in rows if base_ranks[(row["date"], row["race_id"], row["horse_number"])] == rank]),
            "OFFSET_PL_V2": metric([row for row in rows if v2_ranks[(row["date"], row["race_id"], row["horse_number"])] == rank]),
        }
    missing = {}
    for index, feature in enumerate(FEATURES):
        absent = sum(row["raw_features"][index] is None for row in rows)
        missing[feature] = {"missing_n": absent, "total_n": len(rows), "missing_rate": absent / len(rows)}
    top5_inside = [row for row in current if bool(row.get("current_top5"))]
    top5_outside = [row for row in current if not bool(row.get("current_top5"))]
    return {
        "role": "SECONDARY_DESCRIPTIVE_ONLY_NOT_GATED",
        "CURRENT_TOP5_INSIDE": metric(top5_inside),
        "CURRENT_TOP5_OUTSIDE": metric(top5_outside),
        "same_volume_by_current_k": by_k,
        "all_race_rank_position": rank_metrics,
        "feature_missing_rates": missing,
        "offset_coefficients_by_fold": [
            {"fold_id": item["fold"]["fold_id"], "coefficients": dict(zip(FEATURES, item["coefficients"]))}
            for item in fold_outputs
        ],
    }


def run(output: Path = OUT) -> dict[str, Any]:
    if output.exists():
        raise Stop("STOP_EXP025_OUTPUT_EXISTS")
    authority = authority_check()
    # Build and validate every raw-history feature from PRE-only source rows
    # before opening the frozen Result-joined evaluation population.
    pre_source_rows = iter0.load_pre_rows()
    raw_map, raw_audit = history_by_target(pre_source_rows)
    pre_rows = iter2.load_rows()
    frozen = frozen_rows()
    if set((row["date"], row["race_id"], row["horse_number"]) for row in pre_rows if row["month"] in EVAL_MONTHS) != set(frozen):
        raise Stop("STOP_ITER2_FROZEN_POPULATION_MISMATCH")
    for row in pre_rows:
        _history, raw, audit = raw_map[(row["date"], row["race_id"], row["horse_number"])]
        row["raw_features"], row["raw_feature_audit"] = raw, audit
    if any(row["raw_features"][4] is None for row in pre_rows):
        raise Stop("STOP_SURFACE_SWITCH_MISSING_POLICY_UNSPECIFIED")
    staging_parent = output.parent
    staging = Path(tempfile.mkdtemp(prefix=".exp025_staging_", dir=staging_parent))
    try:
        dump(staging, "authority_verification.json", authority)
        dump(staging, "source_identity_audit.json", raw_audit)
        folds, fold_outputs, all_eval = iter0.folds(pre_rows), [], []
        for fold in folds:
            month = fold["evaluation_months"][0]
            train = [row for row in pre_rows if row["month"] in fold["train_months"] and row["valid_result"]]
            test = [dict(row) for row in pre_rows if row["month"] == month]
            base_scaler, base_coef, reproduction_audit = reproduction(train, test, frozen)
            raw_scaler, gamma, offset_audit = fit_offset(train, base_scaler, base_coef)
            predict_fold(test, base_scaler, base_coef, raw_scaler, gamma)
            for row in test:
                row["fold_id"] = fold["fold_id"]
            all_eval.extend(test)
            fold_outputs.append({"fold": fold, "base_pl_reproduction": reproduction_audit, "raw_scaler": raw_scaler, "offset_fit": offset_audit, "coefficients": [float(x) for x in gamma]})
        dump(staging, "fold_audit.json", fold_outputs)
        current = current_selection(all_eval)
        base, base_rank1 = selection(all_eval, "base_p_top3")
        v2, v2_rank1 = selection(all_eval, "v2_p_top3")
        dump(staging, "phase5_secondary_diagnostics.json", phase5_diagnostics(all_eval, current, base, v2, fold_outputs))
        current_by_race = _race_groups(current)
        base_by_race = _race_groups(base); v2_by_race = _race_groups(v2)
        race_delta = []
        for key in sorted(set(base_by_race) & set(v2_by_race)):
            if key not in current_by_race:
                continue
            b, v = metric(base_by_race[key]), metric(v2_by_race[key])
            race_delta.append({"date": key[0], "month": key[0][:6], "race_id": key[1], "base_pl_top3_count": b["top3_hits"], "v2_top3_count": v["top3_hits"], "race_top3_delta": v["top3_hits"] - b["top3_hits"], "base_valid_n": b["valid_n"], "v2_valid_n": v["valid_n"]})
        base_daily, base_month = _full_metric_by_month(all_eval, lambda values: selection(values, "base_p_top3")[0])
        v2_daily, v2_month = _full_metric_by_month(all_eval, lambda values: selection(values, "v2_p_top3")[0])
        current_daily, current_month = _full_metric_by_month(all_eval, current_selection)
        common_rank = [(left, right) for left, right in zip(base_rank1, v2_rank1) if left["valid_result"] and right["valid_result"]]
        rank_base, rank_v2 = metric([x[0] for x in common_rank]), metric([x[1] for x in common_rank])
        base_brier, v2_brier = brier(all_eval, "base_p_top3"), brier(all_eval, "v2_p_top3")
        brier_month = [{"month": month, "base_pl_brier": brier([r for r in all_eval if r["month"] == month], "base_p_top3"), "v2_brier": brier([r for r in all_eval if r["month"] == month], "v2_p_top3")} for month in EVAL_MONTHS]
        global_current = global_selection(all_eval, "adjusted_score")
        global_v2 = global_selection(all_eval, "v2_p_top3")
        global_daily_current = {date: metric(value) for date, value in global_current.items()}
        global_daily_v2 = {date: metric(value) for date, value in global_v2.items()}
        global_daily_base = {date: metric(value) for date, value in global_selection(all_eval, "base_p_top3").items()}
        csvout(staging, "global_daily_topn_detail.csv", [
            {"date": date, "CURRENT": global_daily_current[date], "BASE_PL": global_daily_base[date], "OFFSET_PL_V2": global_daily_v2[date]}
            for date in sorted(global_daily_current)
        ], ["date", "CURRENT", "BASE_PL", "OFFSET_PL_V2"])
        global_month_current = {month: metric([r for date, values in global_current.items() if date.startswith(month) for r in values]) for month in EVAL_MONTHS}
        global_month_v2 = {month: metric([r for date, values in global_v2.items() if date.startswith(month) for r in values]) for month in EVAL_MONTHS}
        global_rank_current = [sorted(values, key=lambda r: (-float(r["adjusted_score"]), int(r["horse_number"]))) [0] for values in _race_groups(all_eval).values()]
        global_rank_v2 = [sorted(values, key=lambda r: (-float(r["v2_p_top3"]), int(r["horse_number"]))) [0] for values in _race_groups(all_eval).values()]
        common_global_rank = [(left, right) for left, right in zip(global_rank_current, global_rank_v2) if left["valid_result"] and right["valid_result"]]
        roadmap_boot = bootstrap_rate(global_daily_current, global_daily_v2)
        bootstrap = bootstrap_race_delta(race_delta)
        monthly_ge = sum(v2_month[m]["top3_rate"] >= base_month[m]["top3_rate"] for m in EVAL_MONTHS)
        worse_brier = sum(item["v2_brier"] > item["base_pl_brier"] for item in brier_month)
        global_current_total = metric([r for rows in global_current.values() for r in rows])
        global_v2_total = metric([r for rows in global_v2.values() for r in rows])
        roadmap_rank_current, roadmap_rank_v2 = metric([x[0] for x in common_global_rank]), metric([x[1] for x in common_global_rank])
        roadmap_calibration = brier(all_eval, "v2_p_top3") <= brier(all_eval, "base_p_top3") and worse_brier <= 2
        gates = {
            "GATE_1": bootstrap["ci_lower_95"] > 0.0,
            "GATE_2": monthly_ge >= 5,
            "GATE_3": rank_v2["top3_rate"] >= rank_base["top3_rate"] - 0.01,
            "GATE_4": v2_brier <= base_brier and worse_brier <= 2,
            "GATE_5": all((
                global_v2_total["top3_rate"] - global_current_total["top3_rate"] >= 0.06,
                sum(global_month_v2[m]["top3_rate"] > global_month_current[m]["top3_rate"] for m in EVAL_MONTHS) >= 5,
                roadmap_boot["ci_lower_95"] > 0.0,
                roadmap_rank_v2["top3_rate"] >= roadmap_rank_current["top3_rate"] - 0.01,
                roadmap_calibration,
            )),
        }
        development_gate = all(gates.values())
        monthly_rows = []
        for month in EVAL_MONTHS:
            monthly_rows.append({"month": month, "CURRENT_SELECTED_N": current_month[month]["selected_n"], "CURRENT_TOP3": current_month[month]["top3_hits"], "CURRENT_RATE": current_month[month]["top3_rate"], "BASE_PL_SELECTED_N": base_month[month]["selected_n"], "BASE_PL_TOP3": base_month[month]["top3_hits"], "BASE_PL_RATE": base_month[month]["top3_rate"], "V2_SELECTED_N": v2_month[month]["selected_n"], "V2_TOP3": v2_month[month]["top3_hits"], "V2_RATE": v2_month[month]["top3_rate"], "V2_MINUS_BASE_PL_RATE": v2_month[month]["top3_rate"] - base_month[month]["top3_rate"]})
        csvout(staging, "monthly_table.csv", monthly_rows, list(monthly_rows[0]))
        csvout(staging, "race_top3_delta.csv", race_delta, list(race_delta[0]))
        dump(staging, "gate_evaluation.json", {"gates": gates, "development_gate": "PASS" if development_gate else "FAIL", "bootstrap": bootstrap, "roadmap_bootstrap": roadmap_boot, "monthly_v2_ge_base": monthly_ge, "rank1_base": rank_base, "rank1_v2": rank_v2, "brier_base": base_brier, "brier_v2": v2_brier, "brier_months_worse": worse_brier, "roadmap_current": global_current_total, "roadmap_v2": global_v2_total, "roadmap_rank1_current": roadmap_rank_current, "roadmap_rank1_v2": roadmap_rank_v2, "roadmap_calibration": roadmap_calibration})
        all_selected = []
        for name, values in (("CURRENT", current), ("BASE_PL", base), ("OFFSET_PL_V2", v2)):
            all_selected.extend({"comparator": name, "date": row["date"], "race_id": row["race_id"], "horse_number": row["horse_number"], "horse_name": row["horse_name"], "actual_finish": row["actual_finish"], "actual_top3": row["actual_top3"], "base_p_top3": row.get("base_p_top3"), "v2_p_top3": row.get("v2_p_top3")} for row in values)
        csvout(staging, "selected_horses.csv", all_selected, ["comparator", "date", "race_id", "horse_number", "horse_name", "actual_finish", "actual_top3", "base_p_top3", "v2_p_top3"])
        # Final-only candidate: fixed PL Forward v1 is permitted solely here.
        model = json.loads(PL_FORWARD_MODEL.read_text(encoding="utf-8"))
        final_rows = [row for row in pre_rows if row["valid_result"]]
        final_scaler = type("Scaler", (), {"mean_": np.asarray(model["scaler"]["mean"], dtype=float), "scale_": np.asarray(model["scaler"]["scale"], dtype=float), "transform": lambda self, x: (x - self.mean_) / self.scale_})()
        final_coef = np.asarray(model["pl_coefficients"], dtype=float)
        final_raw_scaler, final_gamma, final_audit = fit_offset(final_rows, final_scaler, final_coef)
        final_model = {"model": "OFFSET_PL_RAW_HISTORY_V2", "role": "DEVELOPMENT_ONLY_NON_EVIDENTIAL", "base_model": "PL_FORWARD_SHADOW_V1", "base_model_sha256": PL_FORWARD_SHA, "training_dates": ["20260201", "20260913"], "feature_order": list(FEATURES), "history_window": "LATEST_UP_TO_3_VALID_RACES", "identity_rule": "APPROVED_NAME_SIRE_MATERNAL_GRANDSIRE_V1", "continuous_scaler": final_raw_scaler, "offset_coefficients": [float(x) for x in final_gamma], "l2_regularization": 0.0, "optimizer": final_audit, "production_override": False}
        dump(staging, "final_offset_pl_v2_model.json", final_model)
        final_sha = sha(staging / "final_offset_pl_v2_model.json")
        dump(staging, "secondary_0919_1012.json", {"status": "NOT_AVAILABLE", "reason": "No canonical precomputed EXP-025-compatible raw-feature population is frozen for the consumed period; no replay was authorized by this runner."})
        summary = {"STATUS": "COMPLETE", "EXPERIMENT_ID": EXPERIMENT_ID, "IMPLEMENTATION_STATUS": "COMPLETE", "BASE_PL_REPRODUCTION": "PASS", "FOLDS_COMPLETED": len(fold_outputs), "FEATURE_SET_MATCH_PREREG": "PASS", "RESULT_DEPENDENT_FEATURES": 0, "CURRENT": metric(current), "BASE_PL": metric(base), "V2": metric(v2), "V2_MINUS_BASE_PL_RATE": metric(v2)["top3_rate"] - metric(base)["top3_rate"], "RACE_DELTA_SUM": sum(r["race_top3_delta"] for r in race_delta), "MEAN_RACE_DELTA": bootstrap["mean_race_delta"], "BOOTSTRAP_SEED": 20261020, "BOOTSTRAP_CI_LOWER": bootstrap["ci_lower_95"], "BOOTSTRAP_CI_UPPER": bootstrap["ci_upper_95"], "MONTHS_V2_GE_BASE_PL": f"{monthly_ge}/7", "RANK1_BASE_PL": rank_base, "RANK1_V2": rank_v2, "RANK1_DIFFERENCE": rank_v2["top3_rate"] - rank_base["top3_rate"], "BRIER_BASE_PL": base_brier, "BRIER_V2": v2_brier, "BRIER_MONTHS_WORSE": worse_brier, "GLOBAL_DAILY_TOPN_CURRENT": global_current_total, "GLOBAL_DAILY_TOPN_BASE_PL": metric([r for rows in global_selection(all_eval, "base_p_top3").values() for r in rows]), "GLOBAL_DAILY_TOPN_V2": global_v2_total, "ROADMAP_GATE_STATUS": "PASS" if gates["GATE_5"] else "FAIL", **{key: "PASS" if value else "FAIL" for key, value in gates.items()}, "DEVELOPMENT_GATE": "PASS" if development_gate else "FAIL", "FINAL_MODEL_TRAINED": True, "FINAL_MODEL_SHA256": final_sha, "SECONDARY_0919_1012_STATUS": "NOT_AVAILABLE", "EXP024_CHANGED": False, "PRODUCTION_CHANGED": False, "PROSPECTIVE_EVIDENCE_CREDIT": 0}
        dump(staging, "summary.json", summary)
        summary_md = "# EXP-025 Offset PL V2\n\n" + "\n".join(f"- `{key}` = `{value}`" for key, value in summary.items()) + "\n"
        (staging / "summary.md").write_text(summary_md, encoding="utf-8")
        hashes = {path.relative_to(staging).as_posix(): {"sha256": sha(path), "size": path.stat().st_size} for path in sorted(staging.rglob("*")) if path.is_file() and path.name != "artifact_hashes.json"}
        dump(staging, "artifact_hashes.json", {"self_hash_excluded": True, "artifacts": hashes})
        staging.rename(output)
        return summary
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    print(canonical(run(args.output)))


if __name__ == "__main__":
    main()
