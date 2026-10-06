"""Shared pytest fixtures.

Tests never download anything: models must already be present in
``third_party/`` (fetched by ``scripts/fetch_g1_models.ps1``). When an asset is
missing the dependent test is skipped instead of failing.
"""

from __future__ import annotations

import pytest

from g1swarm.config import load_yaml
from g1swarm.paths import resolve_repo_path


def _load_robot(config_path: str) -> dict:
    robot = load_yaml(config_path)
    if not resolve_repo_path(robot["model"]["xml_path"]).is_file():
        pytest.skip(f"G1 assets missing for {config_path}; run scripts/fetch_g1_models.ps1")
    return robot


@pytest.fixture(scope="session")
def locomotion_robot() -> dict:
    return _load_robot("configs/robot/g1_locomotion_12dof.yaml")


@pytest.fixture(scope="session")
def full_body_robot() -> dict:
    return _load_robot("configs/robot/g1_full_29dof.yaml")
