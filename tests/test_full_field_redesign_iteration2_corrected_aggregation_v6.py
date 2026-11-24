from __future__ import annotations
import csv,shutil,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from review import full_field_redesign_iteration2_corrected_aggregation_v6 as v6

BOX=ROOT/".tmp"/"iteration2_v6_synthetic"
FIELDS=["date","month","current_pre_buy_count","eligible_horse_count","eligible_race_count"]
class V6Budget(unittest.TestCase):
    def setUp(self):BOX.mkdir(parents=True,exist_ok=True);self.box=BOX/self.id().split(".")[-1];shutil.rmtree(self.box,ignore_errors=True);self.box.mkdir()
    def tearDown(self):shutil.rmtree(self.box,ignore_errors=True)
    def write(self,rows,fields=FIELDS):
        p=self.box/"budget.csv"
        with p.open("w",encoding="utf-8-sig",newline="") as h:w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)
        return p
    def row(self,date="20260301",count="3"):return {"date":date,"month":date[:6],"current_pre_buy_count":count,"eligible_horse_count":"10","eligible_race_count":"1"}
    def test_canonical_header_and_value(self):self.assertEqual(v6.read_budget(self.write([self.row()]))["20260301"],3)
    def test_legacy_only_header_fails_closed(self):
        p=self.write([{"date":"20260301","budget":"3"}], ["date","budget"])
        with self.assertRaisesRegex(v6.Stop,"STOP_BUDGET_COLUMN_CURRENT_PRE_BUY_COUNT_MISSING"):v6.read_budget(p)
    def test_missing_canonical_column_fails(self):
        p=self.write([{"date":"20260301","month":"202603","eligible_horse_count":"10","eligible_race_count":"1"}], ["date","month","eligible_horse_count","eligible_race_count"])
        with self.assertRaisesRegex(v6.Stop,"STOP_BUDGET_COLUMN_CURRENT_PRE_BUY_COUNT_MISSING"):v6.read_budget(p)
    def test_noninteger_and_negative_fail(self):
        for value in ("x","-1"):
            with self.assertRaisesRegex(v6.Stop,"STOP_BUDGET_CURRENT_PRE_BUY_COUNT_INVALID"):v6.read_budget(self.write([self.row(count=value)]))
    def test_duplicate_and_missing_date_guards(self):
        with self.assertRaisesRegex(v6.Stop,"STOP_BUDGET_DUPLICATE_DATE"):v6.read_budget(self.write([self.row(),self.row()]))
        with self.assertRaisesRegex(v6.Stop,"STOP_DAILY_BUDGET_DATE_MISSING"):v6.read_budget(self.write([self.row()]),{"20260301","20260302"})
    def test_exact_vs_mismatch_direct_conformance_semantics(self):
        values=v6.read_budget(self.write([self.row()]),{"20260301"});v6.assert_budget_conformance(values,{"20260301":3})
        with self.assertRaisesRegex(v6.Stop,"STOP_DAILY_BUDGET_MISMATCH"):v6.assert_budget_conformance(values,{"20260301":2})
if __name__=="__main__":unittest.main()
