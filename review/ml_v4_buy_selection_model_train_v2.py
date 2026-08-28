"""Corrective one-fit V4 Model v2 training under Protocol v2 only."""
from __future__ import annotations

import csv, hashlib, json, math, platform, sys, warnings
from datetime import datetime, timezone
from pathlib import Path
import joblib, numpy as np, scipy, sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "ml_v4_buy_selection_model_v2"
DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v1"
PROTOCOL = ROOT / "reports" / "ml_v4_buy_selection_training_protocol_v2"
RUNTIME = ROOT / "reports" / "ml_v4_training_runtime_v1"
EXPECTED = {"dataset":"02d2471f11c1069ebb264946eacdc55fe3ea673c8812b6d17c8fd973af538b53","feature_schema":"10f576bb55a23225c84634a5c79e21fa7f54ee239977d0faf8743042eb31aaa0","protocol":"be8764d425650a067e4ddaca96f2cc52b9dff371c336676e51d52e3eaf502100","protocol_manifest":"8ebaf317c3d0c916d30ee023f48ff52750d2aeb5dd0ca0ac9e1f8e06f0fac696","runtime_requirements":"30a9ca043286755020691f7040ff0946c1427aa6fedae9daa04d0239e1998dff","runtime_manifest":"efd36424206dfd54c16b0517d9832338bbb61f286a1725c2ddde6c69058182a5"}
SEMANTIC=["Ability","PastPerformance","Distance","CourseShape","LapSuitability","RaceShape","PaceStyle","shadow_ai_rank","decision_score","final_score","adjusted_score","absolute_quality_pass","relative_advantage_pass","effective_reliability_pass","risk_guard_pass","consensus_positive_count","consensus_negative_count","risk_count","conflict_count","race_state"]
TRANSFORMED=[*SEMANTIC[:-1],"is_PLAY_UNCONVERGED_4PLUS","is_SKIP"]
GATES={"absolute_quality_pass","relative_advantage_pass","effective_reliability_pass","risk_guard_pass"}

class Stop(RuntimeError): pass
def sha(p:Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n:str,v:object)->None: (OUT/n).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def number(x:str,c:str)->float:
    try: v=float(x)
    except Exception as e: raise Stop(f"NUMERIC_INVALID:{c}") from e
    if not math.isfinite(v): raise Stop(f"NUMERIC_NONFINITE:{c}")
    return v
def boolean(x:str,c:str)->int:
    if x=="True": return 1
    if x=="False": return 0
    raise Stop(f"BOOLEAN_INVALID:{c}:{x!r}")
def fit(x,y):
    s=StandardScaler(); m=LogisticRegression(penalty="l2",C=1.0,solver="lbfgs",class_weight=None)
    with warnings.catch_warnings(record=True) as got:
        warnings.simplefilter("always",ConvergenceWarning); z=s.fit_transform(x); m.fit(z,y)
    warns=[str(w.message) for w in got if issubclass(w.category,ConvergenceWarning)]
    return s,m,m.predict_proba(z)[:,1],warns

