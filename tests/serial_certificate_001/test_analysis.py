"""Offline adversarial checks for the additive serial comparison and audit."""
from __future__ import annotations

import copy
from dataclasses import asdict
import json
import subprocess

import pytest

from scripts.serial_certificate_001 import analyze_pilot as analysis
from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer
from g1swarm.glm_preflight_001.chat_backend import GLMChatCompletionsBackend, GLMChatConfig
from g1swarm.source_authority import apply_gate


CONFIG = {'model': 'glm-5.3-flash', 'base_url': 'https://provider.invalid/api/v4',
          'temperature': 0.0, 'max_tokens': 4096, 'response_format': {'type': 'json_object'}}
UNIQUE = {'status': 'AUTHORIZED_UNIQUE', 'checks': ['U'] * 7, 'plan': [['stand', 2.0]], 'issues': []}


def historical_row(key):
    base = analysis.ROOT
    prior = analysis.read(base / analysis.V1 / 'samples' / (key + '.json'))
    dd = analysis.read(base / analysis.DD / 'samples' / (key + '.json'))
    dg = analysis.read(base / analysis.DG4 / 'samples' / (key + '.json'))
    bounded = next(row for row in analysis.read(base / analysis.V1 / 'bounded_control.json')['records']
                   if analysis.identity(row) == key)
    return {'sample': prior['sample'], 'B': prior['B'], 'DD': dd['v2'], 'DG4': dg['dg'],
            'DG_serial': copy.deepcopy(dg['dg']), 'bounded': bounded}


def fixture_stage(directory, certificate=None):
    prior = analysis.read(analysis.ROOT / analysis.V1 / 'samples/controlled--cl-a-001.json')
    prompt = (analysis.ROOT / 'prompts/authority_certificate_v2.txt').read_bytes().decode('utf8')
    text = json.dumps(certificate or UNIQUE, ensure_ascii=False, separators=(',', ':'))
    wire = {'id': 'fixture', 'model': CONFIG['model'], 'usage': {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140},
        'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': text}}]}
    backend = GLMChatCompletionsBackend(GLMChatConfig(CONFIG['base_url'], 'offline-fixture', response_format_json_object=True))
    first = asdict(backend._response(wire, 1, 0.2))
    wire['choices'][0]['message'].update(reasoning_content=None, reasoning_content_present=False, reasoning_content_chars=0)
    payload = analysis.historical.expected_payload(prior['sample']['source'], prompt, CONFIG, chat=True)
    digest = analysis.historical.request_hash(payload)
    begin = {'index': 1, 'request_sha256': digest}
    end = dict(begin, latency_s=0.2, status='SUCCESS', provider_document=wire)
    result = apply_gate(prior['sample']['source'], analysis.historical.old.result_from(prior['B']['result']),
        SourceAuthorityCertificateIssuer(analysis.historical.ReplayBackend(first, CONFIG['model']))).to_dict()
    output = {'result': result, 'score': analysis.historical.independent_score(prior['sample'], result),
        'added_wall_s': 0.3, 'recovered': False, 'live_evidence': {'provider_calls': 1, 'provider_attempts': 1,
        'events': [end], 'responses': [first], 'raw_reasoning_persisted': False, 'credential_or_hash_persisted': False}}
    for name, value in [('attempt-01-begin.json', begin), ('attempt-01-end.json', end),
            ('response.json', first), ('started.json', {'started': True, 'model': CONFIG['model'],
                'policy': 'never reissue this semantic call after interruption'}),
            ('request.json', {'payload': payload, 'request_sha256': digest, 'request_input_fields': ['source'],
                'source_sha256': analysis.sha(prior['sample']['source'])}),
            ('stage_result.json', {key: value for key, value in output.items() if key != 'score'})]:
        analysis.write(directory / name, value)
    return output, prior, prompt


def timing(sequence, start, finish):
    return {'serial_sequence': sequence, 'started_monotonic_ns': start, 'finished_monotonic_ns': finish,
            'workers': 1, 'called': True, 'recovered': False}


