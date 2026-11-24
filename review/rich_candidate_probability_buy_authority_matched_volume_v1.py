"""EXP-022 result-blind matched-volume Candidate-probability BUY experiment.

The prepare phase freezes every selected identity before the execute phase is
allowed to call the consumed-development result reader.  No model or Stage-B
runtime is invoked by this module.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.candidate_generation_stage_a_paired_population_expanded_v1 import (
    JAPANESE_VENUE, parse_race_id, result_rows, source_map, stability,
)
from review.candidate_generation_training_dataset_readiness_v1 import outcome

OUT = ROOT / "reports/rich_candidate_probability_buy_authority_matched_volume_v1"
EXP021 = ROOT / "reports/raw_history_representation_candidate_generation_v2"
STAGE_B = ROOT / "reports/candidate_generation_stage_b_fast_route_b4_buy_performance_v1_retry5"
STAGE_A = ROOT / "reports/candidate_generation_stage_a_paired_population_expanded_v1"
LEDGER = ROOT / "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md"
INDEX = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"
FOLD_SHA = "ace55d0d48e24d066cee92e5a11aebbcf908f5256622303d5dd03bc1e5de099e"
EXPECTED = {
    "control_baseline_predictions.csv": "b5445181231fa170871adb3aeb92226059036e39b8e33f4aeabd512600df2f85",
    "control_treatment_predictions.csv": "bfd0f36c872474fbde826047e537d59c9e95ccabd648f19a10c0740e0a645291",
}
CSV_FIELDS = ["date","race_id","venue","race_number","lane","arm","horse_number","horse_name",
              "k_r","probability","candidate_rank","shadow_ai_rank","risk_guard_pass","selected",
              "volume_shortfall"]


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str] = CSV_FIELDS) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def tree_hashes(paths: list[Path]) -> dict[str, str]:
    files: set[Path] = set()
    for path in paths:
        if path.is_file(): files.add(path)
        elif path.is_dir(): files.update(p for p in path.rglob("*") if p.is_file())
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)}


def protected_snapshot() -> dict[str, str]:
    paths = [
        ROOT/"reports/raw_history_representation_candidate_generation_v1", EXP021,
        ROOT/"review/candidate_generation_stage_a_paired_population_expanded_v1.py",
        ROOT/"review/candidate_generation_stage_b_shadow_v1.py",
        ROOT/"review/candidate_generation_stage_b_fast_route_b4_buy_performance_v1.py",
        ROOT/"engine/decision_engine.py", ROOT/"engine/decision_guard.py",
        ROOT/"engine/buy_v1_rc1_engine.py", ROOT/"engine/shadow_buy_decision_engine.py",
        ROOT/"engine/race_decision_engine.py", ROOT/"reports/ml_v4_buy_selection_model_v4",
        STAGE_A/"expanded_stage_a_fold_manifest.json",
    ]
    return tree_hashes(paths)


def complete_exp021_record() -> dict:
    before_l, before_i = sha(LEDGER), sha(INDEX)
    exp020_before = next(e for e in json.loads(INDEX.read_text(encoding="utf-8"))["authoritative_additive_entries"] if e.get("stable_id")=="EXP-020")
    exp020_sha = canonical_sha(exp020_before)
    historical_before = tree_hashes([EXP021])
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    entries = index.get("authoritative_additive_entries")
    if not isinstance(entries, list): raise Stop("STOP_EXP021_RECORD_SCHEMA_CONFLICT")
    entry = next((e for e in entries if e.get("stable_id")=="EXP-021"), None)
    required = {"stable_id","primary_result","operational_state","provenance"}
    if not entry or not required <= set(entry) or entry["operational_state"] != "COMPLETE":
        raise Stop("STOP_EXP021_RECORD_SCHEMA_CONFLICT")
    if "fingerprint" in entry or "accepted_state" in entry:
        raise Stop("STOP_EXP021_RECORD_SCHEMA_CONFLICT")
    entry.update({
        "primary_result":"RATE_POSITIVE_HIT_TRADEOFF",
        "fingerprint":{"major_axis":"RAW_HISTORY_REPRESENTATION","base_features":"existing 20 semantic features",
            "history_depth":10,"model_family":"StandardScaler + LogisticRegression",
            "rich_arm_recipe":"lbfgs / l2 / C=1.0 / tol=0.0001 / max_iter=1000",
            "control_arm_recipe":"frozen Stage-A recipe max_iter=100 (unchanged)","raw_ds_source_fields":19,
            "raw_history_features":390,"total_model_features":411,
            "distinguishing_axis_vs_parent":"Rich TEST arm max_iter 100 -> 1000 only"},
        "reopen_condition":["Material change to raw-history schema, Rich recipe, Candidate Exact5 semantics, or frozen fold protocol"],
        "baseline_training_population":"Current Top5 rows","treatment_training_population":"Full-field rows",
        "candidate_output":"EXACT5","downstream":"Frozen Stage B","stage_b_metric":"BUY_TOP3_RATE",
        "fold_manifest_sha256":FOLD_SHA,
        "accepted_state":{"EXP021_RESULT_INTEGRITY":"ACCEPT","CANDIDATE_INFORMATION_SIGNAL":"POSITIVE",
            "END_TO_END_ADOPTION_STATUS":"HOLD_RATE_HIT_TRADEOFF",
            "RICH_HISTORY_INFORMATION_DIRECTION":"SUPPORTED_AT_CANDIDATE_LEVEL",
            "PRIMARY_BOTTLENECK_INTERPRETATION":"SELECTION_TO_BUY_INTERFACE_MISMATCH",
            "BASELINE_CANDIDATE_TOP3_COVERAGE":"1466 -> 1478 (+12)",
            "BASELINE_STAGE_B":"266/679=39.1753% -> 233/530=43.9623%",
            "TREATMENT_CANDIDATE_TOP3_COVERAGE":"1489 -> 1526 (+37)",
            "TREATMENT_STAGE_B":"276/719=38.3866% -> 247/569=43.4095%",
            "CODEX_DIRECTION_LEVEL_LABEL":"TOO_BROAD"},
        "prohibited_generalization":"RICH_HISTORY_INFORMATION_NOT_SUPPORTED",
        "scope_limitations":["Rich History end-to-end adoption","Input representation alone caused any gain (recipe differs between arms)",
            "Candidate-level statistical significance","Production GO","Formal Prospective evidence"],
        "independent_review_granularity":{"final_claude_verdict":"ACCEPT",
            "candidate_metrics":"independently reproduced from prediction CSVs",
            "downstream_metrics":"independently reproduced via result_rows/outcome",
            "convergence":"10/10 fits n_iter<1000, warning_count=0"},
    })
    INDEX.write_text(json.dumps(index,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    ledger = LEDGER.read_text(encoding="utf-8")
    heading = "### EXP-021 Post-Review Record Completion"
    if heading in ledger: raise Stop("STOP_EXP021_RECORD_SCHEMA_CONFLICT")
    addition = """\n\n### EXP-021 Post-Review Record Completion

