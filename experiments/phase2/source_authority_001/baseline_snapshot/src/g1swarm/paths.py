"""Repository path helpers.

All experiment artifacts are resolved relative to the repository root so that
scripts, tests and skills behave the same regardless of the current working
directory. Both the root and the artifact directory can be redirected with the
``G1SWARM_ROOT`` and ``G1SWARM_ARTIFACTS_DIR`` environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_ROOT = "G1SWARM_ROOT"
ENV_ARTIFACTS = "G1SWARM_ARTIFACTS_DIR"


def repo_root() -> Path:
    override = os.environ.get(ENV_ROOT)
    if override:
        return Path(override).expanduser().resolve()
    source_file = Path(__file__).resolve()
    for candidate in source_file.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    # src/g1swarm/paths.py -> repository root
    return source_file.parents[2]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (repo_root() / path).resolve()


def artifacts_dir() -> Path:
    override = os.environ.get(ENV_ARTIFACTS)
    if override:
        return Path(override).expanduser().resolve()
    return repo_root() / "artifacts"
