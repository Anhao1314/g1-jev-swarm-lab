"""Offline adversarial checks for immutable paired evidence and token accounting."""
from __future__ import annotations

import copy
from dataclasses import asdict
import json

import pytest

from scripts import analyze_cross_model_certificate_pilot as analysis
from g1swarm.glm_preflight_001.chat_backend import GLMChatCompletionsBackend, GLMChatConfig
from g1swarm.source_authority import apply_gate
from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer


CONFIG = {'model': 'glm-5.3-flash', 'base_url': 'https://provider.invalid/api/v4',
          'temperature': 0.0, 'max_tokens': 4096, 'response_format': {'type': 'json_object'}}
KEY = 'synthetic-offline-key'
UNIQUE = {'status': 'AUTHORIZED_UNIQUE', 'checks': ['U'] * 7, 'plan': [['stand', 2.0]], 'issues': []}


def fixture_stage(tmp_path, certificate=None, finish='stop', transport_failures=0):
    prior = analysis.read(analysis.ROOT / analysis.V1 / 'samples/controlled--cl-a-001.json')
    prompt = (analysis.ROOT / 'prompts/authority_certificate_v2.txt').read_bytes().decode('utf8')
    text = json.dumps(certificate or UNIQUE, ensure_ascii=False, separators=(',', ':'))
    wire = {'id': 'fixture-1', 'model': 'glm-5.3-flash', 'usage': {
        'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140,
        'completion_tokens_details': {'reasoning_tokens': 30}}, 'choices': [{
        'index': 0, 'finish_reason': finish, 'message': {
            'role': 'assistant', 'content': text, 'reasoning_content': 'fixture private reasoning'}}]}
    backend = GLMChatCompletionsBackend(GLMChatConfig(CONFIG['base_url'], KEY, response_format_json_object=True))
    attempts = 1 + transport_failures
    first = asdict(backend._response(wire, attempts, 0.3))
    sanitized = copy.deepcopy(wire)
    message = sanitized['choices'][0]['message']
    message.update(reasoning_content=None, reasoning_content_present=True, reasoning_content_chars=len('fixture private reasoning'))
    payload = analysis.expected_payload(prior['sample']['source'], prompt, CONFIG, chat=True)
    digest = analysis.request_hash(payload)
    events = []
    for index in range(1, attempts + 1):
        begin = {'index': index, 'request_sha256': digest}
        end = dict(begin, latency_s=0.2)
        if index < attempts:
            end.update(status='API_ERROR', error_context={'category': 'HTTP', 'reason': 'HTTP_STATUS', 'http_status': 502})
        else:
            end.update(status='SUCCESS', provider_document=sanitized)
        analysis.write(tmp_path / f'attempt-{index:02d}-begin.json', begin)
        analysis.write(tmp_path / f'attempt-{index:02d}-end.json', end)
        events.append(end)
    result = apply_gate(prior['sample']['source'], analysis.old.result_from(prior['B']['result']),
                        SourceAuthorityCertificateIssuer(analysis.ReplayBackend(first, CONFIG['model']))).to_dict()
    output = {'result': result, 'score': analysis.independent_score(prior['sample'], result), 'added_wall_s': 0.4,
              'recovered': False, 'live_evidence': {'provider_calls': 1, 'provider_attempts': attempts,
                  'events': events, 'responses': [first], 'raw_reasoning_persisted': False, 'credential_or_hash_persisted': False}}
    analysis.write(tmp_path / 'stage_result.json', {key: value for key, value in output.items() if key != 'score'})
    analysis.write(tmp_path / 'request.json', {'payload': payload, 'request_sha256': digest,
                                             'request_input_fields': ['source'], 'source_sha256': analysis.sha(prior['sample']['source'])})
    analysis.write(tmp_path / 'response.json', first)
    analysis.write(tmp_path / 'started.json', {'started': True, 'model': CONFIG['model'],
        'policy': 'never reissue this semantic call after interruption'})
    return output, prior, prompt


def errors(output, prior, directory, prompt):
    return analysis.audit_stage(output, prior, directory, prompt, CONFIG, chat=True)


