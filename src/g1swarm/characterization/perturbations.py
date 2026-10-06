"""Seeded, one-factor-at-a-time perturbations for skill characterization.

Design rules:

* one factor at a time - a condition changes exactly one thing;
* the same seed always produces the same physical perturbation;
* every sampled value is recorded in the run manifest;
* initial-state injection happens once, right after ``reset``; the scheduled
  push is injected inside the physics loop through ``DisturbanceProxy``.

The perturbation harness is deliberately separate from the skill layer: skills
only ever issue actuator commands, never state writes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping

import numpy as np

from ..state.robot_state import RobotState

GRAVITY = 9.81


class PerturbationKind(str, Enum):
    NOMINAL = "nominal"
    YAW = "yaw"
    XY_OFFSET = "xy_offset"
    JOINT = "joint"
    FRICTION = "friction"
    PUSH = "push"


@dataclass(frozen=True)
class Perturbation:
    kind: PerturbationKind
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind.value, "parameters": dict(self.parameters)}


def sample_perturbation(
    kind: PerturbationKind | str,
    *,
    seed: int,
    config: Mapping[str, Any],
    num_joints: int,
) -> Perturbation:
    """Sample one perturbation from the frozen ranges in ``config``."""

    kind = PerturbationKind(kind)
    rng = np.random.default_rng(int(seed))
    if kind is PerturbationKind.NOMINAL:
        return Perturbation(kind)
    if kind is PerturbationKind.YAW:
        limit_deg = float(config["yaw_offset_deg_limit"])
        return Perturbation(
            kind, {"yaw_offset_deg": float(rng.uniform(-limit_deg, limit_deg))}
        )
    if kind is PerturbationKind.XY_OFFSET:
        limit_m = float(config["xy_offset_m_limit"])
        offsets = rng.uniform(-limit_m, limit_m, size=2)
        return Perturbation(
            kind,
            {"x_offset_m": float(offsets[0]), "y_offset_m": float(offsets[1])},
        )
    if kind is PerturbationKind.JOINT:
        position_std = float(config["joint_position_std_rad"])
        velocity_std = float(config["joint_velocity_std_radps"])
        position_offsets = rng.normal(0.0, position_std, size=num_joints)
        velocity_offsets = rng.normal(0.0, velocity_std, size=num_joints)
        return Perturbation(
            kind,
            {
                "position_std_rad": position_std,
                "velocity_std_radps": velocity_std,
                "position_offsets_rad": [float(value) for value in position_offsets],
                "velocity_offsets_radps": [float(value) for value in velocity_offsets],
                "max_abs_position_offset_rad": float(np.max(np.abs(position_offsets))),
                "max_abs_velocity_offset_radps": float(np.max(np.abs(velocity_offsets))),
            },
        )
    if kind is PerturbationKind.FRICTION:
        low, high = (float(value) for value in config["friction_slide_range"])
        slide = float(rng.uniform(low, high))
        return Perturbation(
            kind, {"friction_slide": slide, "range": [low, high]}
        )
    if kind is PerturbationKind.PUSH:
        low, high = (float(value) for value in config["push_force_fraction_range"])
        fraction = float(rng.uniform(low, high))
        mass_kg = float(config["robot_mass_kg"])
        trigger_low, trigger_high = (
            float(value) for value in config["push_trigger_s_range"]
        )
        trigger_s = float(rng.uniform(trigger_low, trigger_high))
        direction = [float(value) for value in config.get("push_direction", [0.0, 1.0, 0.0])]
        return Perturbation(
            kind,
            {
                "force_n": fraction * mass_kg * GRAVITY,
                "force_fraction_bodyweight": fraction,
                "robot_mass_kg": mass_kg,
                "direction": direction,
                "duration_s": float(config["push_duration_s"]),
                "trigger_s": trigger_s,
            },
        )
    raise ValueError(f"unsupported perturbation kind: {kind}")


def apply_initial_perturbation(simulation, perturbation: Perturbation) -> dict[str, Any]:
    """Apply an initial-condition perturbation to a freshly reset simulation."""

    kind = perturbation.kind
    parameters = perturbation.parameters
    if kind is PerturbationKind.YAW:
        simulation.set_base_state(yaw_rad=math.radians(parameters["yaw_offset_deg"]))
    elif kind is PerturbationKind.XY_OFFSET:
        simulation.set_base_state(
            xy=(parameters["x_offset_m"], parameters["y_offset_m"])
        )
    elif kind is PerturbationKind.JOINT:
        simulation.offset_joint_state(
            position_offsets=np.asarray(parameters["position_offsets_rad"], dtype=np.float64),
            velocity_offsets=np.asarray(
                parameters["velocity_offsets_radps"], dtype=np.float64
            ),
        )
    elif kind is PerturbationKind.FRICTION:
        simulation.set_all_geom_friction(float(parameters["friction_slide"]))
    return dict(parameters)


@dataclass(frozen=True)
class PushSpec:
    force_n: float
    direction: tuple[float, float, float]
    duration_s: float
    trigger_sim_time: float

    def force_vector(self) -> np.ndarray:
        return np.asarray(self.direction, dtype=np.float64) * self.force_n

    def to_dict(self) -> dict[str, Any]:
        return {
            "force_n": self.force_n,
            "direction": list(self.direction),
            "duration_s": self.duration_s,
            "trigger_sim_time": self.trigger_sim_time,
        }


def push_spec_from(perturbation: Perturbation) -> PushSpec | None:
    if perturbation.kind is not PerturbationKind.PUSH:
        return None
    parameters = perturbation.parameters
    direction = tuple(float(value) for value in parameters["direction"])
    if len(direction) != 3:
        raise ValueError("push direction must have exactly three components")
    return PushSpec(
        force_n=float(parameters["force_n"]),
        direction=direction,
        duration_s=float(parameters["duration_s"]),
        trigger_sim_time=float(parameters["trigger_s"]),
    )


class DisturbanceProxy:
    """Delegating simulation wrapper that injects a scheduled base push.

    Skills receive this proxy as their ``simulation``; all calls are forwarded to
    the real adapter. The proxy only ever sets ``xfrc_applied`` on the base body
    for the scheduled window and clears it afterwards.
    """

    def __init__(self, simulation, push: PushSpec | None = None) -> None:
        self._simulation = simulation
        self._push = push
        self._active = False
        self._events: list[dict[str, Any]] = []

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    @property
    def push(self) -> PushSpec | None:
        return self._push

    def arm_push(self, trigger_sim_time: float) -> None:
        if self._push is not None:
            self._push = replace(self._push, trigger_sim_time=float(trigger_sim_time))

    def step(self, control=None) -> RobotState:
        push = self._push
        if push is not None:
            time_now = float(self._simulation.simulation_time)
            active_now = push.trigger_sim_time <= time_now < (
                push.trigger_sim_time + push.duration_s
            )
            if active_now and not self._active:
                self._simulation.apply_base_force(push.force_vector())
                self._active = True
                self._events.append(
                    {
                        "event": "push_start",
                        "sim_time": time_now,
                        **push.to_dict(),
                    }
                )
            elif not active_now and self._active:
                self._simulation.clear_applied_forces()
                self._active = False
                self._events.append({"event": "push_end", "sim_time": time_now})
        return self._simulation.step(control)

    def release(self) -> None:
        if self._active:
            self._simulation.clear_applied_forces()
            self._active = False
            self._events.append(
                {"event": "push_end", "sim_time": float(self._simulation.simulation_time), "released": True}
            )

    def __getattr__(self, name: str):
        return getattr(self._simulation, name)
