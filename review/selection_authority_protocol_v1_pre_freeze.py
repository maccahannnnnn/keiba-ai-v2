"""Frozen Selection Authority Protocol V1, additive technical wiring only.

This module deliberately owns its feature helpers.  It must never inherit
selection semantics from the mutable daily-V4 runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "docs" / "selection_authority_protocol_v1.json"
FROZEN_PROTOCOL_SHA256 = "01bad1cc325f0ec1e35cb149bc65e20c07582c6d4013f0e344c0d521bb21106f"
MODEL_ROOT = ROOT / "reports" / "ml_v4_buy_selection_model_v5"
FROZEN_MODEL_SHA256 = "d3b17e3022768690d0b1013ab131b35c5a64aa8e4a816fb3e1349bad95fb87a2"
FROZEN_SCALER_SHA256 = "2855f19c43b0fc70e106a85a2c61716d532694c90efc42580b937d5d7bab504d"
FROZEN_SCHEMA_SHA256 = "f50039929b823f2821b4bde6a0cdc41f8be1c4c45cb55682c8a312e811e112c0"
SEMANTIC = [
    "Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability",
    "RaceShape", "PaceStyle", "shadow_ai_rank", "decision_score", "final_score",
    "adjusted_score", "absolute_quality_pass", "relative_advantage_pass",
    "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count",
    "consensus_negative_count", "risk_count", "conflict_count", "race_state",
]
TRANSFORMED = [*SEMANTIC[:-1], "is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"]
GATES = set(SEMANTIC[11:15])
RESULT_KEYS = {"actual_finish", "finish", "actual_top3", "valid_result", "result", "payout", "odds", "popularity", "hit", "success"}


class Stop(RuntimeError):
    """Fail-closed protocol error.  Race errors never emit partial horses."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _assert_result_free(value: object, context: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in RESULT_KEYS:
                raise Stop(f"PRE_RESULT_FIELD_FORBIDDEN:{context}:{key}")
            _assert_result_free(child, context)
    elif isinstance(value, list):
        for child in value:
            _assert_result_free(child, context)


def boolean(value: object, context: str) -> int:
    if value is True:
        return 1
    if value is False:
        return 0
    raise Stop(f"FEATURE_BOOLEAN_INVALID:{context}")


