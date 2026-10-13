"""T2a launch-boundary primitives: one forked Worker under one bounded lifecycle.

Stdlib only: no NumPy/Torch/MuJoCo/backend import, no simulator, policy or checkpoint
access. Trust boundary (trusted same-machine serial one-shot research; not multi-user
authentication): only the canonical `run.py` supervisor entry runs Readiness/source
preflight before any side effect, creates one new campaign directory exclusively,
holds an exclusive lock, writes an immutable execution manifest and POSIX-forks one
Worker with start_new_session semantics. The Worker receives the launcher context in
inherited memory; CLI flags, environment self-reports or caller-authored JSON cannot
obtain or fabricate it. Context fields, actual kernel parent facts and the manifest
bytes bind the Worker to its creating supervisor. No delegation pipe, token, permit
or other authentication object exists.
"""
import ctypes,hashlib,json,os,signal,sys,threading,time,traceback
from pathlib import Path

VERSION='g1.t2a.launch.v1'
MANIFEST_NAME='execution-manifest.json'
RECEIPT_NAME='process-receipt.json'
LOCK_NAME='run.lock'
STDOUT_NAME='worker.stdout.raw'
STDERR_NAME='worker.stderr.raw'
REMOVED_WORKER_FLAGS=('--worker-owner-approved','--supervisor-fd','--worker')
GROUP_GRACE_S=.25
GROUP_KILL_WAIT_S=2.0
GROUP_POLL_S=.02
CLEANUP_ALLOWANCE_S=5.0
CHILD_EXIT_REFUSED=76
_CHILD_BOOT_EXIT=70


class LaunchRefused(RuntimeError):
    """A launch that does not present a genuine inherited supervisor context."""


def _refuse(reason):
    raise LaunchRefused(reason)


class DeadlineInterrupt(Exception):
    """Main-thread SIGALRM interrupt bounding one supervisor lifecycle."""


def _deadline_signal(signum,frame):
    raise DeadlineInterrupt('supervisor_deadline')


class lifecycle_deadline:
    """Bound a synchronous lifecycle step by one absolute monotonic deadline.

    Arms ITIMER_REAL/SIGALRM in the main thread only, so a stalled synchronous
    verifier, manifest write or fork hand-off is interrupted at the cutoff instead of
    running past it; the previous handler and interval timer are restored on exit.
    This is a bounded-interruption mechanism, not authentication.
    """
    __slots__=('deadline_s','_saved')
    def __init__(self,deadline_s):
        self.deadline_s=deadline_s
        self._saved=None
    def __enter__(self):
        if threading.current_thread() is not threading.main_thread():
            _refuse('main_thread_required')
        if threading.current_thread() is threading.main_thread():
            self._saved=(signal.getsignal(signal.SIGALRM),signal.getitimer(signal.ITIMER_REAL))
            signal.signal(signal.SIGALRM,_deadline_signal)
            signal.setitimer(signal.ITIMER_REAL,max(1e-6,self.deadline_s-time.monotonic()))
        return self
    def __exit__(self,exc_type,exc,tb):
        if self._saved is not None:
            signal.setitimer(signal.ITIMER_REAL,0.)
            signal.signal(signal.SIGALRM,self._saved[0])
            delay,interval=self._saved[1]
            if delay>0 or interval>0:
                signal.setitimer(signal.ITIMER_REAL,delay,interval)
            self._saved=None
        return False


def proc_identity(pid=None):
    # Straight from /proc: binds exact pid, state, parent, process group, session,
    # process start ticks and cmdline bytes without cross-session getsid() calls.
    pid=os.getpid() if pid is None else int(pid)
    text=Path(f'/proc/{pid}/stat').read_text()
    fields=text[text.rindex(')')+2:].split()
    return {'pid':pid,'state':fields[0],'ppid':int(fields[1]),'pgrp':int(fields[2]),'sid':int(fields[3]),
            'start_ticks':int(fields[19]),
            'cmdline_sha256':hashlib.sha256(Path(f'/proc/{pid}/cmdline').read_bytes()).hexdigest()}


