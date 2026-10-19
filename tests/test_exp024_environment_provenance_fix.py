import json
import unittest
from pathlib import Path
from unittest.mock import patch

from review import pl_same_volume_reselection_shadow_v1 as s

CURRENT=s.ROOT/'reports/daily_pre_analysis_20261017/current_frozen'


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        # These immutable historical fixtures predate the runner's provenance extension.
        # Simulate their original runner identity without modifying either artifact.
        real_sha=s.sha
        old_runner=json.loads((CURRENT/'provenance.json').read_text(encoding='utf8'))['runner_sha256']
        runner=s.ROOT/'review/prospective_prediction_runner_v1.py'
        patcher=patch.object(s,'sha',side_effect=lambda path: old_runner if path==runner else real_sha(path))
        patcher.start();self.addCleanup(patcher.stop)
        real_read=Path.read_text
        def read_fixture(path, *args, **kwargs):
            content=real_read(path,*args,**kwargs)
            if path==CURRENT/'provenance.json':
                value=json.loads(content)
                value['target_bulk_prediction_input_adapter_sha256']=real_sha(s.ROOT/'review/target_bulk_prediction_input_adapter_v1.py')
                return json.dumps(value)
            return content
        self.read_patcher=patch.object(Path,'read_text',read_fixture)
        self.read_patcher.start();self.addCleanup(self.read_patcher.stop)

    def _changed_file_is_rejected(self, relative, field):
        target=s.ROOT/relative; real_sha=s.sha
        def fake_sha(path):
            return '0'*64 if path==target else real_sha(path)
        with patch.object(s,'sha',side_effect=fake_sha):
            with self.assertRaisesRegex(s.Stop,'ENVIRONMENT_PROVENANCE_MISMATCH:'+field):
                s.verify_current_provenance(CURRENT,'20261017',require_tree_attestation=False)

    def test_shadow_buy_engine_mismatch(self):
        self._changed_file_is_rejected('engine/shadow_buy_decision_engine.py','shadow_buy_engine_sha256')

    def test_runner_mismatch(self):
        self._changed_file_is_rejected('review/prospective_prediction_runner_v1.py','runner_sha256')

    def test_run_new_mismatch(self):
        self._changed_file_is_rejected('review/target_bulk_prediction_input_shadow_v1.py','run_new_module_sha256')

    def test_trace_schema_mismatch(self):
        self._changed_file_is_rejected('docs/buy_gate_trace_schema_v1_1.json','buy_gate_trace_schema_sha256')

    def test_adapter_mismatch(self):
        self._changed_file_is_rejected('review/target_bulk_prediction_input_adapter_v1.py','target_bulk_prediction_input_adapter_sha256')

    def test_verified_adapter_change_splits_fingerprint(self):
        previous=s.verify_current_provenance(CURRENT,'20261017',require_tree_attestation=False)
        target=s.ROOT/'review/target_bulk_prediction_input_adapter_v1.py'
        current_sha=s.sha;current_read=Path.read_text
        def updated_sha(path):return 'a'*64 if path==target else current_sha(path)
        def updated_read(path,*args,**kwargs):
            value=current_read(path,*args,**kwargs)
            if path==CURRENT/'provenance.json':
                data=json.loads(value);data['target_bulk_prediction_input_adapter_sha256']='a'*64
                return json.dumps(data)
            return value
        # Synthetic PRE authority and working-file hash change together; no PRE is edited.
        with patch.object(s,'sha',side_effect=updated_sha),patch.object(Path,'read_text',updated_read):
            changed=s.verify_current_provenance(CURRENT,'20261017',require_tree_attestation=False)
        self.assertNotEqual(previous['current_environment_fingerprint'],changed['current_environment_fingerprint'])
        self.assertTrue(s.environment_block(changed,previous['current_environment_fingerprint'])['change_detected'])

    def test_historical_adapter_missing_fails_closed(self):
        self.read_patcher.stop()
        with self.assertRaisesRegex(s.Stop,'STOP_CURRENT_PRE_ADAPTER_PROVENANCE_MISSING'):
            s.verify_current_provenance(CURRENT,'20261017')

    def _tree(self, directory, files, contents):
        root=Path(directory)
        with patch.object(Path,'is_dir',return_value=True),patch.object(Path,'rglob',return_value=[root/p for p in files]),patch.object(Path,'is_file',return_value=True),patch.object(Path,'is_symlink',return_value=False),patch.object(s,'sha',side_effect=lambda p:contents[p.name]):
            return s.tree_hash(root)

    def test_each_semantic_tree_file_changes_digest(self):
        for tree in ('engine','evaluation','knowledge'):
            with self.subTest(tree=tree):
                a=self._tree(tree,['rule.py'],{'rule.py':'1'*64})
                b=self._tree(tree,['rule.py'],{'rule.py':'2'*64})
                self.assertNotEqual(a,b)

    def test_pycache_and_generated_excluded(self):
        root='engine'
        a=self._tree(root,['rule.py'],{'rule.py':'1'*64})
        b=self._tree(root,['rule.py','__pycache__/rule.pyc','runtime.out','temp/scratch.json'],{'rule.py':'1'*64,'rule.pyc':'2'*64,'runtime.out':'3'*64,'scratch.json':'4'*64})
        self.assertEqual(a,b)

    def test_tree_order_is_deterministic(self):
        contents={'a.py':'1'*64,'b.json':'2'*64}
        self.assertEqual(self._tree('engine',['a.py','b.json'],contents),self._tree('engine',['b.json','a.py'],contents))

    def test_individual_provenance_deterministic_but_legacy_trees_unverified(self):
        a=s.verify_current_provenance(CURRENT,'20261017',require_tree_attestation=False)
        b=s.verify_current_provenance(CURRENT,'20261017',require_tree_attestation=False)
        self.assertEqual(a,b);self.assertEqual(a['tree_provenance_status'],'UNVERIFIED_MISSING_PRE_TREE_ATTESTATION')
        self.assertEqual(set(a['missing_tree_provenance_fields']),{'engine_tree_sha256','evaluation_tree_sha256','knowledge_tree_sha256'})

    def test_missing_tree_authority_stops_before_inference(self):
        with patch.object(s.pl,'infer_payloads',side_effect=AssertionError('must not infer')):
            with self.assertRaisesRegex(s.Stop,'STOP_CURRENT_PRE_TREE_PROVENANCE_MISSING'):
                s.build_pre(CURRENT,s.ROOT/'knowledge')

    def test_working_file_mismatch_rejects_evidence_freeze(self):
        authorization=Path('synthetic_authorization.json')
        output=Path('synthetic_never_written_output')
        selection={'date':'20261017','current_pre_root':str(CURRENT),
                   'current_prediction_sha256':'f'*64,
                   'current_environment':{'tree_provenance_status':'VERIFIED'},
                   'current_environment_fingerprint':'a'*64}
        approval={'protocol_sha256':s.PROTOCOL_SHA,'implementation_sha256':'i'*64,
                  'claude_implementation_review':'PASS','human_final_implementation_approval':True}
        def fake_sha(path):
            if path==authorization:return 'b'*64
            if path==Path(s.__file__):return 'i'*64
            if path==CURRENT/'prediction_manifest.json':return 'f'*64
            raise AssertionError('unexpected read')
        with patch.object(s,'verify_authority'),patch.object(s,'sha',side_effect=fake_sha),\
             patch.object(Path,'exists',return_value=False),\
             patch.object(Path,'read_text',return_value=json.dumps(approval)),\
             patch.object(s,'verify_current_provenance',side_effect=s.Stop('ENVIRONMENT_PROVENANCE_MISMATCH:runner_sha256')),\
             patch.object(Path,'mkdir',side_effect=AssertionError('must not write')):
            with self.assertRaisesRegex(s.Stop,'ENVIRONMENT_PROVENANCE_MISMATCH:runner_sha256'):
                s.freeze_pre(selection,output,first_start_evidence=Path('unused'),first_start_evidence_sha='c'*64,
                             authorization=authorization,authorization_sha='b'*64)

    def test_fingerprint_change_creates_block_and_stops_pool(self):
        a='a'*64;b='b'*64
        block=s.environment_block({'current_environment_fingerprint':b},a)
        self.assertTrue(block['change_detected']);self.assertEqual(block['block_id'],'BLOCK_'+b)
        with self.assertRaisesRegex(s.Stop,'CROSS_BLOCK_POOLING'):
            s.summarize_block([{'date':'20261017','block_fingerprint_sha256':a},{'date':'20261018','block_fingerprint_sha256':b}])

    def test_production_and_current_inputs_unchanged(self):
        files=[s.DECISION,s.ENTRY,s.ROOT/'engine/shadow_buy_decision_engine.py',CURRENT/'prediction_manifest.json']
        before=[s.sha(p) for p in files]
        try:s.verify_current_provenance(CURRENT,'20261017')
        except s.Stop:pass
        self.assertEqual(before,[s.sha(p) for p in files])

if __name__=='__main__':unittest.main()
