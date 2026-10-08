"""Outer-loop path correction tests (signs, clamp, tracking, delegation)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from g1swarm.control import (
    CorrectionConfig,
    CorrectionSample,
    CorrectionTracker,
    CorrectingController,
    PathCorrectionPolicy,
)
from g1swarm.segmentation.mission import MissionFrame
from g1swarm.state import RobotState


def _state(position=(0.0, 0.0, 0.78), yaw_deg: float = 0.0) -> RobotState:
    half = math.radians(yaw_deg) / 2.0
    return RobotState(
        simulation_time=1.0,
        base_position=position,
        base_orientation=(math.cos(half), 0.0, 0.0, math.sin(half)),
        linear_velocity=(0.5, 0.0, 0.0),
        angular_velocity=(0.0, 0.0, 0.0),
        standing=True,
        fallen=False,
        active_skill="walk_forward",
    )


def _frame(yaw_deg: float = 0.0) -> MissionFrame:
    return MissionFrame.from_state(_state(yaw_deg=yaw_deg))


NOMINAL = np.array([0.5, 0.0, 0.0])


def test_heading_error_sign_convention() -> None:
    frame = _frame()
    policy = PathCorrectionPolicy(CorrectionConfig(mode="heading_only", k_heading=1.0))
    corrected, sample = policy.compute(_state(yaw_deg=10.0), frame, NOMINAL, sim_time_s=1.0)
    assert sample.heading_error_rad == pytest.approx(math.radians(10.0))
    assert sample.yaw_raw < 0.0  # turned left -> correct right
    assert corrected[2] == pytest.approx(sample.yaw_raw)
    opposite, other = policy.compute(_state(yaw_deg=-10.0), frame, NOMINAL, sim_time_s=1.0)
    assert other.yaw_raw > 0.0


def test_lateral_error_sign_convention() -> None:
    frame = _frame()
    policy = PathCorrectionPolicy(
        CorrectionConfig(mode="heading_lateral", k_heading=1.0, k_lateral=1.0)
    )
    corrected, sample = policy.compute(_state(position=(0.0, 0.4, 0.78)), frame, NOMINAL, sim_time_s=1.0)
    assert sample.lateral_error_m == pytest.approx(0.4)  # +Y is left of +X
    assert sample.yaw_raw < 0.0  # displaced left -> steer right
    right_side, other = policy.compute(
        _state(position=(0.0, -0.4, 0.78)), frame, NOMINAL, sim_time_s=1.0
    )
    assert other.yaw_raw > 0.0


def test_zero_error_produces_zero_correction() -> None:
    for mode, kwargs in (("heading_only", {"k_heading": 1.0}), ("heading_lateral", {"k_heading": 1.0, "k_lateral": 1.0})):
        policy = PathCorrectionPolicy(CorrectionConfig(mode=mode, **kwargs))
        corrected, sample = policy.compute(_state(), _frame(), NOMINAL, sim_time_s=1.0)
        assert sample.yaw_raw == 0.0
        assert corrected[2] == 0.0
        np.testing.assert_allclose(corrected[:2], NOMINAL[:2])


def test_correction_magnitude_and_clamp() -> None:
    frame = _frame()
    policy = PathCorrectionPolicy(
        CorrectionConfig(mode="heading_only", k_heading=1.0, max_yaw_rate_radps=0.3)
    )
    _, small = policy.compute(_state(yaw_deg=10.0), frame, NOMINAL, sim_time_s=1.0)
    assert small.yaw_clipped == pytest.approx(-math.radians(10.0))
    assert small.saturated is False
    _, large = policy.compute(_state(yaw_deg=60.0), frame, NOMINAL, sim_time_s=1.0)
    assert large.yaw_clipped == pytest.approx(-0.3)
    assert large.saturated is True


def test_deadband_suppresses_small_corrections() -> None:
    policy = PathCorrectionPolicy(
        CorrectionConfig(mode="heading_only", k_heading=0.01, deadband_radps=0.01)
    )
    _, sample = policy.compute(_state(yaw_deg=1.0), _frame(), NOMINAL, sim_time_s=1.0)
    assert sample.yaw_raw == 0.0


def test_tracker_statistics_and_oscillation_deadband() -> None:
    tracker = CorrectionTracker(oscillation_threshold_radps=0.05)
    for yaw in (0.2, 0.2, -0.2, -0.2, 0.001, -0.001):
        tracker.add(
            CorrectionSample(
                sim_time_s=0.0,
                heading_error_rad=0.0,
                lateral_error_m=0.0,
                yaw_raw=yaw,
                yaw_clipped=yaw,
                saturated=False,
                vx_command=0.5,
            )
        )
    summary = tracker.summary()
    assert summary["correction_samples"] == 6
    assert summary["correction_max_abs"] == pytest.approx(0.2)
    assert summary["control_oscillation_count"] == 1  # tiny noise is below the threshold
    assert summary["saturation_count"] == 0


def test_saturation_logging() -> None:
    tracker = CorrectionTracker()
    for _ in range(3):
        tracker.add(
            CorrectionSample(
                sim_time_s=1.0,
                heading_error_rad=0.0,
                lateral_error_m=0.0,
                yaw_raw=-5.0,
                yaw_clipped=-0.6,
                saturated=True,
                vx_command=0.5,
            )
        )
    summary = tracker.summary()
    assert summary["saturation_count"] == 3
    assert summary["saturation_fraction"] == pytest.approx(1.0)
    assert summary["first_saturation_time_s"] == 1.0


def test_config_validation_and_serialization() -> None:
    with pytest.raises(ValueError):
        CorrectionConfig(mode="sideways").validate()
    with pytest.raises(ValueError):
        CorrectionConfig(mode="heading_only", k_heading=0.0).validate()
    config = CorrectionConfig(mode="heading_lateral", k_heading=1.0, k_lateral=0.5)
    payload = config.to_dict()
    assert payload["mode"] == "heading_lateral"
    assert payload["k_lateral"] == 0.5


def test_open_loop_mode_returns_the_nominal_command() -> None:
    policy = PathCorrectionPolicy(CorrectionConfig(mode="none"))
    corrected, sample = policy.compute(_state(yaw_deg=25.0), _frame(), NOMINAL, sim_time_s=1.0)
    np.testing.assert_allclose(corrected, NOMINAL)
    assert sample.yaw_clipped == 0.0
    assert sample.yaw_raw == 0.0


class _RecordingController:
    def __init__(self) -> None:
        self.commands: list[np.ndarray] = []
        self.reset_calls = 0

    def compute_torques(self, *, command, **kwargs) -> np.ndarray:
        self.commands.append(np.array(command, dtype=np.float64))
        return np.zeros(12)

    def reset(self) -> None:
        self.reset_calls += 1


class _SimulationStub:
    def __init__(self, state: RobotState) -> None:
        self._state = state

    def get_robot_state(self) -> RobotState:
        return self._state


def test_correcting_controller_only_changes_the_high_level_command() -> None:
    controller = _RecordingController()
    simulation = _SimulationStub(_state(yaw_deg=10.0))
    frame = _frame()
    policy = PathCorrectionPolicy(CorrectionConfig(mode="heading_only", k_heading=1.0))
    correcting = CorrectingController(controller, policy, simulation, frame)
    correcting.compute_torques(
        joint_positions=np.zeros(12),
        joint_velocities=np.zeros(12),
        quaternion=np.array([1.0, 0.0, 0.0, 0.0]),
        angular_velocity=np.zeros(3),
        command=NOMINAL,
        dt=0.002,
    )
    sent = controller.commands[-1]
    assert sent[0] == pytest.approx(NOMINAL[0])  # vx untouched
    assert sent[1] == pytest.approx(NOMINAL[1])  # vy untouched
    assert sent[2] < 0.0  # yaw correction applied at command level
    correcting.reset()
    assert controller.reset_calls == 1  # memory-reset semantics delegated unchanged
