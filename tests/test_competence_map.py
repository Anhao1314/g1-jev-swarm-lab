"""Competence map schema, serialization and attribution tests."""

from __future__ import annotations

import json

import pytest

from g1swarm.characterization import SCHEMA_VERSION, build_competence_map, validate_competence_map

PROTOCOL = {
    "experiment_id": "g1_skill_characterization_001",
    "robot": {"name": "g1_locomotion_12dof"},
    "provenance": {
        "model_source": "https://example.invalid/model",
        "model_commit": "abc",
        "model_xml": "scene.xml",
        "controller_source": "https://example.invalid/controller",
        "controller_commit": "def",
        "controller_kind": "official_pretrained_policy",
        "policy_sha256": "cafe",
        "dof": 12,
        "actuators": 12,
    },
    "preconditions": {
        "walk_forward": ["controller_available"],
        "turn": ["controller_available"],
        "stop": ["controller_available"],
        "stand": ["controller_available"],
    },
    "success_criteria": {
        "walk_forward": {"no_fall": True},
        "turn": {"no_fall": True},
        "stop": {"no_fall": True},
        "stand": {"no_fall": True},
    },
}

SUMMARY = {
    "campaign": "final",
    "runs_total": 3,
    "artifact_path": "artifacts/g1_skill_characterization_001/final",
    "nominal": {"walk_forward": {"2": {"n": 3, "successes": 3}}},
    "robustness": {
        "walk_forward_2m": {"push": {"n": 10, "successes": 8}},
        "turn_45": {"yaw": {"n": 10, "successes": 10}},
        "walk_stop_2m": {},
    },
    "failures": [
        {
            "run_id": "c-walk_stop_2m-push-seed000",
            "skill": "walk_forward+stop",
            "task": "walk_stop_2m",
            "condition": "push",
            "seed": 0,
            "failure_type": "FALL",
            "failure_reason": "fall or unsafe state detected",
        }
    ],
}


def test_build_and_validate_roundtrip() -> None:
    competence = build_competence_map(protocol=PROTOCOL, summary=SUMMARY, source_commit="deadbeef")
    validate_competence_map(competence)
    assert competence["schema_version"] == SCHEMA_VERSION
    assert competence["source_commit"] == "deadbeef"
    assert competence["robot"]["name"] == "g1_locomotion_12dof"
    assert competence["controller"]["policy_sha256"] == "cafe"
    for skill in ("walk_forward", "turn", "stop", "stand"):
        entry = competence["skills"][skill]
        assert entry["preconditions"] == ["controller_available"]
        assert "nominal" in entry and "conditions" in entry
        assert entry["evidence"]["experiment_id"] == "g1_skill_characterization_001"
    restored = json.loads(json.dumps(competence))
    assert restored == competence


def test_composite_failure_is_attributed_to_both_skills() -> None:
    competence = build_competence_map(protocol=PROTOCOL, summary=SUMMARY, source_commit="deadbeef")
    for skill in ("walk_forward", "stop"):
        modes = competence["skills"][skill]["known_failure_modes"]
        assert modes and modes[0]["failure_type"] == "FALL"
        assert modes[0]["count"] == 1
        assert modes[0]["example_run_id"] == "c-walk_stop_2m-push-seed000"
    assert competence["skills"]["turn"]["known_failure_modes"] == []


def test_validation_rejects_incomplete_maps() -> None:
    with pytest.raises(ValueError):
        validate_competence_map({})
    broken = build_competence_map(protocol=PROTOCOL, summary=SUMMARY, source_commit="deadbeef")
    del broken["skills"]["walk_forward"]["preconditions"]
    with pytest.raises(ValueError, match="preconditions"):
        validate_competence_map(broken)
