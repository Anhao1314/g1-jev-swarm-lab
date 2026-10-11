"""Exactly one frozen campaign: B0, B1, check_env, 256-decision PPO. No retries."""
import hashlib, importlib.metadata, importlib.util, json, os, subprocess, sys, time, traceback
from pathlib import Path

REPO=Path(__file__).resolve().parents[3]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(manifest, expected_sha=None):
    if expected_sha is not None and sha(manifest)!=expected_sha:
        raise RuntimeError("frozen_manifest_sha256_mismatch")
    m=json.loads(Path(manifest).read_text())
    head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=REPO,text=True).strip()
    if head!=m["execution_head"]: raise RuntimeError("execution_head_drift")
    if subprocess.check_output(["git","status","--porcelain","--untracked-files=no"],cwd=REPO,text=True).strip():
        raise RuntimeError("tracked_source_dirty")
    if Path(sys.prefix).resolve() != Path(m["venv"]).resolve(): raise RuntimeError("venv_identity_drift")
    if os.environ.get("G1SWARM_ROOT") or os.environ.get("PYTHONHOME"):
        raise RuntimeError("source_override_forbidden")
    origin=importlib.util.find_spec("g1swarm").origin
    if Path(origin).resolve()!=REPO/"src/g1swarm/__init__.py": raise RuntimeError("actual_import_source_drift")
    if sha(Path(sys.executable).resolve()) != m["python_executable_sha256"]:
        raise RuntimeError("python_executable_drift")
    for p,h in m["installed_files"].items():
        if sha(Path(sys.prefix)/p)!=h: raise RuntimeError("installed_dependency_drift:"+p)
    for p,h in m["files"].items():
        if sha(REPO/p)!=h: raise RuntimeError("source_or_asset_drift:"+p)
    for name,version in m["dependencies"].items():
        if importlib.metadata.version(name)!=version: raise RuntimeError("dependency_drift:"+name)
    if m["scenario"]!={"case":"historical_seen_nominal4m","seed":7,"target_m":4.,"speed_mps":.5,"horizon_s":24.}:
        raise RuntimeError("scenario_drift")
    if m["budgets"]!={"native_steps":60000,"physical_wall_s":1800,"ppo_decisions":256,"ppo_wall_s":600}:
        raise RuntimeError("budget_drift")
    return m

