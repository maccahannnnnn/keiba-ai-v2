"""Isolated 10/18 development smoke; never creates an evidence freeze or approval."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from review import prospective_prediction_runner_v1 as runner
from review import pl_same_volume_reselection_shadow_v1 as shadow

ROOT=runner.ROOT
OUT=ROOT/'reports/exp024_20261018_non_evidential_smoke_v3'
FROZEN=ROOT/'reports/daily_pre_analysis_20261018/current_frozen'
REFERENCE_PL=ROOT/'reports/20261018_multi_ai_pre_v1/pl_forward_shadow.json'


def save(path, value):
    with path.open('xb') as f:f.write(shadow.canonical(value))


def main():
    if OUT.exists():raise RuntimeError('STOP_OUTPUT_EXISTS')
    input_manifest=json.loads((FROZEN/'input_manifest.json').read_text(encoding='utf8'))
    for item in input_manifest['sources'].values():
        if shadow.sha(ROOT/item['path'])!=item['sha256']:raise RuntimeError('STOP_FROZEN_INPUT_HASH_MISMATCH')
    OUT.mkdir(parents=True)
    current=runner.run('20261018',trace=True,output_root=OUT/'reconstructed_current')
    index=json.loads((FROZEN/'race_index.json').read_text(encoding='utf8'))['race_index']
    new_index=json.loads((current/'race_index.json').read_text(encoding='utf8'))['race_index']
    if index!=new_index or len(index)!=21:raise RuntimeError('STOP_CURRENT_RACE_INDEX_DIFFERENCE')
    differences=[x['artifact'] for x in index if (FROZEN/x['artifact']).read_bytes()!=(current/x['artifact']).read_bytes()]
    if differences:raise RuntimeError('STOP_CURRENT_PREDICTION_DIFFERENCE:'+','.join(differences))
    selection=shadow.build_pre(current,ROOT/'knowledge')
    if selection['current_environment']['tree_provenance_status']!='VERIFIED':raise RuntimeError('STOP_TREE_ATTESTATION')
    if selection['current_environment_components']['target_bulk_prediction_input_adapter_sha256']!=shadow.sha(ROOT/'review/target_bulk_prediction_input_adapter_v1.py'):raise RuntimeError('STOP_ADAPTER_ATTESTATION')
    current_count=sum(x['current_buy_count'] for x in selection['races'])
    treatment_count=sum(x['treatment_buy_count'] or 0 for x in selection['races'])
    if (current_count,treatment_count)!=(12,12) or selection['pl_inference_coverage']['rate']!=1:raise RuntimeError('STOP_SELECTION_VOLUME_OR_PL_COVERAGE')
    reference=json.loads(REFERENCE_PL.read_text(encoding='utf8'))
    ref={(x['race_id'],int(x['horse_number'])):(x.get('pl_race_rank'),x.get('pl_top3_probability')) for x in reference['horses']}
    new={(r['race_id'],h['horse_number']):(h['pl_rank'],h['pl_probability']) for r in selection['races'] for h in r['horses']}
    if ref!=new:raise RuntimeError('STOP_FROZEN_PL_RANK_OR_PROBABILITY_DIFFERENCE')
    selection['role']='NON_EVIDENTIAL_END_TO_END_SMOKE'
    selection['evidence_count']=0
    # This SHA-sealed test artifact is explicitly NOT a formal freeze or approval.
    save(OUT/'selection_non_evidential.json',selection)
    frozen_sha=shadow.sha(OUT/'selection_non_evidential.json')
    sealed_at=datetime.now(timezone.utc)
    save(OUT/'selection_sha_non_evidential.json',{'sha256':frozen_sha,'recorded_at':sealed_at.isoformat(),
        'role':'NON_EVIDENTIAL_TEST_HARNESS','formal_freeze':False,'evidence_count':0})
    # Result access starts only after the selection and SHA are fully written.
    read_time=datetime.now(timezone.utc)
    while read_time<=sealed_at:
        time.sleep(0.001)
        read_time=datetime.now(timezone.utc)
    result_read=read_time.isoformat()
    primary=ROOT/'data/raw/target/daily_result_list/馬番順着順_20261018.csv'
    auxiliary=ROOT/'data/raw/target/daily_result_list/着順馬番_20261018.csv'
    rows=shadow._join_results_for_selection(selection,primary,auxiliary)
    if shadow.sha(OUT/'selection_non_evidential.json')!=frozen_sha:raise RuntimeError('STOP_SELECTION_MUTATED')
    post={'date':'20261018','role':'NON_EVIDENTIAL_END_TO_END_SMOKE','block_fingerprint_sha256':selection['current_environment_fingerprint'],
          'result_read_timestamp':result_read,'result_source_sha256':{'primary':shadow.sha(primary),'auxiliary':shadow.sha(auxiliary)},
          'selection_sha256':frozen_sha,'pl_inference_coverage':selection['pl_inference_coverage'],'races':rows}
    summary=shadow.summarize_block([post])
    save(OUT/'post_non_evidential.json',post)
    save(OUT/'daily_summary_non_evidential.json',summary)
    save(OUT/'artifact_hashes.json',{'role':'NON_EVIDENTIAL_END_TO_END_SMOKE','evidence_count':0,
        'files':{p.name:shadow.sha(p) for p in (OUT/'selection_non_evidential.json',OUT/'selection_sha_non_evidential.json',OUT/'post_non_evidential.json',OUT/'daily_summary_non_evidential.json')}})
    print(json.dumps({'selection_count':current_count,'treatment_count':treatment_count,'paired':summary['observed'],
                      'secondary':summary['secondary'],'output':str(OUT)},ensure_ascii=False))


if __name__=='__main__':main()
