"""Train frozen-candidate V4 Model v5 with the unchanged v4 core recipe."""
from __future__ import annotations
import csv,hashlib,json,platform,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
import joblib,numpy as np,scipy,sklearn

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import review.ml_v4_buy_selection_model_train_v4 as v4

DATA=ROOT/'reports'/'ml_v4_buy_selection_dataset_v5'; OLD=ROOT/'reports'/'ml_v4_buy_selection_model_v4'; OUT=ROOT/'reports'/'ml_v4_buy_selection_model_v5'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(n,x):(OUT/n).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def tree(p):
 h=hashlib.sha256()
 for x in sorted(y for y in p.rglob('*') if y.is_file()):h.update(x.relative_to(p).as_posix().encode());h.update(sha(x).encode())
 return h.hexdigest()
def git(*a):return subprocess.run(['git',*a],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
def equal(a,b):return bool(np.array_equal(a,b))
def main():
 if OUT.exists():raise FileExistsError(f'OUTPUT_EXISTS:{OUT}')
 protected=[ROOT/'reports'/f'ml_v4_buy_selection_dataset_v{i}' for i in range(1,5)]+[ROOT/'reports'/f'ml_v4_buy_selection_model_v{i}' for i in range(1,5)]+[ROOT/x for x in ('engine','analyzer','evaluation','importer')]
 before={p.relative_to(ROOT).as_posix():tree(p) for p in protected};head=git('rev-parse','HEAD');status=git('status','--porcelain')
 # Required v4 recipe reproduction gate.
 old_rows,_=v4.load_rows();cols=v4.transformed_columns();os,om,op=v4.fit(old_rows,cols);fm=joblib.load(OLD/'model.joblib');fs=joblib.load(OLD/'scaler.joblib');ox,oy=v4.matrix(old_rows,cols);fp=fm.predict_proba(fs.transform(ox))[:,1]
 repro={'status':'PASS' if all((equal(os.mean_,fs.mean_),equal(os.scale_,fs.scale_),equal(om.coef_,fm.coef_),equal(om.intercept_,fm.intercept_),equal(op,fp))) else 'FAIL','scaler_mean_exact':equal(os.mean_,fs.mean_),'scaler_scale_exact':equal(os.scale_,fs.scale_),'coef_exact':equal(om.coef_,fm.coef_),'intercept_exact':equal(om.intercept_,fm.intercept_),'predict_proba_exact':equal(op,fp),'existing_model_sha256':sha(OLD/'model.joblib'),'existing_scaler_sha256':sha(OLD/'scaler.joblib')}
 if repro['status']!='PASS':raise RuntimeError('STOP_V4_RECIPE_REPRODUCTION_FAILED')
 dm=json.loads((DATA/'training_manifest.json').read_text(encoding='utf-8'));dv=json.loads((DATA/'validation.json').read_text(encoding='utf-8'))
 if dv.get('status')!='PASS' or (dm.get('source_dates'),dm.get('source_races'),dm.get('source_horses'))!=(62,2094,14890):raise RuntimeError('STOP_DATASET_V5_INTEGRITY_FAILED')
 with (DATA/'dataset.csv').open(encoding='utf-8',newline='') as f:r=csv.DictReader(f);rows=list(r)
 if len(rows)!=5530:raise RuntimeError('DATASET_ROW_COUNT_MISMATCH')
 OUT.mkdir(parents=True);s1,m1,p1=v4.fit(rows,cols);s2,m2,p2=v4.fit(rows,cols)
 det={'status':'PASS' if all((equal(s1.mean_,s2.mean_),equal(s1.scale_,s2.scale_),equal(m1.coef_,m2.coef_),equal(m1.intercept_,m2.intercept_),equal(p1,p2))) else 'FAIL','feature_order_exact':True,'scaler_mean_exact':equal(s1.mean_,s2.mean_),'scaler_scale_exact':equal(s1.scale_,s2.scale_),'coef_exact':equal(m1.coef_,m2.coef_),'intercept_exact':equal(m1.intercept_,m2.intercept_),'predictions_exact':equal(m1.predict(s1.transform(v4.matrix(rows,cols)[0])),m2.predict(s2.transform(v4.matrix(rows,cols)[0]))),'probabilities_exact':equal(p1,p2)}
 if det['status']!='PASS':raise RuntimeError('STOP_V5_REPRODUCTION_FAILED')
 joblib.dump(m1,OUT/'model.joblib');joblib.dump(s1,OUT/'scaler.joblib');x,y=v4.matrix(rows,cols);rm=joblib.load(OUT/'model.joblib');rs=joblib.load(OUT/'scaler.joblib')
 if not equal(p1,rm.predict_proba(rs.transform(x))[:,1]):raise RuntimeError('RELOAD_FAILED')
 core={'pipeline':['StandardScaler','LogisticRegression'],'penalty':'l2','C':1.0,'solver':'lbfgs','class_weight':None,'tuning':False,'threshold_search':False,'feature_selection_search':False}
 old_recipe=json.loads((OLD/'training_recipe.json').read_text(encoding='utf-8'))
 if any(old_recipe.get(k)!=v for k,v in core.items()):raise RuntimeError('V4_CORE_RECIPE_AUTHORITY_MISMATCH')
 runtime={'python_executable':sys.executable,'python_version':sys.version,'implementation':platform.python_implementation(),'numpy':np.__version__,'scipy':scipy.__version__,'scikit_learn':sklearn.__version__,'joblib':joblib.__version__}
 dump('v4_recipe_reproduction.json',repro);dump('deterministic_reproduction.json',det)
 dump('training_recipe.json',{**core,'base_recipe':'V4 Model v4','training_population_change_only':True,'formal_fit_count':1,'temporary_deterministic_refit_count':1})
 dump('feature_schema.json',{'model_version':'V4 Model v5','semantic_feature_order':list(v4.SEMANTIC),'semantic_feature_count':20,'dataset_v5_feature_schema_sha256':sha(DATA/'feature_schema.json'),'equal_to_v4':True})
 dump('feature_transform_schema.json',{'transformed_model_input_columns':cols,'transformed_input_count':21,'authority_v4_sha256':sha(OLD/'feature_transform_schema.json'),'equal_to_v4':True})
 dump('training_population.json',{'dataset':'ML_V4_TRAIN_DATASET_V5','dataset_sha256':sha(DATA/'dataset.csv'),'source_dates':62,'source_races':2094,'source_horses':14890,'trainable_rows':5530,'positive':int(y.sum()),'negative':int(len(y)-y.sum()),'weighting':'NONE','resampling':'NONE','training_end_date':'2026-09-13'})
 dump('runtime_environment.json',runtime)
 dump('model_metadata.json',{'version':'V4 Model v5','base_recipe':'V4 Model v4','training_population':'ML_V4_TRAIN_DATASET_V5','training_end_date':'2026-09-13','future_evidence_start':'2026-09-19','model_family':'StandardScaler + LogisticRegression(l2,C=1.0,solver=lbfgs,class_weight=None)','activation_status':'PENDING_HUMAN_APPROVAL','model_sha256':sha(OUT/'model.joblib'),'scaler_sha256':sha(OUT/'scaler.joblib')})
 dump('training_manifest.json',{'model':'V4 Model v5','status':'FROZEN_CANDIDATE_PENDING_HUMAN_APPROVAL','dataset_sha256':sha(DATA/'dataset.csv'),'rows':len(rows),'positive':int(y.sum()),'negative':int(len(y)-y.sum()),'feature_count':21,'recipe_core_equal_v4':True,'feature_schema_equal_v4':True,'v4_recipe_reproduction':'PASS','v5_reproduction':'PASS','model_sha256':sha(OUT/'model.joblib'),'scaler_sha256':sha(OUT/'scaler.joblib'),'runtime':runtime,'timestamp':datetime.now(timezone.utc).isoformat(),'git_head':head})
 dump('reload_validation.json',{'status':'PASS','training_matrix_probability_exact':True,'model_sha256':sha(OUT/'model.joblib'),'scaler_sha256':sha(OUT/'scaler.joblib')})
 after={p.relative_to(ROOT).as_posix():tree(p) for p in protected}
 if before!=after or git('rev-parse','HEAD')!=head:raise RuntimeError('ZERO_DELTA_FAILED')
 dump('safety.json',{'status':'PASS','v1_v4_artifact_before':before,'v1_v4_artifact_after':after,'PRODUCTION_RUNTIME_ZERO_DELTA':'PASS','V1_V4_ARTIFACT_ZERO_DELTA':'PASS','production_change':0,'git_commit':0,'git_push':0,'git_head_before':head,'git_head_after':git('rev-parse','HEAD'),'git_status_before':status})
 (OUT/'report.md').write_text('# V4 Model v5 学習結果\n\nV4の週次再学習Lifecycleを開始するため、V4 Model v4の特徴・前処理・LogisticRegression recipeを固定し、Consumed済み62日のDataset v5だけを変更軸として学習しました。trainable 5,530行です。V4再現とV5独立再学習は完全一致しました。ActivationはHuman承認待ちで、次の未見Prospective開始日は2026-09-19です。\n',encoding='utf-8')
 dump('artifact_hash_index.json',{'self_hash_excluded':True,'indexed_artifacts':{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='artifact_hash_index.json'}})
 return OUT
if __name__=='__main__':print(main())
