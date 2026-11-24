"""One-day, human-approved, race-level exclusion runner for 2026-10-12.

This operational wrapper is deliberately narrow: it creates a temporary
filtered source projection for 京都8R, validates the unchanged Adapter against
the remaining programme, then runs the existing six PRE lanes.  It never
modifies the raw source files or Adapter policy.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from review.prospective_prediction_runner_v1 import (
    POPULATION_SCOPE_ID, SCHEMA_VERSION, _assert_population, _canonical_write,
    _project_race, _sha256, _write_report,
)
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new
from review.independent_race_selection_prospective_pre import run as run_independent
from review.track_condition_semantic_shadow_prospective_pre import run as run_tc
from review.daily_v5_same_volume_prospective_pre import run as run_daily
from review.selection_authority_protocol_v1_v6_forward_shadow_pre_freeze import run_real_formal_pre

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "prediction_input"
DATE = "20261012"
OUT = ROOT / "reports" / "20261012_official_pre_v1_retry4"
TEMP = ROOT / ".tmp" / "20261012_kyoto8_first_start_filtered_sources"
EXCLUSION = {
    "date": "2026-10-12", "race_id": "race_20261012_kyoto_8R", "venue": "京都",
    "race_number": 8, "affected_horse_number": 6, "affected_horse_name": "カドーダムール",
    "affected_registration_id": "23107291",
    "reason": "FIRST_START_ZERO_HISTORY_DE_DS_EXPECTED_MISMATCH",
    "evaluation_status": "NOT_EVALUATED", "human_approved": True,
    "scope": "2026-10-12 OFFICIAL PRE ONLY", "result_access_count": 0,
}

def read(path: Path, width: int) -> list[list[str]]:
    with path.open("r", encoding="cp932", newline="") as f: rows = list(csv.reader(f))
    if not rows or any(len(row) != width for row in rows): raise RuntimeError(f"INPUT_SCHEMA_INVALID:{path.name}")
    return rows

def write(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="cp932", newline="") as f: csv.writer(f, lineterminator="\r\n").writerows(rows)

def is_target_dg(row: list[str]) -> bool: return row[3].strip() == "京都" and int(row[4]) == 8
def is_target_de(row: list[str]) -> bool: return row[1].strip() == "京都" and int(row[2]) == 8
def js(path: Path) -> Any: return json.loads(path.read_text(encoding="utf-8"))

def summary_selection(path: Path, kind: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return selected horses plus a per-race empty-state label."""
    rows, states = [], {}
    if kind == "CURRENT":
        for item in js(path / "race_index.json")["race_index"]:
            payload = js(path / item["artifact"]); rid = payload["race_id"]
            state = payload.get("buy_gate_trace", {}).get("race", {}).get("shadow_race_state")
            selected = payload.get("buys", [])
            states[rid] = state or ("NONE" if not selected else "SELECTED")
            for horse in selected: rows.append({"race_id": rid, "horse_number": horse["horse_number"], "horse_name": horse["horse_name"]})
    elif kind == "INDEPENDENT_V5":
        for race in js(path / "selection_manifest.json")["races"]:
            rid = race["race_id"]; selected = race.get("selected_horses", [])
            states[rid] = "SELECTED" if selected else str(race.get("selection_reason", "NONE"))
            for horse in selected: rows.append({"race_id": rid, "horse_number": horse["horse_number"], "horse_name": horse["horse_name"]})
    elif kind == "TRACKCONDITION_SEMANTIC":
        for race in js(path / "race_level_trace.json")["rows"]:
            rid = race["race_id"]; states[rid] = str(race.get("shadow_race_state", "NONE"))
        for horse in js(path / "horse_level_trace.json")["rows"]:
            if horse.get("shadow_selected"):
                rows.append({"race_id": horse["race_id"], "horse_number": horse["horse_number"], "horse_name": horse["horse_name"]})
        for rid in {x["race_id"] for x in rows}: states[rid] = "SELECTED"
    elif kind == "DAILY_V5_SAME_VOLUME":
        for race in js(path / "selection.json")["races"]:
            rid = race["race_id"]; selected = race.get("selected_horses", [])
            states[rid] = "SELECTED" if selected else str(race.get("scope_status") or race.get("not_comparable_reason") or "NONE")
            for horse in selected: rows.append({"race_id": rid, "horse_number": horse["horse_number"], "horse_name": horse["horse_name"]})
    else:
        arm = "v5" if kind == "FORMAL_V5" else "v6"
        for race in js(path / "dual_pre_semantic.json")["races"]:
            rid = race[arm]["race_id"]; selected = [h for h in race[arm]["horses"] if h.get("selected_by_protocol")]
            states[rid] = "SELECTED" if selected else str(race[arm].get("selection_reason", "NONE"))
            for horse in selected: rows.append({"race_id": rid, "horse_number": horse["horse_number"], "horse_name": horse["horse_name"]})
    return rows, states