def test_unchanged_source_only_payload_is_byte_identical_and_full_gate_replays(tmp_path):
    first, prior, prompt = fixture_stage(tmp_path / 'serial')
    fixture_stage(tmp_path / 'history')
    assert analysis.audit_payload_equality(tmp_path / 'serial', tmp_path / 'history') == []
    assert analysis.historical.audit_stage(first, prior, tmp_path / 'serial', prompt, CONFIG, chat=True) == []


def test_json_equivalence_cannot_hide_persisted_request_byte_drift(tmp_path):
    fixture_stage(tmp_path / 'serial')
    fixture_stage(tmp_path / 'history')
    path = tmp_path / 'serial/request.json'
    path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
    found = analysis.audit_payload_equality(tmp_path / 'serial', tmp_path / 'history')
    assert found == ['serial request document bytes differ from historical DG4 request']


def test_candidate_leak_and_hash_replacement_cannot_pass_source_only_host_audit(tmp_path):
    output, prior, prompt = fixture_stage(tmp_path / 'serial')
    fixture_stage(tmp_path / 'history')
    path = tmp_path / 'serial/request.json'
    request = analysis.read(path)
    request['payload']['messages'][1]['content'] = json.dumps({'source': prior['sample']['source'], 'candidate': prior['B']['result']['mission']})
    request['request_sha256'] = analysis.historical.request_hash(request['payload'])
    analysis.write(path, request)
    assert 'serial full source-only wire payload bytes differ from historical DG4' in analysis.audit_payload_equality(tmp_path / 'serial', tmp_path / 'history')
    found = analysis.historical.audit_stage(output, prior, tmp_path / 'serial', prompt, CONFIG, chat=True)
    assert any('independently reconstructed source-only payload' in issue for issue in found)


def test_candidate_and_score_tamper_is_rejected_by_host_replay(tmp_path):
    output, prior, prompt = fixture_stage(tmp_path)
    output['result']['mission']['steps'][0]['parameters']['duration_s'] = 9
    analysis.write(tmp_path / 'stage_result.json', {key: value for key, value in output.items() if key != 'score'})
    found = analysis.historical.audit_stage(output, prior, tmp_path, prompt, CONFIG, chat=True)
    assert 'deterministic full gate replay differs from recorded result' in found
    assert 'score differs from independent frozen-label scoring' in found
    assert 'release changed historical B candidate' in found


def test_nonoverlapping_serial_intervals_and_historical_order_pass():
    records = [('a', timing(1, 1, 4)), ('b', timing(2, 4, 8))]
    assert analysis.audit_serial_timing(records, ['a', 'b']) == []


@pytest.mark.parametrize('mutation,expected', [
    ('overlap', 'overlap'), ('wrong_worker', 'worker/called'), ('order', 'order'),
    ('sequence', 'contiguous'), ('boolean_clock', 'invalid serial call interval')])
def test_actual_concurrency_order_and_clock_drift_rejected(mutation, expected):
    records = [('a', timing(1, 1, 4)), ('b', timing(2, 4, 8))]
    if mutation == 'overlap':
        records[1][1]['started_monotonic_ns'] = 3
    elif mutation == 'wrong_worker':
        records[1][1]['workers'] = 4
    elif mutation == 'order':
        records[0] = ('b', records[0][1])
    elif mutation == 'sequence':
        records[1][1]['serial_sequence'] = 3
    else:
        records[1][1]['started_monotonic_ns'] = True
    assert any(expected in issue for issue in analysis.audit_serial_timing(records, ['a', 'b']))


def treatment():
    old = analysis.read(analysis.ROOT / analysis.DG4 / 'protocol.json')
    current = dict(old, workers=1)
    actual = {key: old['provider'][key] for key in ('base_url', 'model', 'temperature', 'max_tokens',
        'timeout_s', 'max_network_retries', 'retry_backoff_s', 'retry_statuses', 'max_response_bytes')}
    actual.update(response_format_json_object=True, thinking_enabled=True)
    return current, old, actual


def test_only_concurrency_treatment_and_actual_config_accept_exact_frozen_policy():
    current, old, actual = treatment()
    assert analysis.audit_treatment(current, old, actual) == []


