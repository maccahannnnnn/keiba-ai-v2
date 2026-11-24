"""Narrow canonical comparison for the 50 audited TARGET bulk conflicts.

This module is intentionally not a general CSV normalization framework.  It
only implements the comparison rules approved for TARGET Bulk Canonical
Comparison v1 and never writes either input side.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from evaluation.target_result_adapter import TargetResultAdapter
from review.target_bulk_result_intake import compare_known_missing_time_sentinels


BYTE_IDENTICAL = "BYTE_IDENTICAL"
CANONICALLY_EQUIVALENT = "CANONICALLY_EQUIVALENT"
SEMANTICALLY_EQUIVALENT_MISSING_TIME = "SEMANTICALLY_EQUIVALENT_MISSING_TIME"
ONE_SIDE_MISSING = "ONE_SIDE_MISSING"
BOTH_MISSING = "BOTH_MISSING"
FIELD_NOT_COMPARABLE = "FIELD_NOT_COMPARABLE"
TRUE_CONFLICT = "TRUE_CONFLICT"
UNDETERMINED = "UNDETERMINED"
HUMAN_VERIFIED_BULK_RESULT_CORRECT = "HUMAN_VERIFIED_BULK_RESULT_CORRECT"

RACE_FIELDS = (
    "年", "月", "日", "場所", "R", "芝・ダート", "距離", "天候", "馬場状態", "頭数",
)
HORSE_FIELDS = (
    "馬番", "馬名", "確定着順", "異常コード", "斤量", "騎手", "タイム", "着差",
    "PCI", "通過1", "通過2", "通過3", "通過4", "Ave-3F", "上り3F", "人気",
    "単勝オッズ", "体重", "増減", "調教師",
)
FIELD_NOT_COMPARABLE_FIELDS = frozenset({"着差", "単勝オッズ"})
APPROVED_WEIGHT_ALLOWANCE_SYMBOLS = frozenset({"▲", "☆", "◇", "★"})
WEIGHT_WITH_ALLOWANCE_PATTERN = re.compile(r"^([+-]?\d+(?:\.\d+)?)([^\d.])$")
CORE_TAXONOMY = (
    BYTE_IDENTICAL, CANONICALLY_EQUIVALENT, SEMANTICALLY_EQUIVALENT_MISSING_TIME,
    ONE_SIDE_MISSING, BOTH_MISSING, FIELD_NOT_COMPARABLE, TRUE_CONFLICT, UNDETERMINED,
)
HUMAN_FIELD_MAP = {
    "通過順1角": "通過1", "通過順2角": "通過2", "通過順3角": "通過3", "通過順4角": "通過4",
}


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def compare_field(
    field: str,
    existing_value: object,
    bulk_value: object,
    *,
    finish: object = None,
    abnormal_code: object = None,
) -> dict:
    """Compare one field using only the approved v1 rules."""

    existing = "" if existing_value is None else str(existing_value)
    bulk = "" if bulk_value is None else str(bulk_value)
    result = {"comparison_status": TRUE_CONFLICT, "missing_side": "", "reason": "different_values"}

    if field in FIELD_NOT_COMPARABLE_FIELDS:
        return {**result, "comparison_status": FIELD_NOT_COMPARABLE, "reason": "approved_field_semantics_or_schema_difference"}
    if existing == bulk:
        if _missing(existing):
            return {**result, "comparison_status": BOTH_MISSING, "reason": "both_missing"}
        return {**result, "comparison_status": BYTE_IDENTICAL, "reason": "literal_value_match"}
    if _missing(existing) and _missing(bulk):
        return {**result, "comparison_status": BOTH_MISSING, "reason": "both_missing"}
    if _missing(existing) or _missing(bulk):
        side = "EXISTING" if _missing(existing) else "BULK"
        return {**result, "comparison_status": ONE_SIDE_MISSING, "missing_side": side, "reason": f"one_side_missing_{side.lower()}"}

    sentinel = compare_known_missing_time_sentinels(field, existing, bulk, finish, abnormal_code)
    if sentinel == SEMANTICALLY_EQUIVALENT_MISSING_TIME:
        return {**result, "comparison_status": sentinel, "reason": "approved_phase_ab_missing_time_rule"}

    if field == "天候":
        if existing.strip() == bulk.strip():
            return {**result, "comparison_status": CANONICALLY_EQUIVALENT, "reason": "weather_outer_whitespace_only"}
        return result

    if field in {"芝・ダ", "芝・ダート"}:
        mapping = TargetResultAdapter.SURFACE_MAP
        if existing not in mapping or bulk not in mapping:
            return {**result, "comparison_status": UNDETERMINED, "reason": "unknown_surface_literal"}
        if mapping[existing] == mapping[bulk]:
            return {**result, "comparison_status": CANONICALLY_EQUIVALENT, "reason": "existing_surface_map"}
        return result

    if field == "斤量":
        existing_text = existing.strip()
        bulk_text = bulk.strip()
        allowance_match = WEIGHT_WITH_ALLOWANCE_PATTERN.fullmatch(existing_text)
        if allowance_match:
            numeric_text, symbol = allowance_match.groups()
            if symbol not in APPROVED_WEIGHT_ALLOWANCE_SYMBOLS:
                return {
                    **result, "comparison_status": UNDETERMINED, "reason": "unknown_weight_allowance_symbol",
                    "parsed_existing_weight": "", "parsed_bulk_weight": "", "allowance_symbol": symbol,
                }
            try:
                existing_number = Decimal(numeric_text)
                bulk_number = Decimal(bulk_text)
            except (InvalidOperation, ValueError):
                return {
                    **result, "comparison_status": UNDETERMINED, "reason": "weight_allowance_parse_failure",
                    "parsed_existing_weight": "", "parsed_bulk_weight": "", "allowance_symbol": symbol,
                }
            metadata = {
                "parsed_existing_weight": str(existing_number), "parsed_bulk_weight": str(bulk_number),
                "allowance_symbol": symbol,
            }
            if not existing_number.is_finite() or not bulk_number.is_finite():
                return {**result, "comparison_status": UNDETERMINED, "reason": "weight_allowance_non_finite", **metadata}
            if existing_number == bulk_number:
                return {
                    **result, "comparison_status": CANONICALLY_EQUIVALENT,
                    "reason": "approved_weight_allowance_symbol_exact_decimal_match", **metadata,
                }
            return {
                **result, "comparison_status": TRUE_CONFLICT,
                "reason": "approved_weight_allowance_symbol_numeric_mismatch", **metadata,
            }
        try:
            existing_number = Decimal(existing_text)
            bulk_number = Decimal(bulk_text)
        except (InvalidOperation, ValueError):
            return {**result, "comparison_status": UNDETERMINED, "reason": "weight_parse_failure"}
        if not existing_number.is_finite() or not bulk_number.is_finite():
            return {**result, "comparison_status": UNDETERMINED, "reason": "weight_non_finite"}
        if existing_number == bulk_number:
            return {**result, "comparison_status": CANONICALLY_EQUIVALENT, "reason": "exact_decimal_weight_match"}
        return result

    return result


def _read_csv(path: Path) -> list[dict[str, str]]:
    errors = []
    for encoding in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            with path.open("r", encoding=encoding, errors="strict", newline="") as handle:
                return list(csv.DictReader(handle))
        except (UnicodeDecodeError, csv.Error) as exc:
            errors.append(f"{encoding}:{exc}")
    raise RuntimeError(f"CSV_NOT_READABLE:{path}:{errors}")


def load_human_evidence(path: str | Path) -> dict[tuple[str, str, str], dict]:
    rows = _read_csv(Path(path))
    evidence = {}
    for row in rows:
        if (
            row.get("human_review_status") != "VERIFIED"
            or row.get("human_decision") != "BULK_RESULT_CORRECT"
            or row.get("verified_by") != "HUMAN"
            or row.get("source_type") != "JRA_OFFICIAL"
        ):
            raise RuntimeError("HUMAN_EVIDENCE_NOT_VERIFIED")
        field = HUMAN_FIELD_MAP.get(row.get("対象フィールド", ""))
        key = (row.get("race_id", ""), row.get("馬番", ""), field or "")
        if not all(key) or key in evidence:
            raise RuntimeError("HUMAN_EVIDENCE_KEY_INVALID")
        evidence[key] = row
    if len(evidence) != 5:
        raise RuntimeError("HUMAN_EVIDENCE_COUNT_NOT_FIVE")
    return evidence


class TargetBulkCanonicalReconciler:
    """Reconcile only the pre-audited 50 conflict files."""

    def __init__(self, human_evidence_path: str | Path):
        self.human_evidence_path = Path(human_evidence_path)
        self.human_evidence = load_human_evidence(self.human_evidence_path)

    def reconcile(self, conflict_list_path: str | Path) -> dict:
        conflict_rows = _read_csv(Path(conflict_list_path))
        if len(conflict_rows) != 50 or {row.get("provenance_status") for row in conflict_rows} != {"VERIFIED"}:
            raise RuntimeError("AUDITED_CONFLICT_SET_NOT_EXACTLY_FIFTY_VERIFIED_FILES")

        cells: list[dict] = []
        files: list[dict] = []
        evidence_used: set[tuple[str, str, str]] = set()
        for source in conflict_rows:
            official_path = Path(source["official_path"])
            bulk_path = Path(source["regenerated_split_path"])
            if not official_path.is_file() or not bulk_path.is_file():
                raise RuntimeError(f"RECONCILIATION_INPUT_MISSING:{source['race_id']}:{source['role']}")
            if sha256(official_path) != source["official_sha256"] or sha256(bulk_path) != source["split_sha256"]:
                raise RuntimeError(f"RECONCILIATION_INPUT_SHA_MISMATCH:{source['race_id']}:{source['role']}")

            if source["role"] == "RACE_RESULT":
                local = self._compare_race(source, _read_csv(official_path), _read_csv(bulk_path))
            elif source["role"] == "HORSE_RESULT":
                local, used = self._compare_horses(source, _read_csv(official_path), _read_csv(bulk_path))
                evidence_used.update(used)
            else:
                raise RuntimeError("UNKNOWN_CONFLICT_ROLE")
            cells.extend(local)

            status_counts = Counter(row["effective_status"] for row in local)
            unresolved = status_counts[TRUE_CONFLICT] + status_counts[UNDETERMINED]
            if source["official_sha256"] == source["split_sha256"]:
                file_status = "REUSE"
            elif unresolved:
                file_status = "OBSERVATION_HOLD"
            else:
                file_status = "OBSERVATION_ACCEPTABLE"
            files.append({
                "race_id": source["race_id"], "role": source["role"],
                "official_path": str(official_path), "bulk_split_path": str(bulk_path),
                "official_sha256": source["official_sha256"], "bulk_split_sha256": source["split_sha256"],
                "file_status": file_status, "conflict_stop": False,
                "cell_count": len(local), "effective_status_counts": dict(sorted(status_counts.items())),
            })

        if evidence_used != set(self.human_evidence):
            raise RuntimeError("HUMAN_EVIDENCE_NOT_USED_EXACTLY_ONCE")

        raw_counts = Counter(row["comparison_status"] for row in cells)
        counts = Counter(row["effective_status"] for row in cells)
        by_field = defaultdict(Counter)
        for row in cells:
            by_field[row["effective_status"]][row["field"]] += 1
        file_counts = Counter(row["file_status"] for row in files)
        hold_races = sorted({row["race_id"] for row in files if row["file_status"] == "OBSERVATION_HOLD"})
        race_statuses = []
        for race_id in sorted({row["race_id"] for row in files}):
            related = [row for row in files if row["race_id"] == race_id]
            if any(row["file_status"] == "OBSERVATION_HOLD" for row in related):
                status = "OBSERVATION_HOLD"
            elif all(row["file_status"] == "REUSE" for row in related):
                status = "REUSE"
            else:
                status = "OBSERVATION_ACCEPTABLE"
            race_statuses.append({"race_id": race_id, "race_status": status})
        race_counts = Counter(row["race_status"] for row in race_statuses)
        missing_direction = defaultdict(Counter)
        for row in cells:
            if row["effective_status"] == ONE_SIDE_MISSING:
                missing_direction[row["missing_side"]][row["field"]] += 1
        return {
            "version": "TARGET_BULK_CANONICAL_COMPARISON_V1",
            "scope": "PREAUDITED_50_CONFLICT_FILES_ONLY",
            "status": "PASS" if not hold_races else "PASS_WITH_OBSERVATION_HOLD",
            "file_count": len(files), "race_id_count": len({row["race_id"] for row in files}),
            "cell_count": len(cells),
            "raw_comparison_taxonomy_counts": {key: raw_counts.get(key, 0) for key in CORE_TAXONOMY},
            "taxonomy_counts": {key: counts.get(key, 0) for key in CORE_TAXONOMY},
            "human_verified_bulk_result_correct_count": counts.get(HUMAN_VERIFIED_BULK_RESULT_CORRECT, 0),
            "field_counts_by_taxonomy": {key: dict(sorted(value.items())) for key, value in sorted(by_field.items())},
            "one_side_missing_field_counts_by_side": {
                key: dict(sorted(value.items())) for key, value in sorted(missing_direction.items())
            },
            "file_status_counts": dict(sorted(file_counts.items())),
            "race_status_counts": dict(sorted(race_counts.items())),
            "observation_hold_race_ids": hold_races,
            "conflict_stop_count": 0,
            "human_evidence_count": len(self.human_evidence), "human_evidence_used_count": len(evidence_used),
            "race_statuses": race_statuses, "files": files, "cells": cells,
        }

    def _compare_race(self, source: dict, existing_rows: list[dict], bulk_rows: list[dict]) -> list[dict]:
        if len(existing_rows) != 1 or len(bulk_rows) != 1:
            raise RuntimeError("RACE_RESULT_ROW_COUNT_MISMATCH")
        existing, bulk = existing_rows[0], bulk_rows[0]
        rows = []
        for field in RACE_FIELDS:
            bulk_field = "芝・ダート" if field == "芝・ダート" else field
            rows.append(self._cell(source, "", "", field, existing.get(field), bulk.get(bulk_field)))
        return rows

    def _compare_horses(self, source: dict, existing_rows: list[dict], bulk_rows: list[dict]) -> tuple[list[dict], set]:
        existing = {row.get("馬番", ""): row for row in existing_rows}
        bulk = {row.get("馬番", ""): row for row in bulk_rows}
        if "" in existing or "" in bulk or set(existing) != set(bulk) or len(existing) != len(existing_rows) or len(bulk) != len(bulk_rows):
            raise RuntimeError(f"HORSE_KEY_SET_MISMATCH:{source['race_id']}")
        rows, used = [], set()
        for horse_number in sorted(existing, key=lambda value: int(value)):
            left, right = existing[horse_number], bulk[horse_number]
            for field in HORSE_FIELDS:
                cell = self._cell(
                    source, horse_number, left.get("馬名", ""), field, left.get(field), right.get(field),
                    finish=right.get("確定着順"), abnormal_code=right.get("異常コード"),
                )
                key = (source["race_id"], horse_number, field)
                evidence = self.human_evidence.get(key)
                if evidence:
                    if cell["comparison_status"] != TRUE_CONFLICT:
                        raise RuntimeError("HUMAN_EVIDENCE_CELL_NO_LONGER_CONFLICTS")
                    if str(cell["existing_value"]) != evidence["existing_value"] or str(cell["bulk_value"]) != evidence["bulk_value"]:
                        raise RuntimeError("HUMAN_EVIDENCE_VALUE_MISMATCH")
                    cell.update({
                        "effective_status": HUMAN_VERIFIED_BULK_RESULT_CORRECT,
                        "resolution_evidence": "JRA_OFFICIAL_HUMAN_VERIFIED",
                        "human_decision": "BULK_RESULT_CORRECT",
                    })
                    used.add(key)
                rows.append(cell)
        return rows, used

    @staticmethod
    def _cell(source: dict, horse_number: str, horse_name: str, field: str, existing: object, bulk: object, **context) -> dict:
        compared = compare_field(field, existing, bulk, **context)
        return {
            "race_id": source["race_id"], "role": source["role"], "horse_number": horse_number,
            "horse_name": horse_name, "field": field,
            "existing_value": "" if existing is None else str(existing),
            "bulk_value": "" if bulk is None else str(bulk),
            "parsed_existing_weight": "", "parsed_bulk_weight": "", "allowance_symbol": "",
            **compared, "effective_status": compared["comparison_status"],
            "resolution_evidence": "", "human_decision": "",
        }


def write_json(path: str | Path, payload: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
