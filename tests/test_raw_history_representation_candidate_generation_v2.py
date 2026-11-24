import json
import unittest
from pathlib import Path

import review.raw_history_representation_candidate_generation_v2 as v2


class Exp021ContractTests(unittest.TestCase):
    def test_only_rich_max_iter_changes(self): self.assertEqual(v2.MAX_ITER,1000)
    def test_control_hashes_frozen(self): self.assertEqual(len(v2.CONTROL_SHA),2)
    def test_exp020_feature_schema_sha_frozen(self): self.assertEqual(v2.FEATURE_SCHEMA_SHA,"119a319401e9e4435e8823c38c5233d312b03d5ec69b10ff0dc3da8844e46f64")
    def test_fold_sha_frozen(self): self.assertEqual(v2.FOLD_SHA,"ace55d0d48e24d066cee92e5a11aebbcf908f5256622303d5dd03bc1e5de099e")
    def test_history_contract_reused(self):
        audit=v2.feature_reuse_audit(); self.assertEqual(audit["EXP020_FEATURE_SCHEMA_REUSE_GATE"],"PASS")
    def test_lane_classification_clean(self):
        self.assertEqual(v2.lane_classification({"buy_top3_rate":.4,"top3_hits":10},{"buy_top3_rate":.3,"top3_hits":10}),"CLEAN_POSITIVE")
    def test_lane_classification_rate_tradeoff(self):
        self.assertEqual(v2.lane_classification({"buy_top3_rate":.4,"top3_hits":9},{"buy_top3_rate":.3,"top3_hits":10}),"RATE_POSITIVE_HIT_TRADEOFF")
    def test_lane_classification_hits_tradeoff(self):
        self.assertEqual(v2.lane_classification({"buy_top3_rate":.3,"top3_hits":11},{"buy_top3_rate":.3,"top3_hits":10}),"HITS_POSITIVE_RATE_NONPOSITIVE")
    def test_lane_classification_not_supported(self):
        self.assertEqual(v2.lane_classification({"buy_top3_rate":.2,"top3_hits":9},{"buy_top3_rate":.3,"top3_hits":10}),"NOT_SUPPORTED")


if __name__=="__main__": unittest.main()
