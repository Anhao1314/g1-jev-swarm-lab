"""Additive development DD/DG pilot; historic B/DD, one source-only GLM call.

No Runtime, held-out acquisition, candidate-informed requests, semantic retries,
credential discovery, provider fallback, or reasoning text persistence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping

from scripts import run_authority_certificate_v2_pilot as dd
from scripts.glm_preflight_001 import live_preflight as approved
from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer
from g1swarm.glm_preflight_001 import GLMChatConfig, create_backend
from g1swarm.glm_preflight_001.chat_backend import GLMChatCompletionsBackend
from g1swarm.llm.backend import LLMBackendError, LLMBackendResponse, LLMConfigurationError
from g1swarm.source_authority import apply_gate

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'experiments/phase2/source_authority_cross_model_001'
STARTING_COMMIT = '9dc3a83cdb9a4c1e092ab42bedfc807c9388015e'
MODEL = approved.MODEL
read, write, sha = dd.read, dd.write, dd.sha


def _git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], cwd=ROOT)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf8')


def prior_inventory() -> list[dict[str, Any]]:
    """Raw checkout hashes alongside Git blobs; no newline normalization."""
    records = []
    for entry in _git('ls-tree', '-r', '-z', STARTING_COMMIT).split(b'\0'):
        if not entry:
            continue
        meta, raw_name = entry.split(b'\t', 1)
        mode, kind, oid = meta.decode('ascii').split()
        name = raw_name.decode('utf8')
        path = ROOT / name
        if kind != 'blob' or mode not in {'100644', '100755'} or path.is_symlink():
            raise ValueError('unsupported pre-existing tracked file')
        raw = path.read_bytes()
        records.append({'path': name, 'git_blob': oid, 'bytes': len(raw), 'sha256': sha(raw)})
    return sorted(records, key=lambda item: item['path'])


def verify_prior(inputs: Mapping[str, Any] | None = None) -> None:
    """Every old path is immutable; additive untracked outputs are independent."""
    try:
        _git('merge-base', '--is-ancestor', STARTING_COMMIT, 'HEAD')
    except subprocess.CalledProcessError:
        raise ValueError('pilot starting commit is not an ancestor of HEAD') from None
    anchor = {}
    for entry in _git('ls-tree', '-r', '-z', STARTING_COMMIT).split(b'\0'):
        if entry:
            meta, name = entry.split(b'\t', 1)
            anchor[name.decode('utf8')] = meta.decode('ascii').split()[2]
    changed = _git('diff', '--name-only', STARTING_COMMIT, '--').decode().splitlines()
    protected_changes = sorted(set(changed) & set(anchor))
    if protected_changes:
        raise ValueError('pre-existing tracked evidence/code changed: ' + ', '.join(protected_changes))
    if inputs is not None:
        registry = inputs['prior_tracked_files']
        if (len(registry) != len(anchor) or {record['path']: record['git_blob'] for record in registry} != anchor):
            raise ValueError('pre-existing tracked-file registry membership/blob drift')
        for record in registry:
            raw = (ROOT / record['path']).read_bytes()
            if len(raw) != record['bytes'] or sha(raw) != record['sha256']:
                raise ValueError('pre-existing raw bytes changed: ' + record['path'])


def prepare() -> dict[str, Any]:
    verify_prior()
    rows = dd.original_rows()
    frozen = []
    for path, prior in rows:
        sample = prior['sample']
        dd_path = dd.BASE / 'samples' / f"{sample['population']}--{sample['sample_id']}.json"
        old_dd = read(dd_path)
        old_binding = old_dd['input_binding']
        if old_binding['v1_sample_sha256'] != sha(path.read_bytes()):
            raise ValueError('historical DD has different V1 source/candidate')
        frozen.append({'population': sample['population'], 'sample_id': sample['sample_id'],
            'source_sha256': sha(sample['source'].encode('utf8')),
            'v1_sample_path': path.relative_to(ROOT).as_posix(),
            'v1_sample_sha256': sha(path.read_bytes()),
            'dd_sample_path': dd_path.relative_to(ROOT).as_posix(),
            'dd_sample_sha256': sha(dd_path.read_bytes()),
            'eligible_B_candidate': bool(prior['B']['score']['released'])})
    if len(frozen) != 528 or sum(row['eligible_B_candidate'] for row in frozen) != 291:
        raise ValueError('development population changed')
    document = {'schema': 'cross_model_source_authority_inputs_v1',
        'starting_commit': STARTING_COMMIT, 'sample_count': len(frozen),
        'eligible_B_candidates': sum(row['eligible_B_candidate'] for row in frozen),
        'prior_tracked_files': prior_inventory(), 'rows': frozen,
        'bounded_control_sha256': sha((dd.V1 / 'bounded_control.json').read_bytes()),
        'v1_inputs_sha256': sha((dd.V1 / 'inputs.json').read_bytes()),
        'historical_dd_inputs_sha256': sha((dd.BASE / 'inputs.json').read_bytes()),
        'comparison_design': 'paired identical sources/candidates; historical DD versus later DG; longitudinal provider/time confounding',
        'development_only': True, 'fresh_held_out': False, 'runtime_calls': 0}
    write(BASE / 'inputs.json', document)
    return {'prepared': len(frozen), 'eligible': document['eligible_B_candidates'],
            'prior_tracked_files': len(document['prior_tracked_files']), 'provider_calls': 0}


def binding() -> dict[str, str]:
    paths = [Path(__file__), BASE / 'inputs.json', BASE / 'protocol.json', BASE / 'CONTRACT.md',
        ROOT / 'src/g1swarm/authority_certificate_v2.py', ROOT / 'prompts/authority_certificate_v2.txt',
        ROOT / 'src/g1swarm/glm_preflight_001/chat_backend.py',
        ROOT / 'src/g1swarm/glm_preflight_001/selector.py',
        ROOT / 'src/g1swarm/source_authority/authorization.py',
        ROOT / 'scripts/run_source_authority_pilot.py',
        ROOT / 'scripts/run_authority_certificate_v2_pilot.py',
        ROOT / 'scripts/glm_preflight_001/live_preflight.py',
        ROOT / 'experiments/provider_glm_preflight_001/current_live_receipt.json',
        ROOT / 'experiments/provider_glm_preflight_001/live_profile.json']
    pointer = read(ROOT / 'experiments/provider_glm_preflight_001/current_live_receipt.json')
    paths.append(ROOT / pointer['receipt_path'])
    return {path.relative_to(ROOT).as_posix(): sha(path.read_bytes()) for path in paths}


def resolve_provider() -> tuple[GLMChatConfig, dict[str, Any]]:
    """Only caller-supplied process GLM_API_KEY; no store/User-env discovery."""
    key = os.environ.get('GLM_API_KEY', '')
    if not key:
        raise LLMConfigurationError('explicit process GLM_API_KEY required; no scored calls started')
    config = GLMChatConfig(approved.BASE_URL, key, response_format_json_object=True)
    create_backend(MODEL, glm_config=config)  # Explicit independent selector; no fallback.
    return config, {'provider_id': MODEL, 'model': MODEL, 'base_url': config.base_url,
        'path': '/chat/completions', 'credential_source': 'explicit caller process GLM_API_KEY',
        'credential_or_hash_persisted': False, 'automatic_fallback': False,
        'config': public_config(config)}


def public_config(config: GLMChatConfig) -> dict[str, Any]:
    return {key: sorted(value) if isinstance(value, frozenset) else value
            for key, value in asdict(config).items() if key != 'api_key'}


def _safe_context(error: Exception) -> dict[str, Any]:
    context = error.context if isinstance(error, LLMBackendError) else {}
    output: dict[str, Any] = {}
    for key, choices in [('category', approved._CATEGORIES), ('reason', approved._ERROR_REASONS),
        ('finish_reason', {'stop', 'length'}), ('provider_status', {'completed', 'incomplete'})]:
        if isinstance(context.get(key), str) and context[key] in choices:
            output[key] = context[key]
    for key in ['http_status', 'reasoning_content_chars']:
        if approved._int(context.get(key)):
            output[key] = context[key]
    if isinstance(context.get('reasoning_content_present'), bool):
        output['reasoning_content_present'] = context['reasoning_content_present']
    usage = approved._safe_usage(context.get('usage'))
    if usage is not None:
        output['usage'] = usage
    if context.get('normalized_status_basis') == 'Chat finish_reason stop/length':
        output['normalized_status_basis'] = context['normalized_status_basis']
    return output


class GLMJournalBackend(GLMChatCompletionsBackend):
    """Record first response/attempts without saving or hashing raw reasoning."""

    def __init__(self, config: GLMChatConfig, directory: Path | None = None):
        super().__init__(config)
        self.directory = directory
        self.calls = 0
        self.events: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        if directory:
            directory.mkdir(parents=True, exist_ok=True)

    def safe(self, value: Any) -> Any:
        # Check ALL raw wire fields, including reasoning, before any hash/write.
        if self.config.api_key in json.dumps(value, ensure_ascii=False, allow_nan=False):
            raise LLMBackendError('API_ERROR', 'credential echo rejected',
                context={'category': 'OUTPUT', 'reason': 'CREDENTIAL_ECHO'})
        return value

    def persist(self, name: str, value: Any) -> None:
        checked = self.safe(value)
        if self.directory:
            write(self.directory / name, checked)

    def _wire(self, document: Mapping[str, Any]) -> dict[str, Any]:
        self.safe(document)
        output = {key: document[key] for key in ['id', 'model', 'created'] if key in document}
        usage = document.get('usage')
        if isinstance(usage, dict):
            output['usage'] = {key: value for key, value in usage.items()
                if key in {'prompt_tokens', 'completion_tokens', 'input_tokens', 'output_tokens', 'total_tokens',
                           'prompt_tokens_details', 'completion_tokens_details'}
                and (value is None or approved._int(value) or isinstance(value, dict))}
            for key in ['prompt_tokens_details', 'completion_tokens_details']:
                if isinstance(output['usage'].get(key), dict):
                    output['usage'][key] = {name: value for name, value in output['usage'][key].items()
                        if name in {'cached_tokens', 'reasoning_tokens'} and approved._int(value)}
        choices = document.get('choices')
        if isinstance(choices, list):
            output['choices'] = []
            for choice in choices:
                if not isinstance(choice, dict):
                    output['choices'].append(None)
                    continue
                kept = {key: choice[key] for key in ['index', 'finish_reason'] if key in choice}
                message = choice.get('message')
                if isinstance(message, dict):
                    reasoning = message.get('reasoning_content')
                    kept['message'] = {key: message[key] for key in ['role', 'content'] if key in message}
                    kept['message'].update({'reasoning_content': None,
                        'reasoning_content_present': 'reasoning_content' in message,
                        'reasoning_content_chars': len(reasoning) if isinstance(reasoning, str) else 0})
                output['choices'].append(kept)
        return output

    def complete(self, *, system_prompt: str, user_text: str) -> LLMBackendResponse:
        if self.calls:
            raise LLMBackendError('API_ERROR', 'semantic call cannot be reused', attempts=0)
        self.calls += 1
        payload = self.safe(self._payload(system_prompt, user_text))
        parsed = json.loads(user_text)
        if not isinstance(parsed, dict) or set(parsed) != {'source'} or not isinstance(parsed['source'], str):
            raise ValueError('candidate-blind source-only request required')
        self.persist('request.json', {'payload': payload, 'request_sha256': sha(_canonical(payload)),
            'request_input_fields': ['source'], 'source_sha256': sha(parsed['source'].encode('utf8'))})
        try:
            response = super().complete(system_prompt=system_prompt, user_text=user_text)
            saved = self.safe(asdict(response))
            self.responses.append(saved)
            self.persist('response.json', saved)
            return response
        except Exception as error:
            # Never persist exception messages, arbitrary contexts, or fingerprints.
            saved = {'error_type': 'LLMBackendError' if isinstance(error, LLMBackendError) else 'InternalError',
                'failure_type': getattr(error, 'failure_type', 'API_ERROR'),
                'attempts': getattr(error, 'attempts', len(self.events)),
                'retryable': bool(getattr(error, 'retryable', False)), 'context': _safe_context(error)}
            self.responses.append(saved)
            self.persist('response.json', saved)
            raise

    def _post(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        checked = self.safe(payload)
        index = len(self.events) + 1
        event = {'index': index, 'request_sha256': sha(_canonical(checked))}
        self.persist(f'attempt-{index:02d}-begin.json', event)
        started = time.perf_counter()
        try:
            document = super()._post(payload)
            safe_wire = self._wire(document)
            event.update(status='SUCCESS', provider_document=safe_wire)
            return document
        except Exception as error:
            event.update(status=getattr(error, 'failure_type', 'INTERNAL_ERROR'),
                error_type='LLMBackendError' if isinstance(error, LLMBackendError) else 'InternalError',
                error_context=_safe_context(error))
            raise
        finally:
            event['latency_s'] = time.perf_counter() - started
            self.events.append(event)
            self.persist(f'attempt-{index:02d}-end.json', event)

    def evidence(self) -> dict[str, Any]:
        return {'provider_calls': self.calls, 'provider_attempts': len(self.events),
                'events': self.events, 'responses': self.responses,
                'raw_reasoning_persisted': False, 'credential_or_hash_persisted': False}


class RecoveryBackend:
    """Reuse first saved GLM response or fail closed; never repeat a started call."""
    name = 'durable_glm_first_response_recovery'
    model = MODEL

    def __init__(self, directory: Path, config: GLMChatConfig):
        self.directory, self.config, self.requests = directory, config, 0

    def request_parameters(self):
        return GLMChatCompletionsBackend(self.config).request_parameters()

    def complete(self, *, system_prompt: str, user_text: str) -> LLMBackendResponse:
        self.requests += 1
        path = self.directory / 'response.json'
        request_path = self.directory / 'request.json'
        expected = GLMChatCompletionsBackend(self.config)._payload(system_prompt, user_text)
        if request_path.exists() and read(request_path)['request_sha256'] != sha(_canonical(expected)):
            raise ValueError('recovered request hash changed')
        if not path.exists():
            raise LLMBackendError('API_ERROR', 'interrupted first response unavailable; no new call', attempts=0)
        response = GLMJournalBackend(self.config).safe(read(path))
        if 'error_type' in response:
            raise LLMBackendError(response.get('failure_type', 'API_ERROR'), 'saved first GLM failure',
                attempts=response.get('attempts') or 0, context=response.get('context', {}))
        return LLMBackendResponse(**response)

    def evidence(self):
        begins = list(self.directory.glob('attempt-*-begin.json'))
        ends = [read(path) for path in sorted(self.directory.glob('attempt-*-end.json'))]
        path = self.directory / 'response.json'
        return {'provider_calls': self.requests, 'provider_attempts': len(begins), 'events': ends,
            'responses': [read(path)] if path.exists() else [], 'recovered_without_new_call': True,
            'interrupted_response_unavailable': not path.exists(), 'unmatched_attempts': len(begins) - len(ends),
            'raw_reasoning_persisted': False, 'credential_or_hash_persisted': False}


def durable_stage(directory: Path, config: GLMChatConfig, evaluate) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    receipt, marker = directory / 'stage_result.json', directory / 'started.json'
    if receipt.exists():
        return GLMJournalBackend(config).safe(read(receipt))
    recovered = marker.exists()
    if recovered:
        backend = RecoveryBackend(directory, config)
    else:
        write(marker, {'started': True, 'model': MODEL,
            'policy': 'never reissue this semantic call after interruption'})
        backend = GLMJournalBackend(config, directory)
    started = time.perf_counter()
    result = evaluate(backend)
    value = {'result': result.to_dict(), 'added_wall_s': None if recovered else time.perf_counter() - started,
             'live_evidence': backend.evidence(), 'recovered': recovered}
    checked = GLMJournalBackend(config).safe(value)
    write(receipt, checked)
    return checked


def prior_preflight(config: GLMChatConfig) -> dict[str, Any]:
    pointer = read(ROOT / 'experiments/provider_glm_preflight_001/current_live_receipt.json')
    raw = (ROOT / pointer['receipt_path']).read_bytes()
    if sha(raw) != pointer['receipt_sha256'] or not pointer['ready_for_cross_model_pilot']:
        raise ValueError('approved GLM preflight receipt changed/unready')
    receipt = json.loads(raw)
    typed = next(record for record in receipt['checks'] if record['name'] == 'typed_certificate')
    expected = GLMChatCompletionsBackend(config).request_parameters()
    parameters = typed['response']['request_parameters']
    if (not receipt['ready'] or not typed['passed'] or receipt['provider_id'] != MODEL
        or any(parameters.get(key) != value for key, value in expected.items())
        or parameters.get('timeout_s') != config.timeout_s
        or config.base_url != approved.BASE_URL or config.max_response_bytes != 1048576
        or typed['certificate'] != {'status': 'AUTHORIZED_UNIQUE', 'checks': ['U'] * 7,
                                    'plan': approved.EXPECTED_PLAN, 'issues': []}):
        raise ValueError('fixed approved GLM configuration drift')
    return {'receipt_path': pointer['receipt_path'], 'receipt_sha256': sha(raw),
            'configuration_match': True, 'reasoning_effort': 'provider_default_not_sent'}


def preflight(config: GLMChatConfig, provider_binding: dict, acquired: dict) -> None:
    reference = prior_preflight(config)
    stage = durable_stage(BASE / 'preflight/typed_certificate', config,
        lambda backend: SourceAuthorityCertificateIssuer(backend).issue_certificate(approved.SOURCE))
    outcome = stage['result']
    checks = {'approved_configuration_match': True, 'certificate_usable': outcome['usable'],
        'certificate_exact': outcome['certificate'] == {'status': 'AUTHORIZED_UNIQUE', 'checks': ['U'] * 7,
            'plan': approved.EXPECTED_PLAN, 'issues': []},
        'candidate_blind': outcome['diagnostics'].get('request_input_fields') == ['source']}
    document = {'pass': all(checks.values()), 'checks': checks, 'provider_binding': provider_binding,
        'provider_config': public_config(config), 'acquisition_hashes': acquired,
        'approved_live_reference': reference, 'fictional_source': approved.SOURCE, 'typed_certificate': stage,
        'non_scored': True, 'scored_calls_started': False, 'runtime_calls': 0, 'held_out_calls': 0}
    write(BASE / 'preflight.json', GLMJournalBackend(config).safe(document))
    if not document['pass']:
        raise ValueError('fictional typed preflight failed; no scored calls started')


def collect(workers: int, resume: bool = False) -> dict[str, Any]:
    if not 1 <= workers <= 4:
        raise ValueError('workers must be within 1..4')
    inputs = read(BASE / 'inputs.json')
    verify_prior(inputs)
    config, provider_binding = resolve_provider()
    acquired = binding()
    if (BASE / 'preflight.json').exists():
        if not resume:
            raise FileExistsError('preflight receipt exists; use explicit resume')
        receipt = read(BASE / 'preflight.json')
        if not receipt['pass'] or receipt['acquisition_hashes'] != acquired or receipt['provider_binding'] != provider_binding:
            raise ValueError('cannot resume after code/input/provider drift')
        prior_preflight(config)
    else:
        preflight(config, provider_binding, acquired)

    def one(item):
        path = ROOT / item['v1_sample_path']
        dd_path = ROOT / item['dd_sample_path']
        if sha(path.read_bytes()) != item['v1_sample_sha256'] or sha(dd_path.read_bytes()) != item['dd_sample_sha256']:
            raise ValueError('historical source/B/DD evidence changed')
        prior = read(path)
        if sha(prior['sample']['source'].encode('utf8')) != item['source_sha256']:
            raise ValueError('source binding changed')
        output = BASE / 'samples' / f"{item['population']}--{item['sample_id']}.json"
        if output.exists():
            if not resume:
                raise FileExistsError(output)
            if read(output)['input_binding'] != item:
                raise ValueError('resumed sample input binding changed')
            return
        baseline = dd.old.result_from(prior['B']['result'])
        if baseline.success != item['eligible_B_candidate']:
            raise ValueError('historical B eligibility changed')
        if baseline.success:
            stage = durable_stage(BASE / 'acquisition' / f"{item['population']}--{item['sample_id']}", config,
                lambda backend: apply_gate(prior['sample']['source'], baseline, SourceAuthorityCertificateIssuer(backend)))
        else:
            # Existing host policy bypasses the verifier for an unreleased B.
            stage = {'result': baseline.to_dict(), 'added_wall_s': 0.0, 'recovered': False,
                'live_evidence': {'provider_calls': 0, 'provider_attempts': 0, 'events': [], 'responses': []},
                'skipped_unreleased_B': True}
        stage['score'] = dd.old.score(prior['sample'], dd.old.result_from(stage['result']))
        write(output, GLMJournalBackend(config).safe({'input_binding': item, 'dg': stage}))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, item) for item in inputs['rows']]
        for completed, future in enumerate(as_completed(futures), 1):
            future.result()
            if completed % 20 == 0 or completed == len(futures):
                print(json.dumps({'completed': completed, 'total': len(futures)}), flush=True)
    if binding() != acquired:
        raise ValueError('acquisition code/inputs changed during pilot')
    verify_prior(inputs)
    return {'completed': len(inputs['rows']), 'eligible_DG': inputs['eligible_B_candidates'],
            'historical_DD_retained': True, 'B_reruns': 0, 'DD_reruns': 0, 'runtime_calls': 0, 'held_out_calls': 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'collect'])
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    result = prepare() if args.stage == 'prepare' else collect(args.workers, args.resume)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
