"""Shadow-only UNCONVERGED guards evaluated on the LATEST cohort.

The feature flag is deliberately fixed OFF.  This module has no Production imports and
only writes review reports. Result fields are consumed by ``metrics`` after selection,
never by a guard.
"""
from __future__ import annotations
import csv, json
from collections import defaultdict
from pathlib import Path
from typing import Callable

FEATURE_FLAG_NAME = "UNCONVERGED_COMPOSITE_SELECTOR_V1"
FEATURE_FLAG_ENABLED = False
LATEST_PREFIX = "LATEST_"

def _num(value, default=0.0):
    try:return float(value)
    except (TypeError,ValueError):return default
def _true(value):return str(value).lower()=="true"
def read_latest(path: Path):
    with path.open(encoding="utf-8-sig",newline="") as f:
        return [dict(x) for x in csv.DictReader(f) if x.get("cohort","").startswith(LATEST_PREFIX)]
def by_race(rows):
    out=defaultdict(list)
    for x in rows:out[x["race_id"]].append(x)
    for group in out.values():group.sort(key=lambda x:_num(x.get("candidate_rank"),999))
    return dict(out)

def multi_gate_support_floor(group):
    """Select candidates with three explicit pre-race gate PASS statuses."""
    eligible=[x for x in group if all(x.get(k)=="PASS" for k in ("absolute_status","relative_status","consensus_status"))]
    return eligible[:3]

def top_cluster_dual_separation(group):
    """Select top three only if both preregistered boundary gaps are clear."""
    if len(group)<4:return []
    third,fourth=group[2],group[3]
    adjusted_boundary=_num(fourth.get("adjusted_gap_to_top"))-_num(third.get("adjusted_gap_to_top"))
    absolute_boundary=_num(third.get("absolute_margin"))-_num(fourth.get("absolute_margin"))
    return group[:3] if adjusted_boundary>=10.0 and absolute_boundary>=0.05 else []

def trace_completeness_and_race_support(group):
    """Permit a top-three cluster when at least two candidates have complete gate trace."""
    complete=[x for x in group if all(x.get(k) in {"PASS","FAIL"} for k in ("absolute_status","relative_status","consensus_status"))]
    supported=[x for x in complete if sum(x.get(k)=="PASS" for k in ("absolute_status","relative_status","consensus_status"))>=2]
    return group[:3] if len(supported)>=2 else []

GUARDS: dict[str,Callable] = {
 "MULTI_GATE_SUPPORT_FLOOR":multi_gate_support_floor,
 "TOP_CLUSTER_DUAL_SEPARATION":top_cluster_dual_separation,
 "TRACE_COMPLETENESS_AND_RACE_SUPPORT":trace_completeness_and_race_support,
}

def metrics(name, groups, selector):
    selected=[];selected_races=0
    for group in groups.values():
        picked=selector(group);selected.extend(picked);selected_races+=bool(picked)
    fn=sum(_true(x.get("actual_top3")) for x in selected);fp=len(selected)-fn
    return {"guard":name,"cohort":"LATEST","race_count":len(groups),"horse_count":sum(map(len,groups.values())),"selected_count":len(selected),"fn_improvement":fn,"fp_increase":fp,"roi":fn-fp,"buy_increase":len(selected),"buy_producing_races":selected_races,"buy_incidence_pct":round(100*selected_races/len(groups),2) if groups else 0,"explainability":"HIGH","rollback_ease":"HIGH","feature_flag":FEATURE_FLAG_NAME,"feature_flag_enabled":FEATURE_FLAG_ENABLED,"selected_horses":"; ".join(x["horse_name"] for x in selected)}

def run(root=Path("."), trace_path="reports/unconverged_primary_trace_latest_repaired_v1.csv"):
    root=Path(root); rows=read_latest(root/trace_path);groups=by_race(rows)
    comparison=[metrics(name,groups,fn) for name,fn in GUARDS.items()]
    comparison.sort(key=lambda x:(x["roi"],x["fn_improvement"],-x["fp_increase"]),reverse=True)
    best=comparison[0];judgment="GO" if best["fn_improvement"]>=1 and best["fp_increase"]<=1 and best["roi"]>=0 else "HOLD"
    summary={"status":judgment,"selected_guard":best["guard"],"selected_metrics":best,"comparison":comparison,"latest_race_ids":sorted(groups),"past_excluded":True,"feature_flag":{"name":FEATURE_FLAG_NAME,"enabled":FEATURE_FLAG_ENABLED,"fixed_off":True},"production_connected":False,"production_changed":False,"buy_changed":False,"decision_changed":False,"score_changed":False,"learning_changed":False,"target_trial_adapter_run":False,"main_py_run":False}
    out=root/"reports";out.mkdir(exist_ok=True)
    fields=list(comparison[0]);
    with (out/"unconverged_shadow_phase2_guard_comparison_v1.csv").open("w",encoding="utf-8-sig",newline="") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(comparison)
    (out/"unconverged_shadow_phase2_summary_v1.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return summary
if __name__=="__main__":print(json.dumps(run(),ensure_ascii=False,indent=2))
