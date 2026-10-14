"""Synthetic archives only: no simulation, policy, renderer, or model assets."""
import http.client
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from console.language_v01.saved_results import SavedArchive, build_server, canonical, sha


@pytest.fixture
def archive(tmp_path):
    evidence = tmp_path / 'evidence'
    request_id, run_id = 'a' * 32, 'b' * 32
    directory = evidence / 'runs' / run_id
    files = {}

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = value if isinstance(value, bytes) else json.dumps(value, indent=2).encode()
        path.write_bytes(data)
        files[str(path.resolve())] = {'bytes': len(data), 'sha256': sha(data)}
        return sha(data)

    mission = {'mission_id': 'synthetic-only', 'steps': []}
    request = {'request_id': request_id, 'mission': mission,
               'source': {'text': 'synthetic', 'sha256': sha(b'synthetic')}}
    request['binding'] = {'request_sha256': sha(canonical(request)), 'mission_sha256': sha(canonical(mission))}
    request['contract_sha256'] = sha(canonical(request))
    write(evidence / (request_id + '.json'), request)
    readiness = tmp_path / 'readiness.json'
    readiness_sha = write(readiness, {})
    review = tmp_path / 'review.json'
    review_sha = write(review, {'passed': True})
    p = {'request_id': request_id, 'request': request, 'mission': mission,
         'mission_sha256': sha(canonical(mission)), 'contract_sha256': request['contract_sha256'],
         'evidence_root': str(evidence), 'C_exec': 'c' * 40, 'readiness_sha256': readiness_sha,
         'protocol_sha256': 'd' * 64, 'budget': {'native_steps': 15000}}
    p['preparation_sha256'] = sha(canonical(p))
    prep = evidence / (request_id + '-preparation.json')
    write(prep, p)
    context = {'C_exec': p['C_exec'], 'preparation_sha256': p['preparation_sha256']}
    launch = {**context, 'run_id': run_id, 'preparation': str(prep), 'readiness': str(readiness),
              'readiness_sha256': readiness_sha, 'review': str(review), 'review_sha256': review_sha,
              'owner_comment_id': 123}
    write(directory / 'launch.json', launch)
    raw = {'native_attempt': 1, 'native_completed': 1, 'post': {'qpos': [1.0]},
           'policy_attempt': 1, 'policy_completed': 1}
    raw_sha = write(directory / 'native.jsonl', canonical(raw) + b'\n')
    initial_sha = write(directory / 'initial-state.json', {})
    result = {'mission_id': mission['mission_id'], 'mission_success': True, 'completed_nodes': 3,
              'nodes': [{}, {}, {}], 'simulation_steps_executed': 1}
    result_sha = write(directory / 'result.json', result)
    pose_sha = write(directory / 'poses.npz', b'synthetic-pose-not-numpy')
    physical = {**context, 'request_id': request_id, 'kind': 'NEW_MUJOCO_CAPTURE',
                'executed_mission_sha256': p['mission_sha256'], 'runtime_result': result,
                'native_attempts': 1, 'native_completed': 1, 'policy_inference_attempts': 1,
                'policy_inference_completed': 1, 'startup_reset_requests': 2, 'post_checkpoint_reset_requests': 0,
                'physical_failure': {'fallen': False, 'nonfinite': False}, 'status': 'COMPLETED',
                'technical_errors': [], 'archival_errors': [],
                'files': {'native.jsonl': raw_sha, 'initial-state.json': initial_sha, 'result.json': result_sha,
                          'poses.npz': pose_sha}}
    physical_sha = write(directory / 'physical.json', physical)
    process = {'passed': True, 'reaped': True, 'tree_empty': True, 'timed_out': False}
    for name in ('worker-process', 'outer-process', 'render-process'):
        write(directory / name / 'process_receipt.json', process)
    write(directory / 'completion.json', {**context, 'request_id': request_id, 'run_id': run_id,
                                         'physical_sha256': physical_sha, 'status': 'CAPTURE_FINISHED',
                                         'process': process, 'outer_process': process, 'render_process': process})
    video_sha = write(directory / 'video.mp4', b'0123456789')
    write(directory / 'media.json', {**context, 'request_id': request_id,
          'executed_mission_sha256': p['mission_sha256'], 'source_physical_sha256': physical_sha,
          'source_result_sha256': result_sha, 'new_capture': True, 'historical_fallback': False,
          'file': 'video.mp4', 'renderer': {'video_sha256': video_sha, 'source_pose_sha256': pose_sha,
                                         'frames': 1, 'fps': 20}})
    owner = {'id': 123, 'body': 'synthetic-comment'}
    write(directory / 'owner-source.json', owner)
    write(directory / 'authorization.json', {'preparation_sha256': p['preparation_sha256'], 'comment_id': 123,
          'accepted_independent_review_sha256': review_sha, 'raw_sha256': sha(canonical(owner)),
          'url': 'https://github.com/example/repo/issues/1#issuecomment-123', 'assurance': 'synthetic-only',
          'original_language_proposal': 'DENY', 'language_runtime': 'BLOCKED', 'd011': 'BLOCKED'})
    consumed = {'run_id': run_id, 'owner_comment_id': 123, 'preparation_sha256': p['preparation_sha256']}
    write(evidence / 'owner-consumed' / ('request-' + request_id + '.json'), consumed)
    write(evidence / 'owner-consumed' / 'comment-123.json', consumed)
    index = tmp_path / 'index.json'

    def seal():
        index.write_bytes(canonical({'schema': 'additive-execution-closeout/1', 'run_id': run_id, 'files': files}))
        return SavedArchive(index, sha(index.read_bytes()), request_id)

    return seal(), directory, write, seal


