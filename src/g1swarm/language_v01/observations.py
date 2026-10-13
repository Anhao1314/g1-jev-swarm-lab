"""Read-only fresh-run audit/Console binding. No imports of models or simulator."""
import json
import math
from pathlib import Path
import re
import time

from . import demo_identity as identity
from .service import canonical

def audit_capture(directory,p,deadline=None):
    directory=Path(directory).resolve()
    receipt=identity.read(directory/'physical.json')
    errors=[]
    def check():
        if deadline is not None and time.perf_counter()>=deadline: raise TimeoutError('RAW_AUDIT_DEADLINE')
    expected={'kind':'NEW_MUJOCO_CAPTURE','request_id':p['request_id'],'C_exec':p['C_exec'],
              'preparation_sha256':p['preparation_sha256'],'executed_mission_sha256':p['mission_sha256']}
    if any(receipt.get(k)!=v for k,v in expected.items()): errors.append('CAPTURE_IDENTITY_MISMATCH')
    for name,value in receipt.get('files',{}).items():
        check(); path=(directory/name).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or path.stat().st_size>100000000 or identity.sha(path)!=value:
            errors.append('CAPTURE_FILE_MISMATCH:'+name)
    for required in ('native.jsonl','initial-state.json'):
        if required not in receipt.get('files',{}): errors.append('MISSING_RAW:'+required)
    attempts=[]; completed=[]; policy_attempts=[]; policy_completed=[]; raw_nonfinite=False; raw_fallen=False
    with (directory/'native.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            check()
            if len(line)>262144: errors.append('OVERSIZED_RAW_ROW'); break
            row=json.loads(line)
            if 'native_attempt' in row: attempts.append(row['native_attempt'])
            if 'native_completed' in row and 'post' in row: completed.append(row['native_completed'])
            if 'policy_attempt' in row: policy_attempts.append(row['policy_attempt'])
            if 'policy_completed' in row: policy_completed.append(row['policy_completed'])
            state=row.get('state',{})
            raw_fallen |= state.get('fallen') is True
            for snapshot in (row.get('post',{}),row.get('raw',{})):
                for key in ('qpos','qvel','ctrl'):
                    values=snapshot.get(key,[])
                    raw_nonfinite |= any(type(v) not in (float,int) or not math.isfinite(v) for v in values)
    if (attempts!=list(range(1,len(attempts)+1)) or completed!=list(range(1,len(completed)+1)) or
        policy_attempts!=list(range(1,len(policy_attempts)+1)) or policy_completed!=list(range(1,len(policy_completed)+1))):
        errors.append('RAW_COUNTER_SEQUENCE_INVALID')
    counts={'native_attempts':len(attempts),'native_completed':len(completed),
            'policy_inference_attempts':len(policy_attempts),'policy_inference_completed':len(policy_completed)}
    if any(receipt.get(k)!=v for k,v in counts.items()): errors.append('RAW_RECEIPT_COUNTER_MISMATCH')
    if counts['native_attempts']>p['budget']['native_steps'] or len(completed)>len(attempts): errors.append('NATIVE_BUDGET_OR_COMPLETION_INVALID')
    if receipt.get('startup_reset_requests')!=2 or receipt.get('post_checkpoint_reset_requests')!=0:
        errors.append('INITIALIZATION_OR_POST_CHECKPOINT_RESET_COUNT_MISMATCH')
    flags=receipt.get('physical_failure',{})
    if raw_fallen and flags.get('fallen') is not True: errors.append('OBSERVED_FALL_LOST')
    if raw_nonfinite and flags.get('nonfinite') is not True: errors.append('OBSERVED_NONFINITE_LOST')
    if receipt.get('status')=='COMPLETED':
        result=receipt.get('runtime_result') or {}
        if (not result.get('mission_success') or result.get('completed_nodes')!=3 or len(result.get('nodes',[]))!=3 or
            result.get('simulation_steps_executed')!=len(completed) or receipt.get('technical_errors') or
            receipt.get('archival_errors') or any(flags.values()) or len(attempts)!=len(completed)):
            errors.append('FALSE_COMPLETE_OR_RESULT_STEP_COVERAGE')
    return {'passed':not errors,'errors':errors,'recomputed_counts':counts,
            'physical_failure_observed':{'fallen':raw_fallen,'nonfinite':raw_nonfinite},
            'source_physical_sha256':identity.sha(directory/'physical.json'),'scope':'READ_ONLY_INTEGRITY_NOT_RESCORING'}

def execution_for(preparations,request_id):
    p=preparations.get(request_id)
    evidence=Path(p['evidence_root']).resolve()
    answer={'request_id':request_id,'preparation_sha256':p['preparation_sha256'],'run_id':None,
            'status':'AWAITING_OWNER','kind':None,'physics_steps':0,'policy_calls':0,'result':None,'media':None}
    index=evidence/'execution-index'/(request_id+'.jsonl')
    if not index.is_file(): return answer
    entries=[json.loads(row) for row in index.read_text(encoding='utf-8').splitlines() if row.strip()]
    if not entries: return answer
    attempt=entries[-1]
    if (attempt['preparation_sha256']!=p['preparation_sha256'] or attempt['C_exec']!=p['C_exec'] or
        not re.fullmatch('[a-f0-9]{32}',attempt['run_id'])): raise ValueError('EXECUTION_INDEX_BINDING_MISMATCH')
    directory=(evidence/'runs'/attempt['run_id']).resolve()
    if not directory.is_relative_to(evidence/'runs'): raise ValueError('EXECUTION_PATH_OUTSIDE_EVIDENCE')
    launch=identity.read(directory/'launch.json')
    if launch['preparation_sha256']!=p['preparation_sha256'] or launch['C_exec']!=p['C_exec']:
        raise ValueError('EXECUTION_MANIFEST_BINDING_MISMATCH')
    answer.update(run_id=attempt['run_id'],status='RUNNING',physics_steps=None,policy_calls=None)
    completion=directory/'completion.json'; physical=directory/'physical.json'; worker_error=directory/'worker-error.json'
    if completion.is_file():
        done=identity.read(completion)
        if any(done.get(k)!=answer[k] for k in ('request_id','preparation_sha256','run_id')) or done['C_exec']!=p['C_exec']:
            raise ValueError('COMPLETION_CONTEXT_MISMATCH')
        answer['status']=done['status']
        if done.get('physical_sha256') and (not physical.is_file() or identity.sha(physical)!=done['physical_sha256']):
            raise ValueError('COMPLETION_PHYSICAL_BYTES_MISMATCH')
    if worker_error.is_file():
        failure=identity.read(worker_error); answer.update(reason=failure['reason'],physics_steps=failure['physics_steps'])
    if not physical.is_file(): return answer
    receipt=identity.read(physical)
    if any(receipt.get(k)!=v for k,v in {'request_id':request_id,'preparation_sha256':p['preparation_sha256'],
        'C_exec':p['C_exec'],'executed_mission_sha256':p['mission_sha256']}.items()):
        raise ValueError('ACTUAL_CAPTURE_REQUEST_PLAN_MISMATCH')
    answer['kind']=receipt['kind']
    if receipt['kind']!='NEW_MUJOCO_CAPTURE':
        answer.update(status='SYNTHETIC_TEST_ONLY',physics_steps=0,policy_calls=0)
        return answer
    checked=audit_capture(directory,p)
    if not checked['passed']: raise ValueError('CAPTURE_INTEGRITY_REJECTED:'+','.join(checked['errors']))
    answer.update(physics_steps=receipt['native_completed'],policy_calls=receipt['policy_inference_completed'],result=receipt['runtime_result'])
    media_path=directory/'media.json'
    if media_path.is_file():
        media=identity.read(media_path)
        if (media.get('request_id')!=request_id or media.get('preparation_sha256')!=p['preparation_sha256'] or
            media.get('C_exec')!=p['C_exec'] or media.get('executed_mission_sha256')!=p['mission_sha256'] or
            media.get('source_physical_sha256')!=identity.sha(physical) or
            media.get('source_result_sha256')!=identity.sha(directory/'result.json') or
            media.get('source_physical_sha256')!=checked['source_physical_sha256'] or
            media.get('new_capture') is not True or media.get('historical_fallback') is not False or
            identity.sha(directory/'video.mp4')!=media['renderer']['video_sha256']):
            raise ValueError('MEDIA_FRESH_CAPTURE_BINDING_MISMATCH')
        answer['media']={'url':f'/api/requests/{request_id}/media','kind':'NEW_RUN_STATE_PLAYBACK',
                        'sha256':media['renderer']['video_sha256'],'source_pose_sha256':media['renderer']['source_pose_sha256'],
                        'caption':'本次真实采集的状态回放；不是实时机器人画面'}
    return answer

def media_file(preparations,request_id):
    result=execution_for(preparations,request_id)
    if not result['media']: raise KeyError('NO_QUALIFIED_MEDIA_FOR_THIS_REQUEST')
    p=preparations.get(request_id)
    return Path(p['evidence_root'])/'runs'/result['run_id']/'video.mp4'
