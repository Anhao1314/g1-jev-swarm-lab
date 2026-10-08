"""Outer-loop path correction at the policy-command layer (Phase 1.3).

The correction layer only modifies the high-level ``(vx, vy, yaw_rate)`` command
that the existing Unitree policy consumes. No joint torque, PD gain, action
scale, model or policy weight is touched.

Error definitions (mission frame, fixed at mission start):

* ``e_heading`` - signed heading error of the robot relative to the mission
  forward axis, wrapped to [-pi, pi]; positive means the robot is turned to the
  left of the mission axis, so the correction turns right.
* ``e_lateral`` - signed lateral displacement relative to the mission
  centreline (positive = left of the mission axis), so the same sign convention
  applies.

Correction modes: ``none``, ``heading_only``, ``heading_lateral``.

Reference note: the idea of an outer heading/lateral feedback loop was informed
by the author's earlier Go2W navigation project
(``Anhao1314/Go2w-Mora-navigation``, ``rl/low_level_controller.py``). Go2W is a
wheeled platform; no wheel-control logic was copied - only the error-definition
and ablation idea, re-derived for a velocity-conditioned humanoid policy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing the segmentation package at runtime
    from ..segmentation.mission import MissionFrame

MODES = ("none", "heading_only", "heading_lateral")


@dataclass(frozen=True)
class CorrectionConfig:
    mode: str = "none"
    k_heading: float = 0.0
    k_lateral: float = 0.0
    max_yaw_rate_radps: float = 0.6
    deadband_radps: float = 0.01
    oscillation_threshold_radps: float = 0.05

    def validate(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")
        if self.k_heading < 0.0 or self.k_lateral < 0.0:
            raise ValueError("gains must be non-negative")
        if self.max_yaw_rate_radps <= 0.0:
            raise ValueError("max_yaw_rate_radps must be positive")
        if not 0.0 <= self.deadband_radps <= self.max_yaw_rate_radps:
            raise ValueError("deadband must lie inside the command range")
        if self.mode == "heading_only" and self.k_heading == 0.0:
            raise ValueError("heading_only requires a positive k_heading")
        if self.mode == "heading_lateral" and (self.k_heading == 0.0 or self.k_lateral == 0.0):
            raise ValueError("heading_lateral requires positive k_heading and k_lateral")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "k_heading": self.k_heading,
            "k_lateral": self.k_lateral,
            "max_yaw_rate_radps": self.max_yaw_rate_radps,
            "deadband_radps": self.deadband_radps,
            "oscillation_threshold_radps": self.oscillation_threshold_radps,
        }


@dataclass(frozen=True)
class CorrectionSample:
    sim_time_s: float
    heading_error_rad: float
    lateral_error_m: float
    yaw_raw: float
    yaw_clipped: float
    saturated: bool
    vx_command: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sim_time_s": self.sim_time_s,
            "heading_error_rad": self.heading_error_rad,
            "lateral_error_m": self.lateral_error_m,
            "yaw_raw": self.yaw_raw,
            "yaw_clipped": self.yaw_clipped,
            "saturated": self.saturated,
            "vx_command": self.vx_command,
        }


class PathCorrectionPolicy:
    """Deterministic, replaceable outer-loop correction policy."""

    def __init__(self, config: CorrectionConfig) -> None:
        config.validate()
        self.config = config

    def compute(
        self,
        state,
        frame: MissionFrame,
        nominal_command: np.ndarray,
        *,
        sim_time_s: float,
    ) -> tuple[np.ndarray, CorrectionSample]:
        e_heading = frame.heading_error_rad(state)
        e_lateral = frame.project(state.base_position)[1]
        yaw_raw = 0.0
        if self.config.mode == "heading_only":
            yaw_raw = -self.config.k_heading * e_heading
        elif self.config.mode == "heading_lateral":
            yaw_raw = (
                -self.config.k_heading * e_heading - self.config.k_lateral * e_lateral
            )
        if abs(yaw_raw) < self.config.deadband_radps:
            yaw_raw = 0.0
        limit = self.config.max_yaw_rate_radps
        yaw_clipped = float(np.clip(yaw_raw, -limit, limit))
        saturated = abs(yaw_raw) > limit + 1e-12
        corrected = np.array(nominal_command, dtype=np.float64, copy=True)
        corrected[2] = yaw_clipped
        sample = CorrectionSample(
            sim_time_s=float(sim_time_s),
            heading_error_rad=float(e_heading),
            lateral_error_m=float(e_lateral),
            yaw_raw=float(yaw_raw),
            yaw_clipped=yaw_clipped,
            saturated=saturated,
            vx_command=float(corrected[0]),
        )
        return corrected, sample


class CorrectionTracker:
    """Accumulate correction statistics (RMS, max, saturation, oscillation)."""

    def __init__(self, *, oscillation_threshold_radps: float = 0.05) -> None:
        self._oscillation_threshold = float(oscillation_threshold_radps)
        self.samples = 0
        self._sum_squares = 0.0
        self.max_abs = 0.0
        self.saturation_count = 0
        self.oscillation_count = 0
        self._last_significant_sign = 0
        self.first_saturation_time_s: float | None = None

    def add(self, sample: CorrectionSample) -> None:
        self.samples += 1
        self._sum_squares += sample.yaw_clipped * sample.yaw_clipped
        self.max_abs = max(self.max_abs, abs(sample.yaw_clipped))
        if sample.saturated:
            self.saturation_count += 1
            if self.first_saturation_time_s is None:
                self.first_saturation_time_s = sample.sim_time_s
        if abs(sample.yaw_clipped) >= self._oscillation_threshold:
            sign = 1 if sample.yaw_clipped > 0.0 else -1
            if self._last_significant_sign != 0 and sign != self._last_significant_sign:
                self.oscillation_count += 1
            self._last_significant_sign = sign

    def summary(self) -> dict[str, Any]:
        rms = math.sqrt(self._sum_squares / self.samples) if self.samples else 0.0
        return {
            "correction_rms": rms,
            "correction_max_abs": self.max_abs,
            "saturation_count": self.saturation_count,
            "saturation_fraction": (self.saturation_count / self.samples) if self.samples else 0.0,
            "control_oscillation_count": self.oscillation_count,
            "correction_samples": self.samples,
            "first_saturation_time_s": self.first_saturation_time_s,
        }


class CorrectingController:
    """Wrap the locomotion controller; correct only the high-level command."""

    def __init__(
        self,
        controller,
        policy: PathCorrectionPolicy,
        simulation,
        frame: MissionFrame,
        *,
        tracker: CorrectionTracker | None = None,
        on_sample: Callable[[CorrectionSample], None] | None = None,
        sample_period_s: float = 0.1,
    ) -> None:
        self._controller = controller
        self._policy = policy
        self._simulation = simulation
        self._frame = frame
        self.tracker = tracker or CorrectionTracker(
            oscillation_threshold_radps=policy.config.oscillation_threshold_radps
        )
        self._on_sample = on_sample
        self._sample_period_s = float(sample_period_s)
        self._last_callback_time = -math.inf

    def compute_torques(self, *, joint_positions, joint_velocities, quaternion, angular_velocity, command, dt):
        state = self._simulation.get_robot_state()
        corrected, sample = self._policy.compute(
            state, self._frame, command, sim_time_s=state.simulation_time
        )
        self.tracker.add(sample)
        if self._on_sample is not None and (
            state.simulation_time - self._last_callback_time >= self._sample_period_s
        ):
            self._last_callback_time = state.simulation_time
            self._on_sample(sample)
        return self._controller.compute_torques(
            joint_positions=joint_positions,
            joint_velocities=joint_velocities,
            quaternion=quaternion,
            angular_velocity=angular_velocity,
            command=corrected,
            dt=dt,
        )

    def reset(self) -> None:
        self._controller.reset()

    def __getattr__(self, name: str):
        return getattr(self._controller, name)
