"""Read-only metadata guardrail for Learning/Human Review candidates.

This validator detects active candidates whose race metadata is unusable for
evidence-based review. It never rewrites candidate JSON, legacy records, or
production artifacts.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HUMAN_REVIEW_DB = ROOT / "learning" / "candidate_review_status.json"
DEFAULT_CURRENT_CANDIDATES = ROOT / "reports" / "improvement_candidates" / "improvement_candidates.json"
DEFAULT_REPORT_MD = ROOT / "reports" / "learning_candidate_metadata_validation.md"
DEFAULT_REPORT_JSON = ROOT / "reports" / "learning_candidate_metadata_validation.json"
UNKNOWN_VALUES = {"", "unknown", "UNKNOWN", "MISSING", "LEGACY_UNKNOWN", None}


class LearningCandidateMetadataValidator:
    """Validate candidate metadata evidence without mutating source data."""

    def __init__(
        self,
        human_review_db: Path | str = DEFAULT_HUMAN_REVIEW_DB,
        current_candidates_path: Path | str = DEFAULT_CURRENT_CANDIDATES,
        report_md: Path | str = DEFAULT_REPORT_MD,
        report_json: Path | str = DEFAULT_REPORT_JSON,
    ) -> None:
        self.human_review_db = Path(human_review_db)
        self.current_candidates_path = Path(current_candidates_path)
        self.report_md = Path(report_md)
        self.report_json = Path(report_json)

    def validate(self, write_reports: bool = True) -> dict[str, Any]:
        generated_at = datetime.now().isoformat(timespec="seconds")
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        info: list[dict[str, Any]] = []

        human_review = self._read_json(self.human_review_db, errors, "human_review_db")
        current_candidates = self._read_json(self.current_candidates_path, errors, "current_candidates")
        records = self._records(human_review)
        current_ids = {
            row.get("candidate_id")
            for row in self._list(current_candidates.get("candidates"))
            if row.get("candidate_id")
        }

        rows: list[dict[str, Any]] = []
        for record in records:
            row = self._candidate_row(record, current_ids)
            rows.append(row)
            self._classify(row, errors, warnings, info)

        class_counts = Counter(row["lifecycle_class"] for row in rows)
        active_rows = [row for row in rows if row["is_active"]]
        archived_rows = [row for row in rows if not row["is_active"]]
        summary = {
            "generated_at": generated_at,
            "status": "ERROR" if errors else ("WARNING" if warnings else "PASS"),
            "human_review_records": len(records),
            "current_candidate_ids": len(current_ids),
            "active_candidate_count": len(active_rows),
            "archived_candidate_count": len(archived_rows),
            "active_metadata_all_unknown_count": sum(1 for row in active_rows if row["all_unknown"]),
            "active_metadata_partial_unknown_count": sum(
                1 for row in active_rows if row["unknown_field_count"] in (1, 2)
            ),
            "legacy_archived_unknown_count": sum(
                1 for row in archived_rows if row["all_unknown"] or row["unknown_field_count"] > 0
            ),
            "classification_counts": dict(class_counts),
            "target_hr_381e8e38d41f": next(
                (row for row in rows if row.get("candidate_id") == "hr_381e8e38d41f"),
                None,
            ),
            "errors": errors,
            "warnings": warnings,
            "info": info,
            "candidates": rows,
        }
        if write_reports:
            self._write_reports(summary)
        return summary

    def _candidate_row(self, record: dict[str, Any], current_ids: set[str]) -> dict[str, Any]:
        snapshot = record.get("ranking_snapshot") if isinstance(record.get("ranking_snapshot"), dict) else {}
        candidate_id = record.get("candidate_id")
        ranking_active = bool(record.get("ranking_active")) or candidate_id in current_ids
        occurrences = snapshot.get("occurrences", record.get("occurrences", 0))
        occurrence_valid = isinstance(occurrences, int) and occurrences >= 0
        distances = self._counter_items(snapshot.get("distances"))
        surfaces = self._counter_items(snapshot.get("surfaces"))
        track_conditions = self._counter_items(snapshot.get("track_conditions"))
        lifecycle_class = self._lifecycle_class(ranking_active, snapshot, record)
        unknown_fields = {
            "distance": self._all_unknown(distances),
            "surface": self._all_unknown(surfaces),
            "track_condition": self._all_unknown(track_conditions),
        }
        return {
            "candidate_id": candidate_id or "MISSING",
            "candidate_name": record.get("candidate_name", "MISSING"),
            "candidate_type": record.get("candidate_type", "MISSING"),
            "ranking_active": ranking_active,
            "archive_reason": record.get("archive_reason", ""),
            "occurrences": occurrences,
            "occurrence_valid": occurrence_valid,
            "race_count": snapshot.get("race_count", record.get("race_count", "MISSING")),
            "distances": distances,
            "surfaces": surfaces,
            "track_conditions": track_conditions,
            "candidate_generation_version": snapshot.get("candidate_generation_version", "MISSING"),
            "priority": record.get("priority", "MISSING"),
            "status": record.get("status", "MISSING"),
            "status_source": record.get("status_source", "LEGACY_UNKNOWN"),
            "is_active": ranking_active,
            "lifecycle_class": lifecycle_class,
            "unknown_fields": unknown_fields,
            "unknown_field_count": sum(1 for value in unknown_fields.values() if value),
            "all_unknown": all(unknown_fields.values()),
            "distance_known_rate": self._known_rate(distances),
            "surface_known_rate": self._known_rate(surfaces),
            "track_condition_known_rate": self._known_rate(track_conditions),
        }

    def _classify(
        self,
        row: dict[str, Any],
        errors: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        info: list[dict[str, Any]],
    ) -> None:
        base = {"candidate_id": row["candidate_id"], "candidate_name": row["candidate_name"]}
        if row["candidate_id"] == "MISSING":
            errors.append({**base, "code": "MISSING_CANDIDATE_ID"})
        if not row["occurrence_valid"]:
            errors.append({**base, "code": "INVALID_OCCURRENCES", "occurrences": row["occurrences"]})
        has_positive_occurrences = row["occurrence_valid"] and row["occurrences"] > 0
        if row["is_active"] and has_positive_occurrences and row["all_unknown"]:
            warnings.append({**base, "code": "ACTIVE_METADATA_ALL_UNKNOWN"})
        elif row["is_active"] and has_positive_occurrences and row["unknown_field_count"] >= 2:
            warnings.append({**base, "code": "ACTIVE_METADATA_MULTI_UNKNOWN", "fields": row["unknown_fields"]})
        elif not row["is_active"] and row["unknown_field_count"] > 0:
            info.append({**base, "code": "LEGACY_OR_ARCHIVED_METADATA_UNKNOWN"})

    def _lifecycle_class(self, active: bool, snapshot: dict[str, Any], record: dict[str, Any]) -> str:
        version = str(snapshot.get("candidate_generation_version") or "")
        has_archive = bool(record.get("archive_reason")) or not active
        legacy = not version or version == "MISSING" or str(record.get("status_source", "")).startswith("LEGACY")
        if active and legacy:
            return "ACTIVE_LEGACY"
        if active:
            return "ACTIVE_CURRENT"
        if has_archive and legacy:
            return "ARCHIVED_LEGACY"
        return "ARCHIVED_CURRENT"

    def _counter_items(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [
                {"value": item.get("value", "MISSING"), "count": item.get("count", 0)}
                for item in value
                if isinstance(item, dict)
            ]
        return [{"value": "UNDETERMINED", "count": 0}]

    def _all_unknown(self, items: list[dict[str, Any]]) -> bool:
        return bool(items) and all(item.get("value") in UNKNOWN_VALUES for item in items)

    def _known_rate(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        total = sum(int(item.get("count", 0) or 0) for item in items)
        if total <= 0:
            return {"known": 0, "total": 0, "rate": "UNDETERMINED"}
        known = sum(
            int(item.get("count", 0) or 0)
            for item in items
            if item.get("value") not in UNKNOWN_VALUES
        )
        return {"known": known, "total": total, "rate": round(known / total, 4)}

    def _read_json(self, path: Path, errors: list[dict[str, Any]], label: str) -> dict[str, Any]:
        try:
            if not path.exists():
                errors.append({"code": "MISSING_INPUT", "label": label, "path": str(path)})
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                errors.append({"code": "INVALID_JSON_ROOT", "label": label, "path": str(path)})
                return {}
            return data
        except Exception as exc:  # diagnostic only
            errors.append({"code": "READ_FAILED", "label": label, "path": str(path), "error": str(exc)})
            return {}

    def _records(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        return self._list(data.get("records"))

    def _list(self, value: Any) -> list[dict[str, Any]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def _write_reports(self, summary: dict[str, Any]) -> None:
        json_path = self._resolve_output_path(self.report_json)
        md_path = self._resolve_output_path(self.report_md)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            "# Learning Candidate Metadata Validation",
            "",
            f"- Status: {summary['status']}",
            f"- Human Review records: {summary['human_review_records']}",
            f"- Active candidates: {summary['active_candidate_count']}",
            f"- Archived candidates: {summary['archived_candidate_count']}",
            f"- Active all-unknown: {summary['active_metadata_all_unknown_count']}",
            f"- Active partial-unknown: {summary['active_metadata_partial_unknown_count']}",
            f"- Legacy archived unknown: {summary['legacy_archived_unknown_count']}",
            f"- Errors: {len(summary['errors'])}",
            f"- Warnings: {len(summary['warnings'])}",
            f"- Info: {len(summary['info'])}",
            "",
            "## Target hr_381e8e38d41f",
            "",
            "```json",
            json.dumps(summary["target_hr_381e8e38d41f"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Warnings",
            "",
            "```json",
            json.dumps(summary["warnings"], ensure_ascii=False, indent=2),
            "```",
        ]
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _resolve_output_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return path.with_name(f"{path.stem}_{stamp}{path.suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Learning Candidate metadata evidence.")
    parser.add_argument("--human-review-db", default=str(DEFAULT_HUMAN_REVIEW_DB))
    parser.add_argument("--current-candidates", default=str(DEFAULT_CURRENT_CANDIDATES))
    parser.add_argument("--report-md", default=str(DEFAULT_REPORT_MD))
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON))
    args = parser.parse_args()
    result = LearningCandidateMetadataValidator(
        human_review_db=args.human_review_db,
        current_candidates_path=args.current_candidates,
        report_md=args.report_md,
        report_json=args.report_json,
    ).validate(write_reports=True)
    print(json.dumps({k: v for k, v in result.items() if k != "candidates"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
