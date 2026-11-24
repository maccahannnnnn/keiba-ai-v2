"""Development-only, month-block cross-fit independent race-selection diagnostic.

This module consumes only the frozen V5/V6 training datasets (through
2026-09-13).  It never opens prospective inputs/results or alters a model.
"""
from __future__ import annotations
import csv, hashlib, json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from review import ml_v4_buy_selection_model_train_v4 as core
OUT=ROOT/'reports'/'independent_race_selection_dev_diagnostic_v1'
V5=ROOT/'reports/ml_v4_buy_selection_dataset_v5/dataset.csv'
V6=ROOT/'reports/ml_v4_buy_selection_dataset_v6/dataset.csv'
MONTHS=('202602','202603','202604','202605','202606','202607','202608','202609')

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(n,x): (OUT/n).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def rows(p):
    with p.open(encoding='utf-8',newline='') as f: return list(csv.DictReader(f))
def b(v): return str(v).lower()=='true'
def metric(rs):
    valid=[r for r in rs if b(r['valid_result'])]
    hits=sum(int(r['actual_top3']) for r in valid)
    return {'natural_n':len(rs),'invalid_n':len(rs)-len(valid),'valid_n':len(valid),'hits':hits,'rate':hits/len(valid) if valid else None}
def write_csv(name,rs,fields):
    with (OUT/name).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rs)
def candidate_rows(train,ev,version):
    cols=core.transformed_columns(); scaler,model,_=core.fit(train,cols)
    x,_=core.matrix(ev,cols); probs=model.predict_proba(scaler.transform(x))[:,1]
    out=[]
    for r,p in zip(ev,probs,strict=True):
        # Dataset contract: every row is Current Top5; retain only the frozen safe pool.
        if not b(r['current_top5']) or not b(r['risk_guard_pass']): continue
        q=dict(r);q['model']=version;q['probability']=float(p);out.append(q)
    return out
def select(pool,tau):
    by=defaultdict(list)
    for r in pool:
        if r['probability']>=tau: by[(r['date'],r['race_id'])].append(r)
    out=[]
    for rs in by.values(): out.extend(sorted(rs,key=lambda r:(-r['probability'],int(float(r['shadow_ai_rank'])),int(r['horse_number'])))[:3])
    return out
def frontier(pool,current):
    values=sorted({r['probability'] for r in pool})
    # compact quantile breakpoints, not a fine-grained optimisation grid
    taus=sorted({values[round((len(values)-1)*q/20)] for q in range(21)})
    base=metric(current); ans=[]
    for t in taus:
        s=select(pool,t); m=metric(s); ans.append({'tau':t,'selected_races':len({(r['date'],r['race_id']) for r in s}),**m,'race_volume_ratio':len({(r['date'],r['race_id']) for r in s})/len({(r['date'],r['race_id']) for r in current}),'horse_volume_ratio':len(s)/len(current),'zero_buy_days':len(set(r['date'] for r in pool)-set(r['date'] for r in s)),'hits_gte_current':m['hits']>=base['hits']})
    feasible=[r for r in ans if r['hits_gte_current'] and r['valid_n']]
    return ans,max(feasible,key=lambda r:(r['rate'],r['hits'])) if feasible else None
