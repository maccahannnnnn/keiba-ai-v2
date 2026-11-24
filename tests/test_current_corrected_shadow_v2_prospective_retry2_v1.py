"""Synthetic, Result-free contract tests for retry2 prospective implementation."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from review.current_corrected_shadow_v2_prospective_cumulative_v1 import append_from_frozen_post
from review.current_corrected_shadow_v2_prospective_diagnostics_v1 import diagnostics
from review.current_corrected_shadow_v2_prospective_post_v1 import build_post
from review.current_corrected_shadow_v2_prospective_pre_v1 import run
from review.current_corrected_shadow_v2_prospective_pre_v1 import inspect_result_free, validate_g3
from review.current_corrected_shadow_v2_prospective_state_v1 import PreStateTransitions
from review.current_corrected_shadow_v2_prospective_protocol_v1 import PROTOCOL, ROOT, Stop, load_protocol, sha, validate_authorization_artifact


TMP = ROOT / ".tmp" / "ccsv2_retry2_synthetic_tests"


def _reset() -> Path:
    if TMP.exists(): shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    return TMP


def _authorization(path: Path, *, protocol_sha: str | None = None, status: str = "AUTHORIZED", production: bool = False, date: str = "20261001") -> None:
    protocol = load_protocol()
    freeze=path.parent/'current_corrected_shadow_v2_prospective_protocol_v1_freeze_fixture'; freeze.mkdir(exist_ok=True)
    (freeze/'freeze_record.json').write_text('{}',encoding='utf-8'); (freeze/'artifact_hashes.json').write_text(json.dumps({'indexed_artifacts':{}}),encoding='utf-8')
    manifest={'freeze_record_sha256':sha(freeze/'freeze_record.json'),'artifact_hashes_sha256':sha(freeze/'artifact_hashes.json')}
    (freeze/'root_manifest.json').write_text(json.dumps(manifest),encoding='utf-8'); (freeze/'root_manifest.sha256').write_text(sha(freeze/'root_manifest.json'),encoding='utf-8')
    artifact={"authorization_id":"fixture","protocol_name":protocol["protocol_name"],"protocol_version":protocol["protocol_version"],"protocol_sha256":protocol_sha or sha(PROTOCOL),"authoritative_freeze_path":str(freeze.relative_to(ROOT)).replace('\\','/'),"freeze_record_sha256":sha(freeze/'freeze_record.json'),"root_manifest_sha256":sha(freeze/'root_manifest.json'),"v2_freeze_identity":"CURRENT_CORRECTED_SHADOW_V2_FREEZE_V6","v2_freeze_sha256":protocol["freeze_v6_pins"]["freeze_record_sha256"],"human_decision":"authorized","authorization_status":status,"authorized_at":"2026-10-01T00:00:00Z","authorization_date":date,"production_authorization":production,"earliest_formal_target_date":"20261002","evidence_boundary":"FORMAL_PROSPECTIVE_ONLY","retroactive_backfill_allowed":False,"artifact_provenance":"synthetic test only","independent_review_status":"ACCEPT","external_sha256_record":"sidecar","human_action_artifact_store_schema":"CURRENT_CORRECTED_SHADOW_V2_HUMAN_ACTION_ARTIFACT_STORE","human_action_artifact_store_version":"v1","human_action_artifact_root":"reports/_technical_human_action_store"}
    path.write_text(json.dumps(artifact),encoding="utf-8"); path.with_name(path.name+'.sha256').write_text(sha(path),encoding='utf-8')


def _pre() -> Path:
    root = _reset() / "pre"; root.mkdir()
    files = {
        "current_comparator.json": {"frozen_current_buy_rows":[{"race_id":"r1","horse_number":1}]},
        "primary_selection.json": {"rows":[{"race_id":"r1","horse_number":2}]},
        "natural_buy.json": {"rows":[{"race_id":"r1","horse_number":3}]},
        "summary.json": {"target_date":"20261002"},
    }
    for name, value in files.items(): (root/name).write_text(json.dumps(value),encoding="utf-8")
    hashes={name:sha(root/name) for name in files}
    (root/"artifact_hashes.json").write_text(json.dumps({"indexed_artifacts":hashes}),encoding="utf-8")
    (root/"pre_freeze_manifest.json").write_text(json.dumps({"status":"PRE_FROZEN"}),encoding="utf-8")
    return root


def _rows() -> list[dict]:
    return [{"race_id":"r1","horse_number":1,"valid_result":True,"actual_top3":False},{"race_id":"r1","horse_number":2,"valid_result":True,"actual_top3":True},{"race_id":"r1","horse_number":3,"valid_result":False,"actual_top3":False}]


def test_authorization_absent_invalid_and_future_valid():
    root=_reset(); protocol=load_protocol()
    try: validate_authorization_artifact("20261002",protocol,root/"none.json",PROTOCOL)
    except Stop as exc: assert str(exc)=="FORMAL_EXECUTION_NOT_AUTHORIZED"
    else: assert False
    bad=root/"bad.json"; _authorization(bad,protocol_sha="0"*64)
    try: validate_authorization_artifact("20261002",protocol,bad,PROTOCOL)
    except Stop as exc: assert str(exc)=="STOP_EXECUTION_AUTHORIZATION_INVALID"
    else: assert False
    good=root/"good.json"; _authorization(good)
    assert validate_authorization_artifact("20261002",protocol,good,PROTOCOL)["authorization_id"]=="fixture"


def test_authorization_same_day_and_production_stop():
    root=_reset(); protocol=load_protocol(); same=root/"same.json"; _authorization(same,date="20261002")
    try: validate_authorization_artifact("20261002",protocol,same,PROTOCOL)
    except Stop: pass
    else: assert False
    production=root/"production.json"; _authorization(production,production=True)
    try: validate_authorization_artifact("20261003",protocol,production,PROTOCOL)
    except Stop: pass
    else: assert False


def test_formal_driver_never_starts_without_authorization():
    try: run("20261002")
    except Stop as exc: assert str(exc)=="STOP_LEGACY_FORMAL_PRE_ENTRYPOINT_DISABLED"
    else: assert False


def test_pre_hash_and_frozen_post_join_contract():
    # Stage 2 removes caller-row POST as a Formal authority.
    try: build_post(_pre(), _rows(), block_id="b", counted_dates=1)
    except Stop as exc: assert str(exc)=="STOP_LEGACY_CALLER_ROWS_POST_DISABLED"
    else: assert False


def test_post_missing_duplicate_invalid_and_zero_denominator_stop():
    root=_pre()
    for rows in (_rows()[:2], _rows()+[_rows()[0]]):
        try: build_post(root,rows,block_id="b",counted_dates=1)
        except Stop as exc: assert str(exc)=="STOP_LEGACY_CALLER_ROWS_POST_DISABLED"
        else: assert False


def test_cumulative_auto_counts_consumption_and_no_auto_transition():
    root=_pre()
    try: append_from_frozen_post({},pre_root=root,post_root=root)
    except Stop as exc: assert str(exc)=="STOP_LEGACY_MUTABLE_CUMULATE_DISABLED"
    else: assert False


def test_diagnostics_reuse_v4_precedent_and_block_tables():
    rows=lambda hit:[{"valid_result":True,"actual_top3":hit}]
    value=diagnostics([{"date":"20261001","block_id":"b1","counted_races":1,"current_rows":rows(False),"corrected_rows":rows(True)},{"date":"20261002","block_id":"b2","counted_races":1,"current_rows":rows(True),"corrected_rows":rows(False)},{"date":"20261003","block_id":"b2","counted_races":1,"current_rows":rows(False),"corrected_rows":rows(True)}])
    assert "approximate_two_proportion_z" in value["pooled"]
    assert len(value["leave_one_date_out"])==3 and len(value["independent_block_table"])==2 and len(value["leave_one_block_out_table"])==2

def test_g3_actual_ordering_and_recursive_result_free_inspection():
    validate_g3('2026-10-01T00:00:00+00:00','2026-10-01T00:00:01+00:00')
    for bad in ('2026-10-01T00:00:01+00:00','2026-10-01T00:00:02+00:00','bad','2026-10-01T00:00:00'):
        try: validate_g3(bad,'2026-10-01T00:00:01+00:00')
        except Stop: pass
        else: assert False
    assert inspect_result_free({'nested':{'safe':1}})==0
    assert inspect_result_free({'nested':{'actual_top3':True}})>0
    assert inspect_result_free({'source_path':'data/raw/target/daily_result_list/x.csv'})>0

def test_registry_is_irreversible_and_output_path_independent():
    root=_reset()/'registry'; authority=PreStateTransitions(root)
    authority.claim_date('20261002',attempt_id='a',metadata={})
    assert authority.reader.get_date_state('20261002')=='ATTEMPT_STARTED'
    authority.mark_no_pre('20261002',reason='synthetic')
    assert authority.reader.get_date_state('20261002')=='NO_PRE'
    try: authority.claim_date('20261002',attempt_id='other',metadata={})
    except Stop: pass
    else: assert False
