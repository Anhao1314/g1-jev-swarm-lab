"""No-physics checks for same-session, state-and-authority gated continuation."""

from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from g1swarm.mission import MissionExecutor, MissionValidator, NodeState
from g1swarm.mission.lifecycle import (MissionLifecycle, TestOnlyMissionAuthorizer,
                                       canonical_sha256, mission_sha256)
from g1swarm.state import RobotState
from test_mission_runtime import FakeSession, _mission, _protocol
from test_m2_physical_halt_runtime import CONTRACT


NEW_MISSION = _mission([
    {"id": "n1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}},
    {"id": "n2", "skill": "turn", "parameters": {"angle_deg": 45.0}, "depends_on": ["n1"]},
    {"id": "n3", "skill": "stop", "parameters": {}, "depends_on": ["n2"]},
], "new-oracle-mission")


class Session(FakeSession):
    def __init__(self):
        super().__init__()
        self.simulation = self
        self.controller = SimpleNamespace(_counter=0, _action=np.zeros(2), _target=np.zeros(2))
        self._data = SimpleNamespace(qpos=np.zeros(9), qvel=np.zeros(8), ctrl=np.zeros(2), time=0.0)
        self.total_steps = 0
        self.factory_calls = 0

    def get_robot_state(self):
        return RobotState.from_dict(self._state)

    def run_node(self, node, execution_mode):
        start = deepcopy(self._state)
        execution = super().run_node(node, execution_mode)
        self._state["simulation_time"] += 1.0
        self._state["base_position"] = [self._state["base_position"][0] + 1.0, 0.0, 0.78]
        self.total_steps += 10
        self._data.time = self._state["simulation_time"]
        self._data.qpos[0] = self._state["base_position"][0]
        execution.start_state = start
        execution.end_state = deepcopy(self._state)
        if node.node_id == "s1":
            execution.metrics["lateral_drift_m"] = 0.25
        return execution

    def run_failure_halt(self, contract):
        self._state["simulation_time"] += 1.0
        self._state["linear_velocity"] = [0.05, 0.0, 0.0]
        self._state["active_skill"] = "stop"
        self.total_steps += 10
        self._data.time = self._state["simulation_time"]
        return {"status": "HALT_SUCCEEDED", "final_state": deepcopy(self._state),
                "skill_metrics": {"final_window_mean_speed_mps": 0.099},
                "checks": {key: True for key in (
                    "skill_success", "duration", "final_speed", "window_mean_speed",
                    "displacement", "finite_throughout", "standing_throughout", "no_fall_throughout")}}


def setup(grounder, tmp_path=None):
    session = Session()

    def forbidden_factory(seed):
        raise AssertionError("External session must never create/reset a simulation")

    executor = MissionExecutor(
        validator=MissionValidator(), grounder=grounder,
        session_factory=forbidden_factory, protocol=_protocol(),
        recorder_root=str(tmp_path) if tmp_path else None,
        walk_strict_gate=True, physical_halt_contract=CONTRACT,
    )
    parent = executor.run(_mission([
        {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}},
        {"id": "s2", "skill": "stop", "parameters": {}, "depends_on": ["s1"]},
    ], "failed-parent"), existing_session=session)
    assert parent.state == "FAILED" and not session.closed
    lifecycle = MissionLifecycle(executor=executor, session=session, parent_result=parent,
                                 session_id="same-live-session")
    authority = TestOnlyMissionAuthorizer(allowed_mission_sha256={mission_sha256(NEW_MISSION)})
    return lifecycle, authority, session, parent


def test_authorized_new_graph_reuses_state_and_preserves_failed_evidence(phase13_grounder, tmp_path):
    lifecycle, authority, session, parent = setup(phase13_grounder, tmp_path)
    parent_graph = lifecycle._parent_graph
    old_bytes = {path.name: path.read_bytes() for path in (tmp_path / "failed-parent").iterdir()}
    old_digest = canonical_sha256(parent.to_dict())
    grant = authority.issue(lifecycle, NEW_MISSION)
    before = session.get_robot_state().to_dict()
    outcome = lifecycle.dispatch(NEW_MISSION, authorization=grant, authorizer=authority)
    assert outcome["status"] == "NEW_MISSION_COMPLETED"
    assert outcome["parent_preserved"] is True and not session.closed
    assert canonical_sha256(parent.to_dict()) == old_digest
    assert lifecycle._parent_graph is parent_graph
    assert parent_graph.get("s1").state is NodeState.FAILED
    assert parent_graph.get("s2").state is NodeState.BLOCKED
    assert lifecycle.executor.last_graph is not parent_graph
    assert lifecycle.executor.last_graph.get("n1").start_state == before
    assert [node_id for node_id, _ in session.calls] == ["s1", "n1", "n2", "n3"]
    assert {path.name: path.read_bytes() for path in (tmp_path / "failed-parent").iterdir()} == old_bytes
    assert "TEST_ONLY mission capability" not in json.dumps(lifecycle.events)
    assert outcome["new_mission_result"]["completed_nodes"] == 3


