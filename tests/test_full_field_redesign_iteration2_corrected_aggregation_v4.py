from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from review import full_field_redesign_iteration2_corrected_aggregation_v4 as v4

BOX=ROOT/".tmp"/"iteration2_v4_synthetic"
def digest(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

class V4Synthetic(unittest.TestCase):
    def setUp(self):
        BOX.mkdir(parents=True,exist_ok=True);self.box=BOX/self.id().split(".")[-1];shutil.rmtree(self.box,ignore_errors=True);self.box.mkdir()
        self.old={name:getattr(v4,name) for name in ("EXPECTED_PREREG","EXPECTED_RATIFICATION","EXPECTED_RUN","EXPECTED_ITER1_ARTIFACT_HASH_INDEX_SHA","EXPECTED_ITER1_BUDGET_SHA","EXPECTED_ITER1_PRIMARY_SELECTION_SHA")}
    def tearDown(self):
        for name,value in self.old.items():setattr(v4,name,value)
        shutil.rmtree(self.box,ignore_errors=True)
    def make_paths(self):
        root=self.box/"repo"; inp=root/"inputs"; out=root/"out"; tmp=root/"tmp"; failures=root/"fail"; results=root/"data"/"raw"/"target"/"daily_result_list"; it=root/"iter1"; pre=root/"pre"; docs=root/"docs"
        for p in (inp,results,it,pre,docs):p.mkdir(parents=True,exist_ok=True)
        dates=[]
        for month in range(3,10):
            for day in range(1,10):dates.append(f"20260{month}{day:02}")
        dates=dates[:62]
        rows=[]
        for date in dates:
            race=f"race_{date}_tokyo_1R"
            for no,p in ((1,1.2),(2,.9),(3,.9)):
                rows.append({"date":date,"month":date[:6],"race_id":race,"horse_number":no,"current_buy":no==1,"shadow_ai_rank":no,"adjusted_score":4-no,"past_performance":4-no,"p_v5":4-no,"p_hgb":p,"p_pl":p/3})
            base=[date+"00000000","東京","1","synthetic","","","","","","3","",""]
            with (results/f"馬番順着順_{date}.csv").open("w",encoding="cp932",newline="") as h:csv.writer(h).writerow(base+["1","4","5"])
            with (results/f"着順馬番_{date}.csv").open("w",encoding="cp932",newline="") as h:csv.writer(h).writerow(base+["1","2","3"])
        payload=json.dumps({"rows":rows},ensure_ascii=False).encode();(inp/"run_a_frozen.json").write_bytes(payload);(inp/"run_b_frozen.json").write_bytes(payload)
        prereg=docs/"p";rat=docs/"r";prereg.write_text("p");rat.write_text("r")
        with (it/"daily_current_buy_budget.csv").open("w",encoding="utf-8-sig",newline="") as h:w=csv.DictWriter(h,fieldnames=["date","budget_n"]);w.writeheader();w.writerows({"date":d,"budget_n":1} for d in dates)
        fields=["date","race_id","horse_number","comparator","score","global_rank"]
        with (it/"primary_global_selected_horses.csv").open("w",encoding="utf-8-sig",newline="") as h:
            w=csv.DictWriter(h,fieldnames=fields);w.writeheader()
            for c in ("CURRENT","PP_ONLY_DETERMINISTIC","V5_FULL_FIELD_TRAINED","V5_TOP5_TRAINED"):
                w.writerows({"date":d,"race_id":f"race_{d}_tokyo_1R","horse_number":1,"comparator":c,"score":1,"global_rank":1} for d in dates)
        for n in range(31):
            d=pre/f"run_c_{n:02}";d.mkdir();generated=[]
            for date in dates[n*2:n*2+2]:generated.append({"date":date,"values":{"post_rc1_decision":"BUY"}})
            (d/"runtime_pre_only_output.json").write_text(json.dumps({"generated_rows":generated}))
        index=it/"artifact_hashes.json";index.write_text(json.dumps({"artifacts":{}}))
        v4.EXPECTED_PREREG=digest(prereg);v4.EXPECTED_RATIFICATION=digest(rat);v4.EXPECTED_RUN=digest(inp/"run_a_frozen.json");v4.EXPECTED_ITER1_ARTIFACT_HASH_INDEX_SHA=digest(index);v4.EXPECTED_ITER1_BUDGET_SHA=digest(it/"daily_current_buy_budget.csv");v4.EXPECTED_ITER1_PRIMARY_SELECTION_SHA=digest(it/"primary_global_selected_horses.csv")
        return v4.Paths(root=root,input=inp,output=out,temporary=tmp,failures=failures,results=results,iter1=it,pre=pre,prereg=prereg,ratification=rat)
    def test_real_canonical_loader_uses_synthetic_official_csv(self):
        paths=self.make_paths(); rows=v4.load_rows(paths)[:3];labels=v4.canonical_labels(rows,paths)
        self.assertTrue(labels[v4.ident(rows[0])]["actual_top3"]);self.assertFalse(labels[v4.ident(rows[1])]["actual_top3"])
    def test_prepare_then_same_canonical_execute_path_writes_all_audits(self):
        paths=self.make_paths(); manifest=v4.prepare(paths);result=v4.execute_after_authorization(manifest["manifest_sha256"],paths)
        self.assertIn(result["selected_candidate"],{"NONE","PLACKETT_LUCE","HIST_GRADIENT_BOOSTING"})
        for name in ("model_selection_decision.json","rank1_metrics.csv","calibration_metrics.csv","paired_bootstrap.json","candidate_gate.json","summary.md","artifact_hashes.json"):
            self.assertTrue((paths.output/name).is_file(),name)
        self.assertFalse(paths.temporary.exists())
    def test_model_selection_all_human_ratified_branches(self):
        fail={"candidate_gate_pass":False};ok={"candidate_gate_pass":True};bad={"ci_lower_95":0};good={"ci_lower_95":.001}
        self.assertEqual(v4.select_candidate(fail,fail,bad,False),"NONE");self.assertEqual(v4.select_candidate(ok,fail,bad,False),"PLACKETT_LUCE");self.assertEqual(v4.select_candidate(fail,ok,bad,False),"HIST_GRADIENT_BOOSTING");self.assertEqual(v4.select_candidate(ok,ok,bad,True),"PLACKETT_LUCE");self.assertEqual(v4.select_candidate(ok,ok,good,True),"HIST_GRADIENT_BOOSTING");self.assertEqual(v4.select_candidate(ok,ok,good,False),"PLACKETT_LUCE")
    def test_shadow_rank_is_fail_closed(self):
        with self.assertRaisesRegex(v4.Stop,"STOP_V5_FULL_SHADOW_RANK_MISSING"):v4.shadow_rank({"shadow_ai_rank":None})
        with self.assertRaisesRegex(v4.Stop,"STOP_V5_FULL_SHADOW_RANK_MISSING"):v4.shadow_rank({})
    def test_actual_canonical_parser_wrong_date_venue_and_race_stop(self):
        paths=self.make_paths(); row=v4.load_rows(paths)[0]
        bad={**row,"date":"20269999"}
        with self.assertRaisesRegex(v4.Stop,"STOP_RESULT_DATE_MISMATCH"):v4.canonical_labels([bad],paths)
        bad={**row,"race_id":row["race_id"].replace("tokyo","unknown")}
        with self.assertRaisesRegex(v4.Stop,"STOP_RESULT_VENUE_MISMATCH"):v4.canonical_labels([bad],paths)
        bad={**row,"race_id":row["race_id"].replace("1R","2R")}
        with self.assertRaisesRegex(v4.Stop,"STOP_RESULT_RACE_MISMATCH"):v4.canonical_labels([bad],paths)
    def test_prepare_is_one_shot_and_execute_requires_approved_sha(self):
        paths=self.make_paths();v4.prepare(paths)
        with self.assertRaisesRegex(v4.Stop,"STOP_RESULT_SOURCE_MANIFEST_ALREADY_EXISTS"):v4.prepare(paths)
        with self.assertRaisesRegex(v4.Stop,"STOP_APPROVED_RESULT_MANIFEST_SHA_REQUIRED"):v4.execute_after_authorization(None,paths)
    def test_rank_tie_and_lexical_daily_tie_are_frozen(self):
        a={"horse_number":1,"shadow_ai_rank":99,"p_v5":.5,"p_hgb":.5,"p_pl":.5,"date":"20260301","race_id":"race_20260301_tokyo_10R"}
        b={**a,"horse_number":9,"shadow_ai_rank":1,"race_id":"race_20260301_tokyo_2R"}
        self.assertLess(v4.rank1_key(b,"V5_FULL_FIELD_TRAINED"),v4.rank1_key(a,"V5_FULL_FIELD_TRAINED"))
        self.assertLess(v4.daily_key(a,"PLACKETT_LUCE"),v4.daily_key(b,"PLACKETT_LUCE"))
    def test_output_audit_values_are_available_outside_gate(self):
        paths=self.make_paths();manifest=v4.prepare(paths);v4.execute_after_authorization(manifest["manifest_sha256"],paths)
        with (paths.output/"rank1_metrics.csv").open(encoding="utf-8-sig",newline="") as h:rank=list(csv.DictReader(h))
        with (paths.output/"calibration_metrics.csv").open(encoding="utf-8-sig",newline="") as h:cal=list(csv.DictReader(h))
        gates=json.loads((paths.output/"candidate_gate.json").read_text(encoding="utf-8"))
        self.assertEqual({x["model"] for x in rank},{"V5_FULL_FIELD_TRAINED","PLACKETT_LUCE","HIST_GRADIENT_BOOSTING"})
        self.assertTrue(any(x["scope"]=="POOLED" for x in cal));self.assertIn("PLACKETT_LUCE",gates)
    def test_direct_budget_mismatch_stops(self):
        paths=self.make_paths();p=next(paths.pre.glob("run_c_*/runtime_pre_only_output.json"));p.write_text(json.dumps({"generated_rows":[]}))
        with self.assertRaisesRegex(v4.Stop,"STOP_DAILY_BUDGET_MISMATCH"):v4.prepare(paths)
    def test_manifest_source_mutation_stops_before_final_promotion(self):
        paths=self.make_paths();manifest=v4.prepare(paths);p=paths.results/"馬番順着順_20260301.csv";p.write_text("changed",encoding="cp932")
        with self.assertRaises(v4.Stop):v4.execute_after_authorization(manifest["manifest_sha256"],paths)
        self.assertFalse(paths.output.exists())
    def test_manifest_date_set_mutation_stops_before_result_loader(self):
        paths=self.make_paths();manifest=v4.prepare(paths); p=paths.input/v4.MANIFEST;value=json.loads(p.read_text(encoding="utf-8"));value["evaluation_dates"]=value["evaluation_dates"][:-1];p.write_text(json.dumps(value),encoding="utf-8");
        with self.assertRaisesRegex(v4.Stop,"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"):v4.execute_after_authorization(manifest["manifest_sha256"],paths)
    def test_failure_audit_created_without_final_output(self):
        paths=self.make_paths();manifest=v4.prepare(paths); (paths.results/"馬番順着順_20260301.csv").write_text("changed",encoding="cp932")
        with self.assertRaises(v4.Stop):v4.execute_after_authorization(manifest["manifest_sha256"],paths)
        self.assertFalse(paths.output.exists());self.assertTrue(any(paths.failures.glob("failure_audit_*.json")))

if __name__=="__main__":unittest.main()
