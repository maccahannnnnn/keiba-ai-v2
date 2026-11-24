"""Twenty-seed within-race label-shuffle completion for Jockey Tier V1."""
from __future__ import annotations

import copy, csv, hashlib, json, math, random, statistics, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from analysis import jockey_tier_shadow_validation_v1 as v1

REPORTS = ROOT / "reports"
INPUT = REPORTS / "jockey_tier_rank_transition_v1.csv"
V1_SUMMARY = REPORTS / "jockey_tier_shadow_summary_v1.json"
TIER_TABLE = REPORTS / "jockey_tier_table_v1.json"
SPEC = REPORTS / "jockey_tier_placebo_preregistered_spec_v1.md"
SEEDS = (11,17,23,29,37,41,47,53,59,67,71,73,79,83,89,97,101,103,107,109)
METRICS = ("rank1_3_top3_rate","mean_actual_top3_rank","ndcg_at_3","mrr","rank1_top3_rate","top5_capture_rate")
OUTPUTS = {
    "seeds": REPORTS / "jockey_tier_placebo_seed_results_v1.csv",
    "distribution": REPORTS / "jockey_tier_placebo_distribution_v1.csv",
    "percentiles": REPORTS / "jockey_tier_placebo_observed_percentile_v1.csv",
    "summary": REPORTS / "jockey_tier_placebo_summary_v1.json",
    "report": REPORTS / "jockey_tier_placebo_report_v1.md",
    "safety": REPORTS / "jockey_tier_placebo_safety_v1.json",
    "zero": REPORTS / "jockey_tier_placebo_zero_delta_v1.json",
    "tests": REPORTS / "jockey_tier_placebo_test_manifest_v1.json",
    "roi": REPORTS / "jockey_tier_placebo_roi_update_v1.md",
    "claude": REPORTS / "jockey_tier_placebo_claude_review_packet_v1.md",
}
V1_PROTECTED = [
    REPORTS / name for name in (
        "jockey_tier_table_v1.json","jockey_tier_table_v1.csv","jockey_tier_generation_manifest_v1.json",
        "jockey_tier_shadow_summary_v1.json","jockey_tier_rank_transition_v1.csv","jockey_tier_metric_comparison_v1.csv",
        "jockey_tier_shadow_safety_v1.json","jockey_tier_shadow_zero_delta_v1.json",
    )
]

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def v1_hashes(): return {p.name: sha(p) for p in V1_PROTECTED}
def read_rows():
    rows = v1.read_csv(INPUT)
    for r in rows:
        for key in ("production_adjusted_score",): r[key] = v1.number(r[key])
        for key in ("production_rank","shadow_jockey_sample_size","shadow_jockey_score","shadow_rank","actual_finish"): r[key] = v1.integer(r[key])
        for key in ("valid_result","actual_top3","buy"): r[key] = v1.truth(r[key])
    return rows
def groups(rows):
    out=defaultdict(list)
    for r in rows: out[(r["cohort"],r["race_id"])].append(r)
    return out
def race_seed(seed, cohort, race_id): return int.from_bytes(hashlib.sha256(f"{seed}|{cohort}|{race_id}|JOCKEY_TIER_V1".encode()).digest()[:8],"big")
def assign(rows, seed):
    out=[]
    for (cohort,race_id), rr in sorted(groups(rows).items()):
        ordered=sorted(rr,key=lambda r:r["production_rank"])
        labels=[(r["shadow_jockey_tier"],r["shadow_jockey_sample_size"],r["shadow_jockey_score"]) for r in ordered]
        shuffled=list(labels); random.Random(race_seed(seed,cohort,race_id)).shuffle(shuffled)
        race=[]
        for src,label in zip(ordered,shuffled):
            row=copy.deepcopy(src); tier,sample,score=label
            row.update({"placebo_seed":seed,"placebo_tier":tier,"placebo_sample_size":sample,"placebo_score":score,"placebo_adjusted_score":round(row["production_adjusted_score"]+score,10)})
            race.append(row)
        ranked=sorted(race,key=lambda r:(-r["placebo_adjusted_score"],r["production_rank"]))
        for rank,row in enumerate(ranked,1): row["placebo_rank"]=rank
        out.extend(race)
    return out
def metric(rows, rank): return v1.metric_values(rows,rank)
def seed_result(cohort, seed, rows):
    prod, pla = metric(rows,"production_rank"), metric(rows,"placebo_rank")
    result={"cohort":cohort,"seed":seed,"race_count":len({r['race_id'] for r in rows}),"horse_count":len(rows)}
    for m in METRICS:
        result[f"production_{m}"]=round(prod[m],10); result[f"placebo_{m}"]=round(pla[m],10); result[f"delta_{m}"]=round(pla[m]-prod[m],10)
    result["movement_rate"]=round(sum(r["production_rank"]!=r["placebo_rank"] for r in rows)/len(rows),10)
    return result
