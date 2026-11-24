import unittest

from review import december_2025_all_frozen_systems_diagnostic_pre as panel


class DecemberDiagnosticPanelTests(unittest.TestCase):
    def setUp(self):
        self.manifest = panel.load_manifest()
        self.order = self.manifest["fixed_display_order"]
        self.families = {item["system_id"]: item["model_family_id"] for item in self.manifest["systems"]}

    def test_01_eight_systems_in_fixed_order(self):
        self.assertEqual(len(self.order), 8)
        self.assertEqual(self.order[0], "CURRENT")
        self.assertEqual(self.order[-1], "V4_MODEL_V3_REFERENCE")

    def test_02_v5_family_is_not_three_independent_votes(self):
        rows = panel.selection_bitmap([("r1", 1)], {"INDEPENDENT_V5": {("r1", 1)}, "FORMAL_V5": {("r1", 1)}, "DAILY_V5_REFERENCE": {("r1", 1)}}, self.order, self.families)
        self.assertEqual(rows[0]["system_selection_count"], 3)
        self.assertEqual(rows[0]["unique_model_family_selection_count"], 1)

    def test_03_not_in_scope_is_distinct_from_not_selected(self):
        rows = panel.selection_bitmap([("r1", 1)], {}, self.order, self.families, {system: set() for system in self.order})
        self.assertEqual(set(rows[0]["systems"].values()), {"NOT_IN_SCOPE"})

    def test_04_pairwise_has_twenty_eight_horse_and_race_entries(self):
        pairs = panel.pairwise_overlaps({"CURRENT": {("r1", 1)}, "INDEPENDENT_V5": {("r1", 1), ("r2", 2)}}, self.order)
        self.assertEqual(len(pairs), 28)
        pair = pairs["CURRENT__INDEPENDENT_V5"]
        self.assertIn("race_jaccard", pair)
        self.assertEqual(pair["horse_jaccard"]["numerator"], 1)

    def test_05_race_bitmap_is_deterministic(self):
        rows = panel.selection_bitmap([("r1", 1), ("r1", 2)], {"CURRENT": {("r1", 2)}}, self.order, self.families)
        self.assertEqual(panel.race_bitmap(rows, self.order)[0]["systems"]["CURRENT"], "SELECTED")

    def test_06_excluded_systems_are_frozen(self):
        self.assertIn("VOLUME_AUTHORITY", self.manifest["excluded_systems"])
        self.assertEqual(self.manifest["excluded_systems"]["EXP_022"], "DUPLICATE_FORMAL_V5")

    def test_07_public_runner_has_no_source_or_selection_arguments(self):
        self.assertEqual(panel.run_real_diagnostic_panel.__code__.co_argcount, 0)


if __name__ == "__main__":
    unittest.main()
