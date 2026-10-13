"""Nonphysical T2a launch-boundary checks: synthetic Linux processes only.

No physics, policy load, checkpoint load, prediction or real backend import. The
canonical positive drives the real guarded supervisor main -> POSIX-forked Worker
through a temporary Git/source fixture whose run.py/supervision.py/comparison.py/
protocol.json copies are byte-identical to this worktree, with the real frozen
verify(), hash-only historical checkpoint paths and a test-only post-guard synthetic
executor; NumPy/Torch are poisoned so any heavy import fails loudly instead of running.
Direct supervision tests fork real workers with synthetic Python bodies. Historical
checkpoints are hashed, never loaded.
"""
import hashlib,importlib.util,importlib.metadata,json,os,shutil,signal,subprocess,sys,time
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'experiments/rl/g1_ppo_t2a_frozen_comparison_001'
RUN=HERE/'run.py'
SUP=HERE/'supervision.py'
COMPARISON=HERE/'comparison.py'
PROTOCOL=HERE/'protocol.json'
CHECKPOINTS={'C0':Path('/home/g1rl/g1-rl/evidence/t1b-ppo-optimization-20261011/acquisition-once/checkpoint-0.zip'),
             'C256':Path('/home/g1rl/g1-rl/evidence/t1b-ppo-optimization-20261011/acquisition-once/checkpoint-256.zip')}
ALLOWED_MODIFIED={'experiments/rl/g1_ppo_t2a_frozen_comparison_001/run.py',
                  'experiments/rl/g1_ppo_t2a_frozen_comparison_001/supervision.py',
                  'tests/test_residual_rl_t2a_supervision.py'}
sys.path.insert(0,str(HERE))
import supervision as sup
_rspec=importlib.util.spec_from_file_location('t2_run_under_test',RUN);run=importlib.util.module_from_spec(_rspec);_rspec.loader.exec_module(run)


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _head():return subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
def _dead(pid,tries=240):
    for _ in range(tries):
        try:os.kill(pid,0)
        except OSError:return True
        time.sleep(.05)
    return False
def _poison_dir(base):
    poison=Path(base)/'poison';poison.mkdir(exist_ok=True);marker=Path(base)/'forbidden-import'
    for name in ('numpy','torch'):
        (poison/f'{name}.py').write_text("import pathlib\npathlib.Path(%r).write_text('imported')\nraise ImportError('poisoned %s')\n"%(str(marker),name))
    return poison,marker
def _sanitized_env(*prepend):
    env={k:v for k,v in os.environ.items() if k not in ('G1SWARM_ROOT','PYTHONHOME')}
    env['PYTHONPATH']=os.pathsep.join(str(p) for p in prepend)
    return env
def _guard_args(run_dir,manifest):
    return {'run_identity':run_dir,'manifest':manifest,'readiness_sha256':'R0','execution_head':'H0','protocol_sha256':'P0'}
def _run_supervised(base,name,body,*,limit_s=30,deadline_delta=None,total_delta=None,terminator=None):
    run_dir=Path(base)/name
    manifest=Path(base)/f'{name}.json';manifest.write_bytes(b'{"fixture":true}')
    deadline_s=None if deadline_delta is None else time.monotonic()+deadline_delta
    total_deadline_s=None if total_delta is None else time.monotonic()+total_delta
    def worker_main(context):return body(context,run_dir,manifest)
    result=sup.supervise(worker_main,run_dir,limit_s,run_identity=run_dir,manifest=manifest,readiness_sha256='R0',
                         execution_head='H0',protocol_sha256='P0',run_inputs={'case':name},
                         deadline_s=deadline_s,total_deadline_s=total_deadline_s,terminator=terminator)
    return result,run_dir,manifest
def _refusal_of(run_dir):
    stderr=(run_dir/sup.STDERR_NAME).read_text()
    assert 'WORKER_REFUSED:' in stderr,stderr
    return stderr.split('WORKER_REFUSED:',1)[1].splitlines()[0].strip()
