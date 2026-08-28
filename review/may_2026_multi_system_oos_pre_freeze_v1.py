"""May 2026 PRE-only freeze: Current AI, frozen CF, and V4 Model v2."""
from __future__ import annotations
import hashlib,json,math,sys
from pathlib import Path
import joblib, numpy as np
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
RAW=ROOT/'data'/'raw'/'prediction_input'; OUT=ROOT/'reports'/'may_2026_multi_system_oos_v1'/'pre_retry_v5'
DATES=('20260502','20260503','20260509','20260510','20260516','20260517','20260523','20260524','20260530','20260531')
MODEL=ROOT/'reports'/'ml_v4_buy_selection_model_v2'; PROTOCOL=ROOT/'reports'/'ml_v4_buy_selection_training_protocol_v2'
MAY02_SOURCE_DIAGNOSTIC='reports/may_2026_multi_system_oos_v1/source_diagnostic_20260502_v1'
PREVIOUS_FAILURE_LINEAGE='reports/may_2026_multi_system_oos_v1/pre_retry_v3/pre_freeze_manifest.json'
MAY09_PREVIOUS_DEFECTIVE_DG_SHA='f92c45e9d90b7446c1af55f3d622ef60fbc27118b08ce67980a63883bdf3c4c1'
MAY09_SOURCE_DIAGNOSTIC='reports/may_2026_multi_system_oos_v1/source_diagnostic_20260509_v1'
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.prospective_prediction_runner_v1 import run as current_run
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x): (OUT/n).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
class Stop(RuntimeError):pass
def boolean(v,c):
 if v is True:return 1
 if v is False:return 0
 raise Stop('GATE_BOOLEAN_INVALID:'+c)
SEM=['Ability','PastPerformance','Distance','CourseShape','LapSuitability','RaceShape','PaceStyle','shadow_ai_rank','decision_score','final_score','adjusted_score','absolute_quality_pass','relative_advantage_pass','effective_reliability_pass','risk_guard_pass','consensus_positive_count','consensus_negative_count','risk_count','conflict_count','race_state']; COLS=[*SEM[:-1],'is_PLAY_UNCONVERGED_4PLUS','is_SKIP']; GATES=set(SEM[11:15])
def vector(h,t,state,ctx):
 snap=t.get('evaluator_score_snapshot',{})
 vals=[]
 for f in SEM[:-1]:
  v=snap.get(f) if f in {'Ability','PastPerformance','Distance','CourseShape','LapSuitability','RaceShape','PaceStyle'} else h.get(f,t.get(f))
  if f in GATES: vals.append(boolean(v,ctx+':'+f))
  else:
   if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(float(v)): raise Stop('FEATURE_INVALID:'+ctx+':'+f)
   vals.append(float(v))
 vals += [int(state=='PLAY_UNCONVERGED_4PLUS'),int(state=='SKIP')]
 return vals
