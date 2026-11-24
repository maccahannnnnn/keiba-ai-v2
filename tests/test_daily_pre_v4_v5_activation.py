import math
import unittest

import numpy as np

from review.prospective_three_system_pre_freeze_v1 import (
    ACTIVE_EFFECTIVE_DATE,
    ACTIVE_MODEL_SHA256,
    ACTIVE_MODEL_VERSION,
    ACTIVE_TRAINING_CUTOFF,
    TRANSFORMED,
    Stop,
    load_active_daily_v4,
    run,
)


class DailyPreV4V5ActivationTest(unittest.TestCase):
    def test_active_reference_loads_v5_and_predicts(self):
        model, scaler, identity, indexes = load_active_daily_v4()
        self.assertEqual(identity["model_version"], ACTIVE_MODEL_VERSION)
        self.assertEqual(identity["model_sha256"], ACTIVE_MODEL_SHA256)
        self.assertEqual(identity["training_cutoff"], ACTIVE_TRAINING_CUTOFF)
        self.assertEqual(identity["activation_effective_date"], ACTIVE_EFFECTIVE_DATE)
        self.assertEqual(len(TRANSFORMED), 21)
        self.assertEqual(set(indexes), {"active_v4_model", "active_v4_dataset"})
        probability = float(model.predict_proba(scaler.transform(np.zeros((1, 21), dtype=float)))[0, 1])
        self.assertTrue(math.isfinite(probability))
        self.assertGreaterEqual(probability, 0.0)
        self.assertLessEqual(probability, 1.0)

    def test_dates_before_activation_are_rejected_before_input_access(self):
        with self.assertRaisesRegex(Stop, "ACTIVE_V4_NOT_EFFECTIVE_FOR_DATE:20260913"):
            run("20260913", None, None)


if __name__ == "__main__":
    unittest.main()