def _spawn_escapee(run_dir,name='escapee.pid'):
    # Grandchild that leaves the worker session/group and ignores SIGTERM: only
    # subreaper-based descendant cleanup can reach it.
    script=("import os,signal,time,sys\nos.setsid()\n"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            "open(sys.argv[1],'w').write(str(os.getpid()))\n"
            "time.sleep(120)\n")
    path=run_dir/name
    subprocess.Popen([sys.executable,'-B','-c',script,str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(300):
        if path.exists() and path.read_text().strip():break
        time.sleep(.01)
    assert path.exists() and path.read_text().strip()
    return int(path.read_text().strip())


DRIVER_TEXT=('import hashlib,importlib.util,json,os,sys,time\n'
 'from pathlib import Path\n'
 'run_path,campaign,manifest,sha=sys.argv[1:5]\n'
 'kwargs={}\n'
 "if len(sys.argv)>5:kwargs={'cutoff_s':float(sys.argv[5]),'total_s':float(sys.argv[6])}\n"
 "spec=importlib.util.spec_from_file_location('t2_run_fixture',run_path)\n"
 'module=importlib.util.module_from_spec(spec);sys.modules["t2_run_fixture"]=module;spec.loader.exec_module(module)\n'
 'def executor(root,m,context):\n'
 "    if os.environ.get('T2A_TEST_EXECUTOR')=='sleep':\n"
 '        time.sleep(600)\n'
 '    body={"verify_ran":True,"groups":sorted(m.get("checkpoints",{})),"venv_ok":m.get("venv")==sys.prefix,\n'
 '          "heavy_imports":sorted(name for name in ("numpy","torch") if name in sys.modules),\n'
 '          "context_type":type(context).__name__,"is_child":os.getpid()!=context.supervisor_pid,\n'
 '          "manifest_sha256_matches":hashlib.sha256(Path(context.manifest_path).read_bytes()).hexdigest()==context.manifest_sha256,\n'
 '          "supervisor_pid":context.supervisor_pid}\n'
 '    Path(root,"synthetic-executor.json").write_text(json.dumps(body))\n'
 'module.main([campaign,manifest,sha,"--execute-owner-approved"],executor=executor,**kwargs)\n')


@pytest.fixture(scope='module')
def canonical_fixture(tmp_path_factory):
    tmp=tmp_path_factory.mktemp('canonical')
    fix=tmp/'fixture';sub=fix/'experiments/rl/g1_ppo_t2a_frozen_comparison_001'
    sub.mkdir(parents=True)
    for source in (RUN,SUP,COMPARISON,PROTOCOL):
        shutil.copyfile(source,sub/source.name)
    (fix/'src/g1swarm').mkdir(parents=True)
    (fix/'src/g1swarm/__init__.py').write_text('')
    git=['git','-c','user.email=t2a@fixture','-c','user.name=t2a-fixture','-c','commit.gpgsign=false']
    subprocess.run([*git[:1],'init','-q'],cwd=fix,check=True)
    subprocess.run([*git,'add','-A'],cwd=fix,check=True)
    subprocess.run([*git,'commit','-q','-m','fixture'],cwd=fix,check=True)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=fix,text=True).strip()
    installed={}
    for candidate in ('pyvenv.cfg','bin/pip','bin/pytest','bin/python'):
        path=Path(sys.prefix)/candidate
        if path.exists():installed[candidate]=_sha(path)
        if len(installed)>=2:break
    assert installed
    protocol=json.loads(PROTOCOL.read_text())
    readiness={'schema':'g1-t1-freeze-v1','experiment_id':'g1_ppo_t2a_frozen_comparison_001','execution_head':head,
        'venv':str(Path(sys.prefix).resolve()),'python_executable_sha256':_sha(Path(sys.executable).resolve()),
        'files':{'experiments/rl/g1_ppo_t2a_frozen_comparison_001/'+source.name:_sha(sub/source.name) for source in (RUN,SUP,COMPARISON,PROTOCOL)},
        'installed_files':installed,'dependencies':{'pytest':importlib.metadata.version('pytest')},
        'checkpoints':{group:{'path':str(path),'sha256':protocol['checkpoints'][group]['sha256']} for group,path in CHECKPOINTS.items()},
        'protocol_sha256':_sha(PROTOCOL)}
    readiness_path=tmp/'readiness.json';readiness_path.write_text(json.dumps(readiness))
    driver=tmp/'executor-driver.py';driver.write_text(DRIVER_TEXT)
    return {'tmp':tmp,'fix':fix,'sub':sub,'readiness':readiness_path,'sha':_sha(readiness_path),'head':head,'driver':driver}


def _fixture_env(fixture,poison):
    env=_sanitized_env(poison,fixture['fix']/'src')
    return env


def _run_fixture(fixture,env,campaign,cutoff=None,timeout=180):
    args=[sys.executable,'-B',str(fixture['driver']),str(fixture['sub']/'run.py'),str(campaign),str(fixture['readiness']),fixture['sha']]
    if cutoff is not None:args+=[str(cutoff[0]),str(cutoff[1])]
    return subprocess.run(args,capture_output=True,text=True,env=env,cwd=fixture['fix'],timeout=timeout)


def test_forked_worker_positive_guard_and_lifecycle(tmp_path):
    def body(context,run_dir,manifest):
        marker={'pid':os.getpid(),'ppid':os.getppid(),'supervisor':context.supervisor_pid,
                'session_leader':os.getsid(0)==os.getpid(),
                'manifest_sha_matches':hashlib.sha256(Path(context.manifest_path).read_bytes()).hexdigest()==context.manifest_sha256,
                'run_inputs':dict(context.run_inputs)}
        document=sup.require_launch_context(context,**_guard_args(run_dir,manifest))
        marker['document_run_id']=document['run_id']
        (run_dir/'worker-marker.json').write_text(json.dumps(marker))
        return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'positive',body)
    assert result['native_exitcode']==0 and result['interrupted'] is None and result['failure_phase'] is None
    assert result['cleanup_complete'] is True and result['cleanup_detail'] is None and result['receipt_error'] is None
    assert result['cleanup_allowance_s']==sup.CLEANUP_ALLOWANCE_S==5.0 and result['limit_s']==30
    marker=json.loads((run_dir/'worker-marker.json').read_text())
    assert marker['pid']!=os.getpid() and marker['ppid']==os.getpid() and marker['supervisor']==os.getpid()
    assert marker['session_leader'] is True and marker['manifest_sha_matches'] is True
    assert marker['run_inputs']=={'case':'positive'} and marker['document_run_id']==str(run_dir.resolve())
    assert _dead(result['pid'])
    assert (run_dir/sup.MANIFEST_NAME).exists() and (run_dir/sup.LOCK_NAME).exists()
    assert (run_dir/sup.STDOUT_NAME).exists() and (run_dir/sup.STDERR_NAME).exists()
    receipt=json.loads((run_dir/sup.RECEIPT_NAME).read_text())
    assert receipt==result and receipt['manifest_sha256']==_sha(run_dir/sup.MANIFEST_NAME)
    assert receipt['supervisor_pid']==os.getpid()


