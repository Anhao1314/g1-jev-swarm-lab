"""Nonphysical T2a supervisor-delegation checks: synthetic Linux processes only.

No physics, policy load, checkpoint, prediction or real backend import. The real Worker
boundary is proven with actual subprocess forgery attempts against run.py (custom
pipe/stdin launchers with true kernel facts are refused, and code execution is refused
before NumPy/Torch/backend imports). The positive supervision path is exercised through
genuine supervise() with a synthetic entry anchor (a test-only seam), which is a
mechanism check, not a claim about the physical Worker boundary.
"""
import hashlib,importlib.util,json,os,subprocess,sys,textwrap,time
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'experiments/rl/g1_ppo_t2a_frozen_comparison_001'
RUN=HERE/'run.py'
SUP=HERE/'supervision.py'
_spec=importlib.util.spec_from_file_location('t2_supervision',SUP);sup=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(sup)
_rspec=importlib.util.spec_from_file_location('t2_run_under_test',RUN);run=importlib.util.module_from_spec(_rspec);_rspec.loader.exec_module(run)
ANCHOR=sup.proc_argv(os.getpid())


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _head():return subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()


PRELUDE=("import importlib.util,sys,os,subprocess,time,json\n"
         "spec=importlib.util.spec_from_file_location('sup',"+repr(str(SUP))+")\n"
         "sup=importlib.util.module_from_spec(spec);spec.loader.exec_module(sup)\n"
         "fd=int(sys.argv[sys.argv.index('--supervisor-fd')+1])\n"
         "def _body():\n")
TAIL=("try:\n    _body()\nexcept sup.DelegationRefused as exc:\n"
      "    print('WORKER_REFUSED:'+str(exc),file=sys.stderr)\n    raise SystemExit(76)\n")


def _trust_expr(script):
    return f"sup.entry_trust({str(script)!r},sys.argv,expected_parent_argv={ANCHOR!r})"
def _consume_expr(script,head,proto):
    return f"d=sup.consume_delegation(fd,{_trust_expr(script)},execution_head={head!r},protocol_sha256={proto!r})\n"
def _write_worker(tmp_path,name,make_body,root,manifest,sha):
    script=tmp_path/name
    script.write_text(PRELUDE+textwrap.indent(make_body(str(script)),'    ')+TAIL)
    return [sys.executable,str(script),str(root),str(manifest),sha,'--worker-owner-approved']
def _positive_body(script):
    return _consume_expr(script,'H0','P0')+"print('SYNTHETIC_WORKER_OK')\n"
def _dead(pid,tries=400):
    for _ in range(tries):
        try:os.kill(pid,0)
        except OSError:return True
        time.sleep(.05)
    return False
def _poison_dir(tmp_path,modules=('numpy','torch')):
    poison=tmp_path/'poison';poison.mkdir(exist_ok=True);marker=tmp_path/'forbidden-import'
    for module in modules:
        (poison/f'{module}.py').write_text("import pathlib\npathlib.Path(%r).write_text('imported')\nraise ImportError('poisoned %s')\n"%(str(marker),module))
    return poison,marker
def _poisoned_env(tmp_path):
    poison,marker=_poison_dir(tmp_path)
    return {**os.environ,'PYTHONPATH':str(poison)+os.pathsep+str(ROOT/'src')},marker
def _pipe(payload):
    read_fd,write_fd=os.pipe();os.write(write_fd,json.dumps(payload).encode());os.close(write_fd);return read_fd


def test_genuine_supervised_synthetic_worker_positive(tmp_path):
    root=tmp_path/'run';manifest=tmp_path/'m.json'
    argv=_write_worker(tmp_path,'positive.py',_positive_body,root,manifest,'R0')
    result=sup.supervise(argv,root,30,run_identity=root,readiness_sha256='R0',execution_head='H0',protocol_sha256='P0',manifest=str(manifest))
    assert result['native_exitcode']==0 and result['interrupted'] is None and result['failure_phase'] is None
    assert 'SYNTHETIC_WORKER_OK' in (root/'worker.stdout.raw').read_text()
    assert result['delegation_consumed'] is True
    assert not (root/sup.TOKEN_NAME).exists() and (root/(sup.TOKEN_NAME+sup.CONSUMED_SUFFIX)).exists()


