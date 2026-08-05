"""Build and save Learning Phase2 records from analysis output."""

from datetime import datetime, timezone

from .learning_database import LearningDatabase
from .learning_record import LearningRecord


LEARNING_PHASE2_ENABLED = False


class LearningWriter:
    """Persist analysis snapshots without learning or changing predictions."""

    def __init__(self, enabled=LEARNING_PHASE2_ENABLED, database=None, storage_path=None):
        self.enabled = bool(enabled)
        self.database = database or LearningDatabase(storage_path=storage_path)

    def write_analysis(self, race_output=None, horses=None):
        """Save horse-level records when enabled, otherwise report a no-op."""

        if not self.enabled:
            return {
                "enabled": False,
                "saved": False,
                "record_count": 0,
                "storage_path": str(self.database.storage_path),
                "records": [],
            }

        race = race_output if isinstance(race_output, dict) else {}
        rows = horses if isinstance(horses, list) else race.get("ranked_results", [])
        records = [self._record(race, horse, index) for index, horse in enumerate(rows, start=1)]
        save_result = self.database.save_records(records)
        return {
            "enabled": True,
            "saved": save_result.get("saved", False),
            "record_count": save_result.get("record_count", 0),
            "storage_path": save_result.get("storage_path"),
            "records": [record.to_dict() for record in records],
        }

    def _record(self, race, horse, fallback_rank):
        item = horse if isinstance(horse, dict) else {}
        decision_result = item.get("decision_result") if isinstance(item.get("decision_result"), dict) else {}
        diagnostics = (
            decision_result.get("decision_diagnostics")
            if isinstance(decision_result.get("decision_diagnostics"), dict)
            else item.get("decision_diagnostics")
        )
        if not isinstance(diagnostics, dict):
            diagnostics = {}

        return LearningRecord(
            race_id=str(race.get("race_id") or ""),
            horse_id=str(item.get("horse_id") or item.get("horse_number") or fallback_rank),
            horse_name=str(item.get("horse_name") or item.get("name") or ""),
            decision=str(item.get("decision") or decision_result.get("decision") or ""),
            final_score=self._number_or_none(item.get("final_score")),
            adjusted_score=self._number_or_none(item.get("adjusted_score")),
            confidence=item.get("confidence_level")
            or diagnostics.get("confidence")
            or item.get("confidence")
            or "",
            consensus={
                "score": item.get("consistency_score"),
                "level": item.get("consistency_level"),
                "strong_matches": self._list(item.get("strong_matches")),
                "weak_matches": self._list(item.get("weak_matches")),
                "conflict_factors": self._list(item.get("conflict_factors")),
                "decision_guards_applied": self._list(item.get("decision_guards_applied")),
            },
            risk=self._list(item.get("decision_risks"))
            or self._list(item.get("final_risks"))
            or self._list(item.get("risk_factors")),
            ability=item.get("total_score") or item.get("ability_score"),
            distance=item.get("distance_score"),
            course=item.get("course_score"),
            pace=item.get("pace_style_score") or item.get("pace_score"),
            running_style=item.get("running_style_score") or item.get("pace_style_score"),
            blood=item.get("bloodline_score") or item.get("blood_score"),
            condition=item.get("track_condition_score") or item.get("condition_score"),
            track_bias=item.get("track_bias_score"),
            race_shape=item.get("shape_score") or item.get("race_shape_score"),
            course_shape=item.get("course_shape_score"),
            decision_reason=str(item.get("decision_reason") or decision_result.get("decision_reason") or ""),
            explain=str(item.get("explanation") or item.get("explain_summary") or ""),
            race_summary=str(race.get("race_summary") or race.get("race_summary_short") or ""),
            race_decision=str(race.get("race_decision") or ""),
            analysis_date=str(race.get("prediction_time") or datetime.now(timezone.utc).isoformat()),
            result={},
            finish_position=None,
            metadata={
                "rank": item.get("rank") or item.get("final_rank") or fallback_rank,
                "racecourse": race.get("race_structure", {}).get("racecourse")
                if isinstance(race.get("race_structure"), dict)
                else "",
                "surface": race.get("race_structure", {}).get("surface")
                if isinstance(race.get("race_structure"), dict)
                else "",
                "distance": race.get("race_structure", {}).get("distance")
                if isinstance(race.get("race_structure"), dict)
                else "",
                "feature_phase": "learning_phase2_data_collection",
            },
        )

    def _number_or_none(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _list(self, value):
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        return [value]
