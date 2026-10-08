"""Capability boundary map / risk map schema tests."""

from __future__ import annotations

import json

import pytest

from g1swarm.boundary import (
    CAPABILITY_SCHEMA_VERSION,
    build_capability_boundary_map,
    build_risk_map,
    validate_capability_boundary_map,
    validate_risk_map,
)
from g1swarm.characterization.failures import TAXONOMY_VERSION, FailureType

PROTOCOL = {
    "experiment_id": "g1_failure_boundary_001",
    "robot_config": "configs/robot/g1_locomotion_12dof.yaml",
    "provenance": {
        "model_source": "https://example.invalid/model",
        "model_commit": "abc",
        "controller_source": "https://example.invalid/controller",
        "controller_commit": "def",
        "policy_sha256": "cafe",
        "dof": 12,
        "actuators": 12,
    },
    "thresholds": {
        "envelopes": {
            "nominal": {"lateral_floor_m": 0.35},
            "strict": {"lateral_floor_m": 0.20},
        }
    },
}

SUMMARY = {
    "experiment_id": "g1_failure_boundary_001",
    "campaign": "final",
    "artifact_path": "artifacts/g1_failure_boundary_001/final",
    "runs_total": 12,
    "protocol_sha256": "deadbeef",
    "failures": [
        {
            "run_id": "B_push-final-150-seed000",
            "experiment": "B_push",
            "value": 150.0,
            "failure_type": "FALL",
            "failure_reason": "fall or unsafe state detected",
        }
    ],
    "experiments": {
        "B_push": {
            "spec": {"parameter": "push_force_n"},
            "search": {
                "zones": {
                    "reliable": [20.0, 60.0],
                    "transition": [100.0],
                    "failure": [150.0],
                },
                "boundary_estimate": 100.0,
                "bracket": [100.0, 150.0],
                "boundary_reached": True,
                "stop_reason": "boundary_refined",
                "direction": "increase",
            },
            "final": [
                {
                    "value": 150.0,
                    "n_runs": 5,
                    "deterministic": False,
                    "physical_success_rate": 0.4,
                    "task_success_rate": 0.2,
                    "risk": "HIGH",
                    "failure_counts": {"FALL": 4},
                    "metrics": {"strict_violation_rate": 0.8},
                    "run_ids": ["r1", "r2"],
                }
            ],
        }
    },
}


def test_capability_and_risk_maps_validate_and_roundtrip() -> None:
    capability = build_capability_boundary_map(
        protocol=PROTOCOL, summary=SUMMARY, source_commit="deadbeef"
    )
    validate_capability_boundary_map(capability)
    assert capability["schema_version"] == CAPABILITY_SCHEMA_VERSION
    assert capability["skills"]["walk_forward"]["boundary_status"] == "explored"
    assert capability["skills"]["walk_forward"]["failure_region"] == {
        "push_force_lateral": [150.0]
    }
    assert capability["skills"]["turn"]["boundary_status"] == "not_explored_in_phase_1_2"
    assert capability["failure_taxonomy_version"] == TAXONOMY_VERSION
    assert json.loads(json.dumps(capability)) == capability

    risk_map = build_risk_map(protocol=PROTOCOL, summary=SUMMARY, source_commit="deadbeef")
    validate_risk_map(risk_map)
    condition = risk_map["skills"]["walk_forward"]["conditions"][0]
    assert condition["condition"] == "push_force_lateral"
    assert condition["risk"] == "HIGH"
    assert condition["unit"] == "N"
    assert json.loads(json.dumps(risk_map)) == risk_map


def test_validation_rejects_incomplete_maps() -> None:
    with pytest.raises(ValueError):
        validate_capability_boundary_map({})
    broken = build_capability_boundary_map(
        protocol=PROTOCOL, summary=SUMMARY, source_commit="deadbeef"
    )
    del broken["skills"]["walk_forward"]["failure_region"]
    with pytest.raises(ValueError):
        validate_capability_boundary_map(broken)


def test_taxonomy_v12_has_new_types() -> None:
    assert TAXONOMY_VERSION == "1.2.0"
    assert FailureType.SLIP.value == "SLIP"
    assert FailureType.TASK_ENVELOPE_VIOLATION.value == "TASK_ENVELOPE_VIOLATION"


def test_invalid_risk_label_is_rejected() -> None:
    risk_map = build_risk_map(protocol=PROTOCOL, summary=SUMMARY, source_commit="deadbeef")
    risk_map["skills"]["walk_forward"]["conditions"][0]["risk"] = "MAYBE"
    with pytest.raises(ValueError):
        validate_risk_map(risk_map)
