"""Single-use Windows serial launcher. Ready is not Owner authorization.

The explicit operation flag represents a separately approved trusted operator,
not production identity. No synthetic bypass is exposed in this CLI.
"""
import argparse
import os
from pathlib import Path
import sys
import time
from entry import HERE,ROOT,ARMS,sha,read,write,head,freeze,preflight
from lifecycle import supervise

def worker(path,digest,directory):
    # Context checked before source preflight and before any runtime import.
    entry=read(directory/'entry.json'); launch=read(directory.parent/'launch.json')
    if (entry['parent_pid']!=os.getppid() or launch['parent_pid']!=os.getppid() or
        entry['arm']!=directory.name or entry['arm'] not in ARMS or
        entry['C_exec']!=head() or launch['C_exec']!=head() or
        entry['readiness_sha256']!=digest or launch['readiness_sha256']!=digest or
        entry['deadline']>launch['outer_deadline'] or
        entry['deadline']>entry['started']+120 or entry['started']<launch['started'] or
        launch.get('owner_operation_asserted') is not True):
        raise PermissionError('INVALID_TRUSTED_PARENT_CONTEXT')
    with (directory/'consumed').open('x'): pass
    preflight(path,digest)
    if time.perf_counter()>=entry['deadline']-2: raise TimeoutError('EXPIRED_WORKER')
    from backend import execute
    status=execute(entry['arm'],directory,entry['deadline']-2)
    return 0 if status['complete'] and not status['physical_failure_observed'] else 1

def acquire(path,digest,destination,owner,started=None):
    if owner is not True: raise PermissionError('SEPARATE_OWNER_PHYSICS_AUTHORIZATION_REQUIRED')
    start=time.perf_counter() if started is None else started
    destination.mkdir(parents=True,exist_ok=False)
    outcome={'status':'PARTIAL_STOPPED','arms':[],'native_attempts_total':0,'physics_authority':'trusted separately approved operator only'}
    try:
        source=preflight(path,digest)
        write(destination/'launch.json',{'C_exec':head(),'readiness_sha256':digest,'parent_pid':os.getpid(),
              'started':start,'outer_deadline':start+235,'total_deadline':start+240,'owner_operation_asserted':True})
        from audit_raw import audit,replay
        from handoff import compare
        metrics=[]
        for arm in ARMS:
            if time.perf_counter()>=start+233: raise TimeoutError('TOTAL_LIFECYCLE_DEADLINE')
            arm_start=time.perf_counter(); deadline=min(start+235,arm_start+120)
            directory=destination/arm; directory.mkdir(exist_ok=False)
            write(directory/'entry.json',{'parent_pid':os.getpid(),'arm':arm,'started':arm_start,'deadline':deadline,
                  'C_exec':head(),'readiness_sha256':digest})
            command=[sys.executable,'-B',str(HERE/'run.py'),'worker','--readiness',str(path),
                     '--sha256',digest,'--output',str(directory)]
            process=supervise(command,directory,deadline,ROOT)
            # Audit even failed/partial workers. It cannot erase physical failure.
            checked=audit(directory); write(directory/'independent_audit.json',checked)
            outcome['arms'].append({'arm':arm,'process':process,'audit':checked})
            status=read(directory/'status.json') if (directory/'status.json').exists() else {}
            count=status.get('native_attempts')
            if type(count) is not int or count<0: raise RuntimeError('NATIVE_ATTEMPTS_UNKNOWN')
            outcome['native_attempts_total']+=count
            if count>32000 or outcome['native_attempts_total']>64000: raise RuntimeError('NATIVE_BUDGET_VIOLATION')
            axes={'physical_failure':checked['physical_failure_observed'] or status.get('physical_failure_observed') is True,
                  'technical_or_missing':checked['technical_or_missing'],
                  'strict_failure':checked['metrics'].get('strict') is False,
                  'integrity_failure':not checked['passed_integrity']}
            outcome['arms'][-1]['failure_axes']=axes
            if axes['physical_failure']: raise RuntimeError('PHYSICAL_FAILURE_STOP_WITH_SEPARATE_TECHNICAL_AXIS')
            if not process['passed'] or not checked['passed_integrity'] or not status.get('complete'):
                raise RuntimeError('TECHNICAL_INTEGRITY_OR_COVERAGE_STOP')
            if arm=='constant':
                replayed=replay(directory,Path(source['history_root']))
                write(destination/'historical_replay.json',replayed)
                if not replayed['passed']: raise RuntimeError('HISTORICAL_REPLAY_MISMATCH')
            else:
                if read(directory/'preintervention.json')!=read(destination/'constant/preintervention.json'):
                    raise RuntimeError('PREINTERVENTION_MISMATCH')
            metrics.append(checked['metrics'])
            if time.perf_counter()>=start+235: raise TimeoutError('AUDIT_LIFECYCLE_DEADLINE')
        write(destination/'comparison.json',compare(*metrics))
        outcome['status']='COMPLETE_PREFIX_COMPARISON_NOT_FULL_MISSION'
    except BaseException as exc:
        outcome['stop_reason']={'type':type(exc).__name__,'message':str(exc)}
    finally:
        outcome['elapsed_s']=time.perf_counter()-start
        if outcome['elapsed_s']>=240:
            outcome['status']='PARTIAL_STOPPED'; outcome['budget_violation']=True
        write(destination/'completion.json',outcome)
    return outcome

