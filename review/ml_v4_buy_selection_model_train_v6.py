"""Train V4 Model v6 from the frozen v6 dataset using the unchanged V4 core recipe."""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import scipy
import sklearn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import review.ml_v4_buy_selection_model_train_v4 as v4

DATA = ROOT / "reports" / "ml_v4_buy_selection_dataset_v6"
PARENT_DATA = ROOT / "reports" / "ml_v4_buy_selection_dataset_v5"
PARENT_MODEL = ROOT / "reports" / "ml_v4_buy_selection_model_v5"
OUT = ROOT / "reports" / "ml_v4_buy_selection_model_v6"
EXPECTED_V5_MODEL_SHA = "d3b17e3022768690d0b1013ab131b35c5a64aa8e4a816fb3e1349bad95fb87a2"

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def protected_digest(path):
    if path.is_file(): return sha(path)
    h = hashlib.sha256()
    for item in sorted(x for x in path.rglob("*") if x.is_file()):
        h.update(item.relative_to(path).as_posix().encode())
        h.update(sha(item).encode())
    return h.hexdigest()
def dump(name, value): (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
def equal(a, b): return bool(np.array_equal(a, b))
def git(*args): return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
def load(path):
    with path.open(encoding="utf-8", newline="") as handle: return list(csv.DictReader(handle))

def reproduction(rows, cols, model_path, scaler_path):
    scaler, model, probabilities = v4.fit(rows, cols)
    frozen_model, frozen_scaler = joblib.load(model_path), joblib.load(scaler_path)
    matrix, _ = v4.matrix(rows, cols)
    frozen_probabilities = frozen_model.predict_proba(frozen_scaler.transform(matrix))[:, 1]
    return {"status":"PASS" if all((equal(scaler.mean_, frozen_scaler.mean_), equal(scaler.scale_, frozen_scaler.scale_), equal(model.coef_, frozen_model.coef_), equal(model.intercept_, frozen_model.intercept_), equal(probabilities, frozen_probabilities))) else "FAIL", "scaler_mean_exact":equal(scaler.mean_, frozen_scaler.mean_), "scaler_scale_exact":equal(scaler.scale_, frozen_scaler.scale_), "coef_exact":equal(model.coef_, frozen_model.coef_), "intercept_exact":equal(model.intercept_, frozen_model.intercept_), "predict_proba_exact":equal(probabilities, frozen_probabilities)}

def main():
    if OUT.exists(): raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    if sha(PARENT_MODEL / "model.joblib") != EXPECTED_V5_MODEL_SHA: raise RuntimeError("PARENT_V5_MODEL_SHA_MISMATCH")
    dm = json.loads((DATA / "dataset_manifest.json").read_text(encoding="utf-8")); dv = json.loads((DATA / "validation.json").read_text(encoding="utf-8"))
    if dm.get("status") != "FROZEN_TRAINING_DATASET" or dv.get("status") != "PASS" or dm.get("trainable_rows") != 6271: raise RuntimeError("V6_DATASET_INTEGRITY_FAILED")
    protected = [PARENT_DATA, PARENT_MODEL, ROOT / "reports" / "selection_authority_protocol_v1_january_2026_historical_holdout", ROOT / "review" / "ml_v4_buy_selection_model_train_v5.py"]
    before = {p.relative_to(ROOT).as_posix(): protected_digest(p) for p in protected}
    head, status = git("rev-parse", "HEAD"), git("status", "--porcelain")
    cols = v4.transformed_columns()
    parent_rows = load(PARENT_DATA / "dataset.csv")
    parent_repro = reproduction(parent_rows, cols, PARENT_MODEL / "model.joblib", PARENT_MODEL / "scaler.joblib")
    parent_repro.update({"parent_model_sha256":sha(PARENT_MODEL / "model.joblib"), "parent_scaler_sha256":sha(PARENT_MODEL / "scaler.joblib"), "parent_rows":len(parent_rows)})
    if parent_repro["status"] != "PASS": raise RuntimeError("STOP_PARENT_RECIPE_REPRODUCTION_FAILED")
    rows = load(DATA / "dataset.csv")
    if len(rows) != 6271: raise RuntimeError("V6_ROW_COUNT_MISMATCH")
    OUT.mkdir(parents=True)
    scaler1, model1, probability1 = v4.fit(rows, cols); scaler2, model2, probability2 = v4.fit(rows, cols)
    deterministic = {"status":"PASS" if all((equal(scaler1.mean_,scaler2.mean_),equal(scaler1.scale_,scaler2.scale_),equal(model1.coef_,model2.coef_),equal(model1.intercept_,model2.intercept_),equal(probability1,probability2))) else "FAIL", "scaler_mean_exact":equal(scaler1.mean_,scaler2.mean_), "scaler_scale_exact":equal(scaler1.scale_,scaler2.scale_), "coef_exact":equal(model1.coef_,model2.coef_), "intercept_exact":equal(model1.intercept_,model2.intercept_), "predict_proba_exact":equal(probability1,probability2)}
    if deterministic["status"] != "PASS": raise RuntimeError("STOP_V6_REPRODUCTION_FAILED")
    joblib.dump(model1, OUT / "model.joblib"); joblib.dump(scaler1, OUT / "scaler.joblib")
    matrix, target = v4.matrix(rows, cols); reloaded_model, reloaded_scaler = joblib.load(OUT / "model.joblib"), joblib.load(OUT / "scaler.joblib")
    if not equal(probability1, reloaded_model.predict_proba(reloaded_scaler.transform(matrix))[:, 1]): raise RuntimeError("V6_RELOAD_VALIDATION_FAILED")
    core = {"pipeline":["StandardScaler","LogisticRegression"], "penalty":"l2", "C":1.0, "solver":"lbfgs", "class_weight":None, "tuning":False, "threshold_search":False, "feature_selection_search":False}
    parent_recipe = json.loads((PARENT_MODEL / "training_recipe.json").read_text(encoding="utf-8"))
    if any(parent_recipe.get(k) != v for k, v in core.items()): raise RuntimeError("STOP_V5_RECIPE_IDENTITY_FAILED")
    runtime = {"python_executable":sys.executable, "python_version":sys.version, "implementation":platform.python_implementation(), "numpy":np.__version__, "scipy":scipy.__version__, "scikit_learn":sklearn.__version__, "joblib":joblib.__version__}
    dump("parent_v5_recipe_reproduction.json", parent_repro); dump("deterministic_reproduction.json", deterministic)
    dump("training_recipe.json", {**core, "authority":"review/ml_v4_buy_selection_model_train_v4.py fit", "parent_recipe_sha256":sha(PARENT_MODEL / "training_recipe.json"), "recipe_identity":"EXACT_V5_RECIPE", "change_class":"DATASET_EXPANSION_ONLY"})
    dump("feature_schema.json", {"model_name":"V4 Model v6", "semantic_feature_order":list(v4.SEMANTIC), "semantic_feature_count":20, "dataset_feature_schema_sha256":sha(DATA / "feature_schema.json"), "equal_to_v5":True})
    dump("feature_transform_schema.json", {"transformed_model_input_columns":cols, "transformed_input_count":21, "parent_v5_sha256":sha(PARENT_MODEL / "feature_transform_schema.json"), "equal_to_v5":True})
    dump("training_population.json", {"dataset":"ML_V4_TRAIN_DATASET_V6", "dataset_sha256":sha(DATA / "dataset.csv"), "source_dates":72, "source_races":2243, "source_horses":16935, "training_rows":len(rows), "parent_rows":5530, "january_added_rows":741, "positive":int(target.sum()), "negative":int(len(target)-target.sum()), "january_future_role":"TRAINING_ALLOWED_EVALUATION_PROHIBITED", "weighting":"NONE", "resampling":"NONE"})
    dump("runtime_environment.json", runtime)
    dump("model_metadata.json", {"model_name":"V4 Model v6", "model_version":"v6", "role":"DEVELOPMENT_CANDIDATE_ONLY", "no_auto_activation":True, "parent_model":"V4 Model v5", "parent_model_sha256":EXPECTED_V5_MODEL_SHA, "change_class":"DATASET_EXPANSION_ONLY", "training_start_date":"2026-01-04", "training_end_date":"2026-09-13", "training_dates":72, "training_rows":len(rows), "parent_rows":5530, "january_added_rows":741, "semantic_features":20, "transformed_columns":21, "dataset_sha256":sha(DATA / "dataset.csv"), "model_sha256":sha(OUT / "model.joblib"), "scaler_sha256":sha(OUT / "scaler.joblib"), "january_protocol_sha256":"77bccaf6d3f01e14b25c3e7564d7fd084f93511e64c021dd752269ab5bf00941", "january_result_manifest_sha256":"777216a9b26da55325102d82ed29dbb14df2390fbe5dc5de7ff033dc5051f458", "evaluation_prohibited":{"january_v6":True,"december_v6":True,"v6_performance":True}})
    dump("training_manifest.json", {"model":"V4 Model v6", "status":"FROZEN_DEVELOPMENT_CANDIDATE_ONLY", "dataset_sha256":sha(DATA / "dataset.csv"), "rows":len(rows), "positive":int(target.sum()), "negative":int(len(target)-target.sum()), "feature_count":21, "recipe_identity":"EXACT_V5_RECIPE", "parent_recipe_reproduction":"PASS", "double_fit_determinism":"PASS", "model_sha256":sha(OUT / "model.joblib"), "scaler_sha256":sha(OUT / "scaler.joblib"), "git_head":head, "timestamp":datetime.now(timezone.utc).isoformat()})
    dump("reload_validation.json", {"status":"PASS", "training_matrix_probability_exact":True, "model_sha256":sha(OUT / "model.joblib"), "scaler_sha256":sha(OUT / "scaler.joblib")})
    dump("parameter_delta_vs_v5.json", {"diagnostic_only":True, "coefficient_delta":(model1.coef_ - joblib.load(PARENT_MODEL / "model.joblib").coef_).tolist(), "intercept_delta":(model1.intercept_ - joblib.load(PARENT_MODEL / "model.joblib").intercept_).tolist(), "scaler_mean_delta":(scaler1.mean_ - joblib.load(PARENT_MODEL / "scaler.joblib").mean_).tolist(), "scaler_scale_delta":(scaler1.scale_ - joblib.load(PARENT_MODEL / "scaler.joblib").scale_).tolist()})
    after = {p.relative_to(ROOT).as_posix(): protected_digest(p) for p in protected}
    if before != after or git("rev-parse", "HEAD") != head: raise RuntimeError("PROTECTED_ZERO_DELTA_FAILED")
    dump("safety.json", {"status":"PASS", "protected_before":before, "protected_after":after, "git_head_before":head, "git_head_after":git("rev-parse","HEAD"), "git_status_before":status, "v5_model_change":0, "v5_dataset_change":0, "selection_authority_change":0, "january_evidence_change":0, "production_change":0, "january_v6_evaluation":0, "december_v6_inference":0, "git_commit":0, "git_push":0})
    (OUT / "report.md").write_text("# V4 Model v6 学習結果\n\nFrozen Dataset v6のみを入力に、V5と完全同一のV4 core recipeで学習しました。V6はDEVELOPMENT_CANDIDATE_ONLYであり、January・Decemberを含む性能評価およびactivationは未実行です。\n", encoding="utf-8")
    dump("artifact_index.json", {"self_hash_excluded":True, "indexed_artifacts":{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "artifact_index.json"}})
    return OUT

if __name__ == "__main__": print(main())
