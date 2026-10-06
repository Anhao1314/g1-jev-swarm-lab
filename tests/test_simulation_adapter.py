"""Simulation adapter tests against the vendored official G1 model."""

from __future__ import annotations

import numpy as np
import pytest

from g1swarm.config import build_simulation
from g1swarm.simulation import InvalidControlError, SimulationStateError


def test_model_loads_and_reports_dimensions(locomotion_robot: dict) -> None:
    simulation = build_simulation(locomotion_robot, seed=0)
    try:
        assert simulation.num_qpos == 19
        assert simulation.num_qvel == 18
        assert simulation.num_actuators == 12
        assert simulation.timestep == pytest.approx(0.002)
        summary = simulation.model_summary()
        assert summary["name"] == locomotion_robot["name"]
        assert len(summary["actuator_names"]) == 12
    finally:
        simulation.close()


def test_reset_returns_valid_state_and_is_repeatable(locomotion_robot: dict) -> None:
    simulation = build_simulation(locomotion_robot, seed=0)
    try:
        first = simulation.reset(seed=0)
        assert first.is_finite()
        assert first.standing
        assert not first.fallen
        assert simulation.simulation_time == 0.0
        second = simulation.reset(seed=0)
        assert first.to_dict() == second.to_dict()
    finally:
        simulation.close()


def test_step_advances_time_and_returns_finite_state(locomotion_robot: dict) -> None:
    simulation = build_simulation(locomotion_robot, seed=0)
    try:
        control = np.zeros(simulation.num_actuators)
        state = simulation.step(control)
        assert state.simulation_time == pytest.approx(simulation.timestep)
        assert state.is_finite()
    finally:
        simulation.close()


def test_invalid_control_is_rejected(locomotion_robot: dict) -> None:
    simulation = build_simulation(locomotion_robot, seed=0)
    try:
        with pytest.raises(InvalidControlError):
            simulation.step(np.zeros(simulation.num_actuators - 1))
        with pytest.raises(InvalidControlError):
            simulation.step(np.full(simulation.num_actuators, np.nan))
    finally:
        simulation.close()


def test_closed_simulation_rejects_use(locomotion_robot: dict) -> None:
    simulation = build_simulation(locomotion_robot, seed=0)
    simulation.close()
    with pytest.raises(SimulationStateError):
        simulation.step()
