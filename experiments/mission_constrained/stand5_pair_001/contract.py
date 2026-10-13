"""Stdlib-only comparison and budget contract; no simulation imports."""
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HISTORY = ROOT / 'experiments/phase3b/decision_benchmark_acquisition_001/evidence_attempt02/runs/02--phase3b0a-stand5-16m--continue--primary'
# Only publication identity and measured wall duration are excluded. In particular
# alpha, active, commands, scores, policy configuration and resets stay comparable.
TOP_METADATA = {'run_id', 'probe_id', 'repetition', 'phase', 'provenance'}
WALL_FIELDS = {'wall_time_s', 'elapsed_wall_time_s'}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write('\n')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def rows(path):
    path = Path(path)
    raw = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
    return [json.loads(line) for line in raw.splitlines()]

def comparable(value, *, top=True):
    if isinstance(value, dict):
        return {k: comparable(v, top=False) for k, v in value.items()
                if k not in WALL_FIELDS and not (top and k in TOP_METADATA)}
    if isinstance(value, list):
        return [comparable(v, top=False) for v in value]
    return value

def exact(a, b):
    """No float tolerance or bool/number coercion in historical replay."""
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)

def replay_checks(run):
    # ndarray import only reads retained/new archive bytes; never builds a model.
    import numpy as np
    run = Path(run)
    checks = {
        'record': exact(comparable(read(run/'result.json')), comparable(read(HISTORY/'result.json'))),
        'trace': exact(comparable(rows(run/'trace.jsonl')), comparable(rows(HISTORY/'trace.jsonl.gz'))),
        'decisions': exact(rows(run/'decisions.jsonl'), rows(HISTORY/'decisions.jsonl.gz')),
        'predecision': exact(read(run/'predecision.json'), read(HISTORY/'predecision.json')),
        'audit': exact(read(run/'audit.json'), read(HISTORY/'audit.json')),
        'no_disturbance': exact(read(run/'disturbance_events.json'), []),
    }
    with np.load(run/'poses.npz', allow_pickle=False) as a, np.load(HISTORY/'poses.npz', allow_pickle=False) as b:
        checks['poses'] = set(a.files) == set(b.files) and all(
            a[k].dtype == b[k].dtype and a[k].shape == b[k].shape and
            # NaN is an explicit non-Walk reference sentinel in the old observer.
            np.array_equal(a[k], b[k], equal_nan=True) for k in a.files)
    return {'checks': checks, 'passed': all(checks.values()), 'float_tolerance': 0}

def paired_entry(a, b):
    # Walking control reference differs by design. Physical and policy entry do not.
    fields = ('simulation_time_s', 'qpos', 'qvel', 'ctrl', 'robot_state',
              'planned_origin', 'planned_heading_rad', 'policy_tensors_sha256',
              'push_active', 'applied_force_clear')
    return all(k in a and k in b and exact(a[k], b[k]) for k in fields) and a['push_active'] is False and a['applied_force_clear'] is True

class Budget:
    def __init__(self, deadline, clock=time.perf_counter, maximum=40000):
        self.deadline, self.clock, self.maximum = deadline, clock, maximum
        self.steps = 0
    def before_step(self):
        if self.clock() >= self.deadline or self.steps >= self.maximum:
            raise RuntimeError('FROZEN_BUDGET_EXHAUSTED')
    def completed_step(self):
        self.steps += 1

def physical_failure(nodes):
    return any(n.get('physical_success') is False for n in nodes)

def compare_outcomes(selected, fixed):
    from copy import deepcopy
    a, b = deepcopy(selected), deepcopy(fixed)
    valid = lambda r: (len(r.get('nodes', [])) == 7 and r.get('physical_success') is True
                      and all(n.get('strict_success') is True for n in r['nodes']))
    if not valid(a) or not valid(b):
        return {'verdict': 'NO_JOINT_SUPPORT', 'reason': 'original_strict_or_physical_gate'}
    def metrics(r):
        # Original ordered targets derive from the immutable commanded route.
        pos, heading, norms = [0., 0.], 0., []
        for n in r['nodes']:
            if n['skill'] == 'walk_forward':
                d = n['parameters']['target_distance_m']
                pos = [pos[0]+d*math.cos(heading), pos[1]+d*math.sin(heading)]
            elif n['skill'] == 'turn':
                heading += math.radians(n['parameters']['target_angle_deg'])
            if n['skill'] in ('walk_forward', 'turn'):
                p = n['end_state']['base_position']
                norms.append(math.hypot(p[0]-pos[0], p[1]-pos[1]))
        p = r['final_state']['base_position']
        return norms + [abs(p[0]-pos[0]), abs(p[1]-pos[1]), abs(r['nodes'][-1]['ideal_path_heading_error_deg'])]
    improvement = b['ideal_endpoint_error_m']-a['ideal_endpoint_error_m']
    ma, mb = metrics(a), metrics(b)
    no_cost = len(ma) == len(mb) and all(x <= y+1e-9 for x,y in zip(ma,mb))
    return {'verdict': 'SEEN_CONDITION_SUPPORT' if improvement >= .01 and no_cost else 'NO_JOINT_SUPPORT',
            'endpoint_improvement_m': improvement, 'all_route_components_no_worse': no_cost,
            'selected_components': ma, 'fixed_components': mb, 'generalization': 'NOT_TESTED'}
