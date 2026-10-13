"""Trusted serial Owner-to-canonical-Mission entry, not a production authority service.

The original language proposal remains DENY. A fresh Owner source explicitly
issues the reviewed full plan as a new instruction. No test/approve CLI flag.
"""
from datetime import datetime,timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import uuid

from . import demo_identity as identity
from .action import validate_preparation,check_owner_comment,fetch_owner_comment
from .service import canonical

ENTRY=identity.ROOT/'console/language_v01/demo_entry.py'
REVIEW_VERDICT='READY_FOR_OWNER_SINGLE_LANGUAGE_SIMULATION'

def load_preparation(path):
    p=json.loads(Path(path).read_bytes()); validate_preparation(p)
    evidence=Path(p['evidence_root']).resolve()
    sealed=identity.read(evidence/(p['request_id']+'-preparation.json'))
    request=identity.read(evidence/(p['request_id']+'.json'))
    if canonical(sealed)!=canonical(p) or canonical(request)!=canonical(p['request']):
        raise PermissionError('SEALED_REQUEST_OR_PREPARATION_MISMATCH')
    return json.loads(canonical(p))

def verify_review(path,preparation):
    review=identity.read(path)
    if (review.get('schema')!='language-g1-independent-review/0.1' or
        review.get('verdict')!=REVIEW_VERDICT or review.get('C_exec')!=preparation['C_exec'] or
        review.get('readiness_sha256')!=preparation['readiness_sha256'] or
        review.get('protocol_sha256')!=preparation['protocol_sha256'] or
        review.get('scope')!='NONPHYSICAL_EXECUTION_BOUNDARY_AND_NEW_CAPTURE_CANDIDATE' or
        review.get('physics_performed') is not False):
        raise PermissionError('INDEPENDENT_REVIEW_IDENTITY_OR_SCOPE_MISMATCH')
    report=Path(path).with_name(review['report_file'])
    if not report.resolve().is_relative_to(Path(path).parent.resolve()) or identity.sha(report)!=review['report_sha256']:
        raise PermissionError('INDEPENDENT_REVIEW_REPORT_MISMATCH')
    return identity.sha(path)

def verify_inputs(preparation_path,readiness,readiness_sha,review_path):
    source=identity.verify(readiness,readiness_sha)
    p=load_preparation(preparation_path)
    if (p['C_exec']!=source['C_exec'] or p['readiness_sha256']!=readiness_sha or
        p['source_sha256']!=identity.sha(Path(readiness).with_name('source.json')) or
        p['request']['provenance']['head_at_request']!=source['C_exec']):
        raise PermissionError('REQUEST_EXECUTION_IDENTITY_MISMATCH')
    if p['request']['authorization']['decision']!='DENY' or p['gates']['d011']!='BLOCKED':
        raise PermissionError('ORIGINAL_LANGUAGE_GATE_REWRITTEN')
    review_sha=verify_review(review_path,p)
    return p,source,review_sha

