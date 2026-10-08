"""Reference-frame ablation checks without changing any historical evaluator."""

from __future__ import annotations

import copy
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from g1swarm.boundary.envelope import evaluate_walk_task
from g1swarm.control.path_correction import CorrectionConfig, PathCorrectionPolicy
from g1swarm.paths import repo_root
from g1swarm.reference_ablation import experiment
from g1swarm.reference_ablation.experiment import (
    ReferenceCorrectionPolicy, ReferenceRunner, replay_reference,
)
from g1swarm.segmentation.mission import MissionFrame
from g1swarm.skills import StandSkill, StopSkill, TurnSkill, WalkForwardSkill
from g1swarm.state.robot_state import RobotState
from g1swarm.transition_learning.cases import EVAL_CASES, PRIMITIVE_CASES, SEQUENCE_CASES
from g1swarm.transition_learning.env import EpisodeRunner, replay_case


def _state(x, y, heading):
    return RobotState(
        simulation_time=1.0, base_position=(x, y, .78),
        base_orientation=(math.cos(heading / 2), 0.0, 0.0, math.sin(heading / 2)),
        linear_velocity=(.5, 0.0, 0.0), angular_velocity=(0.0, 0.0, 0.0),
        standing=True, fallen=False,
    )


def _policy():
    return PathCorrectionPolicy(CorrectionConfig(
        mode="heading_lateral", k_heading=1.5, k_lateral=1.0,
        max_yaw_rate_radps=.6, deadband_radps=.01, oscillation_threshold_radps=.05,
    ))


@pytest.mark.parametrize("sign", [-1.0, 1.0])
def test_nonzero_origin_and_yaw_select_planned_axis_without_changing_local_frame(sign):
    planned_origin = np.array([.4, .2 * sign])
    planned_yaw = .2 * sign
    state = _state(.45, .3 * sign, .3 * sign)
    local = MissionFrame.from_state(state)
    runner = SimpleNamespace(planned_origin=planned_origin.copy(), planned_heading=planned_yaw, index=0)
    actual = ReferenceCorrectionPolicy(runner, "actual_node_start", _policy())
    ideal = ReferenceCorrectionPolicy(runner, "ideal_commanded_axis", _policy())
    nominal = np.array([.5, 0.0, 0.0])
    actual_command, _ = actual.compute(state, local, nominal, sim_time_s=1.0)
    ideal_command, sample = ideal.compute(state, local, nominal, sim_time_s=1.0)
    # Independent geometric derivation, including the nonzero planned origin.
    dx, dy = .45 - planned_origin[0], .3 * sign - planned_origin[1]
    expected_lateral = -math.sin(planned_yaw) * dx + math.cos(planned_yaw) * dy
    expected_heading = .3 * sign - planned_yaw
    expected_yaw = -1.5 * expected_heading - expected_lateral
    assert actual.selected_frame(local) is local
    assert actual_command.tolist() == [.5, 0.0, 0.0]
    assert ideal_command == pytest.approx([.5, 0.0, expected_yaw], abs=1e-14)
    assert sample.lateral_error_m == pytest.approx(expected_lateral, abs=1e-14)
    assert sample.heading_error_rad == pytest.approx(expected_heading, abs=1e-14)
    assert local == MissionFrame.from_state(state)
    assert np.array_equal(runner.planned_origin, planned_origin)
    assert runner.planned_heading == planned_yaw
    assert nominal.tolist() == [.5, 0.0, 0.0]


def test_reference_selection_retains_original_saturation_and_deadband():
    runner = SimpleNamespace(planned_origin=np.zeros(2), planned_heading=0.0, index=0)
    policy = ReferenceCorrectionPolicy(runner, "ideal_commanded_axis", _policy())
    nominal = np.array([.5, 0.0, 0.0])
    large = _state(0.0, 2.0, math.pi / 2)
    command, sample = policy.compute(large, MissionFrame.from_state(large), nominal, sim_time_s=1.0)
    assert command.tolist() == [.5, 0.0, -.6] and sample.saturated
    small = _state(0.0, .001, .002)
    command, sample = policy.compute(small, MissionFrame.from_state(small), nominal, sim_time_s=1.0)
    assert command.tolist() == [.5, 0.0, 0.0] and not sample.saturated
    assert policy.config == _policy().config