def test_supervisor_main_reaches_worker_only_after_preflight(tmp_path):
    root=tmp_path/'campaign';manifest=tmp_path/'manifest.json';manifest.write_text('{}')
    seen=[]
    def verifier(path,expected):seen.append((str(path),expected));return {'execution_head':'H0','protocol_sha256':'P0'}
    worker_argv=_write_worker(tmp_path,'positive.py',_positive_body,root,manifest,'R0')
    with pytest.raises(SystemExit) as info:
        run.main([str(root),str(manifest),'R0','--execute-owner-approved'],verifier=verifier,worker_argv=worker_argv)
    assert info.value.code==0
    assert seen==[(str(manifest),'R0')] and (root/'once.claim').exists()
    assert (root/(sup.TOKEN_NAME+sup.CONSUMED_SUFFIX)).exists() and 'SYNTHETIC_WORKER_OK' in (root/'worker.stdout.raw').read_text()
    receipt=json.loads((root/'process-receipt.json').read_text())
    assert 594.0<receipt['limit_s']<=595.0


def test_preflight_failure_creates_no_run_side_effects(tmp_path):
    root=tmp_path/'campaign'
    def verifier(path,expected):raise RuntimeError('wrong_execution_head')
    with pytest.raises(RuntimeError,match='wrong_execution_head'):
        run.main([str(root),str(tmp_path/'m.json'),'R0','--execute-owner-approved'],verifier=verifier,
                 worker_argv=[sys.executable,'-c','raise SystemExit(0)'])
    assert not root.exists()


@pytest.mark.parametrize('case',['readiness','head'])
def test_real_readiness_preflight_blocks_before_side_effects(tmp_path,case):
    root=tmp_path/'campaign';manifest=tmp_path/'manifest.json'
    if case=='readiness':
        manifest.write_text('{}');expected='0'*64;reason='readiness_mismatch'
    else:
        manifest.write_text(json.dumps({'execution_head':'0'*40}));expected=_sha(manifest);reason='wrong_execution_head'
    with pytest.raises(RuntimeError,match=reason):
        run.main([str(root),str(manifest),expected,'--execute-owner-approved'])
    assert not root.exists()


def test_real_source_preflight_blocks_before_side_effects(tmp_path):
    # The live worktree carries uncommitted implementation changes, so a manifest that
    # matches the real HEAD must still be refused at the source-integrity gate.
    root=tmp_path/'campaign';manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'execution_head':_head()}))
    with pytest.raises((RuntimeError,KeyError)):
        run.main([str(root),str(manifest),_sha(manifest),'--execute-owner-approved'])
    assert not root.exists()


def test_direct_worker_rejected_before_backend_imports(tmp_path):
    env,marker=_poisoned_env(tmp_path)
    p=subprocess.run([sys.executable,'-B',str(RUN),str(tmp_path/'run'),str(tmp_path/'m.json'),'0'*64,'--worker-owner-approved'],
                     capture_output=True,text=True,env=env,timeout=30)
    assert p.returncode==76 and 'WORKER_REFUSED:supervisor_delegation_required' in p.stderr
    assert not marker.exists() and not (tmp_path/'run').exists()


def test_argv_env_or_empty_context_alone_never_qualifies(tmp_path):
    root=tmp_path/'run'
    env={**os.environ,'G1_T2A_SUPERVISOR_DELEGATION':json.dumps({'protocol':sup.VERSION}),'PYTHONPATH':str(ROOT/'src')}
    p=subprocess.run([sys.executable,'-B',str(RUN),str(root),str(tmp_path/'m.json'),'0'*64,'--worker-owner-approved'],
                     capture_output=True,text=True,env=env,timeout=30)
    assert p.returncode==76 and 'supervisor_delegation_required' in p.stderr and not root.exists()
    read_fd,write_fd=os.pipe();os.close(write_fd)
    try:
        p=subprocess.run([sys.executable,'-B',str(RUN),str(root),str(tmp_path/'m.json'),'0'*64,'--worker-owner-approved',
                          '--supervisor-fd',str(read_fd)],capture_output=True,text=True,env=env,pass_fds=(read_fd,),timeout=30)
    finally:
        os.close(read_fd)
    assert p.returncode==76 and 'malformed_delegation' in p.stderr and not root.exists()


