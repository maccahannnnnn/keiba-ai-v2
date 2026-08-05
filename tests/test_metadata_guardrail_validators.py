from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from review.diagnostic_safety_validator import DiagnosticSafetyValidator
from review.learning_candidate_metadata_validator import LearningCandidateMetadataValidator
from review.read_only_replay_layer import DailyReviewReadOnlyReplay


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class MetadataGuardrailValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / "reports" / "tmp_metadata_guardrail_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"case_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.hr = self.root / "learning" / "candidate_review_status.json"
        self.current = self.root / "reports" / "improvement_candidates" / "improvement_candidates.json"
        write_json(self.current, {"candidates": [{"candidate_id": "active_all_unknown"}]})

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def validate_metadata(self, records):
        write_json(self.hr, {"records": records})
        return LearningCandidateMetadataValidator(
            human_review_db=self.hr,
            current_candidates_path=self.current,
            report_md=self.root / "reports" / "metadata.md",
            report_json=self.root / "reports" / "metadata.json",
        ).validate(write_reports=False)

    def snapshot(self, occurrences=1, distances=None, surfaces=None, track_conditions=None):
        return {
            "occurrences": occurrences,
            "race_count": 1,
            "distances": distances if distances is not None else [{"value": "unknown", "count": 1}],
            "surfaces": surfaces if surfaces is not None else [{"value": "unknown", "count": 1}],
            "track_conditions": track_conditions
            if track_conditions is not None
            else [{"value": "unknown", "count": 1}],
        }

    def test_active_all_unknown_warns(self):
        result = self.validate_metadata(
            [{"candidate_id": "active_all_unknown", "candidate_name": "A", "ranking_snapshot": self.snapshot()}]
        )
        self.assertEqual(result["active_metadata_all_unknown_count"], 1)
        self.assertEqual(result["warnings"][0]["code"], "ACTIVE_METADATA_ALL_UNKNOWN")

    def test_active_known_has_no_warning(self):
        result = self.validate_metadata(
            [
                {
                    "candidate_id": "active_all_unknown",
                    "candidate_name": "A",
                    "ranking_snapshot": self.snapshot(
                        distances=[{"value": 1200, "count": 2}],
                        surfaces=[{"value": "turf", "count": 2}],
                        track_conditions=[{"value": "good", "count": 2}],
                    ),
                }
            ]
        )
        self.assertEqual(result["active_metadata_all_unknown_count"], 0)
        self.assertEqual(result["warnings"], [])

    def test_archived_legacy_unknown_is_info(self):
        result = self.validate_metadata(
            [
                {
                    "candidate_id": "archived",
                    "candidate_name": "Legacy",
                    "ranking_active": False,
                    "archive_reason": "not_present",
                    "ranking_snapshot": self.snapshot(),
                }
            ]
        )
        self.assertEqual(result["legacy_archived_unknown_count"], 1)
        self.assertEqual(result["info"][0]["code"], "LEGACY_OR_ARCHIVED_METADATA_UNKNOWN")
        self.assertEqual(result["warnings"], [])

    def test_occurrences_zero_is_not_major_warning(self):
        result = self.validate_metadata(
            [{"candidate_id": "active_all_unknown", "candidate_name": "A", "ranking_snapshot": self.snapshot(0)}]
        )
        self.assertEqual(result["warnings"], [])

    def test_missing_candidate_id_is_error(self):
        result = self.validate_metadata([{"candidate_name": "NoId", "ranking_snapshot": self.snapshot()}])
        self.assertEqual(result["errors"][0]["code"], "MISSING_CANDIDATE_ID")

    def test_invalid_occurrences_is_error(self):
        result = self.validate_metadata(
            [{"candidate_id": "active_all_unknown", "candidate_name": "A", "ranking_snapshot": self.snapshot("x")}]
        )
        self.assertEqual(result["errors"][0]["code"], "INVALID_OCCURRENCES")

    def test_known_rate_calculation(self):
        result = self.validate_metadata(
            [
                {
                    "candidate_id": "active_all_unknown",
                    "candidate_name": "A",
                    "ranking_snapshot": self.snapshot(
                        distances=[{"value": 1200, "count": 1}, {"value": "unknown", "count": 1}]
                    ),
                }
            ]
        )
        row = result["candidates"][0]
        self.assertEqual(row["distance_known_rate"], {"known": 1, "total": 2, "rate": 0.5})

    def test_undetermined_when_no_aggregate(self):
        result = self.validate_metadata(
            [{"candidate_id": "active_all_unknown", "candidate_name": "A", "ranking_snapshot": {"occurrences": 1}}]
        )
        self.assertEqual(result["candidates"][0]["distance_known_rate"]["rate"], "UNDETERMINED")


class DiagnosticSafetyValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / "reports" / "tmp_metadata_guardrail_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"case_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        for rel in [
            "learning/improvement_candidates.json",
            "learning/candidate_review_status.json",
            "data/analysis/sample.csv",
            "data/results/sample.csv",
        ]:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def scan(self, source: str):
        script = self.root / "review" / "script.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(source, encoding="utf-8")
        return DiagnosticSafetyValidator(
            script_paths=[script],
            report_md=self.root / "reports" / "safety.md",
            report_json=self.root / "reports" / "safety.json",
            root=self.root,
        ).validate(write_reports=False)

    def test_target_trial_import_detected(self):
        result = self.scan("from evaluation.target_trial_adapter import TargetTrialAdapter\n")
        self.assertEqual(result["dangerous_import_count"], 1)

    def test_target_trial_run_detected(self):
        result = self.scan("TargetTrialAdapter().run('a','b')\n")
        self.assertEqual(result["dangerous_run_call_count"], 1)
        run = [row for row in result["findings"] if row["code"] == "TARGET_TRIAL_ADAPTER_RUN_DIRECT"][0]
        self.assertEqual(run["severity"], "HIGH")

    def test_target_trial_variable_run_detected(self):
        result = self.scan(
            "from evaluation.target_trial_adapter import TargetTrialAdapter\n"
            "adapter = TargetTrialAdapter()\n"
            "adapter.run('a','b')\n"
        )
        self.assertEqual(result["dangerous_run_call_count"], 1)
        run = [row for row in result["findings"] if row["code"] == "TARGET_TRIAL_ADAPTER_RUN_VIA_VARIABLE"][0]
        self.assertEqual(run["variable"], "adapter")
        self.assertEqual(run["severity"], "HIGH")

    def test_target_result_variable_run_detected(self):
        result = self.scan(
            "from evaluation.target_result_adapter import TargetResultAdapter\n"
            "result_adapter = TargetResultAdapter()\n"
            "result_adapter.run('a')\n"
        )
        self.assertEqual(result["dangerous_run_call_count"], 1)
        self.assertEqual(
            [row["code"] for row in result["findings"] if row["severity"] == "HIGH"],
            ["TARGET_RESULT_ADAPTER_RUN_VIA_VARIABLE"],
        )

    def test_import_alias_variable_run_detected(self):
        result = self.scan(
            "from evaluation.target_trial_adapter import TargetTrialAdapter as TTA\n"
            "adapter = TTA()\n"
            "adapter.run('a','b')\n"
        )
        self.assertEqual(result["dangerous_run_call_count"], 1)
        self.assertEqual(
            [row["code"] for row in result["findings"] if row["severity"] == "HIGH"],
            ["TARGET_TRIAL_ADAPTER_RUN_VIA_VARIABLE"],
        )

    def test_construct_only_is_not_run(self):
        result = self.scan("adapter = TargetTrialAdapter()\n")
        self.assertEqual(result["dangerous_run_call_count"], 0)
        self.assertIn("TARGET_TRIAL_ADAPTER_CONSTRUCT_ONLY", [row["code"] for row in result["findings"]])

    def test_load_only_is_not_run(self):
        result = self.scan(
            "from evaluation.target_result_adapter import TargetResultAdapter\n"
            "result_adapter = TargetResultAdapter()\n"
            "result_adapter.load('a','b')\n"
        )
        self.assertEqual(result["dangerous_run_call_count"], 0)
        self.assertIn("TARGET_RESULT_ADAPTER_LOAD_ONLY", [row["code"] for row in result["findings"]])

    def test_unrelated_run_not_detected(self):
        result = self.scan("class Other:\n    def run(self): pass\nother = Other()\nother.run()\n")
        self.assertEqual(result["dangerous_run_call_count"], 0)

    def test_same_variable_name_scope_isolated(self):
        result = self.scan(
            "def a():\n"
            "    adapter = TargetTrialAdapter()\n"
            "def b():\n"
            "    adapter.run()\n"
        )
        self.assertEqual(result["dangerous_run_call_count"], 0)

    def test_target_result_adapter_detected(self):
        result = self.scan("from evaluation.target_result_adapter import TargetResultAdapter\nx=TargetResultAdapter()\n")
        self.assertGreaterEqual(len(result["findings"]), 2)

    def test_production_json_write_detected(self):
        result = self.scan("Path('learning/improvement_candidates.json').write_text('{}')\n")
        self.assertEqual(result["production_write_count"], 1)

    def test_reports_write_allowed(self):
        result = self.scan("Path('reports/out.md').write_text('ok')\n")
        self.assertEqual(result["production_write_count"], 0)

    def test_tmp_write_allowed(self):
        result = self.scan("open('tmp/out.json', 'w')\n")
        self.assertEqual(result["production_write_count"], 0)

    def test_hash_no_diff_when_validator_runs(self):
        result = self.scan("print('read only')\n")
        self.assertFalse(result["hash_changed"])

    def test_legacy_not_migrated_by_metadata_validator(self):
        hr = self.root / "learning" / "candidate_review_status.json"
        current = self.root / "reports" / "improvement_candidates" / "improvement_candidates.json"
        write_json(hr, {"records": [{"candidate_id": "legacy", "ranking_snapshot": {"occurrences": 1}}]})
        write_json(current, {"candidates": []})
        before = hr.read_text(encoding="utf-8")
        LearningCandidateMetadataValidator(hr, current).validate(write_reports=False)
        self.assertEqual(before, hr.read_text(encoding="utf-8"))


class DailyReviewReadOnlyReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        base = Path.cwd() / "reports" / "tmp_metadata_guardrail_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / f"case_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.date = "20990101"
        self.output_dir = Path("reports") / f"review_{self.date}"
        out = self.root / self.output_dir
        out.mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "analysis").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "results").mkdir(parents=True, exist_ok=True)
        race_id = f"race_{self.date}_tokyo_10R"
        suffix = race_id.replace("race_", "")
        for path in [
            self.root / "data" / "analysis" / f"{race_id}_entry.csv",
            self.root / "data" / "analysis" / f"{race_id}_horses.csv",
            self.root / "data" / "results" / f"{race_id}_result.csv",
            self.root / "data" / "results" / f"horse_{suffix}_result.csv",
        ]:
            path.write_text("x\n", encoding="utf-8")
        (out / f"race_summary_{self.date}_v2.csv").write_text(
            "race_id,race_date,racecourse,race_number,self_check_conflict,buy_count,"
            "race_decision_final,winner_in_top5,top5_place_count,top3_place_count,"
            "top1_place,top1_win,winner_in_top3,race_decision_classification,explain_match\n"
            f"{race_id},{self.date},tokyo,10R,False,1,PLAY,True,2,1,True,False,False,PLAY_CORRECT,EXPLAIN_MATCH\n",
            encoding="utf-8",
        )
        (out / f"horse_review_{self.date}_v2.csv").write_text(
            "race_id,horse_number,horse_name,ai_rank,decision,actual_top3,actual_top5,finish_position\n"
            f"{race_id},1,Sample,1,BUY,True,True,2\n",
            encoding="utf-8",
        )
        write_json(
            out / f"daily_review_{self.date}_summary_v2.json",
            {"validation": {"checks": ["PRE_RACE_SAVED_OUTPUT and CURRENT_CODE_REPLAY separated"]}},
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_read_only_replay_loads_saved_rows(self):
        replay = DailyReviewReadOnlyReplay(self.root, self.date, self.output_dir).load()
        self.assertEqual(replay["source"]["mode"], "READ_ONLY_REPLAY")
        self.assertEqual(len(replay["race_rows"]), 1)
        self.assertEqual(len(replay["horse_rows"]), 1)
        self.assertEqual(replay["incomplete"], [])
        self.assertTrue(replay["race_rows"][0]["winner_in_top5"])
        self.assertTrue(replay["horse_rows"][0]["actual_top3"])
        self.assertEqual(replay["source"]["source_review_version"], "v2")
        self.assertEqual(replay["source"]["source_evaluation_origin"], "CURRENT_CODE_REPLAY")
        self.assertEqual(replay["race_rows"][0]["pre_race_saved_output_status"], "NOT_FOUND")

    def test_read_only_replay_reports_missing_saved_review(self):
        replay = DailyReviewReadOnlyReplay(self.root, "20990202", Path("reports") / "review_20990202").load()
        self.assertEqual(replay["race_rows"], [])
        self.assertEqual(replay["incomplete"][0]["reason"], "missing_saved_review:race_summary_20990202*.csv;horse_review_20990202*.csv")

    def test_read_only_replay_rejects_mismatched_versions(self):
        out = self.root / self.output_dir
        (out / f"horse_review_{self.date}_v2.csv").unlink()
        (out / f"horse_review_{self.date}_v3.csv").write_text(
            "race_id,horse_number,horse_name,ai_rank,decision,actual_top3,actual_top5,finish_position\n"
            f"race_{self.date}_tokyo_10R,1,Sample,1,BUY,True,True,2\n",
            encoding="utf-8",
        )
        replay = DailyReviewReadOnlyReplay(self.root, self.date, self.output_dir, source_review_version="v2").load()
        self.assertEqual(replay["race_rows"], [])
        self.assertEqual(replay["replay_errors"][0]["code"], "REPLAY_SOURCE_SELECTION_FAILED")
        self.assertIn("REPLAY_VERSION_MISSING:v2", replay["replay_errors"][0]["message"])

    def test_read_only_replay_selects_common_max_non_replay_version(self):
        out = self.root / self.output_dir
        race_id = f"race_{self.date}_tokyo_10R"
        for version in ["v3", "v4"]:
            (out / f"race_summary_{self.date}_{version}.csv").write_text(
                "race_id,race_date,racecourse,race_number,self_check_conflict,buy_count,"
                "race_decision_final,winner_in_top5,top5_place_count,top3_place_count,"
                "top1_place,top1_win,winner_in_top3,race_decision_classification,explain_match\n"
                f"{race_id},{self.date},tokyo,10R,False,1,PLAY,True,2,1,True,False,False,PLAY_CORRECT,EXPLAIN_MATCH\n",
                encoding="utf-8",
            )
            (out / f"horse_review_{self.date}_{version}.csv").write_text(
                "race_id,horse_number,horse_name,ai_rank,decision,actual_top3,actual_top5,finish_position\n"
                f"{race_id},1,Sample,1,BUY,True,True,2\n",
                encoding="utf-8",
            )
            write_json(
                out / f"daily_review_{self.date}_summary_{version}.json",
                {"replay_source": {"mode": "READ_ONLY_REPLAY"}},
            )
        replay = DailyReviewReadOnlyReplay(self.root, self.date, self.output_dir).load()
        self.assertEqual(replay["source"]["source_review_version"], "v2")
        self.assertTrue(replay["source"]["source_race_summary_path"].endswith(f"race_summary_{self.date}_v2.csv"))

    def test_read_only_replay_does_not_select_by_mtime_only(self):
        out = self.root / self.output_dir
        race_id = f"race_{self.date}_tokyo_10R"
        (out / f"race_summary_{self.date}_v3.csv").write_text(
            "race_id,race_date,racecourse,race_number,self_check_conflict,buy_count,"
            "race_decision_final,winner_in_top5,top5_place_count,top3_place_count,"
            "top1_place,top1_win,winner_in_top3,race_decision_classification,explain_match\n"
            f"{race_id},{self.date},tokyo,10R,False,1,PLAY,True,2,1,True,False,False,PLAY_CORRECT,EXPLAIN_MATCH\n",
            encoding="utf-8",
        )
        (out / f"horse_review_{self.date}_v3.csv").write_text(
            "race_id,horse_number,horse_name,ai_rank,decision,actual_top3,actual_top5,finish_position\n"
            f"{race_id},1,Sample,1,BUY,True,True,2\n",
            encoding="utf-8",
        )
        write_json(out / f"daily_review_{self.date}_summary_v3.json", {"replay_source": {"mode": "READ_ONLY_REPLAY"}})
        replay = DailyReviewReadOnlyReplay(self.root, self.date, self.output_dir).load()
        self.assertEqual(replay["source"]["source_review_version"], "v2")

    def test_read_only_replay_rejects_race_id_set_mismatch(self):
        out = self.root / self.output_dir
        (out / f"horse_review_{self.date}_v2.csv").write_text(
            "race_id,horse_number,horse_name,ai_rank,decision,actual_top3,actual_top5,finish_position\n"
            f"race_{self.date}_tokyo_11R,1,Sample,1,BUY,True,True,2\n",
            encoding="utf-8",
        )
        replay = DailyReviewReadOnlyReplay(self.root, self.date, self.output_dir).load()
        self.assertEqual(replay["race_rows"], [])
        self.assertIn("RACE_ID_SET_MISMATCH", [row["code"] for row in replay["replay_errors"]])

    def test_read_only_replay_rejects_target_date_mismatch(self):
        out = self.root / self.output_dir
        (out / f"race_summary_{self.date}_v2.csv").write_text(
            "race_id,race_date,racecourse,race_number,self_check_conflict,buy_count,"
            "race_decision_final,winner_in_top5,top5_place_count,top3_place_count,"
            "top1_place,top1_win,winner_in_top3,race_decision_classification,explain_match\n"
            "race_20990102_tokyo_10R,20990102,tokyo,10R,False,1,PLAY,True,2,1,True,False,False,PLAY_CORRECT,EXPLAIN_MATCH\n",
            encoding="utf-8",
        )
        replay = DailyReviewReadOnlyReplay(self.root, self.date, self.output_dir).load()
        self.assertEqual(replay["race_rows"], [])
        self.assertIn("TARGET_DATE_MISMATCH", [row["code"] for row in replay["replay_errors"]])

    def test_read_only_replay_rejects_duplicate_race_id(self):
        out = self.root / self.output_dir
        race_id = f"race_{self.date}_tokyo_10R"
        (out / f"race_summary_{self.date}_v2.csv").write_text(
            "race_id,race_date,racecourse,race_number,self_check_conflict,buy_count,"
            "race_decision_final,winner_in_top5,top5_place_count,top3_place_count,"
            "top1_place,top1_win,winner_in_top3,race_decision_classification,explain_match\n"
            f"{race_id},{self.date},tokyo,10R,False,1,PLAY,True,2,1,True,False,False,PLAY_CORRECT,EXPLAIN_MATCH\n"
            f"{race_id},{self.date},tokyo,10R,False,1,PLAY,True,2,1,True,False,False,PLAY_CORRECT,EXPLAIN_MATCH\n",
            encoding="utf-8",
        )
        replay = DailyReviewReadOnlyReplay(self.root, self.date, self.output_dir).load()
        self.assertEqual(replay["race_rows"], [])
        self.assertIn("DUPLICATE_RACE_ID", [row["code"] for row in replay["replay_errors"]])

    def test_read_only_replay_rejects_duplicate_horse(self):
        out = self.root / self.output_dir
        race_id = f"race_{self.date}_tokyo_10R"
        (out / f"horse_review_{self.date}_v2.csv").write_text(
            "race_id,horse_number,horse_name,ai_rank,decision,actual_top3,actual_top5,finish_position\n"
            f"{race_id},1,Sample,1,BUY,True,True,2\n"
            f"{race_id},1,Sample,2,PASS,False,False,8\n",
            encoding="utf-8",
        )
        replay = DailyReviewReadOnlyReplay(self.root, self.date, self.output_dir).load()
        self.assertEqual(replay["race_rows"], [])
        self.assertIn("DUPLICATE_HORSE", [row["code"] for row in replay["replay_errors"]])

    def test_read_only_replay_rejects_buy_count_over_three(self):
        out = self.root / self.output_dir
        race_id = f"race_{self.date}_tokyo_10R"
        (out / f"race_summary_{self.date}_v2.csv").write_text(
            "race_id,race_date,racecourse,race_number,self_check_conflict,buy_count,"
            "race_decision_final,winner_in_top5,top5_place_count,top3_place_count,"
            "top1_place,top1_win,winner_in_top3,race_decision_classification,explain_match\n"
            f"{race_id},{self.date},tokyo,10R,False,4,PLAY,True,2,1,True,False,False,PLAY_CORRECT,EXPLAIN_MATCH\n",
            encoding="utf-8",
        )
        replay = DailyReviewReadOnlyReplay(self.root, self.date, self.output_dir).load()
        self.assertEqual(replay["race_rows"], [])
        self.assertIn("BUY_COUNT_OVER_3", [row["code"] for row in replay["replay_errors"]])


if __name__ == "__main__":
    unittest.main()
