"""Nonphysical qualification only. No synthetic Owner is a real execution grant."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from g1swarm.language_v01 import action,demo_identity as identity
from g1swarm.language_v01.service import ContractService,ContractError,canonical,digest,ROOT
from g1swarm.metrics import RunMetrics
from g1swarm.mission.live_session import NodeExecution
from g1swarm.state import RobotState

GOOD='站立2秒，然后前进4米，最后停止'

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    contracts=ContractService(tmp_path/'requests')
    readiness=tmp_path/'readiness.json'; readiness.write_text('{}')
    source=tmp_path/'source.json'; source.write_text('{}')
    # This fixture isolates nonphysical binding from expensive full identity
    # hashing. Separate clean-process frozen preflight is run on actual metadata.
    monkeypatch.setattr(identity,'verify',lambda *a:{'C_exec':identity.head()})
    service=action.PreparationService(contracts,readiness,identity.sha(readiness))
    request=contracts.create(GOOD)
    preparation=service.prepare(request['request_id'],request['contract_sha256'])
    return preparation,service,contracts

def test_preparation_complete_and_immutable_without_authority(prepared):
    preparation,service,contracts=prepared
    assert preparation['budget']==dict(native_steps=15000,wall_s=120,outer_cutoff_s=115,seed=0,attempts=1)
    assert preparation['gates']['d011']=='BLOCKED' and preparation['gates']['owner']=='NOT_PRESENT'
    assert preparation['execution']['physics_steps']==0 and preparation['execution']['media'] is None
    before=canonical(preparation)
    preparation['mission']['steps'][1]['parameters']['distance_m']=8.
    assert canonical(service.get(preparation['request_id']))==before
    assert contracts.get(preparation['request_id'])['authorization']['decision']=='DENY'

def test_preparation_rejects_stale_or_different_request_binding(prepared):
    p,service,contracts=prepared
    other=contracts.create(GOOD)
    with pytest.raises(ContractError,match='BINDING_MISMATCH'):
        service.prepare(other['request_id'],p['contract_sha256'])
    assert service.prepare(p['request_id'],p['contract_sha256'])==p

@pytest.mark.parametrize('text',['前进4米','前进3米','往前走一点','拿起杯子'])
def test_first_demo_allowlist_and_negative_requests(prepared,text):
    _,service,contracts=prepared; r=contracts.create(text)
    with pytest.raises(ContractError): service.prepare(r['request_id'],r['contract_sha256'])

@pytest.mark.parametrize('field',['mission','budget','request_id','C_exec','readiness_sha256','state_contract'])
def test_preparation_tampering_rejected(prepared,field):
    p,_,_=prepared; p[field]='CHANGED'
    with pytest.raises(ContractError,match='PREPARATION_BINDING_MISMATCH'):
        action.validate_preparation(p)

def test_owner_check_validates_account_and_exact_scope_not_cli_assertion(prepared):
    p,service,_=prepared
    now=datetime.now(timezone.utc)
    created=(now-timedelta(seconds=1)).isoformat()
    fixture={'id':123,'html_url':'https://github.com/Anhao1314/g1-jev-swarm-lab/pull/1#issuecomment-123',
             'user':{'id':183497756,'login':'Anhao1314','type':'User'},'author_association':'OWNER',
             'created_at':created,'updated_at':created,
             'body':json.dumps({'decision':'AUTHORIZE_NEW_EXPLICIT_CANONICAL_MISSION_SINGLE_SIMULATION',
                               'authority_origin':'NEW_EXPLICIT_PLAN_INSTRUCTION_NOT_SOURCE_UNIQUENESS',
                               'request_id':p['request_id'],'mission':p['mission'],
                               'preparation_sha256':p['preparation_sha256'],
                               'expires_at':(now+timedelta(minutes=10)).isoformat()})}
    evidence=action.check_owner_comment(fixture,p,now=now)
    assert evidence['account_id']==183497756
    # Fixture has no authority outside this parser test; actual production still
    # rejects even correct Owner account evidence because narrow release is absent.
    with pytest.raises(PermissionError,match='CANONICAL_PLAN_ORIGIN_CONTRACT_NOT_ACCEPTED'):
        action.require_physical_release(p,service.path,service.sha)
    for mutate in ('id','scope','origin','edited','expired'):
        wrong=deepcopy(fixture)
        if mutate=='id': wrong['user']['id']=1
        if mutate=='scope':
            d=json.loads(wrong['body']); d['preparation_sha256']='0'*64; wrong['body']=json.dumps(d)
        if mutate=='origin': wrong['html_url']=wrong['html_url'].replace('Anhao1314','someone')
        if mutate=='edited': wrong['updated_at']=now.isoformat()
        if mutate=='expired':
            d=json.loads(wrong['body']); d['expires_at']=created; wrong['body']=json.dumps(d)
        with pytest.raises((PermissionError,ValueError)): action.check_owner_comment(wrong,p,now=now)

def test_real_gate_rejects_copied_allow_claim(prepared,tmp_path):
    p,service,_=prepared
    p['gates']['narrow_language_release']='ALLOW'; p['gates']['owner']='APPROVED'
    with pytest.raises(ContractError,match='PREPARATION_BINDING_MISMATCH'):
        action.require_physical_release(p,service.path,service.sha)
    p=service.get(p['request_id'])
    with pytest.raises(PermissionError,match='CANONICAL_PLAN_ORIGIN_CONTRACT_NOT_ACCEPTED'):
        action.require_physical_release(p,service.path,service.sha)

class SyntheticSession:
    def __init__(self,*,fail_walk=False):
        self.current=RobotState(0.,(0.,0.,.78),(1.,0.,0.,0.),(0.,0.,0.),(0.,0.,0.),True,False)
        self.calls=[]; self.fail_walk=fail_walk
    def state(self): return self.current
    def run_node(self,node,mode):
        self.calls.append((node.skill.value,dict(node.parameters),mode))
        before=self.current.to_dict()
        t=self.current.simulation_time+1.
        self.current=RobotState(t,(0.,0.,.78),(1.,0.,0.,0.),(0.,0.,0.),(0.,0.,0.),True,False)
        strict_bad=self.fail_walk and node.skill.value=='walk_forward'
        metrics=RunMetrics(forward_displacement_m=4.,distance_error_m=0.,lateral_drift_m=.5 if strict_bad else 0.,
            heading_error_deg=0.,simulation_time_s=1.,physical_success=True,task_success=True,
            failure_type='SUCCESS',failure_reason=None,controller_memory_resets=1,extras={'path_length_m':0.,'simulation_steps':0}).to_dict()
        return NodeExecution(node.skill.value,'SUCCESS',None,True,metrics,before,self.current.to_dict(),0,1,{})
    def close(self): raise AssertionError('EXISTING_SESSION_MUST_NOT_BE_CLOSED_BY_EXECUTOR')

def snapshot(session):
    # No real state qualification: fixture-only raw/controller representation.
    return {'state':session.state().to_dict(),'raw':'SYNTHETIC','controller_counter':0}

def test_private_canonical_mission_reaches_actual_runtime_without_physics(prepared,tmp_path):
    p,_,_=prepared; session=SyntheticSession()
    receipt=action.dispatch_component(p,session,tmp_path/'synthetic-run',checkpoint=snapshot,scope='SYNTHETIC_OFFLINE_COMPONENT')
    assert receipt['scope']=='SYNTHETIC_OFFLINE_COMPONENT' and receipt['physics_steps']==receipt['policy_calls']==0
    assert receipt['runtime_result']['mission_success'] and len(session.calls)==3
    assert receipt['executed_mission_sha256']==p['mission_sha256']
    assert session.calls==[('stand',{'duration_s':2.},'open_loop'),('walk_forward',{'distance_m':4.},'heading_lateral'),('stop',{},'open_loop')]
    assert (tmp_path/'synthetic-run/ledger'/p['mission']['mission_id']/'mission_manifest.json').is_file()
    before=len(session.calls)
    with pytest.raises(FileExistsError):
        action.dispatch_component(p,SyntheticSession(),tmp_path/'different-run',checkpoint=snapshot,scope='SYNTHETIC_OFFLINE_COMPONENT')
    assert len(session.calls)==before

def test_actual_runtime_failure_blocks_dependents_and_preserves_request(prepared,tmp_path):
    p,_,contracts=prepared; original=canonical(contracts.get(p['request_id']))
    session=SyntheticSession(fail_walk=True)
    receipt=action.dispatch_component(p,session,tmp_path/'synthetic-failure',checkpoint=snapshot,scope='SYNTHETIC_OFFLINE_COMPONENT')
    assert not receipt['runtime_result']['mission_success']
    assert receipt['runtime_result']['failure_type']=='TASK_ENVELOPE_VIOLATION'
    assert len(session.calls)==2 # STOP task remains blocked; no hidden recovery.
    assert canonical(contracts.get(p['request_id']))==original
    assert receipt['media'] is None and receipt['physical_qualification']=='NOT_TESTED'

def test_real_dispatch_scope_and_state_change_are_rejected(prepared,tmp_path):
    p,_,_=prepared; session=SyntheticSession()
    with pytest.raises(PermissionError,match='REAL_DISPATCH_NOT_ENABLED'):
        action.dispatch_component(p,session,tmp_path/'real',checkpoint=snapshot,scope='REAL')
    count=0
    def changed(s):
        nonlocal count
        count+=1; return {**snapshot(s),'raw_qpos_change':count}
    with pytest.raises(PermissionError,match='LIVE_STATE_CHANGED_BEFORE_DISPATCH'):
        action.dispatch_component(p,session,tmp_path/'changed',checkpoint=changed,scope='SYNTHETIC_OFFLINE_COMPONENT')
    assert session.calls==[] and (tmp_path/'changed/entry.json').exists()

def test_initial_state_ineligibility_never_calls_runtime(prepared,tmp_path):
    p,_,_=prepared; session=SyntheticSession()
    session.current=RobotState(1.,(0.,0.,.78),(1.,0.,0.,0.),(0.,0.,0.),(0.,0.,0.),True,False)
    with pytest.raises(PermissionError,match='INITIAL_STATE_NOT_ELIGIBLE'):
        action.dispatch_component(p,session,tmp_path/'bad-state',checkpoint=snapshot,scope='SYNTHETIC_OFFLINE_COMPONENT')
    assert session.calls==[]

def test_clean_real_entry_has_no_bypass_flags_and_no_model_imports(tmp_path):
    # Missing source input fails closed, not a synthetic authorized entry.
    preparation=tmp_path/'preparation.json'; preparation.write_text('{}')
    script=tmp_path/'sentinel.py'
    script.write_text('''import sys,runpy,importlib.abc
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','mujoco','stable_baselines3'}: raise AssertionError('FORBIDDEN_MODEL_IMPORT')
sys.meta_path.insert(0,Deny())
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
''')
    command=[sys.executable,'-B',str(script),str(ROOT/'console/language_v01/demo_entry.py'),'launch',
             '--preparation',str(preparation),'--readiness',str(tmp_path/'missing.json'),'--readiness-sha256','0'*64]
    p=subprocess.run(command,capture_output=True,text=True,timeout=15)
    assert p.returncode==2 and 'REFUSED_BEFORE_MODEL_OR_SIMULATOR_CONSTRUCTION' in p.stdout,p.stderr
    copied=subprocess.run(command+['--owner-approved'],capture_output=True,text=True,timeout=15)
    assert copied.returncode==2 and 'unrecognized arguments' in copied.stderr

def test_preflight_rejects_wrong_readiness(tmp_path):
    path=tmp_path/'readiness.json'; path.write_text('{}')
    with pytest.raises(ValueError,match='READINESS_HASH_MISMATCH'):
        identity.verify(path,'0'*64)

@pytest.mark.parametrize('fault,expected',[('HEAD','EXECUTION_IDENTITY_MISMATCH'),
    ('root','EXECUTION_IDENTITY_MISMATCH'),('source','SOURCE_CONTENT_OR_SET_DRIFT'),
    ('environment','ENVIRONMENT_DRIFT'),('budget','PROTOCOL_OR_BUDGET_DRIFT')])
def test_identity_faults_precede_assets_or_runtime_loading(tmp_path,monkeypatch,fault,expected):
    source={'C_exec':identity.head(),'root':str(ROOT),'files':{'synthetic-source':'abc'},
            'environment':{'synthetic':'metadata'},'asset_root':str(tmp_path),'assets':{}}
    r={'C_exec':identity.head(),'source_sha256':'','protocol_sha256':identity.sha(action.PROTOCOL),
       'budget':identity.read(action.PROTOCOL)['budget']}
    monkeypatch.setattr(identity,'sources',lambda:{'synthetic-source':'abc'})
    monkeypatch.setattr(identity,'environment',lambda:{'synthetic':'metadata'})
    if fault=='HEAD': r['C_exec']='0'*40
    if fault=='root': source['root']=str(tmp_path/'wrong')
    if fault=='source': source['files']={}
    if fault=='environment': source['environment']={}
    if fault=='budget': r['budget']['native_steps']=15001
    identity.write(tmp_path/'source.json',source); r['source_sha256']=identity.sha(tmp_path/'source.json')
    identity.write(tmp_path/'readiness.json',r)
    with pytest.raises(ValueError,match=expected): identity.verify(tmp_path/'readiness.json',identity.sha(tmp_path/'readiness.json'))

def test_real_http_preparation_rejects_authority_fields(prepared):
    from threading import Thread
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    p,preparations,contracts=prepared
    spec=importlib.util.spec_from_file_location('language_action_http',ROOT/'console/language_v01/server.py')
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    server=mod.build_server(0); server.service=contracts; server.preparations=preparations
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        uri=f'http://127.0.0.1:{server.server_port}/api/requests/{p["request_id"]}/prepare'
        req=Request(uri,data=json.dumps({'contract_sha256':p['contract_sha256']}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=5) as response: assert json.load(response)==p
        with urlopen(uri[:-7]+'preparation',timeout=5) as response: assert json.load(response)==p
        bad=Request(uri,data=json.dumps({'contract_sha256':p['contract_sha256'],'owner_approved':True}).encode(),headers={'Content-Type':'application/json'})
        with pytest.raises(HTTPError) as error: urlopen(bad,timeout=5)
        assert error.value.code==409 and 'NO_AUTHORITY_FIELDS' in error.value.read().decode()
    finally: server.shutdown(); thread.join(2); server.server_close()
