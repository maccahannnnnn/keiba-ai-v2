import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from review import historical_replay_runner as runner
from review.historical_replay_ledger import entry, save
from review.historical_replay_safety_validator import PROTECTED, tree_hash, validate


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
    def manifest(self,**changes):
        value={"run_id":"r","phase":"PHASE2_REPRODUCTION","race_ids":[f"race_20260613_tokyo_{x}R" for x in range(1,7)],"max_races":6,"allowed_dates":["20260613"]};value.update(changes);return value
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
    def test_phase4_not_executable(self):
        with self.assertRaises(ValueError):self.load(self.manifest(phase="PHASE4_FULL"))
    def test_source_snapshot_list(self): self.assertIn("evaluation/target_trial_adapter.py",runner.SOURCE_FILES)
    def test_runner_source_snapshot_list(self): self.assertIn("review/historical_replay_runner.py",runner.SOURCE_FILES)


if __name__ == "__main__": unittest.main()