def sync_receipt(directory, output):
    analysis.write(directory / 'stage_result.json', {key: value for key, value in output.items() if key != 'score'})


def test_full_wire_source_binding_and_gate_replay_accepts_exact_first_output(tmp_path):
    output, prior, prompt = fixture_stage(tmp_path, transport_failures=2)
    assert errors(output, prior, tmp_path, prompt) == []
    accounting = analysis.accounting(output['live_evidence'])
    assert accounting['reported_tokens'] == 140
    assert accounting['reported_reasoning_tokens'] == 30
    assert accounting['failed_attempts_unavailable_usage'] == 2
    assert accounting['attempt_units_missing_total_usage'] == 2


def test_self_consistent_candidate_leak_cannot_replace_frozen_source_only_request(tmp_path):
    output, prior, prompt = fixture_stage(tmp_path)
    request = analysis.read(tmp_path / 'request.json')
    request['payload']['messages'][1]['content'] = json.dumps({'source': prior['sample']['source'], 'candidate': prior['B']['result']['mission']})
    request['request_sha256'] = analysis.request_hash(request['payload'])
    analysis.write(tmp_path / 'request.json', request)
    for suffix in ('begin', 'end'):
        path = tmp_path / f'attempt-01-{suffix}.json'
        value = analysis.read(path)
        value['request_sha256'] = request['request_sha256']
        analysis.write(path, value)
        if suffix == 'end':
            output['live_evidence']['events'] = [value]
    sync_receipt(tmp_path, output)
    found = errors(output, prior, tmp_path, prompt)
    assert 'full candidate-blind payload hash mismatch' in found
    assert any('independently reconstructed source-only payload' in item for item in found)


def test_raw_final_content_tamper_is_caught_even_when_all_copies_of_journal_match(tmp_path):
    output, prior, prompt = fixture_stage(tmp_path)
    output['live_evidence']['events'][0]['provider_document']['choices'][0]['message']['content'] += ' '
    analysis.write(tmp_path / 'attempt-01-end.json', output['live_evidence']['events'][0])
    sync_receipt(tmp_path, output)
    assert 'first response differs from independently normalized sanitized wire' in errors(output, prior, tmp_path, prompt)


def test_changed_candidate_and_score_are_rejected_by_independent_gate_and_gold(tmp_path):
    output, prior, prompt = fixture_stage(tmp_path)
    output['result']['mission']['steps'][0]['parameters']['duration_s'] = 9
    sync_receipt(tmp_path, output)
    found = errors(output, prior, tmp_path, prompt)
    assert 'deterministic full gate replay differs from recorded result' in found
    assert 'score differs from independent frozen-label scoring' in found
    assert 'release changed historical B candidate' in found


def test_raw_reasoning_never_allowed_in_new_wire_artifact(tmp_path):
    output, prior, prompt = fixture_stage(tmp_path)
    output['live_evidence']['events'][0]['provider_document']['choices'][0]['message']['reasoning_content'] = 'private'
    analysis.write(tmp_path / 'attempt-01-end.json', output['live_evidence']['events'][0])
    sync_receipt(tmp_path, output)
    with pytest.raises(ValueError, match='raw reasoning text retained'):
        errors(output, prior, tmp_path, prompt)


def test_semantic_output_cannot_be_retried_as_transport_failure(tmp_path):
    output, prior, prompt = fixture_stage(tmp_path, transport_failures=1)
    second = copy.deepcopy(output['live_evidence']['events'][1]['provider_document'])
    output['live_evidence']['events'][0].update(status='SUCCESS', provider_document=second)
    analysis.write(tmp_path / 'attempt-01-end.json', output['live_evidence']['events'][0])
    sync_receipt(tmp_path, output)
    assert 'semantic first output was retried or wire not final attempt' in errors(output, prior, tmp_path, prompt)


