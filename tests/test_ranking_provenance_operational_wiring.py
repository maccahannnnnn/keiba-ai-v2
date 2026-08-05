import json
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from evaluation.trial_batch_runner import TrialBatchRunner
from evaluators.score_weight_evaluator import ScoreWeightEvaluator
from review.diagnostic_safety_validator import snapshot, validate


def rows():
    out=[];evaluator=ScoreWeightEvaluator()
    for n in range(1,7):
        row={key:n+i for i,key in enumerate(evaluator.SCORE_KEYS)}
        row.update({"horse_name":f"Horse {n}","horse_number":str(n),"final_score":100-n,"adjusted_score":110-n,"decision_score":70-n,"ai_rank":n,"decision":"BUY" if n==1 else "PASS","confidence_level":"HIGH","race_state":"OPEN"})
        result=evaluator.evaluate(row);row.update({key:result[key] for key in ("evaluator_provenance","score_weight_provenance_version","weight_calculation_version")});out.append(row)
    return out


class FakeAdapter:
    def __init__(self,payload):self.payload=payload;self.calls=0
    def run(self,*args):self.calls+=1;return self.payload


class OperationalWiringTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]/"reports"/"ranking_provenance"/"test_output"/"operational_wiring"/uuid.uuid4().hex;self.root.mkdir(parents=True);self.entry=self.root/"entry.csv";self.horses=self.root/"horses.csv";self.entry.write_text("fixture\n",encoding="utf-8");self.horses.write_text("fixture\n",encoding="utf-8")
        self.payload={"race_date":"20260816","ranked_results":rows(),"race_decision":"PLAY","race_confidence":"HIGH","review_result":{"status":"SAVED"}}
        self.runner=TrialBatchRunner(self.root,self.root);self.runner.adapter=FakeAdapter(self.payload)
    def execute(self,flag):
        with patch.dict(os.environ,{"RANKING_PROVENANCE_EXPORT_ENABLED":flag},clear=False):
            old=Path.cwd()
            os.chdir(self.root)
            try:return self.runner.run_single_race("race_20260816_tokyo_1R",self.entry,self.horses)
            finally:os.chdir(old)
    def test_off_writer_not_executed(self):self.assertEqual(self.execute("OFF")["ranking_provenance_export"]["status"],"DISABLED")
    def test_off_creates_no_reports(self):self.execute("OFF");self.assertFalse((self.root/"reports").exists())
    def test_on_writer_executes(self):self.assertEqual(self.execute("ON")["ranking_provenance_export"]["status"],"COMPLETE")
    def test_adapter_called_once(self):self.execute("ON");self.assertEqual(self.runner.adapter.calls,1)
    def test_source_created(self):self.execute("ON");self.assertEqual(len(list((self.root/"reports/ranking_provenance/source").glob("*.json"))),1)
    def test_source_has_nine_evaluators(self):
        self.execute("ON");data=json.loads(next((self.root/"reports/ranking_provenance/source").glob("*.json")).read_text(encoding="utf-8"));self.assertTrue(all(len(r["evaluator_provenance"])==9 for r in data["records"]))
    def test_source_has_complete(self):
        self.execute("ON");data=json.loads(next((self.root/"reports/ranking_provenance/source").glob("*.json")).read_text(encoding="utf-8"));self.assertTrue(any(x["weight_status"]=="COMPLETE" for r in data["records"] for x in r["evaluator_provenance"]))
    def test_not_all_trace(self):
        result=self.execute("ON");manifest=json.loads(Path(result["ranking_provenance_export"]["pre_manifest"]).read_text(encoding="utf-8"));self.assertLess(manifest["trace_count"],manifest["horse_count"]*9)
    def test_pre_export_created(self):self.assertTrue(Path(self.execute("ON")["ranking_provenance_export"]["pre_manifest"]).exists())
    def test_ledger_pre_registered(self):
        self.execute("ON");data=json.loads((self.root/"reports/ranking_provenance/ranking_provenance_ledger_v1.json").read_text(encoding="utf-8"));self.assertEqual(data["entries"][0]["pre_race_status"],"PRE_RACE_COMPLETE")
    def test_ledger_post_pending(self):
        self.execute("ON");data=json.loads((self.root/"reports/ranking_provenance/ranking_provenance_ledger_v1.json").read_text(encoding="utf-8"));self.assertEqual(data["entries"][0]["post_race_status"],"POST_RACE_PENDING")
    def test_duplicate_is_skipped(self):self.execute("ON");self.assertEqual(self.execute("ON")["ranking_provenance_export"]["status"],"SKIPPED_DUPLICATE")
    def test_result_fields_not_in_source(self):
        self.execute("ON");text=next((self.root/"reports/ranking_provenance/source").glob("*.json")).read_text(encoding="utf-8");self.assertNotIn("actual_finish",text)
    def test_source_declares_no_result_input(self):
        self.execute("ON");data=json.loads(next((self.root/"reports/ranking_provenance/source").glob("*.json")).read_text(encoding="utf-8"));self.assertEqual(data["result_data_used_as_evaluation_input"],"NO")
    def test_exact_horse_name_join(self):self.execute("ON");self.assertEqual(self.payload["ranked_results"][0]["horse_name"],"Horse 1")
    def test_horse_number_required(self):
        del self.payload["ranked_results"][0]["horse_number"];result=self.execute("ON");manifest=json.loads(Path(result["ranking_provenance_export"]["pre_manifest"]).read_text(encoding="utf-8"));self.assertGreaterEqual(manifest["trace_count"],9)
    def test_final_score_zero_delta(self):
        before=[r["final_score"] for r in self.payload["ranked_results"]];self.execute("ON");self.assertEqual(before,[r["final_score"] for r in self.payload["ranked_results"]])
    def test_adjusted_score_zero_delta(self):
        before=[r["adjusted_score"] for r in self.payload["ranked_results"]];self.execute("ON");self.assertEqual(before,[r["adjusted_score"] for r in self.payload["ranked_results"]])
    def test_rank_zero_delta(self):
        before=[r["ai_rank"] for r in self.payload["ranked_results"]];self.execute("ON");self.assertEqual(before,[r["ai_rank"] for r in self.payload["ranked_results"]])
    def test_buy_zero_delta(self):
        before=[r["decision"] for r in self.payload["ranked_results"]];self.execute("ON");self.assertEqual(before,[r["decision"] for r in self.payload["ranked_results"]])
    def test_race_decision_zero_delta(self):self.execute("ON");self.assertEqual(self.payload["race_decision"],"PLAY")
    def test_confidence_zero_delta(self):self.execute("ON");self.assertEqual(self.payload["race_confidence"],"HIGH")
    def test_review_zero_delta(self):
        before=dict(self.payload["review_result"]);self.execute("ON");self.assertEqual(before,self.payload["review_result"])
    def test_export_failure_keeps_production_result(self):
        self.payload["ranked_results"]=[];result=self.execute("ON");self.assertEqual(result["status"],"executed");self.assertEqual(result["ranking_provenance_export"]["status"],"EXPORT_FAILED")
    def test_failure_records_hold(self):
        self.payload["ranked_results"]=[];result=self.execute("ON");self.assertIn("HOLD",result["ranking_provenance_export"]["operational_action"])
    def test_post_does_not_call_writer(self):self.assertNotIn("write_weight_source",Path("review/ranking_provenance_post_race_evaluator.py").read_text(encoding="utf-8"))
    def test_single_production_caller(self):self.assertEqual(validate(before_hashes=snapshot())["production_orchestration_caller_count"],1)
    def test_safety_pass(self):self.assertEqual(validate(before_hashes=snapshot())["status"],"PASS")


if __name__=="__main__":unittest.main()
