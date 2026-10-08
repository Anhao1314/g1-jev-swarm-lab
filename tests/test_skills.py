"""Skill contract and router tests (no simulator needed)."""

from __future__ import annotations

from typing import Any

from g1swarm.skills import (
    Skill,
    SkillContext,
    SkillRequest,
    SkillResult,
    SkillRouter,
    SkillStatus,
)


class _OkSkill(Skill):
    name = "ok"

    def run(self, context: SkillContext) -> SkillResult:
        return self.result(SkillStatus.SUCCESS, metrics={"seen": context.parameters.get("value", 0)})


class _UnavailableSkill(Skill):
    name = "unavailable"

    def available(self, context: SkillContext) -> bool:
        return False

    def unavailable_reason(self, context: SkillContext) -> str:
        return "not built in this phase"

    def run(self, context: SkillContext) -> SkillResult:  # pragma: no cover - never called
        raise AssertionError("unavailable skill must not run")


class _PreconditionSkill(Skill):
    name = "precondition"

    def check_preconditions(self, context: SkillContext) -> str:
        return "robot is not standing"

    def run(self, context: SkillContext) -> SkillResult:  # pragma: no cover - never called
        raise AssertionError("precondition skill must not run")


def _context() -> SkillContext:
    return SkillContext(simulation=None)  # type: ignore[arg-type]


def test_skill_result_semantics() -> None:
    success = SkillResult(skill="s", status=SkillStatus.SUCCESS)
    assert success.ok and success.terminal
    for status in (
        SkillStatus.FAILURE,
        SkillStatus.TIMEOUT,
        SkillStatus.INTERRUPTED,
        SkillStatus.UNSAFE,
        SkillStatus.NOT_AVAILABLE,
        SkillStatus.PRECONDITION_FAILED,
    ):
        result = SkillResult(skill="s", status=status)
        assert not result.ok
    running = SkillResult(skill="s", status=SkillStatus.RUNNING)
    assert not running.terminal
    assert running.to_dict()["status"] == "RUNNING"


def test_router_runs_valid_skill() -> None:
    router = SkillRouter([_OkSkill()])
    result = router.execute(SkillRequest("ok", {"value": 7}), _context())
    assert result.ok
    assert result.metrics["seen"] == 7
    assert isinstance(result.to_dict()["metrics"], dict)


def test_router_reports_unavailable_skill() -> None:
    router = SkillRouter([_UnavailableSkill()])
    result = router.execute("unavailable", _context())
    assert result.status is SkillStatus.NOT_AVAILABLE
    assert "not built" in (result.reason or "")


def test_router_reports_precondition_failure() -> None:
    router = SkillRouter([_PreconditionSkill()])
    result = router.execute("precondition", _context())
    assert result.status is SkillStatus.PRECONDITION_FAILED
    assert "standing" in (result.reason or "")


def test_router_rejects_unknown_and_invalid_requests() -> None:
    router = SkillRouter([_OkSkill()])
    unknown = router.execute("does-not-exist", _context())
    assert unknown.status is SkillStatus.FAILURE
    assert "unknown skill" in (unknown.reason or "")
    empty = router.execute(SkillRequest("   "), _context())
    assert empty.status is SkillStatus.FAILURE
    invalid: Any = 42
    result = router.execute(invalid, _context())
    assert result.status is SkillStatus.FAILURE
    assert "invalid skill request" in (result.reason or "")
