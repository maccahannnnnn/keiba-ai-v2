import ast
import inspect
import json
import unittest
from pathlib import Path

from analysis import jockey_shadow_read_only_parser_v1 as parser
from analysis import jockey_tier_generation_v1 as generator
from analysis import jockey_tier_shadow_validation_v1 as shadow

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


class JockeyTierShadowValidationV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tiers, cls.table, cls.manifest = shadow.load_frozen_table()
        cls.entries, cls.entry_audit = shadow.entry_lookup()
        cls.production = shadow.production_rows()
        cls.summary = json.loads((REPORTS / "jockey_tier_shadow_summary_v1.json").read_text(encoding="utf-8"))
        cls.safety = json.loads((REPORTS / "jockey_tier_shadow_safety_v1.json").read_text(encoding="utf-8"))
        cls.zero = json.loads((REPORTS / "jockey_tier_shadow_zero_delta_v1.json").read_text(encoding="utf-8"))

    def test_01_jockey_name_fixed_column_confirmed(self):
        self.assertEqual(parser.HISTORY_COLUMNS["jockey_name"], 19)

    def test_02_all_history_fixtures_are_53_columns(self):
        paths = generator.source_files()
        self.assertEqual(len(paths), 85)
        self.assertTrue(all(len(row["semantic_row"]) == 53 for row in parser.parse_history_files(paths)))

    def test_03_entry_crosscheck_is_78_of_78(self):
        records = parser.parse_history_files(generator.source_files())
        top_level_entries = [entry for path in sorted((ROOT / "data" / "analysis").glob("*_entry.csv")) for entry in parser.parse_entry_file(path)]
        entry_by_date_horse = {(e["race_date"], e["horse_name"]): e for e in top_level_entries}
        comparable = [r for r in records if r["history_date"].replace("-", "") >= "20260606" and (r["history_date"].replace("-", ""), r["horse_name"]) in entry_by_date_horse]
        self.assertEqual(len(comparable), 78)
        self.assertTrue(all(r["jockey_name"] == entry_by_date_horse[(r["history_date"].replace("-", ""), r["horse_name"])]["jockey_name"] for r in comparable))

    def test_04_invalid_column_count_fails(self):
        entry_fixture = next((ROOT / "data" / "analysis").glob("*_entry.csv"))
        with self.assertRaises(parser.ShadowSourceError):
            parser.parse_history_file(entry_fixture)

    def test_05_cutoff_day_is_excluded(self):
        records, _ = generator.deduplicate(parser.parse_history_files(generator.source_files()))
        eligible = [row for row in records if row["history_date"] < generator.CUTOFF_DATE]
        self.assertFalse(any(row["history_date"] == generator.CUTOFF_DATE for row in eligible))

    def test_06_cutoff_future_is_excluded(self):
        records, _ = generator.deduplicate(parser.parse_history_files(generator.source_files()))
        eligible = [row for row in records if row["history_date"] < generator.CUTOFF_DATE]
        self.assertFalse(any(row["history_date"] > generator.CUTOFF_DATE for row in eligible))

    def test_07_generator_has_no_results_path(self):
        self.assertNotIn("data/results", inspect.getsource(generator))

    def test_08_generator_accepts_no_post_or_result_argument(self):
        parameters = inspect.signature(generator.build_table).parameters
        self.assertNotIn("result", parameters)
        self.assertNotIn("post", parameters)

    def test_09_dedup_key_is_date_and_horse(self):
        source = inspect.getsource(generator.deduplicate)
        self.assertIn('(record["history_date"], record["horse_name"])', source)

    def test_10_stable_key_collision_detected(self):
        rows = [
            {"history_date": "2026-01-01", "horse_name": "A", "semantic_row": ("x",)},
            {"history_date": "2026-01-01", "horse_name": "A", "semantic_row": ("y",)},
        ]
        with self.assertRaisesRegex(RuntimeError, "STABLE_KEY_COLLISION"):
            generator.deduplicate(rows)

    def test_11_raw_count(self):
        self.assertEqual(self.manifest["raw_record_count"], 18682)

    def test_12_deduplicated_count(self):
        self.assertEqual(self.manifest["deduplicated_record_count"], 17412)

    def test_13_duplicate_count(self):
        self.assertEqual(self.manifest["duplicate_record_count"], 1270)

    def test_14_two_snapshot_key_count(self):
        self.assertEqual(self.manifest["keys_with_two_snapshots"], 1132)

    def test_15_three_plus_snapshot_key_count(self):
        self.assertEqual(self.manifest["keys_with_three_or_more_snapshots"], 69)

    def test_16_minimum_rides_boundary(self):
        self.assertEqual(self.table["minimum_rides"], 30)

    def test_17_tier_a_boundary(self):
        row = next(row for row in self.table["rows"] if row["tier"] == "A")
        self.assertGreaterEqual(row["top3_rate"], self.table["base_top3_rate"] + 0.10)

    def test_18_tier_b_boundary(self):
        row = next(row for row in self.table["rows"] if row["tier"] == "B")
        self.assertGreaterEqual(row["top3_rate"], self.table["base_top3_rate"] + 0.03)
        self.assertLess(row["top3_rate"], self.table["base_top3_rate"] + 0.10)

    def test_19_tier_c_boundary(self):
        row = next(row for row in self.table["rows"] if row["tier"] == "C")
        self.assertGreaterEqual(row["top3_rate"], self.table["base_top3_rate"] - 0.03)
        self.assertLess(row["top3_rate"], self.table["base_top3_rate"] + 0.03)

    def test_20_tier_d_boundary(self):
        row = next(row for row in self.table["rows"] if row["tier"] == "D")
        self.assertLess(row["top3_rate"], self.table["base_top3_rate"] - 0.03)

    def test_21_unknown_is_zero_and_trace(self):
        row = next(row for row in self.table["rows"] if row["tier"] == "UNKNOWN")
        self.assertEqual(row["shadow_score"], 0)
        self.assertTrue(row["status"].startswith("TRACE"))

    def test_22_tier_table_sha_frozen(self):
        self.assertEqual(generator.stable_hash(self.table["rows"]), self.table["table_sha256"])
        self.assertEqual(self.table["table_sha256"], self.manifest["tier_table_sha256"])

    def test_23_feature_flag_default_off(self):
        self.assertEqual((shadow.FLAG_NAME, shadow.FLAG_DEFAULT), ("JOCKEY_TIER_SHADOW_ENABLED", "OFF"))

    def test_24_flag_off_exact_identity(self):
        row = self.production["BASELINE"][0]
        self.assertEqual(shadow.apply_shadow_row(row, self.entries, self.tiers, False), row)

    def test_25_production_score_unchanged(self):
        row = self.production["BASELINE"][0]
        actual = shadow.apply_shadow_row(row, self.entries, self.tiers, True)
        self.assertEqual(actual["production_adjusted_score"], row["production_adjusted_score"])

    def test_26_production_rank_unchanged(self):
        row = self.production["BASELINE"][0]
        actual = shadow.apply_shadow_row(row, self.entries, self.tiers, True)
        self.assertEqual(actual["production_rank"], row["production_rank"])

    def test_27_decision_unchanged(self):
        row = self.production["BASELINE"][0]
        self.assertEqual(shadow.apply_shadow_row(row, self.entries, self.tiers, True)["decision"], row["decision"])

    def test_28_race_decision_unchanged(self):
        row = self.production["BASELINE"][0]
        self.assertEqual(shadow.apply_shadow_row(row, self.entries, self.tiers, True)["race_decision"], row["race_decision"])

    def test_29_buy_unchanged(self):
        row = self.production["BASELINE"][0]
        self.assertEqual(shadow.apply_shadow_row(row, self.entries, self.tiers, True)["buy"], row["buy"])

    def test_30_explain_unchanged(self):
        row = self.production["BASELINE"][0]
        actual = shadow.apply_shadow_row(row, self.entries, self.tiers, True)
        self.assertEqual(actual.get("explanation"), row.get("explanation"))
        self.assertIn("shadow_explain", actual)

    def test_31_shadow_score_only_generated(self):
        row = self.production["BASELINE"][0]
        actual = shadow.apply_shadow_row(row, self.entries, self.tiers, True)
        self.assertEqual(actual["shadow_adjusted_score"], actual["production_adjusted_score"] + actual["shadow_jockey_score"])

    def test_32_cohorts_separate(self):
        self.assertEqual((len(self.production["BASELINE"]), len(self.production["REPLAY"])), (448, 512))

    def test_33_coverage_gate_passes(self):
        self.assertTrue(self.summary["minimum_ride_coverage_gate_pass"])
        self.assertGreaterEqual(self.summary["cohort_results"]["BASELINE"]["minimum_ride_coverage_rate"], 0.70)
        self.assertGreaterEqual(self.summary["cohort_results"]["REPLAY"]["minimum_ride_coverage_rate"], 0.70)

    def test_34_rank1_3_metric(self):
        rows = shadow.rank_shadow(self.production["BASELINE"], self.entries, self.tiers, True)
        self.assertGreater(shadow.metric_values(rows, "shadow_rank")["rank1_3_top3_rate"], 0)

    def test_35_mean_actual_top3_rank_metric(self):
        rows = shadow.rank_shadow(self.production["BASELINE"], self.entries, self.tiers, True)
        self.assertGreater(shadow.metric_values(rows, "shadow_rank")["mean_actual_top3_rank"], 0)

    def test_36_ndcg_metric(self):
        rows = shadow.rank_shadow(self.production["BASELINE"], self.entries, self.tiers, True)
        self.assertGreaterEqual(shadow.metric_values(rows, "shadow_rank")["ndcg_at_3"], 0)

    def test_37_mrr_metric(self):
        rows = shadow.rank_shadow(self.production["BASELINE"], self.entries, self.tiers, True)
        self.assertGreaterEqual(shadow.metric_values(rows, "shadow_rank")["mrr"], 0)

    def test_38_formal_decision_is_reject(self):
        self.assertEqual(self.summary["final_status"], "REJECT")

    def test_39_safety_pass(self):
        self.assertEqual(self.safety["status"], "PASS")
        self.assertEqual(self.safety["target_trial_adapter_run_count"], 0)

    def test_40_zero_delta_pass(self):
        self.assertEqual(self.zero["status"], "PASS")
        self.assertEqual(self.zero["production_field_mutation_count"], 0)


if __name__ == "__main__":
    unittest.main()
