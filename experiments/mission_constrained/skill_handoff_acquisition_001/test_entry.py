"""Nonphysical guard tests; synthetic metadata is explicitly not frozen readiness.

The subprocess positive runs production preflight and worker, with only metadata
providers and the backend replaced in the test process. No production bypass.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

HERE = Path(__file__).parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    entry = load('entry', HERE / 'entry.py')
    monkeypatch.setitem(sys.modules, 'entry', entry)
    root = tmp_path / 'synthetic-source'
    (root / 'src/g1swarm').mkdir(parents=True)
    (root / 'src/g1swarm/__init__.py').write_text('# synthetic origin only\n')
    (root / 'fixture.txt').write_text('synthetic source, not scientific evidence\n')
    design = root / 'design'
    design.mkdir()
    (design / 'protocol.json').write_bytes((entry.DESIGN / 'protocol.json').read_bytes())
    history = root / 'history'
    history.mkdir()
    (history / 'historical.txt').write_text('synthetic history\n')
    historical_hash = entry.sha(history / 'historical.txt')
    (design / 'inputs.json').write_text(json.dumps({'raw': [{'path': 'historical.txt', 'sha256': historical_hash}]}))
    old = root / 'old'
    old.mkdir()
    (root / 'synthetic-asset.txt').write_text('not a model\n')
    assets = {'synthetic-asset.txt': entry.sha(root / 'synthetic-asset.txt')}
    (old / 'asset_restore.json').write_text(json.dumps({'files': assets}))
    monkeypatch.setattr(entry, 'ROOT', root)
    monkeypatch.setattr(entry, 'DESIGN', design)
    monkeypatch.setattr(entry, 'OLD', old)
    monkeypatch.setattr(entry, 'head', lambda: 'synthetic-head')
    monkeypatch.setattr(entry, 'files', lambda: {'fixture.txt': entry.sha(root / 'fixture.txt')})
    monkeypatch.setattr(entry, 'environment', lambda: {'kind': 'synthetic metadata, not installed environment attestation'})
    for name in ('G1SWARM_ROOT', 'G1SWARM_ARTIFACTS_DIR'):
        monkeypatch.delenv(name, raising=False)
    frozen = tmp_path / 'fixture-readiness'
    frozen.mkdir()
    source = {'C_exec': 'synthetic-head', 'root': str(root), 'files': entry.files(), 'assets': assets,
              'environment': entry.environment(), 'history_root': str(history),
              'history': {'historical.txt': historical_hash}}
    entry.write(frozen / 'source.json', source)
    readiness = {'C_exec': 'synthetic-head', 'source_sha256': entry.sha(frozen / 'source.json'),
                 'protocol_sha256': entry.sha(design / 'protocol.json'), 'arm_order': list(entry.ARMS),
                 'max_native_per_arm': 32000, 'max_native_total': 64000, 'max_wall_per_arm': 120,
                 'max_wall_total': 240, 'outer_cutoff': 235, 'physics_authorized': False}
    path = frozen / 'readiness.json'
    entry.write(path, readiness)
    run = load('handoff_entry_run_test', HERE / 'run.py')
    return SimpleNamespace(entry=entry, run=run, root=root, path=path, digest=entry.sha(path), tmp=tmp_path)


def context(f, parent_pid):
    campaign = f.tmp / 'campaign'
    campaign.mkdir()
    directory = campaign / f.entry.ARMS[0]
    directory.mkdir()
    start = time.perf_counter()
    f.entry.write(campaign / 'launch.json', {'C_exec': 'synthetic-head', 'parent_pid': parent_pid,
        'readiness_sha256': f.digest, 'started': start, 'outer_deadline': start + 20,
        'owner_operation_asserted': True})
    f.entry.write(directory / 'entry.json', {'C_exec': 'synthetic-head', 'parent_pid': parent_pid,
        'readiness_sha256': f.digest, 'started': start, 'deadline': start + 15, 'arm': directory.name})
    return directory


def test_synthetic_metadata_preflight_positive(prepared):
    f = prepared
    assert f.entry.preflight(f.path, f.digest)['C_exec'] == 'synthetic-head'


@pytest.mark.parametrize('case,error', [
    ('head', 'EXECUTION_IDENTITY_MISMATCH'), ('readiness', 'READINESS_HASH_MISMATCH'),
    ('source_manifest', 'SOURCE_HASH_MISMATCH'), ('protocol', 'PROTOCOL_DRIFT'),
    ('source_bytes', 'SOURCE_OR_ENVIRONMENT_DRIFT'), ('environment', 'SOURCE_OR_ENVIRONMENT_DRIFT'),
])
def test_identity_rejection(prepared, monkeypatch, case, error):
    f = prepared
    digest = f.digest
    if case == 'head':
        monkeypatch.setattr(f.entry, 'head', lambda: 'wrong-head')
    elif case == 'readiness':
        digest = '0' * 64
    elif case == 'source_manifest':
        f.path.with_name('source.json').write_text('{}')
    elif case == 'protocol':
        (f.entry.DESIGN / 'protocol.json').write_text('{}')
    elif case == 'source_bytes':
        (f.root / 'fixture.txt').write_text('tampered')
    elif case == 'environment':
        monkeypatch.setattr(f.entry, 'environment', lambda: {'wrong': True})
    with pytest.raises(RuntimeError, match=error):
        f.entry.preflight(f.path, digest)


def test_no_owner_stops_before_preflight(prepared, monkeypatch):
    f = prepared
    monkeypatch.setattr(f.run, 'preflight', lambda *args: pytest.fail('must not reach preflight'))
    with pytest.raises(PermissionError, match='SEPARATE_OWNER'):
        f.run.launch(f.path, f.digest, f.tmp / 'unauthorized', False)
    assert not (f.tmp / 'unauthorized').exists()


def test_consumed_replay_stops_before_preflight(prepared, monkeypatch):
    f = prepared
    directory = context(f, os.getppid())
    (directory / 'consumed').touch()
    monkeypatch.setattr(f.run, 'preflight', lambda *args: pytest.fail('replay must not reach preflight'))
    with pytest.raises(FileExistsError):
        f.run.worker(f.path, f.digest, directory)


def sentinel_source():
    return ("import sys,importlib.abc\n"
            "class BlockHeavy(importlib.abc.MetaPathFinder):\n"
            " def find_spec(self,fullname,path=None,target=None):\n"
            "  if fullname.split('.')[0] in {'torch','numpy','mujoco','gym','gymnasium'}: raise AssertionError('HEAVY_IMPORT_ATTEMPT:'+fullname)\n"
            "sys.meta_path.insert(0,BlockHeavy())\n")


def test_direct_worker_rejected_before_heavy_imports(prepared):
    f = prepared
    directory = context(f, -1)
    script = f.tmp / 'direct.py'
    script.write_text(sentinel_source() + f'sys.path.insert(0,{str(HERE)!r})\nimport run\n'
        f'try: run.worker(__import__("pathlib").Path({str(f.path)!r}),{f.digest!r},__import__("pathlib").Path({str(directory)!r}))\n'
        'except PermissionError: print("DIRECT_REJECTED_BEFORE_HEAVY_IMPORTS"); sys.exit(0)\n'
        'raise AssertionError("direct worker accepted")\n', encoding='utf-8')
    result = f.run.supervise([sys.executable, '-B', str(script)], directory, time.perf_counter() + 8, f.tmp)
    assert result['passed']
    assert 'DIRECT_REJECTED_BEFORE_HEAVY_IMPORTS' in (directory / 'worker.log').read_text()
    assert not (directory / 'consumed').exists()


def test_real_supervise_worker_preflight_synthetic_backend(prepared):
    f = prepared
    directory = context(f, os.getpid())
    script = f.tmp / 'positive.py'
    script.write_text(sentinel_source() +
        f'sys.path.insert(0,{str(HERE)!r})\nimport entry\nfrom pathlib import Path\nimport types\n'
        f'entry.ROOT=Path({str(f.root)!r})\nentry.DESIGN=entry.ROOT/"design"\nentry.OLD=entry.ROOT/"old"\n'
        'entry.head=lambda:"synthetic-head"\n'
        'entry.files=lambda:{"fixture.txt":entry.sha(entry.ROOT/"fixture.txt")}\n'
        'entry.environment=lambda:{"kind":"synthetic metadata, not installed environment attestation"}\n'
        'backend=types.ModuleType("backend")\n'
        'def execute(arm,directory,deadline):\n'
        ' assert (directory/"consumed").exists()\n'
        ' entry.write(directory/"synthetic-executed.json",{"arm":arm,"physics":0,"inference":0})\n'
        ' return {"complete":True,"physical_failure_observed":False}\n'
        'backend.execute=execute\nsys.modules["backend"]=backend\nimport run\n'
        f'sys.exit(run.worker(Path({str(f.path)!r}),{f.digest!r},Path({str(directory)!r})))\n', encoding='utf-8')
    result = f.run.supervise([sys.executable, '-B', str(script)], directory, time.perf_counter() + 8, f.tmp)
    assert result['passed'], (directory / 'worker.log').read_text()
    assert f.entry.read(directory / 'synthetic-executed.json') == {'arm': directory.name, 'physics': 0, 'inference': 0}
