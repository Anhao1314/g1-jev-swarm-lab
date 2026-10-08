"""Reproduce derived analysis in an empty temporary output directory, no physics."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def verify(raw_root):
    protected=[ROOT/'experiments/m2/cross_state_reliability_analysis_001'/n for n in ('audit.json','audit.md','raw_evidence_manifest.json')]+[ROOT/'ops/state.json']
    before={p.relative_to(ROOT).as_posix():sha(p) for p in protected}
    with tempfile.TemporaryDirectory(prefix='m24-mechanism-reproduction-') as td:
        target=Path(td)
        outputs=[]
        for script,args in [('analyze.py',['--raw-root',str(raw_root),'--output',str(target/'derived')]),
                            ('halt_analysis.py',['--rawroot',str(raw_root/'experiments/m2/cross_state_reliability_001/artifacts'),'--output',str(target/'halt.json')])]:
            completed=subprocess.run([sys.executable,str(HERE/script),*args],capture_output=True,text=True,check=True)
            outputs.append({'script':script,'exit_code':completed.returncode})
        expected={p.name:sha(p) for p in (HERE/'derived').iterdir() if p.is_file()}
        actual={p.name:sha(p) for p in (target/'derived').iterdir() if p.is_file()}
        assert expected==actual, 'Derived bytes not reproducible'
        assert json.loads((target/'halt.json').read_text())==json.loads((HERE/'halt_analysis.json').read_text())
    after={p.relative_to(ROOT).as_posix():sha(p) for p in protected}
    assert before==after
    changes=subprocess.check_output(['git','diff','--name-only','8d80b7a'],cwd=ROOT,text=True).splitlines()
    assert all(p.startswith('experiments/m2/failure_coverage_mechanism_001/') for p in changes), changes
    metrics=json.loads((HERE/'derived/metrics.json').read_text())
    retained=json.loads((protected[0]).read_text())
    assert retained['verdict']=='INCONCLUSIVE' and retained['integrity_verdict']=='PASS' and len(retained['checks'])==94
    result={'verification':'PASS','fresh_temporary_reproduction':True,'derived_files_exact':expected,
            'halt_recomputation_equal':True,'protected_before_after_sha256':before,'historical_tracked_diff':[],
            'raw_files_rehashed_on_reproduction':metrics['all_raw_files_verified'],
            'original_scientific_verdict':retained['verdict'],'original_integrity':retained['integrity_verdict'],
            'original_audit_checks':94,'physics_policy_provider_calls':0,'commands':outputs}
    (HERE/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'verification':'PASS','derived_files':len(expected),'raw_files':178,'original_audit_checks':94,'science':'INCONCLUSIVE'}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True)
    verify(p.parse_args().raw_root.resolve())
