"""Read-only binding and reconciliation for Human-authoritative action artifacts.

The prospective runtime never creates, edits, or deletes files in this store.
Only synthetic tests are permitted to create fixture artifacts.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from review.current_corrected_shadow_v2_prospective_protocol_v1 import ROOT, Stop
from review.current_corrected_shadow_v2_prospective_state_v1 import PROTOCOL_IDENTITY

SCHEMA_NAME = "CURRENT_CORRECTED_SHADOW_V2_HUMAN_ACTION_ARTIFACT_STORE"
SCHEMA_VERSION = "v1"
ACTION_TYPES = {"REGISTER_REQUIRED_DATE", "SUSPEND", "RESUME", "TERMINATE_RUN"}
_HASH = re.compile(r"^[0-9a-f]{64}$")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_INVALID")
    return parsed


def _canonical_optional(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY")
    return value


@dataclass(frozen=True)
class HumanArtifactStoreBinding:
    root: Path
    authorization_id: str
    authorization_artifact_sha256: str
    schema_name: str
    schema_version: str

    @classmethod
    def from_authorization(cls, authorization: dict[str, Any], authorization_sha256: str) -> "HumanArtifactStoreBinding":
        root_value = authorization.get("human_action_artifact_root")
        if (
            authorization.get("human_action_artifact_store_schema") != SCHEMA_NAME
            or authorization.get("human_action_artifact_store_version") != SCHEMA_VERSION
            or not isinstance(root_value, str)
            or not root_value.strip()
            or not isinstance(authorization.get("authorization_id"), str)
        ):
            raise Stop("STOP_HUMAN_ACTION_ARTIFACT_STORE_BINDING")
        candidate = Path(root_value)
        root = candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()
        # A relative binding must not escape the repository.  Absolute paths are
        # allowed because the authorized store is deliberately external.
        if not candidate.is_absolute():
            try:
                root.relative_to(ROOT.resolve())
            except ValueError as exc:
                raise Stop("STOP_HUMAN_ACTION_ARTIFACT_STORE_BINDING") from exc
        return cls(root, authorization["authorization_id"], authorization_sha256, SCHEMA_NAME, SCHEMA_VERSION)


def _read_record(path: Path, binding: HumanArtifactStoreBinding) -> tuple[str, dict[str, Any]]:
    if not path.is_file() or path.suffix != ".json" or not _HASH.fullmatch(path.stem):
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_FILENAME_SHA_MISMATCH")
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.is_file():
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_SIDECAR_MISSING")
    digest = sha(path)
    if path.stem != digest:
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_FILENAME_SHA_MISMATCH")
    if sidecar.read_text(encoding="utf-8").strip() != digest:
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_SIDECAR_SHA_MISMATCH")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY") from exc
    required = {
        "artifact_schema", "artifact_version", "action_identity", "action_type",
        "protocol_identity", "authorization_id", "authorization_artifact_sha256",
        "human_identity", "created_at", "effective_date", "target_date", "reason",
        "requirement", "exemption_reason", "source_artifact_sha256",
        "human_authorization_artifact_sha256",
    }
    if not isinstance(value, dict) or required - set(value):
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY")
    strings = ("action_identity", "human_identity", "reason")
    if value.get("artifact_schema") != binding.schema_name or value.get("artifact_version") != binding.schema_version:
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY")
    if value.get("protocol_identity") != PROTOCOL_IDENTITY:
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_PROTOCOL_BINDING")
    if value.get("authorization_id") != binding.authorization_id:
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_AUTHORIZATION_ID_BINDING")
    if value.get("authorization_artifact_sha256") != binding.authorization_artifact_sha256 or value.get("human_authorization_artifact_sha256") != binding.authorization_artifact_sha256:
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_AUTHORIZATION_SHA_BINDING")
    if value.get("action_type") not in ACTION_TYPES or any(not isinstance(value.get(field), str) or not value[field].strip() for field in strings):
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY")
    parse_timestamp(value["created_at"])
    if value["human_identity"].strip() == "TECHNICAL_TEST_ONLY" or value["action_identity"].strip() == "TECHNICAL_TEST_ONLY":
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY")
    if value.get("effective_date") is not None and not isinstance(value.get("effective_date"), str):
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY")
    if value.get("target_date") is not None and not isinstance(value.get("target_date"), str):
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY")
    value["requirement"] = _canonical_optional(value.get("requirement"))
    value["exemption_reason"] = _canonical_optional(value.get("exemption_reason"))
    source = value.get("source_artifact_sha256")
    if source is not None and (not isinstance(source, str) or not _HASH.fullmatch(source)):
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_INTEGRITY")
    return digest, value


def discover(binding: HumanArtifactStoreBinding) -> dict[str, dict[str, Any]]:
    if not binding.root.is_dir():
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_STORE_MISSING")
    found: dict[str, dict[str, Any]] = {}
    identities: set[str] = set()
    for path in sorted(binding.root.glob("*.json")):
        digest, value = _read_record(path, binding)
        if digest in found:
            raise Stop("STOP_DUPLICATE_HUMAN_ACTION_ARTIFACT_REFERENCE")
        identity = value["action_identity"]
        if identity in identities:
            raise Stop("STOP_DUPLICATE_HUMAN_ACTION_IDENTITY_ARTIFACT")
        identities.add(identity)
        found[digest] = value
    return found


def validate_external_artifact(path: Path, binding: HumanArtifactStoreBinding, *, action_type: str, effective_date: str | None, target_date: str | None, requirement: str | None = None, exemption_reason: str | None = None) -> tuple[str, dict[str, Any]]:
    try:
        path.resolve().relative_to(binding.root.resolve())
    except ValueError as exc:
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_OUTSIDE_STORE") from exc
    digest, value = _read_record(path, binding)
    if (
        value["action_type"] != action_type
        or value.get("effective_date") != effective_date
        or value.get("target_date") != target_date
        or value.get("requirement") != _canonical_optional(requirement)
        or value.get("exemption_reason") != _canonical_optional(exemption_reason)
    ):
        raise Stop("STOP_HUMAN_ACTION_ARTIFACT_LEDGER_MISMATCH")
    return digest, value


def reconcile(actions: list[dict[str, Any]], binding: HumanArtifactStoreBinding, *, pending_artifact_sha256: str | None = None) -> None:
    artifacts = discover(binding)
    references: set[str] = set()
    identities: set[str] = set()
    for action in actions:
        digest = action.get("human_action_artifact_sha256")
        identity = action.get("human_action_identity")
        if not isinstance(digest, str) or not isinstance(identity, str):
            raise Stop("STOP_MISSING_HUMAN_ACTION_ARTIFACT")
        if digest in references:
            raise Stop("STOP_DUPLICATE_HUMAN_ACTION_ARTIFACT_REFERENCE")
        if identity in identities:
            raise Stop("STOP_DUPLICATE_HUMAN_ACTION_IDENTITY_LEDGER")
        references.add(digest); identities.add(identity)
        artifact = artifacts.get(digest)
        if artifact is None:
            raise Stop("STOP_MISSING_HUMAN_ACTION_ARTIFACT")
        try:
            artifact_created = parse_timestamp(artifact.get("created_at"))
            ledger_created = parse_timestamp(action.get("created_at_jst"))
        except Stop:
            raise
        if artifact_created > ledger_created:
            raise Stop("STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_ORDER")
        pairs = {
            "action_identity": identity,
            "action_type": action.get("action_type"),
            "human_identity": action.get("human_identity"),
            "reason": action.get("reason"),
            "effective_date": action.get("effective_date"),
            "target_date": action.get("target_date"),
            "requirement": action.get("requirement"),
            "exemption_reason": action.get("exemption_reason"),
            "source_artifact_sha256": action.get("source_artifact_sha256"),
            "human_authorization_artifact_sha256": action.get("human_authorization_artifact_sha256"),
        }
        if any(artifact.get(key) != value for key, value in pairs.items()):
            raise Stop("STOP_HUMAN_ACTION_ARTIFACT_LEDGER_MISMATCH")
        if action.get("authorization_id") != binding.authorization_id or action.get("authorization_artifact_sha256") != binding.authorization_artifact_sha256:
            raise Stop("STOP_GOVERNANCE_LEDGER_INTEGRITY")
    permitted_orphans = {pending_artifact_sha256} if pending_artifact_sha256 is not None else set()
    if set(artifacts) != references | permitted_orphans:
        raise Stop("STOP_ORPHAN_HUMAN_ACTION_ARTIFACT")
