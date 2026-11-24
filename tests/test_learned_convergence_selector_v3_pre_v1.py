import unittest

from review.learned_convergence_selector_v3_pre_v1 import load_frozen_v3_model, select_v3_pre


class LearnedConvergenceSelectorV3PreV1Test(unittest.TestCase):
    def test_equal_probability_uses_safe_rank_and_ranked_horse_number(self):
        snapshot = {"Ability": 150.0, "PastPerformance": 60.0, "Distance": 35.0, "CourseShape": 6.0, "LapSuitability": 2.0, "RaceShape": 4.0, "PaceStyle": 12.0}
        payload = {"race_id": "synthetic_v3", "ranked_results": [
            {"rank": 4, "horse_number": 1, "horse_name": "d"}, {"rank": 2, "horse_number": 5, "horse_name": "b"},
            {"rank": 1, "horse_number": 8, "horse_name": "a"}, {"rank": 3, "horse_number": 2, "horse_name": "c"},
        ], "buy_gate_trace": {"race": {"shadow_race_state": "PLAY_UNCONVERGED_4PLUS", "shadow_candidate_count": 4}, "horses": [
            {"shadow_buy_candidate": True, "shadow_ai_rank": 4, "evaluator_score_snapshot": snapshot},
            {"shadow_buy_candidate": True, "shadow_ai_rank": 2, "evaluator_score_snapshot": snapshot},
            {"shadow_buy_candidate": True, "shadow_ai_rank": 1, "evaluator_score_snapshot": snapshot},
            {"shadow_buy_candidate": True, "shadow_ai_rank": 3, "evaluator_score_snapshot": snapshot},
        ]}}
        selected = select_v3_pre(payload, load_frozen_v3_model())["selected"]
        self.assertEqual([row["horse_number"] for row in selected], [8, 5, 2])
        self.assertEqual([row["selection_rank"] for row in selected], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
