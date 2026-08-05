import unittest
from review.unconverged_shadow_evidence_repair import recompute
class RepairTests(unittest.TestCase):
 def test_threshold_recalculation(self):
  row={"decision_score":"0.8","final_score":"130","adjusted_score":"145","ai_rank":"1","ability_score":"120","past_performance_score":"55","distance_score":"30","course_shape_score":"5","lap_score":"0","race_shape_score":"0","pace_style_score":"10"}
  _,a,r,c,*_=recompute([row])[0];self.assertEqual((a,r,c),("PASS","PASS","PASS"))
 def test_relative_failure(self):
  base={"decision_score":"1","final_score":"150","adjusted_score":"200","ai_rank":"1","past_performance_score":"55","distance_score":"30","course_shape_score":"5","lap_score":"0","race_shape_score":"0","pace_style_score":"10"}
  low=dict(base,adjusted_score="140",ai_rank="2")
  self.assertEqual(recompute([base,low])[1][2],"FAIL")
if __name__=="__main__":unittest.main()
