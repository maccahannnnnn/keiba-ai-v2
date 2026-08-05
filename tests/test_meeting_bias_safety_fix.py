from __future__ import annotations

import ast
import csv
import hashlib
import unittest
from pathlib import Path

from engine.meeting_bias_evidence_extractor import MeetingBiasEvidenceExtractor
from review.diagnostic_safety_validator import DiagnosticSafetyValidator
from review.meeting_bias_diagnostic_shadow import MeetingBiasDiagnosticShadow
from review.meeting_bias_read_only_collector import MeetingBiasReadOnlyCollector
from review.meeting_stage_resolver import MeetingStageResolver


ROOT = Path(__file__).resolve().parents[1]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class MeetingBiasSafetyFixTest(unittest.TestCase):
    def test_extractor_has_no_production_adapter_dependency(self) -> None:
        source = (ROOT / "engine" / "meeting_bias_evidence_extractor.py").read_text(encoding="utf-8")
        self.assertNotIn("TargetTrialAdapter", source)
        self.assertNotIn("TargetResultAdapter", source)
        tree = ast.parse(source)
        run_calls = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"adapter", "target_adapter", "trial_adapter"}
        ]
        self.assertEqual([], run_calls)

    def test_extractor_does_not_reference_protected_db_paths(self) -> None:
        source = (ROOT / "engine" / "meeting_bias_evidence_extractor.py").read_text(encoding="utf-8")
        self.assertNotIn("learning/improvement_candidates.json", source)
        self.assertNotIn("candidate_review_status.json", source)
        self.assertNotIn("shadow_projects.json", source)

    def test_collector_reads_saved_artifacts_with_provenance(self) -> None:
        result = MeetingBiasReadOnlyCollector(root=ROOT).collect()
        self.assertEqual("NO", result["production_adapter_used"])
        self.assertEqual("NO", result["evaluator_reexecuted"])
        self.assertEqual("NO", result["decision_recalculated"])
        self.assertEqual("NO", result["buy_recalculated"])
        self.assertEqual("NO", result["result_data_used_as_evaluation_input"])
        self.assertGreaterEqual(len(result["race_records"]), 1)
        self.assertGreaterEqual(len(result["source_manifest"]), 1)
        first = result["source_manifest"][0]
        self.assertTrue(first.get("source_sha256"))
        self.assertEqual("READ_ONLY_SAVED_ARTIFACTS", first.get("replay_mode"))

    def test_extractor_writes_only_configured_report_paths(self) -> None:
        protected = [
            ROOT / "learning" / "improvement_candidates.json",
            ROOT / "learning" / "candidate_review_status.json",
            ROOT / "reports" / "shadow_validation" / "shadow_projects.json",
        ]
        before = {path: file_hash(path) for path in protected if path.exists()}
        temp = ROOT / "reports" / "meeting_bias_safety_test_output"
        temp.mkdir(parents=True, exist_ok=True)
        for path in temp.glob("meeting_bias_*"):
            path.unlink()
        extractor = MeetingBiasEvidenceExtractor(
            evidence_path=temp / "meeting_bias_read_only_evidence_v1.json",
            source_manifest_path=temp / "meeting_bias_source_manifest_v1.json",
            metrics_path=temp / "meeting_bias_diagnostic_safety_v1.json",
            report_path=temp / "meeting_bias_candidate_report_v1.md",
        )
        metrics = extractor.extract()
        self.assertFalse(metrics.get("learning_candidate_update", {}).get("learning_write_enabled", True))
        self.assertTrue((temp / "meeting_bias_read_only_evidence_v1.json").exists())
        self.assertTrue((temp / "meeting_bias_source_manifest_v1.json").exists())
        self.assertTrue((temp / "meeting_bias_diagnostic_safety_v1.json").exists())
        self.assertTrue((temp / "meeting_bias_candidate_report_v1.md").exists())
        after = {path: file_hash(path) for path in protected if path.exists()}
        self.assertEqual(before, after)

    def test_diagnostic_safety_validator_passes_meeting_bias_targets(self) -> None:
        result = DiagnosticSafetyValidator(
            script_paths=[
                ROOT / "engine" / "meeting_bias_evidence_extractor.py",
                ROOT / "review" / "meeting_bias_read_only_collector.py",
                ROOT / "review" / "meeting_stage_resolver.py",
            ]
        ).validate(write_reports=False)
        self.assertEqual("PASS", result["status"])
        self.assertEqual(0, result["dangerous_import_count"])
        self.assertEqual(0, result["dangerous_run_call_count"])
        self.assertEqual(0, result["production_write_count"])
        self.assertEqual(0, result["learning_write_count"])
        self.assertEqual(0, result["human_review_write_count"])
        self.assertEqual(0, result["shadow_project_write_count"])
        self.assertFalse(result["hash_changed"])

    def test_meeting_stage_resolver_three_day_relative_split(self) -> None:
        resolver = MeetingStageResolver(root=ROOT)
        calendar = {
            "tokyo": [
                {"race_date": "20260601", "source_files": ["a"]},
                {"race_date": "20260608", "source_files": ["b"]},
                {"race_date": "20260615", "source_files": ["c"]},
            ]
        }
        first = resolver.resolve_one("race_20260601_tokyo_10R", calendar)
        middle = resolver.resolve_one("race_20260608_tokyo_10R", calendar)
        last = resolver.resolve_one("race_20260615_tokyo_10R", calendar)
        self.assertEqual("OPENING", first.meeting_stage)
        self.assertEqual("MIDDLE", middle.meeting_stage)
        self.assertEqual("CLOSING", last.meeting_stage)
        self.assertEqual("RELATIVE_OBSERVED_SEQUENCE", first.meeting_stage_source)
        self.assertTrue(last.shadow_testable)

    def test_meeting_stage_resolver_sorts_dates_and_deduplicates_days(self) -> None:
        resolver = MeetingStageResolver(root=ROOT)
        calendar = {
            "tokyo": [
                {"race_date": "20260615", "source_files": ["c", "c2"]},
                {"race_date": "20260601", "source_files": ["a"]},
                {"race_date": "20260608", "source_files": ["b"]},
            ]
        }
        result = resolver.resolve_one("race_20260608_tokyo_11R", calendar)
        self.assertEqual(2, result.meeting_day_index)
        self.assertEqual("MIDDLE", result.meeting_stage)
        self.assertTrue(result.source_sha256)

    def test_meeting_stage_resolver_unknown_when_data_insufficient(self) -> None:
        resolver = MeetingStageResolver(root=ROOT)
        calendar = {"tokyo": [{"race_date": "20260601", "source_files": ["a"]}]}
        result = resolver.resolve_one("race_20260601_tokyo_10R", calendar)
        self.assertEqual("UNKNOWN", result.meeting_stage)
        self.assertEqual("INSUFFICIENT_OBSERVED_DAYS", result.derivation_method)
        self.assertFalse(result.shadow_testable)

    def test_meeting_stage_resolver_separates_racecourses(self) -> None:
        resolver = MeetingStageResolver(root=ROOT)
        calendar = {
            "tokyo": [
                {"race_date": "20260601", "source_files": ["a"]},
                {"race_date": "20260608", "source_files": ["b"]},
                {"race_date": "20260615", "source_files": ["c"]},
            ],
            "kyoto": [
                {"race_date": "20260601", "source_files": ["d"]},
            ],
        }
        tokyo = resolver.resolve_one("race_20260615_tokyo_10R", calendar)
        kyoto = resolver.resolve_one("race_20260601_kyoto_10R", calendar)
        self.assertEqual("CLOSING", tokyo.meeting_stage)
        self.assertEqual("UNKNOWN", kyoto.meeting_stage)

    def test_collector_connects_meeting_stage_resolution(self) -> None:
        result = MeetingBiasReadOnlyCollector(root=ROOT).collect()
        resolved = [
            item
            for item in result["source_manifest"]
            if item.get("meeting_stage_resolution", {}).get("meeting_stage") != "UNKNOWN"
        ]
        self.assertGreaterEqual(len(resolved), 1)
        first = resolved[0]["meeting_stage_resolution"]
        self.assertEqual("RELATIVE_OBSERVED_SEQUENCE", first.get("meeting_stage_source"))
        self.assertTrue(first.get("source_sha256"))

    def test_collector_reads_legacy_review_pair_names(self) -> None:
        temp = ROOT / "reports" / "meeting_bias_safety_test_output" / "legacy_pair_test"
        review_dir = temp / "reports" / "review_20260101"
        review_dir.mkdir(parents=True, exist_ok=True)
        race_path = review_dir / "race_review.csv"
        horse_path = review_dir / "horse_review.csv"
        try:
            with race_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["race_id", "racecourse", "race_number"])
                writer.writeheader()
                writer.writerow({"race_id": "race_20260101_tokyo_10R", "racecourse": "tokyo", "race_number": "10R"})
            with horse_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["race_id", "horse_name", "ai_rank", "decision"])
                writer.writeheader()
                writer.writerow({"race_id": "race_20260101_tokyo_10R", "horse_name": "Sample", "ai_rank": "1", "decision": "PASS"})
            collector = MeetingBiasReadOnlyCollector(root=temp)
            pair = collector._latest_review_pair(review_dir)
            self.assertEqual(race_path, pair["race_csv"])
            self.assertEqual(horse_path, pair["horse_csv"])
        finally:
            for path in (race_path, horse_path):
                if path.exists():
                    path.unlink()

    def test_meeting_stage_diagnostic_readiness_is_cohort_level(self) -> None:
        resolver = MeetingStageResolver(root=ROOT)
        rows = [
            resolver.resolve_one(
                "race_20260601_tokyo_10R",
                {
                    "tokyo": [
                        {"race_date": "20260601", "source_files": ["a"]},
                        {"race_date": "20260608", "source_files": ["b"]},
                        {"race_date": "20260615", "source_files": ["c"]},
                    ]
                },
            )
            for _ in range(16)
        ]
        summary = resolver.summarize(rows)
        self.assertEqual("DIAGNOSTIC_ELIGIBLE", summary["diagnostic_readiness"]["level"])
        self.assertIn("COMPARABLE_STAGE_COUNT_BELOW_2", summary["diagnostic_readiness"]["missing_conditions"])

    def test_meeting_bias_diagnostic_shadow_is_review_only(self) -> None:
        source = (ROOT / "review" / "meeting_bias_diagnostic_shadow.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_names = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        self.assertNotIn("TargetTrialAdapter", imported_names)
        self.assertNotIn("TargetResultAdapter", imported_names)
        run_calls = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"adapter", "target_adapter", "trial_adapter", "result_adapter"}
        ]
        self.assertEqual([], run_calls)

    def test_observed_window_hash_is_stable_for_same_window(self) -> None:
        shadow = MeetingBiasDiagnosticShadow()
        evidence = [
            {"race_date": "20260802", "racecourse": "tokyo"},
            {"race_date": "20260801", "racecourse": "tokyo"},
        ]
        manifest = [
            {"meeting_stage_resolution": {"meeting_sequence_id": "tokyo_20260801_20260802"}}
        ]
        first = shadow._observed_window_hash(evidence, manifest)
        second = shadow._observed_window_hash(list(reversed(evidence)), manifest)
        self.assertEqual(first, second)
        self.assertTrue(first)


if __name__ == "__main__":
    unittest.main()
