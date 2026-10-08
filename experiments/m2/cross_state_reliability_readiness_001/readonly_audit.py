"""Independent NO-PHYSICS hash/dependency audit. No simulator imports."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    restored = json.loads((HERE / 'asset_restore.json').read_text())
    old_manifest = ROOT / restored['source_manifest']
    assert sha(old_manifest) == restored['source_manifest_sha256']
    historical = json.loads(old_manifest.read_text())['files']
    for row in restored['files']:
        path = ROOT / row['path']
        assert sha(path) == row['sha256'] == historical[row['path']]
        assert path.stat().st_size == row['bytes']
    deps = json.loads((HERE / 'dependencies.json').read_text())
    assert platform.python_version() == deps['python']
    assert Path(sys.executable).resolve() == Path(deps['executable']).resolve()
    for name, version in deps['packages'].items():
        assert importlib.metadata.version(name) == version, name
    tracked = subprocess.check_output(['git','diff','be69479','--name-only','--diff-filter=MDRT'],cwd=ROOT,text=True)
    assert set(tracked.splitlines()) <= {"tests/.gitattributes"}, tracked
    if tracked.strip():
        prior = subprocess.check_output(["git","show","be69479:tests/.gitattributes"],cwd=ROOT,text=True).splitlines()
        current = (ROOT/"tests/.gitattributes").read_text().splitlines()
        assert current == prior + ["test_m24_acquisition_readiness.py -text whitespace=cr-at-eol", ".gitattributes text eol=lf"]
    source = ROOT / 'experiments/m2/cross_state_reliability_001/source_manifest.json'
    freeze = json.loads(source.read_text())
    for name, expected in freeze['files'].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT.resolve())
        assert sha(path) == expected, name
    assert sha(HERE / 'dependencies.json') == freeze['dependencies_sha256']
    assert sha(ROOT / 'experiments/m2/cross_state_reliability_design_001/protocol.json') == freeze['design_protocol_sha256']
    print(json.dumps({'status':'PASS_NO_PHYSICS_INTEGRITY','asset_count':len(restored['files']),'dependency_count':len(deps['packages']),'source_file_count':len(freeze['files']),'source_manifest_sha256':sha(source),'unexpected_historical_changes':0,'allowed_checkout_metadata_change':bool(tracked.strip())}))

if __name__ == '__main__':
    main()
