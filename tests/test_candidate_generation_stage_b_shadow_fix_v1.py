"""Fix-round B3 tests: synthetic inputs; real Engines for the integration case."""
from copy import deepcopy
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from engine.buy_v1_rc1_engine import BUYV1RC1Engine
from review.candidate_generation_stage_b_shadow_v1 import CandidateGenerationStageBShadow, EXACT5_TIE_BREAK_ID

def horses():
 return [{'horse_number':i,'horse_name':f'Horse{i}','rank':i,'shadow_ai_rank':i,'adjusted_score':100-i,'final_score':100-i,'decision_score':.8,'total_score':130,'past_performance_score':60,'distance_score':35,'course_shape_score':8,'lap_score':1,'shape_score':1,'pace_style_score':15,'warnings':[],'final_risks':[],'conflict_factors':[],'consistency_score':.8,'consistency_level':'high'} for i in range(1,7)]
def ctx(baseline=None): return {'race_id':'race_20990101_tokyo_1R','date':'20990101','venue':'tokyo','race_number':1,'race_structure':{},'structure_flags':{},'baseline_race_decision_result':baseline}
def packet(stage, rows, selected=(1,2,3,4,5), gid='GEN_A', context=None):
 s=stage.race_context_snapshot(rows,context or ctx())
 return {'race_id':s['race_id'],'race_context_snapshot_hash':s['snapshot_hash'],'generator_id':gid,'generator_version_hash':'version','generator_recipe_freeze_hash':'freeze','tie_break_id':EXACT5_TIE_BREAK_ID,'exact5':[{'horse_number':n,'horse_name':f'Horse{n}','candidate_rank':i,'candidate_probability':.9-i/10,'shadow_ai_rank':n} for i,n in enumerate(selected,1)]}

class CorruptRC1:
 def __init__(self, mode): self.mode=mode;self.mutated=False
 def evaluate(self,race,horses):
  shadow=[{'horse_number':h['horse_number'],'horse_name':h['horse_name']} for h in horses]; records=[{'horse_name':h['horse_name'],'rc1_decision':'CAUTION','rc1_buy':False} for h in horses]
  if self.mode=='shadow_name': shadow[0]['horse_name']='bad'
  if self.mode=='rc1_name': records[0]['horse_name']='bad'
  if self.mode=='count': records.pop()
  return {'enabled':True,'shadow_result':{'horse_records':shadow},'horse_records':records,'race_state':'PLAY_CONVERGED'}
 def apply_to_horses(self,horses,result):
  self.mutated=True
  for h in horses: h['decision']='CAUTION'
  if self.mode=='final': horses[0]['horse_name']='bad'
  return horses
class Race:
 def __init__(self):self.count=0
 def decide(self,c,h):self.count=len(h);return {'race_decision':'PASS','race_confidence':.5}
class Decision:
 def __init__(self):self.contexts=[]
 def decide(self,h,c):self.contexts.append(c);return {'decision':'BUY' if c['rank']<=5 else 'CAUTION','decision_score':.8,'adjusted_score':h.get('adjusted_score'),'final_score':h.get('final_score')}
 def decide_many(self,*x):raise AssertionError
class Sync:
 def synchronize(self,r,h,rc):return {'race_decision_original':r['race_decision'],'race_decision_final':r['race_decision']}

def test_real_engine_integration():
 rows=horses(); stage=CandidateGenerationStageBShadow(); out=stage.run(packet(stage,rows),rows,ctx())
 assert out['status']=='COMMITTED' and len(out['horses'])==6 and out['trace']['race']['full_field_count']==6
 assert all(x['decision']!='BUY' for x in out['horses'] if x['horse_number']==6)
def test_score_fallback_exact_order():
 rows=horses();rows[0].pop('adjusted_score');rows[0]['integrated_score']=777;rows[1].pop('adjusted_score');rows[1]['weighted_score']=666;rows[2].pop('adjusted_score');rows[2]['final_score']=555
 snap=CandidateGenerationStageBShadow().race_context_snapshot(rows,ctx());assert snap['top_score']==777 and snap['bottom_score']==94
def test_rc1_off_non_candidate_fails_closed():
 rows=horses();stage=CandidateGenerationStageBShadow(rc1_engine=BUYV1RC1Engine(enabled=False));out=stage.run(packet(stage,rows),rows,ctx());assert out['status']=='STOP' and out['valid_stage_b_buy_artifact'] is False
def test_track_bias_present_absent_and_generator_independence():
 rows=horses();stage=CandidateGenerationStageBShadow(Decision(),Race(),CorruptRC1('none'),Sync());present={'baseline_decision':'BUY','baseline_rank':1};a=ctx(present);b=ctx()
 assert stage.race_context_snapshot(rows,a)['baseline_race_decision_result']==present and stage.race_context_snapshot(rows,b)['baseline_race_decision_result'] is None
 assert packet(stage,rows,(1,2,3,4,5),'A',b)['race_context_snapshot_hash']==packet(stage,rows,(2,3,4,5,6),'B',b)['race_context_snapshot_hash']
def test_all_pre_identity_stops():
 cases=[]
 x=horses();x[0].pop('horse_number');cases.append(('STOP_MISSING_NUMBER',x))
 x=horses();x[1]['horse_number']=1;cases.append(('STOP_DUPLICATE_NUMBER',x))
 x=horses();x[0]['horse_name']='';cases.append(('STOP_MISSING_NAME',x))
 x=horses();x[1]['horse_name']='Horse1';cases.append(('STOP_DUPLICATE_NAME',x))
 for expected,rows in cases:
  source=deepcopy(rows);out=CandidateGenerationStageBShadow().run({},rows,ctx());assert out['failure_state']==expected and rows==source
def test_mid_and_post_identity_stops_and_transaction():
 for mode,expected in [('shadow_name','STOP_NUMBER_NAME_MISMATCH'),('rc1_name','STOP_RC1_NAME_NOT_FOUND'),('count','STOP_COUNT_MISMATCH'),('final','STOP_FINAL_IDENTITY_MISMATCH')]:
  rows=horses(); source=deepcopy(rows);rc=CorruptRC1(mode);out=CandidateGenerationStageBShadow(Decision(),Race(),rc,Sync()).run(packet(CandidateGenerationStageBShadow(Decision(),Race(),rc,Sync()),rows),rows,ctx())
  assert out['status']=='STOP' and out['failure_state']==expected and out['valid_stage_b_buy_artifact'] is False and rows==source
  if mode=='final': assert rc.mutated
def test_trace_and_dual_rank_injection():
 rows=horses();d=Decision();r=Race();stage=CandidateGenerationStageBShadow(d,r,CorruptRC1('none'),Sync());out=stage.run(packet(stage,rows),rows,ctx());assert out['status']=='COMMITTED' and r.count==6
 required={'race_id','horse_number','horse_name','is_candidate_member','current_rank','candidate_rank','decision_rank','shadow_ai_rank','generator_id','generator_version_hash','generator_recipe_freeze_hash','candidate_probability','stage_b_pre_rc1_decision','rc1_decision','final_stage_b_decision','identity_bridge_status','failure_state'}
 assert required <= set(out['trace']['horses'][0]) and [c['rank'] for c in d.contexts]==[1,2,3,4,5,999]
if __name__=='__main__':
 tests=[v for k,v in sorted(globals().items()) if k.startswith('test_')]
 for test in tests:test()
 print(f'stage_b_fix_tests_passed={len(tests)}')
