from __future__ import annotations

import json
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from review.roadmap_v3_pre_infrastructure_v1 import (
    RoadmapStop, assert_evidence_start, comparison_a_records, comparison_b_pre,
    holdout_inventory, market_inventory, meeting_summary, rank1_diagnostics,
    validate_rolling_origin, ws2_preflight, _result_source_exists, _int,
    comparison_a_from_full_field_diagnostic, validate_pre_timing,
    validate_verification_manifest, canonical_sha, execution_date_jst,
)

ROOT = Path(__file__).resolve().parents[1]


def current_races() -> dict:
    return {
        "race_a": {
            "race_id": "race_a", "top5": [{"horse_number": 1}, {"horse_number": 2}],
            "ranked_results": [{"horse_number": 1, "horse_name": "A", "buy": True}, {"horse_number": 2, "horse_name": "B", "buy": False}],
            "buy_gate_trace": {"race": {"shadow_race_state": "PLAY_CONVERGED"}, "horses": [{"horse_number": 1, "shadow_ai_rank": 1}, {"horse_number": 2, "shadow_ai_rank": 2}]},
        },
        "race_b": {
            "race_id": "race_b", "top5": [{"horse_number": 3}],
            "ranked_results": [{"horse_number": 3, "horse_name": "C", "buy": False}, {"horse_number": 4, "horse_name": "D", "buy": True}],
            "buy_gate_trace": {"race": {"shadow_race_state": "SKIP"}, "horses": [{"horse_number": 3, "shadow_ai_rank": 1}, {"horse_number": 4, "shadow_ai_rank": 2}]},
        },
    }


def rows() -> list[dict]:
    return [
        {"race_id": "race_a", "venue": "東京", "race_number": 1, "horse_number": 1, "current_buy": True, "formal_v5_selected": True, "formal_v5_probability": "0.5", "current_shadow_ai_rank": 1},
        {"race_id": "race_a", "venue": "東京", "race_number": 1, "horse_number": 2, "current_buy": False, "formal_v5_selected": False, "formal_v5_probability": "0.5", "current_shadow_ai_rank": 2},
        {"race_id": "race_b", "venue": "中山", "race_number": 2, "horse_number": 3, "current_buy": False, "formal_v5_selected": False, "formal_v5_probability": "0.9", "current_shadow_ai_rank": 1},
        {"race_id": "race_b", "venue": "中山", "race_number": 2, "horse_number": 4, "current_buy": True, "formal_v5_selected": True, "formal_v5_probability": "0.1", "current_shadow_ai_rank": 2},
    ]


IDENTITY = {"model_sha256": "m", "runtime_identity": {"python": "test"}}
DIAGNOSTIC_FIXTURE = ROOT / "tests" / "fixtures" / "roadmap_v3_full_field_diagnostic_fixture.json"


