"""POST review: join frozen 2026-08-22 PRE artifacts to validated Result List."""
from __future__ import annotations
import csv,hashlib,json,re
from collections import Counter
from pathlib import Path
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT=Path(__file__).resolve().parents[1]; PRE=ROOT/'reports'/'prospective_prediction_20260822_v1'; OUT=ROOT/'reports'/'prospective_result_20260822_v1'; RAW=ROOT/'data'/'raw'/'target'/'daily_result_list'
VENUES={'sapporo':'札幌','niigata':'新潟','chuukyou':'中京'}; ABNORMAL={'中止','除外','取消','失格'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def rate(n,d):return n/d if d else None
def parts(rid):
 p=rid.split('_');return VENUES[p[-2]],int(re.sub(r'R$','',p[-1]))
def outcome(row,num):
 raw=row[11+num]; valid=raw.isdigit() and int(raw)>0
 if not valid and raw not in ABNORMAL:raise RuntimeError(f'UNKNOWN_RESULT_SEMANTICS:{raw}')
 return {'actual_finish':raw,'valid_result':valid,'actual_top3':bool(valid and int(raw)<=3),'winner':bool(valid and int(raw)==1)}
def metric(rows, allrows):
 valid=[r for r in rows if r['valid_result']]; hits=sum(r['actual_top3'] for r in valid)
 return {'numerator':hits,'denominator':len(valid),'rate':rate(hits,len(valid))}
def main():
 if OUT.exists():raise RuntimeError('OUTPUT_EXISTS')
 manifest=json.loads((PRE/'prediction_manifest.json').read_text(encoding='utf-8'))
 for x in manifest['files']:
  if sha(PRE/x['relative_path'])!=x['sha256']:raise RuntimeError(f'FROZEN_PRE_MANIFEST_MISMATCH:{x["relative_path"]}')
 primary=RAW/'馬番順着順_20260822.csv'; aux=RAW/'着順馬番_20260822.csv'; validation=validate_source_pair(primary,aux,'20260822')
 if validation['status']!='PASS':raise RuntimeError('RESULT_SCHEMA_FAIL')
 with primary.open(encoding='cp932',newline='') as f: rawrows=list(csv.reader(f))
 result={(r[1],int(r[2])):r for r in rawrows}
 if len(result)!=len(rawrows):raise RuntimeError('DUPLICATE_RESULT_RACE')
 index=json.loads((PRE/'race_index.json').read_text(encoding='utf-8'))['race_index']
 if len(index)!=16:raise RuntimeError('FROZEN_RACE_COUNT')
 allrows=[]; races=[]; buys=[]; unconv=[]; skips=[]; missing=[]
 for item in sorted(index,key=lambda x:x['race_id']):
  payload=json.loads((PRE/item['artifact']).read_text(encoding='utf-8')); rid=payload['race_id']; key=parts(rid); rrow=result.get(key)
  if rrow is None:missing.append(rid);continue
  trace=payload.get('buy_gate_trace',{}).get('race',{}); ranked=[]; bynum={}
  for h in payload['ranked_results']:
   num=int(h['horse_number']); o=outcome(rrow,num); mapped={'race_id':rid,'venue':key[0],'race_number':key[1],'horse_number':num,'horse_name':h.get('horse_name'),'rank':h.get('rank'),'frozen_buy':h.get('buy',h.get('decision')=='BUY'),**o}; ranked.append(mapped);bynum[num]=mapped;allrows.append(mapped)
   if mapped['frozen_buy']:buys.append(mapped)
  top5=ranked[:5]; top5top3=sum(x['valid_result'] and x['actual_top3'] for x in top5); winner=any(x['winner'] for x in ranked); top5winner=any(x['winner'] for x in top5)
  races.append({'race_id':rid,'venue':key[0],'race_number':key[1],'field_size':len(ranked),'frozen_buy_count':sum(x['frozen_buy'] for x in ranked),'frozen_buy_top3_count':sum(x['frozen_buy'] and x['valid_result'] and x['actual_top3'] for x in ranked),'at_least_one_successful_buy':any(x['frozen_buy'] and x['valid_result'] and x['actual_top3'] for x in ranked),'top5_actual_top3_count':top5top3,'winner_in_top5':top5winner,'valid_winner_confirmed':winner,'shadow_race_state':trace.get('shadow_race_state'),'shadow_candidate_count':trace.get('shadow_candidate_count')})
  state=trace.get('shadow_race_state')
  if state=='PLAY_UNCONVERGED_4PLUS':
   candidates=[]
   for h in payload['buy_gate_trace']['horses']:
    if h.get('shadow_buy_candidate'):
     x=bynum.get(int(h['horse_number']))
     if x is None:raise RuntimeError(f'UNCONVERGED_CANDIDATE_MAPPING_MISSING:{rid}:{h["horse_number"]}')
     candidates.append(x)
   if len(candidates)!=trace.get('shadow_candidate_count'):raise RuntimeError(f'CANDIDATE_COUNT_MISMATCH:{rid}')
   unconv.append({'race_id':rid,'venue':key[0],'race_number':key[1],'frozen_shadow_candidate_count':len(candidates),'candidates':candidates,'actual_top3_candidate_count':sum(x['valid_result'] and x['actual_top3'] for x in candidates)})
  if state=='SKIP':skips.append({'race_id':rid,'venue':key[0],'race_number':key[1],'top5':top5,'actual_top3_capture_count':top5top3,'winner_capture':top5winner})
 if missing:raise RuntimeError(f'ELIGIBLE_RESULT_MAPPING_MISSING:{missing}')
 if len(allrows)!=216 or len(buys)!=18:raise RuntimeError(f'FROZEN_POPULATION_MISMATCH:{len(allrows)}:{len(buys)}')
 if len({(x['race_id'],x['horse_number']) for x in allrows})!=216:raise RuntimeError('DUPLICATE_HORSE_MAPPING')
 buy_metric=metric(buys,allrows); top5=[x for r in races for x in [z for z in allrows if z['race_id']==r['race_id'] and z['rank']<=5]]; nonbuy=[x for x in top5 if not x['frozen_buy']]
 nonbuy_metric=metric(nonbuy,allrows); top5_metric=metric(top5,allrows); alltop3=sum(x['valid_result'] and x['actual_top3'] for x in allrows); top5hits=sum(x['valid_result'] and x['actual_top3'] for x in top5); winner_races=[r for r in races if r['valid_winner_confirmed']]; winner_hits=sum(r['winner_in_top5'] for r in winner_races)
 abnormal=[x for x in allrows if not x['valid_result']]
 # Original frozen source must remain byte-identical after writing POST outputs elsewhere.
 for x in manifest['files']:
  if sha(PRE/x['relative_path'])!=x['sha256']:raise RuntimeError(f'FROZEN_PRE_MUTATED:{x["relative_path"]}')
 OUT.mkdir(parents=True)
 dump('result_validation.json',{'status':'PASS','date':'20260822','schema_validation':validation,'eligible_frozen_races':16,'mapped_eligible_races':len(races),'missing_eligible_races':0,'mapped_prediction_horses':len(allrows),'duplicate_race_mapping':0,'duplicate_horse_mapping':0,'abnormal_result_exclusions':len(abnormal),'frozen_pre_manifest_unchanged':True})
 dump('horse_result_mapping.json',{'mapping_count':len(allrows),'rows':allrows})
 dump('buy_results.json',{'frozen_buy_count':len(buys),'valid_buy_count':buy_metric['denominator'],'buy_top3_count':buy_metric['numerator'],'buy_top3_rate':buy_metric['rate'],'horses':buys,'by_race':[{'race_id':r['race_id'],'venue':r['venue'],'race_number':r['race_number'],'buy_count':r['frozen_buy_count'],'buy_top3_count':r['frozen_buy_top3_count'],'at_least_one_successful_buy':r['at_least_one_successful_buy']} for r in races if r['frozen_buy_count']]})
 dump('buy_precision.json',{'BUY_TOP3_RATE':buy_metric,'NON_BUY_TOP5_TOP3_RATE':nonbuy_metric,'BUY_SELECTION_LIFT':None if buy_metric['rate'] is None or nonbuy_metric['rate'] is None else buy_metric['rate']-nonbuy_metric['rate'],'boundary':'One-day prospective observation only; no revision to the established 18-date state.'})
 dump('top5_precision.json',{'TOP5_HORSE_TOP3_RATE':top5_metric,'TOP5_CAPTURE_RATE':{'numerator':top5hits,'denominator':alltop3,'rate':rate(top5hits,alltop3)},'WINNER_TOP5_CAPTURE_RATE':{'numerator':winner_hits,'denominator':len(winner_races),'rate':rate(winner_hits,len(winner_races))},'denominator_method':'All frozen ranked horses mapped to validated Result List; no fixed-three-per-race assumption.'})
 dump('unconverged_results.json',{'race_count':len(unconv),'races':unconv,'distribution_actual_top3_candidates':{str(i):sum(r['actual_top3_candidate_count']==i for r in unconv) for i in range(4)}})
 dump('skip_results.json',{'race_count':len(skips),'races':skips})
 summary={'final_status':'PROSPECTIVE_POST_REVIEW_COMPLETE','eligible_race_mapping_count':len(races),'prediction_horse_count':len(allrows),'frozen_buy_count':len(buys),'valid_buy_count':buy_metric['denominator'],'buy_top3_count':buy_metric['numerator'],'BUY_TOP3_RATE':buy_metric['rate'],'NON_BUY_TOP5_TOP3_RATE':nonbuy_metric['rate'],'TOP5_HORSE_TOP3_RATE':top5_metric['rate'],'TOP5_CAPTURE_RATE':rate(top5hits,alltop3),'WINNER_TOP5_CAPTURE_RATE':rate(winner_hits,len(winner_races)),'BUY_SELECTION_LIFT':None if buy_metric['rate'] is None or nonbuy_metric['rate'] is None else buy_metric['rate']-nonbuy_metric['rate'],'unconverged_race_count':len(unconv),'skip_race_count':len(skips),'abnormal_result_exclusions':len(abnormal),'mapping_discrepancies':0,'REG009_KCU_observation':'NOT_SAVED_IN_FROZEN_PRE_SCHEMA; not analyzed or merged into main population.','frozen_pre_manifest_unchanged':True,'prediction_rerun':False,'rule_changes':0,'production_changes':0}
 dump('summary.json',summary)
 fmt=lambda x:'n/a' if x is None else f'{x:.2%}'
 lines=['# 2026-08-22 Prospective POST Review','',f"- Eligible mapped races: {len(races)}/16; horses: {len(allrows)}; frozen BUY: {len(buys)}",f"- BUY Top3: {buy_metric['numerator']}/{buy_metric['denominator']} ({fmt(buy_metric['rate'])})",f"- Non-BUY Top5 Top3: {nonbuy_metric['numerator']}/{nonbuy_metric['denominator']} ({fmt(nonbuy_metric['rate'])})",f"- Top5 horse Top3: {top5_metric['numerator']}/{top5_metric['denominator']} ({fmt(top5_metric['rate'])})",f"- Top5 capture: {top5hits}/{alltop3} ({fmt(rate(top5hits,alltop3))})",f"- Winner Top5 capture: {winner_hits}/{len(winner_races)} ({fmt(rate(winner_hits,len(winner_races)))})",f"- BUY selection lift: {fmt(summary['BUY_SELECTION_LIFT'])}",f"- Abnormal-result exclusions: {len(abnormal)}",'', '## BUY outcomes','', '| Venue | Race | Horse | Finish | Valid | Top3 |','|---|---:|---|---:|---|---|']
 for x in buys:lines.append(f"| {x['venue']} | {x['race_number']}R | {x['horse_number']} {x['horse_name']} | {x['actual_finish']} | {x['valid_result']} | {x['actual_top3']} |")
 lines += ['', '## UNCONVERGED observation', '']
 for x in unconv:lines.append(f"- {x['venue']} {x['race_number']}R: candidates={x['frozen_shadow_candidate_count']}, actual Top3 candidates={x['actual_top3_candidate_count']}")
 lines += ['', '## SKIP observation', '']
 for x in skips:lines.append(f"- {x['venue']} {x['race_number']}R: Top5 actual Top3={x['actual_top3_capture_count']}, winner captured={x['winner_capture']}")
 lines += ['', 'Frozen PRE manifest remained unchanged. No Prediction rerun, rule/counterfactual, Candidate, or Production change was performed.']
 (OUT/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
if __name__=='__main__':main()
