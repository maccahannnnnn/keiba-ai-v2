"""Independent POST evaluation of frozen A_new/B1 allocations; never selects again."""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from collections import Counter
from pathlib import Path

from review import a_new_global_b1_allocation_shadow_v1 as pre
from review import b1_prospective_diagnostic_v1 as b1
from review import candidate_generation_training_dataset_readiness_v1 as readiness
from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
E1_ROOT = Path('C:/Users/hikar/.codex/worktrees/e1-full-field-allocation-prospective-shadow-v1/keiba AI')
PRE_SHA = '5984dd6b349cbf634e276efa114a620c93d683621bcc87268d19c176bc832c36'
# B1: frozen PRE B1_CODE_SHA / B1 Evidence Authorization V1.
# Readiness: existing candidate_probability_daily_pre_runtime_feasibility_audit_v1/source_manifest.json.
READINESS_SHA = '6eff02b5b86ad9be4700c664492a7fd172cf5d5975df43dc230e5e44e5ddc53e'
Stop = pre.Stop


def evaluate_post(date: str, *, root: Path = ROOT, e1_root: Path = E1_ROOT,
                  a_root: Path = pre.ANEW_ROOT) -> dict:
    """Validate all PRE authorities before opening either official Result CSV."""
    if not isinstance(date, str) or re.fullmatch(r'[0-9]{8}', date) is None:
        raise Stop('STOP_POST_DATE_FORMAT')
    try:
        datetime.strptime(date, '%Y%m%d')
    except ValueError as error:
        raise Stop('STOP_POST_DATE_INVALID') from error
    if (pre.sha(Path(b1.__file__)) != pre.B1_CODE_SHA or
            pre.sha(Path(readiness.__file__)) != READINESS_SHA):
        raise Stop('STOP_POST_JUDGMENT_CODE_SHA')
    if pre.sha(Path(pre.__file__)) != PRE_SHA:
        raise Stop('STOP_PRE_CODE_SHA')
    sources = {}

    def load(path):
        sources[str(path.resolve())] = pre.sha(path)
        return pre.read(path)

    def frozen(folder):
        selection_path = folder / 'selection.json'
        selection, seal = load(selection_path), load(folder / 'freeze_manifest.json')
        if (selection.get('date') != date or seal.get('date') != date or
                seal.get('selection_sha256') != pre.sha(selection_path)):
            raise Stop('STOP_PRE_SELECTION_SHA_OR_DATE')
        return selection, seal

    shadow_dir = root / f'reports/a_new_global_b1_allocation_shadow_v1/daily_pre/{date}'
    shadow, seal = frozen(shadow_dir)
    if (date < '20261121' or shadow.get('lane') != pre.LANE or seal.get('lane') != pre.LANE or
            shadow.get('result_access_count') != 0 or seal.get('result_access_count') != 0 or
            shadow.get('b1_code_sha256') != pre.B1_CODE_SHA or seal.get('b1_code_sha256') != pre.B1_CODE_SHA or
            shadow.get('a_new_model', {}).get('model_sha256') != pre.MODEL_SHA or
            seal.get('a_new_model_sha256') != pre.MODEL_SHA or
            shadow.get('prospective_evidence_credit') != 0 or seal.get('prospective_evidence_credit') != 0 or
            seal.get('freeze_deadline') != shadow.get('freeze_deadline') or
            pre.moment(seal.get('freeze_timestamp_utc')) >= pre.moment(shadow.get('freeze_deadline'))):
        raise Stop('STOP_SHADOW_FREEZE_AUTHORITY')
    anew_dir = a_root / f'reports/a_new_prospective_shadow_v1/daily_pre/{date}'
    anew, anew_seal = frozen(anew_dir)
    if (shadow.get('a_new_selection_sha256') != pre.sha(anew_dir / 'selection.json') or
            shadow.get('a_new_freeze_sha256') != pre.sha(anew_dir / 'freeze_manifest.json') or
            anew.get('a_new_model_sha256') != pre.MODEL_SHA):
        raise Stop('STOP_A_NEW_UPSTREAM_SHA')
    current = root / f'reports/prospective_prediction_{date}_formal_trace_v1'
    manifest_path = current / 'prediction_manifest.json'
    manifest = load(manifest_path)
    if shadow.get('current_manifest_sha256') != pre.sha(manifest_path):
        raise Stop('STOP_CURRENT_MANIFEST_SHA')
    listed = set()
    for entry in manifest.get('files', []):
        name = entry['relative_path']
        path = (current / name).resolve()
        if path.parent != current.resolve() or name in listed or pre.sha(path) != entry['sha256']:
            raise Stop('STOP_CURRENT_PAYLOAD_SHA')
        sources[str(path)] = entry['sha256']
        listed.add(name)
    if not {'race_index.json', 'input_manifest.json'} <= listed:
        raise Stop('STOP_CURRENT_MANIFEST_SCHEMA')
    inputs = load(current / 'input_manifest.json')
    if (inputs.get('date') != date or shadow.get('current_input_manifest_sha256') != pre.sha(current / 'input_manifest.json') or
            shadow.get('input_sha256') != {k: v['sha256'] for k, v in b1.verified_input_sources(current, inputs).items()}):
        raise Stop('STOP_INPUT_SHA')
    current_seal = load(current / 'formal_freeze_attestation.json')
    first_path = (root / current_seal['first_start_evidence_path']).resolve()
    if (not first_path.is_relative_to(root.resolve()) or
            pre.sha(first_path) != current_seal.get('first_start_evidence_sha256') or
            pre.sha(first_path) != shadow.get('first_start_authority_sha256')):
        raise Stop('STOP_FIRST_START_AUTHORITY')
    first = load(first_path)
    if first.get('date') != date or pre.moment(first['first_start_at']) != pre.moment(shadow['freeze_deadline']):
        raise Stop('STOP_FIRST_START_AUTHORITY')
    if (shadow.get('current_freeze_sha256') != pre.sha(current / 'formal_freeze_attestation.json') or
            current_seal.get('prediction_manifest_sha256') != pre.sha(manifest_path) or
            current_seal.get('date') != date or current_seal.get('result_access_count') != 0 or
            pre.moment(current_seal.get('first_start_at')) != pre.moment(shadow['freeze_deadline']) or
            pre.moment(current_seal.get('freeze_timestamp_utc')) >= pre.moment(shadow['freeze_deadline'])):
        raise Stop('STOP_CURRENT_FREEZE_AUTHORITY')
    bdir = root / f'reports/formal_pre_daily/{date}/b1_diagnostic'
    bs, bf = frozen(bdir)
    ep = e1_root / f'reports/e1_full_field_allocation_prospective_shadow_v1/daily_pre/{date}'
    es, ef = frozen(ep)
    if (bs.get('current_prediction_sha256') != pre.sha(manifest_path) or
            bs.get('e1_selection_sha256') != pre.sha(ep / 'selection.json') or
            bs.get('e1_freeze_sha256') != pre.sha(ep / 'freeze_manifest.json') or
            bf.get('result_access_count') != 0 or ef.get('result_access_count') != 0):
        raise Stop('STOP_COMPARATOR_AUTHORITY')
    for comparator_seal in (bf, ef):
        stamp = comparator_seal.get('freeze_timestamp_utc', comparator_seal.get('e1_freeze_timestamp'))
        if pre.moment(stamp) >= pre.moment(shadow['freeze_deadline']):
            raise Stop('STOP_COMPARATOR_LATE')
    index = load(current / 'race_index.json')['race_index']
    fields, selected_current = {}, []
    for entry in index:
        if entry['artifact'] not in listed:
            raise Stop('STOP_CURRENT_ARTIFACT_NOT_LISTED')
        payload = load(current / entry['artifact'])
        rid = entry['race_id']
        if payload.get('race_id') != rid or rid in fields or rid.split('_')[1] != date:
            raise Stop('STOP_RACE_IDENTITY')
        fields[rid] = {int(h['horse_number']): h for h in payload['ranked_results']}
        if len(fields[rid]) != entry['horse_count'] or len(payload['buys']) != entry['buy_count']:
            raise Stop('STOP_CURRENT_COUNTS')
        selected_current += [{'race_id': rid, **h} for h in payload['buys']]
    selected = {pre.LANE: shadow['selected_horses'], 'CURRENT': selected_current,
                'B1': bs['selected_horses'], 'E1': es['selected_horses']}
    n = len(selected_current)
    if shadow.get('daily_current_buy_n') != n or shadow.get('selected_count') != n:
        raise Stop('STOP_DAILY_N')
    for lane, horses in selected.items():
        keys = [(h['race_id'], int(h['horse_number'])) for h in horses]
        if len(keys) != len(set(keys)) or len(keys) != n or max(Counter(k[0] for k in keys).values(), default=0) > 3:
            raise Stop('STOP_SELECTION_ALLOCATION:' + lane)
        for h in horses:
            actual = fields.get(h['race_id'], {}).get(int(h['horse_number']))
            if actual is None or h.get('horse_name') != actual.get('horse_name'):
                raise Stop('STOP_HORSE_IDENTITY:' + lane)
    # All PRE validation above is complete. No selection calculation is called.
    raw = root / 'data/raw/target/daily_result_list'
    primary, secondary = (raw / f'{prefix}_{date}.csv' for prefix in ('馬番順着順', '着順馬番'))
    result_shas = {str(p.resolve()): pre.sha(p) for p in (primary, secondary)}
    if validate_source_pair(primary, secondary, date).get('status') != 'PASS':
        raise Stop('STOP_RESULT_PAIR')
    with primary.open(encoding='cp932', newline='') as handle:
        rows = list(csv.reader(handle))
    results = {(r[1], int(r[2])): r for r in rows}
    if len(results) != len(rows):
        raise Stop('STOP_DUPLICATE_RESULT_RACE')
    outcomes = {}
    for lane, horses in selected.items():
        joined = []
        for h in horses:
            rid = h['race_id']
            _, _, venue, race = rid.split('_')
            key = (JAPANESE_VENUE[venue], int(race[:-1]))
            if key not in results:
                raise Stop('STOP_MISSING_RESULT_RACE')
            joined.extend(b1._join_rows(lane, rid, [int(h['horse_number'])], fields[rid], results[key], outcome))
        outcomes[lane] = joined
    if any(pre.sha(Path(p)) != digest for p, digest in {**sources, **result_shas}.items()):
        raise Stop('STOP_INPUT_CHANGED_DURING_POST')
    report = {'date': date, 'status': 'COMPLETE', 'role': 'SHADOW_POST_DIAGNOSTIC_ONLY',
              'post_evaluator_sha256': pre.sha(Path(__file__)),
              'pre_role_as_recorded': shadow.get('role'), 'prospective_evidence_credit': 0,
              'b1_adoption_evidence_credit': 0, 'metrics': {k: b1.metric(v) for k, v in outcomes.items()},
              'selected_horse_outcomes': outcomes, 'pre_sources_sha256': sources,
              'result_sources_sha256': result_shas, 'production_change': False, 'buy_rule_change': False}
    output = root / f'reports/a_new_global_b1_allocation_shadow_v1/daily_post/{date}'
    output.mkdir(parents=True, exist_ok=False)
    path = output / 'post_summary.json'
    with path.open('xb') as stream:
        stream.write(b1.canonical(report))
    return {'status': 'COMPLETE', 'path': str(path), 'sha256': pre.sha(path)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    print(evaluate_post(parser.parse_args().date))
