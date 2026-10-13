"""Single-demo preparation and immutable Runtime handoff components.

No issuer or physical launch is enabled. Source/plan hashes are not permission.
The independent narrow-release gate is frozen BLOCKED; an Owner statement cannot
override it. Components are qualified offline using explicitly synthetic sessions.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import urllib.request
import uuid

from .service import ContractError, canonical, digest
from . import demo_identity as identity

PROTOCOL=identity.HERE/'demo_protocol.json'

def check_record(record):
    document=deepcopy(record)
    claimed=document.pop('contract_sha256',None)
    if digest(canonical(document))!=claimed: raise ContractError('CONTRACT_BINDING_MISMATCH')
    binding=document.pop('binding')
    if digest(canonical(document))!=binding['request_sha256']:
        raise ContractError('REQUEST_BINDING_MISMATCH')
    if digest(canonical(record['mission']))!=binding['mission_sha256']:
        raise ContractError('MISSION_BINDING_MISMATCH')
    if digest(record['source']['text'].encode('utf-8'))!=record['source']['sha256']:
        raise ContractError('SOURCE_TEXT_MISMATCH')
    if record['compiler']['status']!='SUCCESS' or record['capability']['status']!='GROUNDED' or not record['validation']['valid']:
        raise ContractError('LANGUAGE_OR_CAPABILITY_NOT_ELIGIBLE')
    # Recompile instead of treating a self-consistent client hash as semantics.
    from g1swarm.language.compiler import LanguageCompiler
    if LanguageCompiler().compile(record['source']['text']).mission.to_dict()!=record['mission']:
        raise ContractError('SOURCE_MISSION_SEMANTICS_MISMATCH')
    steps=[{'skill':step['skill'],'parameters':step['parameters']} for step in record['mission']['steps']]
    if steps!=identity.read(PROTOCOL)['allowed_steps']:
        raise ContractError('TOO_BROAD_FOR_FIRST_DEMO')

class PreparationService:
    def __init__(self, contracts, readiness, readiness_sha256):
        self.contracts=contracts
        self.path=Path(readiness); self.sha=readiness_sha256
        self._records={}

    def prepare(self, request_id, claimed_hash):
        self.contracts.check(request_id,claimed_hash)
        source=identity.verify(self.path,self.sha)
        record=self.contracts.get(request_id); check_record(record)
        if record['provenance']['head_at_request']!=source['C_exec']:
            raise ContractError('REQUEST_EXECUTION_HEAD_MISMATCH')
        if request_id in self._records: return json.loads(self._records[request_id])
        protocol=identity.read(PROTOCOL)
        preparation={'schema':'language-g1-single-run-preparation/0.1','preparation_id':uuid.uuid4().hex,
            'created_at':datetime.now(timezone.utc).isoformat(),'request_id':request_id,
            'request':record,'mission':deepcopy(record['mission']),
            'mission_sha256':record['binding']['mission_sha256'],'contract_sha256':claimed_hash,
            'C_exec':source['C_exec'],'readiness_sha256':self.sha,
            'source_sha256':identity.sha(self.path.with_name('source.json')),
            'evidence_root':str(self.contracts._evidence.resolve()) if self.contracts._evidence else None,
            'protocol_sha256':identity.sha(PROTOCOL),'budget':protocol['budget'],
            'state_contract':protocol['state_contract'],
            'gates':{'narrow_language_release':protocol['narrow_language_release'],'owner':'NOT_PRESENT',
                     'live_state':'NOT_OBSERVED','language_runtime':'BLOCKED','d011':'BLOCKED'},
            'execution':{'status':'AWAITING_INDEPENDENT_RELEASE_AND_OWNER','physics_steps':0,
                         'policy_calls':0,'media':None,'result':None},
            'owner_approval_template':{'decision':protocol['owner_source']['decision'],
                                     'authority_origin':protocol['owner_source']['authority_origin'],
                                     'request_id':request_id,'mission':deepcopy(record['mission']),
                                     'preparation_sha256':'REPLACE_WITH_EXACT_PREPARATION_SHA256',
                                     'expires_at':'REPLACE_WITH_OWNER_CHOSEN_UTC_EXPIRY'},
            'authority_scope':'Preparation only; no signature, grant or dispatch. TEST_ONLY and UI cannot authorize.'}
        preparation['preparation_sha256']=digest(canonical(preparation))
        frozen=canonical(preparation)
        if self.contracts._evidence:
            with (self.contracts._evidence/(request_id+'-preparation.json')).open('xb') as stream: stream.write(frozen)
        self._records[request_id]=frozen
        return json.loads(frozen)

    def get(self,request_id): return json.loads(self._records[request_id])

def validate_preparation(preparation):
    document=deepcopy(preparation); claimed=document.pop('preparation_sha256',None)
    if digest(canonical(document))!=claimed: raise ContractError('PREPARATION_BINDING_MISMATCH')
    check_record(preparation['request'])
    if (preparation['mission']!=preparation['request']['mission'] or
        preparation['mission_sha256']!=preparation['request']['binding']['mission_sha256'] or
        preparation['contract_sha256']!=preparation['request']['contract_sha256'] or
        preparation['request_id']!=preparation['request']['request_id']):
        raise ContractError('PREPARATION_PLAN_REQUEST_MISMATCH')
    if (preparation['protocol_sha256']!=identity.sha(PROTOCOL) or
        preparation['budget']!=identity.read(PROTOCOL)['budget'] or
        preparation['state_contract']!=identity.read(PROTOCOL)['state_contract']):
        raise ContractError('PREPARATION_PROTOCOL_DRIFT')
    return canonical(preparation['mission'])

def check_owner_comment(comment, preparation, *, now=None):
    """Check *fresh GitHub API data*, not a client JSON claim. Not a grant issuer.

    Pure check is unit-testable; real evidence must come from fetch_owner_comment.
    Edited approvals, expired approvals and wrong author/repository are refused.
    The preparation digest transitively binds every source/plan/context constraint.
    """
    validate_preparation(preparation)
    expected=identity.read(PROTOCOL)['owner_source']
    user=comment.get('user',{})
    if user.get('id')!=expected['user_id'] or user.get('login')!=expected['login'] or user.get('type')!='User':
        raise PermissionError('OWNER_ACCOUNT_PROVENANCE_MISMATCH')
    if (type(comment.get('id')) is not int or comment['id']<=0 or
        comment.get('author_association')!='OWNER' or
        not re.fullmatch(r'https://github\.com/'+re.escape(expected['repository'])+r'/(?:issues|pull)/\d+#issuecomment-'+str(comment['id']),comment.get('html_url',''))):
        raise PermissionError('OWNER_COMMENT_ORIGIN_MISMATCH')
    if not comment.get('created_at') or comment.get('created_at')!=comment.get('updated_at'):
        raise PermissionError('EDITED_OR_UNDATED_OWNER_APPROVAL')
    decision=json.loads(comment['body'])
    if set(decision)!={'decision','authority_origin','request_id','mission','preparation_sha256','expires_at'}:
        raise PermissionError('OWNER_SCOPE_FIELDS_INVALID')
    if (decision['decision']!=expected['decision'] or decision['preparation_sha256']!=preparation['preparation_sha256']
        or decision['authority_origin']!=expected['authority_origin'] or decision['request_id']!=preparation['request_id']
        or canonical(decision['mission'])!=canonical(preparation['mission'])):
        raise PermissionError('OWNER_APPROVAL_SCOPE_MISMATCH')
    expiry=datetime.fromisoformat(decision['expires_at'].replace('Z','+00:00'))
    created=datetime.fromisoformat(comment['created_at'].replace('Z','+00:00'))
    current=now or datetime.now(timezone.utc)
    if not expiry.tzinfo or not created.tzinfo or created>current or not current<expiry:
        raise PermissionError('OWNER_APPROVAL_EXPIRED_OR_TIME_INVALID')
    return {'comment_id':comment['id'],'url':comment['html_url'],'raw_sha256':digest(canonical(comment)),
            'preparation_sha256':preparation['preparation_sha256'],'account_id':user['id'],
            'assurance':expected['assurance'],'expires_at':decision['expires_at']}

def fetch_owner_comment(comment_id):
    if type(comment_id) is not int or comment_id<=0: raise PermissionError('OWNER_COMMENT_ID_REQUIRED')
    repo=identity.read(PROTOCOL)['owner_source']['repository']
    request=urllib.request.Request(f'https://api.github.com/repos/{repo}/issues/comments/{comment_id}',
                                  headers={'Accept':'application/vnd.github+json','User-Agent':'G1-single-demo-owner-check'})
    with urllib.request.urlopen(request,timeout=10) as response:
        if response.geturl()!=request.full_url: raise PermissionError('OWNER_SOURCE_REDIRECT_REJECTED')
        raw=response.read(65537)
        if len(raw)>65536: raise PermissionError('OWNER_RECORD_TOO_LARGE')
    return json.loads(raw)

def reserve_once(preparation, directory):
    """Trusted serial intent consumption, not identity/authority or concurrent dispatch.

    Fixed request evidence root prevents replay by merely choosing a new run dir.
    Reservation happens before execution; failed/partial attempts remain burned.
    """
    validate_preparation(preparation)
    if not preparation.get('evidence_root'): raise PermissionError('PERSISTENT_REQUEST_EVIDENCE_REQUIRED')
    evidence=Path(preparation['evidence_root'])
    sealed=identity.read(evidence/(preparation['request_id']+'-preparation.json'))
    if canonical(sealed)!=canonical(preparation): raise PermissionError('ISSUER_SEALED_PREPARATION_MISMATCH')
    claims=evidence/'run-claims'; claims.mkdir(exist_ok=True)
    target=Path(directory); target.mkdir(parents=True,exist_ok=False)
    # Exclusive creation is a bounded serial replay guard. Not a production
    # authentication or cross-machine, adversarial-filesystem guarantee.
    identity.write(claims/(preparation['request_id']+'.json'),
                   {'preparation_sha256':preparation['preparation_sha256'],
                    'attempt_directory':str(target.resolve()),'scope':'OFFLINE_INTENT_CONSUMED_NO_PHYSICS_AUTHORITY'})
    return target

def require_physical_release(preparation, readiness, readiness_sha256):
    """Mandatory before *any* simulator/model module loading; cannot be UI-enabled."""
    source=identity.verify(readiness,readiness_sha256)
    validate_preparation(preparation)
    if (preparation['C_exec']!=source['C_exec'] or preparation['readiness_sha256']!=readiness_sha256
        or preparation['source_sha256']!=identity.sha(Path(readiness).with_name('source.json'))):
        raise PermissionError('PREPARATION_EXECUTION_IDENTITY_MISMATCH')
    # No code/CLI/UI flag accepts a caller's ALLOW. Future independently reviewed
    # narrow release requires a new explicit freeze; never reinterpret original DENY.
    if identity.read(PROTOCOL)['narrow_language_release']!='ACCEPTED_INDEPENDENT_CANONICAL_PLAN_ORIGIN_CONTRACT':
        raise PermissionError('CANONICAL_PLAN_ORIGIN_CONTRACT_NOT_ACCEPTED_OWNER_CANNOT_OVERRIDE')
    raise PermissionError('PHYSICAL_LAUNCH_NOT_ENABLED_IN_THIS_NONPHYSICAL_DELIVERY')

def dispatch_component(preparation, session, directory, *, checkpoint, scope):
    """Shared canonical→existing Runtime handoff, *not* an authorization API.

    No production entry calls this while release is blocked. The caller owns
    the actual session and checkpoint (raw physics AND controller state). Offline
    tests use synthetic sessions and keep results explicitly SYNTHETIC.
    """
    if scope!='SYNTHETIC_OFFLINE_COMPONENT': raise PermissionError('REAL_DISPATCH_NOT_ENABLED')
    frozen=canonical(preparation); preparation=json.loads(frozen)
    canonical_mission=validate_preparation(preparation)
    before=canonical(checkpoint(session))
    state=session.state().to_dict()
    from g1swarm.state import RobotState
    robot=RobotState.from_dict(state)
    constraints=preparation['state_contract']
    if (not robot.is_finite() or robot.standing is not True or robot.fallen is not False or
        robot.active_skill is not None or robot.simulation_time!=constraints['simulation_time']):
        raise PermissionError('INITIAL_STATE_NOT_ELIGIBLE')
    root=reserve_once(preparation,directory)
    identity.write(root/'entry.json',{'scope':scope,'preparation_sha256':preparation['preparation_sha256'],
                                    'mission_sha256':digest(canonical_mission),'initial_state_sha256':digest(before)})
    with (root/'consumed').open('x'): pass
    # The comparison object is never the executable origin. Reconstruct a new
    # private Mission only from the checked bytes retained above.
    from g1swarm.mission.ir import Mission
    from g1swarm.mission.runtime import MissionExecutor
    from g1swarm.mission.validator import MissionValidator
    from g1swarm.mission.grounding import CapabilityGrounder
    from .service import PROTOCOL as RETAINED_PROTOCOL
    protocol=identity.read(identity.ROOT/RETAINED_PROTOCOL)
    paths=protocol['grounding']['evidence']
    grounder=CapabilityGrounder(risk_map_path=identity.ROOT/paths['risk_map'],
        boundary_comparison_path=identity.ROOT/paths['boundary_comparison'],
        capability_map_path=identity.ROOT/paths['capability_map'],
        historical_limits=protocol['grounding']['historical'],mode_preference=protocol['grounding']['mode_preference'])
    def no_second_session(seed): raise AssertionError('UNEXPECTED_SESSION_FACTORY')
    executor=MissionExecutor(validator=MissionValidator(),grounder=grounder,session_factory=no_second_session,
        protocol=protocol,seed=0,recorder_root=str(root/'ledger'),walk_strict_gate=True,
        provenance={'C_exec':preparation['C_exec'],'request_id':preparation['request_id'],
                    'scope':scope,'preparation_sha256':preparation['preparation_sha256']})
    if canonical(checkpoint(session))!=before: raise PermissionError('LIVE_STATE_CHANGED_BEFORE_DISPATCH')
    result=executor.run(Mission.from_dict(json.loads(canonical_mission)),existing_session=session,
                        phase='language-g1-synthetic-component')
    receipt={'scope':scope,'request_id':preparation['request_id'],'preparation_sha256':preparation['preparation_sha256'],
             'executed_mission_sha256':digest(canonical_mission),'runtime_result':result.to_dict(),
             'physics_steps':0,'policy_calls':0,'media':None,'physical_qualification':'NOT_TESTED'}
    identity.write(root/'component_result.json',receipt)
    return receipt
