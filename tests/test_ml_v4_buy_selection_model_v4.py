"""Read-only integrity checks for the frozen V4 Model v4 artifact set."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "ml_v4_buy_selection_model_v4"


class ModelV4IntegrityTest(unittest.TestCase):
    def test_frozen_recipe_and_boundary(self) -> None:
        manifest = json.loads((OUT / "training_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["rows"], 4100)
        self.assertEqual(manifest["positive"], 1389)
        self.assertEqual(manifest["negative"], 2711)
        self.assertFalse(manifest["relative_gap_selected"])
        features = json.loads((OUT / "feature_transform_schema.json").read_text(encoding="utf-8"))
        self.assertEqual(features["transformed_input_count"], 21)
        self.assertNotIn("adjusted_score_gap_to_top", features["transformed_model_input_columns"])
        deterministic = json.loads((OUT / "determinism_validation.json").read_text(encoding="utf-8"))
        self.assertEqual(deterministic["status"], "PASS")
        self.assertTrue(deterministic["predict_proba_exact"])
        safety = json.loads((OUT / "safety.json").read_text(encoding="utf-8"))
        self.assertEqual(safety["production_change"], 0)
        self.assertEqual(safety["august_30_result_access"], 0)
        self.assertEqual(safety["february_access"], 0)
        index = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
        self.assertTrue(all(hashlib.sha256((OUT / name).read_bytes()).hexdigest() == digest for name, digest in index.items()))


if __name__ == "__main__":
    unittest.main()