def test_supervisor_without_operator_approval_creates_nothing(tmp_path):
    env,marker=_poisoned_env(tmp_path)
    p=subprocess.run([sys.executable,'-B',str(RUN),str(tmp_path/'run'),str(tmp_path/'m.json'),'0'*64],
                     capture_output=True,text=True,env=env,timeout=30)
    assert p.returncode!=0 and 'OWNER_CONFIRMATION_REQUIRED_BEFORE_PHYSICS' in p.stderr
    assert not (tmp_path/'run').exists() and not marker.exists()


@pytest.mark.parametrize('field,reason',[('readiness_sha256','readiness_binding_mismatch'),
                                         ('execution_head','execution_head_binding_mismatch'),
                                         ('protocol_sha256','protocol_binding_mismatch'),
                                         ('manifest','manifest_binding_mismatch')])
def test_genuine_supervision_refuses_mismatched_binding(tmp_path,field,reason):
    root=tmp_path/'run';manifest=tmp_path/'m.json'
    kwargs={'run_identity':root,'readiness_sha256':'R0','execution_head':'H0','protocol_sha256':'P0','manifest':str(manifest)}
    if field=='manifest':kwargs['manifest']=str(tmp_path/'other.json')
    else:kwargs[field]='drift'
    argv=_write_worker(tmp_path,'positive.py',_positive_body,root,manifest,'R0')
    result=sup.supervise(argv,root,30,**kwargs)
    assert result['native_exitcode']==76 and result['interrupted'] is None
    assert 'WORKER_REFUSED:'+reason in (root/'worker.stderr.raw').read_text()
    assert (root/sup.TOKEN_NAME).exists() and not (root/(sup.TOKEN_NAME+sup.CONSUMED_SUFFIX)).exists()


def test_wrong_run_identity_is_refused(tmp_path):
    root=tmp_path/'run';other=tmp_path/'other';manifest=tmp_path/'m.json'
    argv=_write_worker(tmp_path,'positive.py',_positive_body,root,manifest,'R0')
    result=sup.supervise(argv,root,30,run_identity=other,readiness_sha256='R0',execution_head='H0',protocol_sha256='P0',manifest=str(manifest))
    assert result['native_exitcode']==76 and 'WORKER_REFUSED:run_identity_binding_mismatch' in (root/'worker.stderr.raw').read_text()
    assert (root/sup.TOKEN_NAME).exists()


def test_indirect_descendant_cannot_consume_the_delegation(tmp_path):
    def body(script):
        return ("os.set_inheritable(fd,True)\n"
                "child=subprocess.run([sys.executable,"+repr(str(RUN))+",sys.argv[1],sys.argv[2],sys.argv[3],"
                "'--worker-owner-approved','--supervisor-fd',str(fd)],pass_fds=(fd,))\n"
                "sys.exit(child.returncode)\n")
    root=tmp_path/'run';manifest=tmp_path/'m.json'
    argv=_write_worker(tmp_path,'launcher.py',body,root,manifest,'R0')
    result=sup.supervise(argv,root,30,run_identity=root,readiness_sha256='R0',execution_head=_head(),
                         protocol_sha256=_sha(HERE/'protocol.json'),manifest=str(manifest))
    assert result['native_exitcode']==76
    stderr=(root/'worker.stderr.raw').read_text()
    assert 'WORKER_REFUSED:' in stderr and any(reason in stderr for reason in
        ('worker_not_supervised_session','worker_lifetime_mismatch','parent_identity_mismatch','supervisor_entry_mismatch'))
    assert (root/sup.TOKEN_NAME).exists()


