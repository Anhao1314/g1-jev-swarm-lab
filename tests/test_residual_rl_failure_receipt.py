"""Reproduce only the SB3 info collision. No learn, env.step, or optimizer call."""
from collections import deque
import json
import gymnasium as gym
import numpy as np
import pytest
from gymnasium import spaces
from stable_baselines3.common.logger import configure
from g1swarm.residual_rl.ppo import AuditedPPO,BoundedYawPolicy

class NoExecution(gym.Env):
    action_space=spaces.Box(-1,1,(1,),dtype=np.float32)
    observation_space=spaces.Box(-1,1,(18,),dtype=np.float32)
    def reset(self,**kw): raise AssertionError('no new interaction')
    def step(self,a): raise AssertionError('no new interaction')


def test_exact_sb3_episode_namespace_collision_without_training(tmp_path):
    model=AuditedPPO(BoundedYawPolicy,NoExecution(),n_steps=128,batch_size=64,n_epochs=2,
                    policy_kwargs={'net_arch':[32,32]},seed=7,device='cpu')
    model.set_logger(configure(str(tmp_path),[]))
    model.ep_info_buffer=deque(maxlen=100); model.ep_success_buffer=deque(maxlen=100)
    model._update_info_buffer([{'episode':1}],np.array([False]))
    with pytest.raises(TypeError,match="object of type 'int' has no len"):
        model.dump_logs(1)
    assert model.num_timesteps==0 and not model.policy.optimizer.state
    # Proposed future repair is validated against SB3 ingestion only, not applied to frozen adapter.
    model.ep_info_buffer.clear()
    model._update_info_buffer([{'case_episode':1}],np.array([False]))
    assert len(model.ep_info_buffer)==0
    (tmp_path/'collision-receipt.json').write_text(json.dumps({'current_episode_key':'TypeError reproduced',
        'future_case_episode_key':'no reserved-buffer pollution','environment_steps':0,'optimizer_steps':0}))
