from __future__ import annotations

import csv
import ast
import hashlib
import importlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import review.reg009_retrospective_oos_result_cohort_generator_v1 as generator_module
from review.reg009_retrospective_oos_result_cohort_generator_v1 import (
    REQUIRED_ARTIFACTS,
    CohortGenerationError,
    Reg009RetrospectiveOOSResultCohortGeneratorV1,
    ResultCohortGeneratorConfig,
    _parse_int_literal,
    sha256_path,
)
from review.reg009_retrospective_oos_result_cohort_validator_v1 import (
    Reg009RetrospectiveOOSResultCohortValidatorV1,
)


FIXED_TIME = "2026-08-16T12:00:00+09:00"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_sha(path: Path, digest: str) -> None:
    path.write_text(f"{digest}  authority\n", encoding="utf-8")


class SafeTestDirectory:
    """TemporaryDirectory equivalent that preserves inherited Windows ACLs."""

    def __init__(self, parent: Path):
        for _ in range(16):
            candidate = parent / f".reg009_result_cohort_test_{secrets.token_hex(8)}"
            try:
                if os.name == "nt":
                    os.mkdir(candidate)
                else:
                    os.mkdir(candidate, 0o700)
            except FileExistsError:
                continue
            self.path = candidate
            self.name = str(candidate)
            return
        raise RuntimeError("SAFE_TEST_DIRECTORY_COLLISION_LIMIT_EXCEEDED")

    def cleanup(self) -> None:
        if self.path.exists():
            shutil.rmtree(self.path)


