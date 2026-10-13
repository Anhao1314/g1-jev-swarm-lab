"""Metadata-only identity freeze. No scientific imports, installation or authority."""
import argparse
import hashlib
import importlib.metadata
from importlib.machinery import PathFinder
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RETAINED = ROOT / 'experiments/mission_constrained/stand5_pair_001'
REUSE = {'experiments/mission_constrained/skill_handoff_acquisition_001/lifecycle.py',
         'experiments/m2/closed_loop_mission_001/acquire.py','scripts/run_oracle_missions.py',
         'console/build_m2_replay.py','pyproject.toml'}

def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
def head(): return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
def sources():
    # Import closure plus capability maps, protocol, config, UI and observer code.
    names = subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
    return {name:sha(ROOT/name) for name in names if name.startswith(('src/','configs/','console/language_v01/'))
            or name in read(HERE/'sources.json')['files']
            or name in REUSE}
def environment():
    return {'python':platform.python_version(),'platform':platform.platform(),'executable':sys.executable,
            'base_executable':sys._base_executable,'base_sha256':sha(sys._base_executable),
            'venv_sha256':sha(sys.executable),
            'packages':{name:importlib.metadata.version(name) for name in read(RETAINED/'environment.json')['packages']}}
def asset_check(root):
    expected=read(RETAINED/'asset_restore.json')['files']
    for name, value in expected.items():
        target=(Path(root)/name).resolve()
        if not target.is_relative_to(Path(root).resolve()) or sha(target)!=value:
            raise ValueError('MODEL_ASSET_DRIFT:'+name)
    return expected

def renderer(root):
    exe=Path(root)/'console/.tools/ffmpeg.exe'
    return {'exe':str(exe.resolve()),'sha256':sha(exe)}

def freeze(destination, asset_root):
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():
        raise ValueError('CLEAN_COMMITTED_SOURCE_REQUIRED')
    assets=asset_check(asset_root)
    Path(destination).mkdir(parents=True,exist_ok=False)
    source={'C_exec':head(),'root':str(ROOT),'files':sources(),'environment':environment(),
            'asset_root':str(Path(asset_root).resolve()),'assets':assets,'renderer':renderer(asset_root),
            'asset_receipt_sha256':sha(RETAINED/'asset_restore.json')}
    write(Path(destination)/'source.json',source)
    identity={'schema':'language-g1-demo-readiness/0.1','C_exec':head(),
              'source_sha256':sha(Path(destination)/'source.json'),'protocol_sha256':sha(HERE/'demo_protocol.json'),
              'budget':read(HERE/'demo_protocol.json')['budget'],
              'render_only':read(HERE/'demo_protocol.json')['render_only'],
              'status':'FROZEN_CANDIDATE_PENDING_INDEPENDENT_REVIEW_AND_OWNER',
              'physics_authorized':False,'language_runtime':'BLOCKED','d011':'BLOCKED'}
    write(Path(destination)/'readiness.json',identity)
    return identity

def verify(path, expected_sha):
    path=Path(path)
    if sha(path)!=expected_sha: raise ValueError('READINESS_HASH_MISMATCH')
    identity=read(path); source_path=path.with_name('source.json')
    if sha(source_path)!=identity['source_sha256']: raise ValueError('SOURCE_MANIFEST_MISMATCH')
    source=read(source_path)
    if head()!=identity['C_exec'] or head()!=source['C_exec'] or str(ROOT)!=source['root']:
        raise ValueError('EXECUTION_IDENTITY_MISMATCH')
    if sha(HERE/'demo_protocol.json')!=identity['protocol_sha256'] or identity['budget']!=read(HERE/'demo_protocol.json')['budget']:
        raise ValueError('PROTOCOL_OR_BUDGET_DRIFT')
    if sources()!=source['files']: raise ValueError('SOURCE_CONTENT_OR_SET_DRIFT')
    if environment()!=source['environment']: raise ValueError('ENVIRONMENT_DRIFT')
    if asset_check(source['asset_root'])!=source['assets'] or sha(RETAINED/'asset_restore.json')!=source['asset_receipt_sha256']:
        raise ValueError('ASSET_RECEIPT_DRIFT')
    if renderer(source['asset_root'])!=source['renderer']: raise ValueError('RENDERER_TOOL_DRIFT')
    if os.environ.get('G1SWARM_ROOT') or os.environ.get('G1SWARM_ARTIFACTS_DIR'):
        raise ValueError('EXTERNAL_SOURCE_OVERRIDE')
    spec=PathFinder.find_spec('g1swarm',[str(ROOT/'src')])
    if spec is None or Path(spec.origin).resolve()!=ROOT/'src/g1swarm/__init__.py':
        raise ValueError('PACKAGE_ORIGIN_MISMATCH')
    for name,module in list(sys.modules.items()):
        origin=getattr(module,'__file__',None)
        if name.startswith('g1swarm') and origin and not Path(origin).resolve().is_relative_to(ROOT/'src'):
            raise ValueError('LOADED_PACKAGE_ORIGIN_MISMATCH')
    if {'torch','mujoco','stable_baselines3'} & sys.modules.keys(): raise ValueError('PREMATURE_MODEL_IMPORT')
    return source

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['freeze','preflight'])
    parser.add_argument('--output',type=Path); parser.add_argument('--assets',type=Path)
    parser.add_argument('--readiness',type=Path); parser.add_argument('--sha256')
    args=parser.parse_args()
    if args.command=='freeze': print(json.dumps(freeze(args.output,args.assets)))
    else:
        source=verify(args.readiness,args.sha256)
        print(json.dumps({'status':'NONPHYSICAL_IDENTITY_PASS','C_exec':source['C_exec'],
                         'sources':len(source['files']),'assets':len(source['assets']),
                         'dependencies':len(source['environment']['packages']),'physics_authorized':False}))
