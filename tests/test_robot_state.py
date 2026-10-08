"""RobotState contract tests."""

from __future__ import annotations

import dataclasses
import json

import pytest

from g1swarm.state import RobotState


def _state(**overrides) -> RobotState:
    values = dict(
        simulation_time=0.5,
        base_position=(1.0, 0.0, 0.78),
        base_orientation=(1.0, 0.0, 0.0, 0.0),
        linear_velocity=(0.4, 0.0, 0.0),
        angular_velocity=(0.0, 0.0, 0.1),
        standing=True,
        fallen=False,
        active_skill="walk_forward",
    )
    values.update(overrides)
    return RobotState(**values)


def test_create_and_required_fields() -> None:
    state = _state()
    payload = state.to_dict()
    for field in (
        "simulation_time",
        "base_position",
        "base_orientation",
        "linear_velocity",
        "angular_velocity",
        "standing",
        "fallen",
        "active_skill",
    ):
        assert field in payload
    assert state.standing is True
    assert state.fallen is False
    assert state.active_skill == "walk_forward"


def test_frozen() -> None:
    state = _state()
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.standing = False  # type: ignore[misc]


def test_serialization_roundtrip() -> None:
    state = _state(joint_positions=(0.1, 0.2), joint_velocities=(0.0, 0.0))
    restored = RobotState.from_json(state.to_json())
    assert restored == state
    assert json.loads(state.to_json())["base_position"] == [1.0, 0.0, 0.78]


def test_missing_field_is_rejected() -> None:
    payload = _state().to_dict()
    del payload["fallen"]
    with pytest.raises(ValueError, match="fallen"):
        RobotState.from_dict(payload)


def test_wrong_vector_length_is_rejected() -> None:
    with pytest.raises(ValueError):
        _state(base_position=(0.0, 0.0))


def test_non_finite_detection() -> None:
    assert _state().is_finite()
    assert not _state(linear_velocity=(float("nan"), 0.0, 0.0)).is_finite()
    assert not _state(simulation_time=float("inf")).is_finite()


def test_speed_uses_horizontal_velocity() -> None:
    state = _state(linear_velocity=(3.0, 4.0, 9.0))
    assert state.speed() == pytest.approx(5.0)