@pytest.mark.parametrize('launcher_name',['launcher.py','run.py'])
@pytest.mark.parametrize('channel',['pipe','stdin'])
def test_forged_launcher_with_real_pipe_token_and_true_facts_is_refused(tmp_path,launcher_name,channel):
    # An ordinary custom Python launcher fabricates the token, a real inherited pipe and
    # a JSON payload carrying its own true kernel facts, then spawns the actual Worker.
    # The Worker must refuse: its parent argv is not the canonical supervisor entry.
    root=tmp_path/'forged-run';manifest=tmp_path/'m.json';manifest.write_text('{}')
    head=_head();proto=_sha(HERE/'protocol.json')
    launcher=tmp_path/launcher_name
    launcher.write_text(
        "import importlib.util,json,os,subprocess,sys,time,pathlib\n"
        "spec=importlib.util.spec_from_file_location('sup',"+repr(str(SUP))+")\n"
        "sup=importlib.util.module_from_spec(spec);spec.loader.exec_module(sup)\n"
        "root,manifest,sha="+repr(str(root))+","+repr(str(manifest))+","+"'R0'\n"
        "runner="+repr(str(RUN))+"\n"
        "os.makedirs(os.path.dirname(root),exist_ok=True);os.makedirs(root,exist_ok=True)\n"
        "read_fd,write_fd=os.pipe();os.set_inheritable(read_fd,True)\n"
        "nonce=os.urandom(16).hex()\n"
        "open(os.path.join(root,sup.TOKEN_NAME),'w').write(nonce)\n"
        "out=open(os.path.join(os.path.dirname(root),'w.out'),'wb');err=open(os.path.join(os.path.dirname(root),'w.err'),'wb')\n"
        "base=[sys.executable,runner,root,manifest,sha,'--worker-owner-approved']\n"
        "if "+repr(channel)+"=='stdin':\n"
        "    worker=subprocess.Popen(base+['--supervisor-fd','0'],stdin=read_fd,stdout=out,stderr=err,start_new_session=True)\n"
        "else:\n"
        "    worker=subprocess.Popen(base+['--supervisor-fd',str(read_fd)],pass_fds=(read_fd,),stdout=out,stderr=err,start_new_session=True)\n"
        "os.close(read_fd)\n"
        "payload={'protocol':sup.VERSION,'run_id':str(pathlib.Path(root).resolve()),'manifest':str(pathlib.Path(manifest).resolve()),\n"
        "         'readiness_sha256':sha,'execution_head':"+repr(head)+",'protocol_sha256':"+repr(proto)+",'nonce':nonce,\n"
        "         'token':os.path.join(root,sup.TOKEN_NAME),'issued_unix':time.time(),'supervisor':sup.proc_identity(),\n"
        "         'worker':sup._identity(worker.pid)}\n"
        "os.write(write_fd,json.dumps(payload).encode());os.close(write_fd)\n"
        "print('CHILD_RC',worker.wait())\n")
    env,_=_poisoned_env(tmp_path)
    p=subprocess.run([sys.executable,'-B',str(launcher)],capture_output=True,text=True,env=env,cwd=ROOT,timeout=60)
    assert 'CHILD_RC 76' in p.stdout, p.stdout+p.stderr
    stderr=(tmp_path/'w.err').read_text()
    assert 'WORKER_REFUSED:supervisor_entry_mismatch' in stderr, stderr
    assert (root/sup.TOKEN_NAME).exists() and not (root/(sup.TOKEN_NAME+sup.CONSUMED_SUFFIX)).exists()
    assert not (tmp_path/'forbidden-import').exists()


