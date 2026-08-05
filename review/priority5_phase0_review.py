"""Priority5 Phase0: freeze saved review pairs and audit ranking/FPs (read-only inputs)."""
from __future__ import annotations
import csv, hashlib, json, re
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/"reports"/"baseline"
PAIRS={
 "20260725":("reports/review_20260725/race_review.csv","reports/review_20260725/horse_review.csv","legacy","SAVED_REVIEW"),
 "20260726":("reports/review_20260726/race_review.csv","reports/review_20260726/horse_review.csv","legacy","SAVED_REVIEW"),
 "20260801":("reports/review_20260801/race_summary_20260801_v2.csv","reports/review_20260801/horse_review_20260801_v2.csv","v2","CURRENT_CODE_REPLAY_SAVED_REVIEW"),
 "20260802":("reports/review_20260802/race_summary_20260802_v1.csv","reports/review_20260802/horse_review_20260802_v1.csv","v1","PRE_RACE_SAVED_OUTPUT"),}
RF=("race_id","race_date","racecourse","race_number","surface","distance","race_class","RaceDecision","RaceState","Confidence","buy_count","buy_horses","ai_top1","ai_top3","ai_top5","unconverged","source_version","source_sha256")
HF=("race_id","race_date","horse_name","horse_number","ai_rank","decision","buy_flag","final_score","adjusted_score","decision_score","actual_finish","actual_top3","actual_top5","valid_result","source_version","source_sha256")
def load(p):
 with p.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def val(r,*keys):
 for k in keys:
  if r.get(k) not in (None,""):return r[k]
 return ""
def boolean(v):return str(v).strip().lower() in ("1","true","yes")
def finish(v):
 try:return int(float(str(v)))
 except:return 0