@pytest.mark.parametrize("grant", [None, "made-up-grant", {}, object()])
def test_missing_or_forged_authorization_never_dispatches(phase13_grounder, grant):
    lifecycle, authority, session, _ = setup(phase13_grounder)
    before = (list(session.calls), session.total_steps, session.get_robot_state().to_dict())
    outcome = lifecycle.dispatch(NEW_MISSION, authorization=grant, authorizer=authority)
    assert outcome["status"] == "ESCALATE"
    assert outcome["reason"] in {"AUTHORIZATION_MISSING", "AUTHORIZATION_UNRECOGNIZED"}
    assert (session.calls, session.total_steps, session.get_robot_state().to_dict()) == before


def test_mission_mismatch_and_single_use_replay(phase13_grounder):
    lifecycle, authority, session, _ = setup(phase13_grounder)
    grant = authority.issue(lifecycle, NEW_MISSION)
    different = deepcopy(NEW_MISSION)
    different["steps"][1]["parameters"]["angle_deg"] = 30.0
    outcome = lifecycle.dispatch(different, authorization=grant, authorizer=authority)
    assert outcome["reason"] == "AUTHORIZATION_BINDING_MISMATCH"
    assert len(session.calls) == 1
    assert lifecycle.dispatch(NEW_MISSION, authorization=grant, authorizer=authority)["status"] == "NEW_MISSION_COMPLETED"
    calls = list(session.calls)
    assert lifecycle.dispatch(NEW_MISSION, authorization=grant, authorizer=authority)["status"] == "ESCALATE"
    assert session.calls == calls


def test_same_serialized_session_id_cannot_transfer_capability(phase13_grounder):
    first, authority, _, _ = setup(phase13_grounder)
    second, _, session, _ = setup(phase13_grounder)
    grant = authority.issue(first, NEW_MISSION)
    outcome = second.dispatch(NEW_MISSION, authorization=grant, authorizer=authority)
    assert outcome["reason"] == "AUTHORIZATION_SESSION_MISMATCH"
    assert len(session.calls) == 1


def test_stale_steps_and_live_state_rejected(phase13_grounder):
    lifecycle, authority, session, _ = setup(phase13_grounder)
    grant = authority.issue(lifecycle, NEW_MISSION)
    session.total_steps += 1
    assert lifecycle.dispatch(NEW_MISSION, authorization=grant, authorizer=authority)["reason"] == "AUTHORIZATION_BINDING_MISMATCH"
    session._state["simulation_time"] += 0.002
    outcome = lifecycle.dispatch(NEW_MISSION, authorization=grant, authorizer=authority)
    assert "HALT_ENDPOINT_CHANGED" in outcome["assessment"]["reasons"]
    assert len(session.calls) == 1


@pytest.mark.parametrize("mutation, expected", [
    (lambda s: s._state.update(linear_velocity=[0.451, 0.0, 0.0]), "NOT_HALTED_SPEED"),
    (lambda s: s._state.update(standing=False), "NOT_STANDING_OR_FALLEN"),
    (lambda s: s._state.update(fallen=True), "NOT_STANDING_OR_FALLEN"),
    (lambda s: s._state.update(linear_velocity=[float("nan"), 0.0, 0.0]), "NON_FINITE_STATE"),
    (lambda s: setattr(s, "closed", True), "SESSION_CLOSED"),
])
def test_invalid_physical_state_blocks_even_with_previously_valid_grant(phase13_grounder, mutation, expected):
    lifecycle, authority, session, _ = setup(phase13_grounder)
    grant = authority.issue(lifecycle, NEW_MISSION)
    mutation(session)
    outcome = lifecycle.dispatch(NEW_MISSION, authorization=grant, authorizer=authority)
    assert outcome["status"] == "ESCALATE"
    assert expected in outcome["assessment"]["reasons"]
    assert len(session.calls) == 1