def percentile(vals,p):
    vals=sorted(vals); x=(len(vals)-1)*p; lo,hi=math.floor(x),math.ceil(x)
    return vals[lo] if lo==hi else vals[lo]+(vals[hi]-vals[lo])*(x-lo)
def percentile_rank(vals, observed): return 100*(sum(v<observed for v in vals)+0.5*sum(v==observed for v in vals))/len(vals)
def distributions(seed_rows, observed):
    dist=[]; ranks=[]
    for cohort in ("BASELINE","REPLAY"):
        selected=[r for r in seed_rows if r["cohort"]==cohort]
        for metric_name in METRICS:
            vals=[r[f"delta_{metric_name}"] for r in selected]; obs=observed[cohort]["delta"][metric_name]
            row={"cohort":cohort,"metric":metric_name,"seed_count":20,"observed_delta":obs,"placebo_mean":statistics.mean(vals),"placebo_population_sd":statistics.pstdev(vals),"placebo_min":min(vals),"placebo_p05":percentile(vals,.05),"placebo_p10":percentile(vals,.10),"placebo_median":statistics.median(vals),"placebo_p90":percentile(vals,.90),"placebo_p95":percentile(vals,.95),"placebo_max":max(vals),"observed_percentile":percentile_rank(vals,obs)}
            dist.append(row); ranks.append({"cohort":cohort,"metric":metric_name,"observed_delta":obs,"observed_percentile":row["observed_percentile"],"above_placebo_p95":obs>row["placebo_p95"],"above_placebo_median":obs>row["placebo_median"]})
    return dist,ranks
def interpret(ranks):
    by={(r["cohort"],r["metric"]):r for r in ranks}
    a=[by[(c,"rank1_3_top3_rate")] for c in ("BASELINE","REPLAY")]
    if all(r["above_placebo_p95"] for r in a) and all(by[(c,"mean_actual_top3_rank")]["observed_percentile"]<50 for c in ("BASELINE","REPLAY")) and all(by[(c,m)]["above_placebo_median"] for c in ("BASELINE","REPLAY") for m in ("ndcg_at_3","mrr")): return "OTHER_SIGNAL_ABOVE_PLACEBO_BUT_V1_REJECT_CLOSED"
    if all(r["observed_percentile"]<=50 for r in a): return "REJECT_CONFIRMED"
    return "PLACEBO_VARIANCE_HOLD"
