"""One frozen V4 model fit plus mechanical sanity checks only."""
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
OUT = ROOT / "reports" / "ml_v4_buy_selection_model_v1"
DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v1"
PROTOCOL = ROOT / "reports" / "ml_v4_buy_selection_training_protocol_v1"
RUNTIME = ROOT / "reports" / "ml_v4_training_runtime_v1"
EXPECTED = {"dataset": "02d2471f11c1069ebb264946eacdc55fe3ea673c8812b6d17c8fd973af538b53", "feature_schema": "10f576bb55a23225c84634a5c79e21fa7f54ee239977d0faf8743042eb31aaa0", "dataset_manifest": "98a623a7561af504a3c6e69c7d357eb17e919522aedec8417b648c01e0707c38", "protocol": "97e783a8c63c7a8ff446b14bb7ec6f17001d43128eb215eda994b96be44d1ebd", "protocol_manifest": "847e9f94acc4e4d16c4efa4a8be774ba2e2a53fa82b2a0035ef2de5302fb5d2c", "runtime_requirements": "30a9ca043286755020691f7040ff0946c1427aa6fedae9daa04d0239e1998dff", "runtime_manifest": "efd36424206dfd54c16b0517d9832338bbb61f286a1725c2ddde6c69058182a5"}
STATES = ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP")
GATES = ("absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass")


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def truth(value: str, context: str) -> int:
    if value == "True":
        return 1
    if value == "False":
        return 0
    raise Stop(f"BOOLEAN_ENCODING_INVALID:{context}:{value!r}")


