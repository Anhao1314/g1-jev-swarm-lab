"""Matched nonphysical management replay; no model/task-wide savings claims."""
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import research_ops as ops
import research_ops_efficiency as efficient

BASE = '44d7a664e9d9ecca57661e98ea15200a216e5517'
OUT = ROOT / '.research_ops/efficiency-replay-001'
PATHS = ['scripts/research_ops.py', 'scripts/research_ops_efficiency.py',
         'scripts/research_ops_session.py', 'tests/test_research_ops.py', 'pyproject.toml']
INSTRUCTIONS = ['AGENTS.md', '.agents/skills/g1-research-ops/SKILL.md',
                'ops/verification-policy.md', 'ops/README.md']


def launch(args):
    start = time.perf_counter()
    result = subprocess.run([sys.executable, '-B', 'scripts/research_ops.py', *args],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return time.perf_counter() - start, json.loads(result.stdout)


def routing_run(task):
    return launch(['run', '--task', task, '--stage', 'tests', '--label', 'routing-seven',
                   '--bindings', *PATHS, '--', sys.executable, '-B', '-m', 'pytest',
                   'tests/test_research_ops.py', '-q', '-p', 'no:cacheprovider',
                   '-k', 'test_scope_cannot_lower_declared_claim'])


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    legacy = types.ModuleType('legacy_ops'); legacy.__file__ = str(ROOT / 'scripts/research_ops.py')
    exec(compile(efficient.git_bytes(ROOT, 'show', BASE + ':scripts/research_ops.py'),
                 legacy.__file__, 'exec'), legacy.__dict__)
    old_instructions = sum(len(efficient.git_bytes(ROOT, 'show', BASE + ':' + p).decode()) for p in INSTRUCTIONS)
    new_instructions = sum(len((ROOT / p).read_text(encoding='utf8')) for p in INSTRUCTIONS)
    before = []; after = []
    for trial in range(3):
        start = time.perf_counter(); states = [legacy.context(ROOT) for _ in range(3)]
        assert all(s['status'] == 'CURRENT' for s in states)
        before.append({'seconds': time.perf_counter()-start,
                       'management_chars': 3*old_instructions + sum(len(json.dumps(s)) for s in states),
                       'instruction_read_requests': 12, 'context_validations': 3})
        start = time.perf_counter(); value = efficient.handoff('implementation', ['docs/note.md'], False, False, ROOT)
        assert value['context_status'] == 'CURRENT'
        after.append({'seconds': time.perf_counter()-start,
                      'management_chars': new_instructions + 3*len(json.dumps(value)),
                      'instruction_read_requests': 4, 'context_validations': 1})
    prefixes = ('experiments/m2/unseen_halt_hold_design_001/',
                'experiments/m2/unseen_halt_hold_readiness_001/',
                'experiments/m2/unseen_halt_hold_p1_repair_001/',
                'experiments/m2/migration_source_rebinding_001/')
    groups = {}; all_count = 0
    for line in efficient.git_bytes(ROOT, 'ls-tree', '-r', BASE).decode().splitlines():
        identity, path = line.split('\t', 1)
        if path.startswith(prefixes):
            all_count += 1; groups.setdefault(identity.split()[-1], []).append(path)
    aliases = [{'alias': path, 'canonical': paths[0]} for paths in groups.values() for path in paths[1:]]
    payload = sum(len(efficient.git_bytes(ROOT, 'show', BASE+':'+row['alias'])) for row in aliases)
    ref = efficient.evidence_ref(BASE, [a['canonical'] for a in aliases], ROOT)
    efficient.verify_ref(ref, ROOT)
    encoded = json.dumps({'reference': ref, 'aliases': aliases}, sort_keys=True, indent=2).encode()
    (OUT/'incremental_reference.json').write_bytes(encoded)
    workflows = []
    for trial in range(3):
        measures = {}
        # Alternate order: preserve visible warm-cache limitation.
        for mode in (('before','after') if trial % 2 == 0 else ('after','before')):
            task = f'efficiency-replay-{trial}-{mode}'
            start = time.perf_counter(); routing_run(task)
            if mode == 'before': routing_run(task)
            else:
                _, reused = launch(['reuse','--receipt',str(ops.task_log(task,ROOT)),
                                   '--check-id','routing-seven','--paths',*PATHS])
                assert reused['eligible'] and not reused['fresh_test_run']
            measures[mode] = {'seconds':time.perf_counter()-start,
                              'fresh_check_launches':2 if mode=='before' else 1,
                              'reused_requests':0 if mode=='before' else 1}
        workflows.append(measures)
    value = {'status':'PASS_MATCHED_NONPHYSICAL_REPLAY','baseline':BASE,'trials':3,
             'management':{'before':before,'after':after},
             'immutable_reference':{'namespace_git_files':all_count,'duplicate_blob_pairs':len(aliases),
                 'repeated_payload_bytes':payload,'verified_reference_and_alias_bytes':len(encoded),
                 'domain':'Git logical payload/JSON bytes; NOT actual Git disk savings'},
             'unchanged_unit_requests':workflows,
             'summary':{'management_before_median_seconds':statistics.median(r['seconds'] for r in before),
                 'management_after_median_seconds':statistics.median(r['seconds'] for r in after),
                 'unit_before_median_seconds':statistics.median(r['before']['seconds'] for r in workflows),
                 'unit_after_median_seconds':statistics.median(r['after']['seconds'] for r in workflows)},
             'full_task_time_savings':None,'token_savings':None,'child_cost_savings':None,
             'physics_steps':0,'policy_calls':0,
             'limits':['Scripted 3-role management replay, not 3 real agents or full scientific tasks.',
                       'Two unchanged requests for the same real seven-case routing check; only the second unit request is reused.',
                       'Three warm-cache trials on one Windows host; no stable latency distribution/general savings claim.',
                       'Historical reruns are not automatically unnecessary; changed inputs still require reruns.',
                       'Git already deduplicates blobs; references reduce logical repackaging, not proven Git storage cost.']}
    (OUT/'benchmark.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in value.items() if k not in ('management','unchanged_unit_requests','limits')},indent=2))


if __name__ == '__main__': main()
