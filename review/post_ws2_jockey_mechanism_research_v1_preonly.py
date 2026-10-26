"""POST_WS2 JOCKEY mechanism research V1: PRE-only pool and coverage audit.

This script has one purpose: materialize the human-approved, point-in-time
historical jockey ride pool and describe its PRE-only coverage. It deliberately
does not calculate jockey success rates, JOCKEY_TOP3_LIFT, any coefficient,
prediction, or performance metric. No target Result source is opened.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review import exp025_offset_pl_raw_history_v1 as exp025
from review import jockey_context_cross_snapshot_pit_audit_v1 as jockey_pit
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


OUT = ROOT / "reports" / "post_ws2_jockey_mechanism_research_v1_retry1"
EXPECTED_RAW_TARGET_ROWS = 17_365
EXPECTED_TARGET_ROWS = 17_344
APPROVED_IDENTITY = "APPROVED_NAME_SIRE_MATERNAL_GRANDSIRE_V1"
HISTORY_SELECTION = (
    "TargetBulkPredictionInputAdapterV1.valid_history_rows: source order, "
    "completed/valid rows only, maximum five runs."
)
EVALUATION_CUTOFF = "20260913"


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def dump(path: Path, value: Any) -> None:
    path.write_text(canonical(value), encoding="utf-8")


def csvout(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def quantiles(values: list[int]) -> dict[str, float]:
    if not values:
        raise Stop("STOP_EMPTY_PRIOR_RIDE_POPULATION")
    ordered = sorted(values)

    def interpolate(q: float) -> float:
        if len(ordered) == 1:
            return float(ordered[0])
        position = (len(ordered) - 1) * q
        low, high = math.floor(position), math.ceil(position)
        if low == high:
            return float(ordered[low])
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {f"p{int(q * 100):02d}": interpolate(q) for q in (0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1)}


def bucket(count: int) -> str:
    if count == 0:
        return "0"
    if count <= 4:
        return "1-4"
    if count <= 9:
        return "5-9"
    if count <= 19:
        return "10-19"
    if count <= 49:
        return "20-49"
    if count <= 99:
        return "50-99"
    return "100+"


def target_and_snapshot_records() -> tuple[
    list[dict[str, Any]],
    dict[str, dict[tuple[str, str, str, str], dict[str, Any]]],
    list[dict[str, Any]],
    dict[str, int],
]:
    """Read only DG/DE/DS, applying precisely the existing approved scope."""
    adapter = TargetBulkPredictionInputAdapterV1()
    early_authority = jockey_pit.early_authority()
    targets: list[dict[str, Any]] = []
    snapshot_records: dict[str, dict[tuple[str, str, str, str], dict[str, Any]]] = {}
    authority_rows: list[dict[str, Any]] = []
    stats: Counter[str] = Counter()

    for date in jockey_pit.EXPECTED_DATES:
        de_path, ds_path = exp025.source_path("DE", date), exp025.source_path("DS", date)
        de = exp025.read_source(de_path, 33)
        ds = exp025.read_source(ds_path, 50)
        authority = jockey_pit.source_authority(date, ds_path, early_authority)
        authority_rows.append(authority)
        if not authority["match"]:
            raise Stop(f"STOP_DS_SOURCE_AUTHORITY_MISMATCH:{date}")

        by_lookup_identity: dict[tuple[str, str, str], list[list[str]]] = defaultdict(list)
        for row in ds:
            by_lookup_identity[
                (exp025.clean(row[16]), exp025.clean(row[44]), exp025.clean(row[46]))
            ].append(row)

        records: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for de_row in de:
            venue, race_number = exp025.clean(de_row[1]), exp025.integer(de_row[2])
            horse_number = exp025.integer(de_row[3])
            if race_number is None or horse_number is None:
                raise Stop(f"STOP_TARGET_RACE_OR_HORSE_NUMBER:{date}")
            target_race_id = exp025.race_id(date, venue, race_number)
            stats["raw_target_rows"] += 1
            if target_race_id in jockey_pit.EXCLUDED_RACES:
                stats["excluded_target_rows"] += 1
                continue

            name = exp025.clean(de_row[7])
            sire = exp025.clean(de_row[16])
            maternal_grandsire = exp025.clean(de_row[20])
            canonical_identity = (name, sire, maternal_grandsire)
            lookup_name = name
            if (
                date == exp025.KNOWN_20260906["date"]
                and target_race_id == exp025.KNOWN_20260906["race_id"]
                and horse_number == exp025.KNOWN_20260906["horse_number"]
                and name == exp025.KNOWN_20260906["de_name"]
            ):
                if exp025.clean(de_row[18]) != exp025.KNOWN_20260906["registration_id"]:
                    raise Stop("STOP_20260906_EXCEPTION_SCOPE")
                lookup_name = exp025.KNOWN_20260906["ds_name"]
                stats["approved_20260906_name_exception_rows"] += 1

            history_rows = by_lookup_identity.get((lookup_name, sire, maternal_grandsire))
            if not history_rows:
                raise Stop(f"STOP_HISTORY_IDENTITY_UNMATCHED:{date}:{target_race_id}:{horse_number}")
            targets.append(
                {
                    "date": date,
                    "month": date[:6],
                    "race_id": target_race_id,
                    "horse_number": horse_number,
                    "horse_name": name,
                    "registration_id": exp025.clean(de_row[18]),
                    "current_jockey_raw": str(de_row[10] or "").strip(),
                    "current_jockey_normalized": jockey_pit.normalize_jockey(de_row[10]),
                    "horse_identity": canonical_identity,
                }
            )
            stats["included_target_rows"] += 1

            # Exact adapter boundary. The historical finish field is read only
            # to identify a completed/valid row; it is never aggregated here.
            for history in adapter.valid_history_rows(history_rows):
                history_date = exp025.ds_date(history)
                if history_date >= date:
                    raise Stop(
                        f"STOP_HISTORY_DATE_NOT_STRICTLY_BEFORE_SNAPSHOT:{date}:{history_date}"
                    )
                history_race_id = adapter._race_id(
                    history_date, exp025.clean(history[4]), exp025.integer(history[6])
                )
                key = (*canonical_identity, history_race_id)
                record = {
                    "horse_identity": canonical_identity,
                    "historical_race_id": history_race_id,
                    "historical_race_date": history_date,
                    "historical_jockey_raw": str(history[19] or "").strip(),
                    "historical_jockey_normalized": jockey_pit.normalize_jockey(history[19]),
                }
                existing = records.get(key)
                if existing is not None and existing != record:
                    raise Stop(f"STOP_DUPLICATE_RECORD_WITHIN_SNAPSHOT:{date}:{history_race_id}")
                records[key] = record
        snapshot_records[date] = records

    if stats["raw_target_rows"] != EXPECTED_RAW_TARGET_ROWS:
        raise Stop(f"STOP_RAW_TARGET_SCOPE:{stats['raw_target_rows']}")
    if stats["included_target_rows"] != EXPECTED_TARGET_ROWS:
        raise Stop(f"STOP_TARGET_SCOPE:{stats['included_target_rows']}")
    if stats["excluded_target_rows"] != EXPECTED_RAW_TARGET_ROWS - EXPECTED_TARGET_ROWS:
        raise Stop(f"STOP_EXCLUSION_SCOPE:{stats['excluded_target_rows']}")
    if stats["approved_20260906_name_exception_rows"] != 1:
        raise Stop(f"STOP_20260906_EXCEPTION_COUNT:{stats['approved_20260906_name_exception_rows']}")
    return targets, snapshot_records, authority_rows, dict(stats)


def build_coverage() -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    targets, snapshot_records, authority_rows, source_stats = target_and_snapshot_records()
    targets_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        targets_by_date[str(target["date"])].append(target)

    known_records: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    records_by_jockey: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
    records_by_horse_jockey: dict[
        tuple[tuple[str, str, str], str], set[tuple[str, str, str, str]]
    ] = defaultdict(set)
    exposures: list[dict[str, Any]] = []
    historical_date_violations = 0

    for date in jockey_pit.EXPECTED_DATES:
        # snapshot_date == target_date is deliberately included, per the frozen
        # predicate snapshot_date <= target_date.
        for key, record in snapshot_records[date].items():
            existing = known_records.get(key)
            if existing is not None and existing != record:
                raise Stop(f"STOP_CROSS_SNAPSHOT_RECORD_CONFLICT:{date}:{key[-1]}")
            known_records[key] = record
            jockey = str(record["historical_jockey_normalized"])
            if jockey:
                records_by_jockey[jockey].add(key)
                records_by_horse_jockey[(record["horse_identity"], jockey)].add(key)

        for target in targets_by_date[date]:
            current_jockey = str(target["current_jockey_normalized"])
            available = records_by_jockey.get(current_jockey, set()) if current_jockey else set()
            own = (
                records_by_horse_jockey.get((target["horse_identity"], current_jockey), set())
                if current_jockey
                else set()
            )
            eligible_keys = available - own
            if any(str(known_records[key]["historical_race_date"]) >= date for key in eligible_keys):
                historical_date_violations += 1
            exposures.append(
                {
                    "date": target["date"],
                    "month": target["month"],
                    "race_id": target["race_id"],
                    "horse_number": target["horse_number"],
                    "horse_name": target["horse_name"],
                    "registration_id": target["registration_id"],
                    "current_jockey_raw": target["current_jockey_raw"],
                    "current_jockey_normalized": current_jockey,
                    "current_jockey_present": bool(current_jockey),
                    "prior_ride_count": len(eligible_keys),
                    "prior_ride_bucket": bucket(len(eligible_keys)),
                    "target_horse_rides_excluded": len(own),
                    "snapshot_date_constraint": "PASS",
                    "historical_date_constraint": "PASS",
                }
            )

    if historical_date_violations:
        raise Stop(f"STOP_HISTORICAL_DATE_CONSTRAINT:{historical_date_violations}")
    if len(exposures) != EXPECTED_TARGET_ROWS:
        raise Stop(f"STOP_EXPOSURE_SCOPE:{len(exposures)}")

    # The 74-date scope is the qualified PIT source universe. The frozen
    # experiment evaluates only the existing 62-date February--September-13
    # population, so all primary coverage outputs use that exact subset.
    all_exposures = exposures
    exposures = [row for row in all_exposures if str(row["date"]) <= EVALUATION_CUTOFF]
    if len({str(row["date"]) for row in exposures}) != 62:
        raise Stop(f"STOP_EVALUATION_DATE_SCOPE:{len({str(row['date']) for row in exposures})}")
    if not exposures:
        raise Stop("STOP_EVALUATION_TARGET_SCOPE_EMPTY")

    counts = [int(row["prior_ride_count"]) for row in exposures]
    current_present = sum(bool(row["current_jockey_present"]) for row in exposures)
    with_prior = sum(count > 0 for count in counts)
    zero_prior = sum(count == 0 for count in counts)
    distribution = [
        {
            "prior_ride_bucket": label,
            "target_rows": sum(row["prior_ride_bucket"] == label for row in exposures),
            "rate": sum(row["prior_ride_bucket"] == label for row in exposures) / len(exposures),
        }
        for label in ("0", "1-4", "5-9", "10-19", "20-49", "50-99", "100+")
    ]
    monthly: list[dict[str, Any]] = []
    for month in sorted({str(row["month"]) for row in exposures}):
        values = [row for row in exposures if row["month"] == month]
        ride_counts = [int(row["prior_ride_count"]) for row in values]
        monthly.append(
            {
                "month": month,
                "target_rows": len(values),
                "current_jockey_present": sum(bool(row["current_jockey_present"]) for row in values),
                "current_jockey_coverage_rate": sum(bool(row["current_jockey_present"]) for row in values) / len(values),
                "with_prior_ride_rows": sum(count > 0 for count in ride_counts),
                "with_prior_ride_rate": sum(count > 0 for count in ride_counts) / len(values),
                "zero_prior_ride_rows": sum(count == 0 for count in ride_counts),
                "zero_prior_ride_rate": sum(count == 0 for count in ride_counts) / len(values),
                "prior_ride_count_mean": mean(ride_counts),
                "prior_ride_count_median": quantiles(ride_counts)["p50"],
            }
        )
    summary = {
        "STATUS": "COMPLETE",
        "ROLE": "POST_WS2_JOCKEY_MECHANISM_RESEARCH_V1_PRE_ONLY_COVERAGE",
        "PIT_POOL_DEFINITION": "PASS",
        "IDENTITY_RULE": APPROVED_IDENTITY,
        "HISTORICAL_RECORD_IDENTITY": "horse_identity + historical_DS_race_id",
        "VALID_COMPLETED_HISTORY_SELECTION": HISTORY_SELECTION,
        "POOL_PREDICATE": "snapshot_date <= target_date AND historical_race_date < target_date",
        "TARGET_HORSE_RIDES_EXCLUDED_FROM_OWN_JOCKEY_PRIOR": True,
        "TARGET_ROWS": len(exposures),
        "EVALUATION_DATE_CUTOFF": EVALUATION_CUTOFF,
        "EVALUATION_DATE_COUNT": 62,
        "PIT_QUALIFIED_74_DATE_TARGET_ROWS": len(all_exposures),
        "RAW_TARGET_ROWS": source_stats["raw_target_rows"],
        "APPROVED_EXCLUDED_TARGET_ROWS": source_stats["excluded_target_rows"],
        "CURRENT_JOCKEY_COVERAGE": {
            "rows_with_current_jockey": current_present,
            "rows_without_current_jockey": len(exposures) - current_present,
            "rate": current_present / len(exposures),
        },
        "CURRENT_JOCKEY_WITH_PRIOR_RIDE_COVERAGE": {
            "rows": with_prior,
            "rate": with_prior / len(exposures),
        },
        "ZERO_PRIOR_RIDE_ROWS": zero_prior,
        "ZERO_PRIOR_RIDE_RATE": zero_prior / len(exposures),
        "PRIOR_RIDE_COUNT_MEAN": mean(counts),
        "PRIOR_RIDE_COUNT_MEDIAN": quantiles(counts)["p50"],
        "PRIOR_RIDE_COUNT_QUANTILES": quantiles(counts),
        "MONTHLY_COVERAGE_ROWS": len(monthly),
        "SNAPSHOT_DATE_CONSTRAINT": "PASS",
        "HISTORICAL_DATE_CONSTRAINT": "PASS",
        "SOURCE_AUTHORITY": "PASS",
        "SOURCE_AUTHORITY_DATES": len(authority_rows),
        "APPROVED_20260906_NAME_EXCEPTION_ROWS": source_stats["approved_20260906_name_exception_rows"],
        "TARGET_RESULT_ACCESS": 0,
        "JOCKEY_SUCCESS_RATE_CALCULATED": False,
        "MODEL_TRAINED": False,
        "MODEL_IMPLEMENTED": False,
        "PREDICTION_EXECUTED": False,
        "PERFORMANCE_EVALUATED": False,
        "EXP024_CHANGED": False,
        "EXP025_CHANGED": False,
        "PRODUCTION_CHANGED": False,
        "GIT_CHANGED": False,
    }
    return summary, exposures, all_exposures, distribution, monthly, authority_rows


def run(output: Path = OUT) -> dict[str, Any]:
    if output.exists():
        raise Stop(f"STOP_OUTPUT_EXISTS:{output}")
    summary, exposures, all_exposures, distribution, monthly, authority_rows = build_coverage()
    staging = Path(tempfile.mkdtemp(prefix=".post_ws2_jockey_", dir=output.parent))
    try:
        dump(staging / "summary.json", summary)
        dump(staging / "source_authority.json", authority_rows)
        csvout(
            staging / "prior_ride_coverage_by_target.csv",
            exposures,
            [
                "date", "month", "race_id", "horse_number", "horse_name", "registration_id",
                "current_jockey_raw", "current_jockey_normalized", "current_jockey_present",
                "prior_ride_count", "prior_ride_bucket", "target_horse_rides_excluded",
                "snapshot_date_constraint", "historical_date_constraint",
            ],
        )
        csvout(
            staging / "pit_qualified_74_date_prior_ride_coverage_by_target.csv",
            all_exposures,
            [
                "date", "month", "race_id", "horse_number", "horse_name", "registration_id",
                "current_jockey_raw", "current_jockey_normalized", "current_jockey_present",
                "prior_ride_count", "prior_ride_bucket", "target_horse_rides_excluded",
                "snapshot_date_constraint", "historical_date_constraint",
            ],
        )
        csvout(
            staging / "prior_ride_distribution.csv",
            distribution,
            ["prior_ride_bucket", "target_rows", "rate"],
        )
        csvout(
            staging / "monthly_coverage.csv",
            monthly,
            [
                "month", "target_rows", "current_jockey_present", "current_jockey_coverage_rate",
                "with_prior_ride_rows", "with_prior_ride_rate", "zero_prior_ride_rows",
                "zero_prior_ride_rate", "prior_ride_count_mean", "prior_ride_count_median",
            ],
        )
        (staging / "summary.md").write_text(
            "# POST_WS2 JOCKEY_MECHANISM_RESEARCH_V1 PRE-only coverage\n\n"
            f"- Primary evaluation target rows: {summary['TARGET_ROWS']} across "
            f"{summary['EVALUATION_DATE_COUNT']} dates through {summary['EVALUATION_DATE_CUTOFF']}.\n"
            f"- Supplementary PIT-qualified target rows: {summary['PIT_QUALIFIED_74_DATE_TARGET_ROWS']}.\n"
            f"- Current-jockey field coverage: {summary['CURRENT_JOCKEY_COVERAGE']['rate']:.6f}.\n"
            f"- Zero qualifying-prior rides: {summary['ZERO_PRIOR_RIDE_ROWS']} / "
            f"{summary['TARGET_ROWS']} ({summary['ZERO_PRIOR_RIDE_RATE']:.6f}).\n"
            f"- Prior-ride mean / median: {summary['PRIOR_RIDE_COUNT_MEAN']:.6f} / "
            f"{summary['PRIOR_RIDE_COUNT_MEDIAN']:.6f}.\n"
            "- Pool predicate: snapshot_date <= target_date AND historical_race_date < target_date.\n"
            "- Target-horse rides are removed from the target jockey prior.\n"
            "- No target Result access, jockey success-rate calculation, model fitting, prediction, or performance evaluation.\n",
            encoding="utf-8",
        )
        hashes = {
            path.relative_to(staging).as_posix(): {"sha256": sha(path), "size": path.stat().st_size}
            for path in sorted(staging.iterdir())
            if path.is_file()
        }
        dump(staging / "artifact_hashes.json", {"self_hash_excluded": True, "artifacts": hashes})
        staging.rename(output)
        return summary
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, sort_keys=True, indent=2))