@pytest.mark.parametrize('field,value', [('model', 'glm-other'), ('temperature', 0.2), ('max_tokens', 8192),
    ('timeout_s', 120), ('max_network_retries', 3), ('retry_backoff_s', 1),
    ('thinking', {'type': 'disabled'}), ('response_format', None)])
def test_model_reasoning_budget_temperature_timeout_and_retry_drift_rejected(field, value):
    current, old, actual = treatment()
    current = copy.deepcopy(current)
    current['provider'][field] = value
    assert any('provider/model/reasoning' in issue for issue in analysis.audit_treatment(current, old, actual))


def test_declared_serial_policy_cannot_hide_actual_provider_policy_drift():
    current, old, actual = treatment()
    actual['max_network_retries'] = 10
    assert any('actual acquisition provider configuration' in issue for issue in analysis.audit_treatment(current, old, actual))


@pytest.mark.parametrize('field', ['request', 'contract', 'first_response', 'semantic_credit'])
def test_source_authority_release_and_scoring_protocol_drift_rejected(field):
    current, old, actual = treatment()
    current[field] = 'changed policy'
    assert any(issue.endswith(': ' + field) for issue in analysis.audit_treatment(current, old, actual))


def test_old_thresholds_known_unsafe_and_no_heldout_policy_must_remain_exact():
    current, old, actual = treatment()
    current = copy.deepcopy(current)
    current['readiness_criteria']['unauthorized_release'] = 1
    current['known_B_unsafe_ids'] = ['ood-m-031']
    current['held_out_started'] = True
    found = analysis.audit_treatment(current, old, actual)
    assert 'inherited readiness thresholds changed' in found
    assert 'known seven unsafe membership changed' in found
    assert 'held_out_started is not explicitly false' in found


def test_paired_skips_contribute_neither_usable_nor_resource_or_authority_disagreement():
    row = historical_row('ood--ood-m-001')
    result = analysis.paired([row])
    assert result['comparison']['left_arm'] == 'DG4'
    assert result['comparison']['right_arm'] == 'DG_serial'
    assert result['usable_certificate_pairing']['called_pair_n'] == 0
    assert result['resource_failure_pairing'] == {}
    assert result['authority_or_reason_disagreement_count'] == 0


def test_paired_retention_recovery_is_labeled_serial_vs_historical_DG4():
    row = historical_row('ood--ood-v-001')
    row['DG_serial'] = copy.deepcopy(row['B'])
    # Synthetic semantic stage retains B score but carries a usable certificate.
    row['DG_serial']['live_evidence'] = copy.deepcopy(historical_row('controlled--cl-a-001')['DG4']['live_evidence'])
    row['DG_serial']['result']['diagnostics']['source_authorization'] = copy.deepcopy(historical_row('controlled--cl-a-001')['DG4']['result']['diagnostics']['source_authorization'])
    result = analysis.paired([row])
    assert result['serial_recovered_from_DG4'] == 1
    assert result['serial_recovered_ids'] == ['ood--ood-v-001']
    assert result['usable_certificate_pairing']['serial_recovered'] == 1
    assert result['disagreements'][0]['DG4']['taxonomy'] == 'provider_or_transport_failure'
    assert 'DD' not in result['disagreements'][0]


def test_accounting_counts_attempts_once_and_missing_usage_remains_unknown():
    evidence = {'events': [
        {'status': 'API_ERROR', 'error_context': {'reason': 'NETWORK_ERROR'}},
        {'status': 'API_ERROR', 'error_context': {'http_status': 429, 'usage': {'total_tokens': 10}}},
        {'status': 'SUCCESS', 'provider_document': {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140,
                'completion_tokens_details': {'reasoning_tokens': 30}}}}], 'responses': [{'usage': {'total_tokens': 140}}]}
    result = analysis.accounting(evidence)
    assert result['reported_tokens'] == 150
    assert result['reported_reasoning_tokens'] == 30
    assert result['attempt_units_missing_total_usage'] == 1
    assert result['http_429_failure_attempts'] == 1


