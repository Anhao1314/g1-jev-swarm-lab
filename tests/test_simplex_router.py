"""Tests for the Phase 2.2b simplex canonical router (Treatment D)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from g1swarm.language.benchmark import evaluate_compiler_sample
from g1swarm.language.compiler import LanguageCompiler
from g1swarm.language.errors import CompilerStatus, LanguageErrorCode
from g1swarm.language.result import CompilerResult
from g1swarm.llm.backend import ScriptedBackend
from g1swarm.mission.ir import MISSION_SCHEMA_VERSION, Mission, MissionStep, SkillName
from g1swarm.simplex.canonicalizer import LLMMissionCanonicalizer
from g1swarm.simplex.router import (
    GUARD_ERROR,
    GUARD_MALFORMED,
    GUARD_PASS,
    SimplexRoute,
    SimplexRouter,
)

OPEN_LANGUAGE_VALID = "麻烦往前走四米"
CANONICAL_TEXT = "前进4米"
MALFORMED_CONNECTORS = "前进4米然后然后停止"


@dataclass
class FakeGuardResult:
    status: str
    reason_code: str | None = None


class FakeGuard:
    def __init__(self, result):
        self.result = result
        self.calls: list[str] = []

    def check(self, text: str):
        self.calls.append(text)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class FakeCanonicalizationResult:
    status: str
    canonical_text: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    usage: dict | None = None
    raw_response: str | None = None
    error: str | None = None
    diagnostics: dict | None = None


class FakeCanonicalizer:
    model = "fake-model"
    prompt_sha256 = "0" * 64
    prompt_path = "prompts/fake.txt"

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[str] = []

    def canonicalize(self, text: str):
        self.calls.append(text)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeLark:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls: list[str] = []

    def compile(self, text: str) -> CompilerResult:
        self.calls.append(text)
        return self.mapping.get(
            text,
            CompilerResult(
                status=CompilerStatus.MALFORMED,
                normalized_text=text,
                error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
                error_message="fake parser rejected input",
            ),
        )


def _mission(skill: SkillName = SkillName.WALK_FORWARD, parameters=None) -> Mission:
    return Mission(
        mission_id="m-simplex-test",
        steps=(
            MissionStep(
                step_id="s1",
                skill=skill,
                parameters=dict(parameters or {"distance_m": 4.0}),
            ),
        ),
        schema_version=MISSION_SCHEMA_VERSION,
    )


def _success(text: str) -> CompilerResult:
    return CompilerResult(
        status=CompilerStatus.SUCCESS, mission=_mission(), normalized_text=text
    )


def _failure(status: CompilerStatus, code: LanguageErrorCode) -> CompilerResult:
    return CompilerResult(
        status=status,
        normalized_text="",
        error_code=code,
        error_message=f"fake {status.value}",
    )


def test_frozen_valid_input_uses_lark_fast_path_without_llm() -> None:
    guard = FakeGuard(FakeGuardResult(GUARD_PASS))
    canonicalizer = FakeCanonicalizer(FakeCanonicalizationResult("SUCCESS", CANONICAL_TEXT))
    router = SimplexRouter(
        guard=guard, canonicalizer=canonicalizer, lark_compiler=LanguageCompiler()
    )

    result = router.compile("站立")

    assert result.route is SimplexRoute.LARK_FAST_PATH
    assert result.status is CompilerStatus.SUCCESS
    assert result.mission is not None
    assert result.llm_invocations == 0
    assert canonicalizer.calls == []
    assert guard.calls == ["站立"]


def test_guard_reject_blocks_before_lark_and_llm() -> None:
    guard = FakeGuard(FakeGuardResult(GUARD_MALFORMED, "DUPLICATE_CONNECTOR"))
    canonicalizer = FakeCanonicalizer(FakeCanonicalizationResult("SUCCESS", CANONICAL_TEXT))
    lark = FakeLark({})
    router = SimplexRouter(guard=guard, canonicalizer=canonicalizer, lark_compiler=lark)

    result = router.compile(MALFORMED_CONNECTORS)

    assert result.route is SimplexRoute.GUARD_REJECT
    assert result.status is CompilerStatus.MALFORMED
    assert result.guard_status == GUARD_MALFORMED
    assert result.guard_reason_code == "DUPLICATE_CONNECTOR"
    assert result.error_code is LanguageErrorCode.LANGUAGE_PARSE_ERROR
    assert result.llm_invocations == 0
    assert lark.calls == []
    assert canonicalizer.calls == []


def test_guard_exception_fails_closed_without_llm() -> None:
    guard = FakeGuard(RuntimeError("guard exploded"))
    canonicalizer = FakeCanonicalizer(FakeCanonicalizationResult("SUCCESS", CANONICAL_TEXT))
    lark = FakeLark({})
    router = SimplexRouter(guard=guard, canonicalizer=canonicalizer, lark_compiler=lark)

    result = router.compile("前进4米")

    assert result.route is SimplexRoute.GUARD_REJECT
    assert result.guard_status == GUARD_ERROR
    assert result.status is CompilerStatus.MALFORMED
    assert result.llm_invocations == 0
    assert lark.calls == []
    assert canonicalizer.calls == []
    assert result.diagnostics["failure_type"] == "GUARD_ERROR"


def test_escalation_canonicalizes_then_compiles_with_frozen_lark() -> None:
    guard = FakeGuard(FakeGuardResult(GUARD_PASS))
    canonicalizer = FakeCanonicalizer(
        FakeCanonicalizationResult("SUCCESS", CANONICAL_TEXT, usage={"total_tokens": 123})
    )
    router = SimplexRouter(
        guard=guard, canonicalizer=canonicalizer, lark_compiler=LanguageCompiler()
    )

    result = router.compile(OPEN_LANGUAGE_VALID)

    assert result.route is SimplexRoute.CANONICALIZED
    assert result.status is CompilerStatus.SUCCESS
    assert result.mission is not None
    assert result.canonical_text == CANONICAL_TEXT
    assert result.llm_invocations == 1
    assert result.provider_tokens == 123
    assert canonicalizer.calls == [OPEN_LANGUAGE_VALID]
    assert result.diagnostics["canonical_text_lark_accepted"] is True
    assert [step.skill for step in result.mission.steps] == [SkillName.WALK_FORWARD]


@pytest.mark.parametrize(
    ("canonical_status", "expected_status", "expected_code"),
    [
        ("AMBIGUOUS", CompilerStatus.AMBIGUOUS, LanguageErrorCode.AMBIGUOUS_COMMAND),
        (
            "UNSUPPORTED",
            CompilerStatus.UNSUPPORTED,
            LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY,
        ),
        ("MALFORMED", CompilerStatus.MALFORMED, LanguageErrorCode.LANGUAGE_PARSE_ERROR),
    ],
)
def test_canonicalizer_refusal_maps_status_without_second_lark(
    canonical_status: str, expected_status: CompilerStatus, expected_code: LanguageErrorCode
) -> None:
    guard = FakeGuard(FakeGuardResult(GUARD_PASS))
    canonicalizer = FakeCanonicalizer(FakeCanonicalizationResult(canonical_status))
    lark = FakeLark({OPEN_LANGUAGE_VALID: _failure(CompilerStatus.MALFORMED, LanguageErrorCode.LANGUAGE_PARSE_ERROR)})
    router = SimplexRouter(guard=guard, canonicalizer=canonicalizer, lark_compiler=lark)

    result = router.compile(OPEN_LANGUAGE_VALID)

    assert result.route is SimplexRoute.CANONICALIZER_REFUSAL
    assert result.status is expected_status
    assert result.error_code is expected_code
    assert result.llm_invocations == 1
    assert canonicalizer.calls == [OPEN_LANGUAGE_VALID]
    assert lark.calls == [OPEN_LANGUAGE_VALID]


def test_canonical_lark_reject_is_final_without_retry() -> None:
    guard = FakeGuard(FakeGuardResult(GUARD_PASS))
    canonicalizer = FakeCanonicalizer(
        FakeCanonicalizationResult("SUCCESS", "这不是受控语言")
    )
    lark = FakeLark(
        {
            OPEN_LANGUAGE_VALID: _failure(
                CompilerStatus.MALFORMED, LanguageErrorCode.LANGUAGE_PARSE_ERROR
            )
        }
    )
    router = SimplexRouter(guard=guard, canonicalizer=canonicalizer, lark_compiler=lark)

    result = router.compile(OPEN_LANGUAGE_VALID)

    assert result.route is SimplexRoute.CANONICAL_LARK_REJECT
    assert result.status is CompilerStatus.MALFORMED
    assert result.error_code is LanguageErrorCode.LANGUAGE_PARSE_ERROR
    assert result.llm_invocations == 1
    assert canonicalizer.calls == [OPEN_LANGUAGE_VALID]
    assert lark.calls == [OPEN_LANGUAGE_VALID, "这不是受控语言"]
    assert result.diagnostics["canonical_text_lark_accepted"] is False


def test_canonicalizer_transport_error_fails_closed() -> None:
    guard = FakeGuard(FakeGuardResult(GUARD_PASS))
    canonicalizer = FakeCanonicalizer(RuntimeError("connection reset"))
    lark = FakeLark({OPEN_LANGUAGE_VALID: _failure(CompilerStatus.MALFORMED, LanguageErrorCode.LANGUAGE_PARSE_ERROR)})
    router = SimplexRouter(guard=guard, canonicalizer=canonicalizer, lark_compiler=lark)

    result = router.compile(OPEN_LANGUAGE_VALID)

    assert result.route is SimplexRoute.CANONICALIZER_REFUSAL
    assert result.status is CompilerStatus.MALFORMED
    assert result.error_code is LanguageErrorCode.LLM_API_ERROR
    assert result.llm_invocations == 1
    assert result.diagnostics["failure_type"] == "CANONICALIZER_ERROR"
    assert canonicalizer.calls == [OPEN_LANGUAGE_VALID]


def test_empty_input_is_rejected_before_every_stage() -> None:
    guard = FakeGuard(FakeGuardResult(GUARD_PASS))
    canonicalizer = FakeCanonicalizer(FakeCanonicalizationResult("SUCCESS", CANONICAL_TEXT))
    lark = FakeLark({})
    router = SimplexRouter(guard=guard, canonicalizer=canonicalizer, lark_compiler=lark)

    result = router.compile("   ")

    assert result.route is SimplexRoute.GUARD_REJECT
    assert result.status is CompilerStatus.MALFORMED
    assert result.error_code is LanguageErrorCode.EMPTY_LANGUAGE_INPUT
    assert result.llm_invocations == 0
    assert guard.calls == []
    assert lark.calls == []
    assert canonicalizer.calls == []


def test_duck_typed_mapping_guard_result_is_accepted() -> None:
    guard = FakeGuard({"status": "MALFORMED", "reason_code": "TRAILING_CONNECTOR"})
    canonicalizer = FakeCanonicalizer(FakeCanonicalizationResult("SUCCESS", CANONICAL_TEXT))
    router = SimplexRouter(guard=guard, canonicalizer=canonicalizer, lark_compiler=FakeLark({}))

    result = router.compile("前进4米然后")

    assert result.route is SimplexRoute.GUARD_REJECT
    assert result.guard_reason_code == "TRAILING_CONNECTOR"


def test_at_most_one_llm_invocation_across_all_branches() -> None:
    scenarios = [
        (FakeGuardResult(GUARD_MALFORMED, "LEADING_CONNECTOR"), FakeCanonicalizationResult("SUCCESS", CANONICAL_TEXT)),
        (FakeGuardResult(GUARD_PASS), FakeCanonicalizationResult("AMBIGUOUS")),
        (FakeGuardResult(GUARD_PASS), FakeCanonicalizationResult("UNSUPPORTED")),
        (FakeGuardResult(GUARD_PASS), FakeCanonicalizationResult("SUCCESS", CANONICAL_TEXT)),
        (FakeGuardResult(GUARD_PASS), RuntimeError("timeout")),
    ]
    lark = FakeLark({})
    for guard_result, canonical_outcome in scenarios:
        router = SimplexRouter(
            guard=FakeGuard(guard_result),
            canonicalizer=FakeCanonicalizer(canonical_outcome),
            lark_compiler=lark,
        )
        result = router.compile("前进4米然后然后停止")
        assert result.llm_invocations <= 1


def test_router_result_is_scoring_compatible_with_frozen_benchmark() -> None:
    guard = FakeGuard(FakeGuardResult(GUARD_PASS))
    canonicalizer = FakeCanonicalizer(FakeCanonicalizationResult("SUCCESS", CANONICAL_TEXT))
    router = SimplexRouter(
        guard=guard, canonicalizer=canonicalizer, lark_compiler=LanguageCompiler()
    )
    sample = {
        "sample_id": "simplex-test-001",
        "group_id": "g-simplex-test",
        "category": "atomic_valid",
        "source": "test",
        "utterance": OPEN_LANGUAGE_VALID,
        "expected_compiler_status": "SUCCESS",
        "expected_error_code": None,
        "expected_mission": {
            "schema_version": MISSION_SCHEMA_VERSION,
            "steps": [
                {
                    "id": "s1",
                    "skill": "walk_forward",
                    "parameters": {"distance_m": 4.0},
                    "depends_on": [],
                }
            ],
        },
    }

    row = evaluate_compiler_sample(sample, router)

    assert row["actual_status"] == "SUCCESS"
    assert row["exact_ir_match"] is True
    assert row["invalid_language_reaching_robot"] is False
    assert row["latency_s"] >= 0.0


def test_typed_canonicalizer_error_status_maps_to_llm_api_error() -> None:
    guard = FakeGuard(FakeGuardResult(GUARD_PASS))
    canonicalizer = FakeCanonicalizer(
        FakeCanonicalizationResult(
            "ERROR",
            error="API_ERROR: connection reset",
            diagnostics={"failure_type": "API_ERROR", "attempts": 3},
        )
    )
    lark = FakeLark(
        {OPEN_LANGUAGE_VALID: _failure(CompilerStatus.MALFORMED, LanguageErrorCode.LANGUAGE_PARSE_ERROR)}
    )
    router = SimplexRouter(guard=guard, canonicalizer=canonicalizer, lark_compiler=lark)

    result = router.compile(OPEN_LANGUAGE_VALID)

    assert result.route is SimplexRoute.CANONICALIZER_REFUSAL
    assert result.status is CompilerStatus.MALFORMED
    assert result.error_code is LanguageErrorCode.LLM_API_ERROR
    assert result.llm_invocations == 1
    assert result.diagnostics["failure_type"] == "CANONICALIZER_ERROR"
    assert result.diagnostics["canonicalizer_failure_type"] == "API_ERROR"
    assert result.diagnostics["canonicalizer_diagnostics"]["attempts"] == 3
    assert lark.calls == [OPEN_LANGUAGE_VALID]


def test_router_integrates_with_real_canonicalizer_and_scripted_backend() -> None:
    envelope = json.dumps(
        {"status": "SUCCESS", "canonical_text": CANONICAL_TEXT, "error_code": None},
        ensure_ascii=False,
    )
    backend = ScriptedBackend({OPEN_LANGUAGE_VALID: envelope})
    canonicalizer = LLMMissionCanonicalizer(backend=backend)
    router = SimplexRouter(
        guard=FakeGuard(FakeGuardResult(GUARD_PASS)),
        canonicalizer=canonicalizer,
        lark_compiler=LanguageCompiler(),
    )

    result = router.compile(OPEN_LANGUAGE_VALID)

    assert result.route is SimplexRoute.CANONICALIZED
    assert result.status is CompilerStatus.SUCCESS
    assert result.canonical_text == CANONICAL_TEXT
    assert result.mission is not None
    assert result.llm_invocations == 1
    assert router.prompt_sha256 == canonicalizer.prompt_sha256
    assert isinstance(canonicalizer.prompt_path, Path)
    assert len(backend.requests) == 1


def test_missing_guard_is_recorded_as_skipped() -> None:
    canonicalizer = FakeCanonicalizer(FakeCanonicalizationResult("SUCCESS", CANONICAL_TEXT))
    router = SimplexRouter(
        canonicalizer=canonicalizer, lark_compiler=LanguageCompiler()
    )

    result = router.compile("站立")

    assert result.route is SimplexRoute.LARK_FAST_PATH
    assert result.guard_status == "SKIPPED"
    assert result.diagnostics["guard_missing"] is True
    assert result.llm_invocations == 0
