"""Deterministic Mission Runtime tests (fake + live sessions)."""

from __future__ import annotations

import json
import math

from g1swarm.metrics import RunMetrics
from g1swarm.mission import (
    CapabilityGrounder,
    LiveMissionSession,
    MissionExecutor,
    MissionFailureType,
    MissionValidator,
    NodeExecution,
    NodeState,
)
from g1swarm.state import RobotState


# ---------------------------------------------------------------------------
def _state_payload(position=(0.0, 0.0, 0.78), yaw_deg: float = 0.0) -> dict:
    half = math.radians(yaw_deg) / 2.0
    return RobotState(
        simulation_time=0.0,
        base_position=position,
        base_orientation=(math.cos(half), 0.0, 0.0, math.sin(half)),
        linear_velocity=(0.0, 0.0, 0.0),
        angular_velocity=(0.0, 0.0, 0.0),
        standing=True,
        fallen=False,
        active_skill=None,
    ).to_dict()


def _node_metrics(*, task: bool = True, physical: bool = True) -> dict:
    return RunMetrics(
        forward_displacement_m=1.0,
        distance_error_m=0.0,
        lateral_drift_m=0.0,
        heading_error_deg=0.0,
        simulation_time_s=1.0,
        physical_success=physical,
        task_success=task,
        failure_type="SUCCESS" if task else "FAILURE",
        failure_reason=None if task else "fake failure",
        controller_memory_resets=1,
        extras={"path_length_m": 1.0, "simulation_steps": 10},
    ).to_dict()


class _State:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_dict(self) -> dict:
        return dict(self._payload)


class FakeSession:
    def __init__(self, behaviors: dict[str, str] | None = None) -> None:
        self.behaviors = dict(behaviors or {})
        self.calls: list[tuple[str, str]] = []
        self.closed = False
        self._state = _state_payload()

    def state(self) -> _State:
        return _State(self._state)

    def run_node(self, node, execution_mode: str) -> NodeExecution:
        self.calls.append((node.node_id, execution_mode))
        status = self.behaviors.get(node.node_id, "SUCCESS")
        ok = status == "SUCCESS"
        physically_valid = status not in {"UNSAFE", "NON_FINITE_STATE", "INVALID_CONTROL"}
        return NodeExecution(
            skill=node.skill.value,
            status=status,
            reason=None if ok else f"fake {status}",
            physical_success=physically_valid,
            metrics=_node_metrics(task=ok),
            start_state=dict(self._state),
            end_state=dict(self._state),
            simulation_steps=10,
            memory_resets=1,
            correction={},
        )

    def close(self) -> None:
        self.closed = True


def _protocol() -> dict:
    return {
        "protocol_path": "configs/experiments/oracle_mission_runtime_001.yaml",
        "_protocol_sha256": "test-hash",
        "provenance": {
            "policy_sha256": "cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d",
            "controller_commit": "276801e46c5d433564f24658bac64f254b7d2d4b",
        },
        "skill_parameters": {
            "walk_forward": {
                "tolerance_m": 0.2,
                "speed_mps": 0.5,
                "timeout_min_s": 15.0,
                "timeout_s_per_m": 6.0,
            },
            "turn": {
                "tolerance_deg": 15.0,
                "yaw_rate_radps": 0.5,
                "max_duration_s": 10.0,
                "settle_s": 0.5,
            },
            "stand": {"default_duration_s": 2.0},
            "stop": {"window_s": 1.0, "speed_threshold_mps": 0.10, "max_duration_s": 4.0},
        },
        "grounding": {
            "correction_gains": {
                "heading_only": {"k_heading": 1.5},
                "heading_lateral": {"k_heading": 1.5, "k_lateral": 1.0},
            },
            "correction_limits": {
                "max_yaw_rate_radps": 0.6,
                "deadband_radps": 0.01,
                "oscillation_threshold_radps": 0.05,
            },
        },
    }


def _mission(steps: list[dict], mission_id: str = "runtime-mission") -> dict:
    return {"schema_version": "2.0.0", "mission_id": mission_id, "steps": steps}


def _executor(grounder: CapabilityGrounder, behaviors=None, **kwargs):
    holder: dict[str, FakeSession] = {}

    def factory(seed: int) -> FakeSession:
        session = FakeSession(behaviors)
        holder["session"] = session
        return session

    executor = MissionExecutor(
        validator=MissionValidator(),
        grounder=grounder,
        session_factory=factory,
        protocol=_protocol(),
        provenance={"git_commit": "test"},
        **kwargs,
    )
    return executor, holder