def test_network_and_429_comparisons_use_both_call_and_attempt_denominators():
    row = historical_row('controlled--cl-a-001')
    output = row['DG_serial']
    output['live_evidence'] = {'provider_calls': 1, 'provider_attempts': 3,
        'events': [{'status': 'API_ERROR', 'error_context': {'reason': 'NETWORK_ERROR'}},
                   {'status': 'API_ERROR', 'error_context': {'http_status': 429}},
                   {'status': 'API_ERROR', 'error_context': {'http_status': 429}}],
        'responses': [{'failure_type': 'API_ERROR', 'attempts': 3, 'context': {'http_status': 429}}]}
    output['result']['diagnostics']['source_authorization'] = {'status': 'UNKNOWN', 'reason_code': 'BACKEND_FAILURE', 'diagnostics': {'certificate_usable': False}}
    result = analysis.metrics([row], 'DG_serial')
    assert result['http_429_attempt_rate'] == {'numerator': 2, 'denominator': 3, 'rate': 2 / 3}
    assert result['network_attempt_rate'] == {'numerator': 1, 'denominator': 3, 'rate': 1 / 3}
    assert result['calls_with_429_rate'] == {'numerator': 1, 'denominator': 1, 'rate': 1}
    assert result['final_429_or_network_failure_rate'] == {'numerator': 1, 'denominator': 1, 'rate': 1}
    assert result['reported_tokens_are_lower_bound_when_usage_missing'] is True


def test_specific_unknown_is_review_candidate_not_automatic_semantic_credit(tmp_path):
    specific = {'status': 'UNKNOWN', 'checks': ['U'] * 6 + ['?'], 'plan': None,
                'issues': [{'relation': 'unit', 'reason': 'MISSING'}]}
    output, _, _ = fixture_stage(tmp_path, specific)
    case = analysis.unsafe_arm(output)
    assert case['usable'] is True
    assert case['specific_semantic_rejection_review_candidate'] is True
    assert case['semantic_credit'] is None


def test_valid_unique_certificate_is_not_mislabeled_as_known_unsafe_false_unique(tmp_path):
    output, _, _ = fixture_stage(tmp_path)
    case = analysis.unsafe_arm(output, known_unsafe=False)
    assert case['authorized_unique_certificate'] is True
    assert case['certificate_false_unique'] is False
    assert case['certificate_false_unique_matches_B'] is False


def test_invalid_plan_false_unique_claim_is_raw_only_without_semantic_credit_or_host_release(tmp_path):
    malformed = {'status': 'AUTHORIZED_UNIQUE', 'checks': ['U'] * 7,
                 'plan': [['walk', 8]], 'issues': []}
    output, prior, prompt = fixture_stage(tmp_path, malformed)
    assert analysis.historical.audit_stage(output, prior, tmp_path, prompt, CONFIG, chat=True) == []
    case = analysis.unsafe_arm(output)
    assert case['raw_final_authority_status_claim'] == 'AUTHORIZED_UNIQUE'
    assert case['raw_false_unique_claim'] is True
    assert case['usable'] is False
    assert case['contract_usable_false_unique'] is False
    assert case['certificate_false_unique'] is False
    assert case['taxonomy'] == 'certificate_contract_failure'
    assert case['semantic_credit'] is None
    assert case['released'] is case['unauthorized_release'] is False
    assert case['certificate'] is None
    assert not case['specific_semantic_rejection_review_candidate']


@pytest.mark.parametrize('text', [
    '{"status":"AUTHORIZED_UNIQUE","status":"UNKNOWN"}',
    '{"status":"AUTHORIZED_UNIQUE","nested":{"a":1,"a":2}}',
    '{"status":"AUTHORIZED_UNIQUE","plan":[NaN]}',
    '{"status":"AUTHORIZED_UNIQUE","plan":[Infinity]}',
    '{"status":"AUTHORIZED_UNIQUE","plan":[1e9999]}',
    '[{"status":"AUTHORIZED_UNIQUE"}]',
    '{"status":["AUTHORIZED_UNIQUE"]}',
    '{"status":"AUTHORIZED_UNIQUE"} trailing',
    '```json\n{"status":"AUTHORIZED_UNIQUE"}\n```'])
