"""2026-10-24 research PRE; no Result or active-model dependency."""
import hashlib
import json
from pathlib import Path
import numpy as np
from review import adaptive_pl_jockey_research_v1 as research
from review import pl_adaptive_shadow_v1 as adaptive
from review import pl_forward_shadow_v1 as forward
from review import post_ws2_jockey_mechanism_research_v1_model as jockey
from review import exp025_offset_pl_raw_history_v1 as identity
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new

ROOT=research.ROOT
DATE='20261024'
OUT=ROOT/'reports/adaptive_pl_jockey_research_v1/20261024_pre'
EXPECTED={'adaptive_model.json':'3448e846234b5a47a376e8ea46c4544dd4e6b31357d033cceca567bdff9f5d1a',
          'integrated_model.json':'66bf159125786e258fd671be5b823bdfd0b79b3a3bb0db7c2e93713245b8b376',
          'integrated_manifest.json':'da988d09747c17104e12a75daa5ba65d6310b2eacdc50f8278237e03f284db45',
          'jockey_history_manifest.json':'092debc076d2dc1b2524da759b9a21d8df845203729ae5c1ed0ba4aab074013c'}

def run():
    if OUT.exists():
        raise RuntimeError('STOP_1024_PRE_OUTPUT_EXISTS')
    for name,expected in EXPECTED.items():
        if adaptive.sha(research.OUT/name)!=expected:
            raise RuntimeError('STOP_RESEARCH_MODEL_SHA')
    paths={k:ROOT/'data/raw/prediction_input'/f'{k}261024.CSV' for k in ('DG','DE','DS')}
    if any(not p.is_file() for p in paths.values()):
        raise RuntimeError('STOP_1024_PRE_INPUT_MISSING')
    adapter=TargetBulkPredictionInputAdapterV1()
    try:
        bundle=adapter.load(paths['DG'],paths['DE'],paths['DS'])
    except Exception as error:
        raise RuntimeError('STOP_1024_HORSE_SET_MISMATCH:'+str(error)) from error
    de=identity.read_source(paths['DE'],33)
    ds=identity.read_source(paths['DS'],50)
    by_ds={}
    for row in ds:
        ident=tuple(identity.clean(row[i]) for i in (16,44,46))
        by_ds.setdefault(ident,[]).append(row)
    targets=[]; today_records=[]
    for row in de:
        race_id=identity.race_id(DATE,identity.clean(row[1]),identity.integer(row[2]))
        horse_no=identity.integer(row[3])
        ident=tuple(identity.clean(row[i]) for i in (7,16,20))
        if race_id not in bundle.races or ident not in by_ds:
            raise RuntimeError(f'STOP_1024_HORSE_SET_MISMATCH:{race_id}:{horse_no}:{ident}')
        targets.append(dict(date=DATE,race_id=race_id,horse_number=horse_no,horse_name=ident[0],
            horse_identity=ident,current_jockey_normalized=jockey.jockey_pit.normalize_jockey(row[10])))
        for history in adapter.valid_history_rows(by_ds[ident]):
            hd=identity.ds_date(history)
            if hd>=DATE:
                raise RuntimeError('STOP_1024_PIT:'+race_id)
            today_records.append(dict(snapshot_date=DATE,horse_identity=ident,
                historical_race_id=adapter._race_id(hd,identity.clean(history[4]),identity.integer(history[6])),
                historical_race_date=hd,historical_jockey_normalized=jockey.jockey_pit.normalize_jockey(history[19]),
                field_size=history[21],finish=history[23],completed_valid=True))
    _,snapshots,_=research.history_pool()
    snapshots[DATE]=today_records
    feature=jockey.feature_map_asof(targets,snapshots)
    if len(targets)!=sum(len(r.today_entries) for r in bundle.races.values()) or set(feature)!={research.key(t) for t in targets}:
        raise RuntimeError('STOP_1024_HORSE_SET_MISMATCH')
    target_map={research.key(t):t for t in targets}
    model=json.loads((research.OUT/'adaptive_model.json').read_text(encoding='utf-8'))
    beta=json.loads((research.OUT/'integrated_model.json').read_text(encoding='utf-8'))['beta_jockey']
    def infer():
        rows=[]; race_summaries=[]
        for race_id,race in sorted(bundle.races.items()):
            payload=run_new(race_id,race,trace=True)
            records=forward._payload_records(payload,DATE)
            matrix=np.vstack([r['vector'] for r in records])
            scaler=(matrix-np.asarray(model['scaler']['mean']))/np.asarray(model['scaler']['scale'])
            utility=scaler[:,:19]@np.asarray(model['pl_coefficients'])
            baseline,total=adaptive.iter2.pl_top3(scaler,np.asarray(model['pl_coefficients']))
            offset_zero,_=identity._top3_from_utility(utility)
            if not np.array_equal(baseline,offset_zero):
                raise RuntimeError('STOP_ADAPTIVE_OFFSET_REPRODUCTION_FAILURE')
            keys=[(DATE,race_id,int(r['horse_number'])) for r in records]
            if any(k not in feature for k in keys):
                raise RuntimeError('STOP_1024_HORSE_SET_MISMATCH:'+race_id)
            lift=np.asarray([feature[k][jockey.FEATURE] for k in keys])
            adjusted=utility+beta*lift
            integrated,integrated_total=identity._top3_from_utility(adjusted)
            if abs(total-3)>1e-8 or abs(integrated_total-3)>1e-8:
                raise RuntimeError('STOP_TOP3_PROBABILITY_SUM:'+race_id)
            br=sorted(range(len(keys)),key=lambda i:(-float(baseline[i]),keys[i][2]))
            ir=sorted(range(len(keys)),key=lambda i:(-float(integrated[i]),keys[i][2]))
            b_rank={v:i+1 for i,v in enumerate(br)}; i_rank={v:i+1 for i,v in enumerate(ir)}
            race_rows=[]
            for i,k in enumerate(keys):
                t=target_map[k]; f=feature[k]
                record=dict(date='2026-10-24',venue=race_id.split('_')[2],race_id=race_id,
                    horse_number=k[2],horse_name=t['horse_name'],adaptive_utility=float(utility[i]),
                    adaptive_p_top3=float(baseline[i]),adaptive_rank=b_rank[i],
                    jockey_name=t['current_jockey_normalized'],prior_ride_count=f['prior_ride_count'],
                    jockey_top3_lift=float(lift[i]),integrated_utility=float(adjusted[i]),
                    integrated_p_top3=float(integrated[i]),integrated_rank=i_rank[i],
                    rank_change_vs_adaptive=b_rank[i]-i_rank[i])
                race_rows.append(record)
            rows.extend(race_rows)
            race_summaries.append(dict(race_id=race_id,
                adaptive_top5=[(x['horse_number'],x['horse_name']) for x in sorted(race_rows,key=lambda x:x['adaptive_rank'])[:5]],
                integrated_top5=[(x['horse_number'],x['horse_name']) for x in sorted(race_rows,key=lambda x:x['integrated_rank'])[:5]],
                positive_movers=[(x['horse_number'],x['rank_change_vs_adaptive']) for x in sorted(race_rows,key=lambda x:-x['rank_change_vs_adaptive']) if x['rank_change_vs_adaptive']>0][:5],
                negative_movers=[(x['horse_number'],x['rank_change_vs_adaptive']) for x in sorted(race_rows,key=lambda x:x['rank_change_vs_adaptive']) if x['rank_change_vs_adaptive']<0][:5]))
        return dict(date='2026-10-24',model='ADAPTIVE_PL_JOCKEY_RESEARCH_V1',role='RESEARCH_FORWARD_PRE',
                    formal_prospective_evidence_credit=0,pl_family_max_votes=1,
                    sources={k:{'path':str(v.relative_to(ROOT)).replace('\\','/'),'sha256':adaptive.sha(v)} for k,v in paths.items()},
                    horses=rows),race_summaries
    first,summary=infer(); second,summary2=infer()
    if adaptive.canonical_bytes(first)!=adaptive.canonical_bytes(second) or adaptive.canonical_bytes(summary)!=adaptive.canonical_bytes(summary2):
        raise RuntimeError('STOP_NONDETERMINISTIC_OUTPUT')
    OUT.mkdir(parents=True)
    adaptive.write_json(OUT/'prediction.json',first)
    adaptive.write_json(OUT/'summary.json',dict(races=summary,pl_family_max_votes=1))
    adaptive.write_json(OUT/'artifact_hashes.json',dict(prediction_sha256=adaptive.sha(OUT/'prediction.json'),summary_sha256=adaptive.sha(OUT/'summary.json')))
    return len(summary),len(first['horses'])

if __name__=='__main__':
    print(run())