def fact_packet(bundle, source: dict[str, Path]) -> dict[str, Any]:
    packet_races=[]
    for race_id, race in sorted(bundle.races.items()):
        horses=[]
        for entry in race.today_entries:
            past=[]
            for p in [x for x in race.past_races if x.horse_name == entry.horse_name][:5]:
                past.append({"date": p.race_date.isoformat(), "race_id": p.race_id, "class": p.class_level, "surface": p.surface, "distance_m": p.distance, "track_condition": p.track_condition, "jockey": p.jockey, "field_size": p.field_size, "historical_finish_position": p.finish_position, "margin": p.margin, "corner_positions": p.corner_positions, "last_3f": p.last_3f, "body_weight": p.body_weight, "body_weight_diff": p.body_weight_diff, "sire": p.sire, "dam_sire": p.dam_sire})
            key=(entry.horse_number, entry.horse_name)
            horses.append({"horse_number": entry.horse_number, "horse_name": entry.horse_name, "registration_id": race.target_horse_identifiers.get(key), "jockey": entry.jockey, "sire": entry.sire, "dam_sire": entry.dam_sire, "assigned_weight": entry.weight, "class": entry.class_level, "past_races": past, "data_quality_flags": ["PAST_RACES_LT_5"] if len(past) < 5 else []})
        packet_races.append({"race_id": race_id, "venue": race.dg_row[3].strip(), "race_number": int(race.dg_row[4]), "race_name": race.dg_row[6].strip(), "class": race.dg_row[5].strip(), "surface": race.dg_row[7].strip(), "distance_m": int(race.dg_row[8]), "field_size": len(horses), "horses": horses})
    return {"date": "2026-10-12", "FACT_EXTRACTION_ONLY": True, "AI_SELECTION_INCLUDED": False, "RESULT_INCLUDED": False, "ODDS_INCLUDED": False, "POPULARITY_INCLUDED": False, "result_access_count": 0, "source_trace": {k: {"path": str(v.relative_to(ROOT)), "sha256": _sha256(v)} for k,v in source.items()}, "excluded_races": [EXCLUSION], "races": packet_races}

