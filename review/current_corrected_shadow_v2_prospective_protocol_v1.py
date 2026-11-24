"""Pure, additive protocol primitives for CURRENT_CORRECTED_SHADOW_V2.

Nothing in this module is imported by the production prediction path.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "current_corrected_shadow_v2_prospective_protocol_v1.json"
FREEZE = ROOT / "reports" / "current_corrected_shadow_v2_freeze_v6.json"
FREEZE_INDEX = ROOT / "reports" / "current_corrected_shadow_v2_freeze_v6_artifacts" / "artifact_hashes.json"
RUNTIME = (
    ROOT / "review" / "current_corrected_shadow_v2.py",
    ROOT / "review" / "current_corrected_shadow_v2_runner.py",
    ROOT / "review" / "current_corrected_shadow_v2_replay.py",
    ROOT / "review" / "current_corrected_shadow_v2_aggregator.py",
)

TC_SOURCE = ROOT / "review" / "track_condition_semantic_shadow_prospective_pre.py"

class Stop(RuntimeError):
    pass

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL.read_text(encoding="utf-8"))

def validate_protocol(protocol: dict[str, Any]) -> None:
    required = {"protocol_name", "protocol_version", "role", "model", "production_authorization", "execution_authorization", "minimum_evidence", "primary", "secondary", "verdict_order", "evidence_boundary", "freeze_v6_pins"}
    if set(required) - set(protocol):
        raise Stop("STOP_PROTOCOL_INCOMPLETE")
    if protocol["minimum_evidence"] != {"counted_races": 60, "counted_dates": 12}:
        raise Stop("STOP_PROTOCOL_MINIMUM")
    auth = protocol["execution_authorization"]
    if protocol["production_authorization"] is not False or auth != {"mode": "EXTERNAL_HUMAN_AUTHORIZATION_ARTIFACT", "required": True, "protocol_itself_grants_execution_authorization": False, "artifact_path": "reports/current_corrected_shadow_v2_prospective_execution_authorization_v1.json"}:
        raise Stop("STOP_PROTOCOL_AUTHORIZATION")
    if protocol["primary"].get("selection") != "corrected_shadow.rank ascending top k; k=Frozen Current BUY count":
        raise Stop("STOP_PRIMARY_SEMANTICS")

def verify_freeze_pins(protocol: dict[str, Any]) -> None:
    pins = protocol["freeze_v6_pins"]
    required = {"freeze_record_sha256": sha(FREEZE), "freeze_index_sha256": sha(FREEZE_INDEX)}
    required.update({path.name + "_sha256": sha(path) for path in RUNTIME})
    if any(pins.get(key) != value for key, value in required.items()):
        raise Stop("DATE_LEVEL_STOP:FREEZE_V6_PIN_MISMATCH")
    if pins.get("central_jra_meeting_week_id_module_sha256") != sha(TC_SOURCE):
        raise Stop("DATE_LEVEL_STOP:TC_BLOCK_PIN_MISMATCH")

def central_jra_meeting_week_id(date: str) -> str:
    """Verify TrackCondition source before its dynamic import and execution."""
    protocol=load_protocol(); verify_freeze_pins(protocol)
    spec=importlib.util.spec_from_file_location("_verified_tc_block",TC_SOURCE)
    if spec is None or spec.loader is None: raise Stop("DATE_LEVEL_STOP:TC_BLOCK_IMPORT")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.central_jra_meeting_week_id(date)

def validate_start(target_date: str, protocol: dict[str, Any], *, authorization_date: str | None = None) -> None:
    freeze_date = protocol["protocol_freeze_date"]
    if authorization_date is None:
        raise Stop("FORMAL_EXECUTION_NOT_AUTHORIZED")
    if target_date <= max(freeze_date, authorization_date):
        raise Stop("DATE_LEVEL_STOP:G1_START_BOUNDARY")

def verify_authoritative_freeze(freeze_root: Path) -> dict[str, Any]:
    """Verify a reviewed freeze root through its non-self-referential sidecar."""
    if not freeze_root.is_dir() or not freeze_root.name.startswith("current_corrected_shadow_v2_prospective_protocol_v1_freeze_"):
        raise Stop("STOP_EXECUTION_AUTHORIZATION_INVALID")
    record, root_manifest, sidecar, index = (freeze_root / "freeze_record.json", freeze_root / "root_manifest.json", freeze_root / "root_manifest.sha256", freeze_root / "artifact_hashes.json")
    if not all(path.is_file() for path in (record, root_manifest, sidecar, index)):
        raise Stop("STOP_EXECUTION_AUTHORIZATION_INVALID")
    if sidecar.read_text(encoding="utf-8").strip() != sha(root_manifest):
        raise Stop("STOP_EXECUTION_AUTHORIZATION_INVALID")
    manifest=json.loads(root_manifest.read_text(encoding="utf-8"))
    if manifest.get("freeze_record_sha256") != sha(record) or manifest.get("artifact_hashes_sha256") != sha(index):
        raise Stop("STOP_EXECUTION_AUTHORIZATION_INVALID")
    indexed=json.loads(index.read_text(encoding="utf-8")).get("indexed_artifacts",{})
    for name, expected in indexed.items():
        path=freeze_root/name
        if not path.is_file() or sha(path)!=expected: raise Stop("STOP_EXECUTION_AUTHORIZATION_INVALID")
    return {"path":str(freeze_root.relative_to(ROOT)).replace("\\","/"),"freeze_record_sha256":sha(record),"root_manifest_sha256":sha(root_manifest)}

def validate_authorization_artifact(target_date: str, protocol: dict[str, Any], artifact_path: Path, authoritative_protocol_freeze: Path | None = None) -> dict[str, Any]:
    if not artifact_path.is_file(): raise Stop("FORMAL_EXECUTION_NOT_AUTHORIZED")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    required = {"authorization_id", "protocol_name", "protocol_version", "protocol_sha256", "authoritative_freeze_path", "freeze_record_sha256", "root_manifest_sha256", "v2_freeze_identity", "v2_freeze_sha256", "human_decision", "authorization_status", "authorized_at", "authorization_date", "production_authorization", "earliest_formal_target_date", "evidence_boundary", "retroactive_backfill_allowed", "artifact_provenance", "independent_review_status", "external_sha256_record", "human_action_artifact_store_schema", "human_action_artifact_store_version", "human_action_artifact_root"}
    if set(required) - set(artifact): raise Stop("STOP_EXECUTION_AUTHORIZATION_INVALID")
    sidecar=artifact_path.with_name(artifact_path.name+".sha256")
    if not sidecar.is_file() or sidecar.read_text(encoding="utf-8").strip()!=sha(artifact_path): raise Stop("STOP_EXECUTION_AUTHORIZATION_INVALID")
    freeze_root=ROOT/artifact["authoritative_freeze_path"]
    freeze=verify_authoritative_freeze(freeze_root)
    checks = [artifact["authorization_status"] == "AUTHORIZED", artifact["human_decision"] == "authorized", artifact["protocol_name"] == protocol["protocol_name"], artifact["protocol_version"] == protocol["protocol_version"], artifact["protocol_sha256"] == sha(PROTOCOL), artifact["freeze_record_sha256"] == freeze["freeze_record_sha256"], artifact["root_manifest_sha256"] == freeze["root_manifest_sha256"], artifact["v2_freeze_identity"] == "CURRENT_CORRECTED_SHADOW_V2_FREEZE_V6", artifact["v2_freeze_sha256"] == sha(FREEZE), artifact["production_authorization"] is False, artifact["retroactive_backfill_allowed"] is False, artifact["independent_review_status"] == "ACCEPT", artifact["human_action_artifact_store_schema"] == "CURRENT_CORRECTED_SHADOW_V2_HUMAN_ACTION_ARTIFACT_STORE", artifact["human_action_artifact_store_version"] == "v1", isinstance(artifact["human_action_artifact_root"], str) and bool(artifact["human_action_artifact_root"].strip())]
    if not all(checks): raise Stop("STOP_EXECUTION_AUTHORIZATION_INVALID")
    try: validate_start(target_date, protocol, authorization_date=artifact["authorization_date"])
    except Stop as exc: raise Stop("STOP_EXECUTION_AUTHORIZATION_INVALID" if str(exc) != "FORMAL_EXECUTION_NOT_AUTHORIZED" else str(exc)) from exc
    if target_date < artifact["earliest_formal_target_date"]: raise Stop("STOP_EXECUTION_AUTHORIZATION_INVALID")
    return artifact

def current_buy_count(rows: list[dict[str, Any]]) -> int:
    return sum(bool(row.get("buy")) for row in rows)

def select_primary(corrected_rows: list[dict[str, Any]], target_k: int) -> tuple[list[dict[str, Any]], bool]:
    ordered = sorted(corrected_rows, key=lambda row: int(row["corrected_shadow"]["rank"]))
    selected = ordered[:target_k]
    boundary_tie = bool(target_k and len(ordered) > target_k and selected[-1]["corrected_shadow"]["adjusted_score"] == ordered[target_k]["corrected_shadow"]["adjusted_score"])
    return selected, boundary_tie

def select_natural(corrected_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in corrected_rows if row["corrected_shadow"]["buy"] is True]

def validate_pre_rows(current_rows: list[dict[str, Any]], corrected_rows: list[dict[str, Any]], target_k: int) -> None:
    current_numbers = {int(row["horse_number"]) for row in current_rows}
    corrected_numbers = {int(row["horse_number"]) for row in corrected_rows}
    if current_numbers != corrected_numbers:
        raise Stop("DATE_LEVEL_STOP:HORSE_SET_INTEGRITY")
    ranks = sorted(int(row["corrected_shadow"]["rank"]) for row in corrected_rows)
    if ranks != list(range(1, len(corrected_rows) + 1)):
        raise Stop("DATE_LEVEL_STOP:RANK_INTEGRITY")
    selected, _ = select_primary(corrected_rows, target_k)
    if len(selected) != target_k:
        raise Stop("DATE_LEVEL_STOP:PRIMARY_SHORTFALL")

def normalize_current_buy(row: dict[str, Any]) -> bool:
    return bool(row.get("buy"))

def normalize_control_buy(row: dict[str, Any]) -> bool:
    return bool(row.get("buy_v1_rc1_buy"))

def control_observables(control: dict[str, Any], frozen: dict[str, Any]) -> dict[str, int]:
    left = {int(row["horse_number"]): row for row in control["ranked_results"]}
    right = {int(row["horse_number"]): row for row in frozen["ranked_results"]}
    values = {"horse_set": int(set(left) != set(right)), "buy_set": 0, "race_state": 0, "rank": 0, "adjusted_score": 0, "final_score": 0, "decision": 0, "decision_score": 0}
    if set(left) != set(right):
        return values
    values["buy_set"] = int({number for number,row in left.items() if normalize_control_buy(row)} != {number for number,row in right.items() if normalize_current_buy(row)})
    for key in ("rank", "adjusted_score", "final_score", "decision", "decision_score"):
        values[key] = sum(left[number].get(key) != right[number].get(key) for number in left)
    values["race_state"] = int({row.get("buy_v1_rc1_race_state") for row in left.values()} != {row.get("buy_v1_rc1_race_state") for row in right.values()})
    return values

def control_field_availability(control: dict[str, Any], frozen: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Return availability/non-null/mismatch counts; absent fields never pass."""
    left = {int(row["horse_number"]): row for row in control["ranked_results"]}
    right = {int(row["horse_number"]): row for row in frozen["ranked_results"]}
    fields = ("horse_set", "buy_set", "race_state", "rank", "adjusted_score", "final_score", "decision", "decision_score")
    report: dict[str, dict[str, int]] = {}
    for field in fields:
        if field == "horse_set":
            report[field] = {"available_count": 1, "non_null_count": 1, "mismatch_count": int(set(left) != set(right))}
        elif field == "buy_set":
            report[field] = {"available_count": len(left) + len(right), "non_null_count": len(left) + len(right), "mismatch_count": int({n for n,r in left.items() if normalize_control_buy(r)} != {n for n,r in right.items() if normalize_current_buy(r)})}
        elif field == "race_state":
            lv = [r.get("buy_v1_rc1_race_state") for r in left.values()]
            rv = [r.get("buy_v1_rc1_race_state") for r in right.values()]
            available = sum(v is not None for v in lv + rv)
            report[field] = {"available_count": available, "non_null_count": available, "mismatch_count": int(set(lv) != set(rv))}
        else:
            pairs = [(left[n].get(field), right[n].get(field)) for n in left.keys() & right.keys()]
            available = sum(a is not None and b is not None for a,b in pairs)
            report[field] = {"available_count": available, "non_null_count": available, "mismatch_count": sum(a != b for a,b in pairs if a is not None and b is not None)}
    return report

