import unittest

from review.pl_jockey_decision_addendum_v1 import (
    date_bootstrap, decision, field_size_diagnostic, global_allocation,
    ordinary_rate, overlap_class, require_paired_identity, require_post_source,
    rule_a_hits, smallest_field_first,
)


def day(i, delta=2, races=5, slots=15, valid_hits=9):
    return dict(date=f"2026-11-{i:02d}", same_race=True, same_k=True,
                same_volume=True, plj_slots=slots, current_slots=slots,
                eligible_races=races, delta_hits=delta,
                plj_valid_n=slots, plj_valid_hits=valid_hits)


class AddendumTests(unittest.TestCase):
    def test_same_race(self):
        x = day(1); x["same_race"] = False
        with self.assertRaises(ValueError): require_paired_identity([x])

    def test_same_k(self):
        x = day(1); x["same_k"] = False
        with self.assertRaises(ValueError): require_paired_identity([x])

    def test_same_volume(self):
        x = day(1); x["current_slots"] = 14
        with self.assertRaises(ValueError): require_paired_identity([x])

    def test_invalid_separation(self):
        rows = [dict(valid_result=True, actual_top3=True),
                dict(valid_result=False, actual_top3=True)]
        self.assertEqual(ordinary_rate(rows)["valid"], 1)
        self.assertEqual(rule_a_hits(rows), 1)
        self.assertEqual(ordinary_rate(rows)["buy_top3_rate"], 1)

    def test_minimum_both_bounds(self):
        self.assertEqual(decision([day(i) for i in range(1, 12)])["status"], "BELOW_FIRST_MINIMUM")
        self.assertFalse(decision([day(i, races=4) for i in range(1, 13)])["first_checkpoint_reached"])
        self.assertTrue(decision([day(i) for i in range(1, 13)])["first_checkpoint_reached"])

    def test_final_both_bounds(self):
        self.assertFalse(decision([day(i, races=4) for i in range(1, 25)])["final_checkpoint_reached"])
        self.assertTrue(decision([day(i) for i in range(1, 25)])["final_checkpoint_reached"])

    def test_accept(self):
        self.assertEqual(decision([day(i) for i in range(1, 13)], bootstrap_ci=(1, 10))["status"], "ACCEPT")

    def test_reject(self):
        self.assertEqual(decision([day(i, delta=0) for i in range(1, 25)], bootstrap_ci=(-1, 1))["status"], "REJECT")

    def test_inconclusive(self):
        self.assertEqual(decision([day(i, delta=1, slots=30) for i in range(1, 25)], bootstrap_ci=(-1, 2))["status"], "INCONCLUSIVE_CLOSE")

    def test_top_two_removed(self):
        days = [day(i, delta=0) for i in range(1, 13)]
        days[0]["delta_hits"] = 10; days[1]["delta_hits"] = 10
        x = decision(days, bootstrap_ci=(1, 10))
        self.assertEqual(x["top_two_removed_delta_hits"], 0)
        self.assertNotEqual(x["status"], "ACCEPT")

    def test_second_half(self):
        days = [day(i, delta=3 if i <= 6 else -1) for i in range(1, 13)]
        x = decision(days, bootstrap_ci=(1, 10))
        self.assertLess(x["second_half_delta_hits"], 0)
        self.assertNotEqual(x["status"], "ACCEPT")

    def test_field_size(self):
        rows = [dict(field_size=6, valid_result=True, actual_top3=True),
                dict(field_size=12, valid_result=True, actual_top3=False),
                dict(field_size=10, valid_result=False, actual_top3=True)]
        x = field_size_diagnostic(rows)
        self.assertEqual(x["valid"], 2)
        self.assertAlmostEqual(x["expected_hits"], .75)
        self.assertAlmostEqual(x["excess_hits"], .25)

    def test_smallest_field_order(self):
        rows = [dict(race_id="b", field_size=6, horse_number=2),
                dict(race_id="a", field_size=6, horse_number=3),
                dict(race_id="a", field_size=6, horse_number=1)]
        self.assertEqual([(r["race_id"], r["horse_number"]) for r in smallest_field_first(rows, 2)], [("a", 1), ("a", 3)])

    def test_overlap_partition(self):
        x = overlap_class({(1,), (2,)}, {(2,), (3,)})
        self.assertEqual(x["PL_JOCKEY_E1_OVERLAP"], {(2,)})
        self.assertEqual(x["PL_JOCKEY_NON_OVERLAP"], {(1,)})
        self.assertEqual(x["E1_NON_OVERLAP"], {(3,)})

    def test_no_result_no_post(self):
        with self.assertRaises(ValueError): require_post_source(result_exists=False, result_read_after_freeze=False)

    def test_no_popularity_or_betting_odds_dependency(self):
        # Neither PRE diagnostic selector accepts/consults a popularity or odds field.
        rows = [dict(race_id="a", field_size=10, horse_number=1, plj_p_top3=.2, popularity=1, betting_odds=1),
                dict(race_id="b", field_size=8, horse_number=2, plj_p_top3=.9, popularity=9, betting_odds=100)]
        self.assertEqual(smallest_field_first(rows, 1)[0]["race_id"], "b")
        self.assertEqual(global_allocation(rows, 1)[0]["race_id"], "b")
        for row in rows:
            row["popularity"] *= -1; row["betting_odds"] *= -1
        self.assertEqual(global_allocation(rows, 1)[0]["race_id"], "b")


if __name__ == "__main__":
    unittest.main()
