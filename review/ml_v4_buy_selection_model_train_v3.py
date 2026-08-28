"""One-shot V4 Model v3 training from the frozen Dataset v2 authority only."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import scipy
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "ml_v4_buy_selection_model_v3"
DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v2"
PROTOCOL = ROOT / "reports" / "ml_v4_buy_selection_training_protocol_v2"
RUNTIME = ROOT / "reports" / "ml_v4_training_runtime_v1"
EXPECTED = {
    "dataset": "b61994c2a488696a2fcc70f4b4f24e4756e4b6562ca751fa1f30819d30e535e2",
    "feature_schema": "d30597a96f43bd04ba491eac75925b2fd254df50c3e1372790d86b92eebb8eb1",
    "dataset_manifest": "9c71da008dd5a968a7d9a9c01b99456491c5518e8a57c2a18f2c47cf5d02566d",
    "protocol": "be8764d425650a067e4ddaca96f2cc52b9dff371c336676e51d52e3eaf502100",
    "protocol_manifest": "8ebaf317c3d0c916d30ee023f48ff52750d2aeb5dd0ca0ac9e1f8e06f0fac696",
    "runtime_requirements": "30a9ca043286755020691f7040ff0946c1427aa6fedae9daa04d0239e1998dff",
    "runtime_manifest": "efd36424206dfd54c16b0517d9832338bbb61f286a1725c2ddde6c69058182a5",
}
SEMANTIC = ["Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle", "shadow_ai_rank", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count", "consensus_negative_count", "risk_count", "conflict_count", "race_state"]
TRANSFORMED = [*SEMANTIC[:-1], "is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"]
GATES = {"absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass"}
FROZEN_ROOTS = (
    ROOT / "reports" / "ml_v4_buy_selection_dataset_v1",
    DATASET,
    ROOT / "reports" / "ml_v4_buy_selection_model_v2",
    ROOT / "reports" / "may_2026_multi_system_oos_v1" / "pre_retry_v5",
    ROOT / "reports" / "may_2026_multi_system_oos_v1" / "post_v1",
)


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def number(value: str, context: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise Stop(f"NUMERIC_INVALID:{context}") from exc
    if not math.isfinite(numeric):
        raise Stop(f"NUMERIC_NONFINITE:{context}")
    return numeric


def boolean(value: str, context: str) -> int:
    if value == "True":
        return 1
    if value == "False":
        return 0
    raise Stop(f"BOOLEAN_INVALID:{context}:{value!r}")


def fit(features: np.ndarray, target: np.ndarray) -> tuple[StandardScaler, LogisticRegression, np.ndarray, list[str]]:
    scaler = StandardScaler()
    model = LogisticRegression(penalty="l2", C=1.0, solver="lbfgs", class_weight=None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        transformed = scaler.fit_transform(features)
        model.fit(transformed, target)
    return scaler, model, model.predict_proba(transformed)[:, 1], [str(item.message) for item in caught if issubclass(item.category, ConvergenceWarning)]


def verify_index(root: Path) -> dict:
    index_path = root / "artifact_hashes.json"
    if not index_path.is_file():
        raise Stop(f"FROZEN_INDEX_MISSING:{root}")
    index = json.loads(index_path.read_text(encoding="utf-8")).get("indexed_artifacts", {})
    bad = [name for name, expected in index.items() if not (root / name).is_file() or sha(root / name) != expected]
    if bad:
        raise Stop(f"FROZEN_INDEX_MISMATCH:{root}:{','.join(bad)}")
    return {"path": str(root.relative_to(ROOT)), "artifact_count": len(index), "status": "PASS"}


def authority() -> tuple[dict, dict]:
    actual = {
        "dataset": sha(DATASET / "dataset.csv"),
        "feature_schema": sha(DATASET / "feature_schema.json"),
        "dataset_manifest": sha(DATASET / "dataset_manifest.json"),
        "protocol": sha(PROTOCOL / "training_protocol.md"),
        "protocol_manifest": sha(PROTOCOL / "protocol_manifest.json"),
        "runtime_requirements": sha(RUNTIME / "requirements_frozen.txt"),
        "runtime_manifest": sha(RUNTIME / "runtime_manifest.json"),
    }
    if actual != EXPECTED:
        raise Stop(f"AUTHORITY_SHA_MISMATCH:{actual}")
    manifest = json.loads((DATASET / "dataset_manifest.json").read_text(encoding="utf-8"))
    validation = json.loads((DATASET / "validation.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN_BUILD_ARTIFACT" or validation.get("status") != "PASS":
        raise Stop("DATASET_V2_STATUS_INVALID")
    counts = validation.get("actual_counts", {})
    if counts.get("rows") != 3240 or counts.get("positive") != 1108 or counts.get("negative") != 2132 or validation.get("feature_missing_count") != 0:
        raise Stop(f"DATASET_V2_COUNTS_INVALID:{counts}")
    return actual, validation


def transform_structure() -> dict:
    protocol = json.loads((PROTOCOL / "feature_transform_schema.json").read_text(encoding="utf-8"))
    columns = protocol.get("transformed_model_input_columns", [])
    expected = (set(SEMANTIC) - {"race_state"}) | {"is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"}
    result = {
        "PaceStyle_present": "PaceStyle" in columns,
        "raw_race_state_absent": "race_state" not in columns,
        "race_state_dummy_2_present": all(name in columns for name in ("is_PLAY_UNCONVERGED_4PLUS", "is_SKIP")),
        "transformed_feature_count": len(columns),
        "set_match": set(columns) == expected,
        "order_match": columns == TRANSFORMED,
        "duplicates": len(columns) - len(set(columns)),
    }
    if not result["PaceStyle_present"] or not result["raw_race_state_absent"] or not result["race_state_dummy_2_present"] or result["transformed_feature_count"] != 21 or not result["set_match"] or not result["order_match"] or result["duplicates"]:
        raise Stop(f"FEATURE_TRANSFORM_INVALID:{result}")
    return result


def load_matrix() -> tuple[np.ndarray, np.ndarray, list[str]]:
    rows = list(csv.DictReader((DATASET / "dataset.csv").open(encoding="utf-8", newline="")))
    matrix, targets, identities = [], [], []
    for row in rows:
        row_id = row.get("row_id", "")
        if row.get("current_top5") != "True" or row.get("valid_result") != "True":
            raise Stop(f"POPULATION_INVALID:{row_id}")
        state = row.get("race_state")
        if state not in {"PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"}:
            raise Stop(f"RACE_STATE_INVALID:{row_id}:{state}")
        values = [boolean(row[name], f"{row_id}:{name}") if name in GATES else number(row[name], f"{row_id}:{name}") for name in SEMANTIC[:-1]]
        values.extend((int(state == "PLAY_UNCONVERGED_4PLUS"), int(state == "SKIP")))
        if row.get("actual_top3") not in {"0", "1"}:
            raise Stop(f"TARGET_INVALID:{row_id}")
        matrix.append(values)
        targets.append(int(row["actual_top3"]))
        identities.append(row_id)
    x, y = np.asarray(matrix, dtype=float), np.asarray(targets, dtype=int)
    if x.shape != (3240, 21) or y.shape != (3240,) or int(y.sum()) != 1108 or len(set(identities)) != 3240:
        raise Stop(f"DATASET_MATRIX_INVALID:{x.shape}:{int(y.sum())}:{len(set(identities))}")
    return x, y, identities


def run() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        before = [verify_index(root) for root in FROZEN_ROOTS]
        actual, dataset_validation = authority()
        structure = transform_structure()
        runtime_validation = json.loads((RUNTIME / "runtime_validation.json").read_text(encoding="utf-8"))
        expected_packages = {"numpy": "2.3.5", "scikit_learn": "1.9.0", "scipy": "1.18.1", "joblib": "1.5.3"}
        current_packages = {"numpy": np.__version__, "scikit_learn": sklearn.__version__, "scipy": scipy.__version__, "joblib": joblib.__version__}
        if runtime_validation.get("status") != "PASS" or current_packages != expected_packages:
            raise Stop(f"RUNTIME_VERSION_INVALID:{current_packages}")
        features, target, identities = load_matrix()
        scaler, model, probabilities, warnings_first = fit(features, target)
        if warnings_first:
            raise Stop(f"SOLVER_NON_CONVERGENCE:{warnings_first}")
        sanity = {
            "coefficient_shape": list(model.coef_.shape) == [1, 21],
            "intercept_shape": list(model.intercept_.shape) == [1],
            "scaler_mean_shape": list(scaler.mean_.shape) == [21],
            "scaler_scale_shape": list(scaler.scale_.shape) == [21],
            "finite_coefficients": bool(np.isfinite(model.coef_).all()),
            "finite_intercept": bool(np.isfinite(model.intercept_).all()),
            "finite_scaler": bool(np.isfinite(scaler.mean_).all() and np.isfinite(scaler.scale_).all()),
            "probabilities_in_range": bool(np.isfinite(probabilities).all() and np.all((probabilities >= 0) & (probabilities <= 1))),
            "probability_alignment": len(probabilities) == len(identities),
            "nonconstant_output": bool(np.ptp(probabilities) > 0),
        }
        if not all(sanity.values()):
            raise Stop(f"MECHANICAL_VALIDATION_FAILED:{sanity}")
        scaler_2, model_2, probabilities_2, warnings_second = fit(features, target)
        deterministic = bool(not warnings_second and np.array_equal(scaler.mean_, scaler_2.mean_) and np.array_equal(scaler.scale_, scaler_2.scale_) and np.array_equal(model.coef_, model_2.coef_) and np.array_equal(model.intercept_, model_2.intercept_) and np.array_equal(probabilities, probabilities_2))
        if not deterministic:
            raise Stop("DETERMINISTIC_REPRODUCTION_FAILED")
        joblib.dump(model, OUT / "model.joblib")
        joblib.dump(scaler, OUT / "scaler.joblib")
        reloaded_model, reloaded_scaler = joblib.load(OUT / "model.joblib"), joblib.load(OUT / "scaler.joblib")
        reload_match = bool(np.array_equal(probabilities, reloaded_model.predict_proba(reloaded_scaler.transform(features))[:, 1]))
        if not reload_match:
            raise Stop("SERIALIZATION_RELOAD_PREDICTION_MISMATCH")
        after = [verify_index(root) for root in FROZEN_ROOTS]
        write("feature_transform_schema.json", {"source_protocol_v2_sha256": actual["protocol"], "semantic_feature_order": SEMANTIC, "semantic_feature_count": 20, "transformed_model_input_columns": TRANSFORMED, "transformed_model_input_column_count": 21, "validation": structure, "race_state": {"reference": "PLAY_CONVERGED", "raw_model_input": "DROP", "dummies": ["is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"], "unknown": "FAIL_CLOSED"}})
        write("coefficient_table.json", {"intercept": float(model.intercept_[0]), "coefficients": [{"feature_name": name, "coefficient": float(coefficient)} for name, coefficient in zip(TRANSFORMED, model.coef_[0], strict=True)], "inspection_only": True})
        write("model_output_schema.json", {"output": "RAW_MODEL_PROBABILITY", "semantic": "P(actual_top3)", "performance_evaluation": "NOT_EXECUTED"})
        write("model_metadata.json", {"model": "KeibaAI_V4_BUY_Selection_Model_V3", "parent_model_family": "V4 BUY Selection Learning", "previous_frozen_model": "V4 Model v2", "algorithm": "LogisticRegression", "penalty": "l2", "C": 1.0, "solver": "lbfgs", "class_weight": None, "runtime": {"python": sys.version, "implementation": platform.python_implementation(), **current_packages}, "authority_sha256": actual, "train_rows": 3240, "target": {"actual_top3_positive": 1108, "negative": 2132}, "semantic_features": 20, "model_input_columns": 21, "formal_scaler_fit_count": 1, "formal_model_fit_count": 1, "deterministic_reproduction_refit_count": 1, "timestamp": datetime.now(timezone.utc).isoformat()})
        write("model_lineage.json", {"previous_frozen_model": "V4 Model v2", "train_dataset": "V4 TRAIN Dataset v2", "dataset_v2_sha256": actual["dataset"], "may_role_for_model_v3_plus": "ADDITIVE_TRAIN_REUSE", "may_role_for_model_v2": "CONSUMED_INDEPENDENT_OOS_FOR_V4_MODEL_V2", "may_model_v2_oos_evidence_reinterpretation": "PROHIBITED", "feature_target_algorithm_selection_semantics": "UNCHANGED", "change_reason": "TRAIN_POPULATION_EXPANSION_ONLY"})
        write("training_validation.json", {"status": "PASS", "dataset_authority": "PASS", "runtime_validation": "PASS", "train_rows": 3240, "target_positive": 1108, "target_negative": 2132, "semantic_feature_count": 20, "transformed_feature_count": 21, "feature_transform": structure, "scaler_feature_order_equals_model_coefficient_order": True, "scaler_fit_count": 1, "model_fit_count": 1, "deterministic_refit_count": 1, "deterministic_reproduction": "PASS", "serialization_reload_prediction": "PASS", **{name: "PASS" if value else "FAIL" for name, value in sanity.items()}, "performance_evaluation_count": 0, "historical_oos_count": 0, "prospective_count": 0, "threshold_tuning_count": 0, "resampling_count": 0})
        write("training_manifest.json", {"status": "MODEL_V3_FIT_COMPLETE_FREEZE_READY", "model_v3_sha256": sha(OUT / "model.joblib"), "scaler_v3_sha256": sha(OUT / "scaler.joblib"), "model_metadata_v3_sha256": sha(OUT / "model_metadata.json"), "dataset_v2_sha256": actual["dataset"], "protocol_v2_sha256": actual["protocol"], "runtime_manifest_sha256": actual["runtime_manifest"], "feature_transform_schema_sha256": sha(OUT / "feature_transform_schema.json"), "frozen_artifact_integrity_before": before, "frozen_artifact_integrity_after": after, "model_status": "TRAINED_CANDIDATE"})
        write("artifact_hashes.json", {"indexed_artifacts": {path.name: sha(path) for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write("training_validation.json", {"status": "FAIL", "final_status": "V4_MODEL_V3_TRAINING_FAILED", "reason": str(exc), "model_fit_count": 0, "scaler_fit_count": 0, "performance_evaluation_count": 0})
        return OUT


if __name__ == "__main__":
    print(run())
