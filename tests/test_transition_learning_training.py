"""Offline integrity/checkpoint tests; no G1 physics or PPO learning runs."""

from __future__ import annotations

import hashlib
import json

import gymnasium as gym
import numpy as np
import pytest
import torch
from stable_baselines3 import PPO

from g1swarm.transition_learning import training


class SyntheticContractEnv(gym.Env):
    observation_space = gym.spaces.Box(-1, 1, shape=(4,), dtype=np.float32)
    action_space = gym.spaces.Box(-1, 1, shape=(3,), dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        return np.zeros(4, dtype=np.float32), {}

    def step(self, action):
        raise AssertionError("checkpoint tests must not collect training samples")


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_real_checkpoint_roundtrip_and_no_overwrite(tmp_path):
    torch.set_num_threads(1)
    model = PPO(
        "MlpPolicy", SyntheticContractEnv(), n_steps=8, batch_size=4,
        seed=53, device="cpu", policy_kwargs={"net_arch": [8, 8]},
    )
    receipt = training._save_checkpoint(model, tmp_path, "initial")
    reloaded = PPO.load(receipt["checkpoint"], device="cpu")
    assert training.policy_weight_sha(reloaded) == training.policy_weight_sha(model)
    obs = np.array([0.1, 0.2, -0.3, 0.4], dtype=np.float32)
    assert np.array_equal(model.predict(obs, deterministic=True)[0],
                          reloaded.predict(obs, deterministic=True)[0])
    with pytest.raises(FileExistsError):
        training._save_checkpoint(model, tmp_path, "initial")
    assert receipt["file_sha256"] == hashlib.sha256(
        (tmp_path / "initial.zip").read_bytes()
    ).hexdigest()


def test_tensor_hash_detects_parameter_tampering():
    model = PPO(
        "MlpPolicy", SyntheticContractEnv(), n_steps=8, batch_size=4,
        seed=59, device="cpu", policy_kwargs={"net_arch": [8, 8]},
    )
    before = training.policy_weight_sha(model)
    with torch.no_grad():
        next(model.policy.parameters()).add_(0.25)
    assert training.policy_weight_sha(model) != before


def test_replay_identity_keeps_physical_path_error():
    a = {"wall_time_s": 1.0, "trace_path": "a", "ideal_path_error_m": 0.2,
         "nodes": [{"elapsed_wall_time_s": 1.0, "heading_error_deg": 3.0}]}
    b = {"wall_time_s": 8.0, "trace_path": "b", "ideal_path_error_m": 0.2,
         "nodes": [{"elapsed_wall_time_s": 8.0, "heading_error_deg": 3.0}]}
    assert training._canonical_replay(a) == training._canonical_replay(b)
    b["ideal_path_error_m"] = 0.4
    assert training._canonical_replay(a) != training._canonical_replay(b)


def test_ppo_nested_frozen_policy_options_are_honored():
    supplied = {"net_arch": [32, 16], "log_std_init": -0.75}
    options = training._ppo_options({"ppo": {"policy_kwargs": supplied}}, 11)
    assert options["policy_kwargs"] == supplied
    assert options["seed"] == 11 and options["device"] == "cpu"
    assert "log_std_init" not in training._ppo_options({"ppo": {}}, 11)["policy_kwargs"]


def test_invalid_minibatch_rollout_contract_rejected():
    with pytest.raises(ValueError, match="divide"):
        training._ppo_options({"ppo": {"n_steps": 512, "batch_size": 63}}, 11)


def test_baseline_freeze_detects_source_drift(tmp_path, monkeypatch):
    baseline = tmp_path / "base.py"
    baseline.write_bytes(b"frozen base source\n")
    frozen = tmp_path / "freeze.json"
    _write(frozen, {"files": {"base.py": {
        "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
        "bytes": baseline.stat().st_size,
    }}})
    monkeypatch.setattr(training, "BASELINE_FREEZE", "freeze.json")
    monkeypatch.setattr(training, "resolve_repo_path", lambda path: tmp_path / path)
    assert training.verify_baseline_freeze()["baseline_drift"] is False
    baseline.write_bytes(b"changed base source\n")
    with pytest.raises(RuntimeError, match="baseline drift"):
        training.verify_baseline_freeze()


def test_baseline_freeze_missing_file_is_not_silently_dropped(tmp_path, monkeypatch):
    frozen = tmp_path / "freeze.json"
    _write(frozen, {"files": {"missing.py": {"sha256": "0" * 64, "bytes": 2}}})
    monkeypatch.setattr(training, "BASELINE_FREEZE", "freeze.json")
    monkeypatch.setattr(training, "resolve_repo_path", lambda path: tmp_path / path)
    with pytest.raises(RuntimeError, match="MISSING"):
        training.verify_baseline_freeze()


def _case_freeze(tmp_path, monkeypatch):
    manifest = {
        "train": list(training.TRAIN_CASES), "evaluation": list(training.EVAL_CASES),
        "primitive": list(training.PRIMITIVE_CASES), "sequence": list(training.SEQUENCE_CASES),
    }
    manifest = json.loads(json.dumps(manifest))
    path = tmp_path / "case_manifest.json"
    _write(path, manifest)
    monkeypatch.setattr(training, "CASE_MANIFEST", "case_manifest.json")
    monkeypatch.setattr(training, "resolve_repo_path", lambda value: tmp_path / value)
    return path, manifest, {"case_manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_case_freeze_rejects_tampered_split_bytes(tmp_path, monkeypatch):
    path, manifest, protocol = _case_freeze(tmp_path, monkeypatch)
    assert training.verify_case_manifest(protocol)["verified_case_counts"]["train"] == 12
    manifest["evaluation"][0]["initial_yaw_deg"] = 999
    _write(path, manifest)
    with pytest.raises(RuntimeError, match="manifest hash mismatch"):
        training.verify_case_manifest(protocol)


def test_case_freeze_rejects_live_collection_drift(tmp_path, monkeypatch):
    _, _, protocol = _case_freeze(tmp_path, monkeypatch)
    monkeypatch.setattr(training, "TRAIN_CASES", training.TRAIN_CASES[1:])
    with pytest.raises(RuntimeError, match="live train case collection differs"):
        training.verify_case_manifest(protocol)


@pytest.mark.parametrize("frozen", [None, False, "true", 1])
def test_protocol_requires_explicit_boolean_freeze(tmp_path, monkeypatch, frozen):
    protocol = tmp_path / "protocol.json"
    _write(protocol, {"frozen": frozen})
    monkeypatch.setattr(training, "resolve_repo_path", lambda path: path)
    with pytest.raises(ValueError, match="frozen pilot protocol"):
        training._prepare(protocol, tmp_path / "output", "test")
    assert not (tmp_path / "output").exists()


def test_campaign_directory_cannot_overwrite_existing_evidence(tmp_path, monkeypatch):
    protocol = tmp_path / "protocol.json"
    _write(protocol, {"frozen": True, "baseline_freeze_sha256": "same"})
    destination = tmp_path / "output"
    destination.mkdir()
    sentinel = destination / "sentinel.json"
    sentinel.write_bytes(b"original evidence")
    monkeypatch.setattr(training, "resolve_repo_path", lambda path: path)
    monkeypatch.setattr(training, "verify_baseline_freeze", lambda: {"baseline_freeze_sha256": "same"})
    monkeypatch.setattr(training, "verify_case_manifest", lambda protocol: {})
    with pytest.raises(FileExistsError):
        training._prepare(protocol, destination, "test")
    assert sentinel.read_bytes() == b"original evidence"


def test_baseline_manifest_cannot_be_replaced_even_with_self_consistent_files(tmp_path, monkeypatch):
    protocol = tmp_path / "protocol.json"
    _write(protocol, {"frozen": True, "baseline_freeze_sha256": "original"})
    monkeypatch.setattr(training, "resolve_repo_path", lambda path: path)
    monkeypatch.setattr(training, "verify_baseline_freeze", lambda: {
        "baseline_freeze_sha256": "replacement", "baseline_drift": False,
    })
    with pytest.raises(RuntimeError, match="frozen protocol pin"):
        training._prepare(protocol, tmp_path / "output", "test")
    assert not (tmp_path / "output").exists()


def test_frozen_training_budget_cannot_be_extended(tmp_path, monkeypatch):
    protocol = {"ppo": {"n_steps": 512}, "train_timesteps": 8192}
    monkeypatch.setattr(training, "_prepare", lambda *args: (
        tmp_path / "protocol.json", tmp_path, protocol, {},
    ))
    with pytest.raises(ValueError, match="frozen pilot budget"):
        training._train_campaign(
            seed=11, protocol_path="unused", output_dir=tmp_path,
            smoke=False, timesteps=16384,
        )


def test_held_out_evaluation_rejects_nonfinal_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "_prepare", lambda *args: (
        tmp_path / "protocol.json", tmp_path, {"train_timesteps": 8192}, {},
    ))
    monkeypatch.setattr(training, "resolve_repo_path", lambda path: path)
    with pytest.raises(ValueError, match="fixed final"):
        training._run_evaluation(
            protocol_path="unused", output_dir=tmp_path,
            checkpoints=[tmp_path / "step-00002048.zip"], include_baselines=False,
        )


def test_held_out_evaluation_rejects_provenance_mismatch(tmp_path, monkeypatch):
    checkpoint = tmp_path / "final.zip"
    checkpoint.write_bytes(b"checkpoint bytes")
    _write(tmp_path / "training_summary.json", {
        "status": "COMPLETE", "num_timesteps": 8192,
        "provenance": {"protocol_sha256": "different"},
        "final_checkpoint": {"file_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest()},
    })
    monkeypatch.setattr(training, "_prepare", lambda *args: (
        tmp_path / "protocol.json", tmp_path, {"train_timesteps": 8192},
        {"protocol_sha256": "current"},
    ))
    monkeypatch.setattr(training, "resolve_repo_path", lambda path: path)
    with pytest.raises(ValueError, match="provenance/budget"):
        training._run_evaluation(
            protocol_path="unused", output_dir=tmp_path,
            checkpoints=[checkpoint], include_baselines=False,
        )
