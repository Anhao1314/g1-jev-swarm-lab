"""Phase 1 skills for the Unitree G1.

* ``StandSkill`` - deterministic PD hold of the configured default stance.
* ``StopSkill`` - zero-velocity command through the official controller.
* ``WalkForwardSkill`` - forward velocity command through the official
  pretrained Unitree locomotion policy (real actuator input, no teleporting).
* ``TurnSkill`` - yaw-rate command through the same official policy.

Every result is derived from measured simulation state: a skill reports
``FAILURE``/``TIMEOUT``/``UNSAFE`` instead of pretending success.
"""

from __future__ import annotations

from collections import deque

import math
import time

import numpy as np

from ..state.robot_state import RobotState
from .contract import Skill, SkillContext, SkillResult, SkillStatus

WALK_TOLERANCE_M = 0.2


def _tilt_deg(quaternion: np.ndarray | tuple[float, ...]) -> float:
    w, x, y, z = (float(value) for value in quaternion)
    norm = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    up_z = 1.0 - 2.0 * (x * x + y * y)
    return math.degrees(math.acos(max(-1.0, min(1.0, up_z))))


def _yaw_rad(quaternion: np.ndarray | tuple[float, ...]) -> float:
    w, x, y, z = (float(value) for value in quaternion)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def _horizontal_offset(start: RobotState, end: RobotState) -> np.ndarray:
    return np.array(end.base_position[:2], dtype=np.float64) - np.array(
        start.base_position[:2], dtype=np.float64
    )


def _pd_torques(context: SkillContext, target: np.ndarray) -> np.ndarray:
    return (target - context.simulation.joint_positions()) * context.kp() - (
        context.simulation.joint_velocities() * context.kd()
    )


def _policy_torques(context: SkillContext, command: np.ndarray) -> np.ndarray:
    controller = context.controller
    return controller.compute_torques(
        joint_positions=context.simulation.joint_positions(),
        joint_velocities=context.simulation.joint_velocities(),
        quaternion=context.simulation.base_quaternion(),
        angular_velocity=context.simulation.base_angular_velocity(),
        command=command,
        dt=context.simulation.timestep,
    )


class StandSkill(Skill):
    """Hold the configured default stance with the official PD gains."""

    name = "stand"

    def run(self, context: SkillContext) -> SkillResult:
        target = context.default_angles()
        if target.size != context.simulation.num_actuators:
            return self.result(
                SkillStatus.PRECONDITION_FAILED,
                reason="default_angles do not match the model actuator count",
            )
        duration_s = float(context.parameters.get("duration_s", 2.0))
        steps_limit = min(int(round(duration_s / context.simulation.timestep)), context.max_steps)
        context.simulation.set_active_skill(self.name)
        # The official deployment stands via the learned controller with a zero
        # velocity command; the deterministic PD hold is only a fallback for
        # runtimes without the policy. Measured evidence decides the status.
        use_controller = context.controller is not None
        if use_controller:
            context.controller.reset()
        zero_command = np.zeros(3, dtype=np.float64)
        started = time.perf_counter()
        start_state = context.state()
        heights: list[float] = []
        tilts: list[float] = []
        speeds: list[float] = []
        fallen = False
        steps = 0
        for _ in range(max(1, steps_limit)):
            if use_controller:
                torques = _policy_torques(context, zero_command)
            else:
                torques = _pd_torques(context, target)
            state = context.simulation.step(torques)
            steps += 1
            heights.append(state.base_position[2])
            tilts.append(_tilt_deg(state.base_orientation))
            speeds.append(state.speed())
            if state.fallen:
                fallen = True
                break
        final_state = context.state()
        metrics = {
            "duration_s": duration_s,
            "requested_steps": steps_limit,
            "final_height_m": final_state.base_position[2],
            "min_height_m": min(heights) if heights else final_state.base_position[2],
            "max_tilt_deg": max(tilts) if tilts else _tilt_deg(final_state.base_orientation),
            "final_speed_mps": final_state.speed(),
            "base_drift_m": float(np.linalg.norm(_horizontal_offset(start_state, final_state))),
            "fallen": fallen,
            "controller": "official_pretrained_policy" if use_controller else "pd_hold",
        }
        status = SkillStatus.SUCCESS if (not fallen and final_state.standing) else SkillStatus.FAILURE
        reason = None if status is SkillStatus.SUCCESS else "robot did not remain standing"
        return self.result(
            status,
            reason=reason,
            metrics=metrics,
            steps=steps,
            duration_s=time.perf_counter() - started,
        )


