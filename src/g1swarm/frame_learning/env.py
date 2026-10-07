"""Replace only correction heading; inherit original residual, reward and skills."""
from __future__ import annotations

from queue import Queue
from threading import Thread

import gymnasium as gym
import numpy as np

from ..heading_alignment.experiment import HeadingCorrectionPolicy, MODE_BY_ALPHA, validate_alpha
from ..reference_ablation.experiment import ReferenceRunner
from ..transition_learning.env import EpisodeRunner, TransitionEnv, OBS_SIZE


def frame_alpha(alpha):
    value = validate_alpha(alpha)
    if value not in (0.0, 0.5):
        raise ValueError("Only frozen alpha0/0.5 is allowed in this PPO experiment")
    return value


def arm_label(alpha, seed=None):
    alpha = frame_alpha(alpha)
    return f"alpha{alpha:g}-" + ("residual-off" if seed is None else f"learned-seed{seed}")


class FrameRunner(ReferenceRunner):
    def __init__(self, case, alpha, treatment="deterministic_correction", control=None,
                 trace_path=None, optimizing=False):
        self.alpha = frame_alpha(alpha)
        if treatment not in ("deterministic_correction", "learned"):
            raise ValueError("Frame experiment requires corrected or learned treatment")
        self.policy_decision_calls = 0
        self.policy_configured = control is not None
        def counted_control(obs, reward):
            self.policy_decision_calls += 1
            return control(obs, reward)
        EpisodeRunner.__init__(self, case, treatment, control=counted_control if control is not None else None,
                               trace_path=trace_path)
        self.optimizing = bool(optimizing)
        self.reference_mode = MODE_BY_ALPHA[self.alpha]
        self.correction = HeadingCorrectionPolicy(self, self.alpha, self.correction)

    def run(self):
        record = super().run()
        record.update(heading_alignment_alpha=self.alpha,
                      residual_enabled=self.treatment == "learned",
                      PPO_training=self.optimizing, learned_policy_configured=self.policy_configured,
                      policy_decision_calls=self.policy_decision_calls)
        return record


def replay_frame(case, alpha, policy=None, trace_path=None):
    control = (lambda obs, reward: policy(obs)) if policy is not None else None
    runner = FrameRunner(case, alpha, "learned" if policy is not None else "deterministic_correction",
                         control=control, trace_path=trace_path)
    try:
        return runner.run()
    finally:
        runner.close()


class FrameEnv(TransitionEnv):
    def __init__(self, cases, alpha, seed=0, log_path=None, decision_log_path=None):
        self.alpha = frame_alpha(alpha)
        super().__init__(cases, treatment="learned", seed=seed, log_path=log_path,
                         decision_log_path=decision_log_path)

    def reset(self, *, seed=None, options=None):
        # This is the original reset sequence with only the runner factory changed.
        # Do not call TransitionEnv.reset or globally replace its EpisodeRunner.
        gym.Env.reset(self, seed=seed)
        self.close()
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        case = options.get("case") if options and "case" in options else self.cases[int(self.rng.integers(len(self.cases)))]
        self.events, self.actions = Queue(), Queue()
        self.runner = FrameRunner(case, self.alpha, "learned", control=self._control, optimizing=True)
        self.thread = Thread(target=self._worker, daemon=True)
        self.done = False
        self.thread.start()
        event = self._event()
        self.pending_terminal = event if event[0] == "terminal" else None
        obs = np.zeros(OBS_SIZE, np.float32) if self.pending_terminal else event[1]
        self.current_observation = obs.copy()
        return obs, {"case_id": case["id"]}
