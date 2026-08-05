"""POST_RACE join for immutable PRE_RACE UNCONVERGED evidence."""
from __future__ import annotations
import csv,hashlib,json
from pathlib import Path
GUARDS=("TOP_CLUSTER_DUAL_SEPARATION","MULTI_GATE_SUPPORT_FLOOR","TRACE_COMPLETENESS_AND_RACE_SUPPORT")
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p,enc="utf-8-sig"):
 with Path(p).open(encoding=enc,newline="") as f:return list(csv.DictReader(f))
def evaluate(pre_race_file,result_dir,output_file):
 pre_race_file,result_dir,output_file=map(Path,(pre_race_file,result_dir,output_file));rows=read(pre_race_file);out=[]
 for row in rows:
  p=result_dir/f"horse_{row['race_id'][5:]}_result.csv";results=read(p,"cp932");hit=next((x for x in results if str(x.get("馬番","")).strip()==str(row["horse_number"]).strip()),{})
  try:finish=int(hit.get("確定着順",0))
  except:finish=0
  valid=finish>0 and str(hit.get("異常コード","0")).strip() in {"","0"};joined=dict(row);joined.update({"actual_finish":finish,"actual_top3":valid and finish<=3,"actual_top5":valid and finish<=5,"valid_result":valid,"invalid_result_reason":"" if valid else f"finish={finish};abnormal={hit.get('異常コード','')}","pre_race_sha256":sha(pre_race_file)})
  for g in GUARDS:
   selected=str(row.get(f"{g}_selected","")).lower()=="true";joined[f"{g}_FN_recovered"]=selected and valid and finish<=3;joined[f"{g}_FP_added"]=selected and valid and finish>=4;joined[f"{g}_Top5_added"]=selected and valid and finish<=5
  out.append(joined)
 output_file.parent.mkdir(parents=True,exist_ok=True);fields=list(out[0])
 with output_file.open("w",encoding="utf-8-sig",newline="") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
 eligible=[x for x in out if str(x.get("guard_eligible","")).lower()=="true"]
 summary={"pre_race_sha256":sha(pre_race_file),"race_count":len({x['race_id'] for x in out}),"candidate_count":len(eligible),"detected_candidate_count":len(out),"valid_candidate_count":sum(bool(x['valid_result']) for x in eligible),"guards":{},"per_race":{}}
 for g in GUARDS:
  selected=sum(str(x.get(f"{g}_selected","")).lower()=="true" for x in out);fn=sum(bool(x[f"{g}_FN_recovered"]) for x in out);fp=sum(bool(x[f"{g}_FP_added"]) for x in out);summary["guards"][g]={"selected_count":selected,"FN":fn,"FP":fp,"ROI":fn-fp,"Top5":sum(bool(x[f"{g}_Top5_added"]) for x in out)}
 for rid in sorted({x["race_id"] for x in out}):
  race_rows=[x for x in out if x["race_id"]==rid];race_eligible=[x for x in race_rows if str(x.get("guard_eligible","")).lower()=="true"]
  race={"race_id":rid,"race_date":race_rows[0].get("race_date",""),"racecourse":race_rows[0].get("racecourse",""),"candidate_count":len(race_eligible),"detected_candidate_count":len(race_rows),"valid_candidate_count":sum(bool(x["valid_result"]) for x in race_eligible),"absolute_pass_count":sum(x.get("absolute_status")=="PASS" for x in race_rows),"relative_pass_count":sum(x.get("relative_status")=="PASS" for x in race_rows),"consensus_pass_count":sum(x.get("consensus_status")=="PASS" for x in race_rows),"trace_count":sum(x.get("trace_status")=="COMPLETE" for x in race_rows),"guards":{}}
  for g in GUARDS:
   chosen=[x for x in race_rows if str(x.get(f"{g}_selected","")).lower()=="true"];fn=sum(bool(x[f"{g}_FN_recovered"]) for x in chosen);fp=sum(bool(x[f"{g}_FP_added"]) for x in chosen)
   reasons={}
   for x in chosen:
    reason=x.get(f"{g}_selection_reason") or "UNSPECIFIED";reasons[reason]=reasons.get(reason,0)+1
   race["guards"][g]={"selected_count":len(chosen),"FN":fn,"FP":fp,"Top5":sum(bool(x[f"{g}_Top5_added"]) for x in chosen),"ROI":fn-fp,"selected_horses":[x["horse_name"] for x in chosen],"selection_reason_counts":reasons}
  summary["per_race"][rid]=race
 output_file.with_suffix(".json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");return summary
if __name__=="__main__":print(json.dumps(evaluate("reports/shadow_unconverged/pre_race/unconverged_shadow_pre_race_20260802_v1.csv","data/results","reports/shadow_unconverged/post_race/unconverged_shadow_post_race_20260802_v1.csv"),ensure_ascii=False,indent=2))
