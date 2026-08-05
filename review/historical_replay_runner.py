"""Dedicated isolated CURRENT_CODE_REPLAY runner. Never consumes results in PRE."""
from __future__ import annotations
import argparse,hashlib,json,platform,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from evaluation.target_trial_adapter import TargetTrialAdapter
from review.historical_replay_asset_locator import discover
from review.historical_replay_ledger import entry as ledger_entry,save as save_ledger
from review.historical_replay_post_race import join as post_join,sha
from review.ranking_provenance_exporter import PIPELINE_VERSION,export,write_weight_source

ROOT=Path(__file__).resolve().parents[1];VERSION="HR_V1"
SMOKE_RACES=("race_20260606_hanshin_10R","race_20260711_kokura_7R","race_20260802_niigata_6R")
PHASE_LIMITS={"PHASE1_SMOKE":3,"PHASE2_ONE_DAY":10,"PHASE2_REPRODUCTION":6,"PHASE3_PILOT":20,"PHASE4_FULL":0}
SOURCE_FILES=("review/historical_replay_runner.py","evaluation/target_trial_adapter.py","review/historical_replay_asset_locator.py","review/historical_replay_post_race.py","review/historical_replay_ledger.py","review/historical_replay_safety_validator.py")
RESULT_FIELDS={"actual_finish","actual_top3","actual_top5","finish_position","result","result_path","result_hash"}
def now():return datetime.now(timezone.utc).isoformat()
def write_new(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise FileExistsError(f"HISTORICAL_ARTIFACT_ALREADY_EXISTS:{path}")
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
def git(args):
    try:return subprocess.run(["git",*args],cwd=ROOT,text=True,capture_output=True,check=False).stdout.strip()
    except OSError:return "UNAVAILABLE"
def config():
    flags={"BUY_V1_RC1_ENABLED":True,"RANKING_PROVENANCE_EXPORT_ENABLED":True,"learning_phase2":False,"shadow_engine":False,"meeting_bias":"READ_ONLY","manual_track_bias":None}
    digest=hashlib.sha256(json.dumps(flags,sort_keys=True).encode()).hexdigest();return flags,digest
def horse_rows(result,race_id,date):
    rows=[]
    for item in result.get("ranked_results") or result.get("results") or []:
        row=dict(item);row.update({"race_id":race_id,"race_date":date,"racecourse":race_id.split("_")[2],"race_number":race_id.split("_")[3],"source_version":VERSION,"pipeline_version":PIPELINE_VERSION,"ai_rank":item.get("rank") or item.get("ai_rank")});rows.append(row)
    return rows
def load_asset_manifest(path):
    source=Path(path);payload=json.loads(source.read_text(encoding="utf-8"))
    required={"run_id","phase","race_ids","max_races","allowed_dates"}
    if not required.issubset(payload):raise ValueError("ASSET_MANIFEST_REQUIRED_FIELDS_MISSING")
    race_ids=payload["race_ids"]
    if not isinstance(race_ids,list) or not race_ids:raise ValueError("RACE_IDS_REQUIRED")
    if len(race_ids)!=len(set(race_ids)):raise ValueError("DUPLICATE_RACE_ID")
    phase=payload["phase"];limit=PHASE_LIMITS.get(phase)
    if limit is None or phase=="PHASE4_FULL":raise ValueError("PHASE_NOT_EXECUTABLE")
    if len(race_ids)>limit or len(race_ids)>int(payload["max_races"]):raise ValueError("MAX_RACES_EXCEEDED")
    dates={x.split("_")[1] for x in race_ids if len(x.split("_"))>=4}
    if dates-set(payload["allowed_dates"]):raise ValueError("ALLOWED_DATES_VIOLATION")
    if phase=="PHASE2_ONE_DAY" and len(dates)!=1:raise ValueError("PHASE2_SINGLE_DAY_REQUIRED")
    expected={"20260613"} if phase=="PHASE2_REPRODUCTION" else dates
    if phase=="PHASE2_REPRODUCTION" and (dates!=expected or len(race_ids)!=6):raise ValueError("PHASE2_REPRODUCTION_SCOPE_MISMATCH")
    return payload
def _source_evidence(run_root,execution_command):
    snapshot=run_root/"code_snapshot";snapshot.mkdir()
    hashes={}
    for relative in SOURCE_FILES:
        source=ROOT/relative;target=snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);hashes[relative]=sha(source)
    return {"runner_source_sha256":hashes[SOURCE_FILES[0]],"target_trial_adapter_sha256":hashes[SOURCE_FILES[1]],"asset_locator_sha256":hashes[SOURCE_FILES[2]],"post_runner_sha256":hashes[SOURCE_FILES[3]],"ledger_sha256":hashes[SOURCE_FILES[4]],"safety_validator_sha256":hashes[SOURCE_FILES[5]],"source_sha256":hashes,"execution_command":execution_command,"python_version":platform.python_version(),"code_snapshot":"code_snapshot/"}
