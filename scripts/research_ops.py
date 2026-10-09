"""Repo-local Research Ops: stdlib only, no simulator import or automatic acquisition."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('context', 'reasoning', 'implementation', 'experiment', 'tests', 'browser_qa', 'audit', 'git_closeout')
SCIENCE = 'experiments/phase3a/residual_authority_feasibility_001'
CONSOLE = 'experiments/research_console/residual_authority_replay_001'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def confined(root, name):
    p = Path(name)
    if not name or '\\' in name or ':' in name or p.is_absolute() or any(x in ('', '.', '..') for x in name.split('/')):
        raise ValueError(f'Invalid relative path: {name}')
    target = (root / p).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes root: {name}')
    return target


def git(*args, root=ROOT):
    return subprocess.check_output(['git', *args], cwd=root, text=True, encoding='utf-8').strip()


def context(root=ROOT):
    state = read(root / 'ops/state.json')
    errors = []
    for name, expected in state['anchors'].items():
        p = confined(root, name)
        if not p.is_file() or sha(p) != expected:
            errors.append(f'Anchor changed/missing: {name}')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', state['baseline_commit'], 'HEAD'], cwd=root, capture_output=True).returncode:
        errors.append('Selected baseline is not ancestor of HEAD')
    changed = git('diff', '--name-only', state['baseline_commit'], '--', 'experiments/phase3a', 'experiments/research_console', root=root).splitlines()
    if changed:
        errors.append('Research selection changed since baseline; review state pointers')
    status = git('status', '--porcelain', '--untracked-files=normal', root=root).splitlines()
    if git('ls-files', '--others', '--exclude-standard', '--', 'experiments/phase3a', 'experiments/research_console', root=root):
        errors.append('Untracked research artifact/namespace; review selection before relying on current state')
    # Never present unvalidated retained state as current on anchor drift.
    audit = read(root / state['decision']) if not errors else {}
    if audit and audit.get('experiment_id') != state['experiment']:
        errors.append('Decision/selected experiment mismatch'); audit = {}
    return {'status': 'STALE' if errors else 'CURRENT', 'errors': errors,
            'branch': git('branch', '--show-current', root=root), 'head': git('rev-parse', '--short', 'HEAD', root=root),
            'baseline_commit': state['baseline_commit'], 'active_line': state['active_line'],
            'selected_experiment': state['experiment'], 'verdict': audit.get('scientific_verdict', 'UNVERIFIED'),
            'blocker': audit.get('remaining_blocker', 'State validation required'),
            'phase3a5': 'PAUSED', 'anchors_verified': len(state['anchors']) - len([e for e in errors if e.startswith('Anchor')]),
            'working_tree': {'tracked_changes': sum(not s.startswith('??') for s in status), 'untracked_entries': sum(s.startswith('??') for s in status)},
            'frozen_assets': state['frozen_assets'], 'allowed': state['allowed'], 'forbidden': state['forbidden'],
            'tests': state['tests'], 'selection_rule': 'Explicit reviewed pointers; changes fail closed, never choose latest by mtime'}


def plan(kind, paths, claims=(), *, p1=False, final_head=False):
    tier = 'claim' if claims or kind == 'claim' else kind
    paths = list(dict.fromkeys(paths))
    checks = ['scoped diff review']
    flags = []
    if any(p.startswith('console/') for p in paths):
        checks += ['check console', 'affected Console Python tests', 'node --test console/web/data.test.js if frontend changed', 'fresh affected browser QA if UI/server/data changed']
    if any(p.startswith(('scripts/research_ops', 'ops/', '.agents/skills/', 'tests/test_research_ops')) for p in paths):
        checks += ['python -m pytest tests/test_research_ops.py tests/test_research_ops_efficiency.py -q']
    if any(p.startswith(('src/', 'configs/', 'scripts/run_', 'experiments/')) for p in paths):
        checks += ['affected scientific contracts and targeted tests', 'execution equivalence before scientific use if observation/execution changed']
        flags += ['Scientific/shared boundary touched; protocol review required. Historical evidence stays immutable.']
    known = ('console/', 'docs/', 'ops/', '.agents/skills/', 'src/', 'configs/', 'experiments/', 'tests/', 'scripts/research_ops')
    unknown = [p for p in paths if not p.startswith(known) and p not in ('AGENTS.md', 'README.md', '.gitignore', '.gitattributes', 'pyproject.toml')]
    if unknown or not paths:
        flags += ['NEEDS_SCOPE_REVIEW: unknown/empty affected paths']
    if tier in ('mechanism', 'claim'):
        checks += ['applicable frozen protocol / bounded budget before acquisition', 'evidence / controls / protocol-source-config-policy binding', 'targeted measurement and interpretation audit']
    if tier == 'claim':
        checks += ['strict provenance / frozen splits and thresholds / appropriate baseline', 'independent evidence AND interpretation audit']
    if p1:
        checks += ['independent P1 implementation/evidence review; retain failure contrast']
    if final_head:
        checks += ['fresh exact-final-HEAD gate; do not reuse an earlier HEAD receipt']
    docs_only = all(p.startswith('docs/') or p == 'README.md' for p in paths)
    risk = 'R2' if p1 or final_head or tier != 'implementation' or flags else ('R1' if len(checks) > 1 or not docs_only else 'R0')
    return {'tier': tier, 'claims': list(claims), 'paths': paths, 'checks': checks, 'scope_flags': flags,
            'risk': risk, 'p1': p1, 'final_head': final_head,
            'delegation': 'one bounded independent reviewer required' if p1 or tier == 'claim' else 'single owner; delegate only disjoint work with a concrete benefit',
            'full_scientific_audit_default': tier == 'claim', 'acquisition_authorized': False,
            'policy': 'ops/verification-policy.md', 'mandatory_protocol_checks_are_not_optional': True}


def check_console(root=ROOT):
    spec = importlib.util.spec_from_file_location('ops_console_transport', root / 'console/server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = module.ConsoleData(root / CONSOLE, root)
    old = module.ConsoleData(root / 'experiments/research_console/vertical_slice_001', root)
    manifest = read(root / SCIENCE / 'evidence_manifest.json')
    for name, entry in manifest['files'].items():
        path = confined(root, name)
        if sha(path) != entry['sha256'] or path.stat().st_size != entry['bytes']:
            raise ValueError(f'Scientific export mismatch: {name}')
    receipt = read(root / 'console/qa/authority-validation.json')
    mismatches = [name for name, expected in receipt['artifact_sha256'].items() if sha(confined(root, name)) != expected]
    for key in ('new_physics_steps', 'new_probes', 'training_updates', 'provider_calls'):
        if receipt[key] != 0:
            raise ValueError(f'Retained observer receipt has nonzero {key}')
    decision = read(root / SCIENCE / 'FINAL_AUDIT.json')
    return {'status': 'PASS_RETAINED_INTEGRITY', 'inventory': data.verification, 'old_inventory': old.verification,
            'scientific_exports_verified': len(manifest['files']), 'verdict': decision['scientific_verdict'],
            'browser_qa': 'REQUIRES_FRESH_BROWSER_QA' if mismatches else 'REUSED_BYTE_IDENTICAL_RECEIPT',
            'browser_identity_mismatches': mismatches, 'browser_limit': receipt['nonblocking_limitation'],
            'fresh_browser_run': False, 'new_physics_steps': 0, 'numeric_audit_rerun': False,
            'simulation_imported': 'mujoco' in sys.modules, 'warning': 'Hash equality is not a fresh browser/environment or independent scientific audit'}


def closeout(base, paths, root=ROOT):
    # Scope is checked but mutations remain explicit human/agent Git operations.
    names = git('diff', '--name-only', base, root=root).splitlines()
    outside = [n for n in names if not any(n == p or n.startswith(p.rstrip('/') + '/') for p in paths)]
    untracked = git('ls-files', '--others', '--exclude-standard', root=root).splitlines()
    task_untracked = [n for n in untracked if any(n == p or n.startswith(p.rstrip('/') + '/') for p in paths)]
    unrelated = [n for n in untracked if n not in task_untracked]
    diff = subprocess.run(['git', 'diff', '--check', base, '--', *paths], cwd=root, capture_output=True, text=True)
    return {'status': 'PASS_SCOPED_DIFF' if diff.returncode == 0 else 'FAIL_DIFF', 'base': base,
            'head': git('rev-parse', 'HEAD', root=root), 'branch': git('branch', '--show-current', root=root),
            'scope': paths, 'outside_tracked_changes': outside, 'diff_errors': diff.stdout,
            'untracked_task_paths': task_untracked, 'unrelated_untracked_count': len(unrelated), 'unrelated_untracked_sample': unrelated[:5],
            'remote_status': 'NOT_CONTACTED', 'staged_or_committed': False}


def retained_experiment_closeout(root=ROOT):
    """Current retained Phase3A.4d adapter; not a universal scientific release gate."""
    state = context(root)
    if state['status'] != 'CURRENT': raise ValueError('State stale; cannot reuse retained experiment closeout')
    protocol = read(root / SCIENCE / 'protocol.json')
    audit = read(root / SCIENCE / 'FINAL_AUDIT.json')
    if not protocol['frozen'] or protocol['experiment_id'] != audit['experiment_id']:
        raise ValueError('Protocol/final audit identity or freeze mismatch')
    for name, expected in audit['retained_artifact_hashes'].items():
        if sha(confined(root / SCIENCE, name)) != expected:
            raise ValueError(f'Retained experiment artifact drift: {name}')
    manifest = read(root / SCIENCE / 'evidence_manifest.json')
    for name, entry in manifest['files'].items():
        if sha(confined(root, name)) != entry['sha256']:
            raise ValueError(f'Retained experiment export drift: {name}')
    return {'status':'REUSED_RETAINED_CLOSEOUT', 'experiment':audit['experiment_id'],
            'scientific_verdict':audit['scientific_verdict'], 'blocker':audit['remaining_blocker'],
            'independent_reviews':audit['independent_reviews'], 'fresh_independent_audit':False,
            'new_acquisition':False, 'phase3a5':'PAUSED', 'export_files_verified':len(manifest['files']),
            'limit':'Only this retained schema supported; new experiments follow their own protocol and decision gates'}


def task_log(task, root=ROOT):
    if not task or not all(c.isalnum() or c in '-_' for c in task):
        raise ValueError('Task ID must be letters/digits/hyphen/underscore')
    return root / '.research_ops' / f'{task}.jsonl'


def record(task, event, root=ROOT):
    path = task_log(task, root)
    path.parent.mkdir(exist_ok=True)
    event['at_utc'] = datetime.now(timezone.utc).isoformat()
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(event, ensure_ascii=True) + '\n')


def summarize(task, root=ROOT):
    rows = [json.loads(s) for s in task_log(task, root).read_text().splitlines()]
    ends = [r for r in rows if r.get('event') == 'task_end']
    return {'task': task, 'elapsed_window': {'measured': bool(ends) and ends[0]['elapsed_seconds'] is not None, 'seconds': ends[0]['elapsed_seconds'] if ends else None,
            'scope': ends[0]['scope'] if ends else None, 'limit': 'Monotonic observed window includes waits; stage sums are not end-to-end time'},
            'output_log_bytes': sum(r.get('output_bytes', 0) for r in rows) if any('output_bytes' in r for r in rows) else None,
            'stages': {stage: {'measured': bool(items := [r for r in rows if r.get('stage') == stage]),
            'seconds': round(sum(r['seconds'] for r in items), 4) if items else None,
            'events': len(items), 'shell_commands': sum(r.get('shell_commands', 0) for r in items),
            'failed_commands': sum(r.get('exit_code', 0) != 0 for r in items)} for stage in STAGES},
            'token_usage': 'UNAVAILABLE unless imported from session records; intervals may overlap, do not sum as wall time'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('context')
    p = sub.add_parser('plan'); p.add_argument('--kind', choices=('implementation', 'mechanism', 'claim'), default='implementation'); p.add_argument('--paths', nargs='+', required=True); p.add_argument('--claim', action='append', default=[]); p.add_argument('--p1', action='store_true'); p.add_argument('--final-head', action='store_true')
    p = sub.add_parser('check'); p.add_argument('target', choices=('console',))
    p = sub.add_parser('closeout'); p.add_argument('--base', required=True); p.add_argument('--paths', nargs='+', required=True); p.add_argument('--retained-experiment', action='store_true')
    p = sub.add_parser('run'); p.add_argument('--task', required=True); p.add_argument('--stage', choices=STAGES, required=True); p.add_argument('--label', required=True); p.add_argument('--bindings', nargs='+'); p.add_argument('--gate', choices=('unit', 'protocol', 'independent', 'final-head'), default='unit'); p.add_argument('argv', nargs=argparse.REMAINDER)
    p = sub.add_parser('mark'); p.add_argument('--task', required=True); p.add_argument('--stage', choices=STAGES, required=True); p.add_argument('--label', required=True); p.add_argument('--seconds', type=float, required=True)
    p = sub.add_parser('summary'); p.add_argument('--task', required=True)
    p.add_argument('--session', type=Path, help='Sanitized research_ops_session receipt; never raw messages')
    for action in ('begin', 'end'):
        p = sub.add_parser(action); p.add_argument('--task', required=True); p.add_argument('--scope', choices=('complete-task', 'observed-window'), default='observed-window')
    p = sub.add_parser('handoff'); p.add_argument('--kind', choices=('implementation','mechanism','claim'), default='implementation'); p.add_argument('--paths', nargs='+', required=True); p.add_argument('--p1', action='store_true'); p.add_argument('--final-head', action='store_true')
    p = sub.add_parser('evidence-ref'); p.add_argument('--revision'); p.add_argument('--paths', nargs='+'); p.add_argument('--verify', type=Path)
    p = sub.add_parser('reuse'); p.add_argument('--receipt', type=Path, required=True); p.add_argument('--check-id', required=True); p.add_argument('--paths', nargs='+', required=True); p.add_argument('--gate', choices=('unit','protocol','independent','final-head'), default='unit')
    args = parser.parse_args(); started = time.perf_counter(); code = 0
    try:
        if args.command == 'context':
            result = context(); code = int(result['status'] != 'CURRENT')
        elif args.command == 'plan': result = plan(args.kind, args.paths, args.claim, p1=args.p1, final_head=args.final_head)
        elif args.command == 'check': result = check_console()
        elif args.command == 'closeout':
            result = closeout(args.base, args.paths); code = int(result['status'] != 'PASS_SCOPED_DIFF')
            if args.retained_experiment: result['experiment_closeout'] = retained_experiment_closeout()
        elif args.command == 'summary':
            result = summarize(args.task)
            if args.session:
                import research_ops_efficiency as efficient
                result['session_usage'] = efficient.session_stats(read(args.session))
                result['session_usage_limit'] = 'Parent window only; child costs excluded; missing usage remains null'
        elif args.command in ('begin', 'end', 'handoff', 'evidence-ref', 'reuse'):
            import research_ops_efficiency as efficient
            if args.command in ('begin', 'end'): result = efficient.lifecycle(args.task, args.command, args.scope, ROOT)
            elif args.command == 'handoff':
                result = efficient.handoff(args.kind, args.paths, args.p1, args.final_head, ROOT); code = int(result['context_status'] != 'CURRENT')
            elif args.command == 'evidence-ref':
                result = efficient.verify_ref(read(args.verify), ROOT) if args.verify else efficient.evidence_ref(args.revision or '', args.paths or [], ROOT)
            else:
                result = efficient.reuse(efficient.load_check_receipt(args.receipt, args.check_id), args.check_id, args.paths, args.gate, ROOT); code = int(not result['eligible'])
        elif args.command == 'mark':
            if args.seconds < 0: raise ValueError('Duration cannot be negative')
            result = {'stage': args.stage, 'seconds': args.seconds, 'label': args.label, 'source': 'manual_measured', 'shell_commands': 0}
            record(args.task, result, ROOT)
        else:
            command = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
            if not command: raise ValueError('Missing command after --')
            path = task_log(args.task, ROOT); path.parent.mkdir(exist_ok=True)
            if args.bindings:
                import research_ops_efficiency as efficient
                before = efficient.bindings(args.bindings, ROOT)
            output = path.parent / f'{args.task}-{time.time_ns()}.log'
            with output.open('wb') as stream:
                code = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT).returncode
            result = {'stage': args.stage, 'label': args.label, 'seconds': time.perf_counter() - started, 'source': 'measured_command',
                      'shell_commands': 1, 'exit_code': code, 'output': str(output.relative_to(ROOT)), 'output_sha256': sha(output), 'output_bytes': output.stat().st_size, 'gate': args.gate}
            if args.bindings:
                try:
                    after = efficient.bindings(args.bindings, ROOT)
                    result['inputs_unchanged_during_check'] = before == after
                    if before == after and code == 0: result['reuse_bindings'] = after
                except (OSError, ValueError, KeyError) as error:
                    result['inputs_unchanged_during_check'] = False
                    result['bindings_error'] = type(error).__name__
            record(args.task, result, ROOT)
            if 'reuse_bindings' in result:
                result = {key: value for key, value in result.items() if key != 'reuse_bindings'}
                result['reuse_receipt'] = str(path.relative_to(ROOT))
        result['ops_elapsed_seconds'] = round(time.perf_counter() - started, 4)
        print(json.dumps(result, ensure_ascii=True, indent=2)); return code
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(json.dumps({'status': 'BLOCKED', 'error': str(error)})); return 1


if __name__ == '__main__':
    raise SystemExit(main())
