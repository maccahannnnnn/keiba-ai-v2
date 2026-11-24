"""Read-only retrospective multi-lane diagnostic for 2026-10-10 and 2026-10-11."""
from __future__ import annotations
import csv, hashlib, json
from collections import defaultdict
from pathlib import Path
from typing import Any
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports'/'20261010_20261011_multilane_combination_diagnostic_v1_retry2'
LANES=('CURRENT','INDEPENDENT_V5','TRACKCONDITION_SEMANTIC','DAILY_V5_SAME_VOLUME','FORMAL_V5','FORMAL_V6')
JA={'tokyo':'東京','kyoto':'京都'}
COMBOS={
 'CURRENT':('CURRENT',),'DAILY':('DAILY_V5_SAME_VOLUME',),'INDEPENDENT':('INDEPENDENT_V5',),'FORMAL':('FORMAL_V5',),
 'CURRENT_UNION_DAILY':('CURRENT','DAILY_V5_SAME_VOLUME'),'CURRENT_UNION_INDEPENDENT':('CURRENT','INDEPENDENT_V5'),
 'DAILY_UNION_INDEPENDENT':('DAILY_V5_SAME_VOLUME','INDEPENDENT_V5'),
 'CURRENT_UNION_DAILY_UNION_INDEPENDENT':('CURRENT','DAILY_V5_SAME_VOLUME','INDEPENDENT_V5'),
 'CURRENT_UNION_FORMAL':('CURRENT','FORMAL_V5'),'DAILY_UNION_FORMAL':('DAILY_V5_SAME_VOLUME','FORMAL_V5'),
 'INDEPENDENT_UNION_FORMAL':('INDEPENDENT_V5','FORMAL_V5'),
 'ALL_AI_UNION':('CURRENT','INDEPENDENT_V5','TRACKCONDITION_SEMANTIC','DAILY_V5_SAME_VOLUME','FORMAL_V5'),
}
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p:Path)->Any:return json.loads(p.read_text(encoding='utf-8'))
def dump(p:Path,x:Any)->None:p.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def key(rid:str,no:Any)->tuple[str,str]:return rid,str(no)

def paths(date:str)->dict[str,Path]:
 if date=='20261010':
  return {'current':ROOT/'reports/prospective_prediction_20261010_v1','independent':ROOT/'reports/independent_race_selection_prospective/20261010_pre','tc':ROOT/'reports/track_condition_semantic_shadow_prospective/20261010_pre','daily':ROOT/'reports/daily_v5_same_volume_prospective/20261010_pre','formal':ROOT/'reports/selection_authority_protocol_v1_v6_forward_shadow/pre/20261010','post':ROOT/'reports/20261010_post_result_review_v1/post_review.json'}
 base=ROOT/'reports/20261011_official_pre_v1'
 return {'current':base/'current_frozen','independent':base/'independent_v5','tc':base/'trackcondition_semantic','daily':base/'daily_v5_same_volume','formal':base/'formal_v5_v6/20261011','post':ROOT/'reports/20261011_official_post_result_review_v1/post_review.json'}

def frozen(date:str)->dict[str,Any]:
 p=paths(date); curidx=load(p['current']/'race_index.json')['race_index']; records={}; sel={x:defaultdict(set) for x in LANES}
 for item in curidx:
  doc=load(p['current']/item['artifact']); rid=doc['race_id']; ranked=doc['ranked_results']
  records[rid]={'venue':str(ranked[0].get('venue') or rid.split('_')[-2]),'race_number':int(ranked[0].get('race_number') or rid.split('_')[-1][:-1]),'names':{str(h['horse_number']):h['horse_name'] for h in ranked},'state':doc.get('buy_gate_trace',{}).get('race',{}).get('shadow_race_state'),'payload':doc}
  sel['CURRENT'][rid]={str(h['horse_number']) for h in doc.get('buys',[])}
 independent={r['race_id']:r for r in load(p['independent']/'selection_manifest.json')['races']}
 for rid,r in independent.items():sel['INDEPENDENT_V5'][rid]={str(h['horse_number']) for h in r.get('selected_horses',[])}
 for h in load(p['tc']/'horse_level_trace.json')['rows']:
  if h.get('shadow_selected'):sel['TRACKCONDITION_SEMANTIC'][h['race_id']].add(str(h['horse_number']))
 daily={r['race_id']:r for r in load(p['daily']/'selection.json')['races']}
 for rid,r in daily.items():sel['DAILY_V5_SAME_VOLUME'][rid]={str(h['horse_number']) for h in r.get('selected_horses',[])}
 for r in load(p['formal']/'dual_pre_semantic.json')['races']:
  for lane,arm in [('FORMAL_V5','v5'),('FORMAL_V6','v6')]:sel[lane][r[arm]['race_id']]={str(h['horse_number']) for h in r[arm]['horses'] if h.get('selected_by_protocol')}
 ids=set(records)
 for lane in LANES:
  for rid in ids: sel[lane][rid]  # omitted selected-empty races are explicit empty sets for comparison
 if any(set(v)!=ids for v in sel.values()):raise RuntimeError(f'STOP_LANE_RACE_SET_MISMATCH:{date}')
 man=load(p['current']/'prediction_manifest.json')
 if any(sha(p['current']/x['relative_path'])!=x['sha256'] for x in man['files']):raise RuntimeError(f'STOP_CURRENT_MANIFEST_SHA:{date}')
 return {'records':records,'selection':sel,'source_paths':p}

