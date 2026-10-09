import hashlib,json,subprocess
from pathlib import Path
r=Path(r'D:\webcodex\mujoco-g1\language-codex');out=Path(r'D:\webcodex\mujoco-g1\audit-m26a-3082e2b-20261009');p=r/'experiments/m2/unseen_halt_hold_p1_repair_001'
def load(x):return json.loads(x.read_text(encoding='utf8'))
def sha(x):return hashlib.sha256(x).hexdigest()
s=load(p/'source_manifest.json');print('source keys',list(s));print('files value',str(next(iter(s['files'].items())))[:250])
rows={};missing=[];mismatch=[]
for name,v in s['files'].items():
 expected=v['sha256'] if isinstance(v,dict) else v;q=r/name
 if not q.is_file():missing.append(name);rows[name]={'status':'MISSING','expected':expected};continue
 actual=sha(q.read_bytes());rows[name]={'status':'MATCH' if actual==expected else 'MISMATCH','expected':expected,'actual':actual}
 if actual!=expected:mismatch.append(name)
ready=load(p/'readiness_manifest.json');binds=[]
for n,v in ready['sha256'].items():
 q=r/n;actual=sha(q.read_bytes()) if q.is_file() else None
 if actual!=v:binds.append({'path':n,'expected':v,'actual':actual})
result={'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip(),'source_manifest_sha256':sha((p/'source_manifest.json').read_bytes()),'readiness_sha256':sha((p/'readiness_manifest.json').read_bytes()),'source_files':len(rows),'missing':missing,'mismatched':mismatch,'readiness_binding_mismatches':binds,'files':rows}
(out/'local_source_integrity.json').write_text(json.dumps(result,indent=2),encoding='utf8');print('sources',len(rows),'missing',len(missing),'mismatch',len(mismatch),'readymismatch',len(binds));print(missing[:4],mismatch[:8])
