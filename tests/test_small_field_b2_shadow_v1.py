import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import numpy as np

from review import small_field_b2_shadow_v1 as subject
from review.exp025_offset_pl_raw_history_v1 import _top3_from_utility


class B2ShadowTests(unittest.TestCase):
    def races(self):
        result = {}
        for rid, size in (('r1', 6), ('r2', 8), ('r3', 4)):
            utility = np.arange(size) / 10
            p, _ = _top3_from_utility(utility)
            result[rid] = [{'horse_number': i + 1, 'horse_name': str(i + 1),
                            'utility': float(utility[i]), 'p_top3': float(p[i])} for i in range(size)]
        return result

    def test_probability_caps_volume_and_determinism(self):
        races = self.races()
        selected = subject.calculate(races, 5)
        self.assertEqual(len(selected), 5)
        self.assertEqual(selected, subject.calculate(races, 5))
        self.assertLessEqual(sum(r['race_id'] == 'r1' for r in selected), 2)
        self.assertLessEqual(sum(r['race_id'] == 'r2' for r in selected), 3)
        self.assertFalse(any(r['race_id'] == 'r3' for r in selected))
        with self.assertRaisesRegex(subject.Stop, 'STOP_DAILY_CAPACITY'):
            subject.calculate(races, 6)

    def test_utility_not_adjusted_twice_and_drift_rejected(self):
        races = self.races()
        races['r1'][0]['p_top3'] += .01
        with self.assertRaisesRegex(subject.Stop, 'STOP_UTILITY_PROBABILITY_MISMATCH'):
            subject.calculate(races, 1)

    def test_pre_refuses_result_presence_without_opening_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / 'data/raw/target/daily_result_list'
            raw.mkdir(parents=True)
            (raw / '着順馬番_20261121.csv').write_bytes(b'marker')
            with patch.object(subject.parent, 'derive', side_effect=AssertionError('PRE input read')):
                with self.assertRaisesRegex(subject.Stop, 'STOP_RESULT_ALREADY_PRESENT'):
                    subject.freeze_pre('20261121', root=root)

    def make_post_fixture(self, root):
        date = '20261121'
        rid = 'race_20261121_tokyo_1R'
        folder = root / f'reports/small_field_b2_shadow_v1/daily_pre/{date}'
        folder.mkdir(parents=True)
        h = {'race_id': rid, 'horse_number': 3, 'horse_name': 'synthetic'}
        record = {'date': date, 'status': 'FROZEN_SHADOW_PRE', 'result_access_count': 0,
                  'evidence_credit': 0, 'b1_adoption_evidence_credit': 0,
                  'freeze_deadline': '2026-11-21T09:00:00+09:00', 'input_sources_sha256': {},
                  'race_field_sizes': {rid: 6}, 'lanes': {lane: {
                      'selected_horses': [h], 'parent_selected_horses': [h]} for lane in subject.PARENTS}}
        selection = folder / 'selection.json'
        selection.write_bytes(subject.parent.canonical(record))
        seal = {'date': date, 'selection_sha256': subject.parent.sha(selection),
                'freeze_timestamp_utc': '2026-11-20T00:00:00+00:00',
                'freeze_deadline': record['freeze_deadline'], 'result_access_count': 0,
                'evidence_credit': 0, 'b1_adoption_evidence_credit': 0}
        (folder / 'freeze_manifest.json').write_bytes(subject.parent.canonical(seal))
        row = [date, '東京', '1'] + [''] * 6 + ['6', '', ''] + ['1', '2', '3', '4', '中止', '取消']
        return folder, {('東京', 1): row}

    def test_isolated_post_third_is_loss_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder, results = self.make_post_fixture(root)
            before = (folder / 'selection.json').read_bytes()
            with patch('review.formal_post_daily_v1.result_sources', return_value=(results, {'synthetic': 'hash'})):
                result = subject.evaluate_post('20261121', root=root)
                with self.assertRaises(FileExistsError):
                    subject.evaluate_post('20261121', root=root)
            report = subject.parent.read(Path(result['path']))
            for m in report['metrics'].values():
                self.assertEqual(m['top3_hits'], 1)
                self.assertEqual(m['place_hits_confirmed'], 0)
                self.assertEqual(m['place_losses_confirmed'], 1)
            self.assertEqual(report['evidence_credit'], 0)
            self.assertEqual((folder / 'selection.json').read_bytes(), before)

    def test_bad_freeze_stops_before_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder, _ = self.make_post_fixture(root)
            (folder / 'selection.json').write_bytes(b'{}')
            with patch('review.formal_post_daily_v1.result_sources', side_effect=AssertionError('Result read')):
                with self.assertRaisesRegex(subject.Stop, 'STOP_PRE_AUTHORITY'):
                    subject.evaluate_post('20261121', root=root)

    def test_ambiguous_and_documented_sale_terms(self):
        self.assertEqual(subject.rules.ticket('3', 7, 8), 'UNKNOWN_SALE_OR_PLACE_TERMS')
        self.assertEqual(subject.rules.ticket('3', 6, 6), 'LOSS')
        for token in ('取消', '除外'):
            self.assertEqual(subject.rules.ticket(token, 6, 7), 'REFUND')
        for token in ('中止', '失格'):
            self.assertEqual(subject.rules.ticket(token, 7, 7), 'LOSS')


if __name__ == '__main__':
    unittest.main()
