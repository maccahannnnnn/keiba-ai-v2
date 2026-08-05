"""Import race results into a review-friendly structure.

ResultImporter only normalizes post-race result data. It does not score,
review, learn, or change prediction snapshots, review records, decisions, or
trial reports.
"""

import csv
import re
import unicodedata
from pathlib import Path


class ResultImporter:
    """Normalize official result-like data for future review comparison."""

    RESULT_ENCODINGS = ["utf-8-sig", "cp932", "shift_jis"]

    COLUMN_ALIASES = {
        "race_id": ["race_id", "レースID"],
        "race_date": ["race_date", "開催日", "日付"],
        "racecourse": ["racecourse", "競馬場"],
        "race_number": ["race_number", "race_no", "R", "レース番号"],
        "surface": ["surface", "芝ダート"],
        "distance": ["distance", "距離"],
        "track_condition": ["track_condition", "馬場状態"],
        "frame_number": ["frame_number", "枠番"],
        "horse_number": ["horse_number", "馬番"],
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
        "last_3f_rank": ["last_3f_rank", "上がり順位", "上3F順位"],
        "result_note": ["result_note", "\u5099\u8003", "note"],
    }

    COURSE_MAP = {
        "札幌": "sapporo",
        "函館": "hakodate",
        "福島": "fukushima",
        "新潟": "niigata",
        "東京": "tokyo",
        "中山": "nakayama",
        "中京": "chukyo",
        "京都": "kyoto",
        "阪神": "hanshin",
        "小倉": "kokura",
    }

    SURFACE_MAP = {
        "芝": "turf",
        "turf": "turf",
        "Turf": "turf",
        "ダート": "dirt",
        "ダ": "dirt",
        "dirt": "dirt",
        "Dirt": "dirt",
    }

    CONDITION_MAP = {
        "良": "firm",
        "稍重": "yielding",
        "重": "soft",
        "不良": "heavy",
        "firm": "firm",
        "good": "good",
        "yielding": "yielding",
        "soft": "soft",
        "heavy": "heavy",
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

        race_meta = self._race_meta_from_rows(horse_results)
        race_result = {
            "prediction_id": prediction_id,
            "race_name": race_name,
            "race_id": self._race_id_from_rows(horse_results),
            "race_date": race_meta.get("race_date"),
            "racecourse": race_meta.get("racecourse"),
            "race_number": race_meta.get("race_number"),
            "surface": race_meta.get("surface"),
            "distance": race_meta.get("distance"),
            "track_condition": race_meta.get("track_condition"),
            "result_status": status,
            "result_loaded": loaded,
            "horse_results": horse_results,
        }

        return {
            "prediction_id": prediction_id,
            "race_id": race_result.get("race_id"),
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
        race_date = self._normalize_date(self._pick(item, "race_date"))
        racecourse = self._normalize_racecourse(self._pick(item, "racecourse"))
        race_number = self._normalize_race_number(self._pick(item, "race_number"))
        surface = self._normalize_surface(self._pick(item, "surface"))
        corner_positions = self._pick(item, "passing_order") or ""
        race_id = self._pick(item, "race_id") or self._build_race_id(
            race_date,
            racecourse,
            race_number,
        )
        return {
            "race_id": race_id,
            "race_date": race_date,
            "racecourse": racecourse,
            "race_number": race_number,
            "surface": surface,
            "distance": self._to_int(self._pick(item, "distance")),
            "track_condition": self._normalize_track_condition(self._pick(item, "track_condition")),
            "frame_number": self._to_int(self._pick(item, "frame_number")),
            "horse_number": self._to_int(self._pick(item, "horse_number")),
            "horse_name": self._normalize_name(self._pick(item, "horse_name")) or "unknown",
            "finish_position": self._to_int(self._pick(item, "finish_position")),
            "official_time": self._pick(item, "official_time") or "",
            "finish_time": self._pick(item, "official_time") or "",
            "margin": self._pick(item, "margin") or "",
            "passing_order": corner_positions,
            "corner_positions": corner_positions,
            "fourth_corner_position": self._fourth_corner_position(corner_positions),
            "last3f": self._pick(item, "last3f") or "",
            "last_3f": self._pick(item, "last3f") or "",
            "last_3f_rank": self._to_int(self._pick(item, "last_3f_rank")),
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

    def _normalize_date(self, value):
        text = str(value or "").strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 8:
            return digits[:8]
        return text or None

    def _normalize_racecourse(self, value):
        text = str(value or "").strip()
        if not text:
            return None
        normalized = self.COURSE_MAP.get(text)
        if normalized:
            return normalized
        return text.lower()

    def _normalize_race_number(self, value):
        text = str(value or "").strip()
        if not text:
            return None
        match = re.search(r"\d+", text)
        if not match:
            return text.upper()
        return f"{int(match.group(0))}R"

    def _normalize_surface(self, value):
        text = str(value or "").strip()
        if not text:
            return None
        return self.SURFACE_MAP.get(text, text.lower())

    def _normalize_track_condition(self, value):
        text = str(value or "").strip()
        if not text:
            return None
        return self.CONDITION_MAP.get(text, text.lower())

    def _build_race_id(self, race_date, racecourse, race_number):
        if race_date and racecourse and race_number:
            return f"race_{race_date}_{racecourse}_{race_number}"
        return None

    def _race_id_from_rows(self, rows):
        for row in rows:
            if isinstance(row, dict) and row.get("race_id"):
                return row.get("race_id")
        return None

    def _race_meta_from_rows(self, rows):
        meta = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in [
                "race_date",
                "racecourse",
                "race_number",
                "surface",
                "distance",
                "track_condition",
            ]:
                if key not in meta and row.get(key) not in (None, ""):
                    meta[key] = row.get(key)
        return meta

    def _fourth_corner_position(self, value):
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        if not text:
            return None
        numbers = re.findall(r"\d+", text)
        if not numbers:
            return None
        try:
            return int(numbers[-1])
        except (TypeError, ValueError):
            return None

    def _normalize_name(self, value):
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        return text.replace(" ", "").replace("　", "")

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
