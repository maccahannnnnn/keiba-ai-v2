"""One-shot December 2025 POST join; reads results only after the consumed marker."""
from __future__ import annotations
import csv, hashlib, json
from collections import Counter
from pathlib import Path
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT=Path(__file__).resolve().parents[1]
FORMAL=ROOT/'reports/december_2025_three_lane_one_shot_holdout_pre'; DIAG=ROOT/'reports/december_2025_all_frozen_systems_diagnostic_pre'
ANALYSIS=ROOT/'reports/december_2025_pre_result_selection_analysis'; OUT=ROOT/'reports/december_2025_one_shot_post'; STATE=ROOT/'reports/december_2025_three_lane_one_shot_holdout_state/CONSUMED'; RAW=ROOT/'data/raw/target/daily_result_list'
DATES=('20251206','20251207','20251213','20251214','20251220','20251221','20251227','20251228')
SYSTEMS=('CURRENT','INDEPENDENT_V5','TRACKCONDITION_SEMANTIC','FORMAL_V5','FORMAL_V6','CF_TOP3_RANK_ANCHORED','DAILY_V5_REFERENCE','V4_MODEL_V3_REFERENCE')
EXPECTED={'artifact_hashes.json':('228f9dd3e45a769054d3c3a25ea98c8777a19506bd6257d97b01d0645c9b09d5',FORMAL),'diagnostic':('d7cad92676d018b0715ac0d63a5312b73eed28759905eefa444b04260220932d',DIAG),'analysis':('c70e21485487540666c984a99c5584efa3546bd0c3589e362694ddb69fc3e83f',ANALYSIS)}
VENUE={'札幌':'sapporo','函館':'hakodate','福島':'fukushima','新潟':'niigata','東京':'tokyo','中山':'nakayama','中京':'chuukyou','京都':'kyoto','阪神':'hanshin','小倉':'kokura'}
ABNORMAL={'中止','除外','取消','失格'}
EXCLUDED='race_20251213_hanshin_8R'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p,x): Path(p).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def metric(rows):
 v=[x for x in rows if x['valid_result']]; h=[x for x in v if x['actual_top3']]
 return {'selected_n':len(rows),'invalid_n':len(rows)-len(v),'valid_n':len(v),'hits':len(h),'rate':len(h)/len(v) if v else None,'selected_races':len({x['race_id'] for x in rows}),'successful_buy_races':len({x['race_id'] for x in h}),'buy_zero_dates':sorted(set(DATES)-{x['date'] for x in rows})}
