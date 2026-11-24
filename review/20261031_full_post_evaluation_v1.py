"""Result-only 2026-10-31 audit of previously frozen PRE selections."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review.candidate_generation_training_dataset_readiness_v1 import (
    JAPANESE_VENUE, outcome, parse_race_id, result_rows,
)

ROOT = Path(__file__).resolve().parents[1]
E1 = Path('C:/Users/hikar/.codex/worktrees/e1-full-field-allocation-prospective-shadow-v1/keiba AI')
ANEW = Path('C:/Users/hikar/.codex/worktrees/a-new-prospective-shadow-v1/keiba AI')
OUT = ROOT / 'reports/20261031_full_post_evaluation_v1'
DATE = '20261031'
LANES = ('CURRENT', 'EXP024', 'CURRENT_RANK1', 'PL_JOCKEY', 'A_NEW', 'E1', 'INDEPENDENT_V5')
FORMAL_FAMILIES = {
    'CURRENT_FAMILY': ('CURRENT', 'CURRENT_RANK1'),
    'PL_V1_FAMILY': ('EXP024', 'PL_JOCKEY', 'E1'),
    'V5_FAMILY': ('INDEPENDENT_V5',),
}


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(name: str, fields: list[str], records: list[dict]) -> None:
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)


def metrics(rows: list[dict]) -> dict:
    valid = [r for r in rows if r['valid_result']]
    hits = sum(r['actual_top3'] for r in valid)
    return {'selected': len(rows), 'valid': len(valid), 'invalid': len(rows) - len(valid),
            'hits': hits, 'misses': len(valid) - hits,
            'rate': hits / len(valid) if valid else None}


def percent(m: dict) -> str:
    return f"{100*m['rate']:.2f}%" if m['rate'] is not None else 'N/A'


def key(rid: str, no: int) -> tuple[str, int]:
    return rid, int(no)


def main() -> None:
    sources = {
        'result_horse_order': ROOT / f'data/raw/target/daily_result_list/馬番順着順_{DATE}.csv',
        'result_finish_order': ROOT / f'data/raw/target/daily_result_list/着順馬番_{DATE}.csv',
        'consensus_pre_matrix': ROOT / f'reports/20261031_multi_lane_consensus_v2/multi_lane_consensus_20261031.json',
        'current_manifest': ROOT / f'reports/prospective_prediction_{DATE}_formal_trace_v1/prediction_manifest.json',
        'exp024_selection': ROOT / f'reports/exp024_pl_same_volume/{DATE}_pre/selection.json',
        'current_rank1_selection': ROOT / f'reports/current_rank1_prospective_shadow_v2/{DATE}_pre/pre_selection.json',
        'pl_jockey_selection': ROOT / f'reports/frozen_pl_v1_jockey_offset_provisional_v1/{DATE}_pre/selection.json',
        'independent_selection': ROOT / f'reports/independent_race_selection_prospective/{DATE}_pre/selection_manifest.json',
        'a_new_recovery': ANEW / f'reports/a_new_prospective_shadow_v1_non_evidential_recovery/{DATE}/recovery_manifest.json',
        'a_new_formal_status': ANEW / f'reports/a_new_prospective_shadow_v1/date_status/{DATE}/status.json',
        'e1_selection': E1 / f'reports/e1_full_field_allocation_prospective_shadow_v1/daily_pre/{DATE}/selection.json',
        'e1_post': E1 / f'reports/e1_full_field_allocation_prospective_shadow_v1/daily_post/{DATE}/post.json',
    }
    assert all(p.is_file() for p in sources.values()), 'SOURCE_MISSING'
    pre = load(sources['consensus_pre_matrix'])
    assert pre['target_date'] == '2026-10-31' and pre['result_access_count'] == 0
    pre_horses = pre['horses']
    assert len(pre_horses) == 173 and len({key(h['race_id'], h['horse_number']) for h in pre_horses}) == 173
    assert len({h['race_id'] for h in pre_horses}) == 13
    source_sha = {name: digest(path) for name, path in sources.items()}
    assert source_sha['result_horse_order'] == 'a9c285c7c75e3f700876cfd5ec90bded495ee11885dd86388c3b1b4d9584e96c'
    assert source_sha['result_finish_order'] == 'b62c163a8f622f087e85ec21d1637aeda825140bcab936ba97fac715a5ae2032'
    assert source_sha['e1_selection'] == pre['source_sha256']['e1_selection']
    assert source_sha['a_new_recovery'] == pre['source_sha256']['a_new_recovery_manifest']
    assert source_sha['a_new_formal_status'] == pre['source_sha256']['a_new_formal_status']

    direct = {lane: set() for lane in LANES}
    for path in sorted((ROOT / f'reports/prospective_prediction_{DATE}_formal_trace_v1').glob('*_prediction.json')):
        race = load(path)
        direct['CURRENT'].update(key(race['race_id'], h['horse_number']) for h in race['buys'])
    for race in load(sources['exp024_selection'])['races']:
        direct['EXP024'].update(key(race['race_id'], n) for n in race['treatment_selected_horses'])
    for row in load(sources['current_rank1_selection'])['selections']:
        direct['CURRENT_RANK1'].add(key(row['race_id'], row['selected_horse_number']))
    for race in load(sources['pl_jockey_selection'])['races']:
        direct['PL_JOCKEY'].update(key(race['race_id'], n) for n in race['candidate_selected_horses'])
    recovery = load(sources['a_new_recovery'])
    assert recovery['evidence_credit'] == 0 and recovery['formal_status'] == 'NOT_COLLECTED'
    assert load(sources['a_new_formal_status'])['status'] == 'NOT_COLLECTED'
    direct['A_NEW'].update(key(h['race_id'], h['horse_number']) for h in recovery['selected_horses'])
    direct['E1'].update(key(h['race_id'], h['horse_number']) for h in load(sources['e1_selection'])['selected_horses'])
    for race in load(sources['independent_selection'])['races']:
        direct['INDEPENDENT_V5'].update(key(race['race_id'], h['horse_number']) for h in race['selected_horses'])
    for lane in LANES:
        matrix = {key(h['race_id'], h['horse_number']) for h in pre_horses if h[f'{lane}_selected']}
        assert matrix == direct[lane], f'PRE_MATRIX_MISMATCH:{lane}'

    result = result_rows(DATE)
    all_rows = []
    for horse in pre_horses:
        rid, no = key(horse['race_id'], horse['horse_number'])
        parsed_date, venue_en, race_no = parse_race_id(rid)
        assert parsed_date == DATE
        source = result[(JAPANESE_VENUE[venue_en], race_no)]
        assert no <= int(source[9]), f'RESULT_HORSE_MISSING:{rid}:{no}'
        valid, finish, hit = outcome(source, no)
        lanes = [lane for lane in LANES if (rid, no) in direct[lane]]
        families = [family for family, members in FORMAL_FAMILIES.items() if any(lane in lanes for lane in members)]
        all_rows.append({'date': '2026-10-31', 'race_id': rid, 'venue': JAPANESE_VENUE[venue_en],
                         'race_number': race_no, 'horse_number': no, 'horse_name': horse.get('horse_name_raw') or '',
                         'selected_lanes': '|'.join(lanes), 'formal_families': '|'.join(families),
                         'formal_family_count': len(families), 'current_buy': 'CURRENT' in lanes,
                         'finish': finish, 'result_status': 'VALID' if valid else source[11 + no].strip(),
                         'valid_result': valid, 'actual_top3': bool(hit) if valid else None,
                         **{f'{lane}_selected': lane in lanes for lane in LANES}})
    assert len(all_rows) == 173
    selected = [r for r in all_rows if r['selected_lanes']]
    lane_stats = {lane: metrics([r for r in all_rows if r[f'{lane}_selected']]) for lane in LANES}
    e1_post = load(sources['e1_post'])
    assert e1_post['evidence_date'] is True and e1_post['e1']['hits'] == lane_stats['E1']['hits']
    assert e1_post['e1']['valid'] == lane_stats['E1']['valid']
    assert e1_post['result_source_sha256']['horse_order'] == source_sha['result_horse_order']
    assert e1_post['result_source_sha256']['finish_order'] == source_sha['result_finish_order']
    categories = {
        '3_FAMILY': [r for r in all_rows if r['formal_family_count'] == 3],
        '2_FAMILY': [r for r in all_rows if r['formal_family_count'] == 2],
        '1_FAMILY': [r for r in all_rows if r['formal_family_count'] == 1],
        'CURRENT_ONLY': [r for r in all_rows if r['formal_families'] == 'CURRENT_FAMILY'],
        'PL_ONLY': [r for r in all_rows if r['formal_families'] == 'PL_V1_FAMILY'],
        'V5_ONLY': [r for r in all_rows if r['formal_families'] == 'V5_FAMILY'],
        'CURRENT_NONBUY_MULTI_FAMILY': [r for r in all_rows if not r['current_buy'] and r['formal_family_count'] >= 2],
    }
    family_stats = {name: metrics(rows) for name, rows in categories.items()}
    assert sum(family_stats[k]['selected'] for k in ('3_FAMILY', '2_FAMILY', '1_FAMILY')) == len([r for r in all_rows if r['formal_family_count'] > 0])
    OUT.mkdir(parents=True, exist_ok=False)
    write_csv('lane_performance_20261031.csv', ['lane', 'selected', 'valid', 'invalid', 'hits', 'misses', 'rate', 'evidence_role'],
              [{'lane': lane, **lane_stats[lane], 'evidence_role': 'NON_EVIDENTIAL_OPERATIONAL_RECOVERY' if lane == 'A_NEW' else 'FORMAL_EVIDENCE' if lane == 'E1' else 'POST_RESULT_DIAGNOSTIC'} for lane in LANES])
    write_csv('family_support_performance_20261031.csv', ['category', 'selected', 'valid', 'invalid', 'hits', 'misses', 'rate'],
              [{'category': name, **stat} for name, stat in family_stats.items()])
    write_csv('selected_horse_results_20261031.csv',
              ['date', 'race_id', 'venue', 'race_number', 'horse_number', 'horse_name', 'selected_lanes', 'formal_families',
               'formal_family_count', 'current_buy', 'finish', 'result_status', 'valid_result', 'actual_top3'] + [f'{l}_selected' for l in LANES], selected)

    race_groups = defaultdict(list)
    for row in all_rows:
        race_groups[row['race_id']].append(row)
    race_lines = ['# 2026-10-31 race-by-race POST', '', '凍結PREの13R・173頭を正式Resultへ結合。着順以外の敗因は推測しない。', '']
    for rid, rows in sorted(race_groups.items()):
        race_lines += [f'## {rows[0]["venue"]}{rows[0]["race_number"]} ({rid})', '', '| 馬番 | 馬名 | 選択lane | 正式family | 着順 | Top3 |', '|---:|---|---|---|---:|---|']
        for r in rows:
            if not r['selected_lanes']:
                continue
            race_lines.append(f"| {r['horse_number']} | {r['horse_name']} | {r['selected_lanes']} | {r['formal_families'] or 'A_NEW reference only'} | {r['finish'] if r['valid_result'] else r['result_status']} | {'YES' if r['actual_top3'] else 'NO' if r['valid_result'] else 'INVALID'} |")
        race_lines.append('')
    (OUT / 'race_by_race_post_20261031.md').write_text('\n'.join(race_lines), encoding='utf-8')

    special = [('京都8R #3', 'race_20261031_kyoto_8R', 3), ('東京6R #15', 'race_20261031_tokyo_6R', 15),
               ('東京7R #8', 'race_20261031_tokyo_7R', 8), ('京都9R #3', 'race_20261031_kyoto_9R', 3),
               ('東京7R #6', 'race_20261031_tokyo_7R', 6), ('東京10R #7', 'race_20261031_tokyo_10R', 7),
               ('東京12R #4', 'race_20261031_tokyo_12R', 4), ('東京12R #10', 'race_20261031_tokyo_12R', 10)]
    by_key = {key(r['race_id'], r['horse_number']): r for r in all_rows}
    specials = [{'label': label, **by_key[key(rid, no)]} for label, rid, no in special]
    summary_lines = ['# 2026-10-31 full POST evaluation', '', 'Role: POST_RESULT_DIAGNOSTIC; E1は正式Evidence、A_newは非Evidence参考成績。', '',
                     f"Result files: `{sources['result_horse_order']}` ({sources['result_horse_order'].stat().st_size} bytes, SHA256 `{source_sha['result_horse_order']}`); `{sources['result_finish_order']}` ({sources['result_finish_order'].stat().st_size} bytes, SHA256 `{source_sha['result_finish_order']}`).", '',
                     f'Result全体24R、凍結PRE評価対象13R・173頭。対象馬の無効結果は{sum(not r["valid_result"] for r in all_rows)}頭。', '',
                     '| Lane | Selected | Valid | Top3 | Rate | Role |', '|---|---:|---:|---:|---:|---|']
    for lane in LANES:
        m = lane_stats[lane]
        summary_lines.append(f"| {lane} | {m['selected']} | {m['valid']} | {m['hits']} | {percent(m)} | {'NON_EVIDENTIAL' if lane == 'A_NEW' else 'FORMAL_EVIDENCE' if lane == 'E1' else 'DIAGNOSTIC'} |")
    summary_lines += ['', '| Formal family support | Horses | Valid | Top3 | Rate |', '|---|---:|---:|---:|---:|']
    for name, m in family_stats.items():
        summary_lines.append(f"| {name} | {m['selected']} | {m['valid']} | {m['hits']} | {percent(m)} |")
    summary_lines += ['', 'Formal family定義: CURRENT=Current+Current Rank1、PL_V1=EXP024+PL_JOCKEY+E1、V5=Independent V5。A_newは含めない。', '',
                      '## 3-family / 2-family', '', '| Race | # | Horse | Families | Lanes | Finish | Top3 |', '|---|---:|---|---|---|---:|---|']
    for r in all_rows:
        if r['formal_family_count'] >= 2:
            summary_lines.append(f"| {r['venue']}{r['race_number']} | {r['horse_number']} | {r['horse_name']} | {r['formal_families']} | {r['selected_lanes']} | {r['finish'] if r['valid_result'] else r['result_status']} | {'YES' if r['actual_top3'] else 'NO' if r['valid_result'] else 'INVALID'} |")
    summary_lines += ['', '## 指定馬', '', '| Horse | Families | Lanes | Finish | Top3 |', '|---|---|---|---:|---|']
    for r in specials:
        summary_lines.append(f"| {r['label']} {r['horse_name']} | {r['formal_families']} | {r['selected_lanes']} | {r['finish'] if r['valid_result'] else r['result_status']} | {'YES' if r['actual_top3'] else 'NO' if r['valid_result'] else 'INVALID'} |")
    summary_lines += ['', 'HUMAN_BET_SET_NOT_IDENTIFIABLE: 凍結consensus artifactから実際の5頭集合を一意に復元できない。',
                      '', 'POST_HOC_POPULARITY_DIAGNOSTIC_AVAILABLE=NO: 指定Result listは着順・馬番であり当日人気順位を保持しない。人気による選抜・再評価なし。',
                      '', f"E1 formal POST: `{sources['e1_post']}`, SHA256 `{source_sha['e1_post']}`, evidence date count 1, state COLLECTING。", '',
                      'モデル・BUY・PRE・Productionは変更なし。']
    (OUT / 'post_evaluation_summary_20261031.md').write_text('\n'.join(summary_lines) + '\n', encoding='utf-8')
    report = {'target_date': '2026-10-31', 'status': 'COMPLETE', 'result_validation': 'PASS',
              'result_total_races': len(result), 'pre_evaluation_races': 13, 'pre_evaluation_horses': len(all_rows),
              'result_source': {k: {'path': str(sources[k]), 'size': sources[k].stat().st_size, 'sha256': source_sha[k]} for k in ('result_horse_order', 'result_finish_order')},
              'source_sha256': source_sha, 'lane_performance': lane_stats, 'family_support_performance': family_stats,
              'formal_family_definition': FORMAL_FAMILIES, 'three_family_horses': categories['3_FAMILY'],
              'two_family_horses': categories['2_FAMILY'], 'current_nonbuy_multi_family_horses': categories['CURRENT_NONBUY_MULTI_FAMILY'],
              'specified_horses': specials, 'human_bet_set': 'HUMAN_BET_SET_NOT_IDENTIFIABLE',
              'e1_post': {'status': 'COMPLETE', 'path': str(sources['e1_post']), 'sha256': source_sha['e1_post'],
                          'evidence_date_count': 1, 'state': 'COLLECTING'},
              'a_new': {'formal_status': 'NOT_COLLECTED', 'evidence_credit': 0},
              'post_hoc_popularity_diagnostic_available': False, 'pre_selection_changed': False,
              'model_changed': False, 'buy_rule_changed': False, 'training_executed': False,
              'production_changed': False}
    (OUT / 'post_evaluation_20261031.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'lanes': lane_stats, 'families': family_stats, 'out': str(OUT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
