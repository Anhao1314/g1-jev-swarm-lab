"""First version of the shared robot-state protocol.

``RobotState`` is the contract that skills, the skill router, evaluation and
future decision layers share. It intentionally exposes a compact, serializable
view of the robot instead of raw simulator buffers.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

REQUIRED_FIELDS = (
    "simulation_time",
    "base_position",
    "base_orientation",
    "linear_velocity",
    "angular_velocity",
    "standing",
    "fallen",
    "active_skill",
)


def _as_tuple(values: Any, length: int | None, name: str) -> tuple[float, ...]:
    try:
        result = tuple(float(value) for value in values)
    except TypeError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{name} must be a sequence of numbers") from exc
    if length is not None and len(result) != length:
        raise ValueError(f"{name} must contain exactly {length} values, got {len(result)}")
    return result


@dataclass(frozen=True)
class RobotState:
    """Compact robot state exchanged between runtime layers.

    ``base_orientation`` uses the MuJoCo quaternion convention ``(w, x, y, z)``.
    Joint arrays are optional: upper layers only receive them when a caller
    explicitly needs them (for example a locomotion skill), never by default.
    """

    simulation_time: float
    base_position: tuple[float, float, float]
    base_orientation: tuple[float, float, float, float]
    linear_velocity: tuple[float, float, float]
    angular_velocity: tuple[float, float, float]
    standing: bool
    fallen: bool
    active_skill: str | None = None
    joint_positions: tuple[float, ...] | None = None
    joint_velocities: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "simulation_time", float(self.simulation_time))
        object.__setattr__(self, "base_position", _as_tuple(self.base_position, 3, "base_position"))
        object.__setattr__(
            self, "base_orientation", _as_tuple(self.base_orientation, 4, "base_orientation")
        )
        object.__setattr__(self, "linear_velocity", _as_tuple(self.linear_velocity, 3, "linear_velocity"))
        object.__setattr__(
            self, "angular_velocity", _as_tuple(self.angular_velocity, 3, "angular_velocity")
        )
        if self.joint_positions is not None:
            object.__setattr__(
                self, "joint_positions", _as_tuple(self.joint_positions, None, "joint_positions")
            )
        if self.joint_velocities is not None:
            object.__setattr__(
                self, "joint_velocities", _as_tuple(self.joint_velocities, None, "joint_velocities")
            )

    def numeric_values(self) -> tuple[float, ...]:
        values: list[float] = [self.simulation_time]
        values.extend(self.base_position)
        values.extend(self.base_orientation)
        values.extend(self.linear_velocity)
        values.extend(self.angular_velocity)
        if self.joint_positions is not None:
            values.extend(self.joint_positions)
        if self.joint_velocities is not None:
            values.extend(self.joint_velocities)
        return tuple(values)

    def is_finite(self) -> bool:
        """True when every numeric entry is finite (no NaN / Infinity)."""

        return all(math.isfinite(value) for value in self.numeric_values())

    def speed(self) -> float:
        """Horizontal base speed in m/s."""

        vx, vy, _ = self.linear_velocity
        return math.hypot(vx, vy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_time": self.simulation_time,
            "base_position": list(self.base_position),
            "base_orientation": list(self.base_orientation),
            "linear_velocity": list(self.linear_velocity),
            "angular_velocity": list(self.angular_velocity),
            "standing": self.standing,
            "fallen": self.fallen,
            "active_skill": self.active_skill,
            "joint_positions": None if self.joint_positions is None else list(self.joint_positions),
            "joint_velocities": None if self.joint_velocities is None else list(self.joint_velocities),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RobotState":
        missing = [field for field in REQUIRED_FIELDS if field not in data]
        if missing:
            raise ValueError(f"missing required RobotState fields: {', '.join(missing)}")
        return cls(**{field: data[field] for field in data})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "RobotState":
        return cls.from_dict(json.loads(payload))
