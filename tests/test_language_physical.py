"""Synthetic backend fault injection; zero real native/policy/renderer calls."""
from io import StringIO
import json
import sys
import time
from types import SimpleNamespace as NS

import numpy as np
import pytest

from g1swarm.language_v01 import physical, media
from g1swarm.language_v01.service import canonical, digest
from g1swarm.state import RobotState


def data(): return NS(time=0., qpos=np.zeros(7), qvel=np.zeros(6), ctrl=np.zeros(1))


def test_native_attempts_count_before_failure_and_no_implicit_retry():
    output=StringIO(); w=physical.Witness(2,time.perf_counter()+5,output)
    calls=[]
    def fail(*args): calls.append(args); raise ValueError('native failure')
    with pytest.raises(ValueError): w.native(fail,None,data())
    assert len(calls)==w.attempts==1 and w.completed==0
    with pytest.raises(RuntimeError,match='PRIOR_TECHNICAL'): w.native(fail,None,data())
    assert len(calls)==1 and 'native failure' in output.getvalue()


@pytest.mark.parametrize('args,kwargs',[(('batch',),{}),((),{'nstep':5})])
def test_native_batch_never_calls_original(args,kwargs):
    w=physical.Witness(1,time.perf_counter()+5,StringIO())
    with pytest.raises(RuntimeError,match='BATCHED'): w.native(lambda *a:pytest.fail('called'),None,data(),*args,**kwargs)
    assert w.attempts==w.completed==0


def test_native_budget_and_deadline_precede_original():
    w=physical.Witness(1,time.perf_counter()+5,StringIO()); calls=[]
    w.native(lambda *a:calls.append(1),None,data())
    with pytest.raises(RuntimeError,match='BUDGET'): w.native(lambda *a:calls.append(2),None,data())
    assert calls==[1] and w.attempts==w.completed==1
    w=physical.Witness(1,0,StringIO())
    with pytest.raises(TimeoutError): w.native(lambda *a:pytest.fail('called'),None,data())
    assert w.attempts==0


def test_nonfinite_raw_evidence_survives_json_archival():
    output=StringIO(); w=physical.Witness(1,time.perf_counter()+5,output)
    d=data(); d.qpos[0]=np.nan
    w.native(lambda *a:None,None,d)
    assert json.loads(output.getvalue().splitlines()[0])['pre']['qpos'][0]=={'nonfinite':'nan'}


