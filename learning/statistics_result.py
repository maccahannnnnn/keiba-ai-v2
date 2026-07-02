"""Standard result wrapper for StatisticsEngine output."""

from datetime import datetime, timezone


class StatisticsResult:
    """Normalize statistics summaries for exporters and future dashboards."""

    SCHEMA_VERSION = "statistics_result_v1"
    ENGINE_NAME = "StatisticsEngine"
    ENGINE_VERSION = "0.9"

    def __init__(
        self,
        statistics_summary=None,
        record_count=0,
        source="LearningHistory",
        warnings=None,
    ):
        self.statistics_summary = statistics_summary if isinstance(statistics_summary, dict) else {}
        self.record_count = record_count if isinstance(record_count, int) else 0
        self.source = source or "LearningHistory"
        self.warnings = warnings if isinstance(warnings, list) else []
        self.generated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        """Return the standard dictionary used by dashboards and exporters."""

        summary = self.get_summary()
        statistics = self.get_statistics()
        return {
            "metadata": {
                "engine_name": self.ENGINE_NAME,
                "engine_version": self.ENGINE_VERSION,
                "generated_at": self.generated_at,
                "record_count": self.record_count,
                "source": self.source,
                "schema_version": self.SCHEMA_VERSION,
            },
            "summary": summary,
            "statistics": statistics,
            "warnings": self.get_warnings(),
            "raw": self.statistics_summary,
        }

    def get_statistics(self):
        """Return only the statistics payload."""

        return {
            "decision_stats": self._dict_value("decision_stats"),
            "confidence_stats": self._dict_value("confidence_stats"),
            "buy_pass_stats": self._dict_value("buy_pass_stats"),
            "improvement_frequency": self._dict_value("improvement_frequency"),
            "course_stats": self._dict_value("course_stats"),
            "distance_stats": self._dict_value("distance_stats"),
            "track_condition_stats": self._dict_value("track_condition_stats"),
        }

    def get_summary(self):
        """Return only the summary payload."""

        total_reviews = self.statistics_summary.get("total_reviews", 0)
        if not isinstance(total_reviews, int):
            total_reviews = 0
        return {
            "total_reviews": total_reviews,
            "summary_comment": self.statistics_summary.get("summary_comment", "") or "",
        }

    def get_warnings(self):
        """Return warnings."""

        return list(self.warnings)

    def _dict_value(self, key):
        value = self.statistics_summary.get(key)
        return value if isinstance(value, dict) else {}