def lifecycle():
    spec=importlib.util.spec_from_file_location('language_g1_retained_windows_job',
        identity.ROOT/'experiments/mission_constrained/skill_handoff_acquisition_001/lifecycle.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def consume(p,owner,directory):
    evidence=Path(p['evidence_root'])
    claims=evidence/'owner-consumed'; claims.mkdir(exist_ok=True)
    for key in ('request-'+p['request_id'],'comment-'+str(owner['comment_id'])):
        identity.write(claims/(key+'.json'),{'preparation_sha256':p['preparation_sha256'],
            'run_id':Path(directory).name,'run_path':str(Path(directory).resolve()),
            'owner_comment_id':owner['comment_id'],'scope':'TRUSTED_SERIAL_RESEARCH_SINGLE_ATTEMPT'})

def worker(directory):
    directory=Path(directory).resolve()
    backend_entered=False
    try:
        launch=identity.read(directory/'launch.json')
        if (launch['parent_pid']!=os.getppid() or launch['C_exec']!=identity.head() or
            launch['run_id']!=directory.name or launch['deadline']!=launch['started']+115 or
            time.perf_counter()>=launch['deadline']-2):
            raise PermissionError('DIRECT_OR_EXPIRED_WORKER_REJECTED')
        p,source,review_sha=verify_inputs(launch['preparation'],launch['readiness'],launch['readiness_sha256'],launch['review'])
        if (directory.parent!=Path(p['evidence_root']).resolve()/'runs' or
            launch['preparation_sha256']!=p['preparation_sha256'] or launch['review_sha256']!=review_sha):
            raise PermissionError('WORKER_MANIFEST_CONTEXT_MISMATCH')
        intent=identity.read(Path(p['evidence_root'])/'launch-requests'/(p['request_id']+'.json'))
        if intent['run_id']!=directory.name or intent['parent_pid']!=os.getppid():
            raise PermissionError('WORKER_SINGLE_ATTEMPT_CONTEXT_MISMATCH')
        with (directory/'worker-used').open('x'): pass
        raw=fetch_owner_comment(launch['owner_comment_id'])
        owner=check_owner_comment(raw,p,accepted_review_sha256=review_sha)
        if raw['id']!=launch['owner_comment_id']: raise PermissionError('OWNER_SOURCE_ID_MISMATCH')
        identity.write(directory/'owner-source.json',raw)
        identity.write(directory/'authorization.json',{**owner,'accepted_independent_review_sha256':review_sha,
            'execution_basis':'OWNER_NEW_EXPLICIT_CANONICAL_MISSION',
            'original_language_proposal':'DENY','language_runtime':'BLOCKED','d011':'BLOCKED'})
        if time.perf_counter()>=launch['deadline']-2: raise TimeoutError('NO_MODEL_STARTUP_BUDGET')
        check_owner_comment(raw,p,accepted_review_sha256=review_sha)
        consume(p,owner,directory)
        identity.verify(launch['readiness'],launch['readiness_sha256'])
        expiry=datetime.fromisoformat(owner['expires_at'].replace('Z','+00:00'))
        remaining=(expiry-datetime.now(timezone.utc)).total_seconds()
        if remaining<=0: raise PermissionError('OWNER_EXPIRED_BEFORE_MODEL_LOADING')
        backend_deadline=min(launch['deadline']-2,time.perf_counter()+remaining)
        from .physical import execute
        backend_entered=True
        result=execute(json.loads(canonical(p)),source,directory,backend_deadline)
        return 0 if result.get('status')=='COMPLETED' else 1
    except BaseException as exc:
        error={'status':'REFUSED_OR_TECHNICAL_STOP','stage':'worker','type':type(exc).__name__,
               'reason':str(exc),'physics_steps':None if backend_entered else 0,'backend_entered':backend_entered}
        if directory.is_dir(): identity.write(directory/'worker-error.json',error)
        print(json.dumps(error),flush=True)
        return 2

def supervisor(directory):
    directory=Path(directory).resolve()
    outer=identity.read(directory/'outer.json')
    if outer['parent_pid']!=os.getppid() or outer['deadline']!=outer['started']+115:
        raise PermissionError('DIRECT_SUPERVISOR_REJECTED')
    started=outer['started']
    preparation_path,readiness,readiness_sha,review_path,owner_comment_id=(outer[k] for k in
        ('preparation','readiness','readiness_sha256','review','owner_comment_id'))
    p,source,review_sha=verify_inputs(preparation_path,readiness,readiness_sha,review_path)
    if directory.parent!=Path(p['evidence_root']).resolve()/'runs':
        raise PermissionError('OUTER_RUN_DIRECTORY_MISMATCH')
    record={'run_id':directory.name,'parent_pid':os.getpid(),'C_exec':source['C_exec'],
        'started':started,'deadline':started+115,'total_deadline':started+120,
        'preparation':str(Path(preparation_path).resolve()),'preparation_sha256':p['preparation_sha256'],
        'readiness':str(Path(readiness).resolve()),'readiness_sha256':readiness_sha,
        'review':str(Path(review_path).resolve()),'review_sha256':review_sha,'owner_comment_id':owner_comment_id}
    identity.write(directory/'launch.json',record)
    index=Path(p['evidence_root'])/'execution-index'; index.mkdir(exist_ok=True)
    with (index/(p['request_id']+'.jsonl')).open('a',encoding='utf-8') as stream:
        stream.write(json.dumps({'run_id':directory.name,'preparation_sha256':p['preparation_sha256'],
                                'C_exec':p['C_exec']})+'\n')
    intents=Path(p['evidence_root'])/'launch-requests'; intents.mkdir(exist_ok=True)
    identity.write(intents/(p['request_id']+'.json'),{'run_id':directory.name,'parent_pid':os.getpid(),
        'preparation_sha256':p['preparation_sha256'],'scope':'SINGLE_LAUNCH_ATTEMPT_NO_AUTOMATIC_RETRY'})
    command=[sys.executable,'-B',str(ENTRY),'worker','--run-directory',str(directory)]
    process_dir=directory/'worker-process'; process_dir.mkdir(exist_ok=False)
    process=lifecycle().supervise(command,process_dir,started+113,identity.ROOT)
    audit=None
    if (directory/'physical.json').is_file() and identity.read(directory/'physical.json').get('kind')=='NEW_MUJOCO_CAPTURE':
        from .observations import audit_capture
        audit=audit_capture(directory,p,started+113)
        identity.write(directory/'capture-audit.json',audit)
    summary={'run_id':directory.name,'request_id':p['request_id'],'C_exec':p['C_exec'],
        'preparation_sha256':p['preparation_sha256'],'process':process,
        'physical_sha256':identity.sha(directory/'physical.json') if (directory/'physical.json').exists() else None,
        'status':'CAPTURE_FINISHED' if process['passed'] else 'REFUSED_FAILED_OR_PARTIAL',
        'elapsed_s':time.perf_counter()-started,'within_total_budget':time.perf_counter()<=started+120,
        'media':'NOT_RENDERED','broad_language_runtime':'BLOCKED','d011':'BLOCKED'}
    if summary['physical_sha256']: summary['kind']=identity.read(directory/'physical.json')['kind']
    if audit is not None:
        summary['capture_integrity']=audit['passed']
        if not audit['passed']: summary['status']='REFUSED_FAILED_OR_PARTIAL'
    identity.write(directory/'supervisor-completion.json',summary)
    return summary

def launch(preparation_path,readiness,readiness_sha,review_path,owner_comment_id):
    started=time.perf_counter()
    # Only bounded local metadata is read before the outer Job. Compiler,
    # frozen-source checks and network I/O belong to the contained Supervisor.
    path=Path(preparation_path)
    if path.stat().st_size>262144: raise PermissionError('PREPARATION_SIZE_LIMIT')
    p=json.loads(path.read_bytes())
    directory=Path(p['evidence_root']).resolve()/'runs'/uuid.uuid4().hex
    directory.mkdir(parents=True,exist_ok=False)
    identity.write(directory/'outer.json',{'parent_pid':os.getpid(),'started':started,'deadline':started+115,
        'preparation':str(path.resolve()),'readiness':str(Path(readiness).resolve()),
        'readiness_sha256':readiness_sha,'review':str(Path(review_path).resolve()),'owner_comment_id':owner_comment_id})
    process_dir=directory/'outer-process'; process_dir.mkdir(exist_ok=False)
    command=[sys.executable,'-B',str(ENTRY),'supervisor','--run-directory',str(directory)]
    outer=lifecycle().supervise(command,process_dir,started+115,identity.ROOT)
    path=directory/'supervisor-completion.json'
    summary=identity.read(path) if path.exists() else {'status':'REFUSED_FAILED_OR_PARTIAL','run_id':directory.name,
        'request_id':p.get('request_id'),'C_exec':p.get('C_exec'),'preparation_sha256':p.get('preparation_sha256')}
    summary['outer_process']=outer
    summary['within_total_budget']=time.perf_counter()<=started+120
    if not outer['passed'] or not summary['within_total_budget']: summary['status']='REFUSED_FAILED_OR_PARTIAL'
    cleaned=(outer.get('reaped') and outer.get('tree_empty') and not outer.get('timed_out') and not outer.get('cleanup_errors'))
    if (cleaned and summary.get('capture_integrity') and summary['within_total_budget'] and summary.get('kind')=='NEW_MUJOCO_CAPTURE' and
        identity.read(directory/'physical.json')['native_completed']>0):
        # A valid negative capture is also observable. Media never rewrites the
        # mission verdict, and rendering failure never hides a saved task result.
        render_dir=directory/'render-process'; render_dir.mkdir(exist_ok=False)
        render_started=time.perf_counter()
        identity.write(render_dir/'entry.json',{'parent_pid':os.getpid(),'run_id':directory.name,
            'started':render_started,'deadline':render_started+55,'owner_comment_id':owner_comment_id})
        command=[sys.executable,'-B',str(ENTRY),'render','--run-directory',str(directory)]
        summary['render_process']=lifecycle().supervise(command,render_dir,render_started+55,identity.ROOT)
        summary['media']='AVAILABLE' if summary['render_process']['passed'] and (directory/'media.json').is_file() else 'RENDER_FAILED_OR_PARTIAL'
        summary['render_within_budget']=time.perf_counter()<=render_started+60
    identity.write(directory/'completion.json',summary)
    return summary

def render_worker(directory):
    directory=Path(directory).resolve()
    try:
        entry=identity.read(directory/'render-process/entry.json'); launch=identity.read(directory/'launch.json')
        if (entry['parent_pid']!=os.getppid() or entry['run_id']!=directory.name or
            entry['deadline']!=entry['started']+55 or time.perf_counter()>=entry['deadline']-2):
            raise PermissionError('DIRECT_RENDER_WORKER_REJECTED')
        p,source,review_sha=verify_inputs(launch['preparation'],launch['readiness'],launch['readiness_sha256'],launch['review'])
        raw=fetch_owner_comment(entry['owner_comment_id'])
        check_owner_comment(raw,p,accepted_review_sha256=review_sha)
        consumed=identity.read(Path(p['evidence_root'])/'owner-consumed'/('request-'+p['request_id']+'.json'))
        if consumed['run_id']!=directory.name: raise PermissionError('UNRELATED_CAPTURE_RENDER_REJECTED')
        from .media import render_saved
        render_saved(directory,source,entry['deadline']-2)
        return 0
    except BaseException as exc:
        identity.write(directory/'media-error.json',{'type':type(exc).__name__,'reason':str(exc),'physics_steps':0,'policy_calls':0})
        return 2
