"""Synthetic-only Round 2 Human-store tail-anchor tests."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from review.current_corrected_shadow_v2_prospective_governance_v1 import GovernanceLedger, require_governance_allows_operation
from review.current_corrected_shadow_v2_prospective_human_artifact_store_v1 import HumanArtifactStoreBinding, SCHEMA_NAME, SCHEMA_VERSION
from review.current_corrected_shadow_v2_prospective_protocol_v1 import ROOT, Stop
from review.current_corrected_shadow_v2_prospective_state_v1 import PROTOCOL_IDENTITY

BOX = ROOT / "reports" / "_ccsv2_stage3a_round2_test"
AUTH = "a" * 64
ROUND2_MUTATION_PROBES = [
    *(f"T9_{field}" for field in ("action_identity", "action_type", "human_identity", "reason", "effective_date", "target_date", "created_at_jst", "registered_date", "requirement", "exemption_reason", "source_artifact_sha256", "human_authorization_artifact_sha256")),
    "CA_FILENAME_CONTENT_SHA", "CA_SIDECAR_CONTENT", "CA_SIDECAR_EXISTS", "CA_AUTH_SHA", "CA_AUTH_ID", "CA_PROTOCOL", "CA_STORE_MISSING", "CA_OUTSIDE_STORE", "CA_APPEND_ORPHAN", "CA_APPEND_RECONCILIATION", "CA_TECHNICAL_IDENTITY",
]
MUTATION_RESULTS: list[dict[str, str]] = []


class Reader:
    def __init__(self, root: Path): self.event_root = root
    def get_date_state(self, _date: str) -> str: return "PRE_FROZEN"


def _stop(code: str, fn, *, mutation_id: str | None = None, test_name: str | None = None, targeted_guard: str | None = None) -> None:
    try: fn()
    except Stop as exc:
        actual = str(exc)
        if mutation_id is not None:
            MUTATION_RESULTS.append({"mutation_id": mutation_id, "targeted_guard": targeted_guard or code, "mutation_applied": "YES", "test_name": test_name or "unknown", "expected_result": code, "actual_result": actual, "detected": "YES" if actual == code else "NO", "detection_type": "BEHAVIORAL_MUTATION_TEST"})
        assert actual == code
    else: raise AssertionError(code)


def _box() -> Path:
    if BOX.exists(): raise AssertionError("sandbox residual")
    BOX.mkdir(parents=True); return BOX


def _binding(root: Path, *, auth: str = AUTH) -> HumanArtifactStoreBinding:
    store = root / "human_store"; store.mkdir()
    return HumanArtifactStoreBinding(store, "TECH", auth, SCHEMA_NAME, SCHEMA_VERSION)


def _artifact(binding: HumanArtifactStoreBinding, identity: str, kind: str, *, target: str | None = None, effective: str | None = None, reason: str = "synthetic human approval", overrides: dict | None = None) -> Path:
    value = {"artifact_schema": SCHEMA_NAME, "artifact_version": SCHEMA_VERSION, "action_identity": identity, "action_type": kind, "protocol_identity": PROTOCOL_IDENTITY, "authorization_id": binding.authorization_id, "authorization_artifact_sha256": binding.authorization_artifact_sha256, "human_authorization_artifact_sha256": binding.authorization_artifact_sha256, "human_identity": "Synthetic Human", "created_at": "2020-12-01T00:00:00+09:00", "effective_date": effective, "target_date": target, "reason": reason, "requirement": "synthetic" if kind == "REGISTER_REQUIRED_DATE" else None, "exemption_reason": None, "source_artifact_sha256": None}
    value.update(overrides or {})
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest(); path = binding.root / f"{digest}.json"
    path.write_bytes(raw); path.with_name(path.name + ".sha256").write_text(digest + "\n", encoding="utf-8")
    return path


def _append(ledger: GovernanceLedger, binding: HumanArtifactStoreBinding, identity: str, kind: str, *, target: str | None = None, effective: str | None = None) -> Path:
    artifact = _artifact(binding, identity, kind, target=target, effective=effective)
    return ledger.append(kind, human_artifact=artifact, target_date=target, effective_date=effective, requirement="synthetic" if kind == "REGISTER_REQUIRED_DATE" else None)


def _rename_content_file_only(path: Path) -> None:
    """Keep the sidecar adjacent so the filename guard is reached first."""
    renamed = path.with_name("0" * 64 + ".json")
    path.rename(renamed)
    path.with_name(path.name + ".sha256").rename(renamed.with_name(renamed.name + ".sha256"))


def _chain(root: Path, *, terminate: bool = False) -> tuple[GovernanceLedger, HumanArtifactStoreBinding, list[Path]]:
    binding = _binding(root); ledger = GovernanceLedger(root / "ledger", "TECH", AUTH, binding)
    paths = [_append(ledger, binding, "A", "REGISTER_REQUIRED_DATE", target="20280101"), _append(ledger, binding, "B", "REGISTER_REQUIRED_DATE", target="20280102")]
    paths.append(_append(ledger, binding, "C", "TERMINATE_RUN" if terminate else "REGISTER_REQUIRED_DATE", target=None if terminate else "20280103"))
    return ledger, binding, paths


def test_round2_happy_path_and_ancestor_semantics() -> None:
    root = _box()
    try:
        ledger, binding, _ = _chain(root)
        actions = ledger.actions(); pinned = actions[1]["_sha"]
        # T2 valid ancestor and T3 future append both remain valid.
        require_governance_allows_operation(ledger=ledger, target_date="20280102", operation="POST", state_reader=Reader(root), claim_head=pinned)
        _append(ledger, binding, "D", "REGISTER_REQUIRED_DATE", target="20280104")
        require_governance_allows_operation(ledger=ledger, target_date="20280102", operation="POST", state_reader=Reader(root), claim_head=pinned)
        # T1 unknown pinned head.
        _stop("STOP_GOVERNANCE_HEAD_NOT_ANCESTOR", lambda: require_governance_allows_operation(ledger=ledger, target_date="20280102", operation="POST", state_reader=Reader(root), claim_head="f" * 64))
    finally: shutil.rmtree(root)


def test_round2_tail_deletion_and_missing_artifact() -> None:
    root = _box()
    try:
        ledger, binding, paths = _chain(root, terminate=True)
        # T8: retain C artifact, delete only terminal ledger entry; it cannot revive the run.
        paths[-1].unlink()
        _stop("STOP_ORPHAN_HUMAN_ACTION_ARTIFACT", ledger.actions)
        # T10 independently: ledger entry retained but its external artifact removed.
        root2 = root / "missing"; root2.mkdir(); ledger2, binding2, _ = _chain(root2)
        digest = ledger2.actions()[-1]["human_action_artifact_sha256"]
        (binding2.root / f"{digest}.json").unlink(); (binding2.root / f"{digest}.json.sha256").unlink()
        _stop("STOP_MISSING_HUMAN_ACTION_ARTIFACT", ledger2.actions)
    finally: shutil.rmtree(root)


def test_round2_replacement_duplicates_and_fork() -> None:
    root = _box()
    try:
        ledger, binding, paths = _chain(root)
        # T9 tail replacement becomes a semantic ledger/artifact mismatch.
        tail = json.loads(paths[-1].read_text(encoding="utf-8")); tail["human_action_identity"] = "C_prime"; paths[-1].write_text(json.dumps(tail), encoding="utf-8")
        _stop("STOP_HUMAN_ACTION_ARTIFACT_LEDGER_MISMATCH", ledger.actions)
        root2 = root / "duplicates"; root2.mkdir(); ledger2, binding2, paths2 = _chain(root2)
        duplicate = json.loads(paths2[-1].read_text(encoding="utf-8")); duplicate["human_action_artifact_sha256"] = json.loads(paths2[-2].read_text(encoding="utf-8"))["human_action_artifact_sha256"]; paths2[-1].write_text(json.dumps(duplicate), encoding="utf-8")
        _stop("STOP_DUPLICATE_HUMAN_ACTION_ARTIFACT_REFERENCE", ledger2.actions)  # T11
        root3 = root / "identity"; root3.mkdir(); ledger3, binding3, _ = _chain(root3)
        # T12 duplicate artifact action identity in the authorized store.
        _artifact(binding3, "A", "REGISTER_REQUIRED_DATE", target="20280109")
        _stop("STOP_DUPLICATE_HUMAN_ACTION_IDENTITY_ARTIFACT", ledger3.actions)
        root5 = root / "ledger_identity"; root5.mkdir(); ledger5, _, paths5 = _chain(root5)
        duplicate_identity = json.loads(paths5[-1].read_text(encoding="utf-8")); duplicate_identity["human_action_identity"] = "A"; paths5[-1].write_text(json.dumps(duplicate_identity), encoding="utf-8")
        _stop("STOP_DUPLICATE_HUMAN_ACTION_IDENTITY_LEDGER", ledger5.actions)
        root4 = root / "fork"; root4.mkdir(); ledger4, _binding4, paths4 = _chain(root4)
        prior = json.loads(paths4[-1].read_text(encoding="utf-8")); prior["previous_action_sha256"] = "f" * 64; paths4[-1].write_text(json.dumps(prior), encoding="utf-8")
        _stop("STOP_GOVERNANCE_LEDGER_INTEGRITY", ledger4.actions)  # T6
        # A: duplicate sequence/fork entry; B: tail reattached to an ancestor;
        # C: a competing tail after an otherwise valid append.
        for name, mode in (("duplicate_sequence", "duplicate"), ("ancestor_tail", "ancestor"), ("competing_tail", "competing")):
            probe = root / name; probe.mkdir(); ledgerx, bindingx, pathsx = _chain(probe)
            if mode == "duplicate":
                copied = json.loads(pathsx[-1].read_text(encoding="utf-8")); (ledgerx.root / "000004_duplicate.json").write_text(json.dumps(copied), encoding="utf-8")
            elif mode == "ancestor":
                changed = json.loads(pathsx[-1].read_text(encoding="utf-8")); changed["previous_action_sha256"] = ledgerx.actions()[0]["_sha"]; pathsx[-1].write_text(json.dumps(changed), encoding="utf-8")
            else:
                _append(ledgerx, bindingx, "D", "REGISTER_REQUIRED_DATE", target="20280104")
                copied = json.loads((ledgerx.root / "000004_register_required_date.json").read_text(encoding="utf-8")); copied["previous_action_sha256"] = ledgerx.actions()[1]["_sha"]; (ledgerx.root / "000005_competing.json").write_text(json.dumps(copied), encoding="utf-8")
            _stop("STOP_GOVERNANCE_LEDGER_INTEGRITY", ledgerx.actions)
    finally: shutil.rmtree(root)


def test_round2_pinned_mutation_deletion_and_authorization() -> None:
    root = _box()
    try:
        ledger, binding, paths = _chain(root); pinned = ledger.actions()[1]["_sha"]
        paths[1].unlink(); _stop("STOP_GOVERNANCE_LEDGER_SEQUENCE", ledger.actions)  # T4
        root2 = root / "mutated"; root2.mkdir(); ledger2, _, paths2 = _chain(root2); changed = json.loads(paths2[1].read_text(encoding="utf-8")); changed["reason"] = "tampered"; paths2[1].write_text(json.dumps(changed), encoding="utf-8")
        _stop("STOP_GOVERNANCE_LEDGER_INTEGRITY", ledger2.actions)  # T5
        other = GovernanceLedger(ledger.root, "OTHER", "b" * 64, HumanArtifactStoreBinding(binding.root, "OTHER", "b" * 64, SCHEMA_NAME, SCHEMA_VERSION))
        _stop("STOP_GOVERNANCE_LEDGER_INTEGRITY", other.actions)  # T7
        assert isinstance(pinned, str)
    finally: shutil.rmtree(root)


def test_round2_pre_post_cumulate_audit_head_binding() -> None:
    """Public POST/CUMULATE paths bind their own validated current heads."""
    from tests import test_current_corrected_shadow_v2_prospective_stage2_v1 as stage2
    import review.current_corrected_shadow_v2_prospective_post_v1 as post_module
    import review.current_corrected_shadow_v2_prospective_cumulative_v1 as cumulative_module
    from review.current_corrected_shadow_v2_prospective_state_v1 import PreStateTransitions
    root = _box()
    try:
        target, project = "20280103", root / "project"; project.mkdir()
        auth_path = project / "auth.json"; auth_path.write_text('{"synthetic":true}\n', encoding="utf-8")
        auth_sha = hashlib.sha256(auth_path.read_bytes()).hexdigest()
        store = project / "human_store"; store.mkdir(); binding = HumanArtifactStoreBinding(store, "TECHNICAL_TEST_ONLY", auth_sha, SCHEMA_NAME, SCHEMA_VERSION)
        authorization = {"authorization_id": "TECHNICAL_TEST_ONLY", "human_action_artifact_root": str(binding.root), "human_action_artifact_store_schema": SCHEMA_NAME, "human_action_artifact_store_version": SCHEMA_VERSION, "authoritative_freeze_path": "unused"}
        ledger = GovernanceLedger(project / "reports" / "current_corrected_shadow_v2_prospective_governance_v1", "TECHNICAL_TEST_ONLY", auth_sha, binding)
        _append(ledger, binding, "A", "REGISTER_REQUIRED_DATE", target="20280101")
        _append(ledger, binding, "B", "REGISTER_REQUIRED_DATE", target=target)
        pre_head = ledger.actions()[-1]["_sha"]
        pre = stage2._build_pre(target, project, races=2)
        state_root = project / "reports" / "current_corrected_shadow_v2_prospective_state_v1"
        state = PreStateTransitions(state_root)
        state.claim_date(target, attempt_id=f"{target}:technical", metadata={"authorization_id": "TECHNICAL_TEST_ONLY", "governance_ledger_head_sha256": pre_head})
        state.mark_pre_frozen_from_artifact(target, attempt_id=f"{target}:technical", pre_directory=pre)
        _append(ledger, binding, "C", "REGISTER_REQUIRED_DATE", target="20280104")
        post_head = ledger.actions()[-1]["_sha"]
        originals = (post_module.ROOT, post_module.load_protocol, post_module.validate_authorization_artifact, post_module.validate_runtime_freeze_binding, post_module._canonical_result_loader, cumulative_module.ROOT, cumulative_module.load_protocol, cumulative_module.validate_authorization_artifact, cumulative_module.validate_runtime_freeze_binding)
        try:
            post_module.ROOT = project; post_module.load_protocol = lambda: {"execution_authorization": {"artifact_path": "auth.json"}}; post_module.validate_authorization_artifact = lambda *_args: authorization; post_module.validate_runtime_freeze_binding = lambda *_args, **_kwargs: None; post_module._canonical_result_loader = lambda date, pre, _root: stage2._loader(date, pre)
            post = post_module.run_formal_post(target, project / "post", authorization_path=auth_path)
            post_manifest = json.loads((post / "post_manifest.json").read_text(encoding="utf-8")); post_provenance = json.loads((post / "provenance.json").read_text(encoding="utf-8"))
            history = state.reader.event_history(target); post_state = next(item for item in history if item["event"] == "POST_FROZEN")
            assert post_manifest["governance_ledger_head_sha256"] == post_head == post_provenance["governance_ledger_head_sha256"] == post_state["governance_ledger_head_sha256"]
            _append(ledger, binding, "D", "REGISTER_REQUIRED_DATE", target="20280105")
            cumulative_head = ledger.actions()[-1]["_sha"]
            cumulative_module.ROOT = project; cumulative_module.load_protocol = lambda: {"execution_authorization": {"artifact_path": "auth.json"}}; cumulative_module.validate_authorization_artifact = lambda *_args: authorization; cumulative_module.validate_runtime_freeze_binding = lambda *_args, **_kwargs: None
            event = cumulative_module.run_formal_cumulate(target)
            history = state.reader.event_history(target); cumulative_state = next(item for item in history if item["event"] == "CUMULATED")
            assert json.loads(event.read_text(encoding="utf-8"))["governance_ledger_head_sha256"] == cumulative_head == cumulative_state["governance_ledger_head_sha256"]
            actions = ledger.actions(); assert pre_head in {row["_sha"] for row in actions} and post_head in {row["_sha"] for row in actions}
        finally:
            post_module.ROOT, post_module.load_protocol, post_module.validate_authorization_artifact, post_module.validate_runtime_freeze_binding, post_module._canonical_result_loader, cumulative_module.ROOT, cumulative_module.load_protocol, cumulative_module.validate_authorization_artifact, cumulative_module.validate_runtime_freeze_binding = originals
    finally: shutil.rmtree(root)


def test_round2_t9_all_tail_fields_and_timestamp_binding() -> None:
    root = _box()
    try:
        mutations = {
            "human_action_identity": "C_prime", "action_type": "SUSPEND", "human_identity": "Other Human", "reason": "other",
            "effective_date": "20280102", "target_date": "20280104", "created_at_jst": "2026-01-01T00:00:00+09:00",
            "registered_date": "19990101", "requirement": "other", "exemption_reason": "other",
            "source_artifact_sha256": "b" * 64, "human_authorization_artifact_sha256": "b" * 64,
        }
        for field, value in mutations.items():
            probe = root / field; probe.mkdir(); ledger, _, paths = _chain(probe)
            row = json.loads(paths[-1].read_text(encoding="utf-8")); row[field] = value; paths[-1].write_text(json.dumps(row), encoding="utf-8")
            try: ledger.actions()
            except Stop as exc:
                MUTATION_RESULTS.append({"mutation_id": f"T9_{field.replace('human_action_identity', 'action_identity')}", "targeted_guard": "external artifact / ledger semantic binding", "mutation_applied": "YES", "test_name": "test_round2_t9_all_tail_fields_and_timestamp_binding", "expected_result": "STOP", "actual_result": str(exc), "detected": "YES", "detection_type": "BEHAVIORAL_MUTATION_TEST"})
            else: raise AssertionError(f"T9 mutation undetected: {field}")
        # Artifact timestamps must be timezone-aware and not postdate ledger append.
        probe = root / "timestamp"; probe.mkdir(); binding = _binding(probe); ledger = GovernanceLedger(probe / "ledger", "TECH", AUTH, binding)
        naive = _artifact(binding, "naive", "REGISTER_REQUIRED_DATE", target="20280101", overrides={"created_at": "2020-01-01T00:00:00"})
        _stop("STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_INVALID", lambda: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=naive, target_date="20280101", requirement="synthetic"), mutation_id="CA_TIMESTAMP_NAIVE", test_name="test_round2_t9_all_tail_fields_and_timestamp_binding")
        invalid = _artifact(binding, "invalid", "REGISTER_REQUIRED_DATE", target="20280101", overrides={"created_at": "not-a-date"})
        _stop("STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_INVALID", lambda: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=invalid, target_date="20280101", requirement="synthetic"), mutation_id="CA_TIMESTAMP_INVALID", test_name="test_round2_t9_all_tail_fields_and_timestamp_binding")
        future = _artifact(binding, "future", "REGISTER_REQUIRED_DATE", target="20280101", overrides={"created_at": "2099-01-01T00:00:00+09:00"})
        _stop("STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_ORDER", lambda: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=future, target_date="20280101", requirement="synthetic"), mutation_id="CA_TIMESTAMP_APPEND_ORDER", test_name="test_round2_t9_all_tail_fields_and_timestamp_binding")
        # Reconciliation, not merely append, rejects an already-written tail
        # whose ledger timestamp has been moved before its external artifact.
        stable = root / "reconcile"; stable.mkdir(); stable_ledger, _, stable_paths = _chain(stable)
        row = json.loads(stable_paths[-1].read_text(encoding="utf-8")); row["created_at_jst"] = "2019-12-01T00:00:00+09:00"; row["registered_date"] = "20191201"; stable_paths[-1].write_text(json.dumps(row), encoding="utf-8")
        _stop("STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_ORDER", stable_ledger.actions, mutation_id="CA_TIMESTAMP_RECONCILE_ORDER", test_name="test_round2_t9_all_tail_fields_and_timestamp_binding")
        MUTATION_RESULTS.append({"mutation_id": "CA_APPEND_RECONCILIATION", "targeted_guard": "post-write ledger/artifact reconciliation timestamp order", "mutation_applied": "YES", "test_name": "test_round2_t9_all_tail_fields_and_timestamp_binding", "expected_result": "STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_ORDER", "actual_result": "STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_ORDER", "detected": "YES", "detection_type": "BEHAVIORAL_MUTATION_TEST"})
    finally: shutil.rmtree(root)


def test_round2_content_addressed_store_guards() -> None:
    root = _box()
    try:
        # The artifact is already ledger-linked before each targeted mutation;
        # no orphan guard can satisfy these assertions.
        for name, mutate, expected, probe_id in (
            ("filename", _rename_content_file_only, "STOP_HUMAN_ACTION_ARTIFACT_FILENAME_SHA_MISMATCH", "CA_FILENAME_CONTENT_SHA"),
            ("sidecar", lambda p: p.with_name(p.name + ".sha256").write_text("0" * 64, encoding="utf-8"), "STOP_HUMAN_ACTION_ARTIFACT_SIDECAR_SHA_MISMATCH", "CA_SIDECAR_CONTENT"),
            ("missing_sidecar", lambda p: p.with_name(p.name + ".sha256").unlink(), "STOP_HUMAN_ACTION_ARTIFACT_SIDECAR_MISSING", "CA_SIDECAR_EXISTS"),
        ):
            probe = root / name; probe.mkdir(); binding = _binding(probe); ledger = GovernanceLedger(probe / "ledger", "TECH", AUTH, binding); path = _artifact(binding, "A", "REGISTER_REQUIRED_DATE", target="20280101"); ledger.append("REGISTER_REQUIRED_DATE", human_artifact=path, target_date="20280101", requirement="synthetic"); mutate(path)
            _stop(expected, ledger.actions, mutation_id=probe_id, test_name="test_round2_content_addressed_store_guards")
        # Binding fields are checked before a ledger can accept the artifact.
        for field, value, expected, probe_id in (("authorization_artifact_sha256", "b" * 64, "STOP_HUMAN_ACTION_ARTIFACT_AUTHORIZATION_SHA_BINDING", "CA_AUTH_SHA"), ("authorization_id", "OTHER", "STOP_HUMAN_ACTION_ARTIFACT_AUTHORIZATION_ID_BINDING", "CA_AUTH_ID"), ("protocol_identity", "OTHER", "STOP_HUMAN_ACTION_ARTIFACT_PROTOCOL_BINDING", "CA_PROTOCOL")):
            probe = root / field; probe.mkdir(); binding = _binding(probe); ledger = GovernanceLedger(probe / "ledger", "TECH", AUTH, binding); path = _artifact(binding, "A", "REGISTER_REQUIRED_DATE", target="20280101", overrides={field: value})
            _stop(expected, lambda path=path: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=path, target_date="20280101", requirement="synthetic"), mutation_id=probe_id, test_name="test_round2_content_addressed_store_guards")
        missing = HumanArtifactStoreBinding(root / "absent", "TECH", AUTH, SCHEMA_NAME, SCHEMA_VERSION)
        _stop("STOP_HUMAN_ACTION_ARTIFACT_STORE_MISSING", lambda: GovernanceLedger(root / "ledger_missing", "TECH", AUTH, missing).actions(), mutation_id="CA_STORE_MISSING", test_name="test_round2_content_addressed_store_guards")
        outside_root = root / "outside"; outside_root.mkdir(); outside = _binding(outside_root); outside_path = _artifact(outside, "O", "REGISTER_REQUIRED_DATE", target="20280101")
        inside_root = root / "inside"; inside_root.mkdir(); inside = _binding(inside_root); inside_ledger = GovernanceLedger(inside_root / "ledger", "TECH", AUTH, inside)
        _stop("STOP_HUMAN_ACTION_ARTIFACT_OUTSIDE_STORE", lambda: inside_ledger.append("REGISTER_REQUIRED_DATE", human_artifact=outside_path, target_date="20280101", requirement="synthetic"), mutation_id="CA_OUTSIDE_STORE", test_name="test_round2_content_addressed_store_guards")
        # A pre-existing orphan is never masked by the currently appended artifact.
        probe = root / "orphan"; probe.mkdir(); ledger, binding, _ = _chain(probe); _artifact(binding, "orphan", "REGISTER_REQUIRED_DATE", target="20280109")
        path = _artifact(binding, "new", "REGISTER_REQUIRED_DATE", target="20280110")
        before = len(list(ledger.root.glob("*.json")))
        _stop("STOP_ORPHAN_HUMAN_ACTION_ARTIFACT", lambda: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=path, target_date="20280110", requirement="synthetic"), mutation_id="CA_APPEND_ORPHAN", test_name="test_round2_content_addressed_store_guards")
        assert len(list(ledger.root.glob("*.json"))) == before
        tech_probe = root / "tech"; tech_probe.mkdir(); binding = _binding(tech_probe); ledger = GovernanceLedger(tech_probe / "ledger", "TECH", AUTH, binding); tech = _artifact(binding, "tech", "REGISTER_REQUIRED_DATE", target="20280101", overrides={"human_identity": "TECHNICAL_TEST_ONLY"})
        _stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY", lambda: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=tech, target_date="20280101", requirement="synthetic"), mutation_id="CA_TECHNICAL_IDENTITY", test_name="test_round2_content_addressed_store_guards")
        technical_action = _artifact(binding, "TECHNICAL_TEST_ONLY", "REGISTER_REQUIRED_DATE", target="20280102")
        _stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY", lambda: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=technical_action, target_date="20280102", requirement="synthetic"))
    finally: shutil.rmtree(root)


def test_round2_formal_store_binding_is_required() -> None:
    # Formal callers construct this binding after authorization validation; no
    # unbound GovernanceLedger fallback is available on those public paths.
    _stop("STOP_HUMAN_ACTION_ARTIFACT_STORE_BINDING", lambda: HumanArtifactStoreBinding.from_authorization({"authorization_id": "TECH"}, AUTH))


def test_round2_append_semantic_preflight_atomicity() -> None:
    """Artifact-first semantic disagreement never creates a ledger record."""
    root = _box()
    try:
        for name, artifact_overrides, append_kwargs in (
            ("requirement", {"requirement": "artifact requirement"}, {"requirement": "ledger requirement"}),
            ("exemption", {"exemption_reason": "artifact exemption"}, {"exemption_reason": "ledger exemption"}),
        ):
            probe = root / name; probe.mkdir(); binding = _binding(probe); ledger = GovernanceLedger(probe / "ledger", "TECH", AUTH, binding)
            artifact = _artifact(binding, name, "REGISTER_REQUIRED_DATE", target="20280101", overrides=artifact_overrides)
            before = len(list(ledger.root.glob("*.json"))) if ledger.root.exists() else 0
            _stop("STOP_HUMAN_ACTION_ARTIFACT_LEDGER_MISMATCH", lambda artifact=artifact, append_kwargs=append_kwargs: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=artifact, target_date="20280101", **append_kwargs), mutation_id=f"CA_APPEND_{name.upper()}", test_name="test_round2_append_semantic_preflight_atomicity")
            assert (len(list(ledger.root.glob("*.json"))) if ledger.root.exists() else 0) == before
        # Authorization/source fields are supplied by the external artifact;
        # each malformed value is rejected before a first ledger write.
        for name, overrides, expected in (
            ("human_auth", {"human_authorization_artifact_sha256": "b" * 64}, "STOP_HUMAN_ACTION_ARTIFACT_AUTHORIZATION_SHA_BINDING"),
            ("source", {"source_artifact_sha256": "not-a-sha"}, "STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY"),
        ):
            probe = root / name; probe.mkdir(); binding = _binding(probe); ledger = GovernanceLedger(probe / "ledger", "TECH", AUTH, binding)
            artifact = _artifact(binding, name, "REGISTER_REQUIRED_DATE", target="20280101", overrides=overrides)
            _stop(expected, lambda artifact=artifact: ledger.append("REGISTER_REQUIRED_DATE", human_artifact=artifact, target_date="20280101", requirement="synthetic"), mutation_id=f"CA_APPEND_{name.upper()}", test_name="test_round2_append_semantic_preflight_atomicity")
            assert not ledger.root.exists() or not list(ledger.root.glob("*.json"))
    finally: shutil.rmtree(root)
