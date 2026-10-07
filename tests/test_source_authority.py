"""Synthetic contract and release-boundary tests; no campaign oracle patterns."""

from __future__ import annotations

import copy
import json

import pytest

from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.llm.backend import LLMBackendError, LLMBackendResponse, ScriptedBackend
from g1swarm.mission.ir import Mission
from g1swarm.source_authority import (
    AUTHORITY_DIMENSIONS,
    AuthorizationResult,
    AuthorizationStatus,
    LLMSemanticAmbiguityGate,
    LLMSourceAuthorizationVerifier,
    apply_gate,
    source_authorization,
)

SOURCE = "站立3秒，然后前进6米。"


def _steps() -> list[dict]:
    return [
        {"id": "s1", "skill": "stand", "parameters": {"duration_s": 3.0}, "depends_on": []},
        {"id": "s2", "skill": "walk_forward", "parameters": {"distance_m": 6.0}, "depends_on": ["s1"]},
    ]


def _mission(steps: list[dict] | None = None, mission_id: str = "candidate") -> Mission:
    return Mission.from_dict({"schema_version": "2.0.0", "mission_id": mission_id, "steps": steps or _steps()})


def _payload(*, source_aware: bool = True, source: str = SOURCE, status: str = "AUTHORIZED_UNIQUE") -> dict:
    dimensions = {name: {"status": "UNIQUE", "explanation": "Source establishes this relation or leaves it inapplicable."}
                  for name in AUTHORITY_DIMENSIONS}
    if status != "AUTHORIZED_UNIQUE":
        dimensions["unresolved_relations"]["status"] = status
    payload = {
        "status": status,
        "coverage": [{"text": source, "role": "ACTION", "explanation": "All requested actions and sequencing considered."}],
        "dimensions": dimensions,
    }
    if source_aware:
        payload["authorized_plan"] = _steps() if status == "AUTHORIZED_UNIQUE" else None
    return payload


def _authorizer(payload: dict | str, *, source_aware: bool = True):
    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    backend = ScriptedBackend(lambda **_: raw)
    cls = LLMSourceAuthorizationVerifier if source_aware else LLMSemanticAmbiguityGate
    return cls(backend), backend


def _baseline(mission: Mission | None = None) -> CompilerResult:
    return CompilerResult(CompilerStatus.SUCCESS, mission or _mission(), SOURCE,
                          diagnostics={"architecture": "guarded_direct_llm_v1", "immutable_marker": "B"})


def test_authorized_exact_source_plan_releases_original_candidate() -> None:
    authorizer, backend = _authorizer(_payload())
    baseline = _baseline()
    before = copy.deepcopy(baseline.to_dict())
    result = apply_gate(SOURCE, baseline, authorizer)
    assert result.success
    assert result.mission is baseline.mission
    assert baseline.to_dict() == before
    assert result.diagnostics["released_executable"] is True
    assert result.diagnostics["source_authorization"]["status"] == "AUTHORIZED_UNIQUE"
    assert len(backend.requests) == 1
    request = json.loads(backend.requests[0]["user_text"])
    assert request["source"] == SOURCE
    assert request["candidate_ir"]["steps"] == _steps()


def test_source_only_gate_does_not_receive_or_claim_candidate_comparison() -> None:
    authorizer, backend = _authorizer(_payload(source_aware=False), source_aware=False)
    wrong = _steps()
    wrong[1]["parameters"]["distance_m"] = 7
    result = authorizer.authorize(SOURCE, _mission(wrong))
    assert result.authorized  # Deliberate treatment limitation, retained as evidence.
    assert json.loads(backend.requests[0]["user_text"]) == {"source": SOURCE}
    assert "plan_matches_candidate" not in result.diagnostics


@pytest.mark.parametrize("dimension", AUTHORITY_DIMENSIONS)
@pytest.mark.parametrize("state", ["AMBIGUOUS", "UNKNOWN"])
def test_each_nonunique_dimension_withholds_executable(dimension: str, state: str) -> None:
    payload = _payload(status=state)
    payload["dimensions"]["unresolved_relations"]["status"] = "UNIQUE"
    payload["dimensions"][dimension]["status"] = state
    authorizer, _ = _authorizer(payload)
    result = apply_gate(SOURCE, _baseline(), authorizer)
    assert result.mission is None
    assert result.diagnostics["released_executable"] is False
    assert result.diagnostics["source_authorization"]["status"] == state


def test_inconsistent_declared_authority_is_unknown() -> None:
    payload = _payload()
    payload["dimensions"]["unresolved_relations"]["status"] = "AMBIGUOUS"
    authorizer, _ = _authorizer(payload)
    result = authorizer.authorize(SOURCE, _mission())
    assert result.status is AuthorizationStatus.UNKNOWN
    assert result.reason_code == "VERIFIER_STATUS_DISAGREEMENT"


