"""Freeze migration-only metadata from pinned Git code; never grant physics."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

def write_new(path, value):
    with path.open('x', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')

def freeze(code_head):
    gate = runpy.run_path(str(HERE / 'readiness.py'))
    gate['validate_location']()
    gate['git_location']()
    gate['verify_binding']()
    gate['verify_original']()
    gate['dependency_check']()
    namespace = gate['NAMESPACE']
    paths = gate['expected_source_paths']()
    code = sorted(name for name in paths if name.startswith(namespace + '/')
                  and not name.startswith(namespace + '/evidence/')
                  and Path(name).suffix in ('.py', '.ps1', '.cmd', '.bat', '.sh'))
    files = {name: gate['digest'](gate['checked_path'](ROOT, name)) for name in sorted(paths)}
    subprocess.run(['git', 'merge-base', '--is-ancestor', code_head, 'HEAD'], cwd=ROOT, check=True)
    for name in code:
        frozen = gate['git'](ROOT, 'show', code_head + ':' + name)
        gate['require'](hashlib.sha256(frozen).hexdigest() == files[name], 'Code byte mismatch before freeze: ' + name)
    source = {'namespace': namespace, 'base_head': gate['BASE_HEAD'],
              'physics_authorized': False, 'execution_code_head': code_head,
              'execution_code_files': code, 'files': files, 'source_count': len(files),
              'original_source_count': 438,
              'original_source_sha256': gate['ORIGINAL_SOURCE_SHA'],
              'original_readiness_sha256': gate['ORIGINAL_READY_SHA'],
              'meaning': 'Independent migration source identity; original receipts remain immutable and original gate still rejects migrated origin.'}
    write_new(HERE / 'source_manifest.json', source)
    old = gate['load'](ROOT / gate['ORIGINAL'] / 'readiness_manifest.json')
    names = ['source_manifest.json', 'dependencies.json', 'binding.json',
             'offline_test_receipt.json', 'archive_index.json']
    names.extend(path.relative_to(HERE).as_posix() for path in (HERE / 'logs').glob('*') if path.is_file())
    ready = {'namespace': namespace, 'base_head': gate['BASE_HEAD'], 'status': gate['STATUS'],
             'physics_authorized': False, 'execution_code_head': code_head,
             'source_manifest_sha256': gate['digest'](HERE / 'source_manifest.json'),
             'sha256': {namespace + '/' + name: gate['digest'](HERE / name) for name in names},
             'original_readiness_sha256': gate['ORIGINAL_READY_SHA'],
             'exact_execution_head_binding': 'Final commit HEAD externally reviewed and required via --execution-head; no self-hashing commit.',
             'acquisition_integrated': False, 'independent_owner_review_pending': True}
    ready.update({key: old[key] for key in ('freeze', 'cell_ids', 'hold_window_s', 'hold_native_steps')})
    write_new(HERE / 'readiness_manifest.json', ready)
    return {'status': gate['STATUS'], 'source_count': len(files),
            'source_manifest_sha256': gate['digest'](HERE / 'source_manifest.json'),
            'readiness_sha256': gate['digest'](HERE / 'readiness_manifest.json'),
            'execution_code_head': code_head, 'physics_authorized': False}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code-head', required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.code_head), indent=2))
