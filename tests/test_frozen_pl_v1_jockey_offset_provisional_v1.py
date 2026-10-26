"""Result-blind technical tests for the provisional review-layer candidate."""
import unittest
import copy
from pathlib import Path
from unittest.mock import patch

import numpy as np

from review import exp025_offset_pl_raw_history_v1 as identity
from review import frozen_pl_v1_jockey_offset_provisional_v1 as subject
from review import post_ws2_jockey_mechanism_research_v1_model as jockey


DATE = '20261025'
RACE = 'race_20261025_tokyo_7R'


def fixture(k=2):
    numbers = [1, 2, 3, 4]
    field = [{'horse_number': n, 'horse_name': f'H{n}'} for n in numbers]
    payload = {'race_id': RACE, 'ranked_results': field, 'buys': field[:k], 'buy_count': k}
    vectors = []
    for n in numbers:
        v = np.zeros(21)
        v[0] = n / 5
        vectors.append({'date': DATE, 'race_id': RACE, 'horse_number': n, 'horse_name': f'H{n}', 'vector': v})
    mean = [0.0] * 21
    scale = [1.0] * 21
    coef = [1.0] + [0.0] * 18
    model = {'scaler': {'mean': mean, 'scale': scale}, 'pl_coefficients': coef}
    base, _ = identity._top3_from_utility(np.array([r['vector'][0] for r in vectors]))
    pl = [{'horse_number': n, 'pl_top3_probability': float(base[i])} for i, n in enumerate(numbers)]
    features = {(DATE, RACE, n): {jockey.FEATURE: 0.0} for n in numbers}
    return payload, vectors, pl, features, model


