"""Skill router: maps a bounded request to a verified skill implementation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from ..simulation.errors import G1SimulationError
from .contract import Skill, SkillContext, SkillResult, SkillStatus


@dataclass(frozen=True)
class SkillRequest:
    skill_name: str
    parameters: dict[str, Any] = field(default_factory=dict)


class UnknownSkillError(KeyError):
    """Raised only when callers use the strict lookup API."""


class SkillRouter:
    """Owns the registered skills and enforces availability and preconditions.

    ``execute`` never raises for bad requests: it returns a structured failure
    status so the runtime can react safely (unknown skill, unavailable skill,
    failed precondition). Simulation errors raised inside a skill are converted
    to ``UNSAFE`` results instead of crashing the runtime loop.
    """

    def __init__(self, skills: Iterable[Skill] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        for skill in skills or ():
            self.register(skill)

    def register(self, skill: Skill) -> None:
        if not skill.name:
            raise ValueError("skill must define a non-empty name")
        if skill.name in self._skills:
            raise ValueError(f"skill already registered: {skill.name}")
        self._skills[skill.name] = skill

    @property
    def skill_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._skills))

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise UnknownSkillError(name) from exc

    def execute(self, request: SkillRequest | str, context: SkillContext) -> SkillResult:
        if isinstance(request, str):
            request = SkillRequest(request)
        if not isinstance(request, SkillRequest):
            return SkillResult(
                skill="<invalid>",
                status=SkillStatus.FAILURE,
                reason=f"invalid skill request: {type(request).__name__}",
            )
        name = request.skill_name.strip() if isinstance(request.skill_name, str) else ""
        if not name:
            return SkillResult(
                skill="<invalid>",
                status=SkillStatus.FAILURE,
                reason="invalid skill request: empty skill name",
            )
        skill = self._skills.get(name)
        if skill is None:
            return SkillResult(
                skill=name,
                status=SkillStatus.FAILURE,
                reason=f"unknown skill: {name}; available: {', '.join(self.skill_names) or 'none'}",
            )
        if not skill.available(context):
            return SkillResult(
                skill=name,
                status=SkillStatus.NOT_AVAILABLE,
                reason=skill.unavailable_reason(context) or "skill not available in this runtime",
            )
        precondition = skill.check_preconditions(context)
        if precondition:
            return SkillResult(
                skill=name,
                status=SkillStatus.PRECONDITION_FAILED,
                reason=precondition,
            )
        merged = {**context.parameters, **request.parameters}
        try:
            return skill.run(replace(context, parameters=merged))
        except G1SimulationError as exc:
            return SkillResult(
                skill=name,
                status=SkillStatus.UNSAFE,
                reason=f"simulation safety stop: {exc}",
            )