_CTX_SEAL=object()


class LauncherContext:
    """Inherited in-memory launch context; only the supervising process creates it."""
    __slots__=('run_id','readiness_path','manifest_path','manifest_sha256','readiness_sha256','execution_head','protocol_sha256',
               'supervisor_pid','supervisor_start_ticks','worker_pid','started_unix','deadline_monotonic','run_inputs','_seal')
    def __init__(self,*,run_id,manifest_path,manifest_sha256,readiness_sha256,execution_head,protocol_sha256,
                 supervisor_pid,supervisor_start_ticks,started_unix,deadline_monotonic,run_inputs,seal,readiness_path=None):
        if seal is not _CTX_SEAL:_refuse('launch_context_construction_forbidden')
        self.run_id=run_id
        self.readiness_path=readiness_path
        self.manifest_path=manifest_path
        self.manifest_sha256=manifest_sha256
        self.readiness_sha256=readiness_sha256
        self.execution_head=execution_head
        self.protocol_sha256=protocol_sha256
        self.supervisor_pid=supervisor_pid
        self.supervisor_start_ticks=supervisor_start_ticks
        self.worker_pid=None
        self.started_unix=started_unix
        self.deadline_monotonic=deadline_monotonic
        self.run_inputs=run_inputs
        self._seal=_CTX_SEAL


def is_genuine_context(context):
    return isinstance(context,LauncherContext) and context._seal is _CTX_SEAL


def require_launch_context(context,*,run_identity,manifest,readiness_sha256,execution_head,protocol_sha256):
    """Re-check the inherited launch context, manifest bytes and bindings in the Worker.

    Runs before the real frozen verification and before any heavy import; `execute`
    calls it again, so a direct caller can never reach NumPy/Torch. Only the forked
    Worker instance of the creating supervisor qualifies.
    """
    if not is_genuine_context(context):
        _refuse('inherited_launch_context_required')
    if os.getpid()!=context.worker_pid:
        _refuse('worker_identity_mismatch')
    try:
        if os.getsid(0)!=os.getpid():
            _refuse('worker_not_own_session')
    except OSError:
        _refuse('worker_not_own_session')
    ppid=os.getppid()
    if ppid!=context.supervisor_pid:
        _refuse('supervisor_parent_mismatch')
    try:
        parent=proc_identity(ppid)
    except (OSError,ValueError,IndexError):
        _refuse('supervisor_identity_unavailable')
    if parent['start_ticks']!=context.supervisor_start_ticks:
        _refuse('supervisor_lifetime_changed')
    if context.deadline_monotonic is not None and time.monotonic()>context.deadline_monotonic:
        _refuse('launch_context_expired')
    if Path(run_identity).resolve()!=Path(context.run_id):
        _refuse('run_identity_binding_mismatch')
    if Path(manifest).resolve()!=Path(context.readiness_path):
        _refuse('manifest_binding_mismatch')
    if readiness_sha256!=context.readiness_sha256:
        _refuse('readiness_binding_mismatch')
    if execution_head!=context.execution_head:
        _refuse('execution_head_binding_mismatch')
    if protocol_sha256!=context.protocol_sha256:
        _refuse('protocol_binding_mismatch')
    try:
        raw=Path(context.manifest_path).read_bytes()
    except OSError:
        _refuse('manifest_unavailable')
    if hashlib.sha256(raw).hexdigest()!=context.manifest_sha256:
        _refuse('manifest_bytes_changed')
    try:
        document=json.loads(raw.decode())
    except (ValueError,UnicodeDecodeError):
        _refuse('manifest_unreadable')
    if not isinstance(document,dict):
        _refuse('manifest_unreadable')
    if document.get('run_id')!=context.run_id:_refuse('manifest_run_identity_mismatch')
    if document.get('execution_head')!=context.execution_head:_refuse('manifest_execution_head_mismatch')
    if document.get('protocol_sha256')!=context.protocol_sha256:_refuse('manifest_protocol_mismatch')
    if document.get('readiness_sha256')!=context.readiness_sha256:_refuse('manifest_readiness_mismatch')
    if document.get('supervisor_pid')!=context.supervisor_pid:_refuse('manifest_supervisor_mismatch')
    if document.get('supervisor_start_ticks')!=context.supervisor_start_ticks:_refuse('manifest_supervisor_mismatch')
    if document.get('run_inputs')!=context.run_inputs:_refuse('manifest_run_inputs_mismatch')
    return document


