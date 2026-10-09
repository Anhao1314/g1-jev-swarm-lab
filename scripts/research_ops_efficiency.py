"""Small management helpers: scoped reuse, immutable Git refs, brief handoffs."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time


def live_environment(root):
    from research_ops import sha
    versions = {d.metadata['Name'].lower(): d.version for d in importlib.metadata.distributions() if d.metadata['Name']}
    site = Path(sys.executable).parent.parent / 'Lib/site-packages'
    pointers = {p.name: sha(p) for p in site.glob('*.pth')}
    return {'executable': str(Path(sys.executable).resolve()), 'python': platform.python_version(),
            'platform': platform.platform(), 'project_root': str(root.resolve()),
            'distribution_versions': versions, 'pth_sha256': pointers}


def load_check_receipt(path, check_id):
    text = Path(path).read_text(encoding='utf-8')
    try:
        value = json.loads(text)
        rows = value if isinstance(value, list) else [value]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line]
    matches = [row for row in rows if row.get('label') == check_id]
    return matches[-1] if matches else {}


def bindings(paths, root):
    from research_ops import confined, sha
    if not paths or len(paths) != len(set(paths)):
        raise ValueError('Explicit unique covered code/config/test paths required')
    return {'files': {p: sha(confined(root, p)) for p in sorted(paths)},
            'environment': live_environment(root)}


def reuse(receipt, check_id, paths, gate, root):
    from research_ops import confined, sha
    if gate != 'unit' or receipt.get('gate') != 'unit':
        return {'status': 'FRESH_GATE_REQUIRED', 'eligible': False, 'reason': 'Protocol/final-HEAD/independent gates are never waived'}
    if receipt.get('exit_code') != 0 or receipt.get('label') != check_id or not receipt.get('reuse_bindings'):
        return {'status': 'RERUN_REQUIRED', 'eligible': False, 'reason': 'Missing successful matching check receipt'}
    try:
        current = bindings(paths, root)
        log = confined(root, receipt['output'].replace('\\', '/'))
        unchanged = receipt['reuse_bindings'] == current and sha(log) == receipt['output_sha256']
    except (OSError, ValueError, KeyError):
        unchanged = False
    return {'status': 'REUSED_SCOPED_CHECK' if unchanged else 'RERUN_REQUIRED',
            'eligible': unchanged, 'check_id': check_id, 'fresh_test_run': False,
            'acquisition_authorized': False,
            'limit': 'Caller must list the complete covered code/config/test contract; not an independent review or scientific gate'}


def git_bytes(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def evidence_ref(revision, paths, root):
    from research_ops import confined
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Fixed full Git commit required')
    if git_bytes(root, 'rev-parse', revision + '^{commit}').decode().strip() != revision:
        raise ValueError('Reference commit mismatch')
    rows = []
    for name in sorted(set(paths)):
        confined(root, name)
        record = git_bytes(root, 'ls-tree', revision, '--', name).decode().strip()
        identity, actual_name = record.split('\t', 1)
        mode, kind, oid = identity.split()
        if actual_name != name or kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('Reference must name an exact ordinary Git blob')
        data = git_bytes(root, 'cat-file', 'blob', oid)
        if data.startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise ValueError('LFS pointer is not sealed raw payload')
        rows.append({'path': name, 'blob': oid, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
    if not rows:
        raise ValueError('Reference membership must not be empty')
    return {'schema': 'git_evidence_reference_v1', 'revision': revision, 'byte_domain': 'GIT_BLOB_BYTES',
            'files': rows, 'limit': 'References preserve retained bytes, not verdict applicability, Windows checkout bytes or acquisition authority'}


def verify_ref(value, root):
    if value.get('schema') != 'git_evidence_reference_v1' or value.get('byte_domain') != 'GIT_BLOB_BYTES':
        raise ValueError('Unknown reference schema/domain')
    expected = evidence_ref(value['revision'], [r['path'] for r in value['files']], root)
    if expected['files'] != value['files']:
        raise ValueError('Evidence reference identity/content drift')
    return {'status': 'VERIFIED_GIT_EVIDENCE_REFERENCE', 'files': len(expected['files']), 'bytes': sum(r['bytes'] for r in expected['files']), 'new_archive_copies': 0, 'acquisition_authorized': False}


def handoff(kind, paths, p1, final_head, root):
    from research_ops import context, git, plan, sha
    state = context(root)
    route = plan(kind, paths, p1=p1, final_head=final_head)
    return {'schema': 'brief_handoff_v1', 'context_status': state['status'],
            'head': git('rev-parse', 'HEAD', root=root), 'root': str(root.resolve()),
            'state_sha256': sha(root / 'ops/state.json'), 'anchors_verified': state['anchors_verified'],
            'selected_experiment': state['selected_experiment'], 'retained_verdict': state['verdict'],
            'tier': route['tier'], 'risk': route['risk'], 'paths': paths, 'checks': route['checks'],
            'working_tree': state['working_tree'], 'boundary': 'Context handoff only; not a certified source snapshot or independent audit',
            'delegation': route['delegation'], 'reopen_when': 'HEAD, inputs, environment, anchors, scope or new evidence changes',
            'acquisition_authorized': False, 'read_only_review': True}


def lifecycle(task, phase, scope, root):
    from research_ops import record, task_log
    path = task_log(task, root)
    rows = [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []
    starts = [r for r in rows if r.get('event') == 'task_begin']
    ends = [r for r in rows if r.get('event') == 'task_end']
    if phase == 'begin':
        if starts: raise ValueError('Task already started; use a new task ID')
        value = {'event': 'task_begin', 'stage': 'lifecycle', 'monotonic_ns': time.monotonic_ns(), 'scope': scope}
        value.update(wall_ns=time.time_ns(), host=platform.node())
    else:
        if len(starts) != 1 or ends: raise ValueError('Task lifecycle missing start or already ended')
        elapsed = (time.monotonic_ns() - starts[0]['monotonic_ns']) / 1e9
        if elapsed < 0: raise ValueError('Invalid monotonic interval')
        consistent = starts[0].get('host') == platform.node() and abs((time.time_ns() - starts[0]['wall_ns']) / 1e9 - elapsed) <= 2
        value = {'event': 'task_end', 'stage': 'lifecycle', 'elapsed_seconds': elapsed, 'scope': starts[0]['scope']}
        value['clock_continuity'] = consistent
        if not consistent: value['elapsed_seconds'] = None
    record(task, value, root)
    return value


def session_stats(value):
    if value.get('schema_version') != 1 or not re.fullmatch('[0-9a-f]{64}', value.get('source_rollout_sha256', '')):
        raise ValueError('Expected sanitized session receipt with fixed source identity')
    counts = value.get('recorded_token_usage')
    allowed = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens')
    usage = None if counts is None else {k: counts[k] for k in allowed if k in counts}
    if usage is not None and any(type(v) is not int or v < 0 for v in usage.values()):
        raise ValueError('Invalid recorded token count')
    window = value.get('window', {})
    safe_window = {k: window[k] for k in ('start_ordinal_inclusive', 'end_ordinal_exclusive', 'elapsed_seconds') if k in window}
    if any(type(v) not in (int, float) or v < 0 for v in safe_window.values()):
        raise ValueError('Invalid sanitized window')
    uncached = value.get('uncached_input_tokens')
    if uncached is not None and (type(uncached) is not int or uncached < 0):
        raise ValueError('Invalid recorded uncached count')
    return {'source_rollout_sha256': value['source_rollout_sha256'], 'window': safe_window,
            'recorded_token_usage': usage, 'uncached_input_tokens': uncached}
