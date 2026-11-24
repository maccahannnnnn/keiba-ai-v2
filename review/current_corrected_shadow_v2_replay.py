"""Canonical all-off/all-on technical replay for CURRENT_CORRECTED_SHADOW_V2.

This command reads only pre-race DG/DE/DS sources.  It never imports Result
data and creates outputs only below its explicitly supplied report root.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from review.current_corrected_shadow_v2 import CorrectionConfigV2, apply_corrected_shadow_v2
from review.current_corrected_shadow_v2_runner import inventory_risk_vocabulary, run_new_v2, sha256
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1, HUMAN_APPROVED_20260906_EXACT_EXCEPTION

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'reports/current_corrected_shadow_v1_raw_replay_v7/current_canonical_complete_replay_payload_manifest_v1.json'
DEFAULT_OUTPUT=ROOT/'reports/current_corrected_shadow_v2_technical_replay_v2'
EXCLUSIONS={
 '20251213':('race_20251213_hanshin_8R','マーブルヘイロー'),
 '20260823':('race_20260823_niigata_7R','マインドフルネス'),
}
OBSERVABLES=('rank','buy_v1_rc1_buy','buy_v1_rc1_candidate','buy_v1_rc1_race_state','integrated_score','final_score','adjusted_score','decision','decision_score')

def _write_cp932(path:Path,rows:list[list[str]]):
    with path.open('w',encoding='cp932',newline='') as f: csv.writer(f,lineterminator='\r\n').writerows(rows)

def _source_paths(entry): return tuple(ROOT/entry['raw_source_paths'][key].replace('\\','/') for key in ('DG','DE','DS'))

def _filtered_date_sources(date:str, paths:tuple[Path,Path,Path], root:Path):
    """Reproduce only the two already-authorized date-specific exclusions."""
    if date not in EXCLUSIONS: return paths
    adapter=TargetBulkPredictionInputAdapterV1(); dg,de,ds=paths
    dg_rows,_=adapter._read_fixed(dg,'DG'); de_rows,_=adapter._read_fixed(de,'DE'); ds_rows,_=adapter._read_fixed(ds,'DS')
    target_id,target_name=EXCLUSIONS[date]; target_date=adapter._validate_dates({'DG':dg_rows,'DE':de_rows,'DS':ds_rows})
    dg_by=adapter._validate_dg(dg_rows,target_date); de_by,_,_=adapter._validate_de(de_rows,target_date)
    key=next((key for key in dg_by if adapter._race_id(target_date,key[0],key[1])==target_id),None)
    if key is None: raise RuntimeError('APPROVED_EXCLUSION_RACE_NOT_FOUND:'+target_id)
    excluded=de_by[key]; names={adapter._clean_name(row[7]) for row in excluded}
    if target_name not in names: raise RuntimeError('APPROVED_EXCLUSION_IDENTITY_MISMATCH:'+target_id)
    filtered={'DG':[row for row in dg_rows if row is not dg_by[key]],'DE':[row for row in de_rows if row not in excluded], 'DS':[row for row in ds_rows if adapter._clean_name(row[16]) not in names]}
    root.mkdir(parents=True,exist_ok=True); output=[]
    for kind in ('DG','DE','DS'):
        path=root/f'{kind}{date[2:]}.CSV'; _write_cp932(path,filtered[kind]); output.append(path)
    return tuple(output)

def _compare(current, expected, race_id):
    left={str(row.get('horse_name')):row for row in current['ranked_results']}; right={str(row.get('horse_name')):row for row in expected['ranked_results']}
    mismatches=[]
    if set(left)!=set(right): return [{'race_id':race_id,'field':'horse_set','expected':sorted(right),'actual':sorted(left)}]
    for name in sorted(left):
        for field in OBSERVABLES:
            if left[name].get(field)!=right[name].get(field):
                mismatches.append({'race_id':race_id,'horse_name':name,'field':field,'expected':right[name].get(field),'actual':left[name].get(field)})
    return mismatches

def run(output_root:Path=DEFAULT_OUTPUT):
    if output_root.exists(): raise RuntimeError('OUTPUT_ALREADY_EXISTS:'+str(output_root))
    manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
    by_date=defaultdict(list)
    for entry in manifest['races']: by_date[entry['date']].append(entry)
    temporary=ROOT/'.tmp/current_corrected_shadow_v2_replay_filtered'
    if temporary.exists(): raise RuntimeError('FILTERED_SOURCE_RESIDUE')
    output_root.mkdir(parents=True); on_root=output_root/'all_on_outputs'; on_root.mkdir()
    all_off_mismatches=[]; on_races=on_horses=0; started_at=datetime.now(timezone.utc).isoformat(); structural=defaultdict(int)
    try:
        for date, entries in sorted(by_date.items()):
            print(f"V2_REPLAY_DATE_START {date} {len(entries)}", flush=True)
            paths=_filtered_date_sources(date,_source_paths(entries[0]),temporary/date)
            compatibility_exception=HUMAN_APPROVED_20260906_EXACT_EXCEPTION if date == '20260906' else None
            bundle=TargetBulkPredictionInputAdapterV1().load(*paths, compatibility_exception=compatibility_exception)
            for entry in entries:
                race_id=entry['race_id']
                if race_id not in bundle.races: raise RuntimeError('CANONICAL_RACE_MISSING:'+race_id)
                expected=json.loads((ROOT/entry['payload_path'].replace('\\','/')).read_text(encoding='utf-8'))['current_replay']
                off=run_new_v2(race_id,bundle.races[race_id],CorrectionConfigV2.all_off())
                all_off_mismatches.extend(_compare(off,expected,race_id))
                on=run_new_v2(race_id,bundle.races[race_id],CorrectionConfigV2.all_on())
                projected=apply_corrected_shadow_v2(on['ranked_results'],CorrectionConfigV2.all_on())
                structural['race_state:'+projected[0]['corrected_shadow']['race_state'] if projected else 'race_state:EMPTY'] += 1
                structural['buy_positive_race'] += int(any(row['corrected_shadow']['buy'] for row in projected))
                for row in projected:
                    shadow=row['corrected_shadow']; detail=shadow['risk_guard_detail']
                    structural['risk_guard_pass'] += int(shadow['risk_guard']); structural['risk_guard_fail'] += int(not shadow['risk_guard'])
                    structural['reliability_pass'] += int(shadow['reliability']['pass']); structural['reliability_fail'] += int(not shadow['reliability']['pass'])
                    structural['candidate'] += int(shadow['candidate']); structural['buy'] += int(shadow['buy'])
                    structural['fail_severe'] += int(detail['severe']); structural['fail_true_data_limitation'] += int(detail['true_data_limitation']); structural['fail_risk_count'] += int(detail['risk_count_fail'])
                artifact={'schema_version':'CURRENT_CORRECTED_SHADOW_V2_ALL_ON_RACE_V1','race_id':race_id,'v2_pace_trace':on['v2_pace_trace'],'corrected_rows':[{'horse_name':r.get('horse_name'),'horse_number':r.get('horse_number'),'corrected_shadow':r['corrected_shadow']} for r in projected]}
                target=on_root/f'{race_id}.json'; target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
                on_races+=1; on_horses+=len(projected)
            print(f"V2_REPLAY_DATE_DONE {date} {on_races} {on_horses}", flush=True)
        inventory=inventory_risk_vocabulary(output_root/'risk_vocabulary_inventory.json')
        all_on_hashes={path.name:sha256(path) for path in sorted(on_root.glob('*.json'))}
        all_off={'status':'PASS' if not all_off_mismatches else 'FAIL','population_id':'CURRENT_CANONICAL_COMPLETE_REPLAY_PAYLOAD_MANIFEST_V1','race_count':len(manifest['races']),'horse_count':manifest['total_horses'],'OBSERVABLE_MISMATCH':len(all_off_mismatches),'mismatches':all_off_mismatches[:100], 'result_access_count':0}
        on_manifest={'status':'TECHNICAL_REPLAY_COMPLETE','evidence_boundary':'POST_RESULT_ENGINEERING_REPLAY_ONLY','population_id':'CURRENT_CANONICAL_COMPLETE_REPLAY_PAYLOAD_MANIFEST_V1','source_race_count':len(manifest['races']),'source_horse_count':manifest['total_horses'],'output_race_count':on_races,'output_horse_count':on_horses,'raw_replay_input_manifest_sha256':sha256(MANIFEST),'runner_sha256':sha256(Path(__file__)),'config_sha256':sha256(ROOT/'review/current_corrected_shadow_v2.py'),'risk_mapping_sha256':sha256(output_root/'risk_vocabulary_inventory.json'),'output_artifact_sha256':hashlib.sha256(json.dumps(all_on_hashes,sort_keys=True).encode()).hexdigest(),'RESULT_ACCESS':0,'PERFORMANCE_EVALUATION':False,'PRODUCTION_MODIFIED':False,'started_at':started_at,'completed_at':datetime.now(timezone.utc).isoformat(),'structural_diagnostics':dict(structural),'PACE_DEPENDENT_CONSUMERS':['RacePacePredictor','RaceStructureEngine','RaceShapeEvaluator','CourseShapeEvaluator','LapSuitabilityEvaluator','ConsistencyEngine']}
        (output_root/'all_off_reproduction_report.json').write_text(json.dumps(all_off,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (output_root/'all_on_manifest.json').write_text(json.dumps(on_manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return all_off,on_manifest,inventory
    finally:
        if temporary.exists(): shutil.rmtree(temporary)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--output-root',default=str(DEFAULT_OUTPUT)); args=parser.parse_args()
    off,on,inventory=run(Path(args.output_root)); print(json.dumps({'all_off':off['status'],'mismatches':off['OBSERVABLE_MISMATCH'],'all_on_races':on['output_race_count'],'all_on_horses':on['output_horse_count'],'unmapped':inventory['UNMAPPED_RISK_TEXT_COUNT']},ensure_ascii=False))
