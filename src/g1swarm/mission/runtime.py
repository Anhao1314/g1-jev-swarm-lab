"""Deterministic Mission Runtime (Phase 2.0).

Validation -> capability grounding -> task graph -> sequential execution of
READY nodes through the existing Skill Router. No reasoning, no recovery, no
replanning, no language: a failed node stops the mission and blocks its
descendants.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Protocol

from ..evidence import utc_timestamp
from ..characterization.kinematics import wrap_angle_deg, yaw_deg
from ..boundary.envelope import STRICT_WALK_ENVELOPE
from ..simulation.errors import G1SimulationError, InvalidControlError, SimulationStateError
from ..skills import SkillStatus
from .evidence import MissionRecorder
from .grounding import CapabilityGrounder, GroundedPlan
from .ir import (
    MISSION_SCHEMA_VERSION,
    Mission,
    MissionIRError,
    is_path_safe_mission_id,
)
from .live_session import NodeExecution
from .task_graph import MissionState, NodeState, TaskGraph
from .validator import MissionValidator


class MissionFailureType(str, Enum):
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    UNSUPPORTED_SKILL = "UNSUPPORTED_SKILL"
    CAPABILITY_REJECTED = "CAPABILITY_REJECTED"
    CAPABILITY_UNKNOWN = "CAPABILITY_UNKNOWN"
    PRECONDITION_FAILURE = "PRECONDITION_FAILURE"
    SKILL_FAILURE = "SKILL_FAILURE"
    TRANSITION_FAILURE = "TRANSITION_FAILURE"
    MISSION_TIMEOUT = "MISSION_TIMEOUT"
    INVALID_STATE = "INVALID_STATE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    TASK_ENVELOPE_VIOLATION = "TASK_ENVELOPE_VIOLATION"


class MissionSessionProtocol(Protocol):
    def state(self): ...
    def run_node(self, node, execution_mode: str) -> NodeExecution: ...
    def run_failure_halt(self, contract: Mapping[str, Any]) -> dict[str, Any]: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class MissionResult:
    mission_id: str
    mission_schema_version: str
    horizon: int
    state: str
    mission_success: bool
    failure_type: str | None
    failure_reason: str | None
    completed_nodes: int
    failed_node: str | None
    total_simulation_time_s: float
    total_wall_time_s: float
    skill_invocations: int
    physical_success: bool
    path_length_m: float
    transition_count: int
    controller_memory_resets: int
    simulation_steps_executed: int
    nodes: tuple[dict[str, Any], ...] = ()
    transitions: tuple[dict[str, Any], ...] = ()
    grounding: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    map_hashes: dict[str, str] = field(default_factory=dict)
    physical_halt: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "mission_id": self.mission_id,
            "mission_schema_version": self.mission_schema_version,
            "horizon": self.horizon,
            "state": self.state,
            "mission_success": self.mission_success,
            "failure_type": self.failure_type,
            "failure_reason": self.failure_reason,
            "completed_nodes": self.completed_nodes,
            "failed_node": self.failed_node,
            "total_simulation_time_s": self.total_simulation_time_s,
            "total_wall_time_s": self.total_wall_time_s,
            "skill_invocations": self.skill_invocations,
            "physical_success": self.physical_success,
            "path_length_m": self.path_length_m,
            "transition_count": self.transition_count,
            "controller_memory_resets": self.controller_memory_resets,
            "simulation_steps_executed": self.simulation_steps_executed,
            "nodes": [dict(node) for node in self.nodes],
            "transitions": [dict(transition) for transition in self.transitions],
            "grounding": dict(self.grounding),
            "validation": dict(self.validation),
            "map_hashes": dict(self.map_hashes),
        }
        if self.physical_halt is not None:
            payload["physical_halt"] = dict(self.physical_halt)
        return payload


class MissionExecutor:
    def __init__(
        self,
        *,
        validator: MissionValidator,
        grounder: CapabilityGrounder,
        session_factory: Callable[[int], MissionSessionProtocol],
        protocol: Mapping[str, Any],
        recorder_root: str | None = None,
        seed: int = 0,
        provenance: Mapping[str, Any] | None = None,
        walk_strict_gate: bool = False,
        physical_halt_contract: Mapping[str, Any] | None = None,
    ) -> None:
        self.validator = validator
        self.grounder = grounder
        self.session_factory = session_factory
        self.protocol = dict(protocol)
        self.recorder_root = recorder_root
        self.seed = int(seed)
        self.provenance = dict(provenance or {})
        self.walk_strict_gate = bool(walk_strict_gate)
        if physical_halt_contract is not None and not self.walk_strict_gate:
            raise ValueError("Physical halt requires the strict walk feedback gate")
        self.physical_halt_contract = (
            dict(physical_halt_contract) if physical_halt_contract is not None else None
        )
        self.last_graph: TaskGraph | None = None

    # ------------------------------------------------------------------
    def run(
        self,
        mission_input: Mapping[str, Any] | Mission,
        *,
        phase: str = "final",
        write_evidence: bool = True,
        existing_session: MissionSessionProtocol | None = None,
    ) -> MissionResult:
        started_at = utc_timestamp()
        started = time.perf_counter()
        mission_id = "unparsed-mission"
        if isinstance(mission_input, Mission):
            mission_id = mission_input.mission_id
        elif isinstance(mission_input, Mapping):
            candidate = mission_input.get("mission_id")
            if isinstance(candidate, str) and is_path_safe_mission_id(candidate):
                mission_id = candidate
        recorder: MissionRecorder | None = None
        if write_evidence and self.recorder_root:
            recorder = MissionRecorder(self.recorder_root, mission_id)

        def log(event: str, payload: dict[str, Any] | None = None) -> None:
            if recorder is not None:
                recorder.log_event(event, payload)

        log("mission_received", {"phase": phase, "input": self._plain(mission_input)})

        mission: Mission | None = None
        try:
            mission = (
                mission_input
                if isinstance(mission_input, Mission)
                else Mission.from_dict(mission_input)
            )
        except MissionIRError as exc:
            return self._reject(
                mission_id=mission_id,
                failure_type=MissionFailureType.VALIDATION_FAILURE,
                reason=str(exc),
                horizon=0,
                recorder=recorder,
                log=log,
                started=started,
                started_at=started_at,
                phase=phase,
            )

        report = self.validator.validate(mission)
        validation_payload = report.to_dict()
        if not report.valid:
            log("validation_rejected", validation_payload)
            return self._reject(
                mission_id=mission.mission_id,
                failure_type=MissionFailureType.VALIDATION_FAILURE,
                reason="; ".join(issue.message for issue in report.issues),
                horizon=mission.horizon,
                recorder=recorder,
                log=log,
                started=started,
                started_at=started_at,
                phase=phase,
                validation=validation_payload,
                mission_input=mission.to_dict(),
            )
        log("validation_passed", {"issues": []})

        plan = self.grounder.ground_mission(mission)
        grounding_payload = plan.to_dict()
        if not plan.grounded:
            log("capability_rejected", grounding_payload)
            return self._reject(
                mission_id=mission.mission_id,
                failure_type=MissionFailureType(plan.status),
                reason="; ".join(result.reason for result in plan.results if not result.supported),
                horizon=mission.horizon,
                recorder=recorder,
                log=log,
                started=started,
                started_at=started_at,
                phase=phase,
                validation=validation_payload,
                grounding=grounding_payload,
                mission_input=mission.to_dict(),
            )
        log("capability_grounded", grounding_payload)

        graph = TaskGraph.from_mission(mission, plan)
        self.last_graph = graph
        nodes_payload: list[dict[str, Any]] = []
        transitions: list[dict[str, Any]] = []
        failure_type: MissionFailureType | None = None
        failure_reason: str | None = None
        failed_node: str | None = None
        physical_halt: dict[str, Any] | None = None
        session = None
        try:
            # Explicit lifecycle opt-in: the caller owns and eventually closes
            # this live session. Ordinary mission dispatch keeps its lifecycle.
            session = existing_session if existing_session is not None else self.session_factory(self.seed)
            previous_node = None
            while True:
                graph.refresh_ready()
                ready = graph.ready_nodes()
                if not ready:
                    break
                node = ready[0]
                graph.mark_running(node.node_id)
                log("node_ready", {"node_id": node.node_id, "skill": node.skill.value})
                log(
                    "node_start",
                    {
                        "node_id": node.node_id,
                        "skill": node.skill.value,
                        "execution_mode": node.execution_mode,
                        "risk": node.risk,
                    },
                )
                start_state = session.state().to_dict()
                log("skill_start", {"node_id": node.node_id, "skill": node.skill.value})
                try:
                    execution = session.run_node(node, node.execution_mode)
                except (SimulationStateError, InvalidControlError) as exc:
                    execution = None
                    failure_type = MissionFailureType.INVALID_STATE
                    failure_reason = f"{type(exc).__name__}: {exc}"
                except G1SimulationError as exc:
                    execution = None
                    failure_type = MissionFailureType.SKILL_FAILURE
                    failure_reason = f"{type(exc).__name__}: {exc}"
                except Exception as exc:  # safety net, recorded as INTERNAL_ERROR
                    execution = None
                    failure_type = MissionFailureType.INTERNAL_ERROR
                    failure_reason = f"{type(exc).__name__}: {exc}"
                if execution is None:
                    synthetic = {"skill": node.skill.value, "status": "INTERNAL", "reason": failure_reason}
                    graph.mark_failed(
                        node.node_id, result=synthetic, start_state=start_state, end_state=start_state
                    )
                    failed_node = node.node_id
                    log("node_failure", {"node_id": node.node_id, "reason": failure_reason})
                    break
                log(
                    "skill_end",
                    {"node_id": node.node_id, "status": execution.status, "reason": execution.reason},
                )
                if previous_node is not None:
                    transition = self._transition(
                        previous_node, node, previous_end_state, start_state
                    )
                    transitions.append(transition)
                    log("transition_checkpoint", transition)
                gate_decision = None
                if (
                    self.walk_strict_gate
                    and node.skill.value == "walk_forward"
                    and execution.status == SkillStatus.SUCCESS.value
                    and execution.physical_success
                ):
                    evaluation = STRICT_WALK_ENVELOPE.evaluate(
                        execution.metrics, float(node.parameters["distance_m"])
                    )
                    gate_decision = {
                        "action": "CONTINUE" if evaluation.satisfied else "STOP_DEPENDENTS",
                        "reason": "strict_walk_envelope_satisfied" if evaluation.satisfied else "strict_walk_envelope_violated",
                        "observed_metrics": {
                            key: execution.metrics[key]
                            for key in ("distance_error_m", "lateral_drift_m", "heading_error_deg", "simulation_time_s")
                        },
                        "evaluation": evaluation.to_dict(),
                        "evaluator": "g1swarm.boundary.envelope.STRICT_WALK_ENVELOPE",
                        "provenance": dict(self.provenance),
                    }
                    log("feedback_decision", {"node_id": node.node_id, **gate_decision})
                gate_passed = gate_decision is None or gate_decision["action"] == "CONTINUE"
                if execution.status == SkillStatus.SUCCESS.value and execution.physical_success and gate_passed:
                    graph.mark_success(
                        node.node_id,
                        result=execution.to_dict(),
                        start_state=start_state,
                        end_state=execution.end_state,
                    )
                    nodes_payload.append(self._node_payload(node, execution, decision=gate_decision))
                    log("node_success", {"node_id": node.node_id, "skill": node.skill.value})
                    previous_node = node
                    previous_end_state = execution.end_state
                    continue
                graph.mark_failed(
                    node.node_id,
                    result=execution.to_dict(),
                    start_state=start_state,
                    end_state=execution.end_state,
                )
                nodes_payload.append(self._node_payload(node, execution, decision=gate_decision))
                blocked = graph.block_descendants(node.node_id)
                failed_node = node.node_id
                failure_type = (
                    MissionFailureType.TASK_ENVELOPE_VIOLATION
                    if not gate_passed and execution.status == SkillStatus.SUCCESS.value and execution.physical_success
                    else self._attribute_failure(node, execution, first=previous_node is None)
                )
                failure_reason = (
                    ", ".join(gate_decision["evaluation"]["violations"])
                    if failure_type is MissionFailureType.TASK_ENVELOPE_VIOLATION
                    else execution.reason or execution.status
                )
                log(
                    "node_failure",
                    {
                        "node_id": node.node_id,
                        "skill": node.skill.value,
                        "status": execution.status,
                        "failure_type": failure_type.value,
                        "blocked": blocked,
                    },
                )
                if (
                    self.physical_halt_contract is not None
                    and gate_decision is not None
                    and gate_decision["action"] == "STOP_DEPENDENTS"
                ):
                    log("physical_halt_requested", {
                        "trigger_node_id": node.node_id,
                        "trigger_action": gate_decision["action"],
                        "blocked_task_nodes": blocked,
                        "pre_halt_state": session.state().to_dict(),
                        "provenance": dict(self.provenance),
                    })
                    try:
                        physical_halt = session.run_failure_halt(self.physical_halt_contract)
                    except Exception as exc:
                        physical_halt = {
                            "request": "EXPLICIT_INDEPENDENT_PHYSICAL_HALT",
                            "status": "HALT_FAILED",
                            "failure_stage": "runtime_halt_dispatch",
                            "failure_type": type(exc).__name__,
                            "failure_reason": str(exc),
                        }
                    physical_halt["trigger_node_id"] = node.node_id
                    physical_halt["trigger_action"] = gate_decision["action"]
                    physical_halt["blocked_task_nodes"] = blocked
                    physical_halt["provenance"] = dict(self.provenance)
                    log(
                        "physical_halt_succeeded" if physical_halt["status"] == "HALT_SUCCEEDED"
                        else "physical_halt_failed",
                        physical_halt,
                    )
                break
        except Exception as exc:  # pragma: no cover - defensive
            failure_type = MissionFailureType.INTERNAL_ERROR
            failure_reason = f"{type(exc).__name__}: {exc}"
        finally:
            if session is not None and existing_session is None:
                session.close()

        mission_success = graph.all_succeeded()
        state = MissionState.SUCCESS.value if mission_success else MissionState.FAILED.value
        if not mission_success and failure_type is None:
            failure_type = MissionFailureType.INTERNAL_ERROR
            failure_reason = failure_reason or "mission ended without a classified node failure"
        physical = all(
            bool(node_payload["metrics"]["physical_success"]) for node_payload in nodes_payload
        )
        result = MissionResult(
            mission_id=mission.mission_id,
            mission_schema_version=mission.schema_version,
            horizon=mission.horizon,
            state=state,
            mission_success=mission_success,
            failure_type=None if mission_success else failure_type.value if failure_type else None,
            failure_reason=None if mission_success else failure_reason,
            completed_nodes=sum(
                1 for node in graph.nodes if node.state is NodeState.SUCCESS
            ),
            failed_node=failed_node,
            total_simulation_time_s=sum(
                node_payload["metrics"]["simulation_time_s"] for node_payload in nodes_payload
            ),
            total_wall_time_s=time.perf_counter() - started,
            skill_invocations=len(nodes_payload),
            physical_success=physical,
            path_length_m=sum(
                node_payload["metrics"].get("path_length_m", 0.0) for node_payload in nodes_payload
            ),
            transition_count=len(transitions),
            controller_memory_resets=sum(
                node_payload["metrics"]["controller_memory_resets"]
                for node_payload in nodes_payload
            ),
            simulation_steps_executed=sum(
                node_payload["metrics"].get("simulation_steps", 0) for node_payload in nodes_payload
            ),
            nodes=tuple(nodes_payload),
            transitions=tuple(transitions),
            grounding=grounding_payload,
            map_hashes=dict(plan.map_hashes),
            validation=validation_payload,
            physical_halt=physical_halt,
        )
        log("mission_success" if mission_success else "mission_failure", result.to_dict())
        self._write_evidence(
            recorder,
            mission=mission,
            result=result,
            graph=graph,
            plan=plan,
            phase=phase,
            started_at=started_at,
        )
        return result

    # ------------------------------------------------------------------
    def _attribute_failure(self, node, execution: NodeExecution, *, first: bool) -> MissionFailureType:
        status = execution.status
        if status == SkillStatus.NOT_AVAILABLE.value:
            return MissionFailureType.UNSUPPORTED_SKILL
        if status == SkillStatus.PRECONDITION_FAILED.value:
            return (
                MissionFailureType.PRECONDITION_FAILURE
                if first
                else MissionFailureType.TRANSITION_FAILURE
            )
        if status == SkillStatus.TIMEOUT.value:
            return MissionFailureType.MISSION_TIMEOUT
        if status in {"NON_FINITE_STATE", "INVALID_CONTROL"}:
            return MissionFailureType.INVALID_STATE
        if status == "UNSAFE":
            return MissionFailureType.SKILL_FAILURE
        if not execution.physical_success:
            return MissionFailureType.INVALID_STATE
        return MissionFailureType.SKILL_FAILURE

    @staticmethod
    def _transition(previous_node, node, previous_end_state, next_start_state) -> dict[str, Any]:
        return {
            "previous_skill": previous_node.skill.value,
            "next_skill": node.skill.value,
            "previous_node_id": previous_node.node_id,
            "next_node_id": node.node_id,
            "previous_end_state": previous_end_state,
            "next_start_state": next_start_state,
            "position_delta_m": [
                float(next_start_state["base_position"][index])
                - float(previous_end_state["base_position"][index])
                for index in range(3)
            ],
            "heading_delta_deg": wrap_angle_deg(
                yaw_deg(next_start_state["base_orientation"])
                - yaw_deg(previous_end_state["base_orientation"])
            ),
            "controller_memory_reset": 1,
        }

    @staticmethod
    def _node_payload(node, execution: NodeExecution, *, decision=None) -> dict[str, Any]:
        payload = {
            "node_id": node.node_id,
            "skill": node.skill.value,
            "execution_mode": node.execution_mode,
            "risk": node.risk,
            "depends_on": list(node.depends_on),
            "metrics": dict(execution.metrics),
            "transitions": [],
        }
        if decision is not None:
            payload["feedback_decision"] = decision
        return payload

    def _reject(
        self,
        *,
        mission_id: str,
        failure_type: MissionFailureType,
        reason: str,
        horizon: int,
        recorder: MissionRecorder | None,
        log: Callable[[str, dict[str, Any] | None], None],
        started: float,
        started_at: str,
        phase: str,
        validation: dict[str, Any] | None = None,
        grounding: dict[str, Any] | None = None,
        mission_input: dict[str, Any] | None = None,
    ) -> MissionResult:
        result = MissionResult(
            mission_id=mission_id,
            mission_schema_version=MISSION_SCHEMA_VERSION,
            horizon=horizon,
            state=MissionState.REJECTED.value,
            mission_success=False,
            failure_type=failure_type.value,
            failure_reason=reason,
            completed_nodes=0,
            failed_node=None,
            total_simulation_time_s=0.0,
            total_wall_time_s=time.perf_counter() - started,
            skill_invocations=0,
            physical_success=True,
            path_length_m=0.0,
            transition_count=0,
            controller_memory_resets=0,
            simulation_steps_executed=0,
            grounding=grounding or {},
            validation=validation or {},
            map_hashes=dict(self.grounder.map_hashes),
        )
        log("mission_rejected", result.to_dict())
        if recorder is not None:
            recorder.write_manifest(
                {
                    "mission_id": mission_id,
                    "mission_schema_version": MISSION_SCHEMA_VERSION,
                    "phase": phase,
                    "git_commit": self.provenance.get("git_commit"),
                    "protocol_path": self.protocol.get("protocol_path"),
                    "protocol_sha256": self.protocol.get("_protocol_sha256"),
                    "provenance": dict(self.provenance),
                    "map_hashes": dict(self.grounder.map_hashes),
                    "mission_input": mission_input,
                    "grounded_plan": grounding or {},
                    "validation": validation or {},
                    "started_at": started_at,
                    "finished_at": utc_timestamp(),
                    "result": result.to_dict(),
                }
            )
            recorder.write_task_graph({"nodes": [], "execution_order": [], "rejected": True})
            recorder.write_summary(result.to_dict())
        return result

    def _write_evidence(
        self,
        recorder: MissionRecorder | None,
        *,
        mission: Mission,
        result: MissionResult,
        graph: TaskGraph,
        plan: GroundedPlan,
        phase: str,
        started_at: str,
    ) -> None:
        if recorder is None:
            return
        recorder.write_manifest(
            {
                "mission_id": mission.mission_id,
                "mission_schema_version": mission.schema_version,
                "phase": phase,
                "git_commit": self.provenance.get("git_commit"),
                "protocol_path": self.protocol.get("protocol_path"),
                "protocol_sha256": self.protocol.get("_protocol_sha256"),
                "provenance": dict(self.provenance),
                "map_hashes": dict(plan.map_hashes),
                "mission_input": mission.to_dict(),
                "grounded_plan": plan.to_dict(),
                "validation": result.validation,
                "started_at": started_at,
                "finished_at": utc_timestamp(),
                "result": result.to_dict(),
            }
        )
        recorder.write_task_graph(graph.to_dict())
        recorder.write_summary(result.to_dict())

    @staticmethod
    def _plain(value: Any) -> Any:
        if isinstance(value, Mission):
            return value.to_dict()
        if isinstance(value, Mapping):
            return {str(key): MissionExecutor._plain(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [MissionExecutor._plain(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return repr(value)