def test_inherited_context_required_and_construction_forbidden(tmp_path):
    with pytest.raises(sup.LaunchRefused,match='launch_context_construction_forbidden'):
        sup.LauncherContext(run_id='r',manifest_path='m',manifest_sha256='h',readiness_sha256='R0',
                            execution_head='H0',protocol_sha256='P0',supervisor_pid=1,supervisor_start_ticks=1,
                            started_unix=1.,deadline_monotonic=None,run_inputs={},seal=object())
    assert sup.is_genuine_context(None) is False and sup.is_genuine_context('x') is False
    def body(context,run_dir,manifest):
        sup.require_launch_context(None,**_guard_args(run_dir,manifest));return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'no-context',body)
    assert result['native_exitcode']==76 and _refusal_of(run_dir)=='inherited_launch_context_required'
    assert (run_dir/sup.MANIFEST_NAME).exists()


def test_manifest_byte_change_is_refused(tmp_path):
    def body(context,run_dir,manifest):
        os.chmod(context.manifest_path,0o600)
        Path(context.manifest_path).write_bytes(b'{"tampered":true}')
        sup.require_launch_context(context,**_guard_args(run_dir,manifest));return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'byte-tamper',body)
    assert result['native_exitcode']==76 and _refusal_of(run_dir)=='manifest_bytes_changed'


@pytest.mark.parametrize('field,reason',[('run_id','manifest_run_identity_mismatch'),
    ('execution_head','manifest_execution_head_mismatch'),('protocol_sha256','manifest_protocol_mismatch'),
    ('readiness_sha256','manifest_readiness_mismatch'),('supervisor_pid','manifest_supervisor_mismatch'),
    ('run_inputs','manifest_run_inputs_mismatch')])
def test_manifest_field_mismatch_is_refused(tmp_path,field,reason):
    def body(context,run_dir,manifest):
        document=json.loads(Path(context.manifest_path).read_text())
        if field=='run_inputs':document[field]={'tampered':True}
        elif isinstance(document.get(field),int):document[field]=document[field]+1
        else:document[field]='tampered'
        raw=json.dumps(document,sort_keys=True,separators=(',',':')).encode()
        os.chmod(context.manifest_path,0o600)
        Path(context.manifest_path).write_bytes(raw)
        context.manifest_sha256=hashlib.sha256(raw).hexdigest()
        sup.require_launch_context(context,**_guard_args(run_dir,manifest));return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'field-'+field,body)
    assert result['native_exitcode']==76 and _refusal_of(run_dir)==reason