def runtime_fixture(monkeypatch, tmp_path, failure=None):
    objects=[]
    mj=NS(mj_step=lambda model,d:setattr(d,'time',d.time+.002))
    class Policy:
        def state_dict(self): return {'hidden':np.zeros(1)}
        def named_modules(self): return [('',self)]
        def __call__(self,*a): return 'synthetic action'
    class Controller:
        def __init__(self): self._policy=Policy(); self._counter=0; self._action=np.zeros(1); self._target=np.zeros(1)
        def compute_torques(self,**kwargs):
            if failure=='control': raise ValueError('InvalidControlError synthetic source')
            self._counter+=1; self._policy('synthetic'); return np.zeros(1)
    class Simulation:
        def __init__(self):
            self._data=data(); self._data.qpos[2]=.78; self.closed=False; self.reset(seed=0); objects.append(self)
            if failure=='nonfinite_init': self._data.ctrl[0]=np.nan
        def reset(self,**kwargs): self._data.time=0.; return self.get_robot_state()
        def get_robot_state(self):
            fallen=failure=='fall' and self._data.time>0
            return RobotState(self._data.time,(0.,0.,.78),(1.,0.,0.,0.),(0.,0.,0.),(0.,0.,0.),not fallen,fallen)
        def step(self,control=None): mj.mj_step(None,self._data); return self.get_robot_state()
        def close(self): self.closed=True
    live=NS(build_simulation=lambda robot,seed:Simulation())
    class Session:
        def __init__(self,**kwargs):
            self.simulation=live.build_simulation({},seed=0); self.controller=Controller()
            self.current_state=self.simulation.reset(seed=0); self.total_steps=0
        def state(self): return self.current_state
        def close(self): self.simulation.close()
    live.LiveMissionSession=Session
    class Collector:
        def __init__(self): self.times=[]; self.qpos=[]; self.qvel=[]; self.ctrl=[]
        def wrap(self,obj): return obj
        def capture(self,sim): self.times.append(sim._data.time); self.qpos.append(sim._data.qpos.copy()); self.qvel.append(sim._data.qvel.copy()); self.ctrl.append(sim._data.ctrl.copy())
        def save(self,path,sim): self.capture(sim); path.write_bytes(b'synthetic poses')
    class Executor:
        def __init__(self,**kwargs): assert kwargs['walk_strict_gate'] is True and 'physical_halt_contract' not in kwargs
        def run(self,mission,existing_session,phase):
            assert mission=={'synthetic':True}
            session=existing_session
            # Simulate Router swallowing a compute exception into UNSAFE.
            try:
                if failure=='reset': session.simulation.reset(seed=0)
                session.simulation.step(session.controller.compute_torques(command=np.zeros(3)))
            except Exception: return NS(to_dict=lambda:{'mission_success':False,'failure_type':'SKILL_FAILURE','failure_reason':'UNSAFE'})
            return NS(to_dict=lambda:{'mission_success':True,'failure_type':None,'failure_reason':None,
                'completed_nodes':3,'nodes':[{}, {}, {}],'simulation_steps_executed':1})
    root=tmp_path/'assets'; root.mkdir(); (root/'xml').write_bytes(b'xml'); (root/'policy').write_bytes(b'policy')
    source={'C_exec':'frozen','root':str(physical.ROOT),'asset_root':str(root),'assets':{'xml':physical.sha(root/'xml'),'policy':physical.sha(root/'policy')}}
    protocol={'robot_config':'ignored','provenance':{'policy_sha256':source['assets']['policy']},
              'grounding':{'evidence':dict(risk_map='risk',boundary_comparison='boundary',capability_map='capability'), 'historical':{},'mode_preference':[]}}
    monkeypatch.setattr(physical,'read',lambda path:protocol)
    monkeypatch.setattr(physical,'validate_preparation',lambda p:canonical(p['mission']))
    monkeypatch.setattr(physical,'_runtime',lambda:{'np':np,'torch':NS(set_num_threads=lambda n:None,use_deterministic_algorithms=lambda x:None,manual_seed=lambda n:None),
        'random':NS(seed=lambda n:None),'mujoco':mj,'load_yaml':lambda p:{'model':{'xml_path':'xml'},'controller':{'policy_path':'policy'}},
        'live_session':live,'G1Simulation':Simulation,'G1LocomotionController':Controller,'PoseCollector':Collector,
        'CapabilityGrounder':lambda **k:None,'MissionExecutor':Executor,'MissionValidator':lambda:None,
        'Mission':NS(from_dict=lambda p:p)})
    prep={'C_exec':'frozen','budget':{'native_steps':15000},'mission':{'synthetic':True},'request_id':'synthetic','preparation_sha256':'synthetic'}
    prep['mission_sha256']=digest(canonical(prep['mission']))
    directory=tmp_path/'run'; directory.mkdir()
    return prep,source,directory,objects


@pytest.mark.parametrize('failure',[None,'control','fall'])
def test_full_backend_preserves_count_axes_swallowed_errors_and_close(monkeypatch,tmp_path,failure):
    p,s,d,objects=runtime_fixture(monkeypatch,tmp_path,failure)
    r=physical.execute(p,s,d,time.perf_counter()+5)
    assert objects[0].closed and r['startup_reset_requests']==2 and r['post_checkpoint_reset_requests']==0
    assert (d/'native.jsonl').exists() and (d/'physical.json').exists()
    if failure=='control':
        assert r['technical_errors'][0]['stage']=='controller_compute' and r['native_completed']==0
        assert r['physical_failure']=={'fallen':False,'nonfinite':False}
    elif failure=='fall':
        assert r['physical_failure']['fallen'] and r['native_completed']==1
        assert r['technical_errors']==[]
    else:
        assert r['status']=='COMPLETED' and r['native_attempts']==r['native_completed']==1
        assert r['policy_inference_attempts']==r['policy_inference_completed']==1
        rows=[json.loads(line) for line in (d/'native.jsonl').read_text().splitlines()]
        assert [row['policy_attempt'] for row in rows if 'policy_attempt' in row]==[1]
        assert [row['policy_completed'] for row in rows if 'policy_completed' in row]==[1]
    assert r['executed_mission_sha256']==digest(canonical(p['mission']))


