"""Read-only Phase A-1 integrity preflight for the February V4 Model v4 holdout.

The script intentionally does not instantiate or call the prediction adapter.
It validates only raw DG/DE/DS identity and schema sentinels needed before a
later formal PRE freeze.  Daily Result Lists and result-semantic columns are
not opened or used.
"""
from __future__ import annotations

import csv
import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.date_exclusivity_validator_v1 import collect_evidence_dates, validate
from review.target_bulk_prediction_input_adapter_v1 import COURSE_CODES, COURSE_KEYS, EXPECTED_WIDTHS


EVIDENCE_ROLE = "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V4"
DATES = ["20260201", "20260207", "20260208", "20260210", "20260214", "20260215", "20260221", "20260222", "20260228"]
SPECIAL_VENUES = {"20260208": {"小倉"}, "20260210": {"東京", "京都"}}
MODEL_AUTHORITY = {
    "model.joblib": ("reports/ml_v4_buy_selection_model_v4/model.joblib", "58d3977d0f44eab325a2b384f0c17b66ddc276fff6370f6e05b7a1680642d74f"),
    "scaler.joblib": ("reports/ml_v4_buy_selection_model_v4/scaler.joblib", "3d18757f4991c21a4a645f92ca26361d88c030a4097696d2cc4a6c86d3767b90"),
    "dataset.csv": ("reports/ml_v4_buy_selection_dataset_v4/dataset.csv", "b02bb4b59b5f297e60964f96050890dbf32a7ac3b5a9ef93424b9d612e3ae80a"),
    "selected_feature_columns.json": ("reports/ml_v4_buy_selection_model_v4/selected_feature_columns.json", "acf79da95865cc087cead024280f04baa4eeda2b98911c2aa21be9c010af3c5d"),
}


def clean(value: object) -> str:
    return str(value or "").strip().replace(" ", "").replace("　", "")


def text(value: object) -> str:
    return str(value or "").strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_fixed(path: Path, kind: str, errors: list[dict[str, Any]]) -> list[list[str]]:
    try:
        raw = path.read_bytes()
        decoded = raw.decode("cp932")
        rows = list(csv.reader(decoded.splitlines()))
    except Exception as exc:  # Preserve a fail-closed, source-specific error.
        errors.append({"code": "RAW_UNREADABLE", "path": relative(path), "detail": f"{type(exc).__name__}:{exc}"})
        return []
    expected_width = EXPECTED_WIDTHS[kind]
    invalid = [index + 1 for index, row in enumerate(rows) if len(row) != expected_width]
    if not rows or any(not row for row in rows):
        errors.append({"code": "RAW_EMPTY_ROW", "path": relative(path), "detail": "empty source or row"})
    if invalid:
        errors.append({"code": "RAW_COLUMN_COUNT_INVALID", "path": relative(path), "detail": invalid[:20]})
    header_sentinels = {"年", "月", "日", "場所", "馬名", "race_date"}
    if rows and header_sentinels.intersection({text(value) for value in rows[0]}):
        errors.append({"code": "RAW_HEADER_UNEXPECTED", "path": relative(path), "detail": "first row header sentinel"})
    return rows


def add_error(errors: list[dict[str, Any]], code: str, date: str, detail: Any) -> None:
    errors.append({"code": code, "date": date, "detail": detail})


def is_new_or_jump(category: str) -> tuple[bool, bool]:
    return "新馬" in category, "障害" in category or "障" in category


