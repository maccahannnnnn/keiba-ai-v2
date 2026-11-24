from __future__ import annotations

import copy
import unittest

from review.cf_top3_rank_anchored_shadow_v1 import (
    ShadowProtocolIntegrityError, append_formal_post_evidence, empty_formal_ledger,
    join_post_result, protocol_hash, protocol_definition, select_pre,
)


def trace(state="PLAY_UNCONVERGED_4PLUS", ranks=(1, 2, 3, 4), legacy=None):
    legacy = legacy or tuple(range(len(ranks), 0, -1))
    return {"race": {"shadow_race_state": state, "shadow_candidate_count": len(ranks), "shadow_spec_converged": state != "PLAY_UNCONVERGED_4PLUS"}, "horses": [{"horse_number": index + 1, "horse_name": f"H{index + 1}", "shadow_ai_rank": rank, "ai_rank": legacy[index], "shadow_buy_candidate": state == "PLAY_UNCONVERGED_4PLUS", "shadow_buy": False} for index, rank in enumerate(ranks)]}


def ranked(count):
    return [{"horse_number": index + 1, "horse_name": f"H{index + 1}", "buy": False} for index in range(count)]


def select(value):
    return select_pre(date="20260824", venue="札幌", race_number=1, race_id="race_20260824_sapporo_1R", buy_gate_trace=value, ranked_results=ranked(len(value["horses"])))


def activation_record():
    return {"formal_activation_status": "ACTIVATED", "formal_activation_id": "TEST_ONLY_ACTIVATION", "protocol_version": protocol_definition()["protocol_version"], "protocol_sha256": protocol_hash()}


def activated_ledger():
    ledger = empty_formal_ledger()
    ledger["formal_activation_status"] = "ACTIVATED"
    return ledger


def post_record(race_id):
    return {"race_id": race_id, "candidate_pool_valid_count": 4, "candidate_pool_top3_count": 2, "selected_valid_count": 3, "selected_top3_count": 2}


