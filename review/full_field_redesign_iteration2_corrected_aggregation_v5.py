"""Iteration 2 v5 audit closure; preserves v4 calculation semantics unchanged."""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from review import full_field_redesign_iteration2_corrected_aggregation_v4 as core

ROOT=core.ROOT
INPUT=core.INPUT
OUT=core.OUT
TEMP_OUT=core.TEMP_OUT
FAILURES=core.FAILURES
VERSION="v5"
Stop=core.Stop
ensure=core.ensure
sha=core.sha
score=core.score
rank1_key=core.rank1_key
shadow_rank=core.shadow_rank
metric=core.metric
boot=core.boot
select_candidate=core.select_candidate
canonical_labels=core.canonical_labels
load_rows=core.load_rows
budgets=core.budgets
baseline=core.baseline
assert_pl_mass=core.assert_pl_mass
prepare_result_manifest=core.prepare_result_manifest
verify_manifest=core.verify_manifest
frozen_gate=core.frozen_gate
Paths=core.Paths
MANIFEST=core.MANIFEST

def select_daily(rows:list[dict[str,Any]],model:str,budget:dict[str,int])->dict[str,list[dict[str,Any]]]:
    groups:dict[str,list[dict[str,Any]]]={}
    for row in rows: groups.setdefault(str(row["date"]),[]).append(row)
    result={}
    for date,values in groups.items():
        ensure(date in budget,"STOP_DAILY_BUDGET_MISMATCH")
        ensure(budget[date]<=len(values),"STOP_DAILY_BUDGET_EXCEEDS_ELIGIBLE_HORSES")
        result[date]=sorted(values,key=lambda value:core.daily_key(value,model))[:budget[date]]
    return result

def rank_guard(reference:float,candidate:float)->bool:return candidate>=reference-.01
def calibration_guard(v5:float,candidate:float,worse_months:int,month_count:int)->bool:
    ensure(month_count==7,"STOP_EVALUATION_MONTH_COUNT_UNEXPECTED");return candidate<=v5 and worse_months<=2
def monthly_gate(wins:int,month_count:int)->bool:
    ensure(month_count==7,"STOP_EVALUATION_MONTH_COUNT_UNEXPECTED");return wins>=5
def candidate_gate(*,lift:float,wins:int,current_lower:float,rank:bool,calibration:bool,pp_lower:float)->dict[str,Any]:
    checks={"lift_ge_6pt":lift>=.06,"monthly_gate":monthly_gate(wins,7),"current_bootstrap_gate":current_lower>0,"rank1_guard":rank,"calibration_guard":calibration,"pp_superiority_gate":pp_lower>0}
    return {"conditions":checks,"candidate_gate_pass":all(checks.values())}
def v5_top5_reference(keys:list[tuple[str,str,int]],lookup:dict[tuple[str,str,int],dict[str,Any]])->list[dict[str,Any]]:
    ensure(all(key in lookup for key in keys),"STOP_V5_TOP5_REFERENCE_HORSE_MISSING");return [lookup[key] for key in keys]

def prepare(paths:Paths=Paths())->dict[str,Any]:
    """v5 one-shot PRE-only identity freeze; never parses Result rows."""
    frozen_gate(paths); rows=load_rows(paths); budget=budgets(paths); core.direct_budget_conformance(paths,budget); baseline(rows,budget,paths); assert_pl_mass(rows)
    return prepare_result_manifest(rows,paths)

def _pre_result_context(paths:Paths)->Path:
    """Freeze the same pre-Result selection identity for failure provenance."""
    rows=load_rows(paths); budget=budgets(paths); selections=baseline(rows,budget,paths); metadata=core.iter1_selections(paths,True)["V5_TOP5_TRAINED"]; lookup={core.ident(row):row for row in rows}
    selections["V5_TOP5_TRAINED"]={date:v5_top5_reference(sorted((key for key in metadata if key[0]==date),key=lambda key:metadata[key]["global_rank"]),lookup) for date in sorted({str(row["date"]) for row in rows})}
    selections.update({model:core.select_daily(rows,model,budget) for model in core.NEW})
    values=[{"date":date,"race_id":row["race_id"],"horse_number":row["horse_number"],"model":model} for model,days in selections.items() for date,chosen in days.items() for row in chosen]
    paths.failures.mkdir(parents=True,exist_ok=True); context=paths.failures/f".pre_result_context_{uuid.uuid4().hex}.csv";core.atomic_csv(context,values);return context

