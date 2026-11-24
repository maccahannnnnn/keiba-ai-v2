"""Stage A causal-isolation preflight only.

This intentionally does not fit a scaler/model, score horses, or produce
candidate selections.  It records whether the approved Full-field readiness
scope can be compared to the frozen V4 recipe by changing only population.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "candidate_generation_stage_a_full_field_v1"
READINESS = ROOT / "reports" / "candidate_generation_training_dataset_readiness_v1"
V4_DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v4"
V4_MODEL = ROOT / "reports" / "ml_v4_buy_selection_model_v4"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value) -> None:
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")

    readiness = load(READINESS / "training_dataset_readiness_summary.json")
    blocks = load(READINESS / "included_blocks.json")
    readiness_features = list(readiness["canonical_semantic_feature_order"])
    fullfield_dates = sorted({date for block in blocks for date in block["dates"]})

    model_manifest = load(V4_MODEL / "training_manifest.json")
    v4_recipe = load(V4_MODEL / "training_recipe.json")
    v4_schema = load(V4_MODEL / "feature_schema.json")
    v4_transform = load(V4_MODEL / "feature_transform_schema.json")
    source_inventory = load(V4_DATASET / "source_date_inventory.json")
    v4_dates = sorted(set(source_inventory["parent_dates"]) | set(source_inventory["march_dates"]))
    v4_cv = load(V4_MODEL / "development_cv.json")

    semantic_v4 = list(v4_schema["semantic_feature_order"])
    v4_only = sorted(set(v4_dates) - set(fullfield_dates))
    fullfield_only = sorted(set(fullfield_dates) - set(v4_dates))
    same_universe = not v4_only and not fullfield_only

    # V4 recorded a seven-block non-evidential CV with March retained in train;
    # the readiness artifact has no matching fold manifest because it only
    # establishes a 32-date Full-field buildability scope.
    v4_fold_blocks = [fold["validation_block"] for fold in v4_cv["folds"]]
    fold_assignment_recovered = bool(v4_fold_blocks)
    same_fold_assignment = False
    label_policy_same = True
    feature_recipe_same = semantic_v4 == readiness_features and len(semantic_v4) == 20
    model_recipe_same = (
        v4_recipe.get("pipeline") == ["StandardScaler", "LogisticRegression"]
        and v4_recipe.get("penalty") == "l2"
        and v4_recipe.get("C") == 1.0
        and v4_recipe.get("solver") == "lbfgs"
        and v4_recipe.get("class_weight") is None
        and v4_transform.get("transformed_input_count") == 21
    )
    only_population = same_universe and same_fold_assignment and label_policy_same and feature_recipe_same and model_recipe_same

    OUT.mkdir(parents=True)
    protocol = {
        "experiment": "CANDIDATE_GENERATION_STAGE_A_FULL_FIELD_V1",
        "evidence_role": "NON_EVIDENTIAL_DEVELOPMENT_EXPERIMENT",
        "stage_b_execution": "NO",
        "target": "HORSE_ACTUAL_TOP3_PROBABILITY",
        "candidate_output_volume": "EXACT5",
        "current_top5_role": "COMPARATOR_ONLY",
        "execution_status": "STOP_BEFORE_MODEL_FIT",
    }
    causal = {
        "CAUSAL_ISOLATION_PREFLIGHT": "STOP",
        "V4_RACE_DATE_UNIVERSE_RECOVERED": "YES",
        "FULLFIELD_RACE_DATE_UNIVERSE_RECOVERED": "YES",
        "SAME_RACE_DATE_UNIVERSE": "YES" if same_universe else "NO",
        "SAME_FOLD_ASSIGNMENT": "YES" if same_fold_assignment else "NO",
        "SAME_LABEL_POLICY": "YES" if label_policy_same else "NO",
        "SAME_FEATURE_RECIPE": "YES" if feature_recipe_same else "NO",
        "SAME_MODEL_RECIPE": "YES" if model_recipe_same else "NO",
        "ONLY_MAJOR_CHANGE_IS_TRAINING_POPULATION": "YES" if only_population else "NO",
        "stop_reason": "DATASET_SCOPE_RECONCILIATION_REQUIRED",
        "reason": "Frozen V4 recipe covers 45 dates while approved Full-field readiness covers 32 dates; no canonical Full-field fold assignment matching frozen V4's seven-block CV was recovered.",
    }
    data_scope = {
        "frozen_v4_date_count": len(v4_dates),
        "fullfield_readiness_date_count": len(fullfield_dates),
        "frozen_v4_only_dates": v4_only,
        "fullfield_only_dates": fullfield_only,
        "v4_dataset_rows": model_manifest["rows"],
        "fullfield_valid_rows": readiness["valid_rows"],
        "fullfield_races": readiness["race_count"],
        "april_data_access": 0,
        "untouched_holdout_access": 0,
        "future_result_access": 0,
    }
    fold_manifest = {
        "frozen_v4_fold_assignment_recovered": fold_assignment_recovered,
        "frozen_v4_fold_count": len(v4_fold_blocks),
        "frozen_v4_validation_blocks": v4_fold_blocks,
        "frozen_v4_protocol_note": "March remains training-only in all primary V4 development CV folds.",
        "fullfield_matching_fold_assignment_recovered": False,
        "same_fold_assignment": False,
        "result": "STOP",
    }
    feature_recipe = {
        "frozen_v4_semantic_feature_order": semantic_v4,
        "fullfield_semantic_feature_order": readiness_features,
        "semantic_feature_count": len(semantic_v4),
        "transformed_input_count": v4_transform["transformed_input_count"],
        "same_feature_recipe": feature_recipe_same,
    }
    model_recipe = {
        "pipeline": v4_recipe["pipeline"],
        "penalty": v4_recipe["penalty"],
        "C": v4_recipe["C"],
        "solver": v4_recipe["solver"],
        "class_weight": v4_recipe["class_weight"],
        "same_model_recipe": model_recipe_same,
    }
    training_audit = {
        "TRAINING_POPULATION": "NOT_STARTED_FULL_FIELD",
        "model_fit_count": 0,
        "scaler_fit_count": 0,
        "held_out_prediction_count": 0,
        "final_all_data_model_fit": 0,
        "top5_filter_use_count": 0,
        "reason": causal["stop_reason"],
    }
    assertions = {
        "causal_isolation_preflight": "FAIL_STOP",
        "same_race_date_universe": same_universe,
        "same_fold_assignment": same_fold_assignment,
        "same_label_policy": label_policy_same,
        "same_feature_recipe": feature_recipe_same,
        "same_model_recipe": model_recipe_same,
        "untouched_access_zero": True,
        "model_fit_performed": False,
    }
    ledger = {
        "experiment_name": "CANDIDATE_GENERATION_STAGE_A_FULL_FIELD_V1",
        "mechanism_family": "TRAINING_POPULATION_AXIS",
        "question": "Can a Full-field-trained candidate model improve candidate-set Top3 capture versus frozen Current Top5?",
        "status": "NOT_EXECUTED_CAUSAL_ISOLATION_STOP",
        "duplicate_relationship": "Top5-conditioned model to Full-field-trained Candidate Generator; no stable ANA/EXP ID assigned.",
        "evidence_role": "NON_EVIDENTIAL_DEVELOPMENT_EXPERIMENT",
    }
    safety = {
        "status": "PASS_STOP_BOUNDARY",
        "ENGINE_CHANGE": 0,
        "RACE_DECISION_ENGINE_CHANGE": 0,
        "CURRENT_BUY_EXECUTION": 0,
        "BUY_TOP3_RATE_EVALUATION": 0,
        "V4_FORMAL_RERUN": 0,
        "CF_EXECUTION": 0,
        "FEATURE_CHANGE": 0,
        "NEW_FEATURE_SEARCH": 0,
        "MODEL_FAMILY_CHANGE": 0,
        "HYPERPARAMETER_CHANGE": 0,
        "CLASS_WEIGHT_CHANGE": 0,
        "THRESHOLD_SEARCH": 0,
        "OUTPUT_VOLUME_CHANGE": 0,
        "PRODUCTION_CHANGE": 0,
        "PRODUCTION_MODEL_REGISTRATION": 0,
        "FORMAL_PROTOCOL_CHANGE": 0,
        "SOURCE_DATA_CHANGE": 0,
        "APRIL_ACCESS": 0,
        "UNTOUCHED_HOLDOUT_ACCESS": 0,
        "FUTURE_RESULT_ACCESS": 0,
        "FINAL_ALL_DATA_MODEL_FIT": 0,
        "ARTIFACT_HASH_VALIDATION": "PENDING",
    }
    for name, value in {
        "protocol.json": protocol,
        "causal_isolation_preflight.json": causal,
        "data_scope.json": data_scope,
        "fold_manifest.json": fold_manifest,
        "feature_recipe.json": feature_recipe,
        "model_recipe.json": model_recipe,
        "training_audit.json": training_audit,
        "assertion_audit.json": assertions,
        "ledger_entry_proposal.json": ledger,
        "safety.json": safety,
    }.items():
        write(name, value)
    (OUT / "report.md").write_text(
        "# Candidate Generation Stage A — Full-field Candidate Quality Model v1\n\n"
        "## 結果\n\n"
        "`CANDIDATE_GENERATION_STAGE_A_FULL_FIELD_V1 = STOP`\n\n"
        "凍結V4 Model v4の一次dataset inventoryは45日、承認済みFull-field readinessは32日です。"
        "さらに後者には凍結V4の7-block開発CVと同一のfold assignmentがありません。"
        "したがって、今回の差分はTraining Populationだけとは機械的に確認できず、"
        "`DATASET_SCOPE_RECONCILIATION_REQUIRED` とします。\n\n"
        "学習・scaler fit・held-out scoring・EXACT5生成・Current comparator・性能評価は一切実行していません。"
        "Aprilのraw/prediction/result、未使用Holdout、将来Resultにもアクセスしていません。\n",
        encoding="utf-8",
    )
    indexed = {p.name: {"sha256": sha(p), "size": p.stat().st_size} for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "artifact_hash_index.json"}
    write("artifact_hash_index.json", {"indexed_artifacts": indexed, "self_hash_excluded": True})
    return OUT


if __name__ == "__main__":
    print(main())
