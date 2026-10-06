"""Static Mission Validator (Phase 2.0).

The validator performs *static legality* checks only - no simulator, no
capability knowledge. Schema-level sanity limits (for example the maximum turn
angle) are explicitly not capability claims: a mission may be schema-valid and
still be rejected later by capability grounding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ir import MAX_MISSION_STEPS, MISSION_ID_PATTERN, MISSION_SCHEMA_VERSION, Mission, SkillName

# Schema-level sanity limits (NOT robot capability limits).
DEFAULT_TURN_ANGLE_LIMIT_DEG = 180.0
DEFAULT_STAND_DURATION_LIMIT_S = 60.0


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    step_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "step_id": self.step_id}


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "issues": [issue.to_dict() for issue in self.issues]}

    @property
    def failure_type(self) -> str | None:
        return None if self.valid else "VALIDATION_FAILURE"


class MissionValidator:
    def __init__(
        self,
        *,
        max_steps: int = MAX_MISSION_STEPS,
        turn_angle_limit_deg: float = DEFAULT_TURN_ANGLE_LIMIT_DEG,
        stand_duration_limit_s: float = DEFAULT_STAND_DURATION_LIMIT_S,
    ) -> None:
        self.max_steps = int(max_steps)
        self.turn_angle_limit_deg = float(turn_angle_limit_deg)
        self.stand_duration_limit_s = float(stand_duration_limit_s)

    def validate(self, mission: Mission) -> ValidationReport:
        issues: list[ValidationIssue] = []
        if mission.schema_version != MISSION_SCHEMA_VERSION:
            issues.append(
                ValidationIssue(
                    "SCHEMA_VERSION_MISMATCH",
                    f"schema_version must be {MISSION_SCHEMA_VERSION!r}",
                )
            )
        if not MISSION_ID_PATTERN.match(mission.mission_id):
            issues.append(
                ValidationIssue("INVALID_MISSION_ID", "mission_id must be path-safe")
            )
        if not mission.steps:
            issues.append(ValidationIssue("EMPTY_MISSION", "mission must contain at least one step"))
        if len(mission.steps) > self.max_steps:
            issues.append(
                ValidationIssue(
                    "TOO_MANY_STEPS",
                    f"mission has {len(mission.steps)} steps; schema limit is {self.max_steps}",
                )
            )

        seen: dict[str, int] = {}
        for index, step in enumerate(mission.steps):
            if step.step_id in seen:
                issues.append(
                    ValidationIssue(
                        "DUPLICATE_STEP_ID",
                        f"step id {step.step_id!r} is used more than once",
                        step.step_id,
                    )
                )
            else:
                seen[step.step_id] = index

        for step in mission.steps:
            for dependency in step.depends_on:
                if dependency == step.step_id:
                    issues.append(
                        ValidationIssue(
                            "SELF_DEPENDENCY",
                            f"step {step.step_id!r} depends on itself",
                            step.step_id,
                        )
                    )
                elif dependency not in seen:
                    issues.append(
                        ValidationIssue(
                            "UNKNOWN_DEPENDENCY",
                            f"step {step.step_id!r} depends on unknown step {dependency!r}",
                            step.step_id,
                        )
                    )

        ordered = self._dependency_order(mission, seen)
        if ordered is None:
            issues.append(
                ValidationIssue("DEPENDENCY_CYCLE", "step dependencies contain a cycle")
            )
        elif ordered != [step.step_id for step in mission.steps]:
            # Dependencies must not require reordering: the IR is a linear
            # program whose dependencies only refer backwards.
            issues.append(
                ValidationIssue(
                    "FORWARD_DEPENDENCY",
                    "depends_on may only reference earlier steps in the mission",
                )
            )

        for step in mission.steps:
            if step.skill is SkillName.WALK_FORWARD:
                distance = step.parameters.get("distance_m")
                if distance is None or distance <= 0.0:
                    issues.append(
                        ValidationIssue(
                            "INVALID_DISTANCE",
                            f"walk_forward distance_m must be > 0, got {distance}",
                            step.step_id,
                        )
                    )
            elif step.skill is SkillName.TURN:
                angle = step.parameters.get("angle_deg")
                if angle is None or angle == 0.0:
                    issues.append(
                        ValidationIssue(
                            "INVALID_ANGLE",
                            f"turn angle_deg must be non-zero, got {angle}",
                            step.step_id,
                        )
                    )
                elif abs(angle) > self.turn_angle_limit_deg:
                    issues.append(
                        ValidationIssue(
                            "INVALID_ANGLE",
                            f"turn angle_deg {angle} exceeds the schema sanity limit "
                            f"{self.turn_angle_limit_deg} (not a capability claim)",
                            step.step_id,
                        )
                    )
            elif step.skill is SkillName.STAND:
                duration = step.parameters.get("duration_s")
                if duration is not None and (
                    duration <= 0.0 or duration > self.stand_duration_limit_s
                ):
                    issues.append(
                        ValidationIssue(
                            "INVALID_DURATION",
                            f"stand duration_s must be in (0, {self.stand_duration_limit_s}], "
                            f"got {duration}",
                            step.step_id,
                        )
                    )
        return ValidationReport(valid=not issues, issues=tuple(issues))

    @staticmethod
    def _dependency_order(mission: Mission, seen: dict[str, int]) -> list[str] | None:
        """Kahn topological order; None when a cycle exists."""

        remaining = {step.step_id: set(step.depends_on) for step in mission.steps}
        order: list[str] = []
        while remaining:
            ready = sorted(
                (step_id for step_id, deps in remaining.items() if not deps),
                key=lambda step_id: seen.get(step_id, 0),
            )
            if not ready:
                return None
            for step_id in ready:
                order.append(step_id)
                del remaining[step_id]
            for deps in remaining.values():
                deps.difference_update(ready)
        return order
