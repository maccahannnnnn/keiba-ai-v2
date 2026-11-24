from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from review import full_field_redesign_iteration2_corrected_aggregation_v2 as m

SANDBOX = Path(__file__).resolve().parents[1] / ".tmp"

def row(*, horse=1, race="race_20260301_tokyo_10R", p_hgb=.5, p_pl=.2, p_v5=.3, adjusted=10., pp=9., shadow=1):
    return {"date":"20260301","month":"202603","race_id":race,"venue":"東京","race_number":10,"horse_number":horse,"current_buy":True,"shadow_ai_rank":shadow,"adjusted_score":adjusted,"past_performance":pp,"p_v5":p_v5,"p_pl":p_pl,"p_hgb":p_hgb}

class V2SyntheticTest(unittest.TestCase):
    def test_01_model_mapping_and_bad_pl_mass(self):
        r=row(p_hgb=.9,p_pl=.1); self.assertEqual(m.score(r,"CORRECTED_PLACKETT_LUCE"),.9); self.assertEqual(m.score(r,"CORRECTED_HIST_GRADIENT_BOOSTING"),.1)
        with self.assertRaisesRegex(m.Stop,"STOP_PL_PROBABILITY_SANITY_FAILURE"): m.assert_pl_mass([r])
    def test_02_tiebreak_ignores_shadow_rank(self):
        a=row(horse=9,race="race_20260301_tokyo_10R",shadow=99);b=row(horse=1,race="race_20260301_tokyo_10R",shadow=1)
        self.assertEqual(m.select_daily([a,b],"CORRECTED_PLACKETT_LUCE",{"20260301":2})["20260301"],[b,a])
    def test_03_daily_top_n(self):
        rs=[row(horse=1,p_hgb=.1),row(horse=2,p_hgb=.8),row(horse=3,p_hgb=.7)]
        self.assertEqual([x["horse_number"] for x in m.select_daily(rs,"CORRECTED_PLACKETT_LUCE",{"20260301":2})["20260301"]],[2,3])
    def test_04_common_rank1_uses_full_field_and_excludes_invalid(self):
        a=row(horse=1,p_hgb=.1,p_pl=.1,p_v5=.1); b=row(horse=2,p_hgb=.9,p_pl=.8,p_v5=.7); c=row(horse=3,race="race_20260301_tokyo_11R",p_hgb=.9,p_pl=.8,p_v5=.7)
        labels={m.ident(a):{"valid_result":True},m.ident(b):{"valid_result":True},m.ident(c):{"valid_result":False}}
        out=m.full_race_rank1([a,b,c],labels)
        self.assertEqual(out["CORRECTED_PLACKETT_LUCE"]["rows"][0]["horse_number"],2);self.assertEqual(len(out["CORRECTED_PLACKETT_LUCE"]["common_races"]),1)
    def test_05_rank1_guard_boundary(self): self.assertTrue(m.rank_guard(.50,.49));self.assertFalse(m.rank_guard(.50,.489999))
    def test_06_monthly_5_of_7(self): self.assertTrue(m.monthly_rule(5,7));self.assertFalse(m.monthly_rule(4,7))
    def test_07_calibration_worse_months(self): self.assertTrue(m.calibration_guard(.2,.2,2,7));self.assertFalse(m.calibration_guard(.2,.2,3,7))
    def test_08_candidate_all_pass_and_each_condition_fail(self):
        args=dict(lift=.06,wins=5,boot_current=.01,rank=True,cal=True,boot_pp=.01,name="CORRECTED_PLACKETT_LUCE")
        self.assertEqual(m.gate(**args)["status"],"PASS")
        for field,bad in (("lift",.059),("wins",4),("boot_current",0),("rank",False),("cal",False),("boot_pp",0)):
            trial={**args,field:bad};self.assertEqual(m.gate(**trial)["status"],"FAIL")
    def test_09_both_pass_defaults_pl(self):
        g={"status":"PASS"};self.assertEqual(m.choose(g,g,.0,True),"PLACKETT_LUCE")
    def test_10_hgb_minus_pl_direction(self):
        g={"status":"PASS"};self.assertEqual(m.choose(g,g,.001,True),"HIST_GRADIENT_BOOSTING");self.assertEqual(m.choose(g,g,-.001,True),"PLACKETT_LUCE")
    def test_11_v5_top5_reference_only(self):
        with self.assertRaisesRegex(m.Stop,"STOP_V5_TOP5_GATE_FORBIDDEN"):m.gate(lift=1,wins=7,boot_current=1,rank=True,cal=True,boot_pp=1,name="V5_TOP5_TRAINED")
    def test_12_output_root_exists(self):
        SANDBOX.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SANDBOX) as d:
            old=m.OUT;m.OUT=Path(d)
            try:
                with self.assertRaisesRegex(m.Stop,"STOP_OUTPUT_ROOT_ALREADY_EXISTS"):m.execute_after_authorization()
            finally:m.OUT=old
    def test_13_pre_result_sha_failure_before_loader(self):
        old_prepare,old_out,old_loader=m.prepare,m.OUT,m.canonical_result_loader;calls=[];m.OUT=SANDBOX/"v2_nonexistent_output"
        m.prepare=lambda:(_ for _ in ()).throw(m.Stop("STOP_FROZEN_SOURCE_SHA_MISMATCH"))
        m.canonical_result_loader=lambda _: calls.append("called")
        try:
            with self.assertRaisesRegex(m.Stop,"STOP_FROZEN_SOURCE_SHA_MISMATCH"):m.execute_after_authorization()
            self.assertEqual(calls,[])
        finally:m.prepare, m.OUT, m.canonical_result_loader=old_prepare,old_out,old_loader
    def test_14_daily_budget_direct_match_and_mismatch(self):
        old_a,old_b=m.load_budget,m.recompute_pre_buy_budget;m.load_budget=lambda:{"x":1};m.recompute_pre_buy_budget=lambda:{"x":1}
        try:
            self.assertEqual(m.direct_budget_conformance(),{"x":1});m.recompute_pre_buy_budget=lambda:{"x":2}
            with self.assertRaisesRegex(m.Stop,"STOP_DAILY_BUDGET_MISMATCH"):m.direct_budget_conformance()
        finally:m.load_budget,m.recompute_pre_buy_budget=old_a,old_b
    def test_15_baseline_selection_mismatch(self):
        old=m.read_iter1_selection;m.read_iter1_selection=lambda:{"CURRENT":set(),"PP_ONLY_DETERMINISTIC":set(),"V5_FULL_FIELD_TRAINED":set()}
        try:
            with self.assertRaisesRegex(m.Stop,"STOP_BASELINE_SELECTION_CONFORMANCE_FAILURE"):m.baseline_conformance([row()],{"20260301":1})
        finally:m.read_iter1_selection=old
    def test_16_result_identity_mismatch_before_parse(self):
        SANDBOX.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SANDBOX) as d:
            root=Path(d); names=["馬番順着順_20260301.csv","着順馬番_20260301.csv"]
            for name in names:(root/name).write_bytes(b"x")
            manifest={"PERFORMANCE_ROWS_PARSED":False,"canonical_result_loader_identifier":m.RESULT_LOADER_ID,"sources":[{"filename":n,"path":n,"byte_size":1,"sha256":"bad"} for n in names]}; p=root/"manifest.json";p.write_text(json.dumps(manifest),encoding="utf-8")
            old=m.ROOT;m.ROOT=root
            try:
                with self.assertRaisesRegex(m.Stop,"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"):m.verify_result_identity(p,{"20260301"})
            finally:m.ROOT=old
    def test_17_pre_result_selection_freeze_before_loader(self):
        SANDBOX.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SANDBOX) as d:
            calls=[];r=row();sels={n:{"20260301":[r]} for n in m.ALL};top={m.ident(r):{"score":.1,"global_rank":1}};output=Path(d)/"out"
            def loader(_):calls.append((output/"pre_result_selected_horses.csv").is_file());return {}
            m.freeze_selection_before_result_loader(output,sels,top,loader,[r]);self.assertEqual(calls,[True])

if __name__=="__main__":unittest.main()