def _proc_table():
    table={}
    for name in os.listdir('/proc'):
        if not name.isdigit():
            continue
        try:
            table[int(name)]=proc_identity(int(name))
        except (OSError,ValueError,IndexError):
            pass
    return table


def _descendants(table,pid):
    children={}
    for child,info in table.items():
        children.setdefault(info['ppid'],[]).append(child)
    found=[];stack=[pid]
    while stack:
        for child in children.get(stack.pop(),[]):
            if child not in found:
                found.append(child);stack.append(child)
    return found


def _live_targets(owned_pid):
    # Everything the supervisor owns: the forked worker, its process-group/session
    # members including session-escaping descendants that re-parented to this process
    # as the minimal Linux subreaper. Zombies must also be reaped.
    table=_proc_table()
    me=os.getpid()
    targets=set(_descendants(table,me))
    for pid,info in table.items():
        if pid==me:
            continue
        if info['pgrp']==owned_pid or info['sid']==owned_pid:
            targets.add(pid)
    return targets  # A zombie still requires waitpid; dead is not yet reaped.


def _targets_alive(owned_pid):
    try:
        return bool(_live_targets(owned_pid))
    except Exception:
        return True  # unreadable /proc means unconfirmed, never "clean"


def _set_child_subreaper():
    if ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)!=0:
        raise OSError(ctypes.get_errno(),'subreaper_setup_failed')


def _signal_tree(owned_pid,signum):
    try:
        os.killpg(owned_pid,signum)
    except OSError:
        pass
    try:
        targets=_live_targets(owned_pid)
    except Exception:
        targets=set()
    for pid in (owned_pid,)+tuple(sorted(targets)):
        try:
            os.kill(pid,signum)
        except OSError:
            pass


def _reap_children():
    reaped={}
    while True:
        try:
            pid,status=os.waitpid(-1,os.WNOHANG)
        except (ChildProcessError,OSError):
            return reaped
        if pid==0:
            return reaped
        reaped[pid]=status


def _cleanup_lifecycle(owned_pid,total_deadline_s,terminator=None):
    # One bounded group cleanup for every exit path: a single 250 ms SIGTERM grace for
    # the whole owned tree, then capped SIGKILL plus reaping, all inside the total
    # budget. Unconfirmed termination is reported incomplete, never as success.
    info={'cleanup_complete':False,'cleanup_detail':'cleanup_not_run','worker_status':None}
    if owned_pid is None:
        info['cleanup_complete']=True
        info['cleanup_detail']=None
        return info
    terminate=terminator if terminator is not None else _signal_tree
    def settle(until):
        while True:
            for pid,status in _reap_children().items():
                if pid==owned_pid:
                    info['worker_status']=status
            if not _targets_alive(owned_pid):
                return True
            if time.monotonic()>=until:
                return False
            time.sleep(GROUP_POLL_S)
    try:
        if total_deadline_s-time.monotonic()<=0:
            info['cleanup_detail']='cleanup_deadline_exhausted'
            return info
        terminate(owned_pid,signal.SIGTERM)
        if settle(min(time.monotonic()+GROUP_GRACE_S,total_deadline_s)):
            info['cleanup_complete']=True
            info['cleanup_detail']=None
            return info
        if total_deadline_s-time.monotonic()>0:
            terminate(owned_pid,signal.SIGKILL)
            if settle(min(time.monotonic()+GROUP_KILL_WAIT_S,total_deadline_s)):
                info['cleanup_complete']=True
                info['cleanup_detail']=None
                return info
        for pid,status in _reap_children().items():
            if pid==owned_pid:
                info['worker_status']=status
        info['cleanup_detail']='descendants_persist' if _targets_alive(owned_pid) else 'worker_unreaped'
        return info
    except Exception as exc:
        info['cleanup_detail']=f'{type(exc).__name__}:{exc}'
        return info


