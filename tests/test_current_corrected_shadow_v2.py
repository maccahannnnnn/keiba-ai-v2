import json
from pathlib import Path

import review.current_corrected_shadow_v2 as core
from review.current_corrected_shadow_v2 import CorrectionConfigV2, apply_corrected_shadow_v2, map_risks, reliability_predicate, reliability_v2, risk_guard_detail
from review.current_corrected_shadow_v2_aggregator import selections, ranks
def row(n=1,h=3,pp=10,**x):
 d={"horse_number":n,"history_count":h,"past_performance_score":pp,"total_score":20,"distance_score":2,"lap_score":3,"pace_style_score":4,"bloodline_score":1,"track_condition_score":1,"track_bias_score":0,"rank":n,"buy_v1_rc1_buy":True};d.update(x);return d
def test_low_history_boundaries_and_median_and_vote_separation():
 a,b,c,d=apply_corrected_shadow_v2([row(1,0,99),row(2,1,88),row(3,2,10),row(4,3,20)],CorrectionConfigV2.all_on())
 assert a['corrected_shadow']['low_history'] and b['corrected_shadow']['low_history']
 assert not c['corrected_shadow']['low_history'] and not d['corrected_shadow']['low_history']
 assert a['corrected_shadow']['imputation_applied'] and a['corrected_shadow']['past_performance_ranking_score']==15
 assert a['corrected_shadow']['past_performance_vote_score']==99
def test_imputation_unavailable_and_reliability_exact_set():
 s=apply_corrected_shadow_v2([row(1,1,9)],CorrectionConfigV2.all_on())[0]['corrected_shadow'];assert s['imputation_unavailable'] and not s['imputation_applied']
 r=reliability_v2(row(total_score=120,past_performance_score=55,distance_score=30,lap_score=0,pace_style_score=10),55);assert r['authority_evaluators']==['ability','past_performance','distance','lap','pace_style'] and r['pass']
def test_reliability_exact_threshold_boundaries_and_negative_rule():
    x=row(total_score=120,past_performance_score=55,distance_score=30,lap_score=0,pace_style_score=10)
    assert reliability_v2(x,55)['pass']
    x['past_performance_score']=54.9; x['pace_style_score']=9.9; assert not reliability_v2(x,54.9)['pass']
    x=row(total_score=120,past_performance_score=55,distance_score=30,lap_score=-5,pace_style_score=10)
    assert reliability_v2(x,55)['negative_count']==1 and reliability_v2(x,55)['pass']
    x['lap_score']=-4.9; assert reliability_v2(x,55)['negative_count']==0
    x=row(total_score=120,past_performance_score=55,distance_score=30,lap_score=-5,pace_style_score=10)
    x['distance_score']=-5; assert not reliability_v2(x,55)['pass']
def test_risk_semantic_dedupe_and_derived_major_not_authority_or_severe():
    risks,_=map_risks(['距離適性の不安','距離適性に課題','重大リスクが複数'],dedupe=True,authority_filter=True)
    assert len(risks)==1 and risks[0]['semantic_cause']=='distance_concern' and not risks[0]['severe']
    risks,_=map_risks(['重大リスクが複数'],dedupe=True,authority_filter=True)
    assert risks==[]
def test_risk_guard_count_data_limitation_and_current_severe_only():
    base=row(total_score=120,past_performance_score=55,distance_score=30,lap_score=0,pace_style_score=10)
    five=[dict(base,horse_number=i+1,weaknesses=['距離適性の不安'] if i==0 else []) for i in range(5)]
    # Five independent authority causes must pass; six must fail.
    causes=['距離適性の不安','近走内容に課題','当日バイアス情報が限定的','入力データに一部不足あり','データ不足が大きい','評価値が欠損']
    rows=[dict(base,horse_number=i+1,weaknesses=[cause]) for i,cause in enumerate(causes)]
    out=apply_corrected_shadow_v2(rows,CorrectionConfigV2.all_on())
    assert all(not r['corrected_shadow']['risk_guard'] for r in out[4:])  # true data limitation blocks
    assert all(r['corrected_shadow']['risk_guard'] for r in out[:4])
    concern=apply_corrected_shadow_v2([dict(base,weaknesses=['距離適性の不安'])],CorrectionConfigV2.all_on())[0]['corrected_shadow']
    assert concern['risk_guard'] and not concern['risk_guard_detail']['severe']
    for text in ['取消','除外','出走不能','能力不足','距離不適']:
        blocked=apply_corrected_shadow_v2([dict(base,weaknesses=[text])],CorrectionConfigV2.all_on())[0]['corrected_shadow']
        assert not blocked['risk_guard'] and blocked['risk_guard_detail']['severe']