def test_post_checkpoint_reset_is_error_even_when_swallowed(monkeypatch,tmp_path):
    p,s,d,objects=runtime_fixture(monkeypatch,tmp_path,'reset')
    r=physical.execute(p,s,d,time.perf_counter()+5)
    assert objects[0].closed and r['startup_reset_requests']==2
    assert r['post_checkpoint_reset_requests']==1 and r['native_completed']==0
    assert r['technical_errors'][0]['stage']=='reset_guard'


def test_nonfinite_initial_controller_buffer_refuses_execution(monkeypatch,tmp_path):
    p,s,d,objects=runtime_fixture(monkeypatch,tmp_path,'nonfinite_init')
    r=physical.execute(p,s,d,time.perf_counter()+5)
    assert objects[0].closed and r['native_attempts']==r['policy_inference_attempts']==0
    assert 'INITIAL_LIVE_STATE_NOT_ELIGIBLE' in r['technical_errors'][0]['message']


def test_closed_backend_files_exclude_open_job_receipts_and_worker_logs(monkeypatch,tmp_path):
    from g1swarm.language_v01.observations import audit_capture
    p,s,d,_=runtime_fixture(monkeypatch,tmp_path)
    pending=[]
    for name in ('outer-process/process_receipt.json','worker-process/process_receipt.json','worker.log',
                 'launch.json','authorization.json','worker-used.json'):
        path=d/name; path.parent.mkdir(exist_ok=True); path.write_bytes(b''); pending.append(path)
    result=physical.execute(p,s,d,time.perf_counter()+5)
    assert not any(path.relative_to(d).as_posix() in result['files'] for path in pending)
    assert audit_capture(d,p)['passed']
    for path in pending: path.write_bytes(b'finalized after backend exited')
    assert audit_capture(d,p)['passed']
    with (d/'native.jsonl').open('a') as stream: stream.write('{}\n')
    audited=audit_capture(d,p)
    assert not audited['passed'] and 'CAPTURE_FILE_MISMATCH:native.jsonl' in audited['errors']


def test_constructor_crosses_supplied_owner_deadline_without_native_or_policy(monkeypatch,tmp_path):
    p,s,d,objects=runtime_fixture(monkeypatch,tmp_path)
    clock=[100.]
    monkeypatch.setattr(physical.time,'perf_counter',lambda:clock[0])
    runtime=physical._runtime(); original=runtime['live_session'].LiveMissionSession
    def expired_initialization(**kwargs):
        session=original(**kwargs); clock[0]=151.; return session
    runtime['live_session'].LiveMissionSession=expired_initialization
    monkeypatch.setattr(physical,'_runtime',lambda:runtime)
    result=physical.execute(p,s,d,150.)
    assert objects[0].closed and result['startup_reset_requests']==2
    assert result['native_attempts']==result['native_completed']==0
    assert result['policy_inference_attempts']==result['policy_inference_completed']==0
    assert result['technical_errors'][0]['type']=='TimeoutError'
    assert 'PHYSICAL_DEADLINE_EXCEEDED' in result['technical_errors'][0]['message']


@pytest.mark.parametrize('kind,count',[('SYNTHETIC_OFFLINE_COMPONENT',1),('NEW_MUJOCO_CAPTURE',0)])
def test_media_rejects_synthetic_or_zero_steps_before_renderer_import(tmp_path,kind,count):
    physical.write(tmp_path/'physical.json',{'kind':kind,'C_exec':'frozen','native_completed':count,'files':{'poses.npz':'x'}})
    with pytest.raises(PermissionError,match='NO_QUALIFIED'): media.render_saved(tmp_path,{'C_exec':'frozen'},time.perf_counter()+5)
    assert 'mujoco' not in sys.modules and 'torch' not in sys.modules


def test_media_rejects_new_run_bytes_drift_before_renderer_import(tmp_path):
    (tmp_path/'poses.npz').write_bytes(b'modified')
    physical.write(tmp_path/'physical.json',{'kind':'NEW_MUJOCO_CAPTURE','C_exec':'frozen','native_completed':1,'files':{'poses.npz':'wrong'}})
    with pytest.raises(ValueError,match='CONTENT_DRIFT'): media.render_saved(tmp_path,{'C_exec':'frozen'},time.perf_counter()+5)


