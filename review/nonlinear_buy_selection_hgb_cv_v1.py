"""Frozen Logistic vs HistGradientBoosting 7-fold BUY-selection CV experiment."""
from __future__ import annotations

import csv, hashlib, json, math, os, platform, subprocess, sys
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from review.february_additive_training_cv_v1 import (FOLDS, MARCH, feature_vector, full_validation_candidates, metric, rate_pp, sha, tree_hash, git)
from review.ml_v4_buy_selection_model_train_v4 import SEMANTIC
from review.ml_v4_buy_selection_dataset_inventory_v2 import Stop

OUT = ROOT / "reports" / "nonlinear_buy_selection_hgb_cv_v1"
DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v4" / "dataset.csv"
LABEL = "CV_EXPERIMENT_ONLY"
HGB_KW = dict(loss="log_loss", learning_rate=0.1, max_iter=100, max_leaf_nodes=31, max_depth=None, min_samples_leaf=30, l2_regularization=1.0, early_stopping=False, random_state=42)

def rows(path: Path):
    with path.open(encoding="utf-8", newline="") as f: return list(csv.DictReader(f))
def write(name, value): (OUT / name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def identity_sha(items):
    return hashlib.sha256("\n".join(sorted(f"{r['race_id']}:{r['horse_number']}" for r in items)).encode()).hexdigest()
def auc(y,p): return roc_auc_score(y,p)
def secondary(y,p): return {"row_count":len(y),"roc_auc":auc(y,p),"brier_score":brier_score_loss(y,p),"logloss":log_loss(y,p,labels=[0,1])}
def distribution(p):
    a=np.asarray(p,dtype=float); q=np.quantile(a,[.01,.05,.5,.95,.99])
    return {"min":float(a.min()),"p01":float(q[0]),"p05":float(q[1]),"median":float(q[2]),"p95":float(q[3]),"p99":float(q[4]),"max":float(a.max()),"fraction_lt_0_01":float(np.mean(a<.01)),"fraction_gt_0_99":float(np.mean(a>.99))}
def select(candidates, prob, k): return sorted(candidates,key=lambda r:(-prob[r["row_id"]],float(r["shadow_ai_rank"]),int(r["horse_number"])))[:k]

def fit_logistic(train, valid):
    x=np.asarray([feature_vector(r) for r in train],float); y=np.asarray([int(r["actual_top3"]) for r in train])
    s=StandardScaler(); xs=s.fit_transform(x)
    m=LogisticRegression(penalty="l2",C=1.0,solver="lbfgs",class_weight=None,max_iter=1000).fit(xs,y)
    return m,s,m.predict_proba(s.transform(np.asarray([feature_vector(r) for r in valid],float)))[:,1],m.predict_proba(xs)[:,1]
def fit_hgb(train, valid):
    x=np.asarray([feature_vector(r) for r in train],float); y=np.asarray([int(r["actual_top3"]) for r in train])
    m=HistGradientBoostingClassifier(**HGB_KW)
    required=HGB_KW
    if any(m.get_params()[k] != v for k,v in required.items()): raise Stop("HGB_EFFECTIVE_PARAMS_MISMATCH")
    m.fit(x,y)
    return m,m.predict_proba(np.asarray([feature_vector(r) for r in valid],float))[:,1],m.predict_proba(x)[:,1]

def main():
    if OUT.exists(): raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    protected=[ROOT/"reports"/"ml_v4_buy_selection_dataset_v4",ROOT/"reports"/"ml_v4_buy_selection_model_v4",ROOT/"reports"/"ml_v4_buy_selection_model_v3",ROOT/"reports"/"v4_model_v3_formal_prospective",ROOT/"reports"/"shadow_cf_top3_rank_anchored_v1"]
    before={str(p.relative_to(ROOT)):tree_hash(p) for p in protected}; head_before,status_before=git("rev-parse","HEAD"),git("status","--porcelain")
    data=rows(DATASET); by=Counter(r["source_block"] for r in data)
    if len(data)!=4100 or sum(by[f] for f in FOLDS)!=3240 or by[MARCH]!=860: raise Stop("DATASET_V4_FROZEN_POPULATION_MISMATCH")
    if any("FEBRUARY" in r["source_block"] for r in data): raise Stop("FEBRUARY_INPUT_PRESENT")
    for r in data: feature_vector(r)
    feature_names=[*SEMANTIC[:-1],"is_PLAY_UNCONVERGED_4PLUS","is_SKIP"]
    fsha=hashlib.sha256(json.dumps(feature_names,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    control_probe=LogisticRegression(penalty="l2",C=1.0,solver="lbfgs",class_weight=None,max_iter=1000)
    treatment_probe=HistGradientBoostingClassifier(**HGB_KW)
    if any(treatment_probe.get_params()[k]!=v for k,v in HGB_KW.items()): raise Stop("HGB_PREFIT_ASSERT_FAILED")
    OUT.mkdir(parents=True); (OUT/"cv_experiment_only_models").mkdir()
    # These artifacts are written before the first model fit.
    write("authority.json",{"status":"HUMAN_APPROVED","design":"FROZEN_READY_FOR_EXECUTION","question":"Does nonlinear estimator capacity improve same-volume BUY_TOP3_RATE using exactly Model v4 information?","february_use":"NOT_USED"})
    write("prior_nonlinearity_context.json",{"path":"reports/v4_selection_feature_headroom_diagnostic_v1/nonlinearity_triage.json","role":"NON_EVIDENTIAL_DEVELOPMENT_TRIAGE_ONLY","rerun":False,"reinterpretation":False})
    write("design_freeze.json",{"folds":list(FOLDS),"dataset_rows":4100,"validation_rows":3240,"march_train_only":860,"february_rows_used":0,"forbidden":["feature change","gap feature","tuning","calibration","resampling","class weighting","final candidate","production change"]})
    write("environment_freeze.json",{"python_executable":sys.executable,"python_version":sys.version,"python_implementation":platform.python_implementation(),"platform":platform.platform(),"sklearn_version":sklearn.__version__,"numpy_version":np.__version__,"omp_num_threads":os.environ.get("OMP_NUM_THREADS"),"runtime_note":"OMP_NUM_THREADS=1 is an execution-environment setting only; estimator get_params() remains frozen."})
    write("feature_order.json",{"semantic_feature_count":20,"transformed_feature_count":21,"ordered_features":feature_names,"feature_order_sha256":fsha,"dataset_sha256":sha(DATASET)})
    write("fold_inventory.json",{"source_block_counts":dict(by),"fold_count":7,"validation_capable_rows":3240,"march_train_only_rows":860,"february_rows":0})
    control_params=control_probe.get_params(); treatment_params=treatment_probe.get_params()
    write("control_recipe.json",{"preprocessing":"fold-local StandardScaler fit on train only","estimator":"LogisticRegression","params":control_params})
    write("treatment_recipe.json",{"preprocessing":"NONE","estimator":"HistGradientBoostingClassifier","params":treatment_params,"calibration":"NONE","class_weight":"NONE","resampling":"NONE"})
    write("effective_estimator_params.json",{"control":control_params,"treatment":treatment_params,"pre_fit_assertion":"PASS"})
    candidates,reconstruction=full_validation_candidates(data)
    training_hashes={}; validation_hashes={}; leakage=[]; folds={}; preds=[]; rd=[]; models=[]; scalers=[]; probdist={"pooled":{"logistic":[],"hgb":[]},"folds":{}}
    for fold in FOLDS:
        valid=[r for r in data if r["source_block"]==fold]; train=[r for r in data if r["source_block"]!=fold]
        vi,ti={r["row_id"] for r in valid},{r["row_id"] for r in train}
        if vi & ti or any(r["source_block"]==MARCH for r in valid) or any("FEBRUARY" in r["source_block"] for r in train): raise Stop(f"LEAKAGE_FAILURE:{fold}")
        train_race_horse={(r["race_id"],r["horse_number"]) for r in train}; valid_race_horse={(r["race_id"],r["horse_number"]) for r in valid}
        if train_race_horse & valid_race_horse: raise Stop(f"RACE_HORSE_LEAKAGE:{fold}")
        training_hashes[fold]={"identity_sha256":identity_sha(train),"row_count":len(train)}; validation_hashes[fold]={"identity_sha256":identity_sha(valid),"row_count":len(valid)}
        leakage.append({"fold":fold,"status":"PASS","validation_absent_from_train":True,"same_train_identities_control_treatment":True,"same_validation_identities_control_treatment":True,"march_train_only_rows":860,"february_rows":0,"race_horse_overlap":0,"scaler_train_only":True,"hgb_train_only":True,"validation_labels_in_parameters":False,"hyperparameter_tuning":False,"early_stopping_internal_split":False})
        lm,ls,lp,ltrain=fit_logistic(train,valid); hm,hp,htrain=fit_hgb(train,valid)
        safe=fold.replace(" ","_").replace("(","").replace(")","")
        lmp=OUT/"cv_experiment_only_models"/f"logistic_{safe}.joblib"; lsp=OUT/"cv_experiment_only_models"/f"logistic_{safe}_scaler.joblib"; hmp=OUT/"cv_experiment_only_models"/f"hgb_{safe}.joblib"
        joblib.dump(lm,lmp); joblib.dump(ls,lsp); joblib.dump(hm,hmp)
        models += [{"fold":fold,"arm":"LOGISTIC_CONTROL","path":str(lmp.relative_to(ROOT)),"sha256":sha(lmp),"status":LABEL},{"fold":fold,"arm":"HGB_TREATMENT","path":str(hmp.relative_to(ROOT)),"sha256":sha(hmp),"status":LABEL}]
        scalers += [{"fold":fold,"arm":"LOGISTIC_CONTROL","path":str(lsp.relative_to(ROOT)),"sha256":sha(lsp),"status":LABEL}]
        cands=[x for group in candidates.values() for x in group if x["source_block"]==fold]
        lall=lm.predict_proba(ls.transform(np.asarray([feature_vector(r) for r in cands],float)))[:,1]; hall=hm.predict_proba(np.asarray([feature_vector(r) for r in cands],float))[:,1]
        lmap={r["row_id"]:float(p) for r,p in zip(cands,lall)}; hmap={r["row_id"]:float(p) for r,p in zip(cands,hall)}
        for r,p,q in zip(valid,lp,hp): preds.append({"fold":fold,"row_id":r["row_id"],"race_id":r["race_id"],"horse_number":r["horse_number"],"shadow_ai_rank":r["shadow_ai_rank"],"current_buy":r["current_buy"],"race_state":r["race_state"],"actual_top3":int(r["actual_top3"]),"logistic_probability":float(p),"hgb_probability":float(q)})
        eligible=[]; selected_l=[]; selected_h=[]
        for rid,group in candidates.items():
            if group[0]["source_block"]!=fold: continue
            buys=[x for x in group if x["current_buy"]]
            if group[0]["race_state"]=="PLAY_CONVERGED" and buys:
                eligible.append(rid); k=len(buys); selected_l+=select(group,lmap,k); selected_h+=select(group,hmap,k)
        ml,mh=metric(selected_l),metric(selected_h); raw=mh["top3_hits"]-ml["top3_hits"]; lift=mh["buy_top3_rate"]-ml["buy_top3_rate"]
        for rid in eligible:
            a=metric([x for x in selected_l if x["race_id"]==rid])["top3_hits"]; b=metric([x for x in selected_h if x["race_id"]==rid])["top3_hits"]; rd.append({"fold":fold,"race_id":rid,"current_buy_count":len([x for x in selected_l if x["race_id"]==rid]),"logistic_top3_hits":a,"hgb_top3_hits":b,"race_hit_delta":b-a})
        y=[int(r["actual_top3"]) for r in valid]
        folds[fold]={"eligible_races":len(eligible),"logistic":ml,"hgb":mh,"raw_hit_difference":raw,"buy_top3_rate_lift":lift,"direction":"POSITIVE" if raw>0 else "NEGATIVE" if raw<0 else "NEUTRAL","secondary":{"logistic":secondary(y,lp),"hgb":secondary(y,hp)},"train_validation_auc":{"logistic":{"train_auc":auc([int(r["actual_top3"]) for r in train],ltrain),"validation_auc":auc(y,lp)},"hgb":{"train_auc":auc([int(r["actual_top3"]) for r in train],htrain),"validation_auc":auc(y,hp)}}}
        for arm in ("logistic","hgb"): folds[fold]["train_validation_auc"][arm]["gap"]=folds[fold]["train_validation_auc"][arm]["train_auc"]-folds[fold]["train_validation_auc"][arm]["validation_auc"]
        probdist["pooled"]["logistic"]+=list(lp); probdist["pooled"]["hgb"]+=list(hp); probdist["folds"][fold]={"logistic":distribution(lp),"hgb":distribution(hp)}
    def pool(names):
        rec=[folds[x] for x in names]
        def arm(n):
            x={k:sum(r[n][k] for r in rec) for k in ("nominal_selected_count","invalid_selected_count","valid_selected_count","top3_hits")}; x["buy_top3_rate"]=x["top3_hits"]/x["valid_selected_count"]; return x
        l,h=arm("logistic"),arm("hgb"); return {"logistic":l,"hgb":h,"raw_hit_difference":h["top3_hits"]-l["top3_hits"],"buy_top3_rate_lift":h["buy_top3_rate"]-l["buy_top3_rate"]}
    pooled=pool(list(FOLDS)); direction=Counter(r["direction"] for r in folds.values()); deltas=Counter(r["race_hit_delta"] for r in rd)
    lofo=[]
    for excluded in FOLDS:
        x=pool([f for f in FOLDS if f!=excluded]); lofo.append({"excluded_fold":excluded,**x,"raw_gate":x["raw_hit_difference"]>=0,"rate_gate":x["buy_top3_rate_lift"]>=0})
    y=[x["actual_top3"] for x in preds]; sec={"authority":"SECONDARY_ONLY_CANNOT_OVERRIDE_PRIMARY_BUY_GATE","pooled":{"logistic":secondary(y,[x["logistic_probability"] for x in preds]),"hgb":secondary(y,[x["hgb_probability"] for x in preds])},"folds":{f:folds[f]["secondary"] for f in FOLDS}}
    gates={"pooled_raw_hit_diff_gt_zero":pooled["raw_hit_difference"]>0,"pooled_rate_lift_gt_zero":pooled["buy_top3_rate_lift"]>0,"positive_folds_gt_negative":direction["POSITIVE"]>direction["NEGATIVE"],"all_lofo_raw_nonnegative":all(x["raw_gate"] for x in lofo),"all_lofo_rate_nonnegative":all(x["rate_gate"] for x in lofo)}
    verdict="NOT_SUPPORTED" if not gates["pooled_raw_hit_diff_gt_zero"] or not gates["pooled_rate_lift_gt_zero"] else "SUPPORTED_FOR_NEXT_STAGE" if all(gates.values()) else "INCONCLUSIVE"
    pooled.update({"eligible_races":len(rd),"hgb_superior_races":sum(x["race_hit_delta"]>0 for x in rd),"equal_races":sum(x["race_hit_delta"]==0 for x in rd),"logistic_superior_races":sum(x["race_hit_delta"]<0 for x in rd),"full_race_hit_delta_distribution":dict(sorted(deltas.items()))})
    write("training_identity_hashes.json",training_hashes); write("validation_identity_hashes.json",validation_hashes); write("leakage_checks.json",{"status":"PASS","checks":leakage}); write("model_artifact_hashes.json",{"status":LABEL,"models":models}); write("scaler_artifact_hashes.json",{"status":LABEL,"scalers":scalers,"treatment_scaler_count":0})
    with (OUT/"validation_predictions.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(preds[0]));w.writeheader();w.writerows(preds)
    write("buy_evaluation_eligibility.json",{"status":"PASS","rule":"PLAY_CONVERGED AND Current BUY >= 1","candidate_universe":"FROZEN_CURRENT_TOP5","reconstruction":reconstruction,"eligible_races_by_fold":{f:folds[f]["eligible_races"] for f in FOLDS},"invalid_semantics":"not replaced; excluded from denominator"})
    write("fold_buy_metrics.json",folds);write("pooled_buy_metrics.json",pooled)
    with (OUT/"race_level_delta.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rd[0]));w.writeheader();w.writerows(rd)
    write("race_delta_summary.json",{"eligible_races":len(rd),"hgb_superior_races":pooled["hgb_superior_races"],"equal_races":pooled["equal_races"],"logistic_superior_races":pooled["logistic_superior_races"],"distribution":dict(sorted(deltas.items())),"net_hit_difference":pooled["raw_hit_difference"]})
    write("fold_direction_summary.json",{"positive_folds":direction["POSITIVE"],"neutral_folds":direction["NEUTRAL"],"negative_folds":direction["NEGATIVE"],"by_fold":{f:folds[f]["direction"] for f in FOLDS}});write("lofo_robustness.json",{"trials":lofo,"all_raw_nonnegative":gates["all_lofo_raw_nonnegative"],"all_rate_nonnegative":gates["all_lofo_rate_nonnegative"]});write("secondary_metrics.json",sec);write("train_validation_auc_gap.json",{f:folds[f]["train_validation_auc"] for f in FOLDS});write("probability_distribution.json",{"pooled":{"logistic":distribution(probdist["pooled"]["logistic"]),"hgb":distribution(probdist["pooled"]["hgb"])},"folds":probdist["folds"]})
    write("promotion_gate.json",{"frozen_gates":gates,"verdict":verdict});write("interpretation_boundary.json",{"allowed_if_supported":"existing Model v4 information with preregistered nonlinear estimator improved same-volume BUY selection relative to fold-retrained LogisticRegression","prohibited":["feature importance","SHAP","interaction inference","production readiness","February addition","automatic candidate build"],"FEATURE_IMPORTANCE_ANALYSIS":"NOT_IN_SCOPE","SHAP":"NOT_IN_SCOPE"});write("formal_track_preservation.json",{"V4_MODEL_V4_FORMAL_PROSPECTIVE_STATUS":"READY_FOR_FIRST_FORMAL_PRE","V4_MODEL_V3_FORMAL_PROSPECTIVE_SHADOW":"CONTINUE","CF_EVIDENCE_TRACK":"SEPARATE_AND_CONTINUING","FEBRUARY_ADDITIVE_TRAINING":"INCONCLUSIVE"})
    after={str(p.relative_to(ROOT)):tree_hash(p) for p in protected};head_after,status_after=git("rev-parse","HEAD"),git("status","--porcelain")
    if before!=after or head_before!=head_after: raise Stop("FROZEN_AUTHORITY_MUTATION")
    write("safety.json",{"status":"PASS","protected_before":before,"protected_after":after,"git_head_before":head_before,"git_head_after":head_after,"git_status_before":status_before,"git_status_after":status_after,"production_change":0,"model_v4_mutation":0,"model_v3_mutation":0,"registry_promotion":0,"final_candidate_model":0,"feature_change":0,"threshold_optimization":0,"buy_engine_change":0,"decision_engine_change":0,"february_use":0,"new_result_acquisition":0,"historical_current_prediction_rerun":0,"v3_protocol_change":0,"v4_protocol_change":0,"cf_protocol_change":0,"authorized_logistic_fits":7,"authorized_scaler_fits":7,"authorized_hgb_fits":7})
    report=f"# Nonlinear BUY Selection — 7-fold Logistic vs HGB CV\n\nVerdict: `{verdict}` pending independent review.\n\nLogistic: {pooled['logistic']['top3_hits']} / {pooled['logistic']['valid_selected_count']} = {rate_pp(pooled['logistic']['buy_top3_rate']):.4f}%\nHGB: {pooled['hgb']['top3_hits']} / {pooled['hgb']['valid_selected_count']} = {rate_pp(pooled['hgb']['buy_top3_rate']):.4f}%\nDifference: {pooled['raw_hit_difference']:+d} hits; {rate_pp(pooled['buy_top3_rate_lift']):+.4f}pt.\n"
    (OUT/"report.md").write_text(report,encoding="utf-8")
    write("artifact_hashes.json",{"indexed_artifacts":{str(p.relative_to(OUT)).replace("\\","/"):sha(p) for p in sorted(x for x in OUT.rglob("*") if x.is_file() and x.name!="artifact_hashes.json")},"self_hash_excluded":True})
    return OUT
if __name__=="__main__": print(main())
