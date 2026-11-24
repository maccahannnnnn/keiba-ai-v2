"""EXP-026 implementation-only tests; no real target Result JOIN or beta fit."""
from __future__ import annotations

import math
import inspect
import unittest
import csv
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import numpy as np

from review import exp025_offset_pl_raw_history_v1 as exp025
from review import exp026_trainer_top3_lift_v1 as subject


def target(date: str, horse: str, number: int, name: str = "Trainer", affiliation: str = "East") -> dict:
    return {"date": date, "race_id": f"race_{date}_tokyo_1R", "horse_number": number,
            "horse_identity": (horse, "Sire", "DamSire"),
            "trainer_name": name, "trainer_affiliation": affiliation}


def record(snapshot: str, date: str, horse: str, code: str, finish: int = 1,
           name: str = "Trainer", affiliation: str = "East", race: str | None = None) -> dict:
    return {"snapshot_date": snapshot, "historical_race_date": date,
            "historical_race_id": race or f"race_{date}_tokyo_1R",
            "horse_identity": (horse, "Sire", "DamSire"),
            "trainer_name": name, "trainer_affiliation": affiliation,
            "trainer_code": code, "field_size": "12", "finish": str(finish)}


class TrainerFeatureTests(unittest.TestCase):
    def test_training_row_uses_own_date_and_future_snapshot_does_not_leak(self) -> None:
        march = target("20260301", "Target", 1)
        april = target("20260401", "Target", 1)
        snapshots = {
            "20260301": [record("20260301", "20260201", "Other", "001")],
            "20260401": [record("20260401", "20260315", "Another", "001", finish=4)],
        }
        result = subject.feature_map_asof([march, april], snapshots)
        self.assertEqual(result[subject.key(march)]["prior_count"], 1)
        self.assertEqual(result[subject.key(april)]["prior_count"], 2)
        self.assertAlmostEqual(result[subject.key(march)]["trainer_top3_lift"], math.log(11 / 10.25))

    def test_target_self_history_is_excluded_across_trainers(self) -> None:
        t = target("20260301", "Target", 1)
        snapshots = {"20260301": [record("20260301", "20260201", "Target", "001"),
                                   record("20260301", "20260202", "Other", "001", finish=2)]}
        result = subject.feature_map_asof([t], snapshots)[subject.key(t)]
        self.assertEqual((result["prior_count"], result["H_T"]), (1, 1))

    def test_cross_snapshot_duplicate_is_counted_once(self) -> None:
        t = target("20260401", "Target", 1)
        first = record("20260301", "20260201", "Other", "001")
        second = dict(first, snapshot_date="20260401")
        result = subject.feature_map_asof([t], {"20260301": [first], "20260401": [second]})
        self.assertEqual(result[subject.key(t)]["prior_count"], 1)

    def test_cross_snapshot_conflict_stops(self) -> None:
        first = record("20260301", "20260201", "Other", "001")
        second = dict(first, snapshot_date="20260401", trainer_code="002")
        with self.assertRaisesRegex(subject.Stop, "CROSS_SNAPSHOT"):
            subject.feature_map_asof([target("20260401", "Target", 1)],
                                    {"20260301": [first], "20260401": [second]})

    def test_future_history_stops(self) -> None:
        with self.assertRaisesRegex(subject.Stop, "SNAPSHOT_DATE"):
            subject.feature_map_asof([target("20260301", "Target", 1)],
                                    {"20260301": [record("20260301", "20260301", "Other", "001")]})

    def test_transfer_keeps_historical_trainer_code(self) -> None:
        t = target("20260301", "Target", 1)
        histories = [record("20260301", "20260201", "Other", "001"),
                     record("20260301", "20260202", "Other", "002", name="NewTrainer")]
        result = subject.feature_map_asof([t], {"20260301": histories})[subject.key(t)]
        self.assertEqual(result["prior_count"], 1)

    def test_transfer_does_not_reintroduce_target_horse_history(self) -> None:
        t = target("20260301", "Target", 1, name="NewTrainer")
        histories = [record("20260301", "20260201", "Target", "001", name="OldTrainer"),
                     record("20260301", "20260202", "Target", "002", name="NewTrainer"),
                     record("20260301", "20260203", "Other", "002", name="NewTrainer")]
        result = subject.feature_map_asof([t], {"20260301": histories})[subject.key(t)]
        self.assertEqual((result["prior_count"], result["H_T"]), (1, 1))

    def test_same_race_other_horse_appearing_later_does_not_rewrite_training_feature(self) -> None:
        march = target("20260301", "Target", 1)
        april = target("20260401", "Target", 1)
        snapshots = {"20260301": [record("20260301", "20260201", "Prior", "001")],
                     "20260401": [record("20260401", "20260301", "OtherInTargetRace", "001")]}
        features = subject.feature_map_asof([march, april], snapshots)
        self.assertEqual(features[subject.key(march)]["prior_count"], 1)
        self.assertEqual(features[subject.key(april)]["prior_count"], 2)

    def test_ambiguous_mapping_and_missing_code_are_neutral(self) -> None:
        t = target("20260301", "Target", 1)
        histories = [record("20260301", "20260201", "HorseA", "001"),
                     record("20260301", "20260202", "HorseB", "002")]
        result = subject.feature_map_asof([t], {"20260301": histories})[subject.key(t)]
        self.assertEqual((result["mapping_status"], result["trainer_top3_lift"]), ("AMBIGUOUS", 0.0))
        missing = subject.feature_map_asof([t], {"20260301": [record("20260301", "20260201", "HorseA", "")]})
        self.assertEqual(missing[subject.key(t)]["trainer_top3_lift"], 0.0)

    def test_beta_zero_exactly_reproduces_existing_pl_jockey_transform(self) -> None:
        base = np.asarray([1.0, 0.5, 0.0, -0.5])
        jockey_lift = np.asarray([0.2, -0.1, 0.4, 0.0])
        trainer_lift = np.asarray([-0.3, 0.5, 0.1, 0.2])
        expected = exp025._top3_from_utility(base + 1.11 * jockey_lift)[0]
        actual = subject.treatment_probabilities(base, jockey_lift, trainer_lift, 1.11, 0.0)
        self.assertTrue(np.array_equal(expected, actual))
        self.assertAlmostEqual(float(actual.sum()), 3.0)

    def test_b1_cap_and_daily_volume(self) -> None:
        rows = []
        for race in ("race_20260301_tokyo_1R", "race_20260301_tokyo_2R"):
            for horse in range(1, 5):
                rows.append({"date": "20260301", "race_id": race, "horse_number": horse,
                             "current_buy": horse <= 2, "p": 1.0 - horse / 10})
        selected = subject.select_b1(rows, "p")
        self.assertEqual(len(selected), 4)
        self.assertEqual(Counter(r["race_id"] for r in selected),
                         Counter({"race_20260301_tokyo_1R": 2, "race_20260301_tokyo_2R": 2}))

    def test_signed_gap_is_not_clipped(self) -> None:
        rows = [{"valid_result": True, "actual_top3": True, "p": 0.2}]
        self.assertEqual(subject.signed_gap(rows, "p"), -0.8)

    def test_saved_b1_identity_and_gap(self) -> None:
        result = subject.verify_saved_b1()
        self.assertEqual((result["selected"], result["valid"], result["hits"]), (716, 714, 380))
        self.assertAlmostEqual(result["gap"], 0.08146014347072025, places=15)

    def test_saved_full_field_b1_membership_reproduction(self) -> None:
        subject.verify_authorities()
        with subject.JOCKEY_ROWS.open(encoding="utf-8-sig", newline="") as handle:
            full = [{"date": r["date"], "race_id": r["race_id"],
                     "horse_number": int(r["horse_number"]),
                     "current_buy": r["current_buy"] == "True",
                     "jockey_p_top3": float(r["jockey_p_top3"])}
                    for r in csv.DictReader(handle)]
        with subject.B1_SOURCE.open(encoding="utf-8-sig", newline="") as handle:
            frozen = {subject.key(r) for r in csv.DictReader(handle)
                      if r["C_B1_GLOBAL_CAP3"] == "True"}
        actual = {subject.key(r) for r in subject.select_b1(full, "jockey_p_top3")}
        self.assertEqual(len(actual), 716)
        self.assertEqual(actual, frozen)

    def test_execution_requires_separate_approval_before_reading_result(self) -> None:
        self.assertFalse(subject.OUT.exists())
        with self.assertRaisesRegex(subject.Stop, "SEPARATE_EXECUTION_APPROVAL"):
            subject.execute_one_shot()
        with self.assertRaisesRegex(subject.Stop, "REVIEW_AND_SEPARATE_EXECUTION_APPROVAL"):
            subject.execute_one_shot(human_execution_approved=True)
        self.assertFalse(subject.OUT.exists())

    def test_execution_paths_cannot_be_passed_by_caller(self) -> None:
        parameters = inspect.signature(subject.execute_one_shot).parameters
        self.assertNotIn("out_dir", parameters)
        self.assertNotIn("prelabel_dir", parameters)
        with self.assertRaises(TypeError):
            subject.execute_one_shot(human_execution_approved=True,
                                     claude_review_accepted=True,
                                     human_approval_id="SYNTHETIC_APPROVAL",
                                     out_dir=Path("alternate"))
        self.assertFalse(subject.OUT.exists())

    def test_failed_start_record_never_reads_result_or_retries(self) -> None:
        with tempfile.TemporaryDirectory(dir=subject.ROOT / ".tmp") as temp:
            root = Path(temp)
            out = root / "one_shot"
            prelabel = root / "prelabel"
            prelabel.mkdir()
            with patch.object(subject, "OUT", out), \
                 patch.object(subject, "PRELABEL_OUT", prelabel), \
                 patch.object(subject, "_json_write", side_effect=OSError("SYNTHETIC_WRITE_FAILURE")), \
                 patch.object(subject, "verify_authorities") as authorities, \
                 patch.object(subject.iter2, "load_rows") as result_read, \
                 patch.object(subject, "_fit_beta") as fit:
                with self.assertRaisesRegex(OSError, "SYNTHETIC_WRITE_FAILURE"):
                    subject.execute_one_shot(human_execution_approved=True,
                                             claude_review_accepted=True,
                                             human_approval_id="SYNTHETIC_APPROVAL")
                authorities.assert_not_called()
                result_read.assert_not_called()
                fit.assert_not_called()
                self.assertTrue(out.is_dir())
                with self.assertRaisesRegex(subject.Stop, "ALREADY_EXISTS"):
                    subject.execute_one_shot(human_execution_approved=True,
                                             claude_review_accepted=True,
                                             human_approval_id="SYNTHETIC_APPROVAL")

    def test_consumed_secondary_scope_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            subject.jockey.reject_consumed_secondary([{"date": "20260919"}])

    def test_exclusive_start_and_stopped_record_in_isolated_folder(self) -> None:
        with tempfile.TemporaryDirectory(dir=subject.ROOT / ".tmp") as temp:
            root = Path(temp)
            self.assertTrue(root.resolve().is_relative_to(subject.ROOT.resolve()))
            prelabel = root / "prelabel"
            prelabel.mkdir()
            (prelabel / "feature_manifest.json").write_text("{}", encoding="utf-8")
            out = root / "one_shot"
            with patch.object(subject, "OUT", out), \
                 patch.object(subject, "PRELABEL_OUT", prelabel), \
                 patch.object(subject, "verify_authorities"), \
                 patch.object(subject, "load_prelabel_inputs", return_value=([], {})), \
                 patch.object(subject, "verify_frozen_prelabel", return_value={"table_sha256": "synthetic", "rows": {}}), \
                 patch.object(subject, "verify_saved_b1"), \
                 patch.object(subject.iter2, "load_rows", side_effect=subject.Stop("SYNTHETIC_RESULT_READ_STOP")):
                with self.assertRaisesRegex(subject.Stop, "SYNTHETIC_RESULT_READ_STOP"):
                    subject.execute_one_shot(human_execution_approved=True,
                                             claude_review_accepted=True,
                                             human_approval_id="SYNTHETIC_APPROVAL")
            self.assertTrue((out / "execution_started.json").is_file())
            started = __import__("json").loads((out / "execution_started.json").read_text(encoding="utf-8"))
            self.assertEqual(started["output_dir"], str(out.resolve()))
            self.assertEqual(started["prelabel_dir"], str(prelabel.resolve()))
            self.assertTrue((out / "execution_stopped.json").is_file())
            self.assertFalse((out / "execution_complete.json").exists())
            with patch.object(subject, "OUT", out), \
                 patch.object(subject, "PRELABEL_OUT", prelabel):
                with self.assertRaisesRegex(subject.Stop, "ALREADY_EXISTS"):
                    subject.execute_one_shot(human_execution_approved=True,
                                             claude_review_accepted=True,
                                             human_approval_id="SYNTHETIC_APPROVAL")

    def test_baseline_failure_prevents_any_trainer_fit(self) -> None:
        with tempfile.TemporaryDirectory(dir=subject.ROOT / ".tmp") as temp:
            root = Path(temp)
            prelabel = root / "prelabel"
            prelabel.mkdir()
            (prelabel / "feature_manifest.json").write_text("{}", encoding="utf-8")
            out = root / "one_shot"
            row = {"date": "20260301", "race_id": "race_20260301_tokyo_1R", "horse_number": 1}
            with patch.object(subject, "OUT", out), \
                 patch.object(subject, "PRELABEL_OUT", prelabel), \
                 patch.object(subject, "verify_authorities"), \
                 patch.object(subject, "load_prelabel_inputs", return_value=([row], {subject.key(row): {}})), \
                 patch.object(subject, "verify_frozen_prelabel", return_value={"table_sha256": "synthetic", "rows": {}}), \
                 patch.object(subject, "verify_saved_b1"), \
                 patch.object(subject.iter2, "load_rows", return_value=[dict(row)]), \
                 patch.object(subject.jockey, "reject_consumed_secondary"), \
                 patch.object(subject, "_baseline_all_folds", side_effect=subject.Stop("SYNTHETIC_BASELINE_MISMATCH")), \
                 patch.object(subject, "_fit_beta") as fit:
                with self.assertRaisesRegex(subject.Stop, "SYNTHETIC_BASELINE_MISMATCH"):
                    subject.execute_one_shot(human_execution_approved=True,
                                             claude_review_accepted=True,
                                             human_approval_id="SYNTHETIC_APPROVAL")
                fit.assert_not_called()
            stopped = __import__("json").loads((out / "execution_stopped.json").read_text(encoding="utf-8"))
            self.assertEqual(stopped["stage"], "ALL_FOLD_ZERO_BETA_BASELINE_REPRODUCTION")

    def test_synthetic_complete_artifacts_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory(dir=subject.ROOT / ".tmp") as temp:
            root = Path(temp)
            prelabel = root / "prelabel"
            prelabel.mkdir()
            (prelabel / "feature_manifest.json").write_text("{}", encoding="utf-8")
            out = root / "one_shot"
            row = {"date": "20260301", "race_id": "race_20260301_tokyo_1R", "horse_number": 1,
                   "horse_name": "Synthetic", "month": "202603", "current_buy": True,
                   "valid_result": True, "actual_top3": True,
                   "JOCKEY_TOP3_LIFT": 0.1, "trainer_top3_lift": 0.2,
                   "prior_count": 1, "mapping_status": "MAPPED", "fold": "SYNTHETIC_FOLD",
                   "control_utility": 0.1, "jockey_p_top3": 0.5,
                   "treatment_utility": 0.1, "trainer_p_top3": 0.5}
            context = {"fold": {"fold_id": "SYNTHETIC_FOLD", "train_months": ["202602"],
                                "evaluation_months": ["202603"], "train_rows": 1, "evaluation_rows": 1},
                       "train": [row], "test": [row], "scaler": object(),
                       "coef": np.zeros(19), "beta_jockey": 1.0, "base_audit": {}}
            with patch.object(subject, "OUT", out), \
                 patch.object(subject, "PRELABEL_OUT", prelabel), \
                 patch.object(subject, "verify_authorities"), \
                 patch.object(subject, "load_prelabel_inputs", return_value=([row], {subject.key(row): {}})), \
                 patch.object(subject, "verify_frozen_prelabel", return_value={"table_sha256": "synthetic", "rows": {}}), \
                 patch.object(subject, "verify_saved_b1"), \
                 patch.object(subject.iter2, "load_rows", return_value=[dict(row)]), \
                 patch.object(subject.jockey, "reject_consumed_secondary"), \
                 patch.object(subject, "_baseline_all_folds", return_value=([context], [row], [row])), \
                 patch.object(subject, "_fit_beta", return_value=(0.0, {"success": True})), \
                 patch.object(subject, "_predict_fold"), \
                 patch.object(subject, "select_b1", return_value=[row] * 716), \
                 patch.object(subject, "_gates", return_value={"verdict": "EXPERIMENT_FAIL", "gates": {}}):
                subject.execute_one_shot(human_execution_approved=True,
                                         claude_review_accepted=True,
                                         human_approval_id="SYNTHETIC_APPROVAL")
            self.assertTrue((out / "execution_complete.json").is_file())
            self.assertFalse((out / "execution_stopped.json").exists())
            completed = __import__("json").loads((out / "execution_complete.json").read_text(encoding="utf-8"))
            self.assertEqual(completed["status"], "COMPLETE")
            self.assertEqual(completed["output_dir"], str(out.resolve()))
            for name, expected_sha in completed["artifact_sha256"].items():
                self.assertEqual(subject.sha(out / name), expected_sha)
            for name in ("evaluation_rows.csv", "fold_audit.json", "selection_comparison.csv",
                         "metrics.json", "execution_started.json", "baseline_verified.json"):
                self.assertTrue((out / name).is_file(), name)
            self.assertFalse(subject.OUT.exists())


