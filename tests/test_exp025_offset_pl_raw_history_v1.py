from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import numpy as np

from review import exp025_offset_pl_raw_history_v1 as exp


def ds(*, date="260101", surface="芝", distance="1600", field="10", finish="3", abnormal="", margin="1.2", corners=("", "", "", "4")):
    row = [""] * 50
    row[0], row[1], row[2] = date[:2], date[2:4], date[4:]
    row[12], row[14], row[21], row[23], row[25], row[26] = surface, distance, field, finish, abnormal, margin
    row[31:35] = list(corners)
    return row


class Exp025FeatureTest(unittest.TestCase):
    def test_seven_feature_formulas_and_caps(self):
        rows = [ds(date="260103", finish="2", field="5", margin="5.0", distance="1800", surface="ダ", corners=("", "", "", "3")), ds(date="260102", finish="1", field="5", margin="-1", distance="1400", surface="芝", corners=("", "", "2", ""))]
        values, audit = exp.raw_feature_values(rows, target_date="20260110", target_distance=1600, target_surface="芝")
        self.assertAlmostEqual(values[0], ((2 - 1) / 4 + 0) / 2)
        self.assertAlmostEqual(values[1], 1.5)
        self.assertAlmostEqual(values[2], ((3 - 1) / 4 + (2 - 1) / 4) / 2)
        self.assertAlmostEqual(values[3], .2)
        self.assertEqual(values[4], 1.0)
        self.assertAlmostEqual(values[5], math.log1p(7))
        self.assertAlmostEqual(values[6], 2 / 3)
        self.assertEqual(audit["valid_history_count"], 2)

    def test_max_three_and_valid_filtering(self):
        rows = [ds(date=f"2512{day:02d}", finish=str(day), field="10") for day in range(1, 6)]
        rows[0][25] = "1"
        values, audit = exp.raw_feature_values(rows, target_date="20260110", target_distance=1600, target_surface="芝")
        self.assertEqual(audit["valid_history_count"], 3)
        self.assertAlmostEqual(values[6], 1.0)

    def test_missing_continuous_is_training_mean_zero(self):
        scaler = {"continuous_indices": list(exp.CONTINUOUS), "mean": [1.0] * 5, "scale": [2.0] * 5, "fit_rows": 2}
        raw = [None, None, None, None, 1.0, None, 0.0]
        got = exp.scale_transform(raw, scaler)
        self.assertTrue(np.array_equal(got, np.asarray([0, 0, 0, 0, 1, 0, 0], dtype=float)))

    def test_surface_switch_missing_fails_closed(self):
        scaler = {"continuous_indices": list(exp.CONTINUOUS), "mean": [1.0] * 5, "scale": [2.0] * 5, "fit_rows": 2}
        with self.assertRaisesRegex(exp.Stop, "SURFACE_SWITCH_MISSING_POLICY_UNSPECIFIED"):
            exp.scale_transform([None, None, None, None, None, None, 0.0], scaler)

    def test_top3_mass_and_determinism(self):
        utility = np.asarray([.1, .2, -.3, .4])
        left, total_left = exp._top3_from_utility(utility)
        right, total_right = exp._top3_from_utility(utility)
        self.assertEqual(left.tolist(), right.tolist())
        self.assertAlmostEqual(total_left, 3.0)
        self.assertAlmostEqual(total_right, 3.0)

    def test_bootstrap_seed_is_deterministic(self):
        rows = [{"date": "20260301", "race_top3_delta": 1}, {"date": "20260302", "race_top3_delta": -1}]
        self.assertEqual(exp.bootstrap_race_delta(rows), exp.bootstrap_race_delta(rows))

    def test_surface_and_history_depth(self):
        rows = [ds(date="260101", surface="芝")]
        values, _ = exp.raw_feature_values(rows, target_date="20260105", target_distance=1600, target_surface="芝")
        self.assertEqual(values[4], 0.0)
        self.assertEqual(values[6], 1 / 3)

    def test_rest_cap_and_asof_fail_closed(self):
        values, _ = exp.raw_feature_values([ds(date="240101")], target_date="20260105", target_distance=1600, target_surface="芝")
        self.assertAlmostEqual(values[5], math.log1p(365))
        with self.assertRaisesRegex(exp.Stop, "ASOF_VIOLATION"):
            exp.raw_feature_values([ds(date="260105")], target_date="20260105", target_distance=1600, target_surface="芝")

    def test_feature_creation_has_no_label_argument(self):
        # The source-only feature API accepts only history and PRE race context.
        values, audit = exp.raw_feature_values([ds(date="260101", finish="1")], target_date="20260105", target_distance=1600, target_surface="芝")
        self.assertEqual(len(values), 7)
        self.assertEqual(audit["valid_history_count"], 1)

    def test_identity_mismatch_fails_closed(self):
        target = {"date": "20260301", "race_id": "race_20260301_tokyo_1R", "horse_number": 1, "horse_name": "正しい馬"}
        de, dg, ds_rows = [""] * 33, [""] * 11, [""] * 50
        de[1], de[2], de[3], de[7] = "東京", "1", "1", "異なる馬"
        dg[3], dg[4], dg[7], dg[8] = "東京", "1", "芝", "1600"
        paths = {kind: exp.ROOT / f"identity_fixture_{kind}.CSV" for kind in ("DE", "DG", "DS")}
        def source(kind, _date): return paths[kind]
        def read(path, _width): return {paths["DE"]: [de], paths["DG"]: [dg], paths["DS"]: [ds_rows]}[path]
        with patch.object(exp, "source_path", source), patch.object(exp, "read_source", read), patch.object(exp, "sha", lambda _path: "fixture"):
            with self.assertRaisesRegex(exp.Stop, "DE_PRE_IDENTITY"):
                exp.history_by_target([target])

    def test_rolling_folds_are_strictly_chronological(self):
        rows = []
        for month in exp.iter0.MONTHS:
            for finish in (1, 4):
                rows.append({"month": month, "date": month + "01", "race_id": f"race_{month}", "valid_result": True, "actual_top3": finish == 1})
        for fold in exp.iter0.folds(rows):
            self.assertTrue(all(month < fold["evaluation_months"][0] for month in fold["train_months"]))

    def test_fold_reproduction_compares_p_hgb_exactly(self):
        rng = np.random.default_rng(20261020)
        def row(date, race, horse):
            return {"date": date, "month": date[:6], "race_id": race, "horse_number": horse, "features": rng.normal(size=21).tolist(), "valid_result": True, "actual_top3": horse <= 3, "actual_finish": horse}
        train = [row("20260201", f"r{race}", horse) for race in range(20) for horse in range(1, 5)]
        test = [row("20260301", f"r{race}", horse) for race in range(2) for horse in range(1, 5)]
        scaler, coefficient, _ = exp.iter2.pl_fit(train)
        frozen = {}
        for values in exp._race_groups(test).values():
            probability, _ = exp.iter2.pl_top3(scaler.transform(np.asarray([item["features"] for item in values], dtype=float)), coefficient)
            for item, p in zip(values, probability):
                frozen[(item["date"], item["race_id"], item["horse_number"])] = {"p_hgb": float(p)}
        _, _, audit = exp.reproduction(train, test, frozen)
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["max_abs_probability_difference"], 0.0)


if __name__ == "__main__":
    unittest.main()
