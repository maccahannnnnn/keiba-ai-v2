"""Freeze March 2026 Current-AI and V4-v3 PRE comparison artifacts only.

This runner intentionally has no Result-reader imports.  It consumes only the
already preflighted DG/DE/DS inputs and frozen Model-v3 authorities.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import scipy
import sklearn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.date_exclusivity_validator_v1 import collect_evidence_dates, validate
from review.prospective_prediction_runner_v1 import _assert_population, run as current_run
from review.prospective_three_system_pre_freeze_v1 import (
    Stop, TRANSFORMED, assert_result_free, safe_rank, vector,
)
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


OUT = ROOT / "reports" / "march_2026_historical_holdout_pre"
PREFLIGHT = ROOT / "reports" / "march_2026_historical_holdout_preflight_v3"
RAW = ROOT / "data" / "raw" / "prediction_input"
MODEL_ROOT = ROOT / "reports" / "ml_v4_buy_selection_model_v3"
DATASET_ROOT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v2"
DATES = ["20260301", "20260307", "20260308", "20260314", "20260315", "20260321", "20260322", "20260328", "20260329"]
EXPECTED_MODEL_HASHES = {
    "model.joblib": "7f06d9e3ba2f330b6f42d699ee25ea64d83a5287c3b7f72fb0233e14c755312d",
    "scaler.joblib": "800a0d54307e0caafef7b8efd131f5ab60f1d75d1e021dae7627d690187d103c",
    "model_metadata.json": "c401b64a5877ae9b7b0d5448bda9747fd03fc17c36c92d13d1648f0bb4024b46",
    "training_manifest.json": "18a3361bc4789c4e998a4d1acf3432227b52935a4d82f3548bbff77b930b027d",
    "feature_transform_schema.json": "b30a4142b23ed3eecd6a24d516b3e020b213994798f776e2a97f444e60fd9fe2",
}
EXPECTED_DATASET_HASH = "b61994c2a488696a2fcc70f4b4f24e4756e4b6562ca751fa1f30819d30e535e2"
RESULT_KEYS = {"finish", "finishing_position", "result", "actual_top3", "payout", "winner", "success", "failure", "lift"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def rid_parts(race_id: str) -> tuple[str, int]:
    pieces = race_id.split("_")
    if len(pieces) < 3 or not pieces[-1].endswith("R"):
        raise Stop(f"RACE_ID_PARSE_FAILURE:{race_id}")
    return pieces[-2], int(pieces[-1][:-1])


def verify_sources() -> list[dict]:
    expected = json.loads((PREFLIGHT / "source_hashes.json").read_text(encoding="utf-8")).get("sources")
    if not isinstance(expected, list) or len(expected) != 27:
        raise Stop("PREFLIGHT_SOURCE_HASHES_INVALID")
    verified = []
    for item in expected:
        name = item.get("filename")
        path = RAW / str(name)
        actual = {"filename": name, "date": item.get("date"), "source_type": item.get("source_type"),
                  "path": str(path.relative_to(ROOT)), "byte_size": path.stat().st_size if path.is_file() else None,
                  "sha256": sha(path) if path.is_file() else None}
        if not path.is_file() or actual["byte_size"] != item.get("byte_size") or actual["sha256"] != item.get("sha256"):
            raise Stop(f"FROZEN_SOURCE_MISMATCH:{name}")
        verified.append(actual)
    if sorted({x["date"] for x in verified}) != DATES:
        raise Stop("FROZEN_DATE_SET_MISMATCH")
    return verified


def verify_model() -> dict:
    hashes = {name: sha(MODEL_ROOT / name) for name in EXPECTED_MODEL_HASHES}
    for name, expected in EXPECTED_MODEL_HASHES.items():
        if hashes[name] != expected:
            raise Stop(f"FROZEN_MODEL_HASH_MISMATCH:{name}")
    # The frozen Dataset-v2 authority supplied for this phase is the immutable
    # row dataset itself, not its descriptive manifest.
    dataset_file = DATASET_ROOT / "dataset.csv"
    if sha(dataset_file) != EXPECTED_DATASET_HASH:
        raise Stop("FROZEN_DATASET_V2_HASH_MISMATCH")
    transform = json.loads((MODEL_ROOT / "feature_transform_schema.json").read_text(encoding="utf-8"))
    if transform.get("transformed_model_input_columns") != TRANSFORMED:
        raise Stop("V4_TRANSFORM_ORDER_MISMATCH")
    return {"model_v3": hashes, "dataset_v2_sha256": sha(dataset_file)}


def artifact_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file() and path.name != "artifact_hashes.json"}


def scan_result_leakage(value: object, context: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in RESULT_KEYS:
                raise Stop(f"PRE_RESULT_FIELD_FORBIDDEN:{context}:{key}")
            scan_result_leakage(child, context)
    elif isinstance(value, list):
        for child in value:
            scan_result_leakage(child, context)


def runtime() -> dict:
    actual = {"python_executable": sys.executable, "python_version": sys.version, "implementation": platform.python_implementation(),
              "platform": platform.platform(), "numpy": np.__version__, "scikit_learn": sklearn.__version__, "scipy": scipy.__version__, "joblib": joblib.__version__}
    expected = {"numpy": "2.3.5", "scikit_learn": "1.9.0", "scipy": "1.18.1", "joblib": "1.5.3"}
    if any(actual[key] != value for key, value in expected.items()):
        raise Stop("V4_TRAINING_RUNTIME_INCOMPATIBLE")
    actual.update({"expected_libraries": expected, "compatibility": "PASS"})
    return actual


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    started = datetime.now(timezone.utc).isoformat()
    source_rows = verify_sources()
    authority = verify_model()
    run_time = runtime()
    exclusivity = validate(DATES, collect_evidence_dates(ROOT))
    if exclusivity["status"] != "PASS":
        raise Stop("DATE_EXCLUSIVITY_CONFLICT")

    # Load every daily source before prediction.  This checks the same input and
    # population boundary as the production-compatible runner without changing it.
    adapter = TargetBulkPredictionInputAdapterV1()
    bundles, population_dates, registration = {}, [], {}
    source_races = source_horses = 0
    venue_counts: dict[str, int] = {}
    for date in DATES:
        paths = {kind: RAW / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
        bundle = adapter.load(paths["DG"], paths["DE"], paths["DS"])
        if bundle.date != date:
            raise Stop(f"TARGET_DATE_MISMATCH:{bundle.date}:{date}")
        _assert_population(bundle)
        bundles[date] = bundle
        day_races = []
        for race_id, race in sorted(bundle.races.items()):
            venue, number = rid_parts(race_id)
            source_races += 1
            source_horses += len(race.today_entries)
            venue_counts[venue] = venue_counts.get(venue, 0) + 1
            day_races.append({"race_id": race_id, "venue": venue, "race_number": number, "source_horses": len(race.today_entries), "prediction_eligible": True})
            for (number_key, name), identifier in race.target_horse_identifiers.items():
                registration[(race_id, int(number_key), name)] = identifier
        population_dates.append({"date": date, "source_races": len(day_races), "source_horses": sum(x["source_horses"] for x in day_races), "excluded_races": [], "eligible_races": day_races})

    OUT.mkdir(parents=True)
    current_records, v4_records, comparison = [], [], []
    current_roots = {}
    model = joblib.load(MODEL_ROOT / "model.joblib")
    scaler = joblib.load(MODEL_ROOT / "scaler.joblib")
    if getattr(model, "n_features_in_", None) != 21 or getattr(scaler, "n_features_in_", None) != 21:
        raise Stop("V4_MODEL_FEATURE_COUNT_MISMATCH")
    for date in DATES:
        prediction_root = current_run(date, trace=True, output_root=OUT / "current_ai" / date)
        current_roots[date] = prediction_root
        manifest = json.loads((prediction_root / "prediction_manifest.json").read_text(encoding="utf-8"))
        for entry in manifest.get("files", []):
            file = prediction_root / entry["relative_path"]
            if not file.is_file() or sha(file) != entry["sha256"]:
                raise Stop(f"CURRENT_PREDICTION_MANIFEST_MISMATCH:{date}:{entry.get('relative_path')}")
        for item in json.loads((prediction_root / "race_index.json").read_text(encoding="utf-8"))["race_index"]:
            payload = json.loads((prediction_root / item["artifact"]).read_text(encoding="utf-8"))
            assert_result_free(payload, payload["race_id"])
            scan_result_leakage(payload, payload["race_id"])
            race_id, venue, race_number = payload["race_id"], *rid_parts(payload["race_id"])
            trace = payload.get("buy_gate_trace")
            if not isinstance(trace, dict) or not isinstance(trace.get("race"), dict) or not isinstance(trace.get("horses"), list):
                raise Stop(f"TRACE_REQUIRED:{race_id}")
            state = trace["race"].get("shadow_race_state")
            if state not in {"PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"}:
                raise Stop(f"RACE_STATE_INVALID:{race_id}:{state}")
            ranked, top5 = payload["ranked_results"], payload["top5"]
            trace_by_number = {int(row["horse_number"]): row for row in trace["horses"]}
            if set(trace_by_number) != {int(row["horse_number"]) for row in ranked}:
                raise Stop(f"TRACE_HORSE_SET_MISMATCH:{race_id}")
            buys = [row for row in ranked if row.get("buy") is True]
            current_horses = [{"horse_number": int(row["horse_number"]), "horse_name": row.get("horse_name"),
                               "registration_id": registration.get((race_id, int(row["horse_number"]), row.get("horse_name"))),
                               "shadow_ai_rank": safe_rank(trace_by_number[int(row["horse_number"])].get("shadow_ai_rank"), f"{race_id}:{row['horse_number']}"),
                               "current_ai_buy": row.get("buy") is True, "race_state": state,
                               "final_score": row.get("final_score"), "adjusted_score": row.get("adjusted_score"), "decision_score": row.get("decision_score")} for row in ranked]
            if any(row["registration_id"] is None for row in current_horses):
                raise Stop(f"REGISTRATION_ID_UNRESOLVED:{race_id}")
            current_record = {"date": date, "race_id": race_id, "venue": venue, "race_number": race_number, "race_state": state,
                              "current_buy_count": len(buys), "current_buy_horses": [{"horse_number": int(x["horse_number"]), "horse_name": x.get("horse_name"), "registration_id": x["registration_id"]} for x in current_horses if x["current_ai_buy"]],
                              "horses": current_horses, "source_prediction_root": str(prediction_root.relative_to(ROOT)), "source_prediction_manifest_sha256": sha(prediction_root / "prediction_manifest.json")}
            current_records.append(current_record)
            v4_record = {"date": date, "race_id": race_id, "venue": venue, "race_number": race_number, "race_state": state,
                         "scope_status": "OUT_OF_SCOPE_RACE_STATE", "current_buy_count": len(buys), "top5_probabilities": [], "selected_horses": [], "selected_count": 0}
            if state == "PLAY_CONVERGED":
                rows = [(horse, trace_by_number[int(horse["horse_number"])], vector(horse, trace_by_number[int(horse["horse_number"])], state, f"{race_id}:{horse['horse_number']}")) for horse in top5]
                probabilities = model.predict_proba(scaler.transform(np.asarray([x[2] for x in rows], dtype=float)))[:, 1]
                ordered = sorted([{"horse_number": int(horse["horse_number"]), "horse_name": horse.get("horse_name"),
                                   "registration_id": registration.get((race_id, int(horse["horse_number"]), horse.get("horse_name"))),
                                   "predicted_actual_top3_probability": float(prob),
                                   "shadow_ai_rank": safe_rank(trace_row.get("shadow_ai_rank"), f"{race_id}:{horse['horse_number']}")}
                                  for (horse, trace_row, _), prob in zip(rows, probabilities, strict=True)],
                                 key=lambda row: (-row["predicted_actual_top3_probability"], row["shadow_ai_rank"], row["horse_number"]))
                if any(row["registration_id"] is None for row in ordered):
                    raise Stop(f"V4_REGISTRATION_ID_UNRESOLVED:{race_id}")
                v4_record.update({"scope_status": "ELIGIBLE_PLAY_CONVERGED", "top5_probabilities": ordered, "selected_horses": ordered[:len(buys)], "selected_count": len(buys)})
            if v4_record["selected_count"] != len(buys):
                raise Stop(f"SAME_VOLUME_MISMATCH:{race_id}")
            v4_records.append(v4_record)
            current_list = [x["horse_number"] for x in current_record["current_buy_horses"]]
            v4_list = [x["horse_number"] for x in v4_record["selected_horses"]]
            comparison.append({"date": date, "race_id": race_id, "venue": venue, "race_number": race_number, "race_state": state,
                               "current_buy_count": len(buys), "v4_selection_count": v4_record["selected_count"],
                               "current_horse_numbers": current_list, "v4_horse_numbers": v4_list,
                               "comparison": "MATCH" if state == "PLAY_CONVERGED" and current_list == v4_list else ("DIVERGENT" if state == "PLAY_CONVERGED" else "OUT_OF_SCOPE_RACE_STATE")})

    eligible_races, eligible_horses = len(current_records), sum(len(x["horses"]) for x in current_records)
    if eligible_races != source_races or eligible_horses != source_horses:
        raise Stop("FORMAL_POPULATION_IDENTITY_MISMATCH")
    for payload in (current_records, v4_records, comparison):
        scan_result_leakage(payload, "march_pre_output")
    current_buy_count = sum(x["current_buy_count"] for x in current_records)
    state_counts = {state: sum(x["race_state"] == state for x in current_records) for state in ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP")}
    match = sum(x["comparison"] == "MATCH" for x in comparison)
    divergent = sum(x["comparison"] == "DIVERGENT" for x in comparison)
    write(OUT / "source_inventory.json", {"frozen_preflight_root": str(PREFLIGHT.relative_to(ROOT)), "verified_sources": source_rows, "source_count": len(source_rows), "mismatch_count": 0})
    write(OUT / "population_manifest.json", {"population_scope_id": "PREDICTION_BUY_1WIN_PLUS_FLAT", "evidence_role": "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT", "source_dates": DATES, "dates": population_dates, "source_races": source_races, "excluded_races": 0, "eligible_races": eligible_races, "eligible_dates": len(DATES), "source_horses": source_horses, "eligible_horses": eligible_horses, "venue_distribution": venue_counts})
    write(OUT / "exclusions.json", {"excluded_races": [], "count": 0, "rule": "Existing runner population assertion found no newcomer, maiden, jump, or other forbidden-population race."})
    write(OUT / "current_ai_prediction.json", {"evidence_role": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "races": current_records, "race_count": eligible_races, "horse_count": eligible_horses, "buy_count": current_buy_count, "race_state_counts": state_counts})
    write(OUT / "v4_model_v3_prediction.json", {"evidence_role": "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_CANDIDATE", "model_status": "FROZEN_CANDIDATE", "races": v4_records, "scored_horses": sum(len(x["top5_probabilities"]) for x in v4_records), "selected_horses": sum(x["selected_count"] for x in v4_records)})
    write(OUT / "same_volume_selection.json", {"comparator": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "tie_break": ["P(actual_top3) DESC", "safe shadow_ai_rank ASC", "horse_number ASC"], "races": comparison, "selected_count_mismatch": 0, "duplicate_selection": 0, "unresolved_horse": 0, "identical_races": match, "divergent_races": divergent, "out_of_scope_race_state": eligible_races - match - divergent})
    write(OUT / "model_provenance.json", {"authority": authority, "runtime": run_time, "model_status": "FROZEN_CANDIDATE", "dataset_role": "V4_TRAIN_DATASET_V2", "model_fit_count": 0, "scaler_fit_count": 0})
    write(OUT / "date_exclusivity_validation.json", exclusivity)
    write(OUT / "result_leakage_validation.json", {"status": "PASS", "result_data_access_count": 0, "result_field_leakage_count": 0, "actual_top3_field_count": 0, "performance_calculation_count": 0, "historical_gate_evaluation_count": 0})
    safety = {"status": "PASS", "result_data_access_count": 0, "prediction_execution_count": len(DATES), "prediction_rerun_after_freeze_count": 0, "post_evaluation_count": 0, "production_change_count": 0, "buy_rule_change_count": 0, "model_change_count": 0, "adapter_change_count": 0, "cf_change_count": 0, "model_fit_count": 0, "scaler_fit_count": 0}
    write(OUT / "safety.json", safety)
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    write(OUT / "pre_freeze_manifest.json", {"final_status": "MARCH_2026_HISTORICAL_HOLDOUT_PRE_FROZEN_PENDING_INDEPENDENT_REVIEW", "generated_at": started, "completed_at": datetime.now(timezone.utc).isoformat(), "evidence_role": "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT", "purpose": "V4 Model v3 Candidate Advancement Gate", "frozen_dates": DATES, "population_scope_id": "PREDICTION_BUY_1WIN_PLUS_FLAT", "eligible_races": eligible_races, "eligible_horses": eligible_horses, "current_buy_count": current_buy_count, "v4_selected_count": sum(x["selected_count"] for x in v4_records), "frozen_gate": {"eligible_races_min": 20, "eligible_dates_min": 4, "pooled_same_volume_lift_min_pt": 0.0, "evaluation_phase": "POST_ONLY_NOT_EVALUATED"}, "comparator": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "tie_break": ["P(actual_top3) DESC", "safe shadow_ai_rank ASC", "horse_number ASC"], "source_hash_verification": "PASS", "model_hash_verification": "PASS", "date_exclusivity": "PASS", "result_data_access_count": 0, "git_branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(), "git_head": git_head, "runtime": run_time, "claude_independent_pre_review_required": True, "claude_authored_pre_independent_review_manifest_required": True, "march_result_access_authorized": False, "march_post_authorized": False})
    report = ["# March 2026 Historical Holdout PRE Freeze", "", "- Final: `FROZEN_PENDING_INDEPENDENT_REVIEW`", "- Evidence role: `TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT`", f"- Dates/races/horses: `{len(DATES)}/{eligible_races}/{eligible_horses}`", f"- Current AI BUY: `{current_buy_count}`", f"- V4 selected: `{sum(x['selected_count'] for x in v4_records)}`", f"- Result access: `0`", f"- Date exclusivity overlap: `{exclusivity['overlap_count']}`", "", "POST is prohibited pending Claude Code's independent PRE review and its Claude-authored manifest."]
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    write(OUT / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": artifact_hashes(OUT)})
    # Verify exactly what the freeze index claims, without generating a second prediction.
    index = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
    if any(sha(OUT / rel) != digest for rel, digest in index.items()):
        raise Stop("FREEZE_ARTIFACT_HASH_MISMATCH")
    print("MARCH_2026_HISTORICAL_HOLDOUT_PRE=FROZEN_PENDING_INDEPENDENT_REVIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
