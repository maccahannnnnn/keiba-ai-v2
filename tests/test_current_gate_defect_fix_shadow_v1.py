import unittest
from unittest.mock import patch

from engine.decision_engine import DecisionEngine
from engine.shadow_buy_decision_engine import ShadowBUYDecisionEngine
from review import current_gate_defect_fix_shadow_v1 as subject


class GateFixTests(unittest.TestCase):
    def test_a1_exact_duplicates_only(self):
        engine = DecisionEngine()
        risks = ["展開面の不安", "展開面の不安", "展開不向き"]
        self.assertEqual(len(engine._major_risks(risks)), 3)
        engine._major_risks = subject.MethodType(subject._a1_major_risks, engine)
        self.assertEqual(engine._major_risks(risks), ["展開面の不安", "展開不向き"])
        self.assertFalse(engine._major_risks(["当日バイアス情報が限定的"]))

    def test_a1_penalty_uses_deduplicated_major_count(self):
        item = {"final_risks": ["展開面の不安", "展開面の不安"]}
        original = DecisionEngine()
        baseline_risks = []
        baseline = original._apply_strengths_and_risks(item, 1.0, [], baseline_risks)
        corrected = DecisionEngine()
        corrected._major_risks = subject.MethodType(subject._a1_major_risks, corrected)
        corrected_risks = []
        shadow = corrected._apply_strengths_and_risks(item, 1.0, [], corrected_risks)
        self.assertAlmostEqual(shadow - baseline, 0.12)
        self.assertIn("重大リスクが複数", baseline_risks)
        self.assertNotIn("重大リスクが複数", corrected_risks)

    def test_a1_keeps_distinct_major_risks_and_other_penalty(self):
        item = {"final_risks": ["展開面の不安", "展開不向き"]}
        baseline = DecisionEngine()._apply_strengths_and_risks(item, 1.0, [], [])
        corrected = DecisionEngine()
        corrected._major_risks = subject.MethodType(subject._a1_major_risks, corrected)
        self.assertEqual(corrected._apply_strengths_and_risks(item, 1.0, [], []), baseline)

    def test_a2_only_synthesized_decision_text(self):
        engine = ShadowBUYDecisionEngine(enabled=True)
        engine._risks = subject.MethodType(subject._a2_risks, engine)
        horse = {"decision_risks": ["重大リスクが複数", "重大リスクが複数の懸念", "出走不能"],
                 "final_risks": ["距離不適"], "risk_factors": ["取消"]}
        self.assertEqual(engine._risks(horse), ["重大リスクが複数の懸念", "出走不能", "距離不適", "取消"])
        self.assertNotIn("重大リスクが複数", engine._risks(horse))

    def test_a2_preserves_severe_and_count_guards(self):
        engine = ShadowBUYDecisionEngine(enabled=True)
        engine._risks = subject.MethodType(subject._a2_risks, engine)
        risks = engine._risks({"decision_risks": ["重大リスクが複数", "取消", "出走不能"]})
        self.assertEqual(risks, ["取消", "出走不能"])
        self.assertTrue(engine._has_keyword(" ".join(risks), engine.SEVERE_RISK_KEYWORDS))
        self.assertEqual(len(risks), 2)

    def test_rc1_engine_is_patch_target_and_independent(self):
        from evaluation.target_trial_adapter import TargetTrialAdapter
        adapter = TargetTrialAdapter(learning_phase2_enabled=False, enable_learning_candidate_engine=False)
        other = adapter.shadow_buy_decision_engine
        subject.configure_adapter(adapter, subject.GateFixConfig(True, True))
        self.assertEqual(adapter.decision_engine._major_risks(["展開面の不安"] * 2), ["展開面の不安"])
        self.assertNotIn("重大リスクが複数", adapter.buy_v1_rc1_engine.shadow_engine._risks(
            {"decision_risks": ["重大リスクが複数"]}))
        self.assertEqual(other._risks({"decision_risks": ["重大リスクが複数"]}), ["重大リスクが複数"])

    def test_all_off_is_existing_runner_and_patches_restore(self):
        original = subject.raw_runner.TargetTrialAdapter
        with patch.object(subject.raw_runner, "run_new", return_value={"unchanged": True}) as runner:
            self.assertEqual(subject.run_race("race_test", object(), subject.GateFixConfig()), {"unchanged": True})
            self.assertEqual(runner.call_count, 1)
            self.assertIs(subject.raw_runner.TargetTrialAdapter, original)
        with patch.object(subject.raw_runner, "run_new", side_effect=ValueError("synthetic")):
            for config in (subject.GateFixConfig(True, False), subject.GateFixConfig(False, True),
                           subject.GateFixConfig(True, True)):
                with self.assertRaises(ValueError):
                    subject.run_race("race_test", object(), config)
                self.assertIs(subject.raw_runner.TargetTrialAdapter, original)


if __name__ == "__main__":
    unittest.main()
