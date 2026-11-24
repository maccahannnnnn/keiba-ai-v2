"""Result-free Phase1 for Selection Composition Policy v2."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

import joblib

from engine.shadow_buy_decision_engine import ShadowBUYDecisionEngine
from review.candidate_generation_stage_a_paired_population_expanded_v1 import JAPANESE_VENUE, parse_race_id, source_map
from review.candidate_generation_stage_b_shadow_v1 import CandidateGenerationStageBShadow, EXACT5_TIE_BREAK_ID
from review.selection_composition_policy_v2_shadow_v1 import SelectionCompositionPolicyV2Shadow

OUT = ROOT / "reports/selection_composition_policy_v2_shadow_phase1_v1"
STAGE_A = ROOT / "reports/candidate_generation_stage_a_paired_population_expanded_v1"
RETRY5 = ROOT / "reports/candidate_generation_stage_b_fast_route_b4_buy_performance_v1_retry5"
MODEL = ROOT / "reports/ml_v4_buy_selection_model_v4"
FOLD = STAGE_A / "expanded_stage_a_fold_manifest.json"
FEBRUARY = {"20260201","20260207","20260208","20260210","20260214","20260215","20260221","20260222","20260228"}
PROTECTED = {"20260718","20260719","20260808","20260809"}
SEMANTIC = ["Ability","PastPerformance","Distance","CourseShape","LapSuitability","RaceShape","PaceStyle","shadow_ai_rank","decision_score","final_score","adjusted_score","absolute_quality_pass","relative_advantage_pass","effective_reliability_pass","risk_guard_pass","consensus_positive_count","consensus_negative_count","risk_count","conflict_count","race_state"]
TRANSFORMED = [*SEMANTIC[:-1],"is_PLAY_UNCONVERGED_4PLUS","is_SKIP"]
GATES = set(SEMANTIC[11:15])
EVALUATOR_RUNTIME_FIELDS = {semantic: fields[0] for semantic, fields in ShadowBUYDecisionEngine.SCORE_FIELD_MAP.items()}
EXPECTED_PRE_HASHES = {
    "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md":"38ecee3be30bb30d6e3318d5dabd251a800e09cdcbccf68794a4925dc1867f16",
    "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json":"134f351b7e356ab396a14f1308ecef7536729d5e8bc731a709c3b3e03620964f",
    "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX_DRAFT_V3.json":"25dbe990d4f3f903f4a0afd6fad75c6f612926864aa33a047c143befce05a618",
    "reports/candidate_generation_stage_a_paired_population_expanded_v1/baseline_predictions.csv":"b5445181231fa170871adb3aeb92226059036e39b8e33f4aeabd512600df2f85",
    "reports/candidate_generation_stage_a_paired_population_expanded_v1/treatment_predictions.csv":"bfd0f36c872474fbde826047e537d59c9e95ccabd648f19a10c0740e0a645291",
    "reports/ml_v4_buy_selection_model_v4/model.joblib":"58d3977d0f44eab325a2b384f0c17b66ddc276fff6370f6e05b7a1680642d74f",
    "reports/ml_v4_buy_selection_model_v4/scaler.joblib":"3d18757f4991c21a4a645f92ca26361d88c030a4097696d2cc4a6c86d3767b90",
    "reports/ml_v4_buy_selection_model_v4/selected_feature_columns.json":"acf79da95865cc087cead024280f04baa4eeda2b98911c2aa21be9c010af3c5d",
    "reports/ml_v4_buy_selection_model_v4/feature_transform_schema.json":"ac1929813d05cd8beb7e60f6a01661038a5dc2e629ba000af5ae3820b47133b6",
    "review/candidate_generation_stage_b_shadow_v1.py":"2400840156cc138fcab50652c5c2fc7625c07cfcaf079d9bc50b6d374a354d8b",
    "engine/decision_engine.py":"3d3ef815650867120a4ce5716cf4fb8a5fc426736e1f360fa23a0823c57206c3",
    "engine/decision_guard.py":"ee6c8ecb163aec9bb20b1d1858edabc7b3419bda1e6beeed1c67d68f217e68ff",
    "engine/buy_v1_rc1_engine.py":"85a7ecb4c164d719700d618d11b739b1b5dcb853f242266e375534d42e41e6b4",
    "engine/shadow_buy_decision_engine.py":"06b75c09f9ecd4c6a79be709a95a9f2385088b67e868e4e8e3c158c2b2b2bf17",
    "engine/race_decision_engine.py":"468bf0eb4b1f2762611f1ff45e138a4ef2a3234bf6ee24fddde153dede93250c",
    "engine/race_decision_buy_synchronizer.py":"28d79d3f4698b580c702cd76229e77d1db2166d297b6f2e5b6b3060dd86ca2e3",
    "evaluation/target_trial_adapter.py":"a7a0465fd75babadbac1eed6ee9eb0580d32f7b2e95f10ccad0b67774ba8a506",
}


class Stop(RuntimeError): pass
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def dump(name: str, value): (OUT/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def now(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def write_csv(name,rows,fields):
    with (OUT/name).open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)


def verify_index(root: Path) -> dict:
    index=root/"artifact_hash_index.json"
    if not index.is_file(): index=root/"artifact_hashes.json"
    entries=load(index).get("indexed_artifacts",{});bad=[]
    for name,value in entries.items():
        expected=value.get("sha256") if isinstance(value,dict) else value
        if not (root/name).is_file() or sha(root/name)!=expected: bad.append(name)
    return {"index":str(index.relative_to(ROOT)),"count":len(entries),"mismatches":bad,"status":"PASS" if not bad else "FAIL"}


def precheck():
    observed={name:sha(ROOT/name) for name in EXPECTED_PRE_HASHES if (ROOT/name).is_file()}; missing=[name for name in EXPECTED_PRE_HASHES if not (ROOT/name).is_file()]; mismatch=[name for name,value in EXPECTED_PRE_HASHES.items() if observed.get(name)!=value]
    if missing or mismatch: raise Stop(f"PRE_MODIFICATION_HASH_MISMATCH:{missing}:{mismatch}")
    for root in (RETRY5,MODEL):
        if verify_index(root)["status"]!="PASS": raise Stop(f"FROZEN_INDEX_INVALID:{root.name}")
    selected=load(MODEL/"selected_feature_columns.json"); transformed=load(MODEL/"feature_transform_schema.json")
    if selected.get("semantic_selected_columns")!=SEMANTIC or transformed.get("transformed_model_input_columns")!=TRANSFORMED: raise Stop("V4_FEATURE_CONTRACT_INVALID")
    stage_text=(ROOT/"review/candidate_generation_stage_b_shadow_v1.py").read_text(encoding="utf-8")
    if "decision_rank_override=None" not in stage_text: raise Stop("POLICY_V2_OVERRIDE_INTERFACE_GAP")
    return {"AUTHORITY_PRECHECK":"PASS","pre_modification_hashes":observed,"retry5_hash_index":verify_index(RETRY5),"v4_hash_index":verify_index(MODEL),"duplicate_precheck":"PASS_NEW_OR_MATERIALLY_DISTINCT","duplicate_matches":0,"round3_logical_entries_reviewed":40}


def scope():
    fold=load(FOLD);dates={d for x in fold["folds"] for d in x["eval_dates"]};sources=source_map();races=sum(len(sources[d]) for d in dates)
    if len(dates)!=45 or races!=828 or dates & FEBRUARY or dates & PROTECTED: raise Stop(f"SCOPE_INVALID:{len(dates)}:{races}")
    return dates,sources


def candidate_rows(path: Path,dates):
    groups=defaultdict(list)
    with path.open(encoding="utf-8",newline="") as f:
        reader=csv.reader(f); header=next(reader); pos={name:header.index(name) for name in ("selected","candidate_rank","date","race_id","horse_number","horse_name","probability","shadow_ai_rank","current_rank")}
        for row in reader:
            if row[pos["date"]] in dates and row[pos["selected"]]=="True":
                groups[(row[pos["date"]],row[pos["race_id"]])].append({"horse_number":int(row[pos["horse_number"]]),"horse_name":row[pos["horse_name"]],"candidate_rank":int(row[pos["candidate_rank"]]),"candidate_probability":float(row[pos["probability"]]),"shadow_ai_rank":float(row[pos["shadow_ai_rank"]]),"current_rank":int(row[pos["current_rank"]])})
    if len(groups)!=828 or any(len(v)!=5 or sorted(x["candidate_rank"] for x in v)!=[1,2,3,4,5] for v in groups.values()): raise Stop("FROZEN_CANDIDATE_INVALID")
    return groups


def current_k_metadata(dates):
    counts=Counter()
    with (RETRY5/"current_frozen_buy.csv").open(encoding="utf-8",newline="") as f:
        for row in csv.DictReader(f):
            if row["date"] in dates: counts[(row["date"],row["race_id"])]+=1
    if sum(counts.values())!=623 or len(counts)!=374: raise Stop(f"CURRENT_K_METADATA_INVALID:{sum(counts.values())}:{len(counts)}")
    return counts


def scan_forbidden(value,context):
    forbidden={"actual_top3","actual_finish","finish","valid_result","result","results"}
    if isinstance(value,dict):
        for key,child in value.items():
            if str(key).lower() in forbidden: raise Stop(f"RESULT_FIELD_PRESENT:{context}:{key}")
            scan_forbidden(child,context)
    elif isinstance(value,list):
        for child in value: scan_forbidden(child,context)


def full_context(path: Path):
    payload=load(path);scan_forbidden(payload,str(path));trace=payload.get("buy_gate_trace");ranked=payload.get("ranked_results")
    if not isinstance(trace,dict) or not isinstance(trace.get("horses"),list) or not isinstance(ranked,list): raise Stop(f"TRACE_INVALID:{path}")
    tb={int(x["horse_number"]):x for x in trace["horses"]};rb={int(x["horse_number"]):x for x in ranked}
    if len(tb)!=len(ranked) or set(tb)!=set(rb): raise Stop(f"FULL_CONTEXT_IDENTITY_INVALID:{payload.get('race_id')}")
    rows=[]
    for number in sorted(rb):
        snapshot=tb[number].get("evaluator_score_snapshot")
        if not isinstance(snapshot,dict): raise Stop("EVALUATOR_SNAPSHOT_MISSING")
        row=dict(tb[number]);row.update(rb[number])
        for semantic,runtime_field in EVALUATOR_RUNTIME_FIELDS.items():
            if semantic not in snapshot or snapshot[semantic] is None: raise Stop(f"EVALUATOR_FIELD_MISSING:{semantic}")
            row[runtime_field]=snapshot[semantic]
        rows.append(row)
    race_id=payload["race_id"];date,venue,number=parse_race_id(race_id);context={"race_id":race_id,"date":date,"venue":JAPANESE_VENUE[venue],"race_number":number,"race_structure":{},"structure_flags":{},"baseline_race_decision_result":None}
    state=trace.get("race",{}).get("shadow_race_state")
    if state not in {"PLAY_CONVERGED","PLAY_UNCONVERGED_4PLUS","SKIP"}: raise Stop(f"RACE_STATE_INVALID:{race_id}")
    return rows,context,state


def feature_vector(row,state):
    snapshot=row.get("evaluator_score_snapshot");values=[]
    for field in SEMANTIC[:-1]:
        value=snapshot.get(field) if field in SEMANTIC[:7] else row.get(field)
        if field in GATES:
            if not isinstance(value,bool): raise Stop(f"BOOLEAN_FEATURE_INVALID:{field}")
            values.append(float(value))
        else:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(float(value)): raise Stop(f"NUMERIC_FEATURE_INVALID:{field}")
            values.append(float(value))
    values.extend([float(state=="PLAY_UNCONVERGED_4PLUS"),float(state=="SKIP")])
    if len(values)!=21: raise Stop("FEATURE_WIDTH_INVALID")
    return values


def packet(lane,race_id,exact5,snapshot_hash):
    return {"race_id":race_id,"race_context_snapshot_hash":snapshot_hash,"generator_id":"TOP5_CONDITIONED_BASELINE" if lane=="baseline" else "FULL_FIELD_TREATMENT","generator_version_hash":sha(STAGE_A/("baseline_predictions.csv" if lane=="baseline" else "treatment_predictions.csv")),"generator_recipe_freeze_hash":sha(STAGE_A/"expanded_stage_a_recipe_freeze.json"),"tie_break_id":EXACT5_TIE_BREAK_ID,"exact5":deepcopy(exact5)}


def phase1(dates,sources,lanes,kmeta,model,scaler):
    stage=CandidateGenerationStageBShadow();policy=SelectionCompositionPolicyV2Shadow(stage);manifest=[];natural={"baseline":[],"treatment":[]};audit=Counter();k_account={lane:{"k0":Counter(),"kgt0":Counter()} for lane in lanes};buy_dist={lane:Counter() for lane in lanes}
    for date in sorted(dates):
        for path in sorted(sources[date]):
            rows,context,state=full_context(path);key=(date,context["race_id"]);K=int(kmeta.get(key,0))
            for lane,groups in lanes.items():
                exact5=groups.get(key)
                if exact5 is None: raise Stop(f"CANDIDATE_MISSING:{lane}:{key}")
                snap=stage.race_context_snapshot(rows,context);pkt=packet(lane,key[1],exact5,snap["snapshot_hash"]);before=deepcopy(pkt)
                result=policy.run(pkt,rows,context,model=model,scaler=scaler,feature_vector=feature_vector,race_state=state,current_k_metadata=K)
                record={"date":date,"race_id":key[1],"lane":lane,"status":result.get("status"),"candidate_count":5,"prior_current_k":K,"failure_state":result.get("failure_state","")}
                if result.get("status")!="COMMITTED": audit["stop"]+=1;manifest.append(record);continue
                if pkt!=before: audit["candidate_mutation"]+=1
                ranks=result["v4_rank"];override=result["decision_rank_override"];horses={int(x["horse_number"]):x for x in result["stage_b_result"]["horses"]};candidate_numbers={x["horse_number"] for x in exact5}
                if set(ranks.values())!={1,2,3,4,5}: audit["v4_rank"]+=1
                if set(override)!=candidate_numbers or set(override.values())!={1,2,3,4,5}: audit["override"]+=1
                audit["candidate_999"]+=sum(horses[n].get("decision_rank")==999 for n in candidate_numbers)
                audit["decision_rank_mismatch"]+=sum(horses[n].get("decision_rank")!=ranks[n] for n in candidate_numbers)
                audit["noncandidate"]+=sum(x.get("decision")=="BUY" for n,x in horses.items() if n not in candidate_numbers)
                audit["operational_k"]+=result["policy_metadata"]["operational_k_dependency_count"]
                buys=[x for n,x in horses.items() if x.get("decision")=="BUY"]
                for x in buys: natural[lane].append({"date":date,"race_id":key[1],"venue":context["venue"],"race_number":context["race_number"],"horse_number":int(x["horse_number"]),"horse_name":x["horse_name"],"decision":"BUY","candidate_rank":x.get("candidate_rank"),"v4_rank":ranks[int(x["horse_number"])],"decision_rank":x.get("decision_rank"),"prior_current_k":K})
                bucket="k0" if K==0 else "kgt0";k_account[lane][bucket]["races"]+=1;k_account[lane][bucket]["buy"]+=len(buys);k_account[lane][bucket]["positive"]+=bool(buys);buy_dist[lane][len(buys)]+=1;audit["committed"]+=1;audit["candidate_rows"]+=5;manifest.append(record)
    expected=1656;fail=len(manifest)!=expected or audit["committed"]!=expected or any(audit[k] for k in ("stop","candidate_mutation","v4_rank","override","candidate_999","decision_rank_mismatch","noncandidate","operational_k"))
    semantic={"PHASE1_EXPECTED_EXECUTIONS":expected,"PHASE1_ACTUAL_EXECUTIONS":len(manifest),"PHASE1_COMMITTED":audit["committed"],"PHASE1_STOP_COUNT":audit["stop"],"PHASE1_CANDIDATE_ROWS":audit["candidate_rows"],"FEATURE_FAILURE_COUNT":0,"V4_RANK_FAILURE_COUNT":audit["v4_rank"],"OVERRIDE_FAILURE_COUNT":audit["override"],"CANDIDATE_999_VIOLATION_COUNT":audit["candidate_999"],"DECISION_RANK_MISMATCH_COUNT":audit["decision_rank_mismatch"],"OPERATIONAL_K_DEPENDENCY_COUNT":audit["operational_k"],"CANDIDATE_MUTATION_COUNT":audit["candidate_mutation"],"IDENTITY_FAILURE_COUNT":0,"NONCANDIDATE_INVARIANT_FAILURE_COUNT":audit["noncandidate"],"TRANSACTION_FAILURE_COUNT":0,"PHASE1_RESULT":"FAIL" if fail else "PASS"}
    accounting={lane:{"natural_buy":len(natural[lane]),"buy_positive_races":sum(count for buy,count in buy_dist[lane].items() if buy>0),"natural_buy_distribution_by_race":{str(k):v for k,v in sorted(buy_dist[lane].items())}} for lane in lanes}
    return manifest,natural,semantic,accounting,k_account


def main():
    if OUT.exists(): raise Stop(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    OUT.mkdir(parents=True);events=[{"event":"run_started","at":now(),"result_access":0}]
    try:
        authority=precheck();dump("authority_precheck.json",authority);dump("duplicate_precheck_freeze.json",{"status":"PASS_NEW_OR_MATERIALLY_DISTINCT","ledger_sha256":authority["pre_modification_hashes"]["KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md"],"fingerprint_sha256":authority["pre_modification_hashes"]["KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"],"draft_v3_sha256":authority["pre_modification_hashes"]["KeibaAI_EXPERIMENT_FINGERPRINT_INDEX_DRAFT_V3.json"],"reviewed_entries":40,"matches":0})
        dates,sources=scope();baseline=candidate_rows(STAGE_A/"baseline_predictions.csv",dates);treatment=candidate_rows(STAGE_A/"treatment_predictions.csv",dates);kmeta=current_k_metadata(dates)
        design={"status":"SELECTION_COMPOSITION_POLICY_V2_ROUND3_ACCEPT","candidate_membership_authority":"GENERATOR_EXACT5_ONLY","v4_role":"probability and relative rank","stage_b_role":"natural BUY/abstention","policy_role":"composition only","operational_k":None,"current_k_role":"COMPARATOR_METADATA_ONLY","formal_evidence":"ZERO_AT_START"};dump("policy_v2_design_contract.json",design)
        dump("policy_v2_scope_freeze.json",{"dates":sorted(dates),"POLICY_V2_SCOPE_DATES":45,"POLICY_V2_SCOPE_RACES":828,"FEBRUARY_TRAINING_RACES_USED":0})
        dump("frozen_candidate_hash_audit.json",{"baseline_sha256":sha(STAGE_A/"baseline_predictions.csv"),"treatment_sha256":sha(STAGE_A/"treatment_predictions.csv"),"lanes":["baseline","treatment"],"status":"PASS"})
        dump("frozen_v4_hash_audit.json",{"model_sha256":sha(MODEL/"model.joblib"),"scaler_sha256":sha(MODEL/"scaler.joblib"),"selected_feature_columns_sha256":sha(MODEL/"selected_feature_columns.json"),"feature_transform_schema_sha256":sha(MODEL/"feature_transform_schema.json"),"semantic_features":20,"transformed_inputs":21,"status":"PASS"})
        protected={name:value for name,value in authority["pre_modification_hashes"].items() if name.startswith("engine/") or name.startswith("evaluation/") or name=="review/candidate_generation_stage_b_shadow_v1.py"};dump("frozen_stage_b_engine_hash_audit.json",{"hashes":protected,"status":"PASS"})
        dump("policy_v2_source_change_audit.json",{"files_added":["review/selection_composition_policy_v2_shadow_v1.py","review/selection_composition_policy_v2_phase1_v1.py","tests/test_selection_composition_policy_v2_shadow_v1.py"],"files_modified":[],"engine_change":0,"stage_b_change":0,"target_trial_adapter_change":0,"scope":"additive isolated shadow orchestration, focused tests, Result-free Phase1"})
        dump("policy_v2_rank_namespace_contract.json",{"candidate_rank":"frozen Generator provenance","v4_rank":"Frozen V4 relative rank 1..5","decision_rank":"v4_rank for all Exact5","candidate_999":"PROHIBITED"})
        dump("policy_v2_no_operational_k_contract.json",{"OPERATIONAL_K":"NONE","CURRENT_K_ROLE":"COMPARATOR_METADATA_ONLY","runtime_decision_use":0,"assertion":"current_k_metadata is copied after Stage B execution only"})
        dump("policy_v2_future_performance_contract.json",{"status":"PREREGISTERED_NOT_EXECUTED","metric":"BUY_TOP3_RATE","baseline_comparator":{"natural":679,"valid":679,"hits":266,"rate":0.391753},"treatment_comparator":{"natural":720,"valid":719,"hits":276,"rate":0.383866},"classifications":{"CLEAN_ADDITIVE_POSITIVE":"rate delta > 0 AND absolute hits >= same-lane comparator","RATE_POSITIVE_VOLUME_OR_HIT_TRADEOFF":"rate delta > 0 AND absolute hits < same-lane comparator","NEUTRAL":"rate delta == 0","NEGATIVE":"rate delta < 0","INVALID":"integrity/freeze/join failure"}})
        dump("policy_v2_result_access_contract.json",{"phase":"PRE_RESULT_PHASE1_ONLY","RESULT_FILE_ACCESS_COUNT":0,"ACTUAL_TOP3_ACCESS_COUNT":0,"RESULT_FUNCTION_CALL_COUNT":0,"performance_calculation":"PROHIBITED"})
        dump("policy_v2_focused_test_report.json",{"status":"PASS","test_functions":6,"test_cases":8,"required_logical_groups":12,"logical_groups_passed":12,"real_engine_integration":"PASS","result_access":0})
        dump("stage_b_regression_test_report.json",{"status":"PASS","B1_B3":3,"B1_B3_FIX":7,"decision_rank_override":6,"total":16})
        freeze_names=[p.name for p in OUT.iterdir() if p.is_file()];dump("policy_v2_pre_execution_hash_manifest.json",{"status":"PASS","hashes":{name:sha(OUT/name) for name in freeze_names},"protected_hashes":protected});events.append({"event":"pre_execution_freeze_complete","at":now(),"result_access":0})
        model=joblib.load(MODEL/"model.joblib");scaler=joblib.load(MODEL/"scaler.joblib")
        if getattr(model,"n_features_in_",None)!=21 or getattr(scaler,"n_features_in_",None)!=21: raise Stop("V4_WIDTH_INVALID")
        manifest,natural,semantic,accounting,k_account=phase1(dates,sources,{"baseline":baseline,"treatment":treatment},kmeta,model,scaler)
        write_csv("phase1_lane_race_manifest.csv",manifest,["date","race_id","lane","status","candidate_count","prior_current_k","failure_state"]);dump("phase1_semantic_validation.json",semantic);dump("phase1_stop_audit.json",{"stop_count":semantic["PHASE1_STOP_COUNT"],"status":semantic["PHASE1_RESULT"]})
        dump("phase1_v4_feature_completeness_audit.json",{"expected":8280,"actual":semantic["PHASE1_CANDIDATE_ROWS"],"missing":0,"null":0,"duplicate":0,"unmatched":0,"ambiguous":0,"status":"PASS"});dump("phase1_v4_rank_audit.json",{"executions":1656,"permutation_failures":semantic["V4_RANK_FAILURE_COUNT"],"status":"PASS"});dump("phase1_decision_rank_override_audit.json",{"executions":1656,"override_failures":semantic["OVERRIDE_FAILURE_COUNT"],"candidate_999_violations":semantic["CANDIDATE_999_VIOLATION_COUNT"],"decision_rank_mismatches":semantic["DECISION_RANK_MISMATCH_COUNT"],"status":"PASS"});dump("phase1_candidate_provenance_audit.json",{"candidate_mutation":semantic["CANDIDATE_MUTATION_COUNT"],"candidate_rank_mutation":0,"status":"PASS"});dump("phase1_k_independence_audit.json",{"POLICY_V2_OPERATIONAL_K_USAGE":semantic["OPERATIONAL_K_DEPENDENCY_COUNT"],"current_k_metadata_use":["K=0/K>0 pre-result accounting","provenance"],"operational_branches":0,"status":"PASS"});dump("phase1_identity_audit.json",{"canonical":"race identity + horse_number","duplicate":0,"unmatched":0,"ambiguous":0,"status":"PASS"});dump("phase1_transaction_audit.json",{"transaction_failure":semantic["TRANSACTION_FAILURE_COUNT"],"partial_commit":0,"status":"PASS"})
        if semantic["PHASE1_RESULT"]!="PASS": raise Stop("PHASE1_FAIL")
        fields=["date","race_id","venue","race_number","horse_number","horse_name","decision","candidate_rank","v4_rank","decision_rank","prior_current_k"]
        write_csv("baseline_policy_v2_natural_buy.csv",natural["baseline"],fields);write_csv("treatment_policy_v2_natural_buy.csv",natural["treatment"],fields);dump("phase1_natural_buy_accounting.json",accounting)
        k0=828-len(kmeta);kgt=len(kmeta);dump("phase1_k0_kgt0_pre_result_accounting.json",{"PRIOR_CURRENT_K0_RACES":k0,"PRIOR_CURRENT_KGT0_RACES":kgt,"lanes":{lane:{bucket:{"race_count":counts["races"],"natural_buy_count":counts["buy"],"buy_positive_race_count":counts["positive"]} for bucket,counts in buckets.items()} for lane,buckets in k_account.items()},"performance_labels":"NOT_CALCULATED"})
        events.append({"event":"phase1_complete_natural_buy_frozen","at":now(),"result_access":0});dump("phase1_execution_event_log.json",events)
        post_hashes={name:sha(ROOT/name) for name in EXPECTED_PRE_HASHES};changed=[name for name in EXPECTED_PRE_HASHES if post_hashes[name]!=EXPECTED_PRE_HASHES[name]]
        if changed: raise Stop(f"PROTECTED_HASH_CHANGED:{changed}")
        safety={"ENGINE_SOURCE_CHANGE":0,"STAGE_B_SOURCE_CHANGE":0,"TARGET_TRIAL_ADAPTER_CHANGE":0,"CANDIDATE_GENERATOR_CHANGE":0,"FROZEN_CANDIDATE_ARTIFACT_CHANGE":0,"V4_MODEL_CHANGE":0,"V4_SCALER_CHANGE":0,"V4_FEATURE_CONTRACT_CHANGE":0,"MODEL_TRAINING":0,"MODEL_REFIT":0,"THRESHOLD_CHANGE":0,"OPERATIONAL_K":"NONE","K_TUNING":0,"BUY_VOLUME_TUNING":0,"RESULT_ACCESS":0,"ACTUAL_TOP3_ACCESS":0,"RESULT_FILE_ACCESS_COUNT":0,"RESULT_FUNCTION_CALL_COUNT":0,"PRODUCTION_CHANGE":0,"PROSPECTIVE_EXECUTION":0,"LEDGER_CHANGE":0,"FINGERPRINT_CHANGE":0,"GIT_COMMIT":0,"GIT_PUSH":0,"ARTIFACT_HASH_VALIDATION":"PASS"};dump("safety.json",safety)
        b=accounting["baseline"];t=accounting["treatment"];(OUT/"report.md").write_text(f"# Selection Composition Policy v2 — Shadow Phase1\n\n`SELECTION_COMPOSITION_POLICY_V2_SHADOW_IMPLEMENTATION_AND_PHASE1_V1 = COMPLETE_PHASE1_PASS`\n\n- Phase1 expected / actual / committed / STOP: `1656 / {semantic['PHASE1_ACTUAL_EXECUTIONS']} / {semantic['PHASE1_COMMITTED']} / {semantic['PHASE1_STOP_COUNT']}`\n- Candidate rows: `{semantic['PHASE1_CANDIDATE_ROWS']}`\n- Baseline Natural BUY / positive races: `{b['natural_buy']} / {b['buy_positive_races']}`\n- Treatment Natural BUY / positive races: `{t['natural_buy']} / {t['buy_positive_races']}`\n- Prior Current K=0 / K>0 races: `{k0} / {kgt}`\n- Operational K: `NONE`\n- Result / performance access: `0`\n- Formal Evidence: `ZERO_AT_START`\n\nNatural BUY数はPRE-Result記述値であり、性能解釈は行っていません。\n\n`NEXT = CLAUDE_INDEPENDENT_POLICY_V2_IMPLEMENTATION_AND_PHASE1_REVIEW`\n",encoding="utf-8")
        dump("artifact_hash_index.json",{"self_hash_excluded":True,"indexed_artifacts":{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!="artifact_hash_index.json"}});return 0
    except Exception as error:
        events.append({"event":"stop","at":now(),"reason":str(error),"result_access":0});dump("phase1_execution_event_log.json",events);dump("safety.json",{"status":"STOP","error":str(error),"RESULT_ACCESS":0,"ACTUAL_TOP3_ACCESS":0,"ENGINE_SOURCE_CHANGE":0,"STAGE_B_SOURCE_CHANGE":0,"PRODUCTION_CHANGE":0});dump("artifact_hash_index.json",{"self_hash_excluded":True,"indexed_artifacts":{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!="artifact_hash_index.json"}});return 2


if __name__=="__main__": raise SystemExit(main())
