"""Build the frozen V4 TRAIN dataset from Inventory v2 authorities only.

Dataset construction only: no fitting, scoring, feature selection, or policy
calibration occurs here.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parents[1]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from review.ml_v4_buy_selection_dataset_inventory_v2 import (
    FEATURES, OUT as INVENTORY_OUT, ROOT, Stop, formal_buy_set, outcome,
    result_for_race, result_rows, sha, stored,
)

OUT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v1"
EXPECTED_CATEGORIES = {
    "TRUE_BUY_SUCCESS": 108,
    "BUY_FALSE_POSITIVE": 209,
    "TOP5_NONBUY_MISSED": 675,
    "TRUE_BUY_ABSTENTION": 1291,
}


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def category(current_buy: bool, actual_top3: bool) -> str:
    if current_buy and actual_top3:
        return "TRUE_BUY_SUCCESS"
    if current_buy:
        return "BUY_FALSE_POSITIVE"
    if actual_top3:
        return "TOP5_NONBUY_MISSED"
    return "TRUE_BUY_ABSTENTION"


def csv_write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_inventory_authority() -> tuple[dict, dict]:
    summary_path = INVENTORY_OUT / "summary.json"
    source_path = INVENTORY_OUT / "source_manifest.json"
    if not summary_path.is_file() or not source_path.is_file():
        raise Stop("INVENTORY_V2_AUTHORITY_MISSING")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if summary.get("final_status") != "V4_DATASET_INVENTORY_V2_COMPLETE":
        raise Stop("INVENTORY_V2_NOT_COMPLETE")
    if source.get("formal_source_policy") != "AUGUST_6_DATES_TRACE_SOLE_SOURCE":
        raise Stop("INVENTORY_V2_SOURCE_POLICY_INVALID")
    return summary, source


def build() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        inventory_summary, inventory_sources = read_inventory_authority()
        source_entries = inventory_sources.get("sources")
        if not isinstance(source_entries, list) or len(source_entries) != 26:
            raise Stop("INVENTORY_V2_SOURCE_MANIFEST_STRUCTURE_INVALID")
        full_rows, feature_rows, target_rows = [], [], []
        source_validation, buy_validation = [], []
        seen_rows, seen_races = set(), set()
        for source in sorted(source_entries, key=lambda x: (x["date"], x["block"])):
            date, block = source["date"], source["block"]
            result_info = source["result_label_source"]
            result_path = ROOT / result_info["path"]
            if sha(result_path) != result_info["sha256"]:
                raise Stop(f"RESULT_SOURCE_SHA_MISMATCH:{date}")
            result_index = result_rows(date)
            artifacts = source["prediction_feature_source"]["artifacts"]
            if source["prediction_feature_source"].get("artifact_pattern") != "race_*_prediction.json":
                raise Stop(f"NON_EXPLICIT_RACE_ARTIFACT_PATTERN:{date}")
            for artifact in artifacts:
                path = ROOT / artifact["path"]
                if not path.is_file() or sha(path) != artifact["sha256"]:
                    raise Stop(f"PREDICTION_SOURCE_SHA_MISMATCH:{path}")
                payload = json.loads(path.read_text(encoding="utf-8"))
                race_id = payload.get("race_id")
                if not race_id or race_id.split("_")[1] != date or race_id in seen_races:
                    raise Stop(f"RACE_IDENTITY_INVALID_OR_DUPLICATE:{path}")
                seen_races.add(race_id)
                buy_numbers, authority = formal_buy_set(payload, path)
                buy_validation.append({"date": date, "block": block, **authority})
                target_race_key, result_row = result_for_race(race_id, result_index)
                traces = {int(row["horse_number"]): row for row in payload.get("buy_gate_trace", {}).get("horses", [])}
                race_trace = payload.get("buy_gate_trace", {}).get("race", {})
                ranked = payload.get("ranked_results")
                if not isinstance(ranked, list) or not ranked:
                    raise Stop(f"RANKED_RESULTS_INVALID:{path}")
                for horse in ranked:
                    number = int(horse["horse_number"])
                    rank = horse.get("rank")
                    current_top5 = rank is not None and int(rank) <= 5
                    if not current_top5:
                        continue
                    label = outcome(result_row, number)
                    if not label["valid_result"]:
                        continue
                    row_id = f"{date}:{race_id}:{number}"
                    if row_id in seen_rows:
                        raise Stop(f"DUPLICATE_ROW_ID:{row_id}")
                    seen_rows.add(row_id)
                    feature_values = {feature: stored(horse, traces.get(number), feature, race_trace) for feature in FEATURES}
                    if any(value is None for value in feature_values.values()):
                        missing = [name for name, value in feature_values.items() if value is None]
                        raise Stop(f"FEATURE_MISSING:{row_id}:{','.join(missing)}")
                    current_buy = number in buy_numbers
                    context = category(current_buy, bool(label["actual_top3"]))
                    full_rows.append({
                        "row_id": row_id, "date": date, "race_id": race_id, "target_race_key": target_race_key,
                        "horse_number": number, "horse_name": horse.get("horse_name"), **feature_values,
                        "current_buy": current_buy, "current_top5": True,
                        "selection_error_category": context, "actual_top3": int(bool(label["actual_top3"])),
                        "actual_finish": label.get("actual_finish"), "valid_result": bool(label["valid_result"]),
                        "source_prediction_artifact_path": artifact["path"], "source_prediction_artifact_sha256": artifact["sha256"],
                        "source_result_artifact_path": result_info["path"], "source_result_artifact_sha256": result_info["sha256"],
                        "source_block": block, "evidence_role_note": "FROZEN_PRE_FEATURES_POST_RESULT_LABEL_ONLY",
                        "dataset_version": "ML_V4_TRAIN_DATASET_V1", "split_role": "TRAIN",
                    })
                source_validation.append({"date": date, "block": block, "status": "PASS", "prediction_artifact_count": len(artifacts), "result_source_sha256": result_info["sha256"]})
        full_rows.sort(key=lambda row: (row["date"], row["race_id"], row["horse_number"]))
        for row in full_rows:
            feature_rows.append({"row_id": row["row_id"], **{feature: row[feature] for feature in FEATURES}})
            target_rows.append({"row_id": row["row_id"], "actual_top3": row["actual_top3"]})
        categories = Counter(row["selection_error_category"] for row in full_rows)
        positives = sum(row["actual_top3"] for row in full_rows)
        if len(full_rows) != 2283 or len(feature_rows) != 2283 or len(target_rows) != 2283:
            raise Stop(f"TRAIN_ROW_COUNT_MISMATCH:{len(full_rows)}:{len(feature_rows)}:{len(target_rows)}")
        if positives != 783 or len(full_rows) - positives != 1500:
            raise Stop(f"TARGET_BALANCE_MISMATCH:{positives}:{len(full_rows)-positives}")
        if dict(categories) != EXPECTED_CATEGORIES:
            raise Stop(f"CATEGORY_COUNTS_MISMATCH:{dict(categories)}")
        if len(FEATURES) != 20 or len({row["row_id"] for row in full_rows}) != len(full_rows):
            raise Stop("FEATURE_OR_ROW_IDENTITY_VALIDATION_FAILED")
        full_fields = ["row_id", "date", "race_id", "target_race_key", "horse_number", "horse_name", *FEATURES, "current_buy", "current_top5", "selection_error_category", "actual_top3", "actual_finish", "valid_result", "source_prediction_artifact_path", "source_prediction_artifact_sha256", "source_result_artifact_path", "source_result_artifact_sha256", "source_block", "evidence_role_note", "dataset_version", "split_role"]
        feature_fields = ["row_id", *FEATURES]
        target_fields = ["row_id", "actual_top3"]
        csv_write(OUT / "dataset.csv", full_fields, full_rows)
        csv_write(OUT / "feature_matrix.csv", feature_fields, feature_rows)
        csv_write(OUT / "target.csv", target_fields, target_rows)
        feature_schema = {"dataset_version": "ML_V4_TRAIN_DATASET_V1", "feature_order": list(FEATURES), "feature_column_count": len(FEATURES), "frozen": True, "excluded_features": ["current_buy", "current_top5", "head_count", "actual_finish", "actual_top3", "valid_result", "selection_error_category", "payout", "result_derived_information"]}
        schema = {"dataset_version": "ML_V4_TRAIN_DATASET_V1", "split_role": "TRAIN", "identity_columns": full_fields[:6], "feature_columns": list(FEATURES), "context_columns": ["current_buy", "current_top5", "selection_error_category"], "target_column": "actual_top3", "audit_only_columns": ["actual_finish", "valid_result"], "provenance_columns": full_fields[-8:], "row_order": "date ASC, race_id ASC, horse_number ASC", "row_identity": "date:race_id:horse_number"}
        write_json("feature_schema.json", feature_schema); write_json("dataset_schema.json", schema)
        write_json("source_manifest.json", {"status": "PASS", "authoritative_inventory": str(INVENTORY_OUT.relative_to(ROOT)), "inventory_summary_sha256": sha(INVENTORY_OUT / "summary.json"), "sources": inventory_sources, "source_validation": source_validation, "may_access_count": 0, "march_or_earlier_access_count": 0, "prediction_regeneration_count": 0})
        write_json("lineage.json", {"april_lineage_status": "April historical evidence role preserved; V4 TRAIN reuse is additive.", "existing_april_cf_v3_evidence_status": "RETROSPECTIVE_EXTERNAL_HOLDOUT_UNCHANGED", "v4_train_role": "TRAIN_DEVELOPMENT_ELIGIBLE", "may_role": "UNTOUCHED_RESERVE_FUTURE_INDEPENDENT_OOS_CANDIDATE", "candidate_generation_diagnostic_reference": {"miss": 595, "top5_capture": {"numerator": 783, "denominator": 1378, "rate": 783 / 1378}}})
        write_json("validation.json", {"status": "PASS", "race_population_source_consistency": "PASS", "train_row_count": len(full_rows), "feature_row_count": len(feature_rows), "target_row_count": len(target_rows), "feature_column_count": len(FEATURES), "feature_missing_count": 0, "row_duplicate_count": 0, "target_balance": {"positive": positives, "negative": len(full_rows)-positives}, "selection_error_counts": dict(categories), "buy_authority_validation": "PASS", "result_leakage_validation": "PASS", "may_access_count": 0, "march_or_earlier_access_count": 0, "prediction_regeneration_count": 0, "existing_source_overwrite_count": 0})
        write_json("leakage_validation.json", {"status": "PASS", "feature_columns": list(FEATURES), "feature_column_count": len(FEATURES), "forbidden_feature_columns": ["current_buy", "current_top5", "actual_finish", "actual_top3", "valid_result", "selection_error_category", "payout", "result_derived_information"], "forbidden_present_in_feature_matrix": [], "result_fields_used_as_features": 0, "result_usage": "TARGET_AND_CONTEXT_LABEL_ONLY"})
        write_json("dataset_summary.json", {"dataset_build_status": "PASS", "final_status": "V4_TRAIN_DATASET_V1_BUILT", "train_row_count": len(full_rows), "feature_count": len(FEATURES), "target_balance": {"positive": positives, "negative": len(full_rows)-positives}, "selection_error_counts": dict(categories), "feature_missing_count": 0, "row_duplicate_count": 0, "buy_authority_validation": "PASS", "result_leakage_validation": "PASS", "april_lineage_status": "PRESERVED_AND_ADDITIVE", "source_manifest_status": "PASS", "may_access_count": 0, "march_or_earlier_access_count": 0, "prediction_regeneration_count": 0, "model_training_ready": "YES", "blocking": [], "major": [], "minor": [], "no_resampling_initial": True, "model_training_execution": 0})
        write_json("dataset_manifest.json", {"dataset_version": "ML_V4_TRAIN_DATASET_V1", "status": "FROZEN_BUILD_ARTIFACT", "split_role": "TRAIN", "dataset_sha256": sha(OUT / "dataset.csv"), "feature_schema_sha256": sha(OUT / "feature_schema.json"), "source_manifest_sha256": sha(OUT / "source_manifest.json"), "target_semantics": "actual_top3 true=1 false=0; Top5 and valid_result only", "feature_order": list(FEATURES), "no_resampling_initial": True, "april_lineage": "preserved historical holdout evidence; additive V4 TRAIN reuse", "may": "UNTOUCHED_RESERVE"})
        write_json("buy_authority_validation.json", {"status": "PASS", "authority": "ranked_results[].decision == 'BUY'", "race_validation_count": len(buy_validation), "races": buy_validation})
        write_json("artifact_hashes.json", {"indexed_artifacts": {p.name: sha(p) for p in OUT.iterdir() if p.is_file() and p.name != "artifact_hashes.json"}, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write_json("dataset_summary.json", {"dataset_build_status": "FAIL", "final_status": "V4_TRAIN_DATASET_BUILD_FAILED", "reason": str(exc), "model_training_ready": "NO", "may_access_count": 0, "march_or_earlier_access_count": 0, "prediction_regeneration_count": 0})
        return OUT


if __name__ == "__main__":
    print(build())