def _acquire_lock(run_dir):
    path=run_dir/LOCK_NAME
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        import fcntl
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except ImportError:
        pass
    except OSError:
        os.close(fd)
        _refuse('run_lock_unavailable')
    return fd


def _manifest_doc(run_dir,readiness_sha256,execution_head,protocol_sha256,run_inputs,supervisor_start_ticks,started_unix):
    return {'schema':'g1-t2a-execution-manifest-v1','run_id':str(run_dir),'execution_head':execution_head,
            'protocol_sha256':protocol_sha256,'readiness_sha256':readiness_sha256,'started_unix':started_unix,
            'run_inputs':dict(run_inputs),'supervisor_pid':os.getpid(),'supervisor_start_ticks':supervisor_start_ticks}


def _status_exitcode(status):
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return -os.WTERMSIG(status)
    return None


def _signal_reason(state):
    if state.get('signal') is None:
        return None
    try:
        return 'signal:'+signal.Signals(state['signal']).name
    except ValueError:
        return 'signal:%d'%state['signal']


def _wait_worker(owned_pid,deadline_s,poll_s,state):
    while True:
        try:
            done,status=os.waitpid(owned_pid,os.WNOHANG)
        except ChildProcessError:
            return {'status':None,'reason':'reaped'}
        if done==owned_pid:
            return {'status':status,'reason':None}
        reason=_signal_reason(state)
        if reason is not None:
            return {'status':None,'reason':reason}
        if time.monotonic()>=deadline_s:
            return {'status':None,'reason':'wall_clock_watchdog'}
        time.sleep(poll_s)


def _child_main(worker_main,context,out_fd,err_fd,previous_mask):
    # Runs in the forked child only; never returns. Resets inherited signal state and
    # owns one session/process group so the supervisor can clean up the whole tree.
    code=_CHILD_BOOT_EXIT
    try:
        signal.signal(signal.SIGTERM,signal.SIG_DFL)
        signal.signal(signal.SIGINT,signal.SIG_DFL)
        signal.signal(signal.SIGALRM,signal.SIG_DFL)
        signal.setitimer(signal.ITIMER_REAL,0.)
        try:
            os.setsid()
        except OSError:
            pass
        os.dup2(out_fd,1);os.dup2(err_fd,2)
        sys.stdout=os.fdopen(os.dup(1),'w',buffering=1)
        sys.stderr=os.fdopen(os.dup(2),'w',buffering=1)
        null_fd=os.open(os.devnull,os.O_RDONLY)
        os.dup2(null_fd,0);os.close(null_fd)
        signal.pthread_sigmask(signal.SIG_SETMASK,previous_mask)
        context.worker_pid=os.getpid()
        code=0
        try:
            outcome=worker_main(context)
            if isinstance(outcome,int) and outcome:
                code=outcome
        except LaunchRefused as exc:
            print('WORKER_REFUSED:'+str(exc),file=sys.stderr,flush=True)
            code=CHILD_EXIT_REFUSED
        except SystemExit as exc:
            if isinstance(exc.code,int):
                code=exc.code
            elif exc.code is None:
                code=0
            else:
                print(str(exc.code),file=sys.stderr,flush=True)
                code=1
        except BaseException:
            traceback.print_exc()
            code=1
    except BaseException:
        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(code)


def _write_receipt(run_dir,result,created):
    if not created or not run_dir.is_dir():
        return 'run_directory_unavailable'
    try:
        (run_dir/RECEIPT_NAME).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        return None
    except Exception as exc:
        try:
            print(f'T2A_RECEIPT_WRITE_FAILED:{type(exc).__name__}:{exc}',file=sys.stderr)
        except Exception:
            pass
        return f'{type(exc).__name__}:{exc}'


