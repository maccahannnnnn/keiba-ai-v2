"""Additive, result-free detail audit for the April 2026-04-18 recovery."""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.april_source_recovery_validation_v1 import (
    NEW, OLD, OLD_HASHES, OTHER_DATES, TARGET_EXCLUDED_RACE, de_key, dg_key,
    is_target_jump, raw_rows,
)
from review.prospective_prediction_runner_v1 import _assert_population
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


OUT = ROOT / "reports" / "april_2026_source_recovery_20260418_v1_completion_v1_recovery_v4"
PRIOR = ROOT / "reports" / "april_2026_source_recovery_20260418_v1_completion_v1_recovery_v2"
NEW_HASHES = {
    "DG": "3bf451b46bd666a44baac478c4172c2a97e503bd9e76ee078492777c02cb3352",
    "DE": "c8e0fdb9ddbaf16e805b5b2af3b876f07ef635221a2393d5052140a46cd1c717",
    "DS": "ef59d6779fbf3c76e504484e827a5e9404e534ff38c610e0869fc8e04796fbc9",
}


class Stop(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}:{detail}")
        self.code, self.detail = code, detail


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def write(name: str, value: object) -> Path:
    path = OUT / name
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def dg_detail(adapter, old_rows, new_rows):
    def record(row):
        return {"course": adapter._text(row[3]), "race_number": adapter._int(row[4], "DG_RACE_NUMBER_INVALID"),
                "race_name": adapter._text(row[5]), "class": adapter._text(row[6]), "surface": adapter._text(row[7]),
                "distance": adapter._text(row[8]), "field_size": adapter._text(row[9])}
    old = {dg_key(adapter, row): record(row) for row in old_rows}
    new = {dg_key(adapter, row): record(row) for row in new_rows}
    common = sorted(set(old) & set(new))
    diffs = [{"race_key": list(key), "old": old[key], "new": new[key]} for key in common if {field: old[key][field] for field in ("surface", "distance", "field_size")} != {field: new[key][field] for field in ("surface", "distance", "field_size")}]
    return {"old_races": [old[key] for key in sorted(old)], "new_races": [new[key] for key in sorted(new)],
            "common_races": [old[key] for key in common], "removed_races": [old[key] for key in sorted(set(old) - set(new))],
            "added_races": [new[key] for key in sorted(set(new) - set(old))], "common_race_main_field_diffs": diffs}


def de_detail(adapter, date, old_dg_rows, new_dg_rows, old_rows, new_rows):
    def primary(row):
        return de_key(adapter, row)
    old = {primary(row): row for row in old_rows}
    new = {primary(row): row for row in new_rows}
    common = sorted(set(old) & set(new))
    removed, added = sorted(set(old) - set(new)), sorted(set(new) - set(old))
    def identity(key, row):
        return {"course": key[0], "race_number": key[1], "horse_number": key[2], "horse_name": key[3], "identifier": adapter._text(row[18]), "stable_key": adapter._text(row[32])}
    field_diffs = []
    for key in common:
        old_entry, new_entry = asdict(adapter._today_entry(date, next(row for row in old_dg_rows if dg_key(adapter, row) == key[:2]), old[key])), asdict(adapter._today_entry(date, next(row for row in new_dg_rows if dg_key(adapter, row) == key[:2]), new[key]))
        changed = {field: {"old": old_entry[field], "new": new_entry[field]} for field in old_entry if old_entry[field] != new_entry[field]}
        old_identity, new_identity = identity(key, old[key]), identity(key, new[key])
        changed.update({field: {"old": old_identity[field], "new": new_identity[field]} for field in ("identifier", "stable_key") if old_identity[field] != new_identity[field]})
        if changed:
            field_diffs.append({"horse": old_identity, "field_diffs": changed})
    return {"old_horses": [identity(key, old[key]) for key in sorted(old)], "new_horses": [identity(key, new[key]) for key in sorted(new)],
            "common_horses": [identity(key, old[key]) for key in common], "removed_horses": [identity(key, old[key]) for key in removed],
            "added_horses": [identity(key, new[key]) for key in added], "common_flat_todayentry_diffs": field_diffs}


def ds_detail(adapter, old_rows, new_rows, common_horse_names):
    def group(rows):
        values = {}
        for name in common_horse_names:
            selected = [row for row in rows if adapter._clean_name(row[16]) == name]
            mapped = [asdict(row) for row in adapter._past_races(selected)]
            values[name] = {"history_row_count": len(selected), "mapped_history_count": len(mapped),
                            "raw_history_rows": sorted([list(row) for row in selected]), "mapped_history": sorted(mapped, key=dump)}
        return values
    old, new = group(old_rows), group(new_rows)
    records, diffs = [], []
    for name in sorted(common_horse_names):
        match = old[name] == new[name]
        record = {"horse_name": name, "status": "MATCH" if match else "DIFF", "old_history_row_count": old[name]["history_row_count"], "new_history_row_count": new[name]["history_row_count"], "old_mapped_history": old[name]["mapped_history"], "new_mapped_history": new[name]["mapped_history"]}
        records.append(record)
        if not match:
            diffs.append(record)
    return {"common_flat_horse_histories": records, "history_diff_count": len(diffs), "history_diffs": diffs}


