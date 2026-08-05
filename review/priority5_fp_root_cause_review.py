"""Formal BASELINE_34 freeze and read-only severe-FP root-cause review."""
from __future__ import annotations
import csv, hashlib, json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; B=ROOT/"reports"/"baseline"; R=ROOT/"reports"
MISSING=(
 "race_20260725_chuukyou_10R","race_20260725_niigata_12R","race_20260725_sapporo_10R",
 "race_20260726_chuukyou_10R","race_20260726_niigata_5R")
def load(p):
 with p.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def write_csv(p,fields,rows):
 with p.open("w",encoding="utf-8-sig",newline="") as f:w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def yes(v):return str(v).lower()=="true"
def source_rows():
 out={}
 for p in (R/"review_20260725"/"horse_review.csv",R/"review_20260726"/"horse_review.csv",R/"review_20260801"/"horse_review_20260801_v2.csv",R/"review_20260802"/"horse_review_20260802_v1.csv"):
  for x in load(p):out[(x.get("race_id",""),x.get("horse_number",""))]=(x,p)
 return out
def classify(row, detail):
 date=row["race_date"]; secondary=[]
 if date=="20260725": primary="DATA_QUALITY_OR_TRACE";secondary.append("LEGACY_GATE_TRACE_MISSING")
 elif date=="20260726": primary="HIGH_CONFIDENCE_SEVERE_MISS";secondary.append("ALL_GATES_CLEAR_OR_SUFFICIENT_MARGIN")
 elif date=="20260801": primary="DATA_QUALITY_OR_TRACE";secondary.append("DETAILED_GATE_MARGIN_MISSING")
 else: primary="DATA_QUALITY_OR_TRACE";secondary.extend(("BLOODLINE_MISSING","INPUT_LIMITATION"))
 return primary,";".join(secondary)