def test_one_horse_five_six_risk_count_and_final_reliability_predicate():
    five=[{'category':'GENUINE_INDEPENDENT_RISK','semantic_cause':str(i),'severe':False} for i in range(5)]
    six=five+[{'category':'GENUINE_INDEPENDENT_RISK','semantic_cause':'six','severe':False}]
    assert risk_guard_detail(five,True)['pass'] and risk_guard_detail(five,True)['authority_risk_count']==5
    assert not risk_guard_detail(six,True)['pass'] and risk_guard_detail(six,True)['risk_count_fail']
    assert reliability_predicate(4,1) and not reliability_predicate(4,2) and not reliability_predicate(3,0)
def test_risk_config_isolation_reliability_only_and_all_off():
    base=row(total_score=120,past_performance_score=55,distance_score=30,lap_score=0,pace_style_score=10)
    traces=['展開面の不安','ラップ適性の不安','展開不向き','構造一致度が低い','コース形状とのズレ','構造との矛盾あり']
    reliable=apply_corrected_shadow_v2([dict(base,weaknesses=traces)],CorrectionConfigV2(reliability_correction=True))[0]['corrected_shadow']
    assert reliable['reliability']['pass'] and reliable['risk_guard'] and reliable['risk_guard_detail']['authority_risk_count']==0
    off=apply_corrected_shadow_v2([dict(base,weaknesses=['データ不足が大きい'])],CorrectionConfigV2.all_off())[0]['corrected_shadow']
    assert off['risk_guard'] and off['risk_guard_detail']['authority_risk_count']==0
    on=apply_corrected_shadow_v2([dict(base,weaknesses=['データ不足が大きい'])],CorrectionConfigV2(risk_authority_filter=True))[0]['corrected_shadow']
    assert not on['risk_guard'] and on['risk_guard_detail']['true_data_limitation']
def test_individual_correction_flags_are_independent():
    assert CorrectionConfigV2(neutral_pace=True).neutral_pace
    assert not CorrectionConfigV2(neutral_pace=True).reliability_correction
def test_real_runner_neutral_pace_reaches_all_required_consumers():
    from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
    from review.current_corrected_shadow_v2_runner import PACE_DEPENDENT_CONSUMERS, run_new_v2
    bundle=TargetBulkPredictionInputAdapterV1().load('data/raw/prediction_input/DG260921.CSV','data/raw/prediction_input/DE260921.CSV','data/raw/prediction_input/DS260921.CSV')
    race_id=sorted(bundle.races)[0]
    output=run_new_v2(race_id,bundle.races[race_id],CorrectionConfigV2.all_on())
    assert output['v2_pace_trace']['predicted_pace_original'] is not None
    assert output['v2_pace_trace']['pace_authority_input']=='average'
    assert set(PACE_DEPENDENT_CONSUMERS)=={'RacePacePredictor','RaceStructureEngine','RaceShapeEvaluator','CourseShapeEvaluator','LapSuitabilityEvaluator','ConsistencyEngine'}
    assert all(row['pace_authority_input']=='average' and isinstance(row['lap_result'],dict) and isinstance(row['consistency_result'],dict) for row in output['ranked_results'])
def test_current_corrected_field_separation():
 rows=[row(1,rank=1,buy_v1_rc1_buy=True),row(2,rank=8,buy_v1_rc1_buy=False)]
 rows[0]['corrected_shadow']={'rank':8,'buy':False};rows[1]['corrected_shadow']={'rank':1,'buy':True}
 assert [r['horse_number'] for r in selections(rows,'current')]==[1]
 assert [r['horse_number'] for r in selections(rows,'corrected')]==[2]
 assert ranks(rows,'current')==[1,8] and ranks(rows,'corrected')==[8,1]

def test_one_cause_multi_gate_is_deduped_by_actual_guard_processing():
    base=row(total_score=120,past_performance_score=55,distance_score=30,lap_score=0,pace_style_score=10)
    output=apply_corrected_shadow_v2([dict(base,weaknesses=['距離適性の不安'],risk_factors=['距離適性に課題'],decision_risks=['距離適性の不安'])],CorrectionConfigV2.all_on())[0]['corrected_shadow']
    assert output['risk_guard']
    assert output['risk_guard_detail']['authority_risk_count']==1
    assert [item['semantic_cause'] for item in output['authority_risks']]==['distance_concern']