def stable(rows,fields):
 x=sorted([[str(r.get(f,"")) for f in fields] for r in rows]);return hashlib.sha256(json.dumps(x,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
def write_csv(p,fields,rows):
 with p.open("w",encoding="utf-8-sig",newline="") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def run():
 OUT.mkdir(parents=True,exist_ok=True); races=[];horses=[];sources=[]
 for date,(rs,hs,version,origin) in PAIRS.items():
  rp,hp=ROOT/rs,ROOT/hs; rr,hh=load(rp),load(hp); rids={val(x,"race_id") for x in rr}; hids={val(x,"race_id") for x in hh}
  sources.append({"race_date":date,"source_race_file":rs,"source_horse_file":hs,"source_version":version,"source_evaluation_origin":origin,"source_race_sha256":sha(rp),"source_horse_sha256":sha(hp),"race_count":len(rr),"horse_count":len(hh),"race_id_set_match":rids==hids,"duplicate_count":len(rr)-len(rids)+len(hh)-len({(val(x,"race_id"),val(x,"horse_number"),val(x,"horse_name")) for x in hh}),"pairing_status":"PAIRED" if rids==hids else "MISMATCH"})
  by={rid:[] for rid in rids}
  for x in hh:by.setdefault(val(x,"race_id"),[]).append(x)
  for x in rr:
   rid=val(x,"race_id"); m=re.match(r"race_(\d{8})_([^_]+)_([^_]+)",rid); group=by.get(rid,[])
   ranked=sorted(group,key=lambda q:int(val(q,"ai_rank","rank") or 999)); buys=[val(q,"horse_name") for q in group if val(q,"decision").upper()=="BUY"]
   races.append({"race_id":rid,"race_date":date,"racecourse":val(x,"racecourse","course") or (m.group(2) if m else ""),"race_number":val(x,"race_number","race_no") or (m.group(3) if m else ""),"surface":val(x,"surface"),"distance":val(x,"distance"),"race_class":val(x,"race_class"),"RaceDecision":val(x,"race_decision","race_decision_final","RaceDecision"),"RaceState":val(x,"race_state","buy_v1_rc1_race_state","RaceState"),"Confidence":val(x,"race_confidence","confidence","Confidence"),"buy_count":len(buys),"buy_horses":"; ".join(buys),"ai_top1":val(ranked[0],"horse_name") if ranked else "","ai_top3":"; ".join(val(q,"horse_name") for q in ranked[:3]),"ai_top5":"; ".join(val(q,"horse_name") for q in ranked[:5]),"unconverged":"UNCONVERGED" in val(x,"race_state","buy_v1_rc1_race_state","RaceState"),"source_version":version,"source_sha256":sha(rp)})
  for x in hh:
   f=finish(val(x,"actual_finish","finish_position")); valid=f>0
   horses.append({"race_id":val(x,"race_id"),"race_date":date,"horse_name":val(x,"horse_name"),"horse_number":val(x,"horse_number"),"ai_rank":val(x,"ai_rank","rank"),"decision":val(x,"decision"),"buy_flag":val(x,"decision").upper()=="BUY","final_score":val(x,"final_score"),"adjusted_score":val(x,"adjusted_score"),"decision_score":val(x,"decision_score"),"actual_finish":f,"actual_top3":valid and f<=3,"actual_top5":valid and f<=5,"valid_result":valid,"source_version":version,"source_sha256":sha(hp)})
 write_csv(OUT/"keibaai_baseline_4days_v1_race.csv",RF,races);write_csv(OUT/"keibaai_baseline_4days_v1_horse.csv",HF,horses)
 buys=[x for x in horses if boolean(x["buy_flag"])];valid=[x for x in horses if boolean(x["valid_result"])]; fps=[x for x in buys if boolean(x["valid_result"]) and int(x["actual_finish"])>=4]
 for x in fps:
  f=int(x["actual_finish"]);x["fp_severity"]="NEAR_MISS" if f<=5 else ("MODERATE_MISS" if f<=9 else "SEVERE_MISS")
 top={}
 actual_top3_all=sum(boolean(x["actual_top3"]) for x in valid)
 for n in (1,3,5):
  subset=[x for x in valid if int(x["ai_rank"] or 999)<=n]; captured=sum(boolean(x["actual_top3"]) for x in subset);top[str(n)]={"target_horses":len(subset),"actual_top3":captured,"actual_top3_precision":round(100*captured/len(subset),2) if subset else 0,"share_of_all_actual_top3_captured":round(100*captured/actual_top3_all,2) if actual_top3_all else 0,"actual_top5":sum(boolean(x["actual_top5"]) for x in subset),"actual_top5_precision":round(100*sum(boolean(x["actual_top5"]) for x in subset)/len(subset),2) if subset else 0}
 expected=39; errors=[] if len(races)==expected else [f"EXPECTED_39_ACTUAL_{len(races)}"]
 hashes={"race_baseline_sha256":sha(OUT/"keibaai_baseline_4days_v1_race.csv"),"horse_baseline_sha256":sha(OUT/"keibaai_baseline_4days_v1_horse.csv"),"buy_set_sha256":stable(buys,("race_date","race_id","horse_number","horse_name")),"decision_set_sha256":stable(races,("race_id","RaceDecision","RaceState","buy_count")),"score_manifest_sha256":stable(horses,("race_id","horse_number","final_score","adjusted_score","decision_score"))}
 source_doc={"sources":sources,"result_data_used_as_evaluation_input":"NO"};(OUT/"keibaai_baseline_4days_v1_sources.json").write_text(json.dumps(source_doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");hashes["source_manifest_sha256"]=sha(OUT/"keibaai_baseline_4days_v1_sources.json")
 buy_races=len({x["race_id"] for x in buys}); buy0=len(races)-buy_races
 summary={"status":"PRIORITY5_PHASE0_COMPLETE" if not errors else "PRIORITY5_PHASE0_INCOMPLETE","baseline_freeze":"COMPLETE_WITH_COUNT_DISCREPANCY" if errors else "COMPLETE","target_dates":list(PAIRS),"expected_race_count":expected,"race_count":len(races),"horse_count":len(horses),"buy_count":len(buys),"buy_race_count":buy_races,"buy_race_rate":round(100*buy_races/len(races),2),"buy0_race_count":buy0,"buy0_race_rate":round(100*buy0/len(races),2),"average_buy_per_race":round(len(buys)/len(races),3),"buy_top3":sum(boolean(x["actual_top3"]) for x in buys),"buy_top5":sum(boolean(x["actual_top5"]) for x in buys),"buy_win":sum(int(x["actual_finish"])==1 for x in buys),"buy_place_rate":round(100*sum(boolean(x["actual_top3"]) for x in buys)/len(buys),2) if buys else 0,"buy_top5_rate":round(100*sum(boolean(x["actual_top5"]) for x in buys)/len(buys),2) if buys else 0,"fp_count":len(fps),"fn_count":sum(boolean(x["actual_top3"]) and x["decision"]!="BUY" for x in valid),"race_decision_distribution":Counter(x["RaceDecision"] for x in races),"unconverged_count":sum(boolean(x["unconverged"]) for x in races),"ranking":top,"fp_severity":Counter(x["fp_severity"] for x in fps),"ranking_judgment":"INSUFFICIENT_BASELINE" if errors else "MIXED_RESULT_ADDITIONAL_DIAGNOSTIC_REQUIRED","priority5_progress_judgment":"HOLD_INSUFFICIENT_BASELINE" if errors else "HOLD_PENDING_HUMAN_REVIEW","remeasurement_judgment":"REMEASUREMENT_WAIT","errors":errors,"hashes":hashes}
 for name in ("keibaai_baseline_4days_v1_summary.json","keibaai_baseline_4days_v1_manifest.json"):(OUT/name).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 (ROOT/"reports"/"priority5_phase0_summary_v1.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 write_csv(ROOT/"reports"/"priority5_fp_candidate_cohort_v1.csv",tuple(HF)+("fp_severity",),fps)
 write_csv(OUT/"ranking_capture_audit_v1.csv",("rank_scope","target_horses","actual_top3","actual_top3_precision","share_of_all_actual_top3_captured","actual_top5","actual_top5_precision"),[dict(rank_scope=f"Top{k}",**v) for k,v in top.items()])
 return summary
if __name__=="__main__":print(json.dumps(run(),ensure_ascii=False,indent=2,default=lambda x:dict(x)))
