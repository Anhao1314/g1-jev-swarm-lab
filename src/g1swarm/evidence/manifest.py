"""Experiment manifests and environment provenance.

Every real experiment run records the same manifest fields so that results can
be traced back to code revision, seed, model/controller source and machine.
Missing values are recorded as ``null`` - never invented.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from ..paths import repo_root

MANIFEST_FIELDS = (
    "experiment_id",
    "campaign",
    "run_id",
    "git_commit",
    "seed",
    "timestamp",
    "os",
    "python_version",
    "mujoco_version",
    "torch_version",
    "cuda_version",
    "gpu",
    "g1_model_source",
    "g1_model_commit",
    "controller_source",
    "controller_version",
    "controller_hash",
    "task",
    "config",
    "perturbation_type",
    "perturbation_parameters",
    "thresholds",
    "result",
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip()
    return commit or None


@dataclass(frozen=True)
class EnvironmentInfo:
    """Machine and package versions captured at run time."""

    os: str
    python_version: str
    mujoco_version: str | None
    torch_version: str | None
    cuda_version: str | None
    gpu: str | None
    git_commit: str | None = None

    @classmethod
    def collect(cls) -> "EnvironmentInfo":
        torch_version: str | None = None
        cuda_version: str | None = None
        gpu: str | None = None
        try:
            import torch

            torch_version = torch.__version__
            cuda_version = torch.version.cuda
            if torch.cuda.is_available():
                gpu = torch.cuda.get_device_name(0)
        except ImportError:
            pass
        return cls(
            os=platform.platform(),
            python_version=sys.version.split()[0],
            mujoco_version=_package_version("mujoco"),
            torch_version=torch_version,
            cuda_version=cuda_version,
            gpu=gpu,
            git_commit=_git_commit(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "os": self.os,
            "python_version": self.python_version,
            "mujoco_version": self.mujoco_version,
            "torch_version": self.torch_version,
            "cuda_version": self.cuda_version,
            "gpu": self.gpu,
            "git_commit": self.git_commit,
        }


@dataclass
class RunManifest:
    """Manifest for a single experiment run."""

    experiment_id: str
    run_id: str
    task: str
    config: dict[str, Any]
    environment: EnvironmentInfo
    seed: int | None = None
    timestamp: str = field(default_factory=utc_timestamp)
    g1_model_source: str | None = None
    g1_model_commit: str | None = None
    controller_source: str | None = None
    controller_version: str | None = None
    controller_hash: str | None = None
    result: dict[str, Any] | None = None
    campaign: str | None = None
    perturbation_type: str | None = None
    perturbation_parameters: dict[str, Any] | None = None
    thresholds: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        env = self.environment
        return {
            "experiment_id": self.experiment_id,
            "campaign": self.campaign,
            "run_id": self.run_id,
            "git_commit": env.git_commit,
            "seed": self.seed,
            "timestamp": self.timestamp,
            "os": env.os,
            "python_version": env.python_version,
            "mujoco_version": env.mujoco_version,
            "torch_version": env.torch_version,
            "cuda_version": env.cuda_version,
            "gpu": env.gpu,
            "g1_model_source": self.g1_model_source,
            "g1_model_commit": self.g1_model_commit,
            "controller_source": self.controller_source,
            "controller_version": self.controller_version,
            "controller_hash": self.controller_hash,
            "task": self.task,
            "config": self.config,
            "perturbation_type": self.perturbation_type,
            "perturbation_parameters": self.perturbation_parameters,
            "thresholds": self.thresholds,
            "result": self.result,
        }

    def validate(self) -> None:
        missing = [name for name in MANIFEST_FIELDS if name not in self.to_dict()]
        if missing:
            raise ValueError(f"manifest is missing fields: {', '.join(missing)}")
