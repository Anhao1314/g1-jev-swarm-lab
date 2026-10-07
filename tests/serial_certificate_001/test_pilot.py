"""Offline tests for single scheduler, fixed configuration and first evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import threading

import pytest

from scripts.serial_certificate_001 import run_pilot as run
from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer
from g1swarm.glm_preflight_001 import GLMChatConfig
from g1swarm.glm_preflight_001.chat_backend import GLMChatCompletionsBackend
from g1swarm.llm.backend import LLMBackendError

KEY = 'synthetic-offline-serial-secret'
CERTIFICATE = {'status': 'AUTHORIZED_UNIQUE', 'checks': ['U'] * 7,
               'plan': run.approved.EXPECTED_PLAN, 'issues': []}


def config() -> GLMChatConfig:
    return GLMChatConfig(run.approved.BASE_URL, KEY, response_format_json_object=True)


def wire(content=None):
    return {'id': 'offline-serial-first', 'model': run.MODEL,
        'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
            'role': 'assistant', 'content': json.dumps(CERTIFICATE) if content is None else content,
            'reasoning_content': 'private reasoning never persisted'}}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 200, 'total_tokens': 300,
            'completion_tokens_details': {'reasoning_tokens': 150}}}


def issue(backend):
    return SourceAuthorityCertificateIssuer(backend).issue_certificate(run.approved.SOURCE)


def rows_fixture(tmp_path, monkeypatch, count=3):
    prior = next(copy.deepcopy(value) for _, value in run.dd.original_rows() if value['B']['score']['released'])
    inputs, by_id = {'rows': []}, {}
    for index in range(count):
        row = copy.deepcopy(prior)
        row['sample']['sample_id'] = f'fictional-serial-{index}'
        row['sample']['source'] = run.approved.SOURCE
        item = {'population': row['sample']['population'], 'sample_id': row['sample']['sample_id'],
            'source_sha256': run.sha(row['sample']['source'].encode('utf8')), 'eligible_B_candidate': True}
        inputs['rows'].append(item)
        by_id[item['sample_id']] = row
    monkeypatch.setattr(run, 'BASE', tmp_path)
    monkeypatch.setattr(run, 'verify_history', lambda item: by_id[item['sample_id']])
    return inputs, by_id


def test_serial_requests_have_maximum_one_active_and_preserve_original_order(tmp_path, monkeypatch):
    inputs, _ = rows_fixture(tmp_path, monkeypatch)
    main_thread = threading.get_ident()
    state = {'active': 0, 'maximum': 0, 'calls': 0}

    def post(self, payload):
        # This also fails if a later implementation silently uses a thread pool.
        assert threading.get_ident() == main_thread
        state['active'] += 1
        state['maximum'] = max(state['maximum'], state['active'])
        assert state['active'] == 1
        state['calls'] += 1
        state['active'] -= 1
        return wire()

    monkeypatch.setattr(GLMChatCompletionsBackend, '_post', post)
    run.collect_rows(inputs, config(), resume=False, run_id='offline-one-scheduler')
    assert state == {'active': 0, 'maximum': 1, 'calls': 3}
    timings = [run.read(tmp_path / 'acquisition' / f"{item['population']}--{item['sample_id']}" / 'timing.json')
               for item in inputs['rows']]
    assert [value['serial_sequence'] for value in timings] == [1, 2, 3]
    assert all(t['workers'] == 1 and t['called'] for t in timings)
    assert all(left['finished_monotonic_ns'] <= right['started_monotonic_ns']
               for left, right in zip(timings, timings[1:]))
    assert all(t['started_monotonic_ns'] <= t['finished_monotonic_ns'] for t in timings)


@pytest.mark.parametrize('workers', [0, 2, 4, True])
def test_only_one_worker_accepted_before_any_provider_or_filesystem_action(monkeypatch, workers):
    monkeypatch.setattr(run, 'scheduler_lock', lambda: (_ for _ in ()).throw(AssertionError('must reject first')))
    with pytest.raises(ValueError, match='exactly one worker'):
        run.collect(workers)


def test_full_wire_payload_and_fixed_retry_schedule_equal_historical_dg4(tmp_path, monkeypatch):
    seen, delays = [], []
    def post(self, payload):
        seen.append(payload)
        if len(seen) == 1:
            raise LLMBackendError('API_ERROR', 'offline 429', retryable=True,
                context={'category': 'HTTP', 'reason': 'HTTP_STATUS', 'http_status': 429})
        if len(seen) == 2:
            raise LLMBackendError('API_ERROR', 'offline network', retryable=True,
                context={'category': 'TRANSPORT', 'reason': 'NETWORK_ERROR'})
        return wire(content='unusable semantic output')

    monkeypatch.setattr(GLMChatCompletionsBackend, '_post', post)
    monkeypatch.setattr(run.time, 'sleep', delays.append)
    backend = run.GLMJournalBackend(config(), tmp_path)
    outcome = issue(backend)
    assert not outcome.usable and outcome.reason_code == 'MALFORMED_CERTIFICATE_RESPONSE'
    assert delays == [0.5, 1.0]
    assert len(seen) == 3 and seen[0] == seen[1] == seen[2]
    request = run.read(tmp_path / 'request.json')
    system_prompt = (run.ROOT / 'prompts/authority_certificate_v2.txt').read_text('utf8')
    expected = GLMChatCompletionsBackend(config())._payload(system_prompt,
        json.dumps({'source': run.approved.SOURCE}, ensure_ascii=False, separators=(',', ':')))
    assert request['payload'] == expected
    assert request['request_sha256'] == run.sha(run.historical._canonical(expected))
    assert request['payload']['max_tokens'] == 4096 and request['payload']['temperature'] == 0
    assert request['payload']['thinking'] == {'type': 'enabled'}
    assert 'workers' not in expected and 'concurrency' not in expected and 'reasoning_effort' not in expected
    assert backend.evidence()['provider_calls'] == 1 and backend.evidence()['provider_attempts'] == 3
    assert [event['status'] for event in backend.events] == ['API_ERROR', 'API_ERROR', 'SUCCESS']


def test_first_request_file_bytes_equal_historical_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post', lambda self, payload: wire())
    old_backend = run.historical.GLMJournalBackend(config(), tmp_path / 'old')
    new_backend = run.GLMJournalBackend(config(), tmp_path / 'serial')
    assert issue(old_backend).usable and issue(new_backend).usable
    assert (tmp_path / 'old/request.json').read_bytes() == (tmp_path / 'serial/request.json').read_bytes()
    saved = '\n'.join(path.read_text('utf8') for path in (tmp_path / 'serial').glob('*.json'))
    assert KEY not in saved and run.sha(KEY.encode('utf8')) not in saved
    assert 'private reasoning never persisted' not in saved


def test_approved_profile_and_dg4_settings_immutable(monkeypatch, tmp_path):
    # The real configuration check is offline and validates the preflight receipt.
    monkeypatch.setattr(run, 'BASE', tmp_path)
    protocol = run.read(run.historical.BASE / 'protocol.json')
    protocol['workers'] = 1
    run.write(tmp_path / 'protocol.json', protocol)
    assert run.validate_configuration(config())['configuration_match']
    altered = GLMChatConfig(run.approved.BASE_URL, KEY, max_network_retries=1, response_format_json_object=True)
    with pytest.raises(ValueError, match='configuration drift'):
        run.validate_configuration(altered)
    protocol['provider']['thinking'] = {'type': 'disabled'}
    (tmp_path / 'protocol.json').unlink()
    run.write(tmp_path / 'protocol.json', protocol)
    with pytest.raises(ValueError, match='provider protocol differs'):
        run.validate_configuration(config())


def test_frozen_runner_snapshot_drift_rejected(tmp_path, monkeypatch):
    runner = tmp_path / 'runner.py'
    runner.write_bytes(b'fixed runner bytes\n')
    base = tmp_path / 'pilot'
    base.mkdir()
    (base / 'acquisition_runner_snapshot.py').write_bytes(runner.read_bytes())
    run.write(base / 'inputs.json', {'prior_tracked_files': []})
    frozen = {'runner.py': run.sha(runner.read_bytes())}
    run.write(base / 'acquisition_binding.json', {'workers': 1, 'starting_commit': run.STARTING_COMMIT,
        'acquisition_hashes': frozen})
    monkeypatch.setattr(run, '__file__', str(runner))
    monkeypatch.setattr(run, 'BASE', base)
    monkeypatch.setattr(run, 'verify_prior', lambda inputs: None)
    monkeypatch.setattr(run, 'binding', lambda: {'runner.py': run.sha(runner.read_bytes())})
    assert run.verify_prepared()['acquisition_hashes'] == frozen
    runner.write_bytes(b'mutated runner bytes\n')
    with pytest.raises(ValueError, match='frozen acquisition runner'):
        run.verify_prepared()


def test_frozen_acquisition_input_binding_drift_rejected(tmp_path, monkeypatch):
    runner = tmp_path / 'runner.py'
    runner.write_bytes(b'fixed\n')
    base = tmp_path / 'pilot'
    base.mkdir()
    (base / 'acquisition_runner_snapshot.py').write_bytes(runner.read_bytes())
    run.write(base / 'inputs.json', {'prior_tracked_files': []})
    run.write(base / 'acquisition_binding.json', {'workers': 1, 'starting_commit': run.STARTING_COMMIT,
        'acquisition_hashes': {'input.json': 'frozen'}})
    monkeypatch.setattr(run, '__file__', str(runner))
    monkeypatch.setattr(run, 'BASE', base)
    monkeypatch.setattr(run, 'verify_prior', lambda inputs: None)
    monkeypatch.setattr(run, 'binding', lambda: {'input.json': 'mutated'})
    with pytest.raises(ValueError, match='pre-scored acquisition binding'):
        run.verify_prepared()


def test_historical_dg4_unsafe_bytes_tamper_rejected(tmp_path, monkeypatch):
    sample = {'population': 'ood', 'sample_id': 'ood-m-031', 'source': 'already seen unsafe source'}
    run.write(tmp_path / 'v1.json', {'sample': sample, 'B': {'unchanged': True}})
    item = {'population': 'ood', 'sample_id': 'ood-m-031', 'source_sha256': run.sha(sample['source'].encode()),
        'v1_sample_path': 'v1.json', 'v1_sample_sha256': run.sha((tmp_path / 'v1.json').read_bytes()),
        'dd_sample_path': 'dd.json', 'eligible_B_candidate': True}
    run.write(tmp_path / 'dd.json', {'input_binding': {'v1_sample_sha256': item['v1_sample_sha256']}})
    item['dd_sample_sha256'] = run.sha((tmp_path / 'dd.json').read_bytes())
    run.write(tmp_path / 'dg4.json', {'input_binding': item, 'dg': {'score': {'released': True}}})
    complete = {**item, 'dg_sample_path': 'dg4.json', 'dg_sample_sha256': run.sha((tmp_path / 'dg4.json').read_bytes())}
    monkeypatch.setattr(run, 'ROOT', tmp_path)
    assert run.verify_history(complete)['sample'] == sample
    with (tmp_path / 'dg4.json').open('ab') as handle:
        handle.write(b'\n')
    with pytest.raises(ValueError, match='historical source/B/DD/DG4 evidence changed: dg'):
        run.verify_history(complete)


def test_resume_reuses_saved_first_response_and_preserves_timing_without_new_call(tmp_path, monkeypatch):
    inputs, _ = rows_fixture(tmp_path, monkeypatch, count=1)
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post', lambda self, payload: wire())
    run.collect_rows(inputs, config(), resume=False, run_id='original')
    item = inputs['rows'][0]
    output = tmp_path / 'samples' / f"{item['population']}--{item['sample_id']}.json"
    directory = tmp_path / 'acquisition' / f"{item['population']}--{item['sample_id']}"
    original_stage = run.read(output)['dg_serial']
    timing_bytes = (directory / 'timing.json').read_bytes()
    # Lose derived stage and sample; the saved first response must be replayed.
    output.unlink()
    (directory / 'stage_result.json').unlink()
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post',
        lambda *args: (_ for _ in ()).throw(AssertionError('semantic reissue forbidden')))
    run.collect_rows(inputs, config(), resume=True, run_id='resume')
    recovered = run.read(output)['dg_serial']
    assert recovered['recovered'] and recovered['live_evidence']['recovered_without_new_call']
    assert recovered['score'] == original_stage['score']
    assert recovered['result']['status'] == original_stage['result']['status']
    assert recovered['result']['mission'] == original_stage['result']['mission']
    left = recovered['result']['diagnostics']['source_authorization']
    right = original_stage['result']['diagnostics']['source_authorization']
    assert left['status'] == right['status'] and left['reason_code'] == right['reason_code']
    for field in ('certificate', 'raw_response', 'raw_response_sha256', 'usage', 'request_parameters'):
        assert left['diagnostics'][field] == right['diagnostics'][field]
    assert (directory / 'timing.json').read_bytes() == timing_bytes


def test_skip_rows_never_call_verifier_and_have_no_schedule_timing(tmp_path, monkeypatch):
    from g1swarm.language.errors import CompilerStatus
    from g1swarm.language.result import CompilerResult
    result = CompilerResult(CompilerStatus.MALFORMED, normalized_text='fictional')
    sample = {'population': 'controlled', 'sample_id': 'fictional-skip', 'source': 'fictional',
        'expected_status': 'MALFORMED', 'expected_mission': None}
    item = {'population': sample['population'], 'sample_id': sample['sample_id'], 'eligible_B_candidate': False}
    monkeypatch.setattr(run, 'BASE', tmp_path)
    monkeypatch.setattr(run, 'verify_history', lambda _: {'sample': sample, 'B': {'result': result.to_dict()}})
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post',
        lambda *args: (_ for _ in ()).throw(AssertionError('skipped B cannot call provider')))
    run.collect_rows({'rows': [item]}, config(), resume=False, run_id='offline')
    saved = run.read(tmp_path / 'samples/controlled--fictional-skip.json')['dg_serial']
    assert saved['result'] == result.to_dict() and saved['live_evidence']['provider_calls'] == 0
    assert not (tmp_path / 'acquisition').exists()


def test_scheduler_lock_rejects_another_invocation_and_releases_on_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(run, 'BASE', tmp_path)
    with run.scheduler_lock():
        with pytest.raises(ValueError, match='already active'):
            with run.scheduler_lock():
                raise AssertionError('second scheduler entered')
    with run.scheduler_lock():
        pass