def outcomes(date:str,pre:dict[str,Any])->dict[tuple[str,str],dict[str,Any]]:
 raw=ROOT/'data/raw/target/daily_result_list'; primary=raw/f'馬番順着順_{date}.csv'; aux=raw/f'着順馬番_{date}.csv'; pair=validate_source_pair(primary,aux,date)
 if pair.get('status')!='PASS':raise RuntimeError(f'STOP_RESULT_PAIR:{date}')
 with primary.open(encoding='cp932',newline='') as f: rows={x[0]:x for x in csv.reader(f)}
 index=pair['source_d_primary']['race_index']; byid={(x['venue_name'],int(x['race_number'])):k for k,x in index.items()}; out={}
 for rid,r in pre['records'].items():
  k=byid[(JA[r['venue']],r['race_number'])]; src=rows[k]
  for no in r['names']:
   value=src[11+int(no)].strip(); valid=value.isdigit() and int(value)>0
   out[key(rid,no)]={'actual_finish':int(value) if valid else None,'valid_result':valid,'actual_top3':bool(valid and int(value)<=3),'raw_result':value}
 return out

def metric(keys:set[tuple[str,str]],out:dict[tuple[str,str],dict[str,Any]])->dict[str,Any]:
 valid=[k for k in keys if out[k]['valid_result']]; hits=[k for k in valid if out[k]['actual_top3']]; races={k[0] for k in keys}; hitr={k[0] for k in hits}
 return {'unique_selected_N':len(keys),'valid_N':len(valid),'invalid_N':len(keys)-len(valid),'Top3_hits':len(hits),'BUY_TOP3_RATE':len(hits)/len(valid) if valid else None,'selected_races':len(races),'race_success_count':len(hitr),'race_success_rate':len(hitr)/len(races) if races else None,'average_selected_per_race':len(keys)/len(races) if races else None}

def selection_set(pre:dict[str,Any],lanes:tuple[str,...])->set[tuple[str,str]]:return {(rid,no) for lane in lanes for rid,nums in pre['selection'][lane].items() for no in nums}

def trace_1012()->tuple[list[dict[str,Any]],str]:
 base=ROOT/'reports/20261012_official_pre_v1_retry4/current_frozen'; rows=[]; patterns=[]
 for rid in ['race_20261012_tokyo_7R','race_20261012_tokyo_8R','race_20261012_tokyo_10R','race_20261012_tokyo_11R','race_20261012_tokyo_12R','race_20261012_tokyo_9R','race_20261012_kyoto_7R','race_20261012_kyoto_9R','race_20261012_kyoto_10R','race_20261012_kyoto_11R','race_20261012_kyoto_12R']:
  p=load(base/f'{rid}_prediction.json'); t=p.get('buy_gate_trace',{}); race=t.get('race',{}); horses=t.get('horses',[]); candidates=[h for h in horses if h.get('shadow_buy_candidate')]
  failed=[]
  for h in horses:
   if not h.get('risk_guard_pass'):failed.append('risk_guard')
   if not h.get('reliability_pass'):failed.append('reliability')
   if not h.get('absolute_quality_pass'):failed.append('absolute_quality')
   if not h.get('relative_advantage_pass'):failed.append('relative_advantage')
  rec={'race_id':rid,'race':rid.split('_')[-2].upper()+rid.split('_')[-1],'candidate_count':race.get('shadow_candidate_count','NOT_RECORDED_IN_ARTIFACT'),'candidate_horses':','.join(f"#{h['horse_number']}" for h in candidates) or 'NONE','failed_gate':','.join(sorted(set(failed))) or 'NONE_RECORDED','reason_code':race.get('shadow_race_state','NOT_RECORDED_IN_ARTIFACT'),'final_state':p.get('race_decision','NOT_RECORDED_IN_ARTIFACT'),'missing_evaluators':sum(len(h.get('missing_evaluators',[])) for h in horses),'imputation_state':'NOT_RECORDED_IN_ARTIFACT','course_profile_matched_all':all(h.get('course_profile_matched') is True for h in horses)}
  rows.append(rec)
  if 'tokyo' in rid and race.get('shadow_race_state')=='SKIP':patterns.append(rec['failed_gate'])
 return rows,('risk/reliability/quality gates; no missing-evaluator evidence' if patterns else 'NOT_RECORDED_IN_ARTIFACT')

