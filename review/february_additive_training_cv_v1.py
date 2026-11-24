"""Frozen 7-fold February additive-training Control vs Treatment CV experiment.

This is an experiment-only runner.  It never mutates a formal model, a
protocol, production code, or a frozen prediction/result artifact.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.ml_v4_buy_selection_dataset_build_v4 import primary_feature_values, top5_and_buy
from review.ml_v4_buy_selection_dataset_inventory_v2 import Stop, formal_buy_set, outcome, result_for_race, result_rows, sha
from review.ml_v4_buy_selection_model_train_v4 import GATES, SEMANTIC

OUT = ROOT / "reports" / "february_additive_training_cv_v1"
DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v4" / "dataset.csv"
FEBRUARY = ROOT / "reports" / "february_additive_training_dry_run_v1" / "dry_run_dataset.csv"
FOLDS = ("April", "May 2026 Independent OOS additive TRAIN reuse for V4 Model v3+", "June", "July H1", "July H2", "August Development", "August Development (Prospective)")
MARCH = "MARCH_2026_HISTORICAL_HOLDOUT_ADDITIVE_TRAIN_REUSE_V4"
EXPECTED_EXISTING = {"rows": 4100, "validation_rows": 3240, "march_rows": 860}
EXPECTED_FEBRUARY = {"rows": 797, "positive": 244, "negative": 553}
LABEL = "CV_EXPERIMENT_ONLY"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        digest.update(str(p.relative_to(root)).replace("\\", "/").encode()); digest.update(b"\0")
        digest.update(sha(p).encode()); digest.update(b"\n")
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def truth(value: object) -> bool:
    return str(value) == "True" or value is True or str(value) == "1"


def feature_vector(row: dict) -> list[float]:
    """Exact active Model v4 semantics: 20 semantic -> 21 transformed inputs."""
    values = []
    for name in SEMANTIC[:-1]:
        value = float(truth(row[name])) if name in GATES else float(row[name])
        if not math.isfinite(value):
            raise Stop(f"NONFINITE_ACTIVE_FEATURE:{row.get('row_id')}:{name}")
        values.append(value)
    state = row["race_state"]
    values.extend([float(state == "PLAY_UNCONVERGED_4PLUS"), float(state == "SKIP")])
    if len(values) != 21:
        raise Stop("TRANSFORMED_FEATURE_COUNT_INVALID")
    return values


def fit_predict(train: list[dict], valid: list[dict], label: str, fold: str) -> tuple[np.ndarray, StandardScaler, LogisticRegression]:
    x_train = np.asarray([feature_vector(r) for r in train], dtype=float)
    y_train = np.asarray([int(r["actual_top3"]) for r in train], dtype=int)
    if len(set(y_train)) != 2:
        raise Stop(f"TRAIN_LABEL_DEGENERATE:{label}:{fold}")
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x_train)
    model = LogisticRegression(penalty="l2", C=1.0, solver="lbfgs", class_weight=None, max_iter=1000)
    model.fit(x_scaled, y_train)
    return model.predict_proba(scaler.transform(np.asarray([feature_vector(r) for r in valid], dtype=float)))[:, 1], scaler, model


def metric(selected: list[dict]) -> dict:
    valid = [x for x in selected if x["valid_result"]]
    hits = sum(int(x["actual_top3"]) for x in valid)
    return {"nominal_selected_count": len(selected), "invalid_selected_count": len(selected) - len(valid), "valid_selected_count": len(valid), "top3_hits": hits, "buy_top3_rate": hits / len(valid) if valid else None}


def rate_pp(value: float | None) -> float | None:
    return None if value is None else value * 100.0


def same_value(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool) or str(left) in {"True", "False"} or str(right) in {"True", "False"}:
        return truth(left) == truth(right)
    try:
        return abs(float(left) - float(right)) <= 1e-9
    except (TypeError, ValueError):
        return left == right


def full_validation_candidates(dataset_rows: list[dict]) -> tuple[dict[str, list[dict]], dict]:
    """Restore the *frozen* complete Current Top5 universe from referenced PREs.

    Dataset v4 intentionally contains valid rows only; this reconstruction is
    required so a selected invalid runner remains unreplaced in KPI evaluation.
    Every valid reconstructed row is compared back to Dataset v4.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in dataset_rows:
        if r["source_block"] in FOLDS:
            grouped[r["race_id"]].append(r)
    reconstructed: dict[str, list[dict]] = {}
    validation_match_count = invalid_count = 0
    for race_id, known in grouped.items():
        path = ROOT / known[0]["source_prediction_artifact_path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("race_id") != race_id:
            raise Stop(f"PREDICTION_PATH_RACE_ID_MISMATCH:{path}")
        ranked, buys, _ = top5_and_buy(payload, path)
        if len(ranked) != 5:
            raise Stop(f"FROZEN_TOP5_NOT_FIVE:{race_id}:{len(ranked)}")
        expected = {(int(r["horse_number"])): r for r in known}
        traces = {int(x["horse_number"]): x for x in payload.get("buy_gate_trace", {}).get("horses", [])}
        race_trace = payload.get("buy_gate_trace", {}).get("race", {})
        date = known[0]["date"]
        _, result = result_for_race(race_id, result_rows(date))
        maximum = max(float(x["adjusted_score"]) for x in ranked)
        candidates = []
        for horse in ranked:
            number = int(horse["horse_number"])
            values = primary_feature_values(horse, traces.get(number), race_trace, float(horse["adjusted_score"]) - maximum)
            label = outcome(result, number)
            item = {"row_id": f"{date}:{race_id}:{number}", "date": date, "race_id": race_id, "horse_number": number,
                    "horse_name": horse.get("horse_name"), **values, "current_buy": number in buys,
                    "actual_top3": int(bool(label["actual_top3"])), "valid_result": bool(label["valid_result"]),
                    "source_block": known[0]["source_block"], "source_prediction_artifact_path": str(path.relative_to(ROOT))}
            feature_vector(item)
            prior = expected.get(number)
            if item["valid_result"]:
                if prior is None:
                    raise Stop(f"VALID_ROW_MISSING_FROM_DATASET:{item['row_id']}")
                for key in (*SEMANTIC, "actual_top3", "current_buy", "valid_result"):
                    if not same_value(item[key], prior[key]):
                        raise Stop(f"FROZEN_CANDIDATE_RECONSTRUCTION_MISMATCH:{item['row_id']}:{key}")
                validation_match_count += 1
            else:
                invalid_count += 1
            candidates.append(item)
        if set(expected) != {x["horse_number"] for x in candidates if x["valid_result"]}:
            raise Stop(f"VALID_TOP5_IDENTITY_SET_MISMATCH:{race_id}")
        reconstructed[race_id] = candidates
    return reconstructed, {"races": len(reconstructed), "valid_dataset_rows_matched": validation_match_count, "invalid_top5_rows_preserved": invalid_count}


def select_by_probability(candidates: list[dict], probabilities: dict[str, float], k: int) -> list[dict]:
    ordered = sorted(candidates, key=lambda r: (-probabilities[r["row_id"]], float(r["shadow_ai_rank"]), int(r["horse_number"])))
    return ordered[:k]


def secondary(y: list[int], p: list[float]) -> dict:
    return {"row_count": len(y), "roc_auc": roc_auc_score(y, p), "brier_score": brier_score_loss(y, p), "logloss": log_loss(y, p, labels=[0, 1])}


def main() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    protected = [ROOT / "reports" / "ml_v4_buy_selection_dataset_v4", ROOT / "reports" / "ml_v4_buy_selection_model_v4", ROOT / "reports" / "february_additive_training_dry_run_v1", ROOT / "reports" / "v4_model_v3_formal_prospective", ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"]
    before = {str(p.relative_to(ROOT)): tree_hash(p) for p in protected}
    head_before, status_before = git("rev-parse", "HEAD"), git("status", "--porcelain")
    existing, february = read_csv(DATASET), read_csv(FEBRUARY)
    if len(existing) != EXPECTED_EXISTING["rows"] or len(february) != EXPECTED_FEBRUARY["rows"]:
        raise Stop("FROZEN_INPUT_ROW_COUNT_MISMATCH")
    blocks = Counter(r["source_block"] for r in existing)
    if sum(blocks[f] for f in FOLDS) != EXPECTED_EXISTING["validation_rows"] or blocks[MARCH] != EXPECTED_EXISTING["march_rows"]:
        raise Stop(f"FOLD_INVENTORY_MISMATCH:{dict(blocks)}")
    if sum(int(r["actual_top3"]) for r in february) != EXPECTED_FEBRUARY["positive"]:
        raise Stop("FEBRUARY_POSITIVE_COUNT_MISMATCH")
    if any(r["source_block"] != "FEBRUARY_2026_ADDITIVE_TRAIN_DRY_RUN" or r["split_role"] != "TREATMENT_TRAIN_ONLY" for r in february):
        raise Stop("FEBRUARY_ROLE_MISMATCH")
    if set(r["row_id"] for r in existing) & set(r["row_id"] for r in february):
        raise Stop("FEBRUARY_EXISTING_IDENTITY_OVERLAP")
    for row in [*existing, *february]:
        feature_vector(row)

    OUT.mkdir(parents=True); (OUT / "cv_experiment_only_models").mkdir()
    write("authority.json", {"status": "HUMAN_APPROVED", "question": "Does adding the 797 February training rows improve the fixed Model v4 recipe on the same non-February validation population?", "dataset_v4": {"path": str(DATASET.relative_to(ROOT)), "sha256": sha(DATASET), "rows": len(existing)}, "february_dry_run": {"path": str(FEBRUARY.relative_to(ROOT)), "sha256": sha(FEBRUARY), "rows": len(february)}, "model_recipe": {"semantic_features": list(SEMANTIC), "semantic_feature_count": 20, "transformed_feature_count": 21, "scaler": "StandardScaler", "estimator": "LogisticRegression", "penalty": "L2", "C": 1.0, "solver": "lbfgs", "class_weight": None}})
    write("design_freeze.json", {"fold_count": 7, "folds": list(FOLDS), "march": MARCH, "february": "FEBRUARY_2026_ADDITIVE_TRAIN_DRY_RUN", "treatment_only_change": "additive 797 February rows", "forbidden": ["feature change", "weighting", "sampling", "threshold optimization", "final candidate model", "production change"]})
    write("fold_inventory.json", {"existing_rows": len(existing), "source_block_counts": dict(blocks), "validation_capable_rows": sum(blocks[f] for f in FOLDS), "march_train_only_rows": blocks[MARCH], "february_treatment_train_only_rows": len(february), "february_positive": sum(int(r["actual_top3"]) for r in february), "february_negative": len(february)-sum(int(r["actual_top3"]) for r in february)})

    all_candidates, reconstruction = full_validation_candidates(existing)
    fold_records, validation_predictions, race_delta, models, scalers, leakage = {}, [], [], [], [], []
    for fold in FOLDS:
        valid_rows = [r for r in existing if r["source_block"] == fold]
        control = [r for r in existing if r["source_block"] != fold]
        treatment = [*control, *february]
        valid_ids, c_ids, t_ids = {r["row_id"] for r in valid_rows}, {r["row_id"] for r in control}, {r["row_id"] for r in treatment}
        if valid_ids & c_ids or valid_ids & t_ids or any(r["source_block"] == MARCH for r in valid_rows) or any(r["source_block"].startswith("FEBRUARY") for r in valid_rows):
            raise Stop(f"LEAKAGE_CHECK_FAILED:{fold}")
        if not all(r["source_block"] == MARCH for r in control if r["source_block"] == MARCH) or len([r for r in treatment if r["source_block"].startswith("FEBRUARY")]) != len(february):
            raise Stop(f"TRAIN_COMPOSITION_INVALID:{fold}")
        cp, cs, cm = fit_predict(control, valid_rows, "CONTROL", fold)
        tp, ts, tm = fit_predict(treatment, valid_rows, "TREATMENT", fold)
        for arm, scaler, model in (("control", cs, cm), ("treatment", ts, tm)):
            mp = OUT / "cv_experiment_only_models" / f"{arm}_{fold.replace(' ', '_').replace('(', '').replace(')', '')}.joblib"
            sp = OUT / "cv_experiment_only_models" / f"{arm}_{fold.replace(' ', '_').replace('(', '').replace(')', '')}_scaler.joblib"
            joblib.dump(model, mp); joblib.dump(scaler, sp)
            models.append({"fold": fold, "arm": arm, "path": str(mp.relative_to(ROOT)), "sha256": sha(mp), "status": LABEL})
            scalers.append({"fold": fold, "arm": arm, "path": str(sp.relative_to(ROOT)), "sha256": sha(sp), "status": LABEL})
        # Primary BUY evaluation uses the complete frozen Top5.  Invalid-result
        # runners are still scored and may be selected, but are never replaced.
        fold_candidates = [candidate for candidates in all_candidates.values() for candidate in candidates if candidate["source_block"] == fold]
        cp_all = cm.predict_proba(cs.transform(np.asarray([feature_vector(r) for r in fold_candidates], dtype=float)))[:, 1]
        tp_all = tm.predict_proba(ts.transform(np.asarray([feature_vector(r) for r in fold_candidates], dtype=float)))[:, 1]
        probs_c = {r["row_id"]: float(p) for r, p in zip(fold_candidates, cp_all)}; probs_t = {r["row_id"]: float(p) for r, p in zip(fold_candidates, tp_all)}
        for r in valid_rows:
            validation_predictions.append({"fold": fold, "row_id": r["row_id"], "race_id": r["race_id"], "actual_top3": int(r["actual_top3"]), "control_probability": probs_c[r["row_id"]], "treatment_probability": probs_t[r["row_id"]]})
        eligible, selected_c, selected_t = [], [], []
        for race_id, candidates in all_candidates.items():
            if candidates[0]["source_block"] != fold:
                continue
            buys = [x for x in candidates if x["current_buy"]]
            if candidates[0]["race_state"] == "PLAY_CONVERGED" and buys:
                k = len(buys); eligible.append(race_id)
                selected_c.extend(select_by_probability(candidates, probs_c, k)); selected_t.extend(select_by_probability(candidates, probs_t, k))
        mc, mt = metric(selected_c), metric(selected_t)
        for rid in eligible:
            rc = [r for r in selected_c if r["race_id"] == rid]; rt = [r for r in selected_t if r["race_id"] == rid]
            delta = metric(rt)["top3_hits"] - metric(rc)["top3_hits"]
            race_delta.append({"fold": fold, "race_id": rid, "current_buy_count": len(rc), "control_top3_hits": metric(rc)["top3_hits"], "treatment_top3_hits": metric(rt)["top3_hits"], "race_hit_delta": delta})
        raw = mt["top3_hits"] - mc["top3_hits"]
        lift = mt["buy_top3_rate"] - mc["buy_top3_rate"]
        fold_records[fold] = {"eligible_races": len(eligible), "control": mc, "treatment": mt, "raw_hit_difference": raw, "buy_top3_rate_lift": lift, "direction": "POSITIVE" if raw > 0 else "NEGATIVE" if raw < 0 else "NEUTRAL", "secondary": {"control": secondary([int(r["actual_top3"]) for r in valid_rows], list(cp)), "treatment": secondary([int(r["actual_top3"]) for r in valid_rows], list(tp))}}
        leakage.append({"fold": fold, "status": "PASS", "validation_rows": len(valid_rows), "control_train_rows": len(control), "treatment_train_rows": len(treatment), "validation_absent_from_control": True, "validation_absent_from_treatment": True, "february_validation_rows": 0, "february_treatment_train_rows": len(february), "march_control_train_rows": blocks[MARCH], "march_treatment_train_rows": blocks[MARCH], "same_race_horse_identity_overlap": 0, "scaler_fit_excludes_validation": True, "outcome_dependent_adjustment": False})

    def pooled(names: list[str]) -> dict:
        records = [fold_records[n] for n in names]
        def total(arm: str, key: str): return sum(r[arm][key] for r in records)
        c = {k: total("control", k) for k in ("nominal_selected_count", "invalid_selected_count", "valid_selected_count", "top3_hits")}; c["buy_top3_rate"] = c["top3_hits"] / c["valid_selected_count"]
        t = {k: total("treatment", k) for k in ("nominal_selected_count", "invalid_selected_count", "valid_selected_count", "top3_hits")}; t["buy_top3_rate"] = t["top3_hits"] / t["valid_selected_count"]
        return {"control": c, "treatment": t, "raw_hit_difference": t["top3_hits"] - c["top3_hits"], "buy_top3_rate_lift": t["buy_top3_rate"] - c["buy_top3_rate"]}
    primary = pooled(list(FOLDS))
    direction = Counter(r["direction"] for r in fold_records.values())
    race_counts = Counter(x["race_hit_delta"] for x in race_delta)
    lofo = []
    for excluded in FOLDS:
        value = pooled([f for f in FOLDS if f != excluded])
        lofo.append({"excluded_fold": excluded, **value, "raw_gate": value["raw_hit_difference"] >= 0, "rate_gate": value["buy_top3_rate_lift"] >= 0})
    all_predictions = validation_predictions
    y = [r["actual_top3"] for r in all_predictions]
    sec = {"pooled": {"control": secondary(y, [r["control_probability"] for r in all_predictions]), "treatment": secondary(y, [r["treatment_probability"] for r in all_predictions])}, "folds": {f: fold_records[f]["secondary"] for f in FOLDS}, "authority": "SECONDARY_ONLY_CANNOT_OVERRIDE_PRIMARY_BUY_GATE"}
    gates = {"pooled_raw_hit_diff_gt_zero": primary["raw_hit_difference"] > 0, "pooled_rate_lift_gt_zero": primary["buy_top3_rate_lift"] > 0, "positive_folds_gt_negative": direction["POSITIVE"] > direction["NEGATIVE"], "all_lofo_raw_nonnegative": all(x["raw_gate"] for x in lofo), "all_lofo_rate_nonnegative": all(x["rate_gate"] for x in lofo)}
    if not gates["pooled_raw_hit_diff_gt_zero"] or not gates["pooled_rate_lift_gt_zero"]:
        verdict = "NOT_SUPPORTED"
    elif all(gates.values()):
        verdict = "SUPPORTED_FOR_NEXT_STAGE"
    else:
        verdict = "INCONCLUSIVE"
    primary.update({"eligible_races": len(race_delta), "treatment_superior_races": sum(x["race_hit_delta"] > 0 for x in race_delta), "equal_races": sum(x["race_hit_delta"] == 0 for x in race_delta), "control_superior_races": sum(x["race_hit_delta"] < 0 for x in race_delta), "full_race_hit_delta_distribution": dict(sorted(race_counts.items()))})
    write("training_population_by_fold.json", {f: {"control_rows": len(existing)-blocks[f], "treatment_rows": len(existing)-blocks[f]+len(february), "validation_rows": blocks[f], "control_positive": sum(int(r["actual_top3"]) for r in existing if r["source_block"] != f), "treatment_positive": sum(int(r["actual_top3"]) for r in existing if r["source_block"] != f)+EXPECTED_FEBRUARY["positive"]} for f in FOLDS})
    write("leakage_checks.json", {"status": "PASS", "checks": leakage})
    write("control_training_manifest.json", {"status": LABEL, "by_fold": {f: {"rows": len(existing)-blocks[f], "excluded_validation_fold": f, "input_dataset_sha256": sha(DATASET)} for f in FOLDS}})
    write("treatment_training_manifest.json", {"status": LABEL, "by_fold": {f: {"rows": len(existing)-blocks[f]+len(february), "included_february_rows": len(february), "input_dataset_sha256": sha(DATASET), "february_sha256": sha(FEBRUARY)} for f in FOLDS}})
    write("fold_model_hashes.json", {"status": LABEL, "models": models}); write("fold_scaler_hashes.json", {"status": LABEL, "scalers": scalers})
    write("validation_prediction_manifest.json", {"status": LABEL, "validation_rows": len(validation_predictions), "rows": validation_predictions, "feature_reconstruction": reconstruction})
    write("buy_evaluation_eligibility.json", {"status": "PASS", "rule": "PLAY_CONVERGED AND Current BUY >= 1", "reconstruction": reconstruction, "eligible_races_by_fold": {f: fold_records[f]["eligible_races"] for f in FOLDS}, "invalid_result_rule": "selected invalid runner excluded from denominator and not replaced"})
    write("fold_buy_metrics.json", fold_records); write("pooled_buy_metrics.json", primary)
    with (OUT / "race_level_delta.csv").open("w", encoding="utf-8", newline="") as dest:
        writer = csv.DictWriter(dest, fieldnames=["fold", "race_id", "current_buy_count", "control_top3_hits", "treatment_top3_hits", "race_hit_delta"]); writer.writeheader(); writer.writerows(race_delta)
    write("race_delta_summary.json", {"eligible_races": len(race_delta), "distribution": dict(sorted(race_counts.items()))})
    write("fold_direction_summary.json", {"positive_folds": direction["POSITIVE"], "neutral_folds": direction["NEUTRAL"], "negative_folds": direction["NEGATIVE"], "by_fold": {f: fold_records[f]["direction"] for f in FOLDS}})
    write("lofo_robustness.json", {"trials": lofo, "all_raw_nonnegative": gates["all_lofo_raw_nonnegative"], "all_rate_nonnegative": gates["all_lofo_rate_nonnegative"]})
    write("secondary_metrics.json", sec)
    write("promotion_gate.json", {"frozen_gates": gates, "verdict": verdict, "rule": "SUPPORTED iff all five gates; NOT_SUPPORTED if pooled raw or rate is nonpositive; otherwise INCONCLUSIVE"})
    write("interpretation_boundary.json", {"allowed_if_supported": "ADDITIONAL_FEBRUARY_TRAINING_DATA_IS_USEFUL_UNDER_THE_FIXED_V4_RECIPE; eligible only for new candidate build and independent validation design", "prohibited_conclusions": ["February unique mechanism", "February subgroup selection", "automatic full 4897-row candidate", "production adoption"]})
    write("february_closure_preservation.json", {"FEBRUARY_FEATURE_HYPOTHESIS_GENERATION": "CLOSED_AFTER_V4_RESELECTION_RELIABILITY_DIAGNOSTIC", "february_role": "TRAIN_INPUT_ONLY"})
    write("formal_track_preservation.json", {"V4_MODEL_V4_FORMAL_PROSPECTIVE_STATUS": "READY_FOR_FIRST_FORMAL_PRE", "V4_MODEL_V3_FORMAL_PROSPECTIVE_SHADOW": "CONTINUE", "CF_EVIDENCE_TRACK": "SEPARATE_AND_CONTINUING"})
    after = {str(p.relative_to(ROOT)): tree_hash(p) for p in protected}; head_after, status_after = git("rev-parse", "HEAD"), git("status", "--porcelain")
    if before != after or head_before != head_after:
        raise Stop("FROZEN_AUTHORITY_MUTATION")
    write("safety.json", {"status": "PASS", "protected_before": before, "protected_after": after, "git_head_before": head_before, "git_head_after": head_after, "git_status_before": status_before, "git_status_after": status_after, "production_change": 0, "model_v4_mutation": 0, "model_v3_mutation": 0, "final_candidate_model": 0, "model_registry_promotion": 0, "buy_engine_change": 0, "decision_engine_change": 0, "feature_change": 0, "threshold_optimization": 0, "february_prediction_rerun": 0, "new_result_acquisition": 0, "february_pre_mutation": 0, "february_post_mutation": 0, "v3_protocol_change": 0, "v4_protocol_change": 0, "cf_protocol_change": 0, "authorized_control_fits": 7, "authorized_treatment_fits": 7, "authorized_scaler_fits": 14})
    report = ["# February Additive Training — 7-fold Control vs Treatment CV", "", f"Final verdict: `{verdict}` (pending independent review).", "", "Temporary models/scalers are explicitly `CV_EXPERIMENT_ONLY`; no final candidate was built or promoted.", "", "## Pooled primary BUY KPI", "", f"Control: {primary['control']['top3_hits']} / {primary['control']['valid_selected_count']} = {rate_pp(primary['control']['buy_top3_rate']):.4f}%", f"Treatment: {primary['treatment']['top3_hits']} / {primary['treatment']['valid_selected_count']} = {rate_pp(primary['treatment']['buy_top3_rate']):.4f}%", f"Difference: {primary['raw_hit_difference']:+d} hits; {rate_pp(primary['buy_top3_rate_lift']):+.4f} percentage points."]
    (OUT / "report.md").write_text("\n".join(report)+"\n", encoding="utf-8")
    write("artifact_hashes.json", {"indexed_artifacts": {str(p.relative_to(OUT)).replace("\\", "/"): sha(p) for p in sorted(x for x in OUT.rglob("*") if x.is_file() and x.name != "artifact_hashes.json")}, "self_hash_excluded": True})
    return OUT


if __name__ == "__main__":
    print(main())
