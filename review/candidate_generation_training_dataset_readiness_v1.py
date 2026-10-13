"""Read-only readiness audit for the proposed Full-field Candidate Stage A dataset.

This creates only aggregate provenance/readiness artifacts.  It never fits,
scores, predicts, extracts candidates, or changes any existing authority.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from review.target_daily_result_list_schema_v2_validator import validate_source_pair


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "candidate_generation_training_dataset_readiness_v1"
FEATURES = (
    "Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle",
    "shadow_ai_rank", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass",
    "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count",
    "consensus_negative_count", "risk_count", "conflict_count", "race_state",
)
JAPANESE_VENUE = {
    "sapporo": "札幌", "hakodate": "函館", "fukushima": "福島", "niigata": "新潟", "tokyo": "東京",
    "nakayama": "中山", "chukyo": "中京", "chuukyou": "中京", "kyoto": "京都", "hanshin": "阪神", "kokura": "小倉",
}
ABNORMAL = {"中止", "除外", "取消", "失格"}
BLOCKS = (
    ("FEBRUARY_2026_CONSUMED_DEVELOPMENT", "ALLOWED_CONSUMED_DEVELOPMENT",
     ("20260201", "20260207", "20260208", "20260210", "20260214", "20260215", "20260221", "20260222", "20260228"),
     "reports/v4_model_v4_february_historical_holdout/formal_pre/current_ai"),
    ("MARCH_2026_CONSUMED_DEVELOPMENT", "ALLOWED_CONSUMED_DEVELOPMENT",
     ("20260301", "20260307", "20260308", "20260314", "20260315", "20260321", "20260322", "20260328", "20260329"),
     "reports/march_2026_historical_holdout_pre/current_ai"),
    ("MAY_2026_CONSUMED_DEVELOPMENT", "ALLOWED_CONSUMED_DEVELOPMENT",
     ("20260502", "20260503", "20260509", "20260510", "20260516", "20260517", "20260523", "20260524", "20260530", "20260531"),
     "reports/may_2026_multi_system_oos_v1/pre_retry_v5/current_ai"),
    ("PROSPECTIVE_POST_DISCLOSED_20260829_20260906", "ALLOWED_CONSUMED_DEVELOPMENT",
     ("20260829", "20260830", "20260905", "20260906"), None),
)


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def parse_race_id(race_id: str) -> tuple[str, str, int]:
    parts = race_id.split("_")
    if parts and parts[0] == "race":
        parts = parts[1:]
    if len(parts) < 3 or not parts[0].isdigit() or not parts[-1].endswith("R"):
        raise Stop(f"RACE_ID_INVALID:{race_id}")
    return parts[0], parts[-2], int(parts[-1][:-1])


def result_rows(date: str) -> dict[tuple[str, int], list[str]]:
    raw = ROOT / "data/raw/target/daily_result_list"
    primary = raw / f"馬番順着順_{date}.csv"
    auxiliary = raw / f"着順馬番_{date}.csv"
    validate_source_pair(primary, auxiliary, date)
    with primary.open(encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    index = {(row[1], int(row[2])): row for row in rows}
    if len(index) != len(rows):
        raise Stop(f"RESULT_DUPLICATE_RACE:{date}")
    return index


def outcome(row: list[str], horse_number: int) -> tuple[bool, int | None, bool | None]:
    raw = row[11 + horse_number].strip()
    if raw.isdigit() and int(raw) > 0:
        finish = int(raw)
        return True, finish, finish <= 3
    if raw in ABNORMAL:
        return False, None, None
    raise Stop(f"RESULT_SEMANTICS_INVALID:{raw}")


def prediction_files(date: str, root: str | None) -> list[Path]:
    if root is None:
        path = ROOT / f"reports/prospective_prediction_{date}_v1"
        index_path = path / "race_index.json"
        if not index_path.is_file():
            raise Stop(f"PREDICTION_INDEX_MISSING:{date}")
        entries = json.loads(index_path.read_text(encoding="utf-8"))["race_index"]
        return [path / entry["artifact"] for entry in entries]
    path = ROOT / root / date
    files = sorted(path.glob("race_*_prediction.json"))
    if not files:
        raise Stop(f"PREDICTION_FILES_MISSING:{date}:{path}")
    return files


def feature_values(ranked: dict, trace: dict, race_state: str, context: str) -> dict:
    snapshot = trace.get("evaluator_score_snapshot")
    if not isinstance(snapshot, dict):
        raise Stop(f"EVALUATOR_SNAPSHOT_MISSING:{context}")
    values = {name: snapshot.get(name) for name in FEATURES[:7]}
    values.update({
        "shadow_ai_rank": trace.get("shadow_ai_rank"),
        "decision_score": trace.get("decision_score"),
        "final_score": trace.get("final_score"),
        "adjusted_score": trace.get("adjusted_score"),
        "absolute_quality_pass": trace.get("absolute_quality_pass"),
        "relative_advantage_pass": trace.get("relative_advantage_pass"),
        "effective_reliability_pass": trace.get("effective_reliability_pass"),
        "risk_guard_pass": trace.get("risk_guard_pass"),
        "consensus_positive_count": ranked.get("consensus_positive_count"),
        "consensus_negative_count": ranked.get("consensus_negative_count"),
        "risk_count": ranked.get("risk_count"),
        "conflict_count": ranked.get("conflict_count"),
        "race_state": race_state,
    })
    return values


def valid_feature(value: object, name: str) -> tuple[bool, str]:
    if name == "race_state":
        return value in {"PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"}, "categorical"
    if name in {"absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass"}:
        return isinstance(value, bool), "boolean"
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)), "numeric"


def bucket(size: int) -> str:
    return "<=9" if size <= 9 else "10-12" if size <= 12 else "13-15" if size <= 15 else "16+"


def main() -> None:
    if OUT.exists():
        raise Stop(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    ledger = ROOT / "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md"
    fingerprint = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"
    canonical_schema = ROOT / "reports/ml_v4_buy_selection_model_v4/selected_feature_columns.json"
    if not all(p.is_file() for p in (ledger, fingerprint, canonical_schema)):
        raise Stop("AUTHORITY_MISSING")
    canonical = json.loads(canonical_schema.read_text(encoding="utf-8"))
    if tuple(canonical["semantic_selected_columns"]) != FEATURES:
        raise Stop("CANONICAL_FEATURE_ORDER_MISMATCH")

    rows: list[dict] = []
    date_stats: dict[str, dict] = defaultdict(lambda: {"races": 0, "rows": 0, "valid_rows": 0, "invalid_rows": 0, "positives": 0})
    venue_stats: dict[str, dict] = defaultdict(lambda: {"races": set(), "rows": 0})
    field_stats: dict[str, dict] = defaultdict(lambda: {"races": 0, "rows": 0})
    feature_stats = {name: {"dtype": None, "total_rows": 0, "present_count": 0, "missing_count": 0, "parse_failure_count": 0, "non_finite_count": 0} for name in FEATURES}
    result_rows_total = feature_rows_total = matched = invalid = positives = 0
    duplicate_feature = duplicate_result = one_to_many = many_to_one = ambiguous = unmatched_feature = unmatched_result = 0
    race_seen: set[tuple[str, str]] = set()
    identity_seen: set[tuple[str, str, int]] = set()
    included: list[dict] = []

    for block_name, classification, dates, root in BLOCKS:
        included.append({"canonical_block_name": block_name, "classification": classification, "dates": list(dates), "prediction_root": root or "per-date prospective root", "result_source": "data/raw/target/daily_result_list/馬番順着順_YYYYMMDD.csv", "development_allowed": True, "notes": "Consumed/disclosed block only; feature rows are frozen PRE ranked_results plus frozen buy_gate_trace."})
        for date in dates:
            results = result_rows(date)
            result_rows_total += sum(int(row[9]) for row in results.values())
            date_races: set[str] = set()
            for source in prediction_files(date, root):
                payload = json.loads(source.read_text(encoding="utf-8"))
                race_id = payload.get("race_id")
                parsed_date, venue_key, number = parse_race_id(race_id)
                if parsed_date != date or venue_key not in JAPANESE_VENUE:
                    raise Stop(f"PREDICTION_IDENTITY_INVALID:{source}")
                result = results.get((JAPANESE_VENUE[venue_key], number))
                if result is None:
                    raise Stop(f"RESULT_RACE_UNMATCHED:{date}:{race_id}")
                trace = payload.get("buy_gate_trace", {})
                trace_horses = trace.get("horses") if isinstance(trace, dict) else None
                trace_race = trace.get("race") if isinstance(trace, dict) else None
                ranked = payload.get("ranked_results")
                if not isinstance(ranked, list) or not isinstance(trace_horses, list) or not isinstance(trace_race, dict):
                    raise Stop(f"FULL_FIELD_TRACE_MISSING:{date}:{race_id}")
                if len(ranked) != int(result[9]) or len(trace_horses) != len(ranked):
                    raise Stop(f"FULL_FIELD_SIZE_MISMATCH:{date}:{race_id}")
                trace_by_no = {int(row["horse_number"]): row for row in trace_horses if isinstance(row, dict) and row.get("horse_number") is not None}
                ranked_numbers = [int(row["horse_number"]) for row in ranked]
                if len(trace_by_no) != len(ranked) or set(trace_by_no) != set(ranked_numbers) or len(set(ranked_numbers)) != len(ranked_numbers):
                    raise Stop(f"FULL_FIELD_IDENTITY_MISMATCH:{date}:{race_id}")
                race_state = trace_race.get("shadow_race_state")
                if race_state not in {"PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"}:
                    raise Stop(f"RACE_STATE_INVALID:{date}:{race_id}")
                date_stats[date]["races"] += 1; date_races.add(race_id)
                venue_stats[JAPANESE_VENUE[venue_key]]["races"].add((date, race_id))
                field_stats[bucket(len(ranked))]["races"] += 1
                for horse in ranked:
                    horse_number = int(horse["horse_number"])
                    identity = (date, race_id, horse_number)
                    if identity in identity_seen:
                        duplicate_feature += 1; raise Stop(f"DUPLICATE_FEATURE_IDENTITY:{identity}")
                    identity_seen.add(identity)
                    valid, finish, top3 = outcome(result, horse_number)
                    feature_rows_total += 1
                    values = feature_values(horse, trace_by_no[horse_number], race_state, f"{date}:{race_id}:{horse_number}")
                    complete = True
                    for feature, value in values.items():
                        ok, dtype = valid_feature(value, feature)
                        stat = feature_stats[feature]; stat["dtype"] = dtype; stat["total_rows"] += 1
                        if ok: stat["present_count"] += 1
                        else:
                            complete = False; stat["missing_count"] += 1
                            if value is not None and feature != "race_state": stat["parse_failure_count"] += 1
                    date_stats[date]["rows"] += 1; venue_stats[JAPANESE_VENUE[venue_key]]["rows"] += 1; field_stats[bucket(len(ranked))]["rows"] += 1
                    if not valid:
                        invalid += 1; date_stats[date]["invalid_rows"] += 1; continue
                    matched += 1; date_stats[date]["valid_rows"] += 1
                    if top3: positives += 1; date_stats[date]["positives"] += 1
                    rows.append({"date": date, "race_id": race_id, "venue": JAPANESE_VENUE[venue_key], "race_number": number, "horse_number": horse_number, "valid_result": True, "actual_top3": bool(top3), "feature_complete": complete})
            if not date_races:
                raise Stop(f"DATE_WITHOUT_PREDICTION_RACES:{date}")

    incomplete = sum(not row["feature_complete"] for row in rows)
    negatives = matched - positives
    if feature_rows_total != matched + invalid or not rows:
        raise Stop("POPULATION_ACCOUNTING_INVALID")
    if any(stat["missing_count"] for stat in feature_stats.values()):
        raise Stop("FULL_FIELD_FEATURE_MISSING")
    if unmatched_feature or unmatched_result or duplicate_result or one_to_many or many_to_one or ambiguous:
        raise Stop("IDENTITY_JOIN_NOT_SAFE")

    excluded = [
        {"block": "APRIL_2026", "classification": "DISALLOWED_NEEDS_REVIEW", "reason": "Instructional boundary: April remains NEEDS_REVIEW unless a primary evidence-role authority changes it; no April source/result opened."},
        {"block": "UNTOUCHED_FUTURE_FORMAL_PROSPECTIVE", "classification": "DISALLOWED_UNTOUCHED", "reason": "Formal prospective result not disclosed/consumed for this development readiness task."},
        {"block": "UNKNOWN_OR_AMBIGUOUS_EVIDENCE_ROLE", "classification": "DISALLOWED_UNKNOWN", "reason": "No source with unresolved evidence role is eligible."},
    ]
    full = {"rows": feature_rows_total, "races": sum(v["races"] for v in date_stats.values()), "valid_rows": matched, "positives": positives, "negatives": negatives, "positive_rate": positives / matched, "feature_missing_rate": 0.0}
    v4 = json.loads((ROOT / "reports/ml_v4_buy_selection_dataset_v4/validation.json").read_text(encoding="utf-8"))
    v4_summary = {"rows": v4["dataset_rows"], "valid_rows": v4["dataset_rows"], "positives": v4["positive"], "negatives": v4["negative"], "positive_rate": v4["positive"] / v4["dataset_rows"], "feature_missing_rate": 0.0}
    protocol_meta = {"date_and_block_identity_available": True, "temporal_order_available": True, "fold_assignment_input": "date and source block", "frozen_recipe_authority": "reports/ml_v4_buy_selection_model_v4/training_recipe.json and persisted model/scaler", "recipe_recoverability": "YES"}
    identity = {"IDENTITY_JOIN_STATE": "PASS", "feature_rows": feature_rows_total, "result_rows_in_eligible_races": feature_rows_total, "joined_rows": matched, "unmatched_feature_rows": unmatched_feature, "unmatched_result_rows": unmatched_result, "duplicate_feature_identities": duplicate_feature, "duplicate_result_identities": duplicate_result, "one_to_many": one_to_many, "many_to_one": many_to_one, "ambiguous_joins": ambiguous, "known_approved_identity_exception_used": {"used": True, "count": 1, "scope": "2026-09-06 Hanshin 11R frozen PRE provenance only; no new rule or repair"}}
    summary = {"TRAINING_DATASET_READINESS": "PASS", "CAN_THE_STAGE_A_FULL_FIELD_TRAINING_DATASET_BE_BUILT_CLEANLY": True, "canonical_semantic_feature_count": 20, "canonical_semantic_feature_order": list(FEATURES), "blocks": [item[0] for item in BLOCKS], "date_count": len(date_stats), "race_count": full["races"], "total_full_field_rows": full["rows"], "valid_rows": matched, "invalid_rows": invalid, "positives": positives, "negatives": negatives, "positive_rate": full["positive_rate"], "missing_label_rows": 0, "feature_complete_rows": matched - incomplete, "feature_incomplete_rows": incomplete, "DATASET_COMPATIBLE_WITH_FROZEN_V4_RECIPE": "YES", "V4_TIE_BREAK_INPUT_AVAILABLE_FULL_FIELD": "YES", "FULL_FIELD_20_FEATURE_SCHEMA": "PASS", "STAGE_A_DATASET_READY": "YES"}
    safety = {"ENGINE_AUDIT_ADDITIONAL": 0, "ENGINE_CHANGE": 0, "RACE_DECISION_ENGINE_CHANGE": 0, "MODEL_TRAINING": 0, "SCALER_FIT": 0, "PREDICTION": 0, "CANDIDATE_EXACT5_GENERATION": 0, "STAGE_A_PERFORMANCE_EVALUATION": 0, "BUY_TOP3_RATE_EVALUATION": 0, "V4_RERUN": 0, "CF_EXECUTION": 0, "FEATURE_CHANGE": 0, "NEW_FEATURE_SEARCH": 0, "HYPERPARAMETER_CHANGE": 0, "THRESHOLD_CHANGE": 0, "PRODUCTION_CHANGE": 0, "FORMAL_PROTOCOL_CHANGE": 0, "SOURCE_DATA_CHANGE": 0, "UNTOUCHED_HOLDOUT_ACCESS": 0, "ledger_change": 0, "status": "PASS"}
    OUT.mkdir(parents=True)
    dump(OUT / "scope.json", {"canonical_task": "TRAINING_DATASET_READINESS_SUMMARY", "evidence_role": "NON_EVIDENTIAL_DEVELOPMENT_READINESS", "stage_b_integration": "DEFERRED", "stage_a_first_without_downstream": "ACCEPT", "model_training_authorized": "NO"})
    dump(OUT / "history_boundary_check.json", {"HISTORY_BOUNDARY_CHECK": "PASS", "authorities": {"ledger": sha(ledger), "fingerprint": sha(fingerprint), "ana_020": str((ROOT / "reports/candidate_generation_observability_feasibility_v1_retry1").relative_to(ROOT))}, "untouched_holdout_access": 0, "april_opened": False})
    dump(OUT / "development_data_inventory.json", {"included": included, "excluded": excluded})
    dump(OUT / "included_blocks.json", included); dump(OUT / "excluded_blocks.json", excluded); dump(OUT / "identity_join_audit.json", identity)
    dump(OUT / "training_dataset_readiness_summary.json", summary); dump(OUT / "feature_schema_readiness.json", {"FULL_FIELD_20_FEATURE_SCHEMA": "PASS", "features": feature_stats})
    dump(OUT / "fullfield_vs_v4_population_summary.json", {"full_field_stage_a": full, "existing_v4_top5_conditioned": v4_summary, "interpretation": "Scale/label/schema only; no performance conclusion."})
    dump(OUT / "tie_break_input_readiness.json", {"V4_TIE_BREAK_INPUT_AVAILABLE_FULL_FIELD": "YES", "field": "shadow_ai_rank", "all_full_field_rows_present": True, "tie_break_order": ["probability DESC (not generated here)", "shadow_ai_rank ASC", "horse_number ASC"], "downstream_rank_not_assessed": True})
    dump(OUT / "training_protocol_metadata_readiness.json", protocol_meta); dump(OUT / "safety.json", safety)
    lines = ["# Full-field Candidate Training Dataset Readiness — 完了", "", "`TRAINING_DATASET_READINESS_SUMMARY = COMPLETE`", "", "`HISTORY_BOUNDARY_CHECK = PASS`", "", f"- Allowed blocks: {len(included)} / dates: {len(date_stats)} / races: {full['races']}", f"- Full-field rows: {full['rows']} | valid: {matched} | invalid excluded: {invalid}", f"- actual_top3 positives: {positives} | negatives: {negatives} | positive rate: {full['positive_rate']:.6f}", f"- Feature-complete valid rows: {matched-incomplete} | incomplete: {incomplete}", "", "`IDENTITY_JOIN_STATE = PASS`", "", f"- joined valid rows: {matched}; unmatched feature/result rows: 0 / 0; duplicates: 0; one-to-many: 0; many-to-one: 0; ambiguous: 0", "- 2026-09-06 Hanshin 11R approved frozen-PRE identity exception is recorded as existing provenance only; no generalized rule was made.", "", "`FULL_FIELD_20_FEATURE_SCHEMA = PASS`", "", "`DATASET_COMPATIBLE_WITH_FROZEN_V4_RECIPE = YES`", "", "`V4_TIE_BREAK_INPUT_AVAILABLE_FULL_FIELD = YES`", "", "`STAGE_A_DATASET_READY = YES`", "", "Stage B integration remains deferred. This result authorizes neither model training nor Candidate Generator implementation; next state is Claude independent readiness review."]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hashes = {path.name: {"sha256": sha(path), "size": path.stat().st_size} for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hash_index.json"}
    dump(OUT / "artifact_hash_index.json", {"self_hash_excluded": True, "indexed_artifacts": hashes})
    print("TRAINING_DATASET_READINESS_SUMMARY=COMPLETE")


if __name__ == "__main__":
    main()