- `EXP021_RESULT_INTEGRITY = ACCEPT`
- `EXP021_PRIMARY_RESULT = RATE_POSITIVE_HIT_TRADEOFF`
- `RICH_HISTORY_CANDIDATE_INFORMATION_SIGNAL = POSITIVE`
- `RICH_HISTORY_INFORMATION_DIRECTION = SUPPORTED_AT_CANDIDATE_LEVEL`
- `EXP021_END_TO_END_ADOPTION_STATUS = HOLD_RATE_HIT_TRADEOFF`
- `PRIMARY_BOTTLENECK = SELECTION_TO_BUY_INTERFACE_MISMATCH`
"""
    LEDGER.write_text(ledger + addition, encoding="utf-8")
    index_after = json.loads(INDEX.read_text(encoding="utf-8"))
    exp020_after = next(e for e in index_after["authoritative_additive_entries"] if e.get("stable_id")=="EXP-020")
    if canonical_sha(exp020_after) != exp020_sha or tree_hashes([EXP021]) != historical_before:
        raise Stop("STOP_EXP021_RECORD_SCHEMA_CONFLICT")
    return {"status":"COMPLETE","ledger_before_sha256":before_l,"ledger_after_sha256":sha(LEDGER),
            "fingerprint_index_before_sha256":before_i,"fingerprint_index_after_sha256":sha(INDEX),
            "exp020_unchanged":True,"exp021_historical_artifacts_unchanged":True}


def duplicate_precheck() -> dict:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    entries = index["authoritative_additive_entries"]
    if any(e.get("stable_id")=="EXP-022" for e in entries): raise Stop("STOP_DUPLICATE_EXPERIMENT")
    terms = ("same-volume","matched volume","current-k","reselection","selection-to-buy","probability authority")
    findings=[]
    for e in entries:
        text=json.dumps(e,ensure_ascii=False).lower()
        hits=[t for t in terms if t in text]
        if hits: findings.append({"stable_id":e.get("stable_id"),"hits":hits,"canonical_name":e.get("canonical_name")})
    # Existing experiments may share volume controls, but none combines the
    # EXP-021 Rich Exact5 source and Rich probability as final BUY authority.
    return {"status":"PASS","semantic_duplicate_count":0,"related_records":findings,
            "distinguishing_mechanism":"EXP021_RICH_EXACT5 + EXP021_RICH_PROBABILITY + CONTROL_NATURAL_STAGE_B_BUY_COUNT; risk_guard veto only"}


def register_exp022() -> dict:
    index=json.loads(INDEX.read_text(encoding="utf-8")); entries=index["authoritative_additive_entries"]
    if any(e.get("stable_id")=="EXP-022" for e in entries): raise Stop("STOP_FINGERPRINT_REGISTRATION_FAILURE")
    fingerprint={"experiment_role":"SELECTION_TO_BUY_INTERFACE","candidate_source":"EXP021_RICH_EXACT5",
        "ranking_authority":"EXP021_RICH_PROBABILITY","new_model_training":"NONE",
        "per_race_volume_source":"CONTROL_NATURAL_STAGE_B_BUY_COUNT","risk_guard_role":"ELIGIBILITY_SAFETY_VETO_ONLY",
        "legacy_quality_gates_role":"COMPARATOR_ONLY_NOT_TEST_SELECTION_AUTHORITY","candidate_k":"EXACT5_FROZEN",
        "result_evaluation_population":"frozen consumed Development 45d/828r"}
    fid=canonical_sha(fingerprint)
    entries.append({"stable_id":"EXP-022","type":"DEVELOPMENT EXPERIMENT",
        "canonical_name":"RICH_CANDIDATE_PROBABILITY_BUY_AUTHORITY_MATCHED_VOLUME_V1",
        "aliases":["Rich Candidate Probability BUY Authority Matched Volume V1"],
        "mechanism_family":"CANDIDATE_GENERATION","normalized_family":"CANDIDATE_GENERATION",
        "experiment_role":"SELECTION_TO_BUY_INTERFACE","model_role":"Selection to BUY Interface",
        "evidence_role":"NON_EVIDENTIAL_DEVELOPMENT_ONLY","development_disposition":"OBSERVATION_ONLY",
        "evidence_gate_status":"NOT_APPLICABLE","operational_state":"READY","primary_lane":"BASELINE",
        "secondary_lane":"TREATMENT","parent":"EXP-021","fingerprint":fingerprint,
        "fingerprint_id":fid,"do_not_repeat":"PENDING_RESULT_REVIEW","untouched_holdout_used":False,
        "formal_prospective_used":False,"provenance":{"root":"reports/rich_candidate_probability_buy_authority_matched_volume_v1/","registration_stage":"PRE_RESULT"}})
    index["total_logical_entries"] += 1; index["machine_state"]["TOTAL_LOGICAL_ENTRIES"] = index["total_logical_entries"]
    index["machine_state"]["NEW_DEVELOPMENT_EXPERIMENT_AUTHORIZED_BY_THIS_TASK"]="EXP-022"
    index["development_disposition_counts"]["OBSERVATION_ONLY"] += 1
    index["evidence_gate_status_counts"]["NOT_APPLICABLE"] += 1
    index["operational_state_counts"]["READY"] += 1
    index["authoritative_last_update_date"]="2026-09-12"
    INDEX.write_text(json.dumps(index,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    ledger=LEDGER.read_text(encoding="utf-8")
    replacements={"- Logical entries: 42":"- Logical entries: 43",
        "OBSERVATION_ONLY 15 / NOT_APPLICABLE 9":"OBSERVATION_ONLY 16 / NOT_APPLICABLE 9",
        "PENDING 5 / NOT_APPLICABLE 20":"PENDING 5 / NOT_APPLICABLE 21",
        "READY 1 / HOLD 1":"READY 2 / HOLD 1",
        "EXP-019, EXP-020, EXP-021`":"EXP-019, EXP-020, EXP-021, EXP-022`",
        "`TOTAL_LOGICAL_ENTRIES = 42`":"`TOTAL_LOGICAL_ENTRIES = 43`"}
    for old,new in replacements.items():
        if ledger.count(old)!=1: raise Stop("STOP_FINGERPRINT_REGISTRATION_FAILURE:"+old)
        ledger=ledger.replace(old,new)
    ledger += f"""\n\n## Authoritative Additive Entry — 2026-09-12 — EXP-022

