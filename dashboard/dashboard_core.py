"""DashboardCore display-data builder.

DashboardCore reads PredictionArchive records and reshapes them for future UI,
CLI, Web, or GUI display. It does not save archives, analyze results, learn,
or modify any evaluation output.
"""

from datetime import datetime, timezone

from archive.prediction_archive import PredictionArchive


class DashboardCore:
    """Build dashboard-friendly dictionaries from PredictionArchive records."""

    DASHBOARD_VERSION = "dashboard_core_v1"

    def __init__(self, archive=None, archive_dir="data/prediction_archive"):
        self.archive = archive if archive is not None else PredictionArchive(archive_dir=archive_dir)

    def build_dashboard_data(self, filters=None, limit=None):
        """Return a unified dashboard data dictionary from PredictionArchive."""

        warnings = []
        metadata_items = self.archive.search(filters, limit=limit) if filters else self.archive.list_archives(limit=limit)
        if not isinstance(metadata_items, list):
            metadata_items = []
            warnings.append("archive metadata list could not be loaded")

        archives = []
        for metadata in metadata_items:
            archive_id = metadata.get("archive_id") if isinstance(metadata, dict) else None
            loaded = self.archive.load(archive_id)
            if isinstance(loaded, dict):
                archives.append(loaded)
            else:
                warnings.append(f"archive could not be loaded: {archive_id}")

        overview = self.build_overview(archives)
        warnings.extend(self._archive_warnings(archives))

        return {
            "metadata": {
                "dashboard_version": self.DASHBOARD_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "PredictionArchive",
                "archive_count": len(archives),
            },
            "overview": overview,
            "statistics_view": self.build_statistics_view(archives),
            "prediction_view": self.build_prediction_view(archives, limit=limit or 20),
            "review_view": self.build_review_view(archives, limit=limit or 20),
            "learning_view": self.build_learning_view(archives, limit=limit or 20),
            "warnings": warnings,
        }

    def build_overview(self, archives):
        """Aggregate archive counts and latest timestamp."""

        archive_list = archives if isinstance(archives, list) else []
        type_counts = {
            "prediction": 0,
            "statistics": 0,
            "review": 0,
            "learning": 0,
        }
        latest_created_at = ""

        for archive in archive_list:
            archive_type = self._safe_get(archive, ["metadata", "archive_type"], "unknown")
            if archive_type in type_counts:
                type_counts[archive_type] += 1
            created_at = self._safe_get(archive, ["metadata", "created_at"], "")
            if str(created_at) > str(latest_created_at):
                latest_created_at = created_at

        total = len(archive_list)
        return {
            "total_archives": total,
            "prediction_count": type_counts["prediction"],
            "statistics_count": type_counts["statistics"],
            "review_count": type_counts["review"],
            "learning_count": type_counts["learning"],
            "latest_created_at": latest_created_at,
            "summary_comment": self._overview_comment(total, type_counts),
        }

    def build_statistics_view(self, archives):
        """Return the latest statistics archive in display format."""

        statistics_archives = self._filter_by_type(archives, "statistics")
        if not statistics_archives:
            return {
                "total_reviews": 0,
                "summary_comment": "",
                "decision_stats": {},
                "confidence_stats": {},
                "buy_pass_stats": {},
                "improvement_frequency": {},
                "course_stats": {},
                "distance_stats": {},
                "track_condition_stats": {},
            }

        latest = self._sort_newest(statistics_archives)[0]
        payload = self._safe_get(latest, ["payload"], {})
        summary = self._safe_get(payload, ["summary"], {})
        statistics = self._safe_get(payload, ["statistics"], {})
        if not statistics:
            statistics = payload

        return {
            "total_reviews": self._safe_get(summary, ["total_reviews"], self._safe_get(payload, ["total_reviews"], 0)),
            "summary_comment": self._safe_get(summary, ["summary_comment"], self._safe_get(payload, ["summary_comment"], "")),
            "decision_stats": self._safe_get(statistics, ["decision_stats"], {}),
            "confidence_stats": self._safe_get(statistics, ["confidence_stats"], {}),
            "buy_pass_stats": self._safe_get(statistics, ["buy_pass_stats"], {}),
            "improvement_frequency": self._safe_get(statistics, ["improvement_frequency"], {}),
            "course_stats": self._safe_get(statistics, ["course_stats"], {}),
            "distance_stats": self._safe_get(statistics, ["distance_stats"], {}),
            "track_condition_stats": self._safe_get(statistics, ["track_condition_stats"], {}),
        }

    def build_prediction_view(self, archives, limit=20):
        """Build prediction archive list rows."""

        rows = []
        for archive in self._sort_newest(self._filter_by_type(archives, "prediction"))[: self._limit(limit)]:
            metadata = self._safe_get(archive, ["metadata"], {})
            rows.append(
                {
                    "archive_id": self._safe_get(metadata, ["archive_id"], ""),
                    "created_at": self._safe_get(metadata, ["created_at"], ""),
                    "race_id": self._safe_get(metadata, ["race_id"], ""),
                    "racecourse": self._safe_get(metadata, ["racecourse"], ""),
                    "course": self._safe_get(metadata, ["course"], ""),
                    "surface": self._safe_get(metadata, ["surface"], ""),
                    "distance": self._safe_get(metadata, ["distance"], ""),
                    "track_condition": self._safe_get(metadata, ["track_condition"], ""),
                    "decision": self._safe_get(metadata, ["decision"], ""),
                    "confidence": self._safe_get(metadata, ["confidence"], ""),
                    "summary": self._safe_get(archive, ["summary"], {}),
                }
            )
        return rows

    def build_review_view(self, archives, limit=20):
        """Build review archive list rows."""

        rows = []
        for archive in self._sort_newest(self._filter_by_type(archives, "review"))[: self._limit(limit)]:
            metadata = self._safe_get(archive, ["metadata"], {})
            payload = self._safe_get(archive, ["payload"], {})
            rows.append(
                {
                    "archive_id": self._safe_get(metadata, ["archive_id"], ""),
                    "created_at": self._safe_get(metadata, ["created_at"], ""),
                    "race_id": self._safe_get(metadata, ["race_id"], ""),
                    "racecourse": self._safe_get(metadata, ["racecourse"], ""),
                    "decision": self._safe_get(metadata, ["decision"], ""),
                    "confidence": self._safe_get(metadata, ["confidence"], ""),
                    "review_result": self._safe_get(payload, ["review_result"], self._safe_get(payload, ["review_level"], "")),
                    "summary": self._safe_get(archive, ["summary"], {}),
                }
            )
        return rows

    def build_learning_view(self, archives, limit=20):
        """Build learning archive list rows."""

        rows = []
        for archive in self._sort_newest(self._filter_by_type(archives, "learning"))[: self._limit(limit)]:
            metadata = self._safe_get(archive, ["metadata"], {})
            payload = self._safe_get(archive, ["payload"], {})
            improvements = self._safe_get(payload, ["improvement_targets"], [])
            if not isinstance(improvements, list):
                improvements = []
            rows.append(
                {
                    "archive_id": self._safe_get(metadata, ["archive_id"], ""),
                    "created_at": self._safe_get(metadata, ["created_at"], ""),
                    "race_id": self._safe_get(metadata, ["race_id"], ""),
                    "improvement_count": len(improvements),
                    "main_improvement": improvements[0] if improvements else "",
                    "summary": self._safe_get(archive, ["summary"], {}),
                }
            )
        return rows

    def _safe_get(self, data, path, default=None):
        """Safely get a nested value from dict data."""

        current = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current.get(key)
        return default if current is None else current

    def _filter_by_type(self, archives, archive_type):
        archive_list = archives if isinstance(archives, list) else []
        return [
            archive
            for archive in archive_list
            if self._safe_get(archive, ["metadata", "archive_type"], "") == archive_type
        ]

    def _sort_newest(self, archives):
        archive_list = archives if isinstance(archives, list) else []
        return sorted(
            archive_list,
            key=lambda item: str(self._safe_get(item, ["metadata", "created_at"], "")),
            reverse=True,
        )

    def _archive_warnings(self, archives):
        warnings = []
        for archive in archives:
            archive_warnings = self._safe_get(archive, ["warnings"], [])
            if isinstance(archive_warnings, list):
                warnings.extend(str(warning) for warning in archive_warnings if warning)
        return warnings

    def _overview_comment(self, total, type_counts):
        if total == 0:
            return "保存済みArchiveはまだありません。"
        comments = []
        if type_counts.get("prediction", 0) > 0:
            comments.append("予想履歴が蓄積されています。")
        if type_counts.get("statistics", 0) > 0:
            comments.append("StatisticsResultが保存されており、統計表示が可能です。")
        if type_counts.get("review", 0) == 0:
            comments.append("Review履歴が少ないため、改善傾向の判断は保留です。")
        return " ".join(comments) if comments else "Archiveデータを表示できます。"

    def _limit(self, limit):
        return limit if isinstance(limit, int) and limit >= 0 else 20


if __name__ == "__main__":
    dashboard = DashboardCore()
    print(dashboard.build_dashboard_data(limit=5))
