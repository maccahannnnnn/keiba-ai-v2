"""Independent B1/A_new B-2 PRE and POST. No model fitting or parent writes."""
import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from review import a_new_global_b1_allocation_shadow_v1 as parent
from review import small_field_place_h1_diagnostic_v2 as rules
from review import small_field_place_h1_diagnostic_v1 as probability
from review.exp025_offset_pl_raw_history_v1 import _top3_from_utility

ROOT = Path(__file__).resolve().parents[1]
ROLE = 'SMALL_FIELD_B2_PROSPECTIVE_SHADOW_ONLY'
PARENTS = ('B1', 'A_NEW_B1')
Stop = parent.Stop


def checked_date(date):
    if not isinstance(date, str) or re.fullmatch(r'[0-9]{8}', date) is None:
        raise Stop('STOP_DATE')
    try:
        datetime.strptime(date, '%Y%m%d')
    except ValueError as error:
        raise Stop('STOP_DATE') from error


def calculate(races, n):
    """Reuse H1 v2 B-2; utility already contains exactly one jockey correction."""
    for rid, rows in races.items():
        if len(rows) != len({int(r['horse_number']) for r in rows}):
            raise Stop('STOP_DUPLICATE_HORSE')
        p, _ = _top3_from_utility(np.asarray([r['utility'] for r in rows], dtype=float))
        if any(abs(float(p[i]) - r['p_top3']) > 1e-12 for i, r in enumerate(rows)):
            raise Stop('STOP_UTILITY_PROBABILITY_MISMATCH:' + rid)
    try:
        return rules.allocate(races, n, 'B-2')
    except ValueError as error:
        raise Stop(str(error)) from error


