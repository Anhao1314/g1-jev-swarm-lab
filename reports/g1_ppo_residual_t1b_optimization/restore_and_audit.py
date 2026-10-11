"""Hash-bound restore and raw read-only audit. No physics/Torch/policy imports."""
import hashlib,json,subprocess,sys,tarfile
from pathlib import Path,PurePosixPath
BASE=Path(__file__).resolve().parent
m=json.loads((BASE/'RAW_MANIFEST.json').read_text()); archive=BASE/m['archive']
assert hashlib.sha256(archive.read_bytes()).hexdigest()==m['sha256'],'archive hash mismatch'
dest=Path(sys.argv[1]).resolve(); dest.mkdir(exist_ok=False)
seen=set()
with tarfile.open(archive,'r:gz') as t:
    for item in t.getmembers():
        name=PurePosixPath(item.name)
        assert item.isfile() and not name.is_absolute() and '..' not in name.parts and item.name in m['files']
        assert item.name not in seen; seen.add(item.name)
        data=t.extractfile(item).read(); expected=m['files'][item.name]
        assert len(data)==expected['bytes'] and hashlib.sha256(data).hexdigest()==expected['sha256'],item.name
        path=dest/item.name; path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as f:f.write(data)
assert seen==set(m['files']),'missing/extra member'
auditor=BASE.parents[1]/'experiments/rl/g1_ppo_yaw_smoke_001/audit.py'
cmd=[sys.executable,'-B',str(auditor),str(dest/'raw/acquisition-once')]
p=subprocess.run(cmd,capture_output=True,timeout=30)
(dest/'restored-audit.json').write_bytes(p.stdout); (dest/'restored-audit.stderr.raw').write_bytes(p.stderr)
receipt={'archive_sha256':m['sha256'],'restored_files':len(seen),'native_audit_exitcode':p.returncode,
         'physics_steps':0,'policy_calls':0,'imports':'standard library only'}
(dest/'restore-receipt.json').write_text(json.dumps(receipt,indent=2)); print(json.dumps(receipt))
raise SystemExit(p.returncode)
