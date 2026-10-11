"""Nonphysical candidate T2a guard/scoring checks; no policy load or prediction."""
import hashlib,importlib.util,json,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'experiments/rl/g1_ppo_t2a_frozen_comparison_001'
spec=importlib.util.spec_from_file_location('t2_comparison',HERE/'comparison.py'); c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

def gates(a,b,d):return {'physical_success':a,'task_success':b,'strict_success':d}
@pytest.mark.parametrize('outcomes,expected',[
 ({'B0':gates(1,1,1),'C0':gates(1,1,1),'C256':gates(1,1,1)},'NO_MEANINGFUL_GAIN'),
 ({'B0':gates(1,1,0),'C0':gates(1,1,0),'C256':gates(1,1,1)},'IMPROVED_SEEN_CASE'),
 ({'B0':gates(1,1,1),'C0':gates(1,1,1),'C256':gates(0,0,0)},'REGRESSION'),
 ({'B0':gates(1,1,1)},'INCONCLUSIVE'),
 ({'B0':gates(1,1,1),'C0':gates(1,1,1),'C256':{**gates(1,1,1),'technical_invalid':True}},'INCONCLUSIVE')])
def test_frozen_gate_classification(outcomes,expected):assert c.classify(outcomes)==expected


def test_continuous_delta_is_common_clock_not_extrapolation():
    row=lambda t,l:{'t':t,'lateral_m':l,'heading_deg':0.,'residual_yaw':0.}
    v=c.matched_delta([row(.002,0),row(.004,1)],[row(.002,.1)])
    assert v['common_native_samples']==1 and v['common_end_s']==.002
    assert v['lateral_delta_rms_m']==pytest.approx(.1)
    with pytest.raises(ValueError,match='clock'):c.matched_delta([row(.002,0)],[row(.003,0)])


def test_default_entry_refuses_before_runtime_modules(tmp_path):
    p=subprocess.run([sys.executable,'-B',str(HERE/'run.py'),str(tmp_path/'acquisition'),str(tmp_path/'no-manifest'),'0'*64],capture_output=True,text=True,timeout=5)
    assert p.returncode!=0 and 'OWNER_CONFIRMATION_REQUIRED_BEFORE_PHYSICS' in p.stderr
    assert not (tmp_path/'acquisition').exists()


def test_checkpoint_and_protocol_membership_are_pinned():
    p=json.loads((HERE/'protocol.json').read_text())
    assert p['groups']==['B0','C0','C256'] and p['optimizer_updates_allowed']==0
    assert p['authorization_status']=='OWNER_CONFIRMATION_PENDING'
    assert p['checkpoints']['C256']['sha256']=='cc383df4f9508d9db97f12043f483e4b8e7ae5ee7bf0d1de015197384ef486d2'
    assert p['budgets']['total_native_steps']==3*p['budgets']['per_group_native_steps']==36000



def test_fake_actor_is_deterministic_and_training_is_blocked():
    from types import SimpleNamespace
    calls=[]
    class Fake:
        def __init__(self):self.policy=SimpleNamespace(optimizer=SimpleNamespace(step=lambda:calls.append('optimizer')))
        def learn(self):calls.append('learn')
        def train(self):calls.append('train')
        def predict(self,obs,*,deterministic):calls.append(('predict',deterministic));return [.1],None
    actor=Fake();c.lock_actor(actor)
    for method in (actor.learn,actor.train,actor.policy.optimizer.step):
        with pytest.raises(RuntimeError,match='forbidden'):method()
    assert calls==[]
    assert c.frozen_action(actor,None)==[.1] and calls==[('predict',True)]

@pytest.mark.parametrize('bad',[[1.01],[float('nan')],[0,0]])
def test_invalid_fake_actor_action_refused(bad):
    from types import SimpleNamespace
    fake=SimpleNamespace(predict=lambda obs,deterministic:(bad,None))
    with pytest.raises(ValueError,match='invalid'):c.frozen_action(fake,None)


def test_native_heading_uses_original_normalized_frame_metric():
    import math
    from types import SimpleNamespace
    from g1swarm.segmentation.mission import MissionFrame
    frame=MissionFrame((0.,0.,.8),.2)
    quaternion=[2*math.cos(.3),0.,0.,2*math.sin(.3)]
    row={'sim_time':.002,'qpos':[1.,.1,.8]+quaternion,'deterministic_command':[.5,0.,0.],
         'applied_command':[.5,0.,0.]}
    value=c.curves([row],frame)['values'][0]
    expected=frame.heading_error_deg(SimpleNamespace(base_orientation=quaternion))
    assert value['heading_deg']==expected and expected==pytest.approx(math.degrees(.4))
