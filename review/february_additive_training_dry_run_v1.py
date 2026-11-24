"""February additive TRAIN compatibility dry-run; never fits a model or scaler."""
from __future__ import annotations
import csv, hashlib, json, math, statistics, sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
 sys.path.insert(0,str(ROOT))
OUT=ROOT/"reports"/"february_additive_training_dry_run_v1"
PRE=ROOT/"reports"/"v4_model_v4_february_historical_holdout"/"formal_pre"
POST=ROOT/"reports"/"v4_model_v4_february_historical_holdout"/"formal_post"
DATA=ROOT/"reports"/"ml_v4_buy_selection_dataset_v4"
MODEL=ROOT/"reports"/"ml_v4_buy_selection_model_v4"
V3=ROOT/"reports"/"v4_model_v3_prospective_protocol_v1"; V4=ROOT/"reports"/"v4_model_v4_formal_prospective"; CF=ROOT/"reports"/"shadow_cf_top3_rank_anchored_v1"
class Stop(RuntimeError):pass
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):
 v=json.loads(Path(p).read_text(encoding="utf8"))
 if not isinstance(v,dict):raise Stop(f"JSON_OBJECT_REQUIRED:{p}")
 return v
def dump(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
def verify(root):
 x=load(root/"artifact_hashes.json").get("indexed_artifacts")
 if not isinstance(x,dict):raise Stop(f"HASH_INDEX_INVALID:{root}")
 for n,h in x.items():
  if not isinstance(h,str) or not (root/n).is_file() or sha(root/n)!=h:raise Stop(f"HASH_INDEX_MISMATCH:{root}:{n}")
 return len(x)

def main():
 if OUT.exists():raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
 from review.ml_v4_buy_selection_dataset_build_v4 import primary_feature_values, top5_and_buy
 from review.ml_v4_buy_selection_dataset_inventory_v2 import FEATURES, outcome, result_for_race, result_rows, sha as source_sha
 from review.ml_v4_buy_selection_model_train_v4 import SEMANTIC, GATES, transformed_columns
 before={"pre":sha(PRE/"artifact_hashes.json"),"post":sha(POST/"artifact_hashes.json"),"dataset":sha(DATA/"dataset.csv"),"model":sha(MODEL/"model.joblib"),"scaler":sha(MODEL/"scaler.joblib"),"v3":sha(V3/"artifact_hashes.json"),"v4":sha(V4/"artifact_hashes.json"),"cf":sha(CF/"protocol.json")}
 checks={"pre_verified":verify(PRE),"post_verified":verify(POST),"v3_verified":verify(V3),"v4_verified":verify(V4)}
 if set(FEATURES)!=set(SEMANTIC):raise Stop("MODEL_V4_20_FEATURE_SET_AUTHORITY_MISMATCH")
 cols=transformed_columns()
 if len(FEATURES)!=20 or len(cols)!=21:raise Stop("MODEL_V4_TRANSFORM_AUTHORITY_MISMATCH")
 OUT.mkdir(parents=True)
 dump("authority.json",{"design":"FEBRUARY_ADDITIVE_TRAINING_DESIGN = FROZEN_PENDING_DRY_RUN","ready_for_round4":"YES","model_training_authorized":"NO","builder":"review/ml_v4_buy_selection_dataset_build_v4.py","model_transform_authority":"review/ml_v4_buy_selection_model_train_v4.py","semantic_feature_count":20,"transformed_input_count":21,"relative_gap":"available in Dataset v4 builder but explicitly not selected for Model v4"})
 dump("design_freeze_reference.json",{"base_dataset":{"rows":4100,"primary_validation_capable":3240,"march_train_only":860},"authoritative_cv_fold_count":7,"february_role":"TREATMENT_TRAIN_ONLY","forbidden":["February validation","model fit","scaler fit","candidate model","prediction rerun","feature/threshold change"]})
 dates=sorted(p.name for p in (PRE/"current_ai").iterdir() if p.is_dir())
 expected_dates=["20260201","20260207","20260208","20260210","20260214","20260215","20260221","20260222","20260228"]
 if dates!=expected_dates:raise Stop(f"FEBRUARY_DATE_SET_MISMATCH:{dates}")
 files=[]
 for d in dates:files += sorted((PRE/"current_ai"/d).glob("race_*_prediction.json"))
 if len(files)!=160:raise Stop(f"FEBRUARY_SOURCE_RACE_COUNT_MISMATCH:{len(files)}")
 source_hashes={"prediction_artifacts":[{"path":str(p.relative_to(ROOT)),"sha256":sha(p)} for p in files],"daily_results":[{"path":str((ROOT/'data'/'raw'/'target'/'daily_result_list'/f"馬番順着順_{d}.csv").relative_to(ROOT)),"sha256":sha(ROOT/'data'/'raw'/'target'/'daily_result_list'/f"馬番順着順_{d}.csv")} for d in dates]}
 dump("source_hashes.json",source_hashes)
 rows=[]; race_ids=[]; failures=[]; inv=[]; perdate=defaultdict(lambda:{"races":0,"top5":0,"invalid":0,"valid":0}); venues=Counter(); feature_source={f:{"source":"primary_feature_values -> stored frozen PRE horse / buy_gate_trace / race trace","expected_dtype":"numeric_or_boolean_or_race_state"} for f in FEATURES}
 for path in files:
  try:
   payload=load(path); rid=payload.get("race_id"); date=path.parent.name
   if not isinstance(rid,str) or rid.split("_")[1]!=date:raise Stop("RACE_DATE_IDENTITY_INVALID")
   top5,buys,_=top5_and_buy(payload,path)
   if len(top5)!=5:raise Stop("TOP5_COUNT_INVALID")
   index=result_rows(date); key,result=result_for_race(rid,index); traces={int(x["horse_number"]):x for x in payload.get("buy_gate_trace",{}).get("horses",[])}; race_trace=payload.get("buy_gate_trace",{}).get("race",{})
   if len(traces)!=len(payload.get("ranked_results",[])):raise Stop("TRACE_COVERAGE_INVALID")
   scores=[float(x["adjusted_score"]) for x in top5]; maximum=max(scores); perdate[date]["races"]+=1; race_ids.append(rid); venues[rid.split("_")[2]]+=1
   for horse in top5:
    no=int(horse["horse_number"]); perdate[date]["top5"]+=1; label=outcome(result,no)
    if not label["valid_result"]:
     perdate[date]["invalid"]+=1; inv.append({"date":date,"race_id":rid,"horse_number":no,"reason":"valid_result=False","actual_finish":label.get("actual_finish")});continue
    gap=float(horse["adjusted_score"])-maximum
    values=primary_feature_values(horse,traces.get(no),race_trace,gap)
    active={f:values[f] for f in FEATURES}; missing=[f for f,v in active.items() if v is None]
    if missing:raise Stop("FEATURE_MISSING:"+",".join(missing))
    # Exact Model-v4 pre-scaler transformation compatibility: booleans and race-state dummies only.
    transformed=[]
    for f in SEMANTIC[:-1]:
     v=active[f]; transformed.append(float(bool(v)) if f in GATES else float(v))
    state=active["race_state"]
    if state not in {"PLAY_CONVERGED","PLAY_UNCONVERGED_4PLUS","SKIP"}:raise Stop(f"RACE_STATE_INVALID:{state}")
    transformed += [float(state=="PLAY_UNCONVERGED_4PLUS"),float(state=="SKIP")]
    if len(transformed)!=21 or any(not math.isfinite(v) for v in transformed):raise Stop("TRANSFORMATION_NONFINITE")
    perdate[date]["valid"]+=1
    result_path = ROOT / "data" / "raw" / "target" / "daily_result_list" / ("馬番順着順_" + date + ".csv")
    rows.append({"row_id":f"{date}:{rid}:{no}","date":date,"race_id":rid,"target_race_key":key,"horse_number":no,"horse_name":horse.get("horse_name"),**active,"current_buy":no in buys,"current_top5":True,"selection_error_category":("TRUE_BUY_SUCCESS" if no in buys and label["actual_top3"] else "BUY_FALSE_POSITIVE" if no in buys else "TOP5_NONBUY_MISSED" if label["actual_top3"] else "TRUE_BUY_ABSTENTION"),"actual_top3":int(bool(label["actual_top3"])),"actual_finish":label.get("actual_finish"),"valid_result":True,"source_prediction_artifact_path":str(path.relative_to(ROOT)),"source_prediction_artifact_sha256":source_sha(path),"source_result_artifact_path":str(result_path.relative_to(ROOT)),"source_result_artifact_sha256":source_sha(result_path),"source_block":"FEBRUARY_2026_ADDITIVE_TRAIN_DRY_RUN","evidence_role_note":"FROZEN_PRE_FEATURES_POST_RESULT_LABEL_ONLY","split_role":"TREATMENT_TRAIN_ONLY"})
  except Exception as exc:failures.append({"path":str(path.relative_to(ROOT)),"error":str(exc)})
 if failures:raise Stop("FEBRUARY_SOURCE_PARSE_FAILURE:"+json.dumps(failures,ensure_ascii=True))
 if len(set(race_ids))!=160:raise Stop("DUPLICATE_OR_MISSING_SOURCE_RACE")
 top5_before=sum(x["top5"] for x in perdate.values()); invalid=len(inv); pos=sum(x["actual_top3"] for x in rows); neg=len(rows)-pos
 if pos+neg!=len(rows) or top5_before-invalid!=len(rows):raise Stop("ROW_ARITHMETIC_MISMATCH")
 # Compare identity against all existing 4100 rows (base+March), not file ordering.
 with (DATA/"dataset.csv").open(encoding="utf8",newline="") as f: existing=list(csv.DictReader(f))
 if len(existing)!=4100:raise Stop("EXISTING_DATASET_V4_SIZE_MISMATCH")
 existing_ids={r["row_id"] for r in existing}; ids=[r["row_id"] for r in rows]; overlap=sorted(set(ids)&existing_ids)
 if overlap:raise Stop(f"FEBRUARY_EXISTING_TRAIN_OVERLAP:{overlap[:3]}")
 if len(set(ids))!=len(ids):raise Stop("FEBRUARY_INTERNAL_DUPLICATE_ROWS")
 fields=list(rows[0]);
 with (OUT/"dry_run_dataset.csv").open("w",encoding="utf8",newline="") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 dump("source_race_inventory.json",{"expected_source_races":160,"actual_parsed_races":len(race_ids),"missing_races":[],"duplicate_races":[],"unexpected_races":[],"source_dates":dates,"race_ids":sorted(race_ids)})
 dump("parse_integrity.json",{"status":"PASS","successfully_parsed_races":160,"failed_parse_races":0,"failures":[]})
 dump("row_inventory.json",{"source_horse_count":sum(len(load(p)["ranked_results"]) for p in files),"top5_rows_before_valid_result_filter":top5_before,"invalid_result_rows_removed":invalid,"final_train_eligible_rows":len(rows),"unique_races_represented":len(set(r["race_id"] for r in rows)),"unique_dates":len(set(r["date"] for r in rows)),"exclusions_by_exact_reason":{"valid_result=False":invalid}})
 dump("invalid_result_exclusions.json",{"count":invalid,"rows":inv});dump("label_inventory.json",{"actual_top3_positive_rows":pos,"negative_rows":neg,"arithmetic_check":pos+neg==len(rows),"label_semantics":"existing outcome() / valid_result only"});dump("venue_date_distribution.json",{"venue_distribution":dict(venues),"date_distribution":dict(perdate)})
 comp={}
 for f in FEATURES:
  vals=[r[f] for r in rows];comp[f]={**feature_source[f],"missing_count":sum(v is None for v in vals),"null_count":sum(v is None for v in vals),"non_finite_count":sum(not math.isfinite(float(v)) for v in vals if f not in GATES and f!="race_state"),"successfully_populated_row_count":len(vals)}
 if any(x["missing_count"] or x["non_finite_count"] for x in comp.values()):raise Stop("FEBRUARY_V4_FEATURE_COMPATIBILITY_STOP")
 dump("feature_completeness.json",{"status":"PASS","semantic_feature_count":20,"features":comp});dump("feature_source_map.json",feature_source)
 dump("transformation_compatibility.json",{"status":"PASS","semantic_feature_order":list(SEMANTIC),"transformed_column_order":cols,"semantic_feature_count":20,"transformed_input_count":21,"equations":"frozen Model-v4 matrix(): gate booleans -> 0/1; race_state -> is_PLAY_UNCONVERGED_4PLUS,is_SKIP; other active semantic values -> float; StandardScaler fit NOT performed.","all_transformed_values_finite":True,"february_specific_transform":False})
 base_fields=set(existing[0]); dry_fields=set(fields); relevant=set(FEATURES)|{"actual_top3","valid_result","race_id","horse_number","date","current_buy","current_top5","source_block","split_role"}
 if not relevant<=base_fields or not relevant<=dry_fields:raise Stop("FEBRUARY_SCHEMA_COMPATIBILITY_STOP")
 dump("schema_compatibility.json",{"FEBRUARY_SCHEMA_COMPATIBILITY":"PASS","modeling_relevant_columns":sorted(relevant),"base_dataset_contains_all":True,"february_contains_all":True,"allowed_differences":["date/race/horse/source identity","source block","split role"],"relative_gap":"not selected by Model v4; not required for active 20-feature dry-run"})
 dump("overlap_check.json",{"FEBRUARY_EXISTING_TRAIN_OVERLAP":0,"overlap_vs_existing_3240_validation_capable":0,"overlap_vs_march_860_train_only":0,"stable_identity":"date:race_id:horse_number"});dump("internal_duplicate_check.json",{"FEBRUARY_INTERNAL_DUPLICATE_ROWS":0,"row_count":len(rows)})
 dump("prediction_rerun_assessment.json",{"FEBRUARY_PREDICTION_RERUN_REQUIRED":"NO","reason":"All active Model-v4 features and metadata reproduced from frozen PRE artifacts using existing builder helper functions.","prediction_rerun_count":0,"probability_regeneration_count":0})
 dump("population_semantics.json",{"TRAINING_ROW_POPULATION":"Current Top5 rank<=5 AND valid_result=True","BUY_KPI_EVALUATION_RACE_POPULATION":"PLAY_CONVERGED AND Current BUY >= 1","separate_populations":True,"forbidden_filters":["BUY","race_state","replacement_depth","buy_volume","outcome pattern"]})
 dump("future_cv_design_preservation.json",{"authoritative_cv_folds":7,"control":"existing v4 training excluding fold f + March TRAIN_ONLY","treatment":"same control + February TRAIN_ONLY","validation":"fold f only","training_executed":False})
 dump("future_promotion_rule.json",{"SUPPORTED_FOR_NEXT_STAGE":"all five frozen raw-hit/rate/fold/LOFO conditions","NOT_SUPPORTED":"pooled raw hit difference <=0 OR pooled BUY_TOP3_RATE lift <=0","INCONCLUSIVE":"positive pooled gates but later conditions fail","evaluated_in_round4":False})
 dump("february_closure_preservation.json",{"FEBRUARY_FEATURE_HYPOTHESIS_GENERATION":"CLOSED_AFTER_V4_RESELECTION_RELIABILITY_DIAGNOSTIC","round4_role":"ADDITIVE_TRAIN_DATASET_COMPATIBILITY_CHECK","not_feature_discovery":True})
 dump("formal_track_preservation.json",{"V4_MODEL_V4_FORMAL_PROSPECTIVE_STATUS":"READY_FOR_FIRST_FORMAL_PRE","V4_MODEL_V3_FORMAL_PROSPECTIVE_SHADOW":"CONTINUE","CF_EVIDENCE_TRACK":"SEPARATE_AND_CONTINUING","mutation_count":0})
 after={"pre":sha(PRE/"artifact_hashes.json"),"post":sha(POST/"artifact_hashes.json"),"dataset":sha(DATA/"dataset.csv"),"model":sha(MODEL/"model.joblib"),"scaler":sha(MODEL/"scaler.joblib"),"v3":sha(V3/"artifact_hashes.json"),"v4":sha(V4/"artifact_hashes.json"),"cf":sha(CF/"protocol.json")}
 if before!=after:raise Stop("FROZEN_AUTHORITY_MUTATION")
 dump("safety.json",{"status":"PASS","model_training":0,"candidate_model_creation":0,"model_v4_mutation":0,"model_v3_mutation":0,"scaler_fit":0,"prediction_rerun":0,"probability_regeneration":0,"feature_addition":0,"feature_removal":0,"threshold_optimization":0,"buy_engine_change":0,"decision_engine_change":0,"production_change":0,"new_result_acquisition":0,"february_pre_mutation":0,"february_post_mutation":0,"v3_protocol_change":0,"v4_protocol_change":0,"cf_protocol_change":0,"authority_hashes_before_after":after,**checks})
 (OUT/"report.md").write_text(f"# February Additive Training Round 4 Dry-run\n\n- `FEBRUARY_ADDITIVE_TRAINING_DRY_RUN = COMPLETE_PENDING_INDEPENDENT_REVIEW`\n- 160 source races; {len(rows)} valid Top5 training rows; {pos} positive / {neg} negative.\n- Model/scaler fitting and Prediction rerun were not executed.\n",encoding="utf8")
 hs={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"};dump("artifact_hashes.json",{"self_hash_excluded":True,"indexed_artifacts":hs})
 if any(sha(OUT/n)!=h for n,h in hs.items()):raise Stop("ARTIFACT_HASH_MISMATCH")
 print("FEBRUARY_ADDITIVE_TRAINING_DRY_RUN=COMPLETE_PENDING_INDEPENDENT_REVIEW")
if __name__=="__main__":main()