class SyntheticEstimatorAndGateTests(unittest.TestCase):
    class _IdentityScaler:
        def transform(self, x: np.ndarray) -> np.ndarray:
            return x

    @staticmethod
    def _fit_rows(all_zero: bool = False, bad: bool = False) -> list[dict]:
        rows = []
        for race in range(10):
            signal = [2.0, 1.0, 0.0, -1.0] if race < 8 else [-1.0, 0.0, 1.0, 2.0]
            for i in range(4):
                value = 0.0 if all_zero else signal[i]
                if bad and race == 0 and i == 0:
                    value = float("nan")
                rows.append({"date": "20260201", "race_id": f"race_20260201_tokyo_{race+1}R",
                             "valid_result": True, "actual_finish": i + 1,
                             "features": np.zeros(19), subject.jockey.FEATURE: 0.0,
                             "trainer_top3_lift": value})
        return rows

    def test_synthetic_positive_trainer_beta(self) -> None:
        beta, audit = subject._fit_beta(self._fit_rows(), self._IdentityScaler(), np.zeros(19), 0.0)
        self.assertGreater(beta, 0.0)
        self.assertTrue(audit["success"])

    def test_synthetic_zero_trainer_feature_gives_zero_beta(self) -> None:
        beta, audit = subject._fit_beta(self._fit_rows(all_zero=True), self._IdentityScaler(), np.zeros(19), 0.0)
        self.assertEqual(beta, 0.0)
        self.assertTrue(audit["success"])

    def test_synthetic_nonfinite_trainer_feature_stops(self) -> None:
        with self.assertRaisesRegex(subject.Stop, "FIT_NONFINITE"):
            subject._fit_beta(self._fit_rows(bad=True), self._IdentityScaler(), np.zeros(19), 0.0)

    @staticmethod
    def _gate_case(worse_months: int = 2, losing_months: int = 3,
                   positive_betas: int = 6, gap_t: float = 0.02) -> dict:
        months = [f"2026{m:02d}" for m in range(3, 10)]
        rows, groups = [], []
        for index, month in enumerate(months):
            race = []
            for horse in range(4):
                win = horse < 3
                worse = index < worse_months
                treatment_p = (0.4 if win else 0.6) if worse else (0.6 if win else 0.4)
                race.append({"date": month + "01", "month": month,
                             "valid_result": True, "actual_top3": win,
                             "jockey_p_top3": 0.5, "trainer_p_top3": treatment_p,
                             "control_utility": 0.0,
                             "treatment_utility": [0.2 + 0.02 * index,
                                                   0.1 + 0.01 * index,
                                                   0.0, -0.1][horse]})
            groups.append((race, [0, 1, 2]))
            rows.extend(race)
        base_counts = [55, 55, 54, 54, 54, 54, 54]
        candidate_counts = list(base_counts)
        for i in range(losing_months):
            candidate_counts[i] -= 1
            candidate_counts[-1] += 1
        base = [{"date": month + "01", "month": month, "valid_result": True, "actual_top3": True}
                for month, count in zip(months, base_counts) for _ in range(count)]
        treatment = [{"date": month + "01", "month": month, "valid_result": True, "actual_top3": True}
                     for month, count in zip(months, candidate_counts) for _ in range(count)]
        betas = [0.1] * positive_betas + [-0.1] * (7 - positive_betas)
        with patch.object(subject.iter2, "valid_pl_races", return_value=(groups, [])), \
             patch.object(subject, "signed_gap", side_effect=[0.0, gap_t]), \
             patch.object(subject, "BASELINE_GAP", 0.0):
            return subject._gates(rows, betas, base, treatment)

    def test_synthetic_g2_six_positive_pass_five_fail(self) -> None:
        self.assertTrue(self._gate_case(positive_betas=6)["gates"]["G2"])
        self.assertFalse(self._gate_case(positive_betas=5)["gates"]["G2"])

    def test_synthetic_g3_two_worse_months_pass_three_fail(self) -> None:
        self.assertTrue(self._gate_case(worse_months=2)["gates"]["G3"])
        self.assertFalse(self._gate_case(worse_months=3)["gates"]["G3"])

    def test_synthetic_g4_exact_boundary_and_negative_gap(self) -> None:
        self.assertTrue(self._gate_case(gap_t=0.02)["gates"]["G4"])
        self.assertFalse(self._gate_case(gap_t=0.020000000000000004)["gates"]["G4"])
        self.assertTrue(self._gate_case(gap_t=-0.1)["gates"]["G4"])

    def test_synthetic_g5_three_losses_pass_four_fail_ties_not_losses(self) -> None:
        result = self._gate_case(losing_months=3)
        self.assertTrue(result["gates"]["G5"])
        self.assertEqual(result["losing_months"], 3)
        self.assertFalse(self._gate_case(losing_months=4)["gates"]["G5"])

    def test_synthetic_g1_bootstrap_seed_is_reproducible(self) -> None:
        first = self._gate_case()
        second = self._gate_case()
        self.assertEqual(first["daily_paired_bootstrap_ci"], second["daily_paired_bootstrap_ci"])
        self.assertEqual(first["bootstrap_seed"], 20261110)
        self.assertEqual((first["g1_point_weighting"], first["g1_bootstrap_weighting"]),
                         ("RACE_EQUAL_MEAN", "DATE_EQUAL_MEAN"))


if __name__ == "__main__":
    unittest.main()
