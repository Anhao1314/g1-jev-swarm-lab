"""Phase 1.2b tests: mission frame, schedules, memory flag, artifacts."""

from __future__ import annotations

import json
import math

import numpy as np
import yaml

from g1swarm.segmentation import (
    MissionFrame,
    SegmentationRunner,
    build_distance_boundary,
    build_execution_strategy_map,
    build_risk_map_v1_2b,
    build_segment_schedule,
    build_segmentation_comparison,
    build_state_aware_schedule,
    drift_per_meter,
    heading_error_per_meter,
    validate_comparison,
    validate_distance_boundary,
    validate_execution_strategy,
    validate_risk_map_v1_2b,
)
from g1swarm.skills import SkillContext, SkillRequest, SkillRouter, WalkForwardSkill
from g1swarm.state import RobotState

PROTOCOL = yaml.safe_load(
    open("configs/experiments/g1_distance_segmentation_001.yaml", encoding="utf-8").read()
)


def _state(position=(0.0, 0.0, 0.78), yaw_deg: float = 0.0, standing: bool = True) -> RobotState:
    half = math.radians(yaw_deg) / 2.0
    return RobotState(
        simulation_time=0.0,
        base_position=position,
        base_orientation=(math.cos(half), 0.0, 0.0, math.sin(half)),
        linear_velocity=(0.0, 0.0, 0.0),
        angular_velocity=(0.0, 0.0, 0.0),
        standing=standing,
        fallen=False,
        active_skill=None,
    )


def test_mission_frame_projection_and_heading() -> None:
    frame = MissionFrame.from_state(_state(yaw_deg=90.0))
    forward, lateral = frame.project((0.0, 3.0, 0.78))
    assert forward == 3.0 and abs(lateral) < 1e-9
    assert frame.heading_error_deg(_state(yaw_deg=90.0)) == 0.0
    assert frame.heading_error_deg(_state(yaw_deg=110.0)) == 20.0


def test_segment_schedule_generation() -> None:
    assert build_segment_schedule(8.0) == [2.0, 2.0, 2.0, 2.0]
    assert build_segment_schedule(5.0) == [2.0, 2.0, 1.0]
    assert build_segment_schedule(3.5) == [2.0, 1.5]
    assert build_segment_schedule(1.0) == [1.0]


def test_state_aware_schedule_uses_remaining_distance() -> None:
    assert build_state_aware_schedule(8.0, 6.3) == [1.7]
    assert build_state_aware_schedule(8.0, 8.0) == []
    assert build_state_aware_schedule(8.0, 0.0) == [2.0, 2.0, 2.0, 2.0]


def test_per_meter_rates() -> None:
    assert drift_per_meter(-0.4, 4.0) == -0.1
    assert heading_error_per_meter(-8.0, 4.0) == -2.0
    assert drift_per_meter(0.0, 0.0) is None


class _FakeController:
    def __init__(self) -> None:
        self.reset_calls = 0

    def reset(self) -> None:
        self.reset_calls += 1

    def compute_torques(self, **kwargs) -> np.ndarray:
        return np.zeros(12)


class _FakeSimulation:
    timestep = 0.002
    num_actuators = 12

    def __init__(self, state: RobotState) -> None:
        self._state = state

    def get_robot_state(self) -> RobotState:
        return self._state

    def step(self, control=None) -> RobotState:
        return self._state

    def set_active_skill(self, name) -> None:
        return None

    def joint_positions(self) -> np.ndarray:
        return np.zeros(12)

    def joint_velocities(self) -> np.ndarray:
        return np.zeros(12)

    def base_quaternion(self) -> np.ndarray:
        return np.array([1.0, 0.0, 0.0, 0.0])

    def base_angular_velocity(self) -> np.ndarray:
        return np.zeros(3)


def test_walk_forward_reset_memory_flag() -> None:
    simulation = _FakeSimulation(_state())
    router = SkillRouter([WalkForwardSkill()])
    for reset_memory, expected in ((True, 1), (False, 0)):
        controller = _FakeController()
        context = SkillContext(
            simulation=simulation, controller=controller, robot_config={}, max_steps=1, seed=0
        )
        router.execute(
            SkillRequest(
                "walk_forward",
                {
                    "target_distance_m": 0.1,
                    "max_duration_s": 0.002,
                    "reset_memory": reset_memory,
                },
            ),
            context,
        )
        assert controller.reset_calls == expected


def _boundary_observation(value: float, task: int, n: int = 3, drift: float = 0.0) -> dict:
    return {
        "value": value,
        "n_runs": n,
        "physical_successes": n,
        "task_successes": task,
        "physical_success_rate": 1.0,
        "task_success_rate": task / n,
        "zone": "reliable" if task == n else "failure",
        "deterministic": True,
        "failure_counts": {} if task == n else {"EXCESSIVE_DRIFT": n - task},
        "metrics": {
            "strict_violation_rate": 0.0,
            "mean_lateral_drift_m": drift,
            "mean_heading_error_deg": -2.0,
            "mean_completion_sim_time_s": value * 2.2,
            "mean_mean_speed_mps": 0.45,
            "drift_per_meter": drift / value,
        },
        "run_ids": [f"run-{value:g}-{i}" for i in range(n)],
        "risk": "LOW" if task == n else "HIGH",
    }