class SyntheticFixture:
    def __init__(self, root: Path, *, crosscheck: bool = False):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.schema = json.loads((Path(__file__).resolve().parents[1] / "docs" / "target_bulk_result_schema_v1.json").read_text(encoding="utf-8"))
        self.schema_path = root / "schema.json"
        _write_json(self.schema_path, self.schema)
        self.schema_sha_path = root / "schema.sha256"
        _write_sha(self.schema_sha_path, sha256_path(self.schema_path))

        self.authority = root / "authority.md"
        self.authority.write_text("ACTIVE\n", encoding="utf-8")
        self.frozen = root / "frozen.md"
        self.frozen.write_text("- status: FROZEN\n", encoding="utf-8")
        self.frozen_sha = root / "frozen.sha256"
        _write_sha(self.frozen_sha, sha256_path(self.frozen))
        self.generation = root / "generation.md"
        self.generation.write_text("- Status: APPROVED / FROZEN\n", encoding="utf-8")
        self.generation_sha = root / "generation.sha256"
        _write_sha(self.generation_sha, sha256_path(self.generation))

        self.rows: list[list[str]] = []
        self._add_race("20260718", "函館", 1, [1, 2, 3, 4])
        self._add_race("20260718", "函館", 2, [1, 2, 3, 4])
        self._add_race("20260719", "函館", 1, [1, 2, 3, 4])
        self._add_race("20260719", "函館", 2, [1, 2, 3, 4])
        self._add_race("20260720", "函館", 1, [1, 2, 3, 4])
        self.raw = root / "raw.csv"
        self.write_raw()

        day1, day2 = root / "daily1.json", root / "daily2.json"
        _write_json(day1, {"date": "20260718"})
        _write_json(day2, {"date": "20260719"})
        self.population = root / "population.json"
        pop = {
            "status": "TARGET_POPULATION_FIXED",
            "target_population_fixed": True,
            "inputs": [
                {"path": str(day1), "sha256": sha256_path(day1)},
                {"path": str(day2), "sha256": sha256_path(day2)},
            ],
            "all_races": [
                self._population_row("20260718", 1, "TARGET_POPULATION_INCLUDED", None),
                self._population_row("20260718", 2, "EXCLUDED_NEWCOMER", "NEWCOMER"),
                self._population_row("20260719", 1, "TARGET_POPULATION_INCLUDED", None),
                self._population_row("20260719", 2, "EXCLUDED_JUMP", "JUMP"),
            ],
            "existing_result_pairs": [],
        }
        self.crosscheck_files: list[Path] = []
        if crosscheck:
            race_file = root / "existing_race.csv"
            race_file.write_text("race\n1\n", encoding="cp932")
            horse_file = root / "existing_horse.csv"
            with horse_file.open("w", encoding="cp932", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([self.schema["ordered_columns"][22], self.schema["ordered_columns"][16], self.schema["ordered_columns"][23], self.schema["ordered_columns"][25]])
                for no in range(1, 5):
                    writer.writerow([no, f"Horse-20260718-1-{no}", no, 0])
            pop["existing_result_pairs"] = [{
                "canonical_race_id": "race_20260718_hakodate_1R",
                "race_level_result_path": str(race_file),
                "race_level_sha256": sha256_path(race_file),
                "horse_level_result_path": str(horse_file),
                "horse_level_sha256": sha256_path(horse_file),
            }]
            self.crosscheck_files = [race_file, horse_file]
        _write_json(self.population, pop)

        self.config = ResultCohortGeneratorConfig(
            authority_path=self.authority,
            authority_sha256=sha256_path(self.authority),
            frozen_spec_path=self.frozen,
            frozen_spec_sha_path=self.frozen_sha,
            frozen_spec_sha256=sha256_path(self.frozen),
            generation_spec_path=self.generation,
            generation_spec_sha_path=self.generation_sha,
            generation_spec_sha256=sha256_path(self.generation),
            schema_path=self.schema_path,
            schema_sha_path=self.schema_sha_path,
            schema_sha256=sha256_path(self.schema_path),
            population_path=self.population,
            population_sha256=sha256_path(self.population),
            raw_path=self.raw,
            raw_sha256=sha256_path(self.raw),
            conflict_root=root / "unused-conflict",
            expected_raw_row_count=20,
            expected_raw_race_count=5,
            expected_raw_date_count=3,
            expected_raw_venue_count=1,
            expected_population_all=4,
            expected_population_included=2,
            expected_population_newcomer=1,
            expected_population_jump=1,
            expected_crosscheck_races=1 if crosscheck else 0,
            expected_crosscheck_horses=4 if crosscheck else 0,
            verify_document_contracts=False,
            verify_conflict_diagnosis=False,
            verify_daily_summary_inputs=True,
        )

    def _add_race(self, date: str, venue: str, race_number: int, finishes: list[int], abnormal: list[int] | None = None) -> None:
        abnormal = abnormal or [0] * len(finishes)
        for horse_number, (finish, code) in enumerate(zip(finishes, abnormal), 1):
            row = [""] * 50
            row[0], row[1], row[2] = str(int(date[:4]) - 2000), str(int(date[4:6])), str(int(date[6:]))
            row[3], row[4], row[5], row[6] = "1", venue, "1", str(race_number)
            row[16] = f"Horse-{date}-{race_number}-{horse_number}"
            row[21], row[22], row[23], row[25] = str(len(finishes)), str(horse_number), str(finish), str(code)
            self.rows.append(row)

    @staticmethod
    def _population_row(date: str, race_number: int, status: str, exclusion: str | None) -> dict[str, object]:
        return {
            "target_race_key": f"{date}|函館|{race_number}",
            "canonical_race_id": f"race_{date}_hakodate_{race_number}R",
            "date": date,
            "venue_code": "02",
            "venue_ja": "函館",
            "venue_canonical": "hakodate",
            "meeting_number": 1,
            "meeting_day": 1,
            "race_number": race_number,
            "class_name": "TEST",
            "population_status": status,
            "exclusion_reason": exclusion,
        }

    def write_raw(self) -> None:
        with self.raw.open("w", encoding="cp932", newline="") as handle:
            csv.writer(handle).writerows(self.rows)

    def refresh_raw(self, **config_changes: object) -> None:
        self.write_raw()
        self.config = replace(self.config, raw_sha256=sha256_path(self.raw), **config_changes)

    def refresh_population(self, value: dict[str, object]) -> None:
        _write_json(self.population, value)
        self.config = replace(self.config, population_sha256=sha256_path(self.population))

    def enable_document_contracts(self) -> None:
        authority_sha = sha256_path(self.authority)
        self.frozen.write_text(
            "\n".join([
                "- status: FROZEN",
                "- human_approval: APPROVED",
                "- human_approval_date: 2026-08-14",
                "- production_status: HOLD",
                f"- constitution_sha256: `{authority_sha}`",
                "",
            ]),
            encoding="utf-8",
        )
        frozen_sha = sha256_path(self.frozen)
        _write_sha(self.frozen_sha, frozen_sha)
        self.generation.write_text(
            "\n".join([
                "- Status: `APPROVED / FROZEN`",
                "- Approved by: `Human`",
                "- Approved date: `2026-08-14`",
                "- Production status: `HOLD`",
                "- Registry change: `PROHIBITED`",
                "- Knowledge change: `PROHIBITED`",
                f"- Constitution SHA256: `{authority_sha}`",
                f"- Frozen Spec SHA256: `{frozen_sha}`",
                f"- Population Record SHA256: `{self.config.population_sha256}`",
                f"- Source raw SHA256: `{self.config.raw_sha256}`",
                "",
            ]),
            encoding="utf-8",
        )
        generation_sha = sha256_path(self.generation)
        _write_sha(self.generation_sha, generation_sha)
        self.config = replace(
            self.config,
            frozen_spec_sha256=frozen_sha,
            generation_spec_sha256=generation_sha,
            verify_document_contracts=True,
        )

    def refresh_frozen_contract(self) -> None:
        digest = sha256_path(self.frozen)
        _write_sha(self.frozen_sha, digest)
        self.config = replace(self.config, frozen_spec_sha256=digest)

    def refresh_generation_contract(self) -> None:
        digest = sha256_path(self.generation)
        _write_sha(self.generation_sha, digest)
        self.config = replace(self.config, generation_spec_sha256=digest)

    def enable_conflict_diagnosis(self) -> None:
        conflict = self.root / "conflict"
        conflict.mkdir()
        artifacts: dict[str, object] = {
            "summary.json": {
                "final_decision": "CONFLICT_DIAGNOSIS_COMPLETE",
                "race_count": self.config.expected_crosscheck_races,
                "file_count": self.config.expected_crosscheck_races * 2,
                "horse_row_count": self.config.expected_crosscheck_horses,
            },
            "frozen_spec_impact.json": {
                "race_count": self.config.expected_crosscheck_races,
                "horse_row_count": self.config.expected_crosscheck_horses,
                "horse_identity_mismatch_count": 0,
                "row_set_mismatch_count": 0,
                "valid_result_mismatch_count": 0,
                "actual_top3_mismatch_count": 0,
                "frozen_spec_decision_impact_race_count": 0,
                "all_selected_horses_uniquely_identifiable": True,
            },
            "file_comparison.json": {"file_count": self.config.expected_crosscheck_races * 2},
            "field_comparison.json": {"horse_row_count": self.config.expected_crosscheck_horses},
            "route_provenance.json": {"status": "PASS"},
            "safety.json": {"status": "PASS"},
            "report.md": "PASS\n",
        }
        for name, payload in artifacts.items():
            path = conflict / name
            if name.endswith(".json"):
                _write_json(path, payload)
            else:
                path.write_text(str(payload), encoding="utf-8")
        self.config = replace(self.config, conflict_root=conflict, verify_conflict_diagnosis=True)
        self.refresh_conflict_hashes()

    def refresh_conflict_hashes(self) -> None:
        conflict = self.config.conflict_root
        hashes = {
            path.name: sha256_path(path)
            for path in sorted(conflict.iterdir())
            if path.is_file() and path.name != "provenance.json"
        }
        _write_json(conflict / "provenance.json", {"artifact_sha256": hashes})

    def generator(self) -> Reg009RetrospectiveOOSResultCohortGeneratorV1:
        return Reg009RetrospectiveOOSResultCohortGeneratorV1(self.config)


class ResultCohortGeneratorV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = SafeTestDirectory(Path(__file__).resolve().parents[1])
        self.fx = SyntheticFixture(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_reason(self, code: str, action) -> None:
        with self.assertRaises(CohortGenerationError) as caught:
            action()
        self.assertEqual(code, caught.exception.reason_code)

    def assert_no_output_or_staging(self, output: Path) -> None:
        self.assertFalse(output.exists())
        self.assertEqual([], list(output.parent.glob(f".{output.name}.staging-*")))

    def generate(self, name: str = "out") -> Path:
        output = Path(self.temp.name) / name
        result = self.fx.generator().generate(output, generated_at=FIXED_TIME)
        self.assertEqual("PASS", result["status"])
        return output

    def test_01_input_preflight_passes(self) -> None:
        result = self.fx.generator().validate_inputs_only()
        self.assertEqual("PASS", result["status"])
        self.assertEqual(4, result["allowed_date_race_count"])

    def test_02_cp932_headerless_50_columns(self) -> None:
        with self.fx.raw.open("r", encoding="cp932", errors="strict", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertTrue(rows)
        self.assertTrue(all(len(row) == 50 for row in rows))
        self.assertNotEqual(self.fx.schema["ordered_columns"], rows[0])

    def test_03_rejects_49_columns(self) -> None:
        self.fx.rows[0].pop()
        self.fx.refresh_raw()
        self.assert_reason("COLUMN_COUNT_MISMATCH", self.fx.generator().validate_inputs_only)

    def test_04_rejects_51_columns(self) -> None:
        self.fx.rows[0].append("x")
        self.fx.refresh_raw()
        self.assert_reason("COLUMN_COUNT_MISMATCH", self.fx.generator().validate_inputs_only)

    def test_05_rejects_header(self) -> None:
        self.fx.rows.insert(0, list(self.fx.schema["ordered_columns"]))
        self.fx.refresh_raw(expected_raw_row_count=21)
        self.assert_reason("HEADER_PRESENT_NOT_ALLOWED", self.fx.generator().validate_inputs_only)

    def test_06_rejects_source_sha_mismatch(self) -> None:
        self.fx.config = replace(self.fx.config, raw_sha256="0" * 64)
        self.assert_reason("SOURCE_RAW_SHA256_MISMATCH", self.fx.generator().validate_inputs_only)

    def test_07_rejects_authority_sha_mismatch(self) -> None:
        self.fx.config = replace(self.fx.config, authority_sha256="0" * 64)
        self.assert_reason("AUTHORITY_SHA256_MISMATCH", self.fx.generator().validate_inputs_only)

    def test_08_non_whitelist_date_is_not_mapped(self) -> None:
        result = self.fx.generator().validate_inputs_only()
        self.assertEqual(4, result["allowed_date_race_count"])
        self.assertEqual(5, result["raw_race_count"])

    def test_09_missing_target_date_stops(self) -> None:
        self.fx.rows = [r for r in self.fx.rows if not (r[0] == "26" and r[1] == "7" and r[2] == "19")]
        self.fx.refresh_raw(expected_raw_row_count=12, expected_raw_race_count=3, expected_raw_date_count=2)
        self.assert_reason("TARGET_DATE_MISSING", self.fx.generator().validate_inputs_only)

    def test_10_missing_target_race_stops(self) -> None:
        self.fx.rows = [r for r in self.fx.rows if not (r[2] == "19" and r[6] == "2")]
        self.fx.refresh_raw(expected_raw_row_count=16, expected_raw_race_count=4)
        self.assert_reason("TARGET_RACE_MISSING", self.fx.generator().validate_inputs_only)

    def test_11_missing_horse_stops(self) -> None:
        self.fx.rows.pop(0)
        self.fx.refresh_raw(expected_raw_row_count=19)
        self.assert_reason("HORSE_MISSING_OR_FIELD_SIZE_MISMATCH", self.fx.generator().validate_inputs_only)

    def test_12_duplicate_horse_stops(self) -> None:
        self.fx.rows[1][22] = self.fx.rows[0][22]
        self.fx.rows[1][16] = self.fx.rows[0][16]
        self.fx.refresh_raw()
        self.assert_reason("DUPLICATE_HORSE", self.fx.generator().validate_inputs_only)

    def test_13_identity_collision_stops(self) -> None:
        self.fx.rows[1][22] = self.fx.rows[0][22]
        self.fx.refresh_raw()
        self.assert_reason("IDENTITY_COLLISION", self.fx.generator().validate_inputs_only)

    def test_14_ambiguous_horse_mapping_stops(self) -> None:
        self.fx.rows[1][16] = self.fx.rows[0][16]
        self.fx.refresh_raw()
        self.assert_reason("AMBIGUOUS_HORSE_MAPPING", self.fx.generator().validate_inputs_only)

    def test_15_unparseable_finish_stops(self) -> None:
        self.fx.rows[0][23] = "x"
        self.fx.refresh_raw()
        self.assert_reason("UNPARSEABLE_FINISH", self.fx.generator().validate_inputs_only)

    def test_16_unparseable_abnormal_status_stops(self) -> None:
        self.fx.rows[0][25] = "取消"
        self.fx.refresh_raw()
        self.assert_reason("UNKNOWN_OR_UNPARSEABLE_ABNORMAL_STATUS", self.fx.generator().validate_inputs_only)

    def test_17_normal_result_is_valid(self) -> None:
        output = self.generate()
        horses = json.loads((output / "horse_results.json").read_text(encoding="utf-8"))["records"]
        self.assertTrue(all(h["derived_valid_result"] for h in horses))

    def test_18_nonzero_statuses_are_invalid_without_code_names(self) -> None:
        for sequence, code in enumerate((1, 3, 4)):
            with self.subTest(nonzero_abnormal_code=code):
                fx = SyntheticFixture(Path(self.temp.name) / f"case{sequence}")
                fx.rows[0][25] = str(code)
                fx.rows[0][23] = "0"
                fx.rows[1][23], fx.rows[2][23], fx.rows[3][23] = "1", "2", "3"
                fx.refresh_raw()
                out = Path(self.temp.name) / f"out{sequence}"
                fx.generator().generate(out, generated_at=FIXED_TIME)
                record = json.loads((out / "horse_results.json").read_text(encoding="utf-8"))["records"][0]
                self.assertFalse(record["derived_valid_result"])
                self.assertFalse(record["derived_actual_top3"])
                self.assertEqual("NONZERO_ABNORMAL_STATUS", record["derivation_reason"])

    def test_19_normal_zero_finish_stops(self) -> None:
        self.fx.rows[0][23] = "0"
        self.fx.refresh_raw()
        self.assert_reason("NORMAL_STATUS_INVALID_FINISH", lambda: self.fx.generator().generate(Path(self.temp.name) / "out", generated_at=FIXED_TIME))

    def test_20_normal_finish_over_field_size_stops(self) -> None:
        self.fx.rows[0][23] = "5"
        self.fx.refresh_raw()
        self.assert_reason("NORMAL_STATUS_INVALID_FINISH", lambda: self.fx.generator().generate(Path(self.temp.name) / "out", generated_at=FIXED_TIME))

    def test_21_actual_top3_derivation(self) -> None:
        output = self.generate()
        horses = json.loads((output / "horse_results.json").read_text(encoding="utf-8"))["records"][:4]
        self.assertEqual([True, True, True, False], [h["derived_actual_top3"] for h in horses])

    def test_22_tie_113_is_accepted(self) -> None:
        self.fx.rows[0][23], self.fx.rows[1][23] = "1", "1"
        self.fx.refresh_raw()
        self.generate()

    def test_23_tie_1224_is_accepted(self) -> None:
        self.fx.rows[0][23], self.fx.rows[1][23], self.fx.rows[2][23], self.fx.rows[3][23] = "1", "2", "2", "4"
        self.fx.refresh_raw()
        self.generate()

    def test_24_invalid_skip_rank_stops(self) -> None:
        for index, rank in enumerate((1, 2, 4, 4)):
            self.fx.rows[index][23] = str(rank)
        self.fx.refresh_raw()
        self.assert_reason("INVALID_SKIP_RANK_SEQUENCE", lambda: self.fx.generator().generate(Path(self.temp.name) / "out", generated_at=FIXED_TIME))

    def test_25_population_reconciliation_is_exact(self) -> None:
        output = self.generate()
        doc = json.loads((output / "population_reconciliation.json").read_text(encoding="utf-8"))
        self.assertEqual((4, 2, 2), (doc["counts"]["all"], doc["counts"]["included"], doc["counts"]["excluded"]))

    def test_26_crosscheck_matches(self) -> None:
        fx = SyntheticFixture(Path(self.temp.name) / "crosscheck", crosscheck=True)
        result = fx.generator().generate(Path(self.temp.name) / "crosscheck-out", generated_at=FIXED_TIME)
        self.assertEqual("PASS", result["status"])

    def test_27_crosscheck_mismatch_stops(self) -> None:
        fx = SyntheticFixture(Path(self.temp.name) / "crosscheck", crosscheck=True)
        horse_file = fx.crosscheck_files[1]
        text = horse_file.read_text(encoding="cp932").replace("Horse-20260718-1-1", "Wrong")
        horse_file.write_text(text, encoding="cp932")
        pop = json.loads(fx.population.read_text(encoding="utf-8"))
        pop["existing_result_pairs"][0]["horse_level_sha256"] = sha256_path(horse_file)
        fx.refresh_population(pop)
        self.assert_reason("COHORT_VALIDATION_STOP", lambda: fx.generator().generate(Path(self.temp.name) / "crosscheck-out", generated_at=FIXED_TIME))

    def test_28_required_seven_artifacts_only(self) -> None:
        output = self.generate()
        self.assertEqual(sorted(REQUIRED_ARTIFACTS), sorted(p.name for p in output.iterdir()))

    def test_29_exclusive_create_refuses_existing_root(self) -> None:
        root = Path(self.temp.name) / "exists"
        root.mkdir()
        self.assert_reason("OUTPUT_ROOT_ALREADY_EXISTS", lambda: self.fx.generator().generate(root, generated_at=FIXED_TIME))

    def test_30_generation_is_deterministic(self) -> None:
        first, second = self.generate("first"), self.generate("second")
        for name in REQUIRED_ARTIFACTS:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)

    def test_31_validator_passes(self) -> None:
        output = self.generate()
        result = Reg009RetrospectiveOOSResultCohortValidatorV1(self.fx.config).validate(output)
        self.assertEqual("PASS", result["status"])

    def test_32_validator_detects_tamper(self) -> None:
        output = self.generate()
        with (output / "report.md").open("a", encoding="utf-8") as handle:
            handle.write("tamper\n")
        result = Reg009RetrospectiveOOSResultCohortValidatorV1(self.fx.config).validate(output)
        self.assertEqual(("FAIL", "ARTIFACT_SHA256_MISMATCH"), (result["status"], result["reason_code"]))

    def test_33_horse_records_preserve_raw_provenance(self) -> None:
        output = self.generate()
        record = json.loads((output / "horse_results.json").read_text(encoding="utf-8"))["records"][0]
        self.assertEqual(self.fx.config.raw_sha256, record["source_raw_sha256"])
        self.assertIsInstance(record["source_row_number"], int)
        self.assertIsNone(record["stable_source_horse_id"])

    def test_34_forbidden_evaluation_fields_are_absent(self) -> None:
        output = self.generate()
        text = (output / "horse_results.json").read_text(encoding="utf-8").lower()
        for forbidden in ("prediction", "buy", "decision", "shadow", "odds", "popularity", "target_mark"):
            self.assertNotIn(forbidden, text)

    def test_35_no_feature_flag_or_production_connection(self) -> None:
        output = self.generate()
        provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual((0, 0), (provenance["feature_flag_connection_count"], provenance["production_connection_count"]))

    def test_36_no_data_results_write_is_recorded(self) -> None:
        output = self.generate()
        provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(0, provenance["data_results_write_count"])

    def test_37_validate_only_writes_nothing(self) -> None:
        before = sorted(p.relative_to(self.fx.root) for p in self.fx.root.rglob("*"))
        self.fx.generator().validate_inputs_only()
        after = sorted(p.relative_to(self.fx.root) for p in self.fx.root.rglob("*"))
        self.assertEqual(before, after)

    def test_38_generated_at_is_required(self) -> None:
        self.assert_reason("GENERATED_AT_REQUIRED", lambda: self.fx.generator().generate(Path(self.temp.name) / "out", generated_at=""))

    def test_39_population_sha_mismatch_stops(self) -> None:
        self.fx.config = replace(self.fx.config, population_sha256="0" * 64)
        self.assert_reason("POPULATION_SHA256_MISMATCH", self.fx.generator().validate_inputs_only)

    def test_40_daily_summary_sha_mismatch_stops(self) -> None:
        pop = json.loads(self.fx.population.read_text(encoding="utf-8"))
        pop["inputs"][0]["sha256"] = "0" * 64
        self.fx.refresh_population(pop)
        self.assert_reason("DAILY_SUMMARY_SHA256_MISMATCH", self.fx.generator().validate_inputs_only)

    def test_41_schema_sha_mismatch_stops(self) -> None:
        self.fx.config = replace(self.fx.config, schema_sha256="0" * 64)
        self.assert_reason("SCHEMA_SHA256_MISMATCH", self.fx.generator().validate_inputs_only)

    def test_42_validator_is_read_only(self) -> None:
        output = self.generate()
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
        Reg009RetrospectiveOOSResultCohortValidatorV1(self.fx.config).validate(output)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
        self.assertEqual(before, after)

    def test_43_target_meeting_day_letter_b_maps_to_11(self) -> None:
        for row in self.fx.rows[:4]:
            row[5] = "B"
        pop = json.loads(self.fx.population.read_text(encoding="utf-8"))
        pop["all_races"][0]["meeting_day"] = 11
        self.fx.refresh_population(pop)
        self.fx.refresh_raw()
        self.fx.generator().validate_inputs_only()

    def test_44_unexpected_target_date_race_stops(self) -> None:
        self.fx._add_race("20260718", "函館", 3, [1, 2, 3, 4])
        moved = self.fx.rows[-4:]
        del self.fx.rows[-4:]
        self.fx.rows[8:8] = moved
        self.fx.refresh_raw(expected_raw_row_count=24, expected_raw_race_count=6)
        self.assert_reason("UNEXPECTED_RACE", self.fx.generator().validate_inputs_only)

    def test_45_noncontiguous_duplicate_race_stops(self) -> None:
        first_race_last_row = self.fx.rows.pop(3)
        self.fx.rows.insert(7, first_race_last_row)
        self.fx.refresh_raw()
        self.assert_reason("DUPLICATE_RACE", self.fx.generator().validate_inputs_only)

    def test_46_ambiguous_race_mapping_stops(self) -> None:
        pop = json.loads(self.fx.population.read_text(encoding="utf-8"))
        duplicate = dict(pop["all_races"][0])
        duplicate["canonical_race_id"] = "race_20260718_hakodate_duplicate_1R"
        pop["all_races"].append(duplicate)
        self.fx.refresh_population(pop)
        self.fx.config = replace(
            self.fx.config,
            expected_population_all=5,
            expected_population_included=3,
        )
        self.assert_reason("AMBIGUOUS_RACE_MAPPING", self.fx.generator().validate_inputs_only)

    def test_47_invalid_result_is_excluded_from_valid_count(self) -> None:
        self.fx.rows[0][25], self.fx.rows[0][23] = "3", "0"
        self.fx.rows[1][23], self.fx.rows[2][23], self.fx.rows[3][23] = "1", "2", "3"
        self.fx.refresh_raw()
        output = self.generate()
        races = json.loads((output / "race_results.json").read_text(encoding="utf-8"))["records"]
        race = next(r for r in races if r["canonical_race_id"] == "race_20260718_hakodate_1R")
        self.assertEqual((3, 1), (race["derived_valid_horse_count"], race["derived_invalid_horse_count"]))

    def test_48_generator_has_no_production_import(self) -> None:
        source_path = Path(__file__).resolve().parents[1] / "review" / "reg009_retrospective_oos_result_cohort_generator_v1.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        forbidden = ("analyzer", "evaluation", "main", "learning", "knowledge", "target_result_adapter")
        self.assertFalse(any(any(token in name.lower() for token in forbidden) for name in imported), imported)

    def test_49_module_import_has_no_formal_output_side_effect(self) -> None:
        module = importlib.import_module("review.reg009_retrospective_oos_result_cohort_generator_v1")
        formal = module.FORMAL_OUTPUT_ROOT
        before = formal.exists()
        completed = subprocess.run(
            [sys.executable, "-c", "import review.reg009_retrospective_oos_result_cohort_generator_v1"],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(before, formal.exists())

    def test_50_atomic_publish_has_no_staging_residue(self) -> None:
        output = self.generate()
        self.assertTrue(output.is_dir())
        self.assertEqual(sorted(REQUIRED_ARTIFACTS), sorted(p.name for p in output.iterdir()))
        self.assertEqual([], list(output.parent.glob(f".{output.name}.staging-*")))

    def test_51_partial_write_failure_cleans_staging(self) -> None:
        output = Path(self.temp.name) / "partial-output"
        generator = self.fx.generator()
        original = generator._write_artifact
        call_count = 0

        def fail_fourth(path: Path, data: bytes) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 4:
                raise OSError("intentional partial write failure")
            original(path, data)

        with mock.patch.object(generator, "_write_artifact", side_effect=fail_fourth):
            self.assert_reason("STAGING_WRITE_OR_PUBLISH_FAILED", lambda: generator.generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_52_staging_validation_failure_cleans_staging(self) -> None:
        output = Path(self.temp.name) / "validation-output"
        generator = self.fx.generator()
        with mock.patch.object(
            Reg009RetrospectiveOOSResultCohortValidatorV1,
            "validate",
            return_value={"status": "FAIL", "reason_code": "INTENTIONAL_TEST_FAILURE"},
        ):
            self.assert_reason("GENERATED_COHORT_VALIDATION_FAILED", lambda: generator.generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_53_publish_race_preserves_competing_output_and_cleans_staging(self) -> None:
        output = Path(self.temp.name) / "publish-race-output"
        generator = self.fx.generator()
        original = generator._atomic_publish

        def create_competing_output(staging: Path, destination: Path) -> None:
            destination.mkdir()
            (destination / "owner.txt").write_text("competing process", encoding="utf-8")
            original(staging, destination)

        with mock.patch.object(generator, "_atomic_publish", side_effect=create_competing_output):
            self.assert_reason("OUTPUT_ROOT_ALREADY_EXISTS_DURING_PUBLISH", lambda: generator.generate(output, generated_at=FIXED_TIME))
        self.assertEqual("competing process", (output / "owner.txt").read_text(encoding="utf-8"))
        self.assertEqual([], list(output.parent.glob(f".{output.name}.staging-*")))

    def test_54_retry_succeeds_after_partial_write_failure(self) -> None:
        output = Path(self.temp.name) / "retry-output"
        generator = self.fx.generator()
        original = generator._write_artifact
        call_count = 0

        def fail_once(path: Path, data: bytes) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise OSError("intentional one-shot failure")
            original(path, data)

        with mock.patch.object(generator, "_write_artifact", side_effect=fail_once):
            self.assert_reason("STAGING_WRITE_OR_PUBLISH_FAILED", lambda: generator.generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)
        result = generator.generate(output, generated_at=FIXED_TIME)
        self.assertEqual("PASS", result["status"])

    def test_55_frozen_spec_status_failure_stops_before_staging(self) -> None:
        self.fx.enable_document_contracts()
        self.fx.frozen.write_text(self.fx.frozen.read_text(encoding="utf-8").replace("status: FROZEN", "status: DRAFT"), encoding="utf-8")
        self.fx.refresh_frozen_contract()
        output = Path(self.temp.name) / "contract-output"
        self.assert_reason("FROZEN_SPEC_STATUS_MISMATCH", lambda: self.fx.generator().generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_56_generation_spec_status_failure_stops_before_staging(self) -> None:
        self.fx.enable_document_contracts()
        self.fx.generation.write_text(self.fx.generation.read_text(encoding="utf-8").replace("APPROVED / FROZEN", "DRAFT"), encoding="utf-8")
        self.fx.refresh_generation_contract()
        output = Path(self.temp.name) / "contract-output"
        self.assert_reason("GENERATION_SPEC_STATUS_MISMATCH", lambda: self.fx.generator().generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_57_generation_spec_cross_reference_failure_stops_before_staging(self) -> None:
        self.fx.enable_document_contracts()
        self.fx.generation.write_text(self.fx.generation.read_text(encoding="utf-8").replace(self.fx.config.raw_sha256, "0" * 64), encoding="utf-8")
        self.fx.refresh_generation_contract()
        output = Path(self.temp.name) / "contract-output"
        self.assert_reason("GENERATION_SPEC_CROSS_REFERENCE_MISMATCH", lambda: self.fx.generator().generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_58_frozen_human_approval_failure_stops_before_staging(self) -> None:
        self.fx.enable_document_contracts()
        self.fx.frozen.write_text(self.fx.frozen.read_text(encoding="utf-8").replace("human_approval: APPROVED", "human_approval: PENDING"), encoding="utf-8")
        self.fx.refresh_frozen_contract()
        output = Path(self.temp.name) / "contract-output"
        self.assert_reason("FROZEN_SPEC_HUMAN_APPROVAL_CONTRACT_MISMATCH", lambda: self.fx.generator().generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_59_generation_human_approval_failure_stops_before_staging(self) -> None:
        self.fx.enable_document_contracts()
        self.fx.generation.write_text(self.fx.generation.read_text(encoding="utf-8").replace("Approved by: `Human`", "Approved by: `Unknown`"), encoding="utf-8")
        self.fx.refresh_generation_contract()
        output = Path(self.temp.name) / "contract-output"
        self.assert_reason("GENERATION_SPEC_HUMAN_APPROVAL_CONTRACT_MISMATCH", lambda: self.fx.generator().generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def conflict_failure(self, filename: str, field: str, value: object, reason: str, *, remove: bool = False) -> None:
        self.fx.enable_conflict_diagnosis()
        path = self.fx.config.conflict_root / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        if remove:
            payload.pop(field)
        else:
            payload[field] = value
        _write_json(path, payload)
        self.fx.refresh_conflict_hashes()
        output = Path(self.temp.name) / "conflict-output"
        self.assert_reason(reason, lambda: self.fx.generator().generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_60_conflict_status_semantic_failure(self) -> None:
        self.conflict_failure("summary.json", "final_decision", "HOLD", "CONFLICT_DIAGNOSIS_STATUS_MISMATCH")

    def test_61_conflict_race_count_semantic_failure(self) -> None:
        self.conflict_failure("summary.json", "race_count", 99, "CONFLICT_DIAGNOSIS_RACE_COUNT_MISMATCH")

    def test_62_conflict_horse_count_semantic_failure(self) -> None:
        self.conflict_failure("summary.json", "horse_row_count", 99, "CONFLICT_DIAGNOSIS_HORSE_COUNT_MISMATCH")

    def test_63_conflict_identity_semantic_failure(self) -> None:
        self.conflict_failure("frozen_spec_impact.json", "horse_identity_mismatch_count", 1, "CONFLICT_DIAGNOSIS_IDENTITY_MISMATCH")

    def test_64_conflict_valid_result_semantic_failure(self) -> None:
        self.conflict_failure("frozen_spec_impact.json", "valid_result_mismatch_count", 1, "CONFLICT_DIAGNOSIS_VALID_RESULT_MISMATCH")

    def test_65_conflict_actual_top3_semantic_failure(self) -> None:
        self.conflict_failure("frozen_spec_impact.json", "actual_top3_mismatch_count", 1, "CONFLICT_DIAGNOSIS_ACTUAL_TOP3_MISMATCH")

    def test_66_conflict_frozen_decision_impact_semantic_failure(self) -> None:
        self.conflict_failure("frozen_spec_impact.json", "frozen_spec_decision_impact_race_count", 1, "CONFLICT_DIAGNOSIS_FROZEN_DECISION_IMPACT")

    def test_67_conflict_required_field_missing(self) -> None:
        self.conflict_failure("frozen_spec_impact.json", "valid_result_mismatch_count", None, "CONFLICT_DIAGNOSIS_REQUIRED_FIELD_MISSING", remove=True)

    def test_68_ascii_integer_literals_pass(self) -> None:
        for literal, expected in (("0", 0), ("1", 1), ("12", 12), ("+12", 12), ("-1", -1)):
            with self.subTest(literal=literal):
                self.assertEqual(expected, _parse_int_literal(literal, "INVALID", literal))

    def test_69_full_width_integer_literal_stops(self) -> None:
        self.fx.rows[0][23] = "１２"
        self.fx.refresh_raw()
        output = Path(self.temp.name) / "full-width-output"
        self.assert_reason("UNPARSEABLE_FINISH", lambda: self.fx.generator().generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_70_mixed_width_integer_literal_stops(self) -> None:
        self.fx.rows[0][23] = "1２"
        self.fx.refresh_raw()
        output = Path(self.temp.name) / "mixed-width-output"
        self.assert_reason("UNPARSEABLE_FINISH", lambda: self.fx.generator().generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_71_empty_row_stops_before_staging(self) -> None:
        self.fx.rows.insert(4, [""] * 50)
        self.fx.refresh_raw(expected_raw_row_count=21)
        output = Path(self.temp.name) / "empty-row-output"
        self.assert_reason("EMPTY_ROW_NOT_ALLOWED", lambda: self.fx.generator().generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_72_conflict_file_count_semantic_failure(self) -> None:
        self.conflict_failure("summary.json", "file_count", 99, "CONFLICT_DIAGNOSIS_FILE_COUNT_MISMATCH")

    def test_73_conflict_row_set_semantic_failure(self) -> None:
        self.conflict_failure("frozen_spec_impact.json", "row_set_mismatch_count", 1, "CONFLICT_DIAGNOSIS_IDENTITY_MISMATCH")

    def _new_staging(self, label: str) -> tuple[Reg009RetrospectiveOOSResultCohortGeneratorV1, Path, str, Path]:
        generator = self.fx.generator()
        parent = Path(self.temp.name)
        prefix = f".{label}.staging-"
        staging = generator._create_staging_directory(parent, prefix)
        return generator, parent, prefix, staging

    def test_74_windows_staging_does_not_use_tempfile_mkdtemp(self) -> None:
        if generator_module.os.name != "nt":
            self.skipTest("Windows-specific runtime test")
        with mock.patch.object(tempfile, "mkdtemp", side_effect=AssertionError("mkdtemp must not be used")):
            generator, parent, prefix, staging = self._new_staging("no-mkdtemp")
        self.assertTrue(staging.is_dir())
        generator._cleanup_staging(staging, parent, prefix)

    def test_75_windows_staging_omits_explicit_mode(self) -> None:
        if generator_module.os.name != "nt":
            self.skipTest("Windows-specific runtime test")
        real_mkdir = generator_module.os.mkdir
        calls: list[tuple[object, ...]] = []

        def capture(path: object, *args: object) -> None:
            calls.append(args)
            real_mkdir(path, *args)

        generator = self.fx.generator()
        parent = Path(self.temp.name)
        prefix = ".default-mode.staging-"
        with mock.patch.object(generator_module.os, "mkdir", side_effect=capture):
            staging = generator._create_staging_directory(parent, prefix)
        self.assertEqual([()], calls)
        generator._cleanup_staging(staging, parent, prefix)

    def test_76_windows_staging_is_writable_by_current_user(self) -> None:
        if generator_module.os.name != "nt":
            self.skipTest("Windows-specific runtime test")
        generator, parent, prefix, staging = self._new_staging("write")
        target = staging / "probe.txt"
        try:
            with target.open("xb") as handle:
                handle.write(b"REG009")
            self.assertEqual(6, target.stat().st_size)
        finally:
            if target.exists():
                target.unlink()
            generator._cleanup_staging(staging, parent, prefix)

    def test_77_windows_staging_is_listable_by_current_user(self) -> None:
        if generator_module.os.name != "nt":
            self.skipTest("Windows-specific runtime test")
        generator, parent, prefix, staging = self._new_staging("list")
        target = staging / "probe.txt"
        try:
            target.write_bytes(b"REG009")
            self.assertEqual(["probe.txt"], [item.name for item in staging.iterdir()])
        finally:
            if target.exists():
                target.unlink()
            generator._cleanup_staging(staging, parent, prefix)

    def test_78_windows_staging_is_readable_by_current_user(self) -> None:
        if generator_module.os.name != "nt":
            self.skipTest("Windows-specific runtime test")
        generator, parent, prefix, staging = self._new_staging("read")
        target = staging / "probe.txt"
        try:
            target.write_bytes(b"REG009")
            self.assertEqual(b"REG009", target.read_bytes())
        finally:
            if target.exists():
                target.unlink()
            generator._cleanup_staging(staging, parent, prefix)

    def test_79_windows_staging_and_file_are_deletable_by_current_user(self) -> None:
        if generator_module.os.name != "nt":
            self.skipTest("Windows-specific runtime test")
        generator, parent, prefix, staging = self._new_staging("delete")
        target = staging / "probe.txt"
        target.write_bytes(b"REG009")
        target.unlink()
        self.assertFalse(target.exists())
        generator._cleanup_staging(staging, parent, prefix)
        self.assertFalse(staging.exists())

    def test_80_posix_branch_uses_private_0700_mode(self) -> None:
        candidate = Path(self.temp.name) / "posix-staging"
        with mock.patch.object(generator_module.os, "mkdir") as mkdir:
            self.fx.generator()._mkdir_staging_candidate(candidate, platform_name="posix")
        mkdir.assert_called_once_with(candidate, 0o700)

    def test_81_staging_suffix_collision_retries(self) -> None:
        generator = self.fx.generator()
        parent = Path(self.temp.name)
        prefix = ".collision.staging-"
        first = parent / f"{prefix}{'0' * 16}"
        first.mkdir()
        with mock.patch.object(generator_module.secrets, "token_hex", side_effect=["0" * 16, "1" * 16]):
            staging = generator._create_staging_directory(parent, prefix, max_attempts=2)
        self.assertEqual(f"{prefix}{'1' * 16}", staging.name)
        generator._cleanup_staging(staging, parent, prefix)
        first.rmdir()

    def test_82_staging_collision_limit_is_structured_stop(self) -> None:
        generator = self.fx.generator()
        parent = Path(self.temp.name)
        prefix = ".collision-limit.staging-"
        collision = parent / f"{prefix}{'0' * 16}"
        collision.mkdir()
        try:
            with mock.patch.object(generator_module.secrets, "token_hex", return_value="0" * 16):
                self.assert_reason(
                    "STAGING_DIRECTORY_COLLISION_LIMIT_EXCEEDED",
                    lambda: generator._create_staging_directory(parent, prefix, max_attempts=2),
                )
        finally:
            collision.rmdir()

    def test_83_staging_mkdir_permission_error_is_structured_stop(self) -> None:
        generator = self.fx.generator()
        parent = Path(self.temp.name)
        with mock.patch.object(
            Reg009RetrospectiveOOSResultCohortGeneratorV1,
            "_mkdir_staging_candidate",
            side_effect=PermissionError("denied"),
        ):
            self.assert_reason(
                "STAGING_DIRECTORY_CREATE_FAILED",
                lambda: generator._create_staging_directory(parent, ".permission.staging-"),
            )

    def test_84_staging_suffix_path_validation_is_fail_closed(self) -> None:
        generator = self.fx.generator()
        with mock.patch.object(generator_module.secrets, "token_hex", return_value=r"..\outside"):
            self.assert_reason(
                "STAGING_DIRECTORY_PATH_INVALID",
                lambda: generator._create_staging_directory(Path(self.temp.name), ".unsafe.staging-"),
            )

    def test_85_staging_symlink_or_reparse_is_refused_and_cleaned(self) -> None:
        generator = self.fx.generator()
        parent = Path(self.temp.name)
        prefix = ".reparse.staging-"
        candidate = parent / f"{prefix}{'1' * 16}"
        original = Path.is_symlink

        def simulate_reparse(path: Path) -> bool:
            return path == candidate or original(path)

        with mock.patch.object(generator_module.secrets, "token_hex", return_value="1" * 16), mock.patch.object(
            Path, "is_symlink", autospec=True, side_effect=simulate_reparse
        ):
            self.assert_reason(
                "STAGING_DIRECTORY_REPARSE_POINT_REFUSED",
                lambda: generator._create_staging_directory(parent, prefix),
            )
        self.assertFalse(candidate.exists())

    def test_86_staging_parent_outside_allowed_parent_is_refused(self) -> None:
        generator = self.fx.generator()
        root = Path(self.temp.name)
        allowed, outside = root / "allowed", root / "outside"
        allowed.mkdir()
        outside.mkdir()
        candidate = outside / ".outside.staging-0000000000000000"
        candidate.mkdir()
        try:
            self.assert_reason(
                "STAGING_DIRECTORY_PATH_INVALID",
                lambda: generator._validate_staging_directory(candidate, allowed.resolve(), ".outside.staging-"),
            )
        finally:
            candidate.rmdir()
            outside.rmdir()
            allowed.rmdir()

    def test_87_new_staging_helper_preserves_atomic_publish(self) -> None:
        output = self.generate("v3-atomic-output")
        self.assertTrue(output.is_dir())
        self.assertEqual([], list(output.parent.glob(f".{output.name}.staging-*")))

    def test_88_new_staging_helper_cleans_write_failure(self) -> None:
        output = Path(self.temp.name) / "v3-write-failure"
        generator = self.fx.generator()
        with mock.patch.object(generator, "_write_artifact", side_effect=OSError("v3 write failure")):
            self.assert_reason("STAGING_WRITE_OR_PUBLISH_FAILED", lambda: generator.generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_89_new_staging_helper_cleans_validation_failure(self) -> None:
        output = Path(self.temp.name) / "v3-validation-failure"
        generator = self.fx.generator()
        with mock.patch.object(
            Reg009RetrospectiveOOSResultCohortValidatorV1,
            "validate",
            return_value={"status": "FAIL", "reason_code": "V3_TEST"},
        ):
            self.assert_reason("GENERATED_COHORT_VALIDATION_FAILED", lambda: generator.generate(output, generated_at=FIXED_TIME))
        self.assert_no_output_or_staging(output)

    def test_90_new_staging_helper_cleans_publish_conflict(self) -> None:
        output = Path(self.temp.name) / "v3-publish-conflict"
        generator = self.fx.generator()
        original = generator._atomic_publish

        def conflict(staging: Path, destination: Path) -> None:
            destination.mkdir()
            original(staging, destination)

        with mock.patch.object(generator, "_atomic_publish", side_effect=conflict):
            self.assert_reason("OUTPUT_ROOT_ALREADY_EXISTS_DURING_PUBLISH", lambda: generator.generate(output, generated_at=FIXED_TIME))
        self.assertEqual([], list(output.parent.glob(f".{output.name}.staging-*")))

    def test_91_new_staging_helper_allows_retry_after_failure(self) -> None:
        output = Path(self.temp.name) / "v3-retry-output"
        generator = self.fx.generator()
        with mock.patch.object(generator, "_write_artifact", side_effect=OSError("one shot")):
            self.assert_reason("STAGING_WRITE_OR_PUBLISH_FAILED", lambda: generator.generate(output, generated_at=FIXED_TIME))
        result = generator.generate(output, generated_at=FIXED_TIME)
        self.assertEqual("PASS", result["status"])

    def test_92_new_staging_helper_leaves_no_residue_after_success(self) -> None:
        output = self.generate("v3-no-residue")
        self.assertEqual([], list(output.parent.glob(f".{output.name}.staging-*")))


if __name__ == "__main__":
    unittest.main()