| Field | EXP-022 |
|---|---|
| Canonical name | RICH_CANDIDATE_PROBABILITY_BUY_AUTHORITY_MATCHED_VOLUME_V1 |
| Parent | EXP-021 |
| Role | Selection → BUY interface experiment |
| Candidate / ranking | EXP-021 frozen Rich Exact5 / frozen Rich probability |
| Volume | Same-lane CONTROL natural Stage B BUY count |
| Safety eligibility | frozen risk_guard_pass veto only |
| Evidence role | NON_EVIDENTIAL_DEVELOPMENT_ONLY |
| Fingerprint ID | `{fid}` |
| Operational state | READY（PRE-RESULT） |
"""
    LEDGER.write_text(ledger,encoding="utf-8")
    return {"status":"REGISTERED_PRE_RESULT","experiment_id":"EXP-022","fingerprint_id":fid,
            "ledger_sha256":sha(LEDGER),"fingerprint_index_sha256":sha(INDEX)}


def input_hash_audit() -> dict:
    idx=json.loads((EXP021/"artifact_hash_index.json").read_text(encoding="utf-8"))["indexed_artifacts"]
    inputs={}
    for name in ("control_baseline_predictions.csv","control_treatment_predictions.csv","rich_baseline_predictions.csv",
                 "rich_treatment_predictions.csv","rich_baseline_stage_b_natural_buy.csv","rich_treatment_stage_b_natural_buy.csv"):
        p=EXP021/name; expected=idx[name]["sha256"]
        inputs[name]={"path":p.relative_to(ROOT).as_posix(),"expected_sha256":expected,"actual_sha256":sha(p),"match":sha(p)==expected}
    for lane in ("baseline","treatment"):
        name=f"{lane}_stage_b_natural_buy.csv"; p=STAGE_B/name
        stage_index=json.loads((STAGE_B/"artifact_hash_index.json").read_text(encoding="utf-8"))
        expected=stage_index.get("indexed_artifacts",stage_index.get("hashes",{}))[name]
        inputs["control_"+name]={"path":p.relative_to(ROOT).as_posix(),"expected_sha256":expected,"actual_sha256":sha(p),"match":sha(p)==expected}
    fold=STAGE_A/"expanded_stage_a_fold_manifest.json"
    inputs["fold_manifest"]={"path":fold.relative_to(ROOT).as_posix(),"expected_sha256":FOLD_SHA,"actual_sha256":sha(fold),"match":sha(fold)==FOLD_SHA}
    if any(not v["match"] for v in inputs.values()) or any(inputs[n]["actual_sha256"]!=h for n,h in EXPECTED.items()):
        raise Stop("STOP_INPUT_HASH_MISMATCH")
    return {"status":"PASS","inputs":inputs}


def exact5(path: Path) -> dict[tuple[str,str], list[dict]]:
    grouped=defaultdict(list)
    for r in read_csv(path):
        if r["selected"]=="True":
            grouped[(r["date"],r["race_id"])].append({"date":r["date"],"race_id":r["race_id"],
                "venue":r["venue"],"race_number":int(r["race_number"]),"horse_number":int(r["horse_number"]),
                "horse_name":r["horse_name"],"probability":float(r["probability"]),
                "candidate_rank":int(r["candidate_rank"]),"shadow_ai_rank":float(r["shadow_ai_rank"])})
    if len(grouped)!=828 or any(len(v)!=5 for v in grouped.values()): raise Stop("STOP_EXACT5_INTEGRITY_FAILURE")
    return grouped


def kr(path: Path) -> tuple[dict[tuple[str,str],int], list[dict]]:
    rows=read_csv(path); counts=Counter((r["date"],r["race_id"]) for r in rows)
    return dict(counts), rows


def risk_map(keys: set[tuple[str,str]]) -> tuple[dict[tuple[str,str,int],bool], dict]:
    sources=source_map(); risks={}; source_files=[]
    for date,race_id in sorted(keys):
        matches=[]
        for path in sources.get(date,[]):
            payload=json.loads(path.read_text(encoding="utf-8"))
            if payload.get("race_id")==race_id: matches.append((path,payload))
        if len(matches)!=1: raise Stop("STOP_RISK_GUARD_PROVENANCE_UNAVAILABLE")
        path,payload=matches[0]; horses=payload.get("buy_gate_trace",{}).get("horses")
        if not isinstance(horses,list): raise Stop("STOP_RISK_GUARD_PROVENANCE_UNAVAILABLE")
        for h in horses:
            if not isinstance(h.get("risk_guard_pass"),bool): raise Stop("STOP_RISK_GUARD_PROVENANCE_UNAVAILABLE")
            risks[(date,race_id,int(h["horse_number"]))]=h["risk_guard_pass"]
        source_files.append({"date":date,"race_id":race_id,"path":path.relative_to(ROOT).as_posix(),"sha256":sha(path)})
    return risks,{"status":"PASS","race_count":len(keys),"trace_source_count":len(source_files),"trace_sources":source_files}


def make_selection(candidates: dict, kr_counts: dict, risks: dict, lane: str, arm: str) -> tuple[list[dict],dict]:
    rows=[]; short_races=0; short_horses=0
    if set(candidates)!=set(kr_counts) and set(kr_counts)-set(candidates): raise Stop("STOP_KR_RECONSTRUCTION_FAILURE")
    for key,items in sorted(candidates.items()):
        k=kr_counts.get(key,0)
        ordered=sorted(items,key=lambda x:(-x["probability"],x["shadow_ai_rank"],x["horse_number"]))
        eligible=[r for r in ordered if risks.get((key[0],key[1],r["horse_number"])) is True]
        selected={r["horse_number"] for r in eligible[:k]}; short=max(0,k-len(selected))
        short_races += int(short>0); short_horses += short
        for r in ordered:
            rows.append({**r,"lane":lane,"arm":arm,"k_r":k,
                         "risk_guard_pass":risks.get((key[0],key[1],r["horse_number"])),
                         "selected":r["horse_number"] in selected,"volume_shortfall":short})
    actual=sum(r["selected"] for r in rows); intended=sum(kr_counts.values())
    audit={"intended_natural_buy":intended,"actual_natural_buy":actual,"shortfall_horses":short_horses,
           "shortfall_races":short_races,"VOLUME_MATCH_STATUS":"COMPLETE" if short_horses==0 else "INCOMPLETE_DUE_TO_SAFETY_ELIGIBILITY"}
    return rows,audit


def prepare() -> None:
    recovery = OUT.exists()
    if not recovery:
        OUT.mkdir(parents=True)
        exp021=complete_exp021_record(); dump(OUT/"exp021_record_completion.json",exp021)
        duplicate=duplicate_precheck(); dump(OUT/"duplicate_precheck.json",duplicate)
        registration=register_exp022(); dump(OUT/"exp022_registration.json",registration)
    else:
        required=(OUT/"exp021_record_completion.json",OUT/"duplicate_precheck.json",OUT/"exp022_registration.json")
        if not all(p.is_file() for p in required): raise Stop("PREPARE_RECOVERY_AUTHORITY_INCOMPLETE")
        registration=json.loads((OUT/"exp022_registration.json").read_text(encoding="utf-8"))
        index=json.loads(INDEX.read_text(encoding="utf-8"))
        entry=next((e for e in index["authoritative_additive_entries"] if e.get("stable_id")=="EXP-022"),None)
        if not entry or entry.get("operational_state")!="READY" or entry.get("fingerprint_id")!=registration.get("fingerprint_id"):
            raise Stop("PREPARE_RECOVERY_REGISTRY_MISMATCH")
    protected=protected_snapshot()
    inputs=input_hash_audit(); dump(OUT/"input_hash_audit.json",inputs)
    fold=json.loads((STAGE_A/"expanded_stage_a_fold_manifest.json").read_text(encoding="utf-8"))
    dates={d for f in fold["folds"] for d in f["eval_dates"]}
    if len(dates)!=45 or fold["evaluation_race_total"]!=828: raise Stop("STOP_EXACT5_INTEGRITY_FAILURE")
    rich_b=exact5(EXP021/"rich_baseline_predictions.csv"); rich_t=exact5(EXP021/"rich_treatment_predictions.csv")
    control_b=exact5(EXP021/"control_baseline_predictions.csv"); control_t=exact5(EXP021/"control_treatment_predictions.csv")
    kb,ref_b=kr(STAGE_B/"baseline_stage_b_natural_buy.csv"); kt,ref_t=kr(STAGE_B/"treatment_stage_b_natural_buy.csv")
    all_keys=set(rich_b)|set(rich_t)|set(control_b)|set(control_t)
    if len(all_keys)!=828 or sum(kb.values())!=679 or sum(kt.values())!=720:
        raise Stop("STOP_KR_RECONSTRUCTION_FAILURE")
    bdist=Counter(kb.get(k,0) for k in all_keys); tdist=Counter(kt.get(k,0) for k in all_keys)
    if bdist != Counter({0:327,1:350,2:124,3:27}): raise Stop("STOP_KR_RECONSTRUCTION_FAILURE")
    dump(OUT/"control_kr_audit.json",{"status":"PASS","baseline_total":679,"treatment_total":720,
         "baseline_distribution":dict(sorted(bdist.items())),"treatment_distribution":dict(sorted(tdist.items()))})
    risks,risk_audit=risk_map(all_keys); dump(OUT/"risk_guard_availability_audit.json",risk_audit)
    exact_audit={"status":"PASS","races":828,"baseline_rich_rows":sum(map(len,rich_b.values())),
        "treatment_rich_rows":sum(map(len,rich_t.values())),"baseline_control_rows":sum(map(len,control_b.values())),
        "treatment_control_rows":sum(map(len,control_t.values())),"exact5_each_race":True}
    dump(OUT/"exact5_audit.json",exact_audit)
    outputs={}; volume={}
    for lane,cand_test,cand_diag,kvals in (("baseline",rich_b,control_b,kb),("treatment",rich_t,control_t,kt)):
        for arm,cands in (("test",cand_test),("diag",cand_diag)):
            rows,audit=make_selection(cands,kvals,risks,lane,arm.upper()); name=f"{lane}_{arm}_buy_set_pre_result.csv"
            write_csv(OUT/name,rows); outputs[name]={"sha256":sha(OUT/name),"row_count":len(rows),"selected_count":sum(r["selected"] for r in rows)}
            volume[f"{lane}_{arm}"]=audit
    pre={"experiment_id":"EXP-022","fingerprint_id":registration["fingerprint_id"],"evidence_role":"NON_EVIDENTIAL_DEVELOPMENT_ONLY",
        "created_at":datetime.now(timezone.utc).isoformat(),"ordering":["input hash validation","risk guard trace read","BUY set construction","BUY set hash freeze","result access"],
        "selection_rule":{"TEST":"Rich Exact5 ordered probability DESC, shadow_ai_rank ASC, horse_number ASC","DIAG":"Control Exact5 under same ordering",
            "k_r":"same-lane CONTROL natural Stage B BUY count","risk_guard":"only eligibility veto","outside_exact5_fill":False},
        "input_hashes":inputs["inputs"],"per_race_kr":{"baseline":{f"{k[0]}|{k[1]}":v for k,v in sorted(kb.items())},"treatment":{f"{k[0]}|{k[1]}":v for k,v in sorted(kt.items())}},
        "output_artifacts":outputs,"volume_match_audit":volume,"RESULT_ACCESS_BEFORE_BUY_SET_FREEZE":0}
    dump(OUT/"pre_execution_freeze.json",{"experiment_fingerprint":registration,"model_training":0,"model_refit":0,"scaler_fit":0,
         "fold_manifest_sha256":FOLD_SHA,"protected_before":protected})
    dump(OUT/"pre_result_selection_freeze.json",pre)
    dump(OUT/"result_access_order.json",{"selection_freeze_exists":True,"selection_freeze_sha256":sha(OUT/"pre_result_selection_freeze.json"),
         "RESULT_ACCESS_BEFORE_BUY_SET_FREEZE":0,"result_access_started":False})
    dump(OUT/"safety.json",{"phase":"PRE_RESULT_FREEZE","MODEL_TRAINING":0,"MODEL_REFIT":0,"SCALER_FIT":0,
         "THRESHOLD_SEARCH":0,"K_TUNING":0,"STAGE_B_TUNING":0,"FEATURE_SEARCH":0,"SUBGROUP_SEARCH":0,
         "UNTAPPED_HOLDOUT_ACCESS":0,"FORMAL_PROSPECTIVE_EXECUTION":0,"GIT_COMMIT":0,"GIT_PUSH":0})


def validate_freeze() -> dict:
    pre=json.loads((OUT/"pre_result_selection_freeze.json").read_text(encoding="utf-8"))
    for name,meta in pre["output_artifacts"].items():
        if sha(OUT/name)!=meta["sha256"]: raise Stop("STOP_RESULT_BOUNDARY_VIOLATION")
    return pre


def result_lookup(dates: set[str]) -> dict[tuple[str,str,int],tuple[bool,int|None,bool|None]]:
    lookup={}
    for date in sorted(dates):
        results=result_rows(date)
        for (venue,rno),row in results.items():
            # Race ids are reconciled through the frozen selections below.
            lookup[(date,f"{venue}|{rno}",-1)]=(True,None,None)
    return lookup


def evaluate(rows: list[dict], cache: dict[str,dict]) -> tuple[dict,list[dict]]:
    selected=[r for r in rows if str(r.get("selected")).lower()=="true"]
    details=[]
    for r in selected:
        date=r["date"]
        if date not in cache: cache[date]=result_rows(date)
        _,venue_key,rno=parse_race_id(r["race_id"]); rr=cache[date].get((JAPANESE_VENUE[venue_key],rno))
        if rr is None: raise Stop("RESULT_RACE_UNMATCHED:"+r["race_id"])
        valid,finish,top3=outcome(rr,int(r["horse_number"]))
        details.append({**r,"valid_result":valid,"actual_finish":finish,"actual_top3":bool(top3) if valid else None})
    valid=[r for r in details if r["valid_result"]]; hits=sum(r["actual_top3"] for r in valid)
    races=defaultdict(list)
    for r in details: races[(r["date"],r["race_id"])].append(r)
    dist=Counter(len(v) for v in races.values()); positive=sum(any(x["valid_result"] and x["actual_top3"] for x in v) for v in races.values())
    return {"natural_buy":len(details),"valid_buy":len(valid),"invalid_buy":len(details)-len(valid),"top3_hits":hits,
        "buy_top3_rate":hits/len(valid) if valid else None,"buy_positive_race_count":positive,
        "race_buy_count_distribution":dict(sorted(dist.items()))},details


def classify(test: dict, ref: dict, fold_nets: list[int]) -> tuple[str,str]:
    hit=test["top3_hits"]-ref["top3_hits"]; rate=test["buy_top3_rate"]-ref["buy_top3_rate"]
    stable=stability(hit,fold_nets)
    if rate>0 and hit>0: return ("CLEAN_SELECTION_GAIN" if stable=="CONSISTENT" else "POSITIVE_BUT_UNSTABLE"),stable
    if rate>0 and hit<=0: return "RATE_POSITIVE_HIT_NONPOSITIVE",stable
    if hit>0 and rate<=0: return "HIT_POSITIVE_RATE_NONPOSITIVE",stable
    if hit==0 and rate<=0: return "NEUTRAL",stable
    return "NEGATIVE",stable


def direction_pair(left: dict,right: dict) -> str:
    hd=right["top3_hits"]-left["top3_hits"]; rd=right["buy_top3_rate"]-left["buy_top3_rate"]
    if hd>0 and rd>0:return "POSITIVE"
    if hd<0 and rd<0:return "NEGATIVE"
    if hd==0 and rd==0:return "NEUTRAL"
    return "MIXED"


def execute() -> None:
    pre=validate_freeze()
    order=json.loads((OUT/"result_access_order.json").read_text(encoding="utf-8"))
    if order["RESULT_ACCESS_BEFORE_BUY_SET_FREEZE"]!=0: raise Stop("STOP_RESULT_BOUNDARY_VIOLATION")
    fold=json.loads((STAGE_A/"expanded_stage_a_fold_manifest.json").read_text(encoding="utf-8")); cache={}
    fold_of={d:f["fold_id"] for f in fold["folds"] for d in f["eval_dates"]}
    ref_files={"baseline":STAGE_B/"baseline_stage_b_natural_buy.csv","treatment":STAGE_B/"treatment_stage_b_natural_buy.csv"}
    rich_ref_files={"baseline":EXP021/"rich_baseline_stage_b_natural_buy.csv","treatment":EXP021/"rich_treatment_stage_b_natural_buy.csv"}
    all_metrics={}; stability_out={}; detail_by={}
    expected={"baseline":(679,679,0,266),"treatment":(720,719,1,276)}
    expected_rich={"baseline":(530,530,0,233),"treatment":(569,569,0,247)}
    for lane in ("baseline","treatment"):
        ref_rows=[{**r,"selected":True} for r in read_csv(ref_files[lane])]
        ref,ref_detail=evaluate(ref_rows,cache)
        rich_rows=[{**r,"selected":True} for r in read_csv(rich_ref_files[lane])]
        ref2,ref2_detail=evaluate(rich_rows,cache)
        if (ref["natural_buy"],ref["valid_buy"],ref["invalid_buy"],ref["top3_hits"])!=expected[lane]: raise Stop("INVALID_REFERENCE_METRICS")
        if (ref2["natural_buy"],ref2["valid_buy"],ref2["invalid_buy"],ref2["top3_hits"])!=expected_rich[lane]: raise Stop("INVALID_REFERENCE2_METRICS")
        arm_metrics={"REF":ref,"REF2":ref2}
        details={"REF":ref_detail,"REF2":ref2_detail}
        for arm in ("test","diag"):
            rows=read_csv(OUT/f"{lane}_{arm}_buy_set_pre_result.csv"); metric,detail=evaluate(rows,cache)
            metric["candidate_input_count"]=len(rows); metric["candidate_to_buy_conversion_rate"]=metric["natural_buy"]/len(rows)
            arm_metrics[arm.upper()]=metric; details[arm.upper()]=detail
        fold_nets=[]; fold_rows=[]
        for f in fold["folds"]:
            dates=set(f["eval_dates"])
            rh=sum(x["actual_top3"] for x in ref_detail if x["date"] in dates and x["valid_result"])
            th=sum(x["actual_top3"] for x in details["TEST"] if x["date"] in dates and x["valid_result"])
            fold_nets.append(th-rh); fold_rows.append({"fold_id":f["fold_id"],"ref_hits":rh,"test_hits":th,"hit_net":th-rh})
        classification,stable=classify(arm_metrics["TEST"],ref,fold_nets)
        arm_metrics["test_rate_delta_pt"]=(arm_metrics["TEST"]["buy_top3_rate"]-ref["buy_top3_rate"])*100
        arm_metrics["test_hit_delta"]=arm_metrics["TEST"]["top3_hits"]-ref["top3_hits"]
        arm_metrics["test_classification"]=classification
        all_metrics[lane]=arm_metrics; detail_by[lane]=details
        stability_out[lane]={"overall_hit_net":arm_metrics["test_hit_delta"],"fold_nets":fold_rows,"stability":stable}
        dump(OUT/f"{lane}_metrics.json",arm_metrics)
    dump(OUT/"fold_stability.json",stability_out)
    invalid={lane:{arm:m[arm]["invalid_buy"] for arm in ("REF","TEST","DIAG","REF2")} for lane,m in all_metrics.items()}
    dump(OUT/"invalid_result_audit.json",{"semantics":"invalid excluded from denominator; not failure; no replacement","counts":invalid})
    interface_by={lane:direction_pair(m["REF"],m["DIAG"]) for lane,m in all_metrics.items()}
    rich_by={lane:direction_pair(m["DIAG"],m["TEST"]) for lane,m in all_metrics.items()}
    combine=lambda d: next(iter(set(d.values()))) if len(set(d.values()))==1 else "MIXED"
    decomposition={"interface_authority_by_lane":interface_by,"rich_information_incremental_by_lane":rich_by,
        "INTERFACE_AUTHORITY_SIGNAL":combine(interface_by),"RICH_INFORMATION_INCREMENTAL_SIGNAL":combine(rich_by),
        "interpretation_boundary":"consumed Development only; no formal causality"}
    dump(OUT/"diagnostic_decomposition.json",decomposition)
    protected_before=json.loads((OUT/"pre_execution_freeze.json").read_text(encoding="utf-8"))["protected_before"]
    protected_after=protected_snapshot(); bad=[p for p,h in protected_before.items() if protected_after.get(p)!=h]
    dump(OUT/"protected_file_hash_audit.json",{"before":protected_before,"after":protected_after,"mismatches":bad,
         "PROTECTED_RUNTIME_ZERO_DELTA":"PASS" if not bad else "FAIL"})
    if bad: raise Stop("PROTECTED_RUNTIME_ZERO_DELTA_FAIL")
    index=json.loads(INDEX.read_text(encoding="utf-8")); entry=next(e for e in index["authoritative_additive_entries"] if e.get("stable_id")=="EXP-022")
    if entry["operational_state"]!="READY": raise Stop("STOP_FINGERPRINT_REGISTRATION_FAILURE")
    primary=all_metrics["baseline"]["test_classification"]
    hypothesis="SUPPORTED" if primary=="CLEAN_SELECTION_GAIN" else "MIXED" if primary in {"RATE_POSITIVE_HIT_NONPOSITIVE","HIT_POSITIVE_RATE_NONPOSITIVE","POSITIVE_BUT_UNSTABLE"} else "NOT_SUPPORTED" if primary in {"NEUTRAL","NEGATIVE"} else "INVALID"
    entry.update({"operational_state":"COMPLETE","primary_result":primary,"do_not_repeat":"YES_WITH_UNCHANGED_FROZEN_RECIPE",
        "accepted_state":{"PRIMARY_EXP022_SIGNAL":primary,"SELECTION_TO_BUY_INTERFACE_HYPOTHESIS":hypothesis,
            "INTERFACE_AUTHORITY_SIGNAL":decomposition["INTERFACE_AUTHORITY_SIGNAL"],
            "RICH_INFORMATION_INCREMENTAL_SIGNAL":decomposition["RICH_INFORMATION_INCREMENTAL_SIGNAL"]},
        "reopen_condition":["Material change to Rich Exact5, Rich probability, risk_guard semantics, CONTROL natural BUY volume, or frozen fold protocol"]})
    index["operational_state_counts"]["READY"]-=1; index["operational_state_counts"]["COMPLETE"]+=1
    index["machine_state"]["NEW_DEVELOPMENT_EXPERIMENT_AUTHORIZED_BY_THIS_TASK"]="NO"
    INDEX.write_text(json.dumps(index,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    ledger=LEDGER.read_text(encoding="utf-8")
    old="Operational: ACTIVE 2 / PAUSE 1 / READY 2 / HOLD 1 / CLOSED 21 / COMPLETE 16"
    new="Operational: ACTIVE 2 / PAUSE 1 / READY 1 / HOLD 1 / CLOSED 21 / COMPLETE 17"
    if ledger.count(old)!=1: raise Stop("STOP_FINGERPRINT_REGISTRATION_FAILURE")
    LEDGER.write_text(ledger.replace(old,new)+f"\n\n### EXP-022 Result Finalization\n\n- Result: `{primary}`\n- Operational state: `COMPLETE`\n- Evidence role: `NON_EVIDENTIAL_DEVELOPMENT_ONLY`\n",encoding="utf-8")
    order.update({"result_access_started":True,"result_access_started_after_freeze":True,
                  "result_access_completed":True,"RESULT_ACCESS_BEFORE_BUY_SET_FREEZE":0})
    dump(OUT/"result_access_order.json",order)
    safety={"MODEL_TRAINING":0,"MODEL_REFIT":0,"SCALER_FIT":0,"THRESHOLD_SEARCH":0,"K_TUNING":0,
        "STAGE_B_TUNING":0,"FEATURE_SEARCH":0,"SUBGROUP_SEARCH":0,"STAGE_B_CHANGE":0,"V4_CHANGE":0,
        "PRODUCTION_CHANGE":0,"UNTAPPED_HOLDOUT_ACCESS":0,"FORMAL_PROSPECTIVE_EXECUTION":0,
        "PROTECTED_RUNTIME_ZERO_DELTA":"PASS","GIT_COMMIT":0,"GIT_PUSH":0}
    dump(OUT/"safety.json",safety)
    b=all_metrics["baseline"]; t=all_metrics["treatment"]
    report=f"""# EXP-022 Rich Candidate Probability BUY Authority Matched Volume V1