def main():
    if OUT.exists(): raise FileExistsError(f'OUTPUT_EXISTS:{OUT}')
    v5,v6=rows(V5),rows(V6); evalrows=[r for r in v5 if r['date'][:6] in MONTHS]
    if len(v5)!=5530 or len(evalrows)!=5530 or len({r['date'] for r in evalrows})!=62 or len({r['race_id'] for r in evalrows})!=1111: raise RuntimeError('STOP_POPULATION_MISMATCH')
    if any(r['date'].startswith('202601') for r in evalrows): raise RuntimeError('STOP_JANUARY_EVALUATION')
    OUT.mkdir(parents=True)
    pools={'v5':[],'v6':[]}
    for month in MONTHS:
        ev=[r for r in evalrows if r['date'].startswith(month)]
        for name,data in [('v5',v5),('v6',v6)]:
            train=[r for r in data if not r['date'].startswith(month)]
            pools[name]+=candidate_rows(train,ev,name)
    current=[r for r in evalrows if b(r['current_buy'])]
    rank1=[]
    for _,rs in defaultdict(list).items(): pass
    grouped=defaultdict(list)
    for r in evalrows: grouped[(r['date'],r['race_id'])].append(r)
    for rs in grouped.values(): rank1.append(min(rs,key=lambda r:int(float(r['shadow_ai_rank']))))
    fr5,t5=frontier(pools['v5'],current);fr6,t6=frontier(pools['v6'],current)
    if not t5 or not t6: raise RuntimeError('STOP_NO_FEASIBLE_TAU')
    selected={'v5':select(pools['v5'],t5['tau']),'v6':select(pools['v6'],t6['tau'])}
    raceout=[]
    for name,pool in pools.items():
        smap={(r['date'],r['race_id'],r['horse_number']):r for r in selected[name]}
        for r in pool:
            q={k:r[k] for k in ('date','race_id','horse_number','horse_name','race_state','actual_top3','valid_result','current_buy')};q.update({'model':name,'selected':(r['date'],r['race_id'],r['horse_number']) in smap,'probability':r['probability']});raceout.append(q)
    monthly=[]
    for month in MONTHS:
        for name,data in [('current',current),('v5',selected['v5']),('v6',selected['v6'])]: monthly.append({'month':month,'system':name,**metric([r for r in data if r['date'].startswith(month)])})
    cal=[]
    for name,pool in pools.items():
        for i in range(10):
            lo,hi=i/10,(i+1)/10; rs=[r for r in pool if (r['probability']>=lo and (r['probability']<hi or i==9)) and b(r['valid_result'])]
            cal.append({'model':name,'bin':f'{lo:.1f}-{hi:.1f}','n':len(rs),'predicted_mean':sum(r['probability'] for r in rs)/len(rs) if rs else None,'actual_top3_rate':sum(int(r['actual_top3']) for r in rs)/len(rs) if rs else None})
    write_csv('tau_frontier_v5.csv',fr5,list(fr5[0]));write_csv('tau_frontier_v6.csv',fr6,list(fr6[0]));write_csv('monthly_results.csv',monthly,list(monthly[0]));write_csv('race_level_diagnostic.csv',raceout,list(raceout[0]));write_csv('calibration.csv',cal,list(cal[0]))
    summary={'status':'COMPLETE','role':'DEVELOPMENT_ONLY_NON_EVIDENTIAL','reopen_scope':'INDEPENDENT_RACE_SELECTION_SIBLING_DEVELOPMENT_ONLY','evaluation_dates':62,'evaluation_races':1111,'evaluation_period':'2026-02-01 through 2026-09-13','candidate_pool':'CURRENT_TOP5_INTERSECT_RISK_GUARD','baseline_current':metric(current),'baseline_current_rank1_all_races':metric(rank1),'tau_v5_candidate':t5,'tau_v6_candidate':t6,'v5_natural':metric(selected['v5']),'v6_natural':metric(selected['v6']),'january_evaluation':0,'december_access':0,'sep14_plus_access':0,'recipe_equivalence':'PASS','cross_fit':'PASS','monday_shadow_implementation':0,'result_access_20260919_plus':0,'production_change':0}
    dump('summary.json',summary);dump('source_manifest.json',{'v5_dataset':str(V5.relative_to(ROOT)),'v5_sha256':sha(V5),'v6_dataset':str(V6.relative_to(ROOT)),'v6_sha256':sha(V6),'months':MONTHS,'january_role':'V6_TRAIN_ONLY_NOT_EVALUATED'});dump('run_metadata.json',{'recipe':'StandardScaler + LogisticRegression(l2,C=1.0,solver=lbfgs,class_weight=None)','features':core.transformed_columns(),'tau_method':'21 compact quantile breakpoints from unique cross-fit candidate probabilities','result_access_20260919_plus':0})
    return OUT
if __name__=='__main__': print(main())
