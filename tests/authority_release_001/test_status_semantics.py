"""Offline public result semantics; no model, provider or Runtime acquisition."""
from __future__ import annotations

import copy
import json

import pytest

from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer
from g1swarm.authority_release_001 import begin_release_request
from g1swarm.authority_mechanism_001.contract import AuthorityService
from g1swarm.language import LanguageCompiler
from g1swarm.language.errors import CompilerStatus, LanguageErrorCode
from g1swarm.language.result import CompilerResult
from g1swarm.llm.backend import LLMBackendError, LLMBackendResponse, LLMConfigurationError
from g1swarm.llm.compiler import FROZEN_STATUSES
from g1swarm.source_authority import AuthorizationResult, AuthorizationStatus, apply_gate
from g1swarm.source_authority.authorization import apply_gate as direct_gate
from g1swarm.source_authority_bounded import BoundedSourceAuthorizationVerifier

SOURCE = "站立2秒然后停止"


@pytest.fixture(params=[apply_gate, direct_gate], ids=["package", "module"])
def gate(request):
    return request.param


class Proposal:
    treatment = "offline-semantic-result-fixture"

    def __init__(self, status, reason, diagnostics=None):
        self.result = AuthorizationResult(status, reason, diagnostics or {})

    def authorize(self, source, candidate):
        return self.result


def baseline():
    result = LanguageCompiler().compile(SOURCE)
    assert result.success
    return result


def test_missing_independent_authority_is_clarification_not_malformed(gate):
    original = baseline()
    before = copy.deepcopy(original.to_dict())
    result = gate(SOURCE, original, BoundedSourceAuthorizationVerifier(), derive_bounded_authority=False)
    assert result.status is CompilerStatus.AMBIGUOUS
    assert result.error_code is LanguageErrorCode.AUTHORITY_UNRESOLVED
    assert result.diagnostics["release_outcome"] == "AUTHORITY_UNRESOLVED"
    assert result.diagnostics["clarification_required"]
    assert result.diagnostics["source_authorization"]["reason_code"] == "AUTHORITY_UNESTABLISHED_CLARIFICATION_REQUIRED"
    assert result.mission is None and not result.success
    assert original.to_dict() == before
    assert result.to_dict()["error_code"] == "AUTHORITY_UNRESOLVED"


@pytest.mark.parametrize("state,reason,status,code,outcome", [
    ("AMBIGUOUS", "SEMANTIC_AMBIGUOUS", "AMBIGUOUS", "AMBIGUOUS_COMMAND", "SEMANTIC_AMBIGUITY"),
    ("UNKNOWN", "SEMANTIC_UNKNOWN", "AMBIGUOUS", "AUTHORITY_UNRESOLVED", "AUTHORITY_UNRESOLVED"),
    ("UNKNOWN", "SOURCE_UNPROVEN", "AMBIGUOUS", "AUTHORITY_UNRESOLVED", "AUTHORITY_UNRESOLVED"),
    ("UNKNOWN", "MALFORMED_CERTIFICATE_RESPONSE", "MALFORMED", "LLM_OUTPUT_INVALID", "MODEL_OUTPUT_MALFORMED"),
    ("UNKNOWN", "INVALID_CERTIFICATE_PLAN", "MALFORMED", "LLM_OUTPUT_INVALID", "MODEL_OUTPUT_MALFORMED"),
    ("UNKNOWN", "CERTIFICATE_STATUS_DISAGREEMENT", "MALFORMED", "LLM_OUTPUT_INVALID", "MODEL_OUTPUT_MALFORMED"),
    ("UNKNOWN", "AUTHORIZED_PLAN_DISAGREEMENT", "UNSUPPORTED", "AUTHORITY_DENIED", "AUTHORITY_DENIED"),
    ("UNKNOWN", "INCOMPLETE_PROVIDER_RESPONSE", "MALFORMED", "LLM_API_ERROR", "BACKEND_FAILURE"),
    ("UNKNOWN", "PROVIDER_MODEL_MISMATCH", "MALFORMED", "LLM_API_ERROR", "BACKEND_FAILURE"),
])
def test_public_result_families_are_not_collapsed(gate, state, reason, status, code, outcome):
    result = gate(SOURCE, baseline(), Proposal(AuthorizationStatus(state), reason))
    assert result.status.value == status and result.error_code.value == code
    assert result.diagnostics["release_outcome"] == outcome
    assert result.diagnostics["clarification_required"] == (outcome == "AUTHORITY_UNRESOLVED")
    assert result.mission is None