class StopSkill(Skill):
    """Command zero velocity with the official controller until the base is slow."""

    name = "stop"

    def available(self, context: SkillContext) -> bool:
        return context.controller is not None

    def unavailable_reason(self, context: SkillContext) -> str | None:
        return "official locomotion controller is not loaded"

    def run(self, context: SkillContext) -> SkillResult:
        max_duration_s = float(context.parameters.get("max_duration_s", 4.0))
        window_s = float(context.parameters.get("window_s", 1.0))
        speed_threshold = float(context.parameters.get("speed_threshold_mps", 0.05))
        max_steps = min(int(round(max_duration_s / context.simulation.timestep)), context.max_steps)
        window_steps = max(1, int(round(window_s / context.simulation.timestep)))
        recent_speeds: deque[float] = deque(maxlen=window_steps)
        command = np.zeros(3, dtype=np.float64)
        context.simulation.set_active_skill(self.name)
        started = time.perf_counter()
        fallen = False
        steps = 0
        status = SkillStatus.TIMEOUT
        final_speed = context.state().speed()
        for _ in range(max_steps):
            state = context.simulation.step(_policy_torques(context, command))
            steps += 1
            final_speed = state.speed()
            if state.fallen:
                fallen = True
                status = SkillStatus.UNSAFE
                break
            recent_speeds.append(final_speed)
            window_mean = sum(recent_speeds) / len(recent_speeds)
            if len(recent_speeds) >= window_steps and window_mean <= speed_threshold:
                status = SkillStatus.SUCCESS
                break
        metrics = {
            "final_speed_mps": final_speed,
            "final_window_mean_speed_mps": (
                sum(recent_speeds) / len(recent_speeds) if recent_speeds else final_speed
            ),
            "speed_threshold_mps": speed_threshold,
            "window_s": window_s,
            "fallen": fallen,
        }
        reason = None if status is SkillStatus.SUCCESS else "robot did not reach the stop threshold"
        return self.result(
            status,
            reason=reason,
            metrics=metrics,
            steps=steps,
            duration_s=time.perf_counter() - started,
        )


class WalkForwardSkill(Skill):
    """Forward locomotion through the official pretrained G1 policy.

    The skill only issues velocity commands; displacement is produced by real
    actuator torques. Directly editing the root pose is deliberately not
    possible through this interface.
    """

    name = "walk_forward"

    def available(self, context: SkillContext) -> bool:
        return context.controller is not None

    def unavailable_reason(self, context: SkillContext) -> str | None:
        return "official locomotion controller is not loaded"

    def check_preconditions(self, context: SkillContext) -> str | None:
        if not context.state().standing:
            return "walk requires a standing robot; run stand first"
        return None

    def run(self, context: SkillContext) -> SkillResult:
        target_distance_m = float(context.parameters.get("target_distance_m", 2.0))
        speed_mps = float(context.parameters.get("speed_mps", 0.5))
        max_duration_s = float(context.parameters.get("max_duration_s", 15.0))
        tolerance_m = float(context.parameters.get("tolerance_m", WALK_TOLERANCE_M))
        stop_at_distance_m = float(
            context.parameters.get("stop_at_distance_m", target_distance_m)
        )
        if target_distance_m <= 0.0:
            return self.result(
                SkillStatus.PRECONDITION_FAILED, reason="target_distance_m must be positive"
            )
        max_steps = min(int(round(max_duration_s / context.simulation.timestep)), context.max_steps)
        command = np.array([speed_mps, 0.0, 0.0], dtype=np.float64)
        context.simulation.set_active_skill(self.name)
        context.controller.reset()
        started = time.perf_counter()
        start_state = context.state()
        yaw0 = _yaw_rad(start_state.base_orientation)
        forward = np.array([math.cos(yaw0), math.sin(yaw0)], dtype=np.float64)
        status = SkillStatus.TIMEOUT
        fallen = False
        steps = 0
        progress = 0.0
        lateral = 0.0
        for _ in range(max_steps):
            state = context.simulation.step(_policy_torques(context, command))
            steps += 1
            offset = _horizontal_offset(start_state, state)
            progress = float(offset @ forward)
            lateral = float(forward[0] * offset[1] - forward[1] * offset[0])
            if state.fallen:
                fallen = True
                status = SkillStatus.UNSAFE
                break
            if progress >= stop_at_distance_m:
                status = (
                    SkillStatus.SUCCESS
                    if progress >= target_distance_m - tolerance_m
                    else SkillStatus.FAILURE
                )
                break
        final_state = context.state()
        yaw_final = _yaw_rad(final_state.base_orientation)
        metrics = {
            "target_distance_m": target_distance_m,
            "tolerance_m": tolerance_m,
            "stop_at_distance_m": stop_at_distance_m,
            "forward_displacement_m": progress,
            "lateral_drift_m": lateral,
            "heading_error_deg": math.degrees(_wrap_angle(yaw_final - yaw0)),
            "elapsed_sim_time_s": final_state.simulation_time - start_state.simulation_time,
            "elapsed_wall_time_s": time.perf_counter() - started,
            "final_position": list(final_state.base_position),
            "fallen": fallen,
        }
        reason = None if status is SkillStatus.SUCCESS else "walk did not reach the target distance"
        return self.result(
            status,
            reason=reason,
            metrics=metrics,
            steps=steps,
            duration_s=time.perf_counter() - started,
        )


