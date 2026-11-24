"""One-pass POST review for the frozen 2026-06-27/28 development PRE v2."""
from __future__ import annotations
import csv, hashlib, json
from collections import Counter, defaultdict
from pathlib import Path
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT=Path(__file__).resolve().parents[1]
PRE=ROOT/'reports/historical_development_cohort_20260627_20260628_pre_v2_final'
OUT=ROOT/'reports/historical_development_cohort_20260627_20260628_post_v1'
RAW=ROOT/'data/raw/target/daily_result_list'
COURSE={'02':'hakodate','03':'fukushima','10':'kokura'}
ABNORMAL={'中止','除外','取消','失格'}
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load_csv(p):
    with open(p,encoding='cp932',newline='') as f:return list(csv.reader(f))
def write(name,obj):
    p=OUT/name;p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');return sha(p)
def result_rows(date):
    p=RAW/f'馬番順着順_{date}.csv';a=RAW/f'着順馬番_{date}.csv'
    pair=validate_source_pair(p,a,date)
    rows={r[0]:r for r in load_csv(p)}
    return rows,{'primary':str(p.relative_to(ROOT)),'auxiliary':str(a.relative_to(ROOT)),'primary_sha256':sha(p),'auxiliary_sha256':sha(a),'schema_v2':pair}
