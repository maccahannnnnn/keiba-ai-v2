"""Aggregate already-frozen CF formal PRE evidence without re-selection.

This is a one-shot POST evidence recorder.  It reads only frozen PRE records
and canonical daily-result lists, appends eligible dates through the existing
CF ledger API, and writes a separate formal aggregation report.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from review.cf_top3_rank_anchored_shadow_v1 import (
    PROTOCOL_VERSION,
    append_formal_post_evidence,
    protocol_definition,
    protocol_hash,
)
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
CF_ROOT = ROOT / "reports/shadow_cf_top3_rank_anchored_v1"
OUTPUT = ROOT / "reports/cf_formal_prospective_aggregation_v1"
RAW = ROOT / "data/raw/target/daily_result_list"
ABNORMAL = {"中止", "除外", "取消", "失格"}
VENUES = {"sapporo": "札幌", "hakodate": "函館", "fukushima": "福島", "niigata": "新潟", "tokyo": "東京", "nakayama": "中山", "chukyo": "中京", "chuukyou": "中京", "kyoto": "京都", "hanshin": "阪神", "kokura": "小倉"}

SOURCES = (
    ("20260829", "reports/prospective_three_system_20260829_v1_retry2/cf_formal_prospective_pre.json", "reports/prospective_prediction_20260829_v1", "20260829", None),
    ("20260830", "reports/shadow_cf_top3_rank_anchored_v1/formal_pre_20260830.json", "reports/prospective_prediction_20260830_v1", "20260830", None),
    ("20260905", "reports/shadow_cf_top3_rank_anchored_v1/formal_pre_20260905.json", "reports/prospective_prediction_20260905_v1", "20260905", None),
    ("20260906", "reports/shadow_cf_top3_rank_anchored_v1/formal_pre_20260906.json", "reports/prospective_prediction_20260906_v1", "20260906", None),
    ("20260912", "reports/daily_pre_prediction_20260912/current_cf_v4_reference/cf_formal_prospective_pre.json", "reports/daily_pre_prediction_20260912/current_frozen", "20260912", None),
    ("20260913", "reports/daily_pre_prediction_20260913/current_cf_v4_reference/cf_formal_prospective_pre.json", "reports/daily_pre_prediction_20260913/current_frozen", "20260913", None),
    ("20260919", "reports/daily_pre_prediction_20260919/current_cf_v4_reference/cf_formal_prospective_pre.json", "reports/daily_pre_prediction_20260919/current_frozen", "20260919", None),
    ("20260920", "reports/daily_pre_prediction_20260920/current_cf_v4_reference/cf_formal_prospective_pre.json", "reports/daily_pre_prediction_20260920/current_frozen", "20260920", None),
    # The frozen label is 9/21, but storm postponement moved Nakayama to 9/22.
    ("20260921", "reports/daily_pre_analysis_20260921/current_cf_v5_reference/cf_formal_prospective_pre.json", "reports/daily_pre_analysis_20260921/current_frozen", "20260922", "馬番順着順_220260922.csv"),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rate(hits: int, valid: int) -> float | None:
    return hits / valid if valid else None


def metric(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(row["actual_top3"] for row in valid)
    return {"selected_n": len(rows), "invalid_n": len(rows) - len(valid), "valid_n": len(valid), "hits": hits, "rate": rate(hits, len(valid))}


def aggregate(items: list[dict]) -> dict:
    valid = sum(item["valid_n"] for item in items)
    hits = sum(item["hits"] for item in items)
    return {"selected_n": sum(item["selected_n"] for item in items), "invalid_n": sum(item["invalid_n"] for item in items), "valid_n": valid, "hits": hits, "rate": rate(hits, valid)}


def race_parts(race_id: str) -> tuple[str, int]:
    bits = race_id.split("_")
    return bits[-2], int(bits[-1].removesuffix("R"))


def outcome(result: list[str], horse_number: int) -> dict:
    raw = result[11 + horse_number].strip()
    if raw.isdigit():
        finish = int(raw)
        valid = finish > 0
    elif raw in ABNORMAL:
        finish, valid = 0, False
    else:
        raise RuntimeError(f"STOP_UNKNOWN_RESULT_SEMANTICS:{raw}")
    return {"actual_finish": finish, "raw_result": raw, "valid_result": valid, "actual_top3": bool(valid and finish <= 3)}


def verify_prediction_root(root: Path) -> tuple[dict, dict[str, dict]]:
    manifest = read(root / "prediction_manifest.json")
    bad = [item["relative_path"] for item in manifest["files"] if not (root / item["relative_path"]).is_file() or sha(root / item["relative_path"]) != item["sha256"]]
    if bad:
        raise RuntimeError(f"STOP_CURRENT_PRE_HASH_MISMATCH:{root}:{bad}")
    index = read(root / "race_index.json")["race_index"]
    races = {item["race_id"]: read(root / item["artifact"]) for item in index}
    return manifest, races


def load_result(date: str, primary_name: str | None = None) -> tuple[dict, dict[tuple[str, int], list[str]], dict]:
    primary = RAW / (primary_name or f"馬番順着順_{date}.csv")
    auxiliary = RAW / f"着順馬番_{date}.csv"
    validation = validate_source_pair(primary, auxiliary, date)
    with primary.open(encoding="cp932", newline="") as source:
        rows = list(csv.reader(source))
    by_venue_race = {(row[1], int(row[2])): row for row in rows}
    if len(by_venue_race) != len(rows):
        raise RuntimeError(f"STOP_DUPLICATE_RESULT_RACE:{date}")
    return validation, by_venue_race, {"primary": str(primary.relative_to(ROOT)), "auxiliary": str(auxiliary.relative_to(ROOT)), "primary_sha256": sha(primary), "auxiliary_sha256": sha(auxiliary)}


def pre_before_result(provenance: dict, date: str) -> dict:
    generated = provenance.get("generated_at")
    if not isinstance(generated, str) or provenance.get("result_data_access_count") != 0:
        raise RuntimeError(f"STOP_PRE_RESULT_BOUNDARY_UNPROVEN:{date}")
    generated_time = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    target_start = datetime.strptime(date, "%Y%m%d").replace(tzinfo=timezone.utc)
    if generated_time >= target_start:
        raise RuntimeError(f"STOP_PRE_NOT_BEFORE_TARGET_DATE:{date}")
    return {"status": "PASS", "pre_generated_at": generated, "pre_result_data_access_count": 0,
            "result_access_timestamp": "CANONICAL_POST_ONLY; source acquisition timestamp not persisted", "proof": "PRE generated before target-date start and records zero Result access"}


def current_rows(payloads: dict[str, dict], results: dict[tuple[str, int], list[str]]) -> list[dict]:
    rows = []
    for race_id, payload in payloads.items():
        venue_key, number = race_parts(race_id)
        result = results.get((VENUES[venue_key], number))
        if result is None:
            raise RuntimeError(f"STOP_CURRENT_RESULT_RACE_MISSING:{race_id}")
        if len(payload["ranked_results"]) != int(result[9]):
            raise RuntimeError(f"STOP_CURRENT_RESULT_HEADCOUNT_MISMATCH:{race_id}")
        for horse in payload["ranked_results"]:
            if bool(horse.get("buy", horse.get("decision") == "BUY")):
                rows.append({"race_id": race_id, "horse_number": int(horse["horse_number"]), "horse_name": horse["horse_name"], **outcome(result, int(horse["horse_number"]))})
    return rows


def run() -> Path:
    if OUTPUT.exists():
        raise RuntimeError("STOP_OUTPUT_EXISTS")
    activation = read(CF_ROOT / "activation_record.json")
    ledger_path = CF_ROOT / "cumulative_ledger.json"
    original_ledger = read(ledger_path)
    if activation.get("protocol_sha256") != protocol_hash() or original_ledger.get("formal_activation_status") != "ACTIVATED":
        raise RuntimeError("STOP_CF_ACTIVATION_OR_LEDGER_MISMATCH")
    source_manifest, result_manifest, per_date, current_metrics = [], [], [], []
    ledger = original_ledger
    for date, pre_relative, current_relative, result_date, primary_name in SOURCES:
        pre_path, current_root = ROOT / pre_relative, ROOT / current_relative
        pre = read(pre_path)
        if pre.get("date") != date or pre.get("protocol_version") != PROTOCOL_VERSION or pre.get("protocol_sha256") != protocol_hash():
            raise RuntimeError(f"STOP_CF_PRE_PROTOCOL_MISMATCH:{date}")
        manifest, payloads = verify_prediction_root(current_root)
        if pre.get("source_prediction_manifest_sha256") != sha(current_root / "prediction_manifest.json"):
            raise RuntimeError(f"STOP_CF_CURRENT_PRE_DEPENDENCY_MISMATCH:{date}")
        boundary = pre_before_result(read(current_root / "provenance.json"), date)
        validation, results, result_source = load_result(result_date, primary_name)
        selected_rows, pool_rows, post_records = [], [], []
        for race in pre["eligible_races"]:
            race_id = race["race_id"]
            venue_key, number = race_parts(race_id)
            result = results.get((VENUES[venue_key], number))
            if result is None or race_id not in payloads:
                raise RuntimeError(f"STOP_CF_RESULT_RACE_IDENTITY_MISMATCH:{date}:{race_id}")
            if len(payloads[race_id]["ranked_results"]) != int(result[9]):
                raise RuntimeError(f"STOP_CF_RESULT_HEADCOUNT_MISMATCH:{date}:{race_id}")
            def join(horses: list[dict]) -> list[dict]:
                return [{"race_id": race_id, "horse_number": int(horse["horse_number"]), "horse_name": horse["horse_name"], **outcome(result, int(horse["horse_number"]))} for horse in horses]
            selected, pool = join(race["cf_selected_horses"]), join(race["candidate_horses"])
            selected_rows.extend(selected); pool_rows.extend(pool)
            sm, pm = metric(selected), metric(pool)
            post_records.append({"race_id": race_id, "selected_valid_count": sm["valid_n"], "selected_top3_count": sm["hits"], "candidate_pool_valid_count": pm["valid_n"], "candidate_pool_top3_count": pm["hits"]})
        sm, pm = metric(selected_rows), metric(pool_rows)
        difference = None if sm["rate"] is None or pm["rate"] is None else sm["rate"] - pm["rate"]
        # 9/21 input intentionally spans Hanshin (actual 9/21) and postponed
        # Nakayama (actual 9/22); this affects only the descriptive Current lane.
        current_result_index = results
        if date == "20260921":
            _, hanshin_results, _ = load_result("20260921")
            if set(hanshin_results).intersection(results):
                raise RuntimeError("STOP_POSTPONED_SCHEDULE_RESULT_IDENTITY_CONFLICT")
            current_result_index = {**hanshin_results, **results}
        current = metric(current_rows(payloads, current_result_index))
        current_metrics.append({"date": date, **current, "cf": sm, "raw_hit_delta_cf_minus_current": sm["hits"] - current["hits"], "rate_delta_cf_minus_current": None if sm["rate"] is None or current["rate"] is None else sm["rate"] - current["rate"]})
        entry = {"date": date, "pre_path": pre_relative, "pre_sha256": sha(pre_path), "current_pre_root": current_relative, "current_prediction_manifest_sha256": sha(current_root / "prediction_manifest.json"), "pre_integrity": boundary, "selected_races": len(post_records), "selected": sm, "candidate_comparator": pm, "raw_hit_delta": sm["hits"] - pm["hits"], "rate_delta": difference, "daily_sign": "NON_NEGATIVE" if difference is not None and difference >= 0 else ("NEGATIVE" if difference is not None else "NOT_EVALUABLE"), "formal_evidence_status": "RECORDED" if post_records else "NO_ELIGIBLE_CF_RACE"}
        per_date.append(entry)
        source_manifest.append({"date": date, "pre_path": pre_relative, "pre_sha256": sha(pre_path), "current_pre_root": current_relative, "current_manifest_sha256": sha(current_root / "prediction_manifest.json"), "eligible_races": len(post_records), "selected_horses": sm["selected_n"], "freeze_boundary": boundary})
        result_manifest.append({"pre_date": date, "result_date": result_date, **result_source, "schema_status": validation["status"], "joined_cf_races": len(post_records)})
        if post_records:
            ledger = append_formal_post_evidence(ledger=ledger, date=date, activation_record=activation, post_records=post_records, independent_race_count=len(post_records))
    if ledger["formal_independent_race_count"] != 27 or sum(item["selected"]["selected_n"] for item in per_date) != 81:
        raise RuntimeError("STOP_FROZEN_POPULATION_COUNT_MISMATCH")
    recorded = [item for item in per_date if item["selected_races"]]
    cf_total = aggregate([item["selected"] for item in recorded])
    comparator_total = aggregate([item["candidate_comparator"] for item in recorded])
    raw_delta, rate_delta = cf_total["hits"] - comparator_total["hits"], cf_total["rate"] - comparator_total["rate"]
    lodo = []
    for omitted in recorded:
        rest = [item for item in recorded if item["date"] != omitted["date"]]
        cf_rest, comparator_rest = aggregate([item["selected"] for item in rest]), aggregate([item["candidate_comparator"] for item in rest])
        delta = cf_rest["rate"] - comparator_rest["rate"]
        lodo.append({"omitted_date": omitted["date"], "cf": cf_rest, "comparator": comparator_rest, "rate_delta": delta, "sign": "NON_NEGATIVE" if delta >= 0 else "NEGATIVE"})
    lodo_stable = all(item["rate_delta"] >= 0 for item in lodo)
    non_negative = sum(item["daily_sign"] == "NON_NEGATIVE" for item in recorded)
    majority = non_negative > len(recorded) / 2
    protocol = protocol_definition()
    minimum = protocol["SHADOW_ACCEPT"]["all_conditions"]
    if cf_total["rate"] >= comparator_total["rate"] and lodo_stable and majority:
        verdict = "SHADOW_ACCEPT"
    elif cf_total["rate"] < comparator_total["rate"] or sum(item["daily_sign"] == "NEGATIVE" for item in recorded) > len(recorded) / 2:
        verdict = "SHADOW_REJECT"
    else:
        verdict = "HOLD"
    secondary_current = aggregate([{key: item[key] for key in ("selected_n", "invalid_n", "valid_n", "hits", "rate")} for item in current_metrics])
    secondary = {"label": "SECONDARY_NON_GATE_COMPARISON", "current": secondary_current, "cf": cf_total, "raw_hit_delta_cf_minus_current": cf_total["hits"] - secondary_current["hits"], "rate_delta_cf_minus_current": cf_total["rate"] - secondary_current["rate"]}
    suspension = {"20260926": {"status": "SUSPENDED_NO_PRE", "reason": "CF was omitted from the all-system prospective operation", "backfill": False}, "20260927": {"status": "SUSPENDED_NO_PRE", "reason": "CF was omitted from the all-system prospective operation", "backfill": False}}
    cumulative = {"formal_pre_dates_found": len(SOURCES), "formal_dates_with_eligible_races": len(recorded), "formal_races": ledger["formal_independent_race_count"], "frozen_selected_horses": cf_total["selected_n"], "cf": cf_total, "comparator": comparator_total, "raw_hit_delta": raw_delta, "rate_delta": rate_delta, "production_contamination": 0}
    verdict_record = {"protocol_version": PROTOCOL_VERSION, "protocol_sha256": protocol_hash(), "protocol_rule": minimum, "lodo_sign_stable": lodo_stable, "non_negative_date_majority": majority, "non_negative_dates": non_negative, "represented_dates": len(recorded), "production_authorization": False, "verdict": verdict, "cf_prospective_resume": "READY" if verdict == "SHADOW_ACCEPT" else "NOT_READY"}
    OUTPUT.mkdir(parents=True)
    for name, value in {"source_pre_manifest.json": source_manifest, "result_manifest.json": result_manifest, "per_date_performance.json": per_date, "cumulative_performance.json": cumulative, "leave_one_date_out.json": lodo, "secondary_current_comparison.json": secondary, "suspension_record.json": suspension, "formal_verdict.json": verdict_record}.items():
        dump(OUTPUT / name, value)
    dump(OUTPUT / "SUCCESS", {"status": "SUCCESS", "production_change": 0, "backfill_performed": False, "ledger_path": str(ledger_path.relative_to(ROOT))})
    dump(OUTPUT / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": {path.name: sha(path) for path in OUTPUT.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}})
    # The canonical ledger is updated only after every source, hash, and result join passed.
    dump(ledger_path, ledger)
    return OUTPUT


if __name__ == "__main__":
    print(run())
