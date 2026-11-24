"""M1--M3 technical-only tests; every state/artifact root is isolated."""
from __future__ import annotations

import hashlib
import json
import shutil
from contextlib import contextmanager
from pathlib import Path

from review.current_corrected_shadow_v2_prospective_formal_pre_v1 import (
    RUNTIME_MODULES, _PipelineResult, _run_formal_pre_for_test,
    validate_runtime_freeze_binding,
)
from review.current_corrected_shadow_v2_prospective_protocol_v1 import Stop
from review.current_corrected_shadow_v2_prospective_runtime_binding_v1 import validate_import_closure
from review.current_corrected_shadow_v2_prospective_state_v1 import (
    PreStateTransitions, REQUIRED_PRE_ARTIFACTS, StateReader, validate_transition,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def _sandbox():
    root = Path.cwd() / "reports" / "_ccsv2_stage1_technical_test_sandbox"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        if root.exists():
            shutil.rmtree(root)


def _preflight() -> dict:
    return {"attempt_id": "technical-only", "authorization_id": "fixture-auth", "result_data_access_count": 0}


def _write_pre(root: Path, *, target_date: str = "20260926", attempt_id: str = "technical-only", authorization_id: str = "fixture-auth", missing: str | None = None, extra: bool = False, bad_hash: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_PRE_ARTIFACTS - {"artifact_hashes.json", "pre_freeze_manifest.json"}:
        if name == missing:
            continue
        value = "# report\n" if name.endswith(".md") else {"target_date": target_date, "attempt_id": attempt_id, "protocol_identity": "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1", "authorization_id": authorization_id, "result_data_access_count": 0}
        (root / name).write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    indexed = {str(path.relative_to(root)).replace("\\", "/"): _sha(path) for path in root.rglob("*") if path.is_file()}
    if bad_hash and indexed:
        indexed[next(iter(indexed))] = "0" * 64
    (root / "artifact_hashes.json").write_text(json.dumps({"indexed_artifacts": indexed}), encoding="utf-8")
    if missing != "pre_freeze_manifest.json":
        (root / "pre_freeze_manifest.json").write_text(json.dumps({"status": "PRE_FROZEN", "target_date": target_date, "attempt_id": attempt_id, "protocol_identity": "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1", "authorization_id": authorization_id, "result_data_access_count": 0, "artifact_hashes_sha256": _sha(root / "artifact_hashes.json")}), encoding="utf-8")
    if extra:
        (root / "unexpected.json").write_text("{}", encoding="utf-8")
    return root


def test_m3_protocol_and_date_transition_tables():
    for before, after in (("UNCLAIMED", "ATTEMPT_STARTED"), ("ATTEMPT_STARTED", "PRE_FROZEN"), ("ATTEMPT_STARTED", "NO_PRE"), ("PRE_FROZEN", "POST_FROZEN")):
        validate_transition(before, after)
    for before, after in (("NO_PRE", "ATTEMPT_STARTED"), ("PRE_FROZEN", "ATTEMPT_STARTED"), ("UNCLAIMED", "PRE_FROZEN")):
        try: validate_transition(before, after)
        except Stop: pass
        else: assert False
    allowed = (("NOT_STARTED", "RUNNING", False), ("RUNNING", "SUSPENDED", False), ("RUNNING", "HOLD_VOLUME_CONFOUNDED", False), ("HOLD:EVIDENCE_QUANTITY", "RUNNING", False), ("SUSPENDED", "RUNNING", True))
    denied = (("NOT_STARTED", "SUSPENDED", False), ("SUSPENDED", "RUNNING", False), ("HOLD_VOLUME_CONFOUNDED", "RUNNING", False), ("HOLD_VOLUME_CONFOUNDED", "ACCEPT", False), ("ACCEPT", "RUNNING", False), ("ACCEPT", "REJECT", False), ("REJECT", "RUNNING", False))
    for before, after, resume in allowed:
        validate_transition(before, after, protocol_level=True, human_resume=resume)
    for before, after, resume in denied:
        try: validate_transition(before, after, protocol_level=True, human_resume=resume)
        except Stop: pass
        else: assert False, (before, after)


def test_m1_import_closure_detects_missing_binding():
    validate_import_closure()
    reduced = tuple(path for path in RUNTIME_MODULES if path.name != "target_bulk_prediction_input_adapter_v1.py")
    try: validate_import_closure(bound_modules=reduced)
    except Stop as exc: assert "target_bulk_prediction_input_adapter_v1.py" in str(exc)
    else: assert False


def test_m1_runtime_binding_behavioral_matrix_claims_nothing():
    with _sandbox() as root:
        index = {"indexed_artifacts": {str(path.relative_to(Path.cwd())).replace("\\", "/"): _sha(path) for path in RUNTIME_MODULES}}
        freeze = root / "freeze"; freeze.mkdir(); (freeze / "artifact_hashes.json").write_text(json.dumps(index), encoding="utf-8")
        validate_runtime_freeze_binding(freeze)
        for module_name in ("current_corrected_shadow_v2_prospective_pre_v1.py", "target_bulk_prediction_input_adapter_v1.py", "current_corrected_shadow_v2_prospective_state_v1.py", "current_corrected_shadow_v2_prospective_validators_v1.py"):
            changed = {"indexed_artifacts": dict(index["indexed_artifacts"])}
            key = next(k for k in changed["indexed_artifacts"] if k.endswith(module_name))
            changed["indexed_artifacts"][key] = "0" * 64
            (freeze / "artifact_hashes.json").write_text(json.dumps(changed), encoding="utf-8")
            transitions = PreStateTransitions(root / module_name)
            try:
                _run_formal_pre_for_test("20261002", event_root=root / module_name, preflight=lambda: (validate_runtime_freeze_binding(freeze), _preflight())[1], pipeline=lambda *_: _PipelineResult(root))
            except Stop as exc: assert str(exc) == "STOP_RUNTIME_NOT_EQUAL_TO_AUTHORIZED_FREEZE"
            else: assert False
            assert transitions.reader.get_date_state("20261002") == "UNCLAIMED"
        assert not list(root.rglob("001_attempt_started.json"))


def test_m2_fake_pre_rejection_and_artifact_derivation():
    with _sandbox() as root:
        cases = {
            "missing_directory": None,
            "bad_hash": _write_pre(root / "bad_hash", bad_hash=True),
            "missing_required": _write_pre(root / "missing_required", missing="summary.json"),
            "unexpected": _write_pre(root / "unexpected", extra=True),
            "wrong_date": _write_pre(root / "wrong_date", target_date="20260927"),
        }
        for name, pre in cases.items():
            transitions = PreStateTransitions(root / "state" / name)
            transitions.claim_date("20260926", attempt_id="technical-only", metadata={"authorization_id": "fixture-auth"})
            try: transitions.mark_pre_frozen_from_artifact("20260926", attempt_id="technical-only", pre_directory=pre or root / "absent")
            except Stop as exc: assert str(exc) == "STOP_PRE_ARTIFACT_INTEGRITY"
            else: assert False
            assert transitions.reader.get_date_state("20260926") == "ATTEMPT_STARTED"
        transitions = PreStateTransitions(root / "state" / "valid")
        transitions.claim_date("20260926", attempt_id="technical-only", metadata={"authorization_id": "fixture-auth"})
        valid = _write_pre(root / "valid")
        event = transitions.mark_pre_frozen_from_artifact("20260926", attempt_id="technical-only", pre_directory=valid)
        value = json.loads(event.read_text(encoding="utf-8"))
        assert transitions.reader.get_date_state("20260926") == "PRE_FROZEN"
        assert value["pre_manifest_sha256"] == _sha(valid / "pre_freeze_manifest.json")
        assert value["artifact_index_sha256"] == _sha(valid / "artifact_hashes.json")


def test_m2_happy_path_and_failure_matrix_are_irreversible():
    with _sandbox() as root:
        state = root / "state"
        def pipeline(_timestamp: str, attempt_id: str):
            return _PipelineResult(_write_pre(root / "pre", attempt_id=attempt_id))
        _run_formal_pre_for_test("20260926", event_root=state, preflight=_preflight, pipeline=pipeline)
        assert StateReader(state).get_date_state("20260926") == "PRE_FROZEN"
        for name in ("current_missing", "g2", "g3", "result_key", "corrected"):
            transitions = PreStateTransitions(root / name)
            try: _run_formal_pre_for_test("20261002", event_root=root / name, preflight=_preflight, pipeline=lambda *_args, name=name: (_ for _ in ()).throw(Stop(name)))
            except Stop: pass
            else: assert False
            assert transitions.reader.get_date_state("20261002") == "NO_PRE"
            try: transitions.claim_date("20261002", attempt_id="retry", metadata={})
            except Stop: pass
            else: assert False


def test_public_api_surface_prevents_unsafe_write():
    import review.current_corrected_shadow_v2_prospective_formal_pre_v1 as formal
    from review.current_corrected_shadow_v2_prospective_pre_v1 import run, run_formal, write_no_pre
    assert [name for name, value in vars(formal).items() if callable(value) and name in {"run", "run_formal", "run_formal_pre"}] == ["run_formal_pre"]
    assert not hasattr(PreStateTransitions(Path("x")), "mark_pre_frozen")
    try: write_no_pre(Path("x"), "20261002", "unsafe")
    except Stop as exc: assert str(exc) == "STOP_LEGACY_NO_PRE_OUTPUT_DISABLED"
    else: assert False
    for legacy in (lambda: run("20261002"), lambda: run_formal("20261002", Path("dg"), Path("de"), Path("ds"), Path("out"), authorization_path=Path("auth"), authoritative_protocol_freeze=Path("freeze"))):
        try: legacy()
        except Stop as exc: assert str(exc) == "STOP_LEGACY_FORMAL_PRE_ENTRYPOINT_DISABLED"
        else: assert False
