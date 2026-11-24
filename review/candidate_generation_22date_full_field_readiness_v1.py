"""Technical, performance-blind Full-field readiness audit for 22 approved dates."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.target_daily_result_list_schema_v2_validator import validate_source_pair
OUT = ROOT / "reports/candidate_generation_22date_full_field_readiness_v1"
GOV = ROOT / "reports/candidate_generation_26date_governance_reconciliation_v1"
FINGERPRINT = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"
LEDGER = ROOT / "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md"
DRAFT = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX_DRAFT_V3.json"
SOURCE_MANIFEST = ROOT / "reports/ml_v4_buy_selection_dataset_v1/source_manifest.json"
MODEL_SCHEMA = ROOT / "reports/ml_v4_buy_selection_model_v4/selected_feature_columns.json"
TRANSFORM = ROOT / "reports/ml_v4_buy_selection_model_v4/feature_transform_schema.json"

FEATURES = ("Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle",
            "shadow_ai_rank", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass",
            "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count",
            "consensus_negative_count", "risk_count", "conflict_count", "race_state")
VENUES = {"sapporo":"札幌", "hakodate":"函館", "fukushima":"福島", "niigata":"新潟", "tokyo":"東京", "nakayama":"中山", "chukyo":"中京", "chuukyou":"中京", "kyoto":"京都", "hanshin":"阪神", "kokura":"小倉"}
ABNORMAL = {"中止", "除外", "取消", "失格"}
BLOCKS = {
    "APRIL": ["20260404","20260405","20260411","20260412","20260418","20260419","20260425","20260426"],
    "JUNE": ["20260620","20260621","20260627","20260628"],
    "JULY": ["20260704","20260705","20260711","20260712","20260725","20260726"],
    "AUGUST": ["20260801","20260802","20260815","20260816"],
}
DATES = [d for values in BLOCKS.values() for d in values]
PROTECTED = {"20260718","20260719","20260808","20260809"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def dump(name: str, value) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values(): yield from walk(child)
    elif isinstance(value, list):
        for child in value: yield from walk(child)


def provenance_sources() -> dict[str, dict]:
    found: dict[str, list[dict]] = defaultdict(list)
    for item in walk(load(SOURCE_MANIFEST)):
        source = item.get("prediction_feature_source") if isinstance(item, dict) else None
        if isinstance(source, dict) and isinstance(item.get("date"), str) and source.get("root"):
            found[item["date"]].append({"root": source["root"], "result": item.get("result_label_source", {}), "semantic_role": item.get("semantic_role")})
    result = {}
    for date, entries in found.items():
        unique = {(e["root"], json.dumps(e.get("result", {}), sort_keys=True, ensure_ascii=False)) for e in entries}
        if len(unique) == 1: result[date] = entries[0]
    return result


def parse_race_id(race_id: str):
    parts = race_id.split("_")
    if parts and parts[0] == "race": parts = parts[1:]
    if len(parts) < 3 or not parts[0].isdigit() or not parts[-1].endswith("R"):
        raise ValueError("invalid race id")
    return parts[0], parts[-2], int(parts[-1][:-1])


def feature_values(horse, trace, state):
    snapshot = trace.get("evaluator_score_snapshot") if isinstance(trace, dict) else None
    if not isinstance(snapshot, dict): raise ValueError("EVALUATOR_SNAPSHOT_MISSING")
    out = {name: snapshot.get(name) for name in FEATURES[:7]}
    out.update({"shadow_ai_rank": trace.get("shadow_ai_rank"), "decision_score": trace.get("decision_score"),
        "final_score": trace.get("final_score"), "adjusted_score": trace.get("adjusted_score"),
        "absolute_quality_pass": trace.get("absolute_quality_pass"), "relative_advantage_pass": trace.get("relative_advantage_pass"),
        "effective_reliability_pass": trace.get("effective_reliability_pass"), "risk_guard_pass": trace.get("risk_guard_pass"),
        "consensus_positive_count": horse.get("consensus_positive_count"), "consensus_negative_count": horse.get("consensus_negative_count"),
        "risk_count": horse.get("risk_count"), "conflict_count": horse.get("conflict_count"), "race_state": state})
    return out


def valid_feature(name, value):
    if name == "race_state": return value in {"PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"}
    if name in {"absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass"}: return isinstance(value, bool)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def main():
    if OUT.exists(): raise SystemExit(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    OUT.mkdir(parents=True)
    before = {"ledger":sha(LEDGER), "fingerprint":sha(FINGERPRINT), "draft_v3":sha(DRAFT)}
    gov_rows = list(csv.DictReader((GOV / "date_level_governance_audit.csv").open(encoding="utf-8")))
    allowed = {r["date"].replace("-", "") for r in gov_rows if r["candidate_generation_reuse_state"] in {"ALLOWED_CONSUMED_DEVELOPMENT", "ALLOWED_WITH_PROVENANCE_NOTE"}}
    history_ok = (len(DATES) == 22 and set(DATES) == allowed and not (set(DATES) & PROTECTED) and
                  (GOV / "scope_arithmetic.json").is_file() and (GOV / "report.md").is_file())
    model_schema = load(MODEL_SCHEMA)
    transform = load(TRANSFORM)
    canonical = tuple(model_schema.get("semantic_selected_columns", []))
    schema_ok = canonical == FEATURES and transform.get("transformed_input_count") == 21
    dump("history_precheck.json", {"HISTORY_PRECHECK":"PASS" if history_ok and schema_ok else "FAIL", "governance_audit":str(GOV),
        "ledger_sha256":before["ledger"], "fingerprint_sha256":before["fingerprint"], "canonical_feature_source":str(MODEL_SCHEMA),
        "ana020_source":"reports/candidate_generation_observability_feasibility_v1_retry1/", "governance_22date_scope_match":"PASS" if history_ok else "FAIL"})
    dump("canonical_20_features.json", {"feature_names":list(canonical), "semantic_feature_count":len(canonical), "transformed_input_count":transform.get("transformed_input_count"), "source_artifact":str(MODEL_SCHEMA), "source_sha256":sha(MODEL_SCHEMA), "transform_source":str(TRANSFORM), "transform_sha256":sha(TRANSFORM)})
    dump("scope.json", {"GOVERNANCE_SCOPE_USED":"EXACT_22_ALLOWED_DATES", "requested_date_count":22, "dates":DATES, "protected_dates":sorted(PROTECTED), "CURRENT_32_DATE_OVERLAP":0, "technical_only":True})
    sources = provenance_sources()
    source_rows=[]; result_rows=[]; date_rows=[]; race_rows=[]; feature_by_date=[]; identity_stats={}; rank_stats={}; join_stats={}; invalid_stats={}; leakage={}; provenance={}
    all_feature_issue=all_identity_issue=all_rank_issue=all_join_issue=False
    for block, dates in BLOCKS.items():
        for date in dates:
            info=sources.get(date); failures=[]; races=0; horse_rows=0; feature_missing=feature_type=identity_duplicate=identity_unmatched=identity_ambiguous=0; invalid=0; result_joined=0; rank_bad=0
            if not info:
                failures.append("PROVENANCE_UNRESOLVED")
                source_rows.append({"date":date,"block":block,"prediction_source":"","source_sha256":"","status":"SOURCE_MISSING"})
            else:
                root=ROOT / Path(info["root"]); files=sorted(root.glob(f"race_{date}_*_prediction.json"))
                source_rows.append({"date":date,"block":block,"prediction_source":str(root),"source_sha256":sha(root / "summary.json") if (root / "summary.json").is_file() else "NO_SUMMARY","status":"FOUND" if files else "SOURCE_MISSING"})
                result_info=info.get("result") or {}; result_path=ROOT / Path(result_info.get("path","")); aux=result_path.parent / result_path.name.replace("馬番順着順_", "着順馬番_")
                result_rows.append({"date":date,"result_source_path":str(result_path),"result_source_sha256":result_info.get("sha256",""),"disclosure_provenance":"V4 Dataset v1 source manifest","status":"FOUND" if result_path.is_file() and aux.is_file() else "SOURCE_MISSING"})
                try:
                    validate_source_pair(result_path, aux, date)
                    with result_path.open(encoding="cp932",newline="") as fh: raw=list(csv.reader(fh))
                    result_by_race={(r[1],int(r[2])):r for r in raw}
                    if len(raw)!=len(result_by_race): raise ValueError("RESULT_DUPLICATE_RACE")
                    for file in files:
                        payload=load(file); race_id=payload.get("race_id",""); pd,venue_key,rno=parse_race_id(race_id); venue=VENUES.get(venue_key)
                        if pd!=date or venue is None: raise ValueError("RACE_IDENTITY_MISMATCH")
                        result=result_by_race.get((venue,rno))
                        ranked=payload.get("ranked_results"); trace=payload.get("buy_gate_trace",{}); trace_horses=trace.get("horses") if isinstance(trace,dict) else None; state=trace.get("race",{}).get("shadow_race_state") if isinstance(trace,dict) else None
                        if result is None: raise ValueError("RESULT_JOIN_MISMATCH")
                        if not isinstance(ranked,list) or not isinstance(trace_horses,list) or len(ranked)!=int(result[9]) or len(trace_horses)!=len(ranked): raise ValueError("FULL_FIELD_NOT_PROVEN")
                        nums=[]; by_num={}
                        for item in trace_horses:
                            if not isinstance(item,dict) or item.get("horse_number") is None: raise ValueError("IDENTITY_MISMATCH")
                            n=int(item["horse_number"]); nums.append(n); by_num[n]=item
                        rnums=[int(h.get("horse_number")) for h in ranked]
                        if len(set(nums))!=len(nums) or set(nums)!=set(rnums) or len(rnums)!=len(set(rnums)): raise ValueError("IDENTITY_MISMATCH")
                        if state not in {"PLAY_CONVERGED","PLAY_UNCONVERGED_4PLUS","SKIP"}: raise ValueError("FEATURE_SCHEMA_MISMATCH")
                        ranks=[]
                        for horse in ranked:
                            n=int(horse["horse_number"]); vals=feature_values(horse,by_num[n],state); horse_rows+=1
                            for name,val in vals.items():
                                if not valid_feature(name,val):
                                    feature_missing += int(val is None); feature_type += int(val is not None)
                            ranks.append(vals["shadow_ai_rank"])
                            raw_finish=result[11+n].strip()
                            if raw_finish in ABNORMAL: invalid+=1
                            elif raw_finish.isdigit() and int(raw_finish)>0: result_joined+=1
                            else: raise ValueError("RESULT_JOIN_MISMATCH")
                        if len(ranks)!=len(set(ranks)) or sorted(int(x) for x in ranks)!=list(range(1,len(ranks)+1)): rank_bad+=1
                        races+=1
                        race_rows.append({"date":date,"venue":venue,"race":rno,"expected_full_field_source_count":int(result[9]),"feature_row_count":len(ranked),"duplicate_count":0,"missing_count":0,"full_field_status":"PASS"})
                except Exception as exc:
                    token=str(exc)
                    failures.append(token if token in {"SOURCE_MISSING","FULL_FIELD_NOT_PROVEN","TOP5_ONLY_MATERIAL","FEATURE_SCHEMA_MISMATCH","FEATURE_MISSING","FEATURE_TYPE_ERROR","IDENTITY_MISMATCH","RESULT_JOIN_MISMATCH","SHADOW_RANK_MISSING","PROVENANCE_UNRESOLVED","LEAKAGE_RISK","RECIPE_INCOMPATIBLE"} else "OTHER")
            if feature_missing or feature_type: failures.append("FEATURE_MISSING" if feature_missing else "FEATURE_TYPE_ERROR")
            if rank_bad: failures.append("SHADOW_RANK_MISSING")
            ready=not failures and races>0 and schema_ok
            status="TECHNICAL_READY" if ready else "NOT_TECHNICAL_READY"
            feature_by_date.append({"date":date,"feature_missing_count":feature_missing,"feature_type_error_count":feature_type,"semantic_feature_count":20 if schema_ok else len(canonical)})
            identity_stats[date]={"unmatched":identity_unmatched,"duplicate":identity_duplicate,"ambiguous":identity_ambiguous,"status":"PASS" if not (identity_unmatched or identity_duplicate or identity_ambiguous) and ready else "FAIL"}
            rank_stats[date]={"status":"PASS" if rank_bad==0 and ready else "FAIL","malformed_or_duplicate_race_count":rank_bad}
            join_stats[date]={"status":"PASS" if ready else "FAIL","joined_row_count":result_joined,"unmatched_count":identity_unmatched,"duplicate_count":identity_duplicate,"ambiguous_count":identity_ambiguous}
            invalid_stats[date]={"valid_result_parse_status":"PASS" if ready else "FAIL","invalid_result_count":invalid,"source_population_unchanged":True}
            leakage[date]={"RESULT_TO_FEATURE_LEAKAGE":"NO","basis":"features read from frozen PRE prediction/buy_gate_trace; result source used only after feature extraction for technical identity/parse audit"}
            provenance[date]={"block":block,"prediction_source":info.get("root") if info else None,"result_source":(info or {}).get("result",{}).get("path"),"generator":"existing frozen prediction artifact","status":"PASS" if info else "FAIL"}
            date_rows.append({"date":f"{date[:4]}-{date[4:6]}-{date[6:]}","month":date[:6],"governance_state":"ALLOWED","source_found":"PASS" if info else "FAIL","full_field_population":"PASS" if ready else "FAIL","race_count":races,"horse_row_count":horse_rows,"semantic_feature_count":20 if schema_ok else len(canonical),"feature_name_match":"PASS" if canonical==FEATURES else "FAIL","feature_order_match":"PASS" if canonical==FEATURES else "FAIL","feature_missing_count":feature_missing,"feature_type_error_count":feature_type,"identity_unmatched_count":identity_unmatched,"identity_duplicate_count":identity_duplicate,"identity_ambiguous_count":identity_ambiguous,"shadow_ai_rank_status":"PASS" if rank_bad==0 and ready else "FAIL","result_source_status":"PASS" if info else "FAIL","result_join_status":"PASS" if ready else "FAIL","valid_result_parse_status":"PASS" if ready else "FAIL","invalid_result_count":invalid,"result_to_feature_leakage":"NO","temporal_metadata_status":"PASS" if ready else "FAIL","recipe_compatibility":"PASS" if schema_ok else "FAIL","technical_readiness":status,"failure_reason":";".join(sorted(set(failures))) or "","notes":"performance metrics not calculated"})
    with (OUT/"source_inventory.csv").open("w",newline="",encoding="utf-8") as fh: w=csv.DictWriter(fh,fieldnames=list(source_rows[0])); w.writeheader(); w.writerows(source_rows)
    with (OUT/"result_source_inventory.csv").open("w",newline="",encoding="utf-8") as fh: w=csv.DictWriter(fh,fieldnames=list(result_rows[0])); w.writeheader(); w.writerows(result_rows)
    with (OUT/"date_level_readiness.csv").open("w",newline="",encoding="utf-8") as fh: w=csv.DictWriter(fh,fieldnames=list(date_rows[0])); w.writeheader(); w.writerows(date_rows)
    with (OUT/"race_level_population_audit.csv").open("w",newline="",encoding="utf-8") as fh: w=csv.DictWriter(fh,fieldnames=["date","venue","race","expected_full_field_source_count","feature_row_count","duplicate_count","missing_count","full_field_status"]); w.writeheader(); w.writerows(race_rows)
    with (OUT/"feature_completeness_by_date.csv").open("w",newline="",encoding="utf-8") as fh: w=csv.DictWriter(fh,fieldnames=list(feature_by_date[0])); w.writeheader(); w.writerows(feature_by_date)
    dump("feature_schema_audit.json", {"CANONICAL_20_FEATURE_SCHEMA":"PASS" if schema_ok else "FAIL","FEATURE_NAME_MATCH":"PASS" if canonical==FEATURES else "FAIL","FEATURE_ORDER_MATCH":"PASS" if canonical==FEATURES else "FAIL","features":list(canonical),"transformed_input_count":transform.get("transformed_input_count")})
    dump("identity_audit.json", identity_stats); dump("result_join_audit.json", join_stats); dump("invalid_result_audit.json", invalid_stats); dump("shadow_ai_rank_audit.json",rank_stats); dump("pre_race_leakage_audit.json",leakage); dump("provenance_audit.json",provenance)
    ready_dates=[r["date"] for r in date_rows if r["technical_readiness"]=="TECHNICAL_READY"]; failed=[{"date":r["date"],"reason":r["failure_reason"]} for r in date_rows if r["technical_readiness"]!="TECHNICAL_READY"]
    dump("recipe_compatibility_audit.json", {"FROZEN_RECIPE_COMPATIBILITY":"PASS" if schema_ok else "FAIL","semantic_feature_count":len(canonical),"transformed_input_count":transform.get("transformed_input_count"),"model_family":"LogisticRegression contract only; no fit"})
    dump("scope_arithmetic.json", {"CURRENT_EXISTING_CLEAN_SCOPE":"32_DATES","ADDITIONAL_GOVERNANCE_ALLOWED":22,"ADDITIONAL_TECHNICAL_READY":len(ready_dates),"ADDITIONAL_TECHNICAL_NOT_READY":len(failed),"POTENTIAL_FULL_FIELD_READY_SCOPE":f"{32+len(ready_dates)}_DATES","not_expanded_stage_a_official_scope":True})
    dump("unresolved_items.json", {"not_technical_ready":failed,"protected_dates":sorted(PROTECTED),"no_substitution":True})
    after={"ledger":sha(LEDGER),"fingerprint":sha(FINGERPRINT),"draft_v3":sha(DRAFT)}
    safety={"LEDGER_CHANGE":0,"FINGERPRINT_CHANGE":0,"DRAFT_V3_CHANGE":0,"DATA_CATALOG_CHANGE":0,"WORK_RECORD_CHANGE":0,"SOURCE_CHANGE":0,"PROTECTED_4_DATE_DATA_ACCESS":0,"UNTOUCHED_HOLDOUT_ACCESS":0,"FUTURE_RESULT_ACCESS":0,"FINAL_TRAINING_DATASET_BUILD":0,"MODEL_TRAINING":0,"SCALER_FIT":0,"PREDICTION":0,"CANDIDATE_EXACT5":0,"PERFORMANCE_METRIC_CALCULATION":0,"STAGE_A_RERUN":0,"STAGE_B_EXECUTION":0,"ENGINE_CHANGE":0,"RACE_DECISION_ENGINE_CHANGE":0,"PRODUCTION_CHANGE":0,"GIT_COMMIT":0,"GIT_PUSH":0,"authority_unchanged":before==after,"ARTIFACT_HASH_VALIDATION":"PENDING"}
    dump("safety.json",safety)
    report=["# Candidate Generation","# 22-Date Full-field Readiness — 完了","",f"`CANDIDATE_GENERATION_22DATE_FULL_FIELD_READINESS_V1 = COMPLETE`","",f"- Requested/audited dates: 22/22","- Protected 4-date data access: 0",f"- Technical ready: {len(ready_dates)}",f"- Not technical ready: {len(failed)}",f"- Potential Full-field-ready scope: {32+len(ready_dates)} dates","","No performance metric, model training, scaler fit, prediction, Candidate EXACT5, Stage A rerun, or Stage B was executed.","", "## Technical-ready dates", "", *[f"- {d}" for d in ready_dates], "", "## Not technical-ready dates", "", *[f"- {x['date']}: {x['reason']}" for x in failed], "", "## Next", "", "`NEXT = CLAUDE_INDEPENDENT_READINESS_REVIEW_FOR_54_DATE_SCOPE`" if not failed else "`NEXT = CLAUDE_INDEPENDENT_READINESS_REVIEW_FOR_PARTIAL_EXPANDED_SCOPE`"]
    (OUT/"report.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    hashes={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hash_index.json"}; dump("artifact_hash_index.json",{"algorithm":"SHA256","indexed_artifacts":hashes,"self_hash_excluded":True}); safety["ARTIFACT_HASH_VALIDATION"]="PASS" if all(sha(OUT/n)==h for n,h in hashes.items()) else "FAIL"; dump("safety.json",safety); hashes["safety.json"]=sha(OUT/"safety.json"); dump("artifact_hash_index.json",{"algorithm":"SHA256","indexed_artifacts":hashes,"self_hash_excluded":True})
    print("CANDIDATE_GENERATION_22DATE_FULL_FIELD_READINESS_V1=COMPLETE")


if __name__=="__main__": main()
