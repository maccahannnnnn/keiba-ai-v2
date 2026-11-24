"""Non-evidential paired Stage-A experiment: Top5-trained vs Full-field-trained.

This is deliberately isolated from every decision, BUY, shadow, and formal
lane.  Its sole output is held-out candidate-set Top3 capture on the approved
32-date consumed-development scope.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from review.candidate_generation_training_dataset_readiness_v1 import (
    BLOCKS, FEATURES, JAPANESE_VENUE, Stop, feature_values, outcome,
    parse_race_id, prediction_files, result_rows, valid_feature,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "candidate_generation_stage_a_paired_population_v1_retry1"
V4_MODEL = ROOT / "reports" / "ml_v4_buy_selection_model_v4"
READINESS = ROOT / "reports" / "candidate_generation_training_dataset_readiness_v1"
FOLDS = (
    ("FOLD_MARCH_EVAL", ("FEBRUARY_2026_CONSUMED_DEVELOPMENT",), ("MARCH_2026_CONSUMED_DEVELOPMENT",)),
    ("FOLD_MAY_EVAL", ("FEBRUARY_2026_CONSUMED_DEVELOPMENT", "MARCH_2026_CONSUMED_DEVELOPMENT"), ("MAY_2026_CONSUMED_DEVELOPMENT",)),
    ("FOLD_RECENT_PROSPECTIVE_EVAL", ("FEBRUARY_2026_CONSUMED_DEVELOPMENT", "MARCH_2026_CONSUMED_DEVELOPMENT", "MAY_2026_CONSUMED_DEVELOPMENT"), ("PROSPECTIVE_POST_DISCLOSED_20260829_20260906",)),
)
GATES = {"absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name: str, value) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(name: str, fields: list[str], rows: list[dict]) -> None:
    path = OUT / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        # CSVs intentionally expose only the row-level audit fields prescribed
        # for this experiment; the immutable feature payload stays in frozen
        # source artifacts rather than being duplicated here.
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def block_map() -> dict[str, dict]:
    result = {}
    for name, _, dates, root in BLOCKS:
        for date in dates:
            result[date] = {"name": name, "root": root}
    return result


def prerace_races() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Recover race IDs using only frozen prediction artifacts, before labels."""
    dates, races = defaultdict(list), defaultdict(list)
    for name, _, block_dates, root in BLOCKS:
        for date in block_dates:
            for path in prediction_files(date, root):
                payload = json.loads(path.read_text(encoding="utf-8"))
                race_id = payload.get("race_id")
                parsed_date, venue, number = parse_race_id(race_id)
                if parsed_date != date or venue not in JAPANESE_VENUE or number < 1:
                    raise Stop(f"PRE_RACE_IDENTITY_INVALID:{path}")
                dates[name].append(date); races[name].append(race_id)
    return {k: sorted(set(v)) for k, v in dates.items()}, {k: sorted(set(v)) for k, v in races.items()}


def freeze_folds(block_dates: dict[str, list[str]], block_races: dict[str, list[str]]) -> dict:
    folds = []
    seen_dates, seen_races = set(), set()
    for name, train_blocks, eval_blocks in FOLDS:
        train_dates = sorted({d for b in train_blocks for d in block_dates[b]})
        eval_dates = sorted({d for b in eval_blocks for d in block_dates[b]})
        train_races = sorted({r for b in train_blocks for r in block_races[b]})
        eval_races = sorted({r for b in eval_blocks for r in block_races[b]})
        if set(train_dates) & set(eval_dates) or set(train_races) & set(eval_races):
            raise Stop(f"FOLD_TRAIN_EVAL_OVERLAP:{name}")
        if seen_dates & set(eval_dates) or seen_races & set(eval_races):
            raise Stop(f"FOLD_EVAL_DUPLICATION:{name}")
        if max(train_dates) >= min(eval_dates):
            raise Stop(f"TEMPORAL_ORDER_INVALID:{name}")
        seen_dates.update(eval_dates); seen_races.update(eval_races)
        folds.append({"name": name, "train_blocks": list(train_blocks), "eval_blocks": list(eval_blocks), "train_dates": train_dates, "eval_dates": eval_dates, "train_race_ids": train_races, "eval_race_ids": eval_races})
    return {"performance_blind": True, "fold_count": len(folds), "folds": folds,
            "assertions": {"TRAIN_EVAL_DATE_OVERLAP": 0, "TRAIN_EVAL_RACE_OVERLAP": 0,
                           "EVAL_DATE_DUPLICATION_ACROSS_FOLDS": 0, "EVAL_RACE_DUPLICATION_ACROSS_FOLDS": 0,
                           "TEMPORAL_ORDER_VALID": "YES"}}