def test_restart_and_canonical_owner_binding(archive):
    a, _, _, _ = archive
    first, video = a.read()
    restarted = SavedArchive(a.index, a.index_sha256, a.request_id).read()[0]
    assert first == restarted
    assert video == b'0123456789'
    assert first['authority']['consumed'] is True
    assert first['authority']['language_runtime'] == 'BLOCKED'


@pytest.mark.parametrize('name', ['video.mp4', 'native.jsonl', 'result.json', 'completion.json'])
def test_tamper_after_success_rejects(archive, name):
    a, directory, _, _ = archive
    a.read()
    with (directory / name).open('ab') as stream:
        stream.write(b' ')
    with pytest.raises(ValueError, match='ARCHIVE_BYTES_CHANGED'):
        a.read()


def test_missing_and_unpinned_required_file(archive):
    a, directory, _, _ = archive
    (directory / 'video.mp4').unlink()
    with pytest.raises(OSError):
        a.read()


def test_wrong_request_and_index_rejected(archive):
    a, _, _, _ = archive
    with pytest.raises(ValueError, match='REQUEST_NOT_UNIQUELY_PINNED'):
        SavedArchive(a.index, a.index_sha256, 'f' * 32).read()
    with pytest.raises(ValueError, match='ARCHIVE_INDEX_CHANGED'):
        SavedArchive(a.index, '0' * 64, a.request_id).read()


@pytest.mark.parametrize('filename,key,value', [
    ('completion.json', 'request_id', 'f' * 32),
    ('physical.json', 'executed_mission_sha256', '0' * 64),
    ('authorization.json', 'raw_sha256', '0' * 64),
    ('launch.json', 'C_exec', 'f' * 40),
])
def test_self_resealed_cross_binding_rejected(archive, filename, key, value):
    _, directory, write, seal = archive
    path = directory / filename
    document = json.loads(path.read_bytes())
    document[key] = value
    write(path, document)
    with pytest.raises(ValueError):
        seal().read()


def test_http_read_only_and_range(archive):
    a, directory, _, _ = archive
    server = build_server(a.index, a.index_sha256, a.request_id, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        status, data, response_headers = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return status, data, response_headers

    try:
        assert request('GET', '/')[0] == 200
        assert request('GET', '/api/result')[0] == 200
        assert request('POST', '/api/requests')[0] == 405
        assert request('GET', '/../../result.json')[0] == 404
        assert request('GET', '/api/result?path=secret')[0] == 404
        assert request('GET', '/api/result', {'Host': 'evil.example'})[0] == 403
        status, data, headers = request('GET', '/video', {'Range': 'bytes=2-5'})
        assert status == 206 and data == b'2345'
        assert headers['Content-Range'] == 'bytes 2-5/10'
        assert request('GET', '/video', {'Range': 'bytes=200-'})[0] == 416
        assert request('GET', '/video', {'Range': 'bytes=1-2,4-5'})[0] == 416
        (directory / 'video.mp4').write_bytes(b'corrupt')
        assert request('GET', '/api/result')[0] == 409
        assert request('GET', '/video')[0] == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_import_does_not_load_physics_or_policy():
    completed = subprocess.run([sys.executable, '-B', '-c',
        "import sys; import console.language_v01.saved_results; "
        "assert not {'torch','mujoco','stable_baselines3', 'g1swarm.language_v01.physical', "
        "'g1swarm.language_v01.host'} & set(sys.modules)"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr.decode()
