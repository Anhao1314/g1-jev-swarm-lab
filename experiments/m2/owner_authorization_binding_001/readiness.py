"""Reuse immutable PR25 gate definitions for a separately frozen worktree.

Only fixed-root Git identity, source membership and binding reconstruction differ.
The original gate/receipts stay unchanged, and physical authority stays absent.
"""
import hashlib
import importlib.util
from pathlib import Path
import subprocess

ROOT = Path('D:/webcodex/mujoco-g1/owner-authorization-binding')
HERE = ROOT / 'experiments/m2/owner_authorization_binding_001'
BASE = '8adef9f6f6a89f93c9c225b92b3b7fc90430693a'
PARENT = 'experiments/m2/acquisition_entry_binding_001'
PARENT_READY_SHA = '8dd88843f4abd9b283076b4e42c73c317b0863336e861f41fd3bbbc663e282b0'

def inherited():
    path = ROOT / PARENT / 'readiness.py'
    raw = path.read_bytes()
    pin = subprocess.check_output(['git', 'show', BASE + ':' + PARENT + '/readiness.py'], cwd=ROOT)
    if raw != pin:
        raise ValueError('Immutable PR25 gate byte drift')
    spec = importlib.util.spec_from_file_location('owner_binding_pr25_helpers', path)
    module = importlib.util.module_from_spec(spec)
    # Compile the byte-checked source, avoiding a cached .pyc at this seam.
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    module.ROOT, module.HERE = ROOT, HERE
    module.NAMESPACE, module.BASE_HEAD = HERE.relative_to(ROOT).as_posix(), BASE
    module.STATUS = 'OWNER_BINDING_FROZEN_NONPHYSICAL_ONLY'
    module.check_identity = check_identity
    module.source_paths = source_paths
    module.expected_binding = expected_binding
    return module

def check_identity(execution_head):
    g = inherited()
    g.require(g.re.fullmatch(r'[0-9a-f]{40}', execution_head or ''), 'Exact full execution HEAD required')
    g.require(not any(k in g.os.environ for k in ('GIT_DIR','GIT_WORK_TREE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES')), 'Git identity override forbidden')
    g.require(g.git('rev-parse','HEAD').decode().strip() == execution_head, 'Current HEAD differs from execution HEAD')
    r = g.helpers()
    r['no_links'](ROOT)
    r['no_links'](HERE)
    g.require(Path(__file__).absolute() == HERE / 'readiness.py', 'Wrong Owner gate location')
    g.require(Path(g.git('rev-parse','--show-toplevel').decode().strip()) == ROOT, 'Wrong worktree root')
    directory = g.COMMON / 'worktrees/owner-authorization-binding'
    g.require(Path(g.git('rev-parse','--absolute-git-dir').decode().strip()) == directory, 'Wrong worktree registration')
    r['no_links'](directory)
    g.require((ROOT / '.git').read_text().strip() == 'gitdir: ' + directory.as_posix(), 'Wrong worktree pointer')
    g.require((directory / 'gitdir').read_text().strip() == (ROOT / '.git').as_posix(), 'Wrong worktree backlink')
    blocks = g.git('worktree','list','--porcelain').decode().split('\n\n')
    match = [b.splitlines() for b in blocks if b.startswith('worktree ' + ROOT.as_posix() + '\n')]
    g.require(len(match) == 1 and 'HEAD ' + execution_head in match[0], 'Wrong registered HEAD')
    common = Path(g.git('rev-parse','--git-common-dir').decode().strip())
    g.require(r['no_links'](common if common.is_absolute() else ROOT / common) == g.COMMON, 'Wrong Git common store')
    g.require(not (g.COMMON / 'objects/info/alternates').exists(), 'Git alternates forbidden')
    g.require(g.git('remote','get-url','origin').decode().strip() == g.ORIGIN, 'Wrong Git origin')
    subprocess.run(['git','merge-base','--is-ancestor',BASE,'HEAD'],cwd=ROOT,check=True)
    base, current = r['git_tree'](ROOT,BASE), r['git_tree'](ROOT,'HEAD')
    g.require(len(base) == 2867 and all(current.get(p) == v for p,v in base.items()), 'Historical PR25 Git tree changed')
    g.require(all(p in base or p.startswith(g.NAMESPACE + '/') for p in current), 'Unexpected tracked additions')
    g.require(not g.git('status','--porcelain','--untracked-files=all'), 'Dirty or untracked worktree')
    ignored = g.git('ls-files','--others','--ignored','--exclude-standard','-z').split(b'\0')
    g.require(not any(Path(p.decode()).suffix in ('.py','.ps1','.cmd','.bat','.sh') for p in ignored if p), 'Ignored executable forbidden')
    return {'execution_head':execution_head,'preserved_git_entries':len(base)}

