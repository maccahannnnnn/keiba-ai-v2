"""Result-blind, review-layer provisional PL Forward v1 + frozen jockey offset.

This module never runs Current, changes EXP-024, fits beta, or reads Result.
The caller supplies already-frozen Current and PL artifacts. No PRE is run on import.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from review import adaptive_pl_jockey_research_v1 as historical
from review import exp025_offset_pl_raw_history_v1 as identity
from review import jockey_context_cross_snapshot_pit_audit_v1 as pit
from review import pl_forward_shadow_v1 as forward
from review import post_ws2_jockey_mechanism_research_v1_model as jockey
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / 'models/pl_forward_shadow_v1/pl_forward_shadow_v1_model.json'
MODEL_SHA = '418fc9b4cefe1757f79dfc22a7d49b7c1592b91084cca97f88f55bb1389b0585'
BETA_PATH = ROOT / 'models/adaptive_pl_jockey_research_v1/integrated_model.json'
BETA_SHA = '66bf159125786e258fd671be5b823bdfd0b79b3a3bb0db7c2e93713245b8b376'
BETA = 1.1118321180295676
FEATURE_SHA = '11831ba888ee35c935b42d3713c523b13d8d1e1cfbed4096e0a3c60b27040a27'
HISTORY_MANIFEST = ROOT / 'models/adaptive_pl_jockey_research_v1/jockey_history_manifest.json'
HISTORY_SHA = '092debc076d2dc1b2524da759b9a21d8df845203729ae5c1ed0ba4aab074013c'
FORMAL_SNAPSHOT_MANIFEST = ROOT / 'docs/KeibaAI_JOCKEY_FORMAL_PRE_SNAPSHOT_MANIFEST_V1.json'
FORMAL_GENESIS_ENTRIES_SHA = 'd490ec635b9c263dcb5e29d6f384b2a837b8ce8686543613e5bef09d4b1d3629'
FORMAL_EXPECTED_PREFIX_SHA = '13a8696e01bddf3e98ef9a78b04666431a209aa3127a3bd533e0effa70d87773'
RUNTIME_DEPENDENCIES = {
    'review/adaptive_pl_jockey_research_v1.py': '6914f9942338a12ccf86e1762bf56ec4fc1ff031d8462009d22f06486f98c73d',
    'review/pl_adaptive_shadow_v1.py': '2ab88d7da2aec0802b43a60d89fc1ea81a5cf89d44436c9cbfcfb9ffbe4fc109',
    'review/jockey_context_cross_snapshot_pit_audit_v1.py': '30a49b9be5bafaa50380ff39887492e11f28d16a6a0482352c36b2e6123009d7',
    'review/post_ws2_jockey_mechanism_research_v1_preonly.py': '390eea727bd338f22bece3928a0987786a2ba5002498203c82498bce7558b695',
    'review/post_ws2_jockey_mechanism_research_v1_model.py': FEATURE_SHA,
}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def verify_identity() -> tuple[dict, float]:
    for path, expected in ((MODEL_PATH, MODEL_SHA), (BETA_PATH, BETA_SHA),
                           (Path(jockey.__file__), FEATURE_SHA), (HISTORY_MANIFEST, HISTORY_SHA)):
        if not path.is_file() or sha(path) != expected:
            raise Stop('STOP_FROZEN_AUTHORITY_SHA:' + str(path))
    for relative, expected in RUNTIME_DEPENDENCIES.items():
        path = ROOT / relative
        if not path.is_file() or sha(path) != expected:
            raise Stop('STOP_RUNTIME_DEPENDENCY_SHA:' + relative)
    model, model_sha = forward.load_model()
    beta = load(BETA_PATH)
    if (model_sha != MODEL_SHA or beta.get('feature') != jockey.FEATURE or
            beta.get('feature_implementation_sha256') != FEATURE_SHA or
            type(beta.get('beta_jockey')) is not float or beta['beta_jockey'] != BETA or
            beta.get('kappa') != 10 or beta.get('scaling') != 'NONE'):
        raise Stop('STOP_FROZEN_MODEL_OR_BETA_IDENTITY')
    return model, beta['beta_jockey']


def validate_formal_manifest(date: str, *, require_target_entry: bool = True,
                             value: dict | None = None) -> list[dict]:
    """Append-only registry: no expected prior formal date can disappear."""
    if value is None:
        value = load(FORMAL_SNAPSHOT_MANIFEST)
    if value.get('manifest_version') != 1:
        raise Stop('STOP_FORMAL_SNAPSHOT_MANIFEST_VERSION')
    expected = value.get('expected_formal_pre_dates')
    entries = value.get('entries')
    if not isinstance(expected, list) or not isinstance(entries, list):
        raise Stop('STOP_FORMAL_SNAPSHOT_MANIFEST_SCHEMA')
    if (len(expected) < 3 or hashlib.sha256(canonical(expected[:3])).hexdigest() != FORMAL_EXPECTED_PREFIX_SHA or
            len(entries) < 2 or hashlib.sha256(canonical(entries[:2])).hexdigest() != FORMAL_GENESIS_ENTRIES_SHA):
        raise Stop('STOP_FORMAL_SNAPSHOT_GENESIS_CHANGED')
    dates = [str(row.get('date')) for row in entries]
    if (expected != sorted(set(expected)) or dates != sorted(set(dates)) or
            any(d not in expected for d in dates)):
        raise Stop('STOP_FORMAL_SNAPSHOT_DUPLICATE_OR_ORDER')
    for index, row in enumerate(entries[2:], start=2):
        preceding_sha = hashlib.sha256(canonical(entries[:index])).hexdigest()
        if row.get('previous_entries_sha256') != preceding_sha:
            raise Stop('STOP_FORMAL_SNAPSHOT_APPEND_CHAIN:' + str(row.get('date')))
    required = {d for d in expected if d < date or (require_target_entry and d == date)}
    missing = required - set(dates)
    if missing:
        raise Stop('STOP_EXPECTED_FORMAL_PRE_SNAPSHOT_MISSING:' + ','.join(sorted(missing)))
    if require_target_entry and date not in dates:
        raise Stop('STOP_TARGET_FORMAL_PRE_SNAPSHOT_MISSING:' + date)
    output = []
    for row in entries:
        snapshot_date = row['date']
        if snapshot_date > date or (snapshot_date == date and not require_target_entry):
            continue
        for name in ('current_pre_path', 'current_pre_sha256', 'ds_snapshot_path', 'ds_snapshot_sha256',
                     'input_manifest_path', 'input_manifest_sha256', 'status'):
            if not row.get(name):
                raise Stop('STOP_FORMAL_SNAPSHOT_REQUIRED_FIELD:' + snapshot_date + ':' + name)
        if row['status'] != 'FROZEN_PRE_SOURCE':
            raise Stop('STOP_FORMAL_SNAPSHOT_STATUS:' + snapshot_date)
        if snapshot_date not in row['current_pre_path']:
            raise Stop('STOP_FORMAL_SNAPSHOT_DATE_PROVENANCE:' + snapshot_date)
        paths = {name: ROOT / row[name] for name in ('current_pre_path', 'ds_snapshot_path', 'input_manifest_path')}
        for name, path in paths.items():
            expected_sha = row[name.replace('_path', '_sha256')]
            if not path.is_file() or sha(path) != expected_sha:
                raise Stop('STOP_FORMAL_SNAPSHOT_SHA:' + snapshot_date + ':' + name)
        input_manifest = load(paths['input_manifest_path'])
        source = input_manifest.get('sources', {}).get('DS')
        if (not isinstance(source, dict) or source.get('sha256') != row['ds_snapshot_sha256'] or
                (ROOT / str(source.get('path', '')).replace('\\', '/')).resolve() != paths['ds_snapshot_path'].resolve() or
                paths['current_pre_path'].parent != paths['input_manifest_path'].parent):
            raise Stop('STOP_FORMAL_SNAPSHOT_PROVENANCE:' + snapshot_date)
        output.append(row)
    return output


def snapshot_manifest(date: str, target_ds: Path, current_input_manifest: Path | None = None) -> list[dict]:
    """Historical authority plus every registered formal PRE snapshot through date."""
    frozen = load(HISTORY_MANIFEST)
    authorities = {item['date']: item for item in frozen['authorities']}
    result = []
    for snapshot_date in pit.EXPECTED_DATES:
        if snapshot_date > date:
            continue
        if snapshot_date not in authorities:
            raise Stop('STOP_JOCKEY_SNAPSHOT_AUTHORITY:' + snapshot_date)
        item = authorities[snapshot_date]
        path = ROOT / item['ds_path']
        authority_path = ROOT / item['authority_artifact']
        if (not path.is_file() or not authority_path.is_file() or
                sha(path) != item['ds_sha256_expected'] or
                sha(authority_path) != item['authority_artifact_sha256'] or not item['match']):
            raise Stop('STOP_JOCKEY_SNAPSHOT_SHA:' + snapshot_date)
        result.append({'snapshot_date': snapshot_date, 'path': item['ds_path'],
                       'sha256': sha(path), 'included': True, 'authority_path': item['authority_artifact'],
                       'authority_sha256': item['authority_artifact_sha256'], 'reason_for_exclusion': None})
    formal = validate_formal_manifest(date)
    for row in formal:
        if row['date'] == date and (ROOT / row['ds_snapshot_path']).resolve() != target_ds.resolve():
            raise Stop('STOP_TARGET_DS_AUTHORITY_MISMATCH')
        if row['date'] == date and (current_input_manifest is None or
                                    (ROOT / row['input_manifest_path']).resolve() != current_input_manifest.resolve()):
            raise Stop('STOP_TARGET_INPUT_MANIFEST_AUTHORITY_MISMATCH')
        result.append({'snapshot_date': row['date'], 'path': row['ds_snapshot_path'],
                       'sha256': row['ds_snapshot_sha256'], 'included': True,
                       'authority_path': row['input_manifest_path'],
                       'authority_sha256': row['input_manifest_sha256'], 'reason_for_exclusion': None})
    if len(result) != len({item['snapshot_date'] for item in result}):
        raise Stop('STOP_DUPLICATE_SNAPSHOT_DATE')
    return result


def _snapshot_records(date: str, de_path: Path, ds_path: Path, expected_keys: set[tuple[str, int]]) -> tuple[list[dict], list[dict]]:
    adapter = TargetBulkPredictionInputAdapterV1()
    de, ds = identity.read_source(de_path, 33), identity.read_source(ds_path, 50)
    by_ds = defaultdict(list)
    for row in ds:
        by_ds[tuple(identity.clean(row[i]) for i in (16, 44, 46))].append(row)
    targets, records = [], []
    for row in de:
        rid = identity.race_id(date, identity.clean(row[1]), identity.integer(row[2]))
        number = identity.integer(row[3])
        if (rid, number) not in expected_keys:
            raise Stop('STOP_CURRENT_DE_SCOPE_MISMATCH')
        ident = tuple(identity.clean(row[i]) for i in (7, 16, 20))
        if ident not in by_ds:
            raise Stop('STOP_JOCKEY_TARGET_DS_IDENTITY:' + rid)
        targets.append({'date': date, 'race_id': rid, 'horse_number': number, 'horse_name': ident[0],
                        'horse_identity': ident, 'current_jockey_normalized': pit.normalize_jockey(row[10])})
        for history in adapter.valid_history_rows(by_ds[ident]):
            hd = identity.ds_date(history)
            if hd >= date:
                raise Stop('STOP_JOCKEY_PIT_HISTORY_DATE')
            records.append({'snapshot_date': date, 'horse_identity': ident,
                            'historical_race_id': adapter._race_id(hd, identity.clean(history[4]), identity.integer(history[6])),
                            'historical_race_date': hd, 'historical_jockey_normalized': pit.normalize_jockey(history[19]),
                            'field_size': history[21], 'finish': history[23], 'completed_valid': True})
    if len(targets) != len(expected_keys):
        raise Stop('STOP_CURRENT_DE_SCOPE_MISMATCH')
    return targets, records


def selection_for_race(payload: dict, pl_rows: list[dict], feature: dict, model: dict, beta: float) -> dict:
    rid = payload['race_id']
    field = payload['ranked_results']
    current = sorted(int(row['horse_number']) for row in payload['buys'])
    k = len(current)
    numbers = {int(row['horse_number']) for row in field}
    if k > 3 or len(numbers) != len(field) or not set(current) <= numbers or payload['buy_count'] != k:
        raise Stop('STOP_CURRENT_K_OR_FIELD')
    mapped = {int(row['horse_number']): row for row in pl_rows}
    if set(mapped) != numbers:
        raise Stop('STOP_PL_CURRENT_HORSE_SET')
    try:
        records = forward._payload_records(payload, rid.split('_')[1])
        matrix = np.vstack([item['vector'] for item in records])
        mean = np.asarray(model['scaler']['mean'], dtype=float)
        scale = np.asarray(model['scaler']['scale'], dtype=float)
        coef = np.asarray(model['pl_coefficients'], dtype=float)
        utility = ((matrix - mean) / scale)[:, :19] @ coef
        base, _ = identity._top3_from_utility(utility)
        for index, record in enumerate(records):
            number = record['horse_number']
            if abs(float(base[index]) - float(mapped[number]['pl_top3_probability'])) > 1e-10:
                raise Stop('STOP_FROZEN_PL_PROBABILITY_REPRODUCTION:' + rid)
        lifts = np.asarray([float(feature[(rid.split('_')[1], rid, r['horse_number'])][jockey.FEATURE]) for r in records])
        if not np.all(np.isfinite(lifts)):
            raise Stop('STOP_JOCKEY_FEATURE_NONFINITE')
        adjusted = utility + beta * lifts
        probabilities, mass = identity._top3_from_utility(adjusted)
        if abs(mass - 3.0) > 1e-8:
            raise Stop('STOP_CANDIDATE_PROBABILITY_MASS')
        order = sorted(range(len(records)), key=lambda i: (-float(probabilities[i]), records[i]['horse_number']))
        selected = [records[i]['horse_number'] for i in order[:k]]
        return {'race_id': rid, 'current_selected_horses': current, 'candidate_selected_horses': selected,
                'current_k': k, 'candidate_k': len(selected), 'provisional_fallback_race': False,
                'fallback_reason': None, 'horses': [{'horse_number': records[i]['horse_number'],
                'horse_name': records[i]['horse_name'], 'candidate_utility': float(adjusted[i]),
                'jockey_top3_lift': float(lifts[i]), 'candidate_p_top3': float(probabilities[i]),
                'candidate_rank': order.index(i) + 1} for i in range(len(records))]}
    except (KeyError, ValueError, TypeError, IndexError) as error:
        # Only uncovered horse-level conditions fall back. Authority failures above still STOP.
        return {'race_id': rid, 'current_selected_horses': current, 'candidate_selected_horses': current,
                'current_k': k, 'candidate_k': k, 'provisional_fallback_race': True,
                'fallback_reason': 'UNCOVERED_HORSE_LEVEL_JOCKEY_CONDITION:' + type(error).__name__, 'horses': []}


def build_pre(current_root: Path, pl_prediction_path: Path, de_path: Path, ds_path: Path) -> dict:
    """Build a PRE-only candidate; all supplied artifacts must already be frozen."""
    model, beta = verify_identity()
    current_manifest_path = current_root / 'prediction_manifest.json'
    manifest = load(current_manifest_path)
    for entry in manifest['files']:
        if sha(current_root / entry['relative_path']) != entry['sha256']:
            raise Stop('STOP_CURRENT_PRE_SHA')
    source_manifest_path = current_root / 'input_manifest.json'
    source_manifest = load(source_manifest_path)
    for kind, supplied in (('DE', de_path), ('DS', ds_path)):
        source = source_manifest['sources'][kind]
        expected_path = ROOT / str(source['path']).replace('\\', '/')
        if expected_path.resolve() != supplied.resolve() or sha(supplied) != source['sha256']:
            raise Stop('STOP_CURRENT_INPUT_SHA:' + kind)
    provenance = load(current_root / 'provenance.json')
    if provenance.get('result_data_access_count') != 0:
        raise Stop('STOP_CURRENT_PRE_RESULT_ACCESS')
    entries = load(current_root / 'race_index.json')['race_index']
    payloads = [load(current_root / entry['artifact']) for entry in entries]
    dates = {p['race_id'].split('_')[1] for p in payloads}
    if len(dates) != 1 or len(payloads) != len({p['race_id'] for p in payloads}):
        raise Stop('STOP_CURRENT_PRE_DATE_OR_RACE')
    date = dates.pop()
    pl = load(pl_prediction_path)
    if (pl.get('model_sha256') != MODEL_SHA or pl.get('input_pre_artifact_sha256') != sha(current_manifest_path)
            or pl.get('result_fields_used') is not False):
        raise Stop('STOP_FROZEN_PL_ARTIFACT_IDENTITY')
    if {r['race_id'] for r in pl['races']} != {p['race_id'] for p in payloads}:
        raise Stop('STOP_PL_CURRENT_RACE_SET')
    if any(r['inference_status'] != 'AVAILABLE' for r in pl['races']):
        raise Stop('STOP_FROZEN_PL_UNAVAILABLE')
    expected = {(p['race_id'], int(h['horse_number'])) for p in payloads for h in p['ranked_results']}
    by_pl = defaultdict(list)
    for h in pl['horses']:
        by_pl[h['race_id']].append(h)
    if {(r, int(h['horse_number'])) for r, rows in by_pl.items() for h in rows} != expected:
        raise Stop('STOP_PL_CURRENT_HORSE_SET')
    snapshots = snapshot_manifest(date, ds_path, current_root / 'input_manifest.json')
    targets, today = _snapshot_records(date, de_path, ds_path, expected)
    _, history_snapshots, _ = historical.history_pool()
    history_snapshots = {d: rows for d, rows in history_snapshots.items() if d <= date}
    formal_entries = validate_formal_manifest(date)
    for entry in formal_entries:
        prior_date = entry['date']
        if prior_date >= date:
            continue
        prior_root = (ROOT / entry['current_pre_path']).parent
        prior_input = load(ROOT / entry['input_manifest_path'])['sources']['DE']
        prior_de = ROOT / str(prior_input['path']).replace('\\', '/')
        if not prior_de.is_file() or sha(prior_de) != prior_input['sha256']:
            raise Stop('STOP_PRIOR_DE_SOURCE_SHA:' + prior_date)
        scope = {(e['race_id'], int(h['horse_number'])) for e in load(prior_root / 'race_index.json')['race_index']
                 for h in load(prior_root / e['artifact'])['ranked_results']}
        _, prior_records = _snapshot_records(prior_date, prior_de, ROOT / entry['ds_snapshot_path'], scope)
        history_snapshots[prior_date] = prior_records
    history_snapshots[date] = today
    features = jockey.feature_map_asof(targets, history_snapshots)
    if set(features) != {(date, rid, number) for rid, number in expected}:
        raise Stop('STOP_JOCKEY_FEATURE_COVERAGE')
    races = [selection_for_race(p, by_pl[p['race_id']], features, model, beta) for p in sorted(payloads, key=lambda p: p['race_id'])]
    if any(r['candidate_k'] != r['current_k'] for r in races):
        raise Stop('STOP_SAME_RACE_SAME_K')
    return {'date': date, 'role': 'PROVISIONAL_PRIMARY_OPERATIONAL_CANDIDATE_PRE_ONLY',
            'production_status': 'UNCHANGED', 'formal_evidence_credit_at_creation': 0,
            'current_pre_sha256': sha(current_manifest_path), 'pl_prediction_sha256': sha(pl_prediction_path),
            'current_input_manifest_sha256': sha(source_manifest_path),
            'model_sha256': MODEL_SHA, 'beta': beta, 'beta_source_sha256': BETA_SHA,
            'jockey_feature_sha256': FEATURE_SHA, 'jockey_snapshot_manifest': snapshots,
            'jockey_snapshot_manifest_sha256': hashlib.sha256(canonical(snapshots)).hexdigest(),
            'formal_snapshot_authority_manifest_sha256': sha(FORMAL_SNAPSHOT_MANIFEST),
            'runtime_dependency_sha256': dict(RUNTIME_DEPENDENCIES),
            'eligible_race_count': len(races), 'candidate_selected_horse_count': sum(r['candidate_k'] for r in races),
            'current_selected_horse_count': sum(r['current_k'] for r in races),
            'fallback_race_ids': [r['race_id'] for r in races if r['provisional_fallback_race']],
            'fallback_race_count': sum(r['provisional_fallback_race'] for r in races),
            'result_access_count': 0, 'semantic_validation_result': 'PASS', 'races': races}


def audit_for_freeze(selection: dict, *, freeze_timestamp: str, first_race_timestamp: str,
                     first_race_authority_path: Path) -> dict:
    """Day-1 guard. Caller alone controls writing a new, immutable audit artifact."""
    if not first_race_authority_path.is_file():
        raise Stop('STOP_FIRST_RACE_AUTHORITY_MISSING')
    schedule = load(first_race_authority_path)
    if (schedule.get('date') != selection.get('date') or
            schedule.get('first_start_at') != first_race_timestamp):
        raise Stop('STOP_FIRST_RACE_AUTHORITY_MISMATCH')
    try:
        frozen = datetime.fromisoformat(freeze_timestamp.replace('Z', '+00:00'))
        start = datetime.fromisoformat(first_race_timestamp.replace('Z', '+00:00'))
    except ValueError as error:
        raise Stop('STOP_FREEZE_TIME_INVALID') from error
    if frozen.tzinfo is None or start.tzinfo is None or frozen.astimezone(timezone.utc) >= start.astimezone(timezone.utc):
        raise Stop('STOP_FREEZE_NOT_BEFORE_FIRST_RACE')
    if selection.get('result_access_count') != 0 or selection.get('semantic_validation_result') != 'PASS':
        raise Stop('STOP_PRE_SEMANTIC_OR_RESULT_ACCESS')
    return {'date': selection['date'], 'provisional_pre_status': 'READY_TO_FREEZE',
            'current_pre_sha256': selection['current_pre_sha256'], 'pl_prediction_sha256': selection['pl_prediction_sha256'],
            'beta_source_sha256': BETA_SHA, 'jockey_feature_sha256': FEATURE_SHA,
            'jockey_snapshot_manifest_sha256': selection['jockey_snapshot_manifest_sha256'],
            'formal_snapshot_authority_manifest_sha256': selection['formal_snapshot_authority_manifest_sha256'],
            'runtime_dependency_sha256': selection['runtime_dependency_sha256'],
            'eligible_race_count': selection['eligible_race_count'],
            'candidate_selected_horse_count': selection['candidate_selected_horse_count'],
            'current_selected_horse_count': selection['current_selected_horse_count'],
            'fallback_race_count': selection['fallback_race_count'], 'fallback_race_ids': selection['fallback_race_ids'],
            'freeze_timestamp': freeze_timestamp, 'first_race_timestamp': first_race_timestamp,
            'first_race_timestamp_authority_path': str(first_race_authority_path),
            'first_race_timestamp_authority_sha256': sha(first_race_authority_path),
            'result_access_count': 0, 'semantic_validation_result': 'PASS',
            'selection_sha256': hashlib.sha256(canonical(selection)).hexdigest()}


def freeze_pre(selection: dict, output_root: Path, *, first_race_authority_path: Path) -> dict:
    """Exclusive Result-blind freeze; the schedule source still requires Human authority review."""
    if output_root.exists():
        raise Stop('STOP_OUTPUT_EXISTS')
    schedule = load(first_race_authority_path)
    first = schedule.get('first_start_at')
    if not isinstance(first, str):
        raise Stop('STOP_FIRST_RACE_AUTHORITY_MISMATCH')
    now = datetime.now(timezone.utc).isoformat()
    audit = audit_for_freeze(selection, freeze_timestamp=now, first_race_timestamp=first,
                             first_race_authority_path=first_race_authority_path)
    output_root.mkdir(parents=True, exist_ok=False)
    try:
        with (output_root / 'selection.json').open('xb') as handle:
            handle.write(canonical(selection))
        frozen = datetime.now(timezone.utc).isoformat()
        audit = audit_for_freeze(selection, freeze_timestamp=frozen, first_race_timestamp=first,
                                 first_race_authority_path=first_race_authority_path)
        with (output_root / 'provisional_audit.json').open('xb') as handle:
            handle.write(canonical(audit))
    except Exception:
        # Preserve partial evidence for inspection rather than silently overwriting.
        raise
    return audit


def provisional_status_from_paired_counts(*, prospective_dates: int, eligible_comparison_races: int,
                                          candidate_minus_current_hits: int,
                                          candidate_minus_exp024_hits: int) -> dict:
    """Pure post-count guard; this module neither reads Result nor changes a selection."""
    if min(prospective_dates, eligible_comparison_races) < 0:
        raise Stop('STOP_PROSPECTIVE_COUNT_INVALID')
    ready = prospective_dates >= 5 and eligible_comparison_races >= 25
    suspended = ready and candidate_minus_current_hits <= -5
    return {'rollback_eligible': ready,
            'provisional_operational_status': 'SUSPENDED_PENDING_HUMAN_REVIEW' if suspended else 'ACTIVE_OR_PENDING',
            'operational_first_choice': 'CURRENT' if suspended else 'FROZEN_PL_V1_JOCKEY_OFFSET',
            'jockey_harm_warning': ready and candidate_minus_exp024_hits <= -5,
            'human_review_required': suspended or (ready and candidate_minus_exp024_hits <= -5),
            'beta_retuned': False}
