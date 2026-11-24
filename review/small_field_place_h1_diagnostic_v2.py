"""Outcome correction of the preserved v1 H1 diagnostic; no model inference.

The approved complete PRE roster bounds sales-start field size from above.
For PRE <=7 and >=5 actual starters, third is a definite place loss.
"""
from collections import Counter
from pathlib import Path
import json

from review import small_field_place_h1_diagnostic_v1 as v1

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/small_field_place_h1_diagnostic_v2'
V1_SHA = '097c1f40e6fc3f45239dc1576d046bc7d40e23c0ff5ff16e9755d5b50d79ebdd'
JRA_URL = 'https://www.jra.go.jp/kouza/baken/index.html'


def ticket(raw, starters, pre_field_size):
    if type(pre_field_size) is not int or type(starters) is not int or not 0 <= starters <= pre_field_size:
        raise ValueError('STOP_FIELD_COUNTS')
    if raw in ('取消', '除外'):
        return 'REFUND'
    if raw in ('中止', '失格'):
        return 'LOSS'
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError('STOP_RESULT_TOKEN')
    finish = int(raw)
    if starters < 5:
        return 'UNKNOWN_SALE_OR_PLACE_TERMS'
    if pre_field_size <= 7:
        return 'HIT' if finish <= 2 else 'LOSS'
    if finish <= 2:
        return 'HIT'
    if finish >= 4:
        return 'LOSS'
    return 'HIT' if starters >= 8 else 'UNKNOWN_SALE_OR_PLACE_TERMS'


def cap(mode, size):
    if mode != 'A' and size <= 4:
        return 0
    return v1.cap(mode, size)


def allocate(races, n, mode):
    # Reuse all ranking, probability and tie logic; B-3 also excludes <=4.
    eligible = races if mode == 'A' else {rid: rows for rid, rows in races.items() if len(rows) >= 5}
    return v1.allocate(eligible, n, mode)


def paired(old_rows, new_rows):
    old = {v1.key(r): r for r in old_rows}
    new = {v1.key(r): r for r in new_rows}
    common = sorted(old.keys() & new.keys())
    removed = [old[k] for k in sorted(old.keys() - new.keys())]
    added = [new[k] for k in sorted(new.keys() - old.keys())]
    if any(old[k]['ticket_status'] != new[k]['ticket_status'] for k in common):
        raise ValueError('STOP_COMMON_OUTCOME_MISMATCH')
    a, b = v1.metric(old_rows), v1.metric(new_rows)
    exact = a['place_unknown'] == b['place_unknown'] == 0
    return {'old': a, 'new': b, 'common_selected': len(common),
            'common_metric': v1.metric([old[k] for k in common]),
            'removed_metric': v1.metric(removed), 'added_metric': v1.metric(added),
            'place_hit_difference': b['place_hits_confirmed'] - a['place_hits_confirmed'] if exact else None,
            'refund_difference': b['refunds'] - a['refunds'],
            'nonrefund_denominator_difference': (b['selected'] - b['refunds']) - (a['selected'] - a['refunds']),
            'place_rate_difference': b['place_rate_all_nonrefund_exact'] - a['place_rate_all_nonrefund_exact']
                if exact and a['place_rate_all_nonrefund_exact'] is not None and b['place_rate_all_nonrefund_exact'] is not None else None,
            'removed': removed, 'added': added}


def main():
    if OUT.exists():
        raise ValueError('STOP_OUTPUT_EXISTS')
    source = v1.OUT / 'diagnostic.json'
    if v1.reference.sha(source) != V1_SHA:
        raise ValueError('STOP_V1_SHA')
    old = v1.reference.read(source)
    series = {}
    for label, rows in old['selections'].items():
        mode = label.split('/')[1]
        if any(r['pre_field_size'] <= 4 for r in rows) and mode != 'A':
            raise ValueError('STOP_V1_SELECTION_REQUIRES_REDERIVATION')
        series[label] = [dict(r, ticket_status=ticket(r['raw_result'], r['actual_starters'], r['pre_field_size']))
                         for r in rows]
        # All saved identities, probabilities and allocation order are retained.
        if [v1.key(r) for r in series[label]] != [v1.key(r) for r in rows]:
            raise ValueError('STOP_SELECTION_DRIFT')
        if Counter(r['date'] for r in rows) != Counter(r['date'] for r in old['selections'][label.split('/')[0] + '/A']):
            raise ValueError('STOP_DAILY_N')
    totals = {label: v1.metric(rows) for label, rows in series.items()}
    comparisons = {}
    for model in ('B1', 'A_NEW_B1'):
        for mode in v1.MODES[1:]:
            comparisons[model + '/' + mode + '_vs_A'] = paired(series[model + '/A'], series[model + '/' + mode])
        comparisons[model + '/C-2_vs_B-2'] = paired(series[model + '/B-2'], series[model + '/C-2'])
    for mode in v1.MODES:
        comparisons['A_NEW_B1/' + mode + '_vs_B1_same_mode'] = paired(series['B1/' + mode], series['A_NEW_B1/' + mode])
    monthly, bands = {}, {}
    for label, rows in series.items():
        monthly[label] = {m: v1.metric([r for r in rows if r['date'][:6] == m])
                          for m in sorted({r['date'][:6] for r in rows})}
        bands[label] = {band: v1.metric([r for r in rows if
            ('<=4' if r['pre_field_size'] <= 4 else '5-7' if r['pre_field_size'] <= 7 else
             '8' if r['pre_field_size'] == 8 else '9+') == band]) for band in ('<=4', '5-7', '8', '9+')}
    corrected_races = [dict(r, place_terms='TOP2', place_terms_determined_from_pre_upper_bound=True)
                       for r in old['sales_start_unverified_races_under8_starters']
                       if 5 <= r['actual_starters'] <= r['pre_field_size'] <= 7]
    report = {'version': 2, 'role': old['role'], 'evidence_credit': 0,
              'v1_path': str(source), 'v1_sha256': V1_SHA,
              'code_sha256': v1.reference.sha(Path(__file__)), 'source_provenance': old['sources'],
              'result_sha256': old['result_sha256'], 'jra_reference_url': JRA_URL,
              'selection_reused_without_change': True, 'training_or_inference': False,
              'totals': totals, 'paired_comparisons': comparisons, 'monthly': monthly,
              'pre_field_bands': bands, 'selections': series, 'corrected_small_races': corrected_races,
              'remaining_unknown_selected': {label: [r for r in rows if r['ticket_status'].startswith('UNKNOWN')]
                                             for label, rows in series.items()}}
    OUT.mkdir(parents=True, exist_ok=False)
    with (OUT / 'diagnostic.json').open('xb') as stream:
        stream.write(v1.b1.canonical(report))
    print(json.dumps({'totals': totals, 'corrected_races': len(corrected_races),
                      'sha256': v1.reference.sha(OUT / 'diagnostic.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
