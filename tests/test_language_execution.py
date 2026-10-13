"""Guarded candidate tests. Owner/API/backend fixtures have no real authority."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import time
import uuid

import pytest
from g1swarm.language_v01 import action,host,demo_identity as identity,observations,physical
from g1swarm.language_v01.service import ContractService,canonical,digest
from test_language_action import SyntheticSession,snapshot

@pytest.fixture
def case(tmp_path,monkeypatch):
    # Source/asset preflight itself is independently qualified on frozen metadata
    # after commit; this fixture isolates lifecycle/approval logic.
    source={'C_exec':identity.head(),'root':str(identity.ROOT)}
    monkeypatch.setattr(identity,'verify',lambda *a:source)
    identity.write(tmp_path/'source.json',{})
    identity.write(tmp_path/'readiness.json',{})
    contracts=ContractService(tmp_path/'requests')
    preparations=action.PreparationService(contracts,tmp_path/'readiness.json',identity.sha(tmp_path/'readiness.json'))
    r=contracts.create('站立2秒，然后前进4米，最后停止。')
    p=preparations.prepare(r['request_id'],r['contract_sha256'])
    report=tmp_path/'report.md'; report.write_text('SYNTHETIC_REVIEW_FIXTURE_NOT_REAL_REVIEW')
    review={'schema':'language-g1-independent-review/0.1','verdict':host.REVIEW_VERDICT,
        'C_exec':p['C_exec'],'readiness_sha256':p['readiness_sha256'],'protocol_sha256':p['protocol_sha256'],
        'scope':'NONPHYSICAL_EXECUTION_BOUNDARY_AND_NEW_CAPTURE_CANDIDATE','physics_performed':False,
        'report_file':'report.md','report_sha256':identity.sha(report)}
    identity.write(tmp_path/'review.json',review)
    now=datetime.now(timezone.utc); created=(now-timedelta(seconds=1)).isoformat()
    approval={'id':123,'html_url':'https://github.com/Anhao1314/g1-jev-swarm-lab/pull/1#issuecomment-123',
        'user':{'id':183497756,'login':'Anhao1314','type':'User'},'author_association':'OWNER',
        'created_at':created,'updated_at':created,
        'body':json.dumps({'decision':'AUTHORIZE_NEW_EXPLICIT_CANONICAL_MISSION_SINGLE_SIMULATION',
             'authority_origin':'NEW_EXPLICIT_PLAN_INSTRUCTION_NOT_SOURCE_UNIQUENESS',
             'request_id':p['request_id'],'mission':p['mission'],'preparation_sha256':p['preparation_sha256'],
             'accepted_independent_review_sha256':identity.sha(tmp_path/'review.json'),
             'expires_at':(now+timedelta(minutes=30)).isoformat()})}
    def synthetic(preparation,source,directory,deadline):
        result=action.dispatch_component(preparation,SyntheticSession(),directory/'component',checkpoint=snapshot,
                                         scope='SYNTHETIC_OFFLINE_COMPONENT')
        payload={'kind':'SYNTHETIC_NONPHYSICAL_BACKEND','status':'COMPLETED','request_id':p['request_id'],
            'preparation_sha256':p['preparation_sha256'],'C_exec':p['C_exec'],'executed_mission_sha256':p['mission_sha256'],
            'native_completed':0,'native_attempts':0,'policy_inference_completed':0,'runtime_result':result['runtime_result']}
        identity.write(directory/'physical.json',payload)
        return payload
    monkeypatch.setattr(host,'fetch_owner_comment',lambda *a:deepcopy(approval))
    monkeypatch.setattr(physical,'execute',synthetic)
    return {'root':tmp_path,'p':p,'preparations':preparations,'approval':approval,'source':source}

def make_worker(case,parent=None):
    p=case['p']; root=case['root']; directory=root/'requests/runs'/uuid.uuid4().hex
    directory.mkdir(parents=True)
    started=time.perf_counter()
    record={'run_id':directory.name,'C_exec':p['C_exec'],'parent_pid':os.getppid() if parent is None else parent,
        'preparation':str(root/'requests'/(p['request_id']+'-preparation.json')),'preparation_sha256':p['preparation_sha256'],
        'readiness':str(root/'readiness.json'),'readiness_sha256':p['readiness_sha256'],
        'review':str(root/'review.json'),'review_sha256':identity.sha(root/'review.json'),'owner_comment_id':123,
        'started':started,'deadline':started+115}
    identity.write(directory/'launch.json',record)
    intents=root/'requests/launch-requests'; intents.mkdir(exist_ok=True)
    intent=intents/(p['request_id']+'.json')
    if not intent.exists(): identity.write(intent,{'run_id':directory.name,'parent_pid':record['parent_pid']})
    return directory,record

def test_guarded_positive_to_actual_runtime_is_synthetic(case):
    directory,_=make_worker(case)
    assert host.worker(directory)==0
    result=identity.read(directory/'physical.json')
    assert result['kind']=='SYNTHETIC_NONPHYSICAL_BACKEND' and result['native_completed']==0
    assert result['runtime_result']['mission_success'] and result['runtime_result']['completed_nodes']==3
    assert identity.read(directory/'authorization.json')['original_language_proposal']=='DENY'
    assert (case['root']/'requests/owner-consumed/comment-123.json').exists()
    assert identity.read(directory/'component/component_result.json')['executed_mission_sha256']==case['p']['mission_sha256']

@pytest.mark.parametrize('fault',['parent','manifest','review','owner','scope','expired','review_acceptance','readiness','plan'])
def test_all_rejections_precede_backend(case,monkeypatch,fault):
    directory,record=make_worker(case)
    calls=[]; monkeypatch.setattr(physical,'execute',lambda *a:calls.append(a))
    if fault=='parent': record['parent_pid']=-1
    if fault=='manifest': record['preparation_sha256']='0'*64
    if fault in ('parent','manifest'):
        (directory/'launch.json').write_text(json.dumps(record))
    if fault=='review':
        path=case['root']/'report.md'; path.write_text('CHANGED')
    if fault=='readiness': monkeypatch.setattr(identity,'verify',lambda *a:(_ for _ in ()).throw(ValueError('READINESS_HASH_MISMATCH')))
    if fault=='plan':
        file=case['root']/'requests'/(case['p']['request_id']+'-preparation.json')
        p=identity.read(file); p['mission']['steps'][1]['parameters']['distance_m']=8.; file.write_text(json.dumps(p))
    bad=deepcopy(case['approval'])
    if fault=='owner': bad['user']['id']=1
    if fault in ('scope','expired','review_acceptance'):
        body=json.loads(bad['body'])
        if fault=='scope': body['authority_origin']='SOURCE_UNIQUE'
        if fault=='expired': body['expires_at']=bad['created_at']
        if fault=='review_acceptance': body['accepted_independent_review_sha256']='0'*64
        bad['body']=json.dumps(body)
    monkeypatch.setattr(host,'fetch_owner_comment',lambda *a:bad)
    assert host.worker(directory)==2 and calls==[]
    assert identity.read(directory/'worker-error.json')['physics_steps']==0

def test_replay_new_directory_and_failure_remain_consumed(case,monkeypatch):
    directory,_=make_worker(case)
    def fail(*a): raise RuntimeError('SYNTHETIC_BACKEND_FAULT')
    monkeypatch.setattr(physical,'execute',fail)
    assert host.worker(directory)==2
    assert (case['root']/'requests/owner-consumed/comment-123.json').exists()
    other,_=make_worker(case)
    calls=[]; monkeypatch.setattr(physical,'execute',lambda *a:calls.append(a))
    assert host.worker(other)==2 and not calls
    assert identity.read(other/'worker-error.json')['reason']=='WORKER_SINGLE_ATTEMPT_CONTEXT_MISMATCH'

def test_owner_io_failure_cannot_call_backend(case,monkeypatch):
    directory,_=make_worker(case)
    monkeypatch.setattr(host,'fetch_owner_comment',lambda *a:(_ for _ in ()).throw(TimeoutError('SYNTHETIC_OWNER_NETWORK_TIMEOUT')))
    calls=[]; monkeypatch.setattr(physical,'execute',lambda *a:calls.append(a))
    assert host.worker(directory)==2 and not calls

def test_observer_awaits_real_owner_and_never_promotes_synthetic(case):
    p=case['p']; preparations=case['preparations']
    waiting=observations.execution_for(preparations,p['request_id'])
    assert waiting['status']=='AWAITING_OWNER' and waiting['media'] is None
    directory,_=make_worker(case); assert host.worker(directory)==0
    index=case['root']/'requests/execution-index'; index.mkdir()
    identity.write(directory/'completion.json',{'run_id':directory.name,'request_id':p['request_id'],
        'C_exec':p['C_exec'],'preparation_sha256':p['preparation_sha256'],'status':'CAPTURE_FINISHED',
        'physical_sha256':identity.sha(directory/'physical.json')})
    (index/(p['request_id']+'.jsonl')).write_text(json.dumps({'run_id':directory.name,
        'preparation_sha256':p['preparation_sha256'],'C_exec':p['C_exec']})+'\n')
    result=observations.execution_for(preparations,p['request_id'])
    assert result['status']=='SYNTHETIC_TEST_ONLY' and result['media'] is None and result['result'] is None
    with pytest.raises(KeyError): observations.media_file(preparations,p['request_id'])
    # Append-only explicit newest failure, never mtime selection or old PASS hide.
    other,_=make_worker(case); assert host.worker(other)==2
    with (index/(p['request_id']+'.jsonl')).open('a') as stream:
        stream.write(json.dumps({'run_id':other.name,'preparation_sha256':p['preparation_sha256'],'C_exec':p['C_exec']})+'\n')
    current=observations.execution_for(preparations,p['request_id'])
    assert current['run_id']==other.name and 'reason' in current and current['media'] is None

def test_observer_rejects_foreign_source_or_historical_media(case):
    p=case['p']; index=case['root']/'requests/execution-index'; index.mkdir()
    (index/(p['request_id']+'.jsonl')).write_text(json.dumps({'run_id':'0'*32,'C_exec':'OLD_HISTORY',
                                                          'preparation_sha256':p['preparation_sha256']})+'\n')
    with pytest.raises(ValueError,match='INDEX_BINDING_MISMATCH'):
        observations.execution_for(case['preparations'],p['request_id'])

def test_readonly_raw_audit_keeps_failure_and_counts(case,tmp_path):
    p=case['p']; directory=tmp_path/'audit'; directory.mkdir()
    rows=[{'native_attempt':1,'pre':{}},{'native_completed':1,'post':{'qpos':[.78], 'qvel':[0.],'ctrl':[0.]}},
          {'state':{'fallen':True}},{'policy_attempt':1},{'policy_completed':1}]
    (directory/'native.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    identity.write(directory/'initial-state.json',{})
    receipt={'kind':'NEW_MUJOCO_CAPTURE','request_id':p['request_id'],'C_exec':p['C_exec'],
        'preparation_sha256':p['preparation_sha256'],'executed_mission_sha256':p['mission_sha256'],
        'native_attempts':1,'native_completed':1,'policy_inference_attempts':1,'policy_inference_completed':1,
        'startup_reset_requests':2,'post_checkpoint_reset_requests':0,'physical_failure':{'fallen':True,'nonfinite':False},'status':'FAILED_OR_PARTIAL',
        'files':{'native.jsonl':identity.sha(directory/'native.jsonl'),'initial-state.json':identity.sha(directory/'initial-state.json')}}
    identity.write(directory/'physical.json',receipt)
    checked=observations.audit_capture(directory,p)
    assert checked['passed'] and checked['physical_failure_observed']['fallen']
    receipt['native_attempts']=0; receipt['physical_failure']['fallen']=False
    (directory/'physical.json').write_text(json.dumps(receipt))
    checked=observations.audit_capture(directory,p)
    assert not checked['passed'] and 'OBSERVED_FALL_LOST' in checked['errors']
