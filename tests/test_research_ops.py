"""Behavioral boundary tests for routing, staleness, telemetry and sanitized import."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import research_ops as ops
import research_ops_session as session


@pytest.mark.parametrize('kind,claims,expected', [
    ('implementation', [], 'implementation'), ('mechanism', [], 'mechanism'),
    ('implementation', ['held-out'], 'claim'), ('implementation', ['safety'], 'claim'),
    ('implementation', ['generalization'], 'claim'), ('implementation', ['baseline-adoption'], 'claim'),
    ('claim', [], 'claim')])
def test_scope_cannot_lower_declared_claim(kind, claims, expected):
    result = ops.plan(kind, ['console/web/app.js'], claims)
    assert result['tier'] == expected
    assert result['acquisition_authorized'] is False
    assert result['full_scientific_audit_default'] is (expected == 'claim')
    if expected == 'claim': assert 'independent evidence AND interpretation audit' in result['checks']


def test_scientific_bugfix_and_unknown_paths_do_not_skip_contract_review():
    assert ops.plan('implementation', ['src/g1swarm/runtime.py'])['scope_flags']
    assert ops.plan('implementation', ['new-area/thing'])['scope_flags']
    assert ops.plan('implementation', ['docs/notes.md'])['checks'] == ['scoped diff review']


@pytest.mark.parametrize('name', ['../outside', 'C:/outside', 'x/../../outside', 'x\\file', '/absolute'])
def test_manifest_and_task_paths_cannot_escape(tmp_path, name):
    with pytest.raises(ValueError): ops.confined(tmp_path, name)


def mini_repo(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'ops').mkdir(); (tmp_path / 'decision.json').write_text(json.dumps({'experiment_id':'fixed', 'scientific_verdict':'INCONCLUSIVE', 'remaining_blocker':'unproved'}))
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'decision.json'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    state = {'baseline_commit':ops.git('rev-parse','HEAD',root=tmp_path),'anchors':{'decision.json':ops.sha(tmp_path/'decision.json')},'decision':'decision.json','experiment':'fixed','active_line':'fixture','frozen_assets':[],'allowed':[],'forbidden':[],'tests':{}}
    (tmp_path/'ops/state.json').write_text(json.dumps(state)); return tmp_path


def test_changed_decision_fails_closed(tmp_path):
    root=mini_repo(tmp_path); assert ops.context(root)['verdict']=='INCONCLUSIVE'
    (root/'decision.json').write_text('{}')
    result=ops.context(root); assert result['status']=='STALE'; assert result['verdict']=='UNVERIFIED'


def test_new_untracked_experiment_cannot_be_invisible(tmp_path):
    root=mini_repo(tmp_path); target=root/'experiments/phase3a/new'; target.mkdir(parents=True); (target/'report.json').write_text('{}')
    assert ops.context(root)['status']=='STALE'


def test_scoped_closeout_reports_unrelated_without_staging(tmp_path):
    root=mini_repo(tmp_path); (root/'decision.json').write_text('changed')
    result=ops.closeout('HEAD',['ops'],root)
    assert result['outside_tracked_changes']==['decision.json']
    assert ops.git('diff','--cached','--name-only',root=root)==''


def test_missing_phase_is_unmeasured_and_failed_command_is_visible(tmp_path):
    ops.record('fixture', {'stage':'tests','seconds':0.5,'exit_code':2,'shell_commands':1},tmp_path)
    result=ops.summarize('fixture',tmp_path)
    assert result['stages']['tests']['failed_commands']==1
    assert result['stages']['experiment']['seconds'] is None
    with pytest.raises(ValueError): ops.task_log('../escape',tmp_path)


def test_session_import_uses_per_response_usage_once_and_excludes_binary_secrets(tmp_path):
    p=tmp_path/'rollout.jsonl'
    data=[{'timestamp':'2026-10-07T00:00:00Z','type':'response_item','payload':{'type':'custom_tool_call','name':'exec','input':'text(await tools.exec_command({cmd:"Get-Content docs/readme.md; Get-Content C:/secret/key"}));'}},
          {'timestamp':'2026-10-07T00:00:01Z','type':'response_item','payload':{'type':'custom_tool_call_output','output':[{'type':'input_text','text':'abcd'},{'type':'image','data':'BINARY_SECRET'}]}},
          {'timestamp':'2026-10-07T00:00:02Z','type':'token_usage_record','payload':{'usage':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':10}}},
          {'timestamp':'2026-10-07T00:00:03Z','type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':100}}}}]
    p.write_text('\n'.join(json.dumps(r) for r in data))
    result=session.import_session(p,0)
    assert result['uncached_input_tokens']==20; assert result['text_tool_output_chars']==4
    assert result['file_read_counts']=={'docs/readme.md':1}
    assert 'secret' not in json.dumps(result).lower()


def test_live_retained_console_inventory_without_physics():
    result=ops.check_console()
    assert result['inventory']['source_files']==41
    assert result['scientific_exports_verified']==61
    assert result['browser_qa']=='REUSED_BYTE_IDENTICAL_RECEIPT'
    assert result['fresh_browser_run'] is False
    assert result['new_physics_steps']==0


def test_tampered_export_is_detected_before_browser_reuse(tmp_path, monkeypatch):
    # Real inventory validated independently; inject one byte identity failure.
    original=ops.sha
    def changed(path):
        return '0'*64 if Path(path).as_posix().endswith('evidence/completion.json') else original(path)
    monkeypatch.setattr(ops,'sha',changed)
    with pytest.raises(ValueError,match='Scientific export mismatch'): ops.check_console()


def test_browser_code_drift_requires_fresh_qa(monkeypatch):
    original=ops.sha
    monkeypatch.setattr(ops,'sha',lambda path: '0'*64 if Path(path).as_posix().endswith('console/web/app.js') else original(path))
    result=ops.check_console()
    assert result['browser_qa']=='REQUIRES_FRESH_BROWSER_QA'
    assert 'console/web/app.js' in result['browser_identity_mismatches']


def test_retained_closeout_reuses_verdict_and_reviews_without_claiming_new_audit():
    result=ops.retained_experiment_closeout()
    assert result['scientific_verdict']=='INCONCLUSIVE'
    assert result['fresh_independent_audit'] is False
    assert result['new_acquisition'] is False
    assert result['phase3a5']=='PAUSED'