def safe_rank(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise Stop(f"V4_SAFE_RANK_INVALID:{context}:{value!r}")
    rank = int(value)
    if rank < 1 or float(value) != float(rank):
        raise Stop(f"V4_SAFE_RANK_INVALID:{context}:{value!r}")
    return rank


def frozen_local_vector(horse: dict[str, Any], trace: dict[str, Any], state: str, context: str) -> list[float]:
    """Frozen local reproduction of V5's 21-column transform, not an import."""
    snapshot = trace.get("evaluator_score_snapshot", {})
    if not isinstance(snapshot, dict):
        raise Stop(f"EVALUATOR_SNAPSHOT_INVALID:{context}")
    values: list[float] = []
    for field in SEMANTIC[:-1]:
        value = snapshot.get(field) if field in {"Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle"} else horse.get(field, trace.get(field))
        if field in GATES:
            values.append(float(boolean(value, f"{context}:{field}")))
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise Stop(f"FEATURE_INVALID:{context}:{field}")
            values.append(float(value))
    values.extend([float(state == "PLAY_UNCONVERGED_4PLUS"), float(state == "SKIP")])
    if len(values) != 21:
        raise Stop(f"FEATURE_VECTOR_LENGTH_INVALID:{context}:{len(values)}")
    return values


def load_frozen_protocol() -> dict[str, Any]:
    if not PROTOCOL_PATH.is_file() or sha256(PROTOCOL_PATH) != FROZEN_PROTOCOL_SHA256:
        raise Stop("PROTOCOL_SHA_MISMATCH")
    payload = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    contract = payload.get("model_contract", {})
    feature = payload.get("feature_contract", {})
    if contract.get("model_sha256") != FROZEN_MODEL_SHA256 or contract.get("scaler_sha256") != FROZEN_SCALER_SHA256:
        raise Stop("PROTOCOL_MODEL_CONTRACT_MISMATCH")
    if feature.get("feature_schema_sha256") != FROZEN_SCHEMA_SHA256:
        raise Stop("PROTOCOL_FEATURE_CONTRACT_MISMATCH")
    return payload


def load_frozen_v5(protocol: dict[str, Any]) -> tuple[object, object, dict[str, str]]:
    """Load the protocol-pinned V5 artifact; no active-daily loader is used."""
    contract = protocol["model_contract"]
    feature = protocol["feature_contract"]
    model_path, scaler_path, schema_path = MODEL_ROOT / "model.joblib", MODEL_ROOT / "scaler.joblib", MODEL_ROOT / "feature_transform_schema.json"
    metadata_path = MODEL_ROOT / "model_metadata.json"
    if sha256(model_path) != contract["model_sha256"]:
        raise Stop("MODEL_SHA_MISMATCH")
    if sha256(scaler_path) != contract["scaler_sha256"]:
        raise Stop("SCALER_SHA_MISMATCH")
    if sha256(schema_path) != feature["feature_schema_sha256"]:
        raise Stop("FEATURE_SCHEMA_SHA_MISMATCH")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    actual_model_version = _validated_model_version(metadata, contract)
    if metadata.get("model_sha256") != contract["model_sha256"]:
        raise Stop("MODEL_SHA_MISMATCH")
    if metadata.get("scaler_sha256") != contract["scaler_sha256"]:
        raise Stop("SCALER_SHA_MISMATCH")
    if metadata.get("training_end_date") != contract["training_cutoff"]:
        raise Stop("TRAINING_CUTOFF_MISMATCH")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if schema.get("transformed_model_input_columns") != TRANSFORMED:
        raise Stop("FEATURE_SCHEMA_SHA_MISMATCH")
    try:
        model, scaler = joblib.load(model_path), joblib.load(scaler_path)
    except Exception as exc:  # pragma: no cover - platform-specific joblib failures
        raise Stop("MODEL_LOAD_FAILURE") from exc
    if getattr(model, "n_features_in_", None) != 21 or getattr(scaler, "n_features_in_", None) != 21:
        raise Stop("FEATURE_SCHEMA_SHA_MISMATCH")
    return model, scaler, {"model_name": contract["model_name"], "model_version": actual_model_version, "model_ref": contract["model_ref"], "model_sha256": contract["model_sha256"], "scaler_sha256": contract["scaler_sha256"], "feature_schema_sha256": feature["feature_schema_sha256"], "training_cutoff": contract["training_cutoff"]}


def _validated_model_version(metadata: dict[str, Any], contract: dict[str, Any]) -> str:
    """Return only the model_metadata.json version after frozen validation."""
    actual_model_version = metadata.get("version")
    if not isinstance(actual_model_version, str) or actual_model_version != contract["model_name"]:
        raise Stop("MODEL_VERSION_MISMATCH")
    return actual_model_version


def pre_artifact_required_field_completeness(protocol: dict[str, Any], semantic: dict[str, Any]) -> tuple[int, list[str]]:
    """Validate the 36 frozen fields plus persisted protocol SHA (37 total)."""
    expected = [*protocol["pre_freeze_contract"]["required_fields"], "protocol_sha256"]
    available = set(semantic) | set(semantic.get("model", {}))
    for race in semantic.get("races", []):
        available |= set(race)
        for horse in race.get("horses", []):
            available |= set(horse)
    return len(expected), sorted(set(expected) - available)


def _manifest_hashes(prediction_root: Path) -> dict[str, str]:
    manifest_path = prediction_root / "prediction_manifest.json"
    if not manifest_path.is_file():
        raise Stop("CURRENT_PREDICTION_MANIFEST_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    values: dict[str, str] = {}
    for entry in manifest.get("files", []):
        rel, expected = entry.get("relative_path"), entry.get("sha256")
        path = prediction_root / str(rel)
        if not rel or not expected or not path.is_file() or sha256(path) != expected:
            raise Stop(f"SOURCE_PREDICTION_SHA_MISMATCH:{rel}")
        values[str(rel)] = str(expected)
    return values


def _race_result(date: str, payload: dict[str, Any], source_sha: str, model: object, scaler: object, identity: dict[str, str]) -> dict[str, Any]:
    race_id = str(payload.get("race_id", "UNKNOWN"))
    try:
        _assert_result_free(payload, race_id)
        ranked = payload.get("ranked_results")
        trace = payload.get("buy_gate_trace")
        if not isinstance(ranked, list) or not isinstance(trace, dict) or not isinstance(trace.get("horses"), list) or not isinstance(trace.get("race"), dict):
            raise Stop("FULL_FIELD_INPUT_INVALID")
        state = trace["race"].get("shadow_race_state")
        if state not in {"PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"}:
            raise Stop("RACE_STATE_INVALID")
        nums = [int(row["horse_number"]) for row in ranked if isinstance(row, dict) and row.get("horse_number") is not None]
        trace_by_number = {int(row["horse_number"]): row for row in trace["horses"] if isinstance(row, dict) and row.get("horse_number") is not None}
        if len(nums) != len(ranked) or len(set(nums)) != len(nums) or len(trace_by_number) != len(trace["horses"]) or set(nums) != set(trace_by_number):
            raise Stop("FULL_FIELD_HORSE_SET_MISMATCH")
        target_k = sum(row.get("buy") is True for row in ranked)
        common = {"date":date, "race_id":race_id, "venue":payload.get("venue"), "race_number":payload.get("race_number"), "race_state":state, "source_prediction_sha256":source_sha, "full_field_input_valid":True, "target_k":target_k, "play_converged_integrity_check":"PASS"}
        if target_k == 0:
            return {**common, "race_status":"NOT_RUN", "not_run_reason":"TARGET_K_ZERO_OUT_OF_SCOPE", "selected_n":0, "shortfall":0, "horses":[]}
        if state != "PLAY_CONVERGED":
            return {**common, "race_status":"NOT_RUN", "not_run_reason":"BUY_COUNT_GTE_1_BUT_RACE_STATE_NOT_PLAY_CONVERGED", "play_converged_integrity_check":"FAIL", "selected_n":0, "shortfall":0, "horses":[]}
        if len(ranked) < 5:
            raise Stop("INVALID_EXACT5_CONSTRUCTION")
        rows=[]
        for horse in ranked:
            number=int(horse["horse_number"]); t=trace_by_number[number]
            if not isinstance(t.get("risk_guard_pass"), bool):
                raise Stop("MISSING_REQUIRED_FEATURE:risk_guard_pass")
            rows.append((horse,t,frozen_local_vector(horse,t,state,f"{race_id}:{number}")))
        probabilities=model.predict_proba(scaler.transform(np.asarray([x[2] for x in rows],dtype=float)))[:,1]
        scored=[]
        for (horse,t,_), probability in zip(rows,probabilities,strict=True):
            if not math.isfinite(float(probability)):
                raise Stop("NON_FINITE_PROBABILITY")
            scored.append({"horse_number":int(horse["horse_number"]),"horse_name":horse.get("horse_name"),"probability":float(probability),"shadow_ai_rank":safe_rank(t.get("shadow_ai_rank"),f"{race_id}:{horse['horse_number']}"),"risk_guard_pass":t["risk_guard_pass"],"current_buy_flag":horse.get("buy") is True})
        ordered=sorted(scored,key=lambda x:(-x["probability"],x["shadow_ai_rank"],x["horse_number"]))
        exact5=ordered[:5]
        if len({x["horse_number"] for x in exact5}) != 5:
            raise Stop("INVALID_EXACT5_CONSTRUCTION")
        eligible=[row for row in exact5 if row["risk_guard_pass"]]
        selected={row["horse_number"] for row in eligible[:target_k]}
        output=[]
        exact_index={row["horse_number"]:i+1 for i,row in enumerate(exact5)}
        selected_index={row["horse_number"]:i+1 for i,row in enumerate(eligible[:target_k])}
        for rank,row in enumerate(ordered,1):
            no=row["horse_number"]
            if no not in exact_index: reason="OUTSIDE_EXACT5"; eligibility=False
            elif not row["risk_guard_pass"]: reason="RISK_GUARD_FAIL"; eligibility=False
            elif no in selected: reason="SELECTED"; eligibility=True
            else: reason="NOT_SELECTED_WITHIN_TARGET_K"; eligibility=True
            output.append({**row,"probability_rank":rank,"exact5_membership":no in exact_index,"exact5_rank":exact_index.get(no),"selection_eligibility":eligibility,"selection_exclusion_reason":reason,"selected_by_protocol":no in selected,"selection_rank":selected_index.get(no)})
        selected_n=len(selected); shortfall=max(0,target_k-selected_n)
        return {**common,"race_status":"SUCCESS","not_run_reason":None,"selected_n":selected_n,"shortfall":shortfall,"horses":output}
    except Stop as exc:
        return {"date":date,"race_id":race_id,"race_status":"NOT_RUN","not_run_reason":str(exc),"full_field_input_valid":False,"source_prediction_sha256":source_sha,"horses":[]}


def run_technical_wiring(date: str, prediction_root: Path, output_root: Path) -> Path:
    """Run only an explicitly labelled, result-free technical fixture."""
    if not date.isdigit() or len(date) != 8:
        raise Stop("DATE_FORMAT_INVALID")
    if output_root.exists():
        raise Stop("OUTPUT_PATH_ALREADY_EXISTS")
    protocol=load_frozen_protocol(); model,scaler,identity=load_frozen_v5(protocol)
    prediction_root=prediction_root.resolve(); hashes=_manifest_hashes(prediction_root)
    index_path=prediction_root/'race_index.json'
    race_index=json.loads(index_path.read_text(encoding='utf-8')).get('race_index')
    if not isinstance(race_index,list): raise Stop('RACE_INDEX_INVALID')
    races=[]
    for item in race_index:
        rel=item.get('artifact'); path=prediction_root/str(rel)
        if rel not in hashes: raise Stop(f'SOURCE_PREDICTION_SHA_MISMATCH:{rel}')
        payload=json.loads(path.read_text(encoding='utf-8'))
        races.append(_race_result(date,payload,hashes[rel],model,scaler,identity))
    semantic={"protocol_name":protocol['identity']['protocol_name'],"protocol_version":protocol['identity']['protocol_version'],"protocol_sha256":FROZEN_PROTOCOL_SHA256,"evidence_role":"TECHNICAL_WIRING_TEST_ONLY","formal_evidence":False,"model":identity,"ordering_rule":"predicted_actual_top3_probability DESC","tie_break_rule":["shadow_ai_rank ASC","horse_number ASC"],"risk_guard_semantics":"FROZEN_SAFETY_ELIGIBILITY_VETO_AFTER_EXACT5_BEFORE_TARGET_K","volume_source":"CURRENT_PRE_FROZEN_BUY_COUNT","outside_fill_rule":"PROHIBITED","races":races}
    output_root.mkdir(parents=True)
    _write(output_root/'semantic_selection.json',semantic)
    _write(output_root/'manifest.json',{"technical_fixture_date":date,"technical_fixture_role":"TECHNICAL_WIRING_TEST_ONLY","formal_evidence":False,"race_count":len(races),"success_race_count":sum(r['race_status']=='SUCCESS' for r in races),"not_run_race_count":sum(r['race_status']=='NOT_RUN' for r in races),"source_prediction_sha_authority":"RAW_FILE_BYTES_SHA256","semantic_selection_sha256":sha256(output_root/'semantic_selection.json')})
    return output_root


def main() -> None:
    parser=argparse.ArgumentParser(description='Selection Authority Protocol V1 technical wiring only')
    parser.add_argument('--technical-date', required=True); parser.add_argument('--prediction-root', type=Path, required=True); parser.add_argument('--output-root', type=Path, required=True)
    args=parser.parse_args(); run_technical_wiring(args.technical_date,args.prediction_root,args.output_root)


if __name__ == '__main__': main()
