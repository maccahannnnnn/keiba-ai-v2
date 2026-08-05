import csv
import json
import unittest
import uuid
from pathlib import Path

from evaluators.score_weight_evaluator import ScoreWeightEvaluator
from review.ranking_provenance_exporter import export, write_weight_source
from review.ranking_provenance_ledger import register_pre
from review.ranking_provenance_post_race_evaluator import join

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"reports"/"ranking_provenance"/"test_output"/"phase_c1"/uuid.uuid4().hex
SOURCE=Path(__file__)


def horse(race,n,count=7):
    scores={key:n+index for index,key in enumerate(ScoreWeightEvaluator.SCORE_KEYS)}
    return {**scores,"race_id":race,"race_date":"20260809","racecourse":"tokyo","race_number":race.rsplit("_",1)[-1],"horse_name":f"{race}-H{n}","horse_number":str(n),"final_score":100-n,"adjusted_score":120-n,"ai_rank":str(n),"source_version":"fixture_v1","pipeline_version":"ranking_provenance_v1"}


class RankingUpstreamProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evaluator=ScoreWeightEvaluator();cls.rows=[]
        for race,count in (("race_20260809_tokyo_1R",7),("race_20260809_tokyo_2R",6),("race_20260809_tokyo_3R",8)):
            for n in range(1,count+1):
                row=horse(race,n);result=evaluator.evaluate(row)
                row.update({key:result[key] for key in ("evaluator_provenance","score_weight_provenance_version","weight_calculation_version")});cls.rows.append(row)
        cls.rows[4]["adjusted_score"]=cls.rows[5]["adjusted_score"]
        source_rows=cls.rows[:-1]
        expected_source=OUT/"source"/"ranking_weight_source_20260809_batch_swp_v1.json"
        expected_source.unlink(missing_ok=True)
        cls.source=write_weight_source(source_rows,OUT,"20260809","fixture_v1",SOURCE)
        cls.result=export(cls.rows,OUT/"pre","20260809","fixture_v1",SOURCE,provenance_source_file=cls.source)

    def test_swp_version(self):self.assertEqual(self.rows[0]["score_weight_provenance_version"],"SWP_V1")
    def test_nine_evaluators(self):self.assertEqual(len(self.rows[0]["evaluator_provenance"]),9)
    def test_raw_is_copied(self):self.assertEqual(self.rows[0]["evaluator_provenance"][0]["raw_score"],1.0)
    def test_weight_is_copied(self):self.assertEqual(self.rows[0]["evaluator_provenance"][0]["weight"],1.0)
    def test_contribution_is_copied(self):self.assertEqual(self.rows[0]["evaluator_provenance"][0]["weighted_contribution"],1.0)
    def test_unknown_existing_logic_version(self):self.assertEqual(self.rows[0]["weight_calculation_version"],"UNKNOWN_EXISTING_LOGIC")
    def test_reason_not_invented(self):self.assertEqual(self.rows[0]["evaluator_provenance"][0]["weight_reason"],"")
    def test_reason_status(self):self.assertEqual(self.rows[0]["evaluator_provenance"][0]["weight_reason_status"],"NOT_EXPOSED")
    def test_missing_raw_trace(self):
        result=ScoreWeightEvaluator().evaluate({})
        self.assertTrue(all(x["weight_status"]=="TRACE" and x["raw_score"]=="" for x in result["evaluator_provenance"]))
    def test_missing_raw_not_zero_inferred(self):self.assertNotEqual(ScoreWeightEvaluator().evaluate({})["evaluator_provenance"][0]["raw_score"],0)
    def test_existing_weighted_score_formula(self):
        result=ScoreWeightEvaluator().evaluate(self.rows[0]);self.assertEqual(result["weighted_score"],sum(x["weighted_value"] for x in result["weighted_score_breakdown"].values()))
    def test_source_artifact_exists(self):self.assertTrue(self.source.exists())
    def test_source_record_count(self):self.assertEqual(len(json.loads(self.source.read_text(encoding="utf-8"))["records"]),20)
    def test_three_races(self):self.assertEqual(self.result["manifest"]["race_count"],3)
    def test_different_horse_counts(self):self.assertEqual(self.result["manifest"]["horse_count"],21)
    def test_missing_join_trace(self):self.assertTrue(all(x["reason_code"]=="PROVENANCE_SOURCE_NOT_FOUND" for x in self.result["long_rows"][-9:]))
    def test_no_missing_join_inference(self):self.assertTrue(all(x["weight"]=="" for x in self.result["long_rows"][-9:]))
    def test_top5_tie(self):self.assertGreater(self.result["manifest"]["top5_boundary_tie_count"],0)
    def test_result_data_not_used(self):self.assertEqual(self.result["manifest"]["result_data_used_as_evaluation_input"],"NO")
    def test_mixed_source_date_rejected(self):
        payload=json.loads(self.source.read_text(encoding="utf-8"));payload["records"][0]["race_date"]="20260810";path=OUT/"bad_date.json";path.write_text(json.dumps(payload),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"MIXED_PROVENANCE_SOURCE_DATE"):export(self.rows,OUT/"bad","20260809","fixture_v1",SOURCE,provenance_source_file=path)
    def test_source_version_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError,"SOURCE_VERSION_MISMATCH"):export(self.rows,OUT/"bad_version","20260809","other",SOURCE,provenance_source_file=self.source)
    def test_pipeline_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError,"PIPELINE_VERSION_MISMATCH"):export(self.rows,OUT/"bad_pipe","20260809","fixture_v1",SOURCE,pipeline_version="other",provenance_source_file=self.source)
    def test_pre_ledger_states(self):
        ledger=OUT/"ledger.json";ledger.unlink(missing_ok=True);payload=register_pre(ledger,self.result["manifest"]);self.assertTrue(all(x["pre_race_status"]=="PRE_RACE_COMPLETE" and x["post_race_status"]=="POST_RACE_PENDING" for x in payload["entries"]))
    def test_ledger_deduplicates(self):
        ledger=OUT/"dedupe.json";ledger.unlink(missing_ok=True);register_pre(ledger,self.result["manifest"]);payload=register_pre(ledger,self.result["manifest"]);self.assertEqual(len(payload["entries"]),3)
    def test_post_evaluator_completes_ledger(self):
        ledger=OUT/"post_ledger.json";ledger.unlink(missing_ok=True);register_pre(ledger,self.result["manifest"]);results=OUT/"results.csv"
        with results.open("w",encoding="utf-8-sig",newline="") as h:
            w=csv.DictWriter(h,fieldnames=["race_id","horse_number","actual_finish"]);w.writeheader();w.writerows({"race_id":r["race_id"],"horse_number":r["horse_number"],"actual_finish":1} for r in self.rows)
        join(self.result["summary_path"],results,OUT/"post.csv",ledger);payload=json.loads(ledger.read_text(encoding="utf-8"));self.assertTrue(all(x["post_race_status"]=="POST_RACE_COMPLETE" and x["post_race_sha256"] for x in payload["entries"]))
    def test_post_failure_updates_ledger(self):
        ledger=OUT/"fail_ledger.json";ledger.unlink(missing_ok=True);register_pre(ledger,self.result["manifest"])
        with self.assertRaises(FileNotFoundError):join(self.result["summary_path"],OUT/"absent.csv",OUT/"never.csv",ledger)
        payload=json.loads(ledger.read_text(encoding="utf-8"));self.assertTrue(all(x["post_race_status"]=="POST_RACE_FAILED" for x in payload["entries"]))
    def test_pre_sha_saved(self):
        ledger=OUT/"sha_ledger.json";ledger.unlink(missing_ok=True);payload=register_pre(ledger,self.result["manifest"]);self.assertTrue(all(x["pre_race_sha256"]==self.result["manifest"]["summary_sha256"] for x in payload["entries"]))
    def test_long_cardinality(self):self.assertEqual(len(self.result["long_rows"]),21*9)
    def test_export_does_not_recalculate(self):self.assertEqual(self.result["long_rows"][0]["weighted_contribution"],1.0)


if __name__=="__main__":unittest.main()
