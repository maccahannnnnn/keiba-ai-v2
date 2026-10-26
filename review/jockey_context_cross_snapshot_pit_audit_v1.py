"""PRE-only historical-jockey cross-snapshot PIT audit.

This audit deliberately reuses the EXP-025 source identity and the existing
adapter's historical-race identity.  It neither opens a target Result source
nor fits or runs a model.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review import exp025_offset_pl_raw_history_v1 as exp025
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


OUT = ROOT / "reports" / "jockey_context_cross_snapshot_pit_audit_v1"
EXP025_SOURCE_AUDIT = ROOT / "reports" / "exp025_offset_pl_raw_history_v1_retry1" / "source_identity_audit.json"
EXCLUDED_RACES = {
    "race_20260823_niigata_7R",
    "race_20261012_kyoto_8R",
}
APPRENTICE_MARKS = "▲△☆◇★◆"
EXPECTED_UNIQUE_HISTORY_RECORDS = 36_227
EXPECTED_COMPARISON_PAIRS = 80_363

# The 74-date, February--October source universe qualified in the final
# EXP-025 raw-history audit.  Listing it here prevents an accidental pickup
# of January or any subsequently acquired daily input.
EXPECTED_DATES = (
    "20260201", "20260207", "20260208", "20260210", "20260214", "20260215", "20260221", "20260222", "20260228",
    "20260301", "20260307", "20260308", "20260314", "20260315", "20260321", "20260322", "20260328", "20260329",
    "20260404", "20260405", "20260411", "20260412", "20260418", "20260419", "20260425", "20260426",
    "20260502", "20260503", "20260509", "20260510", "20260516", "20260517", "20260523", "20260524", "20260530", "20260531",
    "20260620", "20260621", "20260627", "20260628",
    "20260704", "20260705", "20260711", "20260712", "20260718", "20260719", "20260725", "20260726",
    "20260801", "20260802", "20260808", "20260809", "20260815", "20260816", "20260822", "20260823", "20260829", "20260830",
    "20260905", "20260906", "20260912", "20260913", "20260919", "20260920", "20260921", "20260926", "20260927",
    "20261003", "20261004", "20261010", "20261011", "20261012", "20261017", "20261018",
)

# These are existing contemporaneous PRE records, selected explicitly rather
# than by an auto-latest search.  10/12 references the original raw DS SHA in
# its approved temporary-filter manifest because the race exclusion happens
# after raw-source acquisition.
LATE_DS_AUTHORITY: dict[str, tuple[Path, str]] = {
    "20260919": (ROOT / "reports" / "daily_pre_prediction_20260919" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
    "20260920": (ROOT / "reports" / "daily_pre_prediction_20260920" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
    "20260921": (ROOT / "reports" / "daily_pre_analysis_20260921" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
    "20260926": (ROOT / "reports" / "daily_pre_analysis_20260926" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
    "20260927": (ROOT / "reports" / "daily_pre_analysis_20260927" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
    "20261003": (ROOT / "reports" / "daily_pre_analysis_20261003" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
    "20261004": (ROOT / "reports" / "daily_pre_analysis_20261004" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
    "20261010": (ROOT / "reports" / "daily_pre_analysis_20261010" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
    "20261011": (ROOT / "reports" / "20261011_official_pre_v1" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
    "20261012": (ROOT / "reports" / "20261012_official_pre_v1_retry4" / "filtered_source_manifest.json", "original_source_sha256.DS"),
    "20261017": (ROOT / "reports" / "daily_pre_analysis_20261017" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
    "20261018": (ROOT / "reports" / "daily_pre_analysis_20261018" / "current_frozen" / "input_manifest.json", "sources.DS.sha256"),
}


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


def normalize_jockey(value: Any) -> str:
    """The already-frozen formatting-only jockey normalization."""
    text = unicodedata.normalize("NFKC", str(value or "").strip())
    text = re.sub(r"[ \u3000]", "", text)
    return text.strip(APPRENTICE_MARKS)


def nested(value: dict[str, Any], path: str) -> str:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise Stop(f"STOP_AUTHORITY_FIELD_MISSING:{path}")
        current = current[part]
    if not isinstance(current, str) or len(current) != 64:
        raise Stop(f"STOP_AUTHORITY_SHA_INVALID:{path}")
    return current.lower()


def early_authority() -> dict[str, str]:
    data = json.loads(EXP025_SOURCE_AUDIT.read_text(encoding="utf-8"))
    records = data.get("inventory")
    if not isinstance(records, list):
        raise Stop("STOP_EXP025_SOURCE_AUDIT_SCHEMA")
    values = {
        str(item["date"]): str(item["sha256"]).lower()
        for item in records
        if item.get("kind") == "DS"
    }
    if len(values) != 62:
        raise Stop(f"STOP_EXP025_DS_AUTHORITY_SCOPE:{len(values)}")
    return values


def source_authority(date: str, ds_path: Path, early: dict[str, str]) -> dict[str, Any]:
    actual = sha(ds_path)
    if date in early:
        expected = early[date]
        source = EXP025_SOURCE_AUDIT
        authority = "EXP025_SOURCE_IDENTITY_AUDIT"
    else:
        source, field = LATE_DS_AUTHORITY[date]
        expected = nested(json.loads(source.read_text(encoding="utf-8")), field)
        authority = "CONTEMPORANEOUS_PRE_INPUT_MANIFEST"
    return {
        "date": date,
        "ds_path": str(ds_path.relative_to(ROOT)).replace("\\", "/"),
        "ds_sha256_actual": actual,
        "authority_artifact": str(source.relative_to(ROOT)).replace("\\", "/"),
        "authority_artifact_sha256": sha(source),
        "authority_type": authority,
        "ds_sha256_expected": expected,
        "match": actual == expected,
    }


def audit() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    adapter = TargetBulkPredictionInputAdapterV1()
    early = early_authority()
    authority_rows: list[dict[str, Any]] = []
    occurrences: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    stats: Counter[str] = Counter()
    date_order_violations: list[dict[str, str]] = []

    for date in EXPECTED_DATES:
        de_path, ds_path = exp025.source_path("DE", date), exp025.source_path("DS", date)
        de = exp025.read_source(de_path, 33)
        ds = exp025.read_source(ds_path, 50)
        authority_rows.append(source_authority(date, ds_path, early))
        ds_by_identity: dict[tuple[str, str, str], list[list[str]]] = defaultdict(list)
        for item in ds:
            ds_by_identity[(exp025.clean(item[16]), exp025.clean(item[44]), exp025.clean(item[46]))].append(item)

        for de_row in de:
            target_race_id = exp025.race_id(date, exp025.clean(de_row[1]), exp025.integer(de_row[2]))
            horse_number = exp025.integer(de_row[3])
            stats["raw_target_horses"] += 1
            if target_race_id in EXCLUDED_RACES:
                stats["excluded_target_horses"] += 1
                continue
            name = exp025.clean(de_row[7])
            sire = exp025.clean(de_row[16])
            maternal_grandsire = exp025.clean(de_row[20])
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
                stats["approved_20260906_name_exception"] += 1

            identity = (lookup_name, sire, maternal_grandsire)
            histories = ds_by_identity.get(identity)
            if not histories:
                raise Stop(f"STOP_HISTORY_IDENTITY_UNMATCHED:{date}:{target_race_id}:{horse_number}")
            # Exact existing adapter semantics: source order, valid completed
            # runs only, and no more than five historical races.
            for history in adapter.valid_history_rows(histories):
                history_date = exp025.ds_date(history)
                if history_date >= date:
                    date_order_violations.append({
                        "target_date": date,
                        "target_race_id": target_race_id,
                        "horse_number": str(horse_number),
                        "history_date": history_date,
                    })
                    continue
                history_race_id = adapter._race_id(history_date, exp025.clean(history[4]), exp025.integer(history[6]))
                # EXP-025's canonical DE identity is used for the durable key;
                # the one approved 09/06 spelling exception is lookup-only.
                key = (name, sire, maternal_grandsire, history_race_id)
                occurrences[key].append({
                    "snapshot_date": date,
                    "raw_jockey": str(history[19] or "").strip(),
                    "normalized_jockey": normalize_jockey(history[19]),
                    "history_date": history_date,
                    "history_race_id": history_race_id,
                })
            stats["included_target_horses"] += 1

    if date_order_violations:
        raise Stop(f"STOP_HISTORY_DATE_ORDER:{len(date_order_violations)}")
    if stats["raw_target_horses"] != 17_365 or stats["included_target_horses"] != 17_344:
        raise Stop(f"STOP_EXP025_TARGET_SCOPE:{stats['raw_target_horses']}/{stats['included_target_horses']}")
    if not all(row["match"] for row in authority_rows):
        raise Stop("STOP_DS_SOURCE_AUTHORITY_MISMATCH")

    comparison = Counter()
    mismatches: list[dict[str, Any]] = []
    duplicate_snapshot_occurrences = 0
    for key, values in occurrences.items():
        snapshots = [value["snapshot_date"] for value in values]
        duplicate_snapshot_occurrences += len(snapshots) - len(set(snapshots))
        for left, right in itertools.combinations(values, 2):
            comparison["comparison_pairs"] += 1
            left_norm, right_norm = left["normalized_jockey"], right["normalized_jockey"]
            if not left_norm and not right_norm:
                comparison["blank_blank"] += 1
            elif not left_norm or not right_norm:
                comparison["one_side_blank"] += 1
            else:
                comparison["both_populated"] += 1
            if left_norm == right_norm:
                comparison["exact_match_pairs"] += 1
            else:
                comparison["mismatch_pairs"] += 1
                mismatches.append({
                    "horse_name": key[0],
                    "sire": key[1],
                    "maternal_grandsire": key[2],
                    "historical_race_id": key[3],
                    "historical_race_date": left["history_date"],
                    "snapshot_date_a": left["snapshot_date"],
                    "snapshot_date_b": right["snapshot_date"],
                    "raw_jockey_a": left["raw_jockey"],
                    "raw_jockey_b": right["raw_jockey"],
                    "normalized_jockey_a": left_norm,
                    "normalized_jockey_b": right_norm,
                    "mismatch_kind": "ONE_SIDE_BLANK" if not left_norm or not right_norm else "POPULATED_VALUE_MISMATCH",
                })

    unique_records = len(occurrences)
    comparisons = comparison["comparison_pairs"]
    if unique_records != EXPECTED_UNIQUE_HISTORY_RECORDS or comparisons != EXPECTED_COMPARISON_PAIRS:
        raise Stop(f"STOP_EXP025_STRUCTURAL_REPRODUCTION:{unique_records}/{comparisons}")
    if duplicate_snapshot_occurrences:
        raise Stop(f"STOP_DUPLICATE_RECORD_WITHIN_SNAPSHOT:{duplicate_snapshot_occurrences}")

    populated_mismatch = sum(row["mismatch_kind"] == "POPULATED_VALUE_MISMATCH" for row in mismatches)
    if populated_mismatch:
        pit_status = "PIT_FAIL"
    elif comparison["one_side_blank"]:
        pit_status = "PIT_NOT_PROVEN"
    else:
        pit_status = "PIT_CONFIRMED_DEVELOPMENT"
    report = {
        "STATUS": "COMPLETE",
        "ROLE": "JOCKEY_CONTEXT_CROSS_SNAPSHOT_PIT_AUDIT",
        "PREVIOUS_ZERO_PAIR_ROOT_CAUSE": "VALUE_SET_CARDINALITY_BUG: the prior audit stored normalized jockey values in a set and treated set cardinality > 1 as a repeated record. Identical repeated values therefore collapsed to one set member and were incorrectly counted as zero repeated records / zero pairs.",
        "EXP025_IDENTITY_RULE": "APPROVED_NAME_SIRE_MATERNAL_GRANDSIRE_V1",
        "EXP025_MATCH_KEY_FIELDS": [
            "DE canonical horse_name (whitespace-normalized; 2026-09-06 approved lookup spelling exception is lookup-only)",
            "DE sire/father",
            "DE maternal_grandsire/dam_sire",
            "Adapter PastRace race_id = historical DS date + DS course + DS race_number",
        ],
        "EXP025_HISTORY_SELECTION": "TargetBulkPredictionInputAdapterV1.valid_history_rows: source order, completed/valid rows only, maximum five runs.",
        "EXP025_RECORD_COUNT": EXPECTED_UNIQUE_HISTORY_RECORDS,
        "EXP025_COMPARISON_PAIR_COUNT": EXPECTED_COMPARISON_PAIRS,
        "JOCKEY_UNIQUE_HISTORY_RECORDS": unique_records,
        "JOCKEY_COMPARISON_PAIRS": comparisons,
        "JOCKEY_EXACT_MATCH_PAIRS": comparison["exact_match_pairs"],
        "JOCKEY_MISMATCH_PAIRS": comparison["mismatch_pairs"],
        "JOCKEY_MATCH_RATE": comparison["exact_match_pairs"] / comparisons if comparisons else None,
        "JOCKEY_BLANK_BLANK": comparison["blank_blank"],
        "JOCKEY_ONE_SIDE_BLANK": comparison["one_side_blank"],
        "JOCKEY_BOTH_POPULATED": comparison["both_populated"],
        "DATE_ORDER_CHECK": "PASS",
        "SOURCE_AUTHORITY": "PASS",
        "SOURCE_AUTHORITY_DATES": len(authority_rows),
        "TARGET_HORSES_RAW": stats["raw_target_horses"],
        "TARGET_HORSES_AFTER_APPROVED_EXCLUSIONS": stats["included_target_horses"],
        "EXCLUDED_RACE_COUNT": len(EXCLUDED_RACES),
        "APPROVED_20260906_NAME_EXCEPTION_ROWS": stats["approved_20260906_name_exception"],
        "HISTORICAL_JOCKEY_FIELD": "DS column 20 (1-based): jockey of the completed historical race",
        "HISTORICAL_JOCKEY_NORMALIZATION": "Unicode NFKC -> remove ASCII/full-width whitespace -> strip only leading/trailing ▲△☆◇★◆; no aliases or manual merges.",
        "HISTORICAL_JOCKEY_PIT_STATUS": pit_status,
        "JOCKEY_PREREGISTRATION_PATH": "OPEN" if pit_status == "PIT_CONFIRMED_DEVELOPMENT" else "BLOCKED",
        "NEXT_SOURCE": None if pit_status == "PIT_CONFIRMED_DEVELOPMENT" else "PEDIGREE_CONDITION_INTERACTIONS",
        "TARGET_RESULT_ACCESS": 0,
        "MODEL_TRAINED": False,
        "LEDGER_CHANGED": False,
        "EXP024_CHANGED": False,
        "EXP025_CHANGED": False,
        "PRODUCTION_CHANGED": False,
        "GIT_CHANGED": False,
        "BLOCKING": 0 if pit_status == "PIT_CONFIRMED_DEVELOPMENT" else 1,
        "MAJOR": 0,
        "MINOR": [],
    }
    return report, authority_rows, mismatches


def run(output: Path = OUT) -> dict[str, Any]:
    if output.exists():
        raise Stop(f"STOP_OUTPUT_EXISTS:{output}")
    report, authority_rows, mismatches = audit()
    staging = Path(tempfile.mkdtemp(prefix=".jockey_cross_snapshot_", dir=output.parent))
    try:
        dump(staging / "summary.json", report)
        dump(staging / "source_authority.json", authority_rows)
        csvout(
            staging / "jockey_mismatches.csv",
            mismatches,
            ["horse_name", "sire", "maternal_grandsire", "historical_race_id", "historical_race_date", "snapshot_date_a", "snapshot_date_b", "raw_jockey_a", "raw_jockey_b", "normalized_jockey_a", "normalized_jockey_b", "mismatch_kind"],
        )
        (staging / "summary.md").write_text(
            "# JOCKEY_CONTEXT Historical Jockey Cross-Snapshot PIT Audit\n\n"
            "- Role: `JOCKEY_CONTEXT_CROSS_SNAPSHOT_PIT_AUDIT`\n"
            f"- EXP-025 structural reproduction: `{report['JOCKEY_UNIQUE_HISTORY_RECORDS']}` unique records / `{report['JOCKEY_COMPARISON_PAIRS']}` pairs.\n"
            f"- Normalized historical-jockey exact matches: `{report['JOCKEY_EXACT_MATCH_PAIRS']}`; mismatches: `{report['JOCKEY_MISMATCH_PAIRS']}`.\n"
            f"- PIT: `{report['HISTORICAL_JOCKEY_PIT_STATUS']}`.\n"
            "- Target Result access, model fitting/inference, and Git operations: `0` / `FALSE`.\n",
            encoding="utf-8",
        )
        hashes = {
            path.relative_to(staging).as_posix(): {"sha256": sha(path), "size": path.stat().st_size}
            for path in sorted(staging.iterdir()) if path.is_file()
        }
        dump(staging / "artifact_hashes.json", {"self_hash_excluded": True, "artifacts": hashes})
        staging.rename(output)
        return report
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, sort_keys=True, indent=2))
