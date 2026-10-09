"""Offline authorization failures and positive seams; no simulator or policy."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

HERE=Path(__file__).absolute().parent
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),obj.__dict__)
    return obj
A=module('owner_authority_test',HERE/'authority.py')
E=module('owner_entry_test',HERE/'acquire.py')
G=module('owner_gate_test',HERE/'readiness.py')

@pytest.fixture
def pair(tmp_path):
    binding={'execution_head':'a'*40,'readiness_sha256':'b'*64,'source_manifest_sha256':'c'*64,
             'protocol_sha256':'d'*64,'source_root':'fixed worktree','cell_order':['one','two'],
             'canonical_cells_sha256':'e'*64,'budget':{'attempts_per_cell':1,'maximum_cells':2,
                 'max_wall_s_per_cell':120,'maximum_wall_s_total':720},
             'hold_window_s':2.0,'hold_native_steps':1000,'output':str(tmp_path/'output'),'ledger':str(tmp_path/'ledger')}
    store=A.TestLedger(tmp_path/'ledger')
    record=store.issue_test(binding)
    return binding,record,store

@pytest.mark.parametrize('field',['execution_head','readiness_sha256','source_manifest_sha256','protocol_sha256',
                                  'source_root','cell_order','canonical_cells_sha256','budget','hold_window_s',
                                  'hold_native_steps','output','ledger'])
def test_complete_binding_tamper_rejected_before_consumption(pair,field):
    binding,record,store=pair
    expected=deepcopy(binding)
    expected[field]='changed'
    with pytest.raises(A.AuthorizationError,match='BINDING'):
        store.consume(record,expected)
    assert not (store.root/'claims').exists()

@pytest.mark.parametrize('field,value',[('record_id','f'*32),('issuer','declared owner'),('kind',A.OWNER),
                                      ('decision','ALLOW_MANY'),('expires_at',0),('expires_at',float('inf')),
                                      ('issued_at',True),('extra','unknown')])
def test_record_metadata_tamper_or_wrong_kind_rejected(pair,field,value):
    binding,record,store=pair
    record[field]=value
    with pytest.raises(A.AuthorizationError):
        store.consume(record,binding)
    assert not (store.root/'claims').exists()

def test_unissued_self_declared_test_json_is_not_a_capability(pair):
    binding,_,store=pair
    claimed=A.issue_test_record(binding)
    with pytest.raises(A.AuthorizationError,match='NOT_ISSUED'):
        store.consume(claimed,binding)

def test_single_claim_survives_new_ledger_instance_and_failed_load(pair):
    binding,record,store=pair
    lease=store.consume(record,binding)
    lease.close('SIMULATED_TECHNICAL_LOAD_FAILURE_NO_REFUND')
    with pytest.raises(A.AuthorizationError,match='REPLAY'):
        A.TestLedger(store.root).consume(record,binding)
    assert A.read(lease.claim)['status']=='CONSUMED_BEFORE_ADAPTER_LOAD'
    assert A.read(lease.campaign/'closed.json')['no_retry'] is True

def test_mutating_original_record_after_issue_does_not_mutate_registry(pair):
    binding,record,store=pair
    record['expires_at']+=1
    with pytest.raises(A.AuthorizationError,match='TAMPERED'):
        store.consume(record,binding)

def test_empty_real_owner_trust_and_test_kind_rejected(pair):
    binding,record,_=pair
    with pytest.raises(A.AuthorizationError,match='KIND'):
        A.verify_owner_record(record,binding,{'owner_records':{}})
    # Synthetic verifier input only; not an issued or accepted real approval.
    synthetic=deepcopy(record)
    synthetic.update(kind=A.OWNER,issuer='synthetic-reviewed-owner',evidence_ref='https://github.com/Anhao1314/g1-jev-swarm-lab/issues/0')
    with pytest.raises(A.AuthorizationError,match='ALLOWLIST'):
        A.verify_owner_record(synthetic,binding,{'owner_records':{}})

def test_synthetic_external_anchor_checks_bytes_not_production_identity(pair):
    binding,record,_=pair
    synthetic=deepcopy(record)
    synthetic.update(kind=A.OWNER,issuer='synthetic-reviewed-owner',evidence_ref='https://github.com/Anhao1314/g1-jev-swarm-lab/issues/0')
    fixture_trust={'owner_records':{A.digest(synthetic):{'issuer':synthetic['issuer'],'evidence_ref':synthetic['evidence_ref']}}}
    result=A.verify_owner_record(synthetic,binding,fixture_trust)
    assert result['physical_dispatch_enabled'] is False and result['production_identity_authenticated'] is False
    changed=deepcopy(synthetic)
    changed['issuer']='changed'
    with pytest.raises(A.AuthorizationError,match='ALLOWLIST'):
        A.verify_owner_record(changed,binding,fixture_trust)
    assert json.loads((HERE/'owner_trust.json').read_text())['owner_records']=={}

def delegate(pair,monkeypatch,index=0):
    binding,record,store=pair
    lease=store.consume(record,binding)
    packet=lease.delegate(index,202)
    parent_pid=packet['supervisor_pid']
    monkeypatch.setattr(A.os,'getppid',lambda:parent_pid)
    monkeypatch.setattr(A.os,'getpid',lambda:202)
    return binding,store,lease,packet

@pytest.mark.parametrize('field,value',[('nonce','forged'),('index',1),('supervisor_pid',987654321),
                                      ('worker_pid',987654321),('binding_sha256','0'*64),('claim','outside.json')])
def test_worker_delegation_tamper_rejected(pair,monkeypatch,field,value):
    binding,store,lease,packet=delegate(pair,monkeypatch)
    packet[field]=value
    with pytest.raises((A.AuthorizationError,FileNotFoundError)):
        store.claim_worker(packet,binding)
    assert not (lease.campaign/'0-backend.json').exists()

def test_worker_and_backend_each_once_only(pair,monkeypatch):
    binding,store,lease,packet=delegate(pair,monkeypatch)
    worker=store.claim_worker(packet,binding)
    result=worker.enter_substitute(binding)
    assert result['status']=='NONPHYSICAL_BACKEND_SUBSTITUTE_ONLY' and result['physics_steps']==0
    with pytest.raises(A.AuthorizationError,match='REPLAY'):
        store.claim_worker(packet,binding)
    with pytest.raises(A.AuthorizationError,match='REPLAY'):
        worker.enter_substitute(binding)

def test_backend_source_binding_drift_rejected_before_double(pair,monkeypatch):
    binding,store,lease,packet=delegate(pair,monkeypatch)
    worker=store.claim_worker(packet,binding)
    changed=deepcopy(binding)
    changed['execution_head']='0'*40
    with pytest.raises(A.AuthorizationError,match='BACKEND_BINDING'):
        worker.enter_substitute(changed)
    assert not (lease.campaign/'0-backend.json').exists()

def test_direct_worker_pid_mismatch_and_next_cell_order_rejected(pair,monkeypatch):
    binding,record,store=pair
    lease=store.consume(record,binding)
    with pytest.raises(A.AuthorizationError,match='ORDER'):
        lease.delegate(1,202)
    packet=lease.delegate(0,202)
    with pytest.raises(A.AuthorizationError,match='SUPERVISOR|WORKER'):
        store.claim_worker(packet,binding)
    assert not (lease.campaign/'0-used.json').exists()

def test_backend_without_consumed_worker_permit_rejected(pair,monkeypatch):
    binding,store,lease,packet=delegate(pair,monkeypatch)
    forged=A.WorkerLease(lease.campaign,0,binding,packet)
    with pytest.raises(A.AuthorizationError,match='WITHOUT_VALID_CONSUMED'):
        forged.enter_substitute(binding)

def test_expiry_rejected(pair,monkeypatch):
    binding,record,store=pair
    monkeypatch.setattr(A.time,'time',lambda:record['expires_at'])
    with pytest.raises(A.AuthorizationError,match='EXPIRED'):
        store.consume(record,binding)

def test_expiry_between_worker_claim_and_backend_is_rejected(pair,monkeypatch):
    binding,store,lease,packet=delegate(pair,monkeypatch)
    worker=store.claim_worker(packet,binding)
    deadline=A.read(lease.claim)['record']['expires_at']
    monkeypatch.setattr(A.time,'time',lambda:deadline)
    with pytest.raises(A.AuthorizationError,match='EXPIRED'):
        worker.enter_substitute(binding)
    assert not (lease.campaign/'0-backend.json').exists()

def test_existing_output_not_modified_even_on_authorization_failure(pair,tmp_path):
    expected,record,store=pair
    output=Path(expected['output'])
    output.mkdir()
    (output/'retained.txt').write_bytes(b'prior data stays intact')
    record_path=tmp_path/'test-record.json'
    A.write_once(record_path,record)
    args=SimpleNamespace(test_record=record_path,output=output,ledger=store.root)
    with pytest.raises(A.AuthorizationError,match='OUTPUT_ALREADY_EXISTS'):
        E.offline_supervisor(object(),A,args,expected)
    assert [p.name for p in output.iterdir()]==['retained.txt']
    assert (output/'retained.txt').read_bytes()==b'prior data stays intact'
    assert (store.root/'claims'/(record['record_id']+'.json')).is_file()

def test_result_write_failure_preserves_original_and_remaining_watchdog(pair,tmp_path,monkeypatch):
    expected,record,store=pair
    record_path=tmp_path/'test-record.json'
    A.write_once(record_path,record)
    args=SimpleNamespace(test_record=record_path,output=Path(expected['output']),ledger=store.root,
                         execution_head=expected['execution_head'],readiness_sha256=expected['readiness_sha256'])
    seen=[]
    p1=SimpleNamespace(campaign_wall_guard=lambda *a:None,cell_wall_guard=lambda *a:None,
                       BudgetFailure=RuntimeError)
    def supervise(command,run_dir,timeout):
        assert p1.subprocess.STDOUT==E.subprocess.STDOUT
        assert p1.subprocess.TimeoutExpired is E.subprocess.TimeoutExpired
        seen.append(timeout)
        index=expected['cell_order'].index(run_dir.name)
        # Explicit unit-only reporting fault fixture, no Worker acceptance claim.
        A.write_once(store.root/'claims'/(record['record_id']+'-workers')/f'{index}-backend.json',{'unit_double':True})
        A.write_once(run_dir/'substitute_result.json',{'kind':A.TEST,'cell_id':run_dir.name,'binding_sha256':A.digest(expected)})
    p1.supervise=supervise
    monkeypatch.setattr(E,'load_frozen_supervisor',lambda gate:p1)
    monkeypatch.setattr(E,'binding',lambda gate,args:deepcopy(expected))
    times=iter([0,0,719,0,719])
    monkeypatch.setattr(E,'time',SimpleNamespace(perf_counter=lambda:next(times)))
    original=A.write_once
    def write(path,value):
        if path.name=='authorization_flow.json':
            raise OSError('injected final result write failure')
        return original(path,value)
    monkeypatch.setattr(A,'write_once',write)
    with pytest.raises(OSError,match='injected final result'):
        E.offline_supervisor(object(),A,args,expected)
    assert seen==[1,1]
    failure=A.read(args.output/'authorization_flow_failed.json')
    assert failure['reason'].startswith('OSError:') and failure['completed_workers']==2
    assert failure['classification']=='TECHNICAL_INTERRUPTION_NONPHYSICAL'

def test_supervisor_launch_failure_keeps_claim_and_no_retry(pair,tmp_path,monkeypatch):
    expected,record,store=pair
    record_path=tmp_path/'test-record.json'
    A.write_once(record_path,record)
    args=SimpleNamespace(test_record=record_path,output=Path(expected['output']),ledger=store.root)
    gate=object()
    monkeypatch.setattr(E,'load_frozen_supervisor',lambda gate:(_ for _ in ()).throw(RuntimeError('injected load failure')))
    with pytest.raises(RuntimeError,match='injected'):
        E.offline_supervisor(gate,A,args,expected)
    assert (store.root/'claims'/(record['record_id']+'.json')).is_file()
    with pytest.raises(A.AuthorizationError,match='REPLAY'):
        store.consume(record,expected)

@pytest.mark.parametrize('operation',['acquire','worker','offline-supervisor','offline-worker'])
def test_identity_failure_before_any_authority_or_backend_load(monkeypatch,operation):
    calls=[]
    def denied(**kwargs):
        calls.append('gate')
        raise ValueError('wrong HEAD')
    monkeypatch.setattr(E,'gate_module',lambda:SimpleNamespace(check_target=denied))
    monkeypatch.setattr(E,'authority_module',lambda:calls.append('AUTHORITY_LOADED'))
    with pytest.raises(ValueError,match='wrong HEAD'):
        E.main([operation,'--execution-head','0'*40,'--readiness-sha256','0'*64])
    assert calls==['gate']

def test_inherited_supervisor_and_p1_sources_unchanged():
    g=G.inherited()
    root=G.ROOT
    raw=root/g.ORIGINAL/'acquire.py'
    p1=module('p1_unchanged_test',raw)
    assert p1.supervise.__code__.co_filename==str(raw)
    assert not {'mujoco','torch','numpy','g1swarm'}.intersection(sys.modules)

def test_new_binding_covers_canonical_six_cells_and_budget(tmp_path):
    receipt={'execution_head':'a'*40,'readiness_sha256':'b'*64,'source_manifest_sha256':'c'*64}
    binding=G.canonical_binding(receipt,tmp_path/'out',tmp_path/'ledger')
    protocol=G.load(G.ROOT/G.inherited().DESIGN)
    assert binding['cell_order']==[c['id'] for c in protocol['cells_in_order']]
    assert binding['canonical_cells_sha256']==A.digest(protocol['cells_in_order'])
    assert binding['budget']==protocol['budget'] and binding['hold_native_steps']==1000