@pytest.mark.parametrize('case,reason',[('run_identity','run_identity_binding_mismatch'),('manifest','manifest_binding_mismatch')])
def test_run_identity_and_manifest_binding_are_refused(tmp_path,case,reason):
    def body(context,run_dir,manifest):
        kwargs=_guard_args(run_dir,manifest);kwargs[case]=tmp_path/('other-'+case)
        sup.require_launch_context(context,**kwargs);return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'bind-'+case,body)
    assert result['native_exitcode']==76 and _refusal_of(run_dir)==reason


@pytest.mark.parametrize('field,reason',[('readiness_sha256','readiness_binding_mismatch'),
    ('execution_head','execution_head_binding_mismatch'),('protocol_sha256','protocol_binding_mismatch')])
def test_argument_binding_drift_is_refused(tmp_path,field,reason):
    def body(context,run_dir,manifest):
        kwargs=_guard_args(run_dir,manifest);kwargs[field]='drift'
        sup.require_launch_context(context,**kwargs);return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'arg-'+field,body)
    assert result['native_exitcode']==76 and _refusal_of(run_dir)==reason


def test_expired_or_forged_parent_context_is_refused(tmp_path):
    def expired(context,run_dir,manifest):
        context.deadline_monotonic=time.monotonic()-1.
        sup.require_launch_context(context,**_guard_args(run_dir,manifest));return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'expired',expired)
    assert result['native_exitcode']==76 and _refusal_of(run_dir)=='launch_context_expired'
    def forged_parent(context,run_dir,manifest):
        context.supervisor_pid=1234567
        sup.require_launch_context(context,**_guard_args(run_dir,manifest));return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'forged-parent',forged_parent)
    assert result['native_exitcode']==76 and _refusal_of(run_dir)=='supervisor_parent_mismatch'
    def forged_lifetime(context,run_dir,manifest):
        context.supervisor_start_ticks=1
        sup.require_launch_context(context,**_guard_args(run_dir,manifest));return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'forged-lifetime',forged_lifetime)
    assert result['native_exitcode']==76 and _refusal_of(run_dir)=='supervisor_lifetime_changed'


def test_grandchild_of_worker_cannot_qualify(tmp_path):
    def body(context,run_dir,manifest):
        pid=os.fork()
        if pid==0:
            try:
                sup.require_launch_context(context,**_guard_args(run_dir,manifest))
                print('GRANDCHILD_ACCEPTED')
            except sup.LaunchRefused as exc:
                print('GRANDCHILD_REFUSED:'+str(exc))
            os._exit(0)
        os.waitpid(pid,0)
        return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'grandchild',body)
    assert result['native_exitcode']==0
    stdout=(run_dir/sup.STDOUT_NAME).read_text()
    assert 'GRANDCHILD_REFUSED:worker_identity_mismatch' in stdout and 'GRANDCHILD_ACCEPTED' not in stdout


def test_direct_worker_flags_refused_before_heavy_imports(tmp_path):
    for index,flag in enumerate(('--worker-owner-approved','--supervisor-fd','--worker')):
        case=tmp_path/f'flag-{index}';case.mkdir()
        poison,marker=_poison_dir(case)
        args=[sys.executable,'-B',str(RUN),str(case/'run'),str(case/'m.json'),'0'*64,flag]
        if flag=='--supervisor-fd':args.append('0')
        p=subprocess.run(args,capture_output=True,text=True,env=_sanitized_env(poison),timeout=30)
        assert p.returncode==76 and 'WORKER_REFUSED:external_worker_entry_removed' in p.stderr
        assert not marker.exists() and not (case/'run').exists()


def test_direct_execute_refusal_before_heavy_imports(tmp_path):
    poison,marker=_poison_dir(tmp_path)
    script=("import importlib.util,sys\n"
            "spec=importlib.util.spec_from_file_location('t2_run',sys.argv[1])\n"
            "run=importlib.util.module_from_spec(spec);spec.loader.exec_module(run)\n"
            "try:run.execute(sys.argv[2],sys.argv[3],'0'*64)\n"
            "except Exception as exc:print('EXECUTE_REFUSED:'+type(exc).__name__+':'+str(exc));sys.exit(0)\n"
            "sys.exit(9)\n")
    p=subprocess.run([sys.executable,'-B','-c',script,str(RUN),str(tmp_path/'run'),str(tmp_path/'m.json')],
                     capture_output=True,text=True,env=_sanitized_env(poison),timeout=30)
    assert p.returncode==0 and 'EXECUTE_REFUSED:LaunchRefused:inherited_launch_context_required' in p.stdout,p.stdout+p.stderr
    assert not marker.exists() and not (tmp_path/'run').exists()


