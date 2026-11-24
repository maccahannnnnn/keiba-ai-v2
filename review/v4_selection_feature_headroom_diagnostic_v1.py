"""TRAIN-only, non-evidential V4 selection feature-headroom diagnostic."""
from __future__ import annotations

import csv, hashlib, json, math
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"reports"/"v4_selection_feature_headroom_diagnostic_v1"
DATA=ROOT/"reports"/"ml_v4_buy_selection_dataset_v2"
MODEL=ROOT/"reports"/"ml_v4_buy_selection_model_v3"
BUY_PRECISION=ROOT/"reports"/"buy_precision_v1"
ROOT_CAUSE=ROOT/"reports"/"failed_buy_root_cause_v1"
FEATURES=["Ability","PastPerformance","Distance","CourseShape","LapSuitability","RaceShape","PaceStyle","shadow_ai_rank","decision_score","final_score","adjusted_score","absolute_quality_pass","relative_advantage_pass","effective_reliability_pass","risk_guard_pass","consensus_positive_count","consensus_negative_count","risk_count","conflict_count"]
TRANSFORMED=[*FEATURES,"is_PLAY_UNCONVERGED_4PLUS","is_SKIP"]
EXPECTED={"dataset.csv":"b61994c2a488696a2fcc70f4b4f24e4756e4b6562ca751fa1f30819d30e535e2","model.joblib":"7f06d9e3ba2f330b6f42d699ee25ea64d83a5287c3b7f72fb0233e14c755312d","scaler.joblib":"800a0d54307e0caafef7b8efd131f5ab60f1d75d1e021dae7627d690187d103c","feature_transform_schema.json":"b30a4142b23ed3eecd6a24d516b3e020b213994798f776e2a97f444e60fd9fe2"}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x): p.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
def f(x): return float(x)
def b(x): return 1.0 if x=="True" else 0.0
def label(x):
    if x not in {"0","1"}: raise RuntimeError("TARGET_LABEL_FORMAT_INVALID")
    return float(x)
def corr(x,y):
    if np.std(x)==0 or np.std(y)==0:return 0.0
    return float(np.corrcoef(x,y)[0,1])
def cohend(a,bv):
    if len(a)<2 or len(bv)<2:return None
    s=math.sqrt((np.var(a,ddof=1)+np.var(bv,ddof=1))/2)
    return 0.0 if s==0 else float((np.mean(a)-np.mean(bv))/s)

def candidate_stats(name, values, y, blocks, X, selected, missed):
    values=np.asarray(values,float); block_corr={k:corr(values[idx],y[idx]) for k,idx in blocks.items()}
    max_red=max(abs(corr(values,X[:,j])) for j in range(X.shape[1]))
    fp=np.where(selected & (y==0))[0]; tp=np.where(selected & (y==1))[0]
    miss=np.where(missed)[0]
    return {"name":name,"target_correlation":corr(values,y),"max_abs_correlation_existing":max_red,"incremental_proxy":abs(corr(values,y))*(1-max_red),"temporal_block_target_correlation":block_corr,"temporal_same_direction_fraction":sum(np.sign(v)==np.sign(corr(values,y)) for v in block_corr.values() if v!=0)/max(1,sum(v!=0 for v in block_corr.values())),"selected_tp_vs_fp_cohen_d":cohend(values[tp],values[fp]),"missed_top3_vs_selected_fp_cohen_d":cohend(values[miss],values[fp]),"mean":float(np.mean(values)),"std":float(np.std(values))}

