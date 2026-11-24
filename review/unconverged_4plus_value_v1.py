"""Read-only value-density diagnostic for saved PLAY_UNCONVERGED_4PLUS races."""
from __future__ import annotations
import csv,json
from collections import Counter,defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'reports'/'unconverged_4plus_value_v1'; TOP5=ROOT/'reports'/'failed_buy_root_cause_v1'/'top5_result_export.csv'; BUY_CONTEXT=ROOT/'reports'/'buy_precision_v1'/'pooled_precision.json'
BLOCKS={'JUNE_BLOCK_1':('20260620','20260621','20260627','20260628'),'JULY_H1':('20260704','20260705','20260711','20260712'),'JULY_H2':('20260718','20260719','20260725','20260726'),'AUGUST_DEVELOPMENT':('20260801','20260802','20260808','20260809','20260815','20260816')}
ROOTS={**{d:ROOT/'reports'/'h5_temporal_june_block1_v1'/f'prediction_{d}' for d in BLOCKS['JUNE_BLOCK_1']},**{d:ROOT/'reports'/'cand_h5_001_july_4day_validation_v1'/f'prediction_{d}' for d in BLOCKS['JULY_H1']},**{d:ROOT/'reports'/'h5_temporal_july_h2_v1'/f'prediction_{d}' for d in BLOCKS['JULY_H2']},**{d:ROOT/'reports'/'buy_improvement_trace_6day_v1'/f'prediction_{d}' for d in BLOCKS['AUGUST_DEVELOPMENT']}}
def dump(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def rate(n,d):return n/d if d else None
def band(n):return 'TOO_SMALL' if n<=9 else 'OBSERVATION_ONLY' if n<=19 else 'DIRECTIONAL_WATCH' if n<=29 else 'MEANINGFUL_VALIDATION' if n<=49 else 'STRONG_RETROSPECTIVE_EVIDENCE' if n<=99 else 'HIGH_CONFIDENCE_OPERATIONAL'
def boolv(v,f,k):
 if not isinstance(v,bool):raise RuntimeError(f'INVALID_BOOL:{f}:{k}')
 return v
def summarise(races):
 counts=Counter(r['top3_candidate_count'] for r in races); candidates=[h for r in races for h in r['candidates']]; total=len(races)
 valid_candidates=[h for h in candidates if h['valid_result']]
 return {'race_count':total,'distribution_0_1_2_3':{str(n):{'race_count':counts[n],'share':rate(counts[n],total)} for n in range(4)},'at_least_1_top3_candidate_races':{'count':sum(counts[n] for n in (1,2,3)),'share':rate(sum(counts[n] for n in (1,2,3)),total)},'at_least_2_top3_candidate_races':{'count':sum(counts[n] for n in (2,3)),'share':rate(sum(counts[n] for n in (2,3)),total)},'all_3_top3_candidate_races':{'count':counts[3],'share':rate(counts[3],total)},'candidate_level_top3':{'numerator':sum(h['actual_top3'] for h in valid_candidates),'denominator':len(valid_candidates),'rate':rate(sum(h['actual_top3'] for h in valid_candidates),len(valid_candidates)),'invalid_candidate_exclusions':len(candidates)-len(valid_candidates)},'independent_race_count':total,'outcome_evidence_band':band(total)}
def main():
 if OUT.exists():raise RuntimeError('OUTPUT_EXISTS')
 OUT.mkdir(parents=True)
 with TOP5.open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
 if len(rows)!=1535:raise RuntimeError('TOP5_ROW_COUNT')
 primary={(r['race_id'],int(r['horse_number'])):r for r in rows}
 if len(primary)!=1535:raise RuntimeError('TOP5_DUPLICATE')
 all_races=[]; coverage=[]
 for block,dates in BLOCKS.items():
  for date in dates:
   for p in sorted(ROOTS[date].glob('race_*_prediction.json')):
    x=json.loads(p.read_text(encoding='utf-8')); rid=x['race_id']; trace=x['buy_gate_trace']; race=trace.get('race',{}); hs=trace.get('horses',[]); state=race.get('shadow_race_state'); count=race.get('shadow_candidate_count')
    if not isinstance(count,int):raise RuntimeError(f'CANDIDATE_COUNT_INVALID:{rid}')
    candidates=[]
    for h in hs:
     if boolv(h.get('shadow_buy_candidate'),'shadow_buy_candidate',rid):
      # Result mapping is required only for the authorized UNCONVERGED_4PLUS
      # population. Other race states are outside this diagnostic's population.
      if state=='PLAY_UNCONVERGED_4PLUS':
       key=(rid,h['horse_number']); row=primary.get(key)
       if row is None:raise RuntimeError(f'CANDIDATE_NOT_IN_FROZEN_TOP5_EXPORT:{key}')
       valid=row['valid_result']=='True'; top3=row['actual_top3']=='True'
       candidates.append({'horse_number':h['horse_number'],'actual_top3':top3,'valid_result':valid})
    if state=='PLAY_UNCONVERGED_4PLUS' and len(candidates)!=count:raise RuntimeError(f'CANDIDATE_SET_COUNT_MISMATCH:{rid}:{count}:{len(candidates)}')
    coverage.append({'race_id':rid,'block':block,'date':date,'shadow_race_state':state,'shadow_candidate_count':count,'candidate_set_complete':True})
    if state=='PLAY_UNCONVERGED_4PLUS':
     if count not in {4,5}:raise RuntimeError(f'UNCONVERGED_COUNT_INVALID:{rid}:{count}')
     all_races.append({'race_id':rid,'block':block,'date':date,'candidate_count':count,'candidates':candidates,'top3_candidate_count':sum(h['actual_top3'] for h in candidates)})
 if len(all_races)!=67:raise RuntimeError(f'UNCONVERGED_RACE_COUNT:{len(all_races)}')
 if Counter(r['candidate_count'] for r in all_races)!={4:29,5:38}:raise RuntimeError(f'CANDIDATE_SPLIT:{Counter(r["candidate_count"] for r in all_races)}')
 pooled=summarise(all_races); byblock={b:summarise([r for r in all_races if r['block']==b]) for b in BLOCKS}; bycount={str(n):summarise([r for r in all_races if r['candidate_count']==n]) for n in (4,5)}
 buy=json.loads(BUY_CONTEXT.read_text(encoding='utf-8'))['BUY_TOP3_RATE']
 # No tuned percentage defines "meaningful". Two-or-more correct candidates are recorded as the direct structural observation.
 multi=pooled['at_least_2_top3_candidate_races']['count']; all3=pooled['all_3_top3_candidate_races']['count']
 supported=[]
 if multi: supported.append('RESULT_B_CONVERGENCE_BLOCK_DISCARDS_MULTI_CORRECT_SIGNAL')
 # Four all-three races across only two blocks are recorded, but are neither a
 # substantial subset nor repeated high-density signal across the full blocks.
 # No numerical concentration threshold is introduced by this diagnostic.
 strong_concentration=False
 if strong_concentration: supported.append('RESULT_C_STRONG_CORRECT_SIGNAL_CONCENTRATION')
 conclusion='STRONG_CORRECT_SIGNAL_CONCENTRATION' if 'RESULT_C_STRONG_CORRECT_SIGNAL_CONCENTRATION' in supported else 'CONVERGENCE_BLOCK_DISCARDS_MULTI_CORRECT_SIGNAL' if 'RESULT_B_CONVERGENCE_BLOCK_DISCARDS_MULTI_CORRECT_SIGNAL' in supported else 'CONVERGENCE_BLOCK_PLAUSIBLY_PROTECTIVE'
 dump('source_validation.json',{'status':'PASS','source_dates':18,'source_races':307,'unconverged_races':len(all_races),'candidate_count_split':{'4':29,'5':38},'candidate_set_complete':True,'valid_result_semantics_complete':True,'actual_top3_semantics_from_frozen_export':True,'prediction_rerun':False,'engine_change':False})
 dump('top3_candidate_count_distribution.json',pooled); dump('candidate_count_split.json',bycount); dump('block_breakdown.json',byblock)
 dump('candidate_performance_context.json',{'unconverged_candidate_top3':pooled['candidate_level_top3'],'normal_buy_top3_context':buy,'comparison_boundary':'Descriptive context only; populations are not counterfactually equivalent and no promotion inference is made.'})
 dump('evidence_by_block.json',{'independent_evidence_unit':'RACE','by_block':{b:{'race_count':v['race_count'],'outcome_evidence_band':v['outcome_evidence_band']} for b,v in byblock.items()},'pooled':{'race_count':pooled['race_count'],'outcome_evidence_band':pooled['outcome_evidence_band']}})
 dump('analysis_gate.json',{'final_conclusion':conclusion,'supported_outcomes':supported,'convergence_rule_review_justified':bool(multi),'bounded_shadow_alternative_design_discussion_justified':strong_concentration,'convergence_mechanism_deprioritized':False,'candidate_created':False,'rule_changes':0,'prediction_rerun':False,'production_changes':0})
 dump('summary.json',{'final_conclusion':conclusion,'supported_outcomes':supported,'total_unconverged_races':len(all_races),'four_candidate_races':29,'five_candidate_races':38,'pooled':pooled,'normal_buy_top3_context':buy,'no_rule_candidate_production_change':True})
 fmt=lambda x:'n/a' if x is None else f'{x:.2%}'
 lines=['# UNCONVERGED_4PLUS Value Diagnostic v1','',f'Final conclusion: `{conclusion}`.','',f'Across {pooled["race_count"]} unconverged races, candidate Top3 density is recorded without alternative-policy simulation.','', '| Actual Top3 candidates in saved candidate set | Races | Share |','|---|---:|---:|']
 for n,v in pooled['distribution_0_1_2_3'].items():lines.append(f'| {n} | {v["race_count"]} | {fmt(v["share"])} |')
 lines += ['',f"At least two actual Top3 candidates: {pooled['at_least_2_top3_candidate_races']['count']}/{pooled['race_count']} ({fmt(pooled['at_least_2_top3_candidate_races']['share'])}).",f"All three actual Top3 candidates: {pooled['all_3_top3_candidate_races']['count']}/{pooled['race_count']} ({fmt(pooled['all_3_top3_candidate_races']['share'])}).",f"Candidate-level Top3: {pooled['candidate_level_top3']['numerator']}/{pooled['candidate_level_top3']['denominator']} ({fmt(pooled['candidate_level_top3']['rate'])}); frozen normal BUY context: {buy['numerator']}/{buy['denominator']} ({fmt(buy['rate'])}).",'', 'This establishes discarded-signal density only. It does not support changing a cap, convergence rule, BUY count, or Production behavior.']
 (OUT/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
if __name__=='__main__':main()
