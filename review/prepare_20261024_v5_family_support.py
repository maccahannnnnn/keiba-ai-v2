"""PRE-only V5 member support export for the frozen 2026-10-24 lanes."""
import json
from pathlib import Path
from review.pl_adaptive_shadow_v1 import write_json, sha

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'reports'
CURRENT=BASE/'prospective_prediction_20261024_v1'
OUT=BASE/'20261024_v5_family_support_pre'

def load(path):
    return json.loads(path.read_text(encoding='utf-8'))

def run():
    if OUT.exists():
        raise RuntimeError('STOP_OUTPUT_EXISTS')
    index=load(CURRENT/'race_index.json')['race_index']
    horses={}
    for item in index:
        p=load(CURRENT/item['artifact'])
        for row in p['ranked_results']:
            key=(p['race_id'],int(row['horse_number']))
            horses[key]={'race_id':key[0],'horse_number':key[1],'horse_name':row['horse_name'],'v5_member_lanes_supporting':[]}
    def add(race_id,rows,lane):
        for row in rows:
            key=(race_id,int(row['horse_number']))
            if key not in horses:
                raise RuntimeError('STOP_V5_HORSE_SET_MISMATCH:'+str(key))
            horses[key]['v5_member_lanes_supporting'].append(lane)
    indep=load(BASE/'independent_race_selection_prospective/20261024_pre_retry1/selection_manifest.json')
    for row in indep['races']:
        add(row['race_id'],row['selected_horses'],'INDEPENDENT_V5')
    tc=load(BASE/'trackcondition_semantic_prospective/20261024_pre/horse_level_trace.json')
    for row in tc['rows']:
        if row['shadow_selected']:
            add(row['race_id'],[row],'TRACKCONDITION_SEMANTIC')
    daily=load(BASE/'daily_v5_same_volume_prospective/20261024_pre/selection.json')
    for row in daily['races']:
        add(row['race_id'],row['selected_horses'],'DAILY_V5_SAME_VOLUME')
    formal=load(BASE/'v5_v6_technical_reference/20261024_pre/dual_pre_semantic.json')
    for row in formal['races']:
        for arm,lane in [('v5','FORMAL_V5'),('v6','FORMAL_V6')]:
            add(row[arm]['race_id'],[h for h in row[arm]['horses'] if h['selected_by_protocol']],lane)
    records=[]
    for key in sorted(horses):
        row=horses[key]
        row['v5_member_lanes_supporting'].sort()
        row['v5_family_high']=bool(row['v5_member_lanes_supporting'])
        row['v5_family_vote_count']=int(row['v5_family_high'])
        records.append(row)
    OUT.mkdir(parents=True)
    write_json(OUT/'support.json',{'date':'2026-10-24','role':'PRE_INTERNAL_FAMILY_SUPPORT_ONLY','formal_evidence':False,'horses':records})
    write_json(OUT/'artifact_hashes.json',{'support_sha256':sha(OUT/'support.json')})
    return len(records),sum(r['v5_family_high'] for r in records)

if __name__=='__main__':
    print(run())
