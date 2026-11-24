import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from review import historical_replay_runner as runner
from review.historical_replay_ledger import entry, save
from review.historical_replay_post_race import read_csv, result_horse_number, result_semantics
from review.historical_replay_safety_validator import PROTECTED, ast_scan, tree_hash, validate
from review.historical_replay_semantic_diff import compare


class HistoricalReplayRunnerTests(unittest.TestCase):
    def test_version(self): self.assertEqual(runner.VERSION, "HR_V1")
    def test_three_smoke_races(self): self.assertEqual(len(runner.SMOKE_RACES), 3)
    def test_multiple_dates(self): self.assertGreater(len({x.split("_")[1] for x in runner.SMOKE_RACES}), 1)
    def test_multiple_courses(self): self.assertGreater(len({x.split("_")[2] for x in runner.SMOKE_RACES}), 1)
    def test_result_fields_finish(self): self.assertIn("actual_finish", runner.RESULT_FIELDS)
    def test_result_fields_top3(self): self.assertIn("actual_top3", runner.RESULT_FIELDS)
    def test_result_fields_top5(self): self.assertIn("actual_top5", runner.RESULT_FIELDS)
    def test_result_fields_path(self): self.assertIn("result_path", runner.RESULT_FIELDS)
    def test_result_fields_hash(self): self.assertIn("result_hash", runner.RESULT_FIELDS)
    def test_config_buy(self): self.assertTrue(runner.config()[0]["BUY_V1_RC1_ENABLED"])
    def test_config_provenance(self): self.assertTrue(runner.config()[0]["RANKING_PROVENANCE_EXPORT_ENABLED"])
    def test_config_learning_off(self): self.assertFalse(runner.config()[0]["learning_phase2"])
    def test_config_shadow_off(self): self.assertFalse(runner.config()[0]["shadow_engine"])
    def test_config_meeting_bias(self): self.assertEqual(runner.config()[0]["meeting_bias"], "READ_ONLY")
    def test_config_manual_bias(self): self.assertIsNone(runner.config()[0]["manual_track_bias"])
    def test_config_hash_stable(self): self.assertEqual(runner.config()[1], runner.config()[1])
    def test_config_hash_length(self): self.assertEqual(len(runner.config()[1]), 64)
    def test_protected_learning(self): self.assertIn("learning", PROTECTED)
    def test_protected_knowledge(self): self.assertIn("knowledge", PROTECTED)
    def test_protected_candidate_report(self): self.assertIn("reports/improvement_candidates.md", PROTECTED)
    def test_source_has_no_main_import(self): self.assertNotIn("import main", Path(runner.__file__).read_text(encoding="utf-8"))
    def test_source_has_adapter_constructor(self): self.assertIn("TargetTrialAdapter(", Path(runner.__file__).read_text(encoding="utf-8"))
    def test_source_disables_candidate_engine(self): self.assertIn("enable_learning_candidate_engine=False", Path(runner.__file__).read_text(encoding="utf-8"))
    def test_source_has_no_candidate_writer(self): self.assertNotIn("LearningCandidateEngine(", Path(runner.__file__).read_text(encoding="utf-8"))
    def test_ast_one_adapter_run_callsite(self):
        tree=ast.parse(Path(runner.__file__).read_text(encoding="utf-8")); calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="run"]
        self.assertEqual(len(calls), 2)  # subprocess.run plus adapter.run
    def test_write_new(self):
        with patch("pathlib.Path.exists",return_value=False), patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_text") as write:
            runner.write_new(Path("x.json"),{"x":1});self.assertTrue(write.called)
    def test_write_new_no_overwrite(self):
        with patch("pathlib.Path.exists",return_value=True):
            with self.assertRaises(FileExistsError): runner.write_new(Path("x.json"),{})
    def test_ledger_entry_status(self): self.assertEqual(entry("r","20260101",1,"DISCOVERED")["status"],"DISCOVERED")
    def test_ledger_entry_counts(self): self.assertEqual(entry("r","20260101",9,"DISCOVERED")["horse_count"],9)
    def test_ledger_save(self):
        with patch("pathlib.Path.exists",return_value=False), patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_text") as write:
            save(Path("ledger.json"),"run",[entry("r","d",1,"DISCOVERED")]);self.assertTrue(write.called)
    def test_ledger_no_overwrite(self):
        with patch("pathlib.Path.exists",return_value=True):
            with self.assertRaises(FileExistsError): save(Path("ledger.json"),"run",[])
    def test_tree_hash_missing(self): self.assertEqual(tree_hash(Path("definitely_missing_hr_v1")),"MISSING")
    def test_tree_hash_file(self):
        self.assertEqual(len(tree_hash(Path(runner.__file__))),64)
    def test_validate_rejects_outside_root(self): self.assertEqual(validate({},Path(tempfile.gettempdir()))["status"],"FAIL")
    def test_horse_rows_tags(self):
        rows=runner.horse_rows({"ranked_results":[{"horse_name":"h","rank":1}]},"race_20260101_tokyo_1R","20260101")
        self.assertEqual(rows[0]["pipeline_version"],runner.PIPELINE_VERSION)
    def test_horse_rows_rank(self):
        rows=runner.horse_rows({"ranked_results":[{"rank":2}]},"race_20260101_tokyo_1R","20260101")
        self.assertEqual(rows[0]["ai_rank"],2)
    def test_horse_rows_course(self):
        rows=runner.horse_rows({"ranked_results":[{}]},"race_20260101_tokyo_1R","20260101")
        self.assertEqual(rows[0]["racecourse"],"tokyo")
    def test_result_semantics_normal_top3(self):
        result=result_semantics({"確定着順":"3","異常コード":"0"})
        self.assertEqual(result,{"actual_finish":3,"actual_top3":True,"actual_top5":True,"valid_result":True})
    def test_result_semantics_normal_fourth_or_lower(self):
        result=result_semantics({"確定着順":"4","異常コード":"0"})
        self.assertEqual(result,{"actual_finish":4,"actual_top3":False,"actual_top5":True,"valid_result":True})
    def test_result_semantics_finish_zero_is_invalid(self):
        result=result_semantics({"確定着順":"0","異常コード":"3"})
        self.assertEqual(result,{"actual_finish":0,"actual_top3":False,"actual_top5":False,"valid_result":False})
    def test_result_semantics_nonzero_abnormal_is_invalid(self):
        result=result_semantics({"確定着順":"2","異常コード":"4"})
        self.assertEqual(result,{"actual_finish":2,"actual_top3":False,"actual_top5":False,"valid_result":False})
    def test_result_semantics_blank_abnormal_is_normal(self):
        result=result_semantics({"確定着順":"1","異常コード":""})
        self.assertTrue(result["valid_result"]);self.assertTrue(result["actual_top3"])
    def test_known_17_replay_anomalies_reclassify_invalid(self):
        assets={row["race_id"]:row for row in runner.discover(runner.ROOT/"data")};old=[]
        for path in (runner.ROOT/"reports/historical_replay_current_code").glob("**/review/review.json"):
            payload=json.loads(path.read_text(encoding="utf-8"))
            for horse in payload.get("horses",[]):
                if horse.get("actual_finish")==0 and horse.get("actual_top3") is True and horse.get("valid_result") is True:
                    old.append((payload["race_id"],str(horse["horse_number"])))
        self.assertEqual(len(old),17)
        for race_id,horse_number in old:
            rows=read_csv(assets[race_id]["assets"]["horse_result"][0]);result=next(row for row in rows if result_horse_number(row)==horse_number)
            self.assertEqual(result_semantics(result)["valid_result"],False)
            self.assertEqual(result_semantics(result)["actual_top3"],False)
    def test_formal_baseline_five_invalid_results_match(self):
        expected={("race_20260725_niigata_7R","15"),("race_20260726_sapporo_10R","7"),("race_20260726_sapporo_11R","7"),("race_20260801_niigata_8R","4"),("race_20260801_sapporo_10R","12")}
        assets={row["race_id"]:row for row in runner.discover(runner.ROOT/"data")}
        for race_id,horse_number in expected:
            rows=read_csv(assets[race_id]["assets"]["horse_result"][0]);result=next(row for row in rows if result_horse_number(row)==horse_number);semantics=result_semantics(result)
            self.assertEqual((semantics["valid_result"],semantics["actual_top3"]),(False,False))
    def test_invalid_buy_is_excluded_from_evaluation_denominator(self):
        row={"decision":"BUY",**result_semantics({"確定着順":"0","異常コード":"4"})}
        eligible=[item for item in [row] if item["valid_result"]]
        self.assertEqual(eligible,[])
    def manifest(self,**changes):
        value={"run_id":"r","phase":"PHASE2_REPRODUCTION","race_ids":[f"race_20260613_tokyo_{x}R" for x in range(1,7)],"max_races":6,"allowed_dates":["20260613"],"execution_authorized":True};value.update(changes);return value
    def load(self,value):
        with patch("pathlib.Path.read_text",return_value=json.dumps(value)):return runner.load_asset_manifest(Path("m.json"))
    def test_manifest_valid(self): self.assertEqual(self.load(self.manifest())["phase"],"PHASE2_REPRODUCTION")
    def test_manifest_duplicate_rejected(self):
        with self.assertRaises(ValueError):self.load(self.manifest(race_ids=["race_20260613_tokyo_1R"]*6))
    def test_manifest_max_rejected(self):
        with self.assertRaises(ValueError):self.load(self.manifest(max_races=5))
    def test_manifest_wrong_date_rejected(self):
        with self.assertRaises(ValueError):self.load(self.manifest(allowed_dates=["20260614"]))
    def test_manifest_phase2_scope_rejected(self):
        with self.assertRaises(ValueError):self.load(self.manifest(race_ids=["race_20260613_tokyo_1R"]))
    def test_phase1_limit(self): self.assertEqual(runner.PHASE_LIMITS["PHASE1_SMOKE"],3)
    def test_phase2_limit(self): self.assertEqual(runner.PHASE_LIMITS["PHASE2_ONE_DAY"],10)
    def test_phase3_limit(self): self.assertEqual(runner.PHASE_LIMITS["PHASE3_PILOT"],20)
    def test_phase4_authorized_manifest_is_valid(self): self.assertEqual(self.load(self.manifest(phase="PHASE4_BATCH"))["phase"],"PHASE4_BATCH")
    def test_phase4_full_always_rejected(self):
        with self.assertRaisesRegex(ValueError,"PHASE_NOT_EXECUTABLE"):self.load(self.manifest(phase="PHASE4_FULL"))
    def test_phase4_batch_limit_is_30(self): self.assertEqual(runner.PHASE_LIMITS["PHASE4_BATCH"],30)
    def test_phase4_batch_31_rejected(self):
        ids=[f"race_20260613_tokyo_{x}R" for x in range(1,32)]
        with self.assertRaisesRegex(ValueError,"MAX_RACES_EXCEEDED"):self.load(self.manifest(phase="PHASE4_BATCH",race_ids=ids,max_races=31))
    def test_phase4_full_106_rejected(self):
        ids=[f"race_20260613_tokyo_{x}R" for x in range(1,107)]
        with self.assertRaisesRegex(ValueError,"PHASE_NOT_EXECUTABLE"):self.load(self.manifest(phase="PHASE4_FULL",race_ids=ids,max_races=106))
    def test_execution_authorized_missing_rejected(self):
        value=self.manifest();value.pop("execution_authorized")
        with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):self.load(value)
    def test_execution_authorized_false_rejected(self):
        with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):self.load(self.manifest(execution_authorized=False))
    def test_execution_authorized_string_rejected(self):
        with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):self.load(self.manifest(execution_authorized="true"))
    def test_execution_authorized_numeric_rejected(self):
        with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):self.load(self.manifest(execution_authorized=1))
    def test_execution_authorized_boolean_true_only_succeeds(self): self.assertIs(self.load(self.manifest())["execution_authorized"],True)
    def test_phase1_manifest_checks_authorization(self):
        with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):self.load(self.manifest(phase="PHASE1_SMOKE",race_ids=self.manifest()["race_ids"][:3],max_races=3,execution_authorized=False))
    def test_phase2_manifest_checks_authorization(self):
        with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):self.load(self.manifest(execution_authorized=False))
    def test_phase3_manifest_checks_authorization(self):
        with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):self.load(self.manifest(phase="PHASE3_PILOT",execution_authorized=False))
    def test_phase4_manifest_checks_authorization(self):
        with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):self.load(self.manifest(phase="PHASE4_BATCH",execution_authorized=False))
    def test_run_manifest_passes_authorization_evidence(self):
        value=self.manifest()
        with patch.object(runner,"sha",return_value="a"*64), patch.object(runner,"load_asset_manifest",return_value=value), patch.object(runner,"run_selection",return_value=(Path("run"),{})) as execute:
            runner.run_manifest_file(Path("m.json"))
        evidence=execute.call_args.args[-1];self.assertEqual(evidence["authorization_source_manifest_sha256"],"a"*64);self.assertEqual(evidence["authorized_phase"],value["phase"]);self.assertEqual(evidence["authorized_race_count"],6)
    def test_authorization_manifest_mutation_detected(self):
        with patch.object(runner,"sha",side_effect=["a"*64,"b"*64]), patch.object(runner,"load_asset_manifest",return_value=self.manifest()), patch.object(runner,"run_selection",return_value=(Path("run"),{})):
            with self.assertRaisesRegex(ValueError,"AUTHORIZATION_MANIFEST_CHANGED"):runner.run_manifest_file(Path("m.json"))
    def test_unauthorized_manifest_adapter_run_zero(self):
        with patch.object(runner,"sha",return_value="a"*64), patch.object(runner,"load_asset_manifest",side_effect=ValueError("EXECUTION_NOT_AUTHORIZED")), patch.object(runner,"run_selection") as execute:
            with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):runner.run_manifest_file(Path("m.json"))
        execute.assert_not_called()
    def test_unauthorized_manifest_write_zero(self):
        with patch.object(runner,"sha",return_value="a"*64), patch.object(runner,"load_asset_manifest",side_effect=ValueError("EXECUTION_NOT_AUTHORIZED")), patch.object(runner,"write_new") as write:
            with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):runner.run_manifest_file(Path("m.json"))
        write.assert_not_called()
    def test_run_smoke_without_manifest_rejected(self):
        with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):runner.run_smoke("r")
    def test_run_smoke_unauthorized_adapter_zero(self):
        with patch.object(runner,"TargetTrialAdapter") as adapter:
            with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):runner.run_smoke("r")
        adapter.assert_not_called()
    def test_run_smoke_unauthorized_write_zero(self):
        with patch.object(runner,"write_new") as write:
            with self.assertRaisesRegex(ValueError,"EXECUTION_NOT_AUTHORIZED"):runner.run_smoke("r")
        write.assert_not_called()
    def test_run_smoke_authorized_uses_common_manifest_runner(self):
        value=self.manifest(run_id="smoke",phase="PHASE1_SMOKE",race_ids=list(runner.SMOKE_RACES),max_races=3,allowed_dates=sorted({x.split("_")[1] for x in runner.SMOKE_RACES}))
        with patch.object(runner,"load_asset_manifest",return_value=value) as load, patch.object(runner,"run_manifest_file",return_value=(Path("run"),{})) as execute:
            runner.run_smoke("smoke",Path("smoke.json"))
        load.assert_called_once();execute.assert_called_once()
    def test_source_snapshot_list(self): self.assertIn("evaluation/target_trial_adapter.py",runner.SOURCE_FILES)
    def test_runner_source_snapshot_list(self): self.assertIn("review/historical_replay_runner.py",runner.SOURCE_FILES)
    def test_ast_safety_passes(self): self.assertEqual(ast_scan()["status"],"PASS")
    def test_ast_safety_nonzero_scope(self): self.assertGreater(ast_scan()["scan_target_count"],0)
    def test_ast_safety_adapter_count(self): self.assertEqual(ast_scan()["adapter_run_callsite_count"],1)
    def test_ast_safety_missing_target_fails(self): self.assertEqual(ast_scan(["missing_hr_file.py"])["status"],"FAIL")
    def test_semantic_diff_self_exact(self):
        root=runner.ROOT/"reports/historical_replay_current_code/HR_PHASE2_REPRODUCTION_20260613_V2";self.assertEqual(compare(root,root)["judgment"],"SEMANTIC_EXACT_MATCH")
    def test_semantic_diff_v1_v2_has_no_semantic_diff(self):
        left=runner.ROOT/"reports/historical_replay_current_code/HR_PHASE2_20260613_V1";right=runner.ROOT/"reports/historical_replay_current_code/HR_PHASE2_REPRODUCTION_20260613_V2";self.assertNotEqual(compare(left,right)["judgment"],"SEMANTIC_DIFF_FOUND")
    def test_ast_forbidden_fixture_fails(self):
        result=ast_scan(["tests/fixtures/historical_replay_ast_forbidden.py.txt"]);self.assertEqual(result["status"],"FAIL")
    def test_ast_learning_generate_detected(self):
        result=ast_scan(["tests/fixtures/historical_replay_ast_forbidden.py.txt"]);self.assertTrue(any(x["category"]=="learning_generate_call" for x in result["findings"]))
    def test_ast_protected_write_detected(self):
        result=ast_scan(["tests/fixtures/historical_replay_ast_forbidden.py.txt"]);self.assertTrue(any(x["category"]=="protected_write" for x in result["findings"]))
    def test_ast_main_execution_detected(self):
        result=ast_scan(["tests/fixtures/historical_replay_ast_forbidden.py.txt"]);self.assertTrue(any(x["category"]=="main_execution" for x in result["findings"]))
    def batch_manifests(self):
        return [json.loads((runner.ROOT/f"reports/historical_replay/phase4_batch{x}_v1_asset_manifest.json").read_text(encoding="utf-8")) for x in range(1,5)]
    def test_four_phase4_batches(self): self.assertEqual(len(self.batch_manifests()),4)
    def test_phase4_total_106(self): self.assertEqual(sum(len(x["race_ids"]) for x in self.batch_manifests()),106)
    def test_phase4_no_duplicates(self):
        ids=sum((x["race_ids"] for x in self.batch_manifests()),[]);self.assertEqual(len(ids),len(set(ids)))
    def test_phase4_no_omissions(self):
        manifests=self.batch_manifests();planned=set(sum((x["race_ids"] for x in manifests),[]));allowed_dates=set(sum((x["allowed_dates"] for x in manifests),[]));ready={x["race_id"] for x in runner.discover(runner.ROOT/"data") if x["status"]=="READY" and x["race_id"].split("_")[1] in allowed_dates};self.assertEqual(planned,ready)
    def test_phase4_max_races_match(self):
        self.assertTrue(all(x["max_races"]==len(x["race_ids"]) for x in self.batch_manifests()))
    def test_phase4_allowed_dates_match(self):
        self.assertTrue(all({r.split("_")[1] for r in x["race_ids"]}==set(x["allowed_dates"]) for x in self.batch_manifests()))
    def test_phase4_execution_not_authorized(self): self.assertTrue(all(x["execution_authorized"] is False for x in self.batch_manifests()))
    def test_phase4_batch_manifest_phase(self): self.assertTrue(all(x["phase"]=="PHASE4_BATCH" for x in self.batch_manifests()))


if __name__ == "__main__": unittest.main()
