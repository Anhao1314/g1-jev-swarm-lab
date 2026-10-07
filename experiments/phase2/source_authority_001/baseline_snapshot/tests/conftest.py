"""Shared pytest fixtures.

Tests never download anything: models must already be present in
``third_party/`` (fetched by ``scripts/fetch_g1_models.ps1``). When an asset is
missing the dependent test is skipped instead of failing.
"""

from __future__ import annotations

import pytest

from g1swarm.config import load_yaml
from g1swarm.mission import CapabilityGrounder
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


PHASE13_DIR = "experiments/baselines/g1_closed_loop_correction_001"
HISTORICAL_SKILL_LIMITS = {
    "turn": {
        "max_abs_angle_deg": 90.0,
        "source_phase": "phase1.1",
        "evidence_ref": "experiments/baselines/g1_skill_characterization_001/summary.json",
    },
    "stand": {
        "max_duration_s": 20.0,
        "default_duration_s": 2.0,
        "source_phase": "phase1.1",
        "evidence_ref": "experiments/baselines/g1_skill_characterization_001/summary.json",
    },
    "stop": {
        "source_phase": "phase1.1",
        "evidence_ref": "experiments/baselines/g1_skill_characterization_001/summary.json",
    },
}


@pytest.fixture(scope="session")
def phase13_grounder() -> CapabilityGrounder:
    base = resolve_repo_path(PHASE13_DIR)
    return CapabilityGrounder(
        risk_map_path=base / "risk_map_v1_3.json",
        boundary_comparison_path=base / "boundary_comparison.json",
        capability_map_path=base / "capability_map_v1_3.json",
        historical_limits=HISTORICAL_SKILL_LIMITS,
    )
