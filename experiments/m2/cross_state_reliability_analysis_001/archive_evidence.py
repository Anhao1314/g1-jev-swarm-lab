"""Lossless raw-evidence transport; no simulator imports or execution."""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
STORE = ROOT / 'experiments/m2/cross_state_reliability_archives_001'

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pack', action='store_true')
    parser.add_argument('--restore-to', type=Path)
    args = parser.parse_args()
    manifest = json.loads((HERE / 'raw_evidence_manifest.json').read_text())
    files = manifest['files']
    if args.pack:
        STORE.mkdir(exist_ok=True)
        groups = {}
        for name in files:
            group = Path(name).parts[4] if len(Path(name).parts) > 5 else 'campaign'
            groups.setdefault(group, []).append(name)
        archives = {}
        for group, members in sorted(groups.items()):
            archive = STORE / (group + '.tar.gz')
            if archive.exists():
                raise RuntimeError('Refusing to overwrite archive')
            with tarfile.open(archive, 'w:gz', compresslevel=6) as tar:
                for name in sorted(members):
                    if digest(ROOT / name) != files[name]['sha256']:
                        raise RuntimeError('Raw evidence drift: ' + name)
                    tar.add(ROOT / name, arcname=name, recursive=False)
            archives[archive.name] = {'sha256': digest(archive), 'bytes': archive.stat().st_size, 'members': sorted(members)}
        (STORE / 'manifest.json').write_text(json.dumps({'archives': archives}, indent=2) + '\n')
    inventory = json.loads((STORE / 'manifest.json').read_text())['archives']
    seen = set()
    for name, item in inventory.items():
        archive = STORE / name
        if digest(archive) != item['sha256']:
            raise RuntimeError('Archive mismatch')
        with tarfile.open(archive, 'r:gz') as tar:
            members = tar.getmembers()
            if sorted(m.name for m in members) != item['members']:
                raise RuntimeError('Member inventory mismatch')
            for member in members:
                if member.name in seen or member.name not in files or not member.isfile():
                    raise RuntimeError('Unexpected archive member')
                seen.add(member.name)
                data = tar.extractfile(member).read()
                expected = files[member.name]
                if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                    raise RuntimeError('Raw member mismatch')
                if args.restore_to:
                    root = args.restore_to.resolve()
                    target = (root / member.name).resolve()
                    if not target.is_relative_to(root) or target.exists():
                        raise RuntimeError('Unsafe or existing restore target')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as f:
                        f.write(data)
    if seen != set(files):
        raise RuntimeError('Incomplete raw evidence')
    print(json.dumps({'status': 'PASS_LOSSLESS_RAW_EVIDENCE', 'files': len(seen), 'archives': len(inventory), 'raw_bytes': sum(x['bytes'] for x in files.values()), 'archive_bytes': sum(x['bytes'] for x in inventory.values())}))

if __name__ == '__main__':
    main()
