"""Independent, read-only native evidence audit. No simulation/model imports.

Recorded success flags are checked against native state and the original pure
envelope evaluator. Partial technical evidence never erases an observed fall.
This module neither authorizes nor runs an experiment.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skill_handoff_001'))
from handoff import speed, window_mean_speed

# Load only this pure original source, not boundary.__init__ and its unrelated
# characterization imports. Its sole project dependency is metrics.schema.
_spec = importlib.util.spec_from_file_location(
    'g1swarm.boundary._handoff_audit_envelope', ROOT / 'src/g1swarm/boundary/envelope.py')
_env = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _env
_spec.loader.exec_module(_env)

PARAMETERS = [
    {'duration_s': 5.0},
    {'max_duration_s': 48.0, 'reset_memory': True, 'speed_mps': .5,
     'target_distance_m': 8.0, 'tolerance_m': .8},
    {'max_duration_s': 10.0, 'settle_s': .5, 'target_angle_deg': -90.0,
     'tolerance_deg': 15.0, 'yaw_rate_radps': .5},
]
SKILLS = ['stand', 'walk_forward', 'turn']
EPS = 1e-9  # arithmetic/timestamp tolerance, not scientific threshold


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def yaw(q):
    w, x, y, z = q
    return math.atan2(2 * (w*z+x*y), 1-2*(y*y+z*z))


def wrap(x):
    return math.atan2(math.sin(x), math.cos(x))


def finite_number(x):
    return type(x) in (int, float) and math.isfinite(x)


def flags(row):
    """Independent copy of frozen simulation height/tilt predicate."""
    q, v = row['qpos'], row['qvel']
    finite = all(finite_number(x) for x in q + v + row['ctrl'])
    if not finite:
        return False, True
    w, x, y, z = q[3:7]
    norm = math.sqrt(w*w+x*x+y*y+z*z)
    if not norm:
        raise ValueError('zero quaternion is invalid evidence')
    tilt = math.degrees(math.acos(max(-1., min(1., 1-2*((x/norm)**2+(y/norm)**2)))))
    return q[2] < .45 or tilt > 65., False


def state_matches(state, snap):
    return (state['simulation_time'] == snap['time_s'] and
            state['base_position'] == snap['qpos'][:3] and
            state['base_orientation'] == snap['qpos'][3:7] and
            state['linear_velocity'] == snap['qvel'][:3] and
            state['angular_velocity'] == snap['qvel'][3:6])


def audit(directory):
    directory = Path(directory)
    errors, hashes = [], {}
    observed_fall = observed_nonfinite = False
    nodes, rows, status = [], [], {}
    node_results = []

    def check(ok, label):
        if not ok and label not in errors:
            errors.append(label)

    def load(name, lines=False):
        path = directory / name
        try:
            hashes[name] = digest(path)
            content = path.read_text(encoding='utf-8')
            if not lines:
                return json.loads(content)
            parsed = []
            for i, line in enumerate(content.splitlines()):
                try:
                    parsed.append(json.loads(line))
                except (ValueError, TypeError):
                    check(False, f'{name}:malformed_line:{i+1}')
                    break
            return parsed
        except (OSError, ValueError, TypeError) as exc:
            check(False, f'{name}:{type(exc).__name__}')
            return [] if lines else {}

    status = load('status.json')
    result = load('result.json' if (directory/'result.json').is_file() else 'partial_nodes.json')
    nodes = result.get('nodes', []) if isinstance(result, dict) else result
    rows = load('native.jsonl', True)
    boundaries = load('boundaries.json')
    pre = load('preintervention.json')
    trace = load('trace.jsonl', True)
    schedules = load('schedule.jsonl', True)
    reset_journal = load('controller_resets.json')
    check(isinstance(nodes, list), 'nodes:list_required')
    if not isinstance(nodes, list):
        nodes = []
    check(isinstance(status, dict), 'status:object_required')
    if not isinstance(status, dict):
        status = {}
    for key in ('complete', 'physical_failure_observed', 'nonfinite_state_observed'):
        check(type(status.get(key)) is bool, f'status:{key}:boolean_required')
    for key in ('technical_errors', 'archive_errors'):
        check(isinstance(status.get(key), list), f'status:{key}:list_required')
    complete = status.get('complete') is True
    technical = bool(status.get('technical_errors') or status.get('archive_errors') or not complete)
    check(status.get('reset_events') == ['constructor_reset', 'initial_base'], 'simulator_reset_identity')
    if complete:
        check(len(nodes) == 3, 'complete_requires_three_nodes')
        check(result.get('heading_alignment_alpha') == .25, 'fixed_alpha_identity')
    before, after = [], []
    pending, previous = None, None
    by_node = {i: [] for i in range(3)}
    by_time = {}
    prefix_hash = hashlib.sha256()
    pre_seen = False
    for offset, row in enumerate(rows):
        try:
            check(row.get('phase') in ('before', 'after'), f'phase:{offset}')
            check(type(row.get('step')) is int and row['step'] >= 1, f'step_type:{offset}')
            check(type(row.get('node')) is int and row['node'] in range(3), f'node:{offset}')
            check(finite_number(row.get('time_s')), f'time:{offset}')
            for key, size in [('qpos',19), ('qvel',18), ('ctrl',12), ('command',3), ('action',12), ('target',12)]:
                if not isinstance(row.get(key), list) or len(row[key]) != size:
                    raise ValueError(f'{key}:shape')
                if key not in ('qpos', 'qvel'):
                    check(all(finite_number(x) for x in row[key]), f'{key}:nonfinite:{offset}')
            fall, nonfinite = flags(row)
            observed_fall |= fall
            observed_nonfinite |= nonfinite
            for key in ('counter', 'resets'):
                check(type(row.get(key)) is int and row[key] >= 0, f'{key}:{offset}')
            if isinstance(pre, dict) and row.get('phase') == 'before' and row['step'] == pre.get('next_native_step'):
                check(pre.get('native_prefix_sha256') == prefix_hash.hexdigest(), 'preintervention:prefix_hash')
                snap = pre['snapshot']
                check(all(snap[k] == row[k] for k in ('qpos','qvel','time_s','node','resets')), 'preintervention:state')
                check(isinstance(pre.get('policy_tensors_sha256'), str) and len(pre['policy_tensors_sha256']) == 64, 'preintervention:policy_digest')
                check(7. < pre['progress_m'] < 8., 'preintervention:trigger')
                pre_seen = True
            if row['phase'] == 'before':
                check(pending is None, 'native:missing_after')
                check(row['step'] == len(before)+1, 'native:attempt_order')
                before.append(row)
                if previous is not None:
                    check(row['time_s'] == previous['time_s'] and row['qpos'] == previous['qpos'] and row['qvel'] == previous['qvel'], 'native:state_discontinuity')
                    check(row['node'] in (previous['node'], previous['node']+1), 'native:node_order')
                    if row['node'] == previous['node']:
                        check(row['counter'] == previous['counter']+1 and row['resets'] == previous['resets'], 'native:controller_discontinuity')
                    else:
                        check(row['counter'] == 1 and row['resets'] == previous['resets']+1, 'native:node_reset_identity')
                else:
                    check(row['node'] == 0 and row['time_s'] == 0. and row['counter'] == 1 and row['resets'] == 1, 'native:initial_identity')
                pending = row
            else:
                check(pending is not None, 'native:orphan_after')
                check(row['step'] == len(after)+1, 'native:completion_order')
                after.append(row)
                if pending is not None:
                    check(row['step'] == pending['step'] and row['node'] == pending['node'], 'native:pair_identity')
                    check(abs(row['time_s']-pending['time_s']-.002) <= EPS, 'native:timestep')
                    check(all(row[k] == pending[k] for k in ('counter','resets','ctrl','command','action','target')), 'native:pair_control_changed')
                by_node[row['node']].append(row)
                previous, pending = row, None
            by_time.setdefault(row['time_s'], []).append(row)
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            check(False, f'native_row:{offset}:{type(exc).__name__}:{exc}')
        # Match NativeLedger's exact canonical bytes, independent of JSONL whitespace.
        prefix_hash.update(json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=True).encode())
    check(len(before) == status.get('native_attempts'), 'native:attempt_count')
    check(len(after) == status.get('native_steps_completed'), 'native:completed_count')
    check(len(before) <= 32000, 'native:budget_exceeded')
    check(len(before)-len(after) in (0,1), 'native:unknown_step_count')
    check(pending is None or technical, 'native:unexplained_unfinished_step')
    check(not complete or len(before) == len(after), 'complete:unfinished_step')
    check(not complete or pre_seen, 'preintervention:missing')
    if (directory/'native_exception_state.json').is_file():
        exceptional = load('native_exception_state.json')
        try:
            fall, nonfinite = flags(exceptional)
            observed_fall |= fall
            observed_nonfinite |= nonfinite
            check(technical and pending is not None, 'native_exception:unexplained_snapshot')
            if pending is not None:
                check(all(exceptional[k] == pending[k] for k in ('node','counter','resets','command','ctrl')),
                      'native_exception:attempt_identity')
        except (KeyError,ValueError,TypeError,IndexError):
            check(False, 'native_exception:malformed')
    check((status.get('nonfinite_state_observed') is True) == observed_nonfinite, 'nonfinite_flag_mismatch')
    if 'native_sha256' in status:
        check(status['native_sha256'] == prefix_hash.hexdigest(), 'native:journal_hash')
    observed_physical = observed_fall or observed_nonfinite
    # Boundaries are captured before original skill reset and after skill return.
    if not isinstance(boundaries, list):
        check(False, 'boundaries:list_required')
        boundaries = []
    if complete:
        check([(b.get('node'),b.get('phase')) for b in boundaries] ==
              [(i,p) for i in range(3) for p in ('entry','exit')], 'boundary:complete_order')
    boundary_map = {}
    for boundary in boundaries:
        try:
            key = boundary['node'], boundary['phase']
            check(key not in boundary_map, 'boundary:duplicate')
            boundary_map[key] = boundary['snapshot']
            check(isinstance(boundary['policy_tensors_sha256'], str) and len(boundary['policy_tensors_sha256']) == 64, 'boundary:policy_digest')
        except (KeyError, TypeError):
            check(False, 'boundary:malformed')
    try:
        origin = boundary_map[1,'entry']['qpos'][:3]
        angle = yaw(boundary_map[1,'entry']['qpos'][3:7])
        check(pre['frame']['origin'] == origin and abs(pre['frame']['yaw']-angle) <= EPS,
              'preintervention:original_frame')
        offset = [pre['snapshot']['qpos'][j]-origin[j] for j in (0,1)]
        check(abs(pre['progress_m']-(math.cos(angle)*offset[0]+math.sin(angle)*offset[1])) <= EPS,
              'preintervention:original_progress')
    except (KeyError,TypeError,ValueError):
        check(False, 'preintervention:missing_frame_or_state')
    # Every existing correction callback is a native Walk command. Validate the
    # declared vx intervention and preserve the original yaw-only correction
    # envelope, without inventing a replacement low-level control calculation.
    walk_before = [r for r in before if r['node'] == 1]
    check(len(schedules) == len(walk_before), 'schedule:callback_coverage')
    declared_arm = None
    for index, (scheduled, native) in enumerate(zip(schedules, walk_before)):
        try:
            arm = scheduled['arm']
            if declared_arm is None:
                declared_arm = arm
            check(arm == declared_arm, 'schedule:mixed_arms')
            if directory.name in ('constant','terminal_schedule'):
                check(arm == directory.name, 'schedule:directory_arm')
            frame = boundary_map[1,'entry']
            angle = yaw(frame['qpos'][3:7])
            dx, dy = [native['qpos'][j]-frame['qpos'][j] for j in (0,1)]
            progress = math.cos(angle)*dx+math.sin(angle)*dy
            # Native MissionFrame uses a NumPy dot; the independent scalar
            # projection above may differ by roundoff. Check that projection
            # within the frozen arithmetic tolerance, then replay the declared
            # schedule exactly at its recorded argument.
            expected = speed(scheduled['original_progress_m'], arm)
            check(scheduled['node_index'] == 1 and scheduled['time_s'] == native['time_s'], 'schedule:callback_identity')
            check(abs(scheduled['original_progress_m']-progress) <= EPS, 'schedule:original_progress')
            check(scheduled['original_nominal'] == [.5,0.,0.], 'schedule:original_nominal')
            check(scheduled['scheduled_nominal'] == [expected,0.,0.], 'schedule:formula')
            check(native['command'][:2] == [expected,0.] and abs(native['command'][2]) <= .6,
                  'schedule:applied_command_bounds')
        except (KeyError,TypeError,ValueError,IndexError):
            check(False, f'schedule:{index}:malformed')
    try:
        if not isinstance(reset_journal, list):
            raise ValueError('reset list missing')
        check(len(reset_journal) > 0, 'controller_reset:empty')
        constructor = reset_journal[0]
        check(constructor == {'node':-1,'step':0,'counter_before':0,'counter_after':0},
              'controller_reset:constructor_identity')
        expected = []
        for i in range(3):
            if (i,'entry') in boundary_map:
                b = boundary_map[i,'entry']
                first = next((r for r in before if r['node']==i), None)
                if first is not None:
                    expected.append({'node':i,'step':first['step']-1,
                                     'counter_before':b['counter'],'counter_after':0})
        projected = [{k:r.get(k) for k in ('node','step','counter_before','counter_after')} for r in reset_journal[1:]]
        check(projected == expected, 'controller_reset:skill_identity')
        for reset in reset_journal[1:]:
            b = boundary_map[reset['node'],'entry']
            snap = reset['post_reset_snapshot']
            check(all(snap[k] == b[k] for k in ('qpos','qvel','ctrl','time_s','command','node','resets')),
                  'controller_reset:physical_continuity')
            check(snap['counter'] == 0 and snap['action'] == [0.]*12,
                  'controller_reset:counter_action')
            check(isinstance(reset['policy_tensors_sha256'], str) and len(reset['policy_tensors_sha256']) == 64,
                  'controller_reset:policy_digest')
    except (KeyError,TypeError,ValueError,IndexError):
        check(False, 'controller_reset:malformed')
    for i, node in enumerate(nodes):
        try:
            start, end = boundary_map[i,'entry'], boundary_map[i,'exit']
            check(node['skill'] == SKILLS[i] and node['parameters'] == PARAMETERS[i], f'node:{i}:frozen_semantics')
            check(state_matches(node['start_state'], start) and state_matches(node['end_state'], end), f'node:{i}:state_boundary')
            selected = by_node[i]
            first = next(r for r in before if r['node'] == i)
            last = selected[-1]
            for key in ('time_s','qpos','qvel'):
                check(start[key] == first[key] and end[key] == last[key], f'node:{i}:native_boundary:{key}')
            check(first['resets'] == start['resets']+1 and last['resets'] == end['resets'], f'node:{i}:reset_boundary')
            duration = end['time_s']-start['time_s']
            angle = yaw(start['qpos'][3:7])
            dx, dy = (end['qpos'][j]-start['qpos'][j] for j in (0,1))
            forward = math.cos(angle)*dx+math.sin(angle)*dy
            lateral = -math.sin(angle)*dx+math.cos(angle)*dy
            relative_heading = math.degrees(wrap(yaw(end['qpos'][3:7])-angle))
            heading = relative_heading-(-90. if i == 2 else 0.)
            for key, computed in [('duration_s',duration),('forward_progress_m',forward),('lateral_drift_m',lateral),('heading_error_deg',heading)]:
                check(finite_number(node[key]) and abs(node[key]-computed) <= EPS, f'node:{i}:derived:{key}')
            node_fall = any(flags(r)[0] for r in selected+[first])
            node_nonfinite = any(flags(r)[1] for r in selected+[first])
            physical = _env.physical_success(fallen=node_fall, finite=not node_nonfinite,
                skill_status=node['status'], simulation_completed=True)
            strict = node['status'] == 'SUCCESS' and physical
            if i == 0:
                check(node['status'] != 'SUCCESS' or abs(duration-5.) <= EPS, 'stand:duration_identity')
            elif i == 1:
                envelope = _env.evaluate_walk_task({'absolute_distance_error_m':abs(forward-8.),
                    'lateral_drift_m':lateral,'heading_error_deg':heading,'completion_sim_time_s':duration}, 8., physical=physical)
                strict &= envelope['strict_success']
                check(node['status'] != 'SUCCESS' or forward >= 8., 'walk:premature_success')
                check(duration <= 48.+EPS, 'walk:duration_cap')
                check(node['envelope']['strict_success'] == envelope['strict_success'], 'walk:envelope_mismatch')
            else:
                crossed = [r for r in selected if abs(math.degrees(wrap(yaw(r['qpos'][3:7])-angle))) >= 90.]
                if node['status'] == 'SUCCESS':
                    check(bool(crossed) and abs(heading) <= 15., 'turn:invalid_success')
                    if crossed:
                        check(abs(end['time_s']-crossed[0]['time_s']-.5) <= EPS, 'turn:settle_duration')
                check(duration <= 10.5+EPS, 'turn:duration_cap')
            check(node['physical_success'] is physical, f'node:{i}:physical_label')
            check(node['strict_success'] == strict and type(node['strict_success']) is bool, f'node:{i}:strict_label')
            check(node['simulation_steps'] == len(selected), f'node:{i}:step_count')
            node_results.append({'node':i,'physical':physical,'strict':strict,
                                 'duration_s':duration if finite_number(duration) else None})
        except (KeyError, ValueError, TypeError, IndexError, StopIteration) as exc:
            check(False, f'node:{i}:{type(exc).__name__}:{exc}')
    observed_physical |= any(n['physical'] is False for n in node_results)
    check((status.get('physical_failure_observed') is True) == observed_physical, 'physical_failure_flag_mismatch')
    check(not complete or bool(trace), 'trace:complete_but_empty')
    if complete:
        expected_trace = [(r['node'],r['time_s']) for r in before if (r['counter']-1)%50 == 0]
        check([(r.get('node_index'),r.get('time_s')) for r in trace] == expected_trace,
              'trace:original_callback_coverage')
    # Boundary snapshots account for initial time-zero ctrl before first compute.
    pose_candidates = {t:list(rs) for t,rs in by_time.items()}
    for snap in boundary_map.values():
        try:
            pose_candidates.setdefault(snap['time_s'], []).append(snap)
        except (KeyError, TypeError):
            check(False, 'boundary:missing_time')
    for i, row in enumerate(trace):
        try:
            candidates = by_time.get(row['time_s'], [])
            check(any(state_matches(row['state_before_command'], r) for r in candidates), f'trace:{i}:state_not_native')
            check(any(r['phase']=='before' and r['node']==row['node_index'] and
                      r['command']==row['applied_command'] for r in candidates), f'trace:{i}:applied_command_not_native')
        except (KeyError, TypeError):
            check(False, f'trace:{i}:malformed')
    try:
        path = directory/'poses.npz'
        hashes['poses.npz'] = digest(path)
        with np.load(path, allow_pickle=False) as pose:
            times = pose['time_s']
            check(len(times) > 0, 'poses:empty')
            check(all(b > a for a,b in zip(times,times[1:])), 'poses:time_order')
            for i, t in enumerate(times):
                check(any(np.array_equal(pose['qpos'][i], r['qpos']) and
                          np.array_equal(pose['qvel'][i], r['qvel']) and
                          np.array_equal(pose['ctrl'][i], r['ctrl']) for r in pose_candidates.get(float(t),[])), f'poses:{i}:state_not_native')
    except (OSError, KeyError, ValueError, IndexError, TypeError) as exc:
        check(False, f'poses:{type(exc).__name__}')
    metrics = {'complete':complete, 'physical':False if observed_physical else (all(n['physical'] for n in node_results) if len(node_results)==3 else None),
               'strict':False if any(n['strict'] is False for n in node_results) else (True if len(node_results)==3 else None),
               'technical':bool(technical or errors)}
    try:
        walk = boundary_map[1,'exit']; turn = boundary_map[2,'exit']
        start = boundary_map[1,'entry']
        samples = [(start['time_s'], *start['qvel'][:2])] + [(r['time_s'], *r['qvel'][:2]) for r in by_node[1]]
        metrics.update(exit_speed=math.hypot(*walk['qvel'][:2]),
            mean_speed=window_mean_speed(samples, walk['time_s']),
            walk_world_norm=math.hypot(walk['qpos'][0]-8., walk['qpos'][1]),
            turn_world_norm=math.hypot(turn['qpos'][0]-8., turn['qpos'][1]),
            turn_x=turn['qpos'][0]-8., turn_y=turn['qpos'][1],
            turn_heading=wrap(yaw(turn['qpos'][3:7])+math.pi/2),
            duration=turn['time_s']-boundary_map[0,'entry']['time_s'])
    except (ValueError, KeyError, TypeError):
        check(False, 'metrics:incomplete_native_window_or_boundary')
        metrics['technical'] = True
    for key, value in list(metrics.items()):
        if type(value) is float and not math.isfinite(value):
            metrics[key] = None
            metrics['technical'] = True
            check(False, f'metrics:{key}:nonfinite')
    return {'passed_integrity':not errors, 'metrics':metrics, 'failures':errors,
            'physical_failure_observed':observed_physical,
            'fall_observed':observed_fall,'nonfinite_state_observed':observed_nonfinite,
            'technical_or_missing':bool(technical or errors),
            'verdict':'INCONCLUSIVE' if technical or errors else 'RAW_AUDIT_COMPLETE',
            'nodes':node_results,'source_hashes':hashes}


def _scientific(value):
    if isinstance(value, dict):
        return {k:_scientific(v) for k,v in value.items() if k not in ('wall_time_s','elapsed_wall_time_s')}
    if isinstance(value, list):
        return [_scientific(v) for v in value]
    return value


def replay(directory, history):
    """Zero-tolerance first-three-node historical replay; no outcome relabeling."""
    directory, history = Path(directory), Path(history)
    if (history/'fixed').is_dir():
        history /= 'fixed'
    checks, hashes = {}, {}
    try:
        current = json.loads((directory/'result.json').read_text())
        prior = json.loads((history/'result.json').read_text())
        checks['alpha'] = current.get('heading_alignment_alpha') == prior.get('heading_alignment_alpha') == .25
        checks['nodes'] = len(current['nodes']) == 3 and _scientific(current['nodes']) == _scientific(prior['nodes'][:3])
        end = prior['nodes'][2]['end_state']['simulation_time']
        oldtrace = [json.loads(s) for s in (history/'trace.jsonl').read_text().splitlines()]
        newtrace = [json.loads(s) for s in (directory/'trace.jsonl').read_text().splitlines()]
        checks['trace'] = _scientific(newtrace) == _scientific([r for r in oldtrace if r['node_index'] < 3])
        with np.load(history/'poses.npz', allow_pickle=False) as old, np.load(directory/'poses.npz', allow_pickle=False) as new:
            checks['pose_columns'] = set(old.files) == set(new.files)
            mask = old['time_s'] <= end
            count = int(mask.sum())
            checks['pose_samples'] = len(new['time_s']) in (count,count+1)
            for key in old.files:
                checks[f'poses:{key}'] = key in new.files and old[key].dtype == new[key].dtype and np.array_equal(old[key][mask], new[key][:count], equal_nan=True)
            checks['optional_terminal'] = len(new['time_s']) == count or (len(new['time_s']) == count+1 and new['time_s'][-1] == end)
        for prefix, root in [('new',directory), ('history',history)]:
            for name in ('result.json','trace.jsonl','poses.npz'):
                hashes[f'{prefix}/{name}'] = digest(root/name)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        checks[f'exception:{type(exc).__name__}:{exc}'] = False
    return {'passed':bool(checks) and all(checks.values()), 'checks':checks,'source_hashes':hashes,
            'historical_native_coverage':'unavailable; retained samples only, not every-native equivalence'}