def test_operator_flag_required_without_side_effects(tmp_path):
    poison,marker=_poison_dir(tmp_path)
    p=subprocess.run([sys.executable,'-B',str(RUN),str(tmp_path/'run'),str(tmp_path/'m.json'),'0'*64],
                     capture_output=True,text=True,env=_sanitized_env(poison),timeout=30)
    assert p.returncode!=0 and 'OWNER_CONFIRMATION_REQUIRED_BEFORE_PHYSICS' in p.stderr
    assert not (tmp_path/'run').exists() and not marker.exists()


def test_preflight_failure_and_timeout_leave_no_side_effects(tmp_path):
    root=tmp_path/'campaign'
    def failing(path,expected):raise RuntimeError('wrong_execution_head')
    with pytest.raises(RuntimeError,match='wrong_execution_head'):
        run.main([str(root),str(tmp_path/'m.json'),'R0','--execute-owner-approved'],verifier=failing)
    assert not root.exists()
    def stalling(path,expected):
        time.sleep(5.);return {'execution_head':'H0','protocol_sha256':'P0'}
    started=time.monotonic()
    with pytest.raises(RuntimeError,match='supervisor_cutoff_exhausted'):
        run.main([str(root),str(tmp_path/'m.json'),'R0','--execute-owner-approved'],verifier=stalling,
                 cutoff_s=.4,total_s=5.4)
    assert time.monotonic()-started<3. and not root.exists()


def test_real_readiness_preflight_blocks_before_side_effects(tmp_path):
    root=tmp_path/'campaign';manifest=tmp_path/'m.json'
    manifest.write_text('{}')
    with pytest.raises(RuntimeError,match='readiness_mismatch'):
        run.main([str(root),str(manifest),'0'*64,'--execute-owner-approved'])
    manifest.write_text(json.dumps({'execution_head':'0'*40}))
    with pytest.raises(RuntimeError,match='wrong_execution_head'):
        run.main([str(root),str(manifest),_sha(manifest),'--execute-owner-approved'])
    assert not root.exists()


def test_setup_deadline_exhausted_before_directory_creation(tmp_path):
    def body(context,run_dir,manifest):return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'setup-timeout',body,deadline_delta=-0.001,total_delta=5.)
    assert result['interrupted']=='wall_clock_watchdog' and result['interrupted_phase']=='setup'
    assert result['pid'] is None and result['cleanup_complete'] is True
    assert not run_dir.exists() and result['receipt_error']=='run_directory_unavailable'


def test_worker_timeout_is_killed_reaped_and_receipted(tmp_path):
    def body(context,run_dir,manifest):
        time.sleep(30.);return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'timeout',body,deadline_delta=0.8,total_delta=5.8)
    assert result['interrupted']=='wall_clock_watchdog' and result['interrupted_phase']=='supervise'
    assert result['cleanup_complete'] is True and result['receipt_error'] is None
    assert result['native_exitcode']==-signal.SIGTERM and _dead(result['pid'])
    receipt=json.loads((run_dir/sup.RECEIPT_NAME).read_text())
    assert receipt['interrupted']=='wall_clock_watchdog' and receipt['cleanup_complete'] is True


def test_worker_crash_cleanup_and_receipt(tmp_path):
    def body(context,run_dir,manifest):
        raise RuntimeError('synthetic_crash_boom')
    result,run_dir,manifest=_run_supervised(tmp_path,'crash',body)
    assert result['native_exitcode']==1 and result['cleanup_complete'] is True
    assert result['interrupted'] is None and result['failure_phase'] is None and result['receipt_error'] is None
    stderr=(run_dir/sup.STDERR_NAME).read_text()
    assert 'synthetic_crash_boom' in stderr and 'RuntimeError' in stderr
    assert (run_dir/sup.RECEIPT_NAME).exists()


def test_crash_cleanup_kills_group_descendants(tmp_path):
    def body(context,run_dir,manifest):
        child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(60)'],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        (run_dir/'grandchild.pid').write_text(str(child.pid))
        raise RuntimeError('crash_with_descendant')
    result,run_dir,manifest=_run_supervised(tmp_path,'crash-desc',body)
    pid=int((run_dir/'grandchild.pid').read_text())
    assert result['native_exitcode']==1 and result['cleanup_complete'] is True
    assert _dead(pid)


def test_timeout_cleanup_kills_session_escaped_grandchild(tmp_path):
    def body(context,run_dir,manifest):
        _spawn_escapee(run_dir)
        time.sleep(30.);return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'timeout-escape',body,deadline_delta=1.2,total_delta=6.2)
    pid=int((run_dir/'escapee.pid').read_text())
    assert result['interrupted']=='wall_clock_watchdog'
    assert result['cleanup_complete'] is True,result['cleanup_detail']
    assert _dead(pid)