def test_ambiguity_takes_precedence_over_unknown_dimension() -> None:
    payload = _payload(status="AMBIGUOUS")
    payload["dimensions"]["reference_resolution"]["status"] = "UNKNOWN"
    authorizer, _ = _authorizer(payload)
    assert authorizer.authorize(SOURCE, _mission()).status is AuthorizationStatus.AMBIGUOUS


@pytest.mark.parametrize("changed", ["count", "order", "parameter", "skill", "dependency"])
def test_complete_plan_comparison_rejects_candidate_drift(changed: str) -> None:
    plan = _steps()
    if changed == "count":
        plan.append({"id": "s3", "skill": "stop", "parameters": {}, "depends_on": ["s2"]})
    elif changed == "order":
        plan[0]["skill"], plan[1]["skill"] = plan[1]["skill"], plan[0]["skill"]
        plan[0]["parameters"], plan[1]["parameters"] = plan[1]["parameters"], plan[0]["parameters"]
    elif changed == "parameter":
        plan[1]["parameters"]["distance_m"] = 9
    elif changed == "skill":
        plan[1]["skill"] = "turn"
        plan[1]["parameters"] = {"angle_deg": 6}
    else:
        plan[1]["depends_on"] = []  # Static legal IR; differs from authorized chain.
    authorizer, _ = _authorizer(_payload())
    result = apply_gate(SOURCE, _baseline(_mission(plan)), authorizer)
    assert result.mission is None
    assert result.diagnostics["source_authorization"]["reason_code"] == "AUTHORIZED_PLAN_DISAGREEMENT"


def test_mission_identity_and_integral_float_representation_are_ignored() -> None:
    payload = _payload()
    payload["authorized_plan"][0]["parameters"]["duration_s"] = 3
    payload["authorized_plan"][1]["parameters"]["distance_m"] = 6
    authorizer, _ = _authorizer(payload)
    assert authorizer.authorize(SOURCE, _mission(mission_id="another-identity")).authorized


@pytest.mark.parametrize("change", ["omit_suffix", "normalize_space", "reorder", "duplicate"])
def test_exact_original_source_coverage_is_required(change: str) -> None:
    source = " 站立3秒， 然后前进6米。\r\n"
    payload = _payload(source=source)
    if change == "omit_suffix":
        payload["coverage"][0]["text"] = source[:-1]
    elif change == "normalize_space":
        payload["coverage"][0]["text"] = source.strip()
    elif change == "reorder":
        payload["coverage"][0]["text"] = "然后前进6米。 站立3秒，\r\n"
    else:
        payload["coverage"].append(copy.deepcopy(payload["coverage"][0]))
    authorizer, _ = _authorizer(payload)
    result = authorizer.authorize(source, _mission())
    assert result.status is AuthorizationStatus.UNKNOWN
    assert result.reason_code == "INCOMPLETE_SOURCE_COVERAGE"


def test_multiple_coverage_segments_cover_whitespace_and_punctuation() -> None:
    source = " 站立3秒，然后前进6米。\n"
    payload = _payload(source=source)
    payload["coverage"] = [
        {"text": " ", "role": "SEPARATOR", "explanation": "Whitespace has no semantic effect."},
        {"text": "站立3秒", "role": "ACTION", "explanation": "Stand for specified duration."},
        {"text": "，然后", "role": "RELATION", "explanation": "Next action follows standing."},
        {"text": "前进6米", "role": "ACTION", "explanation": "Walk the specified distance."},
        {"text": "。\n", "role": "SEPARATOR", "explanation": "Trailing punctuation and whitespace."},
    ]
    authorizer, _ = _authorizer(payload)
    assert authorizer.authorize(source, _mission()).authorized


@pytest.mark.parametrize("raw", ["", "not json", "[]", "{}", "null", "```json\n{}\n```", "{} {}", "{\"status\":NaN}", "{\"status\":1e999}", "{\"status\":\"UNKNOWN\",\"status\":\"AUTHORIZED_UNIQUE\"}"])
def test_unusable_model_outputs_fail_closed_without_repair(raw: str) -> None:
    authorizer, backend = _authorizer(raw)
    result = apply_gate(SOURCE, _baseline(), authorizer)
    assert result.mission is None
    assert result.diagnostics["source_authorization"]["status"] == "UNKNOWN"
    assert len(backend.requests) == 1


