"""Recompute LATEST gate evidence from saved pre-race fields and production thresholds."""
from __future__ import annotations
import csv,json
from pathlib import Path

TH={"decision":0.80,"final":130.0,"adjusted":145.0,"rank":5,"positive":5,"negative":1}
SCORES={"Ability":(("ability_score",),120),"PastPerformance":(("past_performance_score",),55),"Distance":(("distance_score",),30),"CourseShape":(("course_shape_score",),5),"LapSuitability":(("lap_score",),0),"RaceShape":(("race_shape_score",),0),"PaceStyle":(("pace_style_score",),10)}
OPTIONAL_MISSING={"Ability"}
def num(v):
 try:return float(v)
 except (TypeError,ValueError):return None
def load(path):
 with path.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def status(v):return "PASS" if v else "FAIL"
def recompute(group):
 top=max(num(x.get("adjusted_score")) or -1e9 for x in group);out=[]
 for x in group:
  ds,fs,adj,rank=map(num,(x.get("decision_score"),x.get("final_score"),x.get("adjusted_score"),x.get("ai_rank")))
  absolute=all((ds is not None and ds>=TH["decision"],fs is not None and fs>=TH["final"],adj is not None and adj>=TH["adjusted"]))
  relative=rank is not None and rank<=TH["rank"] and adj is not None and top-adj<=max(35.0,top*0.22)
  positive=negative=0;missing=[]
  for name,(keys,threshold) in SCORES.items():
   value=next((num(x.get(k)) for k in keys if num(x.get(k)) is not None),None)
   if value is None:missing.append(name)
   elif value<0:negative+=1
   elif value>=threshold:positive+=1
  blocking=[m for m in missing if m not in OPTIONAL_MISSING]
  consensus=positive>=TH["positive"] and negative<=TH["negative"] and not blocking
  out.append((x,status(absolute),status(relative),status(consensus),positive,negative,";".join(missing),";".join(blocking)))
 return out
def run(root=Path(".")):
 root=Path(root);trace=load(root/"reports"/"unconverged_primary_trace_v1.csv");latest=[x for x in trace if x["cohort"].startswith("LATEST_")]
 source=load(root/"reports"/"review_20260802"/"horse_review_20260802_v1.csv");idx={(x["race_id"],x["horse_name"]):x for x in source};groups={}
 for t in latest:
  s=idx[(t["race_id"],t["horse_name"])];groups.setdefault(t["race_id"],[]).append(s)
 calc={}
 for group in groups.values():
  for x,a,r,c,p,n,m,b in recompute(group):calc[(x["race_id"],x["horse_name"])]=(a,r,c,p,n,m,b)
 repaired=[];diff=[]
 for t in latest:
  row=dict(t);a,r,c,p,n,m,b=calc[(t["race_id"],t["horse_name"])]
  for field,new in (("absolute_status",a),("relative_status",r),("consensus_status",c)):
   if row.get(field,"")!=new:diff.append({"race_id":row["race_id"],"horse_name":row["horse_name"],"field":field,"before":row.get(field,""),"after":new})
   row[field]=new
  row.update({"absolute_pass":str(a=="PASS"),"relative_pass":str(r=="PASS"),"consensus_pass":str(c=="PASS"),"positive_evaluator_count":p,"negative_evaluator_count":n,"missing_evaluators":m,"blocking_missing_evaluators":b,"evidence_repair":"PRODUCTION_THRESHOLDS_SAVED_PRERACE_FIELDS"});repaired.append(row)
 out=root/"reports";fields=list(repaired[0])
 with (out/"unconverged_primary_trace_latest_repaired_v1.csv").open("w",encoding="utf-8-sig",newline="") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(repaired)
 with (out/"unconverged_primary_trace_latest_diff_v1.csv").open("w",encoding="utf-8-sig",newline="") as f:w=csv.DictWriter(f,fieldnames=("race_id","horse_name","field","before","after"));w.writeheader();w.writerows(diff)
 summary={"status":"EVIDENCE_REPAIRED","original_overwritten":False,"latest_candidates":len(latest),"difference_count":len(diff),"difference_by_field":{f:sum(x["field"]==f for x in diff) for f in ("absolute_status","relative_status","consensus_status")},"thresholds":TH,"result_fields_used_for_gate":False,"all_recomputed_pass":{f:sum(x[f]=="PASS" for x in repaired) for f in ("absolute_status","relative_status","consensus_status")}}
 (out/"unconverged_shadow_evidence_repair_v1.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");return summary
if __name__=="__main__":print(json.dumps(run(),ensure_ascii=False,indent=2))
