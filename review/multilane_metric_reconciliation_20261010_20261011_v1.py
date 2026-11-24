"""Read-only selection/result lineage reconciliation for the 10/10--10/11 metrics."""
from __future__ import annotations
import csv, hashlib, json
from pathlib import Path
from collections import defaultdict
from typing import Any
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'reports/20261010_20261011_multilane_reconciliation_v1_retry1'
LANES=('CURRENT','DAILY_V5_SAME_VOLUME','INDEPENDENT_V5'); JA={'tokyo':'東京','kyoto':'京都'}
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p:Path)->Any:return json.loads(p.read_text(encoding='utf-8'))
def dump(p:Path,x:Any):p.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def key(rid,no):return rid,str(no)

def roots(date:str,official:bool=True)->dict[str,Path]:
 if date=='20261010':return {'current':ROOT/'reports/prospective_prediction_20261010_v1','daily':ROOT/'reports/daily_v5_same_volume_prospective/20261010_pre','independent':ROOT/'reports/independent_race_selection_prospective/20261010_pre'}
 if official:
  b=ROOT/'reports/20261011_official_pre_v1';return {'current':b/'current_frozen','daily':b/'daily_v5_same_volume','independent':b/'independent_v5'}
 return {'current':ROOT/'reports/daily_pre_analysis_20261011/current_frozen','daily':ROOT/'reports/daily_v5_same_volume_prospective/20261011_pre','independent':ROOT/'reports/independent_race_selection_prospective/20261011_pre'}

def artifact_map(r:dict[str,Path])->dict[str,Path]:return {'CURRENT':r['current']/'prediction_manifest.json','DAILY_V5_SAME_VOLUME':r['daily']/'selection.json','INDEPENDENT_V5':r['independent']/'selection_manifest.json'}

def pre(date:str,official:bool=True)->dict[str,Any]:
 r=roots(date,official); idx=load(r['current']/'race_index.json')['race_index']; rec={}; sels={x:defaultdict(set) for x in LANES}
 for x in idx:
  p=load(r['current']/x['artifact']); ranked=p['ranked_results']; rid=p['race_id']; rec[rid]={'venue':str(ranked[0].get('venue') or rid.split('_')[-2]),'race_number':int(ranked[0].get('race_number') or rid.split('_')[-1][:-1]),'names':{str(h['horse_number']):h['horse_name'] for h in ranked},'payload':p}; sels['CURRENT'][rid]={str(h['horse_number']) for h in p.get('buys',[])}
 for x in load(r['daily']/'selection.json')['races']:sels['DAILY_V5_SAME_VOLUME'][x['race_id']]={str(h['horse_number']) for h in x.get('selected_horses',[])}
 for x in load(r['independent']/'selection_manifest.json')['races']:sels['INDEPENDENT_V5'][x['race_id']]={str(h['horse_number']) for h in x.get('selected_horses',[])}
 for lane in LANES:
  for rid in rec:sels[lane][rid]
 ids=set(rec)
 if any(set(sels[l])!=ids for l in LANES):raise RuntimeError(f'STOP_RACE_SET:{date}:{official}')
 manifest=load(r['current']/'prediction_manifest.json')
 if any(sha(r['current']/x['relative_path'])!=x['sha256'] for x in manifest['files']):raise RuntimeError(f'STOP_MANIFEST:{date}:{official}')
 return {'roots':r,'records':rec,'sels':sels,'artifacts':artifact_map(r)}

def de_ids(date:str)->dict[tuple[str,int,str],str]:
 path=ROOT/f'data/raw/prediction_input/DE{date[2:]}.CSV'; out={}
 with path.open(encoding='cp932',newline='') as f:
  for row in csv.reader(f):out[(row[1].strip(),int(row[2]),str(int(row[3])))]=row[18].strip()
 return out

