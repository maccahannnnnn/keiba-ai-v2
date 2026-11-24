from copy import deepcopy

from review.current_corrected_shadow_v2_prospective_protocol_v1 import Stop, central_jra_meeting_week_id, diagnostic_flags, load_protocol, select_natural, select_primary, validate_start, verdict, verify_freeze_pins
from review.current_corrected_shadow_v2_prospective_pre_v1 import run
from review.current_corrected_shadow_v2_prospective_validators_v1 import validate_ledger, validate_post, validate_pre_start

def shadow(rank, *, candidate=True, buy=False, score=10):
    return {"horse_number": rank, "corrected_shadow": {"rank": rank, "candidate": candidate, "buy": buy, "adjusted_score": score}}

def test_protocol_and_prestar_pins():
    protocol=load_protocol(); assert protocol['minimum_evidence']=={'counted_races':60,'counted_dates':12}; assert protocol['lift_threshold_pt']==0.0; assert protocol['production_authorization'] is False
    assert validate_pre_start(protocol)['freeze_pins']=='PASS'

def test_block_verification_vectors():
    expected={'20260919':'20260919','20260920':'20260919','20260921':'20260919','20260923':'20260919','20260925':'20260919','20260926':'20260926','20260927':'20260926'}
    assert {d:central_jra_meeting_week_id(d) for d in expected}==expected

def test_block_module_pin_mismatch_stops():
    protocol=deepcopy(load_protocol()); protocol['freeze_v6_pins']['central_jra_meeting_week_id_module_sha256']='0'*64
    try: verify_freeze_pins(protocol)
    except Stop as exc: assert str(exc)=='DATE_LEVEL_STOP:TC_BLOCK_PIN_MISMATCH'
    else: assert False

def test_g1_same_day_historical_and_authorized_future():
    protocol=deepcopy(load_protocol()); protocol['formal_execution_authorized']=True
    for date in ('20260930','20260929'):
        try: validate_start(date,protocol,authorization_date='20260930')
        except Stop: pass
        else: assert False
    validate_start('20261001',protocol,authorization_date='20260930')

def test_formal_driver_stops_without_human_authorization():
    try: run('20261001')
    except Stop as exc: assert str(exc)=='STOP_LEGACY_FORMAL_PRE_ENTRYPOINT_DISABLED'
    else: assert False

def test_primary_is_pure_rank_and_candidate_independent():
    rows=[shadow(2,candidate=False,buy=False,score=100),shadow(1,candidate=False,buy=False,score=101),shadow(3,candidate=True,buy=True,score=99)]
    selected,tie=select_primary(rows,2)
    assert [r['horse_number'] for r in selected]==[1,2] and tie is False
    assert [r['horse_number'] for r in select_natural(rows)]==[3]

def test_build_race_artifact_uses_frozen_current_and_v2_rank_only():
    import json
    from pathlib import Path
    from review.current_corrected_shadow_v2_prospective_pre_v1 import build_race_artifact
    from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
    root=Path('reports/daily_pre_analysis_20260926/current_frozen'); index=json.loads((root/'race_index.json').read_text(encoding='utf-8'))['race_index'][0]
    frozen=json.loads((root/index['artifact']).read_text(encoding='utf-8'))
    bundle=TargetBulkPredictionInputAdapterV1().load('data/raw/prediction_input/DG260926.CSV','data/raw/prediction_input/DE260926.CSV','data/raw/prediction_input/DS260926.CSV')
    artifact=build_race_artifact(index['race_id'],bundle.races[index['race_id']],frozen)
    assert len(artifact['primary_selection'])==artifact['target_k']==index['buy_count']
    assert [row['corrected_shadow']['rank'] for row in artifact['primary_selection']]==list(range(1,index['buy_count']+1))

def test_no_pre_backfill_and_date_level_failure_contract():
    protocol=load_protocol(); assert protocol['no_pre']=={'backfill':False,'formal_post_forbidden':True}; assert protocol['corrected_only_failure'].startswith('DATE_LEVEL_STOP')

def test_invalid_results_are_arm_specific_and_not_denominator():
    rows=[{'race_id':'r','horse_number':1,'current_selected':True,'corrected_selected':True,'valid_result':True,'actual_top3':True},{'race_id':'r','horse_number':2,'current_selected':True,'corrected_selected':True,'valid_result':False,'actual_top3':False}]
    assert rows[1]['valid_result'] is False and rows[1]['actual_top3'] is False
    try: validate_post(True,[dict(rows[1],actual_top3=True)])
    except Stop: pass
    else: assert False

def test_verdict_boundaries_and_terminal_immutability():
    assert verdict(59,12,0,10).startswith('HOLD'); assert verdict(60,11,0,10).startswith('HOLD'); assert verdict(60,12,1,10)=='HOLD_VOLUME_CONFOUNDED'
    assert verdict(60,12,0,-0.1).endswith('REJECT'); assert verdict(60,12,0,0).endswith('ACCEPT'); assert verdict(60,12,0,0.1).endswith('ACCEPT')

def test_diagnostics_are_non_gate_and_suspension_requires_human_decision():
    assert diagnostic_flags([-1,2],[('a',3),('b',-5),('c',1)],1)=={'TEMPORAL_FRAGILITY_FLAG','TEMPORAL_CONCENTRATION_FLAG'}
    ledger={'minimum_unit':['races','dates'],'block_is_gate':False,'entries':[],'terminal_verdict':None,'state':'SUSPENDED','suspension_reason':'wait','suspended_at':'2026-09-30T00:00:00+00:00'}
    try: validate_ledger(ledger)
    except Stop: pass
    else: assert False
    ledger['human_decision']='pause'; validate_ledger(ledger)
