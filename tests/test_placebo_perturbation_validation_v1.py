from __future__ import annotations

import copy
import math
import unittest
from collections import Counter
from unittest.mock import patch

from analysis import placebo_perturbation_validation_v1 as placebo


def row(cohort="BASELINE", race_id="race_a", horse_number=1, score=5, rank=1, top3=True):
    return {
        "cohort": cohort, "race_id": race_id, "race_date": "20260725", "racecourse": "test",
        "horse_number": str(horse_number), "horse_name": f"h{horse_number}",
        "valid_result": True, "actual_finish": horse_number, "actual_top3": top3,
        "buy": False, "decision": "CAUTION", "race_decision": "PASS",
        "production_adjusted_score": 100.0 - horse_number, "production_rank": rank,
        "shadow_recency_score": score, "shadow_recency_category": "TEST",
        "shadow_recency_days": "20", "shadow_explain": "unchanged",
    }


def four_rows(cohort="BASELINE", race_id="race_a"):
    scores = (5, 0, -3, -5)
    return [row(cohort, race_id, index + 1, score, index + 1, index < 3) for index, score in enumerate(scores)]


def dist(mean, sd=0.005, p10=None, p90=None, cohort="BASELINE"):
    return {
        "cohort": cohort, "metric": "rank1_3_top3_rate", "delta_mean": mean,
        "delta_population_sd": sd, "delta_p10": mean - 0.005 if p10 is None else p10,
        "delta_p90": mean + 0.005 if p90 is None else p90,
    }


def distribution_fixture(seed_values):
    rows = []
    for cohort in placebo.EXPECTED:
        for seed in seed_values:
            item = {"cohort": cohort, "placebo_seed": seed}
            for metric in placebo.METRICS:
                item[f"production_{metric}"] = 0
                item[f"placebo_{metric}"] = seed
                item[f"delta_{metric}"] = seed
            rows.append(item)
    return rows


