"""Read-only PATH_R split using saved race-level shadow runtime state."""
from __future__ import annotations
import csv,json
from collections import Counter,defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'reports'/'path_r_mechanism_split_v1'; TOP5=ROOT/'reports'/'failed_buy_root_cause_v1'/'top5_result_export.csv'
BLOCKS={'JUNE_BLOCK_1':('20260620','20260621','20260627','20260628'),'JULY_H1':('20260704','20260705','20260711','20260712'),'JULY_H2':('20260718','20260719','20260725','20260726'),'AUGUST_DEVELOPMENT':('20260801','20260802','20260808','20260809','20260815','20260816')}
ROOTS={**{d:ROOT/'reports'/'h5_temporal_june_block1_v1'/f'prediction_{d}' for d in BLOCKS['JUNE_BLOCK_1']},**{d:ROOT/'reports'/'cand_h5_001_july_4day_validation_v1'/f'prediction_{d}' for d in BLOCKS['JULY_H1']},**{d:ROOT/'reports'/'h5_temporal_july_h2_v1'/f'prediction_{d}' for d in BLOCKS['JULY_H2']},**{d:ROOT/'reports'/'buy_improvement_trace_6day_v1'/f'prediction_{d}' for d in BLOCKS['AUGUST_DEVELOPMENT']}}
EXPECTED={'PLAY_CONVERGED','PLAY_UNCONVERGED_4PLUS','SKIP'}
def dump(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def rate(n,d):return n/d if d else None
def band(n):return 'TOO_SMALL' if n<=9 else 'OBSERVATION_ONLY' if n<=19 else 'DIRECTIONAL_WATCH' if n<=29 else 'MEANINGFUL_VALIDATION' if n<=49 else 'STRONG_RETROSPECTIVE_EVIDENCE' if n<=99 else 'HIGH_CONFIDENCE_OPERATIONAL'
def boolv(v,f,k):
 if not isinstance(v,bool):raise RuntimeError(f'INVALID_BOOL:{f}:{k}')
 return v
def mechanism(rows):
 states=defaultdict(list)
 for r in rows:states[r['shadow_race_state']].append(r)
 total=len(rows); totalr=len({r['race_id'] for r in rows}); out={}
 for state,rs in states.items():
  races=len({r['race_id'] for r in rs}); hits=sum(r['actual_top3'] for r in rs)
  out[state]={'horse_count':len(rs),'share_of_path_r_horses':rate(len(rs),total),'independent_race_count':races,'share_of_path_r_races':rate(races,totalr),'valid_result_horse_count':sum(r['valid_result'] for r in rs),'actual_top3_count':hits,'top3_rate':rate(hits,sum(r['valid_result'] for r in rs)),'outcome_evidence_band':band(races),'mechanism_occurrence_label':'MECHANISM_OCCURRENCE_NEGLIGIBLE' if len(rs)<=1 else 'OBSERVED_RUNTIME_MECHANISM'}
 return out
def candidates(rows):
 races={r['race_id']:(r['shadow_candidate_count'],r['shadow_race_state']) for r in rows}; values=[x[0] for x in races.values() if x[1]=='PLAY_UNCONVERGED_4PLUS']; c=Counter(values)
 return {'unconverged_race_count':len(values),'minimum':min(values) if values else None,'maximum':max(values) if values else None,'median':sorted(values)[len(values)//2] if values else None,'counts_by_candidate_count':{str(k):c[k] for k in sorted(c)}}
def main():
 if OUT.exists():raise RuntimeError('OUTPUT_EXISTS')
 OUT.mkdir(parents=True)
 with TOP5.open(encoding='utf-8',newline='') as f: primary=list(csv.DictReader(f))
 if len(primary)!=1535:raise RuntimeError('TOP5_ROW_COUNT')
 idx={(r['race_id'],int(r['horse_number'])):r for r in primary}
 if len(idx)!=1535:raise RuntimeError('TOP5_DUPLICATE')
 trace={}; races={}; bydate=Counter(); unexpected=[]; race_checks=[]
 for block,dates in BLOCKS.items():
  for date in dates:
   arts=sorted(ROOTS[date].glob('race_*_prediction.json'))
   if not arts:raise RuntimeError(f'ARTIFACT_MISSING:{date}')
   for p in arts:
    x=json.loads(p.read_text(encoding='utf-8')); rid=x['race_id']; t=x.get('buy_gate_trace',{}); rh=t.get('race'); hs=t.get('horses')
    if not isinstance(rh,dict) or not isinstance(hs,list):raise RuntimeError(f'TRACE_STRUCTURE:{rid}')
    state=rh.get('shadow_race_state'); count=rh.get('shadow_candidate_count')
    if state not in EXPECTED:unexpected.append({'race_id':rid,'state':state})
    if not isinstance(count,int) or count<0:raise RuntimeError(f'CANDIDATE_COUNT_INVALID:{rid}')
    calc_candidate=sum(boolv(h.get('shadow_buy_candidate'),'shadow_buy_candidate',rid) for h in hs); calc_buy=sum(boolv(h.get('shadow_buy'),'shadow_buy',rid) for h in hs)
    if calc_candidate!=count:raise RuntimeError(f'CANDIDATE_COUNT_MISMATCH:{rid}:{count}:{calc_candidate}')
    races[rid]={'block':block,'date':date,'shadow_race_state':state,'shadow_candidate_count':count,'shadow_buy_count':calc_buy}; bydate[date]+=1
    race_checks.append({'race_id':rid,'date':date,'block':block,'state':state,'saved_candidate_count':count,'computed_candidate_count':calc_candidate,'computed_shadow_buy_count':calc_buy,'candidate_count_matches_saved':True})
    for h in hs:
     key=(rid,h.get('horse_number'))
     if key in trace:raise RuntimeError(f'DUP_TRACE:{key}')
     trace[key]=h
 if len(races)!=307 or len(trace)!=3925:raise RuntimeError(f'COVERAGE:{len(races)}:{len(trace)}')
 if unexpected:raise RuntimeError(f'UNEXPECTED_STATE:{unexpected}')
 records=[]
 for key,row in idx.items():
  h=trace.get(key); race=races.get(key[0])
  if h is None or race is None:raise RuntimeError(f'MISSING_TRACE:{key}')
  isbuy=row['is_buy']=='True'; valid=row['valid_result']=='True'; top3=row['actual_top3']=='True'; candidate=boolv(h.get('shadow_buy_candidate'),'shadow_buy_candidate',key); shadow=boolv(h.get('shadow_buy'),'shadow_buy',key)
  if isbuy!=shadow:raise RuntimeError(f'BUY_ALIGNMENT:{key}')
  if not isbuy and valid and candidate and not shadow:records.append({'block':row['block'],'date':row['date'],'race_id':key[0],'horse_number':key[1],'valid_result':valid,'actual_top3':top3,**race})
 if len(records)!=306:raise RuntimeError(f'PATH_R_TOTAL:{len(records)}')
 byblock={}
 for b in BLOCKS:
  rows=[r for r in records if r['block']==b]; byblock[b]={'path_r_horse_count':len(rows),'path_r_independent_race_count':len({r['race_id'] for r in rows}),'mechanisms':mechanism(rows),'candidate_count_distribution':candidates(rows)}
 pooled={'path_r_horse_count':len(records),'path_r_independent_race_count':len({r['race_id'] for r in records}),'mechanisms':mechanism(records),'candidate_count_distribution':candidates(records)}
 unconv=pooled['mechanisms'].get('PLAY_UNCONVERGED_4PLUS',{}).get('horse_count',0); skip=pooled['mechanisms'].get('SKIP',{}).get('horse_count',0)
 supported=[]
 if unconv and skip<=1:supported.append('RESULT_A_UNCONVERGED_4PLUS_DOMINANT')
 elif skip and unconv<=1:supported.append('RESULT_B_RACE_SKIP_DOMINANT')
 else:supported.append('RESULT_C_MIXED_DOWNSTREAM_MECHANISMS')
 # A single isolated SKIP is explicitly not treated as outcome-comparison evidence or a temporal pattern.
 conclusion='PATH_R_UNCONVERGED_4PLUS_DOMINANT' if 'RESULT_A_UNCONVERGED_4PLUS_DOMINANT' in supported else 'PATH_R_RACE_SKIP_DOMINANT' if 'RESULT_B_RACE_SKIP_DOMINANT' in supported else 'PATH_R_MIXED_MECHANISMS'
 dump('source_validation.json',{'status':'PASS','source_dates':18,'source_races':len(races),'source_prediction_horses':len(trace),'top5_rows':len(idx),'path_r_total':len(records),'no_prediction_rerun':True,'no_engine_change':True})
 dump('race_state_validation.json',{'status':'PASS','expected_states':sorted(EXPECTED),'unexpected_state_count':0,'race_state_coverage':len(races),'shadow_candidate_count_complete':True,'candidate_count_matches_trace_horse_candidates':True,'race_candidate_buy_checks':race_checks})
 dump('path_r_mechanism_counts.json',{'by_block':{b:{'path_r_horse_count':v['path_r_horse_count'],'path_r_independent_race_count':v['path_r_independent_race_count'],'mechanisms':v['mechanisms']} for b,v in byblock.items()},'pooled':{'path_r_horse_count':pooled['path_r_horse_count'],'path_r_independent_race_count':pooled['path_r_independent_race_count'],'mechanisms':pooled['mechanisms']}})
 dump('mechanism_by_block.json',{b:v['mechanisms'] for b,v in byblock.items()}); dump('mechanism_outcomes.json',{'by_block':{b:v['mechanisms'] for b,v in byblock.items()},'pooled':pooled['mechanisms'],'outcome_boundary':'Outcome rates are descriptive; evidence bands apply only to outcome interpretation.'})
 dump('candidate_count_distribution.json',{'by_block':{b:v['candidate_count_distribution'] for b,v in byblock.items()},'pooled':pooled['candidate_count_distribution'],'boundary':'Saved runtime candidate counts only; no cap or parameter optimization.'})
 dump('evidence_by_block.json',{'independent_evidence_unit':'RACE','by_block':{b:{s:{'independent_race_count':x['independent_race_count'],'outcome_evidence_band':x['outcome_evidence_band']} for s,x in v['mechanisms'].items()} for b,v in byblock.items()},'pooled':{s:{'independent_race_count':x['independent_race_count'],'outcome_evidence_band':x['outcome_evidence_band']} for s,x in pooled['mechanisms'].items()}})
 dump('temporal_interpretation.json',{'buy_selection_lift_context':{'JUNE_BLOCK_1':-0.1008,'JULY_H1':0.0427,'JULY_H2':0.092,'AUGUST_DEVELOPMENT':-0.0005},'mechanism_occurrence_by_block':{b:{s:x['horse_count'] for s,x in v['mechanisms'].items()} for b,v in byblock.items()},'interpretation':'PLAY_UNCONVERGED_4PLUS occurs in every block and accounts for all but an isolated saved SKIP PATH_R horse. This is runtime mechanism attribution, not intervention validity.'})
 dump('analysis_gate.json',{'final_conclusion':conclusion,'supported_outcomes':supported,'candidate_count_convergence_next_structural_target':conclusion=='PATH_R_UNCONVERGED_4PLUS_DOMINANT','more_historical_required_for_mechanism_attribution':False,'candidate_created':False,'prediction_rerun':False,'production_changes':0})
 dump('summary.json',{'final_conclusion':conclusion,'supported_outcomes':supported,'path_r_total':len(records),'unconverged_path_r_horses':unconv,'skip_path_r_horses':skip,'unexpected_state_count':0,'pooled':pooled,'no_candidate_created':True,'no_prediction_buy_decision_production_change':True})
 fmt=lambda x:'n/a' if x is None else f'{x:.2%}'
 lines=['# PATH_R Mechanism Split v1','',f'Final conclusion: `{conclusion}`.','',f'PATH_R contains {len(records)} valid non-BUY Top5 horses across {pooled["path_r_independent_race_count"]} races.','', '| Mechanism | Horses | PATH_R share | Races | Outcome Top3 | Outcome evidence |','|---|---:|---:|---:|---:|---:|']
 for s,x in pooled['mechanisms'].items():lines.append(f'| {s} | {x["horse_count"]} | {fmt(x["share_of_path_r_horses"])} | {x["independent_race_count"]} | {x["actual_top3_count"]}/{x["valid_result_horse_count"]} ({fmt(x["top3_rate"])}) | {x["outcome_evidence_band"]} |')
 lines += ['','`PLAY_UNCONVERGED_4PLUS` is a saved runtime mechanism fact. This does not validate changing a candidate cap, convergence rule, BUY count, or any Production behavior.','', 'No Candidate was created; no Prediction rerun, Tier 2 trace, BUY/Decision, or Production change occurred.']
 (OUT/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
if __name__=='__main__':main()