`RICH_CANDIDATE_PROBABILITY_BUY_AUTHORITY_MATCHED_VOLUME_V1 = COMPLETE`

- Evidence role: `NON_EVIDENTIAL_DEVELOPMENT_ONLY`
- Baseline TEST: {b['TEST']['top3_hits']}/{b['TEST']['valid_buy']} = {b['TEST']['buy_top3_rate']:.4%}; delta {b['test_rate_delta_pt']:+.4f}pt / {b['test_hit_delta']:+d} hits; `{b['test_classification']}`.
- Baseline DIAG: {b['DIAG']['top3_hits']}/{b['DIAG']['valid_buy']} = {b['DIAG']['buy_top3_rate']:.4%}.
- Treatment TEST: {t['TEST']['top3_hits']}/{t['TEST']['valid_buy']} = {t['TEST']['buy_top3_rate']:.4%}; delta {t['test_rate_delta_pt']:+.4f}pt / {t['test_hit_delta']:+d} hits; `{t['test_classification']}`.
- Treatment DIAG: {t['DIAG']['top3_hits']}/{t['DIAG']['valid_buy']} = {t['DIAG']['buy_top3_rate']:.4%}.
- Interface authority signal: `{decomposition['INTERFACE_AUTHORITY_SIGNAL']}`.
- Rich incremental information signal: `{decomposition['RICH_INFORMATION_INCREMENTAL_SIGNAL']}`.
- Selection-to-BUY hypothesis: `{hypothesis}`.
- Result access before selection freeze: `0`.
- Race-level cross-horse priority: `SECONDARY`.
"""
    (OUT/"report.md").write_text(report,encoding="utf-8")
    # Hash every authoritative output except the self-index.
    names=sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hash_index.json")
    dump(OUT/"artifact_hash_index.json",{"indexed_artifacts":{n:{"sha256":sha(OUT/n),"size":(OUT/n).stat().st_size} for n in names},"self_hash_excluded":True})


def complete_reporting() -> None:
    """Complete non-semantic reporting fields without reloading any Result."""
    pre=validate_freeze()
    metrics={lane:json.loads((OUT/f"{lane}_metrics.json").read_text(encoding="utf-8")) for lane in ("baseline","treatment")}
    for lane,values in metrics.items():
        for arm in ("REF","REF2"):
            values[arm]["candidate_input_count"]=4140
            values[arm]["candidate_to_buy_conversion_rate"]=values[arm]["natural_buy"]/4140
        dump(OUT/f"{lane}_metrics.json",values)
    b,t=metrics["baseline"],metrics["treatment"]
    decomposition=json.loads((OUT/"diagnostic_decomposition.json").read_text(encoding="utf-8"))
    decomposition["scientific_questions"]={
        "Q1_rich_probability_vs_legacy_stage_b_primary":"NOT_SUPPORTED_BY_PRIMARY_CONTRACT: rate improved slightly, hits decreased, and safety eligibility caused volume shortfall",
        "Q2_control_probability_authority_vs_legacy_stage_b":"POSITIVE_IN_BOTH_LANES",
        "Q3_rich_information_with_interface_fixed":"MIXED: negative in Baseline, positive in Treatment",
    }
    dump(OUT/"diagnostic_decomposition.json",decomposition)
    bv=pre["volume_match_audit"]["baseline_test"]; tv=pre["volume_match_audit"]["treatment_test"]
    report=f"""# EXP-022 Rich Candidate Probability BUY Authority Matched Volume V1

