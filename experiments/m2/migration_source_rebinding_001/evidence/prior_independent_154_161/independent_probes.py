"""Independent synthetic probes; pure scoring only, no live modules."""
import hashlib,importlib.util,json,sys
from pathlib import Path
ROOT=Path(r'D:\webcodex\mujoco-g1\language-codex');OUT=Path(__file__).parent
sys.dont_write_bytecode=True
HERE=ROOT/'experiments/m2/unseen_halt_hold_p1_repair_001'
def mod(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
A=mod('independent_p1_raw',HERE/'audit.py');C=mod('independent_p1_collector',HERE/'acquire.py');spec=json.loads((A.DESIGN/'protocol.json').read_text());entry={'time_s':1.,'qpos':[0.,0.,.8,1.,0.,0.,0.]+[0.]*12,'controller_counter':500}
def raw(i,speed=.05,x=0.,z=.8):
 return {'sequence':500+i,'time_s':1.+i*.002,'phase':'hold','qpos':[x,0.,z,1.,0.,0.,0.]+[0.]*12,'qvel':[speed]+[0.]*17,'ctrl':[0.]*12,'xfrc_applied':[[0.]*6],'controller':{'_counter':500+i,'_action':[0.]*12,'_target':[0.]*12}}
cases={}
for name,seed,rows,expected in [('rolling_then_missing',[.1]*500,[raw(1,speed=1.)],'HOLD_FAILED'),('path_then_missing',[.05]*500,[raw(1,x=.21)],'HOLD_FAILED'),('fall_then_missing',[.05]*500,[raw(1,z=.4)],'HOLD_FAILED'),('instant_only_incomplete',[.05]*500,[raw(1,speed=.15)],'TECHNICAL_PARTIAL'),('complete_valid',[.05]*500,[raw(i,x=i*.0001) for i in range(1,1001)],'HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE')]:
 log=[{'hold_step':i,'native_sequence':r['sequence'],'command_xyz_mps_radps':[0.,0.,0.]} for i,r in enumerate(rows,1)]
 score=A.hold_score(entry,rows,log,seed,spec);assert score['status']==expected
 cases[name]={'status':score['status'],'completion':score['completion_status'],'physical_failures':score['observed_physical_failures']}
witness={'native_steps':0,'phase':'hold'};records=[]
def failure():raise RuntimeError('independent control calculation fault')
try:C.exception_observer(failure,'control.compute_torques',witness,records.append,lambda:{'qpos':[0.,0.,.8],'qvel':[0.]*3,'ctrl':[float('nan')]})()
except RuntimeError:pass
assert records[0]['classification']=='TECHNICAL_CONTROL_OR_ADAPTER_ERROR' and witness['technical_failures']
assert not any(n in sys.modules for n in ['mujoco','torch','onnxruntime'])
receipt={'status':'INDEPENDENT_SYNTHETIC_PROBES_PASS','cases':cases,'control_error_classification':records[0]['classification'],'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'audit.py',HERE/'acquire.py',A.DESIGN/'protocol.json']},'physics_steps':0,'policy_inferences':0,'is_scientific_sample':False}
(OUT/'independent_probes.json').write_text(json.dumps(receipt,indent=2),encoding='utf8');print(json.dumps(receipt,indent=2))
