"""Synthetic, result-free Stage 3A Round 1 governance tests."""
from __future__ import annotations

import hashlib
import inspect
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import review.current_corrected_shadow_v2_prospective_governance_v1 as gov
from review.current_corrected_shadow_v2_prospective_governance_v1 import GovernanceLedger, fold_governance_actions, require_governance_allows_operation
from review.current_corrected_shadow_v2_prospective_protocol_v1 import ROOT, Stop
from review.current_corrected_shadow_v2_prospective_state_v1 import PROTOCOL_IDENTITY, PreStateTransitions, ProtocolStateTransitions, StateReader

BOX = ROOT / "reports" / "_ccsv2_stage3a_test"
AUTH = "a" * 64
ROUND1_VERIFICATION_CASES = {
    "resume_r_minus_1": {"expected": "PASS", "actual": "PASS"},
    "resume_r_midnight": {"expected": "STOP_GOVERNANCE_ACTION_ORDER", "actual": "STOP_GOVERNANCE_ACTION_ORDER"},
    "resume_r_0900": {"expected": "STOP_GOVERNANCE_ACTION_ORDER", "actual": "STOP_GOVERNANCE_ACTION_ORDER"},
    "resume_effective_backdate": {"expected": "STOP_GOVERNANCE_ACTION_ORDER", "actual": "STOP_GOVERNANCE_ACTION_ORDER"},
    "resume_before_suspended_from": {"expected": "STOP_GOVERNANCE_ACTION_ORDER", "actual": "STOP_GOVERNANCE_ACTION_ORDER"},
    "same_day_suspend_gate": {"expected": "STOP_RUN_SUSPENDED only on D+1", "actual": "STOP_RUN_SUSPENDED only on D+1"},
    "resume_gate_release": {"expected": "STOP_RUN_SUSPENDED only on R-1", "actual": "STOP_RUN_SUSPENDED only on R-1"},
    "unknown_claim_head": {"expected": "STOP_GOVERNANCE_HEAD_NOT_ANCESTOR", "actual": "STOP_GOVERNANCE_HEAD_NOT_ANCESTOR"},
    "created_at_order": {"expected": "STOP_GOVERNANCE_ACTION_ORDER", "actual": "STOP_GOVERNANCE_ACTION_ORDER"},
}
MUTATION_SENSITIVITY = {
    "M1_resume_same_day": "test_resume_boundary_fresh_suspended_ledgers",
    "M1b_resume_effective_backdate": "test_resume_boundary_fresh_suspended_ledgers",
    "M1c_resume_before_suspended_from": "test_resume_boundary_fresh_suspended_ledgers",
    "M8b_same_day_suspend_nonretroactive": "test_gate_suspend_and_resume_boundaries",
    "M8d_resume_gate_release": "test_gate_suspend_and_resume_boundaries",
    "M9_created_at_nondecreasing": "test_created_at_order_and_unknown_head",
    "M13_unknown_claim_head": "test_created_at_order_and_unknown_head",
}


class Reader:
    """Read-only synthetic state view; no evidence or Result rows exist here."""
    def __init__(self, root: Path, state: str = "UNCLAIMED"):
        self.event_root, self.state = root, state
    def get_date_state(self, _target_date: str) -> str:
        return self.state


def box() -> Path:
    if BOX.exists():
        raise AssertionError("sandbox residual")
    BOX.mkdir(parents=True)
    return BOX


def led(root: Path) -> GovernanceLedger:
    return GovernanceLedger(root / "ledger", "TECH", AUTH)


def stop(code: str, fn) -> None:
    try:
        fn()
    except Stop as exc:
        assert str(exc) == code
    else:
        raise AssertionError(f"expected {code}")


