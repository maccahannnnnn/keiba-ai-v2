"""Convert TARGET result CSV files into KeibaAI's standard result shape.

This adapter is intentionally separate from ResultImporter.  It only converts
TARGET result exports into dictionaries that downstream review/comparison code
can consume; it does not score, re-score, or change evaluator behavior.
"""

import csv
import re
import unicodedata
from pathlib import Path

from evaluation.course_name_normalizer import normalize_course_name


class TargetResultAdapter:
    """Load TARGET race/horse result CSV files safely."""

    ENCODINGS = ["utf-8-sig", "cp932", "shift_jis"]

    COURSE_MAP = {
        "札幌": "sapporo",
        "函館": "hakodate",
        "福島": "fukushima",
        "新潟": "niigata",
        "東京": "tokyo",
        "中山": "nakayama",
        "中京": "chuukyou",
        "京都": "kyoto",
        "阪神": "hanshin",
        "小倉": "kokura",
    }

    SURFACE_MAP = {
        "芝": "turf",
        "ダート": "dirt",
        "ダ": "dirt",
        "turf": "turf",
        "dirt": "dirt",
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

    def load(self, race_result_path=None, horse_result_path=None):
        """Load two TARGET result files and return standard result dictionaries."""

        warnings = []
        sources = []
        for path in [race_result_path, horse_result_path]:
            if path in (None, ""):
                continue
            rows, encoding, error = self._load_csv(path)
            if error:
                warnings.append(error)
            sources.append({"path": str(path), "rows": rows, "encoding": encoding})

        race_rows = []
        horse_rows = []
        for source in sources:
            rows = source.get("rows", [])
            if not rows:
                continue
            if self._looks_like_race_result(rows[0]):
                race_rows.extend(rows)
            elif self._looks_like_horse_results(rows[0]):
                horse_rows.extend(rows)
            else:
                warnings.append(f"Unsupported TARGET result columns: {source.get('path')}")

        race_result = self._convert_race_result(
            race_rows[0] if race_rows else {},
            race_result_path,
            horse_result_path,
            warnings,
        )
        race_id = race_result.get("race_id") or self._race_id_from_paths(
            race_result_path,
            horse_result_path,
        )
        if race_id and not race_result.get("race_id"):
            race_result["race_id"] = race_id

        horse_results = [
            self._convert_horse_result(row, race_id)
            for row in horse_rows
            if isinstance(row, dict)
        ]

        if not race_rows:
            warnings.append("race result row not found")
        if not horse_rows:
            warnings.append("horse result rows not found")

        return {
            "race_id": race_id,
            "race_result": race_result,
            "horse_results": horse_results,
            "warnings": warnings,
        }

    def _load_csv(self, path_like):
        path = Path(path_like)
        if not path.exists() or not path.is_file():
            return [], None, f"file not found: {path_like}"

        for encoding in self.ENCODINGS:
            try:
                with path.open("r", encoding=encoding, newline="") as file:
                    rows = list(csv.DictReader(file))
                return rows, encoding, None
            except (OSError, UnicodeDecodeError, csv.Error):
                continue
        return [], None, f"failed to read csv: {path_like}"

    def _looks_like_race_result(self, row):
        keys = set(row.keys()) if isinstance(row, dict) else set()
        return bool({"場所", "R", "芝・ダート", "距離"} & keys) and "馬名" not in keys

    def _looks_like_horse_results(self, row):
        keys = set(row.keys()) if isinstance(row, dict) else set()
        return "馬名" in keys and ("確定着順" in keys or "馬番" in keys)

    def _convert_race_result(self, row, race_result_path, horse_result_path, warnings):
        item = row if isinstance(row, dict) else {}
        race_date = self._normalize_date(self._pick(item, ["日付S"]))
        if not race_date:
            race_date = self._normalize_date(
                self._date_from_parts(item.get("年"), item.get("月"), item.get("日"))
            )
        racecourse = self._normalize_racecourse(item.get("場所"))
        race_number = self._normalize_race_number(item.get("R"))
        race_id = self._race_id_from_parts(race_date, racecourse, race_number)
        if not race_id:
            race_id = self._race_id_from_paths(race_result_path, horse_result_path)
            if race_id:
                warnings.append("race_id generated from filename")

        return {
            "race_id": race_id,
            "race_date": race_date,
            "racecourse": racecourse,
            "race_number": race_number,
            "race_name": self._clean_text(item.get("レース名")),
            "race_class": self._clean_text(item.get("クラス名")),
            "surface": self._normalize_surface(item.get("芝・ダート")),
            "distance": self._to_int(item.get("距離")),
            "weather": self._clean_text(item.get("天候")),
            "track_condition": self._normalize_track_condition(item.get("馬場状態")),
            "track_condition_raw": self._clean_text(item.get("馬場状態")),
            "race_last_3f": self._to_float(item.get("上り3F")),
            "winning_time": self._pick(item, ["1着入線タイム(秒)", "1着入線タイム"]),
            "average_time": self._pick(item, ["全馬平均タイム(秒)", "全馬平均タイム"]),
            "race_pci": self._to_float(item.get("レースPCI")),
            "lap_sequence": self._clean_text(item.get("通過ラップ表記")),
            "field_size": self._to_int(item.get("頭数")),
            "corner_1_positions": self._clean_text(item.get("1コーナー位置")),
            "corner_2_positions": self._clean_text(item.get("2コーナー位置")),
            "corner_3_positions": self._clean_text(item.get("3コーナー位置")),
            "corner_4_positions": self._clean_text(item.get("4コーナー位置")),
        }

    def _convert_horse_result(self, row, race_id):
        corners = [
            self._clean_text(row.get("通過1")),
            self._clean_text(row.get("通過2")),
            self._clean_text(row.get("通過3")),
            self._clean_text(row.get("通過4")),
        ]
        corners = [value for value in corners if value not in (None, "")]
        corner_positions = "-".join(corners)
        return {
            "race_id": race_id,
            "finish_position": self._to_int(row.get("確定着順")),
            "frame_number": self._to_int(row.get("枠番")),
            "horse_number": self._to_int(row.get("馬番")),
            "horse_name": self._normalize_name(row.get("馬名")),
            "finish_time": self._clean_text(row.get("タイム")),
            "official_time": self._clean_text(row.get("タイム")),
            "margin": self._clean_text(row.get("着差")),
            "pci": self._to_float(row.get("PCI")),
            "corner_positions": corner_positions,
            "passing_order": corner_positions,
            "fourth_corner_position": self._to_int(corners[-1] if corners else None),
            "average_3f": self._to_float(row.get("Ave-3F")),
            "last_3f": self._to_float(row.get("上り3F")),
            "last3f": self._to_float(row.get("上り3F")),
            "popularity": self._to_int(row.get("人気")),
            "odds": self._to_float(row.get("単勝オッズ")),
            "horse_weight": self._to_int(row.get("体重")),
            "weight_change": self._to_int(row.get("増減")),
            "abnormal_code": self._clean_text(row.get("異常コード")),
        }

    def _race_id_from_paths(self, *paths):
        pattern = re.compile(r"(?:race|horse)_(\d{8})_([a-z]+)_(\d{1,2}[rR])_result\.csv$")
        for path in paths:
            if path in (None, ""):
                continue
            match = pattern.search(Path(str(path)).name)
            if not match:
                continue
            return self._race_id_from_parts(
                match.group(1),
                match.group(2).lower(),
                self._normalize_race_number(match.group(3)),
            )
        return None

    def _race_id_from_parts(self, race_date, racecourse, race_number):
        if race_date and racecourse and race_number:
            return f"race_{race_date}_{racecourse}_{race_number}"
        return None

    def _date_from_parts(self, year, month, day):
        if year in (None, "") or month in (None, "") or day in (None, ""):
            return None
        return f"{year}{str(month).zfill(2)}{str(day).zfill(2)}"

    def _normalize_date(self, value):
        text = self._clean_text(value)
        separated = re.match(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$", text)
        if separated:
            return (
                f"{separated.group(1)}"
                f"{int(separated.group(2)):02d}"
                f"{int(separated.group(3)):02d}"
            )
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 8:
            return digits[:8]
        return None

    def _normalize_racecourse(self, value):
        text = self._clean_text(value)
        if not text:
            return None
        return normalize_course_name(self.COURSE_MAP.get(text, text.lower()))

    def _normalize_surface(self, value):
        text = self._clean_text(value)
        if not text:
            return None
        return self.SURFACE_MAP.get(text, text.lower())

    def _normalize_track_condition(self, value):
        text = self._clean_text(value)
        if not text:
            return None
        return self.CONDITION_MAP.get(text, text.lower())

    def _normalize_race_number(self, value):
        text = self._clean_text(value)
        match = re.search(r"\d+", text)
        if not match:
            return None
        return f"{int(match.group(0))}R"

    def _normalize_name(self, value):
        return self._clean_text(value).replace(" ", "").replace("　", "")

    def _pick(self, row, keys):
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return self._clean_text(value)
        return None

    def _clean_text(self, value):
        if value is None:
            return ""
        return unicodedata.normalize("NFKC", str(value)).strip()

    def _to_int(self, value):
        text = self._clean_text(value)
        if not text:
            return None
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None

    def _to_float(self, value):
        text = self._clean_text(value)
        if not text:
            return None
        try:
            return float(text)
        except (TypeError, ValueError):
            return None


if __name__ == "__main__":
    adapter = TargetResultAdapter()
    result = adapter.load(
        "data/results/race_20260712_kokura_11R_result.csv",
        "data/results/horse_20260712_kokura_11R_result.csv",
    )
    print(result)
