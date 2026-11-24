"""One-fit, TRAIN-only freezer for LOW_CAPACITY_TOP3_SELECTOR_V2.

The runner builds the frozen TRAIN candidate set from pre-race artifacts,
writes environment provenance, and only then parses outcome fields for TRAIN
rows.  The mixed historical result export is byte-filtered by the leading
block/date fields; August rows are never decoded as CSV or read into label
records.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sys
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import scipy
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "low_capacity_top3_selector_v2_train_v1_retry2"
FEATURES = ("Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle")
GATES = ("absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass")
BLOCKS = {
    "JUNE_BLOCK_1": ("20260620", "20260621", "20260627", "20260628"),
    "JULY_H1": ("20260704", "20260705", "20260711", "20260712"),
    "JULY_H2": ("20260718", "20260719", "20260725", "20260726"),
}
PREDICTION_ROOTS = {
    **{d: ROOT / "reports" / "h5_temporal_june_block1_v1" / f"prediction_{d}" for d in BLOCKS["JUNE_BLOCK_1"]},
    **{d: ROOT / "reports" / "cand_h5_001_july_4day_validation_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H1"]},
    **{d: ROOT / "reports" / "h5_temporal_july_h2_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H2"]},
}
RESULT_EXPORT = ROOT / "reports" / "failed_buy_root_cause_v1" / "top5_result_export.csv"
EXPECTED = {"races": 203, "candidates": 317, "candidate_races": 126}


def fail(code: str) -> None:
    raise RuntimeError(code)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def truth(value: object, field: str, key: str) -> bool:
    if not isinstance(value, bool):
        fail(f"TRAIN_POPULATION_INTEGRITY_FAILURE:NON_BOOLEAN_{field}:{key}")
    return value


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(name: str, rows: list[dict], names: list[str]) -> None:
    with (OUT / name).open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=names, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def environment_manifest() -> dict:
    import pip
    return {
        "protocol": "LOW_CAPACITY_TOP3_SELECTOR_V2",
        "environment_frozen_before_train_outcome_access": True,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "scikit_learn_version": sklearn.__version__,
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "pip_version": pip.__version__,
        "joblib_version": joblib.__version__,
        "installation_method": f"{sys.executable} -m pip install scikit-learn",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def pre_only_candidates() -> tuple[list[dict], dict, list[Path]]:
    rows: list[dict] = []
    race_ids: set[str] = set()
    identities: set[tuple[str, int]] = set()
    candidate_races: set[str] = set()
    artifact_paths: list[Path] = []
    source_index = 0
    for block, dates in BLOCKS.items():
        for date in dates:
            paths = sorted(PREDICTION_ROOTS[date].glob("race_*_prediction.json"))
            if not paths:
                fail(f"TRAIN_POPULATION_INTEGRITY_FAILURE:MISSING_PREDICTION_ARTIFACT:{date}")
            artifact_paths.extend(paths)
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                race_id = str(payload.get("race_id") or "")
                trace = payload.get("buy_gate_trace")
                race = trace.get("race") if isinstance(trace, dict) else None
                horses = trace.get("horses") if isinstance(trace, dict) else None
                if not race_id or race_id in race_ids or not isinstance(race, dict) or not isinstance(horses, list):
                    fail(f"TRAIN_POPULATION_INTEGRITY_FAILURE:TRACE_STRUCTURE:{path}")
                race_ids.add(race_id)
                state = race.get("shadow_race_state")
                if state not in {"PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"}:
                    fail(f"TRAIN_POPULATION_INTEGRITY_FAILURE:UNKNOWN_RACE_STATE:{race_id}:{state}")
                for trace_index, horse in enumerate(horses):
                    number = horse.get("horse_number")
                    key_text = f"{race_id}:{number}"
                    if not isinstance(number, int) or (race_id, number) in identities:
                        fail(f"TRAIN_POPULATION_INTEGRITY_FAILURE:IDENTITY:{key_text}")
                    identities.add((race_id, number))
                    gate_pass = all(truth(horse.get(gate), gate, key_text) for gate in GATES)
                    candidate = truth(horse.get("shadow_buy_candidate"), "shadow_buy_candidate", key_text)
                    if candidate != gate_pass:
                        fail(f"TRAIN_POPULATION_INTEGRITY_FAILURE:GATE_EQUIVALENCE:{key_text}")
                    if not candidate:
                        continue
                    snapshot = horse.get("evaluator_score_snapshot")
                    if not isinstance(snapshot, dict):
                        fail(f"TRAIN_POPULATION_INTEGRITY_FAILURE:SNAPSHOT_MISSING:{key_text}")
                    feature_values: dict[str, float] = {}
                    for feature in FEATURES:
                        value = snapshot.get(feature)
                        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                            fail(f"TRAIN_POPULATION_INTEGRITY_FAILURE:FEATURE_INVALID:{key_text}:{feature}")
                        feature_values[feature] = float(value)
                    source_index += 1
                    rows.append({
                        "date": date, "temporal_block": block, "race_id": race_id, "horse_number": number,
                        "convergence_state": state, "source_artifact_identifier": str(path.relative_to(ROOT)),
                        "source_row_identifier": f"buy_gate_trace.horses[{trace_index}]", **feature_values,
                    })
                    candidate_races.add(race_id)
    actual = {"races": len(race_ids), "candidates": len(rows), "candidate_races": len(candidate_races), "unique_horse_identities": len(identities)}
    if any(actual[key] != EXPECTED[key] for key in EXPECTED):
        fail(f"TRAIN_POPULATION_INTEGRITY_FAILURE:EXPECTED={EXPECTED}:ACTUAL={actual}")
    return rows, actual, artifact_paths


def train_outcomes_only() -> dict[tuple[str, int], dict]:
    """Parse actual label fields only for rows whose leading block is TRAIN."""
    train_blocks = set(BLOCKS)
    outcomes: dict[tuple[str, int], dict] = {}
    august_rows_skipped_without_label_decode = 0
    with RESULT_EXPORT.open("rb") as source:
        header = source.readline().decode("utf-8").rstrip("\r\n").split(",")
        required = ["block", "date", "race_id", "rank", "horse_number", "is_buy", "valid_result", "actual_top3", "raw_result"]
        if header != required:
            fail("TRAIN_RESULT_LABEL_AUDIT_FAILURE:RESULT_EXPORT_HEADER")
        for raw_line in source:
            prefix = raw_line.split(b",", 5)
            if len(prefix) != 6:
                fail("TRAIN_RESULT_LABEL_AUDIT_FAILURE:RESULT_EXPORT_PREFIX")
            block = prefix[0].decode("utf-8")
            date = prefix[1].decode("utf-8")
            if block not in train_blocks:
                august_rows_skipped_without_label_decode += 1
                continue
            row = next(csv.DictReader([raw_line.decode("utf-8")], fieldnames=header))
            if row["block"] != block or row["date"] != date:
                fail("TRAIN_RESULT_LABEL_AUDIT_FAILURE:BLOCK_DATE_PARSE")
            key = (row["race_id"], int(row["horse_number"]))
            if key in outcomes:
                fail(f"TRAIN_RESULT_LABEL_AUDIT_FAILURE:DUPLICATE_RESULT_KEY:{key}")
            if row["valid_result"] not in {"True", "False"} or row["actual_top3"] not in {"True", "False"}:
                fail(f"TRAIN_RESULT_LABEL_AUDIT_FAILURE:BOOLEAN_SEMANTICS:{key}")
            outcomes[key] = {"valid_result": row["valid_result"] == "True", "actual_top3": row["actual_top3"] == "True", "date": date, "block": block}
    return outcomes | {("__AUDIT__", 0): {"august_rows_skipped_without_label_decode": august_rows_skipped_without_label_decode}}


def diagnostic(rows: list[dict]) -> dict:
    output = {}
    for state in ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS"):
        group = [row for row in rows if row["convergence_state"] == state]
        true_count = sum(row["actual_top3"] is True for row in group)
        output[state] = {"candidate_count": len(group), "Top3_true": true_count, "Top3_false": len(group) - true_count,
                         "Top3_base_rate": true_count / len(group) if group else None,
                         "independent_race_count": len({row["race_id"] for row in group})}
    return output


def main() -> None:
    if OUT.exists():
        fail("PROTOCOL_INTEGRITY_FAILURE:OUTPUT_EXISTS")
    OUT.mkdir(parents=True)

    # Environment provenance is immutably written before any result-label call.
    environment = environment_manifest()
    write_json("environment_manifest.json", environment)
    environment_sha = sha256(OUT / "environment_manifest.json")

    # Sections 4–6: all PRE-only.
    candidates, population, prediction_paths = pre_only_candidates()
    write_json("train_population_pre_only.json", population)
    write_json("source_artifacts_pre_only.json", {
        "prediction_artifact_count": len(prediction_paths),
        "prediction_artifacts": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in prediction_paths],
        "outcome_source": str(RESULT_EXPORT.relative_to(ROOT)),
        "outcome_source_access_rule": "only TRAIN rows are CSV-decoded; August rows are skipped before label decode",
        "august_outcome_access": 0,
    })

    # Section 7: outcome labels may now be loaded for TRAIN records only.
    outcome_map = train_outcomes_only()
    audit = outcome_map.pop(("__AUDIT__", 0))
    for row in candidates:
        key = (row["race_id"], row["horse_number"])
        outcome = outcome_map.get(key)
        if outcome is None:
            fail(f"TRAIN_RESULT_LABEL_AUDIT_FAILURE:MISSING_RESULT_KEY:{key}")
        if outcome["date"] != row["date"] or outcome["block"] != row["temporal_block"]:
            fail(f"TRAIN_RESULT_LABEL_AUDIT_FAILURE:DATE_BLOCK_MISMATCH:{key}")
        row["valid_result"] = outcome["valid_result"]
        row["actual_top3"] = outcome["actual_top3"]
        row["fit_included"] = outcome["valid_result"]
    valid = [row for row in candidates if row["fit_included"]]
    invalid = [row for row in candidates if not row["fit_included"]]
    top3_true = sum(row["actual_top3"] for row in valid)
    top3_false = len(valid) - top3_true
    label_audit = {"status": "PASS", "TRAIN_ELIGIBLE_CANDIDATES_PRE_RESULT": len(candidates),
                   "TRAIN_VALID_LABEL_CANDIDATES": len(valid), "TRAIN_INVALID_RESULT_CANDIDATES": len(invalid),
                   "TOP3_TRUE": top3_true, "TOP3_FALSE": top3_false,
                   "INDEPENDENT_TRAIN_RACES_AFTER_FILTER": len({row["race_id"] for row in valid}),
                   "august_rows_skipped_without_label_decode": audit["august_rows_skipped_without_label_decode"],
                   "AUGUST_OUTCOME_ACCESS": 0}
    if not valid or not top3_true or not top3_false:
        fail(f"FIT_NOT_VIABLE_PROTOCOL_STOP:LABEL_COUNTS:{label_audit}")

    manifest_fields = ["date", "temporal_block", "race_id", "horse_number", "convergence_state", "valid_result", *FEATURES,
                       "actual_top3", "fit_included", "source_artifact_identifier", "source_row_identifier"]
    write_csv("train_candidate_manifest.csv", candidates, manifest_fields)
    candidate_manifest_sha = sha256(OUT / "train_candidate_manifest.csv")
    write_json("train_label_audit.json", label_audit)
    write_json("convergence_diagnostic.json", diagnostic(valid))

    # Section 15: only viability checks; never used to alter the frozen design.
    X = np.asarray([[row[feature] for feature in FEATURES] for row in valid], dtype=float)
    y = np.asarray([int(row["actual_top3"]) for row in valid], dtype=int)
    variance = X.var(axis=0)
    viability = {
        "status": "FIT_VIABLE", "positive_labels_exist": bool(np.any(y == 1)), "negative_labels_exist": bool(np.any(y == 0)),
        "feature_order": list(FEATURES), "all_features_finite": bool(np.isfinite(X).all()), "missing_feature_count": 0,
        "feature_variance": {feature: float(variance[index]) for index, feature in enumerate(FEATURES)},
        "every_feature_variance_gt_zero": bool(np.all(variance > 0)),
        "independent_train_races": len({row["race_id"] for row in valid}),
        "separation_assessment": "NO_PREVENTING_SYMPTOM_OBSERVED; L2-regularized frozen logistic fit will be attempted once",
    }
    if not (viability["positive_labels_exist"] and viability["negative_labels_exist"] and viability["all_features_finite"] and viability["every_feature_variance_gt_zero"] and viability["independent_train_races"] > 1):
        fail(f"FIT_NOT_VIABLE_PROTOCOL_STOP:{viability}")
    write_json("fit_viability.json", viability)

    # The sole frozen model fit in this protocol.
    pipeline = Pipeline([
        ("scaler", StandardScaler(with_mean=True, with_std=True)),
        ("logistic_regression", LogisticRegression(penalty="l2", C=1.0, solver="lbfgs", tol=1e-4, max_iter=1000, class_weight=None, fit_intercept=True)),
    ])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        pipeline.fit(X, y)
    convergence_warnings = [str(item.message) for item in caught if issubclass(item.category, ConvergenceWarning)]
    if convergence_warnings:
        fail(f"MODEL_FIT_PROTOCOL_FAILURE:CONVERGENCE_WARNING:{convergence_warnings}")
    logistic = pipeline.named_steps["logistic_regression"]
    scaler = pipeline.named_steps["scaler"]
    if int(logistic.n_iter_[0]) > 1000:
        fail(f"MODEL_FIT_PROTOCOL_FAILURE:N_ITER:{logistic.n_iter_.tolist()}")
    model_path = OUT / "low_capacity_top3_selector_v2_pipeline.joblib"
    joblib.dump(pipeline, model_path)
    model_sha = sha256(model_path)
    model_metadata = {
        "protocol": "LOW_CAPACITY_TOP3_SELECTOR_V2", "model_fit_count": 1,
        "feature_names": list(FEATURES), "scaler": {"with_mean": True, "with_std": True, "mean_": scaler.mean_.tolist(), "scale_": scaler.scale_.tolist()},
        "logistic_regression": {"penalty": "l2", "C": 1.0, "solver": "lbfgs", "tol": 1e-4, "max_iter": 1000,
                                "class_weight": None, "fit_intercept": True, "random_state": "NOT_SPECIFIED",
                                "coef_": logistic.coef_.tolist(), "intercept_": logistic.intercept_.tolist(), "n_iter_": logistic.n_iter_.tolist()},
        "fit_convergence_status": "SUCCESS_NO_CONVERGENCE_WARNING", "python_version": sys.version,
        "scikit_learn_version": sklearn.__version__, "numpy_version": np.__version__, "scipy_version": scipy.__version__,
        "train_candidate_manifest_sha256": candidate_manifest_sha, "environment_manifest_sha256": environment_sha,
        "serialized_model_sha256": model_sha,
    }
    write_json("model_metadata.json", model_metadata)
    write_json("frozen_future_action.json", {
        "gate_requirement": list(GATES), "probability_threshold": 0.50, "maximum_buy_per_race": 3,
        "selection": "all p>=0.50; if >3 retain top three probabilities",
        "exact_cutoff_tie_break": ["lower safe shadow_ai_rank", "lower horse_number"],
        "august_evaluated": False,
    })
    summary = {
        "state": "V2_TRAIN_MODEL_FROZEN", "environment_manifest_sha256": environment_sha,
        "train_candidate_manifest_sha256": candidate_manifest_sha, "model_sha256": model_sha,
        "train_population": population, "train_label_audit": label_audit, "fit_viability": viability,
        "model_fit": "SUCCESS", "fit_convergence_status": model_metadata["fit_convergence_status"], "n_iter_": logistic.n_iter_.tolist(),
        "feature_model_action_changed_after_train_access": "NO", "AUGUST_OUTCOME_ACCESS": 0, "CF_CHANGE": 0, "PRODUCTION_CHANGE": 0,
        "alternative_models": 0, "refits": 0,
    }
    write_json("summary.json", summary)
    lines = [
        "# LOW_CAPACITY_TOP3_SELECTOR_V2 — Frozen TRAIN Model", "",
        "Final state: `V2_TRAIN_MODEL_FROZEN`.", "",
        "## Integrity", "",
        "- Environment frozen before TRAIN outcome access: PASS",
        "- TRAIN population reproduction: PASS (203 races, 317 gate-eligible candidates, 126 candidate races)",
        f"- TRAIN label audit: PASS ({len(valid)} valid / {len(invalid)} invalid; Top3 {top3_true} / non-Top3 {top3_false})",
        "- August outcome access: 0", "",
        "## Frozen model", "",
        "- Pipeline: StandardScaler(with_mean=True, with_std=True) → LogisticRegression(l2, C=1.0, lbfgs, tol=1e-4, max_iter=1000)",
        f"- Features: {', '.join(FEATURES)}", f"- Fit: SUCCESS; n_iter={logistic.n_iter_.tolist()}",
        f"- Candidate manifest SHA256: `{candidate_manifest_sha}`", f"- Environment manifest SHA256: `{environment_sha}`", f"- Model SHA256: `{model_sha}`", "",
        "No August validation, alternate fit, CF change, or Production change was performed.",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