class ProvisionalTests(unittest.TestCase):
    @staticmethod
    def formal_fixture():
        value = copy.deepcopy(subject.load(subject.FORMAL_SNAPSHOT_MANIFEST))
        value['entries'].append({
            'date': '20261031',
            'current_pre_path': 'reports/prospective_prediction_20261031_v1/prediction_manifest.json',
            'current_pre_sha256': 'a' * 64,
            'ds_snapshot_path': 'data/raw/prediction_input/DS261031.CSV',
            'ds_snapshot_sha256': 'b' * 64,
            'input_manifest_path': 'reports/prospective_prediction_20261031_v1/input_manifest.json',
            'input_manifest_sha256': 'c' * 64,
            'freeze_timestamp': '2026-10-31T08:00:00+09:00',
            'previous_entries_sha256': subject.FORMAL_GENESIS_ENTRIES_SHA,
            'status': 'FROZEN_PRE_SOURCE',
        })
        hashes = {}
        inputs = {}
        for row in value['entries']:
            for key in ('current_pre', 'ds_snapshot', 'input_manifest'):
                hashes[str(subject.ROOT / row[key + '_path'])] = row[key + '_sha256']
            inputs[str(subject.ROOT / row['input_manifest_path'])] = {
                'sources': {'DS': {'path': row['ds_snapshot_path'], 'sha256': row['ds_snapshot_sha256']}}
            }
        return value, hashes, inputs

    def test_exact_beta_and_model(self):
        _, beta = subject.verify_identity()
        self.assertEqual(beta, 1.1118321180295676)

    def test_model_identity_failure(self):
        with patch.object(subject, 'MODEL_SHA', '0' * 64), self.assertRaises(subject.Stop):
            subject.verify_identity()

    def test_beta_source_identity_failure(self):
        with patch.object(subject, 'BETA_SHA', '0' * 64), self.assertRaises(subject.Stop):
            subject.verify_identity()

    def test_same_race_same_k(self):
        p, records, pl, features, model = fixture(2)
        with patch.object(subject.forward, '_payload_records', return_value=records):
            row = subject.selection_for_race(p, pl, features, model, subject.BETA)
        self.assertEqual(row['candidate_k'], row['current_k'])
        self.assertEqual(len(row['candidate_selected_horses']), 2)
        self.assertFalse(row['provisional_fallback_race'])

    def test_deterministic(self):
        p, records, pl, features, model = fixture(2)
        with patch.object(subject.forward, '_payload_records', return_value=records):
            a = subject.selection_for_race(p, pl, features, model, subject.BETA)
            b = subject.selection_for_race(p, pl, features, model, subject.BETA)
        self.assertEqual(subject.canonical(a), subject.canonical(b))

    def test_pit_excludes_future_history(self):
        target = {'date': DATE, 'current_jockey_normalized': 'J', 'horse_identity': ('A', 'S', 'M')}
        future = {'snapshot_date': '20261026', 'historical_race_date': '20261024',
                  'historical_jockey_normalized': 'J', 'horse_identity': ('B', 'S', 'M'),
                  'historical_race_id': 'race_20261024_tokyo_7R', 'field_size': 10,
                  'finish': 1, 'completed_valid': True}
        self.assertEqual(jockey.jockey_top3_lift(target, [future])['prior_ride_count'], 0)
        past = dict(future, snapshot_date=DATE, historical_race_date=DATE)
        self.assertEqual(jockey.jockey_top3_lift(target, [past])['prior_ride_count'], 0)

    def test_missing_snapshot_stops(self):
        with self.assertRaises(subject.Stop):
            subject.snapshot_manifest(DATE, Path('missing/DS261025.CSV'))

    def test_cold_start_is_zero(self):
        target = {'date': DATE, 'current_jockey_normalized': 'J', 'horse_identity': ('A', 'S', 'M')}
        self.assertEqual(jockey.jockey_top3_lift(target, [])[jockey.FEATURE], 0.0)

    def test_uncovered_horse_level_falls_back_to_current(self):
        p, records, pl, features, model = fixture(2)
        del features[(DATE, RACE, 4)]
        with patch.object(subject.forward, '_payload_records', return_value=records):
            row = subject.selection_for_race(p, pl, features, model, subject.BETA)
        self.assertTrue(row['provisional_fallback_race'])
        self.assertEqual(row['candidate_selected_horses'], row['current_selected_horses'])

    def test_result_independent_selection(self):
        p, records, pl, features, model = fixture(2)
        with patch.object(subject.forward, '_payload_records', return_value=records):
            row = subject.selection_for_race(p, pl, features, model, subject.BETA)
        self.assertNotIn('actual_top3', str(row))
        self.assertNotIn('valid_result', str(row))

    def test_no_four_plus_leak(self):
        p, records, pl, features, model = fixture(4)
        with self.assertRaises(subject.Stop):
            subject.selection_for_race(p, pl, features, model, subject.BETA)

    def test_no_e1_or_rank1_interaction(self):
        text = Path(subject.__file__).read_text(encoding='utf-8')
        self.assertNotIn('from review import pl_all_race_allocation', text)
        self.assertNotIn('from review import current_unconverged_rank1', text)

    def test_pre_first_race_time_guard(self):
        selection = {'date': DATE, 'result_access_count': 0, 'semantic_validation_result': 'PASS',
                     'current_pre_sha256': 'a', 'pl_prediction_sha256': 'b',
                     'jockey_snapshot_manifest_sha256': 'c', 'eligible_race_count': 1,
                     'candidate_selected_horse_count': 1, 'current_selected_horse_count': 1,
                     'fallback_race_count': 0, 'fallback_race_ids': []}
        with patch.object(subject, 'load', return_value={'date': DATE, 'first_start_at': '2026-10-25T10:00:00+09:00'}):
            with self.assertRaises(subject.Stop):
                subject.audit_for_freeze(selection, freeze_timestamp='2026-10-25T10:00:00+09:00',
                                         first_race_timestamp='2026-10-25T10:00:00+09:00',
                                         first_race_authority_path=subject.BETA_PATH)

    def test_provisional_rollback_and_jockey_warning(self):
        early = subject.provisional_status_from_paired_counts(prospective_dates=4, eligible_comparison_races=40,
                   candidate_minus_current_hits=-9, candidate_minus_exp024_hits=-9)
        self.assertFalse(early['rollback_eligible'])
        mature = subject.provisional_status_from_paired_counts(prospective_dates=5, eligible_comparison_races=25,
                   candidate_minus_current_hits=-5, candidate_minus_exp024_hits=-5)
        self.assertEqual(mature['operational_first_choice'], 'CURRENT')
        self.assertTrue(mature['jockey_harm_warning'])
        self.assertFalse(mature['beta_retuned'])

    def test_smoke_20261025_includes_20261024(self):
        root = Path('reports/20261025_pre_v1')
        selection = subject.build_pre(root / 'current_frozen', root / 'pl_forward_prediction.json',
                                      root / 'filtered_source/DE261025.CSV', root / 'filtered_source/DS261025.CSV')
        self.assertEqual(selection['date'], DATE)
        self.assertEqual(selection['fallback_race_count'], 0)
        self.assertEqual(selection['candidate_selected_horse_count'], selection['current_selected_horse_count'])
        self.assertIn('20261024', {x['snapshot_date'] for x in selection['jockey_snapshot_manifest']})
        self.assertEqual(selection['result_access_count'], 0)

    def test_20261101_missing_expected_1031_stops(self):
        value = subject.load(subject.FORMAL_SNAPSHOT_MANIFEST)
        with self.assertRaisesRegex(subject.Stop, 'STOP_EXPECTED_FORMAL_PRE_SNAPSHOT_MISSING:20261031'):
            subject.validate_formal_manifest('20261101', require_target_entry=False, value=value)

    def test_20261101_complete_1031_structural_pass(self):
        value, hashes, inputs = self.formal_fixture()
        with (patch.object(Path, 'is_file', return_value=True),
              patch.object(subject, 'sha', side_effect=lambda path: hashes[str(path)]),
              patch.object(subject, 'load', side_effect=lambda path: inputs[str(path)])):
            rows = subject.validate_formal_manifest('20261101', require_target_entry=False, value=value)
        self.assertEqual([row['date'] for row in rows], ['20261024', '20261025', '20261031'])

    def test_formal_snapshot_sha_mismatch_stops(self):
        value, hashes, inputs = self.formal_fixture()
        hashes[str(subject.ROOT / value['entries'][-1]['ds_snapshot_path'])] = '0' * 64
        with (patch.object(Path, 'is_file', return_value=True),
              patch.object(subject, 'sha', side_effect=lambda path: hashes[str(path)]),
              patch.object(subject, 'load', side_effect=lambda path: inputs[str(path)]),
              self.assertRaisesRegex(subject.Stop, 'STOP_FORMAL_SNAPSHOT_SHA')):
            subject.validate_formal_manifest('20261101', require_target_entry=False, value=value)

    def test_duplicate_formal_date_stops(self):
        value, _, _ = self.formal_fixture()
        value['entries'].append(copy.deepcopy(value['entries'][-1]))
        with self.assertRaisesRegex(subject.Stop, 'STOP_FORMAL_SNAPSHOT_DUPLICATE_OR_ORDER'):
            subject.validate_formal_manifest('20261101', require_target_entry=False, value=value)

    def test_future_snapshot_excluded(self):
        value, hashes, inputs = self.formal_fixture()
        with (patch.object(Path, 'is_file', return_value=True),
              patch.object(subject, 'sha', side_effect=lambda path: hashes[str(path)]),
              patch.object(subject, 'load', side_effect=lambda path: inputs[str(path)])):
            rows = subject.validate_formal_manifest('20261025', value=value)
        self.assertEqual([row['date'] for row in rows], ['20261024', '20261025'])

    def test_runtime_dependency_sha_mismatch_stops(self):
        with patch.object(subject, 'RUNTIME_DEPENDENCIES',
                          {'review/adaptive_pl_jockey_research_v1.py': '0' * 64}), self.assertRaisesRegex(subject.Stop, 'STOP_RUNTIME_DEPENDENCY_SHA'):
            subject.verify_identity()

    def test_formal_manifest_order_is_deterministic(self):
        value, _, _ = self.formal_fixture()
        value['entries'][1], value['entries'][2] = value['entries'][2], value['entries'][1]
        with self.assertRaises(subject.Stop):
            subject.validate_formal_manifest('20261101', require_target_entry=False, value=value)


if __name__ == '__main__':
    unittest.main()
