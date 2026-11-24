"""Reference tables from completed POST and frozen PRE; no selection changes."""
import json
import hashlib
from pathlib import Path
from collections import Counter
from review import small_field_place_h1_diagnostic_v2 as rules
from review.formal_post_daily_v1 import result_sources
from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/daily_post_reference_20261122'
DATE = '20261122'


def main():
    if OUT.exists():
        raise RuntimeError('STOP_OUTPUT_EXISTS')
    sources = {}
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    def load(path):
        path = Path(path)
        if not path.is_absolute():
            path = ROOT / path
        sources[str(path)] = sha(path)
        return json.loads(path.read_text(encoding='utf-8'))
    def key(h):
        return h['race_id'], int(h['horse_number'])
    comparison_path = ROOT / f'reports/pre_selection_comparison_{DATE}/comparison.json'
    if sha(comparison_path) != 'cdf5ee88a95f0e24a46204e3e0ea9228369f93aa6767ddc5df7870afccd81d1d':
        raise RuntimeError('STOP_PRE_COMPARISON_SHA')
    frozen = load(comparison_path)
    if any(sha(p) != h for p,h in frozen['sources_sha256'].items()):
        raise RuntimeError('STOP_FROZEN_SOURCE_SHA')
    summary = load(f'reports/formal_pre_daily/{DATE}/summary.json')
    bpost = load(f'reports/b1_prospective_diagnostic_v1/{DATE}_post/post_summary.json')
    apost = load(f'reports/a_new_global_b1_allocation_shadow_v1/daily_post/{DATE}/post_summary.json')
    b2post = load(f'reports/small_field_b2_shadow_v1/daily_post/{DATE}/post_summary.json')
    pl = load(f'reports/pl_forward_shadow_v1/{DATE}_pre/prediction.json')
    plj = load(summary['lanes']['PL_JOCKEY']['selection_path'])
    anew = load(summary['lanes']['A_NEW']['selection_path'])
    bs = load(f'reports/formal_pre_daily/{DATE}/b1_diagnostic/selection.json')
    e = {key(h): h for h in pl['horses']}
    b = {(r['race_id'],int(h['horse_number'])):h for r in plj['races'] for h in r['horses']}
    a = {(r['race_id'],int(h['horse_number'])):h for r in anew['races'] for h in r['horses']}
    comparison_rows = {key(h):h for h in frozen['all_selected_horses']}
    current_keys = {key(h) for h in summary['lanes']['CURRENT']['selected_horses']}
    result, result_sha = result_sources(DATE)
    for post in (bpost, apost):
        if sorted(post['result_sources_sha256'].values()) != sorted(result_sha.values()):
            raise RuntimeError('STOP_POST_RESULT_SHA')

    def joined(k):
        rid,number = k
        if not (e[k]['horse_name'] == b[k]['horse_name'] == a[k]['horse_name']):
            raise RuntimeError('STOP_NAME_IDENTITY')
        _,_,venue,rn = rid.split('_')
        raw = result[JAPANESE_VENUE[venue],int(rn[:-1])]
        size = int(raw[9])
        starters = sum(raw[11+n].strip() not in ('取消','除外') for n in range(1,size+1))
        valid,finish,hit = outcome(raw,number)
        pre = comparison_rows.get(k)
        return {'race_id':rid,'venue':JAPANESE_VENUE[venue],'race_number':int(rn[:-1]),
                'horse_number':number,'horse_name':e[k]['horse_name'],'valid_result':valid,'finish':finish,
                'actual_top3':hit,'raw_result':raw[11+number].strip(),
                'ticket_status':rules.ticket(raw[11+number].strip(),starters,size),
                'e1_p_top3':e[k]['pl_top3_probability'],'b1_p_top3':b[k]['candidate_p_top3'],
                'a_new_p_top3':a[k]['a_new_p_top3'], 'group':pre['group'] if pre else 'NONE_OF_THREE',
                'selections':pre['selections'] if pre else {'E1':False,'B1':False,'A_NEW_B1':False,'CURRENT':k in current_keys},
                'e1_pl_race_rank':e[k]['pl_race_rank'],'b1_plj_race_rank':b[k]['candidate_rank'],
                'a_new_race_rank':a[k]['a_new_rank']}
    groups = {g:[joined(key(h)) for h in rows] for g,rows in frozen['groups'].items()}
    triple = [joined(key(h)) for h in frozen['same_n_comparison']['triple_common']]
    top5 = [joined(key(h)) for h in frozen['same_n_comparison']['b1_top_same_n']]
    human_keys = [(f'race_{DATE}_{venue}_{rn}R',number) for venue,rn,number in [
        ('tokyo',8,2),('tokyo',9,2),('tokyo',9,4),('kyoto',6,4),('kyoto',8,10),
        ('kyoto',9,11),('kyoto',10,1),('kyoto',11,12),('kyoto',12,11)]]
    human = [joined(k) for k in human_keys]
    b_ordered = sorted(bs['selected_horses'],key=lambda h:(-h['pl_jockey_p_top3'],h['race_id'],int(h['horse_number'])))
    b_rows = [dict(joined(key(h)),b1_global_rank=h['global_rank'],b1_selection_order=h['selection_order']) for h in b_ordered]
    totals = {}
    for lane, rows in [('CURRENT',[joined(k) for k in sorted(current_keys)]),
                       ('E1',[joined(key(h)) for h in summary['lanes']['E1']['selected_horses']]),
                       ('B1',b_rows),('A_NEW_B1',b2post['outcomes']['A_NEW_B1/PARENT']),
                       ('B1_B2',b2post['outcomes']['B1/B2']),('A_NEW_B1_B2',b2post['outcomes']['A_NEW_B1/B2'])]:
        totals[lane] = dict(rules.v1.metric(rows),selected_races=len({h['race_id'] for h in rows}))
    prior_b = load('reports/b1_prospective_diagnostic_v1/20261121_post/post_summary.json')
    prior_a = load('reports/a_new_global_b1_allocation_shadow_v1/daily_post/20261121/post_summary.json')
    cumulative = {}
    for lane,prior in [('CURRENT',prior_b['metrics']['CURRENT']),('E1',prior_b['metrics']['E1']),
                        ('B1',prior_b['metrics']['B1']),('A_NEW_B1',prior_a['metrics']['A_NEW_GLOBAL_B1_ALLOCATION_SHADOW'])]:
        today = totals[lane]
        n = prior['valid'] + today['valid']
        hits = prior['top3_hits'] + today['top3_hits']
        cumulative[lane] = {'selected':prior['selected']+today['selected'],'valid':n,'hits':hits,'rate':hits/n,
                            'nov21_hits':prior['top3_hits'],'nov21_valid':prior['valid']}
    triple_keys,top_keys = {key(h) for h in triple},{key(h) for h in top5}
    report = {'date':DATE,'role':'POST_REFERENCE_DIAGNOSTIC_NOT_NEW_BUY_RULE','evidence_credit':0,
              'result_sources_sha256':result_sha,'sources_sha256':sources,'totals':totals,
              'human_purchases':human,'human_metric':rules.v1.metric(human),
              'triple_common':triple,'triple_metric':rules.v1.metric(triple),
              'b1_top5':top5,'b1_top5_metric':rules.v1.metric(top5),
              'triple_only':[joined(k) for k in sorted(triple_keys-top_keys)],
              'top5_only':[joined(k) for k in sorted(top_keys-triple_keys)],
              'b1_all':b_rows,'b1_top_n':{str(n):rules.v1.metric(b_rows[:n]) for n in (5,10,12)},
              'groups':groups,'group_metrics':{g:rules.v1.metric(rows) for g,rows in groups.items()},
              'two_day_top3_cumulative':cumulative,
              'adoption_review':{'block':1,'eligible_date_in_block':2,'decision_due':False,
                  'note':'8-date first checkpoint and 50 selected independent prospective races still apply; no adoption action.'}}
    if any(sha(p)!=h for p,h in sources.items()):
        raise RuntimeError('STOP_SOURCE_CHANGED')
    OUT.mkdir(parents=True,exist_ok=False)
    with (OUT/'reference.json').open('xb') as stream:
        stream.write(rules.v1.b1.canonical(report))
    print(json.dumps({k:report[k] for k in ('totals','human_metric','triple_metric','b1_top5_metric','group_metrics','two_day_top3_cumulative')},ensure_ascii=False))
    print('REPORT_SHA',sha(OUT/'reference.json'))


if __name__ == '__main__':
    main()
