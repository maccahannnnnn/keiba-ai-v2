"""Read-only structural diagnosis of saved BUY-gate trace artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "buy_gate_diagnostic_v1"
TOP5 = ROOT / "reports" / "failed_buy_root_cause_v1" / "top5_result_export.csv"
BLOCKS = {
    "JUNE_BLOCK_1": ("20260620", "20260621", "20260627", "20260628"),
    "JULY_H1": ("20260704", "20260705", "20260711", "20260712"),
    "JULY_H2": ("20260718", "20260719", "20260725", "20260726"),
    "AUGUST_DEVELOPMENT": ("20260801", "20260802", "20260808", "20260809", "20260815", "20260816"),
}
PREDICTION_ROOTS = {
    **{d: ROOT / "reports" / "h5_temporal_june_block1_v1" / f"prediction_{d}" for d in BLOCKS["JUNE_BLOCK_1"]},
    **{d: ROOT / "reports" / "cand_h5_001_july_4day_validation_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H1"]},
    **{d: ROOT / "reports" / "h5_temporal_july_h2_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H2"]},
    **{d: ROOT / "reports" / "buy_improvement_trace_6day_v1" / f"prediction_{d}" for d in BLOCKS["AUGUST_DEVELOPMENT"]},
}
GATES = ("absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass")
LIFTS = {"JUNE_BLOCK_1": -0.1008, "JULY_H1": 0.0427, "JULY_H2": 0.0920, "AUGUST_DEVELOPMENT": -0.0005}


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def boolean(v: object, field: str, identity: str) -> bool:
    if not isinstance(v, bool):
        raise RuntimeError(f"TRACE_FIELD_NOT_BOOLEAN:{field}:{identity}")
    return v


def rate(n: int, d: int) -> float | None: return n / d if d else None


def band(n: int) -> str:
    if n <= 9: return "TOO_SMALL"
    if n <= 19: return "OBSERVATION_ONLY"
    if n <= 29: return "DIRECTIONAL_WATCH"
    if n <= 49: return "MEANINGFUL_VALIDATION"
    if n <= 99: return "STRONG_RETROSPECTIVE_EVIDENCE"
    return "HIGH_CONFIDENCE_OPERATIONAL"


def parse_primary() -> dict[tuple[str, int], dict]:
    with TOP5.open(encoding="utf-8", newline="") as f: rows = list(csv.DictReader(f))
    if len(rows) != 1535: raise RuntimeError(f"TOP5_ROW_COUNT:{len(rows)}")
    indexed = {}
    for row in rows:
        key = (row["race_id"], int(row["horse_number"]))
        if key in indexed: raise RuntimeError(f"DUPLICATE_TOP5_HORSE:{key}")
        for field in ("is_buy", "valid_result", "actual_top3"):
            if row[field] not in {"True", "False"}: raise RuntimeError(f"PRIMARY_BOOLEAN_INVALID:{field}:{key}")
            row[field] = row[field] == "True"
        row["rank"] = int(row["rank"]); indexed[key] = row
    return indexed


def group_metrics(rows: list[dict]) -> dict:
    correct = [r for r in rows if r["actual_top3"]]
    incorrect = [r for r in rows if not r["actual_top3"]]
    gate = {}
    for name in GATES:
        cn = sum(not r[name] for r in correct); inn = sum(not r[name] for r in incorrect)
        cr, ir = rate(cn, len(correct)), rate(inn, len(incorrect))
        gate[name] = {"correct_rejected_fail_count":cn,"correct_rejected_denominator":len(correct),"correct_reject_gate_rate":cr,"incorrect_rejected_fail_count":inn,"incorrect_rejected_denominator":len(incorrect),"incorrect_reject_gate_rate":ir,"gate_error_enrichment":None if cr is None or ir is None else cr-ir}
    counts=Counter(r["failed_gate_count"] for r in rows)
    return {"path_g_horse_count":len(rows),"correct_rejected_horse_count":len(correct),"incorrect_rejected_horse_count":len(incorrect),"path_g_independent_race_count":len({r['race_id'] for r in rows}),"evidence_band":band(len({r['race_id'] for r in rows})),"gates":gate,"failed_gate_count_distribution":{str(i):counts[i] for i in range(1,5)},"multiple_gate_failure_count":sum(counts[i] for i in (2,3,4)),"multiple_gate_failure_rate":rate(sum(counts[i] for i in (2,3,4)),len(rows))}


def path_r_metrics(rows: list[dict]) -> dict:
    correct=sum(r["actual_top3"] for r in rows); races=len({r["race_id"] for r in rows})
    return {"path_r_horse_count":len(rows),"correct_horse_count":correct,"incorrect_horse_count":len(rows)-correct,"correct_rate":rate(correct,len(rows)),"independent_race_count":races,"evidence_band":band(races)}


def main() -> None:
    if OUT.exists(): raise RuntimeError("OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    primary=parse_primary(); trace={}; date_races=Counter(); trace_counts=Counter()
    for block,dates in BLOCKS.items():
        for date in dates:
            artifacts=sorted(PREDICTION_ROOTS[date].glob("race_*_prediction.json"))
            if not artifacts: raise RuntimeError(f"TRACE_ARTIFACT_MISSING:{date}")
            date_races[date]=len(artifacts)
            for path in artifacts:
                p=json.loads(path.read_text(encoding="utf-8")); race_id=p.get("race_id")
                horses=p.get("buy_gate_trace",{}).get("horses")
                if not race_id or not isinstance(horses,list): raise RuntimeError(f"TRACE_STRUCTURE_INVALID:{path}")
                for h in horses:
                    number=h.get("horse_number"); key=(race_id,number)
                    if not isinstance(number,int) or key in trace: raise RuntimeError(f"TRACE_IDENTITY_INVALID:{key}")
                    trace[key]=h; trace_counts[date]+=1
    missing=[{"race_id":a,"horse_number":b} for a,b in primary if (a,b) not in trace]
    alignment=[]
    for key,row in primary.items():
        h=trace.get(key)
        if h is None: continue
        observed=h.get("shadow_buy")
        if not isinstance(observed,bool): raise RuntimeError(f"TRACE_FIELD_NOT_BOOLEAN:shadow_buy:{key}")
        if row["is_buy"] != observed: alignment.append({"race_id":key[0],"horse_number":key[1],"is_buy":row["is_buy"],"shadow_buy":observed})
    alignment_report={"status":"PASS" if not missing and not alignment else "FAIL","primary_top5_rows":len(primary),"matched_horse_count":len(primary)-len(missing),"trace_runtime_missing_count":len(missing),"shadow_buy_mismatch_count":len(alignment),"mismatches":alignment,"missing_trace_records":missing}
    dump("buy_shadow_alignment.json",alignment_report)
    if missing or alignment: raise RuntimeError("STOPPED_BUY_SHADOW_ALIGNMENT_MISMATCH")
    records=[]
    for key,row in primary.items():
        h=trace[key]; identity=f"{key[0]}:{key[1]}"
        values={g:boolean(h.get(g),g,identity) for g in GATES}
        candidate=boolean(h.get("shadow_buy_candidate"),"shadow_buy_candidate",identity)
        shadow=boolean(h.get("shadow_buy"),"shadow_buy",identity)
        rel_diag=boolean(h.get("reliability_pass"),"reliability_pass",identity)
        if row["is_buy"] != shadow: raise RuntimeError("ALIGNMENT_RACE")
        path="BUY" if row["is_buy"] else "PATH_G" if not candidate else "PATH_R" if not shadow else "UNCLASSIFIED"
        records.append({**row,**values,"reliability_pass":rel_diag,"shadow_buy_candidate":candidate,"shadow_buy":shadow,"path":path,"failed_gate_count":sum(not values[g] for g in GATES),"failed_gates":[g for g in GATES if not values[g]]})
    nonbuy=[r for r in records if not r["is_buy"] and r["valid_result"]]
    unclassified=[r for r in nonbuy if r["path"] not in {"PATH_G","PATH_R"}]
    if unclassified: raise RuntimeError(f"PATH_EXHAUSTIVENESS_FAIL:{len(unclassified)}")
    path_g=[r for r in nonbuy if r["path"]=="PATH_G"]; path_r=[r for r in nonbuy if r["path"]=="PATH_R"]
    by_block={}
    for block in BLOCKS:
        block_nonbuy=[r for r in nonbuy if r["block"]==block]
        g=[r for r in block_nonbuy if r["path"]=="PATH_G"]; rr=[r for r in block_nonbuy if r["path"]=="PATH_R"]
        by_block[block]={"valid_non_buy_top5_horse_count":len(block_nonbuy),"valid_non_buy_top5_independent_race_count":len({r['race_id'] for r in block_nonbuy}),"path_g":group_metrics(g),"path_r":path_r_metrics(rr),"buy_selection_lift_context":LIFTS[block]}
    pooled={"valid_non_buy_top5_horse_count":len(nonbuy),"valid_non_buy_top5_independent_race_count":len({r['race_id'] for r in nonbuy}),"path_g":group_metrics(path_g),"path_r":path_r_metrics(path_r)}
    combos=Counter("|".join(r["failed_gates"]) for r in path_g)
    gate_rates={b:v["path_g"]["gates"] for b,v in by_block.items()}; enrichment={b:{g:x["gate_error_enrichment"] for g,x in v["path_g"]["gates"].items()} for b,v in by_block.items()}
    weak=("JUNE_BLOCK_1","AUGUST_DEVELOPMENT"); positive=("JULY_H1","JULY_H2")
    temporal={}
    supported=[]
    for gate in GATES:
        weakvals=[enrichment[b][gate] for b in weak if enrichment[b][gate] is not None]
        posvals=[enrichment[b][gate] for b in positive if enrichment[b][gate] is not None]
        weakmean=rate(sum(weakvals),len(weakvals)) if weakvals else None; posmean=rate(sum(posvals),len(posvals)) if posvals else None
        adverse=weakmean is not None and posmean is not None and weakmean>0 and weakmean>posmean
        temporal[gate]={"enrichment_by_block":{b:enrichment[b][gate] for b in BLOCKS},"weak_or_near_zero_period_mean":weakmean,"positive_lift_period_mean":posmean,"pattern":"STRONGER_IN_JUNE_AUGUST_THAN_JULY" if adverse else "CHANGES_IN_ANOTHER_DIRECTION" if weakmean is not None and posmean is not None else "TOO_SPARSE_TO_INTERPRET","single_gate_directional_signal":adverse}
        if adverse: supported.append("A")
    pathr_rates={b:by_block[b]["path_r"]["correct_rate"] for b in BLOCKS}; pathr_freq={b:rate(by_block[b]["path_r"]["path_r_horse_count"],by_block[b]["valid_non_buy_top5_horse_count"]) for b in BLOCKS}
    pathr_alignment=False
    temporal["PATH_R"]={"correct_rate_by_block":pathr_rates,"frequency_by_block":pathr_freq,"observability":"Downstream reason is intentionally not reconstructed from candidate counts or race structure.","downstream_path_directional_signal":pathr_alignment}
    if pathr_alignment: supported.append("B")
    different=any(t["pattern"]=="CHANGES_IN_ANOTHER_DIRECTION" for g,t in temporal.items() if g in GATES)
    if different: supported.append("C")
    if not supported: supported.append("D")
    if len([g for g in GATES if temporal[g]["single_gate_directional_signal"]])==0 and len(combos)>1: supported.append("E")
    primary_decision="BUY_GATE_DIAGNOSTIC_SIGNAL_FOUND" if "A" in supported or "B" in supported else "BUY_GATE_DIAGNOSTIC_TEMPORALLY_COMPLEX" if "C" in supported or "E" in supported else "BUY_GATE_DIAGNOSTIC_NOT_EXPLANATORY"
    dump("source_validation.json",{"status":"PASS","source_dates":18,"source_races":307,"source_prediction_horses":sum(trace_counts.values()),"primary_top5_rows":len(primary),"trace_matched_top5_rows":len(primary),"prediction_roots":{d:str(p.relative_to(ROOT)) for d,p in PREDICTION_ROOTS.items()},"trace_counts_by_date":dict(trace_counts),"no_prediction_rerun":True})
    dump("path_decomposition.json",{"valid_non_buy_top5_count":len(nonbuy),"PATH_G_count":len(path_g),"PATH_R_count":len(path_r),"unclassified_count":len(unclassified),"path_partition_exhaustive":True,"pooled":pooled})
    dump("gate_rates_by_block.json",gate_rates); dump("gate_enrichment_by_block.json",enrichment)
    dump("failed_gate_count_distribution.json",{"pooled":pooled["path_g"],"by_block":{b:v["path_g"] for b,v in by_block.items()}})
    dump("gate_combination_appendix.json",{"maximum_possible_combinations":16,"observed_combinations":dict(sorted(combos.items())),"interpretation_boundary":"Appendix only; combinations are not promoted into hypotheses or Candidates."})
    dump("path_r_by_block.json",{"by_block":{b:v["path_r"] for b,v in by_block.items()},"pooled":pooled["path_r"],"reason_boundary":"One observed downstream category; detailed runtime reason was not reconstructed."})
    dump("evidence_by_block.json",{"by_block":by_block,"pooled_independent_race_count":pooled["valid_non_buy_top5_independent_race_count"],"independent_evidence_unit":"RACE"})
    dump("temporal_interpretation.json",{"buy_selection_lift_context":LIFTS,"gate_interpretation":temporal,"temporal_comparison_rule":"No numerical cutoff was added; observed enrichment direction and weak/near-zero versus positive-period ordering are reported descriptively."})
    dump("analysis_gate.json",{"primary_operational_conclusion":primary_decision,"supported_outcomes":sorted(set(supported)),"candidate_created":False,"production_changes":0,"buy_changes":0,"decision_changes":0,"prediction_reruns":0})
    summary={"final_decision":primary_decision,"supported_analysis_gate_outcomes":sorted(set(supported)),"source_dates":18,"source_races":307,"matched_horse_count":len(primary),"is_buy_shadow_buy_mismatch_count":0,"valid_non_buy_top5_count":len(nonbuy),"PATH_G_count":len(path_g),"PATH_R_count":len(path_r),"unclassified_count":0,"pooled":pooled,"no_candidate_created":True,"no_production_buy_decision_change":True}
    dump("summary.json",summary)
    fmt=lambda x:"n/a" if x is None else f"{x:.2%}"
    lines=["# BUY Gate Failure Diagnostic v1","",f"Final conclusion: `{primary_decision}`.","", "## Path decomposition", "", "| Block | Valid non-BUY Top5 | PATH_G | PATH_R | BUY-selection lift context |", "|---|---:|---:|---:|---:|"]
    for b,v in by_block.items(): lines.append(f"| {b} | {v['valid_non_buy_top5_horse_count']} | {v['path_g']['path_g_horse_count']} | {v['path_r']['path_r_horse_count']} | {fmt(v['buy_selection_lift_context'])} |")
    lines += ["", "## Pooled PATH_G gate rates", "", "| Operative gate | Correct rejected fail rate | Incorrect rejected fail rate | Error enrichment |", "|---|---:|---:|---:|"]
    for gate, values in pooled["path_g"]["gates"].items():
        lines.append(f"| {gate} | {fmt(values['correct_reject_gate_rate'])} ({values['correct_rejected_fail_count']}/{values['correct_rejected_denominator']}) | {fmt(values['incorrect_reject_gate_rate'])} ({values['incorrect_rejected_fail_count']}/{values['incorrect_rejected_denominator']}) | {fmt(values['gate_error_enrichment'])} |")
    lines += ["", f"", f"PATH_G multiple-gate failures: {pooled['path_g']['multiple_gate_failure_count']}/{pooled['path_g']['path_g_horse_count']} ({fmt(pooled['path_g']['multiple_gate_failure_rate'])}).", f"PATH_R correct rate: {pooled['path_r']['correct_horse_count']}/{pooled['path_r']['path_r_horse_count']} ({fmt(pooled['path_r']['correct_rate'])}).", "", "`PATH_R` is retained as one observed downstream category. No detailed downstream reason was inferred.", "", f"Supported analysis outcomes: {', '.join(sorted(set(supported)))}.", "", "No Candidate was created; no Prediction rerun and no Production/BUY/Decision modification occurred."]
    (OUT / "report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")

if __name__ == "__main__": main()
