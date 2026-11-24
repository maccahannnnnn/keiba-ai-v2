"""Build V4 TRAIN Dataset v5 by adding all newly-consumed dates to frozen v4."""
from __future__ import annotations
import csv, hashlib, json, subprocess, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from review.ml_v4_buy_selection_dataset_build_v1 import category,csv_write
from review.ml_v4_buy_selection_dataset_build_v4 import FEATURES,GAP,primary_feature_values,reference_feature_values,top5_and_buy
from review.ml_v4_buy_selection_dataset_inventory_v2 import Stop,outcome,result_for_race,result_rows,sha

PARENT=ROOT/'reports'/'ml_v4_buy_selection_dataset_v4'; OUT=ROOT/'reports'/'ml_v4_buy_selection_dataset_v5'
FEB=('20260201','20260207','20260208','20260210','20260214','20260215','20260221','20260222','20260228')
LATE=('20260822','20260823','20260829','20260830','20260905','20260906','20260912','20260913')
ADD=FEB+LATE
PRED={**{d:ROOT/'reports'/'v4_model_v4_february_historical_holdout'/'formal_pre'/'current_ai'/d for d in FEB},
 '20260822':ROOT/'reports'/'prospective_prediction_20260822_v1','20260823':ROOT/'reports'/'prospective_prediction_20260823_v1',
 '20260829':ROOT/'reports'/'prospective_prediction_20260829_v1','20260830':ROOT/'reports'/'prospective_prediction_20260830_v1',
 '20260905':ROOT/'reports'/'prospective_prediction_20260905_v1','20260906':ROOT/'reports'/'prospective_prediction_20260906_v1',
 '20260912':ROOT/'reports'/'daily_pre_prediction_20260912'/'current_frozen','20260913':ROOT/'reports'/'daily_pre_prediction_20260913'/'current_frozen'}
def dump(n,x):(OUT/n).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def tree(p):
 h=hashlib.sha256()
 for x in sorted(y for y in p.rglob('*') if y.is_file()):h.update(x.relative_to(p).as_posix().encode());h.update(sha(x).encode())
 return h.hexdigest()
def git(*a):return subprocess.run(['git',*a],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
def source_universe(dates):
 total_r=total_h=0; months=defaultdict(lambda:{'dates':0,'races':0,'horses':0}); entries=[]
 for d in dates:
  files={k:ROOT/'data'/'raw'/'prediction_input'/f'{k}{d[2:]}.CSV' for k in ('DG','DE','DS')}; files.update({'result_primary':ROOT/'data'/'raw'/'target'/'daily_result_list'/f'馬番順着順_{d}.csv','result_auxiliary':ROOT/'data'/'raw'/'target'/'daily_result_list'/f'着順馬番_{d}.csv'})
  if any(not p.is_file() for p in files.values()):raise Stop(f'SOURCE_FILE_MISSING:{d}')
  with files['result_primary'].open(encoding='cp932',newline='') as f: rr=list(csv.reader(f))
  with files['DE'].open(encoding='cp932',newline='') as f: de=list(csv.reader(f))
  races=len(rr);horses=len(de);total_r+=races;total_h+=horses;m=months[d[:6]];m['dates']+=1;m['races']+=races;m['horses']+=horses
  entries.append({'date':d,'source_races':races,'source_horses':horses,'race_count_semantics':'DAILY_RESULT_LIST_ACQUIRED_RACE_UNIVERSE','horse_count_semantics':'DE_PREDICTION_ENTRY_ROWS','files':{k:{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p),'size':p.stat().st_size} for k,p in files.items()}})
 return total_r,total_h,dict(months),entries
