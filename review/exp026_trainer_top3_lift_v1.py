"""Isolated EXP-026 implementation. Import and PRE-label preparation do not read target Result.

The one-shot development entry point is disabled until a separate Human execution
instruction. No existing prediction, B1, E1, or formal PRE/POST module is edited.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

from review import exp025_offset_pl_raw_history_v1 as exp025
from review import full_field_redesign_iter0_retry7 as iter0
from review import full_field_redesign_iteration2_v1 as iter2
from review import jockey_context_cross_snapshot_pit_audit_v1 as pit
from review import post_ws2_jockey_mechanism_research_v1_model as jockey
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / "docs/KeibaAI_EXP026_Trainer_Top3_Lift_Preregistration_20261110.md"
PREREG_SHA = "4229bf4f58beeca60b43770ed5e7b4d4bbbae4942cbaaa0a2a35abca2ac51b20"
B1_SOURCE = ROOT / "reports/historical_buy_selection_audit_202603_202609_v1/selection_comparison.csv"
B1_SHA = "b58544abfdf275be28fe49a945f0d35073feafd8a4fd0cfcec7db4316e40aba6"
JOCKEY_ROWS = ROOT / "reports/post_ws2_jockey_mechanism_research_v1_development/evaluation_rows.csv"
JOCKEY_ROWS_SHA = "66afcc3212b4f2129174dbd1d671c69912e2489c05b95511b64339f17a480ac9"
FOLD_AUDIT = ROOT / "reports/post_ws2_jockey_mechanism_research_v1_development/fold_audit.json"
FOLD_AUDIT_SHA = "8fe1110db035798aef712c3142cb600e03ee4c422005fedc4ce07cd3d7c61645"
OUT = ROOT / "reports/exp026_trainer_top3_lift_v1_development"
PRELABEL_OUT = ROOT / "reports/exp026_trainer_top3_lift_v1_prelabel"
TEST_FILE = ROOT / "tests/test_exp026_trainer_top3_lift_v1.py"
SEED = 20261110
KAPPA = 10.0
BASELINE_GAP = 0.08146014347072025


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def _csv_write(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def verify_authorities() -> None:
    for path, expected in ((PREREG, PREREG_SHA), (B1_SOURCE, B1_SHA),
                           (JOCKEY_ROWS, JOCKEY_ROWS_SHA), (FOLD_AUDIT, FOLD_AUDIT_SHA)):
        if not path.is_file() or sha(path) != expected:
            raise Stop(f"STOP_EXP026_AUTHORITY:{path.name}")


def key(row: dict[str, Any]) -> tuple[str, str, int]:
    return str(row["date"]), str(row["race_id"]), int(row["horse_number"])


def history_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (*tuple(record["horse_identity"]), str(record["historical_race_id"]))


def trainer_feature(target: dict[str, Any], records: dict[tuple[Any, ...], dict[str, Any]],
                    pair_codes: dict[tuple[str, str], set[str]],
                    by_code: dict[str, set[tuple[Any, ...]]] | None = None) -> dict[str, Any]:
    """Compute the frozen prior using only this target's own as-of pool."""
    date = str(target["date"])
    pair = (exp025.clean(target["trainer_name"]), exp025.clean(target["trainer_affiliation"]))
    codes = pair_codes.get(pair, set())
    code = next(iter(codes)) if len(codes) == 1 else None
    if not code:
        return {"trainer_top3_lift": 0.0, "prior_count": 0, "H_T": 0,
                "E_T": 0.0, "mapping_status": "AMBIGUOUS" if len(codes) > 1 else "UNMAPPED"}
    own = tuple(target["horse_identity"])
    hits, expected, count = 0, 0.0, 0
    available = (records[k] for k in sorted(by_code.get(code, set()))) if by_code is not None else records.values()
    for record in available:
        if str(record["trainer_code"]) != code or tuple(record["horse_identity"]) == own:
            continue
        if str(record["snapshot_date"]) > date or str(record["historical_race_date"]) >= date:
            raise Stop("STOP_EXP026_HISTORY_NOT_ASOF")
        field = jockey._strict_field_size(record["field_size"])
        finish = jockey._strict_finish(record["finish"])
        if field is None or finish is None:
            raise Stop("STOP_EXP026_INVALID_HISTORY")
        count += 1
        hits += int(finish <= 3)
        expected += min(3, field) / field
    return {"trainer_top3_lift": math.log((hits + KAPPA) / (expected + KAPPA)) if count else 0.0,
            "prior_count": count, "H_T": hits, "E_T": expected,
            "mapping_status": "MAPPED" if count else "NO_HISTORY"}


