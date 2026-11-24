import unittest

from review.daily_pre_track_information_runtime_observability_audit_v1 import (
    canonical_json,
    classify_manual_track_bias,
    classify_timestamp,
    count_track_bias_scores,
    prior_same_surface_count,
)


class DailyPreTrackObservabilityAuditV1Test(unittest.TestCase):
    def test_manual_track_bias_state_classification(self):
        self.assertEqual(classify_manual_track_bias(None), "PROVEN_NULL_OR_ABSENT")
        self.assertEqual(classify_manual_track_bias("front"), "PROVEN_NON_NULL")
        self.assertEqual(classify_manual_track_bias(None, observable=False), "NOT_OBSERVABLE_FROM_ARTIFACT")

    def test_zero_nonzero_missing_and_malformed_count(self):
        result = count_track_bias_scores([
            {"track_bias_score": 0}, {"track_bias_score": 2},
            {"track_bias_score": -1}, {}, {"track_bias_score": "bad"},
        ])
        self.assertEqual(result, {"total": 5, "zero": 1, "positive": 1, "negative": 1, "missing": 1, "malformed": 1})

    def test_timestamp_semantics(self):
        self.assertEqual(classify_timestamp("result_finalized_at", "x"), "SOURCE_SEMANTIC_TIMESTAMP")
        self.assertEqual(classify_timestamp("scheduled_post_time", "x"), "SCHEDULED_RACE_TIME_ONLY")
        self.assertEqual(classify_timestamp("mtime", "x"), "FILESYSTEM_METADATA_ONLY")
        self.assertEqual(classify_timestamp("unknown", None), "NONE")

    def test_prior_race_only_and_surface_separation(self):
        rows = [
            {"date": "20260101", "venue": "東京", "race_number": 1, "surface": "turf"},
            {"date": "20260101", "venue": "東京", "race_number": 2, "surface": "dirt"},
            {"date": "20260101", "venue": "東京", "race_number": 3, "surface": "turf"},
            {"date": "20260101", "venue": "東京", "race_number": 5, "surface": "turf"},
            {"date": "20260101", "venue": "東京", "race_number": 9, "surface": "turf"},
        ]
        self.assertEqual(prior_same_surface_count(rows, rows[3]), 2)
        self.assertEqual(prior_same_surface_count(rows, rows[2]), 1)

    def test_deterministic_artifact_serialization(self):
        left = canonical_json({"b": 2, "a": 1})
        right = canonical_json({"a": 1, "b": 2})
        self.assertEqual(left, right)

    def test_no_performance_join_surface(self):
        forbidden = {"actual_top3", "buy_top3_rate", "finish_join"}
        exported_helpers = {classify_manual_track_bias.__name__, count_track_bias_scores.__name__, classify_timestamp.__name__, prior_same_surface_count.__name__}
        self.assertTrue(forbidden.isdisjoint(exported_helpers))


if __name__ == "__main__":
    unittest.main()
