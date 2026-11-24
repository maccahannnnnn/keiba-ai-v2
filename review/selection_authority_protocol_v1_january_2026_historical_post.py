"""One-shot POST join for the frozen January Selection Authority PRE.

This module never calls prediction, selection, model inference, or training.
It only validates frozen PRE/source authorities and joins Daily Result List
outcomes to already-frozen Current and Selection selections.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from review.historical_replay_post_race import result_semantics
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "reports" / "selection_authority_protocol_v1_january_2026_historical_holdout"
PRE = BASE / "selection_authority_pre"
CURRENT = BASE / "current_pre"
OUT = BASE / "post"
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
SOURCE_MANIFEST = OUT / "result_source_manifest.json"
DATES = ["20260104", "20260105", "20260110", "20260111", "20260112", "20260117", "20260118", "20260124", "20260125", "20260131"]
EXPECTED = {
    "january_protocol": (ROOT / "docs" / "selection_authority_protocol_v1_january_2026_historical_holdout.json", "77bccaf6d3f01e14b25c3e7564d7fd084f93511e64c021dd752269ab5bf00941"),
    "parent_protocol": (ROOT / "docs" / "selection_authority_protocol_v1.json", "01bad1cc325f0ec1e35cb149bc65e20c07582c6d4013f0e344c0d521bb21106f"),
    "population": (BASE / "realized_population_manifest.json", "3388c234a1aa42f3bf10a2bc51576d33dc9067cb4415dd8fffdf95d4c1e94e45"),
    "current_pre": (CURRENT / "current_pre_freeze_manifest.json", "ba840efbb5e3b4551386412e3ebedd9038e3274d2460cda525e5fea2a5b55139"),
    "selection_semantic": (PRE / "semantic_selection.json", "4c712fecdd101153a8e5d0db687e6d52b48aa2257afa22fe26e0de2cbbb4fcd5"),
    "selection_manifest": (PRE / "manifest.json", "98c821b7fe630f37ccf226a00647706df04f9114dbcdb3854ec44bc57a8d1368"),
    "selection_index": (PRE / "artifact_index.json", "0fcd8fbd60d21e0af7a87d828e507690e884aa38aef3dcc9e77c466d157911d0"),
    "model": (ROOT / "reports" / "ml_v4_buy_selection_model_v5" / "model.joblib", "d3b17e3022768690d0b1013ab131b35c5a64aa8e4a816fb3e1349bad95fb87a2"),
}
ABNORMAL = {"中止", "除外", "取消", "失格"}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stop(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def read_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="cp932", newline="") as handle:
        return list(csv.reader(handle))


def verify_pre() -> dict[str, str]:
    observed = {}
    for label, (path, expected) in EXPECTED.items():
        actual = sha(path) if path.is_file() else None
        if actual != expected:
            raise Stop(f"FROZEN_PRE_AUTHORITY_MISMATCH:{label}")
        observed[label] = actual
    index = read_json(PRE / "artifact_index.json").get("indexed_artifacts")
    if not isinstance(index, dict) or any(sha(PRE / name) != digest for name, digest in index.items()):
        raise Stop("FROZEN_SELECTION_PRE_INDEX_MISMATCH")
    return observed


def verify_result_source_manifest() -> tuple[dict[str, Any], dict[tuple[str, str], Path]]:
    manifest = read_json(SOURCE_MANIFEST)
    files = manifest.get("files")
    if manifest.get("status") != "FROZEN_BEFORE_RESULT_PARSE_OR_JOIN" or not isinstance(files, list) or len(files) != 20:
        raise Stop("RESULT_SOURCE_MANIFEST_INVALID")
    locations: dict[tuple[str, str], Path] = {}
    for item in files:
        date, file_type, relative = item.get("date"), item.get("file_type"), item.get("path")
        if date not in DATES or file_type not in {"PRIMARY_HORSE_NUMBER_ORDER_FINISH", "AUXILIARY_FINISH_ORDER_HORSE_NUMBER"} or not isinstance(relative, str):
            raise Stop("RESULT_SOURCE_MANIFEST_ENTRY_INVALID")
        key = (date, file_type)
        path = ROOT / relative
        if key in locations or not path.is_file() or path.stat().st_size != item.get("size") or sha(path) != item.get("sha256"):
            raise Stop(f"RESULT_SOURCE_MUTATION_OR_DUPLICATE:{date}:{file_type}")
        locations[key] = path
    if set(date for date, _ in locations) != set(DATES) or len(locations) != 20:
        raise Stop("STOP_RESULT_SOURCE_INCOMPLETE")
    return manifest, locations


def outcome(primary_row: list[str], horse_number: int) -> dict[str, Any]:
    raw = primary_row[11 + horse_number].strip()
    if raw.isdigit() and int(raw) > 0:
        semantic = {"馬番": str(horse_number), "確定着順": raw, "異常コード": "0"}
    elif raw in ABNORMAL or raw == "0":
        semantic = {"馬番": str(horse_number), "確定着順": "0", "異常コード": raw if raw else "0"}
    else:
        raise Stop(f"UNKNOWN_INVALID_RESULT_SEMANTICS:{raw!r}")
    return {"raw_result_value": raw, **result_semantics(semantic)}


def crosscheck(primary: list[str], auxiliary: list[str], key: str) -> dict[str, Any]:
    head = int(primary[9]); by_finish: dict[int, set[int]] = defaultdict(set); invalid: set[int] = set()
    for number in range(1, head + 1):
        item = outcome(primary, number)
        if item["valid_result"]:
            by_finish[int(item["actual_finish"])].add(number)
        else:
            invalid.add(number)
    shown = [int(value) for value in auxiliary[12:12 + head]]; offset = 0
    for finish in sorted(by_finish):
        expected = by_finish[finish]; actual = set(shown[offset:offset + len(expected)])
        if actual != expected:
            raise Stop(f"RESULT_SOURCE_DISAGREEMENT:{key}:FINISH_{finish}")
        offset += len(expected)
    if set(shown[offset:]) != invalid:
        raise Stop(f"RESULT_SOURCE_DISAGREEMENT:{key}:ABNORMAL_SUFFIX")
    return {"target_race_key": key, "status": "PASS", "head_count": head, "invalid_horse_numbers": sorted(invalid)}


def load_results(locations: dict[tuple[str, str], Path]) -> tuple[dict[str, dict[tuple[str, int], tuple[str, list[str]]]], list[dict[str, Any]], list[dict[str, Any]]]:
    lookup: dict[str, dict[tuple[str, int], tuple[str, list[str]]]] = {}; validations=[]; checks=[]
    for date in DATES:
        primary = locations[(date, "PRIMARY_HORSE_NUMBER_ORDER_FINISH")]
        auxiliary = locations[(date, "AUXILIARY_FINISH_ORDER_HORSE_NUMBER")]
        validations.append(validate_source_pair(primary, auxiliary, date))
        rows_a, rows_b = read_rows(primary), read_rows(auxiliary)
        by_a, by_b = {row[0]: row for row in rows_a}, {row[0]: row for row in rows_b}
        if len(by_a) != len(rows_a) or len(by_b) != len(rows_b) or set(by_a) != set(by_b):
            raise Stop(f"RESULT_PAIR_RACE_SET_OR_DUPLICATE_FAILURE:{date}")
        day: dict[tuple[str, int], tuple[str, list[str]]] = {}
        for key in sorted(by_a):
            row = by_a[key]; identity = (row[1], int(row[2]))
            if identity in day:
                raise Stop(f"RESULT_DUPLICATE_RACE_IDENTITY:{date}:{identity}")
            day[identity] = (key, row); checks.append(crosscheck(row, by_b[key], key))
        lookup[date] = day
    return lookup, validations, checks


def metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(bool(row["actual_top3"]) for row in valid)
    return {"natural_selected": len(rows), "invalid_selected": len(rows) - len(valid), "valid_selected": len(valid), "top3_hits": hits, "buy_top3_rate": hits / len(valid) if valid else None}


def compare(current: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    if current["buy_top3_rate"] is None or selection["buy_top3_rate"] is None:
        raise Stop("EMPTY_VALID_SELECTION_DENOMINATOR")
    lift = selection["buy_top3_rate"] - current["buy_top3_rate"]
    return {"raw_hit_difference": selection["top3_hits"] - current["top3_hits"], "pooled_lift_pt": lift * 100, "raw_selected_volume_difference": selection["natural_selected"] - current["natural_selected"], "valid_selected_volume_difference": selection["valid_selected"] - current["valid_selected"]}


def source_current_payloads() -> dict[str, dict[str, Any]]:
    freeze = read_json(CURRENT / "current_pre_freeze_manifest.json")
    result = {}
    for date, digest in freeze["per_date_prediction_manifest_sha256"].items():
        day = CURRENT / date
        if sha(day / "prediction_manifest.json") != digest:
            raise Stop(f"CURRENT_PRE_MANIFEST_MISMATCH:{date}")
        for entry in read_json(day / "race_index.json")["race_index"]:
            path = day / entry["artifact"]
            result[read_json(path)["race_id"]] = read_json(path)
    return result


def join(pre: dict[str, Any], results: dict[str, dict[tuple[str, int], tuple[str, list[str]]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    current_payloads = source_current_payloads(); current_rows=[]; selection_rows=[]; races=[]
    for race in pre["races"]:
        if race.get("race_status") != "SUCCESS":
            continue
        date, venue, number, race_id = race["date"], race["venue"], race["race_number"], race["race_id"]
        matched = results.get(date, {}).get((venue, number))
        if matched is None:
            raise Stop(f"MISSING_RESULT_RACE_JOIN:{race_id}")
        result_key, result_row = matched
        payload = current_payloads.get(race_id)
        if payload is None or sha(CURRENT / date / next(entry["artifact"] for entry in read_json(CURRENT / date / "race_index.json")["race_index"] if entry["race_id"] == race_id)) != race["source_prediction_sha256"]:
            raise Stop(f"CURRENT_PRE_SOURCE_PREDICTION_MISMATCH:{race_id}")
        current_horses = [row for row in payload["ranked_results"] if row.get("buy") is True]
        selection_horses = [row for row in race["horses"] if row.get("selected_by_protocol") is True]
        if len(current_horses) != race["target_k"] or len(selection_horses) != race["selected_n"]:
            raise Stop(f"FROZEN_PRE_SELECTION_COUNT_MISMATCH:{race_id}")
        def attach(horse: dict[str, Any], arm: str) -> dict[str, Any]:
            number = int(horse["horse_number"])
            if number < 1 or number > int(result_row[9]):
                raise Stop(f"RESULT_HORSE_JOIN_AMBIGUITY:{race_id}:{number}")
            return {"date": date, "race_id": race_id, "result_race_key": result_key, "venue": venue, "race_number": race["race_number"], "horse_number": number, "horse_name": horse.get("horse_name"), "arm": arm, **outcome(result_row, number)}
        current = [attach(horse, "CURRENT") for horse in current_horses]; selection = [attach(horse, "SELECTION_AUTHORITY") for horse in selection_horses]
        current_rows.extend(current); selection_rows.extend(selection)
        races.append({"date": date, "race_id": race_id, "venue": venue, "race_number": race["race_number"], "target_k": race["target_k"], "selected_n": race["selected_n"], "shortfall": race["shortfall"], "current": current, "selection": selection, "current_metric": metric(current), "selection_metric": metric(selection)})
    if len(races) != 81:
        raise Stop(f"ELIGIBLE_RACE_COUNT_MISMATCH:{len(races)}")
    return current_rows, selection_rows, races


def evidence_band(count: int) -> str:
    return "TOO_SMALL" if count <= 9 else "OBSERVATION_ONLY" if count <= 19 else "DIRECTIONAL_WATCH" if count <= 29 else "WEAK" if count <= 39 else "MODERATE" if count <= 59 else "STRONG" if count <= 79 else "VERY_STRONG"


def main() -> int:
    if not SOURCE_MANIFEST.is_file() or any(path.name != "result_source_manifest.json" for path in OUT.iterdir()):
        raise Stop("POST_OUTPUT_ROOT_NOT_PRISTINE_AFTER_RESULT_FREEZE")
    pre_before = verify_pre(); source_manifest, locations = verify_result_source_manifest(); source_manifest_sha = sha(SOURCE_MANIFEST)
    result_lookup, validations, checks = load_results(locations)
    semantic = read_json(PRE / "semantic_selection.json")
    current, selection, races = join(semantic, result_lookup)
    cm, sm = metric(current), metric(selection); comparison = compare(cm, sm)
    shortfall = sum(race["shortfall"] for race in races); shortfall_races = sum(race["shortfall"] > 0 for race in races)
    if (shortfall, shortfall_races) != (11, 10):
        raise Stop(f"FROZEN_SHORTFALL_RECOUNT_MISMATCH:{shortfall}:{shortfall_races}")
    daily=[]; venue=[]
    for date in DATES:
        cr=[row for row in current if row["date"] == date]; sr=[row for row in selection if row["date"] == date]; rm=[row for row in races if row["date"] == date]
        daily.append({"date":date,"eligible_races":len(rm),"current":metric(cr),"selection":metric(sr),**compare(metric(cr),metric(sr)),"shortfall":sum(row["shortfall"] for row in rm),"races_with_shortfall":sum(row["shortfall"]>0 for row in rm)})
    for name in sorted({row["venue"] for row in races}):
        cr=[row for row in current if row["venue"] == name]; sr=[row for row in selection if row["venue"] == name]; rm=[row for row in races if row["venue"] == name]
        venue.append({"venue":name,"diagnostic_only":True,"eligible_races":len(rm),"current":metric(cr),"selection":metric(sr),**compare(metric(cr),metric(sr)),"shortfall":sum(row["shortfall"] for row in rm)})
    p1,p2=cm["buy_top3_rate"],sm["buy_top3_rate"]; n1,n2=cm["valid_selected"],sm["valid_selected"]; se=math.sqrt(p1*(1-p1)/n1+p2*(1-p2)/n2); z=(p2-p1)/se if se else None; p=math.erfc(abs(z)/math.sqrt(2)) if z is not None else None
    lodo=[]
    for date in DATES:
        a=metric([row for row in current if row["date"] != date]); b=metric([row for row in selection if row["date"] != date]); lodo.append({"excluded_date":date,**compare(a,b)})
    lodo_lifts=[row["pooled_lift_pt"] for row in lodo]; most=max(lodo,key=lambda row:abs(comparison["pooled_lift_pt"]-row["pooled_lift_pt"]))["excluded_date"]
    contributions=sorted(({"date":row["date"],"raw_hit_difference":row["raw_hit_difference"]} for row in daily),key=lambda row:(-row["raw_hit_difference"],row["date"])); removed=[row["date"] for row in contributions[:4]]
    stress=compare(metric([row for row in current if row["date"] not in removed]),metric([row for row in selection if row["date"] not in removed])); concentration_flag=stress["pooled_lift_pt"] <= 0 < comparison["pooled_lift_pt"]
    evaluable=sum(metric(race["current"])["valid_selected"] > 0 and metric(race["selection"])["valid_selected"] > 0 for race in races)
    uncertainty={"label":"APPROXIMATE_DIAGNOSTIC_ONLY","dependence_caveat":"RACE_WITHIN_SELECTION_DEPENDENCE_NOT_MODELED","approximate_z":z,"approximate_p":p,"lodo":lodo,"lodo_lift_range":[min(lodo_lifts),max(lodo_lifts)],"lodo_most_influential_date":most,"concentration":{"classification":"CONCENTRATION_FLAG" if concentration_flag else "CLEAN","removed_dates":removed,"date_contributions":contributions,"stress":stress}}
    post_summary={"cohort_identity":"JANUARY_2026_SELECTION_AUTHORITY_HISTORICAL_HOLDOUT","evidence_role":semantic["evidence_role"],"reverse_time_limitation":"BACKWARD_TEMPORAL_GENERALIZATION_ONLY; never Production authorization.","authority_sha256":pre_before,"result_source_manifest_sha256":source_manifest_sha,"population_races":149,"eligible_races":81,"evaluable_independent_races":evaluable,"current":cm,"selection":sm,**comparison,"total_shortfall":shortfall,"races_with_shortfall":shortfall_races,"approximate_z":z,"approximate_p":p,"lodo_lift_range":uncertainty["lodo_lift_range"],"lodo_most_influential_date":most,"concentration_result":uncertainty["concentration"]["classification"],"evidence_race_count":evaluable,"evidence_band":evidence_band(evaluable),"shortfall_confounding":"PRESENT","primary_historical_verdict":"HOLD_VOLUME_CONFOUNDED","production_authorization":"NO","formal_prospective_gate_remains_required":"YES"}
    if verify_pre() != pre_before:
        raise Stop("PRE_IMMUTABILITY_FAILURE")
    dump(OUT / "result_pair_crosscheck.json",{"status":"PASS","source_validations":validations,"crosschecked_race_count":len(checks),"crosschecks":checks})
    dump(OUT / "result_population_reconciliation.json",{"status":"PASS","population_races":149,"eligible_races":81,"result_race_join_missing":0,"result_race_join_ambiguous":0,"horse_join_ambiguous":0,"scope_extra_result_races_not_added":True})
    dump(OUT / "joined_current_results.json",{"arm":"CURRENT","records":current,"metrics":cm})
    dump(OUT / "joined_selection_results.json",{"arm":"SELECTION_AUTHORITY","records":selection,"metrics":sm})
    dump(OUT / "post_summary.json",post_summary); dump(OUT / "date_level_summary.json",{"dates":daily,"venues_diagnostic_only":venue}); dump(OUT / "statistical_uncertainty.json",uncertainty)
    manifest={"artifact_type":"JANUARY_2026_SELECTION_AUTHORITY_HISTORICAL_HOLDOUT_ONE_SHOT_POST_MANIFEST_V1","status":"COMPLETE","result_source_manifest_sha256":source_manifest_sha,"pre_immutability":"PASS","post_summary_sha256":sha(OUT/"post_summary.json"),"result_access":True,"model_inference":0,"model_retraining":0,"current_prediction_regeneration":0,"selection_regeneration":0,"production_change":0,"ledger_change":0,"fingerprint_change":0,"git_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),"completed_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    dump(OUT / "post_manifest.json",manifest)
    indexed={path.name:sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_index.json"}; dump(OUT / "artifact_index.json",{"index_excludes_self":True,"indexed_artifacts":indexed})
    print("JANUARY_2026_HISTORICAL_HOLDOUT_POST=COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
