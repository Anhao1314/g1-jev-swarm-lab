"""Formal skill preconditions: rejection happens before any control is issued."""

from __future__ import annotations

import numpy as np

from g1swarm.skills import (
    SkillContext,
    SkillRouter,
    SkillStatus,
    StandSkill,
    StopSkill,
    TurnSkill,
    WalkForwardSkill,
)
from g1swarm.state import RobotState


class _FakeSimulation:
    def __init__(self, state: RobotState) -> None:
        self._state = state
        self.step_calls = 0
        self.timestep = 0.002
        self.num_actuators = 12

    def get_robot_state(self) -> RobotState:
        return self._state

    def step(self, control=None) -> RobotState:
        self.step_calls += 1
        return self._state

    def set_active_skill(self, name) -> None:
        return None

    def joint_positions(self) -> np.ndarray:
        return np.zeros(self.num_actuators)

    def joint_velocities(self) -> np.ndarray:
        return np.zeros(self.num_actuators)

    def base_quaternion(self) -> np.ndarray:
        return np.array([1.0, 0.0, 0.0, 0.0])

    def base_angular_velocity(self) -> np.ndarray:
        return np.zeros(3)


def _state(**overrides) -> RobotState:
    values = dict(
        simulation_time=0.0,
        base_position=(0.0, 0.0, 0.78),
        base_orientation=(1.0, 0.0, 0.0, 0.0),
        linear_velocity=(0.0, 0.0, 0.0),
        angular_velocity=(0.0, 0.0, 0.0),
        standing=True,
        fallen=False,
        active_skill=None,
    )
    values.update(overrides)
    return RobotState(**values)


def _run(skill, state: RobotState, *, controller):
    simulation = _FakeSimulation(state)
    router = SkillRouter([skill])
    context = SkillContext(
        simulation=simulation, controller=controller, robot_config={}, max_steps=10, seed=0
    )
    result = router.execute(skill.name, context)
    return result, simulation


def test_walk_requires_standing_and_not_fallen() -> None:
    result, simulation = _run(WalkForwardSkill(), _state(standing=False), controller=object())
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert simulation.step_calls == 0
    result, simulation = _run(WalkForwardSkill(), _state(fallen=True), controller=object())
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert simulation.step_calls == 0


def test_walk_requires_controller_and_finite_state() -> None:
    result, simulation = _run(WalkForwardSkill(), _state(), controller=None)
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert simulation.step_calls == 0
    result, simulation = _run(
        WalkForwardSkill(), _state(linear_velocity=(float("nan"), 0.0, 0.0)), controller=object()
    )
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert simulation.step_calls == 0


def test_turn_preconditions() -> None:
    result, simulation = _run(TurnSkill(), _state(standing=False), controller=object())
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert simulation.step_calls == 0
    result, simulation = _run(TurnSkill(), _state(), controller=None)
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert simulation.step_calls == 0


def test_stop_requires_controller_and_finite_state() -> None:
    result, simulation = _run(StopSkill(), _state(), controller=None)
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert simulation.step_calls == 0
    result, simulation = _run(
        StopSkill(), _state(simulation_time=float("inf")), controller=object()
    )
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert simulation.step_calls == 0


def test_stand_requires_controller_and_finite_state_but_not_standing() -> None:
    result, simulation = _run(StandSkill(), _state(standing=False), controller=None)
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert simulation.step_calls == 0
    result, simulation = _run(
        StandSkill(), _state(base_position=(0.0, 0.0, float("nan"))), controller=object()
    )
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert simulation.step_calls == 0
