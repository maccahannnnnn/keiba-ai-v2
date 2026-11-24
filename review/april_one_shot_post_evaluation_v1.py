"""One-shot, result-authorized POST evaluation for frozen April PRE only."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.historical_replay_post_race import result_semantics
from review.target_bulk_prediction_input_adapter_v1 import COURSE_CODES
from review.target_daily_result_list_schema_v2_validator import validate_source_pair


PRE = ROOT / "reports" / "april_2026_retrospective_external_holdout_v2" / "pre_execution_full_8date_v1"
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
OUT = ROOT / "reports" / "april_2026_retrospective_external_holdout_v2" / "one_shot_post_evaluation_v1"
DATES = ("20260404", "20260405", "20260411", "20260412", "20260418", "20260419", "20260425", "20260426")
EXPECTED = {
    "pre_manifest.json": "04202da16c89d90792900e092a382984b94a0ed14f3818c73112e1c812cb9c8b",
    "buy_gate_trace.json": "d06dc400262754f2bf4492deeb2035bea004e74a7bb732000114ba4f0de90642",
    "v3_pre_selections.json": "967377c6a4470a2440d4436702a9d33b85967e50511188d779763929ca26f3fa",
    "cf_pre_selections.json": "93caa672c1f4809d540ec5266454afcc9be03d382d32265c37b11da6b8d3412d",
    "artifact_hashes.json": "c6835f2c982db425bd5125e36133be0610af29c54af349094e39a14074610add",
}
ABNORMAL = {"中止", "除外", "取消", "失格"}


class Stop(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}:{detail}")
        self.code, self.detail = code, detail


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> Path:
    path = OUT / name
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def read_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="cp932", newline="") as handle:
        return list(csv.reader(handle))


def pre_immutable() -> dict:
    for name, expected in EXPECTED.items():
        if not (PRE / name).is_file() or sha(PRE / name) != expected:
            raise Stop("APRIL_POST_PRE_IMMUTABILITY_FAILURE", name)
    index = json.loads((PRE / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
    for relative, expected in index.items():
        if not (PRE / relative).is_file() or sha(PRE / relative) != expected:
            raise Stop("APRIL_POST_PRE_IMMUTABILITY_FAILURE", relative)
    manifest = json.loads((PRE / "pre_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "APRIL_PRE_FROZEN" or manifest.get("prediction", {}).get("race_count") != 152 or manifest.get("prediction", {}).get("horse_count") != 2035:
        raise Stop("APRIL_POST_PRE_IMMUTABILITY_FAILURE", "FROZEN_POPULATION")
    return manifest


def result_inventory() -> tuple[dict, dict[str, dict]]:
    records, lookup = [], {}
    for date in DATES:
        c = RAW / f"馬番順着順_{date}.csv"
        d = RAW / f"着順馬番_{date}.csv"
        if not c.is_file() or not d.is_file():
            raise Stop("APRIL_POST_RESULT_INVENTORY_FAILURE", f"MISSING:{date}")
        try:
            pair = validate_source_pair(c, d, date)
        except Exception as exc:
            raise Stop("APRIL_POST_RESULT_CROSSCHECK_FAILURE", f"{date}:{exc}") from exc
        c_rows, d_rows = read_rows(c), read_rows(d)
        by_c, by_d = {row[0]: row for row in c_rows}, {row[0]: row for row in d_rows}
        if len(by_c) != len(c_rows) or len(by_d) != len(d_rows):
            raise Stop("APRIL_POST_RESULT_INVENTORY_FAILURE", f"DUPLICATE_RACE:{date}")
        records.append({"date": date, "source_c": {"path": str(c.relative_to(ROOT)), "sha256": sha(c)}, "source_d": {"path": str(d.relative_to(ROOT)), "sha256": sha(d)}, "schema_v2_structural": pair})
        lookup[date] = {"c": by_c, "d": by_d, "pair": pair}
    return {"status": "PASS", "dates": records, "file_count": len(records) * 2}, lookup


def source_c_outcome(row: list[str], horse_number: int) -> dict:
    raw = row[11 + horse_number].strip()
    if raw.isdigit() and int(raw) > 0:
        semantic_row = {"馬番": str(horse_number), "確定着順": raw, "異常コード": "0"}
    elif raw in ABNORMAL:
        semantic_row = {"馬番": str(horse_number), "確定着順": "0", "異常コード": raw}
    else:
        raise Stop("APRIL_POST_VALID_RESULT_SEMANTIC_MISMATCH", f"SOURCE_C_STATUS:{raw!r}")
    return {"raw_source_c_status": raw, **result_semantics(semantic_row)}


def crosscheck_one(c_row: list[str], d_row: list[str], race_key: str) -> dict:
    head_count = int(c_row[9])
    c_normal: dict[int, list[int]] = defaultdict(list)
    abnormal = set()
    for horse_number in range(1, head_count + 1):
        outcome = source_c_outcome(c_row, horse_number)
        if outcome["valid_result"]:
            c_normal[outcome["actual_finish"]].append(horse_number)
        else:
            abnormal.add(horse_number)
    d_sequence = [int(value) for value in d_row[12:12 + head_count]]
    expected_prefix = [number for finish in sorted(c_normal) for number in c_normal[finish]]
    prefix = d_sequence[:len(expected_prefix)]
    offset = 0
    for finish in sorted(c_normal):
        group = c_normal[finish]
        observed = prefix[offset:offset + len(group)]
        if set(observed) != set(group):
            raise Stop("APRIL_POST_RESULT_CROSSCHECK_FAILURE", f"FINISH_ORDER:{race_key}:{finish}")
        offset += len(group)
    if set(d_sequence[len(expected_prefix):]) != abnormal:
        raise Stop("APRIL_POST_RESULT_CROSSCHECK_FAILURE", f"ABNORMAL_SUFFIX:{race_key}")
    return {"target_race_key": race_key, "head_count": head_count, "normal_finish_groups": {str(key): sorted(value) for key, value in c_normal.items()}, "source_d_finish_order_sequence": d_sequence, "status": "PASS"}


def reconcile(lookup: dict[str, dict]) -> dict:
    records = []
    for date, data in lookup.items():
        c, d = data["c"], data["d"]
        if set(c) != set(d):
            raise Stop("APRIL_POST_RESULT_CROSSCHECK_FAILURE", f"RACE_SET:{date}")
        for key in sorted(c):
            records.append(crosscheck_one(c[key], d[key], key))
    return {"status": "PASS", "race_count": len(records), "source_d_role": "FINISH_ORDER_HORSE_NUMBER_STRUCTURAL_CROSSCHECK_ONLY", "records": records}


def venue_number(race_id: str) -> tuple[str, int]:
    parts = race_id.split("_")
    if len(parts) != 4 or not parts[3].endswith("R"):
        raise Stop("APRIL_POST_RESULT_JOIN_FAILURE", f"RACE_ID:{race_id}")
    return parts[2], int(parts[3][:-1])


def c_race_for_pre(race_id: str, lookup: dict[str, dict]) -> tuple[str, list[str]]:
    date = race_id.split("_")[1]
    venue_key, number = venue_number(race_id)
    venue = next((name for name, key in COURSE_CODES.items() if key == venue_key), None)
    matches = [(key, row) for key, row in lookup[date]["c"].items() if row[1] == venue and int(row[2]) == number]
    if len(matches) != 1:
        raise Stop("APRIL_POST_RESULT_JOIN_FAILURE", f"RACE:{race_id}:{len(matches)}")
    return matches[0]


def metric(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    top3 = [row for row in valid if row["actual_top3"]]
    return {"top3_count": len(top3), "valid_count": len(valid), "invalid_result_count": len(rows) - len(valid), "top3_rate": len(top3) / len(valid) if valid else None}


def classify(lift: float | None, eligible_races: int) -> str:
    if eligible_races < 10:
        return "RECORD_ONLY_TOO_SMALL"
    if lift is None:
        return "INCONCLUSIVE"
    if lift >= 0.03:
        return "SUPPORTIVE"
    if lift < 0:
        return "UNSUPPORTIVE"
    return "INCONCLUSIVE"


def schema_payload(evaluation: dict) -> dict:
    return {"evidence_type": "RETROSPECTIVE_EXTERNAL_HOLDOUT", "prospective_ledger_member": False, "production_unchanged": True,
            "candidate_frozen": True, "result_access_before_freeze": False, "post_outcome_tuning_allowed": False,
            "backfill_allowed": False, "may_2026_status": "UNTOUCHED_RESERVE", "entries": [], "evaluation": evaluation}


def schema_valid(payload: dict) -> bool:
    return payload["evidence_type"] == "RETROSPECTIVE_EXTERNAL_HOLDOUT" and payload["prospective_ledger_member"] is False and payload["production_unchanged"] is True and payload["candidate_frozen"] is True and payload["result_access_before_freeze"] is False and payload["post_outcome_tuning_allowed"] is False and payload["backfill_allowed"] is False and payload["may_2026_status"] == "UNTOUCHED_RESERVE" and payload["entries"] == []


def run() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        frozen = pre_immutable()
        inventory, result_lookup = result_inventory()
        cross = reconcile(result_lookup)
        v3 = json.loads((PRE / "v3_pre_selections.json").read_text(encoding="utf-8"))["records"]
        cf = json.loads((PRE / "cf_pre_selections.json").read_text(encoding="utf-8"))["records"]
        if len(v3) != 152 or len(cf) != 152:
            raise Stop("APRIL_POST_POPULATION_IDENTITY_FAILURE", "SELECTION_RACE_COUNT")
        pre_horses, candidate_pool, v3_selected, cf_selected, current_unconverged_buys = [], [], [], [], []
        result_race_keys = {}
        for artifact in frozen["prediction"]["artifacts"]:
            payload = json.loads((ROOT / artifact["path"]).read_text(encoding="utf-8"))
            race_id = payload["race_id"]
            race_key, c_row = c_race_for_pre(race_id, result_lookup)
            result_race_keys[race_id] = race_key
            for horse in payload["ranked_results"]:
                number = int(horse["horse_number"])
                row = {"race_id": race_id, "target_race_key": race_key, "horse_number": number, "horse_name": horse.get("horse_name"), "rank": horse.get("rank"), "current_buy": bool(horse.get("buy")), **source_c_outcome(c_row, number)}
                pre_horses.append(row)
        if len(pre_horses) != 2035 or len({(row["race_id"], row["horse_number"]) for row in pre_horses}) != 2035:
            raise Stop("APRIL_POST_RESULT_JOIN_FAILURE", "FROZEN_HORSE_IDENTITY")
        outcomes = {(row["race_id"], row["horse_number"]): row for row in pre_horses}
        v3_eligible = [row for row in v3 if row["eligible"]]
        cf_eligible = [row for row in cf if row["shadow_eligibility"] == "ELIGIBLE"]
        if len(v3_eligible) != 35 or len(cf_eligible) != 35 or {row["race_id"] for row in v3_eligible} != {row["race_id"] for row in cf_eligible}:
            raise Stop("APRIL_POST_POPULATION_IDENTITY_FAILURE", "ELIGIBLE_RACE_SET")
        for v3_row, cf_row in zip(sorted(v3_eligible, key=lambda row: row["race_id"]), sorted(cf_eligible, key=lambda row: row["race_id"])):
            v_pool = {(row["horse_number"], row["shadow_ai_rank"]) for row in v3_row["all_candidates"]}
            c_pool = {(row["horse_number"], row["shadow_ai_rank"]) for row in cf_row["candidate_horses"]}
            if v_pool != c_pool or len(v_pool) < 4:
                raise Stop("APRIL_POST_POPULATION_IDENTITY_FAILURE", v3_row["race_id"])
            for horse, rank in sorted(v_pool):
                candidate_pool.append({**outcomes[(v3_row["race_id"], horse)], "shadow_ai_rank": rank})
            for selected in v3_row["selected"]:
                v3_selected.append({**outcomes[(v3_row["race_id"], selected["horse_number"])], "shadow_ai_rank": selected["shadow_ai_rank"], "predicted_top3_probability": selected["predicted_top3_probability"]})
            for selected in cf_row["cf_selected_horses"]:
                cf_selected.append({**outcomes[(cf_row["race_id"], selected["horse_number"])], "shadow_ai_rank": selected["shadow_ai_rank"]})
            current_unconverged_buys.extend([row for row in pre_horses if row["race_id"] == v3_row["race_id"] and row["current_buy"]])
        if len(candidate_pool) != 162 or len(v3_selected) != 105 or len(cf_selected) != 105:
            raise Stop("APRIL_POST_POPULATION_IDENTITY_FAILURE", "FROZEN_COUNTS")
        pool_metric, v3_metric, cf_metric = metric(candidate_pool), metric(v3_selected), metric(cf_selected)
        v3_lift = v3_metric["top3_rate"] - pool_metric["top3_rate"] if v3_metric["top3_rate"] is not None and pool_metric["top3_rate"] is not None else None
        cf_lift = cf_metric["top3_rate"] - pool_metric["top3_rate"] if cf_metric["top3_rate"] is not None and pool_metric["top3_rate"] is not None else None
        all_current_buys = [row for row in pre_horses if row["current_buy"]]
        current_35 = metric(current_unconverged_buys)
        current_152 = metric(all_current_buys)
        whole = {"scope": "SECONDARY_ONLY_35_PLAY_UNCONVERGED_4PLUS_RACES", "current": {"buy_count": len(current_unconverged_buys), **current_35}, "v3_counterfactual": {"buy_count": len(v3_selected), **v3_metric}, "cf_counterfactual": {"buy_count": len(cf_selected), **cf_metric}, "v3_buy_count_delta": len(v3_selected) - len(current_unconverged_buys), "cf_buy_count_delta": len(cf_selected) - len(current_unconverged_buys), "v3_absolute_rate_delta": None if current_35["top3_rate"] is None or v3_metric["top3_rate"] is None else v3_metric["top3_rate"] - current_35["top3_rate"], "cf_absolute_rate_delta": None if current_35["top3_rate"] is None or cf_metric["top3_rate"] is None else cf_metric["top3_rate"] - current_35["top3_rate"]}
        pool_eval = {"scope": "PRIMARY_SELECTOR_EVALUATION_SCOPE_35_PLAY_UNCONVERGED_4PLUS_RACES", "eligible_race_count": 35, "candidate_pool": candidate_pool, **pool_metric}
        v3_eval = {"scope": "PRIMARY_SELECTOR_EVALUATION_SCOPE_35_PLAY_UNCONVERGED_4PLUS_RACES", "selected_horses": v3_selected, **v3_metric, "selection_lift": v3_lift, "selection_lift_percentage_points": None if v3_lift is None else v3_lift * 100, "april_classification": classify(v3_lift, 35), "temporal_interpretation": "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT"}
        cf_eval = {"scope": "PRIMARY_SELECTOR_EVALUATION_SCOPE_35_PLAY_UNCONVERGED_4PLUS_RACES", "selected_horses": cf_selected, **cf_metric, "selection_lift": cf_lift, "selection_lift_percentage_points": None if cf_lift is None else cf_lift * 100, "april_classification": classify(cf_lift, 35), "april_plus3_interpretation": "APRIL_COMMON_REPORTING_SCALE_ONLY_NOT_CF_PROSPECTIVE_ACCEPT_REJECT"}
        v3_evidence, cf_evidence, whole_evidence = schema_payload(v3_eval), schema_payload(cf_eval), schema_payload(whole)
        if not all(schema_valid(item) for item in (v3_evidence, cf_evidence, whole_evidence)):
            raise Stop("APRIL_POST_EVIDENCE_SCHEMA_FAILURE", "SCHEMA_CONSTANTS")
        write("result_inventory.json", inventory)
        write("result_pair_reconciliation.json", cross)
        write("result_join_manifest.json", {"status": "PASS", "matched_horse_count": len(pre_horses), "missing_count": 0, "ambiguous_count": 0, "race_mapping_count": len(result_race_keys), "source_c_semantic_authority": True, "source_d_semantics_used": False})
        write("valid_result_manifest.json", {"horses": pre_horses, "invalid_result_count": sum(not row["valid_result"] for row in pre_horses)})
        write("candidate_pool_evaluation.json", pool_eval)
        write("v3_post_evaluation.json", v3_evidence)
        write("cf_post_evaluation.json", cf_evidence)
        write("whole_system_counterfactual.json", whole_evidence)
        write("current_system_reference_152r.json", {"scope": "CURRENT_SYSTEM_REFERENCE_SCOPE_152_APRIL_PREDICTION_RACES", "current_buy_count": len(all_current_buys), **current_152})
        manifest = {"status": "APRIL_ONE_SHOT_POST_EVALUATION_COMPLETE", "pre_immutability": "PASS", "pre_root": str(PRE.relative_to(ROOT)), "pre_hashes": EXPECTED, "result_inventory": "PASS", "source_c_d_structural_reconciliation": "PASS", "source_c_d_simple_semantic_crosscheck": "PASS", "result_join": {"status": "PASS", "matched_horse_count": len(pre_horses), "missing_count": 0, "ambiguous_count": 0}, "primary_population": {"eligible_races": 35, "candidate_horses": 162, "v3_selected": 105, "cf_selected": 105}, "evidence_band": "MEANINGFUL_RETROSPECTIVE_EXTERNAL_HOLDOUT", "schemas": {"v3": "PASS", "cf": "PASS", "whole_system": "PASS"}, "post_orchestration": {"path": "review/april_one_shot_post_evaluation_v1.py", "sha256": sha(Path(__file__))}, "generated_at": datetime.now(timezone.utc).isoformat(), "access_and_change_counts": {"prediction_rerun": 0, "pre_modification": 0, "v3_semantic_change": 0, "cf_semantic_change": 0, "production_change": 0, "may_access": 0}}
        write("post_evaluation_manifest.json", manifest)
        (OUT / "report.md").write_text("# April 2026 One-Shot POST Evaluation\n\n`APRIL_ONE_SHOT_POST_EVALUATION_COMPLETE`。詳細はJSON成果物を参照。Outcome確認後の再試行・調整は行わない。\n", encoding="utf-8")
        hashes = {str(path.relative_to(OUT)): sha(path) for path in sorted(OUT.glob("*")) if path.is_file()}
        write("artifact_hashes.json", {"indexed_artifacts": hashes, "self_hash_excluded": True})
        indexed = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
        if any(sha(OUT / name) != expected for name, expected in indexed.items()):
            raise Stop("APRIL_POST_ARTIFACT_HASH_FAILURE", "INDEX")
        return OUT
    except Stop as exc:
        write("post_evaluation_manifest.json", {"status": "STOP_WITH_REASON", "reason_code": exc.code, "detail": exc.detail, "access_and_change_counts": {"prediction_rerun": 0, "pre_modification": 0, "v3_semantic_change": 0, "cf_semantic_change": 0, "production_change": 0, "may_access": 0}})
        return OUT


if __name__ == "__main__":
    print(run())
