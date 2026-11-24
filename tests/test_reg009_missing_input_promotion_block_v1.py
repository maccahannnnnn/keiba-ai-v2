import os
import unittest
from unittest.mock import patch

from evaluation.reg009_missing_input_promotion_block_v1 import (
    FEATURE_FLAG_NAME,
    MissingInputPromotionBlockV1,
)


class MissingInputPromotionBlockV1Tests(unittest.TestCase):
    def base_row(self, **updates):
        row = {
            "production_buy": False,
            "reg009_promoted": True,
            "reg009_shadow_buy": True,
            "warnings": [],
            "risk_reasons": [],
            "consensus_block_reasons": [],
        }
        row.update(updates)
        return row

    def test_flag_off_exactly_preserves_reg009_shadow_result(self):
        result = MissingInputPromotionBlockV1(enabled=False).evaluate(
            self.base_row(warnings=["Bloodline profile not found"])
        )
        self.assertTrue(result.shadow_buy_after)
        self.assertFalse(result.promotion_blocked)

    def test_missing_input_blocks_added_promotion(self):
        result = MissingInputPromotionBlockV1(enabled=True).evaluate(
            self.base_row(warnings=["Bloodline profile not found"])
        )
        self.assertTrue(result.missing_input_signal_present)
        self.assertTrue(result.promotion_blocked)
        self.assertFalse(result.shadow_buy_after)

    def test_no_missing_input_keeps_promotion(self):
        result = MissingInputPromotionBlockV1(enabled=True).evaluate(self.base_row())
        self.assertFalse(result.missing_input_signal_present)
        self.assertTrue(result.shadow_buy_after)

    def test_existing_production_buy_is_never_demoted(self):
        result = MissingInputPromotionBlockV1(enabled=True).evaluate(
            self.base_row(production_buy=True, warnings=["Bloodline profile not found"])
        )
        self.assertTrue(result.shadow_buy_after)
        self.assertFalse(result.promotion_blocked)

    def test_score_zero_alone_does_not_block(self):
        result = MissingInputPromotionBlockV1(enabled=True).evaluate(
            self.base_row(bloodline_score=0)
        )
        self.assertTrue(result.shadow_buy_after)
        self.assertFalse(result.missing_input_signal_present)

    def test_weak_matches_and_risk_count_do_not_block(self):
        result = MissingInputPromotionBlockV1(enabled=True).evaluate(
            self.base_row(weak_matches=["x"], risk_count=99)
        )
        self.assertTrue(result.shadow_buy_after)
        self.assertFalse(result.missing_input_signal_present)

    def test_result_information_is_ignored(self):
        result = MissingInputPromotionBlockV1(enabled=True).evaluate(
            self.base_row(actual_finish=8, actual_top3=False, fp_label=True)
        )
        self.assertTrue(result.shadow_buy_after)
        self.assertFalse(result.missing_input_signal_present)

    def test_environment_feature_flag_defaults_off_and_rolls_back(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(MissingInputPromotionBlockV1().enabled)
        with patch.dict(os.environ, {FEATURE_FLAG_NAME: "true"}, clear=True):
            self.assertTrue(MissingInputPromotionBlockV1().enabled)
        with patch.dict(os.environ, {FEATURE_FLAG_NAME: "false"}, clear=True):
            self.assertFalse(MissingInputPromotionBlockV1().enabled)

    def test_condition_count_is_exactly_one(self):
        result = MissingInputPromotionBlockV1(enabled=True).evaluate(self.base_row())
        self.assertEqual(result.condition_count, 1)

    def test_race_level_activation_is_not_changed(self):
        row = self.base_row(
            adjusted_gap=16.4,
            race_gate_activated=True,
            warnings=["Bloodline profile not found"],
        )
        annotated = MissingInputPromotionBlockV1(enabled=True).annotate(row)
        self.assertEqual(annotated["adjusted_gap"], 16.4)
        self.assertTrue(annotated["race_gate_activated"])

    def test_exact_existing_guard_reason_is_supported(self):
        result = MissingInputPromotionBlockV1(enabled=True).evaluate(
            self.base_row(consensus_block_reasons=["evaluator_score_missing"])
        )
        self.assertTrue(result.promotion_blocked)

    def test_partial_text_is_not_inferred_as_missing(self):
        result = MissingInputPromotionBlockV1(enabled=True).evaluate(
            self.base_row(warnings=["other profile not found somewhere"])
        )
        self.assertFalse(result.missing_input_signal_present)
        self.assertTrue(result.shadow_buy_after)


if __name__ == "__main__":
    unittest.main()