def test_cleanup_failure_is_receipted_honestly(tmp_path):
    def body(context,run_dir,manifest):
        _spawn_escapee(run_dir)
        return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'noop-terminator',body,terminator=lambda owned_pid,signum:None)
    pid=int((run_dir/'escapee.pid').read_text())
    try:
        assert result['native_exitcode']==0
        assert result['cleanup_complete'] is False and result['cleanup_detail']=='descendants_persist'
        receipt=json.loads((run_dir/sup.RECEIPT_NAME).read_text())
        assert receipt['cleanup_complete'] is False and receipt['cleanup_detail']=='descendants_persist'
        lifecycle_ok=(result['native_exitcode']==0 and result['interrupted'] is None
                      and result['failure_phase'] is None and result['cleanup_complete'])
        assert lifecycle_ok is False  # supervisor main must exit nonzero
    finally:
        try:os.kill(pid,signal.SIGKILL)
        except OSError:pass
        for _ in range(100):
            sup._reap_children()
            if _dead(pid,tries=1):break
            time.sleep(.05)
        assert _dead(pid)


def test_signal_during_supervise_enters_cleanup(tmp_path):
    for signum in (signal.SIGTERM,signal.SIGINT):
        def body(context,run_dir,manifest):
            os.kill(context.supervisor_pid,signum)
            time.sleep(30.);return 0
        result,run_dir,manifest=_run_supervised(tmp_path,'signal-'+signal.Signals(signum).name,body)
        assert result['interrupted']=='signal:'+signal.Signals(signum).name
        assert result['cleanup_complete'] is True and result['receipt_error'] is None
        assert _dead(result['pid'])
        assert (run_dir/sup.RECEIPT_NAME).exists()
        assert json.loads((run_dir/sup.RECEIPT_NAME).read_text())['signal']==signum


def test_replay_of_existing_run_directory_is_refused(tmp_path):
    def body(context,run_dir,manifest):return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'replay',body)
    manifest_before=(run_dir/sup.MANIFEST_NAME).read_bytes()
    receipt_before=(run_dir/sup.RECEIPT_NAME).read_bytes()
    with pytest.raises(sup.LaunchRefused,match='run_replay_refused'):
        sup.supervise(lambda context:0,run_dir,30,run_identity=run_dir,manifest=manifest,
                      readiness_sha256='R0',execution_head='H0',protocol_sha256='P0')
    assert (run_dir/sup.MANIFEST_NAME).read_bytes()==manifest_before
    assert (run_dir/sup.RECEIPT_NAME).read_bytes()==receipt_before
    manual=tmp_path/'manual';manual.mkdir()
    with pytest.raises(sup.LaunchRefused,match='run_replay_refused'):
        sup.supervise(lambda context:0,manual,30,run_identity=manual,manifest=tmp_path/'m.json',
                      readiness_sha256='R0',execution_head='H0',protocol_sha256='P0')
    assert list(manual.iterdir())==[]


def test_execution_manifest_is_immutable_and_unique(tmp_path):
    def body(context,run_dir,manifest):return 0
    result,run_dir,manifest=_run_supervised(tmp_path,'manifest-a',body)
    result_b,run_dir_b,manifest_b=_run_supervised(tmp_path,'manifest-b',body)
    document=json.loads((run_dir/sup.MANIFEST_NAME).read_text())
    assert document['schema']=='g1-t2a-execution-manifest-v1'
    assert document['run_id']==str(run_dir.resolve()) and document['execution_head']=='H0'
    assert document['protocol_sha256']=='P0' and document['readiness_sha256']=='R0'
    assert isinstance(document['started_unix'],float) and document['run_inputs']=={'case':'manifest-a'}
    assert document['supervisor_pid']==os.getpid() and isinstance(document['supervisor_start_ticks'],int)
    document_b=json.loads((run_dir_b/sup.MANIFEST_NAME).read_text())
    assert document_b['run_id']==str(run_dir_b.resolve()) and document_b['run_id']!=document['run_id']
    assert _sha(run_dir/sup.MANIFEST_NAME)==result['manifest_sha256']
    assert (run_dir/sup.MANIFEST_NAME).stat().st_mode & 0o777==0o444
    with pytest.raises(PermissionError):
        (run_dir/sup.MANIFEST_NAME).write_text('tampered')
    assert json.loads((run_dir/sup.MANIFEST_NAME).read_text())==document