def main(root,manifest,expected_sha):
    freeze=verify(manifest,expected_sha)  # before Torch, MuJoCo, or real policy modules load
    import numpy as np
    import torch
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True); torch.manual_seed(7); np.random.seed(7)
    from g1swarm.residual_rl.environment import Ledger,make_stack,metrics,G1YawResidualEnv
    from g1swarm.control.path_correction import CorrectingController
    from g1swarm.segmentation.mission import MissionFrame
    from g1swarm.skills.basic import WalkForwardSkill
    from g1swarm.skills.contract import SkillContext
    ledger=Ledger(root)
    try:
        ledger.stage="B0"
        robot,sim,low,policy=make_stack(ledger,baseline=True)
        sim.reset(seed=7); frame=MissionFrame.from_state(sim.get_robot_state())
        ctrl=CorrectingController(low,policy,sim,frame)
        context=SkillContext(simulation=sim,controller=ctrl,robot_config=robot,
            parameters={"target_distance_m":4.,"speed_mps":.5,"max_duration_s":24.},max_steps=12000,seed=7)
        skill=WalkForwardSkill()
        if skill.check_preconditions(context): raise RuntimeError("B0_precondition")
        result=skill.run(context); b0=sim.rows.copy(); b0metric=metrics(sim,frame)
        (root/"b0.json").write_text(json.dumps({"skill":result.to_dict(),"evaluation":b0metric},indent=2))
        sim.close()
        ledger.stage="B1"
        env=G1YawResidualEnv(ledger); env.reset(seed=7)
        done=False
        while not done:
            _,_,terminated,truncated,_=env.step(np.array([0.],dtype=np.float32)); done=terminated or truncated
        b1=env.sim.rows.copy(); b1metric=metrics(env.sim,env.frame)
        (root/"b1.json").write_text(json.dumps({"evaluation":b1metric},indent=2))
        equal=b0==b1 and b0metric==b1metric
        comparison={"exact_native_rows":equal,"b0_native_steps":len(b0),"b1_native_steps":len(b1),
                    "evaluations_exact":b0metric==b1metric,"tolerance":0.,"reset_counts_exact":True if equal else False}
        (root/"equivalence.json").write_text(json.dumps(comparison,indent=2))
        if not equal: raise RuntimeError("B0_B1_not_exactly_equivalent")
        env.close(); print({"B0_B1":"PASS","native_steps":len(b0)+len(b1)},flush=True)
        ledger.stage="check_env"
        from stable_baselines3.common.env_checker import check_env
        env=G1YawResidualEnv(ledger)
        env.action_space.seed(7)
        check_env(env,warn=True,skip_render_check=True)
        ledger.event("check_env_pass",native_completed=ledger.completed)
        env.close()
        ledger.stage="train"
        marker={"monotonic":time.monotonic()}
        tmp=root/"training-start.tmp"; tmp.write_text(json.dumps(marker)); tmp.rename(root/"training-start.json")
        from g1swarm.residual_rl.ppo import AuditedPPO,BoundedYawPolicy
        env=G1YawResidualEnv(ledger); env.decision_cap=256
        model=AuditedPPO(BoundedYawPolicy,env,n_steps=128,batch_size=64,n_epochs=2,learning_rate=3e-4,
                        gamma=.99,gae_lambda=.95,clip_range=.2,target_kl=.03,
                        policy_kwargs={"net_arch":[32,32]},seed=7,device="cpu",verbose=0)
        model.attach_audit(root,ledger); model.save(root/"checkpoint-0")
        model.learn(total_timesteps=256)
        if model.num_timesteps!=256 or env.train_decisions!=256: raise RuntimeError("decision_count_mismatch")
        if time.monotonic()-marker["monotonic"]>=595: raise RuntimeError("ppo_time_budget")
        obs=np.zeros(18,dtype=np.float32)
        expected=model.predict(obs,deterministic=True)[0]
        restored=AuditedPPO.load(root/"checkpoint-256.zip",device="cpu")
        if not np.array_equal(expected,restored.predict(obs,deterministic=True)[0]): raise RuntimeError("reload_action_mismatch")
        if not all(torch.equal(v,restored.policy.state_dict()[k]) for k,v in model.policy.state_dict().items()):
            raise RuntimeError("reload_tensor_mismatch")
        if time.monotonic()-marker["monotonic"] >= 595 or time.monotonic()-ledger.started >= 1790:
            raise RuntimeError("final_budget_recheck_failed")
        final={"verdict":"T1_PPO_SMOKE_PIPELINE_PASS","ppo_decisions":model.num_timesteps,
               "optimizer_steps":model.optimizer_steps,"epoch_updates":model._n_updates,
               "native_completed":ledger.completed,"native_reserved":ledger.reserved,
               "physical_wall_s":time.monotonic()-ledger.started,
               "training_wall_s":time.monotonic()-marker["monotonic"],"checkpoint_reload":"PASS",
               "checkpoint_sha256":{str(n):sha(root/f"checkpoint-{n}.zip") for n in (0,128,256)},
               "B0_B1":comparison,"performance_claim":False,"freeze_sha256":sha(manifest)}
        (root/"result.json").write_text(json.dumps(final,indent=2)); print(final,flush=True); env.close()
    except BaseException as exc:
        failure={"verdict":"T1_BLOCKED_WITH_EXACT_EVIDENCE","stage":ledger.stage,"type":type(exc).__name__,
                 "reason":str(exc),"traceback":traceback.format_exc(),"native_completed":ledger.completed,
                 "native_reserved":ledger.reserved,"physical_wall_s":time.monotonic()-ledger.started}
        (root/"failure.json").write_text(json.dumps(failure,indent=2)); print(failure,flush=True)
        raise
    finally: ledger.close()

if __name__=="__main__": main(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3])
