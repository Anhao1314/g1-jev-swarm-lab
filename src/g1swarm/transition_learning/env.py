"""Real MuJoCo transitions using the original frozen skill bodies.

A worker pauses only at command decisions; Gym actions never replace skill
termination, reset behavior, joint control or physics. Synchronous replay uses
the same runner without queues. References for the intended path are diagnostic
and observed by the residual; old walk envelopes retain their local start frame.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from queue import Queue
from threading import Event, Thread
import time

import gymnasium as gym
import numpy as np

from ..config import build_controller, build_simulation, load_yaml
from ..control.path_correction import CorrectionConfig, PathCorrectionPolicy
from ..boundary.envelope import evaluate_walk_task, physical_success
from ..segmentation.mission import MissionFrame
from ..skills import SkillContext, SkillRequest, SkillRouter, StandSkill, WalkForwardSkill, TurnSkill, StopSkill

SKILLS = ("stand", "walk_forward", "turn", "stop")
PAIRS = {("walk_forward", "turn"), ("turn", "walk_forward"),
         ("walk_forward", "stop"), ("stand", "walk_forward")}
BOUNDS = np.array([0.1, 0.06, 0.12], dtype=np.float64)
WINDOW = 2.0
QUANTUM_STEPS = 50
OBS_SIZE = 61
TREATMENTS = {"frozen_baseline", "deterministic_correction", "learned"}


def wrap(x):
    return math.atan2(math.sin(x), math.cos(x))


def yaw(state):
    w, x, y, z = state.base_orientation
    return math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))


def tilt(state):
    w, x, y, z = state.base_orientation
    n = w*w+x*x+y*y+z*z
    return math.acos(np.clip(1-2*(x*x+y*y)/n, -1, 1))


class Cancelled(Exception):
    pass


class _Controller:
    def __init__(self, runner):
        self.runner = runner

    def reset(self):
        self.runner.base.reset()
        self.runner.resets += 1

    def compute_torques(self, **kwargs):
        r = self.runner
        if r.abort.is_set():
            raise Cancelled()
        nominal = np.array(kwargs["command"], copy=True)
        r.last_nominal_command = nominal.copy()
        corrected = nominal.copy()
        state = r.sim.get_robot_state()
        if r.treatment != "frozen_baseline" and r.skill == "walk_forward":
            corrected, _ = r.correction.compute(state, r.frame, nominal,
                                                sim_time_s=state.simulation_time)
        eligible = r.index > 0 and (r.previous, r.skill) in PAIRS
        elapsed = state.simulation_time-r.node_start.simulation_time
        active = r.treatment == "learned" and eligible and elapsed < WINDOW-1e-9
        if eligible and r.node_steps % QUANTUM_STEPS == 0:
            obs = r.observation(nominal, active)
            if r.control is not None:
                action = np.asarray(r.control(obs, r.dense_reward()), dtype=np.float64)
            else:
                action = np.zeros(3)
            if action.shape != (3,) or not np.isfinite(action).all():
                raise ValueError("Residual action must be finite shape(3,)")
            r.action = np.clip(action, -1, 1) if active else np.zeros(3)
        if not active:
            r.action = np.zeros(3)
        applied = corrected + r.action*BOUNDS
        # Frozen yaw corridor remains the total command bound; other components
        # are bounded by the original nominal command plus the residual box.
        applied[2] = np.clip(applied[2], -0.6, 0.6)
        if r.treatment == "frozen_baseline":
            applied = nominal  # exact historical bypass
        if r.node_steps % QUANTUM_STEPS == 0:
            r.trace({"node_index": r.index, "skill": r.skill, "previous_skill": r.previous,
                     "elapsed_s": elapsed, "time_s": state.simulation_time,
                     "eligible": eligible, "active": active, "nominal_command": nominal.tolist(),
                     "deterministic_command": corrected.tolist(), "applied_command": applied.tolist(),
                     "residual": (applied-corrected).tolist(), "action": r.action.tolist(),
                     "reset_count": r.resets, "height_m": state.base_position[2],
                     "tilt_deg": math.degrees(tilt(state))})
        kwargs["command"] = applied
        return r.base.compute_torques(**kwargs)

    def __getattr__(self, name):
        return getattr(self.runner.base, name)


class _Monitor:
    def __init__(self, runner):
        self.r = runner

    def step(self, control=None):
        r = self.r
        state = r.sim.step(control)
        r.node_steps += 1
        r.max_tilt = max(r.max_tilt, math.degrees(tilt(state)))
        r.min_height = min(r.min_height, state.base_position[2])
        elapsed = state.simulation_time-r.node_start.simulation_time
        if elapsed <= WINDOW+1e-9:
            r.transition_speeds.append(state.speed())
            r.transition_max_tilt = max(r.transition_max_tilt, math.degrees(tilt(state)))
            r.transition_min_height = min(r.transition_min_height, state.base_position[2])
            r.transition_end = state
            r.transition_angular_speeds.append(float(np.linalg.norm(state.angular_velocity)))
            r.transition_standing.append(float(state.standing))
            h = yaw(state)
            vx, vy, _ = state.linear_velocity
            body_v = np.array([math.cos(h)*vx+math.sin(h)*vy, -math.sin(h)*vx+math.cos(h)*vy])
            tracking = (state.standing and np.linalg.norm(body_v-r.last_nominal_command[:2]) <= .15
                        and abs(state.angular_velocity[2]-r.last_nominal_command[2]) <= .15)
            r.recovery_run_s = r.recovery_run_s+r.sim.timestep if tracking else 0.0
            if r.recovery_time_s is None and r.recovery_run_s >= .2-1e-9:
                r.recovery_time_s = elapsed-r.recovery_run_s
        return state

    def __getattr__(self, name):
        return getattr(self.r.sim, name)


class EpisodeRunner:
    def __init__(self, case, treatment, control=None, trace_path=None):
        if treatment not in TREATMENTS:
            raise ValueError(f"Unknown treatment {treatment}")
        self.case, self.treatment, self.control = case, treatment, control
        self.robot = load_yaml("configs/robot/g1_locomotion_12dof.yaml")
        self.sim = build_simulation(self.robot, seed=0)
        self.base = build_controller(self.robot)
        self.sim.set_base_state(yaw_rad=math.radians(case.get("initial_yaw_deg", 0.0)))
        self.correction = PathCorrectionPolicy(CorrectionConfig(
            mode="heading_lateral", k_heading=1.5, k_lateral=1.0,
            max_yaw_rate_radps=0.6, deadband_radps=0.01,
            oscillation_threshold_radps=0.05))
        self.router = SkillRouter([StandSkill(), WalkForwardSkill(), TurnSkill(), StopSkill()])
        self.abort = Event()
        self.index, self.resets, self.node_steps = 0, 0, 0
        self.skill, self.previous = "stand", None
        self.action = np.zeros(3)
        self.last_reward_action = np.zeros(3)
        self.nodes = []
        initial = self.sim.get_robot_state()
        self.planned_heading = yaw(initial)
        self.planned_origin = np.array(initial.base_position[:2])
        self.trace_path = Path(trace_path) if trace_path else None
        if self.trace_path:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.trace_file = self.trace_path.open("x", encoding="utf-8")
        else:
            self.trace_file = None
        self.trace_count = 0
        self.record = None

    def trace(self, row):
        self.trace_count += 1
        self.last_command_trace = row
        if self.trace_file:
            self.trace_file.write(json.dumps(row, allow_nan=False)+"\n")

    def observation(self, nominal, active):
        s = self.sim.get_robot_state()
        forward, lateral = self.frame.project(s.base_position)
        local_heading = math.radians(self.frame.heading_error_deg(s))
        target_d = float(self.parameters.get("target_distance_m", 0))
        target_a = math.radians(float(self.parameters.get("target_angle_deg", 0)))
        elapsed = s.simulation_time-self.node_start.simulation_time
        phase = self.base._counter*self.sim.timestep/self.base.config.phase_period_s*2*math.pi
        world_v = np.array(s.linear_velocity)
        h = yaw(s)
        body_v = [math.cos(h)*world_v[0]+math.sin(h)*world_v[1],
                  -math.sin(h)*world_v[0]+math.cos(h)*world_v[1], world_v[2]]
        offset = np.array(s.base_position[:2])-self.planned_origin
        planned_lat = -math.sin(self.planned_heading)*offset[0]+math.cos(self.planned_heading)*offset[1]
        planned_h = wrap(h-self.planned_heading)
        features = ([float(self.skill == name) for name in SKILLS]
                    +[float(self.previous == name) for name in SKILLS]
                    +list(nominal)+body_v+list(s.angular_velocity)
                    +list(self.base.get_gravity_orientation(np.array(s.base_orientation)))
                    +[s.base_position[2], forward/4, lateral/.35,
                      math.sin(local_heading), math.cos(local_heading), (target_d-forward)/4,
                      wrap(target_a-local_heading)/math.pi, elapsed/4, float(active),
                      math.sin(phase), math.cos(phase)]
                    +list(self.action)+[planned_lat/2, math.sin(planned_h), math.cos(planned_h)]
                    +list((self.sim.joint_positions()-np.array(self.base.default_angles))/.5)
                    +list(self.sim.joint_velocities()*.05))
        obs = np.clip(np.asarray(features, dtype=np.float32), -20, 20)
        if obs.shape != (OBS_SIZE,) or not np.isfinite(obs).all():
            raise ValueError(f"Invalid observation {obs.shape}")
        return obs

    def dense_reward(self):
        if self.node_steps == 0:
            return 0.0
        s = self.sim.get_robot_state()
        _, lat = self.frame.project(s.base_position)
        heading = math.radians(self.frame.heading_error_deg(s))
        cost = .1*tilt(s)**2
        if self.skill == "walk_forward":
            cost += 4*heading**2+4*lat**2
        elif self.skill == "turn":
            remaining = wrap(math.radians(self.parameters["target_angle_deg"])-heading)
            cost += 2*remaining**2
        elif self.skill == "stop":
            cost += 2*s.speed()**2
        cost += .05*float(self.action@self.action)
        cost += .02*float(np.sum((self.action-self.last_reward_action)**2))
        self.last_reward_action = self.action.copy()
        return -float(cost)

    def _node_record(self, result):
        s = self.sim.get_robot_state()
        elapsed = s.simulation_time-self.node_start.simulation_time
        forward, lateral = self.frame.project(s.base_position)
        heading = self.frame.heading_error_deg(s)
        if self.skill == "turn":
            heading = float(result.metrics["heading_error_deg"])
        physical = physical_success(fallen=s.fallen or bool(result.metrics.get("fallen")),
                                    finite=s.is_finite(), skill_status=result.status.value,
                                    simulation_completed=True)
        violations = []
        strict = result.status.value == "SUCCESS" and physical
        task = strict
        envelope = None
        if self.skill == "walk_forward":
            d = self.parameters["target_distance_m"]
            envelope = evaluate_walk_task({"absolute_distance_error_m": abs(forward-d),
                "lateral_drift_m": lateral, "heading_error_deg": heading,
                "completion_sim_time_s": elapsed}, d, physical=physical)
            task = task and envelope["task_success"]
            strict = strict and envelope["strict_success"]
            violations = envelope["task_violations"]
        transition_state = self.transition_end
        _, transition_lat = self.frame.project(transition_state.base_position)
        transition_h = self.frame.heading_error_deg(transition_state)
        offset = np.array(s.base_position[:2])-self.planned_origin
        ideal_lat = -math.sin(self.planned_heading)*offset[0]+math.cos(self.planned_heading)*offset[1]
        ideal_target_heading = self.planned_heading
        if self.skill == "turn":
            ideal_target_heading += math.radians(self.parameters["target_angle_deg"])
        ideal_heading_error = math.degrees(wrap(yaw(s)-ideal_target_heading))
        return {"skill": self.skill, "parameters": self.parameters,
                "status": result.status.value, "reason": result.reason,
                "physical_success": physical, "task_success": bool(task), "strict_success": bool(strict),
                "violations": violations, "lateral_drift_m": float(lateral),
                "heading_error_deg": float(heading), "forward_progress_m": float(forward),
                "duration_s": elapsed, "fallen": bool(s.fallen or result.metrics.get("fallen")),
                "max_tilt_deg": self.max_tilt, "min_height_m": self.min_height,
                "simulation_steps": self.node_steps, "memory_reset_count": self.resets-self.node_resets_start,
                "skill_metrics": result.metrics, "envelope": envelope,
                "start_state": self.node_start.to_dict(), "end_state": s.to_dict(),
                "ideal_path_lateral_error_m": float(ideal_lat),
                "ideal_path_heading_error_deg": float(ideal_heading_error),
                "transition_metrics": {"eligible": self.index > 0 and (self.previous,self.skill) in PAIRS,
                    "duration_s": min(WINDOW, elapsed), "observation_window_s": min(WINDOW, elapsed), "completion_duration_s": elapsed,
                    "lateral_change_m": float(transition_lat), "heading_change_deg": float(transition_h),
                    "max_tilt_deg": self.transition_max_tilt, "min_height_m": self.transition_min_height,
                    "speed_rms_mps": float(np.sqrt(np.mean(np.square(self.transition_speeds)))) if self.transition_speeds else 0.0,
                    "final_speed_mps": transition_state.speed(), "next_skill_final_speed_mps": s.speed(),
                    "angular_speed_rms_radps": float(np.sqrt(np.mean(np.square(self.transition_angular_speeds)))) if self.transition_angular_speeds else 0.0,
                    "standing_fraction": float(np.mean(self.transition_standing)) if self.transition_standing else 0.0,
                    "sustained_tracking_recovery_s": self.recovery_time_s}}

    def run(self):
        started = time.perf_counter()
        for index, node in enumerate(self.case["nodes"]):
            self.index = index
            self.previous = self.nodes[-1]["skill"] if self.nodes else None
            self.skill = node["skill"]
            self.parameters = dict(node["parameters"])
            self.node_start = self.sim.get_robot_state()
            self.frame = MissionFrame.from_state(self.node_start)
            self.node_steps = 0
            self.node_resets_start = self.resets
            self.action = np.zeros(3)
            self.last_reward_action = np.zeros(3)
            self.max_tilt = self.transition_max_tilt = math.degrees(tilt(self.node_start))
            self.min_height = self.transition_min_height = self.node_start.base_position[2]
            self.transition_speeds = []
            self.transition_angular_speeds = []
            self.transition_standing = []
            self.recovery_run_s = 0.0
            self.recovery_time_s = None
            self.transition_end = self.node_start
            context = SkillContext(simulation=_Monitor(self), controller=_Controller(self),
                                   robot_config=self.robot, max_steps=600000, seed=0)
            result = self.router.execute(SkillRequest(self.skill, self.parameters), context)
            self.nodes.append(self._node_record(result))
            if self.skill == "walk_forward":
                self.planned_origin += self.parameters["target_distance_m"]*np.array([
                    math.cos(self.planned_heading), math.sin(self.planned_heading)])
            elif self.skill == "turn":
                self.planned_heading = wrap(self.planned_heading+math.radians(self.parameters["target_angle_deg"]))
            if not self.nodes[-1]["physical_success"] or result.status.value != "SUCCESS":
                break
        failures = []
        for node in self.nodes:
            if not node["physical_success"]:
                failures.append("FALL_OR_INSTABILITY" if node["fallen"] else node["status"])
            elif not node["task_success"]:
                failures.extend(node["violations"] or [node["status"]])
        complete = len(self.nodes) == len(self.case["nodes"])
        if not complete:
            failures.append("SEQUENCE_INTERRUPTED")
        self.record = {"case_id": self.case["id"], "group": self.case["group"],
            "transition": self.case.get("transition", "none"), "treatment": self.treatment,
            "task_success": complete and all(n["task_success"] for n in self.nodes),
            "physical_success": complete and all(n["physical_success"] for n in self.nodes),
            "nodes": self.nodes, "total_sim_time_s": self.sim.simulation_time,
            "wall_time_s": time.perf_counter()-started, "failure_taxonomy": sorted(set(failures)) or ["SUCCESS"],
            "memory_reset_count": self.resets, "trace_samples": self.trace_count,
            "final_state": self.sim.get_robot_state().to_dict()}
        return self.record

    def terminal_reward(self):
        r = self.record
        penalty = sum(abs(math.radians(n["heading_error_deg"]))+
                      (abs(n["lateral_drift_m"]) if n["skill"] == "walk_forward" else 0)
                      for n in r["nodes"])
        return (15 if r["task_success"] else -15)-(0 if r["physical_success"] else 50)-10*penalty

    def close(self):
        if self.trace_file:
            self.trace_file.close()
        self.sim.close()


def replay_case(case, treatment, policy=None, trace_path=None):
    control = (lambda obs, reward: policy(obs)) if policy is not None else None
    runner = EpisodeRunner(case, treatment, control=control, trace_path=trace_path)
    try:
        return runner.run()
    finally:
        runner.close()


class TransitionEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, cases, treatment="learned", seed=0, log_path=None, decision_log_path=None):
        super().__init__()
        if not cases:
            raise ValueError("At least one training case is required")
        self.cases, self.treatment = cases, treatment
        self.action_space = gym.spaces.Box(-1, 1, shape=(3,), dtype=np.float32)
        self.observation_space = gym.spaces.Box(-20, 20, shape=(OBS_SIZE,), dtype=np.float32)
        self.rng = np.random.default_rng(seed)
        self.log_path = Path(log_path) if log_path else None
        self.decision_log_path = Path(decision_log_path) if decision_log_path else None
        self.decision_count = 0
        self.runner = self.thread = None
        self.last_record = None
        self.done = True
        self.pending_terminal = None

    def _control(self, obs, reward):
        self.events.put(("decision", obs, reward))
        action = self.actions.get()
        if action is None:
            raise Cancelled()
        return action

    def _worker(self):
        try:
            record = self.runner.run()
            self.events.put(("terminal", record, self.runner.dense_reward()+self.runner.terminal_reward()))
        except Cancelled:
            pass
        except BaseException as exc:
            self.events.put(("error", exc, 0))
        finally:
            self.runner.close()

    def _event(self):
        event = self.events.get(timeout=120)
        if event[0] == "error":
            raise RuntimeError("Real MuJoCo episode failed") from event[1]
        return event

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.close()
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        case = options.get("case") if options and "case" in options else self.cases[int(self.rng.integers(len(self.cases)))]
        self.events, self.actions = Queue(), Queue()
        self.runner = EpisodeRunner(case, self.treatment, control=self._control)
        self.thread = Thread(target=self._worker, daemon=True)
        self.done = False
        self.thread.start()
        event = self._event()
        self.pending_terminal = event if event[0] == "terminal" else None
        obs = np.zeros(OBS_SIZE, np.float32) if self.pending_terminal else event[1]
        self.current_observation = obs.copy()
        return obs, {"case_id": case["id"]}

    def step(self, action):
        if self.done:
            raise RuntimeError("reset required after terminated episode")
        action = np.asarray(action, dtype=np.float64)
        if action.shape != (3,) or not np.isfinite(action).all():
            raise ValueError("Invalid residual action")
        if self.pending_terminal:
            event, self.pending_terminal = self.pending_terminal, None
        else:
            self.actions.put(action)
            event = self._event()
        self.decision_count += 1
        if self.decision_log_path:
            self.decision_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.decision_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"decision_index": self.decision_count,
                    "case_id": self.runner.case["id"], "observation": self.current_observation.tolist(),
                    "requested_action": action.tolist(), "reward": float(event[2]),
                    "terminal": event[0] == "terminal",
                    "last_command": getattr(self.runner, "last_command_trace", None)}, allow_nan=False)+"\n")
        self.current_observation = np.zeros(OBS_SIZE, np.float32) if event[0] == "terminal" else event[1].copy()
        if event[0] == "terminal":
            self.done, self.last_record = True, event[1]
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(self.last_record, allow_nan=False)+"\n")
            return np.zeros(OBS_SIZE, np.float32), float(event[2]), True, False, {"episode_record": self.last_record}
        return event[1], float(event[2]), False, False, {}

    def close(self):
        if self.thread is not None and self.thread.is_alive():
            self.runner.abort.set()
            self.actions.put(None)
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                raise RuntimeError("MuJoCo worker failed to stop")
        self.thread = None

    def snapshot(self):
        """Retain the last budget-interrupted episode, without scoring it."""
        if self.runner is None or self.done:
            return None
        return {"status": "BUDGET_INTERRUPTED_NOT_SCORED", "case_id": self.runner.case["id"],
                "current_node_index": self.runner.index, "current_skill": self.runner.skill,
                "completed_nodes": self.runner.nodes,
                "state": self.runner.sim.get_robot_state().to_dict(),
                "memory_reset_count": self.runner.resets,
                "last_command": getattr(self.runner, "last_command_trace", None)}