def test_frozen_scope_constants_and_untouched_science():
    assert run.SUPERVISOR_CUTOFF_S==595. and run.SUPERVISOR_TOTAL_S==600.
    assert sup.CLEANUP_ALLOWANCE_S==5. and sup.GROUP_GRACE_S==.25 and sup.GROUP_KILL_WAIT_S==2.
    protocol=json.loads(PROTOCOL.read_text())
    assert protocol['groups']==['B0','C0','C256'] and protocol['optimizer_updates_allowed']==0
    assert protocol['authorization_status']=='OWNER_CONFIRMATION_PENDING'
    assert protocol['baseline_head']=='7e86481a972146614863bd4b6c4fd4b9d8347241'
    assert protocol['checkpoints']['C256']['sha256']=='cc383df4f9508d9db97f12043f483e4b8e7ae5ee7bf0d1de015197384ef486d2'
    assert protocol['budgets']=={'total_native_steps':36000,'per_group_native_steps':12000,'wall_s':600,
                                 'supervisor_cutoff_s':595,'attempts_per_group':1}
    prefix='experiments/rl/g1_ppo_t2a_frozen_comparison_001/'
    for name in ('protocol.json','comparison.py','PROTOCOL.md'):
        assert subprocess.run(['git','diff','--quiet','HEAD','--',prefix+name],cwd=ROOT).returncode==0,name
    lines=[line[3:] for line in subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],
                                                        cwd=ROOT,text=True).splitlines() if line.strip()]
    assert set(lines)<=ALLOWED_MODIFIED  # also valid on the clean frozen execution commit
    for group,path in CHECKPOINTS.items():
        assert _sha(path)==protocol['checkpoints'][group]['sha256']


def test_canonical_fixture_positive_main_fork_worker_real_verify(canonical_fixture):
    fixture=canonical_fixture
    for source in (RUN,SUP,COMPARISON,PROTOCOL):
        assert _sha(source)==_sha(fixture['sub']/source.name)
    poison,marker=_poison_dir(fixture['tmp'])
    campaign=fixture['tmp']/'campaign-positive'
    env=_fixture_env(fixture,poison);env['T2A_TEST_EXECUTOR']='mark'
    p=_run_fixture(fixture,env,campaign)
    assert p.returncode==0,p.stdout+p.stderr
    assert not marker.exists() and 'Traceback' not in p.stderr
    assert (campaign/sup.STDERR_NAME).read_text()==''
    body=json.loads((campaign/'synthetic-executor.json').read_text())
    assert body['verify_ran'] is True and body['groups']==['C0','C256'] and body['venv_ok'] is True
    assert body['heavy_imports']==[] and body['context_type']=='LauncherContext'
    assert body['is_child'] is True and body['manifest_sha256_matches'] is True
    receipt=json.loads((campaign/sup.RECEIPT_NAME).read_text())
    assert receipt['native_exitcode']==0 and receipt['interrupted'] is None and receipt['cleanup_complete'] is True
    document=json.loads((campaign/sup.MANIFEST_NAME).read_text())
    assert document['execution_head']==fixture['head'] and document['readiness_sha256']==fixture['sha']
    assert document['run_id']==str(campaign.resolve())
    assert receipt['manifest_sha256']==_sha(campaign/sup.MANIFEST_NAME)
    assert receipt['deadline_from_entry_s']==pytest.approx(595.) and receipt['cleanup_allowance_s']==pytest.approx(5.)


def test_canonical_fixture_replay_refused_end_to_end(canonical_fixture):
    fixture=canonical_fixture
    poison,marker=_poison_dir(fixture['tmp'])
    campaign=fixture['tmp']/'campaign-replay'
    env=_fixture_env(fixture,poison);env['T2A_TEST_EXECUTOR']='mark'
    first=_run_fixture(fixture,env,campaign)
    assert first.returncode==0,first.stdout+first.stderr
    manifest_before=_sha(campaign/sup.MANIFEST_NAME)
    receipt_before=(campaign/sup.RECEIPT_NAME).read_bytes()
    listing_before=sorted(p.name for p in campaign.iterdir())
    second=_run_fixture(fixture,env,campaign)
    assert second.returncode==76 and 'SUPERVISOR_REFUSED:run_replay_refused' in second.stderr
    assert _sha(campaign/sup.MANIFEST_NAME)==manifest_before
    assert (campaign/sup.RECEIPT_NAME).read_bytes()==receipt_before
    assert sorted(p.name for p in campaign.iterdir())==listing_before


