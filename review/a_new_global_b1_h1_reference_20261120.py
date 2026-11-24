"""Single saved-probability reference comparison; no training or inference."""
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from review import b1_prospective_diagnostic_v1 as b1
from review.historical_seven_lane_development_panel_v1 import official_labels
from review.formal_post_daily_v1 import result_sources

ROOT = Path(__file__).resolve().parents[1]
FOLDS = Path('C:/Users/hikar/.codex/worktrees/core-model-accuracy-redesign-h1h2/keiba AI/reports/core_model_accuracy_redesign_h1_h2_v1')
OUT = ROOT / 'reports/a_new_global_b1_h1_reference_20261120'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(row):
    return row['race_id'], int(row['horse_number'])


def main():
    if OUT.exists():
        raise RuntimeError('STOP_OUTPUT_EXISTS')
    phase1_path = ROOT / 'reports/historical_lane_combination_validation_v1_a1_completion/phase1_completed_frozen_v3.json'
    phase1 = read(phase1_path)
    selected = {lane: {key(h) for h in phase1['selected_horses'] if h['block'] == 'H1' and h['lane'] == lane
                       and h['selection_eligibility'] == 'TECHNICAL_SOURCE_PASS'}
                for lane in ('CURRENT', 'E1', 'B1')}
    probabilities, sources, fold_info = {}, [], []
    new_selected = set()
    daily_n = defaultdict(int)
    for rid, number in selected['B1']:
        daily_n[rid.split('_')[1]] += 1
    for month in range(3, 10):
        folder = FOLDS / f'fold_2026{month:02d}'
        path = folder / 'pre_freeze.json'
        seal = read(folder / 'freeze_manifest.json')
        if sha(path) != seal['pre_freeze_sha256'] or seal['same_month_result_access_before_freeze'] != 0:
            raise RuntimeError('STOP_FOLD_SHA_OR_PRE_AUTHORITY')
        fold = read(path)
        rows = fold['predictions']['A_new']
        base_rows = fold['predictions']['A0']
        if {key(r) for r in rows} != {key(r) for r in base_rows} or len(rows) != len({key(r) for r in rows}):
            raise RuntimeError('STOP_FOLD_POPULATION')
        if any(fold['training_range'][1] >= r['date'] for r in rows):
            raise RuntimeError('STOP_FOLD_TRAINING_PIT')
        sources.append({'path': str(path), 'sha256': sha(path), 'freeze_sha256': sha(folder / 'freeze_manifest.json')})
        fold_info.append({'month': fold['month'], 'training_range': fold['training_range'],
                          'frozen_at_utc': seal['frozen_at_utc'], 'horses': len(rows),
                          'a_new_model_sha256': hashlib.sha256(b1.canonical(fold['models']['A_new'])).hexdigest(),
                          'jockey_application': fold['models']['A_new']['jockey_application']})
        for row in rows:
            if key(row) in probabilities:
                raise RuntimeError('STOP_DUPLICATE_HORSE')
            probabilities[key(row)] = row
        for branch, data in (('A0', base_rows), ('A_new', rows)):
            by_day = defaultdict(lambda: defaultdict(list))
            for row in data:
                by_day[row['date']][row['race_id']].append(row)
            for date, races in by_day.items():
                packed = []
                for rid, horses in races.items():
                    k = sum((rid, int(h['horse_number'])) in selected['CURRENT'] for h in horses)
                    packed.append({'race_id': rid, 'current_k': k, 'horses': [
                        {'horse_number': h['horse_number'], 'horse_name': h['horse_name'],
                         'candidate_p_top3': h['p_top3']} for h in horses]})
                allocation = b1.select_b1(packed, daily_n[date])
                keys = {key(h) for h in allocation}
                if branch == 'A0':
                    expected = {k for k in selected['B1'] if k[0].split('_')[1] == date}
                    if keys != expected:
                        raise RuntimeError('STOP_B1_IDENTITY_REPRODUCTION:' + date)
                else:
                    new_selected.update(keys)
    if len(probabilities) != 12661 or len(daily_n) != 53 or len({r for r, n in probabilities}) != 951:
        raise RuntimeError('STOP_H1_POPULATION')
    selected['A_NEW_B1'] = new_selected
    # Selection finished before any Result is opened.
    labels, result_shas = {}, {}
    for date in sorted(daily_n):
        keys = {k for values in selected.values() for k in values if k[0].split('_')[1] == date}
        labels.update(official_labels(date, keys))
        _, digests = result_sources(date)
        result_shas[date] = digests

    def metric(keys):
        valid = [labels[k] for k in keys if labels[k][0]]
        hits = sum(v[2] is True for v in valid)
        return {'selected': len(keys), 'valid': len(valid), 'invalid': len(keys) - len(valid),
                'top3_hits': hits, 'top3_rate': hits / len(valid) if valid else None,
                'selected_races': len({k[0] for k in keys})}
    metrics = {lane: metric(keys) for lane, keys in selected.items()}
    if (metrics['B1']['selected'], metrics['B1']['valid'], metrics['B1']['top3_hits']) != (716, 714, 380):
        raise RuntimeError('STOP_B1_RESULT_BASELINE')
    common = selected['B1'] & new_selected
    removed, added = selected['B1'] - new_selected, new_selected - selected['B1']
    daily = [{'date': date, 'metrics': {lane: metric({k for k in keys if k[0].split('_')[1] == date})
                                      for lane, keys in selected.items()}} for date in sorted(daily_n)]
    report = {'role': 'HISTORICAL_DEVELOPMENT_DIAGNOSTIC', 'prospective_evidence_credit': 0,
              'created_at_utc': datetime.now(timezone.utc).isoformat(), 'metrics': metrics,
              'rate_difference_vs_b1': {k: v['top3_rate'] - metrics['B1']['top3_rate'] for k, v in metrics.items()},
              'overlap_with_b1': {k: len(keys & selected['B1']) for k, keys in selected.items()},
              'swaps': {'common': metric(common), 'b1_only': metric(removed), 'a_new_b1_only': metric(added)},
              'folds': fold_info, 'sources': sources, 'phase1_sha256': sha(phase1_path),
              'select_b1_code_sha256': sha(Path(b1.__file__)), 'result_sha256': result_shas,
              'daily': daily, 'selection': {lane: [dict(probabilities[k], valid_result=labels[k][0], finish=labels[k][1],
                           actual_top3=labels[k][2]) for k in sorted(keys)] for lane, keys in selected.items()},
              'swap_horses': {name: [dict(probabilities[k], valid_result=labels[k][0], finish=labels[k][1],
                           actual_top3=labels[k][2]) for k in sorted(keys)] for name, keys in
                           [('b1_only', removed), ('a_new_b1_only', added)]}}
    OUT.mkdir(parents=True, exist_ok=False)
    with (OUT / 'comparison.json').open('xb') as stream:
        stream.write(b1.canonical(report))
    print(json.dumps({k: report[k] for k in ('metrics', 'rate_difference_vs_b1', 'overlap_with_b1', 'swaps', 'folds')}, ensure_ascii=False))
    print('REPORT_SHA256', sha(OUT / 'comparison.json'))


if __name__ == '__main__':
    main()
