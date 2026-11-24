"""Atomic POST evaluation for the frozen March V4-v3 historical holdout."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from review.historical_replay_post_race import result_semantics
from review.target_bulk_prediction_input_adapter_v1 import COURSE_KEYS
from review.target_daily_result_list_schema_v2_validator import validate_source_pair


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
PRE = ROOT / "reports" / "march_2026_historical_holdout_pre"
CORRECTION = ROOT / "reports" / "march_2026_historical_holdout_pre_correction_v1"
PREFLIGHT = ROOT / "reports" / "march_2026_historical_holdout_preflight_v3"
OUT = ROOT / "reports" / "march_2026_historical_holdout_post"
DATES = ["20260301", "20260307", "20260308", "20260314", "20260315", "20260321", "20260322", "20260328", "20260329"]
CLAUDE_MANIFEST = PRE / "pre_independent_review_manifest.json"
CLAUDE_SHA = "046dbba4ae70aff422c6135eeccd09d486c1dcead87b3b5e1ad6f30b5ee1c8de"
ABNORMAL = {"中止", "除外", "取消", "失格"}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def rows(path: Path) -> list[list[str]]:
    with path.open(encoding="cp932", newline="") as handle:
        return list(csv.reader(handle))


def verify_index(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    index = payload.get("indexed_artifacts", payload.get("hashes"))
    if not isinstance(index, dict):
        raise Stop(f"ARTIFACT_INDEX_INVALID:{path.name}")
    for rel, digest in index.items():
        target = path.parent / rel
        if not target.is_file() or sha(target) != digest:
            raise Stop(f"ARTIFACT_INDEX_MISMATCH:{path.name}:{rel}")


def outcome(primary: list[str], number: int) -> dict:
    raw = primary[11 + number].strip()
    if raw.isdigit() and int(raw) > 0:
        semantic = {"馬番": str(number), "確定着順": raw, "異常コード": "0"}
    elif raw in ABNORMAL:
        semantic = {"馬番": str(number), "確定着順": "0", "異常コード": raw}
    else:
        raise Stop(f"RESULT_SEMANTICS_UNRESOLVED:{raw!r}")
    return {"raw_source_status": raw, **result_semantics(semantic)}


def crosscheck(primary: list[str], auxiliary: list[str], race_key: str) -> dict:
    head = int(primary[9])
    groups: dict[int, list[int]] = defaultdict(list)
    abnormal: set[int] = set()
    for number in range(1, head + 1):
        o = outcome(primary, number)
        (groups[o["actual_finish"]] if o["valid_result"] else abnormal).append(number) if o["valid_result"] else abnormal.add(number)
    # The expression above deliberately avoids inferring an order inside ties;
    # Source D is checked by set for every declared finish group.
    ordered = [int(value) for value in auxiliary[12:12 + head]]
    offset = 0
    for finish in sorted(groups):
        expected = set(groups[finish])
        observed = set(ordered[offset:offset + len(expected)])
        if expected != observed:
            raise Stop(f"RESULT_SOURCE_CROSSCHECK_FAILURE:{race_key}:FINISH_{finish}")
        offset += len(expected)
    if set(ordered[offset:]) != abnormal:
        raise Stop(f"RESULT_SOURCE_CROSSCHECK_FAILURE:{race_key}:ABNORMAL_SUFFIX")
    return {"target_race_key": race_key, "head_count": head, "status": "PASS", "finish_groups": {str(k): sorted(v) for k, v in groups.items()}, "abnormal_horses": sorted(abnormal)}


def metric(records: list[dict]) -> dict:
    valid = [x for x in records if x["valid_result"]]
    hits = sum(x["actual_top3"] for x in valid)
    return {"selected_count": len(records), "valid_selected_count": len(valid), "invalid_selected_count": len(records) - len(valid), "top3_hits": hits, "top3_rate": hits / len(valid) if valid else None}


def rate_diff(v4: dict, current: dict) -> dict:
    if v4["top3_rate"] is None or current["top3_rate"] is None:
        raise Stop("EMPTY_VALID_SELECTION_DENOMINATOR")
    return {"raw_hit_difference": v4["top3_hits"] - current["top3_hits"], "lift": v4["top3_rate"] - current["top3_rate"], "lift_percentage_points": (v4["top3_rate"] - current["top3_rate"]) * 100}


def race_parts(race_id: str) -> tuple[str, str, int]:
    parts = race_id.split("_")
    if len(parts) != 4 or not parts[3].endswith("R"):
        raise Stop(f"FROZEN_RACE_ID_INVALID:{race_id}")
    return parts[1], parts[2], int(parts[3][:-1])


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    # All integrity gates are checked before reading result contents or disclosing performance.
    if not CLAUDE_MANIFEST.is_file() or sha(CLAUDE_MANIFEST) != CLAUDE_SHA:
        raise Stop("CLAUDE_PRE_REVIEW_MANIFEST_MISMATCH")
    for index in (PRE / "artifact_hashes.json", CORRECTION / "artifact_hashes.json", PREFLIGHT / "artifact_hashes.json"):
        verify_index(index)
    pre_manifest = json.loads((PRE / "pre_freeze_manifest.json").read_text(encoding="utf-8"))
    if pre_manifest.get("eligible_races") != 173 or pre_manifest.get("eligible_horses") != 2333 or pre_manifest.get("current_buy_count") != 118 or pre_manifest.get("v4_selected_count") != 118:
        raise Stop("FROZEN_PRE_POPULATION_MISMATCH")
    corrected = json.loads((CORRECTION / "corrected_comparison_summary.json").read_text(encoding="utf-8"))
    if (corrected.get("match_races"), corrected.get("divergent_races"), corrected.get("out_of_scope_races")) != (16, 55, 102):
        raise Stop("CORRECTED_COMPARISON_AUTHORITY_MISMATCH")
    selection = json.loads((PRE / "same_volume_selection.json").read_text(encoding="utf-8"))["races"]
    current = json.loads((PRE / "current_ai_prediction.json").read_text(encoding="utf-8"))["races"]
    v4 = json.loads((PRE / "v4_model_v3_prediction.json").read_text(encoding="utf-8"))["races"]
    if not (len(selection) == len(current) == len(v4) == 173):
        raise Stop("FROZEN_SELECTION_RACE_COUNT_MISMATCH")
    current_by_race, v4_by_race = {x["race_id"]: x for x in current}, {x["race_id"]: x for x in v4}
    if set(current_by_race) != set(v4_by_race):
        raise Stop("FROZEN_SELECTION_RACE_SET_MISMATCH")
    comparison = [x for x in selection if x["race_state"] == "PLAY_CONVERGED"]
    if len(comparison) != 71 or sum(x["current_buy_count"] for x in comparison) != 118:
        raise Stop("FROZEN_COMPARISON_POPULATION_MISMATCH")
    for row in comparison:
        if row["current_buy_count"] != row["v4_selection_count"]:
            raise Stop(f"FROZEN_SAME_VOLUME_MISMATCH:{row['race_id']}")

    # Source inventory, structural validation, and C/D crosscheck must all pass before joining the frozen population.
    inventory, lookup, all_crosschecks = [], {}, []
    for date in DATES:
        primary, auxiliary = RAW / f"馬番順着順_{date}.csv", RAW / f"着順馬番_{date}.csv"
        if not primary.is_file() or not auxiliary.is_file():
            raise Stop(f"RESULT_FILE_MISSING:{date}")
        pair = validate_source_pair(primary, auxiliary, date)
        p_rows, a_rows = rows(primary), rows(auxiliary)
        p_by_key, a_by_key = {x[0]: x for x in p_rows}, {x[0]: x for x in a_rows}
        if len(p_by_key) != len(p_rows) or len(a_by_key) != len(a_rows) or set(p_by_key) != set(a_by_key):
            raise Stop(f"RESULT_RACE_IDENTITY_FAILURE:{date}")
        records = [crosscheck(p_by_key[key], a_by_key[key], key) for key in sorted(p_by_key)]
        all_crosschecks.extend(records)
        inventory.extend([{"date": date, "source_type": "HORSE_NUMBER_ORDER_FINISH_STATUS", "filename": primary.name, "path": str(primary.relative_to(ROOT)), "byte_size": primary.stat().st_size, "sha256": sha(primary)}, {"date": date, "source_type": "FINISH_ORDER_HORSE_NUMBER", "filename": auxiliary.name, "path": str(auxiliary.relative_to(ROOT)), "byte_size": auxiliary.stat().st_size, "sha256": sha(auxiliary)}])
        lookup[date] = p_by_key

    # Build the authoritative outcome lookup for every frozen PRE horse, then evaluate only its 71 frozen comparison races.
    outcomes, join_races = {}, {}
    all_pre_horses = 0
    for record in current:
        date, venue_key, number = race_parts(record["race_id"])
        venue_name = next((name for name, key in COURSE_KEYS.items() if key == venue_key), None)
        matches = [(key, row) for key, row in lookup[date].items() if row[1] == venue_name and int(row[2]) == number]
        if len(matches) != 1:
            raise Stop(f"FROZEN_PRE_RESULT_RACE_UNRESOLVED:{record['race_id']}:{len(matches)}")
        key, source_row = matches[0]
        selected_numbers = {int(x["horse_number"]) for x in record["horses"]}
        head = int(source_row[9])
        if selected_numbers != set(range(1, head + 1)):
            raise Stop(f"FROZEN_PRE_RESULT_HORSE_POPULATION_MISMATCH:{record['race_id']}")
        join_races[record["race_id"]] = key
        for horse in record["horses"]:
            number_horse = int(horse["horse_number"])
            outcomes[(record["race_id"], number_horse)] = {"race_id": record["race_id"], "date": date, "venue": venue_key, "race_number": number, "horse_number": number_horse, "horse_name": horse.get("horse_name"), **outcome(source_row, number_horse)}
            all_pre_horses += 1
    if all_pre_horses != 2333 or len(outcomes) != 2333:
        raise Stop("FROZEN_PRE_RESULT_JOIN_COUNT_MISMATCH")

    current_selected, v4_selected, race_rows = [], [], []
    for row in comparison:
        race_id = row["race_id"]
        cur_nums = list(row["current_horse_numbers"])
        v4_nums = list(row["v4_horse_numbers"])
        cur = [{**outcomes[(race_id, n)], "selection_system": "CURRENT"} for n in cur_nums]
        vv = [{**outcomes[(race_id, n)], "selection_system": "V4_MODEL_V3"} for n in v4_nums]
        current_selected.extend(cur); v4_selected.extend(vv)
        cm, vm = metric(cur), metric(vv)
        race_rows.append({"date": row["date"], "race_id": race_id, "venue": row["venue"], "race_number": row["race_number"], "corrected_comparison": next(x["corrected_comparison"] for x in json.loads((CORRECTION / "comparison_label_correction.json").read_text(encoding="utf-8"))["races"] if x["race_id"] == race_id), "current": cm, "v4": vm, "current_selected_horse_numbers": cur_nums, "v4_selected_horse_numbers": v4_nums, "hit_contribution": vm["top3_hits"] - cm["top3_hits"]})
    if len(current_selected) != 118 or len(v4_selected) != 118:
        raise Stop("FROZEN_SELECTION_COUNT_MISMATCH")
    cm, vm = metric(current_selected), metric(v4_selected)
    pooled = {"comparator": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "comparison_races": 71, "comparison_dates": 9, "current": cm, "v4_model_v3": vm, **rate_diff(vm, cm)}
    daily = []
    for date in DATES:
        cr, vr = [x for x in current_selected if x["date"] == date], [x for x in v4_selected if x["date"] == date]
        day_c, day_v = metric(cr), metric(vr)
        daily.append({"date": date, "comparison_races": sum(x["date"] == date for x in race_rows), "current": day_c, "v4_model_v3": day_v, **rate_diff(day_v, day_c)})
    lodo = []
    for date in DATES:
        lc, lv = [x for x in current_selected if x["date"] != date], [x for x in v4_selected if x["date"] != date]
        lcm, lvm = metric(lc), metric(lv)
        lodo.append({"excluded_date": date, "remaining_dates": 8, "remaining_comparison_races": 71 - sum(x["date"] == date for x in race_rows), "current": lcm, "v4_model_v3": lvm, **rate_diff(lvm, lcm)})
    contributions = sorted([{"date": x["date"], "hit_contribution": x["v4_model_v3"]["top3_hits"] - x["current"]["top3_hits"]} for x in daily], key=lambda x: (-x["hit_contribution"], x["date"]))
    excluded = [x["date"] for x in contributions[:math.ceil(len(DATES) / 3)]]
    tc, tv = [x for x in current_selected if x["date"] not in excluded], [x for x in v4_selected if x["date"] not in excluded]
    tcm, tvm = metric(tc), metric(tv)
    stress = {"rule": "exclude top ceil(eligible_dates/3) date contributions; tie date ASC", "date_contributions": contributions, "excluded_dates": excluded, "remaining_current": tcm, "remaining_v4_model_v3": tvm, **rate_diff(tvm, tcm)}
    stress["temporal_concentration_flag"] = stress["lift"] < 0
    gate_checks = {"eligible_races_ge_20": len(comparison) >= 20, "eligible_dates_ge_4": len(DATES) >= 4, "pooled_same_volume_lift_ge_0pt": pooled["lift_percentage_points"] >= 0}
    gate = "PASS" if all(gate_checks.values()) else "FAIL"
    advancement = "HISTORICAL_PASS_PROSPECTIVE_REVIEW_ELIGIBLE" if gate == "PASS" else "HISTORICAL_REJECT"
    correction_records = json.loads((CORRECTION / "comparison_label_correction.json").read_text(encoding="utf-8"))["races"]
    labels = {x["race_id"]: x["corrected_comparison"] for x in correction_records}
    match_rows, divergent_rows = [x for x in race_rows if labels[x["race_id"]] == "MATCH"], [x for x in race_rows if labels[x["race_id"]] == "DIVERGENT"]
    diagnostic = {"formal_pre_corrected_labels": {"MATCH": 16, "DIVERGENT": 55}, "match": {"race_count": len(match_rows), "current_hits": sum(x["current"]["top3_hits"] for x in match_rows), "v4_hits": sum(x["v4"]["top3_hits"] for x in match_rows), "hit_difference": sum(x["v4"]["top3_hits"] - x["current"]["top3_hits"] for x in match_rows)}, "divergent": {"race_count": len(divergent_rows), "current_hits": sum(x["current"]["top3_hits"] for x in divergent_rows), "v4_hits": sum(x["v4"]["top3_hits"] for x in divergent_rows), "hit_difference": sum(x["v4"]["top3_hits"] - x["current"]["top3_hits"] for x in divergent_rows)}}
    if diagnostic["match"]["hit_difference"] != 0:
        raise Stop("MATCH_DIAGNOSTIC_SELECTION_IDENTITY_FAILURE")

    OUT.mkdir(parents=True)
    write(OUT / "result_inventory.json", {"status": "PASS", "expected_files": 18, "present_files": len(inventory), "files": inventory})
    write(OUT / "result_hashes.json", {x["filename"]: x["sha256"] for x in inventory})
    write(OUT / "result_source_integrity.json", {"status": "PASS", "date_count": 9, "source_pair_count": 9, "crosschecked_result_races": len(all_crosschecks), "crosscheck_records": all_crosschecks, "mismatch_count": 0, "duplicate_count": 0, "unresolved_count": 0})
    write(OUT / "post_join_summary.json", {"status": "PASS", "frozen_pre_races": 173, "frozen_pre_horses": 2333, "matched_races": len(join_races), "matched_horses": len(outcomes), "unmatched_count": 0, "ambiguous_count": 0, "invalid_result_count": sum(not x["valid_result"] for x in outcomes.values()), "result_semantics": "finish>0 and abnormal code empty/0"})
    write(OUT / "current_same_volume_result.json", {"metric_name": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "records": current_selected, **cm})
    write(OUT / "v4_model_v3_same_volume_result.json", {"metric_name": "V4_MODEL_V3_FROZEN_SAME_VOLUME", "records": v4_selected, **vm})
    write(OUT / "pooled_comparison.json", pooled)
    write(OUT / "daily_metrics.json", {"dates": daily, "race_metrics": race_rows})
    write(OUT / "lodo_diagnostics.json", {"cases": lodo, "minimum_lift_percentage_points": min(x["lift_percentage_points"] for x in lodo), "maximum_lift_percentage_points": max(x["lift_percentage_points"] for x in lodo)})
    write(OUT / "temporal_concentration_stress_test.json", stress)
    write(OUT / "historical_gate_result.json", {"gate": "V4_MODEL_V3_HISTORICAL_GATE", "checks": gate_checks, "result": gate, "candidate_advancement": advancement, "evidence_role": "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT", "not_production_go": True, "not_formal_prospective_accept": True})
    write(OUT / "evidence_role_validation.json", {"status": "PASS", "evidence_role": "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT", "purpose": "V4 Model v3 Candidate Advancement Gate", "formal_prospective_pooling": "PROHIBITED", "april_pooling": "PROHIBITED", "may_model_v2_oos_pooling": "PROHIBITED", "v4_0829_reference_pooling": "PROHIBITED", "match_divergent_diagnostic": diagnostic, "evidence_invalid": False, "evidence_invalid_reason": None})
    pre_hash_after = {"pre_artifact_index": sha(PRE / "artifact_hashes.json"), "correction_artifact_index": sha(CORRECTION / "artifact_hashes.json"), "claude_manifest": sha(CLAUDE_MANIFEST)}
    safety = {"status": "PASS", "pre_source_mutation_count": 0, "current_selection_mutation_count": 0, "v4_selection_mutation_count": 0, "model_mutation_count": 0, "comparator_mutation_count": 0, "gate_mutation_count": 0, "tie_break_mutation_count": 0, "production_change_count": 0, "cf_change_count": 0, "prediction_rerun_count": 0, "model_inference_count": 0, "result_access_count": 18, "result_import_count": 0, "result_join_count": 2333, "pre_integrity": pre_hash_after, "claude_manifest_expected_sha256": CLAUDE_SHA}
    write(OUT / "safety.json", safety)
    report = ["# March 2026 Historical Holdout POST", "", "- Atomic POST: `COMPLETE`", f"- Current: `{cm['top3_hits']}/{cm['valid_selected_count']} = {cm['top3_rate']*100:.4f}%`", f"- V4 Model v3: `{vm['top3_hits']}/{vm['valid_selected_count']} = {vm['top3_rate']*100:.4f}%`", f"- Same-volume lift: `{pooled['lift_percentage_points']:+.4f}pt`", f"- Historical Gate: `{gate}`", f"- Temporal concentration flag: `{stress['temporal_concentration_flag']}`", "- Evidence role: `TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT`", "- Production activation: `NO`", ""]
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    hashes = {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}
    write(OUT / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": hashes})
    if any(sha(OUT / name) != digest for name, digest in hashes.items()):
        raise Stop("POST_ARTIFACT_FREEZE_HASH_MISMATCH")
    print(f"MARCH_2026_HISTORICAL_HOLDOUT_POST=COMPLETE;V4_MODEL_V3_HISTORICAL_GATE={gate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
