"""Frozen nonphysical process matrix. No live imports, Owner approval or physics."""
import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).absolute().parent
ROOT=HERE.parents[2]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),obj.__dict__)
    return obj

def check(head,sha,work):
    gate=module('owner_flow_gate',HERE/'readiness.py')
    receipt=gate.check_target(expected_sha=sha,execution_head=head)
    auth=module('owner_flow_authority',HERE/'authority.py')
    gate.helpers()['no_links'](work)
    gate.require(not work.exists() and not work.is_relative_to(ROOT),'Fresh external qualification directory required')
    work.mkdir()
    # sitecustomize installs the same live-import tripwire in Supervisor and all
    # native P1-supervised Python children. PYTHONPATH is copied to child env.
    trap=work/'tripwire'
    trap.mkdir()
    (trap/'sitecustomize.py').write_text("import importlib.abc,sys\nclass Deny(importlib.abc.MetaPathFinder):\n def find_spec(self,fullname,path=None,target=None):\n  if any(fullname==p or fullname.startswith(p+'.') for p in ('mujoco','torch','numpy','g1swarm','scripts.run_oracle_missions')):\n   raise RuntimeError('FORBIDDEN_LIVE_IMPORT:'+fullname)\nsys.meta_path.insert(0,Deny())\n",encoding='utf8')
    import os
    environment=dict(os.environ,PYTHONPATH=str(trap))
    output,ledger=work/'output',work/'ledger'
    expected=gate.canonical_binding(receipt,output,ledger)
    record=auth.TestLedger(ledger).issue_test(expected,ttl_s=300)
    path=work/'explicit_test_record.json'
    auth.write_once(path,record)
    base=[sys.executable,str(HERE/'acquire.py')]
    common=['--execution-head',head,'--readiness-sha256',sha,'--output',str(output),'--ledger',str(ledger)]
    results=[]
    def run(name,command,*,stdin='',error=None):
        child=subprocess.run(command,cwd=ROOT,env=environment,input=stdin,capture_output=True,text=True,timeout=720)
        row={'case':name,'command':command,'returncode':child.returncode,'stdout':child.stdout,'stderr':child.stderr}
        results.append(row)
        auth.write_once(work/(name+'.json'),row)
        print(json.dumps(row),flush=True)
        assert 'FORBIDDEN_LIVE_IMPORT' not in child.stderr+child.stdout,name
        if error:
            assert child.returncode!=0 and error in child.stderr,name
        else:
            assert child.returncode==0,child.stderr
    run('six_worker_positive',base+['offline-supervisor',*common,'--test-record',str(path)])
    flow=auth.read(output/'authorization_flow.json')
    assert flow['kind']==auth.TEST and len(flow['results'])==6 and all(r['physics_steps']==0 for r in flow['results'])
    worker_logs=[]
    for cell in expected['cell_order']:
        text=(output/cell/'worker.log').read_text(encoding='utf8')
        assert 'FORBIDDEN_LIVE_IMPORT' not in text
        supervisor=auth.read(output/cell/'supervisor_receipt.json')
        assert supervisor['status']=='WORKER_COMPLETED' and supervisor['worker_exit_code']==0
        worker_logs.append({'cell_id':cell,'supervisor_receipt':supervisor,'worker_log':text})
    run('supervisor_replay',base+['offline-supervisor',*common,'--test-record',str(path)],error='AUTHORIZATION_REPLAY')
    run('direct_worker_no_pipe',base+['offline-worker',*common,'--cell-index','0'],error='WORKER_DELEGATION_MISSING')
    packet=auth.read(ledger/'claims'/(record['record_id']+'-workers')/'0-issued.json')
    run('copied_worker_packet',base+['offline-worker',*common,'--cell-index','0'],stdin=json.dumps(packet),error='SUPERVISOR_IDENTITY_MISMATCH')
    tampered=deepcopy(record)
    tampered['binding']['output']=str(work/'different-output')
    bad=work/'tampered-record.json'
    auth.write_once(bad,tampered)
    run('tampered_record',base+['offline-supervisor',*common,'--test-record',str(bad)],error='AUTHORIZATION_BINDING_MISMATCH')
    run('cli_not_owner',base+['acquire',*common,'--authorize-physics'],error='REAL_OWNER_AUTHORIZATION_MISSING')
    run('test_not_owner',base+['acquire',*common,'--owner-record',str(path)],error='AUTHORITY_KIND')
    wrong=common.copy()
    wrong[1]='0'*40
    run('wrong_head',base+['offline-supervisor',*wrong,'--test-record',str(path)],error='Current HEAD')
    wrong=common.copy()
    wrong[3]='0'*64
    run('wrong_readiness',base+['offline-supervisor',*wrong,'--test-record',str(path)],error='Readiness SHA mismatch')
    summary={'status':'PASS_BOUNDED_NONPHYSICAL_OWNER_BINDING_FLOW','execution_head':head,'readiness_sha256':sha,
             'cases':len(results),'actual_independent_workers':6,'worker_logs':worker_logs,
             'kind':auth.TEST,'real_owner_records_accepted':0,'physics_steps':0,'policy_inferences':0,'model_loads':0,
             'scientific_outcomes':'UNMEASURED_NO_PHYSICS'}
    auth.write_once(work/'acceptance.json',summary)
    print(json.dumps(summary),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution-head',required=True)
    parser.add_argument('--readiness-sha256',required=True)
    parser.add_argument('--work',required=True,type=Path)
    a=parser.parse_args()
    check(a.execution_head,a.readiness_sha256,a.work.absolute())