class TestPlaceboPerturbationValidationV1(unittest.TestCase):
    def test_01_race_score_distribution_exact(self):
        source = four_rows()
        actual = placebo.assign_placebo(source, 11)
        self.assertEqual(Counter(r["shadow_recency_score"] for r in source), Counter(r["placebo_score"] for r in actual))

    def test_02_no_global_shuffle(self):
        source = four_rows(race_id="race_a") + [row(race_id="race_b", horse_number=i + 1, score=5) for i in range(4)]
        actual = placebo.generate_seed_rows(source, 17)
        by_race = placebo.group_by_race(actual)
        self.assertEqual(Counter(r["placebo_score"] for r in by_race[("BASELINE", "race_b")]), Counter({5: 4}))

    def test_03_no_cross_race_assignment(self):
        with self.assertRaisesRegex(RuntimeError, "CROSS_RACE"):
            placebo.assign_placebo([row(race_id="a"), row(race_id="b", horse_number=2)], 23)

    def test_04_fixed_20_seeds(self):
        self.assertEqual(len(placebo.SEEDS), 20)
        self.assertEqual(placebo.SEEDS, (11, 17, 23, 29, 37, 41, 47, 53, 59, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109))

    def test_05_per_seed_result_record(self):
        seeded = placebo.assign_placebo(four_rows(), 29)
        result = placebo.seed_metric_row("BASELINE", 29, seeded)
        self.assertEqual(result["placebo_seed"], 29)

    def test_06_seed_reproducibility(self):
        self.assertEqual(placebo.assign_placebo(four_rows(), 37), placebo.assign_placebo(four_rows(), 37))

    def test_07_production_score_unchanged(self):
        source = four_rows()
        actual = placebo.assign_placebo(source, 41)
        self.assertEqual([r["production_adjusted_score"] for r in source], [r["production_adjusted_score"] for r in actual])

    def test_08_production_rank_unchanged(self):
        source = four_rows()
        actual = placebo.assign_placebo(source, 47)
        self.assertEqual([r["production_rank"] for r in source], [r["production_rank"] for r in actual])

    def test_09_decision_unchanged(self):
        source = four_rows()
        self.assertEqual([r["decision"] for r in source], [r["decision"] for r in placebo.assign_placebo(source, 53)])

    def test_10_race_decision_unchanged(self):
        source = four_rows()
        self.assertEqual([r["race_decision"] for r in source], [r["race_decision"] for r in placebo.assign_placebo(source, 59)])

    def test_11_buy_unchanged(self):
        source = four_rows()
        source[0]["buy"] = True
        self.assertEqual([r["buy"] for r in source], [r["buy"] for r in placebo.assign_placebo(source, 67)])

    def test_12_explain_unchanged(self):
        source = four_rows()
        self.assertEqual([r["shadow_explain"] for r in source], [r["shadow_explain"] for r in placebo.assign_placebo(source, 71)])

    def test_13_baseline_replay_separated(self):
        grouped = placebo.group_by_race([row("BASELINE", "same"), row("REPLAY", "same")])
        self.assertEqual(set(grouped), {("BASELINE", "same"), ("REPLAY", "same")})

    def test_14_duplicate_race_count_zero(self):
        source = four_rows("BASELINE", "b") + four_rows("REPLAY", "r")
        expected = {"BASELINE": {"races": 1, "horses": 4}, "REPLAY": {"races": 1, "horses": 4}}
        with patch.dict(placebo.EXPECTED, expected, clear=True):
            self.assertEqual(placebo.validate_cohorts(source)["duplicate_race_count"], 0)

    def test_15_duplicate_horse_rejected(self):
        source = four_rows() + [copy.deepcopy(four_rows()[0])]
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE"):
            placebo.validate_cohorts(source)

    def test_16_rank1_3_rate(self):
        source = [row(horse_number=1, rank=1, top3=True), row(horse_number=2, rank=2, top3=False), row(horse_number=3, rank=3, top3=True)]
        self.assertAlmostEqual(placebo.metric_values(source, "production_rank")["rank1_3_top3_rate"], 2 / 3)

    def test_17_mean_actual_top3_rank(self):
        source = [row(horse_number=1, rank=2, top3=True), row(horse_number=2, rank=4, top3=True)]
        self.assertEqual(placebo.metric_values(source, "production_rank")["mean_actual_top3_rank"], 3)

    def test_18_ndcg_at_3(self):
        source = [row(horse_number=1, rank=1, top3=True), row(horse_number=2, rank=2, top3=False), row(horse_number=3, rank=3, top3=True)]
        actual = placebo.metric_values(source, "production_rank")["ndcg_at_3"]
        self.assertAlmostEqual(actual, 1.5 / (1 + 1 / math.log2(3)))

    def test_19_mrr(self):
        source = [row(horse_number=1, rank=1, top3=False), row(horse_number=2, rank=2, top3=True)]
        self.assertEqual(placebo.metric_values(source, "production_rank")["mrr"], 0.5)

    def test_20_movement_rate(self):
        source = four_rows()
        source[0]["placebo_rank"], source[1]["placebo_rank"] = 2, 1
        source[2]["placebo_rank"], source[3]["placebo_rank"] = 3, 4
        result = placebo.metric_values(source, "placebo_rank", "production_rank")
        self.assertEqual(result["movement_count"], 2)
        self.assertEqual(result["movement_rate"], 0.5)

    def test_21_distribution_mean(self):
        rows = distribution_fixture((1, 3))
        target = next(r for r in placebo.distribution_rows(rows) if r["cohort"] == "BASELINE" and r["metric"] == "mrr")
        self.assertEqual(target["delta_mean"], 2)

    def test_22_distribution_population_sd(self):
        rows = distribution_fixture((1, 3))
        target = next(r for r in placebo.distribution_rows(rows) if r["cohort"] == "REPLAY" and r["metric"] == "mrr")
        self.assertEqual(target["delta_population_sd"], 1)

    def test_23_distribution_min_max(self):
        rows = distribution_fixture((1, 5))
        target = next(r for r in placebo.distribution_rows(rows) if r["cohort"] == "BASELINE" and r["metric"] == "mrr")
        self.assertEqual((target["delta_min"], target["delta_max"]), (1, 5))

    def test_24_percentiles_linear(self):
        self.assertAlmostEqual(placebo.percentile([0, 10], 0.10), 1)
        self.assertAlmostEqual(placebo.percentile([0, 10], 0.90), 9)

    def test_25_placebo_near_zero(self):
        actual = placebo.classify_placebo([dist(0.0, cohort="BASELINE"), dist(0.005, cohort="REPLAY")])
        self.assertEqual(actual[:2], ("PLACEBO_NEAR_ZERO", "REJECT_CONFIRMED_ANTI_PREDICTIVE"))

    def test_26_placebo_near_minus_two(self):
        actual = placebo.classify_placebo([dist(-0.02, cohort="BASELINE"), dist(-0.019, cohort="REPLAY")])
        self.assertEqual(actual[:2], ("PLACEBO_NEAR_MINUS_TWO", "INCONCLUSIVE_INDISTINGUISHABLE_FROM_PLACEBO"))

    def test_27_placebo_destructive(self):
        actual = placebo.classify_placebo([dist(-0.04, cohort="BASELINE"), dist(-0.05, cohort="REPLAY")])
        self.assertEqual(actual[:2], ("PLACEBO_DESTRUCTIVE", "RANKING_ADDITION_METHOD_REJECT"))

    def test_28_placebo_variance_hold(self):
        actual = placebo.classify_placebo([dist(0.0, sd=0.02, cohort="BASELINE"), dist(0.0, cohort="REPLAY")])
        self.assertEqual(actual[:2], ("MIXED_OR_HIGH_VARIANCE", "PLACEBO_VARIANCE_HOLD"))

    def test_29_existing_recency_artifacts_read_only_hash(self):
        before = placebo.matching_files_hash("pre_race_recency*")
        placebo.read_input()
        self.assertEqual(before, placebo.matching_files_hash("pre_race_recency*"))

    def test_30_safety_snapshot_stable_for_read_only(self):
        before = placebo.protected_snapshot()
        placebo.read_input()
        self.assertEqual(before, placebo.protected_snapshot())

    def test_31_zero_delta_flag_off_copy(self):
        source = placebo.read_input()
        copied = copy.deepcopy(source)
        self.assertEqual(placebo.stable_payload_hash(source), placebo.stable_payload_hash(copied))


if __name__ == "__main__":
    unittest.main()
