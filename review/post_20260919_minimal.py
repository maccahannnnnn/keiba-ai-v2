"""One-date POST adapter for the frozen 2026-09-19 PRE artifacts only."""
from __future__ import annotations
import csv, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from review.target_daily_result_list_schema_v2_validator import validate_source_pair
DATE='20260919'; RAW=ROOT/'data/raw/target/daily_result_list'; OUT=ROOT/'reports/post_20260919_minimal'
CUR=ROOT/'reports/daily_pre_prediction_20260919/current_frozen'; DAILY=ROOT/'reports/daily_pre_prediction_20260919/current_cf_v4_reference'; FORMAL=ROOT/'reports/selection_authority_protocol_v1_v6_forward_shadow/pre/20260919'
EXPECTED={'current':'0eeb43287359cd5232ca1880683c60b1447b23d5794611c7078e7424eda7839d','daily':'734c137bd09d3375bff4ef89c6eca8a6d3951ac6326198dca03e72447c959f03','semantic':'37fafcf38d430b4ddaefe0b0004fa303f6942dc9db3a49565ad15de7b8b34410','formal_manifest':'2e93a5b15741feb83d2a2ffa759a178c4b4cd2a50072777099a68883fbfb8edf','formal_index':'c97552db930d6c93ee4f400b9ca1573293bb8e09a1fbdd80562867d9515e5bd7'}
V={'hanshin':'阪神','nakayama':'中山'}; AB={'中止','除外','取消','失格'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(n,x):(OUT/n).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def parts(r):s=r.split('_');return V[s[-2]],int(s[-1][:-1])
def outcome(row,no):
 x=row[11+int(no)].strip()
 if x.isdigit() and int(x)>0:return {'actual_finish':int(x),'valid_result':True,'actual_top3':int(x)<=3}
 if x in AB:return {'actual_finish':None,'valid_result':False,'actual_top3':False}
 raise RuntimeError('STOP_UNKNOWN_RESULT_SEMANTICS:'+x)
def metric(rows):
 a=[r for r in rows if r['valid_result']];h=sum(r['actual_top3'] for r in a)
 return {'natural_n':len(rows),'invalid_n':len(rows)-len(a),'valid_n':len(a),'hits':h,'buy_top3_rate':h/len(a) if a else None}
def main():
 if OUT.exists():raise RuntimeError('STOP_OUTPUT_ALREADY_EXISTS')
 checks={'current':sha(CUR/'prediction_manifest.json'),'daily':sha(DAILY/'artifact_hashes.json'),'semantic':sha(FORMAL/'dual_pre_semantic.json'),'formal_manifest':sha(FORMAL/'dual_pre_manifest.json'),'formal_index':sha(FORMAL/'artifact_index.json')}
 if any(checks[k]!=EXPECTED[k] for k in checks):raise RuntimeError('STOP_PRE_IDENTITY_MISMATCH')
 primary=RAW/f'馬番順着順_{DATE}.csv';aux=RAW/f'着順馬番_{DATE}.csv'; structural=validate_source_pair(primary,aux,DATE)
 if structural.get('status')!='PASS':raise RuntimeError('STOP_RESULT_SOURCE')
 with primary.open(encoding='cp932',newline='') as f: rr=list(csv.reader(f))
 index={(r[1],int(r[2])):r for r in rr}
 if len(index)!=len(rr):raise RuntimeError('STOP_RESULT_DUPLICATE_RACE')
 manifest=json.loads((CUR/'prediction_manifest.json').read_text(encoding='utf-8'))
 for x in manifest['files']:
  if sha(CUR/x['relative_path'])!=x['sha256']:raise RuntimeError('STOP_CURRENT_PRE_MUTATED')
 races={};current=[]
 for x in json.loads((CUR/'race_index.json').read_text(encoding='utf-8'))['race_index']:
  p=json.loads((CUR/x['artifact']).read_text(encoding='utf-8'));venue,rno=parts(p['race_id']);result=index.get((venue,rno))
  if not result:raise RuntimeError('STOP_RESULT_RACE_MISSING')
  by={int(h['horse_number']):h for h in p['ranked_results']}
  if len(by)!=int(result[9]):raise RuntimeError('STOP_HEADCOUNT_MISMATCH')
  races[p['race_id']]={'venue':venue,'race_number':rno,'by':by,'result':result}
  for h in by.values():
   if h.get('buy') is True:current.append({'lane':'CURRENT','race_id':p['race_id'],'venue':venue,'race_number':rno,'horse_number':int(h['horse_number']),'horse_name':h.get('horse_name'),**outcome(result,h['horse_number'])})
 def join(records,lane,key='selected_horses'):
  out=[]
  for r in records:
   for h in r.get(key,[]):
    z=races.get(r['race_id']);no=int(h['horse_number'])
    if not z or no not in z['by']:raise RuntimeError('STOP_FROZEN_SELECTION_IDENTITY')
    out.append({'lane':lane,'race_id':r['race_id'],'venue':z['venue'],'race_number':z['race_number'],'horse_number':no,'horse_name':h.get('horse_name') or z['by'][no].get('horse_name'),**outcome(z['result'],no)})
  return out
 cfdata=json.loads((DAILY/'cf_selection_manifest.json').read_text(encoding='utf-8'))['all_race_records']; cf=join([r for r in cfdata if r['shadow_eligibility']=='ELIGIBLE'],'CF','cf_selected_horses')
 ddata=json.loads((DAILY/'v4_active_model_selection_manifest.json').read_text(encoding='utf-8'))['races']; daily=join([r for r in ddata if r['scope_status']=='ELIGIBLE_PLAY_CONVERGED'],'DAILY_V5')
 fdata=json.loads((FORMAL/'dual_pre_semantic.json').read_text(encoding='utf-8'))['races']
 def formal_selection(version):
  records=[]
  for outer in fdata:
   if outer['eligible_evidence_race']:
    record=dict(outer[version])
    record['selected_horses']=[h for h in record['horses'] if h['selected_by_protocol']]
    records.append(record)
  return join(records, f'FORMAL_{version.upper()}')
 fv5=formal_selection('v5');fv6=formal_selection('v6')
 if sorted((r['race_id'],r['horse_number'],r['actual_finish']) for r in fv5)!=sorted((r['race_id'],r['horse_number'],r['actual_finish']) for r in fv6):raise RuntimeError('STOP_FORMAL_V5_V6_RESULT_MISMATCH')
 OUT.mkdir(parents=True); allrows=current+cf+daily+fv5+fv6
 with (OUT/'race_level.csv').open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['lane','venue','race_number','race_id','horse_number','horse_name','actual_finish','valid_result','actual_top3']);w.writeheader();w.writerows(allrows)
 summary={'status':'COMPLETE','result_source':'PASS','pre_identity':{'current':'PASS','daily':'PASS','formal':'PASS'},'current':metric(current),'cf':metric(cf),'daily_v5':metric(daily),'formal_v5':metric(fv5),'formal_v6':metric(fv6),'formal_v5_v6_result_equality':'PASS','current_buy_races':len({r['race_id'] for r in current}),'current_successful_buy_races':len({r['race_id'] for r in current if r['valid_result'] and r['actual_top3']}),'user_referenced_v5_6':'NOT_RECONSTRUCTABLE_FROM_ARTIFACTS','current_nonbuy_cf':[r for r in cf if r['race_id'] in {f'race_{DATE}_hanshin_10R',f'race_{DATE}_hanshin_9R',f'race_{DATE}_nakayama_8R'}],'pre_mutation':0,'model_change':0,'tau_change':0,'production_change':0,'independent_race_selection_rule_change':0,'git_commit':0,'git_push':0}
 dump('summary.json',summary);dump('source_manifest.json',{'primary':str(primary.relative_to(ROOT)),'primary_sha256':sha(primary),'auxiliary':str(aux.relative_to(ROOT)),'auxiliary_sha256':sha(aux),'schema_validation':structural,'pre_sha':checks});dump('run_metadata.json',{'date':DATE,'runner':'review/post_20260919_minimal.py','result_access':1,'prediction_rerun':0,'model_fit':0})
 dump('artifact_hashes.json',{'self_hash_excluded':True,'indexed_artifacts':{p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='artifact_hashes.json'}})
if __name__=='__main__':main()
