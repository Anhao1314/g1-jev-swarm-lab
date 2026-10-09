"""Pure contracts for the proposed G1 PPO yaw-residual environment.

This module deliberately has no simulator, Torch, policy, or Gymnasium imports.
It pins the narrow command-composition and episode-boundary behavior that T1
must satisfy before any physical step or optimizer update is authorized.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class ResidualContractError(ValueError):
    """A proposed command or episode state violates the T0 contract."""


@dataclass(frozen=True)
class ResidualCommandConfig:
    """Bounds for a one-dimensional residual at the policy-command layer."""

    residual_yaw_limit_radps: float = 0.12
    total_yaw_limit_radps: float = 0.6

    def validate(self) -> None:
        if not np.isfinite(self.residual_yaw_limit_radps):
            raise ResidualContractError("residual yaw limit must be finite")
        if not np.isfinite(self.total_yaw_limit_radps):
            raise ResidualContractError("total yaw limit must be finite")
        if self.residual_yaw_limit_radps <= 0.0:
            raise ResidualContractError("residual yaw limit must be positive")
        if self.total_yaw_limit_radps <= 0.0:
            raise ResidualContractError("total yaw limit must be positive")
        if self.residual_yaw_limit_radps > self.total_yaw_limit_radps:
            raise ResidualContractError("residual yaw limit must not exceed total yaw limit")


@dataclass(frozen=True)
class ResidualCommandSample:
    """Auditable result of composing one normalized residual action."""

    active: bool
    requested_normalized_action: float
    applied_normalized_action: float
    requested_delta_yaw_radps: float
    applied_delta_yaw_radps: float
    deterministic_yaw_radps: float
    applied_yaw_radps: float
    total_saturated: bool


def apply_yaw_residual(
    deterministic_command: np.ndarray,
    normalized_action: np.ndarray,
    *,
    active: bool,
    config: ResidualCommandConfig = ResidualCommandConfig(),
) -> tuple[np.ndarray, ResidualCommandSample]:
    """Add a bounded yaw residual while preserving ``vx`` and ``vy`` exactly.

    The deterministic input must already satisfy the inherited total-yaw
    corridor. Failing closed here prevents a zero residual from silently
    changing the strong baseline through an additional clamp.
    """

    config.validate()
    command = np.asarray(deterministic_command, dtype=np.float64)
    action = np.asarray(normalized_action, dtype=np.float64)
    if command.shape != (3,):
        raise ResidualContractError(f"deterministic command must have shape (3,), got {command.shape}")
    if action.shape != (1,):
        raise ResidualContractError(f"normalized action must have shape (1,), got {action.shape}")
    if not np.isfinite(command).all() or not np.isfinite(action).all():
        raise ResidualContractError("command and action must be finite")
    deterministic_yaw = float(command[2])
    if abs(deterministic_yaw) > config.total_yaw_limit_radps:
        raise ResidualContractError("deterministic yaw command is outside the inherited corridor")

    requested_action = float(action[0])
    if not -1.0 <= requested_action <= 1.0:
        raise ResidualContractError("normalized action is outside [-1, 1]")
    requested_delta = requested_action * config.residual_yaw_limit_radps if active else 0.0
    bounded_delta = requested_delta
    proposed_yaw = deterministic_yaw + bounded_delta
    applied_yaw = float(
        np.clip(proposed_yaw, -config.total_yaw_limit_radps, config.total_yaw_limit_radps)
    )

    result = np.array(command, copy=True)
    result[2] = applied_yaw
    applied_delta = applied_yaw - deterministic_yaw
    sample = ResidualCommandSample(
        active=bool(active),
        requested_normalized_action=requested_action,
        applied_normalized_action=requested_action if active else 0.0,
        requested_delta_yaw_radps=requested_delta,
        applied_delta_yaw_radps=applied_delta,
        deterministic_yaw_radps=deterministic_yaw,
        applied_yaw_radps=applied_yaw,
        total_saturated=bool(active and abs(proposed_yaw) > config.total_yaw_limit_radps),
    )
    return result, sample


class BoundaryKind(str, Enum):
    CONTINUE = "CONTINUE"
    TERMINATED = "TERMINATED"
    TRUNCATED = "TRUNCATED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class BoundaryDecision:
    kind: BoundaryKind
    reason: str | None = None


def classify_boundary(
    *,
    target_reached: bool = False,
    task_success: bool = False,
    physical_failure: bool = False,
    task_horizon_exhausted: bool = False,
    external_budget_exhausted: bool = False,
    external_interrupt: bool = False,
    invalid_transition: bool = False,
) -> BoundaryDecision:
    """Classify Gymnasium episode boundaries without collapsing their meaning.

    Invalid simulator/controller transitions abort the run and are not scored.
    Task-defined terminal states take precedence over coincident external caps.
    """

    if invalid_transition:
        return BoundaryDecision(BoundaryKind.INVALID, "invalid_transition_not_scored")
    if task_success and not target_reached:
        return BoundaryDecision(BoundaryKind.INVALID, "task_success_without_target_reached")
    if physical_failure:
        return BoundaryDecision(BoundaryKind.TERMINATED, "physical_failure")
    if target_reached:
        reason = "task_success" if task_success else "target_reached_outside_envelope"
        return BoundaryDecision(BoundaryKind.TERMINATED, reason)
    if task_horizon_exhausted:
        return BoundaryDecision(BoundaryKind.TERMINATED, "task_horizon_exhausted")
    if external_interrupt:
        return BoundaryDecision(BoundaryKind.TRUNCATED, "external_interrupt")
    if external_budget_exhausted:
        return BoundaryDecision(BoundaryKind.TRUNCATED, "external_budget_exhausted")
    return BoundaryDecision(BoundaryKind.CONTINUE)
