"""Freeze the pre-cutoff JOCKEY_TIER_ADDITIVE_V1 table.

Reads only top-level TARGET history fixtures through the Shadow-only parser.
It has no result/POST input and performs no Production, Replay, or Evaluator
execution.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.jockey_shadow_read_only_parser_v1 import parse_history_files

REPORTS = ROOT / "reports"
COLUMN_SPEC = REPORTS / "jockey_history_column_spec_v1.md"
TIER_SPEC = REPORTS / "jockey_tier_preregistered_spec_v1.md"
TABLE_JSON = REPORTS / "jockey_tier_table_v1.json"
TABLE_CSV = REPORTS / "jockey_tier_table_v1.csv"
MANIFEST = REPORTS / "jockey_tier_generation_manifest_v1.json"
CUTOFF_DATE = "2026-06-06"
MINIMUM_RIDES = 30


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files() -> list[Path]:
    return sorted((ROOT / "data" / "analysis").glob("*_horses.csv"))


def source_set_sha(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def stable_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def deduplicate(records: list[dict]) -> tuple[list[dict], dict]:
    groups = defaultdict(list)
    for record in records:
        groups[(record["history_date"], record["horse_name"])].append(record)
    collisions = [
        key for key, values in groups.items()
        if len({value["semantic_row"] for value in values}) != 1
    ]
    if collisions:
        raise RuntimeError(f"STABLE_KEY_COLLISION:{len(collisions)}")
    multiplicity = Counter(len(values) for values in groups.values())
    unique = [values[0] for values in groups.values()]
    return unique, {
        "raw_record_count": len(records),
        "deduplicated_record_count": len(unique),
        "duplicate_record_count": len(records) - len(unique),
        "keys_with_two_snapshots": multiplicity[2],
        "keys_with_three_or_more_snapshots": sum(count for size, count in multiplicity.items() if size >= 3),
        "maximum_snapshot_count": max(multiplicity),
        "stable_key_collision_count": 0,
    }


def build_table() -> tuple[list[dict], dict]:
    paths = source_files()
    records = parse_history_files(paths)
    unique, dedup_audit = deduplicate(records)
    eligible = [record for record in unique if record["history_date"] < CUTOFF_DATE]
    if any(record["history_date"] >= CUTOFF_DATE for record in eligible):
        raise RuntimeError("CUTOFF_VIOLATION")
    invalid_finish = [record for record in eligible if not record["finish_position"].isdigit()]
    if invalid_finish:
        raise RuntimeError(f"INVALID_FINISH_POSITION:{len(invalid_finish)}")
    base_top3_rate = sum(int(record["finish_position"]) <= 3 for record in eligible) / len(eligible)
    by_jockey = defaultdict(list)
    for record in eligible:
        by_jockey[record["jockey_name"]].append(record)
    table = []
    for jockey_name, rows in sorted(by_jockey.items()):
        rides = len(rows)
        top3_count = sum(int(row["finish_position"]) <= 3 for row in rows)
        rate = top3_count / rides
        if rides < MINIMUM_RIDES:
            tier, score, status = "UNKNOWN", 0, "TRACE_MINIMUM_RIDES_NOT_MET"
        elif rate >= base_top3_rate + 0.10:
            tier, score, status = "A", 5, "COMPLETE"
        elif rate >= base_top3_rate + 0.03:
            tier, score, status = "B", 2, "COMPLETE"
        elif rate >= base_top3_rate - 0.03:
            tier, score, status = "C", 0, "COMPLETE"
        else:
            tier, score, status = "D", -2, "COMPLETE"
        table.append({
            "jockey_name": jockey_name,
            "rides": rides,
            "top3_count": top3_count,
            "top3_rate": round(rate, 12),
            "tier": tier,
            "shadow_score": score,
            "status": status,
        })
    tier_counts = dict(sorted(Counter(row["tier"] for row in table).items()))
    raw_by_jockey = Counter(record["jockey_name"] for record in records)
    official_by_jockey = Counter(record["jockey_name"] for record in eligible)
    audit = {
        **dedup_audit,
        "fixture_file_count": len(paths),
        "fixture_set_sha256": source_set_sha(paths),
        "cutoff_date": CUTOFF_DATE,
        "cutoff_inclusive": False,
        "cutoff_eligible_record_count": len(eligible),
        "cutoff_excluded_record_count": len(unique) - len(eligible),
        "invalid_finish_count": 0,
        "raw_jockey_count": len(raw_by_jockey),
        "cutoff_jockey_count": len(official_by_jockey),
        "minimum_rides": MINIMUM_RIDES,
        "base_top3_rate": base_top3_rate,
        "tier_counts": tier_counts,
        "raw_distribution_reference": {
            "rides_30_plus": sum(count >= 30 for count in raw_by_jockey.values()),
            "rides_100_plus": sum(count >= 100 for count in raw_by_jockey.values()),
            "rides_50_99": sum(50 <= count <= 99 for count in raw_by_jockey.values()),
            "rides_30_49": sum(30 <= count <= 49 for count in raw_by_jockey.values()),
        },
        "official_cutoff_dedup_distribution": {
            "rides_30_plus": sum(count >= 30 for count in official_by_jockey.values()),
            "rides_100_plus": sum(count >= 100 for count in official_by_jockey.values()),
            "rides_50_99": sum(50 <= count <= 99 for count in official_by_jockey.values()),
            "rides_30_49": sum(30 <= count <= 49 for count in official_by_jockey.values()),
        },
    }
    return table, audit


def write_outputs(replace: bool = False) -> dict:
    table, audit = build_table()
    generated_at = datetime.now(timezone.utc).isoformat()
    table_sha = stable_hash(table)
    table_json = {
        "schema_version": "jockey_tier_table_v1",
        "generated_at": generated_at,
        "candidate_id": "JOCKEY_TIER_ADDITIVE_V1",
        "cutoff_date": CUTOFF_DATE,
        "minimum_rides": MINIMUM_RIDES,
        "base_top3_rate": audit["base_top3_rate"],
        "tier_thresholds": {
            "A": "base_top3_rate + 0.10",
            "B": "base_top3_rate + 0.03",
            "C_lower": "base_top3_rate - 0.03",
            "UNKNOWN": "rides < 30 or unseen",
        },
        "table_sha256": table_sha,
        "rows": table,
    }
    manifest = {
        "schema_version": "jockey_tier_generation_manifest_v1",
        "generated_at": generated_at,
        "cutoff_date": CUTOFF_DATE,
        **audit,
        "column_spec_sha256": sha256(COLUMN_SPEC),
        "preregistered_spec_sha256": sha256(TIER_SPEC),
        "parser_sha256": sha256(ROOT / "analysis" / "jockey_shadow_read_only_parser_v1.py"),
        "generation_code_sha256": sha256(Path(__file__)),
        "tier_table_sha256": table_sha,
        "result_or_post_input_used": False,
        "production_importer_changed": False,
        "tier_table_frozen_before_evaluation": True,
    }
    for path in (TABLE_JSON, TABLE_CSV, MANIFEST):
        if path.exists() and not replace:
            raise FileExistsError(path)
    TABLE_JSON.write_text(json.dumps(table_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with TABLE_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader(); writer.writerows(table)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"table_sha256": table_sha, "audit": audit}, ensure_ascii=False))
    return manifest


if __name__ == "__main__":
    write_outputs(replace="--replace-generated" in sys.argv)
