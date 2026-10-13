"""Two-arm trusted serial experiment entry. Preflight is stdlib-only.

The operation flag is an explicit operator assertion, not human authentication.
This task does not authorize its use. Owner must approve exact readiness later.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from contract import HERE, ROOT, HISTORY, sha, read, write, replay_checks, paired_entry, compare_outcomes

EXECUTION_INPUTS = {
    'experiments/phase3a/residual_yaw_component_001/case.json',
    'experiments/phase3a/residual_authority_feasibility_001/protocol.json',
    'experiments/phase3b/decision_benchmark_acquisition_001/evidence_manifest_attempt02.json',
    'experiments/phase3b/decision_benchmark_acquisition_001/source_manifest.json',
    'experiments/phase3b/decision_benchmark_acquisition_001/protocol.json',
    'experiments/phase3b/decision_benchmark_acquisition_001/cases.json',
    'experiments/phase3b/decision_benchmark_acquisition_001/evidence_attempt02/manifest.json',
}

def head():
    return subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()

def source_files():
    names = subprocess.check_output(['git','ls-files'], cwd=ROOT, text=True).splitlines()
    prefix = HERE.relative_to(ROOT).as_posix()+'/'
    return {p:sha(ROOT/p) for p in names if p in EXECUTION_INPUTS or p.endswith('.py') or p.startswith('configs/') or
            p.startswith(prefix) or p.startswith(HISTORY.relative_to(ROOT).as_posix()+'/')}

def environment():
    frozen = read(HERE/'environment.json')
    return {'python':platform.python_version(), 'platform':platform.platform(), 'executable':sys.executable,
            'base_executable':sys._base_executable,'base_executable_sha256':sha(sys._base_executable),
            'venv_executable_sha256':sha(sys.executable),
            'packages':{k:importlib.metadata.version(k) for k in frozen['packages']}}

def freeze(destination):
    # Never an acquisition. Freeze after the code commit, without circular self-hash.
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'], cwd=ROOT).strip():
        raise RuntimeError('SOURCE_NOT_COMMITTED')
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {'C_exec':head(), 'root':str(ROOT), 'files':source_files(),
                'assets':read(HERE/'asset_restore.json')['files'], 'environment':environment(),
                'historical_manifest_sha256':sha(HISTORY.parents[2]/'evidence_manifest_attempt02.json')}
    write(destination/'source.json', manifest)
    receipt = {'status':'FROZEN_ENGINEERING_IDENTITY_NO_PHYSICS_AUTHORITY', 'physics_authorized':False,
               'C_exec':head(), 'source_sha256':sha(destination/'source.json'),
               'protocol_sha256':sha(HERE/'protocol.json'), 'rule_sha256':sha(HERE/'rule.py'),
               'arm_order':['selected','fixed'], 'native_per_arm':40000, 'native_total':80000,
               'wall_per_arm_s':120, 'wall_total_s':240}
    write(destination/'readiness.json', receipt)
    return receipt

def preflight(path, expected_sha):
    if sha(path) != expected_sha:
        raise RuntimeError('READINESS_HASH_MISMATCH')
    r = read(path)
    source_path = path.with_name('source.json')
    if sha(source_path) != r['source_sha256']:
        raise RuntimeError('SOURCE_MANIFEST_MISMATCH')
    m = read(source_path)
    if not EXECUTION_INPUTS <= m['files'].keys():
        raise RuntimeError('MISSING_FROZEN_EXECUTION_INPUTS')
    if sha(HISTORY.parents[2]/'evidence_manifest_attempt02.json') != m['historical_manifest_sha256']:
        raise RuntimeError('HISTORICAL_MANIFEST_DRIFT')
    if head() != r['C_exec'] or head() != m['C_exec'] or str(ROOT) != m['root']:
        raise RuntimeError('EXECUTION_IDENTITY_MISMATCH')
    if environment() != m['environment']:
        raise RuntimeError('ENVIRONMENT_DRIFT')
    if sha(HERE/'protocol.json') != r['protocol_sha256'] or sha(HERE/'rule.py') != r['rule_sha256']:
        raise RuntimeError('SCIENTIFIC_CONTRACT_DRIFT')
    for name, expected in {**m['files'], **m['assets']}.items():
        path_value = (ROOT/name).resolve()
        if not path_value.is_relative_to(ROOT) or sha(path_value) != expected:
            raise RuntimeError('SOURCE_OR_ASSET_DRIFT:'+name)
    if source_files() != m['files']:
        raise RuntimeError('SOURCE_SET_DRIFT')
    if os.environ.get('G1SWARM_ROOT') or os.environ.get('G1SWARM_ARTIFACTS_DIR'):
        raise RuntimeError('REJECT_EXTERNAL_SOURCE_OVERRIDE')
    # Editable site-packages may point to a different historical worktree.
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT/'src'))
    from importlib.machinery import PathFinder
    spec = PathFinder.find_spec('g1swarm', [str(ROOT/'src')])
    if spec is None or Path(spec.origin).resolve() != ROOT/'src/g1swarm/__init__.py':
        raise RuntimeError('PACKAGE_ORIGIN_MISMATCH')
    if any(x in sys.modules for x in ('torch','mujoco')):
        raise RuntimeError('PREMATURE_RUNTIME_IMPORT')
    return {'status':'NONPHYSICAL_PREFLIGHT_PASS', 'C_exec':head(), 'sources':len(m['files']),
            'assets':len(m['assets']), 'dependencies':len(m['environment']['packages']),
            'physics_authorized':False}

def supervise(command, directory, deadline):
    """Reuse the retained single Python child watchdog pattern, no run retry."""
    started = time.perf_counter()
    receipt = {'started':started, 'deadline':deadline, 'timed_out':False, 'cleanup_errors':[]}
    child = None
    try:
        with (directory/'worker.log').open('x', encoding='utf-8') as log:
            if time.perf_counter() >= deadline-2:
                raise TimeoutError('NO_STARTUP_BUDGET')
            env = dict(os.environ)
            if os.name != 'nt' or command[0] != sys.executable:
                raise RuntimeError('UNQUALIFIED_LAUNCH_INTERPRETER')
            # CPython venv redirectors insert another parent. Invoke the same
            # base interpreter with the venv launcher identity instead; verified
            # by metadata + real production worker guard tests, no installation.
            env['__PYVENV_LAUNCHER__'] = sys.executable
            command = [sys._base_executable, *command[1:]]
            child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            receipt['pid'] = child.pid
            try:
                receipt['returncode'] = child.wait(timeout=max(.001,deadline-2-time.perf_counter()))
            except subprocess.TimeoutExpired:
                receipt['timed_out'] = True
    except BaseException as exc:
        receipt['exception'] = {'type':type(exc).__name__, 'message':str(exc)}
    finally:
        if child is not None and child.poll() is None:
            try:
                # Windows venv redirector itself is a parent of the interpreter.
                # Killing only Popen.pid leaves the actual worker alive.
                if os.name != 'nt':
                    raise RuntimeError('UNQUALIFIED_PLATFORM_CLEANUP')
                killed = subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],
                    capture_output=True, text=True, timeout=max(.001,deadline-time.perf_counter()))
                receipt['tree_cleanup'] = {'returncode':killed.returncode,
                    'stdout':killed.stdout,'stderr':killed.stderr}
                if killed.returncode != 0:
                    raise RuntimeError('TREE_CLEANUP_FAILED')
                child.wait(timeout=max(.001, deadline-time.perf_counter()))
            except BaseException as exc:
                receipt['cleanup_errors'].append(str(exc))
        receipt['reaped'] = child is not None and child.poll() is not None
        receipt['elapsed_s'] = time.perf_counter()-started
        receipt['within_deadline'] = time.perf_counter() <= deadline
        receipt['passed'] = (receipt.get('returncode') == 0 and receipt['reaped'] and
                             not receipt['timed_out'] and not receipt['cleanup_errors'] and receipt['within_deadline'])
        write(directory/'process_receipt.json', receipt)
    return receipt

def acquire(path, expected_sha, destination, owner):
    if owner is not True:
        raise PermissionError('SEPARATE_OWNER_PHYSICS_AUTHORIZATION_REQUIRED')
    started = time.perf_counter()
    preflight(path, expected_sha)
    destination.mkdir(parents=True, exist_ok=False)
    write(destination/'launch.json', {'C_exec':head(),'readiness_sha256':expected_sha,
          'parent_pid':os.getpid(),'started':started,'deadline':started+240,
          'authority':'Trusted serial Owner operator assertion; not production identity'})
    outcome = {'status':'PARTIAL_STOPPED', 'arms':[], 'attempts_per_arm':1}
    def remaining():
        if time.perf_counter() >= started+238:
            raise TimeoutError('TOTAL_LIFECYCLE_DEADLINE')
    try:
        for arm in ('selected','fixed'):
            remaining()
            arm_start = time.perf_counter()
            directory = destination/arm
            directory.mkdir(exist_ok=False)
            deadline = min(started+238, arm_start+120)
            write(directory/'entry.json', {'parent_pid':os.getpid(),'arm':arm,'deadline':deadline,
                                          'readiness_sha256':expected_sha,'C_exec':head()})
            command = [sys.executable,'-B',str(HERE/'run.py'),'worker','--readiness',str(path),
                       '--sha256',expected_sha,'--output',str(directory)]
            receipt = supervise(command, directory, deadline)
            outcome['arms'].append({'arm':arm,'process':receipt})
            if not receipt['passed']:
                raise RuntimeError('WORKER_TECHNICAL_STOP')
            status = read(directory/'status.json')
            if not status['complete'] or status['physical_failure_observed']:
                raise RuntimeError('OBSERVED_FAILURE_OR_INCOMPLETE')
            remaining()
            if arm == 'selected':
                replay = replay_checks(directory)
                write(destination/'replay_gate.json', replay)
                if not replay['passed']:
                    raise RuntimeError('HISTORICAL_REPLAY_NOT_COMPARABLE')
            else:
                if not paired_entry(read(destination/'selected/predecision.json'),read(directory/'predecision.json')):
                    raise RuntimeError('PAIRED_ENTRY_MISMATCH')
                write(destination/'comparison.json', compare_outcomes(read(destination/'selected/result.json'),read(directory/'result.json')))
            remaining()
        outcome['status'] = 'COMPLETE_SEEN_CONDITION_COMPARISON'
    except BaseException as exc:
        outcome['stop_reason'] = {'type':type(exc).__name__,'message':str(exc)}
    finally:
        outcome['elapsed_s'] = time.perf_counter()-started
        if outcome['elapsed_s'] >= 240:
            outcome['status'] = 'PARTIAL_STOPPED'
            outcome['budget_violation'] = True
        write(destination/'completion.json', outcome)
    return outcome

def worker(path, expected_sha, directory):
    # No bypass flags. This is a trusted local serial parent check, not a
    # security claim against a same-user adversary capable of forging files.
    preflight(path, expected_sha)
    entry = read(directory/'entry.json')
    launch = read(directory.parent/'launch.json')
    if (entry['parent_pid'] != os.getppid() or launch['parent_pid'] != os.getppid() or
        entry['C_exec'] != head() or entry['readiness_sha256'] != expected_sha or
        launch['readiness_sha256'] != expected_sha or entry['arm'] != directory.name or
        entry['arm'] not in ('selected','fixed') or entry['deadline'] > launch['deadline']):
        raise PermissionError('INVALID_TRUSTED_PARENT_CONTEXT')
    with (directory/'consumed').open('x'):
        pass
    if time.perf_counter() >= entry['deadline']-2:
        raise TimeoutError('ENTRY_EXPIRED')
    from backend import execute
    status = execute(entry['arm'], directory, entry['deadline']-2)
    return 0 if status['complete'] and not status['physical_failure_observed'] else 1

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['freeze','preflight','acquire','worker'])
    p.add_argument('--readiness', type=Path)
    p.add_argument('--sha256')
    p.add_argument('--output', type=Path)
    p.add_argument('--owner-authorized', action='store_true')
    a = p.parse_args()
    if a.command == 'freeze': print(json.dumps(freeze(a.output)))
    elif a.command == 'preflight': print(json.dumps(preflight(a.readiness,a.sha256)))
    elif a.command == 'acquire': print(json.dumps(acquire(a.readiness,a.sha256,a.output,a.owner_authorized)))
    else: sys.exit(worker(a.readiness,a.sha256,a.output))
