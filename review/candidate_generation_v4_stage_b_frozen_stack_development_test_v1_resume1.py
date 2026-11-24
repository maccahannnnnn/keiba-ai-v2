"""Frozen development-only Candidate → V4 → Stage B stack runner.

This runner deliberately consumes only the already frozen 45-date Stage-A
packets and retry5 Current BUY reference.  It is not connected to production.
"""
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import numpy as np

from review.candidate_generation_stage_b_shadow_v1 import CandidateGenerationStageBShadow, EXACT5_TIE_BREAK_ID
from review.candidate_generation_stage_b_fast_route_b4_buy_performance_v1 import (
    STAGE_A, FEBRUARY, PROTECTED, JAPANESE_VENUE, parse_race_id, source_map,
    full_context, candidate_packet, sha, now, result_rows,
)
from review.candidate_generation_training_dataset_readiness_v1 import outcome

OUT = ROOT / "reports/candidate_generation_v4_stage_b_frozen_stack_development_test_v1_resume1_retry2"
RETRY5 = ROOT / "reports/candidate_generation_stage_b_fast_route_b4_buy_performance_v1_retry5"
MODEL = ROOT / "reports/ml_v4_buy_selection_model_v4"
FOLD = STAGE_A / "expanded_stage_a_fold_manifest.json"
SEMANTIC = ["Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle", "shadow_ai_rank", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count", "consensus_negative_count", "risk_count", "conflict_count", "race_state"]
TRANSFORMED = [*SEMANTIC[:-1], "is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"]
GATES = set(SEMANTIC[11:15])


class Stop(RuntimeError):
    pass


def load(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def dump(name: str, value: object): (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
def write_csv(name: str, rows: list[dict], fields: list[str]):
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
def digest(value: object) -> str: return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_index(root: Path) -> dict:
    index_path = root / "artifact_hash_index.json"
    if not index_path.is_file(): index_path = root / "artifact_hashes.json"
    entries = load(index_path).get("indexed_artifacts", {})
    bad = [name for name, value in entries.items() if not (root / name).is_file() or sha(root / name) != (value.get("sha256") if isinstance(value, dict) else value)]
    return {"root": str(root.relative_to(ROOT)), "index": index_path.name, "indexed_count": len(entries), "mismatches": bad, "status": "PASS" if not bad else "FAIL"}


def scope() -> tuple[set[str], dict[str, list[Path]]]:
    fold = load(FOLD); dates = {d for x in fold["folds"] for d in x["eval_dates"]}; sources = source_map()
    races = sum(len(sources[d]) for d in dates)
    if len(dates) != 45 or races != 828 or dates & FEBRUARY or dates & PROTECTED: raise Stop(f"SCOPE_INVALID:{len(dates)}:{races}")
    return dates, sources


def selected(path: Path, dates: set[str]) -> dict[tuple[str, str], list[dict]]:
    groups = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["date"] in dates and r["selected"] == "True":
                groups[(r["date"], r["race_id"])].append({"horse_number": int(r["horse_number"]), "horse_name": r["horse_name"], "candidate_rank": int(r["candidate_rank"]), "candidate_probability": float(r["probability"]), "current_rank": int(r["current_rank"]), "shadow_ai_rank": float(r["shadow_ai_rank"])})
    if len(groups) != 828 or any(len(v) != 5 or sorted(x["candidate_rank"] for x in v) != [1,2,3,4,5] for v in groups.values()): raise Stop("CANDIDATE_EXACT5_INVALID")
    return groups


def current_k(dates: set[str]) -> tuple[dict[tuple[str, str], int], list[dict]]:
    rows=[]; counts=Counter()
    with (RETRY5 / "current_frozen_buy.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["date"] in dates: rows.append(r); counts[(r["date"], r["race_id"])] += 1
    if len(rows) != 623 or any(v > 5 for v in counts.values()): raise Stop(f"CURRENT_K_REFERENCE_INVALID:{len(rows)}")
    return dict(counts), rows


def number(value, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)): raise Stop(f"FEATURE_INVALID:{context}")
    return float(value)
def gate(value, context: str) -> float:
    if value is True: return 1.0
    if value is False: return 0.0
    raise Stop(f"FEATURE_BOOLEAN_INVALID:{context}")


def vector(row: dict, state: str, context: str) -> list[float]:
    snapshot = row.get("evaluator_score_snapshot")
    if not isinstance(snapshot, dict): raise Stop(f"EVALUATOR_SNAPSHOT_INVALID:{context}")
    values=[]
    for field in SEMANTIC[:-1]:
        value = snapshot.get(field) if field in SEMANTIC[:7] else row.get(field)
        values.append(gate(value, f"{context}:{field}") if field in GATES else number(value, f"{context}:{field}"))
    values += [float(state == "PLAY_UNCONVERGED_4PLUS"), float(state == "SKIP")]
    if len(values) != 21: raise Stop("FEATURE_WIDTH_INVALID")
    return values


def authority_precheck() -> dict:
    for root in (RETRY5, MODEL):
        check = verify_index(root)
        if check["status"] != "PASS": raise Stop(f"HASH_INDEX_FAIL:{root.name}")
    transform = load(MODEL / "feature_transform_schema.json")
    if transform.get("transformed_model_input_columns") != TRANSFORMED or transform.get("transformed_input_count") != 21: raise Stop("V4_FEATURE_CONTRACT_INVALID")
    source = ROOT / "review/candidate_generation_stage_b_shadow_v1.py"
    text = source.read_text(encoding="utf-8")
    if "decision_rank_override=None" not in text or "STOP_OVERRIDE_SENTINEL_BUY_INVARIANT" not in text: raise Stop("OVERRIDE_INTERFACE_UNAVAILABLE")
    return {"AUTHORITY_PRECHECK":"PASS", "scope":"45 dates / 828 races", "retry5_hash_index":verify_index(RETRY5), "model_hash_index":verify_index(MODEL), "candidate_hashes":{"baseline_predictions.csv":sha(STAGE_A / "baseline_predictions.csv"), "treatment_predictions.csv":sha(STAGE_A / "treatment_predictions.csv")}, "v4":{"model_sha256":sha(MODEL / "model.joblib"), "scaler_sha256":sha(MODEL / "scaler.joblib"), "feature_contract_sha256":sha(MODEL / "feature_transform_schema.json")}, "stage_b_source_sha256":sha(source), "override_interface":"AVAILABLE"}


def phase1(dates, sources, lanes, k_by_race, model, scaler):
    stage=CandidateGenerationStageBShadow(); manifest=[]; natural={"baseline":[],"treatment":[]}; infer=[]; ranks=[]; overrides=[]
    failures=Counter(); feature_rows=0; noncurrent={"baseline": Counter(), "treatment": Counter()}
    for date in sorted(dates):
        for path in sorted(sources[date]):
            rows, context, payload = full_context(path); race_id=context["race_id"]; key=(date,race_id)
            state=payload.get("buy_gate_trace",{}).get("race",{}).get("shadow_race_state")
            if state not in {"PLAY_CONVERGED","PLAY_UNCONVERGED_4PLUS","SKIP"}: raise Stop(f"RACE_STATE_INVALID:{race_id}")
            row_by_no={int(x["horse_number"]):x for x in rows}; K=k_by_race.get(key,0)
            if not isinstance(K,int) or not 0<=K<=5: raise Stop(f"K_INVALID:{key}:{K}")
            for lane, candidates in lanes.items():
                if key not in candidates: raise Stop(f"CANDIDATE_MISSING:{lane}:{key}")
                exact5=candidates[key]; nums=[x["horse_number"] for x in exact5]
                if len(set(nums)) != 5 or any(n not in row_by_no for n in nums): raise Stop(f"CANDIDATE_IDENTITY_INVALID:{lane}:{race_id}")
                matrix=np.asarray([vector(row_by_no[x["horse_number"]], state, f"{lane}:{race_id}:{x['horse_number']}") for x in exact5], dtype=float)
                if matrix.shape != (5,21) or not np.isfinite(matrix).all(): raise Stop(f"FEATURE_COMPLETENESS_FAIL:{lane}:{race_id}")
                feature_rows += 5
                prob=model.predict_proba(scaler.transform(matrix))[:,1]
                ordered=sorted(zip(exact5,prob), key=lambda z:(-float(z[1]), float(z[0]["shadow_ai_rank"]), int(z[0]["horse_number"])))
                v4={int(item["horse_number"]): i+1 for i,(item,_) in enumerate(ordered)}
                if set(v4.values()) != {1,2,3,4,5}: raise Stop(f"V4_RANK_INVALID:{lane}:{race_id}")
                selected_numbers={n for n,r in v4.items() if r<=K}; override={n:(r if n in selected_numbers else 999) for n,r in v4.items()}
                if len(selected_numbers)!=K or set(override)!=set(nums): raise Stop(f"SAME_VOLUME_INVALID:{lane}:{race_id}")
                snap=stage.race_context_snapshot(rows,context); packet=candidate_packet(lane,date,race_id,exact5,snap["snapshot_hash"])
                before=deepcopy(exact5); result=stage.run(packet,rows,context,decision_rank_override=override)
                record={"date":date,"race_id":race_id,"lane":lane,"status":result.get("status"),"candidate_count":5,"K":K,"selected_count":len(selected_numbers),"failure_state":result.get("failure_state","")}
                if result.get("status")!="COMMITTED":
                    failures["stop"]+=1; manifest.append(record); continue
                output={int(x["horse_number"]):x for x in result["horses"]}
                problems=[]
                if before != exact5: problems.append("candidate_mutation")
                if any(output[n].get("decision_rank") != override[n] for n in nums): problems.append("override_reflection")
                if any(output[n].get("decision") == "BUY" for n in nums if override[n] == 999): problems.append("sentinel_buy")
                if any(x.get("decision")=="BUY" for n,x in output.items() if n not in nums): problems.append("true_noncandidate_buy")
                if problems:
                    for p in problems: failures[p]+=1
                    record["failure_state"]="INVARIANT:"+",".join(problems)
                else:
                    failures["committed"]+=1
                    for n,x in output.items():
                        if x.get("decision")=="BUY": natural[lane].append({"date":date,"race_id":race_id,"venue":context["venue"],"race_number":context["race_number"],"horse_number":n,"horse_name":x["horse_name"],"decision":"BUY","candidate_rank":x.get("candidate_rank"),"v4_rank":v4.get(n),"decision_rank":x.get("decision_rank")})
                for item,p in zip(exact5,prob): infer.append({"date":date,"race_id":race_id,"lane":lane,"horse_number":item["horse_number"],"probability":float(p)})
                ranks += [{"date":date,"race_id":race_id,"lane":lane,"horse_number":n,"v4_rank":r} for n,r in sorted(v4.items())]
                overrides += [{"date":date,"race_id":race_id,"lane":lane,"horse_number":n,"v4_rank":v4[n],"decision_rank_override":override[n],"v4_selected":n in selected_numbers} for n in sorted(v4)]
                noncurrent[lane]["total"] += 5; noncurrent[lane]["outside"] += sum(int(x["current_rank"])>5 for x in exact5)
                manifest.append(record)
    expected=1656; actual=len(manifest); fail=actual!=expected or failures["committed"]!=expected or any(failures[k] for k in ("stop","candidate_mutation","override_reflection","sentinel_buy","true_noncandidate_buy"))
    semantic={"PHASE1_EXPECTED_STACK_EXECUTIONS":expected,"PHASE1_ACTUAL_STACK_EXECUTIONS":actual,"PHASE1_COMMITTED":failures["committed"],"PHASE1_STOP_COUNT":failures["stop"],"V4_FEATURE_FAILURE_COUNT":0,"V4_RANK_FAILURE_COUNT":0,"SAME_VOLUME_K_FAILURE_COUNT":0,"V4_SELECTED_COUNT_MISMATCH":0,"DECISION_RANK_OVERRIDE_FAILURE_COUNT":failures["override_reflection"],"CANDIDATE_MEMBERSHIP_MUTATION_COUNT":failures["candidate_mutation"],"IDENTITY_FAILURE_COUNT":0,"SENTINEL_BUY_VIOLATION_COUNT":failures["sentinel_buy"],"TRANSACTION_FAILURE_COUNT":0,"TRUE_NONCANDIDATE_BUY_VIOLATION_COUNT":failures["true_noncandidate_buy"],"feature_vectors":feature_rows,"PHASE1_RESULT":"FAIL" if fail else "PASS"}
    return manifest,natural,infer,ranks,overrides,semantic,{lane:{"outside_current_top5_candidate_count":noncurrent[lane]["outside"],"total_candidate_count":noncurrent[lane]["total"],"rate":noncurrent[lane]["outside"]/noncurrent[lane]["total"] if noncurrent[lane]["total"] else None} for lane in ("baseline","treatment")}


def phase2(dates, current, natural):
    lanes={"current":current,"baseline_candidate_stage_b":None,"baseline_v4_stage_b":natural["baseline"],"treatment_candidate_stage_b":None,"treatment_v4_stage_b":natural["treatment"]}
    # Candidate-only values are the retry5 frozen authority, never recomputed.
    frozen=load(RETRY5 / "phase2_lane_performance.json"); lanes["baseline_candidate_stage_b"]=frozen["baseline"]; lanes["treatment_candidate_stage_b"]=frozen["treatment"]
    enriched={}; join={}
    for lane, buys in (("current",current),("baseline_v4_stage_b",natural["baseline"]),("treatment_v4_stage_b",natural["treatment"])):
        seen=Counter((x["date"],x["race_id"],int(x["horse_number"])) for x in buys); rows=[]; missing=0
        for x in buys:
            _,vk,rn=parse_race_id(x["race_id"]); result=result_rows(x["date"]).get((JAPANESE_VENUE[vk],rn))
            if result is None: missing+=1; continue
            valid,finish,top3=outcome(result,int(x["horse_number"])); rows.append({**x,"valid_result":bool(valid),"actual_finish":finish,"actual_top3":bool(top3) if valid else None})
        join[lane]={"duplicate":sum(v>1 for v in seen.values()),"unmatched":missing,"ambiguous":0,"status":"PASS" if not missing and not any(v>1 for v in seen.values()) else "FAIL"}
        if join[lane]["status"]!="PASS": raise Stop(f"RESULT_JOIN_FAIL:{lane}")
        enriched[lane]=rows
    perf=dict((k,v) for k,v in lanes.items() if isinstance(v,dict))
    for lane,rows in enriched.items():
        valid=[x for x in rows if x["valid_result"]]; hits=sum(x["actual_top3"] for x in valid)
        perf[lane]={"natural_buy":len(rows),"valid_buy":len(valid),"invalid_buy":len(rows)-len(valid),"top3_hits":hits,"buy_top3_rate":hits/len(valid) if valid else None,"natural_buy_races":len({(x["date"],x["race_id"]) for x in rows}),"valid_buy_races":len({(x["date"],x["race_id"]) for x in valid})}
    comparisons=[]
    for base,stack,label in (("baseline_candidate_stage_b","baseline_v4_stage_b","BASELINE"),("treatment_candidate_stage_b","treatment_v4_stage_b","TREATMENT")):
        a,b=perf[base],perf[stack]; delta=None if a["buy_top3_rate"] is None or b["buy_top3_rate"] is None else (b["buy_top3_rate"]-a["buy_top3_rate"])*100
        comparisons.append({"lane":label,"valid_buy_delta":b["valid_buy"]-a["valid_buy"],"top3_hit_delta":b["top3_hits"]-a["top3_hits"],"buy_top3_rate_delta_pt":delta,"incremental_signal":"UNDEFINED" if delta is None else "POSITIVE" if delta>0 else "NEUTRAL" if delta==0 else "NEGATIVE"})
    return enriched,join,perf,comparisons


def main():
    if OUT.exists(): raise Stop(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    OUT.mkdir(parents=True); events=[{"event":"run_started","at":now(),"result_access":0}]
    try:
        authority=authority_precheck(); dump("authority_precheck.json",authority)
        dates,sources=scope(); baseline=selected(STAGE_A/"baseline_predictions.csv",dates); treatment=selected(STAGE_A/"treatment_predictions.csv",dates); ks,current=current_k(dates)
        scope_freeze={"execution_dates":sorted(dates),"execution_date_count":45,"execution_race_count":828,"february_training_races":160,"february_execution":0,"phase1_expected":1656}; dump("stack_scope_freeze.json",scope_freeze)
        dump("frozen_candidate_hash_audit.json",authority["candidate_hashes"]); dump("frozen_v4_hash_audit.json",authority["v4"])
        dump("stage_b_override_interface_audit.json",{"status":"PASS","source_sha256":authority["stage_b_source_sha256"],"interface":"keyword-only decision_rank_override","sentinel_buy_invariant":"PASS_AVAILABLE"})
        dump("v4_feature_contract.json",{"semantic_features":SEMANTIC,"transformed_features":TRANSFORMED,"current_dependent_features":["relative_advantage_pass","absolute_quality_pass","race_state"],"recalculation":"PROHIBITED","status":"PASS"})
        dump("stack_rank_namespace_contract.json",{"candidate_rank":"frozen generator 1..5 immutable","v4_rank":"probability DESC, shadow_ai_rank ASC, horse_number ASC","decision_rank":"selected=v4_rank; nonselected Candidate=999","true_noncandidate":999})
        dump("same_volume_k_contract.json",{"K_source":"retry5 current_frozen_buy.csv","rule":"V4 selection layer only","selected_count_equals_K":True,"final_stage_b_buy_volume":"NATURAL_UNFORCED","FINAL_BUY_SAME_VOLUME_FORCING":0})
        dump("stack_performance_contract.json",{"metric":"BUY_TOP3_RATE","valid":"BUY and valid_result","hit":"BUY and valid_result and actual_top3","invalid":"natural count only; excluded denominator"}); dump("stack_phase_gate_contract.json",{"phase1_required":1656,"phase2_only_after_phase1_pass":True,"partial_exclusion":False})
        hashes={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}; dump("frozen_stack_pre_execution_hash_manifest.json",{"PRE_EXECUTION_FREEZE_COMPLETE":"YES","hashes":hashes})
        events.append({"event":"pre_execution_freeze_complete","at":now(),"result_access":0})
        model=joblib.load(MODEL/"model.joblib"); scaler=joblib.load(MODEL/"scaler.joblib")
        if getattr(model,"n_features_in_",None)!=21 or getattr(scaler,"n_features_in_",None)!=21: raise Stop("MODEL_WIDTH_INVALID")
        manifest,natural,infer,ranks,overrides,semantic,noncurrent=phase1(dates,sources,{"baseline":baseline,"treatment":treatment},ks,model,scaler)
        write_csv("phase1_stack_lane_race_manifest.csv",manifest,["date","race_id","lane","status","candidate_count","K","selected_count","failure_state"])
        dump("phase1_v4_inference_audit.json",{"FROZEN_V4_INFERENCE":"YES","model_training":0,"model_refit":0,"scaler_refit":0,"inference_rows":len(infer),"status":"PASS"}); dump("phase1_v4_rank_audit.json",{"rows":len(ranks),"permutation_failures":0,"tie_break":["probability DESC","shadow_ai_rank ASC","horse_number ASC"],"status":"PASS"}); dump("phase1_same_volume_k_audit.json",{"races":828,"lanes":2,"K_total":sum(ks.values()),"selected_count_mismatch":0,"status":"PASS"}); dump("phase1_decision_rank_override_audit.json",{"rows":len(overrides),"override_failure_count":semantic["DECISION_RANK_OVERRIDE_FAILURE_COUNT"],"status":"PASS" if not semantic["DECISION_RANK_OVERRIDE_FAILURE_COUNT"] else "FAIL"}); dump("phase1_identity_audit.json",{"canonical_identity":"race_id + horse_number","duplicate":0,"unmatched":0,"ambiguous":0,"status":"PASS"}); dump("phase1_semantic_validation.json",semantic); dump("phase1_stop_audit.json",{"stop_count":semantic["PHASE1_STOP_COUNT"],"status":semantic["PHASE1_RESULT"]}); dump("v4_feature_completeness_audit.json",{"lanes":2,"races":828,"expected_candidate_rows":8280,"verified_candidate_rows":semantic["feature_vectors"],"missing":0,"null":0,"duplicate_identity":0,"unmatched_identity":0,"ambiguous_identity":0,"status":"PASS"})
        if semantic["PHASE1_RESULT"]!="PASS": raise Stop("STOP_DURING_PHASE1")
        write_csv("baseline_v4_stage_b_natural_buy.csv",natural["baseline"],["date","race_id","venue","race_number","horse_number","horse_name","decision","candidate_rank","v4_rank","decision_rank"]); write_csv("treatment_v4_stage_b_natural_buy.csv",natural["treatment"],["date","race_id","venue","race_number","horse_number","horse_name","decision","candidate_rank","v4_rank","decision_rank"]); dump("non_current_top5_candidate_accounting.json",noncurrent)
        events.append({"event":"natural_buy_frozen","at":now(),"result_access":0}); events.append({"event":"first_result_access","at":now(),"result_access":1})
        enriched,join,perf,comparisons=phase2(dates,current,natural); dump("phase2_result_join_audit.json",join); dump("phase2_stack_performance.json",perf); dump("phase2_incremental_comparison.json",comparisons)
        events.append({"event":"phase2_complete","at":now(),"result_access":1}); dump("execution_event_log.json",events)
        safety={"ENGINE_SOURCE_CHANGE":0,"STAGE_B_SOURCE_CHANGE":0,"TARGET_TRIAL_ADAPTER_CHANGE":0,"CANDIDATE_GENERATOR_CHANGE":0,"V4_MODEL_CHANGE":0,"V4_SCALER_CHANGE":0,"MODEL_TRAINING":0,"THRESHOLD_CHANGE":0,"BUY_VOLUME_TUNING":0,"FINAL_BUY_SAME_VOLUME_FORCING":0,"PRODUCTION_CHANGE":0,"PROSPECTIVE_EXECUTION":0,"UNTOUCHED_HOLDOUT_ACCESS":0,"FUTURE_RESULT_ACCESS":0,"LEDGER_CHANGE":0,"FINGERPRINT_CHANGE":0,"WORK_RECORD_CHANGE":0,"GIT_COMMIT":0,"GIT_PUSH":0,"FIRST_RESULT_ACCESS_AFTER_STACK_FREEZE":"YES","FIRST_RESULT_ACCESS_AFTER_PHASE1_PASS":"YES","ARTIFACT_HASH_VALIDATION":"PASS"}; dump("safety.json",safety)
        def rate(value): return "undefined" if value is None else f"{value:.4%}"
        table="\n".join(f"| {k} | {v['natural_buy']} | {v['valid_buy']} | {v['invalid_buy']} | {v['top3_hits']} | {rate(v['buy_top3_rate'])} |" for k,v in perf.items())
        comp="\n".join(f"| {x['lane']} | {x['valid_buy_delta']} | {x['top3_hit_delta']} | {x['buy_top3_rate_delta_pt']:.6f} | {x['incremental_signal']} |" for x in comparisons)
        (OUT/"report.md").write_text("# Candidate Generation → Frozen V4 → Stage B\n\n`CANDIDATE_GENERATION_V4_STAGE_B_FROZEN_STACK_DEVELOPMENT_TEST_V1_RESUME1 = COMPLETE`\n\n## Phase 1\n\n- Expected / actual / committed: `1656 / %d / %d`\n- Result access began only after semantic execution and Natural BUY freeze.\n\n## Performance\n\n| Lane | Natural | Valid | Invalid | Top3 Hits | BUY_TOP3_RATE |\n|---|---:|---:|---:|---:|---:|\n%s\n\n| Stack | Valid delta | Hit delta | Rate delta (pt) | Signal |\n|---|---:|---:|---:|---|\n%s\n\n`GENERATOR_SELECTION = UNRESOLVED`  \n`FINAL_STACK_SELECTION = UNRESOLVED`  \n`PRODUCTION_GO = NO`  \n`NEXT = CLAUDE_INDEPENDENT_FROZEN_STACK_RESUME1_RESULT_REVIEW`\n" % (semantic["PHASE1_ACTUAL_STACK_EXECUTIONS"],semantic["PHASE1_COMMITTED"],table,comp),encoding="utf-8")
        dump("artifact_hash_index.json",{"self_hash_excluded":True,"indexed_artifacts":{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!="artifact_hash_index.json"}})
        return 0
    except Exception as error:
        events.append({"event":"stop","at":now(),"reason":str(error)}); dump("execution_event_log.json",events); dump("safety.json",{"status":"STOP","error":str(error),"ENGINE_SOURCE_CHANGE":0,"STAGE_B_SOURCE_CHANGE":0,"PRODUCTION_CHANGE":0,"RESULT_ACCESS_BEFORE_PHASE1":0}); dump("artifact_hash_index.json",{"self_hash_excluded":True,"indexed_artifacts":{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!="artifact_hash_index.json"}}); return 2

if __name__ == "__main__": raise SystemExit(main())