@pytest.mark.parametrize("change, expected", [
    (lambda m: m.update(mission_id="failed-parent"), "NEW_MISSION_ID_REUSED"),
    (lambda m: m["steps"][0].update(id="s1"), "OLD_NODE_IDS_REUSED"),
    (lambda m: m["steps"][0]["parameters"].update(distance_m=2.0), "NEW_MISSION_NOT_GROUNDED"),
    (lambda m: m["steps"][0].update(execution_mode_override="open_loop"), "NEW_MISSION_UNSUPPORTED_RISK"),
])
def test_reused_or_ungrounded_new_mission_rejected(phase13_grounder, change, expected):
    lifecycle, authority, session, _ = setup(phase13_grounder)
    mission = deepcopy(NEW_MISSION)
    change(mission)
    outcome = lifecycle.dispatch(mission, authorizer=authority)
    assert expected in outcome["assessment"]["reasons"]
    assert len(session.calls) == 1


def test_allowlist_and_existing_evidence_path_fail_closed(phase13_grounder, tmp_path):
    lifecycle, _, session, _ = setup(phase13_grounder, tmp_path)
    authority = TestOnlyMissionAuthorizer(allowed_mission_sha256=set())
    with pytest.raises(ValueError, match="FROZEN_TEST_ONLY_ALLOWLIST"):
        authority.issue(lifecycle, NEW_MISSION)
    (tmp_path / NEW_MISSION["mission_id"]).mkdir()
    assessment = lifecycle.assess(NEW_MISSION)
    assert "NEW_EVIDENCE_PATH_EXISTS" in assessment["reasons"]
    assert len(session.calls) == 1


def test_parent_mutation_and_failed_halt_never_authorize(phase13_grounder):
    lifecycle, authority, session, parent = setup(phase13_grounder)
    parent.physical_halt["status"] = "HALT_FAILED"
    assert "PARENT_RESULT_CHANGED" in lifecycle.assess(NEW_MISSION)["reasons"]
    with pytest.raises(ValueError, match="Cannot authorize"):
        authority.issue(lifecycle, NEW_MISSION)
    assert len(session.calls) == 1


@pytest.mark.parametrize("change", [
    lambda s: s._data.qpos.__setitem__(7, 0.1),
    lambda s: s._data.qvel.__setitem__(6, 0.1),
    lambda s: s._data.ctrl.__setitem__(0, 0.1),
    lambda s: setattr(s.controller, "_counter", 1),
    lambda s: s.controller._action.__setitem__(0, 0.1),
])
def test_zero_time_execution_state_mutation_invalidates_grant(phase13_grounder, change):
    lifecycle, authority, session, _ = setup(phase13_grounder)
    grant = authority.issue(lifecycle, NEW_MISSION)
    change(session)
    outcome = lifecycle.dispatch(NEW_MISSION, authorization=grant, authorizer=authority)
    assert "EXECUTION_STATE_CHANGED" in outcome["assessment"]["reasons"]
    assert len(session.calls) == 1


@pytest.mark.parametrize("change, expected", [
    (lambda p: p.physical_halt.update(status="HALT_FAILED"), "HALT_NOT_SUCCEEDED"),
    (lambda p: p.physical_halt.update(checks={"final_speed": True}), "HALT_ACCEPTANCE_NOT_MET"),
])
def test_invalid_halt_before_lifecycle_construction_is_not_an_admissible_parent(phase13_grounder, change, expected):
    previous, _, session, parent = setup(phase13_grounder)
    change(parent)
    lifecycle = MissionLifecycle(executor=previous.executor, session=session,
                                 parent_result=parent, session_id="invalid-halt")
    authority = TestOnlyMissionAuthorizer(allowed_mission_sha256={mission_sha256(NEW_MISSION)})
    assert expected in lifecycle.assess(NEW_MISSION)["reasons"]
    with pytest.raises(ValueError, match="Cannot authorize"):
        authority.issue(lifecycle, NEW_MISSION)
    assert len(session.calls) == 1
