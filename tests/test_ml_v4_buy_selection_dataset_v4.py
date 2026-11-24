"""Read-only integrity checks for the frozen V4 Dataset v4 candidate."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v4"


class DatasetV4IntegrityTest(unittest.TestCase):
    def test_frozen_population_and_integrity(self) -> None:
        validation = json.loads((OUT / "validation.json").read_text(encoding="utf-8"))
        expected = {
            "dataset_rows": 4100, "positive": 1389, "negative": 2711,
            "TRUE_BUY_SUCCESS": 208, "BUY_FALSE_POSITIVE": 406,
            "TOP5_NONBUY_MISSED": 1181, "TRUE_BUY_ABSTENTION": 2305,
            "march_rows": 860, "march_positive": 281, "march_negative": 579,
            "march_top5_before_valid": 865, "march_invalid_excluded": 5,
        }
        self.assertEqual({key: validation[key] for key in expected}, expected)
        self.assertEqual(validation["parent_zero_delta"], "PASS")
        self.assertEqual(validation["march_reference_rebuild"], "PASS")
        self.assertEqual(validation["relative_gap"]["min"], -122.0)
        self.assertEqual(validation["relative_gap"]["max"], 0.0)
        self.assertEqual(validation["relative_gap"]["gap_zero_rows"], 174)
        self.assertEqual(validation["relative_gap"]["tie_max_races"], 1)
        index = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
        self.assertTrue(all(hashlib.sha256((OUT / name).read_bytes()).hexdigest() == digest for name, digest in index.items()))


if __name__ == "__main__":
    unittest.main()
