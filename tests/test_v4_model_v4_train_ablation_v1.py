"""Read-only integrity checks for the non-evidential V4 ablation artifacts."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "v4_model_v4_train_ablation_v1"


class V4TrainAblationIntegrityTest(unittest.TestCase):
    def test_primary_and_safety_boundaries(self) -> None:
        folds = json.loads((OUT / "fold_results.json").read_text(encoding="utf-8"))["results"]
        self.assertEqual(len(folds), 28)
        by_block: dict[str, list[dict]] = {}
        for row in folds:
            by_block.setdefault(row["validation_block"], []).append(row)
        self.assertEqual(len(by_block), 7)
        for rows in by_block.values():
            self.assertEqual({r["condition"] for r in rows}, {"A", "B", "C", "D"})
            self.assertEqual(len({r["validation_fold_size"] for r in rows}), 1)
        safety = json.loads((OUT / "safety.json").read_text(encoding="utf-8"))
        self.assertEqual(safety["dataset_v3_mutation"], 0)
        self.assertEqual(safety["dataset_v4_mutation"], 0)
        self.assertFalse(safety["formal_model_artifact_saved"])
        self.assertEqual(safety["august_30_result_access"], 0)
        index = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
        self.assertTrue(all(hashlib.sha256((OUT / name).read_bytes()).hexdigest() == digest for name, digest in index.items()))


if __name__ == "__main__":
    unittest.main()
