"""Non-evidential, TRAIN-only V4 ablation using frozen Dataset v3/v4 only."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import subprocess
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "reports" / "ml_v4_buy_selection_dataset_v3"
V4 = ROOT / "reports" / "ml_v4_buy_selection_dataset_v4"
OUT = ROOT / "reports" / "v4_model_v4_train_ablation_v1"
MARCH = "MARCH_2026_HISTORICAL_HOLDOUT_ADDITIVE_TRAIN_REUSE_V4"
BLOCKS = ("April", "May 2026 Independent OOS additive TRAIN reuse for V4 Model v3+", "June", "July H1", "July H2", "August Development", "August Development (Prospective)")
SMALL = "August Development (Prospective)"
BASE = ("Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle", "shadow_ai_rank", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count", "consensus_negative_count", "risk_count", "conflict_count", "race_state")
GAP = "adjusted_score_gap_to_top"
GATES = {"absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass"}
EXPECTED = {"v3_sha": "e30ac0412e62e502d3671f1222306cc8fc79853125a86cd0fd996fefa64187bc", "v4_sha": "b02bb4b59b5f297e60964f96050890dbf32a7ac3b5a9ef93424b9d612e3ae80a", "v3_rows": 3240, "v4_rows": 4100, "march_rows": 860}


class Stop(RuntimeError): pass
def sha(p: Path) -> str: return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n: str, x: object) -> None: (OUT/n).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def git(*a: str) -> str: return subprocess.run(["git",*a],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip()

def load(path: Path) -> list[dict[str,str]]:
    with path.open(encoding="utf-8",newline="") as f: return list(csv.DictReader(f))

def matrix(rows: list[dict[str,str]], gap: bool) -> tuple[np.ndarray,np.ndarray]:
    values=[]; targets=[]
    for r in rows:
        if r["valid_result"]!="True" or r["current_top5"]!="True": raise Stop(f"POPULATION_SEMANTICS:{r['row_id']}")
        state=r["race_state"]
        if state not in {"PLAY_CONVERGED","PLAY_UNCONVERGED_4PLUS","SKIP"}: raise Stop(f"RACE_STATE:{r['row_id']}")
        x=[]
        for f in BASE[:-1]:
            if f in GATES:
                if r[f] not in {"True","False"}: raise Stop(f"BOOLEAN:{r['row_id']}:{f}")
                x.append(float(r[f]=="True"))
            else: x.append(float(r[f]))
        x.extend([float(state=="PLAY_UNCONVERGED_4PLUS"),float(state=="SKIP")])
        if gap: x.append(float(r[GAP]))
        if r["actual_top3"] not in {"0","1"}: raise Stop(f"TARGET:{r['row_id']}")
        values.append(x); targets.append(int(r["actual_top3"]))
    return np.asarray(values,float),np.asarray(targets,int)

def summary(values: list[float]) -> dict:
    return {"fold_values":values,"mean":statistics.mean(values),"median":statistics.median(values),"standard_deviation":statistics.stdev(values) if len(values)>1 else 0.0,"min":min(values),"max":max(values),"positive_fold_count":sum(v>0 for v in values),"zero_fold_count":sum(v==0 for v in values),"negative_fold_count":sum(v<0 for v in values)}

def run_condition(name: str, train: list[dict], valid: list[dict], use_gap: bool) -> dict:
    xtr,ytr=matrix(train,use_gap); xva,yva=matrix(valid,use_gap)
    if len(set(ytr))!=2 or len(set(yva))!=2: raise Stop(f"CLASS_DEGENERACY:{name}")
    scaler=StandardScaler(); xtr=scaler.fit_transform(xtr); xva=scaler.transform(xva)
    model=LogisticRegression(penalty="l2",C=1.0,solver="lbfgs",class_weight=None).fit(xtr,ytr)
    p=model.predict_proba(xva)[:,1]
    features=[*BASE[:-1],"is_PLAY_UNCONVERGED_4PLUS","is_SKIP"]+([GAP] if use_gap else [])
    result={"condition":name,"validation_fold_size":len(valid),"train_rows":len(train),"semantic_feature_count":21 if use_gap else 20,"feature_count":len(features),"auc":roc_auc_score(yva,p),"log_loss":log_loss(yva,p,labels=[0,1]),"brier":brier_score_loss(yva,p),"positive_count":int(yva.sum()),"negative_count":int(len(yva)-yva.sum()),"scaler_fit_scope":"TRAIN_ONLY","model_serialized":False}
    if use_gap:
        coef=float(model.coef_[0,features.index(GAP)]); result.update({"relative_gap_coefficient":coef,"relative_gap_coefficient_sign":"POSITIVE" if coef>0 else "NEGATIVE" if coef<0 else "ZERO"})
    return result

def pair(name: str, left: dict, right: dict) -> dict:
    # left-right: AUC positive is better; log-loss/Brier positive means lower-is-better improvement.
    return {"comparison":name,"auc_delta":left["auc"]-right["auc"],"log_loss_improvement_lower_is_better":right["log_loss"]-left["log_loss"],"brier_improvement_lower_is_better":right["brier"]-left["brier"]}

def qualitative(one: list[float], two: list[float], labels: tuple[str,str,str,str]) -> str:
    # Purely descriptive sign synthesis; it is explicitly not a numerical gate.
    signs=[math.copysign(1,x) if x else 0 for x in [statistics.mean(one),statistics.mean(two)]]
    if all(x>0 for x in signs): return labels[0]
    if all(x<0 for x in signs): return labels[3]
    if signs[0]!=signs[1]: return labels[2]
    return labels[1]

def main() -> Path:
    if OUT.exists(): raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    before={"v3_dataset":sha(V3/"dataset.csv"),"v4_dataset":sha(V4/"dataset.csv"),"v3_manifest":sha(V3/"dataset_manifest.json"),"v4_manifest":sha(V4/"dataset_manifest.json")}
    if before["v3_dataset"]!=EXPECTED["v3_sha"] or before["v4_dataset"]!=EXPECTED["v4_sha"]: raise Stop("DATASET_AUTHORITY_SHA_MISMATCH")
    head,status=git("rev-parse","HEAD"),git("status","--porcelain")
    v3,v4=load(V3/"dataset.csv"),load(V4/"dataset.csv")
    if len(v3)!=EXPECTED["v3_rows"] or len(v4)!=EXPECTED["v4_rows"]: raise Stop("DATASET_SIZE_MISMATCH")
    b3={r["source_block"] for r in v3}; b4={r["source_block"] for r in v4}
    if b3!=set(BLOCKS) or b4!=set(BLOCKS)|{MARCH}: raise Stop(f"SOURCE_BLOCK_INVALID:{b3}:{b4}")
    march=[r for r in v4 if r["source_block"]==MARCH]
    existing=[r for r in v4 if r["source_block"]!=MARCH]
    if len(march)!=EXPECTED["march_rows"] or {r["row_id"] for r in existing}!={r["row_id"] for r in v3}: raise Stop("V3_V4_PARENT_RELATION_INVALID")
    OUT.mkdir(parents=True)
    inventory=[]; results=[]; pairs={"B_minus_A":[],"C_minus_A":[],"D_minus_C":[],"D_minus_B":[]}; interactions=[]; coefs=[]
    for block in BLOCKS:
        valid=[r for r in existing if r["source_block"]==block]
        six=[r for r in existing if r["source_block"]!=block]
        definitions={"A":(six,False),"B":(six,True),"C":([*six,*march],False),"D":([*six,*march],True)}
        inventory.append({"validation_block":block,"validation_fold_size":len(valid),"validation_positive":sum(int(r["actual_top3"]) for r in valid),"validation_negative":len(valid)-sum(int(r["actual_top3"]) for r in valid),"march_in_primary_validation":False,"warning":"SMALLER_VALIDATION_FOLD_INTERPRET_WITH_CAUTION" if block==SMALL else None})
        by={}
        for name,(train,gap) in definitions.items():
            r=run_condition(name,train,valid,gap); r["validation_block"]=block; results.append(r); by[name]=r
            if gap: coefs.append({"validation_block":block,"condition":name,"coefficient":r["relative_gap_coefficient"],"sign":r["relative_gap_coefficient_sign"]})
        for key,l,r in (("B_minus_A","B","A"),("C_minus_A","C","A"),("D_minus_C","D","C"),("D_minus_B","D","B")): pairs[key].append({"validation_block":block,**pair(key,by[l],by[r])})
        interactions.append({"validation_block":block,"auc_interaction":by["D"]["auc"]-by["B"]["auc"]-by["C"]["auc"]+by["A"]["auc"],"label":"DESCRIPTIVE_INTERACTION_DIAGNOSTIC_ONLY","warning":"DO_NOT_OVERINTERPRET_SINGLE_FOLD_INTERACTION"})
    if len(inventory)!=7 or len(results)!=28 or any(x["validation_fold_size"]!=len([r for r in existing if r["source_block"]==x["validation_block"]]) for x in inventory): raise Stop("PRIMARY_FOLD_STRUCTURE_INVALID")
    supplemental=[]
    for name,gap in (("A_MARCH_HELD_OUT",False),("B_MARCH_HELD_OUT",True)):
        r=run_condition(name,existing,march,gap); r.update({"validation_block":MARCH,"label":"SUPPLEMENTAL_STABILITY_DIAGNOSTIC_ONLY","march_in_training":False,"march_historical_gate_re_evaluation":False}); supplemental.append(r)
    pair_summary={}
    for name,rows in pairs.items():
        pair_summary[name]={metric:summary([r[metric] for r in rows]) for metric in ("auc_delta","log_loss_improvement_lower_is_better","brier_improvement_lower_is_better")}
    condition_summary={}
    for name in "ABCD": condition_summary[name]={metric:summary([r[metric] for r in results if r["condition"]==name]) for metric in ("auc","log_loss","brier")}
    gap_without=[r["auc_delta"] for r in pairs["B_minus_A"]]; gap_with=[r["auc_delta"] for r in pairs["D_minus_C"]]
    march_without=[r["auc_delta"] for r in pairs["C_minus_A"]]; march_with=[r["auc_delta"] for r in pairs["D_minus_B"]]
    interpretation={"relative_gap":qualitative(gap_without,gap_with,("SUPPORTIVE","NEUTRAL","UNSTABLE","ADVERSE")),"march_additive_train_population_effect":qualitative(march_without,march_with,("BROADLY_SUPPORTIVE","NEUTRAL","UNSTABLE","ADVERSE")),"labels":["NON_EVIDENTIAL_DEVELOPMENT_TRIAGE_ONLY","ADDITIONAL_TRAIN_POPULATION_EFFECT"],"not_a_gate":True,"model_v4_recipe_design_review_required":True,"model_v4_training_authorized":False}
    write("design_freeze.json",{"status":"V4_MODEL_V4_TRAIN_ABLATION_DESIGN_ACCEPTED","evidence_role":"NON_EVIDENTIAL_DEVELOPMENT_TRIAGE_ONLY","conditions":{"A":"existing six blocks, 20 semantic features","B":"existing six blocks, 21 semantic features including relative gap","C":"existing six blocks + March, 20 semantic features","D":"existing six blocks + March, 21 semantic features"},"hyperparameters":{"scaler":"StandardScaler TRAIN_ONLY","model":"LogisticRegression","penalty":"l2","C":1.0,"solver":"lbfgs","class_weight":None},"forbidden":["tuning","resampling","threshold optimization","subgroup CV","BUY_TOP3_RATE","same-volume reselection"]})
    write("dataset_authority.json",{"v3":before["v3_dataset"],"v4":before["v4_dataset"],"allowed_sources_only":True,"v3_rows":len(v3),"v4_rows":len(v4),"march_rows":len(march)})
    write("fold_inventory.json",{"primary_fold_count":7,"primary_validation_blocks":list(BLOCKS),"folds":inventory,"march_excluded_from_primary_validation":True})
    write("fold_results.json",{"results":results,"count":len(results)})
    write("pairwise_comparisons.json",{"comparisons":pairs,"summary":pair_summary,"metric_direction":{"auc_delta":"higher is better","log_loss_improvement_lower_is_better":"positive is better","brier_improvement_lower_is_better":"positive is better"}})
    write("interaction_diagnostic.json",{"label":"DESCRIPTIVE_INTERACTION_DIAGNOSTIC_ONLY","warning":"DO_NOT_OVERINTERPRET_SINGLE_FOLD_INTERACTION","folds":interactions,"summary":summary([r["auc_interaction"] for r in interactions])})
    write("supplemental_march_fold_lodo.json",{"label":"SUPPLEMENTAL_STABILITY_DIAGNOSTIC_ONLY","definition":"March held out; TRAIN uses existing seven blocks; only A/B-like feature comparison is defined.","results":supplemental,"march_historical_gate_re_evaluation":False})
    write("coefficient_stability.json",{"relative_gap_coefficients":coefs,"sign_counts":{s:sum(x["sign"]==s for x in coefs) for s in ("POSITIVE","NEGATIVE","ZERO")},"summary":summary([x["coefficient"] for x in coefs])})
    write("metric_summary.json",{"condition_summary":condition_summary,"pairwise_summary":pair_summary,"primary_summary":"UNWEIGHTED_FOLD_SUMMARY","small_fold_warning":"SMALLER_VALIDATION_FOLD_INTERPRET_WITH_CAUTION"})
    write("interpretation.json",interpretation)
    write("evidence_boundary.json",{"label":"NON_EVIDENTIAL_DEVELOPMENT_TRIAGE_ONLY","not_supported":["Historical PASS","Prospective ACCEPT","Production GO","Model v4 Formal Candidate"],"no_formal_model_artifact":True,"no_result_access_outside_frozen_datasets":True})
    after={"v3_dataset":sha(V3/"dataset.csv"),"v4_dataset":sha(V4/"dataset.csv"),"v3_manifest":sha(V3/"dataset_manifest.json"),"v4_manifest":sha(V4/"dataset_manifest.json")}
    if before!=after or git("rev-parse","HEAD")!=head: raise Stop("FROZEN_AUTHORITY_MUTATION")
    write("safety.json",{"status":"PASS","dataset_v3_mutation":0,"dataset_v4_mutation":0,"dataset_sha_before":before,"dataset_sha_after":after,"formal_model_artifact_saved":False,"production_change":0,"model_v3_change":0,"cf_change":0,"formal_prospective_change":0,"august_30_result_access":0,"february_access":0,"git_head_before":head,"git_head_after":git("rev-parse","HEAD"),"git_status_before":status,"git_status_after":git("status","--porcelain")})
    (OUT/"report.md").write_text("# V4 Model v4 TRAIN-only Ablation\n\nA/B/C/Dを同一7 validation blocksで比較した非証拠的development triageです。Dataset v3/v4以外のデータ、8/30 Result、Formal Model artifact、Production変更は使用していません。\n",encoding="utf-8")
    write("artifact_hashes.json",{"indexed_artifacts":{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!="artifact_hashes.json"},"self_hash_excluded":True})
    return OUT

if __name__=="__main__": print(main())
