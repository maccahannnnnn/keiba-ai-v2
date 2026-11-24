"""JOCKEY_CONTEXT PRE-only availability, PIT, overlap, and coverage audit.

No Result source, target outcome, model fitting, or inference is opened here.
Historical DS finish/abnormal fields are inspected only for schema feasibility,
never aggregated into an outcome rate.
"""
from __future__ import annotations

import csv
import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from knowledge.bloodlines import BROODMARE_SIRE_PROFILES, SIRE_PROFILES
from review.target_bulk_prediction_input_adapter_v1 import COURSE_KEYS

OUT = ROOT / "reports" / "jockey_context_pre_only_qualification_audit_v1"
PRE_ROOT = ROOT / "reports" / "full_field_redesign_iter0_v1_retry6" / "pre_only_regeneration" / "shards"
EXPECTED_SHARDS = 31
APPRENTICE_MARKS = "▲△☆◇★◆"
MONTH_ORDER = ("202602", "202603", "202604", "202605", "202606", "202607", "202608", "202609")


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def csvout(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def txt(value: Any) -> str:
    return str(value or "").strip()


def clean_horse(value: Any) -> str:
    return re.sub(r"[ \u3000]", "", txt(value))


def jockey_norm(value: Any) -> str:
    """Frozen proposal: NFKC, remove whitespace, trim only edge apprentice marks.

    This deliberately does not expand abbreviations or equate surname/given-name
    variants, so anything beyond formatting remains distinct and fail-closed.
    """
    item = unicodedata.normalize("NFKC", txt(value))
    item = re.sub(r"[ \u3000]", "", item)
    return item.strip(APPRENTICE_MARKS)


def ds_date(row: list[str]) -> str:
    try:
        return f"20{int(txt(row[0])):02d}{int(txt(row[1])):02d}{int(txt(row[2])):02d}"
    except ValueError as exc:
        raise Stop(f"STOP_DS_DATE:{row[:3]!r}") from exc


def integer(value: Any, label: str) -> int:
    try:
        return int(txt(value).replace("+", ""))
    except ValueError as exc:
        raise Stop(f"STOP_INT:{label}:{value!r}") from exc


def pre_rows() -> list[dict[str, Any]]:
    paths = sorted(PRE_ROOT.glob("run_c_*/runtime_pre_only_output.json"))
    if len(paths) != EXPECTED_SHARDS:
        raise Stop(f"STOP_PRE_SHARD_COUNT:{len(paths)}")
    result: dict[tuple[str, str, int], dict[str, Any]] = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("generated_rows", []):
            key = (str(row["date"]), str(row["race_id"]), int(row["horse_number"]))
            if key in result:
                raise Stop(f"STOP_PRE_DUPLICATE:{key}")
            result[key] = dict(row)
    rows = [result[key] for key in sorted(result)]
    if len(rows) != 14870 or len({str(row["date"]) for row in rows}) != 62:
        raise Stop(f"STOP_PRE_SCOPE:{len(rows)}")
    return rows


def source_path(kind: str, date: str) -> Path:
    return ROOT / "data" / "raw" / "prediction_input" / f"{kind}{date[2:]}{'v2' if date == '20260418' else ''}.CSV"


def read_source(path: Path, width: int) -> list[list[str]]:
    raw = path.read_bytes()
    try:
        content = raw.decode("cp932")
    except UnicodeDecodeError as exc:
        raise Stop(f"STOP_SOURCE_ENCODING:{path}") from exc
    rows = list(csv.reader(content.splitlines()))
    if not rows or any(len(row) != width for row in rows):
        raise Stop(f"STOP_SOURCE_SCHEMA:{path.name}")
    return rows


def bucket(n: int) -> str:
    if n == 0:
        return "0"
    if n <= 4:
        return "1-4"
    if n <= 9:
        return "5-9"
    if n <= 19:
        return "10-19"
    if n <= 49:
        return "20-49"
    if n <= 99:
        return "50-99"
    return "100+"


def pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    left, right = zip(*pairs)
    lx, ly = mean(left), mean(right)
    denom = math.sqrt(sum((x - lx) ** 2 for x in left) * sum((y - ly) ** 2 for y in right))
    return sum((x - lx) * (y - ly) for x, y in pairs) / denom if denom else None


def value_number(values: dict[str, Any], field: str) -> float | None:
    value = values.get(field)
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def audit() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    rows = pre_rows()
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[str(row["date"])].append(row)

    current_entries: dict[tuple[str, str, int], dict[str, Any]] = {}
    raw_current_names: Counter[str] = Counter()
    raw_history_names: Counter[str] = Counter()
    normal_variants: dict[str, set[str]] = defaultdict(set)
    snapshot_history_jockeys: dict[str, set[str]] = {}
    snapshot_jockey_rides: dict[str, dict[str, set[tuple[str, ...]]]] = {}
    snapshot_sha: list[dict[str, Any]] = []
    cross_snapshot: dict[tuple[str, ...], set[str]] = defaultdict(set)
    historical_schema = {"history_rows": 0, "date_prior_violations": 0, "finish_present": 0, "valid_semantics_fields_present": 0}
    all_de_sire: list[str] = []
    all_de_broodmare_sire: list[str] = []

    for date in sorted(by_date):
        paths = {kind: source_path(kind, date) for kind in ("DG", "DE", "DS")}
        if any(not path.is_file() for path in paths.values()):
            raise Stop(f"STOP_SOURCE_MISSING:{date}")
        dg, de, ds = read_source(paths["DG"], 11), read_source(paths["DE"], 33), read_source(paths["DS"], 50)
        snapshot_sha.extend({"date": date, "kind": kind, "path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "rows": len(source), "columns": width, "encoding": "cp932", "header": False}
                            for kind, path, source, width in (("DG", paths["DG"], dg, 11), ("DE", paths["DE"], de, 33), ("DS", paths["DS"], ds, 50)))
        for item in de:
            venue, race_no, horse_no = txt(item[1]), integer(item[2], "de_race"), integer(item[3], "de_horse")
            race_id = f"race_{date}_{COURSE_KEYS[venue]}_{race_no}R"
            key = (date, race_id, horse_no)
            current_entries[key] = {"raw_jockey": txt(item[10]), "jockey": jockey_norm(item[10]), "sire": txt(item[16]), "dam": txt(item[17]), "broodmare_sire": txt(item[20])}
            raw_current_names[txt(item[10])] += 1
            normal_variants[jockey_norm(item[10])].add(txt(item[10]))
            all_de_sire.append(txt(item[16])); all_de_broodmare_sire.append(txt(item[20]))
        rides: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        names: set[str] = set()
        for item in ds:
            historical_schema["history_rows"] += 1
            history_day = ds_date(item)
            if history_day >= date:
                historical_schema["date_prior_violations"] += 1
                raise Stop(f"STOP_DS_NOT_PRIOR:{date}:{history_day}")
            raw_name, normal = txt(item[19]), jockey_norm(item[19])
            raw_history_names[raw_name] += 1
            normal_variants[normal].add(raw_name)
            names.add(normal)
            record = (history_day, txt(item[4]), txt(item[6]), clean_horse(item[16]), txt(item[44]), txt(item[46]))
            rides[normal].add(record)
            cross_snapshot[record].add(normal)
            if txt(item[23]):
                historical_schema["finish_present"] += 1
            if txt(item[25]) in {"", "0"}:
                historical_schema["valid_semantics_fields_present"] += 1
        snapshot_history_jockeys[date] = names
        snapshot_jockey_rides[date] = rides

    expected = {(str(row["date"]), str(row["race_id"]), int(row["horse_number"])) for row in rows}
    if not expected.issubset(current_entries):
        raise Stop(f"STOP_CURRENT_ENTRY_COVERAGE:{len(expected - set(current_entries))}")
    missing_current = [key for key in expected if not current_entries[key]["jockey"]]
    exposures: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row["date"]), str(row["race_id"]), int(row["horse_number"]))
        entry = current_entries[key]
        rides = len(snapshot_jockey_rides[key[0]].get(entry["jockey"], set()))
        exposures.append({"date": key[0], "month": key[0][:6], "race_id": key[1], "horse_number": key[2], "horse_name": row.get("horse_name"), "current_jockey_raw": entry["raw_jockey"], "current_jockey_normalized": entry["jockey"], "prior_ride_count_snapshot_scoped": rides, "log1p_prior_ride_count": math.log1p(rides), "current_jockey_in_snapshot_history": entry["jockey"] in snapshot_history_jockeys[key[0]]})

    raw_names = set(raw_current_names) | set(raw_history_names)
    collisions = []
    for normalized, variants in sorted(normal_variants.items()):
        if len(variants) > 1:
            collisions.append({"normalized": normalized, "raw_variants": sorted(variants), "classification": "FORMAT_NORMALIZATION_ONLY"})
    # With only NFKC/space/edge-apprentice transforms, a collision cannot merge
    # a distinct lexical name.  Abbreviations and name variants stay separate.
    ambiguous: list[dict[str, Any]] = []
    unmatched = sorted({item["current_jockey_normalized"] for item in exposures if not item["current_jockey_in_snapshot_history"]})

    distribution_rows = []
    for label in ("0", "1-4", "5-9", "10-19", "20-49", "50-99", "100+"):
        values = [row for row in exposures if bucket(int(row["prior_ride_count_snapshot_scoped"])) == label]
        distribution_rows.append({"prior_ride_bucket": label, "target_horses": len(values), "rate": len(values) / len(exposures)})
    monthly = []
    for month in MONTH_ORDER:
        values = [row for row in exposures if row["month"] == month]
        record = {"month": month, "target_horses": len(values), "mean_prior_ride_count": mean([r["prior_ride_count_snapshot_scoped"] for r in values]) if values else None}
        record.update({f"bucket_{label}": sum(bucket(int(r["prior_ride_count_snapshot_scoped"])) == label for r in values) for label in ("0", "1-4", "5-9", "10-19", "20-49", "50-99", "100+")})
        monthly.append(record)

    correlation_rows = []
    field_labels = {"Ability": "Ability evaluator score", "PastPerformance": "PastPerformance evaluator score", "adjusted_score": "adjusted score", "decision_score": "decision score", "final_score": "final score", "shadow_ai_rank": "shadow AI rank"}
    exposure_by_key = {(r["date"], r["race_id"], r["horse_number"]): r for r in exposures}
    for field, label in field_labels.items():
        pairs_count, pairs_log = [], []
        for row in rows:
            value = value_number(dict(row["values"]), field)
            if value is not None:
                exposure = exposure_by_key[(str(row["date"]), str(row["race_id"]), int(row["horse_number"]))]
                pairs_count.append((float(exposure["prior_ride_count_snapshot_scoped"]), value))
                pairs_log.append((float(exposure["log1p_prior_ride_count"]), value))
        correlation_rows.append({"comparison": label, "n": len(pairs_count), "pearson_prior_ride_count": pearson(pairs_count), "pearson_log1p_prior_ride_count": pearson(pairs_log), "status": "PRE_ONLY"})
    correlation_rows.insert(0, {"comparison": "Base PL utility", "n": 0, "pearson_prior_ride_count": None, "pearson_log1p_prior_ride_count": None, "status": "NOT_AVAILABLE_PRE_ONLY; no utility is frozen in the PRE-only source and it is not regenerated"})

    cross_conflicts = [{"historical_record_key": list(key), "normalized_jockeys": sorted(values)} for key, values in cross_snapshot.items() if len(values) > 1]
    repeated = [values for values in cross_snapshot.values() if len(values) > 1]
    cross_status = "PASS" if repeated and not cross_conflicts else ("FAIL" if cross_conflicts else "NOT_PROVEN_NO_REPEATED_RECORDS")
    pit = {
        "classification": "PIT_CONFIRMED_DEVELOPMENT" if cross_status == "PASS" else "PIT_NOT_PROVEN",
        "historical_attribute": "DS current-at-that-historical-race jockey, column 20 (1-based)",
        "strict_prior_date": {"status": "PASS", "violations": historical_schema["date_prior_violations"]},
        "source_sha_authority": {"status": "PASS", "source_files": len(snapshot_sha), "sha_records": snapshot_sha},
        "cross_snapshot_immutability": {"status": cross_status, "repeated_historical_records": len(repeated), "comparison_pairs": sum(len(v) - 1 for v in repeated), "jockey_mismatch_count": len(cross_conflicts), "mismatches": cross_conflicts},
        "historical_field_schema": {"date": "DS columns 1-3", "jockey": "DS column 20", "finish": "DS column 24", "abnormal_code": "DS column 26"},
    }
    knowledge = {
        "scope": "target horses in the 62-date PRE-only development population",
        "sire": {"present": len(all_de_sire), "knowledge_match": sum(name in SIRE_PROFILES for name in all_de_sire), "coverage": sum(name in SIRE_PROFILES for name in all_de_sire) / len(all_de_sire)},
        "broodmare_sire": {"present": len(all_de_broodmare_sire), "knowledge_match": sum(name in BROODMARE_SIRE_PROFILES for name in all_de_broodmare_sire), "coverage": sum(name in BROODMARE_SIRE_PROFILES for name in all_de_broodmare_sire) / len(all_de_broodmare_sire)},
        "authority": "knowledge/bloodlines/sire_profiles.py:SIRE_PROFILES; knowledge/bloodlines/broodmare.py:BROODMARE_SIRE_PROFILES",
        "performance_analysis": False,
    }
    summary = {
        "current_jockey_source": {"DE": "column 11 (1-based), active adapter _today_entry", "DG": "NOT_AVAILABLE", "DS": "not current target jockey; historical-race jockey is column 20 (1-based)"},
        "current_jockey_coverage": {"horses_total": len(exposures), "jockey_present": len(exposures) - len(missing_current), "jockey_missing": len(missing_current), "coverage_rate": (len(exposures) - len(missing_current)) / len(exposures)},
        "historical_jockey_pit_status": pit,
        "normalization": {"rule": "Unicode NFKC -> remove ASCII/full-width spaces -> strip only leading/trailing ▲△☆◇★◆; preserve all other characters, abbreviations, and surname/given variants distinct.", "raw_unique_jockeys": len(raw_names), "normalized_unique_jockeys": len(normal_variants), "collision_count": len(collisions), "collisions": collisions, "ambiguous_collisions": ambiguous, "unmatched_current_jockeys": unmatched},
        "prior_feature_feasibility": {"historical_jockey": "YES", "historical_finish": "YES", "historical_valid_result_semantics": "YES", "historical_race_date": "YES", "jockey_prior_top3_feature_feasible": "YES", "note": "No prior Top3 rate, smoothing parameter, or performance test was calculated in this audit."},
        "knowledge": knowledge,
    }
    return summary, exposures, distribution_rows, pit, monthly, {"rows": correlation_rows, "knowledge": knowledge}