def aggregate_arm(rows: list[dict[str, Any]], arm: str) -> dict[str, int]:
    selected = [row for row in rows if row.get(arm + "_selected")]
    valid = [row for row in selected if row.get("valid_result") is True]
    return {"selected_n_raw": len(selected), "invalid_n": len(selected) - len(valid), "valid_selected_n": len(valid), "hits": sum(bool(row.get("actual_top3")) for row in valid)}

def verdict(counted_races: int, counted_dates: int, total_shortfall: int, pooled_lift_pt: float) -> str:
    if counted_races < 60 or counted_dates < 12:
        return "HOLD:EVIDENCE_QUANTITY"
    if total_shortfall > 0:
        return "HOLD_VOLUME_CONFOUNDED"
    return "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_REJECT" if pooled_lift_pt < 0 else "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_ACCEPT"

def diagnostic_flags(date_lifts: list[float], contributions: list[tuple[str, int]], overall_lift: float) -> set[str]:
    flags = set()
    if any(value < 0 for value in date_lifts): flags.add("TEMPORAL_FRAGILITY_FLAG")
    remove_n = (len(date_lifts) + 2) // 3
    if remove_n and contributions and sum(value for _, value in sorted(contributions, key=lambda item: item[1], reverse=True)[remove_n:]) < 0:
        flags.add("TEMPORAL_CONCENTRATION_FLAG")
    return flags

def validate_cumulative(ledger: dict[str, Any]) -> None:
    dates = [entry["date"] for entry in ledger.get("entries", [])]
    if len(dates) != len(set(dates)): raise Stop("STOP_CUMULATIVE_DUPLICATE_DATE")
    if any(entry.get("formal") is not True or entry.get("backfill") is True or entry.get("no_pre") is True or entry.get("calibration_role") or entry.get("historical_role") for entry in ledger.get("entries", [])):
        raise Stop("STOP_CUMULATIVE_EVIDENCE_BOUNDARY")
    if ledger.get("terminal_verdict") and ledger.get("terminal_verdict") not in {"CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_ACCEPT", "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_REJECT"}:
        raise Stop("STOP_CUMULATIVE_TERMINAL")
