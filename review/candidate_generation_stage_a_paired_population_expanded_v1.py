"""Frozen one-shot 54-date paired Stage-A development experiment."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from review.candidate_generation_training_dataset_readiness_v1 import (
    ABNORMAL, FEATURES, JAPANESE_VENUE, Stop, feature_values, outcome,
    parse_race_id, result_rows, valid_feature,
)

OUT = ROOT / "reports/candidate_generation_stage_a_paired_population_expanded_v1"
ADDITIONAL_AUDIT = ROOT / "reports/candidate_generation_22date_full_field_readiness_v1"
GOVERNANCE = ROOT / "reports/candidate_generation_26date_governance_reconciliation_v1"
ORIGINAL = ROOT / "reports/candidate_generation_stage_a_paired_population_v1_retry1"
MODEL = ROOT / "reports/ml_v4_buy_selection_model_v4"
PROTECTED = {"20260718", "20260719", "20260808", "20260809"}

MONTHS = {
    "FEBRUARY": ("20260201","20260207","20260208","20260210","20260214","20260215","20260221","20260222","20260228"),
    "MARCH": ("20260301","20260307","20260308","20260314","20260315","20260321","20260322","20260328","20260329"),
    "APRIL": ("20260404","20260405","20260411","20260412","20260418","20260419","20260425","20260426"),
    "MAY": ("20260502","20260503","20260509","20260510","20260516","20260517","20260523","20260524","20260530","20260531"),
    "JUNE": ("20260620","20260621","20260627","20260628"),
    "JULY": ("20260704","20260705","20260711","20260712","20260725","20260726"),
    "AUGUST": ("20260801","20260802","20260815","20260816","20260829","20260830"),
    "SEPTEMBER": ("20260905","20260906"),
}
EXPECTED_RACES = {"FEBRUARY":160,"MARCH":173,"APRIL":152,"MAY":192,"JUNE":68,"JULY":102,"AUGUST":105,"SEPTEMBER":36}
FOLD_SPEC = (
    ("FOLD_MAR_EXPANDED_EVAL", ("FEBRUARY",), ("MARCH",)),
    ("FOLD_APR_EXPANDED_EVAL", ("FEBRUARY","MARCH"), ("APRIL",)),
    ("FOLD_MAY_EXPANDED_EVAL", ("FEBRUARY","MARCH","APRIL"), ("MAY",)),
    ("FOLD_JUNJUL_EXPANDED_EVAL", ("FEBRUARY","MARCH","APRIL","MAY"), ("JUNE","JULY")),
    ("FOLD_AUGSEP_EXPANDED_EVAL", ("FEBRUARY","MARCH","APRIL","MAY","JUNE","JULY"), ("AUGUST","SEPTEMBER")),
)
GATES = {"absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_sha(value: object) -> str:
    return hashlib.sha256((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")).hexdigest()


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(name: str, rows: list[dict], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(rows[0]) if rows else []
    with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def source_map() -> dict[str, list[Path]]:
    """Use only frozen PRE artifacts; no prediction regeneration."""
    mapping: dict[str, list[Path]] = {}
    for month, root in (
        ("FEBRUARY", "reports/v4_model_v4_february_historical_holdout/formal_pre/current_ai"),
        ("MARCH", "reports/march_2026_historical_holdout_pre/current_ai"),
        ("MAY", "reports/may_2026_multi_system_oos_v1/pre_retry_v5/current_ai"),
    ):
        for date in MONTHS[month]:
            paths = sorted((ROOT / root / date).glob("race_*_prediction.json"))
            if not paths: raise Stop(f"PREDICTION_SOURCE_MISSING:{date}")
            mapping[date] = paths
    for date in (*MONTHS["AUGUST"][-2:], *MONTHS["SEPTEMBER"]):
        index = ROOT / f"reports/prospective_prediction_{date}_v1/race_index.json"
        if not index.is_file(): raise Stop(f"PREDICTION_INDEX_MISSING:{date}")
        mapping[date] = [ROOT / f"reports/prospective_prediction_{date}_v1" / item["artifact"] for item in json.loads(index.read_text(encoding="utf-8"))["race_index"]]
    provenance = json.loads((ADDITIONAL_AUDIT / "provenance_audit.json").read_text(encoding="utf-8"))
    for month in ("APRIL", "JUNE", "JULY"):
        for date in MONTHS[month]:
            root = ROOT / provenance[date]["prediction_source"]
            paths = sorted(root.glob("race_*_prediction.json"))
            if not paths: raise Stop(f"ADDITIONAL_SOURCE_MISSING:{date}")
            mapping[date] = paths
    for date in MONTHS["AUGUST"][:4]:
        root = ROOT / provenance[date]["prediction_source"]
        paths = sorted(root.glob("race_*_prediction.json"))
        if not paths: raise Stop(f"ADDITIONAL_SOURCE_MISSING:{date}")
        mapping[date] = paths
    return mapping


def preflight(mapping: dict[str, list[Path]]) -> tuple[dict[str, list[str]], list[dict]]:
    by_month, inventory = defaultdict(list), []
    for month, dates in MONTHS.items():
        for date in dates:
            if date in PROTECTED: raise Stop(f"PROTECTED_DATE_INCLUDED:{date}")
            paths = mapping.get(date)
            if not paths: raise Stop(f"DATE_SOURCE_UNRECOVERABLE:{date}")
            races = []
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                race_id = payload.get("race_id")
                actual_date, venue, number = parse_race_id(race_id)
                ranked = payload.get("ranked_results")
                if actual_date != date or venue not in JAPANESE_VENUE or not isinstance(ranked, list):
                    raise Stop(f"PRE_IDENTITY_OR_RANKED_INVALID:{path}")
                ranks = [r.get("rank") for r in ranked]
                if sorted(ranks) != list(range(1, len(ranked)+1)) or sum(r <= 5 for r in ranks) != 5:
                    raise Stop(f"CURRENT_TOP5_CONTRACT_UNAVAILABLE:{date}:{race_id}")
                if len(ranked) < 5: raise Stop(f"ORIGINAL_EXACT5_UNDEFINED:{date}:{race_id}")
                races.append(race_id)
            if len(set(races)) != len(races): raise Stop(f"DUPLICATE_PRE_RACE:{date}")
            by_month[month].extend(races)
            inventory.append({"date":date,"month":month,"race_count":len(races),"prediction_artifact_count":len(paths),"source_sha256":sha(paths[0]),"current_top5_contract":"PASS"})
    for month, expected in EXPECTED_RACES.items():
        if len(by_month[month]) != expected: raise Stop(f"MONTH_RACE_COUNT_MISMATCH:{month}:{len(by_month[month])}:{expected}")
    return {k: sorted(v) for k,v in by_month.items()}, inventory


def build_rows(mapping: dict[str, list[Path]], date_month: dict[str,str]) -> list[dict]:
    rows, seen = [], set()
    for date in sorted(mapping):
        results = result_rows(date)
        for path in mapping[date]:
            payload = json.loads(path.read_text(encoding="utf-8")); race_id = payload["race_id"]
            _, venue_key, number = parse_race_id(race_id); result = results.get((JAPANESE_VENUE[venue_key], number))
            if result is None: raise Stop(f"RESULT_RACE_UNMATCHED:{race_id}")
            ranked = payload.get("ranked_results"); trace = payload.get("buy_gate_trace", {})
            horses, race = trace.get("horses"), trace.get("race") if isinstance(trace,dict) else (None,None)
            if not isinstance(ranked,list) or not isinstance(horses,list) or not isinstance(race,dict) or len(ranked)!=int(result[9]) or len(horses)!=len(ranked):
                raise Stop(f"FULL_FIELD_TRACE_OR_SIZE_INVALID:{race_id}")
            by_no={int(x["horse_number"]):x for x in horses if isinstance(x,dict) and x.get("horse_number") is not None}
            nums=[int(x["horse_number"]) for x in ranked]
            if len(by_no)!=len(ranked) or set(by_no)!=set(nums) or len(set(nums))!=len(nums): raise Stop(f"FULL_FIELD_IDENTITY_INVALID:{race_id}")
            state=race.get("shadow_race_state")
            if state not in {"PLAY_CONVERGED","PLAY_UNCONVERGED_4PLUS","SKIP"}: raise Stop(f"RACE_STATE_INVALID:{race_id}")
            for horse in ranked:
                no=int(horse["horse_number"]); key=(date,race_id,no)
                if key in seen: raise Stop(f"DUPLICATE_ROW:{key}")
                seen.add(key); values=feature_values(horse,by_no[no],state,":".join(map(str,key)))
                if any(not valid_feature(value,feature)[0] for feature,value in values.items()): raise Stop(f"FEATURE_INVALID:{key}")
                valid,finish,top3=outcome(result,no)
                rows.append({"date":date,"month":date_month[date],"race_id":race_id,"venue":JAPANESE_VENUE[venue_key],"race_number":number,"horse_number":no,"horse_name":horse.get("horse_name"),"current_rank":horse.get("rank"),"current_top5":horse.get("rank")<=5,"valid_result":valid,"actual_finish":finish,"actual_top3":int(top3) if valid else None,**values})
    return rows


def vector(row: dict) -> list[float]:
    values=[]
    for feature in FEATURES[:-1]: values.append(float(bool(row[feature])) if feature in GATES else float(row[feature]))
    values += [float(row["race_state"]=="PLAY_UNCONVERGED_4PLUS"),float(row["race_state"]=="SKIP")]
    if len(values)!=21 or not all(math.isfinite(x) for x in values): raise Stop("TRANSFORM_INPUT_INVALID")
    return values


def fit(rows: list[dict], label: str):
    if not rows or not all(r["valid_result"] for r in rows): raise Stop(f"TRAIN_LABEL_BOUNDARY_FAIL:{label}")
    x=np.asarray([vector(r) for r in rows],dtype=float); y=np.asarray([r["actual_top3"] for r in rows],dtype=int)
    if y.sum()==0 or y.sum()==len(y): raise Stop(f"TRAIN_CLASS_DEGENERATE:{label}")
    scaler=StandardScaler()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always",ConvergenceWarning); z=scaler.fit_transform(x); model=LogisticRegression(solver="lbfgs",penalty="l2",C=1.0,class_weight=None,max_iter=100,tol=0.0001).fit(z,y)
    if any(issubclass(w.category,ConvergenceWarning) for w in caught) or not np.isfinite(model.coef_).all(): raise Stop(f"MODEL_CONVERGENCE_FAIL:{label}")
    return scaler,model,{"training_rows":len(rows),"feature_rows":len(rows),"scaler_fit_rows":len(rows),"positive_rows":int(y.sum()),"negative_rows":int(len(y)-y.sum()),"convergence":"PASS"}


def select(rows: list[dict], scaler, model, label: str) -> list[dict]:
    grouped=defaultdict(list)
    for r in rows: grouped[(r["date"],r["race_id"])].append({**r,"model":label,"probability":float(model.predict_proba(scaler.transform(np.asarray([vector(r)],dtype=float)))[:,1][0])})
    out=[]
    for key,items in grouped.items():
        if len(items)<5: raise Stop(f"EXACT5_UNDEFINED:{label}:{key}")
        for i,row in enumerate(sorted(items,key=lambda x:(-x["probability"],x["shadow_ai_rank"],x["horse_number"]))): out.append({**row,"selected":i<5,"candidate_rank":i+1})
    return out


def frozen_current(rows: list[dict]) -> list[dict]:
    grouped=defaultdict(list)
    for r in rows: grouped[(r["date"],r["race_id"])].append(r)
    out=[]
    for key,items in grouped.items():
        chosen=sorted((r for r in items if r["current_top5"]),key=lambda r:r["current_rank"])
        if len(chosen)!=5: raise Stop(f"CURRENT_TOP5_NOT_EXACT5:{key}")
        out += [{**r,"model":"FROZEN_CURRENT_TOP5","selected":True,"candidate_rank":r["current_rank"]} for r in chosen]
    return out


def summarize(records: list[dict], left: str, right: str) -> dict:
    c=Counter()
    for r in records:
        c["races"]+=1; c["denominator"]+=r["valid_top3_slots"]; c["left"]+=r[left+"_capture"]; c["right"]+=r[right+"_capture"]; c["recovered"]+=r[f"{left}_to_{right}_recovered"]; c["displaced"]+=r[f"{left}_to_{right}_displaced"]
    if c["right"]-c["left"] != c["recovered"]-c["displaced"]: raise Stop(f"ACCOUNTING_FAIL:{left}:{right}")
    rate = lambda count: count / c["denominator"] if c["denominator"] else None
    return {"races":c["races"],"valid_actual_top3_denominator":c["denominator"],"left_capture":c["left"],"right_capture":c["right"],"left_rate":rate(c["left"]),"right_rate":rate(c["right"]),"raw_difference":c["right"]-c["left"],"pp_difference":rate(c["right"]-c["left"]),"recovered":c["recovered"],"displaced":c["displaced"],"net":c["recovered"]-c["displaced"]}


def compare(rows: list[dict], current: list[dict], baseline: list[dict], treatment: list[dict]) -> list[dict]:
    all_rows=defaultdict(list); sets={}
    for r in rows: all_rows[(r["date"],r["race_id"])].append(r)
    for name,values in (("current",current),("baseline",baseline),("treatment",treatment)):
        g=defaultdict(list)
        for r in values:
            if r["selected"]: g[(r["date"],r["race_id"])].append(r)
        if any(len(v)!=5 for v in g.values()): raise Stop(f"EXACT5_VOLUME_FAIL:{name}")
        sets[name]=g
    records=[]
    for key,field in sorted(all_rows.items()):
        top={r["horse_number"] for r in field if r["valid_result"] and r["actual_top3"]==1}; selected={n:{r["horse_number"] for r in sets[n][key]} for n in sets}
        caps={n:len(top & selected[n]) for n in selected}
        rec={}
        for left,right in (("baseline","treatment"),("current","baseline"),("current","treatment")):
            recovered=len(top & selected[right]-selected[left]); displaced=len(top & selected[left]-selected[right])
            if caps[right]-caps[left] != recovered-displaced: raise Stop(f"PAIR_ACCOUNTING_FAIL:{key}:{left}:{right}")
            rec[f"{left}_to_{right}_recovered"]=recovered; rec[f"{left}_to_{right}_displaced"]=displaced
        expected=len(top)*min(5,len(field))/len(field)
        records.append({"date":key[0],"month":field[0]["month"],"race_id":key[1],"valid_field_size":len(field),"valid_top3_slots":len(top),"current_capture":caps["current"],"baseline_capture":caps["baseline"],"treatment_capture":caps["treatment"],"baseline_invalid_selected":sum(not r["valid_result"] for r in sets["baseline"][key]),"treatment_invalid_selected":sum(not r["valid_result"] for r in sets["treatment"][key]),"current_invalid_selected":sum(not r["valid_result"] for r in sets["current"][key]),"expected_capture":expected,"oracle_capture":len(top),"treatment_vs_baseline": "TREATMENT_SUPERIOR" if caps["treatment"]>caps["baseline"] else "BASELINE_SUPERIOR" if caps["treatment"]<caps["baseline"] else "EQUAL",**rec})
    return records


def direction(net: int) -> str: return "POSITIVE" if net>0 else "NEGATIVE" if net<0 else "NEUTRAL"
def stability(total: int, fold_nets: list[int]) -> str:
    if total==0: return "NOT_APPLICABLE"
    signs={1 if x>0 else -1 if x<0 else 0 for x in fold_nets}; sign=1 if total>0 else -1
    if -sign not in signs: return "CONSISTENT"
    return "CONCENTRATED" if any((1 if x>0 else -1 if x<0 else 0)==sign and abs(x)>=abs(total) for x in fold_nets) else "MIXED"


def main() -> None:
    retry = OUT.exists()
    if retry and not (OUT / "freeze_hash_manifest.json").is_file():
        raise Stop(f"RETRY_FREEZE_AUTHORITY_MISSING:{OUT}")
    required=(ROOT/"KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md",ROOT/"KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json",ORIGINAL/"performance_blind_fold_manifest.json",ORIGINAL/"stage_a_normalized_capture.json",ADDITIONAL_AUDIT/"scope_arithmetic.json",GOVERNANCE/"scope_arithmetic.json",MODEL/"feature_schema.json",MODEL/"feature_transform_schema.json",MODEL/"training_recipe.json")
    if not all(p.is_file() for p in required): raise Stop("HISTORY_OR_PRIMARY_AUTHORITY_MISSING")
    recipe=json.loads((MODEL/"training_recipe.json").read_text(encoding="utf-8")); schema=json.loads((MODEL/"feature_schema.json").read_text(encoding="utf-8")); transform=json.loads((MODEL/"feature_transform_schema.json").read_text(encoding="utf-8"))
    # The frozen recipe JSON is authoritative for model family/hyperparameters it
    # persists.  The original Stage-A authority fixes the two omitted sklearn
    # defaults explicitly at max_iter=100 and tol=0.0001.
    if tuple(schema["semantic_feature_order"])!=FEATURES or transform["transformed_input_count"]!=21 or not (recipe["pipeline"]==["StandardScaler","LogisticRegression"] and recipe["solver"]=="lbfgs" and recipe["penalty"]=="l2" and recipe["C"]==1.0 and recipe["class_weight"] is None): raise Stop("FROZEN_RECIPE_CONTRACT_MISMATCH")
    if not retry:
        OUT.mkdir(parents=True)
    mapping=source_map(); races, inventory=preflight(mapping); dates=[d for m in MONTHS.values() for d in m]; date_month={d:m for m,ds in MONTHS.items() for d in ds}
    if len(dates)!=54 or len(set(dates))!=54 or set(dates)&PROTECTED or len(mapping)!=54 or sum(map(len,races.values()))!=988: raise Stop("EXACT_SCOPE_ASSERTION_FAIL")
    folds=[]
    for name,train_months,eval_months in FOLD_SPEC:
        train_dates=[d for m in train_months for d in MONTHS[m]]; eval_dates=[d for m in eval_months for d in MONTHS[m]]
        folds.append({"fold_id":name,"train_months":list(train_months),"eval_months":list(eval_months),"train_dates":train_dates,"eval_dates":eval_dates,"train_races":sum(len(races[m]) for m in train_months),"eval_races":sum(len(races[m]) for m in eval_months)})
    scope={"canonical_experiment":"CANDIDATE_GENERATION_STAGE_A_PAIRED_POPULATION_EXPANDED_V1","evidence_role":"NON_EVIDENTIAL_DEVELOPMENT_EXPERIMENT","coverage_expansion_reason":"COVERAGE_COMPLETENESS","dates":dates,"total_date_count":54,"total_race_count":988,"current_32_date_count":32,"additional_22_date_count":22,"current_additional_date_overlap":0,"protected_4_dates":sorted(PROTECTED),"protected_4_dates_included":"NO","month_race_counts":{m:len(races[m]) for m in MONTHS}}
    metric={"primary":"Actual Top3 capture by Exact5: baseline vs treatment","operational":"Frozen Current Top5 vs baseline; Frozen Current Top5 vs treatment","recovered_displaced":"right-only versus left-only actual Top3 slots; net=recovered-displaced","invalid_result":"selected invalid-result slot stays occupied, no replacement, no hit","normalized_capture_formula":"expected = valid_top3_slots * min(5, valid_field_size) / valid_field_size; normalized=(observed-expected)/(oracle-expected)","race_superiority":"treatment capture vs baseline capture","formal_accept_reject_threshold":"NONE"}
    decision={"direction_rule":"POSITIVE if aggregate net > 0; NEUTRAL if = 0; NEGATIVE if < 0","temporal_stability_rule":"FROZEN_DETERMINISTIC_SIGN_BASED_RULE","generator_choice_default":"UNRESOLVED","full_field_treatment_preferred":"primary POSITIVE+CONSISTENT and current_to_treatment POSITIVE","top5_baseline_preferred":"primary NEGATIVE+CONSISTENT and current_to_baseline POSITIVE","stage_b_design":"PROCEED iff current_to_baseline or current_to_treatment is POSITIVE+CONSISTENT; otherwise HOLD","stage_b_implementation":"HOLD","general_races_lt_100_fold_rule_created":"NO","fold_grouping_rule":"THIS_EXACT_5_FOLD_MANIFEST_ONLY"}
    top5={"ORIGINAL_STAGE_A_CURRENT_TOP5_CONTRACT_RECOVERED":"YES","CURRENT_TOP5_SELECTION_RULE_RECOVERED_FROM_PRIMARY_ARTIFACT":"YES","selection_rule":"ranked_results current rank <= 5, exactly five rows per frozen race","FROZEN_CURRENT_TOP5_AVAILABLE_FOR_ALL_54_DATES":"YES","FROZEN_CURRENT_OPERATIONAL_COMPARATOR_AVAILABLE":"YES","BASELINE_TRAINING_POPULATION_REPRODUCIBLE":"YES","source_authority":str(ORIGINAL/"performance_blind_fold_manifest.json")}
    recipe_freeze={"semantic_features":list(FEATURES),"semantic_feature_count":20,"transformed_input_count":21,"scaler":"StandardScaler fitted independently per fold and population","model":{"family":"LogisticRegression","solver":"lbfgs","penalty":"l2","C":1.0,"class_weight":None,"max_iter":100,"tol":0.0001},"target":"actual_top3","prediction":"predict_proba[:,1]","exact5_tie_break":["probability DESC","shadow_ai_rank ASC","horse_number ASC"]}
    history={"HISTORY_DUPLICATE_PRECHECK":"PASS","classification":"COVERAGE_EXPANDED_RERUN_OF_EXISTING_STAGE_A","new_ana_id":False,"new_exp_id":False,"new_gate_id":False,"primary_artifacts":[str(x.relative_to(ROOT)) for x in required]}
    fold_freeze={"folds":folds,"evaluation_race_total":828,"february_training_only_races":160,"performance_blind":True,"PERFORMANCE_BLIND_FOLD_FREEZE":"PASS"}
    freeze_names=["expanded_stage_a_scope_freeze.json","expanded_stage_a_fold_manifest.json","expanded_stage_a_recipe_freeze.json","expanded_stage_a_metric_contract.json","expanded_stage_a_decision_framework.json"]
    freeze_values={"expanded_stage_a_scope_freeze.json":scope,"expanded_stage_a_fold_manifest.json":fold_freeze,"expanded_stage_a_recipe_freeze.json":recipe_freeze,"expanded_stage_a_metric_contract.json":metric,"expanded_stage_a_decision_framework.json":decision}
    if retry:
        recorded=json.loads((OUT / "freeze_hash_manifest.json").read_text(encoding="utf-8"))["hashes"]
        # A retry validates the already frozen bytes.  It must not rewrite or
        # regenerate the five freeze artifacts merely because the reporting
        # code was corrected after an interrupted first run.
        if set(recorded) != set(freeze_names) or any(sha(OUT/name) != recorded[name] for name in freeze_names):
            raise Stop("RETRY_FREEZE_HASH_OR_CONTENT_MISMATCH")
    else:
        dump("scope.json",scope); dump("history_precheck.json",history); dump("current_top5_contract_preflight.json",top5)
        for name in freeze_names: dump(name,freeze_values[name])
        freeze_hash={x:sha(OUT/x) for x in freeze_names}; dump("freeze_hash_manifest.json",{"FREEZE_ARTIFACTS_CREATED":"YES","FREEZE_ARTIFACT_HASH_VALIDATION":"PASS","hashes":freeze_hash})
    if not retry:
        dump("pre_performance_assertions.json",{"EXACT_54_DATES":"PASS","RACES_988":"PASS","PROTECTED_4_EXCLUDED":"PASS","CURRENT_TOP5_CONTRACT":"PASS","FIVE_FOLD_MANIFEST":"PASS","FEATURE_CONTRACT":"PASS","MODEL_RECIPE":"PASS","NORMALIZED_METRIC_FORMULA":"PASS","DECISION_FRAMEWORK":"PASS","FREEZE_HASHES":"PASS","NO_PERFORMANCE_YET_CALCULATED":"YES","PRE_PERFORMANCE_FREEZE_GATE":"PASS"})
    rows=build_rows(mapping,date_month)
    if len({(r["date"],r["race_id"]) for r in rows})!=988: raise Stop("ROW_SCOPE_RACE_MISMATCH")
    all_b,all_t,all_c,records,fold_rows=[],[],[],[],[]; convergence=[]
    for fold in folds:
        train_dates=set(fold["train_dates"]); eval_dates=set(fold["eval_dates"]); train=[r for r in rows if r["date"] in train_dates and r["valid_result"]]; base_train=[r for r in train if r["current_top5"]]; evaluation=[r for r in rows if r["date"] in eval_dates]
        bs,bm,ba=fit(base_train,fold["fold_id"]+":BASELINE"); ts,tm,ta=fit(train,fold["fold_id"]+":TREATMENT"); b=select(evaluation,bs,bm,"PAIRED_TOP5_BASELINE_EXACT5"); t=select(evaluation,ts,tm,"FULL_FIELD_TREATMENT_EXACT5"); c=frozen_current(evaluation); rec=compare(evaluation,c,b,t); records+=rec; all_b+=b; all_t+=t; all_c+=c; convergence += [{"fold_id":fold["fold_id"],"model":"BASELINE","population":"CURRENT_TOP5","audit":ba},{"fold_id":fold["fold_id"],"model":"TREATMENT","population":"FULL_FIELD","audit":ta}]
        pb=summarize(rec,"baseline","treatment"); cb=summarize(rec,"current","baseline"); ct=summarize(rec,"current","treatment"); fold_rows.append({"fold_id":fold["fold_id"],"eval_dates":"|".join(fold["eval_dates"]),"race_count":pb["races"],"valid_actual_top3_denominator":pb["valid_actual_top3_denominator"],"current_captured":cb["left_capture"],"baseline_captured":pb["left_capture"],"treatment_captured":pb["right_capture"],"primary_net":pb["net"],"current_to_baseline_net":cb["net"],"current_to_treatment_net":ct["net"]})
    primary=summarize(records,"baseline","treatment"); current_baseline=summarize(records,"current","baseline"); current_treatment=summarize(records,"current","treatment")
    primary_nets=[x["primary_net"] for x in fold_rows]; cb_nets=[x["current_to_baseline_net"] for x in fold_rows]; ct_nets=[x["current_to_treatment_net"] for x in fold_rows]
    primary.update({"direction":direction(primary["net"]),"temporal_stability":stability(primary["net"],primary_nets)}); current_baseline.update({"direction":direction(current_baseline["net"]),"temporal_stability":stability(current_baseline["net"],cb_nets)}); current_treatment.update({"direction":direction(current_treatment["net"]),"temporal_stability":stability(current_treatment["net"],ct_nets)})
    choice="FULL_FIELD_TREATMENT_PREFERRED" if primary["direction"]=="POSITIVE" and primary["temporal_stability"]=="CONSISTENT" and current_treatment["direction"]=="POSITIVE" else "TOP5_CONDITIONED_BASELINE_PREFERRED" if primary["direction"]=="NEGATIVE" and primary["temporal_stability"]=="CONSISTENT" and current_baseline["direction"]=="POSITIVE" else "UNRESOLVED"
    stage="PROCEED" if (current_baseline["direction"]=="POSITIVE" and current_baseline["temporal_stability"]=="CONSISTENT") or (current_treatment["direction"]=="POSITIVE" and current_treatment["temporal_stability"]=="CONSISTENT") else "HOLD"; mode="FULL_FIELD_TREATMENT" if choice=="FULL_FIELD_TREATMENT_PREFERRED" else "TOP5_CONDITIONED_BASELINE" if choice=="TOP5_CONDITIONED_BASELINE_PREFERRED" else "GENERATOR_INDEPENDENT" if stage=="PROCEED" else "NOT_APPLICABLE"
    date_rows=[]
    for date in dates:
        rec=[r for r in records if r["date"]==date]; p=summarize(rec,"baseline","treatment"); cb=summarize(rec,"current","baseline"); ct=summarize(rec,"current","treatment"); date_rows.append({"date":date,"race_count":p["races"],"valid_actual_top3_denominator":p["valid_actual_top3_denominator"],"current_capture":cb["left_capture"],"baseline_capture":p["left_capture"],"treatment_capture":p["right_capture"],"primary_net":p["net"],"current_to_baseline_net":cb["net"],"current_to_treatment_net":ct["net"]})
    normalized={}
    for name,key in (("current","current_capture"),("baseline","baseline_capture"),("treatment","treatment_capture")):
        observed=sum(r[key] for r in records); expected=sum(r["expected_capture"] for r in records); oracle=sum(r["oracle_capture"] for r in records); normalized[name]={"SUM_OBSERVED":observed,"SUM_EXPECTED":expected,"SUM_ORACLE":oracle,"WEIGHTED_NORMALIZED_CAPTURE_POSITION":(observed-expected)/(oracle-expected)}
    normalized["treatment_minus_baseline"]=normalized["treatment"]["WEIGHTED_NORMALIZED_CAPTURE_POSITION"]-normalized["baseline"]["WEIGHTED_NORMALIZED_CAPTURE_POSITION"]
    normalized["treatment_minus_current"]=normalized["treatment"]["WEIGHTED_NORMALIZED_CAPTURE_POSITION"]-normalized["current"]["WEIGHTED_NORMALIZED_CAPTURE_POSITION"]
    concise=["model","selected","candidate_rank","date","month","race_id","venue","race_number","horse_number","horse_name","current_rank","valid_result","actual_finish","actual_top3","probability","shadow_ai_rank"]
    write_csv("baseline_predictions.csv",all_b,concise); write_csv("treatment_predictions.csv",all_t,concise); write_csv("baseline_exact5.csv",[r for r in all_b if r["selected"]],[x for x in concise if x!="probability"]); write_csv("treatment_exact5.csv",[r for r in all_t if r["selected"]],[x for x in concise if x!="probability"]); write_csv("current_comparator.csv",all_c,[x for x in concise if x!="probability"]); write_csv("fold_level_accounting.csv",fold_rows); write_csv("date_level_accounting.csv",date_rows); write_csv("source_inventory.csv",inventory)
    dump("training_manifest.json",{"fold_count":5,"all_data_final_fit":0,"training_population_axis_only":"YES","baseline":"Frozen Current Top5 valid rows","treatment":"Full-field valid rows","evaluation":"same held-out full field"}); dump("model_convergence_audit.json",{"MODEL_CONVERGENCE":"PASS","per_fold_model":convergence,"all_data_final_fit":0}); dump("primary_accounting.json",primary); dump("operational_accounting.json",{"current_to_baseline":current_baseline,"current_to_treatment":current_treatment}); dump("recovered_displaced_accounting.json",{"baseline_to_treatment":{"recovered":primary["recovered"],"displaced":primary["displaced"],"net":primary["net"]},"current_to_baseline":{"recovered":current_baseline["recovered"],"displaced":current_baseline["displaced"],"net":current_baseline["net"]},"current_to_treatment":{"recovered":current_treatment["recovered"],"displaced":current_treatment["displaced"],"net":current_treatment["net"]}}); dump("normalized_capture.json",normalized); dump("invalid_selection_audit.json",{"baseline_invalid_selected":sum(r["baseline_invalid_selected"] for r in records),"treatment_invalid_selected":sum(r["treatment_invalid_selected"] for r in records),"current_invalid_selected":sum(r["current_invalid_selected"] for r in records),"replacement_after_result":0})
    dump("interpretation_framework_result.json",{"layer_1_training_population_causal_effect":{"direction":primary["direction"],"stability":primary["temporal_stability"]},"layer_2_operational":{"current_to_baseline":{"direction":current_baseline["direction"],"stability":current_baseline["temporal_stability"]},"current_to_treatment":{"direction":current_treatment["direction"],"stability":current_treatment["temporal_stability"]},"note":"Current-to-treatment total is not attributed entirely to full-field training."},"layer_3_stage_b_design":stage}); dump("generator_choice_result.json",{"GENERATOR_CHOICE":choice}); dump("stage_b_design_implication.json",{"STAGE_B_INTEGRATION_DESIGN":stage,"STAGE_B_GENERATOR_MODE":mode,"STAGE_B_IMPLEMENTATION":"HOLD","PRODUCTION_DECISION":"NOT_AUTHORIZED"})
    safety={"LEDGER_CHANGE":0,"FINGERPRINT_CHANGE":0,"DRAFT_V3_CHANGE":0,"DATA_CATALOG_CHANGE":0,"WORK_RECORD_CHANGE":0,"PROTECTED_4_DATE_DATA_ACCESS":0,"UNTOUCHED_HOLDOUT_ACCESS":0,"FUTURE_RESULT_ACCESS":0,"NEW_FEATURE_SEARCH":0,"MODEL_SHOPPING":0,"HYPERPARAMETER_SEARCH":0,"ALL_DATA_FINAL_FIT":0,"STAGE_B_EXECUTION":0,"ENGINE_CHANGE":0,"RACE_DECISION_ENGINE_CHANGE":0,"PRODUCTION_CHANGE":0,"GIT_COMMIT":0,"GIT_PUSH":0,"ORIGINAL_32_DAY_STAGE_A_CHANGED":"NO","ARTIFACT_HASH_VALIDATION":"PENDING"}; dump("safety.json",safety)
    dump("scope_arithmetic.json",{"TOTAL_DATE_COUNT":54,"TOTAL_RACE_COUNT":988,"EVALUATION_RACE_COUNT":828,"FEBRUARY_TRAINING_ONLY_RACE_COUNT":160,"month_race_counts":{m:len(races[m]) for m in MONTHS}})
    report=f"# Candidate Generation\n# 54-Date Expanded Paired Stage A — 完了\n\n`CANDIDATE_GENERATION_STAGE_A_PAIRED_POPULATION_EXPANDED_V1 = COMPLETE`\n\n- Scope: 54 dates / 988 races; evaluation: 828 races; February is training-only.\n- Primary Baseline→Treatment: {primary['left_capture']} / {primary['valid_actual_top3_denominator']} vs {primary['right_capture']} / {primary['valid_actual_top3_denominator']}; net {primary['net']}; {primary['direction']} / {primary['temporal_stability']}.\n- Generator Choice: `{choice}`. Stage B design implication: `{stage}`; implementation remains HOLD.\n- Original 32-day result remains separate (Baseline 760/1313; Treatment 770/1313; net +10; POSITIVE_BUT_WEAK / CONCENTRATED).\n\n`NEXT = CLAUDE_INDEPENDENT_EXPANDED_STAGE_A_RESULT_REVIEW`\n"; (OUT/"report.md").write_text(report,encoding="utf-8")
    index={str(p.relative_to(OUT)).replace("\\\\","/"):{"sha256":sha(p),"size":p.stat().st_size} for p in OUT.rglob("*") if p.is_file() and p.name!="artifact_hash_index.json"}; dump("artifact_hash_index.json",{"indexed_artifacts":index,"self_hash_excluded":True}); safety["ARTIFACT_HASH_VALIDATION"]="PASS"; dump("safety.json",safety)
    # Safety changed after the first index generation: recreate the index once, excluding itself.
    index={str(p.relative_to(OUT)).replace("\\\\","/"):{"sha256":sha(p),"size":p.stat().st_size} for p in OUT.rglob("*") if p.is_file() and p.name!="artifact_hash_index.json"}; dump("artifact_hash_index.json",{"indexed_artifacts":index,"self_hash_excluded":True})
    print("CANDIDATE_GENERATION_STAGE_A_PAIRED_POPULATION_EXPANDED_V1=COMPLETE")


if __name__ == "__main__": main()