def build_rows() -> list[dict]:
    """Join the approved frozen PRE features to only the approved result labels."""
    rows, seen = [], set()
    for block, _, dates, root in BLOCKS:
        for date in dates:
            results = result_rows(date)
            for path in prediction_files(date, root):
                payload = json.loads(path.read_text(encoding="utf-8"))
                race_id = payload["race_id"]
                _, venue_key, race_no = parse_race_id(race_id)
                result = results.get((JAPANESE_VENUE[venue_key], race_no))
                if result is None: raise Stop(f"RESULT_RACE_UNMATCHED:{race_id}")
                ranked, trace = payload.get("ranked_results"), payload.get("buy_gate_trace", {})
                horses, race_trace = trace.get("horses"), trace.get("race")
                if not isinstance(ranked, list) or not isinstance(horses, list) or not isinstance(race_trace, dict):
                    raise Stop(f"TRACE_UNAVAILABLE:{race_id}")
                if len(ranked) != int(result[9]) or len(horses) != len(ranked):
                    raise Stop(f"FULL_FIELD_SIZE_MISMATCH:{race_id}")
                trace_by_no = {int(x["horse_number"]): x for x in horses if isinstance(x, dict) and x.get("horse_number") is not None}
                if len(trace_by_no) != len(ranked): raise Stop(f"TRACE_IDENTITY_INVALID:{race_id}")
                state = race_trace.get("shadow_race_state")
                if state not in {"PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"}: raise Stop(f"RACE_STATE_INVALID:{race_id}")
                for horse in ranked:
                    no, rank = int(horse["horse_number"]), horse.get("rank")
                    if not isinstance(rank, int) or rank < 1: raise Stop(f"CURRENT_RANK_UNRECOVERABLE:{race_id}:{no}")
                    key = (date, race_id, no)
                    if key in seen: raise Stop(f"DUPLICATE_ROW:{key}")
                    seen.add(key)
                    values = feature_values(horse, trace_by_no.get(no), state, f"{date}:{race_id}:{no}")
                    if any(not valid_feature(value, feature)[0] for feature, value in values.items()):
                        raise Stop(f"FEATURE_INVALID:{date}:{race_id}:{no}")
                    valid, finish, top3 = outcome(result, no)
                    rows.append({"date": date, "block": block, "race_id": race_id, "venue": JAPANESE_VENUE[venue_key],
                                 "race_number": race_no, "horse_number": no, "horse_name": horse.get("horse_name"),
                                 "current_rank": rank, "current_top5": rank <= 5, "valid_result": valid,
                                 "actual_finish": finish, "actual_top3": int(top3) if valid else None, **values})
    if len(rows) != 8149: raise Stop(f"FULLFIELD_ROW_COUNT_MISMATCH:{len(rows)}")
    valid = [r for r in rows if r["valid_result"]]
    if len(valid) != 8100 or sum(r["actual_top3"] for r in valid) != 1793: raise Stop("FULLFIELD_LABEL_ACCOUNTING_MISMATCH")
    return rows


