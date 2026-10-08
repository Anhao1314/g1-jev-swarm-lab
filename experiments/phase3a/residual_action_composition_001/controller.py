"""Experiment-local authority mask; observation and monitor retain original 2 s semantics.

The copied legacy adapter differs only in first-Walk authority duration and an
explicit trace field distinguishing the unchanged observation active feature.
No shared module constants, skill bodies, evaluator or training paths change.
"""
from __future__ import annotations
from contextlib import contextmanager
from threading import current_thread, main_thread
import math
import numpy as np
from g1swarm.transition_learning import env as legacy
from g1swarm.transition_learning.env import BOUNDS, WINDOW, PAIRS, QUANTUM_STEPS, Cancelled, tilt

ORIGINAL_CONTROLLER = legacy._Controller

class WindowController(ORIGINAL_CONTROLLER):

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
        observation_active = r.treatment == "learned" and eligible and elapsed < WINDOW-1e-9
        limit = r.authority_window_s if r.index == 1 and r.skill == "walk_forward" else WINDOW
        active = r.treatment == "learned" and eligible and elapsed < limit-1e-9
        if eligible and r.node_steps % QUANTUM_STEPS == 0:
            obs = r.observation(nominal, observation_active)
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
                     "eligible": eligible, "active": active, "observation_active": observation_active,
                     "nominal_command": nominal.tolist(),
                     "deterministic_command": corrected.tolist(), "applied_command": applied.tolist(),
                     "residual": (applied-corrected).tolist(), "action": r.action.tolist(),
                     "reset_count": r.resets, "height_m": state.base_position[2],
                     "tilt_deg": math.degrees(tilt(state))})
        kwargs["command"] = applied
        return r.base.compute_torques(**kwargs)

    def __getattr__(self, name):
        return getattr(self.runner.base, name)



@contextmanager
def isolated_controller():
    """Only the synchronous experiment process may substitute this adapter."""
    if current_thread() is not main_thread() or legacy._Controller is not ORIGINAL_CONTROLLER:
        raise RuntimeError("Controller substitution requires an unmodified synchronous main thread")
    legacy._Controller = WindowController
    try:
        yield
    finally:
        legacy._Controller = ORIGINAL_CONTROLLER
