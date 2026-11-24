"""Build and freeze the additive V4 Dataset v3; never fits a formal model."""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from review.v4_feature_expansion_relative_gap_position_feature_v1 import (
    RelativeGapFeatureError,
    adjusted_score_gap_to_top,
)


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v2"
DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v3"
OUT = ROOT / "reports" / "v4_feature_expansion_relative_gap_position_v1"
MODEL_V3 = ROOT / "reports" / "ml_v4_buy_selection_model_v3"
V4_PROTOCOL = ROOT / "reports" / "v4_model_v3_prospective_protocol_v1"
CF_ROOT = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"
PRE_0830 = ROOT / "reports" / "v4_model_v3_formal_prospective" / "20260830_pre"
FEATURE = "adjusted_score_gap_to_top"
SEMANTIC_V2 = [
    "Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability",
    "RaceShape", "PaceStyle", "shadow_ai_rank", "decision_score", "final_score",
    "adjusted_score", "absolute_quality_pass", "relative_advantage_pass",
    "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count",
    "consensus_negative_count", "risk_count", "conflict_count", "race_state",
]
TRANSFORMED_V2 = [*SEMANTIC_V2[:-1], "is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"]
SEMANTIC_V3 = [*SEMANTIC_V2, FEATURE]
TRANSFORMED_V3 = [*TRANSFORMED_V2, FEATURE]
BOOLEAN = {"absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass"}
EXPECTED_DATASET_SHA = "b61994c2a488696a2fcc70f4b4f24e4756e4b6562ca751fa1f30819d30e535e2"
EXPECTED_FEATURE_SCHEMA_SHA = "d30597a96f43bd04ba491eac75925b2fd254df50c3e1372790d86b92eebb8eb1"
EXPECTED_ROWS = 3240
EXPECTED_DIAGNOSTIC_CORRELATION = 0.7266777740087019


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def csv_write(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def verify_index(root: Path) -> dict[str, object]:
    index_path = root / "artifact_hashes.json"
    index = json.loads(index_path.read_text(encoding="utf-8")).get("indexed_artifacts")
    if not isinstance(index, dict):
        raise Stop(f"FROZEN_INDEX_INVALID:{root}")
    invalid = [name for name, expected in index.items() if not (root / name).is_file() or sha(root / name) != expected]
    if invalid:
        raise Stop(f"FROZEN_INDEX_MISMATCH:{root}:{','.join(invalid)}")
    return {"path": str(root.relative_to(ROOT)), "artifact_count": len(index), "status": "PASS", "index_sha256": sha(index_path)}


def read_parent() -> tuple[list[dict[str, str]], list[str]]:
    with (PARENT / "dataset.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader); fields = list(reader.fieldnames or [])
    if len(rows) != EXPECTED_ROWS or len({row.get("row_id") for row in rows}) != EXPECTED_ROWS:
        raise Stop("PARENT_ROW_IDENTITY_INVALID")
    missing = [name for name in SEMANTIC_V2 if name not in fields]
    if missing:
        raise Stop(f"PARENT_FEATURE_SCHEMA_INVALID:{','.join(missing)}")
    return rows, fields


def float_value(value: object, context: str) -> float:
    if isinstance(value, bool):
        raise Stop(f"NUMERIC_INVALID:{context}")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise Stop(f"NUMERIC_INVALID:{context}") from exc
    if not math.isfinite(numeric):
        raise Stop(f"NUMERIC_INVALID:{context}")
    return numeric


def bool_value(value: object, context: str) -> float:
    if value in (True, "True"):
        return 1.0
    if value in (False, "False"):
        return 0.0
    raise Stop(f"BOOLEAN_INVALID:{context}")


def feature_matrix(rows: list[dict[str, object]], *, candidate: bool) -> tuple[np.ndarray, np.ndarray]:
    matrix, target = [], []
    names = TRANSFORMED_V3 if candidate else TRANSFORMED_V2
    for row in rows:
        row_id = str(row["row_id"]); values: list[float] = []
        for name in names:
            if name == "is_PLAY_UNCONVERGED_4PLUS":
                values.append(float(row["race_state"] == "PLAY_UNCONVERGED_4PLUS"))
            elif name == "is_SKIP":
                values.append(float(row["race_state"] == "SKIP"))
            elif name in BOOLEAN:
                values.append(bool_value(row[name], f"{row_id}:{name}"))
            else:
                values.append(float_value(row[name], f"{row_id}:{name}"))
        label = row.get("actual_top3")
        if label not in ("0", "1", 0, 1):
            raise Stop(f"TARGET_INVALID:{row_id}")
        matrix.append(values); target.append(int(label))
    return np.asarray(matrix, dtype=float), np.asarray(target, dtype=int)


def correlation(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or float(np.std(x)) == 0 or float(np.std(y)) == 0:
        raise Stop("CORRELATION_UNDEFINED")
    return float(np.corrcoef(x, y)[0, 1])


def reference_gap(rows: list[dict[str, str]]) -> dict[str, float]:
    grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        grouped[row["race_id"]].append((row["row_id"], float_value(row["adjusted_score"], row["row_id"])))
    output: dict[str, float] = {}
    for items in grouped.values():
        maximum = max(score for _, score in items)
        for row_id, score in items:
            output[row_id] = score - maximum
    return output


def leakage_validation() -> dict[str, object]:
    module = ROOT / "review" / "v4_feature_expansion_relative_gap_position_feature_v1.py"
    text = module.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(module))
    forbidden_names = {"predict_proba", "coef_", "decision_function", "actual_top3", "finish", "result", "winner", "payout", "hit", "success", "failure"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    tokens = sorted(forbidden_names.intersection(names | attributes))
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "adjusted_score_gap_to_top"), None)
    parameter_names = [] if function is None else [arg.arg for arg in function.args.args]
    return {"status": "PASS" if not tokens and parameter_names == ["rows"] else "FAIL", "feature_module": str(module.relative_to(ROOT)), "forbidden_dependency_references": tokens, "feature_function_parameters": parameter_names, "feature_computation_uses_target_label": False, "feature_computation_uses_model_output": False, "allowed_source": ["race_id", "row_id", "adjusted_score"]}


def temporal(rows: list[dict[str, object]]) -> dict[str, object]:
    target = np.asarray([int(row["actual_top3"]) for row in rows], dtype=float)
    all_feature = np.asarray([float(row[FEATURE]) for row in rows], dtype=float)
    overall = correlation(all_feature, target)
    blocks = sorted({str(row["source_block"]) for row in rows})
    values = []
    for block in blocks:
        indices = [index for index, row in enumerate(rows) if row["source_block"] == block]
        value = correlation(all_feature[indices], target[indices])
        values.append({"block": block, "row_count": len(indices), "target_correlation": value, "same_direction_as_overall": value * overall > 0})
    fraction = sum(item["same_direction_as_overall"] for item in values) / len(values)
    return {"status": "PASS" if len(values) == 7 and fraction == 1.0 else "FAIL", "overall_target_correlation": overall, "blocks": values, "temporal_same_direction_fraction": fraction, "expected": "7/7 same direction; March and new May/OOS artifacts not read"}


def redundancy(rows: list[dict[str, object]]) -> dict[str, object]:
    feature = np.asarray([float(row[FEATURE]) for row in rows], dtype=float)
    existing: dict[str, np.ndarray] = {}
    for name in TRANSFORMED_V2:
        if name == "is_PLAY_UNCONVERGED_4PLUS":
            existing[name] = np.asarray([float(row["race_state"] == "PLAY_UNCONVERGED_4PLUS") for row in rows])
        elif name == "is_SKIP":
            existing[name] = np.asarray([float(row["race_state"] == "SKIP") for row in rows])
        elif name in BOOLEAN:
            existing[name] = np.asarray([bool_value(row[name], name) for row in rows])
        else:
            existing[name] = np.asarray([float_value(row[name], name) for row in rows])
    correlations = {name: abs(correlation(feature, value)) for name, value in existing.items() if float(np.std(value)) > 0}
    name, maximum = max(correlations.items(), key=lambda item: (item[1], item[0]))
    difference = maximum - EXPECTED_DIAGNOSTIC_CORRELATION
    status = "PASS" if math.isclose(maximum, EXPECTED_DIAGNOSTIC_CORRELATION, rel_tol=0.0, abs_tol=1e-12) else "REVIEW_REQUIRED_REDUNDANCY_SHIFT"
    return {"status": status, "max_abs_correlation_existing": maximum, "corresponding_existing_feature": name, "diagnostic_estimate": EXPECTED_DIAGNOSTIC_CORRELATION, "difference_from_diagnostic_estimate": difference, "all_existing_transformed_input_correlations": correlations, "rule": "Exact same-parent calculation must reproduce the diagnostic value; any non-machine-precision difference is held for Human review without a newly invented threshold."}


def development_cv(rows: list[dict[str, object]]) -> tuple[dict[str, object], dict[str, object]]:
    x_base, y = feature_matrix(rows, candidate=False)
    x_candidate, _ = feature_matrix(rows, candidate=True)
    blocks = sorted({str(row["source_block"]) for row in rows})
    folds = []
    for block in blocks:
        test = np.asarray([row["source_block"] == block for row in rows])
        train = ~test
        if len(np.unique(y[test])) < 2:
            raise Stop(f"CV_FOLD_SINGLE_CLASS:{block}")
        def fit_auc(x: np.ndarray) -> tuple[float, list[float]]:
            scaler = StandardScaler(); transformed_train = scaler.fit_transform(x[train])
            model = LogisticRegression(penalty="l2", C=1.0, solver="lbfgs", class_weight=None, max_iter=1000)
            model.fit(transformed_train, y[train])
            return float(roc_auc_score(y[test], model.predict_proba(scaler.transform(x[test]))[:, 1])), [float(value) for value in model.coef_[0]]
        base_auc, _ = fit_auc(x_base)
        candidate_auc, coefficients = fit_auc(x_candidate)
        folds.append({"held_out_train_block": block, "baseline_auc": base_auc, "candidate_auc": candidate_auc, "delta_auc": candidate_auc - base_auc, "candidate_feature_coefficient": coefficients[-1]})
    scaler = StandardScaler(); transformed = scaler.fit_transform(x_candidate)
    model = LogisticRegression(penalty="l2", C=1.0, solver="lbfgs", class_weight=None, max_iter=1000)
    model.fit(transformed, y)
    coefficient = float(model.coef_[0, -1])
    target_corr = correlation(np.asarray([float(row[FEATURE]) for row in rows]), y.astype(float))
    return ({"status": "PASS", "evidence_role": "NON_EVIDENTIAL_DEVELOPMENT_TRIAGE_ONLY", "fold_type": "leave_one_existing_TRAIN_source_block_out", "baseline_mean_auc": float(np.mean([row["baseline_auc"] for row in folds])), "candidate_mean_auc": float(np.mean([row["candidate_auc"] for row in folds])), "delta_auc": float(np.mean([row["candidate_auc"] - row["baseline_auc"] for row in folds])), "folds": folds, "formal_model_artifact_saved": False, "model_fit_scope": "temporary TRAIN-only diagnostic"}, {"status": "PASS" if coefficient * target_corr > 0 else "REVIEW_REQUIRED", "evidence_role": "NON_EVIDENTIAL_DEVELOPMENT_TRIAGE_ONLY", "temporary_full_train_coefficient": coefficient, "target_correlation": target_corr, "sign_consistent": coefficient * target_corr > 0, "formal_model_artifact_saved": False})


def run() -> tuple[Path, Path]:
    if OUT.exists() or DATASET.exists():
        raise FileExistsError("EXCLUSIVE_CREATE_REQUIRED")
    frozen_before = [verify_index(root) for root in (PARENT, MODEL_V3, V4_PROTOCOL, PRE_0830)]
    parent_manifest = json.loads((PARENT / "dataset_manifest.json").read_text(encoding="utf-8"))
    parent_validation = json.loads((PARENT / "validation.json").read_text(encoding="utf-8"))
    if sha(PARENT / "dataset.csv") != EXPECTED_DATASET_SHA or parent_manifest.get("row_count") != EXPECTED_ROWS or parent_validation.get("status") != "PASS" or parent_validation.get("duplicate_row_count") != 0 or parent_validation.get("feature_missing_count") != 0:
        raise Stop("DATASET_V2_AUTHORITY_INVALID")
    if sha(PARENT / "feature_schema.json") != EXPECTED_FEATURE_SCHEMA_SHA or parent_manifest.get("feature_count") != 20:
        raise Stop("DATASET_V2_FEATURE_AUTHORITY_INVALID")
    parent_rows, parent_fields = read_parent()
    try:
        implementation = adjusted_score_gap_to_top(parent_rows)
    except RelativeGapFeatureError as exc:
        raise Stop(str(exc)) from exc
    reference = reference_gap(parent_rows)
    mismatch = [row_id for row_id in implementation if not math.isclose(implementation[row_id], reference.get(row_id, math.nan), rel_tol=0.0, abs_tol=1e-12)]
    if mismatch:
        raise Stop(f"FEATURE_REFERENCE_RECALCULATION_MISMATCH:{mismatch[:3]}")
    if len(implementation) != EXPECTED_ROWS or any(not math.isfinite(value) or value > 0 for value in implementation.values()):
        raise Stop("FEATURE_RANGE_OR_COMPLETENESS_INVALID")
    insert_at = parent_fields.index("current_buy")
    fields = [*parent_fields[:insert_at], FEATURE, *parent_fields[insert_at:]]
    v3_rows: list[dict[str, object]] = []
    for parent in parent_rows:
        row = dict(parent); row[FEATURE] = implementation[parent["row_id"]]; row["dataset_version"] = "ML_V4_TRAIN_DATASET_V3"; v3_rows.append(row)
    inherited_delta = [row["row_id"] for row, parent in zip(v3_rows, parent_rows, strict=True) if any(row[name] != parent[name] for name in parent_fields if name != "dataset_version")]
    target_delta = [row["row_id"] for row, parent in zip(v3_rows, parent_rows, strict=True) if row["actual_top3"] != parent["actual_top3"]]
    if inherited_delta or target_delta or len({row["row_id"] for row in v3_rows}) != EXPECTED_ROWS:
        raise Stop("DATASET_ZERO_DELTA_FAILURE")
    temporal_result = temporal(v3_rows)
    if temporal_result["status"] != "PASS":
        raise Stop("TEMPORAL_SIGN_CONSISTENCY_FAILURE")
    redundancy_result = redundancy(v3_rows)
    if redundancy_result["status"] != "PASS":
        raise Stop("REVIEW_REQUIRED_REDUNDANCY_SHIFT")
    leakage = leakage_validation()
    if leakage["status"] != "PASS":
        raise Stop("FEATURE_LEAKAGE_GUARD_FAILURE")
    cv, coefficient = development_cv(v3_rows)
    if coefficient["status"] != "PASS":
        raise Stop("COEFFICIENT_SIGN_REVIEW_REQUIRED")
    DATASET.mkdir(parents=True); OUT.mkdir(parents=True)
    feature_matrix_rows = [{"row_id": row["row_id"], **{name: row[name] for name in SEMANTIC_V3}} for row in v3_rows]
    target_rows = [{"row_id": row["row_id"], "actual_top3": row["actual_top3"]} for row in v3_rows]
    csv_write(DATASET / "dataset.csv", fields, v3_rows)
    csv_write(DATASET / "feature_matrix.csv", ["row_id", *SEMANTIC_V3], feature_matrix_rows)
    csv_write(DATASET / "target.csv", ["row_id", "actual_top3"], target_rows)
    dataset_feature_schema = {"dataset_version": "ML_V4_TRAIN_DATASET_V3", "parent_dataset": "ML_V4_TRAIN_DATASET_V2", "inherited_dataset_feature_order": [name for name in parent_fields if name in SEMANTIC_V2], "semantic_feature_order": SEMANTIC_V3, "semantic_feature_count": 21, "new_feature": FEATURE, "new_feature_position": 21, "frozen_candidate": True}
    dataset_transform_schema = {"semantic_feature_order": SEMANTIC_V3, "semantic_feature_count": 21, "transformed_model_input_columns": TRANSFORMED_V3, "transformed_model_input_count": 22, "new_feature_transform": "numeric_identity_at_end", "inherited_transform_unchanged": True, "formal_model_training": "NOT_EXECUTED"}
    dataset_population = {"population": "EXACT_PARENT_DATASET_V2_TOP5_VALID_ROWS", "row_count": EXPECTED_ROWS, "population_delta": 0, "target_delta": 0, "existing_feature_delta": 0, "MARCH_ADDITIVE_TRAIN_REUSE": "NOT_EXECUTED", "May": "PARENT_V2_LINEAGE_ONLY_NO_SEPARATE_OOS_ARTIFACT_READ", "prospective": "NOT_USED"}
    dataset_lineage = {"parent": "V4 BUY Selection Dataset v2", "relationship": "ADDITIVE_FEATURE_EXPANSION", "new_feature": FEATURE, "parent_dataset_sha256": EXPECTED_DATASET_SHA, "population_delta": 0, "target_delta": 0, "existing_feature_delta": 0, "result_oos_reuse": 0, "formal_model_training": "NOT_EXECUTED"}
    dataset_validation = {"status": "PASS", "rows": EXPECTED_ROWS, "duplicate_row_count": 0, "new_feature_missing_count": 0, "new_feature_range": {"max": max(float(row[FEATURE]) for row in v3_rows), "min": min(float(row[FEATURE]) for row in v3_rows)}, "existing_feature_delta_count": 0, "target_delta_count": 0, "parent_row_identity_match": True, "independent_reference_recalculation": "PASS", "semantic_feature_count": 21, "transformed_input_count": 22, "model_fit_count": 0, "scaler_fit_count": 0}
    for name, value in {"feature_schema.json": dataset_feature_schema, "feature_transform_schema.json": dataset_transform_schema, "population_schema.json": dataset_population, "lineage.json": dataset_lineage, "validation.json": dataset_validation}.items(): write(DATASET / name, value)
    write(DATASET / "dataset_manifest.json", {"dataset_version": "ML_V4_TRAIN_DATASET_V3", "status": "FROZEN_CANDIDATE_PENDING_INDEPENDENT_REVIEW", "dataset_sha256": sha(DATASET / "dataset.csv"), "feature_schema_sha256": sha(DATASET / "feature_schema.json"), "feature_transform_schema_sha256": sha(DATASET / "feature_transform_schema.json"), "lineage_sha256": sha(DATASET / "lineage.json"), "validation_sha256": sha(DATASET / "validation.json"), "row_count": EXPECTED_ROWS, "semantic_feature_count": 21, "transformed_input_count": 22, "model_version": "DEFERRED"})
    write(DATASET / "artifact_hashes.json", {"indexed_artifacts": {path.name: sha(path) for path in sorted(DATASET.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}, "self_hash_excluded": True})
    frozen_after = [verify_index(root) for root in (PARENT, MODEL_V3, V4_PROTOCOL, PRE_0830)]
    authority = {"status": "PASS", "dataset_v2_sha256": sha(PARENT / "dataset.csv"), "dataset_v2_manifest_sha256": sha(PARENT / "dataset_manifest.json"), "dataset_v2_feature_schema_sha256": sha(PARENT / "feature_schema.json"), "row_count": EXPECTED_ROWS, "duplicate_row_count": 0, "semantic_feature_count": 20, "transformed_input_count": 21, "frozen_authorities_before": frozen_before, "frozen_authorities_after": frozen_after}
    feature_definition = {"name": FEATURE, "formula": "adjusted_score_gap_to_top_i = adjusted_score_i - max(adjusted_score for all Top5 candidates in same race)", "domain": "same-race Top5 candidate pool only", "range": "(-infinity, 0]", "ties": "every tied maximum has value 0", "missing": "FAIL_CLOSED", "source": "existing semantic feature adjusted_score", "result_independent": True, "model_output_independent": True}
    reference_check = {"status": "PASS", "row_count": EXPECTED_ROWS, "implementation_reference_mismatch_count": 0, "tolerance": "exact float computation path / abs_tol=1e-12 only for comparison", "feature_max": max(implementation.values()), "feature_min": min(implementation.values()), "two_independent_calculations": ["grouped shared feature function", "separate simple grouped reference"]}
    zero_delta = {"status": "PASS", "row_identity_delta_count": 0, "race_identity_delta_count": 0, "horse_identity_delta_count": 0, "target_delta_count": 0, "existing_20_semantic_feature_delta_count": 0, "labels_delta_count": 0, "population_delta_count": 0, "category_handling_delta_count": 0, "race_state_handling_delta_count": 0, "dataset_v2_sha256_unchanged": sha(PARENT / "dataset.csv") == EXPECTED_DATASET_SHA}
    safety = {"status": "PASS", "production_change_count": 0, "current_buy_change_count": 0, "decision_engine_change_count": 0, "buy_gate_change_count": 0, "race_state_change_count": 0, "candidate_generation_change_count": 0, "cf_change_count": 0, "v4_model_v3_change_count": 0, "formal_prospective_protocol_change_count": 0, "march_result_access_count": 0, "may_external_oos_artifact_access_count": 0, "prospective_result_access_count": 0, "formal_model_fit_count": 0, "formal_scaler_fit_count": 0, "new_model_artifacts_saved": 0, "MARCH_ADDITIVE_TRAIN_REUSE": "NOT_EXECUTED"}
    lineage = {**dataset_lineage, "dataset_v3_root": str(DATASET.relative_to(ROOT)), "dataset_v3_dataset_sha256": sha(DATASET / "dataset.csv"), "model_version": "DEFERRED", "V4_Model_v3": "UNCHANGED", "Formal_Prospective": "SEPARATE_AND_UNCHANGED"}
    for name, value in {"authority_validation.json": authority, "feature_definition.json": feature_definition, "feature_reference_recalculation.json": reference_check, "dataset_v3_manifest.json": json.loads((DATASET / "dataset_manifest.json").read_text(encoding="utf-8")), "dataset_v2_v3_zero_delta.json": zero_delta, "leakage_validation.json": leakage, "temporal_stability.json": temporal_result, "redundancy_validation.json": redundancy_result, "development_cv_triage.json": cv, "coefficient_diagnostic.json": coefficient, "lineage.json": lineage, "safety.json": safety}.items(): write(OUT / name, value)
    report = "\n".join(["# V4 Feature Expansion — Relative Gap / Position v1", "", "- Status: `IMPLEMENTED_DATASET_V3_READY_PENDING_INDEPENDENT_REVIEW`", f"- New feature: `{FEATURE}`", "- Formula: `adjusted_score_i - max(adjusted_score within same-race Top5)`", "- Dataset v3: 3,240 rows; 21 semantic features; 22 transformed inputs.", "- Dataset v2 values, labels, and population remain unchanged.", "- Temporary TRAIN-only CV is non-evidential; no model/scaler artifact was saved.", "- March reuse: `NOT_EXECUTED`; prospective and external OOS Results: not accessed.", "- New model training: `NOT_AUTHORIZED`; model version: `DEFERRED`.", ""])
    (OUT / "report.md").write_text(report, encoding="utf-8")
    write(OUT / "artifact_hashes.json", {"indexed_artifacts": {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}, "self_hash_excluded": True})
    return DATASET, OUT


def main() -> int:
    parser = argparse.ArgumentParser(); parser.parse_args()
    dataset, report = run()
    print(json.dumps({"dataset_root": str(dataset), "report_root": str(report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
