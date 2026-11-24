"""Approved pre-disclosure recovery: A/B-only February reselection diagnostic."""
from __future__ import annotations
import csv, hashlib, json, math, statistics
from collections import Counter
from pathlib import Path
from typing import Any
from scipy.stats import mannwhitneyu, spearmanr

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"reports"/"v4_reselection_reliability_signal_family_v2"
V1=ROOT/"reports"/"v4_reselection_reliability_signal_family_v1"
PRE=ROOT/"reports"/"v4_model_v4_february_historical_holdout"/"formal_pre"
POST=ROOT/"reports"/"v4_model_v4_february_historical_holdout"/"formal_post"
V3=ROOT/"reports"/"v4_model_v3_prospective_protocol_v1"; V4=ROOT/"reports"/"v4_model_v4_formal_prospective"; CF=ROOT/"reports"/"shadow_cf_top3_rank_anchored_v1"
class Stop(RuntimeError): pass
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):
 v=json.loads(Path(p).read_text(encoding="utf8"))
 if not isinstance(v,dict): raise Stop(f"JSON_OBJECT_REQUIRED:{p}")
 return v
def dump(n,v): (OUT/n).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
def verify(root):
 d=load(root/"artifact_hashes.json").get("indexed_artifacts")
 if not isinstance(d,dict): raise Stop(f"HASH_INDEX_INVALID:{root}")
 for n,h in d.items():
  if not isinstance(h,str) or not (root/n).is_file() or sha(root/n)!=h: raise Stop(f"HASH_INDEX_MISMATCH:{root}:{n}")
 return len(d)
def q(x,p): return float(__import__("numpy").percentile(x,p)) if x else None
def desc(x): return {"n":len(x),"median":q(x,50),"iqr":[q(x,25),q(x,75)],"mean_descriptive_only":statistics.mean(x) if x else None}
def rrb(a,b):
 if not a or not b:return None
 return (sum(x>y for x in a for y in b)-sum(x<y for x in a for y in b))/(len(a)*len(b))
def ctest(a,b,expect):
 o={"positive_benefit":desc(a),"non_positive_benefit":desc(b),"expected_sign":expect}
 if not a or not b:return {**o,"computable":False,"direction":"NOT_EVALUABLE"}
 u=mannwhitneyu(a,b,alternative="two-sided"); r=rrb(a,b); good=(r>0 if expect=="POSITIVE" else r<0)
 return {**o,"computable":True,"mann_whitney_u":float(u.statistic),"two_sided_p_diagnostic_only":float(u.pvalue),"r_rb":r,"direction":"EXPECTED_STRICT_SIGN" if good else "ZERO_OR_OPPOSITE"}
