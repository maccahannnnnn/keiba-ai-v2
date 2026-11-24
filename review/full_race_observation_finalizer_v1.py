"""Finalize the approved TARGET historical sample as Observation-only data.

The runner is fail-closed and idempotent. It never overwrites an existing
result file: existing pairs are reused, and only paths absent at preflight are
created from the validated/staged TARGET split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from review.observation_intake import ObservationManifestBuilder
from review.observation_manifest_validator import ObservationManifestValidator
from review.target_bulk_result_intake import TargetBulkResultSplitter


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/target/scehema_samples/テスト３.csv"
RESULT_ROOT = ROOT / "data/results"
CANONICAL_RESULT = ROOT / "reports/target_bulk_canonical_comparison_v1/target_bulk_canonical_comparison_result_v1.json"
HUMAN_EVIDENCE = ROOT / "reports/target_bulk_human_review_v1/target_bulk_human_review_cells_v1.csv"
OUTPUT = ROOT / "reports/full_race_observation_finalization_v1"
STAGE = OUTPUT / "stage"
MANIFEST_ROOT = OUTPUT / "manifests"
EXPECTED_RAW_SHA = "9264844e79c99e2e8f06a39116b4599bf5f8722e83b4059be689041069b65336"
EXPECTED_SCHEMA_SHA = "54ce8fe71652daeadadee46397b115cb8ea2377a3c24e2f32060d5de7d6b5a88"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class FullRaceObservationFinalizerV1:
    def preflight(self) -> dict:
        if sha(RAW) != EXPECTED_RAW_SHA:
            raise RuntimeError("RAW_SHA_MISMATCH")
        canonical = json.loads(CANONICAL_RESULT.read_text(encoding="utf-8"))
        if (
            canonical.get("file_count") != 50
            or canonical.get("conflict_stop_count") != 0
            or canonical.get("taxonomy_counts", {}).get("TRUE_CONFLICT") != 0
            or canonical.get("taxonomy_counts", {}).get("UNDETERMINED") != 0
            or canonical.get("file_status_counts") != {"OBSERVATION_ACCEPTABLE": 50}
        ):
            raise RuntimeError("CANONICAL_RECONCILIATION_NOT_FINAL")
        if STAGE.exists():
            raise RuntimeError("STAGE_ALREADY_EXISTS")
        staged = TargetBulkResultSplitter().stage(RAW, STAGE)
        if staged["source_sha256"] != EXPECTED_RAW_SHA or staged["schema_sha256"] != EXPECTED_SCHEMA_SHA:
            raise RuntimeError("STAGED_PROVENANCE_MISMATCH")
        if (staged["row_count"], staged["race_count"], staged["split_file_count"], staged["target_result_adapter_complete_count"]) != (1146, 96, 192, 96):
            raise RuntimeError("STAGED_SAMPLE_COUNTS_MISMATCH")
        items = []
        existing_races, new_races = set(), set()
        for row in staged["split_files"]:
            source = Path(row["path"])
            destination = RESULT_ROOT / source.name
            exists = destination.is_file()
            if exists:
                existing_races.add(row["race_id"])
            else:
                new_races.add(row["race_id"])
            items.append({
                "race_id": row["race_id"], "role": row["role"], "staged_path": str(source),
                "staged_sha256": row["sha256"], "official_path": str(destination.resolve()),
                "preexisting": exists, "preexisting_sha256": sha(destination) if exists else None,
            })
        if existing_races & new_races:
            raise RuntimeError(f"PARTIAL_EXISTING_RACE_PAIR:{sorted(existing_races & new_races)}")
        if (len(existing_races), len(new_races), sum(row["preexisting"] for row in items)) != (25, 71, 50):
            raise RuntimeError("EXISTING_NEW_COUNTS_MISMATCH")
        return {"staged": staged, "items": items, "existing_races": existing_races, "new_races": new_races}

    def execute(self) -> dict:
        completed = OUTPUT / "full_race_observation_finalization_summary_v1.json"
        if completed.is_file():
            prior = json.loads(completed.read_text(encoding="utf-8"))
            provenance_path = OUTPUT / "full_race_observation_provenance_v1.json"
            if prior.get("status") != "PASS" or not provenance_path.is_file():
                raise RuntimeError("INCOMPLETE_PRIOR_FINALIZATION_STATE")
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            for row in provenance.get("files", []):
                path = Path(row["official_path"])
                if not path.is_file() or sha(path) != row["official_sha256"]:
                    raise RuntimeError(f"FINALIZED_RESULT_SHA_MISMATCH:{path}")
            prior["idempotent_revalidation"] = True
            prior["new_write_count_this_run"] = 0
            return prior
        preflight = self.preflight()
        created: list[Path] = []
        try:
            for row in preflight["items"]:
                if row["preexisting"]:
                    continue
                source, destination = Path(row["staged_path"]), Path(row["official_path"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with source.open("rb") as reader, destination.open("xb") as writer:
                        shutil.copyfileobj(reader, writer)
                except FileExistsError as exc:
                    raise RuntimeError(f"OVERWRITE_GUARD_TRIGGERED:{destination}") from exc
                created.append(destination)
                if sha(destination) != row["staged_sha256"]:
                    raise RuntimeError(f"PLACED_FILE_SHA_MISMATCH:{destination}")

            canonical = json.loads(CANONICAL_RESULT.read_text(encoding="utf-8"))
            canonical_by_key = {(row["race_id"], row["role"]): row for row in canonical["files"]}
            provenance_files = []
            for row in preflight["items"]:
                path = Path(row["official_path"])
                mode = "EXISTING_RESULT_REUSED" if row["preexisting"] else "NEW_BULK_RESULT_PLACED"
                record = {
                    **row, "placement_mode": mode, "official_sha256": sha(path),
                    "source_raw_sha256": EXPECTED_RAW_SHA, "schema_sha256": EXPECTED_SCHEMA_SHA,
                    "canonical_reconciliation": "NOT_APPLICABLE_NEW_FILE",
                }
                if row["preexisting"]:
                    checked = canonical_by_key.get((row["race_id"], row["role"]))
                    if not checked or checked["file_status"] != "OBSERVATION_ACCEPTABLE" or checked["official_sha256"] != record["official_sha256"]:
                        raise RuntimeError("EXISTING_CANONICAL_PROVENANCE_MISMATCH")
                    record["canonical_reconciliation"] = "OBSERVATION_ACCEPTABLE"
                provenance_files.append(record)

            generated_at = datetime.now().astimezone().isoformat()
            builder = ObservationManifestBuilder(RESULT_ROOT)
            validator = ObservationManifestValidator()
            manifests, validations = [], []
            dates_courses = sorted({(race_id.split("_")[1], race_id.split("_")[2]) for race_id in preflight["staged"]["race_ids"]})
            for date, course in dates_courses:
                manifest = builder.build(
                    date=date, racecourse=course, expected_race_numbers=range(1, 13),
                    prediction_linked_race_ids=(), generated_at=generated_at, source="TARGET_FRONTIER_JV",
                )
                manifest["target_bulk_source_sha256"] = EXPECTED_RAW_SHA
                manifest["target_bulk_schema_sha256"] = EXPECTED_SCHEMA_SHA
                manifest["target_bulk_provenance_path"] = str((OUTPUT / "full_race_observation_provenance_v1.json").resolve())
                manifest["human_review_evidence_path"] = str(HUMAN_EVIDENCE.resolve())
                manifest["historical_sample_classification"] = "OBSERVATION_ONLY_BASELINE_EXCLUDED_KPI_INELIGIBLE"
                validation = validator.validate(manifest)
                if validation["status"] != "PASS":
                    raise RuntimeError(f"OBSERVATION_MANIFEST_VALIDATION_FAILED:{manifest['population_id']}:{validation['reason_codes']}")
                manifest_path = MANIFEST_ROOT / f"{manifest['population_id'].lower()}_manifest_v1.json"
                builder.save(manifest, manifest_path)
                manifests.append({"population_id": manifest["population_id"], "path": str(manifest_path.resolve()), "sha256": sha(manifest_path), "manifest": manifest})
                validations.append({"population_id": manifest["population_id"], **validation})

            provenance = {
                "version": "FULL_RACE_OBSERVATION_PROVENANCE_V1", "generated_at": generated_at,
                "source_type": "TARGET_FRONTIER_JV", "raw_source_path": str(RAW.resolve()),
                "raw_source_sha256": EXPECTED_RAW_SHA, "schema_name": "TARGET_BULK_RESULT_SCHEMA_V1",
                "schema_version": "target_bulk_result_v1", "schema_sha256": EXPECTED_SCHEMA_SHA,
                "row_count": 1146, "race_count": 96, "file_count": 192,
                "existing_result_reused_race_count": 25, "new_result_placed_race_count": 71,
                "existing_result_overwrite_count": 0, "human_review_evidence_path": str(HUMAN_EVIDENCE.resolve()),
                "human_review_decision": "BULK_RESULT_CORRECT_5_OF_5_EXISTING_FILES_NOT_CORRECTED",
                "canonical_comparison_result_path": str(CANONICAL_RESULT.resolve()),
                "files": provenance_files,
            }
            _write_json(OUTPUT / "full_race_observation_provenance_v1.json", provenance)
            bundle = {
                "version": "FULL_RACE_OBSERVATION_FINALIZATION_V1", "status": "PASS",
                "raw_source_sha256": EXPECTED_RAW_SHA, "schema_sha256": EXPECTED_SCHEMA_SHA,
                "row_count": 1146, "race_count": 96, "horse_count": sum(item["manifest"]["saved_horse_count"] for item in manifests),
                "existing_result_reused_race_count": 25, "new_result_placed_race_count": 71,
                "new_result_placed_file_count": len(created), "existing_result_overwrite_count": 0,
                "population_count": len(manifests),
                "complete_population_count": sum(item["manifest"]["completeness_status"] == "COMPLETE" for item in manifests),
                "incomplete_population_count": sum(item["manifest"]["completeness_status"] == "INCOMPLETE" for item in manifests),
                "missing_race_list": [row for item in manifests for row in item["manifest"]["missing_race_list"]],
                "conflict_stop_count": 0, "human_review_evidence_preserved": True,
                "formal_observation_registered": True, "prediction_output_in_manifest_count": 0,
                "baseline_membership": "EXCLUDED", "kpi_eligible": "NO", "production_evidence": "NO",
                "manifests": [{key: item[key] for key in ("population_id", "path", "sha256")} for item in manifests],
                "validations": validations,
            }
            _write_json(OUTPUT / "full_race_observation_finalization_summary_v1.json", bundle)
            return bundle
        except Exception:
            for path in reversed(created):
                if path.is_file():
                    path.unlink()
            raise
        finally:
            shutil.rmtree(STAGE, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize approved TARGET full-race Observation sample")
    parser.add_argument("--execute", action="store_true", required=True)
    parser.parse_args()
    result = FullRaceObservationFinalizerV1().execute()
    print(json.dumps({key: result[key] for key in ("status", "race_count", "existing_result_reused_race_count", "new_result_placed_race_count", "population_count", "complete_population_count", "conflict_stop_count")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
