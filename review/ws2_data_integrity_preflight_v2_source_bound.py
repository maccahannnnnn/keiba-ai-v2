"""WS2 v2 canonical-format preflight implementation.

This is a read-only compatibility gate.  It maps the repository's actual V5
package, headerless TARGET sources and race prediction artifacts to canonical
audit records; it never trains, predicts, calculates performance, or changes
a source artifact.
"""
from __future__ import annotations

import ast
import csv
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from review.ws2_data_integrity_preflight_v2 import DataIntegrityStop, sha256

CONTRACT_PATH = "docs/ws2_data_integrity_preflight_v2_contract_revision_10.json"
POLICY_PATH = "docs/ws2_v5_feature_source_policy_v5.json"
DATASET_ROOT = "reports/ml_v4_buy_selection_dataset_v5_1"
MODEL_ROOT = "reports/ml_v4_buy_selection_model_v5"
# These two pins are updated only together with their additive policy/contract
# revisions.  They bind the formal-readiness gate without changing any frozen
# dataset, model, raw-source, or prediction artifact.
CONTRACT_SHA256 = "f1b3e791cbaf8839b2879d2d15b76906db53db524f62e8876d207c71a316a2a5"
POLICY_SHA256 = "82e19e197f3b7f335a8b234c784a7f57663670470844fa1003e75d8922846e72"
CANONICAL_DATASET_CSV_SHA256 = "ac0a73b36ea6c2e03a2f9df41417ea81561a2de9c55e392e71a0e73448a7e2b7"
CANONICAL_DATASET_MANIFEST_SHA256 = "3bbb8ccd77247a6f976d13f7bee1d7e2761dac12363f0d8302cdca4a8be45522"
CANONICAL_DATASET_HASH_INDEX_SHA256 = "8a76812e49c8abbbaf82748637ec19441d2abd05edb03ef5258d9a0cf52d2589"
CANONICAL_DATASET_VERSION = "ML_V4_TRAIN_DATASET_V5_1_CORRECTED"
CANONICAL_DATASET_ROW_COUNT = 5530
CANONICAL_DATASET_FEATURE_COUNT = 21
SOURCE_LINEAGE_CORRECTION_PATH = "reports/ml_v4_buy_selection_dataset_v5_source_lineage_correction_20260418_v1/correction.json"
SOURCE_LINEAGE_CORRECTION_SHA256 = "03d086df4effea266f3aeebd12e56a2d60fa668c74adfabbbc99a8f1e487da67"
SOURCE_LINEAGE_CORRECTION_DATE = "20260418"
SOURCE_LINEAGE_CORRECTION_KINDS = ("DE", "DG", "DS")
KNOWN_EXCLUSION_BRIDGE_PATH = "reports/ws2_known_data_integrity_exclusion_bridge_20260823_v1/exclusion_bridge.json"
KNOWN_EXCLUSION_BRIDGE_SHA256 = "c905411baf3499647a57a77ed21ad996ba3051d0c644f025c263f8726ff0fd3a"
KNOWN_EXCLUSION_DATE = "20260823"
KNOWN_EXCLUSION_RACE_ID = "race_20260823_niigata_7R"
KNOWN_EXCLUSION_VENUE = "新潟"
KNOWN_EXCLUSION_RACE_NUMBER = 7
KNOWN_EXCLUSION_HORSE_NUMBER = 6
KNOWN_EXCLUSION_HORSE_NAME = "マインドフルネス"
KNOWN_EXCLUSION_REGISTRATION_ID = "24103226"
KNOWN_EXCLUSION_SOURCE_KINDS = ("DG", "DE", "DS")
KNOWN_ADAPTER_COMPATIBILITY_REUSE_PATH = "reports/ws2_existing_adapter_compatibility_reuse_20260906_v1/compatibility_reuse.json"
KNOWN_ADAPTER_COMPATIBILITY_REUSE_SHA256 = "52f96c8fb7d4b8f0a6164bb59233305f595a0c21f7c185047ea204773d03ad26"
KNOWN_ADAPTER_COMPATIBILITY_DATE = "20260906"
KNOWN_ADAPTER_COMPATIBILITY_RACE_ID = "race_20260906_hanshin_11R"
KNOWN_ADAPTER_COMPATIBILITY_SOURCE_KINDS = ("DG", "DE", "DS")
REQUIRED_DATASET = ("dataset.csv", "feature_schema.json", "training_manifest.json", "source_date_manifest.json", "exclusion_manifest.json", "lineage.json", "artifact_hash_index.json")
REQUIRED_MODEL = ("model.joblib", "scaler.joblib", "model_metadata.json", "training_manifest.json", "training_recipe.json", "deterministic_reproduction.json", "runtime_environment.json", "artifact_hash_index.json")
SHA_REQUIRED = frozenset({"dataset", "prediction", "DG", "DE", "DS", "result_primary", "exclusion_manifest", "model", "scaler"})
PROTECTED = {"UNTOUCHED_CANDIDATE", "PROSPECTIVE", "EXCLUDED", "ROLE_UNKNOWN_PROTECTED"}


def _stop(code: str) -> None:
    raise DataIntegrityStop(code)


class FeatureSourceValueMismatch(DataIntegrityStop):
    """Fail closed while retaining the minimum source-bound audit context."""

    def __init__(self, context: dict[str, Any]) -> None:
        super().__init__("STOP_FEATURE_SOURCE_VALUE_MISMATCH")
        self.context = context


class HashValidationStop(DataIntegrityStop):
    """Fail closed with machine-readable hash/authority context."""

    def __init__(self, code: str, context: dict[str, Any]) -> None:
        super().__init__(code)
        self.context = {**context, "stop_code": code}