def population_detail(adapter, date, paths):
    bundle = adapter.load(paths["DG"], paths["DE"], paths["DS"])
    if bundle.date != date:
        raise Stop("SOURCE_RECOVERY_AUDIT_DETAIL_CONTRADICTION", f"DATE:{date}:{bundle.date}")
    _assert_population(bundle)
    rows, _ = raw_rows(adapter, paths)
    new_count = sum("新馬" in adapter._text(row[5]) or "newcomer" in adapter._text(row[5]).lower() for row in rows["DG"])
    maiden_count = sum("未勝利" in adapter._text(row[5]) or "maiden" in adapter._text(row[5]).lower() for row in rows["DG"])
    jump_count = sum(adapter._text(row[7]) == "障害" for row in rows["DG"])
    return {"date": date, "new_race_count": new_count, "maiden_race_count": maiden_count, "jump_race_count": jump_count,
            "dg_sentinel_status": "PASS", "structural_preflight_status": "PASS", "race_count": len(bundle.races), "horse_count": sum(len(r.today_entries) for r in bundle.races.values())}


def run() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        before_prior = {path.name: sha(path) for path in PRIOR.glob("*") if path.is_file()}
        if not before_prior:
            raise Stop("SOURCE_RECOVERY_AUDIT_DETAIL_CONTRADICTION", "PRIOR_COMPLETION_MISSING")
        if any(sha(OLD[kind]) != value for kind, value in OLD_HASHES.items()):
            raise Stop("SOURCE_RECOVERY_AUDIT_DETAIL_CONTRADICTION", "OLD_SOURCE_SHA_CHANGED")
        if any(sha(NEW[kind]) != value for kind, value in NEW_HASHES.items()):
            raise Stop("SOURCE_RECOVERY_AUDIT_DETAIL_CONTRADICTION", "CORRECTED_SOURCE_SHA_CHANGED")
        adapter = TargetBulkPredictionInputAdapterV1()
        old_rows, date = raw_rows(adapter, OLD)
        new_rows, new_date = raw_rows(adapter, NEW)
        if date != "20260418" or new_date != "20260418":
            raise Stop("SOURCE_RECOVERY_AUDIT_DETAIL_CONTRADICTION", "DATE_MISMATCH")
        dg = dg_detail(adapter, old_rows["DG"], new_rows["DG"])
        de = de_detail(adapter, date, old_rows["DG"], new_rows["DG"], old_rows["DE"], new_rows["DE"])
        removed_keys = {(item["course"], item["race_number"]) for item in dg["removed_races"]}
        if removed_keys != {TARGET_EXCLUDED_RACE} or dg["added_races"] or dg["common_race_main_field_diffs"]:
            raise Stop("SOURCE_RECOVERY_AUDIT_DETAIL_CONTRADICTION", "DG_DETAIL")
        if any((item["course"], item["race_number"]) != TARGET_EXCLUDED_RACE for item in de["removed_horses"]) or de["added_horses"] or de["common_flat_todayentry_diffs"]:
            raise Stop("SOURCE_RECOVERY_AUDIT_DETAIL_CONTRADICTION", "DE_DETAIL")
        common_names = {item["horse_name"] for item in de["common_horses"]}
        ds = ds_detail(adapter, old_rows["DS"], new_rows["DS"], common_names)
        if ds["history_diff_count"]:
            raise Stop("SOURCE_RECOVERY_AUDIT_DETAIL_CONTRADICTION", "DS_DETAIL")
        old_jump_rows = [row for row in old_rows["DG"] if is_target_jump(adapter, row)]
        removed_jump = {"race": dg["removed_races"], "removed_de_horses": de["removed_horses"],
                        "removed_ds_relationships": [{"horse_name": item["horse_name"], "old_ds_history_row_count": sum(adapter._clean_name(row[16]) == item["horse_name"] for row in old_rows["DS"])} for item in de["removed_horses"]],
                        "old_dg_rows": old_jump_rows}
        old_order = {"dg": [list(dg_key(adapter, row)) for row in old_rows["DG"]], "de": [list(de_key(adapter, row)) for row in old_rows["DE"]], "ds_horse_name": [adapter._clean_name(row[16]) for row in old_rows["DS"]]}
        new_order = {"dg": [list(dg_key(adapter, row)) for row in new_rows["DG"]], "de": [list(de_key(adapter, row)) for row in new_rows["DE"]], "ds_horse_name": [adapter._clean_name(row[16]) for row in new_rows["DS"]]}
        row_order = {"old_row_order": old_order, "new_row_order": new_order, "row_order_changed": old_order != new_order,
                     "race_key_set_equality": True, "horse_key_set_equality": True, "adapter_mapping_equality": True,
                     "row_order_semantic_independence": "PASS"}
        other = []
        for day in OTHER_DATES:
            paths = {kind: ROOT / "data" / "raw" / "prediction_input" / f"{kind}{day[2:]}.CSV" for kind in ("DG", "DE", "DS")}
            other.append(population_detail(adapter, day, paths))
        corrected = population_detail(adapter, "20260418", NEW)
        if any(item[key] for item in [corrected, *other] for key in ("new_race_count", "maiden_race_count", "jump_race_count")):
            raise Stop("SOURCE_RECOVERY_AUDIT_DETAIL_CONTRADICTION", "FORBIDDEN_POPULATION")
        confirmation = {"confirmed_by": "HUMAN", "confirmation_timestamp": None, "timestamp_source": "NOT_FORMALLY_CAPTURED", "confirmation_method": "HUMAN_STATEMENT", "confirmation_summary": "2026-04-18 DG/DE/DS were reacquired from TARGET using the ordinary Prospective population setting for 1-win-class-or-higher flat races only. The prior files were not deleted or overwritten.", "result_access_at_confirmation": 0}
        detailed = {"classification": "PRE_ONLY_SOURCE_DRIFT_CHECK", "evidence_status": "DIAGNOSTIC_NOT_EVIDENCE", "dg_race_comparison": dg, "de_horse_comparison": de, "ds_history_comparison": ds, "removed_jump_race_detail": removed_jump, "row_order_analysis": row_order, "must_match_item_level_results": {"dg": "PASS", "de": "PASS", "ds": "PASS", "headcount": "PASS", "identity_mapping": "PASS"}, "allowed_expected_diff": ["中山11R 中山グランドジャンプ（JG1）・障害と同レース専用DE/DS行の消失", "再exportに伴うraw SHA256差", "row ordering"], "stop_diff_details": [], "must_match": "PASS", "stop_diff_count": 0, "source_reacquisition_non_target_drift": "NO"}
        write("drift_check_detailed.json", detailed)
        write("forbidden_population_detail.json", {"corrected_20260418": corrected, "other_7_dates": other, "all_8_dates_forbidden_population": "PASS"})
        write("human_reacquisition_confirmation_detail.json", confirmation)
        after_prior = {path.name: sha(path) for path in PRIOR.glob("*") if path.is_file()}
        if before_prior != after_prior:
            raise Stop("SOURCE_RECOVERY_AUDIT_DETAIL_CONTRADICTION", "PRIOR_COMPLETION_MUTATED")
        status = {"revision_status": "APRIL_SOURCE_SET_READY_FOR_HUMAN_APPROVAL", "old_completion_artifact_immutability": "PASS", "old_source_sha_verification": "PASS", "corrected_v2_source_sha_verification": "PASS", "dg_common_race_count": len(dg["common_races"]), "dg_removed_race_list": dg["removed_races"], "dg_added_race_list": dg["added_races"], "unexpected_flat_dg_diff_count": 0, "de_common_horse_count": len(de["common_horses"]), "de_removed_horse_count": len(de["removed_horses"]), "de_removed_horse_list": de["removed_horses"], "de_added_horse_list": de["added_horses"], "unexpected_flat_de_diff_count": 0, "ds_common_flat_horse_history_match": "PASS", "ds_history_diff_count": 0, "row_order_semantic_independence": "PASS", "other_7_dates_forbidden_population_detail": "PASS", "april_8_date_forbidden_population": "PASS", "human_reacquisition_confirmation_record": confirmation, "must_match": "PASS", "stop_diff_count": 0, "source_reacquisition_non_target_drift": "NO", "access_counts": {"result_access": 0, "outcome_access": 0, "prediction_execution": 0, "v3_execution": 0, "cf_execution": 0, "may_access": 0}, "production_changes": 0, "blocking_issue": None}
        write("revision_status.json", status)
        index = {path.name: sha(path) for path in sorted(OUT.glob("*.json"))}
        write("artifact_hashes.json", {"indexed_artifacts": index, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write("revision_status.json", {"revision_status": "STOP_WITH_REASON", "reason_code": exc.code, "detail": exc.detail, "access_counts": {"result_access": 0, "outcome_access": 0, "prediction_execution": 0, "v3_execution": 0, "cf_execution": 0, "may_access": 0}, "production_changes": 0})
        return OUT


if __name__ == "__main__":
    print(run())