class RoadmapV3PreInfrastructureTests(unittest.TestCase):
    def test_current_race_set_exact_match_is_required(self):
        broken = rows()[:-1]
        with self.assertRaisesRegex(RoadmapStop, "RACE_SET_MISMATCH|HORSE_SET_MISMATCH"):
            comparison_a_records(target_date="20261006", current_races=current_races(), rows=broken, formal_identity=IDENTITY)

    def test_float_like_integer_rank_normalization_is_exact_and_non_integral_stops(self):
        for value, expected in (("1.0", 1), ("2.0", 2), ("1", 1), (1.0, 1)):
            self.assertEqual(_int(value, "SHADOW_AI_RANK"), expected)
        for value in ("1.5", "abc", "", "NaN", "inf"):
            with self.assertRaisesRegex(RoadmapStop, "INVALID_SHADOW_AI_RANK"):
                _int(value, "SHADOW_AI_RANK")

    def test_zero_budget_is_not_counted(self):
        races = current_races()
        for payload in races.values():
            for horse in payload["ranked_results"]:
                horse["buy"] = False
        record = comparison_a_records(target_date="20261006", current_races=races, rows=rows(), formal_identity=IDENTITY)
        self.assertEqual(record["zero_budget_status"], "ZERO_BUDGET_NOT_COUNTED")
        self.assertEqual(record["selected_n"], 0)

    def test_unavailable_race_is_fail_closed_without_fill(self):
        source = rows()
        source[0]["formal_v5_probability"] = ""
        source[1]["formal_v5_probability"] = ""
        record = comparison_a_records(target_date="20261006", current_races=current_races(), rows=source, formal_identity=IDENTITY)
        self.assertEqual(record["unavailable_race_count"], 1)
        self.assertEqual(record["budget_n"], 2)
        self.assertEqual(record["selected_n"], 2)
        self.assertEqual(record["shortfall"], 0)

    def test_stored_probability_tie_uses_formal_deterministic_tie_break(self):
        record = comparison_a_records(target_date="20261006", current_races=current_races(), rows=rows(), formal_identity=IDENTITY)
        tied = [item for item in record["selected_horses"] if item["race_id"] == "race_a"]
        self.assertEqual(tied[0]["horse_number"], 1)
        self.assertEqual(record["tie_break_rule"][1:], ["shadow_ai_rank ASC", "race_id ASC", "horse_number ASC"])

    def test_formal_v5_tie_break_is_derived_from_frozen_protocol_not_daily_order(self):
        protocol = json.loads((ROOT / "docs" / "selection_authority_protocol_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(protocol["ordering"]["rules"], [
            "predicted_actual_top3_probability DESC", "shadow_ai_rank ASC", "horse_number ASC",
        ])

    def test_selected_set_is_frozen_and_top5_split_is_reported(self):
        record = comparison_a_records(target_date="20261006", current_races=current_races(), rows=rows(), formal_identity=IDENTITY)
        self.assertEqual([(item["race_id"], item["horse_number"]) for item in record["selected_horses"]], [("race_b", 3), ("race_a", 1)])
        self.assertEqual(record["selected_current_top5_count"], 2)
        self.assertEqual(record["selected_outside_current_top5_count"], 0)

    def test_full_field_probability_is_the_single_authority_and_skip_is_retained(self):
        source = rows()
        current = current_races()
        current["race_b"]["ranked_results"][1]["buy"] = False
        source[3]["current_buy"] = False
        source[2]["formal_v5_probability"] = ""  # Formal V5 target-k=0 is out of scope.
        record = comparison_a_from_full_field_diagnostic(
            target_date="20990101", current_races=current, analysis_rows=source,
            full_field_diagnostic_path=DIAGNOSTIC_FIXTURE, formal_tie_break_identity=IDENTITY,
        )
        self.assertEqual(record["probability_authority"], "FROZEN_NEXT_PRE_DIAGNOSTIC_FULL_FIELD_V5_P_TOP3")
        self.assertEqual(record["unavailable_race_count"], 0)
        self.assertIn("race_b", {row["race_id"] for row in record["race_records"]})
        diagnostic = rank1_diagnostics(record, source)
        self.assertEqual(len(diagnostic["R2"]), 1)
        current["race_b"]["buy_gate_trace"]["race"]["shadow_race_state"] = "PLAY_UNCONVERGED_4PLUS"
        unconverged = comparison_a_from_full_field_diagnostic(
            target_date="20990101", current_races=current, analysis_rows=source,
            full_field_diagnostic_path=DIAGNOSTIC_FIXTURE, formal_tie_break_identity=IDENTITY,
        )
        self.assertEqual(unconverged["race_records"][1]["race_status"], "AVAILABLE")

    def test_full_field_model_sha_mismatch_stops(self):
        with self.assertRaisesRegex(RoadmapStop, "V5_MODEL_SHA_MISMATCH"):
            comparison_a_from_full_field_diagnostic(
                target_date="20990101", current_races=current_races(), analysis_rows=rows(),
                full_field_diagnostic_path=DIAGNOSTIC_FIXTURE,
                formal_tie_break_identity={"model_sha256": "different", "runtime_identity": "test"},
            )

    def test_missing_full_field_diagnostic_stops_without_reinference(self):
        with self.assertRaisesRegex(RoadmapStop, "FULL_FIELD_DIAGNOSTIC_MISSING"):
            comparison_a_from_full_field_diagnostic(
                target_date="20990101", current_races=current_races(), analysis_rows=rows(),
                full_field_diagnostic_path=ROOT / "tests" / "fixtures" / "not-present.json",
                formal_tie_break_identity=IDENTITY,
            )

    def test_shortfall_is_reported_without_probability_fill(self):
        source = rows()
        races = current_races()
        races["race_a"]["ranked_results"][1]["buy"] = True
        source[0]["formal_v5_probability"] = ""
        source[1]["formal_v5_probability"] = ""
        record = comparison_a_records(target_date="20261006", current_races=races, rows=source, formal_identity=IDENTITY)
        self.assertEqual(record["budget_n"], 3)
        self.assertEqual(record["selected_n"], 2)
        self.assertEqual(record["shortfall"], 1)

    def test_no_post_replacement_or_result_fields_exist_in_pre_record(self):
        record = comparison_a_records(target_date="20261006", current_races=current_races(), rows=rows(), formal_identity=IDENTITY)
        self.assertEqual(record["result_access_count"], 0)
        self.assertNotIn("valid_n", record)
        self.assertNotIn("hits", record)

    def test_comparison_b_overlap_decomposition(self):
        record = comparison_b_pre(rows())
        self.assertEqual(record["current_selected_n"], 2)
        self.assertEqual(record["formal_selected_n"], 2)
        self.assertEqual(len(record["overlap_decomposition"]["BOTH_SELECTED"]), 2)

    def test_rank1_r1_r2_r3_partition(self):
        comparison = comparison_a_records(target_date="20261006", current_races=current_races(), rows=rows(), formal_identity=IDENTITY)
        diagnostic = rank1_diagnostics(comparison, rows())
        self.assertTrue(diagnostic["partition_pass"])
        self.assertEqual(len(diagnostic["R1"]) + len(diagnostic["R2"]), len(diagnostic["R3"]))

    def test_defined_meeting_groups_normal_and_three_day_weekend(self):
        two = meeting_summary(["20261010", "20261011"], 4)
        three = meeting_summary(["20261010", "20261011", "20261012"], 6)
        self.assertEqual(two["defined_meeting_count"], 1)
        self.assertEqual(three["defined_meeting_count"], 1)
        self.assertEqual(three["target_date_count"], 3)

    def test_evidence_start_requires_all_prerequisites_and_strictly_later_date(self):
        with self.assertRaisesRegex(RoadmapStop, "PREREQUISITE"):
            assert_evidence_start(target_date="20261006", execution_spec_approval_date="20261005", implementation_verified=False, artifact_sha_frozen=True)
        with self.assertRaisesRegex(RoadmapStop, "NOT_STRICTLY_AFTER"):
            assert_evidence_start(target_date="20261005", execution_spec_approval_date="20261005", implementation_verified=True, artifact_sha_frozen=True)
        self.assertTrue(assert_evidence_start(target_date="20261006", execution_spec_approval_date="20261005", implementation_verified=True, artifact_sha_frozen=True)["evidence_start_eligible"])

    def test_result_source_existence_guard_detects_without_reading_contents(self):
        self.assertTrue(_result_source_exists("20261003", ROOT))
        self.assertFalse(_result_source_exists("20990101", ROOT))

    def test_jst_forward_guard_and_missing_verification_manifest_fail_closed(self):
        self.assertEqual(
            execution_date_jst(datetime(2026, 10, 10, 23, 0, tzinfo=timezone.utc)),
            "20261011",
        )
        with self.assertRaisesRegex(RoadmapStop, "STOP_PAST_DATE_ROADMAP_V3_PRE"):
            validate_pre_timing(target_date="20261010", execution_date="20261011", repository_root=ROOT)
        with self.assertRaisesRegex(RoadmapStop, "RESULT_SOURCE_EXISTS"):
            validate_pre_timing(target_date="20261003", execution_date="20261003", repository_root=ROOT)
        self.assertEqual(
            validate_pre_timing(target_date="20990101", execution_date="20990101", repository_root=ROOT)["result_source_existence_check"],
            "PASS",
        )
        self.assertEqual(validate_pre_timing(target_date="20990102", execution_date="20990101", repository_root=ROOT)["result_source_existence_check"], "PASS")
        with self.assertRaisesRegex(RoadmapStop, "INFRASTRUCTURE_NOT_VERIFIED"):
            validate_verification_manifest(ROOT / "docs" / "roadmap_v3_pre_infrastructure_contract_v2.json", {})

    def test_verification_manifest_status_and_sha_mismatch_fail_closed(self):
        sandbox = ROOT / ".tmp" / f"roadmap_v3_verification_{uuid4().hex}"
        sandbox.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, sandbox, True)
        expected = {
            "execution_spec_sha": "a", "amendment_sha": "b", "active_contract_sha": "c",
            "implementation_file_sha": "d", "relevant_test_file_sha": "e",
        }
        base = {
            **expected, "test_status": "PASS", "independent_review_status": "ACCEPT",
            "human_authorization_status": True, "verification_timestamp_jst": "2026-10-05T12:00:00+09:00",
        }
        def write(name, payload):
            record = dict(payload)
            record["verification_record_sha"] = canonical_sha(record)
            path = sandbox / name
            path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            return path
        self.assertEqual(validate_verification_manifest(write("ok.json", base), expected)[0]["test_status"], "PASS")
        rejected = dict(base, independent_review_status="REQUIRES_FIX")
        with self.assertRaisesRegex(RoadmapStop, "INFRASTRUCTURE_NOT_VERIFIED"):
            validate_verification_manifest(write("rejected.json", rejected), expected)
        invalid_hash = write("bad-hash.json", base)
        payload = json.loads(invalid_hash.read_text(encoding="utf-8"))
        payload["verification_record_sha"] = "0" * 64
        invalid_hash.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(RoadmapStop, "INFRASTRUCTURE_NOT_VERIFIED"):
            validate_verification_manifest(invalid_hash, expected)

    def test_ws2_leakage_guard_and_rolling_origin_order(self):
        good = {"v5_top5_only_confirmed": True, "historical_full_field_rows_available": True, "current_scores_point_in_time_safe": True, "learning_db_clean": True, "pre_time_features_only": True, "track_condition_semantics_known": True, "model_identity_proven": True, "runtime_available": True, "feature_columns": ["field_size"]}
        self.assertEqual(ws2_preflight(good)["status"], "PASS")
        bad = dict(good, feature_columns=["actual_top3"])
        with self.assertRaisesRegex(RoadmapStop, "STOP_WS2_DATA_INTEGRITY"):
            ws2_preflight(bad)
        self.assertEqual(validate_rolling_origin([{"training_months": ["202601", "202602"], "prediction_month": "202603"}])["status"], "PASS")
        with self.assertRaisesRegex(RoadmapStop, "ROLLING_ORIGIN_ORDER"):
            validate_rolling_origin([{"training_months": ["202604"], "prediction_month": "202603"}])

    def test_holdout_and_market_never_declare_unproven_or_feed_features(self):
        inventory = holdout_inventory([{"period": "202512", "role": "HOLDOUT"}, {"period": "202603", "role": "TRAIN"}])
        self.assertFalse(inventory["untouched_holdout_declared"])
        self.assertEqual(market_inventory({"source_availability": "NOT_COLLECTED"})["market_as_ai_input"], "PROHIBITED")
        with self.assertRaisesRegex(RoadmapStop, "MARKET_ISOLATION"):
            market_inventory({"feature_table_path": "forbidden.csv"})


if __name__ == "__main__":
    unittest.main()
