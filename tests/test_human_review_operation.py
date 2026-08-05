import hashlib
import json
import unittest
from pathlib import Path
import shutil
import uuid

from engine.human_review_cli import HumanReviewCLI, HumanReviewEvidenceReader
from engine.human_review_engine import HumanReviewEngine
from review.human_review_quality_validator import HumanReviewQualityValidator


class FakeRankingEngine:
    def __init__(self, item=None):
        self.item = item or self.item_for("B")

    def item_for(self, priority, name="CandidateA", ctype="Evaluator"):
        status = {"A": "REVIEW_REQUIRED", "B": "WATCH", "S": "REVIEW_REQUIRED"}.get(priority, "LOW_PRIORITY")
        return {
            "candidate_name": name,
            "candidate_type": ctype,
            "priority": priority,
            "ranking_score": 0.5,
            "rank": 1,
            "status": status,
            "occurrences": 3,
            "fn_count": 2,
            "fp_count": 1,
            "race_count": 2,
            "racecourses": [],
            "distances": [],
            "related_evaluators": [],
        }

    def _load_database(self):
        return {"records": []}

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _build_ranking(self, records):
        return [self.item]


class OldHumanReviewEngine(HumanReviewEngine):
    def _refresh_existing_record(self, record, item, now):
        record["candidate_name"] = item.get("candidate_name")
        record["candidate_type"] = item.get("candidate_type")
        record["priority"] = item.get("priority")
        record["ranking_score"] = item.get("ranking_score")
        record["rank"] = item.get("rank")
        if record.get("status") not in self.TERMINAL_OR_HUMAN_STATUSES:
            status = item.get("status") or record.get("status") or "REVIEW_REQUIRED"
            record["status"] = status if status in self.VALID_STATUSES else "REVIEW_REQUIRED"
        record["ranking_snapshot"] = self._ranking_snapshot(item)
        record["updated_at"] = now
        record.setdefault("implementation_history", [])
        record.setdefault("review_comment", "")
        record.setdefault("reviewer", "")
        record.setdefault("review_date", "")


