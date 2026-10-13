"""Pure Python process tests. No simulator, policy, or numerical runtime imports."""
import ctypes
from ctypes import wintypes
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

spec = importlib.util.spec_from_file_location('handoff_lifecycle', Path(__file__).with_name('lifecycle.py'))
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Qualified Windows Job implementation only')


def invoke(tmp_path, source, seconds=8):
    script = tmp_path / 'synthetic.py'
    script.write_text(source, encoding='utf-8')
    return lifecycle.supervise([sys.executable, '-B', str(script)], tmp_path,
                               time.perf_counter() + seconds, tmp_path)


def exited(pid):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k.OpenProcess(0x100000, False, pid)
    if not handle:
        return ctypes.get_last_error() == 87  # process ID no longer exists
    try:
        return k.WaitForSingleObject(handle, 0) == 0
    finally:
        k.CloseHandle(handle)


def descendant_source(root_exit):
    # Child publishes its own PID after Python startup, excluding mere spawn
    # success as proof. It in turn spawns a grandchild, also in the same Job.
    grandchild = "import os,time; from pathlib import Path; Path('grandchild.pid').write_text(str(os.getpid())); time.sleep(30)"
    child = ("import os,sys,time,subprocess; from pathlib import Path; "
             "Path('child.pid').write_text(str(os.getpid())); "
             f"subprocess.Popen([sys.executable,'-B','-c',{grandchild!r}]); time.sleep(30)")
    return ("import subprocess,sys,time\nfrom pathlib import Path\n"
            f"subprocess.Popen([sys.executable,'-B','-c',{child!r}])\n"
            "while not Path('grandchild.pid').exists(): time.sleep(.01)\n"
            + (f"sys.exit({root_exit})\n" if root_exit is not None else "time.sleep(30)\n"))


def test_normal_exit_and_venv_identity(tmp_path):
    result = invoke(tmp_path, "import sys,json; print(json.dumps({'executable':sys.executable,'prefix':sys.prefix}))")
    assert result['passed'] and result['job_assigned_before_resume']
    child = json.loads((tmp_path / 'worker.log').read_text())
    assert Path(child['executable']).resolve() == Path(sys.executable).resolve()
    assert Path(child['prefix']).resolve() == Path(sys.prefix).resolve()
    assert json.loads((tmp_path / 'process_receipt.json').read_text()) == result


def test_exception_preserved(tmp_path):
    result = invoke(tmp_path, "raise RuntimeError('synthetic failure')")
    assert not result['passed'] and result['returncode'] != 0
    assert result['tree_empty'] and result['reaped'] and not result['cleanup_errors']
    assert 'synthetic failure' in (tmp_path / 'worker.log').read_text()


@pytest.mark.parametrize('root_exit', [0, 7, None])
def test_descendants_cleaned_normal_crash_timeout(tmp_path, root_exit):
    result = invoke(tmp_path, descendant_source(root_exit), seconds=3.5 if root_exit is None else 8)
    assert result['tree_empty'] and result['reaped'] and not result['cleanup_errors']
    assert result['within_deadline']
    assert result['passed'] == (root_exit == 0)
    assert result['timed_out'] == (root_exit is None)
    for name in ('child.pid', 'grandchild.pid'):
        assert exited(int((tmp_path / name).read_text()))


def test_cleanup_failure_is_not_pass(tmp_path, monkeypatch):
    def fail_termination(self):
        raise OSError('injected cleanup failure')
    monkeypatch.setattr(lifecycle._Job, 'terminate', fail_termination)
    result = invoke(tmp_path, descendant_source(0))
    assert not result['passed'] and result['cleanup_errors'] == ['injected cleanup failure']
    # The independent kill-on-close fallback still prevents orphaned children.
    for name in ('child.pid', 'grandchild.pid'):
        deadline = time.perf_counter() + 1
        while not exited(int((tmp_path / name).read_text())) and time.perf_counter() < deadline:
            time.sleep(.01)
        assert exited(int((tmp_path / name).read_text()))


def test_assign_failure_prevents_code_execution(tmp_path, monkeypatch):
    def fail_assign(self, process):
        raise OSError('injected assign failure')
    monkeypatch.setattr(lifecycle._Job, 'assign', fail_assign)
    result = invoke(tmp_path, "from pathlib import Path; Path('executed').touch()")
    assert not result['passed'] and result['reaped']
    assert result['exception']['message'] == 'injected assign failure'
    assert not (tmp_path / 'executed').exists()


