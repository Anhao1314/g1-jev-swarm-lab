"""Independent geometry and real replay checks for origin-only selection."""

from __future__ import annotations

import copy
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from g1swarm.boundary.envelope import evaluate_walk_task
from g1swarm.control.path_correction import CorrectionConfig, PathCorrectionPolicy
from g1swarm.origin_ablation import experiment
from g1swarm.origin_ablation.experiment import OriginCorrectionPolicy, OriginRunner, replay_origin
from g1swarm.paths import repo_root
from g1swarm.reference_ablation.experiment import ReferenceRunner, replay_reference
from g1swarm.segmentation.mission import MissionFrame
from g1swarm.skills import StandSkill, StopSkill, TurnSkill, WalkForwardSkill
from g1swarm.state.robot_state import RobotState
from g1swarm.transition_learning.cases import EVAL_CASES, PRIMITIVE_CASES, SEQUENCE_CASES
from g1swarm.transition_learning.env import replay_case


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


def _expected_yaw(state, origin, heading):
    # Derive geometry independently; do not call selected_frame/project/compute.
    robot_yaw = 2 * math.atan2(state.base_orientation[3], state.base_orientation[0])
    error = math.atan2(math.sin(robot_yaw - heading), math.cos(robot_yaw - heading))
    dx = state.base_position[0] - origin[0]
    dy = state.base_position[1] - origin[1]
    lateral = -math.sin(heading) * dx + math.cos(heading) * dy
    raw = -1.5 * error - lateral
    if abs(raw) < .01:
        raw = 0.0
    return float(np.clip(raw, -.6, .6)), error, lateral


@pytest.mark.parametrize("sign", [-1.0, 1.0])
def test_hybrid_uses_actual_origin_and_ideal_heading_with_independent_geometry(sign):
    planned_origin = np.array([.4, .2 * sign])
    planned_heading = .2 * sign
    start = _state(.45, .3 * sign, .3 * sign)
    current = _state(.5, .4 * sign, .35 * sign)
    local = MissionFrame.from_state(start)
    runner = SimpleNamespace(planned_origin=planned_origin.copy(), planned_heading=planned_heading, index=0)
    nominal = np.array([.5, 0.0, 0.0])
    policies = {mode: OriginCorrectionPolicy(runner, mode, _policy()) for mode in experiment.MODES}
    samples = {}
    for mode, policy in policies.items():
        actual_mode = mode == "actual_node_start"
        origin = planned_origin if mode == "ideal_commanded_axis" else start.base_position
        heading = local.initial_yaw_rad if actual_mode else planned_heading
        expected_yaw, expected_heading, expected_lateral = _expected_yaw(current, origin, heading)
        command, sample = policy.compute(current, local, nominal, sim_time_s=1.0)
        assert command == pytest.approx([.5, 0.0, expected_yaw], abs=1e-14)
        assert sample.heading_error_rad == pytest.approx(expected_heading, abs=1e-14)
        assert sample.lateral_error_m == pytest.approx(expected_lateral, abs=1e-14)
        assert policy.config == _policy().config
        samples[mode] = sample
    hybrid = policies[experiment.HYBRID].selected_frame(local)
    full = policies["ideal_commanded_axis"].selected_frame(local)
    assert hybrid.initial_position == start.base_position
    assert hybrid.initial_position != full.initial_position
    assert hybrid.initial_yaw_rad == full.initial_yaw_rad == planned_heading
    assert hybrid.initial_yaw_rad != local.initial_yaw_rad
    assert samples[experiment.HYBRID].heading_error_rad == samples["ideal_commanded_axis"].heading_error_rad
    assert samples[experiment.HYBRID].lateral_error_m != samples["ideal_commanded_axis"].lateral_error_m
    assert policies["actual_node_start"].selected_frame(local) is local
    assert local == MissionFrame.from_state(start)
    assert np.array_equal(runner.planned_origin, planned_origin)
    assert runner.planned_heading == planned_heading
    assert nominal.tolist() == [.5, 0.0, 0.0]


def test_hybrid_wraps_ideal_heading_and_keeps_original_clipping():
    start = _state(1.0, 1.0, -math.pi + .03)
    local = MissionFrame.from_state(start)
    runner = SimpleNamespace(planned_origin=np.array([-10.0, -10.0]), planned_heading=math.pi - .02, index=0)
    policy = OriginCorrectionPolicy(runner, experiment.HYBRID, _policy())
    command, sample = policy.compute(start, local, np.array([.5, 0.0, 0.0]), sim_time_s=1.0)
    assert sample.heading_error_rad == pytest.approx(.05, abs=1e-14)
    assert sample.lateral_error_m == 0.0
    assert command[2] == pytest.approx(-.075, abs=1e-14)
    large = _state(1.0, 3.0, 0.0)
    runner.planned_heading = 0.0
    command, sample = policy.compute(large, local, np.array([.5, 0.0, 0.0]), sim_time_s=1.0)
    assert command.tolist() == [.5, 0.0, -.6] and sample.saturated


