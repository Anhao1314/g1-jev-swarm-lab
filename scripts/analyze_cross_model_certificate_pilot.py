"""Independent offline binding, replay, accounting and paired DG pilot analysis.

No backend transport or Runtime method is called. Specific typed rejections are
review candidates, never semantic credit until the independent source review.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
from typing import Any

from scripts import run_source_authority_pilot as old
from scripts.validate_source_authority_evidence import independent_score
from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer, parse_certificate
from g1swarm.glm_preflight_001.chat_backend import GLMChatCompletionsBackend, GLMChatConfig
from g1swarm.llm.backend import LLMBackendError, LLMBackendResponse, _extract_output_text
from g1swarm.source_authority import apply_gate

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = 'experiments/phase2/source_authority_cross_model_001'
V1 = 'experiments/phase2/source_authority_001'
DD = 'experiments/phase2/source_authority_v2_001'
KNOWN_UNSAFE = ('ood-m-012', 'ood-m-025', 'ood-m-031', 'ood-m-052', 'ood-m-066', 'ood-m-069', 'cl-h-011')
ACQUISITION_RUNNER_LOGICAL_PATH = 'scripts/run_cross_model_source_authority_pilot.py'
PUBLICATION_RUNNER_PATH = 'scripts/run_cross_model_certificate_pilot.py'
ACQUISITION_RUNNER_SNAPSHOT = EXPERIMENT + '/acquisition_runner_snapshot.py'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def sha(value):
    return hashlib.sha256(value.encode('utf8') if isinstance(value, str) else value).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf8'))


def identity(sample):
    return f"{sample['population']}--{sample['sample_id']}"


def auth(output):
    return output['result']['diagnostics'].get('source_authorization', {})


def detail(output):
    return auth(output).get('diagnostics', {})


def int_token(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def accounting(evidence):
    """Each attempt owns its usage; normalized final usage is only a fallback.

    A wire document with missing usage is still authoritative: its absence must
    not be hidden by a duplicate final response. Error contexts can retain
    usage when a transport observer cannot retain a usable wire document.
    """
    events = evidence.get('events', [])
    units = []
    documents = []
    failed_unknown = 0
    for event in events:
        document = event.get('provider_document')
        context = event.get('error_context') or {}
        if isinstance(document, dict):
            documents.append(document)
            units.append(document.get('usage'))
        elif isinstance(context.get('usage'), dict):
            units.append(context['usage'])
        else:
            units.append(None)
        if event.get('status') != 'SUCCESS' and not isinstance(units[-1], dict):
            failed_unknown += 1
    if not events:
        units = [response.get('usage') or (response.get('context') or {}).get('usage')
                 for response in evidence.get('responses', [])]
    result = {'reported_tokens': 0, 'reported_input_tokens': 0, 'reported_output_tokens': 0,
              'reported_reasoning_tokens': 0, 'responses_with_total_usage': 0,
              'responses_with_input_usage': 0, 'responses_with_output_usage': 0,
              'responses_with_reasoning_usage': 0, 'accounted_attempt_units': len(units),
              'attempt_units_missing_total_usage': 0, 'wire_responses': len(documents),
              'failed_attempts_unavailable_usage': failed_unknown,
              'transport_failure_attempts': sum(e.get('status') != 'SUCCESS' for e in events),
              'http_429_failure_attempts': sum((e.get('error_context') or {}).get('http_status') == 429 for e in events),
              'http_5xx_failure_attempts': sum((e.get('error_context') or {}).get('http_status') in {500, 502, 503, 504} for e in events),
              'timeout_failure_attempts': sum(e.get('status') == 'TIMEOUT' for e in events),
              'output_exhaustion': 0, 'incomplete_responses': 0, 'empty_assistant': 0,
              'reasoning_only_exhaustion': 0}
    for usage in units:
        usage = usage if isinstance(usage, dict) else {}
        mappings = [('total_tokens', 'reported_tokens', 'responses_with_total_usage'),
                    ('input_tokens', 'reported_input_tokens', 'responses_with_input_usage'),
                    ('output_tokens', 'reported_output_tokens', 'responses_with_output_usage')]
        for name, total, count in mappings:
            value = usage.get(name, usage.get({'input_tokens': 'prompt_tokens', 'output_tokens': 'completion_tokens'}.get(name, name)))
            if int_token(value):
                result[total] += value
                result[count] += 1
        reasoning = (usage.get('output_tokens_details') or usage.get('completion_tokens_details') or {}).get('reasoning_tokens')
        if int_token(reasoning):
            result['reported_reasoning_tokens'] += reasoning
            result['responses_with_reasoning_usage'] += 1
        result['attempt_units_missing_total_usage'] += not int_token(usage.get('total_tokens'))
    for document in documents:
        chat = 'choices' in document
        choice = (document.get('choices') or [{}])[0] if chat else {}
        text = (choice.get('message') or {}).get('content') if chat else _extract_output_text(document)
        has_text = isinstance(text, str) and bool(text.strip())
        exhausted = choice.get('finish_reason') == 'length' if chat else (document.get('incomplete_details') or {}).get('reason') == 'max_output_tokens'
        incomplete = choice.get('finish_reason') == 'length' if chat else document.get('status') == 'incomplete'
        result['output_exhaustion'] += exhausted
        result['incomplete_responses'] += incomplete
        result['empty_assistant'] += not has_text
        reasoning_present = (choice.get('message') or {}).get('reasoning_content_chars', document.get('reasoning_content_chars', 0)) if chat else any(o.get('type') == 'reasoning' for o in document.get('output', []))
        result['reasoning_only_exhaustion'] += bool(exhausted and not has_text and reasoning_present)
    # Some recoverable failures retain only normalized error metadata.
    if not documents:
        contexts = [(e.get('error_context') or {}) for e in events]
        if not events:
            contexts = [(r.get('context') or {}) for r in evidence.get('responses', [])]
        for context in contexts:
            exhausted = context.get('finish_reason') == 'length' or context.get('reason') == 'max_output_tokens'
            result['output_exhaustion'] += exhausted
            result['incomplete_responses'] += context.get('provider_status') == 'incomplete'
            result['empty_assistant'] += context.get('reason') == 'NO_FINAL_ASSISTANT_CONTENT'
            result['reasoning_only_exhaustion'] += bool(exhausted and context.get('reason') == 'NO_FINAL_ASSISTANT_CONTENT' and context.get('reasoning_content_chars', 0))
    return result


def expected_payload(source, prompt, config, *, chat):
    user = json.dumps({'source': source}, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    value = {'model': config['model'], 'messages' if chat else 'input': [
        {'role': 'system', 'content': prompt}, {'role': 'user', 'content': user}],
        'temperature': config['temperature'], 'max_tokens' if chat else 'max_output_tokens': config.get('max_tokens', config.get('max_output_tokens')),
        'stream': False}
    if chat:
        value['thinking'] = {'type': 'enabled'}
        if config.get('response_format') == {'type': 'json_object'} or config.get('response_format_json_object'):
            value['response_format'] = {'type': 'json_object'}
    return value


def request_hash(payload):
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))


def resolve_acquisition_binding(root, logical_path, expected_sha256):
    """Preserve the original acquisition key across one publication rename.

    The sole permitted relocation addresses historical V1 package discovery.
    It does not substitute a new implementation: both published runner and
    independently preserved startup snapshot must equal the acquired raw SHA.
    If the original exists, it remains the authority and must match normally.
    """
    root = Path(root)
    original = root / logical_path
    if original.is_file():
        if sha(original.read_bytes()) != expected_sha256:
            raise ValueError('acquisition binding drift: ' + logical_path)
        return original, None
    if logical_path != ACQUISITION_RUNNER_LOGICAL_PATH:
        raise ValueError('missing acquisition path has no authorized relocation: ' + logical_path)
    published = root / PUBLICATION_RUNNER_PATH
    snapshot = root / ACQUISITION_RUNNER_SNAPSHOT
    if not published.is_file() or not snapshot.is_file():
        raise ValueError('relocated acquisition runner or original startup snapshot is unavailable')
    published_raw, snapshot_raw = published.read_bytes(), snapshot.read_bytes()
    if sha(published_raw) != expected_sha256 or sha(snapshot_raw) != expected_sha256 or published_raw != snapshot_raw:
        raise ValueError('relocated acquisition runner/startup snapshot differs from original acquired SHA')
    return published, {'logical_acquisition_path': logical_path,
        'resolved_publication_path': PUBLICATION_RUNNER_PATH,
        'acquisition_snapshot_path': ACQUISITION_RUNNER_SNAPSHOT,
        'expected_acquisition_sha256': expected_sha256,
        'verified_sha256': sha(published_raw), 'verified_snapshot_sha256': sha(snapshot_raw),
        'original_path_absent': True, 'runner_snapshot_bytes_identical': True,
        'namespace_repair_only': True}


def without_timing(value):
    if isinstance(value, dict):
        return {key: without_timing(item) for key, item in value.items() if key not in {'latency_s', 'provider_latency_s'}}
    if isinstance(value, list):
        return [without_timing(item) for item in value]
    return value


def assert_reasoning_sanitized(document):
    if isinstance(document, dict):
        for key, value in document.items():
            if key == 'reasoning_content' and value is not None:
                raise ValueError('raw reasoning text retained')
            assert_reasoning_sanitized(value)
    elif isinstance(document, list):
        for value in document:
            assert_reasoning_sanitized(value)


def sanitized_response(document, first, config):
    """Normalize the preserved wire using the unchanged adapter, offline.

    Adapter interpretation only reads the document; no _post/complete method is
    used. Sanitized reasoning metadata is restored as counts, never as text.
    """
    assert_reasoning_sanitized(document)
    backend = GLMChatCompletionsBackend(GLMChatConfig(
        config['base_url'], 'offline-validator-placeholder',
        temperature=config['temperature'], max_tokens=config['max_tokens'],
        response_format_json_object=config.get('response_format') == {'type': 'json_object'}))
    choice = (document.get('choices') or [{}])[0]
    message = choice.get('message') or {}
    metadata = {'reasoning_content_present': message.get('reasoning_content_present', document.get('reasoning_content_present', False)),
                'reasoning_content_chars': message.get('reasoning_content_chars', document.get('reasoning_content_chars', 0)),
                'normalized_status_basis': 'Chat finish_reason stop/length'}
    try:
        response = asdict(backend._response(document, first['attempts'], first.get('latency_s', 0.0)))
        response['request_parameters']['adapter_response_metadata'] = metadata
        return response
    except LLMBackendError as error:
        context = dict(error.context)
        if 'reasoning_content_present' in context:
            context.update(metadata)
        return {'error_type': 'LLMBackendError', 'failure_type': error.failure_type,
                'attempts': first['attempts'], 'retryable': False, 'context': context}


class ReplayBackend:
    name = 'offline-certificate-replay'

    def __init__(self, first, model):
        self.first = first
        self.model = model
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        if 'text' in self.first:
            return LLMBackendResponse(**self.first)
        raise LLMBackendError(self.first['failure_type'], 'offline replay',
                              attempts=self.first['attempts'], retryable=self.first.get('retryable', False),
                              context=self.first.get('context'))


def audit_stage(output, prior, directory, prompt, config, *, chat):
    errors = []
    source = prior['sample']['source']
    evidence = output['live_evidence']
    called = bool(prior['B']['score']['released'])
    if evidence.get('provider_calls') != int(called):
        errors.append('unexpected provider invocation count')
    if called or not chat:
        receipt = read(directory / 'stage_result.json')
        if receipt != {key: value for key, value in output.items() if key != 'score'}:
            errors.append('sample differs from durable stage receipt')
    if not called:
        if evidence != {'provider_calls': 0, 'provider_attempts': 0, 'events': [], 'responses': []}:
            errors.append('ineligible B acquired provider evidence')
        if list(directory.glob('attempt-*.json')) or (directory / 'response.json').exists():
            errors.append('ineligible B has acquisition ledger')
        if chat:
            if output['result'] != prior['B']['result'] or not output.get('skipped_unreleased_B'):
                errors.append('skipped DG differs from unchanged unreleased B')
            if independent_score(prior['sample'], output['result']) != output['score']:
                errors.append('skipped DG score differs from independent scoring')
            return errors
        first = {'failure_type': 'API_ERROR', 'attempts': 0}
    else:
        started = read(directory / 'started.json')
        expected_started = {'started': True, 'policy': 'never reissue this semantic call after interruption'}
        if chat:
            expected_started['model'] = config['model']
        if started != expected_started:
            errors.append('durable stage started marker/model/policy mismatch')
        payload = expected_payload(source, prompt, config, chat=chat)
        digest = request_hash(payload)
        begins = [read(path) for path in sorted(directory.glob('attempt-*-begin.json'))]
        ends = [read(path) for path in sorted(directory.glob('attempt-*-end.json'))]
        if len(begins) != len(ends) or ends != evidence.get('events') or len(begins) != evidence.get('provider_attempts'):
            errors.append('attempt ledger incomplete or differs from sample')
        if not 1 <= len(begins) <= 3:
            errors.append('attempt ledger exceeds frozen 1..3 budget')
        if [begin.get('index') for begin in begins] != list(range(1, len(begins) + 1)) or [end.get('index') for end in ends] != list(range(1, len(ends) + 1)):
            errors.append('attempt sequence is not contiguous')
        if any(event.get('request_sha256') != digest for event in begins + ends):
            errors.append('full candidate-blind payload hash mismatch')
        if chat:
            request = read(directory / 'request.json')
            if request != {'payload': payload, 'request_sha256': digest, 'request_input_fields': ['source'], 'source_sha256': sha(source)}:
                errors.append('persisted request differs from independently reconstructed source-only payload')
        first = read(directory / 'response.json')
        if evidence.get('responses') != [first]:
            errors.append('first normalized response ledger mismatch')
        if first.get('attempts') != len(begins):
            errors.append('first response attempt count mismatch')
        wires = [event['provider_document'] for event in ends if isinstance(event.get('provider_document'), dict)]
        if len(wires) > 1 or (wires and ends[-1].get('provider_document') != wires[-1]):
            errors.append('semantic first output was retried or wire not final attempt')
        if chat and wires:
            normalized = sanitized_response(wires[0], first, config)
            if without_timing(normalized) != without_timing(first):
                errors.append('first response differs from independently normalized sanitized wire')
        elif not chat and 'text' in first:
            if len(wires) != 1 or _extract_output_text(wires[0]) != first['text']:
                errors.append('DD first response differs from immutable raw wire text')
        elif 'text' in first:
            errors.append('assistant text lacks raw wire binding')
        if 'text' not in first and not wires and ends:
            context = ends[-1].get('error_context')
            if chat and context is not None and context != first.get('context'):
                errors.append('failure context differs from final failed transport attempt')
        diagnostics = detail(output)
        if diagnostics.get('source_sha256') != sha(source) or diagnostics.get('request_input_fields') != ['source']:
            errors.append('certificate source-only diagnostics mismatch')
        if 'text' in first:
            if diagnostics.get('raw_response') != first['text'] or diagnostics.get('raw_response_sha256') != sha(first['text']):
                errors.append('certificate differs from unmodified first response')
            if diagnostics.get('certificate_usable'):
                if parse_certificate(first['text']).to_dict() != diagnostics.get('certificate'):
                    errors.append('stored certificate differs from contract parse')
        elif diagnostics.get('certificate_usable') or diagnostics.get('raw_response') is not None:
            errors.append('unusable response substituted with semantic output')
    replay = ReplayBackend(first, config['model'])
    recomputed = apply_gate(source, old.result_from(prior['B']['result']), SourceAuthorityCertificateIssuer(replay)).to_dict()
    if without_timing(recomputed) != without_timing(output['result']):
        errors.append('deterministic full gate replay differs from recorded result')
    if replay.calls != int(called):
        errors.append('offline gate replay invocation differs from eligibility')
    if independent_score(prior['sample'], output['result']) != output['score']:
        errors.append('score differs from independent frozen-label scoring')
    if output['score']['released'] and output['result'].get('mission') != prior['B']['result'].get('mission'):
        errors.append('release changed historical B candidate')
    if not output['score']['released'] and output['result'].get('mission') is not None:
        errors.append('withheld result retains executable Mission')
    return errors


def audit_preflight(base, receipt, prompt, config):
    """Check the non-scored first certificate and fixed GLM configuration."""
    errors = []
    expected_config = {key: config[key] for key in ('base_url', 'model', 'temperature', 'max_tokens',
        'timeout_s', 'max_network_retries', 'retry_backoff_s', 'retry_statuses', 'max_response_bytes')}
    expected_config.update(response_format_json_object=True, thinking_enabled=True)
    if receipt.get('provider_config') != expected_config:
        errors.append('preflight provider config differs from frozen protocol')
    if receipt.get('checks') != {'approved_configuration_match': True, 'certificate_usable': True,
                                 'certificate_exact': True, 'candidate_blind': True} or not receipt.get('non_scored'):
        errors.append('preflight checks or non-scored classification differs')
    from scripts.glm_preflight_001 import live_preflight as approved
    if receipt.get('fictional_source') != approved.SOURCE:
        errors.append('preflight fictional source changed')
    stage = receipt['typed_certificate']
    directory = base / 'preflight/typed_certificate'
    if stage != read(directory / 'stage_result.json'):
        errors.append('preflight stage differs from durable receipt')
    payload = expected_payload(approved.SOURCE, prompt, config, chat=True)
    digest = request_hash(payload)
    request = read(directory / 'request.json')
    if request != {'payload': payload, 'request_sha256': digest, 'request_input_fields': ['source'], 'source_sha256': sha(approved.SOURCE)}:
        errors.append('preflight full source-only request hash mismatch')
    evidence = stage['live_evidence']
    begins = [read(path) for path in sorted(directory.glob('attempt-*-begin.json'))]
    ends = [read(path) for path in sorted(directory.glob('attempt-*-end.json'))]
    if not 1 <= len(begins) <= 3 or len(ends) != len(begins) or ends != evidence['events'] or len(begins) != evidence['provider_attempts']:
        errors.append('preflight transport ledger incomplete')
    if any(event.get('request_sha256') != digest for event in begins + ends):
        errors.append('preflight request binding changed')
    first = read(directory / 'response.json')
    wires = [event['provider_document'] for event in ends if event.get('provider_document')]
    if evidence['provider_calls'] != 1 or evidence['responses'] != [first] or len(wires) != 1:
        errors.append('preflight first normalized response binding differs')
    elif without_timing(first) != without_timing(sanitized_response(wires[0], first, config)):
        errors.append('preflight normalized response differs from sanitized wire')
    recomputed = SourceAuthorityCertificateIssuer(ReplayBackend(first, config['model'])).issue_certificate(approved.SOURCE).to_dict()
    if without_timing(stage['result']) != without_timing(recomputed) or recomputed['certificate'] != {
            'status': 'AUTHORIZED_UNIQUE', 'checks': ['U'] * 7, 'plan': approved.EXPECTED_PLAN, 'issues': []}:
        errors.append('preflight certificate replay or expected typed plan differs')
    return errors


def validate(root=ROOT, *, partial=False):
    root = Path(root)
    base = root / EXPERIMENT
    inputs = read(base / 'inputs.json')
    protocol = read(base / 'protocol.json')
    old_protocol = read(root / DD / 'protocol.json')
    issues = []
    if protocol['readiness_criteria'] != old_protocol['readiness_criteria']:
        issues.append('inherited readiness thresholds changed')
    if protocol['known_B_unsafe_ids'] != list(KNOWN_UNSAFE):
        issues.append('known unsafe protocol membership changed')
    frozen = inputs['rows']
    expected = {identity(item): item for item in frozen}
    if len(frozen) != 528 or len(expected) != 528 or dict(Counter(item['population'] for item in frozen)) != {'ood': 160, 'phase22b': 179, 'controlled': 189}:
        issues.append('frozen membership differs from 528 original rows')
    original_inputs = read(root / V1 / 'inputs.json')['populations']
    original_by_key = {identity(sample): sample for sample in original_inputs}
    if set(expected) != set(original_by_key):
        issues.append('membership differs from original V1 frozen inputs')
    prompt = (root / 'prompts/authority_certificate_v2.txt').read_bytes().decode('utf8')
    registry = inputs.get('prior_tracked_files')
    if registry:
        tree = {}
        raw_tree = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-r', '-z', protocol['base_commit']])
        for entry in raw_tree.split(b'\0'):
            if entry:
                meta, name = entry.split(b'\t', 1)
                tree[name.decode('utf8')] = meta.decode('ascii').split()[2]
        if len(registry) != len(tree) or {record['path']: record['git_blob'] for record in registry} != tree:
            issues.append('pre-existing tracked raw registry membership/blob mismatch')
        for record in registry:
            path = root / record['path']
            if not path.is_file() or len(path.read_bytes()) != record['bytes'] or sha(path.read_bytes()) != record['sha256']:
                issues.append('pre-existing raw-byte registry drift: ' + record['path'])
    else:
        issues.append('pre-existing raw-byte registry unavailable')
    preflight = read(base / 'preflight.json')
    if not preflight.get('pass'):
        issues.append('DG preflight did not pass')
    hashes = preflight.get('acquisition_hashes', {})
    if not hashes:
        issues.append('acquisition code/input/prompt hashes unavailable')
    relocations = []
    for path, digest in hashes.items():
        try:
            _, relocation = resolve_acquisition_binding(root, path, digest)
            if relocation:
                relocations.append(relocation)
        except ValueError as error:
            issues.append(str(error))
    try:
        issues.extend(audit_preflight(base, preflight, prompt, protocol['provider']))
    except Exception as error:
        issues.append('preflight audit exception ' + type(error).__name__ + ': ' + str(error))
    dd_config = old_protocol['provider']
    seen = set()
    rows = []
    bounded_doc = read(root / V1 / 'bounded_control.json')
    bounded = {identity(record): record for record in bounded_doc['records']}
    for path in sorted((base / 'samples').glob('*.json')):
        row = read(path)
        binding = row['input_binding']
        key = identity(binding)
        if key in seen or key not in expected or binding != expected[key] or path.stem != key:
            issues.append('sample duplicate/unexpected/binding drift: ' + key)
            continue
        seen.add(key)
        prior_path = root / binding['v1_sample_path']
        dd_path = root / binding['dd_sample_path']
        prior = read(prior_path)
        historical = read(dd_path)
        expected_historical_binding = {field: binding[field] for field in ('population', 'sample_id', 'source_sha256', 'v1_sample_path', 'v1_sample_sha256')}
        if historical['input_binding'] != expected_historical_binding:
            issues.append('DD historical input binding differs from exact V1 row: ' + key)
        if binding['v1_sample_path'] != f'{V1}/samples/{key}.json' or binding['dd_sample_path'] != f'{DD}/samples/{key}.json':
            issues.append('historical sample path differs from exact population/sample ID: ' + key)
        if sha(prior_path.read_bytes()) != binding['v1_sample_sha256'] or sha(dd_path.read_bytes()) != binding['dd_sample_sha256']:
            issues.append('immutable historical row byte hash drift: ' + key)
        if prior['sample'] != original_by_key[key] or sha(prior['sample']['source']) != binding['source_sha256']:
            issues.append('source/labels/oracle differ from V1 frozen input: ' + key)
        if binding.get('eligible_B_candidate') is not bool(prior['B']['score']['released']):
            issues.append('frozen B eligibility differs: ' + key)
        for arm, output, directory, config, chat in [
            ('DD', historical['v2'], root / DD / 'acquisition' / key, dd_config, False),
            ('DG', row['dg'], base / 'acquisition' / key, protocol['provider'], True)]:
            try:
                issues.extend(key + '/' + arm + ': ' + issue for issue in audit_stage(output, prior, directory, prompt, config, chat=chat))
            except Exception as error:
                issues.append(key + '/' + arm + ': audit exception ' + type(error).__name__ + ': ' + str(error))
        for arm, output in [('B', prior['B']), ('bounded', bounded[key])]:
            if independent_score(prior['sample'], output['result']) != output['score']:
                issues.append(key + '/' + arm + ': independent score mismatch')
        if bounded[key]['baseline_evidence_sha256'] != binding['v1_sample_sha256']:
            issues.append('bounded candidate byte binding drift: ' + key)
        rows.append({'sample': prior['sample'], 'B': prior['B'], 'DD': historical['v2'], 'DG': row['dg'], 'bounded': bounded[key]})
    missing = sorted(set(expected) - seen)
    if missing and not partial:
        issues.append(f'incomplete DG campaign: {len(missing)} missing')
    unsafe = {row['sample']['sample_id'] for row in rows if row['B']['score']['unauthorized_release']}
    if not partial and unsafe != set(KNOWN_UNSAFE):
        issues.append('known seven unsafe B membership differs')
    calls = sum(row['DG']['live_evidence']['provider_calls'] for row in rows)
    return rows, {'schema': 'cross_model_source_authority_evidence_validation_v1',
        'status': 'FAIL' if issues else 'PASS', 'collection_status': 'COMPLETE' if not missing else 'INCOMPLETE_PARTIAL',
        'final_acceptance_claim': bool(not partial and not missing and not issues),
        'completed_samples': len(rows), 'expected_samples': 528, 'missing_sample_keys': missing,
        'candidate_blind_full_payloads_verified': calls, 'historical_DD_stages_verified': len(rows),
        'acquisition_binding_relocations': relocations,
        'independent_gate_replays': len(rows) + calls, 'preserved_registry_verified': bool(registry),
        'readiness_thresholds_unchanged': protocol['readiness_criteria'] == old_protocol['readiness_criteria'],
        'issues': issues, 'semantic_credit_by_validator': False, 'provider_calls_by_validator': 0, 'runtime_calls_by_validator': 0}


def classification(output):
    diagnostics = detail(output)
    authority = auth(output)
    if not output['live_evidence']['provider_calls']:
        return 'inherited_B_or_guard_skip'
    if not diagnostics.get('certificate_usable'):
        costs = accounting(output['live_evidence'])
        if costs['output_exhaustion']:
            return 'output_budget_exhaustion'
        if authority.get('reason_code') == 'BACKEND_FAILURE':
            return 'provider_or_transport_failure'
        return 'certificate_contract_failure'
    certificate = diagnostics['certificate']
    if certificate['status'] == 'AUTHORIZED_UNIQUE':
        return 'unique_plan_matches_B' if diagnostics.get('plan_matches_candidate') else 'unique_plan_disagrees_with_B'
    issues = certificate['issues']
    if any(issue['relation'] == 'unknown' or issue['reason'] == 'UNKNOWN' for issue in issues):
        return 'usable_generic_UNKNOWN'
    return 'usable_specific_rejection_review_candidate'


def metrics(rows, arm):
    outputs = [row[arm] for row in rows]
    called = [output for output in outputs if output['live_evidence']['provider_calls']]
    costs = [accounting(output['live_evidence']) for output in called]
    valid = [row[arm] for row in rows if row['sample']['expected_status'] == 'SUCCESS']
    baseline_exact = [row for row in rows if row['B']['score']['valid_exact']]
    times = [output['added_wall_s'] for output in called if output.get('added_wall_s') is not None]
    local = [output['added_wall_s'] for output in outputs if output.get('added_wall_s') is not None] if arm == 'bounded' else []
    total = sum(cost['reported_tokens'] for cost in costs)
    usable = sum(bool(detail(output).get('certificate_usable')) for output in called) if arm in {'DD', 'DG'} else None
    result = {'n': len(rows), 'valid_n': len(valid), 'released': sum(o['score']['released'] for o in outputs),
        'unauthorized_release': sum(o['score']['unauthorized_release'] for o in outputs),
        'valid_exact': sum(o['score']['valid_exact'] for o in valid),
        'valid_exact_coverage': sum(o['score']['valid_exact'] for o in valid) / len(valid) if valid else None,
        'false_rejection': sum(o['score']['false_rejection'] for o in valid), 'wrong_ir': sum(o['score']['wrong_ir'] for o in valid),
        'B_exact_valid_n': len(baseline_exact), 'B_exact_valid_retained': sum(row[arm]['score']['valid_exact'] for row in baseline_exact),
        'B_exact_valid_retention_rate': sum(row[arm]['score']['valid_exact'] for row in baseline_exact) / len(baseline_exact) if baseline_exact else None,
        'incremental_false_rejection_ids': [identity(row['sample']) for row in baseline_exact if row[arm]['score']['false_rejection']],
        'called': len(called), 'usable': usable, 'usable_rate': usable / len(called) if usable is not None and called else None,
        'new_provider_calls': sum(o['live_evidence']['provider_calls'] for o in called) if arm == 'DG' else 0,
        'retained_recorded_provider_calls': sum(o['live_evidence']['provider_calls'] for o in called),
        'transport_attempts': sum(o['live_evidence']['provider_attempts'] for o in called),
        'mean_reported_tokens_per_called_stage': total / len(called) if called else None,
        'added_wall_median_s': statistics.median(times) if times else None, 'added_wall_p95_s': old.quantile(times, .95),
        'latency_sample_n': len(times), 'called_stages_without_live_wall_latency': len(called) - len(times),
        'local_added_wall_median_s': statistics.median(local) if local else None, 'local_added_wall_p95_s': old.quantile(local, .95),
        'authorization_status': dict(Counter(auth(o).get('status', 'NOT_EVALUATED')
            if auth(o).get('reason_code') not in {'GUARD_REJECT', 'NO_LEGAL_CANDIDATE'} and (arm == 'bounded' or o['live_evidence']['provider_calls'])
            else 'NOT_EVALUATED' for o in outputs)),
        'authorization_reasons': dict(Counter(auth(o).get('reason_code', 'NOT_EVALUATED') for o in outputs)),
        'certificate_candidate_disagreement': sum(auth(o).get('reason_code') == 'AUTHORIZED_PLAN_DISAGREEMENT' for o in outputs),
        'called_stages_with_missing_attempt_usage': sum(bool(cost['attempt_units_missing_total_usage']) for cost in costs),
        'called_stages_without_any_reported_total_usage': sum(cost['responses_with_total_usage'] == 0 for cost in costs),
        'called_stages_with_429': sum(bool(cost['http_429_failure_attempts']) for cost in costs),
        'final_backend_failure_context_reasons': dict(Counter((response.get('context') or {}).get('reason', 'UNAVAILABLE_IN_HISTORICAL_EVIDENCE')
            for output in called for response in output['live_evidence']['responses'] if 'text' not in response)),
        'failure_taxonomy': dict(Counter(classification(o) for o in outputs)) if arm in {'DD', 'DG'} else {}}
    for field in accounting({'events': [], 'responses': []}):
        result[field] = sum(cost[field] for cost in costs)
    result['output_exhaustion_rate'] = result['output_exhaustion'] / len(called) if called else None
    covered_stages = sum(cost['responses_with_total_usage'] > 0 for cost in costs)
    result['mean_reported_tokens_per_stage_with_any_reported_usage'] = total / covered_stages if covered_stages else None
    result['billed_monetary_cost'] = 'UNVERIFIED_NO_PRICE_ASSUMPTION'
    result['reported_tokens_are_lower_bound_when_usage_missing'] = bool(result['attempt_units_missing_total_usage'])
    return result


def paired(rows):
    exact = [row for row in rows if row['B']['score']['valid_exact']]
    table = Counter((bool(row['DD']['score']['valid_exact']), bool(row['DG']['score']['valid_exact'])) for row in exact)
    resource = Counter()
    disagreement = []
    plans = []
    certificate_comparison = Counter()
    for row in rows:
        dd, dg = row['DD'], row['DG']
        if not dd['live_evidence']['provider_calls'] and not dg['live_evidence']['provider_calls']:
            continue
        dc, gc = classification(dd), classification(dg)
        dr = dc in {'output_budget_exhaustion', 'provider_or_transport_failure'}
        gr = gc in {'output_budget_exhaustion', 'provider_or_transport_failure'}
        if dd['live_evidence']['provider_calls']:
            resource['shared' if dr and gr else 'DD_only' if dr else 'DG_only' if gr else 'neither'] += 1
        a, b = auth(dd), auth(dg)
        if a.get('status') != b.get('status') or a.get('reason_code') != b.get('reason_code'):
            disagreement.append({'sample_key': identity(row['sample']), 'population': row['sample']['population'], 'split': row['sample']['split'],
                                 'DD': {'status': a.get('status'), 'reason': a.get('reason_code'), 'taxonomy': dc},
                                 'DG': {'status': b.get('status'), 'reason': b.get('reason_code'), 'taxonomy': gc}})
        x, y = detail(dd).get('certificate'), detail(dg).get('certificate')
        if x and y:
            certificate_comparison['both_usable'] += 1
            certificate_comparison['status_disagrees'] += x['status'] != y['status']
            certificate_comparison['checks_disagree'] += x['checks'] != y['checks']
            certificate_comparison['typed_issues_disagree'] += x['issues'] != y['issues']
        if x and y and x['status'] == y['status'] == 'AUTHORIZED_UNIQUE' and x['plan'] != y['plan']:
            plans.append({'sample_key': identity(row['sample']), 'DD_plan': x['plan'], 'DG_plan': y['plan']})
    return {'B_exact_valid_n': len(exact), 'both_retained': table[(True, True)],
            'DG_recovered_from_DD': table[(False, True)], 'DG_lost_from_DD': table[(True, False)],
            'both_lost': table[(False, False)],
            'DG_recovered_ids': [identity(row['sample']) for row in exact if not row['DD']['score']['valid_exact'] and row['DG']['score']['valid_exact']],
            'DG_lost_ids': [identity(row['sample']) for row in exact if row['DD']['score']['valid_exact'] and not row['DG']['score']['valid_exact']],
            'resource_failure_pairing': dict(resource), 'status_disagreement_count': sum(d['DD']['status'] != d['DG']['status'] for d in disagreement),
            'reason_disagreement_count': sum(d['DD']['reason'] != d['DG']['reason'] for d in disagreement),
            'authority_or_reason_disagreement_count': len(disagreement), 'unique_plan_disagreement_count': len(plans),
            'paired_usable_certificate_comparison': dict(certificate_comparison),
            'disagreements': disagreement, 'unique_plan_disagreements': plans}


def analyze_rows(rows, protocol):
    cohorts = {'all': rows}
    for row in rows:
        sample = row['sample']
        cohorts.setdefault(sample['population'], []).append(row)
        if sample['population'] == 'ood':
            cohorts.setdefault('ood:' + sample['split'], []).append(row)
    summary = {'schema': 'cross_model_source_authority_summary_v1', 'experiment_id': 'source_authority_cross_model_001',
        'evidence_role': 'already_seen_development_regression_pilot',
        'cohorts': {key: {arm: metrics(group, arm) for arm in ('B', 'DD', 'DG', 'bounded')} for key, group in cohorts.items()},
        'paired': {key: paired(group) for key, group in cohorts.items()},
        'readiness_criteria': protocol['readiness_criteria'], 'independent_semantic_review_required': True,
        'semantic_success_claim': False, 'D011': 'CANDIDATE_NOT_ADOPTED', 'runtime_gate': 'BLOCKED',
        'held_out_started': False, 'runtime_started': False,
        'cost_limitations': ['Each attempt usage counted once, normalized response is only fallback when no ledger.',
                             'Missing usage is unavailable, not zero known cost.', 'B and DD costs and timings are historical.',
                             'DD/DG latency is longitudinal paired workload; B latency is not added as measured live end-to-end.',
                             'Provider reported totals and components are retained verbatim; no component sum substitutes for totals.',
                             'Reasoning tokens are included in provider output totals, never added a second time.',
                             'Monetary billing and package deduction unverified; no price assumptions.']}
    unsafe = []
    for row in rows:
        if not row['B']['score']['unauthorized_release']:
            continue
        sample = row['sample']
        cases = {}
        for arm in ('DD', 'DG', 'bounded'):
            output = row[arm]
            certificate = detail(output).get('certificate')
            cases[arm] = {'score': output['score'], 'status': auth(output).get('status'), 'reason_code': auth(output).get('reason_code'),
                'usable': bool(detail(output).get('certificate_usable')), 'certificate': certificate,
                'taxonomy': classification(output) if arm != 'bounded' else 'bounded_control',
                'specific_semantic_rejection_review_candidate': arm != 'bounded' and classification(output) == 'usable_specific_rejection_review_candidate',
                'semantic_credit': None if arm != 'bounded' else False,
                'certificate_false_unique_matches_B': bool(certificate and certificate['status'] == 'AUTHORIZED_UNIQUE' and detail(output).get('plan_matches_candidate')),
                'certificate_false_unique_host_mismatch': bool(certificate and certificate['status'] == 'AUTHORIZED_UNIQUE' and not detail(output).get('plan_matches_candidate')),
                'accounting': accounting(output['live_evidence'])}
        unsafe.append({'sample_id': sample['sample_id'], 'sample_key': identity(sample), 'population': sample['population'],
                       'split': sample['split'], 'source': sample['source'], 'B_candidate': row['B']['result']['mission'], 'arms': cases})
    order = {sample_id: index for index, sample_id in enumerate(KNOWN_UNSAFE)}
    unsafe.sort(key=lambda case: order.get(case['sample_id'], 99))
    dependencies = {'compiler_unsafe_n': len(unsafe),
        'both_verifiers_false_unique_match_B': [case['sample_id'] for case in unsafe if all(case['arms'][arm]['certificate_false_unique_matches_B'] for arm in ('DD', 'DG'))],
        'DD_false_unique_match_B': [case['sample_id'] for case in unsafe if case['arms']['DD']['certificate_false_unique_matches_B']],
        'DG_false_unique_match_B': [case['sample_id'] for case in unsafe if case['arms']['DG']['certificate_false_unique_matches_B']],
        'DD_false_unique_host_mismatch': [case['sample_id'] for case in unsafe if case['arms']['DD']['certificate_false_unique_host_mismatch']],
        'DG_false_unique_host_mismatch': [case['sample_id'] for case in unsafe if case['arms']['DG']['certificate_false_unique_host_mismatch']],
        'both_resource_fail_closed': [case['sample_id'] for case in unsafe if all(case['arms'][arm]['taxonomy'] in {'output_budget_exhaustion', 'provider_or_transport_failure'} for arm in ('DD', 'DG'))],
        'limitation': 'Seven known selected unsafe candidates cannot estimate statistical error independence. Shared contracts and semantic priors remain.'}
    dg = summary['cohorts']['all']['DG']
    summary['operational_checks_excluding_semantic_review'] = {
        'zero_unauthorized': dg['unauthorized_release'] == 0,
        'usable_rate': dg['usable'] >= 277, 'valid_retention': dg['B_exact_valid_retained'] >= 270,
        'primary_retention': summary['cohorts']['ood:primary_gold']['DG']['B_exact_valid_retained'] >= 70,
        'phase22b_retention': summary['cohorts']['phase22b']['DG']['B_exact_valid_retained'] >= 66,
        'controlled_retention': summary['cohorts']['controlled']['DG']['B_exact_valid_retained'] >= 131,
        'exhaustion': dg['output_exhaustion'] <= 14,
        'token_cost': dg['mean_reported_tokens_per_called_stage'] is not None and dg['mean_reported_tokens_per_called_stage'] <= 2051.47,
        'median_latency': dg['added_wall_median_s'] is not None and dg['added_wall_median_s'] <= 5,
        'p95_latency': dg['added_wall_p95_s'] is not None and dg['added_wall_p95_s'] <= 12}
    return summary, {'known_unsafe_cases': unsafe, 'dependent_failure_analysis': dependencies,
                     'all_disagreements': summary['paired']['all']['disagreements'],
                     'unique_plan_disagreements': summary['paired']['all']['unique_plan_disagreements'],
                     'semantic_credit_pending_independent_review': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--partial', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    rows, validation = validate(args.root, partial=args.partial)
    base = args.root / EXPERIMENT
    if args.validate:
        if args.output:
            write(args.output, validation)
    else:
        write(base / 'evidence_validation.json', validation)
        if validation['status'] != 'PASS' or args.partial:
            print(json.dumps(validation, ensure_ascii=False))
            return 1
        summary, analysis = analyze_rows(rows, read(base / 'protocol.json'))
        write(base / 'summary.json', summary)
        write(base / 'analysis.json', analysis)
    print(json.dumps({key: validation[key] for key in ('status', 'collection_status', 'completed_samples', 'final_acceptance_claim')}, ensure_ascii=False))
    return 0 if validation['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
