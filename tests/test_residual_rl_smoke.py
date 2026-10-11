"""Nonphysical T1 adapter, distribution and identity rejection tests."""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
import torch
from gymnasium import spaces
from g1swarm.residual_rl.environment import G1YawResidualEnv, ResidualCorrection, REPO, Ledger, PhysicalAbort
from g1swarm.residual_rl.contract import ResidualContractError
from g1swarm.residual_rl.ppo import BoundedYawPolicy
from g1swarm.segmentation.mission import MissionFrame
from g1swarm.state.robot_state import RobotState


def test_action_policy_is_bounded_without_clipping():
    torch.set_num_threads(1)
    p=BoundedYawPolicy(spaces.Box(-1,1,(18,),dtype=np.float32),spaces.Box(-1,1,(1,),dtype=np.float32),
                       lambda _:3e-4,net_arch=[32,32])
    obs=torch.zeros((1024,18))
    a,values,logp=p(obs)
    assert p.squash_output and torch.isfinite(logp).all()
    assert (a.abs()<=1).all()
    _,lp,entropy=p.evaluate_actions(obs,a)
    assert torch.allclose(lp,logp,atol=1e-5) and entropy is None
    assert p.optimizer.state=={} # no optimizer update in this test

@pytest.mark.parametrize("a",[[1.01],[float("nan")],[0,0]])
def test_invalid_action_rejected_before_simulation(a):
    env=object.__new__(G1YawResidualEnv); env.done=False
    with pytest.raises(ResidualContractError): env.step(a)

@pytest.mark.parametrize("yaw",[0,.1,-.2,.6,-.6])
def test_zero_residual_matches_original_correction(yaw):
    state=RobotState(0,(0,yaw,.8),(1,0,0,0),(0,0,0),(0,0,0),True,False,"walk_forward")
    frame=MissionFrame((0,0,.8),0)
    a=ResidualCorrection(baseline=True); b=ResidualCorrection()
    ac,asample=a.compute(state,frame,np.array([.5,0,0]),sim_time_s=0)
    bc,bsample=b.compute(state,frame,np.array([.5,0,0]),sim_time_s=0)
    assert np.array_equal(ac,bc) and asample==bsample


def load(name):
    path=REPO/"experiments/rl/g1_ppo_yaw_smoke_001"/f"{name}.py"
    spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod); return mod


def test_wrong_head_rejected_before_physics_import(tmp_path):
    # No imports of runtime modules occur inside verify; wrong HEAD fails first.
    p=tmp_path/"manifest.json"; p.write_text(json.dumps({"execution_head":"0"*40}))
    with pytest.raises(RuntimeError,match="execution_head_drift"): load("run").verify(p)


def test_budget_stops_before_extra_native_call(tmp_path):
    l=Ledger(tmp_path,limit=1); l.reserve()
    with pytest.raises(PhysicalAbort,match="budget"): l.reserve()
    assert l.reserved==1 and l.completed==0
    l.close()


def test_linux_watchdog_kills_descendant(tmp_path):
    child=tmp_path/"child.py"; ids=tmp_path/"pids.json"
    child.write_text("import os,sys,subprocess,json,time\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\nopen(sys.argv[1],'w').write(json.dumps([os.getpid(),p.pid]))\ntime.sleep(60)\n")
    receipt=load("watchdog").bounded([sys.executable,str(child),str(ids)],tmp_path/"proof",.3)
    assert receipt["interrupted"]=="wall_clock_watchdog" and receipt["elapsed_s"]<3
    pids=json.loads(ids.read_text())
    def live(pid):
        p=Path(f"/proc/{pid}/stat")
        return p.exists() and p.read_text().split()[2] not in ("Z","X")
    assert not any(live(p) for p in pids)
    (tmp_path/"proof"/"descendant-proof.json").write_text(json.dumps({"pids":pids,"none_running":True}))


def test_checkpoint_roundtrip_without_training(tmp_path):
    import gymnasium as gym
    from g1swarm.residual_rl.ppo import AuditedPPO
    class NoPhysics(gym.Env):
        observation_space=spaces.Box(-1,1,(18,),dtype=np.float32)
        action_space=spaces.Box(-1,1,(1,),dtype=np.float32)
        def reset(self,*,seed=None,options=None):
            super().reset(seed=seed); return np.zeros(18,dtype=np.float32),{}
        def step(self,a): raise AssertionError("no physics or environment interaction in this test")
    model=AuditedPPO(BoundedYawPolicy,NoPhysics(),n_steps=128,batch_size=64,n_epochs=2,
                    policy_kwargs={"net_arch":[32,32]},seed=7,device="cpu")
    ledger=Ledger(tmp_path/"raw"); model.attach_audit(tmp_path,ledger)
    model.save(tmp_path/"nonphysical")
    restored=AuditedPPO.load(tmp_path/"nonphysical",device="cpu")
    assert all(torch.equal(v,restored.policy.state_dict()[k]) for k,v in model.policy.state_dict().items())
    assert model.optimizer_steps==0 and model.num_timesteps==0
    ledger.close()
