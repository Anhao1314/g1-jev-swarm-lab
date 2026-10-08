"""Fixed heading-strength geometry and original-task replay contracts."""

from __future__ import annotations

import copy
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from g1swarm.boundary.envelope import evaluate_walk_task
from g1swarm.control.path_correction import CorrectionConfig, PathCorrectionPolicy
from g1swarm.heading_alignment import experiment
from g1swarm.heading_alignment.experiment import HeadingCorrectionPolicy, HeadingRunner, replay_heading
from g1swarm.origin_ablation.experiment import OriginRunner, replay_origin
from g1swarm.paths import repo_root
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


@pytest.mark.parametrize("local_deg,planned_deg,expected_deg", [(179., -179., 180.), (-179., 179., -180.)])
def test_midpoint_crosses_pi_on_short_arc_instead_of_unwrapped_zero(local_deg, planned_deg, expected_deg):
    local = MissionFrame(initial_position=(.4, .3, .78), initial_yaw_rad=math.radians(local_deg))
    runner = SimpleNamespace(planned_origin=np.array([9.0, 8.0]), planned_heading=math.radians(planned_deg), index=0)
    policy = HeadingCorrectionPolicy(runner, .5, _policy())
    selected = policy.selected_frame(local)
    assert math.degrees(selected.initial_yaw_rad) == pytest.approx(expected_deg, abs=1e-12)
    assert abs(selected.initial_yaw_rad) > math.radians(179.0)
    assert selected.initial_position == local.initial_position
    assert local.initial_yaw_rad == math.radians(local_deg)


@pytest.mark.parametrize("local_heading,planned_heading,expected", [
    (0.0, math.pi, math.pi / 2), (0.0, -math.pi, -math.pi / 2),
    (math.pi, 0.0, math.pi / 2), (-math.pi, 0.0, -math.pi / 2),
])
def test_antipodal_midpoint_follows_declared_signed_wrap_tie(local_heading, planned_heading, expected):
    local = MissionFrame((.4, .3, .78), local_heading)
    runner = SimpleNamespace(planned_origin=np.zeros(2), planned_heading=planned_heading, index=0)
    selected = HeadingCorrectionPolicy(runner, .5, _policy()).selected_frame(local)
    assert selected.initial_yaw_rad == pytest.approx(expected, abs=1e-14)
    assert selected.initial_position == local.initial_position


@pytest.mark.parametrize("sign", [-1.0, 1.0])
def test_all_alphas_use_frozen_node_start_origin_and_independent_command_formula(sign):
    start = _state(.45, .3 * sign, .3 * sign)
    current = _state(.5, .4 * sign, .35 * sign)
    local = MissionFrame.from_state(start)
    runner = SimpleNamespace(planned_origin=np.array([7.0, 8.0]), planned_heading=.2 * sign, index=0)
    original_origin = runner.planned_origin.copy()
    nominal = np.array([.5, 0.0, 0.0])
    for alpha in experiment.ALPHAS:
        policy = HeadingCorrectionPolicy(runner, alpha, _policy())
        selected = policy.selected_frame(local)
        # This small-angle case has no branch crossing, so linear arithmetic is
        # an independent oracle; the separate pi tests check shortest wrapping.
        expected_heading = local.initial_yaw_rad if alpha == 0.0 else (
            runner.planned_heading if alpha == 1.0 else .25 * sign)
        assert selected.initial_position == start.base_position
        assert selected.initial_position != current.base_position
        assert selected.initial_position[:2] != tuple(runner.planned_origin)
        assert selected.initial_yaw_rad == pytest.approx(expected_heading, abs=1e-14)
        dx, dy = current.base_position[0] - start.base_position[0], current.base_position[1] - start.base_position[1]
        lateral = -math.sin(expected_heading) * dx + math.cos(expected_heading) * dy
        heading_error = .35 * sign - expected_heading
        expected_yaw = -1.5 * heading_error - lateral
        command, sample = policy.compute(current, local, nominal, sim_time_s=1.0)
        assert command == pytest.approx([.5, 0.0, expected_yaw], abs=1e-14)
        assert sample.heading_error_rad == pytest.approx(heading_error, abs=1e-14)
        assert sample.lateral_error_m == pytest.approx(lateral, abs=1e-14)
        assert policy.config == _policy().config
        if alpha == 0.0:
            assert selected is local
        if alpha == 1.0:
            assert selected.initial_yaw_rad == float(runner.planned_heading)
    assert local == MissionFrame.from_state(start)
    assert np.array_equal(runner.planned_origin, original_origin)
    assert nominal.tolist() == [.5, 0.0, 0.0]


