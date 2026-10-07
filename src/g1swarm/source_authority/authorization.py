"""Independent authorization adapters around immutable guarded Direct LLM B.

Authorization is a fallible language judgement, not a proof: source coverage
is checked byte-for-byte in Python, but interpretation is still model supplied.
The source-aware treatment additionally validates a source-derived plan and
compares its complete canonical semantics with the candidate. Neither adapter
repairs the candidate, retries model output, or invokes runtime/grounding.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol

from ..language.errors import CompilerStatus, LanguageErrorCode
from ..language.result import CompilerResult
from ..llm.backend import LLMBackend, LLMBackendError, LLMConfigurationError
from ..mission.ir import MAX_MISSION_STEPS, Mission
from ..mission.validator import MissionValidator
from ..paths import resolve_repo_path
from ..simplex.canonical import canonical_document, comparison_payload
from ..simplex.structural_guard import StructuralGuard

AUTHORITY_DIMENSIONS = (
    "action_multiplicity",
    "action_order",
    "correction_scope",
    "repetition_scope",
    "reference_resolution",
    "temporal_relations",
    "unresolved_relations",
)
SEGMENT_ROLES = frozenset({"ACTION", "RELATION", "EDIT", "QUANTITY", "CONTEXT", "SEPARATOR"})
MAX_SOURCE_CHARS = 8192
MAX_OUTPUT_CHARS = 65536
MAX_EXPLANATION_CHARS = 4096
MAX_SEGMENTS = 256
STEP_KEYS = frozenset({"id", "skill", "parameters", "depends_on"})


class AuthorizationStatus(str, Enum):
    AUTHORIZED_UNIQUE = "AUTHORIZED_UNIQUE"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AuthorizationResult:
    """A judgement and audit evidence; never carries an executable Mission."""

    status: AuthorizationStatus
    reason_code: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def authorized(self) -> bool:
        return self.status is AuthorizationStatus.AUTHORIZED_UNIQUE

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "diagnostics": dict(self.diagnostics),
        }


class SourceAuthorizer(Protocol):
    treatment: str

    def authorize(self, source: str, candidate_ir: Mission | Mapping[str, Any]) -> AuthorizationResult:
        ...


class _ContractError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _ContractError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(name: str) -> None:
    raise _ContractError("NON_FINITE_NUMBER")


def _check_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise _ContractError("NON_FINITE_NUMBER")
    if isinstance(value, dict):
        for item in value.values():
            _check_finite(item)
    if isinstance(value, list):
        for item in value:
            _check_finite(item)


def _text(value: Any, *, limit: int = MAX_EXPLANATION_CHARS) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _check_steps(steps: Any) -> None:
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_MISSION_STEPS:
        raise _ContractError("INVALID_AUTHORIZED_PLAN")
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or set(step) != STEP_KEYS:
            raise _ContractError("INVALID_AUTHORIZED_PLAN")
        if step["id"] != f"s{index}":
            raise _ContractError("INVALID_AUTHORIZED_PLAN")
        dependencies = step["depends_on"]
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
            raise _ContractError("INVALID_AUTHORIZED_PLAN")
        if len(set(dependencies)) != len(dependencies):
            raise _ContractError("DUPLICATE_DEPENDENCY")
        if dependencies != ([] if index == 1 else [f"s{index - 1}"]):
            raise _ContractError("INVALID_AUTHORIZED_PLAN")
        if not isinstance(step["parameters"], dict):
            raise _ContractError("INVALID_AUTHORIZED_PLAN")


def _candidate(candidate_ir: Mission | Mapping[str, Any]) -> Mission:
    if isinstance(candidate_ir, Mission):
        # Round trip to reject malformed manually constructed typed objects,
        # while returning the original object without modifying it.
        document = candidate_ir.to_dict()
        parsed = Mission.from_dict(document)
        mission = candidate_ir
    elif isinstance(candidate_ir, Mapping):
        parsed = Mission.from_dict(candidate_ir)
        mission = parsed
    else:
        raise _ContractError("INVALID_CANDIDATE_IR")
    if any(step.execution_mode_override is not None for step in parsed.steps):
        raise _ContractError("FORBIDDEN_CANDIDATE_FIELD")
    if not MissionValidator().validate(parsed).valid:
        raise _ContractError("INVALID_CANDIDATE_IR")
    return mission


def _parse_witness(raw: str, source: str, *, source_aware: bool) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_OUTPUT_CHARS:
        raise _ContractError("UNUSABLE_RESPONSE")
    try:
        payload = json.loads(raw, object_pairs_hook=_object_pairs, parse_constant=_constant)
    except (json.JSONDecodeError, TypeError, RecursionError):
        raise _ContractError("MALFORMED_OUTPUT") from None
    _check_finite(payload)
    keys = {"status", "coverage", "dimensions"}
    if source_aware:
        keys.add("authorized_plan")
    if not isinstance(payload, dict) or set(payload) != keys:
        raise _ContractError("INVALID_AUTHORIZATION_SCHEMA")
    if payload["status"] not in {status.value for status in AuthorizationStatus}:
        raise _ContractError("INVALID_AUTHORIZATION_SCHEMA")
    coverage = payload["coverage"]
    if not isinstance(coverage, list) or not 1 <= len(coverage) <= MAX_SEGMENTS:
        raise _ContractError("INVALID_COVERAGE_SCHEMA")
    for segment in coverage:
        if not isinstance(segment, dict) or set(segment) != {"text", "role", "explanation"}:
            raise _ContractError("INVALID_COVERAGE_SCHEMA")
        if not isinstance(segment["text"], str) or not segment["text"]:
            raise _ContractError("INVALID_COVERAGE_SCHEMA")
        if segment["role"] not in SEGMENT_ROLES or not _text(segment["explanation"]):
            raise _ContractError("INVALID_COVERAGE_SCHEMA")
    # Original, unnormalized source: punctuation, whitespace, prefix, suffix,
    # negations and correction clauses must all remain represented.
    if "".join(segment["text"] for segment in coverage) != source:
        raise _ContractError("INCOMPLETE_SOURCE_COVERAGE")
    dimensions = payload["dimensions"]
    if not isinstance(dimensions, dict) or set(dimensions) != set(AUTHORITY_DIMENSIONS):
        raise _ContractError("INVALID_DIMENSION_SCHEMA")
    for item in dimensions.values():
        if not isinstance(item, dict) or set(item) != {"status", "explanation"}:
            raise _ContractError("INVALID_DIMENSION_SCHEMA")
        if item["status"] not in {"UNIQUE", "AMBIGUOUS", "UNKNOWN"} or not _text(item["explanation"]):
            raise _ContractError("INVALID_DIMENSION_SCHEMA")
    if source_aware:
        if payload["status"] == AuthorizationStatus.AUTHORIZED_UNIQUE.value:
            _check_steps(payload["authorized_plan"])
        elif payload["authorized_plan"] is not None:
            raise _ContractError("NONUNIQUE_PLAN_MUST_BE_NULL")
    return payload


class _LLMAuthorizer:
    source_aware = False
    treatment = "guarded_direct_llm_semantic_ambiguity_v1"
    default_prompt = "prompts/source_authority_ambiguity_v1.txt"

    def __init__(self, backend: LLMBackend, *, prompt_path: str | Path | None = None) -> None:
        self.backend = backend
        path = resolve_repo_path(prompt_path or self.default_prompt)
        # New Phase 2.4 files use LF byte-exact packaging; hash actual bytes.
        prompt_bytes = path.read_bytes()
        self.prompt_text = prompt_bytes.decode("utf-8")
        self.prompt_sha256 = hashlib.sha256(prompt_bytes).hexdigest()

    def authorize(self, source: str, candidate_ir: Mission | Mapping[str, Any]) -> AuthorizationResult:
        started = time.perf_counter()
        diagnostics: dict[str, Any] = {
            "treatment": self.treatment,
            "model": str(getattr(self.backend, "model", "unknown")),
            "prompt_sha256": self.prompt_sha256,
            "provider_calls": 0,
            "attempts": 0,
            "raw_response": None,
            "usage": None,
            "automatic_repair": False,
            "source_aware": self.source_aware,
        }

        def finish(status: AuthorizationStatus, reason: str) -> AuthorizationResult:
            diagnostics["latency_s"] = time.perf_counter() - started
            return AuthorizationResult(status, reason, diagnostics)

        if not isinstance(source, str) or not source.strip() or len(source) > MAX_SOURCE_CHARS:
            return finish(AuthorizationStatus.UNKNOWN, "INVALID_SOURCE_INPUT")
        diagnostics["source_sha256"] = _sha256(source)
        try:
            candidate = _candidate(candidate_ir)
            candidate_semantics = comparison_payload(candidate, allow_text_numbers=False)
        except Exception:
            return finish(AuthorizationStatus.UNKNOWN, "INVALID_CANDIDATE_IR")
        user_payload: dict[str, Any] = {"source": source}
        if self.source_aware:
            user_payload["candidate_ir"] = canonical_document(candidate, allow_text_numbers=False)
        user_text = json.dumps(user_payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        diagnostics["provider_calls"] = 1
        try:
            response = self.backend.complete(system_prompt=self.prompt_text, user_text=user_text)
        except LLMBackendError as exc:
            diagnostics.update({"attempts": exc.attempts, "backend_failure_type": exc.failure_type})
            return finish(AuthorizationStatus.UNKNOWN, "BACKEND_FAILURE")
        except LLMConfigurationError:
            diagnostics.update({"attempts": 0, "backend_failure_type": "CONFIGURATION_ERROR"})
            return finish(AuthorizationStatus.UNKNOWN, "BACKEND_FAILURE")
        except Exception as exc:
            diagnostics.update({"attempts": None, "backend_failure_type": type(exc).__name__})
            return finish(AuthorizationStatus.UNKNOWN, "BACKEND_FAILURE")
        try:
            diagnostics.update({
                "raw_response": response.text,
                "raw_response_sha256": _sha256(response.text),
                "model": response.model,
                "attempts": response.attempts,
                "provider_latency_s": response.latency_s,
                "request_parameters": dict(response.request_parameters),
                "usage": dict(response.usage) if response.usage else None,
                "response_id": response.response_id,
                "provider_status": response.provider_status,
                "finish_reason": response.finish_reason,
            })
            if response.model != str(getattr(self.backend, "model", "unknown")):
                return finish(AuthorizationStatus.UNKNOWN, "PROVIDER_MODEL_MISMATCH")
            if response.provider_status not in {None, "completed"} or response.finish_reason not in {None, "stop", "completed", "end_turn", "eos_token"}:
                return finish(AuthorizationStatus.UNKNOWN, "INCOMPLETE_PROVIDER_RESPONSE")
            payload = _parse_witness(response.text, source, source_aware=self.source_aware)
        except _ContractError as exc:
            return finish(AuthorizationStatus.UNKNOWN, exc.reason_code)
        except Exception:
            return finish(AuthorizationStatus.UNKNOWN, "UNUSABLE_RESPONSE")
        diagnostics["witness"] = payload
        diagnostics["declared_status"] = payload["status"]
        states = {item["status"] for item in payload["dimensions"].values()}
        derived_status = (
            AuthorizationStatus.AMBIGUOUS if "AMBIGUOUS" in states
            else AuthorizationStatus.UNKNOWN if "UNKNOWN" in states
            else AuthorizationStatus.AUTHORIZED_UNIQUE
        )
        if payload["status"] != derived_status.value:
            return finish(AuthorizationStatus.UNKNOWN, "VERIFIER_STATUS_DISAGREEMENT")
        if derived_status is not AuthorizationStatus.AUTHORIZED_UNIQUE:
            return finish(derived_status, "SOURCE_NOT_UNIQUE" if derived_status is AuthorizationStatus.AMBIGUOUS else "SOURCE_UNPROVEN")
        if self.source_aware:
            try:
                source_plan = Mission.from_dict({
                    "schema_version": "2.0.0", "mission_id": "source-authorized-plan",
                    "steps": payload["authorized_plan"],
                })
                validation = MissionValidator().validate(source_plan)
                diagnostics["authorized_plan_validation"] = validation.to_dict()
                if not validation.valid:
                    return finish(AuthorizationStatus.UNKNOWN, "INVALID_AUTHORIZED_PLAN")
                plan_semantics = comparison_payload(source_plan, allow_text_numbers=False)
                diagnostics["plan_matches_candidate"] = plan_semantics == candidate_semantics
                if plan_semantics != candidate_semantics:
                    return finish(AuthorizationStatus.UNKNOWN, "AUTHORIZED_PLAN_DISAGREEMENT")
            except Exception:
                return finish(AuthorizationStatus.UNKNOWN, "INVALID_AUTHORIZED_PLAN")
        return finish(AuthorizationStatus.AUTHORIZED_UNIQUE, "UNIQUE_SOURCE_AUTHORITY")


class LLMSemanticAmbiguityGate(_LLMAuthorizer):
    """Source-only semantic uniqueness judgement; cannot detect candidate drift."""


class LLMSourceAuthorizationVerifier(_LLMAuthorizer):
    """Whole-source judgement plus deterministic exact source-plan comparison."""

    source_aware = True
    treatment = "guarded_direct_llm_source_authority_v1"
    default_prompt = "prompts/source_authority_verifier_v1.txt"


def source_authorization(
    source: str, candidate_ir: Mission | Mapping[str, Any], *, authorizer: SourceAuthorizer,
) -> AuthorizationResult:
    """Fail-closed public boundary, including custom authorizer exceptions."""
    try:
        result = authorizer.authorize(source, candidate_ir)
        if not isinstance(result, AuthorizationResult) or not isinstance(result.status, AuthorizationStatus):
            raise TypeError("authorizer returned an invalid result")
        return result
    except Exception as exc:
        return AuthorizationResult(AuthorizationStatus.UNKNOWN, "AUTHORIZER_FAILURE", {
            "backend_failure_type": type(exc).__name__, "provider_calls": None,
        })


def apply_gate(source: str, baseline_result: CompilerResult, authorizer: SourceAuthorizer) -> CompilerResult:
    """Release exactly B's candidate iff Guard, IR legality and authority pass.

    The original B result remains intact for replay/comparison. Rejected gated
    results always have mission=None. Evidence may contain raw model output,
    which is never treated as an executable Mission object.
    """
    diagnostics = dict(baseline_result.diagnostics)
    diagnostics["architecture"] = authorizer.treatment
    diagnostics["baseline_status"] = baseline_result.status.value
    guard = StructuralGuard().check(source)
    diagnostics["release_guard"] = guard.to_dict()
    if not guard.passed:
        authority = AuthorizationResult(AuthorizationStatus.UNKNOWN, "GUARD_REJECT", {"provider_calls": 0})
    elif not baseline_result.success:
        authority = AuthorizationResult(AuthorizationStatus.UNKNOWN, "NO_LEGAL_CANDIDATE", {"provider_calls": 0})
    else:
        try:
            candidate = _candidate(baseline_result.mission)
            before = canonical_document(candidate, allow_text_numbers=False)
            diagnostics["release_validation"] = MissionValidator().validate(candidate).to_dict()
            # Pass a detached data copy across the authorization boundary. Even
            # an erroneous custom authorizer cannot change immutable B evidence.
            authorization_candidate = Mission.from_dict(before)
            authority = source_authorization(source, authorization_candidate, authorizer=authorizer)
            if canonical_document(authorization_candidate, allow_text_numbers=False) != before:
                authority = AuthorizationResult(AuthorizationStatus.UNKNOWN, "CANDIDATE_MUTATED", authority.diagnostics)
        except Exception:
            authority = AuthorizationResult(AuthorizationStatus.UNKNOWN, "INVALID_CANDIDATE_IR", {"provider_calls": 0})
    diagnostics["source_authorization"] = authority.to_dict()
    diagnostics["released_executable"] = authority.authorized
    if authority.authorized:
        return CompilerResult(CompilerStatus.SUCCESS, baseline_result.mission, baseline_result.normalized_text, diagnostics=diagnostics)
    if baseline_result.status is not CompilerStatus.SUCCESS and guard.passed:
        return CompilerResult(baseline_result.status, None, baseline_result.normalized_text,
                              baseline_result.error_code, baseline_result.error_message, diagnostics)
    status = CompilerStatus.AMBIGUOUS if authority.status is AuthorizationStatus.AMBIGUOUS else CompilerStatus.MALFORMED
    code = LanguageErrorCode.AMBIGUOUS_COMMAND if status is CompilerStatus.AMBIGUOUS else LanguageErrorCode.LLM_OUTPUT_INVALID
    return CompilerResult(status, None, baseline_result.normalized_text, code,
                          f"source authorization withheld executable Mission: {authority.reason_code}", diagnostics)
