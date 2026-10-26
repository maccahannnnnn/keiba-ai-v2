"""Versioned, leakage-safe adaptive PL development shadow.

This module deliberately reuses the frozen Iteration 2 PL implementation and
the frozen PL Forward feature transform.  It does not change Current or any
Production decision.  Catch-up dates are admitted only after their frozen PRE
payload features exactly reproduce from the source identities recorded at PRE
time.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from review import full_field_redesign_iter0_retry7 as iter0
from review import full_field_redesign_iteration2_v1 as iter2
from review import pl_forward_shadow_v1 as forward
from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome, parse_race_id, result_rows
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new


ROOT = Path(__file__).resolve().parents[1]
FORWARD_ROOT = ROOT / "models" / "pl_forward_shadow_v1"
MODEL_ROOT = ROOT / "models" / "pl_adaptive_shadow_v1"
VERSIONS_ROOT = MODEL_ROOT / "versions"
CURRENT_POINTER = MODEL_ROOT / "current.json"
LEDGER = MODEL_ROOT / "update_ledger.jsonl"
REPORT_ROOT = ROOT / "reports" / "pl_adaptive_shadow_v1"
INITIAL_BASE_CUTOFF = "20260913"
INITIAL_CATCHUP_MAX = "20261012"
EXPECTED_FORWARD = {
    FORWARD_ROOT / "pl_forward_shadow_v1_model.json": "418fc9b4cefe1757f79dfc22a7d49b7c1592b91084cca97f88f55bb1389b0585",
    FORWARD_ROOT / "pl_forward_shadow_v1_manifest.json": "18443426b16dba4c28374d39841eeac0a98af4dd4e617b8ae8457dcee2f6494e",
    ROOT / "review" / "pl_forward_shadow_v1.py": "1a36902f2afee91bd03f99394cc52bf15ba8a8e2b1e99afa009b8df159f8b3cc",
    ROOT / "review" / "full_field_redesign_iteration2_v1.py": "5df9e31df983516e015dec03c856f462e04e5bd63f50ac6616f367f5e64ab0ae",
}

# Only frozen, finalized official PRE roots are candidates.  A missing root is
# an explicit eligibility failure, never a reason to discover a replacement.
CANDIDATES: dict[str, str | None] = {
    "20260914": None,
    "20260919": "reports/daily_pre_prediction_20260919/current_frozen",
    "20260920": "reports/daily_pre_prediction_20260920/current_frozen",
    "20260921": "reports/daily_pre_analysis_20260921/current_frozen",
    "20260922": None,
    "20260926": "reports/daily_pre_analysis_20260926/current_frozen",
    "20260927": "reports/daily_pre_analysis_20260927/current_frozen",
    "20261003": "reports/daily_pre_analysis_20261003/current_frozen",
    "20261004": "reports/daily_pre_analysis_20261004/current_frozen",
    "20261010": "reports/daily_pre_analysis_20261010/current_frozen",
    "20261011": "reports/20261011_official_pre_v1/current_frozen",
    "20261012": "reports/20261012_official_pre_v1_retry4/current_frozen",
}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _date_iso(compact: str) -> str:
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"


def _date_compact(value: str) -> str:
    digits = value.replace("-", "")
    if len(digits) != 8 or not digits.isdigit():
        raise Stop(f"STOP_ADAPTIVE_DATE_INVALID:{value}")
    return digits


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _verify_forward_reference() -> None:
    for path, expected in EXPECTED_FORWARD.items():
        if not path.is_file() or sha(path) != expected:
            raise Stop(f"STOP_ADAPTIVE_FORWARD_REFERENCE_CHANGED:{_relative(path)}")
    if not all(hasattr(iter2, name) for name in ("valid_pl_races", "pl_fit", "pl_top3")):
        raise Stop("STOP_ADAPTIVE_VALIDATED_PL_SOURCE_UNRESOLVED")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Stop(f"STOP_ADAPTIVE_ARTIFACT_MALFORMED:{_relative(path)}") from error
    if not isinstance(value, dict):
        raise Stop(f"STOP_ADAPTIVE_ARTIFACT_MALFORMED:{_relative(path)}")
    return value


def _read_payloads(root: Path, date: str) -> list[dict[str, Any]]:
    index_path = root / "race_index.json"
    if not index_path.is_file():
        raise Stop("OFFICIAL_PRE_RACE_INDEX_MISSING")
    entries = _load_json(index_path).get("race_index")
    if not isinstance(entries, list) or not entries:
        raise Stop("OFFICIAL_PRE_RACE_INDEX_MALFORMED")
    payloads: list[dict[str, Any]] = []
    for entry in entries:
        artifact = entry.get("artifact") if isinstance(entry, dict) else None
        path = root / str(artifact or "")
        if not path.is_file():
            raise Stop("OFFICIAL_PRE_PAYLOAD_MISSING")
        payload = _load_json(path)
        race_id = str(payload.get("race_id", ""))
        if not race_id.startswith(f"race_{date}_"):
            raise Stop("OFFICIAL_PRE_DATE_IDENTITY_AMBIGUOUS")
        payloads.append(payload)
    return sorted(payloads, key=lambda item: str(item["race_id"]))


def _source_paths(manifest: dict[str, Any]) -> dict[str, Path]:
    sources = manifest.get("sources")
    if not isinstance(sources, dict) or set(sources) != {"DG", "DE", "DS"}:
        raise Stop("OFFICIAL_PRE_INPUT_MANIFEST_MALFORMED")
    paths: dict[str, Path] = {}
    for name in ("DG", "DE", "DS"):
        entry = sources[name]
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
            raise Stop("OFFICIAL_PRE_INPUT_MANIFEST_MALFORMED")
        path = ROOT / Path(entry["path"])
        if not path.is_file():
            raise Stop(f"PRE_SOURCE_MISSING:{name}")
        if sha(path) != entry["sha256"]:
            raise Stop(f"PRE_SOURCE_SHA_MISMATCH:{name}")
        paths[name] = path
    return paths


def _read_csv(path: Path, width: int) -> list[list[str]]:
    with path.open("r", encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows or any(len(row) != width for row in rows):
        raise Stop(f"STOP_ADAPTIVE_RAW_SCHEMA_INVALID:{path.name}")
    return rows


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="cp932", newline="") as handle:
        csv.writer(handle, lineterminator="\r\n").writerows(rows)


def _payloads_from_sources(date: str, manifest: dict[str, Any], paths: dict[str, Path]) -> list[dict[str, Any]]:
    """Regenerate exactly from manifest-authenticated source identities.

    The sole supported exception is an explicitly recorded whole-race source
    filter inside the frozen input manifest (currently 2026-10-12 Kyoto 8R).
    """
    temporary_filter = manifest.get("temporary_filtered_input")
    if temporary_filter is None:
        bundle = TargetBulkPredictionInputAdapterV1().load(paths["DG"], paths["DE"], paths["DS"])
        return [run_new(race_id, race, trace=True) for race_id, race in sorted(bundle.races.items())]
    if not isinstance(temporary_filter, dict) or temporary_filter.get("used") is not True:
        raise Stop("STOP_ADAPTIVE_TEMPORARY_FILTER_UNRESOLVED")
    exclusion = temporary_filter.get("exclusion")
    if not isinstance(exclusion, dict) or exclusion.get("human_approved") is not True or exclusion.get("scope") != "2026-10-12 OFFICIAL PRE ONLY":
        raise Stop("STOP_ADAPTIVE_TEMPORARY_FILTER_UNRESOLVED")
    if date != "20261012" or exclusion.get("race_id") != "race_20261012_kyoto_8R" or exclusion.get("venue") != "京都" or exclusion.get("race_number") != 8:
        raise Stop("STOP_ADAPTIVE_TEMPORARY_FILTER_UNRESOLVED")
    dg, de, ds = _read_csv(paths["DG"], 11), _read_csv(paths["DE"], 33), _read_csv(paths["DS"], 50)
    excluded_dg = lambda row: row[3].strip() == "京都" and int(row[4]) == 8
    filtered_dg = [row for row in dg if not excluded_dg(row)]
    filtered_de = [row for row in de if not (row[1].strip() == "京都" and int(row[2]) == 8)]
    clean = TargetBulkPredictionInputAdapterV1()._clean_name
    remaining_names = {clean(row[7]) for row in filtered_de}
    filtered_ds = [row for row in ds if clean(row[16]) in remaining_names]
    expected = temporary_filter.get("filtered_source_sha256")
    if not isinstance(expected, dict):
        raise Stop("STOP_ADAPTIVE_TEMPORARY_FILTER_UNRESOLVED")
    with tempfile.TemporaryDirectory(prefix="pl_adaptive_shadow_", dir=ROOT / ".tmp") as directory:
        directory_path = Path(directory)
        temporary = {name: directory_path / f"{name}{date[2:]}.CSV" for name in ("DG", "DE", "DS")}
        for name, rows in {"DG": filtered_dg, "DE": filtered_de, "DS": filtered_ds}.items():
            _write_csv(temporary[name], rows)
            if sha(temporary[name]) != expected.get(name):
                raise Stop(f"STOP_ADAPTIVE_TEMPORARY_FILTER_HASH_MISMATCH:{name}")
        bundle = TargetBulkPredictionInputAdapterV1().load(temporary["DG"], temporary["DE"], temporary["DS"])
        return [run_new(race_id, race, trace=True) for race_id, race in sorted(bundle.races.items())]


def _records_from_payloads(date: str, payloads: list[dict[str, Any]]) -> dict[tuple[str, str, int], np.ndarray]:
    records: dict[tuple[str, str, int], np.ndarray] = {}
    for payload in payloads:
        _, raw_rows = forward.feature_values_from_runtime(payload, date)
        for item in raw_rows:
            key = (date, str(item["race_id"]), int(item["horse_number"]))
            if key in records:
                raise Stop("STOP_ADAPTIVE_FEATURE_IDENTITY_DUPLICATE")
            records[key] = forward.canonical_vector(item["values"])
    return records


def _equivalence(date: str, path_a: list[dict[str, Any]], path_b: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[tuple[str, str, int], np.ndarray]]:
    a, b = _records_from_payloads(date, path_a), _records_from_payloads(date, path_b)
    if set(a) != set(b):
        return {"date": _date_iso(date), "horses": len(a), "feature_values": len(a) * 21, "differences": abs(len(a) - len(b)) * 21 or 1, "max_abs_diff": None, "feature_equivalence": "FAIL", "reason": "FEATURE_IDENTITY_SET_MISMATCH"}, a
    differences, maximum = 0, 0.0
    for key in sorted(a):
        delta = np.abs(a[key] - b[key])
        differences += int(np.count_nonzero(delta))
        maximum = max(maximum, float(np.max(delta)))
    return {"date": _date_iso(date), "horses": len(a), "feature_values": len(a) * 21, "differences": differences, "max_abs_diff": maximum, "feature_equivalence": "PASS" if differences == 0 else "FAIL"}, a


def _candidate_rows(date: str, payloads: list[dict[str, Any]], vectors: dict[tuple[str, str, int], np.ndarray]) -> list[dict[str, Any]]:
    results = result_rows(date)
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        race_id = str(payload["race_id"])
        parsed_date, venue_key, race_number = parse_race_id(race_id)
        if parsed_date != date or venue_key not in JAPANESE_VENUE:
            raise Stop("STOP_ADAPTIVE_RESULT_RACE_IDENTITY")
        result = results.get((JAPANESE_VENUE[venue_key], race_number))
        if result is None:
            raise Stop("STOP_ADAPTIVE_RESULT_RACE_UNMATCHED")
        _, raw_rows = forward.feature_values_from_runtime(payload, date)
        for item in raw_rows:
            horse_number = int(item["horse_number"])
            valid, finish, top3 = outcome(result, horse_number)
            vector = vectors[(date, race_id, horse_number)]
            rows.append({
                "date": date, "month": date[:6], "race_id": race_id, "venue": JAPANESE_VENUE[venue_key],
                "race_number": race_number, "horse_number": horse_number, "horse_name": item.get("horse_name"),
                "valid_result": bool(valid), "actual_finish": finish, "actual_top3": bool(top3) if valid else None,
                "features": [float(value) for value in vector],
            })
    _assert_unique(rows)
    return rows


def _assert_unique(rows: list[dict[str, Any]]) -> None:
    keys = [(str(row["date"]), str(row["race_id"]), int(row["horse_number"])) for row in rows]
    if len(set(keys)) != len(keys):
        raise Stop("STOP_ADAPTIVE_TRAINING_DUPLICATE_ROW")


def _special_mapping_record() -> dict[str, Any] | None:
    """No filename heuristics: return only an explicit approval record."""
    paths = tuple((ROOT / "docs").glob("**/*0921*0922*")) + tuple((ROOT / "reports").glob("**/*0921*0922*approval*"))
    for path in paths:
        if path.is_file() and "approved" in path.read_text(encoding="utf-8", errors="ignore").lower():
            return {"path": _relative(path), "sha256": sha(path)}
    return None


def _existing_success_dates() -> set[str]:
    if not LEDGER.is_file():
        return set()
    dates: set[str] = set()
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if value.get("activation_status") == "ACTIVATED":
            dates.update(_date_compact(item) for item in value.get("eligible_dates", []))
    return dates


def _preflight_date(date: str, relative_root: str, mapping: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]] | None, dict[str, Any] | None]:
    """One date's fail-closed feature/source/label preflight.

    A caller records this as ineligible rather than treating ordinary source
    availability/equivalence failures as model failures.
    """
    iso = _date_iso(date)
    if date in {"20260921", "20260922"} and mapping is None:
        return {"date": iso, "status": "SKIPPED_INELIGIBLE", "reason": "APPROVED_CANONICAL_0921_0922_MAPPING_MISSING"}, None, None
    root = ROOT / relative_root
    try:
        manifest_path = root / "input_manifest.json"
        if not manifest_path.is_file():
            raise Stop("OFFICIAL_PRE_INPUT_MANIFEST_MISSING")
        manifest = _load_json(manifest_path)
        if _date_compact(str(manifest.get("date", ""))) != date:
            raise Stop("OFFICIAL_PRE_INPUT_MANIFEST_DATE_MISMATCH")
        paths = _source_paths(manifest)
        path_a = _read_payloads(root, date)
        path_b = _payloads_from_sources(date, manifest, paths)
        equivalent, vectors = _equivalence(date, path_a, path_b)
        if equivalent["feature_equivalence"] != "PASS":
            return {"date": iso, "status": "SKIPPED_INELIGIBLE", "reason": "FEATURE_EQUIVALENCE_FAIL", "feature_equivalence": equivalent}, None, None
        rows = _candidate_rows(date, path_a, vectors)
        source = {"date": iso, "pre_root": relative_root, "input_manifest": _relative(manifest_path), "input_manifest_sha256": sha(manifest_path), "sources": {name: {"path": _relative(path), "sha256": sha(path)} for name, path in paths.items()}}
        return {"date": iso, "status": "ELIGIBLE", "feature_equivalence": equivalent, "training_rows": len(rows)}, rows, source
    except Stop as error:
        return {"date": iso, "status": "SKIPPED_INELIGIBLE", "reason": str(error)}, None, None


def preflight_candidates() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]], dict[str, Any] | None]:
    """Returns per-date audit, eligible training rows, source identity records, mapping."""
    used = _existing_success_dates()
    status: list[dict[str, Any]] = []
    eligible: dict[str, list[dict[str, Any]]] = {}
    sources: list[dict[str, Any]] = []
    mapping = _special_mapping_record()
    for date, relative_root in CANDIDATES.items():
        iso = _date_iso(date)
        if date in used:
            status.append({"date": iso, "status": "SKIPPED_INELIGIBLE", "reason": "ALREADY_SUCCESSFULLY_CONSUMED"})
            continue
        if relative_root is None:
            status.append({"date": iso, "status": "SKIPPED_INELIGIBLE", "reason": "OFFICIAL_PRE_ARTIFACT_MISSING"})
            continue
        item, rows, source = _preflight_date(date, relative_root, mapping)
        status.append(item)
        if rows is not None and source is not None:
            eligible[date] = rows; sources.append(source)
    return status, eligible, sources, mapping


def _base_rows() -> list[dict[str, Any]]:
    rows = [row for row in iter0.result_join(iter0.load_pre_rows()) if str(row["date"]) <= INITIAL_BASE_CUTOFF]
    dates = sorted({str(row["date"]) for row in rows})
    if len(dates) != 62 or dates[-1] != INITIAL_BASE_CUTOFF:
        raise Stop("STOP_ADAPTIVE_BASE_POPULATION_INVALID")
    _assert_unique(rows)
    return rows


def _training_identity(base: list[dict[str, Any]], added: dict[str, list[dict[str, Any]]], source_entries: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    base_manifest = _load_json(FORWARD_ROOT / "pl_forward_shadow_v1_manifest.json")
    result_files: list[dict[str, Any]] = []
    for date in sorted(added):
        paths = [ROOT / "data" / "raw" / "target" / "daily_result_list" / f"馬番順着順_{date}.csv", ROOT / "data" / "raw" / "target" / "daily_result_list" / f"着順馬番_{date}.csv"]
        for path in paths:
            if not path.is_file():
                raise Stop("STOP_ADAPTIVE_RESULT_SOURCE_MISSING")
            result_files.append({"path": _relative(path), "sha256": sha(path)})
    identity = {
        "base_forward_manifest_sha256": sha(FORWARD_ROOT / "pl_forward_shadow_v1_manifest.json"),
        "base_training_date_count": len({str(row["date"]) for row in base}),
        "eligible_pre_sources": source_entries,
        "eligible_result_sources": result_files,
        "pl_source_code_sha256": sha(ROOT / "review" / "full_field_redesign_iteration2_v1.py"),
    }
    return hashlib.sha256(canonical_bytes(identity)).hexdigest(), identity


def _model_value(scaler: Any, coefficients: np.ndarray, cutoff: str) -> dict[str, Any]:
    return {
        "model": "PL_ADAPTIVE_SHADOW_V1", "role": "ADAPTIVE_DEVELOPMENT_SHADOW", "training_cutoff": _date_iso(cutoff),
        "feature_model_version": "ITER0_VECTOR_21_PL_FIRST_19_V1", "pl_feature_names": list(forward.FEATURE_NAMES),
        "race_state_columns_excluded": ["PLAY_UNCONVERGED_4PLUS", "SKIP"],
        "scaler": {"mean": [float(item) for item in scaler.mean_], "scale": [float(item) for item in scaler.scale_]},
        "pl_coefficients": [float(item) for item in coefficients],
        "optimizer": {"method": "L-BFGS-B", "init": "zeros", "maxiter": 1000, "gtol": 1e-6, "gradient": "analytic", "l2": 0.0, "intercept": "NONE", "objective": "mean over valid races of Top3 partial likelihood"},
        "production_buy_override": False,
    }


def _assert_training_numerics(rows: list[dict[str, Any]], scaler: Any, coefficients: np.ndarray) -> None:
    matrix = np.asarray([row["features"] for row in rows], dtype=float)
    mean, scale = np.asarray(scaler.mean_, dtype=float), np.asarray(scaler.scale_, dtype=float)
    if matrix.shape[1] != 21 or mean.shape != (21,) or scale.shape != (21,) or coefficients.shape != (19,) or not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(mean)) or not np.all(np.isfinite(scale)) or np.any(scale == 0):
        raise Stop("STOP_ADAPTIVE_TRAINING_NUMERICAL_FAILURE")
    utilities = ((matrix - mean) / scale)[:, :19] @ coefficients
    if not np.all(np.isfinite(utilities)):
        raise Stop("STOP_ADAPTIVE_TRAINING_NUMERICAL_FAILURE")


def _numerical_smoke(model: dict[str, Any], *, payload_root: Path) -> dict[str, Any]:
    payloads = _read_payloads(payload_root, "20261012")
    features_one = [forward._payload_records(payload, "20261012") for payload in payloads]
    features_two = [forward._payload_records(payload, "20261012") for payload in payloads]
    if any(any(not np.array_equal(a["vector"], b["vector"]) for a, b in zip(one, two)) for one, two in zip(features_one, features_two)):
        raise Stop("STOP_ADAPTIVE_SMOKE_FEATURE_NONDETERMINISM")
    first = forward.infer_payloads(model, [("20261012", item) for item in payloads], model_sha256="SMOKE", input_pre_sha256="SMOKE")
    second = forward.infer_payloads(model, [("20261012", item) for item in payloads], model_sha256="SMOKE", input_pre_sha256="SMOKE")
    if canonical_bytes(first) != canonical_bytes(second):
        raise Stop("STOP_ADAPTIVE_SMOKE_INFERENCE_NONDETERMINISM")
    if any(race.get("inference_status") != "AVAILABLE" or abs(float(race["pl_probability_sum"]) - 3.0) > 1e-8 for race in first["races"]):
        raise Stop("STOP_ADAPTIVE_SMOKE_PROBABILITY_SUM")
    return {"feature_matrix_deterministic": True, "inference_byte_identical": True, "probability_sum_to_3": True, "race_count": len(first["races"])}


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(canonical_bytes(value)); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def _append_ledger(value: dict[str, Any]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("ab") as handle:
        handle.write(canonical_bytes(value)); handle.flush(); os.fsync(handle.fileno())


def _activation(model: dict[str, Any], manifest: dict[str, Any]) -> tuple[Path, str, str, str]:
    VERSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="candidate_", dir=VERSIONS_ROOT) as temporary_dir:
        temporary = Path(temporary_dir)
        model_path = temporary / "model.json"
        write_json(model_path, model)
        model_sha = sha(model_path)
        cutoff = _date_compact(str(model["training_cutoff"]))
        final = VERSIONS_ROOT / f"{cutoff}_{model_sha[:12]}"
        if final.exists():
            raise Stop("STOP_ADAPTIVE_VERSION_ALREADY_EXISTS")
        manifest = dict(manifest)
        manifest["model_artifact_sha256"] = model_sha
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        index_path = temporary / "sha256_index.json"
        write_json(index_path, {"self_hash_excluded": True, "artifacts": {"model.json": {"sha256": model_sha, "size": model_path.stat().st_size}, "manifest.json": {"sha256": sha(manifest_path), "size": manifest_path.stat().st_size}}})
        # Validate the immutable snapshot before publishing it.
        if _load_json(model_path).get("training_cutoff") != model["training_cutoff"] or not sha(index_path):
            raise Stop("STOP_ADAPTIVE_VERSION_VALIDATION_FAILED")
        os.replace(temporary, final)
    pointer = {"model": "PL_ADAPTIVE_SHADOW_V1", "role": "ADAPTIVE_DEVELOPMENT_SHADOW", "version_path": _relative(final), "model_sha256": model_sha, "manifest_sha256": sha(final / "manifest.json"), "training_cutoff": model["training_cutoff"], "production_buy_override": False}
    _atomic_write_json(CURRENT_POINTER, pointer)
    return final, model_sha, sha(final / "manifest.json"), sha(CURRENT_POINTER)


def initial_catchup() -> dict[str, Any]:
    _verify_forward_reference()
    if CURRENT_POINTER.exists():
        raise Stop("STOP_ADAPTIVE_INITIAL_CURRENT_POINTER_EXISTS")
    base = _base_rows()
    status, eligible, source_entries, mapping = preflight_candidates()
    rows = base + [row for date in sorted(eligible) for row in eligible[date]]
    _assert_unique(rows)
    if not eligible:
        raise Stop("STOP_ADAPTIVE_NO_ELIGIBLE_CATCHUP_DATES")
    scaler, coefficients, audit = iter2.pl_fit(rows)
    if not audit.get("optimizer_success") or coefficients.shape != (19,) or scaler.mean_.shape != (21,) or scaler.scale_.shape != (21,) or not np.all(np.isfinite(coefficients)) or not np.all(np.isfinite(scaler.mean_)) or not np.all(np.isfinite(scaler.scale_)) or np.any(np.asarray(scaler.scale_) == 0):
        raise Stop("STOP_ADAPTIVE_TRAINING_NUMERICAL_FAILURE")
    _assert_training_numerics(rows, scaler, coefficients)
    valid_races, excluded = iter2.valid_pl_races(rows)
    cutoff = max(eligible)
    identity_sha, identity = _training_identity(base, eligible, source_entries)
    model = _model_value(scaler, coefficients, cutoff)
    smoke = _numerical_smoke(model, payload_root=ROOT / "reports" / "20261012_official_pre_v1_retry4" / "current_frozen")
    manifest = {
        "model": model["model"], "role": model["role"], "training_cutoff": model["training_cutoff"],
        "initial_base_cutoff": _date_iso(INITIAL_BASE_CUTOFF), "initial_base_date_count": 62,
        "eligible_additional_dates": [_date_iso(date) for date in sorted(eligible)], "candidate_date_status": status,
        "training_dates": sorted({_date_iso(str(row["date"])) for row in rows}), "training_date_count": len({str(row["date"]) for row in rows}),
        "training_race_count": len({(str(row["date"]), str(row["race_id"])) for row in rows}), "training_row_count_total": len(rows),
        "training_valid_row_count": sum(bool(row["valid_result"]) for row in rows), "training_invalid_row_count": sum(not bool(row["valid_result"]) for row in rows),
        "valid_pl_race_count": len(valid_races), "excluded_pl_races": excluded, "feature_order": forward.feature_schema(),
        "training_input_sha256": identity_sha, "training_input_identity": identity, "pl_source_code_sha256": sha(ROOT / "review" / "full_field_redesign_iteration2_v1.py"),
        "optimizer_result": audit, "numerical_smoke": smoke, "special_0921_0922_mapping": mapping,
        "auto_training": True, "auto_shadow_activation": True, "auto_production_promotion": False, "production_buy_override": False,
        "performance_evaluation_executed": False,
    }
    previous = None
    try:
        final, model_sha, manifest_sha, pointer_sha = _activation(model, manifest)
        activation = "ACTIVATED"; failure = None
    except Exception as error:
        activation = "ABORT"; failure = str(error); final = None; model_sha = None; manifest_sha = None; pointer_sha = sha(CURRENT_POINTER) if CURRENT_POINTER.exists() else None
    ledger = {"update_timestamp": _utc_now(), "candidate_result_dates": [_date_iso(date) for date in CANDIDATES], "eligible_dates": [_date_iso(date) for date in sorted(eligible)], "skipped_ineligible_dates": [item["date"] for item in status if item["status"] == "SKIPPED_INELIGIBLE"], "skip_reasons": {item["date"]: item.get("reason") for item in status if item["status"] == "SKIPPED_INELIGIBLE"}, "previous_model_sha": previous, "candidate_model_sha": model_sha, "training_cutoff": _date_iso(cutoff), "training_date_count": manifest["training_date_count"], "training_race_count": manifest["training_race_count"], "training_row_count_total": len(rows), "training_valid_row_count": manifest["training_valid_row_count"], "optimizer_success": bool(audit.get("optimizer_success")), "smoke_status": "PASS", "activation_status": activation, "failure_reason": failure}
    _append_ledger(ledger)
    if activation != "ACTIVATED":
        raise Stop(f"STOP_ADAPTIVE_ACTIVATION_ABORT:{failure}")
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    summary = {"implementation_status": "COMPLETE", "candidate_status": status, "eligible_dates": [_date_iso(date) for date in sorted(eligible)], "version_path": _relative(final), "model_sha256": model_sha, "manifest_sha256": manifest_sha, "current_pointer_sha256": pointer_sha, "training_input_sha256": identity_sha, "smoke": smoke, "special_0921_0922_mapping": mapping, "performance_evaluation_executed": False}
    write_json(REPORT_ROOT / "initial_catchup_summary.json", summary)
    write_json(REPORT_ROOT / "artifact_hashes.json", {"self_hash_excluded": True, "artifacts": {"initial_catchup_summary.json": {"sha256": sha(REPORT_ROOT / "initial_catchup_summary.json"), "size": (REPORT_ROOT / "initial_catchup_summary.json").stat().st_size}, "update_ledger.jsonl": {"sha256": sha(LEDGER), "size": LEDGER.stat().st_size}}})
    return summary


def update_completed_date(date_value: str, official_pre_root: str) -> dict[str, Any]:
    """One future completed-date update, for the scheduler/operations caller.

    It reconstructs every previously eligible date from its authenticated PRE
    source manifest before performing a full refit.  Therefore no online
    coefficient update or history-dependent shortcut is possible.
    """
    _verify_forward_reference()
    date = _date_compact(date_value)
    pointer, _, _ = _load_current_once()
    if date in _existing_success_dates():
        raise Stop("STOP_ADAPTIVE_DATE_ALREADY_CONSUMED")
    if date <= _date_compact(str(pointer["training_cutoff"])):
        raise Stop("STOP_ADAPTIVE_DATE_NOT_AFTER_CURRENT_CUTOFF")
    current_manifest = _load_json(ROOT / str(pointer["version_path"]) / "manifest.json")
    previous_sources = current_manifest.get("training_input_identity", {}).get("eligible_pre_sources")
    if not isinstance(previous_sources, list):
        raise Stop("STOP_ADAPTIVE_CURRENT_MANIFEST_INVALID")
    status: list[dict[str, Any]] = []
    eligible: dict[str, list[dict[str, Any]]] = {}
    sources: list[dict[str, Any]] = []
    mapping = _special_mapping_record()
    for entry in previous_sources:
        if not isinstance(entry, dict) or not isinstance(entry.get("date"), str) or not isinstance(entry.get("pre_root"), str):
            raise Stop("STOP_ADAPTIVE_CURRENT_MANIFEST_INVALID")
        previous_date = _date_compact(entry["date"])
        item, rows, source = _preflight_date(previous_date, entry["pre_root"], mapping)
        if rows is None or source is None:
            raise Stop(f"STOP_ADAPTIVE_PREVIOUS_ELIGIBLE_DATE_INVALID:{previous_date}:{item.get('reason')}")
        status.append(item); eligible[previous_date] = rows; sources.append(source)
    new_item, new_rows, new_source = _preflight_date(date, official_pre_root, mapping)
    status.append(new_item)
    if new_rows is None or new_source is None:
        _append_ledger({"update_timestamp": _utc_now(), "candidate_result_dates": [_date_iso(date)], "eligible_dates": [], "skipped_ineligible_dates": [_date_iso(date)], "skip_reasons": {_date_iso(date): new_item.get("reason")}, "previous_model_sha": pointer["model_sha256"], "candidate_model_sha": None, "training_cutoff": pointer["training_cutoff"], "training_date_count": current_manifest.get("training_date_count"), "training_race_count": current_manifest.get("training_race_count"), "training_row_count_total": current_manifest.get("training_row_count_total"), "training_valid_row_count": current_manifest.get("training_valid_row_count"), "optimizer_success": False, "smoke_status": "NOT_RUN", "activation_status": "SKIPPED_INELIGIBLE", "failure_reason": new_item.get("reason")})
        return {"status": "SKIPPED_INELIGIBLE", "date": _date_iso(date), "reason": new_item.get("reason"), "previous_model_kept": True}
    eligible[date] = new_rows; sources.append(new_source)
    base = _base_rows(); rows = base + [row for item_date in sorted(eligible) for row in eligible[item_date]]
    _assert_unique(rows)
    scaler, coefficients, audit = iter2.pl_fit(rows)
    if not audit.get("optimizer_success") or not np.all(np.isfinite(coefficients)) or not np.all(np.isfinite(scaler.mean_)) or not np.all(np.isfinite(scaler.scale_)):
        raise Stop("STOP_ADAPTIVE_TRAINING_NUMERICAL_FAILURE")
    _assert_training_numerics(rows, scaler, coefficients)
    valid_races, excluded = iter2.valid_pl_races(rows)
    identity_sha, identity = _training_identity(base, eligible, sources)
    model = _model_value(scaler, coefficients, date)
    smoke = _numerical_smoke(model, payload_root=ROOT / "reports" / "20261012_official_pre_v1_retry4" / "current_frozen")
    manifest = {"model": model["model"], "role": model["role"], "training_cutoff": model["training_cutoff"], "initial_base_cutoff": _date_iso(INITIAL_BASE_CUTOFF), "initial_base_date_count": 62, "eligible_additional_dates": [_date_iso(item_date) for item_date in sorted(eligible)], "candidate_date_status": status, "training_dates": sorted({_date_iso(str(row["date"])) for row in rows}), "training_date_count": len({str(row["date"]) for row in rows}), "training_race_count": len({(str(row["date"]), str(row["race_id"])) for row in rows}), "training_row_count_total": len(rows), "training_valid_row_count": sum(bool(row["valid_result"]) for row in rows), "training_invalid_row_count": sum(not bool(row["valid_result"]) for row in rows), "valid_pl_race_count": len(valid_races), "excluded_pl_races": excluded, "feature_order": forward.feature_schema(), "training_input_sha256": identity_sha, "training_input_identity": identity, "pl_source_code_sha256": sha(ROOT / "review" / "full_field_redesign_iteration2_v1.py"), "optimizer_result": audit, "numerical_smoke": smoke, "auto_training": True, "auto_shadow_activation": True, "auto_production_promotion": False, "production_buy_override": False, "performance_evaluation_executed": False}
    final, model_sha, manifest_sha, pointer_sha = _activation(model, manifest)
    _append_ledger({"update_timestamp": _utc_now(), "candidate_result_dates": [_date_iso(date)], "eligible_dates": [_date_iso(date)], "skipped_ineligible_dates": [], "skip_reasons": {}, "previous_model_sha": pointer["model_sha256"], "candidate_model_sha": model_sha, "training_cutoff": _date_iso(date), "training_date_count": manifest["training_date_count"], "training_race_count": manifest["training_race_count"], "training_row_count_total": len(rows), "training_valid_row_count": manifest["training_valid_row_count"], "optimizer_success": True, "smoke_status": "PASS", "activation_status": "ACTIVATED", "failure_reason": None})
    return {"status": "ACTIVATED", "date": _date_iso(date), "version_path": _relative(final), "model_sha256": model_sha, "manifest_sha256": manifest_sha, "current_pointer_sha256": pointer_sha}


def _load_current_once() -> tuple[dict[str, Any], dict[str, Any], str]:
    if not CURRENT_POINTER.is_file():
        raise Stop("STOP_ADAPTIVE_CURRENT_MODEL_MISSING")
    pointer = _load_json(CURRENT_POINTER)
    version = ROOT / str(pointer.get("version_path", ""))
    model_path = version / "model.json"
    if not model_path.is_file() or sha(model_path) != pointer.get("model_sha256"):
        raise Stop("STOP_ADAPTIVE_CURRENT_POINTER_INVALID")
    return pointer, _load_json(model_path), sha(CURRENT_POINTER)


def ensure_cutoff_before(training_cutoff: str, target_date: str) -> None:
    """The single no-same-day / no-past-date guard used by the real runner."""
    if _date_compact(training_cutoff) >= _date_compact(target_date):
        raise Stop("STOP_ADAPTIVE_MODEL_CUTOFF_NOT_BEFORE_TARGET")


def adaptive_inference(input_current_root: Path, output: Path, target_date: str) -> dict[str, Any]:
    """Forward-only runner; read the active pointer exactly once."""
    pointer, model, pointer_sha = _load_current_once()
    target = _date_compact(target_date)
    ensure_cutoff_before(str(pointer["training_cutoff"]), target)
    if output.exists():
        raise Stop("STOP_ADAPTIVE_OUTPUT_EXISTS")
    payloads = _read_payloads(input_current_root, target)
    value = forward.infer_payloads(model, [(target, item) for item in payloads], model_sha256=str(pointer["model_sha256"]), input_pre_sha256=sha(input_current_root / "prediction_manifest.json"))
    value.update({"model": "PL_ADAPTIVE_SHADOW_V1", "role": "ADAPTIVE_DEVELOPMENT_SHADOW", "adaptive_model_sha256": pointer["model_sha256"], "adaptive_training_cutoff": pointer["training_cutoff"], "current_pointer_sha256": pointer_sha, "production_buy_override": False})
    for row in value["horses"]:
        row.update({"model": "PL_ADAPTIVE_SHADOW_V1", "role": "ADAPTIVE_DEVELOPMENT_SHADOW", "training_cutoff": pointer["training_cutoff"], "adaptive_model_sha256": pointer["model_sha256"], "production_buy_override": False})
    write_json(output, value)
    return {"output": _relative(output), "sha256": sha(output), "race_count": len(value["races"]), "training_cutoff": pointer["training_cutoff"]}


def _cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial-catchup", action="store_true")
    parser.add_argument("--infer", action="store_true")
    parser.add_argument("--update-date")
    parser.add_argument("--official-pre-root")
    parser.add_argument("--input-root")
    parser.add_argument("--output")
    parser.add_argument("--target-date")
    args = parser.parse_args()
    if args.initial_catchup:
        print(json.dumps(initial_catchup(), ensure_ascii=False, sort_keys=True))
    elif args.infer:
        if not args.input_root or not args.output or not args.target_date:
            raise SystemExit("--infer requires --input-root --output --target-date")
        print(json.dumps(adaptive_inference(ROOT / args.input_root, ROOT / args.output, args.target_date), ensure_ascii=False, sort_keys=True))
    elif args.update_date:
        if not args.official_pre_root:
            raise SystemExit("--update-date requires --official-pre-root")
        print(json.dumps(update_completed_date(args.update_date, args.official_pre_root), ensure_ascii=False, sort_keys=True))
    else:
        raise SystemExit("select --initial-catchup, --update-date, or --infer")


if __name__ == "__main__":
    _cli()
