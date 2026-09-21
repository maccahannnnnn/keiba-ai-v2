"""POST evaluator for an already frozen Independent Race Selection PRE."""
from __future__ import annotations
import csv, hashlib, json
from pathlib import Path
from review.target_daily_result_list_schema_v2_validator import validate_source_pair
from review.target_bulk_prediction_input_adapter_v1 import COURSE_KEYS

ROOT=Path(__file__).resolve().parents[1]
ABNORMAL={"中止","除外","取消","失格"}
# Reuse the adapter's canonical JRA course tokens; unknown tokens must stop.
VENUE={token:name for name,token in COURSE_KEYS.items()}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def resolve_venue(token):
    try: return VENUE[token]
    except KeyError as exc: raise RuntimeError("STOP_UNKNOWN_VENUE_TOKEN:"+str(token)) from exc
def race_result_key(race_id):
    bits=race_id.split("_")
    try: return resolve_venue(bits[-2]),int(bits[-1][:-1])
    except (IndexError, ValueError) as exc: raise RuntimeError("STOP_RACE_ID_PARSE_FAILURE:"+race_id) from exc
def outcome(row,no):
    v=row[11+int(no)].strip()
    if v.isdigit() and int(v)>0: return {"actual_finish":int(v),"valid_result":True,"actual_top3":int(v)<=3}
    if v in ABNORMAL: return {"actual_finish":None,"valid_result":False,"actual_top3":False}
    raise RuntimeError("STOP_UNKNOWN_RESULT_SEMANTICS:"+v)
def metric(rows):
    valid=[x for x in rows if x["valid_result"]]; hits=sum(x["actual_top3"] for x in valid)
    return {"natural_n":len(rows),"invalid_n":len(rows)-len(valid),"valid_n":len(valid),"hits":hits,"rate":hits/len(valid) if valid else None}
def evaluate(pre_root:Path, primary:Path, auxiliary:Path, output:Path):
    if output.exists(): raise RuntimeError("STOP_OUTPUT_EXISTS")
    pre=json.loads((pre_root/"selection_manifest.json").read_text(encoding="utf-8")); date=pre["date"]
    index=json.loads((pre_root/"artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
    if any(sha(pre_root/k)!=v for k,v in index.items()): raise RuntimeError("STOP_PRE_HASH_MISMATCH")
    if validate_source_pair(primary,auxiliary,date).get("status")!="PASS": raise RuntimeError("STOP_RESULT_SOURCE")
    with primary.open(encoding="cp932",newline="") as f: source=list(csv.reader(f))
    results={(r[1],int(r[2])):r for r in source}
    independent=[]; current=[]; byrace={r["race_id"]:r for r in pre["races"]}
    for race in pre["races"]:
        rr=results[race_result_key(race["race_id"])]
        for h in race["selected_horses"]: independent.append({"race_id":race["race_id"],"horse_number":h["horse_number"],**outcome(rr,h["horse_number"])})
    for race in pre["current_comparator"]:
        rr=results[race_result_key(race["race_id"])]
        for h in race["current_buy_horses"]: current.append({"race_id":race["race_id"],"horse_number":h["horse_number"],**outcome(rr,h["horse_number"])})
    im,cm=metric(independent),metric(current)
    current_races={r['race_id'] for r in pre['current_comparator'] if r['current_buy_horses']}
    selected_races={r['race_id'] for r in pre['races'] if r['race_selected']}
    diagnostic={
        'added_from_PLAY_UNCONVERGED_4PLUS':[r for r in independent if byrace[r['race_id']]['current_race_state']=='PLAY_UNCONVERGED_4PLUS'],
        'added_from_SKIP':[r for r in independent if byrace[r['race_id']]['current_race_state']=='SKIP'],
        'common_with_Current_selected_race':[r for r in independent if r['race_id'] in current_races],
        'Current_selected_but_Independent_dropped':[r for r in current if r['race_id'] not in selected_races],
    }
    output.mkdir(parents=True)
    payload={"date":date,"independent":im,"current":cm,"selected_races":sum(r["race_selected"] for r in pre["races"]),"current_buy_races":sum(bool(r["current_buy_horses"]) for r in pre["current_comparator"]),"raw_rate_difference":im["rate"]-cm["rate"] if im["rate"] is not None and cm["rate"] is not None else None,"hit_difference":im["hits"]-cm["hits"],"race_volume_ratio":sum(r["race_selected"] for r in pre["races"])/len(pre["races"]),"horse_volume_ratio":im["natural_n"]/cm["natural_n"] if cm["natural_n"] else None,"result_rows":{"independent":independent,"current":current},"mechanism_splits":{k:{"rows":v,"metrics":metric(v)} for k,v in diagnostic.items()}}
    (output/"summary.json").write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return payload
