"""Corrected, read-only inventory for the V4 BUY-selection learning population.

This program deliberately does not build a dataset or train a model.  It only
audits frozen prediction artifacts and uses daily results as labels.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.historical_replay_post_race import result_semantics
from review.target_bulk_prediction_input_adapter_v1 import COURSE_KEYS

OUT = ROOT / "reports" / "ml_v4_buy_selection_dataset_inventory_v2"
RESULT_ROOT = ROOT / "data" / "raw" / "target" / "daily_result_list"
V1_SOURCE_MANIFEST = ROOT / "reports" / "ml_v4_buy_selection_dataset_inventory_v1" / "source_manifest.json"

BLOCKS = {
    "April": {"root": ROOT / "reports" / "april_2026_retrospective_external_holdout_v2" / "pre_execution_full_8date_v1" / "prediction", "dates": ("20260404", "20260405", "20260411", "20260412", "20260418", "20260419", "20260425", "20260426"), "layout": "date_directory"},
    "June": {"root": ROOT / "reports" / "h5_temporal_june_block1_v1", "dates": ("20260620", "20260621", "20260627", "20260628"), "layout": "prediction_prefix"},
    "July H1": {"root": ROOT / "reports" / "cand_h5_001_july_4day_validation_v1", "dates": ("20260704", "20260705", "20260711", "20260712"), "layout": "prediction_prefix"},
    "July H2": {"root": ROOT / "reports" / "h5_temporal_july_h2_v1", "dates": ("20260718", "20260719", "20260725", "20260726"), "layout": "prediction_prefix"},
    "August Development": {"root": ROOT / "reports" / "buy_improvement_trace_6day_v1", "dates": ("20260801", "20260802", "20260808", "20260809"), "layout": "prediction_prefix"},
    "August Development (Prospective)": {"root": ROOT / "reports" / "buy_improvement_trace_6day_v1", "dates": ("20260815", "20260816"), "layout": "prediction_prefix"},
}
ABNORMAL = {"中止", "除外", "取消", "失格"}
V3_FEATURES = ("Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle")
FEATURES = ("shadow_ai_rank", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count", "consensus_negative_count", "risk_count", "conflict_count", "race_state", *V3_FEATURES)


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def race_files(block: dict, date: str) -> list[Path]:
    root = block["root"] / (date if block["layout"] == "date_directory" else f"prediction_{date}")
    # Explicitly excludes race_index.json and all manifests/summaries.
    return sorted(root.glob("race_*_prediction.json"))


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


def outcome(result_row: list[str], horse_number: int) -> dict:
    raw = result_row[11 + horse_number].strip()
    if raw.isdigit() and int(raw) > 0:
        source = {"馬番": str(horse_number), "確定着順": raw, "異常コード": "0"}
    elif raw in ABNORMAL:
        source = {"馬番": str(horse_number), "確定着順": "0", "異常コード": raw}
    else:
        raise Stop(f"UNKNOWN_RESULT_STATUS:{raw!r}")
    return result_semantics(source)


def formal_buy_set(payload: dict, path: Path) -> tuple[set[int], dict]:
    ranked = payload.get("ranked_results")
    formal_buys = payload.get("buys")
    if not isinstance(ranked, list) or not ranked or not isinstance(formal_buys, list):
        raise Stop(f"BUY_AUTHORITY_STRUCTURE_INVALID:{path}")
    if any(not isinstance(row.get("decision"), str) for row in ranked):
        raise Stop(f"BUY_AUTHORITY_DECISION_MISSING:{path}")
    try:
        derived = {int(row["horse_number"]) for row in ranked if row["decision"] == "BUY"}
        stated = {int(row["horse_number"]) for row in formal_buys}
        stated_count = int(payload["buy_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Stop(f"BUY_AUTHORITY_INVALID:{path}:{exc}") from exc
    if len(derived) != sum(row["decision"] == "BUY" for row in ranked) or len(stated) != len(formal_buys):
        raise Stop(f"BUY_AUTHORITY_DUPLICATE_HORSE:{path}")
    if derived != stated or len(derived) != stated_count:
        raise Stop(f"BUY_AUTHORITY_MISMATCH:{path}")
    return derived, {"path": str(path.relative_to(ROOT)), "race_id": payload.get("race_id"), "derived_buy_horse_numbers": sorted(derived), "formal_buys_horse_numbers": sorted(stated), "derived_buy_count": len(derived), "formal_buy_count": stated_count, "status": "PASS"}


def stored(horse: dict, trace: dict | None, feature: str, race_trace: dict) -> object:
    if feature in V3_FEATURES:
        return (trace or {}).get("evaluator_score_snapshot", {}).get(feature)
    if feature == "race_state":
        return race_trace.get("shadow_race_state")
    return horse.get(feature, (trace or {}).get(feature))


def category(record: dict) -> str | None:
    if not record["current_top5"] or not record["valid_result"]:
        return None
    if record["current_buy"] and record["actual_top3"]:
        return "TRUE_BUY_SUCCESS"
    if record["current_buy"]:
        return "BUY_FALSE_POSITIVE"
    if record["actual_top3"]:
        return "TOP5_NONBUY_MISSED"
    return "TRUE_BUY_ABSTENTION"


def aggregate(rows: list[dict]) -> dict:
    top5 = [r for r in rows if r["current_top5"]]
    valid = [r for r in top5 if r["valid_result"]]
    counts = Counter(r["selection_error_category"] for r in valid)
    all_top3 = [r for r in rows if r["valid_result"] and r["actual_top3"]]
    captured = [r for r in all_top3 if r["current_top5"]]
    return {"races": len({r["race_id"] for r in rows}), "horse_rows": len(rows), "top5_rows": len(top5), "top5_valid_rows": len(valid), "category_counts": {k: counts[k] for k in ("TRUE_BUY_SUCCESS", "BUY_FALSE_POSITIVE", "TOP5_NONBUY_MISSED", "TRUE_BUY_ABSTENTION")}, "candidate_generation_miss": sum(not r["current_top5"] and r["valid_result"] and r["actual_top3"] for r in rows), "top5_capture": {"numerator": len(captured), "denominator": len(all_top3), "rate": len(captured) / len(all_top3) if all_top3 else None}, "target_balance": {"actual_top3_true": sum(r["actual_top3"] for r in valid), "actual_top3_false": sum(not r["actual_top3"] for r in valid)}, "formal_buy_count": sum(r["current_buy"] for r in rows), "formal_buy_identity_count": len({(r["race_id"], r["horse_number"]) for r in rows if r["current_buy"]})}


def availability(rows: list[dict]) -> dict:
    return {f: {"available_row_count": sum(r["features"][f] is not None for r in rows), "missing_row_count": sum(r["features"][f] is None for r in rows), "missing_rate": sum(r["features"][f] is None for r in rows) / len(rows) if rows else None, "source": "FROZEN_PRE_ARTIFACT_ONLY", "missing_not_reconstructed": True} for f in FEATURES}


def v1_august_identity() -> dict[str, set[tuple[str, int]]]:
    if not V1_SOURCE_MANIFEST.is_file():
        raise Stop("MISSING_V1_SOURCE_MANIFEST_FOR_AUGUST_IDENTITY")
    manifest = json.loads(V1_SOURCE_MANIFEST.read_text(encoding="utf-8"))
    result: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for source in manifest.get("sources", []):
        date = source.get("date")
        if date not in {"20260801", "20260802", "20260808", "20260809", "20260815", "20260816"}:
            continue
        for item in source.get("prediction_files", []):
            path = ROOT / item["path"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            result[date].update((payload["race_id"], int(row["horse_number"])) for row in payload["ranked_results"])
    return result


def run() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        expected_august = v1_august_identity()
        rows: list[dict] = []
        by_block: dict[str, list[dict]] = defaultdict(list)
        by_date: dict[str, list[dict]] = defaultdict(list)
        source_manifest, authority_records, artifacts = [], [], []
        seen_races, seen_horses = set(), set()
        for block_name, block in BLOCKS.items():
            for date in block["dates"]:
                files = race_files(block, date)
                if not files:
                    raise Stop(f"MISSING_PREDICTION_ARTIFACT:{block_name}:{date}")
                # Validate all BUY authorities before creating labels/categories.
                date_authority, date_payloads = [], []
                for path in files:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    race_id = payload.get("race_id")
                    if not race_id or race_id.split("_")[1] != date:
                        raise Stop(f"PREDICTION_DATE_IDENTITY:{path}")
                    buys, validation = formal_buy_set(payload, path)
                    date_authority.append(validation)
                    date_payloads.append((path, payload, buys))
                authority_records.append({"block": block_name, "date": date, "status": "PASS", "race_artifact_count": len(files), "derived_buy_identity_count": sum(v["derived_buy_count"] for v in date_authority), "formal_buy_count": sum(v["formal_buy_count"] for v in date_authority), "races": date_authority})
                result_index = result_rows(date)
                source_manifest.append({"block": block_name, "date": date, "prediction_feature_source": {"root": str((block["root"] / (date if block["layout"] == "date_directory" else f"prediction_{date}")).relative_to(ROOT)), "artifact_pattern": "race_*_prediction.json", "artifacts": [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in files]}, "current_buy_authority": "ranked_results[].decision == 'BUY'", "result_label_source": {"path": str((RESULT_ROOT / f"馬番順着順_{date}.csv").relative_to(ROOT)), "sha256": sha(RESULT_ROOT / f"馬番順着順_{date}.csv")}, "semantic_role": "FROZEN_PRE_FEATURES_PLUS_POST_LABELS_ONLY"})
                for path, payload, buys in date_payloads:
                    race_id = payload["race_id"]
                    if race_id in seen_races:
                        raise Stop(f"DUPLICATE_RACE_ID:{race_id}")
                    seen_races.add(race_id)
                    target_key, result_row = result_for_race(race_id, result_index)
                    ranked = payload["ranked_results"]
                    trace = {int(x["horse_number"]): x for x in payload.get("buy_gate_trace", {}).get("horses", [])}
                    race_trace = payload.get("buy_gate_trace", {}).get("race", {})
                    artifacts.append({"date": date, "race_id": race_id, "horse_numbers": sorted(int(x["horse_number"]) for x in ranked)})
                    for horse in ranked:
                        number = int(horse["horse_number"])
                        key = (race_id, number)
                        if key in seen_horses:
                            raise Stop(f"DUPLICATE_HORSE_IDENTITY:{race_id}:{number}")
                        seen_horses.add(key)
                        record = {"block": block_name, "date": date, "race_id": race_id, "horse_number": number, "horse_name": horse.get("horse_name"), "current_buy": number in buys, "current_top5": horse.get("rank") is not None and int(horse["rank"]) <= 5, "target_race_key": target_key, **outcome(result_row, number)}
                        record["features"] = {f: stored(horse, trace.get(number), f, race_trace) for f in FEATURES}
                        record["selection_error_category"] = category(record)
                        rows.append(record); by_block[block_name].append(record); by_date[date].append(record)
        if len(seen_races) != 459:
            raise Stop(f"PREDICTION_RACE_COUNT:{len(seen_races)}")
        august_rows = [r for r in rows if r["date"].startswith("202608")]
        actual_august = defaultdict(set)
        for row in august_rows:
            actual_august[row["date"]].add((row["race_id"], row["horse_number"]))
        august_checks = {date: {"expected_horse_identities": len(expected_august[date]), "trace_horse_identities": len(actual_august[date]), "identity_match": expected_august[date] == actual_august[date]} for date in sorted(expected_august)}
        if set(expected_august) != set(actual_august) or any(not check["identity_match"] for check in august_checks.values()) or len({r["race_id"] for r in august_rows}) != 104:
            raise Stop("AUGUST_TRACE_POPULATION_IDENTITY_MISMATCH")
        total = aggregate(rows)
        if sum(total["category_counts"].values()) != total["top5_valid_rows"]:
            raise Stop("CATEGORY_TOTAL_MISMATCH")
        feature_total = availability(rows)
        block_counts = {name: aggregate(by_block[name]) for name in BLOCKS}
        date_counts = {date: aggregate(by_date[date]) for date in sorted(by_date)}
        missing_blocks = {name: availability(by_block[name]) for name in BLOCKS}
        missing_dates = {date: availability(by_date[date]) for date in sorted(by_date)}
        missing_features = [name for name, info in feature_total.items() if info["missing_row_count"]]
        readiness = "MORE_DESIGN_REQUIRED" if missing_features else "READY"
        summary = {"inventory_v1_status": "SUPERSEDED_DUE_TO_SOURCE_SELECTION_ERROR", "inventory_v2_status": "PASS", "final_status": "V4_DATASET_INVENTORY_V2_COMPLETE", "prediction_races": total["races"], "total_horse_rows": total["horse_rows"], "top5_rows": total["top5_rows"], "top5_valid_rows": total["top5_valid_rows"], "category_counts": total["category_counts"], "candidate_generation_miss": total["candidate_generation_miss"], "top5_capture_rate": total["top5_capture"], "target_balance": total["target_balance"], "formal_buy_counts": {"total": total["formal_buy_count"], "identity_count": total["formal_buy_identity_count"], "by_block": {k: v["formal_buy_count"] for k, v in block_counts.items()}, "by_date": {k: v["formal_buy_count"] for k, v in date_counts.items()}}, "buy_authority_validation": "PASS", "august_trace_source_validation": {"status": "PASS", "race_count": 104, "per_date": august_checks}, "race_horse_identity_status": "PASS", "result_leakage_status": "PASS_LABELS_ONLY", "feature_availability_status": "COMPLETE_BY_OVERALL_BLOCK_DATE", "excluded_from_candidate_features": ["current_buy", "current_top5", "head_count"], "class_imbalance_observation": "COUNTS_ONLY_NO_RESAMPLING_OR_WEIGHTING_APPLIED", "may_access_count": 0, "march_or_earlier_access_count": 0, "dataset_build_readiness": readiness, "blocking": [], "major": ["FEATURE_AVAILABILITY_GAPS_REQUIRE_DESIGN_REVIEW"] if missing_features else [], "minor": [], "prohibited_actions": {"dataset_build": 0, "training": 0, "scaler_fit": 0, "logistic_regression_fit": 0, "feature_selection": 0, "imputation_or_reconstruction": 0, "threshold_tuning": 0, "performance_evaluation": 0, "may_access": 0, "march_or_earlier_access": 0, "cf_change": 0, "production_change": 0}}
        write("summary.json", summary); write("block_level_counts.json", block_counts); write("date_level_counts.json", date_counts); write("feature_availability.json", feature_total); write("feature_missingness_by_block.json", missing_blocks); write("feature_missingness_by_date.json", missing_dates); write("source_manifest.json", {"sources": source_manifest, "formal_source_policy": "AUGUST_6_DATES_TRACE_SOLE_SOURCE", "may_access_count": 0, "march_or_earlier_access_count": 0}); write("buy_authority_validation.json", {"status": "PASS", "authority": "ranked_results[].decision == 'BUY'", "by_date": authority_records}); write("identity_validation.json", {"status": "PASS", "race_count": len(seen_races), "horse_identity_count": len(seen_horses), "duplicate_race_count": 0, "duplicate_horse_count": 0, "ambiguous_join_count": 0, "august_trace_population_validation": {"status": "PASS", "race_count": 104, "per_date": august_checks}}); write("inventory_safety.json", {"status": "PASS", "prediction_execution": 0, "dataset_build": 0, "training": 0, "result_fields_used_as_features": 0, "may_access": 0, "march_or_earlier_access": 0, "production_change": 0, "raw_change": 0, "v1_modified": 0})
        (OUT / "report.md").write_text("# ML V4 BUY Selection Learning — Corrected Dataset Inventory v2\n\nv1は変更せず、August 6日分はTrace完備の正式PRE artifactのみで独立再集計した。学習、データセット構築、特徴量選択、欠損補完、閾値調整、性能評価は実施していない。\n", encoding="utf-8")
        write("artifact_hashes.json", {"indexed_artifacts": {p.name: sha(p) for p in OUT.iterdir() if p.is_file() and p.name != "artifact_hashes.json"}, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write("summary.json", {"inventory_v1_status": "SUPERSEDED_DUE_TO_SOURCE_SELECTION_ERROR", "inventory_v2_status": "FAIL", "final_status": "V4_DATASET_INVENTORY_V2_FAILED", "reason": str(exc), "may_access_count": 0, "march_or_earlier_access_count": 0, "dataset_build_readiness": "MORE_DESIGN_REQUIRED"})
        return OUT


if __name__ == "__main__":
    print(run())
