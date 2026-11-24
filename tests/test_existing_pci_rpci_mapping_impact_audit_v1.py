import csv
import json
import unittest
from pathlib import Path

from evaluation.target_trial_adapter import TargetTrialAdapter  # noqa: F401 - stabilizes package import order
from importer.target_history_importer import TargetHistoryImporter


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "existing_pci_rpci_mapping_impact_audit_v1"


class ExistingPciRpciMappingImpactAuditV1Tests(unittest.TestCase):
    SEMANTIC_CASES = (
        ("race_20260808_sapporo_11R_horses.csv", "テーオードレフォン", "2022/02/06", "50.4", "48.1"),
        ("race_20260808_niigata_7R_horses.csv", "レイニング", "2026/05/31", "56.1", "58.0"),
        ("race_20260809_chuukyou_8R_horses.csv", "メイショウジェンマ", "2026/07/26", "44.5", "43.0"),
        ("race_20260725_chuukyou_6R_horses.csv", "スーパージョック", "2026/04/25", "50.1", "54.4"),
        ("race_20260725_sapporo_11R_horses.csv", "エヴァンスウィート", "2026/07/04", "44.8", "51.2"),
    )

    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads(
            (OUT / "existing_pci_rpci_mapping_impact_summary_v1.json").read_text(encoding="utf-8")
        )
        with (OUT / "existing_pci_rpci_mapping_impact_horses_v1.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            cls.rows = list(csv.DictReader(handle))

    def test_cohort_sizes_are_fixed(self):
        baseline = self.summary["cohorts"]["BASELINE_34"]
        shadow = self.summary["cohorts"]["SHADOW_20260808_20260809"]
        self.assertEqual((baseline["race_count"], baseline["horse_count"]), (34, 448))
        self.assertEqual((shadow["race_count"], shadow["horse_count"]), (16, 223))
        self.assertEqual(len(self.rows), 671)

    def test_past_performance_is_swap_invariant(self):
        self.assertTrue(all(float(row["past_performance_delta"]) == 0 for row in self.rows))

    def test_track_condition_is_swap_invariant(self):
        self.assertTrue(all(float(row["track_condition_delta"]) == 0 for row in self.rows))

    def test_lap_is_directional_and_changes(self):
        baseline = self.summary["cohorts"]["BASELINE_34"]["lap_score_delta"]
        shadow = self.summary["cohorts"]["SHADOW_20260808_20260809"]["lap_score_delta"]
        self.assertEqual(baseline["positive_count"] + baseline["negative_count"], 90)
        self.assertEqual(shadow["positive_count"] + shadow["negative_count"], 36)

    def test_downstream_material_counts(self):
        baseline = self.summary["cohorts"]["BASELINE_34"]
        shadow = self.summary["cohorts"]["SHADOW_20260808_20260809"]
        self.assertEqual((baseline["ranking_changed_count"], baseline["top5_changed_count"]), (68, 6))
        self.assertEqual((baseline["decision_changed_count"], baseline["buy_changed_count"]), (11, 0))
        self.assertEqual((shadow["ranking_changed_count"], shadow["top5_changed_count"]), (36, 6))
        self.assertEqual((shadow["decision_changed_count"], shadow["buy_changed_count"]), (3, 3))

    def test_shadow_buy_count_changes_by_three(self):
        shadow = self.summary["cohorts"]["SHADOW_20260808_20260809"]
        self.assertEqual((shadow["current_buy_count"], shadow["correct_buy_count"]), (7, 10))
        self.assertEqual(shadow["buy_count_delta"], 3)

    def test_official_baseline_is_not_recalculated(self):
        context = self.summary["official_baseline_context"]
        self.assertEqual(context["official_buy_count"], 40)
        self.assertEqual(context["official_buy_place_rate"], 25.64)
        self.assertFalse(self.summary["official_baseline_value_changed"])

    def test_classification_and_safety(self):
        self.assertEqual(self.summary["classification"], "MATERIAL_PRODUCTION_IMPACT")
        self.assertEqual(self.summary["safety"]["status"], "PASS")
        self.assertEqual(self.summary["zero_delta"]["status"], "PASS")
        self.assertEqual(self.summary["safety"]["replay_execution_count"], 0)

    def test_fixed_history_pci_rpci_semantics(self):
        importer = TargetHistoryImporter()
        for file_name, horse_name, race_date, expected_rpci, expected_pci in self.SEMANTIC_CASES:
            with self.subTest(file=file_name, horse=horse_name, race_date=race_date):
                histories = importer.load(ROOT / "data" / "analysis" / file_name)
                self.assertIn(horse_name, histories)
                matching = [run for run in histories[horse_name].runs if run.race_date == race_date]
                self.assertEqual(len(matching), 1)
                run = matching[0]
                self.assertEqual(run.rpci, expected_rpci)
                self.assertEqual(run.pci, expected_pci)
                self.assertNotEqual((run.rpci, run.pci), (expected_pci, expected_rpci))


if __name__ == "__main__":
    unittest.main()
