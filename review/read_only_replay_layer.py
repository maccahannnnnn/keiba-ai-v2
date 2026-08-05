"""Read-only replay layer for Daily Review.

The layer reads saved review CSV artifacts and validates that the corresponding
analysis/result source files still exist. It does not call production adapters
or mutate learning repositories.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any


class ReplaySourceError(RuntimeError):
    """Raised when a saved replay source is unsafe to consume."""


class DailyReviewReadOnlyReplay:
    """Load saved Daily Review rows without rerunning TargetTrialAdapter."""

    VERSION_RE = re.compile(r"^(?P<prefix>race_summary|horse_review)_(?P<date>\d{8})(?:_v(?P<version>\d+))?\.csv$")
    SUMMARY_RE = re.compile(r"^daily_review_(?P<date>\d{8})_summary(?:_v(?P<version>\d+))?\.json$")

    def __init__(
        self,
        base_dir: Path | str,
        date: str,
        output_dir: Path | str,
        source_review_version: str | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.date = date
        self.output_dir = self.base_dir / Path(output_dir)
        self.analysis_dir = self.base_dir / "data" / "analysis"
        self.results_dir = self.base_dir / "data" / "results"
        self.source_review_version = source_review_version

    def load(self) -> dict[str, Any]:
        try:
            pair = self._select_source_pair()
        except ReplaySourceError as exc:
            return {
                "race_rows": [],
                "horse_rows": [],
                "incomplete": [{"race_id": self.date, "reason": str(exc)}],
                "duplicates": [],
                "replay_errors": [{"code": "REPLAY_SOURCE_SELECTION_FAILED", "message": str(exc)}],
                "source": self._source_metadata(None, None, "UNKNOWN_ORIGIN", "SOURCE_SELECTION_FAILED"),
            }

        race_csv = pair["race_csv"]
        horse_csv = pair["horse_csv"]
        source_origin = pair["source_evaluation_origin"]
        source_version = pair["source_review_version"]
        race_rows = [self._normalize_race_row(row) for row in self._read_csv(race_csv)]
        horse_rows = [self._normalize_horse_row(row) for row in self._read_csv(horse_csv)]
        replay_errors = self._validate_saved_pair(race_rows, horse_rows, source_version, source_origin)
        if replay_errors:
            return {
                "race_rows": [],
                "horse_rows": [],
                "incomplete": [{"race_id": self.date, "reason": ";".join(row["code"] for row in replay_errors)}],
                "duplicates": [],
                "replay_errors": replay_errors,
                "source": self._source_metadata(race_csv, horse_csv, source_origin, source_version),
            }

        incomplete, duplicates = self._source_file_status(race_rows)
        for row in race_rows:
            row["replay_status"] = "READ_ONLY_REPLAY"
            row["pre_race_saved_output_status"] = "NOT_FOUND"
            row["saved_review_source_status"] = "FOUND"
            row["source_evaluation_origin"] = source_origin
            row["source_review_version"] = source_version
        return {
            "race_rows": race_rows,
            "horse_rows": horse_rows,
            "incomplete": incomplete,
            "duplicates": duplicates,
            "replay_errors": [],
            "source": self._source_metadata(race_csv, horse_csv, source_origin, source_version),
        }

    def _select_source_pair(self) -> dict[str, Any]:
        race_versions = self._versioned_files("race_summary")
        horse_versions = self._versioned_files("horse_review")
        common_versions = sorted(set(race_versions) & set(horse_versions), key=self._version_sort_key)
        if self.source_review_version:
            version = self._canonical_version(self.source_review_version)
            if version not in race_versions or version not in horse_versions:
                raise ReplaySourceError(f"REPLAY_VERSION_MISSING:{version}")
            source_origin = self._source_origin(version)
            if source_origin == "READ_ONLY_REPLAY":
                raise ReplaySourceError(f"READ_ONLY_REPLAY_OUTPUT_CANNOT_BE_SOURCE:{version}")
            return {
                "source_review_version": version,
                "source_evaluation_origin": source_origin,
                "race_csv": race_versions[version],
                "horse_csv": horse_versions[version],
            }
        if not common_versions:
            raise ReplaySourceError(f"missing_saved_review:race_summary_{self.date}*.csv;horse_review_{self.date}*.csv")

        eligible = []
        for version in common_versions:
            origin = self._source_origin(version)
            if origin != "READ_ONLY_REPLAY":
                eligible.append((version, origin))
        if not eligible:
            raise ReplaySourceError("SOURCE_ORIGIN_UNDETERMINED_OR_REPLAY_ONLY")
        version, origin = sorted(eligible, key=lambda item: self._version_sort_key(item[0]), reverse=True)[0]
        return {
            "source_review_version": version,
            "source_evaluation_origin": origin,
            "race_csv": race_versions[version],
            "horse_csv": horse_versions[version],
        }

    def _versioned_files(self, prefix: str) -> dict[str, Path]:
        files: dict[str, Path] = {}
        for path in self.output_dir.glob(f"{prefix}_{self.date}*.csv"):
            if not path.is_file() or path.name.endswith("_readonly.csv"):
                continue
            match = self.VERSION_RE.match(path.name)
            if not match or match.group("prefix") != prefix or match.group("date") != self.date:
                continue
            version = self._canonical_version(match.group("version") or "base")
            files[version] = path
        return files

    def _canonical_version(self, version: str) -> str:
        value = str(version).strip().lower()
        if value.startswith("v"):
            value = value[1:]
        if value in {"", "base", "1"}:
            return "base"
        return f"v{int(value)}"

    def _version_sort_key(self, version: str) -> int:
        if version == "base":
            return 1
        return int(version[1:])

    def _source_origin(self, version: str) -> str:
        summary = self._summary_json_for_version(version)
        if summary is None:
            return "UNKNOWN_ORIGIN"
        replay_source = summary.get("replay_source")
        if isinstance(replay_source, dict) and replay_source.get("mode") == "READ_ONLY_REPLAY":
            return "READ_ONLY_REPLAY"
        validation = summary.get("validation")
        checks = validation.get("checks") if isinstance(validation, dict) else []
        if isinstance(checks, list) and any("CURRENT_CODE_REPLAY" in str(check) for check in checks):
            return "CURRENT_CODE_REPLAY"
        return "UNKNOWN_ORIGIN"

    def _summary_json_for_version(self, version: str) -> dict[str, Any] | None:
        suffix = "" if version == "base" else f"_{version}"
        path = self.output_dir / f"daily_review_{self.date}_summary{suffix}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _version_history(self) -> list[dict[str, Any]]:
        versions = sorted(
            set(self._versioned_files("race_summary")) | set(self._versioned_files("horse_review")),
            key=self._version_sort_key,
        )
        rows = []
        for version in versions:
            summary = self._summary_json_for_version(version)
            rows.append(
                {
                    "version": version,
                    "race_summary_exists": version in self._versioned_files("race_summary"),
                    "horse_review_exists": version in self._versioned_files("horse_review"),
                    "summary_exists": summary is not None,
                    "source_evaluation_origin": self._source_origin(version),
                }
            )
        return rows

    def _source_metadata(
        self,
        race_csv: Path | None,
        horse_csv: Path | None,
        source_origin: str,
        source_version: str,
    ) -> dict[str, Any]:
        return {
            "replay_mode": "READ_ONLY_REPLAY",
            "mode": "READ_ONLY_REPLAY",
            "source_evaluation_origin": source_origin,
            "source_review_version": source_version,
            "source_race_summary_path": str(race_csv) if race_csv else "",
            "source_horse_review_path": str(horse_csv) if horse_csv else "",
            "race_csv": str(race_csv) if race_csv else "",
            "horse_csv": str(horse_csv) if horse_csv else "",
            "pre_race_saved_output_status": "NOT_FOUND",
            "saved_review_source_status": "FOUND" if race_csv and horse_csv else "NOT_FOUND",
            "evaluator_reexecuted": "NO",
            "decision_recalculated": "NO",
            "buy_recalculated": "NO",
            "production_adapter_used": "NO",
            "result_data_used_as_evaluation_input": "NO",
            "source_race_summary_sha256": self._sha256(race_csv) if race_csv else "",
            "source_horse_review_sha256": self._sha256(horse_csv) if horse_csv else "",
            "generation_history": self._version_history(),
        }

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _read_csv(self, path: Path) -> list[dict[str, Any]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def _validate_saved_pair(
        self,
        race_rows: list[dict[str, Any]],
        horse_rows: list[dict[str, Any]],
        source_version: str,
        source_origin: str,
    ) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        race_ids = [str(row.get("race_id") or "") for row in race_rows]
        horse_race_ids = [str(row.get("race_id") or "") for row in horse_rows]
        if source_origin == "UNKNOWN_ORIGIN":
            errors.append({"code": "SOURCE_ORIGIN_UNDETERMINED", "source_review_version": source_version})
        if any(not race_id.startswith(f"race_{self.date}_") for race_id in race_ids + horse_race_ids):
            errors.append({"code": "TARGET_DATE_MISMATCH", "source_review_version": source_version})
        if len(race_ids) != len(set(race_ids)):
            errors.append({"code": "DUPLICATE_RACE_ID", "source_review_version": source_version})
        if set(race_ids) != set(horse_race_ids):
            errors.append({"code": "RACE_ID_SET_MISMATCH", "source_review_version": source_version})
        for race_id, rows in self._group(horse_rows, "race_id").items():
            seen: set[tuple[str, str]] = set()
            for row in rows:
                key = (str(row.get("horse_number") or ""), str(row.get("horse_name") or ""))
                if key in seen:
                    errors.append({"code": "DUPLICATE_HORSE", "race_id": race_id, "source_review_version": source_version})
                    break
                seen.add(key)
        for row in race_rows:
            buy_count = self._int_or_original(row.get("buy_count"))
            if isinstance(buy_count, int) and buy_count > 3:
                errors.append({"code": "BUY_COUNT_OVER_3", "race_id": row.get("race_id"), "source_review_version": source_version})
        return errors

    def _source_file_status(self, race_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        incomplete: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        for row in race_rows:
            race_id = str(row.get("race_id") or "")
            if not race_id:
                incomplete.append({"race_id": "MISSING", "reason": "missing:race_id"})
                continue
            suffix = race_id.replace("race_", "")
            paths = {
                "entry": self.analysis_dir / f"{race_id}_entry.csv",
                "horses": self.analysis_dir / f"{race_id}_horses.csv",
                "race_result": self.results_dir / f"{race_id}_result.csv",
                "horse_result": self.results_dir / f"horse_{suffix}_result.csv",
            }
            missing = [key for key, path in paths.items() if not path.exists()]
            if missing:
                incomplete.append({"race_id": race_id, "reason": "missing:" + ";".join(missing)})

        for pattern in [
            f"race_{self.date}_*_entry.csv",
            f"race_{self.date}_*_horses.csv",
            f"race_{self.date}_*_result.csv",
            f"horse_{self.date}_*_result.csv",
        ]:
            counts: dict[str, int] = {}
            for path in list(self.analysis_dir.glob(pattern)) + list(self.results_dir.glob(pattern)):
                counts[path.name] = counts.get(path.name, 0) + 1
            for name, count in counts.items():
                if count > 1:
                    duplicates.append({"file": name, "count": count})
        return incomplete, duplicates

    def _group(self, rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row.get(key) or ""), []).append(row)
        return grouped

    def _normalize_race_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        for key in [
            "self_check_conflict",
            "race_decision_sync_applied",
            "buy_v1_rc1_enabled",
            "top1_place",
            "top1_win",
            "winner_in_top3",
            "winner_in_top5",
        ]:
            if key in normalized:
                normalized[key] = self._bool(normalized.get(key))
        for key in [
            "entry_count",
            "analysis_horse_count",
            "result_horse_count",
            "joined_horse_count",
            "buy_count",
            "buy_top3_count",
            "buy_win_count",
            "top3_place_count",
            "top5_place_count",
        ]:
            if key in normalized:
                normalized[key] = self._int_or_original(normalized.get(key))
        return normalized

    def _normalize_horse_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        for key in ["actual_top3", "actual_top5", "race_decision_sync_applied"]:
            if key in normalized:
                normalized[key] = self._bool(normalized.get(key))
        if "ai_rank" in normalized:
            normalized["ai_rank"] = self._int_or_original(normalized.get("ai_rank"))
        return normalized

    def _bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes", "y"}

    def _int_or_original(self, value: Any) -> Any:
        try:
            if value in (None, ""):
                return value
            return int(float(str(value)))
        except (TypeError, ValueError):
            return value
