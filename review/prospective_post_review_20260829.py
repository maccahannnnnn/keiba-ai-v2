"""POST-only review for the frozen 2026-08-29 Current/CF/V4 PRE artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

from review.cf_top3_rank_anchored_shadow_v1 import append_formal_post_evidence
from review.target_daily_result_list_schema_v2_validator import validate_source_pair


ROOT = Path(__file__).resolve().parents[1]
DATE = "20260829"
PRE = ROOT / "reports/prospective_prediction_20260829_v1"
THREE = ROOT / "reports/prospective_three_system_20260829_v1_retry2"
CF_ROOT = ROOT / "reports/shadow_cf_top3_rank_anchored_v1"
RAW = ROOT / "data/raw/target/daily_result_list"
OUT = ROOT / "reports/prospective_20260829_post"
VENUES = {"sapporo": "札幌", "niigata": "新潟", "chuukyou": "中京"}
ABNORMAL = {"中止", "除外", "取消", "失格"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def race_parts(race_id: str) -> tuple[str, int]:
    values = race_id.split("_")
    return VENUES[values[-2]], int(re.sub(r"R$", "", values[-1]))


def outcome(result_row: list[str], horse_number: int) -> dict:
    raw = result_row[11 + horse_number]
    valid = raw.isdigit() and int(raw) > 0
    if not valid and raw not in ABNORMAL:
        raise RuntimeError(f"UNKNOWN_RESULT_SEMANTICS:{raw}")
    return {"actual_finish": raw, "valid_result": valid, "actual_top3": bool(valid and int(raw) <= 3)}


def verify_pre_manifest() -> dict:
    manifest = json.loads((PRE / "prediction_manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        path = PRE / item["relative_path"]
        if not path.is_file() or sha(path) != item["sha256"]:
            raise RuntimeError(f"FROZEN_PRE_MANIFEST_MISMATCH:{item['relative_path']}")
    return manifest


def source_integrity(primary: Path, auxiliary: Path) -> tuple[dict, dict[tuple[str, int], list[str]]]:
    validation = validate_source_pair(primary, auxiliary, DATE)
    if validation["status"] != "PASS":
        raise RuntimeError("RESULT_SCHEMA_FAIL")
    with primary.open(encoding="cp932", newline="") as handle:
        primary_rows = list(csv.reader(handle))
    with auxiliary.open(encoding="cp932", newline="") as handle:
        auxiliary_rows = list(csv.reader(handle))
    primary_index = {(row[1], int(row[2])): row for row in primary_rows}
    auxiliary_index = {(row[1], int(row[2])): row for row in auxiliary_rows}
    if len(primary_index) != len(primary_rows) or len(auxiliary_index) != len(auxiliary_rows):
        raise RuntimeError("DUPLICATE_RESULT_RACE")
    if set(primary_index) != set(auxiliary_index):
        raise RuntimeError("RESULT_RACE_IDENTITY_UNRESOLVED")
    source_horse_mismatch = []
    for key, row in primary_index.items():
        head_count = int(row[9])
        aux_slots = auxiliary_index[key][12:12 + head_count]
        if sorted(int(value) for value in aux_slots) != list(range(1, head_count + 1)):
            source_horse_mismatch.append(key)
            continue
        for position, horse_number in enumerate(aux_slots, start=1):
            raw = row[11 + int(horse_number)]
            if raw.isdigit() and int(raw) > 0 and int(raw) != position:
                source_horse_mismatch.append(key)
                break
    if source_horse_mismatch:
        raise RuntimeError(f"RESULT_SOURCE_HORSE_CONSISTENCY_MISMATCH:{source_horse_mismatch}")
    validation.update({"source_horse_consistency": "PASS", "duplicate_race_count": 0, "unresolved_identity_count": 0})
    return validation, primary_index


def join_current(results: dict[tuple[str, int], list[str]]) -> tuple[list[dict], list[dict], dict[str, dict]]:
    index = json.loads((PRE / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    if len(index) != 17:
        raise RuntimeError("FROZEN_RACE_COUNT_MISMATCH")
    horses, buys, by_race = [], [], {}
    for item in index:
        payload = json.loads((PRE / item["artifact"]).read_text(encoding="utf-8"))
        race_id = payload["race_id"]
        venue, number = race_parts(race_id)
        row = results.get((venue, number))
        if row is None:
            raise RuntimeError(f"FROZEN_RACE_RESULT_MISSING:{race_id}")
        race_rows = []
        for horse in payload["ranked_results"]:
            number_value = int(horse["horse_number"])
            joined = {"race_id": race_id, "venue": venue, "race_number": number, "horse_number": number_value, "horse_name": horse.get("horse_name"), "rank": horse.get("rank"), "frozen_buy": horse.get("buy", horse.get("decision") == "BUY"), **outcome(row, number_value)}
            race_rows.append(joined); horses.append(joined)
            if joined["frozen_buy"]:
                buys.append(joined)
        by_race[race_id] = {"rows": race_rows, "payload": payload}
    if len(horses) != 231 or len(buys) != 16 or len({(row["race_id"], row["horse_number"]) for row in horses}) != 231:
        raise RuntimeError("FROZEN_CURRENT_SELECTION_MISMATCH")
    return horses, buys, by_race


def selected_outcomes(records: list[dict], by_race: dict[str, dict]) -> list[dict]:
    joined = []
    for record in records:
        race = by_race.get(record["race_id"])
        if race is None:
            raise RuntimeError(f"FROZEN_SELECTION_RACE_MISSING:{record['race_id']}")
        by_number = {row["horse_number"]: row for row in race["rows"]}
        selected = []
        for horse in record.get("selected_horses", record.get("cf_selected_horses", [])):
            number = int(horse["horse_number"])
            if number not in by_number:
                raise RuntimeError(f"FROZEN_SELECTION_HORSE_MISSING:{record['race_id']}:{number}")
            selected.append({**by_number[number], "shadow_ai_rank": horse.get("shadow_ai_rank")})
        pool = []
        for horse in record.get("candidate_horses", []):
            number = int(horse["horse_number"])
            if number not in by_number:
                raise RuntimeError(f"FROZEN_POOL_HORSE_MISSING:{record['race_id']}:{number}")
            pool.append({**by_number[number], "shadow_ai_rank": horse.get("shadow_ai_rank")})
        joined.append({"race_id": record["race_id"], "venue": record["venue"], "race_number": record["race_number"], "selected": selected, "candidate_pool": pool})
    return joined


def counts(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(row["actual_top3"] for row in valid)
    return {"valid": len(valid), "top3_hits": hits, "top3_rate": rate(hits, len(valid))}


def main() -> None:
    if OUT.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    manifest = verify_pre_manifest()
    primary, auxiliary = RAW / "馬番順着順_20260829.csv", RAW / "着順馬番_20260829.csv"
    validation, results = source_integrity(primary, auxiliary)
    current_horses, current_buys, by_race = join_current(results)

    cf_manifest = json.loads((THREE / "cf_selection_manifest.json").read_text(encoding="utf-8"))
    if cf_manifest.get("evidence_role") != "FORMAL_PROSPECTIVE_SHADOW" or cf_manifest.get("formal_prospective_pre_status") != "FROZEN_PENDING_POST":
        raise RuntimeError("CF_FROZEN_ROLE_OR_STATUS_MISMATCH")
    cf_records = [record for record in cf_manifest["all_race_records"] if record["shadow_eligibility"] == "ELIGIBLE"]
    cf_joined = selected_outcomes(cf_records, by_race)
    if len(cf_joined) != 4 or sum(len(row["selected"]) for row in cf_joined) != 12:
        raise RuntimeError("CF_FROZEN_SELECTION_MISMATCH")
    cf_post_records = []
    for row in cf_joined:
        selected, pool = counts(row["selected"]), counts(row["candidate_pool"])
        cf_post_records.append({"race_id": row["race_id"], "venue": row["venue"], "race_number": row["race_number"], "selected_horses": row["selected"], "candidate_pool_horses": row["candidate_pool"], "selected_valid_count": selected["valid"], "selected_top3_count": selected["top3_hits"], "SHADOW_SELECTED_TOP3_RATE": selected["top3_rate"], "candidate_pool_size": len(row["candidate_pool"]), "candidate_pool_valid_count": pool["valid"], "candidate_pool_top3_count": pool["top3_hits"], "candidate_pool_top3_rate": pool["top3_rate"], "difference": None if selected["top3_rate"] is None or pool["top3_rate"] is None else selected["top3_rate"] - pool["top3_rate"]})
    ledger = json.loads((CF_ROOT / "cumulative_ledger.json").read_text(encoding="utf-8"))
    activation = json.loads((CF_ROOT / "activation_record.json").read_text(encoding="utf-8"))
    derived_ledger = append_formal_post_evidence(ledger=ledger, date=DATE, activation_record=activation, post_records=cf_post_records, independent_race_count=len(cf_post_records))
    cf_selected = [horse for row in cf_joined for horse in row["selected"]]
    cf_pool = [horse for row in cf_joined for horse in row["candidate_pool"]]

    v4_manifest = json.loads((THREE / "v4_model_v3_reference_selection_manifest.json").read_text(encoding="utf-8"))
    if v4_manifest.get("evidence_role") != "REFERENCE_SHADOW_ONLY_PENDING_HISTORICAL_GATE":
        raise RuntimeError("V4_FROZEN_ROLE_MISMATCH")
    v4_records = [row for row in v4_manifest["races"] if row["scope_status"] == "ELIGIBLE_PLAY_CONVERGED"]
    v4_joined = selected_outcomes(v4_records, by_race)
    v4_selected = [horse for row in v4_joined for horse in row["selected"]]
    if len(v4_joined) != 8 or len(v4_selected) != 16:
        raise RuntimeError("V4_FROZEN_SELECTION_MISMATCH")
    same_volume = []
    for row in v4_joined:
        current = [horse for horse in by_race[row["race_id"]]["rows"] if horse["frozen_buy"]]
        if len(current) != len(row["selected"]):
            raise RuntimeError(f"V4_CURRENT_VOLUME_MISMATCH:{row['race_id']}")
        same_volume.append({"race_id": row["race_id"], "current_ai_top3_hits": counts(current)["top3_hits"], "v4_top3_hits": counts(row["selected"])["top3_hits"], "hit_difference": counts(row["selected"])["top3_hits"] - counts(current)["top3_hits"]})

    for item in manifest["files"]:
        if sha(PRE / item["relative_path"]) != item["sha256"]:
            raise RuntimeError(f"FROZEN_PRE_MUTATED:{item['relative_path']}")
    OUT.mkdir(parents=True)
    current_metric, cf_metric, pool_metric, v4_metric = counts(current_buys), counts(cf_selected), counts(cf_pool), counts(v4_selected)
    dump("result_source_integrity.json", {"RESULT_SOURCE_INTEGRITY": "PASS", "date": DATE, "source_files": {"primary": str(primary.relative_to(ROOT)), "auxiliary": str(auxiliary.relative_to(ROOT))}, "schema_validation": validation})
    dump("post_join_summary.json", {"frozen_race_count": 17, "frozen_horse_count": 231, "matched_horses": len(current_horses), "unmatched_horses": 0, "ambiguous_horses": 0, "invalid_results": sum(not row["valid_result"] for row in current_horses), "frozen_pre_manifest_unchanged": True})
    dump("current_ai_post.json", {"evidence_role": "CURRENT_AI_OPERATIONAL_REFERENCE", "frozen_buy_horses": current_buys, "valid_buy_horses": current_metric["valid"], "top3_hits": current_metric["top3_hits"], "BUY_TOP3_RATE": current_metric["top3_rate"], "buy_positive_races": sum(counts([horse for horse in row["rows"] if horse["frozen_buy"]])["top3_hits"] > 0 for row in by_race.values())})
    dump("cf_formal_prospective_post.json", {"candidate": "CF_TOP3_RANK_ANCHORED", "evidence_role": "FORMAL_PROSPECTIVE_SHADOW", "races": cf_post_records, "eligible_races": len(cf_post_records), "selected_horses": len(cf_selected), "valid_selected_horses": cf_metric["valid"], "selected_top3_hits": cf_metric["top3_hits"], "SHADOW_SELECTED_TOP3_RATE": cf_metric["top3_rate"], "candidate_pool_valid_horses": pool_metric["valid"], "candidate_pool_top3_hits": pool_metric["top3_hits"], "candidate_pool_top3_rate": pool_metric["top3_rate"], "pooled_difference": None if cf_metric["top3_rate"] is None or pool_metric["top3_rate"] is None else cf_metric["top3_rate"] - pool_metric["top3_rate"], "cumulative_ledger_after_20260829": derived_ledger, "lifecycle_state": "SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE"})
    dump("v4_model_v3_reference_post.json", {"evidence_role": "REFERENCE_SHADOW_ONLY_PENDING_HISTORICAL_GATE", "reference_only": True, "formal_prospective_evidence_added": 0, "historical_gate_evidence_added": 0, "races": len(v4_joined), "selected_horses": len(v4_selected), "valid_selected_horses": v4_metric["valid"], "top3_hits": v4_metric["top3_hits"], "top3_rate": v4_metric["top3_rate"], "same_volume_current_comparison": same_volume})
    dump("evidence_role_validation.json", {"status": "PASS", "current_ai": "CURRENT_AI_OPERATIONAL_REFERENCE", "cf": "FORMAL_PROSPECTIVE_SHADOW", "v4": "REFERENCE_SHADOW_ONLY_PENDING_HISTORICAL_GATE", "pre_protocol_context_excluded_from_cf_formal_count": ["20260822", "20260823"], "pooled_cross_role_kpi": False})
    dump("safety.json", {"pre_artifact_changes": 0, "prediction_reruns": 0, "selection_changes": 0, "cf_rule_changes": 0, "v4_model_changes": 0, "buy_semantics_changes": 0, "production_changes": 0, "march_result_access_count": 0, "status": "PASS"})
    summary = {"final_status": "PROSPECTIVE_POST_20260829 = COMPLETE", "current_ai": current_metric, "cf_formal": {"races": len(cf_post_records), **cf_metric, "candidate_pool": pool_metric}, "cf_cumulative": {"completed_dates": [entry["date"] for entry in derived_ledger["formal_evidence"]], "completed_eligible_races": derived_ledger["formal_independent_race_count"], "formal_selected_horses": derived_ledger["formal_evidence"][0]["selected_valid_horses"], "formal_top3_hits": derived_ledger["formal_evidence"][0]["selected_top3"], "minimum_evidence_reached": False, "lifecycle_state": "SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE"}, "v4_reference": {"races": len(v4_joined), **v4_metric, "formal_prospective_evidence_added": 0}, "result_source_integrity": "PASS", "frozen_pre_unchanged": True}
    dump("summary.json", summary)
    lines = ["# 2026-08-29 Prospective POST Review", "", "- Result source integrity: `PASS`", f"- Current AI BUY Top3: {current_metric['top3_hits']}/{current_metric['valid']} ({current_metric['top3_rate']:.2%})", f"- CF Formal Shadow Top3: {cf_metric['top3_hits']}/{cf_metric['valid']} ({cf_metric['top3_rate']:.2%}); pool {pool_metric['top3_hits']}/{pool_metric['valid']} ({pool_metric['top3_rate']:.2%})", f"- V4 reference Top3: {v4_metric['top3_hits']}/{v4_metric['valid']} ({v4_metric['top3_rate']:.2%})", "- CF lifecycle: `SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE` (1 date / 4 races; minimum 4 dates / 20 races).", "- V4 is reference only; formal prospective and Historical Gate evidence added: 0.", "- 2026-08-22 and 2026-08-23 were not added to the Formal Prospective ledger.", "- Frozen PRE was verified unchanged; Prediction reruns and rule/Production changes: 0."]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hashes = {path.name: sha(path) for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}
    dump("artifact_hashes.json", {"hashes": hashes, "self_hash_excluded": True})


if __name__ == "__main__":
    main()