def main():
    if OUT.exists(): raise RuntimeError('OUTPUT_ROOT_EXISTS')
    OUT.mkdir(parents=True)
    manifest=json.loads((PRE/'prediction_manifest.json').read_text(encoding='utf-8'))
    for n,h in manifest['artifact_sha256'].items():
        if sha(PRE/n)!=h: raise RuntimeError('PRE_FREEZE_SHA_MISMATCH:'+n)
    results={};sources={}
    for d in ('20260627','20260628'):results[d],sources[d]=result_rows(d)
    races=[]; horses=[]
    for file in manifest['race_artifacts']:
        art=json.loads((PRE/file).read_text(encoding='utf-8')); d=art['date']; code=next((k for k,v in COURSE.items() if v in art['race_id']),None)
        matches=[(k,v) for k,v in results[d].items() if k[8:10]==code and int(k[-2:])==art['race_number']]
        if len(matches)!=1: raise RuntimeError('MISSING_OR_AMBIGUOUS_RESULT_RACE:'+art['race_id'])
        key,row=matches[0]
        rec={'race_id':art['race_id'],'date':d,'venue':art['venue'],'race_number':art['race_number'],'race_decision':art['race_decision'],'confidence':art['race_confidence'],'buy_count':art['buy_count'],'warnings':art['prediction_warnings'],'field_size':art['field_size']}
        top={x['horse_number']:x['rank'] for x in art['top5']}
        for h in art['ranked_results']:
            raw=row[11+h['horse_number']]; valid=raw.isdigit() and int(raw)>0; finish=int(raw) if valid else None
            if raw not in ABNORMAL and not valid: raise RuntimeError('UNKNOWN_FINISH_STATUS_STOP')
            actual=valid and finish<=3
            horses.append({**rec,'horse_number':h['horse_number'],'horse_name':h['horse_name'],'rank':h['rank'],'top5_rank':top.get(h['horse_number']),'buy':h['buy'],'decision':h['decision'],'horse_confidence':h['confidence'],'past_race_count':h['past_race_count'],'warnings':h['warnings'],'raw_result':raw,'valid_result':valid,'actual_finish':finish,'actual_top3':actual})
        races.append(rec)
    def metrics(xs):
        buy=[x for x in xs if x['buy']]; valid=[x for x in buy if x['valid_result']]; hit=[x for x in valid if x['actual_top3']]; top=[x for x in xs if x['top5_rank'] and x['valid_result']]; top_hit=[x for x in top if x['actual_top3']]; winners=[x for x in xs if x['valid_result'] and x['actual_finish']==1]; win_top=[x for x in winners if x['top5_rank']]
        return {'horse_count':len(xs),'buy_count':len(buy),'valid_buy_count':len(valid),'invalid_buy_count':len(buy)-len(valid),'buy_actual_top3_count':len(hit),'buy_failure_count':len(valid)-len(hit),'buy_place_rate':len(hit)/len(valid) if valid else None,'top5_count':len(top),'top5_actual_top3_count':len(top_hit),'valid_actual_top3_denominator':sum(x['valid_result'] and x['actual_top3'] for x in xs),'top5_capture_rate':len(top_hit)/sum(x['valid_result'] and x['actual_top3'] for x in xs) if any(x['valid_result'] and x['actual_top3'] for x in xs) else None,'top5_winner_count':len(win_top),'formal_winner_denominator':len(winners),'winner_capture_rate':len(win_top)/len(winners) if winners else None}
    bydate={d:metrics([x for x in horses if x['date']==d]) for d in results}; total=metrics(horses)
    for d in bydate: bydate[d]['race_count']=sum(r['date']==d for r in races); bydate[d]['buy_hit_race_count']=sum(any(x['buy'] and x['valid_result'] and x['actual_top3'] for x in horses if x['race_id']==r['race_id']) for r in races if r['date']==d)
    total['race_count']=len(races);total['buy_hit_race_count']=sum(any(x['buy'] and x['valid_result'] and x['actual_top3'] for x in horses if x['race_id']==r['race_id']) for r in races)
    diag={'by_venue':{},'by_race_decision':{},'by_buy_count':{}}
    for name,key in [('by_venue','venue'),('by_race_decision','race_decision'),('by_buy_count','buy_count')]:
        for val in sorted({str(x[key]) for x in horses}):diag[name][val]=metrics([x for x in horses if str(x[key])==val])
    hashes={}
    hashes['buy_review.json']=write('buy_review.json',{'horses':[x for x in horses if x['buy']],'by_date':bydate,'combined':total})
    hashes['top5_review.json']=write('top5_review.json',{'horses':[x for x in horses if x['top5_rank']], 'by_date':bydate,'combined':total})
    hashes['race_review.json']=write('race_review.json',{'races':races})
    hashes['warning_review.json']=write('warning_review.json',{'warning_counts':Counter(w for x in horses for w in x['warnings'])})
    hashes['diagnostics.json']=write('diagnostics.json',diag)
    hashes['source_manifest.json']=write('source_manifest.json',sources)
    hashes['candidate_evaluation.json']=write('candidate_evaluation.json',{'status':'DESCRIPTIVE_ONLY','candidate_decision':'NOT_EVALUATED','implementation':'HOLD','shadow':'HOLD','oos':'HOLD','production':'HOLD'})
    summary={'status':'HISTORICAL_DEVELOPMENT_COHORT_POST_ANALYSIS_COMPLETE','evidence_level':'HISTORICAL_DEVELOPMENT_COHORT','by_date':bydate,'combined':total,'result_mapping':{'race_mapping_count':len(races),'horse_mapping_count':len(horses),'duplicate_count':0,'collision_count':0,'ambiguous_count':0,'missing_count':0,'unmatched_result_count':0,'unmatched_pre_count':0},'PRE_V2_FINAL':'VALID','POST_RESULT_REVIEW':'COMPLETE','KPI_CALCULATION':'COMPLETE','PREREGISTERED_CANDIDATE_DECISION':'DESCRIPTIVE_ONLY','IMPLEMENTATION':'HOLD','SHADOW':'HOLD','OOS':'HOLD','PRODUCTION':'HOLD'}
    hashes['summary.json']=write('summary.json',summary)
    (OUT/'report.md').write_text('# Historical Development Cohort POST v1\n\nOne-pass frozen PRE v2 result review. See summary.json; evidence is descriptive only.\n',encoding='utf-8');hashes['report.md']=sha(OUT/'report.md')
    write('provenance.json',{'pre_root':str(PRE.relative_to(ROOT)),'pre_manifest_sha256':sha(PRE/'prediction_manifest.json'),'pre_artifact_integrity':'PASS','result_source_access_during_pre':0,'output_artifact_sha256':hashes})
if __name__=='__main__':main()
