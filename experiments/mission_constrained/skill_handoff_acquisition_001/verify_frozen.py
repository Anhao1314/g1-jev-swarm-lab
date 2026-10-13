"""Read-only installed identity checks plus process-only synthetic acceptance.

No acquisition CLI is authorized. Backend injection exists only in this test
program; production entry, source preflight and Windows Job code are unchanged.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from entry import HERE,ROOT,head,sha,read,write,preflight
from lifecycle import supervise

def verify(path,digest,output):
    output.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter(); checks={}
    source=preflight(path,digest)
    checks['installed_identity']=True
    for m in ['torch','mujoco']: assert m not in sys.modules
    checks['no_runtime_imports']=True
    # Wrong-head identity is a new receipt copy, never a modified source tree.
    bad=output/'wrong-head'; bad.mkdir()
    s=read(path.with_name('source.json')); r=read(path)
    s['C_exec']='0'*40; r['C_exec']='0'*40
    write(bad/'source.json',s); r['source_sha256']=sha(bad/'source.json')
    write(bad/'readiness.json',r)
    try: preflight(bad/'readiness.json',sha(bad/'readiness.json'))
    except RuntimeError as exc: checks['wrong_head_rejected']=str(exc)=='EXECUTION_IDENTITY_MISMATCH'
    else: checks['wrong_head_rejected']=False
    sentinel=("import sys,importlib.abc\n"
        "class BlockHeavy(importlib.abc.MetaPathFinder):\n"
        " def find_spec(self,fullname,path=None,target=None):\n"
        "  if fullname.split('.')[0] in {'torch','numpy','mujoco','gymnasium'}: raise AssertionError('FORBIDDEN_HEAVY_IMPORT:'+fullname)\n"
        "sys.meta_path.insert(0,BlockHeavy())\n")
    common=sentinel+f'sys.path.insert(0,{str(HERE)!r})\nfrom pathlib import Path\nimport run,entry\n'
    # The actual supervisor start->preflight->cleanup path with invalid source.
    # It must stop before backend; passing this check cannot authorize physics.
    denied=output/'denied'; denied.mkdir()
    script=denied/'check.py'
    script.write_text(common+f'out=run.launch(Path({str(path)!r}),"wrong",Path({str(denied / "attempt")!r}),True)\n'
        'assert out["status"]=="PARTIAL_STOPPED"\n'
        'assert out["process"]["tree_empty"] and out["process"]["reaped"]\n'
        'print("INVALID_SOURCE_REJECTED_WITH_CLEANUP; NO_PHYSICS")\n',encoding='utf-8')
    receipt=supervise([sys.executable,'-B',str(script)],denied,time.perf_counter()+20,ROOT)
    checks['production_launcher_invalid_source_cleanup']=receipt['passed']
    # Full installed preflight, real parent PID, single use, synthetic backend.
    parent=output/'synthetic'; parent.mkdir()
    now=time.perf_counter()
    write(parent/'launch.json',{'parent_pid':os.getpid(),'C_exec':head(),'readiness_sha256':digest,
                               'started':now,'outer_deadline':now+25,'owner_operation_asserted':True})
    directory=parent/'constant'; directory.mkdir()
    write(directory/'entry.json',{'parent_pid':os.getpid(),'arm':'constant','started':now,
                                  'deadline':now+25,'C_exec':head(),'readiness_sha256':digest})
    script=parent/'positive.py'
    script.write_text(common+'import types\nbackend=types.ModuleType("backend")\n'
        'def execute(arm,directory,deadline):\n'
        ' entry.write(directory/"synthetic.json",{"physics_steps":0,"policy_inference":0,"optimizer_updates":0})\n'
        ' return {"complete":True,"physical_failure_observed":False}\n'
        'backend.execute=execute\nsys.modules["backend"]=backend\n'
        f'assert run.worker(Path({str(path)!r}),{digest!r},Path({str(directory)!r}))==0\n'
        f'try: run.worker(Path({str(path)!r}),{digest!r},Path({str(directory)!r}))\n'
        'except FileExistsError: print("REAL_IDENTITY_SYNTHETIC_PASS_AND_REPLAY_REJECTED")\n'
        'else: raise AssertionError("replay accepted")\n',encoding='utf-8')
    receipt=supervise([sys.executable,'-B',str(script)],directory,now+25,ROOT)
    checks['real_identity_supervised_synthetic_and_replay']=receipt['passed']
    result={'passed':all(checks.values()),'checks':checks,'C_exec':head(),'readiness_sha256':digest,
            'source_sha256':sha(path.with_name('source.json')),'protocol_sha256':sha(HERE.with_name('skill_handoff_001')/'protocol.json'),
            'source_files':len(source['files']),'assets':len(source['assets']),
            'dependencies':len(source['environment']['packages']),'elapsed_s':time.perf_counter()-started,
            'physics_steps':0,'policy_inference':0,'optimizer_updates':0,
            'scope':'engineering identity and synthetic execution only; not physical replay or Owner authority'}
    write(output/'receipt.json',result)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--readiness',type=Path,required=True)
    p.add_argument('--sha256',required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); result=verify(a.readiness,a.sha256,a.output)
    print(json.dumps(result,indent=2)); sys.exit(0 if result['passed'] else 1)