def launch(path,digest,destination,owner):
    """Outer Job bounds initialization/preflight, audit and nested Worker jobs."""
    if owner is not True: raise PermissionError('SEPARATE_OWNER_PHYSICS_AUTHORIZATION_REQUIRED')
    start=time.perf_counter()
    destination.mkdir(parents=True,exist_ok=False)
    write(destination/'outer.json',{'parent_pid':os.getpid(),'started':start,'deadline':start+235,
                                  'readiness_sha256':digest,'owner_operation_asserted':True})
    command=[sys.executable,'-B',str(HERE/'run.py'),'supervisor','--readiness',str(path),
             '--sha256',digest,'--output',str(destination/'campaign')]
    receipt=supervise(command,destination,start+235,ROOT)
    result={'process':receipt,'elapsed_s':time.perf_counter()-start,
            'status':'SUPERVISOR_FINISHED' if receipt['passed'] else 'PARTIAL_STOPPED',
            'missing_completion':not (destination/'campaign/completion.json').exists()}
    if result['elapsed_s']>=240: result.update(status='PARTIAL_STOPPED',budget_violation=True)
    write(destination/'outer_receipt.json',result)
    return result

def supervised_campaign(path,digest,destination):
    entry=read(destination.parent/'outer.json')
    if (entry['parent_pid']!=os.getppid() or entry['readiness_sha256']!=digest or
        entry['owner_operation_asserted'] is not True or
        entry['deadline']!=entry['started']+235 or time.perf_counter()>=entry['deadline']-2):
        raise PermissionError('INVALID_OUTER_SUPERVISOR_CONTEXT')
    with (destination.parent/'outer_consumed').open('x'): pass
    outcome=acquire(path,digest,destination,True,entry['started'])
    return 0 if outcome['status']=='COMPLETE_PREFIX_COMPARISON_NOT_FULL_MISSION' else 1

if __name__=='__main__':
    import json
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['freeze','preflight','worker','acquire','supervisor'])
    p.add_argument('--readiness',type=Path); p.add_argument('--sha256')
    p.add_argument('--output',type=Path); p.add_argument('--history',type=Path)
    p.add_argument('--owner-authorized',action='store_true')
    a=p.parse_args()
    if a.command=='freeze': print(json.dumps(freeze(a.output,a.history)))
    elif a.command=='preflight':
        s=preflight(a.readiness,a.sha256)
        print(json.dumps({'status':'NONPHYSICAL_PREFLIGHT_PASS','C_exec':head(),'files':len(s['files']),
              'assets':len(s['assets']),'dependencies':len(s['environment']['packages']),'physics_authorized':False}))
    elif a.command=='worker': sys.exit(worker(a.readiness,a.sha256,a.output))
    elif a.command=='supervisor': sys.exit(supervised_campaign(a.readiness,a.sha256,a.output))
    else: print(json.dumps(launch(a.readiness,a.sha256,a.output,a.owner_authorized)))
