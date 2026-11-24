"""Freeze 2026-09-06 PRE after one Human-approved exact input exception.

This runner never reads Result data.  It consumes the already-frozen Current
prediction and writes selected V4/CF horses only; it deliberately does not
persist a V4 full-Top5 ranking.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from review.cf_top3_rank_anchored_shadow_v1 import freeze_formal_pre_from_prediction, protocol_hash
from review.date_exclusivity_validator_v1 import collect_evidence_dates, validate
from review.prospective_three_system_pre_freeze_v1 import Stop, assert_result_free, parse_identity, safe_rank, vector
from review.target_bulk_prediction_input_adapter_v1 import HUMAN_APPROVED_20260906_EXACT_EXCEPTION


ROOT = Path(__file__).resolve().parents[1]
DATE = "20260906"
CURRENT_ROOT = ROOT / "reports" / "prospective_prediction_20260906_v1"
V4_ROOT = ROOT / "reports" / "v4_model_v3_formal_prospective" / "20260906_pre"
CF_ROOT = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"
CF_PRE = CF_ROOT / "formal_pre_20260906.json"
CF_EXCEPTION = CF_ROOT / "formal_pre_20260906_input_exception_provenance.json"
MODEL_ROOT = ROOT / "reports" / "ml_v4_buy_selection_model_v3"
PROTOCOL_ROOT = ROOT / "reports" / "v4_model_v3_prospective_protocol_v1"
DIAGNOSTIC_ROOT = ROOT / "reports" / "prospective_input_integrity_20260906_v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_index(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("indexed_artifacts") or data.get("artifacts")
    if not isinstance(entries, dict):
        raise Stop(f"ARTIFACT_INDEX_INVALID:{path}")
    for name, digest in entries.items():
        target = path.parent / name
        if not target.is_file() or sha(target) != digest:
            raise Stop(f"ARTIFACT_INDEX_MISMATCH:{path}:{name}")
    return sha(path)


def rows_text(rows: list[dict]) -> str:
    return ", ".join(f"#{int(row['horse_number'])} {row.get('horse_name') or ''}".rstrip() for row in rows) or "なし"


def run() -> tuple[Path, Path]:
    if V4_ROOT.exists() or CF_PRE.exists() or CF_EXCEPTION.exists():
        raise FileExistsError("EXCLUSIVE_CREATE_REQUIRED")
    manifest_path = CURRENT_ROOT / "prediction_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        target = CURRENT_ROOT / entry["relative_path"]
        if not target.is_file() or sha(target) != entry["sha256"]:
            raise Stop(f"CURRENT_PREDICTION_MANIFEST_MISMATCH:{entry['relative_path']}")
    input_manifest = json.loads((CURRENT_ROOT / "input_manifest.json").read_text(encoding="utf-8"))
    exception = input_manifest.get("input_exception")
    if not isinstance(exception, dict) or exception.get("state") != "HUMAN_APPROVED_EXACT_COMPATIBILITY_MAPPING" or exception.get("mapping_count") != 1:
        raise Stop("INPUT_EXCEPTION_PROVENANCE_MISSING")
    diagnostic_index = DIAGNOSTIC_ROOT / "artifact_hash_index.json"
    if sha(diagnostic_index) != "3e4881c48397b94baddb6f46ea07c12e89c74e5c9724c0c9ef4c41df0f164b61":
        raise Stop("INPUT_EXCEPTION_DIAGNOSTIC_HASH_MISMATCH")
    protocol = json.loads((PROTOCOL_ROOT / "protocol.json").read_text(encoding="utf-8"))
    if protocol.get("status") != "HUMAN_APPROVED_AND_FROZEN":
        raise Stop("V4_PROTOCOL_NOT_FROZEN")
    date_exclusivity = validate([DATE], collect_evidence_dates(ROOT))
    if date_exclusivity.get("status") != "PASS":
        raise Stop(f"DATE_EXCLUSIVITY_FAILURE:{date_exclusivity.get('overlap_dates')}")
    model_index = verify_index(MODEL_ROOT / "artifact_hashes.json")
    protocol_index = verify_index(PROTOCOL_ROOT / "artifact_hashes.json")
    activation_path = CF_ROOT / "activation_record.json"
    activation = json.loads(activation_path.read_text(encoding="utf-8"))
    if activation.get("formal_activation_status") != "ACTIVATED" or activation.get("protocol_sha256") != protocol_hash():
        raise Stop("CF_PROTOCOL_OR_ACTIVATION_MISMATCH")
    model, scaler = joblib.load(MODEL_ROOT / "model.joblib"), joblib.load(MODEL_ROOT / "scaler.joblib")
    if getattr(model, "n_features_in_", None) != 21 or getattr(scaler, "n_features_in_", None) != 21:
        raise Stop("V4_MODEL_FEATURE_COUNT_MISMATCH")

    cf_payload = freeze_formal_pre_from_prediction(date=DATE, prediction_root=CURRENT_ROOT, output_path=CF_PRE, activation_record=activation)
    V4_ROOT.mkdir(parents=True)
    index = json.loads((CURRENT_ROOT / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    current_rows, v4_races, diff_rows, review_rows = [], [], [], []
    state_counts = {"PLAY_CONVERGED": 0, "PLAY_UNCONVERGED_4PLUS": 0, "SKIP": 0}
    for item in index:
        payload = json.loads((CURRENT_ROOT / item["artifact"]).read_text(encoding="utf-8"))
        assert_result_free(payload, payload["race_id"])
        race_id = payload["race_id"]
        venue, race_number = parse_identity(race_id)
        trace = payload["buy_gate_trace"]
        state = trace["race"].get("shadow_race_state")
        if state not in state_counts:
            raise Stop(f"RACE_STATE_INVALID:{race_id}:{state}")
        state_counts[state] += 1
        ranked, top5 = payload["ranked_results"], payload["top5"]
        buys = [r for r in ranked if r.get("buy") is True]
        current_rows.append({"race_id": race_id, "venue": venue, "race_number": race_number, "race_state": state, "current_buy_horses": [{"horse_number": r["horse_number"], "horse_name": r.get("horse_name"), "current_ai_rank": r.get("rank")} for r in buys]})
        selected: list[dict] = []
        if state == "PLAY_CONVERGED" and buys:
            trace_by_no = {int(r["horse_number"]): r for r in trace["horses"]}
            if set(trace_by_no) != {int(r["horse_number"]) for r in ranked}:
                raise Stop(f"TRACE_HORSE_SET_MISMATCH:{race_id}")
            vectors = [(r, trace_by_no[int(r["horse_number"])], vector(r, trace_by_no[int(r["horse_number"])], state, f"{race_id}:{r['horse_number']}")) for r in top5]
            probabilities = model.predict_proba(scaler.transform(np.asarray([r[2] for r in vectors], dtype=float)))[:, 1]
            ordered = sorted(({"horse_number": int(h["horse_number"]), "horse_name": h.get("horse_name"), "predicted_actual_top3_probability": float(p), "shadow_ai_rank": safe_rank(t.get("shadow_ai_rank"), f"{race_id}:{h['horse_number']}")} for (h, t, _), p in zip(vectors, probabilities, strict=True)), key=lambda r: (-r["predicted_actual_top3_probability"], r["shadow_ai_rank"], r["horse_number"]))
            selected = ordered[:len(buys)]
            if len(selected) != len(buys):
                raise Stop(f"V4_SAME_VOLUME_VIOLATION:{race_id}")
        v4_races.append({"race_id": race_id, "venue": venue, "race_number": race_number, "race_state": state, "scope_status": "ELIGIBLE" if selected else "NOT_ELIGIBLE_RACE_STATE_OR_CURRENT_BUY_ZERO", "current_buy_count": len(buys), "selected_horses": selected})
        current_set, v4_set = {int(r["horse_number"]) for r in buys}, {int(r["horse_number"]) for r in selected}
        if selected:
            retained, current_out, v4_in = current_set & v4_set, current_set - v4_set, v4_set - current_set
            change = "EXACT_MATCH" if not current_out and not v4_in else ("COMPLETE_REPLACEMENT" if not retained else "PARTIAL_REPLACEMENT")
            diff_rows.append({"race_id": race_id, "venue": venue, "race_number": race_number, "current_buy": sorted(current_set), "v4_selected": sorted(v4_set), "retained": sorted(retained), "current_out": sorted(current_out), "v4_in": sorted(v4_in), "replacement_type": change})
        review_rows.append({"venue": venue, "race_number": race_number, "race_id": race_id, "race_decision": payload.get("race_decision"), "confidence": payload.get("race_confidence"), "race_state": state, "top5": rows_text(top5), "buy": rows_text(buys)})
    eligible = [r for r in v4_races if r["scope_status"] == "ELIGIBLE"]
    if sum(r["current_buy_count"] for r in eligible) != sum(len(r["selected_horses"]) for r in eligible):
        raise Stop("V4_SAME_VOLUME_VIOLATION_TOTAL")
    exception_provenance = {"state": "INPUT_EXCEPTION_20260906_HANSHIN11R=HUMAN_APPROVED_EXACT_COMPATIBILITY_MAPPING", "input_exception_used": True, "input_exception_count": 1, "input_exception_scope": "2026-09-06 / hanshin11R / exact-name-pair-only", "diagnostic_root": str(DIAGNOSTIC_ROOT.relative_to(ROOT)), "diagnostic_artifact_hash_index_sha256": sha(diagnostic_index), "source_prediction_manifest_sha256": sha(manifest_path), "source_sha256": input_manifest["sources"], "generalization_prohibited": True, "result_data_access_count": 0}
    write(V4_ROOT / "exception_provenance.json", exception_provenance)
    write(CF_EXCEPTION, {**exception_provenance, "cf_formal_pre_path": str(CF_PRE.relative_to(ROOT)), "cf_formal_pre_sha256": sha(CF_PRE)})
    write(V4_ROOT / "v4_selection.json", {"schema_version": "V4_MODEL_V3_FORMAL_PROSPECTIVE_PRE_V1", "date": DATE, "evidence_role": "FORMAL_PROSPECTIVE_SHADOW_V4_MODEL_V3", "source_prediction_root": str(CURRENT_ROOT.relative_to(ROOT)), "source_prediction_manifest_sha256": sha(manifest_path), "selection_semantics": "per eligible PLAY_CONVERGED race, select exactly Current BUY count K from frozen Top5 by V4 predicted actual_top3 probability descending, then shadow_ai_rank ascending, then horse_number ascending", "formal_eligible_race_count": len(eligible), "current_selected_count": sum(r["current_buy_count"] for r in eligible), "v4_selected_count": sum(len(r["selected_horses"]) for r in eligible), "races": v4_races, "input_exception_used": True, "result_data_access_count": 0, "status": "FROZEN_PENDING_INDEPENDENT_REVIEW"})
    write(V4_ROOT / "selection_difference.json", {"date": DATE, "races": diff_rows, "counts": {"exact_match": sum(r["replacement_type"] == "EXACT_MATCH" for r in diff_rows), "partial_replacement": sum(r["replacement_type"] == "PARTIAL_REPLACEMENT" for r in diff_rows), "complete_replacement": sum(r["replacement_type"] == "COMPLETE_REPLACEMENT" for r in diff_rows), "retained": sum(len(r["retained"]) for r in diff_rows), "current_out": sum(len(r["current_out"]) for r in diff_rows), "v4_in": sum(len(r["v4_in"]) for r in diff_rows)}})
    write(V4_ROOT / "summary.json", {"date": DATE, "current_races": len(index), "current_horses": sum(i["horse_count"] for i in index), "current_buy_count": sum(len(r["current_buy_horses"]) for r in current_rows), "state_counts": state_counts, "v4_eligible_races": len(eligible), "v4_selected_count": sum(len(r["selected_horses"]) for r in eligible), "cf_eligible_races": len(cf_payload["eligible_races"]), "cf_candidate_pool_count": sum(r["candidate_pool_count"] for r in cf_payload["eligible_races"]), "cf_selected_count": sum(r["cf_selected_count"] for r in cf_payload["eligible_races"]), "input_exception_used": True, "result_data_access_count": 0})
    write(V4_ROOT / "pre_freeze_manifest.json", {"final_status": "V4_MODEL_V3_20260906_PRE=FROZEN", "date": DATE, "current_prediction_authority": str(CURRENT_ROOT.relative_to(ROOT)), "current_prediction_manifest_sha256": sha(manifest_path), "cf_formal_pre_path": str(CF_PRE.relative_to(ROOT)), "cf_formal_pre_sha256": sha(CF_PRE), "input_exception_used": True, "input_exception_count": 1, "v4_full_top5_ranking_freeze_change": 0, "v4_model_v4_status": "NOT_EXECUTED_NOT_AUTHORIZED", "result_data_access_count": 0})
    write(V4_ROOT / "provenance.json", {"date": DATE, "generated_at": datetime.now(timezone.utc).isoformat(), "runner_path": str(Path(__file__).relative_to(ROOT)), "runner_sha256": sha(Path(__file__)), "model_index_sha256": model_index, "model_sha256": sha(MODEL_ROOT / "model.joblib"), "scaler_sha256": sha(MODEL_ROOT / "scaler.joblib"), "protocol_index_sha256": protocol_index, "protocol_sha256": sha(PROTOCOL_ROOT / "protocol.json"), "cf_protocol_sha256": protocol_hash(), "cf_activation_sha256": sha(activation_path), "date_exclusivity": date_exclusivity, "result_data_access_count": 0})
    write(V4_ROOT / "safety.json", {"status": "PASS", "result_access_count": 0, "current_prediction_rerun_after_freeze": 0, "v4_rerun_after_freeze": 0, "cf_reselection_after_freeze": 0, "source_modification_count": 0, "production_change": 0, "model_change": 0, "buy_rule_change": 0, "threshold_change": 0, "protocol_change": 0, "artifact_schema_change": 0, "candidate_generation_change": 0, "ledger_change": 0, "compatibility_mapping_count": 1})
    (CURRENT_ROOT / "pre_race_review").mkdir(exist_ok=True)
    write(CURRENT_ROOT / "pre_race_review" / "summary.json", {"date": DATE, "races": review_rows, "input_exception_used": True, "result_data_access_count": 0})
    (CURRENT_ROOT / "pre_race_review" / "report.md").write_text("# KeibaAI 2026-09-06 PRE\n\n" + "\n".join(f"- {r['venue']} {r['race_number']}R | {r['race_decision']} | Top5: {r['top5']} | BUY: {r['buy']}" for r in review_rows) + "\n", encoding="utf-8")
    files = [p for p in V4_ROOT.iterdir() if p.is_file() and p.name != "artifact_hashes.json"]
    write(V4_ROOT / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": {p.name: sha(p) for p in sorted(files)}})
    return CURRENT_ROOT, V4_ROOT


if __name__ == "__main__":
    current, v4 = run()
    print(json.dumps({"current": str(current), "v4": str(v4)}, ensure_ascii=False))
