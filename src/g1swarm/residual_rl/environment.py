"""T1-only yaw residual Gymnasium adapter. Frozen lower layers are delegated."""
from __future__ import annotations
import dataclasses
import json
import math
import time
from pathlib import Path
import gymnasium as gym
import numpy as np
import yaml
from gymnasium import spaces
from g1swarm.control.g1_locomotion import G1LocomotionConfig, G1LocomotionController
from g1swarm.control.path_correction import CorrectionConfig, PathCorrectionPolicy, CorrectingController
from g1swarm.simulation.g1_simulation import G1ModelConfig, G1Simulation
from g1swarm.segmentation.mission import MissionFrame
from g1swarm.skills.basic import _tilt_deg
from g1swarm.boundary.envelope import evaluate_walk_task
from .contract import apply_yaw_residual, classify_boundary, BoundaryKind, ResidualContractError

REPO = Path(__file__).resolve().parents[3]
SCALES = {"lateral_m": .35, "target_m": 4., "horizon_s": 24., "velocity_mps": .5,
          "yaw_radps": .6, "height_m": .2, "heading_rad": math.radians(15)}

class PhysicalAbort(RuntimeError):
    pass

class Ledger:
    """Reservation is flushed before every mj_step; partial evidence survives interruption."""
    def __init__(self, root, limit=60000):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.file = (self.root / "native.jsonl").open("x", buffering=1)
        self.events = (self.root / "decisions.jsonl").open("x", buffering=1)
        self.limit, self.reserved, self.completed = limit, 0, 0
        self.started = time.monotonic()
        self.stage = "not_started"
    def event(self, kind, **kw):
        self.events.write(json.dumps({"kind":kind, "stage":self.stage, **kw}, allow_nan=False)+"\n")
    def reserve(self):
        if self.reserved >= self.limit or time.monotonic()-self.started >= 1790:
            raise PhysicalAbort("global_physical_budget_exhausted")
        self.reserved += 1
        self.file.write(json.dumps({"reservation":self.reserved,"stage":self.stage})+"\n")
    def complete(self, row):
        self.completed += 1
        self.file.write(json.dumps({"completed":self.completed,"stage":self.stage, **row}, allow_nan=False)+"\n")
    def close(self):
        self.file.close(); self.events.close()

class RecordedController(G1LocomotionController):
    def __init__(self, *a, **kw):
        self.resets = 0
        super().__init__(*a, **kw)
    def reset(self):
        self.resets += 1
        super().reset()
    def compute_torques(self, **kw):
        self.last_command = np.array(kw["command"], copy=True)
        return super().compute_torques(**kw)

class RecordedSimulation(G1Simulation):
    def __init__(self, *a, ledger, **kw):
        self.ledger, self.resets, self.episode, self.episode_steps = ledger, 0, -1, 0
        self.low = self.policy = None
        self.rows = []
        super().__init__(*a, **kw)
    def reset(self, **kw):
        self.resets += 1; self.episode += 1; self.episode_steps = 0; self.rows=[]
        return super().reset(**kw)
    def step(self, control=None):
        self.ledger.reserve()
        state = super().step(control)
        self.episode_steps += 1
        row = {"episode":self.episode,"step":self.episode_steps,"sim_time":self.simulation_time,
               "qpos":self._data.qpos.tolist(),"qvel":self._data.qvel.tolist(),
               "torques":np.asarray(control).tolist(),"deterministic_command":self.policy.last_det.tolist(),
               "applied_command":self.low.last_command.tolist(),"target":self.low.target_angles().tolist(),
               "counter":self.low._counter,"controller_resets":self.low.resets,"simulator_resets":self.resets,
               "fallen":state.fallen,"active_skill":self.active_skill}
        self.rows.append(row)
        self.ledger.complete(row)
        if state.fallen:
            self.ledger.event("physical_failure", row=row)
            raise PhysicalAbort("inherited_fall_height_or_tilt")
        return state

