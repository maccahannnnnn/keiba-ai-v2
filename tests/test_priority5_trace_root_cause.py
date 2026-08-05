import unittest
from review.priority5_trace_root_cause_review import classify, run


class Priority5TraceRootCauseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.audit, cls.summary = run()

    def test_exactly_six_targets(self):
        self.assertEqual(len(self.rows), 6)

    def test_targets_are_unique(self):
        self.assertEqual(len({(r["race_id"], r["horse_number"]) for r in self.rows}), 6)

    def test_primary_cause_is_single(self):
        self.assertTrue(all(r["primary_cause"] and ";" not in r["primary_cause"] for r in self.rows))

    def test_secondary_flags_preserved(self):
        self.assertTrue(all(r["secondary_flags"] for r in self.rows))

    def test_legacy_group_count(self):
        self.assertEqual(sum(r["primary_cause"] == "LEGACY_SCHEMA_MISSING" for r in self.rows), 4)

    def test_source_review_and_report_missing_are_distinct(self):
        self.assertIn("SOURCE_MISSING", {r["missing_point"] for r in self.rows})
        self.assertIn("REPORT_MAPPING_MISSING", {r["missing_point"] for r in self.rows})

    def test_missing_is_not_automatically_causal(self):
        self.assertEqual(sum(r["fp_relationship"].startswith("A_") for r in self.rows), 0)

    def test_no_shadow_below_causal_three(self):
        self.assertFalse(self.summary["shadow_candidate"])

    def test_successful_controls_required(self):
        self.assertTrue(all(int(r["successful_buy_control_count"]) >= 1 for r in self.rows))

    def test_no_production_adapter_execution(self):
        import inspect, review.priority5_trace_root_cause_review as module
        source = inspect.getsource(module)
        self.assertNotIn("TargetTrialAdapter", source)
        self.assertNotIn("TargetResultAdapter", source)

    def test_priority5_completion(self):
        self.assertEqual(self.summary["priority5_judgment"], "PRIORITY5_COMPLETE_NO_CANDIDATE")

    def test_unconverged_not_reanalyzed(self):
        self.assertEqual(self.summary["unconverged_status"], "PAUSE_EVIDENCE_ACCUMULATION_ONLY")


if __name__ == "__main__":
    unittest.main()
