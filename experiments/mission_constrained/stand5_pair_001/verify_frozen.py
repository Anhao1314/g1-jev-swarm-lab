"""Exact-freeze acceptance: real worker guard, synthetic backend only.

This test harness installs a synthetic backend in a CHILD's module table. It
does not add a production CLI bypass, import backend.py or any robot runtime.
"""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

from contract import HERE, ROOT, sha, read, write
import run

def main(path, output):
    output.mkdir(parents=True,exist_ok=False)
    checks={}
    actual_sha=sha(path)
    checks['clean_preflight']=run.preflight(path,actual_sha)['status']=='NONPHYSICAL_PREFLIGHT_PASS'
    baseline=read(path); source=read(path.with_name('source.json'))
    def refused(name, mutate):
        folder=output/name; folder.mkdir()
        r=json.loads(json.dumps(baseline)); m=json.loads(json.dumps(source)); mutate(r,m)
        write(folder/'source.json',m); r['source_sha256']=sha(folder/'source.json'); write(folder/'readiness.json',r)
        try: run.preflight(folder/'readiness.json',sha(folder/'readiness.json'))
        except Exception as exc:
            write(folder/'receipt.json',{'rejected':True,'type':type(exc).__name__,'message':str(exc)})
            return True
        return False
    checks['wrong_head']=refused('wrong-head',lambda r,m:r.update(C_exec='0'*40))
    checks['wrong_root']=refused('wrong-root',lambda r,m:m.update(root='X:/wrong'))
    checks['case_source_drift']=refused('wrong-case',lambda r,m:m['files'].__setitem__('experiments/phase3a/residual_yaw_component_001/case.json','0'*64))
    checks['asset_drift']=refused('wrong-asset',lambda r,m:m['assets'].__setitem__(next(iter(m['assets'])),'0'*64))
    checks['environment_drift']=refused('wrong-env',lambda r,m:m['environment']['packages'].update(torch='wrong'))
    try: run.preflight(path,'0'*64)
    except RuntimeError: checks['wrong_readiness']=True
    # Real parent process, production worker/preflight, real child process.
    parent=output/'synthetic-parent'; parent.mkdir()
    write(parent/'launch.json',{'C_exec':run.head(),'parent_pid':os.getpid(),'readiness_sha256':actual_sha,
                               'deadline':time.perf_counter()+30})
    child=parent/'selected'; child.mkdir()
    entry={'C_exec':run.head(),'parent_pid':os.getpid(),'readiness_sha256':actual_sha,'arm':'selected','deadline':time.perf_counter()+20}
    write(child/'entry.json',entry)
    bootstrap=("import sys,types,pathlib;sys.path.insert(0,"+repr(str(HERE))+");import run;"
        "fake=types.ModuleType('backend');"
        "fake.execute=lambda arm,destination,deadline: {'complete':True,'physical_failure_observed':False};"
        "sys.modules['backend']=fake;"
        "code=run.worker(pathlib.Path("+repr(str(path))+"),"+repr(actual_sha)+",pathlib.Path("+repr(str(child))+"));"
        "assert not {'torch','mujoco'} & sys.modules.keys();sys.exit(code)")
    result=run.supervise([sys.executable,'-B','-c',bootstrap],child,entry['deadline'])
    checks['production_guard_synthetic_positive']=result['passed'] and (child/'consumed').exists()
    # Direct worker with real valid Readiness but no parent context: fail before backend.
    try: run.worker(path,actual_sha,child)
    except PermissionError: checks['direct_worker_valid_readiness_rejected']=True
    # New log directory for replay; the same consumed arm is targeted by bootstrap.
    replay=output/'replay-process'; replay.mkdir()
    receipt=run.supervise([sys.executable,'-B','-c',bootstrap],replay,time.perf_counter()+10)
    checks['consumed_replay_rejected']=not receipt['passed'] and 'FileExistsError' in (replay/'worker.log').read_text()
    write(output/'receipt.json',{'checks':checks,'passed':len(checks)==10 and all(checks.values()),
        'C_exec':run.head(),'readiness_sha256':actual_sha,'physics_steps':0,'policy_inference':0,
        'scope':'real guard/process; explicitly synthetic backend; not physical equivalence'})
    print(json.dumps(read(output/'receipt.json')))
    return 0 if len(checks)==10 and all(checks.values()) else 1

if __name__=='__main__':
    sys.exit(main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve()))