def phase_a():
 e=load(PRE/"formal_eligible_population.json")["eligible_races"]; inf={x["race_id"]:x for x in load(PRE/"v4_prediction.json")["inference_records"]}
 if len(e)!=81 or len(inf)!=81:raise Stop("FROZEN_UNIVERSE_81_MISMATCH")
 rows=[]; top5count=0
 for x in e:
  r=inf.get(x["race_id"]); top=r.get("top5_probabilities") if isinstance(r,dict) else None
  if not isinstance(top,list) or len(top)!=5:raise Stop(f"V4_TOP5_LENGTH_INVALID:{x['race_id']}")
  top5count+=1
  if int(x["replacement_depth"])<1:continue
  k=int(x["current_buy_count"]); current=x["current_selected_horses"]; v4=x["v4_selected_horses"]
  if k not in (1,2,3) or len(current)!=k or len(v4)!=k or k+1>5:raise Stop(f"VOLUME_OR_IDENTITY_INVALID:{x['race_id']}")
  probs=[]; ids=[]
  for z in top:
   p=z.get("predicted_top3_probability"); n=z.get("horse_number")
   if not isinstance(n,int) or isinstance(p,bool) or not isinstance(p,(int,float)) or not math.isfinite(float(p)):raise Stop(f"V4_PROBABILITY_INVALID:{x['race_id']}")
   probs.append(float(p));ids.append(n)
  if len(set(ids))!=5 or sum(probs)<=0:raise Stop(f"V4_CANDIDATE_IDENTITY_INVALID:{x['race_id']}")
  qq=[p/sum(probs) for p in probs]
  rows.append({"date":x["date"],"race_id":x["race_id"],"venue":x["venue"],"race_number":x["race_number"],"race_state":x["race_state"],"buy_volume":k,"replacement_depth":int(x["replacement_depth"]),"current_top5_candidate_universe":"|".join(map(str,ids)),"v4_probabilities":"|".join(map(repr,probs)),"signal_a_boundary_gap":probs[k-1]-probs[k],"signal_b_n_eff":math.exp(-sum(t*math.log(t) for t in qq if t>0)),"p_rank_k":probs[k-1],"signal_c_status":"INVALID_NO_VARIATION_IN_FROZEN_POPULATION"})
 if len(rows)!=62:raise Stop(f"PRIMARY_POPULATION_MISMATCH:{len(rows)}")
 dates=Counter(x["date"] for x in rows); expected={"20260201":8,"20260207":9,"20260210":4,"20260214":11,"20260215":7,"20260221":10,"20260222":6,"20260228":7}
 if dates!=expected:raise Stop("INFORMATIVE_DATE_COUNTS_MISMATCH")
 pop={"formal_eligible_races":81,"primary_diagnostic_population":"FEBRUARY_REPLACEMENT_ACTIVE_62_RACES","primary_races":62,"by_replacement_depth":dict(Counter(x["replacement_depth"] for x in rows)),"by_buy_volume":dict(Counter(x["buy_volume"] for x in rows)),"action_space":"FROZEN_CURRENT_TOP5_ONLY","mechanistic_capability":"WITHIN_CURRENT_TOP5_SELECTION_ONLY","cannot_recover":"HORSE_ABSENT_FROM_FROZEN_CURRENT_TOP5"}
 integ={"status":"PASS","all_81_top5_probability_length_5":top5count,"primary_races":62,"K_values_valid":True,"all_A_B_computable":True,"candidate_identity_valid":True,"signal_c_status":"INVALID_NO_VARIATION_IN_FROZEN_POPULATION"}
 return rows,pop,integ
def structural(rows):
 ks=["signal_a_boundary_gap","signal_b_n_eff","p_rank_k"]; corr={}
 for i,a in enumerate(ks):
  for b in ks[i+1:]:corr[a+"__"+b]=float(spearmanr([x[a] for x in rows],[x[b] for x in rows]).statistic)
 def grouped(field,value):return {s:desc([float(x[s]) for x in rows if x[field]==value]) for s in ks}
 return {"pairwise_spearman":corr,"high_redundancy_abs_rho_gt_0_90":[n for n,v in corr.items() if abs(v)>.90],"by_buy_volume":{str(k):grouped("buy_volume",k) for k in (1,2,3)},"by_replacement_depth":{str(d):grouped("replacement_depth",d) for d in (1,2)},"p_rank_k":"DESCRIPTIVE_ONLY"}
def join(rows,phasehash):
 if sha(OUT/"phase_a_pre_only_dataset.csv")!=phasehash:raise Stop("PHASE_A_SHA_CHANGED_BEFORE_JOIN")
 j=load(POST/"selection_result_join.json")
 def byrace(xs):
  o={}
  for x in xs:o.setdefault(x["race_id"],[]).append(x)
  return o
 c=byrace(j["current_selected"]);v=byrace(j["v4_selected"]);out=[]
 for x in rows:
  cc=c.get(x["race_id"],[]);vv=v.get(x["race_id"],[])
  if len(cc)!=x["buy_volume"] or len(vv)!=x["buy_volume"] or any(not z.get("valid_result") for z in cc+vv):raise Stop(f"RESULT_JOIN_INVALID:{x['race_id']}")
  d=sum(bool(z["actual_top3"]) for z in vv)-sum(bool(z["actual_top3"]) for z in cc);out.append({**x,"race_hit_delta":d,"positive_benefit":d>0})
 counts=(sum(x["positive_benefit"] for x in out),sum(not x["positive_benefit"] for x in out))
 if counts!=(20,42):raise Stop(f"OUTCOME_COMPOSITION_MISMATCH:{counts}")
 after=sha(OUT/"phase_a_pre_only_dataset.csv")
 if after!=phasehash:raise Stop("PHASE_A_SHA_CHANGED_AFTER_JOIN")
 return out,{"phase_a_sha_before_result_join":phasehash,"phase_a_sha_after_result_join":after,"mismatch_count":0,"consumed_result_source":str((POST/"selection_result_join.json").relative_to(ROOT)),"positive_benefit":20,"non_positive_benefit":42}
