"""Safe matched management replay; no rendering, acquisition or browser execution."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

from research_ops import ROOT, SCIENCE, CONSOLE, sha

# Reconstructed from parent Console ordinals 2058,2066,2074,2598,2604,2611,2635.
# Keep code implementation, render and fresh browser QA outside both arms.
TRADITIONAL = [
    'git branch --show-current; git log -3 --oneline; git status --short',
    'git show ffa840d:AGENTS.md; Get-Content docs/experiment-protocol.md',
    f'Get-Content {SCIENCE}/REPORT.md; Get-Content {SCIENCE}/protocol.json',
    'Get-Content console/README.md; Get-Content experiments/research_console/vertical_slice_001/REPORT.md',
    f'Get-Content {CONSOLE}/REPORT.md; Get-Content {CONSOLE}/manifest.json; Get-Content {SCIENCE}/evidence_manifest.json',
    'Get-Content console/qa/authority-validation.json; Get-Content console/qa/authority-browser-qa.json',
]
ADHOC = '''import json,hashlib
from pathlib import Path
from console.server import ConsoleData
r=Path.cwd(); new=ConsoleData(r/"{console}",r); old=ConsoleData(r/"experiments/research_console/vertical_slice_001",r)
x=json.loads((r/"{science}/evidence_manifest.json").read_text())
for name,v in x["files"].items():
 p=r/name; assert hashlib.sha256(p.read_bytes()).hexdigest()==v["sha256"] and p.stat().st_size==v["bytes"]
q=json.loads((r/"console/qa/authority-validation.json").read_text())
for name,value in q["artifact_sha256"].items(): assert hashlib.sha256((r/name).read_bytes()).hexdigest()==value
print(json.dumps({{"inventory":new.verification,"old_inventory":old.verification,"scientific_exports_verified":len(x["files"]),"browser_receipt":"byte-identical, reused; not fresh"}}))
'''.format(console=CONSOLE, science=SCIENCE)


def run(commands, shell=None):
    started=time.perf_counter(); outputs=[]; executions=[]
    for command in commands:
        argv=[shell,'-NoProfile','-Command',command] if isinstance(command,str) else command
        begin=time.perf_counter()
        result=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
        if result.returncode: raise RuntimeError(result.stderr[:800] or result.stdout[:800])
        outputs.append(result.stdout)
        executions.append({'seconds':round(time.perf_counter()-begin,4),'stdout_chars':len(result.stdout),'exit_code':result.returncode})
    text=''.join(outputs)
    return {'elapsed_seconds':round(time.perf_counter()-started,4),'shell_launches':len(commands),
            'text_chars':len(text),'utf8_bytes':len(text.encode()),'context_token_proxy_chars_div4':round(len(text)/4),
            'executions':executions,'last_result':outputs[-1]}


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output',type=Path,required=True); parser.add_argument('--repeats',type=int,default=3); args=parser.parse_args()
    if args.output.exists(): raise SystemExit('Refusing to overwrite benchmark evidence')
    if args.repeats < 1: raise SystemExit('Repeats must be positive')
    shell=shutil.which('pwsh') or shutil.which('powershell')
    python=sys.executable
    before=[*TRADITIONAL,[python,'-c',ADHOC], 'git diff --check HEAD -- AGENTS.md .gitignore ops scripts/research_ops.py scripts/research_ops_session.py scripts/research_ops_benchmark.py tests/test_research_ops.py .agents/skills; git diff --stat; git status --short']
    after=[[python,'scripts/research_ops.py','context'],[python,'scripts/research_ops.py','plan','--kind','implementation','--paths','console/web/app.js','console/server.py','console/build_authority_replay.py'],
           [python,'scripts/research_ops.py','check','console'],[python,'scripts/research_ops.py','closeout','--base','HEAD','--paths','AGENTS.md','.gitignore','ops','scripts/research_ops.py','scripts/research_ops_session.py','scripts/research_ops_benchmark.py','tests/test_research_ops.py','.agents/skills']]
    results={'traditional':[],'ops':[]}
    for index in range(args.repeats):
        for label in (('traditional','ops') if index%2==0 else ('ops','traditional')):
            result=run(before if label=='traditional' else after,shell)
            results[label].append(result)
    old=json.loads(results['traditional'][0]['executions'] and run([[python,'-c',ADHOC]])['last_result'])
    new=json.loads(run([[python,'scripts/research_ops.py','check','console']])['last_result'])
    parity={key:old[key]==new[key] for key in ('inventory','old_inventory','scientific_exports_verified')}
    if not all(parity.values()): raise RuntimeError('Required validation coverage mismatch')
    medians={label:{key:statistics.median(x[key] for x in runs) for key in ('elapsed_seconds','shell_launches','text_chars','context_token_proxy_chars_div4')} for label,runs in results.items()}
    skill_chars=sum(len(p.read_text(encoding='utf-8')) for p in (ROOT/'.agents/skills').glob('g1-*/SKILL.md'))
    old_agents=subprocess.check_output(['git','show','ffa840d:AGENTS.md'],cwd=ROOT,text=True,encoding='utf-8')
    incremental_agents=max(0,len((ROOT/'AGENTS.md').read_text(encoding='utf-8'))-len(old_agents))
    for runs in results.values():
        for item in runs: item.pop('last_result')
    record={'schema_version':1,'at_utc':datetime.now(timezone.utc).isoformat(),'sample_commit':'ffa840d',
            'measurement':'matched management replay; reconstructed traditional read-only commands vs actual ops commands',
            'scope':'state/boundaries/test routing/retained integrity/scoped Git inspection only',
            'traditional_commands':TRADITIONAL,'traditional_adhoc_validator_sha256':__import__('hashlib').sha256(ADHOC.encode()).hexdigest(),
            'results':results,'median':medians,'validation_parity':parity,
            'instruction_overhead':{'both_skill_chars':skill_chars,'incremental_agents_chars':incremental_agents,
                'conservative_ops_total_context_chars':medians['ops']['text_chars']+skill_chars+incremental_agents,
                'note':'Both skills charged once even though only ops may be needed; common AGENTS/system/user prompt held constant.'},
            'new_physics_steps':0,'fresh_browser_runs':0,'acquisition_or_render_runs':0,
            'preserved_outside_comparison':['implementation and source-code reading','new UI browser QA + all historical 24 browser calls','render production + 3226 frames','all 50 original targeted tests','independent scientific interpretation/provenance where required','commit/push/remote verification'],
            'limitations':['Not a randomized full-task LLM A/B or a total-token/time saving claim.',
               'Traditional is reasonable reconstruction, not exact rerun; Windows process-start overhead included.',
               'Files inspected by deterministic integrity stay necessary; only model-facing text is compacted.',
               'Chars/4 is a context-volume proxy, not measured model tokens or billing.',
               'Browser receipt reused because UI/data unchanged; new UI still requires actual browser QA.'],
            'source_script_sha256':sha(Path(__file__))}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'median':medians,'validation_parity':parity},indent=2))


if __name__=='__main__':main()
