import unittest
import numpy as np
from review import small_field_place_h1_diagnostic_v1 as subject
from review import b1_prospective_diagnostic_v1 as b1


class SmallFieldTests(unittest.TestCase):
    def races(self):
        return {rid: [{'race_id': rid, 'horse_number': i + 1, 'horse_name': str(i + 1),
                       'utility': 0.0, 'p_top3': 3 / size} for i in range(size)]
                for rid, size in [('race_a', 6), ('race_b', 8), ('race_c', 4)]}

    def test_exact_top2_uniform_mass_and_shift(self):
        p = subject.top2(np.zeros(6))
        np.testing.assert_allclose(p, np.full(6, 2 / 6), atol=1e-15)
        np.testing.assert_allclose(subject.top2(np.arange(6)), subject.top2(np.arange(6) + 10), atol=1e-15)
        self.assertAlmostEqual(subject.top2([0., 0.]).sum(), 2)

    def test_caps_and_same_daily_volume(self):
        races = self.races()
        for mode in subject.MODES:
            selected = subject.allocate(races, 4, mode)
            self.assertEqual(len(selected), 4)
            for rid, size in [('race_a', 6), ('race_b', 8), ('race_c', 4)]:
                self.assertLessEqual(sum(r['race_id'] == rid for r in selected), subject.cap(mode, size))
            self.assertEqual(selected, subject.allocate(races, 4, mode))
        self.assertEqual(subject.cap('B-2', 8), 3)
        self.assertEqual(subject.cap('C-2', 8), 2)
        with self.assertRaisesRegex(ValueError, 'STOP_DAILY_CAPACITY'):
            subject.allocate(races, 99, 'C-2')

    def test_A_matches_existing_B1_ties(self):
        races = self.races()
        packed = [{'race_id': rid, 'current_k': 2 if rid == 'race_a' else 1,
                   'horses': [dict(r, candidate_p_top3=r['p_top3']) for r in rows]}
                  for rid, rows in races.items()]
        expected = b1.select_b1(packed, 4)
        self.assertEqual([subject.key(h) for h in expected],
                         [subject.key(h) for h in subject.allocate(races, 4, 'A')])

    def test_ticket_rules_preserve_unknown_and_refunds(self):
        self.assertEqual(subject.ticket('取消', 7), 'REFUND')
        self.assertEqual(subject.ticket('除外', 7), 'REFUND')
        self.assertEqual(subject.ticket('中止', 7), 'LOSS')
        self.assertEqual(subject.ticket('失格', 7), 'LOSS')
        self.assertEqual(subject.ticket('3', 8), 'HIT')
        self.assertEqual(subject.ticket('3', 7), 'UNKNOWN_SALE_OR_PLACE_TERMS')
        self.assertEqual(subject.ticket('2', 7), 'HIT')
        self.assertEqual(subject.ticket('4', 7), 'LOSS')
        self.assertEqual(subject.ticket('2', 4), 'UNKNOWN_SALE_OR_PLACE_TERMS')

    def test_baseline_exclusion_and_ticket_failure_are_separate(self):
        rows = [{'valid_result': True, 'actual_top3': True, 'ticket_status': 'HIT'},
                {'valid_result': False, 'actual_top3': None, 'ticket_status': 'LOSS'},
                {'valid_result': False, 'actual_top3': None, 'ticket_status': 'REFUND'},
                {'valid_result': True, 'actual_top3': True, 'ticket_status': 'UNKNOWN_SALE_OR_PLACE_TERMS'}]
        m = subject.metric(rows)
        self.assertEqual((m['valid'], m['top3_hits']), (2, 2))
        self.assertEqual(m['place_known_rate'], .5)
        self.assertIsNone(m['place_rate_all_nonrefund_exact'])
        self.assertEqual(m['place_rate_lower'], 1 / 3)
        self.assertEqual(m['place_rate_upper'], 2 / 3)


if __name__ == '__main__':
    unittest.main()
