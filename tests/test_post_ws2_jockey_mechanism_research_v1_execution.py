"""Execution-boundary and gate-equivalence tests; synthetic data only."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from review import post_ws2_jockey_mechanism_research_v1_model as model


def synthetic_rows():
    rows = []
    for index, month in enumerate(model.EVAL_MONTHS):
        date = month + "01"
        for horse in range(1, 5):
            candidate_score = (5 - horse) / 5 if index % 2 == 0 else horse / 5
            rows.append({
                "date": date, "month": month, "race_id": f"race_{date}_tokyo_1R",
                "horse_number": horse, "horse_name": f"Synthetic{horse}",
                "current_buy": horse == 1, "valid_result": True,
                "actual_top3": horse <= 3, "adjusted_score": float(5 - horse),
                "base_p_top3": (5 - horse) / 5,
                "jockey_p_top3": candidate_score,
                model.FEATURE: 0.1 * horse, "prior_ride_count": horse,
            })
    return rows


class TestExecutionBoundary(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".tmp_jockey_wrapper_", dir=model.ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.canonical = Path(self.temporary.name) / "development"
        self.patch_canonical = patch.object(model, "CANONICAL_OUTPUT", self.canonical)
        self.patch_canonical.start()
        self.addCleanup(self.patch_canonical.stop)

    def test_human_approval_guard_has_no_reads_or_writes(self):
        with patch.object(model, "prepare_development_inputs") as prepare, patch.object(model, "run_development") as development:
            with self.assertRaisesRegex(model.Stop, "STOP_HUMAN_EXECUTION_NOT_APPROVED"):
                model.run()
            prepare.assert_not_called()
            development.assert_not_called()
        self.assertFalse(self.canonical.exists())
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])

    def test_existing_output_stops_before_training_and_preserves_content(self):
        self.canonical.mkdir()
        sentinel = self.canonical / "keep.txt"
        sentinel.write_text("untouched", encoding="utf-8")
        with patch.object(model, "prepare_development_inputs") as prepare, patch.object(model, "run_development") as development:
            with self.assertRaisesRegex(model.Stop, "STOP_OUTPUT_EXISTS"):
                model.run(human_execution_approved=True)
            prepare.assert_not_called()
            development.assert_not_called()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")

    def test_atomic_cleanup_after_temporary_creation(self):
        prepared = {"authority": {}, "targets": [], "features": {}}
        def fail_after_staging(*args, **kwargs):
            self.assertEqual(len(list(Path(self.temporary.name).glob(".development.staging_*"))), 1)
            raise RuntimeError("injected failure")
        with patch.object(model, "prepare_development_inputs", return_value=prepared), patch.object(model, "run_development", side_effect=fail_after_staging):
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                model.run(human_execution_approved=True)
        self.assertFalse(self.canonical.exists())
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])

    def test_success_uses_atomic_rename(self):
        prepared = {"authority": {}, "targets": [], "features": {}}
        def write_fake(staging, *_args):
            self.assertTrue(staging.exists())
            self.assertFalse(self.canonical.exists())
            (staging / "marker").write_text("complete", encoding="utf-8")
            return {"marker": "synthetic"}
        with patch.object(model, "prepare_development_inputs", return_value=prepared), patch.object(model, "run_development", return_value={}), patch.object(model, "_write_execution_artifacts", side_effect=write_fake):
            result = model.run(human_execution_approved=True)
        self.assertEqual(result["EXECUTION_COUNT"], 1)
        self.assertEqual((self.canonical / "marker").read_text(encoding="utf-8"), "complete")
        self.assertEqual(list(Path(self.temporary.name).glob(".development.staging_*")), [])

    def test_required_artifacts_and_hashes(self):
        staging = Path(self.temporary.name) / "staging"
        staging.mkdir()
        rows = synthetic_rows()
        prepared = {
            "authority": {name: digest for name, (_path, digest) in model.AUTHORITIES.items()},
            "targets": [{"date": row["date"]} for row in rows], "features": {},
        }
        result = {"evaluation_rows": rows, "evaluation": {}, "fold_audit": [],
                  "predeclared_diagnostics": {"cold_start_row_rate": 0.0}}
        with patch.object(model, "_fold_report", return_value=[]), patch.object(model, "_gate_report", return_value={"development_gate": "SYNTHETIC"}):
            hashes = model._write_execution_artifacts(staging, prepared, result)
        expected = {
            "authority_verification.json", "fold_audit.json", "evaluation_rows.csv",
            "gate_evaluation.json", "predeclared_diagnostics.json", "artifact_hashes.json",
        }
        self.assertEqual({p.name for p in staging.iterdir()}, expected)
        self.assertEqual(set(hashes), expected - {"artifact_hashes.json"})
        for name, digest in hashes.items():
            self.assertEqual(hashlib.sha256((staging / name).read_bytes()).hexdigest(), digest)
        index = json.loads((staging / "artifact_hashes.json").read_text(encoding="utf-8"))
        self.assertTrue(index["self_hash_excluded"])
        self.assertEqual(
            {name: value["sha256"] for name, value in index["artifacts"].items()}, hashes
        )
        for name, value in index["artifacts"].items():
            self.assertEqual(value["size"], (staging / name).stat().st_size)
        header = (staging / "evaluation_rows.csv").read_text(encoding="utf-8").splitlines()[0]
        self.assertNotIn("odds", header.lower())
        self.assertNotIn("popularity", header.lower())


class TestGateEquivalence(unittest.TestCase):
    def test_exp025_synthetic_gate_equivalence(self):
        rows = synthetic_rows()
        actual = model.evaluate_frozen_gates(rows)
        base, base_rank1 = model.exp025.selection(rows, "base_p_top3")
        candidate, candidate_rank1 = model.exp025.selection(rows, "jockey_p_top3")
        self.assertEqual(actual["base"], model.exp025.metric(base))
        self.assertEqual(actual["candidate"], model.exp025.metric(candidate))
        base_by_race = model.exp025._race_groups(base)
        candidate_by_race = model.exp025._race_groups(candidate)
        race_delta = [{
            "date": key[0], "race_id": key[1],
            "race_top3_delta": model.exp025.metric(candidate_by_race[key])["top3_hits"]
            - model.exp025.metric(base_by_race[key])["top3_hits"],
        } for key in sorted(base_by_race)]
        authoritative_race_boot = model.exp025.bootstrap_race_delta(race_delta, seed=20261023)
        self.assertEqual(actual["race_bootstrap"], authoritative_race_boot)
        _, base_month = model.exp025._full_metric_by_month(rows, lambda subset: model.exp025.selection(subset, "base_p_top3")[0])
        _, candidate_month = model.exp025._full_metric_by_month(rows, lambda subset: model.exp025.selection(subset, "jockey_p_top3")[0])
        paired = [(b, c) for b, c in zip(base_rank1, candidate_rank1) if b["valid_result"] and c["valid_result"]]
        b_rank = model.exp025.metric([b for b, _ in paired])
        c_rank = model.exp025.metric([c for _, c in paired])
        base_brier = model.exp025.brier(rows, "base_p_top3")
        candidate_brier = model.exp025.brier(rows, "jockey_p_top3")
        worse_months = sum(
            model.exp025.brier([r for r in rows if r["month"] == month], "jockey_p_top3")
            > model.exp025.brier([r for r in rows if r["month"] == month], "base_p_top3")
            for month in model.EVAL_MONTHS
        )
        current_global = model.exp025.global_selection(rows, "adjusted_score")
        candidate_global = model.exp025.global_selection(rows, "jockey_p_top3")
        current_daily = {date: model.exp025.metric(value) for date, value in current_global.items()}
        candidate_daily = {date: model.exp025.metric(value) for date, value in candidate_global.items()}
        authoritative_rate_boot = model.exp025.bootstrap_rate(current_daily, candidate_daily, seed=20261023)
        self.assertEqual(actual["global_bootstrap"], authoritative_rate_boot)
        detail = model._gate_report(rows, actual)
        global_components = detail["G5"]["components"]
        current_global_metric = model.exp025.metric([r for values in current_global.values() for r in values])
        candidate_global_metric = model.exp025.metric([r for values in candidate_global.values() for r in values])
        current_global_month = {
            month: model.exp025.metric([r for date, values in current_global.items() if date.startswith(month) for r in values])
            for month in model.EVAL_MONTHS
        }
        candidate_global_month = {
            month: model.exp025.metric([r for date, values in candidate_global.items() if date.startswith(month) for r in values])
            for month in model.EVAL_MONTHS
        }
        rank_current = [
            sorted(values, key=lambda r: (-float(r["adjusted_score"]), int(r["horse_number"])))[0]
            for values in model.exp025._race_groups(rows).values()
        ]
        rank_candidate = [
            sorted(values, key=lambda r: (-float(r["jockey_p_top3"]), int(r["horse_number"])))[0]
            for values in model.exp025._race_groups(rows).values()
        ]
        paired_global = [(left, right) for left, right in zip(rank_current, rank_candidate) if left["valid_result"] and right["valid_result"]]
        rank_current_metric = model.exp025.metric([left for left, _ in paired_global])
        rank_candidate_metric = model.exp025.metric([right for _, right in paired_global])
        expected_components = {
            "rate_at_least_current_plus_6pp": candidate_global_metric["top3_rate"] - current_global_metric["top3_rate"] >= 0.06,
            "above_current_in_at_least_5_months": sum(candidate_global_month[m]["top3_rate"] > current_global_month[m]["top3_rate"] for m in model.EVAL_MONTHS) >= 5,
            "global_bootstrap_lower_above_zero": authoritative_rate_boot["ci_lower_95"] > 0.0,
            "paired_rank1_guard": rank_candidate_metric["top3_rate"] >= rank_current_metric["top3_rate"] - 0.01,
            "calibration_guard": candidate_brier <= base_brier and worse_months <= 2,
        }
        self.assertEqual(global_components, expected_components)
        expected = {
            "GATE_1": authoritative_race_boot["ci_lower_95"] > 0.0,
            "GATE_2": sum(candidate_month[m]["top3_rate"] >= base_month[m]["top3_rate"] for m in model.EVAL_MONTHS) >= 5,
            "GATE_3": c_rank["top3_rate"] >= b_rank["top3_rate"] - 0.01,
            "GATE_4": candidate_brier <= base_brier and worse_months <= 2,
            "GATE_5": all(expected_components.values()),
        }
        self.assertEqual(actual["gates"], expected)
        self.assertEqual(actual["development_gate"], all(expected.values()))
        self.assertEqual(detail["G2"]["pass"], expected["GATE_2"])
        self.assertEqual(detail["G3"]["pass"], expected["GATE_3"])
        self.assertEqual(detail["G4"]["pass"], expected["GATE_4"])
        self.assertEqual(detail["G5"]["pass"], expected["GATE_5"])
        self.assertEqual(len(global_components), 5)


if __name__ == "__main__":
    unittest.main()
