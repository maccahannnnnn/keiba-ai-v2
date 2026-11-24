import unittest

from review.track_condition_semantic_shadow_v1 import EXPECTED, shadow_defaults
from evaluation.track_condition_suitability_evaluator import TrackConditionSuitabilityEvaluator
from evaluation.past_performance_evaluator import PastPerformanceEvaluator


class TrackConditionSemanticShadowV1Tests(unittest.TestCase):
    def test_01_shadow_defaults_only_remove_target_day_track_condition(self):
        control = {"track_condition": "good", "surface": "turf", "distance": 1600, "nested": {"x": 1}}
        shadow = shadow_defaults(control)
        self.assertIsNone(shadow["track_condition"])
        self.assertEqual(shadow["surface"], "turf")
        self.assertEqual(shadow["distance"], 1600)
        shadow["nested"]["x"] = 2
        self.assertEqual(control["nested"]["x"], 1)

    def test_02_unknown_target_condition_is_neutral_for_track_condition_suitability(self):
        result = TrackConditionSuitabilityEvaluator().evaluate(
            recent_runs=[{"track_condition": "good", "finish_position": 1}],
            surface="turf", track_condition=None, horse_name="test",
        )
        self.assertEqual(result["track_condition_score"], 0)
        self.assertEqual(result["track_condition_fit"], "unknown")
        self.assertFalse(result["matched"])

    def test_03_unknown_target_condition_retains_history_but_skips_target_match_component(self):
        runs = [{"track_condition": "good", "finish_position": 1, "margin": 0.0, "distance": 1600, "surface": "turf", "last_3f": 34.0, "pci": 50.0, "rpci": 50.0}]
        result = PastPerformanceEvaluator().evaluate(runs, surface="turf", distance=1600, track_condition=None, horse_name="test")
        self.assertEqual(result["history_count"], 1)
        self.assertGreater(result["past_performance_score"], 0)
        self.assertNotIn("track_condition_fit", result["summary"]["modifiers"])

    def test_04_frozen_may_expected_values_are_complete_and_fixed(self):
        self.assertEqual(EXPECTED, {
            "dates": 10, "races": 192, "horses": 2645, "control_buys": 181,
            "shadow_buys": 133, "common_buys": 66, "control_only_buys": 115,
            "shadow_only_buys": 67, "track_condition_score_changed": 2635,
            "past_performance_score_changed": 2161, "final_score_changed": 2635,
            "ranking_changed": 600, "race_decision_changed": 125, "buy_changed_races": 109,
        })


if __name__ == "__main__":
    unittest.main()
