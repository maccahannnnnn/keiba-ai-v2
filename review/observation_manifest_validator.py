"""Strict validation for Full-Race Observation Manifest v1."""

from __future__ import annotations

import hashlib
from pathlib import Path

from review.observation_intake import POPULATION_SCHEMA_VERSION, SCHEMA_VERSION


class ObservationManifestValidator:
    REQUIRED = {
        "schema_version",
        "population_schema_version",
        "population_id",
        "population_type",
        "date",
        "racecourse",
        "prediction_linked",
        "baseline_membership",
        "production_evidence",
        "kpi_eligible",
        "source",
        "generated_at",
        "expected_race_count",
        "saved_race_count",
        "saved_horse_count",
        "prediction_linked_race_count",
        "observation_only_race_count",
        "result_importer_prediction_id",
        "result_importer_loaded_race_count",
        "completeness_status",
        "expected_race_ids",
        "missing_race_list",
        "abnormal_result_count",
        "races",
        "files",
    }
    FORBIDDEN_KEYS = {"decision", "buy", "ranking", "pre_race", "review"}

    def validate(self, manifest: dict, *, verify_files: bool = True) -> dict:
        errors: list[dict[str, str]] = []

        def add(code: str, detail: str = "") -> None:
            errors.append({"code": code, "detail": detail})

        if not isinstance(manifest, dict):
            return {"status": "FAIL", "reason_codes": ["MANIFEST_NOT_OBJECT"], "errors": [{"code": "MANIFEST_NOT_OBJECT", "detail": ""}]}

        missing_fields = sorted(self.REQUIRED.difference(manifest))
        if missing_fields:
            add("MISSING_REQUIRED_FIELDS", ",".join(missing_fields))
        if manifest.get("schema_version") != SCHEMA_VERSION:
            add("INVALID_SCHEMA_VERSION")
        if manifest.get("population_schema_version") != POPULATION_SCHEMA_VERSION:
            add("INVALID_POPULATION_SCHEMA_VERSION")
        expected_constants = {
            "population_type": "OBSERVATION_ONLY",
            "prediction_linked": False,
            "baseline_membership": "EXCLUDED",
            "production_evidence": "NO",
            "kpi_eligible": "NO",
            "result_importer_prediction_id": None,
        }
        for key, expected in expected_constants.items():
            if manifest.get(key) != expected or type(manifest.get(key)) is not type(expected):
                add("INVALID_OBSERVATION_GUARD", f"{key}={manifest.get(key)!r}")
        if manifest.get("source") not in {"INTERNAL_OFFICIAL_RESULT_CSV", "TARGET_FRONTIER_JV"}:
            add("INVALID_OBSERVATION_SOURCE", repr(manifest.get("source")))

        expected_ids = manifest.get("expected_race_ids") if isinstance(manifest.get("expected_race_ids"), list) else []
        races = manifest.get("races") if isinstance(manifest.get("races"), list) else []
        files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
        missing_races = manifest.get("missing_race_list") if isinstance(manifest.get("missing_race_list"), list) else []
        saved_races = [row for row in races if isinstance(row, dict) and row.get("saved") is True]

        if manifest.get("expected_race_count") != len(expected_ids) or len(expected_ids) != len(set(expected_ids)):
            add("EXPECTED_RACE_COUNT_MISMATCH")
        if len(races) != len(expected_ids) or {row.get("race_id") for row in races if isinstance(row, dict)} != set(expected_ids):
            add("RACE_SET_MISMATCH")
        if manifest.get("saved_race_count") != len(saved_races):
            add("SAVED_RACE_COUNT_MISMATCH")
        if manifest.get("saved_horse_count") != sum(int(row.get("horse_count", 0)) for row in saved_races):
            add("SAVED_HORSE_COUNT_MISMATCH")
        if manifest.get("prediction_linked_race_count") != sum(row.get("prediction_linked") is True for row in saved_races):
            add("PREDICTION_LINKED_COUNT_MISMATCH")
        if manifest.get("observation_only_race_count") != sum(row.get("observation_only") is True for row in saved_races):
            add("OBSERVATION_ONLY_COUNT_MISMATCH")
        if manifest.get("result_importer_loaded_race_count") != len(saved_races):
            add("IMPORTER_LOADED_COUNT_MISMATCH")
        if len(files) != len(saved_races) * 2:
            add("RESULT_FILE_COUNT_MISMATCH")

        if manifest.get("completeness_status") == "COMPLETE":
            if missing_races:
                add("COMPLETE_WITH_MISSING_RACE")
            if len(saved_races) != len(expected_ids):
                add("COMPLETE_WITH_RACE_COUNT_MISMATCH")
        elif manifest.get("completeness_status") != "INCOMPLETE":
            add("INVALID_COMPLETENESS_STATUS")
        elif not missing_races and len(saved_races) == len(expected_ids):
            add("INCOMPLETE_WITHOUT_DEFECT")

        if self._contains_forbidden_key(manifest):
            add("PREDICTION_OUTPUT_FIELD_PRESENT")

        seen_file_keys: set[tuple[str, str]] = set()
        for item in files:
            if not isinstance(item, dict):
                add("INVALID_FILE_RECORD")
                continue
            key = (str(item.get("race_id")), str(item.get("role")))
            if key in seen_file_keys:
                add("DUPLICATE_FILE_RECORD", repr(key))
            seen_file_keys.add(key)
            if item.get("role") not in {"RACE_RESULT", "HORSE_RESULT"}:
                add("INVALID_FILE_ROLE", repr(item.get("role")))
            if verify_files:
                path = Path(str(item.get("path", "")))
                if not path.is_file():
                    add("RESULT_FILE_MISSING", str(path))
                elif hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
                    add("FILE_SHA256_MISMATCH", str(path))

        reason_codes = list(dict.fromkeys(item["code"] for item in errors))
        return {
            "status": "PASS" if not errors else "FAIL",
            "reason_codes": reason_codes,
            "error_count": len(errors),
            "errors": errors,
            "expected_race_count": manifest.get("expected_race_count"),
            "saved_race_count": manifest.get("saved_race_count"),
            "file_count": len(files),
            "completeness_status": manifest.get("completeness_status"),
        }

    def _contains_forbidden_key(self, value: object) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in self.FORBIDDEN_KEYS:
                    return True
                if self._contains_forbidden_key(child):
                    return True
        elif isinstance(value, list):
            return any(self._contains_forbidden_key(child) for child in value)
        return False