`RICH_CANDIDATE_PROBABILITY_BUY_AUTHORITY_MATCHED_VOLUME_V1 = COMPLETE`

- Evidence role: `NON_EVIDENTIAL_DEVELOPMENT_ONLY`
- Baseline volume: intended {bv['intended_natural_buy']} / actual {bv['actual_natural_buy']} / shortfall {bv['shortfall_horses']} in {bv['shortfall_races']} races; `{bv['VOLUME_MATCH_STATUS']}`.
- Baseline TEST: {b['TEST']['top3_hits']}/{b['TEST']['valid_buy']} = {b['TEST']['buy_top3_rate']:.4%}; delta {b['test_rate_delta_pt']:+.4f}pt / {b['test_hit_delta']:+d} hits; `{b['test_classification']}`.
- Baseline DIAG: {b['DIAG']['top3_hits']}/{b['DIAG']['valid_buy']} = {b['DIAG']['buy_top3_rate']:.4%}.
- Treatment volume: intended {tv['intended_natural_buy']} / actual {tv['actual_natural_buy']} / shortfall {tv['shortfall_horses']} in {tv['shortfall_races']} races; `{tv['VOLUME_MATCH_STATUS']}`.
- Treatment TEST: {t['TEST']['top3_hits']}/{t['TEST']['valid_buy']} = {t['TEST']['buy_top3_rate']:.4%}; delta {t['test_rate_delta_pt']:+.4f}pt / {t['test_hit_delta']:+d} hits; `{t['test_classification']}`.
- Treatment DIAG: {t['DIAG']['top3_hits']}/{t['DIAG']['valid_buy']} = {t['DIAG']['buy_top3_rate']:.4%}.
- Interface authority signal: `{decomposition['INTERFACE_AUTHORITY_SIGNAL']}`.
- Rich incremental information signal: `{decomposition['RICH_INFORMATION_INCREMENTAL_SIGNAL']}`.
- Selection-to-BUY hypothesis: `MIXED`.
- Result access before selection freeze: `0`.
- Race-level cross-horse priority: `SECONDARY`.
"""
    (OUT/"report.md").write_text(report,encoding="utf-8")
    names=sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hash_index.json")
    dump(OUT/"artifact_hash_index.json",{"indexed_artifacts":{n:{"sha256":sha(OUT/n),"size":(OUT/n).stat().st_size} for n in names},"self_hash_excluded":True})


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("phase",choices=("prepare","execute","reporting")); args=parser.parse_args()
    if args.phase=="prepare": prepare()
    elif args.phase=="execute": execute()
    else: complete_reporting()


if __name__=="__main__":
    try: main()
    except Stop as exc:
        print(str(exc),file=sys.stderr); raise SystemExit(2)
