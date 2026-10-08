"""The opt-in physical halt is separate from Task Graph skill dispatch."""

from __future__ import annotations

import json

import pytest

from g1swarm.mission import LiveMissionSession, MissionExecutor, MissionFailureType, MissionValidator, NodeState
from g1swarm.skills import SkillResult, SkillStatus
from g1swarm.state import RobotState
from test_mission_runtime import FakeSession, _mission, _protocol


CONTRACT = {
    "stop_skill_parameters": {"max_duration_s": 4.0, "window_s": 1.0,
                              "speed_threshold_mps": 0.1},
    "acceptance": {"max_duration_s": 4.0,
                   "max_final_instantaneous_speed_mps": 0.1,
                   "max_final_window_mean_speed_mps": 0.1,
                   "max_post_block_planar_displacement_m": 0.5},
}


@pytest.mark.parametrize("halt_status", ["HALT_SUCCEEDED", "HALT_FAILED"])
def test_halt_only_after_strict_graph_block(phase13_grounder, tmp_path, halt_status):
    sessions = []

    class DriftingSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.halt_calls = 0

        def run_node(self, node, execution_mode):
            execution = super().run_node(node, execution_mode)
            if node.skill.value == "walk_forward":
                execution.metrics["lateral_drift_m"] = 0.25
            return execution

        def run_failure_halt(self, contract):
            assert contract == CONTRACT
            self.halt_calls += 1
            return {"request": "EXPLICIT_INDEPENDENT_PHYSICAL_HALT",
                    "status": halt_status, "trace": [{"time_s": 1.0}]}

    def factory(seed):
        session = DriftingSession()
        sessions.append(session)
        return session

    mission = _mission([
        {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}},
        {"id": "s2", "skill": "stop", "parameters": {}, "depends_on": ["s1"]},
    ], mission_id="m2-halt-test")
    executor = MissionExecutor(
        validator=MissionValidator(), grounder=phase13_grounder,
        session_factory=factory, protocol=_protocol(),
        recorder_root=str(tmp_path), walk_strict_gate=True,
        physical_halt_contract=CONTRACT, provenance={"study": "m2-test"},
    )
    result = executor.run(mission)
    assert result.state == "FAILED"
    assert result.failure_type == MissionFailureType.TASK_ENVELOPE_VIOLATION.value
    assert result.skill_invocations == 1 and result.completed_nodes == 0
    assert executor.last_graph.get("s2").state is NodeState.BLOCKED
    assert sessions[0].calls == [("s1", "heading_lateral")]
    assert sessions[0].halt_calls == 1
    assert result.physical_halt["status"] == halt_status
    assert result.physical_halt["blocked_task_nodes"] == ["s2"]
    assert result.physical_halt["provenance"] == {"study": "m2-test"}
    events = [json.loads(line)["event"] for line in
              (tmp_path / mission["mission_id"] / "events.jsonl").read_text().splitlines()]
    assert events.index("node_failure") < events.index("physical_halt_requested")
    assert events.index("physical_halt_requested") < events.index(
        "physical_halt_succeeded" if halt_status == "HALT_SUCCEEDED" else "physical_halt_failed"
    )
    assert "physical_halt" in result.to_dict()


def test_halt_not_invoked_for_success_or_default(phase13_grounder):
    sessions = []

    class Session(FakeSession):
        def run_failure_halt(self, contract):
            raise AssertionError("Halt must not be requested")

    def factory(seed):
        session = Session()
        sessions.append(session)
        return session

    mission = _mission([{"id": "s1", "skill": "walk_forward",
                         "parameters": {"distance_m": 4.0}}])
    result = MissionExecutor(
        validator=MissionValidator(), grounder=phase13_grounder,
        session_factory=factory, protocol=_protocol(), walk_strict_gate=True,
        physical_halt_contract=CONTRACT,
    ).run(mission, write_evidence=False)
    assert result.state == "SUCCESS" and result.physical_halt is None
    assert "physical_halt" not in result.to_dict()
    assert sessions[0].calls == [("s1", "heading_lateral")]


def test_halt_cannot_enable_without_feedback_gate(phase13_grounder):
    with pytest.raises(ValueError, match="strict walk feedback"):
        MissionExecutor(
            validator=MissionValidator(), grounder=phase13_grounder,
            session_factory=lambda seed: FakeSession(), protocol=_protocol(),
            physical_halt_contract=CONTRACT,
        )


def test_live_halt_monitor_precedes_pose_wrapper_without_physics():
    def state(t, vx):
        return RobotState(
            simulation_time=t, base_position=(t * 0.01, 0.0, 0.78),
            base_orientation=(1.0, 0.0, 0.0, 0.0),
            linear_velocity=(vx, 0.0, 0.0), angular_velocity=(0.0, 0.0, 0.0),
            standing=True, fallen=False,
        )

    class Simulation:
        timestep = 0.1

        def __init__(self):
            self.current = state(0.0, 0.45)

        def get_robot_state(self):
            return self.current

        def step(self, control=None):
            self.current = state(0.1, 0.05)
            return self.current

    class Router:
        def execute(self, request, context):
            assert request.skill_name == "stop"
            context.simulation.step()
            return SkillResult("stop", SkillStatus.SUCCESS,
                               metrics={"final_window_mean_speed_mps": 0.05})

    simulation = Simulation()
    session = LiveMissionSession.__new__(LiveMissionSession)
    session.simulation = simulation
    session.current_state = simulation.current
    session.controller = object()
    session.robot_config = {}
    session.seed = 0
    session.total_steps = 0
    session.router = Router()

    def pose_wrapper(monitor):
        assert monitor._simulation is simulation
        return monitor

    session.simulation_wrapper = pose_wrapper
    result = session.run_failure_halt({**CONTRACT,
        "acceptance": {**CONTRACT["acceptance"], "stop_skill_status": "SUCCESS"}})
    assert result["status"] == "HALT_SUCCEEDED"
    assert len(result["trace"]) == 2
    assert result["trace"][1]["base_height_m"] == 0.78
    assert result["trace"][1]["tilt_deg"] == 0.0
    assert session.total_steps == 1
