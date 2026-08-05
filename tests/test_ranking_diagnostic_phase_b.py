import inspect
import unittest
from review.ranking_diagnostic_phase_b import rank_rows, run


class RankingDiagnosticPhaseBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows,cls.mismatches,cls.groups,cls.transitions,cls.summary=run()

    def test_448_targets(self):self.assertEqual(len(self.rows),448)
    def test_443_valid(self):self.assertEqual(self.summary["valid_results"],443)
    def test_exactly_8_mismatches(self):self.assertEqual(len(self.mismatches),8)
    def test_ranks_within_race(self):self.assertTrue(all(r["final_rank"]>=1 and r["adjusted_rank"]>=1 for r in self.rows))
    def test_stable_sort_rule(self):
        rows=[{"adjusted_score":"10","horse_number":"2","horse_name":"B"},{"adjusted_score":"10","horse_number":"1","horse_name":"A"}]
        ranks,_=rank_rows(rows,"adjusted_score");self.assertEqual((ranks[id(rows[1])],ranks[id(rows[0])]),(1,2))
    def test_all_mismatches_are_ties(self):self.assertEqual({r["primary_cause"] for r in self.mismatches},{"TIE_BREAK_DIFFERENCE"})
    def test_effect_partition(self):
        o=self.summary["overall"];self.assertEqual(o["IMPROVED"]+o["WORSENED"]+o["NEUTRAL"],443)
    def test_invalid_results_excluded(self):self.assertEqual(sum(r["effect"]=="INVALID_RESULT_EXCLUDED" for r in self.rows),5)
    def test_non_buy_top3_group(self):self.assertEqual(next(r for r in self.groups if r["group"]=="NON_BUY_TOP3" and r["slice_axis"]=="OVERALL")["count"],92)
    def test_fp_group(self):self.assertEqual(next(r for r in self.groups if r["group"]=="FP_BUY" and r["slice_axis"]=="OVERALL")["count"],29)
    def test_successful_buy_group(self):self.assertEqual(self.summary["successful_buy_protection"]["count"],10)
    def test_top5_partition(self):self.assertEqual(sum(r["count"] for r in self.transitions),443)
    def test_no_result_leakage(self):self.assertEqual(self.summary["result_data_used_as_evaluation_input"],"NO")
    def test_no_adapter_or_replay(self):
        source=inspect.getsource(__import__("review.ranking_diagnostic_phase_b",fromlist=["x"]));self.assertNotIn("TargetTrialAdapter",source);self.assertNotIn("TargetResultAdapter",source)
    def test_ranking_review_candidate(self):self.assertEqual(self.summary["judgment"],"RANKING_LAYER_REVIEW_CANDIDATE")
    def test_non_buy_top3_worsens_each_date(self):self.assertTrue(self.summary["review_candidate_evidence"]["worsened_exceeds_improved_on_all_dates"])
    def test_provenance_required_before_next_diagnostic(self):self.assertEqual(self.summary["provenance_addition"]["judgment"],"ADD_BEFORE_NEXT_DIAGNOSTIC")
    def test_zero_production_delta(self):self.assertEqual(self.summary["production_delta"],"ZERO")


if __name__=="__main__":unittest.main()
