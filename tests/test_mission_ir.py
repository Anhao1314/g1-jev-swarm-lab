"""Mission IR parsing and serialization tests."""

from __future__ import annotations

import pytest

from g1swarm.mission import (
    MISSION_SCHEMA_VERSION,
    ExecutionModeOverride,
    Mission,
    MissionIRError,
    SkillName,
)


def _document(**overrides) -> dict:
    document = {
        "schema_version": MISSION_SCHEMA_VERSION,
        "mission_id": "mission-001",
        "steps": [
            {"id": "step-001", "skill": "walk_forward", "parameters": {"distance_m": 8.0}},
            {"id": "step-002", "skill": "turn", "parameters": {"angle_deg": 45.0}},
            {"id": "step-003", "skill": "stop", "parameters": {}},
        ],
    }
    document.update(overrides)
    return document


def test_valid_mission_round_trip() -> None:
    mission = Mission.from_dict(_document())
    assert mission.schema_version == MISSION_SCHEMA_VERSION
    assert mission.mission_id == "mission-001"
    assert mission.horizon == 3
    assert [step.skill for step in mission.steps] == [
        SkillName.WALK_FORWARD,
        SkillName.TURN,
        SkillName.STOP,
    ]
    assert mission.steps[0].parameters["distance_m"] == 8.0
    payload = mission.to_dict()
    assert Mission.from_dict(payload) == mission
    assert Mission.from_json(mission.to_json()) == mission


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(MissionIRError, match="unknown mission fields"):
        Mission.from_dict({**_document(), "planner": "llm"})
    document = _document()
    document["steps"][0]["waypoints"] = [[0, 0], [1, 1]]
    with pytest.raises(MissionIRError, match="unknown fields"):
        Mission.from_dict(document)


def test_wrong_schema_version_is_rejected() -> None:
    with pytest.raises(MissionIRError, match="schema_version"):
        Mission.from_dict(_document(schema_version="1.0.0"))


def test_unsupported_skill_is_rejected() -> None:
    document = _document()
    document["steps"][0]["skill"] = "grab_object"
    with pytest.raises(MissionIRError, match="not a supported skill"):
        Mission.from_dict(document)


def test_non_finite_and_malformed_parameters_are_rejected() -> None:
    for bad in (float("nan"), float("inf"), "8m", True, None):
        document = _document()
        document["steps"][0]["parameters"]["distance_m"] = bad
        with pytest.raises(MissionIRError, match="distance_m"):
            Mission.from_dict(document)


def test_missing_and_extra_parameters_are_rejected() -> None:
    document = _document()
    document["steps"][1]["parameters"] = {}
    with pytest.raises(MissionIRError, match="missing"):
        Mission.from_dict(document)
    document = _document()
    document["steps"][2]["parameters"] = {"speed_mps": 0.5}
    with pytest.raises(MissionIRError, match="unknown fields for stop"):
        Mission.from_dict(document)


def test_unsafe_mission_ids_are_rejected() -> None:
    for bad in ("../escape", "a/b", "", " mission", "mission id", "x" * 65):
        with pytest.raises(MissionIRError):
            Mission.from_dict(_document(mission_id=bad))


def test_execution_mode_override_parsing() -> None:
    document = _document()
    document["steps"][0]["execution_mode_override"] = "heading_lateral"
    mission = Mission.from_dict(document)
    assert mission.steps[0].execution_mode_override is ExecutionModeOverride.HEADING_LATERAL
    document = _document()
    document["steps"][0]["execution_mode_override"] = "warp_drive"
    with pytest.raises(MissionIRError, match="not a known mode"):
        Mission.from_dict(document)
    document = _document()
    document["steps"][0]["execution_mode_override"] = None
    assert Mission.from_dict(document).steps[0].execution_mode_override is None


def test_depends_on_parsing() -> None:
    document = _document()
    document["steps"][1]["depends_on"] = ["step-001", "step-001"]
    mission = Mission.from_dict(document)
    assert mission.steps[1].depends_on == ("step-001",)
    document["steps"][1]["depends_on"] = "step-001"
    with pytest.raises(MissionIRError, match="depends_on must be a list"):
        Mission.from_dict(document)
