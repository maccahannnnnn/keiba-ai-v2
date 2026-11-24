from __future__ import annotations

import json
import unittest
from pathlib import Path

from review.full_race_observation_operational_validator_v1 import validate


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/full_race_observation_finalization_v1"


class FullRaceObservationOperationalV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads((OUT / "full_race_observation_finalization_summary_v1.json").read_text(encoding="utf-8"))
        cls.provenance = json.loads((OUT / "full_race_observation_provenance_v1.json").read_text(encoding="utf-8"))

    def test_96_races_and_1146_horses_are_finalized(self):
        self.assertEqual((self.summary["race_count"], self.summary["horse_count"]), (96, 1146))

    def test_existing_and_new_race_counts(self):
        self.assertEqual((self.summary["existing_result_reused_race_count"], self.summary["new_result_placed_race_count"]), (25, 71))
        self.assertEqual(self.summary["existing_result_overwrite_count"], 0)

    def test_all_eight_populations_are_complete(self):
        self.assertEqual((self.summary["population_count"], self.summary["complete_population_count"], self.summary["incomplete_population_count"]), (8, 8, 0))
        self.assertEqual(self.summary["missing_race_list"], [])

    def test_observation_guards_are_fixed(self):
        self.assertEqual((self.summary["baseline_membership"], self.summary["kpi_eligible"], self.summary["production_evidence"]), ("EXCLUDED", "NO", "NO"))
        self.assertEqual(self.summary["prediction_output_in_manifest_count"], 0)

    def test_provenance_has_192_files_and_no_overwrite(self):
        self.assertEqual(len(self.provenance["files"]), 192)
        self.assertEqual(self.provenance["existing_result_overwrite_count"], 0)
        self.assertEqual(sum(row["placement_mode"] == "EXISTING_RESULT_REUSED" for row in self.provenance["files"]), 50)
        self.assertEqual(sum(row["placement_mode"] == "NEW_BULK_RESULT_PLACED" for row in self.provenance["files"]), 142)

    def test_human_evidence_is_linked_without_correction(self):
        self.assertEqual(self.provenance["human_review_decision"], "BULK_RESULT_CORRECT_5_OF_5_EXISTING_FILES_NOT_CORRECTED")

    def test_operational_validator_passes(self):
        result = validate()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["result_file_sha_failure_count"], 0)

    def test_no_trend_bias_or_ml_execution(self):
        result = validate()
        self.assertEqual(result["trend_bias_ml_execution_count"], 0)
        self.assertEqual(result["prediction_ranking_decision_buy_recalculation_count"], 0)


if __name__ == "__main__":
    unittest.main()