def statfun(signal):return lambda xs:rrb([float(x[signal]) for x in xs if x["positive_benefit"]],[float(x[signal]) for x in xs if not x["positive_benefit"]])
def sign(v,e):return "NOT_EVALUABLE" if v is None else "EXPECTED_STRICT_SIGN" if ((v>0)==(e=="POSITIVE")) else "ZERO_OR_OPPOSITE"
def lodo(rows,f,e):
 return {d:{"remaining_n":len(s:=[x for x in rows if x["date"]!=d]),"statistic":f(s),"direction":sign(f(s),e)} for d in sorted({x["date"] for x in rows})}
def sens(rows,f,e):
 return ({str(d):{"n":len(s:=[x for x in rows if x["replacement_depth"]==d]),"statistic":f(s),"direction":sign(f(s),e)} for d in (1,2)},{str(k):{"n":len(s:=[x for x in rows if x["buy_volume"]==k]),"statistic":f(s),"direction":sign(f(s),e)} for k in (1,2,3)})
def classify(p,l,d,k):
 if p["direction"]!="EXPECTED_STRICT_SIGN":return "NOT_DIRECTIONALLY_SUPPORTED"
 ls=[x["direction"] for x in l.values()]
 if any(x=="NOT_EVALUABLE" for x in ls):return "STRUCTURAL_ROBUSTNESS_NOT_EVALUABLE"
 if any(x!="EXPECTED_STRICT_SIGN" for x in ls):return "NOT_DIRECTIONALLY_SUPPORTED"
 need=[d["1"]["direction"],k["1"]["direction"],k["2"]["direction"]]
 if any(x=="NOT_EVALUABLE" for x in need):return "DIRECTIONALLY_SUPPORTED_BUT_CONTEXT_ROBUSTNESS_NOT_ESTABLISHED"
 if d["1"]["direction"]!="EXPECTED_STRICT_SIGN":return "LIKELY_REPLACEMENT_DEPTH_PROXY"
 if k["1"]["direction"]!="EXPECTED_STRICT_SIGN" or k["2"]["direction"]!="EXPECTED_STRICT_SIGN":return "BUY_VOLUME_DEPENDENT_OR_CONFOUNDED"
 return "CONTEXT_ROBUST_DIRECTIONALLY_SUPPORTED"
