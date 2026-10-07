"""Deterministic Task Graph (Phase 2.0).

The first mission version is linear, but the graph is a real node/dependency
structure: nothing here is a bare ``for`` loop over steps, and the executor
never reorders nodes within one dependency level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .grounding import GroundedPlan, GroundingResult
from .ir import Mission, MissionStep, SkillName


class NodeState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class MissionState(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    GROUNDED = "GROUNDED"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


ALLOWED_NODE_TRANSITIONS: dict[NodeState, frozenset[NodeState]] = {
    NodeState.PENDING: frozenset({NodeState.READY, NodeState.BLOCKED}),
    NodeState.READY: frozenset({NodeState.RUNNING, NodeState.BLOCKED}),
    NodeState.RUNNING: frozenset({NodeState.SUCCESS, NodeState.FAILED}),
    NodeState.SUCCESS: frozenset(),
    NodeState.FAILED: frozenset(),
    NodeState.BLOCKED: frozenset(),
}


class InvalidStateTransition(RuntimeError):
    """A node was moved through an illegal state transition."""


@dataclass
class TaskNode:
    node_id: str
    skill: SkillName
    parameters: dict[str, float]
    execution_mode: str
    risk: str | None
    depends_on: tuple[str, ...] = ()
    execution_mode_override: str | None = None
    state: NodeState = NodeState.PENDING
    result: dict[str, Any] | None = None
    start_state: dict[str, Any] | None = None
    end_state: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "skill": self.skill.value,
            "parameters": dict(self.parameters),
            "execution_mode": self.execution_mode,
            "risk": self.risk,
            "depends_on": list(self.depends_on),
            "execution_mode_override": self.execution_mode_override,
            "state": self.state.value,
            "result": self.result,
            "start_state": self.start_state,
            "end_state": self.end_state,
        }


class TaskGraph:
    def __init__(self, nodes: list[TaskNode]) -> None:
        self.nodes = nodes
        self._by_id = {node.node_id: node for node in nodes}
        if len(self._by_id) != len(nodes):
            raise ValueError("duplicate node ids in task graph")
        self.execution_order: list[str] = []

    # ------------------------------------------------------------------
    @classmethod
    def from_mission(cls, mission: Mission, plan: GroundedPlan) -> "TaskGraph":
        if len(plan.results) != len(mission.steps):
            raise ValueError("grounded plan does not match mission steps")
        nodes = [
            cls._node_from(step, grounding)
            for step, grounding in zip(mission.steps, plan.results)
        ]
        return cls(nodes)

    @staticmethod
    def _node_from(step: MissionStep, grounding: GroundingResult) -> TaskNode:
        return TaskNode(
            node_id=step.step_id,
            skill=step.skill,
            parameters=dict(step.parameters),
            execution_mode=grounding.execution_mode or "open_loop",
            risk=grounding.risk,
            depends_on=step.depends_on,
            execution_mode_override=(
                step.execution_mode_override.value if step.execution_mode_override else None
            ),
        )

    # ------------------------------------------------------------------
    def get(self, node_id: str) -> TaskNode:
        try:
            return self._by_id[node_id]
        except KeyError as exc:  # pragma: no cover - validator prevents this
            raise KeyError(f"unknown node {node_id!r}") from exc

    def _set_state(self, node: TaskNode, new_state: NodeState) -> None:
        if new_state not in ALLOWED_NODE_TRANSITIONS[node.state]:
            raise InvalidStateTransition(
                f"node {node.node_id}: {node.state.value} -> {new_state.value} is not allowed"
            )
        node.state = new_state

    def refresh_ready(self) -> None:
        for node in self.nodes:
            if node.state is not NodeState.PENDING:
                continue
            if all(
                self._by_id[dependency].state is NodeState.SUCCESS
                for dependency in node.depends_on
            ):
                self._set_state(node, NodeState.READY)

    def ready_nodes(self) -> list[TaskNode]:
        """READY nodes in mission (insertion) order - deterministic."""

        return [node for node in self.nodes if node.state is NodeState.READY]

    def mark_running(self, node_id: str) -> TaskNode:
        node = self.get(node_id)
        self._set_state(node, NodeState.RUNNING)
        self.execution_order.append(node_id)
        return node

    def mark_success(
        self,
        node_id: str,
        *,
        result: dict[str, Any],
        start_state: dict[str, Any],
        end_state: dict[str, Any],
    ) -> TaskNode:
        node = self.get(node_id)
        self._set_state(node, NodeState.SUCCESS)
        node.result = dict(result)
        node.start_state = dict(start_state)
        node.end_state = dict(end_state)
        return node

    def mark_failed(
        self,
        node_id: str,
        *,
        result: dict[str, Any],
        start_state: dict[str, Any],
        end_state: dict[str, Any],
    ) -> TaskNode:
        node = self.get(node_id)
        self._set_state(node, NodeState.FAILED)
        node.result = dict(result)
        node.start_state = dict(start_state)
        node.end_state = dict(end_state)
        return node

    def block_descendants(self, node_id: str) -> list[str]:
        """Block every node that (transitively) depends on ``node_id``."""

        blocked: list[str] = []
        frontier = [node_id]
        while frontier:
            current = frontier.pop()
            for node in self.nodes:
                if current in node.depends_on and node.state in {
                    NodeState.PENDING,
                    NodeState.READY,
                }:
                    self._set_state(node, NodeState.BLOCKED)
                    blocked.append(node.node_id)
                    frontier.append(node.node_id)
        return sorted(blocked)

    def all_succeeded(self) -> bool:
        return all(node.state is NodeState.SUCCESS for node in self.nodes)

    def has_failure(self) -> bool:
        return any(node.state is NodeState.FAILED for node in self.nodes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "execution_order": list(self.execution_order),
            "all_succeeded": self.all_succeeded(),
            "has_failure": self.has_failure(),
        }
