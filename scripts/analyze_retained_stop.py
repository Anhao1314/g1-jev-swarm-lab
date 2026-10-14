"""Read-only diagnostics for the pinned first language capture; stdlib only.

Never imports the robot package, executes source, rescores a mission, or grants
authority. The profile deliberately supports one retained capture and criterion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

INDEX_SHA = 'c3e9a9b9726eaffd14bce07b025ea78c80cbbc5f78ab4811240d282504d99d48'
RUN = 'e709447a946f45e1b91b25942319e178'
REQUEST = '5404feae6d3b449ab1e1dfbb53cdd387'
C_EXEC = '2faa98481e64b7a0289dff94884a8f7672902177'
DT, WINDOW_S, THRESHOLD = 0.002, 1.0, 0.10
SOURCE_FILES = (
    'src/g1swarm/skills/basic.py', 'src/g1swarm/state/robot_state.py',
    'src/g1swarm/mission/live_session.py', 'src/g1swarm/language_v01/physical.py',
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def summarize_samples(samples):
    """Describe Stop post-step samples using the unchanged retained criterion.

    Consecutive sample spans are descriptive, not continuous-time guarantees.
    Window means use the original left-to-right sum order (not a running sum).
    """
    n = round(WINDOW_S / DT)
    require(len(samples) >= n, 'INCOMPLETE_STOP_WINDOW')
    for i, row in enumerate(samples):
        require(finite(row['time']) and finite(row['speed']) and row['speed'] >= 0,
                'NONFINITE_OR_NEGATIVE_SAMPLE')
        require(len(row['xy']) == 2 and all(finite(v) for v in row['xy']), 'INVALID_POSITION')
        if i:
            require(abs(row['time'] - samples[i-1]['time'] - DT) < 1e-9, 'SAMPLE_GAP')
    speeds = [r['speed'] for r in samples]
    means = [sum(speeds[i-n:i]) / n for i in range(n, len(samples)+1)]
    passing = [i+n-1 for i, value in enumerate(means) if value <= THRESHOLD]
    first = passing[0] if passing else None
    tail = samples[-n:]
    longest, current = 0, 0
    for row in tail:
        current = current + 1 if row['speed'] <= THRESHOLD else 0
        longest = max(longest, current)
    return {
        'criterion': {'window_s': WINDOW_S, 'window_samples': n,
                      'speed_threshold_mps': THRESHOLD, 'native_timestep_s': DT,
                      'speed_definition': 'horizontal hypot(vx, vy)'},
        'stop_samples': len(samples),
        'first_passing_sample_1based': None if first is None else first+1,
        'first_passing_time_s': None if first is None else samples[first]['time'],
        'full_windows_observed': len(means), 'passing_windows_observed': len(passing),
        'final_window_mean_mps': means[-1],
        'previous_window_mean_mps': means[-2] if len(means) > 1 else None,
        'final_window_margin_mps': THRESHOLD - means[-1],
        'final_instantaneous_speed_mps': speeds[-1],
        'final_window_above_threshold_samples': sum(r['speed'] > THRESHOLD for r in tail),
        'final_window_min_speed_mps': min(r['speed'] for r in tail),
        'final_window_max_speed_mps': max(r['speed'] for r in tail),
        'final_window_longest_at_or_below_samples': longest,
        'final_window_longest_at_or_below_sample_span_s': max(0, longest-1)*DT,
        'final_window_sample_span_s': tail[-1]['time']-tail[0]['time'],
        'final_window_between_samples_path_m': sum(math.dist(a['xy'], b['xy'])
                                                  for a, b in zip(tail, tail[1:])),
        'post_first_pass_observed_samples': None if first is None else len(samples)-first-1,
        'post_first_pass_observed_span_s': None if first is None else samples[-1]['time']-samples[first]['time'],
        'interpretation': 'DESCRIPTIVE_SAMPLES_ONLY_NOT_HOLD_QUALIFICATION',
    }


def read_samples(raw):
    """Cross-check native post state and the state actually returned to the skill."""
    posts, states, attempts, policies, policy_done = {}, {}, [], [], []
    for line in raw.splitlines():
        row = json.loads(line)
        if 'native_attempt' in row:
            attempts.append(row['native_attempt'])
        if 'policy_attempt' in row:
            policies.append(row['policy_attempt'])
        if 'policy_completed' in row:
            policy_done.append(row['policy_completed'])
        if 'post' in row:
            counter = row['native_completed']
            require(counter not in posts, 'DUPLICATE_NATIVE_POST')
            posts[counter] = row['post']
        # The native_observation rows duplicate states; do not double count them.
        if 'state' in row and 'native_completed' in row:
            counter = row['native_completed']
            require(counter not in states, 'DUPLICATE_SKILL_STATE')
            states[counter] = row['state']
    sequence = list(range(1, len(posts)+1))
    require(list(posts) == sequence and list(states) == sequence and attempts == sequence,
            'NATIVE_SEQUENCE_MISMATCH')
    require(policies == list(range(1, len(policies)+1)) and policies == policy_done,
            'POLICY_SEQUENCE_MISMATCH')
    samples = []
    for counter in sequence:
        p, s = posts[counter], states[counter]
        require(p['time_s'] == s['simulation_time'] and p['qpos'][:3] == s['base_position']
                and p['qvel'][:3] == s['linear_velocity'], 'RAW_STATE_MISMATCH')
        require(finite(p['time_s']) and abs(p['time_s'] - counter*DT) < 1e-8,
                'NATIVE_TIME_MISMATCH')
        require(all(finite(v) for v in p['qpos'] + p['qvel']), 'NONFINITE_RAW')
        require(s['fallen'] is False, 'RETAINED_FALL')
        samples.append({'step': counter, 'time': s['simulation_time'],
                        'speed': math.hypot(*s['linear_velocity'][:2]),
                        'xy': s['base_position'][:2], 'skill': s['active_skill']})
    return samples, len(policies)


def analyze(index_path):
    index_bytes = Path(index_path).read_bytes()
    require(sha(index_bytes) == INDEX_SHA, 'INDEX_PIN_MISMATCH')
    index = json.loads(index_bytes)
    require(index['run_id'] == RUN, 'RUN_MISMATCH')
    # Consume the exact bytes hashed here, never reopen a file for calculation.
    archive = {}
    for name, pin in index['files'].items():
        data = Path(name).read_bytes()
        require(len(data) == pin['bytes'] and sha(data) == pin['sha256'], 'ARCHIVE_BYTES_CHANGED:'+name)
        archive[name.replace('\\', '/')] = data

    def get(suffix):
        matches = [v for k, v in archive.items() if k.endswith('/'+suffix)]
        require(len(matches) == 1, 'INPUT_NOT_UNIQUE:'+suffix)
        return matches[0]

    source = json.loads(get('freeze/source.json'))
    require(source['C_exec'] == C_EXEC, 'SOURCE_COMMIT_MISMATCH')
    source_pins = {}
    for name in SOURCE_FILES:
        data = (Path(source['root']) / name).read_bytes()
        require(sha(data) == source['files'][name], 'SOURCE_BYTES_CHANGED:'+name)
        source_pins[name] = sha(data)
    preparation = json.loads(get(REQUEST+'-preparation.json'))
    physical = json.loads(get(RUN+'/physical.json'))
    result = json.loads(get(RUN+'/result.json'))
    require(preparation['C_exec'] == physical['C_exec'] == C_EXEC and
            preparation['request_id'] == physical['request_id'] == REQUEST and
            preparation['preparation_sha256'] == physical['preparation_sha256'] and
            preparation['mission_sha256'] == physical['executed_mission_sha256'], 'REQUEST_BINDING_MISMATCH')
    require(result == physical['runtime_result'], 'RESULT_RECEIPT_MISMATCH')
    for name in ('result.json', 'native.jsonl'):
        require(sha(get(RUN+'/'+name)) == physical['files'][name], 'PHYSICAL_FILE_MISMATCH')
    mission = preparation['mission']
    require([s['skill'] for s in mission['steps']] == ['stand', 'walk_forward', 'stop']
            and mission['steps'][-1]['parameters'] == {}, 'UNSUPPORTED_MISSION_PROFILE')
    samples, policy_count = read_samples(get(RUN+'/native.jsonl'))
    require(len(samples) == physical['native_completed'] == result['simulation_steps_executed']
            and policy_count == physical['policy_inference_completed'], 'RESULT_COUNTER_MISMATCH')
    offset = 0
    for node in result['nodes']:
        count = node['metrics']['simulation_steps']
        require(type(count) is int and 0 < count <= len(samples)-offset
                and all(s['skill'] == node['skill'] for s in samples[offset:offset+count]),
                'NODE_SEGMENT_MISMATCH')
        offset += count
    require(offset == len(samples), 'NODE_COVERAGE_MISMATCH')
    stop = [s for s in samples if s['skill'] == 'stop']
    metrics = summarize_samples(stop)
    require(metrics['first_passing_sample_1based'] == len(stop), 'FIRST_PASS_END_MISMATCH')
    node = result['nodes'][-1]['metrics']
    require(node['skill_status'] == 'SUCCESS' and abs(node['final_speed_mps']-stop[-1]['speed']) < 1e-12,
            'STOP_RESULT_MISMATCH')
    return {
        'schema': 'retained-stop-diagnostics/1', 'status': 'VERIFIED_RETAINED_DIAGNOSTICS',
        'run_id': RUN, 'request_id': REQUEST, 'C_exec': C_EXEC,
        'index_sha256': INDEX_SHA, 'indexed_files_verified': len(archive),
        'analyzer_sha256': sha(Path(__file__).read_bytes()),
        'preparation_sha256': preparation['preparation_sha256'],
        'mission_sha256': preparation['mission_sha256'],
        'protocol_sha256': preparation['protocol_sha256'],
        'policy_sha256': node['policy_hash'],
        'source_contract_hashes': source_pins,
        'native_sha256': sha(get(RUN+'/native.jsonl')),
        'result_sha256': sha(get(RUN+'/result.json')),
        'retained_native_steps': len(samples), 'retained_policy_calls': policy_count,
        'original_mission_success': result['mission_success'], 'original_stop_status': node['skill_status'],
        'diagnostics': metrics,
        'post_success_hold': 'NOT_OBSERVED', 'adaptive_handoff_qualification': 'NOT_ESTABLISHED',
        'authority': 'UNCHANGED_D011_BLOCKED_CONSUMED_GRANT_NOT_REUSABLE',
        'current_execution': {'native_steps': 0, 'policy_calls': 0, 'training': False},
        'scope': 'ONE_RETAINED_RUN_DESCRIPTIVE_ANALYSIS_NOT_RESCORE_OR_GENERALIZATION',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', required=True, type=Path)
    args = parser.parse_args()
    try:
        report = analyze(args.index)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
