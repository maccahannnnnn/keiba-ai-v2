import unittest
from review.priority5_phase0_review import finish, stable
class Phase0Tests(unittest.TestCase):
 def test_finish_validity(self): self.assertEqual(finish("0"),0); self.assertEqual(finish("5"),5); self.assertEqual(finish("取消"),0)
 def test_hash_is_order_independent(self):
  a=[{"race_id":"r2"},{"race_id":"r1"}]
  self.assertEqual(stable(a,("race_id",)),stable(list(reversed(a)),("race_id",)))
 def test_fp_boundaries(self):
  severity=lambda f:"NEAR_MISS" if f<=5 else ("MODERATE_MISS" if f<=9 else "SEVERE_MISS")
  self.assertEqual([severity(x) for x in (4,5,6,9,10)], ["NEAR_MISS","NEAR_MISS","MODERATE_MISS","MODERATE_MISS","SEVERE_MISS"])
if __name__=="__main__":unittest.main()