def test_trace_only_risks_never_become_authority():
    base=row(total_score=120,past_performance_score=55,distance_score=30,lap_score=0,pace_style_score=10)
    traces=['展開面の不安','構造一致度が低い','コース形状とのズレ','重大リスクが複数']
    output=apply_corrected_shadow_v2([dict(base,weaknesses=traces)],CorrectionConfigV2.all_on())[0]['corrected_shadow']
    assert output['risk_guard']
    assert output['risk_guard_detail']['authority_risk_count']==0
    assert output['authority_risks']==[]

def test_true_data_limitation_exact_keywords_only():
    base=row(total_score=120,past_performance_score=55,distance_score=30,lap_score=0,pace_style_score=10)
    for text in ['データ不足が大きい','評価値が欠損','構造評価に必要な情報が不足']:
        output=apply_corrected_shadow_v2([dict(base,weaknesses=[text])],CorrectionConfigV2.all_on())[0]['corrected_shadow']
        assert not output['risk_guard'] and output['risk_guard_detail']['true_data_limitation']
    for text in ['当日バイアス情報が限定的','入力データに一部不足あり']:
        output=apply_corrected_shadow_v2([dict(base,weaknesses=[text])],CorrectionConfigV2.all_on())[0]['corrected_shadow']
        assert output['risk_guard'] and not output['risk_guard_detail']['true_data_limitation']

def test_pp_vote_uses_original_actual_reliability_argument():
    rows=[row(1,1,99,total_score=120,distance_score=30,lap_score=0,pace_style_score=10),row(2,2,15,total_score=120,distance_score=30,lap_score=0,pace_style_score=10)]
    observed=[]; original=core.reliability_v2
    def spy(source, original_pp):
        observed.append(original_pp)
        return original(source, original_pp)
    core.reliability_v2=spy
    try:
        output=apply_corrected_shadow_v2(rows,CorrectionConfigV2(low_history_neutralization=True,reliability_correction=True,equal_component_weights=True))
    finally:
        core.reliability_v2=original
    assert observed[0]==99
    assert output[0]['corrected_shadow']['reliability']['scores']['past_performance']==99

def test_pp_rank_uses_neutralized_value_in_actual_integrated_score():
    source=[row(1,1,99),row(2,2,15)]
    neutral=apply_corrected_shadow_v2(source,CorrectionConfigV2(low_history_neutralization=True,equal_component_weights=True))[0]['corrected_shadow']
    original=apply_corrected_shadow_v2(source,CorrectionConfigV2(equal_component_weights=True))[0]['corrected_shadow']
    assert neutral['past_performance_ranking_score']==15
    assert neutral['integrated_score'] != original['integrated_score']
    assert neutral['integrated_score'] == original['integrated_score'] - 84

def test_actual_pace_consumers_receive_average_and_lap_is_recomputed():
    from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
    from review.current_corrected_shadow_v2_runner import CorrectedAuthorityAdapter, run_new_v2
    bundle=TargetBulkPredictionInputAdapterV1().load('data/raw/prediction_input/DG260921.CSV','data/raw/prediction_input/DE260921.CSV','data/raw/prediction_input/DS260921.CSV')
    race_id=sorted(bundle.races)[0]; observed={key:[] for key in ('RaceStructureEngine','RaceShapeEvaluator','CourseShapeEvaluator','LapSuitabilityEvaluator','ConsistencyEngine')}
    original_init=CorrectedAuthorityAdapter.__init__
    def instrumented_init(self,*args,**kwargs):
        original_init(self,*args,**kwargs)
        original_structure=self.race_structure_engine.analyze
        self.race_structure_engine.analyze=lambda payload: (observed['RaceStructureEngine'].append(payload.get('pace_prediction')),original_structure(payload))[1]
        original_shape=self.race_shape_evaluator.evaluate_many
        self.race_shape_evaluator.evaluate_many=lambda pace,*args,**kw: (observed['RaceShapeEvaluator'].append(pace),original_shape(pace,*args,**kw))[1]
        original_course=self.course_shape_evaluator.evaluate_many
        self.course_shape_evaluator.evaluate_many=lambda horses,pace,*args,**kw: (observed['CourseShapeEvaluator'].append(pace.get('pace_prediction')),original_course(horses,pace,*args,**kw))[1]
        original_lap=self.lap_suitability_evaluator.evaluate_many
        def lap(horses,pace,*args,**kw):
            observed['LapSuitabilityEvaluator'].append(pace.get('pace_prediction'))
            return original_lap(horses,pace,*args,**kw)
        self.lap_suitability_evaluator.evaluate_many=lap
        original_consistency=self.consistency_engine.evaluate
        self.consistency_engine.evaluate=lambda item,*args,**kw: (observed['ConsistencyEngine'].append(item.get('race_pace_prediction')),original_consistency(item,*args,**kw))[1]
    CorrectedAuthorityAdapter.__init__=instrumented_init
    try:
        output=run_new_v2(race_id,bundle.races[race_id],CorrectionConfigV2(neutral_pace=True))
    finally:
        CorrectedAuthorityAdapter.__init__=original_init
    assert all(values and set(values)=={'average'} for values in observed.values())
    assert all(isinstance(item.get('lap_result'),dict) and item.get('lap_score')==item['lap_result'].get('lap_score') for item in output['ranked_results'])