def test_raw_claim_extraction_rejects_duplicates_nonfinite_nonobjects_or_repair(text):
    output = {'live_evidence': {'responses': [{'text': text}]}}
    assert analysis.raw_final_authority_status_claim(output) is None


def test_raw_claim_does_not_substitute_backend_context_or_reasoning_for_final_content():
    output = {'live_evidence': {'responses': [{'failure_type': 'API_ERROR',
        'context': {'text': '{"status":"AUTHORIZED_UNIQUE"}', 'reasoning_content': '{"status":"AUTHORIZED_UNIQUE"}'}}]}}
    assert analysis.raw_final_authority_status_claim(output) is None


def test_valid_source_raw_unique_claim_does_not_become_known_unsafe_claim(tmp_path):
    output, _, _ = fixture_stage(tmp_path)
    case = analysis.unsafe_arm(output, known_unsafe=False)
    assert case['raw_final_authority_status_claim'] == 'AUTHORIZED_UNIQUE'
    assert case['raw_false_unique_claim'] is False


def test_historical_031_release_and_repeated_raw_claim_survive_serial_contract_failure(tmp_path):
    row = historical_row('ood--ood-m-031')
    row['DG_serial'], _, _ = fixture_stage(tmp_path, {'status': 'AUTHORIZED_UNIQUE', 'checks': ['U'] * 7,
        'plan': [['walk', 8]], 'issues': []})
    summary, report = analysis.analyze_rows([row], {'readiness_criteria': {}})
    dependency = report['dependent_failure_analysis']
    assert dependency['historical_DG4_unsafe_release_ids'] == ['ood-m-031']
    assert dependency['serial_unsafe_release_ids'] == []
    assert dependency['persistent_raw_false_unique_claim_ids'] == ['ood-m-031']
    assert dependency['serial_raw_false_unique_claim_without_usable_certificate_ids'] == ['ood-m-031']
    assert dependency['new_serial_raw_false_unique_claim_ids'] == []
    assert dependency['serial_false_unique_ids'] == []
    comparison = summary['DG4_vs_serial']
    assert comparison['known_unsafe_raw_false_unique_claims']['DG4'] == 1
    assert comparison['known_unsafe_raw_false_unique_claims']['DG_serial'] == 1
    assert comparison['known_unsafe_usable_false_unique_certificates']['DG_serial'] == 0


def test_historical_false_unique_031_is_preserved_and_new_identity_reported_separately():
    old = historical_row('ood--ood-m-031')
    new = historical_row('ood--ood-m-012')
    new['DG_serial'] = copy.deepcopy(old['DG4'])
    # Scores are only for exercising analysis identity handling, not live scoring.
    rows = [old, new]
    summary, report = analysis.analyze_rows(rows, {'readiness_criteria': {}}, {'campaign_wall_s': 100, 'resume': False})
    dependencies = report['dependent_failure_analysis']
    assert dependencies['historical_DG4_unsafe_release_ids'] == ['ood-m-031']
    assert dependencies['persistent_unsafe_release_ids'] == ['ood-m-031']
    assert dependencies['new_serial_false_unique_ids'] == ['ood-m-012']
    assert summary['historical_unsafe_release_not_overwritten'] is True
    assert summary['D011'] == 'BLOCKED'
    assert summary['semantic_success_claim'] is False
    assert summary['comparison']['statistical_significance_claim'] is False


def test_campaign_throughput_does_not_replace_per_request_latency_and_resume_is_not_full_duration():
    row = historical_row('controlled--cl-a-001')
    row['DG_serial']['added_wall_s'] = 2
    summary, _ = analysis.analyze_rows([row], {'readiness_criteria': {}}, {'campaign_wall_s': 100, 'resume': False})
    assert summary['cohorts']['all']['DG_serial']['added_wall_median_s'] == 2
    assert summary['campaign']['DG_serial']['calls_per_second'] == .01
    assert summary['campaign']['DG4']['campaign_wall_s'] is None
    resumed, _ = analysis.analyze_rows([row], {'readiness_criteria': {}}, {'campaign_wall_s': 10, 'resume': True})
    assert resumed['campaign']['DG_serial']['calls_per_second'] is None


