"""JSON exporter for StatisticsResult."""

import json
from datetime import datetime
from pathlib import Path

from learning.statistics_result import StatisticsResult


class StatisticsExporter:
    """Export StatisticsResult payloads for future dashboards."""

    def __init__(self, output_dir="reports/statistics"):
        self.output_dir = Path(output_dir)

    def export_json(self, statistics_result, filename=None):
        """Save StatisticsResult or dict as UTF-8 JSON and return the path."""

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            exportable = self._to_exportable_dict(statistics_result)
            output_name = filename or self._default_filename()
            output_path = self.output_dir / output_name
            with output_path.open("w", encoding="utf-8") as handle:
                json.dump(exportable, handle, ensure_ascii=False, indent=2)
            return str(output_path)
        except OSError:
            return None
        except TypeError:
            return None

    def _to_exportable_dict(self, statistics_result):
        """Convert supported result objects to a JSON-exportable dict."""

        if isinstance(statistics_result, StatisticsResult):
            return statistics_result.to_dict()
        if hasattr(statistics_result, "to_dict") and callable(statistics_result.to_dict):
            value = statistics_result.to_dict()
            return value if isinstance(value, dict) else {}
        if isinstance(statistics_result, dict):
            return statistics_result
        return {}

    def _default_filename(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"statistics_{timestamp}.json"
