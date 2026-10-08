"""Mission Validator tests (static legality only)."""

from __future__ import annotations

from g1swarm.mission import (
    MISSION_SCHEMA_VERSION,
    Mission,
    MissionStep,
    MissionValidator,
    SkillName,
)

VALIDATOR = MissionValidator()


def _mission(steps: list[dict], mission_id: str = "mission-001") -> Mission:
    return Mission.from_dict(
        {"schema_version": MISSION_SCHEMA_VERSION, "mission_id": mission_id, "steps": steps}
    )


def _codes(report) -> list[str]:
    return [issue.code for issue in report.issues]


def test_valid_chained_mission_passes() -> None:
    mission = _mission(
        [
            {"id": "s1", "skill": "stand", "parameters": {"duration_s": 1.0}},
            {"id": "s2", "skill": "walk_forward", "parameters": {"distance_m": 4.0},
             "depends_on": ["s1"]},
            {"id": "s3", "skill": "turn", "parameters": {"angle_deg": -45.0},
             "depends_on": ["s2"]},
            {"id": "s4", "skill": "walk_forward", "parameters": {"distance_m": 4.0},
             "depends_on": ["s3"]},
            {"id": "s5", "skill": "stop", "parameters": {}, "depends_on": ["s4"]},
        ]
    )
    report = VALIDATOR.validate(mission)
    assert report.valid, report.to_dict()
    assert report.failure_type is None


def test_win32_alias_mission_id_is_rejected_by_validator() -> None:
    mission = Mission(
        mission_id="trailing.",
        steps=(MissionStep(step_id="s1", skill=SkillName.STOP, parameters={}),),
    )
    report = VALIDATOR.validate(mission)
    assert not report.valid and "INVALID_MISSION_ID" in _codes(report)


def test_empty_mission_is_rejected() -> None:
    report = VALIDATOR.validate(_mission([]))
    assert not report.valid and "EMPTY_MISSION" in _codes(report)
    assert report.failure_type == "VALIDATION_FAILURE"


def test_duplicate_step_ids_are_rejected() -> None:
    report = VALIDATOR.validate(
        _mission(
            [
                {"id": "s1", "skill": "stop", "parameters": {}},
                {"id": "s1", "skill": "stop", "parameters": {}},
            ]
        )
    )
    assert "DUPLICATE_STEP_ID" in _codes(report)


def test_dependency_errors_are_rejected() -> None:
    report = VALIDATOR.validate(
        _mission([{"id": "s1", "skill": "stop", "parameters": {}, "depends_on": ["ghost"]}])
    )
    assert "UNKNOWN_DEPENDENCY" in _codes(report)
    report = VALIDATOR.validate(
        _mission([{"id": "s1", "skill": "stop", "parameters": {}, "depends_on": ["s1"]}])
    )
    assert "SELF_DEPENDENCY" in _codes(report)
    report = VALIDATOR.validate(
        _mission(
            [
                {"id": "s1", "skill": "stop", "parameters": {}, "depends_on": ["s2"]},
                {"id": "s2", "skill": "stop", "parameters": {}, "depends_on": ["s1"]},
            ]
        )
    )
    assert "DEPENDENCY_CYCLE" in _codes(report)
    report = VALIDATOR.validate(
        _mission(
            [
                {"id": "s1", "skill": "stop", "parameters": {}, "depends_on": ["s2"]},
                {"id": "s2", "skill": "stop", "parameters": {}},
            ]
        )
    )
    assert "FORWARD_DEPENDENCY" in _codes(report)


def test_invalid_parameters_are_rejected() -> None:
    report = VALIDATOR.validate(
        _mission([{"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": -2.0}}])
    )
    assert "INVALID_DISTANCE" in _codes(report)
    report = VALIDATOR.validate(
        _mission([{"id": "s1", "skill": "turn", "parameters": {"angle_deg": 0.0}}])
    )
    assert "INVALID_ANGLE" in _codes(report)
    report = VALIDATOR.validate(
        _mission([{"id": "s1", "skill": "turn", "parameters": {"angle_deg": 720.0}}])
    )
    assert "INVALID_ANGLE" in _codes(report)
    report = VALIDATOR.validate(
        _mission([{"id": "s1", "skill": "stand", "parameters": {"duration_s": 0.0}}])
    )
    assert "INVALID_DURATION" in _codes(report)


def test_too_many_steps_is_rejected() -> None:
    steps = [
        {"id": f"s{index:02d}", "skill": "stop", "parameters": {}}
        for index in range(MissionValidator(max_steps=3).max_steps + 1)
    ]
    report = MissionValidator(max_steps=3).validate(_mission(steps))
    assert "TOO_MANY_STEPS" in _codes(report)


def test_report_serialization() -> None:
    report = VALIDATOR.validate(_mission([{"id": "s1", "skill": "stop", "parameters": {}}]))
    payload = report.to_dict()
    assert payload["valid"] is True and payload["issues"] == []
    invalid = VALIDATOR.validate(_mission([]))
    assert invalid.to_dict()["issues"][0]["code"] == "EMPTY_MISSION"
