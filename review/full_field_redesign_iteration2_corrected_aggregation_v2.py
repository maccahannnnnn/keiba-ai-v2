"""Iteration 2 Recovery v2 corrected aggregator; explicit, fail-closed modes.

Default mode never parses Result rows.  `--prepare` is PRE-only and may only
freeze Result-file identity.  `--execute` is intentionally separate and must
be explicitly authorized by a future Human / ChatGPT instruction.
"""
from __future__ import annotations

import csv, hashlib, json, math, random, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from review import full_field_redesign_iteration2_correction_v1 as contract

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "reports" / "full_field_redesign_iteration2_recovery_inputs_v1"
OUT = ROOT / "reports" / "full_field_redesign_iteration2_correction_v1"
ITER1 = ROOT / "reports" / "full_field_redesign_iteration1_completion_v1"
PRE_ROOT = ROOT / "reports" / "full_field_redesign_iter0_v1_retry6" / "pre_only_regeneration" / "shards"
RESULT_ROOT = ROOT / "data" / "raw" / "target" / "daily_result_list"
PREREG = ROOT / "docs" / "KeibaAI_WS2_FullField_Iteration2_Preregistration_v1.md"
RATIFICATION = ROOT / "docs" / "KeibaAI_WS2_FullField_Iteration2_Human_Ratification_v1.md"
EXPECTED_PREREG = "6958c7cc8cfe6ece075a1b4de8c60d9b1be39c046069cfe7faff593cb108dbb5"
EXPECTED_RATIFICATION = "2ffe0d48822f54d723e94d92b12bc4927ae1bdc3e94bc70b0d50288035d3c7d1"
EXPECTED_RUN = "48401e556f28f5625d85dfa315153a6dbba84e3114e3a9752e17b25e50f71c22"
MONTHS = ("202603", "202604", "202605", "202606", "202607", "202608", "202609")
NEW = ("CORRECTED_PLACKETT_LUCE", "CORRECTED_HIST_GRADIENT_BOOSTING")
ALL = ("CURRENT_GLOBAL", "PP_ONLY_DETERMINISTIC", "V5_TOP5_TRAINED", "V5_FULL_FIELD_TRAINED", *NEW)
RESULT_LOADER_ID = "review.candidate_generation_training_dataset_readiness_v1.result_rows+outcome"

class Stop(RuntimeError): pass
def sha(p: Path) -> str: return hashlib.sha256(p.read_bytes()).hexdigest()
def ensure(ok: bool, code: str) -> None:
    if not ok: raise Stop(code)
def ident(r: dict[str, Any]) -> tuple[str, str, int]: return str(r["date"]), str(r["race_id"]), int(r["horse_number"])
def score(r: dict[str, Any], name: str) -> float:
    if name == "CURRENT_GLOBAL": return float(r["adjusted_score"])
    if name == "PP_ONLY_DETERMINISTIC": return float(r["past_performance"])
    if name == "V5_FULL_FIELD_TRAINED": return float(r["p_v5"])
    if name in NEW: return contract.corrected_score(r, name)
    raise Stop("STOP_UNSUPPORTED_COMPARATOR")
def daily_key(r: dict[str, Any], name: str) -> tuple[Any, ...]:
    if name in NEW or name == "PP_ONLY_DETERMINISTIC": return (-score(r,name), str(r["race_id"]), int(r["horse_number"]))
    if name == "CURRENT_GLOBAL": return (-score(r,name), -int(r["horse_number"]), str(r["race_id"]))
    if name == "V5_FULL_FIELD_TRAINED": return (-score(r,name), float(r["shadow_ai_rank"]), int(r["horse_number"]), str(r["race_id"]))
    raise Stop("STOP_UNSUPPORTED_COMPARATOR")
def rank1_key(r: dict[str, Any], name: str) -> tuple[float, int]: return (-score(r,name), int(r["horse_number"]))

def frozen_gate(input_root: Path = INPUT) -> dict[str, Any]:
    ensure(sha(PREREG) == EXPECTED_PREREG and sha(RATIFICATION) == EXPECTED_RATIFICATION, "STOP_FROZEN_SOURCE_SHA_MISMATCH")
    a,b=input_root/"run_a_frozen.json",input_root/"run_b_frozen.json"
    ensure(a.is_file() and b.is_file(), "STOP_FROZEN_SOURCE_SHA_MISMATCH")
    ba,bb=a.read_bytes(),b.read_bytes()
    ensure(hashlib.sha256(ba).hexdigest()==EXPECTED_RUN and hashlib.sha256(bb).hexdigest()==EXPECTED_RUN and ba==bb, "STOP_FROZEN_SOURCE_SHA_MISMATCH")
    return {"preregistration_sha256":EXPECTED_PREREG,"ratification_sha256":EXPECTED_RATIFICATION,"run_a_sha256":EXPECTED_RUN,"run_b_sha256":EXPECTED_RUN,"byte_identical":True}

