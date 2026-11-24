"""Build read-only manifests for full-race result observation populations.

The existing race/horse result CSV files remain the only official result
assets.  This module neither creates nor changes those CSVs; it records their
identity, hashes, completeness, and Prediction/Observation membership.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from engine.result_importer import ResultImporter


SCHEMA_VERSION = "OBSERVATION_MANIFEST_V1"
POPULATION_SCHEMA_VERSION = "OBSERVATION_POPULATION_V1"
RESULT_ENCODINGS = ("utf-8-sig", "cp932", "shift_jis")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_date(value: object) -> str:
    digits = "".join(char for char in str(value) if char.isdigit())
    if len(digits) != 8:
        raise ValueError("INVALID_OBSERVATION_DATE")
    return digits


def _normalize_race_number(value: object) -> str:
    text = str(value).strip().upper()
    if text.endswith("R"):
        text = text[:-1]
    if not text.isdigit() or int(text) <= 0:
        raise ValueError("INVALID_RACE_NUMBER")
    return f"{int(text)}R"


def _read_csv(path: Path) -> list[dict[str, str]]:
    for encoding in RESULT_ENCODINGS:
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return list(csv.DictReader(handle))
        except (UnicodeDecodeError, OSError, csv.Error):
            continue
    raise ValueError(f"RESULT_CSV_NOT_READABLE:{path}")


def _pick(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _positive_finish(value: str) -> bool:
    try:
        return int(float(value)) > 0
    except (TypeError, ValueError):
        return False


def _normal_abnormal_code(value: str) -> bool:
    return value.strip() in {"", "0", "0.0"}


class ObservationManifestBuilder:
    """Create an additive manifest over existing official result CSVs."""

    def __init__(self, result_root: str | Path = "data/results", importer: ResultImporter | None = None):
        self.result_root = Path(result_root)
        self.importer = importer or ResultImporter()

    def build(
        self,
        *,
        date: object,
        racecourse: str,
        expected_race_numbers: Iterable[object],
        prediction_linked_race_ids: Iterable[str] = (),
        generated_at: str | None = None,
        source: str = "INTERNAL_OFFICIAL_RESULT_CSV",
    ) -> dict:
        race_date = _normalize_date(date)
        course = str(racecourse).strip().lower()
        if not course or not course.replace("_", "").isalnum():
            raise ValueError("INVALID_RACECOURSE")

        race_numbers = [_normalize_race_number(value) for value in expected_race_numbers]
        if len(set(race_numbers)) != len(race_numbers) or not race_numbers:
            raise ValueError("INVALID_EXPECTED_RACE_SET")
        expected_race_ids = [f"race_{race_date}_{course}_{number}" for number in race_numbers]
        linked = set(prediction_linked_race_ids)
        unexpected_linked = linked.difference(expected_race_ids)
        if unexpected_linked:
            raise ValueError(f"PREDICTION_LINK_OUTSIDE_POPULATION:{sorted(unexpected_linked)}")

        files: list[dict] = []
        races: list[dict] = []
        missing: list[dict] = []
        saved_horse_count = 0
        abnormal_result_count = 0
        importer_loaded_count = 0

        for race_id, race_number in zip(expected_race_ids, race_numbers):
            suffix = race_id.removeprefix("race_")
            paths = {
                "RACE_RESULT": self.result_root / f"{race_id}_result.csv",
                "HORSE_RESULT": self.result_root / f"horse_{suffix}_result.csv",
            }
            missing_roles = [role for role, path in paths.items() if not path.is_file()]
            importer_loaded = False
            horse_count = 0
            race_abnormal_count = 0

            if not missing_roles:
                imported = self.importer.import_result(paths["HORSE_RESULT"], prediction_id=None)
                importer_loaded = bool(imported.get("result_loaded"))
                if not importer_loaded:
                    missing_roles.append("IMPORTER_RESULT_NOT_LOADED")
                else:
                    importer_loaded_count += 1
                    rows = _read_csv(paths["HORSE_RESULT"])
                    horse_count = len(rows)
                    for row in rows:
                        finish = _pick(row, ("確定着順", "着順", "finish", "finish_position"))
                        abnormal_code = _pick(row, ("異常コード", "abnormal_code"))
                        if not _positive_finish(finish) or not _normal_abnormal_code(abnormal_code):
                            race_abnormal_count += 1
                    for role, path in paths.items():
                        files.append(
                            {
                                "race_id": race_id,
                                "role": role,
                                "path": str(path.resolve()),
                                "sha256": sha256(path),
                            }
                        )
                    saved_horse_count += horse_count
                    abnormal_result_count += race_abnormal_count

            saved = not missing_roles and importer_loaded
            prediction_linked = race_id in linked
            races.append(
                {
                    "race_id": race_id,
                    "race_number": race_number,
                    "saved": saved,
                    "horse_count": horse_count,
                    "abnormal_result_count": race_abnormal_count,
                    "prediction_linked": prediction_linked,
                    "observation_only": saved and not prediction_linked,
                }
            )
            if missing_roles:
                missing.append({"race_id": race_id, "missing_files": missing_roles})

        saved_races = [row for row in races if row["saved"]]
        prediction_linked_count = sum(row["saved"] and row["prediction_linked"] for row in races)
        observation_only_count = sum(row["observation_only"] for row in races)
        complete = len(saved_races) == len(expected_race_ids) and not missing
        timestamp = generated_at or datetime.now(timezone.utc).isoformat()

        return {
            "schema_version": SCHEMA_VERSION,
            "population_schema_version": POPULATION_SCHEMA_VERSION,
            "population_id": f"OBS_{race_date}_{course.upper()}_ALL",
            "population_type": "OBSERVATION_ONLY",
            "date": race_date,
            "racecourse": course,
            "prediction_linked": False,
            "baseline_membership": "EXCLUDED",
            "production_evidence": "NO",
            "kpi_eligible": "NO",
            "source": source,
            "generated_at": timestamp,
            "expected_race_count": len(expected_race_ids),
            "saved_race_count": len(saved_races),
            "saved_horse_count": saved_horse_count,
            "prediction_linked_race_count": prediction_linked_count,
            "observation_only_race_count": observation_only_count,
            "result_importer_prediction_id": None,
            "result_importer_loaded_race_count": importer_loaded_count,
            "completeness_status": "COMPLETE" if complete else "INCOMPLETE",
            "expected_race_ids": expected_race_ids,
            "missing_race_list": missing,
            "abnormal_result_count": abnormal_result_count,
            "races": races,
            "files": files,
        }

    def save(self, manifest: dict, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path
