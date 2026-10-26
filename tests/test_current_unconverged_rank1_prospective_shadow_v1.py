"""Result-blind prospective adapter checks on an already frozen Current PRE."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from review import current_unconverged_rank1_prospective_shadow_v1 as shadow


PRE = shadow.ROOT / "reports/20261025_pre_v1/current_frozen"


class ProspectiveShadowTest(unittest.TestCase):
    def test_existing_frozen_pre_invariants_and_determinism(self):
        with patch("review.candidate_generation_training_dataset_readiness_v1.result_rows",
                   side_effect=AssertionError("Result access")):
            first = shadow.build_pre(PRE, "20261025")
            second = shadow.build_pre(PRE, "20261025")
        self.assertEqual(first, second)
        self.assertEqual(first["result_access_count"], 0)
        self.assertEqual(first["eligible_races"], len(first["selections"]))
        self.assertEqual(len({row["race_id"] for row in first["selections"]}), first["eligible_races"])
        self.assertTrue(all(row["shadow_k"] == 1 and
                            row["race_state"] == "PLAY_UNCONVERGED_4PLUS" and
                            row["selection_reason"] == "CURRENT_SCORE_RANK1_FIXED_K1"
                            for row in first["selections"]))
        rows, _ = shadow.load_frozen_current(PRE, "20261025")
        for addition in first["selections"]:
            candidates = [row for row in rows if row["race_id"] == addition["race_id"]
                          and row["values"]["shadow_buy_candidate"]]
            self.assertEqual(addition["selected_horse_number"],
                             min(candidates, key=lambda row: row["rank"])["horse_number"])
            self.assertEqual(addition["stored_rank"],
                             min(row["rank"] for row in candidates))

    def test_authority_fail_closed(self):
        with patch.object(shadow, "APPROVAL_SHA", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "STOP_SHADOW_AUTHORITY_SHA_MISMATCH"):
                shadow.build_pre(PRE, "20261025")

    def test_missing_state_and_candidate_fail_closed(self):
        original = shadow._json
        for key in ("race_state", "shadow_buy_candidate"):
            def altered_read(path):
                data = original(path)
                if path.name.endswith("_prediction.json"):
                    data = copy.deepcopy(data)
                    del data["ranked_results"][0][{"race_state": "buy_v1_rc1_race_state",
                                                     "shadow_buy_candidate": "buy_v1_rc1_candidate"}[key]]
                return data
            with patch.object(shadow, "_json", side_effect=altered_read):
                with self.assertRaisesRegex(RuntimeError, "STOP_CURRENT_PRE_SELECTOR_INPUT_MISSING"):
                    shadow.load_frozen_current(PRE, "20261025")

    def test_missing_rank_fail_closed(self):
        rows, source = shadow.load_frozen_current(PRE, "20261025")
        altered = copy.deepcopy(rows)
        del altered[0]["rank"]
        with self.assertRaises(RuntimeError):
            shadow.select(altered, source["race_count"])


if __name__ == "__main__":
    unittest.main()
