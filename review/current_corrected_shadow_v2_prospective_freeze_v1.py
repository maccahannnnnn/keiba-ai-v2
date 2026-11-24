"""Immutable freeze for the additive V2 prospective protocol implementation."""
from __future__ import annotations
import hashlib, json, shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/current_corrected_shadow_v2_prospective_protocol_v1_freeze_retry1'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    if OUT.exists(): raise RuntimeError('STOP_PROTOCOL_FREEZE_OUTPUT_EXISTS')
    files=[
        'docs/current_corrected_shadow_v2_prospective_protocol_v1.json','docs/current_corrected_shadow_v2_prospective_protocol_v1_sha256.json',
        'review/current_corrected_shadow_v2_prospective_protocol_v1.py','review/current_corrected_shadow_v2_prospective_validators_v1.py','review/current_corrected_shadow_v2_prospective_pre_v1.py','review/current_corrected_shadow_v2_prospective_post_v1.py','review/current_corrected_shadow_v2_prospective_cumulative_v1.py','review/current_corrected_shadow_v2_prospective_calibration_v1.py','review/current_corrected_shadow_v2_prospective_test_report_v1.py','review/current_corrected_shadow_v2_prospective_freeze_v1.py',
        'tests/test_current_corrected_shadow_v2_prospective_protocol_v1.py','reports/current_corrected_shadow_v2_prospective_calibration_v1/summary.json','reports/current_corrected_shadow_v2_prospective_calibration_v1/race_controls.json','reports/current_corrected_shadow_v2_prospective_calibration_v1/date_controls.json','reports/current_corrected_shadow_v2_prospective_calibration_v1/provenance.json','reports/current_corrected_shadow_v2_prospective_calibration_v1/report.md','reports/current_corrected_shadow_v2_prospective_calibration_v1/artifact_hashes.json','reports/current_corrected_shadow_v2_prospective_human_design_snapshot_v1.json','reports/current_corrected_shadow_v2_prospective_output_schema_v1.json','reports/current_corrected_shadow_v2_prospective_test_report_v1.json',
        'reports/current_corrected_shadow_v2_freeze_v6.json','reports/current_corrected_shadow_v2_freeze_v6_artifacts/artifact_hashes.json']
    OUT.mkdir(parents=True); copied=[]
    for name in files:
        source=ROOT/name
        if not source.is_file(): raise RuntimeError('STOP_PROTOCOL_FREEZE_MISSING:'+name)
        target=OUT/'snapshot'/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target); copied.append(target)
    index={str(path.relative_to(OUT)).replace('\\','/'):sha(path) for path in copied}
    (OUT/'artifact_hashes.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    observed={name:sha(OUT/name) for name in index}; missing=[name for name in index if not (OUT/name).is_file()]
    record={'schema_version':'CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1_FREEZE','status':'FROZEN_PENDING_INDEPENDENT_REVIEW','frozen_at':datetime.now(timezone.utc).isoformat(),'artifact_count':len(index),'FREEZE_SHA_REVERIFY':'PASS' if index==observed and not missing else 'FAIL','HASH_MISMATCH':sum(index.get(k)!=observed.get(k) for k in set(index)|set(observed)),'MISSING_FREEZE_ARTIFACT':len(missing),'formal_execution_authorized':False,'formal_prospective_started':False,'production_authorization':False,'result_access_count':0,'performance_evaluation':False}
    (OUT/'freeze_record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(record,ensure_ascii=False))
if __name__=='__main__': main()
