"""Build Dataset v4 from frozen Dataset v3 plus March Top5-valid TRAIN rows only.

No model/scaler fitting, inference, counterfactual execution, or prospective
result access occurs in this dataset-only build.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.ml_v4_buy_selection_dataset_build_v1 import category, csv_write
from review.ml_v4_buy_selection_dataset_inventory_v2 import (
    FEATURES as BASE_FEATURES, Stop, formal_buy_set, outcome, result_for_race,
    result_rows, sha, stored,
)

PARENT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v3"
MARCH = ROOT / "reports" / "march_2026_historical_holdout_pre"
OUT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v4"
MARCH_DATES = ("20260301", "20260307", "20260308", "20260314", "20260315", "20260321", "20260322", "20260328", "20260329")
GAP = "adjusted_score_gap_to_top"
FEATURES = (*BASE_FEATURES, GAP)
EXPECTED = {"rows": 4100, "positive": 1389, "negative": 2711, "march_rows": 860, "march_positive": 281, "march_negative": 579, "march_top5_before_valid": 865, "march_invalid_excluded": 5, "categories": {"TRUE_BUY_SUCCESS": 208, "BUY_FALSE_POSITIVE": 406, "TOP5_NONBUY_MISSED": 1181, "TRUE_BUY_ABSTENTION": 2305}, "gap_min": -122.0, "gap_max": 0.0, "gap_zero_rows": 174, "tie_max_races": 1}


def jload(path: Path) -> object:
    if not path.is_file():
        raise Stop(f"REQUIRED_ARTIFACT_MISSING:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def tree_hash(root: Path) -> str:
    if not root.exists():
        return "NOT_FOUND"
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8")); digest.update(b"\0"); digest.update(sha(path).encode("ascii")); digest.update(b"\n")
    return digest.hexdigest()


def git_value(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def parent_rows() -> tuple[list[dict[str, str]], list[str], dict]:
    manifest = jload(PARENT / "dataset_manifest.json")
    expected_sha = "e30ac0412e62e502d3671f1222306cc8fc79853125a86cd0fd996fefa64187bc"
    actual_sha = sha(PARENT / "dataset.csv")
    if actual_sha != expected_sha or manifest.get("dataset_sha256") != expected_sha:
        raise Stop(f"PARENT_V3_SHA_MISMATCH:{actual_sha}")
    validation = jload(PARENT / "validation.json")
    if validation.get("status") != "PASS" or validation.get("rows") != 3240 or validation.get("semantic_feature_count") != 21 or validation.get("transformed_input_count") != 22:
        raise Stop("PARENT_V3_AUTHORITY_INVALID")
    with (PARENT / "dataset.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream); rows = list(reader); fields = list(reader.fieldnames or [])
    if len(rows) != 3240 or len({r["row_id"] for r in rows}) != len(rows) or set(FEATURES) - set(fields):
        raise Stop("PARENT_V3_STRUCTURE_INVALID")
    return rows, fields, {"dataset_sha256": actual_sha, "manifest_sha256": sha(PARENT / "dataset_manifest.json"), "validation_sha256": sha(PARENT / "validation.json"), "dataset_version": manifest.get("dataset_version")}


def top5_and_buy(payload: dict, path: Path) -> tuple[list[dict], set[int], dict]:
    ranked = payload.get("ranked_results")
    top5_payload = payload.get("top5")
    if not isinstance(ranked, list) or not isinstance(top5_payload, list):
        raise Stop(f"MARCH_TOP5_STRUCTURE_INVALID:{path}")
    ranked_top5 = [x for x in ranked if x.get("rank") is not None and int(x["rank"]) <= 5]
    ranked_numbers = {int(x["horse_number"]) for x in ranked_top5}
    payload_numbers = {int(x["horse_number"]) for x in top5_payload}
    if len(ranked_numbers) != len(ranked_top5) or len(payload_numbers) != len(top5_payload) or ranked_numbers != payload_numbers:
        raise Stop(f"MARCH_TOP5_SEMANTICS_MISMATCH:{path}")
    buys, buy_record = formal_buy_set(payload, path)
    return ranked_top5, buys, buy_record


def primary_feature_values(horse: dict, trace: dict | None, race_trace: dict, gap: float) -> dict:
    values = {name: stored(horse, trace, name, race_trace) for name in BASE_FEATURES}
    values[GAP] = gap
    return values


def reference_feature_values(horse: dict, trace: dict | None, race_trace: dict, gap: float) -> dict:
    """Separate field-by-field reconstruction for the March reference rebuild."""
    trace = trace or {}
    evaluator = trace.get("evaluator_score_snapshot", {})
    values = {
        "shadow_ai_rank": horse.get("shadow_ai_rank", trace.get("shadow_ai_rank")),
        "decision_score": horse.get("decision_score", trace.get("decision_score")),
        "final_score": horse.get("final_score", trace.get("final_score")),
        "adjusted_score": horse.get("adjusted_score", trace.get("adjusted_score")),
        "absolute_quality_pass": horse.get("absolute_quality_pass", trace.get("absolute_quality_pass")),
        "relative_advantage_pass": horse.get("relative_advantage_pass", trace.get("relative_advantage_pass")),
        "effective_reliability_pass": horse.get("effective_reliability_pass", trace.get("effective_reliability_pass")),
        "risk_guard_pass": horse.get("risk_guard_pass", trace.get("risk_guard_pass")),
        "consensus_positive_count": horse.get("consensus_positive_count", trace.get("consensus_positive_count")),
        "consensus_negative_count": horse.get("consensus_negative_count", trace.get("consensus_negative_count")),
        "risk_count": horse.get("risk_count", trace.get("risk_count")),
        "conflict_count": horse.get("conflict_count", trace.get("conflict_count")),
        "race_state": race_trace.get("shadow_race_state"),
        "Ability": evaluator.get("Ability"), "PastPerformance": evaluator.get("PastPerformance"), "Distance": evaluator.get("Distance"),
        "CourseShape": evaluator.get("CourseShape"), "LapSuitability": evaluator.get("LapSuitability"), "RaceShape": evaluator.get("RaceShape"), "PaceStyle": evaluator.get("PaceStyle"), GAP: gap,
    }
    return values


def march_rows(fields: list[str], existing_rows: set[str], existing_races: set[str]) -> tuple[list[dict], dict, list[dict]]:
    rows, reference, per_date, top5_before, invalid, gap_values, tie_max = [], [], [], 0, 0, [], 0
    for date in MARCH_DATES:
        paths = sorted((MARCH / "current_ai" / date).glob("race_*_prediction.json"))
        if not paths:
            raise Stop(f"MARCH_PREDICTION_SOURCE_MISSING:{date}")
        index = result_rows(date)
        result_path = ROOT / "data" / "raw" / "target" / "daily_result_list" / f"馬番順着順_{date}.csv"
        date_top5 = date_invalid = 0
        for path in paths:
            payload = jload(path); race_id = payload.get("race_id")
            if not isinstance(race_id, str) or race_id.split("_")[1] != date or race_id in existing_races:
                raise Stop(f"MARCH_RACE_ID_INVALID_OR_OVERLAP:{path}")
            existing_races.add(race_id)
            ranked_top5, buys, buy_record = top5_and_buy(payload, path)
            top5_before += len(ranked_top5); date_top5 += len(ranked_top5)
            scores = [float(x["adjusted_score"]) for x in ranked_top5]
            maximum = max(scores)
            if sum(x == maximum for x in scores) > 1: tie_max += 1
            traces = {int(x["horse_number"]): x for x in payload.get("buy_gate_trace", {}).get("horses", [])}
            race_trace = payload.get("buy_gate_trace", {}).get("race", {})
            target_key, result_row = result_for_race(race_id, index)
            for horse in ranked_top5:
                number = int(horse["horse_number"]); gap = float(horse["adjusted_score"]) - maximum; gap_values.append(gap)
                label = outcome(result_row, number)
                if not label["valid_result"]:
                    invalid += 1; date_invalid += 1; continue
                row_id = f"{date}:{race_id}:{number}"
                if row_id in existing_rows: raise Stop(f"MARCH_ROW_ID_OVERLAP:{row_id}")
                existing_rows.add(row_id)
                values = primary_feature_values(horse, traces.get(number), race_trace, gap)
                ref_values = reference_feature_values(horse, traces.get(number), race_trace, gap)
                missing = [name for name, value in values.items() if value is None]
                if missing: raise Stop(f"MARCH_FEATURE_MISSING:{row_id}:{','.join(missing)}")
                current_buy = number in buys
                record = {"row_id": row_id, "date": date, "race_id": race_id, "target_race_key": target_key, "horse_number": number, "horse_name": horse.get("horse_name"), **values, "current_buy": current_buy, "current_top5": True, "selection_error_category": category(current_buy, bool(label["actual_top3"])), "actual_top3": int(bool(label["actual_top3"])), "actual_finish": label.get("actual_finish"), "valid_result": True, "source_prediction_artifact_path": str(path.relative_to(ROOT)), "source_prediction_artifact_sha256": sha(path), "source_result_artifact_path": str(result_path.relative_to(ROOT)), "source_result_artifact_sha256": sha(result_path), "source_block": "MARCH_2026_HISTORICAL_HOLDOUT_ADDITIVE_TRAIN_REUSE_V4", "evidence_role_note": "FROZEN_PRE_FEATURES_POST_RESULT_LABEL_ONLY", "dataset_version": "ML_V4_TRAIN_DATASET_V4", "split_role": "TRAIN"}
                if set(record) != set(fields): raise Stop(f"MARCH_SCHEMA_MISMATCH:{row_id}")
                rows.append(record); reference.append({"row_id": row_id, "target": record["actual_top3"], "category": record["selection_error_category"], "features": ref_values})
        per_date.append({"date": date, "race_count": len(paths), "top5_before_valid": date_top5, "invalid_result_excluded": date_invalid, "valid_additive_rows": date_top5-date_invalid, "result_source_path": str(result_path.relative_to(ROOT)), "result_source_sha256": sha(result_path)})
    raw_min, raw_max = min(gap_values), max(gap_values)
    stats = {"races_processed": sum(x["race_count"] for x in per_date), "top5_before_valid": top5_before, "invalid_result_excluded": invalid, "valid_additive_rows": len(rows), "positive": sum(x["actual_top3"] for x in rows), "negative": len(rows)-sum(x["actual_top3"] for x in rows), "adjusted_score_missing": 0, "feature_missing": 0, "relative_gap": {"min": round(raw_min, 10), "max": round(raw_max, 10), "raw_min": raw_min, "raw_max": raw_max, "gap_zero_rows": sum(x == 0 for x in gap_values), "tie_max_races": tie_max}}
    return rows, {"dates": per_date, **stats}, reference


def assert_equal(name: str, actual, expected) -> None:
    if isinstance(actual, float) and isinstance(expected, float):
        if abs(actual - expected) <= 1e-9:
            return
    if actual != expected: raise Stop(f"ASSERTION_FAILED:{name}:{actual}:{expected}")


def main() -> Path:
    if OUT.exists(): raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    protected = [PARENT, ROOT / "reports" / "ml_v4_buy_selection_dataset_v2", ROOT / "reports" / "ml_v4_buy_selection_model_v3", ROOT / "reports" / "v4_model_v3_formal_prospective", ROOT / "reports" / "prospective_prediction_20260830_v1", ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"]
    before = {str(p.relative_to(ROOT)): tree_hash(p) for p in protected}
    head_before, status_before = git_value("rev-parse", "HEAD"), git_value("status", "--porcelain")
    OUT.mkdir(parents=True)
    parent, fields, parent_authority = parent_rows()
    parent_ids, parent_races, parent_dates = {x["row_id"] for x in parent}, {x["race_id"] for x in parent}, {x["date"] for x in parent}
    inherited = [{**row, "dataset_version": "ML_V4_TRAIN_DATASET_V4"} for row in parent]
    added, march, reference = march_rows(fields, set(parent_ids), set(parent_races))
    for key in ("races_processed", "top5_before_valid", "invalid_result_excluded", "valid_additive_rows", "positive", "negative"):
        assert_equal(f"march_{key}", march[key], {"races_processed": 173, "top5_before_valid": 865, "invalid_result_excluded": 5, "valid_additive_rows": 860, "positive": 281, "negative": 579}[key])
    for key in ("min", "max", "gap_zero_rows", "tie_max_races"): assert_equal(f"relative_gap_{key}", march["relative_gap"][key], EXPECTED[{"min":"gap_min","max":"gap_max","gap_zero_rows":"gap_zero_rows","tie_max_races":"tie_max_races"}[key]])
    rows = sorted([*inherited, *added], key=lambda x: (x["date"], x["race_id"], int(x["horse_number"])))
    categories = Counter(x["selection_error_category"] for x in rows); positive = sum(int(x["actual_top3"]) for x in rows)
    for key, actual in (("rows",len(rows)),("positive",positive),("negative",len(rows)-positive)): assert_equal(key,actual,EXPECTED[key])
    assert_equal("categories", dict(categories), EXPECTED["categories"])
    # Parent identity/content may differ only by the explicitly allowed dataset_version.
    v4_parent = {x["row_id"]: x for x in rows if x["row_id"] in parent_ids}
    for old in parent:
        candidate = dict(v4_parent[old["row_id"]]); candidate["dataset_version"] = old["dataset_version"]
        if candidate != old: raise Stop(f"PARENT_ZERO_DELTA_FAILURE:{old['row_id']}")
    if parent_dates & set(MARCH_DATES) or len({x["row_id"] for x in rows}) != len(rows) or len({x["race_id"] for x in added} & parent_races): raise Stop("EXCLUSIVITY_FAILURE")
    ref_by_id = {x["row_id"]: x for x in reference}; primary_added = {x["row_id"]: x for x in added}
    mismatch = [rid for rid, ref in ref_by_id.items() if rid not in primary_added or ref["target"] != primary_added[rid]["actual_top3"] or ref["category"] != primary_added[rid]["selection_error_category"] or any(ref["features"][k] != primary_added[rid][k] for k in FEATURES)]
    if mismatch or len(ref_by_id) != 860: raise Stop(f"MARCH_REFERENCE_REBUILD_MISMATCH:{len(mismatch)}")
    feature_rows = [{"row_id": x["row_id"], **{key:x[key] for key in FEATURES}} for x in rows]; targets = [{"row_id":x["row_id"],"actual_top3":x["actual_top3"]} for x in rows]
    csv_write(OUT / "dataset.csv", fields, rows); csv_write(OUT / "feature_matrix.csv", ["row_id",*FEATURES], feature_rows); csv_write(OUT / "target.csv", ["row_id","actual_top3"], targets)
    write("feature_schema.json", {"dataset_version":"ML_V4_TRAIN_DATASET_V4","parent":"ML_V4_TRAIN_DATASET_V3","semantic_feature_order":list(FEATURES),"semantic_feature_count":21,"parent_schema_sha256":sha(PARENT/"feature_schema.json"),"unchanged":True})
    write("feature_transform_schema.json", {"dataset_version":"ML_V4_TRAIN_DATASET_V4","parent_sha256":sha(PARENT/"feature_transform_schema.json"),"semantic_feature_count":21,"transformed_input_count":22,"transform_semantics":"UNCHANGED_FROM_V3","model_training":"NOT_EXECUTED"})
    write("population_schema.json", {"parent_population":"ML_V4_TRAIN_DATASET_V3","additive_population":"173 March races, ranked_results rank<=5 AND valid_result=True","source_block":"MARCH_2026_HISTORICAL_HOLDOUT_ADDITIVE_TRAIN_REUSE_V4","forbidden_filters":["BUY-positive-only","performance-based","replacement_depth","buy_volume","concentration"],"resampling":"PROHIBITED"})
    write("source_date_inventory.json", {"parent_date_count":len(parent_dates),"parent_dates":sorted(parent_dates),"march_date_count":9,"march_dates":list(MARCH_DATES),"dataset_v4_date_count":len({x['date'] for x in rows}),"date_overlap":[],"march":march})
    write("lineage.json", {"parent":"V4 BUY Selection Dataset v3","relationship":"ADDITIVE_TRAIN_REUSE_PLUS_EXISTING_FEATURE_SET","existing_v3_rows":"UNCHANGED_EXCEPT_DATASET_VERSION","march_model_v3_role":"CONSUMED_TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V3","march_model_v4_plus_role":"ADDITIVE_TRAIN_REUSE_FOR_V4_MODEL_V4","historical_gate":"PASS_UNCHANGED","oos_evidence_reinterpretation":"PROHIBITED","reuse_as_independent_evaluation_for_v4_plus":"PROHIBITED"})
    validation = {"status":"PASS","dataset_rows":len(rows),"positive":positive,"negative":len(rows)-positive,**dict(categories),"march_rows":len(added),"march_positive":march["positive"],"march_negative":march["negative"],"march_top5_before_valid":march["top5_before_valid"],"march_invalid_excluded":march["invalid_result_excluded"],"feature_missing":0,"adjusted_score_missing":0,"top5_semantics_mismatch":0,"buy_authority_mismatch":0,"date_overlap":0,"race_id_overlap":0,"row_id_overlap":0,"parent_zero_delta":"PASS","march_reference_rebuild":"PASS","relative_gap":march["relative_gap"],"model_fit_count":0,"scaler_fit_count":0,"prediction_execution_count":0,"august_30_result_access_count":0,"concentration_sampling_use_count":0}
    write("validation.json",validation)
    write("dataset_manifest.json", {"dataset_version":"ML_V4_TRAIN_DATASET_V4","status":"FROZEN_CANDIDATE_PENDING_INDEPENDENT_REVIEW","dataset_sha256":sha(OUT/"dataset.csv"),"row_count":len(rows),"semantic_feature_count":21,"transformed_input_count":22,"parent":parent_authority,"lineage_sha256":sha(OUT/"lineage.json"),"validation_sha256":sha(OUT/"validation.json")})
    after = {str(p.relative_to(ROOT)): tree_hash(p) for p in protected}; head_after,status_after=git_value("rev-parse","HEAD"),git_value("status","--porcelain")
    if before != after or head_before != head_after: raise Stop("FROZEN_AUTHORITY_MUTATION")
    write("safety.json", {"status":"PASS","frozen_authority_before":before,"frozen_authority_after":after,"git_head_before":head_before,"git_head_after":head_after,"git_status_before":status_before,"git_status_after":status_after,"production_changes":0,"model_v3_changes":0,"cf_changes":0,"formal_prospective_changes":0,"august_30_pre_changes":0,"august_30_result_access_count":0,"model_fit_count":0,"scaler_fit_count":0})
    (OUT/"report.md").write_text("# V4 BUY Selection Dataset v4\n\nDataset v3の3,240行を内容不変（`dataset_version`のみv4）で継承し、March 2026の173レースからTop5かつvalid_resultの860行をadditive TRAIN reuseしました。Model fit、scaler fit、8/30 Result access、Concentrationに基づくsamplingは0です。\n",encoding="utf-8")
    write("artifact_hashes.json", {"indexed_artifacts":{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!="artifact_hashes.json"},"self_hash_excluded":True})
    return OUT


if __name__ == "__main__":
    print(main())
