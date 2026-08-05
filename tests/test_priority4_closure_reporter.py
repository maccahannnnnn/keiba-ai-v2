import unittest
from review.priority4_closure_reporter import DATES,canonical_hash
class ReporterTests(unittest.TestCase):
 def test_target_dates_and_stable_hash(self):
  self.assertEqual(len(DATES),8)
  a=[{"race_id":"b","horse_number":"2"},{"race_id":"a","horse_number":"1"}]
  self.assertEqual(canonical_hash(a,("race_id","horse_number")),canonical_hash(list(reversed(a)),("race_id","horse_number")))
if __name__=="__main__": unittest.main()