def feature_map_asof(targets: list[dict[str, Any]],
                     snapshots: dict[str, list[dict[str, Any]]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        by_date[str(target["date"])].append(target)
    known: dict[tuple[Any, ...], dict[str, Any]] = {}
    by_code: dict[str, set[tuple[Any, ...]]] = defaultdict(set)
    pair_codes: dict[tuple[str, str], set[str]] = defaultdict(set)
    output = {}
    for date in sorted(snapshots):
        for record in snapshots[date]:
            if str(record["snapshot_date"]) != date or str(record["historical_race_date"]) >= date:
                raise Stop("STOP_EXP026_SNAPSHOT_DATE")
            hkey = history_key(record)
            old = known.get(hkey)
            fields = ("historical_race_date", "trainer_name", "trainer_affiliation",
                      "trainer_code", "field_size", "finish")
            if old is not None:
                if any(old[field] != record[field] for field in fields):
                    raise Stop("STOP_EXP026_CROSS_SNAPSHOT_HISTORY_CONFLICT")
                continue
            known[hkey] = record
            code = exp025.clean(record["trainer_code"])
            if code:
                pair_codes[(exp025.clean(record["trainer_name"]),
                            exp025.clean(record["trainer_affiliation"]))].add(code)
                by_code[code].add(hkey)
        for target in by_date[date]:
            tkey = key(target)
            if tkey in output:
                raise Stop("STOP_EXP026_DUPLICATE_TARGET")
            output[tkey] = trainer_feature(target, known, pair_codes, by_code)
    if len(output) != len(targets):
        raise Stop("STOP_EXP026_TARGET_COVERAGE")
    return output


def load_prelabel_inputs() -> tuple[list[dict[str, Any]], dict[tuple[str, str, int], dict[str, Any]]]:
    """Read the approved 62 PRE snapshots only; do not open target Result."""
    if not PREREG.is_file() or sha(PREREG) != PREREG_SHA:
        raise Stop("STOP_EXP026_PREREG_AUTHORITY")
    targets, jockey_snapshots = jockey.load_development_pit_pool()
    jockey_map = jockey.feature_map_asof(targets, jockey_snapshots)
    target_by_key = {key(row): row for row in targets}
    adapter = TargetBulkPredictionInputAdapterV1()
    trainer_snapshots = {}
    for date in jockey.development_source_dates():
        de = exp025.read_source(exp025.source_path("DE", date), 33)
        ds = exp025.read_source(exp025.source_path("DS", date), 50)
        by_identity: dict[tuple[str, str, str], list[list[str]]] = defaultdict(list)
        for row in ds:
            by_identity[(exp025.clean(row[16]), exp025.clean(row[44]), exp025.clean(row[46]))].append(row)
        snapshot = {}
        for row in de:
            race = exp025.race_id(date, exp025.clean(row[1]), exp025.integer(row[2]))
            if race in pit.EXCLUDED_RACES:
                continue
            tkey = date, race, exp025.integer(row[3])
            if tkey not in target_by_key:
                raise Stop("STOP_EXP026_TARGET_IDENTITY")
            target = target_by_key[tkey]
            target["trainer_name"] = exp025.clean(row[12])
            target["trainer_affiliation"] = exp025.clean(row[13])
            identity = tuple(target["horse_identity"])
            lookup = identity[0]
            if date == "20260906" and race == exp025.KNOWN_20260906["race_id"] and tkey[2] == exp025.KNOWN_20260906["horse_number"]:
                lookup = exp025.KNOWN_20260906["ds_name"]
            for history in adapter.valid_history_rows(by_identity[(lookup, identity[1], identity[2])]):
                historical_date = exp025.ds_date(history)
                if historical_date >= date:
                    raise Stop("STOP_EXP026_FUTURE_HISTORY")
                historical_race = adapter._race_id(historical_date, exp025.clean(history[4]),
                                                   exp025.integer(history[6]))
                record = {"snapshot_date": date, "horse_identity": identity,
                          "historical_race_id": historical_race,
                          "historical_race_date": historical_date,
                          "trainer_name": exp025.clean(history[39]),
                          "trainer_affiliation": exp025.clean(history[40]),
                          "trainer_code": exp025.clean(history[43]),
                          "field_size": history[21], "finish": history[23]}
                hkey = history_key(record)
                if hkey in snapshot and snapshot[hkey] != record:
                    raise Stop("STOP_EXP026_WITHIN_SNAPSHOT_CONFLICT")
                snapshot[hkey] = record
        trainer_snapshots[date] = list(snapshot.values())
    tmap = feature_map_asof(targets, trainer_snapshots)
    if set(tmap) != set(jockey_map):
        raise Stop("STOP_EXP026_JOCKEY_TARGET_MISMATCH")
    combined = {k: {**v, **jockey_map[k]} for k, v in tmap.items()}
    return targets, combined


PRELABEL_FIELDS = ("date", "race_id", "horse_number", "horse_name", "trainer_name",
                   "trainer_affiliation", "mapping_status", "prior_count", "H_T", "E_T",
                   "trainer_top3_lift", "JOCKEY_TOP3_LIFT")


def _prelabel_rows(targets: list[dict[str, Any]], features: dict[tuple[str, str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**{field: target.get(field, "") for field in PRELABEL_FIELDS}, **features[key(target)]}
            for target in sorted(targets, key=key)]


def _prelabel_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    evaluation = [row for row in rows if str(row["date"]) >= "20260301"]
    status = Counter(str(row["mapping_status"]) for row in evaluation)
    counts = {"all_rows": len(rows), "evaluation_rows": len(evaluation),
              "mapped_unique": status["MAPPED"] + status["NO_HISTORY"],
              "ambiguous": status["AMBIGUOUS"], "unmapped": status["UNMAPPED"],
              "zero_history": sum(int(row["prior_count"]) == 0 for row in evaluation)}
    if counts != {"all_rows": 14870, "evaluation_rows": 12661, "mapped_unique": 12547,
                  "ambiguous": 46, "unmapped": 68, "zero_history": 132}:
        raise Stop(f"STOP_EXP026_PRELABEL_COUNTS:{counts}")
    return counts


def freeze_prelabel_features(out_dir: Path = PRELABEL_OUT) -> dict[str, Any]:
    """Freeze PRE-only T/J features without opening an evaluation Result label."""
    if out_dir.exists():
        raise Stop("STOP_EXP026_PRELABEL_ALREADY_EXISTS")
    targets, features = load_prelabel_inputs()
    rows = _prelabel_rows(targets, features)
    counts = _prelabel_counts(rows)
    sources = []
    for date in jockey.development_source_dates():
        sources.append({"date": date, **{kind: sha(exp025.source_path(kind, date))
                                         for kind in ("DG", "DE", "DS")}})
    out_dir.mkdir(parents=True, exist_ok=False)
    table = out_dir / "trainer_prelabel_features.csv"
    _csv_write(table, rows, PRELABEL_FIELDS)
    manifest = {"experiment": "EXP-026", "role": "PRELABEL_FEATURE_FREEZE_ONLY",
                "created_at_utc": _now(), "table_sha256": sha(table), "rows": counts,
                "preregistration_sha256": PREREG_SHA, "source_sha256_by_date": sources,
                "target_result_label_access": 0, "candidate_training_count": 0}
    _json_write(out_dir / "feature_manifest.json", manifest)
    return manifest


def verify_frozen_prelabel(targets: list[dict[str, Any]],
                           features: dict[tuple[str, str, int], dict[str, Any]],
                           out_dir: Path = PRELABEL_OUT) -> dict[str, Any]:
    manifest_path = out_dir / "feature_manifest.json"
    table = out_dir / "trainer_prelabel_features.csv"
    if not manifest_path.is_file() or not table.is_file():
        raise Stop("STOP_EXP026_PRELABEL_FREEZE_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("table_sha256") != sha(table) or manifest.get("preregistration_sha256") != PREREG_SHA:
        raise Stop("STOP_EXP026_PRELABEL_SHA_MISMATCH")
    expected = _prelabel_rows(targets, features)
    _prelabel_counts(expected)
    with table.open(encoding="utf-8", newline="") as handle:
        frozen = list(csv.DictReader(handle))
    numeric = {"E_T", "trainer_top3_lift", "JOCKEY_TOP3_LIFT"}
    if len(frozen) != len(expected) or any(
        any((not math.isfinite(float(left[field])) or
             not math.isfinite(float(right[field])) or
             abs(float(left[field]) - float(right[field])) > 1e-12)
            if field in numeric else (str(left[field]) != str(right[field]))
            for field in PRELABEL_FIELDS)
        for left, right in zip(frozen, expected)
    ):
        raise Stop("STOP_EXP026_PRELABEL_FEATURE_MISMATCH")
    # The frozen T values, not a fresh floating-point summation, are used later.
    for row in frozen:
        features[key(row)]["trainer_top3_lift"] = float(row["trainer_top3_lift"])
    for source in manifest.get("source_sha256_by_date", []):
        for kind in ("DG", "DE", "DS"):
            if source.get(kind) != sha(exp025.source_path(kind, source["date"])):
                raise Stop("STOP_EXP026_PRELABEL_SOURCE_MISMATCH")
    if len(manifest.get("source_sha256_by_date", [])) != 62:
        raise Stop("STOP_EXP026_PRELABEL_SOURCE_SCOPE")
    return manifest


def treatment_probabilities(base_utility: np.ndarray, jockey_lift: np.ndarray,
                            trainer_lift: np.ndarray, beta_jockey: float,
                            beta_trainer: float) -> np.ndarray:
    base = np.asarray(base_utility, dtype=float)
    j = np.asarray(jockey_lift, dtype=float)
    t = np.asarray(trainer_lift, dtype=float)
    if base.shape != j.shape or base.shape != t.shape or base.ndim != 1:
        raise Stop("STOP_EXP026_UTILITY_SHAPE")
    utility = base + float(beta_jockey) * j + float(beta_trainer) * t
    return exp025._top3_from_utility(utility)[0]


def select_b1(rows: list[dict[str, Any]], probability_field: str) -> list[dict[str, Any]]:
    """Same Current daily N and B1's exact score/race/horse ordering, cap three."""
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[str(row["date"])].append(row)
    selected = []
    for date, day in sorted(by_date.items()):
        n = sum(bool(row["current_buy"]) for row in day)
        per_race: Counter[str] = Counter()
        for row in sorted(day, key=lambda r: (-float(r[probability_field]), str(r["race_id"]), int(r["horse_number"]))):
            if n == 0:
                break
            race = str(row["race_id"])
            if per_race[race] >= 3:
                continue
            selected.append(row)
            per_race[race] += 1
            n -= 1
        if n:
            raise Stop(f"STOP_EXP026_B1_VOLUME:{date}")
    return selected


def signed_gap(selected: list[dict[str, Any]], probability_field: str) -> float:
    valid = [row for row in selected if bool(row["valid_result"])]
    if not valid:
        raise Stop("STOP_EXP026_GAP_EMPTY")
    return sum(float(row[probability_field]) - int(bool(row["actual_top3"])) for row in valid) / len(valid)


def verify_saved_b1() -> dict[str, Any]:
    verify_authorities()
    with B1_SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = [r for r in rows if r["C_B1_GLOBAL_CAP3"] == "True"]
    valid = [r for r in selected if r["valid_result"] == "True"]
    hits = sum(r["actual_top3"] == "True" for r in valid)
    gap = sum(float(r["jockey_p_top3"]) - int(r["actual_top3"] == "True") for r in valid) / len(valid)
    if (len(selected), len(valid), hits) != (716, 714, 380) or abs(gap - BASELINE_GAP) > 1e-15:
        raise Stop("STOP_EXP026_B1_REPRODUCTION")
    return {"selected": len(selected), "valid": len(valid), "hits": hits, "gap": gap}


def _partial_nll(utility: np.ndarray, winners: list[int]) -> float:
    remaining = list(range(len(utility)))
    loss = 0.0
    for winner in winners:
        if winner not in remaining:
            raise Stop("STOP_EXP026_ORDERED_WINNERS")
        loss += float(logsumexp(utility[remaining]) - utility[winner])
        remaining.remove(winner)
    return loss


def _fit_beta(train: list[dict[str, Any]], scaler: Any, coef: np.ndarray,
              beta_jockey: float) -> tuple[float, dict[str, Any]]:
    groups = []
    for values, winners in iter2.valid_pl_races(train)[0]:
        matrix = np.vstack([np.asarray(r["features"], dtype=float) for r in values])
        base = scaler.transform(matrix)[:, :19] @ coef
        if not np.all(np.isfinite(base)) or any(not math.isfinite(float(r["trainer_top3_lift"]))
                                             or not math.isfinite(float(r[jockey.FEATURE])) for r in values):
            raise Stop("STOP_EXP026_FIT_NONFINITE")
        group = [{"base_utility": float(u + beta_jockey * float(r[jockey.FEATURE])),
                  jockey.FEATURE: float(r["trainer_top3_lift"])} for r, u in zip(values, base)]
        groups.append((group, winners))
    if not groups:
        raise Stop("STOP_EXP026_NO_TRAINING_RACES")
    fit = minimize(lambda x: jockey._partial_objective_one(groups, x), np.zeros(1),
                   method="L-BFGS-B", jac=True,
                   options={"maxiter": 1000, "gtol": 1e-6})
    if not fit.success or not np.isfinite(fit.x[0]):
        raise Stop("STOP_EXP026_BETA_FIT")
    return float(fit.x[0]), {"optimizer": "L-BFGS-B", "success": bool(fit.success),
                              "training_races": len(groups), "iterations": int(fit.nit),
                              "objective": float(fit.fun), "initial_beta": 0.0,
                              "l2": 0.0, "maxiter": 1000, "gtol": 1e-6}


def _predict_fold(test: list[dict[str, Any]], scaler: Any, coef: np.ndarray,
                  beta_jockey: float, beta_trainer: float) -> None:
    for values in exp025._race_groups(test).values():
        matrix = np.vstack([np.asarray(r["features"], dtype=float) for r in values])
        base = scaler.transform(matrix)[:, :19] @ coef
        j = np.asarray([float(r[jockey.FEATURE]) for r in values])
        t = np.asarray([float(r["trainer_top3_lift"]) for r in values])
        control = treatment_probabilities(base, j, t, beta_jockey, 0.0)
        treatment = treatment_probabilities(base, j, t, beta_jockey, beta_trainer)
        for row, utility, p0, p1 in zip(values, base + beta_jockey * j, control, treatment):
            row["control_utility"] = float(utility)
            row["treatment_utility"] = float(utility + beta_trainer * row["trainer_top3_lift"])
            row["jockey_p_top3"] = float(p0)
            row["trainer_p_top3"] = float(p1)


def _saved_control_rows() -> dict[tuple[str, str, int], dict[str, str]]:
    with JOCKEY_ROWS.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_key = {key(row): row for row in rows}
    if len(rows) != 12661 or len(by_key) != len(rows):
        raise Stop("STOP_EXP026_SAVED_JOCKEY_POPULATION")
    return by_key


def _gates(rows: list[dict[str, Any]], betas: list[float],
           control_selected: list[dict[str, Any]],
           treatment_selected: list[dict[str, Any]]) -> dict[str, Any]:
    losses = []
    for values, winners in iter2.valid_pl_races(rows)[0]:
        losses.append((str(values[0]["date"]),
                       _partial_nll(np.asarray([r["control_utility"] for r in values]), winners),
                       _partial_nll(np.asarray([r["treatment_utility"] for r in values]), winners)))
    if not losses:
        raise Stop("STOP_EXP026_NLL_EMPTY")
    daily: dict[str, list[float]] = defaultdict(list)
    for date, control, treatment in losses:
        daily[date].append(control - treatment)
    daily_delta = np.asarray([np.mean(daily[date]) for date in sorted(daily)])
    rng = np.random.default_rng(SEED)
    samples = np.asarray([float(np.mean(rng.choice(daily_delta, len(daily_delta), replace=True)))
                          for _ in range(10000)])
    ci = np.quantile(samples, [0.025, 0.975])
    control_nll = float(np.mean([r[1] for r in losses]))
    treatment_nll = float(np.mean([r[2] for r in losses]))
    daily_nll = [{"date": date, "race_count": len(daily[date]),
                  "mean_improvement": float(np.mean(daily[date]))} for date in sorted(daily)]
    monthly_nll = [{"month": month,
                    "race_count": sum(date.startswith(month) for date, _, _ in losses),
                    "mean_improvement": float(np.mean([control - treatment for date, control, treatment in losses
                                                       if date.startswith(month)]))}
                   for month in sorted({r[0][:6] for r in losses})]
    valid = [r for r in rows if r["valid_result"]]
    def brier(subset: list[dict[str, Any]], field: str) -> float:
        return sum((float(r[field]) - int(bool(r["actual_top3"]))) ** 2 for r in subset) / len(subset)
    control_brier, treatment_brier = brier(valid, "jockey_p_top3"), brier(valid, "trainer_p_top3")
    months = sorted({str(r["month"]) for r in rows})
    worse_months = sum(brier([r for r in valid if r["month"] == m], "trainer_p_top3") >
                       brier([r for r in valid if r["month"] == m], "jockey_p_top3") for m in months)
    monthly_brier = [{"month": month,
                      "control": brier([r for r in valid if r["month"] == month], "jockey_p_top3"),
                      "treatment": brier([r for r in valid if r["month"] == month], "trainer_p_top3")}
                     for month in months]
    gap_b1 = signed_gap(control_selected, "jockey_p_top3")
    gap_t = signed_gap(treatment_selected, "trainer_p_top3")
    if abs(gap_b1 - BASELINE_GAP) > 1e-12:
        raise Stop("STOP_EXP026_B1_GAP_MISMATCH")
    base_hits = sum(bool(r["actual_top3"]) for r in control_selected if r["valid_result"])
    treatment_hits = sum(bool(r["actual_top3"]) for r in treatment_selected if r["valid_result"])
    losing_months = sum(
        sum(bool(r["actual_top3"]) for r in treatment_selected if r["valid_result"] and r["month"] == m)
        < sum(bool(r["actual_top3"]) for r in control_selected if r["valid_result"] and r["month"] == m)
        for m in months
    )
    if base_hits != 380:
        raise Stop("STOP_EXP026_B1_HITS_MISMATCH")
    monthly_hits = [{"month": month,
                     "control_selected": sum(r["month"] == month for r in control_selected),
                     "treatment_selected": sum(r["month"] == month for r in treatment_selected),
                     "control_hits": sum(bool(r["actual_top3"]) for r in control_selected
                                         if r["valid_result"] and r["month"] == month),
                     "treatment_hits": sum(bool(r["actual_top3"]) for r in treatment_selected
                                           if r["valid_result"] and r["month"] == month)}
                    for month in months]
    dates = sorted({str(r["date"]) for r in rows})
    daily_hits = [{"date": date,
                   "control_selected": sum(r["date"] == date for r in control_selected),
                   "treatment_selected": sum(r["date"] == date for r in treatment_selected),
                   "control_valid": sum(r["date"] == date and bool(r["valid_result"]) for r in control_selected),
                   "treatment_valid": sum(r["date"] == date and bool(r["valid_result"]) for r in treatment_selected),
                   "control_hits": sum(r["date"] == date and bool(r["valid_result"]) and bool(r["actual_top3"])
                                       for r in control_selected),
                   "treatment_hits": sum(r["date"] == date and bool(r["valid_result"]) and bool(r["actual_top3"])
                                         for r in treatment_selected)}
                  for date in dates]
    gates = {
        "G1": treatment_nll < control_nll and float(ci[0]) > 0.0,
        "G2": sum(beta > 0 for beta in betas) >= 6,
        "G3": treatment_brier <= control_brier and worse_months <= 2,
        "G4": gap_t - gap_b1 <= 0.02,
        "G5": treatment_hits >= 380 and losing_months <= 3,
    }
    return {"gates": gates, "verdict": "EXPERIMENT_PASS" if all(gates.values()) else "EXPERIMENT_FAIL",
            "control_nll": control_nll, "treatment_nll": treatment_nll,
            "daily_paired_bootstrap_ci": [float(ci[0]), float(ci[1])],
            "g1_point_weighting": "RACE_EQUAL_MEAN", "g1_bootstrap_weighting": "DATE_EQUAL_MEAN",
            "bootstrap_iterations": 10000, "bootstrap_seed": SEED,
            "daily_nll": daily_nll, "monthly_nll": monthly_nll,
            "control_brier": control_brier, "treatment_brier": treatment_brier,
            "brier_worse_months": worse_months, "monthly_brier": monthly_brier,
            "gap_b1": gap_b1, "gap_t": gap_t,
            "control_hits": base_hits, "treatment_hits": treatment_hits,
            "losing_months": losing_months, "monthly_hits": monthly_hits, "daily_hits": daily_hits,
            "beta_by_fold": betas}


def _baseline_all_folds(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]],
                                                                list[dict[str, Any]],
                                                                list[dict[str, Any]]]:
    """Finish all seven beta_T=0 reproductions before returning any fit context."""
    fold_audit = json.loads(FOLD_AUDIT.read_text(encoding="utf-8"))
    fold_beta = {r["test_months"][0]: float(r["beta_jockey"]) for r in fold_audit}
    if len(fold_beta) != 7:
        raise Stop("STOP_EXP026_JOCKEY_FOLD_BETA")
    frozen = exp025.frozen_rows()
    contexts, all_control = [], []
    for fold in iter0.folds(rows):
        month = fold["evaluation_months"][0]
        train = [r for r in rows if r["month"] in fold["train_months"] and r["valid_result"]]
        test = [dict(r) for r in rows if r["month"] == month]
        scaler, coef, base_audit = jockey.assert_exact_base_reproduction(train, test, frozen)
        beta_j = fold_beta[month]
        _predict_fold(test, scaler, coef, beta_j, 0.0)
        for row in test:
            row["fold"] = fold["fold_id"]
        contexts.append({"fold": fold, "train": train, "test": test, "scaler": scaler,
                         "coef": coef, "beta_jockey": beta_j, "base_audit": base_audit})
        all_control.extend(test)
    if len(contexts) != 7 or len(all_control) != 12661 or len({r["date"] for r in all_control}) != 53:
        raise Stop("STOP_EXP026_EVAL_POPULATION")
    saved = _saved_control_rows()
    if set(saved) != {key(r) for r in all_control}:
        raise Stop("STOP_EXP026_CONTROL_IDENTITY")
    for row in all_control:
        reference = saved[key(row)]
        if abs(float(row[jockey.FEATURE]) - float(reference[jockey.FEATURE])) > 1e-12:
            raise Stop("STOP_EXP026_JOCKEY_FEATURE_MISMATCH")
        if abs(float(row["jockey_p_top3"]) - float(reference["jockey_p_top3"])) > 1e-12:
            raise Stop("STOP_EXP026_CONTROL_PROBABILITY")
    control_selected = select_b1(all_control, "jockey_p_top3")
    with B1_SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        saved_b1 = {key(r) for r in csv.DictReader(handle) if r["C_B1_GLOBAL_CAP3"] == "True"}
    valid = [r for r in control_selected if r["valid_result"]]
    if ({key(r) for r in control_selected} != saved_b1 or
            (len(control_selected), len(valid), sum(bool(r["actual_top3"]) for r in valid)) != (716, 714, 380)):
        raise Stop("STOP_EXP026_B1_SELECTION_IDENTITY")
    return contexts, all_control, control_selected


EVALUATION_FIELDS = ("date", "race_id", "horse_number", "horse_name", "fold", "month",
                     "current_buy", "valid_result", "actual_top3", "JOCKEY_TOP3_LIFT",
                     "trainer_top3_lift", "prior_count", "mapping_status", "control_utility",
                     "jockey_p_top3", "treatment_utility", "trainer_p_top3")
SELECTION_FIELDS = ("date", "race_id", "horse_number", "horse_name", "month",
                    "baseline_selected", "treatment_selected", "daily_selection_count",
                    "monthly_selection_count", "valid_result", "actual_top3")


def _selection_rows(rows: list[dict[str, Any]], control: list[dict[str, Any]],
                    treatment: list[dict[str, Any]]) -> list[dict[str, Any]]:
    control_keys, treatment_keys = {key(r) for r in control}, {key(r) for r in treatment}
    by_date = Counter(r["date"] for r in control)
    by_month = Counter(r["month"] for r in control)
    output = []
    for row in sorted(rows, key=key):
        k = key(row)
        if k in control_keys or k in treatment_keys:
            output.append({**row, "baseline_selected": k in control_keys,
                           "treatment_selected": k in treatment_keys,
                           "daily_selection_count": by_date[row["date"]],
                           "monthly_selection_count": by_month[row["month"]]})
    return output


def execute_one_shot(*, human_execution_approved: bool = False,
                     claude_review_accepted: bool = False,
                     human_approval_id: str | None = None) -> dict[str, Any]:
    """Separately authorized one-shot; never invoked by implementation tests on real inputs."""
    if not human_execution_approved or not claude_review_accepted or not human_approval_id:
        raise Stop("STOP_EXP026_REVIEW_AND_SEPARATE_EXECUTION_APPROVAL_REQUIRED")
    # The module authorities are the only execution paths. Tests isolate them by
    # patching OUT and PRELABEL_OUT, never by passing alternative paths to this API.
    out_dir = OUT.resolve()
    prelabel_dir = PRELABEL_OUT.resolve()
    if not OUT.is_absolute() or not PRELABEL_OUT.is_absolute():
        raise Stop("STOP_EXP026_EXECUTION_PATH_NOT_ABSOLUTE")
    if out_dir.exists():
        raise Stop("STOP_EXP026_ONE_SHOT_ALREADY_EXISTS")
    implementation_sha = sha(Path(__file__))
    test_sha = sha(TEST_FILE)
    prelabel_table = prelabel_dir / "trainer_prelabel_features.csv"
    prelabel_manifest = prelabel_dir / "feature_manifest.json"
    prelabel_table_sha = sha(prelabel_table) if prelabel_table.is_file() else None
    prelabel_manifest_sha = sha(prelabel_manifest) if prelabel_manifest.is_file() else None
    started = {"experiment": "EXP-026 TRAINER_TOP3_LIFT", "started_at_utc": _now(),
               "human_approval_id": human_approval_id, "status": "STARTED",
               "output_dir": str(out_dir), "prelabel_dir": str(prelabel_dir),
               "preregistration_sha256": PREREG_SHA,
               "implementation_sha256": implementation_sha, "test_sha256": test_sha,
               "baseline_artifact_sha256": B1_SHA,
               "input_artifact_sha256": {
                                         "prelabel_table": prelabel_table_sha,
                                         "prelabel_manifest": prelabel_manifest_sha,
                                         "saved_jockey_rows": JOCKEY_ROWS_SHA,
                                         "jockey_fold_audit": FOLD_AUDIT_SHA}}
    if Path(started["output_dir"]) != OUT.resolve() or Path(started["prelabel_dir"]) != PRELABEL_OUT.resolve():
        raise Stop("STOP_EXP026_EXECUTION_PATH_MISMATCH")
    # Claim before opening or hashing any Result-labelled input. This also makes
    # a failed authority/PRE-label check a non-retryable one-shot STOP.
    out_dir.mkdir(parents=True, exist_ok=False)
    stage = "WRITE_EXECUTION_STARTED"
    completed_folds: list[dict[str, Any]] = []
    try:
        _json_write(out_dir / "execution_started.json", started)
        stage = "VERIFY_AUTHORITIES_AND_PRELABEL"
        verify_authorities()
        targets, feature_map = load_prelabel_inputs()  # PRE-only source rows.
        prelabel = verify_frozen_prelabel(targets, feature_map, prelabel_dir)
        _json_write(out_dir / "prelabel_verified.json",
                    {"table_sha256": prelabel["table_sha256"],
                     "manifest_sha256": sha(prelabel_dir / "feature_manifest.json"),
                     "row_counts": prelabel["rows"], "status": "VERIFIED"})
        stage = "READ_BASELINE_AND_TARGET_RESULT"
        verify_saved_b1()
        rows = iter2.load_rows()  # First new target Result-label read; execution_started exists.
        jockey.reject_consumed_secondary(rows)
        if len(rows) != len(targets) or {key(r) for r in rows} != set(feature_map):
            raise Stop("STOP_EXP026_RESULT_PRE_POPULATION")
        for row in rows:
            row.update(feature_map[key(row)])
        stage = "ALL_FOLD_ZERO_BETA_BASELINE_REPRODUCTION"
        contexts, all_control, control_selected = _baseline_all_folds(rows)
        _json_write(out_dir / "baseline_verified.json",
                    {"status": "PASS", "folds": 7, "rows": 12661, "b1_selected": 716,
                     "b1_valid": 714, "b1_hits": 380, "tolerance": 1e-12,
                     "checks": ["identity", "JOCKEY_TOP3_LIFT", "PL+Jockey probability",
                                "B1 selected identity"]})
        stage = "BETA_T_FIT"
        all_eval, betas = [], []
        for context in contexts:
            fold = context["fold"]
            beta_t, fit = _fit_beta(context["train"], context["scaler"], context["coef"],
                                    context["beta_jockey"])
            test = context["test"]
            _predict_fold(test, context["scaler"], context["coef"], context["beta_jockey"], beta_t)
            all_eval.extend(test)
            betas.append(beta_t)
            completed_folds.append({"fold_id": fold["fold_id"], "train_months": fold["train_months"],
                                    "evaluation_months": fold["evaluation_months"],
                                    "train_rows": fold["train_rows"],
                                    "evaluation_rows": fold["evaluation_rows"],
                                    "beta_jockey": context["beta_jockey"], "beta_trainer": beta_t,
                                    "base_reproduction": context["base_audit"],
                                    "optimizer": fit, "status": "COMPLETE"})
            _json_write(out_dir / "fold_audit_partial.json", completed_folds)
        stage = "CANDIDATE_SELECTION_AND_GATES"
        treatment_selected = select_b1(all_eval, "trainer_p_top3")
        if len(treatment_selected) != 716:
            raise Stop("STOP_EXP026_TREATMENT_VOLUME")
        result = _gates(all_eval, betas, control_selected, treatment_selected)
        stage = "WRITE_AUDIT_ARTIFACTS"
        _csv_write(out_dir / "evaluation_rows.csv", sorted(all_eval, key=key), EVALUATION_FIELDS)
        _json_write(out_dir / "fold_audit.json", completed_folds)
        _csv_write(out_dir / "selection_comparison.csv",
                   _selection_rows(all_eval, control_selected, treatment_selected), SELECTION_FIELDS)
        _json_write(out_dir / "metrics.json", result)
        _json_write(out_dir / "gate_result.json", result)
        artifacts = {path.name: sha(path) for path in out_dir.iterdir() if path.is_file()}
        _json_write(out_dir / "execution_complete.json",
                    {**started, "completed_at_utc": _now(), "status": "COMPLETE",
                     "verdict": result["verdict"], "artifact_sha256": artifacts})
        return result
    except Exception as error:
        try:
            _json_write(out_dir / "execution_stopped.json",
                        {**started, "stopped_at_utc": _now(), "status": "STOPPED",
                         "stage": stage, "reason_type": type(error).__name__,
                         "reason": str(error), "completed_fold_count": len(completed_folds),
                         "available_artifacts": sorted(path.name for path in out_dir.iterdir() if path.is_file())})
        except Exception:
            pass  # The exclusive OUT directory still prevents automatic rerun.
        raise