def freeze_pre(date, *, root=ROOT, a_root=parent.ANEW_ROOT):
    checked_date(date)
    # Existence only: never read a Result file in PRE.
    raw = root / 'data/raw/target/daily_result_list'
    if any((raw / f'{prefix}_{date}.csv').exists() for prefix in ('馬番順着順', '着順馬番')):
        raise Stop('STOP_RESULT_ALREADY_PRESENT')
    out = root / f'reports/small_field_b2_shadow_v1/daily_pre/{date}'
    if out.exists():
        raise Stop('STOP_OUTPUT_EXISTS')
    verified = parent.derive(date, root=root, a_root=a_root)
    deadline = parent.moment(verified['freeze_deadline'])
    if datetime.now(timezone.utc) >= deadline:
        raise Stop('STOP_CUTOFF')
    sources = {}

    def read(path):
        sources[str(path.resolve())] = parent.sha(path)
        return parent.read(path)

    def pair(folder):
        s, f = read(folder / 'selection.json'), read(folder / 'freeze_manifest.json')
        if s.get('date') != date or f.get('date') != date or f.get('selection_sha256') != parent.sha(folder / 'selection.json'):
            raise Stop('STOP_PARENT_FREEZE_SHA')
        if f.get('result_access_count') != 0 or parent.moment(f['freeze_timestamp_utc']) >= deadline:
            raise Stop('STOP_PARENT_FREEZE_TIME_OR_RESULT')
        return s

    bdir = root / f'reports/formal_pre_daily/{date}/b1_diagnostic'
    b = pair(bdir)
    adir = root / f'reports/a_new_global_b1_allocation_shadow_v1/daily_pre/{date}'
    a = pair(adir)
    plj_path = root / f'reports/frozen_pl_v1_jockey_offset_provisional_v1/{date}_pre/selection.json'
    plj = read(plj_path)
    audit_path = plj_path.with_name('provisional_audit.json')
    audit = read(audit_path)
    anew_path = a_root / f'reports/a_new_prospective_shadow_v1/daily_pre/{date}/selection.json'
    anew = read(anew_path)
    if (b.get('pl_jockey_selection_sha256') != parent.sha(plj_path) or
            b.get('pl_jockey_freeze_sha256') != parent.sha(audit_path) or
            audit.get('selection_sha256') != parent.sha(plj_path) or
            b.get('current_prediction_sha256') != verified['current_manifest_sha256'] or
            a.get('a_new_selection_sha256') != parent.sha(anew_path) or
            a.get('current_manifest_sha256') != verified['current_manifest_sha256'] or
            a.get('selected_horses') != verified['selected_horses'] or
            plj.get('fallback_race_count') != 0 or plj.get('result_access_count') != 0):
        raise Stop('STOP_PARENT_LINEAGE')
    current = root / f'reports/prospective_prediction_{date}_formal_trace_v1'
    for name in ('prediction_manifest.json', 'input_manifest.json', 'race_index.json', 'formal_freeze_attestation.json'):
        read(current / name)
    inputs = parent.read(current / 'input_manifest.json')
    for item in parent.b1.verified_input_sources(current, inputs).values():
        sources[item['path']] = item['sha256']
    attestation = parent.read(current / 'formal_freeze_attestation.json')
    first_path = root / attestation['first_start_evidence_path']
    read(first_path)
    for file in (Path(__file__), Path(parent.__file__), Path(rules.__file__), Path(probability.__file__)):
        sources[str(file.resolve())] = parent.sha(file)
    for path in (a_root / 'models/a_new_prospective_shadow_v1/a_new_final_model.json',
                 root / 'models/pl_forward_shadow_v1/pl_forward_shadow_v1_model.json',
                 root / 'models/adaptive_pl_jockey_research_v1/integrated_model.json'):
        sources[str(path.resolve())] = parent.sha(path)
    index = parent.read(current / 'race_index.json')['race_index']
    expected = {}
    for item in index:
        payload = read(current / item['artifact'])
        expected[item['race_id']] = {(int(h['horse_number']), h['horse_name']) for h in payload['ranked_results']}
    data, baselines = {}, {'B1': b['selected_horses'], 'A_NEW_B1': a['selected_horses']}
    for label, value, u, p in (('B1', plj, 'candidate_utility', 'candidate_p_top3'),
                               ('A_NEW_B1', anew, 'a_new_utility', 'a_new_p_top3')):
        races = {}
        for race in value['races']:
            rid = race['race_id']
            if rid in races:
                raise Stop('STOP_DUPLICATE_RACE')
            if {(int(h['horse_number']), h['horse_name']) for h in race['horses']} != expected.get(rid):
                raise Stop('STOP_HORSE_IDENTITY')
            races[rid] = [dict(h, race_id=rid, horse_number=int(h['horse_number']), utility=h[u], p_top3=h[p])
                          for h in race['horses']]
        if set(races) != set(expected):
            raise Stop('STOP_RACE_SET')
        n = len(baselines[label])
        if n != verified['daily_current_buy_n']:
            raise Stop('STOP_PARENT_DAILY_N')
        selected = calculate(races, n)
        old_keys = {rules.v1.key(h) for h in baselines[label]}
        new_keys = {rules.v1.key(h) for h in selected}
        data[label] = {'lane': label + '_SMALL_FIELD_B2_SHADOW', 'parent_selected_count': n,
                       'selected_count': len(selected), 'selected_horses': selected,
                       'parent_selected_horses': baselines[label], 'all_probabilities': races,
                       'common_with_parent': len(old_keys & new_keys),
                       'removed_keys': sorted(old_keys - new_keys), 'added_keys': sorted(new_keys - old_keys),
                       'model_sha256': plj['model_sha256'] if label == 'B1' else anew['a_new_model_sha256'],
                       'jockey_beta': plj['beta'], 'jockey_reapplication': False}
    record = {'date': date, 'status': 'PRE_CALCULATED', 'role': ROLE,
              'evidence_credit': 0, 'b1_adoption_evidence_credit': 0, 'result_access_count': 0,
              'head_count_basis': 'PRE_ENTRY_ROSTER', 'sales_start_field_size_verified': False,
              'race_field_sizes': {rid: len(hs) for rid, hs in expected.items()},
              'freeze_deadline': deadline.isoformat(), 'input_sources_sha256': sources, 'lanes': data}
    if any(parent.sha(Path(path)) != digest for path, digest in sources.items()):
        raise Stop('STOP_SOURCE_CHANGED')
    stamp = datetime.now(timezone.utc)
    if stamp >= deadline:
        raise Stop('STOP_CUTOFF')
    out.mkdir(parents=True, exist_ok=False)
    record.update(status='FROZEN_SHADOW_PRE', generated_at_utc=stamp.isoformat())
    selection_path = out / 'selection.json'
    with selection_path.open('xb') as stream:
        stream.write(parent.canonical(record))
    stamp = datetime.now(timezone.utc)
    if stamp >= deadline:
        raise Stop('STOP_CUTOFF_CROSSED_PARTIAL_OUTPUT')
    seal = {'date': date, 'status': 'FROZEN_SHADOW_PRE', 'role': ROLE,
            'selection_sha256': parent.sha(selection_path), 'freeze_timestamp_utc': stamp.isoformat(),
            'freeze_deadline': deadline.isoformat(), 'result_access_count': 0,
            'evidence_credit': 0, 'b1_adoption_evidence_credit': 0}
    with (out / 'freeze_manifest.json').open('xb') as stream:
        stream.write(parent.canonical(seal))
    return {'date': date, 'status': seal['status'], 'selection_sha256': seal['selection_sha256'],
            'freeze_sha256': parent.sha(out / 'freeze_manifest.json'),
            'lanes': {k: {'selected': v['selected_count'], 'common': v['common_with_parent']} for k, v in data.items()}}


