from __future__ import annotations

import copy
import unittest

from analysis import raceshape_positive_impact_dedup_shadow_v1 as shadow
from evaluation.impact_evaluator import ImpactEvaluator


def base_row(cohort="REPLAY", horse="1", rank=1, top3=True):
    return {
        "cohort": cohort, "race_id": "race_a", "race_date": "20260601", "racecourse": "tokyo",
        "horse_number": horse, "horse_name": f"h{horse}", "production_adjusted_score": 110.0,
        "production_rank": rank, "valid_result": True, "actual_finish": 1 if top3 else 5,
        "actual_top3": top3, "actual_top5": top3, "decision": "CAUTION", "race_decision": "PASS",
        "buy": False, "explanation": "production explain",
    }


def evidence(shape=10, impact=10, integrated=100, status="COMPLETE", comment="展開向く"):
    return {
        "shape_score": shape, "shape_comment": comment, "integrated_score": integrated,
        "impact_score": impact, "weight_status": status, "weighted_contribution": 12,
    }


def result(a=0.03, b=-0.1, ndcg=0.01, mrr=0.01, movement=0.2, outflow=0):
    return {
        "movement_rate": movement, "delta": {
            "rank1_3_top3_rate": a, "mean_actual_top3_rank": b, "ndcg_at_3": ndcg, "mrr": mrr,
        }, "actual_top3_top3_outflow_count": outflow,
    }


class TrackingImpactEvaluator(ImpactEvaluator):
    def __init__(self):
        super().__init__()
        self.helper_calls = 0

    def _impact_from_comment_or_score(self, shape_comment, shape_score):
        self.helper_calls += 1
        return super()._impact_from_comment_or_score(shape_comment, shape_score)


