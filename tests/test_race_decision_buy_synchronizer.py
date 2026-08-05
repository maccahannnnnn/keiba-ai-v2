import unittest

from engine.race_decision_buy_synchronizer import RaceDecisionBuySynchronizer


class RaceDecisionBuySynchronizerTest(unittest.TestCase):
    def setUp(self):
        self.sync = RaceDecisionBuySynchronizer()

    def _race(self, decision):
        return {
            "race_decision": decision,
            "race_confidence": "high",
            "race_decision_score": 0.31,
            "race_decision_reason": "original reason",
        }

    def _horses(self, buy_count):
        horses = []
        for index in range(1, 5):
            decision = "BUY" if index <= buy_count else "CAUTION"
            horses.append(
                {
                    "horse_name": f"Horse{index}",
                    "decision": decision,
                    "final_score": 100 + index,
                    "adjusted_score": 120 + index,
                    "confidence_level": "very_high",
                    "ability_score": 10 + index,
                }
            )
        return horses

    def test_pass_buy0_keeps_pass(self):
        result = self.sync.synchronize(self._race("PASS"), self._horses(0))
        self.assertEqual(result["race_decision_final"], "PASS")
        self.assertFalse(result["race_decision_sync_applied"])

    def test_pass_buy1_syncs_to_non_pass(self):
        result = self.sync.synchronize(self._race("PASS"), self._horses(1))
        self.assertEqual(result["race_decision_final"], "PLAY")
        self.assertTrue(result["race_decision_sync_applied"])

    def test_pass_buy2_syncs_to_non_pass(self):
        result = self.sync.synchronize(self._race("PASS"), self._horses(2))
        self.assertEqual(result["race_decision_final"], "PLAY")
        self.assertTrue(result["race_decision_sync_applied"])

    def test_pass_buy3_syncs_to_non_pass(self):
        result = self.sync.synchronize(self._race("PASS"), self._horses(3))
        self.assertEqual(result["race_decision_final"], "PLAY")
        self.assertTrue(result["race_decision_sync_applied"])

    def test_play_buy_keeps_play(self):
        result = self.sync.synchronize(self._race("PLAY"), self._horses(1))
        self.assertEqual(result["race_decision_final"], "PLAY")
        self.assertFalse(result["race_decision_sync_applied"])

    def test_caution_buy_keeps_caution(self):
        result = self.sync.synchronize(self._race("CAUTION"), self._horses(1))
        self.assertEqual(result["race_decision_final"], "CAUTION")
        self.assertFalse(result["race_decision_sync_applied"])

    def test_play_buy0_does_not_force_pass(self):
        result = self.sync.synchronize(self._race("PLAY"), self._horses(0))
        self.assertEqual(result["race_decision_final"], "PLAY")
        self.assertFalse(result["race_decision_sync_applied"])

    def test_original_decision_is_kept(self):
        result = self.sync.synchronize(self._race("PASS"), self._horses(1))
        race = result["race_decision_result"]
        self.assertEqual(race["race_decision_original"], "PASS")
        self.assertEqual(race["race_decision_final"], "PLAY")

    def test_sync_reason_is_kept(self):
        result = self.sync.synchronize(self._race("PASS"), self._horses(1))
        self.assertIn("BUY V1 RC1", result["race_decision_sync_reason"])
        self.assertIn("BUY V1 RC1", result["race_decision_result"]["race_decision_reason"])

    def test_buy_horses_and_buy_count_do_not_change(self):
        horses = self._horses(3)
        before = [horse["horse_name"] for horse in horses if horse["decision"] == "BUY"]
        result = self.sync.synchronize(self._race("PASS"), horses)
        after = [horse["horse_name"] for horse in horses if horse["decision"] == "BUY"]
        self.assertEqual(before, after)
        self.assertEqual(result["final_buy_count"], 3)

    def test_scores_do_not_change(self):
        horses = self._horses(2)
        before = [(horse["final_score"], horse["adjusted_score"]) for horse in horses]
        self.sync.synchronize(self._race("PASS"), horses)
        after = [(horse["final_score"], horse["adjusted_score"]) for horse in horses]
        self.assertEqual(before, after)

    def test_confidence_does_not_change(self):
        race = self._race("PASS")
        result = self.sync.synchronize(race, self._horses(1))
        self.assertEqual(result["race_decision_result"]["race_confidence"], "high")

    def test_evaluator_like_fields_do_not_change(self):
        horses = self._horses(1)
        before = [horse["ability_score"] for horse in horses]
        self.sync.synchronize(self._race("PASS"), horses)
        after = [horse["ability_score"] for horse in horses]
        self.assertEqual(before, after)

    def test_existing_output_compatibility(self):
        result = self.sync.synchronize(self._race("PASS"), self._horses(1))
        race = result["race_decision_result"]
        self.assertIn("race_decision", race)
        self.assertIn("race_decision_original", race)
        self.assertIn("race_decision_sync_reason", race)

    def test_invalid_data_is_safe(self):
        result = self.sync.synchronize(None, None, None)
        self.assertEqual(result["final_buy_count"], 0)
        self.assertFalse(result["race_decision_sync_applied"])


if __name__ == "__main__":
    unittest.main()