@pytest.mark.parametrize("alpha", [.4, .6, -.5, 1.5, math.nan, math.inf, -math.inf, None, True, False])
def test_only_predeclared_finite_alphas_are_allowed_before_asset_load(alpha, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid alpha must fail before constructing the old runner")
    monkeypatch.setattr(OriginRunner, "__init__", forbidden)
    with pytest.raises(ValueError, match="alpha"):
        HeadingRunner(PRIMITIVE_CASES[0], alpha)
    with pytest.raises(ValueError, match="alpha"):
        HeadingCorrectionPolicy(SimpleNamespace(), alpha, _policy())


def test_original_case_sets_and_discrete_alpha_grid_are_unchanged():
    assert experiment.ALPHAS == (0.0, 0.5, 1.0)
    assert experiment.EVAL_CASES is EVAL_CASES
    assert experiment.PRIMITIVE_CASES is PRIMITIVE_CASES
    assert experiment.SEQUENCE_CASES is SEQUENCE_CASES
    manifest = json.loads((repo_root() / experiment.PILOT / "case_manifest.json").read_text(encoding="utf-8"))
    assert manifest["evaluation"] == list(EVAL_CASES)
    assert manifest["primitive"] == list(PRIMITIVE_CASES)
    assert manifest["sequence"] == list(SEQUENCE_CASES)
    assert (len(EVAL_CASES), len(PRIMITIVE_CASES), len(SEQUENCE_CASES)) == (16, 8, 2)


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
        return {key: _existing_measures(value[key], item) for key, item in original.items()
                if "wall" not in key and key not in {"heading_alignment_alpha"}}
    if isinstance(original, list):
        assert len(value) == len(original)
        return [_existing_measures(item, prior) for item, prior in zip(value, original)]
    return value


def _trace(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def mixed_replays(physical_policy, tmp_path_factory):
    directory = tmp_path_factory.mktemp("heading-alignment-tests")
    case = {"id": "heading-test-mixed", "group": "sequence", "transition": "mixed", "nodes": [
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
    for alpha in experiment.ALPHAS:
        key = f"alpha-{alpha}"
        records[key] = replay_heading(case, alpha, trace_path=directory / f"{key}.jsonl")
        traces[key] = _trace(directory / f"{key}.jsonl")
        if alpha in (0.0, 1.0):
            mode = "actual_node_start" if alpha == 0.0 else "actual_origin_ideal_heading"
            key = f"anchor-{alpha}"
            records[key] = replay_origin(case, mode, trace_path=directory / f"{key}.jsonl")
            traces[key] = _trace(directory / f"{key}.jsonl")
    assert case == before
    return records, traces


@pytest.mark.parametrize("alpha", [0.0, 1.0])
def test_endpoints_replay_old_actual_and_hybrid_records_and_commands_exactly(alpha, mixed_replays):
    records, traces = mixed_replays
    original, observed = records[f"anchor-{alpha}"], records[f"alpha-{alpha}"]
    assert _existing_measures(observed, original) == _existing_measures(original, original)
    old_rows, new_rows = traces[f"anchor-{alpha}"], traces[f"alpha-{alpha}"]
    assert len(new_rows) == len(old_rows)
    assert [_existing_measures(new, old) for new, old in zip(new_rows, old_rows)] == old_rows


def test_midpoint_has_constant_node_start_origin_zero_residual_and_original_nonwalk_commands(mixed_replays):
    records, traces = mixed_replays
    record = records["alpha-0.5"]
    assert record["heading_alignment_alpha"] == .5
    assert record["residual_enabled"] is False and record["PPO_training"] is False
    assert record["memory_reset_count"] == 4
    assert [node["memory_reset_count"] for node in record["nodes"]] == [1, 1, 1, 1, 0]
    assert [node["skill"] for node in record["nodes"]] == ["stand", "walk_forward", "turn", "walk_forward", "stop"]
    for row in traces["alpha-0.5"]:
        assert row["action"] == row["residual"] == [0.0, 0.0, 0.0]
        if row["skill"] != "walk_forward":
            assert row["applied_command"] == row["nominal_command"]
            continue
        measured = row["walking_reference"]
        node = record["nodes"][row["node_index"]]
        assert measured["control_origin"] == node["start_state"]["base_position"]
        assert measured["control_origin"] == measured["measurement_origin"]
    starts = {alpha: next(row for row in traces[f"alpha-{alpha}"] if row["skill"] == "walk_forward") for alpha in experiment.ALPHAS}
    h0 = starts[0.0]["walking_reference"]["control_heading_rad"]
    hhalf = starts[0.5]["walking_reference"]["control_heading_rad"]
    h1 = starts[1.0]["walking_reference"]["control_heading_rad"]
    assert hhalf == pytest.approx((h0 + h1) / 2, abs=1e-14)
    assert starts[0.5]["applied_command"] != starts[0.0]["applied_command"]
    assert starts[0.5]["applied_command"] != starts[1.0]["applied_command"]


def test_midpoint_local_measurements_and_original_envelopes_remain_actual_start(mixed_replays):
    records, _ = mixed_replays
    for node in records["alpha-0.5"]["nodes"]:
        if node["skill"] != "walk_forward":
            continue
        start, end = RobotState.from_dict(node["start_state"]), RobotState.from_dict(node["end_state"])
        local = MissionFrame.from_state(start)
        forward, lateral = local.project(end.base_position)
        heading = local.heading_error_deg(end)
        assert node["forward_progress_m"] == pytest.approx(forward, abs=1e-14)
        assert node["lateral_drift_m"] == pytest.approx(lateral, abs=1e-14)
        assert node["heading_error_deg"] == pytest.approx(heading, abs=1e-14)
        expected = evaluate_walk_task({
            "absolute_distance_error_m": abs(forward - node["parameters"]["target_distance_m"]),
            "lateral_drift_m": lateral, "heading_error_deg": heading,
            "completion_sim_time_s": node["duration_s"]},
            node["parameters"]["target_distance_m"], physical=node["physical_success"])
        assert node["envelope"] == expected
        assert node["walking_reference"]["measurement_heading_rad"] == local.initial_yaw_rad
        assert node["walking_reference"]["measurement_origin"] == list(start.base_position)


def test_midpoint_preserves_original_controller_gains_skills_and_context(physical_policy):
    original = OriginRunner(PRIMITIVE_CASES[0], "actual_node_start")
    midpoint = HeadingRunner(PRIMITIVE_CASES[0], .5)
    try:
        assert midpoint.base.config == original.base.config
        assert midpoint.robot == original.robot and midpoint.sim.timestep == original.sim.timestep == .002
        assert midpoint.correction.config == original.correction.config
        assert type(midpoint.correction.delegate) is PathCorrectionPolicy
        assert midpoint.router.skill_names == original.router.skill_names
        for name, cls in {"stand": StandSkill, "walk_forward": WalkForwardSkill, "turn": TurnSkill, "stop": StopSkill}.items():
            assert type(midpoint.router.get(name)) is type(original.router.get(name)) is cls
        assert midpoint.control is None and midpoint.treatment == "deterministic_correction"
    finally:
        original.close()
        midpoint.close()


@pytest.mark.parametrize("case", PRIMITIVE_CASES, ids=lambda case: case["id"])
def test_all_primitives_are_exact_original_physics_for_all_fixed_alphas(case, physical_policy):
    before = copy.deepcopy(case)
    original = replay_case(case, "deterministic_correction")
    for alpha in experiment.ALPHAS:
        observed = replay_heading(case, alpha)
        assert _existing_measures(observed, original) == _existing_measures(original, original)
        assert observed["task_success"] == original["task_success"]
        assert observed["physical_success"] == original["physical_success"]
    assert case == before
