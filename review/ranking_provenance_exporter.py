"""Additive PRE_RACE Ranking Provenance exporter; never calculates weights."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_VERSION = "ranking_provenance_v1"
EXPECTED_EVALUATORS = {
    "Bloodline":"bloodline_score", "PastPerformance":"past_performance_score", "PaceStyle":"pace_style_score",
    "Distance":"distance_score", "TrackCondition":"track_condition_score", "RaceShape":"shape_score",
    "CourseShape":"course_shape_score", "TrackBias":"track_bias_score", "LapSuitability":"lap_score",
}
RESULT_FIELDS = {"actual_finish","finish_position","actual_top3","actual_top5","result","payout","odds"}
SUMMARY_FIELDS = ("race_id","race_date","racecourse","race_number","horse_name","horse_number","final_score","adjusted_score","rank_before","rank_after","saved_ai_rank","rank_after_matches_saved_ai_rank","ranking_score_source","fallback_used","fallback_reason","tie_break_rule","top5_boundary_tie","weight_calculation_version","provenance_complete","trace_count","source_version","source_file","source_sha256","pipeline_version")
LONG_FIELDS = ("race_id","horse_name","horse_number","evaluator_name","raw_score","weight","weighted_contribution","weight_reason","weight_reason_status","weight_status","missing_fields","reason_code","source_field","calculation_version","source_file","source_sha256","pipeline_version")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value):
    try:return float(value)
    except (TypeError,ValueError):return None


def rank_map(rows,field):
    usable=[row for row in rows if number(row.get(field)) is not None]
    ordered=sorted(usable,key=lambda row:(-number(row[field]),-(int(row.get("horse_number") or 0))))
    return {id(row):index for index,row in enumerate(ordered,1)},ordered


def ranking_value(row):
    for field in ("adjusted_score","integrated_score","weighted_score","final_score"):
        if number(row.get(field)) is not None:return number(row[field]),field
    return None,"NONE"


def ranking_rank_map(rows):
    usable=[row for row in rows if ranking_value(row)[0] is not None]
    ordered=sorted(usable,key=lambda row:(-ranking_value(row)[0],-(int(row.get("horse_number") or 0))))
    return {id(row):index for index,row in enumerate(ordered,1)},ordered


def _write_csv(path,fields,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction="ignore");writer.writeheader();writer.writerows(rows)


def write_weight_source(rows,output_dir,race_date,source_version,source_file,pipeline_version=PIPELINE_VERSION):
    """Persist upstream evidence exactly as supplied; never calculate weights."""
    source_file=Path(source_file);source_hash=sha256(source_file);records=[]
    for row in rows:
        if str(row.get("race_date"))!=str(race_date):raise ValueError("MIXED_RACE_DATE_PROHIBITED")
        if str(row.get("source_version",source_version))!=str(source_version):raise ValueError("MIXED_SOURCE_VERSION_PROHIBITED")
        if str(row.get("pipeline_version",pipeline_version))!=str(pipeline_version):raise ValueError("MIXED_PIPELINE_VERSION_PROHIBITED")
        records.append({"race_id":row.get("race_id",""),"horse_name":row.get("horse_name",""),"horse_number":str(row.get("horse_number","")),"race_date":str(race_date),"source_version":source_version,"pipeline_version":pipeline_version,"score_weight_provenance_version":row.get("score_weight_provenance_version",""),"evaluator_provenance":row.get("evaluator_provenance",[])})
    race_ids=sorted({str(row.get("race_id","")) for row in records})
    if not race_ids:raise ValueError("WEIGHT_SOURCE_REQUIRES_RACE")
    race_label=race_ids[0] if len(race_ids)==1 else "batch"
    race_token="".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in race_label)
    payload={"artifact_type":"RANKING_WEIGHT_SOURCE","score_weight_provenance_version":"SWP_V1","race_id":race_ids[0] if len(race_ids)==1 else "MULTI_RACE_BATCH","race_ids":race_ids,"race_date":str(race_date),"source_version":source_version,"pipeline_version":pipeline_version,"source_file":str(source_file),"source_sha256":source_hash,"created_at":datetime.now(timezone.utc).isoformat(),"result_data_used_as_evaluation_input":"NO","records":records}
    path=Path(output_dir)/"source"/f"ranking_weight_source_{race_date}_{race_token}_swp_v1.json";path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise FileExistsError(f"RANKING_WEIGHT_SOURCE_ALREADY_EXISTS:{path}")
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return path


def _load_weight_source(path,race_date,source_version,pipeline_version):
    payload=json.loads(Path(path).read_text(encoding="utf-8"))
    if str(payload.get("race_date"))!=str(race_date):raise ValueError("PROVENANCE_SOURCE_DATE_MISMATCH")
    if str(payload.get("source_version"))!=str(source_version):raise ValueError("PROVENANCE_SOURCE_VERSION_MISMATCH")
    if str(payload.get("pipeline_version"))!=str(pipeline_version):raise ValueError("PROVENANCE_PIPELINE_VERSION_MISMATCH")
    records=payload.get("records",[])
    for row in records:
        if str(row.get("race_date"))!=str(race_date):raise ValueError("MIXED_PROVENANCE_SOURCE_DATE")
        if str(row.get("source_version"))!=str(source_version):raise ValueError("MIXED_PROVENANCE_SOURCE_VERSION")
        if str(row.get("pipeline_version"))!=str(pipeline_version):raise ValueError("MIXED_PROVENANCE_PIPELINE_VERSION")
    return {(str(row.get("race_id","")),str(row.get("horse_name","")),str(row.get("horse_number",""))):row for row in records}


def export(rows,output_dir,race_date,source_version,source_file,pipeline_version=PIPELINE_VERSION,provenance_source_file=None):
    rows=[dict(row) for row in rows]
    if not rows:raise ValueError("EMPTY_PRE_RACE_INPUT")
    if any(RESULT_FIELDS.intersection(row) for row in rows):raise ValueError("RESULT_FIELDS_PROHIBITED_IN_PRE_RACE_INPUT")
    source_file=Path(source_file);source_hash=sha256(source_file)
    provenance_map=_load_weight_source(provenance_source_file,race_date,source_version,pipeline_version) if provenance_source_file else None
    race_groups={}
    for row in rows:
        if str(row.get("race_date"))!=str(race_date):raise ValueError("MIXED_RACE_DATE_PROHIBITED")
        if str(row.get("source_version",source_version))!=str(source_version):raise ValueError("MIXED_SOURCE_VERSION_PROHIBITED")
        race_groups.setdefault(row["race_id"],[]).append(row)
    summaries=[];long_rows=[]
    for race_id,group in race_groups.items():
        before,_=rank_map(group,"final_score");after,ordered=ranking_rank_map(group)
        boundary_tie=len(ordered)>=6 and ranking_value(ordered[4])[0]==ranking_value(ordered[5])[0]
        for row in group:
            join_key=(str(race_id),str(row.get("horse_name","")),str(row.get("horse_number","")))
            joined_source=(provenance_map.get(join_key) if all(join_key) else None) if provenance_map is not None else row
            supplied={item.get("evaluator_name"):item for item in (joined_source or {}).get("evaluator_provenance",[]) if isinstance(item,dict)}
            horse_long=[]
            for evaluator,field in EXPECTED_EVALUATORS.items():
                item=supplied.get(evaluator,{})
                raw=item.get("raw_score","");weight=item.get("weight","");contribution=item.get("weighted_contribution","")
                reason=item.get("weight_reason","");version=item.get("calculation_version","")
                missing=item.get("missing_fields",[name for name,value in (("raw_score",raw),("weight",weight),("weighted_contribution",contribution),("calculation_version",version)) if value in (None,"")])
                status=item.get("weight_status","COMPLETE" if not missing else "TRACE")
                reason_code="PROVENANCE_SOURCE_NOT_FOUND" if joined_source is None else ("ALL_PROVENANCE_FIELDS_SAVED" if status=="COMPLETE" else "SOURCE_PROVENANCE_INCOMPLETE_NO_INFERENCE")
                horse_long.append({"race_id":race_id,"horse_name":row.get("horse_name",""),"horse_number":row.get("horse_number",""),"evaluator_name":evaluator,"raw_score":raw,"weight":weight,"weighted_contribution":contribution,"weight_reason":reason,"weight_reason_status":item.get("weight_reason_status","NOT_EXPOSED" if not reason else "EXPOSED"),"weight_status":status,"missing_fields":";".join(missing),"reason_code":reason_code,"source_field":item.get("source_field",field),"calculation_version":version,"source_file":str(provenance_source_file or source_file),"source_sha256":sha256(Path(provenance_source_file)) if provenance_source_file else source_hash,"pipeline_version":pipeline_version})
            long_rows.extend(horse_long)
            trace_count=sum(item["weight_status"]=="TRACE" for item in horse_long)
            score_value,score_source=ranking_value(row);fallback=score_source!="adjusted_score"
            fallback_reason="ADJUSTED_SCORE_MISSING" if fallback else ""
            saved_rank=int(row["ai_rank"]) if str(row.get("ai_rank","")).isdigit() else ""
            calculated_after=after.get(id(row),"")
            summaries.append({"race_id":race_id,"race_date":race_date,"racecourse":row.get("racecourse",race_id.split("_")[2]),"race_number":row.get("race_number",race_id.split("_")[3]),"horse_name":row.get("horse_name",""),"horse_number":row.get("horse_number",""),"final_score":row.get("final_score",""),"adjusted_score":row.get("adjusted_score",""),"rank_before":before.get(id(row),""),"rank_after":calculated_after,"saved_ai_rank":saved_rank,"rank_after_matches_saved_ai_rank":bool(calculated_after and saved_rank and calculated_after==saved_rank),"ranking_score_source":score_source,"fallback_used":fallback,"fallback_reason":fallback_reason,"tie_break_rule":"score DESC -> horse_number DESC","top5_boundary_tie":boundary_tie,"weight_calculation_version":row.get("weight_calculation_version",""),"provenance_complete":trace_count==0 and not fallback and bool(calculated_after),"trace_count":trace_count,"source_version":source_version,"source_file":str(source_file),"source_sha256":source_hash,"pipeline_version":pipeline_version})
    output_dir=Path(output_dir);race_token=""
    if len(race_groups)==1:
        only_race=next(iter(race_groups));race_token="_"+"".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(only_race))
    stem=f"ranking_provenance_{race_date}_{source_version}{race_token}_v1"
    summary_path=output_dir/f"{stem}.csv";long_path=output_dir/f"{stem}_evaluator_long.csv"
    manifest_path=output_dir/f"{stem}_manifest.json"
    existing=[path for path in (summary_path,long_path,manifest_path) if path.exists()]
    if existing:raise FileExistsError("RANKING_PROVENANCE_ARTIFACT_ALREADY_EXISTS:"+",".join(str(path) for path in existing))
    _write_csv(summary_path,SUMMARY_FIELDS,summaries);_write_csv(long_path,LONG_FIELDS,long_rows)
    manifest={"pipeline_version":pipeline_version,"race_date":race_date,"source_version":source_version,"source_file":str(source_file),"source_sha256":source_hash,"summary_file":str(summary_path),"summary_sha256":sha256(summary_path),"evaluator_long_file":str(long_path),"evaluator_long_sha256":sha256(long_path),"race_count":len(race_groups),"horse_count":len(summaries),"provenance_complete_count":sum(row["provenance_complete"] for row in summaries),"trace_count":sum(int(row["trace_count"]) for row in summaries),"top5_boundary_tie_count":len({row["race_id"] for row in summaries if row["top5_boundary_tie"]}),"result_data_used_as_evaluation_input":"NO"}
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {"summary_path":summary_path,"long_path":long_path,"manifest_path":manifest_path,"summary_rows":summaries,"long_rows":long_rows,"manifest":manifest}


def update_ledger(path,manifest):
    from review.ranking_provenance_ledger import register_pre
    return register_pre(path,manifest)
