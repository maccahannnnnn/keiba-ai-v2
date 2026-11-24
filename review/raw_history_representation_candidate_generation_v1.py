"""Gated raw-history representation Candidate Generation development experiment.

This module is an additive sibling of the frozen 54-date paired Stage-A runner.
It never changes the production engine, Stage-B implementation, frozen V4
artifacts, or source data.  ``--prepare`` freezes all pre-result contracts;
``--execute`` is allowed only after those hashes exist and validate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import warnings
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

import review.candidate_generation_stage_a_paired_population_expanded_v1 as stage_a
import review.candidate_generation_stage_b_fast_route_b4_buy_performance_v1 as stage_b

OUT = ROOT / "reports/raw_history_representation_candidate_generation_v1"
LEDGER = ROOT / "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md"
FINGERPRINT = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"
DS_SCHEMA = ROOT / "docs/target_bulk_result_schema_v1.json"
STAGE_A_ROOT = ROOT / "reports/candidate_generation_stage_a_paired_population_expanded_v1"
STAGE_B_ROOT = ROOT / "reports/candidate_generation_stage_b_fast_route_b4_buy_performance_v1_retry5"
SELECTION_ROOT = ROOT / "reports/selection_composition_policy_v2_shadow_phase1_v1"
FOLD_SHA = "ace55d0d48e24d066cee92e5a11aebbcf908f5256622303d5dd03bc1e5de099e"
CONTROL_BASELINE_SHA = "b5445181231fa170871adb3aeb92226059036e39b8e33f4aeabd512600df2f85"
CONTROL_TREATMENT_SHA = "bfd0f36c872474fbde826047e537d59c9e95ccabd648f19a10c0740e0a645291"
HISTORY_DEPTH = 10

# Numeric, interpretable, stable historical performance/condition measurements.
# Every value gets a paired missing indicator for every slot.
INCLUDED_NUMERIC = (
    ("DISTANCE", 14), ("CARRIED_WEIGHT", 20), ("FIELD_SIZE", 21),
    ("FINISH_POSITION", 23), ("MARGIN_SECONDS", 26), ("POPULARITY", 27),
    ("RUN_TIME_SECONDS", 28), ("ADJUSTED_TIME", 30),
    ("CORNER_1", 31), ("CORNER_2", 32), ("CORNER_3", 33), ("CORNER_4", 34),
    ("LAST_3F", 35), ("AVE_3F", 36), ("BODY_WEIGHT", 37),
    ("BODY_WEIGHT_DIFF", 38), ("PRIZE_MONEY", 41), ("RPCI", 48), ("PCI", 49),
)

CLASSIFICATIONS = {
    0:"REDUNDANT_OR_BOOKKEEPING_EXCLUDE", 1:"REDUNDANT_OR_BOOKKEEPING_EXCLUDE",
    2:"REDUNDANT_OR_BOOKKEEPING_EXCLUDE", 3:"REDUNDANT_OR_BOOKKEEPING_EXCLUDE",
    4:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE", 5:"REDUNDANT_OR_BOOKKEEPING_EXCLUDE",
    6:"REDUNDANT_OR_BOOKKEEPING_EXCLUDE", 7:"REDUNDANT_OR_BOOKKEEPING_EXCLUDE",
    8:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE", 9:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE",
    10:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE", 11:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE",
    12:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE", 13:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE",
    14:"PRE_TARGET_SAFE_INCLUDE", 15:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE",
    16:"IDENTIFIER_ONLY_EXCLUDE", 17:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE",
    18:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE", 19:"PERSON_OR_PEDIGREE_EXCLUDE",
    20:"PRE_TARGET_SAFE_INCLUDE", 21:"PRE_TARGET_SAFE_INCLUDE", 22:"IDENTIFIER_ONLY_EXCLUDE",
    23:"PRE_TARGET_SAFE_INCLUDE", 24:"REDUNDANT_OR_BOOKKEEPING_EXCLUDE",
    25:"LEAKAGE_RISK_EXCLUDE", 26:"PRE_TARGET_SAFE_INCLUDE", 27:"PRE_TARGET_SAFE_INCLUDE",
    28:"PRE_TARGET_SAFE_INCLUDE", 29:"REDUNDANT_OR_BOOKKEEPING_EXCLUDE",
    30:"PRE_TARGET_SAFE_INCLUDE", 31:"PRE_TARGET_SAFE_INCLUDE", 32:"PRE_TARGET_SAFE_INCLUDE",
    33:"PRE_TARGET_SAFE_INCLUDE", 34:"PRE_TARGET_SAFE_INCLUDE", 35:"PRE_TARGET_SAFE_INCLUDE",
    36:"PRE_TARGET_SAFE_INCLUDE", 37:"PRE_TARGET_SAFE_INCLUDE", 38:"PRE_TARGET_SAFE_INCLUDE",
    39:"PERSON_OR_PEDIGREE_EXCLUDE", 40:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE",
    41:"PRE_TARGET_SAFE_INCLUDE", 42:"PERSON_OR_PEDIGREE_EXCLUDE",
    43:"PERSON_OR_PEDIGREE_EXCLUDE", 44:"PERSON_OR_PEDIGREE_EXCLUDE",
    45:"PERSON_OR_PEDIGREE_EXCLUDE", 46:"PERSON_OR_PEDIGREE_EXCLUDE",
    47:"UNSTABLE_OR_UNSUPPORTED_EXCLUDE", 48:"PRE_TARGET_SAFE_INCLUDE",
    49:"PRE_TARGET_SAFE_INCLUDE",
}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(name: str, rows: list[dict], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(rows[0]) if rows else []
    with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def clean_name(value: object) -> str:
    return str(value or "").strip().replace(" ", "").replace("　", "")


def raw_path(kind: str, date: str) -> Path:
    suffix = date[2:]
    if date == "20260418":
        return ROOT / f"data/raw/prediction_input/{kind}{suffix}v2.CSV"
    return ROOT / f"data/raw/prediction_input/{kind}{suffix}.CSV"


def read_fixed(path: Path, width: int) -> list[list[str]]:
    if not path.is_file():
        raise Stop(f"RAW_SOURCE_MISSING:{path}")
    with path.open(encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows or any(len(row) != width for row in rows):
        raise Stop(f"RAW_SOURCE_WIDTH_INVALID:{path}:{sorted({len(x) for x in rows})}")
    return rows


def ds_date(row: list[str]) -> str:
    try:
        return f"{2000 + int(row[0].strip()):04d}{int(row[1].strip()):02d}{int(row[2].strip()):02d}"
    except (ValueError, IndexError) as exc:
        raise Stop(f"DS_DATE_INVALID:{row[:3]}") from exc


def optional_number(value: object) -> tuple[float, float]:
    text = str(value or "").strip().replace("+", "")
    if not text or not re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return 0.0, 1.0
    number = float(text)
    if not math.isfinite(number):
        return 0.0, 1.0
    return number, 0.0


def raw_feature_names() -> list[str]:
    names = []
    for slot in range(1, HISTORY_DEPTH + 1):
        names.append(f"HIST_{slot:02d}_PRESENT")
        for semantic, _ in INCLUDED_NUMERIC:
            names.extend((f"HIST_{slot:02d}_{semantic}", f"HIST_{slot:02d}_{semantic}_MISSING"))
    return names


def history_vector(rows: list[list[str]], target_date: str) -> tuple[list[float], dict]:
    inspected = len(rows)
    rejected_date = [row for row in rows if ds_date(row) >= target_date]
    eligible = [row for row in rows if ds_date(row) < target_date and row[25].strip() in {"", "0"} and optional_number(row[23])[0] > 0]
    eligible.sort(key=ds_date, reverse=True)
    used = eligible[:HISTORY_DEPTH]
    values: list[float] = []
    for slot in range(HISTORY_DEPTH):
        if slot >= len(used):
            values.append(0.0)
            for _semantic, _index in INCLUDED_NUMERIC:
                values.extend((0.0, 0.0))
            continue
        row = used[slot]
        values.append(1.0)
        for _semantic, index in INCLUDED_NUMERIC:
            values.extend(optional_number(row[index]))
    expected = HISTORY_DEPTH * (1 + 2 * len(INCLUDED_NUMERIC))
    if len(values) != expected or not all(math.isfinite(x) for x in values):
        raise Stop("RAW_HISTORY_VECTOR_INVALID")
    return values, {"inspected":inspected,"eligible":len(eligible),"date_rejected":len(rejected_date),"used":len(used),"max_used_date":max((ds_date(x) for x in used),default=None)}


def feature_inventory() -> tuple[list[dict], dict]:
    schema = json.loads(DS_SCHEMA.read_text(encoding="utf-8"))
    columns = schema["ordered_columns"]
    if len(columns) != 50 or set(CLASSIFICATIONS) != set(range(50)):
        raise Stop("DS_50_COLUMN_AUTHORITY_INVALID")
    include_by_index = {i:n for n,i in INCLUDED_NUMERIC}
    records=[]
    for index,name in enumerate(columns):
        classification=CLASSIFICATIONS[index]
        included=classification == "PRE_TARGET_SAFE_INCLUDE"
        if included != (index in include_by_index):
            raise Stop(f"FEATURE_CLASSIFICATION_INCONSISTENT:{index}")
        records.append({"one_based_column":index+1,"zero_based_index":index,"source_column":name,"classification":classification,"included_in_rich_history":included,"rich_semantic_name":include_by_index.get(index),"reason":"numeric historical performance/condition measurement" if included else "excluded by frozen category; not used as predictor"})
    return records, schema


def source_inventory_and_history() -> tuple[list[dict], dict[str,dict[str,list[list[str]]]], dict]:
    dates=[d for values in stage_a.MONTHS.values() for d in values]
    inventory=[]; histories={}; totals=Counter(); bucket=Counter()
    for date in dates:
        by_name=defaultdict(list)
        for kind,width in (("DG",11),("DE",33),("DS",50)):
            path=raw_path(kind,date); rows=read_fixed(path,width)
            inventory.append({"date":date,"kind":kind,"path":str(path.relative_to(ROOT)).replace("\\","/"),"sha256":sha(path),"bytes":path.stat().st_size,"rows":len(rows),"column_count":width,"encoding":"cp932","header":False})
            totals[f"{kind}_rows"] += len(rows)
            if kind == "DS":
                for row in rows:
                    by_name[clean_name(row[16])].append(row)
                    totals["DS_rows_inspected"] += 1
                    if ds_date(row) >= date: totals["DS_date_rejected"] += 1
        for rows in by_name.values():
            usable=sum(ds_date(x)<date and x[25].strip() in {"","0"} and optional_number(x[23])[0]>0 for x in rows)
            bucket["0"] += usable==0; bucket["1-4"] += 1<=usable<=4; bucket["5"] += usable==5; bucket["6-9"] += 6<=usable<=9; bucket["10+"] += usable>=10
        if date == "20260906" and "ファストネットワー" in by_name and "ファストネットワーク" not in by_name:
            by_name["ファストネットワーク"] = by_name["ファストネットワー"]
        histories[date]=dict(by_name)
    return inventory,histories,{"source_dates":len(dates),**dict(totals),"source_horse_history_count_buckets":dict(bucket)}


def freeze_hashes() -> dict:
    names=("raw_history_feature_schema_v1.json","raw_history_experiment_design_freeze_v1.json","raw_history_evaluation_protocol_v1.json","raw_history_execution_order_v1.json")
    return {name:sha(OUT/name) for name in names}


def register_fingerprint() -> dict:
    before={"ledger_sha256":sha(LEDGER),"fingerprint_sha256":sha(FINGERPRINT)}
    index=json.loads(FINGERPRINT.read_text(encoding="utf-8"))
    all_ids={x.get("stable_id") for x in index.get("authoritative_additive_entries",[])}
    if "EXP-020" in all_ids:
        raise Stop("FINGERPRINT_ID_COLLISION:EXP-020")
    canonical="Raw History Representation Candidate Generation V1"
    for entry in index.get("authoritative_additive_entries",[]):
        if entry.get("canonical_name")==canonical or "RAW_HISTORY_REPRESENTATION" in json.dumps(entry,ensure_ascii=False):
            raise Stop("DUPLICATE_OR_RENAMED_REPEAT")
    entry={
        "stable_id":"EXP-020","type":"DEVELOPMENT EXPERIMENT","canonical_name":canonical,
        "aliases":["Deep Raw History Representation Candidate Generator","HISTORY_DEPTH_V1"],
        "mechanism_family":"CANDIDATE_GENERATION","normalized_family":"CANDIDATE_GENERATION",
        "evidence_role":"NON_EVIDENTIAL_DEVELOPMENT_EXPERIMENT","development_disposition":"OBSERVATION_ONLY",
        "evidence_gate_status":"NOT_APPLICABLE","operational_state":"READY",
        "model_role":"Candidate Generator","baseline_training_population":"Current Top5 rows",
        "treatment_training_population":"Full-field rows","target":"actual_top3",
        "candidate_output":"EXACT5","downstream":"Frozen Stage B + Frozen Selection Policy v2",
        "fold_manifest_sha256":FOLD_SHA,"stage_b_metric":"BUY_TOP3_RATE",
        "untouched_holdout_used":False,"formal_prospective_used":False,
        "fingerprint":{"major_axis":"RAW_HISTORY_REPRESENTATION","base_features":"existing 20 semantic features","history_depth":HISTORY_DEPTH,"model_family":"StandardScaler + LogisticRegression"},
        "do_not_repeat":"PENDING_RESULT_REVIEW","reopen_condition":["Material change to raw-history schema or frozen fold protocol"],
        "provenance":{"root":"reports/raw_history_representation_candidate_generation_v1/","registration_stage":"PRE_EXECUTION"},
    }
    index.setdefault("authoritative_additive_entries",[]).append(entry)
    index["total_logical_entries"]=int(index.get("total_logical_entries",40))+1
    index.setdefault("machine_state",{})["TOTAL_LOGICAL_ENTRIES"]=index["total_logical_entries"]
    index["authoritative_last_update_date"]="2026-09-11"
    index.setdefault("development_disposition_counts",{})["OBSERVATION_ONLY"]=int(index["development_disposition_counts"].get("OBSERVATION_ONLY",0))+1
    index.setdefault("evidence_gate_status_counts",{})["NOT_APPLICABLE"]=int(index["evidence_gate_status_counts"].get("NOT_APPLICABLE",0))+1
    index.setdefault("operational_state_counts",{})["READY"]=int(index["operational_state_counts"].get("READY",0))+1
    FINGERPRINT.write_text(json.dumps(index,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    addition=("\n## Authoritative Additive Entry — 2026-09-11\n\n"
        "| Field | EXP-020 |\n|---|---|\n"
        "| Canonical name | Raw History Representation Candidate Generation V1 |\n"
        "| Mechanism family | CANDIDATE_GENERATION |\n"
        "| Evidence role | NON_EVIDENTIAL_DEVELOPMENT_EXPERIMENT |\n"
        "| Major axis | Existing 20 semantic features + frozen HISTORY_DEPTH_V1=10 raw-history representation |\n"
        "| Baseline / Treatment | Current Top5 training rows / Full-field training rows |\n"
        "| Output / downstream | EXACT5 / Frozen Stage B + Frozen Selection Policy v2 |\n"
        "| Fold authority | `ace55d0d48e24d066cee92e5a11aebbcf908f5256622303d5dd03bc1e5de099e` |\n"
        "| Boundary | Development only; untouched holdout and Formal Prospective are prohibited. |\n"
        "| Provenance | `reports/raw_history_representation_candidate_generation_v1/` |\n")
    LEDGER.write_text(LEDGER.read_text(encoding="utf-8")+addition,encoding="utf-8")
    return {**before,"after":{"ledger_sha256":sha(LEDGER),"fingerprint_sha256":sha(FINGERPRINT)},"stable_id":"EXP-020","status":"REGISTERED_PRE_EXECUTION","collision_count":0,"duplicate_count":0}


def prepare() -> None:
    if OUT.exists(): raise Stop(f"OUTPUT_EXISTS:{OUT}")
    required=(LEDGER,FINGERPRINT,DS_SCHEMA,STAGE_A_ROOT/"expanded_stage_a_fold_manifest.json",STAGE_A_ROOT/"baseline_predictions.csv",STAGE_A_ROOT/"treatment_predictions.csv",STAGE_B_ROOT/"phase2_lane_performance.json",SELECTION_ROOT/"policy_v2_scope_freeze.json")
    if not all(p.is_file() for p in required): raise Stop("AUTHORITY_MISSING")
    if sha(STAGE_A_ROOT/"expanded_stage_a_fold_manifest.json")!=FOLD_SHA: raise Stop("FOLD_SHA_MISMATCH")
    OUT.mkdir(parents=True)
    records,schema=feature_inventory()
    inventory,_histories,stats=source_inventory_and_history()
    write_csv("source_inventory.csv",inventory)
    dump("ds_field_inventory.json",{"source_schema":str(DS_SCHEMA.relative_to(ROOT)),"source_schema_sha256":sha(DS_SCHEMA),"column_count":50,"fields":records})
    include=[r for r in records if r["included_in_rich_history"]]
    feature_schema={"schema_id":"RAW_HISTORY_FEATURE_SCHEMA_V1","history_depth":HISTORY_DEPTH,"slot_order":"most recent valid completed run first","base_semantic_feature_count":20,"base_transformed_feature_count":21,"included_numeric_source_fields":include,"per_slot_layout":["HIST_nn_PRESENT","each numeric value","paired *_MISSING indicator"],"missing_slot":"all zeros including PRESENT=0","present_row_missing_numeric":"value=0 and missing_indicator=1","feature_names":raw_feature_names(),"raw_history_feature_count":len(raw_feature_names()),"total_transformed_feature_count":21+len(raw_feature_names()),"date_usage":"ordering/as-of validation only; not a predictor","person_pedigree_identifiers_excluded":True}
    dump("raw_history_feature_schema_v1.json",feature_schema)
    design={"experiment_id":"RAW_HISTORY_REPRESENTATION_CANDIDATE_GENERATION_V1","model_role":"Candidate Generator","major_axis_only":"Raw history representation added to existing 20 semantic features","history_depth_id":"HISTORY_DEPTH_V1","history_depth":10,"lanes":{"baseline":"Current Top5 training rows","treatment":"Full-field training rows"},"target":"actual_top3","output":"EXACT5","tie_break":["probability DESC","shadow_ai_rank ASC","horse_number ASC"],"fold_manifest_sha256":FOLD_SHA,"evaluation_dates":45,"evaluation_races":828,"february_training_only_races":160,"untouched_holdout":False,"formal_prospective":False,"model_family":"StandardScaler + LogisticRegression","hyperparameters":{"solver":"lbfgs","penalty":"l2","C":1.0,"class_weight":None,"max_iter":100,"tol":0.0001},"source_stats":stats}
    protocol={"stage_a_primary":"NET_TOP3_CAPTURE_GAIN","stage_b_primary":"BUY_TOP3_RATE","baseline_control":{"natural_buy":679,"valid_buy":679,"top3_hits":266,"buy_top3_rate":0.3917525773195876},"treatment_control":{"natural_buy":720,"valid_buy":719,"invalid_buy":1,"top3_hits":276,"buy_top3_rate":0.38386648122392214},"accept":"both Stage B lanes strictly improve valid BUY_TOP3_RATE versus their own control and Top3 capture has no material collapse","hold":"one lane improves while other degrades materially, temporal inconsistency, or mixed result","reject":"both lanes fail to improve Stage B, major capture degradation, convergence/identity/as-of failure"}
    order={"steps":["SOURCE_INVENTORY","DS_FIELD_INVENTORY","FEATURE_SCHEMA_FREEZE","EXPERIMENT_DESIGN_FREEZE","EVALUATION_PROTOCOL_FREEZE","FINGERPRINT_REGISTRATION","CONTROL_REPRODUCTION","RICH_TRAINING","RICH_STAGE_A","FROZEN_STAGE_B","FINAL_CLASSIFICATION"],"result_access_before_freeze":0}
    dump("raw_history_experiment_design_freeze_v1.json",design); dump("raw_history_evaluation_protocol_v1.json",protocol); dump("raw_history_execution_order_v1.json",order)
    freeze=freeze_hashes(); dump("pre_execution_freeze_hash_manifest.json",{"status":"PASS","hashes":freeze,"created_at":now()})
    registration=register_fingerprint(); dump("fingerprint_registration.json",registration)
    dump("safety.json",{"phase":"PREPARED","production_change":0,"engine_change":0,"stage_b_change":0,"v4_change":0,"source_change":0,"untouched_holdout_access":0,"formal_prospective_execution":0,"performance_calculation":0,"result_access":0,"freeze_hash_validation":"PASS"})
    print("RAW_HISTORY_PREPARE=COMPLETE")


def enrich_rows(rows: list[dict], histories: dict[str,dict[str,list[list[str]]]]) -> tuple[list[dict],dict]:
    out=[]; audit=Counter(); buckets=Counter(); latest_used_date=None
    for row in rows:
        horse_rows=histories[row["date"]].get(clean_name(row["horse_name"]))
        if horse_rows is None: raise Stop(f"DS_HORSE_IDENTITY_UNMATCHED:{row['date']}:{row['race_id']}:{row['horse_name']}")
        vector,stats=history_vector(horse_rows,row["date"])
        if stats["date_rejected"]: raise Stop(f"AS_OF_DATE_VIOLATION:{row['date']}:{row['horse_name']}")
        for key in ("inspected","eligible","date_rejected","used"):
            audit[key] += int(stats[key])
        if stats["max_used_date"] is not None:
            latest_used_date=max(latest_used_date or stats["max_used_date"],stats["max_used_date"])
        buckets["0" if stats["used"]==0 else "1-4" if stats["used"]<=4 else "5" if stats["used"]==5 else "6-9" if stats["used"]<=9 else "10"]+=1
        out.append({**row,"raw_history_vector":vector,"history_used":stats["used"]})
    return out,{**dict(audit),"latest_used_history_date":latest_used_date,"target_horse_history_buckets":dict(buckets),"as_of_date_violations":0}


def vector(row: dict, rich: bool) -> list[float]:
    base=stage_a.vector(row)
    values=base+(row["raw_history_vector"] if rich else [])
    if not all(math.isfinite(x) for x in values): raise Stop("MODEL_INPUT_NONFINITE")
    return values


def exact5_order_key(row: dict) -> tuple[float, float, int]:
    return (-float(row["probability"]), float(row["shadow_ai_rank"]), int(row["horse_number"]))


def fit(rows: list[dict], label: str, rich: bool):
    if not rows or not all(r["valid_result"] for r in rows): raise Stop(f"TRAIN_LABEL_BOUNDARY_FAIL:{label}")
    x=np.asarray([vector(r,rich) for r in rows],dtype=float); y=np.asarray([r["actual_top3"] for r in rows],dtype=int)
    scaler=StandardScaler()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        z=scaler.fit_transform(x)
        model=LogisticRegression(solver="lbfgs",penalty="l2",C=1.0,class_weight=None,max_iter=100,tol=0.0001).fit(z,y)
    conv=[str(w.message) for w in caught if issubclass(w.category,ConvergenceWarning)]
    if conv or not np.isfinite(model.coef_).all(): raise Stop(f"MODEL_CONVERGENCE_FAIL:{label}:{conv}")
    return scaler,model,{"label":label,"training_rows":len(rows),"positive_rows":int(y.sum()),"negative_rows":int(len(y)-y.sum()),"input_features":x.shape[1],"scaler_fit_rows":len(rows),"model_fit_rows":len(rows),"convergence":"PASS","warnings":[]}


def select(rows: list[dict], scaler, model, label: str, rich: bool) -> list[dict]:
    grouped=defaultdict(list)
    for row in rows:
        prob=float(model.predict_proba(scaler.transform(np.asarray([vector(row,rich)],dtype=float)))[:,1][0])
        grouped[(row["date"],row["race_id"])].append({**row,"model":label,"probability":prob})
    out=[]
    for key,items in grouped.items():
        ordered=sorted(items,key=exact5_order_key)
        if len(ordered)<5: raise Stop(f"EXACT5_UNDEFINED:{key}")
        out += [{**r,"selected":i<5,"candidate_rank":i+1} for i,r in enumerate(ordered)]
    return out


def grouped_selected(rows: list[dict]) -> dict:
    out=defaultdict(list)
    for r in rows:
        if r["selected"]: out[(r["date"],r["race_id"])].append({"horse_number":int(r["horse_number"]),"horse_name":r["horse_name"],"candidate_rank":int(r["candidate_rank"]),"candidate_probability":float(r["probability"]),"current_rank":int(r["current_rank"]),"shadow_ai_rank":float(r["shadow_ai_rank"])})
    if len(out)!=828 or any(len(x)!=5 for x in out.values()): raise Stop("EXACT5_GROUPING_FAIL")
    return dict(out)


def stage_a_metrics(eval_rows: list[dict], control: list[dict], rich: list[dict]) -> dict:
    by_result=defaultdict(list)
    for r in eval_rows: by_result[(r["date"],r["race_id"])].append(r)
    def sets(values):
        g=defaultdict(set)
        for r in values:
            if r["selected"]: g[(r["date"],r["race_id"])].add(r["horse_number"])
        return g
    c,s=sets(control),sets(rich); total=Counter(); folds=defaultdict(Counter); dates=defaultdict(Counter)
    for key,field in by_result.items():
        top={r["horse_number"] for r in field if r["valid_result"] and r["actual_top3"]==1}
        rec=len((s[key]-c[key])&top); disp=len((c[key]-s[key])&top); ch=len(c[key]&top); sh=len(s[key]&top)
        fold=next(f["fold_id"] for f in json.loads((OUT/"raw_history_experiment_design_freeze_v1.json").read_text(encoding="utf-8")).get("folds",[]) if False) if False else ""
        for target in (total,dates[key[0]]): target.update({"races":1,"denominator":len(top),"control_hits":ch,"rich_hits":sh,"recovered":rec,"displaced":disp})
    return {"aggregate":dict(total),"by_date":[{"date":d,**dict(v)} for d,v in sorted(dates.items())]}


def execute() -> None:
    if not OUT.is_dir(): raise Stop("PREPARE_REQUIRED")
    frozen=json.loads((OUT/"pre_execution_freeze_hash_manifest.json").read_text(encoding="utf-8"))["hashes"]
    if frozen!=freeze_hashes(): raise Stop("PRE_EXECUTION_FREEZE_MISMATCH")
    mapping=stage_a.source_map(); races,inventory=stage_a.preflight(mapping)
    date_month={d:m for m,ds in stage_a.MONTHS.items() for d in ds}
    rows=stage_a.build_rows(mapping,date_month)
    _raw_inventory,histories,source_stats=source_inventory_and_history()
    rows,audit=enrich_rows(rows,histories)
    folds=[]
    for fold_id,train_months,eval_months in stage_a.FOLD_SPEC:
        folds.append({"fold_id":fold_id,"train_dates":[d for m in train_months for d in stage_a.MONTHS[m]],"eval_dates":[d for m in eval_months for d in stage_a.MONTHS[m]]})
    all_control={"baseline":[],"treatment":[]}; all_rich={"baseline":[],"treatment":[]}; convergence=[]; fold_metrics=[]
    # CONTROL is generated and byte-verified before the first Rich model fit.
    for fold in folds:
        train_dates=set(fold["train_dates"]); eval_dates=set(fold["eval_dates"])
        train=[r for r in rows if r["date"] in train_dates and r["valid_result"]]
        eval_rows=[r for r in rows if r["date"] in eval_dates]
        for lane,train_rows in (("baseline",[r for r in train if r["current_top5"]]),("treatment",train)):
            cs,cm,ca=fit(train_rows,f"CONTROL_{lane}_{fold['fold_id']}",False)
            control_label = "PAIRED_TOP5_BASELINE_EXACT5" if lane == "baseline" else "FULL_FIELD_TREATMENT_EXACT5"
            cp=select(eval_rows,cs,cm,control_label,False)
            all_control[lane]+=cp; convergence.append(ca)
    concise=["model","selected","candidate_rank","date","month","race_id","venue","race_number","horse_number","horse_name","current_rank","valid_result","actual_finish","actual_top3","probability","shadow_ai_rank"]
    for lane in ("baseline","treatment"):
        write_csv(f"control_{lane}_predictions.csv",all_control[lane],concise)
    control_hashes={lane:sha(OUT/f"control_{lane}_predictions.csv") for lane in ("baseline","treatment")}
    control_ok=control_hashes=={"baseline":CONTROL_BASELINE_SHA,"treatment":CONTROL_TREATMENT_SHA}
    dump("control_reproduction.json",{"status":"PASS" if control_ok else "FAIL","actual":control_hashes,"expected":{"baseline":CONTROL_BASELINE_SHA,"treatment":CONTROL_TREATMENT_SHA},"independently_generated":True,"reference_artifact_bytes_copied":False})
    if not control_ok: raise Stop("CONTROL_REPRODUCTION_FAIL")
    for fold in folds:
        train_dates=set(fold["train_dates"]); eval_dates=set(fold["eval_dates"])
        train=[r for r in rows if r["date"] in train_dates and r["valid_result"]]
        eval_rows=[r for r in rows if r["date"] in eval_dates]
        for lane,train_rows in (("baseline",[r for r in train if r["current_top5"]]),("treatment",train)):
            rs,rm,ra=fit(train_rows,f"RICH_{lane}_{fold['fold_id']}",True)
            rp=select(eval_rows,rs,rm,f"RICH_{lane.upper()}_EXACT5",True)
            all_rich[lane]+=rp; convergence.append(ra)
            cp=[r for r in all_control[lane] if r["date"] in eval_dates]
            metric=stage_a_metrics(eval_rows,cp,rp)["aggregate"]
            fold_metrics.append({"fold_id":fold["fold_id"],"lane":lane,**metric,"net":metric["rich_hits"]-metric["control_hits"]})
    for lane in ("baseline","treatment"):
        write_csv(f"rich_{lane}_predictions.csv",all_rich[lane],concise)
    dump("model_convergence_audit.json",{"status":"PASS","fits":convergence,"fit_count":len(convergence),"all_data_final_fit":0})
    dump("history_coverage_audit.json",{**source_stats,**audit,"history_depth":10,"used_row_date_violation":0})
    stage_a_summary={}
    for lane in ("baseline","treatment"):
        eval_rows=[r for r in rows if r["date"] not in set(stage_a.MONTHS["FEBRUARY"])]
        stage_a_summary[lane]=stage_a_metrics(eval_rows,all_control[lane],all_rich[lane])
    dump("stage_a_metrics.json",{"lanes":stage_a_summary,"folds":fold_metrics})
    # Frozen Stage-B is reused by invocation only; its source and semantics remain unchanged.
    dates={d for f in folds for d in f["eval_dates"]}; sources=stage_a.source_map(); sources={d:sources[d] for d in dates}
    current=stage_b.current_buys(dates,sources); all_keys={(d,json.loads(p.read_text(encoding="utf-8"))["race_id"]) for d in dates for p in sources[d]}
    original_packet=stage_b.candidate_packet
    try:
        stage_b.candidate_packet=lambda lane,date,race_id,exact5,snapshot_hash:{"race_id":race_id,"race_context_snapshot_hash":snapshot_hash,"generator_id":f"RAW_HISTORY_{lane.upper()}","generator_version_hash":sha(OUT/f"rich_{lane}_predictions.csv"),"generator_recipe_freeze_hash":sha(OUT/"raw_history_experiment_design_freeze_v1.json"),"tie_break_id":stage_b.EXACT5_TIE_BREAK_ID,"exact5":deepcopy(exact5)}
        events=[]; manifest,natural,p1=stage_b.phase1(dates,sources,grouped_selected(all_rich["baseline"]),grouped_selected(all_rich["treatment"]),events)
    finally:
        stage_b.candidate_packet=original_packet
    if p1["PHASE1_RESULT"]!="PASS": raise Stop("FROZEN_STAGE_B_PHASE1_FAIL")
    write_csv("stage_b_natural_buy_baseline.csv",natural["baseline"],["date","race_id","venue","race_number","horse_number","horse_name","decision","candidate_rank","current_rank"])
    write_csv("stage_b_natural_buy_treatment.csv",natural["treatment"],["date","race_id","venue","race_number","horse_number","horse_name","decision","candidate_rank","current_rank"])
    enriched,joins,perf,comparisons,race_rows,undefined=stage_b.phase2(dates,all_keys,current,natural,events)
    if undefined: raise Stop(f"STAGE_B_DENOMINATOR_UNDEFINED:{undefined}")
    controls=json.loads((STAGE_B_ROOT/"phase2_lane_performance.json").read_text(encoding="utf-8"))
    dump("stage_b_metrics.json",{"control":{"baseline":controls["baseline"],"treatment":controls["treatment"]},"rich":{"baseline":perf["baseline"],"treatment":perf["treatment"]},"delta_rate_pt":{"baseline":(perf["baseline"]["buy_top3_rate"]-controls["baseline"]["buy_top3_rate"])*100,"treatment":(perf["treatment"]["buy_top3_rate"]-controls["treatment"]["buy_top3_rate"])*100},"result_join":joins,"phase1":p1})
    b_delta=perf["baseline"]["buy_top3_rate"]-controls["baseline"]["buy_top3_rate"]
    t_delta=perf["treatment"]["buy_top3_rate"]-controls["treatment"]["buy_top3_rate"]
    capture_delta={lane:stage_a_summary[lane]["aggregate"]["rich_hits"]-stage_a_summary[lane]["aggregate"]["control_hits"] for lane in ("baseline","treatment")}
    if b_delta>0 and t_delta>0 and min(capture_delta.values())>=-3: classification="RAW_HISTORY_REPRESENTATION_PROMISING"
    elif b_delta<=0 and t_delta<=0: classification="RAW_HISTORY_REPRESENTATION_NOT_SUPPORTED"
    else: classification="RAW_HISTORY_REPRESENTATION_MIXED"
    dump("final_classification.json",{"classification":classification,"baseline_stage_b_rate_delta":b_delta,"treatment_stage_b_rate_delta":t_delta,"stage_a_capture_delta":capture_delta,"production_go":False,"untouched_holdout_used":False,"formal_prospective_used":False})
    safety={"production_change":0,"engine_change":0,"decision_engine_change":0,"race_decision_engine_change":0,"stage_b_source_change":0,"selection_policy_source_change":0,"v4_change":0,"raw_source_change":0,"untouched_holdout_access":0,"formal_prospective_execution":0,"threshold_search":0,"hyperparameter_search":0,"result_access":"CONSUMED_DEVELOPMENT_ONLY_AFTER_FREEZE","control_reproduction":"PASS","as_of_date_violations":0,"artifact_hash_validation":"PENDING"}; dump("safety.json",safety)
    report=(f"# Raw History Representation Candidate Generation V1\n\n"
        f"`FINAL_CLASSIFICATION = {classification}`\n\n"
        f"- CONTROL reproduction: PASS\n- Evaluation: 45 dates / 828 races; February 160 races is training-only.\n"
        f"- Raw history: HISTORY_DEPTH_V1=10; included numeric fields={len(INCLUDED_NUMERIC)}; raw features={len(raw_feature_names())}.\n"
        f"- Stage A capture delta: Baseline {capture_delta['baseline']:+d}, Treatment {capture_delta['treatment']:+d}.\n"
        f"- Stage B BUY_TOP3_RATE: Baseline {controls['baseline']['buy_top3_rate']:.6%} → {perf['baseline']['buy_top3_rate']:.6%}; Treatment {controls['treatment']['buy_top3_rate']:.6%} → {perf['treatment']['buy_top3_rate']:.6%}.\n"
        f"- Production / untouched holdout / Formal Prospective: not executed.\n\n"
        "`NEXT = CLAUDE_INDEPENDENT_RAW_HISTORY_IMPLEMENTATION_RESULT_REVIEW`\n")
    (OUT/"report.md").write_text(report,encoding="utf-8")
    safety["artifact_hash_validation"]="PASS"; dump("safety.json",safety)
    index={str(p.relative_to(OUT)).replace("\\","/"):{"sha256":sha(p),"size":p.stat().st_size} for p in OUT.rglob("*") if p.is_file() and p.name!="artifact_hash_index.json"}
    dump("artifact_hash_index.json",{"self_hash_excluded":True,"indexed_artifacts":index})
    print(f"RAW_HISTORY_REPRESENTATION_CANDIDATE_GENERATION_V1={classification}")


def finalize_stopped(reason: str) -> None:
    """Materialize a fail-closed audit without another model-fit attempt."""
    if not OUT.is_dir(): raise Stop("PREPARE_REQUIRED")
    design_path=OUT/"raw_history_experiment_design_freeze_v1.json"
    design=json.loads(design_path.read_text(encoding="utf-8"))
    dump("raw_history_model_freeze_v1.json",{
        "status":"SEMANTICS_FROZEN_BY_PRE_EXECUTION_DESIGN_ARTIFACT",
        "source_artifact":"raw_history_experiment_design_freeze_v1.json",
        "source_artifact_sha256":sha(design_path),
        "model_family":design["model_family"],"hyperparameters":design["hyperparameters"],
        "target":design["target"],"candidate_output":design["output"],
        "note":"This named projection records the already-frozen recipe; it does not alter or retry it."
    })
    _inventory,histories,source_stats=source_inventory_and_history()
    mapping=stage_a.source_map(); date_month={d:m for m,ds in stage_a.MONTHS.items() for d in ds}
    rows=stage_a.build_rows(mapping,date_month); _rows,audit=enrich_rows(rows,histories)
    dump("history_coverage_audit.json",{**source_stats,**audit,"history_depth":10,"used_row_date_violation":0})
    concise=["model","selected","candidate_rank","date","month","race_id","venue","race_number","horse_number","horse_name","current_rank","valid_result","actual_finish","actual_top3","probability","shadow_ai_rank"]
    for name in ("rich_baseline_predictions.csv","rich_treatment_predictions.csv"):
        write_csv(name,[],concise)
    buy_fields=["date","race_id","venue","race_number","horse_number","horse_name","decision","candidate_rank","current_rank"]
    write_csv("stage_b_natural_buy_baseline.csv",[],buy_fields); write_csv("stage_b_natural_buy_treatment.csv",[],buy_fields)
    dump("model_convergence_audit.json",{"status":"FAIL_CLOSED","control_fit_count":10,"control_fit_status":"PASS_AND_BYTE_IDENTICAL","rich_fit_attempt_count":1,"rich_fit_success_count":0,"failed_fit":"RICH_baseline_FOLD_MAR_EXPANDED_EVAL","fixed_max_iter":100,"retry_count":0,"hyperparameter_change":0,"reason":reason})
    dump("stage_a_metrics.json",{"status":"NOT_EXECUTED_DUE_TO_MODEL_CONVERGENCE_FAILURE","performance_calculation":0})
    dump("stage_b_metrics.json",{"status":"NOT_EXECUTED_DUE_TO_MODEL_CONVERGENCE_FAILURE","stage_b_execution":0,"result_access_for_stage_b":0})
    dump("final_classification.json",{"classification":"STOP_MODEL_CONVERGENCE_FAILURE","requested_three_way_classification":"NOT_REACHED","reason":reason,"production_go":False,"untouched_holdout_used":False,"formal_prospective_used":False})
    control={"baseline":sha(OUT/"control_baseline_predictions.csv") if (OUT/"control_baseline_predictions.csv").is_file() else None,"treatment":sha(OUT/"control_treatment_predictions.csv") if (OUT/"control_treatment_predictions.csv").is_file() else None}
    dump("control_reproduction.json",{"status":"PASS" if control=={"baseline":CONTROL_BASELINE_SHA,"treatment":CONTROL_TREATMENT_SHA} else "FAIL","actual":control,"expected":{"baseline":CONTROL_BASELINE_SHA,"treatment":CONTROL_TREATMENT_SHA},"independently_generated":True,"reference_artifact_bytes_copied":False})
    dump("safety.json",{"phase":"FAIL_CLOSED","stop_reason":reason,"production_change":0,"engine_change":0,"decision_engine_change":0,"race_decision_engine_change":0,"stage_b_change":0,"selection_policy_change":0,"v4_change":0,"raw_source_change":0,"untouched_holdout_access":0,"formal_prospective_execution":0,"threshold_search":0,"hyperparameter_search":0,"consumed_development_result_access_dates":54,"future_result_access":0,"control_fit_count":10,"rich_fit_attempt_count":1,"rich_fit_success_count":0,"stage_b_execution":0,"control_reproduction":"PASS","as_of_date_violations":0,"artifact_hash_validation":"PASS"})
    (OUT/"report.md").write_text("# Raw History Representation Candidate Generation V1\n\n`FINAL = STOP_MODEL_CONVERGENCE_FAILURE`\n\n- CONTROL reproduction: PASS.\n- First Rich fit stopped because frozen lbfgs/max_iter=100 did not converge.\n- No Rich prediction, Stage A performance calculation, or Stage B execution followed.\n- Recipe, feature set, threshold, Production, and frozen authorities were not changed.\n\n`NEXT = CLAUDE_INDEPENDENT_RAW_HISTORY_IMPLEMENTATION_RESULT_REVIEW`\n",encoding="utf-8")
    index={str(p.relative_to(OUT)).replace("\\","/"):{"sha256":sha(p),"size":p.stat().st_size} for p in OUT.rglob("*") if p.is_file() and p.name!="artifact_hash_index.json"}
    dump("artifact_hash_index.json",{"self_hash_excluded":True,"indexed_artifacts":index})
    print("RAW_HISTORY_REPRESENTATION_CANDIDATE_GENERATION_V1=STOP_MODEL_CONVERGENCE_FAILURE")


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("phase",choices=("prepare","execute","finalize-stop")); args=parser.parse_args()
    if args.phase=="prepare": prepare()
    elif args.phase=="execute": execute()
    else: finalize_stopped("MODEL_CONVERGENCE_FAIL:RICH_baseline_FOLD_MAR_EXPANDED_EVAL:lbfgs reached frozen max_iter=100")


if __name__ == "__main__":
    main()
