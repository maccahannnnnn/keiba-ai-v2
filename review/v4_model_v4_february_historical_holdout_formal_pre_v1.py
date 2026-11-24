"""Formal PRE-only freeze for the V4 Model v4 February historical holdout.

This runner contains no Result-reader imports.  It verifies the frozen Phase
A-1 sources, runs the approved Current prediction path, then records only the
same-volume V4 selection required for a later separately authorized POST.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import scipy
import sklearn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.date_exclusivity_validator_v1 import collect_evidence_dates, validate
from review.prospective_prediction_runner_v1 import _assert_population, run as current_run
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


OUT = ROOT / "reports/v4_model_v4_february_historical_holdout/formal_pre"
PREFLIGHT = ROOT / "reports/v4_model_v4_february_historical_holdout/preflight/phase_a1_retry_after_reacquisition_v1"
RAW = ROOT / "data/raw/prediction_input"
MODEL = ROOT / "reports/ml_v4_buy_selection_model_v4"
DATASET = ROOT / "reports/ml_v4_buy_selection_dataset_v4"
DATES = ["20260201", "20260207", "20260208", "20260210", "20260214", "20260215", "20260221", "20260222", "20260228"]
ROLE = "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V4"
SEMANTIC = ["Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle", "shadow_ai_rank", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count", "consensus_negative_count", "risk_count", "conflict_count", "race_state"]
TRANSFORMED = [*SEMANTIC[:-1], "is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"]
GATES = set(SEMANTIC[11:15])
EXPECTED = {
    "model.joblib": "58d3977d0f44eab325a2b384f0c17b66ddc276fff6370f6e05b7a1680642d74f",
    "scaler.joblib": "3d18757f4991c21a4a645f92ca26361d88c030a4097696d2cc4a6c86d3767b90",
    "selected_feature_columns.json": "acf79da95865cc087cead024280f04baa4eeda2b98911c2aa21be9c010af3c5d",
}
DATASET_SHA = "b02bb4b59b5f297e60964f96050890dbf32a7ac3b5a9ef93424b9d612e3ae80a"
RESULT_KEYS = {"finish", "finishing_position", "result", "actual_top3", "payout", "winner", "success", "failure", "lift", "valid_result"}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def safe_rank(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise Stop(f"SAFE_SHADOW_AI_RANK_INVALID:{context}")
    value = int(value)
    if value < 1:
        raise Stop(f"SAFE_SHADOW_AI_RANK_INVALID:{context}")
    return value


def gate_value(value: object, context: str) -> float:
    if value is True:
        return 1.0
    if value is False:
        return 0.0
    raise Stop(f"FEATURE_BOOLEAN_INVALID:{context}")


def feature_vector(horse: dict, trace: dict, state: str, context: str) -> list[float]:
    snapshot = trace.get("evaluator_score_snapshot")
    if not isinstance(snapshot, dict):
        raise Stop(f"EVALUATOR_SNAPSHOT_INVALID:{context}")
    values = []
    evaluator_fields = {"Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle"}
    for field in SEMANTIC[:-1]:
        value = snapshot.get(field) if field in evaluator_fields else horse.get(field, trace.get(field))
        if field in GATES:
            values.append(gate_value(value, f"{context}:{field}"))
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise Stop(f"FEATURE_INVALID:{context}:{field}")
            values.append(float(value))
    values.extend([float(state == "PLAY_UNCONVERGED_4PLUS"), float(state == "SKIP")])
    if len(values) != 21:
        raise Stop(f"FEATURE_WIDTH_INVALID:{context}")
    return values


def race_parts(race_id: str) -> tuple[str, int]:
    pieces = race_id.split("_")
    if len(pieces) < 4 or not pieces[-1].endswith("R"):
        raise Stop(f"RACE_ID_PARSE_INVALID:{race_id}")
    return pieces[-2], int(pieces[-1][:-1])


def scan_result_fields(value: object, context: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in RESULT_KEYS:
                raise Stop(f"PRE_RESULT_FIELD_FORBIDDEN:{context}:{key}")
            scan_result_fields(child, context)
    elif isinstance(value, list):
        for child in value:
            scan_result_fields(child, context)


def verify_index(index_path: Path) -> None:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    entries = payload.get("indexed_artifacts")
    if not isinstance(entries, dict):
        raise Stop(f"AUTHORITY_HASH_INDEX_INVALID:{index_path}")
    for relative, digest in entries.items():
        path = index_path.parent / relative
        if not path.is_file() or sha(path) != digest:
            raise Stop(f"AUTHORITY_HASH_INDEX_MISMATCH:{index_path}:{relative}")


def verify_authority() -> dict[str, Any]:
    for root in (MODEL, DATASET):
        verify_index(root / "artifact_hashes.json")
    observed = {name: sha(MODEL / name) for name in EXPECTED}
    if any(observed[name] != expected for name, expected in EXPECTED.items()):
        raise Stop("FROZEN_MODEL_AUTHORITY_HASH_MISMATCH")
    dataset_observed = sha(DATASET / "dataset.csv")
    if dataset_observed != DATASET_SHA:
        raise Stop("FROZEN_DATASET_AUTHORITY_HASH_MISMATCH")
    transform = json.loads((MODEL / "feature_transform_schema.json").read_text(encoding="utf-8"))
    selected = json.loads((MODEL / "selected_feature_columns.json").read_text(encoding="utf-8"))
    if transform.get("transformed_model_input_columns") != TRANSFORMED or transform.get("transformed_input_count") != 21:
        raise Stop("V4_TRANSFORM_SCHEMA_MISMATCH")
    if selected.get("semantic_selected_columns") != SEMANTIC or selected.get("relative_gap_status") != "AVAILABLE_BUT_NOT_SELECTED_FOR_MODEL_V4":
        raise Stop("V4_SELECTED_FEATURE_SCHEMA_MISMATCH")
    return {"model_sha256": observed["model.joblib"], "scaler_sha256": observed["scaler.joblib"], "selected_feature_columns_sha256": observed["selected_feature_columns.json"], "dataset_v4_sha256": dataset_observed, "semantic_feature_count": 20, "transformed_feature_count": 21, "relative_gap_status": "AVAILABLE_BUT_NOT_SELECTED_FOR_MODEL_V4", "relative_gap_used_for_inference": False}


def verify_sources() -> list[dict[str, Any]]:
    integrity = json.loads((PREFLIGHT / "dg_de_ds_reconciliation.json").read_text(encoding="utf-8"))
    safety = json.loads((PREFLIGHT / "safety_phase_a1.json").read_text(encoding="utf-8"))
    population = json.loads((PREFLIGHT / "source_population_inventory.json").read_text(encoding="utf-8"))
    if integrity.get("status") != "PASS" or safety.get("status") != "PASS" or population.get("totals", {}).get("source_races_total") != 160 or population.get("totals", {}).get("source_horses_total") != 2209:
        raise Stop("PHASE_A1_AUTHORITY_INVALID")
    raw = json.loads((PREFLIGHT / "raw_source_hashes.json").read_text(encoding="utf-8")).get("hashes")
    if not isinstance(raw, list) or len(raw) != 27:
        raise Stop("PHASE_A1_RAW_SOURCE_HASHES_INVALID")
    verified = []
    for item in raw:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["byte_size"] or sha(path) != item["sha256"]:
            raise Stop(f"FROZEN_SOURCE_MISMATCH:{item.get('filename')}")
        verified.append({"date": item["date"], "source_type": item["source_type"], "path": item["path"], "byte_size": item["byte_size"], "sha256": item["sha256"]})
    if sorted({row["date"] for row in verified}) != DATES:
        raise Stop("FROZEN_DATE_SET_MISMATCH")
    return verified


def runtime() -> dict[str, str]:
    actual = {"python_executable": sys.executable, "python_version": sys.version, "implementation": platform.python_implementation(), "numpy": np.__version__, "scikit_learn": sklearn.__version__, "scipy": scipy.__version__, "joblib": joblib.__version__}
    expected = {"numpy": "2.3.5", "scikit_learn": "1.9.0", "scipy": "1.18.1", "joblib": "1.5.3"}
    if any(actual[key] != value for key, value in expected.items()):
        raise Stop("V4_RUNTIME_INCOMPATIBLE")
    actual["compatibility"] = "PASS"
    return actual


def all_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file() and path.name != "artifact_hashes.json"}


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    source_rows = verify_sources()
    authority = verify_authority()
    run_time = runtime()
    exclusivity = validate(DATES, collect_evidence_dates(ROOT))
    if exclusivity.get("status") != "PASS":
        raise Stop("DATE_EXCLUSIVITY_CONFLICT")
    result_root = ROOT / "data/raw/target/daily_result_list"
    result_file_names = sorted(path.name for path in result_root.glob("*202602*.csv")) if result_root.is_dir() else []
    if result_file_names:
        raise Stop("UNEXPECTED_FEBRUARY_RESULT_FILE_PRESENT")

    adapter = TargetBulkPredictionInputAdapterV1()
    registration: dict[tuple[str, int, str], str] = {}
    source_races = source_horses = 0
    venue_counts: dict[str, int] = {}
    population_dates = []
    for date in DATES:
        paths = {kind: RAW / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
        bundle = adapter.load(paths["DG"], paths["DE"], paths["DS"])
        if bundle.date != date:
            raise Stop(f"TARGET_DATE_MISMATCH:{date}:{bundle.date}")
        _assert_population(bundle)
        day = []
        for race_id, race in sorted(bundle.races.items()):
            venue, number = race_parts(race_id)
            count = len(race.today_entries)
            source_races += 1; source_horses += count; venue_counts[venue] = venue_counts.get(venue, 0) + 1
            day.append({"race_id": race_id, "venue": venue, "race_number": number, "source_horse_count": count})
            for (horse_number, horse_name), registration_id in race.target_horse_identifiers.items():
                registration[(race_id, int(horse_number), horse_name)] = registration_id
        population_dates.append({"date": date, "race_count": len(day), "horse_count": sum(row["source_horse_count"] for row in day), "races": day})
    if (source_races, source_horses) != (160, 2209):
        raise Stop(f"SOURCE_POPULATION_MUTATION:{source_races}:{source_horses}")

    OUT.mkdir(parents=True)
    model, scaler = joblib.load(MODEL / "model.joblib"), joblib.load(MODEL / "scaler.joblib")
    if getattr(model, "n_features_in_", None) != 21 or getattr(scaler, "n_features_in_", None) != 21:
        raise Stop("MODEL_FEATURE_WIDTH_MISMATCH")

    current_records, inference_records, eligible, selection_audit = [], [], [], []
    current_roots = {}
    state_counts = {state: 0 for state in ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP")}
    current_buy_total = 0
    for date in DATES:
        root = current_run(date, trace=True, output_root=OUT / "current_ai" / date)
        current_roots[date] = root
        prediction_manifest = json.loads((root / "prediction_manifest.json").read_text(encoding="utf-8"))
        for item in prediction_manifest.get("files", []):
            artifact = root / item["relative_path"]
            if not artifact.is_file() or sha(artifact) != item["sha256"]:
                raise Stop(f"CURRENT_PREDICTION_MANIFEST_MISMATCH:{date}:{item.get('relative_path')}")
        race_index = json.loads((root / "race_index.json").read_text(encoding="utf-8")).get("race_index")
        if not isinstance(race_index, list):
            raise Stop(f"CURRENT_RACE_INDEX_INVALID:{date}")
        for item in race_index:
            payload = json.loads((root / item["artifact"]).read_text(encoding="utf-8"))
            scan_result_fields(payload, payload.get("race_id", date))
            race_id = payload["race_id"]; venue, race_number = race_parts(race_id)
            ranked, top5 = payload["ranked_results"], payload["top5"]
            trace = payload.get("buy_gate_trace")
            if not isinstance(trace, dict) or not isinstance(trace.get("race"), dict) or not isinstance(trace.get("horses"), list):
                raise Stop(f"BUY_GATE_TRACE_REQUIRED:{race_id}")
            state = trace["race"].get("shadow_race_state")
            if state not in state_counts:
                raise Stop(f"RACE_STATE_INVALID:{race_id}:{state}")
            state_counts[state] += 1
            traces = {int(row["horse_number"]): row for row in trace["horses"]}
            if set(traces) != {int(row["horse_number"]) for row in ranked}:
                raise Stop(f"TRACE_HORSE_SET_MISMATCH:{race_id}")
            current_buys = [row for row in ranked if row.get("buy") is True]
            if len(current_buys) > 3:
                raise Stop(f"CURRENT_BUY_VOLUME_OUT_OF_RANGE:{race_id}")
            current_buy_total += len(current_buys)
            current_selection = [{"horse_number": int(row["horse_number"]), "horse_name": row.get("horse_name"), "registration_id": registration.get((race_id, int(row["horse_number"]), row.get("horse_name")))} for row in current_buys]
            if any(row["registration_id"] is None for row in current_selection):
                raise Stop(f"CURRENT_REGISTRATION_ID_UNRESOLVED:{race_id}")
            current_records.append({"date": date, "race_id": race_id, "venue": venue, "race_number": race_number, "race_state": state, "current_buy_count": len(current_selection), "current_buy_horses": current_selection, "source_prediction_root": str(root.relative_to(ROOT)), "source_prediction_manifest_sha256": sha(root / "prediction_manifest.json")})
            if state != "PLAY_CONVERGED":
                continue
            vectors = []
            for horse in top5:
                number = int(horse["horse_number"])
                vectors.append((horse, traces[number], feature_vector(horse, traces[number], state, f"{race_id}:{number}")))
            probabilities = model.predict_proba(scaler.transform(np.asarray([row[2] for row in vectors], dtype=float)))[:, 1]
            ordered = sorted([
                {"horse_number": int(horse["horse_number"]), "horse_name": horse.get("horse_name"), "registration_id": registration.get((race_id, int(horse["horse_number"]), horse.get("horse_name")),), "predicted_top3_probability": float(probability), "shadow_ai_rank": safe_rank(trace_row.get("shadow_ai_rank"), f"{race_id}:{horse['horse_number']}")}
                for (horse, trace_row, _), probability in zip(vectors, probabilities, strict=True)
            ], key=lambda row: (-row["predicted_top3_probability"], row["shadow_ai_rank"], row["horse_number"]))
            if any(row["registration_id"] is None for row in ordered):
                raise Stop(f"V4_REGISTRATION_ID_UNRESOLVED:{race_id}")
            inference_records.append({"date": date, "race_id": race_id, "venue": venue, "race_number": race_number, "race_state": state, "top5_probabilities": ordered})
            if not current_selection:
                continue
            selected = ordered[:len(current_selection)]
            current_numbers, v4_numbers = [row["horse_number"] for row in current_selection], [row["horse_number"] for row in selected]
            current_only, v4_only = sorted(set(current_numbers) - set(v4_numbers)), sorted(set(v4_numbers) - set(current_numbers))
            if len(selected) != len(current_selection):
                raise Stop(f"SAME_VOLUME_MISMATCH:{race_id}")
            if len(current_only) != len(v4_only):
                raise Stop(f"SELECTION_SET_ASYMMETRY:{race_id}")
            if len(current_only) > 3:
                raise Stop(f"REPLACEMENT_DEPTH_OUT_OF_RANGE:{race_id}")
            record = {"date": date, "race_id": race_id, "venue": venue, "race_number": race_number, "race_state": state, "current_buy_count": len(current_selection), "current_selected_horses": current_selection, "v4_selected_horses": selected, "same_volume_count": len(selected), "overlap_count": len(set(current_numbers) & set(v4_numbers)), "current_only_count": len(current_only), "v4_only_count": len(v4_only), "replacement_depth": len(current_only), "current_only_horse_numbers": current_only, "v4_only_horse_numbers": v4_only}
            eligible.append(record)
            selection_audit.append(record)

    if len(current_records) != 160:
        raise Stop("CURRENT_RACE_POPULATION_MISMATCH")
    if sum(record["current_buy_count"] for record in eligible) != sum(record["same_volume_count"] for record in eligible):
        raise Stop("TOTAL_SAME_VOLUME_MISMATCH")
    scan_result_fields([current_records, inference_records, eligible], "formal_pre_output")
    replacement = {str(depth): sum(record["replacement_depth"] == depth for record in eligible) for depth in range(4)}
    volumes = {str(volume): sum(record["current_buy_count"] == volume for record in eligible) for volume in range(1, 4)}
    eligible_dates = sorted({record["date"] for record in eligible})
    gate = {"eligible_races_min": 20, "independent_dates_min": 4, "pooled_same_volume_lift_min_percentage_points": 0.0, "eligible_races_frozen": len(eligible), "independent_dates_frozen": len(eligible_dates), "minimum_evidence_status": "PASS" if len(eligible) >= 20 and len(eligible_dates) >= 4 else "HISTORICAL_HOLDOUT_INSUFFICIENT_MINIMUM_EVIDENCE", "post_metric_evaluation": "NOT_EVALUATED_PRE_ONLY"}

    write(OUT / "source_authority.json", {"artifact_type": "FEBRUARY_FORMAL_PRE_SOURCE_AUTHORITY_V1", "evidence_role": ROLE, "candidate_dates": DATES, "source_population": {"races": 160, "horses": 2209}, "phase_a1_root": str(PREFLIGHT.relative_to(ROOT)), "verified_sources": source_rows, "date_exclusivity": {"status": exclusivity["status"], "overlap_count": exclusivity["overlap_count"]}, "raw_source_mutation_count": 0})
    write(OUT / "current_prediction.json", {"artifact_type": "FEBRUARY_CURRENT_PREDICTION_PRE_FREEZE_V1", "current_buy_semantics": "Existing approved Current AI; no rule or threshold changes", "race_state_counts": state_counts, "current_buy_positive_race_count": sum(record["current_buy_count"] > 0 for record in current_records), "current_buy_horse_count": current_buy_total, "races": current_records})
    write(OUT / "v4_prediction.json", {"artifact_type": "FEBRUARY_V4_MODEL_V4_INFERENCE_PRE_FREEZE_V1", "evidence_role": ROLE, "model_authority": authority, "inference_scope": "PLAY_CONVERGED Top5 only", "inference_records": inference_records, "relative_gap_used_for_inference": False, "model_fit_count": 0, "scaler_fit_count": 0})
    write(OUT / "formal_eligible_population.json", {"artifact_type": "FEBRUARY_FORMAL_ELIGIBLE_POPULATION_V1", "eligibility": "PLAY_CONVERGED AND Current BUY >= 1", "eligible_race_count": len(eligible), "eligible_date_count": len(eligible_dates), "eligible_dates": eligible_dates, "eligible_races": eligible})
    write(OUT / "same_volume_audit.json", {"artifact_type": "FEBRUARY_SAME_VOLUME_AUDIT_V1", "comparator": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "rule": "V4 selection volume equals Current BUY count for each formal eligible race", "current_selected_total": sum(record["current_buy_count"] for record in eligible), "v4_selected_total": sum(record["same_volume_count"] for record in eligible), "per_race": [{key: record[key] for key in ("date", "race_id", "venue", "race_number", "current_buy_count", "same_volume_count")} for record in eligible], "status": "PASS"})
    write(OUT / "selection_set_audit.json", {"artifact_type": "FEBRUARY_SELECTION_SET_AUDIT_V1", "ordering": ["predicted P(actual_top3) DESC", "safe shadow_ai_rank ASC", "horse_number ASC"], "selection_set_records": selection_audit, "current_only_equals_v4_only": True, "status": "PASS"})
    write(OUT / "replacement_depth_preregistration.json", {"artifact_type": "FEBRUARY_REPLACEMENT_DEPTH_PREREGISTRATION_V1", "status": "PREREGISTERED_DIAGNOSTIC_NON_GATE", "definition": "current_only_count", "categories": [0, 1, 2, 3], "distribution": replacement, "per_race": [{key: record[key] for key in ("date", "race_id", "replacement_depth", "overlap_count", "current_buy_count")} for record in eligible]})
    write(OUT / "buy_volume_preregistration.json", {"artifact_type": "FEBRUARY_BUY_VOLUME_PREREGISTRATION_V1", "status": "PREREGISTERED_DIAGNOSTIC_NON_GATE", "definition": "Current BUY count per formal eligible race", "categories": [1, 2, 3], "distribution": volumes})
    write(OUT / "historical_gate_freeze.json", {"artifact_type": "FEBRUARY_HISTORICAL_GATE_FREEZE_V1", "gate": gate, "gate_definition": "eligible races >=20 AND independent dates >=4 AND pooled same-volume lift >=0.0pt", "result_access_before_gate": 0})
    write(OUT / "temporal_diagnostic_freeze.json", {"artifact_type": "FEBRUARY_TEMPORAL_DIAGNOSTIC_FREEZE_V1", "status": "POST_ONLY_NON_GATE_NOT_EXECUTED", "lodo": "Leave one independent date out", "concentration_stress": {"date_contribution": "V4 hits - Current hits", "sort": ["contribution DESC", "date ASC"], "remove_date_count": "ceil(independent_dates / 3)", "remaining_reporting": ["Current valid N/hits/rate", "V4 valid N/hits/rate", "raw hit difference", "lift"]}})
    write(OUT / "invalid_result_semantics.json", {"artifact_type": "FEBRUARY_INVALID_RESULT_SEMANTICS_FREEZE_V1", "phase": "POST_ONLY_NOT_EXECUTED", "rule": "Rows classified invalid in authorized POST are excluded from the valid denominator and displayed separately as invalid_selected_count.", "result_access_count": 0})
    write(OUT / "result_access_audit.json", {"artifact_type": "FEBRUARY_FORMAL_PRE_RESULT_ACCESS_AUDIT_V1", "february_result_file_name_count": 0, "result_file_contents_read": False, "result_importer_execution_count": 0, "finish_access_count": 0, "actual_top3_access_count": 0, "result_data_access_count": 0, "status": "PASS"})
    write(OUT / "evidence_boundary.json", {"artifact_type": "FEBRUARY_FORMAL_PRE_EVIDENCE_BOUNDARY_V1", "evidence_role": ROLE, "not_prospective_evidence": True, "purpose": "Backward temporal generalization only", "forbidden": ["result access", "POST", "performance metric", "thresholding", "refit", "Current BUY rule change", "relative gap selection"], "formal_post_authorized": False})
    safety = {"artifact_type": "FEBRUARY_FORMAL_PRE_SAFETY_V1", "status": "PASS", "result_data_access_count": 0, "finish_access_count": 0, "actual_top3_access_count": 0, "adapter_execution_count": len(DATES), "prediction_execution_count": len(DATES), "current_buy_generation_count": len(DATES), "model_v4_inference_race_count": len(inference_records), "model_fit_count": 0, "scaler_fit_count": 0, "production_change_count": 0, "current_ai_change_count": 0, "buy_gate_change_count": 0, "cf_change_count": 0, "v4_model_mutation_count": 0, "source_raw_mutation_count": 0, "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    write(OUT / "safety.json", safety)
    manifest = {"artifact_type": "FEBRUARY_FORMAL_PRE_FREEZE_MANIFEST_V1", "final_status": "FEBRUARY_2026_FORMAL_PRE = FROZEN_PENDING_INDEPENDENT_REVIEW", "created_at": started, "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "evidence_role": ROLE, "candidate_dates": DATES, "source_population": {"races": 160, "horses": 2209}, "source_sha_references": str((PREFLIGHT / "raw_source_hashes.json").relative_to(ROOT)), "model_authority": authority, "protocol": {"current_buy_semantics": "Existing approved Current AI", "eligibility": "PLAY_CONVERGED AND Current BUY >= 1", "comparator": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "same_volume_rule": "Current BUY count per race", "selection_order": ["predicted P(actual_top3) DESC", "safe shadow_ai_rank ASC", "horse_number ASC"], "replacement_depth": "current_only_count; bins 0/1/2/3", "buy_volume": "Current BUY count; bins 1/2/3", "historical_gate": gate}, "result_access_count": 0, "formal_post_authorized": False, "git_head": safety["git_head"], "runtime": run_time, "artifact_hash_index": "artifact_hashes.json", "claude_independent_february_pre_review_required": True}
    write(OUT / "pre_freeze_manifest.json", manifest)
    report = ["# February 2026 V4 Model v4 Historical Holdout — Formal PRE Freeze", "", f"- Final: `FROZEN_PENDING_INDEPENDENT_REVIEW`", f"- Evidence role: `{ROLE}`", f"- Candidate dates / source races / horses: `{len(DATES)} / 160 / 2209`", f"- Race states: `{state_counts}`", f"- Current BUY-positive races / horses: `{sum(record['current_buy_count'] > 0 for record in current_records)} / {current_buy_total}`", f"- Formal eligible races / dates: `{len(eligible)} / {len(eligible_dates)}`", f"- Same-volume Current / V4 selections: `{sum(record['current_buy_count'] for record in eligible)} / {sum(record['same_volume_count'] for record in eligible)}`", f"- replacement_depth distribution: `{replacement}`", f"- buy_volume distribution: `{volumes}`", "- Result access: `0`", "", "## Formal eligible races", ""]
    for record in eligible:
        current = ", ".join(f"{row['horse_number']} {row['horse_name']}" for row in record["current_selected_horses"])
        v4 = ", ".join(f"{row['horse_number']} {row['horse_name']} ({row['predicted_top3_probability']:.6f})" for row in record["v4_selected_horses"])
        report.extend([f"- `{record['date']} {record['venue']} {record['race_number']}R` | Current: {current} | V4: {v4} | depth={record['replacement_depth']}"])
    report.extend(["", "POST and February Result access are prohibited pending Claude Code's independent PRE review."])
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    write(OUT / "artifact_hashes.json", {"artifact_type": "FEBRUARY_FORMAL_PRE_HASH_INDEX_V1", "indexed_artifacts": all_hashes(OUT), "self_hash_excluded": True})
    index = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
    if any(sha(OUT / relative) != digest for relative, digest in index.items()):
        raise Stop("FORMAL_PRE_ARTIFACT_HASH_MISMATCH")
    print("FEBRUARY_2026_FORMAL_PRE=FROZEN_PENDING_INDEPENDENT_REVIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