def test_distance_boundary_detection() -> None:
    payload = {
        "search": {
            "bracket": [2.75, 3.0],
            "boundary_estimate": 2.75,
            "boundary_reached": True,
            "stop_reason": "boundary_refined",
            "resolution_m": 0.25,
            "trace": [{"decision": "safe_start", "value": 2.0}],
        },
        "final": [
            _boundary_observation(2.75, 3, drift=-0.55),
            _boundary_observation(3.0, 0, drift=-0.62),
        ],
    }
    boundary = build_distance_boundary(PROTOCOL, payload)
    validate_distance_boundary(boundary)
    assert boundary["last_reliable_m"] == 2.75
    assert boundary["first_failure_m"] == 3.0
    assert boundary["task_boundary_bracket_m"] == [2.75, 3.0]
    assert boundary["dominant_failure_modes"][0]["failure_type"] == "EXCESSIVE_DRIFT"


def _mission(treatment: str, distance: float, task: bool, drift: float, heading: float,
             stops: int, resets: int, time_s: float = 10.0) -> dict:
    return {
        "run_id": f"{treatment}-{distance:g}",
        "treatment": treatment,
        "total_distance_m": distance,
        "phase": "final",
        "seed": 0,
        "metrics": {
            "treatment": treatment,
            "physical_success": True,
            "task_success": task,
            "final_forward_progress_m": distance,
            "final_lateral_drift_m": drift,
            "final_heading_error_deg": heading,
            "total_simulation_time_s": time_s,
            "total_stopping_time_s": 1.0 * stops,
            "path_length_m": distance,
            "skill_invocations": max(1, stops),
            "stops": stops,
            "controller_memory_resets": resets,
            "failure_type": "SUCCESS" if task else "EXCESSIVE_DRIFT",
        },
    }


def test_comparison_verdicts_and_same_frame() -> None:
    records = [
        _mission("direct_long", 4.0, False, drift=-1.0, heading=-18.0, stops=0, resets=1),
        _mission("segmented_continuous", 4.0, True, drift=-0.2, heading=-4.0, stops=2, resets=0),
        _mission("segmented_reset", 4.0, False, drift=-0.9, heading=-17.0, stops=2, resets=2),
    ]
    comparison = build_segmentation_comparison(PROTOCOL, records)
    validate_comparison(comparison)
    entry = comparison["distances"]["4"]["treatments"]
    assert entry["segmented_continuous"]["improvement_vs_direct"]["verdict"] == "IMPROVED_TASK_OUTCOME"
    assert entry["segmented_reset"]["improvement_vs_direct"]["verdict"] == "NO_IMPROVEMENT"
    assert entry["segmented_continuous"]["delta_vs_direct"]["lateral_drift_m"] == 0.8


def test_risk_and_strategy_maps_validate() -> None:
    records = [
        _mission("direct_long", 8.0, False, drift=-1.5, heading=-22.0, stops=0, resets=1),
        _mission("segmented_continuous", 8.0, True, drift=-0.3, heading=-5.0, stops=4, resets=0),
    ]
    comparison = build_segmentation_comparison(PROTOCOL, records)
    payload = {
        "search": {"bracket": [2.75, 3.0], "boundary_estimate": 2.75, "boundary_reached": True,
                   "stop_reason": "boundary_refined", "resolution_m": 0.25, "trace": []},
        "final": [_boundary_observation(2.75, 3), _boundary_observation(3.0, 0)],
    }
    boundary = build_distance_boundary(PROTOCOL, payload)
    risk = build_risk_map_v1_2b(
        protocol=PROTOCOL, boundary=boundary, comparison=comparison, source_commit="abc"
    )
    validate_risk_map_v1_2b(risk)
    strategy = build_execution_strategy_map(
        protocol=PROTOCOL, comparison=comparison, source_commit="abc"
    )
    validate_execution_strategy(strategy)
    assert risk["skills"]["walk_forward"]["distance_boundary"]["last_reliable_m"] == 2.75
    assert strategy["strategies"]["8"]["direct_long"]["task_success"] is False
    assert json.loads(json.dumps(risk)) == risk


def test_phase_12_maps_are_not_overwritten() -> None:
    phase12 = json.loads(
        open(
            "experiments/baselines/g1_failure_boundary_001/risk_map.json", encoding="utf-8"
        ).read()
    )
    assert phase12["experiment_id"] == "g1_failure_boundary_001"
    assert "g1_distance_segmentation_001" not in json.dumps(phase12)


def test_one_mission_integration(tmp_path, monkeypatch, locomotion_robot: dict) -> None:
    monkeypatch.setenv("G1SWARM_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    runner = SegmentationRunner(
        "configs/experiments/g1_distance_segmentation_001.yaml", campaign="pilot"
    )
    record = runner.run_mission("direct_long", 4.0, phase="pilot", seed=0)
    summary = runner.summarize()
    assert summary["missions_total"] == 1
    assert summary["task_successes"] == sum(
        1 for item in runner.records if item["metrics"]["task_success"]
    )
    metrics = record["metrics"]
    for key in (
        "final_forward_progress_m",
        "final_lateral_drift_m",
        "final_heading_error_deg",
        "controller_memory_resets",
        "skill_invocations",
        "path_length_m",
        "physical_success",
        "task_success",
    ):
        assert key in metrics
    assert metrics["controller_memory_resets"] == 1
