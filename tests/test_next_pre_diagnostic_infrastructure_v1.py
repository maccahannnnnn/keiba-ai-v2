"""Result-free regression tests for next-PRE diagnostic-only infrastructure."""
from __future__ import annotations

import copy
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import unittest

from review.next_pre_diagnostic_infrastructure_v1 import (
    DiagnosticStop, RESEARCH_LANES, assert_selection_unchanged, build_funnel_diagnostic,
    build_v5_full_field_diagnostic, duplicate_fingerprint_check, freeze_next_pre_diagnostics,
    observation_plan_template, selection_snapshot, validate_forward_diagnostic_timing,
    verify_v5_full_field_parity_20261004, _execution_date_jst,
)


def _rows() -> list[dict]:
    return [
        {"race_id": "race_x", "venue": "東京", "race_number": 1, "horse_number": 1, "horse_name": "A", "current_race_state": "PLAY_CONVERGED", "field_size": 2, "current_shadow_ai_rank": 1, "current_top5": True, "current_buy": True, "current_risk_guard_pass": True, "current_shadow_buy_candidate": True, "independent_v5_candidate": True, "independent_v5_selected": True, "trackcondition_selected": False, "daily_v5_candidate": True, "daily_v5_selected": False, "formal_v5_exact5_membership": True, "formal_v5_selected": True, "formal_v6_exact5_membership": True, "formal_v6_selected": True, "diagnostic_feature_vector": [1.0, 0.0]},
        {"race_id": "race_x", "venue": "東京", "race_number": 1, "horse_number": 2, "horse_name": "B", "current_race_state": "PLAY_CONVERGED", "field_size": 2, "current_shadow_ai_rank": 2, "current_top5": True, "current_buy": False, "current_risk_guard_pass": False, "current_shadow_buy_candidate": False, "independent_v5_candidate": False, "independent_v5_selected": False, "trackcondition_selected": True, "daily_v5_candidate": False, "daily_v5_selected": True, "formal_v5_exact5_membership": True, "formal_v5_selected": False, "formal_v6_exact5_membership": True, "formal_v6_selected": False, "diagnostic_feature_vector": [0.0, 1.0]},
    ]


def _workspace_sandbox(name: str) -> Path:
    """Use a pre-provisioned workspace sandbox; Windows temp ACLs are unreliable."""
    path = Path(__file__).resolve().parents[1] / ".tmp" / "next_pre_diagnostic_jst_test_sandbox_ps" / name
    if not path.is_dir():
        raise RuntimeError("test sandbox must be provisioned by the test command")
    return path


