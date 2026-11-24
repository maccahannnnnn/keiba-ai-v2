"""Single public Formal PRE authority for the V2 prospective protocol.

The real entrypoint is deliberately authorization-gated.  The private
test-only harness accepts injected roots and a synthetic pipeline so that the
state machine can be proven without any Formal execution or freeze.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from review.current_corrected_shadow_v2_prospective_protocol_v1 import (
    PROTOCOL, ROOT, Stop, load_protocol, sha, validate_authorization_artifact,
    validate_start,
)
from review.current_corrected_shadow_v2_prospective_validators_v1 import validate_pre_start
from review.current_corrected_shadow_v2_prospective_state_v1 import PreStateTransitions, canonical_date
from review.current_corrected_shadow_v2_prospective_runtime_binding_v1 import FORMAL_RUNTIME_MODULES, validate_import_closure
from review.current_corrected_shadow_v2_prospective_governance_v1 import GovernanceLedger, require_governance_allows_operation, _now_utc
from review.current_corrected_shadow_v2_prospective_human_artifact_store_v1 import HumanArtifactStoreBinding

RUNTIME_MODULES = FORMAL_RUNTIME_MODULES  # compatibility read-only alias; no second list.


def _indexed_sha(index: dict[str, Any], module: Path) -> str | None:
    items = index.get("indexed_artifacts", index.get("artifacts", {}))
    if not isinstance(items, dict):
        return None
    relative = str(module.relative_to(ROOT)).replace("\\", "/")
    candidates = (relative, f"snapshot/{relative}", f"static/{relative}")
    for key in candidates:
        value = items.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict) and isinstance(value.get("sha256"), str):
            return value["sha256"]
    return None


def validate_runtime_freeze_binding(freeze_root: Path, *, runtime_modules: tuple[Path, ...] = RUNTIME_MODULES) -> None:
    """Fail closed unless every directly used module equals the authorized index."""
    index_path = freeze_root / "artifact_hashes.json"
    if not index_path.is_file():
        raise Stop("STOP_RUNTIME_NOT_EQUAL_TO_AUTHORIZED_FREEZE")
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Stop("STOP_RUNTIME_NOT_EQUAL_TO_AUTHORIZED_FREEZE") from exc
    validate_import_closure(bound_modules=runtime_modules)
    for module in runtime_modules:
        expected = _indexed_sha(index, module)
        if expected is None or not module.is_file() or sha(module) != expected:
            raise Stop("STOP_RUNTIME_NOT_EQUAL_TO_AUTHORIZED_FREEZE")


@dataclass(frozen=True)
class _PipelineResult:
    pre_directory: Path


def _run(target_date: str, transitions: PreStateTransitions, *, preflight: Callable[[], dict[str, Any]], pipeline: Callable[[str, str], _PipelineResult]) -> _PipelineResult:
    """Shared implementation: all preflight occurs before the exclusive claim."""
    target_date = canonical_date(target_date)
    preflight_metadata = preflight()  # Any error here must not consume a date.
    attempt_id = preflight_metadata["attempt_id"]
    claim_path = transitions.claim_date(target_date, attempt_id=attempt_id, metadata=preflight_metadata)
    try:
        claim_event = json.loads(claim_path.read_text(encoding="utf-8"))
        result = pipeline(claim_event["recorded_at"], attempt_id)
        transitions.mark_pre_frozen_from_artifact(target_date, attempt_id=attempt_id, pre_directory=result.pre_directory)
        return result
    except Exception as exc:
        try:
            transitions.mark_no_pre(target_date, reason=type(exc).__name__)
        except Exception:
            # ATTEMPT_STARTED remains the irreversible retry block by design.
            pass
        raise Stop("DATE_LEVEL_STOP:NO_PRE") from exc


def run_formal_pre(target_date: str, dg: Path, de: Path, ds: Path, output_root: Path, *, authorization_path: Path | None = None) -> _PipelineResult:
    """The only public Formal PRE entrypoint.

    Stage 1 intentionally provides no executable production pipeline: there is
    no final freeze and no Human authorization artifact.  If both later exist,
    Stage 2/3 will attach the already-reviewed PRE pipeline behind this exact
    entrypoint without changing its claim ordering.
    """
    protocol = load_protocol()
    validate_pre_start(protocol)
    authorization_path = authorization_path or ROOT / protocol["execution_authorization"]["artifact_path"]
    authorization = validate_authorization_artifact(target_date, protocol, authorization_path)
    freeze_root = ROOT / authorization["authoritative_freeze_path"]
    validate_runtime_freeze_binding(freeze_root)
    validate_start(target_date, protocol, authorization_date=authorization["authorization_date"])
    target_date = canonical_date(target_date)
    now = _now_utc()
    authorization_sha = sha(authorization_path)
    binding = HumanArtifactStoreBinding.from_authorization(authorization, authorization_sha)
    ledger = GovernanceLedger(ROOT / "reports" / "current_corrected_shadow_v2_prospective_governance_v1", authorization["authorization_id"], authorization_sha, binding)
    view = require_governance_allows_operation(ledger=ledger, target_date=target_date, operation="PRE", state_reader=PreStateTransitions().reader, as_of=now)

    def preflight() -> dict[str, Any]:
        return {"attempt_id": f"{target_date}:formal", "authorization_id": authorization["authorization_id"], "authorization_artifact_sha256": authorization_sha, "freeze_root_manifest_sha256": authorization["root_manifest_sha256"], "governance_ledger_head_sha256": view["current_ledger_head_sha256"]}

    from review.current_corrected_shadow_v2_prospective_pre_v1 import _legacy_pipeline_not_state_authority

    def pipeline(attempt_started_at: str, attempt_id: str) -> _PipelineResult:
        root = _legacy_pipeline_not_state_authority(
            target_date, dg, de, ds, output_root,
            authorization_path=authorization_path,
            authoritative_protocol_freeze=freeze_root,
            attempt_started_at=attempt_started_at,
            attempt_id=attempt_id,
            governance_ledger_head_sha256=view["current_ledger_head_sha256"],
        )
        return _PipelineResult(root)

    return _run(target_date, PreStateTransitions(), preflight=preflight, pipeline=pipeline)


def _run_formal_pre_for_test(target_date: str, *, event_root: Path, preflight: Callable[[], dict[str, Any]], pipeline: Callable[[str, str], _PipelineResult]) -> _PipelineResult:
    """Private injection point for TECHNICAL_TEST_ONLY state-machine checks."""
    return _run(target_date, PreStateTransitions(event_root), preflight=preflight, pipeline=pipeline)