def select(rows,s): return [x for x in rows if x['systems'][s]=='SELECTED']
def run():
 if OUT.exists() or STATE.exists(): raise RuntimeError('STOP_OUTPUT_OR_CONSUMED_EXISTS')
 if sha(FORMAL/'artifact_hashes.json')!=EXPECTED['artifact_hashes.json'][0] or sha(DIAG/'artifact_hashes.json')!=EXPECTED['diagnostic'][0] or sha(ANALYSIS/'artifact_hashes.json')!=EXPECTED['analysis'][0]: raise RuntimeError('STOP_PRE_FREEZE_SHA_MISMATCH')
 files=[]
 for date in DATES:
  files += [RAW/f'馬番順着順_{date}.csv',RAW/f'着順馬番_{date}.csv']
 if any(not p.is_file() for p in files): raise RuntimeError('STOP_RESULT_SOURCE_MISSING')
 STATE.parent.mkdir(parents=True,exist_ok=True); dump(STATE,{'status':'CONSUMED','reason':'DECEMBER_2025_ONE_SHOT_POST_RESULT_OPEN','pre_artifact_indices':{k:v[0] for k,v in EXPECTED.items()},'result_paths':[str(p.relative_to(ROOT)) for p in files]})
 source={}; result={}
 for date in DATES:
  primary,aux=RAW/f'馬番順着順_{date}.csv',RAW/f'着順馬番_{date}.csv'; source[date]={'primary':str(primary.relative_to(ROOT)),'auxiliary':str(aux.relative_to(ROOT)),'primary_sha256':sha(primary),'auxiliary_sha256':sha(aux),'schema':validate_source_pair(primary,aux,date)}
  with primary.open(encoding='cp932',newline='') as f: rows=list(csv.reader(f))
  for row in rows: result[(date,VENUE[row[1]],int(row[2]))]=row
 bitmap=read(DIAG/'system_selection_bitmap.json'); population=read(FORMAL/'population_freeze.json'); pre=read(FORMAL/'current_pre.json')
 names={(p['date'],p['race_id'],int(h['horse_number'])):h.get('horse_name') for p in pre['predictions'] for h in p['ranked_results']}
 joined=[]; invalid=0
 for x in bitmap:
  date=x['race_id'].split('_')[1]; _,_,venue,rno=x['race_id'].rsplit('_',3); key=(date,venue,int(rno[:-1]))
  if x['race_id']==EXCLUDED: continue
  row=result.get(key)
  if row is None: raise RuntimeError('STOP_RESULT_RACE_JOIN_MISSING:'+x['race_id'])
  raw=row[11+int(x['horse_number'])]; valid=raw.isdigit() and int(raw)>0
  if not valid and raw not in ABNORMAL and raw!='0': raise RuntimeError('STOP_UNKNOWN_RESULT_STATUS:'+raw)
  finish=int(raw) if valid else None; invalid += not valid
  joined.append({**x,'date':date,'horse_name':names.get((date,x['race_id'],int(x['horse_number']))),'actual_finish':finish,'valid_result':valid,'actual_top3':bool(valid and finish<=3)})
 performance={s:{'role':'FORMAL' if s in SYSTEMS[:5] else 'DIAGNOSTIC',**metric(select(joined,s))} for s in SYSTEMS}; current=performance['CURRENT']
 versus={}
 for s in SYSTEMS[1:]:
  m=performance[s]; rd=(m['rate']-current['rate']) if m['rate'] is not None and current['rate'] is not None else None; hd=m['hits']-current['hits']; versus[s]={'rate_delta_vs_current':rd,'hit_delta_vs_current':hd,'horse_volume_ratio':m['selected_n']/current['selected_n'],'race_volume_ratio':m['selected_races']/current['selected_races'],'interpretation':'SUPPORTIVE' if rd>=0 and hd>=0 else 'WARNING' if (rd>=0 and hd<0) or (rd<0 and hd>0) else 'CONTRADICTION'}
 def group(condition): return metric([x for x in joined if condition(x)])
 sets={s:{(x['race_id'],x['horse_number']) for x in select(joined,s)} for s in SYSTEMS}
 v5v6={'v5':performance['FORMAL_V5'],'v6':performance['FORMAL_V6'],'v5_only':group(lambda x:(x['race_id'],x['horse_number']) in sets['FORMAL_V5']-sets['FORMAL_V6']),'v6_only':group(lambda x:(x['race_id'],x['horse_number']) in sets['FORMAL_V6']-sets['FORMAL_V5'])}
 v5v6['raw_hit_delta_v6_minus_v5']=performance['FORMAL_V6']['hits']-performance['FORMAL_V5']['hits']; v5v6['rate_delta_v6_minus_v5']=performance['FORMAL_V6']['rate']-performance['FORMAL_V5']['rate']
 ind=sets['INDEPENDENT_V5']; cur=sets['CURRENT']; tc=sets['TRACKCONDITION_SEMANTIC']; state={p['race_id']:p['buy_gate_trace']['race']['shadow_race_state'] for p in pre['predictions']}
 ind_out={'common':group(lambda x:(x['race_id'],x['horse_number']) in ind&cur),'independent_only':group(lambda x:(x['race_id'],x['horse_number']) in ind-cur),'added_from_UNCONVERGED':group(lambda x:(x['race_id'],x['horse_number']) in ind-cur and state[x['race_id']].startswith('PLAY_UNCONVERGED')),'added_from_SKIP':group(lambda x:(x['race_id'],x['horse_number']) in ind-cur and state[x['race_id']]=='SKIP'),'current_dropped':group(lambda x:(x['race_id'],x['horse_number']) in cur-ind)}
 tc_out={'common':group(lambda x:(x['race_id'],x['horse_number']) in tc&cur),'tc_only':group(lambda x:(x['race_id'],x['horse_number']) in tc-cur),'current_only':group(lambda x:(x['race_id'],x['horse_number']) in cur-tc)}
 daily={'daily_only':group(lambda x:(x['race_id'],x['horse_number']) in sets['DAILY_V5_REFERENCE']-sets['V4_MODEL_V3_REFERENCE']),'v3_only':group(lambda x:(x['race_id'],x['horse_number']) in sets['V4_MODEL_V3_REFERENCE']-sets['DAILY_V5_REFERENCE'])}
 unique={s:{'current_missed_top3_recovered':sum(x['actual_top3'] and (x['race_id'],x['horse_number']) not in cur for x in select(joined,s))} for s in SYSTEMS if s!='CURRENT'}
 detail=[{'date':x['date'],'race_id':x['race_id'],'horse_number':x['horse_number'],'horse_name':x['horse_name'],'actual_finish':x['actual_finish'],'selected_by_systems':[s for s in SYSTEMS if x['systems'][s]=='SELECTED']} for x in joined if x['actual_top3'] and (x['race_id'],x['horse_number']) not in cur and any(x['systems'][s]=='SELECTED' for s in SYSTEMS[1:])]
 pairs={}
 for a in SYSTEMS:
  for b in SYSTEMS:
   if a<b: pairs[f'{a}__{b}']={'common':group(lambda x,a=a,b=b:(x['race_id'],x['horse_number']) in sets[a]&sets[b]),'a_only':group(lambda x,a=a,b=b:(x['race_id'],x['horse_number']) in sets[a]-sets[b]),'b_only':group(lambda x,a=a,b=b:(x['race_id'],x['horse_number']) in sets[b]-sets[a])}
 agreement={}
 for k in ('system_selection_count','unique_model_family_selection_count'):
  agreement[k]={str(n):metric([x for x in joined if x[k]==n]) for n in sorted({x[k] for x in joined})}
 date_by_date={s:{d:metric([x for x in select(joined,s) if x['date']==d]) for d in DATES} for s in SYSTEMS}
 OUT.mkdir(); artifacts={'result_source_manifest.json':source,'result_join_integrity.json':{'status':'PASS','population_races':population['eligible_races'],'population_horses':population['eligible_horses'],'excluded_race_count':1,'joined_horse_count':len(joined),'invalid_result_count':invalid},'eight_system_performance.json':performance,'versus_current.json':versus,'formal_v5_v6_comparison.json':v5v6,'independent_mechanism_outcomes.json':ind_out,'trackcondition_mechanism_outcomes.json':tc_out,'daily_v5_v3_outcomes.json':daily,'unique_hit_horses.json':{'counts':unique,'horses':detail},'pairwise_outcomes.json':pairs,'agreement_outcomes.json':agreement,'date_by_date_performance.json':date_by_date,'december_2025_post_summary.json':{'status':'COMPLETE','evidence_role':'TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT','performance':performance,'result_access_count':1,'production_change':0}}
 for n,x in artifacts.items(): dump(OUT/n,x)
 hashes={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}; dump(OUT/'artifact_hashes.json',{'self_hash_excluded':True,'indexed_artifacts':hashes}); dump(OUT/'SUCCESS',{'status':'SUCCESS','result_access_count':1,'artifact_hashes_frozen':True}); return OUT
if __name__=='__main__': print(run())
