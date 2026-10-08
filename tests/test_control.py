"""Official locomotion controller wiring tests."""

from __future__ import annotations

import numpy as np
import pytest

from g1swarm.config import build_controller, build_simulation, locomotion_config


def _controller_or_skip(robot: dict):
    config = locomotion_config(robot)
    if config is None:
        pytest.skip("robot config has no official controller")
    try:
        import torch  # noqa: F401
    except ImportError:
        pytest.skip("torch is not installed in this environment")
    return build_controller(robot)


def test_controller_produces_finite_torques(locomotion_robot: dict) -> None:
    simulation = build_simulation(locomotion_robot, seed=0)
    controller = _controller_or_skip(locomotion_robot)
    try:
        command = np.zeros(3)
        for _ in range(60):
            torques = controller.compute_torques(
                joint_positions=simulation.joint_positions(),
                joint_velocities=simulation.joint_velocities(),
                quaternion=simulation.base_quaternion(),
                angular_velocity=simulation.base_angular_velocity(),
                command=command,
                dt=simulation.timestep,
            )
            assert torques.shape == (simulation.num_actuators,)
            assert np.all(np.isfinite(torques))
            state = simulation.step(torques)
            assert state.is_finite()
        assert controller.num_actions == simulation.num_actuators
    finally:
        simulation.close()


def test_policy_memory_reset_is_available(locomotion_robot: dict) -> None:
    controller = _controller_or_skip(locomotion_robot)
    controller.reset()  # must not raise; recurrent policy exposes reset_memory
