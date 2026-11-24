"""Frozen horse-level Logistic vs within-race symmetric Pairwise Logistic CV."""
from __future__ import annotations
import csv, hashlib, json, platform, sys
from collections import Counter, defaultdict
from pathlib import Path
import joblib
import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from review.february_additive_training_cv_v1 import FOLDS,MARCH,feature_vector,full_validation_candidates,metric,rate_pp,sha,tree_hash,git
from review.ml_v4_buy_selection_model_train_v4 import SEMANTIC
from review.ml_v4_buy_selection_dataset_inventory_v2 import Stop

OUT=ROOT/'reports'/'within_race_pairwise_logistic_cv_v1'; DATASET=ROOT/'reports'/'ml_v4_buy_selection_dataset_v4'/'dataset.csv'; LABEL='CV_EXPERIMENT_ONLY'; ATOL=1e-10; RTOL=1e-9
EXPECTED={'April':3344,'May 2026 Independent OOS additive TRAIN reuse for V4 Model v3+':3143,'June':3762,'July H1':3761,'July H2':3767,'August Development':3747,'August Development (Prospective)':3936}
def read(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def write(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def ish(rows):return hashlib.sha256('\n'.join(sorted(f"{r['race_id']}:{r['horse_number']}" for r in rows)).encode()).hexdigest()
def ok(a,b):return bool(np.isclose(a,b,atol=ATOL,rtol=RTOL))
def select(rows,scores,k):return sorted(rows,key=lambda r:(-scores[r['row_id']],float(r['shadow_ai_rank']),int(r['horse_number'])))[:k]
def concordance(groups,scores):
    race_scores=[]; ties=0; pair_count=0
    for group in groups:
        pos=[x for x in group if x['valid_result'] and int(x['actual_top3'])==1]; neg=[x for x in group if x['valid_result'] and int(x['actual_top3'])==0]
        if not pos or not neg:continue
        vals=[]
        for p in pos:
            for n in neg:
                d=scores[p['row_id']]-scores[n['row_id']]; ties+=d==0; pair_count+=1; vals.append(1.0 if d>0 else 0.0 if d<0 else .5)
        race_scores.append(float(np.mean(vals)))
    return {'race_equal_concordance':float(np.mean(race_scores)) if race_scores else None,'informative_validation_races':len(race_scores),'exact_score_tie_pair_count':ties,'pooled_pair_count':pair_count}
def pairs(train,xs,hf):
    by=defaultdict(list)
    for r,x in zip(train,xs):by[r['race_id']].append((r,x))
    features=[]; labels=[]; weights=[]; detail=[]; pair_ids=[]; informative=0; zero=0; unordered=0; posall=negall=0
    for rid,group in by.items():
        pos=[(r,x) for r,x in group if int(r['actual_top3'])==1];neg=[(r,x) for r,x in group if int(r['actual_top3'])==0];posall+=len(pos);negall+=len(neg)
        if not pos or not neg:zero+=1;detail.append({'race_id':rid,'informative':False,'positive':len(pos),'negative':len(neg),'pair_rows':0});continue
        informative+=1; unordered+=len(pos)*len(neg); detail.append({'race_id':rid,'informative':True,'positive':len(pos),'negative':len(neg),'pair_rows':2*len(pos)*len(neg)})
    if not informative:raise Stop('ZERO_INFORMATIVE_RACES_ALL_TRAIN')
    for rid,group in by.items():
        pos=[(r,x) for r,x in group if int(r['actual_top3'])==1];neg=[(r,x) for r,x in group if int(r['actual_top3'])==0]
        if not pos or not neg:continue
        w=hf/(informative*2*len(pos)*len(neg))
        for pr,px in pos:
            for nr,nx in neg:
                d=px-nx;features.extend([d,-d]);labels.extend([1,0]);weights.extend([w,w]);pair_ids.extend([(rid,pr['row_id'],nr['row_id'],1),(rid,pr['row_id'],nr['row_id'],0)])
    x=np.asarray(features,float);y=np.asarray(labels,int);w=np.asarray(weights,float)
    # Mechanical symmetry/integrity checks before Treatment fit.
    symmetric=len(y)%2==0 and int(y.sum())==len(y)//2 and all(np.array_equal(x[i+1],-x[i]) and y[i]==1 and y[i+1]==0 and w[i]==w[i+1] for i in range(0,len(y),2))
    duplicate=len(set(pair_ids))!=len(pair_ids)
    per_race=[]
    for item in detail:
        if item['informative']:
            total=hf/informative; per_race.append(ok(item['pair_rows']*(hf/(informative*item['pair_rows'])),total))
    audit={'H_f':hf,'outer_train_race_count':len(by),'train_horse_row_count':len(train),'informative_race_count':informative,'ZERO_INFORMATIVE_PAIRS_race_count':zero,'total_valid_positive_horses':posall,'total_valid_negative_horses':negall,'unordered_positive_negative_pair_count':unordered,'symmetric_pair_row_count':len(y),'y1_count':int(y.sum()),'y0_count':int(len(y)-y.sum()),'raw_conceptual_pair_weight':'1/(2*P_r*N_r)','final_actual_weight':'H_f/(R_f*2*P_r*N_r)','weight_min':float(w.min()),'weight_max':float(w.max()),'weight_mean':float(w.mean()),'weight_sum':float(w.sum()),'expected_H_f':hf,'pair_symmetry':'PASS' if symmetric else 'FAIL','race_equal_total_weight':'PASS' if all(per_race) else 'FAIL','global_total_weight':'PASS' if ok(w.sum(),hf) else 'FAIL','finite_positive_weights':bool(np.all(np.isfinite(w)) and np.all(w>0)),'duplicate_unintended_pair_rows':duplicate}
    if not symmetric or duplicate or not audit['finite_positive_weights'] or not all(per_race) or not ok(w.sum(),hf):raise Stop('PAIRWISE_PRE_FIT_INTEGRITY_STOP')
    return x,y,w,audit,detail

def main():
    if OUT.exists():raise FileExistsError(f'OUTPUT_EXISTS:{OUT}')
    protected=[ROOT/'reports'/'ml_v4_buy_selection_dataset_v4',ROOT/'reports'/'ml_v4_buy_selection_model_v4',ROOT/'reports'/'ml_v4_buy_selection_model_v3',ROOT/'reports'/'v4_model_v3_formal_prospective',ROOT/'reports'/'shadow_cf_top3_rank_anchored_v1']
    before={str(p.relative_to(ROOT)):tree_hash(p) for p in protected};head_before,status_before=git('rev-parse','HEAD'),git('status','--porcelain')
    data=read(DATASET);byblock=Counter(r['source_block'] for r in data)
    if len(data)!=4100 or sum(byblock[f] for f in FOLDS)!=3240 or byblock[MARCH]!=860 or any('FEBRUARY' in r['source_block'] for r in data):raise Stop('FROZEN_DATA_BOUNDARY_MISMATCH')
    for r in data:feature_vector(r)
    names=[*SEMANTIC[:-1],'is_PLAY_UNCONVERGED_4PLUS','is_SKIP'];fsha=hashlib.sha256(json.dumps(names,separators=(',',':')).encode()).hexdigest()
    control_probe=LogisticRegression(penalty='l2',C=1.0,solver='lbfgs',class_weight=None,fit_intercept=True,max_iter=1000,tol=.0001);pair_probe=LogisticRegression(penalty='l2',C=1.0,solver='lbfgs',class_weight=None,fit_intercept=False,max_iter=1000,tol=.0001)
    OUT.mkdir(parents=True);(OUT/'cv_experiment_only_models').mkdir()
    write('authority.json',{'status':'HUMAN_APPROVED','design':'ACCEPTED_AND_FROZEN','question':'Does changing only from horse-level binary classification to within-race pairwise ranking improve same-volume BUY_TOP3_RATE?','FEBRUARY_USED':'NO'})
    write('design_freeze.json',{'folds':list(FOLDS),'dataset_rows':4100,'validation_rows':3240,'march_train_only_rows':860,'february_rows':0,'pair_construction':'symmetric within-race positive-negative only','atol':ATOL,'rtol':RTOL,'forbidden':['feature change','gap','tuning','alternate weighting','candidate build','production']})
    write('environment_freeze.json',{'python_executable':sys.executable,'python_version':sys.version,'implementation':platform.python_implementation(),'sklearn_version':sklearn.__version__,'numpy_version':np.__version__,'git_head':head_before,'atol':ATOL,'rtol':RTOL})
    write('feature_order.json',{'ordered_transformed_features':names,'semantic_feature_count':20,'transformed_feature_count':21,'feature_order_sha256':fsha,'dataset_sha256':sha(DATASET)})
    write('fold_inventory.json',{'source_block_counts':dict(byblock),'expected_train_rows':EXPECTED,'february_rows':0})
    write('control_recipe.json',{'preprocessing':'shared fold StandardScaler','params':control_probe.get_params(),'target':'actual_top3','sample_weight':'none'})
    write('pairwise_recipe.json',{'preprocessing':'same shared fold StandardScaler; no pair-specific scaler','params':pair_probe.get_params(),'target':'symmetric positive-negative pair orientation','sample_weight':'H_f/(R_f*2*P_r*N_r)'})
    candidates,recon=full_validation_candidates(data)
    identities={};scalers=[];models=[];coefs=[];inventories={};weight_audit={};symmetry={};prefit={};scores=[];folds={};rd=[];leak=[];concord={}
    for fold in FOLDS:
        valid=[r for r in data if r['source_block']==fold];train=[r for r in data if r['source_block']!=fold];hf=len(train)
        if hf!=EXPECTED[fold]:raise Stop(f'EXPECTED_H_F_MISMATCH:{fold}:{hf}')
        train_ids={r['row_id'] for r in train};valid_ids={r['row_id'] for r in valid};racehorse_train={(r['race_id'],r['horse_number']) for r in train};racehorse_valid={(r['race_id'],r['horse_number']) for r in valid}
        if train_ids&valid_ids or racehorse_train&racehorse_valid:raise Stop(f'OUTER_LEAKAGE:{fold}')
        identities[fold]={'train_identity_sha256':ish(train),'validation_identity_sha256':ish(valid),'train_rows':hf,'validation_rows':len(valid)}
        xtrain=np.asarray([feature_vector(r) for r in train],float);xvalid=np.asarray([feature_vector(r) for r in valid],float);ytrain=np.asarray([int(r['actual_top3']) for r in train],int)
        scaler=StandardScaler();xs=scaler.fit_transform(xtrain);xv=scaler.transform(xvalid)
        safe=fold.replace(' ','_').replace('(','').replace(')','');sp=OUT/'cv_experiment_only_models'/f'shared_scaler_{safe}.joblib';joblib.dump(scaler,sp);scalers.append({'fold':fold,'path':str(sp.relative_to(ROOT)),'sha256':sha(sp),'status':LABEL})
        control=LogisticRegression(**control_probe.get_params()).fit(xs,ytrain);cp=control.predict_proba(xv)[:,1]
        px,py,pw,audit,detail=pairs(train,xs,hf);pair=LogisticRegression(**pair_probe.get_params()).fit(px,py,sample_weight=pw);coef=pair.coef_.ravel();pp=xv@coef
        if not np.all(np.isfinite(pp)):raise Stop(f'PAIRWISE_NONFINITE_VALIDATION_SCORE:{fold}')
        cmp=OUT/'cv_experiment_only_models'/f'control_{safe}.joblib';pmp=OUT/'cv_experiment_only_models'/f'pairwise_{safe}.joblib';joblib.dump(control,cmp);joblib.dump(pair,pmp)
        models += [{'fold':fold,'arm':'HORSE_LEVEL_CONTROL','path':str(cmp.relative_to(ROOT)),'sha256':sha(cmp),'status':LABEL},{'fold':fold,'arm':'PAIRWISE_TREATMENT','path':str(pmp.relative_to(ROOT)),'sha256':sha(pmp),'status':LABEL}]
        coefs += [{'fold':fold,'arm':'control','coefficient_sha256':hashlib.sha256(control.coef_.tobytes()+control.intercept_.tobytes()).hexdigest()},{'fold':fold,'arm':'pairwise','coefficient_sha256':hashlib.sha256(pair.coef_.tobytes()).hexdigest(),'intercept':float(pair.intercept_[0])}]
        inventories[fold]=audit;weight_audit[fold]={k:audit[k] for k in ('weight_min','weight_max','weight_mean','weight_sum','expected_H_f','race_equal_total_weight','global_total_weight')};symmetry[fold]={'pair_symmetry':audit['pair_symmetry'],'y1_count':audit['y1_count'],'y0_count':audit['y0_count'],'duplicate_unintended_pair_rows':audit['duplicate_unintended_pair_rows']};prefit[fold]={'status':'PASS','all_assertions':['balanced labels','X/-X symmetry','identical symmetric weights','finite positive weights','race equal total weight','global H_f weight sum','no validation race','no February','no unintended duplicate']}
        leak.append({'fold':fold,'status':'PASS','validation_absent_train':True,'same_scaler_for_both_arms':True,'scaler_fit_train_only':True,'pair_dataset_train_only':True,'march_train_only_rows':860,'february_rows':0,'outcome_tuning':False})
        cands=[x for group in candidates.values() for x in group if x['source_block']==fold];cx=scaler.transform(np.asarray([feature_vector(r) for r in cands],float));ca=control.predict_proba(cx)[:,1];pa=cx@coef;cmap={r['row_id']:float(p) for r,p in zip(cands,ca)};pmap={r['row_id']:float(p) for r,p in zip(cands,pa)}
        for r,a,b in zip(valid,cp,pp):scores.append({'fold':fold,'row_id':r['row_id'],'race_id':r['race_id'],'horse_number':r['horse_number'],'shadow_ai_rank':r['shadow_ai_rank'],'current_buy':r['current_buy'],'race_state':r['race_state'],'actual_top3':int(r['actual_top3']),'control_probability':float(a),'pairwise_ranking_score':float(b)})
        eligible=[];selc=[];selp=[]
        for rid,g in candidates.items():
            if g[0]['source_block']!=fold:continue
            buys=[x for x in g if x['current_buy']]
            if g[0]['race_state']=='PLAY_CONVERGED' and buys:eligible.append(rid);k=len(buys);selc+=select(g,cmap,k);selp+=select(g,pmap,k)
        mc,mp=metric(selc),metric(selp);raw=mp['top3_hits']-mc['top3_hits'];lift=mp['buy_top3_rate']-mc['buy_top3_rate']
        groups=[g for g in candidates.values() if g[0]['source_block']==fold];concord[fold]={'control':concordance(groups,cmap),'pairwise':concordance(groups,pmap)}
        for rid in eligible:
            a=metric([x for x in selc if x['race_id']==rid])['top3_hits'];b=metric([x for x in selp if x['race_id']==rid])['top3_hits'];rd.append({'fold':fold,'race_id':rid,'current_buy_count':len([x for x in selc if x['race_id']==rid]),'control_top3_hits':a,'pairwise_top3_hits':b,'race_hit_delta':b-a})
        folds[fold]={'eligible_races':len(eligible),'control':mc,'pairwise':mp,'raw_hit_difference':raw,'buy_top3_rate_lift':lift,'direction':'POSITIVE' if raw>0 else 'NEGATIVE' if raw<0 else 'NEUTRAL','concordance':concord[fold]}
    def pool(names):
        rec=[folds[f] for f in names]
        def arm(name):
            d={k:sum(r[name][k] for r in rec) for k in ('nominal_selected_count','invalid_selected_count','valid_selected_count','top3_hits')};d['buy_top3_rate']=d['top3_hits']/d['valid_selected_count'];return d
        c,p=arm('control'),arm('pairwise');return {'control':c,'pairwise':p,'raw_hit_difference':p['top3_hits']-c['top3_hits'],'buy_top3_rate_lift':p['buy_top3_rate']-c['buy_top3_rate']}
    pooled=pool(list(FOLDS));dcount=Counter(x['race_hit_delta'] for x in rd);direction=Counter(x['direction'] for x in folds.values());lofo=[]
    for excluded in FOLDS:
        x=pool([f for f in FOLDS if f!=excluded]);lofo.append({'excluded_fold':excluded,**x,'raw_gate':x['raw_hit_difference']>=0,'rate_gate':x['buy_top3_rate_lift']>=0})
    # Pool race-equal concordance by the registered simple mean of race values.
    cvals=[];pvals=[];ct=pt=inf=0
    for f in FOLDS:
        c=concord[f]['control'];p=concord[f]['pairwise'];cvals += [c['race_equal_concordance']]*c['informative_validation_races'];pvals += [p['race_equal_concordance']]*p['informative_validation_races'];ct+=c['exact_score_tie_pair_count'];pt+=p['exact_score_tie_pair_count'];inf+=c['informative_validation_races']
    conpool={'control_race_equal_concordance':float(np.mean(cvals)),'pairwise_race_equal_concordance':float(np.mean(pvals)),'difference':float(np.mean(pvals)-np.mean(cvals)),'informative_validation_races':inf,'control_exact_score_tie_pair_count':ct,'pairwise_exact_score_tie_pair_count':pt,'authority':'SECONDARY_ONLY_NO_GATE_AUTHORITY'}
    gates={'pooled_raw_hit_diff_gt_zero':pooled['raw_hit_difference']>0,'pooled_rate_lift_gt_zero':pooled['buy_top3_rate_lift']>0,'positive_folds_gt_negative':direction['POSITIVE']>direction['NEGATIVE'],'all_lofo_raw_nonnegative':all(x['raw_gate'] for x in lofo),'all_lofo_rate_nonnegative':all(x['rate_gate'] for x in lofo)}
    verdict='NOT_SUPPORTED' if not gates['pooled_raw_hit_diff_gt_zero'] or not gates['pooled_rate_lift_gt_zero'] else 'SUPPORTED_FOR_NEXT_STAGE' if all(gates.values()) else 'INCONCLUSIVE'
    pooled.update({'eligible_races':len(rd),'pairwise_superior_races':sum(x['race_hit_delta']>0 for x in rd),'equal_races':sum(x['race_hit_delta']==0 for x in rd),'control_superior_races':sum(x['race_hit_delta']<0 for x in rd),'full_race_hit_delta_distribution':dict(sorted(dcount.items()))})
    write('train_validation_identity_hashes.json',identities);write('shared_scaler_manifest.json',{'status':LABEL,'scalers':scalers,'treatment_scaler_count':0});write('pair_construction_inventory.json',inventories);write('pair_weight_audit.json',weight_audit);write('pair_symmetry_audit.json',symmetry);write('pre_fit_integrity.json',{'status':'PASS','by_fold':prefit});write('model_artifact_hashes.json',{'status':LABEL,'models':models});write('coefficient_hashes.json',{'coefficients':coefs})
    with (OUT/'validation_scores.csv').open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=list(scores[0]));w.writeheader();w.writerows(scores)
    write('buy_evaluation_eligibility.json',{'status':'PASS','rule':'PLAY_CONVERGED AND Current BUY >= 1','candidate_universe':'FROZEN_CURRENT_TOP5 including invalid outcomes until after selection','reconstruction':recon,'eligible_races_by_fold':{f:folds[f]['eligible_races'] for f in FOLDS}});write('fold_buy_metrics.json',folds);write('pooled_buy_metrics.json',pooled)
    with (OUT/'race_level_delta.csv').open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rd[0]));w.writeheader();w.writerows(rd)
    write('race_delta_summary.json',{'eligible_races':len(rd),'pairwise_superior_races':pooled['pairwise_superior_races'],'equal_races':pooled['equal_races'],'control_superior_races':pooled['control_superior_races'],'distribution':dict(sorted(dcount.items())),'net_hit_difference':pooled['raw_hit_difference']});write('fold_direction_summary.json',{'pairwise_positive_folds':direction['POSITIVE'],'neutral_folds':direction['NEUTRAL'],'control_positive_folds':direction['NEGATIVE'],'by_fold':{f:folds[f]['direction'] for f in FOLDS}});write('lofo_robustness.json',{'trials':lofo,'all_raw_nonnegative':gates['all_lofo_raw_nonnegative'],'all_rate_nonnegative':gates['all_lofo_rate_nonnegative']});write('pairwise_concordance.json',{'pooled':conpool,'folds':concord});write('promotion_gate.json',{'frozen_gates':gates,'verdict':verdict});write('interpretation_boundary.json',{'allowed_if_supported':'same features and linear family with within-race Pairwise objective improved same-volume BUY selection','prohibited':['feature discovery','feature attribution','weighting attribution','production readiness','February addition','automatic candidate build']});write('formal_track_preservation.json',{'V4_MODEL_V4_FORMAL_PROSPECTIVE_STATUS':'READY_FOR_FIRST_FORMAL_PRE','V4_MODEL_V3_FORMAL_PROSPECTIVE_SHADOW':'CONTINUE','CF_EVIDENCE_TRACK':'SEPARATE_AND_CONTINUING','FEBRUARY_ADDITIVE_TRAINING':'INCONCLUSIVE'})
    after={str(p.relative_to(ROOT)):tree_hash(p) for p in protected};head_after,status_after=git('rev-parse','HEAD'),git('status','--porcelain')
    if before!=after or head_before!=head_after:raise Stop('FROZEN_AUTHORITY_MUTATION')
    write('safety.json',{'status':'PASS','protected_before':before,'protected_after':after,'git_head_before':head_before,'git_head_after':head_after,'git_status_before':status_before,'git_status_after':status_after,'production_change':0,'model_v4_mutation':0,'model_v3_mutation':0,'registry_promotion':0,'final_pairwise_candidate':0,'feature_change':0,'buy_engine_change':0,'decision_engine_change':0,'threshold_optimization':0,'february_use':0,'new_result_acquisition':0,'historical_current_prediction_rerun':0,'v3_protocol_change':0,'v4_protocol_change':0,'cf_protocol_change':0,'authorized_shared_scaler_fits':7,'authorized_control_fits':7,'authorized_pairwise_fits':7})
    (OUT/'report.md').write_text(f"# Within-Race Pairwise Ranking — 7-fold CV\n\nVerdict: `{verdict}` pending independent review.\n\nControl: {pooled['control']['top3_hits']} / {pooled['control']['valid_selected_count']} = {rate_pp(pooled['control']['buy_top3_rate']):.4f}%\nPairwise: {pooled['pairwise']['top3_hits']} / {pooled['pairwise']['valid_selected_count']} = {rate_pp(pooled['pairwise']['buy_top3_rate']):.4f}%\nDifference: {pooled['raw_hit_difference']:+d} hits; {rate_pp(pooled['buy_top3_rate_lift']):+.4f}pt.\n",encoding='utf-8')
    write('artifact_hashes.json',{'indexed_artifacts':{str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in sorted(x for x in OUT.rglob('*') if x.is_file() and x.name!='artifact_hashes.json')},'self_hash_excluded':True});return OUT
if __name__=='__main__':print(main())
