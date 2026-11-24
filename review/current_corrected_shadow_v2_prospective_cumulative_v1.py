"""Single-entry immutable-event Formal CUMULATE authority for protocol v1."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from review.current_corrected_shadow_v2_prospective_protocol_v1 import ROOT, Stop, load_protocol, sha, validate_authorization_artifact, verdict
from review.current_corrected_shadow_v2_prospective_runtime_binding_v1 import FORMAL_RUNTIME_MODULES
from review.current_corrected_shadow_v2_prospective_formal_pre_v1 import validate_runtime_freeze_binding
from review.current_corrected_shadow_v2_prospective_post_v1 import REQUIRED_POST_ARTIFACTS
from review.current_corrected_shadow_v2_prospective_state_v1 import CumulativeStateTransitions, PROTOCOL_IDENTITY, StateReader
from review.current_corrected_shadow_v2_prospective_cumulative_fold_v1 import fold_cumulative_evidence
from review.current_corrected_shadow_v2_prospective_governance_v1 import GovernanceLedger, require_governance_allows_operation, _now_utc
from review.current_corrected_shadow_v2_prospective_human_artifact_store_v1 import HumanArtifactStoreBinding


def _read(path: Path, stop: str) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: raise Stop(stop) from exc
    if not isinstance(value, dict): raise Stop(stop)
    return value


def verify_frozen_post(post_root: Path, *, target_date: str | None = None) -> dict[str, Any]:
    if not post_root.is_dir() or not all((post_root / name).is_file() for name in REQUIRED_POST_ARTIFACTS): raise Stop("STOP_POST_FREEZE_INTEGRITY_FAILURE")
    index, manifest = _read(post_root / "artifact_hashes.json", "STOP_POST_FREEZE_INTEGRITY_FAILURE"), _read(post_root / "post_manifest.json", "STOP_POST_FREEZE_INTEGRITY_FAILURE")
    indexed = index.get("indexed_artifacts")
    actual = {str(path.relative_to(post_root)).replace("\\", "/") for path in post_root.rglob("*") if path.is_file()} - {"artifact_hashes.json", "post_manifest.json"}
    if not isinstance(indexed, dict) or set(indexed) != actual or any(not isinstance(value, str) or sha(post_root / name) != value for name, value in indexed.items()): raise Stop("STOP_POST_FREEZE_INTEGRITY_FAILURE")
    if manifest.get("status") != "POST_FROZEN" or manifest.get("protocol_identity") != PROTOCOL_IDENTITY or manifest.get("artifact_hashes_sha256") != sha(post_root / "artifact_hashes.json"): raise Stop("STOP_POST_FREEZE_INTEGRITY_FAILURE")
    if target_date is not None and manifest.get("target_date") != target_date: raise Stop("STOP_POST_FREEZE_INTEGRITY_FAILURE")
    return {"post_root": str(post_root), "post_manifest_sha256": sha(post_root / "post_manifest.json"), "post_index_sha256": sha(post_root / "artifact_hashes.json")}


def _post_entry(post_root: Path, *, target_date: str) -> dict[str, Any]:
    identity = verify_frozen_post(post_root, target_date=target_date)
    pre, summary = _read(post_root / "frozen_pre_reference.json", "STOP_POST_FREEZE_INTEGRITY_FAILURE"), _read(post_root / "summary.json", "STOP_POST_FREEZE_INTEGRITY_FAILURE")
    primary, secondary = _read(post_root / "primary_post.json", "STOP_POST_FREEZE_INTEGRITY_FAILURE"), _read(post_root / "natural_post.json", "STOP_POST_FREEZE_INTEGRITY_FAILURE")
    races = _read(post_root / "race_metrics.json", "STOP_POST_FREEZE_INTEGRITY_FAILURE").get("races")
    if not isinstance(races, list) or not isinstance(summary.get("block_id"), str): raise Stop("STOP_POST_FREEZE_INTEGRITY_FAILURE")
    return {"target_date": target_date, "post_path": str(post_root), "post_manifest_sha256": identity["post_manifest_sha256"], "pre_path": pre.get("pre_path"), "pre_manifest_sha256": pre.get("pre_manifest_sha256"), "block_id": summary["block_id"], "races": races, "primary": primary, "secondary": secondary}


def _event_paths(event_root: Path) -> list[Path]:
    root = event_root / "cumulative_events"
    if not root.exists(): return []
    if not root.is_dir(): raise Stop("STOP_CUMULATIVE_EVENT_INTEGRITY")
    return sorted(root.glob("*.json"))


def _load_events(event_root: Path) -> list[dict[str, Any]]:
    events = [_read(path, "STOP_CUMULATIVE_EVENT_INTEGRITY") for path in _event_paths(event_root)]
    dates, posts = [event.get("target_date") for event in events], [event.get("post_manifest_sha256") for event in events]
    if len(dates) != len(set(dates)) or len(posts) != len(set(posts)): raise Stop("STOP_CUMULATIVE_DUPLICATE_DATE")
    return events


def _totals(events: list[dict[str, Any]]) -> dict[str, Any]:
    folded=fold_cumulative_evidence(events)
    return {"counted_races":folded["counted_races"],"counted_dates":folded["counted_dates"],"blocks":folded["blocks"],"comparator":folded["comparator"],"primary":folded["primary"],"shortfall":folded["shortfall"],"pooled_lift_pt":folded["pooled_lift_pt"]}


def _append_event(target_date: str, *, event_root: Path, entry: dict[str, Any]) -> Path:
    root = event_root / "cumulative_events"; root.mkdir(parents=True, exist_ok=True); path = root / f"{target_date}.json"
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(entry, handle, ensure_ascii=False, indent=2); handle.write("\n")
    except FileExistsError as exc: raise Stop("STOP_CUMULATIVE_DUPLICATE_DATE") from exc
    return path


def _run_cumulate(target_date: str, *, event_root: Path, governance_ledger_head_sha256: str | None = None) -> Path:
    reader = StateReader(event_root)
    if reader.get_date_state(target_date) != "POST_FROZEN": raise Stop("STOP_CUMULATE_REQUIRES_POST_FROZEN")
    for root in sorted(path for path in event_root.iterdir() if path.is_dir() and path.name.isdigit()):
        if root.name < target_date and reader.get_date_state(root.name) in {"PRE_FROZEN", "POST_FROZEN"}:
            raise Stop("STOP_EARLIER_FORMAL_DATE_PENDING")
    history = reader.event_history(target_date); post_event = next(item for item in history if item.get("event") == "POST_FROZEN")
    governance_head = governance_ledger_head_sha256 if governance_ledger_head_sha256 is not None else (history[0].get("metadata", {}).get("governance_ledger_head_sha256") if history else None)
    entry = _post_entry(Path(post_event["post_path"]), target_date=target_date); events = _load_events(event_root)
    canonical_event = event_root / "cumulative_events" / f"{target_date}.json"
    if canonical_event.is_file():
        # Idempotent crash recovery: an event may exist while the date-state
        # transition did not.  It must still be exactly bound to this frozen POST.
        existing = _read(canonical_event, "STOP_CUMULATIVE_EVENT_INTEGRITY")
        expected_rows = [row for row in entry["races"] if row.get("counted") is True]
        if existing.get("target_date") != target_date or existing.get("post_manifest_sha256") != entry["post_manifest_sha256"] or existing.get("pre_path") != entry["pre_path"] or existing.get("counted_race_rows") != expected_rows:
            raise Stop("STOP_CUMULATIVE_EVENT_INTEGRITY")
        CumulativeStateTransitions(event_root).mark_cumulated_from_event(target_date, event_path=canonical_event, governance_ledger_head_sha256=governance_head)
        return canonical_event
    existing_dates = [str(event.get("target_date")) for event in events]
    if existing_dates and target_date <= max(existing_dates):
        raise Stop("STOP_NON_MONOTONIC_CUMULATIVE_DATE")
    if any(event.get("post_manifest_sha256") == entry["post_manifest_sha256"] for event in events): raise Stop("STOP_CUMULATIVE_DUPLICATE_POST")
    before_fold = fold_cumulative_evidence(events)
    before = "NOT_STARTED" if not events else before_fold["protocol_state_after"]
    if before_fold["evaluation_point_consumed"]: raise Stop("STOP_EVALUATION_POINT_CONSUMED")
    counted = [race for race in entry["races"] if race.get("counted") is True]; totals = _totals(events + [{"counted_race_rows": counted}])
    folded=fold_cumulative_evidence(events + [{"counted_race_rows": counted}])
    full = {**entry, "event_type": "FORMAL_CUMULATE", "created_at": datetime.now(timezone.utc).isoformat(), "governance_ledger_head_sha256": governance_head, "counted_races": len(counted), "counted_race_rows": counted, "comparator": folded["comparator"], "primary": folded["primary"], "secondary": folded["secondary"], "shortfall": folded["shortfall"], "accumulated_races_after_append": folded["counted_races"], "accumulated_dates_after_append": folded["counted_dates"], "accumulated_blocks_after_append": folded["accumulated_blocks"], "pooled_lift_pt": folded["pooled_lift_pt"], "protocol_state_before": before, "protocol_state_after": folded["protocol_state_after"], "evaluation_point_consumed": folded["evaluation_point_consumed"], "terminal_verdict": folded["terminal_verdict"], "candidate_label": folded["candidate_label"]}
    path = _append_event(target_date, event_root=event_root, entry=full); CumulativeStateTransitions(event_root).mark_cumulated_from_event(target_date, event_path=path, governance_ledger_head_sha256=governance_head)
    return path


def run_formal_cumulate(target_date: str) -> Path:
    """The one public CUMULATE authority; no caller-supplied POST or metrics."""
    protocol = load_protocol(); auth_path = ROOT / protocol["execution_authorization"]["artifact_path"]
    authorization = validate_authorization_artifact(target_date, protocol, auth_path)
    validate_runtime_freeze_binding(ROOT / authorization["authoritative_freeze_path"], runtime_modules=FORMAL_RUNTIME_MODULES)
    state_root = ROOT / "reports" / "current_corrected_shadow_v2_prospective_state_v1"; history = StateReader(state_root).event_history(target_date)
    head = history[0].get("metadata", {}).get("governance_ledger_head_sha256") if history else None
    authorization_sha = sha(auth_path)
    ledger = GovernanceLedger(ROOT / "reports" / "current_corrected_shadow_v2_prospective_governance_v1", authorization["authorization_id"], authorization_sha, HumanArtifactStoreBinding.from_authorization(authorization, authorization_sha))
    view = require_governance_allows_operation(ledger=ledger, target_date=target_date, operation="CUMULATE", state_reader=StateReader(state_root), as_of=_now_utc(), claim_head=head)
    return _run_cumulate(target_date, event_root=state_root, governance_ledger_head_sha256=view["current_ledger_head_sha256"])


def _run_formal_cumulate_for_test(target_date: str, *, event_root: Path, governance_ledger_head_sha256: str | None = None) -> Path:
    return _run_cumulate(target_date, event_root=event_root, governance_ledger_head_sha256=governance_ledger_head_sha256)


def append_from_frozen_post(*_args: Any, **_kwargs: Any) -> None:
    raise Stop("STOP_LEGACY_MUTABLE_CUMULATE_DISABLED")


def evaluate_once(*_args: Any, **_kwargs: Any) -> None:
    raise Stop("STOP_LEGACY_MUTABLE_CUMULATE_DISABLED")
