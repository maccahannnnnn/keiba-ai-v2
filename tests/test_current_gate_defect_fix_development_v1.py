"""Synthetic, Result-free tests for the approved tie-only comparison rule."""
import copy
import unittest

from review.current_gate_defect_fix_development_v1 import compare_off


def pair():
    rows = [
        {"horse_number": 13, "horse_name": "A", "rank": 5, "adjusted_score": 135.8,
         "decision": "PASS", "decision_score": 0.5, "decision_risks": [],
         "buy_v1_rc1_buy": False, "decision_result": {"ai_rank": 5.0}},
        {"horse_number": 7, "horse_name": "B", "rank": 6, "adjusted_score": 135.8,
         "decision": "PASS", "decision_score": 0.5, "decision_risks": [],
         "buy_v1_rc1_buy": False, "decision_result": {"ai_rank": 6.0}},
    ]
    current = {"race_id": "race_20260228_kokura_11R", "race_decision": "PLAY",
               "race_confidence": "medium", "ranked_results": rows,
               "buy_gate_trace": {"race": {"shadow_race_state": "PLAY_CONVERGED"},
                                  "horses": [{"horse_number": 13, "risk_guard_pass": True},
                                             {"horse_number": 7, "risk_guard_pass": True}]}}
    saved = copy.deepcopy(current)
    saved["ranked_results"][0]["decision_result"]["ai_rank"] = 6.0
    saved["ranked_results"][1]["decision_result"]["ai_rank"] = 5.0
    return current, saved


class ComparisonTests(unittest.TestCase):
    def test_exact_tie_diagnostic_only_including_top5_boundary(self):
        current, saved = pair()
        rows = compare_off(current["race_id"], current, saved)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["classification"] for row in rows}, {"TIE_ORDER_DIAGNOSTIC_ONLY"})

    def test_not_exactly_tied_rejected(self):
        current, saved = pair()
        current["ranked_results"][1]["adjusted_score"] = 135.81
        rows = compare_off(current["race_id"], current, saved)
        self.assertTrue(any(row["classification"] == "OTHER" for row in rows))

    def test_top_rank_difference_rejected(self):
        current, saved = pair()
        saved["ranked_results"][0]["rank"] = 6
        rows = compare_off(current["race_id"], current, saved)
        self.assertTrue(any(row["classification"] == "DECISION_RELEVANT" for row in rows))

    def test_buy_difference_rejected(self):
        current, saved = pair()
        saved["ranked_results"][0]["buy_v1_rc1_buy"] = True
        rows = compare_off(current["race_id"], current, saved)
        self.assertTrue(any(row["classification"] == "DECISION_RELEVANT" for row in rows))

    def test_gate_difference_rejected(self):
        current, saved = pair()
        saved["buy_gate_trace"]["horses"][0]["risk_guard_pass"] = False
        rows = compare_off(current["race_id"], current, saved)
        self.assertTrue(any(row["classification"] == "DECISION_RELEVANT" for row in rows))

    def test_rank_only_gate_risk_summary_allowed_but_other_text_rejected(self):
        current, saved = pair()
        current["buy_gate_trace"]["horses"][0]["risk_summary"] = ["same", "Low Rank BUY Guard: AI順位5位のためBUYからCAUTIONへ調整"]
        saved["buy_gate_trace"]["horses"][0]["risk_summary"] = ["same", "Low Rank BUY Guard: AI順位6位のためBUYからCAUTIONへ調整"]
        rows = compare_off(current["race_id"], current, saved)
        self.assertEqual({row["classification"] for row in rows}, {"TIE_ORDER_DIAGNOSTIC_ONLY"})
        saved["buy_gate_trace"]["horses"][0]["risk_summary"].append("別の危険")
        rows = compare_off(current["race_id"], current, saved)
        self.assertIn("DECISION_RELEVANT", {row["classification"] for row in rows})

    def test_unrelated_diagnostic_difference_rejected(self):
        current, saved = pair()
        saved["ranked_results"][0]["unknown_diagnostic"] = "different"
        rows = compare_off(current["race_id"], current, saved)
        self.assertTrue(any(row["classification"] == "OTHER" for row in rows))


if __name__ == "__main__":
    unittest.main()