@pytest.mark.parametrize("change", ["missing_dimension", "extra_dimension", "confidence", "empty_explanation", "invalid_role", "missing_plan", "duplicate_dependency", "unknown_skill", "wrong_step_id", "extra_step_field", "invalid_parameter", "nonlinear_plan"])
def test_strict_witness_and_plan_schema(change: str) -> None:
    payload = _payload()
    if change == "missing_dimension":
        del payload["dimensions"]["action_order"]
    elif change == "extra_dimension":
        payload["dimensions"]["confidence"] = {"status": "UNIQUE", "explanation": "invented"}
    elif change == "confidence":
        payload["confidence"] = 1.0
    elif change == "empty_explanation":
        payload["dimensions"]["action_order"]["explanation"] = " "
    elif change == "invalid_role":
        payload["coverage"][0]["role"] = "IGNORE"
    elif change == "missing_plan":
        del payload["authorized_plan"]
    elif change == "duplicate_dependency":
        payload["authorized_plan"][1]["depends_on"] = ["s1", "s1"]
    elif change == "unknown_skill":
        payload["authorized_plan"][1]["skill"] = "teleport"
    elif change == "wrong_step_id":
        payload["authorized_plan"][1]["id"] = "s1"
    elif change == "extra_step_field":
        payload["authorized_plan"][0]["execution_mode_override"] = "open_loop"
    elif change == "invalid_parameter":
        payload["authorized_plan"][1]["parameters"]["distance_m"] = True
    else:
        payload["authorized_plan"][1]["depends_on"] = []
    authorizer, _ = _authorizer(payload)
    assert not apply_gate(SOURCE, _baseline(), authorizer).success


@pytest.mark.parametrize("status", ["AMBIGUOUS", "UNKNOWN"])
def test_nonunique_response_cannot_carry_a_plan(status: str) -> None:
    payload = _payload(status=status)
    payload["authorized_plan"] = _steps()
    authorizer, _ = _authorizer(payload)
    result = authorizer.authorize(SOURCE, _mission())
    assert result.status is AuthorizationStatus.UNKNOWN
    assert result.reason_code == "NONUNIQUE_PLAN_MUST_BE_NULL"


class _RaisingBackend:
    model = "test"
    name = "raising"

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        raise self.error


@pytest.mark.parametrize("error", [LLMBackendError("TIMEOUT", "transport failure", attempts=3), RuntimeError("internal failure")])
def test_transport_and_unexpected_failures_withhold_mission(error: Exception) -> None:
    backend = _RaisingBackend(error)
    authorizer = LLMSourceAuthorizationVerifier(backend)
    result = apply_gate(SOURCE, _baseline(), authorizer)
    evidence = result.diagnostics["source_authorization"]
    assert result.mission is None
    assert evidence["status"] == "UNKNOWN"
    assert evidence["reason_code"] == "BACKEND_FAILURE"
    assert backend.calls == 1
    if isinstance(error, LLMBackendError):
        assert evidence["diagnostics"]["attempts"] == 3


def test_guard_failure_short_circuits_authorizer() -> None:
    backend = _RaisingBackend(AssertionError("must not call"))
    result = apply_gate("然后前进6米", _baseline(), LLMSourceAuthorizationVerifier(backend))
    assert result.mission is None
    assert backend.calls == 0
    assert result.diagnostics["source_authorization"]["reason_code"] == "GUARD_REJECT"


def test_invalid_candidate_short_circuits_authorizer() -> None:
    steps = _steps()
    steps[1]["parameters"]["distance_m"] = -2
    backend = _RaisingBackend(AssertionError("must not call"))
    result = apply_gate(SOURCE, _baseline(_mission(steps)), LLMSourceAuthorizationVerifier(backend))
    assert result.mission is None
    assert backend.calls == 0
    assert result.diagnostics["source_authorization"]["reason_code"] == "INVALID_CANDIDATE_IR"


def test_rejected_baseline_never_gains_a_mission_or_verifier_call() -> None:
    backend = _RaisingBackend(AssertionError("must not call"))
    baseline = CompilerResult(CompilerStatus.AMBIGUOUS, error_message="baseline ambiguity")
    result = apply_gate(SOURCE, baseline, LLMSourceAuthorizationVerifier(backend))
    assert result.status is CompilerStatus.AMBIGUOUS
    assert result.mission is None
    assert backend.calls == 0


def test_custom_authorizer_exception_fails_closed() -> None:
    class BrokenAuthorizer:
        treatment = "broken"

        def authorize(self, source, candidate_ir):
            raise ValueError("broken")

    assert source_authorization(SOURCE, _mission(), authorizer=BrokenAuthorizer()).status is AuthorizationStatus.UNKNOWN
    assert apply_gate(SOURCE, _baseline(), BrokenAuthorizer()).mission is None


