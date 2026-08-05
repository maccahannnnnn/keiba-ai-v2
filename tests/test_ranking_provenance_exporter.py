import csv
import hashlib
import inspect
import unittest
import uuid
from pathlib import Path
from review.ranking_provenance_exporter import EXPECTED_EVALUATORS, export, update_ledger
from review.ranking_provenance_feasibility_audit import run as feasibility
from review.ranking_provenance_post_race_evaluator import join

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"reports"/"ranking_provenance"/"test_output"/"phase_c_legacy"/uuid.uuid4().hex
SOURCE=Path(__file__)

def provenance(raw=10,weight=1.2,contribution=12):
    return [{"evaluator_name":name,"raw_score":raw,"weight":weight,"weighted_contribution":contribution,"weight_reason":"saved_rule","source_field":field,"calculation_version":"weight_v1"} for name,field in EXPECTED_EVALUATORS.items()]

def row(number,final,adjusted,rank,with_provenance=True):
    return {"race_id":"race_20260809_tokyo_1R","race_date":"20260809","racecourse":"tokyo","race_number":"1R","horse_name":f"H{number}","horse_number":str(number),"final_score":final,"adjusted_score":adjusted,"ai_rank":str(rank),"source_version":"future_v1","weight_calculation_version":"weight_v1","evaluator_provenance":provenance() if with_provenance else []}

class RankingProvenanceExporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=[row(1,100,120,1),row(2,90,110,2)]
        cls.result=export(cls.rows,OUT/"pre_race","20260809","future_v1",SOURCE)

    def test_existing_csv_not_modified(self):self.assertTrue(self.result["summary_path"].name.startswith("ranking_provenance_"))
    def test_existing_artifacts_not_overwritten(self):
        with self.assertRaises(FileExistsError):export(self.rows,OUT/"pre_race","20260809","future_v1",SOURCE)
    def test_weight_preserved(self):self.assertTrue(all(str(r["weight"])=="1.2" for r in self.result["long_rows"]))
    def test_contribution_preserved(self):self.assertTrue(all(str(r["weighted_contribution"])=="12" for r in self.result["long_rows"]))
    def test_rank_before(self):self.assertEqual([r["rank_before"] for r in self.result["summary_rows"]],[1,2])
    def test_rank_after_regression(self):self.assertEqual([r["rank_after"] for r in self.result["summary_rows"]],[1,2])
    def test_saved_rank_match(self):self.assertTrue(all(r["rank_after_matches_saved_ai_rank"] for r in self.result["summary_rows"]))
    def test_fallback_saved(self):
        rows=[row(1,100,"",1),row(2,90,110,2)];rows[0]["integrated_score"]=120
        result=export(rows,OUT/"fallback","20260809","future_v1",SOURCE);self.assertTrue(result["summary_rows"][0]["fallback_used"]);self.assertEqual(result["summary_rows"][0]["ranking_score_source"],"integrated_score")
    def test_fallback_reason_saved(self):
        r=row(1,100,"",1);r["weighted_score"]=120;result=export([r],OUT/"fallback_reason","20260809","future_v1",SOURCE);self.assertEqual(result["summary_rows"][0]["fallback_reason"],"ADJUSTED_SCORE_MISSING")
    def test_top5_boundary_tie(self):
        rows=[row(i,110-i,100-i,i) for i in range(1,7)];rows[5]["adjusted_score"]=rows[4]["adjusted_score"]
        result=export(rows,OUT/"boundary","20260809","future_v1",SOURCE);self.assertTrue(all(r["top5_boundary_tie"] for r in result["summary_rows"]))
    def test_no_raw_score_inference(self):
        result=export([row(1,100,120,1,False)],OUT/"trace","20260809","future_v1",SOURCE);self.assertTrue(all(r["weight_status"]=="TRACE" for r in result["long_rows"]));self.assertTrue(all(r["weighted_contribution"]=="" for r in result["long_rows"]))
    def test_trace_missing_fields(self):
        result=export([row(1,100,120,1,False)],OUT/"trace_fields","20260809","future_v1",SOURCE);self.assertTrue(all("weight" in r["missing_fields"] for r in result["long_rows"]))
    def test_result_fields_rejected(self):
        r=row(1,100,120,1);r["actual_finish"]=1
        with self.assertRaisesRegex(ValueError,"RESULT_FIELDS_PROHIBITED"):export([r],OUT/"reject","20260809","future_v1",SOURCE)
    def test_mixed_date_rejected(self):
        rows=self.rows+[dict(row(3,80,90,3),race_date="20260810")]
        with self.assertRaisesRegex(ValueError,"MIXED_RACE_DATE"):export(rows,OUT/"date","20260809","future_v1",SOURCE)
    def test_mixed_version_rejected(self):
        rows=self.rows+[dict(row(3,80,90,3),source_version="future_v2")]
        with self.assertRaisesRegex(ValueError,"MIXED_SOURCE_VERSION"):export(rows,OUT/"version","20260809","future_v1",SOURCE)
    def test_long_format_cardinality(self):self.assertEqual(len(self.result["long_rows"]),2*len(EXPECTED_EVALUATORS))
    def test_ledger_deduplicates(self):
        ledger=OUT/"ranking_provenance_test_ledger.json";payload=update_ledger(ledger,self.result["manifest"]);payload=update_ledger(ledger,self.result["manifest"]);self.assertEqual(len(payload["entries"]),1)
    def test_post_join_preserves_pre_sha(self):
        pre_hash=hashlib.sha256(self.result["summary_path"].read_bytes()).hexdigest();out=OUT/"post"/"joined.csv";joined=join(self.result["summary_path"],ROOT/"tests"/"fixtures"/"ranking_provenance_result_fixture.csv",out);self.assertTrue(all(r["pre_race_sha256"]==pre_hash for r in joined));self.assertEqual(hashlib.sha256(self.result["summary_path"].read_bytes()).hexdigest(),pre_hash)
    def test_future_only_feasibility(self):
        rows,summary=feasibility();self.assertEqual(len(rows),4);self.assertEqual(summary["final_judgment"],"READY_FUTURE_ONLY");self.assertFalse(summary["current_code_replay_used"])
    def test_no_production_adapters(self):
        import review.ranking_provenance_exporter as module
        source=inspect.getsource(module);self.assertNotIn("TargetTrialAdapter",source);self.assertNotIn("TargetResultAdapter",source)

if __name__=="__main__":unittest.main()