class CountingHumanReviewEngine(HumanReviewEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_call_count = 0

    def update_review(self, *args, **kwargs):
        self.update_call_count += 1
        return super().update_review(*args, **kwargs)


class HumanReviewOperationTest(unittest.TestCase):
    def setUp(self):
        self.tmp_parent = Path("reports") / "test_tmp"
        self.tmp_parent.mkdir(parents=True, exist_ok=True)
        self.root = self.tmp_parent / f"human_review_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "candidate_review_status.json"
        self.report_path = self.root / "human_review_report.md"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def engine(self, ranking_engine=None, cls=HumanReviewEngine):
        return cls(
            status_db_path=self.db_path,
            report_path=self.report_path,
            ranking_engine=ranking_engine or FakeRankingEngine(),
        )

    def read_records(self):
        return json.loads(self.db_path.read_text(encoding="utf-8")).get("records", [])

    def first_record(self):
        return self.read_records()[0]

    def test_reproduce_old_watch_rollback_and_low_priority_fallback(self):
        ranking = FakeRankingEngine()
        old = self.engine(ranking, OldHumanReviewEngine)
        old.sync_from_ranking()
        self.assertEqual(self.first_record()["status"], "WATCH")
        old.update_review(candidate_name="CandidateA", status="WATCH", reviewer="tester", review_comment="human watch")
        ranking.item = ranking.item_for("A")
        old.sync_from_ranking()
        self.assertEqual(self.first_record()["status"], "REVIEW_REQUIRED")
        ranking.item = ranking.item_for("C")
        old.sync_from_ranking()
        self.assertEqual(self.first_record()["status"], "REVIEW_REQUIRED")

    def test_ranking_watch_new_record_has_ranking_source(self):
        self.engine().sync_from_ranking()
        record = self.first_record()
        self.assertEqual(record["status"], "WATCH")
        self.assertEqual(record["status_source"], "RANKING")

    def test_ranking_watch_updates_to_review_required_on_priority_a(self):
        ranking = FakeRankingEngine()
        engine = self.engine(ranking)
        engine.sync_from_ranking()
        ranking.item = ranking.item_for("A")
        engine.sync_from_ranking()
        record = self.first_record()
        self.assertEqual(record["status"], "REVIEW_REQUIRED")
        self.assertEqual(record["status_source"], "RANKING")

    def test_ranking_watch_low_priority_falls_back_to_review_required(self):
        ranking = FakeRankingEngine()
        engine = self.engine(ranking)
        engine.sync_from_ranking()
        ranking.item = ranking.item_for("C")
        engine.sync_from_ranking()
        record = self.first_record()
        self.assertEqual(record["status"], "REVIEW_REQUIRED")
        self.assertEqual(record["status_source"], "RANKING")

    def test_update_review_watch_has_human_source(self):
        engine = self.engine()
        engine.sync_from_ranking()
        engine.update_review(candidate_name="CandidateA", status="WATCH", reviewer="person1", review_comment="watch reason")
        record = self.first_record()
        self.assertEqual(record["status"], "WATCH")
        self.assertEqual(record["status_source"], "HUMAN")

    def test_human_watch_survives_priority_changes(self):
        ranking = FakeRankingEngine()
        engine = self.engine(ranking)
        engine.sync_from_ranking()
        engine.update_review(candidate_name="CandidateA", status="WATCH", reviewer="person1", review_comment="watch reason")
        ranking.item = ranking.item_for("A")
        engine.sync_from_ranking()
        self.assertEqual(self.first_record()["status"], "WATCH")
        self.assertEqual(self.first_record()["status_source"], "HUMAN")

    def test_terminal_statuses_are_preserved(self):
        for status in ["APPROVED", "REJECTED", "IMPLEMENTED", "REVERTED"]:
            with self.subTest(status=status):
                tmp_path = self.tmp_parent / f"terminal_{uuid.uuid4().hex}"
                tmp_path.mkdir(parents=True, exist_ok=True)
                try:
                    ranking = FakeRankingEngine()
                    engine = HumanReviewEngine(
                        status_db_path=tmp_path / "candidate_review_status.json",
                        report_path=tmp_path / "report.md",
                        ranking_engine=ranking,
                    )
                    engine.sync_from_ranking()
                    engine.update_review(candidate_name="CandidateA", status=status, reviewer="person1", review_comment="reason")
                    ranking.item = ranking.item_for("A")
                    engine.sync_from_ranking()
                    data = json.loads((tmp_path / "candidate_review_status.json").read_text(encoding="utf-8"))
                    self.assertEqual(data["records"][0]["status"], status)
                    self.assertEqual(data["records"][0]["status_source"], "HUMAN")
                finally:
                    shutil.rmtree(tmp_path, ignore_errors=True)

    def test_missing_status_source_is_legacy_unknown_in_validator(self):
        self.db_path.write_text(
            json.dumps({"records": [{"candidate_id": "x", "status": "WATCH", "review_comment": "", "implementation_history": []}]}),
            encoding="utf-8",
        )
        result = HumanReviewQualityValidator(
            human_review_db=self.db_path,
            shadow_projects_path=self.root / "missing_shadow.json",
            report_md=self.root / "validator.md",
            report_json=self.root / "validator.json",
            report_csv=self.root / "validator.csv",
        ).validate(write_reports=False)
        self.assertEqual(result["candidate_rows"][0]["status_source"], "LEGACY_UNKNOWN")

    def test_update_review_old_signature_compatible(self):
        engine = self.engine()
        engine.sync_from_ranking()
        result = engine.update_review(candidate_name="CandidateA", status="APPROVED", review_comment="ok")
        self.assertEqual(result["status"], "updated")
        self.assertEqual(self.first_record()["reviewer"], "human")

    def test_structured_five_fields_are_saved(self):
        engine = self.engine()
        engine.sync_from_ranking()
        engine.update_review(
            candidate_name="CandidateA",
            status="APPROVED",
            reviewer="person1",
            review_comment="ok",
            expected_effect="fn down",
            side_effect="fp risk",
            additional_data_needed="next race",
            shadow_test_target="shadow target",
            recheck_condition="after 10 races",
        )
        details = self.first_record()["review_details"]
        self.assertEqual(details["expected_effect"], "fn down")
        self.assertEqual(details["side_effect"], "fp risk")
        self.assertEqual(details["additional_data_needed"], "next race")
        self.assertEqual(details["shadow_test_target"], "shadow target")
        self.assertEqual(details["recheck_condition"], "after 10 races")
        self.assertEqual(self.first_record()["implementation_history"][-1]["review_details"], details)

    def test_cli_dry_run_cancel_has_no_db_diff(self):
        engine = self.engine()
        engine.sync_from_ranking()
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        cli = HumanReviewCLI(engine=engine)
        result = cli.review(
            candidate_id=self.first_record()["candidate_id"],
            status="WATCH",
            reviewer="person1",
            review_comment="",
            dry_run=True,
        )
        after = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(before, after)

    def test_cli_save_calls_update_review_once(self):
        engine = CountingHumanReviewEngine(
            status_db_path=self.db_path,
            report_path=self.report_path,
            ranking_engine=FakeRankingEngine(),
        )
        engine.sync_from_ranking()
        cli = HumanReviewCLI(engine=engine)
        result = cli.review(
            candidate_id=self.first_record()["candidate_id"],
            status="WATCH",
            reviewer="person1",
            review_comment="watch reason",
            confirm=True,
        )
        self.assertEqual(result["status"], "updated")
        self.assertEqual(engine.update_call_count, 1)

    def test_cli_invalid_status_rejected(self):
        self.engine().sync_from_ranking()
        cli = HumanReviewCLI(engine=self.engine())
        result = cli.review(candidate_id="x", status="IMPLEMENTED", reviewer="person1", review_comment="no")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "cli_status_not_allowed")

    def test_cli_human_watch_filter_excludes_ranking_watch(self):
        engine = self.engine()
        engine.sync_from_ranking()
        cli = HumanReviewCLI(engine=engine)
        self.assertEqual(cli.list_candidates("human-watch"), [])
        engine.update_review(candidate_name="CandidateA", status="WATCH", reviewer="person1", review_comment="watch reason")
        self.assertEqual(len(cli.list_candidates("human-watch")), 1)

    def test_empty_candidate_list(self):
        cli = HumanReviewCLI(engine=self.engine())
        self.db_path.write_text(json.dumps({"records": []}), encoding="utf-8")
        self.assertEqual(cli.list_candidates("all"), [])

    def test_no_evidence(self):
        reader = HumanReviewEvidenceReader(self.root / "missing_improvement.json")
        result = reader.evidence_for_candidate({"candidate_name": "Nope", "candidate_type": "Evaluator"})
        self.assertEqual(result["matched_record_count"], 0)

    def test_undetermined_evidence(self):
        improvement = self.root / "improvement_candidates.json"
        improvement.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "race_id": "race_x",
                            "horse": "HorseA",
                            "attribution_candidates": [{"target": "CandidateA", "target_type": "Evaluator"}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = HumanReviewEvidenceReader(improvement).evidence_for_candidate(
            {"candidate_name": "CandidateA", "candidate_type": "Evaluator"}
        )
        self.assertEqual(result["matched_record_count"], 1)
        self.assertEqual(len(result["undetermined"]), 1)

    def test_temp_db_is_used_not_production_json(self):
        engine = self.engine()
        engine.sync_from_ranking()
        self.assertTrue(self.db_path.exists())
        self.assertTrue(str(self.db_path).startswith(str(self.root)))


if __name__ == "__main__":
    unittest.main()
