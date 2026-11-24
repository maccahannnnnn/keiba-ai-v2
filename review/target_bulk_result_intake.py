"""Fail-closed intake for headerless TARGET Frontier JV bulk results.

All rows are decoded, schema-checked, sentinel-checked, and grouped before any
split file is written.  The formal ordered column list lives only in
``docs/target_bulk_result_schema_v1.json``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import OrderedDict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from evaluation.target_result_adapter import TargetResultAdapter
from review.observation_intake import POPULATION_SCHEMA_VERSION, SCHEMA_VERSION
from review.observation_manifest_validator import ObservationManifestValidator


FORMAL_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs" / "target_bulk_result_schema_v1.json"
FORMAL_SCHEMA_SHA_PATH = FORMAL_SCHEMA_PATH.with_suffix(".sha256")
PROVENANCE_VERSION = "TARGET_BULK_RESULT_PROVENANCE_V1"
SPLITTER_VERSION = "TARGET_BULK_RESULT_SPLITTER_V1"
MISSING_TIME_COMPARISON_STATUS = "SEMANTICALLY_EQUIVALENT_MISSING_TIME"
KNOWN_MISSING_TIME_SENTINELS = frozenset({"0.00.0", "------"})
STRICT_ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

RACE_RESULT_COLUMNS = ["年", "月", "日", "場所", "R", "略レース名", "芝・ダート", "距離", "天候", "馬場状態", "頭数"]
HORSE_RESULT_COLUMNS = [
    "確定着順", "異常コード", "ブリンカー", "枠番", "馬番",
    "馬印1", "馬印2", "馬印3", "馬印4", "馬名", "Ｃ", "性別", "年齢",
    "斤量", "騎手", "タイム", "着差", "PCI", "通過1", "通過2", "通過3",
    "通過4", "Ave-3F", "上り3F", "人気", "単勝オッズ", "体重", "増減",
    "多頭出し", "所属", "調教師", "賞金", "馬記号",
]


class TargetBulkIntakeError(RuntimeError):
    def __init__(self, reason_code: str, details: object = None):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.details = details


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_expected_sha(path: Path) -> str:
    text = path.read_text(encoding="ascii").strip()
    token = text.split()[0] if text else ""
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise TargetBulkIntakeError("INVALID_SCHEMA_SHA_RECORD")
    return token


def normalize_allowed_dates(allowed_dates: Sequence[date | str] | None) -> dict | None:
    """Normalize an explicit date whitelist without accepting ambiguous input."""

    if allowed_dates is None:
        return None
    original_arguments: list[str] = []
    normalized: list[str] = []
    for value in allowed_dates:
        if type(value) is date:
            text = value.isoformat()
        elif isinstance(value, str):
            text = value
            if not STRICT_ISO_DATE_PATTERN.fullmatch(text):
                raise TargetBulkIntakeError("INVALID_ALLOWED_DATE_FORMAT", {"value": value})
            try:
                date.fromisoformat(text)
            except ValueError as exc:
                raise TargetBulkIntakeError("INVALID_ALLOWED_DATE_FORMAT", {"value": value}) from exc
        else:
            raise TargetBulkIntakeError("INVALID_ALLOWED_DATE_FORMAT", {"value": repr(value)})
        original_arguments.append(text)
        normalized.append(text)
    if not normalized:
        raise TargetBulkIntakeError("ALLOWED_DATES_EMPTY")
    unique = sorted(set(normalized))
    return {
        "allowed_dates": unique,
        "allowed_dates_original_arguments": original_arguments,
        "duplicate_allowed_dates_detected": len(unique) != len(normalized),
    }


def load_formal_schema(
    schema_path: str | Path = FORMAL_SCHEMA_PATH,
    schema_sha_path: str | Path = FORMAL_SCHEMA_SHA_PATH,
    *,
    expected_schema_name: str = "TARGET_BULK_RESULT_SCHEMA_V1",
    expected_schema_version: str = "target_bulk_result_v1",
) -> tuple[dict, str]:
    path = Path(schema_path)
    sha_path = Path(schema_sha_path)
    if not path.is_file() or not sha_path.is_file():
        raise TargetBulkIntakeError("FORMAL_SCHEMA_NOT_FOUND")
    expected_sha = _read_expected_sha(sha_path)
    actual_sha = _sha256(path)
    if actual_sha != expected_sha:
        raise TargetBulkIntakeError("SCHEMA_SHA256_MISMATCH", {"expected": expected_sha, "actual": actual_sha})
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TargetBulkIntakeError("SCHEMA_NOT_READABLE", str(exc)) from exc
    if schema.get("schema_name") != expected_schema_name:
        raise TargetBulkIntakeError("SCHEMA_NAME_MISMATCH")
    if schema.get("schema_version") != expected_schema_version:
        raise TargetBulkIntakeError("SCHEMA_VERSION_MISMATCH")
    columns = schema.get("ordered_columns")
    if schema.get("column_count") != 50 or not isinstance(columns, list) or len(columns) != 50 or len(set(columns)) != 50:
        raise TargetBulkIntakeError("INVALID_FORMAL_ORDERED_COLUMNS")
    if schema.get("header_present") is not False or schema.get("record_unit") != "1 row = 1 horse result":
        raise TargetBulkIntakeError("INVALID_SCHEMA_STRUCTURE")
    return schema, actual_sha


def _is_int(value: str, low: int | None = None, high: int | None = None) -> bool:
    if not re.fullmatch(r"[+-]?\d+", value):
        return False
    number = int(value)
    return (low is None or number >= low) and (high is None or number <= high)


def _is_decimal(value: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value))


def compare_known_missing_time_sentinels(
    field: object,
    existing_value: object,
    bulk_value: object,
    finish: object,
    abnormal_code: object,
) -> str:
    """Classify only the approved abnormal-result missing-time literal pair.

    This helper does not rewrite either raw value and is intentionally not
    wired into byte-level reconciliation.  All four approved conditions must
    hold; every other comparison remains ``CONFLICT``.
    """

    if field != "タイム":
        return "CONFLICT"
    if not _is_zero_finish(finish) or not _is_nonzero_abnormal_code(abnormal_code):
        return "CONFLICT"
    if not isinstance(existing_value, str) or not isinstance(bulk_value, str):
        return "CONFLICT"
    if {existing_value, bulk_value} != KNOWN_MISSING_TIME_SENTINELS:
        return "CONFLICT"
    return MISSING_TIME_COMPARISON_STATUS


def _is_zero_finish(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == 0
    return isinstance(value, str) and value == "0"


def _is_nonzero_abnormal_code(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value != 0
    return isinstance(value, str) and bool(re.fullmatch(r"[+-]?\d+", value)) and int(value) != 0


class TargetBulkResultValidator:
    """Validate the entire raw file before exposing any grouped row."""

    def __init__(self, schema_path: str | Path = FORMAL_SCHEMA_PATH, schema_sha_path: str | Path = FORMAL_SCHEMA_SHA_PATH):
        self.schema_path = Path(schema_path)
        self.schema_sha_path = Path(schema_sha_path)
        self.target_adapter = TargetResultAdapter()

    def validate(
        self,
        raw_path: str | Path,
        *,
        expected_schema_name: str = "TARGET_BULK_RESULT_SCHEMA_V1",
        expected_schema_version: str = "target_bulk_result_v1",
    ) -> dict:
        path = Path(raw_path)
        if not path.is_file():
            raise TargetBulkIntakeError("RAW_FILE_NOT_FOUND")
        schema, schema_sha = load_formal_schema(
            self.schema_path,
            self.schema_sha_path,
            expected_schema_name=expected_schema_name,
            expected_schema_version=expected_schema_version,
        )
        try:
            with path.open("r", encoding=schema["encoding"], errors="strict", newline="") as handle:
                rows = list(csv.reader(handle))
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise TargetBulkIntakeError("RAW_DECODE_OR_CSV_FAILURE", str(exc)) from exc
        if not rows:
            raise TargetBulkIntakeError("RAW_FILE_EMPTY")
        empty_lines = [index for index, row in enumerate(rows, 1) if not row or all(not cell.strip() for cell in row)]
        if empty_lines:
            raise TargetBulkIntakeError("EMPTY_ROW_NOT_ALLOWED", empty_lines)
        bad_width = [{"line": index, "column_count": len(row)} for index, row in enumerate(rows, 1) if len(row) != 50]
        if bad_width:
            raise TargetBulkIntakeError("COLUMN_COUNT_MISMATCH", bad_width)
        if rows[0] == schema["ordered_columns"] or rows[0][0].strip() == "年":
            raise TargetBulkIntakeError("HEADER_PRESENT_NOT_ALLOWED")

        records = [dict(zip(schema["ordered_columns"], row)) for row in rows]
        sentinel_errors: list[dict] = []
        groups: OrderedDict[str, list[dict]] = OrderedDict()
        closed_keys: set[str] = set()
        active_key: str | None = None

        for line, record in enumerate(records, 1):
            clean = {key: str(value).strip() for key, value in record.items()}
            errors = self._sentinel_errors(clean)
            if errors:
                sentinel_errors.append({"line": line, "fields": errors})
                continue
            racecourse = self.target_adapter._normalize_racecourse(clean["場所"])
            if racecourse not in set(self.target_adapter.COURSE_MAP.values()):
                sentinel_errors.append({"line": line, "fields": ["場所"]})
                continue
            year = int(clean["年"])
            full_year = year if year >= 2000 else 2000 + year
            race_number = int(clean["レース番号"])
            race_id = self.target_adapter._race_id_from_parts(
                f"{full_year:04d}{int(clean['月']):02d}{int(clean['日']):02d}",
                racecourse,
                f"{race_number}R",
            )
            if active_key is not None and race_id != active_key:
                closed_keys.add(active_key)
            if race_id in closed_keys:
                raise TargetBulkIntakeError("RACE_KEY_REAPPEARED", {"line": line, "race_id": race_id})
            active_key = race_id
            groups.setdefault(race_id, []).append(record)

        if sentinel_errors:
            raise TargetBulkIntakeError("SENTINEL_VALIDATION_FAILED", sentinel_errors)

        for race_id, group in groups.items():
            horse_numbers = [int(str(row["馬番"]).strip()) for row in group]
            if len(horse_numbers) != len(set(horse_numbers)):
                raise TargetBulkIntakeError("DUPLICATE_HORSE_NUMBER", race_id)
            field_sizes = {int(str(row["頭数"]).strip()) for row in group}
            if len(field_sizes) != 1 or next(iter(field_sizes)) != len(group):
                raise TargetBulkIntakeError("FIELD_SIZE_ROW_COUNT_MISMATCH", {"race_id": race_id, "field_sizes": sorted(field_sizes), "rows": len(group)})
            stable_fields = ("年", "月", "日", "場所", "レース番号", "芝・ダ", "距離", "頭数")
            for field in stable_fields:
                if len({str(row[field]).strip() for row in group}) != 1:
                    raise TargetBulkIntakeError("RACE_GROUPING_INCONSISTENT", {"race_id": race_id, "field": field})

        return {
            "status": "PASS",
            "raw_path": str(path.resolve()),
            "source_sha256": _sha256(path),
            "schema_name": schema["schema_name"],
            "schema_version": schema["schema_version"],
            "schema_sha256": schema_sha,
            "encoding": schema["encoding"],
            "column_count": 50,
            "row_count": len(records),
            "race_count": len(groups),
            "date_count": len({race_id.split("_")[1] for race_id in groups}),
            "course_count": len({race_id.split("_")[2] for race_id in groups}),
            "race_ids": list(groups),
            "groups": groups,
        }

    def _sentinel_errors(self, row: dict[str, str]) -> list[str]:
        errors = []
        checks = {
            "年": _is_int(row["年"], 0, 9999) and len(row["年"]) in {2, 4},
            "月": _is_int(row["月"], 1, 12),
            "日": _is_int(row["日"], 1, 31),
            "場所": row["場所"] in self.target_adapter.COURSE_MAP,
            "レース番号": _is_int(row["レース番号"], 1, 12),
            "芝・ダ": row["芝・ダ"] in {"芝", "ダ", "ダート"},
            "距離": _is_int(row["距離"], 1, 9999),
            "頭数": _is_int(row["頭数"], 1, 99),
            "馬番": _is_int(row["馬番"], 1, 99),
            "確定着順": _is_int(row["確定着順"], 0, 99),
            "異常コード": _is_int(row["異常コード"], 0, 99),
            "タイムS": bool(re.fullmatch(r"\d+\.\d{2}\.\d", row["タイムS"])),
            "Ave-3F": not row["Ave-3F"] or _is_decimal(row["Ave-3F"]),
            "馬体重": not row["馬体重"] or _is_int(row["馬体重"], 1, 999),
            "増減": not row["増減"] or bool(re.fullmatch(r"[+-]?\d+", row["増減"])),
            "騎手コード": bool(re.fullmatch(r"\d{5}", row["騎手コード"])),
            "調教師コード": bool(re.fullmatch(r"\d{5}", row["調教師コード"])),
            "RPCI": not row["RPCI"] or _is_decimal(row["RPCI"]),
            "PCI": not row["PCI"] or _is_decimal(row["PCI"]),
        }
        for name, passed in checks.items():
            if not passed:
                errors.append(name)
        if checks["頭数"] and checks["馬番"] and int(row["馬番"]) > int(row["頭数"]):
            errors.append("馬番>頭数")
        return errors


class TargetBulkResultSplitter:
    """Stage deterministic split artifacts after successful full validation."""

    def __init__(self, validator: TargetBulkResultValidator | None = None):
        self.validator = validator or TargetBulkResultValidator()
        self.target_adapter = TargetResultAdapter()

    def stage(
        self,
        raw_path: str | Path,
        staging_root: str | Path,
        *,
        allowed_dates: Sequence[date | str] | None = None,
        **validation_options,
    ) -> dict:
        validated = self.validator.validate(raw_path, **validation_options)
        validated = self._filter_by_allowed_dates(validated, allowed_dates)
        return self._stage_validated(validated, staging_root)

    def stage_many(
        self,
        raw_paths: Sequence[str | Path],
        staging_root: str | Path,
        *,
        allowed_dates: Sequence[date | str] | None = None,
        **validation_options,
    ) -> dict:
        paths = [Path(path) for path in raw_paths]
        if not paths:
            raise TargetBulkIntakeError("RAW_SOURCE_LIST_EMPTY")
        validated_sources = [self.validator.validate(path, **validation_options) for path in paths]
        combined_groups: OrderedDict[str, list[dict]] = OrderedDict()
        duplicate_race_ids: list[str] = []
        for validated in validated_sources:
            for race_id, rows in validated["groups"].items():
                if race_id in combined_groups:
                    if combined_groups[race_id] != rows:
                        raise TargetBulkIntakeError(
                            "DUPLICATE_RACE_ID_ACROSS_SOURCES_CONFLICT",
                            {"race_id": race_id, "raw_source_paths": [str(path.resolve()) for path in paths]},
                        )
                    duplicate_race_ids.append(race_id)
                    continue
                combined_groups[race_id] = rows
        first = validated_sources[0]
        source_records = [
            {"path": item["raw_path"], "sha256": item["source_sha256"]}
            for item in validated_sources
        ]
        source_fingerprint = hashlib.sha256(
            json.dumps(source_records, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        combined = {
            **{key: value for key, value in first.items() if key != "groups"},
            "raw_path": first["raw_path"],
            "source_sha256": source_fingerprint,
            "row_count": sum(item["row_count"] for item in validated_sources),
            "race_count": len(combined_groups),
            "date_count": len({race_id.split("_")[1] for race_id in combined_groups}),
            "course_count": len({race_id.split("_")[2] for race_id in combined_groups}),
            "race_ids": list(combined_groups),
            "groups": combined_groups,
            "raw_source_paths": [item["raw_path"] for item in validated_sources],
            "raw_source_sha256": source_records,
            "duplicate_source_race_ids": sorted(set(duplicate_race_ids)),
        }
        combined = self._filter_by_allowed_dates(combined, allowed_dates)
        return self._stage_validated(combined, staging_root)

    def _stage_validated(self, validated: dict, staging_root: str | Path) -> dict:
        root = Path(staging_root)
        if root.exists() and any(root.iterdir()):
            raise TargetBulkIntakeError("STAGING_ROOT_NOT_EMPTY")
        root.mkdir(parents=True, exist_ok=True)
        split_files = []
        adapter_complete_count = 0
        for race_id, rows in validated["groups"].items():
            race_path = root / f"{race_id}_result.csv"
            horse_path = root / f"horse_{race_id.removeprefix('race_')}_result.csv"
            race_row, horse_rows = self._convert(rows)
            self._write_csv(race_path, RACE_RESULT_COLUMNS, [race_row])
            self._write_csv(horse_path, HORSE_RESULT_COLUMNS, horse_rows)
            loaded = self.target_adapter.load(race_path, horse_path)
            if loaded.get("race_id") != race_id or len(loaded.get("horse_results", [])) != len(rows) or loaded.get("warnings"):
                raise TargetBulkIntakeError("TARGET_RESULT_ADAPTER_COMPATIBILITY_FAILED", {"race_id": race_id, "warnings": loaded.get("warnings")})
            adapter_complete_count += 1
            for role, path in (("RACE_RESULT", race_path), ("HORSE_RESULT", horse_path)):
                split_files.append({"race_id": race_id, "role": role, "path": str(path.resolve()), "sha256": _sha256(path)})
        return {
            **{key: value for key, value in validated.items() if key != "groups"},
            "splitter_version": SPLITTER_VERSION,
            "staging_root": str(root.resolve()),
            "split_count": len(validated["groups"]),
            "split_file_count": len(split_files),
            "target_result_adapter_complete_count": adapter_complete_count,
            "split_files": split_files,
        }

    def _filter_by_allowed_dates(
        self,
        validated: dict,
        allowed_dates: Sequence[date | str] | None,
    ) -> dict:
        normalized = normalize_allowed_dates(allowed_dates)
        if normalized is None:
            return validated
        groups = validated["groups"]
        detected_dates = sorted({race_id.split("_")[1] for race_id in groups})
        requested_compact = {value.replace("-", "") for value in normalized["allowed_dates"]}
        missing_compact = sorted(requested_compact - set(detected_dates))
        if missing_compact:
            raise TargetBulkIntakeError(
                "ALLOWED_DATE_NOT_FOUND",
                {
                    "requested_allowed_dates": normalized["allowed_dates"],
                    "detected_input_dates": [self._iso_date(value) for value in detected_dates],
                    "missing_allowed_dates": [self._iso_date(value) for value in missing_compact],
                },
            )
        included: OrderedDict[str, list[dict]] = OrderedDict()
        excluded: OrderedDict[str, list[dict]] = OrderedDict()
        for race_id, rows in groups.items():
            target = included if race_id.split("_")[1] in requested_compact else excluded
            target[race_id] = rows
        included_ids, excluded_ids = list(included), list(excluded)
        audit = {
            **normalized,
            "date_filter_applied": True,
            "input_detected_dates": [self._iso_date(value) for value in detected_dates],
            "included_dates": sorted({self._iso_date(race_id.split("_")[1]) for race_id in included}),
            "excluded_dates": sorted({self._iso_date(race_id.split("_")[1]) for race_id in excluded}),
            "included_race_count": len(included),
            "excluded_race_count": len(excluded),
            "included_race_ids": included_ids,
            "excluded_race_ids": excluded_ids,
            "included_by_date": self._group_race_ids_by_date_and_venue(included_ids, reason=None),
            "excluded_by_date_reason": "DATE_NOT_IN_ALLOWED_DATES",
            "excluded_by_date": self._group_race_ids_by_date_and_venue(excluded_ids),
            "validation_scope": "FULL_RAW_INPUT",
            "processing_scope": "ALLOWED_DATES_ONLY",
        }
        return {
            **validated,
            "raw_row_count": validated["row_count"],
            "raw_race_count": validated["race_count"],
            "raw_date_count": validated["date_count"],
            "raw_course_count": validated["course_count"],
            "row_count": sum(len(rows) for rows in included.values()),
            "race_count": len(included),
            "date_count": len({race_id.split("_")[1] for race_id in included}),
            "course_count": len({race_id.split("_")[2] for race_id in included}),
            "race_ids": included_ids,
            "groups": included,
            "date_filter_audit": audit,
        }

    @staticmethod
    def _iso_date(compact: str) -> str:
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"

    @classmethod
    def _group_race_ids_by_date_and_venue(
        cls,
        race_ids: Sequence[str],
        *,
        reason: str | None = "DATE_NOT_IN_ALLOWED_DATES",
    ) -> list[dict]:
        grouped: OrderedDict[tuple[str, str], list[str]] = OrderedDict()
        for race_id in race_ids:
            _, compact, venue, _ = race_id.split("_")
            grouped.setdefault((compact, venue), []).append(race_id)
        rows = [
            {
                "date": cls._iso_date(compact),
                "venue": venue,
                "race_count": len(ids),
                "race_ids": ids,
            }
            for (compact, venue), ids in grouped.items()
        ]
        if reason is not None:
            for row in rows:
                row["reason"] = reason
        return rows

    def reconcile(self, staged: dict, official_root: str | Path) -> dict:
        official = Path(official_root)
        statuses = []
        for item in staged["split_files"]:
            staged_path = Path(item["path"])
            official_path = official / staged_path.name
            if not official_path.exists():
                status = "NEW"
            elif _sha256(official_path) == item["sha256"]:
                status = "REUSE"
            else:
                status = "CONFLICT_STOP"
            statuses.append({**item, "official_path": str(official_path.resolve()), "reconciliation_status": status})
        conflicts = [row for row in statuses if row["reconciliation_status"] == "CONFLICT_STOP"]
        return {"status": "STOP" if conflicts else "PASS", "conflict_count": len(conflicts), "files": statuses}

    def build_provenance(self, staged: dict, *, imported_at: str | None = None) -> dict:
        provenance = {
            "provenance_version": PROVENANCE_VERSION,
            "source_type": "TARGET_FRONTIER_JV",
            "raw_source_path": staged["raw_path"],
            "source_file_sha256": staged["source_sha256"],
            "imported_at": imported_at or datetime.now(timezone.utc).isoformat(),
            "schema_name": staged["schema_name"],
            "schema_version": staged["schema_version"],
            "schema_sha256": staged["schema_sha256"],
            "selected_column_count": staged["column_count"],
            "row_count": staged["row_count"],
            "split_count": staged["split_count"],
            "split_files": staged["split_files"],
            "formal_observation_registered": False,
        }
        if "raw_source_paths" in staged:
            provenance["raw_source_paths"] = staged["raw_source_paths"]
            provenance["raw_source_sha256"] = staged["raw_source_sha256"]
            provenance["duplicate_source_race_ids"] = staged["duplicate_source_race_ids"]
        if "date_filter_audit" in staged:
            provenance.update(staged["date_filter_audit"])
            provenance["raw_source_paths"] = staged.get("raw_source_paths", [staged["raw_path"]])
            provenance["raw_source_sha256"] = staged.get(
                "raw_source_sha256",
                [{"path": staged["raw_path"], "sha256": staged["source_sha256"]}],
            )
        return provenance

    def build_observation_manifests(
        self,
        staged: dict,
        *,
        prediction_linked_race_ids: Iterable[str] = (),
        generated_at: str | None = None,
    ) -> list[dict]:
        linked = set(prediction_linked_race_ids)
        grouped: OrderedDict[tuple[str, str], list[int]] = OrderedDict()
        for race_id in staged["race_ids"]:
            _, date, course, race_number = race_id.split("_")
            grouped.setdefault((date, course), []).append(int(race_number[:-1]))
        manifests = []
        for (date, course), race_numbers in grouped.items():
            local_linked = [race_id for race_id in linked if race_id.startswith(f"race_{date}_{course}_")]
            race_ids = [f"race_{date}_{course}_{number}R" for number in sorted(race_numbers)]
            race_rows = []
            files = []
            saved_horses = 0
            abnormal = 0
            for race_id in race_ids:
                related = [item for item in staged["split_files"] if item["race_id"] == race_id]
                horse_file = next(item for item in related if item["role"] == "HORSE_RESULT")
                with Path(horse_file["path"]).open("r", encoding="cp932", newline="") as handle:
                    horse_rows = list(csv.DictReader(handle))
                race_abnormal = sum(
                    not _is_int(str(row.get("確定着順", "")).strip(), 1, 99)
                    or str(row.get("異常コード", "")).strip() not in {"", "0", "0.0"}
                    for row in horse_rows
                )
                prediction_linked = race_id in local_linked
                race_rows.append({
                    "race_id": race_id, "race_number": race_id.rsplit("_", 1)[1], "saved": True,
                    "horse_count": len(horse_rows), "abnormal_result_count": race_abnormal,
                    "prediction_linked": prediction_linked, "observation_only": not prediction_linked,
                })
                saved_horses += len(horse_rows)
                abnormal += race_abnormal
                files.extend(related)
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "population_schema_version": POPULATION_SCHEMA_VERSION,
                "population_id": f"OBS_{date}_{course.upper()}_ALL",
                "population_type": "OBSERVATION_ONLY",
                "date": date,
                "racecourse": course,
                "prediction_linked": False,
                "baseline_membership": "EXCLUDED",
                "production_evidence": "NO",
                "kpi_eligible": "NO",
                "source": "INTERNAL_OFFICIAL_RESULT_CSV",
                "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
                "expected_race_count": len(race_ids),
                "saved_race_count": len(race_ids),
                "saved_horse_count": saved_horses,
                "prediction_linked_race_count": len(local_linked),
                "observation_only_race_count": len(race_ids) - len(local_linked),
                "result_importer_prediction_id": None,
                "result_importer_loaded_race_count": len(race_ids),
                "completeness_status": "COMPLETE",
                "expected_race_ids": race_ids,
                "missing_race_list": [],
                "abnormal_result_count": abnormal,
                "races": race_rows,
                "files": files,
                "target_bulk_source_sha256": staged["source_sha256"],
                "target_bulk_schema_sha256": staged["schema_sha256"],
            }
            validation = ObservationManifestValidator().validate(manifest)
            if validation["status"] != "PASS":
                raise TargetBulkIntakeError("OBSERVATION_MANIFEST_VALIDATION_FAILED", validation)
            manifests.append(manifest)
        return manifests

    def _convert(self, rows: list[dict]) -> tuple[dict, list[dict]]:
        first = {key: str(value).strip() for key, value in rows[0].items()}
        year = int(first["年"])
        full_year = year if year >= 2000 else 2000 + year
        race = {
            "年": full_year, "月": first["月"].zfill(2), "日": first["日"].zfill(2),
            "場所": first["場所"], "R": int(first["レース番号"]), "略レース名": first["略レース名"],
            "芝・ダート": first["芝・ダ"], "距離": first["距離"], "天候": first["天候"],
            "馬場状態": first["馬場状態"], "頭数": first["頭数"],
        }
        horses = []
        for raw in rows:
            row = {key: str(value).strip() for key, value in raw.items()}
            horses.append({
                "確定着順": row["確定着順"], "異常コード": row["異常コード"], "ブリンカー": "",
                "枠番": "", "馬番": row["馬番"],
                "馬印1": "", "馬印2": "", "馬印3": "", "馬印4": "", "馬名": row["馬名"], "Ｃ": "",
                "性別": row["性別"], "年齢": row["年齢"], "斤量": row["斤量"], "騎手": row["騎手"],
                "タイム": row["タイムS"], "着差": row["着差タイム"], "PCI": row["PCI"],
                "通過1": row["通過順1角"], "通過2": row["通過順2角"], "通過3": row["通過順3角"], "通過4": row["通過順4角"],
                "Ave-3F": row["Ave-3F"], "上り3F": row["上がり3Fタイム"], "人気": row["人気"], "単勝オッズ": "",
                "体重": row["馬体重"], "増減": row["増減"], "多頭出し": "", "所属": row["所属"],
                "調教師": row["調教師"], "賞金": row["賞金"], "馬記号": "",
            })
        return race, horses

    def _write_csv(self, path: Path, fieldnames: list[str], rows: list[dict]) -> None:
        with path.open("w", encoding="cp932", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