def main() -> int:
    if OUT.exists(): raise RuntimeError("OFFICIAL_PRE_OUTPUT_ALREADY_EXISTS")
    if TEMP.exists(): raise RuntimeError("TEMP_FILTERED_SOURCE_RESIDUE")
    source={k: RAW / f"{k}{DATE[2:]}.CSV" for k in ("DG","DE","DS")}
    dg,de,ds=read(source["DG"],11),read(source["DE"],33),read(source["DS"],50)
    excluded_dg=[r for r in dg if is_target_dg(r)]; excluded_de=[r for r in de if is_target_de(r)]
    target=[r for r in excluded_de if int(r[3])==6 and r[7].strip()=="カドーダムール" and r[18].strip()=="23107291"]
    if len(excluded_dg)!=1 or not excluded_de or len(target)!=1: raise RuntimeError("HUMAN_EXCLUSION_TARGET_NOT_UNIQUE")
    clean=TargetBulkPredictionInputAdapterV1()._clean_name
    filtered={"DG":[r for r in dg if not is_target_dg(r)], "DE":[r for r in de if not is_target_de(r)]}
    remaining={clean(r[7]) for r in filtered["DE"]}
    filtered["DS"]=[r for r in ds if clean(r[16]) in remaining]
    if len(dg)-len(filtered["DG"])!=1 or len(de)-len(filtered["DE"])!=len(excluded_de): raise RuntimeError("UNAUTHORIZED_ADDITIONAL_EXCLUSION")
    TEMP.mkdir(parents=True)
    try:
        paths={k:TEMP / f"{k}{DATE[2:]}.CSV" for k in ("DG","DE","DS")}
        for k,p in paths.items(): write(p,filtered[k])
        bundle=TargetBulkPredictionInputAdapterV1().load(paths["DG"],paths["DE"],paths["DS"])
        if bundle.date!=DATE or EXCLUSION["race_id"] in bundle.races or len(bundle.races)!=11: raise RuntimeError("FILTERED_POPULATION_INVALID")
        _assert_population(bundle)
        OUT.mkdir(parents=True); current=OUT/"current_frozen"; current.mkdir(); generated=datetime.now(timezone.utc).isoformat()
        artifacts=[]; index=[]
        for rid,race in sorted(bundle.races.items()):
            output=run_new(rid,race,trace=True); artifact=_project_race(rid,output); artifact["buy_gate_trace"]=output["buy_gate_trace"]; artifact["trace_status"]="NOT_FORMALLY_FROZEN_TRACE"
            name=f"{rid}_prediction.json"; _canonical_write(current/name,artifact); artifacts.append(name); index.append({"race_id":rid,"artifact":name,"horse_count":len(artifact["ranked_results"]),"buy_count":artifact["buy_count"],"race_decision":artifact["race_decision"]})
        _canonical_write(current/"race_index.json",{"schema_version":SCHEMA_VERSION,"race_index":index})
        _canonical_write(current/"input_manifest.json",{"date":DATE,"population_scope_id":POPULATION_SCOPE_ID,"sources":{k:{"path":str(v.relative_to(ROOT)),"sha256":_sha256(v)} for k,v in source.items()},"temporary_filtered_input":{"used":True,"temporary_files_retained":False,"filtered_source_sha256":{k:_sha256(v) for k,v in paths.items()},"filtered_row_counts":{k:len(v) for k,v in filtered.items()},"exclusion":EXCLUSION}})
        _canonical_write(current/"provenance.json",{"target_date":DATE,"schema_version":SCHEMA_VERSION,"population_scope_id":POPULATION_SCOPE_ID,"generated_at":generated,"trace_mode":True,"result_data_access_count":0,"runner_path":str(Path(__file__).relative_to(ROOT)),"runner_sha256":_sha256(Path(__file__)),"current_ai_runner_sha256":_sha256(ROOT/"review"/"prospective_prediction_runner_v1.py"),"human_exclusion":EXCLUSION,"training_executed":False,"production_change":False})
        _canonical_write(current/"summary.json",{"schema_version":SCHEMA_VERSION,"date":DATE,"total_source_races":len(dg),"excluded_input_integrity_races":1,"evaluated_races":len(index),"evaluated_horses":sum(x["horse_count"] for x in index),"buy_count":sum(x["buy_count"] for x in index),"result_data_access_count":0,"not_evaluated":[EXCLUSION]})
        _write_report(current/"report.md",date=DATE,trace=True,race_count=len(index),horse_count=sum(x["horse_count"] for x in index),buy_count=sum(x["buy_count"] for x in index))
        files=artifacts+["race_index.json","input_manifest.json","provenance.json","summary.json","report.md"]
        _canonical_write(current/"prediction_manifest.json",{"schema_version":SCHEMA_VERSION,"excludes":["prediction_manifest.json"],"files":[{"relative_path":x,"sha256":_sha256(current/x)} for x in files]})
        _canonical_write(OUT/"population_freeze.json",{"total_source_races":len(dg),"excluded_races":1,"evaluated_races":len(index),"evaluated_horses":sum(x["horse_count"] for x in index),"exclusions":[EXCLUSION],"no_other_automatic_exclusion":True,"result_access_count":0})
        _canonical_write(OUT/"filtered_source_manifest.json",{"original_source_sha256":{k:_sha256(v) for k,v in source.items()},"filtered_source_sha256":{k:_sha256(v) for k,v in paths.items()},"original_rows":{k:len(v) for k,v in {"DG":dg,"DE":de,"DS":ds}.items()},"filtered_rows":{k:len(v) for k,v in filtered.items()},"removed_rows":{k:len({"DG":dg,"DE":de,"DS":ds}[k])-len(filtered[k]) for k in filtered},"exclusion":EXCLUSION,"temporary_source_copy":True,"raw_source_modified":False})
        indep=run_independent(DATE,current,OUT/"independent_v5")
        tc=run_tc(DATE,paths["DG"],paths["DE"],paths["DS"],current,indep,OUT/"trackcondition_semantic")
        daily=run_daily(DATE,current,OUT/"daily_v5_same_volume")
        formal=run_real_formal_pre(DATE,current,OUT/"formal_v5_v6")
        lane_paths={"CURRENT":current,"INDEPENDENT_V5":indep,"TRACKCONDITION_SEMANTIC":tc,"DAILY_V5_SAME_VOLUME":daily,"FORMAL_V5":formal,"FORMAL_V6":formal}
        selections={}; states={}
        for lane,path in lane_paths.items(): selections[lane],states[lane]=summary_selection(path,lane)
        race_ids=sorted(bundle.races)
        rows=[]
        for rid in race_ids:
            race=bundle.races[rid]
            row={"venue":race.dg_row[3].strip(),"race_number":int(race.dg_row[4]),"race_id":rid,"race_state":states["CURRENT"].get(rid,"N/A")}
            for lane in lane_paths:
                horses=[x for x in selections[lane] if x["race_id"]==rid]
                row[lane]=" / ".join(f"#{x['horse_number']} {x['horse_name']}" for x in horses) if horses else states[lane].get(rid,"NONE")
            rows.append(row)
        counts={lane:{"selected_horses":len(xs),"selected_races":len({x["race_id"] for x in xs})} for lane,xs in selections.items()}
        equal=sorted((x["race_id"],x["horse_number"],x["horse_name"]) for x in selections["FORMAL_V5"])==sorted((x["race_id"],x["horse_number"],x["horse_name"]) for x in selections["FORMAL_V6"])
        _canonical_write(OUT/"ai_selection_summary.json",{"date":DATE,"source":"OFFICIAL_PRE_ONLY","pre_rerun":False,"result_access_count":0,"excluded_races":[EXCLUSION],"races":rows,"lane_counts":counts,"formal_v5_v6_exact_match":equal})
        md=["# 2026-10-12 Official PRE selection summary","", "- Result access: 0", "- NOT_EVALUATED: 京都8R (human-approved whole-race exclusion)","", "| Venue | Race | Race State | CURRENT | INDEPENDENT_V5 | TRACKCONDITION | DAILY_V5 | FORMAL_V5 | FORMAL_V6 |","|---|---:|---|---|---|---|---|---|---|"]
        for r in rows: md.append(f"| {r['venue']} | {r['race_number']} | {r['race_state']} | {r['CURRENT']} | {r['INDEPENDENT_V5']} | {r['TRACKCONDITION_SEMANTIC']} | {r['DAILY_V5_SAME_VOLUME']} | {r['FORMAL_V5']} | {r['FORMAL_V6']} |")
        md += ["", "## Lane counts", "", "| Lane | Selected horses | Selected races |","|---|---:|---:|"]
        for lane,count in counts.items(): md.append(f"| {lane} | {count['selected_horses']} | {count['selected_races']} |")
        md.append(f"\nFORMAL_V5 / FORMAL_V6 exact match: {equal}")
        (OUT/"ai_selection_summary.md").write_text("\n".join(md)+"\n",encoding="utf-8")
        facts=fact_packet(bundle,source); factroot=OUT/"fact_extraction_only"; factroot.mkdir(); fp=factroot/"20261012_human_independent_analysis_packet.json"; _canonical_write(fp,facts)
        (factroot/"20261012_human_independent_analysis_packet.md").write_text("# 2026-10-12 FACT_EXTRACTION_ONLY\n\nAI selection, results, odds, popularity and marks are excluded.\n\n- Races: 11\n- Excluded: 京都8R (human-approved)\n",encoding="utf-8")
        _canonical_write(OUT/"official_pre_manifest.json",{"date":DATE,"input_status":"OFFICIAL_WITH_HUMAN_APPROVED_RACE_EXCLUSION","result_access_count":0,"training_executed":False,"production_changed":False,"excluded_races":[EXCLUSION],"current_pre":str(current.relative_to(ROOT)),"lanes":{k:str(v.relative_to(ROOT)) for k,v in lane_paths.items()},"selection_summary_sha256":_sha256(OUT/"ai_selection_summary.json"),"fact_packet_sha256":_sha256(fp)})
        items={str(p.relative_to(OUT)): _sha256(p) for p in OUT.rglob("*") if p.is_file() and p.name!="official_pre_artifact_index.json"}
        _canonical_write(OUT/"official_pre_artifact_index.json",{"self_hash_excluded":True,"indexed_artifacts":items})
        print(json.dumps({"output":str(OUT),"races":len(index),"horses":sum(x["horse_count"] for x in index),"lane_counts":counts,"formal_equal":equal,"artifact_index_sha256":_sha256(OUT/"official_pre_artifact_index.json")},ensure_ascii=False))
    finally:
        if TEMP.exists(): shutil.rmtree(TEMP)
    return 0

if __name__ == "__main__": raise SystemExit(main())
