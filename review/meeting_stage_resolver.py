"""Retrospective meeting-stage resolver for MeetingBias review evidence.

The resolver uses repository-local race dates only. It does not call
Production adapters, does not infer from external calendars, and returns
UNKNOWN when there are too few observed dates to make a safe relative split.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MeetingStageResolution:
    race_id: str
    race_date: str
    racecourse: str
    meeting_sequence_id: str
    meeting_day_index: int | None
    meeting_week: int | None
    meeting_stage: str
    meeting_stage_source: str
    derivation_method: str
    derivation_confidence: str
    shadow_testable: bool
    source_files: list[str]
    source_sha256: str
    resolver_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "race_id": self.race_id,
            "race_date": self.race_date,
            "racecourse": self.racecourse,
            "meeting_sequence_id": self.meeting_sequence_id,
            "meeting_day_index": self.meeting_day_index,
            "meeting_week": self.meeting_week,
            "meeting_stage": self.meeting_stage,
            "meeting_stage_source": self.meeting_stage_source,
            "derivation_method": self.derivation_method,
            "derivation_confidence": self.derivation_confidence,
            "shadow_testable": self.shadow_testable,
            "source_files": ";".join(self.source_files),
            "source_sha256": self.source_sha256,
            "resolver_version": self.resolver_version,
        }


class MeetingStageResolver:
    """Resolve OPENING/MIDDLE/CLOSING from observed repository race dates."""

    VERSION = "meeting_stage_resolver_v1"
    MIN_OBSERVED_DAYS = 3
    SEQUENCE_GAP_DAYS = 14
    RACE_ID_RE = re.compile(r"race_(?P<date>\d{8})_(?P<course>[^_]+)_(?P<race_no>\d+R)")

    def __init__(self, root: Path | str = Path(".")) -> None:
        self.root = Path(root)

    def resolve(self, race_ids: list[str]) -> dict[str, MeetingStageResolution]:
        calendar = self._observed_calendar()
        return {race_id: self.resolve_one(race_id, calendar) for race_id in race_ids}

    def resolve_one(
        self,
        race_id: str,
        calendar: dict[str, list[dict[str, Any]]] | None = None,
    ) -> MeetingStageResolution:
        parsed = self._parse_race_id(race_id)
        if not parsed:
            return self._unknown(race_id, "", "", "RACE_ID_UNPARSEABLE")
        race_date, racecourse = parsed["race_date"], parsed["racecourse"]
        calendar = calendar if calendar is not None else self._observed_calendar()
        course_days = sorted(calendar.get(racecourse, []), key=lambda item: item.get("race_date", ""))
        sequence = self._sequence_for_date(course_days, race_date)
        if not sequence or len(sequence) < self.MIN_OBSERVED_DAYS:
            return self._unknown(race_id, race_date, racecourse, "INSUFFICIENT_OBSERVED_DAYS", course_days)

        dates = [item["race_date"] for item in sequence]
        if race_date not in dates:
            return self._unknown(race_id, race_date, racecourse, "DATE_NOT_IN_OBSERVED_SEQUENCE", sequence)

        index = dates.index(race_date) + 1
        stage = self._stage_from_index(index, len(dates))
        sequence_id = f"{racecourse}_{dates[0]}_{dates[-1]}"
        source_files = sorted({file for item in sequence for file in item.get("source_files", [])})
        return MeetingStageResolution(
            race_id=race_id,
            race_date=race_date,
            racecourse=racecourse,
            meeting_sequence_id=sequence_id,
            meeting_day_index=index,
            meeting_week=((index - 1) // 2) + 1,
            meeting_stage=stage,
            meeting_stage_source="RELATIVE_OBSERVED_SEQUENCE",
            derivation_method="relative_observed_sequence_thirds",
            derivation_confidence="MEDIUM" if len(dates) >= 4 else "LOW",
            shadow_testable=True,
            source_files=source_files,
            source_sha256=self._source_hash(source_files),
            resolver_version=self.VERSION,
        )

    def _stage_from_index(self, index: int, total: int) -> str:
        first_boundary = total / 3
        second_boundary = (total * 2) / 3
        if index <= first_boundary:
            return "OPENING"
        if index <= second_boundary:
            return "MIDDLE"
        return "CLOSING"

    def _observed_calendar(self) -> dict[str, list[dict[str, Any]]]:
        by_course: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for folder in (self.root / "data" / "results", self.root / "data" / "analysis"):
            if not folder.exists():
                continue
            for path in folder.rglob("*.csv"):
                parsed = self._parse_race_id(path.name)
                if not parsed:
                    continue
                by_course[parsed["racecourse"]][parsed["race_date"]].add(str(path))
        return {
            course: [
                {"race_date": date, "source_files": sorted(files)}
                for date, files in sorted(date_map.items())
            ]
            for course, date_map in by_course.items()
        }

    def _sequence_for_date(self, course_days: list[dict[str, Any]], race_date: str) -> list[dict[str, Any]]:
        if not course_days:
            return []
        sequences: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        previous: datetime | None = None
        for item in course_days:
            current_date = self._date(item["race_date"])
            if previous is not None and (current_date - previous).days > self.SEQUENCE_GAP_DAYS:
                sequences.append(current)
                current = []
            current.append(item)
            previous = current_date
        if current:
            sequences.append(current)
        for sequence in sequences:
            if race_date in {item["race_date"] for item in sequence}:
                return sequence
        return []

    def _parse_race_id(self, value: str) -> dict[str, str] | None:
        match = self.RACE_ID_RE.search(str(value or ""))
        if not match:
            return None
        return {
            "race_date": match.group("date"),
            "racecourse": match.group("course"),
            "race_no": match.group("race_no"),
        }

    def _unknown(
        self,
        race_id: str,
        race_date: str,
        racecourse: str,
        reason: str,
        source_days: list[dict[str, Any]] | None = None,
    ) -> MeetingStageResolution:
        source_files = sorted({file for item in source_days or [] for file in item.get("source_files", [])})
        return MeetingStageResolution(
            race_id=race_id,
            race_date=race_date,
            racecourse=racecourse,
            meeting_sequence_id="UNKNOWN",
            meeting_day_index=None,
            meeting_week=None,
            meeting_stage="UNKNOWN",
            meeting_stage_source="UNKNOWN",
            derivation_method=reason,
            derivation_confidence="UNKNOWN",
            shadow_testable=False,
            source_files=source_files,
            source_sha256=self._source_hash(source_files),
            resolver_version=self.VERSION,
        )

    def _date(self, value: str) -> datetime:
        return datetime.strptime(value, "%Y%m%d")

    def _source_hash(self, files: list[str]) -> str:
        digest = hashlib.sha256()
        for file_name in sorted(files):
            path = Path(file_name)
            digest.update(str(path).replace("\\", "/").encode("utf-8"))
            if path.exists() and path.is_file():
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def summarize(self, rows: list[MeetingStageResolution]) -> dict[str, Any]:
        total = len(rows)
        known = sum(1 for row in rows if row.meeting_stage != "UNKNOWN")
        stage_counts = Counter(row.meeting_stage for row in rows)
        comparable_stage_count = len(
            {
                row.meeting_stage
                for row in rows
                if row.meeting_stage not in {"UNKNOWN", "", None}
            }
        )
        racecourse_count = len({row.racecourse for row in rows if row.racecourse})
        readiness = self.diagnostic_readiness(rows)
        return {
            "total": total,
            "known": known,
            "unknown": total - known,
            "unknown_rate": round((total - known) / total, 4) if total else 0,
            "shadow_testable": readiness.get("level"),
            "stage_counts": dict(stage_counts),
            "racecourse_counts": dict(Counter(row.racecourse for row in rows)),
            "source_counts": dict(Counter(row.meeting_stage_source for row in rows)),
            "confidence_counts": dict(Counter(row.derivation_confidence for row in rows)),
            "comparable_stage_count": comparable_stage_count,
            "target_meeting_count": racecourse_count,
            "diagnostic_readiness": readiness,
        }

    def diagnostic_readiness(self, rows: list[MeetingStageResolution]) -> dict[str, Any]:
        """Return cohort-level diagnostic readiness without scoring effects."""

        total = len(rows)
        known = sum(1 for row in rows if row.meeting_stage != "UNKNOWN")
        stages = {
            row.meeting_stage
            for row in rows
            if row.meeting_stage not in {"UNKNOWN", "", None}
        }
        racecourses = {row.racecourse for row in rows if row.racecourse}
        missing_conditions: list[str] = []
        if total == 0:
            missing_conditions.append("NO_RESOLUTION_ROWS")
        if known == 0:
            missing_conditions.append("NO_STAGE_RESOLVED")
        if known < total:
            missing_conditions.append("UNRESOLVED_STAGE_ROWS_PRESENT")
        if known < 15:
            missing_conditions.append("RESOLVED_STAGE_ROWS_BELOW_15")
        if len(stages) < 2:
            missing_conditions.append("COMPARABLE_STAGE_COUNT_BELOW_2")
        if len(racecourses) < 1:
            missing_conditions.append("NO_TARGET_MEETING")

        if known == 0:
            level = "STAGE_RESOLVED"
            reason = "No rows reached resolved meeting_stage; diagnostic comparison is not ready."
        elif known < 15:
            level = "STAGE_RESOLVED"
            reason = "Meeting stages are resolved, but resolved row count is below diagnostic eligibility target."
        elif len(stages) < 2:
            level = "DIAGNOSTIC_ELIGIBLE"
            reason = "Resolved evidence is sufficient for diagnostics, but only one meeting_stage is represented."
        else:
            level = "CROSS_STAGE_COMPARABLE"
            reason = "Multiple meeting stages are represented and can be compared diagnostically."

        if level == "CROSS_STAGE_COMPARABLE" and known >= 15 and len(stages) >= 2:
            level = "SHADOW_TESTABLE"
            reason = "Cohort has enough resolved rows and multiple comparable meeting stages for Diagnostic Shadow."

        return {
            "level": level,
            "reason": reason,
            "missing_conditions": missing_conditions,
            "comparable_stage_count": len(stages),
            "target_meeting_count": len(racecourses),
            "resolved_stage_rows": known,
            "total_rows": total,
            "stage_counts": dict(Counter(row.meeting_stage for row in rows)),
            "racecourse_counts": dict(Counter(row.racecourse for row in rows)),
        }