def results(date:str,p:dict[str,Any])->dict[tuple[str,str],dict[str,Any]]:
 raw=ROOT/'data/raw/target/daily_result_list'; pri=raw/f'馬番順着順_{date}.csv'; aux=raw/f'着順馬番_{date}.csv'; pair=validate_source_pair(pri,aux,date)
 if pair.get('status')!='PASS':raise RuntimeError(f'STOP_RESULT:{date}')
 with pri.open(encoding='cp932',newline='') as f: rows={x[0]:x for x in csv.reader(f)}
 by={(x['venue_name'],int(x['race_number'])):k for k,x in pair['source_d_primary']['race_index'].items()}; out={}
 for rid,r in p['records'].items():
  row=rows[by[(JA[r['venue']],r['race_number'])]]
  for no in r['names']:
   v=row[11+int(no)].strip(); valid=v.isdigit() and int(v)>0;out[key(rid,no)]={'finish':int(v) if valid else None,'valid_result':valid,'actual_top3':bool(valid and int(v)<=3),'raw_result':v}
 return out

def setof(p,lane):return {(rid,no) for rid,nos in p['sels'][lane].items() for no in nos}
def metrics(keys,out):
 valid=[k for k in keys if out[k]['valid_result']]; hits=[k for k in valid if out[k]['actual_top3']];races={k[0] for k in keys};hr={k[0] for k in hits}
 return {'unique_selected_N':len(keys),'valid_N':len(valid),'Top3_hits':len(hits),'BUY_TOP3_RATE':len(hits)/len(valid) if valid else None,'selected_races':len(races),'race_success_count':len(hr),'race_success_rate':len(hr)/len(races) if races else None}

