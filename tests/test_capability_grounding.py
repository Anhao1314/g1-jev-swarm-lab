"""Capability grounding tests against the real Phase 1.3 evidence."""

from __future__ import annotations

from g1swarm.mission import (
    CAPABILITY_REJECTED,
    CAPABILITY_UNKNOWN,
    GROUNDED,
    CapabilityGrounder,
    ExecutionModeOverride,
    Mission,
    MissionStep,
    SkillName,
)


def _step(step_id: str, skill: SkillName, **parameters) -> MissionStep:
    return MissionStep(step_id=step_id, skill=skill, parameters=dict(parameters))


def _mission(*steps: MissionStep, mission_id: str = "ground-mission") -> Mission:
    return Mission(mission_id=mission_id, steps=tuple(steps))


def test_walk_8m_selects_evidence_backed_closed_loop_mode(
    phase13_grounder: CapabilityGrounder,
) -> None:
    result = phase13_grounder.ground_step(_step("s1", SkillName.WALK_FORWARD, distance_m=8.0))
    assert result.status == GROUNDED
    assert result.supported
    assert result.execution_mode == "heading_lateral"  # LOW risk + frozen preference
    assert result.risk == "LOW"
    assert "risk_map_v1_3.json" in (result.evidence_ref or "")
    assert result.source_phase == "phase1.3"
    assert result.experimental_override is False


def test_walk_4m_is_grounded_and_prefers_heading_lateral(
    phase13_grounder: CapabilityGrounder,
) -> None:
    result = phase13_grounder.ground_step(_step("s1", SkillName.WALK_FORWARD, distance_m=4.0))
    assert result.status == GROUNDED and result.execution_mode == "heading_lateral"
    assert result.risk == "LOW"


def test_extension_distance_uses_boundary_evidence(
    phase13_grounder: CapabilityGrounder,
) -> None:
    result = phase13_grounder.ground_step(_step("s1", SkillName.WALK_FORWARD, distance_m=12.0))
    assert result.status == GROUNDED
    assert result.execution_mode in {"heading_lateral", "heading_only"}
    assert result.risk == "MEDIUM"
    assert "boundary_comparison.json" in (result.evidence_ref or "")


def test_distance_beyond_evidence_is_unknown_not_extrapolated(
    phase13_grounder: CapabilityGrounder,
) -> None:
    result = phase13_grounder.ground_step(_step("s1", SkillName.WALK_FORWARD, distance_m=25.0))
    assert result.status == CAPABILITY_UNKNOWN
    assert not result.supported
    assert result.execution_mode is None
    assert "no recorded evidence" in result.reason
    assert "segment" in result.reason or "interpolation" in result.reason


def test_open_loop_is_never_the_default_for_long_walks(
    phase13_grounder: CapabilityGrounder,
) -> None:
    for distance in (6.0, 8.0, 10.0):
        result = phase13_grounder.ground_step(
            _step("s1", SkillName.WALK_FORWARD, distance_m=distance)
        )
        assert result.execution_mode in {"heading_lateral", "heading_only"}


def test_explicit_override_is_grounded_but_marked_experimental(
    phase13_grounder: CapabilityGrounder,
) -> None:
    step = MissionStep(
        step_id="s1",
        skill=SkillName.WALK_FORWARD,
        parameters={"distance_m": 8.0},
        execution_mode_override=ExecutionModeOverride.OPEN_LOOP,
    )
    result = phase13_grounder.ground_step(step)
    assert result.status == GROUNDED
    assert result.execution_mode == "open_loop"
    assert result.experimental_override is True
    assert result.risk == "HIGH"  # the recorded risk is carried, not hidden


def test_override_without_evidence_is_unknown(
    phase13_grounder: CapabilityGrounder,
) -> None:
    step = MissionStep(
        step_id="s1",
        skill=SkillName.WALK_FORWARD,
        parameters={"distance_m": 12.0},
        execution_mode_override=ExecutionModeOverride.OPEN_LOOP,
    )
    result = phase13_grounder.ground_step(step)
    assert result.status == CAPABILITY_UNKNOWN
    assert "no recorded evidence" in result.reason


def test_turn_and_stand_reference_historical_evidence(
    phase13_grounder: CapabilityGrounder,
) -> None:
    turn = phase13_grounder.ground_step(_step("s1", SkillName.TURN, angle_deg=45.0))
    assert turn.status == GROUNDED and turn.source_phase == "phase1.1"
    far_turn = phase13_grounder.ground_step(_step("s2", SkillName.TURN, angle_deg=120.0))
    assert far_turn.status == CAPABILITY_UNKNOWN
    stand = phase13_grounder.ground_step(_step("s3", SkillName.STAND, duration_s=10.0))
    assert stand.status == GROUNDED
    long_stand = phase13_grounder.ground_step(_step("s4", SkillName.STAND, duration_s=30.0))
    assert long_stand.status == CAPABILITY_UNKNOWN
    stop = phase13_grounder.ground_step(_step("s5", SkillName.STOP))
    assert stop.status == GROUNDED


def test_ground_mission_status_and_map_hashes(phase13_grounder: CapabilityGrounder) -> None:
    good = _mission(
        _step("s1", SkillName.WALK_FORWARD, distance_m=8.0),
        _step("s2", SkillName.TURN, angle_deg=45.0),
    )
    plan = phase13_grounder.ground_mission(good)
    assert plan.grounded and plan.status == GROUNDED
    assert set(plan.map_hashes) == {"risk_map_v1_3", "boundary_comparison", "capability_map_v1_3"}
    assert all(len(value) == 64 for value in plan.map_hashes.values())

    unknown = phase13_grounder.ground_mission(
        _mission(_step("s1", SkillName.WALK_FORWARD, distance_m=25.0))
    )
    assert unknown.status == CAPABILITY_UNKNOWN
    assert len(unknown.results) == 1  # no silent segmentation into shorter walks


def test_high_risk_only_point_is_rejected() -> None:
    grounder = CapabilityGrounder.__new__(CapabilityGrounder)  # bypass file loading
    grounder.risk_map_path = "synthetic"
    grounder.boundary_path = "synthetic"
    grounder.risk_map = {
        "skills": {
            "walk_forward": {
                "execution_mode": {"9": {"heading_lateral": {"risk": "HIGH"}}}
            }
        }
    }
    grounder.boundary = {"treatments": {}}
    grounder.mode_preference = ("heading_lateral", "heading_only", "open_loop")
    grounder.historical_limits = {}
    result = grounder.ground_step(_step("s1", SkillName.WALK_FORWARD, distance_m=9.0))
    assert result.status == CAPABILITY_REJECTED
    assert result.risk == "HIGH"
    assert "segmentation is not an allowed strategy" in result.reason


def test_in_place_skills_never_get_the_walking_correction_mode(
    phase13_grounder: CapabilityGrounder,
) -> None:
    """Pilot regression: the walking path-correction layer fights an in-place turn.

    A turn held against the node-start heading stalls below the target until timeout,
    so the walking closed-loop modes are reserved for walk_forward nodes.
    """
    turn = phase13_grounder.ground_step(_step("s1", SkillName.TURN, angle_deg=45.0))
    stand = phase13_grounder.ground_step(_step("s2", SkillName.STAND, duration_s=2.0))
    stop = phase13_grounder.ground_step(_step("s3", SkillName.STOP))
    assert (turn.execution_mode, stand.execution_mode, stop.execution_mode) == (
        "open_loop",
        "open_loop",
        "open_loop",
    )