def test_length_finish_has_no_semantic_credit_even_if_complete_json_is_present(tmp_path):
    output, prior, prompt = fixture_stage(tmp_path, finish='length')
    assert errors(output, prior, tmp_path, prompt) == []
    assert not analysis.detail(output)['certificate_usable']
    assert analysis.classification(output) == 'output_budget_exhaustion'
    assert not output['score']['released']


def test_specific_rejection_is_review_candidate_generic_unknown_is_not(tmp_path):
    specific = {'status': 'AMBIGUOUS', 'checks': ['A'] + ['U'] * 6, 'plan': None,
                'issues': [{'relation': 'multiplicity', 'reason': 'UNRESOLVED'}]}
    output, prior, prompt = fixture_stage(tmp_path / 'specific', certificate=specific)
    assert errors(output, prior, tmp_path / 'specific', prompt) == []
    assert analysis.classification(output) == 'usable_specific_rejection_review_candidate'
    generic = {'status': 'UNKNOWN', 'checks': ['U'] * 6 + ['?'], 'plan': None,
               'issues': [{'relation': 'unknown', 'reason': 'UNKNOWN'}]}
    output, _, _ = fixture_stage(tmp_path / 'generic', certificate=generic)
    assert analysis.classification(output) == 'usable_generic_UNKNOWN'


def test_wire_usage_and_failed_context_count_once_without_normalized_duplicate():
    evidence = {'events': [
        {'status': 'API_ERROR', 'error_context': {'usage': {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30}}},
        {'status': 'SUCCESS', 'provider_document': {'model': 'glm-5.3-flash', 'choices': [{'finish_reason': 'length', 'message': {
            'content': None, 'reasoning_content_chars': 19}}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 4096,
            'total_tokens': 4196, 'completion_tokens_details': {'reasoning_tokens': 4096}}}}],
        'responses': [{'usage': {'total_tokens': 4196}}]}
    result = analysis.accounting(evidence)
    assert result['reported_tokens'] == 4226
    assert result['reported_input_tokens'] == 110
    assert result['reported_output_tokens'] == 4116
    assert result['reported_reasoning_tokens'] == 4096
    assert result['failed_attempts_unavailable_usage'] == 0
    assert result['output_exhaustion'] == result['reasoning_only_exhaustion'] == 1