def hash_source(path: Path, kind: str, date: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "date": date,
        "source_type": kind,
        "filename": path.name,
        "path": relative(path),
        "byte_size": stat.st_size,
        "sha256": sha256(path),
        "modified_timestamp_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--candidate-preregistration", type=Path)
    args = parser.parse_args()
    phase_a0_root = ROOT / "reports/v4_model_v4_february_historical_holdout/preflight"
    output = args.output_root.resolve() if args.output_root else phase_a0_root
    preregistration_path = (args.candidate_preregistration.resolve() if args.candidate_preregistration else phase_a0_root / "february_candidate_date_preregistration.json")
    targets = [
        "prediction_source_inventory_after_acquisition.json", "raw_source_hashes.json", "date_exclusivity_post_acquisition.json",
        "dg_integrity.json", "de_integrity.json", "ds_integrity.json", "dg_de_ds_reconciliation.json",
        "special_date_integrity_0208_0210.json", "source_population_inventory.json", "feature_source_availability.json",
        "result_access_audit.json", "prediction_execution_audit.json", "safety_phase_a1.json", "phase_a1_report.md",
        "phase_a1_artifact_hashes.json", "reacquisition_0201_hash_comparison.json", "february_0201_tokyo12_detail.json",
    ]
    if not preregistration_path.is_file():
        raise FileNotFoundError(f"PHASE_A0_PREREQUISITE_MISSING:{preregistration_path}")
    output.mkdir(parents=True, exist_ok=True)
    existing = [name for name in targets if (output / name).exists()]
    if existing:
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{existing}")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    head_before = git_head()
    source_root = ROOT / "data/raw/prediction_input"
    result_root = ROOT / "data/raw/target/daily_result_list"
    expected_paths = [(date, kind, source_root / f"{kind}{date[2:]}.CSV") for date in DATES for kind in ("DG", "DE", "DS")]
    missing_paths = [relative(path) for _, _, path in expected_paths if not path.is_file()]
    if missing_paths:
        # This branch is retained for rerun safety; no raw source is opened.
        write_json(output / "prediction_source_inventory_after_acquisition.json", {"status": "STOP_RAW_FILES_MISSING", "missing_paths": missing_paths, "result_data_access_count": 0})
        raise RuntimeError("STOP_RAW_FILES_MISSING")

    source_hashes = [hash_source(path, kind, date) for date, kind, path in expected_paths]
    before_hashes = {(entry["date"], entry["source_type"]): entry["sha256"] for entry in source_hashes}
    old_hash_path = phase_a0_root / "raw_source_hashes.json"
    old_hashes = {}
    if old_hash_path.is_file():
        old_hashes = {(entry["date"], entry["source_type"]): entry["sha256"] for entry in json.loads(old_hash_path.read_text(encoding="utf-8")).get("hashes", [])}
    changed_raw_sources = [entry for entry in source_hashes if old_hashes.get((entry["date"], entry["source_type"])) not in {None, entry["sha256"]}]
    intended_reacquired = {("20260201", "DG"), ("20260201", "DE"), ("20260201", "DS")}
    errors: list[dict[str, Any]] = []
    dg_summary: dict[str, Any] = {"dates": {}, "errors": errors, "validation_scope": "DG identity and non-result programme fields only"}
    de_errors: list[dict[str, Any]] = []
    ds_errors: list[dict[str, Any]] = []
    dg_by_date: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    de_by_date: dict[str, dict[tuple[str, int], list[dict[str, Any]]]] = {}
    ds_names_by_date: dict[str, set[str]] = {}
    ds_stats_by_date: dict[str, Any] = {}
    population_dates: dict[str, Any] = {}

    for date in DATES:
        dg_rows = read_fixed(source_root / f"DG{date[2:]}.CSV", "DG", errors)
        de_rows = read_fixed(source_root / f"DE{date[2:]}.CSV", "DE", de_errors)
        ds_rows = read_fixed(source_root / f"DS{date[2:]}.CSV", "DS", ds_errors)
        dg_races: dict[tuple[str, int], dict[str, Any]] = {}
        for row_index, row in enumerate(dg_rows, 1):
            if len(row) != 11:
                continue
            row_date = f"{text(row[0])}{text(row[1]).zfill(2)}{text(row[2]).zfill(2)}"
            course, surface, category = text(row[3]), text(row[7]), f"{text(row[5])} {text(row[6])}"
            try:
                number, distance, field_size = int(text(row[4])), int(text(row[8])), int(text(row[9]))
            except ValueError:
                add_error(errors, "DG_NUMERIC_SENTINEL_INVALID", date, {"row": row_index})
                continue
            if row_date != date:
                add_error(errors, "DG_DATE_INVALID", date, {"row": row_index, "observed": row_date})
            if course not in COURSE_KEYS:
                add_error(errors, "DG_VENUE_UNEXPECTED", date, {"row": row_index, "venue": course})
            if number <= 0 or number > 12:
                add_error(errors, "DG_RACE_NUMBER_INVALID", date, {"row": row_index, "race_number": number})
            if surface not in {"芝", "ダ", "ダート"} or distance <= 0 or field_size <= 0:
                add_error(errors, "DG_SENTINEL_INVALID", date, {"row": row_index})
            key = (course, number)
            if key in dg_races:
                add_error(errors, "DG_RACE_DUPLICATE", date, {"venue": course, "race_number": number})
            new_race, obstacle = is_new_or_jump(category)
            dg_races[key] = {"venue": course, "race_number": number, "field_size": field_size, "surface": surface, "distance": distance, "category": category, "new_race": new_race, "obstacle": obstacle}
        dg_by_date[date] = dg_races
        dg_summary["dates"][date] = {"race_count": len(dg_races), "venues": sorted({key[0] for key in dg_races}), "races": list(sorted(dg_races.values(), key=lambda value: (value["venue"], value["race_number"]))) }

        de_races: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        seen_registration: set[str] = set()
        for row_index, row in enumerate(de_rows, 1):
            if len(row) != 33:
                continue
            if text(row[0]) != date[2:]:
                add_error(de_errors, "DE_DATE_INVALID", date, {"row": row_index, "observed": text(row[0])})
            course, name, registration, stable = text(row[1]), clean(row[7]), text(row[18]), text(row[32])
            try:
                race_number, horse_number = int(text(row[2])), int(text(row[3]))
            except ValueError:
                add_error(de_errors, "DE_NUMERIC_SENTINEL_INVALID", date, {"row": row_index})
                continue
            if course not in COURSE_CODES or race_number <= 0 or race_number > 12 or horse_number <= 0 or not name:
                add_error(de_errors, "DE_IDENTITY_INVALID", date, {"row": row_index})
            if not re.fullmatch(r"\d{8}", registration):
                add_error(de_errors, "DE_REGISTRATION_ID_INVALID", date, {"row": row_index})
            elif registration in seen_registration:
                add_error(de_errors, "DE_REGISTRATION_ID_COLLISION", date, {"registration_id": registration})
            else:
                seen_registration.add(registration)
            expected_code = COURSE_CODES.get(course)
            if expected_code is None or not stable.startswith(expected_code) or not stable.endswith(f"{horse_number:02d}"):
                add_error(de_errors, "DE_STABLE_KEY_STRUCTURE_INVALID", date, {"row": row_index, "stable_key": stable})
            de_races[(course, race_number)].append({"horse_number": horse_number, "horse_name": name, "registration_id": registration})
        for key, entries in de_races.items():
            numbers = [entry["horse_number"] for entry in entries]
            names = [entry["horse_name"] for entry in entries]
            if len(numbers) != len(set(numbers)) or len(names) != len(set(names)):
                add_error(de_errors, "DE_RACE_HORSE_DUPLICATE", date, {"venue": key[0], "race_number": key[1]})
        de_by_date[date] = dict(de_races)

        # DS reads identity and non-result source sentinels only.  In particular,
        # indices 23+ (finish, margin, corners, time) are deliberately untouched.
        ds_by_name: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        ds_row_errors = 0
        for row_index, row in enumerate(ds_rows, 1):
            if len(row) != 50:
                continue
            try:
                year, month, day, race_number, distance = int(text(row[0])), int(text(row[1])), int(text(row[2])), int(text(row[6])), int(text(row[14]))
                historic_date = datetime(2000 + year, month, day).strftime("%Y%m%d")
            except ValueError:
                add_error(ds_errors, "DS_IDENTITY_SENTINEL_INVALID", date, {"row": row_index}); ds_row_errors += 1; continue
            course, surface, name = text(row[4]), text(row[12]), clean(row[16])
            if historic_date >= date:
                add_error(ds_errors, "DS_FUTURE_OR_SAME_DAY_RUN", date, {"row": row_index, "historic_date": historic_date}); ds_row_errors += 1
            if not course or race_number <= 0 or surface not in {"芝", "ダ"} or distance <= 0 or not name:
                add_error(ds_errors, "DS_REQUIRED_INPUT_MISSING", date, {"row": row_index}); ds_row_errors += 1
            ds_by_name[name].append((historic_date, course, race_number))
        for name, histories in ds_by_name.items():
            dates_order = [value[0] for value in histories]
            if dates_order != sorted(dates_order, reverse=True):
                add_error(ds_errors, "DS_RUN_ORDER_INVALID", date, {"horse_name": name}); ds_row_errors += 1
        de_names = {entry["horse_name"] for entries in de_races.values() for entry in entries}
        ds_names = set(ds_by_name)
        ds_names_by_date[date] = ds_names
        ds_stats_by_date[date] = {
            "history_row_count": len(ds_rows), "history_horse_count": len(ds_names), "target_horse_name_match_method": "date-scoped unique normalized horse_name",
            "registration_id_in_ds": "NOT_AVAILABLE_IN_FIXED_DS_V1_MAPPING", "result_equivalent_columns_read": [], "identity_error_count": ds_row_errors,
        }
        new_count = sum(1 for race in dg_races.values() if race["new_race"])
        obstacle_count = sum(1 for race in dg_races.values() if race["obstacle"])
        population_dates[date] = {"race_count": len(dg_races), "horse_count": sum(len(rows) for rows in de_races.values()), "new_race_count": new_count, "obstacle_race_count": obstacle_count, "ordinary_candidate_race_count": len(dg_races) - new_count - obstacle_count, "venues": sorted({key[0] for key in dg_races})}

    reconciliation_dates: dict[str, Any] = {}
    for date in DATES:
        dg_keys, de_keys = set(dg_by_date[date]), set(de_by_date[date])
        headcount_mismatch = []
        for key in sorted(dg_keys & de_keys):
            if dg_by_date[date][key]["field_size"] != len(de_by_date[date][key]):
                headcount_mismatch.append({"venue": key[0], "race_number": key[1], "dg_field_size": dg_by_date[date][key]["field_size"], "de_horse_count": len(de_by_date[date][key])})
        de_names = {entry["horse_name"] for entries in de_by_date[date].values() for entry in entries}
        missing_ds, extra_ds = sorted(de_names - ds_names_by_date[date]), sorted(ds_names_by_date[date] - de_names)
        if dg_keys != de_keys:
            add_error(errors, "DG_DE_RACE_SET_MISMATCH", date, {"dg_only": sorted(dg_keys - de_keys), "de_only": sorted(de_keys - dg_keys)})
        if headcount_mismatch:
            add_error(errors, "DG_DE_HEADCOUNT_MISMATCH", date, headcount_mismatch)
        if missing_ds or extra_ds:
            add_error(ds_errors, "DE_DS_HORSE_SET_MISMATCH", date, {"missing_in_ds": missing_ds, "extra_in_ds": extra_ds})
        reconciliation_dates[date] = {"dg_de_race_set_match": dg_keys == de_keys, "dg_only_races": sorted(dg_keys - de_keys), "de_only_races": sorted(de_keys - dg_keys), "headcount_mismatches": headcount_mismatch, "de_ds_horse_set_match": not missing_ds and not extra_ds, "missing_in_ds_count": len(missing_ds), "extra_in_ds_count": len(extra_ds), "missing_in_ds": missing_ds, "extra_in_ds": extra_ds, "ds_target_race_set_comparison": "NOT_APPLICABLE_DS_ROWS_ARE_HISTORICAL_RUNS; target association uses DE/DS horse identity"}

    prereg = json.loads(preregistration_path.read_text(encoding="utf-8"))
    if prereg.get("candidate_dates") != DATES:
        errors.append({"code": "CANDIDATE_DATE_AUTHORITY_MISMATCH", "detail": prereg.get("candidate_dates")})
    if any((entry["date"], entry["source_type"]) not in intended_reacquired for entry in changed_raw_sources):
        errors.append({"code": "UNEXPECTED_RAW_SOURCE_CHANGE", "detail": [{"date": entry["date"], "source_type": entry["source_type"]} for entry in changed_raw_sources]})
    exclusivity = validate(DATES, collect_evidence_dates(ROOT))
    exclusivity.update({"artifact_type": "DATE_EXCLUSIVITY_POST_ACQUISITION_V1", "evidence_role": EVIDENCE_ROLE, "checked_at_utc": now, "git_head": head_before, "result_data_access_count": 0})
    if exclusivity["status"] != "PASS":
        errors.append({"code": "DATE_EXCLUSIVITY_CONFLICT", "detail": exclusivity["overlap_dates"]})

    special = {}
    for date, expected_venues in SPECIAL_VENUES.items():
        observed = {key[0] for key in dg_by_date[date]}
        special[date] = {"expected_dg_venues": sorted(expected_venues), "observed_dg_venues": sorted(observed), "dg_calendar_match": observed == expected_venues, "de_venues": sorted({key[0] for key in de_by_date[date]}), "dg_de_race_set_match": reconciliation_dates[date]["dg_de_race_set_match"], "de_ds_horse_set_match": reconciliation_dates[date]["de_ds_horse_set_match"]}
        if observed != expected_venues:
            add_error(errors, "SPECIAL_DATE_VENUE_MISMATCH", date, special[date])

    authority_checks = {}
    for label, (path_text, expected) in MODEL_AUTHORITY.items():
        path = ROOT / path_text
        observed = sha256(path) if path.is_file() else None
        authority_checks[label] = {"path": path_text, "expected_sha256": expected, "observed_sha256": observed, "status": "PASS" if observed == expected else "FAIL"}
        if observed != expected:
            errors.append({"code": "MODEL_AUTHORITY_HASH_MISMATCH", "detail": label})

    # Source-level availability only: all semantic model columns are produced by
    # the later frozen prediction pipeline, not stored as raw DG/DE/DS columns.
    selected = json.loads((ROOT / "reports/ml_v4_buy_selection_model_v4/selected_feature_columns.json").read_text(encoding="utf-8"))
    feature_source = {
        "artifact_type": "V4_MODEL_V4_FEATURE_SOURCE_AVAILABILITY_V1",
        "selected_semantic_input_count": len(selected["semantic_selected_columns"]),
        "selected_transformed_input_count": len(selected["transformed_selected_columns"]),
        "relative_gap_status": selected["relative_gap_status"],
        "relative_gap_used_for_selection": False,
        "raw_prerequisites": {"DG": "AVAILABLE", "DE": "AVAILABLE", "DS": "AVAILABLE"},
        "derived_feature_values": "NOT_GENERATED_IN_PHASE_A1",
        "schema_level_status": "RAW_PREREQUISITES_AVAILABLE; value-level availability deferred to authorized PRE freeze",
        "prediction_execution_count": 0,
    }

    all_errors = errors + de_errors + ds_errors
    feb01_unresolved = any(error["code"] in {"DG_DE_RACE_SET_MISMATCH", "DE_DS_HORSE_SET_MISMATCH"} and error.get("date") == "20260201" for error in all_errors)
    status = "PASS" if not all_errors else ("STOP_SOURCE_SEMANTICS_UNRESOLVED_AFTER_REACQUISITION" if feb01_unresolved else "STOP_SOURCE_INTEGRITY_FAILURE")
    inventory = {"artifact_type": "FEBRUARY_PREDICTION_SOURCE_INVENTORY_AFTER_ACQUISITION_V1", "candidate_dates": DATES, "expected_file_count": 27, "found_file_count": 27, "status": "PASS", "files": source_hashes, "content_scope": "DG/DE/DS only; no Daily Result List opened", "result_data_access_count": 0}
    write_json(output / "prediction_source_inventory_after_acquisition.json", inventory)
    write_json(output / "raw_source_hashes.json", {"artifact_type": "FEBRUARY_RAW_SOURCE_HASH_FREEZE_V1", "source_file_count": 27, "hashes": source_hashes, "raw_source_modification_count": 0, "status": "PASS"})
    write_json(output / "reacquisition_0201_hash_comparison.json", {
        "artifact_type": "FEBRUARY_0201_REACQUISITION_HASH_COMPARISON_V1",
        "old_hash_authority": relative(old_hash_path) if old_hash_path.is_file() else None,
        "intended_reacquired_sources": ["DG260201.CSV", "DE260201.CSV", "DS260201.CSV"],
        "changed_sources": [{"filename": entry["filename"], "source_type": entry["source_type"], "old_sha256": old_hashes.get((entry["date"], entry["source_type"])), "new_sha256": entry["sha256"]} for entry in changed_raw_sources],
        "unexpected_source_change_count": sum((entry["date"], entry["source_type"]) not in intended_reacquired for entry in changed_raw_sources),
        "only_intended_sources_changed": all((entry["date"], entry["source_type"]) in intended_reacquired for entry in changed_raw_sources),
        "raw_source_mutation_by_validator": 0,
    })
    write_json(output / "date_exclusivity_post_acquisition.json", exclusivity)
    write_json(output / "dg_integrity.json", {"artifact_type": "FEBRUARY_DG_INTEGRITY_V1", "status": "PASS" if not errors else "FAIL", **dg_summary})
    write_json(output / "de_integrity.json", {"artifact_type": "FEBRUARY_DE_INTEGRITY_V1", "status": "PASS" if not de_errors else "FAIL", "per_date_race_count": {date: len(value) for date, value in de_by_date.items()}, "per_date_horse_count": {date: sum(len(rows) for rows in value.values()) for date, value in de_by_date.items()}, "errors": de_errors, "registration_id_source": "DE column 19 (1-based)", "stable_key_source": "DE column 33 (1-based)"})
    write_json(output / "ds_integrity.json", {"artifact_type": "FEBRUARY_DS_INTEGRITY_V1", "status": "PASS" if not ds_errors else "FAIL", "per_date": ds_stats_by_date, "errors": ds_errors, "fields_read": ["past_race_date", "past_race_venue", "past_race_number", "surface", "distance", "horse_name"], "fields_not_read": ["finish_position", "abnormal_result", "margin", "corner_positions", "time", "last_3f", "payout"], "result_data_access_count": 0})
    write_json(output / "dg_de_ds_reconciliation.json", {"artifact_type": "FEBRUARY_DG_DE_DS_RECONCILIATION_V1", "status": "PASS" if all(item["dg_de_race_set_match"] and item["de_ds_horse_set_match"] and not item["headcount_mismatches"] for item in reconciliation_dates.values()) else "FAIL", "per_date": reconciliation_dates, "de_ds_join_semantics": "exact date-scoped normalized horse_name set equality; DS registration ID is not available in fixed DS v1 mapping"})
    write_json(output / "special_date_integrity_0208_0210.json", {"artifact_type": "FEBRUARY_SPECIAL_DATE_INTEGRITY_V1", "status": "PASS" if all(item["dg_calendar_match"] and item["dg_de_race_set_match"] and item["de_ds_horse_set_match"] for item in special.values()) else "FAIL", "dates": special})
    feb01_dg = dg_by_date["20260201"]
    feb01_de = de_by_date["20260201"]
    feb01_tokyo12_entries = feb01_de.get(("東京", 12), [])
    feb01_de_names = {entry["horse_name"] for entries in feb01_de.values() for entry in entries}
    feb01_tokyo12_names = {entry["horse_name"] for entry in feb01_tokyo12_entries}
    write_json(output / "february_0201_tokyo12_detail.json", {
        "artifact_type": "FEBRUARY_0201_TOKYO12_SOURCE_SEMANTICS_DETAIL_V1",
        "dg": {"total_races": len(feb01_dg), "venues": sorted({key[0] for key in feb01_dg}), "tokyo_race_numbers": sorted(number for venue, number in feb01_dg if venue == "東京"), "tokyo12_present": ("東京", 12) in feb01_dg},
        "de": {"total_races": len(feb01_de), "venues": sorted({key[0] for key in feb01_de}), "tokyo_race_numbers": sorted(number for venue, number in feb01_de if venue == "東京"), "tokyo12_present": ("東京", 12) in feb01_de, "tokyo12_horse_count": len(feb01_tokyo12_entries), "tokyo12_identity_fields": ["horse_number", "horse_name", "registration_id"], "tokyo12_entries": feb01_tokyo12_entries, "race_classification_from_dg": feb01_dg.get(("東京", 12), {}).get("category")},
        "ds": {"historical_race_identity_semantics": "DS contains past-race records, not target-date entry races", "total_history_horses": len(ds_names_by_date["20260201"]), "tokyo12_target_race_presence": "NOT_APPLICABLE", "tokyo12_de_horse_set_fully_present": feb01_tokyo12_names.issubset(ds_names_by_date["20260201"]), "tokyo12_de_horses_missing_count": len(feb01_tokyo12_names - ds_names_by_date["20260201"]), "tokyo12_de_horses_missing": sorted(feb01_tokyo12_names - ds_names_by_date["20260201"]), "all_de_horses_missing_count": len(feb01_de_names - ds_names_by_date["20260201"])} ,
        "formal_answer": "Three source sets reconcile only when DG/DE target race sets match and every DE horse has a DS history-name match. No class-based exclusion is applied.",
    })
    totals = {"source_races_total": sum(item["race_count"] for item in population_dates.values()), "source_horses_total": sum(item["horse_count"] for item in population_dates.values()), "new_race_count": sum(item["new_race_count"] for item in population_dates.values()), "obstacle_race_count": sum(item["obstacle_race_count"] for item in population_dates.values()), "ordinary_candidate_race_count": sum(item["ordinary_candidate_race_count"] for item in population_dates.values())}
    write_json(output / "source_population_inventory.json", {"artifact_type": "FEBRUARY_SOURCE_POPULATION_INVENTORY_V1", "status": "SOURCE_LEVEL_ONLY", "candidate_dates": DATES, "per_date": population_dates, "totals": totals, "formal_exclusions": ["新馬", "障害"], "not_evaluated": ["BUY eligibility", "V4 selection", "probability", "historical lift"]})
    write_json(output / "feature_source_availability.json", feature_source)
    write_json(output / "result_access_audit.json", {"artifact_type": "FEBRUARY_RESULT_ACCESS_AUDIT_V1", "february_result_file_name_count": len(list(result_root.glob("*202602*.csv"))) if result_root.is_dir() else 0, "result_file_contents_read": False, "result_importer_execution_count": 0, "finish_access_count": 0, "actual_top3_access_count": 0, "result_data_access_count": 0, "status": "PASS"})
    write_json(output / "prediction_execution_audit.json", {"artifact_type": "FEBRUARY_PREDICTION_EXECUTION_AUDIT_V1", "adapter_execution_count": 0, "current_prediction_execution_count": 0, "model_v4_inference_count": 0, "model_v4_predict_proba_count": 0, "buy_generation_count": 0, "cf_execution_count": 0, "same_volume_selection_count": 0, "status": "PASS"})
    after_hashes = {(date, kind): sha256(path) for date, kind, path in expected_paths}
    raw_zero_delta = before_hashes == after_hashes
    head_after = git_head()
    safety = {"artifact_type": "FEBRUARY_PHASE_A1_SAFETY_V1", "status": "PASS" if raw_zero_delta and head_before == head_after else "FAIL", "source_raw_zero_delta": raw_zero_delta, "result_data_access_count": 0, "prediction_execution_count": 0, "production_change_count": 0, "current_ai_change_count": 0, "buy_gate_change_count": 0, "cf_change_count": 0, "v4_model_v4_change_count": 0, "dataset_v4_change_count": 0, "adapter_execution_count": 0, "git_head_before": head_before, "git_head_after": head_after, "model_authority": authority_checks}
    write_json(output / "safety_phase_a1.json", safety)
    report = f"""# V4 Model v4 — February 2026 Historical Holdout\n\n## Phase A-1 result\n\n- Status: `{status}`\n- Candidate dates: `{len(DATES)}`\n- Raw sources: `27/27`\n- Date exclusivity overlap: `{exclusivity['overlap_count']}`\n- Source races / horses: `{totals['source_races_total']} / {totals['source_horses_total']}`\n- New races / obstacle races: `{totals['new_race_count']} / {totals['obstacle_race_count']}`\n- Result access: `0`\n- Prediction / Adapter execution: `0 / 0`\n\n## Boundary\n\nThis run only validates prediction-side DG/DE/DS integrity. It did not use a Daily Result List, finish, actual_top3, prediction, model inference, BUY generation, CF, or POST evaluation.\n\n## Next state\n\n`FEBRUARY_FORMAL_PRE_FREEZE_READY` is `YES` only when this artifact status is `PASS`; result access remains unauthorized regardless.\n"""
    (output / "phase_a1_report.md").write_text(report, encoding="utf-8")
    hashes = {path.name: sha256(path) for path in sorted(output.iterdir()) if path.is_file() and path.name in targets and path.name != "phase_a1_artifact_hashes.json"}
    write_json(output / "phase_a1_artifact_hashes.json", {"artifact_type": "FEBRUARY_PHASE_A1_HASH_INDEX_V1", "indexed_artifacts": hashes, "self_hash_excluded": True, "status": "PASS"})
    print(f"FEBRUARY_2026_SOURCE_INTEGRITY_PREFLIGHT={status}")
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
