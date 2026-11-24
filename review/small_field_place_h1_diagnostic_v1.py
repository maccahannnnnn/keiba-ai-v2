"""H1-only saved-utility diagnostic. Never changes a model or a frozen lane.

Selection uses saved PRE field size, never Result. Sales-start counts are not
available: uncertain third-place tickets are exposed, not assigned a win/loss.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from review import b1_prospective_diagnostic_v1 as b1
from review import a_new_global_b1_h1_reference_20261120 as reference
from review.exp025_offset_pl_raw_history_v1 import _top3_from_utility
from review.formal_post_daily_v1 import result_sources
from review.candidate_generation_training_dataset_readiness_v1 import outcome, JAPANESE_VENUE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/small_field_place_h1_diagnostic_v1'
MODES = ('A', 'B-3', 'B-2', 'C-2')


def top2(utility):
    """Exact first-two ordered PL draws, using the existing utility/worth convention."""
    u = np.asarray(utility, dtype=float)
    if u.ndim != 1 or len(u) < 2 or not np.isfinite(u).all():
        raise ValueError('STOP_UTILITY')
    worth = np.exp(u - np.max(u))
    total = float(worth.sum())
    p = np.zeros(len(u))
    for a in range(len(u)):
        for b in range(len(u)):
            if a == b:
                continue
            probability = worth[a] / total * worth[b] / (total - worth[a])
            p[a] += probability
            p[b] += probability
    if not np.isfinite(p).all() or abs(p.sum() - 2) > 1e-10:
        raise ValueError('STOP_TOP2_MASS')
    return p


def cap(mode, size):
    if mode in ('B-2', 'C-2') and size <= 4:
        return 0
    if 5 <= size <= 7 and mode != 'A':
        return 2
    if mode == 'C-2' and size == 8:
        return 2
    return 3


def allocate(races, n, mode):
    flat = []
    for rid, rows in races.items():
        size = len(rows)
        p2 = top2([r['utility'] for r in rows]) if 5 <= size <= 7 and mode in ('B-2', 'C-2') else None
        for i, row in enumerate(rows):
            flat.append(dict(row, race_id=rid, horse_number=int(row['horse_number']), pre_field_size=size,
                             allocation_probability=float(p2[i]) if p2 is not None else row['p_top3']))
    flat.sort(key=lambda h: (-h['allocation_probability'], h['race_id'], h['horse_number']))
    counts = Counter()
    selected = []
    for row in flat:
        if len(selected) == n:
            break
        rid = row['race_id']
        if counts[rid] >= cap(mode, row['pre_field_size']):
            continue
        counts[rid] += 1
        selected.append(row)
    if len(selected) != n:
        raise ValueError('STOP_DAILY_CAPACITY')
    return selected


def ticket(raw, starters):
    """Refunds separately; DNF/DQ lose. No invented sales-start head count.

    >=8 actual starters implies >=8 at sales start. With 5..7 starters,
    1st/2nd win and 4th+ lose regardless of whether the sale was 2- or 3-place.
    Third place remains unknown without sales-start evidence.
    """
    if raw in ('取消', '除外'):
        return 'REFUND'
    if raw in ('中止', '失格'):
        return 'LOSS'
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError('STOP_RESULT_TOKEN')
    finish = int(raw)
    if starters < 5:
        return 'UNKNOWN_SALE_OR_PLACE_TERMS'
    if finish <= 2:
        return 'HIT'
    if finish >= 4:
        return 'LOSS'
    return 'HIT' if starters >= 8 else 'UNKNOWN_SALE_OR_PLACE_TERMS'


def metric(rows):
    valid = [r for r in rows if r['valid_result']]
    counts = Counter(r['ticket_status'] for r in rows)
    known = counts['HIT'] + counts['LOSS']
    unknown = counts['UNKNOWN_SALE_OR_PLACE_TERMS']
    denominator = known + unknown
    hits = sum(r['actual_top3'] is True for r in valid)
    return {'selected': len(rows), 'valid': len(valid), 'invalid': len(rows) - len(valid),
            'top3_hits': hits, 'top3_rate': hits / len(valid) if valid else None,
            'place_hits_confirmed': counts['HIT'], 'place_losses_confirmed': counts['LOSS'],
            'refunds': counts['REFUND'], 'place_unknown': unknown,
            'place_known_denominator': known, 'place_known_rate': counts['HIT'] / known if known else None,
            'place_rate_all_nonrefund_exact': counts['HIT'] / denominator if denominator and not unknown else None,
            'place_rate_lower': counts['HIT'] / denominator if denominator else None,
            'place_rate_upper': (counts['HIT'] + unknown) / denominator if denominator else None}


def key(row):
    return row['race_id'], int(row['horse_number'])


def main():
    if OUT.exists():
        raise ValueError('STOP_OUTPUT_EXISTS')
    baseline_path = reference.OUT / 'comparison.json'
    baseline = reference.read(baseline_path)
    by_model = {m: defaultdict(lambda: defaultdict(list)) for m in ('B1', 'A_NEW_B1')}
    provenance = []
    for month in range(3, 10):
        folder = reference.FOLDS / f'fold_2026{month:02d}'
        path = folder / 'pre_freeze.json'
        freeze = reference.read(folder / 'freeze_manifest.json')
        if reference.sha(path) != freeze['pre_freeze_sha256']:
            raise ValueError('STOP_FOLD_SHA')
        fold = reference.read(path)
        provenance.append({'path': str(path), 'sha256': reference.sha(path), 'training_range': fold['training_range']})
        for model, branch in (('B1', 'A0'), ('A_NEW_B1', 'A_new')):
            for row in fold['predictions'][branch]:
                if not '20260301' <= row['date'] <= '20260913' or fold['training_range'][1] >= row['date']:
                    raise ValueError('STOP_SCOPE_OR_TRAINING_PIT')
                by_model[model][row['date']][row['race_id']].append(row)
    selections = {}
    for model, days in by_model.items():
        n_by_day = Counter(row['date'] for row in baseline['selection'][model])
        universe = set()
        for date, races in days.items():
            for rid, rows in races.items():
                if len(rows) != len({key(r) for r in rows}):
                    raise ValueError('STOP_DUPLICATE_HORSE')
                p, _ = _top3_from_utility(np.asarray([r['utility'] for r in rows]))
                if max(abs(float(p[i]) - row['p_top3']) for i, row in enumerate(rows)) > 1e-12:
                    raise ValueError('STOP_UTILITY_BASELINE')
                universe.add(rid)
            for mode in MODES:
                selections[model, mode, date] = allocate(races, n_by_day[date], mode)
            if {key(r) for r in selections[model, 'A', date]} != {
                    key(r) for r in baseline['selection'][model] if r['date'] == date}:
                raise ValueError('STOP_A_SELECTION_IDENTITY')
            # Independent check against unchanged B1 selector.
            packed = [{'race_id': rid, 'current_k': sum(bool(r['current_buy']) for r in rows),
                       'horses': [dict(r, candidate_p_top3=r['p_top3']) for r in rows]}
                      for rid, rows in races.items()]
            if {key(r) for r in b1.select_b1(packed, n_by_day[date])} != {
                    key(r) for r in selections[model, 'A', date]}:
                raise ValueError('STOP_SELECT_B1_MATCH')
        if len(days) != 53 or len(universe) != 951:
            raise ValueError('STOP_POPULATION')
    # All eight selection series are fixed before any Result read.
    rows_out = defaultdict(list)
    result_sha, ambiguity = {}, []
    for date in sorted(by_model['B1']):
        results, result_sha[date] = result_sources(date)
        race_info = {}
        for rid, horses in by_model['B1'][date].items():
            parts = rid.split('_')
            row = results[JAPANESE_VENUE[parts[2]], int(parts[3][:-1])]
            count = int(row[9])
            if count != len(horses) or {int(r['horse_number']) for r in horses} != set(range(1, count + 1)):
                raise ValueError('STOP_RESULT_PRE_ROSTER')
            tokens = [row[11 + n].strip() for n in range(1, count + 1)]
            starters = sum(t not in ('取消', '除外') for t in tokens)
            race_info[rid] = (row, starters)
            if starters < 8:
                ambiguity.append({'race_id': rid, 'pre_field_size': count, 'actual_starters': starters,
                                  'sales_start_field_size': None, 'sales_start_place_terms_verified': False})
        for model in by_model:
            for mode in MODES:
                for horse in selections[model, mode, date]:
                    row, starters = race_info[horse['race_id']]
                    valid, finish, hit = outcome(row, horse['horse_number'])
                    rows_out[model, mode].append(dict(horse, valid_result=valid, finish=finish, actual_top3=hit,
                        actual_starters=starters, raw_result=row[11 + horse['horse_number']].strip(),
                        ticket_status=ticket(row[11 + horse['horse_number']].strip(), starters)))
    totals = {model + '/' + mode: metric(rows) for (model, mode), rows in rows_out.items()}
    swaps = {}
    for model in by_model:
        old = {key(r): r for r in rows_out[model, 'A']}
        for mode in MODES[1:]:
            new = {key(r): r for r in rows_out[model, mode]}
            removed, added = sorted(old.keys() - new.keys()), sorted(new.keys() - old.keys())
            swaps[model + '/' + mode] = {'common': len(old.keys() & new.keys()),
                'removed_metric': metric([old[k] for k in removed]), 'added_metric': metric([new[k] for k in added]),
                'removed': [old[k] for k in removed], 'added': [new[k] for k in added]}
    monthly, bands = {}, {}
    for (model, mode), rows in rows_out.items():
        monthly[model + '/' + mode] = {month: metric([r for r in rows if r['date'][:6] == month])
                                      for month in sorted({r['date'][:6] for r in rows})}
        bands[model + '/' + mode] = {band: metric([r for r in rows if
            ('<=4' if r['pre_field_size'] <= 4 else '5-7' if r['pre_field_size'] <= 7 else
             '8' if r['pre_field_size'] == 8 else '9+') == band]) for band in ('<=4', '5-7', '8', '9+')}
    report = {'role': 'HISTORICAL_DEVELOPMENT_DIAGNOSTIC', 'evidence_credit': 0,
              'baseline_sha256': reference.sha(baseline_path), 'select_b1_code_sha256': reference.sha(Path(b1.__file__)),
              'code_sha256': reference.sha(Path(__file__)), 'sources': provenance, 'result_sha256': result_sha,
              'selection_field_size_basis': 'SAVED_PRE_COMPLETE_FIELD_NOT_ASSUMED_SALES_START_COUNT',
              'utility_contains_jockey_adjustment': True, 'jockey_reapplication': False,
              'place_rule_source': 'https://jra.jp/kouza/baken/index.html',
              'place_rate_caveat': 'UNKNOWN terms excluded only in known_rate; full nonrefund rate is bounds, not exact.',
              'totals': totals, 'swaps': swaps, 'monthly': monthly, 'pre_field_bands': bands,
              'sales_start_unverified_races_under8_starters': ambiguity,
              'selections': {m + '/' + v: rows for (m, v), rows in rows_out.items()}}
    OUT.mkdir(parents=True, exist_ok=False)
    with (OUT / 'diagnostic.json').open('xb') as stream:
        stream.write(b1.canonical(report))
    print(json.dumps({'totals': totals, 'ambiguous_races': len(ambiguity)}, ensure_ascii=False))
    print('OUTPUT_SHA256', reference.sha(OUT / 'diagnostic.json'))


if __name__ == '__main__':
    main()
