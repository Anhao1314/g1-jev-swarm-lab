"""Offline product contract tests. No live session, simulator or policy calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.request import Request,urlopen
from urllib.error import HTTPError

import pytest
from g1swarm.language_v01.service import ContractService,ContractError,canonical,ROOT

GOOD='站立2秒，然后前进4米，最后停止'

def test_fresh_command_uses_real_compiler_grounding_and_static_graph(tmp_path):
    s=ContractService(tmp_path/'requests'); r=s.create(GOOD)
    assert r['compiler']['status']=='SUCCESS'
    assert r['capability']['status']=='GROUNDED'
    assert [n['skill'] for n in r['task_graph']]==['stand','walk_forward','stop']
    assert all(n['state']=='PENDING' and n['result'] is None for n in r['task_graph'])
    assert all(n['evidence_ref'] for n in r['capability']['results'])
    assert r['authorization']['decision']=='DENY'
    assert r['execution']==dict(status='NOT_EXECUTED',physics_steps=0,policy_calls=0,result=None,replay=None)
    assert json.loads((tmp_path/'requests'/(r['request_id']+'.json')).read_bytes())==r

@pytest.mark.parametrize('text,status,cap',[('往前走一点','AMBIGUOUS',None),('拿起杯子','UNSUPPORTED',None),
    ('前进3米','SUCCESS','CAPABILITY_UNKNOWN'),('前进100米','SUCCESS','CAPABILITY_UNKNOWN')])
def test_real_negative_language_and_capability(text,status,cap):
    r=ContractService().create(text)
    assert r['compiler']['status']==status
    assert (r['capability']['status'] if r['capability'] else None)==cap
    assert r['authorization']['decision']=='DENY'
    assert r['task_graph']==[]

def test_canonical_binding_covers_every_field_and_no_mutable_authority():
    s=ContractService(); r=s.create(GOOD); original=deepcopy(r)
    unsigned=deepcopy(r); signature=unsigned.pop('contract_sha256')
    assert hashlib.sha256(canonical(unsigned)).hexdigest()==signature
    binding=unsigned.pop('binding')
    assert hashlib.sha256(canonical(unsigned)).hexdigest()==binding['request_sha256']
    r['mission']['steps'][0]['parameters']['duration_s']=99
    r['authorization']['decision']='ALLOW'
    assert s.get(r['request_id'])==original
    changed=deepcopy(original); changed['mission']=r['mission']; changed.pop('contract_sha256')
    with pytest.raises(ContractError,match='BINDING_MISMATCH'):
        s.check(r['request_id'],hashlib.sha256(canonical(changed)).hexdigest())
    assert s.check(r['request_id'],signature)['decision']=='DENY'

def test_identical_text_distinct_request_and_session_binding():
    s=ContractService(); a=s.create(GOOD); b=s.create(GOOD); other=ContractService()
    assert a['mission']==b['mission']
    assert a['request_id']!=b['request_id'] and a['contract_sha256']!=b['contract_sha256']
    with pytest.raises(ContractError): s.check(b['request_id'],a['contract_sha256'])
    with pytest.raises(KeyError): other.get(a['request_id'])
    # Repeat integrity checks never consume/create a grant or enable execution.
    assert s.check(a['request_id'],a['contract_sha256'])==s.check(a['request_id'],a['contract_sha256'])

def test_source_drift_is_rejected_without_mutating_history():
    s=ContractService(); first=next(iter(s._pins['files']))
    s._pins['files'][first]='0'*64 # fault injection into in-memory expected identity only
    with pytest.raises(ContractError,match='RETAINED_SOURCE_DRIFT'): s.create(GOOD)

@pytest.fixture
def http_server():
    spec=importlib.util.spec_from_file_location('language_offline_server',ROOT/'console/language_v01/server.py')
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    server=mod.build_server(0); thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    yield server
    server.shutdown(); thread.join(2); server.server_close()

def call(server,path,body=None,headers=None):
    h={'Content-Type':'application/json',**(headers or {})}
    req=Request(f'http://127.0.0.1:{server.server_port}'+path,data=None if body is None else json.dumps(body).encode(),headers=h)
    try:
        with urlopen(req,timeout=5) as response: return response.status,json.load(response)
    except HTTPError as error: return error.code,json.load(error)

def test_real_http_request_check_and_export(http_server):
    code,r=call(http_server,'/api/requests',{'text':GOOD}); assert code==200
    code,export=call(http_server,'/api/requests/'+r['request_id']); assert export==r
    code,checked=call(http_server,'/api/requests/'+r['request_id']+'/check',{'contract_sha256':r['contract_sha256']})
    assert code==200 and checked['binding_valid'] and checked['decision']=='DENY'
    code,checked=call(http_server,'/api/requests/'+r['request_id']+'/check',{'contract_sha256':'0'*64})
    assert code==409 and checked['error']=='CONTRACT_BINDING_MISMATCH'

@pytest.mark.parametrize('payload',[{'text':GOOD,'owner_authorized':True},{'text':GOOD,'principal':'owner'},
                                  {'text':GOOD,'mission':{}},{'text':GOOD,'allow_test_principal':True}])
def test_client_claims_cannot_be_authority(http_server,payload):
    code,r=call(http_server,'/api/requests',payload)
    assert code==409 and 'NO_AUTHORITY_FIELDS' in r['error']

def test_no_execute_route_and_cross_origin_reject(http_server):
    assert call(http_server,'/api/execute',{})[0]==404
    assert call(http_server,'/api/requests',{'text':GOOD},{'Origin':'https://example.com'})[0]==403
    assert call(http_server,'/api/health',headers={'Host':'example.com'})[0]==403

def test_clean_process_forbids_model_and_physics_imports_and_factories(tmp_path):
    script=tmp_path/'sentinel.py'
    script.write_text('''import sys,importlib.abc
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'mujoco','torch','stable_baselines3'}: raise AssertionError('FORBIDDEN_IMPORT:'+fullname)
sys.meta_path.insert(0,Deny())
from g1swarm.language_v01.service import ContractService
import g1swarm.mission.live_session as live
def forbidden(*a,**k): raise AssertionError('FORBIDDEN_EXECUTION')
live.build_simulation=live.build_controller=forbidden
live.LiveMissionSession.__init__=forbidden
from g1swarm.mission.runtime import MissionExecutor
MissionExecutor.execute=forbidden
s=ContractService(); r=s.create('前进4米')
assert s.check(r['request_id'],r['contract_sha256'])['decision']=='DENY'
assert not {'torch','mujoco'} & set(sys.modules)
print('NO_MODEL_NO_PHYSICS_NO_EXECUTOR_PASS')
''',encoding='utf-8')
    p=subprocess.run([sys.executable,'-B',str(script)],cwd=ROOT,capture_output=True,text=True,timeout=15)
    assert p.returncode==0,p.stderr
    assert 'NO_MODEL_NO_PHYSICS_NO_EXECUTOR_PASS' in p.stdout
