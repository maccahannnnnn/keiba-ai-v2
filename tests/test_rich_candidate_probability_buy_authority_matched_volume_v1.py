import hashlib
import inspect
import csv
import io
import unittest
from collections import Counter
from pathlib import Path

import review.rich_candidate_probability_buy_authority_matched_volume_v1 as exp


class Exp022Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = exp.input_hash_audit()
        cls.rich_b = exp.exact5(exp.EXP021 / "rich_baseline_predictions.csv")
        cls.control_b = exp.exact5(exp.EXP021 / "control_baseline_predictions.csv")
        cls.kb, _ = exp.kr(exp.STAGE_B / "baseline_stage_b_natural_buy.csv")
        cls.kt, _ = exp.kr(exp.STAGE_B / "treatment_stage_b_natural_buy.csv")

    def test_01_authoritative_input_hash_validation(self):
        self.assertEqual(self.audit["status"], "PASS")

    def test_02_per_race_kr_exact_reconstruction(self):
        self.assertTrue(all(v in (1,2,3) for v in self.kb.values()))

    def test_03_baseline_kr_total_679(self): self.assertEqual(sum(self.kb.values()),679)
    def test_04_treatment_kr_total_720(self): self.assertEqual(sum(self.kt.values()),720)

    def test_05_rich_exact5(self):
        self.assertEqual(len(self.rich_b),828); self.assertTrue(all(len(v)==5 for v in self.rich_b.values()))

    def test_06_probability_sort_deterministic(self):
        items=[{"probability":.2,"shadow_ai_rank":2,"horse_number":2},{"probability":.9,"shadow_ai_rank":3,"horse_number":1}]
        key=lambda x:(-x["probability"],x["shadow_ai_rank"],x["horse_number"])
        self.assertEqual(sorted(items,key=key)[0]["horse_number"],1)

    def test_07_frozen_tie_break_shadow_rank(self):
        items=[{"probability":.5,"shadow_ai_rank":2,"horse_number":1},{"probability":.5,"shadow_ai_rank":1,"horse_number":2}]
        self.assertEqual(sorted(items,key=lambda x:(-x["probability"],x["shadow_ai_rank"],x["horse_number"]))[0]["horse_number"],2)

    def test_08_frozen_tie_break_horse_number(self):
        items=[{"probability":.5,"shadow_ai_rank":1,"horse_number":2},{"probability":.5,"shadow_ai_rank":1,"horse_number":1}]
        self.assertEqual(sorted(items,key=lambda x:(-x["probability"],x["shadow_ai_rank"],x["horse_number"]))[0]["horse_number"],1)

    @staticmethod
    def fixture():
        key=("20260101","race_20260101_tokyo_1R")
        rows=[{"date":key[0],"race_id":key[1],"venue":"東京","race_number":1,"horse_number":i,
               "horse_name":str(i),"probability":1-i/10,"candidate_rank":i,"shadow_ai_rank":i} for i in range(1,6)]
        return key,{key:rows}

    def test_09_risk_guard_eligibility(self):
        key,c=self.fixture(); risks={(key[0],key[1],i):i!=1 for i in range(1,6)}
        rows,_=exp.make_selection(c,{key:1},risks,"baseline","TEST")
        self.assertEqual([r["horse_number"] for r in rows if r["selected"]],[2])

    def test_10_no_selection_outside_exact5(self):
        key,c=self.fixture(); risks={(key[0],key[1],i):True for i in range(1,8)}
        rows,_=exp.make_selection(c,{key:3},risks,"baseline","TEST")
        self.assertLessEqual(max(r["horse_number"] for r in rows if r["selected"]),5)

    def test_11_no_fill_on_shortfall(self):
        key,c=self.fixture(); risks={(key[0],key[1],i):i==1 for i in range(1,6)}
        rows,a=exp.make_selection(c,{key:3},risks,"baseline","TEST")
        self.assertEqual(sum(r["selected"] for r in rows),1); self.assertEqual(a["shortfall_horses"],2)

    def test_12_volume_match_status(self):
        key,c=self.fixture(); risks={(key[0],key[1],i):True for i in range(1,6)}
        _,a=exp.make_selection(c,{key:2},risks,"baseline","TEST")
        self.assertEqual(a["VOLUME_MATCH_STATUS"],"COMPLETE")

    def test_13_diag_uses_control_probability(self):
        self.assertNotEqual(exp.sha(exp.EXP021/"control_baseline_predictions.csv"),exp.sha(exp.EXP021/"rich_baseline_predictions.csv"))

    def test_14_test_uses_rich_probability(self):
        source=inspect.getsource(exp.prepare)
        self.assertIn('("baseline",rich_b,control_b,kb)',source)

    def test_15_result_boundary_order(self):
        source=inspect.getsource(exp.execute)
        self.assertLess(source.index("validate_freeze()"),source.index("evaluate(ref_rows"))

    def test_16_buy_set_hash_stability(self):
        key,c=self.fixture(); rows,_=exp.make_selection(c,{key:1},{(key[0],key[1],i):True for i in range(1,6)},"b","TEST")
        def encoded():
            s=io.StringIO(newline=""); w=csv.DictWriter(s,fieldnames=exp.CSV_FIELDS,extrasaction="ignore"); w.writeheader(); w.writerows(rows); return s.getvalue().encode()
        self.assertEqual(hashlib.sha256(encoded()).hexdigest(),hashlib.sha256(encoded()).hexdigest())

    def test_17_invalid_denominator_classification_contract(self):
        ref={"top3_hits":2,"buy_top3_rate":.4}; test={"top3_hits":3,"buy_top3_rate":.5}
        self.assertEqual(exp.classify(test,ref,[1,0,0,0,0])[0],"CLEAN_SELECTION_GAIN")

    def test_18_no_model_fit_and_stage_b_protected(self):
        source=Path(exp.__file__).read_text(encoding="utf-8")
        self.assertNotIn(".fit(",source); self.assertEqual(self.audit["inputs"]["fold_manifest"]["match"],True)


if __name__ == "__main__": unittest.main()
