"""Deterministic, fail-closed REG-009 retrospective OOS result cohort generator.

This module is intentionally independent from Production, ResultImporter,
Prediction, Shadow, Registry, Knowledge, and feature flags.  Importing it has
no side effects.  Formal generation happens only through :meth:`generate` or
the explicit CLI ``--generate`` action.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
FORMAL_OUTPUT_ROOT = ROOT / "reports" / "reg009_retrospective_oos_20260718_20260719_result_cohort_v1"
REQUIRED_ARTIFACTS = (
    "cohort_manifest.json",
    "race_results.json",
    "horse_results.json",
    "population_reconciliation.json",
    "derivation_validation.json",
    "provenance.json",
    "report.md",
)
SCHEMA_VERSION = "REG009_RETROSPECTIVE_OOS_RESULT_COHORT_V1"
GENERATOR_VERSION = "REG009_RETROSPECTIVE_OOS_RESULT_COHORT_GENERATOR_V1"
EXPECTED_AUTHORITY_SHA256 = "7e2d26dc6ea381a8f6762de36144739837aff7df321dc93fbd48c605e951435c"
EXPECTED_FROZEN_SPEC_SHA256 = "7f07307f918755a051350f61344de166b90dd6782bb33337382997532a6cc22a"
EXPECTED_GENERATION_SPEC_SHA256 = "8c1ff1e90c8c044094b49d1b5bfe2c76f87bd023882faa78b2a9a32084a4ef2a"
EXPECTED_POPULATION_SHA256 = "eb6fc0845cdc643409a03669cb0d96348959ee3c9c04a58e48c4efff4c3a2b55"
EXPECTED_RAW_SHA256 = "69159a1237b89b3f6433f1c775a65889d417e1253755085fe29936ca0c9b8730"
EXPECTED_SCHEMA_SHA256 = "54ce8fe71652daeadadee46397b115cb8ea2377a3c24e2f32060d5de7d6b5a88"
STAGING_DIRECTORY_MAX_ATTEMPTS = 16


class CohortGenerationError(RuntimeError):
    """Fail-closed error carrying a stable reason code and optional details."""

    def __init__(self, reason_code: str, details: Any = None):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.details = details


@dataclass(frozen=True)
class ResultCohortGeneratorConfig:
    authority_path: Path = ROOT / "docs" / "keibaai_constitution_v1_2.md"
    authority_sha256: str = EXPECTED_AUTHORITY_SHA256
    frozen_spec_path: Path = ROOT / "docs" / "reg009_knowledge_coverage_uncertainty_retrospective_oos_frozen_spec_v1.md"
    frozen_spec_sha_path: Path = ROOT / "docs" / "reg009_knowledge_coverage_uncertainty_retrospective_oos_frozen_spec_v1.sha256"
    frozen_spec_sha256: str = EXPECTED_FROZEN_SPEC_SHA256
    generation_spec_path: Path = ROOT / "docs" / "reg009_retrospective_oos_result_cohort_generation_spec_v1.md"
    generation_spec_sha_path: Path = ROOT / "docs" / "reg009_retrospective_oos_result_cohort_generation_spec_v1.sha256"
    generation_spec_sha256: str = EXPECTED_GENERATION_SPEC_SHA256
    schema_path: Path = ROOT / "docs" / "target_bulk_result_schema_v1.json"
    schema_sha_path: Path = ROOT / "docs" / "target_bulk_result_schema_v1.sha256"
    schema_sha256: str = EXPECTED_SCHEMA_SHA256
    population_path: Path = ROOT / "reports" / "reg009_target_population_20260718_20260719_v1" / "summary.json"
    population_sha256: str = EXPECTED_POPULATION_SHA256
    raw_path: Path = ROOT / "data" / "raw" / "target" / "full_race_observation" / "full_fukushima2_kokura2_hakodate1.csv"
    raw_sha256: str = EXPECTED_RAW_SHA256
    conflict_root: Path = ROOT / "reports" / "reg009_full_race_observation_20260718_20260719_conflict_diagnosis_v1"
    allowed_dates: tuple[str, ...] = ("20260718", "20260719")
    expected_raw_row_count: int = 4367
    expected_raw_race_count: int = 336
    expected_raw_date_count: int = 12
    expected_raw_venue_count: int = 3
    expected_population_all: int = 72
    expected_population_included: int = 64
    expected_population_newcomer: int = 6
    expected_population_jump: int = 2
    expected_crosscheck_races: int = 22
    expected_crosscheck_horses: int = 311
    verify_document_contracts: bool = True
    verify_conflict_diagnosis: bool = True
    verify_daily_summary_inputs: bool = True


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n").encode("utf-8")


def _read_sha_record(path: Path) -> str:
    if not path.is_file():
        raise CohortGenerationError("SHA_RECORD_NOT_FOUND", str(path))
    match = re.search(r"\b[0-9a-fA-F]{64}\b", path.read_text(encoding="utf-8"))
    if not match:
        raise CohortGenerationError("INVALID_SHA_RECORD", str(path))
    return match.group(0).lower()


def _require_sha(path: Path, expected: str, reason: str) -> str:
    if not path.is_file():
        raise CohortGenerationError(reason, {"path": str(path), "error": "NOT_FOUND"})
    actual = sha256_path(path)
    if actual != expected:
        raise CohortGenerationError(reason, {"path": str(path), "expected": expected, "actual": actual})
    return actual


def _parse_int_literal(value: Any, reason: str, details: Any) -> int:
    text = str(value).strip()
    if not re.fullmatch(r"[+-]?[0-9]+", text):
        raise CohortGenerationError(reason, details)
    return int(text)


def _parse_meeting_ordinal(value: Any, reason: str, details: Any) -> int:
    """Parse TARGET's one-character meeting ordinal (A=10, B=11, C=12)."""

    text = str(value).strip().upper()
    if re.fullmatch(r"[0-9]+", text):
        parsed = int(text)
    elif text in {"A", "B", "C"}:
        parsed = 10 + ord(text) - ord("A")
    else:
        raise CohortGenerationError(reason, details)
    if not 1 <= parsed <= 12:
        raise CohortGenerationError(reason, details)
    return parsed


