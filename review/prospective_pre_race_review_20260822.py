"""Read frozen 2026-08-22 Prediction artifacts and render a PRE-RACE review."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'reports'/'prospective_prediction_20260822_v1'
OUT=SOURCE/'pre_race_review'
VENUES={'sapporo':'札幌','niigata':'新潟','chuukyou':'中京'}

def sha(p:Path):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def race_parts(rid):
 p=rid.split('_'); return VENUES.get(p[-2],p[-2]),int(re.sub(r'R$','',p[-1]))
def compact(row):
 return {k:row.get(k) for k in ('rank','horse_number','horse_name','adjusted_score','decision_score','decision','buy','confidence','buy_v1_rc1_candidate','buy_v1_rc1_status','buy_v1_rc1_reason','explain_summary','risks','warnings')}
def main():
 if OUT.exists():raise RuntimeError('OUTPUT_EXISTS')
 manifest=json.loads((SOURCE/'prediction_manifest.json').read_text(encoding='utf-8'))
 for item in manifest['files']:
  p=SOURCE/item['relative_path']
  if not p.exists() or sha(p)!=item['sha256']:raise RuntimeError(f'FROZEN_MANIFEST_MISMATCH:{item["relative_path"]}')
 index=json.loads((SOURCE/'race_index.json').read_text(encoding='utf-8'))['race_index']
 if len(index)!=16:raise RuntimeError(f'RACE_COUNT:{len(index)}')
 OUT.mkdir()
 races=[]; buys=[]; no_buys=[]; convergence=[]
 for item in sorted(index,key=lambda x:x['race_id']):
  payload=json.loads((SOURCE/item['artifact']).read_text(encoding='utf-8')); venue,race_no=race_parts(payload['race_id']); trace=payload.get('buy_gate_trace',{}).get('race',{})
  row={'race_id':payload['race_id'],'venue':venue,'race_number':race_no,'race_name_or_class':'NOT_SAVED_IN_FROZEN_ARTIFACT','field_size':len(payload['ranked_results']),'race_decision':payload.get('race_decision'),'race_confidence':payload.get('race_confidence'),'race_buy_count':payload.get('buy_count'),'race_convergence_state':trace.get('shadow_race_state','NOT_SAVED_IN_FROZEN_ARTIFACT'),'shadow_candidate_count':trace.get('shadow_candidate_count','NOT_SAVED_IN_FROZEN_ARTIFACT'),'trace_status':payload.get('trace_status'),'top5':[compact(x) for x in payload['top5']]}
  races.append(row)
  for x in payload['buys']:
   b=compact(x); b.update({'race_id':payload['race_id'],'venue':venue,'race_number':race_no,'race_buy_count':payload['buy_count'],'race_convergence_state':trace.get('shadow_race_state','NOT_SAVED_IN_FROZEN_ARTIFACT')}); buys.append(b)
  if payload['buy_count']==0:no_buys.append({'race_id':payload['race_id'],'venue':venue,'race_number':race_no,'top5_exists':bool(payload['top5']),'race_decision':payload.get('race_decision'),'race_convergence_state':trace.get('shadow_race_state','NOT_SAVED_IN_FROZEN_ARTIFACT'),'shadow_candidate_count':trace.get('shadow_candidate_count','NOT_SAVED_IN_FROZEN_ARTIFACT')})
  if trace.get('shadow_race_state') in {'PLAY_UNCONVERGED_4PLUS','SKIP'} or int(trace.get('shadow_candidate_count',0) or 0)>=4: convergence.append({'race_id':payload['race_id'],'venue':venue,'race_number':race_no,'race_buy_count':payload['buy_count'],'shadow_race_state':trace.get('shadow_race_state'),'shadow_candidate_count':trace.get('shadow_candidate_count'),'shadow_spec_converged':trace.get('shadow_spec_converged')})
 if len(buys)!=18:raise RuntimeError(f'BUY_COUNT:{len(buys)}')
 # Revalidate only the original frozen manifest files after producing the separate review subtree.
 for item in manifest['files']:
  if sha(SOURCE/item['relative_path'])!=item['sha256']:raise RuntimeError(f'FROZEN_SOURCE_MUTATED:{item["relative_path"]}')
 dump('race_summary.json',{'source':'frozen prospective_prediction_20260822_v1','result_data_access_count':0,'races':races})
 dump('buy_summary.json',{'source':'frozen prospective_prediction_20260822_v1','result_data_access_count':0,'buy_horse_count':len(buys),'buys':buys})
 dump('no_buy_races.json',{'source':'frozen prospective_prediction_20260822_v1','result_data_access_count':0,'no_buy_race_count':len(no_buys),'races':no_buys})
 dump('convergence_observation.json',{'source':'frozen prospective_prediction_20260822_v1','result_data_access_count':0,'observations':convergence,'boundary':'Observation only. Current frozen BUY remains authoritative; no retrospective convergence finding was applied.'})
 lines=['# 2026-08-22 Prospective PRE-RACE Review','', 'Frozen Prediction source: `reports/prospective_prediction_20260822_v1/`.', '', '## BUY summary','',f'- Frozen BUY horses: {len(buys)}','- Result-data access: 0','- Frozen source manifest integrity: PASS','', '| Venue | Race | Horse | AI rank | Adjusted | Decision score | Race BUY count | State |','|---|---:|---|---:|---:|---:|---:|---|']
 for b in buys:lines.append(f"| {b['venue']} | {b['race_number']}R | {b['horse_number']} {b['horse_name']} | {b['rank']} | {b['adjusted_score']} | {b['decision_score']} | {b['race_buy_count']} | {b['race_convergence_state']} |")
 lines += ['', '## Race review']
 for r in races:
  lines += ['',f"### {r['venue']} {r['race_number']}R — {r['race_id']}",f"- Field: {r['field_size']}; RaceDecision: {r['race_decision']}; Confidence: {r['race_confidence']}; BUY: {r['race_buy_count']}; State: {r['race_convergence_state']}; candidates: {r['shadow_candidate_count']}",'- Race name/class: NOT_SAVED_IN_FROZEN_ARTIFACT','- AI Top5:']
  for h in r['top5']:
   risk='; '.join(h['risks'] or []) or 'none saved'; lines.append(f"  - #{h['rank']} {h['horse_number']} {h['horse_name']} | adjusted {h['adjusted_score']} | decision {h['decision_score']} | {h['decision']} | risk: {risk}")
 lines += ['', '## No-BUY / convergence context', '',f'- Top5 exists and BUY=0: {len(no_buys)} races',f'- PLAY_UNCONVERGED_4PLUS / 4+ candidates / SKIP observations: {len(convergence)} races','- These are frozen runtime observations only; no rule, BUY, ranking, or convergence behavior was changed.']
 (OUT/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
if __name__=='__main__':main()
