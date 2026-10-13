"""Stdlib execution identity; reuses retained environment and asset receipts."""
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
DESIGN=HERE.with_name('skill_handoff_001')
OLD=HERE.with_name('stand5_pair_001')
sys.path.insert(0,str(DESIGN))
from handoff import PROTOCOL
ARMS=tuple(PROTOCOL['arms_in_order'])

def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,indent=2,sort_keys=True,allow_nan=False)
def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=True).encode()
def head(): return subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
def files():
    return {n:sha(ROOT/n) for n in subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()}
def environment():
    return {'python':platform.python_version(),'platform':platform.platform(),'executable':sys.executable,
            'base_executable':sys._base_executable,'base_sha256':sha(sys._base_executable),
            'venv_sha256':sha(sys.executable),
            'packages':{p:importlib.metadata.version(p) for p in read(OLD/'environment.json')['packages']}}
def freeze(destination,history):
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT).strip():
        raise RuntimeError('UNCOMMITTED_SOURCE')
    # Historical source identity is exact, not a caller-supplied substitute cohort.
    for item in read(DESIGN/'inputs.json')['raw']:
        if sha(history/item['path'])!=item['sha256']: raise RuntimeError('HISTORICAL_INPUT_MISMATCH')
    assets=read(OLD/'asset_restore.json')['files']
    for n,h in assets.items():
        if sha(ROOT/n)!=h: raise RuntimeError('ASSET_MISMATCH:'+n)
    destination.mkdir(parents=True,exist_ok=False)
    source={'C_exec':head(),'root':str(ROOT),'files':files(),'assets':assets,'environment':environment(),
            'history_root':str(history.resolve()),'history':{p.relative_to(history).as_posix():sha(p) for p in sorted(history.rglob('*')) if p.is_file()}}
    write(destination/'source.json',source)
    r={'C_exec':head(),'source_sha256':sha(destination/'source.json'),'protocol_sha256':sha(DESIGN/'protocol.json'),
       'arm_order':list(ARMS),'max_native_per_arm':32000,'max_native_total':64000,
       'max_wall_per_arm':120,'max_wall_total':240,'outer_cutoff':235,'physics_authorized':False,
       'status':'FROZEN_ENGINEERING_IDENTITY_PENDING_INDEPENDENT_ACCEPTANCE'}
    write(destination/'readiness.json',r)
    return r
def preflight(path,digest):
    if sha(path)!=digest: raise RuntimeError('READINESS_HASH_MISMATCH')
    r=read(path); src=path.with_name('source.json')
    if sha(src)!=r['source_sha256']: raise RuntimeError('SOURCE_HASH_MISMATCH')
    m=read(src)
    if head()!=r['C_exec'] or head()!=m['C_exec'] or str(ROOT)!=m['root']: raise RuntimeError('EXECUTION_IDENTITY_MISMATCH')
    if sha(DESIGN/'protocol.json')!=r['protocol_sha256']: raise RuntimeError('PROTOCOL_DRIFT')
    if (r['arm_order']!=list(ARMS) or [r[k] for k in ('max_native_per_arm','max_native_total','max_wall_per_arm','max_wall_total','outer_cutoff')]!=[32000,64000,120,240,235]):
        raise RuntimeError('BUDGET_OR_ORDER_DRIFT')
    if files()!=m['files'] or environment()!=m['environment']: raise RuntimeError('SOURCE_OR_ENVIRONMENT_DRIFT')
    expected_assets=read(OLD/'asset_restore.json')['files']
    if m['assets']!=expected_assets: raise RuntimeError('ASSET_SET_DRIFT')
    for n,h in m['assets'].items():
        if sha(ROOT/n)!=h: raise RuntimeError('ASSET_DRIFT')
    history=Path(m['history_root'])
    for n,h in m['history'].items():
        if sha(history/n)!=h: raise RuntimeError('HISTORY_DRIFT')
    for item in read(DESIGN/'inputs.json')['raw']:
        if m['history'].get(item['path'])!=item['sha256']: raise RuntimeError('HISTORICAL_SET_DRIFT')
    if os.environ.get('G1SWARM_ROOT') or os.environ.get('G1SWARM_ARTIFACTS_DIR'): raise RuntimeError('EXTERNAL_ROOT_OVERRIDE')
    sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
    from importlib.machinery import PathFinder
    spec=PathFinder.find_spec('g1swarm',[str(ROOT/'src')])
    if spec is None or Path(spec.origin).resolve()!=ROOT/'src/g1swarm/__init__.py': raise RuntimeError('PACKAGE_ORIGIN_MISMATCH')
    if {'torch','mujoco'} & sys.modules.keys(): raise RuntimeError('PREMATURE_RUNTIME_IMPORT')
    return m
