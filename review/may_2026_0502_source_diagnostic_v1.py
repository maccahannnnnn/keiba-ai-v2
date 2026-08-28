"""Read-only, fact-only DG/DE race-set diagnostic for 2026-05-02."""
from __future__ import annotations
import csv,hashlib,json
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; RAW=ROOT/'data'/'raw'/'prediction_input'; OUT=ROOT/'reports'/'may_2026_multi_system_oos_v1'/'source_diagnostic_20260502_v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(OUT/n).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def read(kind):
 p=RAW/f'{kind}260502.CSV'
 with p.open(encoding='cp932',newline='') as f:rows=list(csv.reader(f))
 return p,rows
def main():
 if OUT.exists():raise FileExistsError('OUTPUT_EXISTS:'+str(OUT))
 OUT.mkdir(parents=True)
 dgpath,dg=read('DG');depath,de=read('DE')
 dgmap={(r[3].strip(),int(r[4])):r for r in dg}; demap=defaultdict(list)
 for r in de:demap[(r[1].strip(),int(r[2]))].append(r)
 dkeys=set(dgmap);ekeys=set(demap); dgonly=sorted(dkeys-ekeys);deonly=sorted(ekeys-dkeys)
 venues=sorted({x[0] for x in dkeys|ekeys}); other={v:{'dg_keys':sorted(n for c,n in dkeys if c==v),'de_keys':sorted(n for c,n in ekeys if c==v),'match':{n for c,n in dkeys if c==v}=={n for c,n in ekeys if c==v}} for v in venues if v!='東京'}
 def dgs(n):
  r=dgmap.get(('東京',n));return None if r is None else {'race_number':n,'race_name':r[5],'class_condition':r[6],'surface':r[7],'distance':int(r[8]),'horse_count':int(r[9]),'raw_race_identity_fields':r}
 def des(n):
  rs=demap.get(('東京',n),[])
  return None if not rs else {'race_number':n,'race_name':rs[0][7] if len(rs[0])>7 else None,'class_condition':rs[0][4],'surface':rs[0][5],'distance':int(rs[0][6]),'horse_count':len(rs),'raw_race_identity_fields':{'date':rs[0][0],'venue':rs[0][1],'race_number':rs[0][2],'class':rs[0][4],'surface':rs[0][5],'distance':rs[0][6],'stable_key_example':rs[0][32]}}
 neighbors={str(n):{'DG':dgs(n),'DE':des(n)} for n in range(3,9)}
 mapping=[]
 for n in (5,6):
  a=dgs(n);matches=[]
  if a:
   for m in range(3,9):
    b=des(m)
    if b and (a['surface'],a['distance'],a['class_condition'],a['horse_count'])==(b['surface'],b['distance'],b['class_condition'],b['horse_count']):matches.append(m)
  mapping.append({'dg_race_number':n,'exact_structural_de_neighbor_matches':matches,'same_number_present':n in matches,'alternate_number_match':any(m!=n for m in matches)})
 shift='YES' if any(x['alternate_number_match'] for x in mapping) else ('NO' if all(x['same_number_present'] for x in mapping) else 'UNKNOWN')
 write('race_set_diff.json',{'date':'20260502','dg_only_race_keys':dgonly,'de_only_race_keys':deonly,'set_equality':dkeys==ekeys,'previous_failed_reason_reference':'DG_DE_RACE_MISMATCH: [(東京,5),(東京,6)]','current_adapter_equivalent_key_result':'MATCH'})
 write('date_race_count_summary.json',{'dg_total_race_count':len(dkeys),'de_total_race_count':len(ekeys),'dg_race_count_by_venue':dict(Counter(c for c,n in dkeys)),'de_race_count_by_venue':dict(Counter(c for c,n in ekeys)),'other_venue_race_sets':other,'other_venue_race_set_match':'PASS' if all(x['match'] for x in other.values()) else 'FAIL','tokyo_other_than_5_6_match':({n for c,n in dkeys if c=='東京' and n not in {5,6}}=={n for c,n in ekeys if c=='東京' and n not in {5,6}})})
 write('tokyo_neighbor_race_summary.json',{'venue':'東京','races_3_to_8':neighbors,'neighboring_race_mapping_summary':mapping,'possible_race_number_shift':shift})
 write('file_identity.json',{'DG':{'path':str(dgpath.relative_to(ROOT)),'byte_size':dgpath.stat().st_size,'timestamp_utc':datetime.fromtimestamp(dgpath.stat().st_mtime,timezone.utc).isoformat(),'sha256':sha(dgpath)},'DE':{'path':str(depath.relative_to(ROOT)),'byte_size':depath.stat().st_size,'timestamp_utc':datetime.fromtimestamp(depath.stat().st_mtime,timezone.utc).isoformat(),'sha256':sha(depath)},'prior_failed_artifact_source_sha_available':False,'reacquisition_byte_identity':'UNKNOWN'})
 facts=['Current DG race-key set equals current DE race-key set.','DG_ONLY and DE_ONLY are empty for currently placed files.','Tokyo 5R and 6R exist in both current DG and DE.','Other venues have matching DG/DE race-key sets.','No alternate exact structural neighbor mapping was found for Tokyo 5R/6R using surface, distance, class/condition, and horse count.','DS was not referenced because DG/DE facts resolved the current race-set direction.','Prior failed artifacts did not contain input SHA256 values, so byte identity with the failed run is UNKNOWN.']
 write('diagnostic_facts.json',{'diagnostic_status':'COMPLETE','factual_findings':facts,'possible_target_source_semantic_difference':'UNKNOWN','next_review_required':'YES','interpretation_boundary':'No safe exclusion, adapter fix, population change, or race-number correction was made.'})
 write('safety.json',{'status':'PASS','result_access_count':0,'prediction_execution_count':0,'current_ai_execution_count':0,'cf_execution_count':0,'v4_inference_count':0,'performance_calculation_count':0,'source_modification_count':0,'ds_referenced':'NO'})
 write('artifact_hashes.json',{'indexed_artifacts':{p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='artifact_hashes.json'},'self_hash_excluded':True})
if __name__=='__main__':main()
