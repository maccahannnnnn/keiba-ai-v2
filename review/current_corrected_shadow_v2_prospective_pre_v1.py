"""Formal PRE entrypoint. It deliberately refuses execution until Human authorization."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from review.current_corrected_shadow_v2 import CorrectionConfigV2, apply_corrected_shadow_v2
from review.current_corrected_shadow_v2_prospective_protocol_v1 import ROOT, Stop, central_jra_meeting_week_id, control_field_availability, control_observables, current_buy_count, load_protocol, select_natural, select_primary, sha, validate_authorization_artifact, validate_pre_rows, validate_start, verify_authoritative_freeze
from review.current_corrected_shadow_v2_runner import run_new_v2
from review.current_corrected_shadow_v2_prospective_validators_v1 import validate_pre, validate_pre_start
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1

def run(target_date: str, *, human_execution_authorization_date: str | None = None) -> None:
    """Legacy entrypoint retained only to fail closed during the Stage 1 migration."""
    raise Stop("STOP_LEGACY_FORMAL_PRE_ENTRYPOINT_DISABLED")

def build_race_artifact(race_id: str, race_bundle, frozen_current: dict) -> dict:
    """The future authorized driver calls this per race; it never reruns Current.

    Frozen Current is the comparator.  The local ALL-OFF run is only a control
    reproduction, and Corrected Primary is rank-only after the ALL-ON run.
    """
    control = run_new_v2(race_id, race_bundle, CorrectionConfigV2.all_off())
    availability = control_field_availability(control, frozen_current)
    if any(not value["available_count"] or not value["non_null_count"] for value in availability.values()):
        raise Stop("DATE_LEVEL_STOP:UNAVAILABLE_CONTROL_FIELD")
    mismatches = control_observables(control, frozen_current)
    if any(mismatches.values()) or any(value["mismatch_count"] for value in availability.values()): raise Stop("DATE_LEVEL_STOP:ALL_OFF_CONTROL")
    corrected_rows = apply_corrected_shadow_v2(run_new_v2(race_id, race_bundle, CorrectionConfigV2.all_on())["ranked_results"], CorrectionConfigV2.all_on())
    for input_row_order, row in enumerate(corrected_rows):
        row["input_row_order"] = input_row_order
    target_k = current_buy_count(frozen_current["ranked_results"])
    if target_k < 1:
        return {"race_id": race_id, "target_k": 0, "primary_eligible": False, "control_mismatches": mismatches,
                "control_field_availability": availability, "corrected_rows": corrected_rows,
                "primary_selection": [], "natural_buy": select_natural(corrected_rows), "boundary_tie": False}
    validate_pre_rows(frozen_current["ranked_results"], corrected_rows, target_k)
    primary, boundary_tie = select_primary(corrected_rows, target_k)
    return {"race_id": race_id, "target_k": target_k, "primary_eligible": True, "control_mismatches": mismatches, "control_field_availability": availability, "corrected_rows": corrected_rows,
            "primary_selection": primary, "natural_buy": select_natural(corrected_rows), "boundary_tie": boundary_tie}

def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

FORBIDDEN_RESULT_TOKENS={"result","results","finish","finish_position","actual_top3","valid_result","result_source","result_manifest","result_loader"}
def validate_g3(generated_at: str, attempt_started_at: str) -> None:
    try:
        left,right=datetime.fromisoformat(generated_at),datetime.fromisoformat(attempt_started_at)
    except Exception as exc: raise Stop('DATE_LEVEL_STOP:G3_ORDERING') from exc
    if left.tzinfo is None or right.tzinfo is None or left>=right: raise Stop('DATE_LEVEL_STOP:G3_ORDERING')
def inspect_result_free(value: object, path: str='') -> int:
    if isinstance(value,dict):
        return sum((str(k).lower() in FORBIDDEN_RESULT_TOKENS) + inspect_result_free(v,path+'.'+str(k)) for k,v in value.items())
    if isinstance(value,list): return sum(inspect_result_free(v,path) for v in value)
    if isinstance(value,str):
        low=value.lower(); return int(('daily_result' in low) or ('result' in low and ('path' in path.lower() or 'source' in path.lower() or 'manifest' in path.lower())))
    return 0

def _discover_current(target_date: str) -> Path:
    candidates=[]
    for path in (ROOT/'reports').glob(f'**/daily_pre_analysis_{target_date}/current_frozen'):
        if (path/'summary.json').is_file() and json.loads((path/'summary.json').read_text(encoding='utf-8')).get('date')==target_date: candidates.append(path)
    if len(candidates)!=1: raise Stop('DATE_LEVEL_STOP:CURRENT_PRE_DISCOVERY')
    return candidates[0]

def _load_current(root: Path, target_date: str) -> tuple[dict[str,dict],str,dict,dict]:
    manifest_path=root/'prediction_manifest.json'; manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    for entry in manifest.get('files',[]):
        path=root/entry['relative_path']
        if not path.is_file() or sha(path)!=entry['sha256']: raise Stop('DATE_LEVEL_STOP:CURRENT_PRE_HASH')
    summary=json.loads((root/'summary.json').read_text(encoding='utf-8')); provenance=json.loads((root/'provenance.json').read_text(encoding='utf-8'))
    if summary.get('date')!=target_date or provenance.get('target_date')!=target_date or provenance.get('result_data_access_count')!=0 or not provenance.get('generated_at'):
        raise Stop('DATE_LEVEL_STOP:G2_G3_CURRENT')
    index=json.loads((root/'race_index.json').read_text(encoding='utf-8'))['race_index']
    rows={entry['race_id']:json.loads((root/entry['artifact']).read_text(encoding='utf-8')) for entry in index}
    return rows,sha(manifest_path),summary,provenance

def write_no_pre(output_root: Path, target_date: str, reason: str, *, current_pre: Path | None=None) -> Path:
    """Deprecated: NO_PRE is authoritative only through PreStateTransitions."""
    raise Stop("STOP_LEGACY_NO_PRE_OUTPUT_DISABLED")

def _legacy_pipeline_not_state_authority(target_date: str, dg: Path, de: Path, ds: Path, output_root: Path, *, authorization_path: Path, authoritative_protocol_freeze: Path, attempt_started_at: str, attempt_id: str, governance_ledger_head_sha256: str | None = None) -> Path:
    """Private PRE body called only after the Stage 1 state-authority claim.

    It writes PRE artifacts, never date-state events.  Any failure is raised to
    the single entrypoint, which records the sole NO_PRE authority event.
    """
    protocol=load_protocol(); authorization=validate_authorization_artifact(target_date,protocol,authorization_path,authoritative_protocol_freeze)
    started=attempt_started_at
    current_root=_discover_current(target_date)
    current, current_manifest_sha, summary, current_provenance=_load_current(current_root,target_date); validate_g3(current_provenance['generated_at'],started)
    result_data_access_count=inspect_result_free({'current':current,'summary':summary,'provenance':current_provenance})
    if result_data_access_count: raise Stop('STOP_RESULT_CONTAMINATION')
    bundle=TargetBulkPredictionInputAdapterV1().load(dg,de,ds)
    actual_dates={str(race.today_entries[0].race_date).replace('-','') for race in bundle.races.values()}
    if bundle.date!=target_date or actual_dates!={target_date} or set(bundle.races)!=set(current):
        raise Stop('DATE_LEVEL_STOP:G2_G4')
    race_artifacts=[]; primary=[]; natural=[]; population=[]
    for race_id,race_bundle in bundle.races.items():
        try: artifact=build_race_artifact(race_id,race_bundle,current[race_id])
        except Stop as exc:
            raise Stop('DATE_LEVEL_STOP:CORRECTED_ONLY_FAILURE:'+str(exc)) from exc
        population.append({'race_id':race_id,'target_k':artifact['target_k'],'primary_eligible':artifact['target_k']>=1})
        if artifact['target_k']>=1: primary.extend({'race_id':race_id,'horse_number':row['horse_number'],'rank':row['corrected_shadow']['rank']} for row in artifact['primary_selection'])
        natural.extend({'race_id':race_id,'horse_number':row['horse_number'],'buy':True} for row in artifact['natural_buy'])
        race_artifacts.append(artifact)
    gates={'G1':'PASS','G2':'PASS','G3':'PASS','G4':'PASS'}
    for artifact in race_artifacts:
        if artifact['target_k']>=1: validate_pre(current[artifact['race_id']]['ranked_results'],artifact['corrected_rows'],artifact['target_k'],gates,0)
    output_root.mkdir(parents=True,exist_ok=False); rows_root=output_root/'corrected_rows'; rows_root.mkdir()
    for artifact in race_artifacts: _write(rows_root/(artifact['race_id']+'.json'),artifact)
    frozen_current_buy_rows=[{'race_id':rid,'horse_number':row['horse_number']} for rid,payload in current.items() for row in payload['ranked_results'] if row.get('buy')]
    _write(output_root/'population.json',{'target_date':target_date,'races':population}); _write(output_root/'current_comparator.json',{'current_pre_root':str(current_root.relative_to(ROOT)).replace('\\','/'),'current_pre_manifest_sha256':current_manifest_sha,'frozen_current_buy_rows':frozen_current_buy_rows}); _write(output_root/'primary_selection.json',{'selection':'corrected_shadow.rank ascending top k','rows':primary}); _write(output_root/'natural_buy.json',{'rows':natural}); _write(output_root/'integrity_check.json',{'G1_G4':gates,'result_data_access_count':result_data_access_count,'all_off_field_availability':[{'race_id':x['race_id'],'fields':x['control_field_availability']} for x in race_artifacts]}); _write(output_root/'exclusion_record.json',{'automatic_exclusions':[],'buy_zero_primary_filtered':[x['race_id'] for x in population if not x['primary_eligible']]})
    # The authorized freeze is a directory.  Its identity has already been
    # verified by the authorization preflight; hashing the directory itself is
    # both undefined and a Windows PermissionError hazard (N1).
    freeze_identity = verify_authoritative_freeze(authoritative_protocol_freeze)
    provenance={'target_date':target_date,'attempt_id':attempt_id,'protocol_identity':'CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1','started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),'protocol_sha256':sha(ROOT/'docs/current_corrected_shadow_v2_prospective_protocol_v1.json'),'authorized_freeze':freeze_identity,'authorization_pinned_freeze_record_sha256':authorization['freeze_record_sha256'],'authorization_pinned_root_manifest_sha256':authorization['root_manifest_sha256'],'freeze_v6_record_sha256':protocol['freeze_v6_pins']['freeze_record_sha256'],'freeze_v6_index_sha256':protocol['freeze_v6_pins']['freeze_index_sha256'],'runtime_sha256':protocol['freeze_v6_pins'],'pre_driver_sha256':sha(Path(__file__)),'current_pre_manifest_sha256':current_manifest_sha,'raw_input_sha256':{kind:sha(path) for kind,path in {'DG':dg,'DE':de,'DS':ds}.items()},'result_data_access_count':result_data_access_count,'authorization_id':authorization['authorization_id'],'governance_ledger_head_sha256':governance_ledger_head_sha256}
    _write(output_root/'provenance.json',provenance); _write(output_root/'summary.json',{'status':'PRE_FROZEN','target_date':target_date,'primary_races':sum(x['primary_eligible'] for x in population),'primary_selected_n':len(primary),'natural_selected_n':len(natural),'central_jra_meeting_week_id':central_jra_meeting_week_id(target_date)}); _write(output_root/'safety.json',{'result_data_access_count':result_data_access_count,'production_authorization':False,'formal':True}); _write(output_root/'report.md','# Current Corrected Shadow V2 Formal PRE\n')
    files=[path for path in output_root.rglob('*') if path.is_file()]
    _write(output_root/'artifact_hashes.json',{'self_hash_excluded':True,'indexed_artifacts':{str(path.relative_to(output_root)).replace('\\','/'):sha(path) for path in files}})
    _write(output_root/'pre_freeze_manifest.json',{'status':'PRE_FROZEN','target_date':target_date,'attempt_id':attempt_id,'protocol_identity':'CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1','authorization_id':authorization['authorization_id'],'governance_ledger_head_sha256':governance_ledger_head_sha256,'result_data_access_count':result_data_access_count,'artifact_hashes_sha256':sha(output_root/'artifact_hashes.json')})
    return output_root

def run_formal(target_date: str, dg: Path, de: Path, ds: Path, output_root: Path, *, authorization_path: Path, authoritative_protocol_freeze: Path) -> Path:
    """Legacy API: not an authority and cannot start Formal PRE."""
    raise Stop("STOP_LEGACY_FORMAL_PRE_ENTRYPOINT_DISABLED")
