"""Result-free validation of the 2026-04-18 corrected April PRE source."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.prospective_prediction_runner_v1 import _assert_population
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


RAW = ROOT / "data" / "raw" / "prediction_input"
OLD = {kind: RAW / f"{kind}260418.CSV" for kind in ("DG", "DE", "DS")}
NEW = {kind: RAW / f"{kind}260418v2.CSV" for kind in ("DG", "DE", "DS")}
OTHER_DATES = ("20260404", "20260405", "20260411", "20260412", "20260419", "20260425", "20260426")
OUT = ROOT / "reports" / "april_2026_source_recovery_20260418_v1_completion_v1_recovery_v2"
OLD_HASHES = {
    "DG": "61bc1734b56e5e67b140ce3cd22be385b2a433e186cd0a826fa48899cd4f01b8",
    "DE": "3b62898339c565f51419638d7be1960376eb1c1d918b7cf667146410143637eb",
    "DS": "dfbf8714c190aa0144d42e5f675623696cb4bc80d1808d9f9955019393dbd5ea",
}
TARGET_EXCLUDED_RACE = ("中山", 11)


class Stop(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}:{detail}")
        self.code, self.detail = code, detail


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, data: object) -> Path:
    path = OUT / name
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def source_record(paths: dict[str, Path], version: str) -> dict:
    for path in paths.values():
        if not path.is_file():
            raise Stop("SOURCE_RECOVERY_NEW_SOURCE_PREFLIGHT_FAILURE", f"RAW_FILE_MISSING:{path}")
    return {"source_version": version, "sources": {
        kind: {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}
        for kind, path in paths.items()
    }}


def raw_rows(adapter: TargetBulkPredictionInputAdapterV1, paths: dict[str, Path]) -> tuple[dict[str, list[list[str]]], str]:
    rows = {kind: adapter._read_fixed(path, kind)[0] for kind, path in paths.items()}
    return rows, adapter._validate_dates(rows)


def dg_key(adapter: TargetBulkPredictionInputAdapterV1, row: list[str]) -> tuple[str, int]:
    return adapter._text(row[3]), adapter._int(row[4], "DG_RACE_NUMBER_INVALID")


def de_key(adapter: TargetBulkPredictionInputAdapterV1, row: list[str]) -> tuple[str, int, int, str]:
    return (adapter._text(row[1]), adapter._int(row[2], "DE_RACE_NUMBER_INVALID"),
            adapter._int(row[3], "DE_HORSE_NUMBER_INVALID"), adapter._clean_name(row[7]))


def is_target_jump(adapter: TargetBulkPredictionInputAdapterV1, row: list[str]) -> bool:
    return dg_key(adapter, row) == TARGET_EXCLUDED_RACE and adapter._text(row[7]) == "障害" and "中山グラ" in adapter._text(row[5])


def flat_semantics(adapter: TargetBulkPredictionInputAdapterV1, rows: dict[str, list[list[str]]], date: str) -> dict:
    jumps = [row for row in rows["DG"] if adapter._text(row[7]) == "障害"]
    if jumps and any(not is_target_jump(adapter, row) for row in jumps):
        raise Stop("SOURCE_REACQUISITION_NON_TARGET_DRIFT", "UNEXPECTED_JUMP_RACE")
    dg = {dg_key(adapter, row): row for row in rows["DG"] if not is_target_jump(adapter, row)}
    if len(dg) != len(rows["DG"]) - len(jumps):
        raise Stop("SOURCE_REACQUISITION_NON_TARGET_DRIFT", "DG_DUPLICATE_KEY")
    excluded_names = {adapter._clean_name(row[7]) for row in rows["DE"] if de_key(adapter, row)[:2] == TARGET_EXCLUDED_RACE}
    de: dict[tuple[str, int, int, str], list[str]] = {}
    for row in rows["DE"]:
        key = de_key(adapter, row)
        if key[:2] == TARGET_EXCLUDED_RACE:
            continue
        if key in de:
            raise Stop("SOURCE_REACQUISITION_NON_TARGET_DRIFT", f"DE_DUPLICATE:{key}")
        de[key] = row
    by_race: dict[tuple[str, int], list[list[str]]] = defaultdict(list)
    for key, row in de.items():
        by_race[key[:2]].append(row)
    if set(dg) != set(by_race):
        raise Stop("SOURCE_REACQUISITION_NON_TARGET_DRIFT", "DG_DE_RACE_SET")
    entry = {key: asdict(adapter._today_entry(date, dg[key[:2]], row)) for key, row in de.items()}
    identities = {key: {"horse_number": key[2], "horse_name": key[3], "identifier": adapter._text(row[18]), "stable_key": adapter._text(row[32])} for key, row in de.items()}
    dg_main = {key: {"surface": adapter._text(row[7]), "distance": adapter._text(row[8]), "field_size": adapter._text(row[9])} for key, row in dg.items()}
    headcounts = {key: len(value) for key, value in by_race.items()}
    ds_by_name: dict[str, list[list[str]]] = defaultdict(list)
    for row in rows["DS"]:
        ds_by_name[adapter._clean_name(row[16])].append(row)
    names = {key[3] for key in de}
    if set(ds_by_name) != names | excluded_names:
        raise Stop("SOURCE_REACQUISITION_NON_TARGET_DRIFT", "DE_DS_SEMANTIC_NAME_SET")
    ds_raw = {name: Counter(tuple(row) for row in ds_by_name[name]) for name in names}
    ds_mapped = {name: Counter(json.dumps(asdict(value), ensure_ascii=False, sort_keys=True, default=str) for value in adapter._past_races(ds_by_name[name])) for name in names}
    return {"dg": dg_main, "identities": identities, "entries": entry, "headcounts": headcounts,
            "ds_raw": ds_raw, "ds_mapped": ds_mapped,
            "row_orders": {"dg": [dg_key(adapter, row) for row in rows["DG"] if not is_target_jump(adapter, row)],
                           "de": [de_key(adapter, row) for row in rows["DE"] if de_key(adapter, row)[:2] != TARGET_EXCLUDED_RACE],
                           "ds": [adapter._clean_name(row[16]) for row in rows["DS"]]},
            "jump_count": len(jumps)}


def diff(old: dict, new: dict) -> list[dict]:
    differences = []
    for name in ("dg", "identities", "entries", "headcounts", "ds_raw", "ds_mapped"):
        old_map, new_map = old[name], new[name]
        for key in sorted(set(old_map) ^ set(new_map), key=str):
            differences.append({"category": name, "key": str(key), "difference": "KEY_SET_MISMATCH"})
        for key in sorted(set(old_map) & set(new_map), key=str):
            if old_map[key] != new_map[key]:
                differences.append({"category": name, "key": str(key), "difference": "VALUE_MISMATCH"})
    return differences


def other_date_preflight(adapter: TargetBulkPredictionInputAdapterV1) -> list[dict]:
    records = []
    for date in OTHER_DATES:
        paths = {kind: RAW / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
        try:
            bundle = adapter.load(paths["DG"], paths["DE"], paths["DS"])
            if bundle.date != date:
                raise ValueError(f"TARGET_DATE_MISMATCH:{bundle.date}")
            _assert_population(bundle)
            records.append({"date": date, "status": "PASS", "race_count": len(bundle.races), "horse_count": sum(len(r.today_entries) for r in bundle.races.values()), "preflight": bundle.preflight})
        except Exception as exc:
            raise Stop("SOURCE_RECOVERY_OTHER_DATE_REPREFLIGHT_FAILURE", f"{date}:{exc}") from exc
    return records


def run() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        if any(sha(OLD[kind]) != expected for kind, expected in OLD_HASHES.items()):
            raise Stop("SOURCE_RECOVERY_OLD_SOURCE_IMMUTABILITY_FAILURE", "OLD_SOURCE_SHA")
        adapter = TargetBulkPredictionInputAdapterV1()
        old_record, new_record = source_record(OLD, "INVALID_PRE_SOURCE_VERSION"), source_record(NEW, "CORRECTED_PRE_SOURCE_VERSION")
        old_rows, old_date = raw_rows(adapter, OLD)
        new_rows, new_date = raw_rows(adapter, NEW)
        if old_date != "20260418" or new_date != "20260418":
            raise Stop("SOURCE_RECOVERY_NEW_SOURCE_PREFLIGHT_FAILURE", f"DATE:{old_date}:{new_date}")
        new_bundle = adapter.load(NEW["DG"], NEW["DE"], NEW["DS"])
        _assert_population(new_bundle)
        if any(adapter._text(row[7]) == "障害" for row in new_rows["DG"]):
            raise Stop("SOURCE_RECOVERY_NEW_SOURCE_PREFLIGHT_FAILURE", "FORBIDDEN_JUMP_PRESENT")
        old_semantic, new_semantic = flat_semantics(adapter, old_rows, old_date), flat_semantics(adapter, new_rows, new_date)
        differences = diff(old_semantic, new_semantic)
        if differences:
            raise Stop("SOURCE_REACQUISITION_NON_TARGET_DRIFT", json.dumps(differences, ensure_ascii=False, sort_keys=True))
        order_changed = old_semantic["row_orders"] != new_semantic["row_orders"]
        other = other_date_preflight(adapter)
        write("lineage.json", {"old": {**old_record, "superseded_by": "CORRECTED_PRE_SOURCE_VERSION"},
                               "new": {**new_record, "supersedes": "INVALID_PRE_SOURCE_VERSION", "human_reacquisition_confirmation": "HUMAN_STATEMENT"},
                               "failure_replaced": "DG_SENTINEL_INVALID"})
        write("drift_check.json", {"classification": "PRE_ONLY_SOURCE_DRIFT_CHECK", "evidence_status": "DIAGNOSTIC_NOT_EVIDENCE",
                                    "must_match": "PASS", "stop_diff_count": 0,
                                    "allowed_expected_diff": ["中山11R 中山グランドジャンプ（JG1）およびその専用Source rowsの消失", "raw file SHA256"],
                                    "old_jump_count": old_semantic["jump_count"], "new_jump_count": new_semantic["jump_count"],
                                    "row_order_changed": order_changed, "row_order_semantic_independence": "PASS"})
        write("other_dates_repreflight.json", {"status": "PASS", "records": other})
        source_set = {"status": "APRIL_SOURCE_RECOVERY_READY_FOR_PRE_EXECUTION", "population_scope_id": "PREDICTION_BUY_1WIN_PLUS_FLAT",
                      "active_dates": [{"date": date, "source_version": "CORRECTED_PRE_SOURCE_VERSION" if date == "20260418" else "EXISTING_PRE_SOURCE_VERSION",
                                        "sources": {kind: {"path": str((NEW if date == "20260418" else {k: RAW / f'{k}{date[2:]}.CSV' for k in ("DG", "DE", "DS")})[kind].relative_to(ROOT)),
                                                           "sha256": sha((NEW if date == "20260418" else {k: RAW / f'{k}{date[2:]}.CSV' for k in ("DG", "DE", "DS")})[kind])} for kind in ("DG", "DE", "DS")}}
                                       for date in ("20260404", "20260405", "20260411", "20260412", "20260418", "20260419", "20260425", "20260426")],
                      "replacement_lineage": {"date": "20260418", "old": old_record, "new": new_record},
                      "all_date_population_preflight": "PASS", "access_counts": {"result_access": 0, "outcome_access": 0, "prediction_execution": 0, "v3_execution": 0, "cf_execution": 0, "may_access": 0},
                      "production_changes": 0}
        set_path = write("april_active_source_set_manifest.json", source_set)
        status_path = write("recovery_completion_status.json", {"source_recovery_status": "APRIL_SOURCE_RECOVERY_READY_FOR_PRE_EXECUTION", "old_source_sha_verification": "PASS", "v2_dg_sentinel": "PASS", "forbidden_population": "PASS", "v2_structural_preflight": "PASS", "must_match": "PASS", "stop_diff_count": 0, "source_reacquisition_non_target_drift": "NO", "row_order_semantic_independence": "PASS", "corrected_source_status": "CORRECTED_PRE_SOURCE_ACCEPTED", "other_7_dates_repreflight": "PASS", "active_source_set_manifest": str(set_path.relative_to(ROOT)), "access_counts": source_set["access_counts"], "production_changes": 0, "blocking_issue": None})
        index = {str(path.relative_to(OUT)): sha(path) for path in sorted(OUT.glob("*.json"))}
        write("artifact_hashes.json", {"indexed_artifacts": index, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write("recovery_completion_status.json", {"source_recovery_status": "STOP_WITH_REASON", "reason_code": exc.code, "detail": exc.detail, "access_counts": {"result_access": 0, "outcome_access": 0, "prediction_execution": 0, "v3_execution": 0, "cf_execution": 0, "may_access": 0}, "production_changes": 0})
        return OUT


if __name__ == "__main__":
    print(run())
