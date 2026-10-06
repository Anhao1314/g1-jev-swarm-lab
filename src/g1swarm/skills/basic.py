"""Phase 1 skills for the Unitree G1.

* ``StandSkill`` - stable stance through the official pretrained controller
  (zero velocity command).
* ``StopSkill`` - zero-velocity command through the official controller.
* ``WalkForwardSkill`` - forward velocity command through the official
  pretrained Unitree locomotion policy (real actuator input, no teleporting).
* ``TurnSkill`` - yaw-rate command through the same official policy.

Every result is derived from measured simulation state: a skill reports
``FAILURE``/``TIMEOUT``/``UNSAFE`` instead of pretending success. Phase 1.1 adds
formal preconditions (checked by the router before any control is issued, with
``PRECONDITION_FAILED`` on rejection) and threshold-crossing timestamps used by
the characterization evidence.
"""

from __future__ import annotations

import math
import time
from collections import deque

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


def _roll_pitch_deg(quaternion: np.ndarray | tuple[float, ...]) -> tuple[float, float]:
    w, x, y, z = (float(value) for value in quaternion)
    norm = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x))))
    return math.degrees(roll), math.degrees(pitch)


def _yaw_rad(quaternion: np.ndarray | tuple[float, ...]) -> float:
    w, x, y, z = (float(value) for value in quaternion)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def _horizontal_offset(start: RobotState, end: RobotState) -> np.ndarray:
    return np.array(end.base_position[:2], dtype=np.float64) - np.array(
        start.base_position[:2], dtype=np.float64
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


def _common_preconditions(context: SkillContext, *, require_standing: bool) -> str | None:
    """Formal Phase 1.1 preconditions shared by the four target skills.

    Preconditions are checked by the router before any control is issued; the
    skill body is never entered when one of them fails.
    """

    if context.controller is None:
        return "official locomotion controller is not available"
    state = context.state()
    if not state.is_finite():
        return "robot state is non-finite"
    if require_standing:
        if state.fallen:
            return "robot is fallen"
        if not state.standing:
            return "robot is not standing"
    return None


class StandSkill(Skill):
    """Hold a stable stance with the official pretrained controller."""

    name = "stand"

    def check_preconditions(self, context: SkillContext) -> str | None:
        return _common_preconditions(context, require_standing=False)

    def run(self, context: SkillContext) -> SkillResult:
        duration_s = float(context.parameters.get("duration_s", 2.0))
        steps_limit = min(int(round(duration_s / context.simulation.timestep)), context.max_steps)
        context.simulation.set_active_skill(self.name)
        context.controller.reset()
        zero_command = np.zeros(3, dtype=np.float64)
        started = time.perf_counter()
        start_state = context.state()
        heights: list[float] = []
        tilts: list[float] = []
        rolls: list[float] = []
        pitches: list[float] = []
        speeds: list[float] = []
        fallen = False
        steps = 0
        for _ in range(max(1, steps_limit)):
            state = context.simulation.step(_policy_torques(context, zero_command))
            steps += 1
            heights.append(state.base_position[2])
            tilts.append(_tilt_deg(state.base_orientation))
            roll, pitch = _roll_pitch_deg(state.base_orientation)
            rolls.append(roll)
            pitches.append(pitch)
            speeds.append(state.speed())
            if state.fallen:
                fallen = True
                break
        final_state = context.state()
        metrics = {
            "duration_s": duration_s,
            "requested_steps": steps_limit,
            "height_min_m": min(heights) if heights else final_state.base_position[2],
            "height_mean_m": float(np.mean(heights)) if heights else final_state.base_position[2],
            "height_max_m": max(heights) if heights else final_state.base_position[2],
            "final_height_m": final_state.base_position[2],
            "max_abs_roll_deg": max((abs(value) for value in rolls), default=0.0),
            "max_abs_pitch_deg": max((abs(value) for value in pitches), default=0.0),
            "max_tilt_deg": max(tilts) if tilts else _tilt_deg(final_state.base_orientation),
            "final_speed_mps": final_state.speed(),
            "mean_speed_mps": float(np.mean(speeds)) if speeds else 0.0,
            "base_drift_m": float(np.linalg.norm(_horizontal_offset(start_state, final_state))),
            "fallen": fallen,
            "controller": "official_pretrained_policy",
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

    def check_preconditions(self, context: SkillContext) -> str | None:
        return _common_preconditions(context, require_standing=False)

    def run(self, context: SkillContext) -> SkillResult:
        max_duration_s = float(context.parameters.get("max_duration_s", 4.0))
        window_s = float(context.parameters.get("window_s", 1.0))
        speed_threshold = float(context.parameters.get("speed_threshold_mps", 0.10))
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
        threshold_crossing_sim_time: float | None = None
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
                threshold_crossing_sim_time = state.simulation_time
                status = SkillStatus.SUCCESS
                break
        window_mean = (
            sum(recent_speeds) / len(recent_speeds) if recent_speeds else final_speed
        )
        metrics = {
            "final_speed_mps": final_speed,
            "final_window_mean_speed_mps": window_mean,
            "speed_threshold_mps": speed_threshold,
            "window_s": window_s,
            "threshold_crossing_sim_time": threshold_crossing_sim_time,
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

    def check_preconditions(self, context: SkillContext) -> str | None:
        return _common_preconditions(context, require_standing=True)

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
        # Phase 1.2b: ``reset_memory=False`` keeps the recurrent policy state
        # continuous across consecutive WalkForward invocations (segmentation
        # study). The default preserves the Phase 1/1.1/1.2 lifecycle.
        reset_memory = bool(context.parameters.get("reset_memory", True))
        if reset_memory:
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
        success_threshold = target_distance_m - tolerance_m
        threshold_crossing_sim_time: float | None = None
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
            if progress >= success_threshold and threshold_crossing_sim_time is None:
                threshold_crossing_sim_time = state.simulation_time
            if progress >= stop_at_distance_m:
                status = (
                    SkillStatus.SUCCESS
                    if progress >= success_threshold
                    else SkillStatus.FAILURE
                )
                break
        final_state = context.state()
        yaw_final = _yaw_rad(final_state.base_orientation)
        elapsed_sim_time = final_state.simulation_time - start_state.simulation_time
        metrics = {
            "target_distance_m": target_distance_m,
            "stop_at_distance_m": stop_at_distance_m,
            "tolerance_m": tolerance_m,
            "forward_displacement_m": progress,
            "lateral_drift_m": lateral,
            "heading_error_deg": math.degrees(_wrap_angle(yaw_final - yaw0)),
            "elapsed_sim_time_s": elapsed_sim_time,
            "elapsed_wall_time_s": time.perf_counter() - started,
            "mean_speed_mps": (progress / elapsed_sim_time) if elapsed_sim_time > 0 else 0.0,
            "residual_speed_mps": final_state.speed(),
            "controller_memory_reset": reset_memory,
            "threshold_crossing_sim_time": threshold_crossing_sim_time,
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

    def check_preconditions(self, context: SkillContext) -> str | None:
        return _common_preconditions(context, require_standing=True)

    def run(self, context: SkillContext) -> SkillResult:
        target_deg = float(context.parameters.get("target_angle_deg", 45.0))
        # Implementation fix (Phase 1.1 characterization): the command must
        # follow the sign of the target angle. Before this fix a negative
        # target was executed as a positive turn (90.4 deg error at -45 deg).
        yaw_direction = 1.0 if target_deg >= 0.0 else -1.0
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
        yaw_rate_command = yaw_direction * abs(yaw_rate)
        command = np.array([0.0, 0.0, yaw_rate_command], dtype=np.float64)
        zero = np.zeros(3, dtype=np.float64)
        fallen = False
        steps = 0
        status = SkillStatus.TIMEOUT
        threshold_crossing_sim_time: float | None = None
        for _ in range(max_steps):
            state = context.simulation.step(_policy_torques(context, command))
            steps += 1
            turned = abs(math.degrees(_wrap_angle(_yaw_rad(state.base_orientation) - yaw0)))
            if state.fallen:
                fallen = True
                status = SkillStatus.UNSAFE
                break
            if turned >= abs(target_deg):
                threshold_crossing_sim_time = state.simulation_time
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
            "yaw_rate_command_radps": yaw_rate_command,
            "tolerance_deg": tolerance_deg,
            "turned_deg": turned_deg,
            "heading_error_deg": heading_error_deg,
            "translation_drift_m": float(
                np.linalg.norm(_horizontal_offset(start_state, final_state))
            ),
            "elapsed_sim_time_s": final_state.simulation_time - start_state.simulation_time,
            "elapsed_wall_time_s": time.perf_counter() - started,
            "residual_speed_mps": final_state.speed(),
            "threshold_crossing_sim_time": threshold_crossing_sim_time,
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
