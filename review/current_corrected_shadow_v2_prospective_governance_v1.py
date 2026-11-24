"""Append-only, result-free run governance for prospective protocol v1."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from review.current_corrected_shadow_v2_prospective_protocol_v1 import Stop
from review.current_corrected_shadow_v2_prospective_state_v1 import PROTOCOL_IDENTITY, StateReader, canonical_date, protocol_state_from_cumulative_events
from review.current_corrected_shadow_v2_prospective_human_artifact_store_v1 import HumanArtifactStoreBinding, parse_timestamp, reconcile, validate_external_artifact

JST=timezone(timedelta(hours=9), name='JST')
def _now_utc() -> datetime: return datetime.now(timezone.utc)
def _sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def _jst_day(now: datetime) -> str: return now.astimezone(JST).strftime('%Y%m%d')
def _parse_jst(value: str) -> datetime:
    try: parsed=datetime.fromisoformat(value)
    except ValueError as exc: raise Stop('STOP_GOVERNANCE_TIMESTAMP_INVALID') from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(hours=9): raise Stop('STOP_GOVERNANCE_TIMESTAMP_INVALID')
    return parsed.astimezone(JST)
def validate_human_action_artifact(path: Path, *, action_type: str, authorization_artifact_sha256: str, effective_date: str|None, target_date: str|None) -> dict[str,Any]:
    sidecar=path.with_name(path.name+'.sha256')
    if not path.is_file() or not sidecar.is_file(): raise Stop('STOP_HUMAN_ACTION_ARTIFACT_MISSING')
    try: value=json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc: raise Stop('STOP_HUMAN_ACTION_ARTIFACT_INVALID') from exc
    if sidecar.read_text(encoding='utf-8').strip()!=_sha(path) or not isinstance(value,dict): raise Stop('STOP_HUMAN_ACTION_ARTIFACT_INVALID')
    identity=value.get('human_identity')
    reason=value.get('reason')
    if value.get('protocol_identity')!=PROTOCOL_IDENTITY or value.get('authorization_artifact_sha256')!=authorization_artifact_sha256 or value.get('action_type')!=action_type or value.get('effective_date')!=effective_date or value.get('target_date')!=target_date or not isinstance(identity,str) or not identity.strip() or identity.strip()=='TECHNICAL_TEST_ONLY' or not isinstance(reason,str) or not reason.strip(): raise Stop('STOP_HUMAN_ACTION_ARTIFACT_INVALID')
    return value

def fold_governance_actions(actions: list[dict[str, Any]], *, as_of: datetime, state_reader: StateReader | None = None) -> dict[str, Any]:
    state='RUNNING'; required: set[str]=set(); exempt:set[str]=set(); head=None; suspended_from=None; terminated=False
    last_created: datetime|None=None; last_effective=''
    for action in actions:
        created=str(action.get('created_at_jst','')); created_dt=_parse_jst(created); effective=str(action.get('effective_date') or '')
        if (last_created is not None and created_dt < last_created) or (effective and effective < last_effective): raise Stop('STOP_GOVERNANCE_ACTION_ORDER')
        last_created=created_dt; last_effective=effective or last_effective; kind=action.get('action_type')
        if terminated: raise Stop('STOP_GOVERNANCE_ACTION_AFTER_TERMINATE')
        if kind=='REGISTER_REQUIRED_DATE':
            target=canonical_date(str(action.get('target_date')))
            if str(action.get('registered_date','')) >= target or target in required: raise Stop('STOP_GOVERNANCE_COVERAGE_REGISTRATION')
            required.add(target)
            if state=='SUSPENDED' and suspended_from and target >= suspended_from: exempt.add(target)
        elif kind=='SUSPEND':
            if state!='RUNNING': raise Stop('STOP_GOVERNANCE_ACTION_ORDER')
            state='SUSPENDED'; suspended_from=canonical_date(str(action.get('effective_date')))
            if suspended_from < created_dt.strftime('%Y%m%d'): raise Stop('STOP_GOVERNANCE_EFFECTIVE_DATE_BACKDATED')
            exempt.update(d for d in required if d >= suspended_from and created_dt < datetime.strptime(d,'%Y%m%d').replace(tzinfo=JST))
        elif kind=='RESUME':
            if state!='SUSPENDED': raise Stop('STOP_GOVERNANCE_ACTION_ORDER')
            resume=canonical_date(str(action.get('effective_date')))
            if resume < str(suspended_from) or resume < created_dt.strftime('%Y%m%d') or created_dt >= datetime.strptime(resume,'%Y%m%d').replace(tzinfo=JST): raise Stop('STOP_GOVERNANCE_ACTION_ORDER')
            exempt.difference_update(d for d in required if d >= resume); state='RUNNING'; suspended_from=None
        elif kind=='TERMINATE_RUN': state='TERMINATED'; terminated=True
        else: raise Stop('STOP_GOVERNANCE_ACTION_TYPE')
        head=action.get('_sha')
    today=_jst_day(as_of)
    consumed = bool(state_reader and protocol_state_from_cumulative_events(state_reader.event_root) not in {'NOT_STARTED','RUNNING','HOLD:EVIDENCE_QUANTITY'})
    breaches=[] if consumed else [d for d in sorted(required-exempt) if d < today and state_reader and state_reader.get_date_state(d)=='UNCLAIMED']
    return {'run_state':'TERMINATED' if terminated else ('COVERAGE_BREACH' if breaches else state),'required_dates':sorted(required),'exempt_dates':sorted(exempt),'coverage_breach_dates':breaches,'current_ledger_head_sha256':head,'suspension_from':suspended_from,'terminated':terminated,'evaluation_consumed':consumed}

@dataclass(frozen=True)
class GovernanceLedger:
    root: Path; authorization_id: str; authorization_artifact_sha256: str; human_artifact_store: HumanArtifactStoreBinding|None=None
    def _paths(self)->list[Path]: return sorted(self.root.glob('*.json')) if self.root.exists() else []
    def _read_actions(self)->list[dict[str,Any]]:
        actions=[]; previous=None
        for index,path in enumerate(self._paths(),1):
            if path.name[:6]!=f'{index:06d}': raise Stop('STOP_GOVERNANCE_LEDGER_SEQUENCE')
            try: value=json.loads(path.read_text(encoding='utf-8'))
            except Exception as exc: raise Stop('STOP_GOVERNANCE_LEDGER_INTEGRITY') from exc
            if not isinstance(value,dict) or value.get('protocol_identity')!=PROTOCOL_IDENTITY or value.get('authorization_id')!=self.authorization_id or value.get('authorization_artifact_sha256')!=self.authorization_artifact_sha256 or value.get('previous_action_sha256')!=previous: raise Stop('STOP_GOVERNANCE_LEDGER_INTEGRITY')
            created = _parse_jst(str(value.get('created_at_jst', '')))
            if value.get('registered_date') != created.astimezone(JST).strftime('%Y%m%d'):
                raise Stop('STOP_GOVERNANCE_REGISTERED_DATE_BINDING')
            if self.human_artifact_store is not None and value.get('human_authorization_artifact_sha256') != self.authorization_artifact_sha256:
                raise Stop('STOP_HUMAN_ACTION_ARTIFACT_LEDGER_MISMATCH')
            value['_sha']=_sha(path); actions.append(value); previous=value['_sha']
        return actions
    def actions(self)->list[dict[str,Any]]:
        actions=self._read_actions()
        if self.human_artifact_store is not None:
            reconcile(actions, self.human_artifact_store)
        return actions
    def append(self, action_type:str, *, human_artifact:Path, effective_date:str|None=None, target_date:str|None=None, requirement:str|None=None, reason:str|None=None, exemption_reason:str|None=None)->Path:
        # The canonical timestamp has a single authority: one internal UTC
        # clock sample for the whole append preflight and write operation.
        now=_now_utc()
        old=self._read_actions(); fold_governance_actions(old,as_of=now)
        created_at=now.astimezone(JST)
        created_at_jst=created_at.isoformat()
        if self.human_artifact_store is None:
            artifact=validate_human_action_artifact(human_artifact,action_type=action_type,authorization_artifact_sha256=self.authorization_artifact_sha256,effective_date=effective_date,target_date=target_date)
            artifact_sha=_sha(human_artifact); action_identity=artifact['human_identity'].strip(); human_identity=artifact['human_identity'].strip()
        else:
            artifact_sha, artifact=validate_external_artifact(human_artifact,self.human_artifact_store,action_type=action_type,effective_date=effective_date,target_date=target_date,requirement=requirement,exemption_reason=exemption_reason)
            action_identity=artifact['action_identity']; human_identity=artifact['human_identity'].strip()
            if parse_timestamp(artifact['created_at']) > _parse_jst(created_at_jst):
                raise Stop('STOP_HUMAN_ACTION_ARTIFACT_TIMESTAMP_ORDER')
            # The submitted external artifact is the only permitted unlinked
            # artifact during append preflight; all historical artifacts must
            # already have exactly one ledger reference.
            reconcile(old, self.human_artifact_store, pending_artifact_sha256=artifact_sha)
        if old and _parse_jst(created_at_jst) < _parse_jst(old[-1]['created_at_jst']): raise Stop('STOP_GOVERNANCE_CLOCK_REGRESSION')
        self.root.mkdir(parents=True,exist_ok=True); path=self.root/f'{len(old)+1:06d}_{action_type.lower()}.json'
        value={'protocol_identity':PROTOCOL_IDENTITY,'authorization_id':self.authorization_id,'authorization_artifact_sha256':self.authorization_artifact_sha256,'action_type':action_type,'created_at_jst':created_at_jst,'effective_date':effective_date,'target_date':target_date,'registered_date':created_at.date().strftime('%Y%m%d'),'requirement':requirement,'exemption_reason':exemption_reason,'reason':artifact['reason'],'human_action_identity':action_identity,'human_identity':human_identity,'human_action_artifact_sha256':artifact_sha,'human_authorization_artifact_sha256':self.authorization_artifact_sha256 if self.human_artifact_store is not None else artifact_sha,'source_artifact_sha256':artifact.get('source_artifact_sha256') if self.human_artifact_store is not None else artifact_sha,'previous_action_sha256':old[-1]['_sha'] if old else None}
        candidate=dict(value); candidate['_sha']='PENDING'
        fold_governance_actions(old+[candidate],as_of=now)
        try:
            with path.open('x',encoding='utf-8') as f: json.dump(value,f,ensure_ascii=False,indent=2); f.write('\n')
        except FileExistsError as exc: raise Stop('STOP_GOVERNANCE_LEDGER_SEQUENCE') from exc
        self.actions(); return path

def require_governance_allows_operation(*, ledger: GovernanceLedger, target_date:str, operation:str, state_reader:StateReader, as_of:datetime|None=None, claim_head:str|None=None)->dict[str,Any]:
    now=as_of or _now_utc(); target_date=canonical_date(target_date); actions=ledger.actions(); view=fold_governance_actions(actions,as_of=now,state_reader=state_reader)
    chain={a['_sha'] for a in actions}
    if claim_head is not None and claim_head not in chain: raise Stop('STOP_GOVERNANCE_HEAD_NOT_ANCESTOR')
    if view['run_state']=='TERMINATED': raise Stop('STOP_RUN_TERMINATED')
    if view['run_state']=='COVERAGE_BREACH': raise Stop('STOP_COVERAGE_BREACH')
    today=_jst_day(now)
    if operation=='PRE':
        suspended=False
        for action in actions:
            if action.get('action_type')=='SUSPEND' and str(action.get('effective_date')) <= target_date and _parse_jst(action['created_at_jst']) < datetime.strptime(target_date,'%Y%m%d').replace(tzinfo=JST): suspended=True
            if action.get('action_type')=='RESUME' and str(action.get('effective_date')) <= target_date: suspended=False
        if suspended: raise Stop('STOP_RUN_SUSPENDED')
        if target_date < today: raise Stop('STOP_PAST_DATE_FORMAL_PRE')
        if target_date not in view['required_dates'] or target_date in view['exempt_dates']: raise Stop('STOP_DATE_NOT_REGISTERED')
    return view
