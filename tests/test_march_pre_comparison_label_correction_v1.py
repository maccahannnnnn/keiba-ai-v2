import json
import unittest
from pathlib import Path

from review.march_pre_comparison_label_correction_v1 import selection_label


class MarchPreComparisonLabelCorrectionTests(unittest.TestCase):
    def test_order_difference_is_match(self):
        self.assertEqual("MATCH", selection_label([2, 5], [5, 2], "PLAY_CONVERGED"))

    def test_membership_difference_is_divergent(self):
        self.assertEqual("DIVERGENT", selection_label([2, 5], [2, 6], "PLAY_CONVERGED"))

    def test_out_of_scope_is_not_compared(self):
        self.assertEqual("OUT_OF_SCOPE_RACE_STATE", selection_label([2], [2], "SKIP"))

    def test_frozen_affected_races_and_all_comparison_races(self):
        root = Path(__file__).resolve().parents[1]
        rows = json.loads((root / "reports" / "march_2026_historical_holdout_pre" / "same_volume_selection.json").read_text(encoding="utf-8"))["races"]
        corrected = {row["race_id"]: selection_label(row["current_horse_numbers"], row["v4_horse_numbers"], row["race_state"]) for row in rows}
        for race_id in ("race_20260328_hanshin_7R", "race_20260329_hanshin_9R", "race_20260329_nakayama_9R"):
            self.assertEqual("MATCH", corrected[race_id])
        self.assertEqual(16, sum(label == "MATCH" for label in corrected.values()))
        self.assertEqual(55, sum(label == "DIVERGENT" for label in corrected.values()))


if __name__ == "__main__":
    unittest.main()