def test_canonical_fixture_worker_timeout_end_to_end(canonical_fixture):
    fixture=canonical_fixture
    poison,marker=_poison_dir(fixture['tmp'])
    campaign=fixture['tmp']/'campaign-timeout'
    env=_fixture_env(fixture,poison);env['T2A_TEST_EXECUTOR']='sleep'
    p=_run_fixture(fixture,env,campaign,cutoff=(3.0,8.0))
    assert p.returncode==1,p.stdout+p.stderr
    assert not marker.exists()
    receipt=json.loads((campaign/sup.RECEIPT_NAME).read_text())
    assert receipt['interrupted']=='wall_clock_watchdog' and receipt['interrupted_phase']=='supervise'
    assert receipt['native_exitcode']==-signal.SIGTERM and receipt['cleanup_complete'] is True
    assert receipt['deadline_from_entry_s']==pytest.approx(3.0) and receipt['cleanup_allowance_s']==pytest.approx(5.0)
    assert not (campaign/'synthetic-executor.json').exists()


def test_input_readiness_is_never_replaced(tmp_path):
    result,run_dir,manifest=_run_supervised(tmp_path,'input-preserved',lambda *args:0)
    assert manifest.read_bytes()==b'{"fixture":true}'
    assert manifest.resolve()!=(run_dir/sup.MANIFEST_NAME).resolve()
    assert result['cleanup_complete']


def test_preexisting_child_is_refused_and_untouched(tmp_path):
    child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'])
    try:
        with pytest.raises(sup.LaunchRefused,match='dedicated_supervisor_required'):
            _run_supervised(tmp_path,'shared-host',lambda *args:0)
        assert child.poll() is None
        assert not (tmp_path/'shared-host').exists()
    finally:
        child.terminate();child.wait(timeout=5)


def test_subreaper_failure_refuses_before_spawn(tmp_path,monkeypatch):
    def fail():raise OSError('subreaper_setup_failed')
    monkeypatch.setattr(sup,'_set_child_subreaper',fail)
    with pytest.raises(OSError,match='subreaper_setup_failed'):
        _run_supervised(tmp_path,'no-subreaper',lambda *args:0)
    assert not (tmp_path/'no-subreaper').exists()


def test_stalled_cleanup_is_bounded_and_failure_retained(tmp_path):
    def body(context,run_dir,manifest):time.sleep(30)
    def stall(*args):time.sleep(30)
    started=time.monotonic()
    result,run_dir,_=_run_supervised(tmp_path,'stalled-cleanup',body,
        deadline_delta=.2,total_delta=1.7,terminator=stall)
    assert time.monotonic()-started<2.2
    assert result['cleanup_complete'] is False
    assert 'DeadlineInterrupt' in result['cleanup_detail']
    assert _dead(result['pid'])
    receipt=json.loads((run_dir/sup.RECEIPT_NAME).read_text())
    assert receipt['cleanup_complete'] is False and receipt['interrupted']=='wall_clock_watchdog'


def test_stalled_receipt_cannot_report_success(tmp_path,monkeypatch,capsys):
    original=Path.write_text
    def stall(path,*args,**kwargs):
        if path.name==sup.RECEIPT_NAME:time.sleep(30)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'write_text',stall)
    started=time.monotonic()
    result,run_dir,_=_run_supervised(tmp_path,'receipt-stall',lambda *args:0,
        deadline_delta=.2,total_delta=1.5)
    assert time.monotonic()-started<2.
    assert 'DeadlineInterrupt' in result['receipt_error']
    assert _dead(result['pid'])
    assert 'T2A_RECEIPT_WRITE_FAILED' in capsys.readouterr().err
    assert not (run_dir/sup.RECEIPT_NAME).exists()


@pytest.mark.parametrize('mode',['raise','stall'])
def test_outer_cleanup_exception_still_reaps_and_records(tmp_path,monkeypatch,mode):
    def broken(*args):
        if mode=='stall':time.sleep(30)
        raise RuntimeError('outer_cleanup_fault')
    monkeypatch.setattr(sup,'_cleanup_lifecycle',broken)
    previous={signum:signal.getsignal(signum) for signum in (signal.SIGTERM,signal.SIGINT)}
    result,run_dir,_=_run_supervised(tmp_path,'outer-'+mode,lambda *args:time.sleep(30),
        deadline_delta=.2,total_delta=1.7)
    assert result['cleanup_complete'] is False and _dead(result['pid'])
    assert ('DeadlineInterrupt' if mode=='stall' else 'outer_cleanup_fault') in result['cleanup_detail']
    assert json.loads((run_dir/sup.RECEIPT_NAME).read_text())['cleanup_complete'] is False
    assert all(signal.getsignal(s)==h for s,h in previous.items())
