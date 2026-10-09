"""Only PR23's actual invocation and latest no-run-attempt boundaries."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import research_ops as ops
import research_ops_efficiency as efficient


def spec(path, argv):
    path.write_text(json.dumps({'schema': 'nonsecret_test_invocation_v1',
                               'nonsecret': True, 'argv': argv}))
    return path


def cli(root, monkeypatch, command, invocation, paths=('code.txt',)):
    monkeypatch.setattr(ops, 'ROOT', root)
    monkeypatch.setattr(sys, 'argv', ['research_ops.py', 'run', '--task', 'case',
        '--stage', 'tests', '--label', 'same-label', '--invocation-spec', str(invocation),
        '--bindings', *paths, '--', *command])
    return ops.main()


def passing(root, monkeypatch):
    monkeypatch.setattr(efficient, 'live_environment', lambda root: {'python': 'fixture'})
    (root/'code.txt').write_text('unchanged')
    command = [sys.executable, '-c', "print('PASS')"]
    invocation = spec(root/'pass.json', command)
    assert cli(root, monkeypatch, command, invocation) == 0
    old = efficient.load_check_receipt(ops.task_log('case', root), 'same-label')
    assert efficient.reuse(old, 'same-label', ['code.txt'], 'unit', root, invocation_spec=invocation)['eligible']
    return old, command, invocation


@pytest.mark.parametrize('mutation', ['selector', 'flag', 'command', 'missing', 'legacy'])
def test_only_invocation_changes_do_not_reuse_pass(tmp_path, monkeypatch, mutation):
    old, command, invocation = passing(tmp_path, monkeypatch)
    other = invocation
    if mutation == 'selector': other = spec(tmp_path/'other.json', command + ['-k', 'different_test'])
    if mutation == 'flag': other = spec(tmp_path/'other.json', command + ['--collect-only'])
    if mutation == 'command': other = spec(tmp_path/'other.json', [sys.executable, '-c', "print('different check')"])
    if mutation == 'missing': other = None
    if mutation == 'legacy': old.pop('invocation_identity')
    result = efficient.reuse(old, 'same-label', ['code.txt'], 'unit', tmp_path, invocation_spec=other)
    assert not result['eligible'] and 'invocation' in result['reason']


@pytest.mark.parametrize('failure', ['missing_input', 'duplicate_binding', 'spawn', 'declared_mismatch', 'missing_command'])
def test_failed_precheck_or_start_masks_old_pass(tmp_path, monkeypatch, failure):
    old, command, invocation = passing(tmp_path, monkeypatch)
    attempted, proposed, paths = command, invocation, ('code.txt',)
    if failure == 'missing_input': (tmp_path/'code.txt').unlink()
    if failure == 'duplicate_binding': paths = ('code.txt', 'code.txt')
    if failure == 'spawn':
        attempted = [str(tmp_path/'not-installed.exe')]
        proposed = spec(tmp_path/'missing-executable.json', attempted)
    if failure == 'declared_mismatch': attempted = [sys.executable, '-c', "print('different')"]
    if failure == 'missing_command': attempted = []
    assert cli(tmp_path, monkeypatch, attempted, proposed, paths) != 0
    current = efficient.load_check_receipt(ops.task_log('case', tmp_path), 'same-label')
    assert current['status'] == 'TECHNICAL_NO_RUN'
    assert current['command_started'] is False and current['command_exit_code'] is None
    assert current['shell_commands'] == 0 and current['exit_code'] != 0
    if failure == 'spawn': assert current['failure_phase'] == 'command_start'
    if failure == 'missing_input': assert current['failure_phase'] == 'binding_precheck'
    (tmp_path/'code.txt').write_text('unchanged')
    assert not efficient.reuse(current, 'same-label', ['code.txt'], 'unit', tmp_path, invocation_spec=invocation)['eligible']
    assert efficient.reuse(old, 'same-label', ['code.txt'], 'unit', tmp_path, invocation_spec=invocation)['eligible']
    summary = ops.summarize('case', tmp_path)
    assert summary['stages']['tests']['failed_commands'] == 1
    assert summary['stages']['tests']['shell_commands'] == 1
    assert summary['incomplete_attempts'] == 0


def test_interruption_pending_row_prevents_falling_back(tmp_path, monkeypatch):
    _, command, invocation = passing(tmp_path, monkeypatch)
    monkeypatch.setattr(efficient, 'bindings', lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt): cli(tmp_path, monkeypatch, command, invocation)
    current = efficient.load_check_receipt(ops.task_log('case', tmp_path), 'same-label')
    assert current['event'] == 'run_attempt_started' and current['exit_code'] is None
    assert not efficient.reuse(current, 'same-label', ['code.txt'], 'unit', tmp_path, invocation_spec=invocation)['eligible']
    assert ops.summarize('case', tmp_path)['incomplete_attempts'] == 1


def test_nonsecret_declaration_required_and_argv_not_persisted(tmp_path, monkeypatch):
    old, command, invocation = passing(tmp_path, monkeypatch)
    assert set(old['invocation_identity']) == {'schema', 'sha256'}
    assert 'argv' not in old and command[-1] not in ops.task_log('case', tmp_path).read_text()
    data = json.loads(invocation.read_text()); data['nonsecret'] = False
    invocation.write_text(json.dumps(data))
    assert not efficient.reuse(old, 'same-label', ['code.txt'], 'unit', tmp_path, invocation_spec=invocation)['eligible']


def test_real_pytest_selector_change_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(efficient, 'live_environment', lambda root: {'python': 'fixture'})
    tests = tmp_path/'test_modes.py'
    tests.write_text('def test_one(): assert True\ndef test_two(): assert True\n')
    command = [sys.executable, '-B', '-m', 'pytest', str(tests), '-q', '-p', 'no:cacheprovider', '-k', 'test_one']
    invocation = spec(tmp_path/'one.json', command)
    assert cli(tmp_path, monkeypatch, command, invocation, ('test_modes.py',)) == 0
    old = efficient.load_check_receipt(ops.task_log('case', tmp_path), 'same-label')
    assert efficient.reuse(old, 'same-label', ['test_modes.py'], 'unit', tmp_path, invocation_spec=invocation)['eligible']
    other = spec(tmp_path/'two.json', command[:-1]+['test_two'])
    assert not efficient.reuse(old, 'same-label', ['test_modes.py'], 'unit', tmp_path, invocation_spec=other)['eligible']


def test_implicit_executable_lookup_is_not_reusable(tmp_path, monkeypatch):
    old, _, _ = passing(tmp_path, monkeypatch)
    ambiguous = spec(tmp_path/'ambiguous.json', ['python', '-c', "print('PASS')"])
    with pytest.raises(ValueError, match='Absolute executable'):
        efficient.invocation_identity(ambiguous, tmp_path)
    assert not efficient.reuse(old, 'same-label', ['code.txt'], 'unit', tmp_path, invocation_spec=ambiguous)['eligible']
