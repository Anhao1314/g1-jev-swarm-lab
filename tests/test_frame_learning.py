"""Same-frame residual contracts and one-rollout original-pilot reproduction.

All physics inputs here are historical training/primitive cases or local test
stimuli. Fresh held-out cases are inspected structurally, never simulated.
The tiny PPO tests use temporary artifacts and are not formal campaigns.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import runpy
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.logger import configure

from g1swarm.frame_learning.env import FrameEnv, FrameRunner, replay_frame
from g1swarm.heading_alignment.experiment import HeadingCorrectionPolicy, replay_heading
from g1swarm.paths import repo_root
from g1swarm.segmentation.mission import MissionFrame
from g1swarm.transition_learning import env as original_env
from g1swarm.transition_learning.cases import TRAIN_CASES, PRIMITIVE_CASES
from g1swarm.transition_learning.env import EpisodeRunner, TransitionEnv
from g1swarm.transition_learning.training import (
    EvidenceCallback, _canonical_replay, _ppo_options, _save_checkpoint, policy_weight_sha,
)

ALPHAS = (0.0, .5)
PAIR_CASES = tuple(next(case for case in TRAIN_CASES if case["transition"] == family)
                   for family in ("walk_to_turn", "turn_to_walk", "walk_to_stop", "stand_to_walk"))


def _physics(value):
    if isinstance(value, dict):
        excluded = {"treatment", "treatment_label", "residual_enabled", "PPO_training",
                    "learned_policy_configured", "policy_decision_calls", "active"}
        return {key: _physics(item) for key, item in value.items()
                if key not in excluded and "wall" not in key}
    if isinstance(value, list):
        return [_physics(item) for item in value]
    return value


def _trace(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _original_fields(value, original):
    """Project new annotations away at every depth, retaining old measurements."""
    if isinstance(original, dict):
        return {key: _original_fields(value[key], item) for key, item in original.items()}
    if isinstance(original, list):
        assert len(value) == len(original)
        return [_original_fields(item, prior) for item, prior in zip(value, original)]
    return value


@pytest.fixture(scope="module", autouse=True)
def physical_policy(locomotion_robot):
    if not (repo_root() / locomotion_robot["controller"]["policy_path"]).is_file():
        pytest.skip("Official locomotion policy is unavailable")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.mark.parametrize("alpha", ALPHAS)
@pytest.mark.parametrize("case", PAIR_CASES, ids=lambda case: case["transition"])
def test_zero_actor_has_exact_own_frame_control_physics_and_commands(alpha, case, tmp_path):
    before = copy.deepcopy(case)
    control_path, learned_path = tmp_path / "control.jsonl", tmp_path / "zero-actor.jsonl"
    control = replay_frame(case, alpha, trace_path=control_path)
    observations = []
    def zero(observation):
        observations.append(observation.copy())
        return np.zeros(3)
    learned = replay_frame(case, alpha, policy=zero, trace_path=learned_path)
    assert _physics(learned) == _physics(control)
    assert _physics(_trace(learned_path)) == _physics(_trace(control_path))
    assert learned["residual_enabled"] is True and control["residual_enabled"] is False
    assert learned["PPO_training"] is control["PPO_training"] is False
    assert learned["learned_policy_configured"] is True
    assert control["learned_policy_configured"] is False and control["policy_decision_calls"] == 0
    assert learned["policy_decision_calls"] == len(observations) > 0
    assert all(observation.shape == (61,) and np.isfinite(observation).all() for observation in observations)
    assert case == before


@pytest.mark.parametrize("alpha", ALPHAS)
def test_deterministic_controls_replay_frozen_heading_arms(alpha):
    case = TRAIN_CASES[10]
    expected = replay_heading(case, alpha)
    observed = replay_frame(case, alpha)
    expected = {**expected, "learned_policy_configured": False, "policy_decision_calls": 0}
    assert _physics(observed) == _physics(expected)


@pytest.mark.parametrize("case", PRIMITIVE_CASES, ids=lambda case: case["id"])
def test_all_primitives_cannot_invoke_configured_residual_in_either_frame(case, tmp_path):
    def forbidden(observation):
        pytest.fail("A primitive invoked the transition residual actor")
    for alpha in ALPHAS:
        path = tmp_path / f"primitive-alpha{alpha}.jsonl"
        control = replay_frame(case, alpha)
        learned = replay_frame(case, alpha, policy=forbidden, trace_path=path)
        assert _physics(learned) == _physics(control)
        assert learned["learned_policy_configured"] is True
        assert learned["policy_decision_calls"] == 0
        assert learned["PPO_training"] is False
        assert all(row["residual"] == [0.0, 0.0, 0.0] and not row["active"] for row in _trace(path))


@pytest.mark.parametrize("alpha", ALPHAS)
def test_nonzero_actor_is_bounded_and_masked_after_original_window(alpha, tmp_path):
    case = TRAIN_CASES[10]
    path = tmp_path / f"nonzero-alpha{alpha}.jsonl"
    record = replay_frame(case, alpha, policy=lambda observation: np.array([2.0, -2.0, 2.0]), trace_path=path)
    rows = _trace(path)
    assert any(row["active"] for row in rows)
    assert any(row["eligible"] and row["elapsed_s"] >= 2.0 for row in rows)
    for row in rows:
        residual = np.asarray(row["residual"])
        assert np.all(np.abs(residual) <= np.array([.1, .06, .12]) + 1e-12)
        assert abs(row["applied_command"][2]) <= .6 + 1e-12
        np.testing.assert_allclose(np.asarray(row["applied_command"]) - row["deterministic_command"], residual, rtol=0, atol=1e-12)
        if row["active"]:
            assert row["eligible"] and row["elapsed_s"] < 2.0
            assert row["action"] == [1.0, -1.0, 1.0]
        else:
            assert row["residual"] == [0.0, 0.0, 0.0]
    assert record["PPO_training"] is False and record["policy_decision_calls"] > 0


def test_alpha0_env_case_rng_observations_zero_action_and_rewards_match_original():
    original_class = original_env.EpisodeRunner
    old = TransitionEnv(list(TRAIN_CASES), treatment="learned", seed=23)
    new = FrameEnv(list(TRAIN_CASES), alpha=0.0, seed=23)
    try:
        for episode in range(3):
            old_obs, old_info = old.reset(seed=23 if episode == 0 else None)
            new_obs, new_info = new.reset(seed=23 if episode == 0 else None)
            assert old_info == new_info
            np.testing.assert_array_equal(old_obs, new_obs)
            for _ in range(200):
                a = old.step(np.zeros(3))
                b = new.step(np.zeros(3))
                np.testing.assert_array_equal(a[0], b[0])
                assert a[1:4] == b[1:4]
                assert math.isfinite(a[1])
                if a[2]:
                    # Match every original metric, excluding only added frame
                    # annotations and nonphysical context labels.
                    original = _physics(a[4]["episode_record"])
                    observed = _physics(b[4]["episode_record"])
                    assert _original_fields(observed, original) == original
                    assert b[4]["episode_record"]["PPO_training"] is True
                    break
            else:
                pytest.fail("Historical short training transition did not finish")
    finally:
        old.close()
        new.close()
    assert old.thread is new.thread is None
    assert original_env.EpisodeRunner is original_class


@pytest.mark.parametrize("alpha", ALPHAS)
def test_reward_is_not_recomputed_by_new_diagnostics_and_partial_tail_survives(alpha, monkeypatch):
    calls = {}
    original = EpisodeRunner.dense_reward
    def counted(runner):
        calls[id(runner)] = calls.get(id(runner), 0) + 1
        return original(runner)
    monkeypatch.setattr(EpisodeRunner, "dense_reward", counted)
    env = FrameEnv([TRAIN_CASES[10]], alpha=alpha, seed=31)
    try:
        env.reset(seed=31)
        runner_id = id(env.runner)
        env.step(np.array([.1, -.2, .3]))
        tail = env.snapshot()
        assert tail["status"] == "BUDGET_INTERRUPTED_NOT_SCORED"
        assert tail["case_id"] == TRAIN_CASES[10]["id"]
        assert tail["state"]["simulation_time"] > 0
        steps = 1
        for _ in range(200):
            _, _, done, truncated, info = env.step(np.array([-.1, .2, -.3]))
            steps += 1
            assert not truncated
            if done:
                assert calls[runner_id] == steps + 1
                assert info["episode_record"]["policy_decision_calls"] == steps
                assert env.snapshot() is None
                break
        else:
            pytest.fail("Historical short training transition did not finish")
    finally:
        env.close()
    assert env.thread is None


def test_midpoint_uses_wrapped_heading_and_original_actual_start_origin():
    runner = FrameRunner(TRAIN_CASES[9], .5)
    try:
        assert type(runner.correction) is HeadingCorrectionPolicy
        assert runner.correction.config.k_heading == 1.5 and runner.correction.config.k_lateral == 1.0
        assert runner.correction.config.max_yaw_rate_radps == .6 and runner.correction.config.deadband_radps == .01
        runner.planned_heading = math.radians(-179.0)
        runner.planned_origin = np.array([8.0, 9.0])
        local = MissionFrame((.2, .3, .78), math.radians(179.0))
        selected = runner.correction.selected_frame(local)
        assert selected.initial_position == local.initial_position
        assert math.degrees(selected.initial_yaw_rad) == pytest.approx(180.0, abs=1e-12)
    finally:
        runner.close()


@pytest.mark.parametrize("alpha", [1.0, .4, .6, math.nan, math.inf, -math.inf, True, False])
def test_unlisted_frame_alpha_is_rejected_before_assets(alpha, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid alpha reached robot construction")
    monkeypatch.setattr(EpisodeRunner, "__init__", forbidden)
    with pytest.raises(ValueError):
        FrameRunner(TRAIN_CASES[0], alpha)
    with pytest.raises(ValueError):
        FrameEnv(list(TRAIN_CASES), alpha)


def _adam_steps(model):
    return sorted(set(int(state["step"].item()) for state in model.policy.optimizer.state.values() if "step" in state))


def test_real_one_rollout_ppo_alpha0_repeats_old_optimization_and_checkpoint_physics(tmp_path):
    protocol = json.loads((repo_root() / "experiments/phase3a/transition_learning_001/protocol.json").read_text())
    summaries = []
    trained = []
    for label, factory in [("original", lambda: TransitionEnv(list(TRAIN_CASES), treatment="learned", seed=101)),
                           ("new-alpha0", lambda: FrameEnv(list(TRAIN_CASES), alpha=0.0, seed=101))]:
        folder = tmp_path / label
        folder.mkdir()
        env = factory()
        try:
            model = PPO("MlpPolicy", env, **_ppo_options(protocol, 101))
            model.set_logger(configure(str(folder / "optimizer_logs"), ["json"]))
            initial = policy_weight_sha(model)
            callback = EvidenceCallback(folder, env, {"scope": "isolated_targeted_test_not_campaign"})
            model.learn(total_timesteps=512, callback=callback, progress_bar=False)
            assert model.num_timesteps == 512 and model._n_updates == 5
            assert _adam_steps(model) == [40]
            assert callback.loss_count == 1 and callback.episode_count > 0
            assert policy_weight_sha(model) != initial
            receipt = _save_checkpoint(model, folder, "isolated-test")
            summaries.append({"initial": initial, "final": policy_weight_sha(model),
                              "updates": _trace(folder / "ppo_updates.jsonl")[0]["losses"],
                              "completed_episodes": callback.episode_count})
            trained.append((model, receipt))
        finally:
            env.close()
        assert env.thread is None
    assert summaries[0] == summaries[1]
    model, receipt = trained[1]
    reloaded = PPO.load(receipt["checkpoint"], device="cpu")
    assert policy_weight_sha(reloaded) == policy_weight_sha(model)
    assert _adam_steps(reloaded) == [40]
    before = replay_frame(TRAIN_CASES[0], 0.0, policy=lambda obs: model.predict(obs, deterministic=True)[0])
    after = replay_frame(TRAIN_CASES[0], 0.0, policy=lambda obs: reloaded.predict(obs, deterministic=True)[0])
    assert _canonical_replay(before) == _canonical_replay(after)
    assert before["PPO_training"] is False and before["policy_decision_calls"] > 0


def _split_helper():
    # run_path defines the pure helpers under <run_path>; main() is not called.
    return runpy.run_path(str(repo_root() / "scripts/freeze_phase3a_frame_learning.py"))


def test_fresh_split_manifest_matches_original_train_and_has_no_historical_physics_tuple_overlap():
    from g1swarm.frame_learning import cases
    from g1swarm.transition_learning.cases import EVAL_CASES, SEQUENCE_CASES
    helper = _split_helper()
    manifest = helper["_case_manifest"](repo_root())
    assert cases.TRAIN_CASES is TRAIN_CASES
    assert manifest["training"] == list(TRAIN_CASES)
    assert manifest["heldout"] == list(cases.HELDOUT_CASES)
    assert manifest["regression"] == list((*EVAL_CASES, *PRIMITIVE_CASES, *SEQUENCE_CASES))
    assert (len(manifest["training"]), len(manifest["heldout"]), len(manifest["regression"])) == (12, 16, 26)
    assert manifest["split_checks"]["train_regression_full_signature_overlap"] == 0
    assert manifest["split_checks"]["train_regression_overlap_ignoring_initial_yaw"] == 0
    assert manifest["split_checks"]["fresh_pair_overlap_with_all_old_adjacent_node_pairs"] == 0
    frozen_path = repo_root() / "experiments/phase3a/frame_residual_learning_001/case_manifest.json"
    assert json.loads(frozen_path.read_text(encoding="utf-8")) == manifest
    assert len(cases.REPEAT_CASE_IDS) == 6
    assert set(cases.REPEAT_CASE_IDS) <= {case["id"] for case in (*cases.HELDOUT_CASES, *cases.REGRESSION_CASES)}


def test_pure_split_guard_rejects_renamed_yaw_changed_copy_of_training_case(monkeypatch):
    helper = _split_helper()
    namespace = helper["_case_manifest"].__globals__
    old_fresh = namespace["HELDOUT_CASES"]
    bad = copy.deepcopy(TRAIN_CASES[0])
    bad["id"] = old_fresh[0]["id"]
    bad["initial_yaw_deg"] = 7.5
    monkeypatch.setitem(namespace, "HELDOUT_CASES", (bad, *old_fresh[1:]))
    with pytest.raises(RuntimeError, match="physics tuples overlap"):
        helper["_case_manifest"](repo_root())


def test_frozen_frame_protocol_preserves_all_pilot_training_settings_and_postlock_schedule():
    helper = _split_helper()
    pilot = json.loads((repo_root() / "experiments/phase3a/transition_learning_001/protocol.json").read_text())
    protocol = json.loads((repo_root() / "experiments/phase3a/frame_residual_learning_001/protocol.json").read_text())
    for key in helper["PRESERVED_KEYS"]:
        assert protocol[key] == pilot[key]
    assert protocol["alphas"] == [0.0, .5]
    assert protocol["train_timesteps"] == 8192 and protocol["seeds"] == [11, 29]
    schedule = protocol["evaluation_schedule"]
    assert schedule["primary_totals"] == {"all_records": 252, "fresh_heldout": 96, "seen_regression": 156}
    assert schedule["heldout_cases_in_tests_preflight_smoke_reload_or_training"] is False
    assert schedule["train_before_fresh"]["actors"] == 4
    assert schedule["separate_repeatability"]["records"] == 36
    assert "All4" in schedule["final_checkpoint_lock"]
