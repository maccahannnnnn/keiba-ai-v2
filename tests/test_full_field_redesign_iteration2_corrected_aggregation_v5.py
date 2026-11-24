from __future__ import annotations
import json,shutil,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from review import full_field_redesign_iteration2_corrected_aggregation_v4 as v4
from review import full_field_redesign_iteration2_corrected_aggregation_v5 as v5
from tests.test_full_field_redesign_iteration2_corrected_aggregation_v4 import V4Synthetic

class V5Synthetic(V4Synthetic):
    def test_v5_mapping_is_direct_and_distinct(self):
        row={"p_hgb":.19,"p_pl":.81,"p_v5":.5,"adjusted_score":.1,"past_performance":.2,"horse_number":1,"shadow_ai_rank":1,"race_id":"race_20260301_tokyo_1R"}
        self.assertEqual(v5.score(row,"PLACKETT_LUCE"),.19);self.assertEqual(v5.score(row,"HIST_GRADIENT_BOOSTING"),.81)
    def test_v5_pl_sanity_direct(self):
        good=[{"date":"d","race_id":"r","horse_number":n,"p_hgb":1,"p_pl":.2,"p_v5":.2,"adjusted_score":.2,"past_performance":.2,"shadow_ai_rank":n} for n in range(1,4)]
        v5.assert_pl_mass(good);good[0]["p_hgb"]=.9
        with self.assertRaisesRegex(v5.Stop,"STOP_PL_PROBABILITY_SANITY_FAILURE"):v5.assert_pl_mass(good)
    def test_explicit_daily_budget_guard(self):
        rows=[{"date":"d","race_id":"r","horse_number":1,"p_hgb":1,"p_pl":1,"p_v5":1,"adjusted_score":1,"past_performance":1,"shadow_ai_rank":1}]
        with self.assertRaisesRegex(v5.Stop,"STOP_DAILY_BUDGET_EXCEEDS_ELIGIBLE_HORSES"):v5.select_daily(rows,"PLACKETT_LUCE",{"d":2})
    def test_v5_baseline_direct_and_mismatch_pre_result(self):
        paths=self.make_paths();rows=v5.load_rows(paths);budget=v5.budgets(paths);v5.baseline(rows,budget,paths)
        p=paths.iter1/"primary_global_selected_horses.csv";text=p.read_text(encoding="utf-8-sig").replace(",1,CURRENT,",",2,CURRENT,",1);p.write_text(text,encoding="utf-8-sig")
        with self.assertRaisesRegex(v5.Stop,"STOP_BASELINE_SELECTION_CONFORMANCE_FAILURE"):v5.baseline(rows,budget,paths)
    def test_v5_rank_calibration_monthly_and_candidate_gates_direct(self):
        self.assertTrue(v5.rank_guard(.5,.49));self.assertFalse(v5.rank_guard(.5,.489999))
        self.assertTrue(v5.calibration_guard(.2,.2,2,7));self.assertFalse(v5.calibration_guard(.2,.2,3,7));self.assertFalse(v5.calibration_guard(.2,.21,0,7))
        self.assertTrue(v5.monthly_gate(5,7));self.assertFalse(v5.monthly_gate(4,7))
        good=dict(lift=.06,wins=5,current_lower=.001,rank=True,calibration=True,pp_lower=.001);self.assertTrue(v5.candidate_gate(**good)["candidate_gate_pass"])
        for name,value in (("lift",.059),("wins",4),("current_lower",0),("rank",False),("calibration",False),("pp_lower",0)):
            case={**good,name:value};self.assertFalse(v5.candidate_gate(**case)["candidate_gate_pass"])
    def test_v5_top5_reference_is_not_gate_eligible_and_missing_stops(self):
        key=("d","r",1);self.assertEqual(v5.v5_top5_reference([key],{key:{"x":1}}),[{"x":1}])
        with self.assertRaisesRegex(v5.Stop,"STOP_V5_TOP5_REFERENCE_HORSE_MISSING"):v5.v5_top5_reference([key],{})
    def test_v5_integration_writes_audits_and_consistent_manifest_sha(self):
        paths=self.make_paths();manifest=v5.prepare(paths);v5.execute_after_authorization(manifest["manifest_sha256"],paths)
        required=("source_integrity.json","baseline_conformance.json","recovery_audit.json","rank1_metrics.csv","calibration_metrics.csv","paired_bootstrap.json","candidate_gate.json","model_selection_decision.json")
        self.assertTrue(all((paths.output/x).is_file() for x in required))
        source=json.loads((paths.output/"source_integrity.json").read_text(encoding="utf-8"));audit=json.loads((paths.output/"recovery_audit.json").read_text(encoding="utf-8"));self.assertEqual(source["approved_result_manifest_sha256"],audit["APPROVED_RESULT_MANIFEST_SHA256"]);self.assertEqual(source["recovery_role"],"DEVELOPMENT_ONLY_NON_EVIDENTIAL")
    def test_preexisting_temp_is_preserved(self):
        paths=self.make_paths();manifest=v5.prepare(paths);paths.temporary.mkdir();marker=paths.temporary/"DO_NOT_DELETE.txt";marker.write_text("keep")
        with self.assertRaisesRegex(v5.Stop,"STOP_TEMP_OUTPUT_ALREADY_EXISTS"):v5.execute_after_authorization(manifest["manifest_sha256"],paths)
        self.assertTrue(marker.is_file());self.assertEqual(marker.read_text(),"keep")
    def test_failure_audits_do_not_overwrite(self):
        paths=self.make_paths();manifest=v5.prepare(paths);paths.results.joinpath("馬番順着順_20260301.csv").write_text("changed",encoding="cp932")
        for _ in range(2):
            with self.assertRaises(v5.Stop):v5.execute_after_authorization(manifest["manifest_sha256"],paths)
        self.assertGreaterEqual(len(list(paths.failures.glob("failure_audit_*.json"))),2)
    def test_failure_audit_retains_pre_result_snapshot_sha(self):
        paths=self.make_paths();manifest=v5.prepare(paths);paths.results.joinpath("馬番順着順_20260301.csv").write_text("changed",encoding="cp932")
        with self.assertRaises(v5.Stop):v5.execute_after_authorization(manifest["manifest_sha256"],paths)
        audit=next(json.loads(path.read_text(encoding="utf-8")) for path in paths.failures.glob("failure_audit_*.json") if "pre_result_selection_frozen" in path.read_text(encoding="utf-8"))
        self.assertTrue(audit["pre_result_selection_frozen"]);self.assertEqual(len(audit["pre_result_selected_horses_sha256"]),64)
if __name__=="__main__":unittest.main()
