"""Prior-day window and provenance checks for the v1 Rank1 selector wrapper."""
import hashlib
import unittest
from datetime import datetime, timezone
from pathlib import Path

from review import current_unconverged_rank1_prospective_shadow_v1 as v1
from review import current_unconverged_rank1_prospective_shadow_v2 as v2


TARGET = "20261031"
FIRST = "2026-10-31T09:50:00+09:00"


class PriorDayPreV2Tests(unittest.TestCase):
    def test_d_minus_2_rejected(self):
        with self.assertRaisesRegex(v2.Stop, "STOP_PRE_TOO_EARLY"):
            v2.check_window(TARGET, FIRST, datetime.fromisoformat("2026-10-29T20:00:00+09:00"))

    def test_d_minus_1_before_start_passes(self):
        self.assertTrue(v2.check_window(TARGET, FIRST, datetime.fromisoformat("2026-10-30T20:00:00+09:00")))

    def test_d_before_start_passes(self):
        self.assertFalse(v2.check_window(TARGET, FIRST, datetime.fromisoformat("2026-10-31T08:00:00+09:00")))

    def test_at_and_after_first_start_rejected(self):
        for value in ("2026-10-31T09:50:00+09:00", "2026-10-31T10:00:00+09:00"):
            with self.subTest(value=value), self.assertRaisesRegex(v2.Stop, "STOP_PRE_WINDOW_CLOSED"):
                v2.check_window(TARGET, FIRST, datetime.fromisoformat(value))

    def test_current_authority_mismatch_rejected(self):
        with self.assertRaisesRegex(v2.Stop, "STOP_CURRENT_AUTHORITY_MISMATCH"):
            v2.check_current_authority("a" * 64, "b" * 64)

    def test_input_sha_mismatch_rejected(self):
        expected = {"DG": "a", "DE": "b", "DS": "c"}
        observed = {"DG": "a", "DE": "b", "DS": "different"}
        with self.assertRaisesRegex(v2.Stop, "STOP_INPUT_AUTHORITY_MISMATCH"):
            v2.check_input_authority(expected, observed)

    def test_existing_formal_pre_rejected(self):
        with self.assertRaisesRegex(v2.Stop, "STOP_FORMAL_PRE_ALREADY_EXISTS"):
            v2.check_output_absent(Path(__file__))

    def test_result_free_wrapper(self):
        self.assertEqual(v2.verify_bindings(
            TARGET,
            v2.ROOT / "reports/prospective_prediction_20261031_formal_trace_v1",
            v2.ROOT / "reports/exp024_pl_same_volume/20261031_pre",
        )["input_sha256"], {
            "DG": "74ea4ed67a295f4c0a6a284717232b6161d768b88cced8f9380d00a3098c174c",
            "DE": "ea46bcb3d56da228ecab3d983ce13185b7deaefdd4b786bdb259c6bc41ad0e8d",
            "DS": "01b57db44b5f8fda5d423bfdaf1803f57e293b0396c41dc6903f7e3d7d6ff995",
        })
        self.assertNotIn("daily_result_list", Path(v2.__file__).read_text(encoding="utf8"))

    def test_v1_selection_semantics_identical(self):
        current = v2.ROOT / "reports/prospective_prediction_20261031_formal_trace_v1"
        old = v1.build_pre(current, TARGET)
        new = v2.build_selection(current, TARGET)
        self.assertEqual(old, new)
        self.assertEqual(old["selections"], new["selections"])
        self.assertEqual(v2.sha(v2.V1_RUNNER), v2.V1_RUNNER_SHA)


if __name__ == "__main__":
    unittest.main()
