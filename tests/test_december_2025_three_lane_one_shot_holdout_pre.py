import unittest
from unittest.mock import patch
from types import SimpleNamespace

from review import december_2025_three_lane_one_shot_holdout_pre as pre


def control_fixture():
    control = {"race_decision": "PLAY", "ranked_results": [
        {"horse_number": 1, "buy_v1_rc1_buy": True, "rank": 1, "adjusted_score": 10.0, "buy_v1_rc1_race_state": "PLAY_CONVERGED"},
        {"horse_number": 2, "buy_v1_rc1_buy": False, "rank": 2, "adjusted_score": 9.0, "buy_v1_rc1_race_state": "PLAY_CONVERGED"},
    ]}
    current = {"race_decision": "PLAY", "ranked_results": [{"horse_number": 1, "buy": True, "rank": 1, "adjusted_score": 10.0}, {"horse_number": 2, "buy": False, "rank": 2, "adjusted_score": 9.0}], "buy_gate_trace": {"race": {"shadow_race_state": "PLAY_CONVERGED"}}}
    return control, current


class DecemberOneShotPhaseATests(unittest.TestCase):
    def test_01_december_result_filename_stops(self):
        with patch.object(pre, "december_result_filenames", return_value=["馬番順着順_20251206.csv"]):
            with self.assertRaisesRegex(pre.Stop, "RESULT_ALREADY_PRESENT"):
                pre.assert_no_december_result_sources()

    def test_02_result_key_payload_stops(self):
        with self.assertRaisesRegex(pre.Stop, "RESULT_KEY_PAYLOAD"):
            pre.assert_result_free({"lane": {"actual_top3": True}})

    def test_03_ds_same_day_or_future_stops(self):
        with self.assertRaisesRegex(pre.Stop, "DS_FUTURE_OR_SAME_DAY_RUN"):
            pre.assert_ds_temporal_cutoff("20251206", ["20251205", "20251206"])
        with self.assertRaisesRegex(pre.Stop, "DS_FUTURE_OR_SAME_DAY_RUN"):
            pre.assert_ds_temporal_cutoff("20251206", ["20251207"])

    def test_04_source_date_mismatch_stops(self):
        with self.assertRaisesRegex(pre.Stop, "SOURCE_DATE_MISMATCH"):
            pre.assert_source_dates_align("20251206", "20251206", "20251207", "20251206")

    def test_05_population_freeze_is_required(self):
        with self.assertRaisesRegex(pre.Stop, "POPULATION_NOT_FROZEN"):
            pre.assert_population_frozen({"status": "PENDING"})

    def test_06_current_replay_identity_is_frozen(self):
        identity = pre.verify_frozen_identities()
        self.assertEqual(identity["current_checkpoint"], "418a4624fa35a561ec1d1c0ec2f53c656a8ca84f")
        inventory = pre.current_replay_code_inventory()
        self.assertTrue(inventory["adapter"])
        self.assertTrue(inventory["current_replay"])
        self.assertTrue(inventory["evaluator"])
        self.assertTrue(inventory["decision"])

    def test_07_trackcondition_control_equals_current(self):
        control, current = control_fixture()
        pre.assert_tc_control_reproduces_current(control, current)
        current["ranked_results"][0]["rank"] = 2
        with self.assertRaisesRegex(pre.Stop, "TC_CONTROL_REPRODUCTION_FAILURE"):
            pre.assert_tc_control_reproduces_current(control, current)

    def test_08_independent_v5_and_tau_identity(self):
        identity = pre.verify_frozen_identities()
        protocol = pre.load_protocol()
        self.assertEqual(identity["independent_protocol_sha256"], protocol["identities"]["independent_protocol_sha256"])

    def test_09_v6_reservation_identity(self):
        identity = pre.verify_frozen_identities()
        protocol = pre.load_protocol()
        self.assertEqual(identity["v6_reservation_protocol_sha256"], protocol["v5_v6_reservation"]["reservation_protocol_sha256"])

    def test_10_cit_membership_is_deterministic(self):
        rows = pre.membership_rows({("r1", 1), ("r1", 2)}, {("r1", 1), ("r1", 3)}, {("r1", 1), ("r1", 2), ("r1", 4)})
        self.assertEqual([row["group"] for row in rows], ["CIT", "CT", "I_ONLY", "T_ONLY"])
        self.assertEqual(pre.race_memberships(rows), [{"race_id": "r1", "C": True, "I": True, "T": True, "bits": "CIT"}])

    def test_11_overlap_metrics_are_deterministic(self):
        metrics = pre.overlap_metrics({("r1", 1)}, {("r1", 1), ("r1", 2)}, {("r1", 1), ("r1", 3)})
        self.assertEqual(metrics["horse"]["jaccard_i_t"], 1 / 3)
        self.assertEqual(metrics["horse"]["overlap_coefficient_i_t"], 1 / 2)
        self.assertEqual(metrics["same_race_i_t_horse_disagreement_count"], 1)

    def test_12_schedule_exception_holds_cit_comparison(self):
        frozen = pre.freeze_population([{"date": "20251206", "race_id": "race_a", "venue": "中山", "horse_count": 12, "schedule_exception": True}])
        self.assertEqual(frozen["eligible_races"], 0)
        self.assertEqual(frozen["exclusions"][0]["reason"], "SCHEDULE_EXCEPTION_CIT_COMPARISON_HOLD")

    def test_13_failed_run_has_no_success_marker_payload(self):
        with patch.object(type(pre.ROOT), "mkdir") as mkdir:
            with self.assertRaisesRegex(pre.Stop, "RESULT_KEY_PAYLOAD"):
                pre.write_phase_a(pre.ROOT / "reports" / "__test_failure__", {"forbidden.json": {"result": "forbidden"}})
            mkdir.assert_not_called()

    def test_14_success_payload_is_final_result_free_marker(self):
        marker = pre.success_payload({"population_freeze.json": "abc"})
        pre.assert_result_free(marker)
        self.assertEqual(marker["indexed_artifacts"], {"population_freeze.json": "abc"})
        self.assertEqual(marker["status"], "SUCCESS")

    def test_15_consumed_marker_rejects_reopen(self):
        with patch.object(type(pre.ROOT), "exists", return_value=True):
            with self.assertRaisesRegex(pre.Stop, "ALREADY_CONSUMED"):
                pre.assert_not_consumed(pre.ROOT / "reports" / "any_december_output")

    def test_16_git_head_mismatch_stops(self):
        with patch("review.december_2025_three_lane_one_shot_holdout_pre.subprocess.check_output", return_value="wrong\n"):
            with self.assertRaisesRegex(pre.Stop, "CURRENT_CHECKPOINT_MISMATCH"):
                pre.assert_git_head()

    def test_17_current_dependency_inventory_has_actual_paths(self):
        inventory = pre.current_replay_code_inventory()
        self.assertIn("review/target_bulk_prediction_input_shadow_v1.py", inventory["current_replay"])
        self.assertIn("review/prospective_prediction_runner_v1.py", inventory["current_replay"])
        self.assertIn("review/selection_authority_protocol_v1_pre_freeze.py", inventory["selection"])

    def test_18_population_freeze_preserves_source_sha(self):
        frozen = pre.freeze_population([{"date": "20251206", "race_id": "r1", "venue": "中山", "horse_count": 10, "source_sha256": {"DG": "a"}}])
        self.assertEqual(frozen["eligible_races"], 1)
        self.assertEqual(frozen["source_records"][0]["source_sha256"], {"DG": "a"})

    def test_19_private_synthetic_seam_orders_four_lanes_after_freeze(self):
        calls = []
        def lane(name, selected):
            def run(population):
                self.assertEqual(population["status"], "FROZEN_PRE_RESULT"); calls.append(name); return {"selected": selected}
            return run
        runners = {"current": lane("current", [("r1", 1)]), "independent": lane("independent", [("r1", 1)]), "trackcondition": lane("trackcondition", [("r1", 2)]), "v5_v6": lane("v5_v6", [])}
        with patch.object(pre, "write_phase_a", side_effect=lambda root, artifacts: root) as writer:
            result = pre._execute_phase_a_test_only(source_rows=[{"date": "20251206", "race_id": "r1", "venue": "中山", "horse_count": 10}], lane_runners=runners, output_root=pre.ROOT / "reports" / "__synthetic_december__")
        self.assertEqual(calls, ["current", "independent", "trackcondition", "v5_v6"])
        self.assertEqual(result.name, "__synthetic_december__")
        self.assertIn("population_freeze.json", writer.call_args.args[1])

    def test_20_race_overlap_is_deterministic(self):
        rows = pre.membership_rows({("r1", 1)}, {("r1", 2)}, {("r2", 1)})
        self.assertEqual({row["race_id"]: row["bits"] for row in pre.race_memberships(rows)}, {"r1": "CI", "r2": "T"})

    def test_21_zero_denominator_is_not_applicable(self):
        self.assertEqual(pre.ratio(0, 0), {"value": "NOT_APPLICABLE", "numerator": 0, "denominator": 0})

    def test_22_tc_added_and_abstain_ratios(self):
        values = pre.additional_race_metrics({"c1"}, {"c1", "i1"}, {"c1", "t1"})
        self.assertEqual(values["tc_added_races_selected_by_i_ratio"]["denominator"], 1)
        self.assertEqual(values["tc_abstained_races_i_abstain_ratio"]["denominator"], 0)

    def test_23_global_consumed_blocks_alternate_root(self):
        with patch.object(type(pre.GLOBAL_CONSUMED), "exists", return_value=True):
            with self.assertRaisesRegex(pre.Stop, "ALREADY_CONSUMED"):
                pre.assert_not_consumed(pre.ROOT / "reports" / "alternate")

    def test_24_schedule_exception_is_comparison_hold(self):
        record = pre.freeze_population([{"date": "20251207", "race_id": "r2", "venue": "阪神", "horse_count": 12, "schedule_exception": True}])
        self.assertEqual(record["exclusions"], [{"date": "20251207", "race_id": "r2", "reason": "SCHEDULE_EXCEPTION_CIT_COMPARISON_HOLD"}])

    def test_25_public_entry_has_no_injected_arguments(self):
        self.assertEqual(pre.run_real_phase_a.__code__.co_argcount, 0)

    def test_26_runtime_inventory_is_derived_from_modules(self):
        inventory = pre.runtime_dependency_inventory()
        self.assertTrue(any(row["module_name"].endswith("december_2025_three_lane_one_shot_holdout_pre") for row in inventory))

    def test_27_past_races_are_read_from_race_not_today_entry(self):
        race = SimpleNamespace(past_races=[SimpleNamespace(race_date="2026-09-20")])
        self.assertEqual(pre.history_dates_from_race(race), ["20260920"])

    def test_28_ds_datetime_is_normalized_before_cutoff_validation(self):
        self.assertEqual(pre.compact_race_date("2026-09-20 00:00:00"), "20260920")
        pre.assert_ds_temporal_cutoff("20260921", [pre.compact_race_date("2026-09-20 00:00:00")])

    def test_29_v5_v6_selected_by_protocol_matches_core_and_target_k(self):
        from pathlib import Path
        sources = {"20260921": tuple(Path("data/raw/prediction_input") / f"{part}260921.CSV" for part in ("DG", "DE", "DS"))}
        _, hashes = pre.build_population_from_sources(sources)
        lane = pre._run_real_lanes(sources, hashes)["v5_v6"]
        self.assertGreater(len(lane["v5_selected"]), 0)
        for arm, phase_key in (("v5", "v5_selected"), ("v6", "v6_selected")):
            core_selected = set()
            for record in lane["records"]:
                value = record[arm]
                if value["race_status"] == "SUCCESS":
                    self.assertEqual(value["selected_n"], value["target_k"] - value["shortfall"])
                core_selected.update((record[arm]["race_id"], int(row["horse_number"])) for row in value["horses"] if row.get("selected_by_protocol") is True)
            self.assertEqual(set(lane[phase_key]), core_selected)


if __name__ == "__main__":
    unittest.main()
