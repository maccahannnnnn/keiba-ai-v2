"""Frozen-V5, same-Current-volume prospective shadow; never reruns Current."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import joblib
from review.v4_model_v3_formal_prospective_day1_pre_v1 import _v4_record
ROOT=Path(__file__).resolve().parents[1]; PROTOCOL=ROOT/'docs/daily_v5_same_volume_prospective_protocol_v1.json'; MODEL=ROOT/'reports/ml_v4_buy_selection_model_v5'; DATASET=ROOT/'reports/ml_v4_buy_selection_dataset_v5'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def current_pre_target_date(current_pre_root: Path) -> str:
    """Read the target date from the frozen artifact itself, never its path."""
    provenance = current_pre_root / 'provenance.json'
    if not provenance.is_file():
        raise RuntimeError('STOP_CURRENT_PRE_TARGET_DATE_MISSING')
    target_date = json.loads(provenance.read_text(encoding='utf-8')).get('target_date')
    if not isinstance(target_date, str) or len(target_date) != 8 or not target_date.isdigit():
        raise RuntimeError('STOP_CURRENT_PRE_TARGET_DATE_MISSING')
    return target_date

def assert_current_pre_target_date(date: str, current_pre_root: Path) -> None:
    if date != current_pre_target_date(current_pre_root):
        raise RuntimeError('STOP_CURRENT_PRE_TARGET_DATE_MISMATCH')

def load_assets():
 p=json.loads(PROTOCOL.read_text(encoding='utf-8')); a=p['assets']; paths={'model_sha256':MODEL/'model.joblib','scaler_sha256':MODEL/'scaler.joblib','transform_schema_sha256':MODEL/'feature_transform_schema.json','dataset_sha256':DATASET/'dataset.csv'}
 if any(sha(paths[k])!=a[k] for k in paths): raise RuntimeError('STOP_V5_ASSET_SHA_MISMATCH')
 return joblib.load(paths['model_sha256']),joblib.load(paths['scaler_sha256']),p
def run(date:str,current_pre_root:Path,output_root:Path)->Path:
 if date<'20260926': raise RuntimeError('STOP_EVIDENCE_START_BOUNDARY')
 if output_root.exists(): raise RuntimeError('STOP_OUTPUT_EXISTS')
 assert_current_pre_target_date(date,current_pre_root)
 model,scaler,protocol=load_assets(); manifest=json.loads((current_pre_root/'prediction_manifest.json').read_text(encoding='utf-8'))
 for x in manifest['files']:
  if sha(current_pre_root/x['relative_path'])!=x['sha256']: raise RuntimeError('STOP_CURRENT_PRE_MANIFEST_MISMATCH')
 records=[]
 for item in json.loads((current_pre_root/'race_index.json').read_text(encoding='utf-8'))['race_index']:
  payload=json.loads((current_pre_root/item['artifact']).read_text(encoding='utf-8')); rec=_v4_record(date=date,payload=payload,model=model,scaler=scaler)
  rec['field_size']=len(payload['ranked_results'])
  if rec['current_buy_count'] and rec['race_state']!='PLAY_CONVERGED': rec['scope_status']='NOT_COMPARABLE'; rec['not_comparable_reason']='CURRENT_BUY_NON_PLAY_CONVERGED'
  if rec['scope_status']=='ELIGIBLE' and rec['selected_count']!=rec['current_buy_count']: raise RuntimeError('STOP_TARGET_K_MISMATCH')
  current={int(x['horse_number']) for x in payload['ranked_results'] if x.get('buy') is True}; chosen={int(x['horse_number']) for x in rec['selected_horses']}; rec['difference_trace']={'current_selected':sorted(current),'daily_v5_selected':sorted(chosen),'common':sorted(current&chosen),'current_only':sorted(current-chosen),'daily_v5_only':sorted(chosen-current)}; records.append(rec)
 output_root.mkdir(parents=True); out={'status':'SUCCESS','date':date,'protocol_sha256':sha(PROTOCOL),'model_family':'V5_FAMILY','production_authorization':False,'source_current_pre_manifest_sha256':sha(current_pre_root/'prediction_manifest.json'),'races':records,'result_data_access_count':0}; (output_root/'selection.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); (output_root/'SUCCESS').write_text(json.dumps({'status':'SUCCESS','result_data_access_count':0})+'\n'); return output_root