@pytest.mark.parametrize("mode", [None, "", "ideal", "actual", "adaptive"])
def test_invalid_reference_mode_rejected_before_robot_initialization(mode, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid mode must fail before constructing a robot")
    monkeypatch.setattr(EpisodeRunner, "__init__", forbidden)
    with pytest.raises(ValueError, match="reference mode"):
        ReferenceRunner(PRIMITIVE_CASES[0], mode)
    with pytest.raises(ValueError, match="reference mode"):
        ReferenceCorrectionPolicy(SimpleNamespace(), mode, _policy())


def test_declared_case_collections_equal_original_frozen_evaluation_sets():
    assert experiment.EVAL_CASES is EVAL_CASES
    assert experiment.PRIMITIVE_CASES is PRIMITIVE_CASES
    assert experiment.SEQUENCE_CASES is SEQUENCE_CASES
    manifest = json.loads((repo_root() / experiment.PILOT / "case_manifest.json").read_text(encoding="utf-8"))
    assert manifest["evaluation"] == list(EVAL_CASES)
    assert manifest["primitive"] == list(PRIMITIVE_CASES)
    assert manifest["sequence"] == list(SEQUENCE_CASES)
    assert len(EVAL_CASES) == 16 and len(PRIMITIVE_CASES) == 8 and len(SEQUENCE_CASES) == 2


@pytest.fixture(scope="module")
def physical_policy(locomotion_robot):
    if not (repo_root() / locomotion_robot["controller"]["policy_path"]).is_file():
        pytest.skip("Official locomotion policy is unavailable")
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def _original_measures(value, original):
    """Compare every original measured field, ignoring only wall clock."""
    if isinstance(original, dict):
        return {
            key: _original_measures(value[key], item)
            for key, item in original.items()
            if "wall" not in key
        }
    if isinstance(original, list):
        assert len(value) == len(original)
        return [_original_measures(item, prior) for item, prior in zip(value, original)]
    return value


def _trace(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def mixed_replays(physical_policy, tmp_path_factory):
    directory = tmp_path_factory.mktemp("reference-ablation-tests")
    case = {"id": "reference-test-mixed", "group": "sequence", "transition": "mixed", "nodes": [
        {"skill": "stand", "parameters": {"duration_s": 10.0}},
        {"skill": "walk_forward", "parameters": {"target_distance_m": 1.5,
            "tolerance_m": .2, "speed_mps": .5, "max_duration_s": 15.0}},
        {"skill": "turn", "parameters": {"target_angle_deg": 20.0,
            "tolerance_deg": 15.0, "yaw_rate_radps": .5,
            "max_duration_s": 10.0, "settle_s": .5}},
        {"skill": "walk_forward", "parameters": {"target_distance_m": 1.5,
            "tolerance_m": .2, "speed_mps": .5, "max_duration_s": 15.0}},
        {"skill": "stop", "parameters": {"window_s": 1.0,
            "speed_threshold_mps": .10, "max_duration_s": 4.0}},
    ]}
    before = copy.deepcopy(case)
    records = {"original": replay_case(case, "deterministic_correction", trace_path=directory / "original.jsonl")}
    for mode in experiment.MODES:
        records[mode] = replay_reference(case, mode, trace_path=directory / f"{mode}.jsonl")
    assert case == before
    return records, {key: _trace(directory / f"{key}.jsonl") for key in records}


def test_actual_reference_exactly_replays_original_deterministic_physics(mixed_replays):
    records, traces = mixed_replays
    original = records["original"]
    assert _original_measures(records["actual_node_start"], original) == _original_measures(original, original)
    command_rows = [row for row in traces["actual_node_start"] if "applied_command" in row]
    assert len(command_rows) == len(traces["original"])
    assert [_original_measures(row, prior) for row, prior in zip(command_rows, traces["original"])] == traces["original"]


def test_reference_only_changes_walking_commands_and_keeps_residual_disabled(mixed_replays):
    records, traces = mixed_replays
    for mode in experiment.MODES:
        record = records[mode]
        assert record["residual_enabled"] is False and record["PPO_training"] is False
        assert record["memory_reset_count"] == 4
        assert [node["skill"] for node in record["nodes"]] == ["stand", "walk_forward", "turn", "walk_forward", "stop"]
        for row in traces[mode]:
            if "applied_command" not in row:
                continue
            assert row["action"] == [0.0, 0.0, 0.0]
            assert row["residual"] == [0.0, 0.0, 0.0]
            if row["skill"] != "walk_forward":
                assert row["applied_command"] == row["nominal_command"]
    actual_walk = [row["applied_command"] for row in traces["actual_node_start"] if row.get("skill") == "walk_forward" and "applied_command" in row]
    ideal_walk = [row["applied_command"] for row in traces["ideal_commanded_axis"] if row.get("skill") == "walk_forward" and "applied_command" in row]
    assert actual_walk != ideal_walk


def test_local_measurements_and_envelopes_keep_actual_node_start_frame(mixed_replays):
    records, _ = mixed_replays
    for node in records["ideal_commanded_axis"]["nodes"]:
        if node["skill"] != "walk_forward":
            continue
        start = RobotState.from_dict(node["start_state"])
        end = RobotState.from_dict(node["end_state"])
        actual = MissionFrame.from_state(start)
        forward, lateral = actual.project(end.base_position)
        heading = actual.heading_error_deg(end)
        assert node["forward_progress_m"] == pytest.approx(forward, abs=1e-14)
        assert node["lateral_drift_m"] == pytest.approx(lateral, abs=1e-14)
        assert node["heading_error_deg"] == pytest.approx(heading, abs=1e-14)
        distance = node["parameters"]["target_distance_m"]
        independently_scored = evaluate_walk_task({
            "absolute_distance_error_m": abs(forward - distance), "lateral_drift_m": lateral,
            "heading_error_deg": heading, "completion_sim_time_s": node["duration_s"],
        }, distance, physical=node["physical_success"])
        assert node["envelope"] == independently_scored
        assert node["walking_reference"]["measurement_origin"] == list(start.base_position)
        assert node["walking_reference"]["measurement_heading_rad"] == actual.initial_yaw_rad


def test_original_controller_gains_and_skill_classes_are_preserved(physical_policy):
    original = EpisodeRunner(PRIMITIVE_CASES[0], "deterministic_correction")
    altered = ReferenceRunner(PRIMITIVE_CASES[0], "ideal_commanded_axis")
    try:
        assert altered.base.config == original.base.config
        assert altered.robot == original.robot
        assert altered.sim.timestep == original.sim.timestep == .002
        assert altered.correction.config == original.correction.config
        assert altered.router.skill_names == original.router.skill_names
        for name, cls in {"stand": StandSkill, "walk_forward": WalkForwardSkill, "turn": TurnSkill, "stop": StopSkill}.items():
            assert type(altered.router.get(name)) is type(original.router.get(name)) is cls
        assert altered.control is None and altered.treatment == "deterministic_correction"
    finally:
        original.close()
        altered.close()


@pytest.mark.parametrize("case", PRIMITIVE_CASES, ids=lambda case: case["id"])
def test_all_primitives_have_exact_physics_in_both_reference_modes(case, physical_policy):
    before = copy.deepcopy(case)
    original = replay_case(case, "deterministic_correction")
    for mode in experiment.MODES:
        observed = replay_reference(case, mode)
        assert _original_measures(observed, original) == _original_measures(original, original)
        assert observed["task_success"] == original["task_success"]
        assert observed["physical_success"] == original["physical_success"]
    assert case == before
