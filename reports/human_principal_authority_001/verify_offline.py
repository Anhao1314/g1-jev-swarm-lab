"""Reproduce offline boundary regression; never acquires scientific samples."""
import hashlib, json, os, socket, sys, urllib.request
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[2]
os.environ['G1SWARM_ROOT'] = str(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'src'))
os.chdir(ROOT)
import pytest
import g1swarm.source_authority.authorization as authorization
from g1swarm.simulation import G1Simulation
OUT = ROOT/'reports/human_principal_authority_001'
counts = {'network_attempts': 0, 'runtime_or_physics_attempts': 0}
def network(*a, **kw):
    counts['network_attempts'] += 1
    raise AssertionError('OFFLINE_NETWORK_BLOCKED')
def physics(*a, **kw):
    counts['runtime_or_physics_attempts'] += 1
    raise AssertionError('PHYSICS_BLOCKED')
socket.socket.connect = network
socket.create_connection = network
urllib.request.urlopen = network
G1Simulation.step = physics
previous = json.loads((ROOT/'reports/release_status_semantics_001/execution_receipt_final.json').read_text(encoding='utf8'))
selection = previous['selection'] + ['tests/human_principal_001']
code = pytest.main(selection + ['-q', '--junitxml='+str(OUT/'regression_final.xml')])
xml = ET.parse(OUT/'regression_final.xml')
cases = xml.findall('.//testcase')
failures = sorted(c.attrib['classname']+'::'+c.attrib['name'] for c in cases if c.find('failure') is not None or c.find('error') is not None)
old = json.loads((ROOT/'reports/release_status_semantics_001/verification.json').read_text(encoding='utf8'))['full_related_regression']['unchanged_inherited_failure_identities']
pins = json.loads((OUT/'history_before.json').read_text(encoding='utf8'))
changed = [name for name,sha in pins['files'].items() if not (ROOT/name).exists() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha]
unsafe = json.loads((ROOT/'experiments/phase2/source_authority_cross_model_001/samples/ood--ood-m-031.json').read_text(encoding='utf8'))['dg']['score']['unauthorized_release']
result = dict(verdict='PASS_TEST_ONLY_WITH_INHERITED_FAILURES' if failures==sorted(old) and not changed and not any(counts.values()) and unsafe else 'FAIL', selection=selection, pytest_exit_code=int(code), total=len(cases), passed=len(cases)-len(failures), failed=len(failures), failure_identities=failures, new_failure_identities=sorted(set(failures)-set(old)), execution_guards=counts, provider_calls=0, runtime_calls=0, fresh_held_out=0, historical_files_verified=len(pins['files']), historical_changes=changed, historical_ood_m_031_unsafe_retained=unsafe, authorization_module=authorization.__file__, production_authority_established=False, D011='BLOCKED', Language_Runtime='BLOCKED', base_commit=pins['base_commit'])
(OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps(result,ensure_ascii=False))
raise SystemExit(0 if result['verdict'].startswith('PASS') else 1)