@pytest.mark.parametrize("error,code", [
    (LLMBackendError("TIMEOUT", "offline timeout", attempts=1), LanguageErrorCode.LLM_TIMEOUT),
    (LLMBackendError("API_ERROR", "offline backend failure", attempts=1), LanguageErrorCode.LLM_API_ERROR),
    (LLMConfigurationError("offline configuration"), LanguageErrorCode.LLM_CONFIGURATION_ERROR),
    (RuntimeError("offline unexpected failure"), LanguageErrorCode.LLM_API_ERROR),
])
def test_real_issuer_failure_path_preserves_backend_category(gate, error, code):
    class FailingFixture:
        name, model = "offline-only", "offline-only"
        def complete(self, **kwargs):
            raise error
    result = gate(SOURCE, baseline(), SourceAuthorityCertificateIssuer(FailingFixture()))
    assert result.error_code is code and result.diagnostics["release_outcome"] == "BACKEND_FAILURE"
    assert not result.diagnostics["clarification_required"] and result.mission is None


def test_custom_authorizer_failure_is_backend_failure(gate):
    class Broken:
        treatment = "offline-broken"
        def authorize(self, source, candidate):
            raise ValueError("offline fixture")
    result = gate(SOURCE, baseline(), Broken())
    assert result.error_code is LanguageErrorCode.LLM_API_ERROR
    assert result.diagnostics["release_outcome"] == "BACKEND_FAILURE"


def test_explicit_bad_receipt_is_denied_without_fallback(gate):
    context = begin_release_request(SOURCE)
    service = AuthorityService()
    receipt = service.derive_bounded_receipt(SOURCE, context.context_id)
    receipt["signature"] = "0" * 64
    result = gate(SOURCE, baseline(), BoundedSourceAuthorizationVerifier(), request_context=context,
                  authority_service=service, authority_receipt=receipt)
    assert result.status is CompilerStatus.UNSUPPORTED and result.error_code is LanguageErrorCode.AUTHORITY_DENIED
    assert result.diagnostics["release_outcome"] == "AUTHORITY_DENIED"
    assert result.diagnostics["source_authorization"]["reason_code"] == "UNVERIFIED_AUTHORITY_PROVENANCE"
    assert not result.diagnostics["clarification_required"] and result.mission is None


def test_positive_returns_original_B_and_model_only_does_not(gate):
    original = baseline()
    released = gate(SOURCE, original, BoundedSourceAuthorizationVerifier())
    assert released.mission is original.mission and released.success
    assert released.diagnostics["release_outcome"] == "AUTHORIZED_RELEASE"
    denied = gate(SOURCE, original, Proposal(AuthorizationStatus.AUTHORIZED_UNIQUE, "MODEL_APPROVED"))
    assert denied.mission is None and denied.error_code is LanguageErrorCode.AUTHORITY_DENIED


def test_source_guard_is_source_malformed_not_authority_unknown(gate):
    result = gate("然后前进6米", baseline(), Proposal(AuthorizationStatus.AUTHORIZED_UNIQUE, "MODEL_APPROVED"))
    assert result.status is CompilerStatus.MALFORMED
    assert result.error_code is LanguageErrorCode.LANGUAGE_PARSE_ERROR
    assert result.diagnostics["release_outcome"] == "SOURCE_MALFORMED"


@pytest.mark.parametrize("status,code", [
    (CompilerStatus.MALFORMED, LanguageErrorCode.LLM_TIMEOUT),
    (CompilerStatus.MALFORMED, LanguageErrorCode.LLM_OUTPUT_INVALID),
    (CompilerStatus.AMBIGUOUS, LanguageErrorCode.AMBIGUOUS_COMMAND),
    (CompilerStatus.UNSUPPORTED, LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY),
])
def test_baseline_rejection_contract_is_preserved(gate, status, code):
    original = CompilerResult(status, normalized_text=SOURCE, error_code=code, error_message="existing baseline")
    result = gate(SOURCE, original, BoundedSourceAuthorizationVerifier())
    assert (result.status, result.error_code, result.error_message) == (status, code, original.error_message)
    assert result.mission is None


def test_no_frozen_model_status_schema_extension():
    assert FROZEN_STATUSES == ("SUCCESS", "AMBIGUOUS", "UNSUPPORTED", "MALFORMED")
    assert apply_gate is direct_gate


@pytest.mark.parametrize("code,status,outcome", [
    (LanguageErrorCode.AUTHORITY_UNRESOLVED, CompilerStatus.AMBIGUOUS, "AUTHORITY_UNRESOLVED"),
    (LanguageErrorCode.AUTHORITY_DENIED, CompilerStatus.UNSUPPORTED, "AUTHORITY_DENIED"),
])
def test_regating_withheld_result_preserves_its_authority_semantics(gate, code, status, outcome):
    class NoInvocation:
        treatment = "never-called-fixture"
        def authorize(self, source, candidate):
            pytest.fail("A withheld baseline must not invoke an authorizer")
    original = CompilerResult(status, normalized_text=SOURCE, error_code=code,
                              error_message="retained authority refusal")
    result = gate(SOURCE, original, NoInvocation())
    assert (result.status, result.error_code, result.error_message) == (status, code, original.error_message)
    assert result.diagnostics["release_outcome"] == outcome
    assert result.diagnostics["clarification_required"] == (outcome == "AUTHORITY_UNRESOLVED")
    assert result.mission is None
