import inspect,json,unittest
from pathlib import Path
from review.unconverged_shadow_evidence_collector import FEATURE_FLAG_ENABLED,MAX_SELECT,gate,guards
from review.unconverged_shadow_ledger import LEDGER_SCHEMA_VERSION,trigger,update_ledger

ROOT=Path("reports/shadow_unconverged")
PRE=ROOT/"pre_race/unconverged_shadow_pre_race_20260802_v1.json"
POST=ROOT/"post_race/unconverged_shadow_post_race_20260802_v1.json"

class PipelineTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.pre=json.loads(PRE.read_text(encoding="utf-8"));cls.post=json.loads(POST.read_text(encoding="utf-8"))
 def base(self,rank=1):return {"race_id":"r","horse_name":f"h{rank}","horse_number":str(rank),"ai_rank":str(rank),"final_score":"150","adjusted_score":str(200-rank),"decision_score":"1","absolute_status":"PASS","relative_status":"PASS","consensus_status":"PASS","trace_status":"COMPLETE","guard_score":1,"guard_eligible":True}
 def test_feature_flag_off(self):self.assertFalse(FEATURE_FLAG_ENABLED)
 def test_absolute_same_inputs_same_result(self):self.assertEqual(gate(self.base(),200)["absolute_status"],gate(self.base(2),200)["absolute_status"])
 def test_missing_is_trace(self):self.assertEqual(gate(self.base(),200)["consensus_status"],"TRACE")
 def test_guard_cap_three_and_stable(self):
  choices=guards([self.base(i) for i in range(1,6)]);self.assertTrue(all(len(x)<=MAX_SELECT for x in choices.values()));self.assertEqual([x["ai_rank"] for x in choices["MULTI_GATE_SUPPORT_FLOOR"]],["1","2","3"])
 def test_pre_race_has_no_result_io_or_fields(self):
  import review.unconverged_shadow_evidence_collector as c
  source=inspect.getsource(c);self.assertNotIn("data/results",source);self.assertNotIn("_result.csv",source);self.assertTrue(all(not any(k.startswith("actual_") for k in x) for x in self.pre["rows"]))
 def test_race_candidate_counts_are_5_5_4(self):
  for rid,want in {"race_20260802_chuukyou_6R":5,"race_20260802_niigata_8R":5,"race_20260802_sapporo_11R":4}.items():
   with self.subTest(race_id=rid):self.assertEqual(self.post["per_race"][rid]["candidate_count"],want)
 def test_no_aggregate_14_duplicated_into_races(self):self.assertEqual(sorted(x["candidate_count"] for x in self.post["per_race"].values()),[4,5,5])
 def test_race_guard_aggregates_differ(self):self.assertEqual([x["guards"]["TOP_CLUSTER_DUAL_SEPARATION"]["selected_count"] for x in self.post["per_race"].values()],[3,0,0])
 def test_aggregate_equals_sum_of_races(self):
  for guard,total in self.post["guards"].items():
   for field in ("selected_count","FN","FP","Top5","ROI"):
    with self.subTest(guard=guard,field=field):self.assertEqual(total[field],sum(x["guards"][guard][field] for x in self.post["per_race"].values()))
 def test_duplicate_key_is_ignored(self):
  p=ROOT/"unconverged_shadow_ledger_v1_1.json";first=update_ledger(p,self.post);second=update_ledger(p,self.post);self.assertEqual(len(first["entries"]),3);self.assertEqual(len(second["entries"]),3)
 def test_excluded_candidates_are_auditable_and_not_selected(self):
  excluded=[x for x in self.pre["rows"] if not x["guard_eligible"]];self.assertTrue(excluded);self.assertTrue(all(x["candidate_detected"] and x["pre_filter_status"].startswith("EXCLUDED_") for x in excluded));self.assertTrue(all(not x[f"{g}_selected"] for x in excluded for g in self.post["guards"]))
 def test_summary_metrics_and_invalid_sources(self):
  self.assertEqual([(x["selected_count"],x["FN"],x["FP"],x["ROI"]) for x in self.post["guards"].values()],[(3,1,2,-1),(9,2,7,-5),(9,2,7,-5)]);self.assertEqual(trigger({"ledger_schema_version":LEDGER_SCHEMA_VERSION,"entries":[{"race_date":"20260802","race_id":x,"post_race_status":"COMPLETE"} for x in self.post["per_race"]]}),"EVIDENCE_ACCUMULATING");self.assertEqual(trigger({"pipeline_version":"unconverged_shadow_evidence_v1","entries":[]}),"INVALID_LEDGER_REJECTED")

if __name__=="__main__":unittest.main()