def test_native_error_preserves_post_unknown_and_physical_failure_independently():
    output=StringIO(); w=physical.Witness(2,time.perf_counter()+5,output)
    w.state_reader=lambda:NS(fallen=True,is_finite=lambda:False,to_dict=lambda:{'fallen':True})
    d=data()
    def fail(model,d): d.time=.002; d.qpos[0]=np.nan; raise ValueError('real native fault')
    with pytest.raises(ValueError): w.native(fail,None,d)
    assert w.physical=={'fallen':True,'nonfinite':True} and w.errors[0]['stage']=='native_step'
    post=[json.loads(line) for line in output.getvalue().splitlines() if 'native_post_unknown' in line][0]
    assert post['raw']['time_s']==.002 and post['raw']['qpos'][0]=={'nonfinite':'nan'}
    assert w.attempts==1 and w.completed==0


def test_missing_post_error_state_is_explicit_unknown_and_next_step_refused():
    output=StringIO(); w=physical.Witness(2,time.perf_counter()+5,output)
    with pytest.raises(ValueError): w.native(lambda *a:(_ for _ in ()).throw(ValueError('fault')),None,data())
    assert w.physical_observation['fallen']=='UNKNOWN'
    with pytest.raises(RuntimeError,match='PRIOR_TECHNICAL'): w.native(lambda *a:pytest.fail('retry'),None,data())


def test_observed_physical_failure_refuses_next_step_without_technical_error():
    output=StringIO(); w=physical.Witness(2,time.perf_counter()+5,output)
    w.state_reader=lambda:NS(fallen=True,is_finite=lambda:True,to_dict=lambda:{'fallen':True})
    w.native(lambda *a:None,None,data())
    with pytest.raises(physical.PhysicalStop): w.native(lambda *a:pytest.fail('step'),None,data())
    assert w.attempts==1 and w.completed==1 and w.errors==[]


def test_fake_renderer_receives_only_new_directory_and_frozen_dimensions(monkeypatch,tmp_path):
    (tmp_path/'poses.npz').write_bytes(b'fake-capture'); (tmp_path/'result.json').write_bytes(b'{}')
    receipt={'kind':'NEW_MUJOCO_CAPTURE','C_exec':'frozen','native_completed':1,'request_id':'synthetic-test',
             'preparation_sha256':'p','executed_mission_sha256':'m',
             'files':{name:physical.sha(tmp_path/name) for name in ('poses.npz','result.json')}}
    physical.write(tmp_path/'physical.json',receipt)
    (tmp_path/'encoder').write_bytes(b'fake-encoder')
    model_rel='third_party/unitree_rl_gym/resources/robots/g1_description/scene.xml'
    model=tmp_path/model_rel; model.parent.mkdir(parents=True); model.write_bytes(b'fake-model')
    calls=[]; mj=NS(mj_step=lambda *a:None)
    def render(directory,target,**kwargs):
        calls.append((directory,target,kwargs)); target.write_bytes(b'fake-video')
        with pytest.raises(RuntimeError,match='PHYSICS'): mj.mj_step()
        return {'passed':True,'mj_step_calls':0,'source_pose_sha256':receipt['files']['poses.npz']}
    module=NS(render=render,mujoco=mj)
    monkeypatch.setattr(media.importlib.util,'spec_from_file_location',lambda *a:NS(loader=NS(exec_module=lambda m:None)))
    monkeypatch.setattr(media.importlib.util,'module_from_spec',lambda spec:module)
    source={'C_exec':'frozen','renderer':{'exe':str(tmp_path/'encoder'),'sha256':physical.sha(tmp_path/'encoder')},
            'asset_root':str(tmp_path),'assets':{model_rel:physical.sha(model)}}
    result=media.render_saved(tmp_path,source,time.perf_counter()+5)
    assert calls==[(tmp_path.resolve(),tmp_path.resolve()/'video.mp4',{'width':640,'height':360})]
    assert result['historical_fallback'] is False and result['width']==640 and result['height']==360
