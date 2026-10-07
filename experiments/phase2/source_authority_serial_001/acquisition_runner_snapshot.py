"""Additive one-worker GLM development treatment over immutable prior evidence.

Only verifier scheduling changes. Historical DD/DG4 and B remain raw-byte frozen;
the source-only v2 issuer, transport retries, first-response journal and host gate
are imported unchanged. No Runtime, held-out acquisition or model fallback.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping
import uuid

from scripts import run_cross_model_certificate_pilot as historical
from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer
from g1swarm.glm_preflight_001 import GLMChatConfig
from g1swarm.source_authority import apply_gate

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'experiments/phase2/source_authority_serial_001'
STARTING_COMMIT = '42aa8cdf1e54a2f7b829a9db7b8a300b3675cdfb'
MODEL = historical.MODEL
read, write, sha = historical.read, historical.write, historical.sha
GLMJournalBackend = historical.GLMJournalBackend
durable_stage = historical.durable_stage
public_config = historical.public_config
approved = historical.approved
dd = historical.dd


def _git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], cwd=ROOT)


def _anchor() -> dict[str, str]:
    result = {}
    for entry in _git('ls-tree', '-r', '-z', STARTING_COMMIT).split(b'\0'):
        if not entry:
            continue
        meta, name = entry.split(b'\t', 1)
        mode, kind, oid = meta.decode('ascii').split()
        if kind != 'blob' or mode not in {'100644', '100755'}:
            raise ValueError('unsupported pre-existing tracked file')
        result[name.decode('utf8')] = oid
    return result


def prior_inventory() -> list[dict[str, Any]]:
    records = []
    for name, oid in _anchor().items():
        path = ROOT / name
        if path.is_symlink():
            raise ValueError('unsupported pre-existing symlink')
        raw = path.read_bytes()
        records.append({'path': name, 'git_blob': oid, 'bytes': len(raw), 'sha256': sha(raw)})
    return sorted(records, key=lambda item: item['path'])


def verify_prior(inputs: Mapping[str, Any] | None = None) -> None:
    try:
        _git('merge-base', '--is-ancestor', STARTING_COMMIT, 'HEAD')
    except subprocess.CalledProcessError:
        raise ValueError('serial starting commit is not an ancestor of HEAD') from None
    anchor = _anchor()
    changed = set(_git('diff', '--name-only', STARTING_COMMIT, '--').decode().splitlines()) & set(anchor)
    if changed:
        raise ValueError('pre-existing tracked evidence/code changed: ' + ', '.join(sorted(changed)))
    if inputs is not None:
        registry = inputs['prior_tracked_files']
        if len(registry) != len(anchor) or {r['path']: r['git_blob'] for r in registry} != anchor:
            raise ValueError('pre-existing tracked-file registry membership/blob drift')
        for record in registry:
            raw = (ROOT / record['path']).read_bytes()
            if len(raw) != record['bytes'] or sha(raw) != record['sha256']:
                raise ValueError('pre-existing raw bytes changed: ' + record['path'])


def validate_configuration(config: GLMChatConfig) -> dict[str, Any]:
    """Compare with the already approved profile AND immutable DG4 contract."""
    reference = historical.prior_preflight(config)
    prior = read(historical.BASE / 'protocol.json')
    protocol = read(BASE / 'protocol.json')
    receipt = read(historical.BASE / 'preflight.json')
    if prior['workers'] != 4 or protocol['workers'] != 1:
        raise ValueError('only historical four versus new one worker treatment allowed')
    if protocol['provider'] != prior['provider']:
        raise ValueError('serial provider protocol differs from historical DG4')
    if public_config(config) != receipt['provider_config']:
        raise ValueError('serial actual provider config differs from historical DG4')
    if protocol['readiness_criteria'] != prior['readiness_criteria']:
        raise ValueError('historical scoring/readiness thresholds changed')
    for field in ('request', 'contract', 'first_response', 'semantic_credit', 'known_B_unsafe_ids'):
        if protocol[field] != prior[field]:
            raise ValueError('historical source/contract/scoring policy changed: ' + field)
    return reference


def _immutable_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('immutable prepared artifact differs: ' + path.name)
        return
    with path.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _immutable_json(path: Path, value: Any) -> None:
    if path.exists():
        if read(path) != value:
            raise ValueError('immutable prepared artifact differs: ' + path.name)
    else:
        write(path, value)


def verify_history(item: Mapping[str, Any]) -> dict[str, Any]:
    for prefix in ('v1', 'dd', 'dg'):
        path = ROOT / item[f'{prefix}_sample_path']
        if sha(path.read_bytes()) != item[f'{prefix}_sample_sha256']:
            raise ValueError('historical source/B/DD/DG4 evidence changed: ' + prefix)
    prior = read(ROOT / item['v1_sample_path'])
    if sha(prior['sample']['source'].encode('utf8')) != item['source_sha256']:
        raise ValueError('source binding changed')
    if (prior['sample']['population'], prior['sample']['sample_id']) != (item['population'], item['sample_id']):
        raise ValueError('historical sample identity changed')
    old_dg = read(ROOT / item['dg_sample_path'])
    expected = {k: value for k, value in item.items() if k not in {'dg_sample_path', 'dg_sample_sha256'}}
    if old_dg['input_binding'] != expected:
        raise ValueError('historical DG4 sample binding differs')
    old_dd = read(ROOT / item['dd_sample_path'])
    if old_dd['input_binding']['v1_sample_sha256'] != item['v1_sample_sha256']:
        raise ValueError('historical DD sample binding differs')
    return prior


def binding() -> dict[str, str]:
    paths = [Path(__file__), BASE / 'acquisition_runner_snapshot.py', BASE / 'inputs.json',
        BASE / 'protocol.json', BASE / 'CONTRACT.md', Path(historical.__file__),
        ROOT / 'src/g1swarm/authority_certificate_v2.py', ROOT / 'prompts/authority_certificate_v2.txt',
        ROOT / 'src/g1swarm/glm_preflight_001/chat_backend.py', ROOT / 'src/g1swarm/glm_preflight_001/selector.py',
        ROOT / 'src/g1swarm/source_authority/authorization.py', ROOT / 'scripts/run_source_authority_pilot.py',
        ROOT / 'scripts/run_authority_certificate_v2_pilot.py', ROOT / 'scripts/glm_preflight_001/live_preflight.py',
        historical.BASE / 'inputs.json', historical.BASE / 'protocol.json', historical.BASE / 'preflight.json',
        ROOT / 'experiments/provider_glm_preflight_001/current_live_receipt.json',
        ROOT / 'experiments/provider_glm_preflight_001/live_profile.json']
    pointer = read(ROOT / 'experiments/provider_glm_preflight_001/current_live_receipt.json')
    paths.append(ROOT / pointer['receipt_path'])
    return {path.relative_to(ROOT).as_posix(): sha(path.read_bytes()) for path in paths}


def verify_prepared() -> dict[str, Any]:
    inputs = read(BASE / 'inputs.json')
    verify_prior(inputs)
    if Path(__file__).read_bytes() != (BASE / 'acquisition_runner_snapshot.py').read_bytes():
        raise ValueError('frozen acquisition runner source changed')
    acquired = read(BASE / 'acquisition_binding.json')
    if acquired['acquisition_hashes'] != binding():
        raise ValueError('pre-scored acquisition binding changed')
    if acquired['workers'] != 1 or acquired['starting_commit'] != STARTING_COMMIT:
        raise ValueError('prepared treatment changed')
    return acquired


def prepare() -> dict[str, Any]:
    verify_prior()
    # This offline config verifies the public fixed settings without reading a key.
    validate_configuration(GLMChatConfig(approved.BASE_URL, 'offline-config-check', response_format_json_object=True))
    historical_inputs = read(historical.BASE / 'inputs.json')
    historical.verify_prior(historical_inputs)
    frozen = []
    for item in historical_inputs['rows']:
        dg_path = historical.BASE / 'samples' / f"{item['population']}--{item['sample_id']}.json"
        row = {**item, 'dg_sample_path': dg_path.relative_to(ROOT).as_posix(),
               'dg_sample_sha256': sha(dg_path.read_bytes())}
        verify_history(row)
        frozen.append(row)
    if len(frozen) != 528 or sum(row['eligible_B_candidate'] for row in frozen) != 291:
        raise ValueError('development population changed')
    unsafe = next(row for row in frozen if row['sample_id'] == 'ood-m-031')
    old_unsafe = read(ROOT / unsafe['dg_sample_path'])
    if not old_unsafe['dg']['score']['released'] or not old_unsafe['dg']['score']['unauthorized_release']:
        raise ValueError('historical ood-m-031 unsafe release must remain retained')
    document = {'schema': 'serial_certificate_inputs_v1', 'starting_commit': STARTING_COMMIT,
        'sample_count': len(frozen), 'eligible_B_candidates': 291, 'skipped_unreleased_B': 237,
        'prior_tracked_files': prior_inventory(), 'rows': frozen,
        'bounded_control_sha256': historical_inputs['bounded_control_sha256'],
        'v1_inputs_sha256': historical_inputs['v1_inputs_sha256'],
        'historical_dd_inputs_sha256': historical_inputs['historical_dd_inputs_sha256'],
        'historical_dg_inputs_sha256': sha((historical.BASE / 'inputs.json').read_bytes()),
        'historical_ood_m_031_unsafe_release': {'path': unsafe['dg_sample_path'],
            'sha256': unsafe['dg_sample_sha256'], 'released': True, 'unauthorized_release': True, 'overwritten': False},
        'only_treatment_change': 'verifier request concurrency 4 to 1',
        'acquisition_order': 'exact historical DG4 inputs row order',
        'development_only': True, 'fresh_held_out': False, 'runtime_calls': 0}
    _immutable_json(BASE / 'inputs.json', document)
    _immutable_bytes(BASE / 'acquisition_runner_snapshot.py', Path(__file__).read_bytes())
    _immutable_json(BASE / 'acquisition_binding.json', {'schema': 'serial_acquisition_binding_v1',
        'starting_commit': STARTING_COMMIT, 'workers': 1, 'acquisition_hashes': binding(),
        'source_frozen_before_launch': True, 'provider_calls': 0})
    verify_prepared()
    return {'prepared': len(frozen), 'eligible': 291, 'skipped': 237, 'workers': 1,
            'prior_tracked_files': len(document['prior_tracked_files']), 'provider_calls': 0}


def preflight(config: GLMChatConfig, provider_binding: dict, acquired: dict) -> None:
    reference = validate_configuration(config)
    stage = durable_stage(BASE / 'preflight/typed_certificate', config,
        lambda backend: SourceAuthorityCertificateIssuer(backend).issue_certificate(approved.SOURCE))
    outcome = stage['result']
    checks = {'approved_configuration_match': True, 'historical_DG4_configuration_match': True,
        'certificate_usable': outcome['usable'],
        'certificate_exact': outcome['certificate'] == {'status': 'AUTHORIZED_UNIQUE', 'checks': ['U'] * 7,
            'plan': approved.EXPECTED_PLAN, 'issues': []},
        'candidate_blind': outcome['diagnostics'].get('request_input_fields') == ['source']}
    document = {'pass': all(checks.values()), 'checks': checks, 'provider_binding': provider_binding,
        'provider_config': public_config(config), 'acquisition_hashes': acquired,
        'approved_live_reference': reference, 'fictional_source': approved.SOURCE, 'typed_certificate': stage,
        'non_scored': True, 'scored_calls_started': False, 'workers': 1, 'runtime_calls': 0, 'held_out_calls': 0}
    write(BASE / 'preflight.json', GLMJournalBackend(config).safe(document))
    if not document['pass']:
        raise ValueError('fictional typed preflight failed; no scored calls started')


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def scheduler_lock():
    """An OS-released lock rejects a second scheduler, including during resume."""
    BASE.mkdir(parents=True, exist_ok=True)
    with (BASE / 'scheduler.lock').open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'1')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ValueError('a serial collection scheduler is already active') from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError('a serial collection scheduler is already active') from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def collect_rows(inputs: Mapping[str, Any], config: GLMChatConfig, *, resume: bool, run_id: str) -> None:
    """Strict serial loop: each call and all its transport retries finish first."""
    sequence = 0
    for completed, item in enumerate(inputs['rows'], 1):
        prior = verify_history(item)
        if item['eligible_B_candidate']:
            sequence += 1
        output = BASE / 'samples' / f"{item['population']}--{item['sample_id']}.json"
        if output.exists():
            if not resume:
                raise FileExistsError(output)
            if read(output)['input_binding'] != item:
                raise ValueError('resumed sample input binding changed')
            continue
        baseline = dd.old.result_from(prior['B']['result'])
        if baseline.success != item['eligible_B_candidate']:
            raise ValueError('historical B eligibility changed')
        if baseline.success:
            directory = BASE / 'acquisition' / f"{item['population']}--{item['sample_id']}"
            started_ns = time.monotonic_ns()
            started_utc = _utc()
            stage = durable_stage(directory, config,
                lambda backend: apply_gate(prior['sample']['source'], baseline, SourceAuthorityCertificateIssuer(backend)))
            timing = {'schema': 'serial_stage_timing_v1', 'run_id': run_id,
                'serial_sequence': sequence, 'source_sha256': item['source_sha256'],
                'started_monotonic_ns': started_ns, 'finished_monotonic_ns': time.monotonic_ns(),
                'started_utc': started_utc, 'finished_utc': _utc(),
                'workers': 1, 'recovered': stage['recovered'], 'called': True}
            if (directory / 'timing.json').exists():
                saved_timing = read(directory / 'timing.json')
                if (saved_timing['serial_sequence'] != sequence or saved_timing['workers'] != 1
                        or saved_timing['source_sha256'] != item['source_sha256']):
                    raise ValueError('resumed stage scheduling evidence changed')
            else:
                write(directory / 'timing.json', timing)
        else:
            stage = {'result': baseline.to_dict(), 'added_wall_s': 0.0, 'recovered': False,
                'live_evidence': {'provider_calls': 0, 'provider_attempts': 0, 'events': [], 'responses': []},
                'skipped_unreleased_B': True}
        stage['score'] = dd.old.score(prior['sample'], dd.old.result_from(stage['result']))
        write(output, GLMJournalBackend(config).safe({'input_binding': item, 'dg_serial': stage}))
        if completed % 20 == 0 or completed == len(inputs['rows']):
            print(json.dumps({'completed': completed, 'total': len(inputs['rows']), 'workers': 1}), flush=True)


def collect(workers: int = 1, resume: bool = False) -> dict[str, Any]:
    if isinstance(workers, bool) or workers != 1:
        raise ValueError('DG-serial requires exactly one worker; no other treatment allowed')
    with scheduler_lock():
        prepared = verify_prepared()
        inputs = read(BASE / 'inputs.json')
        config, provider_binding = historical.resolve_provider()
        validate_configuration(config)
        acquired = prepared['acquisition_hashes']
        receipt_path = BASE / 'preflight.json'
        if receipt_path.exists():
            if not resume:
                raise FileExistsError('preflight receipt exists; use explicit resume')
            receipt = read(receipt_path)
            if not receipt['pass'] or receipt['acquisition_hashes'] != acquired or receipt['provider_binding'] != provider_binding:
                raise ValueError('cannot resume after code/input/provider drift')
        else:
            preflight(config, provider_binding, acquired)
        run_id = uuid.uuid4().hex
        started_utc, started = _utc(), time.perf_counter()
        collect_rows(inputs, config, resume=resume, run_id=run_id)
        verify_prepared()
        stages = [read(BASE / 'samples' / f"{item['population']}--{item['sample_id']}.json")['dg_serial']
                  for item in inputs['rows']]
        result = {'schema': 'serial_collection_receipt_v1', 'run_id': run_id, 'workers': 1,
            'started_utc': started_utc, 'finished_utc': _utc(), 'campaign_wall_s': time.perf_counter() - started,
            'completed': len(inputs['rows']), 'eligible_DG_serial': inputs['eligible_B_candidates'],
            'skipped_unreleased_B': sum(bool(stage.get('skipped_unreleased_B')) for stage in stages),
            'provider_config': public_config(config), 'provider_binding': provider_binding,
            'acquisition_hashes': acquired, 'transport_attempts': sum(stage['live_evidence']['provider_attempts'] for stage in stages),
            'resume': resume, 'historical_DD_retained': True, 'historical_DG4_retained': True,
            'historical_ood_m_031_unsafe_release_retained': True,
            'B_reruns': 0, 'DD_reruns': 0, 'DG4_reruns': 0, 'runtime_calls': 0, 'held_out_calls': 0}
        if (BASE / 'collection.json').exists():
            # A completed campaign may be verified with resume; its original wall
            # clock and first evidence remain immutable.
            previous = read(BASE / 'collection.json')
            if not resume or previous['acquisition_hashes'] != acquired:
                raise ValueError('completed serial campaign receipt differs')
            return previous
        write(BASE / 'collection.json', GLMJournalBackend(config).safe(result))
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'collect'])
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.workers != 1:
        parser.error('DG-serial supports only --workers 1')
    result = prepare() if args.stage == 'prepare' else collect(args.workers, args.resume)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