class NextPreDiagnosticInfrastructureTests(unittest.TestCase):
    def test_lane_registration_has_three_distinct_result_free_lanes(self) -> None:
        self.assertEqual([item["lane"] for item in RESEARCH_LANES], ["CURRENT_REFINEMENT", "CURRENT_ABSTENTION_COVERAGE", "CANDIDATE_GENERATION_FUNNEL"])
        self.assertTrue(all(item["fingerprint"]["selection_change"] is False for item in RESEARCH_LANES))


    def test_duplicate_fingerprint_protection(self) -> None:
        self.assertEqual(duplicate_fingerprint_check(RESEARCH_LANES, []), [{"lane": item["lane"], "status": "NEW_RELATED_NOT_DUPLICATE"} for item in RESEARCH_LANES])
        self.assertTrue(all(item["status"] == "DUPLICATE" for item in duplicate_fingerprint_check(RESEARCH_LANES, [{"lane": "CURRENT_REFINEMENT"}, {"lane": "CURRENT_ABSTENTION_COVERAGE"}, {"lane": "CANDIDATE_GENERATION_FUNNEL"}])))


    def test_h1_h5_are_descriptive_only(self) -> None:
        template = observation_plan_template()
        self.assertEqual([row["observation_id"] for row in template["h1_h5"]], ["H1", "H2", "H3", "H4", "H5"])
        self.assertTrue(all(row["result_status_default"] == "DESCRIPTIVE_ONLY" for row in template["h1_h5"]))
        self.assertTrue(all("SUPPORTED_THIS_DATE" in row["automated_formal_verdict_forbidden"] for row in template["h1_h5"]))


    def test_funnel_generation_is_result_free_and_selection_invariant(self) -> None:
        rows = _rows(); before = selection_snapshot(rows)
        artifact = build_funnel_diagnostic(target_date="20990101", rows=rows, source_sha256="source")
        self.assertEqual(artifact["result_access_count"], 0)
        self.assertEqual(artifact["funnel_totals"]["total_field"], 2)
        self.assertTrue(artifact["selection_invariant"]["unchanged"])
        self.assertEqual(before, selection_snapshot(rows))

    def test_string_boolean_and_missing_normalization(self) -> None:
        rows = _rows()
        for row in rows:
            for key, value in list(row.items()):
                if isinstance(value, bool):
                    row[key] = "True" if value else "False"
        rows[1]["current_risk_guard_pass"] = ""
        snapshot = selection_snapshot(rows)
        self.assertEqual(snapshot["CURRENT"], {"race_x": ["1"]})
        self.assertEqual(snapshot["TRACKCONDITION_SEMANTIC"], {"race_x": ["2"]})
        funnel = build_funnel_diagnostic(target_date="20990101", rows=rows, source_sha256="source")
        self.assertEqual(funnel["funnel_totals"]["top5_risk_pass_count"], 1)
        self.assertIs(funnel["horse_rows"][0]["risk_guard_pass"], True)
        self.assertIsNone(funnel["horse_rows"][1]["risk_guard_pass"])

    def test_real_20261004_csv_selection_and_funnel_invariants(self) -> None:
        root = Path(__file__).resolve().parents[1]
        horse_path = root / "reports" / "20261004_all_active_systems_horse_analysis.csv"
        union_path = root / "reports" / "20261004_all_active_systems_union_phase_a_selection.json"
        with horse_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        snapshot = selection_snapshot(rows)
        expected_counts = {
            "CURRENT": 7, "INDEPENDENT_V5": 13, "TRACKCONDITION_SEMANTIC": 8,
            "DAILY_V5_SAME_VOLUME": 7, "FORMAL_V5": 7, "FORMAL_V6": 7,
        }
        self.assertEqual({lane: sum(map(len, races.values())) for lane, races in snapshot.items()}, expected_counts)
        union = json.loads(union_path.read_text(encoding="utf-8"))
        expected = {lane: {} for lane in expected_counts}
        for member in union["canonical_selection"]["members"]:
            for lane in member["selecting_lanes"]:
                expected[lane].setdefault(str(member["race_id"]), []).append(str(member["horse_no"]))
        for lane in expected:
            for race_id in expected[lane]:
                expected[lane][race_id].sort(key=int)
        self.assertEqual(snapshot, expected)
        funnel = build_funnel_diagnostic(target_date="20261004", rows=rows, source_sha256="fixture")
        self.assertEqual(funnel["funnel_totals"]["current_top5_count"], 65)
        self.assertEqual(funnel["funnel_totals"]["top5_risk_pass_count"], 47)
        self.assertTrue(all(isinstance(row["risk_guard_pass"], bool) for row in funnel["horse_rows"]))

    def test_v5_full_field_parity_20261004(self) -> None:
        parity = verify_v5_full_field_parity_20261004()
        self.assertEqual(parity["total_horses"], 217)
        self.assertEqual(parity["independent_overlap_horses"], 65)
        self.assertLessEqual(parity["independent_max_absolute_difference"], 1e-12)
        self.assertEqual(parity["formal_v5_overlap_horses"], 85)
        self.assertLessEqual(parity["formal_v5_max_absolute_difference"], 1e-12)


    def test_v5_full_field_diagnostic_generates_rank_without_selection_mutation(self) -> None:
        rows = _rows(); before = selection_snapshot(rows)
        artifact = build_v5_full_field_diagnostic(target_date="20990101", rows=rows, source_sha256="source", model_identity={"model_sha256": "m", "feature_spec_identity": "f"}, predictor=lambda values: [sum(value) / 2 for value in values])
        self.assertEqual([row["full_field_rank"] for row in artifact["records"]], [1, 2])
        self.assertTrue(all(row["diagnostic_status"] == "AVAILABLE" for row in artifact["records"]))
        self.assertEqual(before, selection_snapshot(rows))


    def test_missing_inference_is_an_artifact_status_not_selection_fallback(self) -> None:
        rows = _rows(); before = selection_snapshot(rows)
        artifact = build_v5_full_field_diagnostic(target_date="20990101", rows=rows, source_sha256="source", model_identity={}, predictor=None)
        self.assertTrue(all(row["diagnostic_status"] == "DIAGNOSTIC_INFERENCE_UNAVAILABLE" for row in artifact["records"]))
        self.assertFalse(artifact["selection_fallback_used"])
        self.assertEqual(before, selection_snapshot(rows))


    def test_result_field_is_rejected_in_pre_path(self) -> None:
        rows = _rows(); rows[0]["actual_top3"] = True
        with self.assertRaisesRegex(DiagnosticStop, "STOP_RESULT_FIELD_IN_PRE_DIAGNOSTIC"):
            build_funnel_diagnostic(target_date="20990101", rows=rows, source_sha256="source")

    def test_selection_mutation_guard_fails_closed(self) -> None:
        before = selection_snapshot(_rows()); after = copy.deepcopy(before)
        after["CURRENT"]["race_x"] = ["2"]
        with self.assertRaisesRegex(DiagnosticStop, "STOP_DIAGNOSTIC_SELECTION_MUTATION"):
            assert_selection_unchanged(before, after)

    def test_past_date_stops_without_role_fallback(self) -> None:
        with self.assertRaisesRegex(DiagnosticStop, "STOP_PAST_DATE_FORWARD_DIAGNOSTIC"):
            validate_forward_diagnostic_timing(
                target_date="20261010", execution_date_jst="20261012", repository_root=_workspace_sandbox("past")
            )

    def test_jst_boundary_uses_fixed_utc_plus_nine_without_tzdata(self) -> None:
        # JST 2026-10-11 08:00 is UTC 2026-10-10 23:00.
        execution = _execution_date_jst(datetime(2026, 10, 10, 23, 0, tzinfo=timezone.utc))
        self.assertEqual(execution, "20261011")
        with self.assertRaisesRegex(DiagnosticStop, "STOP_PAST_DATE_FORWARD_DIAGNOSTIC"):
            validate_forward_diagnostic_timing(
                target_date="20261010", execution_date_jst=execution, repository_root=_workspace_sandbox("past")
            )

    def test_jst_daytime_guard_remains_forward_compatible(self) -> None:
        execution = _execution_date_jst(datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc))
        self.assertEqual(execution, "20261011")
        record = validate_forward_diagnostic_timing(
            target_date="20261011", execution_date_jst=execution, repository_root=_workspace_sandbox("valid")
        )
        self.assertEqual(record["result_source_existence_check"], "PASS")

    def test_existing_result_source_stops(self) -> None:
        root = _workspace_sandbox("result")
        result = root / "data" / "raw" / "target" / "daily_result_list" / "着順馬番_20990101.csv"
        result.write_text("existence-only", encoding="utf-8")
        with self.assertRaisesRegex(DiagnosticStop, "STOP_RESULT_SOURCE_EXISTS_FOR_FORWARD_DIAGNOSTIC"):
            validate_forward_diagnostic_timing(
                target_date="20990101", execution_date_jst="20990101", repository_root=root
            )

    def test_valid_forward_date_without_result_source_passes(self) -> None:
        record = validate_forward_diagnostic_timing(
            target_date="20990102", execution_date_jst="20990101", repository_root=_workspace_sandbox("valid")
        )
        self.assertEqual(record["result_source_existence_check"], "PASS")
        self.assertFalse(record["retrospective_role_fallback"])

    def test_public_entrypoint_with_csv_shaped_fixture_preserves_selection(self) -> None:
        root = _workspace_sandbox("entry")
        current = root / "current"
        rows = _rows()
        for row in rows:
            for key, value in list(row.items()):
                if isinstance(value, bool):
                    row[key] = "True" if value else "False"
        (current / "provenance.json").write_text(json.dumps({"target_date": "20990101", "result_data_access_count": 0}), encoding="utf-8")
        (current / "race_index.json").write_text(json.dumps({"race_index": [{"artifact": "race.json"}]}), encoding="utf-8")
        payload = {
                "race_id": "race_x", "ranked_results": [{"horse_number": 1}, {"horse_number": 2}],
                "buy_gate_trace": {"race": {"shadow_race_state": "PLAY_CONVERGED"}, "horses": [{"horse_number": 1}, {"horse_number": 2}]},
        }
        (current / "race.json").write_text(json.dumps(payload), encoding="utf-8")
        horse_path = root / "analysis.csv"
        with horse_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=sorted({key for row in rows for key in row}))
            writer.writeheader(); writer.writerows(rows)
        union_path = root / "union.json"
        union_path.write_text(json.dumps({"result_access_count": 0, "formal_evidence": False, "selection_sha256": "u"}), encoding="utf-8")
        output = root / f"out_{uuid4().hex}"
        freeze_next_pre_diagnostics(
            target_date="20990101", execution_date_jst="20990101", repository_root=root,
            current_pre_root=current, analysis_horse_csv=horse_path, union_path=union_path, output_root=output,
            feature_vector_builder=lambda *_args: [1.0, 0.0],
            model_loader=lambda: ({"model_sha256": "m", "feature_spec_identity": "f"}, lambda vectors: [0.5] * len(vectors)),
        )
        frozen = json.loads((output / "diagnostic_freeze.json").read_text(encoding="utf-8"))
        funnel = json.loads((output / "candidate_generation_funnel_diagnostic.json").read_text(encoding="utf-8"))
        v5 = json.loads((output / "v5_full_field_diagnostic.json").read_text(encoding="utf-8"))
        self.assertTrue(frozen["selection_before_after"]["unchanged"])
        self.assertEqual(funnel["funnel_totals"]["top5_risk_pass_count"], 1)
        self.assertTrue(all(item["diagnostic_status"] == "AVAILABLE" for item in v5["records"]))
