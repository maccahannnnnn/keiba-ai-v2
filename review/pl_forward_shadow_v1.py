"""Frozen Plackett--Luce development-shadow trainer and PRE-only runner.

The PL optimizer and exact Top3 probability implementation are imported from
the validated Iteration 2 runner.  This module only freezes a full-period
model and applies the same 19-dimensional feature projection to PRE payloads.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from review import full_field_redesign_iter0_retry7 as iter0
from review import full_field_redesign_iteration2_v1 as iter2
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new
from review.ws2_deterministic_pre_only_regeneration_v1 import feature_values_from_runtime


ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "models" / "pl_forward_shadow_v1"
REPORT_ROOT = ROOT / "reports" / "pl_forward_shadow_v1"
ITER2_SOURCE = ROOT / "review" / "full_field_redesign_iteration2_v1.py"
PRE_SHARD_ROOT = ROOT / "reports" / "full_field_redesign_iter0_v1_retry6" / "pre_only_regeneration" / "shards"
TRAINING_CUTOFF = "2026-09-13"
TRAINING_CUTOFF_COMPACT = "20260913"
MODEL_FILE = "pl_forward_shadow_v1_model.json"
MANIFEST_FILE = "pl_forward_shadow_v1_manifest.json"
FEATURE_NAMES = tuple(iter0.FEATURES[:-1])
GATE_FEATURES = {
    "absolute_quality_pass",
    "relative_advantage_pass",
    "effective_reliability_pass",
    "risk_guard_pass",
}
VALID_RACE_STATES = {"PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"}
EXPECTED_ITER2_SOURCE_PREFIX = "5df9e31d"


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_bytes(value))


def date_list_sha(dates: list[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(set(dates))) + "\n").encode("utf-8")).hexdigest()


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or value is None:
        raise Stop(f"MISSING_REQUIRED_FEATURE:{field}")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise Stop(f"MISSING_REQUIRED_FEATURE:{field}") from error
    if not math.isfinite(number):
        raise Stop(f"MISSING_REQUIRED_FEATURE:{field}")
    return number


def canonical_vector(values: dict[str, Any]) -> np.ndarray:
    """The exact Iter0 21-dimensional transform, with explicit missing checks."""
    for name in FEATURE_NAMES:
        if name in GATE_FEATURES:
            if not isinstance(values.get(name), bool):
                raise Stop(f"MISSING_REQUIRED_FEATURE:{name}")
        else:
            _finite_number(values.get(name), name)
    if values.get("race_state") not in VALID_RACE_STATES:
        raise Stop("MISSING_REQUIRED_FEATURE:race_state")
    vector = np.asarray(iter0.vector({"values": values}), dtype=float)
    if vector.shape != (21,) or not np.all(np.isfinite(vector)):
        raise Stop("STOP_PL_FORWARD_FEATURE_VECTOR_INVALID")
    return vector


def feature_schema() -> list[dict[str, Any]]:
    derivation: dict[str, str] = {
        "Ability": "buy_gate_trace.horses[].evaluator_score_snapshot.Ability",
        "PastPerformance": "buy_gate_trace.horses[].evaluator_score_snapshot.PastPerformance",
        "Distance": "buy_gate_trace.horses[].evaluator_score_snapshot.Distance",
        "CourseShape": "buy_gate_trace.horses[].evaluator_score_snapshot.CourseShape",
        "LapSuitability": "buy_gate_trace.horses[].evaluator_score_snapshot.LapSuitability",
        "RaceShape": "buy_gate_trace.horses[].evaluator_score_snapshot.RaceShape",
        "PaceStyle": "buy_gate_trace.horses[].evaluator_score_snapshot.PaceStyle",
        "shadow_ai_rank": "buy_gate_trace.horses[].shadow_ai_rank",
        "decision_score": "buy_gate_trace.horses[].decision_score",
        "final_score": "buy_gate_trace.horses[].final_score",
        "adjusted_score": "buy_gate_trace.horses[].adjusted_score",
        "absolute_quality_pass": "buy_gate_trace.horses[].absolute_quality_pass",
        "relative_advantage_pass": "buy_gate_trace.horses[].relative_advantage_pass",
        "effective_reliability_pass": "buy_gate_trace.horses[].effective_reliability_pass",
        "risk_guard_pass": "buy_gate_trace.horses[].risk_guard_pass",
        "consensus_positive_count": "buy_gate_trace.horses[].positive_count",
        "consensus_negative_count": "buy_gate_trace.horses[].negative_count",
        "risk_count": "ranked_results[].risk_count",
        "conflict_count": "ranked_results[].conflict_count",
    }
    return [{"index": index, "name": name, "source_derivation": derivation[name]} for index, name in enumerate(FEATURE_NAMES)]


def _hash_files(paths: list[Path]) -> tuple[str, list[dict[str, Any]]]:
    entries = [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "bytes": path.stat().st_size} for path in paths]
    return hashlib.sha256(canonical_bytes(entries)).hexdigest(), entries


def _training_source_identity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    shards = sorted(PRE_SHARD_ROOT.glob("run_c_*/runtime_pre_only_output.json"))
    if len(shards) != 31:
        raise Stop(f"STOP_PL_FORWARD_PRE_SHARD_COUNT:{len(shards)}")
    shard_sha, shard_entries = _hash_files(shards)
    result_files: list[Path] = []
    dates = sorted({str(row["date"]) for row in rows})
    for date in dates:
        for filename in (f"馬番順着順_{date}.csv", f"着順馬番_{date}.csv"):
            path = ROOT / "data" / "raw" / "target" / "daily_result_list" / filename
            if not path.is_file():
                raise Stop(f"STOP_PL_FORWARD_RESULT_SOURCE_MISSING:{filename}")
            result_files.append(path)
    result_sha, result_entries = _hash_files(result_files)
    return {
        "frozen_pre_shards": {"aggregate_sha256": shard_sha, "files": shard_entries},
        "training_result_sources": {"aggregate_sha256": result_sha, "files": result_entries},
        "iteration2_validated_source": {"path": str(ITER2_SOURCE.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(ITER2_SOURCE)},
    }


def train_model() -> dict[str, Any]:
    if MODEL_ROOT.exists():
        raise Stop("STOP_PL_FORWARD_MODEL_ROOT_EXISTS")
    source_sha = sha(ITER2_SOURCE)
    if not source_sha.startswith(EXPECTED_ITER2_SOURCE_PREFIX):
        raise Stop("STOP_VALIDATED_PL_SOURCE_UNRESOLVED")
    if not all(hasattr(iter2, name) for name in ("valid_pl_races", "pl_fit", "pl_top3")):
        raise Stop("STOP_VALIDATED_PL_SOURCE_UNRESOLVED")

    # This is the approved full-period development population.  Labels are
    # joined only for dates at or before the explicit cutoff.
    pre_rows = iter0.load_pre_rows()
    joined = [row for row in iter0.result_join(pre_rows) if str(row["date"]) <= TRAINING_CUTOFF_COMPACT]
    dates = sorted({str(row["date"]) for row in joined})
    if not joined or any(str(row["date"]) > TRAINING_CUTOFF_COMPACT for row in joined):
        raise Stop("STOP_PL_FORWARD_CUTOFF_VIOLATION")
    if any(np.asarray(row["features"], dtype=float).shape != (21,) or not np.all(np.isfinite(np.asarray(row["features"], dtype=float))) for row in joined):
        raise Stop("STOP_PL_FORWARD_FEATURE_VECTOR_INVALID")

    scaler, coefficients, audit = iter2.pl_fit(joined)
    if not audit.get("optimizer_success") or not np.all(np.isfinite(coefficients)):
        raise Stop("STOP_PL_FORWARD_TRAINING_NUMERICAL_FAILURE")
    if not np.all(np.isfinite(scaler.mean_)) or not np.all(np.isfinite(scaler.scale_)):
        raise Stop("STOP_PL_FORWARD_TRAINING_NUMERICAL_FAILURE")
    if coefficients.shape != (19,) or scaler.mean_.shape != (21,) or scaler.scale_.shape != (21,):
        raise Stop("STOP_PL_FORWARD_TRAINING_NUMERICAL_FAILURE")

    valid_races, excluded_races = iter2.valid_pl_races(joined)
    source = _training_source_identity(joined)
    model = {
        "model": "PL_FORWARD_SHADOW_V1",
        "role": "DEVELOPMENT_SHADOW_ONLY",
        "training_cutoff": TRAINING_CUTOFF,
        "feature_model_version": "ITER0_VECTOR_21_PL_FIRST_19_V1",
        "pl_feature_names": list(FEATURE_NAMES),
        "race_state_columns_excluded": ["PLAY_UNCONVERGED_4PLUS", "SKIP"],
        "scaler": {"mean": [float(value) for value in scaler.mean_], "scale": [float(value) for value in scaler.scale_]},
        "pl_coefficients": [float(value) for value in coefficients],
        "optimizer": {"method": "L-BFGS-B", "init": "zeros", "maxiter": 1000, "gtol": 1e-6, "gradient": "analytic", "l2": 0.0, "intercept": "NONE", "objective": "mean over valid races of Top3 partial likelihood"},
    }
    manifest = {
        "model": model["model"], "role": model["role"], "training_cutoff": TRAINING_CUTOFF,
        "training_dates": dates, "training_date_count": len(dates), "training_race_count": len({(row["date"], row["race_id"]) for row in joined}),
        "training_row_count": len(joined), "training_valid_row_count": sum(bool(row["valid_result"]) for row in joined),
        "training_invalid_row_count": sum(not bool(row["valid_result"]) for row in joined),
        "valid_pl_race_count": len(valid_races), "excluded_pl_races": excluded_races,
        "feature_order": feature_schema(), "pl_source_code_sha256": source_sha,
        "training_sources": source, "optimizer_result": audit,
        "production_override": False, "formal_evidence": False, "production_evidence": False,
        "results_after_cutoff_used_for_training": False,
    }
    MODEL_ROOT.mkdir(parents=True)
    model_path = MODEL_ROOT / MODEL_FILE
    write_json(model_path, model)
    manifest["model_artifact_sha256"] = sha(model_path)
    manifest_path = MODEL_ROOT / MANIFEST_FILE
    write_json(manifest_path, manifest)
    index = {path.name: {"sha256": sha(path), "size": path.stat().st_size} for path in (model_path, manifest_path)}
    write_json(MODEL_ROOT / "artifact_hashes.json", {"self_hash_excluded": True, "artifacts": index})
    return {"model_path": model_path, "manifest_path": manifest_path, "model_sha256": sha(model_path), "manifest_sha256": sha(manifest_path), "audit": audit, "dates": dates, "races": manifest["training_race_count"], "rows": len(joined)}


def load_model() -> tuple[dict[str, Any], str]:
    path = MODEL_ROOT / MODEL_FILE
    if not path.is_file():
        raise Stop("STOP_PL_FORWARD_MODEL_MISSING")
    model = json.loads(path.read_text(encoding="utf-8"))
    if tuple(model.get("pl_feature_names", [])) != FEATURE_NAMES:
        raise Stop("STOP_PL_FORWARD_FEATURE_ORDER_MISMATCH")
    if model.get("training_cutoff") != TRAINING_CUTOFF or model.get("role") != "DEVELOPMENT_SHADOW_ONLY":
        raise Stop("STOP_PL_FORWARD_MODEL_MANIFEST_INVALID")
    return model, sha(path)


def _payload_records(payload: dict[str, Any], target_date: str) -> list[dict[str, Any]]:
    _, raw_rows = feature_values_from_runtime(payload, target_date)
    records = []
    for item in raw_rows:
        vector = canonical_vector(item["values"])
        records.append({"date": target_date, "race_id": item["race_id"], "horse_number": int(item["horse_number"]), "horse_name": item.get("horse_name"), "vector": vector})
    return records


def infer_records(model: dict[str, Any], records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    if len(records) < 3:
        raise Stop("MISSING_REQUIRED_FEATURE:FIELD_LT_3")
    matrix = np.vstack([row["vector"] for row in records])
    mean = np.asarray(model["scaler"]["mean"], dtype=float)
    scale = np.asarray(model["scaler"]["scale"], dtype=float)
    coefficients = np.asarray(model["pl_coefficients"], dtype=float)
    if matrix.shape[1] != 21 or mean.shape != (21,) or scale.shape != (21,) or coefficients.shape != (19,) or not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(mean)) or not np.all(np.isfinite(scale)) or np.any(scale == 0):
        raise Stop("STOP_PL_FORWARD_TRAINING_NUMERICAL_FAILURE")
    probabilities, total = iter2.pl_top3((matrix - mean) / scale, coefficients)
    if abs(total - 3.0) > 1e-8 or not np.all(np.isfinite(probabilities)):
        raise Stop("STOP_PL_FORWARD_TOP3_SUM_FAILURE")
    ranked = sorted(range(len(records)), key=lambda index: (-float(probabilities[index]), records[index]["horse_number"]))
    ranks = {index: rank for rank, index in enumerate(ranked, start=1)}
    rows = []
    for index, record in enumerate(records):
        rows.append({
            "date": record["date"], "race_id": record["race_id"], "horse_number": record["horse_number"], "horse_name": record["horse_name"],
            "pl_top3_probability": float(probabilities[index]), "pl_race_rank": ranks[index], "inference_status": "AVAILABLE",
        })
    return rows, total


def _unavailable_records(payload: dict[str, Any], target_date: str, reason: str) -> list[dict[str, Any]]:
    ranked = payload.get("ranked_results")
    if not isinstance(ranked, list):
        raise Stop("STOP_RUNTIME_PAYLOAD_MALFORMED")
    return [{"date": target_date, "race_id": payload.get("race_id"), "horse_number": int(row["horse_number"]), "horse_name": row.get("horse_name"), "pl_top3_probability": None, "pl_race_rank": None, "inference_status": "INFERENCE_UNAVAILABLE", "reason": reason} for row in ranked]


def infer_payloads(model: dict[str, Any], payloads: list[tuple[str, dict[str, Any]]], *, model_sha256: str, input_pre_sha256: str, created_at: str | None = None) -> dict[str, Any]:
    output_rows: list[dict[str, Any]] = []
    races: list[dict[str, Any]] = []
    for target_date, payload in sorted(payloads, key=lambda item: (item[0], str(item[1].get("race_id", "")))):
        try:
            rows, probability_sum = infer_records(model, _payload_records(payload, target_date))
            races.append({"date": target_date, "race_id": payload["race_id"], "inference_status": "AVAILABLE", "pl_probability_sum": probability_sum})
        except Stop as error:
            rows = _unavailable_records(payload, target_date, str(error))
            races.append({"date": target_date, "race_id": payload.get("race_id"), "inference_status": "INFERENCE_UNAVAILABLE", "reason": str(error)})
        output_rows.extend(rows)
    if races and all(race["inference_status"] == "AVAILABLE" for race in races):
        ordered = sorted(range(len(output_rows)), key=lambda index: (-float(output_rows[index]["pl_top3_probability"]), output_rows[index]["date"], output_rows[index]["race_id"], output_rows[index]["horse_number"]))
        for rank, index in enumerate(ordered, start=1):
            output_rows[index]["pl_daily_global_rank"] = rank
    for row in output_rows:
        row.update({"model": "PL_FORWARD_SHADOW_V1", "role": "DEVELOPMENT_SHADOW_ONLY", "production_buy_override": False, "feature_model_version": model["feature_model_version"], "model_sha256": model_sha256})
    return {
        "model": "PL_FORWARD_SHADOW_V1", "role": "DEVELOPMENT_SHADOW_ONLY", "created_at": created_at,
        "input_pre_artifact_sha256": input_pre_sha256, "model_sha256": model_sha256,
        "result_fields_used": False, "production_buy_override": False,
        "races": races, "horses": output_rows,
    }


def run_inference(input_current_root: Path, output: Path, *, created_at: str | None = None) -> dict[str, Any]:
    if output.exists():
        raise Stop("STOP_PL_FORWARD_OUTPUT_EXISTS")
    index_path = input_current_root / "race_index.json"
    input_manifest = input_current_root / "prediction_manifest.json"
    if not index_path.is_file() or not input_manifest.is_file():
        raise Stop("STOP_PL_FORWARD_INPUT_ARTIFACT_MISSING")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entries = index.get("race_index")
    if not isinstance(entries, list) or not entries:
        raise Stop("STOP_PL_FORWARD_INPUT_ARTIFACT_MALFORMED")
    payloads = []
    for entry in entries:
        path = input_current_root / str(entry.get("artifact", ""))
        if not path.is_file():
            raise Stop("STOP_PL_FORWARD_INPUT_ARTIFACT_MISSING")
        payload = json.loads(path.read_text(encoding="utf-8"))
        race_id = str(payload.get("race_id", ""))
        date = race_id.split("_")[1] if race_id.startswith("race_") else ""
        if not date.isdigit():
            raise Stop("STOP_PL_FORWARD_INPUT_ARTIFACT_MALFORMED")
        payloads.append((date, payload))
    model, model_sha = load_model()
    value = infer_payloads(model, payloads, model_sha256=model_sha, input_pre_sha256=sha(input_manifest), created_at=created_at)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, value)
    return {"output": output, "sha256": sha(output), "available_races": sum(item["inference_status"] == "AVAILABLE" for item in value["races"]), "race_count": len(value["races"])}


def _read_csv(path: Path, width: int) -> list[list[str]]:
    with path.open("r", encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows or any(len(row) != width for row in rows):
        raise Stop(f"STOP_PL_FORWARD_RAW_SCHEMA_INVALID:{path.name}")
    return rows


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="cp932", newline="") as handle:
        csv.writer(handle, lineterminator="\r\n").writerows(rows)


def _official_20261012_raw_payloads(input_current_root: Path) -> list[tuple[str, dict[str, Any]]]:
    """Recreate the authorized whole-race Kyoto 8R exclusion only for equivalence."""
    date = "20261012"
    raw = ROOT / "data" / "raw" / "prediction_input"
    source = {name: raw / f"{name}{date[2:]}.CSV" for name in ("DG", "DE", "DS")}
    dg, de, ds = _read_csv(source["DG"], 11), _read_csv(source["DE"], 33), _read_csv(source["DS"], 50)
    excluded = lambda row: row[3].strip() == "京都" and int(row[4]) == 8
    filtered_dg = [row for row in dg if not excluded(row)]
    filtered_de = [row for row in de if not (row[1].strip() == "京都" and int(row[2]) == 8)]
    clean = TargetBulkPredictionInputAdapterV1()._clean_name
    remaining = {clean(row[7]) for row in filtered_de}
    filtered_ds = [row for row in ds if clean(row[16]) in remaining]
    temporary_root = ROOT / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pl_forward_shadow_v1_", dir=temporary_root) as directory:
        temporary = Path(directory)
        paths = {name: temporary / f"{name}{date[2:]}.CSV" for name in source}
        for name, rows in {"DG": filtered_dg, "DE": filtered_de, "DS": filtered_ds}.items():
            _write_csv(paths[name], rows)
        bundle = TargetBulkPredictionInputAdapterV1().load(paths["DG"], paths["DE"], paths["DS"])
        payloads = [(date, run_new(race_id, race, trace=True)) for race_id, race in sorted(bundle.races.items())]
    return payloads


def smoke_20261012() -> dict[str, Any]:
    if REPORT_ROOT.exists():
        raise Stop("STOP_PL_FORWARD_REPORT_ROOT_EXISTS")
    input_root = ROOT / "reports" / "20261012_official_pre_v1_retry4" / "current_frozen"
    index = json.loads((input_root / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    path_a = [("20261012", json.loads((input_root / entry["artifact"]).read_text(encoding="utf-8"))) for entry in index]
    path_b = _official_20261012_raw_payloads(input_root)
    a = {(date, item["race_id"], item["horse_number"]): item["vector"] for date, payload in path_a for item in _payload_records(payload, date)}
    b = {(date, item["race_id"], item["horse_number"]): item["vector"] for date, payload in path_b for item in _payload_records(payload, date)}
    if set(a) != set(b):
        raise Stop("STOP_PL_FORWARD_FEATURE_EQUIVALENCE_IDENTITY")
    differences = []
    max_abs = 0.0
    for key in sorted(a):
        for index, (left, right) in enumerate(zip(a[key], b[key])):
            diff = abs(float(left) - float(right)); max_abs = max(max_abs, diff)
            if diff != 0.0:
                differences.append({"date": key[0], "race_id": key[1], "horse_number": key[2], "feature_index": index, "path_a": float(left), "path_b": float(right)})
    if differences:
        raise Stop("STOP_PL_FORWARD_FEATURE_EQUIVALENCE")
    REPORT_ROOT.mkdir(parents=True)
    equivalence = {"date": "2026-10-12", "feature_equivalence_horses": len(a), "feature_equivalence_total_values": len(a) * 21, "feature_equivalence_differences": 0, "max_abs_diff": max_abs, "status": "PASS", "path_a": "official PRE artifact -> feature_values_from_runtime", "path_b": "canonical DG/DE/DS -> run_new(trace=True) -> feature_values_from_runtime", "result_access": False}
    write_json(REPORT_ROOT / "feature_equivalence_20261012.json", equivalence)
    model, model_sha = load_model()
    input_sha = sha(input_root / "prediction_manifest.json")
    fixed_created_at = "2026-10-12T00:00:00Z"
    left = infer_payloads(model, path_a, model_sha256=model_sha, input_pre_sha256=input_sha, created_at=fixed_created_at)
    right = infer_payloads(model, path_a, model_sha256=model_sha, input_pre_sha256=input_sha, created_at=fixed_created_at)
    run_a, run_b = REPORT_ROOT / "real_pre_smoke_20261012_run_a.json", REPORT_ROOT / "real_pre_smoke_20261012_run_b.json"
    write_json(run_a, left); write_json(run_b, right)
    if run_a.read_bytes() != run_b.read_bytes():
        raise Stop("STOP_PL_FORWARD_REAL_PRE_NONDETERMINISTIC")
    if any(item["inference_status"] != "AVAILABLE" or abs(float(item["pl_probability_sum"]) - 3.0) > 1e-8 for item in left["races"]):
        raise Stop("STOP_PL_FORWARD_REAL_PRE_SMOKE")
    summary = {"synthetic_smoke": "RUN_BY_UNIT_TEST", "real_pre_smoke": "PASS", "feature_equivalence": equivalence, "run_a_sha256": sha(run_a), "run_b_sha256": sha(run_b), "byte_identical": True, "pl_sum_to_3": "PASS", "result_access": False, "performance_evaluation_executed": False}
    write_json(REPORT_ROOT / "real_pre_smoke_summary.json", summary)
    index_value = {path.name: {"sha256": sha(path), "size": path.stat().st_size} for path in sorted(REPORT_ROOT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}
    write_json(REPORT_ROOT / "artifact_hashes.json", {"self_hash_excluded": True, "artifacts": index_value})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--smoke-20261012", action="store_true")
    parser.add_argument("--infer-input-current-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--created-at")
    args = parser.parse_args()
    selected = sum(bool(value) for value in (args.train, args.smoke_20261012, args.infer_input_current_root))
    if selected != 1:
        raise Stop("STOP_PL_FORWARD_EXACTLY_ONE_MODE_REQUIRED")
    if args.train:
        result = train_model(); print(json.dumps({"PL_FORWARD_SHADOW_V1_TRAINING": "COMPLETE", "model_sha256": result["model_sha256"]}, ensure_ascii=False))
    elif args.smoke_20261012:
        print(json.dumps(smoke_20261012(), ensure_ascii=False))
    else:
        if args.output is None:
            raise Stop("STOP_PL_FORWARD_OUTPUT_REQUIRED")
        print(json.dumps(run_inference(args.infer_input_current_root, args.output, created_at=args.created_at), ensure_ascii=False))


if __name__ == "__main__":
    main()