def test_recovery_latency_unknown_is_excluded_from_latency_denominator():
    row = historical_row('controlled--cl-a-001')
    row['DG_serial']['added_wall_s'] = None
    row['DG_serial']['recovered'] = True
    result = analysis.metrics([row], 'DG_serial')
    assert result['called'] == 1 and result['latency_sample_n'] == 0
    assert result['called_stages_without_live_wall_latency'] == 1
    assert result['added_wall_median_s'] is result['added_wall_p95_s'] is None


def freeze_fixture(tmp_path):
    raw = b'# acquisition snapshot\r\n'
    paths = ['scripts/serial_certificate_001/run_pilot.py', analysis.EXPERIMENT + '/acquisition_runner_snapshot.py']
    for path in paths:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'core.autocrlf=false', 'add', '--', *paths], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Offline Test', '-c', 'user.email=offline@example.invalid',
        'commit', '-qm', 'Freeze acquisition bytes'], check=True, capture_output=True)
    commit = subprocess.check_output(['git', '-C', str(tmp_path), 'rev-parse', 'HEAD']).decode().strip()
    hashes = {path: analysis.sha(raw) for path in paths}
    receipt = {'freeze_commit': commit, 'starting_commit': commit, 'workers': 1,
        'acquisition_hashes': hashes, 'all_acquisition_hashes_verified_in_Git_commit': {path: True for path in paths},
        'preflight_or_scored_calls_started_at_freeze': False, 'provider_calls': 0, 'runtime_calls': 0, 'held_out_calls': 0,
        'runner_source_snapshot_sha256': analysis.sha(raw), 'recorded_utc': '2026-10-07T10:00:00+00:00'}
    return receipt, hashes, commit


def test_pre_scored_freeze_verifies_actual_git_blob_bytes_and_ancestry(tmp_path):
    receipt, hashes, commit = freeze_fixture(tmp_path)
    assert analysis.audit_pre_scored_freeze(tmp_path, receipt, hashes, commit) == []


def test_self_consistent_freeze_claim_cannot_hide_different_committed_bytes(tmp_path):
    receipt, hashes, commit = freeze_fixture(tmp_path)
    changed = {path: analysis.sha(b'# changed acquisition\n') for path in hashes}
    receipt['acquisition_hashes'] = changed
    receipt['runner_source_snapshot_sha256'] = next(iter(changed.values()))
    assert any('Git commit raw acquisition bytes differ' in issue
               for issue in analysis.audit_pre_scored_freeze(tmp_path, receipt, changed, commit))


@pytest.mark.parametrize('field,value', [('workers', 4), ('provider_calls', 1), ('preflight_or_scored_calls_started_at_freeze', True)])
def test_freeze_cannot_begin_after_provider_calls_or_with_wrong_concurrency(tmp_path, field, value):
    receipt, hashes, commit = freeze_fixture(tmp_path)
    receipt[field] = value
    assert analysis.audit_pre_scored_freeze(tmp_path, receipt, hashes, commit)


def pending_fixture(directory):
    _, prior, prompt = fixture_stage(directory)
    digest = analysis.read(directory / 'request.json')['request_sha256']
    for name in ('response.json', 'stage_result.json'):
        (directory / name).unlink()
    analysis.write(directory / 'attempt-01-end.json', {'index': 1, 'request_sha256': digest,
        'status': 'API_ERROR', 'error_context': {'category': 'TRANSPORT', 'reason': 'NETWORK_ERROR'}, 'latency_s': 60})
    analysis.write(directory / 'attempt-02-begin.json', {'index': 2, 'request_sha256': digest})
    return prior, prompt


