from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from review import pl_adaptive_shadow_v1 as adaptive
from review import pl_forward_shadow_v1 as forward


class AdaptiveGuardTest(unittest.TestCase):
    def test_compact_date_normalization(self) -> None:
        self.assertEqual(adaptive._date_compact("2026-10-12"), "20261012")

    def test_candidate_scope_is_bounded(self) -> None:
        self.assertEqual(min(adaptive.CANDIDATES), "20260914")
        self.assertEqual(max(adaptive.CANDIDATES), "20261012")

    def test_forward_reference_is_immutable(self) -> None:
        adaptive._verify_forward_reference()

    def test_leakage_guard_condition(self) -> None:
        with self.assertRaisesRegex(adaptive.Stop, "STOP_ADAPTIVE_MODEL_CUTOFF_NOT_BEFORE_TARGET"):
            adaptive.ensure_cutoff_before("2026-10-12", "2026-10-12")
        adaptive.ensure_cutoff_before("2026-10-12", "2026-10-17")

    def test_future_dated_synthetic_payload_is_numerically_available(self) -> None:
        """Same frozen 10/12 PRE payload, future-dated in-memory only; no Result."""
        pointer, model, _ = adaptive._load_current_once()
        adaptive.ensure_cutoff_before(pointer["training_cutoff"], "2026-10-17")
        root = adaptive.ROOT / "reports" / "20261012_official_pre_v1_retry4" / "current_frozen"
        entry = json.loads((root / "race_index.json").read_text(encoding="utf-8"))["race_index"][0]
        payload = json.loads((root / entry["artifact"]).read_text(encoding="utf-8"))
        synthetic = copy.deepcopy(payload)
        synthetic["race_id"] = str(synthetic["race_id"]).replace("20261012", "20261017", 1)
        output = forward.infer_payloads(model, [("20261017", synthetic)], model_sha256=pointer["model_sha256"], input_pre_sha256="SYNTHETIC")
        self.assertEqual(output["races"][0]["inference_status"], "AVAILABLE")
        self.assertAlmostEqual(output["races"][0]["pl_probability_sum"], 3.0, places=8)

    def test_actual_runner_rejects_same_day_and_accepts_synthetic_future_fixture(self) -> None:
        source = adaptive.ROOT / "reports" / "20261012_official_pre_v1_retry4" / "current_frozen"
        with tempfile.TemporaryDirectory(prefix="pl_adaptive_test_", dir=adaptive.ROOT / ".tmp") as directory:
            root = Path(directory) / "fixture"; root.mkdir()
            entry = json.loads((source / "race_index.json").read_text(encoding="utf-8"))["race_index"][0]
            payload = json.loads((source / entry["artifact"]).read_text(encoding="utf-8"))
            payload["race_id"] = str(payload["race_id"]).replace("20261012", "20261017", 1)
            artifact = "race_20261017_synthetic_7R_prediction.json"
            (root / artifact).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            (root / "race_index.json").write_text(json.dumps({"race_index": [{"artifact": artifact}]}), encoding="utf-8")
            (root / "prediction_manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(adaptive.Stop, "STOP_ADAPTIVE_MODEL_CUTOFF_NOT_BEFORE_TARGET"):
                adaptive.adaptive_inference(root, root / "same_day.json", "20261012")
            result = adaptive.adaptive_inference(root, root / "future.json", "20261017")
            self.assertEqual(result["race_count"], 1)


if __name__ == "__main__":
    unittest.main()
