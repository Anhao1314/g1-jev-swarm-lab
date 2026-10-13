"""Synthetic arrays only: never instantiate a simulator or load a policy."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_raw as audit


def dump(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')


def state(s):
    return {'simulation_time':s['time_s'], 'base_position':s['qpos'][:3],
            'base_orientation':s['qpos'][3:7], 'linear_velocity':s['qvel'][:3],
            'angular_velocity':s['qvel'][3:6]}


def fixture(root):
    root.mkdir()
    rows, bounds, nodes, schedules = [], [], [], []
    resets = [{'node':-1,'step':0,'counter_before':0,'counter_after':0}]
    snap = {'time_s':0., 'qpos':[0.,0.,.8,1.,0.,0.,0.]+[0.]*12,
            'qvel':[0.]*18,'ctrl':[0.]*12,'command':[0.]*3,
            'counter':0,'resets':0,'action':[0.]*12,'target':[0.]*12,'node':0}
    prefix = hashlib.sha256()
    trigger = None
    step = 0
    trace = []
    for node, count in enumerate([2500,300,251]):
        snap['node'] = node
        start = copy.deepcopy(snap)
        bounds.append({'node':node,'phase':'entry','snapshot':start,'policy_tensors_sha256':'0'*64})
        post_reset=copy.deepcopy(start);post_reset['counter']=0;post_reset['action']=[0.]*12
        resets.append({'node':node,'step':step,'counter_before':snap['counter'],'counter_after':0,
                       'post_reset_snapshot':post_reset,'policy_tensors_sha256':'3'*64})
        snap['resets'] += 1
        snap['counter'] = 0
        for local in range(count):
            if node == 1 and trigger is None and 7. < snap['qpos'][0] < 8.:
                trigger = {'next_native_step':step+1,'native_prefix_sha256':prefix.hexdigest(),
                    'snapshot':copy.deepcopy(snap),'policy_tensors_sha256':'1'*64,
                    'frame':{'origin':[0.,0.,.8],'yaw':0.},'progress_m':snap['qpos'][0]}
            if node == 1:
                snap['command']=[.5,0.,0.]
                schedules.append({'node_index':1,'time_s':snap['time_s'],
                    'original_progress_m':snap['qpos'][0], 'original_nominal':[.5,0.,0.],
                    'scheduled_nominal':[.5,0.,0.],'arm':'constant'})
            elif node == 2:
                snap['command']=[0.,0.,-.5 if local==0 else 0.]
            snap['counter'] += 1
            step += 1
            before = {'phase':'before','step':step,**copy.deepcopy(snap)}
            rows.append(before)
            if local % 50 == 0:
                trace.append({'node_index':node,'time_s':snap['time_s'],'state_before_command':state(snap),
                              'applied_command':snap['command'].copy()})
            snap['time_s'] = step*.002
            if node == 1:
                snap['qpos'][0] = 8.*(local+1)/count
                snap['qvel'][0] = .5
            if node == 2:
                snap['qpos'][0] = 8.1
                snap['qpos'][3:7] = [math.sqrt(.5),0.,0.,-math.sqrt(.5)]
                snap['qvel'][0] = .05
            after = {'phase':'after','step':step,**copy.deepcopy(snap)}
            rows.append(after)
            for row in (before,after):
                prefix.update(json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
        end = copy.deepcopy(snap)
        bounds.append({'node':node,'phase':'exit','snapshot':end,'policy_tensors_sha256':'2'*64})
        heading = math.degrees(audit.wrap(audit.yaw(end['qpos'][3:7])-audit.yaw(start['qpos'][3:7])))+(90. if node==2 else 0.)
        result = {'skill':audit.SKILLS[node],'parameters':audit.PARAMETERS[node],
            'start_state':state(start),'end_state':state(end),'duration_s':end['time_s']-start['time_s'],
            'forward_progress_m':end['qpos'][0]-start['qpos'][0],'lateral_drift_m':0.,
            'heading_error_deg':heading,'status':'SUCCESS','physical_success':True,
            'strict_success':True,'simulation_steps':count,'envelope':None,
            'skill_metrics':{'elapsed_wall_time_s':.01}}
        if node==1:
            result['envelope'] = audit._env.evaluate_walk_task({'absolute_distance_error_m':0.,
                'lateral_drift_m':0.,'heading_error_deg':0.,'completion_sim_time_s':.6},8.,physical=True)
        nodes.append(result)
    dump(root/'result.json',{'nodes':nodes,'heading_alignment_alpha':.25})
    dump(root/'status.json',{'complete':True,'physical_failure_observed':False,
        'nonfinite_state_observed':False,'technical_errors':[],'archive_errors':[],
        'native_attempts':step,'native_steps_completed':step,
        'reset_events':['constructor_reset','initial_base']})
    dump(root/'boundaries.json',bounds)
    dump(root/'preintervention.json',trigger)
    dump(root/'controller_resets.json',resets)
    (root/'schedule.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in schedules))
    (root/'native.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (root/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in trace))
    after = [r for r in rows if r['phase']=='after']
    np.savez(root/'poses.npz',time_s=[r['time_s'] for r in after],qpos=[r['qpos'] for r in after],
             qvel=[r['qvel'] for r in after],ctrl=[r['ctrl'] for r in after])
    return rows


def rewrite_rows(root, rows):
    (root/'native.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))


def test_complete_native_audit_and_no_runtime_import(tmp_path):
    root = tmp_path/'arm'; fixture(root)
    result = audit.audit(root)
    assert result['passed_integrity'], result['failures']
    assert result['metrics']['strict'] is True
    assert result['metrics']['physical'] is True
    assert result['metrics']['mean_speed'] == pytest.approx(.5)
    assert not {'torch','mujoco'} & sys.modules.keys()


@pytest.mark.parametrize('mutation', ['missing','counter','state','dt','reset','manifest_count','trace','boundary','strict_label'])
def test_reject_raw_integrity_faults(tmp_path, mutation):
    root = tmp_path/'arm'; rows = fixture(root)
    if mutation=='missing':
        del rows[-600:-598]
    elif mutation=='counter': rows[600]['counter'] += 1
    elif mutation=='state': rows[600]['qpos'][0] += .1
    elif mutation=='dt': rows[601]['time_s'] += .001
    elif mutation=='reset': rows[600]['resets'] += 1
    elif mutation=='manifest_count':
        s=json.loads((root/'status.json').read_text());s['native_attempts']+=1;dump(root/'status.json',s)
    elif mutation=='trace':
        t=json.loads((root/'trace.jsonl').read_text().splitlines()[0]);t['state_before_command']['base_position'][0]=9.
        (root/'trace.jsonl').write_text(json.dumps(t)+'\n')
    elif mutation=='boundary':
        b=json.loads((root/'boundaries.json').read_text());b[1]['snapshot']['qvel'][0]=9.;dump(root/'boundaries.json',b)
    else:
        r=json.loads((root/'result.json').read_text());r['nodes'][1]['strict_success']=False;dump(root/'result.json',r)
    rewrite_rows(root,rows)
    result=audit.audit(root)
    assert result['passed_integrity'] is False
    assert result['metrics']['technical'] is True


def test_observed_fall_survives_technical_partial(tmp_path):
    root=tmp_path/'arm'; rows=fixture(root)
    rows[-1]['qpos'][2]=.3
    rewrite_rows(root,rows)
    s=json.loads((root/'status.json').read_text())
    s.update(complete=False,physical_failure_observed=True,technical_errors=['simulated archive interruption'])
    dump(root/'status.json',s)
    result=audit.audit(root)
    assert result['physical_failure_observed'] is True
    assert result['metrics']['physical'] is False
    assert result['technical_or_missing'] is True
    assert result['verdict']=='INCONCLUSIVE'


def test_terminal_speed_window_requires_native_density():
    with pytest.raises(ValueError,match='missing native'):
        audit.window_mean_speed([(0.,.5,0.),(.25,.5,0.),(.5,.5,0.)],.5)


def test_nonfinite_and_truncated_tail_are_preserved(tmp_path):
    root=tmp_path/'arm'; rows=fixture(root)
    rows[-1]['qvel'][0]=float('nan')
    rewrite_rows(root,rows)
    with (root/'native.jsonl').open('a') as stream:
        stream.write('{"unfinished":')
    s=json.loads((root/'status.json').read_text())
    s.update(complete=False,physical_failure_observed=True,nonfinite_state_observed=True,
             technical_errors=['simulated interrupted output'])
    dump(root/'status.json',s)
    result=audit.audit(root)
    assert result['nonfinite_state_observed'] is True
    assert result['physical_failure_observed'] is True
    assert result['metrics']['physical'] is False
    assert result['verdict']=='INCONCLUSIVE'
    assert any('malformed_line' in s for s in result['failures'])


@pytest.mark.parametrize('fault',['formula','not_applied','reset_event','missing_callback'])
def test_schedule_and_reset_faults(tmp_path,fault):
    root=tmp_path/'arm'; rows=fixture(root)
    schedule=[json.loads(s) for s in (root/'schedule.jsonl').read_text().splitlines()]
    if fault=='formula':
        schedule[-1]['scheduled_nominal'][0]=.49
    elif fault=='not_applied':
        rows[5500]['command'][0]=.49;rows[5501]['command'][0]=.49
        rewrite_rows(root,rows)
    elif fault=='missing_callback':
        schedule.pop()
    else:
        resets=json.loads((root/'controller_resets.json').read_text());resets[-1]['counter_before']+=1
        dump(root/'controller_resets.json',resets)
    (root/'schedule.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in schedule))
    result=audit.audit(root)
    assert not result['passed_integrity']
    assert any('schedule:' in s or 'controller_reset:' in s for s in result['failures'])


def test_native_exception_snapshot_retains_observed_failure(tmp_path):
    root=tmp_path/'arm'; rows=fixture(root)
    exceptional=rows.pop()
    exceptional['qpos'][2]=.3
    dump(root/'native_exception_state.json',exceptional)
    rewrite_rows(root,rows)
    s=json.loads((root/'status.json').read_text())
    s.update(complete=False,physical_failure_observed=True,technical_errors=['native exception'])
    s['native_steps_completed']-=1
    dump(root/'status.json',s)
    result=audit.audit(root)
    assert result['physical_failure_observed'] is True
    assert result['fall_observed'] is True
    assert result['metrics']['physical'] is False
    assert result['verdict']=='INCONCLUSIVE'


def test_replay_allows_only_matching_nan_reference_sentinels(tmp_path):
    historical=tmp_path/'history';fixture(historical)
    current=tmp_path/'current';fixture(current)
    for root in (historical,current):
        with np.load(root/'poses.npz') as data:
            payload={k:data[k].copy() for k in data.files}
        payload['reference_heading']=np.full(len(payload['time_s']),np.nan)
        np.savez(root/'poses.npz',**payload)
    assert audit.replay(current,historical)['passed']
    payload['reference_heading'][0]=0.
    np.savez(current/'poses.npz',**payload)
    assert audit.replay(current,historical)['checks']['poses:reference_heading'] is False


def test_replay_retains_simulated_duration_and_ignores_wall_only(tmp_path):
    historical=tmp_path/'history';fixture(historical)
    current=tmp_path/'current';fixture(current)
    r=json.loads((current/'result.json').read_text())
    r['nodes'][0]['skill_metrics']['elapsed_wall_time_s']=123.
    dump(current/'result.json',r)
    assert audit.replay(current,historical)['passed']
    r['nodes'][0]['duration_s']+=.002
    dump(current/'result.json',r)
    assert not audit.replay(current,historical)['passed']


def test_replay_rejects_pose_and_trace_tampering(tmp_path):
    historical=tmp_path/'history';fixture(historical)
    current=tmp_path/'current';fixture(current)
    with np.load(current/'poses.npz') as data:
        payload={k:data[k].copy() for k in data.files}
    payload['ctrl'][0,0]=1.
    np.savez(current/'poses.npz',**payload)
    assert audit.replay(current,historical)['checks']['poses:ctrl'] is False
    t=json.loads((current/'trace.jsonl').read_text().splitlines()[0]);t['node_index']=1
    (current/'trace.jsonl').write_text(json.dumps(t)+'\n')
    assert audit.replay(current,historical)['checks']['trace'] is False
