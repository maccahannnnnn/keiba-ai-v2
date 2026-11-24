"""Iteration 2 v4 corrected aggregation: one atomic prepare/execute path.

No work is performed on import.  ``--prepare`` freezes Result file identity
only; ``--execute`` requires the Human-approved manifest digest and never
refreshes that manifest.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from review import full_field_redesign_iteration2_correction_v1 as contract
from review import candidate_generation_training_dataset_readiness_v1 as canonical_result

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "reports" / "full_field_redesign_iteration2_recovery_inputs_v1"
OUT = ROOT / "reports" / "full_field_redesign_iteration2_correction_v1"
TEMP_OUT = ROOT / "reports" / ".full_field_redesign_iteration2_correction_v1.tmp"
FAILURES = ROOT / "reports" / "full_field_redesign_iteration2_recovery_failures"
RESULT_ROOT = ROOT / "data" / "raw" / "target" / "daily_result_list"
ITER1 = ROOT / "reports" / "full_field_redesign_iteration1_completion_v1"
PRE_ROOT = ROOT / "reports" / "full_field_redesign_iter0_v1_retry6" / "pre_only_regeneration" / "shards"
PREREG = ROOT / "docs" / "KeibaAI_WS2_FullField_Iteration2_Preregistration_v1.md"
RATIFICATION = ROOT / "docs" / "KeibaAI_WS2_FullField_Iteration2_Human_Ratification_v1.md"
EXPECTED_PREREG = "6958c7cc8cfe6ece075a1b4de8c60d9b1be39c046069cfe7faff593cb108dbb5"
EXPECTED_RATIFICATION = "2ffe0d48822f54d723e94d92b12bc4927ae1bdc3e94bc70b0d50288035d3c7d1"
EXPECTED_RUN = "48401e556f28f5625d85dfa315153a6dbba84e3114e3a9752e17b25e50f71c22"
EXPECTED_ITER1_ARTIFACT_HASH_INDEX_SHA = "fb3b5d4200e0feb9ec07452c4cecdb9f2bffac634609b430b82f6dc76178ab40"
EXPECTED_ITER1_BUDGET_SHA = "cf122a1a645af9cd246fca36afcd86c90cdc8e06f1ed42080f8db5344b1d4ad0"
EXPECTED_ITER1_PRIMARY_SELECTION_SHA = "a8de7b007f42f6126689399624faab64421e11f5dc41f9760574fdd86c4eaaaf"
MANIFEST = "result_source_identity_manifest.json"
CANONICAL_RESULT_LOADER = "ITER0_ITER1_RESULT_JOIN_COMPATIBLE"
NEW = ("PLACKETT_LUCE", "HIST_GRADIENT_BOOSTING")
ALL = ("CURRENT_GLOBAL", "PP_ONLY_DETERMINISTIC", "V5_TOP5_TRAINED", "V5_FULL_FIELD_TRAINED", *NEW)


class Stop(RuntimeError): pass
def ensure(ok: bool, code: str) -> None:
    if not ok: raise Stop(code)
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def ident(row: dict[str, Any]) -> tuple[str, str, int]: return str(row["date"]), str(row["race_id"]), int(row["horse_number"])

@dataclass(frozen=True)
class Paths:
    root: Path = ROOT; input: Path = INPUT; output: Path = OUT; temporary: Path = TEMP_OUT
    failures: Path = FAILURES; results: Path = RESULT_ROOT; iter1: Path = ITER1; pre: Path = PRE_ROOT
    prereg: Path = PREREG; ratification: Path = RATIFICATION

def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as h:
            json.dump(value, h, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False); h.write("\n"); h.flush(); os.fsync(h.fileno())
        os.replace(tmp, path)
    except Exception: Path(tmp).unlink(missing_ok=True); raise

def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure(bool(rows), "STOP_EMPTY_OUTPUT"); fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as h:
            w=csv.DictWriter(h, fieldnames=list(rows[0]), extrasaction="ignore"); w.writeheader(); w.writerows(rows); h.flush(); os.fsync(h.fileno())
        os.replace(tmp,path)
    except Exception: Path(tmp).unlink(missing_ok=True); raise

def score(row: dict[str, Any], model: str) -> float:
    field={"CURRENT_GLOBAL":"adjusted_score","PP_ONLY_DETERMINISTIC":"past_performance","V5_FULL_FIELD_TRAINED":"p_v5","PLACKETT_LUCE":"p_hgb","HIST_GRADIENT_BOOSTING":"p_pl"}.get(model)
    ensure(field is not None, "STOP_UNSUPPORTED_COMPARATOR"); return float(row[field])

def daily_key(row: dict[str, Any], model: str) -> tuple[Any,...]:
    if model in {"PLACKETT_LUCE","HIST_GRADIENT_BOOSTING","PP_ONLY_DETERMINISTIC"}: return (-score(row,model),str(row["race_id"]),int(row["horse_number"]))
    if model=="CURRENT_GLOBAL": return (-score(row,model),-int(row["horse_number"]),str(row["race_id"]))
    if model=="V5_FULL_FIELD_TRAINED": return (-score(row,model),shadow_rank(row),int(row["horse_number"]),str(row["race_id"]))
    raise Stop("STOP_UNSUPPORTED_COMPARATOR")

def shadow_rank(row: dict[str, Any]) -> int:
    try:
        value=row["shadow_ai_rank"]; ensure(value is not None, "STOP_V5_FULL_SHADOW_RANK_MISSING"); return int(value)
    except (KeyError, TypeError, ValueError) as exc: raise Stop("STOP_V5_FULL_SHADOW_RANK_MISSING") from exc

def rank1_key(row: dict[str, Any], model: str) -> tuple[Any,...]:
    return (-score(row,model), shadow_rank(row),int(row["horse_number"])) if model=="V5_FULL_FIELD_TRAINED" else (-score(row,model),int(row["horse_number"]))

def frozen_gate(paths: Paths) -> None:
    ensure(sha(paths.prereg)==EXPECTED_PREREG,"STOP_PREREGISTRATION_SHA_MISMATCH"); ensure(sha(paths.ratification)==EXPECTED_RATIFICATION,"STOP_RATIFICATION_SHA_MISMATCH")
    a,b=paths.input/"run_a_frozen.json",paths.input/"run_b_frozen.json"; ensure(sha(a)==EXPECTED_RUN,"STOP_RUN_A_SHA_MISMATCH"); ensure(sha(b)==EXPECTED_RUN,"STOP_RUN_B_SHA_MISMATCH"); ensure(a.read_bytes()==b.read_bytes(),"STOP_FROZEN_RUNS_NOT_BYTE_IDENTICAL")
    index=paths.iter1/"artifact_hashes.json"; budget=paths.iter1/"daily_current_buy_budget.csv"; primary=paths.iter1/"primary_global_selected_horses.csv"
    ensure(sha(index)==EXPECTED_ITER1_ARTIFACT_HASH_INDEX_SHA,"STOP_ITER1_HASH_INDEX_SHA_MISMATCH"); ensure(sha(budget)==EXPECTED_ITER1_BUDGET_SHA,"STOP_DAILY_BUDGET_MISMATCH"); ensure(sha(primary)==EXPECTED_ITER1_PRIMARY_SELECTION_SHA,"STOP_V5_TOP5_REFERENCE_SHA_MISMATCH")

def load_rows(paths: Paths) -> list[dict[str, Any]]:
    rows=json.loads((paths.input/"run_a_frozen.json").read_text(encoding="utf-8"))["rows"]
    need={"date","month","race_id","horse_number","current_buy","shadow_ai_rank","adjusted_score","past_performance","p_v5","p_pl","p_hgb"}
    ensure(isinstance(rows,list) and rows and all(need<=set(row) for row in rows),"STOP_FROZEN_SOURCE_SCHEMA_MISMATCH")
    return rows

def budgets(paths: Paths) -> dict[str,int]:
    with (paths.iter1/"daily_current_buy_budget.csv").open(encoding="utf-8-sig",newline="") as h: rows=list(csv.DictReader(h))
    ensure(len(rows)==62 and len({r["date"] for r in rows})==62,"STOP_DAILY_BUDGET_MISMATCH"); return {r["date"]:int(r["budget_n"]) for r in rows}

def direct_budget_conformance(paths: Paths, frozen: dict[str,int]) -> None:
    files=sorted(paths.pre.glob("run_c_*/runtime_pre_only_output.json")); ensure(len(files)==31,"STOP_DAILY_BUDGET_MISMATCH"); actual:dict[str,int]=defaultdict(int)
    for path in files:
        for row in json.loads(path.read_text(encoding="utf-8"))["generated_rows"]:
            actual[str(row["date"])]+=row["values"].get("post_rc1_decision")=="BUY"
    ensure(actual==frozen,"STOP_DAILY_BUDGET_MISMATCH")

def select_daily(rows: list[dict[str, Any]], model: str, budget: dict[str,int]) -> dict[str,list[dict[str,Any]]]:
    d:dict[str,list[dict[str,Any]]]=defaultdict(list)
    for row in rows:d[str(row["date"])].append(row)
    ensure(set(d)<=set(budget),"STOP_DAILY_BUDGET_MISMATCH")
    return {date:sorted(pool,key=lambda r:daily_key(r,model))[:budget[date]] for date,pool in d.items()}

def iter1_selections(paths: Paths, with_meta: bool=False) -> dict[str,Any]:
    result:dict[str,Any]=defaultdict(dict if with_meta else set)
    with (paths.iter1/"primary_global_selected_horses.csv").open(encoding="utf-8-sig",newline="") as h:
        for row in csv.DictReader(h):
            key=(row["date"],row["race_id"],int(row["horse_number"])); name=row["comparator"]
            if with_meta:
                result[name][key]={"global_rank":int(row["global_rank"]),"score":float(row["score"])}
            else:
                result[name].add(key)
    return result

def baseline(rows:list[dict[str,Any]], budget:dict[str,int], paths:Paths)->dict[str,dict[str,list[dict[str,Any]]]]:
    old=iter1_selections(paths); dates={str(r["date"]) for r in rows}; output={}
    for model,oldname in (("CURRENT_GLOBAL","CURRENT"),("PP_ONLY_DETERMINISTIC","PP_ONLY_DETERMINISTIC"),("V5_FULL_FIELD_TRAINED","V5_FULL_FIELD_TRAINED")):
        selection=select_daily(rows,model,budget); ensure({ident(r) for values in selection.values() for r in values}=={k for k in old[oldname] if k[0] in dates},"STOP_BASELINE_SELECTION_CONFORMANCE_FAILURE"); output[model]=selection
    return output

def assert_pl_mass(rows:list[dict[str,Any]])->None:
    try: contract.assert_corrected_pl_probability_mass(rows,1e-8)
    except contract.CorrectionPreparationStop as exc: raise Stop("STOP_PL_PROBABILITY_SANITY_FAILURE") from exc

def prepare_result_manifest(rows:list[dict[str,Any]], paths:Paths)->dict[str,Any]:
    destination=paths.input/MANIFEST; ensure(not destination.exists(),"STOP_RESULT_SOURCE_MANIFEST_ALREADY_EXISTS"); dates=sorted({str(r["date"]) for r in rows}); sources=[]
    for date in dates:
        for filename in (f"馬番順着順_{date}.csv",f"着順馬番_{date}.csv"):
            p=paths.results/filename; ensure(p.is_file(),"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"); sources.append({"date":date,"path":str(p),"filename":filename,"bytes":p.stat().st_size,"sha256":sha(p)})
    value={"canonical_result_loader":CANONICAL_RESULT_LOADER,"PERFORMANCE_ROWS_PARSED":False,"evaluation_dates":dates,"sources":sources}; atomic_json(destination,value); return {**value,"manifest_sha256":sha(destination)}

def verify_manifest(rows:list[dict[str,Any]], paths:Paths, approved:str|None)->None:
    p=paths.input/MANIFEST; ensure(approved is not None and len(approved)==64,"STOP_APPROVED_RESULT_MANIFEST_SHA_REQUIRED"); ensure(p.is_file() and sha(p)==approved,"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"); value=json.loads(p.read_text(encoding="utf-8")); ensure(value.get("canonical_result_loader")==CANONICAL_RESULT_LOADER and value.get("PERFORMANCE_ROWS_PARSED") is False,"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
    dates=sorted({str(r["date"]) for r in rows}); ensure(value.get("evaluation_dates")==dates,"STOP_RESULT_MANIFEST_DATE_SET_MISMATCH")
    for source in value.get("sources",[]):
        p=Path(source["path"]); ensure(p.is_file() and p.name==source["filename"] and p.stat().st_size==source["bytes"] and sha(p)==source["sha256"],"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")

def canonical_labels(rows:list[dict[str,Any]], paths:Paths)->dict[tuple[str,str,int],dict[str,Any]]:
    """Calls the actual Iter0/Iter1 production Result implementation."""
    old_root=canonical_result.ROOT; canonical_result.ROOT=paths.root
    try:
        cache={}; out={}
        for row in rows:
            date,venue,race=canonical_result.parse_race_id(str(row["race_id"])); ensure(date==str(row["date"]),"STOP_RESULT_DATE_MISMATCH"); ensure(venue in canonical_result.JAPANESE_VENUE,"STOP_RESULT_VENUE_MISMATCH")
            if date not in cache: cache[date]=canonical_result.result_rows(date)
            raw=cache[date].get((canonical_result.JAPANESE_VENUE[venue],race)); ensure(raw is not None,"STOP_RESULT_RACE_MISMATCH")
            valid,finish,top3=canonical_result.outcome(raw,int(row["horse_number"])); out[ident(row)]={"valid_result":valid,"actual_finish":finish,"actual_top3":top3}
        return out
    finally: canonical_result.ROOT=old_root

def metric(rows:list[dict[str,Any]])->dict[str,Any]:
    valid=[r for r in rows if r["valid_result"]]; hits=sum(bool(r["actual_top3"]) for r in valid); return {"selected_n":len(rows),"valid_n":len(valid),"invalid_n":len(rows)-len(valid),"top3_hits":hits,"top3_rate":hits/len(valid) if valid else None}
def brier(rows:list[dict[str,Any]], model:str)->float:
    valid=[r for r in rows if r["valid_result"]]; ensure(bool(valid),"STOP_CALIBRATION_NO_VALID_ROWS"); return sum((score(r,model)-int(bool(r["actual_top3"])))**2 for r in valid)/len(valid)
def boot(left:dict[str,dict[str,Any]],right:dict[str,dict[str,Any]])->dict[str,float]:
    ds=sorted(set(left)&set(right)); ensure(bool(ds),"STOP_BOOTSTRAP_NO_COMMON_DATES"); rng=random.Random(20261014); values=[]
    for _ in range(10000):
        sample=[rng.choice(ds) for _ in ds]; values.append(sum(right[d]["top3_hits"] for d in sample)/sum(right[d]["valid_n"] for d in sample)-sum(left[d]["top3_hits"] for d in sample)/sum(left[d]["valid_n"] for d in sample))
    values.sort(); point=sum(right[d]["top3_hits"] for d in ds)/sum(right[d]["valid_n"] for d in ds)-sum(left[d]["top3_hits"] for d in ds)/sum(left[d]["valid_n"] for d in ds); return {"unit":"DATE","n_bootstrap":10000,"seed":20261014,"point_difference":point,"ci_lower_95":values[249],"ci_upper_95":values[9749]}
def select_candidate(pl:dict[str,Any],hgb:dict[str,Any],difference:dict[str,float],hgb_calibration:bool)->str:
    a,b=pl["candidate_gate_pass"],hgb["candidate_gate_pass"]
    if not a and not b:return "NONE"
    if a and not b:return "PLACKETT_LUCE"
    if b and not a:return "HIST_GRADIENT_BOOSTING"
    return "HIST_GRADIENT_BOOSTING" if difference["ci_lower_95"]>0 and hgb_calibration else "PLACKETT_LUCE"

def failure(paths:Paths, stage:str, exc:Exception, result_access:bool)->None:
    paths.failures.mkdir(parents=True,exist_ok=True); p=paths.failures/f"failure_audit_{hashlib.sha256((stage+str(exc)).encode()).hexdigest()[:16]}.json"; atomic_json(p,{"stage":stage,"stop_code":str(exc),"exception_class":type(exc).__name__,"no_performance_metrics":True,"result_access_occurred":result_access,"final_output_promoted":False})

def prepare(paths:Paths=Paths())->dict[str,Any]:
    frozen_gate(paths); rows=load_rows(paths); budget=budgets(paths); direct_budget_conformance(paths,budget); baseline(rows,budget,paths); assert_pl_mass(rows); return prepare_result_manifest(rows,paths)

def execute_after_authorization(approved_manifest_sha:str|None, paths:Paths=Paths())->dict[str,Any]:
    """The one canonical, atomic real execution path (not run by this task)."""
    result_access=False
    try:
        ensure(not paths.output.exists(),"STOP_FINAL_OUTPUT_ALREADY_EXISTS"); ensure(not paths.temporary.exists(),"STOP_TEMP_OUTPUT_ALREADY_EXISTS"); frozen_gate(paths); rows=load_rows(paths); budget=budgets(paths); direct_budget_conformance(paths,budget); base=baseline(rows,budget,paths); assert_pl_mass(rows); verify_manifest(rows,paths,approved_manifest_sha)
        meta=iter1_selections(paths,True)["V5_TOP5_TRAINED"]; lookup={ident(r):r for r in rows}; top5={}
        for date in sorted({str(r["date"]) for r in rows}):
            keys=sorted((k for k in meta if k[0]==date),key=lambda k:meta[k]["global_rank"]); ensure(all(k in lookup for k in keys),"STOP_V5_TOP5_REFERENCE_HORSE_MISSING"); top5[date]=[lookup[k] for k in keys]
        selections={**base,"V5_TOP5_TRAINED":top5,**{model:select_daily(rows,model,budget) for model in NEW}}
        paths.temporary.mkdir(parents=True); pre=[{"date":d,"race_id":r["race_id"],"horse_number":r["horse_number"],"model":m} for m,days in selections.items() for d,values in days.items() for r in values]; atomic_csv(paths.temporary/"pre_result_selected_horses.csv",pre); atomic_json(paths.temporary/"pre_result_selection_manifest.json",{"RESULT_ACCESS_COUNT_AT_FREEZE":0,"sha256":sha(paths.temporary/"pre_result_selected_horses.csv")})
        result_access=True; labels=canonical_labels(rows,paths); joined=[{**r,**labels[ident(r)]} for r in rows]; jlookup={ident(r):r for r in joined}; resolved={m:{d:[jlookup[ident(r)] for r in values] for d,values in days.items()} for m,days in selections.items()}; months=sorted({r["month"] for r in joined}); ensure(len(months)==7,"STOP_EVALUATION_MONTH_COUNT_UNEXPECTED")
        daily={m:{d:metric(v) for d,v in days.items()} for m,days in resolved.items()}; totals={m:metric([r for values in days.values() for r in values]) for m,days in resolved.items()}; monthly={m:{mo:metric([r for d,values in days.items() if d.startswith(mo) for r in values]) for mo in months} for m,days in resolved.items()}
        groups:dict[tuple[str,str],list[dict[str,Any]]]=defaultdict(list)
        for r in joined: groups[(str(r["date"]), str(r["race_id"]))].append(r)
        rank={m:{key:min(values,key=lambda r:rank1_key(r,m)) for key,values in groups.items()} for m in ("V5_FULL_FIELD_TRAINED",*NEW)}; common={key for key in groups if all(labels[ident(rank[m][key])]["valid_result"] for m in rank)}; rank_metrics=[]
        reference_rows=[rank["V5_FULL_FIELD_TRAINED"][key] for key in common]; reference=metric(reference_rows)["top3_rate"]
        for m in rank:
            rows_m=[rank[m][key] for key in common]; value=metric(rows_m); rank_metrics.append({"model":m,"common_rank1_races":len(common),"rank1_hits":value["top3_hits"],"rank1_rate":value["top3_rate"],"reference_model":"V5_FULL_FIELD_TRAINED","reference_rate":reference,"difference_pt":value["top3_rate"]-reference,"allowed_degradation_pt":.01,"guard_pass":value["top3_rate"]>=reference-.01})
        calibration={m:{"POOLED":brier(joined,m),**{mo:brier([r for r in joined if r["month"]==mo],m) for mo in months}} for m in ("V5_FULL_FIELD_TRAINED",*NEW)}; cal_rows=[]; gates={}; comparisons={}
        for m in ("V5_FULL_FIELD_TRAINED",*NEW):
            worse=sum(calibration[m][mo]>calibration["V5_FULL_FIELD_TRAINED"][mo] for mo in months); guard=calibration[m]["POOLED"]<=calibration["V5_FULL_FIELD_TRAINED"]["POOLED"] and worse<=2
            cal_rows += [{"model":m,"scope":"POOLED","month":"","valid_horses":sum(r["valid_result"] for r in joined),"brier":calibration[m]["POOLED"],"v5_full_pooled_brier":calibration["V5_FULL_FIELD_TRAINED"]["POOLED"],"difference":calibration[m]["POOLED"]-calibration["V5_FULL_FIELD_TRAINED"]["POOLED"],"worse_month_count":worse,"calibration_guard_pass":guard}] + [{"model":m,"scope":"MONTH","month":mo,"valid_horses":sum(r["valid_result"] for r in joined if r["month"]==mo),"brier":calibration[m][mo],"v5_full_pooled_brier":"","difference":"","worse_month_count":"","calibration_guard_pass":""} for mo in months]
        for m in NEW:
            current,pp=boot(daily["CURRENT_GLOBAL"],daily[m]),boot(daily["PP_ONLY_DETERMINISTIC"],daily[m]); comparisons[f"{m}_MINUS_CURRENT"]=current; comparisons[f"{m}_MINUS_PP"]=pp; wins=sum(monthly[m][mo]["top3_rate"]>monthly["CURRENT_GLOBAL"][mo]["top3_rate"] for mo in months); rank_ok=next(x["guard_pass"] for x in rank_metrics if x["model"]==m); cal_ok=next(x["calibration_guard_pass"] for x in cal_rows if x["model"]==m and x["scope"]=="POOLED"); gates[m]={"primary_rate":totals[m]["top3_rate"],"current_rate":totals["CURRENT_GLOBAL"]["top3_rate"],"lift_vs_current_raw":totals[m]["top3_rate"]-totals["CURRENT_GLOBAL"]["top3_rate"],"lift_ge_6pt":totals[m]["top3_rate"]-totals["CURRENT_GLOBAL"]["top3_rate"]>=.06,"months_beating_current":wins,"monthly_gate":wins>=5,"current_bootstrap_lower":current["ci_lower_95"],"current_bootstrap_gate":current["ci_lower_95"]>0,"rank1_guard":rank_ok,"calibration_guard":cal_ok,"pp_bootstrap_lower":pp["ci_lower_95"],"pp_superiority_gate":pp["ci_lower_95"]>0}; gates[m]["candidate_gate_pass"]=all([gates[m][k] for k in ("lift_ge_6pt","monthly_gate","current_bootstrap_gate","rank1_guard","calibration_guard","pp_superiority_gate")])
        comparisons["HGB_MINUS_PL"]=boot(daily["PLACKETT_LUCE"],daily["HIST_GRADIENT_BOOSTING"]); choice=select_candidate(gates["PLACKETT_LUCE"],gates["HIST_GRADIENT_BOOSTING"],comparisons["HGB_MINUS_PL"],gates["HIST_GRADIENT_BOOSTING"]["calibration_guard"])
        atomic_json(paths.temporary/"paired_bootstrap.json",comparisons); atomic_json(paths.temporary/"candidate_gate.json",gates); atomic_json(paths.temporary/"model_selection_decision.json",{"pl_candidate_gate":gates["PLACKETT_LUCE"],"hgb_candidate_gate":gates["HIST_GRADIENT_BOOSTING"],"hgb_minus_pl":comparisons["HGB_MINUS_PL"],"hgb_calibration_guard":gates["HIST_GRADIENT_BOOSTING"]["calibration_guard"],"selection_rule":"HGB only if both gates pass, lower CI > 0, and calibration passes","selected_candidate":choice,"evidence_role":"DEVELOPMENT_ONLY_NON_EVIDENTIAL"}); atomic_csv(paths.temporary/"primary_metrics.csv",[{"model":m,**v} for m,v in totals.items()]); atomic_csv(paths.temporary/"primary_by_date.csv",[{"model":m,"date":d,**v} for m,x in daily.items() for d,v in x.items()]); atomic_csv(paths.temporary/"primary_by_month.csv",[{"model":m,"month":mo,**v} for m,x in monthly.items() for mo,v in x.items()]); atomic_csv(paths.temporary/"rank1_metrics.csv",rank_metrics); atomic_csv(paths.temporary/"calibration_metrics.csv",cal_rows)
        summary=["# Iteration 2 corrected aggregation","","EXECUTION_ROLE = DEVELOPMENT_ONLY_NON_EVIDENTIAL","RECOVERY = MAPPING_AND_AGGREGATION_ONLY","TRAINING_RERUN = FALSE","PREDICTION_RERUN = FALSE"]
        for model in ALL:
            value=totals[model]; summary.append(f"{model} = {value['top3_hits']}/{value['valid_n']}={value['top3_rate']}")
        summary += [f"PL_LIFT_VS_CURRENT = {gates['PLACKETT_LUCE']['lift_vs_current_raw']}",f"HGB_LIFT_VS_CURRENT = {gates['HIST_GRADIENT_BOOSTING']['lift_vs_current_raw']}",f"PL_RANK1_GUARD = {'PASS' if gates['PLACKETT_LUCE']['rank1_guard'] else 'FAIL'}",f"HGB_RANK1_GUARD = {'PASS' if gates['HIST_GRADIENT_BOOSTING']['rank1_guard'] else 'FAIL'}",f"PL_CALIBRATION_GUARD = {'PASS' if gates['PLACKETT_LUCE']['calibration_guard'] else 'FAIL'}",f"HGB_CALIBRATION_GUARD = {'PASS' if gates['HIST_GRADIENT_BOOSTING']['calibration_guard'] else 'FAIL'}",f"PL_CANDIDATE_GATE = {'PASS' if gates['PLACKETT_LUCE']['candidate_gate_pass'] else 'FAIL'}",f"HGB_CANDIDATE_GATE = {'PASS' if gates['HIST_GRADIENT_BOOSTING']['candidate_gate_pass'] else 'FAIL'}",f"HGB_MINUS_PL_BOOTSTRAP = {comparisons['HGB_MINUS_PL']}",f"ITERATION2_CANDIDATE = {choice}","FORMAL_EVIDENCE = NO","PRODUCTION_EVIDENCE = NO","PROSPECTIVE_EVIDENCE = NO"]
        (paths.temporary/"summary.md").write_text("\n".join(summary)+"\n",encoding="utf-8"); atomic_json(paths.temporary/"artifact_hashes.json",{"self_hash_excluded":True,"artifacts":{p.name:{"sha256":sha(p),"size":p.stat().st_size} for p in paths.temporary.iterdir() if p.is_file()}}); os.replace(paths.temporary,paths.output); return {"selected_candidate":choice,"output":str(paths.output)}
    except Exception as exc:
        if paths.temporary.exists():shutil.rmtree(paths.temporary,ignore_errors=True)
        failure(paths,"execute",exc,result_access); raise

def main()->None:
    p=argparse.ArgumentParser(); p.add_argument("--prepare",action="store_true");p.add_argument("--execute",action="store_true");p.add_argument("--approved-result-manifest-sha");a=p.parse_args();ensure(a.prepare^a.execute,"STOP_EXACTLY_ONE_MODE_REQUIRED")
    if a.prepare:
        m=prepare(); print(f"RESULT_SOURCE_IDENTITY_MANIFEST_PATH = {INPUT/MANIFEST}\nRESULT_SOURCE_IDENTITY_MANIFEST_SHA256 = {m['manifest_sha256']}\nRESULT_SOURCE_FILE_SHA256 = {[x['sha256'] for x in m['sources']]}\nPREPARE_STATUS = COMPLETE\nREAL_RESULT_ROWS_PARSED = FALSE")
    else: execute_after_authorization(a.approved_result_manifest_sha)
if __name__=="__main__":main()