def test_pace_consumer_inventory_is_repository_derived_and_complete():
    from review.current_corrected_shadow_v2_test_report_v6 import discover_pace_consumers
    from review.current_corrected_shadow_v2_runner import PACE_DEPENDENT_CONSUMERS
    discovered=discover_pace_consumers()
    assert set(discovered)==set(PACE_DEPENDENT_CONSUMERS)

def test_canonical_artifacts_are_complete_and_result_free():
    root=Path('reports/current_corrected_shadow_v2_technical_replay_v5_final')
    off=json.loads((root/'all_off_reproduction_report.json').read_text(encoding='utf-8'))
    on=json.loads((root/'all_on_manifest.json').read_text(encoding='utf-8'))
    vocab=json.loads((root/'risk_vocabulary_inventory.json').read_text(encoding='utf-8'))
    assert (off['race_count'],off['horse_count'],off['OBSERVABLE_MISMATCH'])==(1472,19929,0)
    assert (on['output_race_count'],on['output_horse_count'])==(1472,19929)
    assert vocab['UNMAPPED_RISK_TEXT_COUNT']==0 and len(vocab['items'])==33
    assert on['RESULT_ACCESS']==0 and on['PERFORMANCE_EVALUATION'] is False
    required={'version','integrated_score','adjusted_score','score_components','low_history','history_count','imputation_applied','imputation_unavailable','past_performance_ranking_score','past_performance_vote_score','reliability','authority_risks','risk_guard','risk_guard_detail','trace','rank','candidate','race_state','buy'}
    artifacts=sorted((root/'all_on_outputs').glob('*.json'))
    assert len(artifacts)==1472
    for artifact in artifacts:
        payload=json.loads(artifact.read_text(encoding='utf-8'))
        assert all(required <= set(entry['corrected_shadow']) for entry in payload['corrected_rows'])

def test_nonrisk_flag_and_bundled_risk_family_isolation():
    base=row(total_score=120,past_performance_score=55,distance_score=30,lap_score=0,pace_style_score=10,weaknesses=['データ不足が大きい'])
    low=apply_corrected_shadow_v2([dict(base,history_count=1),dict(base,horse_number=2,history_count=2,past_performance_score=15)],CorrectionConfigV2(low_history_neutralization=True,equal_component_weights=True))[0]['corrected_shadow']
    reliable=apply_corrected_shadow_v2([base],CorrectionConfigV2(reliability_correction=True))[0]['corrected_shadow']
    bundled=apply_corrected_shadow_v2([base],CorrectionConfigV2(risk_semantic_dedupe=True,risk_authority_filter=True,severe_rule=True))[0]['corrected_shadow']
    assert low['imputation_applied'] and low['risk_guard']
    assert reliable['reliability']['pass'] and reliable['risk_guard']
    assert not bundled['risk_guard'] and bundled['risk_guard_detail']['true_data_limitation']

def test_v6_report_registry_matches_real_test_source():
    from review.current_corrected_shadow_v2_test_report_v6 import validate_registry
    assert validate_registry()['TEST_REPORT_SOURCE_CONSISTENCY']=='PASS'