def run():
 races=load(B/"keibaai_baseline_4days_v1_race.csv");horses=load(B/"keibaai_baseline_4days_v1_horse.csv");fp=load(R/"priority5_fp_candidate_cohort_v1.csv"); src=source_rows()
 buys=[x for x in horses if yes(x["buy_flag"])]; valid=[x for x in buys if yes(x["valid_result"])]; wins=sum(x["actual_finish"]=="1" for x in valid); placed=sum(yes(x["actual_top3"]) for x in valid); top5=sum(yes(x["actual_top5"]) for x in valid)
 invalid=[x for x in buys if not yes(x["valid_result"])]; severe=[]; race_map={x["race_id"]:x for x in races}; counts=Counter(x["race_id"] for x in fp)
 for x in fp:
  if x["fp_severity"]!="SEVERE_MISS":continue
  d,p=src[(x["race_id"],x["horse_number"])]; race=race_map[x["race_id"]]; primary,flags=classify(x,d)
  severe.append({**x,"racecourse":race["racecourse"],"race_number":race["race_number"],"absolute_margin":d.get("buy_threshold_gap", ""),"relative_rank":d.get("rank",d.get("ai_rank","")),"relative_gap":d.get("buy_gap_calc", ""),"allowed_gap":d.get("buy_threshold", ""),"relative_margin":d.get("caution_threshold_gap", ""),"positive_evaluator_count":len([z for z in d.get("positive_reasons","").split(";") if z.strip()]),"negative_evaluator_count":len([z for z in d.get("risk_reasons","").split(";") if z.strip()]),"missing_evaluator":"Bloodline" if d.get("bloodline_missing")=="True" else "","consensus_margin":"","RaceDecision":race["RaceDecision"],"RaceState":race["RaceState"],"Confidence":race["Confidence"] or d.get("confidence",""),"track_bias_status":"LIMITED" if "バイアス" in d.get("risk_reasons","") else "UNKNOWN","meeting_bias_status":"DIAGNOSTIC_ONLY_OR_UNKNOWN","bloodline_missing":d.get("bloodline_missing",""),"course_knowledge":"UNKNOWN","primary_classification":primary,"secondary_flags":flags+(";RACE_LEVEL_CLUSTER" if counts[x["race_id"]]>1 else ""),"source_path":str(p.relative_to(ROOT)),"source_sha256":sha(p)})
 coverage=[]
 date_counts=Counter(x["race_date"] for x in races)
 for d in ("20260725","20260726","20260801","20260802"):coverage.append({"race_date":d,"included_races":date_counts[d],"coverage_status":"INCLUDED_SAVED_REVIEW"})
 for rid in MISSING:coverage.append({"race_date":rid[5:13],"race_id":rid,"included_races":0,"coverage_status":"EXCLUDED","reason":"REVIEW_SOURCE_MISSING;ANALYSIS_AND_RESULT_ONLY;NO_SAVED_PRE_RACE_OR_REVIEW;PRODUCTION_REPLAY_PROHIBITED","limitation":"4 of 5 are race 10R or later; possible late-race/top-class bias"})
 write_csv(B/"baseline_34_race_v1_coverage.csv",("race_date","race_id","included_races","coverage_status","reason","limitation"),coverage)
 fields=("race_id","race_date","racecourse","race_number","horse_name","horse_number","ai_rank","actual_finish","final_score","adjusted_score","decision_score","absolute_margin","relative_rank","relative_gap","allowed_gap","relative_margin","positive_evaluator_count","negative_evaluator_count","missing_evaluator","consensus_margin","RaceDecision","RaceState","Confidence","track_bias_status","meeting_bias_status","bloodline_missing","course_knowledge","primary_classification","secondary_flags","source_path","source_sha256")
 write_csv(R/"priority5_fp_classification_v1.csv",fields,severe);write_csv(R/"priority5_fp_gate_margin_v1.csv",fields,severe)
 controls=[{"candidate":"HIGH_CONFIDENCE_CLEAR_GATE_20260726","fp_reducible":4,"lost_successful_buy":"UNDETERMINED","remaining_buy":36,"buy_race_rate_after":"UNDETERMINED","place_rate_change":"UNDETERMINED","status":"HOLD_NO_PRERACE_DISCRIMINATOR_AND_SINGLE_DAY"}]
 write_csv(R/"priority5_fp_control_comparison_v1.csv",("candidate","fp_reducible","lost_successful_buy","remaining_buy","buy_race_rate_after","place_rate_change","status"),controls)
 source_manifest=json.load(open(B/"keibaai_baseline_4days_v1_sources.json",encoding="utf-8")); hashes=json.load(open(B/"keibaai_baseline_4days_v1_manifest.json",encoding="utf-8"))["hashes"]
 manifest={"baseline_name":"BASELINE_34_RACE_v1","status":"COMPLETE_WITH_COVERAGE_LIMITATION","dates":list(date_counts),"race_count":len(races),"horse_count":len(horses),"date_race_counts":date_counts,"date_coverage_rate":{"20260725":"9/12","20260726":"9/11","20260801":"8/8","20260802":"8/8"},"missing_race_ids":list(MISSING),"missing_reason":"REVIEW_SOURCE_MISSING / ANALYSIS_AND_RESULT_ONLY / production replay prohibited","source_manifest":source_manifest,"hashes":hashes}
 (B/"baseline_34_race_v1_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 kpi={"buy_total":len(buys),"valid_result_buy":len(valid),"invalid_result_buy":len(invalid),"invalid_result_buy_rows":invalid,"buy_win":wins,"buy_top3":placed,"buy_top5":top5,"fp_count":len(fp),"official_buy_place_rate":round(100*placed/len(valid),2),"phase0_unadjusted_rate":round(100*placed/len(buys),2),"buy_race_count":len({x['race_id'] for x in buys}),"buy_race_rate":round(100*len({x['race_id'] for x in buys})/len(races),2),"average_buy_per_race":round(len(buys)/len(races),3),"buy0_race_rate":round(100*(len(races)-len({x['race_id'] for x in buys}))/len(races),2),"projected_buy_per_40_races":round(40*len(buys)/len(races),2)}
 (B/"baseline_34_race_v1_kpi.json").write_text(json.dumps(kpi,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 summary={"status":"PRIORITY5_PHASE1_HOLD","baseline_status":manifest["status"],"fp_count":len(fp),"severity":Counter(x["fp_severity"] for x in fp),"severe_primary":Counter(x["primary_classification"] for x in severe),"homogeneous_subgroup":"HIGH_CONFIDENCE_SEVERE_MISS:4 on 20260726","shadow_candidate":False,"shadow_spec_created":False,"priority5_judgment":"HOLD","hold_reasons":["subgroup is single-day/track concentrated","no pre-race discriminator separates successful BUY controls","lost successful BUY cannot be bounded","ranking quality remains RANKING_QUALITY_WATCH"],"ranking_status":"RANKING_QUALITY_WATCH","unconverged_status":"HOLD; LATEST 3 races/14 horses; ADJUSTED_GAP; FN +1 FP +2 ROI -1"}
 (R/"priority5_fp_summary_v1.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 return manifest,kpi,summary,severe
if __name__=="__main__":print(json.dumps(run()[:3],ensure_ascii=False,indent=2,default=dict))
