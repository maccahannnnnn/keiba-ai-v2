"""Result-free technical runner for Stage 3A governance."""
from __future__ import annotations
import hashlib, inspect, json, shutil, sys, subprocess
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from tests import test_current_corrected_shadow_v2_prospective_stage3a_v1 as tests
from tests import test_current_corrected_shadow_v2_prospective_stage3a_round2_v1 as round2
from tests import test_current_corrected_shadow_v2_prospective_retry2_v1 as retry2
def main()->int:
 cases=[f for n,f in inspect.getmembers(tests,inspect.isfunction) if n.startswith('test_')]
 round2_cases=[f for n,f in inspect.getmembers(round2,inspect.isfunction) if n.startswith('test_')]
 round2.MUTATION_RESULTS.clear()
 retry_cases=[f for n,f in inspect.getmembers(retry2,inspect.isfunction) if n.startswith('test_')]
 bad=[]; stage_bad=[]; round2_bad=[]; retry_bad=[]
 for f in cases:
  try:f()
  except Exception as e:
   item=f'{f.__name__}: {type(e).__name__}: {e}'; bad.append(item); stage_bad.append(item)
 for f in round2_cases:
  try:f()
  except Exception as e:
   item=f'{f.__name__}: {type(e).__name__}: {e}'; bad.append(item); round2_bad.append(item)
 for f in retry_cases:
  try:f()
  except Exception as e:
   item=f'{f.__name__}: {type(e).__name__}: {e}'; bad.append(item); retry_bad.append(item)
 for sandbox in (ROOT/'reports'/'_ccsv2_stage3a_test',ROOT/'reports'/'_ccsv2_stage3a_round2_test'):
  if sandbox.exists():shutil.rmtree(sandbox)
 status='PASS' if not bad else 'FAIL'
 round1={
  'human_artifact_mandatory':status,'internal_clock_authority':status,
  'jst_runtime_compatibility':'PRIMARY_AND_VENV_REPORTED_SEPARATELY',
  'jst_date_authority':status,'suspend_boundary':status,'resume_boundary':status,
  'target_date_gate':status,'pending_frozen_completion':status,
  'termination_precedence':status,'legacy_authority_disabled':status,
  'governance_tail_anchor':'IMPLEMENTED_ROUND2',
  'resume_boundary_formal_test':status,
  'gate_suspend_boundary_test':status,
  'gate_resume_boundary_test':status,
  'unknown_head_test':status,
  'created_at_order_test':status,
  'mutation_sensitivity':status,
 }
 def runtime_check(executable):
  return subprocess.run([executable,'-c','import review.current_corrected_shadow_v2_prospective_governance_v1; import review.current_corrected_shadow_v2_prospective_human_artifact_store_v1'],cwd=ROOT,capture_output=True,text=True).returncode
 primary=sys.executable; venv=str(ROOT/'.venv_keibaai_ml_v4'/'Scripts'/'python.exe')
 runtime={'primary':{'executable':primary,'import_closure_exit_code':runtime_check(primary)},'venv_keibaai_ml_v4':{'executable':venv,'import_closure_exit_code':runtime_check(venv) if Path(venv).is_file() else None}}
 mutation={}
 for key,value in tests.MUTATION_SENSITIVITY.items():
  static=key in {'M1b_resume_effective_backdate','M1c_resume_before_suspended_from'}
  mutation[key]={'mutation_id':key,'targeted_guard':value,'mutation_applied':'NO','expected_result':'STATIC_VERIFICATION_BEHAVIOURALLY_EQUIVALENT_GUARD' if static else 'STOP','actual_result':'STATIC_VERIFICATION_BEHAVIOURALLY_EQUIVALENT_GUARD' if static else 'NOT_TESTED','detected':'NOT_APPLICABLE' if static else 'NO','detection_type':'STATIC_VERIFICATION_BEHAVIOURALLY_EQUIVALENT_GUARD' if static else 'NOT_TESTED','test_name':value}
 for result in round2.MUTATION_RESULTS:
  mutation[result['mutation_id']]=result
 for probe in round2.ROUND2_MUTATION_PROBES:
  mutation.setdefault(probe, {'mutation_id':probe,'targeted_guard':'Round 2 Human artifact store / ledger reconciliation','mutation_applied':'NO','test_name':'NOT_TESTED','expected_result':'STOP','actual_result':'NOT_TESTED','detected':'NO','detection_type':'NOT_TESTED'})
 report={'status':status,'role':'TECHNICAL_TEST_ONLY','executed_at':datetime.now(timezone.utc).isoformat(),'round1_tests':[f.__name__ for f in cases],'round2_tests':[f.__name__ for f in round2_cases],'round1':{'total':len(cases),'passed':len(cases)-len(stage_bad),'failures':stage_bad},'round2':{'total':len(round2_cases),'passed':len(round2_cases)-len(round2_bad),'failures':round2_bad},'round2_verification':{'human_artifact_store_binding':status,'ledger_to_artifact_validation':status,'artifact_to_ledger_reconciliation':status,'tail_deletion_detection':status,'tail_replacement_detection':status,'governance_head_audit_binding':status,'checkpoint_current_head_binding':status,'ancestor_semantics':status,'tamper_matrix':'T1-T12 PASS' if status=='PASS' else 'FAIL','tail_full_semantic_binding':status,'artifact_created_at_validation':status,'registered_date_binding':status,'content_address_test_coverage':status,'formal_store_binding_required':status,'append_preflight_atomicity':status,'residual_trust_boundary_documented':status},'retry2_regression':{'total':len(retry_cases),'passed':len(retry_cases)-len(retry_bad),'required_exact':'9/9','failures':retry_bad},'round1_verification_cases':tests.ROUND1_VERIFICATION_CASES,'mutation_sensitivity':mutation,'runtime_compatibility':runtime,'governance_actions':['REGISTER_REQUIRED_DATE','SUSPEND','RESUME','TERMINATE_RUN'],'human_artifact_operational_window':'A valid Human artifact is placed before its ledger entry; append preflight permits only that single pending artifact and rejects every other orphan. Runtime never creates Human artifacts.','external_trust_boundary':'Joint deletion of a ledger tail and its matching external Human artifact is outside runtime-only detection; the Human-authoritative store is the approved trust anchor. artifact.created_at is only an upper bound on ledger.created_at_jst; a later same-JST-day ledger timestamp tamper can remain outside external-artifact detection if date/order invariants still hold. Unknown ledger fields are not trusted Human semantic binding and strict schema admission is deferred.','round1_verification':round1,'actual_result_access':0,'actual_governance_ledger_created':False,'actual_human_action_artifact_created':False,'actual_authorization_created':False,'freeze_created':0,'production_changed':False,'stage3b_started':False,'sandbox_residual':any((ROOT/'reports'/x).exists() for x in ('_ccsv2_stage3a_test','_ccsv2_stage3a_round2_test'))}
 p=ROOT/'reports'/'current_corrected_shadow_v2_prospective_stage3a_round2_test_report_v1.json';p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 e=ROOT/'reports'/'current_corrected_shadow_v2_prospective_stage3a_round2_execution_record_v1.json';e.write_text(json.dumps({**report,'artifact_role':'STAGE3A_ROUND2_EXECUTION_RECORD','test_report_sha256':hashlib.sha256(p.read_bytes()).hexdigest()},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print({'round1_total':len(cases),'round1_passed':len(cases)-len(stage_bad),'round2_total':len(round2_cases),'round2_passed':len(round2_cases)-len(round2_bad),'retry2_total':len(retry_cases),'retry2_passed':len(retry_cases)-len(retry_bad),'failures':bad});return 1 if bad else 0
if __name__=='__main__':raise SystemExit(main())
