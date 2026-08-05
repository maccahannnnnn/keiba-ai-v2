import inspect
import unittest
from review.ranking_diagnostic_phase_a import run


class RankingDiagnosticPhaseATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory, cls.trace, cls.compatibility, cls.gaps, cls.readiness = run()

    def test_four_dates_detected(self):
        self.assertEqual({row["race_date"] for row in self.compatibility}, {"20260725","20260726","20260801","20260802"})

    def test_source_versions_preserved(self):
        self.assertEqual([row["declared_source_version"] for row in self.compatibility], ["legacy","legacy","v2","v1"])

    def test_core_counts(self):
        self.assertEqual((self.readiness["usable_races"], self.readiness["usable_horses"]), (34,448))

    def test_missing_counts_are_explicit(self):
        self.assertTrue(all(int(row["nonempty_count"]) + int(row["missing_count"]) == int(row["row_count"]) for row in self.inventory))

    def test_legacy_current_not_pooled(self):
        self.assertTrue(all(row["pooling_judgment"] != "FULLY_POOLABLE" for row in self.compatibility))

    def test_stored_not_confused_with_derived(self):
        self.assertTrue(all(row["value_kind"] in {"STORED","NOT_STORED"} for row in self.inventory))

    def test_ability_not_imputed(self):
        gap = next(row for row in self.gaps if row["item"] == "ability_score")
        self.assertIn("112/448", gap["availability"])

    def test_weight_contribution_not_imputed(self):
        gap = next(row for row in self.gaps if row["item"] == "weighted contribution")
        self.assertIn("0/448", gap["availability"])

    def test_result_is_label_only(self):
        source = inspect.getsource(__import__("review.ranking_diagnostic_phase_a", fromlist=["x"]))
        self.assertNotIn("TargetTrialAdapter", source)
        self.assertNotIn("TargetResultAdapter", source)

    def test_partial_ready(self):
        self.assertEqual(self.readiness["judgment"], "PARTIAL_DIAGNOSTIC_READY")

    def test_no_shadow_progression(self):
        self.assertTrue(self.readiness["shadow_progression"].startswith("HOLD"))

    def test_no_production_candidate(self):
        self.assertEqual(self.readiness["production_candidate"], "NONE")


if __name__ == "__main__":
    unittest.main()