@pytest.mark.parametrize("mode", [None, "", "actual", "ideal", "hybrid", "adaptive"])
def test_invalid_mode_fails_before_old_runner_or_robot_initialization(mode, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid mode must be rejected before robot construction")
    monkeypatch.setattr(ReferenceRunner, "__init__", forbidden)
    with pytest.raises(ValueError, match="origin mode"):
        OriginRunner(PRIMITIVE_CASES[0], mode)
    with pytest.raises(ValueError, match="origin mode"):
        OriginCorrectionPolicy(SimpleNamespace(), mode, _policy())


def test_origin_experiment_reuses_exact_original_case_sets_and_old_mode_definitions():
    assert experiment.EVAL_CASES is EVAL_CASES
    assert experiment.PRIMITIVE_CASES is PRIMITIVE_CASES
    assert experiment.SEQUENCE_CASES is SEQUENCE_CASES
    manifest = json.loads((repo_root() / experiment.PILOT / "case_manifest.json").read_text(encoding="utf-8"))
    assert manifest["evaluation"] == list(EVAL_CASES)
    assert manifest["primitive"] == list(PRIMITIVE_CASES)
    assert manifest["sequence"] == list(SEQUENCE_CASES)
    assert (len(EVAL_CASES), len(PRIMITIVE_CASES), len(SEQUENCE_CASES)) == (16, 8, 2)
    from g1swarm.reference_ablation import experiment as previous
    assert previous.MODES == ("actual_node_start", "ideal_commanded_axis")
    assert experiment.MODES == ("actual_node_start", "actual_origin_ideal_heading", "ideal_commanded_axis")


@pytest.fixture(scope="module")
def physical_policy(locomotion_robot):
    if not (repo_root() / locomotion_robot["controller"]["policy_path"]).is_file():
        pytest.skip("Official locomotion policy is unavailable")
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def _existing_measures(value, original):
    if isinstance(original, dict):
        return {key: _existing_measures(value[key], item) for key, item in original.items() if "wall" not in key}
    if isinstance(original, list):
        assert len(value) == len(original)
        return [_existing_measures(item, prior) for item, prior in zip(value, original)]
    return value


def _trace(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def mixed_replays(physical_policy, tmp_path_factory):
    directory = tmp_path_factory.mktemp("origin-ablation-tests")
    case = {"id": "origin-test-mixed", "group": "sequence", "transition": "mixed", "nodes": [
        {"skill": "stand", "parameters": {"duration_s": 10.0}},
        {"skill": "walk_forward", "parameters": {"target_distance_m": 1.5,
            "tolerance_m": .2, "speed_mps": .5, "max_duration_s": 15.0}},
        {"skill": "turn", "parameters": {"target_angle_deg": 20.0,
            "tolerance_deg": 15.0, "yaw_rate_radps": .5, "max_duration_s": 10.0, "settle_s": .5}},
        {"skill": "walk_forward", "parameters": {"target_distance_m": 1.5,
            "tolerance_m": .2, "speed_mps": .5, "max_duration_s": 15.0}},
        {"skill": "stop", "parameters": {"window_s": 1.0,
            "speed_threshold_mps": .10, "max_duration_s": 4.0}},
    ]}
    before = copy.deepcopy(case)
    records, traces = {}, {}
    for mode in experiment.MODES:
        name = f"origin-{mode}"
        records[name] = replay_origin(case, mode, trace_path=directory / f"{name}.jsonl")
        traces[name] = _trace(directory / f"{name}.jsonl")
        if mode != experiment.HYBRID:
            name = f"reference-{mode}"
            records[name] = replay_reference(case, mode, trace_path=directory / f"{name}.jsonl")
            traces[name] = _trace(directory / f"{name}.jsonl")
    assert case == before
    return records, traces


@pytest.mark.parametrize("mode", ["actual_node_start", "ideal_commanded_axis"])
def test_old_arms_exactly_replay_previous_reference_physics_and_commands(mode, mixed_replays):
    records, traces = mixed_replays
    original, observed = records[f"reference-{mode}"], records[f"origin-{mode}"]
    assert _existing_measures(observed, original) == _existing_measures(original, original)
    old_rows, new_rows = traces[f"reference-{mode}"], traces[f"origin-{mode}"]
    assert len(old_rows) == len(new_rows)
    assert [_existing_measures(new, old) for new, old in zip(new_rows, old_rows)] == old_rows


def test_hybrid_uses_only_walking_correction_with_zero_residual_and_original_lifecycle(mixed_replays):
    records, traces = mixed_replays
    for mode in experiment.MODES:
        record = records[f"origin-{mode}"]
        assert record["residual_enabled"] is False and record["PPO_training"] is False
        assert [node["skill"] for node in record["nodes"]] == ["stand", "walk_forward", "turn", "walk_forward", "stop"]
        assert record["memory_reset_count"] == 4
        assert [node["memory_reset_count"] for node in record["nodes"]] == [1, 1, 1, 1, 0]
        for row in traces[f"origin-{mode}"]:
            assert row["action"] == row["residual"] == [0.0, 0.0, 0.0]
            if row["skill"] != "walk_forward":
                assert row["applied_command"] == row["nominal_command"]
    first = {mode: next(row for row in traces[f"origin-{mode}"] if row["skill"] == "walk_forward") for mode in experiment.MODES}
    actual, hybrid, full = (first[mode] for mode in experiment.MODES)
    assert hybrid["walking_reference"]["control_origin"] == hybrid["walking_reference"]["measurement_origin"]
    assert hybrid["walking_reference"]["control_heading_rad"] == full["walking_reference"]["control_heading_rad"]
    assert hybrid["walking_reference"]["control_origin"] != full["walking_reference"]["control_origin"]
    assert hybrid["applied_command"] != actual["applied_command"]
    assert hybrid["applied_command"] != full["applied_command"]


def test_hybrid_local_measurements_and_gold_envelopes_still_use_actual_start(mixed_replays):
    records, _ = mixed_replays
    for node in records[f"origin-{experiment.HYBRID}"]["nodes"]:
        if node["skill"] != "walk_forward":
            continue
        start, end = RobotState.from_dict(node["start_state"]), RobotState.from_dict(node["end_state"])
        local = MissionFrame.from_state(start)
        forward, lateral = local.project(end.base_position)
        heading = local.heading_error_deg(end)
        assert node["forward_progress_m"] == pytest.approx(forward, abs=1e-14)
        assert node["lateral_drift_m"] == pytest.approx(lateral, abs=1e-14)
        assert node["heading_error_deg"] == pytest.approx(heading, abs=1e-14)
        distance = node["parameters"]["target_distance_m"]
        expected = evaluate_walk_task({"absolute_distance_error_m": abs(forward - distance),
            "lateral_drift_m": lateral, "heading_error_deg": heading,
            "completion_sim_time_s": node["duration_s"]}, distance, physical=node["physical_success"])
        assert node["envelope"] == expected
        assert node["walking_reference"]["measurement_origin"] == list(start.base_position)
        assert node["walking_reference"]["measurement_heading_rad"] == local.initial_yaw_rad
        assert node["walking_reference"]["control_origin"] == list(start.base_position)


def test_hybrid_preserves_base_policy_gains_robot_and_registered_skill_classes(physical_policy):
    original = ReferenceRunner(PRIMITIVE_CASES[0], "actual_node_start")
    hybrid = OriginRunner(PRIMITIVE_CASES[0], experiment.HYBRID)
    try:
        assert hybrid.base.config == original.base.config
        assert hybrid.robot == original.robot and hybrid.sim.timestep == original.sim.timestep == .002
        assert hybrid.correction.config == original.correction.config
        assert type(hybrid.correction.delegate) is PathCorrectionPolicy
        assert hybrid.router.skill_names == original.router.skill_names
        for name, cls in {"stand": StandSkill, "walk_forward": WalkForwardSkill, "turn": TurnSkill, "stop": StopSkill}.items():
            assert type(hybrid.router.get(name)) is type(original.router.get(name)) is cls
        assert hybrid.control is None and hybrid.treatment == "deterministic_correction"
    finally:
        original.close()
        hybrid.close()


@pytest.mark.parametrize("case", PRIMITIVE_CASES, ids=lambda case: case["id"])
def test_all_primitives_keep_exact_frozen_physics_in_all_three_arms(case, physical_policy):
    before = copy.deepcopy(case)
    original = replay_case(case, "deterministic_correction")
    for mode in experiment.MODES:
        observed = replay_origin(case, mode)
        assert _existing_measures(observed, original) == _existing_measures(original, original)
        assert observed["task_success"] == original["task_success"]
        assert observed["physical_success"] == original["physical_success"]
    assert case == before
