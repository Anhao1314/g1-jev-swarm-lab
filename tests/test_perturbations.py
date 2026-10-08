"""Seeded perturbation generator and disturbance proxy tests."""

from __future__ import annotations

import numpy as np
import pytest

from g1swarm.characterization import (
    DisturbanceProxy,
    PerturbationKind,
    PushSpec,
    apply_initial_perturbation,
    push_spec_from,
    sample_perturbation,
)
from g1swarm.config import build_simulation

CONFIG = {
    "yaw_offset_deg_limit": 10.0,
    "xy_offset_m_limit": 0.05,
    "joint_position_std_rad": 0.02,
    "joint_velocity_std_radps": 0.05,
    "friction_slide_range": [0.4, 1.2],
    "push_force_fraction_range": [0.06, 0.10],
    "push_direction": [0.0, 1.0, 0.0],
    "push_duration_s": 0.2,
    "push_trigger_s_range": [1.0, 2.0],
    "robot_mass_kg": 32.107,
}

SAMPLED_KINDS = (
    PerturbationKind.YAW,
    PerturbationKind.XY_OFFSET,
    PerturbationKind.JOINT,
    PerturbationKind.FRICTION,
    PerturbationKind.PUSH,
)


def test_same_seed_produces_identical_perturbation() -> None:
    for kind in SAMPLED_KINDS:
        first = sample_perturbation(kind, seed=7, config=CONFIG, num_joints=12)
        second = sample_perturbation(kind, seed=7, config=CONFIG, num_joints=12)
        assert first == second


def test_different_seeds_produce_different_perturbation() -> None:
    for kind in SAMPLED_KINDS:
        first = sample_perturbation(kind, seed=0, config=CONFIG, num_joints=12)
        second = sample_perturbation(kind, seed=1, config=CONFIG, num_joints=12)
        assert first != second


def test_nominal_has_no_parameters() -> None:
    perturbation = sample_perturbation(
        PerturbationKind.NOMINAL, seed=0, config=CONFIG, num_joints=12
    )
    assert perturbation.parameters == {}


def test_joint_offsets_stay_bounded() -> None:
    perturbation = sample_perturbation(
        PerturbationKind.JOINT, seed=3, config=CONFIG, num_joints=12
    )
    offsets = np.asarray(perturbation.parameters["position_offsets_rad"])
    velocities = np.asarray(perturbation.parameters["velocity_offsets_radps"])
    assert offsets.shape == (12,)
    assert velocities.shape == (12,)
    # 5 sigma is a safe upper bound for 12 normal draws.
    assert np.max(np.abs(offsets)) < 5 * CONFIG["joint_position_std_rad"]
    assert np.max(np.abs(velocities)) < 5 * CONFIG["joint_velocity_std_radps"]


def test_push_stays_within_frozen_ranges() -> None:
    perturbation = sample_perturbation(
        PerturbationKind.PUSH, seed=4, config=CONFIG, num_joints=12
    )
    parameters = perturbation.parameters
    assert 0.06 <= parameters["force_fraction_bodyweight"] <= 0.10
    assert 1.0 <= parameters["trigger_s"] <= 2.0
    assert parameters["duration_s"] == pytest.approx(0.2)
    assert parameters["direction"] == [0.0, 1.0, 0.0]
    spec = push_spec_from(perturbation)
    assert spec is not None
    assert np.allclose(spec.force_vector(), [0.0, parameters["force_n"], 0.0])


def test_initial_perturbation_is_reproducible_on_the_model(locomotion_robot: dict) -> None:
    first = build_simulation(locomotion_robot, seed=0)
    second = build_simulation(locomotion_robot, seed=0)
    other = build_simulation(locomotion_robot, seed=0)
    try:
        for simulation in (first, second, other):
            simulation.reset(seed=0)
        perturbation = sample_perturbation(
            PerturbationKind.YAW, seed=5, config=CONFIG, num_joints=12
        )
        apply_initial_perturbation(first, perturbation)
        apply_initial_perturbation(second, perturbation)
        different = sample_perturbation(
            PerturbationKind.YAW, seed=6, config=CONFIG, num_joints=12
        )
        apply_initial_perturbation(other, different)
        assert first.get_robot_state().to_dict() == second.get_robot_state().to_dict()
        assert first.get_robot_state().base_orientation != other.get_robot_state().base_orientation
    finally:
        for simulation in (first, second, other):
            simulation.close()


def test_friction_is_applied_to_every_geom(locomotion_robot: dict) -> None:
    simulation = build_simulation(locomotion_robot, seed=0)
    try:
        simulation.set_all_geom_friction(0.6)
        summary = simulation.geom_friction_summary()
        assert summary["slide_values"] == [0.6]
        assert summary["geom_count"] > 0
    finally:
        simulation.close()


class _FakeSimulation:
    def __init__(self) -> None:
        self.time = 0.0
        self.force_calls: list[float] = []
        self.clear_calls = 0

    @property
    def simulation_time(self) -> float:
        return self.time

    def step(self, control=None):
        self.time += 0.002
        return None

    def apply_base_force(self, force):
        self.force_calls.append(float(np.asarray(force)[1]))

    def clear_applied_forces(self):
        self.clear_calls += 1


def test_disturbance_proxy_applies_force_only_inside_the_window() -> None:
    simulation = _FakeSimulation()
    proxy = DisturbanceProxy(
        simulation,
        PushSpec(force_n=25.0, direction=(0.0, 1.0, 0.0), duration_s=0.2, trigger_sim_time=0.1),
    )
    for _ in range(300):
        proxy.step(None)
    proxy.release()
    assert simulation.force_calls, "push force was never applied"
    assert all(value == pytest.approx(25.0) for value in simulation.force_calls)
    assert simulation.clear_calls >= 1
    events = [event["event"] for event in proxy.events]
    assert "push_start" in events and "push_end" in events
    start = next(event for event in proxy.events if event["event"] == "push_start")
    assert start["sim_time"] == pytest.approx(0.102, abs=0.004)
