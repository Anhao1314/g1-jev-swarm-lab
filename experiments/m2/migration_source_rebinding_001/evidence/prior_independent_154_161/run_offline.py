import builtins,hashlib,json,os,sys,subprocess
from pathlib import Path
ROOT=Path(r'D:\webcodex\mujoco-g1\language-codex');OUT=Path(__file__).resolve().parent
os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.dont_write_bytecode=True
os.environ['PYTHONPATH']=str(ROOT/'src')+os.pathsep+str(ROOT)
os.environ['G1SWARM_ROOT']=str(ROOT)
sys.path[:0]=[str(ROOT/'src'),str(ROOT)];os.chdir(ROOT)
paths=[p for folder in ['unseen_halt_hold_design_001','unseen_halt_hold_readiness_001','unseen_halt_hold_p1_repair_001'] for p in (ROOT/'experiments/m2'/folder).rglob('*') if p.is_file()]
def binding():return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
before=binding();(OUT/'before_hashes.json').write_text(json.dumps(before,indent=2),encoding='utf8')
forbidden=[];real_import=builtins.__import__
def guarded(name,*args,**kwargs):
 if name.split('.')[0] in ['mujoco','torch','onnxruntime']:
  forbidden.append(name);raise AssertionError('No physics or policy import allowed:'+name)
 return real_import(name,*args,**kwargs)
builtins.__import__=guarded
import pytest
code=pytest.main(['experiments/m2/unseen_halt_hold_p1_repair_001/test_acquire.py','experiments/m2/unseen_halt_hold_p1_repair_001/test_audit.py','experiments/m2/unseen_halt_hold_p1_repair_001/test_readiness.py','-q','-p','no:cacheprovider','--basetemp='+str(OUT/'pytest-temp'),'--junitxml='+str(OUT/'offline.xml')])
import xml.etree.ElementTree as ET
cases=ET.parse(OUT/'offline.xml').findall('.//testcase');fail=[c.attrib for c in cases if c.find('failure') is not None or c.find('error') is not None]
receipt={'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'exit':int(code),'total':len(cases),'failed':fail,'passed':len(cases)-len(fail),'forbidden_import_attempts':forbidden,'checked_files':len(paths),'changed_files':[k for k,v in before.items() if binding()[k]!=v],'git_status':subprocess.check_output(['git','status','--porcelain=v1'],text=True),'interpreter':sys.executable,'scored_physical_data':False,'physics_steps':0,'policy_inferences':0}
(OUT/'offline_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8');print(json.dumps(receipt));sys.exit(code)