def main()->None:
 if OUT.exists():raise RuntimeError('STOP_OUTPUT_ALREADY_EXISTS')
 OUT.mkdir(parents=True); dates=['20261010','20261011']; pres={d:frozen(d) for d in dates}; outs={d:outcomes(d,pres[d]) for d in dates}
 daily=[]; pooled=[]; inc=[]; overlap=[]; source=[]
 for d in dates:
  p=pres[d]; o=outs[d]; source += [{'date':d,'path':str(x.relative_to(ROOT)),'sha256':sha(x)} for x in [p['source_paths']['current']/'prediction_manifest.json',p['source_paths']['independent']/'selection_manifest.json',p['source_paths']['tc']/'horse_level_trace.json',p['source_paths']['daily']/'selection.json',p['source_paths']['formal']/'dual_pre_semantic.json']]
  raw=ROOT/'data/raw/target/daily_result_list'; source += [{'date':d,'path':str(x.relative_to(ROOT)),'sha256':sha(x)} for x in [raw/f'馬番順着順_{d}.csv',raw/f'着順馬番_{d}.csv']]
  for name,lanes in COMBOS.items():daily.append({'date':d,'combination':name,**metric(selection_set(p,lanes),o),'same_budget_status':'SAME_BUDGET_NOT_DEFINABLE'})
  cur=selection_set(p,('CURRENT',))
  for name,lanes in [('DAILY',('DAILY_V5_SAME_VOLUME',)),('INDEPENDENT',('INDEPENDENT_V5',)),('FORMAL',('FORMAL_V5',)),('TC',('TRACKCONDITION_SEMANTIC',))]:
   added=selection_set(p,lanes)-cur; m=metric(added,o); inc.append({'date':d,'baseline':'CURRENT','added_lane':name,'incremental_selected_N':len(added),'incremental_top3_hits':m['Top3_hits'],'incremental_valid_N':m['valid_N']})
  for a,b in [('CURRENT','DAILY_V5_SAME_VOLUME'),('CURRENT','INDEPENDENT_V5'),('DAILY_V5_SAME_VOLUME','INDEPENDENT_V5'),('CURRENT','FORMAL_V5')]:
   x,y=selection_set(p,(a,)),selection_set(p,(b,)); both=x&y; overlap.append({'date':d,'left':a,'right':b,'overlap_horses':len(both),'union_horses':len(x|y),'jaccard':len(both)/len(x|y) if x|y else None,'left_unique_top3':metric(x-y,o)['Top3_hits'],'right_unique_top3':metric(y-x,o)['Top3_hits']})
 for name,lanes in COMBOS.items():
  combined=set().union(*(selection_set(pres[d],lanes) for d in dates)); outall={**outs['20261010'],**outs['20261011']}; pooled.append({'combination':name,**metric(combined,outall),'same_budget_status':'SAME_BUDGET_NOT_DEFINABLE'})
 # explicit AI+manual union; manual only is a frozen 10/10 source, 10/11 post source rows.
 manual={d:set() for d in dates}; post10=load(paths('20261010')['post']); manual['20261010']={(rid,str(n)) for rid,nums in post10['human_pre_frozen_selection'].items() for n in nums}
 post11=load(paths('20261011')['post']); manual['20261011']={(r['race_id'],str(r['horse_number'])) for r in post11['selected_result_join_rows'] if r.get('system')=='CHATGPT_SOURCE_ONLY_PRE'}
 for d in dates: daily.append({'date':d,'combination':'ALL_AI_UNION_PLUS_CHATGPT_MANUAL',**metric(selection_set(pres[d],COMBOS['ALL_AI_UNION'])|manual[d],outs[d]),'same_budget_status':'SAME_BUDGET_NOT_DEFINABLE'})
 for d in dates:
  added=manual[d]-selection_set(pres[d],('CURRENT',)); m=metric(added,outs[d]); inc.append({'date':d,'baseline':'CURRENT','added_lane':'CHATGPT_MANUAL','incremental_selected_N':len(added),'incremental_top3_hits':m['Top3_hits'],'incremental_valid_N':m['valid_N']})
 for name in ('DAILY','INDEPENDENT','FORMAL','TC','CHATGPT_MANUAL'):
  group=[r for r in inc if r['added_lane']==name]; inc.append({'date':'20261010_20261011','baseline':'CURRENT','added_lane':name,'incremental_selected_N':sum(r['incremental_selected_N'] for r in group),'incremental_top3_hits':sum(r['incremental_top3_hits'] for r in group),'incremental_valid_N':sum(r['incremental_valid_N'] for r in group)})
 allai=set().union(*(selection_set(pres[d],COMBOS['ALL_AI_UNION']) for d in dates)); allman=set().union(*manual.values()); pooled.append({'combination':'ALL_AI_UNION_PLUS_CHATGPT_MANUAL',**metric(allai|allman,{**outs['20261010'],**outs['20261011']}),'same_budget_status':'SAME_BUDGET_NOT_DEFINABLE'})
 trace,dominant=trace_1012()
 def csvout(name,rows):
  fields=sorted({k for r in rows for k in r}) if rows else []
  with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 csvout('daily_combination_metrics.csv',daily);csvout('pooled_combination_metrics.csv',pooled);csvout('incremental_top3_contribution.csv',inc);csvout('lane_overlap_matrix.csv',overlap);csvout('tokyo_skip_trace_20261012.csv',trace)
 diag='# Tokyo SKIP trace — 2026-10-12\n\n'+'\n'.join(f"- {r['race_id']}: state={r['reason_code']}; failed gates={r['failed_gate']}; candidate_count={r['candidate_count']}" for r in trace)+'\n\n- Dominant pattern: '+dominant+'\n- Course-dependent causal feature: NOT_RECORDED_IN_ARTIFACT (this diagnostic does not infer it).\n';(OUT/'tokyo_skip_diagnosis.md').write_text(diag,encoding='utf-8')
 best=max(pooled,key=lambda r:r['BUY_TOP3_RATE'] if r['BUY_TOP3_RATE'] is not None else -1); bestinc=max(inc,key=lambda r:r['incremental_top3_hits'])
 summary={'ANALYSIS_ROLE':'RESULT_DRIVEN_RETROSPECTIVE_DIAGNOSTIC_ONLY','PRE_CHANGED':False,'PREDICTION_RERUN':False,'TRAINING_EXECUTED':False,'PRODUCTION_CHANGED':False,'source_artifacts':source,'daily_metrics':daily,'pooled_metrics':pooled,'incremental_contributions':inc,'same_budget':'SAME_BUDGET_NOT_DEFINABLE where frozen ordering was not uniformly available','tokyo_skip_dominant_reason':dominant,'best_raw_rate_combination_descriptive_only':best['combination'],'best_incremental_coverage_combination_descriptive_only':bestinc['added_lane'],'NO_NEW_BUY_RULE_AUTHORIZED':True}
 dump(OUT/'summary.json',summary)
 lines=['# 2026-10-10 / 2026-10-11 Multi-lane Combination Diagnostic','','- Role: RESULT_DRIVEN_RETROSPECTIVE_DIAGNOSTIC_ONLY','- PRE selection was read from frozen artifacts before outcomes were joined.','- No prediction, training, or production change.','','## Pooled combinations','','| Combination | Hits / valid N | Rate |','|---|---:|---:|']+[f"| {r['combination']} | {r['Top3_hits']} / {r['valid_N']} | {r['BUY_TOP3_RATE']:.2%} |" for r in pooled]+['','## Incremental Top3 hits relative to Current','','| Date | Added lane | Added hits | Added valid N |','|---|---|---:|---:|']+[f"| {r['date']} | {r['added_lane']} | {r['incremental_top3_hits']} | {r['incremental_valid_N']} |" for r in inc]+['',f"- Tokyo SKIP dominant pattern: {dominant}",'','NO_NEW_BUY_RULE_AUTHORIZED = TRUE']
 (OUT/'summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 hashes={str(p.relative_to(OUT)):sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='artifact_hashes.json'};dump(OUT/'artifact_hashes.json',{'self_hash_excluded':True,'indexed_artifacts':hashes})
 print(json.dumps({'output':str(OUT),'best':best,'best_incremental':bestinc,'tokyo_skip':dominant},ensure_ascii=False))
if __name__=='__main__':main()
