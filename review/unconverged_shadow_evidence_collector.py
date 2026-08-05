"""Result-independent PRE_RACE evidence collector for UNCONVERGED races."""
from __future__ import annotations
import csv,hashlib,json
from datetime import datetime,timezone
from pathlib import Path

PIPELINE_VERSION="unconverged_shadow_evidence_v1"; FEATURE_FLAG="UNCONVERGED_SHADOW_EVIDENCE_V1"; FEATURE_FLAG_ENABLED=False; MAX_SELECT=3
TH={"decision_score":.8,"final_score":130.,"adjusted_score":145.,"max_ai_rank":5,"positive":5,"negative":1}
EV={"past_performance_score":55,"distance_score":30,"course_shape_score":5,"lap_score":0,"race_shape_score":0,"pace_style_score":10}
SAFE_HORSE_FIELDS={"race_id","horse_name","horse_number","rank","ai_rank","final_score","adjusted_score","decision_score","ability_score","past_performance_score","distance_score","course_shape_score","lap_score","race_shape_score","pace_style_score","bloodline_score","bloodline_missing","warnings"}
def num(v):
 try:return float(v)
 except:return None
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
 with Path(p).open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def gate(row,top):
 ds,fs,adj,rank=map(num,(row.get("decision_score"),row.get("final_score"),row.get("adjusted_score"),row.get("rank",row.get("ai_rank"))))
 abs_parts={"decision_score":ds is not None and ds>=TH["decision_score"],"final_score":fs is not None and fs>=TH["final_score"],"adjusted_score":adj is not None and adj>=TH["adjusted_score"]}; absolute=all(abs_parts.values())
 allowed=max(35.,top*.22);gap=top-adj if adj is not None else None;relative=rank is not None and rank<=TH["max_ai_rank"] and gap is not None and gap<=allowed
 pos=neg=0;missing=[]
 ability=num(row.get("ability_score"))
 if ability is None:missing.append("Ability(optional)")
 elif ability<0:neg+=1
 elif ability>=120:pos+=1
 for field,t in EV.items():
  v=num(row.get(field));
  if v is None:missing.append(field)
  elif v<0:neg+=1
  elif v>=t:pos+=1
 blocking=[x for x in missing if not x.endswith("(optional)")];consensus=pos>=TH["positive"] and neg<=TH["negative"] and not blocking
 trace="COMPLETE" if ds is not None and fs is not None and adj is not None and rank is not None else "TRACE"
 return {"absolute_status":"PASS" if absolute else "FAIL","decision_score_threshold":TH["decision_score"],"final_score_threshold":TH["final_score"],"adjusted_score_threshold":TH["adjusted_score"],"decision_score_margin":None if ds is None else round(ds-TH["decision_score"],6),"final_score_margin":None if fs is None else round(fs-TH["final_score"],6),"adjusted_score_margin":None if adj is None else round(adj-TH["adjusted_score"],6),"absolute_reason_code":"ALL_ABSOLUTE_THRESHOLDS_MET" if absolute else "ABSOLUTE_THRESHOLD_FAILED","absolute_calculation_version":"shadow_buy_spec_v1_0","absolute_source_fields":"decision_score;final_score;adjusted_score","relative_status":"PASS" if relative else "FAIL","relative_gap":gap,"relative_allowed_gap":allowed,"relative_margin":None if gap is None else round(allowed-gap,6),"relative_reason_code":"RANK_AND_TOP_GAP_ALLOWED" if relative else "RANK_OR_TOP_GAP_FAILED","relative_calculation_version":"shadow_buy_spec_v1_0","relative_source_fields":"ai_rank;adjusted_score","consensus_status":"TRACE" if blocking else ("PASS" if consensus else "FAIL"),"positive_evaluator_count":pos,"negative_evaluator_count":neg,"consensus_positive_threshold":TH["positive"],"consensus_negative_max":TH["negative"],"consensus_positive_margin":pos-TH["positive"],"blocking_missing":";".join(blocking),"optional_missing":";".join(x for x in missing if x.endswith("(optional)")),"consensus_reason_code":"BLOCKING_MISSING_TRACE" if blocking else ("CONSENSUS_THRESHOLDS_MET" if consensus else "CONSENSUS_THRESHOLD_FAILED"),"consensus_calculation_version":"shadow_buy_spec_v1_0","consensus_source_fields":"evaluator_score_fields","trace_status":trace}
