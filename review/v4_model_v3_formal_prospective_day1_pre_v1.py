"""Freeze one formal Current AI / CF / V4-v3 prospective PRE day.

This additive runner is deliberately PRE-only.  It reads DG/DE/DS and already
frozen model/protocol artifacts, never Result sources, and never mutates the
Production decision path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from review.cf_top3_rank_anchored_shadow_v1 import (
    freeze_formal_pre_from_prediction,
    protocol_hash as cf_protocol_hash,
    select_pre,
)
from review.date_exclusivity_validator_v1 import collect_evidence_dates, validate
from review.prospective_prediction_runner_v1 import run as run_current_prediction
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.prospective_three_system_pre_freeze_v1 import (
    SEMANTIC,
    Stop,
    assert_result_free,
    parse_identity,
    safe_rank,
    vector,
)
from review.v4_model_v3_prospective_validator_v1 import ROLE, same_volume


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "prediction_input"
MODEL_ROOT = ROOT / "reports" / "ml_v4_buy_selection_model_v3"
PROTOCOL_ROOT = ROOT / "reports" / "v4_model_v3_prospective_protocol_v1"
CF_ROOT = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"
EXPECTED_TRANSFORM = [*SEMANTIC[:-1], "is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_index(path: Path) -> str:
    index = json.loads(path.read_text(encoding="utf-8"))
    entries = index.get("indexed_artifacts")
    if not isinstance(entries, dict):
        raise Stop(f"AUTHORITY_INDEX_INVALID:{path}")
    for name, expected in entries.items():
        target = path.parent / name
        if not target.is_file() or sha(target) != expected:
            raise Stop(f"AUTHORITY_INDEX_MISMATCH:{path}:{name}")
    return sha(path)


def displayed(rows: list[dict]) -> str:
    return ", ".join(f"#{int(row['horse_number'])} {row.get('horse_name') or 'N/A'}" for row in rows) or "NONE"


def chosen_numbers(rows: list[dict]) -> set[int]:
    return {int(row["horse_number"]) for row in rows}


def _preflight(date: str) -> tuple[dict, object]:
    paths = {kind: RAW / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
    bundle = TargetBulkPredictionInputAdapterV1().load(paths["DG"], paths["DE"], paths["DS"])
    if bundle.date != date:
        raise Stop(f"SOURCE_DATE_MISMATCH:{bundle.date}:{date}")
    source = {
        kind: {
            "path": str(item.path.relative_to(ROOT)), "sha256": item.sha256,
            "byte_size": item.path.stat().st_size, "encoding": item.encoding,
            "delimiter": item.delimiter, "header": item.header,
            "row_count": item.row_count, "column_count": item.width,
        }
        for kind, item in bundle.sources.items()
    }
    return {
        "status": "PASS", "date": date, "sources": source,
        "race_count": len(bundle.races), "horse_count": bundle.preflight["horse_count"],
        "adapter_preflight": bundle.preflight,
        "dg_de_race_identity": "PASS", "de_ds_horse_identity": "PASS",
        "duplicate_count": 0, "ambiguous_count": 0, "unexpected_source_count": 0,
        "result_data_access_count": 0,
    }, bundle


def _authorities(date: str) -> dict:
    protocol_path = PROTOCOL_ROOT / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("status") != "HUMAN_APPROVED_AND_FROZEN" or protocol.get("evidence_role") != ROLE:
        raise Stop("V4_PROTOCOL_NOT_FROZEN_OR_APPROVED")
    transform = json.loads((MODEL_ROOT / "feature_transform_schema.json").read_text(encoding="utf-8"))
    if transform.get("transformed_model_input_columns") != EXPECTED_TRANSFORM:
        raise Stop("V4_TRANSFORM_ORDER_MISMATCH")
    activation_path = CF_ROOT / "activation_record.json"
    activation = json.loads(activation_path.read_text(encoding="utf-8"))
    if activation.get("formal_activation_status") != "ACTIVATED" or activation.get("protocol_sha256") != cf_protocol_hash():
        raise Stop("CF_FORMAL_ACTIVATION_INVALID")
    exclusivity = validate([date], collect_evidence_dates(ROOT))
    if exclusivity.get("status") != "PASS":
        raise Stop(f"DATE_EXCLUSIVITY_FAILURE:{exclusivity.get('overlap_dates')}")
    model_index_sha = verify_index(MODEL_ROOT / "artifact_hashes.json")
    protocol_index_sha = verify_index(PROTOCOL_ROOT / "artifact_hashes.json")
    return {
        "model_index_sha256": model_index_sha,
        "model_sha256": sha(MODEL_ROOT / "model.joblib"),
        "scaler_sha256": sha(MODEL_ROOT / "scaler.joblib"),
        "feature_transform_schema_sha256": sha(MODEL_ROOT / "feature_transform_schema.json"),
        "formal_protocol_sha256": sha(protocol_path),
        "formal_protocol_index_sha256": protocol_index_sha,
        "formal_protocol_version": protocol.get("protocol_version"),
        "evidence_role": ROLE,
        "cf_activation_record_sha256": sha(activation_path),
        "cf_activation": activation,
        "date_exclusivity": exclusivity,
    }


def _v4_record(*, date: str, payload: dict, model, scaler) -> dict:
    race_id = payload["race_id"]
    venue, race_number = parse_identity(race_id)
    trace = payload.get("buy_gate_trace")
    if not isinstance(trace, dict) or not isinstance(trace.get("race"), dict) or not isinstance(trace.get("horses"), list):
        raise Stop(f"TRACE_REQUIRED:{race_id}")
    state = trace["race"].get("shadow_race_state")
    buys = [row for row in payload["ranked_results"] if row.get("buy") is True]
    record = {
        "date": date, "race_id": race_id, "venue": venue, "race_number": race_number,
        "race_state": state, "current_buy_count": len(buys),
        "formal_eligibility": "PLAY_CONVERGED AND Current BUY >= 1",
        "scope_status": "OUT_OF_SCOPE", "top5_probabilities": [], "selected_horses": [], "selected_count": 0,
    }
    if state != "PLAY_CONVERGED" or not buys:
        record["scope_status"] = "NOT_ELIGIBLE_RACE_STATE_OR_CURRENT_BUY_ZERO"
        return record
    trace_by_number = {int(row["horse_number"]): row for row in trace["horses"]}
    ranked_numbers = {int(row["horse_number"]) for row in payload["ranked_results"]}
    if set(trace_by_number) != ranked_numbers:
        raise Stop(f"TRACE_HORSE_SET_MISMATCH:{race_id}")
    rows = []
    for horse in payload["top5"]:
        number = int(horse["horse_number"])
        trace_row = trace_by_number.get(number)
        if trace_row is None:
            raise Stop(f"TOP5_TRACE_HORSE_MISSING:{race_id}:{number}")
        rows.append((horse, trace_row, vector(horse, trace_row, state, f"{race_id}:{number}")))
    probabilities = model.predict_proba(scaler.transform(np.asarray([row[2] for row in rows], dtype=float)))[:, 1]
    ordered = sorted(
        [{"horse_number": int(horse["horse_number"]), "horse_name": horse.get("horse_name"),
          "predicted_actual_top3_probability": float(probability),
          "shadow_ai_rank": safe_rank(trace_row.get("shadow_ai_rank"), f"{race_id}:{horse['horse_number']}"),
          "current_buy": bool(horse.get("buy"))}
         for (horse, trace_row, _), probability in zip(rows, probabilities, strict=True)],
        key=lambda row: (-row["predicted_actual_top3_probability"], row["shadow_ai_rank"], row["horse_number"]),
    )
    selected = ordered[:len(buys)]
    if len(selected) != len(buys):
        raise Stop(f"V4_CANDIDATE_SHORTAGE:{race_id}")
    record.update({"scope_status": "ELIGIBLE", "top5_probabilities": ordered, "selected_horses": selected, "selected_count": len(selected)})
    return record


def _human_report(date: str, current: list[dict], cf_all: list[dict], v4: list[dict], comparison: list[dict], agreement: dict) -> str:
    by_id_cf = {row["race_id"]: row for row in cf_all}
    by_id_v4 = {row["race_id"]: row for row in v4}
    lines = [f"# 2026-08-30 Formal Prospective PRE Selection Summary", "", "- Result data access: `0`", "- Current BUY is operational; CF/V4 are shadow selections only.", "", "## Table A — Race-by-Race Comparison", "", "| Venue | R | Race ID | State | Current BUY | CF Formal Prospective Selection | V4 Model v3 Formal Prospective Selection |", "|---|---:|---|---|---|---|---|"]
    for row in current:
        cf = by_id_cf[row["race_id"]]; v4row = by_id_v4[row["race_id"]]
        cf_text = displayed(cf["cf_selected_horses"]) if cf["shadow_eligibility"] == "ELIGIBLE" else "NONE"
        v4_text = displayed(v4row["selected_horses"]) if v4row["scope_status"] == "ELIGIBLE" else "NONE"
        lines.append(f"| {row['venue']} | {row['race_number']} | {row['race_id']} | {row['race_state']} | {displayed(row['current_buy_horses'])} | {cf_text} | {v4_text} |")
    lines.extend(["", "## Table B — Selection Difference", "", "| Venue | R | Common Current/CF/V4 | Current only | CF only | V4 only |", "|---|---:|---|---|---|---|"])
    for row in comparison:
        lines.append(f"| {row['venue']} | {row['race_number']} | {row['common']} | {row['current_only']} | {row['cf_only']} | {row['v4_only']} |")
    lines.extend(["", "## CF 2026-08-30 Formal Prospective Selections", ""])
    for venue in sorted({row["venue"] for row in current}):
        lines.extend([f"### {venue}"])
        selected = [row for row in cf_all if row["venue"] == venue and row["shadow_eligibility"] == "ELIGIBLE"]
        if not selected:
            lines.append("- NONE")
        for row in selected:
            details = "; ".join(f"#{horse['horse_number']} {horse['horse_name']} (CF rank={horse['shadow_ai_rank']}, pool position={index + 1}, reason=shadow_ai_rank ascending)" for index, horse in enumerate(row["cf_selected_horses"]))
            lines.append(f"- {row['race_number']}R: {details}")
        lines.append("")
    lines.extend(["## V4 Model v3 2026-08-30 Formal Prospective Selections", ""])
    for venue in sorted({row["venue"] for row in current}):
        lines.append(f"### {venue}")
        selected = [row for row in v4 if row["venue"] == venue and row["scope_status"] == "ELIGIBLE"]
        if not selected:
            lines.append("- NONE")
        for row in selected:
            details = ", ".join(f"#{horse['horse_number']} {horse['horse_name']} (p={horse['predicted_actual_top3_probability']:.3f} / shadow_ai_rank={horse['shadow_ai_rank']})" for horse in row["selected_horses"])
            lines.append(f"- {row['race_number']}R: {details}")
        lines.append("")
    lines.extend(["## Current BUY", ""])
    for venue in sorted({row["venue"] for row in current}):
        lines.append(f"### {venue}")
        items = [row for row in current if row["venue"] == venue and row["current_buy_horses"]]
        if not items:
            lines.append("- NONE")
        for row in items:
            lines.append(f"- {row['race_number']}R: {displayed(row['current_buy_horses'])}")
        lines.append("")
    lines.extend(["## Agreement Summary", ""])
    for key, value in agreement.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def run(date: str) -> tuple[Path, Path]:
    if len(date) != 8 or not date.isdigit():
        raise Stop("DATE_FORMAT_INVALID")
    output_root = ROOT / "reports" / "v4_model_v3_formal_prospective" / f"{date}_pre"
    current_root = ROOT / "reports" / f"prospective_prediction_{date}_v1"
    cf_path = CF_ROOT / f"formal_pre_{date}.json"
    if output_root.exists() or current_root.exists() or cf_path.exists():
        raise FileExistsError("EXCLUSIVE_CREATE_REQUIRED")
    source_preflight, _ = _preflight(date)
    authorities = _authorities(date)
    model = joblib.load(MODEL_ROOT / "model.joblib")
    scaler = joblib.load(MODEL_ROOT / "scaler.joblib")
    if getattr(model, "n_features_in_", None) != 21 or getattr(scaler, "n_features_in_", None) != 21:
        raise Stop("V4_MODEL_FEATURE_COUNT_MISMATCH")

    current_root = run_current_prediction(date, trace=True, output_root=current_root)
    manifest = json.loads((current_root / "prediction_manifest.json").read_text(encoding="utf-8"))
    for item in manifest.get("files", []):
        target = current_root / item["relative_path"]
        if not target.is_file() or sha(target) != item["sha256"]:
            raise Stop(f"CURRENT_PREDICTION_MANIFEST_MISMATCH:{item['relative_path']}")

    output_root.mkdir(parents=True)
    activation = authorities["cf_activation"]
    cf_payload = freeze_formal_pre_from_prediction(date=date, prediction_root=current_root, output_path=cf_path, activation_record=activation)
    cf_by_id = {row["race_id"]: row for row in cf_payload["eligible_races"]}
    index = json.loads((current_root / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    current, cf_all, v4, comparisons = [], [], [], []
    state_counts: dict[str, int] = {"PLAY_CONVERGED": 0, "PLAY_UNCONVERGED_4PLUS": 0, "SKIP": 0}
    v4_current_by_race, v4_selected_by_race = {}, {}
    for item in index:
        payload = json.loads((current_root / item["artifact"]).read_text(encoding="utf-8"))
        assert_result_free(payload, payload["race_id"])
        race_id = payload["race_id"]
        venue, race_number = parse_identity(race_id)
        trace = payload["buy_gate_trace"]
        state = trace["race"].get("shadow_race_state")
        if state not in state_counts:
            raise Stop(f"RACE_STATE_INVALID:{race_id}:{state}")
        state_counts[state] += 1
        buys = [row for row in payload["ranked_results"] if row.get("buy") is True]
        current_row = {"date": date, "race_id": race_id, "venue": venue, "race_number": race_number, "race_state": state, "current_buy_count": len(buys), "current_buy_horses": [{"horse_number": row["horse_number"], "horse_name": row.get("horse_name"), "current_ai_rank": row.get("rank"), "current_buy": True} for row in buys]}
        current.append(current_row)
        cf_record = select_pre(date=date, venue=venue, race_number=race_number, race_id=race_id, buy_gate_trace=trace, ranked_results=payload["ranked_results"])
        if cf_record["shadow_eligibility"] == "ELIGIBLE":
            if cf_by_id.get(race_id) != cf_record:
                raise Stop(f"CF_PRE_PARITY_MISMATCH:{race_id}")
        elif race_id in cf_by_id:
            raise Stop(f"CF_PRE_ELIGIBILITY_MISMATCH:{race_id}")
        cf_all.append(cf_record)
        v4_record = _v4_record(date=date, payload=payload, model=model, scaler=scaler)
        v4.append(v4_record)
        if v4_record["scope_status"] == "ELIGIBLE":
            v4_current_by_race[race_id] = current_row["current_buy_horses"]
            v4_selected_by_race[race_id] = v4_record["selected_horses"]
        current_set, cf_set, v4_set = chosen_numbers(current_row["current_buy_horses"]), chosen_numbers(cf_record["cf_selected_horses"]), chosen_numbers(v4_record["selected_horses"])
        lookup = {int(row["horse_number"]): row.get("horse_name") for row in payload["ranked_results"]}
        as_text = lambda values: ", ".join(f"#{number} {lookup.get(number) or 'N/A'}" for number in sorted(values)) or "NONE"
        comparisons.append({"date": date, "race_id": race_id, "venue": venue, "race_number": race_number, "race_state": state, "common": as_text(current_set & cf_set & v4_set), "current_only": as_text(current_set - cf_set - v4_set), "cf_only": as_text(cf_set - current_set - v4_set), "v4_only": as_text(v4_set - current_set - cf_set), "current_set": sorted(current_set), "cf_set": sorted(cf_set), "v4_set": sorted(v4_set)})
    same_volume(v4_current_by_race, v4_selected_by_race)
    agreement = {
        "all_three_identical_races": sum(row["current_set"] == row["cf_set"] == row["v4_set"] for row in comparisons),
        "current_and_cf_only_identical_races": sum(row["current_set"] == row["cf_set"] != row["v4_set"] for row in comparisons),
        "current_and_v4_only_identical_races": sum(row["current_set"] == row["v4_set"] != row["cf_set"] for row in comparisons),
        "cf_and_v4_only_identical_races": sum(row["cf_set"] == row["v4_set"] != row["current_set"] for row in comparisons),
        "all_three_different_races": sum(row["current_set"] != row["cf_set"] and row["current_set"] != row["v4_set"] and row["cf_set"] != row["v4_set"] for row in comparisons),
    }
    current_horses = sum(item["horse_count"] for item in index)
    phase_a = {"status": "PASS", "checks": {"source_integrity": "PASS", "evaluated_population": "PASS", "model_sha": "PASS", "scaler_sha": "PASS", "protocol_sha": "PASS", "comparator": "PASS", "same_volume": "PASS", "prediction_schema": "PASS", "result_access_count": 0, "evidence_role": "PASS", "date_exclusivity": "PASS", "freeze_integrity": "PASS"}, "formal_eligibility": "PLAY_CONVERGED AND Current BUY >= 1", "comparator": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "selection_order": ["predicted P(actual_top3) DESC", "safe shadow_ai_rank ASC", "horse_number ASC"]}
    write(output_root / "source_preflight.json", source_preflight)
    write(output_root / "current_prediction.json", {"date": date, "source_prediction_root": str(current_root.relative_to(ROOT)), "source_prediction_manifest_sha256": sha(current_root / "prediction_manifest.json"), "races": current})
    write(output_root / "v4_prediction.json", {"date": date, "evidence_role": ROLE, "races": v4})
    write(output_root / "same_volume_selection.json", {"date": date, "comparator": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "formal_eligible_races": len(v4_current_by_race), "current_same_volume_count": sum(len(rows) for rows in v4_current_by_race.values()), "v4_selected_count": sum(len(rows) for rows in v4_selected_by_race.values()), "per_race": [{"race_id": race_id, "current_buy_count": len(v4_current_by_race[race_id]), "v4_selected_count": len(v4_selected_by_race[race_id])} for race_id in sorted(v4_current_by_race)]})
    write(output_root / "phase_a_validation.json", phase_a)
    write(output_root / "date_exclusivity_validation.json", authorities["date_exclusivity"])
    write(output_root / "cf_formal_prospective_reference.json", {"date": date, "formal_pre_path": str(cf_path.relative_to(ROOT)), "formal_pre_sha256": sha(cf_path), "formal_eligible_race_count": len(cf_payload["eligible_races"]), "candidate_pool_size": sum(row["candidate_pool_count"] for row in cf_payload["eligible_races"]), "selected_horse_count": sum(row["cf_selected_count"] for row in cf_payload["eligible_races"]), "status": "FROZEN_PENDING_POST"})
    write(output_root / "evidence_ledger_pre_candidate.json", {"date": date, "evidence_role": ROLE, "status": "FROZEN_PRE_CANDIDATE_NOT_POST_EVIDENCE", "post_evidence_included": False, "hits": None, "rate": None, "lift": None, "gate_result": "NOT_EVALUATED", "excluded_evidence": ["March Historical", "May OOS", "April", "2026-08-29 V4 Reference", "CF evidence"]})
    write(output_root / "selection_difference.json", {"date": date, "races": comparisons, "agreement_summary": agreement})
    write(output_root / "provenance.json", {"date": date, "generated_at": datetime.now(timezone.utc).isoformat(), "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "runner_path": str(Path(__file__).relative_to(ROOT)), "runner_sha256": sha(Path(__file__)), "model_and_protocol_authority": {key: value for key, value in authorities.items() if key not in {"cf_activation", "date_exclusivity"}}, "current_prediction_root": str(current_root.relative_to(ROOT)), "current_prediction_manifest_sha256": sha(current_root / "prediction_manifest.json"), "result_data_access_count": 0})
    write(output_root / "pre_freeze_manifest.json", {"final_status": f"PRE_{date} = FROZEN", "v4_status": f"V4_MODEL_V3_FORMAL_PROSPECTIVE_PRE_{date} = FROZEN_PENDING_INDEPENDENT_REVIEW", "date": date, "current_ai_race_count": len(current), "current_ai_horse_count": current_horses, "current_buy_count": sum(row["current_buy_count"] for row in current), "state_counts": state_counts, "cf_status": "FROZEN_PENDING_POST", "cf_eligible_races": len(cf_payload["eligible_races"]), "v4_eligible_races": len(v4_current_by_race), "v4_current_same_volume_count": sum(len(rows) for rows in v4_current_by_race.values()), "v4_selected_count": sum(len(rows) for rows in v4_selected_by_race.values()), "result_data_access_count": 0, "prediction_execution_count": 1, "performance_evaluation_count": 0, "claude_independent_v4_pre_review_required": True, "v4_post_authorized": False, "result_access_for_v4_post_authorized": False})
    write(output_root / "safety.json", {"status": "PASS", "result_data_access_count": 0, "post_execution_count": 0, "performance_calculation_count": 0, "production_change_count": 0, "current_buy_rule_change_count": 0, "v4_model_change_count": 0, "cf_protocol_change_count": 0, "formal_v4_protocol_change_count": 0, "march_artifact_change_count": 0, "may_artifact_change_count": 0})
    (output_root / "human_readable_selection_summary.md").write_text(_human_report(date, current, cf_all, v4, comparisons, agreement), encoding="utf-8")
    files = [path for path in output_root.iterdir() if path.is_file() and path.name != "artifact_hashes.json"]
    write(output_root / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": {path.name: sha(path) for path in sorted(files)}})
    return current_root, output_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    current_root, formal_root = run(args.date)
    print(json.dumps({"current_prediction_root": str(current_root), "formal_v4_root": str(formal_root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