def load_scores(path: Path) -> list[dict[str,Any]]:
    raw=json.loads(path.read_text(encoding="utf-8")).get("rows")
    fields={"date","month","race_id","venue","race_number","horse_number","current_buy","shadow_ai_rank","adjusted_score","past_performance","p_v5","p_pl","p_hgb"}
    ensure(isinstance(raw,list) and raw and all(fields <= set(x) for x in raw), "STOP_FROZEN_SOURCE_SCHEMA_MISMATCH")
    return [{k:x[k] for k in fields} for x in raw]

def load_budget() -> dict[str,int]:
    index=json.loads((ITER1/"artifact_hashes.json").read_text(encoding="utf-8"))["artifacts"]
    p=ITER1/"daily_current_buy_budget.csv"; entry=index.get(p.name,{})
    ensure(p.is_file() and sha(p)==entry.get("sha256"), "STOP_DAILY_BUDGET_MISMATCH")
    with p.open(encoding="utf-8-sig",newline="") as h: rows=list(csv.DictReader(h))
    ensure(len(rows)==62 and len({x["date"] for x in rows})==62, "STOP_DAILY_BUDGET_MISMATCH")
    return {str(x["date"]):int(x["budget_n"]) for x in rows}

def recompute_pre_buy_budget() -> dict[str,int]:
    files=sorted(PRE_ROOT.glob("run_c_*/runtime_pre_only_output.json")); ensure(len(files)==31,"STOP_DAILY_BUDGET_MISMATCH")
    counts: dict[str,int]=defaultdict(int); dates:set[str]=set()
    for p in files:
        for row in json.loads(p.read_text(encoding="utf-8"))["generated_rows"]:
            day=str(row["date"]); dates.add(day); counts[day]+= row["values"].get("post_rc1_decision")=="BUY"
    ensure(len(dates)==62,"STOP_DAILY_BUDGET_MISMATCH")
    return dict(counts)

def direct_budget_conformance() -> dict[str,int]:
    frozen,recomputed=load_budget(),recompute_pre_buy_budget()
    ensure(frozen==recomputed,"STOP_DAILY_BUDGET_MISMATCH")
    return frozen

def select_daily(rows: list[dict[str,Any]], name: str, budgets: dict[str,int]) -> dict[str,list[dict[str,Any]]]:
    by:dict[str,list[dict[str,Any]]]=defaultdict(list)
    for r in rows: by[str(r["date"])].append(r)
    ensure(set(by)<=set(budgets),"STOP_DAILY_BUDGET_MISMATCH")
    out={}
    for day,pool in by.items():
        n=budgets[day]; ensure(0<=n<=len(pool),"STOP_DAILY_BUDGET_MISMATCH"); out[day]=sorted(pool,key=lambda r:daily_key(r,name))[:n]
    return out

def read_iter1_selection(with_score: bool=False) -> dict[str,Any]:
    index=json.loads((ITER1/"artifact_hashes.json").read_text(encoding="utf-8"))["artifacts"]
    p=ITER1/"primary_global_selected_horses.csv"; ensure(p.is_file() and sha(p)==index.get(p.name,{}).get("sha256"),"STOP_V5_TOP5_REFERENCE_SHA_MISMATCH")
    out:dict[str,Any]=defaultdict(dict if with_score else set)
    with p.open(encoding="utf-8-sig",newline="") as h:
        for r in csv.DictReader(h):
            key=(str(r["date"]),str(r["race_id"]),int(r["horse_number"]))
            if with_score: out[str(r["comparator"])][key]={"score":float(r["score"]),"global_rank":int(r["global_rank"])}
            else: out[str(r["comparator"])].add(key)
    return out

def baseline_conformance(rows:list[dict[str,Any]], budgets:dict[str,int]) -> dict[str,dict[str,list[dict[str,Any]]]]:
    frozen=read_iter1_selection(); dates={str(r["date"]) for r in rows}; out={}
    for name,old in (("CURRENT_GLOBAL","CURRENT"),("PP_ONLY_DETERMINISTIC","PP_ONLY_DETERMINISTIC"),("V5_FULL_FIELD_TRAINED","V5_FULL_FIELD_TRAINED")):
        chosen=select_daily(rows,name,budgets); got={ident(r) for rs in chosen.values() for r in rs}; want={x for x in frozen[old] if x[0] in dates}
        ensure(got==want,"STOP_BASELINE_SELECTION_CONFORMANCE_FAILURE"); out[name]=chosen
    return out