def run_manifest_file(path,execution_command=None):
    source=Path(path).resolve();manifest=load_asset_manifest(source)
    command=execution_command or f'{sys.executable} -m review.historical_replay_runner --asset-manifest "{source}"'
    return run_selection(manifest["run_id"],manifest["race_ids"],manifest["phase"],source,command)
def run_selection(run_id,race_ids,phase,asset_manifest_path=None,execution_command=""):
    assets={row["race_id"]:row for row in discover(ROOT/"data")}
    missing=[x for x in race_ids if x not in assets]
    if missing:raise ValueError(f"RACE_ID_NOT_DISCOVERED:{missing}")
    selected=[assets[x] for x in race_ids]
    if any(row["status"]!="READY" for row in selected):raise ValueError("SMOKE_ASSET_NOT_READY")
    run_root=ROOT/"reports/historical_replay_current_code"/run_id
    if run_root.exists():raise FileExistsError(f"HISTORICAL_RUN_ALREADY_EXISTS:{run_root}")
    run_root.mkdir(parents=True);flags,config_hash=config();generated=now();evidence=_source_evidence(run_root,execution_command)
    cohort={"cohort_type":"CURRENT_CODE_REPLAY","source_population":"HISTORICAL_RAW_ASSETS","baseline_membership":"EXCLUDED","comparison_baseline":"BASELINE_34_RACE_v1","comparison_baseline_usage":"REFERENCE_ONLY_NO_COMBINED_ROI","production_evidence":"NO","prospective_evidence":"NO","result_data_used_as_evaluation_input":"NO","historical_replay_version":VERSION}
    write_new(run_root/"cohort_manifest.json",cohort)
    dirty=git(["status","--short"]);run_manifest={"run_id":run_id,"phase":phase,"generated_at":generated,"python_version":platform.python_version(),"git_commit_hash":git(["rev-parse","HEAD"]),"git_status_short":dirty,"dirty_files":dirty.splitlines(),"working_tree_dirty":bool(dirty),"code_version":git(["rev-parse","HEAD"]),"pipeline_version":VERSION,"knowledge_version":"CURRENT_READ_ONLY","entry_source_directory":str(ROOT/"data"),"horses_source_directory":str(ROOT/"data"),"result_source_directory":str(ROOT/"data/results"),"feature_flag_snapshot":flags,"configuration_hash":config_hash,"race_ids":list(race_ids),**evidence}
    if asset_manifest_path:
        run_manifest["asset_manifest_path"]=str(asset_manifest_path);run_manifest["asset_manifest_sha256"]=sha(asset_manifest_path);shutil.copy2(asset_manifest_path,run_root/"asset_manifest.json")
    write_new(run_root/"run_manifest.json",run_manifest);ledger=[]
    for asset in selected:
        race_id=asset["race_id"];date=asset["race_date"];race_root=run_root/date/race_id;analysis=race_root/"analysis";rp=race_root/"ranking_provenance";analysis.mkdir(parents=True)
        paths={key:Path(value[0]) for key,value in asset["assets"].items()};adapter=TargetTrialAdapter(learning_phase2_enabled=False,shadow_buy_spec_v1_enabled=False,buy_v1_rc1_enabled=True,enable_learning_candidate_engine=False)
        result=adapter.run(str(paths["entry"]),str(paths["horses"]));rows=horse_rows(result,race_id,date)
        if any(RESULT_FIELDS.intersection(row) for row in rows):raise ValueError("RESULT_FIELD_IN_PRE")
        source=write_weight_source(rows,rp,date,VERSION,paths["entry"]);pre=export(rows,rp/"pre_race",date,VERSION,paths["entry"],provenance_source_file=source)
        pre_payload={"cohort_type":"CURRENT_CODE_REPLAY","run_id":run_id,"generated_at":generated,"code_version":run_manifest["code_version"],"pipeline_version":VERSION,"source_sha256":sha(paths["entry"]),"result_data_used_as_evaluation_input":"NO","baseline_membership":"EXCLUDED","production_evidence":"NO","configuration_hash":config_hash,"feature_flag_snapshot":flags,"horses":rows}
        pre_file=analysis/"pre_analysis.json";write_new(pre_file,pre_payload)
        freeze={"pre_race_sha256":sha(pre_file),"source_sha256":sha(source),"ranking_manifest_sha256":sha(pre["manifest_path"])};write_new(analysis/"pre_freeze.json",freeze)
        post_file,post_hash,joined=_post_with_sidecar(pre_file,freeze,paths,race_root/"post_race")
        write_new(race_root/"review"/"review.json",{"cohort_type":"CURRENT_CODE_REPLAY","race_id":race_id,"horses":joined,"post_sha256":post_hash})
        trace=int(pre["manifest"]["trace_count"]);complete=sum(row["provenance_complete"] for row in pre["summary_rows"])
        manifest={"race_id":race_id,"race_date":date,"racecourse":asset["racecourse"],"race_number":asset["race_number"],"cohort_type":"CURRENT_CODE_REPLAY","run_id":run_id,"code_version":run_manifest["code_version"],"pipeline_version":VERSION,"source_sha256":sha(paths["entry"]),"pre_race_sha256":freeze["pre_race_sha256"],"post_race_sha256":post_hash,"result_data_used_as_evaluation_input":"NO","result_joined_after_pre_race_freeze":"YES","baseline_membership":"EXCLUDED","production_evidence":"NO","feature_flag_snapshot":flags,"configuration_hash":config_hash,"entry_source_directory":str(paths["entry"].parent)};write_new(race_root/"manifest.json",manifest)
        ledger.append(ledger_entry(race_id,date,len(rows),"POST_RACE_COMPLETE",provenance_complete_count=complete,trace_count=trace,top5_boundary_tie_count=pre["manifest"]["top5_boundary_tie_count"],pre_race_sha256=freeze["pre_race_sha256"],post_race_sha256=post_hash))
        del adapter
    save_ledger(run_root/"ledger.json",run_id,ledger);summary={"run_id":run_id,"phase":phase,"status":"RUN_COMPLETE","race_count":len(ledger),"horse_count":sum(x["horse_count"] for x in ledger),"adapter_instance_count":len(ledger),"all_trace":all(x["trace_count"]==x["horse_count"]*9 for x in ledger),"entries":ledger};write_new(run_root/"summary.json",summary);return run_root,summary