def write_csv(path,rows):
    with path.open("w",encoding="utf-8-sig",newline="") as h: w=csv.DictWriter(h,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
def write_json(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def run(test_status="PENDING_EXTERNAL_TEST_COMMAND"):
    before=v1.protected_snapshot(); v1_before=v1_hashes(); rows=read_rows(); v1_summary=json.loads(V1_SUMMARY.read_text(encoding="utf-8")); table=json.loads(TIER_TABLE.read_text(encoding="utf-8"))
    if table["table_sha256"]!="3cdb6e18fe4594b0e2250de7e5d2ce086acbe8b3737cab2bd973e855f217f938": raise RuntimeError("TIER_TABLE_CHANGED")
    seed_rows=[]; exact=True; mutations=[]
    production_fields=("production_adjusted_score","production_rank","decision","race_decision","buy","valid_result","actual_finish","actual_top3")
    for seed in SEEDS:
        placebo=assign(rows,seed); original={(r["cohort"],r["race_id"],r["horse_number"]):r for r in rows}
        for r in placebo:
            src=original[(r["cohort"],r["race_id"],r["horse_number"])]
            for f in production_fields:
                if r.get(f)!=src.get(f): mutations.append((seed,r["cohort"],r["race_id"],r["horse_number"],f))
        for key,rr in groups(placebo).items(): exact &= Counter((r["shadow_jockey_tier"],r["shadow_jockey_score"]) for r in groups(rows)[key])==Counter((r["placebo_tier"],r["placebo_score"]) for r in rr)
        for cohort in ("BASELINE","REPLAY"): seed_rows.append(seed_result(cohort,seed,[r for r in placebo if r["cohort"]==cohort]))
    dist,ranks=distributions(seed_rows,v1_summary["cohort_results"]); interpretation=interpret(ranks)
    after=v1.protected_snapshot(); v1_after=v1_hashes(); protected_changes=[k for k in before if before[k]!=after[k]]; v1_changes=[k for k in v1_before if v1_before[k]!=v1_after[k]]
    zero=not mutations and not protected_changes and not v1_changes; safety=zero and exact
    if not safety: interpretation="SAFETY_HOLD"
    generated=datetime.now(timezone.utc).isoformat()
    summary={"schema_version":"jockey_tier_placebo_summary_v1","generated_at":generated,"final_interpretation":interpretation,"jockey_v1_original_decision":"REJECT","jockey_v1_closed":True,"tier_table_sha256":table["table_sha256"],"spec_sha256":sha(SPEC),"seeds":list(SEEDS),"seed_count":20,"label_shuffle":"WITHIN_RACE_TIER_LABEL_AND_SCORE","within_race_distribution_exact":exact,"observed_percentiles":ranks,"safety_status":"PASS" if safety else "FAIL","zero_delta_status":"PASS" if zero else "FAIL","target_trial_adapter_run_count":0,"replay_run_count":0,"evaluator_run_count":0,"production_write_count":0,"learning_write_count":0,"knowledge_write_count":0,"new_shadow_candidate_created":False,"jockey_v2_executed":False,"automatic_next_candidate":False}
    safety_json={"schema_version":"jockey_tier_placebo_safety_v1","generated_at":generated,"status":"PASS" if safety else "FAIL","within_race_distribution_exact":exact,"production_field_mutation_count":len(mutations),"protected_changes":protected_changes,"jockey_v1_artifact_changes":v1_changes,"target_trial_adapter_run_count":0,"replay_run_count":0,"evaluator_run_count":0,"production_write_count":0,"learning_write_count":0,"knowledge_write_count":0}
    zero_json={"schema_version":"jockey_tier_placebo_zero_delta_v1","generated_at":generated,"status":"PASS" if zero else "FAIL","production_field_mutation_count":len(mutations),"protected_changes":protected_changes,"jockey_v1_artifact_changes":v1_changes,"feature_flag_off_input_identity":True}
    tests={"schema_version":"jockey_tier_placebo_test_manifest_v1","generated_at":generated,"test_file":"tests/test_jockey_tier_placebo_v1.py","test_method_count":18,"subtest_count":0,"actual_status":test_status,"commands":["python -m py_compile analysis/jockey_tier_placebo_v1.py tests/test_jockey_tier_placebo_v1.py","python -m unittest tests.test_jockey_tier_placebo_v1 -v"]}
    write_csv(OUTPUTS["seeds"],seed_rows); write_csv(OUTPUTS["distribution"],dist); write_csv(OUTPUTS["percentiles"],ranks); write_json(OUTPUTS["summary"],summary); write_json(OUTPUTS["safety"],safety_json); write_json(OUTPUTS["zero"],zero_json); write_json(OUTPUTS["tests"],tests)
    a={r["cohort"]:r for r in ranks if r["metric"]=="rank1_3_top3_rate"}
    report=f"""# Jockey Tier V1 Placebo Completion\n\n## Final interpretation\n\n**{interpretation}**\n\n|Cohort|Observed A delta|Observed percentile|Above p95|\n|---|---:|---:|---:|\n|Baseline|{a['BASELINE']['observed_delta']:+.4f}|{a['BASELINE']['observed_percentile']:.1f}|{a['BASELINE']['above_placebo_p95']}|\n|Replay|{a['REPLAY']['observed_delta']:+.4f}|{a['REPLAY']['observed_percentile']:.1f}|{a['REPLAY']['above_placebo_p95']}|\n\nTier table, coefficients and boundaries were unchanged. Safety/ZERO_DELTA: {summary['safety_status']}/{summary['zero_delta_status']}. Jockey Tier V1 remains REJECT and is now formally closed. No V2 or new candidate was created.\n"""
    OUTPUTS["report"].write_text(report,encoding="utf-8")
    roi=f"""# ROI Update after Jockey Tier V1 Placebo\n\n|Workstream|Status|Next action|\n|---|---|---|\n|Jockey Tier V1|{interpretation}; CLOSED|No V2; do not reopen automatically|\n|Jockey Tier V2|WITHDRAWN|Do not execute|\n|New Shadow candidate|NOT_CREATED|Human authorization required|\n|Ranking redesign|REASSESS_ONLY|Claude/ChatGPT/Human ROI review|\n"""; OUTPUTS["roi"].write_text(roi,encoding="utf-8")
    OUTPUTS["claude"].write_text(f"# Claude Review Packet: Jockey Tier V1 Placebo\n\n- Interpretation: **{interpretation}**\n- Tier SHA: `{table['table_sha256']}`\n- Seeds: `{list(SEEDS)}`\n- Distribution exact / Safety / ZERO_DELTA: `{exact} / {summary['safety_status']} / {summary['zero_delta_status']}`\n- V2/new candidate: `NO / NO`\n\nPlease verify within-race label preservation, observed percentile calculation, frozen interpretation, and formal closure.\n",encoding="utf-8")
    print(json.dumps({"interpretation":interpretation,"A_percentiles":a,"safety":summary["safety_status"]},ensure_ascii=False)); return summary
if __name__=="__main__": run("PASS" if "--tests-passed" in sys.argv else "PENDING_EXTERNAL_TEST_COMMAND")
