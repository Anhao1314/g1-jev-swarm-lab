"""Canonical Mission IR (Phase 2.0).

Schema version ``2.0.0``. The IR is a pure, typed description of *what* the
mission should do. It contains no controller, simulator or execution-strategy
details: capability grounding selects the execution mode later.

Supported skills are exactly the ones with real, validated capability in this
repository: ``stand``, ``walk_forward``, ``turn``, ``stop``. Planning,
navigation, language and manipulation fields do not exist by construction.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

MISSION_SCHEMA_VERSION = "2.0.0"
MAX_MISSION_STEPS = 32
MISSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)

TOP_LEVEL_KEYS = frozenset({"schema_version", "mission_id", "steps"})


def is_path_safe_mission_id(value: str) -> bool:
    """Reject traversal and Win32 aliases that could mix evidence bundles."""

    if not MISSION_ID_PATTERN.match(value) or value.endswith("."):
        return False
    return value.split(".", 1)[0].upper() not in WINDOWS_RESERVED_NAMES
STEP_KEYS = frozenset({"id", "skill", "parameters", "depends_on", "execution_mode_override"})


class SkillName(str, Enum):
    STAND = "stand"
    WALK_FORWARD = "walk_forward"
    TURN = "turn"
    STOP = "stop"


class ExecutionModeOverride(str, Enum):
    """Experiment/replay-only override of the grounded execution mode."""

    OPEN_LOOP = "open_loop"
    HEADING_ONLY = "heading_only"
    HEADING_LATERAL = "heading_lateral"


# Parameter schema: name -> required-or-optional. Range limits live in the
# validator (schema sanity) and in capability grounding (real evidence).
PARAMETER_KEYS: dict[SkillName, frozenset[str]] = {
    SkillName.STAND: frozenset({"duration_s"}),
    SkillName.WALK_FORWARD: frozenset({"distance_m"}),
    SkillName.TURN: frozenset({"angle_deg"}),
    SkillName.STOP: frozenset(),
}
REQUIRED_PARAMETERS: dict[SkillName, frozenset[str]] = {
    SkillName.STAND: frozenset(),
    SkillName.WALK_FORWARD: frozenset({"distance_m"}),
    SkillName.TURN: frozenset({"angle_deg"}),
    SkillName.STOP: frozenset(),
}


class MissionIRError(ValueError):
    """The mission document is structurally invalid (typing/unknown keys)."""


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MissionIRError(f"{field_name} must be a mapping, got {type(value).__name__}")
    return value


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise MissionIRError(f"{field_name} must be a non-empty string")
    return value


def _require_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MissionIRError(f"{field_name} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise MissionIRError(f"{field_name} must be finite")
    return number


@dataclass(frozen=True)
class MissionStep:
    step_id: str
    skill: SkillName
    parameters: dict[str, float] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    execution_mode_override: ExecutionModeOverride | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.step_id, "skill": self.skill.value}
        payload["parameters"] = dict(self.parameters)
        if self.depends_on:
            payload["depends_on"] = list(self.depends_on)
        if self.execution_mode_override is not None:
            payload["execution_mode_override"] = self.execution_mode_override.value
        return payload


@dataclass(frozen=True)
class Mission:
    mission_id: str
    steps: tuple[MissionStep, ...]
    schema_version: str = MISSION_SCHEMA_VERSION

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Mission":
        document = _require_mapping(data, "mission")
        unknown = set(document) - TOP_LEVEL_KEYS
        if unknown:
            raise MissionIRError(f"unknown mission fields: {', '.join(sorted(unknown))}")
        schema_version = _require_str(document.get("schema_version"), "schema_version")
        if schema_version != MISSION_SCHEMA_VERSION:
            raise MissionIRError(
                f"unsupported mission schema_version {schema_version!r}; expected "
                f"{MISSION_SCHEMA_VERSION!r}"
            )
        mission_id = _require_str(document.get("mission_id"), "mission_id")
        if not is_path_safe_mission_id(mission_id):
            raise MissionIRError(
                "mission_id must be a non-reserved, non-trailing-dot name matching "
                "[A-Za-z0-9][A-Za-z0-9._-]{0,63} (path-safe)"
            )
        raw_steps = document.get("steps")
        if not isinstance(raw_steps, (list, tuple)):
            raise MissionIRError("steps must be a list")
        steps = tuple(cls._parse_step(index, item) for index, item in enumerate(raw_steps))
        return cls(mission_id=mission_id, steps=steps, schema_version=schema_version)

    @staticmethod
    def _parse_step(index: int, item: Any) -> MissionStep:
        step = _require_mapping(item, f"steps[{index}]")
        unknown = set(step) - STEP_KEYS
        if unknown:
            raise MissionIRError(
                f"steps[{index}] has unknown fields: {', '.join(sorted(unknown))}"
            )
        step_id = _require_str(step.get("id"), f"steps[{index}].id")
        raw_skill = _require_str(step.get("skill"), f"steps[{index}].skill")
        try:
            skill = SkillName(raw_skill)
        except ValueError as exc:
            raise MissionIRError(
                f"steps[{index}].skill {raw_skill!r} is not a supported skill "
                f"({', '.join(sorted(item.value for item in SkillName))})"
            ) from exc
        raw_parameters = step.get("parameters", {})
        parameters = _require_mapping(raw_parameters, f"steps[{index}].parameters")
        allowed = PARAMETER_KEYS[skill]
        unknown_parameters = set(parameters) - allowed
        if unknown_parameters:
            raise MissionIRError(
                f"steps[{index}].parameters has unknown fields for {skill.value}: "
                f"{', '.join(sorted(unknown_parameters))}"
            )
        missing = REQUIRED_PARAMETERS[skill] - set(parameters)
        if missing:
            raise MissionIRError(
                f"steps[{index}].parameters is missing: {', '.join(sorted(missing))}"
            )
        parsed_parameters = {
            key: _require_number(value, f"steps[{index}].parameters.{key}")
            for key, value in parameters.items()
        }
        raw_depends = step.get("depends_on", [])
        if not isinstance(raw_depends, (list, tuple)):
            raise MissionIRError(f"steps[{index}].depends_on must be a list")
        depends_on: list[str] = []
        for dependency in raw_depends:
            dependency_id = _require_str(dependency, f"steps[{index}].depends_on")
            if dependency_id not in depends_on:
                depends_on.append(dependency_id)
        override_raw = step.get("execution_mode_override")
        override: ExecutionModeOverride | None = None
        if override_raw is not None:
            if not isinstance(override_raw, str):
                raise MissionIRError(
                    f"steps[{index}].execution_mode_override must be a string or null"
                )
            try:
                override = ExecutionModeOverride(override_raw)
            except ValueError as exc:
                raise MissionIRError(
                    f"steps[{index}].execution_mode_override {override_raw!r} is not a known mode"
                ) from exc
        return MissionStep(
            step_id=step_id,
            skill=skill,
            parameters=parsed_parameters,
            depends_on=tuple(depends_on),
            execution_mode_override=override,
        )

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "steps": [step.to_dict() for step in self.steps],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "Mission":
        return cls.from_dict(json.loads(payload))

    @property
    def horizon(self) -> int:
        return len(self.steps)
