"""Freeze Current AI, CF_TOP3_RANK_ANCHORED, and the active Daily V4 PRE selections.

This is an additive review runner.  It consumes an already-frozen Current AI
prediction root and never opens Result sources or changes Production behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.cf_top3_rank_anchored_shadow_v1 import (
    freeze_formal_pre_from_prediction,
    select_pre,
    protocol_hash,
)


MODEL_ROOT = ROOT / "reports" / "ml_v4_buy_selection_model_v5"
DATASET_ROOT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v5"
ACTIVATION_RECORD = MODEL_ROOT / "activation_record.json"
ACTIVE_MODEL_VERSION = "V4 Model v5"
ACTIVE_MODEL_SHA256 = "d3b17e3022768690d0b1013ab131b35c5a64aa8e4a816fb3e1349bad95fb87a2"
ACTIVE_DATASET_SHA256 = "15c77e5c13ccbff2255912fa5440e68baf43e0df753218d84420d4bf29da3b3a"
ACTIVE_TRAINING_CUTOFF = "2026-09-13"
ACTIVE_EFFECTIVE_DATE = "2026-09-19"
MODEL_V2_ROOT = ROOT / "reports" / "ml_v4_buy_selection_model_v2"
PROTOCOL_ROOT = ROOT / "reports" / "ml_v4_buy_selection_training_protocol_v2"
MAY_PRE_ROOT = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "pre_retry_v5"
MAY_POST_ROOT = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "post_v1"
MARCH_ROOT = ROOT / "reports" / "march_2026_historical_external_holdout_v1"
CF_ROOT = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"
RESULT_KEYS = {"actual_finish", "finish", "actual_top3", "valid_result", "result", "payout"}
SEMANTIC = [
    "Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability",
    "RaceShape", "PaceStyle", "shadow_ai_rank", "decision_score", "final_score",
    "adjusted_score", "absolute_quality_pass", "relative_advantage_pass",
    "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count",
    "consensus_negative_count", "risk_count", "conflict_count", "race_state",
]
TRANSFORMED = [*SEMANTIC[:-1], "is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"]
GATES = set(SEMANTIC[11:15])


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def assert_result_free(value: object, context: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in RESULT_KEYS:
                raise Stop(f"PRE_RESULT_FIELD_FORBIDDEN:{context}:{key}")
            assert_result_free(child, context)
    elif isinstance(value, list):
        for child in value:
            assert_result_free(child, context)


def verify_index(index_path: Path) -> str:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    entries = payload.get("artifacts") or payload.get("indexed_artifacts")
    if isinstance(entries, dict):
        entries = [{"path": name, "sha256": digest} for name, digest in entries.items()]
    if not isinstance(entries, list):
        raise Stop(f"ARTIFACT_INDEX_UNREADABLE:{index_path}")
    for entry in entries:
        relative = entry.get("path", entry.get("relative_path"))
        expected = entry.get("sha256")
        target = index_path.parent / str(relative)
        if not relative or not expected or not target.is_file() or sha(target) != expected:
            raise Stop(f"ARTIFACT_INDEX_MISMATCH:{index_path}:{relative}")
    return sha(index_path)


def load_active_daily_v4() -> tuple[object, object, dict, dict]:
    """Fail closed unless the Human-approved Daily V4 activation is intact."""
    activation = json.loads(ACTIVATION_RECORD.read_text(encoding="utf-8"))
    expected = {
        "model_version": ACTIVE_MODEL_VERSION,
        "model_sha256": ACTIVE_MODEL_SHA256,
        "dataset_sha256": ACTIVE_DATASET_SHA256,
        "activation_status": "ACTIVE_FOR_DAILY_PRE",
        "activation_effective_date": ACTIVE_EFFECTIVE_DATE,
        "training_cutoff": ACTIVE_TRAINING_CUTOFF,
        "human_approved": True,
        "activation_reason": "WEEKLY_MEETING_LEARNING_CYCLE",
        "prior_daily_version": "V4 Model v3",
    }
    if any(activation.get(key) != value for key, value in expected.items()):
        raise Stop("V5_ACTIVATION_RECORD_MISMATCH")
    if sha(MODEL_ROOT / "model.joblib") != ACTIVE_MODEL_SHA256:
        raise Stop("V5_MODEL_SHA_MISMATCH")
    if sha(DATASET_ROOT / "dataset.csv") != ACTIVE_DATASET_SHA256:
        raise Stop("V5_DATASET_SHA_MISMATCH")
    model_index_sha = verify_index(MODEL_ROOT / "artifact_hash_index.json")
    dataset_index_sha = verify_index(DATASET_ROOT / "artifact_hash_index.json")
    metadata = json.loads((MODEL_ROOT / "model_metadata.json").read_text(encoding="utf-8"))
    if (
        metadata.get("version") != ACTIVE_MODEL_VERSION
        or metadata.get("model_sha256") != ACTIVE_MODEL_SHA256
        or metadata.get("training_end_date") != ACTIVE_TRAINING_CUTOFF
        or metadata.get("training_population") != "ML_V4_TRAIN_DATASET_V5"
    ):
        raise Stop("V5_MODEL_METADATA_MISMATCH")
    reproduction = json.loads((MODEL_ROOT / "deterministic_reproduction.json").read_text(encoding="utf-8"))
    if reproduction.get("status") != "PASS":
        raise Stop("V5_REPRODUCTION_NOT_PASS")
    transform = json.loads((MODEL_ROOT / "feature_transform_schema.json").read_text(encoding="utf-8"))
    if transform.get("transformed_model_input_columns") != TRANSFORMED or transform.get("equal_to_v4") is not True:
        raise Stop("V5_TRANSFORM_ORDER_MISMATCH")
    model = joblib.load(MODEL_ROOT / "model.joblib")
    scaler = joblib.load(MODEL_ROOT / "scaler.joblib")
    if getattr(model, "n_features_in_", None) != 21 or getattr(scaler, "n_features_in_", None) != 21:
        raise Stop("V5_MODEL_FEATURE_COUNT_MISMATCH")
    identity = {
        "model_version": ACTIVE_MODEL_VERSION,
        "model_sha256": ACTIVE_MODEL_SHA256,
        "dataset_sha256": ACTIVE_DATASET_SHA256,
        "training_cutoff": ACTIVE_TRAINING_CUTOFF,
        "activation_effective_date": ACTIVE_EFFECTIVE_DATE,
        "activation_record_sha256": sha(ACTIVATION_RECORD),
    }
    indexes = {"active_v4_model": model_index_sha, "active_v4_dataset": dataset_index_sha}
    return model, scaler, identity, indexes


def boolean(value: object, context: str) -> int:
    if value is True:
        return 1
    if value is False:
        return 0
    raise Stop(f"FEATURE_BOOLEAN_INVALID:{context}")


def safe_rank(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise Stop(f"V4_SAFE_RANK_INVALID:{context}:{value!r}")
    rank = int(value)
    if rank < 1 or float(value) != float(rank):
        raise Stop(f"V4_SAFE_RANK_INVALID:{context}:{value!r}")
    return rank


def vector(horse: dict, trace: dict, state: str, context: str) -> list[float]:
    snapshot = trace.get("evaluator_score_snapshot", {})
    if not isinstance(snapshot, dict):
        raise Stop(f"EVALUATOR_SNAPSHOT_INVALID:{context}")
    values: list[float] = []
    for field in SEMANTIC[:-1]:
        value = snapshot.get(field) if field in {"Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle"} else horse.get(field, trace.get(field))
        if field in GATES:
            values.append(float(boolean(value, f"{context}:{field}")))
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise Stop(f"FEATURE_INVALID:{context}:{field}")
            values.append(float(value))
    values.extend([float(state == "PLAY_UNCONVERGED_4PLUS"), float(state == "SKIP")])
    return values


def parse_identity(race_id: str) -> tuple[str, int]:
    pieces = race_id.split("_")
    try:
        return pieces[-2], int(pieces[-1].removesuffix("R"))
    except Exception as exc:  # pragma: no cover - fail-closed boundary
        raise Stop(f"RACE_ID_PARSE_FAILURE:{race_id}") from exc


def shown(rows: list[dict]) -> list[str]:
    return [f"{int(row['horse_number'])} {row.get('horse_name', '')}".rstrip() for row in rows]


def run(date: str, prediction_root: Path, output_root: Path) -> Path:
    if not (len(date) == 8 and date.isdigit()):
        raise Stop("DATE_FORMAT_INVALID")
    if date < ACTIVE_EFFECTIVE_DATE.replace("-", ""):
        raise Stop(f"ACTIVE_V4_NOT_EFFECTIVE_FOR_DATE:{date}")
    prediction_root = prediction_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"OUTPUT_ROOT_EXISTS:{output_root}")
    prediction_manifest = prediction_root / "prediction_manifest.json"
    if not prediction_manifest.is_file():
        raise Stop("CURRENT_PREDICTION_MANIFEST_MISSING")
    manifest = json.loads(prediction_manifest.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        path = prediction_root / entry["relative_path"]
        if not path.is_file() or sha(path) != entry["sha256"]:
            raise Stop(f"CURRENT_PREDICTION_MANIFEST_MISMATCH:{entry['relative_path']}")

    model, scaler, active_model_identity, active_indexes = load_active_daily_v4()
    authority_indexes = {
        **active_indexes,
        "model_v2": verify_index(MODEL_V2_ROOT / "artifact_hashes.json"),
        "training_protocol_v2": verify_index(PROTOCOL_ROOT / "artifact_hashes.json"),
        "may_pre_v5": verify_index(MAY_PRE_ROOT / "artifact_hashes.json"),
        "may_post_v1": verify_index(MAY_POST_ROOT / "artifact_hashes.json"),
        "march_preregistration": verify_index(MARCH_ROOT / "artifact_hashes.json"),
    }
    activation_path = CF_ROOT / "activation_record.json"
    activation = json.loads(activation_path.read_text(encoding="utf-8"))
    if activation.get("formal_activation_status") != "ACTIVATED" or activation.get("protocol_sha256") != protocol_hash():
        raise Stop("CF_FORMAL_ACTIVATION_INVALID")

    output_root.mkdir(parents=True)
    cf_formal_path = output_root / "cf_formal_prospective_pre.json"
    formal_cf = freeze_formal_pre_from_prediction(
        date=date,
        prediction_root=prediction_root,
        output_path=cf_formal_path,
        activation_record=activation,
    )
    cf_by_race = {record["race_id"]: record for record in formal_cf["eligible_races"]}
    race_index = json.loads((prediction_root / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    current, cf_all, v4, comparison = [], [], [], []
    state_counts = {"PLAY_CONVERGED": 0, "PLAY_UNCONVERGED_4PLUS": 0, "SKIP": 0}
    for item in race_index:
        payload = json.loads((prediction_root / item["artifact"]).read_text(encoding="utf-8"))
        assert_result_free(payload, payload["race_id"])
        race_id = payload["race_id"]
        venue, race_number = parse_identity(race_id)
        ranked = payload["ranked_results"]
        trace = payload.get("buy_gate_trace")
        if not isinstance(trace, dict) or not isinstance(trace.get("race"), dict) or not isinstance(trace.get("horses"), list):
            raise Stop(f"TRACE_REQUIRED:{race_id}")
        state = trace["race"].get("shadow_race_state")
        if state not in state_counts:
            raise Stop(f"RACE_STATE_INVALID:{race_id}:{state}")
        state_counts[state] += 1
        buys = [row for row in ranked if row.get("buy") is True]
        current_record = {
            "date": date, "race_id": race_id, "venue": venue, "race_number": race_number,
            "race_state": state, "evidence_role": "CURRENT_AI_OPERATIONAL_REFERENCE",
            "current_buy_count": len(buys), "current_buy_horses": [{"horse_number": row["horse_number"], "horse_name": row.get("horse_name"), "current_ai_rank": row.get("rank"), "current_buy": True} for row in buys],
        }
        current.append(current_record)
        cf_record = select_pre(date=date, venue=venue, race_number=race_number, race_id=race_id, buy_gate_trace=trace, ranked_results=ranked)
        if cf_record["shadow_eligibility"] == "ELIGIBLE":
            if cf_by_race.get(race_id) != cf_record:
                raise Stop(f"CF_FORMAL_PRE_PARITY_MISMATCH:{race_id}")
        elif race_id in cf_by_race:
            raise Stop(f"CF_FORMAL_PRE_ELIGIBILITY_MISMATCH:{race_id}")
        cf_all.append(cf_record)

        v4_record = {
            "date": date, "race_id": race_id, "venue": venue, "race_number": race_number,
            "race_state": state, "evidence_role": "REFERENCE_SHADOW_ONLY_PENDING_HISTORICAL_GATE",
            **active_model_identity,
            "scope_status": "OUT_OF_SCOPE_RACE_STATE", "current_buy_count": len(buys),
            "top5_probabilities": [], "selected_horses": [], "selected_count": 0,
        }
        if state == "PLAY_CONVERGED":
            trace_by_number = {int(row["horse_number"]): row for row in trace["horses"]}
            if set(trace_by_number) != {int(row["horse_number"]) for row in ranked}:
                raise Stop(f"TRACE_HORSE_SET_MISMATCH:{race_id}")
            rows = [(horse, trace_by_number[int(horse["horse_number"])], vector(horse, trace_by_number[int(horse["horse_number"])], state, f"{race_id}:{horse['horse_number']}")) for horse in payload["top5"]]
            probabilities = model.predict_proba(scaler.transform(np.asarray([row[2] for row in rows], dtype=float)))[:, 1]
            ordered = sorted(
                [{"horse_number": int(horse["horse_number"]), "horse_name": horse.get("horse_name"), "predicted_actual_top3_probability": float(probability), "shadow_ai_rank": safe_rank(trace_row.get("shadow_ai_rank"), f"{race_id}:{horse['horse_number']}")} for (horse, trace_row, _), probability in zip(rows, probabilities, strict=True)],
                key=lambda row: (-row["predicted_actual_top3_probability"], row["shadow_ai_rank"], row["horse_number"]),
            )
            v4_record.update({"scope_status": "ELIGIBLE_PLAY_CONVERGED", "top5_probabilities": ordered, "selected_horses": ordered[:len(buys)], "selected_count": len(buys)})
        v4.append(v4_record)

        current_list = shown(current_record["current_buy_horses"])
        cf_list = shown(cf_record["cf_selected_horses"])
        v4_list = shown(v4_record["selected_horses"])
        current_cf = "NOT_COMPARABLE"
        current_v4 = "NOT_COMPARABLE"
        cf_v4 = "NOT_COMPARABLE"
        label = "NOT_COMPARABLE"
        notes = []
        if state == "PLAY_CONVERGED":
            current_v4 = "CURRENT_V4_MATCH" if current_list == v4_list else "CURRENT_V4_DIVERGENT"
            label = current_v4
            notes.append("CF is NOT_ELIGIBLE outside PLAY_UNCONVERGED_4PLUS.")
        elif state == "PLAY_UNCONVERGED_4PLUS" and cf_record["shadow_eligibility"] == "ELIGIBLE":
            current_cf = "CURRENT_CF_MATCH" if current_list == cf_list else "CURRENT_CF_DIVERGENT"
            label = current_cf
            notes.append(f"{ACTIVE_MODEL_VERSION} is OUT_OF_SCOPE outside PLAY_CONVERGED.")
        else:
            notes.append("Neither CF nor V4 selection authority is applicable for this race state.")
        comparison.append({
            "date": date, "race_id": race_id, "venue": venue, "race_number": race_number,
            "race_state": state, "current_ai_buy": current_list,
            "cf_selected": cf_list if cf_record["shadow_eligibility"] == "ELIGIBLE" else ["NOT_ELIGIBLE"],
            "v4_active_model_selected": v4_list if v4_record["scope_status"] == "ELIGIBLE_PLAY_CONVERGED" else ["OUT_OF_SCOPE"],
            "v4_model_identity": active_model_identity,
            "current_vs_cf": current_cf, "current_vs_v4": current_v4, "cf_vs_v4": cf_v4,
            "comparison_label": label, "evidence_roles": ["CURRENT_AI_OPERATIONAL_REFERENCE", "FORMAL_PROSPECTIVE_SHADOW", "REFERENCE_SHADOW_ONLY_PENDING_HISTORICAL_GATE"],
            "notes": notes,
        })

    write(output_root / "source_manifest.json", {
        "date": date, "source_prediction_root": str(prediction_root.relative_to(ROOT)),
        "source_prediction_manifest_sha256": sha(prediction_manifest),
        "input_manifest_sha256": sha(prediction_root / "input_manifest.json"),
        "result_data_access_count": 0,
    })
    write(output_root / "current_ai_selection_manifest.json", {"date": date, "evidence_role": "CURRENT_AI_OPERATIONAL_REFERENCE", "races": current})
    write(output_root / "cf_selection_manifest.json", {"date": date, "evidence_role": "FORMAL_PROSPECTIVE_SHADOW", "formal_activation_id": activation["formal_activation_id"], "protocol_sha256": protocol_hash(), "all_race_records": cf_all, "formal_eligible_race_count": len(formal_cf["eligible_races"]), "formal_prospective_pre_status": "FROZEN_PENDING_POST"})
    write(output_root / "v4_active_model_selection_manifest.json", {"date": date, "evidence_role": "REFERENCE_SHADOW_ONLY_PENDING_HISTORICAL_GATE", **active_model_identity, "model_artifact_index_sha256": authority_indexes["active_v4_model"], "races": v4})
    write(output_root / "three_system_comparison_summary.json", {"date": date, "race_state_counts": state_counts, "races": comparison})
    write(output_root / "safety_validation.json", {
        "status": "PASS", "result_file_access_count": 0, "finish_access_count": 0, "actual_top3_access_count": 0,
        "buy_top3_rate_calculation_count": 0, "lift_calculation_count": 0, "post_evaluation_count": 0,
        "prediction_execution_count": 1, "model_fit_count": 0, "scaler_fit_count": 0,
        "production_change": 0, "buy_rule_change": 0, "cf_rule_change": 0, "v4_model_change": 0,
    })
    write(output_root / "provenance.json", {"date": date, "generated_at": datetime.now(timezone.utc).isoformat(), "runner_path": str(Path(__file__).relative_to(ROOT)), "runner_sha256": sha(Path(__file__)), "authority_indexes": authority_indexes, "cf_protocol_content_sha256": protocol_hash(), "cf_activation_record_sha256": sha(activation_path), "result_data_access_count": 0})
    write(output_root / "pre_freeze_manifest.json", {
        "final_status": "PROSPECTIVE_PRE_20260829_FROZEN", "date": date,
        "current_ai_race_count": len(current), "current_ai_horse_count": sum(len(json.loads((prediction_root / item["artifact"]).read_text(encoding="utf-8"))["ranked_results"]) for item in race_index),
        "current_buy_count": sum(row["current_buy_count"] for row in current), "race_state_counts": state_counts,
        "cf_formal_prospective_pre_status": "FROZEN_PENDING_POST", "cf_eligible_race_count": len(formal_cf["eligible_races"]),
        "v4_active_daily_pre_status": "FROZEN_ACTIVE_DAILY_V4", "v4_model_identity": active_model_identity, "v4_eligible_race_count": sum(row["scope_status"] == "ELIGIBLE_PLAY_CONVERGED" for row in v4),
        "result_data_access_count": 0, "prediction_execution_count": 1, "performance_evaluation_count": 0,
    })
    lines = ["# 2026-08-29 Three-System PRE Freeze", "", "Result access: 0", ""]
    for row in comparison:
        lines.extend([f"## {date[:4]}-{date[4:6]}-{date[6:]} {row['venue']} {row['race_number']}R", f"- Race State: `{row['race_state']}`", f"- Current AI BUY: {', '.join(row['current_ai_buy']) or 'none'}", f"- CF: {', '.join(row['cf_selected'])}", f"- {ACTIVE_MODEL_VERSION}: {', '.join(row['v4_active_model_selected'])}", f"- Comparison: `{row['comparison_label']}`", ""])
    (output_root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    files = [path for path in output_root.iterdir() if path.is_file() and path.name != "artifact_hashes.json"]
    write(output_root / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": {path.name: sha(path) for path in sorted(files)}})
    return output_root


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--prediction-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.date, args.prediction_root, args.output_root))
