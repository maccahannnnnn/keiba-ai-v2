"""Result-blind 2026-11-01 seven-lane PRE comparison from sealed artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANEW = Path('C:/Users/hikar/.codex/worktrees/a-new-prospective-shadow-v1/keiba AI')
E1ROOT = Path('C:/Users/hikar/.codex/worktrees/e1-full-field-allocation-prospective-shadow-v1/keiba AI')
OUT = ROOT / 'reports/20261101_multi_lane_pre_v1'
DATE = '20261101'
LANES = ('CURRENT', 'EXP024', 'CURRENT_RANK1', 'PL_JOCKEY', 'A_NEW', 'E1', 'INDEPENDENT_V5')
FAMILIES = {'CURRENT_FAMILY': ('CURRENT', 'CURRENT_RANK1'),
            'PL_V1_FAMILY': ('EXP024', 'PL_JOCKEY', 'A_NEW', 'E1'),
            'V5_FAMILY': ('INDEPENDENT_V5',)}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p: Path):
    return json.loads(p.read_text(encoding='utf-8'))


def csv_write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    assert now.date().isoformat() <= '2026-11-01', 'PRE_DATE_PAST'
    sources = {
        'DG': ROOT / 'data/raw/prediction_input/DG261101.CSV',
        'DE': ROOT / 'data/raw/prediction_input/DE261101.CSV',
        'DS': ROOT / 'data/raw/prediction_input/DS261101.CSV',
        'current_manifest': ROOT / 'reports/prospective_prediction_20261101_formal_trace_v1/prediction_manifest.json',
        'current_input_manifest': ROOT / 'reports/prospective_prediction_20261101_formal_trace_v1/input_manifest.json',
        'current_freeze': ROOT / 'reports/prospective_prediction_20261101_formal_trace_v1/formal_freeze_attestation.json',
        'exp024_selection': ROOT / 'reports/exp024_pl_same_volume/20261101_pre/selection.json',
        'exp024_freeze': ROOT / 'reports/exp024_pl_same_volume/20261101_pre/selection_freeze.json',
        'rank1_selection': ROOT / 'reports/current_rank1_prospective_shadow_v2/20261101_pre/pre_selection.json',
        'rank1_freeze': ROOT / 'reports/current_rank1_prospective_shadow_v2/20261101_pre/freeze_manifest.json',
        'pl_jockey_selection': ROOT / 'reports/frozen_pl_v1_jockey_offset_provisional_v1/20261101_pre/selection.json',
        'pl_jockey_freeze': ROOT / 'reports/frozen_pl_v1_jockey_offset_provisional_v1/20261101_pre/provisional_audit.json',
        'a_new_selection': ANEW / 'reports/a_new_prospective_shadow_v1/daily_pre/20261101/selection.json',
        'a_new_freeze': ANEW / 'reports/a_new_prospective_shadow_v1/daily_pre/20261101/freeze_manifest.json',
        'e1_selection': E1ROOT / 'reports/e1_full_field_allocation_prospective_shadow_v1/daily_pre/20261101/selection.json',
        'e1_freeze': E1ROOT / 'reports/e1_full_field_allocation_prospective_shadow_v1/daily_pre/20261101/freeze_manifest.json',
        'independent_selection': ROOT / 'reports/independent_race_selection_prospective/20261101_pre/selection_manifest.json',
        'independent_hashes': ROOT / 'reports/independent_race_selection_prospective/20261101_pre/artifact_hashes.json',
    }
    assert all(p.is_file() for p in sources.values()), 'PRE_SOURCE_MISSING'
    shas = {name: sha(path) for name, path in sources.items()}
    current_root = sources['current_manifest'].parent
    manifest = load(sources['current_manifest'])
    assert all(sha(current_root / x['relative_path']) == x['sha256'] for x in manifest['files'])
    input_manifest = load(sources['current_input_manifest'])
    assert input_manifest['date'] == DATE
    assert all(shas[k] == input_manifest['sources'][k]['sha256'] for k in ('DG', 'DE', 'DS'))
    first = load(ROOT / 'reports/exp024_pl_same_volume/authority/first_start_20261101.json')['first_start_at']
    assert now < datetime.fromisoformat(first), 'PRE_AFTER_FIRST_START'
    assert load(sources['current_freeze'])['prediction_manifest_sha256'] == shas['current_manifest']
    assert load(sources['exp024_freeze'])['selection_sha256'] == shas['exp024_selection']
    assert load(sources['rank1_freeze'])['selection_sha256'] == shas['rank1_selection']
    assert load(sources['pl_jockey_freeze'])['selection_sha256'] == shas['pl_jockey_selection']
    anew_freeze = load(sources['a_new_freeze'])
    assert anew_freeze['selection_sha256'] == shas['a_new_selection'] and anew_freeze['evidence_date'] is True
    e1_freeze = load(sources['e1_freeze'])
    assert e1_freeze['selection_sha256'] == shas['e1_selection'] and e1_freeze['evidence_date'] is True
    assert load(sources['independent_hashes'])['indexed_artifacts']['selection_manifest.json'] == shas['independent_selection']

    index = load(current_root / 'race_index.json')['race_index']
    payloads = {item['race_id']: load(current_root / item['artifact']) for item in index}
    assert len(payloads) == len(index) == 13
    horses = {}
    lane_sets = {lane: set() for lane in LANES}
    current_states = {}
    for rid, p in payloads.items():
        current_states[rid] = p['buy_gate_trace']['race']['shadow_race_state']
        for h in p['ranked_results']:
            k = (rid, int(h['horse_number']))
            assert k not in horses, 'DUPLICATE_CURRENT_HORSE'
            horses[k] = {'race_id': rid, 'horse_number': k[1], 'horse_name': h['horse_name'], 'current_rank': h.get('rank')}
        lane_sets['CURRENT'].update((rid, int(h['horse_number'])) for h in p['buys'])
    assert len(horses) == 174
    exp = load(sources['exp024_selection'])
    assert exp['date'] == DATE and exp['current_prediction_sha256'] == shas['current_manifest']
    for race in exp['races']:
        lane_sets['EXP024'].update((race['race_id'], int(n)) for n in race['treatment_selected_horses'])
    rank1 = load(sources['rank1_selection'])
    assert rank1['target_date'] == DATE and rank1['result_access_count'] == 0
    for row in rank1['selections']:
        lane_sets['CURRENT_RANK1'].add((row['race_id'], int(row['selected_horse_number'])))
    pj = load(sources['pl_jockey_selection'])
    assert pj['date'] == DATE and pj['result_access_count'] == 0
    pj_detail = {}
    for race in pj['races']:
        rid = race['race_id']
        lane_sets['PL_JOCKEY'].update((rid, int(n)) for n in race['candidate_selected_horses'])
        pj_detail.update({(rid, int(h['horse_number'])): h for h in race['horses']})
    anew = load(sources['a_new_selection'])
    assert anew['date'] == DATE and anew['result_access_count_at_pre_freeze'] == 0
    assert {s['kind']: s['sha256'] for s in anew['source_identity']} == {k: shas[k] for k in ('DE', 'DG', 'DS')}
    anew_detail = {}
    for race in anew['races']:
        rid = race['race_id']
        lane_sets['A_NEW'].update((rid, int(n)) for n in race['a_new_selected_horses'])
        anew_detail.update({(rid, int(h['horse_number'])): h for h in race['horses']})
    e1 = load(sources['e1_selection'])
    assert e1['date'] == DATE and e1['result_access_count_at_pre_freeze'] == 0
    e1_order = {}
    for h in e1['selected_horses']:
        k = (h['race_id'], int(h['horse_number']))
        lane_sets['E1'].add(k)
        e1_order[k] = h['global_selection_order']
    independent = load(sources['independent_selection'])
    assert independent['date'] == DATE and independent['result_data_access_count'] == 0
    v5_detail = {}
    for race in independent['races']:
        rid = race['race_id']
        for h in race['selected_horses']:
            k = (rid, int(h['horse_number']))
            lane_sets['INDEPENDENT_V5'].add(k)
            v5_detail[k] = h
    assert all(s <= set(horses) for s in lane_sets.values()), 'LANE_HORSE_OUTSIDE_CURRENT_FIELD'
    assert len(lane_sets['CURRENT']) == len(lane_sets['EXP024']) == len(lane_sets['PL_JOCKEY']) == len(lane_sets['A_NEW']) == len(lane_sets['E1']) == 14

    rows = []
    for k, h in sorted(horses.items()):
        selected_lanes = [lane for lane in LANES if k in lane_sets[lane]]
        supported_families = [f for f, members in FAMILIES.items() if any(lane in selected_lanes for lane in members)]
        p = pj_detail.get(k, {})
        a = anew_detail.get(k, {})
        v = v5_detail.get(k, {})
        rows.append({**h, 'race_state': current_states[k[0]],
                     **{lane: k in lane_sets[lane] for lane in LANES},
                     'selected_lanes': '|'.join(selected_lanes), 'raw_lane_count': len(selected_lanes),
                     'supported_families': '|'.join(supported_families), 'family_support_count': len(supported_families),
                     'pl_jockey_rank': p.get('candidate_rank'), 'pl_jockey_p_top3': p.get('candidate_p_top3'),
                     'pl_jockey_utility': p.get('candidate_utility'),
                     'a_new_rank': a.get('a_new_rank'), 'a_new_p_top3': a.get('a_new_p_top3'),
                     'e1_global_allocation_rank': e1_order.get(k),
                     'independent_v5_rank': v.get('shadow_ai_rank'), 'independent_v5_p_top3': v.get('p_top3')})
    by_key = {(r['race_id'], r['horse_number']): r for r in rows}
    overlap_keys = sorted(lane_sets['PL_JOCKEY'] & lane_sets['E1'])
    overlap = [by_key[k] for k in overlap_keys]
    triple = [r for r in overlap if r['A_NEW']]
    categories = {
        'PL_JOCKEY_ONLY': [r for r in rows if r['selected_lanes'] == 'PL_JOCKEY'],
        'E1_ONLY': [r for r in rows if r['selected_lanes'] == 'E1'],
        'PL_JOCKEY_E1': overlap,
        'PL_JOCKEY_E1_A_NEW': triple,
        'PL_JOCKEY_E1_V5': [r for r in overlap if r['INDEPENDENT_V5']],
        'CURRENT_NONBUY_PL_JOCKEY_E1': [r for r in overlap if not r['CURRENT']],
        'CURRENT_NONBUY_E1_V5': [r for r in rows if not r['CURRENT'] and r['E1'] and r['INDEPENDENT_V5']],
        'V5_ONLY': [r for r in rows if r['selected_lanes'] == 'INDEPENDENT_V5'],
        'CURRENT_ONLY': [r for r in rows if r['selected_lanes'] == 'CURRENT'],
        'RANK1_SELECTED': [r for r in rows if r['CURRENT_RANK1']],
    }
    OUT.mkdir(parents=True, exist_ok=False)
    csv_write(OUT / 'multi_lane_horse_matrix_20261101.csv', list(rows[0]), rows)
    csv_write(OUT / 'pl_jockey_e1_overlap_20261101.csv', list(rows[0]), overlap)
    race_lines = ['# 2026-11-01 7-lane PRE race summary', '', 'Result・odds・popularityを使用しない。空欄はNONEと記載。', '',
                  '| Race | Current | EXP024 | Rank1 | PL+J | A_new | E1 | V5 | PL+J×E1 |',
                  '|---|---|---|---|---|---|---|---|---|']
    def fmt(keys):
        return ' / '.join(f"#{by_key[k]['horse_number']} {by_key[k]['horse_name']}" for k in sorted(keys)) or 'NONE'
    for rid in sorted(payloads):
        venue, number = rid.split('_')[-2:]
        cells = [fmt(k for k in lane_sets[lane] if k[0] == rid) for lane in LANES]
        joint = fmt(k for k in overlap_keys if k[0] == rid)
        race_lines.append(f"| {venue} {number} | {' | '.join(cells)} | {joint} |")
    (OUT / 'race_summary_20261101.md').write_text('\n'.join(race_lines) + '\n', encoding='utf-8')
    summary_lines = ['# 2026-11-01 PRE consensus', '', '## 最重要観測集合: PL_JOCKEY ∩ E1', '',
                     '10/31の4/6は小標本のPOST診断であり、11/01の新BUYルール・優先順位ではない。', '',
                     '| Race | # | Horse | PL+J rank | PL+J p_top3 | E1 global rank | Current | EXP024 | A_new | V5 |',
                     '|---|---:|---|---:|---:|---:|---|---|---|---|']
    for r in overlap:
        summary_lines.append(f"| {r['race_id']} | {r['horse_number']} | {r['horse_name']} | {r['pl_jockey_rank']} | {r['pl_jockey_p_top3']:.6f} | {r['e1_global_allocation_rank']} | {r['CURRENT']} | {r['EXP024']} | {r['A_NEW']} | {r['INDEPENDENT_V5']} |")
    summary_lines += ['', f"PL_JOCKEY∩E1: {len(overlap)}頭。A_new追加一致: {len(triple)}頭（2者一致より上位扱いしない）。", '',
                      '## レーン選択数', '', '| Lane | Horses | Races |', '|---|---:|---:|']
    for lane in LANES:
        summary_lines.append(f"| {lane} | {len(lane_sets[lane])} | {len({k[0] for k in lane_sets[lane]})} |")
    summary_lines += ['', '## 重点集合', '', '| Category | Count | Horses |', '|---|---:|---|']
    for name, rr in categories.items():
        names = '; '.join('{} #{} {}'.format(r['race_id'], r['horse_number'], r['horse_name']) for r in rr) or 'NONE'
        summary_lines.append(f"| {name} | {len(rr)} | {names} |")
    summary_lines += ['', 'Family: CURRENT_FAMILY=Current+Rank1、PL_V1_FAMILY=EXP024+PL_JOCKEY+A_NEW+E1、V5_FAMILY=Independent V5。A_newはPL派生で独立familyではない。',
                      'Raw lane countは独立票数・BUY判断ではない。', 'Result access=0、odds/popularity input=0。']
    (OUT / 'consensus_summary_20261101.md').write_text('\n'.join(summary_lines) + '\n', encoding='utf-8')
    report = {'target_date': '2026-11-01', 'role': 'PRE_ONLY_MULTI_LANE_ANALYSIS_REFERENCE',
              'generated_at_jst': now.isoformat(), 'first_start_at': first, 'result_access': 0,
              'odds_used_as_input': False, 'popularity_used': False, 'new_buy_rule_created': False,
              'total_races': len(payloads), 'total_horses': len(rows), 'lane_selected_horses': {l: len(lane_sets[l]) for l in LANES},
              'lane_selected_races': {l: len({k[0] for k in lane_sets[l]}) for l in LANES},
              'formal_families': FAMILIES, 'a_new_is_pl_derivative': True,
              'pl_jockey_e1_overlap_count': len(overlap), 'pl_jockey_e1_a_new_count': len(triple),
              'categories': {name: [{'race_id': r['race_id'], 'horse_number': r['horse_number'], 'horse_name': r['horse_name']} for r in rr] for name, rr in categories.items()},
              'source_paths': {name: str(path) for name, path in sources.items()}, 'source_sha256': shas,
              'horses': rows, 'output_sha256': {name: sha(OUT / name) for name in ('multi_lane_horse_matrix_20261101.csv', 'pl_jockey_e1_overlap_20261101.csv', 'race_summary_20261101.md', 'consensus_summary_20261101.md')}}
    (OUT / 'consensus_20261101.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'lanes': report['lane_selected_horses'], 'overlap': len(overlap), 'triple': len(triple),
                      'output': str(OUT), 'json_sha256': sha(OUT / 'consensus_20261101.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