def test_execute_permit_is_single_use_and_bound_before_runtime_imports(tmp_path,monkeypatch):
    # Refusals must precede NumPy/Torch/backend imports: poisoned modules stay unimported.
    root=tmp_path/'run';manifest=tmp_path/'m.json';manifest.write_text('{}')
    head=_head();proto=_sha(HERE/'protocol.json')
    poison,marker=_poison_dir(tmp_path)
    monkeypatch.setenv('PYTHONPATH',str(poison)+os.pathsep+str(ROOT/'src'))
    def body(script):
        return (_consume_expr(script,head,proto)
                +"sys.path.insert(0,"+repr(str(HERE))+")\n"
                +"rspec=importlib.util.spec_from_file_location('t2run',"+repr(str(RUN))+")\n"
                +"t2run=importlib.util.module_from_spec(rspec);rspec.loader.exec_module(t2run)\n"
                +"try:t2run.execute("+repr(str(tmp_path/'other'))+","+repr(str(manifest))+",'R0',d)\n"
                +"except RuntimeError as exc:print('WRONG_ARGS_REFUSED:'+str(exc))\n"
                +"try:t2run.execute("+repr(str(root))+","+repr(str(manifest))+",'R0',d)\n"
                +"except RuntimeError as exc:print('FIRST_USE:'+type(exc).__name__+':'+str(exc))\n"
                +"try:t2run.execute("+repr(str(root))+","+repr(str(manifest))+",'R0',d)\n"
                +"except RuntimeError as exc:print('REPLAY_REFUSED:'+str(exc))\n"
                +"print('FORBIDDEN_IMPORTED',os.path.exists("+repr(str(marker))+"))\n")
    argv=_write_worker(tmp_path,'permit.py',body,root,manifest,'R0')
    result=sup.supervise(argv,root,30,run_identity=root,readiness_sha256='R0',execution_head=head,
                         protocol_sha256=proto,manifest=str(manifest))
    assert result['native_exitcode']==0, (root/'worker.stderr.raw').read_text()
    stdout=(root/'worker.stdout.raw').read_text()
    assert 'WRONG_ARGS_REFUSED:delegation_run_identity_mismatch' in stdout
    assert 'FIRST_USE:RuntimeError:readiness_mismatch' in stdout
    assert 'REPLAY_REFUSED:delegation_already_spent' in stdout
    assert 'FORBIDDEN_IMPORTED False' in stdout and not marker.exists()


def test_execute_requires_a_live_supervisor_delegation(tmp_path):
    for delegation in (None,{'protocol':sup.VERSION},'g1.t2a.supervisor.v1'):
        with pytest.raises(RuntimeError,match='supervisor_delegation_required'):
            run.execute(tmp_path/'run',tmp_path/'m.json','0'*64,delegation)


def test_spawn_failure_writes_receipt_and_preserves_token_and_evidence(tmp_path):
    root=tmp_path/'run';root.mkdir();(root/'failure.json').write_text('worker physical failure evidence')
    kwargs={'run_identity':root,'readiness_sha256':'R0','execution_head':'H0','protocol_sha256':'P0','manifest':str(tmp_path/'m.json')}
    with pytest.raises(FileNotFoundError):
        sup.supervise([str(tmp_path/'no-such-worker-binary')],root,30,**kwargs)
    receipt=json.loads((root/'process-receipt.json').read_text())
    assert receipt['failure_phase']=='spawn' and receipt['pid'] is None and 'no-such-worker-binary' in receipt['failure']
    assert (root/'failure.json').read_text()=='worker physical failure evidence'
    assert (root/sup.TOKEN_NAME).exists() and not (root/(sup.TOKEN_NAME+sup.CONSUMED_SUFFIX)).exists()
    with pytest.raises(FileExistsError):
        sup.supervise([sys.executable,'-c','pass'],root,30,**kwargs)


def test_identity_failure_reaps_group_and_preserves_receipt(tmp_path,monkeypatch):
    root=tmp_path/'run';manifest=tmp_path/'m.json'
    def _boom(pid,*a,**k):raise sup.DelegationRefused('worker_identity_unavailable')
    monkeypatch.setattr(sup,'_identity',_boom)
    argv=_write_worker(tmp_path,'positive.py',_positive_body,root,manifest,'R0')
    with pytest.raises(sup.DelegationRefused,match='worker_identity_unavailable'):
        sup.supervise(argv,root,30,run_identity=root,readiness_sha256='R0',execution_head='H0',protocol_sha256='P0',manifest=str(manifest))
    receipt=json.loads((root/'process-receipt.json').read_text())
    assert receipt['failure_phase']=='identity' and receipt['pid']
    assert _dead(receipt['pid'])
    assert (root/sup.TOKEN_NAME).exists() and not (root/(sup.TOKEN_NAME+sup.CONSUMED_SUFFIX)).exists()