def test_interrupted_request_has_observed_attempt_failure_but_no_terminal_provider_or_semantic_outcome(tmp_path):
    prior, prompt = pending_fixture(tmp_path)
    pending, errors = analysis.audit_unfinished_stage(tmp_path, prior, prompt, CONFIG)
    assert errors == []
    assert pending['classification'] == 'INTERRUPTED_UNOBSERVED'
    assert pending['attempts_started'] == 2 and pending['attempts_finished'] == 1
    assert pending['attempts_unobserved'] == 1
    assert pending['observed_attempt_accounting']['transport_failure_attempts'] == 1
    assert pending['final_provider_failure'] is pending['usable_certificate'] is pending['released'] is None
    assert pending['semantic_credit'] is None
    assert pending['included_in_completed_stage_outcome_metrics'] is False
    assert pending['no_semantic_reissue_allowed'] is True


def test_unfinished_request_cannot_be_filled_with_a_synthetic_first_response(tmp_path):
    prior, prompt = pending_fixture(tmp_path)
    analysis.write(tmp_path / 'response.json', {'failure_type': 'API_ERROR', 'attempts': 2})
    _, errors = analysis.audit_unfinished_stage(tmp_path, prior, prompt, CONFIG)
    assert 'unfinished stage unexpectedly has durable terminal response/stage/timing' in errors


def test_stopped_closeout_uses_exact_completed_pair_scope_and_never_full_serial_acceptance(tmp_path, monkeypatch):
    row = historical_row('ood--ood-m-031')
    base = tmp_path / analysis.EXPERIMENT
    inputs = analysis.read(analysis.ROOT / analysis.EXPERIMENT / 'inputs.json')
    protocol = analysis.read(analysis.ROOT / analysis.EXPERIMENT / 'protocol.json')
    analysis.write(base / 'inputs.json', inputs)
    analysis.write(base / 'protocol.json', protocol)
    analysis.write(base / 'stop_receipt.json', {'planned_samples': 528, 'planned_calls': 291,
        'completed_samples_at_stop': 1, 'completed_called_stages_at_stop': 1, 'full_population_completed': False,
        'frozen_protocol_rewritten': False, 'future_collection_authorized': False, 'in_flight_at_stop': []})
    (base / 'acquisition').mkdir()
    prompt = tmp_path / 'prompts/authority_certificate_v2.txt'
    prompt.parent.mkdir()
    prompt.write_bytes((analysis.ROOT / 'prompts/authority_certificate_v2.txt').read_bytes())
    analysis.write(tmp_path / analysis.DG4 / 'summary.json', analysis.read(analysis.ROOT / analysis.DG4 / 'summary.json'))
    for item in inputs['rows']:
        if item['sample_id'] not in analysis.KNOWN_UNSAFE:
            continue
        for prefix in ('v1', 'dd', 'dg'):
            relative = item[prefix + '_sample_path']
            destination = tmp_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((analysis.ROOT / relative).read_bytes())
    monkeypatch.setattr(analysis, 'validate', lambda root, partial: ([row], {'issues': [], 'completed_samples': 1,
        'final_acceptance_claim': False, 'status': 'PASS'}))
    result = analysis.closeout(tmp_path)
    summary = analysis.read(base / 'partial_summary.json')
    detail = analysis.read(base / 'partial_analysis.json')
    assert result['status'] == 'PASS' and result['final_acceptance_claim'] is False
    assert summary['scope']['completed_paired_comparison_denominator'] == 1
    assert summary['cohorts']['all']['DG4']['called'] == summary['cohorts']['all']['DG_serial']['called'] == 1
    assert summary['full_historical_context']['called_n'] == 291
    assert summary['scope']['full_serial_global_metrics_available'] is False
    assert summary['scope']['global_operational_readiness_assessed'] is False
    assert 'operational_checks_excluding_semantic_review' not in summary
    assert summary['full_population_operational_checks'] == 'NOT_ASSESSED_INCOMPLETE_CAMPAIGN'
    assert 'cl-h-011' in detail['not_run_known_unsafe_ids']
    unrun = next(case for case in detail['unacquired_known_unsafe_cases'] if case['sample_id'] == 'cl-h-011')
    assert unrun['arms']['DG_serial']['taxonomy'] == 'NOT_RUN'
    assert unrun['arms']['DG_serial']['released'] is None
