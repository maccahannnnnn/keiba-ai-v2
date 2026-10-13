"""Shadow-only DG/DE/DS bulk prediction input adapter v1.

The TARGET sources are read-only, headerless CP932 CSV files.  This module
validates their observed fixed layouts and converts only directly mapped
fields into the existing ``TodayEntry`` and ``PastRace`` dataclasses.  It is
not imported by the Production path.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from analyzer.schemas import PastRace, TodayEntry


COURSE_CODES = {
    "札幌": "01", "函館": "02", "福島": "03", "新潟": "04", "東京": "05",
    "中山": "06", "中京": "07", "京都": "08", "阪神": "09", "小倉": "10",
}
COURSE_KEYS = {
    "札幌": "sapporo", "函館": "hakodate", "福島": "fukushima",
    "新潟": "niigata", "東京": "tokyo", "中山": "nakayama",
    "中京": "chuukyou", "京都": "kyoto", "阪神": "hanshin", "小倉": "kokura",
}
EXPECTED_WIDTHS = {"DG": 11, "DE": 33, "DS": 50}
HISTORY_LIMIT = 5

HUMAN_APPROVED_20260906_EXACT_EXCEPTION = "HUMAN_APPROVED_20260906_HANSHIN11R"
HUMAN_APPROVED_20260906_SOURCE_SHA256 = {
    "DG": "d9355e9f461fd110cf218a64ce70f32e85380448980d30df706878ab03764ccf",
    "DE": "f86ce3a652f214f643da1982775ab7cd1631ab659253add4c57959bf81750622",
    "DS": "fb1e554350cd9ebd402fda93b195493e31c2cb37c3e330579cca9d3a48566ce1",
}


class PredictionInputValidationError(ValueError):
    """Fail-closed validation error with a stable reason code."""

    def __init__(self, reason_code: str, detail: str):
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True)
class RawSource:
    kind: str
    path: Path
    sha256: str
    encoding: str
    delimiter: str
    header: bool
    width: int
    row_count: int


@dataclass
class RaceBundle:
    race_id: str
    today_entries: list[TodayEntry]
    past_races: list[PastRace]
    target_horse_identifiers: dict[tuple[int, str], str]
    stable_key_candidates: dict[tuple[int, str], str]
    history_rows_by_horse: dict[str, list[list[str]]]
    dg_row: list[str]


@dataclass
class PredictionInputBundle:
    date: str
    sources: dict[str, RawSource]
    races: dict[str, RaceBundle]
    preflight: dict[str, object]


class TargetBulkPredictionInputAdapterV1:
    """Validate one daily DG/DE/DS set and build existing input schemas."""

    def load(self, dg_path: str | Path, de_path: str | Path, ds_path: str | Path, *, compatibility_exception: str | None = None) -> PredictionInputBundle:
        paths = {"DG": Path(dg_path), "DE": Path(de_path), "DS": Path(ds_path)}
        rows: dict[str, list[list[str]]] = {}
        sources: dict[str, RawSource] = {}
        for kind, path in paths.items():
            values, source = self._read_fixed(path, kind)
            rows[kind] = values
            sources[kind] = source

        date = self._validate_dates(rows)
        dg_by_race = self._validate_dg(rows["DG"], date)
        de_by_race, identifiers, stable_keys = self._validate_de(rows["DE"], date)
        self._validate_dg_de(dg_by_race, de_by_race)
        exception_record = self._apply_human_approved_exact_exception(
            rows=rows, sources=sources, date=date, compatibility_exception=compatibility_exception,
        )
        ds_by_name = self._validate_ds(rows["DS"], date)
        self._validate_de_ds(rows["DE"], ds_by_name)

        races: dict[str, RaceBundle] = {}
        for race_key, dg_row in dg_by_race.items():
            race_id = self._race_id(date, race_key[0], race_key[1])
            entries = [self._today_entry(date, dg_row, row) for row in de_by_race[race_key]]
            past_races: list[PastRace] = []
            ids: dict[tuple[int, str], str] = {}
            keys: dict[tuple[int, str], str] = {}
            for row in de_by_race[race_key]:
                name = self._clean_name(row[7])
                number = self._int(row[3], "DE_HORSE_NUMBER_INVALID")
                ids[(number, name)] = identifiers[(race_id, number, name)]
                keys[(number, name)] = stable_keys[(race_id, number, name)]
                past_races.extend(self._past_races(ds_by_name[name]))
            races[race_id] = RaceBundle(
                race_id=race_id,
                today_entries=entries,
                past_races=past_races,
                target_horse_identifiers=ids,
                stable_key_candidates=keys,
                history_rows_by_horse={
                    self._clean_name(row[7]): list(ds_by_name[self._clean_name(row[7])])
                    for row in de_by_race[race_key]
                },
                dg_row=dg_row,
            )

        de_ids = [self._text(row[18]) for row in rows["DE"]]
        preflight = {
            "status": "PASS",
            "date": date,
            "race_count": len(races),
            "horse_count": len(rows["DE"]),
            "ds_row_count": len(rows["DS"]),
            "dg_de_race_mismatch_count": 0,
            "dg_de_headcount_mismatch_count": 0,
            "de_ds_unmatched_count": 0,
            "de_ds_ambiguous_count": 0,
            "de_column_19_nonempty_count": sum(bool(value) for value in de_ids),
            "de_column_19_unique_count": len(set(de_ids)),
            "de_column_19_collision_count": len(de_ids) - len(set(de_ids)),
            "de_column_33_structural_match_count": len(rows["DE"]),
            "de_column_33_structural_mismatch_count": 0,
            "ds_identifier_equivalent_present": False,
            "de_ds_join_method": "date-scoped unique normalized horse_name",
            "missing_value_inference_count": 0,
            "past_race_limit": HISTORY_LIMIT,
        }
        if exception_record is not None:
            preflight["input_exception"] = exception_record
        return PredictionInputBundle(date=date, sources=sources, races=races, preflight=preflight)

    def _apply_human_approved_exact_exception(self, *, rows: dict[str, list[list[str]]], sources: dict[str, RawSource], date: str, compatibility_exception: str | None) -> dict[str, object] | None:
        """Apply exactly one Human-approved in-memory DS identity reconciliation.

        This has no default behavior and contains no prefix/fuzzy/general alias
        logic.  It is valid only for the frozen source snapshot named below.
        """
        if compatibility_exception is None:
            return None
        if compatibility_exception != HUMAN_APPROVED_20260906_EXACT_EXCEPTION:
            raise PredictionInputValidationError("INPUT_EXCEPTION_NOT_AUTHORIZED", compatibility_exception)
        if date != "20260906":
            raise PredictionInputValidationError("INPUT_EXCEPTION_DATE_MISMATCH", date)
        actual_sha = {kind: source.sha256 for kind, source in sources.items()}
        if actual_sha != HUMAN_APPROVED_20260906_SOURCE_SHA256:
            raise PredictionInputValidationError("INPUT_EXCEPTION_SOURCE_SHA_MISMATCH", repr(actual_sha))

        de_name, ds_name = "ファストネットワーク", "ファストネットワー"
        target_de = [row for row in rows["DE"] if self._text(row[1]) == "阪神" and self._int(row[2], "DE_RACE_NUMBER_INVALID") == 11 and self._int(row[3], "DE_HORSE_NUMBER_INVALID") == 8 and self._clean_name(row[7]) == de_name and self._text(row[18]) == "20190007"]
        dg_context = [row for row in rows["DG"] if self._text(row[3]) == "阪神" and self._int(row[4], "DG_RACE_NUMBER_INVALID") == 11]
        ds_target = [row for row in rows["DS"] if self._clean_name(row[16]) == ds_name]
        de_names = {self._clean_name(row[7]) for row in rows["DE"]}
        ds_names = {self._clean_name(row[16]) for row in rows["DS"]}
        missing, extra = de_names - ds_names, ds_names - de_names
        prefix_candidates = [row for row in rows["DE"] if self._text(row[1]) == "阪神" and self._int(row[2], "DE_RACE_NUMBER_INVALID") == 11 and self._clean_name(row[7]).startswith(ds_name)]
        if not (
            len(target_de) == 1 and len(dg_context) == 1 and len(ds_target) >= 1
            and missing == {de_name} and extra == {ds_name}
            and len(prefix_candidates) == 1 and self._clean_name(prefix_candidates[0][7]) == de_name
            and all(self._text(row[17]) == self._text(target_de[0][8]) for row in ds_target)
            and all(self._text(row[46]) == self._text(target_de[0][20]) for row in ds_target)
        ):
            raise PredictionInputValidationError("INPUT_EXCEPTION_EXACT_SCOPE_MISMATCH", "20260906/hanshin11R")
        for row in ds_target:
            row[16] = de_name
        return {
            "state": "HUMAN_APPROVED_EXACT_COMPATIBILITY_MAPPING",
            "scope": "2026-09-06 / hanshin11R / exact-name-pair-only",
            "mapping_count": 1,
            "de_exact_name": de_name,
            "ds_exact_name": ds_name,
            "source_sha_guard": "PASS",
            "exact_scope_guard": "PASS",
            "general_truncation_rule": "REJECT",
        }

    def _read_fixed(self, path: Path, kind: str) -> tuple[list[list[str]], RawSource]:
        if not path.is_file():
            raise PredictionInputValidationError("RAW_FILE_MISSING", str(path))
        raw = path.read_bytes()
        try:
            text = raw.decode("cp932")
        except UnicodeDecodeError as exc:
            raise PredictionInputValidationError("RAW_ENCODING_INVALID", f"{path}: {exc}") from exc
        parsed = list(csv.reader(text.splitlines()))
        self._validate_fixed_rows(parsed, kind, path)
        width = EXPECTED_WIDTHS[kind]
        return parsed, RawSource(
            kind=kind,
            path=path.resolve(),
            sha256=hashlib.sha256(raw).hexdigest(),
            encoding="cp932",
            delimiter=",",
            header=False,
            width=width,
            row_count=len(parsed),
        )

    def _validate_fixed_rows(self, parsed: list[list[str]], kind: str, path: Path | str = "in-memory") -> None:
        if not parsed or any(not row for row in parsed):
            raise PredictionInputValidationError("RAW_EMPTY_ROW", str(path))
        width = EXPECTED_WIDTHS[kind]
        invalid = [index + 1 for index, row in enumerate(parsed) if len(row) != width]
        if invalid:
            raise PredictionInputValidationError("RAW_COLUMN_COUNT_INVALID", f"{path}: rows={invalid[:10]}")
        if self._looks_like_header(parsed[0], kind):
            raise PredictionInputValidationError("RAW_HEADER_UNEXPECTED", str(path))

    def _read_fixed_rows_for_test(self, parsed: list[list[str]], kind: str) -> None:
        """Exercise fixed-row fail-closed validation without writing fixtures."""

        self._validate_fixed_rows(parsed, kind)

    def _looks_like_header(self, row: list[str], kind: str) -> bool:
        sentinels = {"年", "月", "日", "場所", "馬名", "race_date"}
        return bool(sentinels.intersection({self._text(value) for value in row}))

    def _validate_dates(self, rows: dict[str, list[list[str]]]) -> str:
        de_dates = {self._text(row[0]) for row in rows["DE"]}
        if len(de_dates) != 1 or not re.fullmatch(r"\d{6}", next(iter(de_dates), "")):
            raise PredictionInputValidationError("DE_DATE_INVALID", repr(sorted(de_dates)))
        short = next(iter(de_dates))
        date = f"20{short}"
        dg_dates = {f"{self._text(row[0])}{self._text(row[1]).zfill(2)}{self._text(row[2]).zfill(2)}" for row in rows["DG"]}
        if dg_dates != {date}:
            raise PredictionInputValidationError("DG_DE_DATE_MISMATCH", repr(sorted(dg_dates)))
        return date

    def _validate_dg(self, rows: list[list[str]], date: str) -> dict[tuple[str, int], list[str]]:
        result: dict[tuple[str, int], list[str]] = {}
        for row in rows:
            course = self._text(row[3])
            number = self._int(row[4], "DG_RACE_NUMBER_INVALID")
            self._int(row[6], "DG_DISTANCE_INVALID") if False else None
            distance = self._int(row[8], "DG_DISTANCE_INVALID")
            field_size = self._int(row[9], "DG_FIELD_SIZE_INVALID")
            if course not in COURSE_KEYS or self._text(row[7]) not in {"芝", "ダ", "ダート"} or distance <= 0 or field_size <= 0:
                raise PredictionInputValidationError("DG_SENTINEL_INVALID", repr(row))
            key = (course, number)
            if key in result:
                raise PredictionInputValidationError("DG_RACE_DUPLICATE", repr(key))
            result[key] = row
        return result

    def _validate_de(self, rows: list[list[str]], date: str):
        by_race: dict[tuple[str, int], list[list[str]]] = defaultdict(list)
        identifiers: dict[tuple[str, int, str], str] = {}
        stable_keys: dict[tuple[str, int, str], str] = {}
        seen_ids: set[str] = set()
        for row in rows:
            course = self._text(row[1])
            race_number = self._int(row[2], "DE_RACE_NUMBER_INVALID")
            horse_number = self._int(row[3], "DE_HORSE_NUMBER_INVALID")
            name = self._clean_name(row[7])
            identifier = self._text(row[18])
            stable = self._text(row[32])
            if not name or not re.fullmatch(r"\d{8}", identifier):
                raise PredictionInputValidationError("DE_IDENTIFIER_INVALID", repr(row))
            if identifier in seen_ids:
                raise PredictionInputValidationError("DE_IDENTIFIER_COLLISION", identifier)
            seen_ids.add(identifier)
            expected_code = COURSE_CODES.get(course)
            if expected_code is None or not stable.startswith(expected_code) or not stable.endswith(f"{horse_number:02d}"):
                raise PredictionInputValidationError("DE_STABLE_KEY_STRUCTURE_INVALID", stable)
            race_id = self._race_id(date, course, race_number)
            key = (race_id, horse_number, name)
            identifiers[key] = identifier
            stable_keys[key] = stable
            by_race[(course, race_number)].append(row)
        for key, race_rows in by_race.items():
            horses = [(self._int(row[3], "DE_HORSE_NUMBER_INVALID"), self._clean_name(row[7])) for row in race_rows]
            if len(horses) != len(set(horses)):
                raise PredictionInputValidationError("DE_RACE_HORSE_DUPLICATE", repr(key))
        return dict(by_race), identifiers, stable_keys

    def _validate_dg_de(self, dg, de) -> None:
        if set(dg) != set(de):
            raise PredictionInputValidationError("DG_DE_RACE_MISMATCH", repr(sorted(set(dg) ^ set(de))))
        mismatches = []
        for key, dg_row in dg.items():
            expected = self._int(dg_row[9], "DG_FIELD_SIZE_INVALID")
            actual = len(de[key])
            if expected != actual:
                mismatches.append((key, expected, actual))
        if mismatches:
            raise PredictionInputValidationError("DG_DE_HEADCOUNT_MISMATCH", repr(mismatches))

    def _validate_ds(self, rows: list[list[str]], target_date: str) -> dict[str, list[list[str]]]:
        by_name: dict[str, list[list[str]]] = defaultdict(list)
        for row in rows:
            year = self._int(row[0], "DS_YEAR_INVALID")
            month = self._int(row[1], "DS_MONTH_INVALID")
            day = self._int(row[2], "DS_DAY_INVALID")
            race_date = datetime(2000 + year, month, day)
            if race_date.strftime("%Y%m%d") >= target_date:
                raise PredictionInputValidationError("DS_FUTURE_OR_SAME_DAY_RUN", repr(row[:5]))
            if self._text(row[4]) == "" or self._int(row[6], "DS_RACE_NUMBER_INVALID") <= 0:
                raise PredictionInputValidationError("DS_RACE_CONTEXT_INVALID", repr(row[:8]))
            if self._text(row[12]) not in {"芝", "ダ"} or self._int(row[14], "DS_DISTANCE_INVALID") <= 0:
                raise PredictionInputValidationError("DS_SURFACE_DISTANCE_INVALID", repr(row[12:16]))
            name = self._clean_name(row[16])
            if not name:
                raise PredictionInputValidationError("DS_HORSE_NAME_MISSING", repr(row[:20]))
            by_name[name].append(row)
        for name, horse_rows in by_name.items():
            dates = [self._ds_datetime(row) for row in horse_rows]
            if dates != sorted(dates, reverse=True):
                raise PredictionInputValidationError("DS_RUN_ORDER_INVALID", name)
        return dict(by_name)

    def _validate_de_ds(self, de_rows: list[list[str]], ds_by_name: dict[str, list[list[str]]]) -> None:
        names = [self._clean_name(row[7]) for row in de_rows]
        duplicates = [name for name, count in Counter(names).items() if count > 1]
        if duplicates:
            raise PredictionInputValidationError("DE_DS_AMBIGUOUS_HORSE", repr(duplicates))
        missing = sorted(set(names) - set(ds_by_name))
        extra = sorted(set(ds_by_name) - set(names))
        if missing or extra:
            raise PredictionInputValidationError("DE_DS_HORSE_SET_MISMATCH", f"missing={missing}; extra={extra}")

    def _today_entry(self, date: str, dg: list[str], de: list[str]) -> TodayEntry:
        return TodayEntry(
            race_date=f"{date[:4]}-{date[4:6]}-{date[6:]}",
            racecourse=COURSE_KEYS[self._text(dg[3])],
            race_number=self._int(dg[4], "DG_RACE_NUMBER_INVALID"),
            surface={"芝": "turf", "ダ": "dirt", "ダート": "dirt"}[self._text(dg[7])],
            status="",
            horse_name=self._clean_name(de[7]),
            horse_number=self._int(de[3], "DE_HORSE_NUMBER_INVALID"),
            frame_number=self._int(de[22], "DE_FRAME_NUMBER_INVALID"),
            jockey=self._text(de[10]),
            distance=self._int(dg[8], "DG_DISTANCE_INVALID"),
            track_condition="",
            weight=self._float(de[11], "DE_WEIGHT_INVALID"),
            body_weight=0,
            body_weight_diff=0,
            running_style="",
            last_runs="",
            past_lap_note="",
            expected_lap_note="",
            sire=self._text(de[16]),
            dam_sire=self._text(de[20]),
            bloodline_note="",
            class_level=self._text(de[4]),
        )

    def _past_races(self, rows: list[list[str]]) -> list[PastRace]:
        result = []
        valid_rows = self.valid_history_rows(rows)
        for row in valid_rows:
            course = self._text(row[4])
            number = self._int(row[6], "DS_RACE_NUMBER_INVALID")
            corners = [self._text(row[index]) for index in range(31, 35)]
            result.append(PastRace(
                race_date=self._ds_datetime(row),
                race_id=self._race_id(self._ds_datetime(row).strftime("%Y%m%d"), course, number),
                horse_name=self._clean_name(row[16]),
                jockey=self._text(row[19]),
                distance=self._int(row[14], "DS_DISTANCE_INVALID"),
                track_condition=self._text(row[15]),
                field_size=self._int(row[21], "DS_FIELD_SIZE_INVALID"),
                class_level=self._text(row[8]),
                popularity=self._optional_int(row[27]),
                finish_position=self._optional_int(row[23]),
                corner_positions="-".join(value for value in corners if value),
                running_style="",
                pace="",
                body_weight=self._optional_int(row[37]),
                body_weight_diff=self._optional_int(row[38]),
                sire=self._text(row[44]),
                dam_sire=self._text(row[46]),
                surface=self._text(row[12]),
                margin=self._optional_float(row[26]),
                last_3f=self._optional_float(row[35]),
                pci=self._optional_float(row[49]),
                rpci=self._optional_float(row[48]),
            ))
        return result

    def valid_history_rows(self, rows: list[list[str]]) -> list[list[str]]:
        """Return up to five valid completed runs, preserving source order."""

        return [
            row for row in rows
            if self._text(row[25]) in {"", "0"} and self._optional_int(row[23]) > 0
        ][:HISTORY_LIMIT]

    def _race_id(self, date: str, course: str, number: int) -> str:
        key = COURSE_KEYS.get(course, str(course).strip().lower())
        return f"race_{date}_{key}_{int(number)}R"

    def _ds_datetime(self, row: list[str]) -> datetime:
        return datetime(2000 + int(self._text(row[0])), int(self._text(row[1])), int(self._text(row[2])))

    def _text(self, value: object) -> str:
        return str(value or "").strip()

    def _clean_name(self, value: object) -> str:
        return self._text(value).replace(" ", "").replace("　", "")

    def _int(self, value: object, reason: str) -> int:
        try:
            return int(self._text(value))
        except ValueError as exc:
            raise PredictionInputValidationError(reason, repr(value)) from exc

    def _optional_int(self, value: object) -> int:
        text = self._text(value).replace("+", "")
        if not text or not re.fullmatch(r"-?\d+", text):
            return 0
        return int(text)

    def _optional_float(self, value: object) -> float | None:
        text = self._text(value)
        if not text or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
            return None
        return float(text)

    def _float(self, value: object, reason: str) -> float:
        try:
            return float(self._text(value))
        except ValueError as exc:
            raise PredictionInputValidationError(reason, repr(value)) from exc