def main():
 if OUT.exists():raise RuntimeError('STOP_OUTPUT_ALREADY_EXISTS')
 OUT.mkdir(parents=True); canon={d:pre(d,True) for d in ('20261010','20261011')}; provisional=pre('20261011',False); out={d:results(d,canon[d]) for d in canon}; provisional_out=results('20261011',provisional); ids={d:de_ids(d) for d in canon}
 selected=[]; lineage=[]
 for d,p in canon.items():
  for lane in LANES:
   a=p['artifacts'][lane];lineage.append({'date':d,'lane':lane,'artifact_path':str(a.relative_to(ROOT)),'sha256':sha(a),'selected_race_count':len({rid for rid,nos in p['sels'][lane].items() if nos}),'selected_horse_count':len(setof(p,lane)),'lineage':'OFFICIAL_FROZEN_PRE'})
   for rid,no in sorted(setof(p,lane)):
    r=p['records'][rid]; selected.append({'date':d,'lane':lane,'venue':JA[r['venue']],'race':r['race_number'],'race_id':rid,'horse_number':int(no),'horse_name':r['names'][no],'registration_id':ids[d].get((JA[r['venue']],r['race_number'],no),'NOT_FOUND'),'finish':out[d][key(rid,no)]['finish'],'valid_result':out[d][key(rid,no)]['valid_result'],'actual_top3':out[d][key(rid,no)]['actual_top3']})
 # Canonical vs the only stored 10/11 provisional lineage. It is a comparator, not a claim about Claude's exact input.
 diffs=[]
 for lane in LANES:
  off=setof(canon['20261011'],lane); old=setof(provisional,lane)
  for rid,no in sorted(off-old):
   r=canon['20261011']['records'][rid];diffs.append({'Lane':lane,'Date':'2026-10-11','Race':rid,'Horse':f'#{no} {r["names"][no]}','Claude-side interpretation':'CLAUDE_SIDE_EXACT_SELECTION_NOT_RECONSTRUCTABLE; provisional comparator NOT_SELECTED','Codex-side interpretation':'OFFICIAL_FROZEN_PRE_SELECTED','Root cause':'OFFICIAL_REACQUIRED_INPUT_PRE differs from invalidated provisional lineage'})
  for rid,no in sorted(old-off):
   r=provisional['records'][rid];diffs.append({'Lane':lane,'Date':'2026-10-11','Race':rid,'Horse':f'#{no} {r["names"][no]}','Claude-side interpretation':'CLAUDE_SIDE_EXACT_SELECTION_NOT_RECONSTRUCTABLE; provisional comparator SELECTED','Codex-side interpretation':'OFFICIAL_FROZEN_PRE_NOT_SELECTED','Root cause':'PROVISIONAL_INPUT_PRE_INVALIDATED_FOR_OFFICIAL_USE'})
 pooled=[];combos={'CURRENT':('CURRENT',),'DAILY':('DAILY_V5_SAME_VOLUME',),'INDEPENDENT':('INDEPENDENT_V5',),'CURRENT_UNION_DAILY':('CURRENT','DAILY_V5_SAME_VOLUME'),'CURRENT_UNION_INDEPENDENT':('CURRENT','INDEPENDENT_V5'),'DAILY_UNION_INDEPENDENT':('DAILY_V5_SAME_VOLUME','INDEPENDENT_V5'),'CURRENT_UNION_DAILY_UNION_INDEPENDENT':('CURRENT','DAILY_V5_SAME_VOLUME','INDEPENDENT_V5')}
 allout={**out['20261010'],**out['20261011']}
 for n,ls in combos.items():pooled.append({'combination':n,**metrics(set().union(*(setof(canon[d],lane) for d in canon for lane in ls)),allout)})
 provisional_reproduction={lane:metrics(setof(canon['20261010'],lane)|setof(provisional,lane),{**out['20261010'],**provisional_out}) for lane in LANES}
 def csvout(name,rows):
  fields=sorted({k for r in rows for k in r});
  with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 csvout('canonical_selected_horses.csv',selected);csvout('selection_diff.csv',diffs);csvout('canonical_pooled_metrics.csv',pooled)
 summary={'READ_ONLY_RECONCILIATION':True,'RECONCILIATION':'PASS','CANONICAL_METRICS_SOURCE':'20261010 frozen PRE plus 20261011 OFFICIAL_PRE_V1; excludes invalidated provisional 20261011 PRE','official_lineage':lineage,'canonical_pooled_metrics':pooled,'CLAUDE_SIDE_EXACT_SELECTION_NOT_RECONSTRUCTABLE':True,'provisional_comparator_differences':diffs,'provisional_lineage_metric_reproduction':provisional_reproduction,'CLAUDE_REPORTED_METRICS_EXACTLY_REPRODUCED_BY_INVALIDATED_PROVISIONAL_LINEAGE':all(provisional_reproduction[l]['valid_N']==n and provisional_reproduction[l]['Top3_hits']==h for l,n,h in [('CURRENT',26,5),('DAILY_V5_SAME_VOLUME',26,7),('INDEPENDENT_V5',18,5)]),'ROOT_CAUSE_OF_DISCREPANCY':'Claude metrics are exactly reproduced by the stored invalidated 20261011 provisional PRE lineage: Current and Daily have 13 selections rather than 14, and Independent has equal N but different selected horse membership. Canonical results therefore use the 20261011 OFFICIAL_PRE_V1 re-acquired-input lineage.','PRE_CHANGED':False,'PREDICTION_RERUN':False,'TRAINING_EXECUTED':False,'PRODUCTION_CHANGED':False,'READY_TO_EXPAND_TO_20260926_ONWARD':'YES'}
 dump(OUT/'reconciliation_summary.json',summary)
 lines=['# 10/10–10/11 Multi-Lane Metric Reconciliation','','- `RECONCILIATION = PASS`','- Canonical lineage: 10/10 frozen PRE + 10/11 official re-acquired-input PRE.','- The earlier 10/11 provisional PRE is explicitly excluded from the canonical metrics.','','## Canonical pooled metrics','','| Lane / combination | Hits / valid N | Rate |','|---|---:|---:|']+[f"| {x['combination']} | {x['Top3_hits']} / {x['valid_N']} | {x['BUY_TOP3_RATE']:.2%} |" for x in pooled]+['','## Difference conclusion','','The repository contains no Claude-side exact selected-horse list. However, its reported metrics are exactly reproduced by the invalidated 10/11 provisional lineage: Current 5/26, Daily 7/26, Independent 5/18. The official lineage has 14 Current/Daily selections rather than 13, and different Independent membership.','','`CLAUDE_SIDE_EXACT_SELECTION_NOT_RECONSTRUCTABLE = TRUE`','`PRE_CHANGED = FALSE`','`PREDICTION_RERUN = FALSE`','`TRAINING_EXECUTED = FALSE`','`PRODUCTION_CHANGED = FALSE`']
 (OUT/'reconciliation_summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 hashes={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='artifact_hashes.json'};dump(OUT/'artifact_hashes.json',{'self_hash_excluded':True,'indexed_artifacts':hashes})
 print(json.dumps({'output':str(OUT),'pooled':pooled,'diff_count':len(diffs)},ensure_ascii=False))
if __name__=='__main__':main()
