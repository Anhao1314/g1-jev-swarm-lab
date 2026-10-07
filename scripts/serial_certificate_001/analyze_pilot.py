"""Offline serial development treatment audit and historical DG4 comparison.

This module never calls a provider or Runtime. Semantic rejection correctness
remains an independent review decision; usable typed issues alone earn no credit.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any

from scripts import analyze_cross_model_certificate_pilot as historical

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = 'experiments/phase2/source_authority_serial_001'
DG4 = historical.EXPERIMENT
V1, DD = historical.V1, historical.DD
KNOWN_UNSAFE = historical.KNOWN_UNSAFE
read, write, sha, identity = historical.read, historical.write, historical.sha, historical.identity
auth, detail, classification, accounting = historical.auth, historical.detail, historical.classification, historical.accounting
RESOURCE = {'output_budget_exhaustion', 'provider_or_transport_failure'}


def audit_treatment(protocol, old_protocol, provider_config=None):
    errors = []
    if old_protocol.get('workers') != 4 or protocol.get('workers') != 1:
        errors.append('request concurrency must compare historical 4 workers with exactly 1 worker')
    if protocol.get('provider') != old_protocol.get('provider'):
        errors.append('provider/model/reasoning/output/timeout/retry policy differs from historical DG4')
    for field in ('request', 'contract', 'first_response', 'semantic_credit'):
        if protocol.get(field) != old_protocol.get(field):
            errors.append('frozen source/authority/release/scoring policy differs from historical DG4: ' + field)
    if protocol.get('readiness_criteria') != old_protocol.get('readiness_criteria'):
        errors.append('inherited readiness thresholds changed')
    if protocol.get('known_B_unsafe_ids') != list(KNOWN_UNSAFE):
        errors.append('known seven unsafe membership changed')
    for field in ('runtime_started', 'held_out_started'):
        if protocol.get(field) is not False:
            errors.append(field + ' is not explicitly false')
    if provider_config is not None:
        expected = {key: old_protocol['provider'][key] for key in (
            'base_url', 'model', 'temperature', 'max_tokens', 'timeout_s', 'max_network_retries',
            'retry_backoff_s', 'retry_statuses', 'max_response_bytes')}
        expected.update(response_format_json_object=True, thinking_enabled=True)
        if provider_config != expected:
            errors.append('actual acquisition provider configuration differs from frozen DG4 configuration')
    return errors


def audit_payload_equality(serial_directory, historical_directory):
    """Exact file and canonical wire bytes must agree, beyond hash copies."""
    current = Path(serial_directory) / 'request.json'
    prior = Path(historical_directory) / 'request.json'
    errors = []
    if not current.is_file() or not prior.is_file():
        return ['paired request document missing']
    if current.read_bytes() != prior.read_bytes():
        errors.append('serial request document bytes differ from historical DG4 request')
    a, b = read(current), read(prior)
    wire = lambda x: json.dumps(x['payload'], ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf8')
    if wire(a) != wire(b):
        errors.append('serial full source-only wire payload bytes differ from historical DG4')
    return errors


def audit_serial_timing(records, expected_keys):
    """Check the observed call intervals, independently of declared workers."""
    errors = []
    if len(records) != len(expected_keys):
        errors.append('serial call timing count differs from eligible call count')
    for index, (key, timing) in enumerate(records, 1):
        if timing.get('workers') != 1 or timing.get('called') is not True:
            errors.append('serial call timing worker/called metadata differs: ' + key)
        if index <= len(expected_keys) and key != expected_keys[index - 1]:
            errors.append('serial call order differs from historical eligible input order: ' + key)
        if timing.get('serial_sequence') != index:
            errors.append('serial call sequence is not contiguous: ' + key)
        start, end = timing.get('started_monotonic_ns'), timing.get('finished_monotonic_ns')
        if not historical.int_token(start) or not historical.int_token(end) or end < start:
            errors.append('invalid serial call interval: ' + key)
        elif index > 1:
            previous_end = records[index - 2][1].get('finished_monotonic_ns')
            if historical.int_token(previous_end) and previous_end > start:
                errors.append('observed verifier calls overlap despite 1-worker declaration: ' + key)
    return errors


def verify_registry(root, inputs, protocol):
    errors = []
    registry = inputs.get('prior_tracked_files') or []
    tree = {}
    raw_tree = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-r', '-z', protocol['base_commit']])
    for entry in raw_tree.split(b'\0'):
        if entry:
            meta, name = entry.split(b'\t', 1)
            tree[name.decode('utf8')] = meta.decode('ascii').split()[2]
    if len(registry) != len(tree) or {item['path']: item['git_blob'] for item in registry} != tree:
        errors.append('pre-existing tracked registry membership/blob mismatch')
    for item in registry:
        path = root / item['path']
        if not path.is_file() or len(path.read_bytes()) != item['bytes'] or sha(path.read_bytes()) != item['sha256']:
            errors.append('pre-existing raw-byte registry drift: ' + item['path'])
    if inputs.get('starting_commit') != protocol['base_commit']:
        errors.append('input registry anchor differs from protocol base commit')
    return errors


def expected_acquisition_paths(root):
    """The independently specified provenance set cannot be silently reduced."""
    paths = {'scripts/serial_certificate_001/run_pilot.py', EXPERIMENT + '/acquisition_runner_snapshot.py',
        EXPERIMENT + '/inputs.json', EXPERIMENT + '/protocol.json', EXPERIMENT + '/CONTRACT.md',
        'scripts/run_cross_model_certificate_pilot.py', 'src/g1swarm/authority_certificate_v2.py',
        'prompts/authority_certificate_v2.txt', 'src/g1swarm/glm_preflight_001/chat_backend.py',
        'src/g1swarm/glm_preflight_001/selector.py', 'src/g1swarm/source_authority/authorization.py',
        'scripts/run_source_authority_pilot.py', 'scripts/run_authority_certificate_v2_pilot.py',
        'scripts/glm_preflight_001/live_preflight.py', DG4 + '/inputs.json', DG4 + '/protocol.json', DG4 + '/preflight.json',
        'experiments/provider_glm_preflight_001/current_live_receipt.json',
        'experiments/provider_glm_preflight_001/live_profile.json'}
    pointer = read(Path(root) / 'experiments/provider_glm_preflight_001/current_live_receipt.json')
    paths.add(pointer['receipt_path'])
    return paths


def audit_pre_scored_freeze(root, receipt, hashes, starting_commit):
    """Check actual Git blob bytes, rather than trusting a success declaration."""
    errors = []
    commit = receipt.get('freeze_commit', '')
    if not isinstance(commit, str) or not re.fullmatch('[0-9a-f]{40}', commit):
        return ['pre-scored freeze commit is not a full immutable Git commit ID']
    if receipt.get('starting_commit') != starting_commit or receipt.get('workers') != 1:
        errors.append('pre-scored freeze starting anchor/concurrency differs')
    if receipt.get('acquisition_hashes') != hashes:
        errors.append('pre-scored freeze acquisition hash membership/value differs')
    if receipt.get('all_acquisition_hashes_verified_in_Git_commit') != {path: True for path in hashes}:
        errors.append('pre-scored freeze Git verification declaration incomplete')
    if receipt.get('preflight_or_scored_calls_started_at_freeze') is not False or any(receipt.get(field) != 0 for field in ('provider_calls', 'runtime_calls', 'held_out_calls')):
        errors.append('pre-scored freeze is not explicitly before zero provider/Runtime/held-out calls')
    snapshot_path = EXPERIMENT + '/acquisition_runner_snapshot.py'
    if receipt.get('runner_source_snapshot_sha256') != hashes.get(snapshot_path):
        errors.append('pre-scored freeze runner snapshot hash differs')
    for left, right in ((starting_commit, commit), (commit, 'HEAD')):
        completed = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', left, right], capture_output=True)
        if completed.returncode != 0:
            errors.append('pre-scored freeze commit ancestry check failed: ' + left + ' -> ' + right)
    for path, expected_sha in hashes.items():
        document = subprocess.run(['git', '-C', str(root), 'show', commit + ':' + path], capture_output=True)
        if document.returncode != 0 or sha(document.stdout) != expected_sha:
            errors.append('pre-scored Git commit raw acquisition bytes differ: ' + path)
    try:
        timestamp = datetime.fromisoformat(receipt['recorded_utc'])
        if timestamp.tzinfo is None:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        errors.append('pre-scored freeze UTC timestamp unavailable or invalid')
    return errors


def validate(root=ROOT, *, partial=False):
    root = Path(root)
    base = root / EXPERIMENT
    inputs, protocol = read(base / 'inputs.json'), read(base / 'protocol.json')
    old_protocol = read(root / DG4 / 'protocol.json')
    issues = audit_treatment(protocol, old_protocol)
    issues.extend(verify_registry(root, inputs, protocol))
    old_rows, old_validation = historical.validate(root)
    if old_validation['status'] != 'PASS' or not old_validation['final_acceptance_claim']:
        issues.append('complete immutable DD/DG4 historical validation failed')
        issues.extend('historical: ' + value for value in old_validation['issues'])
    old_by_key = {identity(row['sample']): row for row in old_rows}
    old_inputs = {identity(row): row for row in read(root / DG4 / 'inputs.json')['rows']}
    frozen = inputs['rows']
    expected = {identity(row): row for row in frozen}
    if len(frozen) != 528 or len(expected) != 528 or set(expected) != set(old_inputs):
        issues.append('frozen development membership differs from complete historical DG4 528 rows')
    if sum(row.get('eligible_B_candidate') is True for row in frozen) != 291:
        issues.append('frozen eligible B count differs from 291')
    if [identity(row) for row in frozen] != list(old_inputs):
        issues.append('frozen input order differs from historical DG4 inputs')
    for item in frozen:
        key = identity(item)
        prior_binding = old_inputs.get(key)
        if prior_binding is None or {field: item.get(field) for field in prior_binding} != prior_binding:
            issues.append('frozen source/B/DD binding differs from historical DG4: ' + key)
        path = f'{DG4}/samples/{key}.json'
        if item.get('dg_sample_path') != path or not (root / path).is_file() or sha((root / path).read_bytes()) != item.get('dg_sample_sha256'):
            issues.append('immutable historical DG4 sample bytes/path differ: ' + key)
    acquisition = read(base / 'acquisition_binding.json')
    hashes = acquisition.get('acquisition_hashes', acquisition.get('hashes', {}))
    if not hashes:
        issues.append('immutable acquisition code/input/prompt hash binding unavailable')
    if set(hashes) != expected_acquisition_paths(root):
        issues.append('serial acquisition provenance membership differs from independently specified complete set')
    if acquisition.get('workers') != 1 or acquisition.get('starting_commit') != protocol['base_commit'] or acquisition.get('source_frozen_before_launch') is not True:
        issues.append('pre-scored acquisition binding concurrency/anchor/freeze declaration differs')
    for path, digest in hashes.items():
        if not (root / path).is_file() or sha((root / path).read_bytes()) != digest:
            issues.append('serial acquisition binding drift: ' + path)
    freeze_path = base / 'pre_scored_freeze.json'
    freeze = read(freeze_path) if freeze_path.is_file() else None
    if freeze:
        issues.extend(audit_pre_scored_freeze(root, freeze, hashes, protocol['base_commit']))
    elif not partial:
        issues.append('pre-scored committed code/protocol/input freeze receipt unavailable')
    runner = root / 'scripts/serial_certificate_001/run_pilot.py'
    snapshot = base / 'acquisition_runner_snapshot.py'
    if not snapshot.is_file() or runner.read_bytes() != snapshot.read_bytes():
        issues.append('serial acquisition runner differs from immutable startup snapshot')
    prompt = (root / 'prompts/authority_certificate_v2.txt').read_bytes().decode('utf8')
    preflight_path = base / 'preflight.json'
    if preflight_path.is_file():
        preflight = read(preflight_path)
        if preflight.get('acquisition_hashes') != hashes or preflight.get('workers') != 1 or preflight.get('pass') is not True:
            issues.append('serial preflight acquisition hash/concurrency/pass binding differs')
        try:
            issues.extend(audit_treatment(protocol, old_protocol, preflight.get('provider_config')))
            adapted = dict(preflight)
            checks = dict(preflight.get('checks', {}))
            if checks.pop('historical_DG4_configuration_match', None) is not True:
                issues.append('serial preflight historical DG4 configuration check did not pass')
            adapted['checks'] = checks
            issues.extend(historical.audit_preflight(base, adapted, prompt, protocol['provider']))
        except Exception as error:
            issues.append('serial preflight offline audit exception ' + type(error).__name__ + ': ' + str(error))
    elif not partial:
        issues.append('completed serial preflight receipt unavailable')
    rows, seen, timing = [], set(), []
    for path in sorted((base / 'samples').glob('*.json')):
        row = read(path)
        binding = row['input_binding']
        key = identity(binding)
        if key in seen or key not in expected or binding != expected[key] or path.stem != key:
            issues.append('duplicate/unexpected/sample input binding drift: ' + key)
            continue
        seen.add(key)
        if key not in old_by_key:
            issues.append('historical audited row unavailable: ' + key)
            continue
        old_row = old_by_key[key]
        prior = read(root / binding['v1_sample_path'])
        output = row['dg_serial']
        directory = base / 'acquisition' / key
        try:
            issues.extend(key + '/DG_serial: ' + value for value in historical.audit_stage(
                output, prior, directory, prompt, protocol['provider'], chat=True))
            if binding['eligible_B_candidate']:
                issues.extend(key + ': ' + value for value in audit_payload_equality(directory, root / DG4 / 'acquisition' / key))
                interval = read(directory / 'timing.json')
                recovery_matches = interval.get('recovered') == output.get('recovered') or (interval.get('recovered') is False and output.get('recovered') is True)
                if interval.get('source_sha256') != binding['source_sha256'] or not recovery_matches:
                    issues.append('serial timing source/recovery binding differs: ' + key)
                timing.append((key, interval))
        except Exception as error:
            issues.append(key + ': serial stage audit exception ' + type(error).__name__ + ': ' + str(error))
        rows.append({'sample': old_row['sample'], 'B': old_row['B'], 'DD': old_row['DD'],
                     'DG4': old_row['DG'], 'DG_serial': output, 'bounded': old_row['bounded']})
    missing = sorted(set(expected) - seen)
    if missing and not partial:
        issues.append(f'incomplete serial campaign: {len(missing)} missing')
    unsafe = {row['sample']['sample_id'] for row in rows if row['B']['score']['unauthorized_release']}
    if not partial and unsafe != set(KNOWN_UNSAFE):
        issues.append('known seven unsafe B membership differs')
    eligible_keys = [identity(row) for row in frozen if row.get('eligible_B_candidate')]
    timing.sort(key=lambda pair: pair[1].get('serial_sequence', -1))
    expected_timing = [key for key in eligible_keys if key in seen] if partial else eligible_keys
    issues.extend(audit_serial_timing(timing, expected_timing))
    if timing and not freeze:
        issues.append('scored acquisition began without pre-scored freeze receipt')
    if freeze:
        try:
            frozen_at = datetime.fromisoformat(freeze['recorded_utc'])
            for key, interval in timing:
                if datetime.fromisoformat(interval['started_utc']) < frozen_at:
                    issues.append('recorded scored call starts before pre-scored freeze: ' + key)
        except (KeyError, ValueError, TypeError):
            issues.append('freeze/scored-call timestamp comparison unavailable')
    collection_path = base / 'collection.json'
    collection = read(collection_path) if collection_path.is_file() else None
    if not partial:
        if not collection:
            issues.append('completed serial collection receipt unavailable')
        else:
            issues.extend(audit_treatment(protocol, old_protocol, collection.get('provider_config')))
            if not isinstance(collection.get('provider_config'), dict):
                issues.append('collection actual provider configuration unavailable')
            if collection.get('workers') != 1:
                issues.append('collection actual worker count differs from exactly 1')
            if collection.get('completed') != len(rows):
                issues.append('collection completed sample count differs')
            if collection.get('eligible_DG_serial') != sum(row['DG_serial']['live_evidence']['provider_calls'] for row in rows):
                issues.append('collection eligible provider-call count differs')
            if collection.get('transport_attempts') != sum(row['DG_serial']['live_evidence']['provider_attempts'] for row in rows):
                issues.append('collection transport attempts differ from immutable stage ledger')
            if collection.get('acquisition_hashes') != hashes:
                issues.append('collection acquisition hashes differ from pre-scored binding')
            if collection.get('runtime_calls') != 0 or collection.get('held_out_calls') != 0:
                issues.append('collection contains nonzero Runtime or held-out calls')
    calls = sum(row['DG_serial']['live_evidence']['provider_calls'] for row in rows)
    return rows, {'schema': 'serial_certificate_evidence_validation_v1', 'status': 'FAIL' if issues else 'PASS',
        'collection_status': 'COMPLETE' if not missing else 'INCOMPLETE_PARTIAL',
        'final_acceptance_claim': not partial and not missing and not issues,
        'completed_samples': len(rows), 'expected_samples': 528, 'missing_sample_keys': missing,
        'historical_DD_DG4_validation': old_validation, 'historical_DG4_rows_verified': len(old_rows),
        'candidate_blind_full_payloads_verified': calls, 'byte_identical_paired_payloads_verified': calls,
        'observed_serial_call_intervals_verified': sum(not interval.get('recovered') for _, interval in timing),
        'recovered_intervals_are_replay_not_live_acquisition': sum(bool(interval.get('recovered')) for _, interval in timing),
        'independent_new_gate_replays': calls,
        'preserved_registry_verified': bool(inputs.get('prior_tracked_files')),
        'pre_scored_git_freeze_verified': bool(freeze) and not any('freeze' in issue or 'Git commit raw acquisition bytes' in issue for issue in issues),
        'readiness_thresholds_unchanged': protocol.get('readiness_criteria') == old_protocol['readiness_criteria'],
        'issues': issues, 'semantic_credit_by_validator': False, 'provider_calls_by_validator': 0,
        'runtime_calls_by_validator': 0}


def final_failure(output):
    responses = output['live_evidence'].get('responses', [])
    if not responses or 'text' in responses[-1]:
        return None
    response = responses[-1]
    context = response.get('context') or {}
    if context.get('http_status') == 429:
        return 'http_429'
    if context.get('reason') == 'NETWORK_ERROR':
        return 'network'
    if context.get('reason') == 'TIMEOUT' or response.get('failure_type') == 'TIMEOUT':
        return 'timeout'
    return context.get('reason', 'unclassified')


def raw_final_authority_status_claim(output):
    """Read a strict final JSON status claim without parsing or repairing a plan.

    This is an emitted claim, not a usable v2 certificate or semantic credit.
    Duplicate keys at any nesting level and nonfinite values are rejected.
    Reasoning content and error context never substitute for assistant text.
    """
    responses = output['live_evidence'].get('responses', [])
    text = responses[0].get('text') if len(responses) == 1 else None
    if not isinstance(text, str):
        return None

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def no_nonfinite(value):
        raise ValueError('nonfinite JSON value')

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('nonfinite JSON float')
        return number

    try:
        document = json.loads(text, object_pairs_hook=unique_object, parse_constant=no_nonfinite, parse_float=finite_float)
    except (json.JSONDecodeError, ValueError, TypeError, RecursionError, OverflowError):
        return None
    if not isinstance(document, dict):
        return None
    status = document.get('status')
    return status if isinstance(status, str) and status in {'AUTHORIZED_UNIQUE', 'AMBIGUOUS', 'UNKNOWN'} else None


def metrics(rows, arm):
    mapped = [{'sample': row['sample'], 'B': row['B'], 'DG': row[arm], 'bounded': row['bounded']} for row in rows]
    result = historical.metrics(mapped, 'DG') if arm in {'DD', 'DG4', 'DG_serial'} else historical.metrics(rows, arm)
    result['new_provider_calls'] = result['called'] if arm == 'DG_serial' else 0
    result['arm'] = arm
    called = [row[arm] for row in rows if row[arm]['live_evidence']['provider_calls']]
    events = [event for output in called for event in output['live_evidence'].get('events', [])]
    network = lambda event: (event.get('error_context') or {}).get('reason') == 'NETWORK_ERROR'
    result.update(network_failure_attempts=sum(network(event) for event in events),
        called_stages_with_network_failure=sum(any(network(event) for event in output['live_evidence'].get('events', [])) for output in called),
        final_http_429_failures=sum(final_failure(output) == 'http_429' for output in called),
        final_network_failures=sum(final_failure(output) == 'network' for output in called),
        final_timeout_failures=sum(final_failure(output) == 'timeout' for output in called))
    if arm in {'DD', 'DG4', 'DG_serial'}:
        for field, taxonomy in [('usable_specific_rejection_review_candidates', 'usable_specific_rejection_review_candidate'),
                                ('usable_generic_UNKNOWN', 'usable_generic_UNKNOWN'),
                                ('unusable_contract_failures', 'certificate_contract_failure')]:
            result[field] = sum(classification(output) == taxonomy for output in called)
    result['final_429_or_network_failures'] = result['final_http_429_failures'] + result['final_network_failures']
    for prefix, numerator, denominator in (
            ('http_429_attempt_rate', result['http_429_failure_attempts'], result['transport_attempts']),
            ('network_attempt_rate', result['network_failure_attempts'], result['transport_attempts']),
            ('calls_with_429_rate', result['called_stages_with_429'], result['called']),
            ('calls_with_network_failure_rate', result['called_stages_with_network_failure'], result['called']),
            ('final_429_or_network_failure_rate', result['final_429_or_network_failures'], result['called'])):
        result[prefix] = {'numerator': numerator, 'denominator': denominator,
                          'rate': numerator / denominator if denominator else None}
    result['incremental_false_rejection'] = len(result['incremental_false_rejection_ids'])
    if arm in {'DD', 'DG4', 'DG_serial'}:
        unsafe = [row[arm] for row in rows if row['B']['score']['unauthorized_release']]
        result['raw_final_authority_status_claim_counts'] = dict(Counter(
            raw_final_authority_status_claim(output) or 'NO_STRICT_FINAL_JSON_STATUS' for output in called))
        result['known_unsafe_raw_false_unique_claims'] = sum(raw_final_authority_status_claim(output) == 'AUTHORIZED_UNIQUE' for output in unsafe)
        result['known_unsafe_usable_false_unique_certificates'] = sum(bool(detail(output).get('certificate_usable')) and
            (detail(output).get('certificate') or {}).get('status') == 'AUTHORIZED_UNIQUE' for output in unsafe)
        result['known_unsafe_raw_false_unique_claims_released'] = sum(raw_final_authority_status_claim(output) == 'AUTHORIZED_UNIQUE' and
            output['score']['released'] for output in unsafe)
    return result


def paired(rows):
    mapped = [dict(row, DD=row['DG4'], DG=row['DG_serial']) for row in rows]
    source = historical.paired(mapped)
    result = {key: source[key] for key in ('B_exact_valid_n', 'both_retained', 'both_lost',
        'status_disagreement_count', 'reason_disagreement_count', 'authority_or_reason_disagreement_count',
        'unique_plan_disagreement_count', 'paired_usable_certificate_comparison')}
    result.update(comparison={'left_arm': 'DG4', 'right_arm': 'DG_serial', 'historical_workers': 4,
                             'serial_workers': 1, 'longitudinal_not_randomized': True},
        serial_recovered_from_DG4=source['DG_recovered_from_DD'], serial_lost_from_DG4=source['DG_lost_from_DD'],
        serial_recovered_ids=source['DG_recovered_ids'], serial_lost_ids=source['DG_lost_ids'],
        resource_failure_pairing={key.replace('DD_only', 'DG4_only').replace('DG_only', 'DG_serial_only'): value
                                 for key, value in source['resource_failure_pairing'].items()},
        disagreements=[{**{key: value for key, value in item.items() if key not in {'DD', 'DG'}},
                        'DG4': item['DD'], 'DG_serial': item['DG']} for item in source['disagreements']],
        unique_plan_disagreements=[{'sample_key': item['sample_key'], 'DG4_plan': item['DD_plan'],
                                  'DG_serial_plan': item['DG_plan']} for item in source['unique_plan_disagreements']])
    called = [row for row in rows if row['DG4']['live_evidence']['provider_calls'] or row['DG_serial']['live_evidence']['provider_calls']]
    usable = lambda row, arm: bool(detail(row[arm]).get('certificate_usable'))
    table = Counter((usable(row, 'DG4'), usable(row, 'DG_serial')) for row in called)
    result['usable_certificate_pairing'] = {'called_pair_n': len(called), 'both_usable': table[(True, True)],
        'serial_recovered': table[(False, True)], 'serial_lost': table[(True, False)], 'both_unusable': table[(False, False)],
        'serial_recovered_ids': [identity(row['sample']) for row in called if not usable(row, 'DG4') and usable(row, 'DG_serial')],
        'serial_lost_ids': [identity(row['sample']) for row in called if usable(row, 'DG4') and not usable(row, 'DG_serial')]}
    return result


def unsafe_arm(output, *, bounded=False, known_unsafe=True):
    certificate = detail(output).get('certificate')
    unique = bool(certificate and certificate['status'] == 'AUTHORIZED_UNIQUE')
    raw_status = raw_final_authority_status_claim(output) if not bounded else None
    return {'score': output['score'], 'status': auth(output).get('status'), 'reason_code': auth(output).get('reason_code'),
        'usable': bool(detail(output).get('certificate_usable')), 'certificate': certificate,
        'raw_final_authority_status_claim': raw_status,
        'raw_false_unique_claim': known_unsafe and raw_status == 'AUTHORIZED_UNIQUE',
        'contract_usable_false_unique': known_unsafe and unique and bool(detail(output).get('certificate_usable')),
        'released': bool(output['score']['released']), 'unauthorized_release': bool(output['score']['unauthorized_release']),
        'taxonomy': 'bounded_control' if bounded else classification(output), 'final_failure': final_failure(output),
        'specific_semantic_rejection_review_candidate': not bounded and classification(output) == 'usable_specific_rejection_review_candidate',
        'semantic_credit': False if bounded else None,
        'authorized_unique_certificate': unique,
        'certificate_false_unique': unique and known_unsafe,
        'certificate_false_unique_matches_B': unique and known_unsafe and bool(detail(output).get('plan_matches_candidate')),
        'certificate_false_unique_host_mismatch': unique and known_unsafe and not detail(output).get('plan_matches_candidate'),
        'accounting': accounting(output['live_evidence'])}


def operational_checks(serial, cohorts):
    return {'zero_unauthorized': serial['unauthorized_release'] == 0,
        'usable_rate': serial['usable'] >= 277, 'valid_retention': serial['B_exact_valid_retained'] >= 270,
        'primary_retention': cohorts.get('ood:primary_gold', {}).get('DG_serial', {}).get('B_exact_valid_retained', 0) >= 70,
        'phase22b_retention': cohorts.get('phase22b', {}).get('DG_serial', {}).get('B_exact_valid_retained', 0) >= 66,
        'controlled_retention': cohorts.get('controlled', {}).get('DG_serial', {}).get('B_exact_valid_retained', 0) >= 131,
        'exhaustion': serial['output_exhaustion'] <= 14,
        'token_cost': serial['mean_reported_tokens_per_called_stage'] is not None and serial['mean_reported_tokens_per_called_stage'] <= 2051.47,
        'median_latency': serial['added_wall_median_s'] is not None and serial['added_wall_median_s'] <= 5,
        'p95_latency': serial['added_wall_p95_s'] is not None and serial['added_wall_p95_s'] <= 12}


def analyze_rows(rows, protocol, collection=None):
    groups = {'all': rows}
    for row in rows:
        sample = row['sample']
        groups.setdefault(sample['population'], []).append(row)
        if sample['population'] == 'ood':
            groups.setdefault('ood:' + sample['split'], []).append(row)
    cohorts = {key: {arm: metrics(group, arm) for arm in ('B', 'DD', 'DG4', 'DG_serial', 'bounded')} for key, group in groups.items()}
    unsafe = []
    for row in rows:
        if not row['B']['score']['unauthorized_release']:
            continue
        sample = row['sample']
        unsafe.append({'sample_id': sample['sample_id'], 'sample_key': identity(sample), 'population': sample['population'],
            'split': sample['split'], 'source': sample['source'], 'B_candidate': row['B']['result']['mission'],
            'arms': {arm: unsafe_arm(row[arm], bounded=arm == 'bounded') for arm in ('DD', 'DG4', 'DG_serial', 'bounded')}})
    order = {key: index for index, key in enumerate(KNOWN_UNSAFE)}
    unsafe.sort(key=lambda case: order.get(case['sample_id'], 99))
    ids = lambda arm, field: [case['sample_id'] for case in unsafe if case['arms'][arm][field]]
    old_false, new_false = ids('DG4', 'certificate_false_unique'), ids('DG_serial', 'certificate_false_unique')
    old_claims, new_claims = ids('DG4', 'raw_false_unique_claim'), ids('DG_serial', 'raw_false_unique_claim')
    historical_releases = ids('DG4', 'certificate_false_unique_matches_B')
    serial_releases = ids('DG_serial', 'certificate_false_unique_matches_B')
    dependencies = {'known_unsafe_n': len(unsafe), 'historical_DG4_false_unique_ids': old_false,
        'serial_false_unique_ids': new_false, 'new_serial_false_unique_ids': sorted(set(new_false) - set(old_false)),
        'historical_DG4_raw_false_unique_claim_ids': old_claims, 'serial_raw_false_unique_claim_ids': new_claims,
        'new_serial_raw_false_unique_claim_ids': sorted(set(new_claims) - set(old_claims)),
        'persistent_raw_false_unique_claim_ids': sorted(set(new_claims) & set(old_claims)),
        'serial_raw_false_unique_claim_without_usable_certificate_ids': [case['sample_id'] for case in unsafe
            if case['arms']['DG_serial']['raw_false_unique_claim'] and not case['arms']['DG_serial']['usable']],
        'historical_DG4_unsafe_release_ids': historical_releases, 'serial_unsafe_release_ids': serial_releases,
        'persistent_unsafe_release_ids': sorted(set(historical_releases) & set(serial_releases)),
        'new_serial_unsafe_release_ids': sorted(set(serial_releases) - set(historical_releases)),
        'historical_ood_m_031_unsafe_release_preserved': 'ood-m-031' in historical_releases,
        'historical_censored_now_usable_ids': [case['sample_id'] for case in unsafe
            if case['arms']['DG4']['taxonomy'] in RESOURCE and case['arms']['DG_serial']['usable']],
        'shared_resource_fail_closed_ids': [case['sample_id'] for case in unsafe
            if all(case['arms'][arm]['taxonomy'] in RESOURCE for arm in ('DG4', 'DG_serial'))],
        'unobserved_semantics_receive_no_credit': True,
        'limitation': 'Selected seen cases and longitudinal same-provider acquisitions cannot establish statistical error independence or isolate concurrency from time/load/model-weight drift.'}
    left, right = cohorts['all']['DG4'], cohorts['all']['DG_serial']
    compare_fields = ('usable', 'unauthorized_release', 'valid_exact', 'B_exact_valid_retained', 'incremental_false_rejection',
        'http_429_failure_attempts', 'network_failure_attempts', 'called_stages_with_429', 'called_stages_with_network_failure',
        'final_http_429_failures', 'final_network_failures', 'final_429_or_network_failures', 'output_exhaustion',
        'reported_tokens', 'transport_attempts', 'attempt_units_missing_total_usage')
    compare_fields += ('known_unsafe_raw_false_unique_claims', 'known_unsafe_usable_false_unique_certificates',
                       'known_unsafe_raw_false_unique_claims_released')
    comparison = {field: {'DG4': left[field], 'DG_serial': right[field], 'serial_minus_DG4': right[field] - left[field]} for field in compare_fields}
    campaign = {'DG4': {'workers': 4, 'campaign_wall_s': None, 'calls_per_second': None,
        'unavailable_reason': 'Historical campaign did not preserve a comparable timed campaign receipt.'},
        'DG_serial': {'workers': 1, 'campaign_wall_s': None, 'calls_per_second': None},
        'per_request_latency_distinct_from_campaign_throughput': True}
    if collection:
        duration = collection.get('campaign_wall_s')
        campaign['DG_serial'].update(campaign_wall_s=duration, started_utc=collection.get('started_utc'), finished_utc=collection.get('finished_utc'),
            resumed=bool(collection.get('resume')),
            calls_per_second=right['called'] / duration if not collection.get('resume') and isinstance(duration, (float, int)) and not isinstance(duration, bool) and duration > 0 else None)
        if collection.get('resume'):
            campaign['DG_serial']['throughput_unavailable_reason'] = 'Resumed campaign timing does not measure all retained logical calls.'
    summary = {'schema': 'serial_certificate_summary_v1', 'experiment_id': 'source_authority_serial_001',
        'evidence_role': 'already_seen_development_regression_pilot', 'comparison': {'historical': 'DG4', 'new': 'DG_serial',
        'only_controlled_factor': 'verifier_request_concurrency', 'concurrency': {'DG4': 4, 'DG_serial': 1},
        'longitudinal_not_randomized': True, 'statistical_significance_claim': False},
        'cohorts': cohorts, 'paired': {key: paired(group) for key, group in groups.items()}, 'DG4_vs_serial': comparison,
        'campaign': campaign, 'readiness_criteria': protocol['readiness_criteria'],
        'operational_checks_excluding_semantic_review': operational_checks(right, cohorts),
        'independent_semantic_review_required': True, 'semantic_success_claim': False,
        'D011': 'BLOCKED', 'runtime_gate': 'BLOCKED', 'held_out_started': False, 'runtime_started': False,
        'historical_unsafe_release_not_overwritten': dependencies['historical_ood_m_031_unsafe_release_preserved'],
        'cost_limitations': ['Attempt usage counted once; missing usage is unknown rather than zero.',
            'Provider reported totals are retained; reasoning is already included in output totals.',
            'Reported token comparisons are lower bounds whenever attempt usage is missing.',
            'Monetary billed cost unverified; no current price assumption.',
            'Per-request median/P95 and serial campaign throughput measure different quantities.'],
        'availability_interpretation': 'Descriptive paired development counts only. Different acquisition time/load and unpinned provider weights prevent a causal or statistical-significance claim.'}
    analysis = {'known_unsafe_cases': unsafe, 'dependent_failure_analysis': dependencies,
        'all_disagreements': summary['paired']['all']['disagreements'],
        'unique_plan_disagreements': summary['paired']['all']['unique_plan_disagreements'],
        'semantic_credit_pending_independent_review': True,
        'incremental_valid_losses': [{'sample_key': identity(row['sample']), 'population': row['sample']['population'],
            'split': row['sample']['split'], 'source': row['sample']['source'], 'B_candidate': row['B']['result']['mission'],
            'DG4': unsafe_arm(row['DG4'], known_unsafe=False), 'DG_serial': unsafe_arm(row['DG_serial'], known_unsafe=False)} for row in rows
            if row['B']['score']['valid_exact'] and not row['DG_serial']['score']['valid_exact']]}
    return summary, analysis


def audit_unfinished_stage(directory, prior, prompt, config):
    """Audit an interrupted journal without inventing a terminal provider result."""
    directory = Path(directory)
    errors = []
    payload = historical.expected_payload(prior['sample']['source'], prompt, config, chat=True)
    digest = historical.request_hash(payload)
    request = read(directory / 'request.json')
    if request != {'payload': payload, 'request_sha256': digest, 'request_input_fields': ['source'],
                   'source_sha256': sha(prior['sample']['source'])}:
        errors.append('unfinished stage full candidate-blind request binding differs')
    marker = read(directory / 'started.json')
    if marker != {'started': True, 'model': config['model'], 'policy': 'never reissue this semantic call after interruption'}:
        errors.append('unfinished stage started/model/first-response policy differs')
    begins = [read(path) for path in sorted(directory.glob('attempt-*-begin.json'))]
    ends = [read(path) for path in sorted(directory.glob('attempt-*-end.json'))]
    if not 1 <= len(begins) <= 3 or len(ends) >= len(begins):
        errors.append('unfinished stage attempt ledger is not an interrupted frozen-budget call')
    if [event.get('index') for event in begins] != list(range(1, len(begins) + 1)) or [event.get('index') for event in ends] != list(range(1, len(ends) + 1)):
        errors.append('unfinished stage attempt indices are not contiguous observed prefixes')
    if any(event.get('request_sha256') != digest for event in begins + ends):
        errors.append('unfinished stage attempt request hash differs')
    if any(path.exists() for path in (directory / 'response.json', directory / 'stage_result.json', directory / 'timing.json')):
        errors.append('unfinished stage unexpectedly has durable terminal response/stage/timing')
    for event in ends:
        historical.assert_reasoning_sanitized(event)
        if event.get('provider_document') is not None or event.get('status') not in {'API_ERROR', 'TIMEOUT'}:
            errors.append('unfinished stage contains observed semantic output rather than only pre-terminal transport events')
    costs = accounting({'events': ends, 'responses': []})
    return {'classification': 'INTERRUPTED_UNOBSERVED', 'provider_calls_started': 1,
        'attempts_started': len(begins), 'attempts_finished': len(ends), 'attempts_unobserved': len(begins) - len(ends),
        'durable_first_response_present': False, 'usable_certificate': None, 'released': None,
        'final_provider_failure': None, 'semantic_credit': None, 'no_semantic_reissue_allowed': True,
        'observed_attempt_accounting': costs, 'included_in_completed_stage_outcome_metrics': False}, errors


def closeout(root=ROOT):
    """Scope-limited closeout after an explicit stop; no collection or reissue."""
    root = Path(root)
    base = root / EXPERIMENT
    stop, inputs, protocol = read(base / 'stop_receipt.json'), read(base / 'inputs.json'), read(base / 'protocol.json')
    rows, validation = validate(root, partial=True)
    issues = validation['issues']
    completed_keys = {identity(row['sample']) for row in rows}
    called = sum(row['DG_serial']['live_evidence']['provider_calls'] for row in rows)
    if stop.get('full_population_completed') is not False or stop.get('frozen_protocol_rewritten') is not False or stop.get('future_collection_authorized') is not False:
        issues.append('stop receipt does not preserve original incomplete scope and prohibit future collection')
    if stop.get('completed_samples_at_stop') != len(rows) or stop.get('completed_called_stages_at_stop') != called:
        issues.append('stop receipt completed sample/call counts differ from audited rows')
    if stop.get('planned_samples') != 528 or stop.get('planned_calls') != 291:
        issues.append('stop receipt rewrites frozen full-population scope')
    prompt = (root / 'prompts/authority_certificate_v2.txt').read_bytes().decode('utf8')
    frozen = {identity(row): row for row in inputs['rows']}
    unfinished = []
    for directory in sorted((base / 'acquisition').iterdir()):
        if not directory.is_dir() or directory.name in completed_keys:
            continue
        key = directory.name
        binding = frozen.get(key)
        if not binding or not binding.get('eligible_B_candidate'):
            issues.append('unfinished acquisition directory has unexpected/ineligible sample: ' + key)
            continue
        try:
            pending, errors = audit_unfinished_stage(directory, read(root / binding['v1_sample_path']), prompt, protocol['provider'])
            issues.extend(key + ': ' + issue for issue in errors)
            issues.extend(key + ': ' + issue for issue in audit_payload_equality(directory, root / DG4 / 'acquisition' / key))
            unfinished.append(dict(pending, sample_key=key, source_sha256=binding['source_sha256']))
        except Exception as error:
            issues.append(key + ': unfinished journal audit exception ' + type(error).__name__ + ': ' + str(error))
    declared = stop.get('in_flight_at_stop', [])
    observed = [{key: item[key] for key in ('sample_key', 'attempts_started', 'attempts_finished',
        'durable_first_response_present', 'no_semantic_reissue_allowed')} for item in unfinished]
    if declared != observed:
        issues.append('unfinished acquisition journals differ from explicit stop receipt')
    summary, analysis = analyze_rows(rows, protocol)
    old_summary = read(root / DG4 / 'summary.json')
    summary.pop('operational_checks_excluding_semantic_review', None)
    acquired_unsafe = {case['sample_id'] for case in analysis['known_unsafe_cases']}
    missing_unsafe = [sample_id for sample_id in KNOWN_UNSAFE if sample_id not in acquired_unsafe]
    scope = {'planned_samples': 528, 'planned_calls': 291, 'completed_samples': len(rows),
        'completed_called_stages': called, 'unrun_or_unfinished_samples': 528 - len(rows),
        'not_started_samples': 528 - len(rows) - len(unfinished),
        'not_started_eligible_calls': 291 - called - len(unfinished),
        'completed_paired_comparison_denominator': called, 'unfinished_calls': len(unfinished),
        'unfinished_attempts_started': sum(item['attempts_started'] for item in unfinished),
        'unfinished_attempts_finished': sum(item['attempts_finished'] for item in unfinished),
        'unfinished_attempts_unobserved': sum(item['attempts_unobserved'] for item in unfinished),
        'not_run_known_unsafe_ids': missing_unsafe,
        'all_six_known_OOD_completed': all(sample_id in acquired_unsafe for sample_id in KNOWN_UNSAFE if sample_id.startswith('ood-')),
        'full_population_completed': False, 'full_serial_global_metrics_available': False,
        'global_operational_readiness_assessed': False, 'final_full_population_acceptance_claim': False,
        'future_collection_authorized': False, 'provider_calls_by_closeout': 0}
    summary.update(schema='serial_certificate_stopped_summary_v1', collection_status='STOPPED_EARLY_PARTIAL',
        scope=scope, full_population_operational_checks='NOT_ASSESSED_INCOMPLETE_CAMPAIGN',
        full_historical_context={'source': DG4 + '/summary.json', 'source_sha256': sha((root / DG4 / 'summary.json').read_bytes()),
            'sample_n': 528, 'called_n': 291,
            'cohorts': {name: {('DG4' if arm == 'DG' else arm): value for arm, value in group.items()}
                        for name, group in old_summary['cohorts'].items()}},
        interrupted_unobserved_stages=unfinished, stop_receipt=stop)
    summary['comparison']['scope'] = 'Exact same completed serial sample subset for both DG4 and DG_serial; full DG4 context is reported separately.'
    analysis.update(scope=scope, not_run_known_unsafe_ids=missing_unsafe, interrupted_unobserved_stages=unfinished,
        partial_development_closeout=True)
    unacquired = []
    for sample_id in missing_unsafe:
        binding = next(item for item in inputs['rows'] if item['sample_id'] == sample_id)
        prior = read(root / binding['v1_sample_path'])
        old_dd, old_dg = read(root / binding['dd_sample_path'])['v2'], read(root / binding['dg_sample_path'])['dg']
        unacquired.append({'sample_id': sample_id, 'sample_key': identity(prior['sample']), 'source': prior['sample']['source'],
            'population': prior['sample']['population'], 'split': prior['sample']['split'],
            'B_candidate': prior['B']['result']['mission'], 'arms': {'DD': unsafe_arm(old_dd), 'DG4': unsafe_arm(old_dg),
            'DG_serial': {'acquisition_status': 'NOT_RUN', 'taxonomy': 'NOT_RUN', 'usable': None,
                'certificate': None, 'semantic_credit': None, 'released': None, 'unauthorized_release': None,
                'raw_final_authority_status_claim': None, 'provider_calls': 0}}})
    analysis['unacquired_known_unsafe_cases'] = unacquired
    validation.update(schema='serial_certificate_stopped_evidence_validation_v1', status='FAIL' if issues else 'PASS',
        collection_status='STOPPED_EARLY_PARTIAL', final_acceptance_claim=False, scope=scope,
        completed_evidence_integrity_claim=not issues, interrupted_unobserved_stages=unfinished)
    for name, value in [('partial_evidence_validation.json', validation), ('partial_summary.json', summary), ('partial_analysis.json', analysis)]:
        write(base / name, value)
    return validation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--partial', action='store_true')
    parser.add_argument('--closeout', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.closeout:
        validation = closeout(args.root)
        print(json.dumps({key: validation[key] for key in ('status', 'collection_status', 'completed_samples', 'final_acceptance_claim')}, ensure_ascii=False))
        return 0 if validation['status'] == 'PASS' else 1
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
        summary, analysis = analyze_rows(rows, read(base / 'protocol.json'), read(base / 'collection.json'))
        write(base / 'summary.json', summary)
        write(base / 'analysis.json', analysis)
    print(json.dumps({key: validation[key] for key in ('status', 'collection_status', 'completed_samples', 'final_acceptance_claim')}, ensure_ascii=False))
    return 0 if validation['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