def test_delegation_write_failure_reaps_group_and_preserves_receipt(tmp_path,monkeypatch):
    root=tmp_path/'run';manifest=tmp_path/'m.json'
    def _boom(*a,**k):raise OSError('synthetic_send_failure')
    monkeypatch.setattr(sup,'_send_payload',_boom)
    argv=_write_worker(tmp_path,'positive.py',_positive_body,root,manifest,'R0')
    with pytest.raises(OSError,match='synthetic_send_failure'):
        sup.supervise(argv,root,30,run_identity=root,readiness_sha256='R0',execution_head='H0',protocol_sha256='P0',manifest=str(manifest))
    receipt=json.loads((root/'process-receipt.json').read_text())
    assert receipt['failure_phase']=='delegation_write' and 'synthetic_send_failure' in receipt['failure'] and receipt['pid']
    assert _dead(receipt['pid'])
    assert (root/'worker.stderr.raw').exists() and (root/sup.TOKEN_NAME).exists()


def test_stalled_pipe_transfer_is_bounded(tmp_path):
    read_fd,write_fd=os.pipe()
    fake=tmp_path/'worker.py'
    trust=sup.entry_trust(fake,[str(fake),str(tmp_path/'r'),'m','R0','--worker-owner-approved','--supervisor-fd',str(read_fd)],python_path=sys.executable)
    started=time.monotonic()
    with pytest.raises(sup.DelegationRefused,match='delegation_transfer_timeout'):
        sup.consume_delegation(read_fd,trust,execution_head='H0',protocol_sha256='P0',transfer_timeout_s=.25)
    assert time.monotonic()-started<2
    os.close(write_fd)


def test_foreign_fd_context_is_refused(tmp_path):
    read_fd,write_fd=os.pipe()
    fake=tmp_path/'worker.py'
    trust=sup.entry_trust(fake,[str(fake),str(tmp_path/'r'),'m','R0','--worker-owner-approved','--supervisor-fd',str(read_fd+1)],python_path=sys.executable)
    with pytest.raises(sup.DelegationRefused,match='supervisor_fd_context_mismatch'):
        sup.consume_delegation(read_fd,trust,execution_head='H0',protocol_sha256='P0')
    os.close(write_fd)


def test_stale_delegation_and_construction_guards(tmp_path):
    root=tmp_path/'stale';root.mkdir();token=root/sup.TOKEN_NAME
    nonce=os.urandom(16).hex();token.write_text(nonce)
    payload={'protocol':sup.VERSION,'run_id':str(root.resolve()),'manifest':str((tmp_path/'m.json').resolve()),
             'readiness_sha256':'R0','execution_head':'H0','protocol_sha256':'P0','nonce':nonce,'token':str(token),
             'issued_unix':time.time()-100000.,'supervisor':sup.proc_identity(os.getppid()),'worker':sup.proc_identity()}
    fd=_pipe(payload)
    fake=tmp_path/'worker.py'
    trust=sup.entry_trust(fake,[str(fake),str(root),str(tmp_path/'m.json'),'R0','--worker-owner-approved','--supervisor-fd',str(fd)],
                          python_path=sys.executable,expected_parent_argv=ANCHOR)
    with pytest.raises(sup.DelegationRefused,match='stale_delegation'):
        sup.consume_delegation(fd,trust,execution_head='H0',protocol_sha256='P0')
    assert token.exists()
    with pytest.raises(sup.DelegationRefused,match='delegation_construction_forbidden'):sup.Delegation({},object())
    with pytest.raises(sup.DelegationRefused,match='entry_trust_construction_forbidden'):
        sup.EntryTrust(None,None,None,None,None,0,None,object())
    assert not sup.is_live_delegation({'protocol':sup.VERSION})


def test_watchdog_kills_supervised_worker_and_descendants(tmp_path):
    def body(script):
        return ("descendant=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)'])\n"
                "open(os.path.join(sys.argv[1],'descendant.pid'),'w').write(str(descendant.pid))\n"
                +_consume_expr(script,'H0','P0')+"time.sleep(300)\n")
    root=tmp_path/'run';manifest=tmp_path/'m.json'
    argv=_write_worker(tmp_path,'slow.py',body,root,manifest,'R0')
    result=sup.supervise(argv,root,1,run_identity=root,readiness_sha256='R0',execution_head='H0',protocol_sha256='P0',manifest=str(manifest))
    assert result['interrupted']=='wall_clock_watchdog' and result['elapsed_s']<5
    for pid in (result['pid'],int((root/'descendant.pid').read_text())):
        assert _dead(pid),f'process {pid} survived supervisor termination'


