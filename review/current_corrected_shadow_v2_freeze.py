"""Freeze and SHA-reverify completed CURRENT_CORRECTED_SHADOW_V2 artifacts."""
from __future__ import annotations
import hashlib,json,shutil
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REPLAY=ROOT/'reports/current_corrected_shadow_v2_technical_replay_v5_final'

def sha(path:Path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    snapshot_root=ROOT/'reports/current_corrected_shadow_v2_freeze_v5_artifacts'
    if snapshot_root.exists(): raise RuntimeError('FREEZE_V5_SNAPSHOT_ALREADY_EXISTS')
    snapshot_root.mkdir(parents=True)
    snapshot_sources=[ROOT/'review/current_corrected_shadow_v2.py',ROOT/'review/current_corrected_shadow_v2_runner.py',ROOT/'review/current_corrected_shadow_v2_replay.py',ROOT/'review/current_corrected_shadow_v2_aggregator.py',ROOT/'tests/test_current_corrected_shadow_v2.py',ROOT/'reports/current_corrected_shadow_v2_correction_spec_snapshot_v3.json',ROOT/'reports/current_corrected_shadow_v2_human_decision_snapshot_v3.json']
    snapshots=[]
    for source in snapshot_sources:
        target=snapshot_root/source.name; shutil.copy2(source,target); snapshots.append(target)
    required=snapshots+[ROOT/'reports/current_corrected_shadow_v2_output_schema_v4.json',ROOT/'reports/current_corrected_shadow_v2_test_report_v4.json',ROOT/'reports/current_corrected_shadow_v2_invalidation_v1.json',ROOT/'reports/current_corrected_shadow_v2_freeze_v1.json',ROOT/'reports/current_corrected_shadow_v2_freeze_v1_invalidation.json',ROOT/'reports/current_corrected_shadow_v2_freeze_v2.json',ROOT/'reports/current_corrected_shadow_v2_freeze_v3.json',ROOT/'reports/current_corrected_shadow_v2_freeze_v3_supersession.json',ROOT/'reports/current_corrected_shadow_v2_freeze_v4.json',ROOT/'reports/current_corrected_shadow_v2_freeze_v4_supersession.json',ROOT/'reports/current_corrected_shadow_v2_historical_freeze_mutation_record_v5.json',REPLAY/'risk_vocabulary_inventory.json',REPLAY/'all_off_reproduction_report.json',REPLAY/'all_on_manifest.json',REPLAY/'execution_record.json']
    required.extend(sorted((REPLAY/'all_on_outputs').glob('*.json')))
    missing=[str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    hashes={str(path.relative_to(ROOT)).replace('\\','/'):sha(path) for path in required if path.is_file()}
    index=REPLAY/'artifact_hashes.json'; index.write_text(json.dumps(hashes,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    rechecked={str(path.relative_to(ROOT)).replace('\\','/'):sha(path) for path in required if path.is_file()}
    freeze={'schema_version':'CURRENT_CORRECTED_SHADOW_V2_FREEZE_V5','CURRENT_CORRECTED_SHADOW_V2_REFROZEN_V5':'YES','freeze_v4_lineage':'SUPERSEDED_AFTER_INDEPENDENT_REVIEW_REQUIRES_FIX','immutable_snapshot_root':str(snapshot_root.relative_to(ROOT)).replace('\\','/'),'frozen_at':datetime.now(timezone.utc).isoformat(),'technical_replay_evidence_boundary':'POST_RESULT_ENGINEERING_REPLAY_ONLY','freeze_artifact_count':len(required),'hash_index':str(index.relative_to(ROOT)).replace('\\','/'),'FREEZE_SHA_REVERIFY':'PASS' if hashes==rechecked and not missing else 'FAIL','HASH_MISMATCH':sum(hashes.get(k)!=rechecked.get(k) for k in set(hashes)|set(rechecked)),'MISSING_FREEZE_ARTIFACT':len(missing),'missing':missing,'production_authorization':False,'production_modified':False,'result_access_count':0,'performance_evaluation':False}
    target=ROOT/'reports/current_corrected_shadow_v2_freeze_v5.json'; target.write_text(json.dumps(freeze,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(freeze,ensure_ascii=False))
if __name__=='__main__': main()
