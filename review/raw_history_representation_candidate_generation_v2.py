"""EXP-021: recipe-compatible raw-history Candidate Generation V2.

Additive development-only runner.  EXP-020 remains immutable.  The sole
numerical recipe change is Rich-arm LogisticRegression max_iter 100 -> 1000.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import warnings
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

import review.candidate_generation_stage_a_paired_population_expanded_v1 as stage_a
import review.candidate_generation_stage_b_fast_route_b4_buy_performance_v1 as stage_b
import review.raw_history_representation_candidate_generation_v1 as exp020

OUT=ROOT/"reports/raw_history_representation_candidate_generation_v2"
EXP020=ROOT/"reports/raw_history_representation_candidate_generation_v1"
LEDGER=ROOT/"KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md"
FINGERPRINT=ROOT/"KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"
STAGE_A_ROOT=ROOT/"reports/candidate_generation_stage_a_paired_population_expanded_v1"
STAGE_B_ROOT=ROOT/"reports/candidate_generation_stage_b_fast_route_b4_buy_performance_v1_retry5"
FEATURE_SCHEMA_SHA="119a319401e9e4435e8823c38c5233d312b03d5ec69b10ff0dc3da8844e46f64"
FOLD_SHA="ace55d0d48e24d066cee92e5a11aebbcf908f5256622303d5dd03bc1e5de099e"
CONTROL_SHA={"baseline":"b5445181231fa170871adb3aeb92226059036e39b8e33f4aeabd512600df2f85","treatment":"bfd0f36c872474fbde826047e537d59c9e95ccabd648f19a10c0740e0a645291"}
MAX_ITER=1000


class Stop(RuntimeError): pass
def sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(name:str,value:object)->None: (OUT/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def write_csv(name:str,rows:list[dict],fields:list[str])->None:
    with (OUT/name).open("w",encoding="utf-8",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)


def protected_hashes()->dict[str,str]:
    paths=[
        ROOT/"review/candidate_generation_stage_a_paired_population_expanded_v1.py",
        ROOT/"review/raw_history_representation_candidate_generation_v1.py",
        ROOT/"review/candidate_generation_stage_b_shadow_v1.py",
        ROOT/"review/candidate_generation_stage_b_fast_route_b4_buy_performance_v1.py",
        ROOT/"engine/decision_engine.py",ROOT/"engine/race_decision_engine.py",
        ROOT/"engine/shadow_buy_decision_engine.py",ROOT/"engine/buy_v1_rc1_engine.py",
        STAGE_A_ROOT/"expanded_stage_a_fold_manifest.json",STAGE_A_ROOT/"baseline_predictions.csv",STAGE_A_ROOT/"treatment_predictions.csv",
    ]
    paths += sorted(p for p in EXP020.rglob("*") if p.is_file())
    v4=ROOT/"reports/ml_v4_buy_selection_model_v4"
    paths += sorted(p for p in v4.rglob("*") if p.is_file())
    for date in [d for values in stage_a.MONTHS.values() for d in values]:
        paths += [exp020.raw_path(kind,date) for kind in ("DG","DE","DS")]
    unique={str(p.relative_to(ROOT)).replace("\\","/"):sha(p) for p in paths}
    return dict(sorted(unique.items()))


def feature_reuse_audit()->dict:
    path=EXP020/"raw_history_feature_schema_v1.json"
    if not path.is_file() or sha(path)!=FEATURE_SCHEMA_SHA: raise Stop("STOP_FEATURE_SCHEMA_REUSE_FAILURE")
    data=json.loads(path.read_text(encoding="utf-8"))
    checks={
        "history_depth":data.get("history_depth")==10,
        "included_ds_numeric_source_fields":len(data.get("included_numeric_source_fields",[]))==19,
        "raw_history_features":data.get("raw_history_feature_count")==390,
        "total_model_features":data.get("total_transformed_feature_count")==411,
        "person_pedigree_identifiers_excluded":data.get("person_pedigree_identifiers_excluded") is True,
        "missing_slot":data.get("missing_slot")=="all zeros including PRESENT=0",
        "present_row_missing_numeric":data.get("present_row_missing_numeric")=="value=0 and missing_indicator=1",
    }
    if not all(checks.values()): raise Stop("STOP_FEATURE_SCHEMA_REUSE_FAILURE")
    return {"EXP020_FEATURE_SCHEMA_REUSE_GATE":"PASS","path":str(path.relative_to(ROOT)).replace("\\","/"),"sha256":sha(path),"checks":checks,"zero_variance_columns_observed_by_independent_review":119,"feature_removal_authorized":False}


def register()->dict:
    before={"ledger":sha(LEDGER),"fingerprint":sha(FINGERPRINT)}
    index=json.loads(FINGERPRINT.read_text(encoding="utf-8"))
    entries=index.setdefault("authoritative_additive_entries",[])
    if any(e.get("stable_id")=="EXP-021" for e in entries): raise Stop("STOP_FINGERPRINT_REGISTRATION_FAILURE")
    if any(e.get("canonical_name")=="Raw History Representation Candidate Generation V2" for e in entries): raise Stop("STOP_FINGERPRINT_REGISTRATION_FAILURE")
    exp020_entry=next((e for e in entries if e.get("stable_id")=="EXP-020"),None)
    if not exp020_entry or exp020_entry.get("primary_result")!="STOP_MODEL_CONVERGENCE_FAILURE" or exp020_entry.get("operational_state")!="CLOSED": raise Stop("EXP020_AUTHORITY_INVALID")
    entry={"stable_id":"EXP-021","type":"DEVELOPMENT EXPERIMENT","canonical_name":"Raw History Representation Candidate Generation V2","aliases":["RAW_HISTORY_REPRESENTATION_CANDIDATE_GENERATION_V2"],"mechanism_family":"CANDIDATE_GENERATION","normalized_family":"CANDIDATE_GENERATION","evidence_role":"NON_EVIDENTIAL_DEVELOPMENT_ONLY","development_disposition":"OBSERVATION_ONLY","evidence_gate_status":"NOT_APPLICABLE","operational_state":"READY","model_role":"Candidate Generator","parent":"EXP-020","single_changed_parameter":{"name":"max_iter","from":100,"to":1000,"arm":"RICH_TEST_ONLY"},"same_model_family":True,"same_representation":True,"same_history_depth":10,"same_fold_manifest_sha256":FOLD_SHA,"same_exact5_semantics":True,"same_stage_b":True,"same_development_population":"45d/828r; February 160r training-only","target":"actual_top3","do_not_repeat":"PENDING_RESULT_REVIEW","untouched_holdout_used":False,"formal_prospective_used":False,"provenance":{"root":"reports/raw_history_representation_candidate_generation_v2/","registration_stage":"PRE_EXECUTION"}}
    entries.append(entry); index["total_logical_entries"]+=1; index["machine_state"]["TOTAL_LOGICAL_ENTRIES"]=index["total_logical_entries"]
    index["authoritative_last_update_date"]="2026-09-11"; index["development_disposition_counts"]["OBSERVATION_ONLY"]+=1; index["evidence_gate_status_counts"]["NOT_APPLICABLE"]+=1; index["operational_state_counts"]["READY"]+=1
    FINGERPRINT.write_text(json.dumps(index,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    addition=("\n## Authoritative Additive Entry — 2026-09-11 — EXP-021\n\n| Field | EXP-021 |\n|---|---|\n| Canonical name | Raw History Representation Candidate Generation V2 |\n| Parent | EXP-020（CLOSEDのまま不変） |\n| Evidence role | NON_EVIDENTIAL_DEVELOPMENT_ONLY |\n| Single changed parameter | Rich TEST arm max_iter 100 → 1000 |\n| Fixed | Same representation / HISTORY_DEPTH=10 / folds / Exact5 / Stage B / 45d・828r |\n| Operational state | READY（PRE-EXECUTION） |\n| Boundary | Untouched holdout・Formal Prospective・Productionは禁止 |\n| Provenance | `reports/raw_history_representation_candidate_generation_v2/` |\n")
    ledger_text=LEDGER.read_text(encoding="utf-8")
    replacements={
        "- Logical entries: 41":"- Logical entries: 42",
        "- Development disposition: NOT_SUPPORTED 5 / INCONCLUSIVE 3 / CLOSED 10 / OBSERVATION_ONLY 14 / NOT_APPLICABLE 9":"- Development disposition: NOT_SUPPORTED 5 / INCONCLUSIVE 3 / CLOSED 10 / OBSERVATION_ONLY 15 / NOT_APPLICABLE 9",
        "- Evidence gate: PASS 3 / ACCEPT 5 / CONSUMED 1 / HOLD 5 / REJECT 3 / PENDING 5 / NOT_APPLICABLE 19":"- Evidence gate: PASS 3 / ACCEPT 5 / CONSUMED 1 / HOLD 5 / REJECT 3 / PENDING 5 / NOT_APPLICABLE 20",
        "- Operational: ACTIVE 2 / PAUSE 1 / READY 1 / HOLD 1 / CLOSED 21 / COMPLETE 15":"- Operational: ACTIVE 2 / PAUSE 1 / READY 2 / HOLD 1 / CLOSED 21 / COMPLETE 15",
        "EXP-018, EXP-019, EXP-020`":"EXP-018, EXP-019, EXP-020, EXP-021`",
        "`TOTAL_LOGICAL_ENTRIES = 41`":"`TOTAL_LOGICAL_ENTRIES = 42`",
    }
    for old,new in replacements.items():
        if ledger_text.count(old)!=1: raise Stop("STOP_FINGERPRINT_REGISTRATION_FAILURE:LEDGER_SCHEMA:"+old)
        ledger_text=ledger_text.replace(old,new)
    LEDGER.write_text(ledger_text+addition,encoding="utf-8")
    return {"experiment_id":"EXP-021","duplicate_count":0,"collision_count":0,"ledger_before_sha256":before["ledger"],"fingerprint_index_before_sha256":before["fingerprint"],"ledger_registered_sha256":sha(LEDGER),"fingerprint_index_registered_sha256":sha(FINGERPRINT),"status":"REGISTERED_PRE_EXECUTION"}


def finalize_registry(result:str)->dict:
    index=json.loads(FINGERPRINT.read_text(encoding="utf-8")); entry=next(e for e in index["authoritative_additive_entries"] if e.get("stable_id")=="EXP-021")
    if entry["operational_state"]!="READY": raise Stop("EXP021_REGISTRY_STATE_INVALID")
    entry["operational_state"]="COMPLETE" if result=="COMPLETE" else "CLOSED"; entry["primary_result"]=result; entry["do_not_repeat"]="YES_WITH_UNCHANGED_FROZEN_RECIPE"
    entry["provenance"]["result_artifact"]="reports/raw_history_representation_candidate_generation_v2/report.md"
    index["operational_state_counts"]["READY"]-=1; index["operational_state_counts"][entry["operational_state"]]+=1
    FINGERPRINT.write_text(json.dumps(index,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    ledger_text=LEDGER.read_text(encoding="utf-8")
    before="- Operational: ACTIVE 2 / PAUSE 1 / READY 2 / HOLD 1 / CLOSED 21 / COMPLETE 15"
    after="- Operational: ACTIVE 2 / PAUSE 1 / READY 1 / HOLD 1 / CLOSED 21 / COMPLETE 16" if result=="COMPLETE" else "- Operational: ACTIVE 2 / PAUSE 1 / READY 1 / HOLD 1 / CLOSED 22 / COMPLETE 15"
    if ledger_text.count(before)!=1: raise Stop("EXP021_LEDGER_FINALIZATION_STATE_INVALID")
    ledger_text=ledger_text.replace(before,after)
    LEDGER.write_text(ledger_text+f"\n### EXP-021 Result Finalization\n\n- Result: `{result}`\n- Operational state: `{'COMPLETE' if result=='COMPLETE' else 'CLOSED'}`\n- EXP-020 remains CLOSED / STOP_MODEL_CONVERGENCE_FAILURE.\n",encoding="utf-8")
    return {"ledger_after_sha256":sha(LEDGER),"fingerprint_index_after_sha256":sha(FINGERPRINT)}


def prepare()->None:
    if OUT.exists() and (OUT/"exp021_registration.json").exists(): raise Stop(f"OUTPUT_EXISTS:{OUT}")
    if sha(STAGE_A_ROOT/"expanded_stage_a_fold_manifest.json")!=FOLD_SHA: raise Stop("FOLD_MANIFEST_MISMATCH")
    OUT.mkdir(parents=True,exist_ok=True)
    protected=protected_hashes(); reuse=feature_reuse_audit(); dump("exp020_feature_schema_reuse_audit.json",reuse)
    inventory,histories,source_stats=exp020.source_inventory_and_history()
    # Source-only as-of audit; feature-vector assertion is repeated during execute.
    if source_stats.get("DS_date_rejected",0)!=0: raise Stop("STOP_AS_OF_LEAKAGE")
    dump("ds_asof_runtime_audit.json",{"phase":"SOURCE_PREFLIGHT","DS_ROWS_INSPECTED":source_stats["DS_rows_inspected"],"AS_OF_VIOLATIONS":0,"history_depth":10,"source_stats":source_stats})
    registration=register(); dump("exp021_registration.json",registration)
    freeze={"experiment_id":"EXP-021","identity":"RAW_HISTORY_REPRESENTATION_CANDIDATE_GENERATION_V2","parent":"EXP-020","exp020_feature_schema_sha256":FEATURE_SCHEMA_SHA,"history_depth":10,"raw_ds_included_source_fields":19,"raw_history_features":390,"total_model_features":411,"fold_manifest_sha256":FOLD_SHA,"control_prediction_sha256":CONTROL_SHA,"control_recipe":{"max_iter":100,"unchanged":True},"rich_v2_recipe":{"pipeline":["StandardScaler","LogisticRegression"],"solver":"lbfgs","penalty":"l2","C":1.0,"tol":0.0001,"max_iter":1000,"class_weight":None,"target":"actual_top3"},"only_recipe_difference_from_exp020":"Rich max_iter 100 -> 1000","exact5":["probability DESC","shadow_ai_rank ASC","horse_number ASC"],"stage_b":{"implementation":str((ROOT/"review/candidate_generation_stage_b_shadow_v1.py").relative_to(ROOT)),"implementation_sha256":sha(ROOT/"review/candidate_generation_stage_b_shadow_v1.py"),"runner_sha256":sha(ROOT/"review/candidate_generation_stage_b_fast_route_b4_buy_performance_v1.py")},"development_scope":{"dates":45,"races":828,"february_training_only_dates":9,"february_training_only_races":160},"convergence_contract":{"fit_count":10,"warning_count":0,"n_iter_lt":1000,"finite_coefficients":True,"finite_intercept":True,"finite_probabilities":True,"performance_blind_until_all_pass":True},"downstream_acceptance":{"primary_baseline":{"control_valid_buy":679,"control_hits":266,"control_rate":0.3917525773195876},"secondary_treatment":{"control_natural_buy":720,"control_valid_buy":719,"control_invalid_buy":1,"control_hits":276,"control_rate":0.38386648122392214}},"evidence_role":"NON_EVIDENTIAL_DEVELOPMENT_ONLY","safety":{"max_iter_search":0,"solver_search":0,"feature_search":0,"history_depth_search":0,"threshold_search":0,"k_tuning":0,"subgroup_search":0,"untapped_holdout_access":0,"formal_prospective_execution":0},"protected_hashes":protected}
    dump("pre_execution_freeze_v2.json",freeze)
    registration["pre_execution_freeze_sha256"]=sha(OUT/"pre_execution_freeze_v2.json"); dump("exp021_registration.json",registration)
    dump("safety.json",{"phase":"PREPARED","performance_calculation":0,"result_access":0,"max_iter_search":0,"solver_search":0,"feature_search":0,"history_depth_search":0,"threshold_search":0,"k_tuning":0,"subgroup_search":0,"stage_b_change":0,"engine_change":0,"v4_change":0,"production_change":0,"untapped_holdout_access":0,"formal_prospective_execution":0})
    print("EXP021_PREPARE=COMPLETE",sha(OUT/"pre_execution_freeze_v2.json"))


def fit_v2(rows:list[dict],label:str):
    x=np.asarray([exp020.vector(r,True) for r in rows],dtype=float); y=np.asarray([r["actual_top3"] for r in rows],dtype=int)
    scaler=StandardScaler()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always"); z=scaler.fit_transform(x); model=LogisticRegression(solver="lbfgs",penalty="l2",C=1.0,class_weight=None,max_iter=MAX_ITER,tol=.0001).fit(z,y)
    conv=[str(w.message) for w in caught if issubclass(w.category,ConvergenceWarning)]
    coef=bool(np.isfinite(model.coef_).all()); intercept=bool(np.isfinite(model.intercept_).all())
    audit={"train_N":len(rows),"positive_N":int(y.sum()),"n_features":x.shape[1],"n_iter":int(model.n_iter_[0]),"warning_count":len(conv),"coefficient_finite":coef,"intercept_finite":intercept,"warnings":conv}
    if conv or model.n_iter_[0]>=MAX_ITER or not coef or not intercept: raise Stop("STOP_MODEL_CONVERGENCE_FAILURE:"+label+":"+json.dumps(audit,ensure_ascii=False))
    return scaler,model,audit


def predict_v2(rows:list[dict],scaler,model,label:str)->tuple[list[dict],bool]:
    grouped=defaultdict(list); finite=True
    for r in rows:
        p=float(model.predict_proba(scaler.transform(np.asarray([exp020.vector(r,True)],dtype=float)))[:,1][0]); finite &= math.isfinite(p); grouped[(r["date"],r["race_id"])].append({**r,"model":label,"probability":p})
    out=[]
    for key,items in grouped.items():
        ordered=sorted(items,key=exp020.exact5_order_key)
        if len(ordered)<5: raise Stop("INVALID_EXACT5")
        out += [{**r,"selected":i<5,"candidate_rank":i+1} for i,r in enumerate(ordered)]
    if not finite: raise Stop("STOP_MODEL_CONVERGENCE_FAILURE:NONFINITE_PROBABILITY")
    return out,finite


def candidate_comparison(control:list[dict],rich:list[dict],eval_rows:list[dict])->dict:
    def groups(values):
        g=defaultdict(set)
        for r in values:
            if r["selected"]: g[(r["date"],r["race_id"])].add(int(r["horse_number"]))
        return g
    c,r=groups(control),groups(rich); top=defaultdict(set)
    for x in eval_rows:
        if x["valid_result"] and x["actual_top3"]==1: top[(x["date"],x["race_id"])].add(int(x["horse_number"]))
    overlap=sum(len(c[k]&r[k]) for k in c); changed=sum(c[k]!=r[k] for k in c); control_hits=sum(len(c[k]&top[k]) for k in c); rich_hits=sum(len(r[k]&top[k]) for k in c)
    return {"race_count":len(c),"selected_slots":len(c)*5,"exact5_overlap_count":overlap,"exact5_overlap_rate":overlap/(len(c)*5),"changed_race_count":changed,"unchanged_race_count":len(c)-changed,"control_only_candidate_count":len(c)*5-overlap,"rich_only_candidate_count":len(c)*5-overlap,"control_candidate_top3_coverage":control_hits,"rich_candidate_top3_coverage":rich_hits,"candidate_coverage_delta":rich_hits-control_hits}


def lane_classification(rich:dict,control:dict)->str:
    rate_pos=rich["buy_top3_rate"]>control["buy_top3_rate"]; hit_pos=rich["top3_hits"]>control["top3_hits"]
    if rate_pos and rich["top3_hits"]>=control["top3_hits"]: return "CLEAN_POSITIVE"
    if rate_pos and not hit_pos: return "RATE_POSITIVE_HIT_TRADEOFF"
    if hit_pos and not rate_pos: return "HITS_POSITIVE_RATE_NONPOSITIVE"
    return "NOT_SUPPORTED"


def complete_registry(registration:dict,result:str)->None:
    final=finalize_registry(result); registration.update(final); registration["final_result"]=result; registration["status"]="FINALIZED"; dump("exp021_registration.json",registration)


def finalize_stop(reason:str,registration:dict|None=None)->None:
    result=reason.split(":",1)[0]
    if registration is None: registration=json.loads((OUT/"exp021_registration.json").read_text(encoding="utf-8"))
    complete_registry(registration,result)
    if not (OUT/"control_reproduction.json").exists(): dump("control_reproduction.json",{"CONTROL_REPRODUCTION_GATE":"NOT_EXECUTED","reason":result})
    if not (OUT/"convergence_audit.json").exists(): dump("convergence_audit.json",{"EXP021_CONVERGENCE_GATE":"FAIL","reason":reason,"development_performance_disclosed":False})
    if not (OUT/"fold_training_audit.json").exists(): dump("fold_training_audit.json",{"status":"STOPPED","reason":result,"performance_blind_until_convergence_gate":True})
    for name in ("rich_baseline_predictions.csv","rich_treatment_predictions.csv"):
        if not (OUT/name).exists(): write_csv(name,[],["model","selected","candidate_rank","date","month","race_id","venue","race_number","horse_number","horse_name","current_rank","valid_result","actual_finish","actual_top3","probability","shadow_ai_rank"])
    for name in ("rich_baseline_stage_b_natural_buy.csv","rich_treatment_stage_b_natural_buy.csv"):
        write_csv(name,[],["date","race_id","venue","race_number","horse_number","horse_name","decision","candidate_rank","current_rank"])
    for name in ("candidate_comparison_baseline.json","candidate_comparison_treatment.json","downstream_metrics.json","supporting_model_metrics.json","invalid_result_audit.json"):
        dump(name,{"status":"NOT_DISCLOSED_OR_NOT_EXECUTED","reason":result})
    frozen=json.loads((OUT/"pre_execution_freeze_v2.json").read_text(encoding="utf-8")); protected_ok=protected_hashes()==frozen["protected_hashes"]
    dump("safety.json",{"final":result,"max_iter_search":0,"solver_search":0,"feature_search":0,"history_depth_search":0,"threshold_search":0,"k_tuning":0,"subgroup_search":0,"stage_b_change":0,"engine_change":0,"v4_change":0,"production_change":0,"untapped_holdout_access":0,"formal_prospective_execution":0,"protected_runtime_zero_delta":"PASS" if protected_ok else "FAIL","git_commit":0,"git_push":0})
    (OUT/"report.md").write_text(f"# EXP-021 Raw History Representation Candidate Generation V2\n\n`RAW_HISTORY_REPRESENTATION_CANDIDATE_GENERATION_V2 = {result}`\n\n{reason}\n\nDevelopment performance was not disclosed.\n\n`NEXT = CLAUDE_INDEPENDENT_EXP021_IMPLEMENTATION_RESULT_REVIEW`\n",encoding="utf-8")
    finish_hash_index()


def finish_hash_index()->None:
    index={str(p.relative_to(OUT)).replace("\\","/"):{"sha256":sha(p),"size":p.stat().st_size} for p in OUT.rglob("*") if p.is_file() and p.name!="artifact_hash_index.json"}; dump("artifact_hash_index.json",{"self_hash_excluded":True,"indexed_artifacts":index})


def execute()->None:
    registration=json.loads((OUT/"exp021_registration.json").read_text(encoding="utf-8")); freeze=json.loads((OUT/"pre_execution_freeze_v2.json").read_text(encoding="utf-8"))
    if sha(EXP020/"raw_history_feature_schema_v1.json")!=FEATURE_SCHEMA_SHA or freeze["fold_manifest_sha256"]!=FOLD_SHA: raise Stop("STOP_FEATURE_SCHEMA_REUSE_FAILURE")
    mapping=stage_a.source_map(); stage_a.preflight(mapping); date_month={d:m for m,ds in stage_a.MONTHS.items() for d in ds}
    rows=stage_a.build_rows(mapping,date_month); _inventory,histories,source_stats=exp020.source_inventory_and_history(); rows,asof=exp020.enrich_rows(rows,histories)
    if asof["as_of_date_violations"] or asof["date_rejected"]: raise Stop("STOP_AS_OF_LEAKAGE")
    dump("ds_asof_runtime_audit.json",{"phase":"RUNTIME_FEATURE_VECTOR","DS_ROWS_INSPECTED":source_stats["DS_rows_inspected"],"AS_OF_VIOLATIONS":0,"target_horse_rows":len(rows),"history_rows_used":asof["used"],"history_buckets":asof["target_horse_history_buckets"]})
    folds=[{"fold_id":fid,"train_dates":[d for m in tm for d in stage_a.MONTHS[m]],"eval_dates":[d for m in em for d in stage_a.MONTHS[m]]} for fid,tm,em in stage_a.FOLD_SPEC]
    # CONTROL gate: original max_iter=100 via frozen Stage-A functions.
    control={"baseline":[],"treatment":[]}
    for f in folds:
        train=[r for r in rows if r["date"] in set(f["train_dates"]) and r["valid_result"]]; evaluation=[r for r in rows if r["date"] in set(f["eval_dates"])]
        for lane,tr in (("baseline",[r for r in train if r["current_top5"]]),("treatment",train)):
            s,m,_=stage_a.fit(tr,"EXP021_CONTROL_"+lane+"_"+f["fold_id"]); label="PAIRED_TOP5_BASELINE_EXACT5" if lane=="baseline" else "FULL_FIELD_TREATMENT_EXACT5"; control[lane]+=stage_a.select(evaluation,s,m,label)
    fields=["model","selected","candidate_rank","date","month","race_id","venue","race_number","horse_number","horse_name","current_rank","valid_result","actual_finish","actual_top3","probability","shadow_ai_rank"]
    for lane in control: write_csv(f"control_{lane}_predictions.csv",control[lane],fields)
    actual={lane:sha(OUT/f"control_{lane}_predictions.csv") for lane in control}; ok=actual==CONTROL_SHA; dump("control_reproduction.json",{"CONTROL_REPRODUCTION_GATE":"EXACT_MATCH_PASS" if ok else "FAIL","actual":actual,"expected":CONTROL_SHA,"copied":False})
    if not ok: raise Stop("STOP_CONTROL_REPRODUCTION_FAILURE")
    # Fit all ten Rich models and verify numerics before any performance aggregation.
    rich={"baseline":[],"treatment":[]}; audits=[]; probability_records={"baseline":[],"treatment":[]}
    for f in folds:
        train=[r for r in rows if r["date"] in set(f["train_dates"]) and r["valid_result"]]; evaluation=[r for r in rows if r["date"] in set(f["eval_dates"])]
        for lane,tr in (("baseline",[r for r in train if r["current_top5"]]),("treatment",train)):
            scaler,model,audit=fit_v2(tr,"RICH_"+lane+"_"+f["fold_id"]); prediction,finite=predict_v2(evaluation,scaler,model,"RICH_V2_"+lane.upper()+"_EXACT5")
            audit.update({"lane":lane,"fold":f["fold_id"],"probability_finite":finite}); audits.append(audit); rich[lane]+=prediction; probability_records[lane]+=[(int(r["actual_top3"]),float(r["probability"])) for r in prediction if r["valid_result"]]
    if len(audits)!=10 or any(a["warning_count"] or a["n_iter"]>=1000 or not a["coefficient_finite"] or not a["intercept_finite"] or not a["probability_finite"] for a in audits): raise Stop("STOP_MODEL_CONVERGENCE_FAILURE")
    dump("convergence_audit.json",{"EXP021_CONVERGENCE_GATE":"ALL_FOLDS_BOTH_LANES_PASS","fit_count":10,"fits":audits})
    dump("fold_training_audit.json",{"fold_manifest_sha256":FOLD_SHA,"folds":folds,"performance_blind_until_convergence_gate":True,"development_performance_disclosed_after_gate":True})
    for lane in rich: write_csv(f"rich_{lane}_predictions.csv",rich[lane],fields)
    evaluation=[r for r in rows if r["date"] not in set(stage_a.MONTHS["FEBRUARY"])]
    comparisons={lane:candidate_comparison(control[lane],rich[lane],evaluation) for lane in rich}
    for lane in comparisons: dump(f"candidate_comparison_{lane}.json",comparisons[lane])
    supporting={}
    for lane,values in probability_records.items():
        y=np.asarray([x[0] for x in values]); p=np.asarray([x[1] for x in values]); supporting[lane]={"role":"SUPPORTING_DIAGNOSTIC_ONLY","roc_auc":float(roc_auc_score(y,p)),"log_loss":float(log_loss(y,p)),"valid_rows":len(y)}
    dump("supporting_model_metrics.json",supporting)
    dates={d for f in folds for d in f["eval_dates"]}; all_sources=stage_a.source_map(); sources={d:all_sources[d] for d in dates}; current=stage_b.current_buys(dates,sources); all_keys={(d,json.loads(p.read_text(encoding="utf-8"))["race_id"]) for d in dates for p in sources[d]}
    original=stage_b.candidate_packet
    try:
        stage_b.candidate_packet=lambda lane,date,race_id,exact5,snapshot_hash:{"race_id":race_id,"race_context_snapshot_hash":snapshot_hash,"generator_id":"EXP021_RICH_"+lane.upper(),"generator_version_hash":sha(OUT/f"rich_{lane}_predictions.csv"),"generator_recipe_freeze_hash":sha(OUT/"pre_execution_freeze_v2.json"),"tie_break_id":stage_b.EXACT5_TIE_BREAK_ID,"exact5":deepcopy(exact5)}
        events=[]; manifest,natural,p1=stage_b.phase1(dates,sources,exp020.grouped_selected(rich["baseline"]),exp020.grouped_selected(rich["treatment"]),events)
    finally: stage_b.candidate_packet=original
    if p1["PHASE1_RESULT"]!="PASS": raise Stop("STOP_STAGE_B_INTEGRITY_FAILURE")
    for lane in natural: write_csv(f"rich_{lane}_stage_b_natural_buy.csv",natural[lane],["date","race_id","venue","race_number","horse_number","horse_name","decision","candidate_rank","current_rank"])
    enriched,joins,perf,_comparisons,_race_rows,undefined=stage_b.phase2(dates,all_keys,current,natural,events)
    if undefined or any(x["status"]!="PASS" for x in joins.values()): raise Stop("STOP_STAGE_B_INTEGRITY_FAILURE")
    controls=json.loads((STAGE_B_ROOT/"phase2_lane_performance.json").read_text(encoding="utf-8")); classifications={lane:lane_classification(perf[lane],controls[lane]) for lane in ("baseline","treatment")}
    downstream={"control":{"baseline":controls["baseline"],"treatment":controls["treatment"]},"rich":{"baseline":perf["baseline"],"treatment":perf["treatment"]},"classification":classifications,"rate_delta_pt":{lane:(perf[lane]["buy_top3_rate"]-controls[lane]["buy_top3_rate"])*100 for lane in ("baseline","treatment")},"hit_delta":{lane:perf[lane]["top3_hits"]-controls[lane]["top3_hits"] for lane in ("baseline","treatment")},"secondary_lane_signal":classifications["treatment"]=="CLEAN_POSITIVE" and classifications["baseline"]!="CLEAN_POSITIVE","result_join":joins}
    dump("downstream_metrics.json",downstream); dump("invalid_result_audit.json",{"baseline":perf["baseline"]["invalid_buy"],"treatment":perf["treatment"]["invalid_buy"],"semantics":"excluded from denominator; no replacement; not failure"})
    direction="SUPPORTED" if classifications["baseline"]=="CLEAN_POSITIVE" else "NOT_SUPPORTED"
    after=protected_hashes(); protected_ok=after==freeze["protected_hashes"]
    if not protected_ok: raise Stop("INVALID:PROTECTED_RUNTIME_ZERO_DELTA_FAIL")
    result="COMPLETE"; complete_registry(registration,result)
    safety={"max_iter_search":0,"solver_search":0,"feature_search":0,"history_depth_search":0,"threshold_search":0,"k_tuning":0,"subgroup_search":0,"stage_b_change":0,"engine_change":0,"v4_change":0,"production_change":0,"untapped_holdout_access":0,"formal_prospective_execution":0,"protected_runtime_zero_delta":"PASS","git_commit":0,"git_push":0}; dump("safety.json",safety)
    report=(f"# EXP-021 Raw History Representation Candidate Generation V2\n\n`RAW_HISTORY_REPRESENTATION_CANDIDATE_GENERATION_V2 = COMPLETE`\n\n- Convergence: ALL_FOLDS_BOTH_LANES_PASS (10/10).\n- Baseline Candidate coverage delta: {comparisons['baseline']['candidate_coverage_delta']:+d}; Stage B: {classifications['baseline']}.\n- Treatment Candidate coverage delta: {comparisons['treatment']['candidate_coverage_delta']:+d}; Stage B: {classifications['treatment']}.\n- PRIMARY_RICH_HISTORY_V2_SIGNAL = {classifications['baseline']}\n- RICH_HISTORY_DIRECTION = {direction}\n- V2_CAUSAL_ATTRIBUTION = DIRECTIONAL_ONLY_NOT_REPRESENTATION_ALONE\n- EVIDENCE_ROLE = NON_EVIDENTIAL_DEVELOPMENT_ONLY\n\n`NEXT = CLAUDE_INDEPENDENT_EXP021_IMPLEMENTATION_RESULT_REVIEW`\n")
    (OUT/"report.md").write_text(report,encoding="utf-8"); finish_hash_index()
    print("RAW_HISTORY_REPRESENTATION_CANDIDATE_GENERATION_V2=COMPLETE")


def main()->None:
    p=argparse.ArgumentParser(); p.add_argument("phase",choices=("prepare","execute")); a=p.parse_args()
    if a.phase=="prepare": prepare(); return
    try: execute()
    except Stop as e:
        finalize_stop(str(e)); print(str(e)); raise SystemExit(2)


if __name__=="__main__": main()