def assert_pl_mass(rows:list[dict[str,Any]]) -> None:
    try: contract.assert_corrected_pl_probability_mass(rows,1e-8)
    except contract.CorrectionPreparationStop as e: raise Stop("STOP_PL_PROBABILITY_SANITY_FAILURE") from e

def prepare_result_identity_manifest(rows:list[dict[str,Any]], destination:Path=INPUT/"result_source_identity_manifest.json") -> dict[str,Any]:
    """File identity only: never parse Result rows or calculate performance."""
    dates=sorted({str(r["date"]) for r in rows}); sources=[]
    for day in dates:
        for filename,role in ((f"馬番順着順_{day}.csv","PRIMARY_CANONICAL_RESULT"),(f"着順馬番_{day}.csv","AUXILIARY_RECONCILIATION_RESULT")):
            p=RESULT_ROOT/filename; ensure(p.is_file(),"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
            sources.append({"path":str(p.relative_to(ROOT)).replace("\\","/"),"filename":filename,"byte_size":p.stat().st_size,"sha256":sha(p),"source_role":role})
    m={"canonical_result_loader_identifier":RESULT_LOADER_ID,"join_key_semantics":"date + venue + numeric race_number + horse_number","valid_result_semantics_identifier":"candidate_generation_training_dataset_readiness_v1.outcome","iteration1_source_linkage":{"runner":"review/full_field_redesign_iteration1_completion_v1.py","canonical_join":"review/full_field_redesign_iter0_retry7.py:result_join"},"created_at":datetime.now(timezone.utc).isoformat(),"PERFORMANCE_ROWS_PARSED":False,"sources":sources}
    destination.write_text(json.dumps(m,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return m

def verify_result_identity(manifest_path:Path, dates:set[str]) -> dict[str,Any]:
    ensure(manifest_path.is_file(),"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"); m=json.loads(manifest_path.read_text(encoding="utf-8"))
    ensure(m.get("PERFORMANCE_ROWS_PARSED") is False and m.get("canonical_result_loader_identifier")==RESULT_LOADER_ID,"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
    expected={f"馬番順着順_{d}.csv" for d in dates}|{f"着順馬番_{d}.csv" for d in dates}; actual={x.get("filename") for x in m.get("sources",[])}
    ensure(actual==expected,"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
    for x in m["sources"]:
        p=ROOT/x["path"]; ensure(p.is_file() and p.stat().st_size==x["byte_size"] and sha(p)==x["sha256"],"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
    return m

def canonical_result_loader(rows:list[dict[str,Any]]) -> dict[tuple[str,str,int],dict[str,Any]]:
    """Canonical Iter0/Iteration1 path, called only after identity freeze."""
    from review.candidate_generation_training_dataset_readiness_v1 import outcome, parse_race_id, result_rows
    cache={}; out={}
    for r in rows:
        day,venue,race=parse_race_id(str(r["race_id"])); cache.setdefault(day,result_rows(day)); source=cache[day].get((venue,race))
        ensure(source is not None,"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"); valid,finish,top3=outcome(source,int(r["horse_number"])); out[ident(r)]={"valid_result":valid,"actual_finish":finish,"actual_top3":top3}
    return out

def full_race_rank1(rows:list[dict[str,Any]], labels:dict[tuple[str,str,int],dict[str,Any]]) -> dict[str,dict[str,Any]]:
    groups:dict[tuple[str,str],list[dict[str,Any]]]=defaultdict(list)
    for r in rows: groups[(str(r["date"]),str(r["race_id"]))].append(r)
    rank={name:{race:sorted(pool,key=lambda r:rank1_key(r,name))[0] for race,pool in groups.items()} for name in ("V5_FULL_FIELD_TRAINED",*NEW)}
    common=set.intersection(*(set(x) for x in rank.values())); common={race for race in common if all(labels.get(ident(rank[name][race]),{}).get("valid_result") is True for name in rank)}
    return {name:{"common_races":sorted(common),"rows":[rank[name][race] for race in sorted(common)]} for name in rank}

def rank_guard(reference:float,new:float)->bool:return new>=reference-.01
def calibration_guard(v5:float,new:float,worse:int,months:int)->bool: ensure(months==7,"STOP_EVALUATION_MONTH_COUNT_UNEXPECTED"); return new<=v5 and worse<=2
def monthly_rule(wins:int,months:int)->bool: ensure(months==7,"STOP_EVALUATION_MONTH_COUNT_UNEXPECTED"); return wins>=5
def bootstrap(left:dict[str,dict[str,float]],right:dict[str,dict[str,float]],seed:int=20261014,rounds:int=10000)->dict[str,float]:
    ds=sorted(set(left)&set(right)); ensure(bool(ds),"STOP_BOOTSTRAP_NO_COMMON_DATES"); rng=random.Random(seed); values=[]
    for _ in range(rounds):
        d=[rng.choice(ds) for _ in ds]; values.append(sum(right[x]["hits"] for x in d)/sum(right[x]["valid_n"] for x in d)-sum(left[x]["hits"] for x in d)/sum(left[x]["valid_n"] for x in d))
    values.sort(); return {"unit":"DATE","seed":seed,"rounds":rounds,"ci_95_lower":values[249],"ci_95_upper":values[9749]}
def gate(*,lift:float,wins:int,boot_current:float,rank:bool,cal:bool,boot_pp:float,name:str)->dict[str,Any]:
    ensure(name!="V5_TOP5_TRAINED","STOP_V5_TOP5_GATE_FORBIDDEN"); c={"lift_vs_current_6pt":lift>=.06,"monthly_5_of_7":monthly_rule(wins,7),"bootstrap_current_lower_gt_0":boot_current>0,"rank1_guard":rank,"calibration_guard":cal,"bootstrap_pp_lower_gt_0":boot_pp>0}; return {"conditions":c,"status":"PASS" if all(c.values()) else "FAIL"}
def choose(pl:dict[str,Any],hgb:dict[str,Any],hgb_minus_pl:float,hgb_cal:bool)->str:
    a,b=pl["status"]=="PASS",hgb["status"]=="PASS"
    if not a and not b:return "NONE"
    if a and not b:return "PLACKETT_LUCE"
    if b and not a:return "HIST_GRADIENT_BOOSTING"
    return "HIST_GRADIENT_BOOSTING" if hgb_minus_pl>0 and hgb_cal else "PLACKETT_LUCE"

def snapshot(output:Path,selections:dict[str,dict[str,list[dict[str,Any]]]],top5_metadata:dict[tuple[str,str,int],dict[str,Any]])->None:
    rows=[]
    for name,days in selections.items():
        for day,chosen in days.items():
            for rank,row in enumerate(chosen,1): rows.append({"date":day,"race_id":row["race_id"],"horse_number":row["horse_number"],"comparator":name,"score":top5_metadata.get(ident(row),{}).get("score") if name=="V5_TOP5_TRAINED" else score(row,name),"daily_rank":top5_metadata.get(ident(row),{}).get("global_rank",rank) if name=="V5_TOP5_TRAINED" else rank,"selected":True,"selection_budget":len(chosen)})
    output.mkdir(parents=True,exist_ok=True); p=output/"pre_result_selected_horses.csv"
    with p.open("w",encoding="utf-8-sig",newline="") as h: w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (output/"pre_result_selection_manifest.json").write_text(json.dumps({"row_count":len(rows),"dates":sorted({r["date"] for r in rows}),"comparator_counts":{n:sum(len(x) for x in d.values()) for n,d in selections.items()},"selected_horses_sha256":sha(p),"result_access_count_at_freeze":0},indent=2,sort_keys=True)+"\n",encoding="utf-8")

def freeze_selection_before_result_loader(output:Path,selections:dict[str,dict[str,list[dict[str,Any]]]],top5_metadata:dict[tuple[str,str,int],dict[str,Any]],loader:Callable[[list[dict[str,Any]]],Any],rows:list[dict[str,Any]])->Any:
    """Ordering seam: testable proof that loader is called only after snapshot."""
    snapshot(output,selections,top5_metadata)
    ensure((output/"pre_result_selected_horses.csv").is_file() and (output/"pre_result_selection_manifest.json").is_file(),"STOP_PRE_RESULT_SELECTION_FREEZE_FAILURE")
    return loader(rows)

def metric(rows:list[dict[str,Any]])->dict[str,Any]:
    valid=[r for r in rows if r["valid_result"]]; hits=sum(int(bool(r["actual_top3"])) for r in valid)
    return {"selected_n":len(rows),"invalid_n":len(rows)-len(valid),"valid_n":len(valid),"top3_hits":hits,"top3_rate":hits/len(valid) if valid else None,"selected_races":len({(r["date"],r["race_id"]) for r in rows})}
def join(rows:list[dict[str,Any]],labels:dict[tuple[str,str,int],dict[str,Any]])->list[dict[str,Any]]:
    out=[]
    for r in rows:
        x=labels.get(ident(r)); ensure(isinstance(x,dict) and {"valid_result","actual_top3"}<=set(x),"STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"); out.append({**r,**x})
    return out
def brier(rows:list[dict[str,Any]],name:str)->float:
    valid=[r for r in rows if r["valid_result"]]; ensure(bool(valid),"STOP_CALIBRATION_NO_VALID_ROWS"); return sum((score(r,name)-int(bool(r["actual_top3"])))**2 for r in valid)/len(valid)
def write_json(p:Path,x:Any)->None:p.write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
def write_csv(p:Path,rows:list[dict[str,Any]])->None:
    ensure(bool(rows),"STOP_EMPTY_OUTPUT")
    with p.open("w",encoding="utf-8-sig",newline="") as h:w=csv.DictWriter(h,fieldnames=list(rows[0]),extrasaction="ignore");w.writeheader();w.writerows(rows)
def write_results(source:dict[str,Any],selections:dict[str,dict[str,list[dict[str,Any]]]],rank:dict[str,dict[str,Any]],cals:dict[str,dict[str,float]],boots:dict[str,Any],gates:dict[str,Any],choice:str)->None:
    totals={n:metric([r for d in selections[n].values() for r in d]) for n in ALL}; daily={n:{d:metric(v) for d,v in selections[n].items()} for n in ALL}
    months={n:{m:metric([r for d,v in selections[n].items() if d.startswith(m) for r in v]) for m in MONTHS} for n in ALL}
    write_json(OUT/"source_integrity.json",source); write_json(OUT/"rank1_common_set.json",rank);write_json(OUT/"paired_bootstrap.json",boots);write_json(OUT/"candidate_gate.json",gates);write_json(OUT/"model_selection_decision.json",{"iteration2_candidate":choice,"v5_top5_role":"REFERENCE_ONLY"})
    write_json(OUT/"recovery_audit.json",{"RECOVERY_ROLE":"DEVELOPMENT_ONLY_NON_EVIDENTIAL","ORIGINAL_OUTPUTS":"QUARANTINED","TRAINING_RERUN":False,"PREDICTION_RERUN":False,"CORRECTION":"MAPPING_AND_AGGREGATION_ONLY","MODEL_MAPPING":{"PL":"original p_hgb","HGB":"original p_pl"},"V5_FULL_PROBABILITY_IDENTITY":"NOT_PROVEN","formal_evidence":"NO","production_evidence":"NO","prospective_evidence":"NO"})
    write_csv(OUT/"primary_metrics.csv",[{"comparator":n,**x} for n,x in totals.items()]);write_csv(OUT/"primary_by_date.csv",[{"comparator":n,"date":d,**x} for n,z in daily.items() for d,x in z.items()]);write_csv(OUT/"primary_by_month.csv",[{"comparator":n,"month":m,**x} for n,z in months.items() for m,x in z.items()]);write_csv(OUT/"rank1_metrics.csv",[{"comparator":n,"common_valid_races":len(x["common_races"]),**metric(x["rows"])} for n,x in rank.items()]);write_csv(OUT/"calibration_metrics.csv",[{"comparator":n,"scope":s,"brier":v} for n,x in cals.items() for s,v in x.items()])
    (OUT/"summary.md").write_text("# Iteration 2 corrected aggregation\n\n`DEVELOPMENT_ONLY_NON_EVIDENTIAL`\n",encoding="utf-8")
    hashes={p.relative_to(OUT).as_posix():{"sha256":sha(p),"size":p.stat().st_size} for p in sorted(OUT.iterdir()) if p.is_file() and p.name!="artifact_hashes.json"};write_json(OUT/"artifact_hashes.json",{"self_hash_excluded":True,"artifacts":hashes})

def prepare(input_root:Path=INPUT)->dict[str,Any]:
    frozen=frozen_gate(input_root); budgets=direct_budget_conformance(); rows=load_scores(input_root/"run_a_frozen.json"); ensure({r["date"] for r in rows}<=set(budgets),"STOP_DAILY_BUDGET_MISMATCH"); base=baseline_conformance(rows,budgets); assert_pl_mass(rows); manifest=prepare_result_identity_manifest(rows)
    return {"source_integrity":frozen,"baseline":base,"rows":rows,"budget":budgets,"result_manifest":manifest}

def execute_after_authorization()->None:
    ensure(not OUT.exists(),"STOP_OUTPUT_ROOT_ALREADY_EXISTS"); prepared=prepare(); rows=prepared["rows"]; budgets=prepared["budget"]; base=prepared["baseline"]
    dates={r["date"] for r in rows}; verify_result_identity(INPUT/"result_source_identity_manifest.json",dates)
    selections={**base}; top5=read_iter1_selection(True)["V5_TOP5_TRAINED"]; lookup={ident(r):r for r in rows}; selections["V5_TOP5_TRAINED"]={}
    for day in dates: selections["V5_TOP5_TRAINED"][day]=[lookup[x] for x in sorted((k for k in top5 if k[0]==day),key=lambda k:top5[k]["global_rank"]) if x in lookup]
    for name in NEW: selections[name]=select_daily(rows,name,budgets)
    OUT.mkdir(parents=True)
    write_json(OUT/"baseline_conformance.json",{"status":"PASS","comparators":["CURRENT_GLOBAL","PP_ONLY_DETERMINISTIC","V5_FULL_FIELD_TRAINED"],"daily_budget_direct_conformance":"PASS"})
    labels=freeze_selection_before_result_loader(OUT,selections,top5,canonical_result_loader,rows); joined=join(rows,labels)
    selections={n:{d:[next(r for r in joined if ident(r)==ident(x)) for x in v] for d,v in days.items()} for n,days in selections.items()}
    rank=full_race_rank1(joined,labels)
    rank_rates={n:metric(x["rows"])["top3_rate"] for n,x in rank.items()}
    daily={n:{d:metric(v) for d,v in days.items()} for n,days in selections.items()}; totals={n:metric([r for v in days.values() for r in v]) for n,days in selections.items()}
    monthly={n:{m:metric([r for d,v in days.items() if d.startswith(m) for r in v]) for m in MONTHS} for n,days in selections.items()}
    cals={n:{"POOLED":brier(joined,n),**{m:brier([r for r in joined if r["month"]==m],n) for m in MONTHS}} for n in ("V5_FULL_FIELD_TRAINED",*NEW)}
    boots={}; gates={}
    for n in NEW:
        bc=bootstrap(daily["CURRENT_GLOBAL"],daily[n]);bp=bootstrap(daily["PP_ONLY_DETERMINISTIC"],daily[n]);boots[f"{n}_MINUS_CURRENT_GLOBAL"]=bc;boots[f"{n}_MINUS_PP_ONLY_DETERMINISTIC"]=bp
        worse=sum(cals[n][m]>cals["V5_FULL_FIELD_TRAINED"][m] for m in MONTHS);cal=calibration_guard(cals["V5_FULL_FIELD_TRAINED"]["POOLED"],cals[n]["POOLED"],worse,len(MONTHS));wins=sum(monthly[n][m]["top3_rate"]>monthly["CURRENT_GLOBAL"][m]["top3_rate"] for m in MONTHS)
        gates[n]=gate(lift=totals[n]["top3_rate"]-totals["CURRENT_GLOBAL"]["top3_rate"],wins=wins,boot_current=bc["ci_95_lower"],rank=rank_guard(rank_rates["V5_FULL_FIELD_TRAINED"],rank_rates[n]),cal=cal,boot_pp=bp["ci_95_lower"],name=n)
    hp=bootstrap(daily["CORRECTED_PLACKETT_LUCE"],daily["CORRECTED_HIST_GRADIENT_BOOSTING"]);boots["CORRECTED_HIST_GRADIENT_BOOSTING_MINUS_CORRECTED_PLACKETT_LUCE"]=hp
    choice=choose(gates["CORRECTED_PLACKETT_LUCE"],gates["CORRECTED_HIST_GRADIENT_BOOSTING"],hp["ci_95_lower"],gates["CORRECTED_HIST_GRADIENT_BOOSTING"]["conditions"]["calibration_guard"])
    write_results(prepared["source_integrity"],selections,rank,cals,boots,gates,choice)

def main()->None:
    if len(sys.argv)==1: raise SystemExit("No execution mode selected; Result parsing is disabled.")
    if sys.argv[1]=="--prepare": prepare(); return
    if sys.argv[1]=="--execute": execute_after_authorization(); return
    raise SystemExit("Unsupported mode")
if __name__=="__main__": main()