def test_startup_time_consumes_same_deadline(tmp_path, monkeypatch):
    original = lifecycle._Job.assign
    def slow_assign(self, process):
        original(self, process)
        time.sleep(.3)
    monkeypatch.setattr(lifecycle._Job, 'assign', slow_assign)
    result = invoke(tmp_path, "from pathlib import Path; Path('executed').touch()", seconds=2.15)
    assert result['exception']['message'] == 'STARTUP_DEADLINE'
    assert not result['passed'] and result['reaped'] and result['tree_empty']
    assert result['within_deadline'] and not (tmp_path / 'executed').exists()


def test_exhausted_budget_does_not_spawn(tmp_path):
    result = invoke(tmp_path, "raise AssertionError('must not execute')", seconds=1)
    assert not result['passed'] and 'pid' not in result
    assert result['exception']['message'] == 'NO_STARTUP_BUDGET'


def test_spawn_failure_receipt(tmp_path, monkeypatch):
    def fail_spawn(*args, **kwargs):
        raise OSError('injected spawn failure')
    monkeypatch.setattr(lifecycle.subprocess, 'Popen', fail_spawn)
    result = invoke(tmp_path, 'pass')
    assert not result['passed'] and result['exception']['message'] == 'injected spawn failure'
    assert (tmp_path / 'process_receipt.json').exists()


def test_no_overwrite_of_previous_receipt(tmp_path):
    first = invoke(tmp_path, 'pass')
    before = (tmp_path / 'process_receipt.json').read_bytes()
    with pytest.raises(FileExistsError):
        invoke(tmp_path, 'pass')
    assert first['passed'] and (tmp_path / 'process_receipt.json').read_bytes() == before


def test_supervisor_abrupt_exit_kills_job_tree(tmp_path):
    script = tmp_path / 'synthetic.py'
    script.write_text(descendant_source(None), encoding='utf-8')
    supervisor = tmp_path / 'supervisor.py'
    supervisor.write_text(
        'import sys,time\nfrom pathlib import Path\n'
        f'sys.path.insert(0, {str(Path(__file__).parent)!r})\n'
        'from lifecycle import supervise\n'
        f'supervise([sys.executable,"-B",{str(script)!r}], Path({str(tmp_path)!r}), time.perf_counter()+20, Path({str(tmp_path)!r}))\n',
        encoding='utf-8')
    env = dict(os.environ, __PYVENV_LAUNCHER__=sys.executable)
    parent = subprocess.Popen([sys._base_executable, '-B', str(supervisor)], env=env)
    try:
        deadline = time.perf_counter() + 5
        while not (tmp_path / 'grandchild.pid').exists() and time.perf_counter() < deadline:
            time.sleep(.01)
        assert (tmp_path / 'grandchild.pid').exists()
        parent.kill()
        parent.wait(timeout=2)
        for name in ('child.pid', 'grandchild.pid'):
            deadline = time.perf_counter() + 2
            while not exited(int((tmp_path / name).read_text())) and time.perf_counter() < deadline:
                time.sleep(.01)
            assert exited(int((tmp_path / name).read_text()))
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)


def test_nested_supervisors_positive_and_outer_timeout_cleanup(tmp_path):
    """Outer CLI Job contains an inner per-arm Job on the actual host."""
    for timeout in (False, True):
        run = tmp_path / ('outer-timeout' if timeout else 'positive')
        run.mkdir()
        inner = run / 'inner'
        inner.mkdir()
        worker = inner / 'worker.py'
        worker.write_text(descendant_source(None) if timeout else 'print("nested positive")', encoding='utf-8')
        source = (
            'import sys,time,json\nfrom pathlib import Path\n'
            f'sys.path.insert(0, {str(Path(__file__).parent)!r})\n'
            'from lifecycle import supervise\n'
            f'r=supervise([sys.executable,"-B",{str(worker)!r}], Path({str(inner)!r}), time.perf_counter()+15, Path({str(inner)!r}))\n'
            'print(json.dumps(r),flush=True)\n'
            'sys.exit(0 if r["passed"] else 3)\n'
        )
        result = invoke(run, source, seconds=3.5 if timeout else 8)
        assert result['tree_empty'] and result['reaped'] and not result['cleanup_errors']
        assert result['within_deadline'] and result['passed'] == (not timeout)
        assert result['timed_out'] == timeout
        if timeout:
            for name in ('child.pid', 'grandchild.pid'):
                assert exited(int((inner / name).read_text()))
        else:
            nested = json.loads((inner / 'process_receipt.json').read_text())
            assert nested['passed'] and nested['job_assigned_before_resume'] and nested['tree_empty']
