"""Independent stdlib-only arithmetic audit; does not import the main analyzer.

Run from repository root with .venv/Scripts/python.exe and this file path.
Reads the fixed original archive and exact Git blobs; writes only its sibling JSON.
"""
import hashlib
import json
import math
from pathlib import Path
import subprocess


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    archive = Path('D:/webcodex/mujoco-g1/evidence/language-first-action-20261014')
    index_path = Path('D:/webcodex/mujoco-g1/evidence/language-first-real-6161176858/evidence-index.json')
    index_bytes = index_path.read_bytes()
    assert digest(index_bytes) == 'c3e9a9b9726eaffd14bce07b025ea78c80cbbc5f78ab4811240d282504d99d48'
    index = json.loads(index_bytes)
    checked = {}

    def read(path):
        data = path.read_bytes()
        expected = index['files'][str(path)]
        assert len(data) == expected['bytes'] and digest(data) == expected['sha256'], path
        checked[str(path)] = digest(data)
        return data

    source = json.loads(read(archive / 'freeze/source.json'))
    repo = source['root']
    source_hashes = {}
    for name in ('src/g1swarm/skills/basic.py', 'src/g1swarm/state/robot_state.py',
                 'src/g1swarm/simulation/g1_simulation.py'):
        blob = subprocess.check_output(['git', '-c', 'safe.directory=' + repo,
                                       '-C', repo, 'show', source['C_exec'] + ':' + name])
        retained = (Path(repo) / name).read_bytes()
        assert digest(retained) == source['files'][name], name
        assert retained.replace(b'\r\n', b'\n') == blob.replace(b'\r\n', b'\n'), name
        source_hashes[name] = {'git_blob_sha256': digest(blob),
                              'retained_file_sha256': digest(retained),
                              'CRLF_normalized_content_identical': True}

    run = archive / 'owner-request/runs' / index['run_id']
    events = [json.loads(line) for line in read(run / 'ledger/lang-440cdc04aa405413/events.jsonl').splitlines()]
    summary = next(event for event in events if event['event'] == 'mission_success')
    stop_node = next(node for node in summary['nodes'] if node['skill'] == 'stop')
    stop_count = stop_node['metrics']['simulation_steps']
    start_index = sum(node['metrics']['simulation_steps'] for node in summary['nodes'][:2])
    native = [json.loads(line) for line in read(run / 'native.jsonl').splitlines()]
    post = [row for row in native if 'post' in row]
    assert [row['native_completed'] for row in post] == list(range(1, 6031))
    assert start_index == 5345 and stop_count == 685
    stop = post[start_index:start_index + stop_count]
    speeds = [math.hypot(row['post']['qvel'][0], row['post']['qvel'][1]) for row in stop]
    times = [row['post']['time_s'] for row in stop]
    assert all(math.isfinite(speed) for speed in speeds)
    dt = post[0]['post']['time_s']
    assert dt == .002
    assert all(abs(post[i]['post']['time_s'] - post[i-1]['post']['time_s'] - dt) < 1e-12
               for i in range(1, len(post)))
    window = round(1.0 / dt)
    # Enumerate windows independently; deliberately no rolling accumulator.
    means = [sum(speeds[end-window:end]) / window for end in range(window, len(speeds)+1)]
    first_crossing_end = next(window + offset for offset, mean in enumerate(means) if mean <= .1)
    segments = []
    begin = None
    for offset, speed in enumerate(speeds + [float('inf')]):
        if speed <= .1 and begin is None:
            begin = offset
        if speed > .1 and begin is not None:
            segments.append((begin, offset-1))
            begin = None
    longest = max(segments, key=lambda pair: times[pair[1]] - times[pair[0]])
    lo, hi = longest
    final = speeds[-window:]
    result = {
        'kind': 'INDEPENDENT_RETAINED_DATA_ARITHMETIC_NOT_NEW_QUALIFICATION',
        'run_id': index['run_id'], 'C_exec': source['C_exec'],
        'index_sha256': digest(index_bytes), 'verified_inputs': checked,
        'verified_C_exec_blob_hashes': source_hashes,
        'speed_definition': 'hypot(qvel[0], qvel[1]); horizontal base speed only',
        'stop_native_start_exclusive': start_index, 'stop_native_end_inclusive': start_index + stop_count,
        'stop_post_samples': len(stop), 'window_samples': window,
        'final_window_mean_mps': sum(final) / window,
        'final_window_above_0_1_samples': sum(speed > .1 for speed in final),
        'final_window_above_0_1_fraction': sum(speed > .1 for speed in final) / window,
        'final_speed_mps': speeds[-1],
        'final_window_between_samples_path_m': sum(
            math.hypot(b['post']['qpos'][0]-a['post']['qpos'][0],
                       b['post']['qpos'][1]-a['post']['qpos'][1])
            for a, b in zip(stop[-window:-1], stop[-window+1:])),
        'longest_at_or_below_0_1': {
            'sample_count': hi-lo+1, 'first_native_step': stop[lo]['native_completed'],
            'last_native_step': stop[hi]['native_completed'],
            'first_time_s': times[lo], 'last_time_s': times[hi],
            'sample_span_s': times[hi]-times[lo]},
        'first_mean_crossing': {
            'stop_step': first_crossing_end, 'native_step': start_index+first_crossing_end,
            'time_s': times[first_crossing_end-1],
            'mean_mps': means[first_crossing_end-window],
            'preceding_window_mean_mps': means[first_crossing_end-window-1]},
        'post_success_native_samples': len(post) - (start_index + first_crossing_end),
        'post_success_observed_span_s': post[-1]['post']['time_s'] - times[first_crossing_end-1],
        'conclusion': 'Original sliding-mean success reproduced. Instantaneous low speed and future Hold are not established.'}
    output = Path(__file__).with_name('independent-audit.json')
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ('verified_inputs', 'verified_C_exec_blob_hashes')}, indent=2))


if __name__ == '__main__':
    main()
