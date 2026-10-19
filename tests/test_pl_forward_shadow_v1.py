from __future__ import annotations

import unittest

import numpy as np

from review import pl_forward_shadow_v1 as shadow


class PLForwardShadowV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.model = {
            "feature_model_version": "TEST",
            "scaler": {"mean": [0.0] * 21, "scale": [1.0] * 21},
            "pl_coefficients": [0.0] * 19,
        }

    def test_exact_top3_probability_and_deterministic_rank(self) -> None:
        rows = [{"date": "20261012", "race_id": "race_20261012_tokyo_1R", "horse_number": number, "horse_name": str(number), "vector": np.zeros(21)} for number in (3, 1, 2, 4)]
        output, total = shadow.infer_records(self.model, rows)
        self.assertAlmostEqual(total, 3.0, places=12)
        self.assertEqual([row["pl_race_rank"] for row in output], [3, 1, 2, 4])
        self.assertTrue(all(row["inference_status"] == "AVAILABLE" for row in output))

    def test_missing_feature_fails_closed(self) -> None:
        values = {name: 1.0 for name in shadow.FEATURE_NAMES}
        values.update({name: True for name in shadow.GATE_FEATURES})
        values["Ability"] = None
        values["race_state"] = "PLAY_CONVERGED"
        with self.assertRaisesRegex(shadow.Stop, "MISSING_REQUIRED_FEATURE:Ability"):
            shadow.canonical_vector(values)

    def test_result_named_fields_do_not_affect_runtime_feature_projection(self) -> None:
        ranked = [{"horse_number": number, "horse_name": str(number), "rank": number, "adjusted_score": float(10-number), "decision_score": 1.0, "final_score": 1.0, "consensus_positive_count": 1, "consensus_negative_count": 0, "risk_count": 0, "conflict_count": 0, "buy_v1_rc1_race_state": "PLAY_CONVERGED", "actual_top3": True, "actual_finish": 1, "valid_result": True} for number in (1, 2, 3)]
        horses = []
        for number in (1, 2, 3):
            horses.append({"horse_number": number, "shadow_ai_rank": number, "decision_score": 1.0, "final_score": 1.0, "adjusted_score": float(10-number), "absolute_quality_pass": True, "relative_advantage_pass": True, "effective_reliability_pass": True, "risk_guard_pass": True, "positive_count": 1, "negative_count": 0, "evaluator_score_snapshot": {name: 1.0 for name in shadow.FEATURE_NAMES[:7]}})
        payload = {"race_id": "race_20261012_tokyo_1R", "ranked_results": ranked, "buy_gate_trace": {"horses": horses, "race": {"shadow_race_state": "PLAY_CONVERGED"}}}
        records = shadow._payload_records(payload, "20261012")
        self.assertEqual(len(records), 3)
        self.assertTrue(all(record["vector"].shape == (21,) for record in records))


if __name__ == "__main__":
    unittest.main()
