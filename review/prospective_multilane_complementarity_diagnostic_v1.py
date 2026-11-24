"""Result-driven, read-only complementarity diagnostic for canonical prospective PREs."""
from __future__ import annotations
import csv, hashlib, json
from collections import defaultdict
from pathlib import Path
from typing import Any
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'reports/20260926_onward_multilane_complementarity_diagnostic_v1'
DATES=('20260926','20260927','20261003','20261004','20261010','20261011'); LANES=('CURRENT','DAILY_V5_SAME_VOLUME','INDEPENDENT_V5')
JA={'sapporo':'札幌','hakodate':'函館','fukushima':'福島','niigata':'新潟','tokyo':'東京','nakayama':'中山','chukyo':'中京','kyoto':'京都','hanshin':'阪神','kokura':'小倉'}
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p:Path)->Any:return json.loads(p.read_text(encoding='utf-8'))
def dump(p:Path,x:Any):p.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def K(rid,no):return rid,str(no)
def roots(date:str)->dict[str,Path]:
 if date=='20261010':return {'current':ROOT/'reports/prospective_prediction_20261010_v1','daily':ROOT/f'reports/daily_v5_same_volume_prospective/{date}_pre','independent':ROOT/f'reports/independent_race_selection_prospective/{date}_pre'}
 if date=='20261011':
  b=ROOT/'reports/20261011_official_pre_v1';return {'current':b/'current_frozen','daily':b/'daily_v5_same_volume','independent':b/'independent_v5'}
 return {'current':ROOT/f'reports/daily_pre_analysis_{date}/current_frozen','daily':ROOT/f'reports/daily_v5_same_volume_prospective/{date}_pre','independent':ROOT/f'reports/independent_race_selection_prospective/{date}_pre'}
def artifact_paths(r):return {'CURRENT':r['current']/'prediction_manifest.json','DAILY_V5_SAME_VOLUME':r['daily']/'selection.json','INDEPENDENT_V5':r['independent']/'selection_manifest.json'}
def frozen(date:str)->dict[str,Any]:
 r=roots(date); rec={};sel={x:defaultdict(set) for x in LANES}
 for x in load(r['current']/'race_index.json')['race_index']:
  p=load(r['current']/x['artifact']); ranked=p['ranked_results']; rid=p['race_id'];rec[rid]={'venue':str(ranked[0].get('venue') or rid.split('_')[-2]),'race_number':int(ranked[0].get('race_number') or rid.split('_')[-1][:-1]),'names':{str(h['horse_number']):h['horse_name'] for h in ranked},'state':p.get('buy_gate_trace',{}).get('race',{}).get('shadow_race_state'),'payload':p};sel['CURRENT'][rid]={str(h['horse_number']) for h in p.get('buys',[])}
 for x in load(r['daily']/'selection.json')['races']:sel['DAILY_V5_SAME_VOLUME'][x['race_id']]={str(h['horse_number']) for h in x.get('selected_horses',[])}
 for x in load(r['independent']/'selection_manifest.json')['races']:sel['INDEPENDENT_V5'][x['race_id']]={str(h['horse_number']) for h in x.get('selected_horses',[])}
 for lane in LANES:
  for rid in rec:sel[lane][rid]
 ids=set(rec)
 if any(set(sel[x])!=ids for x in LANES):raise RuntimeError(f'STOP_LANE_RACE_SET:{date}')
 man=load(r['current']/'prediction_manifest.json')
 if any(sha(r['current']/x['relative_path'])!=x['sha256'] for x in man['files']):raise RuntimeError(f'STOP_CURRENT_MANIFEST:{date}')
 return {'roots':r,'records':rec,'selection':sel,'artifact_paths':artifact_paths(r)}
