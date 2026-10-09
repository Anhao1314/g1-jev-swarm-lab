"""Nonphysical workflow boundary tests, not robot or scientific validation."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import research_ops as ops
import research_ops_efficiency as efficient
import research_ops_session as session


def test_risk_and_mandatory_p1_final_head_gates():
    assert ops.plan('implementation', ['docs/note.md'])['risk'] == 'R0'
    assert ops.plan('implementation', ['scripts/research_ops.py'])['risk'] == 'R1'
    p1 = ops.plan('implementation', ['docs/note.md'], p1=True, final_head=True)
    assert p1['risk'] == 'R2' and 'independent' in p1['delegation']
    assert any('fresh exact-final-HEAD' in check for check in p1['checks'])
    assert p1['acquisition_authorized'] is False


def receipt(root, monkeypatch):
    monkeypatch.setattr(efficient, 'live_environment', lambda root: {'python': 'fixture'})
    (root / 'code.py').write_bytes(b'# tested code\n')
    (root / 'log.txt').write_bytes(b'PASS\n')
    spec = root / 'invocation.json'
    spec.write_text(json.dumps({'schema': 'nonsecret_test_invocation_v1', 'nonsecret': True,
                               'argv': [sys.executable, '-c', "print('PASS')"]}))
    return {'gate': 'unit', 'label': 'bounded-check', 'exit_code': 0,
            'output': 'log.txt', 'output_sha256': ops.sha(root / 'log.txt'),
            'invocation_identity': efficient.invocation_identity(spec, root),
            'reuse_bindings': efficient.bindings(['code.py'], root)}


def test_unchanged_scoped_check_reused_without_launch(tmp_path, monkeypatch):
    old = receipt(tmp_path, monkeypatch)
    result = efficient.reuse(old, 'bounded-check', ['code.py'], 'unit', tmp_path, invocation_spec=tmp_path/'invocation.json')
    assert result['eligible'] and not result['fresh_test_run']
    assert result['acquisition_authorized'] is False


@pytest.mark.parametrize('change', ['code', 'environment', 'coverage', 'log', 'failed', 'identity', 'missing'])
def test_reuse_drift_fails_closed(tmp_path, monkeypatch, change):
    old = receipt(tmp_path, monkeypatch)
    paths = ['code.py']; label = 'bounded-check'
    if change == 'code': (tmp_path / 'code.py').write_text('changed')
    if change == 'environment': monkeypatch.setattr(efficient, 'live_environment', lambda root: {'python': 'changed'})
    if change == 'coverage':
        (tmp_path / 'config.json').write_text('{}'); paths += ['config.json']
    if change == 'log': (tmp_path / 'log.txt').write_text('changed')
    if change == 'failed': old['exit_code'] = 1
    if change == 'identity': label = 'different-contract'
    if change == 'missing': old.pop('reuse_bindings')
    assert not efficient.reuse(old, label, paths, 'unit', tmp_path, invocation_spec=tmp_path/'invocation.json')['eligible']


@pytest.mark.parametrize('gate', ['protocol', 'independent', 'final-head'])
def test_mandatory_fresh_gate_not_replaced_by_hash_reuse(tmp_path, monkeypatch, gate):
    old = receipt(tmp_path, monkeypatch)
    assert efficient.reuse(old, 'bounded-check', ['code.py'], gate, tmp_path, invocation_spec=tmp_path/'invocation.json')['status'] == 'FRESH_GATE_REQUIRED'
    old['gate'] = gate
    assert not efficient.reuse(old, 'bounded-check', ['code.py'], 'unit', tmp_path, invocation_spec=tmp_path/'invocation.json')['eligible']


def fixture_git(root):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root).decode().strip()
    git('init', '-q'); (root / 'raw.log').write_bytes(b'failure retained\r\n')
    git('-c', 'core.autocrlf=false', 'add', 'raw.log')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'sealed receipt')
    return git('rev-parse', 'HEAD')


def test_fixed_git_reference_survives_working_tree_change(tmp_path):
    head = fixture_git(tmp_path)
    ref = efficient.evidence_ref(head, ['raw.log'], tmp_path)
    assert ref['files'][0]['sha256'] == hashlib.sha256(b'failure retained\r\n').hexdigest()
    (tmp_path / 'raw.log').write_bytes(b'new working bytes')
    assert efficient.verify_ref(ref, tmp_path)['status'] == 'VERIFIED_GIT_EVIDENCE_REFERENCE'
    assert ref['byte_domain'] == 'GIT_BLOB_BYTES'


def test_reference_tampering_rejected(tmp_path):
    head = fixture_git(tmp_path); ref = efficient.evidence_ref(head, ['raw.log'], tmp_path)
    ref['files'][0]['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='drift'): efficient.verify_ref(ref, tmp_path)
    with pytest.raises(ValueError): efficient.evidence_ref('HEAD', ['raw.log'], tmp_path)
    with pytest.raises(ValueError): efficient.evidence_ref(head, ['../outside'], tmp_path)


def test_lfs_pointer_not_mistaken_for_payload(tmp_path):
    head = fixture_git(tmp_path)
    (tmp_path / 'raw.log').write_bytes(b'version https://git-lfs.github.com/spec/v1\n')
    subprocess.run(['git', '-c', 'core.autocrlf=false', 'add', 'raw.log'], cwd=tmp_path, check=True)
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'pointer'], cwd=tmp_path, check=True)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=tmp_path).decode().strip()
    with pytest.raises(ValueError, match='LFS'): efficient.evidence_ref(head, ['raw.log'], tmp_path)


def test_lifecycle_reports_observed_window_not_command_sum(tmp_path, monkeypatch):
    ticks = iter([10_000_000_000, 11_500_000_000])
    monkeypatch.setattr(efficient.time, 'monotonic_ns', lambda: next(ticks))
    efficient.lifecycle('fixture', 'begin', 'observed-window', tmp_path)
    ops.record('fixture', {'stage': 'tests', 'seconds': 10, 'exit_code': 1, 'shell_commands': 1}, tmp_path)
    efficient.lifecycle('fixture', 'end', 'observed-window', tmp_path)
    result = ops.summarize('fixture', tmp_path)
    assert result['elapsed_window']['seconds'] == 1.5
    assert result['stages']['tests']['seconds'] == 10
    assert result['stages']['tests']['failed_commands'] == 1
    assert result['stages']['reasoning']['seconds'] is None
    with pytest.raises(ValueError): efficient.lifecycle('fixture', 'end', 'complete-task', tmp_path)


def test_partial_token_usage_is_not_fake_uncached_zero(tmp_path):
    path = tmp_path / 'session.jsonl'
    path.write_text(json.dumps({'timestamp': '2026-10-09T00:00:00Z', 'type': 'token_usage_record', 'payload': {'usage': {'output_tokens': 3}}}))
    value = session.import_session(path, 0)
    assert value['recorded_token_usage'] == {'output_tokens': 3}
    assert value['uncached_input_tokens'] is None


def test_latest_failed_check_is_not_hidden_by_earlier_pass(tmp_path):
    path = tmp_path / 'task.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in [
        {'label': 'check', 'exit_code': 0}, {'label': 'other', 'exit_code': 0},
        {'label': 'check', 'exit_code': 1}]))
    assert efficient.load_check_receipt(path, 'check')['exit_code'] == 1
    assert efficient.load_check_receipt(path, 'missing') == {}


def test_missing_gate_identity_is_not_reusable(tmp_path, monkeypatch):
    old = receipt(tmp_path, monkeypatch); old.pop('gate')
    assert not efficient.reuse(old, 'bounded-check', ['code.py'], 'unit', tmp_path, invocation_spec=tmp_path/'invocation.json')['eligible']


def test_deleted_bound_input_failed_attempt_is_always_recorded(tmp_path, monkeypatch):
    old = receipt(tmp_path, monkeypatch)
    ops.record('attempt', old, tmp_path)
    monkeypatch.setattr(ops, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['research_ops.py', 'run', '--task', 'attempt',
        '--stage', 'tests', '--label', 'bounded-check', '--bindings', 'code.py', '--',
        sys.executable, '-c', "from pathlib import Path; Path('code.py').unlink(); raise SystemExit(3)"])
    assert ops.main() == 3
    current = efficient.load_check_receipt(ops.task_log('attempt', tmp_path), 'bounded-check')
    assert current['exit_code'] == 3 and current['bindings_error'] == 'FileNotFoundError'
    (tmp_path / 'code.py').write_bytes(b'# tested code\n')
    assert not efficient.reuse(current, 'bounded-check', ['code.py'], 'unit', tmp_path, invocation_spec=tmp_path/'invocation.json')['eligible']


def test_known_non_document_changes_are_not_review_only():
    assert ops.plan('implementation', ['tests/other_test.py'])['risk'] == 'R1'
    assert ops.plan('implementation', ['pyproject.toml'])['risk'] == 'R1'


def test_session_usage_never_exports_arbitrary_fields_or_fake_counts():
    value = {'schema_version': 1, 'source_rollout_sha256': 'a' * 64,
             'window': {'elapsed_seconds': 1, 'raw_message': 'PRIVATE'},
             'recorded_token_usage': {'output_tokens': 3, 'secret': 'PRIVATE'},
             'uncached_input_tokens': None}
    result = efficient.session_stats(value)
    assert 'PRIVATE' not in json.dumps(result) and result['uncached_input_tokens'] is None
    value['recorded_token_usage']['output_tokens'] = -1
    with pytest.raises(ValueError): efficient.session_stats(value)


def test_clock_or_host_discontinuity_keeps_window_unmeasured(tmp_path, monkeypatch):
    efficient.lifecycle('clock', 'begin', 'observed-window', tmp_path)
    monkeypatch.setattr(efficient.platform, 'node', lambda: 'different host')
    efficient.lifecycle('clock', 'end', 'observed-window', tmp_path)
    result = ops.summarize('clock', tmp_path)['elapsed_window']
    assert result['measured'] is False and result['seconds'] is None
