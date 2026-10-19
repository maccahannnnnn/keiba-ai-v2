"""Additive PL reselection shadow. Never modifies the Current or PL runtime.

PRE construction reads frozen Current and invokes the frozen PL runner only.
Outcome aggregation is deliberately a separate API and requires a sealed PRE.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from review import pl_forward_shadow_v1 as pl
from review.current_environment_tree_hash_v1 import tree_hash as shared_tree_hash

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / 'docs/KeibaAI_PL_SAME_VOLUME_RESELECTION_SHADOW_V1_PROTOCOL.md'
PROTOCOL_SHA = '8f1adabf7e5798519ca73c5d58e36599547da39d039e4243cef51d282c618352'
MODEL_SHA = '418fc9b4cefe1757f79dfc22a7d49b7c1592b91084cca97f88f55bb1389b0585'
MANIFEST_SHA = '18443426b16dba4c28374d39841eeac0a98af4dd4e617b8ae8457dcee2f6494e'
INFERENCE_SHA = '1a36902f2afee91bd03f99394cc52bf15ba8a8e2b1e99afa009b8df159f8b3cc'
PL_CORE_SHA = '5df9e31df983516e015dec03c856f462e04e5bd63f50ac6616f367f5e64ab0ae'
VECTOR_CODE_SHA = '62ef8b831f597f335c43d20d0e470f73ce55ad4bcfe21b6f57c8d13db200ccc1'
FEATURE_CODE_SHA = '48daf9e9956b29f3db5eb179c113aa0d5155591aad68650a4c2fd16dfc71599e'
ENTRY = ROOT / 'review/target_bulk_prediction_input_shadow_v1.py'
DECISION = ROOT / 'engine/decision_engine.py'

class Stop(RuntimeError):
    pass

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')

def timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise Stop('STOP_TIMEZONE_REQUIRED')
    return dt.astimezone(timezone.utc)

def verify_authority() -> None:
    paths = [(PROTOCOL, PROTOCOL_SHA), (pl.MODEL_ROOT/pl.MODEL_FILE, MODEL_SHA),
             (pl.MODEL_ROOT/pl.MANIFEST_FILE, MANIFEST_SHA), (Path(pl.__file__), INFERENCE_SHA),
             (pl.ITER2_SOURCE, PL_CORE_SHA),
             (ROOT/'review/full_field_redesign_iter0_retry7.py', VECTOR_CODE_SHA),
             (ROOT/'review/ws2_deterministic_pre_only_regeneration_v1.py', FEATURE_CODE_SHA)]
    for path, digest in paths:
        if not path.is_file() or sha(path) != digest:
            raise Stop('STOP_FROZEN_AUTHORITY_MISMATCH:' + str(path))
    manifest = json.loads((pl.MODEL_ROOT/pl.MANIFEST_FILE).read_text(encoding='utf8'))
    if manifest.get('model_artifact_sha256') != MODEL_SHA:
        raise Stop('STOP_PL_MANIFEST_MODEL_MISMATCH')

def tree_hash(path: Path) -> str:
    return shared_tree_hash(path,error_factory=Stop,hash_file=sha)

def verify_current_provenance(current_root: Path, expected_date: str, *, require_tree_attestation: bool = True) -> dict:
    """Verify PRE-recorded authorities against working files; never fabricate historical trees."""
    manifest=json.loads((current_root/'prediction_manifest.json').read_text(encoding='utf8'))
    matches=[x for x in manifest.get('files',[]) if x.get('relative_path')=='provenance.json']
    provenance_path=current_root/'provenance.json'
    if len(matches)!=1 or not provenance_path.is_file() or sha(provenance_path)!=matches[0].get('sha256'):
        raise Stop('STOP_CURRENT_PROVENANCE_NOT_PINNED')
    value=json.loads(provenance_path.read_text(encoding='utf8'))
    fields=('git_head','runner_sha256','run_new_module_sha256','shadow_buy_engine_sha256',
            'buy_gate_trace_schema_sha256','buy_gate_trace_schema_version','target_date',
            'runner_path','run_new_module','buy_gate_trace_schema_path')
    missing=[name for name in fields if not value.get(name)]
    if missing:raise Stop('STOP_CURRENT_PROVENANCE_MISSING:' + ','.join(missing))
    if not value.get('target_bulk_prediction_input_adapter_sha256'):
        raise Stop('STOP_CURRENT_PRE_ADAPTER_PROVENANCE_MISSING')
    if value['target_date']!=expected_date:raise Stop('STOP_CURRENT_PROVENANCE_DATE_MISMATCH')
    if not re.fullmatch(r'[0-9a-fA-F]{40}',value['git_head']):raise Stop('STOP_CURRENT_PROVENANCE_GIT_HEAD_INVALID')
    targets={'runner_sha256':ROOT/'review/prospective_prediction_runner_v1.py',
             'run_new_module_sha256':ENTRY,'shadow_buy_engine_sha256':ROOT/'engine/shadow_buy_decision_engine.py',
             'buy_gate_trace_schema_sha256':ROOT/'docs/buy_gate_trace_schema_v1_1.json',
             'target_bulk_prediction_input_adapter_sha256':ROOT/'review/target_bulk_prediction_input_adapter_v1.py'}
    expected_paths={'runner_path':'review/prospective_prediction_runner_v1.py',
                    'run_new_module':'review/target_bulk_prediction_input_shadow_v1.py',
                    'buy_gate_trace_schema_path':'docs/buy_gate_trace_schema_v1_1.json'}
    for name,want in expected_paths.items():
        if str(value[name]).replace('\\','/')!=want:raise Stop('STOP_CURRENT_PROVENANCE_PATH_MISMATCH:' + name)
    if value['buy_gate_trace_schema_version']!='BUY_GATE_TRACE_SCHEMA_V1_1':raise Stop('STOP_CURRENT_TRACE_SCHEMA_UNSUPPORTED')
    for name,path in targets.items():
        if not re.fullmatch(r'[0-9a-fA-F]{64}',str(value[name])):raise Stop('STOP_CURRENT_PROVENANCE_SHA_INVALID:' + name)
        if not path.is_file() or sha(path)!=value[name].lower():raise Stop('ENVIRONMENT_PROVENANCE_MISMATCH:' + name)
    trees={f'{name}_tree_sha256':tree_hash(ROOT/name) for name in ('engine','evaluation','knowledge')}
    tree_missing=[name for name in trees if not value.get(name)]
    if require_tree_attestation and tree_missing:
        raise Stop('STOP_CURRENT_PRE_TREE_PROVENANCE_MISSING:' + ','.join(tree_missing))
    for name,observed in trees.items():
        if value.get(name) and value[name]!=observed:raise Stop('ENVIRONMENT_PROVENANCE_MISMATCH:' + name)
    stable={'git_head':value['git_head'].lower(),**{name:value[name].lower() for name in targets},
            'buy_gate_trace_schema_version':value['buy_gate_trace_schema_version'],**trees,
            'python_version':platform.python_version(),'numpy_version':np.__version__,
            'feature_transform_sha256':sha(ROOT/'review/ws2_deterministic_pre_only_regeneration_v1.py'),
            'iter0_vector_sha256':sha(ROOT/'review/full_field_redesign_iter0_retry7.py')}
    fingerprint=hashlib.sha256(canonical(stable)).hexdigest()
    return {'current_environment_fingerprint':fingerprint,'current_environment_components':stable,
            'block_fingerprint_sha256':fingerprint,'provenance_sha256':sha(provenance_path),
            'tree_provenance_status':'UNVERIFIED_MISSING_PRE_TREE_ATTESTATION' if tree_missing else 'VERIFIED',
            'missing_tree_provenance_fields':tree_missing,
            'runtime_identifier_source':'EXP024_BUILD_RUNTIME_NOT_PRE_RUNTIME'}

def environment_block(environment: dict, previous_fingerprint: str | None) -> dict:
    current=environment['current_environment_fingerprint']
    if previous_fingerprint is not None and not re.fullmatch(r'[0-9a-f]{64}',previous_fingerprint):
        raise Stop('STOP_PREVIOUS_FINGERPRINT_INVALID')
    changed=previous_fingerprint is not None and previous_fingerprint!=current
    return {'block_id':'BLOCK_'+current,'previous_environment_fingerprint':previous_fingerprint,
            'current_environment_fingerprint':current,'change_detected':changed,
            'cross_block_pooling_requires_human_review':True}

def build_race(payload: dict, pl_race: dict, pl_horses: list[dict]) -> dict:
    """Pure, read-only transformation of full-field PRE output."""
    rid = payload.get('race_id'); ranked = payload.get('ranked_results'); buys = payload.get('buys')
    trace = payload.get('buy_gate_trace', {})
    if not isinstance(ranked, list) or not isinstance(buys, list) or not isinstance(trace.get('horses'), list):
        raise Stop('STOP_CURRENT_PRE_TRACE_MISSING')
    def lookup(items):
        out = {int(x['horse_number']): x for x in items}
        if len(out) != len(items): raise Stop('STOP_DUPLICATE_HORSE')
        return out
    horses, traces = lookup(ranked), lookup(trace['horses'])
    current = sorted(lookup(buys))
    k = len(current)
    if k > 3 or set(traces) != set(horses) or not set(current) <= set(horses):
        raise Stop('STOP_CURRENT_BUY_SEMANTICS_OR_TRACE')
    if payload.get('buy_count') != k:
        raise Stop('STOP_CURRENT_BUY_COUNT_MISMATCH')
    top5 = set(lookup(payload.get('top5', [])))
    if len(top5) != min(5, len(horses)) or not top5 <= set(horses):
        raise Stop('STOP_CURRENT_TOP5_UNRESOLVED')
    for n in horses:
        if 'past_race_count' not in horses[n] or 'risk_guard_pass' not in traces[n]:
            raise Stop('STOP_REQUIRED_TRACE_UNAVAILABLE')
    status = pl_race.get('inference_status'); failure = pl_race.get('reason')
    selected = []
    all_rows = lookup(pl_horses)
    if set(all_rows) != set(horses): raise Stop('STOP_PL_FIELD_MISMATCH')
    tie_groups = []
    if status == 'AVAILABLE':
        vals = [(int(n), float(x['pl_top3_probability']), int(x['pl_race_rank'])) for n, x in all_rows.items()]
        if any(not math.isfinite(prob) or not 0 <= prob <= 1 for _, prob, _ in vals): raise Stop('STOP_PL_PROBABILITY_INVALID')
        if abs(sum(v[1] for v in vals)-3.0)>1e-8: raise Stop('STOP_PL_FORWARD_TOP3_SUM_FAILURE')
        if abs(float(pl_race['pl_probability_sum'])-sum(v[1] for v in vals))>1e-8: raise Stop('STOP_PL_SUM_INCONSISTENT')
        order = sorted(vals, key=lambda v: (-v[1], v[0]))
        if any(rank != i for i, (_, _, rank) in enumerate(order, 1)):
            raise Stop('STOP_FROZEN_PL_RANKING_MISMATCH')
        groups=defaultdict(list)
        for n, prob, _ in vals: groups[prob].append(n)
        tie_groups=[{'probability': prob, 'horse_numbers': sorted(ns)} for prob,ns in groups.items() if len(ns)>1]
        selected=[n for n, _, _ in order[:k]]
    elif status == 'INFERENCE_UNAVAILABLE':
        if not failure: raise Stop('STOP_PL_FAILURE_REASON_MISSING')
        status = 'PL_INFERENCE_FAILED'
    else:
        raise Stop('STOP_PL_INFERENCE_STATUS_UNRESOLVED')
    full=[]
    for n in sorted(horses):
        p=all_rows[n]; t=traces[n]; h=horses[n]
        full.append({'horse_number':n,'horse_name':h.get('horse_name'), 'current_buy':n in current,
                     'current_top5_flag':n in top5, 'current_rank':h.get('rank'),
                     'gate_statuses':{name:t.get(name) for name in ('absolute_quality_pass','relative_advantage_pass','effective_reliability_pass','risk_guard_pass')},
                     'past_race_count':h['past_race_count'],'low_history_flags':{'warnings':h.get('warnings'),'risks':h.get('risks')},
                     'pl_probability':p.get('pl_top3_probability'),'pl_rank':p.get('pl_race_rank')})
    return {'date':str(rid).split('_')[1],'race_id':rid,'race_state':trace.get('race',{}).get('shadow_race_state'),
            'current_buy_count':k,'treatment_buy_count':len(selected) if status=='AVAILABLE' or k==0 else None,
            'current_selected_horses':current,'treatment_selected_horses':selected if status=='AVAILABLE' or k==0 else None,
            'overlap_count':len(set(current)&set(selected)) if status=='AVAILABLE' or k==0 else None,
            'pl_only_horses':sorted(set(selected)-set(current)) if status=='AVAILABLE' or k==0 else None,
            'current_only_horses':sorted(set(current)-set(selected)) if status=='AVAILABLE' or k==0 else None,
            'pl_inference_status':status,'pl_probability_sum':pl_race.get('pl_probability_sum'),
            'failure_reason':failure,'tie_exists':bool(tie_groups),
            'tie_break_rule':'PL probability descending, horse_number ascending','tie_break_values':tie_groups,'horses':full}

def construct_selection(payloads: list[dict], pl_output: dict) -> list[dict]:
    races={x['race_id']:x for x in pl_output['races']}; horses=defaultdict(list)
    for x in pl_output['horses']: horses[x['race_id']].append(x)
    if len(races)!=len(pl_output['races']) or set(races)!={p['race_id'] for p in payloads}:
        raise Stop('STOP_PL_RACE_SET_MISMATCH')
    return [build_race(p,races[p['race_id']],horses[p['race_id']]) for p in sorted(payloads,key=lambda x:x['race_id'])]

def build_pre(current_root: Path, knowledge: Path, *, previous_environment_fingerprint: str | None = None) -> dict:
    verify_authority()
    manifest_path=current_root/'prediction_manifest.json'; index_path=current_root/'race_index.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf8'))
    for item in manifest['files']:
        path=current_root/item['relative_path']
        if not path.is_file() or sha(path)!=item['sha256']: raise Stop('STOP_CURRENT_PRE_HASH_MISMATCH')
    entries=json.loads(index_path.read_text(encoding='utf8'))['race_index']
    payloads=[json.loads((current_root/x['artifact']).read_text(encoding='utf8')) for x in entries]
    dates={str(x['race_id']).split('_')[1] for x in payloads}
    if len(dates)!=1 or len(entries)!=len({x['race_id'] for x in payloads}): raise Stop('STOP_CURRENT_RACE_SCOPE')
    date=dates.pop()
    if knowledge.resolve()!=(ROOT/'knowledge').resolve():raise Stop('STOP_NONCANONICAL_KNOWLEDGE_TREE')
    environment=verify_current_provenance(current_root,date)
    model, digest=pl.load_model()
    if digest!=MODEL_SHA: raise Stop('STOP_MODEL_SHA')
    output=pl.infer_payloads(model,[(date,x) for x in payloads],model_sha256=digest,input_pre_sha256=sha(manifest_path))
    races=construct_selection(payloads,output); eligible=[r for r in races if r['current_buy_count']>0]
    success=sum(r['pl_inference_status']=='AVAILABLE' for r in eligible)
    return {'date':date,'role':'PL_SAME_VOLUME_RESELECTION_SHADOW_V1','protocol_sha256':PROTOCOL_SHA,
            'pl_model_sha256':MODEL_SHA,'pl_manifest_sha256':MANIFEST_SHA,'pl_inference_code_sha256':INFERENCE_SHA,
            'current_prediction_sha256':sha(manifest_path),
            'current_prediction_source_files':[{'relative_path':x['relative_path'],'sha256':x['sha256']} for x in manifest['files']],
            'current_pre_root':str(current_root.resolve()),
            'current_environment':environment,
            'current_environment_fingerprint':environment['current_environment_fingerprint'],
            'current_environment_components':environment['current_environment_components'],
            **environment_block(environment,previous_environment_fingerprint),
            'pl_inference_coverage':{'successful_races':success,'current_buy_races':len(eligible),
                                     'rate':success/len(eligible) if eligible else None},'races':races}

def freeze_pre(selection: dict, output_root: Path, *, first_start_evidence: Path, first_start_evidence_sha: str,
               authorization: Path, authorization_sha: str) -> dict:
    """Exclusive PRE seal; schedule evidence must be supplied and SHA pinned by caller."""
    verify_authority()
    if output_root.exists(): raise Stop('STOP_OUTPUT_EXISTS')
    if sha(authorization)!=authorization_sha: raise Stop('STOP_AUTHORIZATION_SHA_MISMATCH')
    approval=json.loads(authorization.read_text(encoding='utf8'))
    if (approval.get('protocol_sha256')!=PROTOCOL_SHA or approval.get('implementation_sha256')!=sha(Path(__file__))
        or approval.get('claude_implementation_review')!='PASS' or approval.get('human_final_implementation_approval') is not True):
        raise Stop('STOP_PROSPECTIVE_EVIDENCE_NOT_AUTHORIZED')
    if selection.get('current_environment',{}).get('tree_provenance_status')!='VERIFIED':
        raise Stop('STOP_CURRENT_PRE_TREE_PROVENANCE_MISSING')
    current_root=Path(selection['current_pre_root'])
    if sha(current_root/'prediction_manifest.json')!=selection['current_prediction_sha256']:
        raise Stop('ENVIRONMENT_PROVENANCE_MISMATCH:current_prediction_manifest')
    environment=verify_current_provenance(current_root,selection['date'])
    if environment['current_environment_fingerprint']!=selection.get('current_environment_fingerprint'):
        raise Stop('ENVIRONMENT_PROVENANCE_MISMATCH:environment_changed_after_build')
    if sha(first_start_evidence)!=first_start_evidence_sha: raise Stop('STOP_SCHEDULE_SHA_MISMATCH')
    schedule=json.loads(first_start_evidence.read_text(encoding='utf8'))
    if schedule.get('date')!=selection['date']: raise Stop('STOP_SCHEDULE_DATE_MISMATCH')
    first=timestamp(schedule['first_start_at']); now=datetime.now(timezone.utc)
    if now>=first: raise Stop('STOP_NOT_BEFORE_FIRST_START')
    output_root.mkdir(parents=True)
    data=canonical(selection); path=output_root/'selection.json'
    with path.open('xb') as f: f.write(data)
    frozen=datetime.now(timezone.utc)
    if frozen>=first: raise Stop('STOP_FREEZE_AFTER_FIRST_START')
    seal={'selection_sha256':hashlib.sha256(data).hexdigest(),'selection_freeze_timestamp':frozen.isoformat(),
          'first_start_at':first.isoformat(),'schedule_source_sha256':first_start_evidence_sha,'schedule_source_path':str(first_start_evidence),
          'authorization_sha256':authorization_sha,
          'result_access_before_freeze':False,'protocol_sha256':PROTOCOL_SHA}
    with (output_root/'selection_freeze.json').open('xb') as f:f.write(canonical(seal))
    return seal

def paired_race(race: dict, results: dict[int, dict]) -> dict:
    current=race['current_selected_horses']; treatment=race['treatment_selected_horses']
    if race['pl_inference_status']!='AVAILABLE':
        return {'race_id':race['race_id'],'pair_valid':False,'reason':'PL_INFERENCE_FAILED'}
    def stat(numbers):
        v=[results[n] for n in numbers if results[n]['valid_result']]
        return {'prediction_count':len(numbers),'valid_count':len(v),'hits':sum(bool(x['actual_top3']) for x in v)}
    c,t=stat(current),stat(treatment); valid=c['valid_count']==t['valid_count']
    return {'race_id':race['race_id'],'current':c,'treatment':t,'pair_valid':valid,
            'reason':None if valid else 'VALID_SELECTED_COUNT_MISMATCH','race_top3_delta':t['hits']-c['hits'],
            'sensitivity_delta_invalid_as_miss':t['hits']-c['hits']}

def date_cluster_bootstrap(rows: list[dict], iterations: int=10000, seed: int=20261018) -> dict:
    grouped=defaultdict(list)
    for x in rows:
        if x['pair_valid']: grouped[x['date']].append(x['race_top3_delta'])
    dates=sorted(grouped)
    if not dates: return {'mean_delta':None,'ci_lower':None,'ci_upper':None}
    rng=np.random.default_rng(seed); draws=[]
    for _ in range(iterations):
        sampled=rng.integers(0,len(dates),size=len(dates))
        values=[v for i in sampled for v in grouped[dates[int(i)]]]
        draws.append(float(np.mean(values)))
    values=[v for d in dates for v in grouped[d]]
    return {'mean_delta':float(np.mean(values)),'ci_lower':float(np.percentile(draws,2.5)),
            'ci_upper':float(np.percentile(draws,97.5)),'iterations':iterations,'seed':seed,'cluster':'DATE'}

def _join_results_for_selection(selection: dict, primary: Path, auxiliary: Path) -> list[dict]:
    """Shared result join used only after the caller has fixed its selection."""
    import csv
    from review.target_daily_result_list_schema_v2_validator import validate_source_pair
    from review.all_active_systems_post_diagnostic_v1 import _crosscheck_finish_order, _outcome
    from review.daily_v5_same_volume_prospective_post import VENUE_TO_JA
    pair=validate_source_pair(primary,auxiliary,selection['date'])
    if pair.get('status')!='PASS': raise Stop('STOP_RESULT_PAIR_INVALID')
    def rows(p):
        with p.open(encoding='cp932',newline='') as f:values=list(csv.reader(f))
        indexed={x[0]:x for x in values}
        if len(indexed)!=len(values):raise Stop('STOP_RESULT_DUPLICATE_KEY')
        return indexed
    a,b=rows(primary),rows(auxiliary);index=pair['source_d_primary']['race_index']
    if set(a)!=set(b): raise Stop('STOP_RESULT_RACE_SET_MISMATCH')
    _crosscheck_finish_order(a,b,index)
    lookup={(v['venue_name'],int(v['race_number'])):key for key,v in index.items()}
    if len(lookup)!=len(index): raise Stop('STOP_RESULT_DUPLICATE_RACE')
    output=[]
    for race in selection['races']:
        if not race['current_buy_count']: continue
        parts=race['race_id'].split('_');key=lookup[(VENUE_TO_JA[parts[-2]],int(parts[-1].removesuffix('R')))]
        head=int(index[key]['head_count'])
        if head!=len(race['horses']): raise Stop('STOP_RESULT_HORSE_COUNT_MISMATCH')
        results={int(h['horse_number']):_outcome(a[key][11+int(h['horse_number'])]) for h in race['horses']}
        row=paired_race(race,results);row['date']=selection['date'];row['results']=results
        row['race_trace']=race;output.append(row)
    return output

def post_from_frozen(pre_root: Path, primary: Path, auxiliary: Path, output_root: Path, *, expected_freeze_sha256: str) -> dict:
    """Read Results only after verifying the immutable selection and time boundary."""
    verify_authority()
    if output_root.exists(): raise Stop('STOP_OUTPUT_EXISTS')
    seal_path=pre_root/'selection_freeze.json'
    if sha(seal_path)!=expected_freeze_sha256: raise Stop('STOP_FREEZE_AUTHORITY_SHA_MISMATCH')
    path=pre_root/'selection.json';seal=json.loads(seal_path.read_text(encoding='utf8'))
    if sha(path)!=seal['selection_sha256'] or seal['protocol_sha256']!=PROTOCOL_SHA: raise Stop('STOP_PRE_SEAL_INVALID')
    freeze=timestamp(seal['selection_freeze_timestamp']);first=timestamp(seal['first_start_at'])
    if freeze>=first: raise Stop('STOP_INVALID_PRE_FREEZE_TIME')
    selection=json.loads(path.read_text(encoding='utf8'))
    if selection.get('protocol_sha256')!=PROTOCOL_SHA: raise Stop('STOP_PRE_PROTOCOL_MISMATCH')
    # Clock is captured immediately before the first Result read.
    read_at=datetime.now(timezone.utc)
    if read_at<=freeze: raise Stop('STOP_RESULT_READ_BEFORE_FREEZE')
    output=_join_results_for_selection(selection,primary,auxiliary)
    report={'date':selection['date'],'role':'PROSPECTIVE_OBSERVATION_ONLY',
            'block_fingerprint_sha256':selection['current_environment']['block_fingerprint_sha256'],
            'selection_sha256':seal['selection_sha256'],'selection_freeze_timestamp':seal['selection_freeze_timestamp'],
            'result_read_timestamp':read_at.isoformat(),'result_source_sha256':{'primary':sha(primary),'auxiliary':sha(auxiliary)},
            'pl_inference_coverage':selection['pl_inference_coverage'],'races':output}
    if sha(path)!=seal['selection_sha256']:raise Stop('STOP_PRE_CHANGED_DURING_RESULT_JOIN')
    output_root.mkdir(parents=True)
    with (output_root/'post.json').open('xb') as f:f.write(canonical(report))
    return report

def summarize_block(posts: list[dict]) -> dict:
    """Calculate one environment block only; chronological checkpoint prefixes are fixed."""
    if not posts: raise Stop('STOP_NO_POST_DATES')
    block={p['block_fingerprint_sha256'] for p in posts}
    if len(block)!=1: raise Stop('STOP_CROSS_BLOCK_POOLING_REQUIRES_HUMAN_REVIEW')
    ordered=sorted(posts,key=lambda x:x['date'])
    if len({p['date'] for p in ordered})!=len(ordered):raise Stop('STOP_DUPLICATE_DATE')
    dates=[]; count=0;checkpoint1=None;checkpoint2=None
    for post in ordered:
        dates.append(post);count+=len(post['races'])
        if checkpoint1 is None and len(dates)>=12 and count>=60:checkpoint1=list(dates)
        if len(dates)>=24 and count>=120:checkpoint2=list(dates);break
    def aggregate(ps):
        allr=[r for p in ps for r in p['races']];paired=[r for r in allr if r['pair_valid']]
        c=sum(x['current']['hits'] for x in paired);t=sum(x['treatment']['hits'] for x in paired)
        n=sum(x['current']['valid_count'] for x in paired)
        current_rate=c/n if n else None;treatment_rate=t/n if n else None
        boot=date_cluster_bootstrap(paired)
        all_available=[r for r in allr if 'current' in r]
        sensitivity=sum(x['sensitivity_delta_invalid_as_miss'] for x in all_available)
        primary=t-c
        sign=lambda value: (value>0)-(value<0)
        human_review=sign(primary)!=sign(sensitivity)
        overall_n=sum(x['treatment']['valid_count'] for x in all_available)
        overall_hits=sum(x['treatment']['hits'] for x in all_available)
        return {'dates':len(ps),'eligible_races':len(allr),'pair_valid_races':len(paired),
                'excluded_races':[{'date':r['date'],'race_id':r['race_id'],'reason':r['reason']} for r in allr if not r['pair_valid']],
                'current_hits':c,'treatment_hits':t,'valid_selected_count':n,'current_rate':current_rate,'treatment_rate':treatment_rate,
                'kpi_headline_all_inference_success':{'hits':overall_hits,'valid_selected_count':overall_n,'rate':overall_hits/overall_n if overall_n else None},
                'rate_difference':(t-c)/n if n else None,'bootstrap':boot,'sensitivity_all_races_delta':sensitivity,
                'human_review_required':human_review,'better_races':sum(x['race_top3_delta']>0 for x in paired),
                'worse_races':sum(x['race_top3_delta']<0 for x in paired),'equal_races':sum(x['race_top3_delta']==0 for x in paired)}
    def gate(ps,final):
        x=aggregate(ps);headline=x['kpi_headline_all_inference_success']['rate'];kpi=headline is not None and headline>=0.4
        sup=x['bootstrap']['ci_lower'] is not None and x['bootstrap']['ci_lower']>0
        x.update({'kpi_gate':kpi,'superiority_gate':sup,'target_plus_6pt_reference':x['rate_difference'] is not None and x['rate_difference']>=0.06,
                  'verdict':'SHADOW_CANDIDATE_PASS' if kpi and sup and not x['human_review_required'] else ('HOLD_NO_GO' if final else 'NOT_PASSED'),
                  'futility_warning':not kpi and x['bootstrap']['mean_delta'] is not None and x['bootstrap']['mean_delta']<=0})
        return x
    daily=[{'date':p['date'],**aggregate([p])} for p in ordered]
    months=defaultdict(list)
    for p in ordered:months[p['date'][:6]].append(p)
    monthly=[{'month':month,**aggregate(ps)} for month,ps in sorted(months.items())]
    lodo=[{'left_out':p['date'],**aggregate([q for q in ordered if q['date']!=p['date']])} for p in ordered if len(ordered)>1]
    all_pairs=[r for p in ordered for r in p['races'] if r.get('pair_valid')]
    secondary=secondary_metrics(all_pairs)
    first_gate=gate(checkpoint1,False) if checkpoint1 else None
    # A checkpoint-1 pass stops advancement and awaits Human review, not an automatic second gate.
    final_gate=gate(checkpoint2,True) if checkpoint2 and first_gate and first_gate['verdict']!='SHADOW_CANDIDATE_PASS' else None
    return {'block_fingerprint_sha256':next(iter(block)),'observed':aggregate(ordered),
            'checkpoint_1':first_gate,'checkpoint_2_final':final_gate,
            'daily':daily,'monthly':monthly,'chronological_blocks':daily,'leave_one_date_out':lodo,
            'concentration':{'largest_absolute_daily_delta':max((abs(x['treatment_hits']-x['current_hits']) for x in daily),default=0)},
            'secondary':secondary,'no_automatic_cross_block_pooling':True}

def secondary_metrics(rows: list[dict]) -> dict:
    overlap=0;selection_count=0;outside=[];current_pl_ranks=[];pl_only=[];current_only=[]
    rank1=Counter();race_success={'current':0,'treatment':0};rank1_hits=0;rank1_n=0
    for row in rows:
        trace=row['race_trace'];results=row['results'];result=lambda n:results.get(n,results.get(str(n)))
        current=trace['current_selected_horses']; treatment=trace['treatment_selected_horses']
        overlap+=trace['overlap_count'];selection_count+=len(treatment)
        race_success['current']+=row['current']['hits']>0;race_success['treatment']+=row['treatment']['hits']>0
        bynum={h['horse_number']:h for h in trace['horses']}
        pl_only.extend({'date':row['date'],'race_id':row['race_id'],'horse_number':n} for n in trace['pl_only_horses'])
        current_only.extend({'date':row['date'],'race_id':row['race_id'],'horse_number':n} for n in trace['current_only_horses'])
        current_pl_ranks.extend(bynum[n]['pl_rank'] for n in current)
        outside.extend(result(n) for n in treatment if not bynum[n]['current_top5_flag'])
        p=[h for h in trace['horses'] if h['pl_rank']==1];c=[h for h in trace['horses'] if h['current_rank']==1]
        if len(p)==1:
            pl_result=result(p[0]['horse_number'])
            if pl_result['valid_result']:
                rank1_n+=1;rank1_hits+=bool(pl_result['actual_top3'])
        if len(p)!=1 or len(c)!=1:
            rank1['CURRENT_RANK1_NOT_DEFINABLE']+=1;continue
        pr=result(p[0]['horse_number']);cr=result(c[0]['horse_number'])
        if not pr['valid_result'] or not cr['valid_result']:rank1['INVALID_RESULT']+=1;continue
        a,b=bool(pr['actual_top3']),bool(cr['actual_top3'])
        rank1['BOTH_CORRECT' if a and b else 'PL_ONLY_CORRECT' if a else 'CURRENT_ONLY_CORRECT' if b else 'BOTH_WRONG']+=1
    valid_outside=[x for x in outside if x['valid_result']]
    return {'raw_top3_hit_difference':sum(r['race_top3_delta'] for r in rows),
            'race_success_rate':{k:v/len(rows) if rows else None for k,v in race_success.items()},
            'overlap_rate':overlap/selection_count if selection_count else None,
            'pl_only_selected_horses':pl_only,'current_only_selected_horses':current_only,
            'pl_rank1_vs_current_rank1':dict(rank1),
            'pl_rank1_precision_diagnostic':{'hits':rank1_hits,'valid_n':rank1_n,'rate':rank1_hits/rank1_n if rank1_n else None},
            'outside_current_top5':{'count':len(outside),'selection_rate':len(outside)/selection_count if selection_count else None,
                                    'valid_n':len(valid_outside),'top3_rate':sum(x['actual_top3'] for x in valid_outside)/len(valid_outside) if valid_outside else None},
            'current_buy_pl_rank_distribution':dict(Counter(current_pl_ranks))}
