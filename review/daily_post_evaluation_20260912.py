"""Frozen 2026-09-12 Daily PRE -> POST review (Current/V4/CF only)."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from review.target_daily_result_list_schema_v2_validator import validate_source_pair

DATE="20260912"
PRE=ROOT/"reports/daily_pre_prediction_20260912"
OUT=ROOT/"reports/daily_post_evaluation_20260912"
RAW=ROOT/"data/raw/target/daily_result_list"
PRIMARY=RAW/f"馬番順着順_{DATE}.csv"
AUX=RAW/f"着順馬番_{DATE}.csv"
EXPECTED_PRE_INDEX_SHA="651eef9a70eabde153016dac1519fb9d94759866334b06df509fef4af08430fe"
ABNORMAL={"中止","除外","取消","失格"}
VENUE_KEY={"hanshin":"阪神","nakayama":"中山"}


def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(name:str,value:object)->None:(OUT/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def read_csv(path:Path,encoding="utf-8-sig"):
    with path.open(encoding=encoding,newline="") as f:return list(csv.DictReader(f))
def write_csv(name:str,rows:list[dict],fields:list[str]):
    with (OUT/name).open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)


def verify_pre()->tuple[dict,dict[str,str]]:
    if sha(PRE/"artifact_hash_index.json")!=EXPECTED_PRE_INDEX_SHA:raise RuntimeError("PRE_ARTIFACT_INDEX_SHA_MISMATCH")
    index=json.loads((PRE/"artifact_hash_index.json").read_text(encoding="utf-8"))["artifacts"]
    before={}
    bad=[]
    for item in index:
        rel=item["path"].replace("\\","/"); path=PRE/Path(rel)
        actual=sha(path) if path.is_file() else None;before[rel]=actual
        if actual!=item["sha256"] or (actual is not None and path.stat().st_size!=item["byte_size"]):bad.append(rel)
    required={"report.md","race_summary.md","current_predictions.csv","v4_predictions.csv","cf_top3_rank_anchored_predictions.csv","all_ai_runner_matrix.csv","model_disagreement_cases.csv"}
    if bad or not required<=set(before):raise RuntimeError(f"PRE_ARTIFACT_INTEGRITY_FAIL:{bad}:{sorted(required-set(before))}")
    safety=json.loads((PRE/"safety.json").read_text(encoding="utf-8"))
    boundary="PASS" if safety.get("RESULT_ACCESS")==0 and safety.get("ODDS_ACCESS")==0 and safety.get("POPULARITY_ACCESS")==0 else "UNRESOLVED"
    return {"PRE_ARTIFACT_INTEGRITY":"PASS","PRE_ARTIFACT_INDEX_SHA256":EXPECTED_PRE_INDEX_SHA,
            "verified_artifact_count":len(index),"required_files_verified":sorted(required),
            "PRE_RESULT_BOUNDARY_INTEGRITY":boundary,"pre_created_before_result_files":max((PRE/Path(x)).stat().st_mtime for x in before)<min(PRIMARY.stat().st_mtime,AUX.stat().st_mtime)},before


def read_result_pair()->tuple[dict,dict[tuple[str,int],list[str]],dict]:
    structural=validate_source_pair(PRIMARY,AUX,DATE)
    with PRIMARY.open(encoding="cp932",newline="") as f:p_rows=list(csv.reader(f))
    with AUX.open(encoding="cp932",newline="") as f:a_rows=list(csv.reader(f))
    p={row[0]:row for row in p_rows};a={row[0]:row for row in a_rows}
    if len(p)!=len(p_rows) or len(a)!=len(a_rows) or set(p)!=set(a):raise RuntimeError("STOP_RESULT_SOURCE_MISMATCH")
    records=[]; index={}
    for key in sorted(p):
        pr,ar=p[key],a[key]; head=int(pr[9]); normal=defaultdict(set); abnormal=set()
        for no in range(1,head+1):
            raw=pr[11+no].strip()
            if raw.isdigit() and int(raw)>0:normal[int(raw)].add(no)
            elif raw in ABNORMAL:abnormal.add(no)
            else:raise RuntimeError(f"UNKNOWN_FINISH_STATUS_STOP:{key}:{no}:{raw}")
        ranks=sorted(normal)
        if not ranks or ranks[0]!=1 or any(r!=1+sum(len(normal[x]) for x in ranks if x<r) for r in ranks):raise RuntimeError(f"INVALID_FINISH_RANK_SEQUENCE_STOP:{key}")
        seq=[int(x) for x in ar[12:12+head]]; pos=0; groups=[]
        for rank in ranks:
            group=seq[pos:pos+len(normal[rank])]
            if set(group)!=normal[rank]:raise RuntimeError(f"STOP_RESULT_SOURCE_MISMATCH:{key}:rank{rank}")
            groups.append({"finish":rank,"horse_numbers":sorted(group)});pos+=len(group)
        if set(seq[pos:])!=abnormal:raise RuntimeError(f"STOP_RESULT_SOURCE_MISMATCH:{key}:abnormal_suffix")
        index[(pr[1],int(pr[2]))]=pr
        records.append({"target_race_key":key,"venue":pr[1],"race_number":int(pr[2]),"head_count":head,
                        "normal_finish_groups":groups,"abnormal_horse_numbers":sorted(abnormal),"status":"PASS"})
    return structural,index,{"RESULT_SOURCE_RECONCILIATION":"PASS","primary_path":PRIMARY.relative_to(ROOT).as_posix(),
        "primary_sha256":sha(PRIMARY),"auxiliary_path":AUX.relative_to(ROOT).as_posix(),"auxiliary_sha256":sha(AUX),
        "race_count":len(records),"horse_count":sum(x["head_count"] for x in records),"duplicate_keys":0,"malformed_rows":0,
        "horse_by_horse_group_aware_crosscheck":"PASS","records":records}


def outcome(row:list[str],no:int)->dict:
    raw=row[11+no].strip()
    if raw.isdigit() and int(raw)>0:return {"actual_finish":int(raw),"raw_finish":raw,"valid_result":True,"actual_top3":int(raw)<=3}
    if raw in ABNORMAL:return {"actual_finish":None,"raw_finish":raw,"valid_result":False,"actual_top3":False}
    raise RuntimeError(f"UNKNOWN_FINISH_STATUS_STOP:{raw}")


def race_parts(race_id:str)->tuple[str,int]:
    s=race_id.split("_");return VENUE_KEY[s[-2]],int(s[-1].removesuffix("R"))


def load_frozen(result_index:dict)->tuple[dict,list[dict],list[dict]]:
    current=read_csv(PRE/"current_predictions.csv");v4=read_csv(PRE/"v4_predictions.csv");cf=read_csv(PRE/"cf_top3_rank_anchored_predictions.csv")
    current_sel=[r for r in current if r["CURRENT_BUY"]=="True"]
    v4_sel=[r for r in v4 if r["V4_selected"]=="True"]
    cf_sel=[r for r in cf if r["CF_selected"]=="True"]
    if (len(current_sel),len(v4_sel),len(cf_sel))!=(7,7,6):raise RuntimeError("FROZEN_SELECTION_COUNT_MISMATCH")
    expected_cur={("中山",8,7),("中山",8,4),("中山",9,8),("中山",9,2),("中山",10,3),("中山",11,9),("中山",12,8)}
    expected_v4={("中山",8,8),("中山",8,1),("中山",9,12),("中山",9,8),("中山",10,9),("中山",11,10),("中山",12,12)}
    expected_cf={("阪神",8,5),("阪神",8,11),("阪神",8,12),("阪神",12,6),("阪神",12,5),("阪神",12,16)}
    def identities(rows):return {(r["venue"],int(r["race_number"]),int(r["horse_number"])) for r in rows}
    if identities(current_sel)!=expected_cur or identities(v4_sel)!=expected_v4 or identities(cf_sel)!=expected_cf:raise RuntimeError("FROZEN_SELECTION_IDENTITY_MISMATCH")
    race_payloads={};all_horses=[]
    ridx=json.loads((PRE/"current_frozen/race_index.json").read_text(encoding="utf-8"))["race_index"]
    for item in ridx:
        p=json.loads((PRE/"current_frozen"/item["artifact"]).read_text(encoding="utf-8")); venue,rno=race_parts(p["race_id"]); rr=result_index.get((venue,rno))
        if rr is None:raise RuntimeError(f"RESULT_RACE_MISSING:{p['race_id']}")
        state=p["buy_gate_trace"]["race"]["shadow_race_state"]
        horses=[]
        for h in p["ranked_results"]:
            no=int(h["horse_number"]); rec={"race_id":p["race_id"],"venue":venue,"race_number":rno,"race_state":state,
                "horse_number":no,"horse_name":h["horse_name"],**outcome(rr,no)};horses.append(rec);all_horses.append(rec)
        if len(horses)!=int(rr[9]):raise RuntimeError(f"PRE_RESULT_HEADCOUNT_MISMATCH:{p['race_id']}")
        race_payloads[p["race_id"]]={"venue":venue,"race_number":rno,"race_state":state,"horses":horses}
    def join(rows,lane):
        out=[]
        for r in rows:
            by={h["horse_number"]:h for h in race_payloads[r["race_id"]]["horses"]}; no=int(r["horse_number"])
            if no not in by or by[no]["horse_name"]!=r["horse_name"]:raise RuntimeError(f"SELECTED_IDENTITY_MISMATCH:{lane}:{r['race_id']}:{no}")
            out.append({**by[no],"lane":lane})
        return out
    return race_payloads,join(current_sel,"CURRENT"),join(v4_sel,"V4"),join(cf_sel,"CF")


def metric(rows:list[dict])->dict:
    valid=[r for r in rows if r["valid_result"]];hits=sum(r["actual_top3"] for r in valid)
    return {"selected_N":len(rows),"valid_N":len(valid),"invalid_N":len(rows)-len(valid),"top3_hits":hits,
        "top3_rate":hits/len(valid) if valid else None,"race_hit_count":len({(r["venue"],r["race_number"]) for r in valid if r["actual_top3"]})}


def main()->None:
    if OUT.exists():raise RuntimeError("OUTPUT_ALREADY_EXISTS")
    pre_integrity,pre_before=verify_pre()
    OUT.mkdir(parents=True)
    dump("pre_artifact_integrity.json",pre_integrity)
    structural,result_index,reconciliation=read_result_pair();dump("result_source_reconciliation.json",{**reconciliation,"structural_validation":structural})
    races,current,v4,cf=load_frozen(result_index)
    cm,vm,cfm=metric(current),metric(v4),metric(cf)
    dump("current_metrics.json",cm);dump("v4_metrics.json",vm);dump("cf_metrics.json",cfm)
    selected_map=defaultdict(lambda:{"CURRENT":False,"V4":False,"CF":False})
    detail={}
    for lane,rows in (("CURRENT",current),("V4",v4),("CF",cf)):
        for r in rows:key=(r["race_id"],r["horse_number"]);selected_map[key][lane]=True;detail[key]=r
    selected=[]
    for key in sorted(detail):
        r=detail[key]; s=selected_map[key]
        selected.append({"venue":r["venue"],"race_number":r["race_number"],"race_id":r["race_id"],"horse_number":r["horse_number"],
            "horse_name":r["horse_name"],"Current_selected":s["CURRENT"],"V4_selected":s["V4"],"CF_selected":s["CF"],
            "AI_lanes":"+".join(k for k,v in s.items() if v),"actual_finish":r["actual_finish"],"valid_result":r["valid_result"],"actual_top3":r["actual_top3"]})
    write_csv("selected_horse_post.csv",selected,["venue","race_number","race_id","horse_number","horse_name","Current_selected","V4_selected","CF_selected","AI_lanes","actual_finish","valid_result","actual_top3"])
    common={rid for rid,x in races.items() if x["venue"]=="中山" and x["race_number"] in {8,9,10,11,12}}
    c_only=[r for r in current if (r["race_id"],r["horse_number"]) not in {(x["race_id"],x["horse_number"]) for x in v4}]
    v_only=[r for r in v4 if (r["race_id"],r["horse_number"]) not in {(x["race_id"],x["horse_number"]) for x in current}]
    overlap=[r for r in current if (r["race_id"],r["horse_number"]) in {(x["race_id"],x["horse_number"]) for x in v4}]
    disagreement=[]
    for group,rows in (("CURRENT_ONLY",c_only),("V4_ONLY",v_only),("OVERLAP",overlap)):
        for r in rows:disagreement.append({"group":group,**r})
    write_csv("model_disagreement_post.csv",disagreement,["group","venue","race_number","race_id","horse_number","horse_name","actual_finish","valid_result","actual_top3"])
    common_summary={"label":"DAILY_COMMON_SCOPE_COMPARISON_ONLY","race_count":len(common),"Current":cm,"V4":vm,
        "V4_minus_Current_hits":vm["top3_hits"]-cm["top3_hits"],"V4_minus_Current_rate_pt":(vm["top3_rate"]-cm["top3_rate"])*100,
        "Current_only":{"selected_N":len(c_only),"top3_hits":sum(r["actual_top3"] for r in c_only if r["valid_result"])},
        "V4_only":{"selected_N":len(v_only),"top3_hits":sum(r["actual_top3"] for r in v_only if r["valid_result"])},
        "overlap":{"selected_N":len(overlap),"top3_hits":sum(r["actual_top3"] for r in overlap if r["valid_result"]),"horses":overlap}}
    dump("current_vs_v4_common_scope.json",common_summary)
    race_rows=[];skip_rows=[]
    for rid,x in sorted(races.items(),key=lambda z:(z[1]["venue"],z[1]["race_number"])):
        cs=[r for r in current if r["race_id"]==rid];vs=[r for r in v4 if r["race_id"]==rid];fs=[r for r in cf if r["race_id"]==rid]
        top=[h for h in x["horses"] if h["valid_result"] and h["actual_top3"]]
        rec={"venue":x["venue"],"race_number":x["race_number"],"race_id":rid,"race_state":x["race_state"],
            "Current_selections":"; ".join(f"#{r['horse_number']} {r['horse_name']}" for r in cs),"Current_top3_hits":sum(r["actual_top3"] for r in cs if r["valid_result"]),
            "V4_selections":"; ".join(f"#{r['horse_number']} {r['horse_name']}" for r in vs),"V4_top3_hits":sum(r["actual_top3"] for r in vs if r["valid_result"]),
            "CF_selections":"; ".join(f"#{r['horse_number']} {r['horse_name']}" for r in fs),"CF_top3_hits":sum(r["actual_top3"] for r in fs if r["valid_result"]),
            "official_top3_horses":"; ".join(f"#{r['horse_number']} {r['horse_name']}({r['actual_finish']}着)" for r in top),
            "notes":"No model miss statistic" if x["race_state"]=="SKIP" else "DAILY_PRE_POST_OBSERVATION_ONLY"}
        race_rows.append(rec)
        if x["race_state"]=="SKIP":skip_rows.append(rec)
    fields=["venue","race_number","race_id","race_state","Current_selections","Current_top3_hits","V4_selections","V4_top3_hits","CF_selections","CF_top3_hits","official_top3_horses","notes"]
    write_csv("race_level_post.csv",race_rows,fields);write_csv("skip_race_context.csv",skip_rows,fields)
    agreement=overlap[0] if len(overlap)==1 else None
    cf_by_race={(r["venue"],r["race_number"]):any(x["actual_top3"] for x in cf if x["venue"]==r["venue"] and x["race_number"]==r["race_number"] and x["valid_result"]) for r in cf}
    dump("result_join_audit.json",{"status":"PASS","pre_races":len(races),"pre_horses":sum(len(x["horses"]) for x in races.values()),
        "selected_unique_horses":len(selected),"selected_lane_records":len(current)+len(v4)+len(cf),"missing_races":0,"missing_horses":0,
        "duplicate_selected_keys":0,"invalid_selected_horses":sum(not r["valid_result"] for r in current+v4+cf)})
    pre_after={rel:sha(PRE/Path(rel)) for rel in pre_before}
    bad=[rel for rel in pre_before if pre_before[rel]!=pre_after[rel]]
    if bad:raise RuntimeError(f"PRE_ARTIFACT_ZERO_DELTA_FAIL:{bad}")
    safety={"RESULT_ACCESS":1,"RESULT_ACCESS_AFTER_PRE_INTEGRITY":True,"ODDS_ACCESS":0,"POPULARITY_ACCESS":0,"MODEL_TRAINING":0,"MODEL_REFIT":0,
        "THRESHOLD_CHANGE":0,"CANDIDATE_K_CHANGE":0,"CURRENT_CHANGE":0,"V4_CHANGE":0,"CF_CHANGE":0,"V3_CHANGE":0,"STAGE_B_CHANGE":0,
        "PRODUCTION_CHANGE":0,"LEDGER_CHANGE":0,"FINGERPRINT_CHANGE":0,"GIT_COMMIT":0,"GIT_PUSH":0,"PRE_ARTIFACT_ZERO_DELTA":"PASS","pre_mutations":bad}
    dump("safety.json",safety)
    lines=["# 2026-09-12 Daily PRE → POST Review","","`EVIDENCE_ROLE = DAILY_PRE_POST_OBSERVATION_ONLY`","",
        f"- Current: {cm['top3_hits']}/{cm['valid_N']} = {cm['top3_rate']:.2%}; race hits {cm['race_hit_count']}.",
        f"- V4（同一中山5R scope）: {vm['top3_hits']}/{vm['valid_N']} = {vm['top3_rate']:.2%}; race hits {vm['race_hit_count']}.",
        f"- CF（阪神8R・12Rのみ）: {cfm['top3_hits']}/{cfm['valid_N']} = {cfm['top3_rate']:.2%}; race hits {cfm['race_hit_count']}.",
        f"- Current/V4差: {vm['top3_hits']-cm['top3_hits']:+d} hits / {(vm['top3_rate']-cm['top3_rate'])*100:+.2f}pt.",
        f"- Agreement: 中山9R #8 ミーントゥビー → {agreement['actual_finish']}着 / Top3={'YES' if agreement['actual_top3'] else 'NO'}.",
        f"- 阪神8R CF Top3 capture: {'YES' if cf_by_race.get(('阪神',8)) else 'NO'}.",f"- 阪神12R CF Top3 capture: {'YES' if cf_by_race.get(('阪神',12)) else 'NO'}.","","## Frozen selected horse results","",
        "| Race | Horse | AI lane(s) | Finish | Top3 |","|---|---|---|---:|---|"]
    lines += [f"| {r['venue']}{r['race_number']}R | #{r['horse_number']} {r['horse_name']} | {r['AI_lanes']} | {r['actual_finish'] if r['valid_result'] else r['raw_finish'] if 'raw_finish' in r else 'INVALID'} | {'YES' if r['actual_top3'] else 'NO'} |" for r in selected]
    (OUT/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    names=sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hash_index.json")
    dump("artifact_hash_index.json",{"indexed_artifacts":{n:{"sha256":sha(OUT/n),"size":(OUT/n).stat().st_size} for n in names},"self_hash_excluded":True,
        "generated_at":datetime.now(timezone.utc).isoformat()})


if __name__=="__main__":main()