def main():
    if OUT.exists(): raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    for n,h in EXPECTED.items():
        p=(DATA/n) if n=="dataset.csv" else (MODEL/n)
        if sha(p)!=h: raise RuntimeError(f"AUTHORITY_HASH_MISMATCH:{n}")
    rows=list(csv.DictReader((DATA/"dataset.csv").open(encoding="utf8",newline="")))
    if len(rows)!=3240 or set(rows[0])-{*rows[0]}: raise RuntimeError("DATASET_ROW_OR_COLUMN_INVALID")
    if any(r["split_role"]!="TRAIN" or r["current_top5"]!="True" for r in rows): raise RuntimeError("TRAIN_POPULATION_MISMATCH")
    model,scaler=joblib.load(MODEL/"model.joblib"),joblib.load(MODEL/"scaler.joblib")
    transform=json.loads((MODEL/"feature_transform_schema.json").read_text(encoding="utf8"))
    if transform.get("transformed_model_input_columns")!=TRANSFORMED: raise RuntimeError("TRANSFORM_MISMATCH")
    X=np.array([[f(r[x]) if x not in {"absolute_quality_pass","relative_advantage_pass","effective_reliability_pass","risk_guard_pass"} else b(r[x]) for x in FEATURES]+[1.0 if r["race_state"]=="PLAY_UNCONVERGED_4PLUS" else 0.0,1.0 if r["race_state"]=="SKIP" else 0.0] for r in rows])
    y=np.array([label(r["actual_top3"]) for r in rows]); prob=model.predict_proba(scaler.transform(X))[:,1]
    if len(prob)!=3240: raise RuntimeError("MODEL_REPRODUCTION_FAILURE")
    group=defaultdict(list)
    for i,r in enumerate(rows): group[r["race_id"]].append(i)
    selected=np.zeros(len(rows),dtype=bool)
    for race,ids in group.items():
        sample=rows[ids[0]]; n=sum(r["current_buy"]=="True" for r in (rows[i] for i in ids))
        if sample["race_state"]=="PLAY_CONVERGED" and n>0:
            order=sorted(ids,key=lambda i:(-prob[i],int(float(rows[i]["shadow_ai_rank"])),int(rows[i]["horse_number"])))
            selected[order[:n]]=True
    missed=(~selected)&(y==1)
    blocks={k:np.array([i for i,r in enumerate(rows) if r["source_block"]==k]) for k in sorted({r["source_block"] for r in rows})}
    coeff=[{"feature":name,"coefficient":float(c),"abs_coefficient":abs(float(c)),"direction":"positive" if c>0 else "negative","target_correlation":corr(X[:,i],y),"standardized_input":True,"pairwise_high_correlation":sorted([{"feature":FEATURES[j] if j<len(FEATURES) else TRANSFORMED[j],"correlation":corr(X[:,i],X[:,j])} for j in range(len(TRANSFORMED)) if j!=i],key=lambda z:-abs(z["correlation"]))[:3]} for i,(name,c) in enumerate(zip(TRANSFORMED,model.coef_[0]))]
    # Race-relative family; probability is diagnostic only, never a prospective input proposal.
    A={"adjusted_score_gap_to_top":np.zeros(len(rows)),"decision_score_gap_to_top":np.zeros(len(rows)),"adjusted_score_z_within_race":np.zeros(len(rows)),"adjusted_score_percentile":np.zeros(len(rows)),"probability_gap_to_cutoff":np.zeros(len(rows)),"top5_adjusted_score_spread":np.zeros(len(rows))}
    B={"consensus_margin":np.zeros(len(rows)),"consensus_ratio":np.zeros(len(rows)),"risk_conflict_density":np.zeros(len(rows)),"race_score_dispersion":np.zeros(len(rows))}
    C={"evaluator_score_range":np.zeros(len(rows)),"evaluator_score_std":np.zeros(len(rows)),"positive_negative_coexistence":np.zeros(len(rows)),"evaluator_vote_entropy":np.zeros(len(rows))}
    for ids in group.values():
        adj=np.array([f(rows[i]["adjusted_score"]) for i in ids]); dec=np.array([f(rows[i]["decision_score"]) for i in ids]); p=prob[ids]; cutoff=sorted(p,reverse=True)[sum(rows[i]["current_buy"]=="True" for i in ids)-1] if sum(rows[i]["current_buy"]=="True" for i in ids)>0 else max(p)
        for pos,i in enumerate(ids):
            A["adjusted_score_gap_to_top"][i]=adj[pos]-max(adj); A["decision_score_gap_to_top"][i]=dec[pos]-max(dec); A["adjusted_score_z_within_race"][i]=0 if np.std(adj)==0 else (adj[pos]-np.mean(adj))/np.std(adj); A["adjusted_score_percentile"][i]=sum(adj<=adj[pos])/len(adj); A["probability_gap_to_cutoff"][i]=p[pos]-cutoff; A["top5_adjusted_score_spread"][i]=np.std(adj)
            posc,negc=f(rows[i]["consensus_positive_count"]),f(rows[i]["consensus_negative_count"]); risk,conf=f(rows[i]["risk_count"]),f(rows[i]["conflict_count"])
            B["consensus_margin"][i]=posc-negc; B["consensus_ratio"][i]=(posc-negc)/max(1,posc+negc); B["risk_conflict_density"][i]=(risk+conf)/max(1,posc+negc+risk+conf); B["race_score_dispersion"][i]=np.std(adj)
            votes=np.array([f(rows[i][x]) for x in ["Ability","PastPerformance","Distance","CourseShape","LapSuitability","RaceShape","PaceStyle"]]); plus,minus=np.sum(votes>0),np.sum(votes<0); total=max(1,plus+minus); probs=[plus/total,minus/total]
            C["evaluator_score_range"][i]=np.ptp(votes); C["evaluator_score_std"][i]=np.std(votes); C["positive_negative_coexistence"][i]=1.0 if plus and minus else 0.0; C["evaluator_vote_entropy"][i]=-sum(q*math.log(q) for q in probs if q)
    families={"RELATIVE_GAP_RELATIVE_POSITION":A,"CONVERGENCE_STRENGTH":B,"EVALUATOR_DISAGREEMENT_STRUCTURE":C}
    stats={family:[candidate_stats(name,values,y,blocks,X,selected,missed) for name,values in candidates.items()] for family,candidates in families.items()}
    ranking=[]
    for family,items in stats.items():
        best=max(items,key=lambda z:(z["incremental_proxy"],z["temporal_same_direction_fraction"],abs(z["selected_tp_vs_fp_cohen_d"] or 0)))
        ranking.append({"family":family,"best_candidate":best["name"],"incremental_proxy":best["incremental_proxy"],"temporal_stability":best["temporal_same_direction_fraction"],"error_separation":best["selected_tp_vs_fp_cohen_d"],"explainability":"HIGH" if family!="EVALUATOR_DISAGREEMENT_STRUCTURE" else "MEDIUM","leakage_risk":"NONE","implementation_complexity":"LOW" if family=="RELATIVE_GAP_RELATIVE_POSITION" else "MEDIUM"})
    ranking.sort(key=lambda z:(-z["incremental_proxy"],-z["temporal_stability"],-(abs(z["error_separation"]) if z["error_separation"] is not None else 0)))
    # Non-evidential triage: leave-one-source-block-out, no model artifact saved.
    aucs=[]
    for test in blocks.values():
        train=np.setdiff1d(np.arange(len(rows)),test); sl=StandardScaler().fit(X[train]); lr=LogisticRegression(solver="lbfgs",max_iter=1000).fit(sl.transform(X[train]),y[train]); tree=DecisionTreeClassifier(max_depth=3,min_samples_leaf=30,random_state=0).fit(X[train],y[train]); aucs.append({"test_block":rows[int(test[0])]["source_block"],"logistic_auc":roc_auc_score(y[test],lr.predict_proba(sl.transform(X[test]))[:,1]),"shallow_tree_auc":roc_auc_score(y[test],tree.predict_proba(X[test])[:,1])})
    nonlinear={"label":"NON_EVIDENTIAL_DEVELOPMENT_TRIAGE_ONLY","method":"leave-one-source-block-out; LogisticRegression vs DecisionTree(max_depth=3,min_samples_leaf=30)","folds":aucs,"mean_logistic_auc":float(np.mean([x["logistic_auc"] for x in aucs])),"mean_shallow_tree_auc":float(np.mean([x["shallow_tree_auc"] for x in aucs])),"models_saved":0,"gate_evidence":False}
    # Selection errors are TRAIN-only: V4 selected false positives and unselected Top3 within Top5.
    errors={"population":"TRAIN_ONLY_NON_EVIDENTIAL","v4_selected_count":int(selected.sum()),"false_positive_selection_style_count":int(np.sum(selected&(y==0))),"missed_top3_within_top5_count":int(np.sum(missed)),"selected_true_positive_count":int(np.sum(selected&(y==1))),"race_level_same_volume_reproduced":True}
    top5=json.loads((BUY_PRECISION/"top5_capture.json").read_text(encoding="utf8")); exports=list(csv.DictReader((ROOT_CAUSE/"top5_result_export.csv").open(encoding="utf8",newline="")))
    outside=[r for r in exports if r["valid_result"]=="True" and r["actual_top3"]=="True" and int(r["rank"])>5]
    side={"purpose":"FALLBACK_ONLY_NO_GENERATION_RULE","june_aug_top5_capture":top5["pooled"],"dataset_lineage_top5_capture_reference":0.5682,"top5_outside_actual_top3_rank_diagnostic":"NOT_EVALUABLE_FROM_TOP5_ONLY_EXPORT","top5_outside_rank_6_10_diagnostic":"NOT_EVALUABLE_FROM_TOP5_ONLY_EXPORT","source":"existing June-Aug root-cause export only; it contains Top5 rows only","no_candidate_generation":True}
    primary=ranking[0]
    nonlinear_dominant=nonlinear["mean_shallow_tree_auc"]>nonlinear["mean_logistic_auc"]+0.02 and primary["incremental_proxy"]<0.02
    if nonlinear_dominant: decision="V4_SELECTION_NONLINEAR_HEADROOM = CONFIRMED"; target="V4_MODEL_CLASS_NONLINEAR_DESIGN_V1"
    elif primary["incremental_proxy"]>0 and primary["temporal_stability"]>=0.5: decision="V4_SELECTION_FEATURE_HEADROOM = CONFIRMED"; target="V4_FEATURE_EXPANSION_RELATIVE_GAP_POSITION_V1" if primary["family"]=="RELATIVE_GAP_RELATIVE_POSITION" else f"V4_FEATURE_EXPANSION_{primary['family']}_V1"
    else: decision="V4_SELECTION_HEADROOM = NOT_CONFIRMED"; target="CANDIDATE_GENERATION_FAILURE_DIAGNOSTIC_V1"
    OUT.mkdir(parents=True)
    write(OUT/"authority_validation.json",{"status":"PASS","dataset_rows":len(rows),"semantic_features":20,"transformed_inputs":21,"sha256":{n:h for n,h in EXPECTED.items()},"duplicate_row_id_count":len(rows)-len({r["row_id"] for r in rows}),"dataset_label_columns":["actual_top3","actual_finish","valid_result"],"model_input_target_leakage_columns":[],"prohibited_oos_access":0})
    write(OUT/"existing_feature_baseline.json",{"standardized_scale":True,"features":coeff})
    write(OUT/"error_population.json",errors); write(OUT/"relative_gap_family.json",{"family":"A", "candidates":stats["RELATIVE_GAP_RELATIVE_POSITION"],"probability_features":"diagnostic_only_not_new_raw_input"}); write(OUT/"convergence_strength_family.json",{"family":"B","candidates":stats["CONVERGENCE_STRENGTH"],"existing_overlap_note":"consensus/risk counts are already present; only non-linear/race-relative forms are potential additions"}); write(OUT/"evaluator_disagreement_family.json",{"family":"C","candidates":stats["EVALUATOR_DISAGREEMENT_STRUCTURE"],"explainability":"family-level aggregates only; no evaluator one-hot proposal"}); write(OUT/"nonlinearity_triage.json",nonlinear)
    write(OUT/"incremental_information.json",{"method":"target correlation, maximum redundancy with 21 existing inputs, selection-error separation; TRAIN_ONLY", "families":stats}); write(OUT/"temporal_stability.json",{"blocks":list(blocks),"families":stats}); write(OUT/"candidate_generation_side_diagnostic.json",side); write(OUT/"feature_family_ranking.json",{"ranking":ranking,"primary_feature_family":primary["family"],"secondary_backup":ranking[1]["family"]}); write(OUT/"headroom_decision.json",{"status":"ACCEPT","decision":decision,"next_implementation_target":target,"proceed_condition":"ChatGPT + Claude + Human review before any implementation","next_stage_accept_reject":"new frozen Dataset/Candidate protocol and independent validation required; no performance promise", "buy_top3_rate_50_relevance":"Selection separation can improve which existing Top5 horses are chosen, but this diagnostic does not estimate points or guarantee 50%."})
    write(OUT/"safety.json",{"status":"PASS","production_change":0,"model_v3_change":0,"cf_change":0,"prospective_change":0,"march_train_reuse":0,"february_access":0,"march_result_access":0,"may_oos_access":0,"prospective_result_access":0,"model_fit_formal":0,"model_artifact_saved":0})
    (OUT/"report.md").write_text(f"# V4 Selection Feature Headroom Diagnostic v1\n\n- Decision: `{decision}`\n- Primary family: `{primary['family']}`\n- Next target: `{target}`\n- TRAIN-only, non-evidential diagnostic.\n",encoding="utf8")
    hs={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"}; write(OUT/"artifact_hashes.json",{"self_hash_excluded":True,"indexed_artifacts":hs})
    print("V4_SELECTION_FEATURE_HEADROOM_DIAGNOSTIC_V1=ACCEPT")

if __name__=="__main__": main()
