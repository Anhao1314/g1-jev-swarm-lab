"""Small kinematics helpers used by characterization metrics."""

from __future__ import annotations

import math

import numpy as np

from ..state.robot_state import RobotState


def _normalized(quaternion) -> tuple[float, float, float, float]:
    w, x, y, z = (float(value) for value in quaternion)
    norm = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    return w / norm, x / norm, y / norm, z / norm


def yaw_rad(quaternion) -> float:
    w, x, y, z = _normalized(quaternion)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def yaw_deg(quaternion) -> float:
    return math.degrees(yaw_rad(quaternion))


def roll_pitch_deg(quaternion) -> tuple[float, float]:
    w, x, y, z = _normalized(quaternion)
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x))))
    return math.degrees(roll), math.degrees(pitch)


def wrap_angle_rad(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def wrap_angle_deg(angle: float) -> float:
    return math.degrees(wrap_angle_rad(math.radians(angle)))


def horizontal_offset(start: RobotState, end: RobotState) -> np.ndarray:
    return np.array(end.base_position[:2], dtype=np.float64) - np.array(
        start.base_position[:2], dtype=np.float64
    )


def forward_lateral(offset_xy: np.ndarray, yaw0_rad: float) -> tuple[float, float]:
    """Project an XY offset on the initial heading (forward, lateral)."""

    forward = np.array([math.cos(yaw0_rad), math.sin(yaw0_rad)], dtype=np.float64)
    forward_component = float(np.asarray(offset_xy) @ forward)
    lateral_component = float(forward[0] * offset_xy[1] - forward[1] * offset_xy[0])
    return forward_component, lateral_component
