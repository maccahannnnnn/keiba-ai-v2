"""Isolated, human-approved research fit; never activates an Adaptive model."""
from pathlib import Path
import hashlib
import json
import numpy as np
from review import pl_adaptive_shadow_v1 as adaptive
from review import post_ws2_jockey_mechanism_research_v1_model as jockey
from review import post_ws2_jockey_mechanism_research_v1_preonly as preonly
from review import exp025_offset_pl_raw_history_v1 as identity
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1

ROOT = adaptive.ROOT
OUT = ROOT / 'models/adaptive_pl_jockey_research_v1'
EXPECTED_ACTIVE = '8c8bd693f7b037e7e3f5c416e09ffec5266fd85ee2791dca4b8ac16e4008df15'

def key(row):
    return (str(row['date']), str(row['race_id']), int(row['horse_number']))

def digest(value):
    return hashlib.sha256(adaptive.canonical_bytes(value)).hexdigest()

def population(rows):
    sets = dict(dates=sorted({key(r)[0] for r in rows}),
                races=sorted({key(r)[:2] for r in rows}),
                horse_rows=sorted(key(r) for r in rows),
                valid_rows=sorted(key(r) for r in rows if r['valid_result']))
    return {'sets': sets, 'hashes': {k: digest(v) for k,v in sets.items()}}

def history_pool():
    targets, _, authorities, _ = preonly.target_and_snapshot_records()
    adapter = TargetBulkPredictionInputAdapterV1()
    snapshots = {}
    manifest = []
    for date in jockey.jockey_pit.EXPECTED_DATES:
        path = identity.source_path('DS', date)
        de_path = identity.source_path('DE', date)
        ds = identity.read_source(path, 50)
        manifest.append({'date':date,'DE':str(de_path),'DE_sha256':adaptive.sha(de_path),
                         'DS':str(path),'DS_sha256':adaptive.sha(path)})
        by_identity = {}
        for row in ds:
            ident = tuple(identity.clean(row[i]) for i in (16,44,46))
            by_identity.setdefault(ident, []).append(row)
        records = []
        for target in (t for t in targets if t['date']==date):
            ident = tuple(target['horse_identity'])
            lookup = ident
            if (date == identity.KNOWN_20260906['date'] and
                target['race_id'] == identity.KNOWN_20260906['race_id'] and
                target['horse_number'] == identity.KNOWN_20260906['horse_number']):
                lookup = (identity.KNOWN_20260906['ds_name'], *ident[1:])
            if lookup not in by_identity:
                raise RuntimeError('STOP_JOCKEY_ADAPTIVE_TRAIN_SET_MISMATCH')
            for row in adapter.valid_history_rows(by_identity[lookup]):
                hd = identity.ds_date(row)
                if hd >= date:
                    raise RuntimeError('STOP_HISTORY_PIT')
                records.append(dict(snapshot_date=date,horse_identity=ident,
                    historical_race_id=adapter._race_id(hd,identity.clean(row[4]),identity.integer(row[6])),
                    historical_race_date=hd,
                    historical_jockey_normalized=jockey.jockey_pit.normalize_jockey(row[19]),
                    field_size=row[21],finish=row[23],completed_valid=True))
        snapshots[date] = records
    return targets, snapshots, {'sources':manifest,'authorities':authorities}

