import unittest
from review import small_field_place_h1_diagnostic_v2 as subject
from tests import test_small_field_place_h1_diagnostic_v1 as fixture


class V2Tests(unittest.TestCase):
    def test_pre_roster_makes_third_a_loss(self):
        for pre, starters in ((6, 6), (7, 7), (7, 5), (6, 5)):
            self.assertEqual(subject.ticket('3', starters, pre), 'LOSS')
            self.assertEqual(subject.ticket('2', starters, pre), 'HIT')

    def test_ambiguous_crossing_and_large_field(self):
        self.assertEqual(subject.ticket('3', 7, 8), 'UNKNOWN_SALE_OR_PLACE_TERMS')
        self.assertEqual(subject.ticket('3', 8, 9), 'HIT')
        self.assertEqual(subject.ticket('4', 7, 8), 'LOSS')
        self.assertEqual(subject.ticket('1', 4, 7), 'UNKNOWN_SALE_OR_PLACE_TERMS')
        with self.assertRaisesRegex(ValueError, 'STOP_FIELD_COUNTS'):
            subject.ticket('3', 8, 7)

    def test_abnormal_semantics_unchanged(self):
        for token in ('取消', '除外'):
            self.assertEqual(subject.ticket(token, 6, 7), 'REFUND')
        for token in ('中止', '失格'):
            self.assertEqual(subject.ticket(token, 7, 7), 'LOSS')

    def test_b3_four_or_less_excluded_and_other_selection_unchanged(self):
        races = fixture.SmallFieldTests().races()
        for mode in ('B-3', 'B-2', 'C-2'):
            self.assertEqual(subject.cap(mode, 4), 0)
            selected = subject.allocate(races, 4, mode)
            self.assertEqual(len(selected), 4)
            self.assertTrue(all(r['pre_field_size'] >= 5 for r in selected))
        self.assertEqual(subject.allocate(races, 4, 'A'), subject.v1.allocate(races, 4, 'A'))

    def test_paired_refund_denominator_and_swap_hits(self):
        def row(n, status):
            return {'race_id': 'r', 'horse_number': n, 'ticket_status': status,
                    'valid_result': status == 'HIT', 'actual_top3': status == 'HIT'}
        old = [row(1, 'HIT'), row(2, 'REFUND')]
        new = [row(1, 'HIT'), row(3, 'LOSS')]
        p = subject.paired(old, new)
        self.assertEqual(p['common_selected'], 1)
        self.assertEqual(p['refund_difference'], -1)
        self.assertEqual(p['nonrefund_denominator_difference'], 1)
        self.assertEqual(p['place_hit_difference'], 0)
        self.assertEqual(p['place_rate_difference'], -.5)
        self.assertEqual(p['removed_metric']['refunds'], 1)
        self.assertEqual(p['added_metric']['place_losses_confirmed'], 1)


if __name__ == '__main__':
    unittest.main()