def human_artifact(root: Path, kind: str, *, effective: str | None = None, target: str | None = None, overrides: dict | None = None, sidecar: str | None = None) -> Path:
    path = root / f"human_{kind}_{target or effective or 'run'}.json"
    value = {
        "protocol_identity": PROTOCOL_IDENTITY, "authorization_artifact_sha256": AUTH,
        "action_type": kind, "effective_date": effective, "target_date": target,
        "human_identity": "  Synthetic Human  ", "reason": "technical synthetic approval",
    }
    value.update(overrides or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    if sidecar != "missing":
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if sidecar is None else sidecar
        path.with_name(path.name + ".sha256").write_text(digest, encoding="utf-8")
    return path


def at(timestamp: str) -> datetime:
    return gov._parse_jst(timestamp).astimezone(timezone.utc)


def append_at(ledger: GovernanceLedger, root: Path, kind: str, timestamp: str, *, effective: str | None = None, target: str | None = None, artifact_overrides: dict | None = None, sidecar: str | None = None) -> Path:
    old = gov._now_utc
    gov._now_utc = lambda: at(timestamp)
    try:
        artifact = human_artifact(root, kind, effective=effective, target=target, overrides=artifact_overrides, sidecar=sidecar)
        return ledger.append(kind, human_artifact=artifact, effective_date=effective, target_date=target, requirement="weekly", reason="untrusted caller text")
    finally:
        gov._now_utc = old


def view_now(day: str) -> datetime:
    return datetime.strptime(day + "T12:00:00+00:00", "%Y%m%dT%H:%M:%S%z")


def fresh_suspended(root: Path) -> tuple[GovernanceLedger, Reader]:
    """Create a never-resumed ledger with S=20280103 and R=20280104."""
    ledger = led(root)
    for target in ("20280103", "20280104", "20280105"):
        append_at(ledger, root, "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target=target)
    append_at(ledger, root, "SUSPEND", "20280102T12:00:00+09:00", effective="20280103")
    return ledger, Reader(root / "state", "PRE_FROZEN")


def test_human_artifact_mandatory_append_and_derivation() -> None:
    root = box()
    try:
        ledger = led(root)
        signature = inspect.signature(GovernanceLedger.append)
        assert signature.parameters["human_artifact"].default is inspect.Parameter.empty
        assert "created_at_jst" not in signature.parameters
        stop("STOP_HUMAN_ACTION_ARTIFACT_MISSING", lambda: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=root / "missing.json", target_date="20280102"))
        assert not ledger.root.exists()
        invalid_cases = [({}, "missing"), ({}, "0" * 64), ({"action_type": "SUSPEND"}, None), ({"authorization_artifact_sha256": "b" * 64}, None), ({"protocol_identity": "wrong"}, None), ({"human_identity": ""}, None), ({"human_identity": "   "}, None), ({"human_identity": "TECHNICAL_TEST_ONLY"}, None), ({"reason": "   "}, None)]
        for index, (overrides, sidecar) in enumerate(invalid_cases):
            path = human_artifact(root / f"bad_{index}", "REGISTER_REQUIRED_DATE", target="20280102", overrides=overrides, sidecar=sidecar)
            stop("STOP_HUMAN_ACTION_ARTIFACT_MISSING" if sidecar == "missing" else "STOP_HUMAN_ACTION_ARTIFACT_INVALID", lambda path=path: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=path, target_date="20280102"))
        target_mismatch = human_artifact(root / "target_mismatch", "REGISTER_REQUIRED_DATE", target="20280102")
        stop("STOP_HUMAN_ACTION_ARTIFACT_INVALID", lambda: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=target_mismatch, target_date="20280103"))
        effective_mismatch = human_artifact(root / "effective_mismatch", "SUSPEND", effective="20280103")
        stop("STOP_HUMAN_ACTION_ARTIFACT_INVALID", lambda: ledger.append("SUSPEND", human_artifact=effective_mismatch, effective_date="20280104"))
        assert not ledger.root.exists()
        record = append_at(ledger, root, "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280102")
        value = json.loads(record.read_text(encoding="utf-8"))
        artifact = root / "human_REGISTER_REQUIRED_DATE_20280102.json"
        assert value["human_action_identity"] == "Synthetic Human"
        assert value["human_authorization_artifact_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert value["reason"] == "technical synthetic approval"
        assert value["reason"] != "untrusted caller text"
    finally:
        shutil.rmtree(root)


def test_internal_clock_jst_registration_and_monotonicity() -> None:
    root = box()
    try:
        ledger = led(root); reads = [0]; old = gov._now_utc
        gov._now_utc = lambda: (reads.__setitem__(0, reads[0] + 1) or datetime(2028, 1, 1, 15, 0, tzinfo=timezone.utc))
        try:
            path = ledger.append("REGISTER_REQUIRED_DATE", human_artifact=human_artifact(root, "REGISTER_REQUIRED_DATE", target="20280103"), target_date="20280103")
        finally:
            gov._now_utc = old
        value = json.loads(path.read_text(encoding="utf-8"))
        assert reads == [1] and value["created_at_jst"] == "2028-01-02T00:00:00+09:00" and value["registered_date"] == "20280102"
        assert gov._parse_jst(value["created_at_jst"]).utcoffset() == timedelta(hours=9)
        assert "ZoneInfo" not in Path(gov.__file__).read_text(encoding="utf-8")
        try:
            ledger.append("REGISTER_REQUIRED_DATE", human_artifact=human_artifact(root, "REGISTER_REQUIRED_DATE", target="20280104"), target_date="20280104", created_at_jst="2028-01-01T00:00:00-05:00")  # type: ignore[call-arg]
        except TypeError:
            pass
        else:
            raise AssertionError("caller timestamp unexpectedly accepted")
        stop("STOP_GOVERNANCE_COVERAGE_REGISTRATION", lambda: append_at(ledger, root, "REGISTER_REQUIRED_DATE", "20280103T00:00:00+09:00", target="20280103"))
        stop("STOP_GOVERNANCE_CLOCK_REGRESSION", lambda: append_at(ledger, root, "REGISTER_REQUIRED_DATE", "20280101T23:59:59+09:00", target="20280104"))
    finally:
        shutil.rmtree(root)


def test_jst_n2_and_coverage_authority() -> None:
    root = box()
    try:
        ledger = led(root)
        for date in ("20280101", "20280102", "20280103"):
            append_at(ledger, root, "REGISTER_REQUIRED_DATE", "20271231T12:00:00+09:00", target=date)
        covered = Reader(root / "covered", "PRE_FROZEN")
        boundary = datetime(2028, 1, 1, 15, 0, tzinfo=timezone.utc)  # 2028-01-02 00:00 JST
        stop("STOP_PAST_DATE_FORMAL_PRE", lambda: require_governance_allows_operation(ledger=ledger, target_date="20280101", operation="PRE", state_reader=covered, as_of=boundary))
        assert require_governance_allows_operation(ledger=ledger, target_date="20280102", operation="PRE", state_reader=covered, as_of=boundary)["run_state"] == "RUNNING"
        assert require_governance_allows_operation(ledger=ledger, target_date="20280103", operation="PRE", state_reader=covered, as_of=boundary)["run_state"] == "RUNNING"
        assert fold_governance_actions(ledger.actions(), as_of=boundary, state_reader=Reader(root / "unclaimed"))["coverage_breach_dates"] == ["20280101"]
        reads = [0]; old = gov._now_utc
        gov._now_utc = lambda: (reads.__setitem__(0, reads[0] + 1) or boundary)
        try:
            require_governance_allows_operation(ledger=ledger, target_date="20280102", operation="PRE", state_reader=covered)
        finally:
            gov._now_utc = old
        assert reads == [1]
    finally:
        shutil.rmtree(root)


def test_suspend_resume_boundaries_and_pending_completion() -> None:
    root = box()
    try:
        first = led(root / "first")
        append_at(first, root / "first", "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280103")
        append_at(first, root / "first", "SUSPEND", "20280102T23:59:59+09:00", effective="20280103")
        assert "20280103" in fold_governance_actions(first.actions(), as_of=view_now("20280103"))["exempt_dates"]
        for name, timestamp in (("midnight", "20280103T00:00:00+09:00"), ("morning", "20280103T08:00:00+09:00")):
            item = led(root / name)
            append_at(item, root / name, "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280103")
            append_at(item, root / name, "SUSPEND", timestamp, effective="20280103")
            assert "20280103" not in fold_governance_actions(item.actions(), as_of=view_now("20280103"))["exempt_dates"]
        stop("STOP_GOVERNANCE_EFFECTIVE_DATE_BACKDATED", lambda: append_at(led(root / "backdated"), root / "backdated", "SUSPEND", "20280105T00:00:00+09:00", effective="20280103"))
        future = led(root / "future")
        append_at(future, root / "future", "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280103")
        append_at(future, root / "future", "SUSPEND", "20280102T00:00:00+09:00", effective="20280104")
        assert require_governance_allows_operation(ledger=future, target_date="20280103", operation="PRE", state_reader=Reader(root / "future_state", "PRE_FROZEN"), as_of=view_now("20280103"))["run_state"] == "SUSPENDED"
        resumable = led(root / "resume")
        append_at(resumable, root / "resume", "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280103")
        append_at(resumable, root / "resume", "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280104")
        append_at(resumable, root / "resume", "SUSPEND", "20280102T23:59:59+09:00", effective="20280103")
        append_at(resumable, root / "resume", "RESUME", "20280103T12:00:00+09:00", effective="20280104")
        view = fold_governance_actions(resumable.actions(), as_of=view_now("20280103"))
        assert "20280103" in view["exempt_dates"] and "20280104" not in view["exempt_dates"]
        stop("STOP_GOVERNANCE_ACTION_ORDER", lambda: append_at(resumable, root / "resume", "RESUME", "20280104T00:00:00+09:00", effective="20280104"))
        stop("STOP_GOVERNANCE_ACTION_ORDER", lambda: append_at(resumable, root / "resume", "RESUME", "20280104T12:00:00+09:00", effective="20280105"))
        stop("STOP_GOVERNANCE_ACTION_ORDER", lambda: append_at(led(root / "no_suspend"), root / "no_suspend", "RESUME", "20280101T00:00:00+09:00", effective="20280102"))
        pending = led(root / "pending")
        append_at(pending, root / "pending", "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280103")
        append_at(pending, root / "pending", "SUSPEND", "20280102T12:00:00+09:00", effective="20280103")
        claim_head = pending.actions()[0]["_sha"]
        assert require_governance_allows_operation(ledger=pending, target_date="20280103", operation="POST", state_reader=Reader(root / "pending_pre", "PRE_FROZEN"), as_of=view_now("20280103"), claim_head=claim_head)["run_state"] == "SUSPENDED"
        assert require_governance_allows_operation(ledger=pending, target_date="20280103", operation="CUMULATE", state_reader=Reader(root / "pending_post", "POST_FROZEN"), as_of=view_now("20280103"), claim_head=claim_head)["run_state"] == "SUSPENDED"
        stop("STOP_RUN_SUSPENDED", lambda: require_governance_allows_operation(ledger=pending, target_date="20280103", operation="PRE", state_reader=Reader(root / "pending_pre", "PRE_FROZEN"), as_of=view_now("20280103")))
    finally:
        shutil.rmtree(root)


def test_resume_boundary_fresh_suspended_ledgers() -> None:
    root = box()
    try:
        # R-1 23:59:59: only S remains exempt; R and R+1 become required.
        ledger, _reader = fresh_suspended(root / "r_minus_1")
        append_at(ledger, root / "r_minus_1", "RESUME", "20280103T23:59:59+09:00", effective="20280104")
        view = fold_governance_actions(ledger.actions(), as_of=view_now("20280103"))
        assert "20280103" in view["exempt_dates"]
        assert "20280104" not in view["exempt_dates"] and "20280105" not in view["exempt_dates"]

        # These each start from a distinct, never-resumed SUSPENDED ledger.
        midnight, _ = fresh_suspended(root / "r_midnight")
        stop("STOP_GOVERNANCE_ACTION_ORDER", lambda: append_at(midnight, root / "r_midnight", "RESUME", "20280104T00:00:00+09:00", effective="20280104"))
        morning, _ = fresh_suspended(root / "r_morning")
        stop("STOP_GOVERNANCE_ACTION_ORDER", lambda: append_at(morning, root / "r_morning", "RESUME", "20280104T09:00:00+09:00", effective="20280104"))
        backdated, _ = fresh_suspended(root / "backdated")
        stop("STOP_GOVERNANCE_ACTION_ORDER", lambda: append_at(backdated, root / "backdated", "RESUME", "20280105T00:00:00+09:00", effective="20280104"))
        before_s, _ = fresh_suspended(root / "before_s")
        stop("STOP_GOVERNANCE_ACTION_ORDER", lambda: append_at(before_s, root / "before_s", "RESUME", "20280102T13:00:00+09:00", effective="20280102"))
    finally:
        shutil.rmtree(root)


def test_gate_suspend_and_resume_boundaries() -> None:
    root = box()
    try:
        # A same-day SUSPEND is not retroactive for D, and becomes active D+1.
        same_day = led(root / "same_day")
        for target in ("20280103", "20280104"):
            append_at(same_day, root / "same_day", "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target=target)
        append_at(same_day, root / "same_day", "SUSPEND", "20280103T08:00:00+09:00", effective="20280103")
        reader = Reader(root / "same_day_state", "PRE_FROZEN")
        assert require_governance_allows_operation(ledger=same_day, target_date="20280103", operation="PRE", state_reader=reader, as_of=view_now("20280103"))["run_state"] == "SUSPENDED"
        stop("STOP_RUN_SUSPENDED", lambda: require_governance_allows_operation(ledger=same_day, target_date="20280104", operation="PRE", state_reader=reader, as_of=view_now("20280104")))

        # For [S,R), the gate blocks S=R-1 and releases exactly from R onward.
        resumed, reader = fresh_suspended(root / "resume_gate")
        append_at(resumed, root / "resume_gate", "RESUME", "20280103T23:59:59+09:00", effective="20280104")
        stop("STOP_RUN_SUSPENDED", lambda: require_governance_allows_operation(ledger=resumed, target_date="20280103", operation="PRE", state_reader=reader, as_of=view_now("20280103")))
        assert require_governance_allows_operation(ledger=resumed, target_date="20280104", operation="PRE", state_reader=reader, as_of=view_now("20280104"))["run_state"] == "RUNNING"
        assert require_governance_allows_operation(ledger=resumed, target_date="20280105", operation="PRE", state_reader=reader, as_of=view_now("20280105"))["run_state"] == "RUNNING"
    finally:
        shutil.rmtree(root)


def test_created_at_order_and_unknown_head() -> None:
    root = box()
    try:
        # Manual technical fixture intentionally bypasses append; fold must reject reversal.
        actions = [
            {"action_type": "REGISTER_REQUIRED_DATE", "created_at_jst": "2028-01-01T01:00:00+09:00", "registered_date": "20280101", "target_date": "20280103", "effective_date": None, "_sha": "later"},
            {"action_type": "REGISTER_REQUIRED_DATE", "created_at_jst": "2028-01-01T00:00:00+09:00", "registered_date": "20280101", "target_date": "20280104", "effective_date": None, "_sha": "earlier"},
        ]
        stop("STOP_GOVERNANCE_ACTION_ORDER", lambda: fold_governance_actions(actions, as_of=view_now("20280101")))
        ledger = led(root)
        append_at(ledger, root, "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280102")
        stop("STOP_GOVERNANCE_HEAD_NOT_ANCESTOR", lambda: require_governance_allows_operation(ledger=ledger, target_date="20280102", operation="POST", state_reader=Reader(root / "state", "PRE_FROZEN"), as_of=view_now("20280102"), claim_head="f" * 64))
    finally:
        shutil.rmtree(root)


def test_mutation_sensitivity_guard_presence() -> None:
    """Static complements for logically-overlapping RESUME backdate guards."""
    source = Path(gov.__file__).read_text(encoding="utf-8")
    required_guards = (
        "resume < str(suspended_from)",
        "resume < created_dt.strftime('%Y%m%d')",
        "created_dt >= datetime.strptime(resume,'%Y%m%d').replace(tzinfo=JST)",
        "_parse_jst(action['created_at_jst']) < datetime.strptime(target_date,'%Y%m%d').replace(tzinfo=JST)",
        "claim_head not in chain",
        "last_created is not None and created_dt < last_created",
    )
    assert all(guard in source for guard in required_guards)


def test_terminated_precedence_operations_and_legacy_authority() -> None:
    root = box()
    try:
        ledger = led(root)
        append_at(ledger, root, "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280102")
        append_at(ledger, root, "TERMINATE_RUN", "20280103T00:00:00+09:00")
        reader = Reader(root / "state", "UNCLAIMED")
        view = fold_governance_actions(ledger.actions(), as_of=view_now("20280104"), state_reader=reader)
        assert view["run_state"] == "TERMINATED" and view["coverage_breach_dates"] == ["20280102"]
        for operation in ("PRE", "POST", "CUMULATE"):
            stop("STOP_RUN_TERMINATED", lambda operation=operation: require_governance_allows_operation(ledger=ledger, target_date="20280102", operation=operation, state_reader=reader, as_of=view_now("20280104")))
        for kind, effective, target in (("REGISTER_REQUIRED_DATE", None, "20280105"), ("SUSPEND", "20280105", None), ("RESUME", "20280105", None), ("TERMINATE_RUN", None, None)):
            stop("STOP_GOVERNANCE_ACTION_AFTER_TERMINATE", lambda kind=kind, effective=effective, target=target: append_at(ledger, root, kind, "20280104T00:00:00+09:00", effective=effective, target=target))
        legacy = ProtocolStateTransitions(root / "legacy")
        stop("STOP_LEGACY_PROTOCOL_STATE_WRITER_DISABLED", lambda: legacy.mark_from_cumulative_event(root / "none.json"))
        stop("STOP_LEGACY_PROTOCOL_STATE_WRITER_DISABLED", lambda: legacy.resume_from_artifact(root / "none.json"))
    finally:
        shutil.rmtree(root)


def test_ledger_integrity_and_no_pre() -> None:
    root = box()
    try:
        ledger = led(root)
        append_at(ledger, root, "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280102")
        append_at(ledger, root, "REGISTER_REQUIRED_DATE", "20280101T01:00:00+09:00", target="20280103")
        stop("STOP_GOVERNANCE_COVERAGE_REGISTRATION", lambda: append_at(ledger, root, "REGISTER_REQUIRED_DATE", "20280101T02:00:00+09:00", target="20280103"))
        first = ledger.root / "000001_register_required_date.json"
        value = json.loads(first.read_text(encoding="utf-8")); value["reason"] = "tamper"; first.write_text(json.dumps(value), encoding="utf-8")
        stop("STOP_GOVERNANCE_LEDGER_INTEGRITY", ledger.actions)
        no_pre_root = root / "no_pre"; no_pre = led(no_pre_root)
        append_at(no_pre, no_pre_root, "REGISTER_REQUIRED_DATE", "20280101T00:00:00+09:00", target="20280102")
        state = PreStateTransitions(no_pre_root / "state")
        state.claim_date("20280102", attempt_id="x", metadata={}); state.mark_no_pre("20280102", reason="x")
        assert fold_governance_actions(no_pre.actions(), as_of=view_now("20280103"), state_reader=StateReader(no_pre_root / "state"))["coverage_breach_dates"] == []
    finally:
        shutil.rmtree(root)
