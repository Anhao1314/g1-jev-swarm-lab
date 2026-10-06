"""Tests for the Phase 2.2b LLM mission canonicalizer."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from g1swarm.language.errors import LanguageErrorCode
from g1swarm.llm.backend import (
    FAILURE_API_ERROR,
    FAILURE_TIMEOUT,
    LLMBackendError,
    LLMBackendResponse,
    LLMConfigurationError,
)
from g1swarm.simplex.canonicalizer import (
    STATUS_AMBIGUOUS,
    STATUS_ERROR,
    STATUS_MALFORMED,
    STATUS_SUCCESS,
    STATUS_UNSUPPORTED,
    CanonicalizerContractError,
    LLMMissionCanonicalizer,
    parse_canonicalizer_envelope,
)
from g1swarm.simplex.router import SimplexRoute, SimplexRouter

PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "llm_mission_canonicalizer_v1.txt"
)


class FakeBackend:
    name = "fake"
    model = "fake-model-1"

    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def complete(self, *, system_prompt: str, user_text: str) -> LLMBackendResponse:
        self.calls.append({"system_prompt": system_prompt, "user_text": user_text})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMBackendResponse(
            text=item,
            model=self.model,
            latency_s=0.01,
            attempts=1,
            request_parameters={"temperature": 0.0, "max_output_tokens": 512},
            usage={"input_tokens": 20, "output_tokens": 10, "total_tokens": 42},
            response_id="resp-1",
            finish_reason="stop",
            provider_status="completed",
        )


def _canonicalizer(*responses: str | Exception) -> tuple[LLMMissionCanonicalizer, FakeBackend]:
    backend = FakeBackend(list(responses))
    canonicalizer = LLMMissionCanonicalizer(backend=backend, prompt_path=PROMPT_PATH)
    return canonicalizer, backend


def _success(text: str = "前进4米") -> str:
    return f'{{"status":"SUCCESS","canonical_text":"{text}","error_code":null}}'


def test_success_outcome_and_prompt_provenance() -> None:
    canonicalizer, backend = _canonicalizer(_success("先前进4米，然后停止"))
    outcome = canonicalizer.canonicalize("麻烦先往前走四米，然后停下来")

    assert outcome.success
    assert outcome.status == STATUS_SUCCESS
    assert outcome.canonical_text == "先前进4米，然后停止"
    assert outcome.error_code is None
    assert outcome.provider_tokens == 42
    assert outcome.raw_response == _success("先前进4米，然后停止")
    assert outcome.latency_s >= 0.0
    assert outcome.diagnostics["model"] == "fake-model-1"
    assert outcome.diagnostics["attempts"] == 1
    assert outcome.diagnostics["usage"]["total_tokens"] == 42
    assert canonicalizer.model == "fake-model-1"
    assert canonicalizer.prompt_version == "llm_mission_canonicalizer_v1"
    expected_hash = hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()
    assert canonicalizer.prompt_sha256 == expected_hash
    assert "canonicalizer" in canonicalizer.prompt_text
    assert backend.calls[0]["user_text"] == "麻烦先往前走四米，然后停下来"
    assert backend.calls[0]["system_prompt"] == canonicalizer.prompt_text


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        (STATUS_AMBIGUOUS, "AMBIGUOUS_COMMAND"),
        (STATUS_AMBIGUOUS, "MISSING_PARAMETER"),
        (STATUS_UNSUPPORTED, "UNSUPPORTED_LANGUAGE_CAPABILITY"),
        (STATUS_MALFORMED, "INVALID_UNIT"),
        (STATUS_MALFORMED, "MALFORMED_NUMBER"),
        (STATUS_MALFORMED, "CONTRADICTORY_COMMAND"),
        (STATUS_MALFORMED, "LANGUAGE_PARSE_ERROR"),
    ],
)
def test_typed_refusals_are_accepted(status: str, error_code: str) -> None:
    canonicalizer, _ = _canonicalizer(
        f'{{"status":"{status}","canonical_text":null,"error_code":"{error_code}"}}'
    )
    outcome = canonicalizer.canonicalize("往前走一点")
    assert outcome.status == status
    assert outcome.canonical_text is None
    assert outcome.error_code == error_code
    assert outcome.error is None


@pytest.mark.parametrize(
    "payload",
    [
        '{"status":"AMBIGUOUS","canonical_text":null,"error_code":"UNSUPPORTED_LANGUAGE_CAPABILITY"}',
        '{"status":"MALFORMED","canonical_text":null,"error_code":"AMBIGUOUS_COMMAND"}',
        '{"status":"UNSUPPORTED","canonical_text":null,"error_code":"LANGUAGE_PARSE_ERROR"}',
        '{"status":"MALFORMED","canonical_text":null,"error_code":"FLYING_NOT_ALLOWED"}',
        '{"status":"SUCCESS","canonical_text":"前进4米","error_code":"MISSING_PARAMETER"}',
        '{"status":"AMBIGUOUS","canonical_text":"前进4米","error_code":"AMBIGUOUS_COMMAND"}',
    ],
)
def test_inconsistent_envelopes_fail_closed(payload: str) -> None:
    canonicalizer, _ = _canonicalizer(payload)
    outcome = canonicalizer.canonicalize("往前走一点")
    assert outcome.status == STATUS_MALFORMED
    assert outcome.error_code == LanguageErrorCode.LANGUAGE_PARSE_ERROR.value
    assert outcome.error_message is not None
    assert "violated the contract" in outcome.error_message
    assert outcome.raw_response == payload
    assert outcome.diagnostics["failure_type"] == "MALFORMED_OUTPUT"


@pytest.mark.parametrize(
    "payload",
    [
        '```json\n{"status":"SUCCESS","canonical_text":"前进4米","error_code":null}\n```',
        '{"status":"SUCCESS","canonical_text":"前进4米","error_code":null} trailing',
        '["SUCCESS"]',
        '{"status":"SUCCESS","canonical_text":"前进4米","error_code":null,"extra":1}',
        '{"status":"SUCCESS","canonical_text":"前进4米"}',
        '{"status":"SUCCESS","canonical_text":"前进4米","error_code":NaN}',
        '{"status":"SUCCESS","canonical_text":"前进\\n4米","error_code":null}',
        '{"status":"SUCCESS","canonical_text":"","error_code":null}',
        '{"status":"FLYING","canonical_text":null,"error_code":"LANGUAGE_PARSE_ERROR"}',
    ],
)
def test_malformed_model_output_is_a_contract_failure(payload: str) -> None:
    with pytest.raises(CanonicalizerContractError):
        parse_canonicalizer_envelope(payload)


def test_output_bounds_are_enforced() -> None:
    with pytest.raises(CanonicalizerContractError):
        parse_canonicalizer_envelope(" " * 4096, max_output_chars=64)
    with pytest.raises(CanonicalizerContractError):
        parse_canonicalizer_envelope(_success("前" * 64), max_canonical_chars=32)


def test_input_guards_reject_before_any_model_call() -> None:
    canonicalizer, backend = _canonicalizer()

    empty = canonicalizer.canonicalize("   ")
    assert empty.status == STATUS_MALFORMED
    assert empty.error_code == LanguageErrorCode.EMPTY_LANGUAGE_INPUT.value

    non_string = canonicalizer.canonicalize(123)  # type: ignore[arg-type]
    assert non_string.status == STATUS_MALFORMED
    assert non_string.error_code == LanguageErrorCode.LANGUAGE_PARSE_ERROR.value

    oversized = canonicalizer.canonicalize("前" * 600)
    assert oversized.status == STATUS_MALFORMED
    assert oversized.error_code == LanguageErrorCode.INPUT_TOO_LONG.value

    assert backend.calls == []


def test_transport_failures_fail_closed() -> None:
    timeout_error = LLMBackendError(
        FAILURE_TIMEOUT, "provider timed out", attempts=3, retryable=True
    )
    canonicalizer, _ = _canonicalizer(timeout_error)
    outcome = canonicalizer.canonicalize("往前走四米")
    assert outcome.status == STATUS_ERROR
    assert outcome.error is not None and "provider timed out" in outcome.error
    assert outcome.diagnostics["failure_type"] == FAILURE_TIMEOUT
    assert outcome.diagnostics["attempts"] == 3

    canonicalizer, _ = _canonicalizer(RuntimeError("socket exploded"))
    outcome = canonicalizer.canonicalize("往前走四米")
    assert outcome.status == STATUS_ERROR
    assert outcome.error == "backend raised RuntimeError"
    assert outcome.diagnostics["failure_type"] == FAILURE_API_ERROR


def test_prompt_hash_mismatch_is_a_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        LLMMissionCanonicalizer(
            backend=FakeBackend([]),
            prompt_path=PROMPT_PATH,
            expected_prompt_sha256="0" * 64,
        )


def test_router_fast_path_never_calls_the_model() -> None:
    canonicalizer, backend = _canonicalizer()
    router = SimplexRouter(canonicalizer=canonicalizer)
    result = router.compile("前进4米")
    assert result.route is SimplexRoute.LARK_FAST_PATH
    assert result.success
    assert result.llm_invocations == 0
    assert backend.calls == []


def test_router_escalates_and_recompiles_canonical_text() -> None:
    canonicalizer, _ = _canonicalizer(_success("前进4米"))
    router = SimplexRouter(canonicalizer=canonicalizer)
    result = router.compile("麻烦往前走四米")
    assert result.route is SimplexRoute.CANONICALIZED
    assert result.success
    assert result.canonical_text == "前进4米"
    assert result.llm_invocations == 1
    assert result.diagnostics["canonical_text_lark_accepted"] is True


def test_router_treats_canonical_text_as_data_only() -> None:
    canonicalizer, _ = _canonicalizer(_success("起飞"))
    router = SimplexRouter(canonicalizer=canonicalizer)
    result = router.compile("麻烦起飞")
    assert result.route is SimplexRoute.CANONICAL_LARK_REJECT
    assert not result.success
    assert result.canonical_text == "起飞"
    assert result.llm_invocations == 1
    assert result.error_code is LanguageErrorCode.LANGUAGE_PARSE_ERROR


def test_router_maps_canonicalizer_refusal_to_a_typed_rejection() -> None:
    payload = (
        '{"status":"AMBIGUOUS","canonical_text":null,"error_code":"MISSING_PARAMETER"}'
    )
    canonicalizer, _ = _canonicalizer(payload)
    router = SimplexRouter(canonicalizer=canonicalizer)
    result = router.compile("往前走一点")
    assert result.route is SimplexRoute.CANONICALIZER_REFUSAL
    assert not result.success
    assert result.canonicalization_status == STATUS_AMBIGUOUS
    assert result.error_code is LanguageErrorCode.AMBIGUOUS_COMMAND
    assert result.llm_invocations == 1