def results(date:str,p:dict[str,Any]):
 raw=ROOT/'data/raw/target/daily_result_list'; pri=raw/f'馬番順着順_{date}.csv'; aux=raw/f'着順馬番_{date}.csv'; pair=validate_source_pair(pri,aux,date)
 if pair.get('status')!='PASS':raise RuntimeError(f'STOP_RESULT_PAIR:{date}')
 with pri.open(encoding='cp932',newline='') as f:rows={x[0]:x for x in csv.reader(f)}
 by={(x['venue_name'],int(x['race_number'])):k for k,x in pair['source_d_primary']['race_index'].items()};out={}
 for rid,r in p['records'].items():
  row=rows[by[(JA[r['venue']],r['race_number'])]]
  for no in r['names']:
   v=row[11+int(no)].strip();valid=v.isdigit() and int(v)>0;out[K(rid,no)]={'finish':int(v) if valid else None,'valid_result':valid,'actual_top3':bool(valid and int(v)<=3),'raw_result':v}
 return out,{'primary':pri,'auxiliary':aux,'pair':pair}
def S(p,lane):return {(rid,no) for rid,nos in p['selection'][lane].items() for no in nos}
def met(keys,out):
 v=[k for k in keys if out[k]['valid_result']];h=[k for k in v if out[k]['actual_top3']];rs={x[0] for x in keys};hr={x[0] for x in h}
 return {'selected_horses':len(keys),'unique_selected_N':len(keys),'valid_N':len(v),'Top3_hits':len(h),'BUY_TOP3_RATE':len(h)/len(v) if v else None,'selected_races':len(rs),'race_success_count':len(hr),'race_success_rate':len(hr)/len(rs) if rs else None,'average_selected_per_race':len(keys)/len(rs) if rs else None}
def union(p,lanes):return set().union(*(S(p,x) for x in lanes))
def state_class(state):
 if state=='PLAY_UNCONVERGED_4PLUS':return 'UNCONVERGED'
 if state=='SKIP':return 'SKIP'
 if state=='PLAY_CONVERGED':return 'BUY_SELECTION_FAILURE'
 return 'UNKNOWN'