def test_normal_worker_exit_reaps_living_descendants(tmp_path):
    def body(script):
        return ("descendant=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)'])\n"
                "open(os.path.join(sys.argv[1],'descendant.pid'),'w').write(str(descendant.pid))\n"
                +_consume_expr(script,'H0','P0'))
    root=tmp_path/'run';manifest=tmp_path/'m.json'
    argv=_write_worker(tmp_path,'exiting.py',body,root,manifest,'R0')
    result=sup.supervise(argv,root,30,run_identity=root,readiness_sha256='R0',execution_head='H0',protocol_sha256='P0',manifest=str(manifest))
    assert result['native_exitcode']==0 and result['interrupted'] is None
    assert _dead(int((root/'descendant.pid').read_text()))


def test_partial_failure_preserves_logs_and_receipt(tmp_path):
    def body(script):
        return _consume_expr(script,'H0','P0')+"print('SYNTHETIC_WORKER_OK')\nsys.exit(3)\n"
    root=tmp_path/'run';manifest=tmp_path/'m.json'
    argv=_write_worker(tmp_path,'partial.py',body,root,manifest,'R0')
    result=sup.supervise(argv,root,30,run_identity=root,readiness_sha256='R0',execution_head='H0',protocol_sha256='P0',manifest=str(manifest))
    assert result['native_exitcode']==3 and result['interrupted'] is None
    assert 'SYNTHETIC_WORKER_OK' in (root/'worker.stdout.raw').read_text()
    assert json.loads((root/'process-receipt.json').read_text())['native_exitcode']==3
    assert (root/(sup.TOKEN_NAME+sup.CONSUMED_SUFFIX)).exists()


def test_supervisor_cutoff_excludes_preflight_time(tmp_path):
    root=tmp_path/'campaign';manifest=tmp_path/'manifest.json';manifest.write_text('{}')
    def verifier(path,expected):time.sleep(.4);return {'execution_head':'H0','protocol_sha256':'P0'}
    worker_argv=_write_worker(tmp_path,'positive.py',_positive_body,root,manifest,'R0')
    with pytest.raises(SystemExit) as info:
        run.main([str(root),str(manifest),'R0','--execute-owner-approved'],verifier=verifier,worker_argv=worker_argv)
    assert info.value.code==0
    receipt=json.loads((root/'process-receipt.json').read_text())
    assert 593.5<receipt['limit_s']<594.8,receipt['limit_s']


def test_relative_campaign_root_resolves_before_token_generation(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    root=Path('rel-run');manifest=tmp_path/'m.json'
    argv=_write_worker(tmp_path,'positive.py',_positive_body,root,manifest,'R0')
    result=sup.supervise(argv,root,30,run_identity=root,readiness_sha256='R0',execution_head='H0',protocol_sha256='P0',manifest=str(manifest))
    assert result['native_exitcode']==0,(tmp_path/'rel-run'/'worker.stderr.raw').read_text()
    assert (tmp_path/'rel-run'/(sup.TOKEN_NAME+sup.CONSUMED_SUFFIX)).exists()


def test_duplicate_campaign_start_is_refused(tmp_path):
    root=tmp_path/'campaign';manifest=tmp_path/'m.json';manifest.write_text('{}')
    def verifier(path,expected):return {'execution_head':'H0','protocol_sha256':'P0'}
    worker_argv=_write_worker(tmp_path,'positive.py',_positive_body,root,manifest,'R0')
    args=[str(root),str(manifest),'R0','--execute-owner-approved']
    with pytest.raises(SystemExit) as info:run.main(args,verifier=verifier,worker_argv=worker_argv)
    assert info.value.code==0
    stdout=(root/'worker.stdout.raw').read_text()
    with pytest.raises(FileExistsError):run.main(args,verifier=verifier,worker_argv=worker_argv)
    assert (root/'worker.stdout.raw').read_text()==stdout