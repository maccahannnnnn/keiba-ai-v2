import copy
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch
from pathlib import Path

from review.pl_jockey_step1_operations_v1 import (
    advance_state, credit_class, derive_pre, eligible_races_from_pre,
    freeze_pre, same_scorer_smallest_field,
)


def race(i, k=1):
    return {"race_id": f"race_{i}", "current_k": k, "candidate_k": k,
            "current_selected_horses": list(range(1, k + 1)),
            "candidate_selected_horses": list(range(1, k + 1))}


def day(i, *, delta=0, slot_count=5):
    pre = [race(j) for j in range(5)]
    return {"date": f"2026-12-{i:02d}", "role": "PROSPECTIVE_ELIGIBLE",
            "pre_frozen_before_result": True, "result_join_verified": True,
            "pre_races": pre, "current_buy_counts": {r["race_id"]: 1 for r in pre},
            "plj_slots": slot_count, "current_slots": slot_count,
            "delta_hits": delta, "plj_valid_n": slot_count, "plj_valid_hits": 2}


class Step1OperationsTests(unittest.TestCase):
    def test_eligible_race_positive_k_only(self):
        rows = [race(1, 0), race(2, 2)]
        self.assertEqual(eligible_races_from_pre(rows, {"race_1": 0, "race_2": 2}), (1, 2))

    def test_same_race_and_k_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "RACE_SET"):
            eligible_races_from_pre([race(1)], {"race_2": 1})
        with self.assertRaisesRegex(ValueError, "K_MISMATCH"):
            eligible_races_from_pre([race(1)], {"race_1": 2})

    def test_pre_artifact_broad_count_not_used(self):
        x = day(1)
        x["eligible_race_count"] = 99
        s = advance_state({}, x)
        self.assertEqual(s["formal_evidence_races"], 5)

    def test_before_12d_60r_no_decision(self):
        state = {}
        for i in range(1, 12):
            state = advance_state(state, day(i))
        self.assertFalse(state.get("first_checkpoint_decided", False))

    def test_12d_60r_first_arrival(self):
        state = {}
        for i in range(1, 13):
            state = advance_state(state, day(i), bootstrap_ci=(-1, 1))
        self.assertTrue(state["first_checkpoint_decided"])
        self.assertEqual(state["first_checkpoint_date"], "2026-12-12")
        self.assertEqual(state["formal_evidence_races"], 60)

    def test_13th_date_no_redecision(self):
        state = {}
        for i in range(1, 14):
            state = advance_state(state, day(i), bootstrap_ci=(-1, 1))
        self.assertEqual(state["first_checkpoint_date"], "2026-12-12")

    def test_final_first_arrival(self):
        state = {}
        for i in range(1, 25):
            state = advance_state(state, day(i), bootstrap_ci=(-1, 1))
        self.assertTrue(state["final_checkpoint_decided"])
        self.assertEqual(state["final_checkpoint_date"], "2026-12-24")

    def test_25th_date_does_not_redecide(self):
        state = {}
        for i in range(1, 26):
            state = advance_state(state, day(i), bootstrap_ci=(-1, 1))
        self.assertEqual(state["formal_evidence_dates"], 24)
        self.assertEqual(state["final_checkpoint_date"], "2026-12-24")

    def test_inconclusive_irreversible(self):
        state = {}
        for i in range(1, 25):
            state = advance_state(state, day(i, delta=1), bootstrap_ci=(-1, 2))
        self.assertEqual(state["terminal_status"], "INCONCLUSIVE_CLOSE")
        later = advance_state(state, day(25, delta=5), bootstrap_ci=(1, 8))
        self.assertEqual(later["terminal_status"], "INCONCLUSIVE_CLOSE")

    def test_1031_and_1101_blocked(self):
        self.assertEqual(credit_class("2026-10-31", "PROSPECTIVE_ELIGIBLE", pre_frozen_before_result=True), "PRE_ADDENDUM_OBSERVATION")
        self.assertEqual(credit_class("2026-11-01", "PROSPECTIVE_ELIGIBLE", pre_frozen_before_result=True), "PRE_ADDENDUM_OBSERVATION")
        self.assertEqual(credit_class("20261101", "PROSPECTIVE_ELIGIBLE", pre_frozen_before_result=True), "PRE_ADDENDUM_OBSERVATION")
        for date in ("2026-10-31", "2026-11-01"):
            x = day(1); x["date"] = date
            self.assertEqual(advance_state({}, x).get("formal_evidence_dates", 0), 0)

    def test_pre_freeze_and_reference_blocked(self):
        self.assertEqual(credit_class("2026-11-03", "PROSPECTIVE_ELIGIBLE", pre_frozen_before_result=True), "REFERENCE_ONLY")
        self.assertEqual(credit_class("2026-12-04", "DIAGNOSTIC_B", pre_frozen_before_result=True), "REFERENCE_ONLY")
        self.assertEqual(credit_class("2026-12-04", "DEVELOPMENT", pre_frozen_before_result=True), "REFERENCE_ONLY")

    def test_post_freeze_eligible_included(self):
        self.assertEqual(credit_class("2026-11-04", "PROSPECTIVE_ELIGIBLE", pre_frozen_before_result=True), "FORMAL_NEW_GATE_ELIGIBLE")

    def test_unverified_post_or_parent_suspend(self):
        x = day(1); x["result_join_verified"] = False
        with self.assertRaisesRegex(ValueError, "RESULT_JOIN_NOT_VERIFIED"):
            advance_state({}, x)
        x["parent_suspended"] = True
        self.assertEqual(advance_state({}, x)["terminal_status"], "PARENT_SUSPEND_HUMAN_REVIEW")

    def test_same_scorer_deterministic(self):
        rows = [dict(race_id="b", field_size=8, horse_number=1, pl_probability=.99, plj_p_top3=.10),
                dict(race_id="a", field_size=8, horse_number=2, pl_probability=.3, plj_p_top3=.9),
                dict(race_id="a", field_size=8, horse_number=1, pl_probability=.9, plj_p_top3=.3)]
        self.assertEqual(same_scorer_smallest_field(rows, 2, scorer="pl_probability")[0]["horse_number"], 1)
        self.assertEqual(same_scorer_smallest_field(rows, 2, scorer="plj_p_top3")[0]["horse_number"], 2)

    def test_scorer_is_frozen_pl_or_plj_only(self):
        row = dict(race_id="a", field_size=8, horse_number=1, pl_probability=.8, plj_p_top3=.2)
        self.assertEqual(same_scorer_smallest_field([row], 1, scorer="pl_probability"), [row])
        self.assertEqual(same_scorer_smallest_field([row], 1, scorer="plj_p_top3"), [row])
        with self.assertRaisesRegex(ValueError, "UNAPPROVED_SCORER"):
            same_scorer_smallest_field([row], 1, scorer="popularity")

    def test_late_pre_diagnostic_not_evaluable_without_opening_files(self):
        late = datetime(2026, 11, 7, 11, 0, tzinfo=timezone(timedelta(hours=9)))
        with patch.object(Path, "read_text", side_effect=AssertionError("PRE opened late")):
            with self.assertRaisesRegex(ValueError, "NOT_EVALUABLE_PRE_NOT_FROZEN"):
                freeze_pre(plj_path=Path("selection.json"), e1_path=Path("selection.json"),
                           current_manifest_path=Path("prediction_manifest.json"),
                           current_buy_counts={}, first_start_at="2026-11-07T10:00:00+09:00",
                           output_path=Path("never_created.json"), now=late)

    def test_pre_runner_has_no_result_or_odds_path(self):
        code = Path("review/pl_jockey_step1_operations_v1.py").read_text(encoding="utf-8")
        self.assertNotIn("daily_result_list", code)
        self.assertNotIn("betting_odds", code)
        self.assertNotIn("popularity", code)
        self.assertNotIn("actual_top3", code)


if __name__ == "__main__":
    unittest.main()