def test_missing_usage_is_unknown_and_does_not_use_duplicate_response():
    result = analysis.accounting({'events': [{'status': 'SUCCESS', 'provider_document': {
        'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}}],
        'responses': [{'usage': {'total_tokens': 77}}]})
    assert result['reported_tokens'] == 0
    assert result['responses_with_total_usage'] == 0
    assert result['attempt_units_missing_total_usage'] == 1


def test_responses_api_reported_totals_are_not_recomputed_or_reasoning_added_twice():
    result = analysis.accounting({'events': [{'status': 'SUCCESS', 'provider_document': {
        'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'},
        'output': [{'type': 'reasoning'}], 'usage': {'input_tokens': 218, 'output_tokens': 4096,
            'total_tokens': 4826, 'output_tokens_details': {'reasoning_tokens': 4096}}}}],
        'responses': [{'usage': {'total_tokens': 4826}}]})
    assert result['reported_tokens'] == 4826
    assert result['reported_input_tokens'] == 218
    assert result['reported_reasoning_tokens'] == 4096
    assert result['output_exhaustion'] == result['reasoning_only_exhaustion'] == 1


def test_inherited_B_is_retained_without_new_ledger_or_verifier(tmp_path):
    prior = analysis.read(analysis.ROOT / analysis.V1 / 'samples/ood--ood-m-001.json')
    output = {'result': copy.deepcopy(prior['B']['result']), 'score': copy.deepcopy(prior['B']['score']),
              'skipped_unreleased_B': True, 'added_wall_s': 0.0, 'recovered': False,
              'live_evidence': {'provider_calls': 0, 'provider_attempts': 0, 'events': [], 'responses': []}}
    assert errors(output, prior, tmp_path, '') == []
    assert analysis.classification(output) == 'inherited_B_or_guard_skip'
    historical = analysis.read(analysis.ROOT / analysis.DD / 'samples/ood--ood-m-001.json')['v2']
    paired = analysis.paired([{'sample': prior['sample'], 'B': prior['B'], 'DD': historical, 'DG': output}])
    assert paired['authority_or_reason_disagreement_count'] == 0
    assert paired['resource_failure_pairing'] == {}
    output['result']['status'] = 'MALFORMED'
    assert 'skipped DG differs from unchanged unreleased B' in errors(output, prior, tmp_path, '')


def test_recovery_latency_is_excluded_not_assigned_zero(tmp_path):
    output, prior, _ = fixture_stage(tmp_path)
    recovered = copy.deepcopy(output)
    recovered['added_wall_s'] = None
    rows = [{'sample': prior['sample'], 'B': prior['B'], 'DD': output, 'DG': recovered, 'bounded': recovered}]
    metrics = analysis.metrics(rows, 'DG')
    assert metrics['called'] == 1 and metrics['latency_sample_n'] == 0
    assert metrics['called_stages_without_live_wall_latency'] == 1
    assert metrics['added_wall_median_s'] is metrics['added_wall_p95_s'] is None


def test_inherited_readiness_criteria_and_known_unsafe_list_unchanged():
    new = analysis.read(analysis.ROOT / analysis.EXPERIMENT / 'protocol.json')
    historical = analysis.read(analysis.ROOT / analysis.DD / 'protocol.json')
    assert new['readiness_criteria'] == historical['readiness_criteria']
    assert new['known_B_unsafe_ids'] == list(analysis.KNOWN_UNSAFE)


def relocation_fixture(root):
    raw = b'# exact acquired runner bytes\r\n'
    published = root / analysis.PUBLICATION_RUNNER_PATH
    snapshot = root / analysis.ACQUISITION_RUNNER_SNAPSHOT
    for path in (published, snapshot):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return published, snapshot, analysis.sha(raw)


def test_only_exact_published_runner_and_startup_snapshot_can_resolve_original_key(tmp_path):
    published, _, digest = relocation_fixture(tmp_path)
    path, record = analysis.resolve_acquisition_binding(tmp_path, analysis.ACQUISITION_RUNNER_LOGICAL_PATH, digest)
    assert path == published
    assert record['logical_acquisition_path'] == analysis.ACQUISITION_RUNNER_LOGICAL_PATH
    assert record['expected_acquisition_sha256'] == record['verified_sha256'] == record['verified_snapshot_sha256'] == digest
    assert record['runner_snapshot_bytes_identical'] and record['namespace_repair_only']


@pytest.mark.parametrize('target', ['published', 'snapshot'])
def test_relocation_rejects_tampered_runner_or_startup_snapshot(tmp_path, target):
    published, snapshot, digest = relocation_fixture(tmp_path)
    (published if target == 'published' else snapshot).write_bytes(b'# altered implementation\n')
    with pytest.raises(ValueError, match='differs from original acquired SHA'):
        analysis.resolve_acquisition_binding(tmp_path, analysis.ACQUISITION_RUNNER_LOGICAL_PATH, digest)


def test_another_missing_logical_acquisition_path_cannot_use_runner_relocation(tmp_path):
    _, _, digest = relocation_fixture(tmp_path)
    with pytest.raises(ValueError, match='no authorized relocation'):
        analysis.resolve_acquisition_binding(tmp_path, 'scripts/other_missing_acquisition.py', digest)


def test_existing_original_binding_cannot_be_hidden_by_correct_relocated_copies(tmp_path):
    _, snapshot, digest = relocation_fixture(tmp_path)
    original = tmp_path / analysis.ACQUISITION_RUNNER_LOGICAL_PATH
    original.write_bytes(snapshot.read_bytes())
    path, record = analysis.resolve_acquisition_binding(tmp_path, analysis.ACQUISITION_RUNNER_LOGICAL_PATH, digest)
    assert path == original and record is None
    original.write_bytes(b'# altered original\n')
    with pytest.raises(ValueError, match='acquisition binding drift'):
        analysis.resolve_acquisition_binding(tmp_path, analysis.ACQUISITION_RUNNER_LOGICAL_PATH, digest)