class TestRaceShapePositiveImpactDedupShadowV1(unittest.TestCase):
    def test_01_existing_negative_dedup(self):
        value, reason = ImpactEvaluator()._suppress_duplicate_shape_penalty(-10, "展開不向き", -10)
        self.assertEqual(value, 0)
        self.assertTrue(reason)

    def test_02_positive_impact_path(self):
        actual = ImpactEvaluator().evaluate(shape_score=10, shape_comment="展開向く", final_score=100)
        self.assertEqual((actual["impact_score"], actual["adjusted_score"]), (10, 110))

    def test_03_no_other_evaluator_same_route(self):
        facts = shadow.structure_evidence()
        self.assertEqual(next(row for row in facts if row["check_id"] == 7)["status"], "PASS")

    def test_04_weighted_contribution_complete_condition(self):
        actual = shadow.apply_shadow_row(base_row(), evidence(status="COMPLETE"), ImpactEvaluator(), True)
        self.assertTrue(actual["shadow_raceshape_positive_impact_suppressed"])

    def test_05_integrated_score_required(self):
        actual = shadow.apply_shadow_row(base_row(), evidence(integrated=None), ImpactEvaluator(), True)
        self.assertFalse(actual["shadow_raceshape_positive_impact_suppressed"])

    def test_06_positive_impact_required(self):
        actual = shadow.apply_shadow_row(base_row(), evidence(shape=0, impact=0, comment="展開普通"), ImpactEvaluator(), True)
        self.assertFalse(actual["shadow_raceshape_positive_impact_suppressed"])

    def test_07_existing_impact_logic_reused(self):
        evaluator = TrackingImpactEvaluator()
        shadow.apply_shadow_row(base_row(), evidence(), evaluator, True)
        self.assertEqual(evaluator.helper_calls, 1)

    def test_08_flag_off_exact(self):
        row = base_row()
        self.assertEqual(shadow.apply_shadow_row(row, evidence(), ImpactEvaluator(), False), row)

    def test_09_production_score_unchanged(self):
        row = base_row()
        actual = shadow.apply_shadow_row(row, evidence(), ImpactEvaluator(), True)
        self.assertEqual(actual["production_adjusted_score"], row["production_adjusted_score"])

    def test_10_production_rank_unchanged(self):
        row = base_row(rank=2)
        actual = shadow.apply_shadow_row(row, evidence(), ImpactEvaluator(), True)
        self.assertEqual(actual["production_rank"], 2)

    def test_11_decision_unchanged(self):
        row = base_row()
        self.assertEqual(shadow.apply_shadow_row(row, evidence(), ImpactEvaluator(), True)["decision"], row["decision"])

    def test_12_race_decision_unchanged(self):
        row = base_row()
        self.assertEqual(shadow.apply_shadow_row(row, evidence(), ImpactEvaluator(), True)["race_decision"], row["race_decision"])

    def test_13_buy_unchanged(self):
        row = base_row()
        self.assertEqual(shadow.apply_shadow_row(row, evidence(), ImpactEvaluator(), True)["buy"], row["buy"])

    def test_14_explain_unchanged(self):
        row = base_row()
        self.assertEqual(shadow.apply_shadow_row(row, evidence(), ImpactEvaluator(), True)["explanation"], row["explanation"])

    def test_15_shadow_positive_impact_zeroed(self):
        actual = shadow.apply_shadow_row(base_row(), evidence(), ImpactEvaluator(), True)
        self.assertEqual((actual["shadow_dedup_impact_score"], actual["shadow_adjusted_score"]), (0, 100))

    def test_16_negative_impact_behavior_unchanged(self):
        actual = shadow.apply_shadow_row(base_row(), evidence(shape=-10, impact=0, integrated=100, comment="展開不向き"), ImpactEvaluator(), True)
        self.assertFalse(actual["shadow_raceshape_positive_impact_suppressed"])
        self.assertEqual(actual["shadow_dedup_impact_score"], 0)

    def test_17_non_raceshape_positive_not_changed(self):
        actual = shadow.apply_shadow_row(base_row(), evidence(shape=0, impact=5, integrated=105, comment="展開普通"), ImpactEvaluator(), True)
        self.assertFalse(actual["shadow_raceshape_positive_impact_suppressed"])
        self.assertEqual(actual["shadow_adjusted_score"], 110)

    def test_18_baseline_replay_separated(self):
        grouped = shadow.group_by_race([base_row("BASELINE"), base_row("REPLAY")])
        self.assertEqual(set(grouped), {("BASELINE", "race_a"), ("REPLAY", "race_a")})

    def test_19_rank1_3_top3_rate(self):
        rows = [base_row(horse="1", rank=1, top3=True), base_row(horse="2", rank=2, top3=False), base_row(horse="3", rank=3, top3=True)]
        self.assertAlmostEqual(shadow.metric_values(rows, "production_rank")["rank1_3_top3_rate"], 2 / 3)

    def test_20_mean_actual_top3_rank(self):
        rows = [base_row(horse="1", rank=2, top3=True), base_row(horse="2", rank=4, top3=True)]
        self.assertEqual(shadow.metric_values(rows, "production_rank")["mean_actual_top3_rank"], 3)

    def test_21_ndcg_at_3(self):
        rows = [base_row(horse="1", rank=1, top3=True), base_row(horse="2", rank=2, top3=False), base_row(horse="3", rank=3, top3=True)]
        self.assertGreater(shadow.metric_values(rows, "production_rank")["ndcg_at_3"], 0.9)

    def test_22_mrr(self):
        rows = [base_row(horse="1", rank=1, top3=False), base_row(horse="2", rank=2, top3=True)]
        self.assertEqual(shadow.metric_values(rows, "production_rank")["mrr"], 0.5)

    def test_23_full_accept(self):
        status, _ = shadow.classify_result({"BASELINE": result(a=0.03), "REPLAY": result(a=0.04)})
        self.assertEqual(status, "FULL_ACCEPT")

    def test_24_partial_accept(self):
        status, _ = shadow.classify_result({"BASELINE": result(a=0.02, b=0), "REPLAY": result(a=0.015, b=0)})
        self.assertEqual(status, "PARTIAL_ACCEPT")

    def test_25_inconclusive(self):
        status, _ = shadow.classify_result({"BASELINE": result(movement=0.09), "REPLAY": result()})
        self.assertEqual(status, "INCONCLUSIVE")

    def test_26_reject(self):
        status, _ = shadow.classify_result({"BASELINE": result(a=-0.01), "REPLAY": result(a=0.01)})
        self.assertEqual(status, "REJECT")

    def test_27_design_hold(self):
        status, _ = shadow.classify_result({"BASELINE": result(), "REPLAY": result()}, design_hold=True)
        self.assertEqual(status, "DESIGN_HOLD")

    def test_28_safety_pass_on_read_only(self):
        before = shadow.protected_snapshot()
        shadow.structure_evidence()
        self.assertEqual(before, shadow.protected_snapshot())

    def test_29_zero_delta_flag_off(self):
        rows = [base_row(), base_row(horse="2")]
        copied = [shadow.apply_shadow_row(row, evidence(), ImpactEvaluator(), False) for row in rows]
        self.assertEqual(shadow.stable_hash(rows), shadow.stable_hash(copied))

    def test_30_replay_evidence_never_leaks_into_baseline(self):
        row = base_row("BASELINE")
        lookup = {("REPLAY", row["race_id"], str(row["horse_number"])): evidence()}
        actual = shadow.rank_shadow([row], lookup, enabled=True)[0]
        self.assertFalse(actual["shadow_raceshape_positive_impact_suppressed"])
        self.assertEqual(actual["shadow_reason"], "BASELINE_REQUIRED_PROVENANCE_UNAVAILABLE")

    def test_31_prior_shadow_fields_are_not_production_state(self):
        source = shadow.read_csv(shadow.INPUT_TRANSITIONS)[0]
        self.assertIn("shadow_rank", source)
        normalized = shadow.normalize_transition_rows()[source["cohort"]][0]
        self.assertNotIn("shadow_rank", normalized)


if __name__ == "__main__":
    unittest.main()
