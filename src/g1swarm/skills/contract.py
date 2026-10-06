"""Minimal skill contract shared by every skill implementation.

The runtime must not care whether a skill is a deterministic controller, an
official robot primitive, a PPO policy or a future learned policy. Skills
therefore share one small interface: availability, preconditions, ``run`` and a
structured ``SkillResult``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Protocol, runtime_checkable

import numpy as np

from ..state.robot_state import RobotState


class SkillStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"
    INTERRUPTED = "INTERRUPTED"
    UNSAFE = "UNSAFE"
    RUNNING = "RUNNING"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"


@dataclass(frozen=True)
class SkillResult:
    """Structured outcome of one skill execution."""

    skill: str
    status: SkillStatus
    reason: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    steps: int = 0
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status is SkillStatus.SUCCESS

    @property
    def terminal(self) -> bool:
        return self.status is not SkillStatus.RUNNING

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "status": self.status.value,
            "reason": self.reason,
            "metrics": self.metrics,
            "steps": self.steps,
            "duration_s": self.duration_s,
        }


@runtime_checkable
class SimulationProtocol(Protocol):
    """The slice of the simulation adapter that skills are allowed to use."""

    timestep: float
    num_actuators: int

    def reset(self, *, seed: int | None = None, keyframe: str | None = None) -> RobotState: ...

    def step(self, control: np.ndarray | None = None) -> RobotState: ...

    def get_robot_state(self) -> RobotState: ...

    def set_active_skill(self, name: str | None) -> None: ...

    def joint_positions(self) -> np.ndarray: ...

    def joint_velocities(self) -> np.ndarray: ...

    def base_quaternion(self) -> np.ndarray: ...

    def base_angular_velocity(self) -> np.ndarray: ...


@dataclass
class SkillContext:
    """Everything a skill is allowed to know about its runtime."""

    simulation: SimulationProtocol
    controller: Any | None = None
    robot_config: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    max_steps: int = 100_000
    seed: int = 0

    def state(self) -> RobotState:
        return self.simulation.get_robot_state()

    @property
    def controller_config(self) -> dict[str, Any]:
        return self.robot_config.get("controller", {})

    def default_angles(self) -> np.ndarray:
        return np.asarray(self.controller_config.get("default_angles", []), dtype=np.float64)

    def kp(self) -> np.ndarray:
        return np.asarray(self.controller_config.get("kp", []), dtype=np.float64)

    def kd(self) -> np.ndarray:
        return np.asarray(self.controller_config.get("kd", []), dtype=np.float64)


class Skill(ABC):
    """One bounded, verifiable embodied behavior."""

    name: ClassVar[str] = ""

    def available(self, context: SkillContext) -> bool:  # noqa: ARG002 - default is available
        return True

    def unavailable_reason(self, context: SkillContext) -> str | None:  # noqa: ARG002
        return None

    def check_preconditions(self, context: SkillContext) -> str | None:  # noqa: ARG002
        """Return a human-readable reason when preconditions fail, else None."""

        return None

    @abstractmethod
    def run(self, context: SkillContext) -> SkillResult:
        """Execute the skill and return a structured, measurable result."""

    def result(
        self,
        status: SkillStatus,
        *,
        reason: str | None = None,
        metrics: dict[str, Any] | None = None,
        steps: int = 0,
        duration_s: float = 0.0,
    ) -> SkillResult:
        return SkillResult(
            skill=self.name,
            status=status,
            reason=reason,
            metrics=metrics or {},
            steps=steps,
            duration_s=duration_s,
        )
