"""Task Graph tests: dependency order, blocking, state transitions."""

from __future__ import annotations

import pytest

from g1swarm.mission import (
    InvalidStateTransition,
    Mission,
    MissionStep,
    NodeState,
    SkillName,
    TaskGraph,
)
from g1swarm.mission.grounding import GroundedPlan, GroundingResult


def _grounding(step_id: str, skill: SkillName, mode: str = "heading_lateral") -> GroundingResult:
    return GroundingResult(
        step_id=step_id,
        skill=skill.value,
        supported=True,
        status="GROUNDED",
        execution_mode=mode,
        risk="LOW",
        evidence_ref="test",
        reason="test",
    )


def _plan(mission: Mission) -> GroundedPlan:
    return GroundedPlan(
        mission_id=mission.mission_id,
        status="GROUNDED",
        results=tuple(_grounding(step.step_id, step.skill) for step in mission.steps),
    )


def _chain_mission() -> Mission:
    return Mission(
        mission_id="graph-mission",
        steps=(
            MissionStep("s1", SkillName.WALK_FORWARD, {"distance_m": 4.0}),
            MissionStep("s2", SkillName.TURN, {"angle_deg": 45.0}, ("s1",)),
            MissionStep("s3", SkillName.STOP, {}, ("s2",)),
        ),
    )


def test_graph_builds_nodes_with_grounded_modes() -> None:
    mission = _chain_mission()
    graph = TaskGraph.from_mission(mission, _plan(mission))
    assert [node.node_id for node in graph.nodes] == ["s1", "s2", "s3"]
    assert all(node.execution_mode == "heading_lateral" for node in graph.nodes)
    graph.refresh_ready()
    assert [node.node_id for node in graph.ready_nodes()] == ["s1"]


def test_dependency_order_is_sequential() -> None:
    mission = _chain_mission()
    graph = TaskGraph.from_mission(mission, _plan(mission))
    graph.refresh_ready()
    graph.mark_running("s1")
    graph.mark_success("s1", result={}, start_state={}, end_state={})
    graph.refresh_ready()
    assert [node.node_id for node in graph.ready_nodes()] == ["s2"]
    graph.mark_running("s2")
    graph.mark_success("s2", result={}, start_state={}, end_state={})
    graph.refresh_ready()
    assert [node.node_id for node in graph.ready_nodes()] == ["s3"]
    graph.mark_running("s3")
    graph.mark_success("s3", result={}, start_state={}, end_state={})
    assert graph.all_succeeded()
    assert graph.execution_order == ["s1", "s2", "s3"]


def test_failure_blocks_descendants() -> None:
    mission = _chain_mission()
    graph = TaskGraph.from_mission(mission, _plan(mission))
    graph.refresh_ready()
    graph.mark_running("s1")
    graph.mark_failed("s1", result={}, start_state={}, end_state={})
    blocked = graph.block_descendants("s1")
    assert blocked == ["s2", "s3"]
    assert graph.get("s2").state is NodeState.BLOCKED
    assert graph.get("s3").state is NodeState.BLOCKED
    assert graph.has_failure() and not graph.all_succeeded()
    assert graph.ready_nodes() == []


def test_invalid_state_transitions_are_rejected() -> None:
    mission = _chain_mission()
    graph = TaskGraph.from_mission(mission, _plan(mission))
    with pytest.raises(InvalidStateTransition):
        graph.mark_running("s1")  # PENDING -> RUNNING is not allowed
    graph.refresh_ready()
    graph.mark_running("s1")
    with pytest.raises(InvalidStateTransition):
        graph.mark_running("s1")  # RUNNING -> RUNNING is not allowed


def test_graph_serialization() -> None:
    mission = _chain_mission()
    graph = TaskGraph.from_mission(mission, _plan(mission))
    payload = graph.to_dict()
    assert [node["node_id"] for node in payload["nodes"]] == ["s1", "s2", "s3"]
    assert payload["nodes"][1]["depends_on"] == ["s1"]
    assert payload["has_failure"] is False
