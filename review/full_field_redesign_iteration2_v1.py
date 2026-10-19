"""Pre-registered Iteration 2 model-family comparison (development only)."""
from __future__ import annotations

import csv, hashlib, json, math, random, subprocess, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)) if str(ROOT) not in sys.path else None
from review import full_field_redesign_iter0_retry7 as i0
from review import full_field_redesign_iteration1_completion_v1 as i1

OUT=ROOT/'reports/full_field_redesign_iteration2_v1'
ITER1=ROOT/'reports/full_field_redesign_iteration1_completion_v1'
PRE=ROOT/'reports/full_field_redesign_iter0_v1_retry6/pre_only_regeneration/shards'
PREREG=ROOT/'docs/KeibaAI_WS2_FullField_Iteration2_Preregistration_v1.md'
PREREG_SHA=ROOT/'docs/KeibaAI_WS2_FullField_Iteration2_Preregistration_v1.sha256'
MONTHS=i0.MONTHS; EVAL=MONTHS[1:]
MODELS=('CURRENT_GLOBAL','PP_ONLY_DETERMINISTIC','V5_FULL_FIELD_TRAINED','PLACKETT_LUCE','HIST_GRADIENT_BOOSTING')

class Stop(RuntimeError): pass
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p:Path,v:Any):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
def num(x:Any,label:str)->float:
    try:v=float(x)
    except Exception as e:raise Stop(f'STOP_NONNUMERIC_{label}:{x!r}') from e
    if not math.isfinite(v):raise Stop(f'STOP_NONFINITE_{label}:{x!r}')
    return v