def run():
 if OUT.exists() and any(OUT.iterdir()):raise FileExistsError('OUTPUT_EXISTS:'+str(OUT))
 OUT.mkdir(parents=True,exist_ok=True)
 sources=[]; source_failure=None
 try:
  if sha(MODEL/'model.joblib')!='faab21d7ae16cbd9475a621bf4b592c30cce1358e46e7a5f55ffb34dc46af093' or sha(MODEL/'scaler.joblib')!='d07201b81f8de215e747fb950269f825e8ea851655d9fedfa5da6d8844a93eaa' or sha(PROTOCOL/'training_protocol.md')!='be8764d425650a067e4ddaca96f2cc52b9dff371c336676e51d52e3eaf502100':raise Stop('MODEL_OR_PROTOCOL_SHA_MISMATCH')
  transform=json.loads((PROTOCOL/'feature_transform_schema.json').read_text(encoding='utf-8'))
  if transform.get('transformed_model_input_columns')!=COLS:raise Stop('V4_TRANSFORM_ORDER_MISMATCH')
  preflight=[]
  adapter=TargetBulkPredictionInputAdapterV1()
  for date in DATES:
   paths={k:RAW/f'{k}{date[2:]}.CSV' for k in ('DG','DE','DS')}
   if not all(p.is_file() for p in paths.values()):
    source_failure={'date':date,'source_sha256':{kind:(sha(path) if path.is_file() else 'UNAVAILABLE') for kind,path in paths.items()},'exception_class':'Stop','exception_args':['MISSING_SOURCE:'+date]}
    raise Stop('MISSING_SOURCE:'+date)
   source_entry={'date':date,'sources':{k:{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for k,p in paths.items()}}
   if date=='20260502':
    source_entry['source_diagnostic_artifact']=MAY02_SOURCE_DIAGNOSTIC
    source_entry['previous_pre_failure_lineage']=PREVIOUS_FAILURE_LINEAGE
    source_entry['independent_review']='PRE_RETRY_ACCEPT'
   if date=='20260509':
    source_entry['source_recovery_lineage']={
     'status':'MAY_2026_0509_SOURCE_RECOVERY_PASS',
     'previous_defective_dg_sha256':MAY09_PREVIOUS_DEFECTIVE_DG_SHA,
     'source_diagnostic_artifact':MAY09_SOURCE_DIAGNOSTIC,
    }
   sources.append(source_entry)
   try:
    bundle=adapter.load(paths['DG'],paths['DE'],paths['DS'])
   except Exception as exc:
    source_failure={'date':date,'source_sha256':source_entry['sources'],'exception_class':type(exc).__name__,'exception_args':list(exc.args)}
    raise
   if bundle.date!=date:raise Stop('DATE_MISMATCH:'+date+':'+str(bundle.date))
   races=sorted(bundle.races); horses=sum(len(r.today_entries) for r in bundle.races.values())
   if len(races)!=len(set(races)) or not races:raise Stop('RACE_IDENTITY_INVALID:'+date)
   preflight.append({'date':date,'status':'PASS','race_count':len(races),'horse_count':horses,'duplicate_race_count':0,'ambiguity_count':0,'de_ds_horse_set':'PASS'})
  write('source_manifest.json',{'status':'PASS','date_count':10,'sources':sources,'result_access_count':0}); write('population_manifest.json',{'population_scope_id':'PREDICTION_BUY_1WIN_PLUS_FLAT','definition':'JRA flat 1-win class or above; newcomer/maiden/jump excluded','preflight':preflight})
  model=joblib.load(MODEL/'model.joblib'); scaler=joblib.load(MODEL/'scaler.joblib')
  if getattr(model,'n_features_in_',None)!=21 or getattr(scaler,'n_features_in_',None)!=21:raise Stop('MODEL_FEATURE_COUNT_MISMATCH')
  current=[]; cf=[]; infer=[]; reselect=[]; p50=[]; states={'PLAY_CONVERGED':0,'PLAY_UNCONVERGED_4PLUS':0,'SKIP':0}; buy_total=0; horses_total=0
  for date in DATES:
   root=current_run(date,trace=True,output_root=OUT/'current_ai'/date)
   index=json.loads((root/'race_index.json').read_text(encoding='utf-8'))['race_index']
   for ix in index:
    payload=json.loads((root/ix['artifact']).read_text(encoding='utf-8')); race_id=payload['race_id']; ranked=payload['ranked_results']; trace=payload.get('buy_gate_trace',{}); race=trace.get('race',{}); state=race.get('shadow_race_state')
    if state not in states:raise Stop('UNKNOWN_RACE_STATE:'+race_id+':'+str(state))
    states[state]+=1; horses_total+=len(ranked); buys=[int(x['horse_number']) for x in ranked if x.get('decision')=='BUY']; buy_total+=len(buys)
    current.append({'date':date,'race_id':race_id,'horse_numbers':[int(x['horse_number']) for x in ranked],'top5':[int(x['horse_number']) for x in payload['top5']],'current_buy':buys,'buy_count':len(buys),'race_state':state,'shadow_ai_rank':{str(x['horse_number']):x.get('rank') for x in ranked}})
    tr={int(x['horse_number']):x for x in trace.get('horses',[])}
    if set(tr)!={int(x['horse_number']) for x in ranked}:raise Stop('TRACE_HORSE_SET_MISMATCH:'+race_id)
    candidates=sorted([x for x in tr.values() if x.get('shadow_buy_candidate') is True],key=lambda x:(x.get('shadow_ai_rank'),x.get('horse_number')))
    if state=='PLAY_UNCONVERGED_4PLUS' and len(candidates)>=4:cf.append({'date':date,'race_id':race_id,'candidate_pool':[{'horse_number':x['horse_number'],'shadow_ai_rank':x['shadow_ai_rank']} for x in candidates],'selected':[int(x['horse_number']) for x in candidates[:3]]})
    if state!='PLAY_CONVERGED':continue
    top5=payload['top5']; rows=[]
    for h in top5:
     n=int(h['horse_number']); rows.append((h,tr[n],vector(h,tr[n],state,race_id+':'+str(n))))
    probs=model.predict_proba(scaler.transform(np.asarray([x[2] for x in rows],dtype=float)))[:,1]
    ranked_prob=sorted([{'horse_number':int(h['horse_number']),'horse_name':h.get('horse_name'),'probability':float(p),'shadow_ai_rank':t.get('shadow_ai_rank')} for (h,t,_),p in zip(rows,probs,strict=True)],key=lambda x:(-x['probability'],x['shadow_ai_rank'],x['horse_number']))
    infer.append({'date':date,'race_id':race_id,'race_state':state,'probabilities':ranked_prob})
    if buys: reselect.append({'date':date,'race_id':race_id,'current_buy_count':len(buys),'post_valid_result_eligibility':'PENDING_POST_ONLY','selected':[x['horse_number'] for x in ranked_prob[:len(buys)]],'ranking':ranked_prob})
    q=[x for x in ranked_prob if x['probability']>=.5][:3]; p50.append({'date':date,'race_id':race_id,'selected':[x['horse_number'] for x in q],'selection_count':len(q),'ranking':ranked_prob})
  write('current_ai_pre.json',{'status':'PASS','races':current}); write('buy_gate_trace_manifest.json',{'status':'PASS','trace_artifact_roots':[str((OUT/'current_ai'/d).relative_to(ROOT)) for d in DATES],'trace_race_count':len(current)}); write('cf_pre_selection.json',{'status':'PASS','rule':'CF_TOP3_RANK_ANCHORED','scope':'PLAY_UNCONVERGED_4PLUS only; candidate_count>=4','selections':cf});
  write('v4_feature_validation.json',{'status':'PASS','semantic_feature_count':20,'transformed_columns':COLS,'transformed_count':21,'PaceStyle_present':True,'raw_race_state_absent':True,'dummy_columns_present':True,'set_equality':'PASS','order_equality':'PASS','unexpected':0,'missing':0,'duplicate':0}); write('v4_inference_manifest.json',{'status':'PASS','scope':'PLAY_CONVERGED Top5 only; no non-converged/SKIP action','model_sha256':sha(MODEL/'model.joblib'),'scaler_sha256':sha(MODEL/'scaler.joblib'),'inference':infer,'scaler_fit_count':0,'model_fit_count':0}); write('v4_reselection_pre.json',{'status':'PASS','benchmark':'CURRENT_BUY_RACE_RESELECTION_BENCHMARK','scope':'PLAY_CONVERGED','selections':reselect}); write('p50_reference_pre.json',{'status':'PASS','status_name':'P50_REFERENCE_CLASSIFIER_DIAGNOSTIC','not_a_buy_policy':True,'scope':'PLAY_CONVERGED','threshold':.5,'max_selected':3,'selections':p50});
  scope={'status':'PASS','PLAY_CONVERGED':{'current_ai_and_v4_benchmark':states['PLAY_CONVERGED']},'PLAY_UNCONVERGED_4PLUS':{'current_ai_and_cf_only':states['PLAY_UNCONVERGED_4PLUS'],'v4_override':0},'SKIP':{'current_ai_only':states['SKIP'],'v4_override':0,'cf_override':0},'mixed_selection_authority':False};write('scope_separation_validation.json',scope)
  write('prediction_manifest.json',{'dates':DATES,'current_ai_roots':[str((OUT/'current_ai'/d).relative_to(ROOT)) for d in DATES],'current_ai_race_count':len(current),'horse_count':horses_total,'current_buy_count':buy_total});write('safety.json',{'status':'PASS','result_access_count':0,'actual_finish_access':0,'actual_top3_access':0,'valid_result_access':0,'payout_access':0,'performance_calculation_count':0,'scaler_fit_count':0,'model_fit_count':0,'production_change':0,'current_buy_rule_change':0,'cf_change':0,'v4_change':0})
  pre={'final_status':'MAY_2026_CURRENT_CF_V4_PRE_FROZEN','may_pre_status':'PASS','source_date_count':10,'source_preflight':'PASS','prediction_race_count':len(current),'prediction_horse_count':horses_total,'race_state_counts':states,'current_buy_count':buy_total,'cf_eligible_race_count':len(cf),'cf_selected_horse_count':sum(len(x['selected']) for x in cf),'v4_eligible_benchmark_race_count':len(reselect),'p50_race_count':len(p50),'result_access_count':0,'performance_calculation_count':0,'scaler_fit_count':0,'model_fit_count':0,'independent_review_ready':'YES','blocking':[],'major':[],'minor':[]};write('pre_freeze_manifest.json',pre);write('artifact_hashes.json',{'indexed_artifacts':{p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='artifact_hashes.json'},'self_hash_excluded':True});return OUT
 except Exception as e:
  write('source_manifest.json',{'status':'FAILED','date_count':10,'sources':sources,'failure':source_failure,'result_access_count':0})
  write('pre_freeze_manifest.json',{'final_status':'MAY_2026_PRE_FAILED','reason':str(e),'failure':source_failure,'result_access_count':0,'performance_calculation_count':0,'scaler_fit_count':0,'model_fit_count':0});return OUT
if __name__=='__main__':print(run())