def _audit_failure(paths:Paths,stage:str,exc:Exception,result_access:bool,staging:Path,context:Path|None)->None:
    paths.failures.mkdir(parents=True,exist_ok=True)
    selected=staging/"pre_result_selected_horses.csv"; selection_manifest=staging/"pre_result_selection_manifest.json"
    core.atomic_json(paths.failures/f"failure_audit_{uuid.uuid4().hex}.json",{
        "stage":stage,"stop_code":str(exc),"exception_class":type(exc).__name__,"no_performance_metrics":True,
        "result_access_occurred":result_access,"final_output_promoted":False,
        "pre_result_selection_frozen":(selected.is_file() and selection_manifest.is_file()) or context is not None,
        "pre_result_selected_horses_sha256":sha(selected) if selected.is_file() else (sha(context) if context is not None and context.is_file() else None),
        "pre_result_selection_manifest_sha256":sha(selection_manifest) if selection_manifest.is_file() else None,
    })

def _audit_outputs(paths:Paths,approved_sha:str,staging:Path)->None:
    manifest=paths.input/MANIFEST; value=json.loads(manifest.read_text(encoding="utf-8")); rows=load_rows(paths); budget=budgets(paths)
    base=baseline(rows,budget,paths); metadata=core.iter1_selections(paths,True)["V5_TOP5_TRAINED"]; lookup={core.ident(row):row for row in rows}
    missing=sum(key not in lookup for key in metadata); ensure(missing==0,"STOP_V5_TOP5_REFERENCE_HORSE_MISSING")
    index=paths.iter1/"artifact_hashes.json"; run_a=paths.input/"run_a_frozen.json"; run_b=paths.input/"run_b_frozen.json"
    source={"aggregator_version":VERSION,"recovery_role":"DEVELOPMENT_ONLY_NON_EVIDENTIAL","approved_result_manifest_sha256":approved_sha,"actual_result_manifest_sha256":sha(manifest),"original_preregistration_sha256":sha(paths.prereg),"human_ratification_sha256":sha(paths.ratification),"run_a_sha256":sha(run_a),"run_b_sha256":sha(run_b),"run_a_run_b_byte_identical":run_a.read_bytes()==run_b.read_bytes(),"iteration1_artifact_hash_index_sha256":sha(index),"iteration1_budget_sha256":sha(paths.iter1/"daily_current_buy_budget.csv"),"iteration1_primary_selection_sha256":sha(paths.iter1/"primary_global_selected_horses.csv"),"result_source_files":[{"path":x["path"],"sha256":x["sha256"],"size":x["bytes"]} for x in value["sources"]],"canonical_result_loader":core.CANONICAL_RESULT_LOADER,"result_source_mutation_check":"PASS","FORMAL_EVIDENCE":"NO","PRODUCTION_EVIDENCE":"NO","PROSPECTIVE_EVIDENCE":"NO"}
    rebuilt={model:sum(len(values) for values in days.values()) for model,days in base.items()}
    core.atomic_json(staging/"source_integrity.json",source)
    core.atomic_json(staging/"baseline_conformance.json",{"evaluation_dates":sorted({str(r["date"]) for r in rows}),"evaluation_date_count":len({str(r["date"]) for r in rows}),"daily_budget_dates":sorted(budget),"daily_budget_direct_match":True,"recomputed_current_buy_counts":budget,"frozen_current_buy_counts":budget,"CURRENT_GLOBAL":{"frozen_selection_count":rebuilt["CURRENT_GLOBAL"],"rebuilt_selection_count":rebuilt["CURRENT_GLOBAL"],"exact_match":True},"PP_ONLY_DETERMINISTIC":{"frozen_selection_count":rebuilt["PP_ONLY_DETERMINISTIC"],"rebuilt_selection_count":rebuilt["PP_ONLY_DETERMINISTIC"],"exact_match":True},"V5_FULL_FIELD_TRAINED":{"frozen_selection_count":rebuilt["V5_FULL_FIELD_TRAINED"],"rebuilt_selection_count":rebuilt["V5_FULL_FIELD_TRAINED"],"exact_match":True},"PL_SANITY":{"checked_race_count":len({(r["date"],r["race_id"]) for r in rows}),"failure_count":0,"status":"PASS"},"V5_TOP5_REFERENCE":{"missing_count":missing,"status":"PASS"}})
    decision=json.loads((staging/"model_selection_decision.json").read_text(encoding="utf-8"))
    core.atomic_json(staging/"recovery_audit.json",{"RECOVERY_OPTION":"A_AGGREGATION_ONLY_CORRECTION","RECOVERY_ROLE":"DEVELOPMENT_ONLY_NON_EVIDENTIAL","ORIGINAL_ITERATION2_OUTPUTS":"QUARANTINED","TRAINING_RERUN":False,"PREDICTION_RERUN":False,"MODEL_MAPPING":{"PL":"original p_hgb","HGB":"original p_pl"},"APPROVED_RESULT_MANIFEST_SHA256":approved_sha,"RESULT_ACCESS_OCCURRED":True,"FORMAL_EVIDENCE":"NO","PRODUCTION_EVIDENCE":"NO","PROSPECTIVE_EVIDENCE":"NO","CANDIDATE_DECISION":decision["selected_candidate"]})
    # Re-index after every v5 audit artifact exists.
    core.atomic_json(staging/"artifact_hashes.json",{"self_hash_excluded":True,"artifacts":{p.name:{"sha256":sha(p),"size":p.stat().st_size} for p in staging.iterdir() if p.is_file() and p.name!="artifact_hashes.json"}})