def vector(row: dict) -> list[float]:
    result = []
    for feature in FEATURES[:-1]:
        value = row[feature]
        result.append(float(value) if feature not in GATES else float(bool(value)))
    result.extend([float(row["race_state"] == "PLAY_UNCONVERGED_4PLUS"), float(row["race_state"] == "SKIP")])
    if len(result) != 21 or any(not math.isfinite(x) for x in result): raise Stop("TRANSFORM_INPUT_INVALID")
    return result


def fit(rows: list[dict], label: str):
    if not rows or not all(r["valid_result"] for r in rows): raise Stop(f"TRAINING_LABEL_BOUNDARY_FAIL:{label}")
    y = np.asarray([r["actual_top3"] for r in rows], dtype=int)
    if not (int(y.sum()) > 0 and int(len(y) - y.sum()) > 0): raise Stop(f"TRAIN_CLASS_DEGENERATE:{label}")
    x = np.asarray([vector(r) for r in rows], dtype=float)
    scaler = StandardScaler()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        z = scaler.fit_transform(x)
        model = LogisticRegression(solver="lbfgs", penalty="l2", C=1.0, class_weight=None, max_iter=100, tol=0.0001).fit(z, y)
    if any(issubclass(w.category, ConvergenceWarning) for w in caught) or not np.isfinite(model.coef_).all():
        raise Stop(f"MODEL_FIT_CONVERGENCE_FAIL:{label}")
    return scaler, model, {"rows": len(rows), "positive": int(y.sum()), "negative": int(len(y)-y.sum())}


def select(rows: list[dict], scaler, model, label: str) -> tuple[list[dict], dict]:
    by_race = defaultdict(list)
    for row in rows:
        prob = float(model.predict_proba(scaler.transform(np.asarray([vector(row)], dtype=float)))[:, 1][0])
        by_race[(row["date"], row["race_id"])].append({**row, "probability": prob})
    selected, ties = [], {"exact_probability_tie_groups": 0, "shadow_ai_rank_usage": 0, "horse_number_usage": 0}
    for key, race_rows in by_race.items():
        if len(race_rows) < 5: raise Stop(f"EXACT5_VOLUME_UNDEFINED:{label}:{key}")
        # A secondary sort can only govern exactly equal floating values.
        ordered = sorted(race_rows, key=lambda r: (-r["probability"], r["shadow_ai_rank"], r["horse_number"]))
        groups = defaultdict(list)
        for row in race_rows: groups[row["probability"]].append(row)
        for group in groups.values():
            if len(group) > 1:
                ties["exact_probability_tie_groups"] += 1
                ranks = {r["shadow_ai_rank"] for r in group}
                if len(ranks) > 1: ties["shadow_ai_rank_usage"] += 1
                else: ties["horse_number_usage"] += 1
        for index, row in enumerate(ordered):
            selected.append({"model": label, "selected": index < 5, "candidate_rank": index + 1, **row})
    return selected, ties


def current_set(rows: list[dict]) -> list[dict]:
    out = []
    by_race = defaultdict(list)
    for row in rows: by_race[(row["date"], row["race_id"])].append(row)
    for key, race_rows in by_race.items():
        chosen = sorted((r for r in race_rows if r["current_top5"]), key=lambda r: r["current_rank"])
        if len(chosen) != 5: raise Stop(f"CURRENT_TOP5_NOT_EXACT5:{key}:{len(chosen)}")
        out += [{"model": "FROZEN_CURRENT_TOP5", "selected": True, "candidate_rank": r["current_rank"], **r} for r in chosen]
    return out


