"""PRE-only factual packet for eight explicitly requested 2026-10-24 races."""
import csv
import json
from collections import Counter
from pathlib import Path
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.pl_adaptive_shadow_v1 import write_json, sha

ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/'reports'
OUT=REPORTS/'20261024_manual_race_analysis_pack_v1'
RACES={f'race_20261024_{v}_{n}R' for v,ns in {'kyoto':(6,7,8,12),'niigata':(6,10,12),'tokyo':(10,)}.items() for n in ns}
PLACE={'kyoto':'京都','niigata':'新潟','tokyo':'東京'}

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def indexed(rows,flag=lambda x:True):
    return {(r['race_id'],int(r['horse_number'])):r for r in rows if flag(r)}

def run():
    if OUT.exists(): raise RuntimeError('STOP_OUTPUT_EXISTS')
    raw=ROOT/'data/raw/prediction_input'
    paths={k:raw/f'{k}261024.CSV' for k in ('DG','DE','DS')}
    bundle=TargetBulkPredictionInputAdapterV1().load(paths['DG'],paths['DE'],paths['DS'])
    if bundle.date!='20261024' or len(bundle.races)!=21 or sum(len(x.today_entries) for x in bundle.races.values())!=269 or not RACES<=set(bundle.races):
        raise RuntimeError('STOP_PRE_POPULATION_MISMATCH')
    source_sha={k:sha(v) for k,v in paths.items()}
    approved={'DG':'e5d54a43ba839ef7ac36176b8114933470831b96e04eb54b70d9e6ca7b2aef96',
              'DE':'91d91d85a2483be7e6f6975c88d7d38d9516f87fa654762b44069e65bd7fc051',
              'DS':'482be75a01668877210e65b6d9d543a777d6ff88c076ea7a7024d3b099343eb0'}
    if source_sha!=approved: raise RuntimeError('STOP_SOURCE_SHA_CHANGED')
    with paths['DE'].open(encoding='cp932',newline='') as stream:
        de=list(csv.reader(stream))
    de_by={(r[1].strip(),int(r[2]),int(r[3])):r for r in de}
    current_root=REPORTS/'prospective_prediction_20261024_v1'
    ci=read(current_root/'race_index.json')['race_index']
    current={r['race_id']:read(current_root/r['artifact']) for r in ci}
    v5=indexed(read(REPORTS/'20261024_v5_family_support_pre/support.json')['horses'])
    pl=indexed(read(REPORTS/'pl_forward_shadow_v1/20261024_pre/prediction.json')['horses'])
    integrated=indexed(read(REPORTS/'adaptive_pl_jockey_research_v1/20261024_pre/prediction.json')['horses'])
    exp=read(REPORTS/'exp024_pl_same_volume/20261024_pre_analysis/selection.json')
    exp_selected={(r['race_id'],int(h if isinstance(h,int) else h['horse_number'])) for r in exp['races'] for h in r['treatment_selected_horses']}
    packet=[]; missing=Counter(); past_count=0
    adapter=TargetBulkPredictionInputAdapterV1()
    for race_id in sorted(RACES):
        race=bundle.races[race_id]
        venue=PLACE[race_id.split('_')[2]]; number=int(race_id.split('_')[3][:-1])
        current_buy={int(x['horse_number']) for x in current[race_id]['buys']}
        horses=[]
        for entry in sorted(race.today_entries,key=lambda x:x.horse_number):
            key=(race_id,entry.horse_number)
            if key not in v5 or key not in pl or key not in integrated:
                raise RuntimeError('STOP_PRE_HORSE_SET_MISMATCH:'+str(key))
            r=de_by[(venue,number,entry.horse_number)]
            histories=adapter._past_races(race.history_rows_by_horse[entry.horse_name])
            past=[]
            for h in histories:
                past.append(dict(race_date=h.race_date.date().isoformat(),venue=h.race_id.split('_')[2],
                    course=None,surface=h.surface,distance=h.distance,track_condition=h.track_condition,
                    class_or_race_level=h.class_level,field_size=h.field_size,finish=h.finish_position,
                    margin=h.margin,running_positions=h.corner_positions or None,final_3f=h.last_3f,
                    race_time=None,pace_or_lap=None,race_first_half=None,race_second_half=None,
                    individual_position_change=None,carried_weight=None,body_weight=h.body_weight,
                    body_weight_change=h.body_weight_diff,source='DS261024.CSV'))
            past_count+=len(past)
            vm=v5[key]; pp=pl[key]; ip=integrated[key]
            exp_yes=key in exp_selected
            pl_yes=(ip['integrated_rank']<=3 or ip['adaptive_rank']<=3 or
                    pp['pl_race_rank']<=3 or exp_yes)
            current_yes=entry.horse_number in current_buy
            ai=dict(CURRENT_BUY=current_yes,V5_FAMILY_SUPPORT=vm['v5_family_high'],
                V5_MEMBER_SUPPORT_COUNT=len(vm['v5_member_lanes_supporting']),
                V5_MEMBER_LANES_SUPPORTING=vm['v5_member_lanes_supporting'],
                PL_FAMILY_SUPPORT=pl_yes,EXP024_SELECTED=exp_yes,
                ADAPTIVE_PL_JOCKEY_RANK=ip['integrated_rank'],
                ADAPTIVE_PL_JOCKEY_P_TOP3=ip['integrated_p_top3'],
                ADAPTIVE_PL_RANK=ip['adaptive_rank'],ADAPTIVE_PL_P_TOP3=ip['adaptive_p_top3'],
                JOCKEY_RANK_CHANGE=ip['rank_change_vs_adaptive'],JOCKEY_TOP3_LIFT=ip['jockey_top3_lift'],
                FROZEN_PL_RANK=pp['pl_race_rank'],
                INDEPENDENT_FAMILY_VOTES=sum((current_yes,vm['v5_family_high'],pl_yes)))
            horse=dict(horse_number=entry.horse_number,horse_name=entry.horse_name,
                sex=r[8].strip() or None,age=int(r[9]) if r[9].strip().isdigit() else None,
                assigned_weight=entry.weight,jockey=entry.jockey,trainer=r[12].strip() or None,
                body_weight=None,past_runs=past,ai_pre_context=ai)
            for field in ('course','race_time','pace_or_lap','race_first_half','race_second_half','carried_weight'):
                missing[field]+=len(past)
            missing['current_body_weight']+=1
            horses.append(horse)
        if len(horses)!=len(race.today_entries): raise RuntimeError('STOP_HORSE_COUNT')
        packet.append(dict(race_metadata=dict(date='2026-10-24',race_id=race_id,venue=venue,
            race_number=number,surface=race.today_entries[0].surface,
            distance=race.today_entries[0].distance,course=None,field_size=len(horses)),
            full_field_horses=horses,
            race_facts=dict(distance_changes_from_previous_start=sum(bool(h['past_runs']) and h['past_runs'][0]['distance']!=race.today_entries[0].distance for h in horses),
                            surface_changes_from_previous_start=sum(bool(h['past_runs']) and h['past_runs'][0]['surface']!=race.today_entries[0].surface for h in horses),
                            historical_running_style_composition=None,class_rises_or_drops=None,course_switches=None),
            data_quality=dict(missing_fields=['course','current_body_weight','race_time','pace_or_lap','race_first_half','race_second_half','carried_weight'],
                              no_past_run_horses=[h['horse_number'] for h in horses if not h['past_runs']])))
    output=dict(role='PRE_ONLY_FACT_EXTRACTION',target_date='2026-10-24',result_access_count=0,
        odds_included=False,popularity_included=False,marks_included=False,
        source_sha256=source_sha,ai_source_sha256={'current':sha(current_root/'prediction_manifest.json'),
        'v5_support':sha(REPORTS/'20261024_v5_family_support_pre/support.json'),
        'frozen_pl':sha(REPORTS/'pl_forward_shadow_v1/20261024_pre/prediction.json'),
        'adaptive_jockey':sha(REPORTS/'adaptive_pl_jockey_research_v1/20261024_pre/prediction.json'),
        'exp024':sha(REPORTS/'exp024_pl_same_volume/20261024_pre_analysis/selection.json')},
        family_vote_semantics='CURRENT / V5 / PL; PL family contributes at most one descriptive vote',
        races=packet,missing_fields_summary=dict(missing))
    OUT.mkdir(parents=True)
    path=OUT/'manual_analysis_data.json'; write_json(path,output)
    write_json(OUT/'artifact_hashes.json',{'manual_analysis_data_sha256':sha(path)})
    return len(packet),sum(len(r['full_field_horses']) for r in packet),past_count,sha(path)

if __name__=='__main__': print(run())