class CfTop3RankAnchoredShadowTests(unittest.TestCase):
    def test_01_four_candidates_selects_exact_three_safe_ranks(self):
        result = select(trace(ranks=(4, 1, 3, 2)))
        self.assertEqual([row["shadow_ai_rank"] for row in result["cf_selected_horses"]], [1, 2, 3])
        self.assertEqual(result["cf_selected_count"], 3)

    def test_02_five_candidates_selects_exact_three(self):
        result = select(trace(ranks=(5, 2, 4, 1, 3), legacy=(1, 2, 3, 4, 5)))
        self.assertEqual([row["shadow_ai_rank"] for row in result["cf_selected_horses"]], [1, 2, 3])

    def test_03_noncontiguous_ranks_selects_first_three(self):
        result = select(trace(ranks=(5, 1, 4, 3)))
        self.assertEqual([row["shadow_ai_rank"] for row in result["cf_selected_horses"]], [1, 3, 4])

    def test_04_noneligible_states_have_no_selection(self):
        for state in ("PLAY_CONVERGED", "SKIP"):
            with self.subTest(state=state):
                result = select(trace(state=state, ranks=(1, 2, 3, 4)))
                self.assertEqual(result["shadow_eligibility"], "NOT_ELIGIBLE_RACE_STATE")
                self.assertEqual(result["cf_selected_count"], 0)

    def test_05_safe_rank_missing_fails_closed(self):
        value = trace()
        del value["horses"][0]["shadow_ai_rank"]
        with self.assertRaisesRegex(ShadowProtocolIntegrityError, "SAFE_RANK_UNAVAILABLE"):
            select(value)

    def test_06_legacy_ai_rank_is_never_used(self):
        result = select(trace(ranks=(4, 3, 2, 1), legacy=(1, 2, 3, 4)))
        self.assertEqual([row["horse_number"] for row in result["cf_selected_horses"]], [4, 3, 2])

    def test_07_production_buy_input_is_unchanged(self):
        value, rows = trace(), ranked(4)
        before_trace, before_rows = copy.deepcopy(value), copy.deepcopy(rows)
        select_pre(date="20260824", venue="札幌", race_number=1, race_id="race", buy_gate_trace=value, ranked_results=rows)
        self.assertEqual(value, before_trace)
        self.assertEqual(rows, before_rows)

    def test_08_pre_rejects_result_fields(self):
        value = trace()
        value["horses"][0]["actual_top3"] = True
        with self.assertRaisesRegex(ShadowProtocolIntegrityError, "PRE_RESULT_FIELD_FORBIDDEN"):
            select(value)

    def test_09_post_excludes_invalid_result_from_denominator(self):
        pre = select(trace())
        post = join_post_result(pre, {1: {"actual_finish": "1", "valid_result": True, "actual_top3": True}, 2: {"actual_finish": "取消", "valid_result": False, "actual_top3": False}, 3: {"actual_finish": "4", "valid_result": True, "actual_top3": False}, 4: {"actual_finish": "2", "valid_result": True, "actual_top3": True}})
        self.assertEqual(post["selected_valid_count"], 2)
        self.assertEqual(post["selected_top3_count"], 1)

    def test_10_empty_ledger_excludes_preprotocol_context(self):
        ledger = empty_formal_ledger()
        self.assertEqual(ledger["formal_activation_status"], "NOT_ACTIVATED")
        self.assertEqual(ledger["formal_evidence"], [])
        self.assertIn("20260822", ledger["pre_protocol_context"])
        self.assertIn("20260823", ledger["pre_protocol_context"])

    def test_11_ledger_requires_explicit_activation(self):
        with self.assertRaisesRegex(ShadowProtocolIntegrityError, "FORMAL_LEDGER_NOT_ACTIVATED"):
            append_formal_post_evidence(ledger=empty_formal_ledger(), date="20260824", activation_record=activation_record(), post_records=[post_record("race_1")], independent_race_count=1)

    def test_12_six_candidates_selects_top_three(self):
        result = select(trace(ranks=(6, 2, 5, 1, 4, 3)))
        self.assertEqual([row["shadow_ai_rank"] for row in result["cf_selected_horses"]], [1, 2, 3])

    def test_13_unconverged_under_four_candidates_fails_closed(self):
        with self.assertRaisesRegex(ShadowProtocolIntegrityError, "UNEXPECTED_CANDIDATE_COUNT"):
            select(trace(ranks=(1, 2, 3)))

    def test_14_duplicate_safe_rank_fails_closed(self):
        with self.assertRaisesRegex(ShadowProtocolIntegrityError, "SAFE_RANK_DUPLICATE"):
            select(trace(ranks=(1, 1, 3, 4)))

    def test_15_preprotocol_dates_cannot_enter_formal_evidence(self):
        for date in ("20260822", "20260823"):
            with self.subTest(date=date):
                with self.assertRaisesRegex(ShadowProtocolIntegrityError, "PRE_PROTOCOL_CONTEXT_NOT_FORMAL"):
                    append_formal_post_evidence(ledger=activated_ledger(), date=date, activation_record=activation_record(), post_records=[post_record("race_1")], independent_race_count=1)

    def test_16_duplicate_race_id_inside_append_fails_closed(self):
        with self.assertRaisesRegex(ShadowProtocolIntegrityError, "FORMAL_RACE_ID_DUPLICATE_WITHIN_APPEND"):
            append_formal_post_evidence(ledger=activated_ledger(), date="20260824", activation_record=activation_record(), post_records=[post_record("race_1"), post_record("race_1")], independent_race_count=2)

    def test_17_duplicate_race_id_across_ledger_fails_closed(self):
        ledger = append_formal_post_evidence(ledger=activated_ledger(), date="20260824", activation_record=activation_record(), post_records=[post_record("race_1")], independent_race_count=1)
        with self.assertRaisesRegex(ShadowProtocolIntegrityError, "FORMAL_RACE_ID_DUPLICATE_ACROSS_LEDGER"):
            append_formal_post_evidence(ledger=ledger, date="20260825", activation_record=activation_record(), post_records=[post_record("race_1")], independent_race_count=1)

    def test_18_independent_race_count_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ShadowProtocolIntegrityError, "INDEPENDENT_RACE_COUNT_MISMATCH"):
            append_formal_post_evidence(ledger=activated_ledger(), date="20260824", activation_record=activation_record(), post_records=[post_record("race_1")], independent_race_count=2)

    def test_19_valid_multi_race_append_preserves_unique_race_ids(self):
        ledger = append_formal_post_evidence(ledger=activated_ledger(), date="20260824", activation_record=activation_record(), post_records=[post_record("race_1"), post_record("race_2")], independent_race_count=2)
        self.assertEqual(ledger["formal_evidence"][0]["race_ids"], ["race_1", "race_2"])
        self.assertEqual(ledger["formal_independent_race_count"], 2)

    def test_20_activation_record_requires_matching_protocol_hash(self):
        bad = activation_record()
        bad["protocol_sha256"] = "not-the-frozen-protocol"
        with self.assertRaisesRegex(ShadowProtocolIntegrityError, "FORMAL_ACTIVATION_PROTOCOL_MISMATCH"):
            append_formal_post_evidence(ledger=activated_ledger(), date="20260824", activation_record=bad, post_records=[post_record("race_1")], independent_race_count=1)


if __name__ == "__main__":
    unittest.main()
