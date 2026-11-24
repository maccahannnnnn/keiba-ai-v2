"""Read-only PATH_G exact failed-Gate-count diagnostic."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "buy_gate_count_correct_rejected_v1"
TOP5 = ROOT / "reports" / "failed_buy_root_cause_v1" / "top5_result_export.csv"
BLOCKS={"JUNE_BLOCK_1":("20260620","20260621","20260627","20260628"),"JULY_H1":("20260704","20260705","20260711","20260712"),"JULY_H2":("20260718","20260719","20260725","20260726"),"AUGUST_DEVELOPMENT":("20260801","20260802","20260808","20260809","20260815","20260816")}
ROOTS={**{d:ROOT/"reports"/"h5_temporal_june_block1_v1"/f"prediction_{d}" for d in BLOCKS["JUNE_BLOCK_1"]},**{d:ROOT/"reports"/"cand_h5_001_july_4day_validation_v1"/f"prediction_{d}" for d in BLOCKS["JULY_H1"]},**{d:ROOT/"reports"/"h5_temporal_july_h2_v1"/f"prediction_{d}" for d in BLOCKS["JULY_H2"]},**{d:ROOT/"reports"/"buy_improvement_trace_6day_v1"/f"prediction_{d}" for d in BLOCKS["AUGUST_DEVELOPMENT"]}}
GATES=("absolute_quality_pass","relative_advantage_pass","effective_reliability_pass","risk_guard_pass")

def dump(name:str,value:object)->None:(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def rate(n:int,d:int):return n/d if d else None
def band(n:int)->str:
    return "TOO_SMALL" if n<=9 else "OBSERVATION_ONLY" if n<=19 else "DIRECTIONAL_WATCH" if n<=29 else "MEANINGFUL_VALIDATION" if n<=49 else "STRONG_RETROSPECTIVE_EVIDENCE" if n<=99 else "HIGH_CONFIDENCE_OPERATIONAL"
def truth(v:object,field:str,key:tuple)->bool:
    if not isinstance(v,bool):raise RuntimeError(f"TRACE_FIELD_INVALID:{field}:{key}")
    return v

def summary(rows:list[dict],correct:bool)->dict:
    group=[r for r in rows if r["actual_top3"]==correct]; denom=len(group); counts=Counter(r["failed_gate_count"] for r in group)
    distribution={}
    for n in range(1,5):
        subset=[r for r in group if r["failed_gate_count"]==n]
        races=len({r["race_id"] for r in subset})
        distribution[str(n)]={"horse_count":len(subset),"percentage_of_group":rate(len(subset),denom),"independent_race_count":races,"evidence_band":band(races)}
    single={}
    singles=[r for r in group if r["failed_gate_count"]==1]
    for gate in GATES:
        subset=[r for r in singles if r["failed_gates"]==[gate]]; races=len({r["race_id"] for r in subset})
        single[gate.replace("_pass","")+"_only"]={"horse_count":len(subset),"percentage_of_group":rate(len(subset),denom),"percentage_of_exactly_one_gate_group":rate(len(subset),len(singles)),"independent_race_count":races,"evidence_band":band(races)}
    return {"group_horse_count":denom,"group_independent_race_count":len({r['race_id'] for r in group}),"group_evidence_band":band(len({r['race_id'] for r in group})),"failed_gate_count_distribution":distribution,"single_gate_correct_reject_share" if correct else "single_gate_incorrect_reject_share":rate(len(singles),denom),"single_gate_breakdown":single}

def main()->None:
    if OUT.exists():raise RuntimeError("OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    with TOP5.open(encoding="utf-8",newline="") as f: primary=list(csv.DictReader(f))
    if len(primary)!=1535:raise RuntimeError("TOP5_ROW_COUNT")
    idx={(r["race_id"],int(r["horse_number"])):r for r in primary}
    if len(idx)!=1535:raise RuntimeError("TOP5_DUPLICATE")
    traces={}
    for block,dates in BLOCKS.items():
      for date in dates:
       for p in sorted(ROOTS[date].glob("race_*_prediction.json")):
        payload=json.loads(p.read_text(encoding="utf-8")); race=payload["race_id"]
        for h in payload["buy_gate_trace"]["horses"]:traces[(race,h["horse_number"])]=h
    if len(traces)!=3925:raise RuntimeError(f"TRACE_COVERAGE:{len(traces)}")
    records=[]
    for key,row in idx.items():
        h=traces.get(key)
        if h is None:raise RuntimeError(f"TRACE_MISSING:{key}")
        isbuy=row["is_buy"]=="True"; valid=row["valid_result"]=="True"; top3=row["actual_top3"]=="True"
        candidate=truth(h.get("shadow_buy_candidate"),"shadow_buy_candidate",key); shadow=truth(h.get("shadow_buy"),"shadow_buy",key)
        if isbuy!=shadow:raise RuntimeError(f"BUY_ALIGNMENT:{key}")
        values={g:truth(h.get(g),g,key) for g in GATES}
        if not isbuy and valid and not candidate:
            failed=[g for g in GATES if not values[g]]
            if len(failed) not in {1,2,3,4}:raise RuntimeError(f"PATH_G_FAILURE_COUNT_INVALID:{key}")
            records.append({"block":row["block"],"date":row["date"],"race_id":key[0],"actual_top3":top3,"failed_gate_count":len(failed),"failed_gates":failed})
    correct=[r for r in records if r["actual_top3"]]; incorrect=[r for r in records if not r["actual_top3"]]
    if len(records)!=1008 or len(correct)!=319 or len(incorrect)!=689:raise RuntimeError(f"POPULATION_RECONCILIATION:{len(records)}:{len(correct)}:{len(incorrect)}")
    by_block={}
    for b in BLOCKS:
        rows=[r for r in records if r["block"]==b]
        by_block[b]={"correct_rejected":summary(rows,True),"incorrect_rejected":summary(rows,False)}
    pooled={"correct_rejected":summary(records,True),"incorrect_rejected":summary(records,False)}
    multi=sum(r["failed_gate_count"]>=2 for r in correct); single=sum(r["failed_gate_count"]==1 for r in correct)
    # "Most" has its ordinary literal meaning: more than one half; no tuned threshold is used.
    supported=["RESULT_2_MULTI_GATE_STRUCTURE_DOMINANT"] if multi>len(correct)/2 else []
    single_races={gate:pooled["correct_rejected"]["single_gate_breakdown"][gate.replace("_pass","")+"_only"]["independent_race_count"] for gate in GATES}
    # The prescribed evidence-band labels determine whether any single-Gate category has strong retrospective support.
    if single and any(band(n) in {"STRONG_RETROSPECTIVE_EVIDENCE","HIGH_CONFIDENCE_OPERATIONAL"} for n in single_races.values()):supported.append("RESULT_1_SINGLE_GATE_SCOPE_MATERIAL")
    # Record variation; do not turn an unspecified magnitude into a formal threshold.
    shares=[by_block[b]["correct_rejected"]["single_gate_correct_reject_share"] for b in BLOCKS]
    if len(set(shares))>1:supported.append("RESULT_3_TEMPORALLY_DIFFERENT_SINGLE_GATE_SCOPE")
    if not single or all(band(n) in {"TOO_SMALL","OBSERVATION_ONLY"} for n in single_races.values()):supported.append("RESULT_4_TOO_SMALL_FOR_SINGLE_GATE_ATTRIBUTION")
    conclusion="MULTI_GATE_STRUCTURE_DOMINANT" if "RESULT_2_MULTI_GATE_STRUCTURE_DOMINANT" in supported else "SINGLE_GATE_SCOPE_MATERIAL" if "RESULT_1_SINGLE_GATE_SCOPE_MATERIAL" in supported else "TEMPORALLY_DIFFERENT_SINGLE_GATE_SCOPE" if "RESULT_3_TEMPORALLY_DIFFERENT_SINGLE_GATE_SCOPE" in supported else "TOO_SMALL_FOR_SINGLE_GATE_ATTRIBUTION"
    dump("source_validation.json",{"status":"PASS","source":"existing saved Top5 export plus saved buy_gate_trace only","source_dates":18,"source_races":307,"top5_rows":1535,"trace_horses":len(traces),"PATH_G":len(records),"CORRECT_REJECTED":len(correct),"INCORRECT_REJECTED":len(incorrect),"operative_gate_count":4,"prediction_rerun":False})
    dump("correct_failed_gate_count.json",{"by_block":{b:v["correct_rejected"] for b,v in by_block.items()},"pooled":pooled["correct_rejected"]})
    dump("incorrect_failed_gate_count.json",{"by_block":{b:v["incorrect_rejected"] for b,v in by_block.items()},"pooled":pooled["incorrect_rejected"]})
    dump("correct_single_gate_breakdown.json",{"by_block":{b:v["correct_rejected"]["single_gate_breakdown"] for b,v in by_block.items()},"pooled":pooled["correct_rejected"]["single_gate_breakdown"]})
    dump("incorrect_single_gate_breakdown.json",{"by_block":{b:v["incorrect_rejected"]["single_gate_breakdown"] for b,v in by_block.items()},"pooled":pooled["incorrect_rejected"]["single_gate_breakdown"]})
    dump("evidence_by_block.json",{"independent_evidence_unit":"RACE","by_block":by_block,"pooled":pooled})
    dump("temporal_comparison.json",{"correct_exact_one_share_by_block":{b:by_block[b]["correct_rejected"]["single_gate_correct_reject_share"] for b in BLOCKS},"single_gate_race_support_pooled":single_races,"interpretation_boundary":"Differences are reported descriptively. No new magnitude cutoff or Gate rule was created."})
    dump("analysis_gate.json",{"primary_conclusion":conclusion,"supported_outcomes":supported,"PATH_R_priority_change":"NO","candidate_created":False,"production_changes":0,"prediction_reruns":0,"threshold_changes":0})
    dump("summary.json",{"final_conclusion":conclusion,"supported_outcomes":supported,"correct_rejected_total":319,"incorrect_rejected_total":689,"correct_exactly_one_gate_count":single,"correct_multiple_gate_count":multi,"correct_single_gate_share":rate(single,319),"correct_multi_gate_share":rate(multi,319),"pooled":pooled,"no_candidate_created":True,"no_prediction_buy_decision_production_change":True})
    fmt=lambda x:"n/a" if x is None else f"{x:.2%}"
    lines=["# BUY Gate Count — Correct Rejected v1","",f"Primary conclusion: `{conclusion}`.","",f"Correct rejected horses: {len(correct)}. Exactly one failed operative Gate: {single}/{len(correct)} ({fmt(rate(single,len(correct)))}). Multiple failed Gates: {multi}/{len(correct)} ({fmt(rate(multi,len(correct)))}).", "", "| Block | Correct exactly-one | Correct multi-Gate | Correct races | Incorrect exactly-one | Incorrect multi-Gate |", "|---|---:|---:|---:|---:|---:|"]
    for b,v in by_block.items():
      c=v["correct_rejected"]; i=v["incorrect_rejected"]; lines.append(f"| {b} | {c['failed_gate_count_distribution']['1']['horse_count']} ({fmt(c['single_gate_correct_reject_share'])}) | {sum(c['failed_gate_count_distribution'][str(n)]['horse_count'] for n in (2,3,4))} | {c['group_independent_race_count']} | {i['failed_gate_count_distribution']['1']['horse_count']} ({fmt(i['single_gate_incorrect_reject_share'])}) | {sum(i['failed_gate_count_distribution'][str(n)]['horse_count'] for n in (2,3,4))} |")
    lines += ["", "This is a structural upper-bound population only. It does not estimate successful BUYs or authorize a single-Gate intervention.", "", "PATH_R was not expanded. No Candidate, Prediction rerun, BUY/Decision, or Production change was made."]
    (OUT/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")

if __name__=="__main__":main()
