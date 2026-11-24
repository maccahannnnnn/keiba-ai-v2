import copy
import inspect
import unittest

from review import historical_development_cohort_pre_freeze_generator_v1 as generator


class HistoricalDevelopmentCohortPreFreezeGeneratorV1Tests(unittest.TestCase):
    def _preflight(self, date, horses, rows):
        return {"status": "PASS", "date": date, "horse_count": horses, "ds_row_count": rows, "de_column_33_structural_mismatch_count": 0}

    def test_date_summaries_keep_independent_preflight_objects(self):
        first = self._preflight("20260627", 202, 2840)
        second = self._preflight("20260628", 208, 2804)
        one = generator.build_date_summary("20260627", first, 17, [], [], [])
        two = generator.build_date_summary("20260628", second, 17, [], [], [])
        self.assertEqual("20260627", one["preflight"]["date"])
        self.assertEqual(202, one["preflight"]["horse_count"])
        self.assertEqual("20260628", two["preflight"]["date"])
        self.assertIsNot(one["preflight"], two["preflight"])

    def test_second_preflight_mutation_cannot_change_first(self):
        first = self._preflight("20260627", 202, 2840)
        second = self._preflight("20260628", 208, 2804)
        one = generator.build_date_summary("20260627", first, 17, [], [], [])
        two = generator.build_date_summary("20260628", second, 17, [], [], [])
        two["preflight"]["horse_count"] = 999
        self.assertEqual(202, one["preflight"]["horse_count"])

    def test_invalid_or_duplicate_date_mapping_fails_closed(self):
        with self.assertRaises(generator.PreFreezeError):
            generator.validate_date_mapping({"20260627": self._preflight("20260627", 202, 2840)})
        with self.assertRaises(generator.PreFreezeError):
            generator.validate_date_mapping({"20260627": self._preflight("20260628", 208, 2804), "20260628": self._preflight("20260628", 208, 2804)})

    def test_generator_has_no_direct_result_adapter_import(self):
        source = inspect.getsource(generator)
        self.assertNotIn("TargetResultAdapter", source)
        self.assertIn("result_source_guard", source)

    def test_prediction_payload_comparison_is_deterministic(self):
        payload = {"race_id": "race_20260627_hakodate_7R", "ranked_results": [{"rank": 1, "buy": True}]}
        self.assertEqual(copy.deepcopy(payload), payload)
        generator._scan_forbidden_result_fields(payload)
        with self.assertRaises(generator.PreFreezeError):
            generator._scan_forbidden_result_fields({"actual_top3": True})

    def test_v1_root_cannot_be_overwritten(self):
        self.assertEqual(generator.PRE_V1_ROOT.name, "historical_development_cohort_20260627_20260628_pre_v1")
        self.assertNotEqual(generator.DEFAULT_OUTPUT_ROOT.resolve(), generator.PRE_V1_ROOT.resolve())


if __name__ == "__main__":
    unittest.main()
