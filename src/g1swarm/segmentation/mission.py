"""Mission-frame metrics and segment schedules for Phase 1.2b.

The mission frame is fixed at mission start (initial base position and heading).
Every forward/lateral/heading quantity for both the single long walk and every
segmented treatment is projected onto that same frame, so accumulated yaw is
never washed out by re-defining "forward" per segment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from ..characterization.kinematics import wrap_angle_deg, wrap_angle_rad, yaw_rad
from ..state.robot_state import RobotState

DEFAULT_SEGMENT_M = 2.0


@dataclass(frozen=True)
class MissionFrame:
    """Frozen initial frame: origin at mission start, +X along initial heading."""

    initial_position: tuple[float, float, float]
    initial_yaw_rad: float

    @classmethod
    def from_state(cls, state: RobotState) -> "MissionFrame":
        return cls(initial_position=state.base_position, initial_yaw_rad=yaw_rad(state.base_orientation))

    @property
    def forward_axis(self) -> np.ndarray:
        return np.array([math.cos(self.initial_yaw_rad), math.sin(self.initial_yaw_rad)])

    def project(self, position) -> tuple[float, float]:
        """Project a world position onto the mission frame (forward, lateral)."""

        offset = np.array(position[:2], dtype=np.float64) - np.array(
            self.initial_position[:2], dtype=np.float64
        )
        forward = float(offset @ self.forward_axis)
        lateral = float(self.forward_axis[0] * offset[1] - self.forward_axis[1] * offset[0])
        return forward, lateral

    def heading_error_rad(self, state: RobotState) -> float:
        """Signed heading error in radians, wrapped to [-pi, pi]."""

        return wrap_angle_rad(yaw_rad(state.base_orientation) - self.initial_yaw_rad)

    def heading_error_deg(self, state: RobotState) -> float:
        return wrap_angle_deg(
            math.degrees(yaw_rad(state.base_orientation)) - math.degrees(self.initial_yaw_rad)
        )


def build_segment_schedule(
    total_distance_m: float,
    *,
    segment_length_m: float = DEFAULT_SEGMENT_M,
    minimum_segment_m: float = 0.1,
) -> list[float]:
    """Fixed segmentation schedule: full segments plus a final partial segment."""

    total = float(total_distance_m)
    segment = float(segment_length_m)
    if total <= 0.0 or segment <= 0.0:
        raise ValueError("total distance and segment length must be positive")
    schedule: list[float] = []
    remaining = total
    while remaining > minimum_segment_m:
        piece = min(segment, remaining)
        schedule.append(round(piece, 6))
        remaining -= piece
    if not schedule:
        schedule.append(round(total, 6))
    return schedule


def build_state_aware_schedule(
    total_distance_m: float,
    achieved_forward_m: float,
    *,
    segment_length_m: float = DEFAULT_SEGMENT_M,
    minimum_segment_m: float = 0.1,
) -> list[float]:
    """Recompute the *remaining* distance along the mission axis.

    Only the distance is adjusted - no yaw or lateral correction is possible
    through this interface.
    """

    remaining = float(total_distance_m) - float(achieved_forward_m)
    if remaining <= minimum_segment_m:
        return []
    return build_segment_schedule(
        remaining, segment_length_m=segment_length_m, minimum_segment_m=minimum_segment_m
    )


def heading_error_per_meter(heading_error_deg: float, forward_m: float) -> float | None:
    if abs(forward_m) < 1e-9:
        return None
    return float(heading_error_deg) / float(forward_m)


def drift_per_meter(lateral_m: float, forward_m: float) -> float | None:
    if abs(forward_m) < 1e-9:
        return None
    return float(lateral_m) / float(forward_m)


class PathLengthProxy:
    """Simulation proxy that accumulates the travelled base path length."""

    def __init__(self, simulation) -> None:
        self._simulation = simulation
        self._last_position = np.array(simulation.get_robot_state().base_position[:2], dtype=np.float64)
        self.path_length_m = 0.0

    def step(self, control=None):
        state = self._simulation.step(control)
        position = np.array(state.base_position[:2], dtype=np.float64)
        self.path_length_m += float(np.linalg.norm(position - self._last_position))
        self._last_position = position
        return state

    def reset_path(self) -> None:
        self.path_length_m = 0.0
        self._last_position = np.array(
            self._simulation.get_robot_state().base_position[:2], dtype=np.float64
        )

    def __getattr__(self, name: str):
        return getattr(self._simulation, name)
