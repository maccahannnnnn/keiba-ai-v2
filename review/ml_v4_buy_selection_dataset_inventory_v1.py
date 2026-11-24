"""Read-only inventory for the agreed V4 BUY-selection learning population."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.historical_replay_post_race import result_semantics
from review.target_bulk_prediction_input_adapter_v1 import COURSE_KEYS


OUT = ROOT / "reports" / "ml_v4_buy_selection_dataset_inventory_v1"
RESULT_ROOT = ROOT / "data" / "raw" / "target" / "daily_result_list"
BLOCKS = {
    "April": {
        "root": ROOT / "reports" / "april_2026_retrospective_external_holdout_v2" / "pre_execution_full_8date_v1" / "prediction",
        "dates": ("20260404", "20260405", "20260411", "20260412", "20260418", "20260419", "20260425", "20260426"),
        "layout": "date_directory",
    },
    "June": {"root": ROOT / "reports" / "h5_temporal_june_block1_v1", "dates": ("20260620", "20260621", "20260627", "20260628"), "layout": "prediction_prefix"},
    "July H1": {"root": ROOT / "reports" / "cand_h5_001_july_4day_validation_v1", "dates": ("20260704", "20260705", "20260711", "20260712"), "layout": "prediction_prefix"},
    "July H2": {"root": ROOT / "reports" / "h5_temporal_july_h2_v1", "dates": ("20260718", "20260719", "20260725", "20260726"), "layout": "prediction_prefix"},
    "August Development": {"root": ROOT / "reports" / "buy_improvement_historical_6day_v1", "dates": ("20260801", "20260802", "20260808", "20260809"), "layout": "prediction_prefix"},
    "August Development (Prospective)": {"root": ROOT / "reports", "dates": ("20260815", "20260816"), "layout": "prospective"},
}
ABNORMAL = {"中止", "除外", "取消", "失格"}
V3_FEATURES = ("Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle")
FEATURES = (
    "shadow_ai_rank", "decision_score", "final_score", "adjusted_score",
    "absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass",
    "consensus_positive_count", "consensus_negative_count", "risk_count", "conflict_count", "race_state", "head_count",
    *V3_FEATURES,
)


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def prediction_files(block: dict, date: str) -> list[Path]:
    root, layout = block["root"], block["layout"]
    if layout == "date_directory":
        return sorted((root / date).glob("*_prediction.json"))
    if layout == "prediction_prefix":
        return sorted((root / f"prediction_{date}").glob("*_prediction.json"))
    if date == "20260815":
        return sorted((root / "prospective_analysis_20260815_v1").glob("**/*_prediction.json"))
    return sorted((root / "prospective_analysis_20260816_v1").glob("**/*_prediction.json"))


def result_rows(date: str) -> dict[str, list[str]]:
    path = RESULT_ROOT / f"馬番順着順_{date}.csv"
    if not path.is_file():
        raise Stop(f"MISSING_PRIMARY_RESULT:{date}")
    with path.open(encoding="cp932", newline="") as source:
        rows = list(csv.reader(source))
    if not rows or any(len(row) < 13 for row in rows):
        raise Stop(f"INVALID_PRIMARY_RESULT:{date}")
    index = {row[0]: row for row in rows}
    if len(index) != len(rows):
        raise Stop(f"DUPLICATE_RESULT_RACE:{date}")
    return index


def outcome(row: list[str], horse_number: int) -> dict:
    raw = row[11 + horse_number].strip()
    if raw.isdigit() and int(raw) > 0:
        source = {"馬番": str(horse_number), "確定着順": raw, "異常コード": "0"}
    elif raw in ABNORMAL:
        source = {"馬番": str(horse_number), "確定着順": "0", "異常コード": raw}
    else:
        raise Stop(f"UNKNOWN_RESULT_STATUS:{raw!r}")
    return result_semantics(source)


def result_for_race(race_id: str, index: dict[str, list[str]]) -> tuple[str, list[str]]:
    parts = race_id.split("_")
    if len(parts) != 4 or not parts[-1].endswith("R"):
        raise Stop(f"INVALID_RACE_ID:{race_id}")
    venue_key, number = parts[2], int(parts[3][:-1])
    venue = next((name for name, key in COURSE_KEYS.items() if key == venue_key), None)
    matches = [(key, row) for key, row in index.items() if row[1] == venue and int(row[2]) == number]
    if len(matches) != 1:
        raise Stop(f"RESULT_RACE_MATCH:{race_id}:{len(matches)}")
    return matches[0]


def stored_value(horse: dict, trace: dict | None, feature: str, race: dict, head_count: object) -> object:
    if feature in V3_FEATURES:
        return (trace or {}).get("evaluator_score_snapshot", {}).get(feature)
    if feature == "race_state":
        return race.get("shadow_race_state")
    if feature == "head_count":
        return head_count
    if feature in horse:
        return horse.get(feature)
    return (trace or {}).get(feature)


def category(row: dict) -> str | None:
    if not row["current_top5"] or not row["valid_result"]:
        return None
    if row["current_buy"] and row["actual_top3"]:
        return "TRUE_BUY_SUCCESS"
    if row["current_buy"]:
        return "BUY_FALSE_POSITIVE"
    if row["actual_top3"]:
        return "TOP5_NONBUY_MISSED"
    return "TRUE_BUY_ABSTENTION"


def aggregate(rows: list[dict]) -> dict:
    top5 = [row for row in rows if row["current_top5"]]
    valid_top5 = [row for row in top5 if row["valid_result"]]
    counts = Counter(row["selection_error_category"] for row in valid_top5)
    all_top3 = [row for row in rows if row["valid_result"] and row["actual_top3"]]
    captured = [row for row in all_top3 if row["current_top5"]]
    return {
        "races": len({row["race_id"] for row in rows}), "horse_rows": len(rows), "top5_rows": len(top5), "top5_valid_rows": len(valid_top5),
        "category_counts": {name: counts[name] for name in ("TRUE_BUY_SUCCESS", "BUY_FALSE_POSITIVE", "TOP5_NONBUY_MISSED", "TRUE_BUY_ABSTENTION")},
        "candidate_generation_miss": sum(not row["current_top5"] and row["valid_result"] and row["actual_top3"] for row in rows),
        "top5_capture": {"numerator": len(captured), "denominator": len(all_top3), "rate": len(captured) / len(all_top3) if all_top3 else None},
    }


def run() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        rows, source_manifest, block_rows = [], [], defaultdict(list)
        for block_name, block in BLOCKS.items():
            for date in block["dates"]:
                result_index = result_rows(date)
                files = prediction_files(block, date)
                if not files:
                    raise Stop(f"MISSING_PREDICTION_ARTIFACT:{block_name}:{date}")
                source_manifest.append({"block": block_name, "date": date, "prediction_files": [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in files], "result_primary_path": str((RESULT_ROOT / f"馬番順着順_{date}.csv").relative_to(ROOT)), "result_primary_sha256": sha(RESULT_ROOT / f"馬番順着順_{date}.csv")})
                for path in files:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    race_id = payload.get("race_id")
                    if not race_id or race_id.split("_")[1] != date:
                        raise Stop(f"PREDICTION_DATE_IDENTITY:{path}")
                    key, result = result_for_race(race_id, result_index)
                    traces = {item["horse_number"]: item for item in payload.get("buy_gate_trace", {}).get("horses", [])}
                    race_trace = payload.get("buy_gate_trace", {}).get("race", {})
                    ranked = payload.get("ranked_results", [])
                    if not ranked:
                        raise Stop(f"EMPTY_RANKED_RESULTS:{path}")
                    for horse in ranked:
                        number = int(horse["horse_number"])
                        result_value = outcome(result, number)
                        record = {"block": block_name, "date": date, "race_id": race_id, "target_race_key": key, "horse_number": number, "horse_name": horse.get("horse_name"), "current_buy": bool(horse.get("buy")), "current_top5": horse.get("rank") is not None and int(horse["rank"]) <= 5, "source_prediction_artifact_path": str(path.relative_to(ROOT)), "source_prediction_artifact_sha256": sha(path), "source_result_artifact_path": str((RESULT_ROOT / f"馬番順着順_{date}.csv").relative_to(ROOT)), "source_result_artifact_sha256": sha(RESULT_ROOT / f"馬番順着順_{date}.csv"), **result_value}
                        trace = traces.get(number)
                        record["features"] = {feature: stored_value(horse, trace, feature, race_trace, payload.get("head_count")) for feature in FEATURES}
                        record["selection_error_category"] = category(record)
                        rows.append(record)
                        block_rows[block_name].append(record)
        total = aggregate(rows)
        if total["races"] != 459:
            raise Stop(f"PREDICTION_RACE_COUNT:{total['races']}")
        if sum(total["category_counts"].values()) != total["top5_valid_rows"]:
            raise Stop("CATEGORY_TOTAL_MISMATCH")
        features = {}
        for feature in FEATURES:
            available = sum(row["features"][feature] is not None for row in rows)
            features[feature] = {"available_row_count": available, "missing_row_count": len(rows) - available, "missing_rate": (len(rows) - available) / len(rows), "source": "FROZEN_PREDICTION_ARTIFACT_ONLY", "semantic_consistency": "PRESENT_AS_STORED_ONLY" if available else "MISSING_NOT_RECONSTRUCTED"}
        missing = [name for name, info in features.items() if info["missing_row_count"]]
        blocks = {name: aggregate(block_rows[name]) for name in BLOCKS}
        top5_viability = "DESIGN_REVIEW_REQUIRED" if total["top5_capture"]["rate"] is not None and total["top5_capture"]["rate"] < 0.5 else "TOP5_SCOPE_SUPPORTED_FOR_INVENTORY_ONLY"
        readiness = "MORE_DESIGN_REQUIRED" if missing else "READY"
        status = "V4_DATASET_DESIGN_REVIEW_REQUIRED" if top5_viability == "DESIGN_REVIEW_REQUIRED" or missing else "V4_DATASET_INVENTORY_COMPLETE"
        summary = {"inventory_status": "DESIGN_REVIEW_REQUIRED" if status.endswith("DESIGN_REVIEW_REQUIRED") else "PASS", "final_status": status, "prediction_races": total["races"], "total_horse_rows": total["horse_rows"], "top5_rows": total["top5_rows"], "top5_valid_rows": total["top5_valid_rows"], "category_counts": total["category_counts"], "candidate_generation_miss": total["candidate_generation_miss"], "top5_capture_rate": total["top5_capture"], "block_level_counts": blocks, "missing_not_reconstructed_fields": missing, "class_imbalance_observation": "COUNTS_ONLY_NO_WEIGHTING_OR_SAMPLING_APPLIED", "top5_scope_viability": top5_viability, "april_lineage_status": {"cf_v3": "RETROSPECTIVE_EXTERNAL_HOLDOUT_UNCHANGED", "v4": "TRAIN_DEVELOPMENT_ELIGIBLE_ADDITIVE_LINEAGE_CANDIDATE_ONLY"}, "may_access_count": 0, "access_before_march_count": 0, "dataset_build_readiness": readiness, "blocking": [], "major": ["FEATURE_AVAILABILITY_GAPS_REQUIRE_SCHEMA_DESIGN" ] if missing else [], "minor": [], "prohibited_actions": {"training": 0, "model_build": 0, "feature_selection": 0, "threshold_tuning": 0, "production_change": 0}}
        write("summary.json", summary)
        write("block_level_counts.json", blocks)
        write("feature_availability.json", features)
        write("source_manifest.json", {"sources": source_manifest, "may_access_count": 0, "access_before_march_count": 0})
        write("inventory_safety.json", {"status": "PASS", "prediction_execution": 0, "training": 0, "may_access": 0, "access_before_march": 0, "production_change": 0, "raw_change": 0})
        (OUT / "report.md").write_text("# ML V4 BUY Selection Learning — Dataset Inventory v1\n\n学習・fit・特徴量選択・閾値調整は実施していない。詳細はJSON成果物を参照。\n", encoding="utf-8")
        hashes = {p.name: sha(p) for p in OUT.iterdir() if p.is_file()}
        write("artifact_hashes.json", {"indexed_artifacts": hashes, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write("summary.json", {"inventory_status": "FAIL", "final_status": "V4_DATASET_DESIGN_REVIEW_REQUIRED", "reason": str(exc), "may_access_count": 0, "training": 0})
        return OUT


if __name__ == "__main__":
    print(run())
