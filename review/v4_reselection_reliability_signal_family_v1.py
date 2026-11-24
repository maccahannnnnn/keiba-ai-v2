"""Frozen Family: V4 same-volume reselection reliability diagnostic only."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from scipy.stats import fisher_exact, mannwhitneyu, spearmanr

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "v4_reselection_reliability_signal_family_v1"
PRE = ROOT / "reports" / "v4_model_v4_february_historical_holdout" / "formal_pre"
POST = ROOT / "reports" / "v4_model_v4_february_historical_holdout" / "formal_post"
V3 = ROOT / "reports" / "v4_model_v3_prospective_protocol_v1"
V4 = ROOT / "reports" / "v4_model_v4_formal_prospective"
CF = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"


class Stop(RuntimeError): pass

def sha(p: Path) -> str: return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p: Path) -> dict[str, Any]:
    v = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(v, dict): raise Stop(f"JSON_OBJECT_REQUIRED:{p}")
    return v
def dump(name: str, v: Any) -> None:
    (OUT / name).write_text(json.dumps(v, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
def verify(root: Path) -> int:
    d = load(root / "artifact_hashes.json").get("indexed_artifacts")
    if not isinstance(d, dict): raise Stop(f"INDEX_INVALID:{root}")
    for n,h in d.items():
        if not isinstance(h,str) or not (root/n).is_file() or sha(root/n) != h: raise Stop(f"INDEX_MISMATCH:{root}:{n}")
    return len(d)
def q(x: list[float], p: float) -> float | None:
    return float(__import__("numpy").percentile(x,p)) if x else None
def desc(x: list[float]) -> dict[str, Any]:
    return {"n":len(x),"median":q(x,50),"iqr":[q(x,25),q(x,75)],"mean_descriptive_only":statistics.mean(x) if x else None}
def rr(pos: list[float], non: list[float]) -> float | None:
    if not pos or not non: return None
    wins=sum(a>b for a in pos for b in non); losses=sum(a<b for a in pos for b in non)
    return (wins-losses)/(len(pos)*len(non))
def cont_test(pos: list[float], non: list[float], expected: str) -> dict[str, Any]:
    out={"positive_benefit":desc(pos),"non_positive_benefit":desc(non),"expected_direction":expected}
    if not pos or not non: return {**out,"computable":False,"direction":"NOT_EVALUABLE"}
    u=mannwhitneyu(pos,non,alternative="two-sided")
    r=rr(pos,non); sign=(r>0 if expected=="POSITIVE" else r<0)
    return {**out,"computable":True,"mann_whitney_u":float(u.statistic),"two_sided_p_diagnostic_only":float(u.pvalue),"r_rb_frozen_orientation":r,"direction":"EXPECTED_STRICT_SIGN" if sign else "ZERO_OR_OPPOSITE"}

def duplicate() -> dict[str,Any]:
    rows=[
      {"name":"race_convergence_quality_v1","path":"reports/race_convergence_quality_v1/","variables":["race state","candidate count"],"overlap":"PARTIAL","reason":"No V4 Top5 probability A/B/C or frozen 62-race reselection outcome."},
      {"name":"RACE_TOP_GAP / BUY_NEXT_GAP / adjusted_score_gap_to_top","path":"reports/v4_model_v4_train_ablation_v1/; review/v4_feature_expansion_relative_gap_position_v1.py","variables":["adjusted-score-space gaps"],"overlap":"PARTIAL","reason":"Explicitly different score space; not rerun."},
      {"name":"Family C Stage 1 / 1.5","path":"reports/v4_family_c_stage1_marginality_v1/; reports/v4_family_c_stage1_5_relative_advantage_v1/","variables":["gate margins","relative advantage"],"overlap":"PARTIAL","reason":"No frozen V4 reselection probability boundary/dispersion/exclusion A/B/C."},
      {"name":"replacement depth / buy volume diagnostics","path":"reports/v4_model_v4_february_historical_holdout/formal_pre/","variables":["replacement_depth","buy_volume"],"overlap":"PARTIAL","reason":"Used only as preregistered context variables here."},
      {"name":"Exact A/B/C reliability family","path":None,"variables":["V4_SELECTION_BOUNDARY_GAP","N_eff","V4_TOP5_EXCLUSION_FLAG"],"overlap":"NONE","reason":"Not found."}]
    return {"status":"PASS_NO_EXACT_DUPLICATE","exact_duplicate_count":0,"inspected":["ANALYSIS_HISTORY/DECISION_LOG/DATA_CATALOG/work governance record (not found)","Candidate Registry","prior Family C","BUY Gate Trace","Relative Gap","race convergence"],"records":rows}

def construct_phase_a() -> tuple[list[dict[str,Any]],dict[str,Any],dict[str,Any]]:
    eligible=load(PRE/"formal_eligible_population.json")["eligible_races"]
    records=load(PRE/"v4_prediction.json")["inference_records"]
    probs={r["race_id"]:r for r in records}
    if len(eligible)!=81 or len(probs)!=81: raise Stop("FROZEN_81_RACE_UNIVERSE_MISMATCH")
    rows=[]; all_top5=0
    for item in eligible:
        rec=probs.get(item["race_id"])
        if not isinstance(rec,dict): raise Stop(f"V4_TOP5_RECORD_MISSING:{item['race_id']}")
        top=rec.get("top5_probabilities")
        if not isinstance(top,list) or len(top)!=5: raise Stop(f"V4_TOP5_LENGTH_INVALID:{item['race_id']}")
        all_top5+=1
        if item["replacement_depth"] < 1: continue
        k=int(item["current_buy_count"]); current=item["current_selected_horses"]; v4=item["v4_selected_horses"]
        if k not in (1,2,3) or len(current)!=k or len(v4)!=k or k+1>5: raise Stop(f"FROZEN_RESELECTION_VOLUME_INVALID:{item['race_id']}")
        nums=[]; ps=[]
        for entry in top:
            n=entry.get("horse_number"); p=entry.get("predicted_top3_probability")
            if not isinstance(n,int) or isinstance(p,bool) or not isinstance(p,(int,float)) or not math.isfinite(float(p)): raise Stop(f"V4_TOP5_VALUE_INVALID:{item['race_id']}")
            nums.append(n); ps.append(float(p))
        if len(set(nums))!=5 or sum(ps)<=0: raise Stop(f"V4_TOP5_IDENTITY_OR_SUM_INVALID:{item['race_id']}")
        a=ps[k-1]-ps[k]; total=sum(ps); qs=[p/total for p in ps]; b=math.exp(-sum(z*math.log(z) for z in qs if z>0))
        current_nums={int(x["horse_number"]) for x in current}; c=int(any(n not in set(nums) for n in current_nums))
        rows.append({"date":item["date"],"race_id":item["race_id"],"venue":item["venue"],"race_number":item["race_number"],"race_state":item["race_state"],"buy_volume":k,"replacement_depth":int(item["replacement_depth"]),"p_rank_k":ps[k-1],"signal_a_boundary_gap":a,"signal_b_n_eff":b,"signal_c_top5_exclusion_flag":c,"v4_top5_horse_numbers":"|".join(map(str,nums)),"current_horse_numbers":"|".join(map(str,sorted(current_nums)))})
    if len(rows)!=62: raise Stop(f"FROZEN_PRIMARY_POPULATION_MISMATCH:{len(rows)}")
    if Counter(r["date"] for r in rows)!={"20260201":8,"20260207":9,"20260210":4,"20260214":11,"20260215":7,"20260221":10,"20260222":6,"20260228":7}: raise Stop("FROZEN_INFORMATIVE_DATE_COUNTS_MISMATCH")
    flag_k={str(k):sum(r["signal_c_top5_exclusion_flag"] for r in rows if r["buy_volume"]==k) for k in (1,2,3)}
    flag_d={str(d):sum(r["signal_c_top5_exclusion_flag"] for r in rows if r["replacement_depth"]==d) for d in (1,2)}
    if flag_k!={"1":13,"2":6,"3":5} or flag_d!={"1":20,"2":4}: raise Stop("FROZEN_EXCLUSION_FLAG_PREVALENCE_MISMATCH")
    population={"formal_eligible_races":81,"primary_replacement_active_races":62,"expected_outcome_composition":{"v4_superior":20,"equal":37,"current_superior":5,"positive_benefit":20,"non_positive_benefit":42},"by_replacement_depth":dict(Counter(r["replacement_depth"] for r in rows)),"by_buy_volume":dict(Counter(r["buy_volume"] for r in rows))}
    integrity={"status":"PASS","all_81_top5_length_5":all_top5,"primary_rows":len(rows),"finite_probability_rows":len(rows),"structural_flag_prevalence":{"overall":sum(r["signal_c_top5_exclusion_flag"] for r in rows),"by_buy_volume":flag_k,"by_replacement_depth":flag_d},"rejected_quantities":{"V4_EXPECTED_RESELECTION_GAIN":"REJECTED_NOT_EVALUABLE: structural missing Current probability for 24/62 races","SELECTED_PROBABILITY_SHARE":"PREEMPTIVELY_REJECTED_AS_REDUNDANT"}}
    return rows,population,integrity

def phase_a_structural(rows:list[dict[str,Any]]) -> dict[str,Any]:
    nums=["signal_a_boundary_gap","signal_b_n_eff","p_rank_k"]
    corr={}
    for i,x in enumerate(nums):
      for y in nums[i+1:]: corr[f"{x}__{y}"]=float(spearmanr([r[x] for r in rows],[r[y] for r in rows]).statistic)
    return {"pairwise_spearman":corr,"high_redundancy_abs_rho_gt_0_90":[k for k,v in corr.items() if abs(v)>.90],"deterministic_affine_dependence":"No exact/affine dependence claimed; recorded result-blind only.","by_buy_volume":{str(k):{s:desc([float(r[s]) for r in rows if r["buy_volume"]==k]) for s in nums} for k in (1,2,3)},"by_replacement_depth":{str(d):{s:desc([float(r[s]) for r in rows if r["replacement_depth"]==d]) for s in nums} for d in (1,2)},"exclusion_flag_by_buy_volume":{str(k):dict(Counter(r["signal_c_top5_exclusion_flag"] for r in rows if r["buy_volume"]==k)) for k in (1,2,3)},"exclusion_flag_by_replacement_depth":{str(d):dict(Counter(r["signal_c_top5_exclusion_flag"] for r in rows if r["replacement_depth"]==d)) for d in (1,2)}}

def write_phase_a(rows:list[dict[str,Any]], structural:dict[str,Any]) -> str:
    fields=list(rows[0]);
    with (OUT/"phase_a_pre_only_dataset.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    dump("phase_a_structural_checks.json",structural)
    hashes={n:sha(OUT/n) for n in ("phase_a_pre_only_dataset.csv","phase_a_structural_checks.json")}
    dump("phase_a_artifact_hashes.json",{"state":"V4_RESELECTION_RELIABILITY_PRE_DATA = FROZEN_BEFORE_RESULT_JOIN","indexed_artifacts":hashes,"self_hash_excluded":True})
    return sha(OUT/"phase_a_pre_only_dataset.csv")

def result_join(rows:list[dict[str,Any]], phase_hash:str)->tuple[list[dict[str,Any]],dict[str,Any]]:
    if sha(OUT/"phase_a_pre_only_dataset.csv")!=phase_hash: raise Stop("PHASE_A_SHA_CHANGED_BEFORE_RESULT_JOIN")
    join=load(POST/"selection_result_join.json"); current=join["current_selected"]; v4=join["v4_selected"]
    by_race=lambda xs:{r: [x for x in xs if x["race_id"]==r] for r in {x["race_id"] for x in xs}}
    cr,vr=by_race(current),by_race(v4); out=[]
    for row in rows:
      c=cr.get(row["race_id"],[]); v=vr.get(row["race_id"],[])
      if len(c)!=row["buy_volume"] or len(v)!=row["buy_volume"] or any(not x.get("valid_result") for x in c+v): raise Stop(f"FROZEN_RESULT_RACE_JOIN_INVALID:{row['race_id']}")
      delta=sum(bool(x["actual_top3"]) for x in v)-sum(bool(x["actual_top3"]) for x in c)
      out.append({**row,"race_hit_delta":delta,"positive_benefit":delta>0})
    counts=Counter(r["race_hit_delta"] for r in out); compos=(sum(r["race_hit_delta"]>0 for r in out),sum(r["race_hit_delta"]==0 for r in out),sum(r["race_hit_delta"]<0 for r in out))
    if len(out)!=62 or compos!=(20,37,5): raise Stop(f"FROZEN_OUTCOME_COMPOSITION_MISMATCH:{compos}")
    after=sha(OUT/"phase_a_pre_only_dataset.csv")
    if after!=phase_hash: raise Stop("PHASE_A_SHA_CHANGED_AFTER_RESULT_JOIN")
    return out,{"phase_a_artifact":"phase_a_pre_only_dataset.csv","phase_a_sha_before_result_join":phase_hash,"phase_a_sha_after_result_join":after,"mismatch_count":0,"consumed_result_source":str((POST/"selection_result_join.json").relative_to(ROOT)),"joined_races":62}

def binary_test(rows:list[dict[str,Any]])->dict[str,Any]:
    one=[r for r in rows if r["signal_c_top5_exclusion_flag"]==1]; zero=[r for r in rows if r["signal_c_top5_exclusion_flag"]==0]
    a=sum(r["positive_benefit"] for r in one); b=len(one)-a; c=sum(r["positive_benefit"] for r in zero); d=len(zero)-c; rate1=a/len(one); rate0=c/len(zero); rd=rate1-rate0
    rrisk=rate1/rate0 if rate0 else None; odds=(a*d)/(b*c) if b*c else None
    return {"signal":"C","mechanism":"CURRENT_V4_CANDIDATE_SET_DISAGREEMENT_SEVERITY","table":{"C1_positive":a,"C1_non_positive":b,"C0_positive":c,"C0_non_positive":d},"n":{"C1":len(one),"C0":len(zero)},"positive_benefit_rate":{"C1":rate1,"C0":rate0},"risk_difference":rd,"risk_ratio":rrisk,"odds_ratio":odds,"fisher_exact_p_diagnostic_only":float(fisher_exact([[a,b],[c,d]],alternative="two-sided").pvalue),"expected_direction":"RD > 0","direction":"EXPECTED_STRICT_SIGN" if rd>0 else "ZERO_OR_OPPOSITE"}

def lodo(rows:list[dict[str,Any]], signal:str, stat:Callable[[list[dict[str,Any]]],float|None], expected:str)->dict[str,Any]:
    result={}
    for date in sorted({r["date"] for r in rows}):
      subset=[r for r in rows if r["date"]!=date]; value=stat(subset); direction="NOT_EVALUABLE" if value is None else "EXPECTED_STRICT_SIGN" if ((value>0)==(expected=="POSITIVE")) else "ZERO_OR_OPPOSITE"
      result[date]={"removed_date":date,"remaining_n":len(subset),"statistic":value,"direction":direction}
    return result

def cont_stat(signal:str)->Callable[[list[dict[str,Any]]],float|None]:
    return lambda xs: rr([float(x[signal]) for x in xs if x["positive_benefit"]],[float(x[signal]) for x in xs if not x["positive_benefit"]])
def rd_stat(xs:list[dict[str,Any]])->float|None:
    one=[x for x in xs if x["signal_c_top5_exclusion_flag"]==1]; zero=[x for x in xs if x["signal_c_top5_exclusion_flag"]==0]
    return None if not one or not zero else sum(x["positive_benefit"] for x in one)/len(one)-sum(x["positive_benefit"] for x in zero)/len(zero)

def sensitivity(rows:list[dict[str,Any]], name:str, stat:Callable[[list[dict[str,Any]]],float|None], expected:str)->tuple[dict[str,Any],dict[str,Any]]:
    def state(v:float|None)->str: return "NOT_EVALUABLE" if v is None else "EXPECTED_STRICT_SIGN" if ((v>0)==(expected=="POSITIVE")) else "ZERO_OR_OPPOSITE"
    depth={str(d):{"n":len(z:=[x for x in rows if x["replacement_depth"]==d]),"statistic":stat(z),"direction":state(stat(z))} for d in (1,2)}
    volume={str(k):{"n":len(z:=[x for x in rows if x["buy_volume"]==k]),"statistic":stat(z),"direction":state(stat(z))} for k in (1,2,3)}
    return depth,volume

def classify(pooled:dict[str,Any], l:dict[str,Any], depth:dict[str,Any], volume:dict[str,Any])->str:
    if pooled.get("direction")!="EXPECTED_STRICT_SIGN": return "NOT_DIRECTIONALLY_SUPPORTED"
    lodo_states=[x["direction"] for x in l.values()]
    if any(x=="NOT_EVALUABLE" for x in lodo_states): return "STRUCTURAL_ROBUSTNESS_NOT_EVALUABLE"
    if any(x!="EXPECTED_STRICT_SIGN" for x in lodo_states): return "NOT_DIRECTIONALLY_SUPPORTED"
    tests=[depth["1"]["direction"],volume["1"]["direction"],volume["2"]["direction"]]
    if any(x=="NOT_EVALUABLE" for x in tests): return "DIRECTIONALLY_SUPPORTED_BUT_CONTEXT_ROBUSTNESS_NOT_ESTABLISHED"
    if depth["1"]["direction"]!="EXPECTED_STRICT_SIGN": return "LIKELY_REPLACEMENT_DEPTH_PROXY"
    if volume["1"]["direction"]!="EXPECTED_STRICT_SIGN" or volume["2"]["direction"]!="EXPECTED_STRICT_SIGN": return "BUY_VOLUME_DEPENDENT_OR_CONFOUNDED"
    return "CONTEXT_ROBUST_DIRECTIONALLY_SUPPORTED"

def main()->int:
    if OUT.exists(): raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    before={"pre":sha(PRE/"artifact_hashes.json"),"post":sha(POST/"artifact_hashes.json"),"v3":sha(V3/"artifact_hashes.json"),"v4":sha(V4/"artifact_hashes.json"),"cf":sha(CF/"protocol.json")}
    checks={"pre_verified":verify(PRE),"post_verified":verify(POST),"v3_verified":verify(V3),"v4_verified":verify(V4)}
    preflight=duplicate()
    if preflight["exact_duplicate_count"]: raise Stop("EXACT_DUPLICATE_EXISTS")
    OUT.mkdir(parents=True); dump("duplicate_analysis_preflight.json",preflight)
    dump("scope.json",{"authority":"V4_RESELECTION_RELIABILITY_SIGNAL_FAMILY_DESIGN = ACCEPTED_AND_FROZEN","signals":["A boundary gap","B N_eff","C top5 exclusion flag"],"forbidden":["new variables","routing","threshold search","model/Production change","new holdout"]})
    dump("design_authority.json",{"status":"ACCEPTED_AND_FROZEN","design_status":"FROZEN_READY_FOR_RESULT_LABEL_JOIN","claude_independent_review":"ACCEPT","chatgpt_integrated_review":"ACCEPT"})
    dump("evidence_role.json",{"PROBABILITY_SOURCE_ORIGIN":"FROZEN_FEBRUARY_EXTERNAL_HOLDOUT_V4_PREDICTION","CURRENT_EVIDENCE_ROLE":"CONSUMED_DEVELOPMENT_DIAGNOSTIC_ONLY","prohibited_descriptions":["external validation of routing","independent routing holdout","formal prospective/historical routing evidence"]})
    rows,population,integrity=construct_phase_a(); dump("population_reproduction.json",population); dump("pre_input_integrity.json",integrity)
    structural=phase_a_structural(rows); phase_hash=write_phase_a(rows,structural)
    joined,manifest=result_join(rows,phase_hash); dump("phase_b_result_join_manifest.json",manifest)
    raw=Counter(r["race_hit_delta"] for r in joined); dump("raw_race_hit_delta_distribution.json",{"counts":dict(sorted(raw.items())),"mean_descriptive_only":statistics.mean(r["race_hit_delta"] for r in joined),"median":statistics.median(r["race_hit_delta"] for r in joined),"total_net_hit_difference":sum(r["race_hit_delta"] for r in joined),"by_signal_c":{str(c):dict(sorted(Counter(r["race_hit_delta"] for r in joined if r["signal_c_top5_exclusion_flag"]==c).items())) for c in (0,1)},"inferential_testing":"PROHIBITED"})
    pos=[r for r in joined if r["positive_benefit"]]; non=[r for r in joined if not r["positive_benefit"]]
    a=cont_test([r["signal_a_boundary_gap"] for r in pos],[r["signal_a_boundary_gap"] for r in non],"POSITIVE"); b=cont_test([r["signal_b_n_eff"] for r in pos],[r["signal_b_n_eff"] for r in non],"NEGATIVE"); c=binary_test(joined)
    dump("signal_a_boundary_gap.json",a); dump("signal_b_n_eff.json",b); dump("signal_c_exclusion_flag.json",c)
    stats={"A":cont_stat("signal_a_boundary_gap"),"B":cont_stat("signal_b_n_eff"),"C":rd_stat}; expectations={"A":"POSITIVE","B":"NEGATIVE","C":"POSITIVE"}; pooled={"A":a,"B":b,"C":c}
    lodos={k:lodo(joined,k,stats[k],expectations[k]) for k in stats}; dump("informative_date_lodo.json",{"informative_dates":sorted({r["date"] for r in joined}),"excluded_noninformative_date":"20260208:NO_REPLACEMENT_ACTIVE_OBSERVATIONS","signals":lodos})
    depths={}; volumes={}
    for k in stats: depths[k],volumes[k]=sensitivity(joined,k,stats[k],expectations[k])
    dump("replacement_depth_sensitivity.json",depths); dump("buy_volume_sensitivity.json",volumes)
    classifications={k:classify(pooled[k],lodos[k],depths[k],volumes[k]) for k in stats}; dump("signal_classifications.json",{"signals":classifications,"eligible_for_next_stage_design_review":[k for k,v in classifications.items() if v=="CONTEXT_ROBUST_DIRECTIONALLY_SUPPORTED"]})
    family="NEXT_STAGE_DESIGN_REVIEW_JUSTIFIED_PENDING_INDEPENDENT_REVIEW" if any(v=="CONTEXT_ROBUST_DIRECTIONALLY_SUPPORTED" for v in classifications.values()) else "CLOSE_NO_ACTIONABLE_SIGNAL_PENDING_INDEPENDENT_REVIEW"
    dump("historical_lineage_assessment.json",{"current_diagnostic_test_set":["V4_SELECTION_BOUNDARY_GAP","N_eff","V4_TOP5_EXCLUSION_FLAG"],"historical_reliability_lineage":["RACE_TOP_GAP","BUY_NEXT_GAP","adjusted_score_gap_to_top","relative_advantage margin","V4_SELECTION_BOUNDARY_GAP","N_eff","V4_TOP5_EXCLUSION_FLAG"],"family_state":family,"conditional_closure_statement":"The seven actually tested representations did not produce an actionable reliability signal." if family.startswith("CLOSE") else "At least one signal reaches the frozen context-robust directional criterion; design review only."})
    dump("february_reuse_closure.json",{"FEBRUARY_FEATURE_HYPOTHESIS_GENERATION":"CLOSED_AFTER_V4_RESELECTION_RELIABILITY_DIAGNOSTIC","future_february_promotion_prohibited":["feature hypothesis","routing signal","subgroup hypothesis","threshold","transformed variant"],"unexpected_patterns":"UNPREREGISTERED_OBSERVATION_ONLY"})
    dump("formal_track_preservation.json",{"V4_MODEL_V4_FORMAL_PROSPECTIVE_STATUS":"READY_FOR_FIRST_FORMAL_PRE","V4_MODEL_V3_FORMAL_PROSPECTIVE_SHADOW":"CONTINUE","CF_EVIDENCE_TRACK":"SEPARATE_AND_CONTINUING","mutations":0})
    after={"pre":sha(PRE/"artifact_hashes.json"),"post":sha(POST/"artifact_hashes.json"),"v3":sha(V3/"artifact_hashes.json"),"v4":sha(V4/"artifact_hashes.json"),"cf":sha(CF/"protocol.json")}
    if before!=after: raise Stop("FROZEN_AUTHORITY_MUTATION")
    dump("safety.json",{"status":"PASS","production":0,"current_ai":0,"buy_engine":0,"decision_engine_semantics":0,"shadow_buy_semantics":0,"model_v3":0,"model_v4":0,"scaler":0,"dataset":0,"v3_protocol":0,"v4_protocol":0,"cf_protocol":0,"prediction_execution":0,"model_retraining":0,"oof_reconstruction":0,"new_result_acquisition":0,"untouched_holdout_access":0,"february_pre_mutation":0,"february_post_mutation":0,"trace_schema_mutation":0,"routing_implementation":0,"threshold_search":0,"authority_hashes_before_after":after,**checks})
    report=["# V4 Reselection Reliability Signal Family", "", "- `V4_RESELECTION_RELIABILITY_DIAGNOSTIC = COMPLETE_PENDING_INDEPENDENT_REVIEW`", f"- Family: `{family}`"]+[f"- Signal {k}: `{v}`" for k,v in classifications.items()]
    (OUT/"report.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    hs={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"}; dump("artifact_hashes.json",{"self_hash_excluded":True,"indexed_artifacts":hs})
    if any(sha(OUT/n)!=h for n,h in hs.items()): raise Stop("ARTIFACT_HASH_MISMATCH")
    print("V4_RESELECTION_RELIABILITY_DIAGNOSTIC=COMPLETE_PENDING_INDEPENDENT_REVIEW")
    return 0
if __name__=="__main__": raise SystemExit(main())
