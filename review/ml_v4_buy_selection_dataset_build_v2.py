"""Freeze V4 TRAIN Dataset v2 by additively reusing May Top5 valid rows.

No model fitting, prediction, scoring, reweighting, sampling, or policy change
occurs here.  Dataset v1 and every May PRE/POST artifact remain read-only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.ml_v4_buy_selection_dataset_build_v1 import (
    FEATURES,
    Stop,
    category,
    csv_write,
    formal_buy_set,
    outcome,
    result_for_race,
    result_rows,
    sha,
    stored,
)

V1 = ROOT / "reports" / "ml_v4_buy_selection_dataset_v1"
PRE = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "pre_retry_v5"
POST = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "post_v1"
OUT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v2"
MAY_DATES = (
    "20260502", "20260503", "20260509", "20260510", "20260516",
    "20260517", "20260523", "20260524", "20260530", "20260531",
)
EXPECTED = {
    "rows": 3240,
    "positive": 1108,
    "negative": 2132,
    "categories": {
        "TRUE_BUY_SUCCESS": 167,
        "BUY_FALSE_POSITIVE": 331,
        "TOP5_NONBUY_MISSED": 941,
        "TRUE_BUY_ABSTENTION": 1801,
    },
    "may_top5_valid_rows": 957,
    "v1_rows": 2283,
}


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def read_v1() -> tuple[list[dict[str, str]], list[str]]:
    path = V1 / "dataset.csv"
    if not path.is_file():
        raise Stop("V1_DATASET_MISSING")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if len(rows) != EXPECTED["v1_rows"] or len(FEATURES) != 20:
        raise Stop(f"V1_STRUCTURE_INVALID:{len(rows)}:{len(FEATURES)}")
    if len({row.get("row_id") for row in rows}) != len(rows):
        raise Stop("V1_DUPLICATE_ROW_ID")
    return rows, fields


def top5_numbers(payload: dict, path: Path) -> set[int]:
    top5 = payload.get("top5")
    trace_horses = payload.get("buy_gate_trace", {}).get("horses", [])
    if not isinstance(top5, list) or not isinstance(trace_horses, list):
        raise Stop(f"MAY_TOP5_STRUCTURE_INVALID:{path}")
    try:
        payload_numbers = {int(row["horse_number"]) for row in top5}
        trace_numbers = {
            int(row["horse_number"])
            for row in trace_horses
            if row.get("shadow_ai_rank") is not None and float(row["shadow_ai_rank"]) <= 5
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise Stop(f"MAY_TOP5_VALUE_INVALID:{path}:{exc}") from exc
    if len(payload_numbers) != len(top5) or payload_numbers != trace_numbers:
        raise Stop(f"MAY_TOP5_SEMANTICS_MISMATCH:{path}")
    return payload_numbers


def may_rows(fields: list[str], seen_races: set[str], seen_rows: set[str]) -> tuple[list[dict], list[dict], dict]:
    records, source_dates, semantic_records = [], [], []
    for date in MAY_DATES:
        files = sorted((PRE / "current_ai" / date).glob("race_*_prediction.json"))
        if not files:
            raise Stop(f"MAY_PREDICTION_SOURCE_MISSING:{date}")
        result_index = result_rows(date)
        result_path = ROOT / "data" / "raw" / "target" / "daily_result_list" / f"馬番順着順_{date}.csv"
        if not result_path.is_file():
            raise Stop(f"MAY_RESULT_SOURCE_MISSING:{date}")
        date_rows, date_races = 0, set()
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            race_id = payload.get("race_id")
            if not isinstance(race_id, str) or race_id.split("_")[1] != date or race_id in seen_races:
                raise Stop(f"MAY_RACE_IDENTITY_INVALID_OR_DUPLICATE:{path}")
            seen_races.add(race_id)
            date_races.add(race_id)
            top5 = top5_numbers(payload, path)
            buy_numbers, buy_authority = formal_buy_set(payload, path)
            ranked = payload.get("ranked_results")
            if not isinstance(ranked, list):
                raise Stop(f"MAY_RANKED_RESULTS_INVALID:{path}")
            ranked_numbers = {int(row["horse_number"]) for row in ranked if row.get("rank") is not None and int(row["rank"]) <= 5}
            if ranked_numbers != top5:
                raise Stop(f"MAY_RANK_TOP5_MISMATCH:{path}")
            trace = {int(row["horse_number"]): row for row in payload.get("buy_gate_trace", {}).get("horses", [])}
            race_trace = payload.get("buy_gate_trace", {}).get("race", {})
            target_race_key, result_row = result_for_race(race_id, result_index)
            for horse in ranked:
                number = int(horse["horse_number"])
                if number not in top5:
                    continue
                label = outcome(result_row, number)
                if not label["valid_result"]:
                    continue
                row_id = f"{date}:{race_id}:{number}"
                if row_id in seen_rows:
                    raise Stop(f"DUPLICATE_ROW_ID:{row_id}")
                seen_rows.add(row_id)
                values = {feature: stored(horse, trace.get(number), feature, race_trace) for feature in FEATURES}
                missing = [key for key, value in values.items() if value is None]
                if missing:
                    raise Stop(f"FEATURE_MISSING:{row_id}:{','.join(missing)}")
                record = {
                    "row_id": row_id,
                    "date": date,
                    "race_id": race_id,
                    "target_race_key": target_race_key,
                    "horse_number": number,
                    "horse_name": horse.get("horse_name"),
                    **values,
                    "current_buy": number in buy_numbers,
                    "current_top5": True,
                    "selection_error_category": category(number in buy_numbers, bool(label["actual_top3"])),
                    "actual_top3": int(bool(label["actual_top3"])),
                    "actual_finish": label.get("actual_finish"),
                    "valid_result": True,
                    "source_prediction_artifact_path": str(path.relative_to(ROOT)),
                    "source_prediction_artifact_sha256": sha(path),
                    "source_result_artifact_path": str(result_path.relative_to(ROOT)),
                    "source_result_artifact_sha256": sha(result_path),
                    "source_block": "May 2026 Independent OOS additive TRAIN reuse for V4 Model v3+",
                    "evidence_role_note": "FROZEN_PRE_FEATURES_POST_RESULT_LABEL_ONLY",
                    "dataset_version": "ML_V4_TRAIN_DATASET_V2",
                    "split_role": "TRAIN",
                }
                if set(record) != set(fields):
                    raise Stop(f"MAY_SCHEMA_MISMATCH:{row_id}")
                records.append(record)
                date_rows += 1
            semantic_records.append({
                "date": date, "race_id": race_id, "artifact": str(path.relative_to(ROOT)),
                "artifact_sha256": sha(path), "payload_top5_count": len(top5),
                "shadow_ai_rank_le_5_count": len(top5), "status": "PASS",
                "buy_authority": buy_authority,
            })
        source_dates.append({
            "date": date, "race_count": len(date_races), "top5_valid_rows": date_rows,
            "prediction_artifact_count": len(files), "result_source_path": str(result_path.relative_to(ROOT)),
            "result_source_sha256": sha(result_path), "status": "PASS",
        })
    return records, source_dates, {"status": "PASS", "race_count": len(semantic_records), "records": semantic_records}


def build() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        pre = json.loads((PRE / "pre_freeze_manifest.json").read_text(encoding="utf-8"))
        post = json.loads((POST / "final_report.json").read_text(encoding="utf-8"))
        if pre.get("final_status") != "MAY_2026_CURRENT_CF_V4_PRE_FROZEN":
            raise Stop("MAY_PRE_FREEZE_AUTHORITY_INVALID")
        if post.get("MAY_OOS_STATUS") != "CONSUMED_INDEPENDENT_OOS_FOR_V4_MODEL_V2":
            raise Stop("MAY_OOS_LINEAGE_AUTHORITY_INVALID")
        v1_rows, fields = read_v1()
        seen_rows = {row["row_id"] for row in v1_rows}
        seen_races = {row["race_id"] for row in v1_rows}
        v1_dates = {row["date"] for row in v1_rows}
        if v1_dates.intersection(MAY_DATES):
            raise Stop("V1_MAY_DATE_OVERLAP")
        added, source_dates, top5_validation = may_rows(fields, seen_races, seen_rows)
        if len(added) != EXPECTED["may_top5_valid_rows"]:
            raise Stop(f"MAY_TOP5_VALID_ROW_COUNT_MISMATCH:{len(added)}")
        rows = sorted([*v1_rows, *added], key=lambda row: (row["date"], row["race_id"], int(row["horse_number"])))
        v1_in_v2 = {row["row_id"]: row for row in rows if row["row_id"] in {item["row_id"] for item in v1_rows}}
        if len(v1_in_v2) != len(v1_rows) or any(v1_in_v2[row["row_id"]] != row for row in v1_rows):
            raise Stop("V1_ROW_CONTENT_CHANGED")
        categories = Counter(row["selection_error_category"] for row in rows)
        positive = sum(int(row["actual_top3"]) for row in rows)
        if len(rows) != EXPECTED["rows"] or positive != EXPECTED["positive"] or len(rows) - positive != EXPECTED["negative"]:
            raise Stop(f"EXPECTED_TARGET_COUNTS_MISMATCH:{len(rows)}:{positive}:{len(rows)-positive}")
        if dict(categories) != EXPECTED["categories"]:
            raise Stop(f"EXPECTED_CATEGORY_COUNTS_MISMATCH:{dict(categories)}")
        feature_rows = [{"row_id": row["row_id"], **{key: row[key] for key in FEATURES}} for row in rows]
        target_rows = [{"row_id": row["row_id"], "actual_top3": row["actual_top3"]} for row in rows]
        csv_write(OUT / "dataset.csv", fields, rows)
        csv_write(OUT / "feature_matrix.csv", ["row_id", *FEATURES], feature_rows)
        csv_write(OUT / "target.csv", ["row_id", "actual_top3"], target_rows)
        write_json("feature_schema.json", {"dataset_version": "ML_V4_TRAIN_DATASET_V2", "feature_order": list(FEATURES), "feature_column_count": 20, "same_as_v1": True, "frozen": True})
        write_json("population_schema.json", {"population": "V1_TRAIN_PLUS_MAY_TOP5_VALID", "May_inclusion": "payload.top5 AND trace.shadow_ai_rank <= 5 AND valid_result", "current_top5": "population_only_not_feature", "current_buy": "context_only_not_feature", "row_weighting": "ONE_VALID_TOP5_ROW_EQUALS_ONE_TRAINING_SAMPLE", "resampling": "PROHIBITED"})
        write_json("source_date_inventory.json", {"v1_date_count": len(v1_dates), "v1_dates": sorted(v1_dates), "may_dates": list(MAY_DATES), "date_overlap": [], "may_sources": source_dates})
        write_json("lineage.json", {"dataset_v1": {"role": "PRESERVED_BYTE_AND_ROW_CONTENT_SOURCE", "dataset_sha256": sha(V1 / "dataset.csv")}, "may_2026": {"model_v2_role": "CONSUMED_INDEPENDENT_OOS_FOR_V4_MODEL_V2", "model_v3_plus_role": "ADDITIVE_TRAIN_REUSE", "oos_evidence_reinterpretation": "PROHIBITED"}, "model_v3_training": "NOT_EXECUTED"})
        write_json("validation.json", {"status": "PASS", "expected_counts": EXPECTED, "actual_counts": {"rows": len(rows), "positive": positive, "negative": len(rows)-positive, "categories": dict(categories), "may_top5_valid_rows": len(added)}, "feature_count": len(FEATURES), "feature_missing_count": 0, "duplicate_race_count": 0, "duplicate_row_count": 0, "target_missing_count": 0, "invalid_category_count": 0, "invalid_valid_result_count": 0, "top5_semantics_validation": top5_validation["status"], "v1_row_content_unchanged": True, "model_fit_count": 0, "scaler_fit_count": 0, "prediction_execution_count": 0, "performance_evaluation_count": 0})
        write_json("dataset_manifest.json", {"dataset_version": "ML_V4_TRAIN_DATASET_V2", "status": "FROZEN_BUILD_ARTIFACT", "dataset_sha256": sha(OUT / "dataset.csv"), "feature_schema_sha256": sha(OUT / "feature_schema.json"), "lineage_sha256": sha(OUT / "lineage.json"), "validation_sha256": sha(OUT / "validation.json"), "row_count": len(rows), "feature_count": 20, "model_v3_training": "NOT_EXECUTED"})
        write_json("dataset_summary.json", {"final_status": "V4_TRAIN_DATASET_V2_BUILT", "status": "PASS", "row_count": len(rows), "target_balance": {"positive": positive, "negative": len(rows)-positive}, "category_counts": dict(categories), "may_top5_valid_rows": len(added), "model_v3_training": "NOT_EXECUTED"})
        write_json("artifact_hashes.json", {"indexed_artifacts": {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write_json("dataset_summary.json", {"final_status": "V4_TRAIN_DATASET_V2_BUILD_FAILED", "status": "FAIL", "reason": str(exc), "formal_freeze": "NO", "model_v3_training": "NOT_EXECUTED"})
        return OUT


if __name__ == "__main__":
    print(build())