# ---------------------------------------------------------------------------
def test_success_flow(phase13_grounder: CapabilityGrounder) -> None:
    executor, holder = _executor(phase13_grounder)
    result = executor.run(
        _mission(
            [
                {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}},
                {"id": "s2", "skill": "stop", "parameters": {}, "depends_on": ["s1"]},
            ]
        ),
        write_evidence=False,
    )
    assert result.state == "SUCCESS" and result.mission_success
    assert result.completed_nodes == 2
    assert result.failed_node is None
    assert result.transition_count == 1
    assert result.physical_success is True
    assert result.simulation_steps_executed == 20
    assert holder["session"].closed is True
    assert [call[0] for call in holder["session"].calls] == ["s1", "s2"]
    assert holder["session"].calls[0][1] == "heading_lateral"


def test_skill_failure_stops_and_blocks_descendants(phase13_grounder: CapabilityGrounder) -> None:
    executor, holder = _executor(phase13_grounder, behaviors={"s2": "FAILURE"})
    result = executor.run(
        _mission(
            [
                {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}},
                {"id": "s2", "skill": "turn", "parameters": {"angle_deg": 45.0},
                 "depends_on": ["s1"]},
                {"id": "s3", "skill": "stop", "parameters": {}, "depends_on": ["s2"]},
            ]
        ),
        write_evidence=False,
    )
    assert result.state == "FAILED"
    assert result.failure_type == MissionFailureType.SKILL_FAILURE.value
    assert result.failed_node == "s2"
    assert result.completed_nodes == 1
    assert executor.last_graph.get("s3").state is NodeState.BLOCKED
    assert [call[0] for call in holder["session"].calls] == ["s1", "s2"]  # no retry


def test_later_precondition_failure_is_a_transition_failure(
    phase13_grounder: CapabilityGrounder,
) -> None:
    executor, _ = _executor(phase13_grounder, behaviors={"s2": "PRECONDITION_FAILED"})
    result = executor.run(
        _mission(
            [
                {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}},
                {"id": "s2", "skill": "turn", "parameters": {"angle_deg": 45.0},
                 "depends_on": ["s1"]},
            ]
        ),
        write_evidence=False,
    )
    assert result.failure_type == MissionFailureType.TRANSITION_FAILURE.value