def compare(label: str, left: list[dict], right: list[dict], current: list[dict], evaluation_rows: list[dict]) -> tuple[list[dict], dict]:
    sets = {}
    for name, values in (("left", left), ("right", right), ("current", current)):
        grouped = defaultdict(list)
        for row in values:
            if row["selected"]: grouped[(row["date"], row["race_id"])].append(row)
        if any(len(v) != 5 for v in grouped.values()): raise Stop(f"CANDIDATE_VOLUME_MISMATCH:{name}")
        sets[name] = grouped
    all_by_race = defaultdict(list)
    for row in evaluation_rows:
        all_by_race[(row["date"], row["race_id"])].append(row)
    records, totals = [], Counter()
    for key in sorted(sets["left"]):
        if key not in sets["right"] or key not in sets["current"]: raise Stop("EVAL_UNIVERSE_MISMATCH")
        l, r, c = sets["left"][key], sets["right"][key], sets["current"][key]
        lookup = {row["horse_number"]: row for row in all_by_race[key]}
        valid_top3 = {n for n, row in lookup.items() if row["valid_result"] and row["actual_top3"] == 1}
        ls, rs, cs = {x["horse_number"] for x in l}, {x["horse_number"] for x in r}, {x["horse_number"] for x in c}
        lc, rc, cc = len(valid_top3 & ls), len(valid_top3 & rs), len(valid_top3 & cs)
        rec, disp = len(valid_top3 & rs - ls), len(valid_top3 & ls - rs)
        crec, cdisp = len(valid_top3 & rs - cs), len(valid_top3 & cs - rs)
        if rc - lc != rec - disp or rc - cc != crec - cdisp: raise Stop(f"ACCOUNTING_ASSERTION_FAIL:{key}")
        n, t, k = len(lookup), len(valid_top3), 5
        expected = t * min(k, n) / n
        records.append({"comparison": label, "date": key[0], "race_id": key[1], "valid_field_size": n, "valid_top3_slots": t,
                        "left_capture": lc, "right_capture": rc, "current_capture": cc,
                        "recovered": rec, "displaced": disp, "net_gain": rec-disp,
                        "current_recovered": crec, "current_displaced": cdisp, "current_net_gain": crec-cdisp,
                        "classification": "TREATMENT_SUPERIOR" if rc>lc else "PAIRED_BASELINE_SUPERIOR" if rc<lc else "EQUAL",
                        "operational_classification": "TREATMENT_SUPERIOR_TO_CURRENT" if rc>cc else "CURRENT_SUPERIOR" if rc<cc else "EQUAL_TO_CURRENT",
                        "expected": expected, "oracle": t,
                        "baseline_invalid_selected": sum(not x["valid_result"] for x in l), "treatment_invalid_selected": sum(not x["valid_result"] for x in r), "current_invalid_selected": sum(not x["valid_result"] for x in c)})
        totals.update({"races":1, "top3_slots":t, "baseline_capture":lc, "treatment_capture":rc, "current_capture":cc,
                       "recovered":rec, "displaced":disp, "current_recovered":crec, "current_displaced":cdisp,
                       "baseline_invalid":sum(not x["valid_result"] for x in l), "treatment_invalid":sum(not x["valid_result"] for x in r), "current_invalid":sum(not x["valid_result"] for x in c)})
    if totals["treatment_capture"]-totals["baseline_capture"] != totals["recovered"]-totals["displaced"]: raise Stop("PRIMARY_AGGREGATE_ACCOUNTING_FAIL")
    if totals["treatment_capture"]-totals["current_capture"] != totals["current_recovered"]-totals["current_displaced"]: raise Stop("OPERATIONAL_AGGREGATE_ACCOUNTING_FAIL")
    return records, dict(totals)


def normalized(records: list[dict]) -> dict:
    result = {}
    for name, capture in (("frozen_current", "current_capture"), ("paired_baseline", "left_capture"), ("treatment", "right_capture")):
        observed = sum(r[capture] for r in records); expected = sum(r["expected"] for r in records); oracle = sum(r["oracle"] for r in records)
        result[name] = {"SUM_OBSERVED": observed, "SUM_EXPECTED": expected, "SUM_ORACLE": oracle,
                        "WEIGHTED_NORMALIZED_CAPTURE_POSITION": (observed-expected)/(oracle-expected) if oracle != expected else None}
    result["treatment_minus_baseline"] = result["treatment"]["WEIGHTED_NORMALIZED_CAPTURE_POSITION"] - result["paired_baseline"]["WEIGHTED_NORMALIZED_CAPTURE_POSITION"]
    result["treatment_minus_current"] = result["treatment"]["WEIGHTED_NORMALIZED_CAPTURE_POSITION"] - result["frozen_current"]["WEIGHTED_NORMALIZED_CAPTURE_POSITION"]
    return result


