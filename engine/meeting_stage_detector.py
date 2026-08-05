"""Detect meeting stage for MeetingBias explain context.

The detector is intentionally small and non-scoring.  It only converts
available meeting metadata into one of the MeetingBias stages used by
MeetingBiasEngine: opening, middle, or closing.
"""

from __future__ import annotations

import re
from datetime import datetime


class MeetingStageDetector:
    """Resolve meeting_stage from explicit metadata with safe fallbacks."""

    STAGES = {"opening", "middle", "closing"}

    def detect(self, context=None):
        """Return opening, middle, or closing from available race metadata."""

        data = context if isinstance(context, dict) else {}

        explicit = self._normalize_stage(data.get("meeting_stage"))
        if explicit:
            return explicit

        week = self._number(data.get("meeting_week") or data.get("開催週"))
        if week is not None:
            return self._stage_from_week(week)

        meeting_day = self._number(
            data.get("meeting_day")
            or data.get("meeting_day_number")
            or data.get("開催日数")
            or data.get("開催日")
        )
        if meeting_day is not None:
            return self._stage_from_meeting_day(meeting_day)

        race_date = data.get("race_date") or data.get("date") or data.get("開催日付")
        stage = self._stage_from_date(race_date)
        if stage:
            return stage

        return "middle"

    def _normalize_stage(self, value):
        if value in (None, ""):
            return None
        text = str(value).strip().lower()
        aliases = {
            "early": "opening",
            "open": "opening",
            "opening_week": "opening",
            "front": "opening",
            "mid": "middle",
            "middle_meeting": "middle",
            "late": "closing",
            "final": "closing",
            "closing_week": "closing",
            "final_week": "closing",
        }
        text = aliases.get(text, text)
        return text if text in self.STAGES else None

    def _stage_from_week(self, week):
        if week <= 1:
            return "opening"
        if week >= 3:
            return "closing"
        return "middle"

    def _stage_from_meeting_day(self, meeting_day):
        if meeting_day <= 2:
            return "opening"
        if meeting_day >= 7:
            return "closing"
        return "middle"

    def _stage_from_date(self, value):
        date_value = self._parse_date(value)
        if date_value is None:
            return None
        week_of_month = ((date_value.day - 1) // 7) + 1
        return self._stage_from_week(week_of_month)

    def _parse_date(self, value):
        if value in (None, ""):
            return None
        text = str(value).strip()
        digits = re.sub(r"\D", "", text)
        if len(digits) == 8:
            try:
                return datetime.strptime(digits, "%Y%m%d").date()
            except ValueError:
                return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    def _number(self, value):
        if value in (None, ""):
            return None
        match = re.search(r"\d+", str(value))
        if not match:
            return None
        try:
            return int(match.group(0))
        except ValueError:
            return None
