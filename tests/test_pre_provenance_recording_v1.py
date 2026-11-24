import copy
import json
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from review.ranking_provenance_exporter import (
    PRE_PROVENANCE_VERSION,
    collect_pre_provenance,
    export,
)


ROOT = Path(__file__).resolve().parents[1]


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True,
        check=True,
    ).stdout.strip()


def row(number, adjusted, decision):
    return {
        "race_id": "race_20260816_tokyo_1R",
        "race_date": "20260816",
        "racecourse": "tokyo",
        "race_number": "1R",
        "horse_name": f"Horse {number}",
        "horse_number": str(number),
        "final_score": adjusted - 10,
        "adjusted_score": adjusted,
        "ai_rank": number,
        "decision": decision,
        "source_version": "future_v1",
        "evaluator_provenance": [],
    }


class PreProvenanceRecordingTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / "reports" / "ranking_provenance" / "test_output" / "pre_provenance" / uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        self.code = self.root / "code.py"
        self.code.write_text("VALUE = 1\n", encoding="utf-8")
        git(self.root, "init")
        git(self.root, "config", "user.email", "pre-provenance@example.invalid")
        git(self.root, "config", "user.name", "PRE Provenance Test")
        git(self.root, "add", "code.py")
        git(self.root, "commit", "-m", "fixture")

    def test_clean_repository_records_commit_and_clean(self):
        data = collect_pre_provenance(
            self.root, "fixture.entrypoint", ("code.py",),
        )
        self.assertEqual(data["provenance_version"], PRE_PROVENANCE_VERSION)
        self.assertRegex(data["git_commit_sha"], r"^[0-9a-f]{40}$")
        self.assertEqual(data["git_worktree_status"], "CLEAN")
        self.assertEqual(data["provenance_status"], "PROVENANCE_COMPLETE")

    def test_dirty_repository_records_dirty(self):
        self.code.write_text("VALUE = 2\n", encoding="utf-8")
        data = collect_pre_provenance(
            self.root, "fixture.entrypoint", ("code.py",),
        )
        self.assertEqual(data["git_worktree_status"], "DIRTY")
        self.assertGreater(data["git_dirty_file_count"], 0)
        self.assertEqual(data["provenance_status"], "PROVENANCE_DIRTY_IDENTIFIED")

    def test_major_code_sha256_is_recorded(self):
        data = collect_pre_provenance(
            self.root, "fixture.entrypoint", ("code.py",),
        )
        self.assertRegex(data["major_code_sha256"]["code.py"], r"^[0-9a-f]{64}$")

    def test_git_unavailable_is_explicit_and_nonfatal(self):
        with patch("review.ranking_provenance_exporter.subprocess.run", side_effect=OSError("git unavailable")):
            data = collect_pre_provenance(
                self.root, "fixture.entrypoint", ("code.py",),
            )
        self.assertEqual(data["git_commit_sha"], "UNKNOWN")
        self.assertEqual(data["git_worktree_status"], "UNAVAILABLE")
        self.assertEqual(data["provenance_status"], "PROVENANCE_INSUFFICIENT")

    def test_export_manifest_adds_provenance_without_csv_schema_change(self):
        rows = [row(1, 120, "BUY"), row(2, 110, "PASS")]
        result = export(
            rows, self.root / "out", "20260816", "future_v1", self.code,
            execution_entrypoint="fixture.entrypoint",
        )
        manifest = json.loads(result["manifest_path"].read_text(encoding="utf-8"))
        self.assertIn("pre_execution_provenance", manifest)
        self.assertEqual(
            manifest["pre_execution_provenance"]["execution_entrypoint"],
            "fixture.entrypoint",
        )
        self.assertNotIn("git_commit_sha", result["summary_rows"][0])

    def test_git_failure_does_not_break_export(self):
        rows = [row(1, 120, "BUY")]
        with patch("review.ranking_provenance_exporter.subprocess.run", side_effect=OSError("git unavailable")):
            result = export(
                rows, self.root / "unavailable", "20260816", "future_v1", self.code,
                execution_entrypoint="fixture.entrypoint",
            )
        self.assertEqual(
            result["manifest"]["pre_execution_provenance"]["provenance_status"],
            "PROVENANCE_INSUFFICIENT",
        )

    def test_provenance_metadata_is_zero_delta_for_evaluation_fields(self):
        rows = [row(1, 120, "BUY"), row(2, 110, "PASS")]
        before = copy.deepcopy(rows)
        first = export(
            rows, self.root / "delta_a", "20260816", "future_v1", self.code,
            execution_entrypoint="fixture.entrypoint",
        )
        with patch("review.ranking_provenance_exporter.subprocess.run", side_effect=OSError("git unavailable")):
            second = export(
                rows, self.root / "delta_b", "20260816", "future_v1", self.code,
                execution_entrypoint="fixture.entrypoint",
            )
        self.assertEqual(first["summary_rows"], second["summary_rows"])
        self.assertEqual(first["long_rows"], second["long_rows"])
        self.assertEqual(rows, before)
        self.assertEqual([x["final_score"] for x in rows], [110, 100])
        self.assertEqual([x["ai_rank"] for x in rows], [1, 2])
        self.assertEqual([x["decision"] for x in rows], ["BUY", "PASS"])


if __name__ == "__main__":
    unittest.main()