def source_paths():
    g = inherited()
    paths = set(g.load(ROOT / PARENT / 'source_manifest.json')['files'])
    # Entire parent evidence namespace is referenced in place, not copied.
    paths.update(p for p in g.helpers()['git_tree'](ROOT,BASE) if p.startswith(PARENT + '/'))
    paths.update(p.relative_to(ROOT).as_posix() for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.py','.ps1','.cmd','.bat','.sh'))
    paths.update(g.NAMESPACE + '/' + p for p in ('.gitattributes','dependencies.json','binding.json','owner_trust.json','contract.json'))
    return paths

def expected_binding():
    return {'source_root':str(ROOT),'base_head':BASE,'namespace':HERE.relative_to(ROOT).as_posix(),
            'parent_readiness_sha256':PARENT_READY_SHA,'physics_authorized':False,'acquisition_integrated':True,
            'owner_physics_authorization':None,'allowed_positive_mode':'TEST_ONLY_NONPHYSICAL',
            'authority_scope':'TRUSTED_SERIAL_REVIEWED_RECORD_PIN_NOT_PRODUCTION_IDENTITY'}

def check_target(*, expected_sha, execution_head):
    g = inherited()
    g.require(expected_sha != PARENT_READY_SHA, 'Old PR25 Readiness cannot bind Owner entry')
    g.require(g.digest(ROOT / PARENT / 'readiness_manifest.json') == PARENT_READY_SHA, 'Parent Readiness drift')
    g.require(g.load(HERE / 'owner_trust.json') == {'schema_version':1,'owner_records':{},'physical_dispatch_enabled':False,
              'scope':'TRUSTED_SERIAL_REVIEWED_RECORD_PIN_NOT_PRODUCTION_IDENTITY'}, 'Owner trust/physical enablement drift')
    return g.check_target(expected_sha=expected_sha, execution_head=execution_head)

def canonical_binding(receipt, output, ledger):
    g = inherited()
    protocol = g.load(ROOT / g.DESIGN)
    def canonical_sha(value):
        return hashlib.sha256(g.json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return {'execution_head':receipt['execution_head'],'readiness_sha256':receipt['readiness_sha256'],
            'source_manifest_sha256':receipt['source_manifest_sha256'],'source_root':str(ROOT),
            'protocol_sha256':g.digest(ROOT / g.DESIGN),'cell_order':[c['id'] for c in protocol['cells_in_order']],
            'canonical_cells_sha256':canonical_sha(protocol['cells_in_order']),
            'budget':protocol['budget'],'hold_window_s':2.0,'hold_native_steps':1000,
            'output':str(Path(output).absolute()),'ledger':str(Path(ledger).absolute())}

# Expose only the helper names required by the unchanged one-shot freeze tool.
G = inherited()
NAMESPACE, BASE_HEAD, ORIGINAL, STATUS = G.NAMESPACE, BASE, G.ORIGINAL, G.STATUS
for _name in ('clean_process','environment','require','load','digest','helpers','git'):
    globals()[_name] = getattr(G,_name)
