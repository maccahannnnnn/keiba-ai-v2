"""Fail-closed operational CLI for a future TARGET full-race raw CSV.

Unseen existing-result differences are never canonicalized automatically.
Only NEW files and byte-identical REUSE files may proceed; any conflict stops
before result placement.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from review.observation_intake import ObservationManifestBuilder
from review.observation_manifest_validator import ObservationManifestValidator
from review.target_bulk_result_intake import (
    TargetBulkIntakeError,
    TargetBulkResultSplitter,
    normalize_allowed_dates,
)


def _raw_paths(raw: str | Path | Sequence[str | Path]) -> list[Path]:
    if isinstance(raw, (str, Path)):
        return [Path(raw)]
    paths = [Path(path) for path in raw]
    if not paths:
        raise TargetBulkIntakeError("RAW_SOURCE_LIST_EMPTY")
    return paths


def _strict_iso_date_argument(value: str) -> str:
    try:
        normalize_allowed_dates([value])
    except TargetBulkIntakeError as exc:
        raise argparse.ArgumentTypeError("allowed date must be strict ISO YYYY-MM-DD") from exc
    return value


def _add_date_filter_audit(payload: dict, staged: dict) -> dict:
    if "date_filter_audit" in staged:
        payload.update(staged["date_filter_audit"])
        payload["raw_source_paths"] = staged.get("raw_source_paths", [staged["raw_path"]])
        payload["raw_source_sha256"] = staged.get(
            "raw_source_sha256",
            [{"path": staged["raw_path"], "sha256": staged["source_sha256"]}],
        )
    return payload


def _assert_processing_scope(staged: dict) -> None:
    audit = staged.get("date_filter_audit")
    if audit is None:
        return
    allowed = {value.replace("-", "") for value in audit["allowed_dates"]}
    downstream_ids = set(staged["race_ids"])
    downstream_ids.update(item["race_id"] for item in staged["split_files"])
    violations = sorted(race_id for race_id in downstream_ids if race_id.split("_")[1] not in allowed)
    if violations:
        raise TargetBulkIntakeError("DATE_FILTER_SCOPE_INVARIANT_VIOLATION", violations)


def run(
    raw: str | Path | Sequence[str | Path],
    output_root: str | Path,
    result_root: str | Path = "data/results",
    *,
    allowed_dates: Sequence[date | str] | None = None,
    execute: bool = True,
) -> dict:
    paths, out, official = _raw_paths(raw), Path(output_root), Path(result_root)
    stage = out / "stage"
    if out.exists() and any(out.iterdir()):
        raise RuntimeError("OUTPUT_ROOT_NOT_EMPTY")
    splitter = TargetBulkResultSplitter()
    if len(paths) == 1:
        staged = splitter.stage(paths[0], stage, allowed_dates=allowed_dates)
    else:
        staged = splitter.stage_many(paths, stage, allowed_dates=allowed_dates)
    _assert_processing_scope(staged)
    reconciliation = splitter.reconcile(staged, official)
    if "date_filter_audit" in staged:
        reconciliation["date_filter_audit"] = staged["date_filter_audit"]
    (out / "reconciliation_v1.json").write_text(json.dumps(reconciliation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if reconciliation["conflict_count"]:
        shutil.rmtree(stage, ignore_errors=True)
        result = {
            "status": "CONFLICT_STOP", "conflict_count": reconciliation["conflict_count"],
            "new_result_placed_file_count": 0, "formal_observation_registered": False,
            "conflicts": [row for row in reconciliation["files"] if row["reconciliation_status"] == "CONFLICT_STOP"],
        }
        if not execute:
            result["dry_run"] = True
        _add_date_filter_audit(result, staged)
        (out / "operation_summary_v1.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    if not execute:
        generated_at = datetime.now().astimezone().isoformat()
        provenance = splitter.build_provenance(staged, imported_at=generated_at)
        provenance["formal_observation_registered"] = False
        (out / "provenance_v1.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = {
            "status": "PASS",
            "dry_run": True,
            "row_count": staged["row_count"],
            "race_count": staged["race_count"],
            "new_result_placed_file_count": 0,
            "planned_new_file_count": sum(row["reconciliation_status"] == "NEW" for row in reconciliation["files"]),
            "reuse_file_count": sum(row["reconciliation_status"] == "REUSE" for row in reconciliation["files"]),
            "conflict_count": 0,
            "population_count": 0,
            "formal_observation_registered": False,
        }
        _add_date_filter_audit(result, staged)
        (out / "operation_summary_v1.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(stage, ignore_errors=True)
        return result

    created = []
    try:
        for row in reconciliation["files"]:
            if row["reconciliation_status"] == "REUSE":
                continue
            source, destination = Path(row["path"]), Path(row["official_path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as reader, destination.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            created.append(destination)
        generated_at = datetime.now().astimezone().isoformat()
        builder, validator = ObservationManifestBuilder(official), ObservationManifestValidator()
        populations = []
        for date, course in sorted({(x.split("_")[1], x.split("_")[2]) for x in staged["race_ids"]}):
            manifest = builder.build(
                date=date, racecourse=course, expected_race_numbers=range(1, 13),
                generated_at=generated_at, source="TARGET_FRONTIER_JV",
            )
            manifest["target_bulk_source_sha256"] = staged["source_sha256"]
            manifest["target_bulk_schema_sha256"] = staged["schema_sha256"]
            _add_date_filter_audit(manifest, staged)
            validation = validator.validate(manifest)
            if validation["status"] != "PASS":
                raise RuntimeError(f"OBSERVATION_MANIFEST_VALIDATION_FAILED:{manifest['population_id']}:{validation['reason_codes']}")
            path = out / "manifests" / f"{manifest['population_id'].lower()}_manifest_v1.json"
            builder.save(manifest, path)
            populations.append({"population_id": manifest["population_id"], "status": manifest["completeness_status"], "path": str(path.resolve())})
        provenance = splitter.build_provenance(staged, imported_at=generated_at)
        provenance["formal_observation_registered"] = True
        (out / "provenance_v1.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = {
            "status": "PASS", "row_count": staged["row_count"], "race_count": staged["race_count"],
            "new_result_placed_file_count": len(created), "reuse_file_count": sum(row["reconciliation_status"] == "REUSE" for row in reconciliation["files"]),
            "conflict_count": 0, "population_count": len(populations),
            "complete_population_count": sum(row["status"] == "COMPLETE" for row in populations),
            "incomplete_population_count": sum(row["status"] == "INCOMPLETE" for row in populations),
            "populations": populations, "formal_observation_registered": True,
        }
        _add_date_filter_audit(result, staged)
        (out / "operation_summary_v1.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    except Exception:
        for path in reversed(created):
            if path.is_file():
                path.unlink()
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fail-closed Full Race Observation intake")
    parser.add_argument("--raw", action="append", required=True, help="TARGET raw CSV path; repeat for multiple source files")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--result-root", default="data/results")
    parser.add_argument(
        "--allowed-date",
        action="append",
        type=_strict_iso_date_argument,
        help=(
            "strict ISO YYYY-MM-DD; repeat for multiple dates. Only requested dates are processed after full raw "
            "validation; a requested date missing from input stops the run. Omit to process every input date."
        ),
    )
    parser.add_argument("--execute", action="store_true", help="place allowed NEW results; omit for write-free dry-run")
    args = parser.parse_args()
    raw = args.raw[0] if len(args.raw) == 1 else args.raw
    result = run(raw, args.output_root, args.result_root, allowed_dates=args.allowed_date, execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