def _race_sort_key(record: dict[str, Any]) -> tuple[str, int, str]:
    return (str(record["canonical_race_id"]), int(record.get("horse_number", 0)), str(record.get("horse_name", "")))


class Reg009RetrospectiveOOSResultCohortGeneratorV1:
    """Read one frozen raw source and create the seven frozen cohort artifacts."""

    def __init__(self, config: ResultCohortGeneratorConfig | None = None):
        self.config = config or ResultCohortGeneratorConfig()

    def validate_inputs_only(self) -> dict[str, Any]:
        """Validate authority and structural inputs without deriving result labels."""

        prepared = self._prepare(derive_results=False, crosscheck=False)
        return {
            "status": "PASS",
            "mode": "VALIDATE_INPUT_ONLY",
            "authority_sha256": prepared["authority"]["authority_sha256"],
            "frozen_spec_sha256": prepared["authority"]["frozen_spec_sha256"],
            "generation_spec_sha256": prepared["authority"]["generation_spec_sha256"],
            "schema_sha256": prepared["authority"]["schema_sha256"],
            "raw_sha256": prepared["authority"]["raw_sha256"],
            "population_sha256": prepared["authority"]["population_sha256"],
            "raw_row_count": prepared["raw_summary"]["raw_row_count"],
            "raw_race_count": prepared["raw_summary"]["raw_race_count"],
            "raw_date_count": prepared["raw_summary"]["raw_date_count"],
            "raw_venue_count": prepared["raw_summary"]["raw_venue_count"],
            "allowed_dates": list(self.config.allowed_dates),
            "allowed_date_race_count": len(prepared["mapped_races"]),
            "target_population_count": prepared["population_counts"]["included"],
            "excluded_population_count": prepared["population_counts"]["excluded"],
            "identity_fields_present": True,
            "result_derivation_performed": False,
            "crosscheck_performed": False,
            "formal_cohort_generation_count": 0,
        }

    def generate(self, output_root: str | Path, *, generated_at: str) -> dict[str, Any]:
        if not generated_at or not isinstance(generated_at, str):
            raise CohortGenerationError("GENERATED_AT_REQUIRED")
        root = Path(output_root).resolve()
        if root.exists() or root.is_symlink():
            raise CohortGenerationError("OUTPUT_ROOT_ALREADY_EXISTS", str(root))
        parent = root.parent
        if not parent.is_dir() or parent.is_symlink():
            raise CohortGenerationError("OUTPUT_PARENT_INVALID", str(parent))

        prepared = self._prepare(derive_results=True, crosscheck=True)
        payloads = self._build_artifacts(prepared, generated_at)
        artifact_sha = {name: hashlib.sha256(payloads[name]).hexdigest() for name in REQUIRED_ARTIFACTS if name != "provenance.json"}
        provenance = self._provenance(prepared, generated_at, artifact_sha)
        provenance_bytes = canonical_json_bytes(provenance)
        staging_prefix = f".{root.name}.staging-"
        staging = self._create_staging_directory(parent, staging_prefix)
        try:
            for name in REQUIRED_ARTIFACTS:
                data = provenance_bytes if name == "provenance.json" else payloads[name]
                self._write_artifact(staging / name, data)

            from review.reg009_retrospective_oos_result_cohort_validator_v1 import (
                Reg009RetrospectiveOOSResultCohortValidatorV1,
            )

            validation = Reg009RetrospectiveOOSResultCohortValidatorV1(self.config).validate(staging)
            if validation["status"] != "PASS":
                raise CohortGenerationError("GENERATED_COHORT_VALIDATION_FAILED", validation)
            self._atomic_publish(staging, root)
        except Exception as exc:
            try:
                self._cleanup_staging(staging, parent, staging_prefix)
            except Exception as cleanup_exc:
                raise CohortGenerationError(
                    "STAGING_CLEANUP_FAILED",
                    {
                        "original_reason_code": getattr(exc, "reason_code", "UNEXPECTED_GENERATION_ERROR"),
                        "original_error": str(exc),
                        "cleanup_error": str(cleanup_exc),
                    },
                ) from cleanup_exc
            if isinstance(exc, CohortGenerationError):
                raise
            raise CohortGenerationError(
                "STAGING_WRITE_OR_PUBLISH_FAILED",
                {"error_type": type(exc).__name__, "error": str(exc)},
            ) from exc
        return {
            "status": "PASS",
            "output_root": str(root.resolve()),
            "artifact_count": len(REQUIRED_ARTIFACTS),
            "artifact_sha256": {**artifact_sha, "provenance.json": hashlib.sha256(provenance_bytes).hexdigest()},
            "validator": validation,
        }

    @staticmethod
    def _write_artifact(path: Path, data: bytes) -> None:
        with path.open("xb") as handle:
            handle.write(data)

    @staticmethod
    def _mkdir_staging_candidate(candidate: Path, *, platform_name: str | None = None) -> None:
        """Create one staging candidate with platform-appropriate permissions."""

        current_platform = os.name if platform_name is None else platform_name
        if current_platform == "nt":
            os.mkdir(candidate)
        else:
            os.mkdir(candidate, 0o700)

    @classmethod
    def _create_staging_directory(
        cls,
        parent: Path,
        prefix: str,
        *,
        max_attempts: int = STAGING_DIRECTORY_MAX_ATTEMPTS,
    ) -> Path:
        """Exclusively create a collision-safe staging directory under *parent*."""

        parent_resolved = parent.resolve(strict=True)
        if not parent_resolved.is_dir() or parent_resolved.is_symlink():
            raise CohortGenerationError("STAGING_DIRECTORY_PARENT_INVALID", str(parent_resolved))
        if max_attempts < 1:
            raise CohortGenerationError("STAGING_DIRECTORY_COLLISION_LIMIT_EXCEEDED", max_attempts)

        for _ in range(max_attempts):
            suffix = secrets.token_hex(8)
            if not re.fullmatch(r"[0-9a-f]{16}", suffix):
                raise CohortGenerationError("STAGING_DIRECTORY_PATH_INVALID", suffix)
            candidate = parent / f"{prefix}{suffix}"
            if (
                candidate.parent.resolve(strict=True) != parent_resolved
                or not candidate.name.startswith(prefix)
            ):
                raise CohortGenerationError("STAGING_DIRECTORY_PATH_INVALID", str(candidate))
            try:
                cls._mkdir_staging_candidate(candidate)
            except FileExistsError:
                continue
            except OSError as exc:
                raise CohortGenerationError(
                    "STAGING_DIRECTORY_CREATE_FAILED",
                    {"error_type": type(exc).__name__, "error": str(exc), "path": str(candidate)},
                ) from exc

            try:
                cls._validate_staging_directory(candidate, parent_resolved, prefix)
            except Exception as exc:
                try:
                    candidate.rmdir()
                except Exception as cleanup_exc:
                    raise CohortGenerationError(
                        "STAGING_DIRECTORY_VALIDATION_CLEANUP_FAILED",
                        {
                            "original_reason_code": getattr(exc, "reason_code", "STAGING_DIRECTORY_VALIDATION_FAILED"),
                            "cleanup_error": str(cleanup_exc),
                            "path": str(candidate),
                        },
                    ) from cleanup_exc
                if isinstance(exc, CohortGenerationError):
                    raise
                raise CohortGenerationError(
                    "STAGING_DIRECTORY_VALIDATION_FAILED",
                    {"error_type": type(exc).__name__, "error": str(exc), "path": str(candidate)},
                ) from exc
            return candidate

        raise CohortGenerationError("STAGING_DIRECTORY_COLLISION_LIMIT_EXCEEDED", max_attempts)

    @staticmethod
    def _validate_staging_directory(candidate: Path, parent_resolved: Path, prefix: str) -> None:
        if candidate.is_symlink():
            raise CohortGenerationError("STAGING_DIRECTORY_REPARSE_POINT_REFUSED", str(candidate))
        try:
            metadata = candidate.stat(follow_symlinks=False)
        except OSError as exc:
            raise CohortGenerationError("STAGING_DIRECTORY_NOT_ACCESSIBLE", str(candidate)) from exc
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        file_attributes = getattr(metadata, "st_file_attributes", 0)
        if reparse_flag and file_attributes & reparse_flag:
            raise CohortGenerationError("STAGING_DIRECTORY_REPARSE_POINT_REFUSED", str(candidate))
        if not candidate.is_dir():
            raise CohortGenerationError("STAGING_DIRECTORY_NOT_DIRECTORY", str(candidate))
        if (
            candidate.parent.resolve(strict=True) != parent_resolved
            or candidate.resolve(strict=True).parent != parent_resolved
            or not candidate.name.startswith(prefix)
        ):
            raise CohortGenerationError("STAGING_DIRECTORY_PATH_INVALID", str(candidate))

    @staticmethod
    def _atomic_publish(staging: Path, destination: Path) -> None:
        if destination.exists() or destination.is_symlink():
            raise CohortGenerationError("OUTPUT_ROOT_ALREADY_EXISTS_DURING_PUBLISH", str(destination))
        try:
            os.rename(staging, destination)
        except FileExistsError as exc:
            raise CohortGenerationError("OUTPUT_ROOT_ALREADY_EXISTS_DURING_PUBLISH", str(destination)) from exc
        except OSError as exc:
            raise CohortGenerationError(
                "ATOMIC_PUBLISH_FAILED",
                {"error_type": type(exc).__name__, "error": str(exc)},
            ) from exc

    @staticmethod
    def _cleanup_staging(staging: Path, parent: Path, expected_prefix: str) -> None:
        if not staging.exists() and not staging.is_symlink():
            return
        if staging.is_symlink():
            raise CohortGenerationError("STAGING_CLEANUP_SYMLINK_REFUSED", str(staging))
        if staging.parent.resolve() != parent.resolve() or not staging.name.startswith(expected_prefix):
            raise CohortGenerationError("STAGING_CLEANUP_PATH_REFUSED", str(staging))
        shutil.rmtree(staging)

    def _prepare(self, *, derive_results: bool, crosscheck: bool) -> dict[str, Any]:
        authority = self._validate_authority()
        schema = self._load_schema()
        population = self._load_population()
        raw = self._load_raw(schema)
        mapped, reconciliation = self._map_population(raw["groups"], population)
        derived = self._derive(mapped) if derive_results else None
        crosscheck_result = self._crosscheck_existing(derived, population) if crosscheck else None
        return {
            "authority": authority,
            "schema": schema,
            "population": population,
            "population_counts": reconciliation["counts"],
            "raw_summary": raw["summary"],
            "mapped_races": mapped,
            "population_reconciliation": reconciliation,
            "derived": derived,
            "crosscheck": crosscheck_result,
        }

    def _validate_authority(self) -> dict[str, str]:
        c = self.config
        authority_sha = _require_sha(c.authority_path, c.authority_sha256, "AUTHORITY_SHA256_MISMATCH")
        frozen_sha = _require_sha(c.frozen_spec_path, c.frozen_spec_sha256, "FROZEN_SPEC_SHA256_MISMATCH")
        generation_sha = _require_sha(c.generation_spec_path, c.generation_spec_sha256, "GENERATION_SPEC_SHA256_MISMATCH")
        if _read_sha_record(c.frozen_spec_sha_path) != frozen_sha:
            raise CohortGenerationError("FROZEN_SPEC_SHA_RECORD_MISMATCH")
        if _read_sha_record(c.generation_spec_sha_path) != generation_sha:
            raise CohortGenerationError("GENERATION_SPEC_SHA_RECORD_MISMATCH")
        schema_sha = _require_sha(c.schema_path, c.schema_sha256, "SCHEMA_SHA256_MISMATCH")
        if _read_sha_record(c.schema_sha_path) != schema_sha:
            raise CohortGenerationError("SCHEMA_SHA_RECORD_MISMATCH")
        population_sha = _require_sha(c.population_path, c.population_sha256, "POPULATION_SHA256_MISMATCH")
        raw_sha = _require_sha(c.raw_path, c.raw_sha256, "SOURCE_RAW_SHA256_MISMATCH")

        if c.verify_document_contracts:
            frozen_text = c.frozen_spec_path.read_text(encoding="utf-8")
            generation_text = c.generation_spec_path.read_text(encoding="utf-8")
            self._validate_document_contracts(
                frozen_text,
                generation_text,
                authority_sha=authority_sha,
                frozen_sha=frozen_sha,
                population_sha=population_sha,
                raw_sha=raw_sha,
            )

        if c.verify_conflict_diagnosis:
            self._verify_conflict_diagnosis()
        return {
            "authority_sha256": authority_sha,
            "frozen_spec_sha256": frozen_sha,
            "generation_spec_sha256": generation_sha,
            "schema_sha256": schema_sha,
            "population_sha256": population_sha,
            "raw_sha256": raw_sha,
        }

    @staticmethod
    def _validate_document_contracts(
        frozen_text: str,
        generation_text: str,
        *,
        authority_sha: str,
        frozen_sha: str,
        population_sha: str,
        raw_sha: str,
    ) -> None:
        if not re.search(r"(?mi)^- status:\s*FROZEN\s*$", frozen_text):
            raise CohortGenerationError("FROZEN_SPEC_STATUS_MISMATCH")
        frozen_required = (
            r"(?mi)^- human_approval:\s*APPROVED\s*$",
            r"(?mi)^- human_approval_date:\s*2026-08-14\s*$",
            r"(?mi)^- production_status:\s*HOLD\s*$",
        )
        if not all(re.search(pattern, frozen_text) for pattern in frozen_required):
            raise CohortGenerationError("FROZEN_SPEC_HUMAN_APPROVAL_CONTRACT_MISMATCH")
        if authority_sha not in frozen_text:
            raise CohortGenerationError("FROZEN_SPEC_AUTHORITY_REFERENCE_MISMATCH")

        if not re.search(r"(?mi)^- Status:\s*`APPROVED / FROZEN`\s*$", generation_text):
            raise CohortGenerationError("GENERATION_SPEC_STATUS_MISMATCH")
        generation_required = (
            r"(?mi)^- Approved by:\s*`Human`\s*$",
            r"(?mi)^- Approved date:\s*`2026-08-14`\s*$",
            r"(?mi)^- Production status:\s*`HOLD`\s*$",
            r"(?mi)^- Registry change:\s*`PROHIBITED`\s*$",
            r"(?mi)^- Knowledge change:\s*`PROHIBITED`\s*$",
        )
        if not all(re.search(pattern, generation_text) for pattern in generation_required):
            raise CohortGenerationError("GENERATION_SPEC_HUMAN_APPROVAL_CONTRACT_MISMATCH")
        required_tokens = (authority_sha, frozen_sha, population_sha, raw_sha)
        missing = [token for token in required_tokens if token not in generation_text]
        if missing:
            raise CohortGenerationError("GENERATION_SPEC_CROSS_REFERENCE_MISMATCH", missing)

    def _verify_conflict_diagnosis(self) -> None:
        root = self.config.conflict_root
        provenance_path = root / "provenance.json"
        if not provenance_path.is_file():
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_NOT_FOUND")
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_NOT_READABLE", str(exc)) from exc
        expected = provenance.get("artifact_sha256")
        if not isinstance(expected, dict) or len(expected) != 7:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_HASH_MANIFEST_INVALID")
        for name, digest in expected.items():
            _require_sha(root / name, str(digest), "CONFLICT_DIAGNOSIS_SHA256_MISMATCH")
        try:
            summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
            impact = json.loads((root / "frozen_spec_impact.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_SEMANTIC_ARTIFACT_NOT_READABLE", str(exc)) from exc
        summary_required = {"final_decision", "race_count", "file_count", "horse_row_count"}
        impact_required = {
            "race_count", "horse_row_count", "horse_identity_mismatch_count", "row_set_mismatch_count",
            "valid_result_mismatch_count", "actual_top3_mismatch_count",
            "frozen_spec_decision_impact_race_count", "all_selected_horses_uniquely_identifiable",
        }
        missing = sorted(summary_required.difference(summary)) + sorted(impact_required.difference(impact))
        if missing:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_REQUIRED_FIELD_MISSING", missing)
        if summary["final_decision"] != "CONFLICT_DIAGNOSIS_COMPLETE":
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_STATUS_MISMATCH")
        if int(summary["race_count"]) != self.config.expected_crosscheck_races or int(impact["race_count"]) != self.config.expected_crosscheck_races:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_RACE_COUNT_MISMATCH")
        if int(summary["file_count"]) != self.config.expected_crosscheck_races * 2:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_FILE_COUNT_MISMATCH")
        if int(summary["horse_row_count"]) != self.config.expected_crosscheck_horses or int(impact["horse_row_count"]) != self.config.expected_crosscheck_horses:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_HORSE_COUNT_MISMATCH")
        if int(impact["horse_identity_mismatch_count"]) != 0 or int(impact["row_set_mismatch_count"]) != 0 or impact["all_selected_horses_uniquely_identifiable"] is not True:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_IDENTITY_MISMATCH")
        if int(impact["valid_result_mismatch_count"]) != 0:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_VALID_RESULT_MISMATCH")
        if int(impact["actual_top3_mismatch_count"]) != 0:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_ACTUAL_TOP3_MISMATCH")
        if int(impact["frozen_spec_decision_impact_race_count"]) != 0:
            raise CohortGenerationError("CONFLICT_DIAGNOSIS_FROZEN_DECISION_IMPACT")

    def _load_schema(self) -> dict[str, Any]:
        try:
            schema = json.loads(self.config.schema_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CohortGenerationError("SCHEMA_NOT_READABLE", str(exc)) from exc
        columns = schema.get("ordered_columns")
        if (
            schema.get("schema_name") != "TARGET_BULK_RESULT_SCHEMA_V1"
            or schema.get("header_present") is not False
            or schema.get("encoding", "").lower() != "cp932"
            or schema.get("column_count") != 50
            or not isinstance(columns, list)
            or len(columns) != 50
            or len(set(columns)) != 50
        ):
            raise CohortGenerationError("SCHEMA_STRUCTURE_MISMATCH")
        required = {"年", "月", "日", "回次", "場所", "日次", "レース番号", "頭数", "馬番", "馬名", "確定着順", "異常コード"}
        if not required.issubset(columns):
            raise CohortGenerationError("SCHEMA_REQUIRED_FIELDS_MISSING", sorted(required.difference(columns)))
        return schema

    def _load_population(self) -> dict[str, Any]:
        try:
            population = json.loads(self.config.population_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CohortGenerationError("POPULATION_NOT_READABLE", str(exc)) from exc
        if population.get("status") != "TARGET_POPULATION_FIXED" or population.get("target_population_fixed") is not True:
            raise CohortGenerationError("POPULATION_STATUS_MISMATCH")
        records = population.get("all_races")
        if not isinstance(records, list):
            raise CohortGenerationError("POPULATION_RECORDS_MISSING")
        if self.config.verify_daily_summary_inputs:
            for item in population.get("inputs", []):
                path = ROOT / str(item.get("path", ""))
                _require_sha(path, str(item.get("sha256", "")), "DAILY_SUMMARY_SHA256_MISMATCH")
        return population

    def _load_raw(self, schema: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.config.raw_path.open("r", encoding="cp932", errors="strict", newline="") as handle:
                rows = list(csv.reader(handle))
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise CohortGenerationError("RAW_DECODE_OR_CSV_FAILURE", str(exc)) from exc
        if not rows:
            raise CohortGenerationError("RAW_FILE_EMPTY")
        columns = schema["ordered_columns"]
        if rows[0] == columns or (rows[0] and rows[0][0].strip() == "年"):
            raise CohortGenerationError("HEADER_PRESENT_NOT_ALLOWED")
        for line, row in enumerate(rows, 1):
            if len(row) != 50:
                raise CohortGenerationError("COLUMN_COUNT_MISMATCH", {"line": line, "column_count": len(row)})
            if not row or all(not cell.strip() for cell in row):
                raise CohortGenerationError("EMPTY_ROW_NOT_ALLOWED", line)

        if self.config.expected_raw_row_count and len(rows) != self.config.expected_raw_row_count:
            raise CohortGenerationError("RAW_ROW_COUNT_MISMATCH", len(rows))

        groups: OrderedDict[tuple[str, str, int], list[dict[str, Any]]] = OrderedDict()
        all_races: set[tuple[str, str, int]] = set()
        all_dates: set[str] = set()
        all_venues: set[str] = set()
        active_key: tuple[str, str, int] | None = None
        closed_keys: set[tuple[str, str, int]] = set()
        for line, row in enumerate(rows, 1):
            record = {name: str(value).strip() for name, value in zip(columns, row)}
            year = _parse_int_literal(record["年"], "INVALID_DATE_FIELD", {"line": line, "field": "年"})
            month = _parse_int_literal(record["月"], "INVALID_DATE_FIELD", {"line": line, "field": "月"})
            day = _parse_int_literal(record["日"], "INVALID_DATE_FIELD", {"line": line, "field": "日"})
            full_year = year if year >= 2000 else 2000 + year
            date_text = f"{full_year:04d}{month:02d}{day:02d}"
            venue = record["場所"]
            race_number = _parse_int_literal(record["レース番号"], "INVALID_RACE_NUMBER", line)
            field_size = _parse_int_literal(record["頭数"], "INVALID_FIELD_SIZE", line)
            horse_number = _parse_int_literal(record["馬番"], "INVALID_HORSE_NUMBER", line)
            if not (1 <= race_number <= 12 and 1 <= field_size <= 99 and 1 <= horse_number <= field_size):
                raise CohortGenerationError("RAW_SENTINEL_VALIDATION_FAILED", line)
            if not record["馬名"]:
                raise CohortGenerationError("HORSE_NAME_MISSING", line)
            _parse_int_literal(record["確定着順"], "UNPARSEABLE_FINISH", line)
            _parse_int_literal(record["異常コード"], "UNKNOWN_OR_UNPARSEABLE_ABNORMAL_STATUS", line)

            key = (date_text, venue, race_number)
            all_dates.add(date_text)
            all_venues.add(venue)
            all_races.add(key)
            if date_text not in self.config.allowed_dates:
                continue
            if active_key is not None and key != active_key:
                closed_keys.add(active_key)
            if key in closed_keys:
                raise CohortGenerationError("DUPLICATE_RACE", key)
            active_key = key
            record["_source_row_number"] = line
            record["_date"] = date_text
            record["_race_number"] = race_number
            record["_field_size"] = field_size
            record["_horse_number"] = horse_number
            groups.setdefault(key, []).append(record)

        if set(self.config.allowed_dates).difference(all_dates):
            raise CohortGenerationError("TARGET_DATE_MISSING", sorted(set(self.config.allowed_dates).difference(all_dates)))
        if self.config.expected_raw_race_count and len(all_races) != self.config.expected_raw_race_count:
            raise CohortGenerationError("RAW_RACE_COUNT_MISMATCH", len(all_races))
        if self.config.expected_raw_date_count and len(all_dates) != self.config.expected_raw_date_count:
            raise CohortGenerationError("RAW_DATE_COUNT_MISMATCH", len(all_dates))
        if self.config.expected_raw_venue_count and len(all_venues) != self.config.expected_raw_venue_count:
            raise CohortGenerationError("RAW_VENUE_COUNT_MISMATCH", len(all_venues))

        for key, race_rows in groups.items():
            fields = {row["_field_size"] for row in race_rows}
            if len(fields) != 1 or next(iter(fields)) != len(race_rows):
                raise CohortGenerationError("HORSE_MISSING_OR_FIELD_SIZE_MISMATCH", {"race": key, "rows": len(race_rows), "field_sizes": sorted(fields)})
            stable_fields = ("年", "月", "日", "回次", "場所", "日次", "レース番号", "頭数")
            for field in stable_fields:
                if len({row[field] for row in race_rows}) != 1:
                    raise CohortGenerationError("RACE_IDENTITY_COLLISION", {"race": key, "field": field})
            by_number: dict[int, str] = {}
            by_name: dict[str, int] = {}
            for row in race_rows:
                number, name = row["_horse_number"], row["馬名"]
                if number in by_number:
                    code = "IDENTITY_COLLISION" if by_number[number] != name else "DUPLICATE_HORSE"
                    raise CohortGenerationError(code, {"race": key, "horse_number": number})
                if name in by_name and by_name[name] != number:
                    raise CohortGenerationError("AMBIGUOUS_HORSE_MAPPING", {"race": key, "horse_name": name})
                by_number[number] = name
                by_name[name] = number
        return {
            "groups": groups,
            "summary": {
                "raw_row_count": len(rows),
                "raw_race_count": len(all_races),
                "raw_date_count": len(all_dates),
                "raw_venue_count": len(all_venues),
                "allowed_date_race_count": len(groups),
                "column_count": 50,
                "encoding": "cp932",
                "header_present": False,
            },
        }

    def _map_population(self, raw_groups: OrderedDict, population: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        records = population["all_races"]
        c = self.config
        status_counts = Counter(str(row.get("population_status")) for row in records)
        included = status_counts["TARGET_POPULATION_INCLUDED"]
        newcomer = status_counts["EXCLUDED_NEWCOMER"]
        jump = status_counts["EXCLUDED_JUMP"]
        excluded = newcomer + jump
        if (len(records), included, newcomer, jump) != (
            c.expected_population_all,
            c.expected_population_included,
            c.expected_population_newcomer,
            c.expected_population_jump,
        ):
            raise CohortGenerationError("POPULATION_COUNT_MISMATCH", dict(status_counts))
        if included + excluded != len(records):
            raise CohortGenerationError("POPULATION_RECONCILIATION_FAILED")

        index: dict[tuple[str, str, int], dict[str, Any]] = {}
        canonical_ids: set[str] = set()
        for row in records:
            key = (str(row.get("date")), str(row.get("venue_ja")), int(row.get("race_number")))
            if key in index:
                raise CohortGenerationError("AMBIGUOUS_RACE_MAPPING", key)
            canonical = str(row.get("canonical_race_id", ""))
            if not canonical or canonical in canonical_ids:
                raise CohortGenerationError("RACE_IDENTITY_COLLISION", canonical)
            index[key] = row
            canonical_ids.add(canonical)

        extra = sorted(key for key in raw_groups if key not in index)
        missing = sorted(key for key in index if key not in raw_groups)
        if extra:
            raise CohortGenerationError("UNEXPECTED_RACE", extra)
        if missing:
            raise CohortGenerationError("TARGET_RACE_MISSING", missing)

        mapped: list[dict[str, Any]] = []
        for key, population_row in sorted(index.items(), key=lambda item: item[1]["canonical_race_id"]):
            race_rows = raw_groups[key]
            meeting_numbers = {_parse_meeting_ordinal(r["回次"], "INVALID_MEETING_NUMBER", key) for r in race_rows}
            meeting_days = {_parse_meeting_ordinal(r["日次"], "INVALID_MEETING_DAY", key) for r in race_rows}
            if meeting_numbers != {int(population_row["meeting_number"])} or meeting_days != {int(population_row["meeting_day"])}:
                raise CohortGenerationError("RACE_IDENTITY_COLLISION", key)
            mapped.append({"population": population_row, "rows": race_rows})
        return mapped, {
            "status": "PASS",
            "counts": {"all": len(records), "included": included, "excluded": excluded, "newcomer": newcomer, "jump": jump},
            "missing_race_count": 0,
            "extra_race_count": 0,
            "duplicate_race_count": 0,
            "formula": f"{included} + {excluded} = {len(records)}",
        }

    def _derive(self, mapped: list[dict[str, Any]]) -> dict[str, Any]:
        race_records: list[dict[str, Any]] = []
        horse_records: list[dict[str, Any]] = []
        invalid_count = 0
        for item in mapped:
            pop = item["population"]
            derived_race_horses: list[dict[str, Any]] = []
            for raw in item["rows"]:
                finish = _parse_int_literal(raw["確定着順"], "UNPARSEABLE_FINISH", raw["_source_row_number"])
                abnormal = _parse_int_literal(raw["異常コード"], "UNKNOWN_OR_UNPARSEABLE_ABNORMAL_STATUS", raw["_source_row_number"])
                field_size = int(raw["_field_size"])
                if abnormal == 0:
                    if not 1 <= finish <= field_size:
                        raise CohortGenerationError("NORMAL_STATUS_INVALID_FINISH", {"line": raw["_source_row_number"], "finish": finish, "field_size": field_size})
                    valid = True
                    reason = "NORMAL_STATUS_POSITIVE_FINISH"
                else:
                    valid = False
                    reason = "NONZERO_ABNORMAL_STATUS"
                    invalid_count += 1
                top3 = bool(valid and finish in {1, 2, 3})
                canonical = str(pop["canonical_race_id"])
                record = {
                    "canonical_race_id": canonical,
                    "source_race_id": str(pop["target_race_key"]),
                    "source_row_number": int(raw["_source_row_number"]),
                    "horse_number": int(raw["_horse_number"]),
                    "horse_name": raw["馬名"],
                    "stable_source_horse_id": None,
                    "identity_key": f"{canonical}|{int(raw['_horse_number'])}",
                    "raw_finish": raw["確定着順"],
                    "parsed_finish": finish,
                    "raw_abnormal_status": raw["異常コード"],
                    "derived_valid_result": valid,
                    "derived_actual_top3": top3,
                    "derivation_reason": reason,
                    "source_raw_sha256": self.config.raw_sha256,
                }
                derived_race_horses.append(record)
                if pop["population_status"] == "TARGET_POPULATION_INCLUDED":
                    horse_records.append(record)
            self._validate_skip_rank(str(pop["canonical_race_id"]), derived_race_horses)
            valid_count = sum(bool(x["derived_valid_result"]) for x in derived_race_horses)
            race_records.append({
                "source_race_id": str(pop["target_race_key"]),
                "canonical_race_id": str(pop["canonical_race_id"]),
                "source_calendar_date": str(pop["date"]),
                "venue": str(pop["venue_canonical"]),
                "race_number": int(pop["race_number"]),
                "source_raw_path": self._display_path(self.config.raw_path),
                "source_raw_sha256": self.config.raw_sha256,
                "population_record_path": self._display_path(self.config.population_path),
                "population_record_sha256": self.config.population_sha256,
                "population_status": str(pop["population_status"]),
                "included_in_oos_cohort": pop["population_status"] == "TARGET_POPULATION_INCLUDED",
                "exclusion_reason": pop.get("exclusion_reason"),
                "source_horse_row_count": len(derived_race_horses),
                "derived_valid_horse_count": valid_count,
                "derived_invalid_horse_count": len(derived_race_horses) - valid_count,
            })
        horse_records.sort(key=_race_sort_key)
        race_records.sort(key=lambda row: row["canonical_race_id"])
        if len({x["identity_key"] for x in horse_records}) != len(horse_records):
            raise CohortGenerationError("DUPLICATE_IDENTITY_KEY")
        return {"race_records": race_records, "horse_records": horse_records, "invalid_source_row_count": invalid_count}

    @staticmethod
    def _validate_skip_rank(race_id: str, horses: Iterable[dict[str, Any]]) -> None:
        valid_finishes = [int(x["parsed_finish"]) for x in horses if x["derived_valid_result"]]
        counts = Counter(valid_finishes)
        expected = 1
        for rank in sorted(counts):
            if rank != expected:
                raise CohortGenerationError("INVALID_SKIP_RANK_SEQUENCE", {"race_id": race_id, "expected": expected, "actual": rank})
            expected += counts[rank]

    def _crosscheck_existing(self, derived: dict[str, Any], population: dict[str, Any]) -> dict[str, Any]:
        by_race = defaultdict_list(derived["horse_records"], "canonical_race_id")
        identity_mismatch = rowset_mismatch = valid_mismatch = top3_mismatch = 0
        horse_count = 0
        pairs = population.get("existing_result_pairs", [])
        if len(pairs) != self.config.expected_crosscheck_races:
            raise CohortGenerationError("CROSSCHECK_RACE_COUNT_MISMATCH", len(pairs))
        for pair in sorted(pairs, key=lambda row: row["canonical_race_id"]):
            race_id = str(pair["canonical_race_id"])
            horse_path = ROOT / str(pair["horse_level_result_path"])
            race_path = ROOT / str(pair["race_level_result_path"])
            _require_sha(horse_path, str(pair["horse_level_sha256"]), "CROSSCHECK_SOURCE_SHA256_MISMATCH")
            _require_sha(race_path, str(pair["race_level_sha256"]), "CROSSCHECK_SOURCE_SHA256_MISMATCH")
            try:
                with horse_path.open("r", encoding="cp932", errors="strict", newline="") as handle:
                    existing_rows = list(csv.DictReader(handle))
            except (OSError, UnicodeDecodeError, csv.Error) as exc:
                raise CohortGenerationError("CROSSCHECK_SOURCE_NOT_READABLE", str(exc)) from exc
            generated = {int(row["horse_number"]): row for row in by_race.get(race_id, [])}
            existing: dict[int, dict[str, Any]] = {}
            field_size = len(generated)
            for row in existing_rows:
                number = _parse_int_literal(row.get("馬番", ""), "CROSSCHECK_HORSE_NUMBER_INVALID", race_id)
                if number in existing:
                    raise CohortGenerationError("CROSSCHECK_DUPLICATE_HORSE", {"race_id": race_id, "horse_number": number})
                finish = _parse_int_literal(row.get("確定着順", ""), "CROSSCHECK_FINISH_INVALID", race_id)
                abnormal = _parse_int_literal(row.get("異常コード", ""), "CROSSCHECK_ABNORMAL_INVALID", race_id)
                valid = bool(abnormal == 0 and 1 <= finish <= field_size)
                actual_top3 = bool(valid and finish in {1, 2, 3})
                existing[number] = {"horse_name": str(row.get("馬名", "")).strip(), "valid": valid, "top3": actual_top3}
            horse_count += len(existing)
            if set(generated) != set(existing):
                rowset_mismatch += 1
                continue
            for number in sorted(existing):
                g, e = generated[number], existing[number]
                if str(g["horse_name"]).strip() != e["horse_name"]:
                    identity_mismatch += 1
                if bool(g["derived_valid_result"]) != e["valid"]:
                    valid_mismatch += 1
                if bool(g["derived_actual_top3"]) != e["top3"]:
                    top3_mismatch += 1
        result = {
            "status": "PASS" if not any((identity_mismatch, rowset_mismatch, valid_mismatch, top3_mismatch)) else "FAIL",
            "race_count": len(pairs),
            "horse_count": horse_count,
            "identity_mismatch_count": identity_mismatch,
            "row_set_mismatch_count": rowset_mismatch,
            "valid_result_mismatch_count": valid_mismatch,
            "actual_top3_mismatch_count": top3_mismatch,
            "source_role": "INDEPENDENT_CROSSCHECK_ONLY",
        }
        if horse_count != self.config.expected_crosscheck_horses:
            raise CohortGenerationError("CROSSCHECK_HORSE_COUNT_MISMATCH", horse_count)
        if result["status"] != "PASS":
            raise CohortGenerationError("COHORT_VALIDATION_STOP", result)
        return result

    def _build_artifacts(self, prepared: dict[str, Any], generated_at: str) -> dict[str, bytes]:
        derived = prepared["derived"]
        races = derived["race_records"]
        horses = derived["horse_records"]
        included = [r for r in races if r["included_in_oos_cohort"]]
        excluded = [r for r in races if not r["included_in_oos_cohort"]]
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "status": "COHORT_GENERATION_COMPLETE",
            "generated_at": generated_at,
            "evidence_level": "RETROSPECTIVE_OOS_LEVEL_B",
            "allowed_dates": list(self.config.allowed_dates),
            "source_raw_path": self._display_path(self.config.raw_path),
            "source_raw_sha256": self.config.raw_sha256,
            "population_record_path": self._display_path(self.config.population_path),
            "population_record_sha256": self.config.population_sha256,
            "all_race_count": len(races),
            "included_race_count": len(included),
            "excluded_race_count": len(excluded),
            "included_horse_count": len(horses),
            "included_race_ids": [r["canonical_race_id"] for r in included],
            "excluded_races": [{"canonical_race_id": r["canonical_race_id"], "population_status": r["population_status"], "exclusion_reason": r["exclusion_reason"]} for r in excluded],
            "required_artifacts": list(REQUIRED_ARTIFACTS),
            "artifact_sha256_reference": "provenance.json",
            "exclusive_create": True,
            "production_connection_count": 0,
            "feature_flag_connection_count": 0,
            "prediction_count": 0,
            "shadow_count": 0,
            "oos_evaluation_count": 0,
            "data_results_write_count": 0,
        }
        race_results = {"schema_version": SCHEMA_VERSION, "record_count": len(races), "records": races}
        horse_results = {"schema_version": SCHEMA_VERSION, "record_count": len(horses), "records": horses}
        reconciliation = {"schema_version": SCHEMA_VERSION, **prepared["population_reconciliation"], "source_allowed_date_race_count": len(races)}
        derivation = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "horse_record_count": len(horses),
            "derivation_success_count": len(horses),
            "derivation_failure_count": 0,
            "inferred_value_count": 0,
            "duplicate_identity_count": 0,
            "ambiguous_identity_count": 0,
            "missing_identity_count": 0,
            "skip_rank_validation": "PASS",
            "invalid_result_actual_top3_true_count": sum(1 for h in horses if not h["derived_valid_result"] and h["derived_actual_top3"]),
            "crosscheck": prepared["crosscheck"],
        }
        report = self._render_report(manifest, reconciliation, derivation)
        return {
            "cohort_manifest.json": canonical_json_bytes(manifest),
            "race_results.json": canonical_json_bytes(race_results),
            "horse_results.json": canonical_json_bytes(horse_results),
            "population_reconciliation.json": canonical_json_bytes(reconciliation),
            "derivation_validation.json": canonical_json_bytes(derivation),
            "report.md": report.encode("utf-8"),
        }

    def _provenance(self, prepared: dict[str, Any], generated_at: str, artifact_sha: dict[str, str]) -> dict[str, Any]:
        conflict_hashes = {}
        if self.config.verify_conflict_diagnosis:
            for path in sorted(self.config.conflict_root.iterdir()):
                if path.is_file():
                    conflict_hashes[path.name] = sha256_path(path)
        return {
            "schema_version": SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "status": "COMPLETE",
            "generated_at": generated_at,
            "authority": prepared["authority"],
            "source_raw_path": self._display_path(self.config.raw_path),
            "population_record_path": self._display_path(self.config.population_path),
            "conflict_diagnosis_artifact_sha256": conflict_hashes,
            "artifact_sha256_excluding_provenance": artifact_sha,
            "ordering": "canonical_race_id ASC; horse_number ASC; horse_name ASC",
            "exclusive_create": True,
            "formal_cohort_generation_count": 1,
            "oos_evaluation_count": 0,
            "prediction_count": 0,
            "shadow_count": 0,
            "production_connection_count": 0,
            "feature_flag_connection_count": 0,
            "data_results_write_count": 0,
            "prohibited_field_use_count": 0,
        }

    @staticmethod
    def _render_report(manifest: dict[str, Any], reconciliation: dict[str, Any], derivation: dict[str, Any]) -> str:
        cross = derivation["crosscheck"]
        return "\n".join(
            [
                "# REG-009 Retrospective OOS Result Cohort V1",
                "",
                "- Status: COHORT_GENERATION_COMPLETE",
                "- Position: uniform result cohort only; no OOS evaluation",
                f"- Allowed dates: {', '.join(manifest['allowed_dates'])}",
                f"- Population: {manifest['all_race_count']} races ({manifest['included_race_count']} included / {manifest['excluded_race_count']} excluded)",
                f"- Included horses: {manifest['included_horse_count']}",
                f"- Reconciliation: {reconciliation['status']}",
                f"- Existing-result cross-check: {cross['status']} ({cross['race_count']} races / {cross['horse_count']} horses)",
                "- Inferred values: 0",
                "- Production / Prediction / Shadow / OOS evaluation: 0 / 0 / 0 / 0",
                "- data/results writes: 0",
                "",
            ]
        )

    @staticmethod
    def _display_path(path: Path) -> str:
        try:
            return path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            return path.resolve().as_posix()


def defaultdict_list(rows: Iterable[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row[key]), []).append(row)
    return grouped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="REG-009 retrospective OOS result cohort generator (read-only inputs, exclusive output).")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--validate-input-only", action="store_true", help="Validate authority and input structure without deriving or writing cohort results.")
    actions.add_argument("--generate", action="store_true", help="Generate the frozen seven-artifact cohort (future authorized operation only).")
    parser.add_argument("--output-root", type=Path, help="Exclusive-create output directory; required with --generate.")
    parser.add_argument("--generated-at", help="Frozen timestamp string; required with --generate for deterministic output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    generator = Reg009RetrospectiveOOSResultCohortGeneratorV1()
    if args.validate_input_only:
        print(json.dumps(generator.validate_inputs_only(), ensure_ascii=False, indent=2))
        return 0
    if args.output_root is None or not args.generated_at:
        raise SystemExit("--output-root and --generated-at are required with --generate")
    print(json.dumps(generator.generate(args.output_root, generated_at=args.generated_at), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
