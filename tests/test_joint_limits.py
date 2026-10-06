"""Joint-limit guard tests for initial-state perturbations."""

from __future__ import annotations

import numpy as np
import pytest

from g1swarm.boundary.perturbation_guard import clip_joint_offsets
from g1swarm.config import build_simulation


def test_joint_limits_are_reported(locomotion_robot: dict) -> None:
    simulation = build_simulation(locomotion_robot, seed=0)
    try:
        low, high = simulation.joint_limits()
        assert low.shape == (simulation.num_actuators,)
        assert high.shape == (simulation.num_actuators,)
        assert np.all(low <= high)
        assert np.any(np.isfinite(low))
    finally:
        simulation.close()


def test_offsets_are_clipped_to_limits() -> None:
    positions = np.array([0.0, 0.0, 0.0])
    offsets = np.array([5.0, -5.0, 0.1])
    low = np.array([-1.0, -0.5, -0.5])
    high = np.array([1.0, 0.5, 0.5])
    clipped, count = clip_joint_offsets(positions, offsets, low, high)
    assert count == 2
    assert np.allclose(positions + clipped, [1.0, -0.5, 0.1])


def test_unlimited_joints_are_left_alone() -> None:
    positions = np.array([0.0])
    offsets = np.array([3.0])
    low = np.array([-np.inf])
    high = np.array([np.inf])
    clipped, count = clip_joint_offsets(positions, offsets, low, high)
    assert count == 0
    assert clipped[0] == pytest.approx(3.0)


def test_invalid_offsets_and_shapes_are_rejected() -> None:
    with pytest.raises(ValueError):
        clip_joint_offsets(
            np.zeros(2), np.array([np.nan, 0.0]), np.array([-1.0, -1.0]), np.array([1.0, 1.0])
        )
    with pytest.raises(ValueError):
        clip_joint_offsets(np.zeros(2), np.zeros(3), np.zeros(2), np.ones(2))


def test_large_sampled_offsets_stay_inside_model_limits(locomotion_robot: dict) -> None:
    simulation = build_simulation(locomotion_robot, seed=0)
    try:
        positions = simulation.joint_positions()
        low, high = simulation.joint_limits()
        rng = np.random.default_rng(7)
        offsets = rng.normal(0.0, 1.0, size=simulation.num_actuators)
        clipped, count = clip_joint_offsets(positions, offsets, low, high)
        resulting = positions + clipped
        assert np.all(resulting <= high + 1e-12)
        assert np.all(resulting >= low - 1e-12)
        assert count >= 1
    finally:
        simulation.close()
