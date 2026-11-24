import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from review import track_condition_semantic_shadow_prospective_pre as pre
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.track_condition_semantic_shadow_v1 import run_race_pair, shadow_defaults

ROOT = Path(__file__).resolve().parents[1]


def control_fixture():
    control_rows = [
        {"horse_number": 1, "buy_v1_rc1_buy": True, "rank": 1, "adjusted_score": 100.0, "buy_v1_rc1_race_state": "PLAY_CONVERGED"},
        {"horse_number": 2, "buy_v1_rc1_buy": False, "rank": 2, "adjusted_score": 90.0, "buy_v1_rc1_race_state": "PLAY_CONVERGED"},
    ]
    frozen_rows = [{"horse_number": 1, "buy": True, "rank": 1, "adjusted_score": 100.0}, {"horse_number": 2, "buy": False, "rank": 2, "adjusted_score": 90.0}]
    return {"ranked_results": control_rows, "race_decision": "PLAY"}, {"ranked_results": frozen_rows, "race_decision": "PLAY", "buy_gate_trace": {"race": {"shadow_race_state": "PLAY_CONVERGED"}}}


class TrackConditionProspectivePreTests(unittest.TestCase):
    def setUp(self):
        self.protocol = pre.load_protocol()
        self.instant = datetime(2026, 9, 26, 1, tzinfo=timezone.utc)
        self.summary = {"date": "20260926"}
        self.provenance = {"target_date": "20260926", "generated_at": (self.instant - timedelta(minutes=1)).isoformat(), "result_data_access_count": 0}

    def _rehearsal_protocol(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["human_approval_freeze_date"] = "20260919"
        return protocol

    def _rehearsal_run(self, output: Path, independent: Path, written: dict | None = None):
        original_iterdir = Path.iterdir
        def output_iterdir(path):
            return iter(()) if path == output else original_iterdir(path)
        def capture_write(path, value):
            if written is not None:
                written[path.name] = value
        with patch.object(pre, "load_protocol", return_value=self._rehearsal_protocol()), patch.object(pre, "_write", capture_write), patch.object(Path, "mkdir"), patch.object(Path, "iterdir", output_iterdir):
            return pre.run("20260920", ROOT / "data/raw/prediction_input/DG260920.CSV", ROOT / "data/raw/prediction_input/DE260920.CSV", ROOT / "data/raw/prediction_input/DS260920.CSV", ROOT / "reports/daily_pre_prediction_20260920/current_frozen", independent, output, clock_utc=datetime(2026, 9, 20, 1, tzinfo=timezone.utc))

    def test_01_target_date_before_execution_date_jst_stops(self):
        with self.assertRaisesRegex(pre.Stop, "POST_EVENT_EXECUTION"):
            pre.validate_execution_date("20260925", self.instant)

    def test_02_target_date_on_or_after_execution_date_jst_passes(self):
        self.assertEqual(pre.validate_execution_date("20260926", self.instant), "20260926")
        self.assertEqual(pre.validate_execution_date("20260927", self.instant), "20260926")

    def test_03_output_inside_independent_root_stops(self):
        with self.assertRaisesRegex(pre.Stop, "OUTPUT_ROOT_ISOLATION"):
            pre.ensure_output_isolated(ROOT / "reports/independent_race_selection_prospective_protocol_v1_implementation/child", ROOT / "reports/independent_race_selection_prospective_protocol_v1_implementation", ROOT / "reports/daily_pre_prediction_20260920/current_frozen")

    def test_04_output_inside_current_frozen_root_stops(self):
        with self.assertRaisesRegex(pre.Stop, "OUTPUT_ROOT_ISOLATION"):
            pre.ensure_output_isolated(ROOT / "reports/daily_pre_prediction_20260920/current_frozen/child", ROOT / "reports/independent_race_selection_prospective_protocol_v1_implementation", ROOT / "reports/daily_pre_prediction_20260920/current_frozen")

    def test_05_independent_mutation_after_snapshot_stops(self):
        with patch.object(pre, "tree_hashes", return_value={"changed": "sha"}):
            with self.assertRaisesRegex(pre.Stop, "STOP_INDEPENDENT_PRE_MUTATED"):
                pre.verify_tree_unchanged({"original": "sha"}, ROOT, "STOP_INDEPENDENT_PRE_MUTATED")

    def test_06_final_independent_snapshot_remains_equal_after_rehearsal_writes(self):
        independent = ROOT / "reports/independent_race_selection_prospective_protocol_v1_implementation"; before = pre.tree_hashes(independent)
        output = ROOT / "reports/__trackcondition_mock_output__"; self._rehearsal_run(output, independent)
        self.assertEqual(before, pre.tree_hashes(independent))

    def test_07_g1_pass_fixture(self):
        self.assertEqual(pre.validate_gates("20260926", self.protocol, self.summary, self.provenance, self.instant)["G1"], "PASS")

    def test_08_g1_fail_fixture(self):
        with self.assertRaisesRegex(pre.Stop, "G1"):
            pre.validate_gates("20260923", self.protocol, self.summary, self.provenance, self.instant)

    def test_09_g2_pass_fixture(self):
        self.assertEqual(pre.validate_gates("20260926", self.protocol, self.summary, self.provenance, self.instant)["G2"], "PASS")

    def test_10_g2_fail_fixture(self):
        with self.assertRaisesRegex(pre.Stop, "G2"):
            pre.validate_gates("20260926", self.protocol, {"date": "20260927"}, self.provenance, self.instant)

    def test_11_g3_pass_fixture(self):
        self.assertEqual(pre.validate_gates("20260926", self.protocol, self.summary, self.provenance, self.instant)["G3"], "PASS")

    def test_12_g3_fail_fixture(self):
        with self.assertRaisesRegex(pre.Stop, "G3"):
            pre.validate_gates("20260926", self.protocol, self.summary, {**self.provenance, "result_data_access_count": 1}, self.instant)

    def test_13_g4_pass_fixture(self):
        self.assertEqual(pre.validate_gates("20260926", self.protocol, self.summary, self.provenance, self.instant)["G4"], "PASS")

    def test_14_g4_fail_fixture(self):
        with self.assertRaisesRegex(pre.Stop, "G4"):
            pre.validate_gates("20260926", self.protocol, self.summary, {**self.provenance, "target_date": "20260927"}, self.instant)

    def test_15_run_end_to_end_rehearsal_passes_result_free(self):
        output = ROOT / "reports/__trackcondition_mock_output_e2e__"
        self.assertEqual(self._rehearsal_run(output, ROOT / "reports/independent_race_selection_prospective_protocol_v1_implementation"), output)

    def test_16_run_end_to_end_fails_closed_for_isolated_root_violation(self):
        independent = ROOT / "reports/independent_race_selection_prospective_protocol_v1_implementation"
        with patch.object(pre, "load_protocol", return_value=self._rehearsal_protocol()):
            with self.assertRaisesRegex(pre.Stop, "OUTPUT_ROOT_ISOLATION"):
                pre.run("20260920", ROOT / "data/raw/prediction_input/DG260920.CSV", ROOT / "data/raw/prediction_input/DE260920.CSV", ROOT / "data/raw/prediction_input/DS260920.CSV", ROOT / "reports/daily_pre_prediction_20260920/current_frozen", independent, independent / "forbidden", clock_utc=datetime(2026, 9, 20, 1, tzinfo=timezone.utc))

    def test_17_protocol_reads_canonical_independent_identity_and_tau(self):
        independent = json.loads((ROOT / self.protocol["independent_protection"]["protocol_path"]).read_text(encoding="utf-8"))
        self.assertEqual(pre.sha(ROOT / self.protocol["independent_protection"]["protocol_path"]), self.protocol["independent_protection"]["protocol_sha256"])
        self.assertEqual(independent["tau"], self.protocol["independent_protection"]["frozen_tau"])

    def test_18_historical_current_control_reproduction(self):
        current, _, _ = pre._current_rows(ROOT / "reports/daily_pre_prediction_20260920/current_frozen", "20260920")
        bundle = TargetBulkPredictionInputAdapterV1().load(ROOT / "data/raw/prediction_input/DG260920.CSV", ROOT / "data/raw/prediction_input/DE260920.CSV", ROOT / "data/raw/prediction_input/DS260920.CSV")
        self.assertEqual(set(bundle.races), set(current))
        for race_id, race_bundle in bundle.races.items():
            control, _, _ = run_race_pair(race_bundle)
            pre.compare_control_to_current(control, current[race_id])

    def test_19_control_tampering_stops_lane(self):
        control, current = control_fixture(); current["ranked_results"][0]["rank"] = 2
        with self.assertRaisesRegex(pre.Stop, "CONTROL_REPRODUCTION_FAILURE:rank"):
            pre.compare_control_to_current(control, current)

    def test_20_unknown_target_condition_does_not_backfill_plurality(self):
        shadow = shadow_defaults({"track_condition": "good", "field_history_track_condition": "good"})
        self.assertIsNone(shadow["track_condition"])
        self.assertEqual(shadow["field_history_track_condition"], "good")

    def test_21_result_access_keys_fail_closed(self):
        with self.assertRaisesRegex(pre.Stop, "STOP_RESULT_LEAKAGE"):
            pre.assert_result_free({"actual_top3": True})

    def test_22_20261010_to_20261012_share_jst_meeting_week_id(self):
        expected = "20261010"
        self.assertEqual(pre.central_jra_meeting_week_id("20261010"), expected)
        self.assertEqual(pre.central_jra_meeting_week_id("20261011"), expected)
        self.assertEqual(pre.central_jra_meeting_week_id("20261012"), expected)

    def test_23_regular_saturday_and_sunday_share_jst_meeting_week_id_and_provenance(self):
        self.assertEqual(pre.central_jra_meeting_week_id("20260926"), pre.central_jra_meeting_week_id("20260927"))
        written = {}
        self._rehearsal_run(ROOT / "reports/__trackcondition_meeting_week_mock__", ROOT / "reports/independent_race_selection_prospective_protocol_v1_implementation", written)
        self.assertEqual(written["summary.json"]["central_jra_meeting_week_id"], "20260919")
        self.assertEqual(written["provenance.json"]["central_jra_meeting_week_id"], "20260919")


if __name__ == "__main__":
    unittest.main()