def main():
 if OUT.exists():raise FileExistsError(f'OUTPUT_EXISTS:{OUT}')
 protected=[ROOT/'reports'/f'ml_v4_buy_selection_dataset_v{i}' for i in range(1,5)]+[ROOT/'reports'/f'ml_v4_buy_selection_model_v{i}' for i in range(1,5)]+[ROOT/'engine',ROOT/'analyzer',ROOT/'evaluation']
 before={p.relative_to(ROOT).as_posix():tree(p) for p in protected};head=git('rev-parse','HEAD');status=git('status','--porcelain')
 with (PARENT/'dataset.csv').open(encoding='utf-8',newline='') as f:r=csv.DictReader(f);parent=list(r);fields=list(r.fieldnames or [])
 pm=json.loads((PARENT/'dataset_manifest.json').read_text(encoding='utf-8')); pv=json.loads((PARENT/'validation.json').read_text(encoding='utf-8'))
 if sha(PARENT/'dataset.csv')!='b02bb4b59b5f297e60964f96050890dbf32a7ac3b5a9ef93424b9d612e3ae80a' or len(parent)!=4100 or pv.get('status')!='PASS':raise Stop('PARENT_V4_INVALID')
 parent_dates={x['date'] for x in parent}; dates=sorted(parent_dates|set(ADD)); parent_invalid=sum(5*len({x['race_id'] for x in parent if x['date']==d})-sum(x['date']==d for x in parent) for d in parent_dates)
 if parent_invalid!=20:raise Stop(f'PARENT_INVALID_RECONSTRUCTION_FAILED:{parent_invalid}')
 if len(parent_dates)!=45 or len(dates)!=62 or parent_dates&set(ADD):raise Stop('DATE_MANIFEST_INVALID')
 sr,sh,months,sources=source_universe(dates)
 if (sr,sh)!=(2094,14890):raise Stop(f'SOURCE_UNIVERSE_MISMATCH:{sr}:{sh}')
 ids={x['row_id'] for x in parent};race_ids={x['race_id'] for x in parent};added=[];invalid=[];per=[]
 for d in ADD:
  root=PRED[d]; paths=sorted(root.glob('race_*_prediction.json'))
  if not paths:raise Stop(f'PREDICTION_SOURCE_MISSING:{d}')
  ri=result_rows(d); before_n=len(added); inv=0
  for path in paths:
   payload=json.loads(path.read_text(encoding='utf-8'));rid=payload['race_id']; top,buys,_=top5_and_buy(payload,path)
   if rid in race_ids:raise Stop(f'RACE_OVERLAP:{rid}')
   race_ids.add(rid); traces={int(x['horse_number']):x for x in payload.get('buy_gate_trace',{}).get('horses',[])};rt=payload.get('buy_gate_trace',{}).get('race',{});tk,rr=result_for_race(rid,ri);mx=max(float(x['adjusted_score']) for x in top)
   for h in top:
    no=int(h['horse_number']);o=outcome(rr,no);rowid=f'{d}:{rid}:{no}'
    if rowid in ids:raise Stop(f'DUPLICATE_ROW:{rowid}')
    ids.add(rowid)
    if not o['valid_result']:invalid.append({'date':d,'race_id':rid,'horse_number':no,'horse_name':h.get('horse_name'),'raw_status':o.get('raw_status')});inv+=1;continue
    gap=float(h['adjusted_score'])-mx; vals=primary_feature_values(h,traces.get(no),rt,gap)
    if any(v is None for v in vals.values()):raise Stop(f'FEATURE_MISSING:{rowid}')
    buy=no in buys; rec={'row_id':rowid,'date':d,'race_id':rid,'target_race_key':tk,'horse_number':no,'horse_name':h.get('horse_name'),**vals,'current_buy':buy,'current_top5':True,'selection_error_category':category(buy,bool(o['actual_top3'])),'actual_top3':int(bool(o['actual_top3'])),'actual_finish':o.get('actual_finish'),'valid_result':True,'source_prediction_artifact_path':path.relative_to(ROOT).as_posix(),'source_prediction_artifact_sha256':sha(path),'source_result_artifact_path':(ROOT/'data'/'raw'/'target'/'daily_result_list'/f'馬番順着順_{d}.csv').relative_to(ROOT).as_posix(),'source_result_artifact_sha256':sha(ROOT/'data'/'raw'/'target'/'daily_result_list'/f'馬番順着順_{d}.csv'),'source_block':'CONSUMED_ADDITIVE_TRAIN_REUSE_V5','evidence_role_note':'FROZEN_PRE_FEATURES_POST_RESULT_LABEL_ONLY','dataset_version':'ML_V4_TRAIN_DATASET_V5','split_role':'TRAIN'}
    if set(rec)!=set(fields):raise Stop(f'SCHEMA_MISMATCH:{rowid}')
    added.append(rec)
  per.append({'date':d,'prediction_root':root.relative_to(ROOT).as_posix(),'prediction_races':len(paths),'top5_before_valid':len(added)-before_n+inv,'invalid_result_excluded':inv,'trainable_rows':len(added)-before_n})
 rows=sorted([{**x,'dataset_version':'ML_V4_TRAIN_DATASET_V5'} for x in parent]+added,key=lambda x:(x['date'],x['race_id'],int(x['horse_number'])))
 if len({x['row_id'] for x in rows})!=len(rows):raise Stop('DUPLICATE_TRAINING_KEY')
 OUT.mkdir(parents=True)
 csv_write(OUT/'dataset.csv',fields,rows);csv_write(OUT/'feature_matrix.csv',['row_id',*FEATURES],[{'row_id':x['row_id'],**{k:x[k] for k in FEATURES}} for x in rows]);csv_write(OUT/'target.csv',['row_id','actual_top3'],[{'row_id':x['row_id'],'actual_top3':x['actual_top3']} for x in rows])
 cats=Counter(x['selection_error_category'] for x in rows);pos=sum(int(x['actual_top3']) for x in rows)
 dump('source_date_manifest.json',{'source_date_count':62,'source_races':sr,'source_horses':sh,'dates':dates,'monthly':months,'sources':sources,'additive_prediction_sources':per})
 dump('feature_schema.json',{'dataset_version':'ML_V4_TRAIN_DATASET_V5','base_recipe':'V4 Dataset v4','semantic_feature_order':list(FEATURES),'feature_schema_equal_v4':True,'parent_feature_schema_sha256':sha(PARENT/'feature_schema.json')})
 dump('exclusion_manifest.json',{'invalid_result_excluded_count':len(invalid)+parent_invalid,'newly_excluded_invalid_rows':invalid,'inherited_v4_invalid_excluded':parent_invalid,'inherited_invalid_reconstruction':'5 * unique parent races - valid parent rows, verified per date','integrity_excluded_training_rows':0,'integrity_excluded_source_races':[{'date':'20260823','race_id':'race_20260823_niigata_7R','source_horses':10,'reason':'SOURCE_DATA_INTEGRITY_UNRESOLVED','authority':'HUMAN_TEMPORARY_RACE_LEVEL_EXCLUSION_20260823_ONLY'}],'date_level_exclusions':0})
 summary={'status':'PASS','source_dates':62,'source_races':sr,'source_horses':sh,'trainable_rows':len(rows),'positive':pos,'negative':len(rows)-pos,'invalid_result_excluded_count':len(invalid)+parent_invalid,'integrity_excluded_training_rows':0,'duplicate_training_keys':0,'categories':dict(cats),'added_rows':len(added),'added_dates':list(ADD)};dump('dataset_summary.json',summary)
 dump('training_manifest.json',{'dataset_version':'ML_V4_TRAIN_DATASET_V5','status':'FROZEN_TRAINING_DATASET','base_dataset':'ML_V4_TRAIN_DATASET_V4','training_population_change_only':True,'source_dates':62,'source_races':sr,'source_horses':sh,'trainable_rows':len(rows),'target':'actual_top3','invalid_result_semantics':'EXCLUDED','feature_order':list(FEATURES),'dataset_sha256':sha(OUT/'dataset.csv'),'training_end_date':'2026-09-13'})
 dump('validation.json',{'status':'PASS','source_dates':62,'source_races':sr,'source_horses':sh,'duplicate_training_keys':0,'unresolved_source_mismatch':0,'feature_schema_mismatch':0,'target_semantic_mismatch':0,'invalid_result_contamination':0,'date_level_exclusions':0,'september_dates_present':{d:d in {x['date'] for x in rows} for d in ('20260905','20260906','20260912','20260913')}})
 dump('lineage.json',{'parent':'ML_V4_TRAIN_DATASET_V4','relationship':'ADDITIVE_CONSUMED_DATA_REUSE','parent_rows_preserved':4100,'added_dates':list(ADD),'february_prior_role':'TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V4','february_v5_role':'ADDITIVE_TRAIN_REUSE','prospective_roles_preserved_for_prior_models':True})
 after={p.relative_to(ROOT).as_posix():tree(p) for p in protected}
 if before!=after or git('rev-parse','HEAD')!=head:raise Stop('PROTECTED_ZERO_DELTA_FAIL')
 dump('safety.json',{'status':'PASS','protected_before':before,'protected_after':after,'git_head_before':head,'git_head_after':git('rev-parse','HEAD'),'git_status_before':status,'production_change':0,'prior_dataset_model_change':0,'prediction_execution':0})
 (OUT/'report.md').write_text(f"# V4 TRAIN Dataset v5\n\nV4 Dataset v4の特徴・target・順序を維持し、Consumed済み17日を追加しました。全62日、source {sr}レース/{sh}頭、trainable {len(rows)}行、invalid除外 {len(invalid)+parent_invalid}行です。\n",encoding='utf-8')
 dump('artifact_hash_index.json',{'self_hash_excluded':True,'indexed_artifacts':{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='artifact_hash_index.json'}})
 return OUT
if __name__=='__main__':print(main())