def run_smoke(run_id):return run_selection(run_id,SMOKE_RACES,"PHASE1_SMOKE",execution_command=f"run_smoke({run_id!r})")
def _post_with_sidecar(pre_file,freeze,paths,output):
    if sha(pre_file)!=freeze["pre_race_sha256"]:raise ValueError("PRE_SHA256_MISMATCH")
    payload=json.loads(Path(pre_file).read_text(encoding="utf-8"))
    from review.historical_replay_post_race import read_csv
    results=read_csv(paths["horse_result"]);lookup={str(r.get("馬番") or "").strip():r for r in results};joined=[]
    for row in payload["horses"]:
        rr=lookup.get(str(row.get("horse_number") or "").strip(),{});f=str(rr.get("確定着順") or "").strip();valid=f.isdigit();x=dict(row);x.update({"actual_finish":int(f) if valid else "","actual_top3":valid and int(f)<=3,"actual_top5":valid and int(f)<=5,"valid_result":valid});joined.append(x)
    out=Path(output)/"post_joined.json";write_new(out,{"cohort_type":"CURRENT_CODE_REPLAY","result_joined_after_pre_race_freeze":"YES","pre_race_sha256":freeze["pre_race_sha256"],"race_result_path":str(paths["race_result"]),"horse_result_path":str(paths["horse_result"]),"horses":joined});return out,sha(out),joined
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--smoke",action="store_true");parser.add_argument("--run-id");parser.add_argument("--asset-manifest");args=parser.parse_args()
    if args.asset_manifest:print(run_manifest_file(args.asset_manifest)[0])
    elif args.smoke and args.run_id:print(run_smoke(args.run_id)[0])
    else:raise SystemExit("ASSET_MANIFEST_OR_SMOKE_REQUIRED")
