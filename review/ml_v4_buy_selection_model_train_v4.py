"""One-shot formal V4 Model v4 training from Dataset v4, without Relative Gap."""
from __future__ import annotations

import csv, hashlib, json, platform, subprocess, sys, warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib, numpy as np, scipy, sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1]
DATASET=ROOT/"reports"/"ml_v4_buy_selection_dataset_v4"
V3=ROOT/"reports"/"ml_v4_buy_selection_model_v3"
OUT=ROOT/"reports"/"ml_v4_buy_selection_model_v4"
GAP="adjusted_score_gap_to_top"
SEMANTIC=("Ability","PastPerformance","Distance","CourseShape","LapSuitability","RaceShape","PaceStyle","shadow_ai_rank","decision_score","final_score","adjusted_score","absolute_quality_pass","relative_advantage_pass","effective_reliability_pass","risk_guard_pass","consensus_positive_count","consensus_negative_count","risk_count","conflict_count","race_state")
GATES={"absolute_quality_pass","relative_advantage_pass","effective_reliability_pass","risk_guard_pass"}
BLOCKS=("April","May 2026 Independent OOS additive TRAIN reuse for V4 Model v3+","June","July H1","July H2","August Development","August Development (Prospective)")
MARCH="MARCH_2026_HISTORICAL_HOLDOUT_ADDITIVE_TRAIN_REUSE_V4"
EXPECTED_SHA="b02bb4b59b5f297e60964f96050890dbf32a7ac3b5a9ef93424b9d612e3ae80a"

