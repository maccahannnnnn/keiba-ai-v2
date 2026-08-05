import unittest
from review.priority5_fp_root_cause_review import classify
class RootCauseTests(unittest.TestCase):
 def test_legacy_trace(self):
  self.assertEqual(classify({"race_date":"20260725"},{})[0],"DATA_QUALITY_OR_TRACE")
 def test_high_confidence_group(self):
  self.assertEqual(classify({"race_date":"20260726"},{})[0],"HIGH_CONFIDENCE_SEVERE_MISS")
 def test_missing_bloodline(self):
  p,s=classify({"race_date":"20260802"},{})
  self.assertEqual(p,"DATA_QUALITY_OR_TRACE");self.assertIn("BLOODLINE_MISSING",s)
if __name__=="__main__":unittest.main()
