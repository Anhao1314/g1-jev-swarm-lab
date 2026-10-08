"""One bounded TEST_ONLY continuation after a measured failure and halt.

This layer neither recovers an old Task Graph nor authenticates a human
principal. A frozen experiment allowlist and an in-process, single-use
capability authorize a separate Oracle mission on the same live session.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .ir import Mission, MissionIRError
from .runtime import MissionExecutor, MissionResult


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def mission_sha256(mission: Mapping[str, Any] | Mission) -> str:
    parsed = mission if isinstance(mission, Mission) else Mission.from_dict(mission)
    return canonical_sha256(parsed.to_dict())


class _TestOnlyGrant:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<TEST_ONLY mission capability>"


class TestOnlyMissionAuthorizer:
    """Registry-backed experiment authority; no serialized bearer tokens."""

    __test__ = False

    def __init__(self, *, allowed_mission_sha256) -> None:
        self.allowed_mission_sha256 = frozenset(allowed_mission_sha256)
        self._issued: dict[_TestOnlyGrant, dict[str, Any]] = {}
        self._owners: dict[_TestOnlyGrant, tuple[MissionLifecycle, Any]] = {}
        self._consumed: set[_TestOnlyGrant] = set()

    def issue(self, lifecycle: "MissionLifecycle", mission) -> _TestOnlyGrant:
        assessment = lifecycle.assess(mission)
        if not assessment["eligible"]:
            raise ValueError("Cannot authorize: " + ",".join(assessment["reasons"]))
        if assessment["mission_sha256"] not in self.allowed_mission_sha256:
            raise ValueError("MISSION_NOT_IN_FROZEN_TEST_ONLY_ALLOWLIST")
        grant = _TestOnlyGrant()
        self._issued[grant] = lifecycle._binding(assessment)
        self._owners[grant] = (lifecycle, lifecycle.session)
        lifecycle._event("test_only_authorization_issued", {
            "authority": "FROZEN_EXPERIMENT_ALLOWLIST",
            "scope": "TEST_ONLY",
            "binding": self._issued[grant],
        })
        return grant

    def _consume(self, grant, binding: dict[str, Any], lifecycle: "MissionLifecycle") -> str | None:
        if grant is None:
            return "AUTHORIZATION_MISSING"
        if not isinstance(grant, _TestOnlyGrant) or grant not in self._issued:
            return "AUTHORIZATION_UNRECOGNIZED"
        if grant in self._consumed:
            return "AUTHORIZATION_REPLAY"
        owner, session = self._owners[grant]
        if owner is not lifecycle or session is not lifecycle.session:
            return "AUTHORIZATION_SESSION_MISMATCH"
        if self._issued[grant] != binding:
            return "AUTHORIZATION_BINDING_MISMATCH"
        self._consumed.add(grant)
        return None


class MissionLifecycle:
    """Assess and gate at most one new mission without reset or graph reuse."""

    def __init__(self, *, executor: MissionExecutor, session, parent_result: MissionResult,
                 session_id: str, parent_receipt_sha256: str | None = None) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        self.executor = executor
        self.session = session
        self.session_id = session_id
        self._parent_result = parent_result
        self.parent_result = deepcopy(parent_result.to_dict())
        self.parent_result_sha256 = canonical_sha256(self.parent_result)
        self.parent_receipt_sha256 = parent_receipt_sha256 or self.parent_result_sha256
        self._parent_graph = executor.last_graph
        if self._parent_graph is None:
            raise ValueError("A completed parent Task Graph is required")
        self.parent_graph = deepcopy(self._parent_graph.to_dict())
        self.parent_graph_sha256 = canonical_sha256(self.parent_graph)
        self._session_identity = id(session)
        self._simulation_identity = id(session.simulation)
        self._controller_identity = id(session.controller)
        try:
            self._halt_execution_sha256 = canonical_sha256(self._execution_snapshot())
        except (AttributeError, TypeError, ValueError):
            self._halt_execution_sha256 = None
        self.events: list[dict[str, Any]] = []
        self._dispatched = False

    def _event(self, event: str, payload: dict[str, Any]) -> None:
        try:
            simulation_time = self.session.simulation.get_robot_state().simulation_time
        except Exception:
            simulation_time = None
        self.events.append({"sequence": len(self.events), "event": event,
                            "session_id": self.session_id,
                            "parent_mission_id": self.parent_result["mission_id"],
                            "simulation_time_s": simulation_time,
                            "simulation_steps": getattr(self.session, "total_steps", None),
                            **deepcopy(payload)})

    def _execution_snapshot(self) -> dict[str, Any]:
        # Read-only experiment introspection, matching the existing pose
        # capture surface. No simulator/controller calls or policy evaluation.
        data = self.session.simulation._data
        snapshot = {name: [float(value) for value in getattr(data, name)]
                    for name in ("qpos", "qvel", "ctrl")}
        snapshot["time_s"] = float(data.time)
        controller = self.session.controller
        for name in ("_action", "_target"):
            if hasattr(controller, name):
                snapshot["controller" + name] = [float(value) for value in getattr(controller, name)]
        if hasattr(controller, "_counter"):
            snapshot["controller_counter"] = int(controller._counter)
        # allow_nan=False also rejects nonfinite raw joints omitted by RobotState.
        canonical_sha256(snapshot)
        return snapshot

    def assess(self, mission_input) -> dict[str, Any]:
        reasons: list[str] = []
        state = None
        step_count = getattr(self.session, "total_steps", None)
        validation = grounding = None
        mission_digest = None
        mission_id = None
        execution_digest = None
        try:
            if canonical_sha256(self._parent_result.to_dict()) != self.parent_result_sha256:
                reasons.append("PARENT_RESULT_CHANGED")
            if canonical_sha256(self.parent_result) != self.parent_result_sha256:
                reasons.append("PARENT_SNAPSHOT_CHANGED")
            if canonical_sha256(self._parent_graph.to_dict()) != self.parent_graph_sha256:
                reasons.append("PARENT_GRAPH_CHANGED")
            if canonical_sha256(self.parent_graph) != self.parent_graph_sha256:
                reasons.append("PARENT_GRAPH_SNAPSHOT_CHANGED")
            if id(self.session) != self._session_identity or id(self.session.simulation) != self._simulation_identity:
                reasons.append("SESSION_CHANGED")
            if id(self.session.controller) != self._controller_identity or self.session.controller is None:
                reasons.append("CONTROLLER_CHANGED_OR_UNAVAILABLE")
            if getattr(self.session.simulation, "closed", False):
                reasons.append("SESSION_CLOSED")
            execution_digest = canonical_sha256(self._execution_snapshot())
            if self._halt_execution_sha256 is None or execution_digest != self._halt_execution_sha256:
                reasons.append("EXECUTION_STATE_CHANGED")
            live = self.session.simulation.get_robot_state()
            state = live.to_dict()
            if not live.is_finite():
                reasons.append("NON_FINITE_STATE")
            if live.fallen or not live.standing:
                reasons.append("NOT_STANDING_OR_FALLEN")
            if not math.isfinite(live.speed()) or live.speed() > 0.10:
                reasons.append("NOT_HALTED_SPEED")
            if self.session.state().to_dict() != state:
                reasons.append("SESSION_STATE_STALE")
            if self.parent_result["state"] != "FAILED":
                reasons.append("PARENT_NOT_FAILED")
            halt = self.parent_result.get("physical_halt") or {}
            if halt.get("status") != "HALT_SUCCEEDED":
                reasons.append("HALT_NOT_SUCCEEDED")
            expected_checks = {"skill_success", "duration", "final_speed", "window_mean_speed",
                               "displacement", "finite_throughout", "standing_throughout", "no_fall_throughout"}
            if set(halt.get("checks", {})) != expected_checks or not all(value is True for value in halt["checks"].values()):
                reasons.append("HALT_ACCEPTANCE_NOT_MET")
            window_mean = float(halt.get("skill_metrics", {}).get("final_window_mean_speed_mps", math.inf))
            if not math.isfinite(window_mean) or window_mean > 0.10:
                reasons.append("HALT_WINDOW_SPEED_NOT_MET")
            if state != halt.get("final_state"):
                reasons.append("HALT_ENDPOINT_CHANGED")
        except Exception as exc:
            reasons.append("STATE_ASSESSMENT_ERROR:" + type(exc).__name__)
        try:
            mission = mission_input if isinstance(mission_input, Mission) else Mission.from_dict(mission_input)
            mission_id = mission.mission_id
            mission_digest = mission_sha256(mission)
            validation = self.executor.validator.validate(mission).to_dict()
            grounding = self.executor.grounder.ground_mission(mission).to_dict()
            if not validation["valid"]:
                reasons.append("NEW_MISSION_INVALID")
            if grounding["status"] != "GROUNDED":
                reasons.append("NEW_MISSION_NOT_GROUNDED")
            if any(item["experimental_override"] or item["risk"] not in {"LOW", "MEDIUM"}
                   for item in grounding["results"]):
                reasons.append("NEW_MISSION_UNSUPPORTED_RISK")
            if mission.mission_id == self.parent_result["mission_id"]:
                reasons.append("NEW_MISSION_ID_REUSED")
            old_ids = {node["node_id"] for node in self.parent_graph["nodes"]}
            if any(step.step_id in old_ids for step in mission.steps):
                reasons.append("OLD_NODE_IDS_REUSED")
            if self.executor.recorder_root and (Path(self.executor.recorder_root) / mission.mission_id).exists():
                reasons.append("NEW_EVIDENCE_PATH_EXISTS")
        except (MissionIRError, ValueError, KeyError, TypeError) as exc:
            reasons.append("MISSION_ASSESSMENT_ERROR:" + type(exc).__name__)
        if self._dispatched:
            reasons.append("CONTINUATION_ALREADY_DISPATCHED")
        # Nonfinite state is recorded for diagnosis but never canonicalized or authorized.
        assessment = {
            "eligible": not reasons, "reasons": reasons, "state": state,
            "simulation_steps": step_count, "mission_sha256": mission_digest,
            "new_mission_id": mission_id,
            "execution_state_sha256": execution_digest,
            "validation": validation, "grounding": grounding,
            "parent_result_sha256": self.parent_result_sha256,
            "parent_graph_sha256": self.parent_graph_sha256,
        }
        self._event("post_halt_assessment", assessment)
        return assessment

    def _binding(self, assessment: dict[str, Any]) -> dict[str, Any]:
        return {"session_id": self.session_id,
                "parent_receipt_sha256": self.parent_receipt_sha256,
                "parent_result_sha256": self.parent_result_sha256,
                "parent_graph_sha256": self.parent_graph_sha256,
                "mission_sha256": assessment["mission_sha256"],
                "assessment_sha256": canonical_sha256(assessment)}

    def dispatch(self, mission_input, *, authorization=None,
                 authorizer: TestOnlyMissionAuthorizer | None = None,
                 phase: str = "m22", write_evidence: bool = True) -> dict[str, Any]:
        # Dispatch the same privately copied document that was assessed and
        # bound; caller mutation cannot change the authorized task afterwards.
        mission_for_execution = deepcopy(mission_input)
        assessment = self.assess(mission_for_execution)
        reason = None
        if not assessment["eligible"]:
            reason = "ASSESSMENT_REJECTED"
        elif authorizer is None:
            reason = "AUTHORIZATION_MISSING"
        elif type(authorizer) is not TestOnlyMissionAuthorizer:
            reason = "AUTHORITY_UNRECOGNIZED"
        else:
            reason = authorizer._consume(authorization, self._binding(assessment), self)
        result = {"status": "ESCALATE" if reason else "NEW_MISSION_AUTHORIZED",
                  "reason": reason, "assessment": assessment,
                  "parent_result_sha256": self.parent_result_sha256,
                  "parent_graph_sha256": self.parent_graph_sha256,
                  "parent_mission_id": self.parent_result["mission_id"],
                  "new_mission_id": assessment["new_mission_id"],
                  "new_mission_result": None}
        if reason:
            self._event("new_mission_rejected", result)
            return result
        self._event("new_mission_authorized", {"scope": "TEST_ONLY", "binding": self._binding(assessment),
                                              "new_mission_id": assessment["new_mission_id"]})
        self._dispatched = True
        try:
            new_result = self.executor.run(mission_for_execution, existing_session=self.session,
                                           phase=phase, write_evidence=write_evidence)
        except Exception as exc:
            result.update(status="ESCALATE", reason="NEW_MISSION_EXECUTION_ERROR",
                          failure_type=type(exc).__name__, failure_reason=str(exc))
            self._event("new_mission_failed", result)
            return result
        result["new_mission_result"] = new_result.to_dict()
        result["status"] = "NEW_MISSION_COMPLETED" if new_result.mission_success else "ESCALATE"
        result["reason"] = None if new_result.mission_success else "NEW_MISSION_FAILED"
        result["parent_preserved"] = (
            canonical_sha256(self._parent_result.to_dict()) == self.parent_result_sha256
            and canonical_sha256(self._parent_graph.to_dict()) == self.parent_graph_sha256
        )
        self._event("new_mission_completed" if new_result.mission_success else "new_mission_failed", result)
        return result