def csvout(name,rows):
 fields=sorted({k for r in rows for k in r}) if rows else []
 with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def main():
 if OUT.exists():raise RuntimeError('STOP_OUTPUT_ALREADY_EXISTS')
 OUT.mkdir(parents=True);pres={d:frozen(d) for d in DATES};outs={};resmeta={}
 for d in DATES:outs[d],resmeta[d]=results(d,pres[d])
 index=[];daily=[];unions=[];incremental=[];exclusive=[];state_rows=[];failures=[];overlap=[];recovered=[]
 for d,p in pres.items():
  o=outs[d];arts=p['artifact_paths'];
  index.append({'date':d,'canonical_pre_path':str(arts['CURRENT'].parent.relative_to(ROOT)),'current_pre_sha256':sha(arts['CURRENT']),'target_races':len(p['records']),'result_join_completeness':'PASS','result_primary_path':str(resmeta[d]['primary'].relative_to(ROOT)),'result_primary_sha256':sha(resmeta[d]['primary']),'result_auxiliary_sha256':sha(resmeta[d]['auxiliary']),'official_1011_override':d=='20261011'})
  for lane in LANES:daily.append({'date':d,'lane':lane,**met(S(p,lane),o)})
  combo={'CURRENT_UNION_DAILY':('CURRENT','DAILY_V5_SAME_VOLUME'),'CURRENT_UNION_INDEPENDENT':('CURRENT','INDEPENDENT_V5'),'DAILY_UNION_INDEPENDENT':('DAILY_V5_SAME_VOLUME','INDEPENDENT_V5'),'CURRENT_UNION_DAILY_UNION_INDEPENDENT':LANES}
  for n,ls in combo.items():unions.append({'scope':'daily','date':d,'combination':n,**met(union(p,ls),o)})
  current=S(p,'CURRENT');dailyset=S(p,'DAILY_V5_SAME_VOLUME');ind=S(p,'INDEPENDENT_V5')
  for label,base,added,lane in [('CURRENT_PLUS_DAILY',current,dailyset,'DAILY_V5_SAME_VOLUME'),('CURRENT_PLUS_INDEPENDENT',current,ind,'INDEPENDENT_V5'),('CURRENT_DAILY_PLUS_INDEPENDENT',current|dailyset,ind,'INDEPENDENT_V5'),('CURRENT_INDEPENDENT_PLUS_DAILY',current|ind,dailyset,'DAILY_V5_SAME_VOLUME')]:
   plus=added-base;m=met(plus,o);incremental.append({'scope':'daily','date':d,'comparison':label,'source_lane':lane,'incremental_selected_N':len(plus),'incremental_Top3_hits':m['Top3_hits'],'incremental_hit_rate':m['BUY_TOP3_RATE']})
   for rid,no in sorted(plus):
    if o[K(rid,no)]['actual_top3'] and o[K(rid,no)]['valid_result']:
     r=p['records'][rid];recovered.append({'date':d,'venue':JA[r['venue']],'race':r['race_number'],'race_id':rid,'horse_number':int(no),'horse_name':r['names'][no],'source_lane':lane,'comparison':label,'current_state':r['state']})
  for rid,no in union(p,LANES):
   members=[x for x in LANES if no in p['selection'][x][rid]]
   bucket={'CURRENT'}==set(members) and 'CURRENT_ONLY' or {'DAILY_V5_SAME_VOLUME'}==set(members) and 'DAILY_ONLY' or {'INDEPENDENT_V5'}==set(members) and 'INDEPENDENT_ONLY' or set(members)=={'CURRENT','DAILY_V5_SAME_VOLUME'} and 'CURRENT_DAILY' or set(members)=={'CURRENT','INDEPENDENT_V5'} and 'CURRENT_INDEPENDENT' or set(members)=={'DAILY_V5_SAME_VOLUME','INDEPENDENT_V5'} and 'DAILY_INDEPENDENT' or set(members)==set(LANES) and 'ALL_THREE' or 'OTHER'
   exclusive.append({'date':d,'bucket':bucket,'selected':1,'valid':int(o[K(rid,no)]['valid_result']),'hit':int(o[K(rid,no)]['actual_top3'] and o[K(rid,no)]['valid_result'])})
  for state in ('PLAY_CONVERGED','PLAY_UNCONVERGED_4PLUS','SKIP'):
   rids=[rid for rid,r in p['records'].items() if r['state']==state]
   for lane in ('DAILY_V5_SAME_VOLUME','INDEPENDENT_V5'):
    add={(rid,no) for rid in rids for no in p['selection'][lane][rid] if no not in p['selection']['CURRENT'][rid]};miss={(rid,no) for rid in rids for no in p['records'][rid]['names'] if no not in p['selection']['CURRENT'][rid] and o[K(rid,no)]['valid_result'] and o[K(rid,no)]['actual_top3']};rec=add&miss
    state_rows.append({'date':d,'current_state':state,'lane':lane,'races':len(rids),'additional_selection_N':len(add),'current_nonselected_top3_N':len(miss),'recovered_top3_hits':len(rec),'recovery_rate':len(rec)/len(miss) if miss else None})
  for rid,r in p['records'].items():
   currenthits={no for no in p['selection']['CURRENT'][rid] if o[K(rid,no)]['valid_result'] and o[K(rid,no)]['actual_top3']}
   if currenthits:continue
   top={no for no in r['names'] if o[K(rid,no)]['valid_result'] and o[K(rid,no)]['actual_top3']};dh=top&p['selection']['DAILY_V5_SAME_VOLUME'][rid];ih=top&p['selection']['INDEPENDENT_V5'][rid]
   bucket='Both recovery' if dh and ih else 'Daily recovery' if dh else 'Independent recovery' if ih else 'Neither';failures.append({'date':d,'race_id':rid,'current_state':r['state'],'failure_reason':state_class(r['state']),'recovery_bucket':bucket,'top3_not_current_N':len(top),'daily_recovered_N':len(dh),'independent_recovered_N':len(ih)})
  for a,b in [('CURRENT','DAILY_V5_SAME_VOLUME'),('CURRENT','INDEPENDENT_V5'),('DAILY_V5_SAME_VOLUME','INDEPENDENT_V5')]:
   x,y=S(p,a),S(p,b);both=x&y;overlap.append({'scope':'daily','date':d,'left':a,'right':b,'overlap_horses':len(both),'union_horses':len(x|y),'Jaccard':len(both)/len(x|y) if x|y else None,'overlap_Top3_hits':met(both,o)['Top3_hits'],'left_unique_Top3_hits':met(x-y,o)['Top3_hits'],'right_unique_Top3_hits':met(y-x,o)['Top3_hits']})
 allout={k:v for d in DATES for k,v in outs[d].items()};
 for lane in LANES:daily.append({'date':'POOLED','lane':lane,**met(set().union(*(S(pres[d],lane) for d in DATES)),allout)})
 for n,ls in {'CURRENT_UNION_DAILY':('CURRENT','DAILY_V5_SAME_VOLUME'),'CURRENT_UNION_INDEPENDENT':('CURRENT','INDEPENDENT_V5'),'DAILY_UNION_INDEPENDENT':('DAILY_V5_SAME_VOLUME','INDEPENDENT_V5'),'CURRENT_UNION_DAILY_UNION_INDEPENDENT':LANES}.items():unions.append({'scope':'POOLED','date':'POOLED','combination':n,**met(set().union(*(union(pres[d],ls) for d in DATES)),allout)})
 for label,base_l,add_l,lane in [('CURRENT_PLUS_DAILY',('CURRENT',),('DAILY_V5_SAME_VOLUME',),'DAILY_V5_SAME_VOLUME'),('CURRENT_PLUS_INDEPENDENT',('CURRENT',),('INDEPENDENT_V5',),'INDEPENDENT_V5'),('CURRENT_DAILY_PLUS_INDEPENDENT',('CURRENT','DAILY_V5_SAME_VOLUME'),('INDEPENDENT_V5',),'INDEPENDENT_V5'),('CURRENT_INDEPENDENT_PLUS_DAILY',('CURRENT','INDEPENDENT_V5'),('DAILY_V5_SAME_VOLUME',),'DAILY_V5_SAME_VOLUME')]:
  base=set().union(*(union(pres[d],base_l) for d in DATES));add=set().union(*(union(pres[d],add_l) for d in DATES))-base;m=met(add,allout);incremental.append({'scope':'POOLED','date':'POOLED','comparison':label,'source_lane':lane,'incremental_selected_N':len(add),'incremental_Top3_hits':m['Top3_hits'],'incremental_hit_rate':m['BUY_TOP3_RATE']})
 for a,b in [('CURRENT','DAILY_V5_SAME_VOLUME'),('CURRENT','INDEPENDENT_V5'),('DAILY_V5_SAME_VOLUME','INDEPENDENT_V5')]:
  x=set().union(*(S(pres[d],a) for d in DATES));y=set().union(*(S(pres[d],b) for d in DATES));both=x&y;overlap.append({'scope':'POOLED','date':'POOLED','left':a,'right':b,'overlap_horses':len(both),'union_horses':len(x|y),'Jaccard':len(both)/len(x|y) if x|y else None,'overlap_Top3_hits':met(both,allout)['Top3_hits'],'left_unique_Top3_hits':met(x-y,allout)['Top3_hits'],'right_unique_Top3_hits':met(y-x,allout)['Top3_hits']})
 buckets=[]
 for d in list(DATES)+['POOLED']:
  x=[r for r in exclusive if d=='POOLED' or r['date']==d]
  for b in ('CURRENT_ONLY','DAILY_ONLY','INDEPENDENT_ONLY','CURRENT_DAILY','CURRENT_INDEPENDENT','DAILY_INDEPENDENT','ALL_THREE','OTHER'):
   z=[r for r in x if r['bucket']==b];v=sum(r['valid'] for r in z);h=sum(r['hit'] for r in z);buckets.append({'date':d,'bucket':b,'selected_N':len(z),'valid_N':v,'Top3_hits':h,'Top3_rate':h/v if v else None})
 for name,rows in [('daily_lane_metrics.csv',daily),('pooled_lane_metrics.csv',[r for r in daily if r['date']=='POOLED']),('union_metrics.csv',unions),('incremental_contribution.csv',incremental),('exclusive_hit_buckets.csv',buckets),('current_state_recovery.csv',state_rows),('failure_recovery.csv',failures),('overlap_matrix.csv',overlap),('recovered_top3_horses.csv',recovered)]:csvout(name,rows)
 evidence_races=sum(len(pres[d]['records']) for d in DATES);band='WEAK' if 30<=evidence_races<=39 else 'MODERATE' if 40<=evidence_races<=59 else 'STRONG' if 60<=evidence_races<=79 else 'VERY_STRONG' if evidence_races>=80 else 'DIRECTIONAL_WATCH' if evidence_races>=20 else 'OBSERVATION_ONLY' if evidence_races>=10 else 'TOO_SMALL'
 canonical={'analysis_role':'RESULT_DRIVEN_RETROSPECTIVE_DIAGNOSTIC_ONLY','dates':list(DATES),'official_20261011_override':True,'inputs':index,'same_budget':'SAME_BUDGET_NOT_DEFINABLE','evidence_races':evidence_races,'evidence_band':band,'result_access_for_diagnostic':True,'pre_changed':False,'prediction_rerun':False,'training_executed':False,'production_changed':False};dump(OUT/'canonical_input_index.json',canonical)
 pooled={r['lane']:r for r in daily if r['date']=='POOLED'};incpool={r['comparison']:r for r in incremental if r['scope']=='POOLED'};statepool=[]
 for state in ('PLAY_UNCONVERGED_4PLUS','SKIP'):
  z=[r for r in state_rows if r['current_state']==state and r['lane']=='INDEPENDENT_V5'];statepool.append((state,sum(r['recovered_top3_hits'] for r in z),sum(r['current_nonselected_top3_N'] for r in z)))
 lines=['# Prospective Multi-Lane Complementarity Diagnostic','','`ANALYSIS_ROLE = RESULT_DRIVEN_RETROSPECTIVE_DIAGNOSTIC_ONLY`',f'`DATE_SCOPE = 2026-09-26 to 2026-10-11`',f'`EVIDENCE_DATES = {len(DATES)}`',f'`EVIDENCE_RACES = {evidence_races}`',f'`EVIDENCE_BAND = {band}`','','## Pooled base lanes','','| Lane | Hits / valid N | Rate |','|---|---:|---:|']+[f"| {x} | {pooled[x]['Top3_hits']} / {pooled[x]['valid_N']} | {pooled[x]['BUY_TOP3_RATE']:.2%} |" for x in LANES]+['','## Pooled incremental','','| Comparison | Added hits / N | Rate |','|---|---:|---:|']+[f"| {x} | {r['incremental_Top3_hits']} / {r['incremental_selected_N']} | {r['incremental_hit_rate']:.2%} |" for x,r in incpool.items()]+['',f"- Independent recovery in UNCONVERGED: {dict((s,(h,n)) for s,h,n in statepool).get('PLAY_UNCONVERGED_4PLUS',(0,0))[0]} / {dict((s,(h,n)) for s,h,n in statepool).get('PLAY_UNCONVERGED_4PLUS',(0,0))[1]}",f"- Independent recovery in SKIP: {dict((s,(h,n)) for s,h,n in statepool).get('SKIP',(0,0))[0]} / {dict((s,(h,n)) for s,h,n in statepool).get('SKIP',(0,0))[1]}",'','`NO_NEW_BUY_RULE_AUTHORIZED = TRUE`','`READY_FOR_CHATGPT_CLAUDE_INTEGRATED_JUDGMENT = YES`']
 (OUT/'summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');hashes={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='artifact_hashes.json'};dump(OUT/'artifact_hashes.json',{'self_hash_excluded':True,'indexed_artifacts':hashes});print(json.dumps({'dates':DATES,'evidence_races':evidence_races,'band':band,'pooled':pooled,'incremental':incpool,'state':statepool},ensure_ascii=False))
if __name__=='__main__':main()
