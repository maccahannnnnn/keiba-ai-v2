"""Synthetic and static tests only: no Result source or model execution."""
from __future__ import annotations

import inspect
import math
import unittest
from unittest.mock import patch

import numpy as np

from review import post_ws2_jockey_mechanism_research_v1_model as model


def target(date="20260321", horse=("Target", "Sire", "Maternal")):
    return {
        "date": date, "race_id": f"race_{date}_hanshin_6R", "horse_number": 4,
        "horse_identity": horse, "current_jockey_normalized": "JockeyA",
    }


def ride(
    *, snapshot="20260320", history="20260301", horse=("Other", "Sire", "Maternal"),
    race="race_20260301_hanshin_1R", field="10", finish="2", valid=True,
):
    return {
        "snapshot_date": snapshot, "historical_race_date": history,
        "horse_identity": horse, "historical_race_id": race,
        "historical_jockey_normalized": "JockeyA", "field_size": field,
        "finish": finish, "completed_valid": valid,
    }


class IdentityScaler:
    def transform(self, values):
        return np.asarray(values, dtype=float)


class TestJockeyMechanismModel(unittest.TestCase):
    def test_cold_start_exact_zero(self):
        value = model.jockey_top3_lift(target(), [])
        self.assertEqual((value[model.FEATURE], value["H"], value["E"]), (0.0, 0, 0.0))

    def test_future_snapshot_excluded(self):
        self.assertEqual(model.jockey_top3_lift(target(), [ride(snapshot="20260322")])["prior_ride_count"], 0)

    def test_same_day_snapshot_and_prior_history(self):
        same_day = ride(snapshot="20260321")
        future_history = ride(snapshot="20260321", history="20260321", race="future")
        value = model.jockey_top3_lift(target(), [same_day, future_history])
        self.assertEqual(value["prior_ride_count"], 1)
        self.assertEqual(value[model.FEATURE], math.log(11.0 / 10.3))

    def test_own_horse_rides_excluded(self):
        self.assertEqual(model.jockey_top3_lift(target(), [ride(horse=target()["horse_identity"])])["prior_ride_count"], 0)

    def test_cross_snapshot_duplicate_does_not_double_count(self):
        first, second = ride(), ride(snapshot="20260321")
        value = model.jockey_top3_lift(target(), [first, second])
        self.assertEqual((value["prior_ride_count"], value["H"], value["E"]), (1, 1, 0.3))

    def test_invalid_field_size_and_invalid_finish_excluded_from_both(self):
        bad = ["bad", "2.5", "1", "NaN", "inf", ""]
        records = [ride(field=field, race=str(index)) for index, field in enumerate(bad)]
        records.append(ride(finish="", race="invalid_finish"))
        records.append(ride(valid=False, race="incomplete"))
        value = model.jockey_top3_lift(target(), records)
        self.assertEqual((value["prior_ride_count"], value["H"], value["E"]), (0, 0, 0.0))

    def test_raw_log_ratio_not_standardized(self):
        value = model.jockey_top3_lift(target(), [ride()])[model.FEATURE]
        self.assertEqual(value, math.log(11.0 / 10.3))
        source = inspect.getsource(model.fit_jockey_offset)
        self.assertNotIn("StandardScaler", source)
        self.assertNotIn("scale_fit", source)
        self.assertNotIn("raw_scaler", source)

    def test_per_row_pit_uses_each_target_date(self):
        records = {"20260321": [ride(snapshot="20260321")], "20260322": [ride(snapshot="20260322", history="20260321", race="later")]}
        targets = [target("20260321"), target("20260322")]
        actual = model.feature_map_asof(targets, records)
        first = actual[("20260321", targets[0]["race_id"], 4)]
        second = actual[("20260322", targets[1]["race_id"], 4)]
        self.assertEqual((first["prior_ride_count"], second["prior_ride_count"]), (1, 2))

    def test_partial_objective_matches_exp025_one_axis(self):
        rows = [
            {"base_utility": float(index) / 10, model.FEATURE: float(index) / 20}
            for index in range(4)
        ]
        one = model._partial_objective_one([(rows, [0, 1, 2])], np.asarray([0.6]))
        authority_rows = [dict(row, raw_z=np.asarray([row[model.FEATURE]] + [0.0] * 6)) for row in rows]
        authority = model.exp025._partial_objective([(authority_rows, [0, 1, 2])], np.asarray([0.6] + [0.0] * 6))
        self.assertAlmostEqual(one[0], authority[0], places=14)
        self.assertAlmostEqual(one[1][0], authority[1][0], places=14)

    def test_optimizer_frozen_configuration_and_failure_stop(self):
        train = [
            {"features": [0.0] * 20, model.FEATURE: float(i), "valid_result": True, "actual_finish": i + 1,
             "date": "20260201", "race_id": "race_20260201_tokyo_1R", "horse_number": i + 1}
            for i in range(3)
        ]
        observed = {}
        def fake_minimize(fun, x0, *, jac, method, options):
            observed.update(x0=x0.copy(), method=method, options=options, objective=fun(x0), gradient=jac(x0))
            return type("Fit", (), {"success": True, "x": np.asarray([0.1]), "fun": 0.5, "nit": 1})()
        with patch.object(model.iter2, "valid_pl_races", return_value=([(train, [0, 1, 2])], [])), patch.object(model, "minimize", side_effect=fake_minimize):
            beta, audit = model.fit_jockey_offset(train, IdentityScaler(), np.zeros(19))
        self.assertEqual(beta, 0.1)
        self.assertEqual(observed["x0"].tolist(), [0.0])
        self.assertEqual((observed["method"], observed["options"]), ("L-BFGS-B", {"maxiter": 1000, "gtol": 1e-6}))
        self.assertEqual(audit["l2"], 0.0)
        self.assertEqual(len(observed["gradient"]), 1)
        failed = type("Fit", (), {"success": False, "x": np.asarray([0.0]), "fun": 0.5, "nit": 0, "message": "fail"})()
        with patch.object(model.iter2, "valid_pl_races", return_value=([(train, [0, 1, 2])], [])), patch.object(model, "minimize", return_value=failed):
            with self.assertRaisesRegex(model.Stop, "STOP_JOCKEY_OFFSET_NUMERICAL"):
                model.fit_jockey_offset(train, IdentityScaler(), np.zeros(19))

    def test_top3_path_uses_authoritative_enumeration(self):
        rows = [{"date": "20260301", "race_id": "r", "features": [0.0] * 20,
                 model.FEATURE: 0.1 * index} for index in range(4)]
        with patch.object(model.exp025, "_top3_from_utility", wraps=model.exp025._top3_from_utility) as authority:
            model.predict_fold(rows, IdentityScaler(), np.zeros(19), 0.5)
            authority.assert_called_once()
            np.testing.assert_allclose(authority.call_args.args[0], [0.0, 0.05, 0.1, 0.15])
        self.assertAlmostEqual(sum(row["jockey_p_top3"] for row in rows), 3.0)

    def test_base_reproduction_exact_difference_required(self):
        test = [{"date": "20260301", "race_id": "r", "horse_number": i + 1,
                 "features": [0.0] * 20} for i in range(3)]
        frozen = {(row["date"], row["race_id"], row["horse_number"]): {"p_hgb": 1.0} for row in test}
        with patch.object(model.exp025.iter2, "pl_fit", return_value=(IdentityScaler(), np.zeros(19), {})):
            with patch.object(model.exp025.iter2, "pl_top3", return_value=(np.ones(3), 3.0)):
                self.assertEqual(model.assert_exact_base_reproduction([], test, frozen)[2]["max_abs_probability_difference"], 0.0)
                frozen[("20260301", "r", 1)]["p_hgb"] = 0.9999999999999999
                with self.assertRaisesRegex(model.Stop, "STOP_BASE_PL_REPRODUCTION_FAILURE"):
                    model.assert_exact_base_reproduction([], test, frozen)

    def test_both_bootstraps_explicit_seed_on_synthetic_rows(self):
        rows = []
        for month in model.EVAL_MONTHS:
            date = month + "01"
            for horse in range(1, 4):
                rows.append({"date": date, "month": month, "race_id": "race_" + date + "_tokyo_1R",
                             "horse_number": horse, "current_buy": horse == 1, "valid_result": True,
                             "actual_top3": True, "adjusted_score": float(4-horse),
                             "base_p_top3": float(4-horse) / 4,
                             "jockey_p_top3": float(4-horse) / 4})
        calls = []
        def fake_race(values, *, seed):
            calls.append(("race", seed)); return {"ci_lower_95": 0.0}
        def fake_rate(left, right, *, seed):
            calls.append(("rate", seed)); return {"ci_lower_95": 0.0}
        with patch.object(model.exp025, "bootstrap_race_delta", side_effect=fake_race), patch.object(model.exp025, "bootstrap_rate", side_effect=fake_rate):
            model.evaluate_frozen_gates(rows)
        self.assertEqual(calls, [("race", 20261023), ("rate", 20261023)])

    def test_consumed_secondary_blocked(self):
        self.assertEqual(len(model.development_source_dates()), 62)
        self.assertEqual(model.development_source_dates()[-1], "20260913")
        self.assertNotIn("20260919", model.development_source_dates())
        for date in ("20260919", "20261012"):
            with self.assertRaisesRegex(model.Stop, "STOP_CONSUMED_SECONDARY_DATE"):
                model.reject_consumed_secondary([{"date": date}])

    def test_execution_guard_and_no_final_fit_path(self):
        with self.assertRaisesRegex(model.Stop, "STOP_HUMAN_EXECUTION_APPROVAL_REQUIRED"):
            model.run_development()
        with self.assertRaisesRegex(model.Stop, "STOP_USE_ATOMIC_EXECUTION_WRAPPER"):
            model.run_development(human_execution_approved=True)
        source = inspect.getsource(model.run_development)
        self.assertNotIn("final_model", source)
        self.assertNotIn("final_rows", source)
        self.assertNotIn("write_text", source)
        self.assertNotIn("fit_offset(final", source)


if __name__ == "__main__":
    unittest.main()
