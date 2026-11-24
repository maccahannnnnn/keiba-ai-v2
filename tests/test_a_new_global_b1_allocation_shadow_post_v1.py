import csv
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from review import a_new_global_b1_allocation_shadow_post_v1 as subject
from review import a_new_global_b1_allocation_shadow_v1 as pre
from tests import test_a_new_global_b1_allocation_shadow_v1 as fixture
from tests.test_a_new_global_b1_allocation_shadow_v1 import DATE, TIME, put


class PostTests(unittest.TestCase):
    def setUp(self):
        fixture.ShadowTests.setUp(self)
        self.e1_root = self.root / 'isolated_e1'
        self.ep = self.e1_root / f'reports/e1_full_field_allocation_prospective_shadow_v1/daily_pre/{DATE}'
        manifest_sha = pre.sha(self.current / 'prediction_manifest.json')
        selected = [{'race_id': f'race_{DATE}_tokyo_{i}R', 'horse_number': 1,
                     'horse_name': f'馬{i}_1'} for i in (1, 2)]
        esha = put(self.ep / 'selection.json', {'date': DATE, 'selected_horses': selected})
        efsha = put(self.ep / 'freeze_manifest.json', {'date': DATE, 'selection_sha256': esha,
                    'result_access_count': 0, 'e1_freeze_timestamp': TIME.isoformat()})
        bp = self.root / f'reports/formal_pre_daily/{DATE}/b1_diagnostic'
        bsha = put(bp / 'selection.json', {'date': DATE, 'selected_horses': selected,
                   'current_prediction_sha256': manifest_sha, 'e1_selection_sha256': esha,
                   'e1_freeze_sha256': efsha})
        put(bp / 'freeze_manifest.json', {'date': DATE, 'selection_sha256': bsha,
                   'result_access_count': 0, 'freeze_timestamp_utc': TIME.isoformat()})
        # Add canonical Current BUY identity and renew its synthetic manifest.
        for i in (1, 2):
            p = self.current / f'race_{DATE}_tokyo_{i}R_prediction.json'
            payload = pre.read(p)
            payload['buys'] = [selected[i - 1]]
            put(p, payload)
        m = pre.read(self.current / 'prediction_manifest.json')
        for row in m['files']:
            row['sha256'] = pre.sha(self.current / row['relative_path'])
        put(self.current / 'prediction_manifest.json', m)
        manifest_sha = pre.sha(self.current / 'prediction_manifest.json')
        cs = pre.read(self.current / 'formal_freeze_attestation.json')
        cs['prediction_manifest_sha256'] = manifest_sha
        put(self.current / 'formal_freeze_attestation.json', cs)
        a = pre.read(self.a_dir / 'selection.json')
        a['current_pre_sha256'] = manifest_sha
        put(self.a_dir / 'selection.json', a)
        af = pre.read(self.a_dir / 'freeze_manifest.json')
        af['selection_sha256'] = pre.sha(self.a_dir / 'selection.json')
        put(self.a_dir / 'freeze_manifest.json', af)
        bs = pre.read(bp / 'selection.json')
        bs['current_prediction_sha256'] = manifest_sha
        put(bp / 'selection.json', bs)
        bf = pre.read(bp / 'freeze_manifest.json')
        bf['selection_sha256'] = pre.sha(bp / 'selection.json')
        put(bp / 'freeze_manifest.json', bf)
        pre.freeze_pre(DATE, root=self.root, a_root=self.anew_root, now=TIME)
        self.raw = self.root / 'data/raw/target/daily_result_list'
        self.raw.mkdir(parents=True)
        for prefix in ('馬番順着順', '着順馬番'):
            with (self.raw / f'{prefix}_{DATE}.csv').open('w', encoding='cp932', newline='') as stream:
                writer = csv.writer(stream)
                for race, finish in ((1, '3'), (2, '中止')):
                    writer.writerow([DATE, '東京', str(race)] + [''] * 9 + [finish, '4', '1'])

    def evaluate(self):
        with patch.object(subject, 'validate_source_pair', return_value={'status': 'PASS'}):
            return subject.evaluate_post(DATE, root=self.root, e1_root=self.e1_root, a_root=self.anew_root)

    def test_metrics_comparison_invalid_and_reproducibility(self):
        result = self.evaluate()
        report = pre.read(Path(result['path']))
        for metric in report['metrics'].values():
            self.assertEqual(metric['selected'], 2)
            self.assertEqual(metric['valid'], 1)
            self.assertEqual(metric['invalid'], 1)
            self.assertEqual(metric['top3_hits'], 1)
            self.assertEqual(metric['top3_rate'], 1.0)
        path = Path(result['path'])
        original = path.read_bytes()
        # Separate fresh synthetic fixture produces byte-identical deterministic report
        # for identical source paths and bytes; recompute without changing PRE.
        path.unlink()
        path.parent.rmdir()
        self.assertEqual(self.evaluate()['sha256'], result['sha256'])
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(FileExistsError):
            self.evaluate()

    def test_bad_pre_stops_before_result_validation(self):
        path = self.root / f'reports/a_new_global_b1_allocation_shadow_v1/daily_pre/{DATE}/selection.json'
        payload = pre.read(path)
        payload['selected_count'] = 999
        put(path, payload)
        with patch.object(subject, 'validate_source_pair', side_effect=AssertionError('Result accessed')):
            with self.assertRaisesRegex(pre.Stop, 'STOP_PRE_SELECTION_SHA_OR_DATE'):
                subject.evaluate_post(DATE, root=self.root, e1_root=self.e1_root, a_root=self.anew_root)

    def test_failure_outcome_uses_baseline(self):
        row = [''] * 16
        for token, expected in [('1', (True, 1, True)), ('2', (True, 2, True)),
                                ('3', (True, 3, True)), ('4', (True, 4, False)),
                                ('中止', (False, None, None)), ('取消', (False, None, None)),
                                ('除外', (False, None, None)), ('失格', (False, None, None))]:
            row[12] = token
            self.assertEqual(subject.outcome(row, 1), expected)

    def test_invalid_dates_stop_before_any_file_read(self):
        for date in ('2026112', '202611210', '../1121', '２０２６１１２１', '20260229', '20261301', None):
            with self.subTest(date=date), patch.object(pre, 'sha', side_effect=AssertionError('file read')):
                with self.assertRaisesRegex(pre.Stop, 'STOP_POST_DATE'):
                    subject.evaluate_post(date, root=self.root)

    def test_judgment_sha_mismatch_stops_before_pre_or_result(self):
        original = pre.sha
        for module in (subject.b1, subject.readiness):
            def digest(path):
                return '0' * 64 if Path(path) == Path(module.__file__) else original(path)
            with self.subTest(module=module.__name__), patch.object(pre, 'sha', side_effect=digest), \
                    patch.object(pre, 'read', side_effect=AssertionError('PRE read')), \
                    patch.object(subject, 'validate_source_pair', side_effect=AssertionError('Result read')):
                with self.assertRaisesRegex(pre.Stop, 'STOP_POST_JUDGMENT_CODE_SHA'):
                    subject.evaluate_post(DATE, root=self.root)

    def test_distinct_lane_selections_and_metrics(self):
        def horses(numbers):
            return [{'race_id': f'race_{DATE}_tokyo_{i}R', 'horse_number': n,
                     'horse_name': f'馬{i}_{n}'} for i, n in enumerate(numbers, 1)]
        def replace_selection(folder, numbers):
            payload = pre.read(folder / 'selection.json')
            payload['selected_horses'] = horses(numbers)
            put(folder / 'selection.json', payload)
            seal = pre.read(folder / 'freeze_manifest.json')
            seal['selection_sha256'] = pre.sha(folder / 'selection.json')
            put(folder / 'freeze_manifest.json', seal)
        replace_selection(self.ep, (1, 3))
        bp = self.root / f'reports/formal_pre_daily/{DATE}/b1_diagnostic'
        replace_selection(bp, (3, 3))
        bs = pre.read(bp / 'selection.json')
        bs['e1_selection_sha256'] = pre.sha(self.ep / 'selection.json')
        bs['e1_freeze_sha256'] = pre.sha(self.ep / 'freeze_manifest.json')
        put(bp / 'selection.json', bs)
        bf = pre.read(bp / 'freeze_manifest.json')
        bf['selection_sha256'] = pre.sha(bp / 'selection.json')
        put(bp / 'freeze_manifest.json', bf)
        shadow_dir = self.root / f'reports/a_new_global_b1_allocation_shadow_v1/daily_pre/{DATE}'
        replace_selection(shadow_dir, (2, 2))
        report = pre.read(Path(self.evaluate()['path']))
        expected = {'CURRENT': ((1, 1), 1, 1, 1), 'B1': ((3, 3), 2, 0, 2),
                    'E1': ((1, 3), 2, 0, 2), pre.LANE: ((2, 2), 2, 0, 0)}
        for lane, (numbers, valid, invalid, hits) in expected.items():
            rows = report['selected_horse_outcomes'][lane]
            self.assertEqual(tuple(r['horse_number'] for r in rows), numbers)
            self.assertTrue(all(r['lane'] == lane for r in rows))
            metric = report['metrics'][lane]
            self.assertEqual((metric['valid'], metric['invalid'], metric['top3_hits']), (valid, invalid, hits))
            self.assertEqual(metric['top3_rate'], hits / valid)
        self.assertEqual(report['post_evaluator_sha256'], pre.sha(Path(subject.__file__)))


if __name__ == '__main__':
    unittest.main()
