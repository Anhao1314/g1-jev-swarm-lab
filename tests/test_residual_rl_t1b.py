"""T1b metadata regressions using a synthetic state source; zero MuJoCo/policy calls."""
from collections import deque
import json
import time
from types import SimpleNamespace
import gymnasium as gym
import numpy as np
from gymnasium import spaces
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.logger import configure
from g1swarm.residual_rl.environment import G1YawResidualEnv, ResidualCorrection
from g1swarm.residual_rl.ppo import AuditedPPO, BoundedYawPolicy
from g1swarm.control.g1_locomotion import G1LocomotionController
from g1swarm.state.robot_state import RobotState

class SyntheticStateSource:
    timestep=.002
    def __init__(self):
        self.resets=0; self.episode=-1; self.episode_steps=0; self.simulation_time=0.; self.active_skill=None
        self._data=SimpleNamespace(qpos=np.array([0.,0.,.8,1.,0.,0.,0.]))
    def reset(self,*,seed):
        assert seed==7
        self.resets+=1;self.episode+=1;self.episode_steps=0;self.simulation_time=0.
        self._data.qpos[:3]=[0.,0.,.8]
    def get_robot_state(self):
        return RobotState(self.simulation_time,tuple(self._data.qpos[:3]),(1.,0.,0.,0.),
                          (0.,0.,0.),(0.,0.,0.),True,False,self.active_skill)
    def set_active_skill(self,name): self.active_skill=name
    def step(self,torques):
        assert np.array_equal(torques,np.zeros(12))
        self.episode_steps+=1; self.simulation_time=self.episode_steps*self.timestep
        self._data.qpos[0]=self.episode_steps*.01
        return self.get_robot_state()
    def joint_positions(self): return np.zeros(12)
    def joint_velocities(self): return np.zeros(12)
    def base_quaternion(self): return np.array([1.,0.,0.,0.])
    def base_angular_velocity(self): return np.zeros(3)
    def close(self): pass

class SyntheticController:
    get_gravity_orientation=staticmethod(G1LocomotionController.get_gravity_orientation)
    def __init__(self): self.resets=0
    def reset(self): self.resets+=1
    def compute_torques(self,**kw): return np.zeros(12)

class Events:
    def __init__(self): self.records=[]; self.completed=0
    def event(self,kind,**kw): self.records.append({'kind':kind,**kw})

def adapter():
    env=object.__new__(G1YawResidualEnv)
    env.action_space=spaces.Box(-1,1,(1,),dtype=np.float32)
    env.observation_space=spaces.Box(-1,1,(18,),dtype=np.float32)
    env.sim=SyntheticStateSource(); env.low=SyntheticController(); env.policy=ResidualCorrection()
    env.ledger=Events(); env.done=True;env.train_decisions=0;env.decision_cap=None
    return env

def test_actual_adapter_reset_step_public_metadata():
    env=adapter(); obs,info=env.reset(seed=7)
    assert isinstance(info['case_episode'],int) and 'episode' not in info
    assert not {'is_success','terminal_observation','TimeLimit.truncated'} & set(info)
    _,reward,terminated,truncated,info=env.step(np.array([0.],dtype=np.float32))
    assert not terminated and not truncated and 'episode' not in info
    assert info['case_episode']==0 and np.isfinite(reward)
    # Raw reset event retains original episode name, not public wrapper name.
    assert env.ledger.records[0]['episode']==0 and 'case_episode' not in env.ledger.records[0]
    assert 'episode' not in env.ledger.records[1]['info']

def test_monitor_summary_and_sb3_logging_no_reserved_collision(tmp_path):
    env=adapter(); monitored=Monitor(env); monitored.reset(seed=7)
    model=AuditedPPO(BoundedYawPolicy,monitored,n_steps=128,batch_size=64,n_epochs=2,
                    policy_kwargs={'net_arch':[32,32]},seed=7,device='cpu')
    model.set_logger(configure(str(tmp_path),[]));model.ep_info_buffer=deque(maxlen=100)
    model.ep_success_buffer=deque(maxlen=100);model.start_time=time.time_ns();model._num_timesteps_at_start=0
    done=False; summaries=0;calls=0
    while not done:
        _,_,terminated,truncated,info=monitored.step(np.array([0.],dtype=np.float32))
        done=terminated or truncated; calls+=1
        assert info['case_episode']==0
        if done:
            assert isinstance(info['episode'],dict)
            assert set(info['episode'])=={'r','l','t'} and info['episode']['l']==calls
            summaries+=1
        else: assert 'episode' not in info
        model._update_info_buffer([info],np.array([done]))
    assert summaries==1 and len(model.ep_info_buffer)==1
    model.dump_logs(1)
    assert model.num_timesteps==0 and not model.policy.optimizer.state
    (tmp_path/'metadata-receipt.json').write_text(json.dumps({'actual_adapter_public_key':'case_episode',
        'raw_reset_key':'episode','SB3_episode_summary':'dict(r,l,t)','summary_count':1,
        'real_physics_steps':0,'official_policy_calls':0,'learn_calls':0,'optimizer_steps':0}))

def test_external_cap_keeps_monitor_summary_without_claiming_task_success(tmp_path):
    env=adapter();env.decision_cap=1; m=Monitor(env);m.reset(seed=7)
    _,_,terminated,truncated,info=m.step(np.array([0.],dtype=np.float32))
    assert truncated and not terminated
    assert info['case_episode']==0 and isinstance(info['episode'],dict)
    assert info['truncation_reason']=='external_smoke_decision_budget' and info['outcome'] is None
