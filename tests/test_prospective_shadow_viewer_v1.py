import csv
import tempfile
import unittest
from pathlib import Path

from analysis.prospective_shadow_viewer_v1 import FIELDS, ViewerInputError, compare_rows, run


class ProspectiveShadowViewerV1Tests(unittest.TestCase):
    def setUp(self):
        self.production = [
            {"race_id": "race_20260808_sapporo_1R", "rank": "1", "horse_name": "A", "decision": "BUY", "adjusted_score": "100"},
            {"race_id": "race_20260808_sapporo_1R", "rank": "2", "horse_name": "B", "decision": "PASS", "adjusted_score": "99"},
            {"race_id": "race_20260808_sapporo_1R", "rank": "3", "horse_name": "C", "decision": "CAUTION", "adjusted_score": "90"},
        ]
        self.entries = {
            ("race_20260808_sapporo_1R", "A"): {"jockey_name": "JA"},
            ("race_20260808_sapporo_1R", "B"): {"jockey_name": "JB"},
            ("race_20260808_sapporo_1R", "C"): {"jockey_name": "JC"},
        }
        self.tiers = {
            "JA": {"tier": "C", "shadow_score": -2},
            "JB": {"tier": "A", "shadow_score": 2},
            "JC": {"tier": "B", "shadow_score": 1},
        }

    def test_flag_off_is_exact_copy(self):
        off = compare_rows(self.production, self.entries, self.tiers, enabled=False)
        self.assertEqual(off, self.production)
        self.assertIsNot(off, self.production)

    def test_shadow_rank_and_rank_slot_projection(self):
        rows = compare_rows(self.production, self.entries, self.tiers, enabled=True)
        by_name = {row["horse_name"]: row for row in rows}
        self.assertEqual(by_name["B"]["Shadow_rank"], 1)
        self.assertEqual(by_name["B"]["Shadow_decision"], "BUY")
        self.assertTrue(by_name["B"]["Shadow_buy"])
        self.assertTrue(by_name["B"]["buy_changed"])
        self.assertEqual(by_name["B"]["rank_change"], 1)
        self.assertIn("NOT_DECISION_ENGINE_OUTPUT", by_name["B"]["comment"])
        self.assertEqual(sorted(row["Production_decision"] for row in rows), sorted(row["Shadow_decision"] for row in rows))

    def test_unknown_jockey_is_neutral_trace(self):
        tiers = dict(self.tiers); tiers.pop("JC")
        row = next(row for row in compare_rows(self.production, self.entries, tiers, enabled=True) if row["horse_name"] == "C")
        self.assertEqual(row["jockey_tier"], "UNKNOWN")
        self.assertEqual(row["tier_adjustment"], 0)
        self.assertIn("TRACE_UNKNOWN_JOCKEY_TIER", row["comment"])

    def test_missing_entry_fails(self):
        with self.assertRaisesRegex(ViewerInputError, "ENTRY_MISSING"):
            compare_rows(self.production, {}, self.tiers, enabled=True)

    def test_rank_sequence_fails(self):
        broken = [dict(row) for row in self.production]; broken[2]["rank"] = "4"
        with self.assertRaisesRegex(ViewerInputError, "PRODUCTION_RANK_SEQUENCE_INVALID"):
            compare_rows(broken, self.entries, self.tiers, enabled=True)

    def test_flag_off_writes_nothing(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            output = Path(temporary) / "out"
            result = run("20260808", enabled=False, output_dir=output)
            self.assertEqual(result["status"], "FLAG_OFF_NO_OUTPUT")
            self.assertFalse(output.exists())

    def test_missing_production_writes_pending_artifacts(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary); output = root / "out"
            result = run("20260808", enabled=True, production_path=root / "missing.csv", output_dir=output)
            self.assertEqual(result["status"], "INPUT_PENDING")
            compare = output / "20260808_shadow_compare.csv"
            with compare.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle); self.assertEqual(next(reader), FIELDS); self.assertEqual(list(reader), [])
            self.assertIn("INPUT_PENDING", (output / "20260808_shadow_summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