def test_rejections_execute_zero_simulation_steps(phase13_grounder: CapabilityGrounder) -> None:
    created: list[int] = []

    def factory(seed: int):
        created.append(seed)
        return FakeSession()

    executor = MissionExecutor(
        validator=MissionValidator(),
        grounder=phase13_grounder,
        session_factory=factory,
        protocol=_protocol(),
    )
    invalid = executor.run(
        _mission([{"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": -2.0}}]),
        write_evidence=False,
    )
    assert invalid.state == "REJECTED"
    assert invalid.failure_type == MissionFailureType.VALIDATION_FAILURE.value
    unknown = executor.run(
        _mission([{"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 25.0}}]),
        write_evidence=False,
    )
    assert unknown.state == "REJECTED"
    assert unknown.failure_type == MissionFailureType.CAPABILITY_UNKNOWN.value
    unsupported = executor.run(
        _mission([{"id": "s1", "skill": "stop", "parameters": {"mode": "x"}}]),
        write_evidence=False,
    )
    assert unsupported.failure_type == MissionFailureType.VALIDATION_FAILURE.value
    assert created == []  # no simulation session was ever created
    assert unknown.simulation_steps_executed == 0 and invalid.simulation_steps_executed == 0


def test_experimental_override_is_forwarded_and_logged(
    phase13_grounder: CapabilityGrounder,
) -> None:
    executor, holder = _executor(phase13_grounder)
    result = executor.run(
        _mission(
            [
                {
                    "id": "s1",
                    "skill": "walk_forward",
                    "parameters": {"distance_m": 8.0},
                    "execution_mode_override": "open_loop",
                }
            ]
        ),
        write_evidence=False,
    )
    assert result.state == "SUCCESS"
    assert holder["session"].calls[0][1] == "open_loop"
    grounded = result.grounding["results"][0]
    assert grounded["execution_mode"] == "open_loop"
    assert grounded["experimental_override"] is True
    assert grounded["risk"] == "HIGH"


def test_evidence_bundle_is_written(
    phase13_grounder: CapabilityGrounder, tmp_path
) -> None:
    executor, _ = _executor(phase13_grounder, recorder_root=str(tmp_path))
    executor.run(
        _mission([{"id": "s1", "skill": "stop", "parameters": {}}], mission_id="evidence-mission"),
        write_evidence=True,
    )
    mission_dir = tmp_path / "evidence-mission"
    for name in ("mission_manifest.json", "task_graph.json", "events.jsonl", "mission_summary.json"):
        assert (mission_dir / name).is_file()
    manifest = json.loads((mission_dir / "mission_manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["map_hashes"]) == {
        "risk_map_v1_3",
        "boundary_comparison",
        "capability_map_v1_3",
    }
    assert manifest["mission_input"]["mission_id"] == "evidence-mission"
    events = [
        json.loads(line)["event"]
        for line in (mission_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for required in (
        "mission_received",
        "validation_passed",
        "capability_grounded",
        "node_start",
        "skill_start",
        "skill_end",
        "node_success",
        "mission_success",
    ):
        assert required in events


def test_runtime_is_deterministic(phase13_grounder: CapabilityGrounder) -> None:
    mission = _mission(
        [
            {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}},
            {"id": "s2", "skill": "stop", "parameters": {}, "depends_on": ["s1"]},
        ]
    )
    first, _ = _executor(phase13_grounder)
    second, _ = _executor(phase13_grounder)
    result_a = first.run(mission, write_evidence=False).to_dict()
    result_b = second.run(mission, write_evidence=False).to_dict()
    result_a.pop("total_wall_time_s")
    result_b.pop("total_wall_time_s")
    assert result_a == result_b


# ---------------------------------------------------------------------------
def test_live_session_runs_a_stop_mission(locomotion_robot: dict) -> None:
    def factory(seed: int) -> LiveMissionSession:
        return LiveMissionSession(robot_config=locomotion_robot, protocol=_protocol(), seed=seed)

    executor = MissionExecutor(
        validator=MissionValidator(),
        grounder=CapabilityGrounder(
            risk_map_path="experiments/baselines/g1_closed_loop_correction_001/risk_map_v1_3.json",
            boundary_comparison_path="experiments/baselines/g1_closed_loop_correction_001/boundary_comparison.json",
            capability_map_path="experiments/baselines/g1_closed_loop_correction_001/capability_map_v1_3.json",
            historical_limits={
                "turn": {"max_abs_angle_deg": 90.0, "source_phase": "phase1.1"},
                "stand": {"max_duration_s": 20.0, "default_duration_s": 2.0, "source_phase": "phase1.1"},
                "stop": {"source_phase": "phase1.1"},
            },
        ),
        session_factory=factory,
        protocol=_protocol(),
    )
    result = executor.run(
        _mission([{"id": "s1", "skill": "stop", "parameters": {}}], mission_id="live-stop"),
        write_evidence=False,
    )
    assert result.state == "SUCCESS" and result.mission_success
    assert result.simulation_steps_executed > 0
    assert result.physical_success is True


def test_live_session_runs_a_grounded_walk(locomotion_robot: dict) -> None:
    def factory(seed: int) -> LiveMissionSession:
        return LiveMissionSession(robot_config=locomotion_robot, protocol=_protocol(), seed=seed)

    executor = MissionExecutor(
        validator=MissionValidator(),
        grounder=CapabilityGrounder(
            risk_map_path="experiments/baselines/g1_closed_loop_correction_001/risk_map_v1_3.json",
            boundary_comparison_path="experiments/baselines/g1_closed_loop_correction_001/boundary_comparison.json",
            capability_map_path="experiments/baselines/g1_closed_loop_correction_001/capability_map_v1_3.json",
            historical_limits={
                "turn": {"max_abs_angle_deg": 90.0, "source_phase": "phase1.1"},
                "stand": {"max_duration_s": 20.0, "default_duration_s": 2.0, "source_phase": "phase1.1"},
                "stop": {"source_phase": "phase1.1"},
            },
        ),
        session_factory=factory,
        protocol=_protocol(),
    )
    result = executor.run(
        _mission(
            [{"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4.0}}],
            mission_id="live-walk",
        ),
        write_evidence=False,
    )
    assert result.state == "SUCCESS"
    assert result.nodes[0]["execution_mode"] == "heading_lateral"
    node_metrics = result.nodes[0]["metrics"]
    assert node_metrics["task_success"] is True
    assert abs(node_metrics["lateral_drift_m"]) < 0.35
