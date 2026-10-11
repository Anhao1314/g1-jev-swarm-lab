"""Only verify archived nonphysical preparation; no execution/import of raw helpers."""
import hashlib,json,sys,tarfile
from pathlib import Path,PurePosixPath
base=Path(__file__).resolve().parent;m=json.loads((base/'EVIDENCE_MANIFEST.json').read_text());a=base/m['archive']
assert hashlib.sha256(a.read_bytes()).hexdigest()==m['sha256']
seen=set()
with tarfile.open(a,'r:gz') as t:
    for item in t.getmembers():
        p=PurePosixPath(item.name);assert item.isfile() and not p.is_absolute() and '..' not in p.parts
        assert item.name in m['files'] and item.name not in seen;seen.add(item.name)
        b=t.extractfile(item).read();expected=m['files'][item.name]
        assert len(b)==expected['bytes'] and hashlib.sha256(b).hexdigest()==expected['sha256']
assert seen==set(m['files'])
print(json.dumps({'archive_integrity':'PASS','verified_members':len(seen),'scientific_result':'NO_RESULT',
                  'physics_steps':0,'policy_loads':0,'policy_predictions':0,'optimizer_updates':0}))
