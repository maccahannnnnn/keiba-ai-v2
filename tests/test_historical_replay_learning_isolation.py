import ast
import inspect
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from evaluation.target_trial_adapter import TargetTrialAdapter
from review import historical_replay_runner as runner
from review.historical_replay_safety_validator import PROTECTED, snapshot


class HistoricalReplayLearningIsolationTests(unittest.TestCase):
    def test_default_true(self):
        self.assertTrue(inspect.signature(TargetTrialAdapter).parameters["enable_learning_candidate_engine"].default)

    def test_normal_mode_enabled(self):
        self.assertTrue(TargetTrialAdapter().enable_learning_candidate_engine)

    def test_historical_mode_disabled(self):
        self.assertFalse(TargetTrialAdapter(enable_learning_candidate_engine=False).enable_learning_candidate_engine)

    def test_runner_passes_false(self):
        self.assertIn("enable_learning_candidate_engine=False", Path(runner.__file__).read_text(encoding="utf-8"))

    def test_runner_does_not_redirect_writer(self):
        self.assertNotIn("LearningCandidateEngine(", Path(runner.__file__).read_text(encoding="utf-8"))

    def test_guard_wraps_generate_call(self):
        source=Path(inspect.getfile(TargetTrialAdapter)).read_text(encoding="utf-8")
        self.assertIn("if self.enable_learning_candidate_engine:", source)

    def test_disabled_result_is_explicit(self):
        source=Path(inspect.getfile(TargetTrialAdapter)).read_text(encoding="utf-8")
        self.assertIn('"status": "disabled"', source)

    def test_disabled_candidates_empty(self):
        source=Path(inspect.getfile(TargetTrialAdapter)).read_text(encoding="utf-8")
        self.assertIn('"candidates": []', source)

    def test_learning_tree_protected(self): self.assertIn("learning", PROTECTED)
    def test_learning_report_protected(self): self.assertIn("reports/improvement_candidates.md", PROTECTED)
    def test_learning_directory_protected(self): self.assertIn("reports/improvement_candidates", PROTECTED)

    def test_snapshot_stable_without_execution(self):
        self.assertEqual(snapshot(), snapshot())

    def test_only_one_generate_callsite(self):
        tree=ast.parse(Path(inspect.getfile(TargetTrialAdapter)).read_text(encoding="utf-8"))
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="generate" and isinstance(n.func.value,ast.Attribute) and n.func.value.attr=="learning_candidate_engine"]
        self.assertEqual(len(calls),1)

    def test_no_environment_toggle(self):
        source=Path(inspect.getfile(TargetTrialAdapter)).read_text(encoding="utf-8")
        self.assertNotIn("ENABLE_LEARNING_CANDIDATE_ENGINE",source)

    def test_no_result_dependency_added(self):
        signature=str(inspect.signature(TargetTrialAdapter))
        self.assertNotIn("result",signature.lower())


if __name__ == "__main__": unittest.main()
