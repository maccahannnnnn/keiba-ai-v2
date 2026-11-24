"""Read-only frozen-PRE comparison. No prediction, Result access, or BUY authority."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATE = '20261122'
OUT = ROOT / 'reports/pre_selection_comparison_20261122'


def main():
    if OUT.exists():
        raise RuntimeError('STOP_REPORT_EXISTS')
    sources = {}
    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()
    def load(p):
        p = Path(p)
        if not p.is_absolute():
            p = ROOT / p
        sources[str(p)] = sha(p)
        return json.loads(p.read_text(encoding='utf-8'))
    def key(h):
        return h['race_id'], int(h['horse_number'])
    summary = load(f'reports/formal_pre_daily/{DATE}/summary.json')
    if summary['status'] != 'COMPLETE' or summary['result_access_count'] != 0:
        raise RuntimeError('STOP_PRE_STATUS')
    for info in summary['lanes'].values():
        for p, s in (('selection_path', 'selection_sha256'), ('authority_path', 'authority_sha256')):
            load(info[p])
            path = Path(info[p])
            if not path.is_absolute():
                path = ROOT / path
            if sha(path) != info[s]:
                raise RuntimeError('STOP_FORMAL_SHA')
    def pair(folder):
        s = load(folder / 'selection.json')
        f = load(folder / 'freeze_manifest.json')
        if s['date'] != DATE or f['date'] != DATE or f['selection_sha256'] != sources[str(folder / 'selection.json')]:
            raise RuntimeError('STOP_SELECTION_SHA')
        return s, f
    b, bf = pair(ROOT / f'reports/formal_pre_daily/{DATE}/b1_diagnostic')
    a, af = pair(ROOT / f'reports/a_new_global_b1_allocation_shadow_v1/daily_pre/{DATE}')
    b2, b2f = pair(ROOT / f'reports/small_field_b2_shadow_v1/daily_pre/{DATE}')
    if any(sha(Path(p)) != h for p, h in b2['input_sources_sha256'].items()):
        raise RuntimeError('STOP_B2_SOURCE_SHA')
    e = load(summary['lanes']['E1']['selection_path'])
    an = load(summary['lanes']['A_NEW']['selection_path'])
    plj = load(summary['lanes']['PL_JOCKEY']['selection_path'])
    pl = load(f'reports/pl_forward_shadow_v1/{DATE}_pre/prediction.json')
    current_root = ROOT / f'reports/prospective_prediction_{DATE}_formal_trace_v1'
    idx = load(current_root / 'race_index.json')['race_index']
    current = {}
    for entry in idx:
        payload = load(current_root / entry['artifact'])
        for h in payload['ranked_results']:
            current[entry['race_id'], int(h['horse_number'])] = h
    selected = {'E1': {key(h) for h in e['selected_horses']}, 'B1': {key(h) for h in b['selected_horses']},
                'A_NEW_B1': {key(h) for h in a['selected_horses']},
                'CURRENT': {key(h) for h in summary['lanes']['CURRENT']['selected_horses']}}
    for lane in ('B1', 'A_NEW_B1'):
        selected[lane + '_B2'] = {key(h) for h in b2['lanes'][lane]['selected_horses']}
        if len(selected[lane + '_B2']) != len(selected[lane]):
            raise RuntimeError('STOP_B2_DAILY_N')
    p_e = {key(h): h for h in pl['horses']}
    p_b = {(r['race_id'], int(h['horse_number'])): h for r in plj['races'] for h in r['horses']}
    p_a = {(r['race_id'], int(h['horse_number'])): h for r in an['races'] for h in r['horses']}
    if set(current) != set(p_e) or set(current) != set(p_b) or set(current) != set(p_a):
        raise RuntimeError('STOP_FULL_FIELD_IDENTITY')
    for k, h in current.items():
        if any(v[k]['horse_name'] != h['horse_name'] for v in (p_e, p_b, p_a)):
            raise RuntimeError('STOP_HORSE_NAME')
    for selection in selected.values():
        if not selection <= set(current):
            raise RuntimeError('STOP_SELECTED_IDENTITY')
    order_e = {key(h): h['global_selection_order'] for h in e['selected_horses']}
    order_b = {key(h): h['global_rank'] for h in b['selected_horses']}
    order_a = {key(h): h['global_rank'] for h in a['selected_horses']}
    group_for = {(True, True, True): 'A', (True, True, False): 'B', (True, False, True): 'C',
                 (False, True, True): 'D', (True, False, False): 'E', (False, True, False): 'F',
                 (False, False, True): 'G'}
    groups = {g: [] for g in 'ABCDEFG'}
    rows = []
    for k in sorted(set.union(*selected.values()), key=lambda k: (k[0].split('_')[2], int(k[0].split('_')[3][:-1]), k[1])):
        rid, n = k
        group = group_for.get(tuple(k in selected[lane] for lane in ('E1', 'B1', 'A_NEW_B1')), 'CURRENT_ONLY')
        row = {'date': DATE, 'race_id': rid, 'venue': {'tokyo': '東京', 'kyoto': '京都'}[rid.split('_')[2]],
               'race_number': int(rid.split('_')[3][:-1]), 'horse_number': n, 'horse_name': current[k]['horse_name'],
               'selections': {lane: k in keys for lane, keys in selected.items()}, 'group': group,
               'e1_pl_race_rank': p_e[k]['pl_race_rank'], 'b1_plj_race_rank': p_b[k]['candidate_rank'],
               'a_new_race_rank': p_a[k]['a_new_rank'], 'e1_selection_order': order_e.get(k),
               'b1_global_rank': order_b.get(k), 'a_new_b1_global_rank': order_a.get(k),
               'e1_p_top3': p_e[k]['pl_top3_probability'], 'b1_p_top3': p_b[k]['candidate_p_top3'],
               'a_new_p_top3': p_a[k]['a_new_p_top3']}
        rows.append(row)
        if group in groups:
            groups[group].append(row)
    k = len(groups['A'])
    top = sorted(b['selected_horses'], key=lambda h: (-h['pl_jockey_p_top3'], h['race_id'], int(h['horse_number'])))[:k]
    lookup = {(r['race_id'], r['horse_number']): r for r in rows}
    top_rows = [lookup[key(h)] for h in top]
    compared = {'status': 'COMPARABLE' if k else 'NOT_COMPARABLE_ZERO_COMMON', 'pre_selected_count': k,
                'triple_common': groups['A'], 'b1_top_same_n': top_rows,
                'overlap': len({key(r) for r in groups['A']} & {key(r) for r in top_rows}),
                'tie_break': 'probability descending, canonical race_id ascending, integer horse_number ascending'}
    report = {'date': DATE, 'role': 'RESULT_FREE_REFERENCE_OBSERVATION', 'evidence_credit': 0,
              'created_at_utc': datetime.now(timezone.utc).isoformat(), 'result_access_count': 0,
              'sources_sha256': sources, 'rank_semantics': 'race ranks are saved PL/PLJ/A_new per-race ranks; E1/B1/A_newB1 allocation orders are distinct saved global values',
              'groups': groups, 'all_selected_horses': rows, 'same_n_comparison': compared,
              'selected_counts': {lane: len(keys) for lane, keys in selected.items()}}
    for path, digest in sources.items():
        if sha(Path(path)) != digest:
            raise RuntimeError('STOP_SOURCE_CHANGED')
    lines = ['2026-11-22 PRE選出比較（Result未参照）',
             'レース内順位は保存済みPL・PLJ・A_new順位。全レース配分順とは別。Currentのみ正式BUY。',
             'A=3AI、B=E1+B1のみ、C=E1+A_newB1のみ、D=B1+A_newB1のみ、E=E1のみ、F=B1のみ、G=A_newB1のみ。', '']
    for title, subset in [('全選出馬', rows)] + [(g, groups[g]) for g in groups] + [('3AI共通と同頭数のB1確率上位', top_rows)]:
        lines += [title, '場 R 馬番 馬名 | Current/E1/B1/A_newB1 | E1/PLJ/A_newレース内順位 | E1/B1/A_new確率 | B1B2/AnewB2 | 区分']
        for r in subset:
            flags = '/'.join('○' if r['selections'][lane] else '-' for lane in ('CURRENT','E1','B1','A_NEW_B1'))
            lines.append(f"{r['venue']} {r['race_number']}R {r['horse_number']} {r['horse_name']} | {flags} | {r['e1_pl_race_rank']}/{r['b1_plj_race_rank']}/{r['a_new_race_rank']} | {r['e1_p_top3']:.2%}/{r['b1_p_top3']:.2%}/{r['a_new_p_top3']:.2%} | {r['selections']['B1_B2']}/{r['selections']['A_NEW_B1_B2']} | {r['group']}")
        lines.append('')
    OUT.mkdir(parents=True, exist_ok=False)
    with (OUT / 'comparison.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2)
    with (OUT / 'human_report.txt').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')
    print(json.dumps({'status': 'COMPLETE', 'counts': report['selected_counts'],
                      'groups': {g: len(v) for g,v in groups.items()}, 'same_n_count': k,
                      'comparison_sha256': sha(OUT / 'comparison.json'), 'human_report_sha256': sha(OUT / 'human_report.txt')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
