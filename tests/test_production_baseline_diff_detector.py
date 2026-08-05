import unittest
from review.production_baseline_diff_detector import compare

R=[{"race_id":"r1","race_decision":"PLAY","race_state":"PLAY_CONVERGED","confidence":"high"}]
H=[{"race_id":"r1","horse_number":"1","decision":"BUY","final_score":"10","adjusted_score":"11","decision_score":"1"}]

class DetectorTests(unittest.TestCase):
    def test_identical(self): self.assertEqual(compare(R,H,R,H)["primary_difference"], "NO_CHANGE")
    def test_buy(self):
        h=[dict(H[0], decision="CAUTION")]
        self.assertEqual(compare(R,H,R,h)["primary_difference"], "BUY_SET_CHANGED")
        self.assertEqual(compare(R,H,R,h)["remeasurement_judgment"], "REMEASUREMENT_GO")
    def test_decision(self): self.assertEqual(compare(R,H,[dict(R[0],race_decision="PASS")],H)["primary_difference"], "DECISION_CHANGED")
    def test_phase0_column_names(self):
        r=[{"race_id":"r1","RaceDecision":"PLAY","RaceState":"PLAY_CONVERGED","Confidence":"high"}]
        self.assertEqual(compare(r,H,[dict(r[0],RaceDecision="PASS")],H)["primary_difference"],"DECISION_CHANGED")
    def test_score(self): self.assertEqual(compare(R,H,R,[dict(H[0],final_score="12")])["primary_difference"], "SCORE_CHANGED_ONLY")
    def test_metadata_ignored(self): self.assertEqual(compare(R,H,[dict(R[0],note="x")],[dict(H[0],note="x")])["primary_difference"], "NO_CHANGE")
    def test_sets_and_source(self):
        self.assertEqual(compare(R,H,[],H)["primary_difference"], "RACE_SET_CHANGED")
        self.assertEqual(compare(R,H,R,[])["primary_difference"], "HORSE_SET_CHANGED")
        self.assertEqual(compare(R,H,R,H,source_compatible=False)["primary_difference"], "SOURCE_CHANGED")
        self.assertEqual(compare(R,H,R,H,trace_compatible=False)["primary_difference"], "TRACE_INCOMPATIBLE")

if __name__ == "__main__": unittest.main()
