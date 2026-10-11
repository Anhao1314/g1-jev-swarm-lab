"""T2a supervisor-only Worker delegation primitives. Stdlib only: no NumPy/Torch/
MuJoCo/backend import and no simulator, policy or checkpoint access.

Trust boundary (trusted same-machine serial one-shot research; not multi-user auth):
- Only this canonical `run.py` supervisor entry runs Readiness/source preflight, creates
  the campaign directory, the one-shot token file and the private pipe, then spawns its
  directly supervised Worker with start_new_session=True.
- The Worker anchors on itself: its executing source (`__file__`), its own kernel argv
  and the kernel facts of its parent. The parent must run the same interpreter and its
  argv must be the canonical supervisor entry built from the Worker's own positional
  arguments (`python [flags] run.py <root> <manifest> <sha> --execute-owner-approved`).
  A custom launcher that fabricates a real pipe, token and caller-authored JSON with
  true PID/session/start/cmdline facts is still refused, because its own argv is not the
  canonical supervisor entry. This is an accidental-launch/ancestry guard, not
  production authentication.
- `claim_execute` re-binds the consumed permit to the exact root/manifest/hash/HEAD/
  protocol plus current worker/parent lifetimes and expiry, and spends it exactly once
  before any runtime import.
"""
import hashlib,hmac,json,os,select,signal,stat,sys,time
from pathlib import Path
from types import MappingProxyType

VERSION = 'g1.t2a.supervisor.v2'
FD_FLAG = '--supervisor-fd'
WORKER_FLAG = '--worker-owner-approved'
SUPERVISOR_FLAG = '--execute-owner-approved'
TOKEN_NAME = 'delegation.token'
CONSUMED_SUFFIX = '.consumed'
MAX_DELEGATION_AGE_S = 600.0
MAX_DELEGATION_BYTES = 1 << 20
MAX_TRANSFER_S = 30.0
GROUP_GRACE_S = .25
GROUP_KILL_WAIT_S = 2.0
GROUP_POLL_S = .02
_EXE_FLAGS = ('-B', '-u')


class DelegationRefused(RuntimeError):
    """A Worker invocation that does not present a live supervisor delegation."""


def _refuse(reason):
    raise DelegationRefused(reason)


_SEAL = object()


class EntryTrust:
    """Worker-side anchor built from the Worker's own source file and kernel argv."""
    __slots__ = ('entry_path', 'python_path', 'root', 'manifest', 'sha256', 'fd', 'expected_parent_argv', '_seal')

    def __init__(self, entry_path, python_path, root, manifest, sha256, fd, expected_parent_argv, seal):
        if seal is not _SEAL:
            _refuse('entry_trust_construction_forbidden')
        self.entry_path = entry_path
        self.python_path = python_path
        self.root = root
        self.manifest = manifest
        self.sha256 = sha256
        self.fd = fd
        self.expected_parent_argv = expected_parent_argv
        self._seal = _SEAL


def entry_trust(entry_file, argv, *, python_path=None, expected_parent_argv=None):
    """Pin the Worker trust anchor from its own executing file and true kernel argv.

    `expected_parent_argv` is a synthetic test-only seam for exercising the positive
    path from a test harness; the real Worker entry never derives its anchor from
    CLI/env/JSON and run.py never passes this override.
    """
    entry = Path(entry_file).resolve()
    python = Path(sys.executable if python_path is None else python_path).resolve()
    argv = list(argv)
    if len(argv) != 7 or argv[4] != WORKER_FLAG or argv[5] != FD_FLAG:
        _refuse('worker_entry_argv_mismatch')
    if Path(argv[0]).resolve() != entry:
        _refuse('worker_entry_argv_mismatch')
    try:
        fd = int(argv[6])
    except ValueError:
        _refuse('worker_entry_argv_mismatch')
    return EntryTrust(entry, python, argv[1], argv[2], argv[3], fd,
                      None if expected_parent_argv is None else tuple(expected_parent_argv), _SEAL)


class Delegation:
    """Worker-side proof that the canonical supervising entry issued this run."""

    __slots__ = ('payload', '_seal', '_spent')

    def __init__(self, payload, seal):
        if seal is not _SEAL:
            _refuse('delegation_construction_forbidden')
        self._seal = _SEAL
        self.payload = MappingProxyType(dict(payload))
        self._spent = False


def is_live_delegation(obj):
    return isinstance(obj, Delegation) and obj._seal is _SEAL and obj.payload.get('protocol') == VERSION


