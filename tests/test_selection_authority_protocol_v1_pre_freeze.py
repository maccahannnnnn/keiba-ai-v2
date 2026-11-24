from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
import unittest
import uuid

from review import selection_authority_protocol_v1_pre_freeze as sut


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'reports' / 'daily_pre_prediction_20260913' / 'current_frozen'


def _reference_module():
    path = ROOT / 'review' / 'prospective_three_system_pre_freeze_v1.py'
    spec = importlib.util.spec_from_file_location('v4_reference_for_equivalence_test', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _payloads():
    index=json.loads((FIXTURE/'race_index.json').read_text(encoding='utf8'))['race_index']
    return [json.loads((FIXTURE/item['artifact']).read_text(encoding='utf8')) for item in index]


class SelectionAuthorityProtocolV1Tests(unittest.TestCase):
    def test_frozen_protocol_and_model_identity_are_pinned(self):
        protocol=sut.load_frozen_protocol()
        _,_,identity=sut.load_frozen_v5(protocol)
        self.assertEqual(protocol['identity']['protocol_status'],'FROZEN_PRE_IMPLEMENTATION')
        self.assertEqual(identity['model_name'],'V4 Model v5')
        self.assertEqual(identity['model_version'],'V4 Model v5')
        self.assertEqual(identity['model_sha256'],sut.FROZEN_MODEL_SHA256)

    def test_model_version_is_independent_authority_field_and_contract_is_complete(self):
        metadata=json.loads((ROOT/'reports/ml_v4_buy_selection_model_v5/model_metadata.json').read_text(encoding='utf8'))
        protocol=sut.load_frozen_protocol()
        base=ROOT / f'.selection_authority_protocol_v1_version_test_{uuid.uuid4().hex}'
        try:
            output=sut.run_technical_wiring('20260913',FIXTURE,base/'artifact')
            semantic=json.loads((output/'semantic_selection.json').read_text(encoding='utf8'))
            self.assertIn('model_name',semantic['model'])
            self.assertIn('model_version',semantic['model'])
            self.assertEqual(semantic['model']['model_version'],metadata['version'])
            expected,missing=sut.pre_artifact_required_field_completeness(protocol,semantic)
            self.assertEqual(expected,37)
            self.assertEqual(missing,[])
        finally:
            if base.exists():
                shutil.rmtree(base)

    def test_model_version_negative_fixture_fails_closed(self):
        protocol=sut.load_frozen_protocol()
        metadata=json.loads((ROOT/'reports/ml_v4_buy_selection_model_v5/model_metadata.json').read_text(encoding='utf8'))
        metadata['version']='V4 Model v999'
        with self.assertRaisesRegex(sut.Stop,'MODEL_VERSION_MISMATCH'):
            sut._validated_model_version(metadata,protocol['model_contract'])

    def test_local_helpers_exactly_match_reference_on_outcome_free_fixture(self):
        reference=_reference_module(); checked=0
        for payload in _payloads():
            trace=payload['buy_gate_trace']; state=trace['race']['shadow_race_state']
            traces={int(x['horse_number']):x for x in trace['horses']}
            for horse in payload['ranked_results']:
                context=f"{payload['race_id']}:{horse['horse_number']}"
                self.assertEqual(sut.frozen_local_vector(horse,traces[int(horse['horse_number'])],state,context),reference.vector(horse,traces[int(horse['horse_number'])],state,context))
                checked+=1
        self.assertGreater(checked,0)
        for value in (1, 2.0, 99): self.assertEqual(sut.safe_rank(value,'x'),reference.safe_rank(value,'x'))
        for value in (True,False): self.assertEqual(sut.boolean(value,'x'),reference.boolean(value,'x'))
        for value in (0,1.5,True,None):
            with self.assertRaises(Exception): sut.safe_rank(value,'x')

    def test_technical_wiring_is_deterministic_and_isolated(self):
        # Direct workspace children avoid the host Temp ACL issue; each path
        # is test-owned and removed in the finally clause below.
        base=ROOT / f'.selection_authority_protocol_v1_test_{uuid.uuid4().hex}'
        try:
            one=sut.run_technical_wiring('20260913',FIXTURE,base/'one')
            two=sut.run_technical_wiring('20260913',FIXTURE,base/'two')
            self.assertEqual((one/'semantic_selection.json').read_bytes(),(two/'semantic_selection.json').read_bytes())
            payload=json.loads((one/'semantic_selection.json').read_text(encoding='utf8'))
            self.assertEqual(payload['evidence_role'],'TECHNICAL_WIRING_TEST_ONLY')
            self.assertIs(payload['formal_evidence'],False)
            self.assertTrue(all(r['race_status'] in {'SUCCESS','NOT_RUN'} for r in payload['races']))
            for race in payload['races']:
                if race['race_status']=='SUCCESS':
                    self.assertEqual(race['shortfall'],max(0,race['target_k']-race['selected_n']))
                    self.assertTrue(all(h['selection_exclusion_reason'] in {'SELECTED','OUTSIDE_EXACT5','RISK_GUARD_FAIL','NOT_SELECTED_WITHIN_TARGET_K'} for h in race['horses']))
        finally:
            if base.exists():
                shutil.rmtree(base)

    def test_atomic_fail_closed_for_non_play_current_buy(self):
        payload=_payloads()[0]
        payload['buy_gate_trace']['race']['shadow_race_state']='SKIP'
        payload['ranked_results'][0]['buy']=True
        protocol=sut.load_frozen_protocol(); model,scaler,identity=sut.load_frozen_v5(protocol)
        result=sut._race_result('20260913',payload,'0'*64,model,scaler,identity)
        self.assertEqual(result['race_status'],'NOT_RUN')
        self.assertEqual(result['not_run_reason'],'BUY_COUNT_GTE_1_BUT_RACE_STATE_NOT_PLAY_CONVERGED')
        self.assertEqual(result['horses'],[])