class ResidualCorrection(PathCorrectionPolicy):
    def __init__(self, *, baseline=False):
        super().__init__(CorrectionConfig(mode="heading_lateral", k_heading=1.5, k_lateral=1.0))
        self.action=0.; self.baseline=baseline; self.last_saturated=False
    def compute(self, state, frame, nominal_command, *, sim_time_s):
        det, sample=super().compute(state,frame,nominal_command,sim_time_s=sim_time_s)
        self.last_det=det.copy()
        if self.baseline:
            self.last_saturated=False
            return det, sample
        applied, residual=apply_yaw_residual(det,np.array([self.action]),active=True)
        self.last_saturated=residual.total_saturated
        return applied, sample


def make_stack(ledger, baseline=False):
    robot=yaml.safe_load((REPO/"configs/robot/g1_locomotion_12dof.yaml").read_text())
    sim=RecordedSimulation(G1ModelConfig(name=robot["name"],xml_path=robot["model"]["xml_path"],
                                         **robot["simulation"]),seed=7,ledger=ledger)
    keys={f.name for f in dataclasses.fields(G1LocomotionConfig)}
    low=RecordedController(G1LocomotionConfig(**{k:v for k,v in robot["controller"].items() if k in keys}),device="cpu")
    policy=ResidualCorrection(baseline=baseline)
    sim.low,sim.policy=low,policy
    return robot,sim,low,policy


def metrics(sim,frame):
    state=sim.get_robot_state(); forward,lateral=frame.project(state.base_position)
    values={"forward_displacement_m":forward,"distance_error_m":abs(forward-4.),
            "lateral_drift_m":lateral,"heading_error_deg":frame.heading_error_deg(state),
            "simulation_time_s":sim.simulation_time}
    return {**values, **evaluate_walk_task(values,4.,physical=not state.fallen)}

