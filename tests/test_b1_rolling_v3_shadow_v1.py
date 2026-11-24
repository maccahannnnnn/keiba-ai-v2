"""Isolated checks; no Result, PRE freeze, or real candidate output writes."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from review import b1_prospective_diagnostic_v1 as b1
from review import b1_rolling_v3_shadow_v1 as subject


class RollingShadowTests(unittest.TestCase):
    def test_model_snapshot_binds_registry_pointer_sha_and_target_date(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            version = "20261115_example"
            model_dir = root / "models/rolling_pl_jockey_v3/versions" / version
            model_dir.mkdir(parents=True)
            model = {"procedure_id": "ROLLING_PL_JOCKEY_V3", "training_end": "20261115",
                     "feature_names": list(subject.forward.FEATURE_NAMES),
                     "trainer_included": False, "scaler_mean": [0.0] * 21,
                     "scaler_scale": [1.0] * 21, "pl_coefficients": [0.0] * 19,
                     "jockey_beta": 1.25}
            model_path = model_dir / "model.json"
            model_path.write_text(json.dumps(model), encoding="utf-8")
            model_sha = subject.sha(model_path)
            manifest_path = model_dir / "manifest.json"
            manifest_path.write_text(json.dumps({"model_sha256": model_sha}), encoding="utf-8")
            manifest_sha = subject.sha(manifest_path)
            entry = {"event": "CANDIDATE_ACTIVATED", "version": version,
                     "model_sha256": model_sha, "manifest_sha256": manifest_sha,
                     "training_end": "20261115"}
            registry = root / "reports/rolling_learning_v3/candidate_registry.jsonl"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps(entry) + "\n", encoding="utf-8")
            pointer = {**entry, "procedure_id": "ROLLING_PL_JOCKEY_V3"}
            current = root / "models/rolling_pl_jockey_v3/current.json"
            current.write_text(json.dumps(pointer), encoding="utf-8")
            loaded = subject.model_snapshot("20261121", root)
            self.assertEqual(loaded["model_sha256"], model_sha)
            with self.assertRaisesRegex(subject.Stop, "STOP_MODEL_PIT_OR_PROCEDURE"):
                subject.model_snapshot("20261115", root)
            manifest_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(subject.Stop, "STOP_MODEL_OR_MANIFEST_SHA"):
                subject.model_snapshot("20261121", root)

    def test_rolling_probabilities_are_separate_and_reproducible(self):
        records = [{"race_id": "race_20261121_tokyo_1R", "horse_number": i,
                    "horse_name": f"horse{i}", "vector": np.asarray([float(i)] * 21)}
                   for i in range(1, 5)]
        snapshot = {"mean": np.zeros(21), "scale": np.ones(21),
                    "coefficients": np.asarray([0.1] + [0.0] * 18), "jockey_beta": 1.0}
        lifts = {1: 0.3, 2: 0.0, 3: -0.2, 4: 0.1}
        with patch.object(subject.forward, "_payload_records", return_value=records):
            left = subject.probabilities_for_race({"race_id": "race_20261121_tokyo_1R"}, lifts, snapshot)
            right = subject.probabilities_for_race({"race_id": "race_20261121_tokyo_1R"}, lifts, snapshot)
        self.assertEqual(left, right)
        self.assertAlmostEqual(sum(h["e1_rolling_p_top3"] for h in left), 3.0)
        self.assertAlmostEqual(sum(h["b1_rolling_p_top3"] for h in left), 3.0)
        self.assertNotEqual([h["e1_rolling_p_top3"] for h in left],
                            [h["b1_rolling_p_top3"] for h in left])
        with patch.object(subject.forward, "_payload_records", return_value=records):
            zero = subject.probabilities_for_race({"race_id": "race_20261121_tokyo_1R"}, lifts,
                                                   {**snapshot, "jockey_beta": 0.0})
        self.assertEqual([h["e1_rolling_p_top3"] for h in zero],
                         [h["b1_rolling_p_top3"] for h in zero])
        races = [{"race_id": "race_20261121_tokyo_1R", "current_k": 2,
                  "horses": [{"horse_number": h["horse_number"], "horse_name": h["horse_name"],
                              "candidate_p_top3": h["b1_rolling_p_top3"]} for h in left]}]
        selected = b1.select_b1(races, 2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(len({(h["race_id"], h["horse_number"]) for h in selected}), 2)

    def test_missing_jockey_feature_stops(self):
        records = [{"race_id": "race_20261121_tokyo_1R", "horse_number": i,
                    "horse_name": str(i), "vector": np.ones(21)} for i in range(1, 4)]
        snapshot = {"mean": np.zeros(21), "scale": np.ones(21),
                    "coefficients": np.zeros(19), "jockey_beta": 1.0}
        with patch.object(subject.forward, "_payload_records", return_value=records):
            with self.assertRaisesRegex(subject.Stop, "STOP_JOCKEY_HORSE_SET"):
                subject.probabilities_for_race({"race_id": "race_20261121_tokyo_1R"}, {1: 0.0}, snapshot)


if __name__ == "__main__":
    unittest.main()
