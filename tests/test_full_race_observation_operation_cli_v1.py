from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "review/full_race_observation_operation_v1.py"


class FullRaceObservationOperationCliV1Tests(unittest.TestCase):
    def test_cli_requires_raw_and_output_with_optional_execute(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn('"--raw", action="append", required=True', text)
        self.assertIn('"--output-root", required=True', text)
        self.assertIn('"--execute", action="store_true"', text)
        self.assertIn('"--allowed-date"', text)
        self.assertIn('action="append"', text)

    def test_new_files_use_exclusive_create(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        modes = [node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open" and node.args and isinstance(node.args[0], ast.Constant)]
        self.assertIn("xb", modes)

    def test_conflict_stops_before_placement(self):
        text = SOURCE.read_text(encoding="utf-8")
        conflict = text.index('if reconciliation["conflict_count"]')
        placement = text.index('destination.open("xb")')
        self.assertLess(conflict, placement)
        self.assertIn('"new_result_placed_file_count": 0', text[conflict:placement])

    def test_no_canonical_guessing_or_production_execution(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("TargetBulkCanonicalReconciler", text)
        self.assertNotIn("TargetTrialAdapter", text)
        self.assertNotIn("Trend", text)
        self.assertNotIn("Bias", text)
        self.assertNotIn("Learning", text)


if __name__ == "__main__":
    unittest.main()
