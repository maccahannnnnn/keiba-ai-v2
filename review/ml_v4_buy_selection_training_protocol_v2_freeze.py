"""Mechanical V2 protocol correction: PaceStyle retained, raw race_state dropped."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "reports" / "ml_v4_buy_selection_training_protocol_v1"
OUT = ROOT / "reports" / "ml_v4_buy_selection_training_protocol_v2"
DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v1"
EXPECTED = {"dataset": "02d2471f11c1069ebb264946eacdc55fe3ea673c8812b6d17c8fd973af538b53", "v1_protocol": "97e783a8c63c7a8ff446b14bb7ec6f17001d43128eb215eda994b96be44d1ebd", "v1_manifest": "847e9f94acc4e4d16c4efa4a8be774ba2e2a53fa82b2a0035ef2de5302fb5d2c"}
SEMANTIC = ["Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle", "shadow_ai_rank", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count", "consensus_negative_count", "risk_count", "conflict_count", "race_state"]
EXPECTED_TRANSFORMED = [*SEMANTIC[:-1], "is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"]
GATES = ["absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def run() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    actual = {"dataset": sha(DATASET / "dataset.csv"), "v1_protocol": sha(V1 / "training_protocol.md"), "v1_manifest": sha(V1 / "protocol_manifest.json")}
    if actual != EXPECTED:
        raise RuntimeError(f"AUTHORITY_SHA_MISMATCH:{actual}")
    v1_protocol = json.loads((V1 / "training_protocol.json").read_text(encoding="utf-8"))
    v1_evaluation = json.loads((V1 / "evaluation_protocol.json").read_text(encoding="utf-8"))
    v1_governance = json.loads((V1 / "governance_boundary.json").read_text(encoding="utf-8"))
    dataset_schema = json.loads((DATASET / "feature_schema.json").read_text(encoding="utf-8"))
    if set(dataset_schema.get("feature_order", [])) != set(SEMANTIC) or len(dataset_schema.get("feature_order", [])) != 20:
        raise RuntimeError("DATASET_SEMANTIC_SET_MISMATCH")
    transform = {"semantic_feature_count": 20, "semantic_feature_order": SEMANTIC, "semantic_feature_order_authority": "Training Protocol v2 §Authoritative Semantic Feature Order", "categorical": {"race_state": {"allowed_categories": ["PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"], "reference": "PLAY_CONVERGED", "raw_feature_model_input": "DROP", "encoding": "one_hot_drop_reference", "dummy_columns_in_order": ["is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"], "unknown_category": "FAIL_CLOSED", "ordinal_encoding": "FORBIDDEN"}}, "boolean": {name: {"false": 0, "true": 1, "other": "FAIL_CLOSED"} for name in GATES}, "transformed_model_input_columns": EXPECTED_TRANSFORMED, "transformed_model_input_column_count": 21}
    actual_columns = transform["transformed_model_input_columns"]
    expected_set = (set(SEMANTIC) - {"race_state"}) | {"is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"}
    actual_set = set(actual_columns)
    validators = {"semantic_feature_count": len(SEMANTIC) == 20, "pace_style_semantic_present": "PaceStyle" in SEMANTIC, "pace_style_transformed_present": "PaceStyle" in actual_columns, "raw_race_state_semantic_present": "race_state" in SEMANTIC, "raw_race_state_transformed_absent": "race_state" not in actual_columns, "race_state_dummy_columns_present": all(x in actual_columns for x in ["is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"]), "transformed_model_input_count": len(actual_columns) == 21, "transformed_set_equality": actual_set == expected_set, "transformed_order_equality": actual_columns == EXPECTED_TRANSFORMED, "unexpected_column_count": len(actual_set - expected_set), "missing_expected_column_count": len(expected_set - actual_set), "duplicate_column_count": len(actual_columns) - len(actual_set)}
    if not all(value is True for key, value in validators.items() if isinstance(value, bool)) or any(validators[key] != 0 for key in ("unexpected_column_count", "missing_expected_column_count", "duplicate_column_count")):
        raise RuntimeError(f"TRANSFORM_VALIDATION_FAILED:{validators}")
    v2_protocol = deepcopy(v1_protocol)
    v2_protocol["protocol_version"] = "ML_V4_BUY_SELECTION_TRAINING_PROTOCOL_V2"
    v2_protocol["status"] = "FROZEN"
    v2_protocol["feature_transform"] = transform
    v2_protocol["supersedes"] = "ML_V4_BUY_SELECTION_TRAINING_PROTOCOL_V1"
    v2_protocol["supersede_reason"] = "FEATURE_TRANSFORM_SPEC_CORRECTION"
    comparison_v1, comparison_v2 = deepcopy(v1_protocol), deepcopy(v2_protocol)
    for protocol in (comparison_v1, comparison_v2):
        protocol.pop("protocol_version", None); protocol.pop("status", None); protocol.pop("feature_transform", None); protocol.pop("supersedes", None); protocol.pop("supersede_reason", None)
    non_feature_changes = 0 if comparison_v1 == comparison_v2 else 1
    if non_feature_changes:
        raise RuntimeError("NON_FEATURE_PROTOCOL_CHANGE_DETECTED")
    correction = {"status": "PASS", "supersedes": "training_protocol_v1", "reason": "FEATURE_TRANSFORM_SPEC_CORRECTION", "mechanical_correction_only": True, "bug": {"pace_style": "omitted from v1 transformed input", "raw_race_state": "retained in v1 transformed input"}, "expected": {"pace_style": "retained", "raw_race_state": "replaced by is_PLAY_UNCONVERGED_4PLUS and is_SKIP"}, "discovery_stage": "POST_TRAIN_PRE_OOS_INDEPENDENT_REVIEW", "performance_disclosure_count": 0, "may_access_count": 0, "oos_contamination": "NO", "protocol_v1_status": "SUPERSEDED_DUE_TO_FEATURE_TRANSFORM_SPEC_ERROR", "model_v1_status": "FREEZE_REJECT_DUE_TO_SUPERSEDED_PROTOCOL", "model_v1_artifact_mutation": 0, "non_feature_protocol_change_count": 0, "validators": validators}
    write("training_protocol.json", v2_protocol); write("feature_transform_schema.json", transform); write("evaluation_protocol.json", v1_evaluation); write("governance_boundary.json", v1_governance); write("protocol_correction_record.json", correction)
    markdown = """# KeibaAI ML V4 BUY Selection Learning — Training Protocol v2\n\nV1を`SUPERSEDED_DUE_TO_FEATURE_TRANSFORM_SPEC_ERROR`とし、既承認のfeature transformを機械的に訂正した。Model v1は`FREEZE_REJECT_DUE_TO_SUPERSEDED_PROTOCOL`であり、May OOSには使用しない。\n\n## Fixed transform\n\n20 semantic featuresは、Ability、PastPerformance、Distance、CourseShape、LapSuitability、RaceShape、PaceStyle、shadow_ai_rank、decision_score、final_score、adjusted_score、4 gate、consensus counts、risk/conflict count、race_stateの順。\n\n`race_state`はmodel inputからDROPする。PLAY_CONVERGEDをreferenceとして`is_PLAY_UNCONVERGED_4PLUS`、`is_SKIP`を同位置に生成する。PaceStyleは必ず保持する。変換後列は21列で、未知stateおよび非boolean gateはFAIL_CLOSED。\n\nV1からの変更はこのtransform訂正だけであり、Dataset、target、recipe、Gate、LODO、P50、May consumption、SKIP/UNCONVERGED boundaryは不変。fit、性能開示、Mayアクセス、OOS評価は0件。\n"""
    (OUT / "training_protocol.md").write_text(markdown, encoding="utf-8")
    write("protocol_manifest.json", {"protocol_version": "ML_V4_BUY_SELECTION_TRAINING_PROTOCOL_V2", "status": "FROZEN", "supersedes": "training_protocol_v1", "reason": "FEATURE_TRANSFORM_SPEC_CORRECTION", "dataset_sha256": actual["dataset"], "v1_protocol_sha256": actual["v1_protocol"], "v1_protocol_manifest_sha256": actual["v1_manifest"], "training_protocol_sha256": sha(OUT / "training_protocol.md"), "training_protocol_json_sha256": sha(OUT / "training_protocol.json"), "feature_transform_schema_sha256": sha(OUT / "feature_transform_schema.json"), "evaluation_protocol_sha256": sha(OUT / "evaluation_protocol.json"), "governance_boundary_sha256": sha(OUT / "governance_boundary.json"), "correction_record_sha256": sha(OUT / "protocol_correction_record.json"), "may_access_count": 0, "march_or_earlier_access_count": 0, "scaler_fit_count": 0, "model_fit_count": 0})
    write("artifact_hashes.json", {"indexed_artifacts": {p.name: sha(p) for p in OUT.iterdir() if p.is_file() and p.name != "artifact_hashes.json"}, "self_hash_excluded": True})
    return OUT


if __name__ == "__main__":
    print(run())