def run()->Path:
    if OUT.exists(): raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        actual={"dataset":sha(DATASET/"dataset.csv"),"feature_schema":sha(DATASET/"feature_schema.json"),"protocol":sha(PROTOCOL/"training_protocol.md"),"protocol_manifest":sha(PROTOCOL/"protocol_manifest.json"),"runtime_requirements":sha(RUNTIME/"requirements_frozen.txt"),"runtime_manifest":sha(RUNTIME/"runtime_manifest.json")}
        if actual!=EXPECTED: raise Stop(f"AUTHORITY_SHA_MISMATCH:{actual}")
        t=json.loads((PROTOCOL/"feature_transform_schema.json").read_text(encoding="utf-8")); cols=t.get("transformed_model_input_columns",[])
        expected_set=(set(SEMANTIC)-{"race_state"})|{"is_PLAY_UNCONVERGED_4PLUS","is_SKIP"}
        structural={"pace_style_transformed_present":"PaceStyle" in cols,"raw_race_state_transformed_absent":"race_state" not in cols,"race_state_dummy_columns_present":all(x in cols for x in ("is_PLAY_UNCONVERGED_4PLUS","is_SKIP")),"transformed_set_equality":set(cols)==expected_set,"transformed_order_equality":cols==TRANSFORMED,"unexpected_column_count":len(set(cols)-expected_set),"missing_expected_column_count":len(expected_set-set(cols)),"duplicate_column_count":len(cols)-len(set(cols))}
        if not all(v is True for v in structural.values() if isinstance(v,bool)) or any(structural[x]!=0 for x in ("unexpected_column_count","missing_expected_column_count","duplicate_column_count")): raise Stop(f"CORRECTED_TRANSFORM_INVALID:{structural}")
        rv=json.loads((RUNTIME/"runtime_validation.json").read_text(encoding="utf-8"))
        if rv.get("status")!="PASS" or not all(rv.get("package_versions_match",{}).values()): raise Stop("RUNTIME_INVALID")
        rows=list(csv.DictReader((DATASET/"dataset.csv").open(encoding="utf-8",newline="")))
        xrows=[]; ys=[]; ids=[]
        for r in rows:
            rid=r.get("row_id","")
            if r.get("current_top5")!="True" or r.get("valid_result")!="True": raise Stop(f"POPULATION_INVALID:{rid}")
            st=r.get("race_state")
            if st not in {"PLAY_CONVERGED","PLAY_UNCONVERGED_4PLUS","SKIP"}: raise Stop(f"UNKNOWN_RACE_STATE:{rid}:{st}")
            vals=[boolean(r[f],f"{rid}:{f}") if f in GATES else number(r[f],f"{rid}:{f}") for f in SEMANTIC[:-1]]+[int(st=="PLAY_UNCONVERGED_4PLUS"),int(st=="SKIP")]
            if len(vals)!=21: raise Stop(f"INPUT_COUNT_INVALID:{rid}")
            if r.get("actual_top3") not in {"0","1"}: raise Stop(f"TARGET_INVALID:{rid}")
            xrows.append(vals);ys.append(int(r["actual_top3"]));ids.append(rid)
        x=np.asarray(xrows,dtype=float); y=np.asarray(ys,dtype=int)
        if x.shape!=(2283,21) or y.shape!=(2283,) or int(y.sum())!=783 or len(set(ids))!=2283: raise Stop(f"DATASET_SHAPE_INVALID:{x.shape}:{int(y.sum())}:{len(set(ids))}")
        scaler,model,p,warns=fit(x,y)
        if warns: raise Stop(f"SOLVER_NON_CONVERGENCE:{warns}")
        sanity={"finite_coefficient_check":bool(np.isfinite(model.coef_).all()),"finite_intercept_check":bool(np.isfinite(model.intercept_).all()),"probability_sanity_check":bool(np.isfinite(p).all() and np.all((p>=0)&(p<=1))),"row_alignment_check":len(p)==2283,"degenerate_output_check":bool(np.ptp(p)>0)}
        if not all(sanity.values()): raise Stop(f"SANITY_FAILED:{sanity}")
        s2,m2,p2,w2=fit(x,y); deterministic=bool(not w2 and np.array_equal(scaler.mean_,s2.mean_) and np.array_equal(scaler.scale_,s2.scale_) and np.array_equal(model.coef_,m2.coef_) and np.array_equal(model.intercept_,m2.intercept_) and np.array_equal(p,p2))
        if not deterministic: raise Stop("DETERMINISTIC_REPRODUCTION_FAILED")
        joblib.dump(model,OUT/"model.joblib");joblib.dump(scaler,OUT/"scaler.joblib")
        write("feature_transform_schema.json",{"source_protocol_v2_sha256":actual["protocol"],"semantic_feature_order":SEMANTIC,"semantic_feature_count":20,"transformed_model_input_columns":TRANSFORMED,"transformed_model_input_column_count":21,"structural_validators":structural,"race_state":{"reference":"PLAY_CONVERGED","raw_model_input":"DROP","dummies":["is_PLAY_UNCONVERGED_4PLUS","is_SKIP"],"unknown":"FAIL_CLOSED"},"gates":{"false":0,"true":1,"other":"FAIL_CLOSED"}})
        write("coefficient_table.json",{"intercept":float(model.intercept_[0]),"coefficients":[{"feature_name":n,"coefficient":float(c)} for n,c in zip(TRANSFORMED,model.coef_[0],strict=True)],"inspection_only":True})
        write("model_output_schema.json",{"output":"RAW_MODEL_PROBABILITY","semantic":"P(actual_top3)","calibration":"NONE","performance_evaluation":"NOT_EXECUTED"})
        write("governance_boundary.json",{"model_v2_status":"TRAINED_CANDIDATE","may":"UNTOUCHED_INDEPENDENT_OOS","not_authorized":["Production","BUY rule","SKIP override","UNCONVERGED override","CF change","May OOS before Claude independent review"],"production_change":0,"cf_change":0})
        write("model_correction_lineage.json",{"model_v1_status":"FREEZE_REJECT_DUE_TO_SUPERSEDED_PROTOCOL","model_v2_status":"TRAINED_FROM_CORRECTED_PROTOCOL_V2","supersedes_model_v1_for_oos":True,"reason":"PROTOCOL_V1_FEATURE_TRANSFORM_SPEC_ERROR","retrain_reason":"CORRECTIVE_RETRAIN_FROM_APPROVED_PROTOCOL_V2","defect":{"pace_style":"omitted","raw_race_state":"retained"},"v2":{"pace_style":"retained","raw_race_state":"replaced_by_dummies"},"discovery":"POST_TRAIN_PRE_OOS","train_performance_disclosed":0,"may_access":0,"oos_contamination":"NO"})
        meta={"model":"KeibaAI_V4_BUY_Selection_Model_V2","algorithm":"LogisticRegression","penalty":"l2","C":1.0,"solver":"lbfgs","class_weight":None,"runtime":{"python":sys.version,"implementation":platform.python_implementation(),"numpy":np.__version__,"scikit_learn":sklearn.__version__,"scipy":scipy.__version__,"joblib":joblib.__version__},"authority_sha256":actual,"train_rows":2283,"target":{"actual_top3_positive":783,"negative":1500},"semantic_features":20,"model_input_columns":21,"output":"RAW_MODEL_PROBABILITY=P(actual_top3)","timestamp":datetime.now(timezone.utc).isoformat(),"formal_scaler_fit_count":1,"formal_model_fit_count":1,"deterministic_reproduction_refit_count":1}
        write("model_metadata.json",meta)
        validation={"model_v1_status":"FREEZE_REJECT_DUE_TO_SUPERSEDED_PROTOCOL","model_v2_training_status":"PASS","dataset_sha_validation":"PASS","protocol_v2_sha_validation":"PASS","runtime_validation":"PASS","train_row_count":2283,"semantic_feature_count":20,"model_input_column_count":21,**{k:("PASS" if v is True else v) for k,v in structural.items()},"scaler_fit_count":1,"model_fit_count":1,"solver_convergence":"PASS",**{k:("PASS" if v else "FAIL") for k,v in sanity.items()},"deterministic_reproduction":"PASS","deterministic_reproduction_refit_count":1,"train_performance_calculation_count":0,"may_access_count":0,"march_or_earlier_access_count":0,"oos_evaluation":0,"feature_selection":0,"hyperparameter_tuning":0,"class_weighting":0,"resampling":0,"calibration":0,"threshold_tuning":0}
        write("training_validation.json",validation)
        write("training_manifest.json",{"status":"MODEL_V2_FIT_COMPLETE_FREEZE_READY","model_v2_sha256":sha(OUT/"model.joblib"),"scaler_v2_sha256":sha(OUT/"scaler.joblib"),"model_metadata_v2_sha256":sha(OUT/"model_metadata.json"),"dataset_sha256":actual["dataset"],"protocol_v2_sha256":actual["protocol"],"runtime_manifest_sha256":actual["runtime_manifest"],"feature_transform_schema_sha256":sha(OUT/"feature_transform_schema.json"),"model_status":"TRAINED_CANDIDATE","may_access_count":0,"formal_model_fit_count":1,"formal_scaler_fit_count":1})
        write("artifact_hashes.json",{"indexed_artifacts":{p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"},"self_hash_excluded":True})
        return OUT
    except Stop as e:
        write("training_validation.json",{"model_v2_training_status":"FAIL","final_status":"V4_MODEL_V2_TRAINING_FAILED","reason":str(e),"model_fit_count":0,"scaler_fit_count":0,"may_access_count":0,"march_or_earlier_access_count":0}); return OUT
if __name__=="__main__": print(run())