def csvout(name:str,rows:list[dict[str,Any]],fields:list[str]):
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as h:
        w=csv.DictWriter(h,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def vector(r):return np.asarray(r['features'],dtype=float)
def ident(r):return (r['date'],r['race_id'],int(r['horse_number']))
def common(r):return (r['date'],r['race_id'],int(r['horse_number']))

def load_rows():
    pre=i0.load_pre_rows(); joined=i0.result_join(pre)
    by={ident({'date':x['date'],'race_id':x['race_id'],'horse_number':x['horse_number']}):x for x in pre}
    for r in joined:
        s=by[ident(r)];v=s['values'];r['adjusted_score']=num(v['adjusted_score'],'adjusted_score');r['past_performance']=num(v['PastPerformance'],'PastPerformance');r['shadow_ai_rank']=num(v['shadow_ai_rank'],'shadow_ai_rank')
    return joined

def valid_pl_races(rows):
    groups=defaultdict(list)
    for r in rows:groups[(r['date'],r['race_id'])].append(r)
    usable=[];excluded=[]
    for k,g in groups.items():
        good=[r for r in g if r['valid_result']]
        ordered=sorted(good,key=lambda r:r['actual_finish'] if r['actual_finish'] is not None else 999)
        top=[r for r in ordered if r['actual_finish'] in (1,2,3)]
        reason=None
        if len(good)<3:reason='VALID_FINISHERS_LT_3'
        elif len(top)!=3:reason='TOP3_UNRESOLVED'
        elif len({r['actual_finish'] for r in top})!=3:reason='TOP3_TIE'
        elif [r['actual_finish'] for r in top]!=[1,2,3]:reason='TOP3_ORDER_UNRESOLVED'
        if reason:excluded.append({'date':k[0],'race_id':k[1],'reason':reason,'field_size':len(g),'valid_finishers':len(good)})
        else:usable.append((good,[good.index(x) for x in top]))
    return usable,excluded

def pl_fit(train):
    races,excluded=valid_pl_races(train)
    if not races:raise Stop('STOP_PL_NO_TRAINING_RACES')
    scaler=StandardScaler();scaler.fit(np.vstack([vector(r) for r in train if r['valid_result']]))
    def objective(beta):
        loss=0.;grad=np.zeros(19)
        for rows,winners in races:
            x=scaler.transform(np.vstack([vector(r) for r in rows]))[:,:19];remaining=list(range(len(rows)))
            for winner in winners:
                pos=remaining.index(winner); xr=x[remaining];u=xr@beta; probs=np.exp(u-logsumexp(u));loss+=-u[pos]+logsumexp(u);grad+=-xr[pos]+probs@xr;remaining.pop(pos)
        return loss/len(races),grad/len(races)
    fit=minimize(lambda b:objective(b)[0],np.zeros(19),jac=lambda b:objective(b)[1],method='L-BFGS-B',options={'maxiter':1000,'gtol':1e-6})
    if not fit.success or not np.all(np.isfinite(fit.x)):raise Stop('PL_FAILED_NUMERICAL:'+str(fit.message))
    return scaler,fit.x,{'status':'PASS','training_races':len(races),'excluded_races':excluded,'optimizer_success':bool(fit.success),'optimizer_message':str(fit.message),'iterations':int(fit.nit),'objective':float(fit.fun),'race_state_coefficients_fixed_at_zero':True}

def pl_top3(x,beta):
    utility=x[:,:19]@beta
    if not np.all(np.isfinite(utility)):raise Stop('PL_FAILED_NUMERICAL:UTILITY')
    worth=np.exp(utility-np.max(utility));total=float(worth.sum());n=len(worth);p=np.zeros(n)
    if n<3:raise Stop('PL_FAILED_NUMERICAL:FIELD_LT_3')
    for a in range(n):
        pa=worth[a]/total
        for b in range(n):
            if b==a:continue
            pab=pa*worth[b]/(total-worth[a])
            for c in range(n):
                if c==a or c==b:continue
                q=pab*worth[c]/(total-worth[a]-worth[b]);p[a]+=q;p[b]+=q;p[c]+=q
    if not np.all(np.isfinite(p)) or abs(float(p.sum())-3)>1e-8:raise Stop('PL_FAILED_NUMERICAL:TOP3_SUM')
    return p,float(p.sum())

def worker(path:Path, fold_indices:list[int]|None=None):
    rows=load_rows();folds=i0.folds(rows);audit=[]
    selected_folds=[(i,fold) for i,fold in enumerate(folds) if fold_indices is None or i in fold_indices]
    if not selected_folds: raise Stop('STOP_WORKER_NO_FOLDS')
    output_rows=[]
    for fold_index,fold in selected_folds:
        train=[r for r in rows if r['month'] in fold['train_months'] and r['valid_result']];ev=[r for r in rows if r['month'] in fold['evaluation_months']]
        x=np.vstack([vector(r) for r in train]);y=np.asarray([int(r['actual_top3']) for r in train])
        sc=StandardScaler();v5=LogisticRegression(solver='lbfgs',penalty='l2',C=1.0,class_weight=None,max_iter=100,tol=0.0001);v5.fit(sc.fit_transform(x),y)
        hgb=HistGradientBoostingClassifier(loss='log_loss',learning_rate=.05,max_iter=200,max_depth=3,min_samples_leaf=50,l2_regularization=1.0,early_stopping=False,random_state=20261014,class_weight=None);hgb.fit(x,y)
        xe=np.vstack([vector(r) for r in ev]);pv5=v5.predict_proba(sc.transform(xe))[:,1];phgb=hgb.predict_proba(xe)[:,1]
        try:
            ps,coef,pl_audit=pl_fit(train);byrace=defaultdict(list)
            for idx,r in enumerate(ev):byrace[(r['date'],r['race_id'])].append((idx,r))
            ppl=np.zeros(len(ev));sums=[]
            for _,items in byrace.items():
                idx=[z[0] for z in items];xx=ps.transform(np.vstack([vector(z[1]) for z in items]));prob,total=pl_top3(xx,coef);ppl[idx]=prob;sums.append(total)
            pl_audit['top3_probability_sum_min']=min(sums);pl_audit['top3_probability_sum_max']=max(sums)
        except Stop as e:
            ppl=np.full(len(ev),np.nan);pl_audit={'status':'FAILED_NUMERICAL','reason':str(e)}
        for r,a,b,c in zip(ev,pv5,ppl,phgb):
            r['p_v5']=float(a);r['p_pl']=None if math.isnan(c) else float(c);r['p_hgb']=float(b)
            output_rows.append({k:r[k] for k in ('date','month','race_id','venue','race_number','horse_number','horse_name','current_rank','current_top5','current_buy','shadow_ai_rank','past_performance','adjusted_score','valid_result','actual_finish','actual_top3','p_v5','p_pl','p_hgb')})
        audit.append({'fold_index':fold_index,'fold':fold,'pl':pl_audit})
    dump(path,{'rows':output_rows,'fold_indices':[i for i,_ in selected_folds],'folds':[f for _,f in selected_folds],'pl_audit':audit})

def assemble(path:Path, shard_paths:list[Path]):
    shards=[json.loads(p.read_text(encoding='utf-8')) for p in shard_paths]
    indices=[i for s in shards for i in s['fold_indices']]
    if sorted(indices)!=list(range(7)) or len(indices)!=len(set(indices)): raise Stop('STOP_SHARD_FOLD_COVERAGE')
    rows=[r for s in shards for r in s['rows']]
    if len({ident(r) for r in rows})!=len(rows): raise Stop('STOP_SHARD_DUPLICATE_ROWS')
    dump(path,{'rows':rows,'folds':[f for s in shards for f in s['folds']],'pl_audit':[a for s in shards for a in s['pl_audit']],'assembled_from_fresh_process_fold_shards':True})

def key(r,name):
    c=common(r)
    if name=='CURRENT_GLOBAL':return (-r['adjusted_score'],-int(r['horse_number']),*c)
    if name=='PP_ONLY_DETERMINISTIC':return (-r['past_performance'],*c)
    if name=='PLACKETT_LUCE':return (-num(r['p_pl'],'p_pl'),*c)
    score='p_v5' if name in ('V5_FULL_FIELD_TRAINED','V5_TOP5_TRAINED') else 'p_hgb'
    return (-num(r[score],score),r['shadow_ai_rank'],int(r['horse_number']),*c)
def metric(sel):
    valid=[r for r in sel if r['valid_result']];h=sum(int(r['actual_top3']) for r in valid);dist=Counter(Counter((r['date'],r['race_id']) for r in sel).values())
    return {'selected_n':len(sel),'invalid_n':len(sel)-len(valid),'valid_n':len(valid),'top3_hits':h,'top3_rate':h/len(valid) if valid else None,'selected_races':len({(r['date'],r['race_id']) for r in sel}),'selection_per_race_distribution':json.dumps(dict(sorted(dist.items())))}
def brier(rows,field):
    v=[r for r in rows if r['valid_result']];p=np.asarray([r[field] for r in v],float);y=np.asarray([r['actual_top3'] for r in v],float);return float(np.mean((p-y)**2))
def auc(rows,field):
    v=[r for r in rows if r['valid_result']];p=np.asarray([r[field] for r in v]);y=np.asarray([r['actual_top3'] for r in v]);pos=y.sum();neg=len(y)-pos
    if not pos or not neg:return None
    order=np.argsort(p);rank=np.empty(len(p));rank[order]=np.arange(1,len(p)+1);return float((rank[y==1].sum()-pos*(pos+1)/2)/(pos*neg))
def boot(left,right,seed=20261014):
    ds=sorted(set(left)&set(right));rng=random.Random(seed);vals=[]
    for _ in range(10000):
        s=[rng.choice(ds) for _ in ds];a=sum(left[d]['top3_hits'] for d in s)/sum(left[d]['valid_n'] for d in s);b=sum(right[d]['top3_hits'] for d in s)/sum(right[d]['valid_n'] for d in s);vals.append(b-a)
    vals.sort();obs=sum(right[d]['top3_hits'] for d in ds)/sum(right[d]['valid_n'] for d in ds)-sum(left[d]['top3_hits'] for d in ds)/sum(left[d]['valid_n'] for d in ds)
    return {'unit':'date','seed':seed,'rounds':10000,'observed_difference':obs,'ci_95_lower':vals[249],'ci_95_upper':vals[9749]}

def main():
    if len(sys.argv)==3 and sys.argv[1]=='--worker':worker(Path(sys.argv[2]));return
    if len(sys.argv)==4 and sys.argv[1]=='--worker-fold':worker(Path(sys.argv[3]),[int(sys.argv[2])]);return
    if len(sys.argv)>=4 and sys.argv[1]=='--assemble':assemble(Path(sys.argv[2]),[Path(x) for x in sys.argv[3:]]);return
    resuming=OUT.exists()
    if resuming:
        allowed={'preregistration.json','model_config.json','split_manifest.json','daily_current_buy_budget.csv','pre_result_freeze_manifest.json'}
        if {p.name for p in OUT.iterdir()}!=allowed:raise Stop('STOP_OUTPUT_EXISTS')
    expected=PREREG_SHA.read_text(encoding='utf-8').split()[0]
    if sha(PREREG)!=expected:raise Stop('STOP_PREREGISTRATION_SHA_MISMATCH')
    # PRE-only freeze, before subprocesses can access Result files.
    pre=i0.load_pre_rows();dates=sorted({r['date'] for r in pre})
    if len(dates)!=62 or any(str(d).startswith('202512') or str(d)>='20260926' for d in dates):raise Stop('STOP_SCOPE_VIOLATION')
    budgets=[]
    for d in dates:
        rs=[r for r in pre if r['date']==d];budgets.append({'date':d,'month':d[:6],'budget_n':sum(r['values'].get('post_rc1_decision')=='BUY' for r in rs),'eligible_horses':len(rs),'eligible_races':len({r['race_id'] for r in rs})})
    if not resuming:
        OUT.mkdir(parents=True)
        dump(OUT/'preregistration.json',{'path':str(PREREG.relative_to(ROOT)),'sha256':expected,'PREREGISTRATION_FROZEN_BEFORE_TRAINING':True,'PREREGISTRATION_FROZEN_BEFORE_RESULT_ACCESS':True})
        dump(OUT/'model_config.json',{'plackett_luce':{'l2_regularization':0.0,'intercept':'NONE','race_state_coefficients':'FIXED_AT_0','optimizer':'L-BFGS-B','maxiter':1000,'gtol':1e-6,'gradient':'analytic','objective':'equal-race-weight mean top3 partial NLL','inference':'exact ordered top3 enumeration'},'hgb':{'loss':'log_loss','learning_rate':.05,'max_iter':200,'max_depth':3,'min_samples_leaf':50,'l2_regularization':1.0,'early_stopping':False,'random_state':20261014,'class_weight':None},'feature_change':False,'parameter_search':False})
        dump(OUT/'split_manifest.json',json.loads((ITER1/'split_manifest.json').read_text(encoding='utf-8')))
        csvout('daily_current_buy_budget.csv',budgets,list(budgets[0]))
        dump(OUT/'pre_result_freeze_manifest.json',{'status':'FROZEN','result_access_before_freeze':0,'pre_rows':len(pre),'pre_dates':dates,'preregistration_sha256':expected,'budget_sha256':sha(OUT/'daily_current_buy_budget.csv')})
    else:
        frozen=json.loads((OUT/'pre_result_freeze_manifest.json').read_text(encoding='utf-8'))
        if frozen.get('preregistration_sha256')!=expected or frozen.get('budget_sha256')!=sha(OUT/'daily_current_buy_budget.csv'):raise Stop('STOP_RESUME_PREFREEZE_INTEGRITY')
    tmp=ROOT/'.tmp'/'iter2_model_runs';tmp.mkdir(parents=True,exist_ok=True);a=tmp/'run_a.json';b=tmp/'run_b.json'
    if '--aggregate-existing' not in sys.argv:
        for p in (a,b):
            if p.exists():p.unlink()
            subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(p)],cwd=ROOT,check=True)
    if not a.exists() or not b.exists(): raise Stop('STOP_MISSING_DETERMINISM_RUN')
    A=json.loads(a.read_text(encoding='utf-8'));B=json.loads(b.read_text(encoding='utf-8'))
    ra={ident(r):r for r in A['rows']};rb={ident(r):r for r in B['rows']}
    if set(ra)!=set(rb):raise Stop('STOP_NONDETERMINISTIC_MODEL_OUTPUT:IDENTITIES')
    determinism={'status':'PASS','fresh_process_runs':2,'models':{}}
    for model,field in (('V5_FULL_FIELD_TRAINED','p_v5'),('PLACKETT_LUCE','p_pl'),('HIST_GRADIENT_BOOSTING','p_hgb')):
        diffs=[abs(num(ra[k][field],field)-num(rb[k][field],field)) for k in ra if ra[k][field] is not None and rb[k][field] is not None];determinism['models'][model]={'max_probability_abs_difference':max(diffs) if diffs else None,'status':'PASS'}
    rows=list(ra.values());pl_ok=all(r['p_pl'] is not None for r in rows)
    if not pl_ok:determinism['models']['PLACKETT_LUCE']['status']='FAILED_NUMERICAL'
    bydate=defaultdict(list)
    for r in rows:bydate[r['date']].append(r)
    bmap={x['date']:x['budget_n'] for x in budgets if x['month'] in EVAL};sels={m:{} for m in MODELS}
    for d,g in bydate.items():
        for m in MODELS:
            if m=='PLACKETT_LUCE' and not pl_ok:continue
            sels[m][d]=sorted(g,key=lambda r:key(r,m))[:bmap[d]]
    # exact selection/rank determinism for all executable models
    for m in ('V5_FULL_FIELD_TRAINED','HIST_GRADIENT_BOOSTING')+(() if not pl_ok else ('PLACKETT_LUCE',)):
        alt=defaultdict(list)
        for r in rb.values():alt[r['date']].append(r)
        aa=[ident(x) for d in sorted(sels[m]) for x in sels[m][d]];bb=[ident(x) for d in sorted(alt) for x in sorted(alt[d],key=lambda r:key(r,m))[:bmap[d]]]
        if aa!=bb:raise Stop('STOP_NONDETERMINISTIC_MODEL_OUTPUT:'+m)
    dump(OUT/'determinism_check.json',determinism)
    primary=[];bydate_metrics={}
    for m in MODELS:
        if m=='PLACKETT_LUCE' and not pl_ok:continue
        bydate_metrics[m]={}
        for d,s in sorted(sels[m].items()):
            q=metric(s);q.update({'comparator':m,'date':d,'month':d[:6],'budget_n':bmap[d]});primary.append(q);bydate_metrics[m][d]=q
    primary_total=[];monthly=[]
    for m in bydate_metrics:
        total=metric([x for d in sels[m] for x in sels[m][d]]);total.update({'comparator':m,'metric':'DAILY_GLOBAL_TOP_N_TOP3_RATE','date_count':len(sels[m])});primary_total.append(total)
        for mo in EVAL:
            q=metric([x for d in sels[m] if d.startswith(mo) for x in sels[m][d]]);q.update({'comparator':m,'month':mo});monthly.append(q)
    csvout('primary_metrics.csv',primary_total,list(primary_total[0]));csvout('primary_by_date.csv',primary,list(primary[0]));csvout('primary_by_month.csv',monthly,list(monthly[0]))
    # common rank1, secondary and calibration
    groups=defaultdict(list)
    for r in rows:groups[(r['date'],r['race_id'])].append(r)
    rank={m:{} for m in bydate_metrics}
    for rid,g in groups.items():
        for m in rank:rank[m][rid]=sorted(g,key=lambda r:key(r,m))[0]
    common_races=sorted(set.intersection(*(set(x) for x in rank.values())))
    rankrows=[]
    for m in rank:
        q=metric([rank[m][x] for x in common_races]);q.update({'comparator':m,'common_valid_races':len(common_races),'metric':'COMMON_VALID_RACE_SET_RANK1_TOP3_RATE'});rankrows.append(q)
    csvout('rank1_common_denominator_metrics.csv',rankrows,list(rankrows[0]))
    secondary=[]
    for m in rank:
        s=[]
        for _,g in groups.items():
            k=sum(r['current_buy'] for r in g)
            if k:s.extend([r for r in g if r['current_buy']] if m=='CURRENT_GLOBAL' else sorted(g,key=lambda r:key(r,m))[:k])
        q=metric(s);q.update({'comparator':m,'metric':'RACE_CONDITIONED_SAME_VOLUME_SECONDARY'});secondary.append(q)
    csvout('secondary_metrics.csv',secondary,list(secondary[0]))
    cal=[]
    for m,f in (('V5_FULL_FIELD_TRAINED','p_v5'),('HIST_GRADIENT_BOOSTING','p_hgb'))+( () if not pl_ok else (('PLACKETT_LUCE','p_pl'),)):
        for scope,rs in [('POOLED',rows)]+[(mo,[r for r in rows if r['month']==mo]) for mo in EVAL]:cal.append({'comparator':m,'scope':scope,'valid_n':sum(r['valid_result'] for r in rs),'auc':auc(rs,f),'brier':brier(rs,f)})
    csvout('calibration_metrics.csv',cal,list(cal[0]))
    boots={};effects=[];wlt=[];loo=[];conc={}
    base_total={r['comparator']:r for r in primary_total};month={(r['comparator'],r['month']):r for r in monthly}
    for m in ('PLACKETT_LUCE','HIST_GRADIENT_BOOSTING'):
        if m not in bydate_metrics:continue
        for ref,label in (('CURRENT_GLOBAL','CURRENT'),('PP_ONLY_DETERMINISTIC','PP'),('V5_FULL_FIELD_TRAINED','V5')):
            z=boot(bydate_metrics[ref],bydate_metrics[m]);z.update({'left':ref,'right':m});boots[f'{label}_VS_{m}']=z
            effects.append({'model':m,'reference':ref,'raw_hit_difference':base_total[m]['top3_hits']-base_total[ref]['top3_hits'],'rate_difference':base_total[m]['top3_rate']-base_total[ref]['top3_rate'],**z})
        wins=loss=ties=0;gains={}
        for mo in EVAL:
            diff=month[(m,mo)]['top3_rate']-month[('V5_FULL_FIELD_TRAINED',mo)]['top3_rate'];state='WIN' if diff>0 else 'LOSS' if diff<0 else 'TIE';wins+=state=='WIN';loss+=state=='LOSS';ties+=state=='TIE';wlt.append({'model':m,'reference':'V5_FULL_FIELD_TRAINED','month':mo,'difference':diff,'outcome':state});gains[mo]=max(0,month[(m,mo)]['top3_hits']-month[('V5_FULL_FIELD_TRAINED',mo)]['top3_hits'])
        wlt.append({'model':m,'reference':'V5_FULL_FIELD_TRAINED','month':'SUMMARY','difference':'','outcome':f'{wins}/{loss}/{ties}'});conc[m]={'positive_hit_gain_by_month':gains,'concentration_flag':bool(sum(gains.values()) and max(gains.values())/sum(gains.values())>.5)}
        for omit in EVAL:
            s=[x for d in sels[m] if not d.startswith(omit) for x in sels[m][d]];q=metric(s);q.update({'model':m,'omitted_month':omit});loo.append(q)
    dump(OUT/'paired_bootstrap.json',boots);csvout('model_family_effect.csv',effects,list(effects[0]));csvout('monthly_win_loss_tie.csv',wlt,list(wlt[0]));csvout('leave_one_month_out.csv',loo,list(loo[0]));dump(OUT/'concentration.json',conc)
    # PP overlap / simplification.
    pp=[]
    for m in ('PLACKETT_LUCE','HIST_GRADIENT_BOOSTING'):
        if m not in sels:continue
        a={ident(x) for d in sels[m] for x in sels[m][d]};b={ident(x) for d in sels['PP_ONLY_DETERMINISTIC'] for x in sels['PP_ONLY_DETERMINISTIC'][d]}
        for label,ids in [('BOTH_SELECTED',a&b),('MODEL_ONLY',a-b),('PP_ONLY',b-a)]:
            q=metric([r for r in rows if ident(r) in ids]);q.update({'model':m,'bucket':label});pp.append(q)
    csvout('pp_simplify_comparison.csv',pp,list(pp[0]))
    rankmap={r['comparator']:r for r in rankrows};calmap={(r['comparator'],r['scope']):r for r in cal};gates={}
    for m in ('PLACKETT_LUCE','HIST_GRADIENT_BOOSTING'):
        if m not in base_total:gates[m]={'status':'FAILED_NUMERICAL'};continue
        det=calmap[(m,'POOLED')]['brier']<=calmap[('V5_FULL_FIELD_TRAINED','POOLED')]['brier'] and sum(calmap[(m,mo)]['brier']>calmap[('V5_FULL_FIELD_TRAINED',mo)]['brier'] for mo in EVAL)<=len(EVAL)/3
        c=boots[f'CURRENT_VS_{m}'];p=boots[f'PP_VS_{m}'];win=sum(month[(m,mo)]['top3_rate']>month[('CURRENT_GLOBAL',mo)]['top3_rate'] for mo in EVAL)>=math.ceil(2*len(EVAL)/3);rguard=rankmap[m]['top3_rate']>=rankmap['V5_FULL_FIELD_TRAINED']['top3_rate']-.01
        cond={'lift_vs_current_6pt':base_total[m]['top3_rate']-base_total['CURRENT_GLOBAL']['top3_rate']>=.06,'monthly_current_2_3':win,'bootstrap_current_lower_gt_0':c['ci_95_lower']>0,'rank1_guard':rguard,'calibration_guard':det,'bootstrap_pp_lower_gt_0':p['ci_95_lower']>0};gates[m]={'conditions':cond,'calibration_guard':'PASS' if det else 'FAIL','complexity_not_justified':not cond['bootstrap_pp_lower_gt_0'],'status':'PASS' if all(cond.values()) else 'FAIL'}
    dump(OUT/'candidate_gate.json',gates)
    plpass=gates.get('PLACKETT_LUCE',{}).get('status')=='PASS';hpass=gates.get('HIST_GRADIENT_BOOSTING',{}).get('status')=='PASS';choice='NONE'
    if plpass and not hpass:choice='PLACKETT_LUCE'
    elif hpass and not plpass:choice='HIST_GRADIENT_BOOSTING'
    elif plpass and hpass:choice='HIST_GRADIENT_BOOSTING' if boots['PLACKETT_LUCE_VS_HIST_GRADIENT_BOOSTING']['ci_95_lower']>0 and gates['HIST_GRADIENT_BOOSTING']['calibration_guard']=='PASS' else 'PLACKETT_LUCE'
    conclusion='CANDIDATE_WORTHY' if choice!='NONE' else 'DEVELOPMENT_DIRECTIONAL_IMPROVEMENT' if any(base_total[m]['top3_rate']>base_total['V5_FULL_FIELD_TRAINED']['top3_rate'] for m in gates if m in base_total) else 'NO_MEANINGFUL_IMPROVEMENT'
    dump(OUT/'model_selection_decision.json',{'iteration2_candidate':choice,'conclusion':conclusion,'rule':'pre-registered independent gates; no winner-by-highest-rate selection'})
    dump(OUT/'research_deadline_status.json',{'legacy_start':'UNKNOWN_LEGACY_NOT_BACKFILLED','current_start':'2026-10-14','deadline':'2026-11-11','days_remaining':(date(2026,11,11)-date.today()).days,'covers':['ITERATION_2','ITERATION_3'],'automatic_renewal':False})
    lines=['# Full-field Redesign — Iteration 2','', '`DEVELOPMENT_ONLY_NON_EVIDENTIAL`','', '| Comparator | Hits / valid N | Rate |', '|---|---:|---:|']+[f"| {m} | {base_total[m]['top3_hits']} / {base_total[m]['valid_n']} | {base_total[m]['top3_rate']:.4%} |" for m in base_total]+['',f'- Candidate: `{choice}`',f'- Conclusion: `{conclusion}`', '- Production / Formal advancement: `FALSE`']
    (OUT/'summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    hashes={p.relative_to(OUT).as_posix():{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='artifact_hashes.json'};dump(OUT/'artifact_hashes.json',{'self_hash_excluded':True,'artifacts':hashes})
    print(json.dumps({'ITERATION_2_STATUS':'COMPLETE','candidate':choice,'conclusion':conclusion},ensure_ascii=False))
if __name__=='__main__':main()
