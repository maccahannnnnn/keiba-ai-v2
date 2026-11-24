"""Additive, result-free V5/V6 forward-comparison PRE wiring.

This module never creates formal evidence by itself.  ``run_technical_fixture``
is explicitly isolated and labels every output ``formal_evidence=false``.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from review import selection_authority_protocol_v1_pre_freeze as v5core

PROTOCOL_PATH = ROOT / "docs" / "selection_authority_protocol_v1_v6_forward_shadow.json"
FROZEN_PROTOCOL_SHA256 = "8f2d25d0f33c0894f7e49750f40255f3cf4ea8e7782f16f570c13a941377e41b"
V6_ROOT = ROOT / "reports" / "ml_v4_buy_selection_model_v6"
REAL_PRE_ROOT = ROOT / "reports" / "selection_authority_protocol_v1_v6_forward_shadow" / "pre"
HUMAN_APPROVAL_DATE = "20260918"
JST = timezone(timedelta(hours=9))

class Stop(RuntimeError):
    pass

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

def load_protocol() -> dict[str, Any]:
    if not PROTOCOL_PATH.is_file() or sha256(PROTOCOL_PATH) != FROZEN_PROTOCOL_SHA256:
        raise Stop("STOP_PROTOCOL_SHA_MISMATCH")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    if protocol.get("evidence_role") != "FORMAL_PROSPECTIVE_MODEL_COMPARISON_V5_V6" or protocol.get("v5_v6_semantic_difference") != "MODEL_IDENTITY_ONLY":
        raise Stop("STOP_PROTOCOL_SEMANTICS_MISMATCH")
    return protocol

def load_frozen_v6(protocol: dict[str, Any]) -> tuple[object, object, dict[str, str]]:
    """Load only the exact V6 bytes pinned by the sibling protocol."""
    contract = protocol["v6_contract"]
    paths = {"model": ROOT / contract["model_path"], "scaler": ROOT / contract["scaler_path"],
             "feature_schema": ROOT / contract["feature_schema_path"], "dataset": ROOT / contract["dataset_path"]}
    for key, path in paths.items():
        if not path.is_file() or sha256(path) != contract[f"{key}_sha256"]:
            raise Stop(f"STOP_V6_IDENTITY_MISMATCH:{key}")
    metadata_path = V6_ROOT / "model_metadata.json"
    if not metadata_path.is_file(): raise Stop("STOP_V6_IDENTITY_MISMATCH:metadata")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("model_name") != contract["expected_model_name"] or metadata.get("role") != contract["expected_role"]:
        raise Stop("STOP_V6_IDENTITY_MISMATCH:metadata")
    if metadata.get("model_sha256") != contract["model_sha256"] or metadata.get("scaler_sha256") != contract["scaler_sha256"] or metadata.get("dataset_sha256") != contract["dataset_sha256"]:
        raise Stop("STOP_V6_IDENTITY_MISMATCH:metadata_hash")
    schema = json.loads(paths["feature_schema"].read_text(encoding="utf-8"))
    if schema.get("model_name") != contract["expected_model_name"] or schema.get("semantic_feature_count") != 20:
        raise Stop("STOP_V6_IDENTITY_MISMATCH:schema")
    transform = json.loads((V6_ROOT / "feature_transform_schema.json").read_text(encoding="utf-8"))
    if transform.get("transformed_model_input_columns") != v5core.TRANSFORMED or transform.get("transformed_input_count") != contract["transformed_feature_count"]:
        raise Stop("STOP_V6_IDENTITY_MISMATCH:transform")
    try:
        model, scaler = joblib.load(paths["model"]), joblib.load(paths["scaler"])
    except Exception as exc:  # pragma: no cover
        raise Stop("STOP_V6_IDENTITY_MISMATCH:load") from exc
    if getattr(model, "n_features_in_", None) != 21 or getattr(scaler, "n_features_in_", None) != 21:
        raise Stop("STOP_V6_IDENTITY_MISMATCH:feature_count")
    return model, scaler, {"model_name": contract["expected_model_name"], "model_version":"V4 Model v6", "model_ref":"FROZEN_V6_DEVELOPMENT_CANDIDATE", "model_sha256":contract["model_sha256"], "scaler_sha256":contract["scaler_sha256"], "feature_schema_sha256":contract["feature_schema_sha256"], "dataset_sha256":contract["dataset_sha256"], "role":contract["expected_role"]}

def _v5(protocol: dict[str, Any]) -> tuple[object, object, dict[str, str]]:
    parent = v5core.load_frozen_protocol()
    if sha256(v5core.PROTOCOL_PATH) != protocol["v5_protocol"]["sha256"]:
        raise Stop("STOP_V5_IDENTITY_MISMATCH:protocol")
    try:
        return v5core.load_frozen_v5(parent)
    except v5core.Stop as exc:
        raise Stop(f"STOP_V5_IDENTITY_MISMATCH:{exc}") from exc

def _validate_arm_population(left: dict[str, Any], right: dict[str, Any]) -> None:
    """The only allowed V5/V6 difference is their fitted parameters."""
    shared = ("date", "race_id", "venue", "race_number", "race_state", "source_prediction_sha256", "full_field_input_valid", "target_k", "play_converged_integrity_check")
    if any(left.get(k) != right.get(k) for k in shared):
        raise Stop("STOP_V5_V6_POPULATION_MISMATCH")
    left_numbers = {x.get("horse_number") for x in left.get("horses", [])}
    right_numbers = {x.get("horse_number") for x in right.get("horses", [])}
    if left_numbers != right_numbers:
        raise Stop("STOP_V5_V6_POPULATION_MISMATCH")

def _dual_race(date: str, payload: dict[str, Any], source_sha: str, v5: tuple[object,object,dict[str,str]], v6: tuple[object,object,dict[str,str]]) -> dict[str, Any]:
    # The parent function is the sole selection implementation for both arms.
    try:
        left = v5core._race_result(date, payload, source_sha, *v5)
        right = v5core._race_result(date, payload, source_sha, *v6)
    except v5core.Stop as exc:
        raise Stop(f"STOP_RESULT_ACCESS_BOUNDARY_VIOLATION:{exc}") from exc
    _validate_arm_population(left, right)
    if not left.get("full_field_input_valid") or not right.get("full_field_input_valid"):
        raise Stop("STOP_V5_V6_POPULATION_MISMATCH")
    if left.get("target_k", 0) < 1 or left.get("race_status") != "SUCCESS":
        return {"eligible_evidence_race":False, "eligibility_reason":left.get("not_run_reason"), "v5":left, "v6":right}
    for arm in (left, right):
        horses = arm.get("horses", [])
        if len({x.get("horse_number") for x in horses}) != len(horses): raise Stop("STOP_V5_V6_POPULATION_MISMATCH")
        exact5 = [x for x in horses if x.get("exact5_membership")]
        if len(exact5) != 5: raise Stop("STOP_EXACT5_INVARIANT")
        if arm.get("shortfall") != max(arm["target_k"] - arm["selected_n"], 0): raise Stop("STOP_SHORTFALL_INVARIANT")
    return {"eligible_evidence_race":True, "eligibility_reason":"PREDEFINED_ELIGIBILITY_PASS", "v5":left, "v6":right}

def _clock_boundary(clock_utc: datetime | None) -> tuple[datetime, str, str]:
    instant = datetime.now(timezone.utc) if clock_utc is None else clock_utc
    if instant.tzinfo is None:
        raise Stop("STOP_CLOCK_TIMEZONE_INVALID")
    instant = instant.astimezone(timezone.utc)
    return instant, instant.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), instant.astimezone(JST).strftime("%Y%m%d")

def _parse_generated_at(value: object) -> tuple[str, str]:
    if not isinstance(value, str): raise Stop("STOP_CURRENT_PRE_PROVENANCE_INVALID")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None: raise ValueError("timezone missing")
    except ValueError as exc:
        raise Stop("STOP_CURRENT_PRE_PROVENANCE_INVALID") from exc
    return value, instant.astimezone(JST).strftime("%Y%m%d")

def _current_pre_identity(target_date: str, prediction_root: Path, execution_timestamp_utc: str, execution_date_jst: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if not isinstance(target_date, str) or not target_date.isdigit() or len(target_date) != 8:
        raise Stop("STOP_EXPLICIT_TARGET_DATE_REQUIRED")
    if target_date < HUMAN_APPROVAL_DATE:
        raise Stop("STOP_BEFORE_FORMAL_EVIDENCE_START")
    if target_date < execution_date_jst:
        raise Stop("STOP_RETROACTIVE_V6_FORMAL_PRE_PROHIBITED")
    summary_path = prediction_root / "summary.json"
    if not prediction_root.is_dir() or not summary_path.is_file():
        raise Stop("STOP_CURRENT_PRE_NOT_FOUND")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("date") != target_date:
        raise Stop("STOP_CURRENT_PRE_AMBIGUOUS")
    hashes = v5core._manifest_hashes(prediction_root)
    provenance_path = prediction_root / "provenance.json"
    if "provenance.json" not in hashes or not provenance_path.is_file():
        raise Stop("STOP_CURRENT_PRE_PROVENANCE_INVALID")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    generated_at, generated_date_jst = _parse_generated_at(provenance.get("generated_at"))
    if generated_date_jst < HUMAN_APPROVAL_DATE:
        raise Stop("STOP_CURRENT_PRE_PREDATES_FORMAL_EVIDENCE_START")
    if provenance.get("target_date") != target_date or summary.get("date") != target_date:
        raise Stop("STOP_CURRENT_PRE_AMBIGUOUS")
    index = json.loads((prediction_root / "race_index.json").read_text(encoding="utf-8")).get("race_index")
    if not isinstance(index, list) or len({x.get("race_id") for x in index if isinstance(x, dict)}) != len(index):
        raise Stop("STOP_CURRENT_PRE_AMBIGUOUS")
    payloads=[]
    for item in index:
        if not isinstance(item, dict): raise Stop("STOP_CURRENT_PRE_AMBIGUOUS")
        rel=str(item.get("artifact")); path=prediction_root / rel
        if rel not in hashes or not path.is_file(): raise Stop(f"STOP_SOURCE_PREDICTION_SHA_MISMATCH:{rel}")
        payload=json.loads(path.read_text(encoding="utf-8"))
        if payload.get("race_id") != item.get("race_id"): raise Stop("STOP_CURRENT_PRE_AMBIGUOUS")
        try: v5core._assert_result_free(payload, str(payload.get("race_id", "UNKNOWN")))
        except v5core.Stop as exc: raise Stop(f"STOP_RESULT_ACCESS_BOUNDARY_VIOLATION:{exc}") from exc
        payloads.append({"payload":payload,"sha":hashes[rel]})
    return {"prediction_root":prediction_root.as_posix(),"summary_sha256":sha256(summary_path),"prediction_manifest_sha256":sha256(prediction_root / "prediction_manifest.json"),"race_index_sha256":sha256(prediction_root / "race_index.json"),"current_pre_generated_at":generated_at,"current_pre_generated_date_jst":generated_date_jst,"current_pre_provenance_sha256":sha256(provenance_path),"execution_timestamp_utc":execution_timestamp_utc,"execution_date_jst":execution_date_jst}, payloads

def run_real_formal_pre(target_date: str, current_pre_root: Path, output_base: Path | None = None, *, clock_utc: datetime | None = None) -> Path:
    """Freeze one explicitly named future Current PRE; never selects a date itself."""
    protocol=load_protocol(); v5=_v5(protocol); v6=load_frozen_v6(protocol)
    _, execution_timestamp_utc, execution_date_jst = _clock_boundary(clock_utc)
    output_base = REAL_PRE_ROOT if output_base is None else output_base
    output = output_base / target_date
    if output.exists(): raise Stop("STOP_REAL_PRE_ALREADY_EXISTS")
    source, payloads = _current_pre_identity(target_date, current_pre_root, execution_timestamp_utc, execution_date_jst)
    races=[_dual_race(target_date, item["payload"], item["sha"], v5, v6) for item in payloads]
    eligible=sum(r["eligible_evidence_race"] for r in races)
    start_boundary={"human_approval_date":HUMAN_APPROVAL_DATE,"formal_evidence_start_rule_id":"APPROVAL_PINNED_PLUS_NON_RETROACTIVE_EXECUTION_PLUS_SOURCE_FRESHNESS","execution_timestamp_utc":execution_timestamp_utc,"execution_date_jst":execution_date_jst,"current_pre_generated_at":source["current_pre_generated_at"],"current_pre_generated_date_jst":source["current_pre_generated_date_jst"],"current_pre_provenance_sha256":source["current_pre_provenance_sha256"],"start_boundary_guards_passed":["G1","G2","G3","G4"]}
    semantic={"protocol_identity":protocol["identity"],"protocol_sha256":FROZEN_PROTOCOL_SHA256,"evidence_role":protocol["evidence_role"],"formal_evidence":True,"formal_evidence_meaning":protocol["formal_evidence_meaning"],"target_date":target_date,"current_pre_source_identity":source,"start_boundary":start_boundary,"v5_identity":v5[2],"v6_identity":v6[2],"eligible_race_definition":protocol["eligible_race_denominator"],"evidence_denominator_depends_on_selected_n":False,"total_source_races":len(races),"eligible_race_count":eligible,"ineligible_race_count":len(races)-eligible,"races":races}
    output.mkdir(parents=True)
    _write(output / "dual_pre_semantic.json", semantic)
    _write(output / "dual_pre_manifest.json", {"target_date":target_date,"formal_evidence":True,"evidence_role":protocol["evidence_role"],"total_source_races":len(races),"eligible_race_count":eligible,"ineligible_race_count":len(races)-eligible,"result_access":0,"actual_top3_access":0,"semantic_sha256":sha256(output / "dual_pre_semantic.json")})
    _write(output / "artifact_index.json", {"self_hash_excluded":True,"indexed_artifacts":{p.name:sha256(p) for p in output.iterdir() if p.is_file() and p.name!="artifact_index.json"}})
    _write(output / "run_metadata.json", {"timestamp":execution_timestamp_utc,"target_date":target_date,"runtime":"REAL_FORMAL_PRE_ENTRYPOINT","formal_evidence":True,"result_access":0,"actual_top3_access":0})
    return output

def run_technical_fixture(date: str, prediction_root: Path, output_root: Path) -> Path:
    """Result-free technical validation only; cannot create formal prospective evidence."""
    if not date.isdigit() or len(date) != 8: raise Stop("STOP_DATE_FORMAT")
    if output_root.exists(): raise Stop("STOP_OUTPUT_PATH_EXISTS")
    protocol = load_protocol(); v5 = _v5(protocol); v6 = load_frozen_v6(protocol)
    hashes = v5core._manifest_hashes(prediction_root)
    index = json.loads((prediction_root / "race_index.json").read_text(encoding="utf-8")).get("race_index")
    if not isinstance(index, list): raise Stop("STOP_RACE_INDEX_INVALID")
    races=[]
    for item in index:
        rel=str(item.get("artifact")); path=prediction_root / rel
        if rel not in hashes: raise Stop(f"STOP_SOURCE_PREDICTION_SHA_MISMATCH:{rel}")
        payload=json.loads(path.read_text(encoding="utf-8"))
        # Explicitly detects any outcome field before either arm receives the payload.
        try: v5core._assert_result_free(payload, str(payload.get("race_id", "UNKNOWN")))
        except v5core.Stop as exc: raise Stop(f"STOP_RESULT_ACCESS_BOUNDARY_VIOLATION:{exc}") from exc
        races.append(_dual_race(date, payload, hashes[rel], v5, v6))
    semantic={"protocol_sha256":FROZEN_PROTOCOL_SHA256,"evidence_role":"TECHNICAL_WIRING_TEST_ONLY","formal_evidence":False,"technical_wiring_only":True,"v5_identity":v5[2],"v6_identity":v6[2],"semantic_difference":"MODEL_IDENTITY_ONLY","eligible_race_denominator_definition":protocol["eligible_race_denominator"],"evidence_denominator_depends_on_selected_n":False,"races":races}
    output_root.mkdir(parents=True); _write(output_root / "dual_pre_semantic.json", semantic)
    _write(output_root / "dual_pre_manifest.json", {"technical_fixture_date":date,"formal_evidence":False,"race_count":len(races),"eligible_evidence_races":sum(x["eligible_evidence_race"] for x in races),"result_access":0,"actual_top3_access":0,"semantic_sha256":sha256(output_root / "dual_pre_semantic.json")})
    _write(output_root / "artifact_index.json", {"self_hash_excluded":True,"indexed_artifacts":{p.name:sha256(p) for p in output_root.iterdir() if p.is_file() and p.name!="artifact_index.json"}})
    return output_root