def test_mutating_custom_authorizer_is_not_released() -> None:
    class MutatingAuthorizer:
        treatment = "mutating"

        def authorize(self, source, candidate_ir):
            candidate_ir.steps[1].parameters["distance_m"] = 100
            return AuthorizationResult(AuthorizationStatus.AUTHORIZED_UNIQUE, "untrusted")

    baseline = _baseline()
    before = copy.deepcopy(baseline.to_dict())
    result = apply_gate(SOURCE, baseline, MutatingAuthorizer())
    assert result.mission is None
    assert baseline.to_dict() == before
    assert result.diagnostics["source_authorization"]["reason_code"] == "CANDIDATE_MUTATED"


def test_evidence_preserves_usage_raw_response_attempts_and_latency() -> None:
    raw = json.dumps(_payload(), ensure_ascii=False)

    class EvidenceBackend:
        name = "evidence"
        model = "shared-model"

        def complete(self, **kwargs):
            return LLMBackendResponse(raw, self.model, 0.25, 2,
                                      {"temperature": 0.0, "max_output_tokens": 3072},
                                      {"input_tokens": 200, "output_tokens": 400, "total_tokens": 600},
                                      "response-1", "completed", "completed")

    evidence = LLMSourceAuthorizationVerifier(EvidenceBackend()).authorize(SOURCE, _mission()).diagnostics
    assert evidence["raw_response"] == raw
    assert evidence["usage"]["total_tokens"] == 600
    assert evidence["attempts"] == 2
    assert evidence["provider_calls"] == 1
    assert evidence["provider_latency_s"] == 0.25
    assert evidence["latency_s"] >= 0
    assert evidence["response_id"] == "response-1"
    assert evidence["automatic_repair"] is False


def test_default_stand_duration_is_exact_compilation_semantics() -> None:
    payload = _payload(source="站立")
    payload["authorized_plan"] = [{"id": "s1", "skill": "stand", "parameters": {"duration_s": 2.0}, "depends_on": []}]
    authorizer, _ = _authorizer(payload)
    assert authorizer.authorize("站立", _mission(payload["authorized_plan"])).authorized
    payload["authorized_plan"][0]["parameters"]["duration_s"] = 4
    assert not authorizer.authorize("站立", _mission(payload["authorized_plan"])).authorized


@pytest.mark.parametrize("source", [None, "", " ", "x" * 8193])
def test_source_bounds_fail_before_provider(source) -> None:
    authorizer, backend = _authorizer(_payload())
    assert authorizer.authorize(source, _mission()).status is AuthorizationStatus.UNKNOWN
    assert backend.requests == []


def test_output_bound_fails_closed() -> None:
    authorizer, _ = _authorizer(" " * 65537)
    assert authorizer.authorize(SOURCE, _mission()).reason_code == "UNUSABLE_RESPONSE"


@pytest.mark.parametrize("provider_status,finish_reason", [("incomplete", "max_output_tokens"), ("completed", "length"), ("failed", None), ("in_progress", None), ("completed", "content_filter")])
def test_incomplete_provider_responses_are_unusable(provider_status, finish_reason) -> None:
    class IncompleteBackend:
        name = "incomplete"
        model = "test"

        def complete(self, **kwargs):
            return LLMBackendResponse(json.dumps(_payload()), self.model, 0.1, 1, {},
                                      finish_reason=finish_reason, provider_status=provider_status)

    result = LLMSourceAuthorizationVerifier(IncompleteBackend()).authorize(SOURCE, _mission())
    assert result.status is AuthorizationStatus.UNKNOWN
    assert result.reason_code == "INCOMPLETE_PROVIDER_RESPONSE"


def test_provider_model_mismatch_is_unknown() -> None:
    class WrongModelBackend:
        name = "wrong-model"
        model = "configured-model"

        def complete(self, **kwargs):
            return LLMBackendResponse(json.dumps(_payload()), "another-model", 0.1, 1, {})

    result = LLMSourceAuthorizationVerifier(WrongModelBackend()).authorize(SOURCE, _mission())
    assert result.status is AuthorizationStatus.UNKNOWN
    assert result.reason_code == "PROVIDER_MODEL_MISMATCH"


def test_success_status_without_baseline_mission_does_not_leak_success() -> None:
    authorizer, backend = _authorizer(_payload())
    result = apply_gate(SOURCE, CompilerResult(CompilerStatus.SUCCESS), authorizer)
    assert result.status is CompilerStatus.MALFORMED
    assert result.mission is None
    assert backend.requests == []