def main():
 if OUT.exists():raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
 before={"pre":sha(PRE/"artifact_hashes.json"),"post":sha(POST/"artifact_hashes.json"),"v3":sha(V3/"artifact_hashes.json"),"v4":sha(V4/"artifact_hashes.json"),"cf":sha(CF/"protocol.json")}; checks={"pre_verified":verify(PRE),"post_verified":verify(POST),"v3_verified":verify(V3),"v4_verified":verify(V4)}
 if not V1.is_dir():raise Stop("V1_STOP_RECORD_NOT_FOUND")
 OUT.mkdir(parents=True)
 dump("recovery_authority.json",{"PRE_DISCLOSURE_DESIGN_CORRECTION":"ACCEPTED","recovery_scope":"A_B_ONLY","result_access_at_recovery_start":0,"A_outcome_analysis_at_start":0,"B_outcome_analysis_at_start":0})
 dump("v1_stop_preservation.json",{"v1_path":str(V1.relative_to(ROOT)),"v1_mutation_count":0,"preserved_state":"STOPPED; original 24/62 expectation, actual 0/62, Result access 0, Phase B not executed"})
 dump("signal_c_forensic_correction.json",{"PRIOR_SIGNAL_C_PREVALENCE_AUDIT":"INVALID_WRONG_RACE_JOIN","SIGNAL_C_STATUS":"INVALID_NO_VARIATION_IN_FROZEN_POPULATION","root_cause":"line-oriented parser assumed race_id before horse_number under sort_keys=True JSON; proper structured JSON record parsing gives C=1: 0/62","outcome_tested":False,"empirical_vote":False})
 dump("governance_lessons.json",{"candidate_universe":"Trace generator/invariant before membership variables; zero variation is conservatively NO_VARIATION_IN_FROZEN_POPULATION.","structured_json":"Use JSON parser and record-level key access; never physical line order assumptions."})
 dump("candidate_universe_semantics.json",{"V4_RESELECTION_CANDIDATE_UNIVERSE":"FROZEN_CURRENT_TOP5","generator_semantics":"V4 scores/orders Current AI top5 and reselects same volume within it.","not_whole_field":True})
 dump("scope.json",{"CURRENT_DIAGNOSTIC_TEST_SET":["A: V4_SELECTION_BOUNDARY_GAP","B: N_eff"],"signal_c":"INVALID_NO_VARIATION_IN_FROZEN_POPULATION","forbidden":["new signal","routing","threshold search","model/Production change"]})
 dump("evidence_role.json",{"PROBABILITY_SOURCE_ORIGIN":"FROZEN_FEBRUARY_EXTERNAL_HOLDOUT_V4_PREDICTION","CURRENT_EVIDENCE_ROLE":"CONSUMED_DEVELOPMENT_DIAGNOSTIC_ONLY"})
 rows,pop,integ=phase_a();dump("population_reproduction.json",pop);dump("pre_input_integrity.json",integ);st=structural(rows)
 with (OUT/"phase_a_pre_only_dataset.csv").open("w",encoding="utf8",newline="") as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 dump("phase_a_structural_checks.json",st); ph=sha(OUT/"phase_a_pre_only_dataset.csv"); dump("phase_a_artifact_hashes.json",{"state":"V4_RESELECTION_RELIABILITY_V2_PRE_DATA = FROZEN_BEFORE_RESULT_JOIN","indexed_artifacts":{"phase_a_pre_only_dataset.csv":ph,"phase_a_structural_checks.json":sha(OUT/"phase_a_structural_checks.json")},"self_hash_excluded":True})
 joined,man=join(rows,ph);dump("phase_b_result_join_manifest.json",man);deltas=[x["race_hit_delta"] for x in joined];dump("raw_race_hit_delta_distribution.json",{"counts":dict(sorted(Counter(deltas).items())),"mean_descriptive_only":statistics.mean(deltas),"median":statistics.median(deltas),"total_net_hit_difference":sum(deltas),"inferential_testing":"PROHIBITED"})
 pos=[x for x in joined if x["positive_benefit"]];non=[x for x in joined if not x["positive_benefit"]]; A=ctest([x["signal_a_boundary_gap"] for x in pos],[x["signal_a_boundary_gap"] for x in non],"POSITIVE");B=ctest([x["signal_b_n_eff"] for x in pos],[x["signal_b_n_eff"] for x in non],"NEGATIVE");dump("signal_a_boundary_gap.json",A);dump("signal_b_n_eff.json",B)
 fs={"A":statfun("signal_a_boundary_gap"),"B":statfun("signal_b_n_eff")}; ex={"A":"POSITIVE","B":"NEGATIVE"}; L={n:lodo(joined,f,ex[n]) for n,f in fs.items()};D={};K={}
 for n,f in fs.items():D[n],K[n]=sens(joined,f,ex[n])
 dump("informative_date_lodo.json",{"informative_dates":sorted({x["date"] for x in joined}),"noninformative_date":"20260208:NO_REPLACEMENT_ACTIVE_OBSERVATIONS","signals":L});dump("replacement_depth_sensitivity.json",D);dump("buy_volume_sensitivity.json",K)
 C={"A":classify(A,L["A"],D["A"],K["A"]),"B":classify(B,L["B"],D["B"],K["B"])};eligible=[n for n,v in C.items() if v=="CONTEXT_ROBUST_DIRECTIONALLY_SUPPORTED"];family="NEXT_STAGE_DESIGN_REVIEW_JUSTIFIED_PENDING_INDEPENDENT_REVIEW" if eligible else "CLOSE_NO_ACTIONABLE_SIGNAL_PENDING_INDEPENDENT_REVIEW";dump("signal_classifications.json",{"A":C["A"],"B":C["B"],"eligible_for_next_stage_design_review":eligible})
 dump("historical_lineage_assessment.json",{"outcome_evaluable":["RACE_TOP_GAP","BUY_NEXT_GAP","adjusted_score_gap_to_top","relative_advantage","Signal A","Signal B"],"Signal C":"INVALID_NO_VARIATION_IN_FROZEN_POPULATION (not empirical negative evidence)","family":family,"lineage":"TESTED_GAP_DISPERSION_AND_RESELECTION_RELIABILITY_LINEAGE = CLOSED_WITHOUT_ACTIONABLE_SIGNAL" if not eligible else "OPEN_FOR_DESIGN_REVIEW_ONLY"})
 dump("february_reuse_closure.json",{"FEBRUARY_FEATURE_HYPOTHESIS_GENERATION":"CLOSED_AFTER_V4_RESELECTION_RELIABILITY_DIAGNOSTIC","unexpected_patterns":"UNPREREGISTERED_OBSERVATION_ONLY"});dump("formal_track_preservation.json",{"V4_MODEL_V4_FORMAL_PROSPECTIVE_STATUS":"READY_FOR_FIRST_FORMAL_PRE","V4_MODEL_V3_FORMAL_PROSPECTIVE_SHADOW":"CONTINUE","CF_EVIDENCE_TRACK":"SEPARATE_AND_CONTINUING","mutation_count":0})
 after={"pre":sha(PRE/"artifact_hashes.json"),"post":sha(POST/"artifact_hashes.json"),"v3":sha(V3/"artifact_hashes.json"),"v4":sha(V4/"artifact_hashes.json"),"cf":sha(CF/"protocol.json")}
 if before!=after:raise Stop("FROZEN_AUTHORITY_MUTATION")
 dump("safety.json",{"status":"PASS","production":0,"current_ai":0,"buy_engine":0,"decision_engine":0,"shadow_buy":0,"model_v3":0,"model_v4":0,"scaler":0,"dataset":0,"v3_protocol":0,"v4_protocol":0,"cf_protocol":0,"prediction_execution":0,"model_retraining":0,"probability_regeneration":0,"new_result_acquisition":0,"untouched_holdout_access":0,"february_pre_mutation":0,"february_post_mutation":0,"routing_implementation":0,"threshold_search":0,"authority_hashes_before_after":after,**checks})
 (OUT/"report.md").write_text("# V4 Reselection Reliability Signal Family v2\n\n- `V4_RESELECTION_RELIABILITY_DIAGNOSTIC_V2 = COMPLETE_PENDING_INDEPENDENT_REVIEW`\n- A: `"+C["A"]+"`\n- B: `"+C["B"]+"`\n- Family: `"+family+"`\n",encoding="utf8")
 hs={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"};dump("artifact_hashes.json",{"self_hash_excluded":True,"indexed_artifacts":hs})
 if any(sha(OUT/n)!=h for n,h in hs.items()):raise Stop("ARTIFACT_HASH_MISMATCH")
 print("V4_RESELECTION_RELIABILITY_DIAGNOSTIC_V2=COMPLETE_PENDING_INDEPENDENT_REVIEW")
if __name__=="__main__":main()