class Stop(RuntimeError): pass
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n:str,x:object)->None:(OUT/n).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def git(*a:str)->str:return subprocess.run(["git",*a],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip()

def load_rows()->tuple[list[dict[str,str]],list[str]]:
    if sha(DATASET/"dataset.csv")!=EXPECTED_SHA: raise Stop("DATASET_V4_SHA_MISMATCH")
    manifest=json.loads((DATASET/"dataset_manifest.json").read_text(encoding="utf-8")); validation=json.loads((DATASET/"validation.json").read_text(encoding="utf-8"))
    if manifest.get("dataset_sha256")!=EXPECTED_SHA or validation.get("dataset_rows")!=4100 or validation.get("positive")!=1389 or validation.get("negative")!=2711: raise Stop("DATASET_V4_AUTHORITY_INVALID")
    with (DATASET/"dataset.csv").open(encoding="utf-8",newline="") as f:
        reader=csv.DictReader(f); rows=list(reader); fields=list(reader.fieldnames or [])
    if len(rows)!=4100 or GAP not in fields or any(x not in fields for x in SEMANTIC): raise Stop("DATASET_V4_SCHEMA_INVALID")
    return rows,fields

def transformed_columns()->list[str]:
    frozen=json.loads((V3/"feature_transform_schema.json").read_text(encoding="utf-8"))
    cols=frozen.get("transformed_model_input_columns")
    expected=[*SEMANTIC[:-1],"is_PLAY_UNCONVERGED_4PLUS","is_SKIP"]
    if cols!=expected or len(cols)!=21 or GAP in cols: raise Stop(f"V3_TRANSFORM_AUTHORITY_INVALID:{cols}")
    return cols

def matrix(rows:list[dict[str,str]], columns:list[str])->tuple[np.ndarray,np.ndarray]:
    values=[]; target=[]
    for r in rows:
        if r["valid_result"]!="True" or r["current_top5"]!="True":raise Stop(f"POPULATION_INVALID:{r['row_id']}")
        if GAP not in r or GAP in columns:raise Stop(f"RELATIVE_GAP_GUARD_FAILURE:{r['row_id']}")
        state=r["race_state"]
        if state not in {"PLAY_CONVERGED","PLAY_UNCONVERGED_4PLUS","SKIP"}:raise Stop(f"RACE_STATE_INVALID:{r['row_id']}")
        row=[]
        for name in SEMANTIC[:-1]:
            if name in GATES:
                if r[name] not in {"True","False"}:raise Stop(f"BOOLEAN_INVALID:{r['row_id']}:{name}")
                row.append(float(r[name]=="True"))
            else: row.append(float(r[name]))
        row += [float(state=="PLAY_UNCONVERGED_4PLUS"),float(state=="SKIP")]
        if r["actual_top3"] not in {"0","1"}:raise Stop(f"TARGET_INVALID:{r['row_id']}")
        values.append(row);target.append(int(r["actual_top3"]))
    x,y=np.asarray(values,float),np.asarray(target,int)
    if x.shape!=(len(rows),21) or int(y.sum())!=sum(int(r["actual_top3"]) for r in rows):raise Stop("MATRIX_INVALID")
    return x,y

def fit(train:list[dict[str,str]],columns:list[str])->tuple[StandardScaler,LogisticRegression,np.ndarray]:
    x,y=matrix(train,columns); scaler=StandardScaler()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always",ConvergenceWarning); warnings.filterwarnings("ignore",category=FutureWarning,module="sklearn\\.linear_model")
        z=scaler.fit_transform(x); model=LogisticRegression(penalty="l2",C=1.0,solver="lbfgs",class_weight=None).fit(z,y)
    if any(issubclass(w.category,ConvergenceWarning) for w in caught):raise Stop("SOLVER_NONCONVERGENCE")
    return scaler,model,model.predict_proba(z)[:,1]

def stat(v:list[float])->dict:
    import statistics
    return {"mean":statistics.mean(v),"median":statistics.median(v),"standard_deviation":statistics.stdev(v) if len(v)>1 else 0.0,"min":min(v),"max":max(v)}

def main()->Path:
    if OUT.exists():raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    frozen=[DATASET,V3,ROOT/"reports"/"v4_model_v3_formal_prospective",ROOT/"reports"/"shadow_cf_top3_rank_anchored_v1",ROOT/"reports"/"prospective_prediction_20260830_v1"]
    before={str(p.relative_to(ROOT)):sha(p/"artifact_hashes.json") if (p/"artifact_hashes.json").is_file() else "NO_INDEX" for p in frozen}
    head,status=git("rev-parse","HEAD"),git("status","--porcelain")
    rows,fields=load_rows();columns=transformed_columns(); x,y=matrix(rows,columns)
    if len(rows)!=4100 or int(y.sum())!=1389 or len(y)-int(y.sum())!=2711:raise Stop("TRAIN_POPULATION_COUNT_MISMATCH")
    if sum(r["source_block"]==MARCH for r in rows)!=860:raise Stop("MARCH_TRAIN_COUNT_MISMATCH")
    OUT.mkdir(parents=True)
    scaler,model,pred=fit(rows,columns)
    # Temporary second fit validates determinism; the first fit remains the formal artifact.
    scaler2,model2,pred2=fit(rows,columns)
    deterministic=bool(np.array_equal(scaler.mean_,scaler2.mean_) and np.array_equal(scaler.scale_,scaler2.scale_) and np.array_equal(model.coef_,model2.coef_) and np.array_equal(model.intercept_,model2.intercept_) and np.array_equal(pred,pred2))
    if not deterministic:raise Stop("DETERMINISM_FAILURE")
    joblib.dump(model,OUT/"model.joblib"); joblib.dump(scaler,OUT/"scaler.joblib")
    rm,rs=joblib.load(OUT/"model.joblib"),joblib.load(OUT/"scaler.joblib")
    if not np.array_equal(pred,rm.predict_proba(rs.transform(x))[:,1]):raise Stop("RELOAD_REPRODUCTION_FAILURE")
    cv=[]
    # One-time non-evidential 7-block development CV: March remains training-only.
    for block in BLOCKS:
        valid=[r for r in rows if r["source_block"]==block]; train=[r for r in rows if r["source_block"]!=block]
        sc,mo,_=fit(train,columns); xv,yv=matrix(valid,columns); pv=mo.predict_proba(sc.transform(xv))[:,1]
        cv.append({"validation_block":block,"validation_fold_size":len(valid),"train_rows":len(train),"positive_count":int(yv.sum()),"negative_count":int(len(yv)-yv.sum()),"auc":roc_auc_score(yv,pv),"log_loss":log_loss(yv,pv,labels=[0,1]),"brier":brier_score_loss(yv,pv),"march_in_validation":False,"label":"NON_EVIDENTIAL_DEVELOPMENT_DIAGNOSTIC_ONLY","warning":"SMALLER_VALIDATION_FOLD_INTERPRET_WITH_CAUTION" if block=="August Development (Prospective)" else None})
    if len(cv)!=7:raise Stop("DEVELOPMENT_CV_FOLD_COUNT_INVALID")
    source_index={name:fields.index(name) for name in [*SEMANTIC,GAP]}
    selected=[]
    for index,name in enumerate(SEMANTIC):
        if name=="race_state":selected.append({"semantic_source_column":name,"source_index":source_index[name],"transformed_columns":[{"name":"is_PLAY_UNCONVERGED_4PLUS","transformed_index":columns.index("is_PLAY_UNCONVERGED_4PLUS")},{"name":"is_SKIP","transformed_index":columns.index("is_SKIP")}],"selected":True})
        else:selected.append({"semantic_source_column":name,"source_index":source_index[name],"transformed_columns":[{"name":name,"transformed_index":columns.index(name)}],"selected":True})
    selected.append({"semantic_source_column":GAP,"source_index":source_index[GAP],"transformed_columns":[],"selected":False,"status":"AVAILABLE_BUT_NOT_SELECTED_FOR_MODEL_V4","EXCLUDED_FROM_MODEL_INPUT":True})
    runtime={"python_executable":sys.executable,"python_version":sys.version,"implementation":platform.python_implementation(),"numpy":np.__version__,"scipy":scipy.__version__,"scikit_learn":sklearn.__version__,"joblib":joblib.__version__}
    write("feature_schema.json",{"semantic_feature_order":list(SEMANTIC),"semantic_feature_count":20,"relative_gap_status":"AVAILABLE_BUT_NOT_SELECTED_FOR_MODEL_V4","dataset_v4_feature_schema_sha256":sha(DATASET/"feature_schema.json")})
    write("feature_transform_schema.json",{"authority":"V4 Model v3 frozen feature_transform_schema.json","authority_sha256":sha(V3/"feature_transform_schema.json"),"transformed_model_input_columns":columns,"transformed_input_count":21,"name_order_transform_semantics_match_model_v3":True,"relative_gap_present":False})
    write("selected_feature_columns.json",{"dataset_source_columns":selected,"semantic_selected_columns":list(SEMANTIC),"semantic_excluded_columns":[GAP],"transformed_selected_columns":columns,"relative_gap_status":"AVAILABLE_BUT_NOT_SELECTED_FOR_MODEL_V4"})
    write("training_population.json",{"rows":4100,"positive":1389,"negative":2711,"march_additive_rows":860,"march_role":"ADDITIVE_TRAIN_REUSE_FOR_V4_MODEL_V4","weighting":"NONE","resampling":"NONE","filtering":"NONE","target":"actual_top3"})
    write("training_recipe.json",{"pipeline":["StandardScaler","LogisticRegression"],"penalty":"l2","C":1.0,"solver":"lbfgs","class_weight":None,"tuning":False,"threshold_search":False,"feature_selection_search":False,"formal_fit_count":1,"temporary_deterministic_refit_count":1,"development_cv_fit_count":7})
    write("runtime_environment.json",runtime)
    write("determinism_validation.json",{"status":"PASS","scaler_mean_exact":True,"scaler_scale_exact":True,"coef_exact":True,"intercept_exact":True,"predict_proba_exact":True,"formal_fit_preserved":True})
    write("reload_validation.json",{"status":"PASS","model_sha256":sha(OUT/"model.joblib"),"scaler_sha256":sha(OUT/"scaler.joblib"),"training_matrix_prediction_exact":True})
    write("development_cv.json",{"label":"NON_EVIDENTIAL_DEVELOPMENT_DIAGNOSTIC_ONLY","definition":"One-time 7-block CV; March stays TRAIN-only in all primary folds.","folds":cv,"summary":{k:stat([r[k] for r in cv]) for k in ("auc","log_loss","brier")},"model_v3_comparison":"DEVELOPMENT_CONTEXT_ONLY","march_signal":"POSITIVE_DEVELOPMENT_SIGNAL_WITH_FOLD_SIZE_SENSITIVITY"})
    write("lineage.json",{"model":"V4 Model v4","dataset_v4_sha256":EXPECTED_SHA,"parent_dataset_v3_sha256":"e30ac0412e62e502d3671f1222306cc8fc79853125a86cd0fd996fefa64187bc","march_model_v3_role":"CONSUMED_TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V3","march_model_v4_role":"ADDITIVE_TRAIN_REUSE_FOR_V4_MODEL_V4","historical_gate":"PASS_UNCHANGED","independent_march_evaluation_for_v4":"PROHIBITED","relative_gap":"AVAILABLE_BUT_NOT_SELECTED_FOR_MODEL_V4","interaction":"NO_CLEAR_RELATIVE_GAP_X_MARCH_SYNERGY_DETECTED"})
    write("evidence_boundary.json",{"not_accessed":["2026-08-30 Result","Formal Prospective Result","February","new Historical Result","unused holdout","CF POST Result"],"not_authorized":["Historical evaluation","Prospective model substitution","Production activation"],"development_cv":"NON_EVIDENTIAL_DEVELOPMENT_DIAGNOSTIC_ONLY"})
    write("training_manifest.json",{"model":"V4 Model v4","status":"FROZEN_CANDIDATE_PENDING_INDEPENDENT_REPRODUCTION_REVIEW","dataset_sha256":EXPECTED_SHA,"rows":4100,"positive":1389,"negative":2711,"march_additive":860,"semantic_selected":20,"transformed_inputs":21,"relative_gap_selected":False,"recipe_sha256":sha(OUT/"training_recipe.json"),"feature_schema_sha256":sha(OUT/"feature_schema.json"),"feature_transform_schema_sha256":sha(OUT/"feature_transform_schema.json"),"selected_feature_columns_sha256":sha(OUT/"selected_feature_columns.json"),"runtime":runtime,"training_timestamp":datetime.now(timezone.utc).isoformat(),"git_head":head,"model_sha256":sha(OUT/"model.joblib"),"scaler_sha256":sha(OUT/"scaler.joblib")})
    after={str(p.relative_to(ROOT)):sha(p/"artifact_hashes.json") if (p/"artifact_hashes.json").is_file() else "NO_INDEX" for p in frozen}
    if before!=after or git("rev-parse","HEAD")!=head:raise Stop("FROZEN_AUTHORITY_MUTATION")
    write("safety.json",{"status":"PASS","frozen_authority_before":before,"frozen_authority_after":after,"production_change":0,"current_ai_change":0,"model_v3_change":0,"cf_change":0,"formal_prospective_change":0,"august_30_result_access":0,"february_access":0,"git_head_before":head,"git_head_after":git("rev-parse","HEAD"),"git_status_before":status,"git_status_after":git("status","--porcelain")})
    (OUT/"report.md").write_text("# V4 Model v4 Formal Training\n\nDataset v4全4,100行を用い、Relative Gapを除外したModel v3同等の21 transformed inputsで一回だけ正式fitしました。Historical/Prospective Resultへのアクセス、Production接続、Model v3置換は行っていません。\n",encoding="utf-8")
    write("artifact_hashes.json",{"indexed_artifacts":{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!="artifact_hashes.json"},"self_hash_excluded":True})
    return OUT
if __name__=="__main__":print(main())
