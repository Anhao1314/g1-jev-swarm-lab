"""Physical and contract checks for the command-residual training environment.

These tests execute the official policy in real MuJoCo. A direct original-skill
replay provides an independent lifecycle reference; no simulated toy dynamics
or replacement task thresholds are used.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from g1swarm.config import build_controller, build_simulation, load_yaml
from g1swarm.paths import repo_root
from g1swarm.skills import (
    SkillContext, SkillRequest, SkillRouter, StandSkill, StopSkill, TurnSkill,
    WalkForwardSkill,
)
from g1swarm.transition_learning.env import TransitionEnv, replay_case


def _stand(duration=0.4):
    return {"skill": "stand", "parameters": {"duration_s": duration}}


def _walk(distance=1.3):
    return {"skill": "walk_forward", "parameters": {
        "target_distance_m": distance, "tolerance_m": 0.2,
        "speed_mps": 0.5, "max_duration_s": 15.0,
    }}


def _turn(angle=20.0):
    return {"skill": "turn", "parameters": {
        "target_angle_deg": angle, "tolerance_deg": 15.0,
        "yaw_rate_radps": 0.5, "max_duration_s": 10.0, "settle_s": 0.5,
    }}


def _stop():
    return {"skill": "stop", "parameters": {
        "window_s": 1.0, "speed_threshold_mps": 0.10, "max_duration_s": 4.0,
    }}


def _case(name, nodes, group="transition"):
    return {"id": name, "group": group, "transition": name, "nodes": nodes}


PAIRED_CASES = (
    _case("walk_to_turn", [_walk(0.6), _turn()]),
    _case("turn_to_walk", [_turn(-20.0), _walk()]),
    _case("walk_to_stop", [_walk(0.6), _stop()]),
    _case("stand_to_walk", [_stand(), _walk()]),
)


def _physical(value):
    """Keep all measured outcomes and drop only nonphysical metadata."""
    if isinstance(value, dict):
        return {key: _physical(item) for key, item in value.items()
                if key not in {"treatment", "wall_time_s", "elapsed_wall_time_s"}}
    if isinstance(value, list):
        return [_physical(item) for item in value]
    return value


def _trace(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module", autouse=True)
def _real_policy(locomotion_robot):
    policy = repo_root() / locomotion_robot["controller"]["policy_path"]
    if not policy.is_file():
        pytest.skip("Official locomotion checkpoint is unavailable")
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def zero_pairs():
    records = {}
    for case in PAIRED_CASES:
        deterministic = replay_case(case, "deterministic_correction")
        zero = replay_case(case, "learned", policy=lambda obs: np.zeros(3))
        records[case["id"]] = (deterministic, zero)
    return records


@pytest.mark.parametrize("case", PAIRED_CASES, ids=lambda case: case["id"])
def test_zero_residual_has_identical_physical_outcomes(case, zero_pairs):
    deterministic, zero = zero_pairs[case["id"]]
    assert len(deterministic["nodes"]) == len(case["nodes"])
    assert _physical(zero) == _physical(deterministic)
    expected_resets = sum(node["skill"] != "stop" for node in case["nodes"])
    assert deterministic["memory_reset_count"] == expected_resets
    assert [node["memory_reset_count"] for node in deterministic["nodes"]] == [
        int(node["skill"] != "stop") for node in case["nodes"]
    ]


class _CountingController:
    """Observe original lifecycle while delegating every control calculation."""

    def __init__(self, controller):
        self.controller = controller
        self.resets = 0

    def reset(self):
        self.resets += 1
        self.controller.reset()

    def __getattr__(self, name):
        return getattr(self.controller, name)


def test_frozen_baseline_matches_direct_original_skill_replay():
    case = PAIRED_CASES[0]
    measured = replay_case(case, "frozen_baseline")
    robot = load_yaml("configs/robot/g1_locomotion_12dof.yaml")
    simulation = build_simulation(robot, seed=0)
    controller = _CountingController(build_controller(robot))
    simulation.set_base_state(yaw_rad=0.0)
    context = SkillContext(simulation=simulation, controller=controller,
                           robot_config=robot, max_steps=600000, seed=0)
    router = SkillRouter([StandSkill(), WalkForwardSkill(), TurnSkill(), StopSkill()])
    try:
        for index, node in enumerate(case["nodes"]):
            result = router.execute(SkillRequest(node["skill"], node["parameters"]), context)
            observed = measured["nodes"][index]
            assert observed["status"] == result.status.value
            assert observed["simulation_steps"] == result.steps
            assert observed["end_state"] == simulation.get_robot_state().to_dict()
        assert measured["memory_reset_count"] == controller.resets == 2
        assert measured["final_state"] == simulation.get_robot_state().to_dict()
    finally:
        simulation.close()


def test_original_walk_status_does_not_hide_frozen_envelope_failure():
    # This is a previously measured open-loop failure region. Reaching the
    # distance remains a skill SUCCESS, while the unchanged corridor fails.
    case = _case("open-loop-drift-negative", [_walk(6.0)], group="primitive")
    result = replay_case(case, "frozen_baseline")
    node = result["nodes"][0]
    assert node["status"] == "SUCCESS"
    assert result["physical_success"]
    assert not result["task_success"]
    assert "EXCESSIVE_DRIFT" in node["violations"]
    assert "EXCESSIVE_DRIFT" in result["failure_taxonomy"]
    expected_lateral_limit = max(0.35, 0.07 * 6.0)
    assert abs(node["lateral_drift_m"]) > expected_lateral_limit
    assert node["envelope"]["nominal_envelope"]["limits"]["lateral_drift_max_m"] == expected_lateral_limit


def test_residual_changes_real_trajectory_only_in_bounded_transition_window(tmp_path, zero_pairs):
    case = PAIRED_CASES[3]
    trace_path = tmp_path / "bounded-command.jsonl"
    altered = replay_case(case, "learned", policy=lambda obs: np.array([2.0, -2.0, 2.0]),
                          trace_path=trace_path)
    deterministic = zero_pairs[case["id"]][0]
    assert _physical(altered["nodes"][0]) == _physical(deterministic["nodes"][0])
    assert altered["final_state"] != deterministic["final_state"]
    rows = _trace(trace_path)
    active = [row for row in rows if row["active"]]
    assert active, "A requested transition must receive real policy commands"
    assert any(row["elapsed_s"] >= 2.0 and row["node_index"] == 1 for row in rows)
    for row in rows:
        residual = np.asarray(row["residual"])
        np.testing.assert_allclose(np.asarray(row["applied_command"])
                                   - np.asarray(row["deterministic_command"]), residual,
                                   rtol=0, atol=1e-12)
        assert np.all(np.abs(residual) <= np.array([0.1, 0.06, 0.12]) + 1e-12)
        assert abs(row["applied_command"][2]) <= 0.6 + 1e-12
        if row["active"]:
            assert row["eligible"] and row["node_index"] == 1
            assert row["skill"] == "walk_forward" and row["previous_skill"] == "stand"
            assert row["elapsed_s"] < 2.0
            np.testing.assert_array_equal(row["action"], [1.0, -1.0, 1.0])
        else:
            np.testing.assert_array_equal(residual, np.zeros(3))


@pytest.mark.parametrize("node", [_stand(), _walk(0.6), _turn(), _stop()],
                         ids=lambda node: node["skill"])
def test_primitive_replay_cannot_receive_learned_action(node, tmp_path):
    case = _case("primitive-" + node["skill"], [node], group="primitive")

    def forbidden_action(observation):
        pytest.fail("Primitive replay called the transition residual policy")

    path = tmp_path / "primitive.jsonl"
    measured = replay_case(case, "learned", policy=forbidden_action, trace_path=path)
    reference = replay_case(case, "deterministic_correction")
    assert _physical(measured) == _physical(reference)
    for row in _trace(path):
        assert not row["eligible"] and not row["active"]
        np.testing.assert_array_equal(row["residual"], np.zeros(3))


def test_unrequested_transition_cannot_receive_residual(tmp_path):
    case = _case("stand_to_stop", [_stand(), _stop()])

    def forbidden_action(observation):
        pytest.fail("Unrequested transition called the residual policy")

    path = tmp_path / "unrequested.jsonl"
    learned = replay_case(case, "learned", policy=forbidden_action, trace_path=path)
    reference = replay_case(case, "deterministic_correction")
    assert len(learned["nodes"]) == 2
    assert _physical(learned) == _physical(reference)
    assert all(not row["eligible"] and not row["active"] for row in _trace(path))


def test_gym_episode_is_finite_matches_zero_replay_and_closes_worker(tmp_path, zero_pairs):
    case = PAIRED_CASES[3]
    log_path = tmp_path / "episodes.jsonl"
    env = TransitionEnv([case], treatment="learned", seed=17, log_path=log_path)
    try:
        observation, info = env.reset(seed=17)
        assert info["case_id"] == case["id"]
        assert env.observation_space.contains(observation)
        assert observation.shape == (61,)
        assert np.isfinite(observation).all()
        with pytest.raises(ValueError):
            env.step(np.array([np.nan, 0, 0]))
        with pytest.raises(ValueError):
            env.step(np.zeros(4))
        for _ in range(200):
            observation, reward, terminated, truncated, info = env.step(np.zeros(3))
            assert env.observation_space.contains(observation)
            assert math.isfinite(reward)
            assert not truncated
            if terminated:
                record = info["episode_record"]
                break
        else:
            pytest.fail("A short physical transition did not terminate")
        assert _physical(record) == _physical(zero_pairs[case["id"]][1])
        assert [json.loads(line) for line in log_path.read_text().splitlines()] == [record]
        with pytest.raises(RuntimeError, match="reset required"):
            env.step(np.zeros(3))
    finally:
        env.close()
    assert env.thread is None


def test_replay_preserves_frozen_controller_policy_and_contract_bytes():
    paths = [
        "third_party/unitree_rl_gym/deploy/pre_train/g1/motion.pt",
        "configs/robot/g1_locomotion_12dof.yaml",
        "configs/experiments/g1_closed_loop_correction_001.yaml",
        "src/g1swarm/control/g1_locomotion.py",
        "src/g1swarm/control/path_correction.py",
        "src/g1swarm/skills/basic.py",
        "src/g1swarm/skills/contract.py",
        "src/g1swarm/boundary/envelope.py",
    ]
    def hashes():
        return {path: hashlib.sha256((repo_root() / path).read_bytes()).hexdigest()
                for path in paths}
    before = hashes()
    assert before[paths[0]] == "cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d"
    replay_case(PAIRED_CASES[0], "learned", policy=lambda obs: np.array([0.1, 0, -0.1]))
    assert hashes() == before