class G1YawResidualEnv(gym.Env):
    metadata={"render_modes":[]}
    def __init__(self, ledger):
        self.train_decisions = 0
        self.decision_cap = None
        self.action_space=spaces.Box(-1.,1.,shape=(1,),dtype=np.float32)
        self.observation_space=spaces.Box(-1.,1.,shape=(18,),dtype=np.float32)
        self.ledger=ledger
        self.robot,self.sim,self.low,self.policy=make_stack(ledger)
        self.done=True
    def reset(self, *, seed=None, options=None):
        if seed not in (None,0,7) or options:
            raise ResidualContractError("only frozen seen nominal4m seed7 is authorized")
        super().reset(seed=seed)
        self.sim.reset(seed=7); self.low.reset()
        self.frame=MissionFrame.from_state(self.sim.get_robot_state())
        self.controller=CorrectingController(self.low,self.policy,self.sim,self.frame)
        self.sim.set_active_skill("walk_forward")
        self.policy.action=0.; self.previous=0.; self.saturated=False; self.done=False
        self.velocity=np.zeros(2); self.yaw_rate=0.
        self.ledger.event("reset",episode=self.sim.episode,controller_resets=self.low.resets,
                          simulator_resets=self.sim.resets,gym_requested_seed=seed,physical_seed=7,initial_qpos=self.sim._data.qpos.tolist())
        return self.observation()
    def potential(self):
        state=self.sim.get_robot_state(); f,l=self.frame.project(state.base_position)
        h=self.frame.heading_error_rad(state)
        return -((l/.35)**2+.5*(h/math.radians(15))**2+.25*((4.-f)/4.)**2)
    def observation(self):
        s=self.sim.get_robot_state(); f,l=self.frame.project(s.base_position); h=self.frame.heading_error_rad(s)
        det,_=PathCorrectionPolicy.compute(self.policy,s,self.frame,np.array([.5,0.,0.]),sim_time_s=s.simulation_time)
        g=self.low.get_gravity_orientation(np.asarray(s.base_orientation))
        raw=np.array([math.sin(h),math.cos(h),l/.35,f/4.,(4.-f)/4.,(24.-s.simulation_time)/24.,
                      * (self.velocity/.5),self.yaw_rate/.6,*g,
                      (s.base_position[2]-self.frame.initial_position[2])/.2,1.,det[2]/.6,
                      self.previous,float(self.saturated),float(s.standing)],dtype=np.float64)
        if not np.isfinite(raw).all(): raise ResidualContractError("nonfinite_observation")
        info={"raw_observation":raw.tolist(),"clipped":(np.abs(raw)>1).tolist(),"scales":SCALES,
              "case":"historical_seen_nominal4m","seed":7,"case_episode":self.sim.episode,
              "controller_resets":self.low.resets,"simulator_resets":self.sim.resets}
        return np.clip(raw,-1,1).astype(np.float32),info
    def step(self, action):
        if self.done: raise ResidualContractError("step_after_episode_boundary")
        a=np.asarray(action,dtype=np.float64)
        # Validate before any control/policy/physics; no normalized-action clipping.
        apply_yaw_residual(np.zeros(3),a,active=True)
        initial=self.sim.get_robot_state(); xy0=np.array(self.frame.project(initial.base_position))
        h0=self.frame.heading_error_rad(initial); phi0=self.potential(); prev=self.previous
        self.policy.action=float(a[0]); saturated=False
        reason=None; outcome=None
        for _ in range(50):
            sim=self.sim
            sim.step(self.controller.compute_torques(joint_positions=sim.joint_positions(),
                joint_velocities=sim.joint_velocities(),quaternion=sim.base_quaternion(),
                angular_velocity=sim.base_angular_velocity(),command=np.array([.5,0.,0.]),dt=sim.timestep))
            saturated |= self.policy.last_saturated
            f,_=self.frame.project(sim.get_robot_state().base_position)
            if f>=4. or sim.episode_steps>=12000:
                outcome=metrics(sim,self.frame)
                b=classify_boundary(target_reached=f>=4.,task_success=f>=4. and outcome["task_success"],
                                    task_horizon_exhausted=sim.episode_steps>=12000)
                reason=b.reason; break
        s=self.sim.get_robot_state(); duration=s.simulation_time-initial.simulation_time
        self.velocity=(np.array(self.frame.project(s.base_position))-xy0)/duration
        delta=math.atan2(math.sin(self.frame.heading_error_rad(s)-h0),math.cos(self.frame.heading_error_rad(s)-h0))
        self.yaw_rate=delta/duration
        self.previous=float(a[0]); self.saturated=bool(saturated)
        tilt=float(np.clip(max(0.,_tilt_deg(s.base_orientation)-15.)/15.,0.,2.))
        terms={"potential_shaping":.99*self.potential()-phi0,"action_cost":-.02*self.previous**2,
               "action_delta_cost":-.01*(self.previous-prev)**2,"tilt_cost":-.1*tilt**2,
               "saturation_cost":-.05*float(saturated),"terminal":0.}
        self.done=reason is not None
        if reason: terms["terminal"]=5. if reason=="task_success" else -5.
        reward=float(sum(terms.values()))
        if not math.isfinite(reward): raise ResidualContractError("nonfinite_reward")
        self.train_decisions += 1
        truncated = bool(not self.done and self.decision_cap is not None and self.train_decisions >= self.decision_cap)
        obs,info=self.observation(); info.update(reward_terms=terms,termination_reason=reason,outcome=outcome,
                                                 requested_action=a.tolist(),applied_action=self.previous)
        self.ledger.event("transition",observation=obs.tolist(),info=info,reward=reward,
                          terminated=self.done,truncated=truncated,native_completed=self.ledger.completed)
        terminated = self.done
        if truncated:
            self.done = True
            info["truncation_reason"] = "external_smoke_decision_budget"
        return obs,reward,terminated,truncated,info
    def close(self):
        self.sim.close()
