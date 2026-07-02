"""Import race results into a review-friendly structure.

ResultImporter only normalizes post-race result data. It does not score,
review, learn, or change prediction snapshots, review records, decisions, or
trial reports.
"""

import csv
from pathlib import Path


class ResultImporter:
    """Normalize official result-like data for future review comparison."""

    RESULT_ENCODINGS = ["utf-8-sig", "cp932", "shift_jis"]

    COLUMN_ALIASES = {
        "horse_name": ["horse_name", "\u99ac\u540d", "name"],
        "finish_position": ["finish_position", "\u7740\u9806", "\u9806\u4f4d"],
        "official_time": [
            "official_time",
            "finish_time",
            "\u30bf\u30a4\u30e0",
            "\u8d70\u7834\u30bf\u30a4\u30e0",
        ],
        "margin": ["margin", "\u7740\u5dee"],
        "passing_order": ["passing_order", "corner_positions", "\u901a\u904e\u9806"],
        "last3f": ["last3f", "last_3f", "\u4e0a\u304c\u308a3F", "\u4e0a3F"],
        "result_note": ["result_note", "\u5099\u8003", "note"],
    }

    def import_result(
        self,
        result_data=None,
        prediction_id=None,
        review_record=None,
        prediction_snapshot=None,
    ):
        """Return normalized result_import_result.

        result_data may be None, a race-result dict, a horse-result list, or a
        CSV path. Missing result data returns a pending result safely.
        """

        if result_data is None or result_data == "":
            return self._pending(prediction_id)

        horse_results = []
        race_name = None

        if isinstance(result_data, dict):
            race_name = result_data.get("race_name")
            source_horses = result_data.get("horse_results")
            if source_horses is None:
                source_horses = result_data.get("horses")
            if isinstance(source_horses, list):
                horse_results = [self._horse_result(row) for row in source_horses]
            elif self._looks_like_horse(result_data):
                horse_results = [self._horse_result(result_data)]
        elif isinstance(result_data, list):
            horse_results = [self._horse_result(row) for row in result_data if isinstance(row, dict)]
        else:
            race_name, horse_results = self._load_csv(result_data)

        horse_results = [row for row in horse_results if row.get("horse_name") != "unknown"]
        loaded = bool(horse_results)
        status = "loaded" if loaded else "pending"

        if not race_name:
            race_name = self._race_name_from_review(review_record, prediction_snapshot)

        race_result = {
            "prediction_id": prediction_id,
            "race_name": race_name,
            "result_status": status,
            "result_loaded": loaded,
            "horse_results": horse_results,
        }

        return {
            "prediction_id": prediction_id,
            "result_loaded": loaded,
            "result_status": status,
            "race_result": race_result,
            "horse_results": horse_results,
        }

    def _pending(self, prediction_id=None):
        race_result = {
            "prediction_id": prediction_id,
            "result_loaded": False,
            "result_status": "pending",
            "horse_results": [],
        }
        return {
            "prediction_id": prediction_id,
            "result_loaded": False,
            "result_status": "pending",
            "race_result": race_result,
            "horse_results": [],
        }

    def _load_csv(self, path_like):
        try:
            path = Path(path_like)
        except (TypeError, ValueError):
            return None, []
        if not path.exists() or not path.is_file():
            return None, []

        for encoding in self.RESULT_ENCODINGS:
            try:
                with path.open("r", encoding=encoding, newline="") as file:
                    rows = list(csv.DictReader(file))
                return path.stem, [self._horse_result(row) for row in rows if isinstance(row, dict)]
            except (OSError, UnicodeDecodeError, csv.Error):
                continue
        return path.stem, []

    def _horse_result(self, row):
        item = row if isinstance(row, dict) else {}
        return {
            "horse_name": self._pick(item, "horse_name") or "unknown",
            "finish_position": self._to_int(self._pick(item, "finish_position")),
            "official_time": self._pick(item, "official_time") or "",
            "margin": self._pick(item, "margin") or "",
            "passing_order": self._pick(item, "passing_order") or "",
            "last3f": self._pick(item, "last3f") or "",
            "result_note": self._pick(item, "result_note") or "",
        }

    def _pick(self, row, key):
        for candidate in self.COLUMN_ALIASES.get(key, [key]):
            value = row.get(candidate)
            if value not in {None, ""}:
                return value
        return None

    def _to_int(self, value):
        if isinstance(value, bool) or value in {None, ""}:
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _looks_like_horse(self, row):
        return any(alias in row for alias in self.COLUMN_ALIASES["horse_name"])

    def _race_name_from_review(self, review_record, prediction_snapshot):
        if isinstance(prediction_snapshot, dict) and prediction_snapshot.get("race_name"):
            return prediction_snapshot.get("race_name")
        if isinstance(review_record, dict):
            race = review_record.get("race")
            if isinstance(race, dict) and race.get("race_name"):
                return race.get("race_name")
        return None


if __name__ == "__main__":
    importer = ResultImporter()
    print(importer.import_result(prediction_id="sample"))
