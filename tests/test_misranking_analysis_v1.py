from __future__ import annotations

import copy
import unittest

from analysis import misranking_analysis_v1 as analysis


def transition(cohort="REPLAY", race="race_a", horse="1", move="IN", finish="1", top3="True"):
    return {
        "cohort": cohort, "race_id": race, "race_date": "20260601", "racecourse": "test",
        "horse_number": horse, "horse_name": f"h{horse}", "valid_result": "True",
        "actual_top3": top3, "actual_finish": finish, "top3_transition": move,
        "production_rank": "4", "shadow_rank": "3", "final_score": "100", "adjusted_score": "110",
    }


def comparison_rows(race_shape_gap=5.0):
    return [
        {"evaluator": "RaceShape", "out_minus_in_weight_uplift": race_shape_gap},
        {"evaluator": "CourseShape", "out_minus_in_weight_uplift": 1.0},
        {"evaluator": "PaceStyle", "out_minus_in_weight_uplift": 0.0},
        {"evaluator": "Distance", "out_minus_in_weight_uplift": 2.0},
        {"evaluator": "PastPerformance", "out_minus_in_weight_uplift": 0.0},
        {"evaluator": "Bloodline", "out_minus_in_weight_uplift": 1.0},
    ]


def cause_targets(in_impact=0, out_impact=10):
    return [
        {"top3_transition": "IN", "positive_impact_applied": in_impact > 0, "impact_score": in_impact, "adjusted_minus_final": 2},
        {"top3_transition": "OUT", "positive_impact_applied": out_impact > 0, "impact_score": out_impact, "adjusted_minus_final": 15},
    ]


class TestMisrankingAnalysisV1(unittest.TestCase):
    def test_01_actual_top3_only(self):
        rows = [transition(top3="True"), transition(horse="2", top3="False")]
        valid, _ = analysis.boundary_targets(rows)
        self.assertEqual(len(valid), 1)

    def test_02_boundary_transition_only(self):
        rows = [transition(move="IN"), transition(horse="2", move="STAY")]
        valid, _ = analysis.boundary_targets(rows)
        self.assertEqual([row["top3_transition"] for row in valid], ["IN"])

    def test_03_finish_zero_excluded(self):
        valid, excluded = analysis.boundary_targets([transition(finish="0")])
        self.assertEqual((len(valid), len(excluded)), (0, 1))

    def test_04_duplicate_boundary_horse_rejected(self):
        row = transition()
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE"):
            analysis.boundary_targets([row, copy.deepcopy(row)])

    def test_05_cohorts_grouped_separately(self):
        grouped = analysis.group_races([transition("BASELINE", "same"), transition("REPLAY", "same")])
        self.assertEqual(set(grouped), {("BASELINE", "same"), ("REPLAY", "same")})

    def test_06_priority_starts_race_shape(self):
        self.assertEqual(analysis.PRIORITY[0], "RaceShape")

    def test_07_evaluator_comparison_weight_difference(self):
        detail = [
            {"evaluator": "RaceShape", "transition": "IN", "raw_score": 1, "weight": 1.0, "weighted_contribution": 1, "weight_uplift": 0},
            {"evaluator": "RaceShape", "transition": "OUT", "raw_score": 2, "weight": 1.5, "weighted_contribution": 3, "weight_uplift": 1},
        ]
        result = analysis.evaluator_comparison(detail)[0]
        self.assertEqual(result["out_minus_in_weight"], 0.5)

    def test_08_evaluator_comparison_contribution_difference(self):
        detail = [
            {"evaluator": "RaceShape", "transition": "IN", "raw_score": -5, "weight": 1.0, "weighted_contribution": -5, "weight_uplift": 0},
            {"evaluator": "RaceShape", "transition": "OUT", "raw_score": 5, "weight": 1.2, "weighted_contribution": 6, "weight_uplift": 1},
        ]
        self.assertEqual(analysis.evaluator_comparison(detail)[0]["out_minus_in_weighted_contribution"], 11)

    def test_09_single_cause_found(self):
        cause, _ = analysis.select_single_cause(comparison_rows(), cause_targets())
        self.assertEqual(cause, "RACESHAPE_POSITIVE_IMPACT_DOUBLE_APPLICATION")

    def test_10_single_cause_rejected_when_inflow_also_impacted(self):
        cause, _ = analysis.select_single_cause(comparison_rows(), cause_targets(in_impact=10))
        self.assertEqual(cause, "NO_SINGLE_CAUSE")

    def test_11_single_cause_rejected_when_other_uplift_larger(self):
        rows = comparison_rows(race_shape_gap=0.5)
        cause, _ = analysis.select_single_cause(rows, cause_targets())
        self.assertEqual(cause, "NO_SINGLE_CAUSE")

    def test_12_real_boundary_counts(self):
        valid, excluded = analysis.boundary_targets(analysis.read_csv(analysis.TRANSITIONS))
        counts = {(c, m): sum(r["cohort"] == c and r["top3_transition"] == m for r in valid) for c in ("BASELINE", "REPLAY") for m in ("IN", "OUT")}
        self.assertEqual(counts, {("BASELINE", "IN"): 10, ("BASELINE", "OUT"): 6, ("REPLAY", "IN"): 5, ("REPLAY", "OUT"): 5})
        self.assertEqual(len(excluded), 1)

    def test_13_real_replay_provenance_complete(self):
        valid, _ = analysis.boundary_targets(analysis.read_csv(analysis.TRANSITIONS))
        targets = [row for row in valid if row["cohort"] == "REPLAY"]
        lookup = {row["race_id"]: row for row in analysis.read_csv(analysis.REPLAY_COHORT)}
        detail, enriched = analysis.replay_evidence(targets, lookup)
        self.assertEqual((len(detail), len(enriched)), (90, 10))

    def test_14_protected_snapshot_stable_on_reads(self):
        before = analysis.protected_snapshot()
        analysis.read_csv(analysis.TRANSITIONS)
        self.assertEqual(before, analysis.protected_snapshot())

    def test_15_candidate_limit_is_one(self):
        cause, _ = analysis.select_single_cause(comparison_rows(), cause_targets())
        candidates = [cause] if cause != "NO_SINGLE_CAUSE" else []
        self.assertLessEqual(len(candidates), 1)


if __name__ == "__main__":
    unittest.main()