def proc_identity(pid=None):
    # Straight from /proc: avoids getsid() cross-session permission errors and binds
    # exact pid, parent, session, process start ticks and cmdline bytes.
    pid = os.getpid() if pid is None else int(pid)
    text = Path(f'/proc/{pid}/stat').read_text()
    fields = text[text.rindex(')') + 2:].split()
    return {'pid': pid, 'ppid': int(fields[1]), 'sid': int(fields[3]), 'start_ticks': int(fields[19]),
            'cmdline_sha256': hashlib.sha256(Path(f'/proc/{pid}/cmdline').read_bytes()).hexdigest()}


def proc_argv(pid=None):
    pid = os.getpid() if pid is None else int(pid)
    return [part.decode('utf-8', 'surrogateescape')
            for part in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') if part]


def _exe_path(pid=None):
    pid = os.getpid() if pid is None else int(pid)
    return Path(os.readlink(f'/proc/{pid}/exe')).resolve()


def _identity(pid, tries=200):
    for _ in range(tries):
        try:
            return proc_identity(pid)
        except (FileNotFoundError, ProcessLookupError, ValueError, IndexError):
            time.sleep(.005)
    _refuse('worker_identity_unavailable')


def _require_pipe(fd):
    try:
        mode = os.fstat(fd).st_mode
    except OSError:
        _refuse('delegation_fd_unavailable')
    if not stat.S_ISFIFO(mode):
        _refuse('delegation_fd_not_a_pipe')


def _read_payload(fd, timeout_s=MAX_TRANSFER_S):
    deadline = time.monotonic() + max(0., timeout_s)
    chunks = []
    total = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _refuse('delegation_transfer_timeout')
        try:
            ready, _, _ = select.select([fd], [], [], remaining)
        except OSError:
            _refuse('delegation_fd_unavailable')
        if not ready:
            _refuse('delegation_transfer_timeout')
        try:
            data = os.read(fd, 65536)
        except BlockingIOError:
            continue
        except OSError:
            _refuse('delegation_fd_unavailable')
        if not data:
            break
        total += len(data)
        if total > MAX_DELEGATION_BYTES:
            _refuse('delegation_too_large')
        chunks.append(data)
    try:
        payload = json.loads(b''.join(chunks).decode())
    except (ValueError, UnicodeDecodeError):
        _refuse('malformed_delegation')
    if not isinstance(payload, dict):
        _refuse('malformed_delegation')
    return payload


def _consume_token(token, nonce, run_dir):
    path = Path(token) if isinstance(token, str) else None
    if path is None or path.parent != run_dir or path.name != TOKEN_NAME:
        _refuse('delegation_token_path_mismatch')
    try:
        recorded = path.read_text().strip()
    except OSError:
        _refuse('delegation_replayed_or_absent')
    if not isinstance(nonce, str) or not hmac.compare_digest(recorded, nonce):
        _refuse('delegation_token_mismatch')
    try:
        os.rename(path, str(path) + CONSUMED_SUFFIX)
    except OSError:
        _refuse('delegation_already_consumed')


def _parent_entry_ok(parent_argv, trust):
    if trust.expected_parent_argv is not None:
        return tuple(parent_argv) == trust.expected_parent_argv
    index = 1
    while index < len(parent_argv) and parent_argv[index] in _EXE_FLAGS:
        index += 1
    if index >= len(parent_argv) or Path(parent_argv[index]).resolve() != trust.entry_path:
        return False
    tail = parent_argv[index + 1:]
    if len(tail) != 4 or tail[3] != SUPERVISOR_FLAG:
        return False
    return (Path(tail[0]).resolve() == Path(trust.root).resolve()
            and Path(tail[1]).resolve() == Path(trust.manifest).resolve()
            and tail[2] == trust.sha256)


def consume_delegation(fd, trust, *, execution_head, protocol_sha256, max_age_s=MAX_DELEGATION_AGE_S,
                       transfer_timeout_s=MAX_TRANSFER_S):
    """Validate and one-shot-consume the supervisor payload read from the inherited fd.

    The parent is authenticated from kernel facts against the Worker's own pinned entry:
    same interpreter executable, canonical supervisor argv, session-leader Worker and a
    genuine inherited pipe. JSON claims alone never qualify.
    """
    try:
        return _consume_delegation(fd, trust, execution_head, protocol_sha256, max_age_s, transfer_timeout_s)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _consume_delegation(fd, trust, execution_head, protocol_sha256, max_age_s, transfer_timeout_s):
    if not isinstance(trust, EntryTrust) or trust._seal is not _SEAL:
        _refuse('entry_trust_required')
    if trust.fd != fd:
        _refuse('supervisor_fd_context_mismatch')
    _require_pipe(fd)
    payload = _read_payload(fd, transfer_timeout_s)
    if payload.get('protocol') != VERSION:
        _refuse('unsupported_delegation')
    run_dir = Path(trust.root).resolve()
    if payload.get('run_id') != str(run_dir):
        _refuse('run_identity_binding_mismatch')
    if payload.get('manifest') != str(Path(trust.manifest).resolve()):
        _refuse('manifest_binding_mismatch')
    if payload.get('readiness_sha256') != trust.sha256:
        _refuse('readiness_binding_mismatch')
    if payload.get('protocol_sha256') != protocol_sha256:
        _refuse('protocol_binding_mismatch')
    if payload.get('execution_head') != execution_head:
        _refuse('execution_head_binding_mismatch')
    issued = payload.get('issued_unix')
    if type(issued) is not float or not 0. <= time.time() - issued <= max_age_s:
        _refuse('stale_delegation')
    claimed_supervisor = payload.get('supervisor')
    claimed_worker = payload.get('worker')
    if not isinstance(claimed_supervisor, dict) or not isinstance(claimed_worker, dict):
        _refuse('malformed_delegation_identity')
    me = proc_identity()
    if me['sid'] != me['pid']:
        _refuse('worker_not_supervised_session')
    for key in ('pid', 'sid', 'start_ticks', 'cmdline_sha256'):
        if me[key] != claimed_worker.get(key):
            _refuse('worker_lifetime_mismatch')
    ppid = os.getppid()
    if ppid != claimed_supervisor.get('pid'):
        _refuse('parent_identity_mismatch')
    parent = proc_identity(ppid)
    for key in ('sid', 'start_ticks', 'cmdline_sha256'):
        if parent[key] != claimed_supervisor.get(key):
            _refuse('parent_lifetime_mismatch')
    if parent['ppid'] == me['pid']:
        _refuse('cyclic_process_ancestry')
    try:
        self_exe = _exe_path()
        parent_exe = _exe_path(ppid)
    except OSError:
        _refuse('supervisor_executable_unavailable')
    if self_exe != trust.python_path:
        _refuse('python_executable_mismatch')
    if parent_exe != trust.python_path:
        _refuse('supervisor_executable_mismatch')
    try:
        parent_argv = proc_argv(ppid)
    except OSError:
        _refuse('supervisor_entry_unavailable')
    if not _parent_entry_ok(parent_argv, trust):
        _refuse('supervisor_entry_mismatch')
    _consume_token(payload.get('token'), payload.get('nonce'), run_dir)
    return Delegation(payload, _SEAL)


def claim_execute(delegation, *, run_identity, manifest, readiness_sha256, execution_head, protocol_sha256,
                  max_age_s=MAX_DELEGATION_AGE_S):
    """Spend the one-shot permit, bound to the exact announcement, before runtime imports."""
    if not is_live_delegation(delegation):
        _refuse('supervisor_delegation_required')
    if delegation._spent:
        _refuse('delegation_already_spent')
    payload = delegation.payload
    if payload.get('run_id') != str(Path(run_identity).resolve()):
        _refuse('delegation_run_identity_mismatch')
    if payload.get('manifest') != str(Path(manifest).resolve()):
        _refuse('delegation_manifest_mismatch')
    if payload.get('readiness_sha256') != readiness_sha256:
        _refuse('delegation_readiness_mismatch')
    if payload.get('execution_head') != execution_head:
        _refuse('delegation_execution_head_mismatch')
    if payload.get('protocol_sha256') != protocol_sha256:
        _refuse('delegation_protocol_mismatch')
    issued = payload.get('issued_unix')
    if type(issued) is not float or not 0. <= time.time() - issued <= max_age_s:
        _refuse('delegation_expired')
    me = proc_identity()
    claimed_worker = payload.get('worker') or {}
    for key in ('pid', 'sid', 'start_ticks', 'cmdline_sha256'):
        if me[key] != claimed_worker.get(key):
            _refuse('delegation_worker_lifetime_changed')
    claimed_supervisor = payload.get('supervisor') or {}
    if os.getppid() != claimed_supervisor.get('pid'):
        _refuse('delegation_parent_lifetime_changed')
    parent = proc_identity(os.getppid())
    for key in ('sid', 'start_ticks', 'cmdline_sha256'):
        if parent[key] != claimed_supervisor.get(key):
            _refuse('delegation_parent_lifetime_changed')
    delegation._spent = True
    return True


def _send_payload(fd, data, transfer_timeout_s=MAX_TRANSFER_S):
    try:
        os.set_blocking(fd, False)
    except OSError:
        pass
    deadline = time.monotonic() + max(0., transfer_timeout_s)
    view = memoryview(data)
    sent = 0
    while sent < len(view):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('delegation_transfer_timeout')
        ready, _, _ = select.select([], [fd], [], remaining)
        if not ready:
            raise TimeoutError('delegation_transfer_timeout')
        try:
            sent += os.write(fd, view[sent:])
        except BlockingIOError:
            continue


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _reap_group(worker, grace_s=GROUP_GRACE_S):
    # Terminate and reap the whole supervised process group on every exit path, not only
    # on timeout: a normal or technical Worker exit must not leave living descendants.
    # The initial SIGTERM tolerates the process-race failure and still preserves receipt.
    pgid = worker.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        worker.wait(timeout=grace_s)
    except Exception:
        pass
    deadline = time.monotonic() + grace_s
    while _group_alive(pgid) and time.monotonic() < deadline:
        time.sleep(GROUP_POLL_S)
    if _group_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + GROUP_KILL_WAIT_S
        while _group_alive(pgid) and time.monotonic() < deadline:
            time.sleep(GROUP_POLL_S)
    try:
        worker.wait(timeout=GROUP_KILL_WAIT_S)
    except Exception:
        pass


def supervise(worker_argv, root, limit_s, *, run_identity, readiness_sha256, execution_head, protocol_sha256,
              manifest=None, poll_s=.05):
    """Run one directly supervised Worker with a private one-shot delegation.

    The outer cutoff covers the complete lifecycle, transfer included, and is measured
    from `started`; launch/identity/write failures close the pipe, terminate and reap the
    process group, and write a raw failure receipt without touching Worker
    physical-failure evidence. `root` is resolved before the token is generated.
    """
    root = Path(root).resolve()
    run_dir = Path(run_identity).resolve()
    nonce = os.urandom(32).hex()
    token_path = root / TOKEN_NAME
    handle = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(handle, nonce.encode())
    finally:
        os.close(handle)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(read_fd, True)
    started = time.monotonic()
    interrupted = None
    failure = None
    phase = 'spawn'
    worker = None
    try:
        with (root / 'worker.stdout.raw').open('xb') as out, (root / 'worker.stderr.raw').open('xb') as err:
            worker = subprocess.Popen(list(worker_argv) + [FD_FLAG, str(read_fd)], stdout=out, stderr=err,
                                      start_new_session=True, pass_fds=(read_fd,))
            os.close(read_fd)
            read_fd = None
            phase = 'identity'
            payload = {'protocol': VERSION, 'run_id': str(run_dir),
                       'manifest': None if manifest is None else str(Path(manifest).resolve()),
                       'readiness_sha256': readiness_sha256, 'execution_head': execution_head,
                       'protocol_sha256': protocol_sha256, 'nonce': nonce, 'token': str(token_path),
                       'issued_unix': time.time(), 'supervisor': proc_identity(), 'worker': _identity(worker.pid)}
            phase = 'delegation_write'
            _send_payload(write_fd, json.dumps(payload).encode(),
                          transfer_timeout_s=max(0., limit_s - (time.monotonic() - started)))
            os.close(write_fd)
            write_fd = None
            phase = 'supervise'
            while worker.poll() is None:
                if time.monotonic() - started >= limit_s:
                    interrupted = 'wall_clock_watchdog'
                    break
                time.sleep(poll_s)
    except BaseException as exc:
        failure = exc
    finally:
        for fd in (read_fd, write_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if worker is not None:
            _reap_group(worker)
    result = {'pid': None if worker is None else worker.pid,
              'native_exitcode': None if worker is None else worker.returncode,
              'interrupted': interrupted,
              'failure_phase': phase if failure is not None else None,
              'failure': None if failure is None else f'{type(failure).__name__}:{failure}',
              'elapsed_s': time.monotonic() - started, 'limit_s': limit_s,
              'delegation_consumed': (root / (TOKEN_NAME + CONSUMED_SUFFIX)).exists()}
    receipt = root / 'process-receipt.json'
    if not receipt.exists():
        receipt.write_text(json.dumps(result, indent=2))
    if failure is not None:
        raise failure
    return result