def finite(value: str, context: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise Stop(f"NUMERIC_FEATURE_INVALID:{context}") from exc
    if not math.isfinite(parsed):
        raise Stop(f"NUMERIC_FEATURE_NONFINITE:{context}")
    return parsed


def fit_once(x: np.ndarray, y: np.ndarray) -> tuple[StandardScaler, LogisticRegression, np.ndarray, list[str]]:
    scaler = StandardScaler()
    model = LogisticRegression(penalty="l2", C=1.0, solver="lbfgs", class_weight=None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        transformed = scaler.fit_transform(x)
        model.fit(transformed, y)
    warnings_text = [str(w.message) for w in caught if issubclass(w.category, ConvergenceWarning)]
    probabilities = model.predict_proba(transformed)[:, 1]
    return scaler, model, probabilities, warnings_text


def run() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        actual = {"dataset": sha(DATASET / "dataset.csv"), "feature_schema": sha(DATASET / "feature_schema.json"), "dataset_manifest": sha(DATASET / "dataset_manifest.json"), "protocol": sha(PROTOCOL / "training_protocol.md"), "protocol_manifest": sha(PROTOCOL / "protocol_manifest.json"), "runtime_requirements": sha(RUNTIME / "requirements_frozen.txt"), "runtime_manifest": sha(RUNTIME / "runtime_manifest.json")}
        if actual != EXPECTED:
            raise Stop(f"AUTHORITY_SHA_MISMATCH:{actual}")
        runtime = json.loads((RUNTIME / "runtime_validation.json").read_text(encoding="utf-8"))
        if runtime.get("status") != "PASS" or not all(runtime.get("package_versions_match", {}).values()):
            raise Stop("TRAINING_RUNTIME_NOT_READY")
        feature_schema = json.loads((DATASET / "feature_schema.json").read_text(encoding="utf-8"))
        transform = json.loads((PROTOCOL / "feature_transform_schema.json").read_text(encoding="utf-8"))
        features = feature_schema.get("feature_order")
        expected_columns = transform.get("transformed_model_input_columns")
        if not isinstance(features, list) or len(features) != 20 or transform.get("semantic_feature_order") != features or transform.get("transformed_model_input_column_count") != 21:
            raise Stop("FROZEN_TRANSFORM_SCHEMA_MISMATCH")
        rows = list(csv.DictReader((DATASET / "dataset.csv").open(encoding="utf-8", newline="")))
        if len(rows) != 2283:
            raise Stop(f"TRAIN_ROW_COUNT_MISMATCH:{len(rows)}")
        input_rows, target, row_ids = [], [], []
        for row in rows:
            row_id = row.get("row_id", "")
            if not row_id or row.get("current_top5") != "True" or row.get("valid_result") != "True":
                raise Stop(f"TRAIN_POPULATION_ROW_INVALID:{row_id}")
            state = row.get("race_state")
            if state not in STATES:
                raise Stop(f"UNKNOWN_RACE_STATE:{row_id}:{state}")
            values = []
            for feature in features:
                if feature == "race_state":
                    continue
                values.append(truth(row[feature], f"{row_id}:{feature}") if feature in GATES else finite(row[feature], f"{row_id}:{feature}"))
            values.extend([1 if state == "PLAY_UNCONVERGED_4PLUS" else 0, 1 if state == "SKIP" else 0])
            if len(values) != 21:
                raise Stop(f"MODEL_INPUT_COLUMN_COUNT_MISMATCH:{row_id}:{len(values)}")
            label = row.get("actual_top3")
            if label not in {"0", "1"}:
                raise Stop(f"TARGET_INVALID:{row_id}:{label!r}")
            input_rows.append(values); target.append(int(label)); row_ids.append(row_id)
        if len(set(row_ids)) != 2283:
            raise Stop("ROW_ID_DUPLICATE")
        x, y = np.asarray(input_rows, dtype=float), np.asarray(target, dtype=int)
        if x.shape != (2283, 21) or y.shape != (2283,) or int(y.sum()) != 783:
            raise Stop(f"TRAIN_SHAPE_OR_BALANCE_MISMATCH:{x.shape}:{y.shape}:{int(y.sum())}")
        scaler, model, probability, convergence_warnings = fit_once(x, y)
        if convergence_warnings:
            raise Stop(f"SOLVER_NON_CONVERGENCE:{convergence_warnings}")
        finite_coef = bool(np.isfinite(model.coef_).all())
        finite_intercept = bool(np.isfinite(model.intercept_).all())
        probability_ok = bool(np.isfinite(probability).all() and np.all((probability >= 0.0) & (probability <= 1.0)))
        nonconstant = bool(np.ptp(probability) > 0.0)
        if not (finite_coef and finite_intercept and probability_ok and nonconstant and len(probability) == len(row_ids)):
            raise Stop("POST_FIT_SANITY_FAILED")
        # This second fit is the specifically authorized deterministic-reproduction validator, not an alternative model.
        scaler2, model2, probability2, warnings2 = fit_once(x, y)
        deterministic = bool(not warnings2 and np.array_equal(scaler.mean_, scaler2.mean_) and np.array_equal(scaler.scale_, scaler2.scale_) and np.array_equal(model.coef_, model2.coef_) and np.array_equal(model.intercept_, model2.intercept_) and np.array_equal(probability, probability2))
        if not deterministic:
            raise Stop("DETERMINISTIC_REPRODUCTION_FAILED")
        joblib.dump(model, OUT / "model.joblib")
        joblib.dump(scaler, OUT / "scaler.joblib")
        coefficient_rows = [{"feature_name": name, "coefficient": float(value), "intercept": float(model.intercept_[0])} for name, value in zip(expected_columns, model.coef_[0], strict=True)]
        write("feature_transform_schema.json", {"source_protocol_sha256": actual["protocol"], "semantic_features": features, "semantic_feature_count": 20, "race_state_encoding": transform["categorical"]["race_state"], "gate_encoding": transform["boolean"], "transformed_model_input_columns": expected_columns, "transformed_model_input_column_count": 21})
        write("coefficient_table.json", {"intercept": float(model.intercept_[0]), "coefficients": coefficient_rows, "inspection_only": True, "feature_change_applied": False})
        write("model_output_schema.json", {"output_name": "RAW_MODEL_PROBABILITY", "semantic": "P(actual_top3)", "calibration": "NONE", "threshold_or_policy": "NOT_DEFINED_IN_TRAINING", "may_oos_evaluation": "NOT_EXECUTED"})
        write("governance_boundary.json", {"model_status": "TRAINED_CANDIDATE", "not_permitted": ["Production adoption", "BUY rule change", "SKIP override", "UNCONVERGED override", "CF change", "May access/evaluation before Claude independent review"], "may_status": "UNTOUCHED_INDEPENDENT_OOS", "production_change": 0, "cf_change": 0})
        metadata = {"model_name": "KeibaAI_V4_BUY_Selection_Model", "version": "V1", "algorithm": "LogisticRegression", "penalty": "l2", "C": 1.0, "solver": "lbfgs", "class_weight": None, "runtime": {"python": sys.version, "implementation": platform.python_implementation(), "numpy": np.__version__, "scikit_learn": sklearn.__version__, "scipy": scipy.__version__, "joblib": joblib.__version__}, "authority_sha256": actual, "train_rows": 2283, "target": {"semantic": "actual_top3", "positive": 783, "negative": 1500}, "semantic_feature_count": 20, "transformed_input_count": 21, "preprocessing": "StandardScaler fit on TRAIN only", "encoding": "race_state one-hot with PLAY_CONVERGED reference; gates bool 0/1", "output_semantic": "RAW_MODEL_PROBABILITY = P(actual_top3)", "training_timestamp": datetime.now(timezone.utc).isoformat(), "model_fit_count": 1, "scaler_fit_count": 1, "deterministic_reproduction_refit_count": 1}
        write("model_metadata.json", metadata)
        validation = {"model_training_status": "PASS", "training_runtime_validation": "PASS", "dataset_sha_validation": "PASS", "protocol_sha_validation": "PASS", "train_row_count": 2283, "semantic_feature_count": 20, "model_input_column_count": 21, "scaler_fit_count": 1, "model_fit_count": 1, "solver_convergence": "PASS", "finite_coefficient_check": "PASS", "finite_intercept_check": "PASS", "probability_sanity_check": "PASS", "row_alignment_check": "PASS", "degenerate_output_check": "PASS", "deterministic_reproduction": "PASS", "deterministic_reproduction_refit_count": 1, "train_performance_calculation_count": 0, "may_access_count": 0, "march_or_earlier_access_count": 0, "feature_selection": 0, "hyperparameter_tuning": 0, "class_weighting": 0, "resampling": 0, "calibration": 0, "threshold_tuning": 0, "oos_evaluation": 0}
        write("training_validation.json", validation)
        write("training_manifest.json", {"status": "MODEL_FIT_COMPLETE_FREEZE_READY", "model_sha256": sha(OUT / "model.joblib"), "scaler_sha256": sha(OUT / "scaler.joblib"), "model_metadata_sha256": sha(OUT / "model_metadata.json"), "dataset_sha256": actual["dataset"], "protocol_sha256": actual["protocol"], "runtime_manifest_sha256": actual["runtime_manifest"], "feature_transform_schema_sha256": sha(OUT / "feature_transform_schema.json"), "output_schema_sha256": sha(OUT / "model_output_schema.json"), "model_status": "TRAINED_CANDIDATE", "may_access_count": 0, "model_fit_count": 1, "scaler_fit_count": 1})
        write("artifact_hashes.json", {"indexed_artifacts": {p.name: sha(p) for p in OUT.iterdir() if p.is_file() and p.name != "artifact_hashes.json"}, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write("training_validation.json", {"model_training_status": "FAIL", "final_status": "V4_MODEL_V1_TRAINING_FAILED", "reason": str(exc), "model_fit_count": 0, "scaler_fit_count": 0, "may_access_count": 0, "march_or_earlier_access_count": 0})
        return OUT


if __name__ == "__main__":
    print(run())
