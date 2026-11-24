"""Atomic POST for the human-approved narrowed 2026-09-05 scope.

Uses frozen Current/V4/CF selections only; V4 full-Top5 reranking is excluded.
"""
from __future__ import annotations
import csv, hashlib, json
from pathlib import Path
from review.target_daily_result_list_schema_v2_validator import validate_source_pair
from review.cf_top3_rank_anchored_shadow_v1 import append_formal_post_evidence

ROOT=Path(__file__).resolve().parents[1]; DATE="20260905"
PRE=ROOT/f"reports/prospective_prediction_{DATE}_v1"; V4PRE=ROOT/f"reports/v4_model_v3_formal_prospective/{DATE}_pre"
V4OUT=ROOT/f"reports/v4_model_v3_formal_prospective/{DATE}_post"; CFROOT=ROOT/"reports/shadow_cf_top3_rank_anchored_v1"; CFOUT=CFROOT/f"formal_post_{DATE}"
RAW=ROOT/"data/raw/target/daily_result_list"; PRIMARY=RAW/f"馬番順着順_{DATE}.csv"; AUX=RAW/f"着順馬番_{DATE}.csv"
VENUE={"阪神":"hanshin","中山":"nakayama","札幌":"sapporo"}; ABNORMAL={"中止","除外","取消","失格"}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x): p.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def metric(rows):
    valid=[x for x in rows if x["valid_result"]]; hits=sum(x["actual_top3"] for x in valid)
    return {"selected":len(rows),"invalid":len(rows)-len(valid),"valid":len(valid),"hits":hits,"rate":hits/len(valid) if valid else None}
def outcome(row,n):
    raw=row[11+n].strip()
    if raw.isdigit(): f=int(raw); valid=f>0
    elif raw in ABNORMAL: f=0; valid=False
    else: raise RuntimeError(f"INVALID_RESULT_SEMANTICS:{raw}")
    return {"actual_finish":f,"raw_finish":raw,"valid_result":valid,"actual_top3":bool(valid and f<=3)}
