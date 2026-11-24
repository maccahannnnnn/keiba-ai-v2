from __future__ import annotations

import ast
import unittest
from pathlib import Path

from review.full_race_observation_finalizer_v1 import (
    CANONICAL_RESULT,
    EXPECTED_RAW_SHA,
    EXPECTED_SCHEMA_SHA,
    HUMAN_EVIDENCE,
    RAW,
    FullRaceObservationFinalizerV1,
    sha,
)


ROOT = Path(__file__).resolve().parents[1]


class FullRaceObservationFinalizerV1Tests(unittest.TestCase):
    def test_frozen_raw_and_schema_sha_match(self):
        self.assertEqual(sha(RAW), EXPECTED_RAW_SHA)
        self.assertEqual(sha(ROOT / "docs/target_bulk_result_schema_v1.json"), EXPECTED_SCHEMA_SHA)

    def test_canonical_result_and_human_evidence_exist(self):
        self.assertTrue(CANONICAL_RESULT.is_file())
        self.assertTrue(HUMAN_EVIDENCE.is_file())

    def test_runner_uses_exclusive_create_for_new_results(self):
        tree = ast.parse((ROOT / "review/full_race_observation_finalizer_v1.py").read_text(encoding="utf-8"))
        modes = [
            node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open"
            and node.args and isinstance(node.args[0], ast.Constant)
        ]
        self.assertIn("xb", modes)

    def test_runner_has_no_copy_overwrite_primitive(self):
        source = (ROOT / "review/full_race_observation_finalizer_v1.py").read_text(encoding="utf-8")
        self.assertNotIn("shutil.copy2", source)
        self.assertNotIn("shutil.copy(", source)
        self.assertNotIn("write_bytes(source", source)

    def test_completed_run_is_idempotent_and_writes_nothing(self):
        result = FullRaceObservationFinalizerV1().execute()
        self.assertTrue(result["idempotent_revalidation"])
        self.assertEqual(result["new_write_count_this_run"], 0)
        self.assertEqual((result["existing_result_reused_race_count"], result["new_result_placed_race_count"]), (25, 71))


if __name__ == "__main__":
    unittest.main()