class TurnSkill(Skill):
    """In-place yaw through the official pretrained G1 policy."""

    name = "turn"

    def available(self, context: SkillContext) -> bool:
        return context.controller is not None

    def unavailable_reason(self, context: SkillContext) -> str | None:
        return "official locomotion controller is not loaded"

    def check_preconditions(self, context: SkillContext) -> str | None:
        if not context.state().standing:
            return "turn requires a standing robot; run stand first"
        return None

    def run(self, context: SkillContext) -> SkillResult:
        target_deg = float(context.parameters.get("target_angle_deg", 45.0))
        tolerance_deg = float(context.parameters.get("tolerance_deg", 15.0))
        yaw_rate = float(context.parameters.get("yaw_rate_radps", 0.5))
        max_duration_s = float(context.parameters.get("max_duration_s", 10.0))
        settle_s = float(context.parameters.get("settle_s", 0.5))
        max_steps = min(int(round(max_duration_s / context.simulation.timestep)), context.max_steps)
        settle_steps = max(1, int(round(settle_s / context.simulation.timestep)))
        context.simulation.set_active_skill(self.name)
        context.controller.reset()
        started = time.perf_counter()
        start_state = context.state()
        yaw0 = _yaw_rad(start_state.base_orientation)
        command = np.array([0.0, 0.0, yaw_rate], dtype=np.float64)
        zero = np.zeros(3, dtype=np.float64)
        fallen = False
        steps = 0
        status = SkillStatus.TIMEOUT
        for _ in range(max_steps):
            state = context.simulation.step(_policy_torques(context, command))
            steps += 1
            turned = abs(math.degrees(_wrap_angle(_yaw_rad(state.base_orientation) - yaw0)))
            if state.fallen:
                fallen = True
                status = SkillStatus.UNSAFE
                break
            if turned >= abs(target_deg):
                status = SkillStatus.SUCCESS
                break
        for _ in range(settle_steps):
            state = context.simulation.step(_policy_torques(context, zero))
            steps += 1
            if state.fallen:
                fallen = True
                status = SkillStatus.UNSAFE
                break
        final_state = context.state()
        turned_deg = math.degrees(_wrap_angle(_yaw_rad(final_state.base_orientation) - yaw0))
        heading_error_deg = turned_deg - target_deg
        within_tolerance = abs(heading_error_deg) <= tolerance_deg
        if status is SkillStatus.SUCCESS and not within_tolerance:
            status = SkillStatus.FAILURE
        metrics = {
            "target_angle_deg": target_deg,
            "tolerance_deg": tolerance_deg,
            "turned_deg": turned_deg,
            "heading_error_deg": heading_error_deg,
            "elapsed_sim_time_s": final_state.simulation_time - start_state.simulation_time,
            "elapsed_wall_time_s": time.perf_counter() - started,
            "fallen": fallen,
        }
        reason = None if status is SkillStatus.SUCCESS else "turn did not reach the target heading"
        return self.result(
            status,
            reason=reason,
            metrics=metrics,
            steps=steps,
            duration_s=time.perf_counter() - started,
        )