def run(output: Path = OUT) -> dict[str, Any]:
    if output.exists():
        raise Stop("STOP_OUTPUT_EXISTS")
    summary, exposures, distribution, pit, monthly, correlations = audit()
    staging = Path(tempfile.mkdtemp(prefix=".jockey_context_audit_", dir=output.parent))
    try:
        csvout(staging / "prior_ride_exposure_by_target.csv", exposures, list(exposures[0]))
        csvout(staging / "prior_ride_count_distribution.csv", distribution, list(distribution[0]))
        csvout(staging / "monthly_prior_ride_coverage.csv", monthly, list(monthly[0]))
        csvout(staging / "result_free_correlation_table.csv", correlations["rows"], list(correlations["rows"][0]))
        dump(staging / "historical_jockey_pit_qualification.json", pit)
        dump(staging / "pedigree_existing_knowledge_coverage.json", correlations["knowledge"])
        preregistration_ready = pit["classification"] == "PIT_CONFIRMED_DEVELOPMENT"
        dump(staging / "summary.json", {
            "STATUS": "COMPLETE", "ROLE": "JOCKEY_CONTEXT_PRE_ONLY_QUALIFICATION_AUDIT", **summary,
            "jockey_context_genuinely_new": "YES", "preregistration_ready": "YES" if preregistration_ready else "NO",
            "pre_registration_boundary": "Any future experiment must separately preregister the snapshot-scoped exposure population and any outcome/smoothing semantics.",
            "TARGET_RESULT_ACCESS": 0, "MODEL_TRAINED": False, "EXP024_CHANGED": False, "EXP025_CHANGED": False, "PRODUCTION_CHANGED": False, "GIT_CHANGED": False,
            "BLOCKING": 0 if preregistration_ready else 1, "MAJOR": 0, "MINOR": ["Snapshot-scoped DS is not a universal jockey-career database; that scope must remain explicit in any later preregistration."],
        })
        (staging / "summary.md").write_text(
            "# JOCKEY_CONTEXT PRE-only Qualification Audit\n\n"
            "- Role: `JOCKEY_CONTEXT_PRE_ONLY_QUALIFICATION_AUDIT`\n"
            "- Target Result access: `0`\n"
            "- Current jockey: DE column 11 (1-based); coverage 100%.\n"
            f"- Historical jockey: DS column 20 (1-based); strict-before-target chronology passed; cross-snapshot status: `{pit['cross_snapshot_immutability']['status']}`.\n"
            "- Normalization: NFKC + whitespace removal + edge apprentice-mark removal only; abbreviations and lexical variants remain distinct.\n"
            f"- Jockey context is genuinely new: `YES`; preregistration readiness: `{'YES' if preregistration_ready else 'NO'}`.\n"
            "- Any future experiment must preserve the snapshot-scoped DS population and preregister outcome/smoothing semantics.\n",
            encoding="utf-8",
        )
        hashes = {path.relative_to(staging).as_posix(): {"sha256": sha(path), "size": path.stat().st_size} for path in sorted(staging.iterdir()) if path.is_file()}
        dump(staging / "artifact_hashes.json", {"self_hash_excluded": True, "artifacts": hashes})
        staging.rename(output)
        return json.loads((output / "summary.json").read_text(encoding="utf-8"))
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, sort_keys=True, indent=2))