def _strict_label_boolean(value: Any) -> bool:
    """Normalize only the frozen boolean label representations.

    Python truthiness is deliberately not used: in particular, ``bool("0")``
    is unsafe for the V5 label columns.  Every representation outside the
    explicit contract fails closed before a label comparison can proceed.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "1":
            return True
        if normalized == "0":
            return False
        lowered = normalized.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    _stop("STOP_LABEL_BOOLEAN_REPRESENTATION_UNSUPPORTED")


def _json(path: Path) -> Any:
    if not path.is_file():
        _stop("STOP_CANONICAL_SOURCE_MISSING")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _stop("STOP_CANONICAL_SOURCE_MALFORMED")


def _csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        _stop("STOP_CANONICAL_SOURCE_MISSING")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            _stop("STOP_CANONICAL_SOURCE_MALFORMED")
        return list(reader.fieldnames), list(reader)


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _date(value: Any) -> str:
    value = str(value).replace("-", "")
    if len(value) != 8 or not value.isdigit():
        _stop("STOP_INVALID_SOURCE_DATE")
    return value


def _verified_overlay_chain(root: Path, leaf: Path) -> dict[str, Any]:
    """Load additive policy/contract overlays from oldest to newest.

    Each link pins its immediate base by SHA256.  This keeps Revision 10 / Policy
    v5 additive while allowing the active authority to retain every prior v3/v4
    field instead of relying on an implicit one-level merge.
    """
    chain: list[tuple[Path, dict[str, Any]]] = []
    current = leaf
    visited: set[Path] = set()
    while current not in visited:
        visited.add(current)
        value = _json(current)
        chain.append((current, value))
        base_value = value.get("base_policy_path", value.get("base_contract_path"))
        base_sha = value.get("base_policy_sha256", value.get("base_contract_sha256"))
        if not base_value:
            break
        base = root / str(base_value)
        if not base.is_file() or sha256(base) != base_sha:
            _stop("STOP_FIXED_POLICY_OR_CONTRACT_INVALID")
        current = base
    else:
        _stop("STOP_FIXED_POLICY_OR_CONTRACT_INVALID")
    merged: dict[str, Any] = {}
    for _, value in reversed(chain):
        merged.update(value)
    return merged


def _git_blob_sha256(root: Path, commit: str, relative_path: str) -> str | None:
    """Return a tracked historical blob digest, never a working-tree fallback."""
    normalized = relative_path.replace("\\", "/").lstrip("/")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not normalized or ".." in Path(normalized).parts:
        return None
    commit_check = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if commit_check.returncode:
        return None
    blob = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{normalized}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if blob.returncode:
        return None
    import hashlib
    return hashlib.sha256(blob.stdout).hexdigest()


class CanonicalSourceMaterializer:
    """Materialize only actual repository formats with mandatory SHA binding."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.sources: list[dict[str, str]] = []
        self.policy_path, self.contract_path = self.root / POLICY_PATH, self.root / CONTRACT_PATH
        if sha256(self.policy_path) != POLICY_SHA256 or sha256(self.contract_path) != CONTRACT_SHA256:
            _stop("STOP_FIXED_POLICY_OR_CONTRACT_HASH_MISMATCH")
        self.policy = _verified_overlay_chain(self.root, self.policy_path)
        self.contract = _verified_overlay_chain(self.root, self.contract_path)
        if (
            self.policy.get("caller_override") != "PROHIBITED"
            or self.policy.get("dataset_package") != DATASET_ROOT
            or self.policy.get("canonical_dataset_package") != CANONICAL_DATASET_VERSION
            or self.policy.get("canonical_dataset_role") != "PRE_SAFE_CORRECTED_TRAINING_DATASET"
            or self.policy.get("frozen_v5_role") != "LEGACY_CONTAMINATED_TRAINING_DIAGNOSTIC_ONLY"
            or self.policy.get("frozen_v5_formal_preflight_eligible") is not False
            or self.policy.get("dataset_package_identity") != "MANIFEST_AND_SHA_PINNED"
            or self.policy.get("row_level_dataset_version_field_authority") != "NON_AUTHORITATIVE_INHERITED_METADATA"
            or self.policy.get("row_level_dataset_version_selector") != "PROHIBITED"
            or self.contract.get("SOURCE_BOUND_EVIDENCE_REQUIRED") is not True
            or self.contract.get("WS2_CANONICAL_PREFLIGHT_DATASET") != CANONICAL_DATASET_VERSION
            or self.contract.get("DATASET_PACKAGE_SELECTION") != "EXACT_PATH_AND_SHA_FAIL_CLOSED"
            or self.contract.get("LEGACY_V5_PREFLIGHT_SELECTION") != "PROHIBITED"
            or self.contract.get("ROW_LEVEL_DATASET_VERSION_FIELD_AUTHORITY") != "NON_AUTHORITATIVE_INHERITED_METADATA"
            or self.contract.get("PACKAGE_MANIFEST_AND_SHA_AUTHORITY") != "CANONICAL"
            or self.contract.get("SOURCE_LINEAGE_CORRECTION_POLICY") != "ADDITIVE_FAIL_CLOSED"
            or self.contract.get("HUMAN_APPROVED_DATE_SPECIFIC_DATA_INTEGRITY_EXCLUSION_POLICY") != "ADDITIVE_FAIL_CLOSED_EXACT_SCOPE_ONLY"
            or self.contract.get("EXISTING_ADAPTER_COMPATIBILITY_REUSE_POLICY") != "ADDITIVE_FAIL_CLOSED_EXACT_SCOPE_ONLY"
            or self.contract.get("BOOLEAN_LABEL_COMPARISON") != "STRICT_SEMANTIC_NORMALIZATION_FAIL_CLOSED"
            or self.contract.get("ADJUSTED_SCORE_GAP_TO_TOP_SCOPE") != "CURRENT_TOP5_PRE_RESULT"
            or self.contract.get("RESULT_DEPENDENT_FEATURE_DERIVATION") != "PROHIBITED"
            or self.contract.get("FEATURE_COMPUTATION_ORDER") != "PRE_FEATURES_BEFORE_RESULT_VALIDITY_FILTER"
            or self.policy.get("MODEL_ACTIVATION_RECORD_AUTHORITY") != "INDEPENDENT_SHA_PINNED"
            or self.policy.get("MODEL_ACTIVATION_RECORD_FROZEN_INDEX_MEMBER") is not False
            or self.policy.get("EMPTY_EXPECTED_SHA_FALLBACK") != "PROHIBITED"
            or self.policy.get("PIT_EVIDENCE_SOURCE") != "PER_PREDICTION_PROVENANCE_AND_GIT_IDENTITY"
            or self.contract.get("FORMAL_READINESS_GATE_CORRECTION") != "ADDITIVE_FAIL_CLOSED"
            or self.contract.get("ACTUAL_FINISH_VALIDATION_REQUIREMENT") != "OPTIONAL_DIAGNOSTIC"
        ):
            _stop("STOP_FIXED_POLICY_OR_CONTRACT_INVALID")
        self._record(self.policy_path)
        self._record(self.contract_path)

    def _record(self, path: Path) -> None:
        self.sources.append({"path": _rel(self.root, path), "sha256": sha256(path)})

    def _require_hash(self, expected: Any, kind: str, *, stage: str = "required_sha_authority", path: Path | None = None, authority_path: str | None = None, authority_sha: str | None = None, index_path: Path | None = None) -> str:
        # Every call site supplies a required authority.  Absence must never
        # become an empty expected SHA and later masquerade as a mismatch.
        if not isinstance(expected, str) or len(expected) != 64:
            self._hash_stop("STOP_REQUIRED_SOURCE_SHA_MISSING", stage=stage, role=kind, path=path or self.root, expected=None, authority_path=authority_path, authority_sha=authority_sha, index_path=index_path)
        return expected.lower()

    def _hash_stop(self, code: str, *, stage: str, role: str, path: Path, expected: str | None, actual: str | None = None, authority_path: str | None = None, authority_sha: str | None = None, index_path: Path | None = None) -> None:
        raise HashValidationStop(code, {"validation_stage": stage, "artifact_role": role, "artifact_path": _rel(self.root, path), "expected_sha256": expected, "actual_sha256": actual, "expected_sha_authority_path": authority_path, "expected_sha_authority_sha256": authority_sha, "package_hash_index_path": _rel(self.root, index_path) if index_path else None, "classification": "IMPLEMENTATION_COMPATIBILITY_STOP" if code == "STOP_ARTIFACT_HASH_INDEX_REQUIRED_ENTRY_MISSING" else "DATA_INTEGRITY_STOP"})

    def package(self, relative: str, required: tuple[str, ...]) -> Path:
        root = self.root / relative
        hashes = _json(root / "artifact_hash_index.json").get("indexed_artifacts")
        if not isinstance(hashes, dict):
            _stop("STOP_ARTIFACT_HASH_INDEX_SCHEMA")
        for name in required:
            path = root / name
            if not path.is_file():
                _stop("STOP_CANONICAL_SOURCE_MISSING")
            if name != "artifact_hash_index.json":
                kind = "dataset" if relative == DATASET_ROOT and name == "dataset.csv" else "model" if name == "model.joblib" else "scaler" if name == "scaler.joblib" else "package"
                expected = hashes.get(name)
                if not isinstance(expected, str) or len(expected) != 64:
                    self._hash_stop("STOP_ARTIFACT_HASH_INDEX_REQUIRED_ENTRY_MISSING", stage="package_hash_index_membership", role=kind, path=path, expected=None, index_path=root / "artifact_hash_index.json")
                actual = sha256(path)
                if actual != expected:
                    self._hash_stop("STOP_SOURCE_HASH_MISMATCH", stage="package_hash_index_validation", role=kind, path=path, expected=expected, actual=actual, index_path=root / "artifact_hash_index.json")
            self._record(path)
        return root

    def canonical_dataset_package(self) -> Path:
        """Resolve exactly the reviewed V5.1 package, never a path discovery result."""
        identity = self.policy.get("canonical_dataset_identity")
        expected_identity = {
            "path": DATASET_ROOT,
            "dataset_csv_sha256": CANONICAL_DATASET_CSV_SHA256,
            "dataset_manifest_sha256": CANONICAL_DATASET_MANIFEST_SHA256,
            "artifact_hash_index_sha256": CANONICAL_DATASET_HASH_INDEX_SHA256,
            "dataset_version": CANONICAL_DATASET_VERSION,
            "row_count": CANONICAL_DATASET_ROW_COUNT,
            "feature_count": CANONICAL_DATASET_FEATURE_COUNT,
        }
        if identity != expected_identity:
            _stop("STOP_CANONICAL_DATASET_POLICY_IDENTITY_MISMATCH")
        root = self.root / DATASET_ROOT
        index_path = root / "artifact_hash_index.json"
        if not index_path.is_file():
            _stop("STOP_CANONICAL_SOURCE_MISSING")
        if sha256(index_path) != CANONICAL_DATASET_HASH_INDEX_SHA256:
            _stop("STOP_CANONICAL_DATASET_HASH_INDEX_MISMATCH")
        dataset_root = self.package(DATASET_ROOT, REQUIRED_DATASET)
        if sha256(dataset_root / "dataset.csv") != CANONICAL_DATASET_CSV_SHA256:
            _stop("STOP_CANONICAL_DATASET_SHA_MISMATCH")
        if sha256(dataset_root / "dataset_manifest.json") != CANONICAL_DATASET_MANIFEST_SHA256:
            _stop("STOP_CANONICAL_DATASET_MANIFEST_SHA_MISMATCH")
        manifest, schema = _json(dataset_root / "dataset_manifest.json"), _json(dataset_root / "feature_schema.json")
        if (
            manifest.get("dataset_version") != CANONICAL_DATASET_VERSION
            or manifest.get("dataset_sha256") != CANONICAL_DATASET_CSV_SHA256
            or manifest.get("row_count") != CANONICAL_DATASET_ROW_COUNT
            or manifest.get("feature_count") != CANONICAL_DATASET_FEATURE_COUNT
            or schema.get("dataset_version") != CANONICAL_DATASET_VERSION
            or len(schema.get("semantic_feature_order", [])) != CANONICAL_DATASET_FEATURE_COUNT
        ):
            _stop("STOP_CANONICAL_DATASET_MANIFEST_IDENTITY_INVALID")
        _, rows = _csv(dataset_root / "dataset.csv")
        if len(rows) != CANONICAL_DATASET_ROW_COUNT:
            _stop("STOP_CANONICAL_DATASET_ROW_COUNT_MISMATCH")
        return dataset_root

    def source_manifest(self, dataset_root: Path, dataset_rows: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
        """Join actual raw ``sources`` to ``additive_prediction_sources``."""
        manifest = _json(dataset_root / "source_date_manifest.json")
        roots, direct = {}, set()
        for item in manifest.get("additive_prediction_sources", []):
            date, prediction_root = _date(item.get("date")), item.get("prediction_root")
            if not isinstance(prediction_root, str) or not prediction_root:
                _stop("STOP_PREDICTION_ROOT_UNPROVEN")
            roots[date] = prediction_root
            direct.add(date)
        # Parent rows preserve their own frozen artifact paths.  This is the
        # authoritative recursive-lineage fallback for dates not added by V5.
        # Read and record each available parent lineage rather than silently
        # shrinking the 62-date source universe to additive dates.
        lineage_path = dataset_root / "lineage.json"
        parent = _json(lineage_path).get("parent") if lineage_path.is_file() else None
        visited = set()
        while parent and parent not in visited:
            visited.add(parent)
            suffix = str(parent).lower().replace("ml_v4_train_dataset_", "ml_v4_buy_selection_dataset_")
            parent_root = self.root / "reports" / suffix
            lineage = parent_root / "lineage.json"
            if not lineage.is_file():
                break
            self._record(lineage)
            parent = _json(lineage).get("parent")
        for row in dataset_rows or []:
            date, artifact = _date(row.get("date")), row.get("source_prediction_artifact_path")
            normalized = artifact.replace("\\", "/") if isinstance(artifact, str) else ""
            if date not in roots and normalized.startswith("reports/"):
                roots[date] = str(Path(normalized).parent).replace("\\", "/")
        result = []
        for item in manifest.get("sources", []):
            date, files = _date(item.get("date")), item.get("files")
            if not isinstance(files, dict) or date not in roots or any(kind not in files for kind in ("DG", "DE", "DS", "result_primary")):
                _stop("STOP_CANONICAL_SOURCE_MANIFEST_SCHEMA")
            corrected_files, overlay = self._source_lineage_overlay(date, files)
            bridge = self._known_data_integrity_exclusion_bridge(date, corrected_files)
            adapter_reuse = self._existing_adapter_compatibility_reuse(date, corrected_files)
            result.append({"date": date, "files": corrected_files, "prediction_root": roots[date], "prediction_source_kind": "DIRECT_ADDITIVE" if date in direct else "INHERITED_PARENT", "declared_source_races": item.get("source_races"), "source_lineage_overlay": overlay, "known_data_integrity_exclusion_bridge": bridge, "existing_adapter_compatibility_reuse": adapter_reuse})
        if not result:
            _stop("STOP_CANONICAL_SOURCE_MANIFEST_SCHEMA")
        return result

    def _source_lineage_overlay(self, date: str, manifest_files: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Apply the sole approved April source correction in memory, or stop.

        This deliberately has no discovery mechanism: the correction record, its
        digest, date and three source kinds are fixed constants.  The frozen V5
        source manifest is never written or rewritten.
        """
        if date != SOURCE_LINEAGE_CORRECTION_DATE:
            return manifest_files, None
        record_path = self.root / SOURCE_LINEAGE_CORRECTION_PATH
        if not record_path.is_file() or sha256(record_path) != SOURCE_LINEAGE_CORRECTION_SHA256:
            _stop("STOP_SOURCE_LINEAGE_CORRECTION_RECORD_HASH_MISMATCH")
        correction = _json(record_path)
        if (
            correction.get("repair_type") != "SOURCE_LINEAGE_INTEGRITY_REPAIR"
            or correction.get("target_date") != SOURCE_LINEAGE_CORRECTION_DATE
            or tuple(correction.get("scope", [])) != SOURCE_LINEAGE_CORRECTION_KINDS
            or correction.get("corrected_role") != "AUTHORITATIVE_APRIL_PRE_SOURCE"
        ):
            _stop("STOP_SOURCE_LINEAGE_CORRECTION_RECORD_SCHEMA")
        old_sources = correction.get("old_sources")
        corrected_sources = correction.get("corrected_sources")
        authority = correction.get("authority_references")
        if not all(isinstance(value, dict) for value in (old_sources, corrected_sources, authority)):
            _stop("STOP_SOURCE_LINEAGE_CORRECTION_RECORD_SCHEMA")
        if set(old_sources) != set(SOURCE_LINEAGE_CORRECTION_KINDS) or set(corrected_sources) != set(SOURCE_LINEAGE_CORRECTION_KINDS):
            _stop("STOP_SOURCE_LINEAGE_CORRECTION_RECORD_SCHEMA")

        authority_values: dict[str, Any] = {}
        for key in ("april_active_source_set_manifest", "recovery_completion_status", "frozen_prediction_input_manifest"):
            reference = authority.get(key)
            if not isinstance(reference, dict):
                _stop("STOP_SOURCE_LINEAGE_CORRECTION_AUTHORITY_SCHEMA")
            path = self.root / str(reference.get("path", ""))
            expected = self._require_hash(reference.get("sha256"), "package")
            if not path.is_file() or sha256(path) != expected:
                _stop("STOP_SOURCE_LINEAGE_CORRECTION_AUTHORITY_HASH_MISMATCH")
            authority_values[key] = _json(path)
            self._record(path)
        recovery = authority_values["recovery_completion_status"]
        active_reference = authority["april_active_source_set_manifest"]
        if (
            recovery.get("corrected_source_status") != "CORRECTED_PRE_SOURCE_ACCEPTED"
            or str(recovery.get("active_source_set_manifest", "")).replace("\\", "/") != str(active_reference["path"]).replace("\\", "/")
        ):
            _stop("STOP_SOURCE_LINEAGE_CORRECTION_RECOVERY_STATUS_MISMATCH")

        active_dates = authority_values["april_active_source_set_manifest"].get("active_dates")
        active = next((entry for entry in active_dates or [] if entry.get("date") == date), None)
        prediction_sources = authority_values["frozen_prediction_input_manifest"].get("sources")
        if not isinstance(active, dict) or active.get("source_version") != "CORRECTED_PRE_SOURCE_VERSION" or not isinstance(active.get("sources"), dict) or not isinstance(prediction_sources, dict):
            _stop("STOP_SOURCE_LINEAGE_CORRECTION_AUTHORITY_SCHEMA")

        for kind in SOURCE_LINEAGE_CORRECTION_KINDS:
            original, old, corrected = manifest_files.get(kind), old_sources.get(kind), corrected_sources.get(kind)
            if not all(isinstance(value, dict) for value in (original, old, corrected)):
                _stop("STOP_SOURCE_LINEAGE_CORRECTION_RECORD_SCHEMA")
            if original.get("sha256") != old.get("sha256") or str(original.get("path", "")).replace("\\", "/") != str(old.get("path", "")).replace("\\", "/"):
                _stop(f"STOP_SOURCE_LINEAGE_CORRECTION_{kind}_OLD_SHA_MISMATCH")
            corrected_path = self.root / str(corrected.get("path", ""))
            corrected_sha = self._require_hash(corrected.get("sha256"), kind)
            if not corrected_path.is_file() or sha256(corrected_path) != corrected_sha:
                _stop(f"STOP_SOURCE_LINEAGE_CORRECTION_{kind}_V2_ACTUAL_SHA_MISMATCH")
            active_source = active["sources"].get(kind)
            prediction_source = prediction_sources.get(kind)
            if not isinstance(active_source, dict) or active_source.get("sha256") != corrected_sha or str(active_source.get("path", "")).replace("\\", "/") != str(corrected.get("path", "")).replace("\\", "/"):
                _stop(f"STOP_SOURCE_LINEAGE_CORRECTION_{kind}_ACTIVE_SOURCE_MISMATCH")
            if not isinstance(prediction_source, dict) or prediction_source.get("sha256") != corrected_sha or str(prediction_source.get("path", "")).replace("\\", "/") != str(corrected.get("path", "")).replace("\\", "/"):
                _stop(f"STOP_SOURCE_LINEAGE_CORRECTION_{kind}_PREDICTION_INPUT_MISMATCH")

        self._record(record_path)
        files = dict(manifest_files)
        files.update({kind: dict(corrected_sources[kind]) for kind in SOURCE_LINEAGE_CORRECTION_KINDS})
        return files, {
            "repair_type": correction["repair_type"],
            "target_date": date,
            "scope": list(SOURCE_LINEAGE_CORRECTION_KINDS),
            "correction_path": SOURCE_LINEAGE_CORRECTION_PATH,
            "correction_sha256": SOURCE_LINEAGE_CORRECTION_SHA256,
        }

    @staticmethod
    def _target_text(value: object) -> str:
        return str(value or "").strip().replace(" ", "").replace("　", "")

    def _known_data_integrity_exclusion_bridge(self, date: str, files: dict[str, Any]) -> dict[str, Any] | None:
        """Authenticate the sole approved whole-race source exclusion.

        This is deliberately source-bound and exact: it neither converts a
        missing DS horse into zero history nor changes the TARGET adapter.  The
        subsequent temporary copy removes the complete approved race before
        normal adapter validation, so any remaining mismatch is still fail
        closed by the unchanged adapter.
        """
        if date != KNOWN_EXCLUSION_DATE:
            return None
        record_path = self.root / KNOWN_EXCLUSION_BRIDGE_PATH
        if not record_path.is_file() or sha256(record_path) != KNOWN_EXCLUSION_BRIDGE_SHA256:
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_RECORD_HASH_MISMATCH")
        record = _json(record_path)
        target = record.get("target_race")
        horse = record.get("affected_horse")
        if not isinstance(target, dict) or not isinstance(horse, dict) or (
            record.get("schema_version") != "ws2_known_data_integrity_exclusion_bridge_20260823_v1"
            or record.get("bridge_type") != "KNOWN_HUMAN_APPROVED_DATE_SPECIFIC_RACE_EXCLUSION"
            or record.get("role") != "HUMAN_APPROVED_DATE_SPECIFIC_RACE_LEVEL_EXCLUSION"
            or record.get("target_date") != KNOWN_EXCLUSION_DATE
            or target != {"race_id": KNOWN_EXCLUSION_RACE_ID, "venue": KNOWN_EXCLUSION_VENUE, "race_number": KNOWN_EXCLUSION_RACE_NUMBER}
            or horse != {"horse_number": KNOWN_EXCLUSION_HORSE_NUMBER, "horse_name": KNOWN_EXCLUSION_HORSE_NAME, "registration_id": KNOWN_EXCLUSION_REGISTRATION_ID}
            or record.get("reason") != "DE_DS_HORSE_SET_MISMATCH"
            or record.get("reason_status") != "SOURCE_DATA_INTEGRITY_UNRESOLVED"
            or record.get("approval_basis") != "ZERO_HISTORY_HORSE_PRE_RESULT_RACE_EXCLUSION"
            or record.get("exclusion_scope") != "WHOLE_RACE"
            or record.get("generalizable") is not False
            or record.get("adapter_validation_rule_changed") is not False
            or record.get("population_rule_changed") is not False
            or record.get("raw_source_modified") is not False
        ):
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_RECORD_SCHEMA")

        authorities = record.get("prior_authorities")
        expected_authorities = {
            "exclusion_record": ("reports/prospective_prediction_20260823_v1/exclusion_record.json", "HUMAN_APPROVED_RACE_EXCLUSION_RECORD"),
            "input_manifest": ("reports/prospective_prediction_20260823_v1/input_manifest.json", "FROZEN_INPUT_PROVENANCE"),
            "provenance": ("reports/prospective_prediction_20260823_v1/provenance.json", "FROZEN_PRE_RUN_PROVENANCE"),
            "historical_runner": ("review/prospective_prediction_20260823_human_exclusion_runner.py", "DATE_SPECIFIC_TEMPORARY_FILTER_IMPLEMENTATION"),
        }
        if not isinstance(authorities, dict) or set(authorities) != set(expected_authorities):
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_AUTHORITY_SCHEMA")
        values: dict[str, Any] = {}
        for key, (expected_path, expected_role) in expected_authorities.items():
            reference = authorities.get(key)
            if not isinstance(reference, dict) or reference.get("path") != expected_path or reference.get("role") != expected_role:
                _stop("STOP_KNOWN_EXCLUSION_BRIDGE_AUTHORITY_SCHEMA")
            path = self.root / expected_path
            expected_sha = self._require_hash(reference.get("sha256"), "package")
            if not path.is_file() or sha256(path) != expected_sha:
                _stop("STOP_KNOWN_EXCLUSION_BRIDGE_AUTHORITY_HASH_MISMATCH")
            self._record(path)
            if key != "historical_runner":
                values[key] = _json(path)

        exclusion = values["exclusion_record"]
        excluded = exclusion.get("excluded_races")
        if not isinstance(excluded, list) or len(excluded) != 1 or exclusion.get("no_other_automatic_exclusion") is not True:
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_HUMAN_AUTHORITY_MISMATCH")
        expected_exclusion = {
            "race_id": KNOWN_EXCLUSION_RACE_ID,
            "venue": KNOWN_EXCLUSION_VENUE,
            "race_number": KNOWN_EXCLUSION_RACE_NUMBER,
            "affected_horse_number": KNOWN_EXCLUSION_HORSE_NUMBER,
            "affected_horse_name": KNOWN_EXCLUSION_HORSE_NAME,
            "reason": "DE_DS_HORSE_SET_MISMATCH",
            "reason_status": "SOURCE_DATA_INTEGRITY_UNRESOLVED",
            "evaluation_status": "NOT_EVALUATED",
            "authority": "HUMAN_TEMPORARY_RACE_LEVEL_EXCLUSION_20260823_ONLY",
        }
        if excluded[0] != expected_exclusion:
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_HUMAN_AUTHORITY_MISMATCH")
        manifest, provenance = values["input_manifest"], values["provenance"]
        if manifest.get("date") != KNOWN_EXCLUSION_DATE or manifest.get("temporary_filtered_input", {}).get("raw_modified") is not False or manifest.get("temporary_filtered_input", {}).get("exclusion") != expected_exclusion or provenance.get("human_exclusion") != expected_exclusion or provenance.get("result_data_access_count") != 0:
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_HUMAN_AUTHORITY_MISMATCH")

        raw = record.get("current_raw_sources")
        if not isinstance(raw, dict) or set(raw) != set(KNOWN_EXCLUSION_SOURCE_KINDS):
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_SOURCE_SCHEMA")
        paths: dict[str, Path] = {}
        for kind in KNOWN_EXCLUSION_SOURCE_KINDS:
            bridge_file, source_file, manifest_file = raw.get(kind), files.get(kind), manifest.get("sources", {}).get(kind)
            if not all(isinstance(value, dict) for value in (bridge_file, source_file, manifest_file)):
                _stop("STOP_KNOWN_EXCLUSION_BRIDGE_SOURCE_SCHEMA")
            path_text = str(bridge_file.get("path", "")).replace("\\", "/")
            bridge_sha = self._require_hash(bridge_file.get("sha256"), kind)
            if (
                path_text != str(source_file.get("path", "")).replace("\\", "/")
                or bridge_sha != source_file.get("sha256")
                or path_text != str(manifest_file.get("path", "")).replace("\\", "/")
                or bridge_sha != manifest_file.get("sha256")
            ):
                _stop(f"STOP_KNOWN_EXCLUSION_BRIDGE_{kind}_SOURCE_BINDING_MISMATCH")
            path = self.root / path_text
            if not path.is_file() or sha256(path) != bridge_sha:
                _stop(f"STOP_KNOWN_EXCLUSION_BRIDGE_{kind}_SOURCE_HASH_MISMATCH")
            paths[kind] = path

        try:
            parsed = {
                kind: list(csv.reader(paths[kind].read_bytes().decode("cp932").splitlines()))
                for kind in KNOWN_EXCLUSION_SOURCE_KINDS
            }
        except UnicodeDecodeError:
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_SOURCE_ENCODING_INVALID")
        if any(any(len(row) != width for row in parsed[kind]) for kind, width in (("DG", 11), ("DE", 33), ("DS", 50))):
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_SOURCE_SCHEMA")
        dg = [row for row in parsed["DG"] if self._target_text(row[3]) == KNOWN_EXCLUSION_VENUE and self._target_text(row[4]) == str(KNOWN_EXCLUSION_RACE_NUMBER)]
        de_race = [row for row in parsed["DE"] if self._target_text(row[1]) == KNOWN_EXCLUSION_VENUE and self._target_text(row[2]) == str(KNOWN_EXCLUSION_RACE_NUMBER)]
        de_target = [row for row in de_race if self._target_text(row[3]) == str(KNOWN_EXCLUSION_HORSE_NUMBER) and self._target_text(row[7]) == KNOWN_EXCLUSION_HORSE_NAME and self._target_text(row[18]) == KNOWN_EXCLUSION_REGISTRATION_ID]
        ds_names = {self._target_text(row[16]) for row in parsed["DS"]}
        if len(dg) != 1 or not de_race or len(de_target) != 1 or KNOWN_EXCLUSION_HORSE_NAME in ds_names:
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_CURRENT_MISMATCH_SEMANTICS")
        excluded_names = {self._target_text(row[7]) for row in de_race}
        all_de_names = {self._target_text(row[7]) for row in parsed["DE"]}
        if not excluded_names or len(excluded_names) != len(de_race) or excluded_names & (all_de_names - excluded_names) or ds_names - all_de_names:
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_UNAUTHORIZED_SCOPE")
        self._record(record_path)
        return {
            "bridge_path": KNOWN_EXCLUSION_BRIDGE_PATH,
            "bridge_sha256": KNOWN_EXCLUSION_BRIDGE_SHA256,
            "role": record["role"],
            "target_date": date,
            "race_id": KNOWN_EXCLUSION_RACE_ID,
            "venue": KNOWN_EXCLUSION_VENUE,
            "race_number": KNOWN_EXCLUSION_RACE_NUMBER,
            "affected_horse": dict(horse),
            "excluded_horse_names": sorted(excluded_names),
            "source_paths": {kind: _rel(self.root, paths[kind]) for kind in KNOWN_EXCLUSION_SOURCE_KINDS},
        }

    def _existing_adapter_compatibility_reuse(self, date: str, files: dict[str, Any]) -> dict[str, Any] | None:
        """Authenticate the pre-existing Adapter-owned 20260906 exception.

        WS2 deliberately does not map or normalize horse names.  Once the
        frozen source authority is authenticated, ``target_prediction_bundle``
        imports the existing Adapter constant and lets that Adapter enforce its
        own exact source, registration-id and name-pair guards.
        """
        if date != KNOWN_ADAPTER_COMPATIBILITY_DATE:
            return None
        record_path = self.root / KNOWN_ADAPTER_COMPATIBILITY_REUSE_PATH
        if not record_path.is_file() or sha256(record_path) != KNOWN_ADAPTER_COMPATIBILITY_REUSE_SHA256:
            _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_RECORD_HASH_MISMATCH")
        record = _json(record_path)
        target, required = record.get("target_scope"), record.get("required_input_exception")
        if not isinstance(target, dict) or not isinstance(required, dict) or (
            record.get("schema_version") != "ws2_existing_adapter_compatibility_reuse_20260906_v1"
            or record.get("reuse_type") != "EXISTING_ADAPTER_AUTHORITY"
            or record.get("role") != "PREVIOUSLY_APPROVED_COMPATIBILITY_MAPPING_REUSE"
            or record.get("target_date") != KNOWN_ADAPTER_COMPATIBILITY_DATE
            or record.get("adapter_exception_constant") != "HUMAN_APPROVED_20260906_EXACT_EXCEPTION"
            or record.get("adapter_change_required") is not False
            or record.get("whole_race_exclusion_required") is not False
            or record.get("general_normalization_rule_change") is not False
            or target != {
                "race_id": KNOWN_ADAPTER_COMPATIBILITY_RACE_ID, "venue": "阪神", "race_number": 11,
                "horse_number": 8, "de_horse_name": "ファストネットワーク", "ds_horse_name": "ファストネットワー",
                "registration_id": "20190007", "scope": "2026-09-06 / hanshin11R / exact-name-pair-only",
            }
            or required != {
                "state": "HUMAN_APPROVED_EXACT_COMPATIBILITY_MAPPING", "mapping_count": 1,
                "scope": "2026-09-06 / hanshin11R / exact-name-pair-only", "source_sha_guard": "PASS",
                "exact_scope_guard": "PASS", "general_truncation_rule": "REJECT",
                "de_exact_name": "ファストネットワーク", "ds_exact_name": "ファストネットワー",
            }
        ):
            _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_RECORD_SCHEMA")
        authorities = record.get("frozen_authorities")
        expected_authorities = {
            "prediction_manifest": "reports/prospective_prediction_20260906_v1/prediction_manifest.json",
            "input_manifest": "reports/prospective_prediction_20260906_v1/input_manifest.json",
            "adapter_implementation": "review/target_bulk_prediction_input_adapter_v1.py",
        }
        if not isinstance(authorities, dict) or set(authorities) != set(expected_authorities):
            _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_AUTHORITY_SCHEMA")
        values: dict[str, Any] = {}
        for key, expected_path in expected_authorities.items():
            reference = authorities[key]
            if not isinstance(reference, dict) or reference.get("path") != expected_path:
                _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_AUTHORITY_SCHEMA")
            path = self.root / expected_path
            expected_sha = self._require_hash(reference.get("sha256"), "package")
            if not path.is_file() or sha256(path) != expected_sha:
                _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_AUTHORITY_HASH_MISMATCH")
            self._record(path)
            if key != "adapter_implementation":
                values[key] = _json(path)
        manifest, input_manifest = values["prediction_manifest"], values["input_manifest"]
        listed_hash = next((item.get("sha256") for item in manifest.get("files", []) if isinstance(item, dict) and item.get("relative_path") == "input_manifest.json"), None)
        if listed_hash != authorities["input_manifest"]["sha256"]:
            _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_FROZEN_INPUT_MANIFEST_HASH_MISMATCH")
        if input_manifest.get("date") != KNOWN_ADAPTER_COMPATIBILITY_DATE or input_manifest.get("input_exception") != required:
            _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_INPUT_EXCEPTION_MISMATCH")
        raw = record.get("current_raw_sources")
        if not isinstance(raw, dict) or set(raw) != set(KNOWN_ADAPTER_COMPATIBILITY_SOURCE_KINDS):
            _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_SOURCE_SCHEMA")
        input_sources = input_manifest.get("sources")
        if not isinstance(input_sources, dict):
            _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_SOURCE_SCHEMA")
        for kind in KNOWN_ADAPTER_COMPATIBILITY_SOURCE_KINDS:
            expected, frozen, current = raw.get(kind), input_sources.get(kind), files.get(kind)
            if not all(isinstance(value, dict) for value in (expected, frozen, current)):
                _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_SOURCE_SCHEMA")
            path_text = str(expected.get("path", "")).replace("\\", "/")
            expected_sha = self._require_hash(expected.get("sha256"), kind)
            if (
                path_text != str(frozen.get("path", "")).replace("\\", "/")
                or expected_sha != frozen.get("sha256")
                or path_text != str(current.get("path", "")).replace("\\", "/")
                or expected_sha != current.get("sha256")
            ):
                _stop(f"STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_{kind}_SOURCE_BINDING_MISMATCH")
            path = self.root / path_text
            if not path.is_file() or sha256(path) != expected_sha:
                _stop(f"STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_{kind}_SOURCE_HASH_MISMATCH")
        self._record(record_path)
        return {
            "reuse_path": KNOWN_ADAPTER_COMPATIBILITY_REUSE_PATH,
            "reuse_sha256": KNOWN_ADAPTER_COMPATIBILITY_REUSE_SHA256,
            "role": record["role"],
            "target_date": date,
            "race_id": KNOWN_ADAPTER_COMPATIBILITY_RACE_ID,
            "adapter_exception_constant": record["adapter_exception_constant"],
            "required_input_exception": dict(required),
            "adapter_implementation_sha256": authorities["adapter_implementation"]["sha256"],
        }

    def source_file(self, entry: dict[str, Any], kind: str) -> Path:
        path = self.root / str(entry.get("path", ""))
        expected = self._require_hash(entry.get("sha256"), kind, stage="raw_source_sha_authority", path=path, authority_path="source_date_manifest")
        if not path.is_file():
            _stop("STOP_CANONICAL_RAW_SOURCE_MISSING")
        if sha256(path) != expected:
            _stop("STOP_SOURCE_HASH_MISMATCH")
        self._record(path)
        return path

    def prediction(self, root_value: str) -> list[dict[str, Any]]:
        """Authenticate every manifest entry; parse only race predictions."""
        base = self.root / root_value
        manifest_path = base / "prediction_manifest.json"
        manifest = _json(manifest_path)
        self._record(manifest_path)
        entries = manifest.get("files")
        if not isinstance(entries, list) or not entries:
            _stop("STOP_PREDICTION_ARTIFACT_MALFORMED")
        artifacts, non_race = [], []
        for entry in entries:
            relative = entry.get("relative_path")
            expected = self._require_hash(entry.get("sha256"), "prediction")
            path = base / str(relative or "")
            if not isinstance(relative, str) or not relative or not path.is_file():
                _stop("STOP_PREDICTION_ARTIFACT_MALFORMED")
            if sha256(path) != expected:
                _stop("STOP_PREDICTION_ARTIFACT_HASH_MISMATCH")
            self._record(path)
            if not re.fullmatch(r"race_.+_prediction\.json", Path(relative).name):
                non_race.append({"relative_path": relative, "artifact_type": "KNOWN_NON_RACE" if Path(relative).name in {"input_manifest.json", "provenance.json", "race_index.json", "report.md", "exclusion_record.json", "summary.json"} else "UNKNOWN_NON_RACE", "sha256": expected})
                continue
            value = _json(path)
            if not isinstance(value.get("ranked_results"), list) or not isinstance(value.get("buy_gate_trace", {}).get("horses"), list):
                _stop("STOP_PREDICTION_ARTIFACT_MALFORMED")
            value["_ws2_artifact_path"] = _rel(self.root, path)
            value["_ws2_artifact_sha256"] = sha256(path)
            artifacts.append(value)
        if not artifacts:
            _stop("STOP_PREDICTION_ARTIFACT_MALFORMED")
        self.manifest_non_race_artifacts = getattr(self, "manifest_non_race_artifacts", []) + non_race
        return artifacts

    def prediction_pit_evidence(self, source: dict[str, Any]) -> dict[str, Any]:
        """Verify prediction-time code/knowledge identity from frozen provenance.

        The model package has no historical regeneration identity.  The only
        accepted authority is the provenance emitted alongside each frozen
        prediction and the exact Git blobs at its recorded commit.
        """
        date = str(source.get("date", ""))
        root_value = str(source.get("prediction_root", ""))
        provenance_path = self.root / root_value / "provenance.json"
        reasons: list[str] = []
        if not provenance_path.is_file():
            return {"date": date, "status": "PIT_UNPROVEN", "reasons": ["PREDICTION_PROVENANCE_MISSING"]}
        provenance = _json(provenance_path)
        self._record(provenance_path)
        commit = str(provenance.get("git_head", ""))
        required = (
            ("run_new_module", "run_new_module_sha256"),
            ("runner_path", "runner_sha256"),
        )
        identities: list[dict[str, Any]] = []
        for path_key, sha_key in required:
            relative, expected = str(provenance.get(path_key, "")), provenance.get(sha_key)
            actual = _git_blob_sha256(self.root, commit, relative)
            valid = isinstance(expected, str) and len(expected) == 64 and actual == expected
            identities.append({"path": relative.replace("\\", "/"), "provenance_field": sha_key, "expected_sha256": expected, "historical_sha256": actual, "verified": valid})
            if not valid:
                reasons.append(f"GENERATOR_IDENTITY_UNPROVEN:{path_key}")
        shadow_expected = provenance.get("shadow_buy_engine_sha256")
        shadow_actual = _git_blob_sha256(self.root, commit, "engine/shadow_buy_decision_engine.py")
        shadow_valid = isinstance(shadow_expected, str) and len(shadow_expected) == 64 and shadow_actual == shadow_expected
        identities.append({"path": "engine/shadow_buy_decision_engine.py", "provenance_field": "shadow_buy_engine_sha256", "expected_sha256": shadow_expected, "historical_sha256": shadow_actual, "verified": shadow_valid})
        if not shadow_valid:
            reasons.append("GENERATOR_IDENTITY_UNPROVEN:shadow_buy_engine_sha256")
        # Knowledge modules are versioned code/static embedded data here.  A
        # historical blob merely proves the file existed; the prediction
        # provenance must also pin the exact content expected at generation.
        # No current-working-tree comparison is accepted as a substitute.
        expected_knowledge = provenance.get("knowledge_code_sha256")
        if not isinstance(expected_knowledge, dict):
            expected_knowledge = {}
        knowledge = []
        for relative in self.policy.get("pit_sensitive_code_paths", []):
            historical = _git_blob_sha256(self.root, commit, str(relative))
            expected = expected_knowledge.get(str(relative))
            verified = isinstance(expected, str) and len(expected) == 64 and historical == expected
            knowledge.append({"path": str(relative), "expected_sha256": expected, "historical_sha256": historical, "verified": verified, "authority": "RECORDED_GIT_HEAD_AND_PREDICTION_PROVENANCE"})
            if not verified:
                reasons.append(f"KNOWLEDGE_GIT_IDENTITY_UNPROVEN:{relative}")
        if provenance.get("result_data_access_count") != 0:
            reasons.append("PREDICTION_PROVENANCE_RESULT_ACCESS_NONZERO")
        return {
            "date": date,
            "prediction_root": root_value,
            "provenance_path": _rel(self.root, provenance_path),
            "git_head": commit,
            "generator_identities": identities,
            "knowledge_code_identities": knowledge,
            "result_data_access_count": provenance.get("result_data_access_count"),
            "status": "PIT_PROVEN" if not reasons else "PIT_UNPROVEN",
            "reasons": reasons,
        }

    def target_prediction_bundle(self, source: dict[str, Any]) -> Any:
        """Delegate headerless CP932 DG/DE/DS parsing to the existing adapter."""
        from review.target_bulk_prediction_input_adapter_v1 import HUMAN_APPROVED_20260906_EXACT_EXCEPTION, PredictionInputValidationError, TargetBulkPredictionInputAdapterV1
        paths = {kind: self.source_file(source["files"][kind], kind) for kind in ("DG", "DE", "DS")}
        try:
            bridge = source.get("known_data_integrity_exclusion_bridge")
            adapter_reuse = source.get("existing_adapter_compatibility_reuse")
            if bridge is not None and adapter_reuse is not None:
                _stop("STOP_COMPATIBILITY_AUTHORITY_SCOPE_COLLISION")
            if bridge is not None:
                return self._load_with_known_whole_race_exclusion(paths, bridge)
            if adapter_reuse is None:
                return TargetBulkPredictionInputAdapterV1().load(paths["DG"], paths["DE"], paths["DS"])
            bundle = TargetBulkPredictionInputAdapterV1().load(
                paths["DG"], paths["DE"], paths["DS"],
                compatibility_exception=HUMAN_APPROVED_20260906_EXACT_EXCEPTION,
            )
            if bundle.date != KNOWN_ADAPTER_COMPATIBILITY_DATE or bundle.preflight.get("input_exception") != adapter_reuse.get("required_input_exception"):
                _stop("STOP_EXISTING_ADAPTER_COMPATIBILITY_REUSE_ADAPTER_OUTPUT_MISMATCH")
            return bundle
        except PredictionInputValidationError as error:
            _stop(f"STOP_TARGET_PREDICTION_INPUT_{error.reason_code}")

    def _load_with_known_whole_race_exclusion(self, paths: dict[str, Path], bridge: dict[str, Any]) -> Any:
        """Use ephemeral filtered copies for the one authenticated whole race.

        The originals were hash-verified by ``source_file`` and are never
        modified.  The adapter itself remains unchanged and receives normal
        headerless CP932 files after the exact race is removed from DG/DE and
        its DE-name scoped DS rows are removed.  No other date or race can
        reach this method because the bridge record is only produced above for
        the fixed source snapshot.
        """
        from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
        if (
            bridge.get("target_date") != KNOWN_EXCLUSION_DATE
            or bridge.get("race_id") != KNOWN_EXCLUSION_RACE_ID
            or bridge.get("venue") != KNOWN_EXCLUSION_VENUE
            or bridge.get("race_number") != KNOWN_EXCLUSION_RACE_NUMBER
            or bridge.get("bridge_sha256") != KNOWN_EXCLUSION_BRIDGE_SHA256
            or bridge.get("role") != "HUMAN_APPROVED_DATE_SPECIFIC_RACE_LEVEL_EXCLUSION"
        ):
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_RUNTIME_SCOPE_MISMATCH")
        try:
            raw_rows = {
                kind: list(csv.reader(paths[kind].read_bytes().decode("cp932").splitlines()))
                for kind in ("DG", "DE", "DS")
            }
        except UnicodeDecodeError:
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_SOURCE_ENCODING_INVALID")
        if any(any(len(row) != width for row in raw_rows[kind]) for kind, width in (("DG", 11), ("DE", 33), ("DS", 50))):
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_SOURCE_SCHEMA")
        is_dg_target = lambda row: self._target_text(row[3]) == KNOWN_EXCLUSION_VENUE and self._target_text(row[4]) == str(KNOWN_EXCLUSION_RACE_NUMBER)
        is_de_target = lambda row: self._target_text(row[1]) == KNOWN_EXCLUSION_VENUE and self._target_text(row[2]) == str(KNOWN_EXCLUSION_RACE_NUMBER)
        dg_target = [row for row in raw_rows["DG"] if is_dg_target(row)]
        de_target = [row for row in raw_rows["DE"] if is_de_target(row)]
        target = [row for row in de_target if self._target_text(row[3]) == str(KNOWN_EXCLUSION_HORSE_NUMBER) and self._target_text(row[7]) == KNOWN_EXCLUSION_HORSE_NAME and self._target_text(row[18]) == KNOWN_EXCLUSION_REGISTRATION_ID]
        excluded_names = {self._target_text(row[7]) for row in de_target}
        if len(dg_target) != 1 or not de_target or len(target) != 1 or excluded_names != set(bridge.get("excluded_horse_names", [])):
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_RUNTIME_SCOPE_MISMATCH")
        filtered = {
            "DG": [row for row in raw_rows["DG"] if not is_dg_target(row)],
            "DE": [row for row in raw_rows["DE"] if not is_de_target(row)],
        }
        remaining_names = {self._target_text(row[7]) for row in filtered["DE"]}
        filtered["DS"] = [row for row in raw_rows["DS"] if self._target_text(row[16]) in remaining_names]
        if (
            len(raw_rows["DG"]) - len(filtered["DG"]) != 1
            or len(raw_rows["DE"]) - len(filtered["DE"]) != len(de_target)
            or any(self._target_text(row[7]) in excluded_names for row in filtered["DE"])
            or any(self._target_text(row[16]) not in remaining_names for row in filtered["DS"])
        ):
            _stop("STOP_KNOWN_EXCLUSION_BRIDGE_UNAUTHORIZED_SCOPE")
        sandbox_parent = self.root / ".tmp"
        sandbox_parent.mkdir(parents=True, exist_ok=True)
        sandbox = Path(tempfile.mkdtemp(prefix="ws2_20260823_known_exclusion_", dir=sandbox_parent))
        try:
            materialized: dict[str, Path] = {}
            for kind, rows in filtered.items():
                path = sandbox / f"{kind}{KNOWN_EXCLUSION_DATE[2:]}.CSV"
                with path.open("w", encoding="cp932", newline="") as handle:
                    csv.writer(handle, lineterminator="\r\n").writerows(rows)
                materialized[kind] = path
            bundle = TargetBulkPredictionInputAdapterV1().load(materialized["DG"], materialized["DE"], materialized["DS"])
            if bundle.date != KNOWN_EXCLUSION_DATE or KNOWN_EXCLUSION_RACE_ID in bundle.races:
                _stop("STOP_KNOWN_EXCLUSION_BRIDGE_RUNTIME_SCOPE_MISMATCH")
            return bundle
        finally:
            try:
                shutil.rmtree(sandbox)
            except OSError:
                _stop("STOP_KNOWN_EXCLUSION_BRIDGE_TEMP_CLEANUP_FAILED")

    def target_result_index(self, source: dict[str, Any]) -> dict[str, Any]:
        """Use the existing Daily Result List parser rather than English remapping."""
        from review.target_daily_result_list_schema_v2_validator import DailyResultListSchemaV2ValidationError, PRIMARY_VARIANT, validate_source
        path = self.source_file(source["files"]["result_primary"], "result_primary")
        try:
            return validate_source(path, source["date"], PRIMARY_VARIANT).as_dict()
        except DailyResultListSchemaV2ValidationError as error:
            _stop(f"STOP_TARGET_RESULT_{error.code}")

    def target_result_labels(self, source: dict[str, Any]) -> dict[tuple[str, str], dict[str, bool]]:
        """Derive canonical labels from validated 馬番順着順 slots.

        The Daily Result List has no English result columns.  Its pre-existing
        primary variant specifies that slot ``12 + horse_number - 1`` is the
        final placing for that horse number.  A zero/non-numeric slot is an
        invalid result; valid rows use the repository's top-3 rule.
        """
        from review.target_bulk_prediction_input_adapter_v1 import COURSE_KEYS
        validated = self.target_result_index(source)
        path = self.root / validated["path"]
        labels: dict[tuple[str, str], dict[str, bool]] = {}
        with path.open("r", encoding="cp932", newline="") as handle:
            for row in csv.reader(handle):
                race_key, venue, number, head_count = row[0], row[1], int(row[2]), int(row[9])
                if venue not in COURSE_KEYS:
                    _stop("STOP_TARGET_RESULT_VENUE_UNPROVEN")
                race_id = f"race_{source['date']}_{COURSE_KEYS[venue]}_{number}R"
                for horse_number, raw_finish in enumerate(row[12:12 + head_count], 1):
                    valid = raw_finish.isdigit() and int(raw_finish) > 0
                    labels[(race_id, str(horse_number))] = {
                        "valid_result": valid,
                        "actual_top3": bool(valid and int(raw_finish) <= 3),
                        "target_race_key": race_key,
                    }
        return labels

    def prediction_eligibility_reasons(self, root_value: str, prediction_races: set[str]) -> dict[str, str]:
        """Read per-race eligibility evidence; never manufacture a reason."""
        base, reasons = self.root / root_value, {}
        index_path = base / "race_index.json"
        if index_path.is_file():
            index = _json(index_path).get("race_index")
            if not isinstance(index, list):
                _stop("STOP_RACE_INDEX_MALFORMED")
            indexed = {str(item.get("race_id")) for item in index if isinstance(item, dict)}
            if indexed != prediction_races:
                _stop("STOP_RACE_INDEX_PREDICTION_ARTIFACT_MISMATCH")
            self._record(index_path)
        exclusion_path = base / "exclusion_record.json"
        if exclusion_path.is_file():
            record = _json(exclusion_path)
            candidates = []
            for key in ("automatic_exclusions", "excluded_races", "integrity_excluded_source_races"):
                value = record.get(key, [])
                candidates.extend(value if isinstance(value, list) else [])
            for item in candidates:
                if isinstance(item, dict) and item.get("race_id") and (item.get("reason") or item.get("reason_code")):
                    reasons[str(item["race_id"])] = str(item.get("reason") or item.get("reason_code"))
            self._record(exclusion_path)
        return reasons

    def model(self) -> dict[str, Any]:
        root = self.package(MODEL_ROOT, REQUIRED_MODEL)
        self.activation_record_authority()
        recipe, metadata = _json(root / "training_recipe.json"), _json(root / "model_metadata.json")
        training, reproduction, runtime = _json(root / "training_manifest.json"), _json(root / "deterministic_reproduction.json"), _json(root / "runtime_environment.json")
        recipe_fields = ("C", "base_recipe", "class_weight", "penalty", "pipeline", "solver")
        missing = [field for field in recipe_fields if field not in recipe]
        missing += [field for field in ("model_sha256", "scaler_sha256", "training_population") if not metadata.get(field)]
        missing += [field for field in ("dataset_sha256", "feature_count") if not training.get(field)]
        if metadata.get("model_sha256") != sha256(root / "model.joblib") or metadata.get("scaler_sha256") != sha256(root / "scaler.joblib"):
            _stop("STOP_V5_MODEL_ASSET_IDENTITY_MISMATCH")
        deterministic = "DETERMINISTIC_ALGORITHM" if recipe.get("solver") == "lbfgs" and recipe.get("penalty") == "l2" else "OTHER_UNPROVEN"
        # Historical PIT identity is intentionally *not* taken from the model
        # package: it belongs to the frozen prediction provenance for each
        # source date.  Keeping that boundary explicit prevents a nonexistent
        # model-level field from becoming a false prerequisite.
        return {"status": "PASS" if not missing and reproduction.get("status") == "PASS" and deterministic != "OTHER_UNPROVEN" else "BLOCKED_RECIPE_OR_RUNTIME_UNPROVEN", "missing": missing, "determinism_source": deterministic, "recipe": {field: recipe.get(field) for field in recipe_fields}, "feature_count": training.get("feature_count"), "runtime": runtime, "historical_pit_authority": "PER_PREDICTION_PROVENANCE_AND_GIT_IDENTITY"}

    def activation_record_authority(self) -> None:
        authority_path = self.root / str(self.policy["model_activation_record_authority_path"])
        authority_sha = str(self.policy["model_activation_record_authority_sha256"])
        actual_authority = sha256(authority_path) if authority_path.is_file() else None
        if actual_authority != authority_sha:
            self._hash_stop("STOP_ACTIVATION_RECORD_AUTHORITY_HASH_MISMATCH", stage="activation_authority_validation", role="activation_authority", path=authority_path, expected=authority_sha, actual=actual_authority, authority_path=str(authority_path.relative_to(self.root)), authority_sha=authority_sha)
        authority = _json(authority_path); record = authority.get("activation_record", {})
        path = self.root / str(record.get("path", "")); expected = record.get("sha256")
        if record.get("included_in_frozen_model_hash_index") is not False or authority.get("validation_authority") != "INDEPENDENT_SHA_PINNED_EVIDENCE" or not isinstance(expected, str) or len(expected) != 64 or not path.is_file():
            self._hash_stop("STOP_ACTIVATION_RECORD_AUTHORITY_INVALID", stage="activation_authority_validation", role="activation_record", path=path, expected=expected if isinstance(expected, str) else None, authority_path=str(authority_path.relative_to(self.root)), authority_sha=authority_sha)
        actual = sha256(path)
        if actual != expected:
            self._hash_stop("STOP_SOURCE_HASH_MISMATCH", stage="activation_record_independent_validation", role="activation_record", path=path, expected=expected, actual=actual, authority_path=str(authority_path.relative_to(self.root)), authority_sha=authority_sha)
        for evidence in authority.get("authority_evidence", []):
            evidence_path = self.root / str(evidence.get("path", "")); evidence_expected = evidence.get("sha256"); evidence_actual = sha256(evidence_path) if evidence_path.is_file() else None
            if evidence_actual != evidence_expected:
                self._hash_stop("STOP_ACTIVATION_RECORD_AUTHORITY_EVIDENCE_MISMATCH", stage="activation_authority_evidence", role="activation_authority_evidence", path=evidence_path, expected=evidence_expected if isinstance(evidence_expected, str) else None, actual=evidence_actual, authority_path=str(authority_path.relative_to(self.root)), authority_sha=authority_sha)
            value = _json(evidence_path)
            pinned = value.get("activation_record_sha256") if "activation_record_sha256" in value else value.get("sources", {}).get("reports/ml_v4_buy_selection_model_v5/activation_record.json", {}).get("expected_sha256")
            if pinned != expected:
                self._hash_stop("STOP_ACTIVATION_RECORD_AUTHORITY_EVIDENCE_MISMATCH", stage="activation_authority_evidence", role="activation_authority_evidence", path=evidence_path, expected=expected, actual=pinned if isinstance(pinned, str) else None, authority_path=str(authority_path.relative_to(self.root)), authority_sha=authority_sha)
        self._record(authority_path); self._record(path)

    def canonical_roles(self, months: set[str], dataset_rows: list[dict[str, str]] | None = None) -> dict[str, list[str]]:
        """Materialize only explicit, machine-readable role records."""
        roles = {month: ["ROLE_UNKNOWN_PROTECTED"] for month in months}
        for relative, field in ((f"{DATASET_ROOT}/lineage.json", "period_roles"), ("KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json", "authoritative_additive_entries")):
            path = self.root / relative
            if not path.is_file():
                continue
            self._record(path)
            for record in _json(path).get(field, []):
                month = str(record.get("period", record.get("month", "")))[:6]
                value = record.get("roles_history", record.get("evidence_role"))
                if month in roles and value:
                    roles[month] = sorted(set(map(str, value))) if isinstance(value, list) else [str(value)]
        # V5's actual row provenance supplies explicit role tokens even where
        # the older fingerprint index has no ``month`` field.  Only exact,
        # machine-readable role values are accepted; prose is never inferred.
        explicit = {"TRAIN", "TRAINING", "VALIDATION", "PROSPECTIVE", "UNTOUCHED", "EXCLUDED"}
        for row in dataset_rows or []:
            month = str(row.get("date", ""))[:6]
            if month not in roles:
                continue
            tokens = {str(row.get(key, "")).strip().upper() for key in ("split_role", "evidence_role_note", "source_block")}
            found = sorted(tokens & explicit)
            if found and roles[month] == ["ROLE_UNKNOWN_PROTECTED"]:
                roles[month] = found
        return roles

    def dependency_scan(self) -> dict[str, Any]:
        """Scan runtime file dependencies without treating docstring prose as I/O."""
        pending = {value.get("module") for value in self.policy["feature_sources"].values() if isinstance(value, dict)}
        seen, findings, path_bases, code_dependencies = set(), [], set(), set()
        while pending:
            relative = pending.pop()
            if not relative or relative in seen:
                continue
            seen.add(relative)
            path = self.root / relative
            if not path.is_file():
                _stop("STOP_REQUIRED_FEATURE_MODULE_MISSING")
            try:
                # TARGET-adjacent historical helpers may be saved as UTF-8
                # with a BOM.  It is source encoding metadata, not malformed
                # Python or a runtime dependency.
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            except SyntaxError:
                _stop("STOP_REQUIRED_FEATURE_MODULE_MALFORMED")
            docstring_constants = set()
            owners = [tree] + [node for node in ast.walk(tree) if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
            for owner in owners:
                body = getattr(owner, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                    docstring_constants.add(id(body[0].value))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "Path":
                    if node.value.args and isinstance(node.value.args[0], ast.Constant) and isinstance(node.value.args[0].value, str) and any(token in node.value.args[0].value.lower() for token in ("knowledge", "learning", "improvement_candidates")):
                        path_bases.update(target.id for target in node.targets if isinstance(target, ast.Name))
                if isinstance(node, ast.Import):
                    for item in node.names:
                        if item.name == "knowledge" or item.name.startswith("knowledge."):
                            code_dependencies.add(item.name.replace(".", "/") + ".py")
                        candidate = item.name.replace(".", "/") + ".py"
                        if (self.root / candidate).is_file():
                            pending.add(candidate)
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == "knowledge" or node.module.startswith("knowledge."):
                        code_dependencies.add(node.module.replace(".", "/") + ".py")
                    candidate = node.module.replace(".", "/") + ".py"
                    if (self.root / candidate).is_file():
                        pending.add(candidate)
                # Require a concrete path component after the category prefix.
                # This deliberately excludes the scanner's own token literals
                # (for example ``"knowledge/"``) as well as docstring prose.
                if isinstance(node, ast.Constant) and id(node) not in docstring_constants and isinstance(node.value, str) and re.search(r"(?:knowledge|learning|improvement_candidates)/.+", node.value.lower()):
                    findings.append({"path": relative, "dependency": "POSSIBLE_LITERAL_PATH"})
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and (any(token in ast.unparse(node).lower() for token in ("knowledge", "learning", "improvement_candidates")) or isinstance(node.left, ast.Name) and node.left.id in path_bases):
                    findings.append({"path": relative, "dependency": "POSSIBLE_STATIC_PATH"})
                if isinstance(node, ast.Call) and ((isinstance(node.func, ast.Attribute) and node.func.attr == "import_module") or (isinstance(node.func, ast.Name) and node.func.id in {"__import__", "spec_from_file_location", "SourceFileLoader"})):
                    findings.append({"path": relative, "dependency": "POSSIBLE_DYNAMIC_IMPORT"})
        return {"status": "PASS" if not findings else "UNRESOLVED", "findings": findings, "code_dependencies": sorted(code_dependencies), "scanned_module_count": len(seen)}

    def feature_producer_provenance(self, pit_records: list[dict[str, Any]]) -> dict[str, Any]:
        """Prove the policy's serialized-key → runtime → generator mapping."""
        mappings = self.policy.get("feature_provenance", {})
        records, unresolved = {}, []
        pit_complete = bool(pit_records) and all(item.get("status") == "PIT_PROVEN" for item in pit_records)
        for feature in self.policy["required_v5_features"]:
            mapping = mappings.get(feature)
            if not isinstance(mapping, dict):
                records[feature] = {"status": "UNPROVEN", "reason": "MAPPING_MISSING"}
                unresolved.append(feature)
                continue
            module, function = str(mapping.get("generator_module", "")), str(mapping.get("generator_function", ""))
            source = self.root / module
            text = source.read_text(encoding="utf-8-sig") if source.is_file() else ""
            leaf = function.split(".")[-1]
            function_present = bool(leaf and re.search(rf"(?:def|class)\s+{re.escape(leaf)}\b", text))
            required_shape = all((mapping.get("serialized_feature_key"), mapping.get("runtime_field"), mapping.get("pre_safe_upstream_input_class"))) and isinstance(mapping.get("recorded_provenance_sha_fields"), list) and bool(mapping.get("recorded_provenance_sha_fields"))
            static_expected = mapping.get("static_generator_sha256")
            static_actual = sha256(source) if source.is_file() else None
            static_valid = static_expected is None or static_expected == static_actual
            mapping_valid = function_present and required_shape and static_valid
            authority_valid = True
            for field in mapping.get("recorded_provenance_sha_fields", []):
                if field == "canonical_v5_1_builder_sha256":
                    authority_valid = authority_valid and static_valid
                    continue
                authority_valid = authority_valid and all(
                    any(identity.get("provenance_field") == field and identity.get("verified") is True for identity in item.get("generator_identities", []))
                    for item in pit_records
                )
            status = "PASS" if mapping_valid and authority_valid and pit_complete else "UNPROVEN"
            records[feature] = {**mapping, "generator_function_present": function_present, "static_generator_sha256_actual": static_actual if static_expected else None, "static_generator_sha256_valid": static_valid, "mapping_status": "PASS" if mapping_valid else "UNRESOLVED", "recorded_authority_valid": authority_valid, "status": status}
            if not mapping_valid:
                unresolved.append(feature)
        proof_unresolved = [feature for feature, record in records.items() if record["status"] != "PASS"]
        return {"records": records, "unresolved_features": unresolved, "proof_unresolved_features": proof_unresolved, "mapping_status": "PASS" if not unresolved else "UNRESOLVED", "status": "PASS" if not proof_unresolved else "UNRESOLVED"}


def _columns(policy: dict[str, Any], headers: list[str]) -> list[dict[str, str]]:
    roles = {name: "METADATA" for name in policy["metadata_columns"]}
    roles.update({name: "FORBIDDEN_RESULT" for name in policy["forbidden_result_columns"]})
    roles[policy["canonical_label"]] = "TARGET"
    roles.update({name: "FEATURE" for name in policy["required_v5_features"]})
    if set(headers) - set(roles):
        _stop("STOP_UNREGISTERED_DATASET_COLUMN")
    return [{"column": column, "role": roles[column]} for column in headers]


def materialize_prediction_rows(artifacts: list[dict[str, Any]], date: str) -> tuple[dict[tuple[str, str], dict[str, Any]], set[str]]:
    """Extract actual trace/snapshot/ranked-result fields, never ``feature_values``."""
    output, races = {}, set()
    for artifact in artifacts:
        race_id, ranked = str(artifact.get("race_id", "")), artifact["ranked_results"]
        trace = {str(row.get("horse_number")): row for row in artifact["buy_gate_trace"]["horses"]}
        if not race_id or set(trace) != {str(row.get("horse_number")) for row in ranked}:
            _stop("STOP_PREDICTION_TRACE_HORSE_SET_MISMATCH")
        races.add(race_id)
        # This feature is defined against the entire Current Top5 population as
        # frozen at PRE time.  Neither a full-field entrant nor any post-result
        # validity state may change the reference maximum.
        top5_ranked = [
            row for row in ranked
            if isinstance(row.get("rank"), int) and row["rank"] <= 5
        ]
        max_adjusted = max(
            (row.get("adjusted_score") for row in top5_ranked if isinstance(row.get("adjusted_score"), (int, float))),
            default=None,
        )
        for ranked_row in ranked:
            number, gate = str(ranked_row.get("horse_number")), trace[str(ranked_row.get("horse_number"))]
            values = {"shadow_ai_rank": gate.get("shadow_ai_rank"), "decision_score": gate.get("decision_score", ranked_row.get("decision_score")), "final_score": gate.get("final_score", ranked_row.get("final_score")), "adjusted_score": gate.get("adjusted_score", ranked_row.get("adjusted_score")), "absolute_quality_pass": gate.get("absolute_quality_pass"), "relative_advantage_pass": gate.get("relative_advantage_pass"), "effective_reliability_pass": gate.get("effective_reliability_pass"), "risk_guard_pass": gate.get("risk_guard_pass"), "consensus_positive_count": gate.get("positive_count", ranked_row.get("consensus_positive_count")), "consensus_negative_count": gate.get("negative_count", ranked_row.get("consensus_negative_count")), "risk_count": ranked_row.get("risk_count"), "conflict_count": ranked_row.get("conflict_count"), "race_state": ranked_row.get("buy_v1_rc1_race_state"), **gate.get("evaluator_score_snapshot", {}), "adjusted_score_gap_to_top": None if max_adjusted is None or not isinstance(ranked_row.get("adjusted_score"), (int, float)) else ranked_row["adjusted_score"]-max_adjusted}
            for key in ("decision_score", "final_score", "adjusted_score", "consensus_positive_count", "consensus_negative_count"):
                if values.get(key) is None:
                    values[key] = ranked_row.get(key)
            output[(race_id, number)] = {"date": date, "values": values, "top5": int(ranked_row.get("rank", 999)) <= 5, "artifact_path": artifact.get("_ws2_artifact_path"), "artifact_sha256": artifact.get("_ws2_artifact_sha256")}
    return output, races


def reconcile_pipeline(prediction_races: set[str], dataset_rows: list[dict[str, str]], exclusions: dict[str, Any]) -> dict[str, str]:
    """Reconcile only the actual prediction population, not all daily result races."""
    training = {row.get("race_id", "") for row in dataset_rows}
    explicit = {str(row.get("race_id")): str(row.get("reason") or row.get("reason_code")) for row in exclusions.get("integrity_excluded_source_races", [])}
    reasons = {}
    for race_id in prediction_races:
        if race_id in training:
            reasons[race_id] = "DATASET_TOP5_LABEL_ELIGIBLE"
        elif race_id in explicit:
            reasons[race_id] = f"EXPLICIT_INTEGRITY_EXCLUSION:{explicit[race_id]}"
        else:
            _stop("STOP_UNEXPLAINED_SOURCE_RACE_EXCLUSION")
    return reasons


def audit_ds_chronology(bundle: Any, target_date: str) -> dict[str, int]:
    """Audit the parsed DS history that the existing adapter actually used.

    Empty *parsed* histories are recorded as legitimate zero history only when
    the adapter supplied an entry and a list.  A missing/unparseable history is
    deliberately not recast as zero history.
    """
    prior_rows = zero_history = 0
    for race in bundle.races.values():
        history_by_horse = getattr(race, "history_rows_by_horse", None)
        if not isinstance(history_by_horse, dict):
            _stop("STOP_DS_AUDIT_UNAVAILABLE")
        for entry in race.today_entries:
            raw_rows = history_by_horse.get(getattr(entry, "horse_name", ""))
            if raw_rows is None:
                _stop("STOP_DS_AUDIT_UNAVAILABLE")
            if not raw_rows:
                zero_history += 1
        # ``RaceBundle.past_races`` is the existing adapter's parsed DS
        # representation.  Audit this object, rather than a prediction-side
        # field which does not exist on TodayEntry.
        parsed = getattr(race, "past_races", None)
        if parsed is None:
            _stop("STOP_DS_AUDIT_UNAVAILABLE")
        for past in parsed:
            raw = getattr(past, "race_date", getattr(past, "date", None))
            if hasattr(raw, "strftime"):
                value = raw.strftime("%Y%m%d")
            else:
                value = "".join(character for character in str(raw or "") if character.isdigit())[:8]
            if len(value) != 8:
                _stop("STOP_DS_AUDIT_UNAVAILABLE")
            if value >= target_date:
                _stop("STOP_DS_FUTURE_OR_SAME_DAY_RUN")
            prior_rows += 1
    return {"past_race_rows": prior_rows, "legitimate_zero_history_horses": zero_history, "ds_audit_unavailable_horses": 0}


def pipeline_stage_ledger(source_races: set[str], prediction_races: set[str], result_races: set[str], dataset_rows: list[dict[str, str]], exclusions: dict[str, Any], eligibility_reasons: dict[str, str] | None = None) -> dict[str, Any]:
    """Record S0--S5 without asserting raw DE and prediction equality.

    S0 comes from the existing TARGET adapter.  S1/S2 are the frozen
    prediction artifacts, S3 is the validated result-label population, and
    S4/S5 are the V5 top-five/final dataset populations.  Each loss from an
    artifact-producing stage must have an existing manifest exclusion.
    """
    dataset_races = {str(row.get("race_id", "")) for row in dataset_rows}
    explicit = {str(row.get("race_id")): str(row.get("reason") or row.get("reason_code")) for row in exclusions.get("integrity_excluded_source_races", [])}
    eligibility_reasons = eligibility_reasons or {}
    stage_sets = {"S0_RAW_SOURCE_RACES": source_races, "S1_PREDICTION_ELIGIBLE_RACES": prediction_races, "S2_PREDICTION_ARTIFACT_RACES": prediction_races, "S3_LABEL_RESULT_ELIGIBLE_RACES": result_races, "S4_V5_DATASET_ELIGIBLE_RACES": dataset_races, "S5_FINAL_TRAINING_DATASET_RACES": dataset_races}
    raw_drops = source_races - prediction_races
    unresolved_raw = raw_drops - set(eligibility_reasons)
    if unresolved_raw:
        _stop("STOP_UNEXPLAINED_RAW_TO_PREDICTION_ELIGIBILITY_DROP")
    unexplained = (prediction_races - dataset_races) - set(explicit)
    if unexplained:
        _stop("STOP_UNEXPLAINED_SOURCE_RACE_EXCLUSION")
    return {"stage_counts": {name: len(values) for name, values in stage_sets.items()}, "artifact_to_dataset_resolution": reconcile_pipeline(prediction_races, dataset_rows, exclusions), "raw_to_prediction_eligibility": {race: "PREDICTION_ELIGIBLE" for race in prediction_races} | {race: f"PREDICTION_INELIGIBLE_{eligibility_reasons[race]}" for race in raw_drops}, "raw_nonprediction_race_count": len(raw_drops), "explicit_exclusions": explicit}


def rolling_origin_folds(roles: dict[str, list[str]]) -> dict[str, Any]:
    """Materialize approved monthly rolling-origin folds, with rejections."""
    ordered, folds, rejected = sorted(roles), [], []
    for index, validation in enumerate(ordered):
        validation_roles = set(roles[validation])
        if validation_roles & PROTECTED:
            rejected.append({"fold_id": f"RO_{validation}", "validation_month": validation, "train_months": [], "exclusion_reason": "PROTECTED_VALIDATION_MONTH"})
            continue
        train = [month for month in ordered[:index] if not (set(roles[month]) & PROTECTED)]
        if len(train) < 3:
            rejected.append({"fold_id": f"RO_{validation}", "validation_month": validation, "train_months": train, "exclusion_reason": "MINIMUM_THREE_PRIOR_ELIGIBLE_MONTHS_NOT_MET"})
            continue
        if any(month >= validation for month in train):
            _stop("STOP_ROLLING_ORIGIN_FUTURE_LEAKAGE")
        folds.append({"fold_id": f"RO_{validation}", "train_months": train, "validation_month": validation, "primary": "ROLLING_ORIGIN_MONTHLY_CROSS_FIT"})
    return {"status": "PASS" if folds else "NO_VALID_FOLD", "folds": folds, "rejected": rejected}


def shared_readiness_prerequisites(*, pit: str, dependency: dict[str, Any], provenance: dict[str, Any], folds: dict[str, Any], roles: dict[str, list[str]], label_integrity: bool, feature_integrity: bool) -> dict[str, Any]:
    """One fail-closed common safety view consumed by both iterations."""
    conditions = {
        "label_integrity": "PASS" if label_integrity else "FAILED",
        "feature_integrity": "PASS" if feature_integrity else "FAILED",
        "pit": "PASS" if pit == "PIT_PROVEN" else "UNRESOLVED",
        "dependency": "PASS" if dependency.get("status") == "PASS" else "UNRESOLVED",
        "code_provenance": "PASS" if provenance.get("status") == "PASS" else "UNRESOLVED",
        "fold_validity": "PASS" if folds.get("status") == "PASS" else "FAILED",
        "role_validity": "PASS" if not any(set(value) & PROTECTED for value in roles.values()) else "FAILED",
    }
    failed = sorted(name for name, state in conditions.items() if state == "FAILED")
    unresolved = sorted(name for name, state in conditions.items() if state == "UNRESOLVED")
    return {"conditions": conditions, "passed_prerequisites": sorted(name for name, state in conditions.items() if state == "PASS"), "failed_prerequisites": failed, "unresolved_prerequisites": unresolved, "status": "PASS" if not failed and not unresolved else "BLOCKED"}


def derive_iteration_readiness(*, shared: dict[str, Any], recipe_status: str, outside_top5_present: bool, outside_top5_complete: bool) -> dict[str, Any]:
    """Apply the same fail-closed prerequisite set to both WS2 iterations."""
    iteration_0 = "READY_FOR_PREREGISTRATION_ONLY" if shared.get("status") == "PASS" and recipe_status == "PASS" else "BLOCKED"
    iteration_0_reasons = [] if recipe_status == "PASS" else ["frozen_v5_recipe_identity_unresolved"]
    iteration_1_reasons: list[str] = []
    if not outside_top5_present:
        iteration_1_reasons.append("full_field_population_missing")
    if not outside_top5_complete:
        iteration_1_reasons.append("full_field_feature_population_incomplete")
    iteration_1 = "DATA_READY_PREREG_REQUIRED" if shared.get("status") == "PASS" and not iteration_1_reasons else "BLOCKED"
    return {
        "iteration_0": iteration_0,
        "iteration_0_reasons": iteration_0_reasons,
        "iteration_1": iteration_1,
        "iteration_1_reasons": iteration_1_reasons,
    }


def resolve_canonical_dataset_target(
    repo_root: Path | str, requested_package: str | None = None,
) -> dict[str, Any]:
    """Resolve the sole WS2 dataset authority without executing preflight.

    ``requested_package`` exists only to make attempted legacy/alternate target
    selection auditable.  There is no discovery, alias, or fallback behavior.
    """
    if requested_package is not None and requested_package.replace("\\", "/") != DATASET_ROOT:
        _stop("STOP_NONCANONICAL_DATASET_PACKAGE_REQUESTED")
    materializer = CanonicalSourceMaterializer(Path(repo_root))
    root = materializer.canonical_dataset_package()
    return {
        "dataset_package": DATASET_ROOT,
        "dataset_csv_sha256": CANONICAL_DATASET_CSV_SHA256,
        "dataset_manifest_sha256": CANONICAL_DATASET_MANIFEST_SHA256,
        "artifact_hash_index_sha256": CANONICAL_DATASET_HASH_INDEX_SHA256,
        "dataset_version": CANONICAL_DATASET_VERSION,
        "row_count": CANONICAL_DATASET_ROW_COUNT,
        "feature_count": CANONICAL_DATASET_FEATURE_COUNT,
        "policy_path": POLICY_PATH,
        "policy_sha256": POLICY_SHA256,
        "contract_path": CONTRACT_PATH,
        "contract_sha256": CONTRACT_SHA256,
        "resolved_path": _rel(Path(repo_root), root),
    }


def evaluate_preflight(repo_root: Path | str) -> dict[str, Any]:
    """Real-data-capable entrypoint.  It is intentionally not called by tests here."""
    materializer = CanonicalSourceMaterializer(Path(repo_root))
    dataset_root = materializer.canonical_dataset_package()
    headers, rows = _csv(dataset_root / "dataset.csv")
    if not rows:
        _stop("STOP_V5_DATASET_ROWS_MISSING")
    classification = _columns(materializer.policy, headers)
    prediction_rows, prediction_races, result_labels, source_races, chronology, pit_records, eligibility_reasons = {}, set(), {}, set(), [], [], {}
    for source in materializer.source_manifest(dataset_root, rows):
        bundle = materializer.target_prediction_bundle(source)
        source_races |= set(bundle.races)
        chronology.append({
            "date": source["date"],
            **audit_ds_chronology(bundle, source["date"]),
            "source_lineage_overlay": source["source_lineage_overlay"],
            "known_data_integrity_exclusion_bridge": source["known_data_integrity_exclusion_bridge"],
            "existing_adapter_compatibility_reuse": source["existing_adapter_compatibility_reuse"],
            "adapter_input_exception": bundle.preflight.get("input_exception"),
        })
        result_labels.update(materializer.target_result_labels(source))
        values, races = materialize_prediction_rows(materializer.prediction(source["prediction_root"]), source["date"])
        pit_records.append(materializer.prediction_pit_evidence(source))
        if not races <= set(bundle.races):
            _stop("STOP_PREDICTION_TARGET_RACE_SET_MISMATCH")
        for race_id in races:
            de_numbers = {str(entry.horse_number) for entry in bundle.races[race_id].today_entries}
            artifact_numbers = {number for (artifact_race, number) in values if artifact_race == race_id}
            if de_numbers != artifact_numbers:
                _stop("STOP_PREDICTION_DE_HORSE_SET_MISMATCH")
        prediction_rows.update(values); prediction_races |= races
        eligibility_reasons.update(materializer.prediction_eligibility_reasons(source["prediction_root"], races))
    for row_index, row in enumerate(rows):
        source = prediction_rows.get((row.get("race_id", ""), row.get("horse_number", "")))
        if not source:
            _stop("STOP_FEATURE_LINEAGE_UNPROVEN")
        recorded_path = str(row.get("source_prediction_artifact_path", "")).replace("\\", "/")
        if recorded_path != source["artifact_path"] or row.get("source_prediction_artifact_sha256") != source["artifact_sha256"]:
            _stop("STOP_PREDICTION_ARTIFACT_BINDING_MISMATCH")
        if any(source["values"].get(feature) is None for feature in materializer.policy["required_v5_features"]):
            _stop("STOP_REQUIRED_V5_FEATURE_UNPROVEN")
        for feature in materializer.policy["required_v5_features"]:
            actual, expected = source["values"][feature], row.get(feature)
            if str(actual).lower() != str(expected).lower():
                try:
                    equal = float(actual) == float(expected)
                except (TypeError, ValueError):
                    equal = False
                if not equal:
                    raise FeatureSourceValueMismatch({
                        "dataset_row_index": row_index,
                        "date": row.get("date"),
                        "race_id": row.get("race_id"),
                        "horse_number": row.get("horse_number"),
                        "feature": feature,
                        "dataset_value": expected,
                        "canonical_value": actual,
                        "dataset_value_type": type(expected).__name__,
                        "canonical_value_type": type(actual).__name__,
                        "source_prediction_artifact_path": source.get("artifact_path"),
                        "source_prediction_artifact_sha256": source.get("artifact_sha256"),
                    })
        label = result_labels.get((row.get("race_id", ""), row.get("horse_number", "")))
        if not label:
            _stop("STOP_LABEL_INTEGRITY_MISMATCH")
        if (
            _strict_label_boolean(label["actual_top3"]) != _strict_label_boolean(row.get("actual_top3"))
            or _strict_label_boolean(label["valid_result"]) != _strict_label_boolean(row.get("valid_result"))
        ):
            _stop("STOP_LABEL_INTEGRITY_MISMATCH")
    exclusions = _json(dataset_root / "exclusion_manifest.json")
    reconciliation = pipeline_stage_ledger(source_races, prediction_races, {race for race, _ in result_labels}, rows, exclusions, eligibility_reasons)
    months = {row.get("date", "")[:6] for row in rows}
    roles, recipe, dependency = materializer.canonical_roles(months, rows), materializer.model(), materializer.dependency_scan()
    pit = "PIT_PROVEN" if all(item["status"] == "PIT_PROVEN" for item in pit_records) and all(item["ds_audit_unavailable_horses"] == 0 for item in chronology) else "PIT_UNPROVEN"
    producer = materializer.feature_producer_provenance(pit_records)
    folds = rolling_origin_folds(roles)
    shared = shared_readiness_prerequisites(pit=pit, dependency=dependency, provenance=producer, folds=folds, roles=roles, label_integrity=True, feature_integrity=True)
    outside = [value for value in prediction_rows.values() if not value["top5"]]
    incomplete = [value for value in outside if any(value["values"].get(feature) is None for feature in materializer.policy["required_v5_features"])]
    readiness = derive_iteration_readiness(
        shared=shared,
        recipe_status=recipe["status"],
        outside_top5_present=bool(outside),
        outside_top5_complete=not incomplete,
    )
    return {"schema_version": "ws2_data_integrity_preflight_v2_canonical_format_v2", "overall_status": "PASS" if readiness["iteration_0"] != "BLOCKED" else "BLOCKED", "source_files": materializer.sources, "column_classification": classification, "canonical_source_status": {"PIT": pit, "pit_evidence": pit_records, "pipeline_reconciliation": reconciliation, "dependency": dependency, "feature_producer_provenance": producer, "roles": roles, "ds_chronology": chronology, "rolling_origin_folds": folds, "authenticated_non_race_manifest_artifacts": getattr(materializer, "manifest_non_race_artifacts", [])}, "runtime_identity": recipe, "iteration_gates": {"shared_safety_prerequisites": shared, "iteration_0": readiness["iteration_0"], "iteration_0_observability": {**shared, "iteration_specific_block_reasons": readiness["iteration_0_reasons"]}, "iteration_1": readiness["iteration_1"], "iteration_1_observability": {**shared, "iteration_specific_block_reasons": readiness["iteration_1_reasons"]}, "outside_top5_horse_count": len(outside), "outside_top5_complete_count": len(outside)-len(incomplete), "outside_top5_incomplete_count": len(incomplete)}, "summary": {"caller_evidence_used": False, "real_data_preflight_executed": False, "training_started": False, "model_change": False, "buy_change": False, "production_change": False, "performance_metrics_emitted": False}}


def run_preflight(repo_root: Path | str, output_dir: Path | str) -> Path:
    root, output = Path(repo_root), Path(output_dir)
    if output.exists():
        _stop("STOP_OUTPUT_ALREADY_EXISTS")
    started = datetime.now(timezone.utc).isoformat()
    # Capture source-discovery metadata before the adapter touches the first
    # raw file.  This makes a genuine input-integrity stop auditable without
    # recasting it as a format failure or losing the intended 62-date scope.
    discovery: dict[str, Any] = {}
    try:
        discovery_materializer = CanonicalSourceMaterializer(root)
        discovery_dataset = discovery_materializer.canonical_dataset_package()
        _, discovery_rows = _csv(discovery_dataset / "dataset.csv")
        discovery_sources = discovery_materializer.source_manifest(discovery_dataset, discovery_rows)
        discovery = {"source_date_count": len(discovery_sources), "direct_additive_date_count": sum(item["prediction_source_kind"] == "DIRECT_ADDITIVE" for item in discovery_sources), "inherited_parent_date_count": sum(item["prediction_source_kind"] == "INHERITED_PARENT" for item in discovery_sources), "source_date_identities": [{"date": item["date"], "prediction_root": item["prediction_root"], "files": item["files"], "source_lineage_overlay": item["source_lineage_overlay"], "known_data_integrity_exclusion_bridge": item["known_data_integrity_exclusion_bridge"], "existing_adapter_compatibility_reuse": item["existing_adapter_compatibility_reuse"]} for item in discovery_sources]}
    except DataIntegrityStop as error:
        discovery = {"discovery_stop": str(error)}
    try:
        result = evaluate_preflight(root)
    except DataIntegrityStop as error:
        code = str(error)
        implementation_prefixes = ("STOP_CANONICAL_", "STOP_PREDICTION_ARTIFACT_MALFORMED", "STOP_RACE_INDEX_", "STOP_REQUIRED_FEATURE_MODULE_")
        classification = "IMPLEMENTATION_COMPATIBILITY_STOP" if code.startswith(implementation_prefixes) else "DATA_INTEGRITY_STOP"
        check = {"check_id": "FAIL_CLOSED_GATE", "reason_code": code}
        if isinstance(error, (FeatureSourceValueMismatch, HashValidationStop)):
            check["diagnostic_context"] = error.context
        result = {"schema_version": "ws2_data_integrity_preflight_v2_canonical_format_v2", "overall_status": "STOP", "stop_classification": classification, "checks": [check], "summary": {"caller_evidence_used": False, "real_data_preflight_executed": False, "training_started": False, "model_change": False, "buy_change": False, "production_change": False}}
    result["compatibility_dry_run"] = {"COMPATIBILITY_DRY_RUN_ONLY": True, "FORMAL_EVIDENCE": False, "PERFORMANCE_EVIDENCE": False, "RETROACTIVE_PROMOTION_PROHIBITED": True, "started_at_utc": started, "completed_at_utc": datetime.now(timezone.utc).isoformat(), "implementation_sha256": sha256(Path(__file__)), "policy_sha256": sha256(root / POLICY_PATH), "contract_sha256": sha256(root / CONTRACT_PATH), "source_discovery": discovery}
    output.mkdir(parents=True)
    target = output / "ws2_data_integrity_preflight_v2_canonical_format.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    (output / "artifact_hashes.json").write_text(json.dumps({target.name: sha256(target)}, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return target