def build():
    if OUT.exists():
        raise RuntimeError('STOP_RESEARCH_OUTPUT_EXISTS_NO_RETRY')
    adaptive._verify_forward_reference()
    jockey.verify_authorities()
    pointer, _, _ = adaptive._load_current_once()
    if pointer['model_sha256'] != EXPECTED_ACTIVE or pointer['training_cutoff']!='2026-10-17':
        raise RuntimeError('STOP_ACTIVE_AUTHORITY')
    protected = {p:adaptive.sha(p) for p in adaptive.MODEL_ROOT.rglob('*') if p.is_file()}
    OUT.mkdir(parents=True)
    adaptive.write_json(OUT/'execution_started.json',{'human_approved':True,'cutoff':'2026-10-18'})
    try:
        old_manifest=adaptive._load_json(ROOT/pointer['version_path']/'manifest.json')
        sources=old_manifest['training_input_identity']['eligible_pre_sources']
        scope=[(adaptive._date_compact(e['date']),e['pre_root']) for e in sources]
        scope.append(('20261018','reports/daily_pre_analysis_20261018/current_frozen'))
        added, audits, source_entries = {}, [], []
        for date,path in scope:
            audit, values, source = adaptive._preflight_date(date,path)
            audits.append(audit)
            if values is None:
                adaptive.write_json(OUT/'eligibility.json',audits)
                raise RuntimeError('STOP_RESEARCH_ADAPTIVE_1018_NOT_AVAILABLE' if date=='20261018' else 'STOP_PRIOR_ADAPTIVE_DATE_INVALID:'+date)
            added[date]=values
            source_entries.append(source)
        base=adaptive._base_rows()
        rows=base+[r for date in sorted(added) for r in added[date]]
        adaptive._assert_unique(rows)
        pop=population(rows)
        valid_races, excluded=adaptive.iter2.valid_pl_races(rows)
        pop.update(excluded_races=excluded,excluded_rows=[key(r) for r in rows if not r['valid_result']])
        adaptive.write_json(OUT/'training_population.json',pop)
        adaptive.write_json(OUT/'eligibility.json',audits)
        scaler,coef,fit=adaptive.iter2.pl_fit(rows)
        if not fit.get('optimizer_success'):
            raise RuntimeError('STOP_RESEARCH_ADAPTIVE_NUMERICAL')
        adaptive._assert_training_numerics(rows,scaler,coef)
        model=adaptive._model_value(scaler,coef,'20261018')
        model.update(model='ADAPTIVE_PL_RESEARCH_20261018',role='RESEARCH_FORWARD_PRE_MODEL')
        adaptive.write_json(OUT/'adaptive_model.json',model)
        input_sha,input_identity=adaptive._training_identity(base,added,source_entries)
        manifest=dict(training_cutoff='2026-10-18',result_cutoff='2026-10-18',research_only=True,
            active_model_changed=False,population_hashes=pop['hashes'],optimizer=fit,
            training_input_sha256=input_sha,training_input_identity=input_identity,
            model_sha256=adaptive.sha(OUT/'adaptive_model.json'),feature_set=model['pl_feature_names'])
        adaptive.write_json(OUT/'adaptive_manifest.json',manifest)
        targets,snapshots,history=history_pool()
        target_map={key(t):t for t in targets}
        if any(key(r) not in target_map for r in rows):
            raise RuntimeError('STOP_JOCKEY_ADAPTIVE_TRAIN_SET_MISMATCH')
        feature_targets=[target_map[key(r)] for r in rows]
        features=jockey.feature_map_asof(feature_targets,snapshots)
        if set(features)!={key(r) for r in rows}:
            raise RuntimeError('STOP_JOCKEY_ADAPTIVE_TRAIN_SET_MISMATCH')
        for row in rows:
            row.update(features[key(row)])
        if population(rows)['hashes']!=pop['hashes']:
            raise RuntimeError('STOP_JOCKEY_ADAPTIVE_TRAIN_SET_MISMATCH')
        adaptive.write_json(OUT/'jockey_history_manifest.json',history)
        try:
            beta,beta_audit=jockey.fit_jockey_offset(rows,scaler,coef)
        except Exception as error:
            raise RuntimeError('STOP_JOCKEY_BETA_NUMERICAL') from error
        # Technical probability and repeatability checks only; no performance evaluation.
        for group in identity._race_groups(rows).values():
            matrix=scaler.transform(np.asarray([r['features'] for r in group]))
            utility=matrix[:,:19]@coef
            base_p,_=adaptive.iter2.pl_top3(matrix,coef)
            zero,_=identity._top3_from_utility(utility)
            if not np.array_equal(base_p,zero):
                raise RuntimeError('STOP_ADAPTIVE_OFFSET_REPRODUCTION_FAILURE')
            u=utility+beta*np.asarray([r[jockey.FEATURE] for r in group])
            first,total=identity._top3_from_utility(u)
            second,_=identity._top3_from_utility(u)
            if abs(total-3)>1e-8 or not np.array_equal(first,second):
                raise RuntimeError('STOP_RESEARCH_DETERMINISM')
        integrated=dict(model='ADAPTIVE_PL_JOCKEY_RESEARCH_V1',role='RESEARCH_FORWARD_PRE_MODEL',
            training_cutoff='2026-10-18',adaptive_model_sha256=adaptive.sha(OUT/'adaptive_model.json'),
            beta_jockey=beta,feature=jockey.FEATURE,kappa=10,scaling='NONE',
            feature_implementation_sha256=adaptive.sha(Path(jockey.__file__)),
            formal_prospective_evidence_credit=0,production_authority='NONE')
        adaptive.write_json(OUT/'integrated_model.json',integrated)
        adaptive.write_json(OUT/'integrated_manifest.json',dict(integrated_model_sha256=adaptive.sha(OUT/'integrated_model.json'),
            adaptive_manifest_sha256=adaptive.sha(OUT/'adaptive_manifest.json'),
            jockey_history_manifest_sha256=adaptive.sha(OUT/'jockey_history_manifest.json'),
            population_hashes=pop['hashes'],beta_fit=beta_audit,train_set_match=True,
            determinism=True,offset_reproduction_max_abs_diff=0.0,
            research_pre_20261024='BLOCKED_PENDING_TARGET_PRE_CHECKS',
            builder_sha256=adaptive.sha(Path(__file__))))
        adaptive.write_json(OUT/'status.json',{'STATUS':'BUILD_COMPLETE','beta_jockey':beta,'train_dates':len(pop['sets']['dates']),
            'train_races':len(pop['sets']['races']),'train_rows':len(rows),'valid_rows':len(pop['sets']['valid_rows'])})
    except Exception as error:
        adaptive.write_json(OUT/'status.json',{'STATUS':'STOPPED','reason':str(error)})
        raise
    finally:
        if any(adaptive.sha(p)!=v for p,v in protected.items()):
            raise RuntimeError('STOP_ACTIVE_ADAPTIVE_MUTATION')
        adaptive.write_json(OUT/'artifact_hashes.json',{'self_hash_excluded':True,'artifacts':{
            p.name:adaptive.sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='artifact_hashes.json'}})

if __name__=='__main__':
    build()