def main() -> None:
    if OUT.exists(): raise Stop(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    readiness = json.loads((READINESS / "training_dataset_readiness_summary.json").read_text(encoding="utf-8"))
    recipe = json.loads((V4_MODEL / "training_recipe.json").read_text(encoding="utf-8"))
    schema = json.loads((V4_MODEL / "feature_schema.json").read_text(encoding="utf-8"))
    transform = json.loads((V4_MODEL / "feature_transform_schema.json").read_text(encoding="utf-8"))
    if readiness["valid_rows"] != 8100 or tuple(schema["semantic_feature_order"]) != FEATURES or transform["transformed_input_count"] != 21: raise Stop("RECIPE_OR_READINESS_AUTHORITY_INVALID")
    if not (recipe["pipeline"] == ["StandardScaler","LogisticRegression"] and recipe["solver"] == "lbfgs" and recipe["penalty"] == "l2" and recipe["C"] == 1.0 and recipe["class_weight"] is None): raise Stop("FROZEN_MODEL_RECIPE_MISMATCH")
    OUT.mkdir(parents=True)
    block_dates, block_races = prerace_races()
    manifest = freeze_folds(block_dates, block_races)
    write_json("performance_blind_fold_manifest.json", manifest)
    manifest_hash = sha(OUT / "performance_blind_fold_manifest.json")
    write_json("fold_freeze_hash.json", {"FOLD_MANIFEST_FROZEN_BEFORE_MODEL_FIT":"YES", "FOLD_MANIFEST_SHA256":manifest_hash})
    rows = build_rows()
    fold_summaries=[]; base_pred=[]; treat_pred=[]; base_exact=[]; treat_exact=[]; curr_exact=[]; all_comparisons=[]; tie=Counter(); all_totals=Counter()
    models = OUT / "models"; models.mkdir()
    for fold in manifest["folds"]:
        train_dates, eval_dates = set(fold["train_dates"]), set(fold["eval_dates"])
        train = [r for r in rows if r["date"] in train_dates and r["valid_result"]]
        baseline_train = [r for r in train if r["current_top5"]]
        treatment_train = train
        evaluation = [r for r in rows if r["date"] in eval_dates]
        if set(r["race_id"] for r in evaluation) != set(fold["eval_race_ids"]): raise Stop(f"EVAL_RACE_SCOPE_MISMATCH:{fold['name']}")
        bs,bm,bstat=fit(baseline_train, fold["name"]+":BASELINE"); ts,tm,tstat=fit(treatment_train, fold["name"]+":TREATMENT")
        joblib.dump(bs, models / f"{fold['name']}_baseline_scaler.joblib"); joblib.dump(bm, models / f"{fold['name']}_baseline_model.joblib")
        joblib.dump(ts, models / f"{fold['name']}_treatment_scaler.joblib"); joblib.dump(tm, models / f"{fold['name']}_treatment_model.joblib")
        bp,bt=select(evaluation,bs,bm,"PAIRED_TOP5_BASELINE_EXACT5"); tp,tt=select(evaluation,ts,tm,"FULL_FIELD_TREATMENT_EXACT5"); cp=current_set(evaluation)
        base_pred += bp; treat_pred += tp; base_exact += [r for r in bp if r["selected"]]; treat_exact += [r for r in tp if r["selected"]]; curr_exact += cp
        comparisons, totals=compare(fold["name"],base_exact[-len(cp):],treat_exact[-len(cp):],cp,evaluation)
        all_comparisons += comparisons; all_totals.update(totals); tie.update({"baseline_tie_groups":bt["exact_probability_tie_groups"],"baseline_shadow":bt["shadow_ai_rank_usage"],"baseline_horse":bt["horse_number_usage"],"treatment_tie_groups":tt["exact_probability_tie_groups"],"treatment_shadow":tt["shadow_ai_rank_usage"],"treatment_horse":tt["horse_number_usage"]})
        fold_summaries.append({"fold":fold["name"],"eval_dates":fold["eval_dates"],"race_count":totals["races"],"baseline_training":bstat,"treatment_training":tstat,"eval_full_field_rows":len(evaluation),**totals})
    if all_totals["treatment_capture"]-all_totals["baseline_capture"] != all_totals["recovered"]-all_totals["displaced"]: raise Stop("PRIMARY_TOTAL_FAIL")
    if all_totals["treatment_capture"]-all_totals["current_capture"] != all_totals["current_recovered"]-all_totals["current_displaced"]: raise Stop("OPERATIONAL_TOTAL_FAIL")
    denom=all_totals["top3_slots"]
    primary={"races":all_totals["races"],"candidate_selections":all_totals["races"]*5,"valid_actual_top3_slots":denom,
             "PAIRED_BASELINE_CAPTURE":all_totals["baseline_capture"],"FULL_FIELD_TREATMENT_CAPTURE":all_totals["treatment_capture"],
             "baseline_capture_rate":all_totals["baseline_capture"]/denom,"treatment_capture_rate":all_totals["treatment_capture"]/denom,
             "PAIRED_TOP3_RECOVERED":all_totals["recovered"],"PAIRED_TOP3_DISPLACED":all_totals["displaced"],"PAIRED_NET_TOP3_CAPTURE_GAIN":all_totals["recovered"]-all_totals["displaced"]}
    primary["PAIRED_RAW_CAPTURE_DIFFERENCE"]=primary["FULL_FIELD_TREATMENT_CAPTURE"]-primary["PAIRED_BASELINE_CAPTURE"]; primary["PAIRED_CAPTURE_RATE_DIFFERENCE"]=primary["treatment_capture_rate"]-primary["baseline_capture_rate"]
    primary["TRAINING_POPULATION_EFFECT"]="POSITIVE_DIRECTIONAL" if primary["PAIRED_NET_TOP3_CAPTURE_GAIN"]>0 else "NEGATIVE_DIRECTIONAL" if primary["PAIRED_NET_TOP3_CAPTURE_GAIN"]<0 else "NO_NET_GAIN"
    operational={"FROZEN_CURRENT_CAPTURE":all_totals["current_capture"],"FULL_FIELD_TREATMENT_CAPTURE":all_totals["treatment_capture"],"current_capture_rate":all_totals["current_capture"]/denom,"treatment_capture_rate":all_totals["treatment_capture"]/denom,"CURRENT_BENCHMARK_TOP3_RECOVERED":all_totals["current_recovered"],"CURRENT_BENCHMARK_TOP3_DISPLACED":all_totals["current_displaced"],"CURRENT_BENCHMARK_NET_TOP3_CAPTURE_GAIN":all_totals["current_recovered"]-all_totals["current_displaced"]}
    operational["CURRENT_BENCHMARK_RAW_DIFFERENCE"]=operational["FULL_FIELD_TREATMENT_CAPTURE"]-operational["FROZEN_CURRENT_CAPTURE"]; operational["CURRENT_BENCHMARK_RATE_DIFFERENCE"]=operational["treatment_capture_rate"]-operational["current_capture_rate"]; operational["OPERATIONAL_BENCHMARK_IS_NOT_PRIMARY_CAUSAL_COMPARISON"]="YES"
    # Keep output compact but fully row-auditable.
    fields=["model","selected","candidate_rank","date","block","race_id","venue","race_number","horse_number","horse_name","current_rank","current_top5","valid_result","actual_finish","actual_top3","probability","shadow_ai_rank"]
    pred_fields=fields; exact_fields=[x for x in fields if x != "probability"]
    write_csv("paired_baseline_predictions.csv",pred_fields,base_pred); write_csv("treatment_predictions.csv",pred_fields,treat_pred)
    write_csv("paired_baseline_exact5.csv",exact_fields,base_exact); write_csv("treatment_exact5.csv",exact_fields,treat_exact); write_csv("frozen_current_top5.csv",exact_fields,curr_exact)
    compare_fields=list(all_comparisons[0]); write_csv("race_level_primary_comparison.csv",compare_fields,all_comparisons); write_csv("race_level_operational_comparison.csv",compare_fields,all_comparisons)
    date_rows=[]
    for date in sorted({r["date"] for r in all_comparisons}):
        group=[r for r in all_comparisons if r["date"]==date]; date_rows.append({"date":date,"races":len(group),"current_capture":sum(r["current_capture"] for r in group),"baseline_capture":sum(r["left_capture"] for r in group),"treatment_capture":sum(r["right_capture"] for r in group),"treatment_vs_baseline_net":sum(r["net_gain"] for r in group),"treatment_vs_current_net":sum(r["current_net_gain"] for r in group)})
    write_json("protocol.json",{"experiment":"CANDIDATE_GENERATION_STAGE_A_PAIRED_POPULATION_V1","evidence_role":"NON_EVIDENTIAL_DEVELOPMENT_EXPERIMENT","stage_a_only":True,"primary_comparator":"PAIRED_TOP5_BASELINE_EXACT5 vs FULL_FIELD_TREATMENT_EXACT5","operational_benchmark":"FROZEN_CURRENT_TOP5 vs FULL_FIELD_TREATMENT_EXACT5"})
    write_json("scope_reconciliation.json",{"previous_stop":"CANDIDATE_GENERATION_STAGE_A_FULL_FIELD_V1: DATASET_SCOPE_MISMATCH","new_common_scope":"32 dates / 597 races","frozen_v4_role":"RECIPE_AUTHORITY_ONLY","ONLY_MAJOR_DIFFERENCE_IS_TRAINING_POPULATION":"YES"})
    write_json("data_scope.json",{"dates":32,"races":597,"full_field_rows":8149,"valid_label_rows":8100,"invalid_rows":49,"positives":1793,"negatives":6307,"april_access":0,"untouched_holdout_access":0,"future_result_access":0})
    write_json("feature_recipe.json",{"semantic_features":list(FEATURES),"semantic_count":20,"transformed_count":21,"same_feature_recipe":True}); write_json("model_recipe.json",{"pipeline":recipe["pipeline"],"solver":recipe["solver"],"penalty":recipe["penalty"],"C":recipe["C"],"class_weight":recipe["class_weight"],"max_iter":100,"tol":0.0001,"same_model_recipe":True})
    write_json("baseline_training_population_audit.json",{"population":"CURRENT_TOP5_ONLY","folds":[{"fold":x["fold"],**x["baseline_training"]} for x in fold_summaries]}); write_json("treatment_training_population_audit.json",{"population":"FULL_FIELD","folds":[{"fold":x["fold"],**x["treatment_training"]} for x in fold_summaries]})
    write_json("fold_training_summary.json",fold_summaries); write_json("fit_convergence_audit.json",{"MODEL_FIT_CONVERGENCE":"PASS","baseline_fit_count":3,"treatment_fit_count":3,"FINAL_ALL_DATA_MODEL_FIT":0})
    write_json("stage_a_primary_aggregate.json",primary); write_json("stage_a_operational_aggregate.json",operational); write_json("stage_a_fold_summary.json",fold_summaries); write_json("stage_a_date_summary.json",date_rows); write_json("stage_a_normalized_capture.json",normalized(all_comparisons))
    write_json("tie_break_audit.json",{"TIE_BREAK_TRIGGER_COUNT_BASELINE":tie["baseline_tie_groups"],"TIE_BREAK_TRIGGER_COUNT_TREATMENT":tie["treatment_tie_groups"],"baseline_shadow_ai_rank_usage":tie["baseline_shadow"],"baseline_horse_number_usage":tie["baseline_horse"],"treatment_shadow_ai_rank_usage":tie["treatment_shadow"],"treatment_horse_number_usage":tie["treatment_horse"]})
    write_json("invalid_selection_audit.json",{"BASELINE_INVALID_SELECTED_COUNT":all_totals["baseline_invalid"],"TREATMENT_INVALID_SELECTED_COUNT":all_totals["treatment_invalid"],"CURRENT_TOP5_INVALID_SELECTED_COUNT":all_totals["current_invalid"],"replacement_after_result":0})
    write_json("assertion_audit.json",{"PERFORMANCE_BLIND_FOLD_FREEZE":"PASS","SAME_EVAL_UNIVERSE":"YES","SAME_FEATURE_RECIPE":"YES","SAME_MODEL_RECIPE":"YES","SAME_LABEL_POLICY":"YES","SAME_TIE_BREAK":"YES","ONLY_MAJOR_DIFFERENCE_IS_TRAINING_POPULATION":"YES","primary_accounting":"PASS","operational_accounting":"PASS","exact5_volume":"PASS"})
    write_json("ledger_entry_proposal.json",{"experiment":"CANDIDATE_GENERATION_STAGE_A_PAIRED_POPULATION_V1","mechanism_family":"TRAINING_POPULATION_AXIS","result":primary["TRAINING_POPULATION_EFFECT"],"relationship_to_previous_stop":"scope-reconciled successor; prior STOP was pre-fit only","evidence_role":"NON_EVIDENTIAL_DEVELOPMENT_EXPERIMENT","stable_id_assigned":False})
    write_json("safety.json",{"ENGINE_CHANGE":0,"RACE_DECISION_ENGINE_CHANGE":0,"CURRENT_BUY_EXECUTION":0,"BUY_TOP3_RATE_EVALUATION":0,"V4_FORMAL_RERUN":0,"CF_EXECUTION":0,"FEATURE_CHANGE":0,"NEW_FEATURE_SEARCH":0,"MODEL_FAMILY_CHANGE":0,"HYPERPARAMETER_CHANGE":0,"CLASS_WEIGHT_CHANGE":0,"THRESHOLD_SEARCH":0,"OUTPUT_VOLUME_CHANGE":0,"PRODUCTION_CHANGE":0,"PRODUCTION_MODEL_REGISTRATION":0,"FORMAL_PROTOCOL_CHANGE":0,"SOURCE_DATA_CHANGE":0,"APRIL_ACCESS":0,"UNTOUCHED_HOLDOUT_ACCESS":0,"FUTURE_RESULT_ACCESS":0,"FINAL_ALL_DATA_MODEL_FIT":0,"ARTIFACT_HASH_VALIDATION":"PENDING"})
    (OUT/"report.md").write_text(f"# Candidate Generation Stage A\n# Paired Training Population Experiment v1 — 完了\n\n`CANDIDATE_GENERATION_STAGE_A_PAIRED_POPULATION_V1 = COMPLETE`\n\nPrimary (paired): baseline capture {primary['PAIRED_BASELINE_CAPTURE']} / treatment capture {primary['FULL_FIELD_TREATMENT_CAPTURE']} / net {primary['PAIRED_NET_TOP3_CAPTURE_GAIN']} ({primary['TRAINING_POPULATION_EFFECT']}).\n\nStage A only; no BUY, downstream Engine, formal V4/CF rerun, or Production connection was used.\n",encoding="utf-8")
    index={str(p.relative_to(OUT)).replace("\\\\","/"):{"sha256":sha(p),"size":p.stat().st_size} for p in sorted(OUT.rglob("*")) if p.is_file() and p.name!="artifact_hash_index.json"}
    write_json("artifact_hash_index.json",{"indexed_artifacts":index,"self_hash_excluded":True})
    print("CANDIDATE_GENERATION_STAGE_A_PAIRED_POPULATION_V1=COMPLETE")

if __name__ == "__main__": main()
