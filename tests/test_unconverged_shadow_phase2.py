import unittest
from pathlib import Path
from review.unconverged_shadow_phase2 import FEATURE_FLAG_ENABLED,GUARDS,by_race,metrics,read_latest
class Phase2Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.groups=by_race(read_latest(Path("reports/unconverged_primary_trace_latest_repaired_v1.csv")))
 def test_flag_fixed_off_and_latest_only(self):
  self.assertFalse(FEATURE_FLAG_ENABLED);self.assertEqual(len(self.groups),3)
  self.assertTrue(all(r.startswith("race_20260802") for r in self.groups))
 def test_expected_metrics(self):
  got={n:metrics(n,self.groups,f) for n,f in GUARDS.items()}
  self.assertEqual((got["MULTI_GATE_SUPPORT_FLOOR"]["fn_improvement"],got["MULTI_GATE_SUPPORT_FLOOR"]["fp_increase"],got["MULTI_GATE_SUPPORT_FLOOR"]["roi"]),(2,7,-5))
  self.assertEqual((got["TOP_CLUSTER_DUAL_SEPARATION"]["fn_improvement"],got["TOP_CLUSTER_DUAL_SEPARATION"]["fp_increase"]),(1,2))
  self.assertEqual((got["TRACE_COMPLETENESS_AND_RACE_SUPPORT"]["fn_improvement"],got["TRACE_COMPLETENESS_AND_RACE_SUPPORT"]["fp_increase"]),(2,7))
 def test_guard_source_does_not_name_result_fields(self):
  import inspect
  for fn in GUARDS.values():
   source=inspect.getsource(fn)
   self.assertNotIn("actual_top3",source);self.assertNotIn("finish_position",source)
if __name__=="__main__":unittest.main()
