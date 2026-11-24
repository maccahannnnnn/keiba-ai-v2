"""Build the additive, PRE-safe correction of the frozen V5 training dataset.

The frozen V5 package is read only.  This builder derives every feature from
the referenced prediction artifacts and changes only the approved
``adjusted_score_gap_to_top`` values in a new V5.1 package.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.ml_v4_buy_selection_dataset_build_v1 import csv_write
from review.ws2_data_integrity_preflight_v2_source_bound import materialize_prediction_rows


FROZEN_V5 = ROOT / "reports" / "ml_v4_buy_selection_dataset_v5"
OUT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v5_1"
FROZEN_V5_DATASET_SHA256 = "15c77e5c13ccbff2255912fa5440e68baf43e0df753218d84420d4bf29da3b3a"
EXPECTED_DELTA_ROW_IDS = frozenset({
    "20260801:race_20260801_sapporo_10R:1",
    "20260801:race_20260801_sapporo_10R:3",
    "20260801:race_20260801_sapporo_10R:7",
    "20260801:race_20260801_sapporo_10R:11",
    "20260815:race_20260815_sapporo_9R:1",
    "20260815:race_20260815_sapporo_9R:2",
    "20260815:race_20260815_sapporo_9R:4",
    "20260815:race_20260815_sapporo_9R:8",
})
GAP = "adjusted_score_gap_to_top"


class Stop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _numeric_equal(left: Any, right: Any) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return str(left).lower() == str(right).lower()


def pre_result_current_top5_gaps(payload: dict[str, Any]) -> dict[str, float]:
    """Return PRE-only gaps against the maximum among Current Top5 horses."""
    ranked = payload.get("ranked_results")
    if not isinstance(ranked, list):
        raise Stop("PREDICTION_RANKED_RESULTS_INVALID")
    top5 = [
        row for row in ranked
        if isinstance(row, dict) and isinstance(row.get("rank"), int) and row["rank"] <= 5
    ]
    if not top5:
        raise Stop("CURRENT_TOP5_POPULATION_MISSING")
    scores: dict[str, float] = {}
    for row in top5:
        number, score = str(row.get("horse_number")), row.get("adjusted_score")
        if number in scores or not isinstance(score, (int, float)):
            raise Stop("CURRENT_TOP5_ADJUSTED_SCORE_INVALID")
        scores[number] = float(score)
    top_score = max(scores.values())
    return {number: score - top_score for number, score in scores.items()}


def _read_frozen_rows() -> tuple[list[str], list[dict[str, str]]]:
    dataset = FROZEN_V5 / "dataset.csv"
    if sha256(dataset) != FROZEN_V5_DATASET_SHA256:
        raise Stop("FROZEN_V5_DATASET_HASH_MISMATCH")
    with dataset.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = list(reader.fieldnames or []), list(reader)
    if len(rows) != 5530 or GAP not in fields or len({row.get("row_id") for row in rows}) != len(rows):
        raise Stop("FROZEN_V5_DATASET_STRUCTURE_INVALID")
    return fields, rows


def _prediction_values(rows: list[dict[str, str]]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, float]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_prediction_artifact_path"].replace("\\", "/")].append(row)
    artifacts, per_artifact_gaps = [], {}
    for relative, linked_rows in grouped.items():
        path = ROOT / relative
        if not path.is_file() or any(row["source_prediction_artifact_sha256"] != sha256(path) for row in linked_rows):
            raise Stop("PREDICTION_ARTIFACT_IDENTITY_MISMATCH")
        payload = _json(path)
        gaps = pre_result_current_top5_gaps(payload)
        per_artifact_gaps[relative] = gaps
        artifacts.append({**payload, "_ws2_artifact_path": relative, "_ws2_artifact_sha256": sha256(path)})
    values, _ = materialize_prediction_rows(artifacts, "PRE_ONLY")
    return values, per_artifact_gaps


def _feature_audit(rows: list[dict[str, str]], values: dict[tuple[str, str], dict[str, Any]], features: list[str]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for row in rows:
        source = values.get((row["race_id"], row["horse_number"]))
        if not source or not source["top5"]:
            raise Stop("CURRENT_TOP5_SOURCE_LINEAGE_UNPROVEN")
        for feature in features:
            canonical = source["values"].get(feature)
            if canonical is None or not _numeric_equal(row.get(feature), canonical):
                mismatches.append({
                    "row_id": row["row_id"], "date": row["date"], "race_id": row["race_id"],
                    "horse_number": row["horse_number"], "feature": feature,
                    "dataset_value": row.get(feature), "canonical_value": canonical,
                })
    return mismatches


def assert_only_gap_changes(
    frozen_rows: list[dict[str, str]], corrected_rows: list[dict[str, str]], fields: list[str],
) -> None:
    """Fail closed unless the rebuild changed only the approved feature."""
    if len(frozen_rows) != len(corrected_rows):
        raise Stop("DATASET_ROW_COUNT_CHANGED")
    for before, after in zip(frozen_rows, corrected_rows):
        changed = {key for key in fields if before.get(key) != after.get(key)}
        if changed - {GAP}:
            raise Stop("NON_GAP_DATASET_VALUE_CHANGED")


def build() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    fields, frozen_rows = _read_frozen_rows()
    feature_schema = _json(FROZEN_V5 / "feature_schema.json")
    features = list(feature_schema.get("semantic_feature_order", []))
    if len(features) != 21 or GAP not in features:
        raise Stop("FROZEN_V5_FEATURE_SCHEMA_INVALID")
    values, artifact_gaps = _prediction_values(frozen_rows)
    corrected_rows, deltas = [], []
    for frozen in frozen_rows:
        row = dict(frozen)
        relative = row["source_prediction_artifact_path"].replace("\\", "/")
        expected = artifact_gaps[relative].get(row["horse_number"])
        if expected is None:
            raise Stop("CURRENT_TOP5_GAP_SOURCE_UNPROVEN")
        if not _numeric_equal(row[GAP], expected):
            deltas.append({
                "row_id": row["row_id"], "date": row["date"], "race_id": row["race_id"],
                "horse_number": row["horse_number"], "old_value": row[GAP], "new_value": repr(expected),
                "source_prediction_artifact_path": relative,
                "source_prediction_artifact_sha256": row["source_prediction_artifact_sha256"],
            })
        row[GAP] = repr(expected)
        corrected_rows.append(row)
    if {item["row_id"] for item in deltas} != EXPECTED_DELTA_ROW_IDS or len(deltas) != 8:
        raise Stop("UNEXPECTED_ADJUSTED_SCORE_GAP_DELTA")
    assert_only_gap_changes(frozen_rows, corrected_rows, fields)
    feature_mismatches = _feature_audit(corrected_rows, values, features)
    if feature_mismatches:
        raise Stop("CORRECTED_DATASET_FEATURE_AUDIT_MISMATCH")
    OUT.mkdir(parents=True)
    csv_write(OUT / "dataset.csv", fields, corrected_rows)
    csv_write(OUT / "feature_matrix.csv", ["row_id", *features], [
        {"row_id": row["row_id"], **{feature: row[feature] for feature in features}}
        for row in corrected_rows
    ])
    csv_write(OUT / "target.csv", ["row_id", "actual_top3"], [
        {"row_id": row["row_id"], "actual_top3": row["actual_top3"]} for row in corrected_rows
    ])
    for name in ("source_date_manifest.json", "exclusion_manifest.json"):
        (OUT / name).write_bytes((FROZEN_V5 / name).read_bytes())
    _dump(OUT / "feature_schema.json", {
        "dataset_version": "ML_V4_TRAIN_DATASET_V5_1_CORRECTED",
        "base_dataset": "ML_V4_TRAIN_DATASET_V5",
        "semantic_feature_order": features,
        "adjusted_score_gap_to_top_scope": "CURRENT_TOP5_PRE_RESULT",
        "result_dependent_feature_derivation": "PROHIBITED",
    })
    _dump(OUT / "dataset_manifest.json", {
        "dataset_version": "ML_V4_TRAIN_DATASET_V5_1_CORRECTED",
        "status": "CORRECTED_DATASET_NOT_TRAINED",
        "dataset_sha256": sha256(OUT / "dataset.csv"), "row_count": len(corrected_rows),
        "feature_count": len(features), "corrected_feature": GAP, "corrected_value_cells": len(deltas),
    })
    _dump(OUT / "training_manifest.json", {
        "dataset_version": "ML_V4_TRAIN_DATASET_V5_1_CORRECTED", "status": "NOT_TRAINED",
        "training": "PROHIBITED_BY_THIS_REBUILD", "dataset_sha256": sha256(OUT / "dataset.csv"),
    })
    _dump(OUT / "lineage.json", {
        "parent": "ML_V4_TRAIN_DATASET_V5", "parent_dataset_sha256": FROZEN_V5_DATASET_SHA256,
        "relationship": "ADDITIVE_PRE_SAFE_FEATURE_CORRECTION", "corrected_feature": GAP,
        "feature_definition": "CURRENT_TOP5_PRE_RESULT",
    })
    _dump(OUT / "correction_delta.json", {"feature": GAP, "delta_count": len(deltas), "deltas": deltas})
    _dump(OUT / "validation.json", {
        "status": "PASS", "row_count": len(corrected_rows), "feature_cell_count": len(corrected_rows) * len(features),
        "semantic_value_mismatch_count": len(feature_mismatches), "representation_only_mismatch_count": 0,
        "result_dependent_feature_value_count": 0, "adjusted_score_gap_delta_count": len(deltas),
        "all_non_gap_dataset_values_unchanged": True,
    })
    _dump(OUT / "frozen_v5_status.json", {
        "FROZEN_V5_TRAINING_DATA_INTEGRITY": "KNOWN_RESULT_LEAKAGE_8_FEATURE_VALUES",
        "FROZEN_V5_ARTIFACT": "PRESERVED", "FROZEN_V5_IN_PLACE_RETRAIN": "PROHIBITED",
        "FROZEN_V5_FUTURE_FORMAL_ADVANCEMENT": "NOT_ELIGIBLE",
        "allowed_role": "LEGACY_CONTAMINATED_TRAINING_DIAGNOSTIC_ONLY",
    })
    _dump(OUT / "safety.json", {
        "frozen_v5_dataset_sha256": FROZEN_V5_DATASET_SHA256,
        "frozen_v5_model_artifact_index_sha256": sha256(ROOT / "reports/ml_v4_buy_selection_model_v5/artifact_hash_index.json"),
        "frozen_v5_changed": False, "model_retrain_executed": False, "prediction_execution": False,
        "result_used_for_feature_computation": False,
    })
    (OUT / "report.md").write_text(
        "# V5.1 corrected dataset\n\n"
        "`adjusted_score_gap_to_top` is reconstructed from the complete Current Top5 PRE population before any Result validity filter. "
        "The frozen V5 dataset and model remain unchanged.\n",
        encoding="utf-8",
    )
    _dump(OUT / "artifact_hash_index.json", {
        "self_hash_excluded": True,
        "indexed_artifacts": {path.name: sha256(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hash_index.json"},
    })
    return OUT


if __name__ == "__main__":
    print(build())
