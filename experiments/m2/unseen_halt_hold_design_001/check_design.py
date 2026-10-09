"""Nonphysical design checks and illustrative classification; not an acquisition adapter."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def blob(ref, path):
    return subprocess.check_output(['git','show',ref+':'+path],cwd=ROOT)


def force_at_pre_step(push, step):
    if push is None:
        return (0.0,0.0,0.0)
    start = push['native_pre_step_start_index']
    active = start <= step < start + push['native_intervals_if_walk_reaches_window_end']
    return tuple(push['force_n']*v if active else 0.0 for v in push['direction_world'])


def descriptor(state):
    """Remove global XY/yaw; no world-frame claim about raw rotational qvel."""
    q, v = state['qpos'], state['qvel']
    if len(q)!=19 or len(v)!=18 or not all(math.isfinite(x) for x in q+v):
        raise ValueError('Incomplete/nonfinite physical descriptor; novelty is unavailable')
    w,x,y,z = q[3:7]
    n = math.sqrt(w*w+x*x+y*y+z*z)
    if n == 0: raise ValueError('Invalid quaternion')
    w,x,y,z = (a/n for a in (w,x,y,z))
    yaw = math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
    c,s = math.cos(yaw), math.sin(yaw)
    return {'joint_position':q[7:], 'joint_velocity':v[6:], 'height':q[2],
            'body_linear_velocity':[c*v[0]+s*v[1],-s*v[0]+c*v[1],v[2]],
            'gravity_direction':[2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)],
            'rotational_speed_norm':math.sqrt(sum(a*a for a in v[3:6]))}


def state_difference(left, right, thresholds):
    a,b = descriptor(left),descriptor(right)
    rms = lambda key: math.sqrt(sum((x-y)**2 for x,y in zip(a[key],b[key]))/len(a[key]))
    angle = math.degrees(math.acos(max(-1,min(1,sum(x*y for x,y in zip(a['gravity_direction'],b['gravity_direction']))))))
    values = {'joint_position_rms_difference_rad':rms('joint_position'),
              'joint_velocity_rms_difference_radps':rms('joint_velocity'),
              'base_body_linear_velocity_l2_difference_mps':math.dist(a['body_linear_velocity'],b['body_linear_velocity']),
              'base_gravity_direction_angle_difference_deg':angle,
              'base_height_absolute_difference_m':abs(a['height']-b['height']),
              'freejoint_rotational_speed_norm_absolute_difference_radps':abs(a['rotational_speed_norm']-b['rotational_speed_norm'])}
    return {'deltas':values,'operationally_distinct':any(v>=thresholds[k] for k,v in values.items())}


def campaign_decision(spec, rows):
    """Synthetic contract logic only; actual raw-data scorer must be frozen later."""
    planned = [c['id'] for c in spec['cells_in_order']]
    if [r['cell_id'] for r in rows] != planned:
        raise ValueError('All frozen cells must appear in order, including NOT_RUN')
    for r in rows:
        if r.get('status')!='VALID': continue
        branch=r.get('parent_branch')
        if branch=='STRICT_TRIGGER' and r.get('halt') not in ('SUCCEEDED','FAILED'):
            raise ValueError('Strict trigger without actual Halt is routing-integrity failure')
        if branch in ('STRICT_PASS_NO_HALT','SKILL_OR_PHYSICAL_FAILURE_NO_HALT') and (
                r.get('halt')!='NOT_REQUESTED' or r.get('hold')!='NOT_RUN'):
            raise ValueError('Never force Halt/Hold in a challenge nontrigger branch')
        if branch=='NORMAL_STOP' and r.get('halt')!='NOT_REQUESTED':
            raise ValueError('Normal Stop is not an independently requested failure Halt')
        if r.get('halt')=='FAILED' and r.get('hold')!='NOT_RUN':
            raise ValueError('Failed Halt must not dispatch Hold')
    new = set(spec['required_primary_cells']+spec['secondary_unseen_cells'])
    valid = [r for r in rows if r.get('status')=='VALID' and r.get('integrity_valid',True)]
    counterexamples = []
    condition_negatives = []
    for r in valid:
        if r['cell_id'] not in new: continue
        halt_failed = r.get('halt')=='FAILED'
        hold_failed = r.get('halt')=='SUCCEEDED' and r.get('hold')=='FAILED'
        if halt_failed or hold_failed:
            distinct = r.get('request_distinct',False) and (halt_failed or r.get('hold_entry_distinct',False))
            (counterexamples if distinct else condition_negatives).append(r['cell_id'])
    complete = len(valid)==len(planned)
    problems = [r['cell_id'] for r in rows if r not in valid or
                r.get('parent_branch')=='SKILL_OR_PHYSICAL_FAILURE_NO_HALT' or
                not r.get('control_valid',True)]
    primary_ok = all(any(r['cell_id']==p and r.get('parent_branch')=='STRICT_TRIGGER' and
                         r.get('halt')=='SUCCEEDED' and r.get('hold')=='SUCCEEDED' and
                         r.get('request_distinct') and r.get('hold_entry_distinct') and
                         r.get('distinct_from_other_primary') for r in valid)
                     for p in spec['required_primary_cells'])
    secondary_ok = all(r.get('parent_branch')=='STRICT_PASS_NO_HALT' or
                       (r.get('parent_branch')=='STRICT_TRIGGER' and r.get('halt')=='SUCCEEDED' and r.get('hold')=='SUCCEEDED')
                       for r in valid if r['cell_id'] in spec['secondary_unseen_cells'])
    controls={r['cell_id']:r for r in valid if r['cell_id'] not in new}
    controls_ok=(len(controls)==3 and
                 controls['seen_no_push_anchor'].get('parent_branch')=='STRICT_TRIGGER' and
                 controls['seen_no_push_anchor'].get('halt')=='SUCCEEDED' and controls['seen_no_push_anchor'].get('hold')=='SUCCEEDED' and
                 controls['seen_plus_y_early_control'].get('parent_branch')=='STRICT_PASS_NO_HALT' and
                 controls['normal_stop_control'].get('parent_branch')=='NORMAL_STOP' and controls['normal_stop_control'].get('hold')=='SUCCEEDED')
    if counterexamples:
        signal='BOUNDED_UNSEEN_COUNTEREXAMPLE'
    elif complete and not problems and not condition_negatives and controls_ok and primary_ok and secondary_ok:
        signal='BOUNDED_PRIMARY_PAIR_SUPPORTED'
    else:
        signal='INCONCLUSIVE_COVERAGE_OR_TECHNICAL'
    requested = [r for r in valid if r.get('parent_branch')=='STRICT_TRIGGER' and r.get('halt') in ('SUCCEEDED','FAILED')]
    hold_eligible = [r for r in requested if r.get('halt')=='SUCCEEDED']
    return {'scientific_signal':signal,'campaign_completion':'COMPLETE' if complete else 'PARTIAL',
            'counterexamples':counterexamples,'condition_negatives_not_distinct':condition_negatives,
            'seen_or_control_physical_negatives':[r['cell_id'] for r in valid if r['cell_id'] not in new and (r.get('halt')=='FAILED' or r.get('hold')=='FAILED')],
            'coverage_or_integrity_problems':problems,
            'failure_chain_halt_denominator':len(requested),
            'failure_chain_hold_denominator':len(hold_eligible),
            'halt_success_fraction':None if not requested else sum(r['halt']=='SUCCEEDED' for r in requested)/len(requested),
            'hold_success_fraction':None if not hold_eligible else sum(r.get('hold')=='SUCCEEDED' for r in hold_eligible)/len(hold_eligible)}


def validate(spec=None):
    if 'mujoco' in sys.modules or 'torch' in sys.modules:
        raise ValueError('Design checker must not import simulator or policy runtime')
    spec = read(HERE/'protocol.json') if spec is None else spec
    binding = read(HERE/'source_binding.json')
    for path,expected in binding['files'].items():
        if hashlib.sha256(blob(binding['baseline_commit'],path)).hexdigest()!=expected:
            raise ValueError('Historical Git source/hash mismatch: '+path)
    m24 = json.loads(blob(binding['baseline_commit'],'experiments/m2/cross_state_reliability_001/protocol.json'))
    m25 = json.loads(blob(binding['baseline_commit'],'experiments/m2/post_halt_hold_design_001/protocol.json'))
    halt = json.loads(blob(binding['baseline_commit'],'experiments/m2/post_failure_halt_001/protocol.json'))
    assert spec['baseline_main_commit']==binding['baseline_commit']
    assert spec['physics_authorized'] is False and spec['execution_adapter_implemented'] is False
    assert spec['scientific_result']=='UNMEASURED_NO_PHYSICS'
    assert spec['layer2_halt']['stop_skill_parameters']==halt['stop_skill_parameters']
    assert spec['layer2_halt']['acceptance']==halt['acceptance']
    assert spec['layer3_hold']['contract']==m25['hold']
    assert spec['layer3_hold']['continuity']==m25['continuity_and_integrity']
    expected=[('seen_no_push_anchor',None,None),('unseen_minus_y_early',-1,500),
              ('unseen_minus_y_late',-1,2000),('unseen_plus_y_late_partner',1,2000),
              ('seen_plus_y_early_control',1,500),('normal_stop_control',None,None)]
    assert len(spec['cells_in_order'])==6
    for cell,(id,sign,start) in zip(spec['cells_in_order'],expected):
        assert cell['id']==id and cell['attempts']==1 and cell['seed']==0
        assert cell['max_native_steps']==30000 and cell['max_wall_s']==120
        assert cell['future_outcome']=='UNMEASURED'
        assert cell['mission']==(m24['normal_control'] if id=='normal_stop_control' else m24['states'][0]['parent_mission'])
        push=cell['push']
        if sign is None: assert push is None
        else:
            assert push['force_n']==60 and push['direction_world']==[0,sign,0]
            assert push['duration_s']==.2 and push['relative_first_walk_trigger_s']==start*.002
            assert push['native_pre_step_start_index']==start and push['native_intervals_if_walk_reaches_window_end']==100
            assert push['frame']=='world' and push['body']=='pelvis' and push['random_trigger'] is False
            active=[n for n in range(2201) if force_at_pre_step(push,n)!=(0,0,0)]
            assert active==list(range(start,start+100))
    b=spec['budget']
    assert b['maximum_cells']==6 and b['attempts_per_cell']==1
    assert b['maximum_native_steps_total']==180000 and b['maximum_wall_s_total']==720
    assert b['max_native_steps_per_cell']==30000 and b['max_wall_s_per_cell']==120
    for seconds in b['conservative_skill_time_bounds_s'].values(): assert seconds/.002 <30000
    assert b['conservative_skill_time_bounds_s']=={'challenge_parent_no_halt_complete':50.5,'challenge_failure_halt_hold':42.0,'normal_parent_and_hold':40.5}
    import yaml
    timing=yaml.safe_load(blob(binding['baseline_commit'],'configs/experiments/oracle_mission_runtime_001.yaml'))['skill_parameters']
    walk6=max(timing['walk_forward']['timeout_min_s'],6*timing['walk_forward']['timeout_s_per_m'])
    walk4=max(timing['walk_forward']['timeout_min_s'],4*timing['walk_forward']['timeout_s_per_m'])
    turn=timing['turn']['max_duration_s']+timing['turn']['settle_s']
    stop=timing['stop']['max_duration_s']
    assert walk6+turn+stop==50.5
    assert walk6+halt['acceptance']['max_duration_s']+m25['hold']['duration_s']==42.0
    assert walk4+turn+stop+m25['hold']['duration_s']==40.5
    assert spec['required_primary_cells']==['unseen_minus_y_early','unseen_minus_y_late']
    assert spec['secondary_unseen_cells']==['unseen_plus_y_late_partner']
    assert set(spec['state_distinctness']['features'])==set(state_difference({'qpos':[0,0,.8,1,0,0,0]+[0]*12,'qvel':[0]*18},{'qpos':[0,0,.8,1,0,0,0]+[0]*12,'qvel':[0]*18},spec['state_distinctness']['features'])['deltas'])
    return {'status':'CANDIDATE_DESIGN_CHECK_PASS_NO_PHYSICS','baseline_commit':binding['baseline_commit'],
            'source_git_bindings_verified':len(binding['files']),'cells':6,'max_native_steps':180000,
            'physics_policy_calls':0,'acquisition_readiness':False,'result':'UNMEASURED',
            'reason':'Design only; experiment adapter/executable/assets/dependencies/readiness freeze and Owner authorization are separate gates.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(validate(),indent=2,sort_keys=True))
