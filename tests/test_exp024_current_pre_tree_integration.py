"""Current runner provenance -> EXP-024 verification; never accesses Results."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from review import prospective_prediction_runner_v1 as runner
from review import pl_same_volume_reselection_shadow_v1 as shadow
from review.current_environment_tree_hash_v1 import tree_hash
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


class CurrentPreTreeIntegrationTests(unittest.TestCase):
    def test_shared_tree_hash_equivalence(self):
        for name in ('engine','evaluation','knowledge'):
            self.assertEqual(runner.tree_hash(runner.ROOT/name),shadow.tree_hash(shadow.ROOT/name))
            self.assertEqual(runner.tree_hash(runner.ROOT/name),tree_hash(runner.ROOT/name))

    def test_runner_provenance_to_shadow_build_with_real_current_path(self):
        date='20260627'
        paths=[runner.RAW/f'{kind}{date[2:]}.CSV' for kind in ('DG','DE','DS')]
        bundle=TargetBulkPredictionInputAdapterV1().load(*paths)
        race_id,race=next(iter(sorted(bundle.races.items())))
        baseline=runner.run_new(race_id,race,trace=True)
        expected=runner._project_race(race_id,baseline)
        expected['buy_gate_trace']=baseline['buy_gate_trace']
        expected['trace_status']='NOT_FORMALLY_FROZEN_TRACE'
        single=SimpleNamespace(date=date,races={race_id:race},preflight=bundle.preflight)
        with tempfile.TemporaryDirectory(dir=runner.ROOT) as temp:
            out=Path(temp)/'current_pre'
            with patch.object(runner.TargetBulkPredictionInputAdapterV1,'load',return_value=single):
                runner.run(date,trace=True,output_root=out)
            provenance=json.loads((out/'provenance.json').read_text(encoding='utf8'))
            for name in ('engine','evaluation','knowledge'):
                self.assertEqual(provenance[name+'_tree_sha256'],tree_hash(runner.ROOT/name))
            self.assertEqual(provenance['runner_sha256'],shadow.sha(Path(runner.__file__)))
            self.assertEqual(provenance['target_bulk_prediction_input_adapter_sha256'],shadow.sha(runner.ROOT/'review/target_bulk_prediction_input_adapter_v1.py'))
            index=json.loads((out/'race_index.json').read_text(encoding='utf8'))['race_index']
            observed=json.loads((out/index[0]['artifact']).read_text(encoding='utf8'))
            self.assertEqual(observed,expected)
            self.assertEqual(observed['buys'],expected['buys'])
            # PL is stubbed only here: this integration tests provenance plumbing, not model output.
            def no_pl(model,payloads,**kwargs):
                p=payloads[0][1]
                return {'races':[{'race_id':p['race_id'],'inference_status':'INFERENCE_UNAVAILABLE','reason':'TEST_STUB'}],
                        'horses':[{'race_id':p['race_id'],'horse_number':h['horse_number']} for h in p['ranked_results']]}
            with patch.object(shadow.pl,'load_model',return_value=(object(),shadow.MODEL_SHA)),\
                 patch.object(shadow.pl,'infer_payloads',side_effect=no_pl):
                built=shadow.build_pre(out,shadow.ROOT/'knowledge')
            self.assertEqual(built['current_environment']['tree_provenance_status'],'VERIFIED')
            self.assertEqual(built['current_environment_components']['target_bulk_prediction_input_adapter_sha256'],provenance['target_bulk_prediction_input_adapter_sha256'])
            self.assertEqual(len(built['current_environment_fingerprint']),64)
            self.assertEqual(built['block_id'],'BLOCK_'+built['current_environment_fingerprint'])
            self.assertEqual(built['races'][0]['current_selected_horses'],sorted(x['horse_number'] for x in expected['buys']))

    def test_adapter_mutation_during_run_fails_closed(self):
        date='20260627'
        paths=[runner.RAW/f'{kind}{date[2:]}.CSV' for kind in ('DG','DE','DS')]
        bundle=TargetBulkPredictionInputAdapterV1().load(*paths)
        race_id,race=next(iter(sorted(bundle.races.items())))
        single=SimpleNamespace(date=date,races={race_id:race},preflight=bundle.preflight)
        adapter=runner.ROOT/'review/target_bulk_prediction_input_adapter_v1.py'
        actual=runner._sha256; calls=[]
        def changing_sha(path):
            if path==adapter:
                calls.append(path)
                return actual(path) if len(calls)==1 else '0'*64
            return actual(path)
        with tempfile.TemporaryDirectory(dir=runner.ROOT) as temp:
            out=Path(temp)/'pre'
            with patch.object(runner.TargetBulkPredictionInputAdapterV1,'load',return_value=single),patch.object(runner,'_sha256',side_effect=changing_sha):
                with self.assertRaisesRegex(RuntimeError,'CURRENT_PRE_ADAPTER_CHANGED_DURING_RUN'):
                    runner.run(date,trace=True,output_root=out)
            self.assertFalse((out/'provenance.json').exists())


if __name__=='__main__':unittest.main()
