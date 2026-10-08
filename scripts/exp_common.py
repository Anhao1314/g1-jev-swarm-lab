"""Shared helpers for Phase 1 experiment entry points."""

from __future__ import annotations

from typing import Any

from g1swarm.config import controller_source, model_source
from g1swarm.evidence import EnvironmentInfo, RunManifest


def manifest_for(
    *,
    experiment_id: str,
    run_id: str,
    task: str,
    robot: dict[str, Any],
    experiment: dict[str, Any],
    seed: int,
    config: dict[str, Any] | None = None,
    environment: EnvironmentInfo | None = None,
) -> RunManifest:
    model_repo, model_commit = model_source(robot)
    controller_repo, controller_commit = controller_source(robot)
    payload = {"experiment": experiment, "robot": robot}
    if config:
        payload.update(config)
    return RunManifest(
        experiment_id=experiment_id,
        run_id=run_id,
        task=task,
        config=payload,
        environment=environment or EnvironmentInfo.collect(),
        seed=seed,
        g1_model_source=model_repo,
        g1_model_commit=model_commit,
        controller_source=controller_repo,
        controller_version=controller_commit,
    )