def stable(rows,score):return sorted(rows,key=lambda x:(-score(x),num(x.get("ai_rank")) or 999,-(num(x.get("adjusted_score")) or -1e9),-(num(x.get("decision_score")) or -1e9),num(x.get("horse_number")) or 999,x.get("horse_name","")))
def guards(group,audit_group=None):
 audit_group=group if audit_group is None else audit_group
 top3=lambda xs:stable(xs,lambda x:num(x.get("guard_score")) or 0)[:MAX_SELECT]
 multi=[x for x in group if all(x[k]=="PASS" for k in ("absolute_status","relative_status","consensus_status"))]
 complete=[x for x in group if x["trace_status"]=="COMPLETE" and x["consensus_status"]!="TRACE"]
 dual=[]
 ranked=sorted(group,key=lambda x:(num(x["ai_rank"]) or 999,-(num(x.get("adjusted_score")) or -1e9),-(num(x.get("decision_score")) or -1e9),num(x.get("horse_number")) or 999,x.get("horse_name","")))
 if len(ranked)>=4 and (num(ranked[3]["adjusted_score"])-num(ranked[2]["adjusted_score"]))<=-10 and (num(ranked[2]["decision_score"])-num(ranked[3]["decision_score"]))>=.05:dual=ranked[:3]
 choices={"TOP_CLUSTER_DUAL_SEPARATION":dual,"MULTI_GATE_SUPPORT_FLOOR":top3(multi),"TRACE_COMPLETENESS_AND_RACE_SUPPORT":top3(complete) if len(complete)>=2 else []}
 for name,selected in choices.items():
  keys={(x["race_id"],x["horse_name"]) for x in selected}
  for x in audit_group:
   eligible=bool(x.get("guard_eligible",True));chosen=(x["race_id"],x["horse_name"]) in keys
   x[f"{name}_selected"]=chosen;x[f"{name}_selection_rank"]=(selected.index(x)+1 if x in selected else "");x[f"{name}_selection_reason"]=("SELECTED_PRE_RACE_GUARD" if chosen else "");x[f"{name}_rejection_reason"]=("" if chosen else ("PRE_FILTER_EXCLUDED" if not eligible else "GUARD_FAILED_OR_CAP3"));x[f"{name}_selected_count_in_race"]=len(selected);x[f"{name}_max_selection_count"]=MAX_SELECT
 return choices
def collect(race_file,horse_file,out_dir,date):
 race_file,horse_file,out_dir=map(Path,(race_file,horse_file,out_dir));rr,hh=read(race_file),read(horse_file); races={x["race_id"]:x for x in rr if x.get("race_state")=="PLAY_UNCONVERGED_4PLUS" and int(x.get("entry_count",0))>=4}; rows=[]
 for rid,race in races.items():
  try:structure=json.loads(race.get("race_structure") or "{}")
  except json.JSONDecodeError:structure={}
  group=[{k:v for k,v in x.items() if k in SAFE_HORSE_FIELDS} for x in hh if x["race_id"]==rid and (num(x.get("rank",x.get("ai_rank"))) or 999)<=TH["max_ai_rank"]];top=max(num(x.get("adjusted_score")) or -1e9 for x in group)
  for x in group:
   x["ai_rank"]=x.get("rank",x.get("ai_rank",""));x.update(gate(x,top));a=x["absolute_status"]=="PASS";r=x["relative_status"]=="PASS";complete=x["trace_status"]=="COMPLETE"
   status="TRACE_INCOMPLETE" if not complete else ("ELIGIBLE_GUARD_INPUT" if a and r else ("EXCLUDED_ABSOLUTE_AND_RELATIVE_FAIL" if not a and not r else ("EXCLUDED_ABSOLUTE_FAIL" if not a else "EXCLUDED_RELATIVE_FAIL")))
   x.update({"candidate_detected":True,"guard_eligible":status=="ELIGIBLE_GUARD_INPUT","pre_filter_status":status,"pre_filter_reason":"ABSOLUTE_AND_RELATIVE_PASS" if status=="ELIGIBLE_GUARD_INPUT" else status})
  eligible=[x for x in group if x["guard_eligible"]]
  for x in group:
   x.update({"race_date":date,"racecourse":rid.split("_")[2],"race_number":rid.split("_")[3],"surface":structure.get("surface","UNKNOWN"),"distance":structure.get("distance",""),"race_class":"UNKNOWN","candidate_count":len(eligible),"detected_candidate_count":len(group),"RaceState":race["race_state"],"guard_score":num(x.get("decision_score")) or 0,"source_race_file":str(race_file),"source_horse_file":str(horse_file),"source_race_sha256":sha(race_file),"source_horse_sha256":sha(horse_file),"result_data_used_as_evaluation_input":"NO","created_at":datetime.now(timezone.utc).isoformat(),"pipeline_version":PIPELINE_VERSION});rows.append(x)
  guards(eligible,group)
 out_dir.mkdir(parents=True,exist_ok=True);base=out_dir/f"unconverged_shadow_pre_race_{date}_v1";fields=list(rows[0])
 with base.with_suffix(".csv").open("w",encoding="utf-8-sig",newline="") as f:w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
 payload={"pipeline_version":PIPELINE_VERSION,"feature_flag":{"name":FEATURE_FLAG,"enabled":FEATURE_FLAG_ENABLED},"race_count":len(races),"candidate_count":sum(bool(x["guard_eligible"]) for x in rows),"detected_candidate_count":len(rows),"rows":[{k:x.get(k) for k in fields} for x in rows],"result_data_used_as_evaluation_input":"NO"};base.with_suffix(".json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");base.with_suffix(".md").write_text(f"# PRE_RACE Shadow Evidence {date}\n\n- races: {len(races)}\n- guard-eligible candidates: {payload['candidate_count']}\n- detected/auditable candidates: {len(rows)}\n- result input: NO\n- feature flag: OFF\n",encoding="utf-8")
 manifest={"pre_race_csv_sha256":sha(base.with_suffix('.csv')),"pre_race_json_sha256":sha(base.with_suffix('.json')),"source_race_sha256":sha(race_file),"source_horse_sha256":sha(horse_file),"pipeline_version":PIPELINE_VERSION};(out_dir/f"unconverged_shadow_pre_race_manifest_{date}_v1.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8");return base.with_suffix(".csv")
if __name__=="__main__":collect("reports/pre_race/20260802/pre_race_20260802_race_summary.csv","reports/review_20260802/horse_review_20260802_v1.csv","reports/shadow_unconverged/pre_race","20260802")