def evaluate_post(date, *, root=ROOT, sales_evidence=None):
    """Read frozen PRE first. Optional documented sales-start counts resolve ambiguity."""
    checked_date(date)
    folder = root / f'reports/small_field_b2_shadow_v1/daily_pre/{date}'
    s, f = parent.read(folder / 'selection.json'), parent.read(folder / 'freeze_manifest.json')
    if (s.get('date') != date or f.get('date') != date or s.get('status') != 'FROZEN_SHADOW_PRE' or
            f.get('selection_sha256') != parent.sha(folder / 'selection.json') or
            f.get('result_access_count') != 0 or s.get('result_access_count') != 0 or
            s.get('evidence_credit') != 0 or f.get('evidence_credit') != 0 or
            s.get('b1_adoption_evidence_credit') != 0 or f.get('b1_adoption_evidence_credit') != 0 or
            parent.moment(f['freeze_timestamp_utc']) >= parent.moment(f['freeze_deadline']) or
            f['freeze_deadline'] != s['freeze_deadline']):
        raise Stop('STOP_PRE_AUTHORITY')
    for path, digest in s['input_sources_sha256'].items():
        if parent.sha(Path(path)) != digest:
            raise Stop('STOP_PRE_SOURCE_SHA')
    sales = {}
    sales_sources = {}
    if sales_evidence is not None:
        evidence = parent.read(sales_evidence)
        sales_sources[str(sales_evidence)] = parent.sha(sales_evidence)
        if evidence.get('date') != date:
            raise Stop('STOP_SALES_EVIDENCE_DATE')
        for rid, item in evidence['races'].items():
            size = item['sales_start_field_size']
            authority = Path(item['authority_path'])
            if (type(size) is not int or not 1 <= size <= s['race_field_sizes'].get(rid, 0) or
                    parent.sha(authority) != item['authority_sha256']):
                raise Stop('STOP_SALES_EVIDENCE_AUTHORITY')
            sales[rid] = size
            sales_sources[str(authority)] = item['authority_sha256']
    # No prediction selection or probability calculation occurs in POST.
    from review.formal_post_daily_v1 import result_sources
    from review.candidate_generation_training_dataset_readiness_v1 import outcome, JAPANESE_VENUE
    results, hashes = result_sources(date)
    output = {}
    for label, lane in s['lanes'].items():
        for variant, horses in (('B2', lane['selected_horses']), ('PARENT', lane['parent_selected_horses'])):
            joined = []
            for h in horses:
                rid, number = h['race_id'], int(h['horse_number'])
                _, _, venue, race = rid.split('_')
                result = results[JAPANESE_VENUE[venue], int(race[:-1])]
                size = s['race_field_sizes'][rid]
                if int(result[9]) != size:
                    raise Stop('STOP_RESULT_ROSTER')
                starters = sum(result[11 + i].strip() not in ('取消', '除外') for i in range(1, size + 1))
                valid, finish, hit = outcome(result, number)
                raw = result[11 + number].strip()
                status = rules.ticket(raw, starters, size)
                basis = 'PRE_ROSTER_BOUND_AND_ACTUAL_STARTERS'
                if rid in sales:
                    sale = sales[rid]
                    if not starters <= sale <= size:
                        raise Stop('STOP_SALES_RESULT_CONFLICT')
                    if sale < 5:
                        status = 'UNKNOWN_SALE_OR_PLACE_TERMS'
                    elif raw not in ('取消', '除外', '中止', '失格'):
                        status = 'HIT' if int(raw) <= (2 if sale <= 7 else 3) else 'LOSS'
                    basis = 'DOCUMENTED_SALES_START_FIELD_SIZE'
                joined.append(dict(h, valid_result=valid, finish=finish, actual_top3=hit,
                                   ticket_status=status, actual_starters=starters, place_terms_basis=basis))
            output[label + '/' + variant] = joined
    report = {'date': date, 'status': 'COMPLETE', 'role': 'SMALL_FIELD_B2_POST_DIAGNOSTIC_ONLY',
              'evidence_credit': 0, 'b1_adoption_evidence_credit': 0,
              'pre_selection_sha256': parent.sha(folder / 'selection.json'),
              'pre_freeze_sha256': parent.sha(folder / 'freeze_manifest.json'), 'result_sources_sha256': hashes,
              'sales_sources_sha256': sales_sources, 'post_code_sha256': parent.sha(Path(__file__)),
              'metrics': {k: probability.metric(rows) for k, rows in output.items()},
              'paired_comparisons': {k: rules.paired(output[k + '/PARENT'], output[k + '/B2']) for k in PARENTS},
              'outcomes': output}
    out = root / f'reports/small_field_b2_shadow_v1/daily_post/{date}'
    out.mkdir(parents=True, exist_ok=False)
    with (out / 'post_summary.json').open('xb') as stream:
        stream.write(parent.canonical(report))
    return {'status': 'COMPLETE', 'path': str(out / 'post_summary.json'), 'sha256': parent.sha(out / 'post_summary.json')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('step', choices=('freeze-pre', 'post'))
    parser.add_argument('--date', required=True)
    parser.add_argument('--sales-start-evidence', type=Path)
    args = parser.parse_args()
    if args.step == 'freeze-pre':
        if args.sales_start_evidence is not None:
            raise Stop('STOP_POST_ONLY_ARGUMENT')
        result = freeze_pre(args.date)
    else:
        result = evaluate_post(args.date, sales_evidence=args.sales_start_evidence)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