def supervise(worker_main,root,limit_s=None,*,run_identity=None,manifest,readiness_sha256,execution_head,
              protocol_sha256,run_inputs=None,poll_s=.05,deadline_s=None,total_deadline_s=None,
              terminator=None,subreaper=True,started_s=None):
    """Run one forked Worker under one bounded lifecycle.

    Preflight, exclusive directory/lock/immutable-manifest creation, fork, Worker
    verification/execution, cleanup and receipt share the caller's absolute
    `deadline_s` (595 s from supervisor entry in production). At the cutoff the whole
    owned tree receives one 250 ms SIGTERM grace, then SIGKILL/reap inside
    `total_deadline_s` (600 s total). SIGTERM/SIGINT also enter cleanup. Cleanup
    uncertainty is recorded honestly and never masks Worker failure evidence; Worker
    physical-failure files are never touched. Only this supervisor creates the run.
    """
    started=time.monotonic() if started_s is None else started_s
    if threading.current_thread() is not threading.main_thread():
        _refuse('main_thread_required')
    # This launcher owns a dedicated serial process, not a shared application host.
    if _descendants(_proc_table(),os.getpid()):
        _refuse('dedicated_supervisor_required')
    if len(os.listdir('/proc/self/task'))!=1:
        _refuse('single_thread_supervisor_required')
    if deadline_s is None:
        deadline_s=started+max(0.,limit_s if limit_s is not None else 0.)
    if total_deadline_s is None:
        total_deadline_s=deadline_s+CLEANUP_ALLOWANCE_S
    if limit_s is None:
        limit_s=deadline_s-started
    run_dir=Path(run_identity if run_identity is not None else root).resolve()
    manifest_path=Path(manifest).resolve()
    if run_inputs is None:
        run_inputs={'root':str(Path(root).resolve()),'manifest':str(manifest_path),'readiness_sha256':readiness_sha256}
    state={'signal':None}
    previous_handlers={}
    installed=False
    def _on_signal(signum,frame):
        if state['signal'] is None:
            state['signal']=signum
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM,signal.SIGINT):
            previous_handlers[signum]=signal.getsignal(signum)
            signal.signal(signum,_on_signal)
        installed=True
    interrupted=None;failure=None;phase='setup';owned_pid=None;native_exitcode=None
    manifest_sha256=None;lock_fd=None;created=False
    try:
        try:
            reason=_signal_reason(state)
            if reason is not None:
                interrupted=reason
            elif time.monotonic()>=deadline_s:
                interrupted='wall_clock_watchdog'
            else:
                with lifecycle_deadline(deadline_s):
                    if not subreaper:_refuse('subreaper_required')
                    _set_child_subreaper()
                    try:
                        run_dir.mkdir(mode=0o700,exist_ok=False)
                    except FileExistsError:
                        raise LaunchRefused('run_replay_refused')
                    created=True
                    phase='manifest'
                    lock_fd=_acquire_lock(run_dir)
                    document=_manifest_doc(run_dir,readiness_sha256,execution_head,protocol_sha256,run_inputs,
                                           proc_identity()['start_ticks'],time.time())
                    execution_manifest=run_dir/MANIFEST_NAME
                    raw=json.dumps(document,sort_keys=True,separators=(',',':')).encode()
                    execution_manifest.write_bytes(raw)
                    os.chmod(execution_manifest,0o444)
                    manifest_sha256=hashlib.sha256(raw).hexdigest()
                    phase='spawn'
                    reason=_signal_reason(state)
                    if reason is not None:
                        interrupted=reason
                    elif time.monotonic()>=deadline_s:
                        interrupted='wall_clock_watchdog'
                    else:
                        context=LauncherContext(run_id=str(run_dir),readiness_path=str(manifest_path),manifest_path=str(run_dir/MANIFEST_NAME),
                            manifest_sha256=manifest_sha256,readiness_sha256=readiness_sha256,
                            execution_head=execution_head,protocol_sha256=protocol_sha256,
                            supervisor_pid=os.getpid(),supervisor_start_ticks=document['supervisor_start_ticks'],
                            started_unix=document['started_unix'],deadline_monotonic=deadline_s,
                            run_inputs=document['run_inputs'],seal=_CTX_SEAL)
                        out_fd=os.open(run_dir/STDOUT_NAME,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                        err_fd=os.open(run_dir/STDERR_NAME,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                        try:
                            blocked={signal.SIGTERM,signal.SIGINT,signal.SIGALRM}
                            previous_mask=signal.pthread_sigmask(signal.SIG_BLOCK,blocked)
                            try:
                                pid=os.fork()
                                if pid==0:
                                    _child_main(worker_main,context,out_fd,err_fd,previous_mask)
                                owned_pid=pid
                            finally:
                                signal.pthread_sigmask(signal.SIG_SETMASK,previous_mask)
                        finally:
                            os.close(out_fd);os.close(err_fd)
                        phase='supervise'
                        outcome=_wait_worker(owned_pid,deadline_s,poll_s,state)
                        if outcome['status'] is not None:
                            native_exitcode=_status_exitcode(outcome['status'])
                        elif outcome['reason'] not in (None,'reaped'):
                            interrupted=outcome['reason']
        except DeadlineInterrupt:
            interrupted=interrupted or 'wall_clock_watchdog'
        except BaseException as exc:
            failure=exc
    finally:
        # Reserve the last second for emergency reap and the receipt. Both cleanup
        # and receipt are interruptible, using the original entry-anchored budget.
        try:
            with lifecycle_deadline(total_deadline_s-1.):
                cleanup=_cleanup_lifecycle(owned_pid,total_deadline_s-1.,terminator)
        except BaseException as exc:
            cleanup={'cleanup_complete':False,'cleanup_detail':f'{type(exc).__name__}:{exc}',
                     'worker_status':None}
        if owned_pid is not None and not cleanup['cleanup_complete']:
            try:
                with lifecycle_deadline(total_deadline_s-.5):
                    _signal_tree(owned_pid,signal.SIGKILL)
                    while True:
                        statuses=_reap_children()
                        if owned_pid in statuses:cleanup['worker_status']=statuses[owned_pid]
                        if not _targets_alive(owned_pid):break
                        time.sleep(GROUP_POLL_S)
            except Exception as exc:
                cleanup['cleanup_detail']+=';emergency:'+type(exc).__name__
            # Even successful emergency reap does not erase the initial failure.
        if owned_pid is not None and native_exitcode is None and cleanup['worker_status'] is not None:
            native_exitcode=_status_exitcode(cleanup['worker_status'])
        result={'pid':owned_pid,'native_exitcode':native_exitcode,'interrupted':interrupted,
                'interrupted_phase':phase if interrupted else None,
                'failure_phase':phase if failure is not None else None,
                'failure':None if failure is None else f'{type(failure).__name__}:{failure}',
                'elapsed_s':time.monotonic()-started,'limit_s':limit_s,
                'deadline_from_entry_s':deadline_s-started,'total_from_entry_s':total_deadline_s-started,
                'cleanup_allowance_s':total_deadline_s-deadline_s,
                'cleanup_complete':cleanup['cleanup_complete'],'cleanup_detail':cleanup['cleanup_detail'],
                'manifest_sha256':manifest_sha256,'run_id':str(run_dir),'supervisor_pid':os.getpid(),
                'signal':state['signal'],'receipt_error':None}
        try:
            with lifecycle_deadline(total_deadline_s):
                result['receipt_error']=_write_receipt(run_dir,result,created)
        except BaseException as exc:
            result['receipt_error']=f'{type(exc).__name__}:{exc}'
        finally:
            if lock_fd is not None:
                try:os.close(lock_fd)
                except OSError:pass
            if installed:
                for signum,handler in previous_handlers.items():
                    signal.signal(signum,handler)
        if result['receipt_error'] is not None:
            # External invocation captures stderr if the filesystem cannot retain a receipt.
            print('T2A_PROCESS_RECEIPT_FAILURE:'+json.dumps(result,sort_keys=True),file=sys.stderr,flush=True)
    if failure is not None:
        raise failure
    return result