def parts(rid): x=rid.split("_"); return x[-2],int(x[-1].removesuffix("R"))
def verify():
    m=json.loads((PRE/"prediction_manifest.json").read_text(encoding="utf-8")); bad=[e["relative_path"] for e in m["files"] if not (PRE/e["relative_path"]).is_file() or sha(PRE/e["relative_path"])!=e["sha256"]]
    h=json.loads((V4PRE/"artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]; badv=[n for n,s in h.items() if not (V4PRE/n).is_file() or sha(V4PRE/n)!=s]
    cf=CFROOT/f"formal_pre_{DATE}.json"
    if bad or badv or not cf.is_file(): raise RuntimeError(f"FROZEN_PRE_INTEGRITY_FAILURE:{bad}:{badv}")
    return {"current_manifest_sha256":sha(PRE/"prediction_manifest.json"),"current_files_verified":len(m["files"]),"v4_files_verified":len(h),"cf_pre_sha256":sha(cf)}
def load_results():
    v=validate_source_pair(PRIMARY,AUX,DATE)
    with PRIMARY.open(encoding="cp932",newline="") as f: rows=list(csv.reader(f))
    idx={(r[1],int(r[2])):r for r in rows}
    if len(idx)!=len(rows): raise RuntimeError("DUPLICATE_RESULT_RACE")
    return v,idx
def main():
    if V4OUT.exists() or CFOUT.exists(): raise RuntimeError("EXCLUSIVE_CREATE_REQUIRED")
    integrity=verify(); validation,results=load_results()
    index=json.loads((PRE/"race_index.json").read_text(encoding="utf-8"))["race_index"]
    allrows=[]; byrace={}; top5=[]; race_top3=[]
    for item in index:
        p=json.loads((PRE/item["artifact"]).read_text(encoding="utf-8")); vk,rn=parts(p["race_id"]); venue_jp=next((k for k,v in VENUE.items() if v==vk),None); row=results.get((venue_jp,rn))
        if row is None: raise RuntimeError(f"RESULT_RACE_MISSING:{p['race_id']}")
        joined=[]
        for h in p["ranked_results"]:
            z={"race_id":p["race_id"],"venue":venue_jp,"venue_key":vk,"race_number":rn,"horse_number":int(h["horse_number"]),"horse_name":h["horse_name"],"current_rank":h.get("rank"),"frozen_buy":bool(h.get("buy")),**outcome(row,int(h["horse_number"]))}; joined.append(z);allrows.append(z)
        if len(joined)!=int(row[9]): raise RuntimeError(f"PRE_RESULT_HORSE_SET_MISMATCH:{p['race_id']}")
        byrace[p["race_id"]]=joined; lookup={z["horse_number"]:z for z in joined}; top5 += [lookup[int(h["horse_number"])] for h in p["top5"]]
        race_top3.append({"race_id":p["race_id"],"venue":venue_jp,"race_number":rn,"actual_top3":[z for z in joined if z["actual_top3"]],"top5":[lookup[int(h["horse_number"])] for h in p["top5"]]})
    current=[z for z in allrows if z["frozen_buy"]]; cm=metric(current)
    v4pre=json.loads((V4PRE/"v4_selection.json").read_text(encoding="utf-8")); v4=[]; comparisons=[]
    for r in v4pre["races"]:
        chosen=[]; lookup={z["horse_number"]:z for z in byrace[r["race_id"]]}
        for n,name,prob,sr in r["v4_selected"]: chosen.append({**lookup[int(n)],"v4_probability_frozen":prob,"shadow_ai_rank":sr})
        cur=[z for z in byrace[r["race_id"]] if z["frozen_buy"]]; a,b=metric(cur),metric(chosen); label="EQUAL" if a["hits"]==b["hits"] else ("CURRENT_SUPERIOR" if a["hits"]>b["hits"] else "V4_SUPERIOR")
        v4+=chosen; comparisons.append({"race_id":r["race_id"],"venue":r["venue"],"race_number":r["race_number"],"current":cur,"v4":chosen,"current_metrics":a,"v4_metrics":b,"comparison":label,"raw_hit_difference":b["hits"]-a["hits"]})
    vm=metric(v4)
    cfpre=json.loads((CFROOT/f"formal_pre_{DATE}.json").read_text(encoding="utf-8")); cfrows=[]; cfrecords=[]
    for r in cfpre["eligible_races"]:
        lookup={z["horse_number"]:z for z in byrace[r["race_id"]]}; selected=[{**lookup[int(h["horse_number"])],"shadow_ai_rank":h["shadow_ai_rank"]} for h in r["cf_selected_horses"]]; pool=[{**lookup[int(h["horse_number"])],"shadow_ai_rank":h["shadow_ai_rank"]} for h in r["candidate_horses"]]; sm,pm=metric(selected),metric(pool); cfrows+=selected; cfrecords.append({"race_id":r["race_id"],"venue":r["venue"],"race_number":r["race_number"],"selected":selected,"pool":pool,"selected_metrics":sm,"pool_metrics":pm,"difference":None if sm["rate"] is None or pm["rate"] is None else sm["rate"]-pm["rate"]})
    cfm=metric(cfrows); poolrows=[x for r in cfrecords for x in r["pool"]]; pm=metric(poolrows)
    # Derived ledger only: never mutate its frozen predecessor.
    vb=json.loads((ROOT/"reports/v4_model_v3_formal_prospective/20260830_post/evidence_ledger_update.json").read_text(encoding="utf-8")); cumulative_v4={"completed_formal_dates":2,"eligible_dates":["20260830",DATE],"eligible_race_count":vb["eligible_race_count"]+len(comparisons),"current":{**metric([]),"selected":vb["current"]["selected_count"]+cm["selected"],"valid":vb["current"]["valid_selected_count"]+cm["valid"],"hits":vb["current"]["top3_hits"]+cm["hits"]},"v4":{**metric([]),"selected":vb["v4"]["selected_count"]+vm["selected"],"valid":vb["v4"]["valid_selected_count"]+vm["valid"],"hits":vb["v4"]["top3_hits"]+vm["hits"]}}
    for k in ("current","v4"): cumulative_v4[k]["invalid"]=cumulative_v4[k]["selected"]-cumulative_v4[k]["valid"]; cumulative_v4[k]["rate"]=cumulative_v4[k]["hits"]/cumulative_v4[k]["valid"] if cumulative_v4[k]["valid"] else None
    cumulative_v4["raw_hit_difference"]=cumulative_v4["v4"]["hits"]-cumulative_v4["current"]["hits"]; cumulative_v4["lift"]=cumulative_v4["v4"]["rate"]-cumulative_v4["current"]["rate"]; cumulative_v4["state"]="SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE"; cumulative_v4["minimum"]={"races":60,"dates":12}
    cfb=json.loads((CFROOT/"formal_post_20260830/cumulative_evidence.json").read_text(encoding="utf-8")); activation=json.loads((CFROOT/"activation_record.json").read_text(encoding="utf-8")); postrecords=[{"race_id":r["race_id"],"selected_valid_count":r["selected_metrics"]["valid"],"selected_top3_count":r["selected_metrics"]["hits"],"candidate_pool_valid_count":r["pool_metrics"]["valid"],"candidate_pool_top3_count":r["pool_metrics"]["hits"]} for r in cfrecords]; cfledger=append_formal_post_evidence(ledger=cfb,date=DATE,activation_record=activation,post_records=postrecords,independent_race_count=len(postrecords)); cfstate="SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE"
    capture=[]; misses=[]; buckets={str(i):0 for i in range(4)}
    for r in race_top3:
        t={x["horse_number"] for x in r["actual_top3"]}; s={x["horse_number"] for x in r["top5"]}; inside=[x for x in r["actual_top3"] if x["horse_number"] in s]; outside=[x for x in r["actual_top3"] if x["horse_number"] not in s]; buckets[str(len(inside))]+=1; rec={"race_id":r["race_id"],"venue":r["venue"],"race_number":r["race_number"],"top5":r["top5"],"actual_top3":r["actual_top3"],"inside":inside,"outside":outside,"TOP5_GENERATION_MISS":bool(outside)}; capture.append(rec); misses += [rec] if outside else []
    capsum={"races":len(capture),"valid_actual_top3_total":sum(len(x["actual_top3"]) for x in capture),"top5_inside":sum(len(x["inside"]) for x in capture),"top5_outside":sum(len(x["outside"]) for x in capture),"capture_buckets":buckets,"at_least_one":sum(v for k,v in buckets.items() if int(k)>=1),"all_three":buckets["3"],"miss_race_count":len(misses),"status":"CURRENT_TOP5_CANDIDATE_CAPTURE_DIAGNOSTIC"}
    safety={"status":"PASS","current_rerun":0,"v4_rerun":0,"v4_retrain":0,"cf_reselection":0,"pre_regeneration":0,"frozen_selection_change":0,"model_change":0,"protocol_change":0,"production_change":0,"candidate_generation_change":0,"ledger_mutation":0,"result_access":"POST_ONLY"}
    V4OUT.mkdir(parents=True); CFOUT.mkdir(parents=True)
    dump(V4OUT/"pre_integrity.json",integrity); dump(V4OUT/"result_reconciliation.json",validation); dump(V4OUT/"current_post.json",{"metrics":cm,"horses":current,"race_success_count":sum(metric([x for x in byrace[r] if x["frozen_buy"]])["hits"]>0 for r in byrace)}); dump(V4OUT/"v4_post.json",{"metrics":vm,"comparisons":comparisons,"difference":{"raw_hits":vm["hits"]-cm["hits"],"rate_points":None if cm["rate"] is None or vm["rate"] is None else 100*(vm["rate"]-cm["rate"])} }); dump(V4OUT/"v4_cumulative_derived.json",cumulative_v4); dump(V4OUT/"current_top5_capture_diagnostic.json",{"summary":capsum,"races":capture,"misses":misses,"v4_full_ranking":"NOT_OBSERVABLE_FROM_FROZEN_20260905_PRE"}); dump(V4OUT/"safety.json",safety)
    dump(CFOUT/"cf_post.json",{"selected_metrics":cfm,"pool_metrics":pm,"difference":None if cfm["rate"] is None or pm["rate"] is None else cfm["rate"]-pm["rate"],"races":cfrecords}); dump(CFOUT/"cumulative_evidence_derived.json",cfledger); dump(CFOUT/"formal_status.json",{"state":cfstate,"dates":cfledger["formal_independent_date_count"],"races":cfledger["formal_independent_race_count"],"minimum":{"dates":4,"races":20}}); dump(CFOUT/"safety.json",safety)
    dump(V4OUT/"resume_record.json",{"initial_attempt":"STOP","reason":"V4_FULL_TOP5_RANKING_NOT_FROZEN","human_approved_scope_narrowing":True,"removed_diagnostic":"V4_FULL_TOP5_RANKING_DIAGNOSTIC","status":"RESUMED"})
    for root in (V4OUT,CFOUT): dump(root/"artifact_hashes.json",{"self_hash_excluded":True,"hashes":{p.name:sha(p) for p in root.iterdir() if p.is_file() and p.name!="artifact_hashes.json"}})
if __name__=="__main__": main()