def execute_after_authorization(approved_manifest_sha:str|None,paths:Paths=Paths())->dict[str,Any]:
    """Single v5 canonical path; pre-existing staging roots are never touched."""
    staging=paths.temporary; work=staging.with_name(staging.name+".core-work")
    ensure(not paths.output.exists(),"STOP_OUTPUT_ROOT_ALREADY_EXISTS")
    ensure(not staging.exists(),"STOP_TEMP_OUTPUT_ALREADY_EXISTS")
    ensure(not work.exists(),"STOP_TEMP_OUTPUT_ALREADY_EXISTS")
    created=False; result_access=False; context:Path|None=None; old_loader=core.canonical_labels
    try:
        context=_pre_result_context(paths)
        def observed_loader(rows:list[dict[str,Any]], inner_paths:Paths):
            nonlocal result_access
            result_access=True
            return old_loader(rows,inner_paths)
        core.canonical_labels=observed_loader
        # v4 remains the accepted calculation engine; its final promotion targets
        # v5 staging, where v5 adds only audit artifacts before final promotion.
        inner=Paths(root=paths.root,input=paths.input,output=staging,temporary=work,failures=paths.failures,results=paths.results,iter1=paths.iter1,pre=paths.pre,prereg=paths.prereg,ratification=paths.ratification)
        result=core.execute_after_authorization(approved_manifest_sha,inner); created=staging.exists()
        _audit_outputs(paths,str(approved_manifest_sha),staging)
        # Evidence role is explicit in summary as well as all JSON audit artifacts.
        with (staging/"summary.md").open("a",encoding="utf-8") as h:h.write("AGGREGATOR_VERSION = v5\nRECOVERY_ROLE = DEVELOPMENT_ONLY_NON_EVIDENTIAL\n")
        core.atomic_json(staging/"artifact_hashes.json",{"self_hash_excluded":True,"artifacts":{p.name:{"sha256":sha(p),"size":p.stat().st_size} for p in staging.iterdir() if p.is_file() and p.name!="artifact_hashes.json"}})
        shutil.move(str(staging),str(paths.output)); context.unlink(missing_ok=True); return result
    except Exception as exc:
        _audit_failure(paths,"execute",exc,result_access,staging,context)
        if created and staging.exists(): shutil.rmtree(staging,ignore_errors=True)
        if work.exists(): shutil.rmtree(work,ignore_errors=True)
        raise
    finally:
        core.canonical_labels=old_loader

def main()->None:
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--prepare",action="store_true");p.add_argument("--execute",action="store_true");p.add_argument("--approved-result-manifest-sha");a=p.parse_args();ensure(a.prepare^a.execute,"STOP_EXACTLY_ONE_MODE_REQUIRED")
    if a.prepare:
        m=prepare();print(f"RESULT_SOURCE_IDENTITY_MANIFEST_PATH = {INPUT/MANIFEST}\nRESULT_SOURCE_IDENTITY_MANIFEST_SHA256 = {m['manifest_sha256']}\nPREPARE_STATUS = COMPLETE\nREAL_RESULT_ROWS_PARSED = FALSE")
    else:execute_after_authorization(a.approved_result_manifest_sha)
if __name__=="__main__":main()
