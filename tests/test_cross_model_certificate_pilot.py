"""Offline first-response, blindness, transport accounting and secret boundaries."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_cross_model_certificate_pilot as run
from g1swarm.glm_preflight_001 import GLMChatConfig
from g1swarm.glm_preflight_001.chat_backend import GLMChatCompletionsBackend
from g1swarm.llm.backend import LLMBackendError, LLMConfigurationError
from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer

KEY = 'synthetic-private-api-key-unique'
CERTIFICATE = {'status': 'AUTHORIZED_UNIQUE', 'checks': ['U'] * 7,
               'plan': [['stand', 3.0], ['stop']], 'issues': []}


def config() -> GLMChatConfig:
    return GLMChatConfig(run.approved.BASE_URL, KEY, response_format_json_object=True)


def wire(*, content=None, reasoning='private reasoning must never be saved', finish='stop'):
    return {'id': 'fictional-response', 'model': run.MODEL,
        'choices': [{'index': 0, 'finish_reason': finish, 'message': {
            'role': 'assistant', 'content': json.dumps(CERTIFICATE) if content is None else content,
            'reasoning_content': reasoning}}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 4096 if finish == 'length' else 200,
            'total_tokens': 4196 if finish == 'length' else 300,
            'completion_tokens_details': {'reasoning_tokens': 4000 if finish == 'length' else 150}}}


def issue(backend):
    return SourceAuthorityCertificateIssuer(backend).issue_certificate(run.approved.SOURCE)


def test_actual_first_payload_hash_is_source_only_and_recomputable(tmp_path, monkeypatch):
    seen = []
    def post(self, payload):
        seen.append(payload)
        return wire()
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post', post)
    backend = run.GLMJournalBackend(config(), tmp_path)
    outcome = issue(backend)
    assert outcome.usable
    assert outcome.certificate.to_dict() == CERTIFICATE
    request = run.read(tmp_path / 'request.json')
    payload = request['payload']
    assert payload == seen[0]
    assert set(json.loads(payload['messages'][1]['content'])) == {'source'}
    assert json.loads(payload['messages'][1]['content'])['source'] == run.approved.SOURCE
    assert 'reasoning_effort' not in payload
    assert payload['thinking'] == {'type': 'enabled'}
    assert payload['max_tokens'] == 4096 and payload['temperature'] == 0
    assert request['request_sha256'] == run.sha(run._canonical(payload))
    assert run.read(tmp_path / 'attempt-01-begin.json')['request_sha256'] == request['request_sha256']
    assert backend.evidence()['provider_calls'] == backend.evidence()['provider_attempts'] == 1
    with pytest.raises(LLMBackendError):
        backend.complete(system_prompt='unused', user_text='{}')


def test_reasoning_text_not_persisted_or_hashed_but_presence_and_usage_remain(tmp_path, monkeypatch):
    reasoning = 'PRIVATE_REASONING_TOKEN_SEQUENCE'
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post', lambda self, payload: wire(reasoning=reasoning))
    backend = run.GLMJournalBackend(config(), tmp_path)
    assert issue(backend).usable
    saved = '\n'.join(path.read_text('utf8') for path in tmp_path.glob('*.json'))
    assert reasoning not in saved and KEY not in saved
    message = run.read(tmp_path / 'attempt-01-end.json')['provider_document']['choices'][0]['message']
    assert message['reasoning_content'] is None
    assert message['reasoning_content_present'] is True
    assert message['reasoning_content_chars'] == len(reasoning)
    response = run.read(tmp_path / 'response.json')
    assert response['request_parameters']['adapter_response_metadata']['reasoning_content_chars'] == len(reasoning)
    assert response['usage']['output_tokens_details']['reasoning_tokens'] == 150


def test_empty_assistant_exhaustion_keeps_safe_error_accounting(tmp_path, monkeypatch):
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post',
                        lambda self, payload: wire(content='', finish='length'))
    backend = run.GLMJournalBackend(config(), tmp_path)
    outcome = issue(backend)
    assert not outcome.usable and outcome.reason_code == 'BACKEND_FAILURE'
    assert backend.evidence()['provider_attempts'] == 1
    response = run.read(tmp_path / 'response.json')
    assert response['context']['reason'] == 'NO_FINAL_ASSISTANT_CONTENT'
    assert response['context']['provider_status'] == 'incomplete'
    assert response['context']['finish_reason'] == 'length'
    assert response['context']['usage']['total_tokens'] == 4196
    assert response['context']['usage']['output_tokens_details']['reasoning_tokens'] == 4000
    assert response['context']['reasoning_content_chars'] > 0
    assert run.read(tmp_path / 'attempt-01-end.json')['status'] == 'SUCCESS'


@pytest.mark.parametrize('location', ['final', 'reasoning', 'id', 'unknown'])
def test_credential_echo_rejected_before_wire_hash_or_persistence(tmp_path, monkeypatch, location):
    document = wire()
    if location == 'final':
        document['choices'][0]['message']['content'] = KEY
    elif location == 'reasoning':
        document['choices'][0]['message']['reasoning_content'] = KEY
    elif location == 'id':
        document['id'] = KEY
    else:
        document['unexpected'] = {'data': KEY}
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post', lambda self, payload: document)
    outcome = issue(run.GLMJournalBackend(config(), tmp_path))
    assert not outcome.usable
    end = run.read(tmp_path / 'attempt-01-end.json')
    assert end['error_context']['reason'] == 'CREDENTIAL_ECHO'
    assert 'provider_document' not in end
    saved = '\n'.join(path.read_text('utf8') for path in tmp_path.glob('*.json'))
    assert KEY not in saved
    assert run.sha(KEY.encode()) not in saved


def test_transport_only_retry_attempts_one_to_three_no_semantic_retry(tmp_path, monkeypatch):
    attempts = []
    def post(self, payload):
        attempts.append(payload)
        if len(attempts) <= 2:
            raise LLMBackendError('TIMEOUT', 'safe synthetic timeout', retryable=True,
                                  context={'category': 'TIMEOUT', 'reason': 'TIMEOUT'})
        return wire(content='invalid semantic output')
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post', post)
    monkeypatch.setattr(run.time, 'sleep', lambda _: None)
    backend = run.GLMJournalBackend(config(), tmp_path)
    outcome = issue(backend)
    assert not outcome.usable and outcome.reason_code == 'MALFORMED_CERTIFICATE_RESPONSE'
    assert len(attempts) == 3
    assert backend.evidence()['provider_calls'] == 1
    assert backend.evidence()['provider_attempts'] == 3
    assert [event['status'] for event in backend.events] == ['TIMEOUT', 'TIMEOUT', 'SUCCESS']
    assert len(list(tmp_path.glob('attempt-*-begin.json'))) == 3
    assert len(list(tmp_path.glob('attempt-*-end.json'))) == 3


def test_durable_interruption_never_reissues_semantic_call(tmp_path, monkeypatch):
    run.write(tmp_path / 'started.json', {'started': True, 'model': run.MODEL})
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post',
                        lambda *args: (_ for _ in ()).throw(AssertionError('new provider call forbidden')))
    stage = run.durable_stage(tmp_path, config(), issue)
    assert stage['recovered'] is True and stage['added_wall_s'] is None
    assert stage['result']['usable'] is False
    assert stage['live_evidence']['interrupted_response_unavailable'] is True
    assert stage['live_evidence']['provider_attempts'] == 0


def test_saved_glm_first_response_replayed_with_its_model_and_metadata(tmp_path, monkeypatch):
    run.write(tmp_path / 'started.json', {'started': True, 'model': run.MODEL})
    backend = run.GLMJournalBackend(config(), tmp_path)
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post', lambda self, payload: wire())
    assert issue(backend).usable
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post',
                        lambda *args: (_ for _ in ()).throw(AssertionError('new call forbidden')))
    stage = run.durable_stage(tmp_path, config(), issue)
    assert stage['result']['usable']
    assert stage['result']['diagnostics']['model'] == run.MODEL
    assert stage['live_evidence']['recovered_without_new_call'] is True
    assert stage['live_evidence']['provider_attempts'] == 1
    assert stage['added_wall_s'] is None


def test_provider_requires_explicit_glm_process_key_no_other_credentials(monkeypatch):
    monkeypatch.delenv('GLM_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'other-provider')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'other-account')
    with pytest.raises(LLMConfigurationError, match='explicit process GLM_API_KEY'):
        run.resolve_provider()
    monkeypatch.setenv('GLM_API_KEY', KEY)
    actual, receipt = run.resolve_provider()
    assert actual.model == run.MODEL and actual.api_key == KEY
    assert receipt['automatic_fallback'] is False
    assert KEY not in json.dumps(receipt)


def test_approved_preflight_fixed_configuration_matches_without_network():
    reference = run.prior_preflight(config())
    assert reference['configuration_match']
    assert reference['reasoning_effort'] == 'provider_default_not_sent'
    drift = GLMChatConfig(run.approved.BASE_URL, KEY, max_tokens=4095, response_format_json_object=True)
    with pytest.raises(ValueError, match='configuration drift'):
        run.prior_preflight(drift)


def test_skipped_unreleased_b_no_verifier_request(tmp_path, monkeypatch):
    from g1swarm.language.errors import CompilerStatus
    from g1swarm.language.result import CompilerResult
    sample = {'population': 'controlled', 'sample_id': 'synthetic-skip', 'source': 'fictional',
              'expected_status': 'MALFORMED', 'expected_mission': None}
    result = CompilerResult(CompilerStatus.MALFORMED, normalized_text='fictional')
    prior = {'sample': sample, 'B': {'result': result.to_dict()}}
    run.write(tmp_path / 'prior.json', prior)
    run.write(tmp_path / 'dd.json', {'unmodified': True})
    item = {'population': sample['population'], 'sample_id': sample['sample_id'],
        'source_sha256': run.sha(sample['source'].encode()), 'v1_sample_path': 'prior.json',
        'v1_sample_sha256': run.sha((tmp_path / 'prior.json').read_bytes()), 'dd_sample_path': 'dd.json',
        'dd_sample_sha256': run.sha((tmp_path / 'dd.json').read_bytes()), 'eligible_B_candidate': False}
    base = tmp_path / 'pilot'
    run.write(base / 'inputs.json', {'rows': [item], 'eligible_B_candidates': 0})
    monkeypatch.setattr(run, 'ROOT', tmp_path)
    monkeypatch.setattr(run, 'BASE', base)
    monkeypatch.setattr(run, 'verify_prior', lambda _: None)
    monkeypatch.setattr(run, 'binding', lambda: {})
    monkeypatch.setattr(run, 'resolve_provider', lambda: (config(), {}))
    monkeypatch.setattr(run, 'preflight', lambda *args: None)
    monkeypatch.setattr(GLMChatCompletionsBackend, '_post',
                        lambda *args: (_ for _ in ()).throw(AssertionError('skipped B cannot call provider')))
    receipt = run.collect(1)
    saved = run.read(base / 'samples/controlled--synthetic-skip.json')['dg']
    assert receipt['B_reruns'] == receipt['DD_reruns'] == 0
    assert saved['result'] == result.to_dict()
    assert saved['live_evidence']['provider_calls'] == 0
    assert not (base / 'acquisition').exists()
