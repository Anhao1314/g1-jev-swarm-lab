"""Non-physical checks for the T0 residual-RL command and protocol contract."""

import ast

from pathlib import Path

import numpy as np
import pytest
import yaml

from g1swarm.residual_rl.contract import (
    BoundaryKind,
    ResidualContractError,
    apply_yaw_residual,
    classify_boundary,
)


def _config() -> dict:
    path = Path(__file__).parents[1] / "configs" / "experiments" / "g1_ppo_residual_t0.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_zero_residual_preserves_deterministic_command_exactly() -> None:
    command = np.array([0.5, 0.0, -0.27], dtype=np.float64)
    applied, sample = apply_yaw_residual(command, np.array([0.0]), active=True)
    np.testing.assert_array_equal(applied, command)
    assert sample.applied_delta_yaw_radps == 0.0
    assert not sample.total_saturated


def test_disabled_residual_preserves_all_command_components() -> None:
    command = np.array([0.5, 0.0, 0.18], dtype=np.float64)
    applied, sample = apply_yaw_residual(command, np.array([1.0]), active=False)
    np.testing.assert_array_equal(applied, command)
    assert sample.applied_normalized_action == 0.0
    assert sample.applied_delta_yaw_radps == 0.0


def test_active_residual_changes_only_yaw_and_respects_both_bounds() -> None:
    command = np.array([0.5, 0.0, 0.55], dtype=np.float64)
    applied, sample = apply_yaw_residual(command, np.array([1.0]), active=True)
    np.testing.assert_array_equal(applied[:2], command[:2])
    assert applied[2] == pytest.approx(0.6)
    assert sample.total_saturated
    assert abs(sample.applied_delta_yaw_radps) <= 0.12


@pytest.mark.parametrize(
    ("command", "action"),
    [
        (np.zeros(2), np.zeros(1)),
        (np.zeros(3), np.zeros(2)),
        (np.array([0.0, 0.0, np.nan]), np.zeros(1)),
        (np.zeros(3), np.array([np.inf])),
        (np.zeros(3), np.array([1.0001])),
        (np.array([0.0, 0.0, 0.61]), np.zeros(1)),
        (np.array([0.0, 0.0, 0.6000000000005]), np.zeros(1)),
    ],
)
def test_invalid_command_or_action_fails_closed(command: np.ndarray, action: np.ndarray) -> None:
    with pytest.raises(ResidualContractError):
        apply_yaw_residual(command, action, active=True)


def test_boundary_semantics_keep_invalid_termination_and_truncation_distinct() -> None:
    assert classify_boundary(invalid_transition=True).kind is BoundaryKind.INVALID
    assert classify_boundary(physical_failure=True, external_budget_exhausted=True).kind is BoundaryKind.TERMINATED
    success = classify_boundary(target_reached=True, task_success=True)
    assert success.kind is BoundaryKind.TERMINATED
    assert success.reason == "task_success"
    outside = classify_boundary(target_reached=True, task_success=False)
    assert outside.kind is BoundaryKind.TERMINATED
    assert outside.reason == "target_reached_outside_envelope"
    assert classify_boundary(task_success=True).kind is BoundaryKind.INVALID
    assert classify_boundary(task_horizon_exhausted=True).kind is BoundaryKind.TERMINATED
    assert classify_boundary(external_budget_exhausted=True).kind is BoundaryKind.TRUNCATED
    assert classify_boundary(external_interrupt=True).kind is BoundaryKind.TRUNCATED
    assert classify_boundary().kind is BoundaryKind.CONTINUE


def test_machine_readable_t0_contract_preserves_scope_and_isolation() -> None:
    config = _config()
    assert config["status"] == "NO_TRAINING_PERFORMED"
    assert config["action"]["shape"] == [1]
    assert config["action"]["residual_limit_radps"] == 0.12
    assert config["frozen_foundation"]["total_yaw_limit_radps"] == 0.6
    assert config["action"]["prohibited_outputs"] == [
        "joint_torque",
        "joint_target",
        "base_pose",
        "PD_gain",
        "vx_residual",
        "vy_residual",
    ]
    assert config["observation"]["shape"] == [
        len(config["observation"]["features_in_order"])
    ]
    isolation = config["data_isolation"]
    assert isolation["historical_seen_regression"]["may_be_called_unseen"] is False
    assert isolation["unseen_test"]["tuning_or_checkpoint_selection"] == "forbidden"
    assert "M2.6A unseen cases or state" in isolation["forbidden_sources"]
    assert config["t0_execution"] == {
        "physics_steps": 0,
        "policy_loads": 0,
        "optimizer_updates": 0,
        "checkpoint_writes": 0,
        "gpu_calls": 0,
        "status": "NO_TRAINING_PERFORMED",
    }


def test_contract_module_has_no_runtime_or_training_imports() -> None:
    path = Path(__file__).parents[1] / "src" / "g1swarm" / "residual_rl" / "contract.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= {"__future__", "dataclasses", "enum", "numpy"}
    assert roots.isdisjoint({"gymnasium", "mujoco", "stable_baselines3", "torch"})
